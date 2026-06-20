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
from agents.state import FeedLensState
from agents.collection_agent import build_collection_agent, _get_rss_sources, _get_search_query
from agents.ranking_agent import build_ranking_agent
from agents.briefing_agent import build_briefing_agent
from tools.mcp_client import PushMCPClient
from models.vector_store import VectorStore
from utils.embedding import EmbeddingModel
from utils.llm_provider import DeepSeekProvider
from tools import db_read, db_write


# ============================================================
# 配置加载
# ============================================================

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
            content = resp.get("content", "").strip()
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
    """planner 自主编排子 Agent（ReAct 的 Think 步骤）。

    7 个决策场景：
      ① 正常每日简报: Collection → Ranking → Briefing
      ② 采集不足: Collection → (items<5) → 补充搜索 → Ranking → Briefing
      ③ 排序不理想: Collection → Ranking → (score<0.3) → 重排 → Briefing
      ④ 重大事件推送: Collection → Ranking → Briefing → PushNow
      ⑤ 跳过采集: Ranking → Briefing (使用上轮结果，不重新采集)
      ⑥ 跳过简报: Collection → Ranking → Push摘要 (内容太多)
      ⑦ 空数据回退: Collection → (items=0) → 扩大时间窗重新采集

    MVP 简化：固定执行 ①，其他场景的检测逻辑在其他节点实现。

    Returns:
        sub_agent_plan: 子 Agent 执行计划
        push_immediate: 是否立即推送
        planner_reason: 决策理由
    """
    trigger_type = state.get("trigger_type", "daily_briefing")
    react_cycle = state.get("react_cycle_count", 0)
    obs = state.get("observation_result", {})
    ranked_items = state.get("ranked_items", [])
    collection_result = state.get("collected_items", [])

    print(f"[planner] ReAct 第 {react_cycle} 轮, trigger={trigger_type}", flush=True)

    # 判断编排策略
    if obs:
        suggested = obs.get("suggested_action", "")
        if "retry_collection" in suggested:
            plan = [{"agent": "Collection", "params": {"retry": True}}]
            reason = "观察结果建议重试采集"
        elif "retry_ranking" in suggested:
            plan = [{"agent": "Ranking", "params": {"rerank": True}}]
            reason = "观察结果建议重新排序"
        else:
            plan = [{"agent": "Collection", "params": {}}, {"agent": "Ranking", "params": {}}, {"agent": "Briefing", "params": {}}]
            reason = "标准流程编排"
    elif react_cycle > 0:
        # ReAct 再思考：基于之前的观察结果调整
        plan = [{"agent": "Collection", "params": {}}, {"agent": "Ranking", "params": {}}, {"agent": "Briefing", "params": {}}]
        reason = "ReAct 循环继续执行"
    else:
        # 首次编排：固定执行采集→排序→简报
        plan = [{"agent": "Collection", "params": {}}, {"agent": "Ranking", "params": {}}, {"agent": "Briefing", "params": {}}]
        reason = "首次编排：标准每日简报流程"

    # 重大事件检测
    push_immediate = False
    if ranked_items and len(ranked_items) > 0:
        top_item = ranked_items[0]
        top_score = top_item.get("_score", 0.0)
        top_importance = top_item.get("importance", 0.5)
        published_at = top_item.get("published_at", "")
        if top_score > 0.85 and top_importance >= 0.9:
            push_immediate = True
            print(f"[planner] 重大事件检测: top_score={top_score:.4f}, 触发立即推送", flush=True)

    print(f"[planner] 编排计划: {[p['agent'] for p in plan]}, push_immediate={push_immediate}", flush=True)
    return {
        "sub_agent_plan": plan,
        "push_immediate": push_immediate,
        "planner_reason": reason,
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

        try:
            if agent_name == "Collection":
                agent = build_collection_agent()
                result = agent.invoke(current_state)
                current_state.update(result)
                results["collection_result"] = result
                print(f"[invoke_sub_agent] Collection 完成: {len(result.get('collected_items', []))} 条", flush=True)

            elif agent_name == "Ranking":
                agent = build_ranking_agent()
                result = agent.invoke(current_state)
                current_state.update(result)
                results["ranking_result"] = result
                ranked = result.get("ranked_items", [])
                print(f"[invoke_sub_agent] Ranking 完成: {len(ranked)} 条", flush=True)

            elif agent_name == "Briefing":
                agent = build_briefing_agent()
                result = agent.invoke(current_state)
                current_state.update(result)
                results["briefing_result"] = result
                print(f"[invoke_sub_agent] Briefing 完成", flush=True)

            else:
                print(f"[invoke_sub_agent] 未知子 Agent: {agent_name}", flush=True)

        except Exception as e:
            print(f"[invoke_sub_agent] {agent_name} 执行失败: {e}", flush=True)
            results[f"{agent_name.lower()}_error"] = str(e)

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
    """评估子 Agent 输出质量（ReAct 的 Observe 步骤）。

    判断是否需要重试：
      - 采集结果为空或过少 → retry_collection
      - 排序质量差（top_score < 0.3）→ retry_ranking
      - 其他 → done

    Returns:
        observation_result: {quality_summary, needs_retry, suggested_action}
    """
    collected = state.get("collected_items", [])
    ranked = state.get("ranked_items", [])
    ranking_detail = state.get("ranking_detail", {})
    briefing = state.get("briefing", {})
    brief_quality = state.get("brief_quality", 1.0)

    obs = {}
    quality_summary = []
    needs_retry = False
    suggested_action = ""

    # 检查采集结果
    if not collected:
        quality_summary.append("采集结果为空")
        needs_retry = True
        suggested_action = "retry_collection"
    elif len(collected) < 3:
        quality_summary.append(f"采集结果过少: {len(collected)} 条 < 3")
        needs_retry = True
        suggested_action = "retry_collection"

    # 检查排序结果
    if ranked and len(ranked) > 0:
        top_score = ranking_detail.get("top_score", 0.0)
        if top_score < 0.3:
            quality_summary.append(f"排序质量差: top_score={top_score:.4f} < 0.3")
            needs_retry = True
            suggested_action = "retry_ranking"

    # 检查简报质量
    if brief_quality < 0.7:
        quality_summary.append(f"简报质量不达标: score={brief_quality:.2f} < 0.7")
        # 简报 Agent 自身有重试逻辑，这里不做干预

    if not quality_summary:
        quality_summary.append("各子 Agent 执行结果质量合格")

    observation = {
        "quality_summary": "; ".join(quality_summary),
        "needs_retry": needs_retry,
        "suggested_action": suggested_action,
        "collected_count": len(collected),
        "ranked_count": len(ranked),
        "brief_quality": brief_quality,
    }

    print(f"[observe] 观察结果: {observation['quality_summary']}", flush=True)
    return {
        "observation_result": observation,
        "react_cycle_count": state.get("react_cycle_count", 0) + 1,
    }


def coordinator_reflect_node(state: FeedLensState) -> dict:
    """综合质量审查：完整性 + 去重遗漏 + 可追溯性 + 矛盾检查。

    审查通过后将 briefing 提取到顶层字段。

    Returns:
        coordinator_observation: 综合审查结果
        briefing: 提取的简报内容
    """
    obs = state.get("observation_result", {})
    collection_result = state.get("collection_result", {})
    ranking_result = state.get("ranking_result", {})
    briefing_result = state.get("briefing_result", {})

    ranked_items = ranking_result.get("ranked_items", state.get("ranked_items", []))
    item_relations = ranking_result.get("item_relations", state.get("item_relations", []))

    # 提取简报内容（适配 briefing_agent 的 JSON 结构）
    briefing = briefing_result.get("briefing", {})
    if not briefing and "briefing_result" in state:
        briefing = state.get("briefing_result", {}).get("briefing", {})

    # 综合质量评估
    issues = []
    contradictions = []

    # 1. 完整性检查
    if len(ranked_items) == 0:
        issues.append("无排序条目")

    # 2. 简报质量检查
    brief_quality = obs.get("brief_quality", 0.0)
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

        # 两两检查矛盾
        for i in range(len(all_brief_items)):
            for j in range(i + 1, len(all_brief_items)):
                if _check_contradiction(all_brief_items[i], all_brief_items[j]):
                    contradictions.append({
                        "item_a": all_brief_items[i].get("id", ""),
                        "item_b": all_brief_items[j].get("id", ""),
                    })

    # 5. 来源追溯检查
    unreferenced = [item for item in ranked_items if not item.get("url")]
    if unreferenced:
        issues.append(f"{len(unreferenced)} 条条目缺少来源 URL")

    # 6. ReAct 循环次数检查
    react_cycles = state.get("react_cycle_count", 0)
    if react_cycles >= 3:
        issues.append("ReAct 循环次数过多，可能存在收敛问题")

    # 计算综合质量分数
    completeness = 1.0 if not issues else max(0.0, 1.0 - len(issues) * 0.15)
    dedup_coverage = len(ranked_items) / max(len(ranked_items) + len(item_relations), 1)

    # P1: 三维度审查评分（完整性 / 去重遗漏 / 可追溯性）
    traceability_score = 1.0 - len(unreferenced) * 0.2
    dedup_quality = 1.0 if not high_similar else max(0.3, 1.0 - len(high_similar) * 0.15)

    coordinator_obs = {
        "completeness": round(completeness, 2),
        "dedup_coverage": round(dedup_coverage, 2),
        "traceability": round(traceability_score, 2),
        "dedup_quality": round(dedup_quality, 2),
        "brief_quality": round(brief_quality, 2),
        "contradictions": contradictions,
        "issues": issues,
        "react_cycles": react_cycles,
        "dimensions": {
            "completeness": {"score": round(completeness, 2), "pass": completeness >= 0.7},
            "dedup": {"score": round(dedup_quality, 2), "pass": dedup_quality >= 0.7},
            "traceability": {"score": round(traceability_score, 2), "pass": traceability_score >= 0.7},
        },
        "overall_pass": len(issues) == 0 and len(contradictions) == 0 and completeness >= 0.7,
    }

    print(f"[coordinator_reflect] 综合审查: issues={len(issues)}, contradictions={len(contradictions)}, "
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
            vs = VectorStore(persist_dir="data/chroma")
            vs.init_collections()
            embedding_model = EmbeddingModel()

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

    当前设计：所有情况都走 push_notification 节点，
    push_immediate 标记仅影响推送 urgency（立即 vs 排队）。
    """
    if state.get("push_immediate", False):
        print(f"[should_push_now] 重大事件，立即推送", flush=True)
    else:
        print(f"[should_push_now] 日常简报，正常推送", flush=True)
    return "push_notification"


# ============================================================
# StateGraph 构建
# ============================================================


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



