"""
采集 Agent 测试脚本。

测试内容：
  1. StateGraph 构建
  2. fetch_rss_node 节点（使用本地测试 RSS）
  3. should_search 条件边逻辑
  4. search_web_node 节点（需 MCP search_server 运行）
  5. enrich_metadata_node 节点（需 LLM API Key）
  6. normalize_items_node 节点
  7. 完整工作流集成测试

Usage:
    # 先启动 search_server
    python -m mcp_servers.search_server

    # 再运行测试
    python scripts/test_collection_agent.py
"""

import sys
import os
import subprocess
import time
import asyncio

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.collection_agent import (
    build_collection_agent,
    fetch_rss_node,
    search_web_node,
    enrich_metadata_node,
    normalize_items_node,
    should_search,
    _get_search_query,
    _get_rss_sources,
)
from agents.state import FeedLensState


# ============================================================
# 辅助
# ============================================================

def make_state(**kwargs) -> FeedLensState:
    """构造测试状态。"""
    return {
        "session_id": "test-session",
        "user_id": 1,
        "trigger_type": "daily_briefing",
        "goal_text": "关注 AI Agent 技术进展",
        "structured_goal": {
            "topics": ["AI Agent", "大模型", "多智能体"],
            "keywords": ["AI", "Agent", "LLM"],
            "preferred_sources": [],
        },
        **kwargs,
    }


# ============================================================
# 测试用例
# ============================================================

def test_build_graph():
    """测试 StateGraph 能正常编译。"""
    print("\n" + "=" * 60)
    print("[test] build_collection_agent - StateGraph 编译")
    print("=" * 60)
    try:
        agent = build_collection_agent()
        assert agent is not None
        print("✓ StateGraph 编译成功")
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_rss_sources():
    """测试 RSS 源选择逻辑。"""
    print("\n" + "=" * 60)
    print("[test] _get_rss_sources - RSS 源选择")
    print("=" * 60)

    # 有 preferred_sources → 优先使用（mock 数据库无活跃源）
    from models import database as db_mod
    original_db = db_mod.Database
    class FakeDB:
        def __init__(self, *a, **kw): pass
        def get_connection(self):
            from contextlib import contextmanager
            class FakeConn:
                def execute(self, *a, **kw):
                    class FakeResult:
                        def fetchall(self): return []
                    return FakeResult()
                def __enter__(self): return self
                def __exit__(self, *a): pass
            @contextmanager
            def conn():
                yield FakeConn()
            return conn()
    db_mod.Database = FakeDB

    state = make_state(structured_goal={"preferred_sources": ["http://example.com/feed"] })
    sources = _get_rss_sources(state)
    db_mod.Database = original_db  # 恢复
    assert sources == ["http://example.com/feed"], f"expected ['http://example.com/feed'], got {sources}"
    print("✓ preferred_sources 优先逻辑正确")

    # 无 preferred_sources + 无 DB → 使用默认
    state2 = make_state(structured_goal={"topics": ["AI"], "preferred_sources": []})
    db_mod.Database = FakeDB
    sources2 = _get_rss_sources(state2)
    db_mod.Database = original_db
    print(f"✓ 默认源: {sources2}")
    assert len(sources2) > 0, "默认源不应为空"
    return True


def test_get_search_query():
    """测试搜索查询词构建。"""
    print("\n" + "=" * 60)
    print("[test] _get_search_query - 查询词构建")
    print("=" * 60)

    state = make_state()
    q = _get_search_query(state)
    print(f"✓ 查询词: {q}")
    assert "AI Agent" in q or "大模型" in q or "多智能体" in q
    # 测试 keywords 回退
    state2 = make_state(structured_goal={"topics": [], "keywords": ["LLM", "Agent", "RL"]})
    q2 = _get_search_query(state2)
    print(f"✓ keywords 回退查询词: {q2}")
    assert "LLM" in q2
    # 测试 goal_text 兜底
    state3 = make_state(structured_goal={"topics": [], "keywords": []})
    q3 = _get_search_query(state3)
    print(f"✓ goal_text 兜底查询词: {q3}")
    assert len(q3) > 0
    return True
    return True


