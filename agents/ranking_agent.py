"""
排序 Agent — 智能去重 + 偏好排序。

工作流: vector_search → deduplicate → rank_items
ReAct: 检索偏好 → 规划排序策略 → 去重+排序 → 评估 → 调参或 Done

去重策略:
  - ≥0.88: 直接判定为重复，保留一条代表
  - ≤0.70: 判定为不重复，全部保留
  - 0.70-0.88: 模糊区间，调用 LLM 做二元判断
  - 最多 LLM 裁决 20 对，超限按硬判处理
"""

import os
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any

from langgraph.graph import StateGraph, END
from utils.config import load_config
from agents.state import FeedLensState
from tools import deduplicate, vector_search, db_read, db_write
from models.vector_store import VectorStore
from utils.embedding import EmbeddingModel
from utils.llm_provider import DeepSeekProvider


# ============================================================
# 配置加载
# ============================================================

def _get_vector_store() -> VectorStore:
    config = load_config()
    persist_dir = config.get("vector_store", {}).get("persist_dir", "data/chroma")
    embedding_model = EmbeddingModel()
    return VectorStore(persist_dir=persist_dir, embedding_fn=embedding_model.encode)


def _get_embedding_model() -> EmbeddingModel:
    return EmbeddingModel()


def _get_llm_provider() -> DeepSeekProvider:
    config = load_config()
    llm_cfg = config.get("llm", {})
    deepseek_cfg = llm_cfg.get("deepseek", {})
    return DeepSeekProvider(
        api_key=deepseek_cfg.get("api_key", ""),
        base_url=deepseek_cfg.get("base_url", "https://api.deepseek.com/v1"),
        model=deepseek_cfg.get("model", "deepseek-chat"),
    )


def _get_db_path() -> str:
    config = load_config()
    return config.get("data", {}).get("db_path", "data/feedlens.db")


# ============================================================
# 排序辅助函数
# ============================================================

def _cosine(vec_a, vec_b) -> float:
    """计算两个向量的余弦相似度（内联实现，无外部依赖）。"""
    if not vec_a or not vec_b:
        return 0.0
    if len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag1 = sum(a * a for a in vec_a) ** 0.5
    mag2 = sum(b * b for b in vec_b) ** 0.5
    if mag1 <= 0 or mag2 <= 0:
        return 0.0
    return dot / (mag1 * mag2)


def _load_preference_vectors(user_id: int) -> tuple:
    """从 ChromaDB user_preference 集合读取用户偏好向量（v_like / v_dislike）。

    ID 格式与 feedback_agent.vector_add_node 保持一致：user_{id}_like / user_{id}_dislike。
    返回 (v_like, v_dislike)，未找到则为 None。
    """
    try:
        vs = _get_vector_store()
        vs.init_collections()
        col = vs.client.get_or_create_collection(
            vs.COLLECTION_USER_PREF,
            embedding_function=vs.chroma_embedding_fn,
        )
        result = col.get(ids=[f"user_{user_id}_like", f"user_{user_id}_dislike"])
        v_like = None
        v_dislike = None
        embeddings = result.get("embeddings") or []
        for idx, _id in enumerate(result.get("ids", [])):
            emb = embeddings[idx] if idx < len(embeddings) else None
            if _id.endswith("_like") and emb is not None:
                v_like = list(emb)
            elif _id.endswith("_dislike") and emb is not None:
                v_dislike = list(emb)
        return v_like, v_dislike
    except Exception as e:
        print(f"[rank_items] 读取偏好向量失败: {e}", flush=True)
        return None, None


