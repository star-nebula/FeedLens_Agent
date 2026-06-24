# Main Agent（主编排）设计思路

> 系统总指挥，基于 LangGraph StateGraph 构建，8 个节点 + LLM 动态路由完成从意图理解到记忆写入的全流程编排。

---

## 整体定位

Main Agent 是整个 FeedLens 的**核心大脑**，负责：
- 理解用户意图（触发类型、目标提取）
- 通过 LLM Planner 编排子 Agent 执行计划
- 通过 Router 动态决策节点跳转
- 串联 3 个子 Agent（Collection → Ranking → Briefing）
- 质量观察 + 综合审查 + 推送 + 记忆写入

---

## 完整流程

```
understand_intent（意图理解）
  │
  ▼
planner（LLM 编排决策）
  │
  ▼
router_node（动态路由）
  │
  ├─→ invoke_sub_agent（执行子 Agent）
  │     ├─ Collection Agent
  │     ├─ Ranking Agent
  │     └─ Briefing Agent
  │
  ├─→ observe_results（质量观察）
  │     └─ 判断采集/排序/简报是否达标
  │
  ├─→ coordinator_reflect（综合审查）
  │     └─ 完整性 + 去重 + 追溯 + 矛盾检查
  │
  ├─→ push_notification（推送简报）
  │     └─ 优先 Markdown，降级摘要
  │
  ├─→ update_memory（记忆写入）
  │     └─ SQLite 日志 + ChromaDB 偏好向量 + 条目历史
  │
  └─→ END / abort（结束 / 放弃）
```

**ReAct 循环**：planner → invoke → observe → planner（最多 3 轮，未达标则重新编排）

---

## 8 个节点详解

### ① understand_intent — 意图理解

```
触发类型识别（daily_briefing / manual / breaking_news）
  → 从 SQLite 读取用户结构化偏好（topics / keywords / preferred_sources）
  → LLM 提取 goal 结构化字段（如用户手动输入了目标文本）
  → 生成 goal_embedding（用于后续排序的相似度计算）
```

### ② planner — LLM 编排决策（ReAct 的 Think 步骤）

```
输入：当前状态摘要（采集量、排序质量、简报质量）+ 历史记忆
输出：sub_agent_plan（下一步该调度哪些子 Agent）

LLM 失败 → 回退到标准三板斧（Collection → Ranking → Briefing）
ReAct ≥ 2 轮 → 收敛模式（跳过采集，仅排序 → 简报）
```

**8 种编排策略**：采集不足时搜索补充、排序差时 rerank、简报少时放宽门槛、质量不达标重试等。

### ③ router_node — 动态路由决策

```
规则优先（8 种场景覆盖）→ LLM 兜底（仅 needs_retry / overall_pass=false 时需要）

防死循环：连续 3 次路由到同一节点 → 强制收敛
硬兜底：agentic_turn_count ≥ max_turns（默认 5）→ 强制结束
```

### ④ invoke_sub_agent — 执行子 Agent

```
按 plan 顺序调度子 Agent，每个通过 run_with_isolation 隔离执行
单失败不阻断后续（失败的 Agent 标记为 isolated，继续执行下一个）
仅成功执行的 Agent 结果才写入 state
```

### ⑤ observe_results — 质量观察

```
通过 hook observe.evaluate 评估三个维度：
  · 采集是否达标（≥ 3 条）
  · 排序是否达标（top_score ≥ 0.3）
  · 简报是否达标（quality ≥ 0.7）

输出 needs_retry 标记 + issues 列表 + suggested_action
```

**特殊检测**：预筛过严（采集充足但排序后极少）→ 建议 expand_threshold 而非重跑。

### ⑥ coordinator_reflect — 综合审查

```
通过 hook reflect.check 做 6 项检查：
  · 完整性（是否有条目缺失）
  · 去重覆盖（重复条目是否标注）
  · 来源追溯（是否缺少 URL）
  · 事实矛盾（调用 briefing_agent 的 _check_contradiction）
  · 简报质量（评分 < 0.5 告警）
  · ReAct 循环次数（≥ 3 次告警）

输出 overall_pass（无 issues 且无矛盾且 completeness ≥ 0.7）
```

### ⑦ push_notification — 推送

```
优先推送简报的 _markdown 渲染版本
无简报时降级为 ranked_items 前 5 条的摘要
通过 MCP client 调用 push_notification 写入通知队列
```

### ⑧ update_memory — 记忆写入

```
1. 写入情节记忆（SQLite execution_logs + LLM 摘要 → ChromaDB）
2. 写入 run_logs / briefs / briefing_items / deduped_items 表
3. 更新 ChromaDB 偏好向量（top 3 条目正向偏好）
4. 写入条目历史向量（用于下次采集的跨批次预过滤去重）
```

---

## 关键设计决策

| 决策 | 做法 | 理由 |
|------|------|------|
| **规则优先路由** | 正常流程全部规则判断，仅重试/重排时需要 LLM | 节省 API 调用，避免 LLM 在确定性场景浪费 |
| **子 Agent 隔离执行** | `run_with_isolation` 包装，单失败不阻断 | 保证管线鲁棒性，一个环节失败不影响其他 |
| **死循环检测** | 连续 3 次同路由 + 轮数上限双重保护 | 防止 LLM 决策导致无限循环 |
| **记忆系统双存储** | SQLite 存执行日志，ChromaDB 存语义记忆 | 结构化查询 + 语义检索互补 |
| **跨批次预过滤** | update_memory 将条目向量写入 ChromaDB | 下次采集时向量比对，拦截历史重复条目 |

---

## 一句话总结

> 意图理解 → LLM 编排计划 → 规则路由跳转 → 顺序执行 3 个子 Agent → 质量观察 → 不达标则重试（最多 3 轮）→ 综合审查 → 推送 → 记忆写入。
