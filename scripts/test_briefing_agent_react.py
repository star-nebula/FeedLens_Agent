"""
简报 Agent ReAct 测试脚本 — Phase 3c 验证。

Mock LLM 返回 tool_calls，验证 ReAct 循环行为：
  - LLM 调 generate_briefing → quality_check → finish_task
  - quality_check 返回低分 → LLM 重新调 generate_briefing
  - 超过 5 轮未调 finish_task → 强制退出并返回已有简报
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import unittest.mock
import agents.briefing_agent as ba


def _mock_state(overrides: dict = None):
    base = {
        "session_id": "test-session-briefing",
        "trigger_type": "daily_briefing",
        "user_id": 1,
        "goal_text": "了解 AI Agent 技术进展",
        "categories": ["科技", "商业", "社会", "其他"],
        "ranked_items": [
            {"id": "item_001", "title": "AI Agent 新突破", "summary": "最新进展摘要", "source": "rss_a", "url": "http://a.com/1", "importance": 0.9, "category": "科技", "published_at": "2026-06-20T10:00:00"},
            {"id": "item_002", "title": "大模型应用实践", "summary": "实践案例分享", "source": "rss_b", "url": "http://b.com/1", "importance": 0.8, "category": "科技", "published_at": "2026-06-21T09:00:00"},
            {"id": "item_003", "title": "多智能体协作", "summary": "协作框架设计", "source": "rss_c", "url": "http://c.com/1", "importance": 0.7, "category": "科技", "published_at": "2026-06-19T08:00:00"},
        ],
        "briefing": {},
        "brief_quality": 0.0,
        "quality_detail": {},
        "briefing_result": {},
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


def test_generate_then_quality_then_finish():
    """LLM 调 generate_briefing → quality_check → finish_task 标准流程。"""
    print("\n[test] briefing_react - generate → quality → finish 标准流程")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.side_effect = [
        _mock_tool_call_response([
            _make_tool_call("generate_briefing", {"items": [], "goal_text": "test"})
        ]),
        _mock_tool_call_response([
            _make_tool_call("quality_check", {"briefing": {}, "ranked_items": []})
        ]),
        _mock_tool_call_response([
            _make_tool_call("finish_task", {"summary": "简报生成完成，质量评分 0.85", "status": "success"})
        ]),
    ]

    state = _mock_state()

    with unittest.mock.patch.object(ba, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch("agents.briefing_agent.tool_registry") as mock_registry:
            mock_registry.get_schemas_for_phase.return_value = []
            mock_registry.dispatch.side_effect = [
                {"briefing": {
                    "title": "AI Agent 技术周报",
                    "summary": "本周 AI Agent 领域重要进展",
                    "categories": [{"name": "科技", "items": state["ranked_items"][:2]}],
                    "_markdown": "# AI Agent 技术周报\n...",
                }},
                {"brief_quality": 0.85, "quality_detail": {"completeness": 1.0, "relevance": 0.9, "coherence": 0.8, "score": 0.85}},
                {"finished": True, "summary": "简报生成完成，质量评分 0.85", "status": "success"},
            ]

            result = ba.run_briefing_agent(state)

    assert "briefing" in result, f"缺少 briefing: {result.keys()}"
    assert result["briefing"]["title"] == "AI Agent 技术周报"
    assert result["brief_quality"] == 0.85
    print(f"  [PASS] generate→quality→finish: quality={result['brief_quality']}")


def test_quality_low_retry():
    """quality_check 返回低分 → LLM 重新调 generate_briefing。"""
    print("\n[test] briefing_react - 质量低分重试")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.side_effect = [
        # 第1轮：生成
        _mock_tool_call_response([
            _make_tool_call("generate_briefing", {"items": [], "goal_text": "test"})
        ]),
        # 第2轮：审查（低分）
        _mock_tool_call_response([
            _make_tool_call("quality_check", {"briefing": {}, "ranked_items": []})
        ]),
        # 第3轮：重新生成
        _mock_tool_call_response([
            _make_tool_call("generate_briefing", {"items": [], "goal_text": "test", "retry_count": 1})
        ]),
        # 第4轮：审查（高分）
        _mock_tool_call_response([
            _make_tool_call("quality_check", {"briefing": {}, "ranked_items": []})
        ]),
        # 第5轮：完成
        _mock_tool_call_response([
            _make_tool_call("finish_task", {"summary": "重试后质量达标", "status": "success"})
        ]),
    ]

    state = _mock_state()

    with unittest.mock.patch.object(ba, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch("agents.briefing_agent.tool_registry") as mock_registry:
            mock_registry.get_schemas_for_phase.return_value = []
            mock_registry.dispatch.side_effect = [
                {"briefing": {"title": "初版简报", "summary": "质量不足"}},
                {"brief_quality": 0.55, "quality_detail": {"score": 0.55}},  # 低分
                {"briefing": {"title": "优化后简报", "summary": "质量改善"}},
                {"brief_quality": 0.82, "quality_detail": {"score": 0.82}},  # 高分
                {"finished": True, "summary": "重试后质量达标", "status": "success"},
            ]

            result = ba.run_briefing_agent(state)

    assert result["brief_quality"] == 0.82, f"期望质量 0.82，实际 {result['brief_quality']}"
    assert result["briefing"]["title"] == "优化后简报"
    print(f"  [PASS] 质量低分重试: final_quality={result['brief_quality']}, title={result['briefing']['title']}")


def test_finish_task_exit():
    """LLM 调 finish_task → 循环正确退出。"""
    print("\n[test] briefing_react - finish_task 退出")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.return_value = _mock_tool_call_response([
        _make_tool_call("finish_task", {"summary": "直接完成", "status": "success"})
    ])

    state = _mock_state()

    with unittest.mock.patch.object(ba, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch("agents.briefing_agent.tool_registry") as mock_registry:
            mock_registry.get_schemas_for_phase.return_value = []
            mock_registry.dispatch.return_value = {"finished": True, "summary": "直接完成", "status": "success"}

            result = ba.run_briefing_agent(state)

    assert "briefing_summary" in result
    print(f"  [PASS] finish_task 退出: summary={result['briefing_summary']}")


def test_max_turns_force_exit():
    """超过 5 轮未调 finish_task → 强制退出并返回已有简报。"""
    print("\n[test] briefing_react - max_turns 强制退出")

    mock_llm = unittest.mock.MagicMock()
    responses = []
    for i in range(5):
        responses.append(_mock_tool_call_response([
            _make_tool_call("generate_briefing", {"items": [], "goal_text": "test"}, call_id=f"call_gen_{i}")
        ]))
    mock_llm.chat_with_tools.side_effect = responses

    state = _mock_state()

    with unittest.mock.patch.object(ba, "_get_llm_provider", return_value=mock_llm):
        with unittest.mock.patch("agents.briefing_agent.tool_registry") as mock_registry:
            mock_registry.get_schemas_for_phase.return_value = []
            mock_registry.dispatch.return_value = {
                "briefing": {"title": f"简报第{i}版", "summary": "..."},
            }

            result = ba.run_briefing_agent(state)

    assert "超时结束" in result.get("briefing_summary", ""), f"期望超时标记，实际: {result.get('briefing_summary')}"
    print(f"  [PASS] max_turns 强制退出: briefing_summary={result['briefing_summary']}")


def test_llm_error_graceful_degrade():
    """LLM 调用失败 → 优雅降级。"""
    print("\n[test] briefing_react - LLM 调用失败降级")

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat_with_tools.side_effect = RuntimeError("LLM 服务不可用")

    state = _mock_state()

    with unittest.mock.patch.object(ba, "_get_llm_provider", return_value=mock_llm):
        result = ba.run_briefing_agent(state)

    assert "briefing" in result
    assert "brief_quality" in result
    print(f"  [PASS] LLM 错误降级: brief_quality={result['brief_quality']}")


def test_build_briefing_agent_compat():
    """验证 build_briefing_agent() 兼容接口。"""
    print("\n[test] briefing_react - build_briefing_agent 兼容接口")

    agent = ba.build_briefing_agent()
    assert agent is not None
    assert hasattr(agent, "invoke")
    print("  [PASS] build_briefing_agent 兼容接口正常")


def test_system_prompt_exists():
    """验证 BRIEFING_SYSTEM_PROMPT 已定义。"""
    print("\n[test] briefing_react - System Prompt")

    assert ba.BRIEFING_SYSTEM_PROMPT, "BRIEFING_SYSTEM_PROMPT 为空"
    assert "generate_briefing" in ba.BRIEFING_SYSTEM_PROMPT
    assert "quality_check" in ba.BRIEFING_SYSTEM_PROMPT
    assert "finish_task" in ba.BRIEFING_SYSTEM_PROMPT
    print("  [PASS] BRIEFING_SYSTEM_PROMPT 包含 generate_briefing/quality_check/finish_task")


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    tests = [
        ("build_briefing_agent 兼容", test_build_briefing_agent_compat),
        ("System Prompt", test_system_prompt_exists),
        ("generate→quality→finish 流程", test_generate_then_quality_then_finish),
        ("质量低分重试", test_quality_low_retry),
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
