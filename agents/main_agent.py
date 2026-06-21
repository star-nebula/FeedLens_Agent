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
- memory.recent_turns: 最近几轮的本会话执行记录
- memory.relevant_history: 过往类似情况的处理经验（可能为空）

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
            content = (resp if isinstance(resp, str) else resp.get("content", "")).strip()
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
        text = response if isinstance(response, str) else response.get("content", "{}")
        plan = _parse_planner_response(text)
        print(f"[planner] LLM 决策: {json.dumps(plan, ensure_ascii=False)}", flush=True)
    except Exception as e:
        print(f"[planner] LLM 调用失败，回退默认: {e}", flush=True)
        plan = _fallback_plan(state)

    print(f"[planner] 编排计划: {[p['agent'] for p in plan.get('sub_agent_plan', [])]}, "
          f"push_immediate={plan.get('push_immediate', False)}", flush=True)

    return {
        "sub_agent_plan": plan.get("sub_agent_plan", []),
        "push_immediate": plan.get("push_immediate", False),
        "planner_reason": plan.get("reason", ""),
    }


def _build_planner_context(state: FeedLensState) -> dict:
    """构建 planner 的 LLM 输入上下文。"""
    obs = state.get("observation_result", {})
    ranking_detail = state.get("ranking_detail", {})
    collected = state.get("collected_items", [])
    top_score = ranking_detail.get("top_score", 0)
    brief_quality = state.get("brief_quality", 0)

    # 记忆检索：用当前状态摘要作为 query，召回相关历史经验（P0）
    memory_query = f"采集{len(collected)}条 排序top{top_score:.2f} 简报质量{brief_quality:.2f}"
    try:
        memory_ctx = get_context(query=memory_query, n_recent=3, n_long_term=3)
        memory_block = {
            "recent_turns": memory_ctx.get("short_term", []),
            "relevant_history": [m.get("document", "") for m in memory_ctx.get("long_term", [])],
        }
    except Exception as e:
        print(f"[planner] 记忆检索失败，降级为空: {e}", flush=True)
        memory_block = {"recent_turns": [], "relevant_history": []}

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
            continue

        result_key = {"Collection": "collection_result", "Ranking": "ranking_result", "Briefing": "briefing_result"}[agent_name]
        # 把 plan 的 params 注入当前 state，让子 Agent 能读到 expand_threshold / search_expand 等
        if isinstance(params, dict) and params:
            current_state = {**current_state, **params}
        result = run_with_isolation(
            f"sub_agent_{agent_name}",
            lambda b=builder, cs=current_state: b().invoke(cs),
            default_return={},
        )
        if isinstance(result, dict) and result:
            current_state.update(result)
            results[result_key] = result
            if agent_name == "Collection":
                print(f"[invoke_sub_agent] Collection 完成: {len(result.get('collected_items', []))} 条", flush=True)
            elif agent_name == "Ranking":
                print(f"[invoke_sub_agent] Ranking 完成: {len(result.get('ranked_items', []))} 条", flush=True)
            elif agent_name == "Briefing":
                print(f"[invoke_sub_agent] Briefing 完成", flush=True)
        else:
            # 隔离返回默认值 {}（子 Agent 失败已记录日志），保留错误标记供 observe_results 评估
            results[f"{agent_name.lower()}_error"] = "isolated_failure"
            print(f"[invoke_sub_agent] {agent_name} 已隔离降级（返回默认空结果）", flush=True)

    # 将子 Agent 执行结果同步到顶层字段
    return {
        "current_sub_agent": plan[-1].get("agent", "") if plan else "",
        "collected_items": current_state.get("collected_items", []),
        "ranked_items": current_state.get("ranked_items", []),
        "deduped_items": current_state.get("deduped_items", []),
        "item_relations": current_state.get("item_relations", []),
        "ranking_detail": current_state.get("ranking_detail", {}),
        "collection_result": results.get("collection_result", {}),
        "ranking_result": results.get("ranking_result", {}),
        "briefing_result": results.get("briefing_result", {}),
        "brief_quality": current_state.get("brief_quality", 0.0),
        "quality_detail": current_state.get("quality_detail", {}),
    }


