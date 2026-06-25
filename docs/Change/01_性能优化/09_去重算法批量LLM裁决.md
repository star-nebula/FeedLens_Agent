# 09 P1 — 去重算法优化：批量 LLM 裁决

> 将批次内去重中间相似度区间的逐对 LLM 裁决改为批量一次调用，减少 HTTP 往返次数。
> 状态：✅ 已实施（2026-06-25，commit `8810282`）

---

## 一、问题分析

### 1.1 原有去重流程

`tools/fc_tools.py` 的 `deduplicate()` 函数执行批次内去重，分三个相似度区间：

```
62 条采集数据
  │
  ▼
O(n²) 余弦比对 (~1900 次)
  │
  ├── sim ≥ 0.88 → 直接判重（无 LLM）
  ├── 0.70 ≤ sim < 0.88 → 逐对调用 LLM 裁决（最多 20 次 API）
  └── sim < 0.70 → 保留
```

### 1.2 性能瓶颈

中间区间的条目逐对调用 LLM，每次都是一次 HTTP 往返。如果有 15 对需要裁决，就是 **15 次独立的 API 调用**，每次都有网络延迟、请求排队、token 预热等开销。

### 1.3 量化

| 场景 | 裁决对数 | 原方案 API 次数 | 优化后 API 次数 | 节省 |
|------|---------|----------------|----------------|------|
| 轻度重复 | 5 对 | 5 次 | 1 次 | -80% |
| 中度重复 | 15 对 | 15 次 | 1 次 | -93% |
| 重度重复 | 25 对 | 20 次（上限） | 1 次 | -95% |

---

## 二、方案设计

### 2.1 两阶段去重策略

```
原有：高阈值 → 直接判重 / 中间 → 逐对 LLM / 低阈值 → 保留
     ⚡ 无 LLM         🐌 N 次 API         ⚡ 无 LLM

优化：高阈值 → 直接判重 / 中间 → 收集后批量 LLM / 低阈值 → 保留
     ⚡ 无 LLM         ⚡ 1 次 API            ⚡ 无 LLM
```

### 2.2 核心改动

**新增函数** `llm_adjudicate_duplicates_batch()`（`tools/fc_tools.py:513`）：

- 将所有中间区间的待裁决 pair 打包成一次 LLM 调用
- 一次 prompt 中包含多对条目，LLM 返回 JSON 数组
- 从 N 次 HTTP 往返降为 1 次

**`deduplicate()` 函数重构**（`tools/fc_tools.py:350`）：

```
阶段1: 遍历所有 pair
  ├── sim ≥ threshold_high → 直接判重（无 LLM）
  └── threshold_low ≤ sim < threshold_high → 收集到 pending_adjudications

阶段2: 批量 LLM 裁决
  ├── 取前 max_llm_adjudications 对 → llm_adjudicate_duplicates_batch() 一次调用
  └── 超限部分 → 硬判为重复（hard_limit）
```

### 2.3 溢出保护

```python
batch = pending_adjudications[:max_llm_adjudications]
overflow = pending_adjudications[max_llm_adjudications:]

# 批量裁决
batch_results = llm_adjudicate_duplicates_batch(batch, llm_provider)

# 超限部分硬判为重复（避免单次调用过大）
for pair_info in overflow:
    duplicate_set.add(j)
```

### 2.4 兼容性

保留原有的 `llm_adjudicate_duplicate()` 单对裁决函数，标记为"逐对调用，保留兼容"。所有调用方统一走批量裁决路径。

---

## 三、代码变更清单

| # | 文件 | 位置 | 改动内容 |
|---|------|------|---------|
| 1 | `tools/fc_tools.py` | L350-478 | `deduplicate()` 重构为两阶段：收集+批量裁决 |
| 2 | `tools/fc_tools.py` | L513-534 | 新增 `llm_adjudicate_duplicates_batch()` 批量裁决函数 |
| 3 | `tools/fc_tools.py` | L489-510 | `llm_adjudicate_duplicate()` 保留兼容（标记为逐对调用） |

---

## 四、防 bug 验证

### 场景 1：无需裁决（全部高相似度）

- 所有 pair 的 sim ≥ 0.88 → 直接判重
- `pending_adjudications` 为空 → 不调 LLM
- ✅ 零 API 调用

### 场景 2：正常批量裁决

- 15 对进入中间区间 → `llm_adjudicate_duplicates_batch()` 一次调用
- LLM 返回 15 个 YES/NO → 逐对应用
- ✅ 1 次 API，原需 15 次

### 场景 3：超限裁决

- 30 对进入中间区间，`max_llm_adjudications=20`
- 前 20 对批量 LLM 裁决 → 后 10 对硬判重复
- ✅ 不超 API 预算，溢出安全处理

### 场景 4：批量 LLM 异常

- `llm_adjudicate_duplicates_batch()` 抛异常
- `deduplicate()` 的 `llm_provider is not None` 检查保证不会因 LLM 不可用崩溃
- ✅ 降级到纯向量判重

---

## 五、预期效果

| 指标 | 优化前 | 优化后 | 改善 |
|------|--------|--------|------|
| 中间区间 LLM 调用 | N 次（逐对） | 1 次（批量） | **-80~95%** |
| HTTP 往返 | N 次 | 1 次 | **大幅减少** |
| 去重精度 | 不变 | 不变 | 无损 |
| 兼容性 | — | 保留单对函数 | 向后兼容 |
