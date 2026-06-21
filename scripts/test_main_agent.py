"""主 Agent 测试脚本 — 对齐 v0.3 + P0 记忆接入实现。

所有外部依赖（LLM/Embedding/MCP/Database/ChromaDB）均被 mock，测试只验证节点逻辑契约。
设计原则：
  - planner 测试 mock _get_llm_provider 返回确定 plan，验证解析/fallback（不验证 LLM 智能）
  - observe 测试用真实实现，断言对齐当前契约字段（needs_retry/suggested_action/issues/briefing_count_ok）
  - push 测试 mock tools.mcp_client.PushMCPClient（真实调用路径）
  - update_memory 测试 mock Database + 验证 P0 add_memory 调用
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import traceback
import unittest.mock

import agents.main_agent as ma


def _mock_state(overrides: dict = None):
    base = {
        "session_id": "test-session-001", "trigger_type": "daily_briefing", "user_id": 1,
        "goal_text": "我想了解 AI Agent 和大模型技术进展",
        "structured_goal": {"topics": ["AI Agent", "大模型"], "keywords": ["LLM", "多智能体"], "preferred_sources": []},
        "goal_embedding": [0.1] * 384, "react_cycle_count": 0,
        "collected_items": [], "ranked_items": [], "briefing": {}, "brief_quality": 1.0,
        "observation_result": {}, "coordinator_observation": {}, "push_status": "pending",
        "sub_agent_plan": [], "planner_reason": "", "push_immediate": False,
    }
    if overrides:
        base.update(overrides)
    return base


def _assert_fields(result, required_keys):
    missing = [k for k in required_keys if k not in result]
    assert not missing, f"缺少字段: {missing}"
    print(f"  [PASS] 包含必需字段: {required_keys}")


def _mock_llm_with_plan(plan_dict):
    llm = unittest.mock.MagicMock()
    llm.chat.return_value = json.dumps(plan_dict, ensure_ascii=False)
    return llm


def test_build_graph():
    print("\n[test] build_graph - StateGraph 编译")
    agent = ma.build_main_agent()
    assert agent is not None, "build_main_agent() 返回 None"
    print("  [PASS] StateGraph 编译成功")


def test_understand_intent_basic():
    """基础功能：goal_text 非空且 DB 无偏好时，LLM 提取结构化 goal。"""
    print("\n[test] understand_intent_node - 基础功能（LLM 提取）")
    state = _mock_state({"goal_text": "关注新能源车和自动驾驶技术"})
    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.return_value = '{"topics": ["新能源车"], "keywords": ["自动驾驶"], "preferred_sources": []}'
    mock_emb = unittest.mock.MagicMock()
    mock_emb.encode.return_value = unittest.mock.MagicMock(tolist=lambda: [[0.1] * 384])
    with unittest.mock.patch.object(ma, "_get_db_path", return_value="data/feedlens.db"):
        with unittest.mock.patch("agents.main_agent.db_read", return_value=[]):
            with unittest.mock.patch("agents.main_agent._get_llm_provider", return_value=mock_llm):
                with unittest.mock.patch("models.database.Database") as MockDB:
                    MockDB.return_value.init_schema.return_value = None
                    with unittest.mock.patch("agents.main_agent.EmbeddingModel", return_value=mock_emb):
                        result = ma.understand_intent_node(state)
    _assert_fields(result, ["trigger_type", "structured_goal", "goal_embedding", "react_cycle_count", "status"])
    assert result["trigger_type"] == "daily_briefing"
    assert result["status"] == "running"
    assert result["structured_goal"]["topics"] == ["新能源车"], f"LLM 提取 topics 错误: {result['structured_goal']}"
    print(f"  [PASS] structured_goal: {result['structured_goal']['topics']}")


def test_understand_intent_with_user_prefs():
    """用户已有偏好：DB 返回偏好时直接加载。"""
    print("\n[test] understand_intent_node - 用户已有偏好（DB 加载）")
    state = _mock_state()
    prefs = {"topics": '["AI Agent", "LLM"]', "keywords": '["多智能体", "RAG"]', "preferred_sources": '[]'}
    mock_emb = unittest.mock.MagicMock()
    mock_emb.encode.return_value = unittest.mock.MagicMock(tolist=lambda: [[0.2] * 384])
    with unittest.mock.patch.object(ma, "_get_db_path", return_value="data/feedlens.db"):
        with unittest.mock.patch("agents.main_agent.db_read", return_value=[prefs]):
            with unittest.mock.patch("models.database.Database") as MockDB:
                MockDB.return_value.init_schema.return_value = None
                with unittest.mock.patch("agents.main_agent.EmbeddingModel", return_value=mock_emb):
                    result = ma.understand_intent_node(state)
    assert result["structured_goal"]["topics"] == ["AI Agent", "LLM"], f"DB 偏好加载错误: {result['structured_goal']}"
    assert result["structured_goal"]["keywords"] == ["多智能体", "RAG"]
    print(f"  [PASS] 从 SQLite 加载偏好成功: {result['structured_goal']['topics']}")


def test_planner_first_run():
    """首次编排：mock LLM 返回标准三板斧，验证 planner 正确解析。"""
    print("\n[test] planner_node - 首次编排（mock LLM）")
    state = _mock_state({"react_cycle_count": 0, "observation_result": {}})
    plan = {"sub_agent_plan": [{"agent": "Collection", "params": {}}, {"agent": "Ranking", "params": {}}, {"agent": "Briefing", "params": {}}], "reason": "标准流程", "push_immediate": False}
    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=_mock_llm_with_plan(plan)):
        result = ma.planner_node(state)
    _assert_fields(result, ["sub_agent_plan", "push_immediate", "planner_reason"])
    agents = [p["agent"] for p in result["sub_agent_plan"]]
    assert agents == ["Collection", "Ranking", "Briefing"], f"期望标准流程，实际: {agents}"
    assert result["push_immediate"] == False
    print(f"  [PASS] 编排计划: {agents}")


def test_planner_with_retry_suggestion():
    """观察建议重试：mock LLM 返回仅 Collection，验证 planner 透传。"""
    print("\n[test] planner_node - 观察建议重试采集（mock LLM）")
    state = _mock_state({"observation_result": {"suggested_action": "search_expand", "needs_retry": True}, "react_cycle_count": 1})
    plan = {"sub_agent_plan": [{"agent": "Collection", "params": {"search_expand": True}}], "reason": "采集不足重试", "push_immediate": False}
    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=_mock_llm_with_plan(plan)):
        result = ma.planner_node(state)
    agents = [p["agent"] for p in result["sub_agent_plan"]]
    assert agents == ["Collection"], f"期望重试采集，实际: {agents}"
    print(f"  [PASS] 接受建议重试: {agents}")


def test_planner_breaking_news():
    """重大事件：mock LLM 返回 push_immediate=True，验证 planner 透传。"""
    print("\n[test] planner_node - 重大事件检测（mock LLM）")
    state = _mock_state({"ranked_items": [{"_score": 0.90, "importance": 0.95, "title": "重大突破"}]})
    plan = {"sub_agent_plan": [{"agent": "Briefing", "params": {}}], "reason": "重大事件立即推送", "push_immediate": True}
    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=_mock_llm_with_plan(plan)):
        result = ma.planner_node(state)
    assert result["push_immediate"] == True, f"未检测到重大事件"
    print(f"  [PASS] 重大事件触发立即推送: push_immediate=True")


def test_planner_fallback_on_llm_failure():
    """LLM 失败时回退默认编排：验证 _fallback_plan 逻辑。"""
    print("\n[test] planner_node - LLM 失败回退")
    state = _mock_state({"react_cycle_count": 0, "observation_result": {}})
    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.side_effect = Exception("LLM 不可用")
    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=mock_llm):
        result = ma.planner_node(state)
    agents = [p["agent"] for p in result["sub_agent_plan"]]
    assert agents == ["Collection", "Ranking", "Briefing"], f"回退编排错误: {agents}"
    assert result["push_immediate"] == False
    print(f"  [PASS] LLM 失败回退标准流程: {agents}")


def test_planner_context_contains_memory():
    """P0 验收：_build_planner_context 返回的上下文含 memory 字段。"""
    print("\n[test] _build_planner_context - P0 记忆字段注入")
    state = _mock_state({"collected_items": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "ranking_detail": {"top_score": 0.6}, "brief_quality": 0.8})
    with unittest.mock.patch("agents.main_agent.get_context", return_value={"short_term": [{"turn": 1}], "long_term": [{"document": "历史经验A"}], "short_term_size": 1}):
        ctx = ma._build_planner_context(state)
    assert "memory" in ctx, "memory 字段缺失"
    assert ctx["memory"]["recent_turns"] == [{"turn": 1}], f"recent_turns 错误: {ctx['memory']}"
    assert ctx["memory"]["relevant_history"] == ["历史经验A"], f"relevant_history 错误: {ctx['memory']}"
    print(f"  [PASS] memory 字段含 recent_turns(1) + relevant_history(1)")


def test_planner_context_memory_degradation():
    """P0 验收：记忆检索失败时降级为空 memory，不抛异常。"""
    print("\n[test] _build_planner_context - 记忆检索失败降级")
    state = _mock_state({"collected_items": [], "ranking_detail": {}, "brief_quality": 0})
    with unittest.mock.patch("agents.main_agent.get_context", side_effect=Exception("ChromaDB 不可用")):
        ctx = ma._build_planner_context(state)
    assert "memory" in ctx, "降级后仍应有 memory 字段"
    assert ctx["memory"]["recent_turns"] == [], f"降级应为空: {ctx['memory']}"
    assert ctx["memory"]["relevant_history"] == [], f"降级应为空: {ctx['memory']}"
    print(f"  [PASS] 记忆检索失败降级为空 memory，无异常")


def test_invoke_sub_agent_empty_plan():
    print("\n[test] invoke_sub_agent_node - 空计划跳过")
    state = _mock_state({"sub_agent_plan": []})
    result = ma.invoke_sub_agent_node(state)
    assert result == {}, "空计划应返回空字典"
    print("  [PASS] 空计划正确跳过")


def test_invoke_sub_agent_with_plan():
    print("\n[test] invoke_sub_agent_node - 顺序执行子 Agent（模拟）")
    mock_collection_agent = unittest.mock.MagicMock()
    mock_collection_agent.invoke.return_value = {"collected_items": [{"id": "c1", "title": "AI Agent 突破", "url": "http://x.com/1", "embedding": [0.1] * 384}, {"id": "c2", "title": "LLM 新进展", "url": "http://x.com/2", "embedding": [0.2] * 384}]}
    mock_ranking_agent = unittest.mock.MagicMock()
    mock_ranking_agent.invoke.return_value = {"ranked_items": [{"id": "c1", "title": "AI Agent 突破", "_score": 0.85}, {"id": "c2", "title": "LLM 新进展", "_score": 0.70}], "ranking_detail": {"top_score": 0.85}}
    mock_briefing_agent = unittest.mock.MagicMock()
    mock_briefing_agent.invoke.return_value = {"briefing_result": {"briefing": {"title": "AI 简报", "sections": []}}}
    state = _mock_state({"sub_agent_plan": [{"agent": "Collection", "params": {}}, {"agent": "Ranking", "params": {}}, {"agent": "Briefing", "params": {}}]})
    with unittest.mock.patch("agents.main_agent.build_collection_agent", return_value=mock_collection_agent):
        with unittest.mock.patch("agents.main_agent.build_ranking_agent", return_value=mock_ranking_agent):
            with unittest.mock.patch("agents.main_agent.build_briefing_agent", return_value=mock_briefing_agent):
                result = ma.invoke_sub_agent_node(state)
    _assert_fields(result, ["current_sub_agent", "collection_result", "ranking_result", "briefing_result"])
    assert result["current_sub_agent"] == "Briefing"
    assert len(result["collection_result"].get("collected_items", [])) == 2
    assert len(result["ranking_result"].get("ranked_items", [])) == 2
    print(f"  [PASS] 子 Agent 顺序执行: Collection(2) → Ranking(2) → Briefing")


def test_observe_quality_pass():
    """质量合格：采集>=3、排序top>=0.3、简报质量>=0.7、简报条目>=10 → needs_retry=False。"""
    print("\n[test] observe_results_node - 质量合格")
    ranked = [{"id": i, "_score": 0.6} for i in range(10)]
    state = _mock_state({"collected_items": [{"id": 1}, {"id": 2}, {"id": 3}], "ranked_items": ranked, "ranking_detail": {"top_score": 0.6}, "brief_quality": 0.8})
    result = ma.observe_results_node(state)
    _assert_fields(result, ["observation_result"])
    obs = result["observation_result"]
    assert obs["needs_retry"] == False, f"质量合格不应重试: {obs}"
    assert obs["collection_ok"] == True
    assert obs["ranking_ok"] == True
    assert obs["briefing_ok"] == True
    assert obs["briefing_count_ok"] == True, f"10 条应 briefing_count_ok: {obs}"
    print(f"  [PASS] 质量合格: needs_retry=False, briefing_count={obs['briefing_count']}")


def test_observe_insufficient_collection():
    """采集不足：collected<3 → needs_retry=True, suggested_action=search_expand。"""
    print("\n[test] observe_results_node - 采集不足")
    state = _mock_state({"collected_items": [{"id": 1}], "ranked_items": [], "ranking_detail": {}, "brief_quality": 1.0})
    result = ma.observe_results_node(state)
    obs = result["observation_result"]
    assert obs["needs_retry"] == True, f"采集不足应重试: {obs}"
    assert obs["collection_ok"] == False
    assert obs["suggested_action"] == "search_expand", f"当前契约 suggested_action 应为 search_expand: {obs}"
    assert any("采集不足" in i for i in obs["issues"]), f"issues 应含采集不足: {obs['issues']}"
    print(f"  [PASS] 采集不足建议 search_expand: issues={obs['issues']}")


def test_observe_poor_ranking():
    """排序质量差：top_score<0.3 → needs_retry=True, ranking_ok=False。"""
    print("\n[test] observe_results_node - 排序质量差")
    state = _mock_state({"collected_items": [{"id": 1}, {"id": 2}, {"id": 3}], "ranked_items": [{"id": 1}], "ranking_detail": {"top_score": 0.15}, "brief_quality": 1.0})
    result = ma.observe_results_node(state)
    obs = result["observation_result"]
    assert obs["needs_retry"] == True, f"排序差应重试: {obs}"
    assert obs["ranking_ok"] == False, f"top_score=0.15 应 ranking_ok=False: {obs}"
    assert obs["ranking_top_score"] == 0.15
    assert any("排序不佳" in i for i in obs["issues"]), f"issues 应含排序不佳: {obs['issues']}"
    print(f"  [PASS] 排序质量差: ranking_ok=False, issues={obs['issues']}")


def test_observe_briefing_count_insufficient():
    """简报条目不足：采集足够(>=10)但排序后<10 → suggested_action=expand_threshold。"""
    print("\n[test] observe_results_node - 简报条目不足（采集足够）")
    collected = [{"id": i} for i in range(12)]
    ranked = [{"id": i, "_score": 0.6} for i in range(5)]
    state = _mock_state({"collected_items": collected, "ranked_items": ranked, "ranking_detail": {"top_score": 0.6}, "brief_quality": 0.8})
    result = ma.observe_results_node(state)
    obs = result["observation_result"]
    assert obs["needs_retry"] == True, f"简报不足应重试: {obs}"
    assert obs["briefing_count_ok"] == False
    assert obs["suggested_action"] == "expand_threshold", f"采集足够应建议 expand_threshold: {obs}"
    print(f"  [PASS] 采集足够排序不足 → expand_threshold: {obs['suggested_action']}")


def test_should_continue_react_retry():
    print("\n[test] should_continue_react - 需要重试")
    state = _mock_state({"observation_result": {"needs_retry": True, "suggested_action": "search_expand"}, "react_cycle_count": 1})
    result = ma.should_continue_react(state)
    assert result == "planner", f"期望 planner，实际: {result}"
    print("  [PASS] needs_retry=True，循环继续 → planner")


def test_should_continue_react_stop():
    print("\n[test] should_continue_react - 停止循环")
    state = _mock_state({"observation_result": {"needs_retry": False}, "react_cycle_count": 2})
    result = ma.should_continue_react(state)
    assert result == "coordinator_reflect", f"期望 coordinator_reflect，实际: {result}"
    print("  [PASS] needs_retry=False，结束循环 → coordinator_reflect")


def test_should_continue_react_max_cycle():
    """达到最大循环次数(>=3)时即使 needs_retry=True 也停止。"""
    print("\n[test] should_continue_react - 达上限强制停止")
    state = _mock_state({"observation_result": {"needs_retry": True}, "react_cycle_count": 3})
    result = ma.should_continue_react(state)
    assert result == "coordinator_reflect", f"达上限应停止: {result}"
    print("  [PASS] react_cycle>=3 强制结束 → coordinator_reflect")


def test_coordinator_reflect_pass():
    print("\n[test] coordinator_reflect_node - 审查通过")
    state = _mock_state({"collection_result": {"collected_items": [{"id": "1", "title": "Test", "url": "http://x.com"}]}, "ranking_result": {"ranked_items": [{"id": "1", "title": "Test", "url": "http://x.com"}], "item_relations": []}, "briefing_result": {"briefing": {"sections": []}}, "observation_result": {"needs_retry": False, "briefing_quality": 0.9}})
    result = ma.coordinator_reflect_node(state)
    _assert_fields(result, ["coordinator_observation", "briefing"])
    obs = result["coordinator_observation"]
    assert obs["overall_pass"] == True, f"应审查通过: {obs}"
    assert obs["completeness"] >= 0.7
    print(f"  [PASS] 综合审查通过: completeness={obs['completeness']}, issues={len(obs['issues'])}")


def test_coordinator_reflect_issues():
    print("\n[test] coordinator_reflect_node - 发现问题")
    state = _mock_state({"collection_result": {}, "ranking_result": {"ranked_items": [], "item_relations": []}, "briefing_result": {}, "observation_result": {}})
    result = ma.coordinator_reflect_node(state)
    obs = result["coordinator_observation"]
    assert obs["overall_pass"] == False, f"应审查不通过: {obs}"
    assert len(obs["issues"]) > 0
    print(f"  [PASS] 发现问题: {obs['issues']}")


def test_push_notification_success():
    print("\n[test] push_notification_node - 推送成功（mock MCP）")
    state = _mock_state({"briefing": {"title": "AI 每日简报", "sections": [], "summary": "摘要", "categories": []}, "user_id": 1, "push_immediate": False, "coordinator_observation": {"completeness": 1.0}})
    mock_client = unittest.mock.MagicMock()
    mock_client.push_sync.return_value = True
    with unittest.mock.patch("tools.mcp_client.PushMCPClient", return_value=mock_client):
        result = ma.push_notification_node(state)
    _assert_fields(result, ["push_status", "push_message"])
    assert result["push_status"] == "sent", f"推送应成功: {result}"
    print(f"  [PASS] 推送成功: {result['push_message']}")


def test_push_notification_fallback():
    print("\n[test] push_notification_node - 推送失败降级")
    state = _mock_state({"briefing": {}, "ranked_items": [{"title": "Test", "url": "http://x.com", "importance": 0.8}], "user_id": 1, "push_immediate": False, "coordinator_observation": {}})
    mock_client = unittest.mock.MagicMock()
    mock_client.push_sync.return_value = False
    with unittest.mock.patch("tools.mcp_client.PushMCPClient", return_value=mock_client):
        result = ma.push_notification_node(state)
    assert result["push_status"] == "failed", f"推送失败应 failed: {result}"
    print(f"  [PASS] 推送失败降级: {result['push_message']}")


def test_update_memory_write_log():
    """写入执行日志 + P0 决策经验（mock Database + add_memory）。"""
    print("\n[test] update_memory_node - 写入执行日志 + P0 决策经验")
    state = _mock_state({"collected_items": [{"id": "1"}, {"id": "2"}], "ranked_items": [{"id": "1", "title": "Test", "summary": "Summary", "url": "http://x.com"}], "briefing": {"title": "简报"}, "coordinator_observation": {"completeness": 1.0, "issues": []}, "planner_reason": "标准流程", "react_cycle_count": 0, "sub_agent_plan": [{"agent": "Collection", "params": {}}]})
    mock_db = unittest.mock.MagicMock()
    mock_db.insert_run_log.return_value = None
    with unittest.mock.patch.object(ma, "_get_db_path", return_value="data/feedlens.db"):
        with unittest.mock.patch("models.database.Database", return_value=mock_db):
            with unittest.mock.patch("agents.main_agent.VectorStore"):
                with unittest.mock.patch("agents.main_agent.add_memory") as mock_add_memory:
                    with unittest.mock.patch("agents.main_agent.EmbeddingModel"):
                        result = ma.update_memory_node(state)
    _assert_fields(result, ["execution_log", "status"])
    assert result["status"] == "completed"
    assert mock_db.insert_run_log.called, "insert_run_log 应被调用"
    assert mock_add_memory.called, "P0: add_memory 应被调用记录决策经验"
    call_kwargs = mock_add_memory.call_args
    assert call_kwargs.kwargs.get("event") == "planner_decision", f"event 应为 planner_decision: {call_kwargs}"
    print(f"  [PASS] 执行日志写入 + P0 决策经验写入: session={result['execution_log']['session_id']}")


def test_react_cycle():
    """ReAct 三轮迭代（mock planner LLM，第3轮给足10条让合格）。"""
    print("\n[test] ReAct 循环 - 三轮迭代模拟（mock LLM）")
    print("  [Round 1] 采集不足...")
    state = _mock_state({"react_cycle_count": 0, "observation_result": {}, "collected_items": [{"id": 1}]})
    plan1 = {"sub_agent_plan": [{"agent": "Collection", "params": {}}], "reason": "采集不足", "push_immediate": False}
    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=_mock_llm_with_plan(plan1)):
        planner_out = ma.planner_node(state)
    assert planner_out["sub_agent_plan"][0]["agent"] == "Collection"
    print("    [PASS] 第1轮: planner 决策 Collection")
    obs_state = dict(state)
    obs_out = ma.observe_results_node(obs_state)
    assert obs_out["observation_result"]["needs_retry"] == True, f"采集不足应重试: {obs_out}"
    obs_out["react_cycle_count"] = 1
    obs_state.update(obs_out)
    should_continue = ma.should_continue_react(obs_state)
    assert should_continue == "planner", f"期望继续，实际: {should_continue}"
    print("    [PASS] 第1轮观察: 采集不足 → 继续 ReAct")
    print("  [Round 2] 重试采集...")
    state["react_cycle_count"] = 1
    state["observation_result"] = obs_out["observation_result"]
    plan2 = {"sub_agent_plan": [{"agent": "Collection", "params": {"search_expand": True}}], "reason": "补充采集", "push_immediate": False}
    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=_mock_llm_with_plan(plan2)):
        planner_out2 = ma.planner_node(state)
    assert planner_out2["sub_agent_plan"][0]["agent"] == "Collection"
    print("    [PASS] 第2轮: 接受建议重试采集")
    print("  [Round 3] 质量合格，结束...")
    state["collected_items"] = [{"id": i} for i in range(12)]
    state["ranked_items"] = [{"id": i, "_score": 0.65} for i in range(10)]
    state["ranking_detail"] = {"top_score": 0.65}
    state["brief_quality"] = 0.85
    state["observation_result"] = {}
    obs_out3 = ma.observe_results_node(state)
    assert obs_out3["observation_result"]["needs_retry"] == False, f"Round3 质量合格不应重试: {obs_out3['observation_result']}"
    assert obs_out3["observation_result"]["briefing_count_ok"] == True, f"10 条应 briefing_count_ok: {obs_out3}"
    state.update(obs_out3)
    should_continue3 = ma.should_continue_react(state)
    assert should_continue3 == "coordinator_reflect", f"期望结束，实际: {should_continue3}"
    print("    [PASS] 第3轮观察: 质量合格 → 结束 ReAct")
    print("  [PASS] ReAct 循环逻辑正确")


def main():
    print("=" * 60)
    print("FeedLens 主 Agent 测试脚本（对齐 v0.3 + P0 实现）")
    print("=" * 60)
    tests = [
        test_build_graph, test_understand_intent_basic, test_understand_intent_with_user_prefs,
        test_planner_first_run, test_planner_with_retry_suggestion, test_planner_breaking_news,
        test_planner_fallback_on_llm_failure, test_planner_context_contains_memory, test_planner_context_memory_degradation,
        test_invoke_sub_agent_empty_plan, test_invoke_sub_agent_with_plan,
        test_observe_quality_pass, test_observe_insufficient_collection, test_observe_poor_ranking, test_observe_briefing_count_insufficient,
        test_should_continue_react_retry, test_should_continue_react_stop, test_should_continue_react_max_cycle,
        test_coordinator_reflect_pass, test_coordinator_reflect_issues,
        test_push_notification_success, test_push_notification_fallback,
        test_update_memory_write_log, test_react_cycle,
    ]
    passed = 0
    failed = 0
    for test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] 失败: {e}")
            traceback.print_exc()
    print("\n" + "=" * 60)
    print(f"测试结果汇总: {passed}/{len(tests)} 通过")
    if failed:
        print(f"  失败: {failed} 项")
        sys.exit(1)
    else:
        print("  全部通过!")
        sys.exit(0)


if __name__ == "__main__":
    main()
