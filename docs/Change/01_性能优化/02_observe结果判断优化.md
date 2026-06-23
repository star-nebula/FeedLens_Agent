# 2.2 P0 — observe_results 判断逻辑优化 实施规划

> 基于 2026-06-23 代码分析，制定详细改动方案。

---

## 一、问题诊断

### 根因分析

第 0 轮：采集 62 条 → 预筛 7 天窗口 → 仅剩 1 条 → top_score=0.25

观察逻辑链路：
```
observe_results_node (main_agent.py:707)
  → _default_observe_evaluate (main_agent.py:1070)
    → ranking_ok = bool(ranked and top_score >= 0.3)  ← 1条+0.25 → False
    → needs_retry = not (collection_ok and ranking_ok and ...)
    → needs_retry = True  ← 触发重跑！
  → router_node 看到 needs_retry=true → 路由到 planner
  → planner 重新编排三板斧（采集+排序+简报）← 浪费！
```

**根因**：`ranking_ok` 的判定只看 `top_score >= 0.3`，但忽略了「条目太少（1条）」这个前置条件——只有 1 条时 top_score 天然低，这是预筛过严导致的，不是排序算法有问题。

### 方案对应关系

| 子方案 | 解决问题 | 改动位置 |
|--------|---------|---------|
| **A. 区分采集不足/预筛过严** | `ranking_ok` 误判导致重跑 | `main_agent.py:1070-1120` |
| **B. 预筛窗口配置化** | 硬编码 168h 太严格 | `ranking_agent.py:224` + `config.yaml` |
| **C. max_turns 收紧** | 8 轮太多，LLM 可无限重试 | `main_agent.py:555` |

---

## 二、改动清单

### 改动 1：`agents/main_agent.py:1070-1120` — `_default_observe_evaluate` 核心修复

**当前代码问题**：
- `ranking_ok` 只看 top_score，不管条目数
- 当条目很少（< 3）且采集已充足时，应判定为"预筛过严"而非"需要重跑"
- `suggested_action` 虽然能输出 `expand_threshold`，但 `needs_retry=True` 已经触发了重跑

**改动逻辑**：
```python
# 新增：采集充足但排序后不足 → 预筛过严
# 此时 ranking_ok 应为 True（不是排序算法问题），不触发重跑
# 转而通过 suggested_action="expand_threshold" 告诉 planner 放宽窗口重排即可
collected_sufficient = len(collected) >= th_coll
ranked_insufficient = len(ranked) < th_coll

# ranking_ok 修正：条目太少时不苛求 top_score（不是排序算法问题）
if ranked_insufficient and collected_sufficient:
    ranking_ok = True  # 不判为排序失败
```

**具体改动**：

在 `_default_observe_evaluate()` 中（第 1075-1120 行），修改判定逻辑：

1. **第 1085-1086 行**：`ranking_ok` 计算前增加"预筛过严"判断
2. **第 1089-1091 行**：`suggest_expand` 和 `needs_retry` 联动修正
3. **第 1093-1110 行**：issues 中明确区分"采集不足"和"预筛过严"

**old_str** (行 1075-1120)：
```
    collected = ctx.get("collected", [])
    ranked = ctx.get("ranked", [])
    top_score = ctx.get("top_score", 0)
    # 简报质量默认 0.0：若 Briefing 从未被调度，不应误判为"质量完美"
    brief_quality = ctx.get("brief_quality", 0.0)
    th_coll = ctx.get("threshold_collection", 3)
    th_rank = ctx.get("threshold_ranking", 0.3)
    th_brief = ctx.get("threshold_briefing", 0.7)
    expected = ctx.get("expected_brief_items", 10)

    collection_ok = len(collected) >= th_coll
    ranking_ok = bool(ranked and top_score >= th_rank)
    # 简报质量评估：需同时检查 brief_quality > 0（是否真正生成）和评分达标
    briefing_ok = brief_quality > 0 and brief_quality >= th_brief
    briefing_count_ok = len(ranked) >= expected
    suggest_expand = (not briefing_count_ok) and (len(collected) >= expected)
    needs_retry = not (collection_ok and ranking_ok and briefing_ok and briefing_count_ok)

    issues = []
    suggested_action = None
    if not collection_ok:
        issues.append(f"采集不足: {len(collected)} 条 < {th_coll}")
        suggested_action = "search_expand"
    if not ranking_ok:
        issues.append(f"排序不佳: top_score={top_score:.2f} < {th_rank}")
    if brief_quality <= 0:
        issues.append("简报未生成")
        suggested_action = suggested_action or "briefing"
    elif not briefing_ok:
        issues.append(f"简报质量低: score={brief_quality:.2f} < {th_brief}")
    if not briefing_count_ok:
        issues.append(f"简报条目不足: {len(ranked)}/{expected}")
        if suggest_expand:
            suggested_action = "expand_threshold"
        elif suggested_action is None:
            suggested_action = "search_expand"
```

