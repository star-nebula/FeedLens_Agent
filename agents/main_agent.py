"""
主 Agent — Coordinator + Planner。

工作流: understand_intent → planner → invoke_sub_agent → observe_results
         → planner(再思考) → coordinator_reflect → push_notification → update_memory

ReAct 循环: planner → invoke_sub_agent → observe_results → planner (最多 3 次)
  - 子 Agent 执行：Collection → Ranking → Briefing
  - 7 个 planner 决策场景见 docstring

MVP 约束：
  - 子 Agent 按顺序执行（暂不支持并行）
  - 不实现 skip_collection / skip_briefing 跳过逻辑
  - 重大事件检测在 Ranking 完成后判断
"""

import os
import json
import yaml
import time
import hashlib
from datetime import datetime
from typing import List, Dict, Any

from langgraph.graph import StateGraph, END
from utils.config import load_config
from utils.error_isolation import run_with_isolation
from agents.state import FeedLensState
from agents.collection_agent import build_collection_agent, _get_rss_sources, _get_search_query
from agents.ranking_agent import build_ranking_agent
from agents.briefing_agent import build_briefing_agent
from tools.mcp_client import PushMCPClient
from models.vector_store import VectorStore
from utils.embedding import EmbeddingModel
from utils.llm_provider import DeepSeekProvider, LLMProvider, LLMRouter
from utils.hooks import hooks
from tools import db_read, db_write
from utils.memory_manager import get_context, add_memory


# ============================================================
# 配置加载
# ============================================================

def _get_llm_provider() -> LLMProvider:
    config = load_config()
    llm_cfg = config.get("llm", {})
    deepseek_cfg = llm_cfg.get("deepseek", {})
    primary = DeepSeekProvider(
        api_key=deepseek_cfg.get("api_key", ""),
        base_url=deepseek_cfg.get("base_url", "https://api.deepseek.com/v1"),
        model=deepseek_cfg.get("model", "deepseek-chat"),
    )
    # P4 模型回退：读 config.llm.fallback 构建备用 Provider，无配置则仅用主 Provider
    fallback_cfg = llm_cfg.get("fallback", {})
    if fallback_cfg.get("api_key"):
        fallback = DeepSeekProvider(
            api_key=fallback_cfg.get("api_key", ""),
            base_url=fallback_cfg.get("base_url", "https://api.deepseek.com/v1"),
            model=fallback_cfg.get("model", "deepseek-chat"),
        )
        return LLMRouter([primary, fallback], names=["deepseek_primary", "deepseek_fallback"])
    return primary


def _get_db_path() -> str:
    config = load_config()
    return config.get("data", {}).get("db_path", "data/feedlens.db")

# ============================================================
# Planner System Prompt（LLM 自主编排）
# ============================================================

PLANNER_SYSTEM_PROMPT = """你是 FeedLens 的编排 Planner。根据当前 Agent 运行状态，决定下一步该调度哪些子 Agent。

## 可调度的子 Agent

- Collection: 采集 RSS 源 + 补充 MCP 搜索。输入：无；输出：collected_items
- Ranking:   向量去重 + 多因子偏好排序。输入：collected_items；输出：ranked_items, ranking_detail
- Briefing:  生成简报 JSON + 质量审查。输入：ranked_items；输出：briefing, brief_quality

## 编排策略参考

- 采集条数 < 3 且未补充搜索 → 对 goal 关键词执行 search_expand
- 排序 top_score < 0.3 → 考虑 rerank 或跳过
- 简报条目 < 10 且采集已足够(>=10条) → expand_threshold：放宽排序门槛，把分数较低但已采集的条目纳入简报（不重新采集，调 Ranking 并在 params 设 expand_threshold=true）
- 简报条目 < 10 且采集也不足 → 先 search_expand 补充采集，再 Ranking
- 简报质量 < 0.7 → retry_briefing 或 skip
- react_cycle >= 2 → 优先收敛，跳过非必须步骤
- top_score > 0.85 且重要性高 → 标记 push_immediate
- 采集足够但排序已达标 → 可跳过 Collection 直接 Ranking（节约时间/API 成本）

## 历史经验参考

上下文中可能包含 memory 字段：
- memory.recent_executions: 近7天执行记录（含每次采集量、排序质量、决策和结果）
- memory.relevant_history: ChromaDB 语义检索的过往类似场景处理经验（可能为空）

若历史经验显示某策略在类似状态下有效或无效，优先参考；若 memory 为空或当前状态与历史差异明显，以当前数据为准决策。

## 输出格式

严格返回 JSON，不加任何解释：
{
  "sub_agent_plan": [{"agent": "Collection", "params": {}}, {"agent": "Ranking", "params": {}}],
  "reason": "一句话中文理由",
  "push_immediate": false
}

params 可选值：search_expand(含 query), retry, rerank, expand_threshold 等。空对象表示标准执行。
注意：expand_threshold 仅对 Ranking 有效，表示放宽排序截断门槛，把更多已采集条目纳入简报。"""


# ============================================================
# Router System Prompt（LLM 动态路由决策）
# ============================================================

ROUTER_SYSTEM_PROMPT = """你是 FeedLens 的自主路由决策者。根据当前 Agent 运行状态和上下文，决定下一步跳转到哪个节点。

## 可跳转节点

- "planner": 需要（重新）编排子 Agent 执行计划
- "invoke_sub_agent": 执行 planner 编排的子 Agent（sub_agent_plan 非空且 sub_agent_executed=false）
- "observe_results": 子 Agent 执行完毕，观察评估结果质量
- "coordinator_reflect": 综合质量审查（完整性+去重+追溯+矛盾检查）
- "push_notification": 简报已就绪，执行推送
- "update_memory": 记录执行日志、更新偏好向量并结束流程
- "abort": 放弃本次执行（多次重试失败或数据始终为0）
- "END": 流程已完全结束

## 决策规则（按优先级，必须严格遵守）

1. sub_agent_executed=true 且 observation 为空 → "observe_results"（子Agent刚执行完，必须评估结果）
2. sub_agent_plan 非空且 sub_agent_executed=false → "invoke_sub_agent"（执行计划中的子Agent）
3. observe_results 完成、needs_retry=true 且 react_cycle_count < 3 → "planner"（ReAct重试）
4. observe_results 完成、needs_retry=false 或已达最大循环 → "coordinator_reflect"
5. coordinator_reflect 完成、overall_pass=true → "push_notification"
6. coordinator_reflect 完成、overall_pass=false 且 react_cycle_count < 3 → "planner"（重新编排）
7. coordinator_reflect 完成、overall_pass=false 且已达最大循环 → "push_notification"（强制推送）
8. push_notification 完成 → "update_memory"
9. update_memory 完成 → "END"
10. 多次重试失败或采集始终为0 → "abort"

## 状态上下文字段说明

- sub_agent_plan: 当前编排计划列表（执行完毕后会被清空）
- sub_agent_plan_count: 计划中的子Agent数量
- sub_agent_executed: 本轮计划是否已执行（true=已执行完，false=未执行）
- collected_count: 已采集条目数
- ranked_count: 已排序条目数
- react_cycle_count: ReAct循环计数（max=3）
- agentic_turn_count: 主循环总轮数
- observation: observe_results输出（含 needs_retry, issues 等）
- coordinator_observation: 综合审查结果（含 overall_pass, issues 等）
- push_status: 推送状态（空/sent/failed）
- status: 当前流程状态（running/completed/failed）
- brief_quality: 简报质量评分

## 输出格式

严格返回 JSON，不加任何解释：
{"next_node": "planner", "reason": "一句话中文理由"}
"""


