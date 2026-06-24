"""
排序 Agent — ReAct 循环实现（Agentic 升级规划2 Phase 3b）。

从 StateGraph 改为 ReAct 循环：LLM Thought → function_call → Observation → ... → finish_task

工具列表: deduplicate, rank_items, finish_task
"""

import json
import os
import math
from datetime import datetime, timedelta
from typing import List, Dict, Any, Tuple

from langgraph.graph import StateGraph, END
from utils.config import load_config
from utils.hooks import hooks
from agents.state import FeedLensState
from tools import deduplicate, vector_search, db_read, db_write
from tools.tool_registry import tool_registry
from models.vector_store import VectorStore
from utils.embedding import EmbeddingModel
from utils.llm_provider import DeepSeekProvider


# ============================================================
# 配置加载（保留原有辅助函数）
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


def _cosine(vec_a, vec_b) -> float:
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
        "dedup_threshold": ranking_cfg.get("dedup_threshold", 0.88),
        "dedup_llm_lower": ranking_cfg.get("dedup_llm_lower", 0.70),
        "dedup_hard_threshold": ranking_cfg.get("dedup_hard_threshold", 0.80),
        "max_llm_adjudications": ranking_cfg.get("max_llm_adjudications", 20),
    }


# ============================================================
# 保留原有节点函数（供 tool_registry 调用）
# ============================================================

def vector_search_node(state: FeedLensState) -> dict:
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
            vs.persist_dir, query_text, n_results=10, collection_name="user_preference",
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
            print(f"[vector_search] 读取反馈历史失败: {e}", flush=True)
        print(f"[vector_search] 偏好检索: {len(preferences)} 条, 反馈历史: {len(feedback_history)} 条", flush=True)
        return {"user_preferences": preferences, "feedback_history": feedback_history}
    except Exception as e:
        print(f"[vector_search] 失败: {e}", flush=True)
        return {"user_preferences": [], "feedback_history": [], "error": f"vector_search failed: {e}"}


def deduplicate_node(state: FeedLensState) -> dict:
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
            items, vector_store=vs, embedding_model=embedding_model,
            llm_provider=llm_provider,
            threshold_high=dedup_cfg["dedup_threshold"],
            threshold_low=dedup_cfg["dedup_llm_lower"],
            max_llm_adjudications=dedup_cfg["max_llm_adjudications"],
        )
        similar_map = {}
        for pair in duplicate_pairs:
            a_id = pair["item_a_id"]
            similar_map[a_id] = similar_map.get(a_id, 0) + 1
        for item in unique_items:
            item["similar_count"] = similar_map.get(item.get("id", ""), 1)
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
                    [pair["item_a_id"], pair["item_b_id"], pair["similarity_score"],
                     pair["dedup_method"], pair["relation_type"], datetime.now().isoformat()],
                )
            except Exception as e:
                if "FOREIGN KEY" not in str(e):
                    print(f"[deduplicate] 写入关系失败: {e}", flush=True)
        try:
            db_write(db_path, "PRAGMA foreign_keys = ON", [])
        except Exception:
            pass
        print(f"[deduplicate] 完成: {len(unique_items)} 条保留, {len(duplicate_pairs)} 对去重", flush=True)
        return {"collected_items": unique_items, "item_relations": duplicate_pairs}
    except Exception as e:
        print(f"[deduplicate] 失败: {e}", flush=True)
        for item in items:
            item.setdefault("similar_count", 1)
        return {"collected_items": items, "item_relations": [], "error": f"deduplicate failed: {e}"}


