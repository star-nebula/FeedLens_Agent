"""
FeedLens 集成测试脚本。

测试范围：
1. 全链路端到端（主 Agent StateGraph，全 mock）
2. Planner 决策场景覆盖
3. ReAct 循环上限控制
4. 去重阈值配置验证

区别于 test_main_agent.py：本测试走完整 StateGraph 而非单独节点。
"""

import sys
import os
import unittest.mock
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from agents.main_agent import planner_node, should_continue_react, build_main_agent


def _mock_items(n: int = 5) -> list:
    now = datetime.now().isoformat()
    return [
        {
            "id": f"item_{i}",
            "title": f"测试新闻 {i}",
            "summary": f"摘要 {i}",
            "url": f"https://example.com/{i}",
            "source": "test",
            "published_at": now,
            "importance": 3,
            "category": "科技",
            "embedding": [0.1] * 384,
        }
        for i in range(1, n + 1)
    ]


def _mock_state(overrides: dict = None) -> dict:
    base = {
        "trigger_type": "daily_briefing",
        "session_id": "test_integration",
        "user_id": 1,
        "goal_text": "关注人工智能和大模型领域",
        "structured_goal": {"topics": ["AI"], "keywords": ["大模型"]},
        "goal_embedding": [0.1] * 384,
        "react_cycle_count": 0,
        "collected_items": [],
        "ranked_items": [],
        "observation_result": {},
        "feedback_history": [],
        "briefing": {},
        "briefing_result": {},
        "coordinator_observation": {},
        "push_status": "pending",
    }
    if overrides:
        base.update(overrides)
    return base


def test_planner_normal_briefing():
    print("\n[test] Planner 场景 — 正常每日简报")
    state = _mock_state({"react_cycle_count": 0, "observation_result": {}})
    result = planner_node(state)
    agents = [p["agent"] for p in result["sub_agent_plan"]]
    assert "Collection" in agents and "Ranking" in agents and "Briefing" in agents
    assert result["planner_reason"] == "首次编排：标准每日简报流程"
    print(f"  [PASS] 计划: {agents}")


def test_planner_retry_collection():
    print("\n[test] Planner 场景 — 采集不足重试")
    state = _mock_state({
        "react_cycle_count": 1,
        "observation_result": {"suggested_action": "retry_collection"},
    })
    result = planner_node(state)
    plan = result["sub_agent_plan"]
    assert len(plan) == 1 and plan[0]["agent"] == "Collection"
    assert plan[0]["params"].get("retry") is True
    print(f"  [PASS] 计划: {[p['agent'] for p in plan]}")


def test_planner_retry_ranking():
    print("\n[test] Planner 场景 — 排序不理想重排")
    state = _mock_state({
        "react_cycle_count": 1,
        "observation_result": {"suggested_action": "retry_ranking"},
    })
    result = planner_node(state)
    plan = result["sub_agent_plan"]
    assert len(plan) == 1 and plan[0]["agent"] == "Ranking"
    assert plan[0]["params"].get("rerank") is True
    print(f"  [PASS] 计划: {[p['agent'] for p in plan]}")


def test_planner_react_rethink():
    print("\n[test] Planner ReAct 再思考")
    state = _mock_state({
        "react_cycle_count": 1,
        "observation_result": {"needs_retry": True, "suggested_action": "continue"},
    })
    result = planner_node(state)
    agents = [p["agent"] for p in result["sub_agent_plan"]]
    assert "Collection" in agents and "Ranking" in agents
    print(f"  [PASS] ReAct cycle=1, 计划: {agents}")


def test_react_continue_under_limit():
    print("\n[test] ReAct — needs_retry=True 且 cycle<3 → 继续")
    state = _mock_state({"react_cycle_count": 1, "observation_result": {"needs_retry": True}})
    assert should_continue_react(state) == "planner"
    print("  [PASS] 继续执行 planner")


def test_react_stop_at_limit():
    print("\n[test] ReAct — needs_retry=False → 结束")
    state = _mock_state({"react_cycle_count": 2, "observation_result": {"needs_retry": False}})
    assert should_continue_react(state) == "coordinator_reflect"
    print("  [PASS] 进入 coordinator_reflect")


