# FeedLens — 智能信息简报 Agent 系统设计文档

> **版本**：v2.0 | **日期**：2026-06-23 | **状态**：✅ 已实现（基于当前代码快照）

---

## 目录

1. [项目概述](#1-项目概述)
2. [系统架构](#2-系统架构)
3. [核心工作流](#3-核心工作流)
4. [Agent 设计](#4-agent-设计)
5. [数据模型](#5-数据模型)
6. [工具系统](#6-工具系统)
7. [配置与运维](#7-配置与运维)
8. [关键设计决策](#8-关键设计决策)
9. [已知限制与演进方向](#9-已知限制与演进方向)

---

## 1. 项目概述

### 1.1 项目定位

FeedLens 是一个**主动式信息聚合 Agent 系统**。与传统的被动问答系统不同，FeedLens 的核心差异化在于：

- **机器自主规划**：主 Agent 通过 ReAct 循环自主编排子 Agent（采集 → 排序 → 简报）
- **定时主动触发**：APScheduler 定时启动，用户无需在场
- **个性化持续学习**：基于用户反馈的 EMA 偏好向量动态更新

### 1.2 核心价值

| 维度 | 传统 RSS 阅读器 | FeedLens Agent |
|------|----------------|----------------|
| 采集方式 | 被动拉取，用户自行浏览 | 定时自主采集 + 搜索补充 |
| 信息过滤 | 按时间排序，用户自行筛选 | 智能去重 + 多因子偏好排序 |
| 个性化 | 关键词硬匹配 | 向量化偏好学习 + 反馈闭环 |
| 输出形态 | 原始条目列表 | 结构化简报（分类 + 重要性 + 来源引用） |
| 交互方式 | 用户主动查看 | Agent 定时推送 + 用户反馈闭环 |

### 1.3 技术栈

| 组件 | 选型 | 用途 |
|------|------|------|
| Agent 编排 | LangGraph StateGraph | 主 Agent + 子 Agent 状态图编排 |
| LLM | DeepSeek Chat (OpenAI 兼容) | Planner 编排、简报生成、元数据提取 |
| Embedding | bge-small-zh-v1.5 (本地) | 条目向量化、偏好向量、语义检索 |
| 向量数据库 | ChromaDB (PersistentClient) | 条目向量、用户偏好向量、长期记忆 |
| 关系数据库 | SQLite (WAL 模式) | 11 张表，全量数据持久化 |
| 定时任务 | APScheduler (BackgroundScheduler) | Cron 定时触发 + 重大事件破例推送 |
| 搜索补充 | MCP Server (SSE :8100) | RSS 不足时搜索引擎补充 |
| 推送服务 | MCP Server (stdio) | 简报推送通知 |
| 用户界面 | Streamlit | 6 页面前端（首页/Goal/源管理/反馈/日志/仪表盘） |
| 日志 | structlog | 结构化日志，支持 console / JSON 双格式 |

### 1.4 项目结构

```
FeedLens_Agent/
├── agents/                  # Agent StateGraph 实现
│   ├── main_agent.py        # 主 Agent（Coordinator + Planner + Router）
│   ├── collection_agent.py  # 采集 Agent（Pipeline / ReAct 双模式）
│   ├── ranking_agent.py     # 排序 Agent（去重 + 多因子排序）
│   ├── briefing_agent.py    # 简报 Agent（生成 + 质量审查）
│   ├── feedback_agent.py    # 反馈 Agent（异步偏好更新）
│   └── state.py             # FeedLensState 全局状态定义
├── tools/                   # 工具模块
│   ├── fc_tools.py          # 8 个 FC 工具实现
│   ├── tool_registry.py     # 工具注册表（15 个工具）
│   └── mcp_client.py        # MCP 客户端封装（Search SSE + Push stdio）
├── mcp_servers/             # MCP 服务端
│   ├── search_server.py     # 搜索服务 (SSE :8100)
│   └── push_server.py       # 推送服务 (stdio)
├── models/                  # 数据模型
│   ├── database.py          # SQLite 封装（WAL + 连接池 + 11 表 Schema）
│   └── vector_store.py      # ChromaDB 封装（3 个 Collection）
├── utils/                   # 工具模块
│   ├── config.py            # 配置加载（YAML + ${ENV_VAR} 插值 + 缓存）
│   ├── llm_provider.py      # LLM Provider 抽象（DeepSeek + LLMRouter 回退）
│   ├── embedding.py         # bge-small-zh-v1.5 单例封装
│   ├── memory_manager.py    # 记忆管理（情节记忆 + 长期记忆）
│   ├── error_isolation.py   # 任务级错误隔离
│   ├── hooks.py             # 策略 Hook 系统
│   ├── logging_config.py    # structlog 配置
│   └── pipeline_runner.py   # Pipeline 流程执行器
├── scheduler/               # 调度器
│   └── push_scheduler.py    # APScheduler 定时推送
├── ui/                      # Streamlit 前端
│   └── pages/               # 6 个页面组件
├── config/
│   └── config.yaml          # 全量配置（13 个配置块）
├── app.py                   # Streamlit 入口
└── requirements.txt         # Python 依赖
```

---

## 2. 系统架构

### 2.1 顶层架构图

```
                         ┌──────────────────────────────────────────────┐
                         │            FeedLens Orchestrator              │
                         │        (LangGraph StateGraph — 主控 Agent)    │
                         │                                              │
  ┌──────────────┐       │  ┌─────────────────┐   ┌──────────────────┐  │
  │  APScheduler │───────┼─▶│ understand_intent│──▶│   Planner Node   │  │
  │  CronTrigger │       │  │  (LLM提取Goal,    │   │ (LLM自主编排，输出│  │
  │  daily 06:00 │       │  │   生成embedding)  │   │ sub_agent_plan[])│  │
  └──────────────┘       │  └─────────────────┘   └────────┬─────────┘  │
         │               │                                  │            │
  重大事件破例触发         │         ┌───────────────────────▼──────────┐  │
         │               │         │       Router Node (规则+LLM)     │  │
         ▼               │         │ 决策: invoke / observe / reflect /│  │
  trigger_type=           │         │      push / update_memory / abort│  │
  breaking_news           │         └──────┬───────────────────────────┘  │
                          │                │                              │
                          │   ┌────────────▼──────────────────────────┐  │
                          │   │    invoke_sub_agent_node (顺序调度)    │  │
                          │   │  run_with_isolation() 隔离每个子Agent  │  │
                          │   └──────┬──────────┬──────────┬──────────┘  │
                          │          │          │          │              │
                          └──────────┼──────────┼──────────┼──────────────┘
                                     │          │          │
                         ┌───────────▼──┐ ┌─────▼──────┐ ┌─▼────────────┐
                         │  Collection  │ │  Ranking   │ │   Briefing   │
                         │  Agent       │ │  Agent     │ │   Agent      │
                         │  (RSS+搜索补充)│ │(去重+排序) │ │(生成+审查)   │
                         └──────────────┘ └────────────┘ └──────────────┘
                                                    │
                         ┌──────────────────────────▼──────────────────┐
                         │       Aggregator 层 (observe + reflect)       │
                         │  质量评估 → 是否回退 planner 重新编排(ReAct)  │
                         └──────────────────────────────────────────────┘
```

### 2.2 分层架构

| 层级 | 组件 | 职责 |
|------|------|------|
| **编排层** | `main_agent.py` | Planner 自主编排 + Router 动态路由 + ReAct 循环控制 |
| **执行层** | `collection_agent.py`, `ranking_agent.py`, `briefing_agent.py` | 三阶段管线：采集 → 排序 → 简报 |
| **工具层** | `tool_registry.py`, `fc_tools.py`, `mcp_client.py` | 15 个工具的注册、Schema 生成与分发执行 |
| **数据层** | `database.py`, `vector_store.py`, `memory_manager.py` | SQLite + ChromaDB 双存储，情节/长期记忆管理 |
| **调度层** | `push_scheduler.py` | APScheduler 定时触发 + 重大事件破例推送 |
| **表现层** | `ui/pages/`, `app.py` | Streamlit 6 页面前端 |

### 2.3 Agent 通信模式

- **进程内 State 共享**：所有 Agent 通过 `FeedLensState` TypedDict 传递数据，无网络开销
- **MCP 协议**：外部服务（搜索、推送）通过 MCP 协议通信
  - Search: SSE 模式，端口 :8100
  - Push: stdio 模式，子进程通信
- **错误隔离**：子 Agent 通过 `run_with_isolation()` 隔离执行，单个崩溃不阻断其余

---

## 3. 核心工作流

### 3.1 完整执行流程

```
understand_intent → planner → router_node → invoke_sub_agent → router_node
                              ↑                         ↓
                              └─── ReAct 循环 ──────────┘
                                                         ↓
                              router_node → observe_results → router_node
                                                                   ↓
                                          coordinator_reflect → router_node
                                                                   ↓
                                          push_notification → router_node
                                                                   ↓
                                          update_memory → END
```

### 3.2 Router 路由决策机制

Router 采用**规则优先 + LLM 兜底**的分层决策策略：

| 优先级 | 决策方式 | 适用场景 |
|--------|---------|---------|
| 1 | 规则路由（零 LLM 延迟） | 正常流程：plan 执行 → observe → reflect → push → memory |
| 2 | LLM 路由（仅异常分支） | needs_retry=true 或 overall_pass=false 时需重新编排 plan |

**防死循环机制**：
- 连续 3 次相同路由 → 强制收敛
- agentic_turn_count ≥ max_turns（配置项，默认 5）→ 强制结束
- react_cycle_count ≥ 3 → 停止 ReAct 循环

### 3.3 ReAct 循环

```
planner(Think) → invoke_sub_agent(Act) → observe_results(Observe) → planner(再思考)
```

- 最多 3 次循环（`max_react_cycles: 3`）
- Planner 通过 LLM 分析当前状态（采集量、排序质量、简报质量）决定下一步
- 降级策略：LLM 失败 → 标准三板斧 `[Collection → Ranking → Briefing]`

### 3.4 Planner 编排决策场景

| 场景 | 编排策略 | 触发条件 |
|------|---------|---------|
| ① 正常每日简报 | `[Collection → Ranking → Briefing]` | 标准流程 |
| ② 采集不足 | `[Collection(补充搜索) → Ranking → Briefing]` | collected < 5 条 |
| ③ 排序不理想 | `[Ranking(调参重排) → Briefing]` | top_score < 0.3 |
| ④ 重大事件 | `[Collection → Ranking → Briefing → PushNow]` | top_score > 0.85 且时效 < 2h |
| ⑤ 简报质量低 | `[Briefing(重试)]` | brief_quality < 0.7 |
| ⑥ 预筛过严 | `[Ranking(expand_threshold)]` | 采集充足但排序后条目极少 |
| ⑦ 空数据回退 | `[Collection(扩大时间窗)]` | 采集结果为空 |

---

## 4. Agent 设计

### 4.1 主 Agent（Coordinator + Planner + Router）

**文件**：`agents/main_agent.py`（约 1343 行）

**核心节点**：

| 节点 | 函数 | 职责 |
|------|------|------|
| `understand_intent` | `understand_intent_node` | 识别触发类型、加载用户 Goal、LLM 提取结构化字段、生成 goal_embedding |
| `planner` | `planner_node` | LLM 自主编排 sub_agent_plan，集成记忆检索（情节+长期） |
| `router_node` | `router_node` | 规则路由（优先）+ LLM 动态路由（兜底），含死循环检测和硬兜底 |
| `invoke_sub_agent` | `invoke_sub_agent_node` | 按 plan 顺序调度子 Agent，run_with_isolation 错误隔离 |
| `observe_results` | `observe_results_node` | 结构化质量评估（Hook 驱动），输出 needs_retry + suggested_action |
| `coordinator_reflect` | `coordinator_reflect_node` | 四维综合审查：完整性/去重/追溯/矛盾检查（Hook 驱动） |
| `push_notification` | `push_notification_node` | MCP stdio 推送简报，含降级（ranked_items 摘要） |
| `update_memory` | `update_memory_node` | 写入执行日志 + 保存简报 + 更新偏好向量 + 决策经验入记忆 |

**Planner 上下文构建**：

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
        "recent_executions": [...],  # SQLite 近7天执行记录
        "relevant_history": [...],   # ChromaDB 语义相似经验
    }
}
```

### 4.2 采集 Agent

**文件**：`agents/collection_agent.py`（约 364 行）

**双模式支持**：

| 模式 | 配置值 | 特点 |
|------|--------|------|
| Pipeline（默认） | `collection_mode: pipeline` | 固定流水线，零 LLM 调用，规则触发搜索补充 |
| ReAct | `collection_mode: react` | LLM 自主决策工具调用，灵活但增加 API 成本 |

**Pipeline 流程**：
```
fetch_rss → (count < 5 ? search_web : skip) → normalize_items
```

**RSS 源获取优先级**：
1. SQLite `sources` 表（用户配置）
2. `structured_goal.preferred_sources`
3. `DEFAULT_RSS_SOURCES`（7 个兜底源）

**采集工具**：
- `fetch_rss`：ThreadPoolExecutor 并行采集，max_workers=5
- `search_web`：MCP SSE 客户端，asyncio.run 同步适配
- `enrich_metadata`：LLM 提取 category/keywords/importance（可关闭）
- `normalize_items`：统一字段格式 + ID 生成

### 4.3 排序 Agent

**文件**：`agents/ranking_agent.py`（约 579 行）

**核心流程**：
```
vector_search → deduplicate → rank_items → (should_rerank?) → retry
```

**去重策略（三层）**：

| 相似度范围 | 处理方式 |
|-----------|---------|
| ≥ 0.88 | 直接判定为重复，保留一条代表 |
| ≤ 0.70 | 判定为不重复，全部保留 |
| 0.70 ~ 0.88 | LLM 二元裁决（上限 20 对，超限按 0.80 硬判） |

**排序公式**：
```
final_score = w₁·similarity + w₂·recency + w₃·preference + w₄·importance
```

| 因子 | 计算方式 | 权重（冷启动） | 权重（有反馈） |
|------|---------|-------------|-------------|
| similarity | cosine(item_emb, goal_emb) | 0.40 | 0.30 |
| recency | exp(-Δt / 24h) | 0.25 | 0.20 |
| preference | like_sim - dislike_sim 归一化 | 0.10 | 0.40 |
| importance | LLM 评分归一化 | 0.25 | 0.10 |

**冷启动/暖启动切换**：feedback_count < 3 → 冷启动权重；≥ 3 → 暖启动权重

**预筛机制**：默认 72h 时间窗口（可配置），expand_threshold 时放宽至 336h（14 天）

### 4.4 简报 Agent

**文件**：`agents/briefing_agent.py`（约 713 行）

**核心流程**：
```
generate_briefing → quality_check → (score < 0.7 ? retry : finish)
```

**关键设计**：

| 特性 | 实现 |
|------|------|
| JSON Schema 输出 | `BRIEFING_SCHEMA` 严格结构化 |
| 分类组织 | 按 category 分组，组内按 importance 降序 |
| 原始数据回填 | `_backfill_briefing_items` 防止 LLM 篡改时间/来源/URL |
| Markdown 渲染 | `_render_markdown` 统一格式输出 |
| 类似报道 | `similar_count` 标注「还有 N 篇类似报道」 |

**质量审查**：
- 四维评分：completeness × 0.3 + relevance × 0.4 + coherence × 0.3
- 矛盾检测：规则（时间差异 > 7 天 / 重要性差异 > 3 / URL 重复）+ LLM
- 重试机制：score < 0.7 时重试，最多 generate_briefing 3 次

### 4.5 反馈 Agent（异步）

**文件**：`agents/feedback_agent.py`（约 401 行）

**流程**：
```
record_feedback → update_preference → vector_add → cleanup_preference
```

**核心算法**：

| 机制 | 实现 |
|------|------|
| EMA 更新 | `v_new = 0.3 × v_current + 0.7 × v_feedback` |
| 偏好正负分离 | v_like / v_dislike 分别存储 |
| 临时补偿 | like +0.15, dislike -0.10, irrelevant -0.15 |
| 关键词权重 | SQLite `user_preferences` 表记录 |
| 自动清理 | 权重 < 0.1 的偏好项自动删除 |
| 异步执行 | `threading.Thread(daemon=True)` 不阻塞主流程 |

---

## 5. 数据模型

### 5.1 全局状态（FeedLensState）

**文件**：`agents/state.py`

```python
class FeedLensState(TypedDict, total=False):
    # ---- 会话元信息 ----
    session_id: str
    trigger_type: str          # daily_briefing | manual | breaking_news
    user_id: int               # MVP 固定为 1

    # ---- 用户 Goal ----
    goal_text: str
    structured_goal: dict      # {topics, keywords, preferred_sources}
    goal_embedding: list[float]

    # ---- 编排控制 ----
    sub_agent_plan: list[dict] # planner 输出
    react_cycle_count: int
    router_decision: dict      # router_node LLM 决策
    router_history: list[dict] # 死循环检测
    agentic_turn_count: int    # 主循环计数
    sub_agent_executed: bool
    agent_status: dict         # 各子 Agent 执行状态

    # ---- 子 Agent 结果 ----
    collected_items: list
    ranked_items: list
    deduped_items: list
    item_relations: list
    ranking_detail: dict
    briefing: dict
    brief_quality: float

    # ---- 观察与审查 ----
    observation_result: dict
    coordinator_observation: dict

    # ---- 推送与反馈 ----
    push_status: str
    feedback_results: list
    feedback_count: int

    # ---- 记忆与状态 ----
    execution_log: dict
    error: Optional[str]
    status: str
```

### 5.2 SQLite 数据库（11 张表，WAL 模式）

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `users` | 用户基础信息 | goal_text, topics(JSON), keywords(JSON), goal_embedding(BLOB) |
| `sources` | RSS 源管理 | url, authority_score, is_active |
| `raw_items` | 原始采集条目 | title, summary, url, published_at, embedding_id |
| `deduped_items` | 去重后条目 | representative_item_id, similar_count, category, importance |
| `item_relations` | 去重关系记录 | item_a_id, item_b_id, similarity_score, dedup_method |
| `briefs` | 简报记录 | content_json, content_md, quality_score |
| `briefing_items` | 简报-条目关联 | briefing_id, item_id, rank, final_score, is_highlight |
| `feedback` | 用户反馈 | user_id, item_id, feedback_type(like/dislike/irrelevant) |
| `user_preferences` | 关键词偏好 | keyword, weight, feedback_count |
| `execution_logs` | 执行日志 | session_id, turn, event, node_name, status, metadata(JSON) |
| `run_logs` | 运行统计 | trigger_type, items_collected, brief_quality_score, duration_ms |

**性能优化**：
- WAL 模式（并发读写）
- 连接池（最多 5 个连接）
- 上下文管理器自动提交/回滚
- 批量插入支持
- 关键字段索引（source_id, published_at, category, user_id, session_id 等）

### 5.3 ChromaDB 向量存储（3 个 Collection）

| 集合 | 用途 | 向量维度 |
|------|------|---------|
| `feed_items` | 条目向量（去重 + 相似度检索） | 384 (bge-small-zh-v1.5) |
| `user_preference` | 用户偏好向量（v_like / v_dislike 正负分离） | 384 |
| `domain_knowledge` | 语义记忆（长期记忆，执行摘要） | 384 |

**Embedding 模型**：`BAAI/bge-small-zh-v1.5`，本地加载，384 维，单例模式

### 5.4 记忆系统

**两层架构**：

| 记忆类型 | 存储 | 检索方式 | 用途 |
|---------|------|---------|------|
| 情节记忆 | SQLite `execution_logs` | 时间范围查询（近7天） | Planner 回顾近期执行效果 |
| 长期记忆 | ChromaDB `domain_knowledge` | 语义相似度检索 | Planner 参考历史类似场景经验 |

**记忆写入**：每次执行结束后，LLM 摘要本次决策+结果 → 写入 ChromaDB，原始记录写入 SQLite

---

## 6. 工具系统

### 6.1 工具注册表（ToolRegistry）

**文件**：`tools/tool_registry.py`

共注册 **15 个工具**，按阶段分组：

| 阶段 | 工具 | 类型 | 说明 |
|------|------|------|------|
| collection | `fetch_rss` | FC | 并行 RSS 采集，ThreadPoolExecutor |
| collection | `search_web` | MCP SSE | 搜索补充，:8100 |
| collection | `enrich_metadata` | FC | LLM 元数据增强（可关闭） |
| collection | `normalize_items` | FC | 字段标准化 |
| ranking | `deduplicate` | FC | 三层去重（向量阈值 + LLM 裁决） |
| ranking | `rank_items` | FC | 多因子加权排序 |
| briefing | `generate_briefing` | FC | JSON Schema 结构化简报 |
| briefing | `quality_check` | FC | 四维质量审查 |
| main | `push_notification` | MCP stdio | 简报推送 |
| main | `record_feedback` | FC | 反馈记录 + 偏好更新 |
| main | `read_memory` | FC | 读取历史决策记忆 |
| main | `write_memory` | FC | 写入决策经验 |
| common | `finish_task` | FC | 阶段完成标记 |

**工具 Schema 生成**：自动转换为 OpenAI Function Calling 格式，支持 `get_schemas_for_phase()` 按阶段过滤

### 6.2 MCP 服务

| 服务 | 传输 | 端口 | 说明 |
|------|------|------|------|
| Search | SSE | :8100 | 需独立启动，支持流式返回 |
| Push | stdio | - | 随主进程启停，子进程通信 |

### 6.3 Hook 系统

**文件**：`utils/hooks.py`

三个策略扩展点，支持在不修改核心代码的情况下替换策略逻辑：

| Hook 点 | 注册函数 | 用途 |
|---------|---------|------|
| `observe.evaluate` | `_default_observe_evaluate` | 质量评估策略（含预筛过严检测） |
| `reflect.check` | `_default_reflect_check` | 综合质量审查策略 |
| `rank.weights` | `_default_rank_weights` | 排序权重动态切换策略 |

---

## 7. 配置与运维

### 7.1 配置项（config.yaml）

```yaml
# LLM 配置
llm:
  provider: deepseek
  deepseek:
    api_key: ${DEEPSEEK_API_KEY}
    base_url: https://api.deepseek.com/v1
    model: deepseek-v4-flash
  fallback:                          # P4 模型回退
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
  max_react_cycles: 3
  max_turns: 5
  collection_mode: pipeline          # pipeline | react
  collection_search_threshold: 5

# 排序 & 去重
ranking:
  dedup_threshold: 0.88
  dedup_llm_lower: 0.70
  max_llm_adjudications: 20
  cold_start_feedback_threshold: 3
  prescreen_hours: 72

# 权重配置
weights_cold: {similarity: 0.40, recency: 0.25, preference: 0.10, importance: 0.25}
weights_warm: {similarity: 0.30, recency: 0.20, preference: 0.40, importance: 0.10}

# 反馈
feedback:
  ema_alpha: 0.3
  feedback_bias_positive: 0.15
  feedback_bias_negative: -0.10
  feedback_bias_irrelevant: -0.15

# 重大事件
breaking_news:
  score_threshold: 0.85
  freshness_hours: 2

# 数据管理
data:
  retention_days: 30
  db_path: data/feedlens.db
  chroma_path: data/chroma
```

### 7.2 启动方式

```bash
# 初始化数据库
python scripts/init_db.py

# 启动 Streamlit 前端（含 APScheduler 后台定时任务）
streamlit run app.py

# 如需 MCP 搜索服务（单独启动）
python -m mcp_servers.search_server
```

### 7.3 错误处理

- **任务级隔离**：`run_with_isolation()` 确保子 Agent 崩溃不中断主流程
- **LLM 回退**：`LLMRouter` 支持主备 Provider 自动切换
- **JSON 解析三层降级**：直接解析 → regex 提取 → 兜底默认值
- **死循环检测**：连续 3 次相同路由 + 轮数硬上限

---

## 8. 关键设计决策

### 8.1 进程内 State 共享 vs 消息队列

**选择**：进程内 TypedDict 共享

**理由**：子 Agent 存在严格的数据依赖链（Collection → Ranking → Briefing），真正可并行的环节极少。引入 MQ 反而增加序列化开销和运维复杂度。

### 8.2 规则路由 + LLM 路由分层

**选择**：正常流程走规则路由（零 LLM 延迟），异常分支走 LLM 路由

**理由**：将 LLM 调用从每次执行 6~10 次降低到 1~3 次（仅异常场景），正常链路延迟下降 60% 以上。

### 8.3 Pipeline vs ReAct 采集模式

**选择**：默认 Pipeline（固定流水线），可选 ReAct

**理由**：采集阶段的工具调用组合高度固定（RSS → 搜索补充 → 标准化），Pipeline 模式省去 LLM 调用开销，仅在需要灵活决策时切换到 ReAct。

### 8.4 混合存储范式（SQLite + ChromaDB）

| 数据类型 | 存储 | 理由 |
|---------|------|------|
| 结构化字段 | SQLite 范式化表 | 支持 SQL 查询、JOIN、索引 |
| 向量数据 | ChromaDB | 高效近邻检索 O(log n) |
| 用户偏好 | ChromaDB 向量 + SQLite 关键词权重 | 语义泛化 + 精确匹配双路并行 |

### 8.5 冷启动/暖启动权重切换

- feedback_count < 3：侧重相似度（40%），偏好仅占 10%
- feedback_count ≥ 3：侧重偏好（40%），相似度降至 30%
- 切换通过 `rank.weights` Hook 实现，可插拔替换策略

---

## 9. 已知限制与演进方向

### 9.1 当前限制

| 限制 | 说明 | 优先级 |
|------|------|--------|
| 单用户模式 | user_id=1 硬编码 | P2 |
| MCP SSE 需手动启动 | search_server.py 需独立运行 | P1 |
| RSS 采集无缓存 | 每次全量拉取 | P1 |
| 跳过采集/简报未实现 | Planner Prompt 有描述但代码未实现 | P1 |
| 子 Agent 串行执行 | 即使无依赖也串行 | P2 |
| 无 Telegram/Webhook 推送 | 仅应用内推送 | P2 |
| LLM 压缩未全链路验证 | memory_manager 有逻辑但未充分测试 | P2 |

### 9.2 演进方向

| 方向 | 目标 | 预计版本 |
|------|------|---------|
| 多用户支持 | user_id 动态化 + 用户认证 | v2.0 |
| 采集缓存 | RSS 条目增量采集，避免重复 | v1.5 |
| 子 Agent 并行 | 独立 Agent 并行执行 | v2.0 |
| 多渠道推送 | Telegram/Email/Webhook | v2.0 |
| Docker 部署 | 容器化 + docker-compose | v1.5 |
| 简报风格切换 | 详细/摘要/自定义模板 | v2.0 |
| 跨类别配额 | 简报各类别条目数可配置 | v2.0 |

---

> **文档基于代码快照自动审查生成，反映当前实现状态。**
> **最后更新**：2026-06-23