def test_should_search():
    """测试条件边逻辑。"""
    print("\n" + "=" * 60)
    print("[test] should_search - 条件边逻辑")
    print("=" * 60)

    state = make_state(collected_items=[])
    assert should_search(state) == "search_web"
    print("✓ 0 条 → search_web")

    state = make_state(collected_items=[{"title": str(i)} for i in range(3)])
    assert should_search(state) == "search_web"
    print("✓ 3 条 → search_web")

    state = make_state(collected_items=[{"title": str(i)} for i in range(5)])
    assert should_search(state) == "enrich_metadata"
    print("✓ 5 条 → enrich_metadata")

    state = make_state(collected_items=[{"title": str(i)} for i in range(10)])
    assert should_search(state) == "enrich_metadata"
    print("✓ 10 条 → enrich_metadata")
    return True


def test_fetch_rss_node():
    """测试 fetch_rss_node（使用本地测试 RSS 文件）。"""
    print("\n" + "=" * 60)
    print("[test] fetch_rss_node - RSS 采集")
    print("=" * 60)

    test_feed = os.path.join(os.path.dirname(__file__), "test_data", "sample_feed.xml")
    if not os.path.exists(test_feed):
        print(f"⚠ 跳过：未找到测试 RSS 文件 {test_feed}")
        # 回退：使用空列表测试节点不崩溃
        state = make_state(structured_goal={"preferred_sources": []})
        state["collected_items"] = []
        result = fetch_rss_node(state)
        print(f"✓ 空状态回退: {len(result.get('collected_items', []))} 条")
        return "skip"

    state = make_state(structured_goal={"preferred_sources": [test_feed]})
    result = fetch_rss_node(state)
    items = result.get("collected_items", [])
    print(f"✓ 采集完成: {len(items)} 条")
    if items:
        print(f"  第一条: {items[0].get('title', 'N/A')[:60]}...")
        assert "title" in items[0]
        assert "url" in items[0]
    return True


def test_normalize_items_node():
    """测试 normalize_items_node。"""
    print("\n" + "=" * 60)
    print("[test] normalize_items_node - 字段标准化")
    print("=" * 60)

    raw = [
        {"title": "  Test Title ", "url": "http://example.com/1", "summary": "summary"},
        {"title": "Title2", "url": "", "content": "content text"},
    ]
    state = make_state(collected_items=raw)
    result = normalize_items_node(state)
    items = result.get("collected_items", [])
    print(f"✓ 标准化完成: {len(items)} 条")
    assert all("id" in item for item in items), "每条应有 id"
    assert all("fetched_at" in item for item in items), "每条应有 fetched_at"
    assert items[0]["title"] == "Test Title", "title 应被 strip"
    print(f"  字段示例: {list(items[0].keys())}")
    return True


async def test_search_web_node():
    """测试 search_web_node（需 MCP search_server 在 :8100 运行）。"""
    print("\n" + "=" * 60)
    print("[test] search_web_node - MCP 搜索补充")
    print("=" * 60)

    state = make_state(collected_items=[{"title": "existing"}])
    try:
        result = await search_web_node(state)
        items = result.get("collected_items", [])
        supplemented = result.get("search_supplemented", False)
        print(f"✓ 搜索完成: supplemented={supplemented}, 共 {len(items)} 条")
        return True
    except Exception as e:
        print(f"⚠ search_web 失败（search_server 可能未启动）: {e}")
        return "skip"
        return True  # 不阻塞整体测试