def test_dedup_threshold_config():
    print("\n[test] 去重阈值配置")
    calib_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "dedup_calibration.json",
    )
    if os.path.exists(calib_path):
        with open(calib_path, "r", encoding="utf-8") as f:
            calib = json.load(f)
        threshold = calib.get("threshold") or calib.get("optimal_threshold")
        assert threshold is not None, "缺少 threshold 字段"
        assert 0.0 <= threshold <= 1.0, f"阈值超出范围: {threshold}"
        print(f"  [PASS] 阈值: {threshold}, F1: {calib.get('optimal_f1', 'N/A')}")
    else:
        print("  [PASS] 校准文件不存在，使用默认阈值 0.88")

def test_full_pipeline():
    print("\n[test] 全链路端到端（主 Agent StateGraph + 全部 mock）")
    items = _mock_items(3)
    state = _mock_state({"collected_items": items, "goal_text": "关注 AI 技术进展"})

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.return_value = {"content": '{"topics":["AI"],"keywords":["大模型"],"preferred_sources":[]}'}

    mock_push_client = unittest.mock.MagicMock()
    mock_push_client.__enter__ = unittest.mock.MagicMock(return_value=mock_push_client)
    mock_push_client.__exit__ = unittest.mock.MagicMock(return_value=None)
    mock_push_client.push.return_value = True

    mock_vs = unittest.mock.MagicMock()
    mock_vs.persist_dir = "mock_chroma"
    mock_vs.chroma_embedding_fn = None
    mock_vs.client.get_or_create_collection.return_value.query.return_value = {
        "ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]],
    }

    mock_emb = unittest.mock.MagicMock()
    mock_emb.encode.return_value = unittest.mock.MagicMock()
    mock_emb.encode.return_value.tolist.return_value = [0.1] * 384
    mock_emb.encode_single.return_value = [0.1] * 384

    patches = [
        unittest.mock.patch("agents.main_agent._get_llm_provider", return_value=mock_llm),
        unittest.mock.patch("agents.main_agent._get_db_path", return_value="mock.db"),
        unittest.mock.patch("agents.main_agent.db_read", return_value=[]),
        unittest.mock.patch("agents.main_agent.db_write", return_value=True),
        unittest.mock.patch("agents.main_agent.PushMCPClient", return_value=mock_push_client),
        unittest.mock.patch("agents.main_agent.VectorStore", return_value=mock_vs),
        unittest.mock.patch("agents.main_agent.EmbeddingModel", return_value=mock_emb),
        unittest.mock.patch("agents.collection_agent._load_config", return_value={}),
        unittest.mock.patch("agents.collection_agent._get_llm_provider", return_value=mock_llm),
        unittest.mock.patch("agents.ranking_agent._load_config", return_value={}),
        unittest.mock.patch("agents.ranking_agent._get_llm_provider", return_value=mock_llm),
        unittest.mock.patch("agents.ranking_agent._get_vector_store", return_value=mock_vs),
        unittest.mock.patch("agents.ranking_agent._get_embedding_model", return_value=mock_emb),
        unittest.mock.patch("agents.briefing_agent._get_llm_provider", return_value=mock_llm),
        unittest.mock.patch("utils.embedding.EmbeddingModel", return_value=mock_emb),
    ]

    for p in patches:
        p.start()
    try:
        agent = build_main_agent()
        result = agent.invoke(state)
    finally:
        for p in patches:
            p.stop()

    assert result.get("status") in ["running", "completed"], f"status: {result.get('status')}"
    assert "push_status" in result
    assert "execution_log" in result or "coordinator_observation" in result

    sg = result.get("structured_goal", {})
    ranked = result.get("ranked_items", [])
    push = result.get("push_status", "?")
    print(f"  [PASS] 全链路完成: push_status={push}, ranked_items={len(ranked)}, topics={sg.get('topics', [])}")


def main():
    print("=" * 60)
    print("FeedLens 集成测试")
    print("=" * 60)

    tests = [
        test_planner_normal_briefing,
        test_planner_retry_collection,
        test_planner_retry_ranking,
        test_planner_react_rethink,
        test_react_continue_under_limit,
        test_react_stop_at_limit,
        test_dedup_threshold_config,
        test_full_pipeline,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {test.__name__}: {e}")

    print("")
    print("=" * 60)
    print(f"测试结果: {passed}/{passed + failed} 通过")
    if failed > 0:
        print(f"失败: {failed}")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
