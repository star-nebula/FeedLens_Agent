# 08 P1 — Briefing 管线深度优化：减少无效重试 + 消除 ReAct 思考

> 基于 2026-06-24 代码全面分析及可行性论证，制定简报管线深度优化方案。
> **核心思路**：取消不可靠的 LLM 自评，通过「生成前硬编码预检 + 分离 coherence + quality 仅评 relevance + 降低重试上限」减少无效 LLM 调用。
> 与 07_向量预过滤 共同构成 v2.1.0 "减少 LLM 冗余调用"的统一目标。

---

## 一、现状分析

### 1.1 当前 Briefing Agent 的 API 调用链

**文件**：`agents/briefing_agent.py`

```
run_briefing_agent() (第510-695行) ReAct 循环:
  Turn 1: LLM思考 → generate_briefing (LLM)
  Turn 2: LLM思考 → quality_check → _llm_assess_quality (LLM)
  Turn 3: (如果 quality < 0.7) LLM思考 → generate_briefing (LLM)
  ...
```

每轮完整 generate+quality 需要 **3 次 LLM API 调用**，重试 3 轮就是 **9 次**。

### 1.2 简报被退回重生成的根本原因分析

质量评分公式：`score = completeness×0.3 + relevance×0.4 + coherence×0.3`

| 因子 | 权重 | 失败模式 | 是否可预判 |
|------|------|---------|-----------|
| **completeness** | 0.3 | 条目数/10 太少 | ✅ **可在生成前预判** |
| **relevance** | 0.4 | LLM 评估条目与目标相关性低 | ⚠️ 不可预判（需 LLM 评估） |
| **coherence** | 0.3 | 时间差>7天 / 重要性差>3 / URL相同 | ✅ **可在生成前预判并修复** |

**关键发现**：completeness + coherence 合占 60% 权重，都可以在生成前通过硬编码规则处理。

### 1.3 核心问题

| 问题 | 浪费的 API |
|------|-----------|
| coherence 扣分可在生成前修复 | 多 1 次/轮（因 coherence 导致的重试） |
| completeness 可在生成前预判 | 浪费的重试轮次 |
| ReAct 思考浪费（流程是确定性的） | 多 1 次/轮 |
| 重试上限偏高（3次→边际改善） | 可能浪费 1 轮 |

---

## 二、优化方案

### 核心思路：生成前消除可控扣分因素 → 减少重试需求 → 消除 ReAct 思考

**放弃的路径**：❌ LLM 在同一响应中自评质量（存在利益冲突，LLM 倾向于给自己打高分）

**选择的路径**：
1. **生成前硬编码预检**：在传入 LLM 之前消除 completeness 和 coherence 的扣分因素
2. **分离 coherence 到生成前**：URL 去重、时间跨度标注等移到 prompt 构建阶段
3. **quality_check 仅评估 relevance**：coherence 不再需要 LLM 参与，且 quality LLM 仅首次调用（后续重试复用缓存）
4. **降低重试上限**：3→2 次（因可控扣分因素已消除）
5. **消除 ReAct 思考**：确定性流程由代码层直接控制

### 新流程对比

```
旧流程 (每轮):
  ReAct LLM思考 → generate_briefing (LLM) → ReAct LLM思考 → quality_check (LLM)
  = 3 次 API/轮, 最多重试3次

新流程 (每轮):
  _preflight_for_briefing (硬编码, 0次LLM)
  → generate_briefing (LLM) → 自动评估 (硬编码, quality LLM仅首次)
  = 1 次 API/轮, 最多重试2次

一次成功: 2次LLM (generate + quality)
重试2次:  4次LLM (generate×3 + quality×1)
```

### 方案 A：生成前硬编码预检（减少可控扣分）

在 `generate_briefing_node` 调用前，对 `ranked_items` 做预检和预处理：

1. **URL 完全相同的条目 → 合并为一条**（保留 importance 更高的）
2. **时间跨度 > 7 天 → 在 prompt 中注入警告**，让 LLM 按时间分组
3. **条目数量检查 → 返回警告**（如仅 N 条，completeness 最多 N/10）
4. **过滤明显低质条目**（_score < 0.15 或无标题）

