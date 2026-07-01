# FeedLens — 基于 LangGraph 的多 Agent 智能信息简报系统

[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.2+-green.svg)](https://langchain-ai.github.io/langgraph/)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek-orange.svg)](https://www.deepseek.com/)
[![Streamlit](https://img.shields.io/badge/UI-Streamlit-red.svg)](https://streamlit.io/)

> **FeedLens** 是一个基于 LangGraph + DeepSeek 的多 Agent 智能信息简报系统。它能**自主规划、定时执行、个性化筛选**信息，从多个 RSS 源采集内容，经过向量去重和多因子排序，最终生成个性化每日简报并推送。

---

## 📑 目录

- [项目概览](#项目概览)
- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [工作流程](#工作流程)
- [子 Agent 详解](#子-agent-详解)
- [技术栈](#技术栈)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [运行测试](#运行测试)
- [数据库设计](#数据库设计)
- [MCP 服务](#mcp-服务)
- [UI 界面](#ui-界面)

---

## 项目概览

在信息过载的时代，用户每天面对海量 RSS 源、新闻资讯，难以高效筛选出真正感兴趣的内容。FeedLens 通过 **LLM 驱动的多 Agent 协作系统**，实现了从信息采集到个性化简报生成的完整自动化流程。

### 系统亮点

- **自主编排**：主 Agent（Coordinator）通过 LLM 动态路由决策，自动编排 Collection → Ranking → Briefing 三个子 Agent
- **ReAct 循环**：基于 LangGraph 的 ReAct 循环机制，支持 LLM 自主思考-执行-观察-重试，最多 3 轮
- **智能去重**：三级向量去重策略（高阈值直接判重 → 中阈值 LLM 裁决 → 低阈值保留）+ 跨批次历史预过滤
- **个性化排序**：多因子加权排序（相似度 + 时效性 + 偏好 + 重要性），支持冷启动/有反馈双模式切换
- **反馈学习**：用户反馈（like/dislike/irrelevant）通过 EMA 算法持续更新偏好向量
- **安全鲁棒**：死循环检测、硬兜底收敛、执行栅栏、子 Agent 错误隔离、LLM 模型回退链
- **定时推送**：APScheduler 每日定时触发 + 重大事件破例推送
- **结构化记忆**：情节记忆（SQLite）+ 长期记忆（ChromaDB）+ 短期记忆（滑动窗口）三级记忆体系

---

## 核心特性

### 1. 多源并行采集
- 支持 RSS/Atom 源并发抓取（ThreadPoolExecutor，默认 10 线程）
- RSS 不足时自动通过 MCP 搜索服务补充（Bing 搜索）
- 支持 Pipeline 模式（无 LLM 参与，省 API 成本）和 ReAct 模式（LLM 自主决策）
- 采集阶段跨批次向量预过滤（直接丢弃历史已出现条目）

### 2. 三级向量去重
| 阈值区间 | 策略 | 说明 |
|---------|------|------|
| ≥ 0.88 | 直接判重 | 高置信度，无需 LLM |
| 0.70 ~ 0.88 | LLM 批量裁决 | 一次请求判断所有 pair |
| ≤ 0.70 | 保留 | 低相似度，视为不同内容 |

### 3. 多因子排序
| 因子 | 冷启动权重 | 有反馈权重 | 说明 |
|------|-----------|-----------|------|
| similarity | 0.40 | 0.30 | 与用户 Goal 的向量相似度 |
| recency | 0.25 | 0.20 | 时间衰减（半衰期 24h） |
| preference | 0.10 | 0.40 | 用户偏好向量匹配 |
| importance | 0.25 | 0.10 | LLM 重要性评分 |

### 4. 简报生成 + 质量审查
- LLM 生成结构化简报 JSON（标题 + 摘要 + 条目列表）
- 自动质量评分（< 0.7 触发重试，最多 2 次）
- Coordinator 综合审查：完整性、去重质量、可追溯性、矛盾检测
- 支持 Markdown 渲染输出

### 5. 反馈驱动学习
- 三种反馈类型：like / dislike / irrelevant
- EMA 平滑更新偏好向量（α=0.3）
- 反馈 ≥ 3 条自动从冷启动模式切换到偏好模式
- 偏好向量自动清理（相似度 < 0.1 的弱偏好）

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Streamlit UI (6 页面)                      │
├─────────────────────────────────────────────────────────────┤
│                   APScheduler (定时调度)                       │
├─────────────────────────────────────────────────────────────┤
│               Main Agent (Coordinator + Planner)              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Intent   │→│ Planner  │→│ Router   │→│ Sub Agent  │  │
│  │ Parser   │  │ (LLM)    │  │ (LLM)    │  │ Invoker    │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
│                     ↑    ReAct Loop (max 3)    ↓              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Memory   │←─│ Push     │←─│Coordinator│←─│ Observe    │  │
│  │ Update   │  │ Notify   │  │ Reflect   │  │ Results    │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────────┘  │
├─────────────────────────────────────────────────────────────┤
│                     Sub Agents (3)                            │
│  ┌────────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │ Collection     │→│ Ranking      │→│ Briefing         │ │
│  │ RSS + Search   │  │ Dedup + Rank │  │ Generate + QC    │ │
│  └────────────────┘  └──────────────┘  └──────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│   SQLite (11 表)  │  ChromaDB (3 集合)  │  MCP Servers      │
└─────────────────────────────────────────────────────────────┘
```

![架构图](FeedLens_Architecture.svg)

---

## 工作流程

### 主流程

```
用户设置 Goal → 定时/手动触发 → 主 Agent 编排
    ├── understand_intent    理解意图（触发类型 + Goal 结构化 + Embedding）
    ├── planner              LLM 自主编排决策（ReAct Think 步骤）
    ├── router_node          LLM 动态路由（规则优先 + LLM 兜底）
    ├── invoke_sub_agent     顺序调度子 Agent（带错误隔离）
    │   ├── Collection       RSS 采集 + 搜索补充 + 向量预过滤
    │   ├── Ranking          向量去重 + 多因子排序
    │   └── Briefing          简报生成 + 质量审查 + 自动重试
    ├── observe_results      结构化质量观察评估
    ├── coordinator_reflect  综合质量审查（完整性/去重/追溯/矛盾）
    ├── push_notification    MCP 推送简报
    └── update_memory        写入记忆（SQLite + ChromaDB + 偏好更新）
```

### ReAct 循环

系统支持最多 3 轮 ReAct 循环：

1. **Think（Planner）**：LLM 分析当前状态，决策下一步调度哪些子 Agent
2. **Act（Invoke）**：执行 Planner 编排的子 Agent 计划
3. **Observe（Observer）**：评估执行结果质量，判断是否需要重试
4. 如果质量不达标且未达上限 → 回到 Think，重新编排
5. 如果质量达标或已达上限 → 进入 Coordinator 审查 → 推送 → 记忆更新

### 安全机制

| 机制 | 说明 |
|------|------|
| 死循环检测 | 连续 3 次相同路由 → 强制结束 |
| 硬兜底 | Agentic 轮数 ≥ 5 → 强制收敛 |
| 执行栅栏 | 同一用户同时只能运行一个管线 |
| 错误隔离 | 子 Agent 失败不阻塞其余 Agent |
| 模型回退 | 主 LLM 不可用时自动切换备用 Provider |
| Planner 降级 | LLM 调用失败时回退到标准三板斧 |
| JSON 容错 | 三层降级解析 LLM 响应（直接解析 → 正则清洗 → 逐字段提取） |

---

## 子 Agent 详解

### Collection Agent（采集 Agent）

- **功能**：从 RSS 源并发抓取内容，RSS 不足时通过 MCP 搜索补充
- **模式**：
  - **Pipeline 模式**（默认）：固定流水线 `fetch_rss → search_web(条件) → normalize_items`，无 LLM 参与
  - **ReAct 模式**（可选）：LLM 自主决策调用工具
- **向量预过滤**：采集阶段查询 ChromaDB 历史，丢弃已出现条目（相似度 ≥ 0.92）
- **默认源**：36氪、少数派、阮一峰周刊、Solidot

### Ranking Agent（排序 Agent）

- **功能**：向量去重 + 多因子加权排序
- **去重策略**：三级阈值（高直接判重 / 中 LLM 裁决 / 低保留）
- **排序因子**：相似度 + 时效性（指数衰减，半衰期 24h）+ 偏好 + 重要性
- **冷/热切换**：反馈 < 3 条时使用冷启动权重，≥ 3 条时偏好权重提升至 0.40
- **时间预筛**：默认过滤 72 小时前的旧条目

### Briefing Agent（简报 Agent）

- **功能**：生成结构化简报 JSON + 质量评分 + 自动重试
- **输出格式**：标题 + 摘要（200 字内）+ 条目列表（含标题/摘要/来源/链接/重要性）
- **质量审查**：评分 < 0.7 触发重试（最多 2 次），重试达上限则强制收敛
- **矛盾检测**：自动检测简报条目间是否存在信息矛盾

### Feedback Agent（反馈 Agent）

- **功能**：处理用户反馈（like/dislike/irrelevant），更新偏好向量
- **算法**：EMA 平滑更新（α=0.3），带正负偏置补偿
- **自动清理**：偏好相似度 < 0.1 的弱偏好自动清除

---

## 技术栈

| 组件 | 技术选型 | 用途 |
|------|----------|------|
| Agent 编排 | LangGraph StateGraph + ReAct | 主/子 Agent 工作流编排 |
| LLM | DeepSeek Chat (deepseek-v4-flash) | 核心推理引擎 |
| LLM 回退 | Mimo-v2.5（可选） | 主模型不可用时自动切换 |
| Embedding | bge-small-zh-v1.5（本地，384 维） | 向量编码（去重/排序/偏好） |
| 向量数据库 | ChromaDB（持久化） | 3 个集合：feed_items / user_preference / domain_knowledge |
| 关系数据库 | SQLite（WAL 模式） | 11 张表：用户/源/条目/简报/反馈/日志等 |
| 定时任务 | APScheduler | 每日定时触发 + 重大事件检测 |
| 搜索补充 | MCP Server（SSE :8100） | Bing 搜索（RSS 不足时补充） |
| 推送服务 | MCP Server（stdio） | 简报推送至 JSONL 通知队列 |
| 用户界面 | Streamlit | 6 个页面（首页/Goal/RSS/反馈/日志/仪表盘） |
| 日志 | structlog | 结构化日志 |
| HTTP 客户端 | httpx / aiohttp | RSS 采集、Bing 搜索 |
| RSS 解析 | feedparser | RSS/Atom feed 解析 |
| 文本处理 | sentence-transformers | Embedding 模型加载和推理 |

---

## 项目结构

```
FeedLens_Agent/
├── agents/                        # Agent StateGraph 实现
│   ├── main_agent.py              # 主 Agent（Coordinator + Planner + Router）
│   ├── collection_agent.py        # 采集 Agent（RSS + 搜索补充）
│   ├── ranking_agent.py           # 排序 Agent（去重 + 偏好排序）
│   ├── briefing_agent.py          # 简报 Agent（生成 + 质量审查）
│   ├── feedback_agent.py          # 反馈 Agent（偏好更新）
│   ├── state.py                   # FeedLensState 共享状态定义
│   └── __init__.py
├── tools/                         # FC 工具 + MCP 客户端
│   ├── fc_tools.py                # RSS/去重/排序/简报 工具函数
│   ├── tool_registry.py           # 工具注册与统一 dispatch
│   ├── mcp_client.py              # MCP 客户端封装
│   └── __init__.py
├── mcp_servers/                   # MCP Server
│   ├── search_server.py           # 搜索服务（SSE :8100）
│   ├── push_server.py             # 推送服务（stdio）
│   └── __init__.py
├── models/                        # 数据模型
│   ├── database.py                # SQLite 数据库（11 表 + 连接池）
│   ├── vector_store.py            # ChromaDB 向量存储（3 集合）
│   └── __init__.py
├── utils/                         # 工具模块
│   ├── config.py                  # 配置加载（支持 ${ENV_VAR} 环境变量）
│   ├── llm_provider.py            # LLM Provider 抽象（DeepSeek + 回退链）
│   ├── embedding.py               # bge-small-zh-v1.5 封装
│   ├── memory_manager.py          # 记忆管理（情节/长期/短期）
│   ├── logging_config.py          # structlog 配置
│   ├── error_isolation.py         # 任务级错误隔离
│   ├── execution_fence.py         # 执行栅栏（防并发）
│   ├── hooks.py                   # Hook 系统（可扩展策略）
│   ├── pipeline_runner.py         # Pipeline 流程执行器
│   └── __init__.py
├── scheduler/                     # 调度器
│   └── push_scheduler.py          # APScheduler 定时推送 + 重大事件检测
├── ui/                            # Streamlit 前端
│   ├── __init__.py
│   └── pages/                     # 6 个页面模块
│       ├── home.py                # 首页
│       ├── goal.py                # Goal 设置
│       ├── sources.py             # RSS 源管理
│       ├── feedback.py            # 反馈记录
│       ├── logs.py                # 执行日志
│       └── dashboard.py           # 执行仪表盘
├── config/
│   └── config.yaml                # 主配置文件
├── scripts/                       # 脚本 + 测试
│   ├── init_db.py                 # 数据库初始化
│   ├── download_models.py         # Embedding 模型下载
│   ├── calibrate_dedup.py         # 去重阈值校准工具
│   ├── test_data/
│   │   └── sample_feed.xml        # 测试用 RSS 数据
│   └── test_*.py                  # 测试脚本（15 个）
├── docs/                          # 项目文档
├── data/                          # 运行时数据目录
│   ├── feedlens.db                # SQLite 数据库（自动生成）
│   └── chroma/                    # ChromaDB 持久化（自动生成）
├── app.py                         # Streamlit 入口
├── requirements.txt               # Python 依赖
├── AGENTS.md                      # AI Agent 开发指引
└── README.md                      # 本文件
```

---

## 快速开始

### 环境要求

- Python 3.10+
- 8GB+ RAM（Embedding 模型需要 ~130MB 下载，运行时约 500MB 内存）
- 网络连接（用于 LLM API 调用和 RSS 采集）

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 API Key

编辑 `config/config.yaml`，填写 DeepSeek API Key：

```yaml
llm:
  deepseek:
    api_key: "sk-your-deepseek-api-key"   # 或使用环境变量 ${DEEPSEEK_API_KEY}
```

支持通过环境变量配置（推荐）：

```bash
export DEEPSEEK_API_KEY="sk-your-deepseek-api-key"
```

### 3. 初始化数据库

```bash
python scripts/init_db.py
```

### 4. 启动应用

```bash
# 启动 Streamlit UI（含 APScheduler 后台定时任务）
streamlit run app.py

# 如需 MCP 搜索服务（单独终端启动）
python -m mcp_servers.search_server
```

启动后访问 http://localhost:8501 即可使用。

### 5. 首次使用

1. 在 **Goal 设置** 页面填写你的关注领域和关键词
2. 在 **RSS 源管理** 页面添加/管理 RSS 订阅源
3. 在 **首页** 点击「立即运行」触发手动执行
4. 查看 **执行仪表盘** 观察运行进度和结果
5. 在 **反馈记录** 页面对简报条目进行 like/dislike 反馈

---

## 配置说明

完整配置位于 `config/config.yaml`，主要配置项如下：

### LLM 配置

```yaml
llm:
  provider: deepseek
  deepseek:
    api_key: ${DEEPSEEK_API_KEY}
    base_url: https://api.deepseek.com/v1
    model: deepseek-v4-flash
  fallback:                        # 可选：模型回退链
    api_key: ${ALTERNATIVE_API_KEY}
    base_url: https://api.xiaomimimo.com/v1
    model: mimo-v2.5
```

### Agent 约束

```yaml
agents:
  max_react_cycles: 3              # ReAct 循环上限
  max_retry: 2                     # 简报重试上限
  max_turns: 5                     # Agentic 最大轮数（超过强制收敛）
  collection_mode: pipeline        # 采集模式：pipeline | react
  collection_search_threshold: 5   # RSS 不足 N 条时自动搜索补充
```

### 排序与去重

```yaml
ranking:
  dedup_threshold: 0.88            # 去重高阈值（≥ 此值判重）
  dedup_llm_lower: 0.70            # 去重低阈值（≤ 此值保留）
  quality_threshold: 0.7           # 简报质量阈值
  half_life_hours: 24              # 时间衰减半衰期
  prescreen_hours: 72              # 预筛时间窗口
```

### 反馈系统

```yaml
feedback:
  feedback_bias_positive: 0.15     # like 偏置
  feedback_bias_negative: -0.10    # dislike 偏置
  feedback_bias_irrelevant: -0.15  # irrelevant 偏置
  ema_alpha: 0.3                   # EMA 平滑系数
```

### 排序权重

```yaml
weights_cold:                      # 冷启动模式（反馈 < 3 条）
  similarity: 0.40
  recency: 0.25
  preference: 0.10
  importance: 0.25

weights_warm:                      # 有反馈模式（反馈 ≥ 3 条）
  similarity: 0.30
  recency: 0.20
  preference: 0.40                 # 偏好权重大幅提升
  importance: 0.10
```

### 调度与数据

```yaml
scheduler:
  cron_time: "06:00"               # 每日简报触发时间
  timezone: "Asia/Shanghai"

data:
  retention_days: 30               # 数据保留天数
  min_items_for_brief: 3           # 生成简报的最低条目数
  db_path: data/feedlens.db
  chroma_path: data/chroma
```

---

## 运行测试

### Mock 测试（无需外部依赖，推荐先跑）

```bash
python scripts/test_main_agent.py          # 主 Agent 完整流程测试
python scripts/test_main_agent_finishing.py # 主 Agent 结束流程测试
python scripts/test_briefing_agent.py      # 简报 Agent 测试
python scripts/test_feedback_agent.py      # 反馈 Agent 测试
python scripts/test_memory_manager.py      # 记忆管理测试
python scripts/test_integration.py         # 集成测试
python scripts/test_logging_monitoring.py  # 日志监控测试
python scripts/test_cold_start_switch.py   # 冷启动切换测试
python scripts/test_push_scheduler.py      # 推送调度器测试
```

### 需要 Embedding 模型的测试

（首次运行会自动下载 bge-small-zh-v1.5，约 130MB）

```bash
python scripts/test_ranking_agent.py       # 排序 Agent 测试
python scripts/test_collection_agent.py    # 采集 Agent 测试
python scripts/test_fc_tools.py            # 工具函数测试
python scripts/test_embedding_speed.py     # Embedding 性能基准
```

### 需要 MCP 服务的测试

```bash
# 先启动 MCP 搜索服务
python -m mcp_servers.search_server        # SSE :8100

# 再运行测试
python scripts/test_mcp_servers.py
```

### 性能基准

```bash
python scripts/test_performance.py
```

---

## 数据库设计

系统使用 **SQLite（WAL 模式）** 存储结构化数据，共 11 张表：

| 表名 | 说明 | 关键字段 |
|------|------|----------|
| `users` | 用户信息与偏好 | goal_text, topics, keywords, preferred_sources, preference_vector |
| `sources` | RSS 源管理 | url, is_active, authority_score |
| `raw_items` | 原始采集条目 | title, summary, url, published_at |
| `deduped_items` | 去重后条目 | representative_item_id, similar_count, category, importance |
| `briefs` | 简报记录 | user_id, content_json, content_md, quality_score |
| `briefing_items` | 简报条目关联 | briefing_id, item_id, rank, final_score, is_highlight |
| `feedbacks` | 用户反馈 | user_id, item_id, feedback_type, created_at |
| `run_logs` | 执行日志 | trigger_type, items_collected, items_deduped, brief_quality_score |
| `execution_logs` | 详细执行记录 | session_id, event, node_name, content, status |
| `item_relations` | 条目相似关系 | item_a_id, item_b_id, similarity, relation_type |
| `item_scores` | 条目评分明细 | item_id, score_components |

同时使用 **ChromaDB** 管理 3 个向量集合：

| 集合 | 说明 | 用途 |
|------|------|------|
| `feed_items` | 条目历史向量 | 跨批次预过滤去重 |
| `user_preference` | 用户偏好向量 | 个性化排序 + 偏好学习 |
| `domain_knowledge` | 领域知识 | 长期记忆语义检索 |

---

## MCP 服务

### Search Server（SSE :8100）

提供 Bing 搜索能力，在 RSS 采集不足时自动补充搜索结果。

```bash
python -m mcp_servers.search_server
```

### Push Server（stdio）

简报推送服务，将生成的简报推送到 JSONL 通知队列。

系统通过 `tools/mcp_client.py` 自动连接 push_server，无需手动启动。

---

## UI 界面

Streamlit 提供 6 个功能页面：

| 页面 | 功能 |
|------|------|
| **首页** | 系统概览，手动触发执行，查看最新简报 |
| **Goal 设置** | 设置关注领域、关键词、偏好来源 |
| **RSS 源管理** | 添加/编辑/启用/禁用 RSS 订阅源 |
| **反馈记录** | 查看和管理对简报条目的反馈 |
| **执行日志** | 查看历史执行记录和详细日志 |
| **执行仪表盘** | 实时查看 Agent 运行状态和指标 |

<!-- 页面截图占位：请手动补充以下截图 -->
<!--
### 首页
![首页截图](docs/images/home.png)

### Goal 设置
![Goal设置截图](docs/images/goal.png)

### RSS 源管理
![RSS源管理截图](docs/images/sources.png)

### 反馈记录
![反馈记录截图](docs/images/feedback.png)

### 执行日志
![执行日志截图](docs/images/logs.png)

### 执行仪表盘
![仪表盘截图](docs/images/dashboard.png)
-->

---

## 开发指引

详见 [AGENTS.md](./AGENTS.md)，包含：

- 项目架构详解
- Agent 工作流设计
- 工具注册与调度机制
- 记忆系统设计
- Hook 可扩展策略系统
- 测试策略与覆盖

## License

本项目仅供学习和研究使用。

---

**Made with ❤️ using LangGraph + DeepSeek + Streamlit**