**new_str**：
```
    collected = ctx.get("collected", [])
    ranked = ctx.get("ranked", [])
    top_score = ctx.get("top_score", 0)
    # 简报质量默认 0.0：若 Briefing 从未被调度，不应误判为"质量完美"
    brief_quality = ctx.get("brief_quality", 0.0)
    th_coll = ctx.get("threshold_collection", 3)
    th_rank = ctx.get("threshold_ranking", 0.3)
    th_brief = ctx.get("threshold_briefing", 0.7)
    expected = ctx.get("expected_brief_items", 10)

    collection_ok = len(collected) >= th_coll

    # P0 优化：区分「排序算法失败」和「预筛过严导致条目不足」
    # 当采集充足(>=th_coll)但排序后不足(<th_coll)时，是预筛窗口过严，
    # 不应判为 ranking_ok=False（会触发完整重跑），而是放宽窗口重新排序即可
    prescreen_too_strict = (
        collection_ok and len(ranked) < th_coll
    )
    if prescreen_too_strict:
        ranking_ok = True  # 不判为排序失败，避免触发不必要的完整重跑
    else:
        ranking_ok = bool(ranked and top_score >= th_rank)

    # 简报质量评估：需同时检查 brief_quality > 0（是否真正生成）和评分达标
    briefing_ok = brief_quality > 0 and brief_quality >= th_brief
    briefing_count_ok = len(ranked) >= expected
    # P0 优化：采集充足但排序不足 → 应 expand_threshold 而非 search_expand
    suggest_expand = collection_ok and not briefing_count_ok
    needs_retry = not (collection_ok and ranking_ok and briefing_ok and briefing_count_ok)

    issues = []
    suggested_action = None
    if not collection_ok:
        issues.append(f"采集不足: {len(collected)} 条 < {th_coll}")
        suggested_action = "search_expand"
    if prescreen_too_strict:
        issues.append(f"预筛过严: 采集{len(collected)}条但排序仅剩{len(ranked)}条")
        suggested_action = "expand_threshold"
    elif not ranking_ok:
        issues.append(f"排序不佳: top_score={top_score:.2f} < {th_rank}")
    if brief_quality <= 0:
        issues.append("简报未生成")
        suggested_action = suggested_action or "briefing"
    elif not briefing_ok:
        issues.append(f"简报质量低: score={brief_quality:.2f} < {th_brief}")
    if not briefing_count_ok:
        issues.append(f"简报条目不足: {len(ranked)}/{expected}")
        if suggest_expand and suggested_action is None:
            suggested_action = "expand_threshold"
        elif suggested_action is None:
            suggested_action = "search_expand"
```

> **注意**：`suggest_expand` 条件从 `(not briefing_count_ok) and (len(collected) >= expected)` 简化为 `collection_ok and not briefing_count_ok`，因为只要采集够了，排序不足就应该 expand 而非重新采集。

---

### 改动 2：`agents/ranking_agent.py:224` — 预筛窗口从硬编码改为读 config

**当前代码**（行 223-224）：
```python
expand_threshold = bool(state.get("expand_threshold", False))
prefilter_hours = 336 if expand_threshold else 168
```

**改动**：`prefilter_hours` 默认值从 config 读取，expand 时的放大窗口也改为可配置：

