"""
FeedLens MCP Client 封装模块。

提供对 search_web (SSE) 和 push_notification (stdio) 两个 MCP Server 的便捷调用。

Usage:
    # 同步调用 search
    from tools.mcp_client import search_web
    results = search_web("人工智能", max_results=5)

    # 同步调用 push
    from tools.mcp_client import push_notification
    ok = push_notification(brief={"title": "..."}, user_id=1)

    # 异步调用（推荐在 Agent 内部使用）
    async with SearchMCPClient() as client:
        results = await client.search("AI")
"""

import asyncio
import contextlib
import json
import os
import sys
from typing import Optional, Dict, Any, List

from mcp import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client, StdioServerParameters


# ============================================================
# Search MCP Client (SSE)
# ============================================================

class SearchMCPClient:
    """
    search_web MCP Server 的客户端封装（SSE 模式）。

    使用示例:
        async with SearchMCPClient() as client:
            results = await client.search("人工智能", max_results=5)
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8100"):
        self.base_url = base_url
        self._exit_stack: Optional[contextlib.AsyncExitStack] = None
        self._session: Optional[ClientSession] = None

    async def connect(self):
        """建立 SSE 连接并初始化会话。"""
        self._exit_stack = contextlib.AsyncExitStack()
        streams = await self._exit_stack.enter_async_context(
            sse_client(f"{self.base_url}/sse")
        )
        read_stream, write_stream = streams
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        return self

    async def disconnect(self):
        """关闭连接。"""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._session = None

    async def search(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        调用 search 工具。

        Args:
            query: 搜索关键词
            max_results: 最大结果数

        Returns:
            搜索结果列表
        """
        if not self._session:
            raise RuntimeError("Client not connected. Use `async with` or call connect().")

        result = await self._session.call_tool(
            "search",
            arguments={"query": query, "max_results": max_results},
        )
        if result.content:
            # MCP 1.28.0 可能将列表拆分为多个 TextContent，逐个解析后合并
            items = []
            for content in result.content:
                if hasattr(content, "text"):
                    parsed = json.loads(content.text)
                    if isinstance(parsed, list):
                        items.extend(parsed)
                    elif isinstance(parsed, dict):
                        items.append(parsed)
            return items
        return []

    def search_sync(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """同步调用 search。"""
        async def _run():
            async with self:
                return await self.search(query, max_results)
        return asyncio.run(_run())

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


# ============================================================
# Push MCP Client (stdio)
# ============================================================

class PushMCPClient:
    """
    push_notification MCP Server 的客户端封装（stdio 模式）。
    负责启动 push_server.py 子进程并与其通信。

    使用示例:
        async with PushMCPClient() as client:
            ok = await client.push(brief={...}, user_id=1)
    """

    def __init__(self, server_script: Optional[str] = None):
        if server_script is None:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            server_script = os.path.join(project_root, "mcp_servers", "push_server.py")
        self.server_script = server_script
        self._exit_stack: Optional[contextlib.AsyncExitStack] = None
        self._session: Optional[ClientSession] = None

    async def connect(self):
        """启动 stdio 子进程并初始化会话。"""
        self._exit_stack = contextlib.AsyncExitStack()
        params = StdioServerParameters(
            command=sys.executable,
            args=[self.server_script],
            env=os.environ.copy(),
        )
        streams = await self._exit_stack.enter_async_context(
            stdio_client(params)
        )
        read_stream, write_stream = streams
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await self._session.initialize()
        return self

    async def disconnect(self):
        """关闭连接并终止子进程。"""
        if self._exit_stack:
            await self._exit_stack.aclose()
            self._exit_stack = None
        self._session = None

    async def push(self, brief: Dict[str, Any], user_id: int, immediate: bool = False) -> bool:
        """
        调用 push 工具。

        Args:
            brief: 简报内容
            user_id: 用户ID
            immediate: 是否立即推送

        Returns:
            推送是否成功
        """
        if not self._session:
            raise RuntimeError("Client not connected. Use `async with` or call connect().")

        result = await self._session.call_tool(
            "push",
            arguments={"brief": brief, "user_id": user_id, "immediate": immediate},
        )
        if result.content:
            text = result.content[0].text
            return json.loads(text)
        return False

    def push_sync(self, brief: Dict[str, Any], user_id: int, immediate: bool = False) -> bool:
        """同步调用 push。"""
        async def _run():
            async with self:
                return await self.push(brief, user_id, immediate)
        return asyncio.run(_run())

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


# ============================================================
# 便捷函数（同步 API）
# ============================================================

def search_web(query: str, max_results: int = 10, base_url: str = "http://127.0.0.1:8100") -> List[Dict[str, Any]]:
    """
    同步调用 search_web MCP Server。

    注意：调用前需确保 search_server.py 已在 :8100 端口运行。
    """
    client = SearchMCPClient(base_url=base_url)
    return client.search_sync(query, max_results)


def push_notification(brief: Dict[str, Any], user_id: int, immediate: bool = False) -> bool:
    """
    同步调用 push_notification MCP Server（stdio 模式）。

    该函数会启动 push_server.py 子进程，执行推送后关闭。
    """
    client = PushMCPClient()
    return client.push_sync(brief, user_id, immediate)
