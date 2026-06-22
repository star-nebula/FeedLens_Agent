"""
FeedLens search_web MCP Server (SSE :8100)

提供 web 搜索工具，当 RSS 采集不足时补充搜索结果。
使用 cn.bing.com 作为搜索源（无需 API Key，国内可用），
失败时降级为模拟数据。

运行方式:
    python -m mcp_servers.search_server
"""

import json
import re
import sys
from typing import List, Dict, Any
from html import unescape

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP


# 创建 MCP 服务器实例
mcp = FastMCP("FeedLensSearch")


@mcp.tool()
async def search(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """
    搜索网页内容。

    Args:
        query: 搜索关键词
        max_results: 最大返回结果数（默认10）

    Returns:
        搜索结果列表，每项包含 title, url, snippet, source
    """
    try:
        results = await _search_bing(query, max_results)
        if results:
            return results
    except Exception as e:
        print(f"[search] Bing search failed: {e}", file=sys.stderr)

    # 降级：返回模拟数据
    return _mock_search_results(query, max_results)


async def _search_bing(query: str, max_results: int) -> List[Dict[str, Any]]:
    """解析 cn.bing.com 搜索结果页。"""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(
            "https://cn.bing.com/search",
            params={"q": query, "count": max_results},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    # cn.bing.com 搜索结果在 <li class="b_algo"> 中
    for item in soup.select("li.b_algo"):
        if len(results) >= max_results:
            break

        title_el = item.select_one("h2 a")
        snippet_el = item.select_one(".b_caption p") or item.select_one(".b_lineclamp2")

        if not title_el:
            continue

        title = title_el.get_text(strip=True)
        url = title_el.get("href", "")
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""

        # 清理 HTML 实体和多余空白
        title = unescape(title)
        snippet = unescape(snippet)
        snippet = re.sub(r"\s+", " ", snippet).strip()

        results.append({
            "title": title,
            "url": url,
            "snippet": snippet,
            "source": "bing",
        })

    return results


def _mock_search_results(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """模拟搜索结果，用于 API 降级或测试。"""
    mock = []
    for i in range(min(max_results, 3)):
        mock.append({
            "title": f"[模拟] {query} 相关结果 {i + 1}",
            "url": f"https://example.com/search?q={query}&idx={i}",
            "snippet": f"这是关于 {query} 的模拟搜索结果片段 {i + 1}，用于 MVP 测试。",
            "source": "mock",
        })
    return mock


if __name__ == "__main__":
    mcp.settings.host = "127.0.0.1"
    mcp.settings.port = 8100
    print("[FeedLensSearch] Starting MCP Server on SSE :8100", file=sys.stderr)
    mcp.run(transport="sse")
