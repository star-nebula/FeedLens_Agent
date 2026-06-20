"""
简报 Agent — 简报生成 + 质量审查（线性流程，无 ReAct）。

工作流: generate_briefing → brief_quality_check → (retry? → generate_briefing) → Done
"""

import json
import re
import os
from typing import List, Dict, Any
from langgraph.graph import StateGraph, END
from utils.config import load_config
from agents.state import FeedLensState
from utils.llm_provider import DeepSeekProvider


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
# 辅助函数
# ============================================================

def _get_llm_provider() -> DeepSeekProvider:
    """获取 LLM Provider，从 config.yaml 读取配置。"""
    config = load_config()
    llm_cfg = config.get("llm", {})
    deepseek_cfg = llm_cfg.get("deepseek", {})
    api_key = deepseek_cfg.get("api_key", "")
    model = deepseek_cfg.get("model", "deepseek-chat")
    base_url = deepseek_cfg.get("base_url", "https://api.deepseek.com/v1")
    return DeepSeekProvider(api_key=api_key, model=model, base_url=base_url)

def _group_by_category(items: List[Dict], categories: List[str]) -> Dict[str, List[Dict]]:
    """将条目按 category 分组，组内按 importance 降序。"""
    grouped = {cat: [] for cat in categories}
    grouped["其他"] = []

    for item in items:
        item_cat = item.get("category", "其他")
        if item_cat not in categories:
            item_cat = "其他"
        grouped[item_cat].append(item)

    # 组内按 importance 降序
    for cat in grouped:
        grouped[cat].sort(key=lambda x: x.get("importance", 0), reverse=True)

    return grouped


def _build_briefing_prompt(
    grouped: Dict[str, List[Dict]],
    goal_text: str,
    categories: List[str],
) -> str:
    """构建简报生成的 LLM prompt。"""
    # 构造 items 文本
    items_text = []
    for cat in categories:
        cat_items = grouped.get(cat, [])
        if not cat_items:
            continue
        items_text.append(f"\n## {cat}（共{len(cat_items)}条）")
        for i, item in enumerate(cat_items[:5]):  # 每类最多5条详细展示
            items_text.append(
                f"- [{item.get('id', f'item_{i}')}] {item.get('title', '')}\n"
                f"  摘要: {item.get('summary', '')[:100]}\n"
                f"  来源: {item.get('source', 'unknown')} | "
                f"重要性: {item.get('importance', 3)}/5"
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


def _parse_json_response(text: str) -> Dict[str, Any]:
    """从 LLM 输出中解析 JSON 简报。"""
    # 尝试提取 ```json ... ``` 或直接 JSON
    json_match = re.search(r'\{[\s\S]*\}', text)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"error": f"JSON 解析失败: {text[:200]}"}


def _render_markdown(briefing: Dict[str, Any]) -> str:
    """将简报 JSON 渲染为 Markdown。"""
    lines = [f"# {briefing.get('title', '简报')}", ""]
    lines.append(f"> {briefing.get('summary', '')}", )
    lines.append("")

    for cat in briefing.get("categories", []):
        cat_name = cat.get("name", "未分类")
        items = cat.get("items", [])
        count = cat.get("count", len(items))

        if not items:
            continue

        lines.append(f"## {cat_name} ({count}条)")
        lines.append("")

        # 主条目
        main_item = items[0]
        lines.append(f"### {main_item.get('title', '')}")
        lines.append("")
        lines.append(f"**摘要**: {main_item.get('summary', '')}")
        lines.append("")
        lines.append(
            f"- 来源: {main_item.get('source', 'unknown')} | "
            f"时间: {main_item.get('published_at', '')} | "
            f"重要性: {main_item.get('importance', 3)}/5"
        )
        lines.append("")

        # 类似报道计数
        similar_count = main_item.get("similar_count", 0)
        if similar_count > 0:
            lines.append(f"> 还有 {similar_count} 篇类似报道")
            lines.append("")

        # 其他条目列表
        if len(items) > 1:
            lines.append("**其他报道:**")
            for item in items[1:]:
                lines.append(f"- {item.get('title', '')}")
            lines.append("")

    lines.append(f"\n---\n*生成时间: {briefing.get('generated_at', '')}*")
    return "\n".join(lines)


