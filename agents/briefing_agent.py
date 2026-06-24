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


_BACKFILL_FIELDS = ["published_at", "source", "url", "importance", "category", "final_score"]


def _backfill_briefing_items(briefing: Dict[str, Any], item_index: Dict[str, Dict[str, Any]]) -> None:
    for cat_group in briefing.get("categories", []):
        for item in cat_group.get("items", []):
            item_id = item.get("id", "")
            orig = item_index.get(item_id)
            if not orig:
                continue
            for field in _BACKFILL_FIELDS:
                # ranking_agent 输出字段是 _score，映射到 final_score
                orig_field = "_score" if field == "final_score" else field
                orig_val = orig.get(orig_field)
                if orig_val not in (None, "", []):
                    cur = item.get(field)
                    if cur in (None, "", []):
                        item[field] = orig_val
                    else:
                        # BUG-001: published_at 也需强制覆盖（LLM 可能生成不准确的日期）
                        if isinstance(orig_val, (int, float)) or field in ("source", "url", "published_at"):
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
    """将简报渲染为统一 Markdown 格式，分类标题 + 条目信息在同一个文本块内。

    输出格式示例：
        # 派早报：英特尔将为苹果代工芯片
        > 英特尔将为苹果代工芯片...

        ## 数据安全与隐私 (1条)
        **Meta因数据安全问题暂停追踪员工鼠标活动的AI训练项目**
        摘要: Meta暂停用于AI训练的内部数据追踪项目。
        链接: https://...
        - 来源: 36氪 | 时间: 2026-06-21 23:13:00 | 重要性: 4/5 | 评分: 0.344
        还有 3 篇类似报道:
        - xxx
        - xxx
    """
    lines = [f"# {briefing.get('title', '简报')}", ""]
    summary = briefing.get('summary', '')
    if summary:
        lines.append(f"> {summary}")
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
        # 主条目标题（粗体）
        lines.append(f"**{main_item.get('title', '')}**")
        lines.append("")
        # 摘要
        item_summary = main_item.get('summary', '')
        if item_summary:
            lines.append(f"摘要: {item_summary}")
            lines.append("")
        # 链接
        url = main_item.get("url", "")
        if url:
            lines.append(f"链接: {url}")
            lines.append("")
        # 元信息行：- 来源 | 时间 | 重要性 | 评分
        meta_parts = []
        meta_parts.append(f"来源: {main_item.get('source', 'unknown')}")
        pub_time = _format_datetime(main_item.get('published_at', ''))
        meta_parts.append(f"时间: {pub_time}" if pub_time else "时间: 未知")
        meta_parts.append(f"重要性: {_format_importance(main_item.get('importance', 0.5))}")
        score = main_item.get('final_score') or main_item.get('score')
        if score is not None:
            try:
                score_val = float(score)
                meta_parts.append(f"评分: {score_val:.3f}")
            except (TypeError, ValueError):
                pass
        lines.append(f"- {' | '.join(meta_parts)}")
        lines.append("")
        # 类似报道（加冒号）
        similar_count = main_item.get("similar_count", 0)
        if similar_count > 0:
            lines.append(f"还有 {similar_count} 篇类似报道:")
        # 子条目标题列表（全部展开）
        if len(items) > 1:
            for item in items[1:]:
                title = item.get('title', '')
                if title:
                    lines.append(f"- {title}")
        if similar_count > 0 or len(items) > 1:
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


