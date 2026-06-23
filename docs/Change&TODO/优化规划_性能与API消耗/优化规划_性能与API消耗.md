# FeedLens Agent 性能与 API 消耗优化规划

> 基于 2026-06-23 手动触发执行日志的全面分析，制定系统化优化方案。

---

## 一、现状回顾

| 指标 | 当前值 | 目标值 |
|------|--------|--------|
| 单次执行耗时 | ~8分36秒 | ≤3分钟 |
| LLM API 调用次数 | ~35+次 | ≤12次 |
| ReAct 循环轮数 | 3轮 | ≤1轮（理想） |
| API 浪费占比 | ~65% | ≤20% |
| 最终质量 | 0.746 | ≥0.7 |

---

## 二、优化方案（按优先级排列）

### 2.1 P0 — enrich_metadata 批量处理优化

**问题描述**：当前 `batch_size=5`，每条新闻单独调 LLM 提取 category/keywords/importance，62 条新闻产生 13 次 API 调用，占总调用量近一半。

**涉及文件**：
- `tools/fc_tools.py:158-205` — `enrich_metadata()` 函数
- `agents/collection_agent.py:204-211` — Collection Agent 调用 enrich_metadata

**优化方案**：

| 方案 | 改动内容 | 预期效果 |
|------|---------|---------|
| **A. 增大 batch_size** | `batch_size=5` → `batch_size=20`（62 条只需 4 批） | API 调用 -69%，耗时 -60% |
| **B. 改为可选调用** | 新增配置项 `enrich_metadata.enabled: false`，默认跳过，仅当 `ranking.weights_cold.importance > 0` 时启用 | API 调用 -100%（该项），质量几乎无影响 |
| **C. 合并 prompt** | 单次 prompt 处理全部条目（一次性返回 JSON 数组），利用 DeepSeek 的长上下文 | API 调用 -92%（62 条仅 1 次） |

**推荐**：**A + B 组合** — 默认关闭 enrich_metadata，仅在 warm start（用户有反馈历史，importance 权重 > 0）时启用且 batch_size=20。

**配置变更**（`config/config.yaml`）：
```yaml
# 新增
enrich_metadata:
  enabled: false              # 默认关闭，冷启动阶段 importance 贡献极小
  batch_size: 20              # 启用时的批次大小
  max_items: 30               # 单次最多处理的条目数
```

**代码变更**：
- `tools/fc_tools.py:161` — `batch_size` 默认值改为 20
- `agents/collection_agent.py` — ReAct prompt 中移除 `enrich_metadata` 的必要性引导，改为"可选"
- `config/config.yaml` — 新增 `enrich_metadata` 配置段

**预估节省**：~17 次 API 调用，~2 分钟耗时

---

### 2.2 P0 — observe_results 判断逻辑优化（避免不必要重跑）

**问题描述**：第 0 轮采集了 62 条，但经 7 天预筛后仅剩 1 条（top_score=0.25），observe 判定"采集不足"导致第 1 轮重跑完整三板斧。实际上 RSS 源没变，重跑得到的内容几乎相同，纯属浪费。

**涉及文件**：
- `agents/main_agent.py:1077-1122` — `_default_observe_evaluate()` hook
- `agents/main_agent.py:707-749` — `observe_results_node()`

**优化方案**：

| 方案 | 改动内容 | 预期效果 |
|------|---------|---------|
| **A. 区分"采集不足"与"预筛过严"** | 当 `len(collected) >= 10` 但 `len(ranked) < 3` 时，不判定为"采集不足"，而是判定为"预筛过严"，suggested_action 改为 `expand_threshold`（放宽时间窗口），而非重跑 Collection | 避免一整轮无效重跑 |
| **B. 缩短默认预筛窗口** | `config.yaml` 新增 `ranking.prescreen_hours: 72`（当前硬编码 168=7天），缩短至 3 天 | 首轮排序即有足够条目 |
| **C. 增加重试上限约束** | 同一 trigger 的 ReAct 轮数上限从 8 降到 3（`router_node` 的 `max_turns`） | 快速收敛，减少无效轮次 |

**推荐**：**A + B + C 组合**。