### 方案 B：分离 coherence 检查到生成前

`_check_contradiction` 的三条规则移到 `_preflight_for_briefing` 中执行：
- URL 相同 → 已在预检中合并
- 时间差 > 7 天 → 已在预检中生成警告
- 重要性差 > 3 → 预检不处理（重要性来自 ranking，属于正常排序结果）

`brief_quality_check_node` 不再执行规则检测，coherence 仅基于 LLM 返回的事实矛盾计算。

### 方案 C：quality_check 仅评估 relevance + 缓存复用

- relevance 仍由独立的 `_llm_assess_quality` LLM 调用评估
- **仅在首次生成后调用** quality LLM（后续重试复用首次评分）
- 如果 relevance < 0.5，在重试 prompt 中给 LLM 反馈

### 方案 D：消除 ReAct 思考 + 降低重试上限

- ReAct 循环改为确定性流程：预检 → 生成 → 评估 → 自动决策
- 重试上限从 3 次降为 2 次
- System Prompt 简化：移除 quality_check 工具引用

---

## 三、详细改动清单

### 3.1 `agents/briefing_agent.py` — 新增 `_preflight_for_briefing()` 函数

**位置**：新增，插入在 `_format_importance()` 之后（第 224 行附近）

```python
def _preflight_for_briefing(ranked_items: list, max_items: int = 10) -> dict:
    """简报生成前预检：消除可控扣分因素。

    处理：
    1. 过滤低质条目（_score < 0.15 或无标题）
    2. URL 相同 → 合并（保留 importance 更高的）
    3. 时间跨度检查 → 生成警告
    4. 条目数量检查 → 生成警告
    """
    warnings = []
    # 过滤低质
    filtered = []
    for item in ranked_items:
        score = item.get("_score", item.get("final_score", 0))
        title = (item.get("title", "") or "").strip()
        if score < 0.15 or len(title) < 3:
            continue
        filtered.append(item)

    # URL 去重合并
    seen_urls = {}
    deduped = []
    for item in filtered:
        url = item.get("url", "")
        if url and url in seen_urls:
            existing = seen_urls[url]
            if item.get("importance", 0) > existing.get("importance", 0):
                deduped[deduped.index(existing)] = item
                seen_urls[url] = item
        else:
            if url: seen_urls[url] = item
            deduped.append(item)

    # 时间跨度
    from datetime import datetime
    times = []
    for item in deduped:
        t = item.get("published_at", "")
        if t:
            try:
                times.append(datetime.fromisoformat(t.replace("Z", "+00:00")))
            except Exception: pass
    if len(times) >= 2 and (max(times) - min(times)).days > 7:
        warnings.append({"type": "large_time_span",
                         "detail": f"跨度{(max(times)-min(times)).days}天，建议按时间分组"})

    # 条目数量
    if len(deduped) < 5:
        warnings.append({"type": "too_few_items",
                         "detail": f"仅{len(deduped)}条，completeness最多{len(deduped)/max_items:.2f}"})

    dropped = len(ranked_items) - len(deduped)
    if dropped > 0:
        print(f"[preflight_briefing] 预检丢弃/合并 {dropped} 条", flush=True)

    return {"items": deduped[:max_items * 2], "warnings": warnings}
```

### 3.2 `agents/briefing_agent.py` — 修改 `generate_briefing_node()`

**位置**：第 368-420 行

**改动**：生成前调用 `_preflight_for_briefing`，prompt 保持不变（**不要求 LLM 自评质量**）。

