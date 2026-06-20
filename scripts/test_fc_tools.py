"""
FC 工具验证测试脚本。

测试所有 8 个工具函数的基本功能：
  1. fetch_rss - RSS 采集
  2. enrich_metadata - LLM 元数据增强（需配置 LLM API Key）
  3. normalize_items - 字段格式化
  4. deduplicate - 向量去重
  5. db_read - SQLite 读取
  6. db_write - SQLite 写入
  7. vector_search - ChromaDB 检索
  8. vector_add - ChromaDB 写入

Usage:
    python scripts/test_fc_tools.py
"""

import sys
import os
import json

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools import (
    fetch_rss, enrich_metadata, normalize_items, deduplicate,
    db_read, db_write, vector_search, vector_add
)
from models.database import Database
from models.vector_store import VectorStore
from utils.embedding import EmbeddingModel
from utils.llm_provider import DeepSeekProvider

def test_fetch_rss():
    """测试 RSS 采集工具。"""
    print("\n" + "=" * 60)
    print("[test] fetch_rss - RSS 采集")
    print("=" * 60)

    import os
    test_feed = os.path.join(os.path.dirname(__file__), "test_data", "sample_feed.xml")
    # feedparser.parse() 可直接接受本地文件路径，无需 file:// 包装（Windows 兼容）
    test_urls = [test_feed]

    try:
        items = fetch_rss(test_urls, max_workers=2)
        print(f"\u2713 \u91c7\u96c6\u5b8c\u6210\uff0c\u5171 {len(items)} \u6761")
        assert len(items) > 0, "\u91c7\u96c6\u7ed3\u679c\u4e3a\u7a7a\uff0cRSS \u89e3\u6790\u53ef\u80fd\u5931\u8d25"
        print(f"  \u7b2c\u4e00\u6761: {items[0]['title']}...")
        assert "source_url" in items[0], "\u7f3a\u5c11 source_url \u5b57\u6bb5"
        assert "title" in items[0] and len(items[0]["title"]) > 0, "title \u5b57\u6bb5\u7f3a\u5931\u6216\u4e3a\u7a7a"
        return True
    except AssertionError as e:
        print(f"\u2717 \u65ad\u8a00\u5931\u8d25: {e}")
        return False
    except Exception as e:
        print(f"\u2717 \u5931\u8d25: {e}")
        return False

def test_normalize_items():
    """测试字段格式化工具。"""
    print("\n" + "=" * 60)
    print("[test] normalize_items - 字段格式化")
    print("=" * 60)

    raw_items = [
        {"title": "  AI 进展 ", "url": "http://example.com/1", "summary": "摘要内容"},
        {"title": "机器学习", "url": "", "content": "完整内容"},
    ]

    try:
        normalized = normalize_items(raw_items)
        print(f"✓ 格式化完成，共 {len(normalized)} 条")
        print(f"  ID 生成: {normalized[0]['id'][:8]}...")
        print(f"  字段检查: {list(normalized[0].keys())}")
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        return False

def test_db_read_write():
    """测试 SQLite 读写工具。"""
    print("\n" + "=" * 60)
    print("[test] db_read / db_write - SQLite 读写")
    print("=" * 60)

    test_db_path = "data/test_fc_tools.db"

    try:
        db = Database(test_db_path)
        db.init_schema()

        write_result = db_write(test_db_path, "INSERT INTO sources (url, name) VALUES (?, ?)", ["http://test.com", "测试源"])
        print(f"✓ 写入成功，影响行数: {write_result}")

        read_result = db_read(test_db_path, "SELECT * FROM sources WHERE name = ?", ["测试源"])
        print(f"✓ 读取成功，返回 {len(read_result)} 条")
        if read_result:
            print(f"  结果: id={read_result[0]['id']}, url={read_result[0]['url']}")

        os.remove(test_db_path)
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        return False

def test_vector_search_add():
    """测试 ChromaDB 向量工具。"""
    print("\n" + "=" * 60)
    print("[test] vector_search / vector_add - ChromaDB 向量")
    print("=" * 60)

    test_chroma_path = "data/test_chroma"

    try:
        add_count = vector_add(
            test_chroma_path,
            ids=["test_1", "test_2"],
            documents=["人工智能最新进展", "机器学习算法优化"],
            metadatas=[{"category": "technology"}, {"category": "technology"}],
        )
        print(f"✓ 添加成功，数量: {add_count}")

        search_result = vector_search(test_chroma_path, "AI 技术", n_results=2)
        print(f"✓ 检索成功，返回 {len(search_result)} 条")
        for hit in search_result:
            print(f"  id={hit['id']}, similarity={hit['similarity']:.4f}")

        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        return False