def _check_contradiction(item1: Dict, item2: Dict) -> bool:
    """P1: 增强矛盾检测。
    
    检测规则：
    1. 时间矛盾：发布时间差 > 7 天
    2. 重要性矛盾：重要性差 > 3
    3. 类别矛盾：同标题跨类别出现
    4. 来源重复：同 URL 多次出现
    """
    # 1. 时间矛盾
    t1 = item1.get("published_at", "")
    t2 = item2.get("published_at", "")
    if t1 and t2:
        try:
            from datetime import datetime
            d1 = datetime.fromisoformat(t1.replace("Z", "+00:00"))
            d2 = datetime.fromisoformat(t2.replace("Z", "+00:00"))
            diff = abs((d1 - d2).total_seconds())
            if diff > 7 * 24 * 3600:
                return True
        except Exception:
            pass
    # 2. 重要性差异过大
    imp1 = item1.get("importance", 3)
    imp2 = item2.get("importance", 3)
    if abs(imp1 - imp2) > 3:
        return True
    # 3. P1: 来源重复检测（同 URL）
    url1 = item1.get("url", "")
    url2 = item2.get("url", "")
    if url1 and url2 and url1 == url2:
        return True
    # 4. P1: 标题相似检测
    title1 = item1.get("title", "")
    title2 = item2.get("title", "")
    if title1 and title2:
        # 简单相似度：共同词比例
        words1 = set(title1)
        words2 = set(title2)
        if words1 and words2:
            overlap = len(words1 & words2) / min(len(words1), len(words2))
            if overlap > 0.8:
                return True
    return False


# ============================================================
# 节点定义
# ============================================================


def generate_briefing_node(state: FeedLensState) -> dict:
    """LLM 生成结构化 JSON 简报。

    按 category 分组，组内按 importance 降序，标注「还有 N 篇类似报道」。

    Returns:
        briefing_result: {briefing, brief_quality, retry_count}
        briefing: 提取的简报 JSON
    """
    ranked_items = state.get("ranked_items", [])
    goal_text = state.get("goal_text", "用户关注热点新闻")
    categories = state.get("categories", DEFAULT_CATEGORIES)

    retry_count = state.get("briefing_result", {}).get("retry_count", 0)
    print(f"[generate_briefing] 第 {retry_count + 1} 次生成，简报条目数: {len(ranked_items)}", flush=True)

    if not ranked_items:
        # 无条目时返回空简报
        empty_briefing = {
            "title": "暂无内容",
            "summary": "当前没有符合条件的新闻条目",
            "categories": [],
            "generated_at": "",
        }
        return {
            "briefing": empty_briefing,
            "briefing_result": {"briefing": empty_briefing, "brief_quality": 1.0, "retry_count": retry_count},
        }

    # 取前 N 条
    items_to_show = ranked_items[:MAX_ITEMS_PER_BRIEFING]

    # 按 category 分组
    grouped = _group_by_category(items_to_show, categories)

    # 构建 LLM prompt
    prompt = _build_briefing_prompt(grouped, goal_text, categories)

    # 调用 LLM
    try:
        llm = _get_llm_provider()
        response = llm.chat([{"role": "user", "content": prompt}])
        response_text = response.get("content", "{}") if isinstance(response, dict) else str(response)
    except Exception as e:
        print(f"[generate_briefing] LLM 调用失败: {e}", flush=True)
        response_text = "{}"

    # 解析 JSON
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
            "title": "简报生成",
            "summary": f"生成了 {len(items_to_show)} 条重要新闻",
            "categories": fallback_categories,
            "generated_at": "",
        }

    # 补充 similar_count（类似报道数量）
    for cat_group in briefing.get("categories", []):
        cat_items = cat_group.get("items", [])
        if cat_items:
            # 第一条是主条目，similar_count = 剩余数量
            cat_name = cat_group.get("name", "")
            total_in_cat = len(grouped.get(cat_name, []))
            cat_items[0]["similar_count"] = max(0, total_in_cat - 1)

    # 渲染 Markdown
    markdown = _render_markdown(briefing)
    briefing["_markdown"] = markdown

    print(f"[generate_briefing] 完成: {briefing.get('title', 'untitled')}", flush=True)

    return {
        "briefing": briefing,
        "briefing_result": {
            "briefing": briefing,
            "brief_quality": 0.0,
            "retry_count": retry_count,
        },
    }