def _preflight_for_briefing(ranked_items: list, max_items: int = 10, min_score: float = 0.15) -> dict:
    """简报生成前硬编码预检：消除可控扣分因素（无 LLM 调用）。

    处理：
    1. 过滤低质条目（_score < min_score 或无标题）
    2. URL 完全相同的条目 → 合并（保留 importance 更高的）
    3. 时间跨度 > 7 天 → 生成警告
    4. 条目数量 < 5 → 生成警告

    Args:
        ranked_items: 排序后的条目列表
        max_items: 简报最多展示条目数（用于 completeness 预判）
        min_score: 最低分数阈值

    Returns:
        {"items": 预处理后的条目列表, "warnings": 警告列表, "dropped": 丢弃数}
    """
    warnings = []
    if not ranked_items:
        return {"items": [], "warnings": [], "dropped": 0}

    # 1. 过滤低质条目
    filtered = []
    for item in ranked_items:
        score = item.get("_score", item.get("final_score", 0))
        title = (item.get("title", "") or "").strip()
        if score < min_score or len(title) < 3:
            continue
        filtered.append(item)

    # 2. URL 去重合并（保留 importance 更高的）
    seen_urls = {}  # url -> item
    deduped = []
    for item in filtered:
        url = item.get("url", "")
        if url and url in seen_urls:
            existing = seen_urls[url]
            if item.get("importance", 0) > existing.get("importance", 0):
                # 替换已有条目
                idx = deduped.index(existing)
                deduped[idx] = item
                seen_urls[url] = item
        else:
            if url:
                seen_urls[url] = item
            deduped.append(item)

    # 3. 时间跨度检查
    from datetime import datetime as dt_module
    times = []
    for item in deduped:
        t = item.get("published_at", "")
        if t:
            try:
                times.append(dt_module.fromisoformat(t.replace("Z", "+00:00")))
            except Exception:
                pass
    if len(times) >= 2 and (max(times) - min(times)).days > 7:
        span_days = (max(times) - min(times)).days
        warnings.append({
            "type": "large_time_span",
            "detail": f"条目时间跨度 {span_days} 天，建议按时间分组"
        })

    # 4. 条目数量检查
    if len(deduped) < 5:
        warnings.append({
            "type": "too_few_items",
            "detail": f"仅 {len(deduped)} 条有效条目，completeness 最多 {len(deduped) / max(max_items, 1):.2f}"
        })

    dropped = len(ranked_items) - len(deduped)
    if dropped > 0:
        print(f"[preflight_briefing] 预检丢弃/合并 {dropped} 条 "
              f"({len(ranked_items)}→{len(deduped)})", flush=True)

    return {"items": deduped[:max_items * 2], "warnings": warnings, "dropped": dropped}


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

    # P1-08: 生成前硬编码预检
    config = load_config()
    prescreen_min_score = config.get("ranking", {}).get("briefing_prescreen_min_score", 0.15)
    preflight = _preflight_for_briefing(ranked_items, max_items=MAX_ITEMS_PER_BRIEFING,
                                        min_score=prescreen_min_score)
    ranked_items = preflight["items"]
    preflight_warnings = preflight["warnings"]

    print(f"[generate_briefing] 第 {retry_count + 1} 次生成，预检后条目数: {len(ranked_items)}", flush=True)

    if not ranked_items:
        empty_briefing = {
            "title": "暂无内容", "summary": "当前没有符合条件的新闻条目",
            "categories": [], "generated_at": "",
        }
        return {
            "briefing": empty_briefing,
            "briefing_result": {"briefing": empty_briefing, "brief_quality": 1.0, "retry_count": retry_count,
                                "_preflight_warnings": preflight_warnings},
        }
    items_to_show = ranked_items[:MAX_ITEMS_PER_BRIEFING]
    grouped = _group_by_category(items_to_show, categories)
    prompt = _build_briefing_prompt(grouped, goal_text, categories)

    # P1-08: 注入预检警告到 prompt
    if preflight_warnings:
        warn_text = "\n".join(f"- [{w['type']}] {w['detail']}" for w in preflight_warnings)
        prompt += f"\n\n## ⚠️ 预检警告（请关注）\n{warn_text}\n"

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
        "briefing_result": {"briefing": briefing, "brief_quality": 0.0, "retry_count": retry_count,
                            "_preflight_warnings": preflight_warnings},
    }


