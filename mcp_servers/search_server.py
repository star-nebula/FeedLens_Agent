"""
FeedLens search_web MCP Server (SSE :8100)

提供 web 搜索工具，当 RSS 采集不足时补充搜索结果。
MVP 阶段使用 DuckDuckGo Instant Answer API 作为搜索源（无需 API Key），
失败时降级为模拟数据。

运行方式:
    python -m mcp_servers.search_server
"""

import json
import sys
from typing import List, Dict, Any

import httpx
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
        results = await _search_duckduckgo(query, max_results)
        if results:
            return results
    except Exception as e:
        print(f"[search] DuckDuckGo search failed: {e}", file=sys.stderr)

    # 降级：返回模拟数据
    return _mock_search_results(query, max_results)


async def _search_duckduckgo(query: str, max_results: int) -> List[Dict[str, Any]]:
    """调用 DuckDuckGo Instant Answer API。"""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_html": 1,
                "skip_disambig": 1,
            },
            headers={"Accept": "application/json", "User-Agent": "FeedLens/1.0"},
        )
        response.raise_for_status()
        data = response.json()

        results = []
        topics = data.get("RelatedTopics", [])

        for topic in topics:
            if len(results) >= max_results:
                break

            if "Text" in topic and "FirstURL" in topic:
                text = topic.get("Text", "")
                title = text.split(" - ")[0] if " - " in text else text[:60]
                results.append({
                    "title": title,
                    "url": topic["FirstURL"],
                    "snippet": text,
                    "source": "duckduckgo",
                })
            elif "Topics" in topic:
                for sub in topic["Topics"]:
                    if len(results) >= max_results:
                        break
                    if "Text" in sub and "FirstURL" in sub:
                        text = sub.get("Text", "")
                        title = text.split(" - ")[0] if " - " in text else text[:60]
                        results.append({
                            "title": title,
                            "url": sub["FirstURL"],
                            "snippet": text,
                            "source": "duckduckgo",
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