def test_deduplicate():
    """测试向量去重工具。"""
    print("\n" + "=" * 60)
    print("[test] deduplicate - 向量去重")
    print("=" * 60)

    test_chroma_path = "data/test_dedup_chroma"

    try:
        vs = VectorStore(persist_dir=test_chroma_path)
        vs.init_collections()

        embedding_model = EmbeddingModel()

        test_items = [
            {"id": "1", "title": "人工智能取得重大突破", "summary": "AI 技术取得了新的进展"},
            {"id": "2", "title": "人工智能获重大突破", "summary": "人工智能技术取得新进展"},
            {"id": "3", "title": "Python 编程入门", "summary": "学习 Python 基础语法"},
        ]

        normalized = normalize_items(test_items)
        unique_items, duplicate_pairs = deduplicate(
            normalized, vs, embedding_model, None,
            threshold_high=0.88,
            threshold_low=0.70,
            max_llm_adjudications=0,
        )

        print(f"✓ 去重完成，原始 {len(test_items)} 条，去重后 {len(unique_items)} 条")
        print(f"  去重关系: {len(duplicate_pairs)} 对")
        for pair in duplicate_pairs:
            print(f"    {pair['item_a_id']} ↔ {pair['item_b_id']} (sim={pair['similarity_score']:.4f})")

        vs.close()
        import shutil
        shutil.rmtree(test_chroma_path)
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        if os.path.exists(test_chroma_path):
            try:
                vs.close()
            except Exception:
                pass
            import shutil
            shutil.rmtree(test_chroma_path)
        return False

def test_enrich_metadata():
    """测试 LLM 元数据增强工具（需配置 API Key）。"""
    print("\n" + "=" * 60)
    print("[test] enrich_metadata - LLM 元数据增强")
    print("=" * 60)

    import yaml
    config_path = "config/config.yaml"
    if not os.path.exists(config_path):
        print("✗ 跳过：未找到配置文件")
        return "skip"

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    api_key = config.get("llm", {}).get("deepseek", {}).get("api_key", "")
    if not api_key:
        print("✗ 跳过：未配置 DeepSeek API Key")
        return "skip"

    try:
        llm_provider = DeepSeekProvider(api_key=api_key)

        test_items = [
            {"title": "英伟达发布新一代 GPU", "summary": "英伟达发布了最新的人工智能芯片"},
            {"title": "OpenAI 推出新模型", "summary": "OpenAI 发布了更强大的语言模型"},
        ]

        enriched = enrich_metadata(test_items, llm_provider, batch_size=2)
        print(f"✓ 增强完成，共 {len(enriched)} 条")
        for item in enriched:
            print(f"  标题: {item['title'][:30]}...")
            print(f"    category: {item['category']}")
            print(f"    keywords: {item['keywords']}")
            print(f"    importance: {item['importance']}")
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        return False

def main():
    print("=" * 60)
    print("FeedLens FC 工具验证测试")
    print("=" * 60)

    results = []

    results.append(("fetch_rss", test_fetch_rss()))
    results.append(("normalize_items", test_normalize_items()))
    results.append(("db_read/write", test_db_read_write()))
    results.append(("vector_search/add", test_vector_search_add()))
    results.append(("deduplicate", test_deduplicate()))
    results.append(("enrich_metadata", test_enrich_metadata()))

    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    passed = 0
    failed = 0
    skipped = 0

    for name, result in results:
        if result == "skip":
            status = "🔶 跳过"
            skipped += 1
        elif result:
            status = "✅ 通过"
            passed += 1
        else:
            status = "❌ 失败"
            failed += 1
        print(f"  {name}: {status}")

    print(f"\n总计: {passed} 通过, {failed} 失败, {skipped} 跳过")

    if failed == 0 and passed > 0:
        if skipped > 0:
            print(f"\n✅ 所有实测通过！{skipped} 项跳过（需配置 API Key 后可测）")
        else:
            print("\n🎉 所有 FC 工具验证通过！")
        sys.exit(0)
    else:
        print("\n⚠️ 部分测试失败，请检查错误信息")
        sys.exit(1)


if __name__ == "__main__":
    main()
