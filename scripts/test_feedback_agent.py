"""
反馈 Agent 测试脚本
"""

import sys
import os
import unittest.mock
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import agents.feedback_agent as fa


def test_compute_preference_weight():
    print("\n[test] _compute_preference_weight")
    # like 第一次
    w1 = fa._compute_preference_weight("like", 1)
    assert 0.15 <= w1 < 0.35, f"like(1): {w1}"

    # like 多次
    w2 = fa._compute_preference_weight("like", 5)
    assert 0.8 <= w2 <= 1.0, f"like(5): {w2}"

    # dislike 第一次
    w3 = fa._compute_preference_weight("dislike", 1)
    assert -0.35 < w3 <= -0.10, f"dislike(1): {w3}"

    # irrelevant 第一次
    w4 = fa._compute_preference_weight("irrelevant", 1)
    assert -0.35 < w4 <= -0.15, f"irrelevant(1): {w4}"

    print(f"  [PASS] like(1)={w1:.3f}, like(5)={w2:.3f}, dislike(1)={w3:.3f}, irrelevant(1)={w4:.3f}")


def test_record_feedback():
    print("\n[test] record_feedback_node")
    with unittest.mock.patch("agents.feedback_agent._get_db") as MockDB:
        mock_conn = unittest.mock.MagicMock()
        mock_db = unittest.mock.MagicMock()
        mock_db.get_connection.return_value.__enter__ = unittest.mock.MagicMock(return_value=mock_conn)
        mock_db.get_connection.return_value.__exit__ = unittest.mock.MagicMock(return_value=None)
        MockDB.return_value = mock_db

        state = {"user_id": 1, "item_id": 100, "feedback_type": "like"}
        result = fa.record_feedback_node(state)

    assert result["feedback_recorded"] == True
    mock_conn.execute.assert_called_once()
    call_args = mock_conn.execute.call_args
    assert call_args[0][0].startswith("INSERT INTO feedback")
    print("  [PASS] 反馈记录写入成功")


def test_update_preference():
    print("\n[test] update_preference_node")
    mock_conn = unittest.mock.MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = {
        "title": "新能源车新闻",
        "summary": "关于新能源车的报道",
        "keywords": '["新能源车", "电池"]',
        "category": "科技",
    }

    mock_db = unittest.mock.MagicMock()
    mock_db.get_connection.return_value.__enter__ = unittest.mock.MagicMock(return_value=mock_conn)
    mock_db.get_connection.return_value.__exit__ = unittest.mock.MagicMock(return_value=None)

    mock_vs = unittest.mock.MagicMock()
    mock_vs.chroma_embedding_fn = unittest.mock.MagicMock(return_value=[[0.1] * 384])
    mock_vs.client.get_or_create_collection.return_value.query.return_value = {
        "ids": [[]],
        "embeddings": [],
    }

    with unittest.mock.patch("agents.feedback_agent._get_db", return_value=mock_db):
        with unittest.mock.patch("agents.feedback_agent._get_vector_store", return_value=mock_vs):
            state = {"user_id": 1, "item_id": 100, "feedback_type": "like"}
            result = fa.update_preference_node(state)

    assert result["preference_updated"] == True
    assert "v_like" in result
    assert "v_dislike" in result
    assert "keywords" in result
    assert "新能源车" in result["keywords"]
    assert len(result["v_like"]) == 384
    print(f"  [PASS] EMA 更新完成: keywords={result['keywords']}")


def test_vector_add():
    print("\n[test] vector_add_node")
    with unittest.mock.patch("agents.feedback_agent._get_vector_store") as MockVS:
        mock_collection = unittest.mock.MagicMock()
        mock_vs = unittest.mock.MagicMock()
        mock_vs.client.get_or_create_collection.return_value = mock_collection
        MockVS.return_value = mock_vs

        state = {
            "user_id": 1,
            "v_like": [0.1] * 384,
            "v_dislike": [-0.1] * 384,
        }
        result = fa.vector_add_node(state)

    assert result["vector_added"] == True
    assert mock_collection.upsert.call_count == 2
    print("  [PASS] 偏好向量写入 ChromaDB")


def test_cleanup_preference():
    print("\n[test] cleanup_preference_node")
    with unittest.mock.patch("agents.feedback_agent._get_db") as MockDB:
        mock_conn = unittest.mock.MagicMock()
        mock_db = unittest.mock.MagicMock()
        mock_db.get_connection.return_value.__enter__ = unittest.mock.MagicMock(return_value=mock_conn)
        mock_db.get_connection.return_value.__exit__ = unittest.mock.MagicMock(return_value=None)
        # 返回2条低权重记录
        mock_conn.execute.return_value.fetchall.return_value = [
            {"id": 1, "keyword": "测试", "weight": 0.05},
            {"id": 2, "keyword": "旧词", "weight": -0.08},
        ]
        MockDB.return_value = mock_db

        state = {"user_id": 1}
        result = fa.cleanup_preference_node(state)

    assert result["cleanup_done"] == True
    assert result["removed_count"] == 2
    # 验证 DELETE 被调用（每个低权重项一次 DELETE）
    delete_calls = [c for c in mock_conn.execute.call_args_list if "DELETE" in str(c.args[0])]
    assert len(delete_calls) == 2, f"期望 2 次 DELETE，实际 {len(delete_calls)} 次"
    print("  [PASS] 清理 2 个低权重偏好项（含 DELETE 验证）")


def test_stategraph_compiles():
    print("\n[test] StateGraph 编译")
    graph = fa.build_feedback_agent()
    assert graph is not None
    print("  [PASS] StateGraph 编译成功")


def test_async_process():
    print("\n[test] process_feedback_async")
    with unittest.mock.patch("agents.feedback_agent.build_feedback_agent") as MockBuild:
        mock_graph = unittest.mock.MagicMock()
        mock_graph.invoke.return_value = {"status": "completed"}
        MockBuild.return_value = mock_graph

        result = fa.process_feedback_async(user_id=1, item_id=100, feedback_type="like")

    assert result["status"] == "started"
    assert "thread_id" in result
    print("  [PASS] 异步处理已启动")


def test_ema_update():
    print("\n[test] EMA 更新算法验证")
    alpha = fa.EMA_ALPHA
    assert alpha == 0.3, f'EMA_ALPHA 应为 0.3（MVP 文档规定），实际: {alpha}'
    current = np.array([0.0] * 5)
    feedback = np.array([1.0] * 5)

    # 第一次更新
    new = alpha * current + (1 - alpha) * feedback
    expected = (1 - alpha) * np.ones(5)
    assert np.allclose(new, expected), f"EMA 第一次: {new}"

    # 第二次更新
    new2 = alpha * new + (1 - alpha) * feedback
    expected2 = alpha * expected + (1 - alpha) * np.ones(5)
    assert np.allclose(new2, expected2), f"EMA 第二次: {new2}"

    print(f"  [PASS] EMA 验证: alpha={alpha}, first={new[0]:.4f}, second={new2[0]:.4f}")


if __name__ == "__main__":
    print("=" * 50)
    print("反馈 Agent 单元测试")
    print("=" * 50)

    tests = [
        test_compute_preference_weight,
        test_record_feedback,
        test_update_preference,
        test_vector_add,
        test_cleanup_preference,
        test_stategraph_compiles,
        test_async_process,
        test_ema_update,
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