**代码变更**：
1. `agents/main_agent.py:1085-1110` — 在 `_default_observe_evaluate()` 中新增"采集充足但排序不足"的判断分支：
   ```python
   # 新增：采集充足但排序后不足 → 预筛过严，应放宽时间窗口而非重采集
   collected_ok_but_ranked_insufficient = (
       len(collected) >= th_coll and len(ranked) < th_coll
   )
   if collected_ok_but_ranked_insufficient:
       issues.append(f"预筛过严: 采集{len(collected)}条但排序仅剩{len(ranked)}条")
       suggested_action = "expand_threshold"  # 不再 suggest "search_expand"
   ```
2. `config/config.yaml` 新增 `ranking.prescreen_hours: 72`
3. `agents/main_agent.py:555` — `max_turns` 从 8 改为 5（或从 config 读取）

**预估节省**：一整轮 ReAct（~4 分钟 + ~15 次 API 调用）

---

### 2.3 P1 — Briefing Agent 质量检查与重试策略优化

**问题描述**：quality_check 的 completeness 维度在条目数少时永远达不到 1.0，导致 0.686 分仍重试（浪费 2 次 generate_briefing + 2 次 quality_check），但重试无法改变 completeness。

**涉及文件**：
- `agents/briefing_agent.py:377-439` — `_quality_check()` 函数（completeness 计算公式）
- `agents/briefing_agent.py:446-462` — `BRIEFING_SYSTEM_PROMPT`（重试引导）
- `agents/briefing_agent.py:469-600` — `run_briefing_agent()` ReAct 循环

**优化方案**：

| 方案 | 改动内容 | 预期效果 |
|------|---------|---------|
| **A. 放宽 completeness 计算** | 当 `ranked_items <= 10` 时，completeness 不苛求 =1.0，改为 `min(1.0, total_items_in_brief / min(len(ranked_items), 10))` | 少量条目时不再因 completeness 卡死 |
| **B. 降低接受阈值** | `threshold_briefing` 从 0.7 降为 0.65（或从 config 读取） | 0.686 直接通过，省掉后续重试 |
| **C. 限制重试次数** | System prompt 已写"最多重试 2 次"但 LLM 实际执行了 3 次，在代码层加硬限制：`generate_briefing` 调用次数 ≥ 3 时强制 finish_task | 防止 LLM 不遵守 prompt 约束 |

**推荐**：**A + C 组合**（不改阈值，优化公式 + 硬限制）。

**代码变更**：
1. `agents/briefing_agent.py:387-392` — completeness 计算逻辑优化：
   ```python
   # 优化：当条目数少时不苛求 completeness=1.0
   total_ranked = len(ranked_items)
   effective_max = min(total_ranked, 10)
   completeness = min(1.0, total_items_in_brief / effective_max) if effective_max > 0 else 0.0
   ```
2. `agents/briefing_agent.py:512-515` — ReAct 循环中加入 `generate_count` 计数，达到 3 次时跳过 LLM 思考直接 finish_task

**预估节省**：每轮最多省 4 次 API 调用（2 × generate + 2 × quality_check），高频场景节省显著

---

### 2.4 P1 — Planner/Router 规则化降级

**问题描述**：每次 planner 和 router 都调 LLM 决策，但很多场景可以用规则判断（如"刚执行完三板斧 → 直接 observe"），当前日志中 planner(3) + router(6) = 9 次不必要的 LLM 调用。

**涉及文件**：
- `agents/main_agent.py:249-305` — `planner_node()`
- `agents/main_agent.py:445-609` — `router_node()` + `_fallback_router_decision()`

**优化方案**：

| 方案 | 改动内容 | 预期效果 |
|------|---------|---------|
| **A. router 优先规则判断** | 在 `router_node()` 中，将 `_fallback_router_decision()` 的逻辑提升为优先规则（先规则、后 LLM），而非仅 LLM 失败时降级 | router LLM 调用减少 60%+ |
| **B. planner 缓存决策** | 同一 trigger 的 planner 决策缓存到 state，第 N 轮不再调 LLM，直接复用第 N-1 轮的修正版 | planner LLM 调用减少 50%+ |
| **C. 合并 understand_intent** | `understand_intent` 的输出直接传给 planner，而非单独调一次 LLM | 节省 1 次 API 调用 |

