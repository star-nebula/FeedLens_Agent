"""
FeedLens 数据库初始化脚本。

Usage:
    python scripts/init_db.py [--db-path data/feedlens.db]

一次性执行：创建 SQLite 11 张表 + 索引 + WAL 模式 + 种子用户。
"""

import sys
import os
import argparse

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.database import Database


def main():
    parser = argparse.ArgumentParser(description="Initialize FeedLens SQLite database.")
    parser.add_argument(
        "--db-path",
        default="data/feedlens.db",
        help="Path to SQLite database file (default: data/feedlens.db)",
    )
    args = parser.parse_args()

    db = Database(args.db_path)

    # --- Step 1: Initialize schema ---
    print(f"[init_db] Creating schema at {args.db_path} ...")
    db.init_schema()
    print("[init_db] Schema created (11 tables + indexes).")

    # --- Step 2: Seed default user ---
    with db.get_connection() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if existing == 0:
            conn.execute(
                "INSERT INTO users (goal_text) VALUES (?)",
                ("",),  # 空 Goal，等待用户通过 UI 设置
            )
            print("[init_db] Default user seeded (id=1, goal_text empty).")
        else:
            print(f"[init_db] {existing} user(s) already exist, skip seeding.")

    # --- Step 3: Verify ---
    with db.get_connection() as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = [t["name"] for t in tables]
        print(f"[init_db] Verified: {len(table_names)} tables — {', '.join(table_names)}")

    print("[init_db] Done.")


if __name__ == "__main__":
    main()
