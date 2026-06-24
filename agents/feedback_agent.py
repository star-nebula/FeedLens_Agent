"""
反馈 Agent — 反馈处理 + 偏好向量更新（异步，单次执行）。

工作流: record_feedback → update_preference → vector_add → cleanup_preference

通过 threading.Thread 异步执行，不阻塞主 Agent。

核心算法：
  - EMA 更新: v_new = α * v_current + (1-α) * v_feedback
  - 偏好正负分离: v_like / v_dislike 分别存储
  - feedback_bias: like+0.15, dislike-0.10, irrelevant-0.15
  - 自动清理: 权重 < 0.1 的偏好项被移除
"""

import json
import threading
import numpy as np
from datetime import datetime
from langgraph.graph import StateGraph, END
from agents.state import FeedLensState
from models.database import Database
from models.vector_store import VectorStore


# ============================================================
# 配置
# ============================================================

EMA_ALPHA = 0.3
FEEDBACK_BIAS = {"like": 0.15, "dislike": -0.10, "irrelevant": -0.15}
MIN_PREFERENCE_WEIGHT = 0.1  # P1: 可通过 ranking.preference_cleanup_threshold 覆盖


# ============================================================
# 辅助函数
# ============================================================

def _get_db() -> Database:
    """获取数据库实例。"""
    return Database("data/feedlens.db")


def _get_vector_store() -> VectorStore:
    """获取向量存储实例。"""
    try:
        from utils.embedding import EmbeddingModel
        emb_model = EmbeddingModel()
        return VectorStore("data/chroma", embedding_fn=emb_model.encode)
    except Exception:
        return VectorStore("data/chroma")


def _compute_preference_weight(feedback_type: str, count: int) -> float:
    """计算偏好权重。

    Args:
        feedback_type: like / dislike / irrelevant
        count: 该关键词的反馈次数

    Returns:
        权重值（[-1, 1]）
    """
    base_bias = FEEDBACK_BIAS.get(feedback_type, 0.0)
    # 反馈次数越多，权重绝对值越大（但有上限）
    magnitude = min(count * 0.15, 0.8)
    if feedback_type == "like":
        return min(1.0, base_bias + magnitude)
    else:
        return max(-1.0, base_bias - magnitude)


# ============================================================
# 节点定义
# ============================================================


def record_feedback_node(state: FeedLensState) -> dict:
    """将用户反馈写入 SQLite feedback 表。

    Args:
        state: 包含 user_id, item_id, feedback_type
    """
    user_id = state.get("user_id", 1)
    item_id = state.get("item_id")
    brief_id = state.get("brief_id")
    feedback_type = state.get("feedback_type", "like")

    if not item_id:
        print("[record_feedback] 缺少 item_id", flush=True)
        return {}

    db = _get_db()
    try:
        with db.get_connection() as conn:
            conn.execute(
                """INSERT INTO feedback (user_id, brief_id, item_id, feedback_type)
                   VALUES (?, ?, ?, ?)""",
                (user_id, brief_id, item_id, feedback_type),
            )
        print(f"[record_feedback] 记录反馈: user_id={user_id}, item_id={item_id}, type={feedback_type}", flush=True)
        return {"feedback_recorded": True}
    except Exception as e:
        print(f"[record_feedback] 写入失败: {e}", flush=True)
        return {"feedback_recorded": False, "error": str(e)}


