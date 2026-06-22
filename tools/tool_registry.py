"""
FeedLens 工具注册表 — 将所有工具包装为标准 OpenAI function calling schema。

每个工具 = {name, description, parameters(JSON Schema), fn(可调用函数)}

Usage:
    from tools.tool_registry import tool_registry

    # 获取所有工具 schema（给 LLM function calling）
    schemas = tool_registry.get_schemas()

    # 获取指定阶段的工具 schema
    schemas = tool_registry.get_schemas_for_phase("collection")

    # 执行工具
    result = tool_registry.dispatch("fetch_rss", {"sources": [...], "max_workers": 3})
"""

import json
from typing import List, Dict, Any, Callable, Optional


# ============================================================
# 工具执行函数（薄包装，延迟导入避免循环依赖）
# ============================================================

def _execute_fetch_rss(arguments: dict) -> dict:
    """RSS 采集。"""
    from tools.fc_tools import fetch_rss as _fn
    sources = arguments.get("sources", [])
    max_workers = arguments.get("max_workers", 5)
    timeout = arguments.get("timeout", 10)
    if not sources:
        from agents.collection_agent import DEFAULT_RSS_SOURCES
        sources = DEFAULT_RSS_SOURCES
    items = _fn(source_urls=sources, max_workers=max_workers, timeout=timeout)
    valid = [it for it in items if "error" not in it]
    return {"items": items, "count": len(items), "valid_count": len(valid)}


def _execute_search_web(arguments: dict) -> dict:
    """MCP 搜索补充。"""
    import asyncio
    from tools.mcp_client import SearchMCPClient

    query = arguments.get("query", "")
    max_results = arguments.get("max_results", 5)
    base_url = arguments.get("base_url", "http://127.0.0.1:8100")

    async def _do():
        client = SearchMCPClient(base_url=base_url)
        async with client:
            return await client.search(query, max_results=max_results)

    try:
        results = asyncio.run(_do())
        converted = []
        for r in results:
            converted.append({
                "source_url": r.get("source", "web_search"),
                "title": r.get("title", ""),
                "summary": r.get("snippet", ""),
                "content": r.get("snippet", ""),
                "url": r.get("url", ""),
                "published_at": "",
            })
        return {"items": converted, "count": len(converted)}
    except Exception as e:
        return {"items": [], "count": 0, "error": str(e)}


def _execute_enrich_metadata(arguments: dict) -> dict:
    """LLM 元数据增强。"""
    from tools.fc_tools import enrich_metadata as _fn
    from utils.llm_provider import DeepSeekProvider
    from utils.config import load_config

    items = arguments.get("items", [])
    batch_size = arguments.get("batch_size", 5)

    if not items:
        return {"items": [], "count": 0}

    config = load_config()
    llm_cfg = config.get("llm", {}).get("deepseek", {})
    llm = DeepSeekProvider(
        api_key=llm_cfg.get("api_key", ""),
        base_url=llm_cfg.get("base_url", "https://api.deepseek.com/v1"),
        model=llm_cfg.get("model", "deepseek-chat"),
    )
    enriched = _fn(items, llm_provider=llm, batch_size=batch_size)
    return {"items": enriched, "count": len(enriched)}


def _execute_normalize_items(arguments: dict) -> dict:
    """字段标准化。"""
    from tools.fc_tools import normalize_items as _fn
    from datetime import datetime

    items = arguments.get("items", [])
    normalized = _fn(items)
    now = datetime.now().isoformat()
    for item in normalized:
        item["fetched_at"] = now
    return {"items": normalized, "count": len(normalized)}