def rank_items_node(state: FeedLensState) -> dict:
    items = state.get("collected_items", [])
    feedback_history = state.get("feedback_history", [])
    goal_embedding = state.get("goal_embedding", [])
    if not items:
        return {"ranked_items": [], "ranking_detail": {}}
    expand_threshold = bool(state.get("expand_threshold", False))
    print(f"[rank_items] 开始排序: {len(items)} 条, expand_threshold={expand_threshold}", flush=True)
    # P0-2.2: 预筛窗口配置化，默认 72h（3天），expand 模式 336h（14天）
    rank_cfg_prescreen = _load_ranking_config()
    prescreen_hours = rank_cfg_prescreen.get("prescreen_hours", 72)
    prefilter_hours = 336 if expand_threshold else prescreen_hours
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
    pre_label = f"14 天" if expand_threshold else f"{prescreen_hours // 24} 天"
    print(f"[rank_items] 预筛({pre_label}): {len(items)} -> {len(filtered_items)} 条 (丢弃: {pre_drop} 条)", flush=True)
    if not filtered_items:
        return {"ranked_items": [], "ranking_detail": {"total_items": 0, "prescreened_dropped": pre_drop}}
    rank_cfg = _load_ranking_config()
    feedback_count = len(feedback_history)
    weight_ctx = hooks.run("rank.weights", {
        "feedback_count": feedback_count,
        "cold_start_threshold": rank_cfg.get("cold_start_threshold", 3),
        "weights_cold": rank_cfg["weights_cold"],
        "weights_warm": rank_cfg["weights_warm"],
    })
    is_cold_start = weight_ctx.get("is_cold_start", feedback_count < rank_cfg["cold_start_threshold"])
    weights = weight_ctx.get("weights", rank_cfg["weights_warm"])
    diversity_bonus = rank_cfg["source_diversity_bonus"]
    mode_label = weight_ctx.get("mode_label", "cold_start" if is_cold_start else "with_feedback")
    print(f"[rank_items] 权重: {mode_label} (feedback={feedback_count})", flush=True)
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
    user_id = state.get("user_id", 1)
    # 优先使用预加载的偏好向量（由 run_ranking_agent 传入），避免重复加载
    v_like = state.get("_pref_v_like")
    v_dislike = state.get("_pref_v_dislike")
    if not is_cold_start and v_like is None and v_dislike is None:
        v_like, v_dislike = _load_preference_vectors(user_id)
        if v_like is None and v_dislike is None:
            print("[rank_items] 偏好向量未就绪，preference 降级为 similarity 代理", flush=True)
    scored_items = []
    for item in filtered_items:
        item_emb = item.get("embedding", [])
        item_id = item.get("id", "")
        similarity_score = 0.0
        # 🔧 安全处理：embedding 可能是 numpy array，空数组的布尔判断会抛异常
        if (item_emb is not None and hasattr(item_emb, '__len__') and len(item_emb) > 0
                and goal_embedding is not None and hasattr(goal_embedding, '__len__') and len(goal_embedding) > 0
                and len(item_emb) == len(goal_embedding)):
            dot = sum(a * b for a, b in zip(item_emb, goal_embedding))
            mag1 = (sum(a * a for a in item_emb)) ** 0.5
            mag2 = (sum(g * g for g in goal_embedding)) ** 0.5
            if mag1 > 0 and mag2 > 0:
                similarity_score = max(0.0, dot / (mag1 * mag2))
        recency_score = 0.5
        published_at = item.get("published_at", "")
        if published_at:
            try:
                pub_time = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                hours_diff = (now - pub_time.replace(tzinfo=None)).total_seconds() / 3600
                recency_score = math.exp(-hours_diff / 24.0)
            except Exception:
                recency_score = 0.5
        if is_cold_start or (v_like is None and v_dislike is None):
            base_pref = similarity_score
        else:
            like_sim = _cosine(item_emb, v_like) if v_like else 0.0
            dislike_sim = _cosine(item_emb, v_dislike) if v_dislike else 0.0
            pref_raw = like_sim - dislike_sim
            base_pref = max(0.0, min(1.0, 0.5 + pref_raw / 2.0))
        feedback_bias = feedback_bias_map.get(item_id, 0.0)
        preference_score = max(0.0, min(1.0, base_pref + feedback_bias))
        raw_importance = float(item.get("importance", 0.5))
        if raw_importance > 1.0:
            importance_score = (raw_importance - 1.0) / 4.0
        else:
            importance_score = raw_importance
        final_score = (
            weights["similarity"] * similarity_score
            + weights["recency"] * recency_score
            + weights["preference"] * preference_score
            + weights["importance"] * importance_score
            + (diversity_bonus if not is_cold_start else 0.0)
        )
        scored_items.append({
            **item,
            "_score": final_score,
            "_score_detail": {
                "similarity": round(similarity_score, 4),
                "recency": round(recency_score, 4),
                "preference": round(preference_score, 4),
                "importance": round(importance_score, 4),
            },
        })
    default_max = 20 if expand_threshold else 10
    max_items = state.get("max_briefing_items", default_max)
    ranked_items = sorted(scored_items, key=lambda x: x["_score"], reverse=True)[:max_items]
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