# ============================================================
# 节点定义
# ============================================================


def understand_intent_node(state: FeedLensState) -> dict:
    """理解用户意图：识别触发类型 + 结构化提取 goal + 生成 goal_embedding。

    触发类型:
      - daily_briefing: 定时任务触发
      - manual: 用户手动触发
      - breaking_news: 重大事件检测触发

    返回:
        trigger_type: 触发类型
        structured_goal: 结构化提取结果 {topics, keywords, preferred_sources}
        goal_embedding: goal 文本的向量表示
    """
    trigger_type = state.get("trigger_type", "daily_briefing")
    goal_text = state.get("goal_text", "")
    user_id = state.get("user_id", 1)

    print(f"[understand_intent] trigger={trigger_type}, goal={goal_text[:50]}...", flush=True)

    # 加载用户结构化偏好（从 SQLite）
    structured_goal = {"topics": [], "keywords": [], "preferred_sources": []}
    try:
        db_path = _get_db_path()
        from models.database import Database
        Database(db_path).init_schema()
        rows = db_read(
            db_path,
            "SELECT topics, keywords, preferred_sources FROM users WHERE id = ?",
            [user_id],
        )
        if rows:
            row = rows[0]
            if row.get("topics"):
                structured_goal["topics"] = json.loads(row["topics"])
            if row.get("keywords"):
                structured_goal["keywords"] = json.loads(row["keywords"])
            if row.get("preferred_sources"):
                structured_goal["preferred_sources"] = json.loads(row["preferred_sources"])
    except Exception as e:
        print(f"[understand_intent] 读取用户偏好失败: {e}", flush=True)

    # 如果 goal_text 有内容，调用 LLM 提取结构化字段
    if goal_text and not structured_goal.get("topics"):
        llm = _get_llm_provider()
        try:
            prompt = f"""从用户目标中提取结构化信息。

用户目标: {goal_text}

请提取以下 JSON 字段（不要输出其他内容）：
{{
  "topics": ["主要关注领域列表，最多3个"],
  "keywords": ["关键词列表，最多5个"],
  "preferred_sources": ["偏好的RSS源URL列表，如无则为空数组"]
}}

直接输出 JSON，不要有额外解释。"""
            resp = llm.chat([{"role": "user", "content": prompt}])
            # 兼容 LLMRouter 不同 provider 的返回格式差异
            if isinstance(resp, str):
                content = resp.strip()
            elif isinstance(resp, dict):
                content = (resp.get("content") or "").strip()
            else:
                content = ""
            # 提取 JSON
            if "{" in content:
                json_str = content[content.index("{"):content.rindex("}")+1]
                parsed = json.loads(json_str)
                structured_goal["topics"] = parsed.get("topics", [])
                structured_goal["keywords"] = parsed.get("keywords", [])
                structured_goal["preferred_sources"] = parsed.get("preferred_sources", [])
                print(f"[understand_intent] LLM 提取: topics={structured_goal['topics']}", flush=True)
        except Exception as e:
            print(f"[understand_intent] LLM 提取失败: {e}", flush=True)

    # 生成 goal_embedding
    goal_embedding = []
    try:
        embedding_model = EmbeddingModel()
        text_for_embedding = " ".join(structured_goal.get("topics", [])[:3] + structured_goal.get("keywords", [])[:5])
        if text_for_embedding:
            goal_embedding = embedding_model.encode([text_for_embedding]).tolist()[0]
    except Exception as e:
        print(f"[understand_intent] goal_embedding 生成失败: {e}", flush=True)

    return {
        "trigger_type": trigger_type,
        "structured_goal": structured_goal,
        "goal_embedding": goal_embedding,
        "react_cycle_count": 0,
        "status": "running",
    }


def planner_node(state: FeedLensState) -> dict:
    """LLM 驱动的自主编排节点（ReAct 的 Think 步骤）。

    将当前 Agent 状态摘要发给 LLM，由 LLM 决定下一步调度哪些子 Agent。
    LLM 失败时回退到标准三板斧。
    """
    react_cycle = state.get("react_cycle_count", 0)
    trigger_type = state.get("trigger_type", "daily_briefing")
    print(f"[planner] ReAct 第 {react_cycle} 轮, trigger={trigger_type}", flush=True)

    context = _build_planner_context(state)

    try:
        llm = _get_llm_provider()
        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ]
        response = llm.chat(messages, temperature=0.3, max_tokens=1024)
        # 兼容 LLMRouter 不同 provider 的返回格式差异
        if isinstance(response, str):
            text = response
        elif isinstance(response, dict):
            text = response.get("content") or "{}"
        else:
            text = "{}"
        plan = _parse_planner_response(text)
        print(f"[planner] LLM 决策: {json.dumps(plan, ensure_ascii=False)}", flush=True)
    except Exception as e:
        print(f"[planner] LLM 调用失败，回退默认: {e}", flush=True)
        plan = _fallback_plan(state)

    print(f"[planner] 编排计划: {[p['agent'] for p in plan.get('sub_agent_plan', [])]}, "
          f"push_immediate={plan.get('push_immediate', False)}", flush=True)

    return {
        "sub_agent_plan": plan.get("sub_agent_plan", []),
        "sub_agent_executed": False,  # 新计划尚未执行
        "observation_result": {},  # 清除旧观察结果，等待新一轮评估
        "push_immediate": plan.get("push_immediate", False),
        "planner_reason": plan.get("reason", ""),
    }


def _build_planner_context(state: FeedLensState) -> dict:
    """构建 planner 的 LLM 输入上下文。

    FeedLens 场景适配：
      - 情节记忆（SQLite）：检索近7天执行记录，供 planner 回顾近期采集/排序/简报效果
      - 长期记忆（ChromaDB）：语义检索历史类似场景的执行经验
    """
    obs = state.get("observation_result", {})
    ranking_detail = state.get("ranking_detail", {})
    collected = state.get("collected_items", [])
    top_score = ranking_detail.get("top_score", 0)
    brief_quality = state.get("brief_quality", 0)

    # 记忆检索：情节记忆（近N天执行记录）+ 长期记忆（语义检索历史经验）
    memory_query = f"采集{len(collected)}条 排序top{top_score:.2f} 简报质量{brief_quality:.2f}"
    try:
        memory_ctx = get_context(query=memory_query, n_episodic=10, n_long_term=3, lookback_days=7)
        _episodic = memory_ctx.get("episodic", [])
        _long_term = memory_ctx.get("long_term", [])
        print(f"[planner] memory: 情节(近7天)={len(_episodic)}条 长期(语义)={len(_long_term)}条", flush=True)

        # 情节记忆：提取执行摘要信息
        recent_executions = []
        for log in _episodic:
            meta = log.get("metadata", {})
            recent_executions.append({
                "session_id": log.get("session_id", ""),
                "created_at": log.get("created_at", ""),
                "situation": meta.get("situation", ""),
                "decision": meta.get("decision", []),
                "outcome": meta.get("outcome", ""),
                "trigger": meta.get("trigger", ""),
            })

        memory_block = {
            "recent_executions": recent_executions,
            "relevant_history": [m.get("document", "") for m in _long_term],
        }
    except Exception as e:
        print(f"[planner] 记忆检索失败，降级为空: {e}", flush=True)
        memory_block = {"recent_executions": [], "relevant_history": []}

    return {
        "trigger": state.get("trigger_type", "daily_briefing"),
        "goal": state.get("goal_text", ""),
        "react_cycle": state.get("react_cycle_count", 0),
        "collection": {
            "count": len(collected),
            "search_supplemented": state.get("search_supplemented", False),
        },
        "ranking": {
            "count": len(state.get("ranked_items", [])),
            "top_score": top_score,
        },
        "briefing": {
            "quality": brief_quality,
        },
        "last_observation": obs,
        "memory": memory_block,
    }