def test_enrich_metadata_node():
    """测试 enrich_metadata_node（需配置 LLM API Key）。"""
    print("\n" + "=" * 60)
    print("[test] enrich_metadata_node - LLM 元数据增强")
    print("=" * 60)

    import yaml
    config_path = "config/config.yaml"
    if not os.path.exists(config_path):
        print("⚠ 跳过：未找到配置文件")
        return "skip"
        return True

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    api_key = config.get("llm", {}).get("deepseek", {}).get("api_key", "")
    if not api_key or api_key == "sk-your-api-key-here":
        print("⚠ 跳过：未配置 DeepSeek API Key")
        return "skip"
        return True

    items = [
        {"title": "OpenAI 发布 GPT-5", "summary": "OpenAI 今日发布了新一代大模型 GPT-5，性能大幅提升。", "url": "http://example.com/1"},
        {"title": "Google 推出 Gemini Pro", "summary": "Google 推出了 Gemini Pro 模型，支持多模态输入。", "url": "http://example.com/2"},
    ]
    state = make_state(collected_items=items)
    try:
        result = enrich_metadata_node(state)
        enriched = result.get("collected_items", [])
        print(f"✓ 增强完成: {len(enriched)} 条")
        for item in enriched:
            print(f"  [{item.get('category', '?')}] {item['title'][:40]}... "
                  f"keywords={item.get('keywords', '?')[:30]} "
                  f"importance={item.get('importance', '?')}")
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        return False


async def test_full_workflow():
    """测试完整工作流（使用本地 RSS + 可选搜索补充）。"""
    print("\n" + "=" * 60)
    print("[test] 完整工作流集成测试")
    print("=" * 60)

    agent = build_collection_agent()

    test_feed = os.path.join(os.path.dirname(__file__), "test_data", "sample_feed.xml")
    preferred = [test_feed] if os.path.exists(test_feed) else []

    state = make_state(
        structured_goal={
            "topics": ["AI"],
            "keywords": ["人工智能"],
            "preferred_sources": preferred,
        }
    )

    try:
        result = await agent.ainvoke(state)
        items = result.get("collected_items", [])
        print(f"✓ 工作流完成: {len(items)} 条")
        assert len(items) > 0, "工作流完成但采集到 0 条（预期 >= 3 条来自 sample_feed.xml）"
        if items:
            print(f"  字段示例: {list(items[0].keys())}")
            assert all(k in items[0] for k in ["id", "title", "url", "category", "keywords", "importance"])
            print("✓ 输出字段完整")
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# 主流程
# ============================================================

async def main():
    print("FeedLens 采集 Agent 测试脚本")

    results = []
    results.append(("build_graph", test_build_graph()))
    results.append(("get_rss_sources", test_get_rss_sources()))
    results.append(("get_search_query", test_get_search_query()))
    results.append(("should_search", test_should_search()))
    results.append(("fetch_rss_node", test_fetch_rss_node()))
    results.append(("normalize_items_node", test_normalize_items_node()))
    results.append(("search_web_node", await test_search_web_node()))
    results.append(("enrich_metadata_node", test_enrich_metadata_node()))
    results.append(("full_workflow", await test_full_workflow()))

    print("\n" + "=" * 60)
    print("[summary] 测试结果汇总")
    print("=" * 60)
    passed = 0
    failed = 0
    skipped = 0

    for name, ok in results:
        if ok == "skip":
            status = "SKIP"
            skipped += 1
        elif ok:
            status = "PASS"
            passed += 1
        else:
            status = "FAIL"
            failed += 1
        print(f"  {status:6}  {name}")

    print(f"\n总计: {passed} 通过, {failed} 失败, {skipped} 跳过")

    if failed > 0:
        print("\n⚠️ 部分测试失败，请检查错误信息")
        return False
    if skipped > 0:
        print(f"\n✅ 所有实测通过！{skipped} 项跳过（需配置 API Key 或启动 search_server 后可测）")
    else:
        print("\n🎉 全部采集 Agent 测试通过！")
    return True


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