# ============================================================
# P1 默认 rank.weights hook
# ============================================================

def _default_rank_weights(ctx: dict) -> dict:
    fb = ctx.get("feedback_count", 0)
    threshold = ctx.get("cold_start_threshold", 3)
    is_cold = fb < threshold
    return {
        "is_cold_start": is_cold,
        "weights": ctx["weights_cold"] if is_cold else ctx["weights_warm"],
        "mode_label": "cold_start" if is_cold else "with_feedback",
    }


hooks.register("rank.weights", _default_rank_weights)


# ============================================================
# System Prompt
# ============================================================

RANKING_SYSTEM_PROMPT = """你是 FeedLens 的排序 Agent。你的目标是对采集到的内容进行去重和排序。

可用工具：
- deduplicate: 向量相似度去重（高相似度直接判重，中间区间 LLM 裁决）
- rank_items: 多因子加权排序（综合相似度、时效性、用户偏好、重要性）
- finish_task: 标记排序完成，返回结果摘要

工作流程建议：
1. 先调用 deduplicate 去除重复内容
2. 再调用 rank_items 按用户偏好排序
3. 调用 finish_task 结束

如果采集条目较少（< 3 条），可以跳过去重直接排序。
完成后必须调用 finish_task。"""


# ============================================================
# ReAct 排序函数
# ============================================================