**推荐**：**A + C 组合**（B 风险较高，暂缓）。

**代码变更**：
1. `agents/main_agent.py:580-587` — `router_node()` 中先调用 `_fallback_router_decision(state)` 做规则判断，若规则能明确决策（confidence=high）则跳过 LLM：
   ```python
   # 优先规则路由
   rule_decision = _fallback_router_decision(state)
   rule_node = rule_decision.get("next_node", "")
   if rule_node and rule_node != "planner":  # planner 需要 LLM 编排，不能规则化
       print(f"[router] 规则决策: {json.dumps(rule_decision, ensure_ascii=False)}", flush=True)
       decision = rule_decision
   else:
       # 规则无法决策时才调 LLM
       ...
   ```
2. `agents/main_agent.py` — `understand_intent` 的意图结果合并到 planner 的输入 context，减少一次独立 LLM 调用

**预估节省**：~4 次 API 调用

---

### 2.5 P2 — Collection Agent 流程固定化（Pipeline 替代 ReAct）

**问题描述**：Collection Agent 的流程实际是固定的（fetch_rss → [enrich_metadata] → normalize_items → finish_task），但每轮仍需 LLM 做 4-5 次"思考→决策调哪个工具"。

**涉及文件**：
- `agents/collection_agent.py:114-258` — `run_collection_agent()` ReAct 循环

**优化方案**：

| 方案 | 改动内容 | 预期效果 |
|------|---------|---------|
| **A. 固定流水线** | Collection Agent 不经过 LLM ReAct，直接顺序执行 fetch_rss → normalize_items → finish_task（enrich 按配置可选），仅当 fetch_rss 返回 < 3 条时才调 LLM 决定是否 search_web | 每轮省 3-4 次 API 调用 |
| **B. 保留 ReAct 但减少 max_turns** | `max_turns` 从 5 降为 3 | 快速收敛，减少无效思考轮次 |

**推荐**：**A 方案**（风险低，Collection 流程确实是确定的）。

**代码变更**：
- `agents/collection_agent.py` — 新增 `run_collection_pipeline()` 函数（无 LLM 的固定流程），`build_collection_agent()` 根据配置选择 pipeline 或 ReAct 模式
- `config/config.yaml` 新增 `agents.collection_mode: pipeline`

**预估节省**：每轮省 3-4 次 API 调用

---

### 2.6 P2 — 预筛窗口可配置化

> **状态：✅ 已在 2.2 优化中附带完成（2026-06-23）**
>
> 实施 P0-2.2「observe_results 判断逻辑优化」时，为解决"采集 62 条 → 预筛 7 天 → 仅剩 1 条"问题，顺带完成了本项的两个方案：
> - **方案 A（配置化）**：`config.yaml` 新增 `ranking.prescreen_hours: 72`，`rank_items_node()` 从 config 读取（`agents/ranking_agent.py:226`）
> - **方案 B（动态调整）**：observe 判定 `prescreen_too_strict` 时注入 `expand_threshold=True`，rank_items 自动放宽到 336h/14 天（`agents/ranking_agent.py:227`）
>
> 无需额外实施。

**问题描述**：当前 `rank_items` 的预筛窗口硬编码为 7 天（168 小时），第 0 轮 62 条 → 1 条就是因为多数条目超过 7 天被丢弃。

**涉及文件**：
- ~~`tools/fc_tools.py`~~ → 实际改动在 `agents/ranking_agent.py` 的 `rank_items_node()`（预筛逻辑所在位置）
- `config/config.yaml` — `ranking` 配置段

**优化方案**：

| 方案 | 改动内容 | 预期效果 | 状态 |
|------|---------|---------|------|
| **A. 配置化预筛窗口** | `config.yaml` 新增 `ranking.prescreen_hours: 72`，rank_items 从 config 读取 | 首轮排序保留更多条目 | ✅ 已完成 |
| **B. 动态调整窗口** | observe 发现排序不足时，planner 传递 `expand_threshold` 参数，rank_items 动态放宽窗口 | 第 N 轮自动扩容，无需重采集 | ✅ 已完成 |

