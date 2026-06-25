# FeedLens — 智能信息简报 Agent 系统设计文档

> **版本**：v2.2.0 | **日期**：2026-06-25 | **状态**：✅ 已实现（基于当前代码审查）

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [核心工作流](#3-核心工作流)
4. [Agent 设计](#4-agent-设计)
5. [数据模型](#5-数据模型)
6. [工具系统与 MCP](#6-工具系统与-mcp)
7. [配置与运维](#7-配置与运维)
8. [关键设计决策](#8-关键设计决策)
9. [已知限制与演进方向](#9-已知限制与演进方向)
10. [版本变更历史](#10-版本变更历史)

---

## 1. 项目概述

### 1.1 项目定位

FeedLens 是一个**主动式信息聚合 Agent 系统**。与传统的被动问答系统不同，FeedLens 的核心差异化在于：

- **机器自主规划**：主 Agent 通过 ReAct 循环自主编排子 Agent（采集 → 排序 → 简报）
- **定时主动触发**：APScheduler 定时启动，用户无需在场
- **个性化持续学习**：基于用户反馈的 EMA 偏好向量动态更新
- **向量预过滤**：跨批次向量去重，大幅降低重复采集和 token 消耗

### 1.2 核心价值

| 维度 | 传统 RSS 阅读器 | FeedLens Agent |
|------|----------------|----------------|
| 采集方式 | 被动拉取，用户自行浏览 | 定时自主采集 + MCP 搜索补充 + 向量预过滤 |
| 信息过滤 | 按时间排序，用户自行筛选 | 三层向量去重 + 多因子偏好排序 |
| 个性化 | 关键词硬匹配 | 向量化偏好学习（v_like/v_dislike 正负分离） + 反馈闭环 |
| 输出形态 | 原始条目列表 | 结构化平铺简报（重要性 + 来源引用 + 反馈按钮） |
| 交互方式 | 用户主动查看 | Agent 定时推送 + 破例推送 + 反馈闭环 |
| 去重能力 | 无 | 跨批次向量预过滤 + 同批次三层去重 |

### 1.3 技术栈

| 组件 | 选型 | 用途 |
|------|------|------|
| Agent 编排 | LangGraph StateGraph | 主 Agent 8 节点 + 子 Agent 状态图编排 |
| LLM | DeepSeek Chat (deepseek-v4-flash) | Planner 编排、简报生成、元数据提取、去重裁决 |
| LLM 回退 | mimo-v2.5 (OpenAI 兼容) | 主 LLM 不可用时自动切换 |
| Embedding | bge-small-zh-v1.5 (本地, 384维) | 条目向量化、偏好向量、语义检索、预过滤 |
| 向量数据库 | ChromaDB (PersistentClient) | 3 个 Collection：条目向量、偏好向量、长期记忆 |
| 关系数据库 | SQLite (WAL 模式, 连接池) | 11 张表，全量数据持久化 |
| 定时任务 | APScheduler (BackgroundScheduler) | Cron 定时触发 + 重大事件破例推送 |
| 搜索补充 | MCP Server (SSE :8100) | RSS 不足时搜索引擎补充 |
| 推送服务 | MCP Server (stdio) | 简报推送通知 |
| 用户界面 | Streamlit | 6 页面前端（首页/Goal/源管理/反馈/日志/仪表盘） |
| 日志 | structlog | 结构化日志，支持 console / JSON 双格式 |

### 1.4 项目结构

```
FeedLens_Agent/
├── agents/                  # Agent StateGraph 实现
│   ├── main_agent.py        # 主 Agent（Coordinator + Planner + Router）~1343行
│   ├── collection_agent.py  # 采集 Agent（Pipeline/ReAct 双模式 + 预过滤）~364行
│   ├── ranking_agent.py     # 排序 Agent（去重 + 多因子排序 + ReAct）~579行
│   ├── briefing_agent.py    # 简报 Agent（平铺 items 生成 + 质量审查）~713行
│   ├── feedback_agent.py    # 反馈 Agent（异步 EMA 偏好更新）~401行
│   └── state.py             # FeedLensState 全局状态（39字段 TypedDict）
├── tools/                   # 工具模块
│   ├── fc_tools.py          # 8 个 FC 工具实现
│   ├── tool_registry.py     # 工具注册表（15 个工具，6 个 phase 分组）
│   └── mcp_client.py        # MCP 客户端封装（Search SSE + Push stdio）
├── mcp_servers/             # MCP 服务端
│   ├── search_server.py     # 搜索服务 (SSE :8100)
│   └── push_server.py       # 推送服务 (stdio)
├── models/                  # 数据模型
│   ├── database.py          # SQLite 封装（WAL + 连接池 + 11 表 Schema + 8 索引）
│   └── vector_store.py      # ChromaDB 封装（3 个 Collection + 自动创建）
├── utils/                   # 工具模块
│   ├── config.py            # 配置加载（YAML + ${ENV_VAR} 插值 + 单例缓存）
│   ├── llm_provider.py      # LLM Provider 抽象（DeepSeek + LLMRouter 回退链）
│   ├── embedding.py         # bge-small-zh-v1.5 单例封装（384维）
│   ├── memory_manager.py    # 记忆管理（情节记忆 SQLite + 长期记忆 ChromaDB）
│   ├── error_isolation.py   # 任务级错误隔离（装饰器 + 上下文管理器 + run_with_isolation）
│   ├── execution_fence.py   # 执行栅栏（per-user 串行化，防并发写偏好向量）
│   ├── hooks.py             # 策略 Hook 系统（observe.evaluate / reflect.check / rank.weights）
│   ├── logging_config.py    # structlog 配置
│   └── pipeline_runner.py   # Pipeline 流程执行器（子进程模式）
├── scheduler/               # 调度器
│   └── push_scheduler.py    # APScheduler 定时推送
├── ui/                      # Streamlit 前端
│   └── pages/               # 6 个页面组件
├── config/
│   └── config.yaml          # 全量配置（14 个配置块，98 行）
├── app.py                   # Streamlit 入口
└── requirements.txt         # Python 依赖
```

---

## 2. 系统架构

### 2.1 顶层架构图

```
                         ┌──────────────────────────────────────────────────┐
                         │           FeedLens Orchestrator                   │
                         │       (LangGraph StateGraph — 主控 Agent)          │
                         │                                                   │
  ┌──────────────┐      │  ┌──────────────────┐   ┌──────────────────────┐  │
  │  APScheduler │──────┼─▶│ understand_intent │──▶│    Planner Node      │  │
  │  CronTrigger │      │  │ (LLM提取Goal,     │   │ (LLM自主编排,         │  │
  │  daily 06:00 │      │  │  生成embedding,   │   │  记忆注入,           │  │
  └──────────────┘      │  │  加载用户偏好)    │   │  输出 sub_agent_plan) │  │
         │              │  └──────────────────┘   └──────────┬───────────┘  │
  重大事件破例触发        │                                    │              │
         │              │        ┌───────────────────────────▼───────────┐  │
         ▼              │        │       Router Node (规则优先 + LLM兜底) │  │
  trigger_type=         │        │  8种规则覆盖正常流, 异常/重试才走LLM   │  │
  breaking_news         │        └──────┬────────────────────────────────┘  │
                         │               │                                   │
                         │   ┌───────────▼───────────────────────────────┐  │
                         │   │     invoke_sub_agent_node (顺序调度)        │  │
                         │   │  run_with_isolation() 隔离每个子 Agent      │  │
                         │   └──────┬──────────┬──────────┬──────────────┘  │
                         │          │          │          │                  │
                         └──────────┼──────────┼──────────┼──────────────────┘
                                    │          │          │
                        ┌───────────▼──┐ ┌─────▼──────┐ ┌─▼──────────────┐
                        │  Collection  │ │  Ranking   │ │   Briefing     │
                        │  Agent       │ │  Agent     │ │   Agent        │
                        │              │ │            │ │                │
                        │ Pipeline模式 │ │ 三层去重   │ │ 平铺items生成  │
                        │ (RSS→搜索补  │ │ (0.88/0.70 │ │ (JSON Schema)  │
                        │  充→标准化)  │ │  +LLM裁决) │ │ + 质量自检     │
                        │ +向量预过滤  │ │ 多因子排序 │ │ + 数据回填     │
                        └──────────────┘ └────────────┘ └────────────────┘
                                                   │
                        ┌──────────────────────────▼──────────────────────┐
                        │       Aggregator 层 (observe + reflect)          │
                        │  质量评估 → 是否回退 planner 重新编排(ReAct循环) │
                        │      + push_notification → update_memory         │
                        └─────────────────────────────────────────────────┘
```

### 2.2 分层架构

| 层级 | 组件 | 职责 |
|------|------|------|
| **编排层** | `main_agent.py` | Planner 自主编排 + Router 规则优先路由 + ReAct 循环控制 + Hook 驱动审查 |
| **执行层** | `collection_agent.py`, `ranking_agent.py`, `briefing_agent.py` | 三阶段管线：采集（含预过滤）→ 排序（含去重）→ 简报（含质量检查） |
| **工具层** | `tool_registry.py`, `fc_tools.py`, `mcp_client.py` | 15 个工具的注册、Schema 生成与统一分发执行 |
| **数据层** | `database.py`, `vector_store.py`, `memory_manager.py` | SQLite + ChromaDB 双存储，情节/长期记忆管理 |
| **调度层** | `push_scheduler.py` | APScheduler 定时触发 + 重大事件破例推送 + execution_fence 防并发 |
| **表现层** | `ui/pages/`, `app.py` | Streamlit 6 页面前端 |

### 2.3 Agent 通信模式

- **进程内 State 共享**：所有 Agent 通过 `FeedLensState` TypedDict（39 字段，total=False）传递数据，无网络开销
- **MCP 协议**：外部服务（搜索、推送）通过 MCP 协议通信
  - Search: SSE 模式，端口 :8100，支持流式返回
  - Push: stdio 模式，子进程通信，随主进程启停
- **错误隔离**：子 Agent 通过 `run_with_isolation()` 隔离执行，单个崩溃不阻断其余，`agent_status` 记录执行状态（success/isolated/not_executed）
- **执行栅栏**：`execution_fence` per-user 锁，防止定时触发与手动触发的并发写偏好向量

---

## 3. 核心工作流

### 3.1 完整执行流程

```
                    ┌─────────────────────────────────────────┐
                    │              START                       │
                    └────────────────┬────────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────────────┐
                    │       understand_intent                  │
                    │  · 识别 trigger_type                     │
                    │  · 加载/提取 structured_goal             │
                    │  · 生成 goal_embedding                   │
                    │  · 加载用户偏好                           │
                    └────────────────┬────────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────────────┐
                    │           planner (LLM)                  │
                    │  · 构建上下文 (含记忆注入)                 │
                    │  · LLM 输出 sub_agent_plan                │
                    │  · 判断 push_immediate                    │
                    │  · 失败→标准三板斧降级                     │
                    └────────────────┬────────────────────────┘
                                     │
                                     ▼
              ┌──────────────────────────────────────────────────┐
              │                  router_node                      │
              │  ┌─────────────────────────────────────────────┐ │
              │  │  规则路由 (8种场景, 零LLM延迟)               │ │
              │  │  1. plan非空+未执行 → invoke_sub_agent      │ │
              │  │  2. 已执行+未观察 → observe_results          │ │
              │  │  3. needs_retry+未达上限 → None (LLM重新编排) │ │
              │  │  3b. needs_retry+达上限 → update_memory     │ │
              │  │  4. 无需重试 → coordinator_reflect           │ │
              │  │  5. 审查通过+未推送 → push_notification      │ │
              │  │  6. 审查不通过+未达上限 → None (LLM重新编排) │ │
              │  │  6b. 审查不通过+达上限 → push_notification   │ │
              │  │  7. 推送完成 → update_memory                 │ │
              │  │  8. 兜底 → update_memory                     │ │
              │  └─────────────────────────────────────────────┘ │
              │  仅 None 时升级到 LLM Router 做复杂决策           │
              └──────────┬──────────┬──────────┬─────────────────┘
                         │          │          │
              ┌──────────▼┐  ┌──────▼─────┐  ┌─▼──────────────┐
              │ invoke_   │  │  observe   │  │ coordinator_   │
              │ sub_agent │  │  _results  │  │ reflect        │
              │           │  │            │  │                │
              │ 按plan顺序 │  │ 结构化评估 │  │ 四维综合审查   │
              │ 调度子Agent│  │ Hook驱动   │  │ Hook驱动       │
              │ 隔离执行   │  │ 输出needs_ │  │ 输出overall_   │
              │           │  │ retry      │  │ pass           │
              └───────────┘  └────────────┘  └────────────────┘
                                                   │
                              ┌────────────────────▼────────────┐
                              │       push_notification          │
                              │  · 优先 Markdown 渲染版           │
                              │  · 降级 ranked_items 摘要         │
                              └────────────────┬────────────────┘
                                               │
                              ┌────────────────▼────────────────┐
                              │        update_memory             │
                              │  · 写入执行日志 (SQLite)          │
                              │  · 保存简报 + 条目关联             │
                              │  · 更新偏好向量 (ChromaDB)        │
                              │  · 写入条目历史向量 (跨批次预过滤)  │
                              │  · LLM摘要→长期记忆 (ChromaDB)    │
                              └────────────────┬────────────────┘
                                               │
                                               ▼
                                              END
```

### 3.2 Router 路由决策机制（规则优先 + LLM 兜底）

v2.2.0 的核心优化：Router 采用**规则优先 + LLM 兜底**的分层决策策略。

| 优先级 | 决策方式 | 适用场景 |
|--------|---------|---------|
| 1 | **规则路由**（零 LLM 延迟） | 8 种确定性场景：plan 执行 → observe → reflect → push → memory |
| 2 | **LLM 路由**（仅异常分支） | needs_retry=true 或 overall_pass=false 且未达上限时，需 LLM 重新编排 plan |

**效果**：正常链路 LLM 调用从 6~10 次降低到 1~3 次，延迟下降 60% 以上。

**防死循环机制**：
- 连续 3 次路由到同一节点 → 强制收敛到 `update_memory`
- `agentic_turn_count ≥ max_turns`（config: 5）→ 强制结束
- `react_cycle_count ≥ max_react_cycles`（config: 3）→ 停止 ReAct 循环
- 同一子 Agent 重复调度 ≥ `max_same_agent_calls`（config: 2）→ 强制跳过

### 3.3 ReAct 循环

```
planner(Think) → invoke_sub_agent(Act) → observe_results(Observe) → planner(再思考)
```

- 最多 3 次循环（`max_react_cycles: 3`）
- Planner 通过 LLM 分析当前状态（采集量、排序质量、简报质量、历史记忆）决定下一步
- 降级策略：LLM 失败 → 标准三板斧 `[Collection → Ranking → Briefing]`
- 收敛策略：react_cycle ≥ 2 → 跳过采集，仅 `[Ranking → Briefing]`

### 3.4 Planner 编排决策场景

Planner 注入**情节记忆**（SQLite 近7天执行记录）+ **长期记忆**（ChromaDB 语义相似经验），辅助 LLM 编排决策：

| 场景 | 编排策略 | 触发条件 |
|------|---------|---------|
| ① 正常每日简报 | `[Collection → Ranking → Briefing]` | 标准流程 |
| ② 采集不足 | `[Collection(补充搜索) → Ranking → Briefing]` | collected < 5 条 |
| ③ 排序不理想 | `[Ranking(调参重排) → Briefing]` | top_score < 0.3 |
| ④ 重大事件 | `[Collection → Ranking → Briefing]` + push_immediate | top_score > 0.85 且时效 < 2h |
| ⑤ 简报质量低 | `[Briefing(重试)]` | brief_quality < 0.7 |
| ⑥ 预筛过严 | `[Ranking(expand_threshold)]` | 采集充足但排序后条目极少 |
| ⑦ 空数据回退 | `[Collection(扩大时间窗)]` | 采集结果为空 |
| ⑧ 完全失败 | abort | 多次采集仍为 0 |

---

## 4. Agent 设计

### 4.1 主 Agent（Coordinator + Planner + Router）

**文件**：`agents/main_agent.py`（~1343 行）

**StateGraph 节点（8 个）**：

| 节点 | 函数 | 职责 |
|------|------|------|
| `understand_intent` | `understand_intent_node` | 识别触发类型（daily/manual/breaking_news）、加载用户 Goal、LLM 提取结构化字段（topics/keywords/preferred_sources）、生成 goal_embedding |
| `planner` | `planner_node` | LLM 自主编排 sub_agent_plan，集成**记忆检索**（情节+长期），判断 push_immediate，失败时降级为标准三板斧 |
| `router_node` | `router_node` | **规则优先路由**（8种场景）+ LLM 动态路由（兜底），含死循环检测和硬兜底 |
| `invoke_sub_agent` | `invoke_sub_agent_node` | 按 plan 顺序调度子 Agent，通过 `run_with_isolation()` 隔离错误，记录 `agent_status` |
| `observe_results` | `observe_results_node` | **Hook 驱动**的结构化质量评估（Hook: `observe.evaluate`），输出 needs_retry + suggested_action，含预筛过严检测 |
| `coordinator_reflect` | `coordinator_reflect_node` | **Hook 驱动**的四维综合审查（Hook: `reflect.check`）：完整性/去重/追溯/矛盾检查 |
| `push_notification` | `push_notification_node` | MCP stdio 推送简报，优先 Markdown，降级 ranked_items 摘要 |
| `update_memory` | `update_memory_node` | 写入 SQLite 执行日志 + 保存简报/条目关联 + 更新 ChromaDB 偏好向量 + 条目历史向量 + LLM 摘要入长期记忆 |

**Planner 上下文构建**（`_build_planner_context`）：

```python
{
    "trigger": state.trigger_type,
    "goal": state.goal_text,
    "react_cycle": state.react_cycle_count,
    "collection": {"count": len(collected_items), "search_supplemented": bool},
    "ranking": {"count": len(ranked_items), "top_score": float},
    "briefing": {"quality": state.brief_quality},
    "last_observation": state.observation_result,
    "memory": {
        "recent_executions": [...],  # SQLite 近7天执行记录（情节记忆）
        "relevant_history": [...],   # ChromaDB 语义相似经验（长期记忆）
    }
}
```

**Hook 系统集成**：

主 Agent 的 `observe_results_node` 和 `coordinator_reflect_node` 通过 Hook 注册表驱动，策略逻辑可插拔替换：

| Hook 点 | 默认函数 | 用途 |
|---------|---------|------|
| `observe.evaluate` | `_default_observe_evaluate` | 质量评估策略（含预筛过严检测） |
| `reflect.check` | `_default_reflect_check` | 综合质量审查策略（四维评分 + 矛盾检测） |
| `rank.weights` | `_default_rank_weights` | 排序权重动态切换策略（冷启动/暖启动） |

### 4.2 采集 Agent

**文件**：`agents/collection_agent.py`（~364 行）

**双模式支持**：

| 模式 | 配置值 | 特点 |
|------|--------|------|
| **Pipeline**（默认） | `collection_mode: pipeline` | 固定流水线，零 LLM 调用，规则触发搜索补充 + 向量预过滤 |
| ReAct | `collection_mode: react` | LLM 自主决策工具调用，max_turns=5，灵活但增加 API 成本 |

**Pipeline 流程**：

```
Step 1: fetch_rss（ThreadPoolExecutor, max_workers=5）
   ↓
Step 2: 向量预过滤（_prefilter_against_history）
   ↓  规则：每个条目标题向量与 ChromaDB feed_items 历史比较
   ↓  阈值：cosine_similarity ≥ 0.92 → 直接丢弃
   ↓  冷启动兜底：feed_items 为空则透传全部
   ↓
Step 3: search_web 补充（条件触发）
   ↓  触发条件：len(collected) < collection_search_threshold(5) 或 来源数 < 3
   ↓  搜索查询构建：topics[:3] → keywords[:3] → goal_text[:50]
   ↓
Step 4: normalize_items（统一字段格式 + ID 生成）
   ↓
Step 5: 再次预过滤（对搜索补充结果）
   ↓
完成
```

**RSS 源获取优先级**（三路优先级）：
1. SQLite `sources` 表（用户手动配置）
2. `structured_goal.preferred_sources`（LLM 自动推荐）
3. `DEFAULT_RSS_SOURCES`（7 个兜底源）

**采集工具**：
- `fetch_rss`：ThreadPoolExecutor 并行采集，max_workers=5，timeout=10s
- `search_web`：MCP SSE 客户端，asyncio.run 同步适配
- `enrich_metadata`：LLM 提取 category/keywords/importance（默认关闭，`enrich_metadata.enabled: false`）
- `normalize_items`：统一字段格式 + ID 生成

**向量预过滤**（`_prefilter_against_history`）：

v2.2.0 新增的跨批次去重机制，在采集阶段即可拦截历史重复条目：

```python
prefilter:
  enabled: true                # 启用
  chroma_collection: feed_items
  similarity_threshold: 0.92   # 余弦相似度阈值（≥此值丢弃）
  query_top_k: 1               # 每次查询返回最相似结果数
  retention_days: 30           # 向量保留天数
```

- 效果：条目数可减少 70%+，token 消耗减少 73%
- 降级策略：任何异常都透传全部条目，不阻塞管线

### 4.3 排序 Agent

**文件**：`agents/ranking_agent.py`（~579 行）

**核心流程**：

```
vector_search → deduplicate → rank_items → (should_rerank?) → retry
```

**去重策略（三层）**：

| 相似度范围 | 处理方式 | 说明 |
|-----------|---------|------|
| ≥ 0.88 | 直接判定为重复，保留一条代表 | `dedup_threshold` |
| ≤ 0.70 | 判定为不重复，全部保留 | `dedup_llm_lower` |
| 0.70 ~ 0.88 | **LLM 批量裁决** | 一次 API 调用裁决多个候选对，而非逐对串行 |
| 超限（>20 对） | 按 0.80 硬判 | `dedup_hard_threshold`，`max_llm_adjudications: 20` |

**排序公式**：

```
final_score = w₁·similarity + w₂·recency + w₃·preference + w₄·importance
```

| 因子 | 计算方式 | 含义 |
|------|---------|------|
| `similarity` | `cosine(item_embedding, goal_embedding)` | 内容与用户关注领域的语义匹配度 |
| `recency` | `exp(-Δt / half_life_hours)`，默认 half_life=24h | 时间新鲜度，指数衰减 |
| `preference` | `cosine(item, v_like) - cosine(item, v_dislike)` 归一化 + feedback_bias | 用户偏好匹配度（正负分离） |
| `importance` | LLM 1-5 分归一化至 [0,1]：`(score - 1) / 4` | 新闻客观重要性 |

**权重动态切换（通过 Hook `rank.weights`）**：

| 阶段 | 条件 | similarity | recency | preference | importance |
|------|------|-----------|---------|-----------|------------|
| 冷启动 | feedback_count < 3 | **0.40** | 0.25 | 0.10 | 0.25 |
| 暖启动 | feedback_count ≥ 3 | 0.30 | 0.20 | **0.40** | 0.10 |

**预处理**：
- 时间衰减预筛：默认 72h 时间窗口（`prescreen_hours: 72`），`expand_threshold` 时放宽至 336h（14天）
- 所有因子 Min-Max 归一化至 [0, 1]
- `feedback_bias` 临时补偿：like +0.15, dislike -0.10, irrelevant -0.15（EMA 更新后归零，避免单次反馈永久污染）

**ReAct 循环**：`should_rerank` 判断——最高分 < 0.3 且重排次数 < 2 时调参重排。

### 4.4 简报 Agent

**文件**：`agents/briefing_agent.py`（~713 行）

**核心流程**：

```
generate_briefing → quality_check → (score < 0.7 ? retry : finish)
```

**JSON Schema（v2.2.0 平铺 items 格式）**：

```json
{
  "title": "string          // 简报标题，简洁有力",
  "summary": "string        // 简报摘要，200字以内",
  "items": [
    {
      "id": "string           // 条目唯一ID（从原始数据复制，禁止编造）",
      "title": "string         // 条目标题",
      "summary": "string       // 条目摘要，200字以内",
      "source": "string        // 来源名称（回填强制覆盖）",
      "url": "string           // 原文链接（回填强制覆盖）",
      "published_at": "string  // 发布时间ISO格式（回填强制覆盖）",
      "importance": "number    // 重要性评分1-5（回填强制覆盖）"
    }
  ],
  "generated_at": "string    // 生成时间ISO格式"
}
```

> **v2.2.0 格式变更**：已从 v2.0 的 `categories` 分组格式改为平铺 `items` 数组，与展示端 Markdown 渲染直接对齐，消除分组→平铺转换步骤。

**关键设计**：

| 特性 | 实现 |
|------|------|
| JSON Schema 输出 | `BRIEFING_SCHEMA` 严格结构化，要求 LLM 直接输出 JSON 不加 markdown 代码块 |
| 条目排序 | 按 importance 降序取 top N（MAX_ITEMS_PER_BRIEFING=10） |
| 原始数据回填 | `_backfill_briefing_items` 强制覆盖 published_at / source / url / importance，防止 LLM 编造 |
| Markdown 渲染 | `_render_markdown` 统一格式，含反馈按钮（👍 👎 🚫） |
| 预检前置 | URL 去重、低分过滤在 LLM 生成前完成，减少噪音 |

**质量审查**：

- **四维评分**（代码层计算，不暴露给 LLM）：completeness × 0.3 + relevance × 0.4 + coherence × 0.3
- **矛盾检测**：规则（时间差异 > 7天 / 重要性差异 > 3 / URL 重复）+ LLM 补充
- **relevance 缓存**：首次质量评估的 relevance 评分缓存，重试复用
- **重试机制**：score < 0.7 时重试，最多 `briefing_max_retries`（config: 2）次
- **fallback 不报错**：JSON 解析失败时用原始数据直接拼接平铺简报

### 4.5 反馈 Agent（异步）

**文件**：`agents/feedback_agent.py`（~401 行）

**流程**：

```
record_feedback → update_preference → vector_add → cleanup_preference
```

**核心算法**：

| 机制 | 实现 | 说明 |
|------|------|------|
| EMA 更新 | `v_new = α · v_current + (1-α) · v_feedback`，α=0.3 | 指数移动平均平滑更新偏好向量 |
| 偏好正负分离 | `v_like` / `v_dislike` 分别存储于 ChromaDB `user_preference` | 正负偏好独立追踪，支持相似度差计算 |
| 临时补偿 | like +0.15, dislike -0.10, irrelevant -0.15 | EMA 更新后自然归零，避免单次反馈永久污染 |
| 关键词权重 | SQLite `user_preferences` 表记录 keyword→weight | 精确匹配 + 向量泛化双路并行 |
| 自动清理 | 权重 < `preference_cleanup_threshold`（0.1）自动删除 | 防止偏好表膨胀 |
| 异步执行 | `threading.Thread(daemon=True)` | 不阻塞主流程 |
| 冷启动切换 | feedback_count ≥ `cold_start_feedback_threshold`（3）时自动切换权重 | 从侧重相似度 → 侧重偏好 |

---

## 5. 数据模型

### 5.1 全局状态（FeedLensState）

**文件**：`agents/state.py` — **39 字段** TypedDict（total=False）

```python
class FeedLensState(TypedDict, total=False):
    # ---- 会话元信息 (3) ----
    session_id: str
    trigger_type: str          # daily_briefing | manual | breaking_news
    user_id: int               # MVP 固定为 1

    # ---- 用户 Goal (3) ----
    goal_text: str
    structured_goal: dict[str, Any]  # {topics, keywords, preferred_sources}
    goal_embedding: list[float]

    # ---- 主 Agent 编排控制 (6) ----
    messages: Annotated[list, add_messages]
    sub_agent_plan: list[dict[str, Any]]  # planner 输出
    react_cycle_count: int
    current_sub_agent: str
    planner_reason: str
    push_immediate: bool

    # ---- 子 Agent 结果 (8) ----
    collected_items: list[dict[str, Any]]
    search_supplemented: bool
    deduped_items: list[dict[str, Any]]
    item_relations: list[dict[str, Any]]
    ranked_items: list[dict[str, Any]]
    ranking_detail: dict[str, Any]
    briefing_result: dict[str, Any]     # {briefing, brief_quality}
    briefing: dict[str, Any]
    brief_quality: float

    # ---- 观察与审查 (2) ----
    observation_result: dict[str, Any]
    coordinator_observation: dict[str, Any]

    # ---- 推送 (2) ----
    push_status: str           # pending | sent | failed
    push_message: str

    # ---- 反馈 (5) ----
    item_id: int
    brief_id: int
    feedback_type: str         # like | dislike | irrelevant
    feedback_results: list[dict[str, Any]]
    feedback_count: int

    # ---- 记忆 (2) ----
    short_term_memory: list[dict[str, Any]]  # 已弃用，保留兼容
    execution_log: dict[str, Any]

    # ---- 错误与状态 (2) ----
    error: Optional[str]
    status: str                # running | completed | failed

    # ---- 路由控制 (4) ----
    router_decision: dict[str, Any]       # {"next_node": "planner", "reason": "..."}
    router_history: list[dict[str, Any]]  # 死循环检测
    agentic_turn_count: int
    sub_agent_executed: bool

    # ---- 子 Agent 执行状态 (1) ----
    agent_status: dict[str, str]  # {"Collection": "success|isolated|not_executed", ...}
```

### 5.2 SQLite 数据库（11 张表，WAL 模式）

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `users` | 用户基础信息 | goal_text, topics(JSON), keywords(JSON), preferred_sources(JSON), goal_embedding(BLOB) |
| `sources` | RSS 源管理 | url, name, category, authority_score, is_active |
| `raw_items` | 原始采集条目 | title, summary, content, url, published_at, source_id, embedding_id |
| `deduped_items` | 去重后条目 | representative_item_id, similar_count, category, keywords, importance, source_diversity_bonus |
| `item_relations` | 去重关系记录 | item_a_id, item_b_id, relation_type, similarity_score, dedup_method |
| `briefs` | 简报记录 | user_id, content_json, content_md, quality_score, quality_detail, retry_count |
| `briefing_items` | 简报-条目关联 | briefing_id, item_id, rank, final_score, is_highlight |
| `feedback` | 用户反馈 | user_id, brief_id, item_id, feedback_type(like/dislike/irrelevant) |
| `user_preferences` | 关键词偏好 | user_id, keyword, weight, vector_id, feedback_count |
| `execution_logs` | 执行日志 | session_id, turn, event, node_name, status(started/completed/failed), duration_ms, metadata(JSON) |
| `run_logs` | 运行统计 | trigger_type, items_collected, items_deduped, dedup_rate, brief_quality_score, duration_ms |

**数据库优化**：
- WAL 模式（并发读写）
- 连接池（最多 5 个连接，线程安全）
- 页面缓存优化（cache_size=10000）
- 同步模式 NORMAL（WAL 安全）
- 上下文管理器自动提交/回滚
- 批量插入支持
- 8 个关键索引：source_id, published_at, category, user_id, item_id, session_id, node_name, trigger_type

### 5.3 ChromaDB 向量存储（3 个 Collection）

| 集合 | 用途 | 向量维度 | 写入时机 |
|------|------|---------|---------|
| `feed_items` | 条目向量（跨批次预过滤 + 同批次去重） | 384 (bge-small-zh-v1.5) | update_memory 阶段 |
| `user_preference` | 用户偏好向量（v_like / v_dislike 正负分离） | 384 | 每次反馈后 |
| `domain_knowledge` | 语义记忆（长期记忆，LLM 摘要） | 384 | 每次执行结束后 |

**Embedding 模型**：`BAAI/bge-small-zh-v1.5`，本地加载，384 维，单例模式，首次运行自动下载 ~130MB

### 5.4 记忆系统（两层架构）

| 记忆类型 | 存储 | 检索方式 | 用途 |
|---------|------|---------|------|
| **情节记忆** | SQLite `execution_logs` | 时间范围查询（近7天） | Planner 回顾近期执行效果 |
| **长期记忆** | ChromaDB `domain_knowledge` | 语义相似度检索（top_k=3） | Planner 参考历史类似场景经验 |

**记忆注入流程**：
1. Planner 调用 `memory_manager.get_context(query=goal_text, n_episodic=10, n_long_term=3, lookback_days=7)`
2. 返回 `{recent_executions, relevant_history}` 注入 Planner 上下文
3. 执行结束后 `update_memory` 写入：SQLite 原始日志 + LLM 摘要 → ChromaDB 长期记忆

---

## 6. 工具系统与 MCP

### 6.1 工具注册表（ToolRegistry）

**文件**：`tools/tool_registry.py`

共注册 **15 个工具**，按 **6 个 phase** 分组，支持 `get_schemas_for_phase()` 按阶段过滤：

| Phase | 工具数 | 工具列表 | 说明 |
|-------|--------|---------|------|
| `collection` | 4 | `fetch_rss`, `search_web`, `enrich_metadata`, `normalize_items` | 采集阶段专用，ReAct 模式下暴露给 LLM |
| `ranking` | 2 | `deduplicate`, `rank_items` | 排序阶段专用 |
| `briefing` | 1 | `generate_briefing` | 简报生成 |
| `briefing_legacy` | 1 | `quality_check` | **不暴露给 LLM**，代码层直接调用 |
| `main` | 4 | `push_notification`, `record_feedback`, `read_memory`, `write_memory` | 主 Agent 专用 |
| `common` | 1 | `finish_task` | 所有阶段可见，标记阶段完成 |

**关键设计**：
- 子 Agent 只能访问自己阶段的工具（通过 phase 过滤）
- 部分工具参数由系统自动注入（如 `items` 参数），LLM 无需手动传参
- `quality_check`（phase=briefing_legacy）不暴露给 LLM，避免 LLM 对质量判断的无效"思考"
- Schema 自动转换为 OpenAI Function Calling 格式

### 6.2 MCP 服务

| 服务 | 传输 | 端口 | 说明 |
|------|------|------|------|
| Search | **SSE** | :8100 | 需独立启动 `python -m mcp_servers.search_server`，支持流式返回 |
| Push | **stdio** | - | 子进程通信，随主进程启停 |

### 6.3 Hook 系统

**文件**：`utils/hooks.py`

轻量级策略扩展机制，支持在不修改核心代码的情况下替换策略逻辑：

```python
class HookRegistry:
    def register(self, name: str, fn: Callable) -> None: ...
    def run(self, name: str, ctx: dict) -> dict: ...
```

**三个策略扩展点**：

| Hook 点 | 注册位置 | 用途 |
|---------|---------|------|
| `observe.evaluate` | main_agent 模块级 | 质量评估策略（含预筛过严检测） |
| `reflect.check` | main_agent 模块级 | 综合质量审查策略（四维评分 + 矛盾检测） |
| `rank.weights` | main_agent 模块级 | 排序权重动态切换策略（冷启动/暖启动） |

同一个 hook 点可注册多个函数，按注册顺序依次执行，异常不传播。

### 6.4 错误隔离

**文件**：`utils/error_isolation.py`

三层隔离机制：

| 机制 | 用途 | 特点 |
|------|------|------|
| `task_error_isolation` 装饰器 | 函数级隔离，支持重试 | max_retries=1, retry_delay=1000ms |
| `TaskErrorIsolator` 上下文管理器 | 代码块级隔离 | 吞掉异常，返回默认值 |
| `run_with_isolation()` | LangGraph 节点级隔离 | 主 Agent 调度子 Agent 时使用，失败返回 default_return |
| `isolate_agent_node` 装饰器 | 专用节点装饰器 | 失败时注入 error 字段，不中断图执行 |

### 6.5 执行栅栏

**文件**：`utils/execution_fence.py`

per-user 锁管理器，防止 APScheduler 定时触发与 UI 手动触发的并发写偏好向量：

```python
lock = try_acquire_pipeline(user_id)  # 获取锁
if lock is None:
    # 该用户已有管线在执行，跳过
    return
try:
    run_pipeline()
finally:
    lock.release()
```

---

## 7. 配置与运维

### 7.1 配置项（config.yaml — 14 个配置块）

```yaml
# LLM 配置
llm:
  provider: deepseek
  deepseek:
    api_key: ${DEEPSEEK_API_KEY}          # 环境变量插值
    base_url: https://api.deepseek.com/v1
    model: deepseek-v4-flash
  fallback:                               # P4 模型回退链
    api_key: ${ALTERNATIVE_API_KEY}
    base_url: https://api.xiaomimimo.com/v1
    model: mimo-v2.5

# Embedding
embedding:
  model_name: BAAI/bge-small-zh-v1.5
  device: cpu

# 调度器
scheduler:
  cron_time: "06:00"
  timezone: "Asia/Shanghai"

# Agent 约束
agents:
  max_react_cycles: 3                     # ReAct 循环上限
  max_retry: 2                            # 简报重试上限
  max_sub_agents_per_plan: 3              # 单次 plan 子 Agent 数上限
  max_same_agent_calls: 2                 # 同一子 Agent 重复调度上限
  max_turns: 5                            # Agentic 最大轮数（硬兜底）
  collection_mode: pipeline               # pipeline | react
  collection_search_threshold: 5          # RSS 不足时触发搜索补充

# 排序 & 去重
ranking:
  dedup_threshold: 0.88                   # 去重高阈值
  dedup_llm_lower: 0.70                   # 去重低阈值
  max_llm_adjudications: 20               # LLM 裁决上限
  dedup_hard_threshold: 0.80              # 超限硬判阈值
  quality_threshold: 0.7                  # 简报质量阈值
  cold_start_feedback_threshold: 3        # 冷启动切换阈值
  half_life_hours: 24                     # 时间衰减半衰期
  prescreen_hours: 72                     # 预筛时间窗口（3天）
  source_diversity_bonus: 0               # 来源多样性加分
  briefing_prescreen_min_score: 0.15      # 简报预筛最低分数
  briefing_max_retries: 2                 # 简报最大重试次数

# 排序权重
weights_cold: {similarity: 0.40, recency: 0.25, preference: 0.10, importance: 0.25}
weights_warm: {similarity: 0.30, recency: 0.20, preference: 0.40, importance: 0.10}

# 反馈系统
feedback:
  feedback_bias_positive: 0.15
  feedback_bias_negative: -0.10
  feedback_bias_irrelevant: -0.15
  ema_alpha: 0.3
  preference_cleanup_threshold: 0.1

# 重大事件推送
breaking_news:
  score_threshold: 0.85
  freshness_hours: 2

# 记忆
memory:
  short_term_window: 15

# 元数据增强
enrich_metadata:
  enabled: false                          # 默认关闭省 API
  batch_size: 20
  max_items: 30

# 数据管理
data:
  retention_days: 30
  min_items_for_brief: 3
  db_path: data/feedlens.db
  chroma_path: data/chroma

# 向量预过滤（v2.2.0 新增）
prefilter:
  enabled: true
  chroma_collection: feed_items
  similarity_threshold: 0.92
  query_top_k: 1
  retention_days: 30
```

### 7.2 启动方式

```bash
# 初始化数据库（幂等）
python scripts/init_db.py

# 启动 Streamlit 前端（含 APScheduler 后台定时任务）
streamlit run app.py

# 如需 MCP 搜索服务（单独启动）
python -m mcp_servers.search_server
```

### 7.3 运行测试

```bash
# 全 mock，无需外部依赖（推荐先跑这些）
python scripts/test_main_agent.py
python scripts/test_briefing_agent.py
python scripts/test_feedback_agent.py
python scripts/test_memory_manager.py
python scripts/test_integration.py

# 需要 Embedding 模型 + ChromaDB（首次运行自动下载 ~130MB）
python scripts/test_ranking_agent.py
python scripts/test_collection_agent.py

# 需要先启动 MCP search_server
python -m mcp_servers.search_server   # SSE :8100
python scripts/test_mcp_servers.py
```

### 7.4 错误处理策略

| 策略 | 实现 | 说明 |
|------|------|------|
| 任务级隔离 | `run_with_isolation()` | 子 Agent 崩溃不中断主流程 |
| LLM 回退 | `LLMRouter` | 主 LLM 不可用时自动切换备用 Provider |
| JSON 解析降级 | 三层降级 | 直接解析 → regex 提取 → 兜底默认值 |
| 死循环检测 | 连续 3 次相同路由 + 轮数硬上限 | 双重保护防无限循环 |
| 预过滤降级 | 异常时透传全部条目 | 不因预过滤故障阻塞管线 |
| 执行栅栏 | per-user 非阻塞锁 | 防止并发写偏好向量 |
| MCP 断线降级 | SSE 异常返回原始数据 | 搜索补充失败不阻塞采集 |

---

## 8. 关键设计决策

### 8.1 规则优先路由 vs 全 LLM 动态路由

**选择**：正常流程走规则路由（零 LLM 延迟），异常分支才走 LLM 路由

**理由**：一次完整管线执行约需 6~10 次状态转移。规则路由覆盖了其中 8 种确定性场景，仅 `needs_retry` 或 `overall_pass=false` 时升级到 LLM 重新编排。正常链路 LLM 调用从 6~10 次降低到 1~3 次，延迟下降 60% 以上。

### 8.2 进程内 State 共享 vs 消息队列

**选择**：进程内 TypedDict 共享

**理由**：子 Agent 存在严格的数据依赖链（Collection → Ranking → Briefing），真正可并行的环节极少。引入 MQ 反而增加序列化/反序列化开销和运维复杂度。当前通过 `run_with_isolation()` 做进程内异常隔离 + `execution_fence` 做并发控制，已满足 MVP 的容错需求。

### 8.3 Pipeline vs ReAct 采集模式

**选择**：默认 Pipeline（固定流水线），可选 ReAct

**理由**：采集阶段的工具调用组合高度固定（RSS → 搜索补充 → 标准化），Pipeline 模式省去 LLM 调用开销。仅在需要灵活决策时通过配置切换到 ReAct。

### 8.4 混合存储范式（SQLite + ChromaDB）

| 数据类型 | 存储 | 理由 |
|---------|------|------|
| 结构化字段 | SQLite 范式化表 | 支持 SQL 查询、JOIN、索引、事务 |
| 向量数据 | ChromaDB | 高效近邻检索 O(log n) |
| 用户偏好 | ChromaDB 向量 + SQLite 关键词权重 | 语义泛化 + 精确匹配双路并行 |
| 执行日志 | SQLite `execution_logs` | 时间范围查询、结构化检索 |
| 长期记忆 | ChromaDB `domain_knowledge` | 语义相似度检索历史经验 |

### 8.5 冷启动/暖启动权重切换

- feedback_count < 3：侧重相似度（40%），偏好仅占 10%
- feedback_count ≥ 3：侧重偏好（40%），相似度降至 30%
- 切换通过 `rank.weights` Hook 实现，可插拔替换策略

### 8.6 简报平铺 items 格式

**选择**：移除 categories 分组，直接平铺 items 数组

**理由**：v2.0 的 categories 分组格式增加了"分组→平铺"转换步骤，且与展示端 Markdown 渲染存在格式差异。v2.2.0 改为平铺格式后，Schema 与渲染直接对齐，消除了转换层。

### 8.7 向量预过滤（跨批次去重）

**选择**：在采集阶段对每个条目做历史向量相似度比较，≥0.92 直接丢弃

**理由**：传统方案仅在排序阶段做同批次去重，无法解决跨批次重复采集问题。向量预过滤在源头拦截，条目数可减少 70%+，token 消耗减少 73%。冷启动时（feed_items 为空）自动透传，不影响首次运行。

### 8.8 质量检查代码化

**选择**：`quality_check` 不暴露给 LLM 作为工具（phase=briefing_legacy），代码层直接调用

**理由**：LLM 对质量判断容易产生无效"思考"和循环。将四维评分（completeness/relevance/coherence/score）完全代码化计算，LLM 只做创造性工作（生成简报文案），不做判断性工作（质量评分）。

---

## 9. 已知限制与演进方向

### 9.1 当前限制

| 限制 | 说明 | 优先级 |
|------|------|--------|
| 单用户模式 | user_id=1 硬编码 | P2 |
| MCP SSE 需手动启动 | search_server.py 需独立运行 | P1 |
| RSS 采集无缓存 | 每次全量拉取，未做增量采集 | P1 |
| 跳过采集/简报未实现 | Planner Prompt 有描述但代码约束跳过 | P1 |
| 子 Agent 串行执行 | 即使无依赖也严格串行 | P2 |
| 无 Telegram/Webhook 推送 | 仅 Streamlit 应用内推送 | P2 |
| LLM 压缩未全链路验证 | memory_manager 有逻辑但未充分测试 | P2 |
| 多语言支持 | 仅中文优化，英文条目处理不完善 | P3 |

### 9.2 演进方向

| 方向 | 目标 | 预计版本 |
|------|------|---------|
| 多用户支持 | user_id 动态化 + 用户认证 | v2.5 |
| 采集增量缓存 | RSS 条目增量采集，避免重复拉取 | v2.3 |
| 子 Agent 并行 | 独立 Agent 并行执行 | v2.5 |
| 多渠道推送 | Telegram/Email/Webhook 推送 | v2.5 |
| Docker 部署 | 容器化 + docker-compose 一键启动 | v2.3 |
| 简报风格切换 | 详细/摘要/自定义模板 | v3.0 |
| 跨类别配额 | 简报各类别条目数可配置 | v3.0 |
| MCP 服务自动管理 | search_server 随主进程启停 | v2.3 |

---

## 10. 版本变更历史

| 版本 | 日期 | 主要变化 |
|------|------|---------|
| **v2.2.0** | **2026-06-25** | **规则优先路由（延迟↓60%）、简报平铺 items 格式、向量预过滤（token↓73%）、质量检查代码化、Planner 记忆注入、执行栅栏、Hook 系统、Pipeline/ReAct 双模式** |
| v2.0 | 2026-06-23 | 全量设计文档重写，反映 Agentic 升级规划2 实现状态 |
| v1.2 (MVP Final) | 2026-06-20 | 合并 MVP 设计文档，根据实际代码修正偏差 |
| v1.0 (MVP) | 2026-06-19 | 初始 MVP 设计文档 |

### v2.2.0 相对 v2.0 的核心变更

| 模块 | v2.0 | v2.2.0 | 影响 |
|------|------|--------|------|
| **Router** | 全 LLM 动态路由 | 规则优先 + LLM 兜底（8种场景规则覆盖） | 正常链路延迟↓60% |
| **简报格式** | categories 分组 + similar_count | 平铺 items 数组 | 消除分组→平铺转换，Schema 更简洁 |
| **去重** | 仅同批次三层去重 | 同批次三层去重 + **向量预过滤**（跨批次） | 条目数↓70%+，token 消耗↓73% |
| **质量检查** | 暴露给 LLM 作为工具 | 代码层直接调用（phase=briefing_legacy） | 消除 LLM 无效"思考"，避免循环 |
| **Planner** | 基础上下文 | 上下文 + **记忆注入**（情节+长期） | LLM 编排决策更智能 |
| **并发控制** | 无 | **执行栅栏** per-user 锁 | 防止并发写偏好向量 |
| **策略扩展** | 硬编码 | **Hook 系统**（3个扩展点） | 策略可插拔替换 |
| **采集模式** | 仅 ReAct | **Pipeline/ReAct 双模式** | Pipeline 零 LLM 调用 |
| **State 字段** | 30+ | **39 字段**（含 router_history/agentic_turn_count/agent_status） | 更精细的路由控制与状态追踪 |
| **工具数量** | 12 | **15**（新增 quality_check/briefing_legacy 分组） | 工具职责更清晰 |

---

> **文档基于 2026-06-25 代码审查生成，反映当前 v2.2.0 实现状态。**
