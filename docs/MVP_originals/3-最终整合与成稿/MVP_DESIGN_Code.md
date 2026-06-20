# FeedLens MVP 设计文档

> **项目代号**：FeedLens  
> **文档版本**：v1.0  
> **最后更新**：2026-06-18  
> **文档状态**：✅ 已定稿

---

## 1. 项目概述（愿景与核心价值）

### 1.1 愿景

FeedLens 是一个**由 LLM Agent 驱动的智能化信息简报系统**。它通过 LangGraph 编排的 Agent 工作流，自动采集、筛选、排序、摘要 RSS 订阅源与网页搜索结果，将海量信息压缩为一份结构化、个性化的每日简报，让用户**在信息过载中不失焦**。

### 1.2 核心价值主张

| 维度 | 传统 RSS 阅读器 | FeedLens Agent |
|------|----------------|----------------|
| 采集方式 | 被动拉取，用户自行浏览 | 定时自主采集 + 搜索补充 |
| 信息过滤 | 按时间排序，用户自行筛选 | 智能去重 + 多因子偏好排序 |
| 个性化 | 基于关键词的硬匹配 | 基于用户反馈动态学习偏好向量 |
| 输出形态 | 原始条目列表 | 结构化简报（分类 + 重要性标注 1-5 + 来源引用） |
| 交互方式 | 用户主动查看 | Agent 定时推送 + 用户反馈闭环 |

### 1.3 项目定位

FeedLens 定位为**个人开发者的信息助理工具**（单用户模式），MVP 阶段聚焦"定时执行 → 自动简报"的核心闭环，不追求多用户、高并发等生产级特性。

### 1.4 MVP 核心假设

> **假设**：用户愿意每天收到一份「5-10 条高价值、已去重、按个人偏好排序」的信息简报，并通过反馈持续改善推送质量。

MVP 阶段的一切设计决策均围绕**最快验证此假设**展开。

### 1.5 核心价值

| 价值维度 | 说明 |
|---------|------|
| **自动化信息筛选** | Agent 自主完成从采集到推送的全流程，用户无需逐个翻阅订阅源 |
| **个性化排序** | 基于用户偏好向量和多因子排序公式，理解"什么对你更重要" |
| **结构化输出** | 简报以结构化 JSON 呈现，含重要性标注（1-5 级）与来源 URL 引用 |
| **持续学习** | 通过点赞/踩/不相关三级反馈，偏好逐渐收敛为用户真正关注的领域 |
| **国内可用** | 全栈选用国内 LLM（DeepSeek / 通义千问）和本地 Embedding 模型，零科学上网需求 |

---

## 2. 核心用户场景与业务闭环

### 2.1 典型用户画像

- **身份**：技术从业者/AI 开发者/个人站长
- **核心痛点**：每天几十到上百条 RSS 订阅，阅读压力大，容易被低价值信息淹没
- **期望**：每天自动拿到一份精华摘要，直接可用的结构化信息

### 2.2 核心场景

**场景一：每日自动简报（P0）**

> 每天早上 8:00，FeedLens 自动启动采集流程 → 从用户订阅的 RSS 源拉取最新条目 → 去重 → 排序 → LLM 摘要生成 → 反思审查 → 输出结构化简报至应用内。用户打开 Streamlit 界面即可阅读。

**场景二：重大事件破例推送（P1）**

> Agent 在采集过程中发现 LLM 评估重要性 ≥ 4 的事件（如某领域核心技术的重大突破），在简报生成前即触发送达标记，用户打开应用时此类条目以突出方式展示。

**场景三：用户反馈驱动偏好演进（P1）**

> 用户对简报中某条信息点击"不相关" → Agent 记录反馈 → 更新长期记忆中的偏好向量（降低对应话题/来源权重） → 后续排序中同类内容优先级下降。Agent 遇到偏好信号冲突时可主动追问用户澄清。

**场景四：关键词搜索补充（P2）**

> 用户设定关注关键词（如"LLM Agent 2026"），FeedLens 在 RSS 采集不足时，通过 MCP Search 服务搜索 Web 作为补充，确保关键话题不被遗漏。

### 2.3 业务闭环

```
用户设定 Goal
    ↓
LLM 提取结构化偏好字段
    ↓
┌───────────────────────────────────────┐
│           APScheduler 定时触发          │
└──────────────┬────────────────────────┘
               ↓
    ┌── 采集（RSS 并行 + 条件搜索补充）
    │     ↓
    ├── 去重（向量相似度 0.88 + 模糊区间 LLM 裁决）
    │     ↓
    ├── 排序（多因子加权：相似度/时效/偏好/重要性）
    │     ↓
    ├── 简报生成（结构化 JSON → Markdown 渲染）
    │     ↓
    ├── 反思（brief_quality 评分 < 0.7 → 重试，最多 2 次）
    │     ↓
    └── 推送（定时推送 + 重大事件破例）
          ↓
    用户反馈（like / dislike / irrelevant）
          ↓
    偏好向量更新 → 影响下一轮排序
```

### 2.4 Agent 工作流节点概览

系统采用 **LangGraph StateGraph** 构建有状态工作流，核心节点及其工具调用类型：

