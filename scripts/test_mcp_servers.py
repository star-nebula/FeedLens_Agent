"""
测试 MCP Server 功能。

测试步骤：
1. 启动 search_server.py（SSE :8100）
2. 测试 search 工具
3. 测试 push_server.py（stdio）
4. 测试 push 工具

Usage:
    python scripts/test_mcp_servers.py
"""

import asyncio
import os
import subprocess
import sys
import time

# 将项目根目录加入 sys.path，确保能 import tools
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 修正 Windows 终端编码
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


async def test_search_server():
    """测试 search_web MCP Server (SSE)。"""
    from tools.mcp_client import SearchMCPClient

    print("\n" + "=" * 60)
    print("[test] search_web MCP Server (SSE :8100)")
    print("=" * 60)

    client = SearchMCPClient(base_url="http://127.0.0.1:8100")
    try:
        async with client:
            results = await client.search("人工智能", max_results=5)
            print(f"OK 搜索成功，返回 {len(results)} 条结果")
            for i, r in enumerate(results[:3]):
                title = r.get("title", "N/A")
                source = r.get("source", "N/A")
                print(f"  [{i+1}] {title} ({source})")
            return True
    except Exception as e:
        import traceback
        print(f"FAIL 失败: {e}")
        traceback.print_exc()
        return False


async def test_push_server():
    """测试 push_notification MCP Server (stdio)。"""
    from tools.mcp_client import PushMCPClient

    print("\n" + "=" * 60)
    print("[test] push_notification MCP Server (stdio)")
    print("=" * 60)

    client = PushMCPClient()
    try:
        async with client:
            brief = {
                "title": "每日简报测试",
                "sections": [
                    {"category": "technology", "items": ["AI 新进展", "LLM 发布"]}
                ],
                "summary": "今日技术动态",
            }
            result = await client.push(brief, user_id=1, immediate=False)
            print(f"OK 推送结果: {result}")
            return True
    except Exception as e:
        print(f"FAIL 失败: {e}")
        return False


async def run_all_tests():
    search_ok = await test_search_server()
    push_ok = await test_push_server()
    return search_ok, push_ok


def main():
    print("FeedLens MCP Server 测试脚本")

    # 先启动 search_server
    print("\n[info] 启动 search_server.py (SSE :8100)...")
    proc = subprocess.Popen(
        [sys.executable, "-m", "mcp_servers.search_server"],
        cwd="E:\\BaiduSyncdisk\\Project\\heima-lesson\\LLM_Projects\\FeedLens_Agent",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    time.sleep(3)  # 等待服务器启动

    try:
        search_ok, push_ok = asyncio.run(run_all_tests())

        print("\n" + "=" * 60)
        print("[summary] 测试结果")
        print("=" * 60)
        print(f"search_web (SSE):         {'PASS' if search_ok else 'FAIL'}")
        print(f"push_notification (stdio): {'PASS' if push_ok else 'FAIL'}")
    finally:
        print("\n[info] 终止 search_server...")
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    main()
