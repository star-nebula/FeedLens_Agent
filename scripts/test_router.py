"""
Router 路由测试脚本 — Phase 4a + 4b 验证。

测试内容：
  - _parse_router_response 三层 JSON 容错
  - _build_router_context 上下文构建
  - router_node 防死循环 + 硬兜底
  - _router_decide 条件边函数
  - 全部路由场景（LLM mock 模拟）
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import unittest.mock
import agents.main_agent as ma


def _mock_state(overrides: dict = None):
    base = {
        "session_id": "test-session-router",
        "trigger_type": "daily_briefing",
        "user_id": 1,
        "goal_text": "了解 AI Agent 技术进展",
        "react_cycle_count": 0,
        "agentic_turn_count": 0,
        "collected_items": [],
        "ranked_items": [],
        "briefing": {},
        "brief_quality": 0.0,
        "sub_agent_plan": [],
        "observation_result": {},
        "coordinator_observation": {},
        "push_status": "",
        "status": "running",
        "router_decision": {},
        "router_history": [],
    }
    if overrides:
        base.update(overrides)
    return base


# ============================================================
# _parse_router_response 测试
# ============================================================


def test_parse_valid_json():
    """正常 JSON 解析。"""
    print("\n[test] router - 正常 JSON 解析")
    result = ma._parse_router_response('{"next_node": "planner", "reason": "需要重新编排"}')
    assert result["next_node"] == "planner"
    assert result["reason"] == "需要重新编排"
    print("  [PASS] 正常 JSON")


def test_parse_json_with_text():
    """带额外文字的 JSON 提取。"""
    print("\n[test] router - 带文字的 JSON 提取")
    result = ma._parse_router_response('好的，我决定下一步：\n{"next_node": "invoke_sub_agent", "reason": "执行采集"}\n请执行。')
    assert result["next_node"] == "invoke_sub_agent"
    print(f"  [PASS] 带文字 JSON: next_node={result['next_node']}")


def test_parse_non_json_fallback():
    """完全非 JSON → 降级为 planner。"""
    print("\n[test] router - 非 JSON 降级")
    result = ma._parse_router_response("I think we should go to planner next")
    assert result["next_node"] == "planner"
    assert "fallback" in result.get("reason", "")
    print(f"  [PASS] 非 JSON 降级: next_node={result['next_node']}")


def test_parse_empty_string():
    """空字符串降级。"""
    print("\n[test] router - 空字符串降级")
    result = ma._parse_router_response("")
    assert result["next_node"] == "planner"
    print("  [PASS] 空字符串降级")


def test_parse_missing_next_node():
    """缺少 next_node 字段 → 降级。"""
    print("\n[test] router - 缺少 next_node")
    result = ma._parse_router_response('{"reason": "no decision"}')
    # 三层都解析不出有效 next_node → 兜底 planner
    assert result["next_node"] == "planner"
    print(f"  [PASS] 缺少 next_node: fallback to {result['next_node']}")


def test_parse_nested_json():
    """嵌套 JSON 块正确提取。"""
    print("\n[test] router - 嵌套 JSON 提取")
    text = '```json\n{"next_node": "push_notification", "reason": "简报已就绪"}\n```'
    result = ma._parse_router_response(text)
    assert result["next_node"] == "push_notification"
    print(f"  [PASS] 嵌套 JSON: next_node={result['next_node']}")


# ============================================================
# _build_router_context 测试
# ============================================================


def test_build_router_context():
    """上下文构建包含必要字段。"""
    print("\n[test] router - 构建路由上下文")
    state = _mock_state({
        "collected_items": [{"id": "1"}],
        "ranked_items": [{"id": "1"}],
        "brief_quality": 0.8,
        "sub_agent_plan": [{"agent": "Collection"}],
    })
    ctx = ma._build_router_context(state)

    assert "sub_agent_plan" in ctx
    assert "collected_count" in ctx
    assert "ranked_count" in ctx
    assert "react_cycle_count" in ctx
    assert "agentic_turn_count" in ctx
    assert "observation" in ctx
    assert "coordinator_observation" in ctx
    assert "push_status" in ctx
    assert "status" in ctx
    assert "brief_quality" in ctx

    assert ctx["collected_count"] == 1
    assert ctx["ranked_count"] == 1
    assert ctx["brief_quality"] == 0.8
    assert ctx["sub_agent_plan_count"] == 1
    print(f"  [PASS] 上下文: collected={ctx['collected_count']}, ranked={ctx['ranked_count']}, quality={ctx['brief_quality']}")


# ============================================================
# router_node 防死循环 + 硬兜底 测试
# ============================================================


def test_router_loop_detection():
    """连续 3 次相同路由 → 强制 update_memory。"""
    print("\n[test] router - 死循环检测")
    state = _mock_state({
        "agentic_turn_count": 3,
        "router_history": [
            {"next_node": "planner", "reason": "t1"},
            {"next_node": "planner", "reason": "t2"},
            {"next_node": "planner", "reason": "t3"},
        ],
    })
    result = ma.router_node(state)
    assert result["router_decision"]["next_node"] == "update_memory"
    assert "死循环" in result["router_decision"]["reason"]
    print(f"  [PASS] 死循环检测: next_node={result['router_decision']['next_node']}")


def test_router_max_turns():
    """超过 8 轮 → 强制结束。"""
    print("\n[test] router - 超过最大轮数")
    state = _mock_state({"agentic_turn_count": 8})
    result = ma.router_node(state)
    assert result["router_decision"]["next_node"] == "update_memory"
    print(f"  [PASS] 超过最大轮数: next_node={result['router_decision']['next_node']}")


# ============================================================
# router_node LLM 决策测试（mock LLM）
# ============================================================


def test_router_llm_decision_planner():
    """LLM 决策 → planner（需要重新编排）。"""
    print("\n[test] router - LLM 决策 planner")
    state = _mock_state({
        "collected_items": [],
        "observation_result": {"needs_retry": True, "issues": ["采集不足"]},
    })
    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.return_value = '{"next_node": "planner", "reason": "采集为空，需要重新编排"}'

    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=mock_llm):
        result = ma.router_node(state)

    assert result["router_decision"]["next_node"] == "planner"
    assert result["agentic_turn_count"] == 1
    assert len(result["router_history"]) == 1
    print(f"  [PASS] LLM→planner: turn={result['agentic_turn_count']}")


def test_router_llm_decision_invoke():
    """LLM 决策 → invoke_sub_agent。"""
    print("\n[test] router - LLM 决策 invoke_sub_agent")
    state = _mock_state({
        "sub_agent_plan": [{"agent": "Collection", "params": {}}],
    })
    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.return_value = '{"next_node": "invoke_sub_agent", "reason": "执行采集任务"}'

    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=mock_llm):
        result = ma.router_node(state)

    assert result["router_decision"]["next_node"] == "invoke_sub_agent"
    print(f"  [PASS] LLM→invoke_sub_agent")


def test_router_llm_decision_push():
    """LLM 决策 → push_notification（简报质量达标）。"""
    print("\n[test] router - LLM 决策 push_notification")
    state = _mock_state({
        "brief_quality": 0.85,
        "coordinator_observation": {"overall_pass": True, "issues": []},
    })
    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.return_value = '{"next_node": "push_notification", "reason": "简报质量达标，可以推送"}'

    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=mock_llm):
        result = ma.router_node(state)

    assert result["router_decision"]["next_node"] == "push_notification"
    print(f"  [PASS] LLM→push_notification")


def test_router_llm_decision_abort():
    """LLM 决策 → abort（采集始终为0）。"""
    print("\n[test] router - LLM 决策 abort")
    state = _mock_state({
        "collected_items": [],
        "react_cycle_count": 3,
        "observation_result": {"needs_retry": True, "collection_ok": False, "issues": ["采集不足"]},
    })
    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.return_value = '{"next_node": "abort", "reason": "多次重试采集仍为0，放弃执行"}'

    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=mock_llm):
        result = ma.router_node(state)

    assert result["router_decision"]["next_node"] == "abort"
    print(f"  [PASS] LLM→abort")


def test_router_llm_decision_update_memory():
    """LLM 决策 → update_memory（推送完成）。"""
    print("\n[test] router - LLM 决策 update_memory")
    state = _mock_state({
        "push_status": "sent",
        "status": "running",
    })
    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.return_value = '{"next_node": "update_memory", "reason": "推送完成，记录日志"}'

    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=mock_llm):
        result = ma.router_node(state)

    assert result["router_decision"]["next_node"] == "update_memory"
    print(f"  [PASS] LLM→update_memory")


def test_router_llm_error_fallback():
    """LLM 调用失败 → 降级到 planner。"""
    print("\n[test] router - LLM 调用失败降级")
    state = _mock_state()
    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.side_effect = RuntimeError("API 超时")

    with unittest.mock.patch.object(ma, "_get_llm_provider", return_value=mock_llm):
        result = ma.router_node(state)

    assert result["router_decision"]["next_node"] == "planner"
    assert "LLM 调用失败" in result["router_decision"]["reason"]
    print(f"  [PASS] LLM 错误降级: {result['router_decision']['reason']}")


# ============================================================
# _router_decide 测试
# ============================================================


def test_router_decide_normal():
    """正常路由决策读取。"""
    print("\n[test] router - _router_decide 正常")
    state = _mock_state({"router_decision": {"next_node": "invoke_sub_agent", "reason": "test"}})
    result = ma._router_decide(state)
    assert result == "invoke_sub_agent"
    print(f"  [PASS] _router_decide: {result}")


def test_router_decide_end():
    """END 路由。"""
    print("\n[test] router - _router_decide END")
    state = _mock_state({"router_decision": {"next_node": "END", "reason": "流程结束"}})
    result = ma._router_decide(state)
    assert result == "END"
    print(f"  [PASS] _router_decide: {result}")


def test_router_decide_invalid_node():
    """非法节点 → 降级 planner。"""
    print("\n[test] router - _router_decide 非法节点")
    state = _mock_state({"router_decision": {"next_node": "unknown_node", "reason": "test"}})
    result = ma._router_decide(state)
    assert result == "planner"
    print(f"  [PASS] _router_decide 非法节点降级: {result}")


def test_router_decide_empty_decision():
    """router_decision 为空 → 降级 planner。"""
    print("\n[test] router - _router_decide 空决策")
    state = _mock_state()
    result = ma._router_decide(state)
    assert result == "planner"
    print(f"  [PASS] _router_decide 空决策降级: {result}")


# ============================================================
# ROUTER_SYSTEM_PROMPT 验证
# ============================================================


def test_router_system_prompt():
    """验证 ROUTER_SYSTEM_PROMPT 包含所有可跳转节点。"""
    print("\n[test] router - ROUTER_SYSTEM_PROMPT")
    prompt = ma.ROUTER_SYSTEM_PROMPT
    required_nodes = [
        "planner", "invoke_sub_agent", "observe_results",
        "coordinator_reflect", "push_notification", "update_memory",
        "abort", "END",
    ]
    for node in required_nodes:
        assert node in prompt, f"ROUTER_SYSTEM_PROMPT 缺少节点: {node}"
    assert '{"next_node"' in prompt
    assert '"reason"' in prompt
    print(f"  [PASS] ROUTER_SYSTEM_PROMPT 包含全部 {len(required_nodes)} 个节点")


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    tests = [
        # _parse_router_response
        ("JSON 解析-正常", test_parse_valid_json),
        ("JSON 解析-带文字", test_parse_json_with_text),
        ("JSON 解析-非JSON降级", test_parse_non_json_fallback),
        ("JSON 解析-空字符串", test_parse_empty_string),
        ("JSON 解析-缺少next_node", test_parse_missing_next_node),
        ("JSON 解析-嵌套JSON", test_parse_nested_json),
        # _build_router_context
        ("构建上下文", test_build_router_context),
        # router_node 安全机制
        ("死循环检测", test_router_loop_detection),
        ("超过最大轮数", test_router_max_turns),
        # router_node LLM 决策
        ("LLM→planner", test_router_llm_decision_planner),
        ("LLM→invoke_sub_agent", test_router_llm_decision_invoke),
        ("LLM→push_notification", test_router_llm_decision_push),
        ("LLM→abort", test_router_llm_decision_abort),
        ("LLM→update_memory", test_router_llm_decision_update_memory),
        ("LLM 错误降级", test_router_llm_error_fallback),
        # _router_decide
        ("_router_decide 正常", test_router_decide_normal),
        ("_router_decide END", test_router_decide_end),
        ("_router_decide 非法节点", test_router_decide_invalid_node),
        ("_router_decide 空决策", test_router_decide_empty_decision),
        # System Prompt
        ("ROUTER_SYSTEM_PROMPT", test_router_system_prompt),
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