| 节点 | 职责 | 调用方式 |
|------|------|---------|
| `understand_intent` | 识别触发类型（daily_briefing / manual_search / feedback_update） | FC |
| `collect_sources` | 三路并行：fetch_rss（FC）+ search_web（MCP SSE）+ recall_memory（FC） | FC + MCP |
| `enrich_metadata` | LLM 提取 category / keywords / importance（1-5） | FC |
| `normalize_items` | 条目字段标准化，统一格式便于后续处理 | FC |
| `planner` | 自主决策下一步：Continue 继续 / SearchMore 补充搜索 / PushNow 破例推送 | FC |
| `deduplicate` | 向量去重（0.88 阈值 + 模糊区间 [0.70, 0.88) LLM 裁决） | FC |
| `rank_items` | 多因子加权排序（冷启动/有反馈动态切换权重） | FC |
| `generate_briefing` | LLM 生成结构化 JSON 简报 | FC |
| `reflect` | 质量评分 + 矛盾检查 + 重试判断（三个维度） | FC |
| `push_notification` | 简报推送（定时 + 重大事件破例） | MCP (stdio) |
| `update_memory` | 更新偏好向量 + 写入执行日志 | FC |

---

## 3. 功能模块设计

### 3.1 优先级划分说明

| 优先级 | 定义 | MVP 约束 |
|-------|------|---------|
| **P0** | 必须实现，MVP 核心闭环缺一不可 | 不可裁剪 |
| **P1** | 重要增强，体现 Agent 差异化价值 | 大部分应实现 |
| **P2** | 锦上添花，可在后续迭代中补充 | 按资源决定 |

### 3.2 功能模块详情

#### P0 功能（核心闭环）

| 模块 | 功能 | 详细说明 |
|------|------|---------|
| **采集引擎** | RSS 订阅源采集 | 使用 feedparser 定时拉取用户配置的 RSS/Atom 源，支持多源并发采集 |
| **采集引擎** | 意图理解（understand_intent） | 识别当前任务类型：daily_briefing / manual_search / feedback_update，决定后续流程 |
| **采集引擎** | 三路并行采集（collect_sources） | RSS 采集 + 搜索补充 + 记忆召回三条路径同时执行，减少总延迟 |
| **采集引擎** | 元数据增强（enrich_metadata） | LLM 对每条原始条目提取 category / keywords / importance 1-5 分 |
| **采集引擎** | 条目标准化（normalize_items） | 统一字段格式，便于后续去重和排序处理 |
| **规划引擎** | 自主规划（planner） | LLM 决策是否补充搜索、是否破例推送。输出 JSON action：{Continue, SearchMore, PushNow}。体现 Agent 的「自主规划」差异化能力 |
| **去重模块** | 向量去重 | ChromaDB 计算标题/内容的 cosine 相似度，0.88 为去重阈值；[0.70, 0.88) 模糊区间提交 LLM 裁决 |
| **去重模块** | 条目关系记录 | item_relations 表记录去重关系（duplicate_of / related_to / merged_into），使去重结果可解释 |
| **去重模块** | 去重阈值校准脚本 | 提供 `calibrate_dedup.py`：人工标注样本 → 计算 P/R/F1 曲线 → 选最优阈值 |
| **排序模块** | 多因子加权排序 | `final_score = w1·similarity + w2·recency + w3·preference + w4·importance` |
| **排序模块** | 冷启动 → 偏好自适应切换 | 冷启动（反馈 < 3 条）：w1=0.40, w2=0.25, w3=0.10, w4=0.25；有反馈后（反馈 >= 3 条）：w1=0.30, w2=0.20, w3=0.40, w4=0.10 |
| **排序模块** | 因子预处理 | Min-Max 归一化至 [0,1]；feedback_bias（正向 +0.15 / 负向 -0.10）叠加到 preference 因子 |
| **排序模块** | 时间衰减预筛 | 半衰期公式 `exp(-delta_t / 24h)`，过时条目跳过排序，避免无效向量计算 |
| **排序模块** | LLM 重要性评估 | LLM 对每条条目评估重要性 1-5 分，作为独立排序因子 |
| **摘要生成** | LLM 结构化摘要 | 使用 LLM 对每条条目生成结构化摘要（关键信息、核心观点、来源引用） |
| **简报生成** | 结构化 JSON 输出 | 输出含重要性标注（1-5 级）和来源 URL 引用的结构化简报，可校验可评分可复用 |
| **简报生成** | 简报 JSON Schema | 标准格式：`{date, category, summary, items[{title, summary, importance, source_url, source_name, similar_count}], quality}` |
| **反思审查** | 质量审查与重试 | LLM 审查简报质量：完整性、去重遗漏、可追溯性三个维度。`brief_quality.score < 0.7` 触发重写，最多 2 次重试 |
| **反思审查** | 矛盾检查 | 反思节点检查简报中是否存在自相矛盾的信息 |
| **用户配置** | Goal 文本 + LLM 结构化提取 | 用户以自然语言描述关注目标（Goal），LLM 自动提取 interest_keywords、preferred_sources 等结构化字段 |
| **数据存储** | SQLite 结构化存储 | 存储用户、订阅源、条目、反馈、执行日志等关系数据，启用 WAL 模式 |
| **数据存储** | ChromaDB 向量存储 | 存储条目 embedding、用户偏好向量、领域知识种子数据 |

#### P1 功能（重要增强）

