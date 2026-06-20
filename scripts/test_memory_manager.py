"""
记忆管理模块测试脚本
"""

import sys
import os
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from utils.memory_manager import (
    ShortTermMemory,
    LongTermMemory,
    EpisodicMemory,
    MemoryManager,
    SHORT_TERM_WINDOW_SIZE,
    get_memory_manager,
    add_memory,
    get_context,
)


def test_short_term_memory():
    print("\n[test] ShortTermMemory - 滑动窗口")
    stm = ShortTermMemory(window_size=5)

    # 添加记忆
    for i in range(7):
        stm.add({"event": f"test_event_{i}", "node_name": "test_node"})

    # 窗口大小应为 5
    assert stm.size() == 5, f"期望 5，实际 {stm.size()}"

    # 最早的两条应该被丢弃
    all_entries = stm.get_all()
    assert all_entries[0]["event"] == "test_event_2", f"期望 test_event_2，实际 {all_entries[0]['event']}"
    assert all_entries[-1]["event"] == "test_event_6"

    # 检查溢出
    assert stm.is_overflow() == True

    # 清空
    stm.clear()
    assert stm.size() == 0

    print("  [PASS] 滑动窗口正确工作")


def test_short_term_get_recent():
    print("\n[test] ShortTermMemory - get_recent")
    stm = ShortTermMemory(window_size=10)

    for i in range(10):
        stm.add({"event": f"event_{i}"})

    recent = stm.get_recent(3)
    assert len(recent) == 3
    assert recent[0]["event"] == "event_7"
    assert recent[1]["event"] == "event_8"
    assert recent[2]["event"] == "event_9"

    print("  [PASS] get_recent 返回最近 3 条")


def test_episodic_memory():
    print("\n[test] EpisodicMemory - SQLite 写入")
    with unittest.mock.patch("utils.memory_manager.Database") as MockDB:
        mock_conn = unittest.mock.MagicMock()
        mock_cursor = unittest.mock.MagicMock()
        mock_cursor.lastrowid = 123
        mock_conn.execute.return_value = mock_cursor

        mock_db = unittest.mock.MagicMock()
        mock_db.get_connection.return_value.__enter__ = unittest.mock.MagicMock(return_value=mock_conn)
        mock_db.get_connection.return_value.__exit__ = unittest.mock.MagicMock(return_value=None)
        MockDB.return_value = mock_db

        em = EpisodicMemory("test.db")
        log_id = em.write(
            session_id="test_session",
            turn=1,
            event="test_event",
            node_name="test_node",
            status="completed",
            duration_ms=100,
            metadata={"key": "value"},
        )

    assert log_id == 123
    print("  [PASS] 情节记忆写入成功")


def test_long_term_memory():
    print("\n[test] LongTermMemory - ChromaDB 写入")
    with unittest.mock.patch("utils.memory_manager.VectorStore") as MockVS:
        mock_collection = unittest.mock.MagicMock()
        mock_vs = unittest.mock.MagicMock()
        mock_vs.client.get_or_create_collection.return_value = mock_collection
        MockVS.return_value = mock_vs

        ltm = LongTermMemory("test_chroma")
        doc_id = ltm.add_compressed("测试压缩记忆", metadata={"source": "test"})

    assert doc_id.startswith("memory_")
    print(f"  [PASS] 长期记忆写入成功: {doc_id}")


def test_long_term_search():
    print("\n[test] LongTermMemory - 检索")
    with unittest.mock.patch("utils.memory_manager.VectorStore") as MockVS:
        mock_collection = unittest.mock.MagicMock()
        mock_collection.query.return_value = {
            "ids": [["memory_001", "memory_002"]],
            "documents": [["记忆1", "记忆2"]],
            "metadatas": [[{"type": "compressed_memory"}, {"type": "compressed_memory"}]],
            "distances": [[0.1, 0.2]],
        }
        mock_vs = unittest.mock.MagicMock()
        mock_vs.client.get_or_create_collection.return_value = mock_collection
        MockVS.return_value = mock_vs

        ltm = LongTermMemory("test_chroma")
        results = ltm.search("测试查询", n_results=2)

    assert len(results) == 2
    assert results[0]["id"] == "memory_001"
    print("  [PASS] 长期记忆检索成功")


def test_memory_manager_add():
    print("\n[test] MemoryManager - add_memory")
    with unittest.mock.patch("utils.memory_manager.ShortTermMemory") as MockSTM:
        with unittest.mock.patch("utils.memory_manager.EpisodicMemory") as MockEM:
            with unittest.mock.patch("utils.memory_manager.LongTermMemory") as MockLTM:
                mock_stm = unittest.mock.MagicMock()
                mock_stm.size.return_value = 1
                mock_stm.is_overflow.return_value = False
                MockSTM.return_value = mock_stm

                mock_em = unittest.mock.MagicMock()
                mock_em.write.return_value = 100
                MockEM.return_value = mock_em

                mock_ltm = unittest.mock.MagicMock()
                MockLTM.return_value = mock_ltm

                mm = MemoryManager()
                result = mm.add_memory(
                    session_id="test_session",
                    event="test_event",
                    node_name="test_node",
                    content={"key": "value"},
                )

    assert result["turn"] == 2  # size + 1
    assert result["log_id"] == 100
    print("  [PASS] MemoryManager.add_memory 成功")


