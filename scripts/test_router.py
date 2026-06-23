"""
Router 路由测试脚本 — Phase 4a + 4b 验证 + P0-2.4 规则优先路由。

测试内容：
  - _parse_router_response 三层 JSON 容错
  - _rule_based_router_decision 规则路由覆盖
  - router_node 防死循环 + 硬兜底
  - router_node 规则优先路由（无需 mock LLM）
  - _router_decide 条件边函数
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
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
# _rule_based_router_decision 测试（P0-2.4 规则优先路由）
# ============================================================


def test_rule_plan_not_executed():
    """plan 非空且未执行 → invoke_sub_agent。"""
    print("\n[test] router - 规则：plan未执行→invoke_sub_agent")
    state = _mock_state({
        "sub_agent_plan": [{"agent": "Collection", "params": {}}],
        "sub_agent_executed": False,
    })
    result = ma._rule_based_router_decision(state)
    assert result is not None
    assert result["next_node"] == "invoke_sub_agent"
    print(f"  [PASS] 规则路由: {result['next_node']}")


def test_rule_executed_no_observe():
    """已执行但未观察 → observe_results。"""
    print("\n[test] router - 规则：已执行未观察→observe_results")
    state = _mock_state({
        "sub_agent_executed": True,
        "observation_result": {},
    })
    result = ma._rule_based_router_decision(state)
    assert result is not None
    assert result["next_node"] == "observe_results"
    print(f"  [PASS] 规则路由: {result['next_node']}")


def test_rule_needs_retry_under_limit():
    """needs_retry 且未达上限 → None（需 LLM planner）。"""
    print("\n[test] router - 规则：needs_retry未达上限→None(需LLM)")
    state = _mock_state({
        "observation_result": {"needs_retry": True, "issues": ["采集不足"]},
        "react_cycle_count": 1,
    })
    result = ma._rule_based_router_decision(state)
    assert result is None
    print(f"  [PASS] 规则无法覆盖: result=None")


def test_rule_needs_retry_at_limit_abort():
    """needs_retry 已达上限且采集为0 → abort。"""
    print("\n[test] router - 规则：needs_retry达上限+采集0→abort")
    state = _mock_state({
        "observation_result": {"needs_retry": True, "issues": ["采集不足"], "collection_ok": False},
        "react_cycle_count": 3,
        "collected_items": [],
    })
    result = ma._rule_based_router_decision(state)
    assert result is not None
    assert result["next_node"] == "abort"
    print(f"  [PASS] 规则路由: {result['next_node']}")


def test_rule_needs_retry_at_limit_converge():
    """needs_retry 已达上限但有数据 → update_memory 收敛。"""
    print("\n[test] router - 规则：needs_retry达上限+有数据→收敛")
    state = _mock_state({
        "observation_result": {"needs_retry": True, "issues": ["简报质量低"]},
        "react_cycle_count": 3,
        "collected_items": [{"id": "1"}],
    })
    result = ma._rule_based_router_decision(state)
    assert result is not None
    assert result["next_node"] == "update_memory"
    print(f"  [PASS] 规则路由: {result['next_node']}")


def test_rule_no_retry_coordinator():
    """needs_retry=false → coordinator_reflect。"""
    print("\n[test] router - 规则：无需重试→coordinator_reflect")
    state = _mock_state({
        "observation_result": {"needs_retry": False, "issues": []},
    })
    result = ma._rule_based_router_decision(state)
    assert result is not None
    assert result["next_node"] == "coordinator_reflect"
    print(f"  [PASS] 规则路由: {result['next_node']}")


def test_rule_coordinator_pass_push():
    """审查通过 → push_notification。"""
    print("\n[test] router - 规则：审查通过→push_notification")
    state = _mock_state({
        "coordinator_observation": {"overall_pass": True, "issues": []},
        "push_status": "",
    })
    result = ma._rule_based_router_decision(state)
    assert result is not None
    assert result["next_node"] == "push_notification"
    print(f"  [PASS] 规则路由: {result['next_node']}")


def test_rule_coordinator_fail_under_limit():
    """审查不通过未达上限 → None（需 LLM planner）。"""
    print("\n[test] router - 规则：审查不通过未达上限→None(需LLM)")
    state = _mock_state({
        "coordinator_observation": {"overall_pass": False, "issues": ["简报质量低"]},
        "react_cycle_count": 1,
    })
    result = ma._rule_based_router_decision(state)
    assert result is None
    print(f"  [PASS] 规则无法覆盖: result=None")


def test_rule_coordinator_fail_at_limit():
    """审查不通过已达上限 → 强制推送。"""
    print("\n[test] router - 规则：审查不通过达上限→强制推送")
    state = _mock_state({
        "coordinator_observation": {"overall_pass": False, "issues": ["简报质量低"]},
        "react_cycle_count": 3,
    })
    result = ma._rule_based_router_decision(state)
    assert result is not None
    assert result["next_node"] == "push_notification"
    print(f"  [PASS] 规则路由: {result['next_node']}")


def test_rule_push_sent_update_memory():
    """推送完成 → update_memory。"""
    print("\n[test] router - 规则：推送完成→update_memory")
    state = _mock_state({
        "push_status": "sent",
    })
    result = ma._rule_based_router_decision(state)
    assert result is not None
    assert result["next_node"] == "update_memory"
    print(f"  [PASS] 规则路由: {result['next_node']}")


def test_rule_fallback_update_memory():
    """无匹配规则 → 兜底 update_memory。"""
    print("\n[test] router - 规则：兜底→update_memory")
    state = _mock_state({
        "status": "running",
    })
    result = ma._rule_based_router_decision(state)
    assert result is not None
    assert result["next_node"] == "update_memory"
    print(f"  [PASS] 规则路由: {result['next_node']}")


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
# router_node 规则优先路由测试（P0-2.4：无需 mock LLM）
# ============================================================


def test_router_rule_plan_not_executed():
    """规则优先：plan 非空 → invoke_sub_agent（不调 LLM）。"""
    print("\n[test] router - 规则优先：plan→invoke_sub_agent")
    state = _mock_state({
        "sub_agent_plan": [{"agent": "Collection", "params": {}}],
    })
    result = ma.router_node(state)
    assert result["router_decision"]["next_node"] == "invoke_sub_agent"
    assert "规则路由" in result["router_decision"]["reason"]
    print(f"  [PASS] 规则优先→invoke_sub_agent（无LLM调用）")


def test_router_rule_needs_retry_to_planner():
    """规则优先：needs_retry 未达上限 → planner（planner 内会调 LLM）。"""
    print("\n[test] router - 规则优先：needs_retry→planner")
    state = _mock_state({
        "observation_result": {"needs_retry": True, "issues": ["采集不足"]},
        "react_cycle_count": 1,
    })
    result = ma.router_node(state)
    assert result["router_decision"]["next_node"] == "planner"
    assert "规则无法覆盖" in result["router_decision"]["reason"]
    print(f"  [PASS] 规则优先→planner（planner内会调LLM重编排）")


def test_router_rule_coordinator_pass_push():
    """规则优先：审查通过 → push_notification。"""
    print("\n[test] router - 规则优先：审查通过→push")
    state = _mock_state({
        "coordinator_observation": {"overall_pass": True, "issues": []},
    })
    result = ma.router_node(state)
    assert result["router_decision"]["next_node"] == "push_notification"
    assert "规则路由" in result["router_decision"]["reason"]
    print(f"  [PASS] 规则优先→push_notification")


def test_router_rule_abort_on_limit():
    """规则优先：needs_retry 达上限+采集为0 → abort。"""
    print("\n[test] router - 规则优先：达上限+采集0→abort")
    state = _mock_state({
        "observation_result": {"needs_retry": True, "issues": ["采集不足"]},
        "react_cycle_count": 3,
        "collected_items": [],
    })
    result = ma.router_node(state)
    assert result["router_decision"]["next_node"] == "abort"
    print(f"  [PASS] 规则优先→abort")


def test_router_rule_push_sent_update_memory():
    """规则优先：推送完成 → update_memory。"""
    print("\n[test] router - 规则优先：推送完成→update_memory")
    state = _mock_state({
        "push_status": "sent",
    })
    result = ma.router_node(state)
    assert result["router_decision"]["next_node"] == "update_memory"
    print(f"  [PASS] 规则优先→update_memory")


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
        # _rule_based_router_decision（P0-2.4 规则优先路由）
        ("规则-plan未执行→invoke", test_rule_plan_not_executed),
        ("规则-已执行未观察→observe", test_rule_executed_no_observe),
        ("规则-needs_retry未达上限→None", test_rule_needs_retry_under_limit),
        ("规则-needs_retry达上限+空→abort", test_rule_needs_retry_at_limit_abort),
        ("规则-needs_retry达上限+有数据→收敛", test_rule_needs_retry_at_limit_converge),
        ("规则-无需重试→coordinator", test_rule_no_retry_coordinator),
        ("规则-审查通过→push", test_rule_coordinator_pass_push),
        ("规则-审查不通过未达上限→None", test_rule_coordinator_fail_under_limit),
        ("规则-审查不通过达上限→强制推送", test_rule_coordinator_fail_at_limit),
        ("规则-推送完成→update_memory", test_rule_push_sent_update_memory),
        ("规则-兜底→update_memory", test_rule_fallback_update_memory),
        # router_node 安全机制
        ("死循环检测", test_router_loop_detection),
        ("超过最大轮数", test_router_max_turns),
        # router_node 规则优先路由
        ("router-规则优先→invoke_sub_agent", test_router_rule_plan_not_executed),
        ("router-规则优先→planner", test_router_rule_needs_retry_to_planner),
        ("router-规则优先→push_notification", test_router_rule_coordinator_pass_push),
        ("router-规则优先→abort", test_router_rule_abort_on_limit),
        ("router-规则优先→update_memory", test_router_rule_push_sent_update_memory),
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
