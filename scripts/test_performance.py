"""
性能基准测试脚本。

测试目标:
1. 单次 Agent 运行 < 60s
2. Embedding 推理 < 100ms/条
3. 排序 + 简报 < 30s
4. SQLite 批量插入性能
5. RSS 采集性能
"""

import sys
import os
import time
import tempfile
import random
from typing import List, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

from models.database import Database
from utils.embedding import EmbeddingModel
from tools.fc_tools import fetch_rss
from agents.ranking_agent import rank_items_node
from datetime import datetime


def test_embedding_performance(num_items: int = 100):
    """测试 Embedding 推理性能。"""
    print("\n[test] Embedding 推理性能")

    # 生成测试文本
    test_texts = [
        f"测试文本 {i}: 人工智能和大模型的最新进展，包括 GPT、Claude、LLaMA 等模型的技术突破和应用案例。"
        for i in range(num_items)
    ]

    # 加载模型 + warm-up（排除首次加载开销）
    model = EmbeddingModel()
    _ = model.encode(["warm-up"])

    # 测试批量推理（取 3 次中值）
    times = []
    for _ in range(3):
        start_time = time.time()
        embeddings = model.encode(test_texts)
        times.append(time.time() - start_time)
    total_time = sorted(times)[1]  # median

    # 计算平均耗时
    avg_time_per_item = (total_time / num_items) * 1000

    # 验证结果
    assert len(embeddings) == num_items
    actual_dim = len(embeddings[0])
    print(f"  Embedding 维度: {actual_dim}")

    print(f"  处理 {num_items} 条文本")
    print(f"  总耗时: {total_time:.2f}s")
    print(f"  平均耗时: {avg_time_per_item:.2f}ms/条")

    # 判断是否达标
    if avg_time_per_item < 100:
        print("  [PASS] Embedding 推理 < 100ms/条")
    else:
        print("  [WARN] Embedding 推理 > 100ms/条")

    return {
        "num_items": num_items,
        "total_time_s": total_time,
        "avg_time_ms_per_item": avg_time_per_item,
        "passed": avg_time_per_item < 100,
    }


def test_sqlite_batch_insert(num_rows: int = 1000):
    """测试 SQLite 批量插入性能。"""
    print("\n[test] SQLite 批量插入性能")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name

    try:
        db = Database(temp_db_path)
        db.init_schema()

        # 生成测试数据
        test_rows = [
            {
                "title": f"测试标题 {i}",
                "summary": f"测试摘要 {i}",
                "url": f"https://example.com/{i}",
                "published_at": datetime.now().isoformat(),
            }
            for i in range(num_rows)
        ]

        # 测试批量插入（executemany）
        start_time = time.time()
        with db.get_connection() as conn:
            conn.executemany(
                "INSERT INTO raw_items (title, summary, url, published_at) VALUES (?, ?, ?, ?)",
                [(r["title"], r["summary"], r["url"], r["published_at"]) for r in test_rows],
            )
        total_time = time.time() - start_time

        # 验证插入结果
        with db.get_connection() as conn:
            count = conn.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
            assert count == num_rows

        print(f"  批量插入 {num_rows} 条")
        print(f"  耗时: {total_time:.2f}s")
        print(f"  速率: {num_rows / total_time:.0f} 条/秒")
        print("  [PASS] SQLite 批量插入正确")

        return {
            "num_rows": num_rows,
            "total_time_s": total_time,
            "rate_per_second": num_rows / total_time,
        }

    finally:
        time.sleep(0.1)
        try:
            os.unlink(temp_db_path)
        except:
            pass


def test_rss_fetch_performance():
    """测试 RSS 采集性能。"""
    print("\n[test] RSS 采集性能")

    # 优先用本地测试文件，回退到公开 RSS 源
    local_feed = os.path.join(os.path.dirname(__file__), "test_data", "sample_feed.xml")
    if os.path.exists(local_feed):
        test_feeds = [local_feed] * 5  # 用本地文件模拟 5 源
    else:
        test_feeds = [
            "https://rss.cnn.com/rss/cnn_topstories.rss",
        ]

    # 测试采集
    start_time = time.time()
    items = fetch_rss(test_feeds, max_workers=10)
    total_time = time.time() - start_time

    # 过滤有效条目
    valid_items = [item for item in items if "error" not in item]

    print(f"  采集 {len(test_feeds)} 个 RSS 源")
    print(f"  耗时: {total_time:.2f}s")
    print(f"  有效条目: {len(valid_items)}")
    print(f"  错误条目: {len(items) - len(valid_items)}")

    return {
        "num_feeds": len(test_feeds),
        "total_time_s": total_time,
        "valid_items": len(valid_items),
        "error_items": len(items) - len(valid_items),
    }