**推荐**：**A + B 组合**（均已完成）。

**配置变更**（`config/config.yaml`）：
```yaml
ranking:
  prescreen_hours: 72          # 新增：预筛时间窗口（小时），默认 72=3天
```

**代码变更**（已在 2.2 中完成）：
- `agents/ranking_agent.py:226` — `rank_items_node()` 中 `prescreen_hours` 从 config 读取，默认 72h
- `agents/ranking_agent.py:227` — `expand_threshold` 模式自动放宽到 336h（14 天）
- `config/config.yaml:48` — 新增 `prescreen_hours: 72`

---

## 三、实施计划

### 第一阶段（预计节省 ~60% API + ~50% 耗时）

| 序号 | 任务 | 涉及文件 | 优先级 | 预计工作量 |
|------|------|---------|--------|-----------|
| 1 | enrich_metadata 默认关闭 + batch_size=20 | `tools/fc_tools.py`, `config/config.yaml`, `agents/collection_agent.py` | P0 | 0.5h |
| 2 | observe 区分"采集不足"与"预筛过严" | `agents/main_agent.py:1077-1122` | P0 | 1h |
| 3 | 预筛窗口配置化 (prescreen_hours) | `agents/ranking_agent.py`, `config/config.yaml` | P2→提前 ✅ 已随2.2完成 | 0.5h |
| 4 | max_turns 收紧 (8→5) | `agents/main_agent.py:555` | P0 | 0.25h |

### 第二阶段（预计再节省 ~20% API + ~20% 耗时）

| 序号 | 任务 | 涉及文件 | 优先级 | 预计工作量 |
|------|------|---------|--------|-----------|
| 5 | Briefing quality_check completeness 公式优化 | `agents/briefing_agent.py:387-392` | P1 | 0.5h |
| 6 | Briefing generate_briefing 硬限制（≤3次） | `agents/briefing_agent.py:512-515` | P1 | 0.5h |
| 7 | router 规则优先判断 | `agents/main_agent.py:580-587` | P1 | 1h |

### 第三阶段（可选优化）

| 序号 | 任务 | 涉及文件 | 优先级 | 预计工作量 |
|------|------|---------|--------|-----------|
| 8 | Collection Agent 固定流水线模式 | `agents/collection_agent.py`, `config/config.yaml` | P2 | 2h |
| 9 | understand_intent 合并到 planner context | `agents/main_agent.py` | P2 | 0.5h |

---

## 四、预期效果

| 指标 | 优化前 | 优化后（预期） | 改善幅度 |
|------|--------|---------------|---------|
| 单次执行耗时 | ~8分36秒 | ≤3分钟 | **-65%** |
| LLM API 调用次数 | ~35+次 | ≤12次 | **-66%** |
| ReAct 循环轮数 | 3轮 | 1-2轮 | **-50%** |
| enrich_metadata API 调用 | 17次 | 0次（默认关闭） | **-100%** |
| 无效重跑轮次 | 1.5轮 | 0轮 | **-100%** |

---

## 五、风险与注意事项

1. **enrich_metadata 关闭影响**：冷启动阶段 importance 权重仅 0.25，且 ranking 主要依赖向量相似度（0.40）和时效性（0.25），关闭 enrich_metadata 对排序质量影响极小（< 0.05 分差）。当用户有足够反馈后（warm start），可重新启用。

2. **预筛窗口缩短风险**：从 7 天缩到 3 天可能导致旧闻混入简报，但配合 deduplicate + rank_items 的时效衰减机制，旧闻得分天然偏低，实际影响可控。

3. **max_turns 收紧风险**：从 8 降到 5，极端情况下可能过早收敛。建议保留 `coordinator_reflect` 的兜底逻辑（超轮数时先审查再结束）。

4. **Collection Pipeline 风险**：如果 RSS 源异常（全部失败），固定流水线缺少 LLM 的 search_web 补充决策。建议保留 `fetch_rss 返回 < 3 条 → 调 LLM 决策` 的 fallback。

5. **回归测试**：每个阶段完成后运行 `scripts/test_main_agent.py` 确认无回归，并手动触发一次验证端到端流程。