| 模块 | 功能 | 详细说明 |
|------|------|---------|
| **推送机制** | 重大事件破例推送 | LLM 评估 importance >= 4 的事件在简报中以突出方式展示，打破"定时推送"的常规 |
| **排序模块** | EMA 偏好更新 | 用户反馈后偏好向量使用指数移动平均（EMA）平滑更新，防止单次反馈剧烈波动 |
| **排序模块** | 来源多样性加分 | 同一事件多角度报道合并后获得 source_diversity_bonus（+0.05），鼓励多源验证 |
| **排序模块** | 反馈权重差异化 | positive +0.15 / negative -0.10 / irrelevant -0.15，"不相关"信号衰减最快 |
| **排序模块** | 跨类别配额 | 排序后按用户话题数均分配额，防止某类话题垄断简报（防信息茧房） |
| **反馈处理** | 三级反馈（like/dislike/irrelevant） | 用户对简报条目进行点赞/踩/不相关三级反馈，"不相关"从候选集移除此类内容 |
| **反馈处理** | 偏好向量正负分离 | 分别维护 v_like（点赞条目向量均值）和 v_dislike（踩条目向量均值），偏好表达更精细 |
| **反馈处理** | 反馈子图独立触发（feedback_workflow） | 反馈处理从主流程解耦为独立子图，支持异步处理 |
| **记忆系统** | 长期记忆（ChromaDB 用户偏好向量） | 基于历史反馈持续更新的用户兴趣向量，影响排序权重 |
| **记忆系统** | 语义记忆种子数据 | MVP 阶段手动维护种子数据（领域关键词、重要来源），不做全量 RAG |
| **记忆系统** | 超窗对话 LLM 摘要压缩 | 超出短期记忆窗口（15 轮）的早期对话通过 LLM 生成摘要，压缩后存入长期记忆 |
| **执行仪表盘** | Streamlit 状态展示 | 展示执行成功率、耗时、去重率、反馈率等历史指标 |
| **容错设计** | 条件边空结果回退 | 去重后剩余 < 3 条时自动回退到采集节点，扩大时间窗/来源 |
| **容错设计** | Scheduler 稳定性 | APScheduler 捕获异常后继续下一次定时任务，单次失败不影响后续调度 |
| **日志系统** | 结构化日志与执行追踪 | structlog 结构化日志 + execution_logs（session/turn/event 三级）+ run_logs（运行指标） |
| **部署** | Docker Compose 一键部署 | 打包 Agent + Streamlit + ChromaDB + MCP Server，`docker compose up` 一键启动 |

#### P2 功能（后续迭代）

| 模块 | 功能 | 详细说明 |
|------|------|---------|
| **搜索补充** | MCP Web Search | 当 RSS 采集不足时，通过 MCP Search 服务（SSE 模式）搜索 Web 作为补充 |
| **记忆系统** | 情节记忆向量化检索 | 情节记忆摘要向量化存入 ChromaDB，支持相似执行经验检索 |
| **记忆系统** | 主动追问式偏好校准 | Agent 发现偏好信号冲突时主动问用户澄清 |
| **多用户** | 用户认证（JWT） | 支持多用户使用，各自独立的偏好和订阅源 |
| **多模态** | 多语言 Embedding（BGE-M3） | 支持英文等多语言信息源 |
| **外部推送** | Telegram Bot | 增加 Telegram 推送渠道作为应用内推送的补充 |

---

## 4. 技术架构选型

### 4.1 整体架构

FeedLens 采用**六层 Agent 架构**（感知层 → 规划层 → 大脑层 → 工具层 → 记忆层 → 展示层），以 LangGraph StateGraph 为核心编排框架。

```
┌─────────────────────────────────────────────────────────┐
│                     展示层 (Streamlit)                    │
│  配置界面 | 简报阅读 | 反馈操作 | 执行仪表盘               │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│                     大脑层 (LLM)                         │
│          DeepSeek 主力 + 通义千问 fallback                │
├──────────────────────┬──────────────────────────────────┤
│                     规划层                              │
│   LangGraph StateGraph | ReAct + Reflection              │
│   understand_intent | plan | 条件边                      │
├──────────────────────┬──────────────────────────────────┤
│       ┌──────────────┴──────────────┐                    │
│       │         工具层              │                    │
│   ┌───┴───┐  ┌───┴───┐  ┌───┴───┐                    │
│   │  FC   │  │  MCP  │  │  MCP  │                    │
│   │ Chroma│  │Search │  │ Push  │                    │
│   │  DB/  │  │ (SSE) │  │(stdio)│                    │
│   │ SQLite│  │ :8100 │  │       │                    │
│   └───────┘  └───────┘  └───────┘                    │
├─────────────────────────────────────────────────────────┤
│                     记忆层                              │
│   短期(15轮State) | 长期(ChromaDB) | 语义(ChromaDB)       │
│   情节(SQLite) | 超窗压缩(LLM)                            │
└─────────────────────────────────────────────────────────┘
```

### 4.2 技术栈决策

