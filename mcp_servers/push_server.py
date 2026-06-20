"""
FeedLens push_notification MCP Server (stdio)

提供简报推送工具，将推送内容写入本地通知队列（JSONL 文件），
供 Streamlit 前端读取展示。

运行方式:
    python -m mcp_servers.push_server
    （通常由主进程通过 MCP stdio client 自动启动）
"""

import json
import os
import sys
from datetime import datetime
from typing import Dict, Any

from mcp.server.fastmcp import FastMCP


# 通知队列文件路径
DEFAULT_QUEUE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "notifications.jsonl",
)

mcp = FastMCP("FeedLensPush")


@mcp.tool()
def push(brief: Dict[str, Any], user_id: int, immediate: bool = False) -> bool:
    """
    推送简报给用户。

    Args:
        brief: 简报内容字典，通常包含 title, sections, summary 等
        user_id: 用户ID
        immediate: 是否立即推送（重大事件破例）

    Returns:
        推送是否成功
    """
    try:
        queue_path = os.environ.get("FEEDLENS_NOTIFICATION_QUEUE", DEFAULT_QUEUE_PATH)
        os.makedirs(os.path.dirname(queue_path), exist_ok=True)

        notification = {
            "user_id": user_id,
            "brief": brief,
            "immediate": immediate,
            "pushed_at": datetime.now().isoformat(),
            "read": False,
        }

        with open(queue_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(notification, ensure_ascii=False) + "\n")

        print(f"[push] Notification queued for user {user_id}", file=sys.stderr)
        return True
    except Exception as e:
        print(f"[push] Error: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    mcp.run(transport="stdio")