```python
def generate_briefing_node(state: FeedLensState) -> dict:
    ranked_items = state.get("ranked_items", [])
    goal_text = state.get("goal_text", "用户关注热点新闻")
    categories = state.get("categories", DEFAULT_CATEGORIES)
    retry_count = state.get("briefing_result", {}).get("retry_count", 0)

    # P1-08: 生成前硬编码预检
    preflight = _preflight_for_briefing(ranked_items)
    ranked_items = preflight["items"]
    preflight_warnings = preflight["warnings"]

    print(f"[generate_briefing] 第 {retry_count + 1} 次生成，预检后条目数: {len(ranked_items)}", flush=True)

    if not ranked_items:
        # 空简报处理不变
        ...

    items_to_show = ranked_items[:MAX_ITEMS_PER_BRIEFING]
    grouped = _group_by_category(items_to_show, categories)
    prompt = _build_briefing_prompt(grouped, goal_text, categories)

    # 注入预检警告到 prompt
    if preflight_warnings:
        warn_text = "\n".join(f"- {w['type']}: {w['detail']}" for w in preflight_warnings)
        prompt += f"\n\n## 预检警告（请关注）\n{warn_text}"

    try:
        llm = _get_llm_provider()
        response = llm.chat([{"role": "user", "content": prompt}])
        response_text = response.get("content", "{}") if isinstance(response, dict) else str(response)
    except Exception as e:
        print(f"[generate_briefing] LLM 调用失败: {e}", flush=True)
        response_text = "{}"

    briefing = _parse_json_response(response_text)
    # ... 回填、渲染逻辑不变 ...

    return {
        "briefing": briefing,
        "briefing_result": {
            "briefing": briefing, "brief_quality": 0.0,
            "retry_count": retry_count,
            "_preflight_warnings": preflight_warnings,
        },
    }
```

### 3.3 `agents/briefing_agent.py` — 修改 `brief_quality_check_node()`

**位置**：第 423-480 行

**改动**：
1. coherence 规则检测移到生成前，此处仅基于 LLM 返回的矛盾计算分数
2. relevance 仍由独立 `_llm_assess_quality` LLM 调用评估
3. **仅在首次生成后调用** quality LLM（后续重试复用缓存）

```python
def brief_quality_check_node(state: FeedLensState) -> dict:
    briefing = state.get("briefing", {})
    ranked_items = state.get("ranked_items", [])
    goal_text = state.get("goal_text", "")
    briefing_result = state.get("briefing_result", {})

    quality_detail = {"completeness": 0.0, "relevance": 0.0,
                      "coherence": 0.0, "score": 0.0, "contradictions": []}

    # completeness: 硬编码计算（不变）
    categories = briefing.get("categories", [])
    total_items_in_brief = sum(len(cat.get("items", [])) for cat in categories)
    effective_max = min(len(ranked_items), MAX_ITEMS_PER_BRIEFING)
    completeness = min(1.0, total_items_in_brief / max(1, effective_max))
    quality_detail["completeness"] = completeness

    # relevance: 独立 LLM 评估（仅首次调用，后续复用缓存）
    all_items = []
    for cat in categories:
        all_items.extend(cat.get("items", []))

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

    # coherence: 仅基于 LLM 返回的矛盾（规则检测已在生成前处理）
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

    print(f"[brief_quality_check] score={score:.4f} "
          f"(c={completeness:.2f}, r={relevance:.2f}, h={coherence:.2f})", flush=True)
    return {"brief_quality": score, "quality_detail": quality_detail, "briefing_result": briefing_result}
```

### 3.4 `agents/briefing_agent.py` — 修改 ReAct 循环

**改动 1**：`BRIEFING_SYSTEM_PROMPT` 移除 `quality_check` 工具引用

```python
BRIEFING_SYSTEM_PROMPT = """你是 FeedLens 的简报 Agent。你的目标是根据排序结果生成高质量信息简报。

可用工具：
- generate_briefing: 根据排序条目生成结构化 JSON 简报
- finish_task: 标记简报生成完成

工作流程：
1. 调用 generate_briefing 生成简报（系统会自动评估质量）
2. 如果系统反馈质量达标，调用 finish_task 结束
3. 如果系统反馈需要重试，重新调用 generate_briefing（最多重试 2 次），然后直接 finish_task

重要规则：
- 简报中每条条目必须保留完整 id（从输入中复制），不要自己编造 id
- 系统会自动判断质量，你只需要按照指令生成和结束
- 最多调用 3 次 generate_briefing（含首次），达到上限后直接 finish_task"""
```