def update_preference_node(state: FeedLensState) -> dict:
    """EMA 更新用户偏好向量 (v_like / v_dislike)。

    偏好正负分离存储于 ChromaDB user_preference 集合。

    更新算法:
      - v_like_new = α * v_like_current + (1-α) * v_feedback (for like)
      - v_dislike_new = α * v_dislike_current + (1-α) * v_feedback (for dislike)
      - feedback_bias 作为时序互补，调整关键词权重
    """
    user_id = state.get("user_id", 1)
    item_id = state.get("item_id")
    feedback_type = state.get("feedback_type", "like")

    if not item_id:
        print("[update_preference] 缺少 item_id", flush=True)
        return {}

    db = _get_db()
    vs = _get_vector_store()

    # 获取条目信息
    item_info = {}
    try:
        with db.get_connection() as conn:
            cursor = conn.execute(
                """SELECT ri.title, ri.summary, di.keywords, di.category
                   FROM deduped_items di
                   JOIN raw_items ri ON di.representative_item_id = ri.id
                   WHERE di.id = ?""",
                (item_id,),
            )
            row = cursor.fetchone()
            if row:
                item_info = dict(row)
    except Exception as e:
        print(f"[update_preference] 查询条目失败: {e}", flush=True)
        return {}

    if not item_info:
        print(f"[update_preference] 条目 {item_id} 不存在", flush=True)
        return {}

    # 提取关键词（从条目或手动指定）
    keywords = []
    if state.get("keywords"):
        keywords = state["keywords"]
    elif item_info.get("keywords"):
        try:
            keywords = json.loads(item_info["keywords"])
        except json.JSONDecodeError:
            keywords = [item_info["keywords"]]

    # 如果没有关键词，从标题和摘要提取
    if not keywords:
        text = f"{item_info.get('title', '')} {item_info.get('summary', '')}"
        # 简单分词：取前5个中文词
        import re
        words = re.findall(r'[\u4e00-\u9fff]{2,}', text)[:5]
        keywords = words

    if not keywords:
        print(f"[update_preference] 无法提取关键词", flush=True)
        return {}

    print(f"[update_preference] 提取关键词: {keywords}", flush=True)

    # 获取当前偏好向量
    current_like = _get_preference_vector(vs, user_id, "like")
    current_dislike = _get_preference_vector(vs, user_id, "dislike")

    # 生成反馈向量（使用关键词的嵌入）
    feedback_vector = _generate_keyword_vector(vs, keywords)

    # EMA 更新
    new_like = current_like
    new_dislike = current_dislike

    if feedback_type == "like":
        new_like = EMA_ALPHA * np.array(current_like) + (1 - EMA_ALPHA) * np.array(feedback_vector)
    elif feedback_type in ["dislike", "irrelevant"]:
        new_dislike = EMA_ALPHA * np.array(current_dislike) + (1 - EMA_ALPHA) * np.array(feedback_vector)

    new_like = new_like.tolist() if hasattr(new_like, "tolist") else list(new_like)
    new_dislike = new_dislike.tolist() if hasattr(new_dislike, "tolist") else list(new_dislike)

    # 更新 SQLite user_preferences 表（关键词级别）
    for keyword in keywords:
        _update_keyword_preference(db, user_id, keyword, feedback_type)

    print(f"[update_preference] EMA 更新完成: like_norm={np.linalg.norm(new_like):.4f}, "
          f"dislike_norm={np.linalg.norm(new_dislike):.4f}", flush=True)

    return {
        "preference_updated": True,
        "v_like": new_like,
        "v_dislike": new_dislike,
        "keywords": keywords,
    }


def _get_preference_vector(vs: VectorStore, user_id: int, pref_type: str) -> list:
    """获取用户当前偏好向量（v_like 或 v_dislike）。"""
    try:
        results = vs.client.get_or_create_collection(
            vs.COLLECTION_USER_PREF,
            embedding_function=vs.chroma_embedding_fn,
        ).query(
            query_texts=[f"user_{user_id}_{pref_type}"],
            n_results=1,
            where={"user_id": user_id, "pref_type": pref_type},
        )
        if results["ids"] and results["ids"][0]:
            return results["embeddings"][0][0] if results["embeddings"] else []
    except Exception:
        pass
    # 默认零向量（384维）
    return [0.0] * 384


def _generate_keyword_vector(vs: VectorStore, keywords: list) -> list:
    """生成关键词的嵌入向量。"""
    if not keywords:
        return [0.0] * 384
    try:
        text = " ".join(keywords)
        if vs.chroma_embedding_fn:
            return vs.chroma_embedding_fn([text])[0]
        # 降级：随机向量
        return np.random.randn(384).tolist()
    except Exception:
        return np.random.randn(384).tolist()


def _update_keyword_preference(db: Database, user_id: int, keyword: str, feedback_type: str):
    """更新关键词级别的偏好（带 feedback_bias）。"""
    try:
        with db.get_connection() as conn:
            # 查询当前记录
            cursor = conn.execute(
                "SELECT id, weight, feedback_count FROM user_preferences WHERE user_id = ? AND keyword = ?",
                (user_id, keyword),
            )
            row = cursor.fetchone()

            if row:
                # 更新现有记录
                current_count = row["feedback_count"] or 0
                new_count = current_count + 1
                weight = _compute_preference_weight(feedback_type, new_count)
                conn.execute(
                    """UPDATE user_preferences SET weight = ?, feedback_count = ?, updated_at = ?
                       WHERE id = ?""",
                    (weight, new_count, datetime.now(), row["id"]),
                )
            else:
                # 插入新记录
                weight = _compute_preference_weight(feedback_type, 1)
                conn.execute(
                    """INSERT INTO user_preferences (user_id, keyword, weight, feedback_count)
                       VALUES (?, ?, ?, ?)""",
                    (user_id, keyword, weight, 1),
                )
    except Exception as e:
        print(f"[update_preference] 更新关键词偏好失败: {e}", flush=True)


