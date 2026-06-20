"""
FeedLens 全局状态定义 — FeedLensState TypedDict。

供主 Agent 和所有子 Agent 共享，是 LangGraph StateGraph 的核心数据载体。
"""

from typing import TypedDict, Annotated, Any, Optional
from langgraph.graph.message import add_messages


class FeedLensState(TypedDict, total=False):
    """FeedLens 全局共享状态。

    所有字段均为 Optional，由各节点按需读写。
    """

    # ---- 会话元信息 ----
    session_id: str
    trigger_type: str              # daily_briefing | manual | breaking_news
    user_id: int                   # MVP 固定为 1

    # ---- 用户 Goal ----
    goal_text: str                 # 用户原始 Goal 文本
    structured_goal: dict[str, Any]  # LLM 提取的结构化字段: {topics, keywords, preferred_sources}
    goal_embedding: list[float]    # structured_goal.topics 拼接后的 embedding

    # ---- 主 Agent 编排控制 ----
    messages: Annotated[list, add_messages]
    sub_agent_plan: list[dict[str, Any]]  # planner 输出: [{agent, params, ...}]
    react_cycle_count: int         # 当前 ReAct 循环计数
    current_sub_agent: str         # 当前被调度的子 Agent 名称
    planner_reason: str            # planner 决策理由
    push_immediate: bool           # planner 判断是否需要立即推送

    # ---- 子 Agent 结果 ----
    collected_items: list[dict[str, Any]]    # 采集 Agent 输出
    search_supplemented: bool                # 是否进行了搜索补充
    deduped_items: list[dict[str, Any]]      # 排序 Agent 去重后条目
    item_relations: list[dict[str, Any]]     # 去重关系记录
    ranked_items: list[dict[str, Any]]       # 排序 Agent 排序后条目
    ranking_detail: dict[str, Any]           # 排序详情 (各因子得分)
    briefing_result: dict[str, Any]          # 简报完整结构: {briefing, brief_quality}
    briefing: dict[str, Any]                 # 提取的简报 JSON 内容
    brief_quality: float                     # brief_quality_check 综合评分

    # ---- 观察与审查 ----
    observation_result: dict[str, Any]       # observe_results 输出: {quality_summary, needs_retry, suggested_action}
    coordinator_observation: dict[str, Any]  # coordinator_reflect 综合审查结果

    # ---- 推送 ----
    push_status: str               # pending | sent | failed
    push_message: str

    # ---- 反馈 ----
    feedback_results: list[dict[str, Any]]   # 反馈子 Agent 处理结果

    # ---- 记忆 ----
    short_term_memory: list[dict[str, Any]]  # 最近 15 轮摘要
    execution_log: dict[str, Any]            # 当前执行日志（写入 execution_logs）

    # ---- 错误与状态 ----
    error: Optional[str]
    status: str                    # running | completed | failed
