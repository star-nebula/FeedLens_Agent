# 2.3 P1 — Briefing Agent 质量检查与重试策略优化 实施规划

> 基于 2026-06-23 代码分析，制定详细改动方案。

---

## 一、现状分析

### 1.1 质量评分链路

```
generate_briefing → briefing (JSON)
         ↓
brief_quality_check_node:
  completeness = min(1.0, total_items_in_brief / max(1, len(ranked_items)))   ← 第392行
  relevance = LLM 评估每条的与目标的匹配度                                    ← 第400-408行
  coherence  = 矛盾检测 (规则 + LLM)                                           ← 第410-425行
  score = completeness*0.3 + relevance*0.4 + coherence*0.3                     ← 第427行
         ↓
ReAct 循环: if score >= 0.7 → finish_task; else → 重试 generate_briefing
```

### 1.2 核心问题

**问题1：completeness 在条目少时不会卡死**
- 验证：ranked=3 → total_items_in_brief=3 → completeness=3/3=1.0 ✅
- 结论：completeness 公式本身没问题，但当 ranked_items 很多（如 60 条）而简报只覆盖了前 10 条时，`completeness=10/60≈0.17`，即使这 10 条已经是最好的了
- **真正的问题**：completeness 的分母是全部 ranked_items 而非简报实际使用的条目数

**问题2：relevance 偏低拖累总分**
- `_llm_assess_quality()` 调用 LLM 评估每条条目的相关性，当 LLM 返回保守评分（如 0.5-0.6）时，`relevance * 0.4` 贡献 0.2-0.24
- 若 `completeness=0.17, relevance=0.6, coherence=1.0`，则 `score = 0.17*0.3 + 0.6*0.4 + 1.0*0.3 = 0.051 + 0.24 + 0.3 = 0.591 < 0.7`
- 重试无法提升 completeness（ranked_items 不变），也无法保证 LLM 给更高 relevance

**问题3：代码层无 generate_count 硬限制**
- System prompt 写了"最多重试 2 次"、"最多 3 次 generate_briefing"，但 LLM 可能不遵守
- 代码层 `max_turns=5` 只限制整体循环轮数，不单独限制 generate_briefing 调用次数

### 1.3 涉及文件

| 文件 | 行号 | 内容 |
|------|------|------|
| `agents/briefing_agent.py:385-439` | `brief_quality_check_node()` | completeness 计算、relevance 评估 |
| `agents/briefing_agent.py:446-462` | `BRIEFING_SYSTEM_PROMPT` | LLM 重试约束（仅 prompt 层面） |
| `agents/briefing_agent.py:469-614` | `run_briefing_agent()` | ReAct 循环，需增加 generate_count 硬限制 |

---

## 二、改动方案

### 方案 A：completeness 分母修正（核心）

**当前代码（第392行）**：
```python
completeness = min(1.0, total_items_in_brief / max(1, len(ranked_items)))
```

**问题**：分母是全部 ranked_items，但简报最多展示 10 条（`items_to_show = ranked_items[:MAX_ITEMS_PER_BRIEFING]`）。当 ranked=62 条时，即使简报完美覆盖了前 10 条，completeness 也只有 `10/62≈0.16`。

**修改为**：
```python
# 简报最多展示 10 条，completeness 应以此为准而非全部 ranked
effective_max = min(len(ranked_items), MAX_ITEMS_PER_BRIEFING)
completeness = min(1.0, total_items_in_brief / max(1, effective_max))
```

### 方案 B：generate_count 硬限制（防 LLM 不守 prompt）

**当前代码**：ReAct 循环无 generate_briefing 调用计数，完全依赖 LLM 自觉遵守 prompt。

**修改**：在 `run_briefing_agent()` 循环中增加 `generate_count` 计数器：
- 每次调用 `generate_briefing` 时 `generate_count += 1`
- 当 `generate_count >= 3` 时，跳过 LLM 思考，直接调用 `finish_task`