```python
from utils.config import load_config
config = load_config()
ranking_cfg = config.get("ranking", {})
expand_threshold = bool(state.get("expand_threshold", False))
prescreen_hours = ranking_cfg.get("prescreen_hours", 72)  # 默认 3 天
prefilter_hours = prescreen_hours * 2 if expand_threshold else prescreen_hours
```

> **逻辑变化**：`expand_threshold=true` 时窗口从 168h→144h（72×2），比原来的 336h 更合理——不需要 14 天那么宽，6 天足够兜底。

**对应 config.yaml 新增**（`ranking` 段）：
```yaml
  prescreen_hours: 72          # 预筛时间窗口（小时），默认 72=3天
```

---

### 改动 3：`agents/main_agent.py:555` — max_turns 收紧

**当前代码**：
```python
max_turns = 8
```

**改动**：降为 5（从 config 读取，默认 5）

**需要同步修改**：
- `router_node` 第 555 行硬编码 `max_turns = 8`
- 新增 config 项 `agents.max_turns: 5`

```python
from utils.config import load_config
config = load_config()
max_turns = config.get("agents", {}).get("max_turns", 5)
```

**config.yaml 修改**（`agents` 段）：
```yaml
agents:
  max_react_cycles: 3
  max_retry: 2
  max_turns: 5                 # 新增：主循环最大轮数（原硬编码 8）
  max_sub_agents_per_plan: 3
  max_same_agent_calls: 2
```

> **注意**：`max_turns` 和 `max_react_cycles` 是两个不同概念。`max_react_cycles=3` 控制 ReAct 循环（planner→invoke→observe 循环次数），`max_turns=5` 控制主循环总轮数（包含 coordinator_reflect、push、update_memory 等）。`max_turns` 应 ≥ `max_react_cycles + 2`（给 coordinator_reflect + push_notification + update_memory 留空间）。

---

### 改动 4：`config/config.yaml` — 新增两项配置

在 `ranking` 段新增 `prescreen_hours`，在 `agents` 段新增 `max_turns`：

```yaml
# --- Agent 约束 ---
agents:
  max_react_cycles: 3          # ReAct 循环上限
  max_retry: 2                 # 简报重试上限
  max_turns: 5                 # 主循环最大轮数（P0 优化：原硬编码 8）
  max_sub_agents_per_plan: 3   # 单次 plan 子 Agent 数量上限
  max_same_agent_calls: 2      # 同一子 Agent 重复调度上限

# --- 排序 & 去重 ---
ranking:
  dedup_threshold: 0.88        # 去重高阈值（>= 此值判重）
  dedup_llm_lower: 0.70        # 去重低阈值（<= 此值保留）
  max_llm_adjudications: 20    # LLM 裁决上限
  dedup_hard_threshold: 0.80   # 超限硬判阈值
  quality_threshold: 0.7       # 简报质量阈值
  cold_start_feedback_threshold: 3  # 冷启动→偏好切换所需反馈数
  half_life_hours: 24          # 时间衰减半衰期
  source_diversity_bonus: 0    # 来源多样性加分（P0=0, P1=0.05）
  prescreen_hours: 72          # 预筛时间窗口（小时），默认 72=3天（P0 优化：原硬编码 168=7天）
```

---

## 三、不改动的地方

| 位置 | 原因 |
|------|------|
| `main_agent.py:470-514` `_fallback_router_decision` | 属于 2.4 优化（router 规则优先），不在 2.2 范围。当前只作为 LLM 失败降级，改动风险较高 |
| `main_agent.py:517-609` `router_node` LLM 调用 | 同上，属于 2.4。2.2 只改 observe 的判断逻辑 |
| `main_agent.py:707-749` `observe_results_node` | 此节点只负责调用 hook 和格式化输出，不需要改 |
| `ranking_agent.py:226-242` 预筛循环体 | 只改 `prefilter_hours` 的值来源，不改循环逻辑 |
| `main_agent.py:381-402` `_fallback_plan` | 不需要改——planner 的 LLM 会从 `suggested_action` 中读取 `expand_threshold` 并在 plan 的 params 中设置 |
| `agents/state.py` | 不需要新增字段——`expand_threshold` 已通过 `params` 注入 state（第 652-654 行），不需要在 TypedDict 中声明 |