def _parse_planner_response(text: str) -> dict:
    """从 LLM 响应中解析编排计划 JSON，失败则抛异常。"""
    import re as _re
    match = _re.search(r'\{[\s\S]*\}', text)
    json_str = match.group() if match else text
    plan = json.loads(json_str)
    # 校验必要字段
    if not isinstance(plan.get("sub_agent_plan"), list):
        raise ValueError("sub_agent_plan 不是列表")
    return plan


def _fallback_plan(state: FeedLensState) -> dict:
    """LLM 调用失败时的默认编排。"""
    react_cycle = state.get("react_cycle_count", 0)
    if react_cycle >= 2:
        # 已经走了两轮，收敛：跳过采集，直接排序+简报
        return {
            "sub_agent_plan": [
                {"agent": "Ranking", "params": {}},
                {"agent": "Briefing", "params": {}},
            ],
            "reason": "已达循环上限，收敛为排序→简报",
            "push_immediate": False,
        }
    return {
        "sub_agent_plan": [
            {"agent": "Collection", "params": {}},
            {"agent": "Ranking", "params": {}},
            {"agent": "Briefing", "params": {}},
        ],
        "reason": "LLM 失败回退，执行标准流程",
        "push_immediate": False,
    }


def _parse_router_response(text: str) -> dict:
    """容错解析 LLM 路由决策，三层降级，必须返回有效 dict。

    Layer 1: 直接 json.loads
    Layer 2: regex 提取第一个 {...} 再 json.loads
    Layer 3: 兜底返回 planner
    """
    # Layer 1: 直接解析
    try:
        decision = json.loads(text)
        if isinstance(decision, dict) and "next_node" in decision:
            return decision
    except (json.JSONDecodeError, TypeError):
        pass

    # Layer 2: regex 提取 JSON 块
    import re as _re
    match = _re.search(r'\{[^{}]*"next_node"\s*:\s*"[^"]*"[^{}]*\}', text)
    if match:
        try:
            decision = json.loads(match.group())
            if isinstance(decision, dict) and "next_node" in decision:
                return decision
        except (json.JSONDecodeError, TypeError):
            pass
    # 更宽松的 regex 提取
    match = _re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            decision = json.loads(match.group())
            if isinstance(decision, dict) and "next_node" in decision:
                return decision
        except (json.JSONDecodeError, TypeError):
            pass

    # Layer 3: 兜底
    print(f"[router] JSON 解析全部失败，降级到 planner。原始响应: {text[:200]}", flush=True)
    return {"next_node": "planner", "reason": "router parse fallback"}


def _build_router_context(state: FeedLensState) -> dict:
    """构建 router_node 的 LLM 输入上下文。"""
    plan = state.get("sub_agent_plan", [])
    obs = state.get("observation_result", {})
    coordinator_obs = state.get("coordinator_observation", {})
    push_status = state.get("push_status", "")
    status = state.get("status", "running")

    return {
        "sub_agent_plan": plan,
        "sub_agent_plan_count": len(plan),
        "sub_agent_executed": state.get("sub_agent_executed", False),
        "collected_count": len(state.get("collected_items", [])),
        "ranked_count": len(state.get("ranked_items", [])),
        "react_cycle_count": state.get("react_cycle_count", 0),
        "agentic_turn_count": state.get("agentic_turn_count", 0),
        "observation": obs,
        "coordinator_observation": coordinator_obs,
        "push_status": push_status,
        "status": status,
        "brief_quality": state.get("brief_quality", 0.0),
        "trigger_type": state.get("trigger_type", "daily_briefing"),
    }


def _rule_based_router_decision(state: FeedLensState) -> dict | None:
    """规则路由决策（不依赖 LLM 的确定性路由）。

    正常流程中所有路由场景均可用规则判断，无需 LLM。
    返回 None 表示规则无法覆盖，需调用 LLM。

    按优先级判断下一步：
    1. plan 非空且未执行 → invoke_sub_agent
    2. plan 已执行但未观察 → observe_results
    3. 已观察、需重试且未达上限 → planner（需要 LLM 重新编排 plan）
    4. 已观察、不需重试 → coordinator_reflect
    5. coordinator 审查通过 → push_notification
    6. push 完成 → update_memory
    7. 兜底 → update_memory
    """
    plan = state.get("sub_agent_plan", [])
    executed = state.get("sub_agent_executed", False)
    obs = state.get("observation_result", {})
    coordinator_obs = state.get("coordinator_observation", {})
    push_status = state.get("push_status", "")
    react_cycle = state.get("react_cycle_count", 0)

    # 1. 有未执行的计划 → 直接执行
    if plan and not executed:
        return {"next_node": "invoke_sub_agent", "reason": "规则路由：执行计划中的子Agent"}

    # 2. 已执行但未观察 → 评估结果
    if executed and not obs:
        return {"next_node": "observe_results", "reason": "规则路由：子Agent执行完毕，评估结果"}

    # 3. 已观察，需要重试且未达上限 → 需要 LLM 重新编排 plan
    if obs.get("needs_retry") and react_cycle < 3:
        return None  # 规则无法覆盖：需要 LLM planner 重新编排 sub_agent_plan

    # 3b. 已观察，需要重试但已达上限 → 根据数据量决定 abort 还是收敛
    if obs.get("needs_retry") and react_cycle >= 3:
        collected_count = len(state.get("collected_items", []))
        if collected_count == 0:
            return {"next_node": "abort", "reason": "规则路由：多次重试采集仍为0，放弃执行"}
        # 有数据但质量不达标 → 强制收敛到 update_memory
        return {"next_node": "update_memory", "reason": "规则路由：已达重试上限，强制收敛结束"}

    # 4. 已观察，无需重试 → 综合审查
    if obs and not obs.get("needs_retry", False):
        return {"next_node": "coordinator_reflect", "reason": "规则路由：进入综合审查"}

    # 5. 综合审查通过 → 推送
    if coordinator_obs.get("overall_pass") and not push_status:
        return {"next_node": "push_notification", "reason": "规则路由：审查通过，推送简报"}

    # 6. 综合审查不通过且未达上限 → 需要 LLM 重新编排
    if coordinator_obs and not coordinator_obs.get("overall_pass", True) and react_cycle < 3:
        return None  # 规则无法覆盖：需要 LLM planner 重新编排 sub_agent_plan

    # 6b. 综合审查不通过且已达上限 → 强制收敛推送
    if coordinator_obs and not coordinator_obs.get("overall_pass", True) and react_cycle >= 3:
        return {"next_node": "push_notification", "reason": "规则路由：审查未通过但已达上限，强制推送"}

    # 7. 推送完成 → 记忆写入
    if push_status == "sent":
        return {"next_node": "update_memory", "reason": "规则路由：推送完成，写入记忆"}

    # 8. 兜底：写入记忆结束
    return {"next_node": "update_memory", "reason": "规则路由：兜底结束流程"}