def _execute_deduplicate(arguments: dict) -> dict:
    """向量去重。"""
    from tools.fc_tools import deduplicate as _fn
    from models.vector_store import VectorStore
    from utils.embedding import EmbeddingModel
    from utils.llm_provider import DeepSeekProvider
    from utils.config import load_config

    items = arguments.get("items", [])
    if len(items) < 2:
        return {"unique_items": items, "duplicate_pairs": [], "unique_count": len(items)}

    config = load_config()
    persist_dir = config.get("vector_store", {}).get("persist_dir", "data/chroma")
    emb_model = EmbeddingModel()
    vs = VectorStore(persist_dir=persist_dir, embedding_fn=emb_model.encode)

    llm_cfg = config.get("llm", {}).get("deepseek", {})
    llm = DeepSeekProvider(
        api_key=llm_cfg.get("api_key", ""),
        base_url=llm_cfg.get("base_url", "https://api.deepseek.com/v1"),
        model=llm_cfg.get("model", "deepseek-chat"),
    )

    ranking_cfg = config.get("ranking", {})
    unique_items, dup_pairs = _fn(
        items,
        vector_store=vs,
        embedding_model=emb_model,
        llm_provider=llm,
        threshold_high=arguments.get("threshold_high", ranking_cfg.get("dedup_threshold", 0.88)),
        threshold_low=arguments.get("threshold_low", ranking_cfg.get("dedup_llm_lower", 0.70)),
        max_llm_adjudications=arguments.get("max_llm_adjudications", ranking_cfg.get("max_llm_adjudications", 20)),
    )
    return {"unique_items": unique_items, "duplicate_pairs": dup_pairs, "unique_count": len(unique_items)}


def _execute_rank_items(arguments: dict) -> dict:
    """多因子偏好排序。"""
    from agents.ranking_agent import rank_items_node, _load_ranking_config, _load_preference_vectors
    from datetime import datetime
    import math

    items = arguments.get("items", [])
    user_id = arguments.get("user_id", 1)
    feedback_history = arguments.get("feedback_history", [])
    goal_embedding = arguments.get("goal_embedding", [])
    expand_threshold = arguments.get("expand_threshold", False)
    max_items = arguments.get("max_items", 10)

    if not items:
        return {"ranked_items": [], "ranking_detail": {}}

    # 构建临时 state 调用排序逻辑
    temp_state = {
        "collected_items": items,
        "feedback_history": feedback_history,
        "goal_embedding": goal_embedding,
        "user_id": user_id,
        "expand_threshold": expand_threshold,
        "max_briefing_items": max_items,
        "ranking_detail": {},
    }
    # 传递预加载的偏好向量，避免 rank_items_node 内部重复加载
    if arguments.get("_pref_v_like") is not None:
        temp_state["_pref_v_like"] = arguments["_pref_v_like"]
    if arguments.get("_pref_v_dislike") is not None:
        temp_state["_pref_v_dislike"] = arguments["_pref_v_dislike"]
    result = rank_items_node(temp_state)
    return result


def _execute_generate_briefing(arguments: dict) -> dict:
    """生成简报。"""
    from agents.briefing_agent import generate_briefing_node, _render_markdown

    items = arguments.get("items", [])
    goal_text = arguments.get("goal_text", "用户关注热点新闻")
    categories = arguments.get("categories", ["科技", "商业", "社会", "其他"])

    temp_state = {
        "ranked_items": items,
        "goal_text": goal_text,
        "categories": categories,
        "briefing_result": {"retry_count": arguments.get("retry_count", 0)},
    }
    result = generate_briefing_node(temp_state)
    briefing = result.get("briefing", {})
    return {"briefing": briefing, "markdown": briefing.get("_markdown", "")}


def _execute_quality_check(arguments: dict) -> dict:
    """质量审查。"""
    from agents.briefing_agent import brief_quality_check_node

    briefing = arguments.get("briefing", {})
    ranked_items = arguments.get("ranked_items", [])
    goal_text = arguments.get("goal_text", "")

    temp_state = {
        "briefing": briefing,
        "ranked_items": ranked_items,
        "goal_text": goal_text,
        "briefing_result": {},
    }
    result = brief_quality_check_node(temp_state)
    return result


