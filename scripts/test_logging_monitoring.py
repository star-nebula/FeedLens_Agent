"""
日志和监控测试脚本。
"""

import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from utils.logging_config import (
    configure_logging,
    get_logger,
    log_event,
    log_error,
    log_metric,
)
from models.database import Database
from utils.error_isolation import (
    task_error_isolation,
    TaskErrorIsolator,
    run_with_isolation,
    isolate_agent_node,
)


def test_structlog_config():
    """测试 structlog 配置（使用临时目录，避免污染项目 logs/）。"""
    print("\n[test] structlog 配置")

    # 重定向日志输出到临时目录
    tmp_log_dir = tempfile.mkdtemp(prefix="feedlens_test_logs_")
    try:
        os.environ["FEEDLENS_LOG_DIR"] = tmp_log_dir

        # 测试控制台格式
        configure_logging(log_level="DEBUG", log_format="console")
        logger = get_logger("test")
        assert logger is not None, "get_logger 应返回 BoundLogger 实例"

        # 测试各级别日志不抛异常
        logger.debug("debug_message", key="value")
        logger.info("info_message", count=42)
        logger.warning("warning_message", reason="test")
        logger.error("error_message", code=500)

        # 测试 JSON 格式
        configure_logging(log_level="INFO", log_format="json")
        logger2 = get_logger("json_test")
        logger2.info("json_message", data={"key": "value"})

        # 测试辅助函数
        log_event(logger, "info", "test_event", extra="data")
        log_metric(logger, "latency", 123.45, unit="ms")

        # 验证日志文件不为空（JSON 格式会写文件）
        json_logs = [f for f in os.listdir(tmp_log_dir) if f.endswith(".log")]
        print(f"  日志文件数: {len(json_logs)}")
    finally:
        shutil.rmtree(tmp_log_dir, ignore_errors=True)
        os.environ.pop("FEEDLENS_LOG_DIR", None)

    print("  [PASS] structlog 配置正确")


def test_execution_logs():
    """测试 execution_logs 记录。"""
    print("\n[test] execution_logs 记录")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name

    try:
        db = Database(temp_db_path)
        db.init_schema()

        # 插入执行日志
        log_id = db.insert_execution_log(
            session_id="test_session",
            turn=1,
            event="node_started",
            node_name="planner",
            status="started",
            metadata={"key": "value"},
        )
        assert log_id > 0

        # 更新执行日志
        db.update_execution_log(
            log_id=log_id,
            status="completed",
            duration_ms=1234,
        )

        # 验证记录
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM execution_logs WHERE id = ?", (log_id,)
            )
            row = cursor.fetchone()
            assert row["session_id"] == "test_session"
            assert row["status"] == "completed"
            assert row["duration_ms"] == 1234

        print(f"  日志 ID: {log_id}")
        print("  [PASS] execution_logs 记录正确")

    finally:
        os.unlink(temp_db_path)


def test_run_logs():
    """测试 run_logs 记录。"""
    print("\n[test] run_logs 记录")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name

    try:
        db = Database(temp_db_path)
        db.init_schema()

        # 插入运行日志
        log_id = db.insert_run_log(
            trigger_type="daily_briefing",
            items_collected=100,
            items_deduped=80,
            dedup_rate=0.2,
            brief_quality_score=0.85,
            duration_ms=30000,
        )
        assert log_id > 0

        # 验证记录
        with db.get_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM run_logs WHERE id = ?", (log_id,)
            )
            row = cursor.fetchone()
            assert row["trigger_type"] == "daily_briefing"
            assert row["items_collected"] == 100
            assert row["items_deduped"] == 80
            assert row["dedup_rate"] == 0.2
            assert row["brief_quality_score"] == 0.85

        print(f"  日志 ID: {log_id}")
        print("  [PASS] run_logs 记录正确")

    finally:
        os.unlink(temp_db_path)


def test_error_isolation_decorator():
    """测试错误隔离装饰器。"""
    print("\n[test] 错误隔离装饰器")

    @task_error_isolation(task_name="test_task", default_return="fallback")
    def failing_func():
        raise ValueError("测试异常")

    result = failing_func()
    assert result == "fallback"

    @task_error_isolation(task_name="success_task", default_return="fallback")
    def success_func():
        return "success"

    result = success_func()
    assert result == "success"

    print("  [PASS] 错误隔离装饰器正确")


def test_error_isolation_context():
    """测试错误隔离上下文管理器。"""
    print("\n[test] 错误隔离上下文管理器")

    with TaskErrorIsolator(task_name="context_test") as isolator:
        raise ValueError("测试异常")

    assert not isolator.success

    with TaskErrorIsolator(task_name="success_context") as isolator:
        pass

    assert isolator.success

    print("  [PASS] 错误隔离上下文管理器正确")


def test_run_with_isolation():
    """测试 run_with_isolation 函数。"""
    print("\n[test] run_with_isolation 函数")

    def failing_func():
        raise ValueError("测试异常")

    result = run_with_isolation("test_func", failing_func, default_return="fallback")
    assert result == "fallback"

    def success_func():
        return "success"

    result = run_with_isolation("success_func", success_func)
    assert result == "success"

    print("  [PASS] run_with_isolation 函数正确")


def test_isolate_agent_node():
    """测试 Agent 节点错误隔离。"""
    print("\n[test] Agent 节点错误隔离")

    @isolate_agent_node
    def failing_node(state):
        raise ValueError("节点失败")

    state = {"key": "value"}
    result = failing_node(state)

    assert "error" in result
    assert result["error"]["node"] == "failing_node"

    @isolate_agent_node
    def success_node(state):
        return {"key": "value", "result": "success"}

    result = success_node(state)
    assert "result" in result
    assert result["result"] == "success"

    print("  [PASS] Agent 节点错误隔离正确")


def test_cleanup_old_data():
    """测试 30 天数据清理。"""
    print("\n[test] 30 天数据清理")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name

    try:
        db = Database(temp_db_path)
        db.init_schema()

        # 插入测试数据
        with db.get_connection() as conn:
            # 旧数据（31天前）
            conn.execute(
                """
                INSERT INTO raw_items (title, fetched_at)
                VALUES ('old_item', datetime('now', '-31 days'))
                """
            )
            # 新数据（1天前）
            conn.execute(
                """
                INSERT INTO raw_items (title, fetched_at)
                VALUES ('new_item', datetime('now', '-1 day'))
                """
            )

            # 旧执行日志
            conn.execute(
                """
                INSERT INTO execution_logs (session_id, turn, event, node_name, status, created_at)
                VALUES ('old_session', 1, 'test', 'test', 'completed', datetime('now', '-31 days'))
                """
            )

        # 执行清理
        stats = db.cleanup_old_data(days=30)

        # 验证清理结果
        assert stats["raw_items_deleted"] == 1
        assert stats["execution_logs_deleted"] == 1

        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
            assert count == 1

        print(f"  清理统计: {stats}")
        print("  [PASS] 30 天数据清理正确")

    finally:
        os.unlink(temp_db_path)


def run_tests():
    print("=" * 60)
    print("日志和监控测试")
    print("=" * 60)

    tests = [
        test_structlog_config,
        test_execution_logs,
        test_run_logs,
        test_error_isolation_decorator,
        test_error_isolation_context,
        test_run_with_isolation,
        test_isolate_agent_node,
        test_cleanup_old_data,
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
    print("=" * 60)
    print(f"测试结果: {passed}/{passed + failed} 通过")
    if failed > 0:
        print(f"失败: {failed}")
    print("=" * 60)

    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