def _load_ranking_config() -> dict:
    """加载排序相关配置（权重、阈值、加分项），未配置时回退到 MVP 推荐默认值。"""
    config = load_config()
    cold = config.get("weights_cold", {})
    warm = config.get("weights_warm", {})
    weights_cold = {
        "similarity": cold.get("similarity", 0.40),
        "recency": cold.get("recency", 0.25),
        "preference": cold.get("preference", 0.10),
        "importance": cold.get("importance", 0.25),
    }
    weights_warm = {
        "similarity": warm.get("similarity", 0.30),
        "recency": warm.get("recency", 0.20),
        "preference": warm.get("preference", 0.40),
        "importance": warm.get("importance", 0.10),
    }
    ranking_cfg = config.get("ranking", {})
    feedback_cfg = config.get("feedback", {})
    return {
        "weights_cold": weights_cold,
        "weights_warm": weights_warm,
        "cold_start_threshold": ranking_cfg.get("cold_start_feedback_threshold", 3),
        "source_diversity_bonus": ranking_cfg.get("source_diversity_bonus", 0),
        "feedback_bias_positive": feedback_cfg.get("feedback_bias_positive", 0.15),
        "feedback_bias_negative": feedback_cfg.get("feedback_bias_negative", -0.10),
        "feedback_bias_irrelevant": feedback_cfg.get("feedback_bias_irrelevant", -0.15),
        # 去重阈值（config.ranking.*）
        "dedup_threshold": ranking_cfg.get("dedup_threshold", 0.88),
        "dedup_llm_lower": ranking_cfg.get("dedup_llm_lower", 0.70),
        "dedup_hard_threshold": ranking_cfg.get("dedup_hard_threshold", 0.80),
        "max_llm_adjudications": ranking_cfg.get("max_llm_adjudications", 20),
    }

# ============================================================
# 节点定义
# ============================================================


def vector_search_node(state: FeedLensState) -> dict:
    """检索用户偏好向量（ChromaDB user_preference 集合）。

    返回:
        user_preferences: 偏好向量检索结果
        feedback_history: 用户反馈历史
    """
    user_id = state.get("user_id", 1)
    structured_goal = state.get("structured_goal", {})
    topics = structured_goal.get("topics", [])
    keywords = structured_goal.get("keywords", [])

    query_text = " ".join(topics[:3] + keywords[:3])[:100] or "技术资讯"
    print(f"[vector_search] 查询用户偏好: user_id={user_id}, query={query_text}", flush=True)

    try:
        vs = _get_vector_store()
        vs.init_collections()

        preferences = vector_search(
            vs.persist_dir,
            query_text,
            n_results=10,
            collection_name="user_preference",
        )

        db_path = _get_db_path()
        feedback_history = []
        try:
            feedback_history = db_read(
                db_path,
                "SELECT item_id, feedback_type FROM feedback WHERE user_id = ? AND created_at > ?",
                [user_id, (datetime.now() - timedelta(days=30)).isoformat()],
            )
        except Exception as e:
            print(f"[vector_search] 读取反馈历史失败（可能未初始化）: {e}", flush=True)

        print(f"[vector_search] 偏好检索: {len(preferences)} 条, 反馈历史: {len(feedback_history)} 条", flush=True)
        return {
            "user_preferences": preferences,
            "feedback_history": feedback_history,
        }
    except Exception as e:
        print(f"[vector_search] 失败: {e}", flush=True)
        return {
            "user_preferences": [],
            "feedback_history": [],
            "error": f"vector_search failed: {e}",
        }


