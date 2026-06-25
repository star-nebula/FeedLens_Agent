# FeedLens 系统架构文档（简历级 Deep Dive）

> **定位**：主动式信息聚合 Agent 系统，核心差异化在于"机器自主规划 + 定时触发 + 个性化过滤"，而非传统的"用户问 → 系统答"。
>
> **技术栈**：Python / LangGraph / Streamlit / APScheduler / ChromaDB / SQLite / DeepSeek LLM / MCP (Model Context Protocol)

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
         │          │          │   Router Node (规则优先 + LLM兜底)   │  │
         ▼          │          │  规则路由覆盖正常流，异常/重试场景    │  │
  trigger_type=     │          │  才升级到 LLM 做复杂决策             │  │
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

传统 RAG 问答系统依赖用户发送 Query 才启动。FeedLens 通过 **APScheduler BackgroundScheduler** 在独立后台线程运行 CronTrigger（默认每日 06:00 Asia/Shanghai），到点后以 `trigger_type=daily_briefing` 向主 Agent 注入初始状态，整个采集→排序→生成→推送管线由机器自主完成，用户无需在场。此外，Ranking 完成后若检测到 `_score > 0.85 && freshness < 2h`，调度器以 `trigger_type=breaking_news` 再次触发，实现"破例立即推送"。UI 端（Streamlit）支持手动触发，实际执行通过 `utils/pipeline_runner.py` 子进程模式隔离，避免阻塞 UI 线程。

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
| `POST /run` → `pipeline_runner.run_agent_pipeline(trigger_type)` | `trigger_type` (manual/daily/breaking_news) | 触发一次完整简报生成管线（子进程隔离执行） |
| `GET /briefs` → `db_read(briefs)` | `user_id, limit` | 查询历史简报列表（含 quality_score） |
| `POST /feedback` → `FeedbackAgent.invoke` | `user_id, item_id, feedback_type` | 提交 like/dislike/irrelevant，异步触发偏好向量更新 |
| `PUT /settings` → `db_write(users)` | `goal_text, topics, preferred_sources` | 更新用户目标与订阅源配置 |

### 对内 API（Agent 内部通信接口）

| 接口 | 协议 | 说明 |
|-----|------|------|
| `search_web MCP` | SSE :8100 | Collection Agent 在 RSS 采集不足时向 MCP Server 发起补充搜索，参数 `{query, max_results}` |
| `push_notification MCP` | stdio | 主 Agent push_notification_node 调用，参数 `{brief, user_id, immediate}`，写 JSONL 通知队列 |
| `FeedLensState` 共享状态 | 进程内 TypedDict | 所有节点以 LangGraph State 传递数据，等价于内部"消息总线"；包含 30+ 字段覆盖会话元信息、编排控制、子Agent结果、质量审查、推送、反馈、记忆、路由控制等全部环节 |
| `ToolRegistry.dispatch()` | 进程内函数调用 | 15 个注册工具的统一分发入口，支持按阶段（collection/ranking/briefing/main）获取工具 schema |
| `hooks.register / hooks.run` | 进程内事件钩子 | observe.evaluate / reflect.check / push.decide 三个策略扩展点，P1 可在不修改核心节点的前提下替换评估逻辑 |
| `memory_manager.get_context / add_memory` | 进程内函数调用 | Planner 记忆注入：情节记忆（SQLite execution_logs，近7天）+ 长期记忆（ChromaDB domain_knowledge，语义检索） |

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

**性能**：向量去重采用三层策略——高相似度（≥0.88）直接判重合并，低相似度（≤0.70）直接保留，中间区间（0.70~0.88）送 LLM **批量裁决**（一次 API 调用裁决多个候选对，而非逐对串行），在保证质量的同时控制 API 成本。排序前还引入**跨批次向量预过滤**（prefilter），将条目与 ChromaDB 历史简报做相似度过滤，条目数可减少 70%+，token 消耗减少 73%。用户规则通过 ChromaDB 向量化存储，即使 1000 条偏好记录，近邻查询复杂度 O(log n)，不会成为排序瓶颈。

---

## 五、当前架构瓶颈与演进方向

### 已解决 ✅：Router Node 从全动态路由 → 规则优先路由

**原瓶颈**：系统中所有节点间的跳转均汇聚到 `router_node`，每一步状态转移都需要调用一次 LLM 做路由决策，一次完整管线执行约产生 **6~10 次串行 LLM 调用**。

**已实现方案：分层路由 — 规则优先 + LLM 兜底**

通过 `_rule_based_router_decision()` 实现规则路由（零 LLM 延迟），覆盖正常流程中的所有确定性场景：
1. **规则路由覆盖**：plan 非空→执行、已执行未观察→评估、无需重试→审查、审查通过→推送、推送完成→写记忆——全部走确定性规则，无需 LLM 调用。
2. **LLM 路由仅异常分支**：仅在检测到 `needs_retry=True` 且未达最大循环时，才升级到 LLM Router 做复杂重新编排决策。

**效果**：正常链路 LLM 调用从 6~10 次降低到 1~3 次（planner + 仅异常时 router），延迟下降 60% 以上。

### 当前瓶颈：单进程顺序执行限制并发

**现象**：子 Agent 按 Collection → Ranking → Briefing 严格顺序执行，且通过 `execution_fence` 做 per-user 串行化，同一用户同时只能有一个管线在执行。当定时触发与手动触发并发时，后到的触发会被跳过。

**演进方向**：
1. **Pipeline/ReAct 双模式**（Collection Agent 已实现）：正常场景走 Pipeline 模式（零 LLM 调用），异常场景（采集不足、质量低）才走 ReAct 模式，进一步减少 API 消耗。
2. **子 Agent 并行化**：当 Ranking 和 Briefing 的输入不依赖前序 Agent 全部完成时，可考虑并行调度（需引入 MQ 或 asyncio 协程）。
3. **多用户扩展**：当前 MVP 固定 user_id=1，多用户场景需要用户级隔离（独立 ChromaDB Collection + 独立 SQLite 视图）。

---

*文档反映当前 v2.2.0 实现状态，基于实际代码审查更新。*
*最后更新：2026-06-25*
