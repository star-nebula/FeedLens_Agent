"""
采集 Agent — RSS 采集 + 搜索补充 + 元数据提取 + 标准化。

工作流: fetch_rss → (search_web?) → enrich_metadata → normalize_items
ReAct: 判断是否需要补充搜索 → 执行 → 评估
"""

import os
from datetime import datetime
import asyncio
from typing import List, Dict, Any

from langgraph.graph import StateGraph, END
from utils.config import load_config
from agents.state import FeedLensState
from tools import fetch_rss, enrich_metadata, normalize_items
from tools.mcp_client import SearchMCPClient
from utils.llm_provider import DeepSeekProvider


# ============================================================
# 默认 RSS 源（MVP 兜底）
# ============================================================

DEFAULT_RSS_SOURCES = [
    # 科技资讯（中文，通过 RSSHub）
    "https://rsshub.app/solidot/",
    "https://rsshub.app/36kr/information/web_news/",
    "https://rsshub.app/36kr/news/latest",
    "https://rsshub.app/zhihu/daily",
    "https://rsshub.app/v2ex/topics/latest",
    # 国际科技
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    # 开源与开发者动态
    "https://rsshub.app/github/trending/daily",
]


# ============================================================
def _get_llm_provider() -> DeepSeekProvider:
    """根据配置创建 LLM Provider。"""
    config = load_config()
    llm_cfg = config.get("llm", {})
    deepseek_cfg = llm_cfg.get("deepseek", {})
    return DeepSeekProvider(
        api_key=deepseek_cfg.get("api_key", ""),
        base_url=deepseek_cfg.get("base_url", "https://api.deepseek.com/v1"),
        model=deepseek_cfg.get("model", "deepseek-chat"),
    )


def _get_rss_sources(state: FeedLensState) -> List[str]:
    """获取 RSS 源列表：
    1. 优先从数据库 sources 表读取用户添加的活跃源
    2. 其次使用 structured_goal 中的 preferred_sources
    3. 最后使用 DEFAULT_RSS_SOURCES 兜底
    """
    # 1. 从数据库读取用户配置的活跃源
    try:
        from models.database import Database
        db = Database("data/feedlens.db")
        with db.get_connection() as conn:
            rows = conn.execute(
                "SELECT url FROM sources WHERE is_active = 1 ORDER BY authority_score DESC"
            ).fetchall()
        if rows:
            urls = [row["url"] for row in rows]
            print(f"[fetch_rss] 从 sources 表读取 {len(urls)} 个活跃源", flush=True)
            return urls
    except Exception as e:
        print(f"[fetch_rss] 读取 sources 表失败: {e}", flush=True)

    # 2. 使用 structured_goal 中的 preferred_sources
    structured_goal = state.get("structured_goal", {})
    preferred = structured_goal.get("preferred_sources", [])
    if preferred:
        return preferred
    return DEFAULT_RSS_SOURCES


def _get_search_query(state: FeedLensState) -> str:
    """构建搜索查询词。"""
    structured_goal = state.get("structured_goal", {})
    topics = structured_goal.get("topics", [])
    keywords = structured_goal.get("keywords", [])
    if topics:
        return " ".join(topics[:3])
    if keywords:
        return " ".join(keywords[:3])
    return state.get("goal_text", "最新科技资讯")[:50]


# ============================================================
# 节点定义
# ============================================================


def fetch_rss_node(state: FeedLensState) -> dict:
    """并行采集多个 RSS 源（feedparser）。"""
    sources = _get_rss_sources(state)
    print(f"[fetch_rss] 开始采集 {len(sources)} 个 RSS 源...", flush=True)

    try:
        raw_items = fetch_rss(sources, max_workers=5)
        # 过滤掉带 error 的条目
        valid_items = [item for item in raw_items if "error" not in item]
        print(f"[fetch_rss] 采集完成: {len(valid_items)} 条有效 / {len(raw_items)} 条总计", flush=True)
        return {"collected_items": valid_items}
    except Exception as e:
        print(f"[fetch_rss] 采集失败: {e}", flush=True)
        return {"collected_items": [], "error": f"fetch_rss failed: {e}"}


