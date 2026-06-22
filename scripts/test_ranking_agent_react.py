"""
排序 Agent ReAct 测试脚本 — Phase 3b 验证。

Mock LLM 返回 tool_calls，验证 ReAct 循环行为：
  - LLM 调 deduplicate → rank_items → finish_task 流程
  - LLM 直接调 rank_items → finish_task（跳过去重）
  - 超过 5 轮未调 finish_task → 强制退出并返回已有数据
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import unittest.mock
import agents.ranking_agent as ra


def _mock_state(overrides: dict = None):
    base = {
        "session_id": "test-session-ranking",
        "trigger_type": "daily_briefing",
        "user_id": 1,
        "goal_text": "了解 AI Agent 技术进展",
        "structured_goal": {
            "topics": ["AI Agent", "大模型"],
            "keywords": ["LLM", "多智能体"],
            "preferred_sources": [],
        },
        "goal_embedding": [0.1] * 384,
        "collected_items": [
            {"id": "item_001", "title": "AI Agent 新突破", "summary": "最新进展", "source": "rss_a", "url": "http://a.com/1", "importance": 0.9, "category": "科技", "published_at": "2026-06-20T10:00:00"},
            {"id": "item_002", "title": "AI Agent 新突破（重复）", "summary": "相同内容", "source": "rss_b", "url": "http://b.com/1", "importance": 0.8, "category": "科技", "published_at": "2026-06-20T11:00:00"},
            {"id": "item_003", "title": "大模型应用实践", "summary": "实践案例", "source": "rss_c", "url": "http://c.com/1", "importance": 0.7, "category": "科技", "published_at": "2026-06-21T09:00:00"},
            {"id": "item_004", "title": "多智能体协作", "summary": "协作框架", "source": "rss_d", "url": "http://d.com/1", "importance": 0.6, "category": "科技", "published_at": "2026-06-19T08:00:00"},
        ],
        "ranked_items": [],
        "ranking_detail": {},
        "feedback_history": [],
    }
    if overrides:
        base.update(overrides)
    return base


def _mock_tool_call_response(tool_calls: list):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": tool_calls,
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


def _make_tool_call(name: str, args: dict, call_id: str = None):
    return {
        "id": call_id or f"call_{name}_001",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(args, ensure_ascii=False),
        },
    }


# ============================================================
# 测试用例
# ============================================================


def test_dedup_then_rank_flow():
    """LLM 调 deduplicate → rank_items → finish_task 标准流程。"""
    print("\n[test] ranking_react - dedup → rank → finish 标准流程")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.side_effect = [
        _mock_tool_call_response([
            _make_tool_call("deduplicate", {"items": []})
        ]),
        _mock_tool_call_response([
            _make_tool_call("rank_items", {"items": []})
        ]),
        _mock_tool_call_response([
            _make_tool_call("finish_task", {"summary": "去重+排序完成，共3条", "status": "success"})
        ]),
    ]

    state = _mock_state()

    with unittest.mock.patch.object(ra, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch("agents.ranking_agent.vector_search_node") as mock_vs:
            mock_vs.return_value = {"user_preferences": [], "feedback_history": []}
            with unittest.mock.patch("agents.ranking_agent.tool_registry") as mock_registry:
                mock_registry.get_schemas_for_phase.return_value = []
                mock_registry.dispatch.side_effect = [
                    {"unique_items": state["collected_items"][:3], "duplicate_pairs": [
                        {"item_a_id": "item_001", "item_b_id": "item_002", "similarity_score": 0.92}
                    ], "unique_count": 3},
                    {"ranked_items": state["collected_items"][:3], "ranking_detail": {"top_score": 0.85, "total_items": 3}},
                    {"finished": True, "summary": "去重+排序完成，共3条", "status": "success"},
                ]

                result = ra.run_ranking_agent(state)

    assert "ranked_items" in result, f"缺少 ranked_items: {result.keys()}"
    assert "ranking_detail" in result
    assert "item_relations" in result
    print(f"  [PASS] dedup→rank→finish: ranked={len(result['ranked_items'])} 条")


def test_skip_dedup_direct_rank():
    """LLM 直接调 rank_items → finish_task（跳过去重）。"""
    print("\n[test] ranking_react - 跳过去重直接排序")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.side_effect = [
        _mock_tool_call_response([
            _make_tool_call("rank_items", {"items": []})
        ]),
        _mock_tool_call_response([
            _make_tool_call("finish_task", {"summary": "直接排序完成", "status": "success"})
        ]),
    ]

    base_state = _mock_state()
    state = _mock_state({"collected_items": [base_state["collected_items"][0]]})  # 仅1条

    with unittest.mock.patch.object(ra, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch("agents.ranking_agent.vector_search_node") as mock_vs:
            mock_vs.return_value = {"user_preferences": [], "feedback_history": []}
            with unittest.mock.patch("agents.ranking_agent.tool_registry") as mock_registry:
                mock_registry.get_schemas_for_phase.return_value = []
                mock_registry.dispatch.side_effect = [
                    {"ranked_items": state["collected_items"], "ranking_detail": {"top_score": 0.9, "total_items": 1}},
                    {"finished": True, "summary": "直接排序完成", "status": "success"},
                ]

                result = ra.run_ranking_agent(state)

    assert len(result["ranked_items"]) == 1
    print(f"  [PASS] 跳过 dedup 直接 rank: {len(result['ranked_items'])} 条")


def test_finish_task_exit():
    """LLM 调 finish_task → 循环正确退出。"""
    print("\n[test] ranking_react - finish_task 退出")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.return_value = _mock_tool_call_response([
        _make_tool_call("finish_task", {"summary": "排序直接完成", "status": "success"})
    ])

    state = _mock_state()

    with unittest.mock.patch.object(ra, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch("agents.ranking_agent.vector_search_node") as mock_vs:
            mock_vs.return_value = {"user_preferences": [], "feedback_history": []}
            with unittest.mock.patch("agents.ranking_agent.tool_registry") as mock_registry:
                mock_registry.get_schemas_for_phase.return_value = []
                mock_registry.dispatch.return_value = {"finished": True, "summary": "排序直接完成", "status": "success"}

                result = ra.run_ranking_agent(state)

    assert "ranking_summary" in result
    print(f"  [PASS] finish_task 退出: summary={result['ranking_summary']}")


def test_max_turns_force_exit():
    """超过 5 轮未调 finish_task → 强制退出并返回已有数据。"""
    print("\n[test] ranking_react - max_turns 强制退出")

    mock_llm = unittest.mock.MagicMock()
    responses = []
    for i in range(5):
        responses.append(_mock_tool_call_response([
            _make_tool_call("deduplicate", {"items": []}, call_id=f"call_dedup_{i}")
        ]))
    mock_llm.chat_with_tools.side_effect = responses

    state = _mock_state()

    with unittest.mock.patch.object(ra, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch("agents.ranking_agent.vector_search_node") as mock_vs:
            mock_vs.return_value = {"user_preferences": [], "feedback_history": []}
            with unittest.mock.patch("agents.ranking_agent.tool_registry") as mock_registry:
                mock_registry.get_schemas_for_phase.return_value = []
                mock_registry.dispatch.return_value = {
                    "unique_items": state["collected_items"][:2],
                    "duplicate_pairs": [],
                    "unique_count": 2,
                }

                result = ra.run_ranking_agent(state)

    assert "超时结束" in result.get("ranking_summary", ""), f"期望超时标记，实际: {result.get('ranking_summary')}"
    print(f"  [PASS] max_turns 强制退出: ranking_summary={result['ranking_summary']}")


def test_llm_error_graceful_degrade():
    """LLM 调用失败 → 优雅降级。"""
    print("\n[test] ranking_react - LLM 调用失败降级")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.side_effect = RuntimeError("LLM 服务不可用")

    state = _mock_state()

    with unittest.mock.patch.object(ra, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch("agents.ranking_agent.vector_search_node") as mock_vs:
            mock_vs.return_value = {"user_preferences": [], "feedback_history": []}
            result = ra.run_ranking_agent(state)

    assert "ranked_items" in result
    assert "ranking_summary" in result
    print(f"  [PASS] LLM 错误降级: ranked={len(result['ranked_items'])}")


def test_build_ranking_agent_compat():
    """验证 build_ranking_agent() 兼容接口。"""
    print("\n[test] ranking_react - build_ranking_agent 兼容接口")

    agent = ra.build_ranking_agent()
    assert agent is not None
    assert hasattr(agent, "invoke")
    print("  [PASS] build_ranking_agent 兼容接口正常")


def test_system_prompt_exists():
    """验证 RANKING_SYSTEM_PROMPT 已定义。"""
    print("\n[test] ranking_react - System Prompt")

    assert ra.RANKING_SYSTEM_PROMPT, "RANKING_SYSTEM_PROMPT 为空"
    assert "deduplicate" in ra.RANKING_SYSTEM_PROMPT
    assert "rank_items" in ra.RANKING_SYSTEM_PROMPT
    assert "finish_task" in ra.RANKING_SYSTEM_PROMPT
    print("  [PASS] RANKING_SYSTEM_PROMPT 包含 deduplicate/rank_items/finish_task")


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    tests = [
        ("build_ranking_agent 兼容", test_build_ranking_agent_compat),
        ("System Prompt", test_system_prompt_exists),
        ("dedup→rank→finish 流程", test_dedup_then_rank_flow),
        ("跳过dedup直接rank", test_skip_dedup_direct_rank),
        ("finish_task 退出", test_finish_task_exit),
        ("max_turns 强制退出", test_max_turns_force_exit),
        ("LLM 错误降级", test_llm_error_graceful_degrade),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {name}: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*50}")
    print(f"结果: {passed} 通过, {failed} 失败, 共 {len(tests)} 项")
    if failed > 0:
        sys.exit(1)
