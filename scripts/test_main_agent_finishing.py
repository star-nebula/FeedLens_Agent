"""
主 Agent 收尾节点测试脚本
"""

import sys
import os
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agents.main_agent as ma


def test_coordinator_reflect_pass():
    print("\n[test] coordinator_reflect_node - 审查通过")
    state = {
        "observation_result": {"brief_quality": 0.8},
        "ranking_result": {
            "ranked_items": [{"id": "1", "title": "test", "url": "http://x.com"}],
            "item_relations": [],
        },
        "briefing_result": {
            "briefing": {
                "title": "简报",
                "summary": "摘要",
                "categories": [
                    {
                        "name": "科技",
                        "items": [
                            {"id": "1", "title": "test", "published_at": "2024-01-01T00:00:00"}
                        ],
                    }
                ],
            }
        },
        "react_cycle_count": 1,
    }
    result = ma.coordinator_reflect_node(state)
    obs = result["coordinator_observation"]
    assert obs["overall_pass"] == True, f"期望通过，实际: {obs}"
    assert len(obs["issues"]) == 0
    assert len(obs["contradictions"]) == 0
    assert result["briefing"]["title"] == "简报"
    print(f"  [PASS] 审查通过: completeness={obs['completeness']}, brief_quality={obs['brief_quality']}")


def test_coordinator_reflect_issues():
    print("\n[test] coordinator_reflect_node - 发现问题")
    state = {
        "observation_result": {"brief_quality": 0.3},
        "ranking_result": {"ranked_items": [], "item_relations": []},
        "briefing_result": {},
        "react_cycle_count": 3,
    }
    result = ma.coordinator_reflect_node(state)
    obs = result["coordinator_observation"]
    assert obs["overall_pass"] == False
    assert len(obs["issues"]) > 0
    assert obs["react_cycles"] == 3
    print(f"  [PASS] 发现问题: {obs['issues']}")


def test_coordinator_reflect_contradictions():
    print("\n[test] coordinator_reflect_node - 矛盾检测")
    state = {
        "observation_result": {"brief_quality": 0.8},
        "ranking_result": {
            "ranked_items": [
                {"id": "1", "title": "A", "url": "http://a.com"},
                {"id": "2", "title": "B", "url": "http://b.com"},
            ],
            "item_relations": [],
        },
        "briefing_result": {
            "briefing": {
                "title": "简报",
                "summary": "摘要",
                "categories": [
                    {
                        "name": "科技",
                        "items": [
                            {"id": "1", "title": "A", "published_at": "2024-01-01T00:00:00", "importance": 5},
                            {"id": "2", "title": "B", "published_at": "2024-01-15T00:00:00", "importance": 1},
                        ],
                    }
                ],
            }
        },
        "react_cycle_count": 1,
    }
    result = ma.coordinator_reflect_node(state)
    obs = result["coordinator_observation"]
    # 时间差超过7天，应检测到矛盾
    assert len(obs["contradictions"]) > 0, f"期望检测到矛盾，实际: {obs['contradictions']}"
    print(f"  [PASS] 检测到 {len(obs['contradictions'])} 个矛盾")


def test_should_push_now():
    print("\n[test] should_push_now")
    assert ma.should_push_now({"push_immediate": True}) == "push_notification"
    assert ma.should_push_now({"push_immediate": False}) == "push_notification"
    print("  [PASS] 重大事件和日常简报都返回 push_notification")


def test_push_notification_with_briefing():
    print("\n[test] push_notification_node - 有简报")
    state = {
        "briefing": {
            "title": "简报",
            "summary": "摘要",
            "categories": [{"name": "科技", "items": [{"id": "1", "title": "test"}]}],
            "_markdown": "# 简报\n> 摘要",
        },
        "user_id": 1,
        "push_immediate": False,
    }
    with unittest.mock.patch("agents.main_agent.PushMCPClient") as MockClient:
        mock_client = unittest.mock.MagicMock()
        mock_client.__enter__ = unittest.mock.MagicMock(return_value=mock_client)
        mock_client.__exit__ = unittest.mock.MagicMock(return_value=None)
        mock_client.push.return_value = True
        MockClient.return_value = mock_client

        result = ma.push_notification_node(state)

    assert result["push_status"] == "sent"
    call_args = mock_client.push.call_args
    brief = call_args[1]["brief"]
    assert "categories" in brief
    assert "markdown" in brief
    assert brief["markdown"] == "# 简报\n> 摘要"
    print(f"  [PASS] 推送成功，包含 categories 和 markdown")


def test_push_notification_fallback():
    print("\n[test] push_notification_node - 降级推送")
    state = {
        "briefing": {},
        "ranked_items": [
            {"title": "Test1", "url": "http://x.com", "importance": 0.8},
            {"title": "Test2", "url": "http://y.com", "importance": 0.6},
        ],
        "user_id": 1,
        "push_immediate": False,
    }
    with unittest.mock.patch("agents.main_agent.PushMCPClient") as MockClient:
        mock_client = unittest.mock.MagicMock()
        mock_client.__enter__ = unittest.mock.MagicMock(return_value=mock_client)
        mock_client.__exit__ = unittest.mock.MagicMock(return_value=None)
        mock_client.push.return_value = False
        MockClient.return_value = mock_client

        result = ma.push_notification_node(state)

    assert result["push_status"] == "failed"
    call_args = mock_client.push.call_args
    brief = call_args[1]["brief"]
    assert "items" in brief
    print(f"  [PASS] 降级推送: {result['push_message']}")


def test_update_memory():
    print("\n[test] update_memory_node - 写入日志")
    state = {
        "user_id": 1,
        "session_id": "test_session",
        "ranked_items": [{"id": "1", "title": "Test", "summary": "Summary"}],
        "briefing": {"title": "简报"},
        "coordinator_observation": {"completeness": 0.9, "issues": []},
        "planner_reason": "测试",
        "react_cycle_count": 1,
        "trigger_type": "daily_briefing",
        "collected_items": [{"id": "1"}],
        "push_status": "sent",
    }
    with unittest.mock.patch("agents.main_agent.db_write") as mock_db:
        with unittest.mock.patch("agents.main_agent.VectorStore") as MockVS:
            with unittest.mock.patch("agents.main_agent.EmbeddingModel") as MockEmb:
                mock_emb = unittest.mock.MagicMock()
                mock_emb.encode_single.return_value = [0.1] * 384
                MockEmb.return_value = mock_emb
                result = ma.update_memory_node(state)

    assert result["status"] == "completed"
    assert "execution_log" in result
    log = result["execution_log"]
    assert log["user_id"] == 1
    assert log["collected_count"] == 1
    assert log["ranked_count"] == 1
    print(f"  [PASS] 记忆更新完成: collected={log['collected_count']}, ranked={log['ranked_count']}")


def test_stategraph_compiles():
    print("\n[test] StateGraph 编译")
    graph = ma.build_main_agent()
    assert graph is not None
    print("  [PASS] StateGraph 编译成功")


if __name__ == "__main__":
    print("=" * 50)
    print("主 Agent 收尾节点测试")
    print("=" * 50)

    tests = [
        test_coordinator_reflect_pass,
        test_coordinator_reflect_issues,
        test_coordinator_reflect_contradictions,
        test_should_push_now,
        test_push_notification_with_briefing,
        test_push_notification_fallback,
        test_update_memory,
        test_stategraph_compiles,
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
    print("=" * 50)
    print(f"测试结果: {passed}/{passed + failed} 通过")
    if failed > 0:
        print(f"失败: {failed}")
    print("=" * 50)
    sys.exit(0 if failed == 0 else 1)
