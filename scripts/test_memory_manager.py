"""
记忆管理模块测试脚本（FeedLens 场景适配版）

架构变更：
  - 删除 ShortTermMemory（FeedLens 每次独立执行，不存在同进程多轮积累）
  - 情节记忆：SQLite execution_logs，增加 get_recent_days_logs() 近N天检索
  - 长期记忆：ChromaDB，每次执行后 LLM 摘要直接写入，不再等15轮压缩
  - get_context()：整合 SQLite 近N天 + ChromaDB 语义检索
"""

import sys
import os
import unittest.mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from utils.memory_manager import (
    EpisodicMemory,
    LongTermMemory,
    MemoryManager,
    EPISODIC_LOOKBACK_DAYS,
    get_memory_manager,
    add_memory,
    get_context,
    summarize_execution,
)


# ============================================================
# 情节记忆测试
# ============================================================

def test_episodic_write():
    """测试情节记忆写入（turn 固定为 1）。"""
    print("\n[test] EpisodicMemory - 写入")
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
            event="planner_decision",
            node_name="planner",
            status="completed",
            duration_ms=100,
            metadata={"situation": "采集10条", "outcome": "ok"},
        )

    assert log_id == 123
    print("  [PASS] 情节记忆写入成功 (turn=1)")


def test_episodic_get_recent_days():
    """测试近N天执行记录检索。"""
    print("\n[test] EpisodicMemory - 近N天检索")
    mock_row1 = {
        "id": 1, "session_id": "s1", "event": "planner_decision",
        "node_name": "planner", "status": "completed",
        "duration_ms": 100,
        "metadata": '{"situation":"采集10条","outcome":"ok"}',
        "created_at": "2026-06-22 10:00:00",
    }
    mock_row2 = {
        "id": 2, "session_id": "s2", "event": "planner_decision",
        "node_name": "planner", "status": "completed",
        "duration_ms": 200,
        "metadata": '{"situation":"采集3条","outcome":"retry_needed"}',
        "created_at": "2026-06-21 10:00:00",
    }

    with unittest.mock.patch("utils.memory_manager.Database") as MockDB:
        mock_conn = unittest.mock.MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [mock_row1, mock_row2]
        mock_db = unittest.mock.MagicMock()
        mock_db.get_connection.return_value.__enter__ = unittest.mock.MagicMock(return_value=mock_conn)
        mock_db.get_connection.return_value.__exit__ = unittest.mock.MagicMock(return_value=None)
        MockDB.return_value = mock_db

        em = EpisodicMemory("test.db")
        logs = em.get_recent_days_logs(days=7, limit=10)

    assert len(logs) == 2
    assert logs[0]["session_id"] == "s1"
    assert isinstance(logs[0]["metadata"], dict)  # JSON 已解析
    assert logs[0]["metadata"]["outcome"] == "ok"
    print("  [PASS] 近7天检索返回 2 条，metadata 已解析")


# ============================================================
# 长期记忆测试
# ============================================================

def test_long_term_summarize_and_store():
    """测试 LLM 摘要 + ChromaDB 写入。"""
    print("\n[test] LongTermMemory - summarize_and_store")
    mock_collection = unittest.mock.MagicMock()
    mock_vs = unittest.mock.MagicMock()
    mock_vs.client.get_or_create_collection.return_value = mock_collection

    mock_llm = unittest.mock.MagicMock()
    mock_llm.chat.return_value = {"content": "本次执行：采集10条，排序质量0.8，简报质量0.9"}

    with unittest.mock.patch("utils.memory_manager.VectorStore", return_value=mock_vs):
        with unittest.mock.patch("utils.llm_provider.DeepSeekProvider", return_value=mock_llm):
            with unittest.mock.patch("utils.memory_manager.load_config", return_value={
                "llm": {"deepseek": {"api_key": "mock_key", "model": "mock-model"}}
            }):
                ltm = LongTermMemory("test_chroma")
                doc_id = ltm.summarize_and_store(
                    session_id="test_session_001",
                    planner_decision={"sub_agent_plan": [{"agent": "Collection"}]},
                    execution_result={"collected_count": 10, "brief_quality": 0.9},
                    trigger_type="manual",
                )

    assert doc_id.startswith("memory_")
    print(f"  [PASS] 摘要写入成功: {doc_id}")