def observe_results_node(state: FeedLensState) -> dict:
    """返回结构化观察摘要，供 planner (LLM) 自主决策。
    策略逻辑已提取为 observe.evaluate hook（P1），可注册自定义实现。
    Returns:
        observation_result: {collection_ok, ranking_ok, briefing_ok, needs_retry, issues, ...}
    """
    collected = state.get("collected_items", [])
    ranked = state.get("ranked_items", [])
    ranking_detail = state.get("ranking_detail", {})
    brief_quality = state.get("brief_quality", 1.0)
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
    """更新偏好 + 写入执行日志。

    1. 如果有新的 ranked_items，更新 ChromaDB 偏好向量
    2. 写入 execution_logs 表

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

    print(f"[update_memory] 更新记忆: user_id={user_id}", flush=True)
    # 写入本轮 planner 决策经验到记忆系统（供后续 planner 检索，P0）
    try:
        obs = state.get("observation_result", {})
        add_memory(
            session_id=session_id,
            event="planner_decision",
            node_name="planner",
            content={
                "situation": f"采集{len(state.get('collected_items', []))} 排序top{state.get('ranking_detail', {}).get('top_score', 0):.2f} 简报质量{state.get('brief_quality', 0):.2f}",
                "decision": state.get("sub_agent_plan", []),
                "reason": planner_reason,
                "outcome": "retry_needed" if obs.get("needs_retry") else "ok",
                "trigger": state.get("trigger_type", ""),
            },
            status="completed",
        )
        print(f"[update_memory] planner 决策经验已写入记忆系统", flush=True)
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

    # 保存简报到 briefs 表
    briefing_data = state.get("briefing", {})
    if briefing_data and briefing_data.get("title"):
        try:
            db2 = Database(_get_db_path())
            user_id_local = state.get("user_id", 1)
            quality_score = state.get("brief_quality", 0.0)

            content_json = json.dumps(briefing_data, ensure_ascii=False)
            content_md = briefing_data.get("_markdown", "")
            with db2.get_connection() as conn:
                conn.execute(
                    """INSERT INTO briefs (user_id, content_json, content_md, quality_score)
                       VALUES (?, ?, ?, ?)""",
                    (user_id_local, content_json, content_md, quality_score),
                )
            print(f"[update_memory] 简报已保存到数据库", flush=True)
        except Exception as e:
            print(f"[update_memory] 简报保存失败: {e}", flush=True)

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

    return {
        "execution_log": execution_log,
        "status": "completed",
    }


# ============================================================
# 条件边
# ============================================================


def should_continue_react(state: FeedLensState) -> str:
    """判断是否继续 ReAct 循环。

    observe_results 之后调用：
      - needs_retry=True 且 react_cycle_count < max_react_cycles → 回退 planner
      - 否则 → coordinator_reflect
    """
    obs = state.get("observation_result", {})
    cycle = state.get("react_cycle_count", 0)
    max_cycles = 3

    if obs.get("needs_retry") and cycle < max_cycles:
        print(f"[should_continue_react] ReAct 第 {cycle} 轮，观察建议重试，进入下一轮", flush=True)
        return "planner"

    print(f"[should_continue_react] ReAct 结束，进入 coordinator_reflect", flush=True)
    return "coordinator_reflect"


def should_push_now(state: FeedLensState) -> str:
    """判断是否立即推送（重大事件）。

    策略逻辑已提取为 push.decide hook（P1），可注册自定义推送策略
    （如特定主题破例推送、夜间静默等）。

    当前设计：所有情况都走 push_notification 节点，
    push_immediate 标记仅影响推送 urgency（立即 vs 排队）。
    """
    push_immediate = state.get("push_immediate", False)
    ctx = hooks.run("push.decide", {
        "push_immediate": push_immediate,
        "trigger_type": state.get("trigger_type", "daily_briefing"),
    })
    immediate = ctx.get("push_immediate", push_immediate)

    if immediate:
        print(f"[should_push_now] 重大事件，立即推送", flush=True)
    else:
        print(f"[should_push_now] 日常简报，正常推送", flush=True)
    return "push_notification"
# ============================================================
# StateGraph 构建
# ============================================================




# ============================================================
# P1 默认 Hook 实现（策略注册，提取硬编码逻辑为可替换 Hook）
# ============================================================

def _default_observe_evaluate(ctx: dict) -> dict:
    """默认质量评估策略：阈值判断 + issues 生成 + suggested_action。

    注册为 observe.evaluate hook。ctx 含 collected/ranked/top_score/
    brief_quality/阈值配置，返回 collection_ok/ranking_ok/.../needs_retry/
    issues/suggested_action。
    """
    collected = ctx.get("collected", [])
    ranked = ctx.get("ranked", [])
    top_score = ctx.get("top_score", 0)
    brief_quality = ctx.get("brief_quality", 1.0)
    th_coll = ctx.get("threshold_collection", 3)
    th_rank = ctx.get("threshold_ranking", 0.3)
    th_brief = ctx.get("threshold_briefing", 0.7)
    expected = ctx.get("expected_brief_items", 10)

    collection_ok = len(collected) >= th_coll
    ranking_ok = bool(ranked and top_score >= th_rank)
    briefing_ok = brief_quality >= th_brief
    briefing_count_ok = len(ranked) >= expected
    suggest_expand = (not briefing_count_ok) and (len(collected) >= expected)
    needs_retry = not (collection_ok and ranking_ok and briefing_ok and briefing_count_ok)

    issues = []
    suggested_action = None
    if not collection_ok:
        issues.append(f"采集不足: {len(collected)} 条 < {th_coll}")
        suggested_action = "search_expand"
    if not ranking_ok:
        issues.append(f"排序不佳: top_score={top_score:.2f} < {th_rank}")
    if not briefing_ok:
        issues.append(f"简报质量低: score={brief_quality:.2f} < {th_brief}")
    if not briefing_count_ok:
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
def build_main_agent() -> StateGraph:
    """构建主 Agent StateGraph。

    流程: understand_intent → planner → invoke_sub_agent → observe_results
                     ↑                                              ↓
                     └──────────── ReAct 循环 (< 3 次) ────────────┘
                                                                    ↓
                                           coordinator_reflect → should_push_now?
                                                                            ↓
                                              push_notification → update_memory → END
    """
    workflow = StateGraph(FeedLensState)

    # 节点
    workflow.add_node("understand_intent", understand_intent_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("invoke_sub_agent", invoke_sub_agent_node)
    workflow.add_node("observe_results", observe_results_node)
    workflow.add_node("coordinator_reflect", coordinator_reflect_node)
    workflow.add_node("push_notification", push_notification_node)
    workflow.add_node("update_memory", update_memory_node)

    # 主流程
    workflow.set_entry_point("understand_intent")
    workflow.add_edge("understand_intent", "planner")
    workflow.add_edge("planner", "invoke_sub_agent")
    workflow.add_edge("invoke_sub_agent", "observe_results")

    # ReAct 循环条件边
    workflow.add_conditional_edges(
        "observe_results",
        should_continue_react,
        {"planner": "planner", "coordinator_reflect": "coordinator_reflect"},
    )

    # coordinator_reflect 之后：重大事件立即推送，日常简报正常推送
    workflow.add_conditional_edges(
        "coordinator_reflect",
        should_push_now,
        {"push_notification": "push_notification", "update_memory": "update_memory"},
    )
    workflow.add_edge("push_notification", "update_memory")
    workflow.add_edge("update_memory", END)

    return workflow.compile()