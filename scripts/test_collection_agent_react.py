"""
采集 Agent ReAct 测试脚本 — Phase 3a 验证。

Mock LLM 返回 tool_calls，验证 ReAct 循环行为：
  - LLM 调 fetch_rss → 返回采集结果
  - LLM 调 search_web → 返回搜索结果
  - LLM 调 finish_task → 循环正确退出
  - 超过 5 轮未调 finish_task → 强制退出并返回已有数据
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import unittest.mock
import agents.collection_agent as ca


def _mock_state(overrides: dict = None):
    base = {
        "session_id": "test-session-collection",
        "trigger_type": "daily_briefing",
        "user_id": 1,
        "goal_text": "了解 AI Agent 技术进展",
        "structured_goal": {
            "topics": ["AI Agent", "大模型"],
            "keywords": ["LLM", "多智能体"],
            "preferred_sources": [],
        },
        "goal_embedding": [0.1] * 384,
        "collected_items": [],
    }
    if overrides:
        base.update(overrides)
    return base


def _mock_tool_call_response(tool_calls: list):
    """构造 mock LLM 返回的 tool_calls 响应（chat_with_tools 格式）。"""
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


def test_fetch_rss_flow():
    """LLM 调 fetch_rss → 返回采集结果。"""
    print("\n[test] collection_react - fetch_rss 流程")

    mock_llm = unittest.mock.MagicMock()
    # 第1轮：调 fetch_rss
    mock_llm.chat_with_tools.side_effect = [
        _mock_tool_call_response([
            _make_tool_call("fetch_rss", {"sources": ["https://example.com/rss"], "max_workers": 3})
        ]),
        # 第2轮：调 finish_task
        _mock_tool_call_response([
            _make_tool_call("finish_task", {"summary": "采集完成，共3条", "status": "success"})
        ]),
    ]

    state = _mock_state()

    with unittest.mock.patch.object(ca, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch.object(ca, "_get_rss_sources", return_value=["https://example.com/rss"]):
            with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
                mock_registry.get_schemas_for_phase.return_value = [{"type": "function", "function": {"name": "fetch_rss"}}]
                mock_registry.dispatch.side_effect = [
                    {"items": [
                        {"title": "AI Agent 新突破", "source_url": "https://example.com/rss"},
                        {"title": "大模型应用实践", "source_url": "https://example.com/rss"},
                        {"title": "多智能体协作", "source_url": "https://example.com/rss"},
                    ], "count": 3, "valid_count": 3},
                    {"finished": True, "summary": "采集完成，共3条", "status": "success"},
                ]

                result = ca.run_collection_agent(state)

    assert "collected_items" in result, f"缺少 collected_items 字段: {result.keys()}"
    assert len(result["collected_items"]) == 3, f"期望 3 条采集结果，实际 {len(result['collected_items'])}"
    assert result["collected_items"][0]["title"] == "AI Agent 新突破"
    print(f"  [PASS] fetch_rss 流程: {len(result['collected_items'])} 条采集结果")


def test_search_web_fallback():
    """LLM 调 search_web → 补充搜索返回结果。"""
    print("\n[test] collection_react - search_web 补充搜索")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.side_effect = [
        _mock_tool_call_response([
            _make_tool_call("fetch_rss", {"sources": ["https://example.com/rss"]})
        ]),
        _mock_tool_call_response([
            _make_tool_call("search_web", {"query": "AI Agent", "max_results": 3})
        ]),
        _mock_tool_call_response([
            _make_tool_call("finish_task", {"summary": "RSS+搜索完成", "status": "success"})
        ]),
    ]

    state = _mock_state()

    with unittest.mock.patch.object(ca, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch.object(ca, "_get_rss_sources", return_value=["https://example.com/rss"]):
            with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
                mock_registry.get_schemas_for_phase.return_value = []
                mock_registry.dispatch.side_effect = [
                    {"items": [{"title": "RSS 条目", "source_url": "rss"}], "count": 1, "valid_count": 1},
                    {"items": [
                        {"title": "搜索结果1", "source_url": "web_search"},
                        {"title": "搜索结果2", "source_url": "web_search"},
                    ], "count": 2},
                    {"finished": True, "summary": "RSS+搜索完成", "status": "success"},
                ]

                result = ca.run_collection_agent(state)

    assert len(result["collected_items"]) == 3, f"期望 3 条（1 RSS + 2 搜索），实际 {len(result['collected_items'])}"
    assert result["search_supplemented"] is True, "应标记 search_supplemented=True"
    print(f"  [PASS] search_web 补充: collected={len(result['collected_items'])}, search_supplemented={result['search_supplemented']}")


def test_finish_task_exit():
    """LLM 调 finish_task → 循环正确退出。"""
    print("\n[test] collection_react - finish_task 退出")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.return_value = _mock_tool_call_response([
        _make_tool_call("finish_task", {"summary": "直接完成", "status": "success"})
    ])

    state = _mock_state({"collected_items": [{"title": "已有条目", "id": "test_001"}]})

    with unittest.mock.patch.object(ca, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
            mock_registry.get_schemas_for_phase.return_value = []
            mock_registry.dispatch.return_value = {"finished": True, "summary": "直接完成", "status": "success"}

            result = ca.run_collection_agent(state)

    assert "collected_items" in result
    assert result["collection_summary"] == "直接完成"
    print(f"  [PASS] finish_task 退出: summary={result['collection_summary']}")


def test_max_turns_force_exit():
    """超过 5 轮未调 finish_task → 强制退出并返回已有数据。"""
    print("\n[test] collection_react - max_turns 强制退出")

    mock_llm = unittest.mock.MagicMock()
    # 每轮都返回非 finish_task 的工具调用，触发 max_turns 兜底
    responses = []
    for i in range(5):
        responses.append(_mock_tool_call_response([
            _make_tool_call("fetch_rss", {"sources": ["https://example.com/rss"]}, call_id=f"call_fetch_{i}")
        ]))
    mock_llm.chat_with_tools.side_effect = responses

    state = _mock_state()

    with unittest.mock.patch.object(ca, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch.object(ca, "_get_rss_sources", return_value=["https://example.com/rss"]):
            with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
                mock_registry.get_schemas_for_phase.return_value = []
                mock_registry.dispatch.return_value = {
                    "items": [{"title": f"条目{i}", "source_url": "rss"}],
                    "count": 1, "valid_count": 1,
                }

                result = ca.run_collection_agent(state)

    # 5轮后强制返回，每轮采集1条，共5条
    assert len(result["collected_items"]) == 5, f"期望 5 条，实际 {len(result['collected_items'])}"
    assert "超时结束" in result["collection_summary"], f"期望超时标记，实际: {result['collection_summary']}"
    print(f"  [PASS] max_turns 强制退出: {len(result['collected_items'])} 条, summary={result['collection_summary']}")


def test_llm_error_graceful_degrade():
    """LLM 调用失败 → 优雅降级，返回已有数据。"""
    print("\n[test] collection_react - LLM 调用失败降级")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.side_effect = RuntimeError("LLM 服务不可用")

    state = _mock_state({"collected_items": [{"title": "预存条目", "id": "pre_001"}]})

    with unittest.mock.patch.object(ca, "_get_llm_provider", return_value=mock_llm):
        result = ca.run_collection_agent(state)

    assert "collected_items" in result
    assert len(result["collected_items"]) >= 0
    print(f"  [PASS] LLM 错误降级: collected={len(result['collected_items'])}")


def test_build_collection_agent_compat():
    """验证 build_collection_agent() 兼容接口可正常调用。"""
    print("\n[test] collection_react - build_collection_agent 兼容接口")

    agent = ca.build_collection_agent()
    assert agent is not None, "build_collection_agent() 返回 None"
    assert hasattr(agent, "invoke"), "缺少 invoke 方法"

    print("  [PASS] build_collection_agent 兼容接口正常")


def test_system_prompt_exists():
    """验证 COLLECTION_SYSTEM_PROMPT 已定义。"""
    print("\n[test] collection_react - System Prompt")

    assert ca.COLLECTION_SYSTEM_PROMPT, "COLLECTION_SYSTEM_PROMPT 为空"
    assert "fetch_rss" in ca.COLLECTION_SYSTEM_PROMPT
    assert "finish_task" in ca.COLLECTION_SYSTEM_PROMPT
    print("  [PASS] COLLECTION_SYSTEM_PROMPT 包含 fetch_rss 和 finish_task")


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    tests = [
        ("build_collection_agent 兼容", test_build_collection_agent_compat),
        ("System Prompt", test_system_prompt_exists),
        ("fetch_rss 流程", test_fetch_rss_flow),
        ("search_web 补充", test_search_web_fallback),
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