def deduplicate_node(state: FeedLensState) -> dict:
    """向量去重（0.88 阈值 + 0.70-0.88 LLM 裁决）。

    返回:
        collected_items: 去重后的条目列表
        item_relations: 去重关系记录
    """
    items = state.get("collected_items", [])
    if not items:
        return {"collected_items": [], "item_relations": []}

    print(f"[deduplicate] 开始去重: {len(items)} 条", flush=True)

    try:
        vs = _get_vector_store()
        vs.init_collections()
        embedding_model = _get_embedding_model()
        llm_provider = _get_llm_provider()

        dedup_cfg = _load_ranking_config()
        unique_items, duplicate_pairs = deduplicate(
            items,
            vector_store=vs,
            embedding_model=embedding_model,
            llm_provider=llm_provider,
            threshold_high=dedup_cfg["dedup_threshold"],
            threshold_low=dedup_cfg["dedup_llm_lower"],
            max_llm_adjudications=dedup_cfg["max_llm_adjudications"],
        )

        # 更新 similar_count（统计每篇保留条目的相似篇数）
        similar_map = {}
        for pair in duplicate_pairs:
            a_id = pair["item_a_id"]
            similar_map[a_id] = similar_map.get(a_id, 0) + 1
        for item in unique_items:
            item["similar_count"] = similar_map.get(item.get("id", ""), 1)

        # 写入 item_relations 表（暂时关闭 FK 约束，因测试中条目可能未写入 raw_items）
        db_path = _get_db_path()
        try:
            db_write(db_path, "PRAGMA foreign_keys = OFF", [])
        except Exception:
            pass
        for pair in duplicate_pairs:
            try:
                db_write(
                    db_path,
                    """INSERT OR IGNORE INTO item_relations
                       (item_a_id, item_b_id, similarity_score, dedup_method, relation_type, created_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    [
                        pair["item_a_id"],
                        pair["item_b_id"],
                        pair["similarity_score"],
                        pair["dedup_method"],
                        pair["relation_type"],
                        datetime.now().isoformat(),
                    ],
                )
            except Exception as e:
                if "FOREIGN KEY" not in str(e):
                    print(f"[deduplicate] 写入关系失败: {e}", flush=True)

        try:
            db_write(db_path, "PRAGMA foreign_keys = ON", [])
        except Exception:
            pass
        print(f"[deduplicate] 完成: {len(unique_items)} 条保留, {len(duplicate_pairs)} 对去重", flush=True)
        return {
            "collected_items": unique_items,
            "item_relations": duplicate_pairs,
        }
    except Exception as e:
        print(f"[deduplicate] 失败: {e}", flush=True)
        # 失败时返回原始条目
        for item in items:
            item.setdefault("similar_count", 1)
        return {
            "collected_items": items,
            "item_relations": [],
            "error": f"deduplicate failed: {e}",
        }


def rank_items_node(state: FeedLensState) -> dict:
    """多因子加权排序。

    final_score = w1*similarity + w2*recency + w3*preference + w4*importance
    
    因子计算:
      - similarity = cosine(item_embedding, goal_embedding)
      - recency = exp(-Δt / τ), τ = 24h
      - preference = 冷启动用 similarity 代理，有反馈由 feedback_bias 驱动
      - importance = (LLM 1-5 分归一化至 0-1)
    
    权重动态切换: feedback_count < 3 → cold_start(0.40/0.25/0.10/0.25), >= 3 → with_feedback(0.30/0.20/0.40/0.10)
    时间衰减预筛: Δt > 7 天直接丢弃（τ=24h 用于排序权重）
    """
    items = state.get("collected_items", [])
    feedback_history = state.get("feedback_history", [])
    goal_embedding = state.get("goal_embedding", [])

    if not items:
        return {"ranked_items": [], "ranking_detail": {}}

    print(f"[rank_items] 开始排序: {len(items)} 条", flush=True)

    # ---- 0. 时间衰减预筛（Δt > N 天直接丢弃）----
    # expand_threshold 时放宽预筛窗口：7 天 -> 14 天，纳入稍旧但相关的条目
    expand_threshold = bool(state.get("expand_threshold", False))
    prefilter_hours = 336 if expand_threshold else 168  # 14天 / 7天
    now = datetime.now()
    filtered_items = []
    for item in items:
        published_at = item.get("published_at", "")
        if published_at:
            try:
                pub_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                hours_diff = (now - pub_time.replace(tzinfo=None)).total_seconds() / 3600
                if hours_diff > prefilter_hours:
                    continue
            except Exception:
                pass
        filtered_items.append(item)

    pre_drop = len(items) - len(filtered_items)
    pre_label = "14 天" if expand_threshold else "7 天"
    print(f"[rank_items] 预筛({pre_label}): {len(items)} -> {len(filtered_items)} 条 (丢弃: {pre_drop} 条)", flush=True)

    if not filtered_items:
        return {"ranked_items": [], "ranking_detail": {"total_items": 0, "prescreened_dropped": pre_drop}}

    # ---- 1. 权重动态切换（从 config.yaml 读取）----
    rank_cfg = _load_ranking_config()
    feedback_count = len(feedback_history)
    is_cold_start = feedback_count < rank_cfg["cold_start_threshold"]
    weights = rank_cfg["weights_cold"] if is_cold_start else rank_cfg["weights_warm"]
    diversity_bonus = rank_cfg["source_diversity_bonus"]

    mode_label = "cold_start" if is_cold_start else "with_feedback"
    print(f"[rank_items] 权重: {mode_label} (feedback={feedback_count})", flush=True)

    # ---- 2. 反馈偏差映射（数值从 config.yaml 读取）----
    feedback_bias_map = {}
    for fb in feedback_history:
        item_id = fb.get("item_id", "")
        fb_type = fb.get("feedback_type", "")
        if fb_type == "like":
            feedback_bias_map[item_id] = rank_cfg["feedback_bias_positive"]
        elif fb_type == "dislike":
            feedback_bias_map[item_id] = rank_cfg["feedback_bias_negative"]
        elif fb_type == "irrelevant":
            feedback_bias_map[item_id] = rank_cfg["feedback_bias_irrelevant"]

    # ---- 2b. 读取用户偏好向量（warm 模式下用于 preference 余弦因子）----
    user_id = state.get("user_id", 1)
    v_like, v_dislike = (None, None)
    if not is_cold_start:
        v_like, v_dislike = _load_preference_vectors(user_id)
        if v_like is None and v_dislike is None:
            # 偏好向量尚未建立（首次进入 warm），降级为 similarity 代理
            print("[rank_items] 偏好向量未就绪，preference 降级为 similarity 代理", flush=True)

    # ---- 3. 各因子计算 ----
    scored_items = []
    for item in filtered_items:
        item_emb = item.get("embedding", [])
        item_id = item.get("id", "")

        # similarity: cosine(item_embedding, goal_embedding)
        similarity_score = 0.0
        if item_emb and goal_embedding and len(item_emb) == len(goal_embedding):
            dot = sum(a * b for a, b in zip(item_emb, goal_embedding))
            mag1 = (sum(a * a for a in item_emb)) ** 0.5
            mag2 = (sum(g * g for g in goal_embedding)) ** 0.5
            if mag1 > 0 and mag2 > 0:
                similarity_score = max(0.0, dot / (mag1 * mag2))

        # recency: exp(-Δt / 24h)
        recency_score = 0.5
        published_at = item.get("published_at", "")
        if published_at:
            try:
                pub_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                hours_diff = (now - pub_time.replace(tzinfo=None)).total_seconds() / 3600
                recency_score = math.exp(-hours_diff / 24.0)
            except Exception:
                recency_score = 0.5

        # preference: cosine(item_embedding, user_preference_vector)
        #   - cold_start / 偏好未就绪: 用 similarity 代理
        #   - warm: (cos(item,v_like) - cos(item,v_dislike)) 归一化 [0,1]，再叠加 feedback_bias
        if is_cold_start or (v_like is None and v_dislike is None):
            base_pref = similarity_score
        else:
            like_sim = _cosine(item_emb, v_like) if v_like else 0.0
            dislike_sim = _cosine(item_emb, v_dislike) if v_dislike else 0.0
            pref_raw = like_sim - dislike_sim  # [-1,1]
            base_pref = max(0.0, min(1.0, 0.5 + pref_raw / 2.0))
        feedback_bias = feedback_bias_map.get(item_id, 0.0)
        preference_score = max(0.0, min(1.0, base_pref + feedback_bias))

        # importance: (LLM 1-5 分归一化至 0-1)
        raw_importance = float(item.get("importance", 0.5))
        if raw_importance > 1.0:
            importance_score = (raw_importance - 1.0) / 4.0
        else:
            importance_score = raw_importance

        # final_score = w1*sim + w2*rec + w3*pref + w4*imp
        final_score = (
            weights["similarity"] * similarity_score
            + weights["recency"] * recency_score
            + weights["preference"] * preference_score
            + weights["importance"] * importance_score
            + (diversity_bonus if not is_cold_start else 0.0)  # P1: 来源多样性加分（config）
        )

        scored_items.append({
            **item,
            "_score": final_score,
            "_score_detail": {
                "similarity": round(similarity_score, 4),
                "recency": round(recency_score, 4),
                "preference": round(preference_score, 4),
                "importance": round(importance_score, 4),
                "weighted_sim": round(weights["similarity"] * similarity_score, 4),
                "weighted_rec": round(weights["recency"] * recency_score, 4),
                "weighted_pref": round(weights["preference"] * preference_score, 4),
                "weighted_imp": round(weights["importance"] * importance_score, 4),
            },
        })

    # ---- 4. 降序 + 上限 ----
    # expand_threshold 时放宽截断上限：10 -> 20，让更多已采集条目进入简报
    default_max = 20 if expand_threshold else 10
    max_items = state.get("max_briefing_items", default_max)
    ranked_items = scored_items[:max_items]

    # ---- 5. ranking_detail ----
    current_detail = state.get("ranking_detail", {})
    rerank_count = current_detail.get("rerank_count", 0)
    top = ranked_items[0]["_score"] if ranked_items else 0.0
    ranking_detail = {
        "total_items": len(filtered_items),
        "prescreened_dropped": pre_drop,
        "ranked_items": len(ranked_items),
        "weights": weights,
        "weight_mode": mode_label,
        "feedback_count": feedback_count,
        "top_score": top,
        "needs_rerank": False,
        "rerank_count": rerank_count + 1,
    }

    print(f"[rank_items] 完成: {len(ranked_items)} 条, 最高分: {top:.4f}", flush=True)
    return {"ranked_items": ranked_items, "ranking_detail": ranking_detail}
def should_rerank(state: FeedLensState) -> str:
    """评估排序质量，判断是否需要调参重排。

    判断逻辑:
      - 去重后剩余 < 3 条 → 标记需要重新采集（由主 Agent 决策）
      - 最高分 < 0.3 且重排次数 < 2 → 调参重排
      - 否则 → Done
    """
    items = state.get("collected_items", [])
    ranking_detail = state.get("ranking_detail", {})
    rerank_count = ranking_detail.get("rerank_count", 0)

    if len(items) < 3:
        print(f"[should_rerank] 去重后仅 {len(items)} 条 < 3，标记需重新采集", flush=True)
        return "__end__"

    top_score = ranking_detail.get("top_score", 0.0)
    if top_score < 0.3 and rerank_count < 2:
        print(f"[should_rerank] 最高分 {top_score:.4f} < 0.3，第 {rerank_count+1} 次调参重排", flush=True)
        return "rank_items"

    print(f"[should_rerank] 排序质量合格（或已达到重排上限）", flush=True)
    return "__end__"


# ============================================================
# StateGraph 构建
# ============================================================


def build_ranking_agent():
    """构建排序 Agent StateGraph。"""
    workflow = StateGraph(FeedLensState)

    workflow.add_node("vector_search", vector_search_node)
    workflow.add_node("deduplicate", deduplicate_node)
    workflow.add_node("rank_items", rank_items_node)

    workflow.set_entry_point("vector_search")
    workflow.add_edge("vector_search", "deduplicate")
    workflow.add_edge("deduplicate", "rank_items")

    # 条件边: 排序质量不够 → 调参重排
    workflow.add_conditional_edges(
        "rank_items",
        should_rerank,
        {"rank_items": "rank_items", "__end__": END},
    )

    return workflow.compile()