def _execute_push_notification(arguments: dict) -> dict:
    """推送简报。"""
    from tools.mcp_client import push_notification as _fn

    brief = arguments.get("brief", {})
    user_id = arguments.get("user_id", 1)
    immediate = arguments.get("immediate", False)

    try:
        ok = _fn(brief=brief, user_id=user_id, immediate=immediate)
        return {"success": ok, "user_id": user_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _execute_record_feedback(arguments: dict) -> dict:
    """记录用户反馈并更新偏好。"""
    from agents.feedback_agent import build_feedback_agent

    item_id = arguments.get("item_id", "")
    feedback_type = arguments.get("feedback_type", "like")
    user_id = arguments.get("user_id", 1)

    agent = build_feedback_agent()
    temp_state = {
        "user_id": user_id,
        "feedback_item_id": item_id,
        "feedback_type": feedback_type,
    }
    try:
        result = agent.invoke(temp_state)
        return {"success": True, "item_id": item_id, "feedback_type": feedback_type}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _execute_read_memory(arguments: dict) -> dict:
    """读取用户历史决策记忆。"""
    from utils.memory_manager import get_context

    query = arguments.get("query", "")
    n_episodic = arguments.get("n_episodic", 10)
    n_long_term = arguments.get("n_long_term", 3)
    lookback_days = arguments.get("lookback_days", 7)

    context = get_context(
        query=query,
        n_episodic=n_episodic,
        n_long_term=n_long_term,
        lookback_days=lookback_days,
    )
    return context


def _execute_write_memory(arguments: dict) -> dict:
    """写入本轮决策经验。"""
    from utils.memory_manager import add_memory

    session_id = arguments.get("session_id", "default")
    event = arguments.get("event", "planner_decision")
    node_name = arguments.get("node_name", "planner")
    content = arguments.get("content", {})
    status = arguments.get("status", "completed")
    execution_result = arguments.get("execution_result")
    planner_decision = arguments.get("planner_decision")
    trigger_type = arguments.get("trigger_type", "daily_briefing")

    result = add_memory(
        session_id=session_id,
        event=event,
        node_name=node_name,
        content=content,
        status=status,
        execution_result=execution_result,
        planner_decision=planner_decision,
        trigger_type=trigger_type,
    )
    return result


# ============================================================
# 工具定义（name + description + JSON Schema + fn）
# ============================================================

TOOLS = [
    # ---- 采集阶段 ----
    {
        "name": "fetch_rss",
        "description": "并行采集多个 RSS 源的内容。传入 URL 列表，返回采集到的条目（标题、摘要、内容、链接、发布时间）。",
        "parameters": {
            "type": "object",
            "properties": {
                "sources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "RSS 源 URL 列表，如果不传则使用默认源",
                },
                "max_workers": {
                    "type": "integer",
                    "description": "并行采集线程数，默认 5",
                },
                "timeout": {
                    "type": "integer",
                    "description": "每个源的请求超时秒数，默认 10",
                },
            },
            "required": [],
        },
        "fn": _execute_fetch_rss,
        "phase": "collection",
    },
    {
        "name": "search_web",
        "description": "通过搜索引擎补充采集内容。当 RSS 采集量不足时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索查询词",
                },
                "max_results": {
                    "type": "integer",
                    "description": "最大结果数，默认 5",
                },
            },
            "required": ["query"],
        },
        "fn": _execute_search_web,
        "phase": "collection",
    },
    {
        "name": "enrich_metadata",
        "description": "使用 LLM 对采集条目提取元数据：分类（category）、关键词（keywords）、重要性评分（importance 0-1）。",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "待增强的条目列表",
                },
                "batch_size": {
                    "type": "integer",
                    "description": "每批处理条数，默认 5",
                },
            },
            "required": ["items"],
        },
        "fn": _execute_enrich_metadata,
        "phase": "collection",
    },
    {
        "name": "normalize_items",
        "description": "统一条目字段格式（标题/时间/来源/ID），确保所有条目结构一致。",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "待标准化的条目列表",
                },
            },
            "required": ["items"],
        },
        "fn": _execute_normalize_items,
        "phase": "collection",
    },
    # ---- 排序阶段 ----
    {
        "name": "deduplicate",
        "description": "向量相似度去重：高相似度（≥0.88）直接判重，低相似度（≤0.70）保留，中间区间 LLM 裁决。",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "待去重的条目列表",
                },
                "threshold_high": {
                    "type": "number",
                    "description": "高阈值，≥此值直接判重，默认 0.88",
                },
                "threshold_low": {
                    "type": "number",
                    "description": "低阈值，≤此值保留，默认 0.70",
                },
            },
            "required": ["items"],
        },
        "fn": _execute_deduplicate,
        "phase": "ranking",
    },
    {
        "name": "rank_items",
        "description": "多因子加权排序：综合相似度、时效性、用户偏好、重要性四个维度计算最终排名。",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "待排序的条目列表",
                },
                "user_id": {
                    "type": "integer",
                    "description": "用户 ID，用于读取偏好向量，默认 1",
                },
                "max_items": {
                    "type": "integer",
                    "description": "最多返回条数，默认 10",
                },
            },
            "required": ["items"],
        },
        "fn": _execute_rank_items,
        "phase": "ranking",
    },
    # ---- 简报阶段 ----
    {
        "name": "generate_briefing",
        "description": "根据排序后的条目生成结构化 JSON 简报，包含标题、摘要、分类分组、Markdown 渲染。",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "排序后的条目列表",
                },
                "goal_text": {
                    "type": "string",
                    "description": "用户目标描述",
                },
                "categories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "分类列表，默认 ['科技', '商业', '社会', '其他']",
                },
            },
            "required": ["items"],
        },
        "fn": _execute_generate_briefing,
        "phase": "briefing",
    },
    {
        "name": "quality_check",
        "description": "四维质量审查：完整性（completeness）、相关性（relevance）、一致性（coherence）、综合评分（score）。返回评分及矛盾检测结果。",
        "parameters": {
            "type": "object",
            "properties": {
                "briefing": {
                    "type": "object",
                    "description": "简报 JSON 对象",
                },
                "ranked_items": {
                    "type": "array",
                    "description": "排序后的条目列表",
                },
                "goal_text": {
                    "type": "string",
                    "description": "用户目标描述",
                },
            },
            "required": ["briefing", "ranked_items"],
        },
        "fn": _execute_quality_check,
        "phase": "briefing",
    },
    # ---- 推送 ----
    {
        "name": "push_notification",
        "description": "将简报推送到 Streamlit 前端展示。",
        "parameters": {
            "type": "object",
            "properties": {
                "brief": {
                    "type": "object",
                    "description": "简报内容（含 _markdown 字段）",
                },
                "user_id": {
                    "type": "integer",
                    "description": "用户 ID，默认 1",
                },
                "immediate": {
                    "type": "boolean",
                    "description": "是否立即推送，默认 false",
                },
            },
            "required": ["brief"],
        },
        "fn": _execute_push_notification,
        "phase": "main",
    },
    # ---- 反馈 ----
    {
        "name": "record_feedback",
        "description": "记录用户反馈（like/dislike/irrelevant），并更新偏好向量。",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {
                    "type": "string",
                    "description": "反馈的条目 ID",
                },
                "feedback_type": {
                    "type": "string",
                    "enum": ["like", "dislike", "irrelevant"],
                    "description": "反馈类型",
                },
                "user_id": {
                    "type": "integer",
                    "description": "用户 ID，默认 1",
                },
            },
            "required": ["item_id", "feedback_type"],
        },
        "fn": _execute_record_feedback,
        "phase": "main",
    },
    # ---- 记忆 ----
    {
        "name": "read_memory",
        "description": "读取用户历史决策记忆，包括近期执行记录（SQLite）和语义相似经验（ChromaDB）。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "语义检索查询文本",
                },
                "n_episodic": {
                    "type": "integer",
                    "description": "情节记忆检索条数，默认 10",
                },
                "n_long_term": {
                    "type": "integer",
                    "description": "长期记忆检索条数，默认 3",
                },
                "lookback_days": {
                    "type": "integer",
                    "description": "情节记忆回溯天数，默认 7",
                },
            },
            "required": ["query"],
        },
        "fn": _execute_read_memory,
        "phase": "main",
    },
    {
        "name": "write_memory",
        "description": "将本轮决策经验写入记忆系统（SQLite 情节记忆 + ChromaDB 长期摘要）。",
        "parameters": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "会话 ID",
                },
                "event": {
                    "type": "string",
                    "description": "事件类型，如 planner_decision",
                },
                "node_name": {
                    "type": "string",
                    "description": "节点名称",
                },
                "content": {
                    "type": "object",
                    "description": "决策/执行内容",
                },
                "execution_result": {
                    "type": "object",
                    "description": "执行结果摘要（collected_count, ranked_count, brief_quality 等）",
                },
            },
            "required": ["session_id", "event", "node_name", "content"],
        },
        "fn": _execute_write_memory,
        "phase": "main",
    },
    # ---- 通用结束标记 ----
    {
        "name": "finish_task",
        "description": "标记当前阶段任务完成。必须调用此工具来结束当前阶段的执行，并返回结果摘要。",
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "完成摘要，描述做了什么、结果如何",
                },
                "status": {
                    "type": "string",
                    "enum": ["success", "partial", "failed"],
                    "description": "完成状态",
                },
            },
            "required": ["summary"],
        },
        "fn": lambda args: {"finished": True, "summary": args.get("summary", ""), "status": args.get("status", "success")},
        "phase": "common",
    },
]