**改动 2**：`run_briefing_agent()` 中 generate_briefing 调用后增加自动评估+自动重试

```python
if tool_name == "generate_briefing":
    generate_count += 1
    briefing = result.get("briefing", {})
    briefing_result = result.get("briefing_result", {})
    current_state["briefing"] = briefing
    current_state["briefing_result"] = briefing_result

    # P1-08: 生成后自动执行质量评估（硬编码，不经过 LLM 思考）
    current_state["ranked_items"] = ranked_items
    current_state["goal_text"] = goal_text
    quality_result = brief_quality_check_node(current_state)
    brief_quality = quality_result.get("brief_quality", 0.0)
    current_state["brief_quality"] = brief_quality
    current_state["quality_detail"] = quality_result.get("quality_detail", {})

    if brief_quality >= 0.7:
        return {
            "briefing": briefing, "brief_quality": brief_quality,
            "quality_detail": quality_result.get("quality_detail", {}),
            "briefing_result": current_state.get("briefing_result", {}),
            "briefing_summary": f"质量达标({brief_quality:.4f})，自动完成",
            "briefing_timing": timing,
        }

    if generate_count >= 3:
        return {
            "briefing": briefing, "brief_quality": brief_quality,
            "quality_detail": quality_result.get("quality_detail", {}),
            "briefing_result": current_state.get("briefing_result", {}),
            "briefing_summary": f"已达最大重试次数({generate_count})，强制收敛",
            "briefing_timing": timing,
        }

    # 自动重试
    print(f"[briefing_react] 质量不达标 ({brief_quality:.4f})，自动重试", flush=True)
    messages.append(message)
    messages.append({"role": "tool", "tool_call_id": tc.get("id", tool_name),
                     "content": json.dumps(result, ensure_ascii=False, default=str)})
    messages.append({"role": "user",
                     "content": f"上次质量评分 {brief_quality:.4f} < 0.7，请重新生成，注意提高相关性。"})
    continue
```

**同时删除**：`quality_check` 工具处理分支。

### 3.5 `tools/tool_registry.py` — 移除 briefing 阶段的 quality_check

**改动**：将 `quality_check` 的 phase 从 `"briefing"` 改为 `"briefing_legacy"`

**不改**：保留 `_execute_quality_check` 函数，`brief_quality_check_node` 内部直接调用 `_llm_assess_quality`。

### 3.6 `config/config.yaml` — 新增配置项

```yaml
ranking:
  # ... 现有配置不变 ...
  briefing_prescreen_min_score: 0.15  # P1-08: 预筛最低分数
  briefing_max_retries: 2             # P1-08: 最大重试次数（从3降为2）
```

---

## 四、不改的部分

| 不改 | 原因 |
|------|------|
| `_check_contradiction()` 函数 | 保留但调用位置从 quality_check 移到 _preflight_for_briefing |
| `_llm_assess_quality()` 函数 | 保留，仍用于 relevance 评估（首次调用） |
| `_render_markdown()` / `_backfill_briefing_items()` | 不调 LLM |
| `_parse_json_response()` / `MAX_ITEMS_PER_BRIEFING` | 逻辑不变 |
| `agents/main_agent.py` / `agents/ranking_agent.py` | 主 Agent 和排序逻辑无感知 |
| `generate_count` 硬限制（03 优化） | 保留，作为双重兜底 |

---

## 五、防 bug 验证

### 5.1 场景矩阵

| 场景 | 预期行为 | 风险 |
|------|---------|------|
| **正常：首次生成 quality >= 0.7** | 1次 generate + 1次 quality LLM，自动完成 | 低 |
| **重试：首次 quality < 0.7** | 自动重试 generate（复用缓存 relevance），最多重试2次 | 低 |
| **预检：URL 重复条目** | 合并为一条（保留 importance 更高的） | 低 |
| **预检：全部条目 score < 0.15** | ranked_items 变空 → 返回空简报 | 中（需确保空简报被正确处理） |
| **预检：时间跨度 > 7天** | prompt 中注入警告，LLM 按时间分组 | 低 |
| **预检：条目 < 5 条** | prompt 中注入警告，completeness 自然降低 | 低 |
| **硬限制：generate_count >= 3** | 强制完成 | 低（03 优化已验证） |

