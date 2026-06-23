"""
Collection Agent Pipeline 模式测试脚本 — P2-2.5 验证。

验证 run_collection_pipeline() 固定流水线行为：
  - fetch_rss → normalize_items → 返回结果，0 次 LLM 调用
  - RSS 不足阈值 → 自动触发 search_web
  - 全部失败 → 返回空列表不崩溃
  - ReAct 模式兼容 → 行为与修改前一致
  - build_collection_agent 兼容 → .invoke() 签名不变
  - 返回值字段完整 → collected_items / search_supplemented / collection_summary
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest.mock
import agents.collection_agent as ca


def _mock_state(overrides: dict = None):
    base = {
        "session_id": "test-session-pipeline",
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


# ============================================================
# 测试用例
# ============================================================


def test_pipeline_fetch_rss_normalize():
    """Pipeline 模式 + RSS 正常 → 顺序执行 fetch_rss → normalize_items → 返回结果。"""
    print("\n[test] pipeline - RSS 正常采集 → normalize → 返回")

    state = _mock_state()

    with unittest.mock.patch.object(ca, "_get_rss_sources", return_value=["https://example.com/rss"]):
        with unittest.mock.patch.object(ca, "_get_search_query", return_value="AI Agent"):
            with unittest.mock.patch.object(ca, "load_config") as mock_config:
                mock_config.return_value = {"agents": {"collection_search_threshold": 5}}
                with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
                    mock_registry.dispatch.side_effect = [
                        # fetch_rss: 返回 10 条
                        {"items": [{"title": f"RSS条目{i}", "source_url": "rss"} for i in range(10)], "count": 10, "valid_count": 10},
                        # normalize_items: 标准化后返回
                        {"items": [{"title": f"标准化条目{i}", "source_url": "rss", "id": f"id_{i}"} for i in range(10)], "count": 10},
                    ]

                    result = ca.run_collection_pipeline(state)

    assert "collected_items" in result, f"缺少 collected_items: {result.keys()}"
    assert len(result["collected_items"]) == 10, f"期望 10 条，实际 {len(result['collected_items'])}"
    assert result["search_supplemented"] is False, "不应触发 search_web（RSS 足够）"
    assert "仅 RSS" in result["collection_summary"], f"summary 应标注仅 RSS: {result['collection_summary']}"
    assert mock_registry.dispatch.call_count == 2, f"应调用 2 次工具（fetch_rss + normalize），实际 {mock_registry.dispatch.call_count}"

    print(f"  [PASS] Pipeline RSS 正常: {len(result['collected_items'])} 条, search_supplemented={result['search_supplemented']}")


def test_pipeline_rss_insufficient_triggers_search():
    """Pipeline 模式 + RSS 不足阈值 → 自动触发 search_web。"""
    print("\n[test] pipeline - RSS 不足 → 自动 search_web 补充")

    state = _mock_state()

    with unittest.mock.patch.object(ca, "_get_rss_sources", return_value=["https://example.com/rss"]):
        with unittest.mock.patch.object(ca, "_get_search_query", return_value="AI Agent"):
            with unittest.mock.patch.object(ca, "load_config") as mock_config:
                mock_config.return_value = {"agents": {"collection_search_threshold": 5}}
                with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
                    mock_registry.dispatch.side_effect = [
                        # fetch_rss: 仅 2 条
                        {"items": [{"title": f"RSS条目{i}", "source_url": "rss"} for i in range(2)], "count": 2, "valid_count": 2},
                        # search_web: 补充 4 条
                        {"items": [{"title": f"搜索条目{i}", "source_url": "web_search"} for i in range(4)], "count": 4},
                        # normalize_items
                        {"items": [{"title": f"标准化条目{i}", "id": f"id_{i}"} for i in range(6)], "count": 6},
                    ]

                    result = ca.run_collection_pipeline(state)

    assert len(result["collected_items"]) == 6, f"期望 6 条（2 RSS + 4 搜索），实际 {len(result['collected_items'])}"
    assert result["search_supplemented"] is True, "应标记 search_supplemented=True"
    assert "搜索补充" in result["collection_summary"], f"summary 应标注搜索补充: {result['collection_summary']}"
    assert mock_registry.dispatch.call_count == 3, f"应调用 3 次工具（fetch_rss + search_web + normalize），实际 {mock_registry.dispatch.call_count}"

    print(f"  [PASS] Pipeline RSS 不足触发搜索: {len(result['collected_items'])} 条, search_supplemented={result['search_supplemented']}")


def test_pipeline_all_fail_graceful():
    """Pipeline 模式 + RSS=0 + search_web=0 → 返回空 collected_items，不崩溃。"""
    print("\n[test] pipeline - RSS 全部失败 → 优雅降级")

    state = _mock_state()

    with unittest.mock.patch.object(ca, "_get_rss_sources", return_value=["https://example.com/rss"]):
        with unittest.mock.patch.object(ca, "_get_search_query", return_value="AI Agent"):
            with unittest.mock.patch.object(ca, "load_config") as mock_config:
                mock_config.return_value = {"agents": {"collection_search_threshold": 5}}
                with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
                    mock_registry.dispatch.side_effect = [
                        # fetch_rss: 空列表
                        {"items": [], "count": 0, "valid_count": 0},
                        # search_web: 空列表
                        {"items": [], "count": 0},
                    ]

                    result = ca.run_collection_pipeline(state)

    assert result["collected_items"] == [], f"期望空列表，实际 {len(result['collected_items'])} 条"
    assert result["search_supplemented"] is False, "搜索无结果时不标记 supplement（已尝试但无补充）"
    assert "共 0 条" in result["collection_summary"], f"summary 应标注 0 条: {result['collection_summary']}"
    # normalize_items 不会被调用（collected_items 为空）
    normalize_calls = [c for c in mock_registry.dispatch.call_args_list if c[0][0] == "normalize_items"]
    assert len(normalize_calls) == 0, "空列表应跳过 normalize_items"

    print(f"  [PASS] Pipeline 全部失败降级: collected={len(result['collected_items'])}")


def test_pipeline_fetch_rss_exception():
    """Pipeline 模式 + fetch_rss 抛异常 → 不崩溃，自动触发 search_web。"""
    print("\n[test] pipeline - fetch_rss 异常 → 自动 search_web")

    state = _mock_state()

    with unittest.mock.patch.object(ca, "_get_rss_sources", return_value=["https://example.com/rss"]):
        with unittest.mock.patch.object(ca, "_get_search_query", return_value="AI Agent"):
            with unittest.mock.patch.object(ca, "load_config") as mock_config:
                mock_config.return_value = {"agents": {"collection_search_threshold": 5}}
                with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
                    mock_registry.dispatch.side_effect = [
                        # fetch_rss: 抛异常
                        Exception("RSS 网络不可达"),
                        # search_web: 返回 3 条
                        {"items": [{"title": f"搜索条目{i}", "source_url": "web_search"} for i in range(3)], "count": 3},
                        # normalize_items
                        {"items": [{"title": f"标准化条目{i}", "id": f"id_{i}"} for i in range(3)], "count": 3},
                    ]

                    result = ca.run_collection_pipeline(state)

    assert len(result["collected_items"]) == 3, f"期望 3 条（仅搜索），实际 {len(result['collected_items'])}"
    assert result["search_supplemented"] is True
    print(f"  [PASS] Pipeline fetch_rss 异常降级: {len(result['collected_items'])} 条")


def test_build_collection_agent_pipeline():
    """验证 build_collection_agent() 在 pipeline 模式下返回正确的 wrapper。"""
    print("\n[test] pipeline - build_collection_agent 模式切换")

    with unittest.mock.patch.object(ca, "load_config") as mock_config:
        mock_config.return_value = {"agents": {"collection_mode": "pipeline"}}

        agent = ca.build_collection_agent()
        assert agent is not None, "build_collection_agent() 返回 None"
        assert hasattr(agent, "invoke"), "缺少 invoke 方法"
        # 验证 wrapper 内部指向 pipeline 函数
        assert agent._fn == ca.run_collection_pipeline, f"pipeline 模式应指向 run_collection_pipeline，实际: {agent._fn.__name__}"

    print("  [PASS] build_collection_agent pipeline 模式正确")


def test_build_collection_agent_react():
    """验证 build_collection_agent() 在 react 模式下返回正确的 wrapper。"""
    print("\n[test] pipeline - build_collection_agent react 兼容模式")

    with unittest.mock.patch.object(ca, "load_config") as mock_config:
        mock_config.return_value = {"agents": {"collection_mode": "react"}}

        agent = ca.build_collection_agent()
        assert agent is not None
        assert hasattr(agent, "invoke")
        assert agent._fn == ca.run_collection_agent, f"react 模式应指向 run_collection_agent，实际: {agent._fn.__name__}"

    print("  [PASS] build_collection_agent react 兼容模式正确")


def test_build_collection_agent_default():
    """验证旧版 config（无 collection_mode 字段）→ 默认 pipeline。"""
    print("\n[test] pipeline - 旧版 config 默认 pipeline")

    with unittest.mock.patch.object(ca, "load_config") as mock_config:
        mock_config.return_value = {"agents": {}}  # 无 collection_mode

        agent = ca.build_collection_agent()
        assert agent._fn == ca.run_collection_pipeline, "旧版 config 应默认 pipeline"

    print("  [PASS] 旧版 config 默认 pipeline")


def test_pipeline_return_signature():
    """验证 Pipeline 返回值字段完整性（与 ReAct 签名一致）。"""
    print("\n[test] pipeline - 返回值字段完整性")

    state = _mock_state()

    with unittest.mock.patch.object(ca, "_get_rss_sources", return_value=["https://example.com/rss"]):
        with unittest.mock.patch.object(ca, "_get_search_query", return_value="AI Agent"):
            with unittest.mock.patch.object(ca, "load_config") as mock_config:
                mock_config.return_value = {"agents": {"collection_search_threshold": 5}}
                with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
                    mock_registry.dispatch.side_effect = [
                        {"items": [{"title": "test", "source_url": "rss"}], "count": 1, "valid_count": 1},
                        {"items": [{"title": "normalized", "id": "n_1"}], "count": 1},
                    ]

                    result = ca.run_collection_pipeline(state)

    required_fields = ["collected_items", "search_supplemented", "collection_summary"]
    for field in required_fields:
        assert field in result, f"缺少字段: {field}"

    assert isinstance(result["collected_items"], list), "collected_items 应为 list"
    assert isinstance(result["search_supplemented"], bool), "search_supplemented 应为 bool"
    assert isinstance(result["collection_summary"], str), "collection_summary 应为 str"
    assert len(result["collection_summary"]) > 0, "collection_summary 不应为空"

    print(f"  [PASS] 返回值字段完整: {list(result.keys())}")


def test_pipeline_no_llm_call():
    """验证 Pipeline 模式下确实没有调用 LLM（核心：0 次 API 调用）。"""
    print("\n[test] pipeline - 无 LLM 调用验证")

    state = _mock_state()

    with unittest.mock.patch.object(ca, "_get_rss_sources", return_value=["https://example.com/rss"]):
        with unittest.mock.patch.object(ca, "_get_search_query", return_value="AI Agent"):
            with unittest.mock.patch.object(ca, "load_config") as mock_config:
                mock_config.return_value = {"agents": {"collection_search_threshold": 5}}
                with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
                    mock_registry.dispatch.side_effect = [
                        {"items": [{"title": f"RSS{i}", "source_url": "rss"} for i in range(8)], "count": 8, "valid_count": 8},
                        {"items": [{"title": f"标准化{i}", "id": f"id_{i}"} for i in range(8)], "count": 8},
                    ]

                    # Patch _get_llm_provider 确保不会被调用
                    with unittest.mock.patch.object(ca, "_get_llm_provider") as mock_llm:
                        result = ca.run_collection_pipeline(state)
                        mock_llm.assert_not_called()

    assert len(result["collected_items"]) == 8
    print("  [PASS] Pipeline 无 LLM 调用: 0 次 API")


def test_pipeline_search_threshold_configurable():
    """验证 collection_search_threshold 可配置（阈值=10，RSS 有 7 条 → 触发搜索）。"""
    print("\n[test] pipeline - search_threshold 可配置")

    state = _mock_state()

    with unittest.mock.patch.object(ca, "_get_rss_sources", return_value=["https://example.com/rss"]):
        with unittest.mock.patch.object(ca, "_get_search_query", return_value="AI Agent"):
            with unittest.mock.patch.object(ca, "load_config") as mock_config:
                mock_config.return_value = {"agents": {"collection_search_threshold": 10}}
                with unittest.mock.patch("agents.collection_agent.tool_registry") as mock_registry:
                    mock_registry.dispatch.side_effect = [
                        {"items": [{"title": f"RSS{i}", "source_url": "rss"} for i in range(7)], "count": 7, "valid_count": 7},
                        {"items": [{"title": f"搜索{i}", "source_url": "web_search"} for i in range(3)], "count": 3},
                        {"items": [{"title": f"标准化{i}", "id": f"id_{i}"} for i in range(10)], "count": 10},
                    ]

                    result = ca.run_collection_pipeline(state)

    assert len(result["collected_items"]) == 10, f"期望 10 条，实际 {len(result['collected_items'])}"
    assert result["search_supplemented"] is True, "阈值=10 且 RSS=7 应触发搜索"

    print(f"  [PASS] search_threshold 可配置: RSS=7, threshold=10, 触发搜索, 最终 {len(result['collected_items'])} 条")


# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
    tests = [
        ("Pipeline RSS 正常采集", test_pipeline_fetch_rss_normalize),
        ("Pipeline RSS 不足触发搜索", test_pipeline_rss_insufficient_triggers_search),
        ("Pipeline 全部失败降级", test_pipeline_all_fail_graceful),
        ("Pipeline fetch_rss 异常降级", test_pipeline_fetch_rss_exception),
        ("build_collection_agent pipeline 模式", test_build_collection_agent_pipeline),
        ("build_collection_agent react 兼容", test_build_collection_agent_react),
        ("build_collection_agent 默认 pipeline", test_build_collection_agent_default),
        ("Pipeline 返回值字段完整性", test_pipeline_return_signature),
        ("Pipeline 无 LLM 调用验证", test_pipeline_no_llm_call),
        ("Pipeline search_threshold 可配置", test_pipeline_search_threshold_configurable),
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