def test_long_term_summarize_fallback():
    """测试 LLM 不可用时的降级。"""
    print("\n[test] LongTermMemory - summarize_and_store (降级)")
    mock_collection = unittest.mock.MagicMock()
    mock_vs = unittest.mock.MagicMock()
    mock_vs.client.get_or_create_collection.return_value = mock_collection

    with unittest.mock.patch("utils.memory_manager.VectorStore", return_value=mock_vs):
        with unittest.mock.patch("utils.llm_provider.DeepSeekProvider") as MockLLM:
            MockLLM.side_effect = Exception("LLM 不可用")
            with unittest.mock.patch("utils.memory_manager.load_config", return_value={
                "llm": {"deepseek": {"api_key": "mock_key", "model": "mock-model"}}
            }):
                ltm = LongTermMemory("test_chroma")
                doc_id = ltm.summarize_and_store(
                    session_id="test_session_002",
                    planner_decision={"sub_agent_plan": []},
                    execution_result={"collected_count": 5, "ranked_count": 3, "brief_quality": 0.6},
                    trigger_type="daily_briefing",
                )

    assert doc_id.startswith("memory_")
    print("  [PASS] LLM 不可用时降级成功（结构化拼接）")


def test_long_term_search():
    """测试 ChromaDB 语义检索。"""
    print("\n[test] LongTermMemory - search")
    mock_collection = unittest.mock.MagicMock()
    mock_collection.query.return_value = {
        "ids": [["memory_001", "memory_002"]],
        "documents": [["采集10条简报质量0.9", "采集3条简报质量0.4"]],
        "metadatas": [[{"type": "execution_summary"}, {"type": "execution_summary"}]],
        "distances": [[0.1, 0.5]],
    }
    mock_vs = unittest.mock.MagicMock()
    mock_vs.client.get_or_create_collection.return_value = mock_collection

    with unittest.mock.patch("utils.memory_manager.VectorStore", return_value=mock_vs):
        ltm = LongTermMemory("test_chroma")
        results = ltm.search("采集 排序 简报质量", n_results=2)

    assert len(results) == 2
    assert results[0]["id"] == "memory_001"
    print("  [PASS] 语义检索返回 2 条")


# ============================================================
# 记忆管理器测试
# ============================================================

def test_memory_manager_add():
    """测试 add_memory：情节记忆 + 长期记忆同时写入。"""
    print("\n[test] MemoryManager - add_memory")
    with unittest.mock.patch("utils.memory_manager.EpisodicMemory") as MockEM:
        with unittest.mock.patch("utils.memory_manager.LongTermMemory") as MockLTM:
            mock_em = unittest.mock.MagicMock()
            mock_em.write.return_value = 100
            MockEM.return_value = mock_em

            mock_ltm = unittest.mock.MagicMock()
            mock_ltm.summarize_and_store.return_value = "memory_test_001"
            MockLTM.return_value = mock_ltm

            mm = MemoryManager()
            result = mm.add_memory(
                session_id="test_session",
                event="planner_decision",
                node_name="planner",
                content={"situation": "采集10条", "outcome": "ok"},
                execution_result={"collected_count": 10, "brief_quality": 0.9},
                planner_decision={"sub_agent_plan": [{"agent": "Collection"}]},
                trigger_type="manual",
            )

    assert result["log_id"] == 100
    assert result["chroma_doc_id"] == "memory_test_001"
    print("  [PASS] MemoryManager.add_memory 同时写入 SQLite + ChromaDB")


