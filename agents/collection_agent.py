"""
采集 Agent — ReAct 循环实现（Agentic 升级规划2 Phase 3a）。

从 StateGraph 改为 ReAct 循环：LLM Thought → function_call → Observation → ... → finish_task

工具列表: fetch_rss, search_web, enrich_metadata, normalize_items, finish_task
"""

import json
import os
from datetime import datetime
from typing import List, Dict, Any

from langgraph.graph import StateGraph, END
from utils.config import load_config
from agents.state import FeedLensState
from tools import fetch_rss, enrich_metadata, normalize_items
from tools.tool_registry import tool_registry
from utils.llm_provider import DeepSeekProvider


# ============================================================
# 默认 RSS 源（MVP 兜底）
# ============================================================

DEFAULT_RSS_SOURCES = [
    "https://rsshub.app/solidot/",
    "https://rsshub.app/36kr/information/web_news/",
    "https://rsshub.app/36kr/news/latest",
    "https://rsshub.app/zhihu/daily",
    "https://rsshub.app/v2ex/topics/latest",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://rsshub.app/github/trending/daily",
]

# ============================================================
# 配置辅助
# ============================================================

def _get_llm_provider() -> DeepSeekProvider:
    config = load_config()
    llm_cfg = config.get("llm", {})
    deepseek_cfg = llm_cfg.get("deepseek", {})
    return DeepSeekProvider(
        api_key=deepseek_cfg.get("api_key", ""),
        base_url=deepseek_cfg.get("base_url", "https://api.deepseek.com/v1"),
        model=deepseek_cfg.get("model", "deepseek-chat"),
    )


def _get_rss_sources(state: FeedLensState) -> List[str]:
    """获取 RSS 源列表：数据库 > structured_goal > DEFAULT。"""
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
# System Prompt
# ============================================================

COLLECTION_SYSTEM_PROMPT = """你是 FeedLens 的采集 Agent。你的目标是从多个来源采集信息。

可用工具：
- fetch_rss: 并行采集多个 RSS 源的内容
- search_web: 通过搜索引擎补充采集内容（当 RSS 采集量不足时使用）
- enrich_metadata: 可选，使用 LLM 对条目提取分类、关键词、重要性评分（如未调用，系统自动填充默认值）
- normalize_items: 统一条目字段格式
- finish_task: 标记采集完成，返回结果摘要

工作流程建议：
1. 先调用 fetch_rss 采集 RSS 源
2. 如果采集量 < 5 条，调用 search_web 补充搜索
3. 调用 normalize_items 标准化字段
4. 调用 finish_task 结束

enrich_metadata 是可选的，跳过不影响流程。完成后必须调用 finish_task。"""


# ============================================================
# ReAct 采集函数
# ============================================================