| 层级 | 技术选型 | 决策说明 |
|------|---------|---------|
| **Agent 框架** | **LangGraph StateGraph** | ⭐ 硬约束 — 全部 9 份文档共识，不可更换。TypedDict 定义共享状态，通过节点+边实现有状态可分支流程 |
| **LLM 后端** | **DeepSeek（主力）+ 通义千问（fallback）** | 国内可用、无需科学上网、性价比高、支持 Function Calling。双供应商冗余提升可用性 |
| **Embedding** | **bge-small-zh-v1.5（本地）** | ⭐ 决策结果 — 免费、无速率限制、中文效果好。本地离线运行，零 API 成本。153M 参数，推理速度约 50ms/条 |
| **向量数据库** | **ChromaDB** | ⭐ 硬约束 — 轻量、本地运行、MVP 阶段够用。FC 直接调用 SDK，不做 MCP 封装 |
| **关系数据库** | **SQLite + WAL 模式** | ⭐ 硬约束 — 零部署、单文件、MVP 友好。使用原生 SQL（非 ORM），透明可调试 |
| **RSS 解析** | **feedparser** | ⭐ 硬约束 — 成熟稳定的 RSS/Atom 解析库 |
| **前端** | **Streamlit** | ⭐ 硬约束 — 配置界面 + 简报阅读 + 反馈操作 + 执行仪表盘 |
| **调度** | **APScheduler** | ⭐ 硬约束 — 定时调度基础设施，cron 表达式触发工作流 |
| **中文分词** | **jieba + 自定义停用词表** | 中文关键词提取和匹配的基础设施 |
| **日志** | **structlog** | 结构化日志输出，便于解析和监控 |
| **工具调用** | **FC + MCP 混合** | FC：ChromaDB SDK、SQLite、RSS 解析等紧耦合操作；MCP Search（SSE，:8100）+ MCP Push（stdio） |
| **MCP Server 数量** | **2 个（search + push）** | ⭐ 决策结果 — 减少进程管理和代码量。Push 本地操作用 stdio 最简，Search 外部 API 用 SSE 流式 |
| **搜索服务** | **商业搜索 API（SSE MCP）** | 开箱即用，不作为 RSS 替代，仅作为补充 |
| **短期记忆** | **15 轮 + 超窗 LLM 压缩** | ⭐ 决策结果 — 10 轮过紧，15 轮有余量，压缩保留长期上下文 |
| **部署方案** | **本地开发 + Docker Compose 交付** | ⭐ 决策结果 — 开发效率优先，交付用容器化，`docker compose up` 一键启动 |
| **用户认证** | **不需要（单用户）** | ⭐ 决策结果 — MVP 不验证认证假设 |
| **ORM** | **原生 SQL** | ⭐ 决策结果 — 透明可调试，适合 MVP 阶段快速迭代 |

### 4.3 核心 Agent 工作流

```
[入口] -> understand_intent --> daily_briefing -> plan -> [三路并行]
                |                              |        |-- fetch_rss (feedparser, FC)
                |-- manual_search -------------|        |-- search_web (MCP Search SSE)
                |                              |        |-- recall_memory (ChromaDB, FC)
                |-- feedback_update -----------|        |
                                                        v
                                           enrich_metadata (LLM: category/keywords/importance 1-5)
                                                        |
                                                        v
                                           normalize_items (字段标准化)
                                                        |
                                                        v
                                           planner (LLM决策: Continue/SearchMore/PushNow)
                                                    ┌──┘
                              ┌────── SearchMore? ──
                              |                       v
                              |           collect_sources (回退补充采集, 最多2次)
                              |                       |
                              |                       v
                              └── Continue ─────────> dedup (向量0.88阈值 + 模糊区间[0.70,0.88)LLM裁决)
                                                        |
                              ┌────── 剩余条目 >= 3? ────── NO -> 回退采集（扩大时间窗/来源）
                              |                           |
                              v YES                       v
                                           rank (多因子加权: 冷启动/有反馈权重切换)
                                                        |
                                                        v
                                           summarize (LLM 结构化摘要)
                                                        |
                                                        v
                                           generate_brief (JSON: {date, category, items[], quality{}})
                                                        |
                                                        v
                                           reflect (审查: 完整性/去重遗漏/可追溯性/矛盾)
                                                    ┌──┘
                                           ┌── score >= 0.7? ──> YES -> deliver + push
                                           |        |
                                           └── NO (<=2次重试) -> revise -> reflect
                                                        |
                                                    fail (2次仍<0.7 -> 降级交付 + 记录日志)
```

### 4.4 Harness 工程：Session / Turn / Event 层级

```text
Session (一次用户会话，对应一次 APScheduler 触发或用户手动操作)
|
|-- Turn-1 (daily_briefing，APScheduler 触发)
|     |-- Event: understand_intent
|     |-- Event: collect_sources (三路并行)
|     |-- Event: enrich_metadata
|     |-- Event: normalize_items
|     |-- Event: planner (????, ????? collect_sources)
|     |-- Event: deduplicate
|     |-- Event: rank_items
|     |-- Event: generate_briefing
|     |-- Event: reflect (可能重试)
|     |-- Event: push_notification
|     └── Event: update_memory
|
|-- Turn-2 (用户反馈 like/dislike/irrelevant，feedback_update 触发)
|     └── Event: update_preference
|
└── Turn-3 (第 2 天，APScheduler 再次触发)
      └── ...（同 Turn-1 流程）
```

### 4.5 工具调用策略（FC + MCP）

系统采用混合工具调用策略，按工具特征分流：

| 类型 | 特征 | 工具列表 | 部署模式 |
|------|------|---------|---------|
| **MCP Server** | 需独立部署、涉及外部系统、有状态 | `search_web`（搜索采集）、`push_notification`（简报推送） | Search: SSE（:8100）；Push: stdio |
| **Function Calling** | 逻辑简单、参数明确、进程内 SDK 调用 | `fetch_rss`、`enrich_metadata`、`normalize_items`、`planner`、`deduplicate`、`rank_items`、`generate_briefing`、`reflect`、`update_preference`、`db_read`、`db_write`、`vector_search`、`vector_add` | 进程内直接调用 |

> **选型原则**：工具需独立部署或有状态 -> MCP；工具是纯函数逻辑或进程内 SDK 调用 -> FC。

---

## 5. 核心数据模型

### 5.1 结构化数据（SQLite）