def brief_quality_check_node(state: FeedLensState) -> dict:
    """简报质量审查（P1-08: coherence 规则检测已移到预检阶段）。

    评分公式不变：score = completeness×0.3 + relevance×0.4 + coherence×0.3

    关键变更：
    - coherence 仅基于 LLM 返回的事实矛盾计算（URL/时间/重要性规则已移至预检）
    - relevance 独立 LLM 评估仅首次调用，后续重试复用缓存
    """
    briefing = state.get("briefing", {})
    ranked_items = state.get("ranked_items", [])
    goal_text = state.get("goal_text", "")
    briefing_result = state.get("briefing_result", {})

    quality_detail = {"completeness": 0.0, "relevance": 0.0, "coherence": 0.0, "score": 0.0, "contradictions": []}

    # completeness: 硬编码计算（不变）
    categories = briefing.get("categories", [])
    total_items_in_brief = sum(len(cat.get("items", [])) for cat in categories)
    effective_max = min(len(ranked_items), 10)
    completeness = min(1.0, total_items_in_brief / max(1, effective_max))
    quality_detail["completeness"] = completeness

    all_items = []
    for cat in categories:
        all_items.extend(cat.get("items", []))

    # relevance: 独立 LLM 评估（仅首次调用，后续复用缓存）
    cached_relevance = briefing_result.get("_cached_relevance")
    if cached_relevance is not None:
        relevance = cached_relevance
        print(f"[brief_quality_check] 复用缓存 relevance: {relevance:.4f}", flush=True)
    elif all_items and goal_text:
        try:
            llm = _get_llm_provider()
            relevance_scores, llm_contradictions_raw = _llm_assess_quality(all_items, goal_text, llm)
            if relevance_scores:
                relevance = sum(relevance_scores) / len(relevance_scores)
            else:
                relevance = 0.5
            # 缓存 relevance 供后续重试复用
            briefing_result["_cached_relevance"] = relevance
            # 处理 LLM 返回的矛盾
            for c in llm_contradictions_raw:
                quality_detail["contradictions"].append({
                    "item_a": c.get("item_a", ""),
                    "item_b": c.get("item_b", ""),
                    "reason": c.get("reason", "LLM detected"),
                })
        except Exception as e:
            print(f"[brief_quality_check] LLM relevance 失败: {e}", flush=True)
            relevance = 0.5
    else:
        relevance = 0.5
    relevance = min(1.0, max(0.0, relevance))
    quality_detail["relevance"] = relevance

    # coherence: 仅基于 LLM 返回的事实矛盾（规则检测已在预检阶段处理）
    # P1-08: _check_contradiction 的 URL/时间/重要性规则不再在此执行
    contradictions = quality_detail["contradictions"]
    if len(contradictions) == 0:
        coherence = 1.0
    elif len(contradictions) <= 2:
        coherence = 0.7
    else:
        coherence = 0.3
    quality_detail["coherence"] = coherence

    score = (completeness * 0.3 + relevance * 0.4 + coherence * 0.3)
    quality_detail["score"] = score

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
- finish_task: 标记简报生成完成

工作流程（严格按顺序执行）：
1. 调用 generate_briefing 生成简报（系统会自动评估质量并反馈）
2. 如果系统反馈质量达标，调用 finish_task 结束
3. 如果系统反馈需要重试，重新调用 generate_briefing（最多重试 2 次），然后直接 finish_task