def router_node(state: FeedLensState) -> dict:
    """LLM 动态路由决策节点。

    防死循环 + 硬兜底 + LLM 自主决策，返回 next_node 路由目标。

    Returns:
        router_decision: {"next_node": "...", "reason": "..."}
        router_history: 追加后的历史决策列表
        agentic_turn_count: 递增后的循环计数
    """
    from agents.state import FeedLensState as _FS

    # 防死循环：检查最近 3 次决策是否相同
    recent = state.get("router_history", [])[-3:]
    if len(recent) >= 3 and len(set(d.get("next_node", "") for d in recent)) == 1:
        same_node = recent[0].get("next_node", "unknown")
        print(f"[router] 死循环检测：连续 3 次路由到 {same_node}，强制结束", flush=True)
        # 如果已经生成了简报但未经过 coordinator_reflect，先走 coordinator_reflect 确保 briefing 写入 state
        has_briefing = bool(state.get("briefing") or state.get("briefing_result", {}).get("briefing"))
        has_reflected = bool(state.get("coordinator_observation"))
        if has_briefing and not has_reflected:
            print(f"[router] 死循环检测：已有简报但未审查，先路由到 coordinator_reflect", flush=True)
            return {
                "router_decision": {"next_node": "coordinator_reflect", "reason": f"死循环检测：强制收敛，先审查再结束"},
                "router_history": state.get("router_history", []) + [
                    {"next_node": "coordinator_reflect", "reason": f"死循环检测：强制收敛"}
                ],
                "agentic_turn_count": state.get("agentic_turn_count", 0) + 1,
            }
        return {
            "router_decision": {"next_node": "update_memory", "reason": f"死循环检测：连续3次{same_node}"},
            "router_history": state.get("router_history", []) + [
                {"next_node": "update_memory", "reason": f"死循环检测：连续3次{same_node}"}
            ],
            "agentic_turn_count": state.get("agentic_turn_count", 0) + 1,
        }

    # 硬兜底：超过 max_turns（P0-2.2: 配置化，默认 5）
    cfg = load_config()
    max_turns = cfg.get("agents", {}).get("max_turns", 5)
    if state.get("agentic_turn_count", 0) >= max_turns:
        print(f"[router] 超过最大轮数 {max_turns}，强制结束", flush=True)
        # 如果已经生成了简报但未经过 coordinator_reflect，先走 coordinator_reflect 确保 briefing 写入 state
        has_briefing = bool(state.get("briefing") or state.get("briefing_result", {}).get("briefing"))
        has_reflected = bool(state.get("coordinator_observation"))
        if has_briefing and not has_reflected:
            print(f"[router] 超轮数：已有简报但未审查，先路由到 coordinator_reflect", flush=True)
            return {
                "router_decision": {"next_node": "coordinator_reflect", "reason": f"超轮数{max_turns}，强制收敛审查"},
                "router_history": state.get("router_history", []) + [
                    {"next_node": "coordinator_reflect", "reason": f"超轮数{max_turns}，强制收敛"}
                ],
                "agentic_turn_count": state.get("agentic_turn_count", 0) + 1,
            }
        return {
            "router_decision": {"next_node": "update_memory", "reason": f"超过最大轮数{max_turns}"},
            "router_history": state.get("router_history", []) + [
                {"next_node": "update_memory", "reason": f"超过最大轮数{max_turns}"}
            ],
            "agentic_turn_count": state.get("agentic_turn_count", 0) + 1,
        }

    # P0-2.4: 规则优先路由 — 正常流程场景全部由规则覆盖，无需 LLM
    # 只有 needs_retry 或 overall_pass=false 需要 planner 重新编排时，才调 LLM
    rule_decision = _rule_based_router_decision(state)
    if rule_decision is not None:
        decision = rule_decision
        print(f"[router] 规则路由: {json.dumps(decision, ensure_ascii=False)}", flush=True)
    else:
        # 规则无法覆盖的场景（needs_retry / overall_pass=false）：需要 LLM planner 重新编排
        # 此时直接路由到 planner，让 planner_node 用 LLM 重新生成 sub_agent_plan
        print(f"[router] 规则无法覆盖（需重新编排），路由到 planner", flush=True)
        decision = {"next_node": "planner", "reason": "规则无法覆盖：需要LLM重新编排sub_agent_plan"}

    return {
        "router_decision": decision,
        "router_history": state.get("router_history", []) + [decision],
        "agentic_turn_count": state.get("agentic_turn_count", 0) + 1,
    }


def invoke_sub_agent_node(state: FeedLensState) -> dict:
    """根据 sub_agent_plan 顺序调度执行子 Agent StateGraph。

    子 Agent 通过 ainvoke 传入当前状态，执行后合并结果。

    Returns:
        包含各子 Agent 执行结果的状态更新
    """
    plan = state.get("sub_agent_plan", [])
    if not plan:
        print("[invoke_sub_agent] 计划为空，跳过", flush=True)
        return {}

    # 当前 ReAct 轮次
    react_cycle = state.get("react_cycle_count", 0)

    results = {}
    current_state = dict(state)
    # 记录各子 Agent 执行状态：成功(success) / 失败(isolated) / 未执行(not_executed)
    agent_status = {}
    # 记录各子 Agent 耗时
    agent_timing = {}

    for step in plan:
        agent_name = step.get("agent", "")
        params = step.get("params", {})

        print(f"[invoke_sub_agent] 执行子 Agent: {agent_name} (ReAct 第 {react_cycle} 轮)", flush=True)

        # 通过 run_with_isolation 隔离每个子 Agent：单个失败不阻断本轮其余子 Agent 调度
        builder = {
            "Collection": build_collection_agent,
            "Ranking": build_ranking_agent,
            "Briefing": build_briefing_agent,
        }.get(agent_name)

        if builder is None:
            print(f"[invoke_sub_agent] 未知子 Agent: {agent_name}", flush=True)
            agent_status[agent_name] = "not_executed"
            continue

        result_key = {"Collection": "collection_result", "Ranking": "ranking_result", "Briefing": "briefing_result"}[agent_name]
        # 把 plan 的 params 注入当前 state，让子 Agent 能读到 expand_threshold / search_expand 等
        if isinstance(params, dict) and params:
            current_state = {**current_state, **params}

        t_agent_start = time.perf_counter()
        result = run_with_isolation(
            f"sub_agent_{agent_name}",
            lambda b=builder, cs=current_state: b().invoke(cs),
            default_return={},
        )
        t_agent_elapsed = time.perf_counter() - t_agent_start
        agent_timing[agent_name] = round(t_agent_elapsed, 2)

        if isinstance(result, dict) and result:
            current_state.update(result)
            results[result_key] = result
            agent_status[agent_name] = "success"
            if agent_name == "Collection":
                print(f"[invoke_sub_agent] Collection 完成: {len(result.get('collected_items', []))} 条, 耗时={t_agent_elapsed:.2f}s", flush=True)
            elif agent_name == "Ranking":
                print(f"[invoke_sub_agent] Ranking 完成: {len(result.get('ranked_items', []))} 条, 耗时={t_agent_elapsed:.2f}s", flush=True)
            elif agent_name == "Briefing":
                print(f"[invoke_sub_agent] Briefing 完成, 耗时={t_agent_elapsed:.2f}s", flush=True)
        else:
            # 隔离返回默认值 {}（子 Agent 失败已记录日志），保留错误标记供 observe_results 评估
            results[f"{agent_name.lower()}_error"] = "isolated_failure"
            agent_status[agent_name] = "isolated"
            print(f"[invoke_sub_agent] {agent_name} 已隔离降级（返回默认空结果）", flush=True)

    # 将子 Agent 执行结果同步到顶层字段
    # 关键：仅将本轮成功执行的结果写入 state，失败的子 Agent 对应字段不覆盖（保留旧值供观察）
    # 但通过 agent_status 记录各 Agent 状态，供 observe_results 区分「失败」和「未执行」
    return_update = {
        "sub_agent_plan": [],  # 清空计划，防止 router 认为"尚未执行"而反复路由
        "sub_agent_executed": True,  # 标记本轮计划已执行，供 router 决策
        "current_sub_agent": plan[-1].get("agent", "") if plan else "",
        "collection_result": results.get("collection_result", {}),
        "ranking_result": results.get("ranking_result", {}),
        "briefing_result": results.get("briefing_result", {}),
        "agent_status": agent_status,  # 新增：各子 Agent 执行状态
        "agent_timing": agent_timing,  # 新增：各子 Agent 耗时
    }

    # 仅当对应子 Agent 成功执行时才覆盖数据字段，防止隔离失败时残留旧数据
    if agent_status.get("Collection") == "success":
        return_update["collected_items"] = current_state.get("collected_items", [])
    if agent_status.get("Ranking") == "success":
        return_update["ranked_items"] = current_state.get("ranked_items", [])
        return_update["deduped_items"] = current_state.get("deduped_items", [])
        return_update["item_relations"] = current_state.get("item_relations", [])
        return_update["ranking_detail"] = current_state.get("ranking_detail", {})
    if agent_status.get("Briefing") == "success":
        return_update["brief_quality"] = current_state.get("brief_quality", 0.0)
        return_update["quality_detail"] = current_state.get("quality_detail", {})
        # 修复：必须显式写入 briefing 字段，防止 coordinator_reflect 被跳过时丢失
        if current_state.get("briefing"):
            return_update["briefing"] = current_state["briefing"]

    return return_update