| 表名 | 核心字段 | 说明 |
|------|---------|------|
| **users** | id, goal_text, interests_json, created_at, updated_at | 单用户，存储 Goal 文本及 LLM 提取的结构化兴趣字段（topics / keywords / preferred_sources） |
| **sources** | id, user_id, url, name, category, authority_score(0-1), is_active | 订阅源配置，RSS/搜索，含来源可信度评分 |
| **feed_items** | id, source_id, title, url, content, summary, author, published_at, fetched_at, embedding_id, importance(1-5), category, keywords | 原始条目，含 LLM enrich_metadata 后的分类/关键词/重要性 |
| **item_relations** | id, item_a_id, item_b_id, relation_type(duplicate_of/related_to/merged_into), similarity_score, dedup_method(vector_threshold/llm_adjudication) | 条目关系记录，去重结果可解释 |
| **briefings** | id, user_id, date, content_json, quality_score, quality_detail({completeness, relevance, coherence}), retry_count, created_at | 简报批次记录 |
| **briefing_items** | id, briefing_id, item_id, rank, final_score, is_highlight | 简报与条目的多对多关联 |
| **user_feedback** | id, user_id, brief_id, item_id, feedback_type(like/dislike/irrelevant), created_at | 用户三级反馈记录 |
| **user_preferences** | id, user_id, like_vector(blob), dislike_vector(blob), updated_at | 正负分离的偏好向量，存入 ChromaDB 并保留 SQLite 索引 |
| **execution_logs** | id, session_id, turn, event, node_name, status(success/error/skipped), duration_ms, metadata(JSON), created_at | 三级日志：session -> turn -> event |
| **memory_context** | id, session_id, turn_id, content, summary, created_at | 超窗压缩后的对话摘要，保留长会话上下文 |

### 5.2 向量数据（ChromaDB Collections）

| Collection | 核心字段 | 用途 |
|-----------|---------|------|
| **feed_items** | id, title, content, embedding, metadata(category, source, importance, date) | 条目向量检索与去重 |
| **user_preference** | user_id, like_embedding, dislike_embedding, updated_at | 用户长期偏好，正负分离 |
| **domain_knowledge** | id, topic, content, embedding, seed_flag | 语义记忆种子数据（MVP 手动维护） |

### 5.3 LangGraph State（TypedDict）

| 字段 | 类型 | 说明 |
|------|------|------|
| trigger_type | str | 触发类型：daily_briefing / manual_search / feedback_update |
| user_goal | str | 用户输入的目标描述 |
| structured_goal | dict | LLM 提取的结构化字段（topics / keywords / preferred_sources） |
| messages | list | 对话历史消息（15 轮滑动窗口） |
| raw_items | list[FeedItem] | 采集到的原始条目 |
| normalized_items | list[dict] | 条目标准化后的统一格式 |
| deduped_items | list[DedupedItem] | 去重后的条目 |
| planner_decision | dict | Planner 决策结果：{action, reason, push_immediate} |
| planner_search_count | int | Planner 触发补充搜索的次数（上限 2） |
| item_relations | list[dict] | 去重关系记录 |
| ranked_items | list[RankedItem] | 排序后的条目 |
| briefing | BriefingOutput | 最终简报输出（JSON） |
| brief_quality | dict | {completeness, relevance, coherence, score} |
| retry_count | int | 反思重试计数（上限 2） |
| reflection_notes | str | 反思审查备注 |
| feedback_history | list[FeedbackSignal] | 本轮反馈记录 |
| short_term_memory | list[dict] | 15 轮滑动窗口缓存 |
| retrieved_memories | list[dict] | 从长期记忆中检索的相关记忆 |
| execution_metrics | dict | 执行指标（耗时、去重率、采集数等） |

---

## 6. API 接口设计

### 6.1 Function Calling 工具接口

FC 工具为进程内直接调用，LLM 自主判断调用时机：

| 工具名 | 方法 | 参数 | 返回 | 说明 | 选型理由 |
|--------|------|------|------|------|---------|
| `fetch_rss` | `fetch` | `sources: list[str]` | `list[dict]` | 并行采集多个 RSS 源 | RSS 解析是纯函数逻辑，进程内调用延迟最低 |
| `enrich_metadata` | `enrich` | `items: list[dict]` | `list[dict]` | LLM 提取 category / keywords / importance | 单次 LLM 推理无持久状态，FC 调用最简单 |
| `normalize_items` | `normalize` | `items: list[dict]` | `list[dict]` | 统一字段格式 | 纯数据转换无 I/O，FC 开销最小 |
| `planner` | `plan` | `items: list[dict], user_goal: str, search_count: int` | `dict(action, reason, push_immediate)` | LLM 自主决策下一步动作 | Agent 自主规划能力的核心节点 |
| `deduplicate` | `dedup` | `items: list[dict], threshold: float = 0.88` | `(list[dict], list[dict])` | 向量去重 + 关系记录 | ChromaDB SDK 进程内调用，FC 无需 IPC 开销 |
| `rank_items` | `rank` | `items: list[dict], user_prefs: dict, feedback_count: int` | `list[dict]` | 多因子加权排序 | 纯计算逻辑无 I/O，FC 性能最优 |
| `generate_briefing` | `generate` | `ranked_items: list[dict], style: str = "concise"` | `dict` | 生成结构化 JSON 简报 | 单次 LLM 推理，FC 调用最简单 |
| `reflect` | `reflect` | `brief: dict` | `dict` | 质量评分 + 重试判断 | 纯计算 + 单次 LLM 调用，FC 最简单 |
| `update_preference` | `update` | `feedback: dict, user_id: int` | `dict` | 更新偏好向量 + 正负分离 | 最终调用 db_write（FC），链路最短 |
| `db_read` | `read` | `table: str, conditions: dict` | `list[dict]` | SQLite 读操作 | 无状态查询，进程内调用延迟最低 |
| `db_write` | `write` | `table: str, data: dict` | `bool` | SQLite 写操作（WAL 模式） | 单次写操作，进程内调用延迟最低 |
| `vector_search` | `search` | `collection: str, query: str, top_k: int = 5` | `list[dict]` | ChromaDB 相似度检索 | ChromaDB SDK 进程内调用，FC 无需 IPC |
| `vector_add` | `add` | `collection: str, docs: list[str], metadatas: list[dict]` | `list[str]` | ChromaDB 写入向量 | ChromaDB SDK 进程内调用，FC 无需 IPC |