# ============================================================
# ToolRegistry
# ============================================================

class ToolRegistry:
    """工具注册表：管理所有工具的 schema 和分发执行。"""

    def __init__(self, tools: list = None):
        self._tools: Dict[str, dict] = {}
        self._schemas: List[dict] = []
        for t in (tools or TOOLS):
            self._tools[t["name"]] = t
            self._schemas.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            })

    def get_schemas(self) -> List[dict]:
        """返回所有工具的 OpenAI function calling schema 列表。"""
        return self._schemas

    def get_schemas_for_phase(self, phase: str) -> List[dict]:
        """返回指定阶段的工具 schema 列表。

        phase: "collection" | "ranking" | "briefing" | "main" | "common"
        其中 "main" 会包含 common 工具，"common" 工具对所有阶段可见。
        """
        names = set()
        for t in self._tools.values():
            t_phase = t.get("phase", "")
            if t_phase == phase or t_phase == "common":
                names.add(t["name"])
        return [s for s in self._schemas if s["function"]["name"] in names]

    def get_schemas_for_phases(self, phases: List[str]) -> List[dict]:
        """返回多个阶段的工具 schema 列表（去重）。"""
        names = set()
        for t in self._tools.values():
            if t.get("phase", "") in phases or t.get("phase", "") == "common":
                names.add(t["name"])
        return [s for s in self._schemas if s["function"]["name"] in names]

    def dispatch(self, tool_name: str, arguments: dict) -> Any:
        """根据 tool_name 执行对应函数。

        Raises:
            KeyError: 工具名不存在时抛出，附带可用工具列表
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            available = list(self._tools.keys())
            raise KeyError(f"工具 '{tool_name}' 不存在。可用工具: {available}")
        return tool["fn"](arguments)

    def get_tool_names(self) -> List[str]:
        """返回所有工具名称。"""
        return list(self._tools.keys())


# ============================================================
# 全局单例
# ============================================================

tool_registry = ToolRegistry()