**实现位置**：`run_briefing_agent()` 第530-542行，在 `if tool_name == "generate_briefing":` 分支中计数；在每轮循环开始前检查 `generate_count >= 3`。

### 方案 C（不做）：降低阈值

规划文档中建议 `threshold_briefing` 从 0.7 → 0.65。**不做**，因为：
- 0.7 阈值是合理的质量标准
- 方案 A 修复 completeness 后，正常场景下 score 应能稳定达到 0.7+
- 降低阈值是掩盖问题而非解决问题

---

## 三、不改的部分

| 不改 | 原因 |
|------|------|
| `BRIEFING_SYSTEM_PROMPT` | 已包含"最多重试 2 次"的 LLM 指令，方案 B 在代码层兜底即可 |
| `_llm_assess_quality()` | LLM relevance 评分逻辑本身合理，方案 A 修复 completeness 后总分应达标 |
| `generate_briefing_node()` | 简报生成逻辑正确，无需改动 |
| `threshold_briefing`（0.7） | 不降低阈值，保持质量标准 |

---

## 四、改动清单

| # | 文件 | 行号 | 改动内容 |
|---|------|------|---------|
| 1 | `agents/briefing_agent.py` | 392 | completeness 分母从 `len(ranked_items)` → `min(len(ranked_items), MAX_ITEMS_PER_BRIEFING)` |
| 2 | `agents/briefing_agent.py` | 512-542 | ReAct 循环新增 `generate_count` 计数器，≥3 次时强制 finish_task |

### 改动 1 详细

```python
# 改前
completeness = min(1.0, total_items_in_brief / max(1, len(ranked_items)))

# 改后
# P1-2.3: completeness 分母以简报实际展示上限为准，避免 ranked 过多时误判
effective_max = min(len(ranked_items), MAX_ITEMS_PER_BRIEFING)
completeness = min(1.0, total_items_in_brief / max(1, effective_max))
```

### 改动 2 详细

在 `run_briefing_agent()` 中：
- 循环开始前初始化 `generate_count = 0`
- 每轮开始时检查：`if generate_count >= 3: 跳过 LLM 直接 finish_task`
- 每次 `tool_name == "generate_briefing"` 时 `generate_count += 1`

---

## 五、防 bug 验证

### 场景 1：ranked=62, 简报覆盖 10 条

| 指标 | 改前 | 改后 |
|------|------|------|
| completeness | 10/62 ≈ 0.16 | 10/10 = 1.0 |
| score (relevance=0.8, coherence=1.0) | 0.16*0.3+0.32+0.3=**0.67** ❌ | 1.0*0.3+0.32+0.3=**0.92** ✅ |

### 场景 2：ranked=3, 简报覆盖 3 条

| 指标 | 改前 | 改后 |
|------|------|------|
| completeness | 3/3 = 1.0 | min(3,10)=3, 3/3=1.0 |
| 不变 | ✅ | ✅ |

### 场景 3：ranked=0（空）

| 指标 | 改前 | 改后 |
|------|------|------|
| completeness | min(1, 0/max(1,0)) = 0 | min(1, 0/max(1, min(0,10))) = 0 |
| 不变 | ✅ | ✅ |

### 场景 4：generate_count 硬限制

- generate_count=3, quality=0.65 → 强制 finish_task，不再重试 ✅
- generate_count=1, quality=0.85 → 正常 finish_task ✅
- 正常路径（LLM 自觉 finish）→ generate_count 计数器不影响 ✅

---

## 六、本质总结

**本质**：把质量评分的分母从「全部排序条目数」修正为「简报实际展示条目上限」，避免 ranked_items 数量大时 completeness 被系统性压低，进而避免因 completeness 无法提升而触发无效重试。同时在代码层加入 generate_briefing 调用次数硬限制，防止 LLM 不遵守 prompt 中的重试上限约束。