### 5.2 回归验证清单

1. ✅ Pipeline 模式下正常生成简报，质量评分无显著下降
2. ✅ 生成前预检正确过滤低质条目和 URL 重复
3. ✅ quality LLM 仅首次调用，后续重试复用缓存
4. ✅ 质量达标自动完成，不经过 LLM 思考
5. ✅ 质量不达标自动重试，最多 2 次
6. ✅ `generate_count` 硬限制仍然生效

---

## 六、预估效果

### 6.1 API 调用次数对比

| 指标 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| 每轮 ReAct 思考 | 1-2 次 | 0 次 | **-100%** |
| 每轮 quality LLM | 1 次（每次重试都调） | 0-1 次（仅首次） | **-50~100%** |
| 最大重试次数 | 3 次 | 2 次 | **-33%** |
| **一次成功** | **3 次** | **2 次** | **-33%** |
| **重试 2 次** | **7 次** | **4 次** | **-43%** |

### 6.2 整体管线（含方案 A）

| 指标 | 当前（v2.0） | A+B 叠加 | 改善 |
|------|------------|---------|------|
| 单次执行 LLM API 调用 | ≤12 次 | ≤6-8 次 | **-33~50%** |
| Briefing 阶段 API | 3-6 次 | 2-4 次 | **-33~50%** |
| Briefing ReAct 思考 | 2-4 次 | 0 次 | **-100%** |
| 单次执行耗时 | ≤3 分钟 | ≤2 分钟 | **-33%** |
| 最终质量 | ≥0.7 | ≥0.7 | 不变 |

---

## 七、实施顺序

```
Step 1: config/config.yaml          ← 新增 briefing_prescreen_min_score + briefing_max_retries
Step 2: agents/briefing_agent.py    ← 新增 _preflight_for_briefing() +
                                        修改 generate_briefing_node (调用预检, 注入警告) +
                                        修改 brief_quality_check_node (coherence规则移到预检, relevance缓存复用) +
                                        修改 BRIEFING_SYSTEM_PROMPT (移除quality_check) +
                                        修改 run_briefing_agent (自动评估+自动重试, 移除quality_check分支)
Step 3: tools/tool_registry.py      ← quality_check phase 改为 briefing_legacy
Step 4: 运行手动触发验证             ← 确认新模式正常
```

---

## 八、与已有优化的关系

| 已有优化 | 编号 | 关系 |
|---------|------|------|
| completeness 分母修正 | 03 | **互补**：03 修复公式，08 减少重试需求 |
| generate_count 硬限制 | 03 | **叠加**：08 保留硬限制作为双重兜底 |
| Planner/Router 规则化 | 04 | **互补**：04 减少主 Agent LLM，08 减少子 Agent LLM |
| Collection pipeline | 05 | **互补**：05 减少采集 LLM，08 减少简报 LLM |
| thinking_mode 关闭 | 06 | **互补**：06 修复稳定性，08 减少调用次数 |
| 向量预过滤去重 | 07 | **互补**：07 减少 Ranking 输入量，08 减少 Briefing 重试 |

---

## 九、风险与回退

1. **relevance 缓存复用风险**：重试时复用首次 relevance 评分，如果重试生成的简报条目顺序变了，relevance 可能不准确。但 relevance 是整体平均分，重试主要调整简报结构而非条目内容，影响可控。

2. **生成前预检可能过于激进**：URL 去重合并可能丢失有价值的同源报道。通过保留 importance 更高的条目来缓解。

3. **回退策略**：保留 `quality_check` 函数实现（phase 改为 `briefing_legacy`），可通过 tool_registry 恢复旧行为。

4. **重试上限降低风险**：从 3 降为 2，极端情况下可能少一次重试机会。但生成前预检消除了可控扣分因素，实际需要重试的场景已大幅减少。