def run_ranking_agent(state: FeedLensState) -> dict:
    """ReAct 排序 Agent — LLM 自主调用工具完成去重+排序。

    Args:
        state: FeedLensState，包含 collected_items, user_id, feedback_history 等

    Returns:
        dict: {collected_items(去重后), ranked_items, ranking_detail, item_relations}
    """
    llm = _get_llm_provider()
    tools = tool_registry.get_schemas_for_phase("ranking")

    items = state.get("collected_items", [])
    user_id = state.get("user_id", 1)

    # 先检索用户偏好和反馈历史
    vs_result = vector_search_node(state)
    current_state = dict(state)
    current_state.update(vs_result)

    # 预加载偏好向量到 current_state，避免 rank_items_node 内部重复加载
    feedback_history = vs_result.get("feedback_history", [])
    feedback_count = len(feedback_history)
    rank_cfg = _load_ranking_config()
    is_cold_start = feedback_count < rank_cfg.get("cold_start_threshold", 3)
    if not is_cold_start:
        v_like, v_dislike = _load_preference_vectors(user_id)
        if v_like is not None or v_dislike is not None:
            current_state["_pref_v_like"] = v_like
            current_state["_pref_v_dislike"] = v_dislike
            print(f"[ranking_react] 偏好向量已预加载 (like={v_like is not None}, dislike={v_dislike is not None})", flush=True)

    user_msg = f"待处理条目: {len(items)} 条\n"
    user_msg += f"用户 ID: {user_id}\n"
    if vs_result.get("feedback_history"):
        user_msg += f"反馈历史: {len(vs_result['feedback_history'])} 条\n"

    # 注入条目摘要（关键字段，避免 token 爆炸）
    if items:
        user_msg += "\n--- 条目列表（每条仅含关键字段）---\n"
        for i, item in enumerate(items[:50]):  # 最多 50 条
            title = item.get("title", "")[:100]
            source = item.get("source_name", item.get("source_url", ""))[:60]
            pub = item.get("published_at", "")[:19]
            summary = (item.get("summary", "") or item.get("content", ""))[:500]
            item_id = item.get("id", f"item_{i}")
            user_msg += (
                f"[{i}] id={item_id} | title={title} | source={source} | "
                f"time={pub} | summary={summary}\n"
            )

    messages = [
        {"role": "system", "content": RANKING_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    ranked_items = []
    ranking_detail = {}

    max_turns = 5
    for turn in range(max_turns):
        print(f"[ranking_react] 第 {turn + 1} 轮思考...", flush=True)

        try:
            response_dict = llm.chat_with_tools(messages=messages, tools=tools)
        except Exception as e:
            print(f"[ranking_react] LLM 调用失败: {e}，退出循环", flush=True)
            break

        choices = response_dict.get("choices", [])
        if not choices:
            print("[ranking_react] LLM 返回空 choices，退出循环", flush=True)
            break
        choice = choices[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")

        tool_calls = message.get("tool_calls", [])
        if tool_calls and finish_reason == "tool_calls":
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    tool_args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                print(f"[ranking_react] 调用工具: {tool_name}", flush=True)

                # 特殊处理：deduplicate/rank_items 需要注入 collected_items
                if tool_name in ("deduplicate", "rank_items") and "items" not in tool_args:
                    tool_args["items"] = current_state.get("collected_items", items)
                if tool_name == "rank_items":
                    if "user_id" not in tool_args:
                        tool_args["user_id"] = user_id
                    if "feedback_history" not in tool_args:
                        tool_args["feedback_history"] = vs_result.get("feedback_history", [])
                    if "goal_embedding" not in tool_args:
                        tool_args["goal_embedding"] = state.get("goal_embedding", [])
                    # P0-2.2: 传递 expand_threshold（planner 通过 params 注入 state）
                    if "expand_threshold" not in tool_args:
                        et = current_state.get("expand_threshold", False)
                        tool_args["expand_threshold"] = et
                        if et:
                            print(f"[ranking_react] expand_threshold=True 已注入 rank_items 工具调用", flush=True)
                    # 传递预加载的偏好向量，避免 rank_items_node 内部重复加载
                    if current_state.get("_pref_v_like") is not None:
                        tool_args["_pref_v_like"] = current_state["_pref_v_like"]
                    if current_state.get("_pref_v_dislike") is not None:
                        tool_args["_pref_v_dislike"] = current_state["_pref_v_dislike"]

                try:
                    result = tool_registry.dispatch(tool_name, tool_args)
                except Exception as e:
                    result = {"error": str(e)}
                    print(f"[ranking_react] 工具 {tool_name} 失败: {e}", flush=True)

                if tool_name == "deduplicate":
                    unique = result.get("unique_items", [])
                    dup_pairs = result.get("duplicate_pairs", [])
                    current_state["collected_items"] = unique
                    current_state["item_relations"] = dup_pairs
                elif tool_name == "rank_items":
                    ranked_items = result.get("ranked_items", [])
                    ranking_detail = result.get("ranking_detail", {})
                    current_state["ranked_items"] = ranked_items
                    current_state["ranking_detail"] = ranking_detail
                elif tool_name == "finish_task":
                    summary = result.get("summary", "")
                    print(f"[ranking_react] 排序完成: {len(ranked_items)} 条", flush=True)
                    # 追加 finish_task 调用记录到 messages 历史（保持完整性，便于审计/重放）
                    messages.append(message)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", tool_name),
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                    return {
                        "collected_items": current_state.get("collected_items", items),
                        "ranked_items": ranked_items,
                        "ranking_detail": ranking_detail,
                        "item_relations": current_state.get("item_relations", []),
                        "ranking_summary": summary,
                    }

                messages.append(message)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", tool_name),
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
        else:
            content = message.get("content", "")
            print(f"[ranking_react] LLM 未调用工具，回复: {content[:100]}", flush=True)
            # tool_choice="required" 下极少出现，但保留一次重试作为兜底
            if content and turn < 1:
                safe_message = {k: v for k, v in message.items() if k != "tool_calls"}
                messages.append(safe_message)
                messages.append({"role": "user", "content": "请调用工具执行去重和排序，完成后调用 finish_task。"})
                continue
            break

    # 兜底
    print(f"[ranking_react] 超过 {max_turns} 轮未完成，强制返回", flush=True)
    return {
        "collected_items": current_state.get("collected_items", items),
        "ranked_items": ranked_items,
        "ranking_detail": ranking_detail,
        "item_relations": current_state.get("item_relations", []),
        "ranking_summary": "超时结束",
    }


# ============================================================
# 兼容接口
# ============================================================

class _ReActAgentWrapper:
    def __init__(self, fn):
        self._fn = fn

    def invoke(self, state: dict) -> dict:
        return self._fn(state)


def build_ranking_agent():
    """构建排序 Agent（兼容旧接口）。"""
    return _ReActAgentWrapper(run_ranking_agent)