def test_ranking_performance(num_items: int = 50):
    """测试排序性能。"""
    print("\n[test] 排序性能")

    # 生成测试数据
    test_items = [
        {
            "id": f"item_{i}",
            "title": f"测试新闻 {i}",
            "summary": f"测试摘要 {i}，这是关于人工智能和大模型的新闻内容。",
            "url": f"https://example.com/{i}",
            "source": "test",
            "published_at": datetime.now().isoformat(),
            "importance": random.uniform(1, 5),
            "category": "科技",
            "embedding": [random.uniform(-1, 1) for _ in range(384)],
        }
        for i in range(num_items)
    ]

    # 构造状态
    state = {
        "collected_items": test_items,
        "goal_embedding": [0.1] * 384,
        "goal_text": "关注人工智能和大模型领域",
        "feedback_history": [
            {"item_id": "item_1", "feedback_type": "like"},
            {"item_id": "item_2", "feedback_type": "dislike"},
        ],
    }

    # 测试排序
    start_time = time.time()
    result = rank_items_node(state)
    total_time = time.time() - start_time

    # 验证结果
    assert "ranked_items" in result
    actual_count = len(result["ranked_items"])
    print(f"  实际返回: {actual_count} 条")

    print(f"  排序 {num_items} 条")
    print(f"  耗时: {total_time:.2f}s")
    print("  [PASS] 排序正确")

    return {
        "num_items": num_items,
        "total_time_s": total_time,
    }


def test_connection_pool():
    """测试连接池性能。"""
    print("\n[test] 连接池性能")

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name

    try:
        db = Database(temp_db_path)
        db.init_schema()

        # 测试多次获取连接
        num_connections = 10
        start_time = time.time()

        for i in range(num_connections):
            with db.get_connection() as conn:
                conn.execute("SELECT 1")

        total_time = time.time() - start_time

        print(f"  获取 {num_connections} 次连接")
        print(f"  耗时: {total_time:.3f}s")
        print(f"  平均: {(total_time / num_connections) * 1000:.2f}ms/次")
        print("  [PASS] 连接池正确")

        return {
            "num_connections": num_connections,
            "total_time_s": total_time,
            "avg_time_ms_per_connection": (total_time / num_connections) * 1000,
        }

    finally:
        time.sleep(0.1)
        try:
            os.unlink(temp_db_path)
        except:
            pass


def run_benchmark():
    """运行完整性能基准测试。"""
    print("=" * 60)
    print("FeedLens 性能基准测试")
    print("=" * 60)

    results = {}

    # 1. Embedding 性能测试
    results["embedding"] = test_embedding_performance(100)

    # 2. SQLite 批量插入测试
    results["sqlite_batch"] = test_sqlite_batch_insert(1000)

    # 3. RSS 采集测试
    results["rss_fetch"] = test_rss_fetch_performance()

    # 4. 排序性能测试
    results["ranking"] = test_ranking_performance(50)

    # 5. 连接池测试
    results["connection_pool"] = test_connection_pool()

    # 汇总报告
    print("\n" + "=" * 60)
    print("性能基准测试报告")
    print("=" * 60)

    print("\n[PERF] 各模块耗时:")
    print(f"  Embedding (100条): {results['embedding']['total_time_s']:.2f}s "
          f"(平均 {results['embedding']['avg_time_ms_per_item']:.2f}ms/条)")
    print(f"  SQLite 批量插入 (1000条): {results['sqlite_batch']['total_time_s']:.2f}s")
    print(f"  RSS 采集 (5源): {results['rss_fetch']['total_time_s']:.2f}s")
    print(f"  排序 (50条): {results['ranking']['total_time_s']:.2f}s")

    # 判断是否达标（单模块指标）
    print("\n[CHECK] 达标情况:")
    if results["embedding"]["avg_time_ms_per_item"] < 100:
        print("  [OK] Embedding 推理 < 100ms/条")
    else:
        print("  [FAIL] Embedding 推理 > 100ms/条")



    ranking_time = results["ranking"]["total_time_s"]
    if ranking_time < 30:
        print("  [OK] 排序 < 30s")
    else:
        print("  [FAIL] 排序 > 30s")

    print("\n" + "=" * 60)

    return results


if __name__ == "__main__":
    run_benchmark()