def observe_results_node(state: FeedLensState) -> dict:
    """返回结构化观察摘要，供 planner (LLM) 自主决策。
    策略逻辑已提取为 observe.evaluate hook（P1），可注册自定义实现。
    Returns:
        observation_result: {collection_ok, ranking_ok, briefing_ok, needs_retry, issues, ...}
    """
    collected = state.get("collected_items", [])
    ranked = state.get("ranked_items", [])
    ranking_detail = state.get("ranking_detail", {})
    # 简报质量默认 0.0：若 Briefing 从未被调度，不应误判为"质量完美"
    brief_quality = state.get("brief_quality", 0.0)
    react_cycle = state.get("react_cycle_count", 0)
    ctx = hooks.run("observe.evaluate", {
        "collected": collected,
        "ranked": ranked,
        "top_score": ranking_detail.get("top_score", 0),
        "brief_quality": brief_quality,
        "react_cycle": react_cycle,
        "threshold_collection": 3,
        "threshold_ranking": 0.3,
        "threshold_briefing": 0.7,
        "expected_brief_items": 10,
        # P1-08-fix: 传递简报摘要，用于判断是否已达内部重试上限
        "briefing_summary": state.get("briefing_result", {}).get("briefing_summary", ""),
    })
    observation = {
        "collection_ok": ctx.get("collection_ok", len(collected) >= 3),
        "collection_count": len(collected),
        "ranking_ok": ctx.get("ranking_ok", False),
        "ranking_top_score": ranking_detail.get("top_score", 0.0),
        "briefing_ok": ctx.get("briefing_ok", brief_quality >= 0.7),
        "briefing_quality": brief_quality,
        "briefing_count": len(ranked),
        "briefing_count_ok": ctx.get("briefing_count_ok", False),
        "suggested_action": ctx.get("suggested_action"),
        "react_cycle": react_cycle,
        "needs_retry": ctx.get("needs_retry", True),
        "issues": ctx.get("issues", []),
    }
    print(f"[observe] {'[WARN]' if observation['needs_retry'] else '[OK]'} "
          f"{'; '.join(observation['issues']) if observation['issues'] else '质量合格'}", flush=True)
    return {
        "observation_result": observation,
        "react_cycle_count": react_cycle + 1,
    }
def coordinator_reflect_node(state: FeedLensState) -> dict:
    """综合质量审查：完整性 + 去重遗漏 + 可追溯性 + 矛盾检查。
    策略逻辑已提取为 reflect.check hook（P1）。
    Returns:
        coordinator_observation: 综合审查结果
        briefing: 简报内容
    """
    obs = state.get("observation_result", {})
    ranking_result = state.get("ranking_result", {})
    briefing_result = state.get("briefing_result", {})
    ranked_items = ranking_result.get("ranked_items", state.get("ranked_items", []))
    item_relations = ranking_result.get("item_relations", state.get("item_relations", []))
    # 提取简报内容
    briefing = briefing_result.get("briefing", {})
    if not briefing and "briefing_result" in state:
        briefing = state.get("briefing_result", {}).get("briefing", {})
    brief_quality = obs.get("briefing_quality", state.get("brief_quality", 0.0))
    react_cycles = state.get("react_cycle_count", 0)
    # 调用 hook 做综合质量评估（P1）
    ctx = hooks.run("reflect.check", {
        "ranked_items": ranked_items,
        "item_relations": item_relations,
        "briefing": briefing,
        "brief_quality": brief_quality,
        "react_cycles": react_cycles,
    })
    coordinator_obs = {
        "completeness": ctx.get("completeness", 1.0),
        "dedup_coverage": ctx.get("dedup_coverage", 1.0),
        "traceability": ctx.get("traceability", 1.0),
        "dedup_quality": ctx.get("dedup_quality", 1.0),
        "brief_quality": round(brief_quality, 2),
        "contradictions": ctx.get("contradictions", []),
        "issues": ctx.get("issues", []),
        "react_cycles": react_cycles,
        "dimensions": ctx.get("dimensions", {
            "completeness": {"score": 1.0, "pass": True},
            "dedup": {"score": 1.0, "pass": True},
            "traceability": {"score": 1.0, "pass": True},
        }),
        "overall_pass": ctx.get("overall_pass", True),
    }
    print(f"[coordinator_reflect] 综合审查: issues={len(coordinator_obs['issues'])}, "
          f"contradictions={len(coordinator_obs['contradictions'])}, "
          f"pass={coordinator_obs['overall_pass']}", flush=True)
    return {
        "coordinator_observation": coordinator_obs,
        "briefing": briefing,
    }