def test_get_context():
    """测试 get_context：情节记忆(近N天) + 长期记忆(语义)。"""
    print("\n[test] MemoryManager - get_context")
    with unittest.mock.patch("utils.memory_manager.EpisodicMemory") as MockEM:
        with unittest.mock.patch("utils.memory_manager.LongTermMemory") as MockLTM:
            mock_em = unittest.mock.MagicMock()
            mock_em.get_recent_days_logs.return_value = [
                {"session_id": "s1", "metadata": {"outcome": "ok"}},
                {"session_id": "s2", "metadata": {"outcome": "retry"}},
            ]
            MockEM.return_value = mock_em

            mock_ltm = unittest.mock.MagicMock()
            mock_ltm.search.return_value = [
                {"id": "ltm_1", "document": "历史经验1", "distance": 0.1},
            ]
            MockLTM.return_value = mock_ltm

            mm = MemoryManager()
            ctx = mm.get_context("测试查询", n_episodic=10, n_long_term=3, lookback_days=7)

    assert ctx["episodic_count"] == 2
    assert ctx["long_term_count"] == 1
    assert len(ctx["episodic"]) == 2
    assert len(ctx["long_term"]) == 1
    print("  [PASS] get_context 返回情节(近7天) + 长期(语义)")


# ============================================================
# 单例与便捷函数测试
# ============================================================

def test_global_singleton():
    """测试全局单例。"""
    print("\n[test] 全局单例")
    mm1 = get_memory_manager()
    mm2 = get_memory_manager()
    assert mm1 is mm2
    print("  [PASS] 全局单例正确")


def test_convenience_functions():
    """测试便捷函数。"""
    print("\n[test] 便捷函数")
    with unittest.mock.patch("utils.memory_manager.get_memory_manager") as MockGetMM:
        mock_mm = unittest.mock.MagicMock()
        mock_mm.add_memory.return_value = {"log_id": 1, "chroma_doc_id": "doc_1"}
        mock_mm.get_context.return_value = {"episodic": [], "long_term": []}
        MockGetMM.return_value = mock_mm

        result1 = add_memory("s1", "e1", "n1", {})
        result2 = get_context("query")

    assert result1["log_id"] == 1
    assert result2["episodic"] == []
    print("  [PASS] 便捷函数正确调用")


def test_constants():
    """测试常量配置。"""
    print("\n[test] 常量配置")
    assert EPISODIC_LOOKBACK_DAYS == 7
    print(f"  [PASS] EPISODIC_LOOKBACK_DAYS = {EPISODIC_LOOKBACK_DAYS}")


def test_summarize_execution_convenience():
    """测试 summarize_execution 便捷函数。"""
    print("\n[test] summarize_execution 便捷函数")
    mock_ltm = unittest.mock.MagicMock()
    mock_ltm.summarize_and_store.return_value = "memory_summary_001"
    mock_mm = unittest.mock.MagicMock()
    mock_mm.long_term = mock_ltm

    with unittest.mock.patch("utils.memory_manager.get_memory_manager", return_value=mock_mm):
        doc_id = summarize_execution(
            session_id="test_session",
            planner_decision={"sub_agent_plan": []},
            execution_result={"collected_count": 8},
            trigger_type="manual",
        )

    assert doc_id == "memory_summary_001"
    print("  [PASS] summarize_execution 正确调用")


# ============================================================
# 运行
# ============================================================

if __name__ == "__main__":
    print("=" * 50)
    print("记忆管理模块测试 (FeedLens 场景适配)")
    print("=" * 50)

    tests = [
        test_episodic_write,
        test_episodic_get_recent_days,
        test_long_term_summarize_and_store,
        test_long_term_summarize_fallback,
        test_long_term_search,
        test_memory_manager_add,
        test_get_context,
        test_global_singleton,
        test_convenience_functions,
        test_constants,
        test_summarize_execution_convenience,
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
            import traceback
            traceback.print_exc()

    print("")
    print("=" * 50)
    print(f"测试结果: {passed}/{passed + failed} 通过")
    if failed > 0:
        print(f"失败: {failed}")
    print("=" * 50)
    sys.exit(0 if failed == 0 else 1)
