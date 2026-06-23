"""
简报 Agent — ReAct 循环实现（Agentic 升级规划2 Phase 3c）。

从 StateGraph 改为轻量 ReAct 循环：
  LLM Thought → function_call → Observation → ... → finish_task

工具列表: generate_briefing, quality_check, finish_task
简报 Agent 只能在这两个工具之间迭代，不允许调到采集/排序工具。
"""

import json
import re
import os
import time
from datetime import datetime
from typing import List, Dict, Any

from langgraph.graph import StateGraph, END
from utils.config import load_config
from agents.state import FeedLensState
from utils.llm_provider import DeepSeekProvider
from tools.tool_registry import tool_registry


# ============================================================
# 配置
# ============================================================

MAX_ITEMS_PER_BRIEFING = 10
DEFAULT_CATEGORIES = ["科技", "商业", "社会", "其他"]


# ============================================================
# JSON Schema
# ============================================================

BRIEFING_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "简报标题"},
        "summary": {"type": "string", "description": "简报摘要，50字以内"},
        "categories": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "summary": {"type": "string"},
                                "source": {"type": "string"},
                                "published_at": {"type": "string"},
                                "importance": {"type": "number"},
                                "similar_count": {"type": "integer"},
                            },
                            "required": ["id", "title", "summary"],
                        },
                    },
                    "count": {"type": "integer"},
                },
                "required": ["name", "items"],
            },
        },
        "generated_at": {"type": "string"},
    },
    "required": ["title", "summary", "categories"],
}


# ============================================================
# 辅助函数（保留原有全部逻辑）
# ============================================================

def _get_llm_provider() -> DeepSeekProvider:
    config = load_config()
    llm_cfg = config.get("llm", {})
    deepseek_cfg = llm_cfg.get("deepseek", {})
    api_key = deepseek_cfg.get("api_key", "")
    model = deepseek_cfg.get("model", "deepseek-chat")
    base_url = deepseek_cfg.get("base_url", "https://api.deepseek.com/v1")
    return DeepSeekProvider(api_key=api_key, model=model, base_url=base_url)


def _group_by_category(items: List[Dict], categories: List[str]) -> Dict[str, List[Dict]]:
    grouped = {cat: [] for cat in categories}
    grouped["其他"] = []
    for item in items:
        item_cat = item.get("category", "其他")
        if item_cat not in categories:
            item_cat = "其他"
        grouped[item_cat].append(item)
    for cat in grouped:
        grouped[cat].sort(key=lambda x: x.get("importance", 0), reverse=True)
    return grouped


def _build_briefing_prompt(grouped: Dict[str, List[Dict]], goal_text: str, categories: List[str]) -> str:
    items_text = []
    for cat in categories:
        cat_items = grouped.get(cat, [])
        if not cat_items:
            continue
        items_text.append(f"\n## {cat}（共{len(cat_items)}条）")
        for i, item in enumerate(cat_items[:5]):
            items_text.append(
                f"- [{item.get('id', f'item_{i}')}] {item.get('title', '')}\n"
                f"  摘要: {item.get('summary', '')[:100]}\n"
                f"  来源: {item.get('source', 'unknown')} | "
                f"  时间: {item.get('published_at', '')} | "
                f"重要性: {_format_importance(item.get('importance', 0.5))}"
            )
        if len(cat_items) > 5:
            items_text.append(f"  还有 {len(cat_items) - 5} 篇类似报道...")
    items_block = "\n".join(items_text) if items_text else "（无条目）"
    prompt = f"""你是一个简报生成助手。根据以下信息生成一份结构化 JSON 简报。

## 用户目标
{goal_text}

## 待处理条目
{items_block}

## 输出要求

## 输出风格: detailed
每条条目保留完整信息（id, title, summary, source, published_at, importance）

1. title：简报标题，简洁有力
2. summary：简报摘要，50字以内
3. categories：按以下分类组织，每类只选最重要的一条作为主条目，其余作为类似报道
4. 每条主条目保留完整信息（id, title, summary, source, published_at, importance）
5. 类似报道只保留 id, title, similar_count（类似报道数量）
6. generated_at：当前时间，ISO 格式

## JSON Schema
{json.dumps(BRIEFING_SCHEMA, ensure_ascii=False, indent=2)}

请直接输出 JSON，不要添加markdown代码块标记。
"""
    return prompt


