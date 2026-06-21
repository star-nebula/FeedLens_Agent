"""
主 Agent 测试脚本 — 验证主 Agent planner 节点及全部 7 个节点功能。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import traceback
from datetime import datetime

# ── Mock LLM / Embedding，避免外部依赖 ────────────────────────
import unittest.mock

import agents.main_agent as ma


def _mock_state(overrides: dict = None):
    base = {
        "session_id": "test-session-001",
        "trigger_type": "daily_briefing",
        "user_id": 1,
        "goal_text": "我想了解 AI Agent 和大模型技术进展",
        "structured_goal": {"topics": ["AI Agent", "大模型"], "keywords": ["LLM", "多智能体"], "preferred_sources": []},
        "goal_embedding": [0.1] * 384,
        "react_cycle_count": 0,
        "collected_items": [],
        "ranked_items": [],
        "briefing": {},
        "brief_quality": 1.0,
        "observation_result": {},
        "coordinator_observation": {},
        "push_status": "pending",
        "sub_agent_plan": [],
        "planner_reason": "",
        "push_immediate": False,
    }
    if overrides:
        base.update(overrides)
    return base


def _assert_fields(result, required_keys):
    missing = [k for k in required_keys if k not in result]
    assert not missing, f"缺少字段: {missing}"
    print(f"  [PASS] 包含必需字段: {required_keys}")


# ═══════════════════════════════════════════════════════════════
# 测试 1: StateGraph 编译
# ═══════════════════════════════════════════════════════════════

def test_build_graph():
    print("\n[test] build_graph - StateGraph 编译")
    try:
        agent = ma.build_main_agent()
        assert agent is not None, "build_main_agent() 返回 None"
        print("  [PASS] StateGraph 编译成功")
    except Exception as e:
        print(f"  [FAIL] StateGraph 编译失败: {e}")
        traceback.print_exc()
        raise


# ═══════════════════════════════════════════════════════════════
# 测试 2: understand_intent_node
# ═══════════════════════════════════════════════════════════════

def test_understand_intent_basic():
    print("\n[test] understand_intent_node - 基础功能")
    state = _mock_state({"goal_text": "关注新能源车和自动驾驶技术"})
    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.return_value = {"content": '{"topics": ["新能源车"], "keywords": ["自动驾驶"], "preferred_sources": []}'}
    with unittest.mock.patch.object(ma, "_load_config", return_value={}):
        with unittest.mock.patch.object(ma, "_get_db_path", return_value="data/feedlens.db"):
            with unittest.mock.patch("agents.main_agent.db_read", return_value=[]):
                with unittest.mock.patch("agents.main_agent._get_llm_provider", return_value=mock_llm):
                    with unittest.mock.patch("utils.embedding.EmbeddingModel") as MockEmb:
                        mock_emb = unittest.mock.MagicMock()
                        mock_emb.encode.return_value = unittest.mock.MagicMock(tolist=lambda: [0.1] * 384)
                        MockEmb.return_value = mock_emb
                        result = ma.understand_intent_node(state)

    _assert_fields(result, ["trigger_type", "structured_goal", "goal_embedding", "react_cycle_count", "status"])
    assert result["trigger_type"] == "daily_briefing"
    assert result["react_cycle_count"] == 0
    assert result["status"] == "running"
    print(f"  [PASS] structured_goal: {result['structured_goal']['topics']}")


def test_understand_intent_with_user_prefs():
    print("\n[test] understand_intent_node - 用户已有偏好")
    state = _mock_state()
    prefs = {
        "topics": '["AI Agent", "LLM"]',
        "keywords": '["多智能体", "RAG"]',
        "preferred_sources": '[]',
    }
    with unittest.mock.patch.object(ma, "_load_config", return_value={}):
        with unittest.mock.patch.object(ma, "_get_db_path", return_value="data/feedlens.db"):
            with unittest.mock.patch("agents.main_agent.db_read", return_value=[prefs]):
                with unittest.mock.patch("utils.embedding.EmbeddingModel") as MockEmb:
                    mock_emb = unittest.mock.MagicMock()
                    mock_emb.encode.return_value = unittest.mock.MagicMock(tolist=lambda: [0.2] * 384)
                    MockEmb.return_value = mock_emb
                    result = ma.understand_intent_node(state)

    assert result["structured_goal"]["topics"] == ["AI Agent", "LLM"]
    assert result["structured_goal"]["keywords"] == ["多智能体", "RAG"]
    print(f"  [PASS] 从 SQLite 加载偏好成功: {result['structured_goal']['topics']}")


# ═══════════════════════════════════════════════════════════════
# 测试 3: planner_node
# ═══════════════════════════════════════════════════════════════

def test_planner_first_run():
    print("\n[test] planner_node - 首次编排")
    state = _mock_state({"react_cycle_count": 0, "observation_result": {}})
    result = ma.planner_node(state)

    _assert_fields(result, ["sub_agent_plan", "push_immediate", "planner_reason"])
    agents = [p["agent"] for p in result["sub_agent_plan"]]
    assert agents == ["Collection", "Ranking", "Briefing"], f"期望标准流程，实际: {agents}"
    assert result["push_immediate"] == False
    print(f"  [PASS] 编排计划: {agents}")


def test_planner_with_retry_suggestion():
    print("\n[test] planner_node - 观察建议重试采集")
    state = _mock_state({
        "observation_result": {"suggested_action": "retry_collection", "needs_retry": True},
        "react_cycle_count": 1,
    })
    result = ma.planner_node(state)
    agents = [p["agent"] for p in result["sub_agent_plan"]]
    assert agents == ["Collection"], f"期望重试采集，实际: {agents}"
    print(f"  [PASS] 接受建议重试: {agents}")


def test_planner_breaking_news():
    print("\n[test] planner_node - 重大事件检测")
    state = _mock_state({
        "ranked_items": [{"_score": 0.90, "importance": 0.95, "title": "重大突破"}],
    })
    result = ma.planner_node(state)
    assert result["push_immediate"] == True, f"未检测到重大事件"
    print(f"  [PASS] 重大事件触发立即推送: score=0.90, importance=0.95")


# ═══════════════════════════════════════════════════════════════
# 测试 4: invoke_sub_agent_node
# ═══════════════════════════════════════════════════════════════

def test_invoke_sub_agent_empty_plan():
    print("\n[test] invoke_sub_agent_node - 空计划跳过")
    state = _mock_state({"sub_agent_plan": []})
    result = ma.invoke_sub_agent_node(state)
    assert result == {}, "空计划应返回空字典"
    print("  [PASS] 空计划正确跳过")


def test_invoke_sub_agent_with_plan():
    print("\n[test] invoke_sub_agent_node - 顺序执行子 Agent（模拟）")

    # Mock 子 Agent
    mock_collection_agent = unittest.mock.MagicMock()
    mock_collection_agent.invoke.return_value = {
        "collected_items": [
            {"id": "c1", "title": "AI Agent 突破", "url": "http://x.com/1", "embedding": [0.1] * 384},
            {"id": "c2", "title": "LLM 新进展", "url": "http://x.com/2", "embedding": [0.2] * 384},
        ]
    }

    mock_ranking_agent = unittest.mock.MagicMock()
    mock_ranking_agent.invoke.return_value = {
        "ranked_items": [
            {"id": "c1", "title": "AI Agent 突破", "_score": 0.85},
            {"id": "c2", "title": "LLM 新进展", "_score": 0.70},
        ],
        "ranking_detail": {"top_score": 0.85},
    }

    mock_briefing_agent = unittest.mock.MagicMock()
    mock_briefing_agent.invoke.return_value = {
        "briefing_result": {"briefing": {"title": "AI 简报", "sections": []}},
    }

    state = _mock_state({
        "sub_agent_plan": [
            {"agent": "Collection", "params": {}},
            {"agent": "Ranking", "params": {}},
            {"agent": "Briefing", "params": {}},
        ],
    })

    with unittest.mock.patch("agents.main_agent.build_collection_agent", return_value=mock_collection_agent):
        with unittest.mock.patch("agents.main_agent.build_ranking_agent", return_value=mock_ranking_agent):
            with unittest.mock.patch("agents.main_agent.build_briefing_agent", return_value=mock_briefing_agent):
                result = ma.invoke_sub_agent_node(state)

    _assert_fields(result, ["current_sub_agent", "collection_result", "ranking_result", "briefing_result"])
    assert result["current_sub_agent"] == "Briefing"
    assert len(result["collection_result"].get("collected_items", [])) == 2
    assert len(result["ranking_result"].get("ranked_items", [])) == 2
    print(f"  [PASS] 子 Agent 顺序执行: Collection(2) → Ranking(2) → Briefing")


# ═══════════════════════════════════════════════════════════════
# 测试 5: observe_results_node
# ═══════════════════════════════════════════════════════════════

def test_observe_quality_pass():
    print("\n[test] observe_results_node - 质量合格")
    state = _mock_state({
        "collected_items": [{"id": 1}, {"id": 2}, {"id": 3}],
        "ranked_items": [{"id": 1}],
        "ranking_detail": {"top_score": 0.6},
        "brief_quality": 0.8,
    })
    result = ma.observe_results_node(state)
    _assert_fields(result, ["observation_result"])
    obs = result["observation_result"]
    assert obs["needs_retry"] == False, f"质量合格不应重试: {obs}"
    assert obs["collected_count"] == 3
    print(f"  [PASS] 质量合格: {obs['quality_summary']}")


def test_observe_insufficient_collection():
    print("\n[test] observe_results_node - 采集不足")
    state = _mock_state({
        "collected_items": [{"id": 1}],
        "ranked_items": [],
        "ranking_detail": {},
        "brief_quality": 1.0,
    })
    result = ma.observe_results_node(state)
    obs = result["observation_result"]
    assert obs["needs_retry"] == True
    assert "retry_collection" in obs["suggested_action"]
    print(f"  [PASS] 采集不足建议重试: {obs['quality_summary']}")


def test_observe_poor_ranking():
    print("\n[test] observe_results_node - 排序质量差")
    state = _mock_state({
        "collected_items": [{"id": 1}, {"id": 2}, {"id": 3}],
        "ranked_items": [{"id": 1}],
        "ranking_detail": {"top_score": 0.15},
        "brief_quality": 1.0,
    })
    result = ma.observe_results_node(state)
    obs = result["observation_result"]
    assert obs["needs_retry"] == True
    assert "retry_ranking" in obs["suggested_action"]
    print(f"  [PASS] 排序质量差建议重排: {obs['quality_summary']}")


# ═══════════════════════════════════════════════════════════════
# 测试 6: should_continue_react
# ═══════════════════════════════════════════════════════════════

def test_should_continue_react_retry():
    print("\n[test] should_continue_react - 需要重试")
    state = _mock_state({
        "observation_result": {"needs_retry": True, "suggested_action": "retry_collection"},
        "react_cycle_count": 1,
    })
    result = ma.should_continue_react(state)
    assert result == "planner", f"期望 planner，实际: {result}"
    print("  [PASS] needs_retry=True，循环继续 → planner")


def test_should_continue_react_stop():
    print("\n[test] should_continue_react - 停止循环")
    state = _mock_state({
        "observation_result": {"needs_retry": False},
        "react_cycle_count": 2,
    })
    result = ma.should_continue_react(state)
    assert result == "coordinator_reflect", f"期望 coordinator_reflect，实际: {result}"
    print("  [PASS] needs_retry=False，结束循环 → coordinator_reflect")


# ═══════════════════════════════════════════════════════════════
# 测试 7: coordinator_reflect_node
# ═══════════════════════════════════════════════════════════════

def test_coordinator_reflect_pass():
    print("\n[test] coordinator_reflect_node - 审查通过")
    state = _mock_state({
        "collection_result": {"collected_items": [{"id": "1", "title": "Test", "url": "http://x.com"}]},
        "ranking_result": {
            "ranked_items": [{"id": "1", "title": "Test", "url": "http://x.com"}],
            "item_relations": [],
        },
        "briefing_result": {"briefing": {"sections": []}},
        "observation_result": {"needs_retry": False},
    })
    result = ma.coordinator_reflect_node(state)
    _assert_fields(result, ["coordinator_observation", "briefing"])
    obs = result["coordinator_observation"]
    assert obs["overall_pass"] == True
    print(f"  [PASS] 综合审查通过: completeness={obs['completeness']}, issues={len(obs['issues'])}")


def test_coordinator_reflect_issues():
    print("\n[test] coordinator_reflect_node - 发现问题")
    state = _mock_state({
        "collection_result": {},
        "ranking_result": {"ranked_items": [], "item_relations": []},
        "briefing_result": {},
        "observation_result": {},
    })
    result = ma.coordinator_reflect_node(state)
    obs = result["coordinator_observation"]
    assert obs["overall_pass"] == False
    assert len(obs["issues"]) > 0
    print(f"  [PASS] 发现问题: {obs['issues']}")


# ═══════════════════════════════════════════════════════════════
# 测试 8: push_notification_node
# ═══════════════════════════════════════════════════════════════

def test_push_notification_success():
    print("\n[test] push_notification_node - 推送成功（模拟）")
    state = _mock_state({
        "briefing": {"title": "AI 每日简报", "sections": [], "summary": "摘要"},
        "user_id": 1,
        "push_immediate": False,
        "coordinator_observation": {"completeness": 1.0},
    })
    with unittest.mock.patch("agents.main_agent.PushMCPClient") as MockClient:
        mock_client = unittest.mock.MagicMock()
        mock_client.__enter__ = unittest.mock.MagicMock(return_value=mock_client)
        mock_client.__exit__ = unittest.mock.MagicMock(return_value=None)
        mock_client.push.return_value = True
        MockClient.return_value = mock_client

        result = ma.push_notification_node(state)

    _assert_fields(result, ["push_status", "push_message"])
    assert result["push_status"] == "sent"
    print(f"  [PASS] 推送成功: {result['push_message']}")


def test_push_notification_fallback():
    print("\n[test] push_notification_node - 降级推送（无简报）")
    state = _mock_state({
        "briefing": {},
        "ranked_items": [{"title": "Test", "url": "http://x.com", "importance": 0.8}],
        "user_id": 1,
        "push_immediate": False,
        "coordinator_observation": {},
    })
    with unittest.mock.patch("agents.main_agent.PushMCPClient") as MockClient:
        mock_client = unittest.mock.MagicMock()
        mock_client.__enter__ = unittest.mock.MagicMock(return_value=mock_client)
        mock_client.__exit__ = unittest.mock.MagicMock(return_value=None)
        mock_client.push.return_value = False
        MockClient.return_value = mock_client

        result = ma.push_notification_node(state)

    assert result["push_status"] == "failed"
    print(f"  [PASS] 推送失败降级: {result['push_message']}")


# ═══════════════════════════════════════════════════════════════
# 测试 9: update_memory_node
# ═══════════════════════════════════════════════════════════════

def test_update_memory_write_log():
    print("\n[test] update_memory_node - 写入执行日志")
    state = _mock_state({
        "collected_items": [{"id": "1"}, {"id": "2"}],
        "ranked_items": [{"id": "1", "title": "Test", "summary": "Summary", "url": "http://x.com"}],
        "briefing": {"title": "简报"},
        "coordinator_observation": {"completeness": 1.0, "issues": []},
        "planner_reason": "标准流程",
        "react_cycle_count": 0,
    })
    with unittest.mock.patch.object(ma, "_get_db_path", return_value="data/feedlens.db"):
        with unittest.mock.patch("agents.main_agent.db_write", return_value=True) as mock_db_write:
            with unittest.mock.patch("agents.main_agent.VectorStore") as MockVS:
                result = ma.update_memory_node(state)

    _assert_fields(result, ["execution_log", "status"])
    assert result["status"] == "completed"
    assert "execution_log" in result
    mock_db_write.assert_called()
    print(f"  [PASS] 执行日志写入成功: session={result['execution_log']['session_id']}")


# ═══════════════════════════════════════════════════════════════
# 测试 10: ReAct 循环（端到端模拟）
# ═══════════════════════════════════════════════════════════════

def test_react_cycle():
    print("\n[test] ReAct 循环 - 三轮迭代模拟")

    # 第 1 轮：采集不足
    print("  [Round 1] 采集不足...")
    state = _mock_state({"react_cycle_count": 0, "observation_result": {}, "collected_items": [{"id": 1}]})
    planner_out = ma.planner_node(state)
    assert planner_out["sub_agent_plan"][0]["agent"] == "Collection"
    print("    [PASS] 第1轮: Collection → Ranking → Briefing")

    # 模拟 observe_results 判定采集不足
    obs_state = dict(state)
    obs_state["collected_items"] = [{"id": 1}]
    obs_state["ranked_items"] = []
    obs_state["ranking_detail"] = {}
    obs_out = ma.observe_results_node(obs_state)
    assert obs_out["observation_result"]["needs_retry"] == True
    # 在 LangGraph 中 observe_results 节点会更新 react_cycle_count，
    # 这里模拟该更新（因为 observe_results_node 不返回该字段）
    obs_out["react_cycle_count"] = 1
    obs_state.update(obs_out)
    should_continue = ma.should_continue_react(obs_state)
    assert should_continue == "planner", f"期望继续，实际: {should_continue}"
    print("    [PASS] 第1轮观察: 采集不足 → 继续 ReAct")

    # 第 2 轮：重试采集
    print("  [Round 2] 重试采集...")
    state["react_cycle_count"] = 1
    state["observation_result"] = obs_out["observation_result"]
    planner_out2 = ma.planner_node(state)
    assert planner_out2["sub_agent_plan"][0]["agent"] == "Collection"
    print("    [PASS] 第2轮: 接受建议重试采集")

    # 第 3 轮：质量合格，结束
    print("  [Round 3] 质量合格，结束...")
    state["collected_items"] = [{"id": 1}, {"id": 2}, {"id": 3}]
    state["ranked_items"] = [{"id": 1, "_score": 0.65}]
    state["ranking_detail"] = {"top_score": 0.65}
    state["brief_quality"] = 0.85
    state["observation_result"] = {}
    obs_out3 = ma.observe_results_node(state)
    assert obs_out3["observation_result"]["needs_retry"] == False, f"Round3 needs_retry should be False: {obs_out3['observation_result']}"
    assert obs_out3["react_cycle_count"] == 1
    state.update(obs_out3)
    should_continue3 = ma.should_continue_react(state)
    assert should_continue3 == "coordinator_reflect", f"期望结束，实际: {should_continue3}"
    print("    [PASS] 第3轮观察: 质量合格 → 结束 ReAct")

    print("  [PASS] ReAct 循环逻辑正确")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("FeedLens 主 Agent 测试脚本（planner 节点）")
    print("=" * 60)

    tests = [
        test_build_graph,
        test_understand_intent_basic,
        test_understand_intent_with_user_prefs,
        test_planner_first_run,
        test_planner_with_retry_suggestion,
        test_planner_breaking_news,
        test_invoke_sub_agent_empty_plan,
        test_invoke_sub_agent_with_plan,
        test_observe_quality_pass,
        test_observe_insufficient_collection,
        test_observe_poor_ranking,
        test_should_continue_react_retry,
        test_should_continue_react_stop,
        test_coordinator_reflect_pass,
        test_coordinator_reflect_issues,
        test_push_notification_success,
        test_push_notification_fallback,
        test_update_memory_write_log,
        test_react_cycle,
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