def test_memory_manager_compress():
    print("\n[test] MemoryManager - compress_window")
    mock_stm = unittest.mock.MagicMock()
    mock_stm.get_all.return_value = [
        {"turn": 1, "node_name": "node1", "content": {"a": 1}},
        {"turn": 2, "node_name": "node2", "content": {"b": 2}},
    ]
    mock_stm.is_overflow.return_value = True

    mock_ltm = unittest.mock.MagicMock()
    mock_ltm.add_compressed.return_value = "memory_compressed"

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.return_value = {"content": "压缩后的摘要"}

    with unittest.mock.patch("utils.llm_provider.DeepSeekProvider", return_value=mock_llm):
        with unittest.mock.patch("utils.memory_manager._load_config", return_value={}):
            mm = MemoryManager()
            mm.short_term = mock_stm
            mm.long_term = mock_ltm
            result = mm.compress_window()

    assert result["success"] == True
    assert result["doc_id"] == "memory_compressed"
    print("  [PASS] 压缩成功")


def test_memory_manager_compress_fallback():
    print("\n[test] MemoryManager - compress_window (降级)")
    mock_stm = unittest.mock.MagicMock()
    mock_stm.get_all.return_value = [{"turn": 1, "node_name": "node1", "content": {}}]
    mock_stm.is_overflow.return_value = True

    mock_ltm = unittest.mock.MagicMock()
    mock_ltm.add_compressed.return_value = "memory_fallback"

    with unittest.mock.patch("utils.llm_provider.DeepSeekProvider") as MockLLM:
        MockLLM.side_effect = Exception("LLM 不可用")

        with unittest.mock.patch("utils.memory_manager._load_config", return_value={}):
            mm = MemoryManager()
            mm.short_term = mock_stm
            mm.long_term = mock_ltm
            result = mm.compress_window()

    assert result["success"] == True
    print("  [PASS] LLM 不可用时降级成功")


def test_get_context():
    print("\n[test] MemoryManager - get_context")
    with unittest.mock.patch("utils.memory_manager.ShortTermMemory") as MockSTM:
        with unittest.mock.patch("utils.memory_manager.LongTermMemory") as MockLTM:
            mock_stm = unittest.mock.MagicMock()
            mock_stm.get_recent.return_value = [{"event": "recent"}]
            mock_stm.size.return_value = 5
            MockSTM.return_value = mock_stm

            mock_ltm = unittest.mock.MagicMock()
            mock_ltm.search.return_value = [{"id": "ltm_1"}]
            MockLTM.return_value = mock_ltm

            mm = MemoryManager()
            ctx = mm.get_context("测试查询")

    assert len(ctx["short_term"]) == 1
    assert len(ctx["long_term"]) == 1
    assert ctx["short_term_size"] == 5
    print("  [PASS] get_context 返回短期+长期记忆")


def test_global_singleton():
    print("\n[test] 全局单例")
    mm1 = get_memory_manager()
    mm2 = get_memory_manager()
    assert mm1 is mm2
    print("  [PASS] 全局单例正确")


def test_convenience_functions():
    print("\n[test] 便捷函数")
    with unittest.mock.patch("utils.memory_manager.get_memory_manager") as MockGetMM:
        mock_mm = unittest.mock.MagicMock()
        mock_mm.add_memory.return_value = {"turn": 1}
        mock_mm.get_context.return_value = {"short_term": []}
        MockGetMM.return_value = mock_mm

        result1 = add_memory("s1", "e1", "n1", {})
        result2 = get_context("query")

    assert result1["turn"] == 1
    assert result2["short_term"] == []
    print("  [PASS] 便捷函数正确调用")


def test_window_size_constant():
    print("\n[test] 常量配置")
    assert SHORT_TERM_WINDOW_SIZE == 15
    print(f"  [PASS] SHORT_TERM_WINDOW_SIZE = {SHORT_TERM_WINDOW_SIZE}")


if __name__ == "__main__":
    print("=" * 50)
    print("记忆管理模块测试")
    print("=" * 50)

    tests = [
        test_short_term_memory,
        test_short_term_get_recent,
        test_episodic_memory,
        test_long_term_memory,
        test_long_term_search,
        test_memory_manager_add,
        test_memory_manager_compress,
        test_memory_manager_compress_fallback,
        test_get_context,
        test_global_singleton,
        test_convenience_functions,
        test_window_size_constant,
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
