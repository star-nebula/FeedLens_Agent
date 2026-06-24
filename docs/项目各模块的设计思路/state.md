# State（全局状态）设计思路

> FeedLensState 是所有 Agent 之间通信的唯一契约，基于 LangGraph StateGraph 的共享状态字典。

---

## 整体定位

`FeedLensState` 是一个 `TypedDict`，约 40 个字段，贯穿整个管线的生命周期。所有节点通过读写 state 字段完成数据传递和状态同步。

---

## 字段分类与数据流

```
                    ┌─────────────────────────────┐
                    │     会话元信息（入口）         │
                    │  session_id, trigger_type,   │
                    │  user_id                     │
                    └──────────┬──────────────────┘
                               │
                               ▼
                    ┌─────────────────────────────┐
                    │     用户 Goal（意图理解）      │
                    │  goal_text                   │
                    │  structured_goal {topics,    │
                    │    keywords, preferred_src}   │
                    │  goal_embedding              │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │  采集阶段     │  │  排序阶段     │  │  简报阶段     │
    │              │  │              │  │              │
    │ collected_   │  │ deduped_     │  │ briefing     │
    │   items      │  │   items      │  │ brief_quality│
    │ search_      │  │ item_        │  │ briefing_    │
    │   supplemented│ │   relations  │  │   result     │
    │              │  │ ranked_items │  │              │
    │              │  │ ranking_     │  │              │
    │              │  │   detail     │  │              │
    └──────────────┘  └──────────────┘  └──────────────┘
              │                │                │
              └────────────────┼────────────────┘
                               │
                               ▼
                    ┌─────────────────────────────┐
                    │     编排控制（主 Agent）       │
                    │  messages, sub_agent_plan,   │
                    │  react_cycle_count,          │
                    │  sub_agent_executed          │
                    └──────────┬──────────────────┘
                               │
                               ▼
                    ┌─────────────────────────────┐
                    │     观察与审查                │
                    │  observation_result          │
                    │  coordinator_observation     │
                    └──────────┬──────────────────┘
                               │
                               ▼
                    ┌─────────────────────────────┐
                    │     推送 + 记忆（出口）        │
                    │  push_status, push_message   │
                    │  execution_log, status       │
                    └─────────────────────────────┘
```

---

## 按职责分组

### 会话元信息（入口字段）
| 字段 | 类型 | 来源 |
|------|------|------|
| `session_id` | str | 系统生成 |
| `trigger_type` | str | 调度器 / 用户操作 |
| `user_id` | int | 调度器 / 前端 |

### 用户 Goal（understand_intent 写入）
| 字段 | 类型 | 说明 |
|------|------|------|
| `goal_text` | str | 用户原始输入 |
| `structured_goal` | dict | LLM 提取的 {topics, keywords, preferred_sources} |
| `goal_embedding` | list[float] | topics 拼接后的向量，用于排序相似度 |

### 子 Agent 结果（invoke_sub_agent 写入）
| 字段 | 来源 Agent | 说明 |
|------|-----------|------|
| `collected_items` | Collection | 采集条目列表 |
| `search_supplemented` | Collection | 是否搜索补充 |
| `deduped_items` | Ranking | 去重后条目 |
| `item_relations` | Ranking | 去重关系对 |
| `ranked_items` | Ranking | 排序后条目 |
| `ranking_detail` | Ranking | 各因子得分明细 |
| `briefing` | Briefing | 简报 JSON |
| `brief_quality` | Briefing | 质量评分 |
| `briefing_result` | Briefing | 完整结果含重试信息 |

### 编排控制（planner / router 写入）
| 字段 | 类型 | 说明 |
|------|------|------|
| `sub_agent_plan` | list[dict] | planner 输出的执行计划 |
| `sub_agent_executed` | bool | 本轮计划是否已执行 |
| `react_cycle_count` | int | ReAct 循环计数 |
| `agentic_turn_count` | int | 主循环总轮数 |
| `router_decision` | dict | LLM 路由决策 |
| `router_history` | list[dict] | 路由历史（用于死循环检测） |
| `planner_reason` | str | planner 决策理由 |

### 观察与审查（observe / coordinator 写入）
| 字段 | 类型 | 说明 |
|------|------|------|
| `observation_result` | dict | 质量观察结果，含 needs_retry / issues |
| `coordinator_observation` | dict | 综合审查结果，含 overall_pass |

### 推送 + 记忆（出口字段）
| 字段 | 类型 | 说明 |
|------|------|------|
| `push_status` | str | pending / sent / failed |
| `push_message` | str | 推送结果描述 |
| `execution_log` | dict | 执行日志 |
| `status` | str | running / completed / failed |
| `error` | str | 错误信息 |

---

## 关键设计决策

| 决策 | 做法 | 理由 |
|------|------|------|
| **TypedDict 而非 Pydantic** | 所有字段 Optional，total=False | 兼容 LangGraph 的增量更新语义 |
| **子 Agent 结果分层存储** | 每个 Agent 独立字段，不覆盖 | 方便追溯和观察评估 |
| **编排控制字段独立** | plan/executed/cycle 单独管理 | 避免和业务数据耦合 |
| **路由历史记录** | 追加式列表 | 用于死循环检测和审计 |
| **agent_status 记录** | 每个子 Agent 的 success/isolated/not_executed | 区分"失败"和"未执行" |

---

## 一句话总结

> 约 40 个字段的 TypedDict，按数据流阶段分为：入口元信息 → Goal → 子 Agent 结果 → 编排控制 → 观察审查 → 推送记忆，是所有节点之间唯一的通信契约。