def brief_quality_check_node(state: FeedLensState) -> dict:
    """四维评分 (completeness / relevance / coherence / score) + 矛盾检查。

    Returns:
        brief_quality: float (综合评分)
        quality_detail: {completeness, relevance, coherence, contradictions}
    """
    briefing = state.get("briefing", {})
    ranked_items = state.get("ranked_items", [])
    goal_text = state.get("goal_text", "")

    quality_detail = {
        "completeness": 0.0,
        "relevance": 0.0,
        "coherence": 0.0,
        "score": 0.0,
        "contradictions": [],
    }

    # 1. completeness 检查
    categories = briefing.get("categories", [])
    total_items_in_brief = sum(len(cat.get("items", [])) for cat in categories)
    completeness = min(1.0, total_items_in_brief / max(1, len(ranked_items)))
    quality_detail["completeness"] = completeness

    # 2. relevance 检查（与用户目标的相关性）
    # 优先使用 structured_goal 中的关键词（LLM 提取），其次回退到简单分词
    structured_goal = state.get("structured_goal", {})
    keywords = structured_goal.get("keywords", [])
    if not keywords and goal_text:
        keywords = [w for w in re.split(r'[,，\s]+', goal_text) if len(w) >= 2]
    relevance = 0.5
    if keywords and categories:
        matched = 0
        total = 0
        for cat in categories:
            for item in cat.get("items", []):
                title = item.get("title", "")
                if any(kw in title for kw in keywords):
                    matched += 1
                total += 1
        if total > 0:
            relevance = matched / total
    quality_detail["relevance"] = relevance

    # 3. coherence 检查（矛盾检测）
    contradictions = []
    all_items = []
    for cat in categories:
        for item in cat.get("items", []):
            all_items.append(item)

    # 两两检查矛盾
    for i in range(len(all_items)):
        for j in range(i + 1, len(all_items)):
            if _check_contradiction(all_items[i], all_items[j]):
                contradictions.append({
                    "item_a": all_items[i].get("id", ""),
                    "item_b": all_items[j].get("id", ""),
                })

    # 无矛盾得 1.0，有矛盾但不多得 0.7，过多得 0.3
    if len(contradictions) == 0:
        coherence = 1.0
    elif len(contradictions) <= 2:
        coherence = 0.7
    else:
        coherence = 0.3
    quality_detail["coherence"] = coherence
    quality_detail["contradictions"] = contradictions

    # 4. 综合评分
    score = (completeness * 0.3 + relevance * 0.4 + coherence * 0.3)
    quality_detail["score"] = score

    # 更新 briefing_result
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

    return {
        "brief_quality": score,
        "quality_detail": quality_detail,
        "briefing_result": briefing_result,
    }


# ============================================================
# 条件边
# ============================================================


def should_retry_brief(state: FeedLensState) -> str:
    """判断是否需要重试简报生成。

    brief_quality < 0.7 且 retry < 2 → 重试，否则 Done。
    """
    quality = state.get("brief_quality", 0.0)
    retry_count = 0
    briefing_result = state.get("briefing_result", {})
    retry_count = briefing_result.get("retry_count", 0)

    if quality < 0.7 and retry_count < 2:
        # 更新重试计数
        briefing_result["retry_count"] = retry_count + 1
        print(f"[should_retry_brief] 质量 {quality:.4f} < 0.7，第 {retry_count + 1} 次重试", flush=True)
        return "generate_briefing"
    return END


# ============================================================
# StateGraph 构建
# ============================================================


def build_briefing_agent() -> StateGraph:
    """构建简报 Agent StateGraph。"""
    workflow = StateGraph(FeedLensState)

    workflow.add_node("generate_briefing", generate_briefing_node)
    workflow.add_node("brief_quality_check", brief_quality_check_node)

    workflow.set_entry_point("generate_briefing")
    workflow.add_edge("generate_briefing", "brief_quality_check")

    # 条件边: 质量不达标 → 重试
    workflow.add_conditional_edges(
        "brief_quality_check",
        should_retry_brief,
        {"generate_briefing": "generate_briefing", "__end__": END},
    )

    return workflow.compile()



