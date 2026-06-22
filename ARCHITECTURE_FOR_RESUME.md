# FeedLens 系统架构文档（简历级 Deep Dive）

> **定位**：主动式信息聚合 Agent 系统，核心差异化在于"机器自主规划 + 定时触发 + 个性化过滤"，而非传统的"用户问 → 系统答"。
>
> **技术栈**：Python / LangGraph / APScheduler / ChromaDB / SQLite / DeepSeek LLM / MCP (Model Context Protocol)

---

## 一、系统顶层架构（Agent 视角）

```
                    ┌────────────────────────────────────────────────────┐
                    │              FeedLens Orchestrator                 │
                    │      (LangGraph StateGraph — 主控 Agent)           │
                    │                                                    │
  ┌──────────────┐  │  ┌───────────────────┐   ┌──────────────────────┐ │
  │  APScheduler │──┼─▶│  understand_intent│──▶│      Planner Node    │ │
  │  CronTrigger │  │  │  (LLM提取Goal,     │   │  (LLM自主编排，输出  │ │
  │  daily 06:00 │  │  │   生成embedding)  │   │  sub_agent_plan[])  │ │
  └──────────────┘  │  └───────────────────┘   └──────────┬───────────┘ │
         │          │                                      │             │
  重大事件破例触发   │          ┌───────────────────────────▼───────────┐  │
         │          │          │         Router Node (LLM动态路由)     │  │
         ▼          │          │  决策: invoke / observe / reflect /   │  │
  trigger_type=     │          │        push / update_memory / abort   │  │
  breaking_news     │          └──────┬────────────────────────────────┘  │
                    │                 │                                    │
                    │    ┌────────────▼────────────────────────────────┐  │
                    │    │      invoke_sub_agent_node (顺序调度)        │  │
                    │    │   run_with_isolation() 隔离每个子 Agent      │  │
                    │    └──────┬──────────────┬──────────────┬────────┘  │
                    │           │              │              │            │
                    └───────────┼──────────────┼──────────────┼────────────┘
                                │              │              │
                    ┌───────────▼──┐  ┌────────▼────────┐  ┌─▼─────────────┐
                    │  Collection  │  │    Ranking      │  │   Briefing    │
                    │  Agent       │  │    Agent        │  │   Agent       │
                    │  (RSS采集+   │  │  (向量去重+     │  │ (LLM生成简报+ │
                    │  MCP搜索补充)│  │  多因子排序)    │  │  质量自检)    │
                    └──────────────┘  └─────────────────┘  └───────────────┘
                                               │
                    ┌──────────────────────────▼──────────────────────────┐
                    │         Aggregator 层（observe_results +             │
                    │         coordinator_reflect）                        │
                    │   质量评估 → 是否回退 planner 重新编排（ReAct循环）  │
                    └────────────────────────────────────────────────────┘
```

### "被动响应"→"主动触发"的关键转变

传统 RAG 问答系统依赖用户发送 Query 才启动。FeedLens 通过 **APScheduler BackgroundScheduler** 在独立后台线程运行 CronTrigger（默认每日 06:00 Asia/Shanghai），到点后以 `trigger_type=daily_briefing` 向主 Agent 注入初始状态，整个采集→排序→生成→推送管线由机器自主完成，用户无需在场。此外，Ranking 完成后若检测到 `_score > 0.85 && freshness < 2h`，调度器以 `trigger_type=breaking_news` 再次触发，实现"破例立即推送"。

---

## 二、核心数据模型与状态机

### 数据库全景（11 张表，SQLite WAL 模式）

```
users ──────────────────────────────────────────────────┐
  ├── goal_text / topics / keywords (JSON字段)           │  
  ├── goal_embedding (BLOB)                              │ FK
  └── user_preferences (keyword + weight + vector_id)   │
                                                         │
sources → raw_items → deduped_items → briefing_items ←──┘ briefs
                  ↓
           item_relations (duplicate_of / merged_into)
                                                 ↓
execution_logs (session_id + node_name + status)  run_logs
feedback (user_id + item_id + feedback_type)
```

### 个性化筛选规则的存储策略：混合范式

| 数据类型 | 存储方式 | 理由 |
|---------|---------|------|
| `topics / keywords / preferred_sources` | users 表 JSON 字段 | 结构灵活，单用户单条记录，无需 JOIN |
| `v_like / v_dislike` 偏好向量 | ChromaDB `user_preference` Collection | 向量相似度检索，SQLite 不支持近邻查询 |
| `keyword → weight` 精细规则 | `user_preferences` 范式化单行 | 支持按 keyword 索引、统计 feedback_count |

**设计哲学**：结构化可枚举字段（topics/keywords）做范式化以便索引；非结构化的语义偏好向量存 ChromaDB；既能精确匹配（关键词权重），又能语义泛化（向量相似度排序）。

### execution_logs 状态流转

```
INSERT (started) → UPDATE (completed)
                ↘ UPDATE (failed)  → [retry < 2] → INSERT (started)
```

每个 LangGraph 节点进入时写 `started`，退出时写 `completed/failed`，`session_id` 串联同一次执行的所有节点日志，`turn` 字段记录 ReAct 循环轮次，支持断点回溯。

---

## 三、核心 API 列表

### 对外 API（用户接口，Streamlit UI → Python 函数调用）

| 接口 | 入参 | 说明 |
|-----|------|------|
| `POST /run` → `main_agent.invoke(state)` | `trigger_type, goal_text, user_id` | 手动触发一次完整简报生成管线 |
| `GET /briefs` → `db_read(briefs)` | `user_id, limit` | 查询历史简报列表（含 quality_score） |
| `POST /feedback` → `FeedbackAgent.invoke` | `user_id, item_id, feedback_type` | 提交 like/dislike/irrelevant，异步触发偏好向量更新 |
| `PUT /settings` → `db_write(users)` | `goal_text, topics, preferred_sources` | 更新用户目标与订阅源配置 |