def vector_add_node(state: FeedLensState) -> dict:
    """将更新后的偏好向量写回 ChromaDB。"""
    user_id = state.get("user_id", 1)
    v_like = state.get("v_like")
    v_dislike = state.get("v_dislike")

    if not v_like or not v_dislike:
        print("[vector_add] 缺少偏好向量", flush=True)
        return {}

    vs = _get_vector_store()
    collection = vs.client.get_or_create_collection(
        vs.COLLECTION_USER_PREF,
        embedding_function=vs.chroma_embedding_fn,
    )

    try:
        # 更新或插入 v_like
        collection.upsert(
            ids=[f"user_{user_id}_like"],
            embeddings=[v_like],
            metadatas=[{"user_id": user_id, "pref_type": "like", "updated_at": datetime.now().isoformat()}],
            documents=[f"User {user_id} positive preferences"],
        )

        # 更新或插入 v_dislike
        collection.upsert(
            ids=[f"user_{user_id}_dislike"],
            embeddings=[v_dislike],
            metadatas=[{"user_id": user_id, "pref_type": "dislike", "updated_at": datetime.now().isoformat()}],
            documents=[f"User {user_id} negative preferences"],
        )

        print(f"[vector_add] 偏好向量已写入 ChromaDB: user_id={user_id}", flush=True)
        return {"vector_added": True}
    except Exception as e:
        print(f"[vector_add] 写入失败: {e}", flush=True)
        return {"vector_added": False, "error": str(e)}


def cleanup_preference_node(state: FeedLensState) -> dict:
    """自动清理低权重偏好项（权重 < 0.1）。"""
    user_id = state.get("user_id", 1)

    db = _get_db()
    try:
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT id, keyword, weight FROM user_preferences WHERE user_id = ? AND ABS(weight) < ?",
                (user_id, MIN_PREFERENCE_WEIGHT),
            )
            rows = cursor.fetchall()
            removed_count = 0
            for row in rows:
                conn.execute("DELETE FROM user_preferences WHERE id = ?", (row["id"],))
                removed_count += 1

        print(f"[cleanup_preference] 清理完成: 移除 {removed_count} 个低权重偏好项", flush=True)
        return {"cleanup_done": True, "removed_count": removed_count}
    except Exception as e:
        print(f"[cleanup_preference] 清理失败: {e}", flush=True)
        return {"cleanup_done": False, "error": str(e)}


# ============================================================
# StateGraph 构建
# ============================================================


def build_feedback_agent() -> StateGraph:
    """构建反馈 Agent StateGraph（单次执行，无循环）。"""
    workflow = StateGraph(FeedLensState)

    workflow.add_node("record_feedback", record_feedback_node)
    workflow.add_node("update_preference", update_preference_node)
    workflow.add_node("vector_add", vector_add_node)
    workflow.add_node("cleanup_preference", cleanup_preference_node)

    workflow.set_entry_point("record_feedback")
    workflow.add_edge("record_feedback", "update_preference")
    workflow.add_edge("update_preference", "vector_add")
    workflow.add_edge("vector_add", "cleanup_preference")
    workflow.add_edge("cleanup_preference", END)

    return workflow.compile()


# ============================================================
# 异步执行封装
# ============================================================


def process_feedback_async(user_id: int, item_id: int, feedback_type: str, **kwargs):
    """异步处理用户反馈（不阻塞主 Agent）。

    Args:
        user_id: 用户 ID
        item_id: 反馈的条目 ID
        feedback_type: like / dislike / irrelevant
        **kwargs: 其他参数（brief_id, keywords 等）
    """
    def _run():
        try:
            graph = build_feedback_agent()
            initial_state = {
                "user_id": user_id,
                "item_id": item_id,
                "feedback_type": feedback_type,
                **kwargs,
            }
            result = graph.invoke(initial_state)
            print(f"[feedback_async] 异步处理完成: {result}", flush=True)
        except Exception as e:
            print(f"[feedback_async] 异步处理失败: {e}", flush=True)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"status": "started", "thread_id": thread.ident}


def process_feedback_sync(user_id: int, item_id: int, feedback_type: str, **kwargs) -> dict:
    """同步处理用户反馈（返回结果）。"""
    graph = build_feedback_agent()
    initial_state = {
        "user_id": user_id,
        "item_id": item_id,
        "feedback_type": feedback_type,
        **kwargs,
    }
    return graph.invoke(initial_state)