### 6.2 MCP 协议接口

MCP Server 为独立进程，通过标准化 MCP 协议连接：

| 服务 | 传输 | 端口 | 方法签名 | 说明 | 选型理由 |
|------|------|------|---------|------|---------|
| **MCP Search** | SSE | 8100 | `search(query: str, max_results: int = 10) -> list[dict]` | Web 搜索采集，流式返回结果 | 搜索 API 是外部 HTTP 服务，需独立进程管理连接池；SSE 适合流式返回场景 |
| **MCP Push** | stdio | — | `push(brief: dict, user_id: int, immediate: bool = False) -> bool` | 简报推送通知（应用内），`immediate=true` 表示重大事件破例 | 推送服务随主进程启停，无需管理端口；MVP 单机部署 stdio 最简 |

### 6.3 Agent 内部节点接口（LangGraph State）

节点间通过共享 State 传递数据，无需 HTTP 路由：

| 节点 | 输入（State 字段） | 输出（写入 State 字段） | 说明 |
|------|-------------------|------------------------|------|
| understand_intent | user_goal, last_state | trigger_type, structured_goal | 识别任务类型 + 结构化提取 |
| collect_sources | structured_goal, sources | raw_items | 三路并行采集 |
| enrich_metadata | raw_items | raw_items (含 category/keywords/importance) | LLM 元数据增强 |
| normalize_items | raw_items | normalized_items | 字段标准化 |
| planner | normalized_items, user_goal | planner_decision, raw_items(可能回退) | 自主决策：Continue/SearchMore/PushNow |
| deduplicate | normalized_items | deduped_items, item_relations | 向量去重 + 关系记录 |
| rank_items | deduped_items, user_preferences | ranked_items | 多因子排序 |
| generate_briefing | ranked_items | briefing, brief_quality | JSON 简报生成 |
| reflect | briefing, brief_quality | quality_score, retry_count, reflection_notes | 质量审查 |
| push_notification | briefing | delivery_status | 推送交付 |
| update_memory | feedback_history, briefing | 更新长期记忆 + 写入日志 | 偏好更新 + 执行记录 |

### 6.4 Streamlit 页面路由

| 路由 | 功能 | 说明 |
|------|------|------|
| `/` | 简报首页 | 展示最新简报，按重要性突出排列，支持历史浏览 |
| `/config` | 配置管理 | 管理 RSS 源、Goal 文本、关键词 |
| `/history` | 历史简报 | 历史简报浏览与检索 |
| `/feedback` | 反馈操作 | 三级反馈按钮（like/dislike/irrelevant）+ 偏好变化趋势 |
| `/dashboard` | 执行仪表盘 | 执行成功率、耗时、去重率、反馈率等历史指标 |

---

## 7. 里程碑规划

### Phase 1（Week 1-2）：项目骨架 + 数据模型

| 交付物 | 验收标准 |
|--------|---------|
| 项目目录结构 | 符合模块化设计：config / models / nodes / tools / utils |
| SQLite 表结构初始化 | 全部 10 张表创建成功，WAL 模式开启 |
| ChromaDB 集合初始化 | items / preferences / domain_knowledge 三个集合创建成功 |
| LangGraph StateGraph 骨架 | 10 个节点定义完成，边连接正确，空实现可跑通 |
| bge-small-zh-v1.5 模型加载 | 本地加载成功，推理速度 < 100ms/条 |
| 基础 Streamlit 界面骨架 | 5 个页面路由可用 |

### Phase 2（Week 3-4）：信息采集 + 智能去重

| 交付物 | 验收标准 |
|--------|---------|
| `fetch_rss` FC 工具 | feedparser 并行采集 3+ RSS 源，解析成功 |
| `search_web` MCP Server（SSE） | 搜索 API 封装，SSE 流式返回，监听 :8100 |
| `enrich_metadata` + `normalize_items` | LLM 提取分类/关键词/重要性，字段统一格式化 |
| `deduplicate` 节点 | 0.88 阈值向量去重 + [0.70, 0.88) 模糊区间 LLM 裁决 |
| `item_relations` 表写入 | 去重关系正确记录 |
| `calibrate_dedup.py` 脚本 | 标注样本 -> P/R/F1 曲线 -> 最优阈值输出 |
| 条件边空结果回退逻辑 | 去重后 < 3 条自动回退采集 |

### Phase 3（Week 5-6）：偏好排序 + 简报生成