重要规则：
- 简报中每条条目必须保留完整 id（从输入中复制），不要自己编造 id
- 系统会自动判断质量，你只需要按照指令生成和结束
- 整个流程最多调用 3 次 generate_briefing（含首次），达到上限后直接 finish_task
- 完成后必须调用 finish_task，不要无限循环优化"""


# ============================================================
# ReAct 简报函数
# ============================================================

def run_briefing_agent(state: FeedLensState) -> dict:
    """ReAct 简报 Agent — 生成后自动评估+自动重试（P1-08: 消除 ReAct 思考）。

    核心变更：
    - 移除 quality_check 工具：生成后代码层自动调用 brief_quality_check_node
    - relevance 缓存复用：仅在首次生成后调用 quality LLM
    - 重试上限从 3 降为 2（可控扣分因素已在预检中消除）
    - max_turns 从 5 降为 4（单轮 2 步 generate→finish_task，2次重试=3轮 generate）

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

    # 读取配置
    config = load_config()
    max_retries = config.get("ranking", {}).get("briefing_max_retries", 2)

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

    max_turns = 4  # P1-08: 从 5 降为 4（2次重试最多3轮 generate，每轮 generate 后 finish_task）
    generate_count = 0  # 硬限制 generate_briefing 调用次数
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
                # P1-08: 移除 quality_check 工具分支（改为代码层自动评估）

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
                    briefing_result = result.get("briefing_result", {})
                    current_state["briefing"] = briefing
                    current_state["briefing_result"] = briefing_result

                    # P1-08: 生成后自动执行质量评估（代码层直接调用，不经过 LLM 思考）
                    current_state["ranked_items"] = ranked_items
                    current_state["goal_text"] = goal_text
                    quality_result = brief_quality_check_node(current_state)
                    brief_quality = quality_result.get("brief_quality", 0.0)
                    current_state["brief_quality"] = brief_quality
                    current_state["quality_detail"] = quality_result.get("quality_detail", {})
                    # 将 _cached_relevance 合并回 briefing_result 供后续重试复用
                    updated_briefing_result = quality_result.get("briefing_result", {})
                    current_state["briefing_result"] = updated_briefing_result

                    # 判断质量是否达标
                    if brief_quality >= 0.7:
                        t_turn_total = time.perf_counter() - t_turn_start
                        print(f"[briefing_react] 质量达标 ({brief_quality:.4f})，自动完成", flush=True)
                        messages.append(message)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", tool_name),
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })
                        t_agent_elapsed = time.perf_counter() - t_agent_start
                        print(f"[briefing_react] ⏱️ 简报 Agent 总耗时: {t_agent_elapsed:.2f}s, "
                              f"ReAct 轮数: {turn + 1}, generate 次数: {generate_count}, timing={timing}", flush=True)
                        return {
                            "briefing": briefing,
                            "brief_quality": brief_quality,
                            "quality_detail": current_state.get("quality_detail", {}),
                            "briefing_result": updated_briefing_result,
                            "briefing_summary": f"质量达标({brief_quality:.4f})，自动完成",
                            "briefing_timing": timing,
                        }

                    # P1-08: 重试上限检查（max_retries，从 3 降为 2）
                    if generate_count > max_retries:
                        t_agent_elapsed = time.perf_counter() - t_agent_start
                        print(f"[briefing_react] generate_briefing 已达 {generate_count} 次（上限 {max_retries}），"
                              f"强制 finish（质量={brief_quality:.4f}）", flush=True)
                        print(f"[briefing_react] ⏱️ 简报 Agent 总耗时: {t_agent_elapsed:.2f}s, "
                              f"ReAct 轮数: {turn + 1}, timing={timing}", flush=True)
                        return {
                            "briefing": briefing,
                            "brief_quality": brief_quality,
                            "quality_detail": current_state.get("quality_detail", {}),
                            "briefing_result": updated_briefing_result,
                            "briefing_summary": f"已达最大重试次数({generate_count})，强制收敛",
                            "briefing_timing": timing,
                        }

                    # 自动重试：注入质量反馈
                    print(f"[briefing_react] 质量不达标 ({brief_quality:.4f})，自动重试 "
                          f"({generate_count}/{max_retries})", flush=True)
                    messages.append(message)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", tool_name),
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                    # 注入重试提示（包含质量反馈）
                    retry_msg = (f"上次质量评分 {brief_quality:.4f} < 0.7，请重新生成简报。"
                                 f"注意提高与用户目标「{goal_text}」的相关性。")
                    messages.append({"role": "user", "content": retry_msg})
                    continue

                elif tool_name == "finish_task":
                    summary = result.get("summary", "")
                    t_turn_total = time.perf_counter() - t_turn_start
                    print(f"[briefing_react] 简报完成: quality={brief_quality:.4f}, "
                          f"本轮耗时={t_turn_total:.2f}s", flush=True)
                    messages.append(message)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", tool_name),
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    })
                    t_agent_elapsed = time.perf_counter() - t_agent_start
                    print(f"[briefing_react] ⏱️ 简报 Agent 总耗时: {t_agent_elapsed:.2f}s, "
                          f"ReAct 轮数: {turn + 1}, timing={timing}", flush=True)
                    return {
                        "briefing": briefing,
                        "brief_quality": brief_quality,
                        "quality_detail": current_state.get("quality_detail", {}),
                        "briefing_result": current_state.get("briefing_result", {}),
                        "briefing_summary": summary,
                        "briefing_timing": timing,
                    }

                # 其他工具（兜底）
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
            # tool_choice="required" 下极少出现，但保留一次重试作为兜底
            if content and turn < 1:
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