def push_notification_node(state: FeedLensState) -> dict:
    """调用 MCP push_notification (stdio) 推送简报。

    优先推送 briefing._markdown 或 briefing JSON，
    失败时降级为 ranked_items 摘要。

    Returns:
        push_status: pending | sent | failed
        push_message: 推送结果描述
    """
    briefing = state.get("briefing", {})
    user_id = state.get("user_id", 1)
    push_immediate = state.get("push_immediate", False)
    ranked_items = state.get("ranked_items", [])
    coordinator_obs = state.get("coordinator_observation", {})

    print(f"[push_notification] 开始推送: user_id={user_id}, immediate={push_immediate}", flush=True)

    # 构建推送内容（适配 briefing_agent 的 categories 结构）
    if briefing:
        # 优先使用 Markdown 渲染版本
        markdown_content = briefing.get("_markdown", "")
        push_content = {
            "title": briefing.get("title", "FeedLens 每日简报"),
            "summary": briefing.get("summary", ""),
            "categories": briefing.get("categories", []),
            "markdown": markdown_content,
            "generated_at": datetime.now().isoformat(),
        }
    else:
        # 降级：使用 ranked_items 摘要
        summary_items = []
        for item in ranked_items[:5]:
            summary_items.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "importance": item.get("importance", 0.5),
            })
        push_content = {
            "title": "FeedLens 每日简报（摘要版）",
            "items": summary_items,
            "generated_at": datetime.now().isoformat(),
        }

    try:
        from tools.mcp_client import push_notification as _push_notification
        success = _push_notification(
            brief=push_content,
            user_id=user_id,
            immediate=push_immediate,
        )
        if success:
            print(f"[push_notification] 推送成功", flush=True)
            return {
                "push_status": "sent",
                "push_message": "简报已推送至通知队列",
            }
        else:
            print(f"[push_notification] 推送返回失败", flush=True)
            return {
                "push_status": "failed",
                "push_message": "MCP push 返回失败",
            }
    except Exception as e:
        print(f"[push_notification] 推送异常: {e}", flush=True)
        return {
            "push_status": "failed",
            "push_message": f"推送异常: {e}",
        }


def update_memory_node(state: FeedLensState) -> dict:
    """更新偏好 + 写入执行日志 + 摘要写入长期记忆。

    FeedLens 场景适配：
      1. 写入情节记忆（SQLite execution_logs）
      2. LLM 摘要本次执行 → 写入长期记忆（ChromaDB）
      3. 写入 run_logs / briefs / 偏好向量

    Returns:
        execution_log: 执行日志
        status: completed
    """
    user_id = state.get("user_id", 1)
    session_id = state.get("session_id", "")
    ranked_items = state.get("ranked_items", [])
    briefing = state.get("briefing", {})
    coordinator_obs = state.get("coordinator_observation", {})
    planner_reason = state.get("planner_reason", "")
    react_cycle = state.get("react_cycle_count", 0)
    trigger_type = state.get("trigger_type", "daily_briefing")

    print(f"[update_memory] 更新记忆: user_id={user_id}", flush=True)

    # 构建执行结果摘要（供记忆系统使用）
    collected_count = len(state.get("collected_items", []))
    ranked_count = len(ranked_items)
    brief_quality_val = state.get("brief_quality", 0.0)

    execution_result = {
        "collected_count": collected_count,
        "ranked_count": ranked_count,
        "brief_quality": brief_quality_val,
        "trigger_type": trigger_type,
        "react_cycle_count": react_cycle,
        "push_status": state.get("push_status", "pending"),
    }

    # 写入本轮 planner 决策经验到记忆系统（情节记忆 + 长期记忆）
    try:
        obs = state.get("observation_result", {})
        planner_decision = state.get("sub_agent_plan", [])
        add_memory(
            session_id=session_id,
            event="planner_decision",
            node_name="planner",
            content={
                "situation": f"采集{collected_count}条 排序top{state.get('ranking_detail', {}).get('top_score', 0):.2f} 简报质量{brief_quality_val:.2f}",
                "decision": planner_decision,
                "reason": planner_reason,
                "outcome": "retry_needed" if obs.get("needs_retry") else "ok",
                "trigger": trigger_type,
            },
            status="completed",
            execution_result=execution_result,
            planner_decision={"sub_agent_plan": planner_decision, "reason": planner_reason},
            trigger_type=trigger_type,
        )
        print(f"[update_memory] planner 决策经验已写入记忆系统（SQLite + ChromaDB）", flush=True)
    except Exception as e:
        print(f"[update_memory] 决策经验写入失败: {e}", flush=True)


    # 写入执行日志
    execution_log = {
        "session_id": session_id,
        "user_id": user_id,
        "trigger_type": state.get("trigger_type", "daily_briefing"),
        "planner_reason": planner_reason,
        "react_cycle_count": react_cycle,
        "collected_count": len(state.get("collected_items", [])),
        "ranked_count": len(ranked_items),
        "brief_quality": coordinator_obs.get("completeness", 0.0),
        "push_status": state.get("push_status", "pending"),
        "executed_at": datetime.now().isoformat(),
        "issues": coordinator_obs.get("issues", []),
    }

    try:
        from models.database import Database
        db = Database(_get_db_path())
        db.insert_run_log(
            trigger_type=state.get("trigger_type", "daily_briefing"),
            items_collected=len(state.get("collected_items", [])),
            items_deduped=len(ranked_items),
            dedup_rate=None,
            brief_quality_score=coordinator_obs.get("completeness", 0.0),
            duration_ms=None,
        )
        print(f"[update_memory] 执行日志写入成功", flush=True)
    except Exception as e:
        print(f"[update_memory] 执行日志写入失败: {e}", flush=True)

    # 保存简报到 briefs 表 + briefing_items + deduped_items
    # 优先从 state.briefing 取，回退到 state.briefing_result.briefing（兼容 coordinator_reflect 被跳过的情况）
    briefing_data = state.get("briefing", {})
    if not briefing_data or not briefing_data.get("title"):
        briefing_result = state.get("briefing_result", {})
        briefing_data = briefing_result.get("briefing", {})
        if briefing_data and briefing_data.get("title"):
            print("[update_memory] briefing 字段为空，从 briefing_result 回退提取成功", flush=True)
    ranked_items = state.get("ranked_items", [])
    if briefing_data and briefing_data.get("title"):
        try:
            db2 = Database(_get_db_path())
            user_id_local = state.get("user_id", 1)
            quality_score = state.get("brief_quality", 0.0)

            content_json = json.dumps(briefing_data, ensure_ascii=False)
            content_md = briefing_data.get("_markdown", "")
            with db2.get_connection() as conn:
                cursor = conn.execute(
                    """INSERT INTO briefs (user_id, content_json, content_md, quality_score)
                       VALUES (?, ?, ?, ?)""",
                    (user_id_local, content_json, content_md, quality_score),
                )
                brief_id = cursor.lastrowid

                # 写入 ranked_items → deduped_items + briefing_items
                for rank, item in enumerate(ranked_items, start=1):
                    item_id_str = item.get("id", "")
                    title = item.get("title", "")
                    summary = item.get("summary", "")
                    url = item.get("url", "")
                    source = item.get("source_name", item.get("source_url", item.get("source", "")))
                    published_at = item.get("published_at", "")
                    importance = item.get("importance", 0.5)
                    category = item.get("category", "其他")
                    final_score = item.get("_score", 0.0)
                    is_highlight = 1 if item.get("is_highlight") else 0

                    # 1) 写入 raw_items（如果还不存在）
                    raw_id = None
                    if url:
                        existing = conn.execute(
                            "SELECT id FROM raw_items WHERE url = ? LIMIT 1", (url,)
                        ).fetchone()
                        if existing:
                            raw_id = existing["id"]
                    if raw_id is None:
                        raw_cursor = conn.execute(
                            """INSERT INTO raw_items (title, summary, url, published_at)
                               VALUES (?, ?, ?, ?)""",
                            (title, summary, url, published_at or datetime.now().isoformat()),
                        )
                        raw_id = raw_cursor.lastrowid

                    # 2) 写入 deduped_items
                    dedup_cursor = conn.execute(
                        """INSERT INTO deduped_items (representative_item_id, similar_count, category, importance)
                           VALUES (?, ?, ?, ?)""",
                        (raw_id, item.get("similar_count", 1), category, importance),
                    )
                    dedup_id = dedup_cursor.lastrowid

                    # 3) 写入 briefing_items
                    conn.execute(
                        """INSERT INTO briefing_items (briefing_id, item_id, rank, final_score, is_highlight)
                           VALUES (?, ?, ?, ?, ?)""",
                        (brief_id, dedup_id, rank, final_score, is_highlight),
                    )

            print(f"[update_memory] 简报已保存: brief_id={brief_id}, items={len(ranked_items)}", flush=True)
        except Exception as e:
            import traceback
            print(f"[update_memory] 简报保存失败: {e}", flush=True)
            traceback.print_exc()

    # 更新 ChromaDB 偏好向量（取 top 3 条的正向偏好）
    if ranked_items:
        try:
            embedding_model = EmbeddingModel()
            vs = VectorStore(persist_dir="data/chroma", embedding_fn=embedding_model.encode)
            vs.init_collections()

            for item in ranked_items[:3]:
                text = f"{item.get('title', '')} {item.get('summary', '')}"
                if text.strip():
                    emb = embedding_model.encode_single(text)
                    pref_col = vs.get_collection("user_preference")
                    pref_col.add(
                        ids=[f"pref_{session_id}_{item.get('id', '')}"],
                        documents=[text],
                        metadatas=[{"user_id": str(user_id), "preference_type": "like"}],
                    )
            print(f"[update_memory] 偏好向量更新完成", flush=True)
        except Exception as e:
            print(f"[update_memory] 偏好向量更新失败: {e}", flush=True)

    # 🆕 写入条目历史向量到 ChromaDB feed_items（用于跨批次预过滤去重）
    # 使用 URL+title hash 作为 ChromaDB ID，确保幂等：相同条目多次执行不产生重复向量
    if ranked_items:
        try:
            embedding_model2 = EmbeddingModel()
            vs2 = VectorStore(persist_dir="data/chroma", embedding_fn=embedding_model2.encode)
            vs2.init_collections()

            now_iso = datetime.now().isoformat()
            ids, docs, metas = [], [], []
            for item in ranked_items:
                url = item.get("url", "")
                title = item.get("title", "")
                summary = item.get("summary", "")
                text = f"{title} {summary}".strip()
                if not text:
                    continue
                # 使用 URL+title 的 SHA256 hash 作为 ChromaDB ID，确保同内容幂等
                content_key = f"{url}|{title}"
                item_hash = hashlib.sha256(content_key.encode("utf-8")).hexdigest()[:32]
                ids.append(item_hash)
                docs.append(text)
                metas.append({
                    "created_at": now_iso,
                    "url": url,
                    "source": item.get("source_name", item.get("source", "")),
                    "title": title[:200],
                })
            if ids:
                vs2.upsert_items(
                    collection="feed_items",
                    ids=ids,
                    documents=docs,
                    metadatas=metas,
                )
                print(f"[update_memory] 条目历史向量写入 ChromaDB: {len(ids)} 条", flush=True)
        except Exception as e:
            print(f"[update_memory] 条目历史向量写入失败（不影响主流程）: {e}", flush=True)

    return {
        "execution_log": execution_log,
        "status": "completed",
    }