| 交付物 | 验收标准 |
|--------|---------|
| `rank_items` 节点 | 冷启动 (0.40/0.25/0.10/0.25) 和有反馈 (0.30/0.20/0.40/0.10) 动态切换 |
| 时间衰减预筛 | 半衰期 tau=24h，过时内容跳过排序 |
| Min-Max 归一化 + feedback_bias | 所有因子归一化至 [0,1]，feedback_bias 叠加 |
| `generate_briefing` 节点 | 输出标准 JSON Schema，含 importance + source_url + similar_count |
| JSON -> Markdown 渲染 | 简报正确渲染，计数标注显示 |
| `reflect` 节点 | 三维度审查（完整性/去重遗漏/可追溯性）+ 矛盾检查 |
| APScheduler 定时触发 | cron 每日定时触发完整工作流 |

### Phase 4（Week 7-8）：推送 + 反馈 + 记忆

| 交付物 | 验收标准 |
|--------|---------|
| `push_notification` MCP Server（stdio） | 推送服务作为子进程运行 |
| 重大事件破例推送 | importance >= 4 条目突出展示 |
| 三级反馈 UI + `feedback_workflow` 子图 | like/dislike/irrelevant 按钮，反馈异步处理 |
| 偏好向量更新 | EMA 平滑 + 正负分离（v_like / v_dislike）+ 权重差异化 |
| 短期记忆 15 轮滑动窗口 + 超窗 LLM 压缩 | 超窗对话生成摘要写入 memory_context |
| 偏好权重自动清理 | 低于 0.1 自动清理 |
| 冷启动 -> 偏好自适应切换逻辑 | 反馈数 >= 3 条时权重自动切换 |

### Phase 5（Week 9-10）：集成测试 + 交付

| 交付物 | 验收标准 |
|--------|---------|
| 端到端集成测试 | 从 Goal 设置到简报推送全流程跑通，无报错 |
| structlog 结构化日志 | 全部节点日志结构化输出 |
| execution_logs 三级日志 | session/turn/event 正确记录，含 duration_ms |
| 来源多样性加分 + 跨类别配额 | 排序中正确生效 |
| Streamlit 执行仪表盘 | 展示成功率、耗时、去重率、反馈率 |
| Scheduler 异常容错 | 单次失败不阻塞下次执行 |
| 30 天数据清理策略 | 定期清理过期 raw_items 和 execution_logs |
| Docker Compose 一键部署 | `docker compose up` 所有组件正常启动 |
| README + 部署指南 | 含环境配置、启动命令、依赖列表、架构说明 |

---

## 8. 其它重要补充

### 8.1 冷启动策略

| 维度 | 冷启动策略 | 切换条件 |
|------|---------|---------|
| 排序权重 | 相似度优先：w1=0.40, w3=0.10 | 用户反馈 >= 3 条 -> 偏好优先：w1=0.30, w3=0.40 |
| 偏好向量 | 使用 Goal 文本提取的 keywords 生成初始偏好向量 | 有真实反馈后逐步替换为 v_like / v_dislike |
| RSS 源 | LLM 根据 Goal 文本推荐初始列表 | 用户可在配置页面手动增删 |
| 语义记忆 | 手动维护种子数据（领域知识、概念关系） | 数据积累后逐步自动补充 |
| 偏好收敛 | 三级反馈设计：irrelevant（-0.15）衰减 > dislike（-0.10），少量反馈即可快速收敛 | feedback_count 作为置信度指标 |

### 8.2 错误处理与容错

| 场景 | 处理策略 |
|------|---------|
| RSS 源不可达 | 跳过该源，记录 warning 日志，继续采集其他源 |
| 搜索 API 超时 | 降级为仅使用 RSS 采集结果，记录 warning |
| 去重后条目不足（< 3 条） | 条件边自动回退到采集节点，扩大时间窗/增加来源 |
| LLM 调用失败 | 重试 1 次；若仍失败，降级使用规则模板生成简报 |
| 简报质量连续不达标 | 2 次重试后接受当前最佳结果，记录日志供后续分析 |
| APScheduler 任务异常 | 捕获异常，记录 error 日志，继续下一次定时任务 |
| SQLite 并发冲突 | WAL 模式 + 事务包裹，自动重试 |
| 偏好权重异常 | 权重 < 0.1 自动清理，防止噪声干扰 |

### 8.3 数据生命周期管理

| 数据类型 | 保留策略 | 清理方式 |
|---------|---------|---------|
| raw_items / feed_items | 30 天 | 定时任务清理过期记录 |
| execution_logs | 30 天 | 定时任务清理过期记录 |
| briefs / feedback | 永久保留 | 不清理 |
| ChromaDB 向量 | 随 raw_items 清理同步删除 | 关联清理 |
| 短期记忆 | 15 轮滑动窗口 | 超窗 LLM 压缩写入长期记忆 |
| 偏好权重 | 低于 0.1 自动清理 | 自动清理 |

### 8.4 质量保证

- **去重效果**：提供 `calibrate_dedup.py` 校准脚本 + 测试数据构造方法（手动构造 20+ 对测试数据，调整阈值至准确率 >= 90%），数据驱动而非拍脑袋定阈值
- **去重阈值校准流程**：
  1. 人工标注 200 对样本（正例/负例）
  2. 计算每对 cosine 相似度
  3. 遍历阈值 0.70-0.95（步长 0.01），计算各阈值 P/R/F1
  4. 绘制 P/R/F1 曲线，选 F1 最优阈值
  5. 更新配置文件中的 `dedup_threshold` 参数
- **简报质量**：反思节点在完整性、去重遗漏、可追溯性三个维度审查，含矛盾检查
- **双 LLM 冗余**：DeepSeek 主力 + 通义千问 fallback，单 LLM 不可用时自动切换