---

## 四、改动汇总

| 序号 | 文件 | 行号 | 改动内容 |
|------|------|------|---------|
| 1 | `agents/main_agent.py` | 1085-1110 | `_default_observe_evaluate`：新增 `prescreen_too_strict` 判断，`ranking_ok` 在预筛过严时不判 false，`suggest_expand` 简化条件 |
| 2 | `agents/ranking_agent.py` | 223-225 | `prefilter_hours` 从硬编码 168/336 改为读 config，默认 72h/144h |
| 3 | `agents/main_agent.py` | 555 | `max_turns` 从硬编码 8 改为读 config，默认 5 |
| 4 | `config/config.yaml` | agents 段 | 新增 `max_turns: 5` |
| 5 | `config/config.yaml` | ranking 段 | 新增 `prescreen_hours: 72` |

---

## 五、风险评估与防 Bug 措施

### 风险 1：预筛窗口从 7 天缩到 3 天，旧闻可能混入简报

- **影响**：旧条目时效性得分低（半衰期 24h），配合 ranking 的时间衰减机制，旧闻天然得分低
- **兜底**：`prescreen_hours` 在 config 中可调，如发现旧闻过多可改回 168

### 风险 2：`ranking_ok=True` 但实际只有 1 条，planner 可能误判

- **影响**：planner 看到 `ranking_ok=True` 但 `briefing_count_ok=False` + `suggested_action="expand_threshold"`，会编排 `Ranking(params={expand_threshold: true})` 而不是完整三板斧
- **验证**：观察 planner 日志，确认编排计划不含 Collection
- **兜底**：如果 planner 仍然编排了完整三板斧，第 2 轮 observe 时 `react_cycle>=1`，`_fallback_plan` 会跳过 Collection

### 风险 3：`max_turns` 从 8 降为 5，极端情况可能过早收敛

- **影响**：正常流程 1 轮 = planner→invoke→observe→router→planner...，5 轮足以完成 2 次 ReAct 循环 + coordinator_reflect + push + update_memory
- **兜底**：第 555 行已有的死循环检测（连续 3 次同节点）会在 `max_turns` 之前触发
- **建议**：5 是下限，如果实际运行中频繁触发上限可改为 6

### 风险 4：`prescreen_too_strict` 与原有逻辑的交互

- **确保**：`prescreen_too_strict` 只在 `collection_ok and len(ranked) < th_coll` 时生效，不影响正常的"采集不足"或"排序算法差"场景
- **验证**：检查 issues 列表输出，确认 `prescreen_too_strict=True` 时不会同时出现"排序不佳"误报

---

## 六、测试验证

测试场景设计：

| 场景 | 输入 | 预期 | 
|------|------|------|
| 采集充足+排序不足 | collected=62, ranked=1, top_score=0.25 | `ranking_ok=True`, `prescreen_too_strict=True`, `suggested_action="expand_threshold"`, `needs_retry=True`(仅因 briefing_count_ok=false) |
| 采集充足+排序正常 | collected=62, ranked=15, top_score=0.8 | `ranking_ok=True`, `needs_retry=False`（若简报也OK） |
| 采集不足 | collected=1, ranked=0 | `collection_ok=False`, `suggested_action="search_expand"` |
| 排序真的差 | collected=20, ranked=20, top_score=0.1 | `ranking_ok=False`（条目够但 top_score 低，是排序问题） |
| 预筛窗口 72h | 3 天内的条目 | 正常通过预筛 |
| 预筛窗口 expand | 6 天内的条目 | expand_threshold=true 时通过预筛 |

---

## 七、实施步骤

1. 改 `config/config.yaml` — 新增 `prescreen_hours` 和 `max_turns`
2. 改 `agents/main_agent.py` — `_default_observe_evaluate` 核心修复
3. 改 `agents/main_agent.py` — `router_node` 中 `max_turns` 读 config
4. 改 `agents/ranking_agent.py` — `prefilter_hours` 读 config
5. 运行测试验证