### 对内 API（Agent 内部通信接口）

| 接口 | 协议 | 说明 |
|-----|------|------|
| `search_web MCP` | SSE :8100 | Collection Agent 在 raw items < 5 条时向 MCP Server 发起补充搜索，参数 `{query, max_results}` |
| `push_notification MCP` | stdio | 主 Agent push_notification_node 调用，参数 `{brief, user_id, immediate}`，写 JSONL 通知队列 |
| `FeedLensState` 共享状态 | 进程内 TypedDict | 所有节点以 LangGraph State 传递数据，等价于内部"消息总线"；`agent_status` 字段记录各子 Agent 执行结果（success / isolated / not_executed）|
| `hooks.register / hooks.run` | 进程内事件钩子 | observe.evaluate / reflect.check / push.decide 三个策略扩展点，P1 可在不修改核心节点的前提下替换评估逻辑 |

---

## 四、关键技术决策与权衡（面试 Deep Dive）

### 4.1 调度策略：APScheduler CronTrigger vs 自研轮询

**选型**：APScheduler `BackgroundScheduler` + `CronTrigger`，运行在 Streamlit 主线程之外的独立后台线程。

**为何不用自研轮询**：自研 `while True: sleep(60)` 无法精确控制时区、无法动态修改触发时间、无法处理时钟漂移。APScheduler 原生支持时区感知 CronTrigger，配置通过 `config.yaml` 的 `scheduler.cron_time` 热读取，运维变更无需重启进程。

**避免任务重复抢占**：MVP 单进程单线程调度，`replace_existing=True` 保证同一 job_id 不会被注册两次。Planner 内置 `agentic_turn_count >= 8` 的硬兜底 + 连续 3 次相同路由检测死循环强制终止，从应用层规避了任务挂起/重叠问题。生产扩展可引入 Redis 分布式锁 + APScheduler JobStore 做多实例互斥。

### 4.2 Agent 通讯：进程内 State 共享 vs 消息队列

**当前方案**：子 Agent 以**同进程直接调用**（`sub_agent.invoke(state)`）的方式执行，共享 `FeedLensState` TypedDict，无网络开销。

**MQ 的取舍**：引入 MQ（如 Celery + Redis）能实现跨进程并行，但 MVP 的子 Agent 存在严格的数据依赖链（Collection → Ranking → Briefing），前者输出是后者输入，真正可并行的环节极少。引入 MQ 反而增加序列化/反序列化开销和运维复杂度。当前通过 `run_with_isolation()` 做进程内异常隔离（单个子 Agent 崩溃不阻断其余），已满足 MVP 的容错需求。

**最终一致性保障**：子 Agent 失败时 `agent_status[name] = "isolated"`，观察节点（observe_results）检测到并设置 `needs_retry=True`，触发 ReAct 回退重试。数据库写入采用 SQLite WAL 模式 + contextmanager 事务，确保崩溃不产生脏数据。

### 4.3 个性化过滤：向量相似度 + 反馈偏置双路并行

**排序公式**：
```
final_score = w₁·similarity + w₂·recency + w₃·(preference + feedback_bias) + w₄·importance
```

- `similarity`：item embedding 与 `goal_embedding`（topics 关键词拼接后实时计算）的余弦相似度，反映当次 Goal 匹配度。
- `preference`：item embedding 与 `v_like`/`v_dislike` 偏好向量的相似度差，通过 EMA（α=0.3）在每次 like/dislike 后异步更新。
- `feedback_bias`：临时补偿项（like+0.15, dislike-0.10, irrelevant-0.15），EMA 更新后自然归零，避免单次反馈永久污染偏好。
- 权重在冷启动（feedback_count < 3）和暖启动状态动态切换：冷启动侧重 similarity（40%），暖启动侧重 preference（40%）。

**性能**：向量去重阈值 0.88（余弦），超过 threshold 的条目对直接合并，相似度 0.70~0.88 的条目送 LLM 裁决（单次最多 20 条），保证去重质量不完全依赖向量精度。用户规则通过 ChromaDB 向量化存储，即使 1000 条偏好记录，近邻查询复杂度 O(log n)，不会成为排序瓶颈。

---

## 五、当前架构瓶颈与演进方向

### 瓶颈：Router Node 是动态路由单点瓶颈

**现象**：系统中所有节点间的跳转均汇聚到 `router_node`，每一步状态转移都需要调用一次 LLM（`temperature=0.1, max_tokens=256`）做路由决策，加上主 Agent 各节点本身的 LLM 调用，一次完整管线执行约产生 **6~10 次串行 LLM 调用**。当调度器并发触发（如 breaking_news 与 daily_briefing 同时到达）时，LLM 请求排队，推送延迟从 30s 增至 2min+。

**优化思路：分层路由 + 规则快路径**

将路由决策拆为两层：
1. **规则路由（零 LLM 延迟）**：在 `_fallback_router_decision()` 已有的确定性规则基础上，将 90% 的"正常流"（采集 OK → 排序 → 简报 → 推送）直接走规则路由，跳过 LLM 调用。
2. **LLM 路由（仅异常分支）**：仅在检测到 `needs_retry=True` 或 `brief_quality < 0.7` 等异常状态时，才升级到 LLM Router 做复杂决策。

这样可以将 LLM 调用次数从每次执行 6~10 次降低到 1~3 次（仅异常场景），正常链路延迟下降 60% 以上，同时保留 LLM 的弹性处理能力应对边缘场景。

---

*文档基于代码快照自动审查生成，反映当前 MVP 实现状态。*
*最后更新：2026-06-22*