def _build_item_index(ranked_items: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    index = {}
    for item in ranked_items:
        item_id = item.get("id", "")
        if item_id:
            index[item_id] = item
    return index


_BACKFILL_FIELDS = ["published_at", "source", "url", "importance", "category"]


def _backfill_briefing_items(briefing: Dict[str, Any], item_index: Dict[str, Dict[str, Any]]) -> None:
    for cat_group in briefing.get("categories", []):
        for item in cat_group.get("items", []):
            item_id = item.get("id", "")
            orig = item_index.get(item_id)
            if not orig:
                continue
            for field in _BACKFILL_FIELDS:
                orig_val = orig.get(field)
                if orig_val not in (None, "", []):
                    cur = item.get(field)
                    if cur in (None, "", []):
                        item[field] = orig_val
                    else:
                        if isinstance(orig_val, (int, float)) or field in ("source", "url"):
                            item[field] = orig_val
                elif item.get(field) in (None, "", []):
                    if field == "published_at":
                        item[field] = "未知时间"
                    elif field == "source":
                        item[field] = "unknown"
                    elif field == "importance":
                        item[field] = 3


def _parse_json_response(text: str) -> Dict[str, Any]:
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": f"JSON 解析失败: {text[:200]}"}


def _format_datetime(iso_str: str) -> str:
    if not iso_str:
        return ""
    s = iso_str.strip()
    try:
        normalized = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return s


def _format_importance(raw) -> str:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return "3/5"
    if val <= 1.0:
        score = round(val * 5)
    else:
        score = round(val)
    score = max(1, min(5, int(score)))
    return f"{score}/5"


def _render_markdown(briefing: Dict[str, Any]) -> str:
    lines = [f"# {briefing.get('title', '简报')}", ""]
    lines.append(f"> {briefing.get('summary', '')}")
    lines.append("")
    for cat in briefing.get("categories", []):
        cat_name = cat.get("name", "未分类")
        items = cat.get("items", [])
        count = cat.get("count", len(items))
        if not items:
            continue
        lines.append(f"## {cat_name} ({count}条)")
        lines.append("")
        main_item = items[0]
        lines.append(f"### {main_item.get('title', '')}")
        lines.append("")
        lines.append(f"**摘要**: {main_item.get('summary', '')}")
        lines.append("")
        url = main_item.get("url", "")
        if url:
            lines.append(f"**链接**: {url}")
            lines.append("")
        lines.append(
            f"- 来源: {main_item.get('source', 'unknown')} | "
            f"时间: {_format_datetime(main_item.get('published_at', ''))} | "
            f"重要性: {_format_importance(main_item.get('importance', 0.5))}"
        )
        lines.append("")
        similar_count = main_item.get("similar_count", 0)
        if similar_count > 0:
            lines.append(f"> 还有 {similar_count} 篇类似报道")
            lines.append("")
        if len(items) > 1:
            lines.append("**其他报道:**")
            for item in items[1:]:
                lines.append(f"- {item.get('title', '')}")
            lines.append("")
    lines.append(f"\n---\n*生成时间: {briefing.get('generated_at', '')}*")
    return "\n".join(lines)


def _llm_assess_quality(items: list[dict], goal_text: str, llm: DeepSeekProvider) -> tuple[list[float], list[dict]]:
    items_text = "\n".join(
        f"[{i}] {item.get('title', '')} | {item.get('summary', '')[:300]}"
        for i, item in enumerate(items)
    )
    prompt = f"""评估以下新闻简报的质量，请返回 JSON：

## 用户目标
{goal_text}

## 简报条目
{items_text}

## 评估要求
1. relevance: 每条条目与用户目标的相关性评分（0-1），返回数组
2. contradictions: 是否有条目之间存在事实矛盾（对同一事件的陈述互相冲突），返回冲突对列表

返回格式：
{{"relevance": [0.8, 0.6, ...], "contradictions": [{{"a": 0, "b": 1, "reason": "..."}}]}}

直接输出 JSON，不加代码块标记。"""
    try:
        response = llm.chat([{"role": "user", "content": prompt}])
        text = response if isinstance(response, str) else response.get("content", "{}")
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            result = json.loads(match.group())
        else:
            result = json.loads(text)
        relevance_scores = result.get("relevance", [0.5] * len(items))
        contradictions = [
            {"item_a": items[c["a"]].get("id", ""), "item_b": items[c["b"]].get("id", ""), "reason": c.get("reason", "")}
            for c in result.get("contradictions", [])
            if isinstance(c, dict) and c.get("a", -1) < len(items) and c.get("b", -1) < len(items)
        ]
        return relevance_scores, contradictions
    except Exception as e:
        print(f"[llm_quality] 失败: {e}，使用默认评分", flush=True)
        return [0.5] * len(items), []


def _check_contradiction(item1: Dict, item2: Dict) -> bool:
    t1 = item1.get("published_at", "")
    t2 = item2.get("published_at", "")
    if t1 and t2:
        try:
            d1 = datetime.fromisoformat(t1.replace("Z", "+00:00"))
            d2 = datetime.fromisoformat(t2.replace("Z", "+00:00"))
            diff = abs((d1 - d2).total_seconds())
            if diff > 7 * 24 * 3600:
                return True
        except Exception:
            pass
    imp1 = item1.get("importance", 3)
    imp2 = item2.get("importance", 3)
    if abs(imp1 - imp2) > 3:
        return True
    url1 = item1.get("url", "")
    url2 = item2.get("url", "")
    if url1 and url2 and url1 == url2:
        return True
    return False


# ============================================================
# 保留原有节点函数（供 tool_registry 调用）
# ============================================================

def generate_briefing_node(state: FeedLensState) -> dict:
    ranked_items = state.get("ranked_items", [])
    goal_text = state.get("goal_text", "用户关注热点新闻")
    categories = state.get("categories", DEFAULT_CATEGORIES)
    retry_count = state.get("briefing_result", {}).get("retry_count", 0)
    print(f"[generate_briefing] 第 {retry_count + 1} 次生成，简报条目数: {len(ranked_items)}", flush=True)
    if not ranked_items:
        empty_briefing = {
            "title": "暂无内容", "summary": "当前没有符合条件的新闻条目",
            "categories": [], "generated_at": "",
        }
        return {
            "briefing": empty_briefing,
            "briefing_result": {"briefing": empty_briefing, "brief_quality": 1.0, "retry_count": retry_count},
        }
    items_to_show = ranked_items[:MAX_ITEMS_PER_BRIEFING]
    grouped = _group_by_category(items_to_show, categories)
    prompt = _build_briefing_prompt(grouped, goal_text, categories)
    try:
        llm = _get_llm_provider()
        response = llm.chat([{"role": "user", "content": prompt}])
        response_text = response.get("content", "{}") if isinstance(response, dict) else str(response)
    except Exception as e:
        print(f"[generate_briefing] LLM 调用失败: {e}", flush=True)
        response_text = "{}"
    briefing = _parse_json_response(response_text)
    if "error" in briefing or not briefing.get("title"):
        print(f"[generate_briefing] JSON 解析失败，使用默认简报", flush=True)
        fallback_categories = []
        for cat in categories:
            cat_items = grouped.get(cat, [])
            if cat_items:
                main_item = {**cat_items[0], "similar_count": max(0, len(cat_items) - 1)}
                fallback_categories.append({"name": cat, "items": [main_item]})
        briefing = {
            "title": "简报生成", "summary": f"生成了 {len(items_to_show)} 条重要新闻",
            "categories": fallback_categories, "generated_at": "",
        }
    item_index = _build_item_index(items_to_show)
    _backfill_briefing_items(briefing, item_index)
    for cat_group in briefing.get("categories", []):
        cat_items = cat_group.get("items", [])
        if cat_items:
            cat_name = cat_group.get("name", "")
            total_in_cat = len(grouped.get(cat_name, []))
            cat_items[0]["similar_count"] = max(0, total_in_cat - 1)
    markdown = _render_markdown(briefing)
    briefing["_markdown"] = markdown
    print(f"[generate_briefing] 完成: {briefing.get('title', 'untitled')}", flush=True)
    return {
        "briefing": briefing,
        "briefing_result": {"briefing": briefing, "brief_quality": 0.0, "retry_count": retry_count},
    }


def brief_quality_check_node(state: FeedLensState) -> dict:
    briefing = state.get("briefing", {})
    ranked_items = state.get("ranked_items", [])
    goal_text = state.get("goal_text", "")
    quality_detail = {"completeness": 0.0, "relevance": 0.0, "coherence": 0.0, "score": 0.0, "contradictions": []}
    categories = briefing.get("categories", [])
    total_items_in_brief = sum(len(cat.get("items", [])) for cat in categories)
    # P1-2.3: 分母取 min(len(ranked), 10)，因为 generate_briefing_node 最多取 10 条展示
    # 避免 ranked=62 时 completeness 被压到 0.16 这种无法通过重试提升的困境
    effective_max = min(len(ranked_items), 10)
    completeness = min(1.0, total_items_in_brief / max(1, effective_max))
    quality_detail["completeness"] = completeness
    all_items = []
    for cat in categories:
        all_items.extend(cat.get("items", []))
    llm_scores = []
    llm_contradictions_raw = []
    relevance = 0.5
    if all_items and goal_text:
        try:
            llm = _get_llm_provider()
            relevance_scores, llm_contradictions_raw = _llm_assess_quality(all_items, goal_text, llm)
            if relevance_scores:
                relevance = sum(relevance_scores) / len(relevance_scores)
        except Exception as e:
            print(f"[brief_quality_check] LLM relevance 失败，回退: {e}", flush=True)
    relevance = min(1.0, max(0.0, relevance))
    quality_detail["relevance"] = relevance
    contradictions = []
    for i in range(len(all_items)):
        for j in range(i + 1, len(all_items)):
            if _check_contradiction(all_items[i], all_items[j]):
                contradictions.append({"item_a": all_items[i].get("id", ""), "item_b": all_items[j].get("id", ""), "reason": "detected by rule"})
    for c in llm_contradictions_raw:
        pair = (c["item_a"], c["item_b"])
        if not any((p["item_a"], p["item_b"]) == pair or (p["item_b"], p["item_a"]) == pair for p in contradictions):
            contradictions.append(c)
    if len(contradictions) == 0:
        coherence = 1.0
    elif len(contradictions) <= 2:
        coherence = 0.7
    else:
        coherence = 0.3
    quality_detail["coherence"] = coherence
    quality_detail["contradictions"] = contradictions
    score = (completeness * 0.3 + relevance * 0.4 + coherence * 0.3)
    quality_detail["score"] = score
    briefing_result = state.get("briefing_result", {})
    briefing_result["brief_quality"] = score
    briefing_result["quality_detail"] = quality_detail
    print(
        f"[brief_quality_check] 综合评分: {score:.4f} "
        f"(completeness={completeness:.2f}, relevance={relevance:.2f}, coherence={coherence:.2f})",
        flush=True
    )
    if contradictions:
        print(f"[brief_quality_check] 发现 {len(contradictions)} 个潜在矛盾", flush=True)
    return {"brief_quality": score, "quality_detail": quality_detail, "briefing_result": briefing_result}


# ============================================================
# System Prompt
# ============================================================

BRIEFING_SYSTEM_PROMPT = """你是 FeedLens 的简报 Agent。你的目标是根据排序结果生成高质量信息简报。

可用工具：
- generate_briefing: 根据排序条目生成结构化 JSON 简报
- quality_check: 四维质量审查（完整性、相关性、一致性、综合评分）
- finish_task: 标记简报生成完成

工作流程（严格按顺序执行）：
1. 调用 generate_briefing 生成简报
2. 调用 quality_check 审查质量
3. 如果质量评分 >= 0.7，立即调用 finish_task 结束，不要再生成新简报
4. 如果质量评分 < 0.7，重新调用 generate_briefing（最多重试 2 次），然后直接 finish_task

重要规则：
- quality_check 评分 >= 0.7 时，不要再调用 generate_briefing，直接 finish_task
- 整个流程最多调用 3 次 generate_briefing，达到上限后直接 finish_task
- 完成后必须调用 finish_task，不要无限循环优化"""


# ============================================================
# ReAct 简报函数
# ============================================================

def run_briefing_agent(state: FeedLensState) -> dict:
    """ReAct 简报 Agent — LLM 自主迭代生成+审查直到质量达标。

    Args:
        state: FeedLensState，包含 ranked_items, goal_text 等

    Returns:
        dict: {briefing, brief_quality, quality_detail, briefing_result}
    """
    t_agent_start = time.perf_counter()

    llm = _get_llm_provider()
    tools = tool_registry.get_schemas_for_phase("briefing")

    ranked_items = state.get("ranked_items", [])
    goal_text = state.get("goal_text", "用户关注热点新闻")
    categories = state.get("categories", DEFAULT_CATEGORIES)

    user_msg = f"排序条目数: {len(ranked_items)}\n用户目标: {goal_text}\n分类: {categories}"

    # 注入条目摘要（关键字段，避免 token 爆炸）
    if ranked_items:
        user_msg += "\n\n--- 条目列表（每条仅含关键字段）---\n"
        for i, item in enumerate(ranked_items[:15]):  # 简报最多 10 条，15 条足够
            title = item.get("title", "")[:100]
            source = item.get("source_name", item.get("source_url", item.get("source", "")))[:60]
            pub = item.get("published_at", "")[:19]
            summary = (item.get("summary", "") or item.get("content", ""))[:120]
            item_id = item.get("id", f"item_{i}")
            importance = item.get("importance", item.get("_score", 0.5))
            user_msg += (
                f"[{i}] id={item_id} | title={title} | source={source} | "
                f"time={pub} | importance={importance} | summary={summary}\n"
            )

    messages = [
        {"role": "system", "content": BRIEFING_SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    current_state = dict(state)
    briefing = {}
    brief_quality = 0.0
    quality_detail = {}

    # 耗时统计
    timing = {"llm_calls": [], "tool_calls": []}

    max_turns = 5
    generate_count = 0  # P1-2.3: 硬限制 generate_briefing 调用次数
    for turn in range(max_turns):
        t_turn_start = time.perf_counter()
        print(f"[briefing_react] 第 {turn + 1} 轮思考...", flush=True)

        try:
            t_llm_start = time.perf_counter()
            response_dict = llm.chat_with_tools(messages=messages, tools=tools)
            t_llm_elapsed = time.perf_counter() - t_llm_start
            timing["llm_calls"].append({"turn": turn + 1, "elapsed": round(t_llm_elapsed, 3)})
            print(f"[briefing_react]   └─ LLM 调用耗时: {t_llm_elapsed:.2f}s", flush=True)
        except Exception as e:
            print(f"[briefing_react] LLM 调用失败: {e}，退出循环", flush=True)
            break

        choices = response_dict.get("choices", [])
        if not choices:
            break
        choice = choices[0]
        message = choice.get("message", {})
        finish_reason = choice.get("finish_reason", "")

        tool_calls = message.get("tool_calls", [])
        if tool_calls and finish_reason == "tool_calls":
            for tc in tool_calls:
                func = tc.get("function", {})
                tool_name = func.get("name", "")
                try:
                    tool_args = json.loads(func.get("arguments", "{}"))
                except json.JSONDecodeError:
                    tool_args = {}

                print(f"[briefing_react] 调用工具: {tool_name}", flush=True)

                # 注入参数
                if tool_name == "generate_briefing":
                    if "items" not in tool_args:
                        tool_args["items"] = ranked_items
                    if "goal_text" not in tool_args:
                        tool_args["goal_text"] = goal_text
                    if "categories" not in tool_args:
                        tool_args["categories"] = categories
                elif tool_name == "quality_check":
                    if "briefing" not in tool_args:
                        tool_args["briefing"] = briefing
                    if "ranked_items" not in tool_args:
                        tool_args["ranked_items"] = ranked_items
                    if "goal_text" not in tool_args:
                        tool_args["goal_text"] = goal_text

                t_tool_start = time.perf_counter()
                try:
                    result = tool_registry.dispatch(tool_name, tool_args)
                except Exception as e:
                    result = {"error": str(e)}
                    print(f"[briefing_react] 工具 {tool_name} 失败: {e}", flush=True)
                t_tool_elapsed = time.perf_counter() - t_tool_start
                timing["tool_calls"].append({"turn": turn + 1, "tool": tool_name, "elapsed": round(t_tool_elapsed, 3)})
                print(f"[briefing_react]   └─ 工具 {tool_name} 耗时: {t_tool_elapsed:.2f}s", flush=True)

                if tool_name == "generate_briefing":
                    generate_count += 1
                    briefing = result.get("briefing", {})
                    current_state["briefing"] = briefing
                    current_state["briefing_result"] = result.get("briefing_result", {})
                elif tool_name == "quality_check":
                    brief_quality = result.get("brief_quality", 0.0)
                    quality_detail = result.get("quality_detail", {})
                    current_state["brief_quality"] = brief_quality
                    current_state["quality_detail"] = quality_detail
                elif tool_name == "finish_task":
                    summary = result.get("summary", "")
                    t_turn_total = time.perf_counter() - t_turn_start
                    print(f"[briefing_react] 简报完成: quality={brief_quality:.4f}, 本轮耗时={t_turn_total:.2f}s", flush=True)
                    # 追加 finish_task 调用记录到 messages 历史（保持完整性，便于审计/重放）
                    messages.append(message)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", tool_name),
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                    t_agent_elapsed = time.perf_counter() - t_agent_start
                    print(f"[briefing_react] ⏱️ 简报 Agent 总耗时: {t_agent_elapsed:.2f}s, ReAct 轮数: {turn + 1}, timing={timing}", flush=True)
                    return {
                        "briefing": briefing,
                        "brief_quality": brief_quality,
                        "quality_detail": quality_detail,
                        "briefing_result": current_state.get("briefing_result", {}),
                        "briefing_summary": summary,
                        "briefing_timing": timing,
                    }

                # P1-2.3: 代码层硬限制 generate_briefing 调用次数，防 LLM 不守 prompt 无限重试
                if generate_count >= 3:
                    t_agent_elapsed = time.perf_counter() - t_agent_start
                    print(f"[briefing_react] generate_briefing 已达 {generate_count} 次，强制 finish（质量={brief_quality:.4f}）", flush=True)
                    print(f"[briefing_react] ⏱️ 简报 Agent 总耗时: {t_agent_elapsed:.2f}s, ReAct 轮数: {turn + 1}, timing={timing}", flush=True)
                    return {
                        "briefing": briefing,
                        "brief_quality": brief_quality,
                        "quality_detail": quality_detail,
                        "briefing_result": current_state.get("briefing_result", {}),
                        "briefing_summary": f"已达最大重试次数({generate_count})，强制收敛",
                        "briefing_timing": timing,
                    }

                messages.append(message)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", tool_name),
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

            t_turn_total = time.perf_counter() - t_turn_start
            print(f"[briefing_react] 第 {turn + 1} 轮完成，耗时: {t_turn_total:.2f}s", flush=True)
        else:
            content = message.get("content", "")
            print(f"[briefing_react] LLM 未调用工具，回复: {content[:100]}", flush=True)
            if content and turn < max_turns - 1:
                # 安全处理：清除可能残留的 tool_calls 字段，防止下轮 API 400 错误
                safe_message = {k: v for k, v in message.items() if k != "tool_calls"}
                messages.append(safe_message)
                messages.append({"role": "user", "content": "请调用工具生成简报和审查质量，完成后调用 finish_task。"})
                continue
            break

    t_agent_elapsed = time.perf_counter() - t_agent_start
    print(f"[briefing_react] 超过 {max_turns} 轮未完成，强制返回", flush=True)
    print(f"[briefing_react] ⏱️ 简报 Agent 总耗时: {t_agent_elapsed:.2f}s, timing={timing}", flush=True)
    return {
        "briefing": briefing,
        "brief_quality": brief_quality,
        "quality_detail": quality_detail,
        "briefing_result": current_state.get("briefing_result", {}),
        "briefing_summary": "超时结束",
        "briefing_timing": timing,
    }


# ============================================================
# 兼容接口
# ============================================================

class _ReActAgentWrapper:
    def __init__(self, fn):
        self._fn = fn

    def invoke(self, state: dict) -> dict:
        return self._fn(state)


def build_briefing_agent():
    """构建简报 Agent（兼容旧接口）。"""
    return _ReActAgentWrapper(run_briefing_agent)
