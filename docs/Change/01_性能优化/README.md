# 性能与 API 消耗优化

> 基于 2026-06-23 执行日志的全面分析，系统化优化 FeedLens 管线性能。

---

## 优化路线图

```
问题发现 → 00_总体规划 → 01_enrich_metadata → 02_observe判断 → 03_briefing质量
              ↓                                                    ↓
         07_向量预过滤 ←── 06_thinking_mode  ←  05_collection_pipeline  ←  04_Planner_Router规则化
              ↓                                                    ↓
         09_批量LLM裁决(去重)                                    08_briefing管线深度优化
              ↓
         10_摘要清洗+Planner容错+VS单例
              ↑                    ↑                    ↑
              └── v2.2 子方案 A ──┴── v2.2 子方案 B ──┴── v2.2 子方案 C
           (纯标题+全量写入)    (批量裁决)        (质量+稳定性)
```

> v2.1.0 将 07 和 08 合并为统一版本，共同目标：**减少 LLM 冗余调用，LLM 只做「创造」不做「判断」**

---

## 效果汇总

| 编号 | 优化项 | 改动文件 | 核心效果 | 状态 |
|------|--------|---------|---------|------|
| 01 | enrich_metadata 批量处理 | `collection_agent.py`, `tool_registry.py`, `config.yaml` | 可关闭，关闭时节省 13 次 API 调用 | ✅ |
| 02 | observe 结果判断优化 | `main_agent.py`, `ranking_agent.py`, `config.yaml` | 修复误判排序失败，避免无效三板斧重跑 | ✅ |
| 03 | briefing 质量检查与重试 | `briefing_agent.py` | completeness 分母修正 + generate_count 硬限制 | ✅ |
| 04 | Planner/Router 规则化降级 | `main_agent.py` | 正常流程节省 6 次 router LLM 调用 | ✅ |
| 05 | collection pipeline 固定化 | `collection_agent.py`, `config.yaml` | 采集阶段 LLM 调用 -100%，耗时 -60~70% | ✅ |
| 06 | thinking_mode 关闭 + tool_choice | `llm_provider.py`, 三个 Agent | 修复 V4 function calling 不稳定 | ✅ |
| 07 | 向量预过滤跨批次去重 | `collection_agent.py`, `main_agent.py`, `vector_store.py`, `config.yaml` | 进入 Ranking 条目 -70%+，rank_items token -73%（Collection 内部步骤） | ✅ v2.2.0 子方案 A |
| 08 | briefing 管线深度优化 | `briefing_agent.py`, `tool_registry.py`, `config.yaml` | ReAct 思考 -100%，quality 仅首次调用，重试 3→2 | 📋 v2.1 子方案 B |
| 09 | 去重算法批量 LLM 裁决 | `tools/fc_tools.py` | 中间区间 N 次 LLM → 1 次批量调用，HTTP 往返 -80~95% | ✅ v2.2.0 子方案 B |
| 10 | 摘要清洗 + Planner 容错 + VectorStore 单例 | `briefing_agent.py`, `main_agent.py`, `vector_store.py`, `home_page.py` | 三层清洗去除噪音、三层 JSON 解析防崩溃、单例防数据丢失 | ✅ v2.2.0 子方案 C |

---

## 整体指标变化

| 指标 | 优化前 | 当前（v2.0） | v2.1 目标（A+B叠加） |
|------|--------|-------------|---------------------|
| 单次执行耗时 | ~8分36秒 | ≤3分钟 | ≤2分钟 |
| LLM API 调用次数 | ~35+次 | ≤12次 | ≤6-8次 |
| API 浪费占比 | ~65% | ≤20% | ≤10% |
| 最终质量 | 0.746 | ≥0.7（保持） | ≥0.7（保持） |

---

## 文档说明

- `00_优化总体规划.md` — 基于执行日志的问题分析和优化方案总览
- `01~08` — 各子项的实施 detail（改动要点、不改部分、测试结果）
- 与 `changelog.md` 的关系：changelog 保留版本条目索引，detail 文档保留完整实施细节