# ============================================================
# P1 默认 Hook 实现（策略注册，提取硬编码逻辑为可替换 Hook）
# ============================================================

def _default_observe_evaluate(ctx: dict) -> dict:
    """默认质量评估策略：阈值判断 + issues 生成 + suggested_action。

    注册为 observe.evaluate hook。ctx 含 collected/ranked/top_score/
    brief_quality/阈值配置，返回 collection_ok/ranking_ok/.../needs_retry/
    issues/suggested_action。

    P0-2.2 优化：新增 prescreen_too_strict 判断，区分"预筛过严导致条目少"
    与"排序算法真正失败"。当采集充足但排序后条目极少时，标记为预筛过严，
    避免 needs_retry=True 触发完整三板斧重跑。
    """
    collected = ctx.get("collected", [])
    ranked = ctx.get("ranked", [])
    top_score = ctx.get("top_score", 0)
    # 简报质量默认 0.0：若 Briefing 从未被调度，不应误判为"质量完美"
    brief_quality = ctx.get("brief_quality", 0.0)
    th_coll = ctx.get("threshold_collection", 3)
    th_rank = ctx.get("threshold_ranking", 0.3)
    th_brief = ctx.get("threshold_briefing", 0.7)
    expected = ctx.get("expected_brief_items", 10)

    collection_ok = len(collected) >= th_coll

    # P0-2.2: 预筛过严检测 — 采集充足但排序后条目极少（如 62→1）
    # 此时 top_score 自然低（条目少），不应归咎于排序算法
    prescreen_too_strict = (
        collection_ok
        and len(collected) >= expected
        and len(ranked) < max(th_coll, expected // 2)
    )
    if prescreen_too_strict:
        ranking_ok = True  # 不归咎排序，避免 needs_retry 触发完整重跑
        print(f"[observe] 检测到预筛过严: collected={len(collected)} -> ranked={len(ranked)}，"
              f"建议 expand_threshold 而非重跑排序", flush=True)
    else:
        ranking_ok = bool(ranked and top_score >= th_rank)

    # 简报质量评估：需同时检查 brief_quality > 0（是否真正生成）和评分达标
    briefing_ok = brief_quality > 0 and brief_quality >= th_brief
    briefing_count_ok = len(ranked) >= expected
    suggest_expand = (not briefing_count_ok) and (len(collected) >= expected)

    # P1-08-fix: 如果 Briefing Agent 内部已达重试上限，不再触发 Planner 重试
    # 避免 Planner 重新调度整个 Briefing Agent 做无用功
    briefing_summary = ctx.get("briefing_summary", "")
    briefing_exhausted = ("已达最大重试次数" in briefing_summary or
                          "强制收敛" in briefing_summary)
    if briefing_exhausted and brief_quality > 0 and not briefing_ok:
        # Briefing 已尽力但未达标 → 标记为 OK（接受当前结果），避免浪费 API
        briefing_ok = True
        print(f"[observe] Briefing Agent 内部已达重试上限 (quality={brief_quality:.4f})，"
              f"接受当前结果不再重试", flush=True)

    needs_retry = not (collection_ok and ranking_ok and briefing_ok and briefing_count_ok)

    issues = []
    suggested_action = None
    if not collection_ok:
        issues.append(f"采集不足: {len(collected)} 条 < {th_coll}")
        suggested_action = "search_expand"
    if prescreen_too_strict:
        issues.append(f"预筛过严: collected={len(collected)} -> ranked={len(ranked)} (预筛窗口过窄)")
        suggested_action = "expand_threshold"
    elif not ranking_ok:
        issues.append(f"排序不佳: top_score={top_score:.2f} < {th_rank}")
    if brief_quality <= 0:
        issues.append("简报未生成")
        suggested_action = suggested_action or "briefing"
    elif not briefing_ok:
        issues.append(f"简报质量低: score={brief_quality:.2f} < {th_brief}")
    if not briefing_count_ok and not prescreen_too_strict:
        issues.append(f"简报条目不足: {len(ranked)}/{expected}")
        if suggest_expand:
            suggested_action = "expand_threshold"
        elif suggested_action is None:
            suggested_action = "search_expand"

    return {
        "collection_ok": collection_ok,
        "ranking_ok": ranking_ok,
        "briefing_ok": briefing_ok,
        "briefing_count_ok": briefing_count_ok,
        "needs_retry": needs_retry,
        "issues": issues,
        "suggested_action": suggested_action,
        "prescreen_too_strict": prescreen_too_strict,
    }

hooks.register("observe.evaluate", _default_observe_evaluate)




def _default_reflect_check(ctx: dict) -> dict:
    """默认综合质量审查策略（完整性 + 去重 + 追溯 + 矛盾）。

    注册为 reflect.check hook。
    """
    ranked_items = ctx.get("ranked_items", [])
    item_relations = ctx.get("item_relations", [])
    briefing = ctx.get("briefing", {})
    brief_quality = ctx.get("brief_quality", 0.0)
    react_cycles = ctx.get("react_cycles", 0)

    issues = []
    contradictions = []

    # 1. 完整性检查
    if len(ranked_items) == 0:
        issues.append("无排序条目")

    # 2. 简报质量检查
    if brief_quality < 0.5:
        issues.append(f"简报质量过低 ({brief_quality:.2f})")

    # 3. 去重检查：similar_count > 1 的条目是否有标注
    high_similar = [item for item in ranked_items if item.get("similar_count", 1) > 1]
    if high_similar and not any("类似报道" in str(item.get("title", "")) for item in ranked_items):
        issues.append(f"{len(high_similar)} 条高相似条目可能缺少「类似报道」标注")

    # 4. 矛盾检查（使用 briefing_agent 的 _check_contradiction）
    if briefing:
        from agents.briefing_agent import _check_contradiction
        categories = briefing.get("categories", [])
        all_brief_items = []
        for cat in categories:
            for item in cat.get("items", []):
                all_brief_items.append(item)
        for i_idx in range(len(all_brief_items)):
            for j_idx in range(i_idx + 1, len(all_brief_items)):
                if _check_contradiction(all_brief_items[i_idx], all_brief_items[j_idx]):
                    contradictions.append({
                        "item_a": all_brief_items[i_idx].get("id", ""),
                        "item_b": all_brief_items[j_idx].get("id", ""),
                    })

    # 5. 来源追溯检查
    unreferenced = [item for item in ranked_items if not item.get("url")]
    if unreferenced:
        issues.append(f"{len(unreferenced)} 条条目缺少来源 URL")

    # 6. ReAct 循环次数检查
    if react_cycles >= 3:
        issues.append("ReAct 循环次数过多，可能存在收敛问题")

    completeness = 1.0 if not issues else max(0.0, 1.0 - len(issues) * 0.15)
    dedup_coverage = len(ranked_items) / max(len(ranked_items) + len(item_relations), 1)
    traceability_score = 1.0 - len(unreferenced) * 0.2
    dedup_quality = 1.0 if not high_similar else max(0.3, 1.0 - len(high_similar) * 0.15)

    return {
        "completeness": round(completeness, 2),
        "dedup_coverage": round(dedup_coverage, 2),
        "traceability": round(traceability_score, 2),
        "dedup_quality": round(dedup_quality, 2),
        "contradictions": contradictions,
        "issues": issues,
        "overall_pass": len(issues) == 0 and len(contradictions) == 0 and completeness >= 0.7,
        "dimensions": {
            "completeness": {"score": round(completeness, 2), "pass": completeness >= 0.7},
            "dedup": {"score": round(dedup_quality, 2), "pass": dedup_quality >= 0.7},
            "traceability": {"score": round(traceability_score, 2), "pass": traceability_score >= 0.7},
        },
    }

hooks.register("reflect.check", _default_reflect_check)



def _default_push_decide(ctx: dict) -> dict:
    """默认推送策略：透传 push_immediate。"""
    return {"push_immediate": ctx.get("push_immediate", False)}

hooks.register("push.decide", _default_push_decide)


# ============================================================
# 路由决策函数（从 router_decision 解析 next_node）
# ============================================================

def _router_decide(state: FeedLensState) -> str:
    """条件边函数：从 state.router_decision 中读取 LLM 决策的 next_node。

    供 add_conditional_edges 使用，将 LLM 动态决策映射为 LangGraph 路由目标。
    """
    decision = state.get("router_decision", {})
    next_node = decision.get("next_node", "planner")

    # 验证目标节点是否合法
    valid_nodes = {
        "planner", "invoke_sub_agent", "observe_results",
        "coordinator_reflect", "push_notification", "update_memory",
        "abort", "END",
    }
    if next_node not in valid_nodes:
        print(f"[router_decide] 非法目标节点 '{next_node}'，降级为 planner", flush=True)
        next_node = "planner"

    return next_node


def build_main_agent() -> StateGraph:
    """构建主 Agent StateGraph（Agentic 升级：LLM 全动态路由）。

    Phase 4b 流程（所有边由 router_node LLM 决策）:
      understand_intent → planner → router_node → invoke_sub_agent / planner
                              ↑                         ↓
                              └─── ReAct 循环 ──────────┘
                                                         ↓
                              router_node → observe_results → router_node
                                                                   ↓
                                          coordinator_reflect → router_node
                                                                   ↓
                                          push_notification → router_node
                                                                   ↓
                                          update_memory → END

    关键改造：
      - 所有节点之间的跳转均由 router_node（LLM）自主决策
      - 保留防死循环（连续3次相同路由 → 强制 update_memory）
      - 保留硬兜底（agentic_turn_count >= 8 → 强制结束）
      - observe_results / coordinator_reflect 仍做质量评估，但路由交给 router_node
    """
    workflow = StateGraph(FeedLensState)

    # 节点注册
    workflow.add_node("understand_intent", understand_intent_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("router_node", router_node)
    workflow.add_node("invoke_sub_agent", invoke_sub_agent_node)
    workflow.add_node("observe_results", observe_results_node)
    workflow.add_node("coordinator_reflect", coordinator_reflect_node)
    workflow.add_node("push_notification", push_notification_node)
    workflow.add_node("update_memory", update_memory_node)

    # 入口：understand_intent → planner（初始计划生成固定先走 planner）
    workflow.set_entry_point("understand_intent")
    workflow.add_edge("understand_intent", "planner")

    # planner → router_node（LLM 决策：invoke_sub_agent 还是重新 planner）
    workflow.add_edge("planner", "router_node")

    # router_node 条件边：LLM 自主路由到所有目标节点
    workflow.add_conditional_edges(
        "router_node",
        _router_decide,
        {
            "planner": "planner",
            "invoke_sub_agent": "invoke_sub_agent",
            "observe_results": "observe_results",
            "coordinator_reflect": "coordinator_reflect",
            "push_notification": "push_notification",
            "update_memory": "update_memory",
            "abort": END,
            "END": END,
        },
    )

    # invoke_sub_agent 执行完后 → router_node（LLM 决定走向 observe 还是重新 planner）
    workflow.add_edge("invoke_sub_agent", "router_node")

    # observe_results 评估完后 → router_node（LLM 决定继续 ReAct 还是进入 coordinator_reflect）
    workflow.add_edge("observe_results", "router_node")

    # coordinator_reflect 审查完后 → router_node（LLM 决定推送还是重做）
    workflow.add_edge("coordinator_reflect", "router_node")

    # push_notification 推送完后 → router_node（LLM 决定 update_memory 还是结束）
    workflow.add_edge("push_notification", "router_node")

    # update_memory → END（固定终点）
    workflow.add_edge("update_memory", END)

    return workflow.compile()