### 8.5 Embedding 工程细节

- 选用 bge-small-zh-v1.5（本地），首次下载显示进度条
- 备选方案：LLM API（text-embedding-v3）做 embedding
- 中文支持：使用 jieba 分词 + 自定义停用词表，提高关键词提取精度
- 向量存储于 ChromaDB，FC 直接调用 SDK（不通过 MCP）

### 8.6 关键配置参数

| 参数 | 默认值 | 说明 | 可调 |
|------|--------|------|------|
| `dedup_threshold` | 0.88 | 去重相似度阈值 | 是（校准脚本） |
| `dedup_llm_lower` | 0.70 | 模糊区间下界（低于此值不重复） | 是 |
| `half_life_hours` | 24 | 时间衰减半衰期 tau | 是 |
| `short_term_window` | 15 | 短期记忆滑动窗口轮数 | 是 |
| `max_retry` | 2 | 反思重试上限 | 是 |
| `quality_threshold` | 0.7 | 简报质量评分阈值 | 是 |
| `min_items_for_brief` | 3 | 生成简报的最低条目数 | 是 |
| `breaking_news_score` | 0.85 | 重大事件破例推送阈值 | 是 |
| `breaking_news_freshness_hours` | 2 | 重大事件时效阈值 | 是 |
| `cold_start_feedback_threshold` | 3 | 冷启动->偏好优先切换所需反馈数 | 是 |
| `preference_cleanup_threshold` | 0.1 | 偏好权重自动清理阈值 | 是 |
| `data_retention_days` | 30 | 过期数据清理天数 | 是 |
| `feedback_bias_positive` | 0.15 | 正向反馈偏置 | 是 |
| `feedback_bias_negative` | -0.10 | 负向反馈偏置 | 是 |
| `feedback_bias_irrelevant` | -0.15 | 不相关反馈偏置 | 是 |
| `source_diversity_bonus` | 0.05 | 来源多样性加分 | 是 |
| `w_sim_cold` / `w_sim_warm` | 0.40 / 0.30 | 相似度权重（冷启动/有反馈） | 是 |
| `w_recency` | 0.25 / 0.20 | 时间衰减权重（冷启动/有反馈） | 是 |
| `w_pref_cold` / `w_pref_warm` | 0.10 / 0.40 | 偏好权重（冷启动/有反馈） | 是 |
| `w_importance` | 0.25 / 0.10 | 重要性权重（冷启动/有反馈） | 是 |

---

## 附录：决策来源映射

本文档中的每项设计决策均可追溯至以下输入文档：

| 输入 | 文件 | 内容 |
|------|------|------|
| 共识点（18 条） | `共识点.md` | 9 份原始 MVP 文档的共识提取 |
| 独特点（72 条） | `独特点.md` | 9 份原始 MVP 文档的独特点提取 |
| 决策清单（28 项） | `决策清单.md` | 18 项冲突决策 + 10 项实现选型 |

**核心决策索引：**

| 编号 | 决策项 | 涉及章节 |
|------|--------|---------|
| **P1** | 简报生成驱动模式 -> 流程驱动 | §3、§4.3 |
| **P2** | 推送机制 -> 定时 + 破例 + 应用内 | §3（P1 推送）、§6.2 |
| **P3** | 用户配置粒度 -> Goal 文本 + LLM 提取 | §3（P0 用户配置）、§5.1 users |
| **P4** | 去重结果处理 -> 计数标注 | §3（P0 去重）、§3（简报 JSON Schema） |
| **P5** | 搜索采集角色 -> RSS 为主 + 搜索补充 | §3（P2 搜索补充）、§6.2 |
| **P6** | 简报输出风格 -> 结构化 JSON | §3（简报 JSON Schema） |
| **P7** | 用户反馈选项 -> 三级 like/dislike/irrelevant | §3（P1 反馈处理）、§8.6 |
| **P8** | 用户认证 -> 不需要（单用户） | §4.2 |
| **T1** | MCP 传输模式 -> Push stdio / Search SSE | §4.5、§6.2 |
| **T2** | 向量去重 -> 0.88 + 纯向量 + LLM 裁决 + 校准 | §3（P0 去重）、§8.4 |
| **T3** | 排序权重 -> 冷启动相似度优先 -> 偏好优先 | §3（P0 排序）、§8.1 |
| **T4** | Embedding 模型 -> 本地 bge-small-zh-v1.5 | §4.2 |
| **T5** | MCP Server 数量 -> 2 个 + FC 调用 DB/向量 | §4.2、§4.5 |
| **T6** | 短期记忆窗口 -> 15 轮 + 超窗压缩 | §4.2、§5.1 memory_context |
| **T7** | 时间衰减函数 -> 半衰期 tau=24h | §3（P0 排序）、§8.6 |
| **T8** | 反思重试 -> 最多 2 次 | §3（P0 反思）、§4.3 工作流 |
| **T9** | 向量库交互 -> FC 直接调用 ChromaDB SDK | §4.2、§4.5 |
| **T10** | 部署方案 -> 本地开发 + Docker Compose 交付 | §4.2、§7 Phase 5 |
| **I1** | 偏好更新算法 -> 简单累加 | §3（P1 排序） |
| **I2** | ORM 选型 -> 原生 SQL | §4.2 |
| **I3** | RSS 采集工具 -> feedparser | §4.2 |
| **I4** | 搜索服务 -> 商业搜索 API（SSE MCP） | §4.2、§6.2 |