def search_web_node(state: FeedLensState) -> dict:
    """条件触发：collected_items < 5 时补充 MCP search_web 搜索。

    同步实现：通过 asyncio.run 驱动异步 MCP 客户端，
    以兼容同步编译的 LangGraph StateGraph（避免在 sync .invoke() 中返回协程）。
    """
    query = _get_search_query(state)
    print(f"[search_web] 补充搜索: {query}", flush=True)

    async def _do_search():
        client = SearchMCPClient(base_url="http://127.0.0.1:8100")
        async with client:
            return await client.search(query, max_results=5)

    try:
        search_results = asyncio.run(_do_search())

        # 将 MCP 搜索结果转换为统一格式
        converted = []
        for r in search_results:
            converted.append({
                "source_url": r.get("source", "web_search"),
                "title": r.get("title", ""),
                "summary": r.get("snippet", ""),
                "content": r.get("snippet", ""),
                "url": r.get("url", ""),
                "published_at": datetime.now().isoformat(),
            })

        existing = state.get("collected_items", [])
        merged = existing + converted
        print(f"[search_web] 补充 {len(converted)} 条，合并后共 {len(merged)} 条", flush=True)
        return {
            "collected_items": merged,
            "search_supplemented": True,
        }
    except Exception as e:
        print(f"[search_web] 搜索失败: {e}", flush=True)
        return {
            "collected_items": state.get("collected_items", []),
            "search_supplemented": False,
            "error": f"search_web failed: {e}",
        }

def enrich_metadata_node(state: FeedLensState) -> dict:
    """LLM 提取 category / keywords / importance。"""
    items = state.get("collected_items", [])
    if not items:
        return {"collected_items": []}

    print(f"[enrich_metadata] 开始增强 {len(items)} 条条目...", flush=True)
    try:
        llm = _get_llm_provider()
        enriched = enrich_metadata(items, llm_provider=llm, batch_size=5)
        print(f"[enrich_metadata] 增强完成", flush=True)
        return {"collected_items": enriched}
    except Exception as e:
        print(f"[enrich_metadata] 失败: {e}", flush=True)
        # 失败时返回原始条目，附加默认元数据
        for item in items:
            item.setdefault("category", "other")
            item.setdefault("keywords", "")
            item.setdefault("importance", 0.5)
        return {"collected_items": items, "error": f"enrich_metadata failed: {e}"}


def normalize_items_node(state: FeedLensState) -> dict:
    """统一字段格式化，输出 collected_items。"""
    items = state.get("collected_items", [])
    if not items:
        return {"collected_items": []}

    print(f"[normalize_items] 开始标准化 {len(items)} 条条目...", flush=True)
    normalized = normalize_items(items)

    # 统一设置 fetched_at
    now = datetime.now().isoformat()
    for item in normalized:
        item["fetched_at"] = now

    print(f"[normalize_items] 标准化完成", flush=True)
    return {"collected_items": normalized}


# ============================================================
# 条件边
# ============================================================


def should_search(state: FeedLensState) -> str:
    """判断是否需要补充搜索。"""
    items = state.get("collected_items", [])
    if len(items) < 5:
        print(f"[should_search] 当前 {len(items)} 条 < 5，触发补充搜索", flush=True)
        return "search_web"
    print(f"[should_search] 当前 {len(items)} 条 >= 5，跳过搜索", flush=True)
    return "enrich_metadata"


# ============================================================
# StateGraph 构建
# ============================================================


def build_collection_agent():
    """构建采集 Agent StateGraph。"""
    workflow = StateGraph(FeedLensState)

    workflow.add_node("fetch_rss", fetch_rss_node)
    workflow.add_node("search_web", search_web_node)
    workflow.add_node("enrich_metadata", enrich_metadata_node)
    workflow.add_node("normalize_items", normalize_items_node)

    workflow.set_entry_point("fetch_rss")

    # 条件边: RSS 后判断是否搜索
    workflow.add_conditional_edges(
        "fetch_rss",
        should_search,
        {"search_web": "search_web", "enrich_metadata": "enrich_metadata"},
    )
    workflow.add_edge("search_web", "enrich_metadata")
    workflow.add_edge("enrich_metadata", "normalize_items")
    workflow.add_edge("normalize_items", END)

    return workflow.compile()