def run_collection_agent(state: FeedLensState) -> dict:
    """ReAct 采集 Agent — LLM 自主调用工具完成采集任务。

    Args:
        state: FeedLensState，包含 goal_text, structured_goal 等

    Returns:
        dict: {collected_items, search_supplemented, collection_summary}
    """
    llm = _get_llm_provider()
    tools = tool_registry.get_schemas_for_phase("collection")

    # 构建初始消息
    goal_text = state.get("goal_text", "收集最新科技资讯")
    structured_goal = state.get("structured_goal", {})
    sources = _get_rss_sources(state)

    user_msg = f"用户目标: {goal_text}\n"
    if structured_goal.get("topics"):
        user_msg += f"关注主题: {', '.join(structured_goal['topics'])}\n"
    if structured_goal.get("keywords"):
        user_msg += f"关键词: {', '.join(structured_goal['keywords'])}\n"
    user_msg += f"可用 RSS 源: {sources[:5]}...\n"

    messages = [
        {"role": "system", "content": COLLECTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    collected_items = state.get("collected_items", [])
    search_supplemented = False
    collection_summary = ""

    max_turns = 5
    for turn in range(max_turns):
        print(f"[collection_react] 第 {turn + 1} 轮思考...", flush=True)

        try:
            response_dict = llm.chat_with_tools(messages=messages, tools=tools)
        except Exception as e:
            print(f"[collection_react] LLM 调用失败: {e}，退出循环", flush=True)
            break

        # 从 model_dump() dict 提取 choice
        choices = response_dict.get("choices", [])
        if not choices:
            print("[collection_react] LLM 返回空 choices，退出循环", flush=True)
            break
        choice = choices[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")

        # 检查是否有 tool_calls
        tool_calls = message.get("tool_calls", [])
        if tool_calls and finish_reason == "tool_calls":
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    tool_args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                print(f"[collection_react] 调用工具: {tool_name}", flush=True)

                # 特殊处理：注入 RSS 源列表
                if tool_name == "fetch_rss" and "sources" not in tool_args:
                    tool_args["sources"] = _get_rss_sources(state)
                # 特殊处理：注入搜索查询词
                if tool_name == "search_web" and "query" not in tool_args:
                    tool_args["query"] = _get_search_query(state)
                # 特殊处理：注入已采集条目（enrich/normalize 需要 items 参数）
                if tool_name in ("enrich_metadata", "normalize_items") and "items" not in tool_args:
                    tool_args["items"] = collected_items

                try:
                    result = tool_registry.dispatch(tool_name, tool_args)
                except Exception as e:
                    result = {"error": str(e)}
                    print(f"[collection_react] 工具 {tool_name} 失败: {e}", flush=True)

                # 累积结果
                if tool_name == "fetch_rss":
                    items = result.get("items", [])
                    valid = [it for it in items if "error" not in it]
                    collected_items.extend(valid)
                elif tool_name == "search_web":
                    items = result.get("items", [])
                    if items:
                        search_supplemented = True
                    collected_items.extend(items)
                elif tool_name == "enrich_metadata":
                    enriched = result.get("items", [])
                    if enriched:
                        enriched_map = {it.get("id", ""): it for it in enriched}
                        for i, item in enumerate(collected_items):
                            item_id = item.get("id", "")
                            if item_id in enriched_map:
                                collected_items[i] = enriched_map[item_id]
                elif tool_name == "normalize_items":
                    normalized = result.get("items", [])
                    if normalized:
                        collected_items = normalized
                elif tool_name == "finish_task":
                    collection_summary = result.get("summary", "")
                    print(f"[collection_react] 采集完成: {len(collected_items)} 条", flush=True)
                    # 追加 finish_task 调用记录到 messages 历史（保持完整性，便于审计/重放）
                    messages.append(message)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", tool_name),
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                    return {
                        "collected_items": collected_items,
                        "search_supplemented": search_supplemented,
                        "collection_summary": collection_summary,
                    }

                # 将 assistant message 和 tool result 追加到 messages
                messages.append(message)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", tool_name),
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
        else:
            # LLM 没调工具直接回复，视为异常
            content = message.get("content", "")
            print(f"[collection_react] LLM 未调用工具，回复: {content[:100]}", flush=True)
            # 如果 LLM 没有 tool_calls 但有内容，再给它一次机会
            if content and turn < max_turns - 1:
                # 安全处理：清除可能残留的 tool_calls 字段，防止下轮 API 400 错误
                safe_message = {k: v for k, v in message.items() if k != "tool_calls"}
                messages.append(safe_message)
                messages.append({"role": "user", "content": "请调用工具执行采集任务，完成后调用 finish_task。"})
                continue
            break

    # 兜底：超过 max_turns 未 finish，返回已有数据
    print(f"[collection_react] 超过 {max_turns} 轮未完成，强制返回 {len(collected_items)} 条", flush=True)
    return {
        "collected_items": collected_items,
        "search_supplemented": search_supplemented,
        "collection_summary": collection_summary or f"超时结束，共采集 {len(collected_items)} 条",
    }


# ============================================================
# 兼容接口：保持 build_collection_agent().invoke(state) 签名
# ============================================================

class _ReActAgentWrapper:
    """将 ReAct 函数包装为兼容 StateGraph .invoke() 的对象。"""

    def __init__(self, fn):
        self._fn = fn

    def invoke(self, state: dict) -> dict:
        return self._fn(state)


def build_collection_agent():
    """构建采集 Agent（兼容旧接口）。

    返回一个具有 .invoke(state) 方法的对象，内部执行 ReAct 循环。
    """
    return _ReActAgentWrapper(run_collection_agent)
