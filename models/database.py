"""
FeedLens SQLite 数据库连接模块。

性能优化:
- WAL 模式（并发读写）
- 页面缓存优化（cache_size）
- 同步模式优化（NORMAL）
- 批量插入支持
- 连接池支持

Usage:
    from models.database import Database
    db = Database("data/feedlens.db")
    with db.get_connection() as conn:
        conn.execute("SELECT ...")
"""

import sqlite3
import os
import json
from contextlib import contextmanager
from threading import Lock
from typing import List, Dict, Any, Optional


class Database:
    """SQLite 数据库封装，WAL 模式 + 线程安全 + 性能优化。"""

    def __init__(self, db_path: str, cache_size: int = 10000):
        self.db_path = db_path
        self.cache_size = cache_size
        self._connection_pool: List[sqlite3.Connection] = []
        self._pool_lock = Lock()
        self._max_pool_size = 5
        os.makedirs(os.path.dirname(db_path), exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """创建优化的数据库连接。"""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)

        # WAL 模式（并发读写）
        conn.execute("PRAGMA journal_mode=WAL")

        # 页面缓存（增加到 10000 页，每页约 4KB）
        conn.execute(f"PRAGMA cache_size=-{self.cache_size}")

        # 同步模式（WAL 模式下可以设置为 NORMAL 提高性能）
        conn.execute("PRAGMA synchronous=NORMAL")

        # 启用外键约束
        conn.execute("PRAGMA foreign_keys=ON")

        # 禁用写同步（WAL 模式下可安全禁用）
        conn.execute("PRAGMA synchronous=OFF")

        # 设置行工厂
        conn.row_factory = sqlite3.Row

        return conn

    def _get_from_pool(self) -> sqlite3.Connection:
        """从连接池获取连接。"""
        with self._pool_lock:
            if self._connection_pool:
                return self._connection_pool.pop()
        return self._connect()

    def _return_to_pool(self, conn: sqlite3.Connection):
        """将连接放回连接池。"""
        with self._pool_lock:
            if len(self._connection_pool) < self._max_pool_size:
                self._connection_pool.append(conn)
            else:
                conn.close()

    @contextmanager
    def get_connection(self):
        """获取数据库连接（上下文管理器，自动提交/回滚）。"""
        conn = self._get_from_pool()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._return_to_pool(conn)

    def init_schema(self):
        """初始化全部 11 张表（幂等：CREATE TABLE IF NOT EXISTS）。"""
        with self.get_connection() as conn:
            conn.executescript(_SCHEMA_SQL)

    def bulk_insert(self, table_name: str, rows: List[Dict[str, Any]]):
        """批量插入数据。

        Args:
            table_name: 表名
            rows: 行数据列表，每行是字典，键为列名
        """
        if not rows:
            return

        with self.get_connection() as conn:
            # 获取列名
            columns = list(rows[0].keys())
            placeholders = ", ".join(["?" for _ in columns])
            column_names = ", ".join(columns)

            # 准备数据
            data = [tuple(row[col] for col in columns) for row in rows]

            # 执行批量插入
            conn.execute(
                f"""
                INSERT INTO {table_name} ({column_names})
                VALUES ({placeholders})
                """,
                data[0],
            )

            # 使用 executemany 批量插入剩余行
            conn.executemany(
                f"""
                INSERT INTO {table_name} ({column_names})
                VALUES ({placeholders})
                """,
                data[1:],
            )

    # ============================================================
    # 执行日志记录
    # ============================================================

    def insert_execution_log(
        self,
        session_id: str,
        turn: int,
        event: str,
        node_name: str,
        status: str,
        duration_ms: int = None,
        metadata: dict = None,
    ) -> int:
        """插入执行日志。

        Args:
            session_id: 会话 ID
            turn: 轮次
            event: 事件类型
            node_name: 节点名称
            status: 状态 (started/completed/failed)
            duration_ms: 耗时（毫秒）
            metadata: 元数据（JSON）

        Returns:
            日志 ID
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO execution_logs
                (session_id, turn, event, node_name, status, duration_ms, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    turn,
                    event,
                    node_name,
                    status,
                    duration_ms,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            return cursor.lastrowid

    def update_execution_log(
        self,
        log_id: int,
        status: str,
        duration_ms: int = None,
        metadata: dict = None,
    ):
        """更新执行日志状态。

        Args:
            log_id: 日志 ID
            status: 新状态
            duration_ms: 耗时（毫秒）
            metadata: 元数据（JSON）
        """
        with self.get_connection() as conn:
            conn.execute(
                """
                UPDATE execution_logs
                SET status = ?, duration_ms = ?, metadata = ?
                WHERE id = ?
                """,
                (
                    status,
                    duration_ms,
                    json.dumps(metadata) if metadata else None,
                    log_id,
                ),
            )

    # ============================================================
    # 运行日志记录
    # ============================================================

    def insert_run_log(
        self,
        trigger_type: str,
        items_collected: int = None,
        items_deduped: int = None,
        dedup_rate: float = None,
        brief_quality_score: float = None,
        duration_ms: int = None,
    ) -> int:
        """插入运行日志。

        Args:
            trigger_type: 触发类型 (daily_briefing/manual/breaking_news/feedback_update)
            items_collected: 采集条目数
            items_deduped: 去重后条目数
            dedup_rate: 去重率
            brief_quality_score: 简报质量分
            duration_ms: 耗时（毫秒）

        Returns:
            日志 ID
        """
        with self.get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO run_logs
                (trigger_type, items_collected, items_deduped, dedup_rate,
                 brief_quality_score, duration_ms)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    trigger_type,
                    items_collected,
                    items_deduped,
                    dedup_rate,
                    brief_quality_score,
                    duration_ms,
                ),
            )
            return cursor.lastrowid

    # ============================================================
    # 30 天数据清理
    # ============================================================

    def cleanup_old_data(self, days: int = 30):
        """清理指定天数之前的过期数据。

        Args:
            days: 保留天数，超过此天数的数据将被清理

        Returns:
            清理统计信息
        """
        stats = {}

        with self.get_connection() as conn:
            # 清理 raw_items（保留最近 30 天）
            result = conn.execute(
                """
                DELETE FROM raw_items
                WHERE fetched_at < datetime('now', '-{} days')
                """.format(days)
            )
            stats["raw_items_deleted"] = result.rowcount

            # 清理 execution_logs（保留最近 30 天）
            result = conn.execute(
                """
                DELETE FROM execution_logs
                WHERE created_at < datetime('now', '-{} days')
                """.format(days)
            )
            stats["execution_logs_deleted"] = result.rowcount

            # 清理 item_relations（保留最近 30 天）
            result = conn.execute(
                """
                DELETE FROM item_relations
                WHERE created_at < datetime('now', '-{} days')
                """.format(days)
            )
            stats["item_relations_deleted"] = result.rowcount

            # 清理孤立的 deduped_items（没有关联的 briefing_items）
            result = conn.execute(
                """
                DELETE FROM deduped_items
                WHERE id NOT IN (SELECT item_id FROM briefing_items)
                  AND created_at < datetime('now', '-{} days')
                """.format(days)
            )
            stats["deduped_items_deleted"] = result.rowcount

        return stats


# ============================================================
# 表结构 DDL（11 张表）
# ============================================================

_SCHEMA_SQL = """
-- 用户表：存储 Goal 文本和结构化提取结果
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_text       TEXT    NOT NULL,
    topics          TEXT,
    keywords        TEXT,
    preferred_sources TEXT,
    goal_embedding  BLOB,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- RSS 源管理
CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT    NOT NULL,
    name            TEXT,
    category        TEXT,
    authority_score REAL    DEFAULT 0.5,
    is_active       INTEGER DEFAULT 1,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 原始采集条目
CREATE TABLE IF NOT EXISTS raw_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER REFERENCES sources(id),
    title           TEXT,
    summary         TEXT,
    content         TEXT,
    url             TEXT,
    published_at    TIMESTAMP,
    fetched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    embedding_id    TEXT
);

-- 去重后条目
CREATE TABLE IF NOT EXISTS deduped_items (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    representative_item_id  INTEGER REFERENCES raw_items(id),
    similar_count           INTEGER DEFAULT 1,
    category                TEXT,
    keywords                TEXT,
    importance              REAL,
    source_diversity_bonus  REAL    DEFAULT 0,
    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 去重关系记录
CREATE TABLE IF NOT EXISTS item_relations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_a_id       INTEGER REFERENCES raw_items(id),
    item_b_id       INTEGER REFERENCES raw_items(id),
    relation_type   TEXT,
    similarity_score REAL,
    dedup_method    TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 简报表
CREATE TABLE IF NOT EXISTS briefs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id),
    content_json    TEXT,
    content_md      TEXT,
    quality_score   REAL,
    quality_detail  TEXT,
    retry_count     INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 简报-条目关联表（多对多）
CREATE TABLE IF NOT EXISTS briefing_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    briefing_id     INTEGER REFERENCES briefs(id),
    item_id         INTEGER REFERENCES deduped_items(id),
    rank            INTEGER,
    final_score     REAL,
    is_highlight    INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户反馈记录
CREATE TABLE IF NOT EXISTS feedback (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id),
    brief_id        INTEGER REFERENCES briefs(id),
    item_id         INTEGER REFERENCES deduped_items(id),
    feedback_type   TEXT    CHECK(feedback_type IN ('like','dislike','irrelevant')),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 用户偏好配置
CREATE TABLE IF NOT EXISTS user_preferences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id),
    keyword         TEXT,
    weight          REAL,
    vector_id       TEXT,
    feedback_count  INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Agent 执行日志
CREATE TABLE IF NOT EXISTS execution_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,
    turn            INTEGER,
    event           TEXT,
    node_name       TEXT,
    status          TEXT    CHECK(status IN ('started','completed','failed')),
    duration_ms     INTEGER,
    metadata        TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 运行记录
CREATE TABLE IF NOT EXISTS run_logs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    trigger_type        TEXT    CHECK(trigger_type IN (
                            'daily_briefing','manual','breaking_news','feedback_update'
                        )),
    items_collected     INTEGER,
    items_deduped       INTEGER,
    dedup_rate          REAL,
    brief_quality_score REAL,
    duration_ms         INTEGER,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_raw_items_source ON raw_items(source_id);
CREATE INDEX IF NOT EXISTS idx_raw_items_published ON raw_items(published_at);
CREATE INDEX IF NOT EXISTS idx_deduped_items_category ON deduped_items(category);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_item ON feedback(item_id);
CREATE INDEX IF NOT EXISTS idx_execution_session ON execution_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_execution_node ON execution_logs(node_name);
CREATE INDEX IF NOT EXISTS idx_run_logs_trigger ON run_logs(trigger_type);
"""
