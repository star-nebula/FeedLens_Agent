# FeedLens — 智能信息简报 Agent MVP 设计文档

> **版本**：v1.0 | **状态**：定稿 | **日期**：2026-06-18

---

## 1. 项目概述（愿景与核心价值）

### 1.1 项目定位

FeedLens 是一个**主动式信息聚合 Agent**。它不是被动问答工具，而是能**定时自主采集、智能去重、偏好排序、生成简报并推送**给用户的智能体系统。核心差异化在于展示 Agent 的「自主规划 + 定时执行 + 个性化筛选」能力。

### 1.2 核心价值主张

| 维度 | 传统 RSS 阅读器 | FeedLens Agent |
|------|----------------|----------------|
| 采集方式 | 被动拉取，用户自行浏览 | 定时自主采集 + 搜索补充 |
| 信息过滤 | 按时间排序，用户自行筛选 | 智能去重 + 偏好排序，推送高价值内容 |
| 个性化 | 基于关键词的硬匹配 | 基于用户反馈动态学习偏好向量 |
| 输出形态 | 原始条目列表 | 结构化简报（分类 + 重要性标注 + 来源引用） |
| 交互方式 | 用户主动查看 | Agent 定时推送 + 用户反馈闭环 |

### 1.3 MVP 核心假设

> **假设**：用户愿意每天收到一份「5-10 条高价值、已去重、按个人偏好排序」的信息简报，并通过反馈持续改善推送质量。

MVP 阶段的一切设计决策均围绕**最快验证此假设**展开。

---

## 2. 核心用户场景与业务闭环

### 2.1 核心用户场景

1. 用户输入一个长期关注目标（如「AI Agent 技术进展」「新能源车行业动态」），系统通过 LLM 自动提取结构化字段（关注领域、关键词、推荐 RSS 源）。
2. Agent 每天定时从多个 RSS 源并行采集最新内容；当 RSS 条目不足时，自动触发搜索 API 补充。
3. 自动去重：同一事件不同来源的报道合并为一条，标注「还有 N 篇类似报道」。
4. 根据用户偏好排序：用户历史点赞/踩/标记不相关的内容会影响后续排序权重。
5. 生成结构化简报：分类组织 + 重要性标注（1-5 级）+ 来源 URL 引用，输出 JSON 后渲染为 Markdown。
6. 推送给用户：每日固定时间通过应用内渠道推送；重大事件（score > 0.85 且时效 < 2h）破例立即推送。
7. 用户反馈「这条有价值」「这条不相关」→ Agent 学习并调整后续筛选排序。

### 2.2 业务闭环

```
用户设定 Goal
    ↓
LLM 提取结构化偏好字段
    ↓
┌───────────────────────────────────────┐
│           APScheduler 定时触发          │
└──────────────┬────────────────────────┘
               ↓
    ┌── 采集（RSS 并行 + 搜索补充）
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

### 2.3 Agent 工作流概览

系统采用 **LangGraph StateGraph** 构建有状态工作流，核心节点构成闭环：

| 节点 | 职责 | 类型 |
|------|------|------|
| `understand_intent` | 识别触发类型（daily_briefing / manual_search / feedback_update） | FC |
| `collect_sources` | 并行采集 RSS 源 + 条件触发搜索补充 | FC + MCP |
| `normalize_items` | 条目标准化（统一字段格式） | FC |
| `deduplicate` | 向量去重（0.88 阈值 + 模糊区间 LLM 裁决） | FC |
| `rank_items` | 多因子加权排序 | FC |
| `generate_briefing` | 结构化 JSON 简报生成 | FC |
| `reflect` | 质量评分 + 重试判断 | FC |
| `push_notification` | 推送简报 | MCP (stdio) |
| `update_memory` | 更新偏好向量 + 写入执行日志 | FC |

> **来源**：共识 1（LangGraph StateGraph）、共识 13（核心数据处理流水线）、独特点 7（understand_intent 节点，DeepSeek 文档）、独特点 32（normalize_items 节点，Perplexity 文档）

---

## 3. 功能模块设计

### P0 — MVP 核心功能（必须实现）

#### 3.1.1 信息采集模块

**职责**：从多个信息源并行采集最新内容。

| 子功能 | 设计决策 | 来源 |
|--------|---------|------|
| RSS 采集 | 使用 `feedparser` 解析 RSS/Atom 格式，并行采集用户配置的多个 RSS 源 | 共识 7、决策 I3 |
| 搜索补充 | 当去重后条目 < 5 条时，触发搜索 API 补充采集；搜索服务通过 MCP (SSE) 调用 | 决策 P5、共识 8、决策 T1 |
| 元数据提取 | `enrich_metadata` 节点：LLM 对每条原始条目提取 category / keywords / importance | 独特点 25（Kimi 文档） |
| 条目标准化 | `normalize_items` 节点：统一字段格式，便于后续处理 | 独特点 32（Perplexity 文档） |
| 中文分词 | 使用 `jieba` 分词 + 自定义停用词表进行中文关键词提取 | 独特点 69（Codex_Mimo 文档） |

**采集策略**：
- RSS 为主要信息源（免费、可控）
- 搜索为补充通道，仅在 RSS 不足时触发，控制 API 调用成本
- 采集结果包含：标题、摘要、正文、来源 URL、发布时间、来源名称

#### 3.1.2 智能去重模块

**职责**：识别同一事件的不同来源报道，合并为一条代表。

| 子功能 | 设计决策 | 来源 |
|--------|---------|------|
| 去重技术路线 | 纯向量去重 + 模糊区间 LLM 裁决（不增加 NER/编辑距离等第二信号） | 决策 T2 |
| 去重阈值 | ≥0.88 判定为重复；≤0.70 判定为不重复；0.70-0.88 模糊区间调用 LLM 做二元判断 | 决策 T2、独特点 42（Qwen 文档） |
| 去重结果处理 | 计数标注：保留一篇代表，简报中标注「还有 N 篇类似报道」 | 决策 P4 |
| 条目关系记录 | `item_relations` 表记录去重关系（duplicate_of / related_to / merged_into），使去重结果可解释 | 独特点 51（Codex_DeepSeek 文档） |
| 来源多样性加分 | 同一事件多角度报道合并后获得 `source_diversity_bonus = +0.05` 排序加分 | 独特点 53（Codex_DeepSeek 文档） |
| 空结果回退 | 若去重后剩余 < 3 条，自动回退到采集节点扩大时间窗/来源 | 独特点 20（GLM 文档） |
| 阈值校准 | 提供 `calibrate_dedup.py` 脚本：人工标注 200 对样本 → 计算 P/R/F1 曲线 → 选最优阈值 | 决策 T2、独特点 15（GLM 文档）、独特点 70（Codex_Mimo 文档） |

**Embedding 模型**：本地 `bge-small-zh-v1.5`（BAAI/bge-small-zh-v1.5），153M 参数，中文语义相似度表现优秀，推理速度约 50ms/条。

> **来源**：决策 T2、决策 T4、共识 11、独特点 42/51/53/20/15/70

#### 3.1.3 偏好排序模块

**职责**：根据用户偏好对去重后的条目进行多因子加权排序。

**排序公式**：

```
final_score = w₁ · similarity + w₂ · recency + w₃ · preference + w₄ · importance
```

| 因子 | 含义 | 计算方式 |
|------|------|---------|
| `similarity` | 内容与用户关注领域的相似度 | cosine(item_embedding, user_profile_embedding) |
| `recency` | 时间新鲜度 | `exp(-Δt / τ)`，τ = 24h（半衰期公式） |
| `preference` | 用户偏好匹配度 | cosine(item_embedding, user_preference_vector) |
| `importance` | 新闻重要性 | LLM 评估 1-5 分，归一化至 0-1 |

**权重策略（动态切换）**：

| 阶段 | 条件 | 权重配置 | 理由 |
|------|------|---------|------|
| 冷启动 | 用户反馈 < 3 条 | w₁=0.40, w₂=0.25, w₃=0.10, w₄=0.25 | 无偏好数据，相似度优先 |
| 有反馈 | 用户反馈 ≥ 3 条 | w₁=0.30, w₂=0.20, w₃=0.40, w₄=0.10 | 偏好数据充分，偏好优先 |

**预处理**：
- 排序前用时间衰减函数预筛：`decay = exp(-Δt / 24h)`，低于阈值的条目跳过排序，避免对过时内容做无意义的向量计算。

**归一化**：
- 排序前对所有因子做 Min-Max 归一化至 [0, 1]。
- 引入 `feedback_bias`：正向反馈 +0.15，负向反馈 -0.1，叠加到 preference 因子。

> **来源**：决策 T3、决策 T7、共识 12、独特点 3（LLM 评估重要性，GPT 文档）、独特点 6（feedback_bias + 归一化，DeepSeek 文档）、独特点 41（Decay 预筛，Qwen 文档）

#### 3.1.4 简报生成模块

**职责**：将排序后的条目组织为结构化简报。

| 子功能 | 设计决策 | 来源 |
|--------|---------|------|
| 输出格式 | LLM 输出结构化 JSON，再渲染为 Markdown | 决策 P6 |
| 重要性标注 | 每条目含 importance 字段（1-5 级 / critical-high-normal-low） | 共识 17 |
| 来源引用 | 每条目含 source_url 字段 | 共识 17 |
| 去重标注 | 计数标注：「{title}（还有 {n} 篇类似报道）」 | 决策 P4 |
| 质量评分 | `brief_quality` 结构化评分：{completeness, relevance, coherence, score}，score < 0.7 触发重试 | 决策 T8、独特点 26（Kimi 文档） |
| 简报风格 | MVP 阶段默认 concise 风格，预留 detailed / bullet 等风格切换接口 | 独特点 28（Kimi 文档） |

**简报 JSON Schema**：

```json
{
  "date": "2026-06-18",
  "category": "AI Agent",
  "summary": "今日聚焦：Agent 框架新进展...",
  "items": [
    {
      "title": "...",
      "summary": "...",
      "importance": 4,
      "source_url": "https://...",
      "source_name": "...",
      "similar_count": 3
    }
  ],
  "quality": {
    "completeness": 0.85,
    "relevance": 0.90,
    "coherence": 0.88,
    "score": 0.88
  }
}
```

#### 3.1.5 推送与反馈模块

**职责**：定时推送简报，接收用户反馈。

| 子功能 | 设计决策 | 来源 |
|--------|---------|------|
| 推送机制 | 定时推送（APScheduler cron job）+ 重大事件破例（score > 0.85 且时效 < 2h） | 决策 P2 |
| 推送渠道 | 应用内渠道（Streamlit 页面展示） | 决策 P2 |
| 推送服务部署 | MCP Server (stdio 模式)，作为子进程随主进程启停 | 决策 T1、共识 4 |
| 反馈选项 | 三级：like（+偏好）/ dislike（-偏好）/ irrelevant（从候选集移除此类内容） | 决策 P7 |
| 反馈子图 | 反馈处理从主流程解耦为独立子图（feedback_workflow），支持异步处理 | 独特点 8（DeepSeek 文档） |

**反馈权重差异化**：

| 反馈类型 | preference 调整 | 语义 |
|---------|----------------|------|
| like | +0.15 | 内容有价值，强化此类偏好 |
| dislike | -0.10 | 内容质量差，弱化此类偏好 |
| irrelevant | -0.15 | 内容不属于关注领域，从候选集移除 |

> **来源**：决策 P2、决策 P7、决策 T1、独特点 8、独特点 63（偏好权重差异化，Codex_Mimo 文档）

#### 3.1.6 反思质量检查模块

**职责**：对生成的简报进行质量审查，不合格则重试。

| 子功能 | 设计决策 | 来源 |
|--------|---------|------|
| 质量评分 | brief_quality 结构化评分（completeness / relevance / coherence / score） | 决策 T8 |
| 重试触发 | score < 0.7 触发重试 | 决策 T8 |
| 重试上限 | 最多 2 次重试 | 决策 T8 |
| 重试后处理 | 若 2 次后仍 < 0.7，接受当前最佳结果并记录日志 | 决策 T8 |
| 矛盾检查 | 反思节点检查简报中是否存在自相矛盾的信息 | 独特点 9（DeepSeek 文档） |
| 反思维度 | 细化为完整性、去重遗漏、可追溯性三个维度 | 独特点 57（Codex_DeepSeek 文档） |

> **来源**：决策 T8、共识 3、独特点 9/57

---

### P1 — MVP 增强功能（优先实现但非阻塞核心闭环）

#### 3.2.1 用户偏好学习模块

**职责**：基于用户反馈动态更新偏好向量，影响后续排序。

| 子功能 | 设计决策 | 来源 |
|--------|---------|------|
| 偏好向量维护 | 维护用户偏好向量，存入 ChromaDB 长期记忆 | 共识 9、共识 10 |
| 正负分离 | 分别维护 v_like（点赞条目向量均值）和 v_dislike（踩条目向量均值） | 独特点 11（DeepSeek 文档） |
| 更新算法 | 简单累加：新反馈向量加权叠加到偏好向量 | 决策 I1 |
| EMA 平滑 | 偏好向量用 EMA（指数移动平均）平滑更新，防止剧烈波动 | 独特点 17（GLM 文档） |
| 偏好自动清理 | 偏好权重低于 0.1 的关键词自动清理 | 独特点 63（Codex_Mimo 文档） |
| 用户画像 embedding | 生成用户画像向量用于相似度计算 | 独特点 12（DeepSeek 文档） |
| 语义记忆种子数据 | MVP 阶段使用手动维护的种子数据，不做全量 RAG | 独特点 68（Codex_Mimo 文档） |

#### 3.2.2 记忆管理模块

**职责**：管理 Agent 的四层记忆体系。

| 记忆层 | 存储位置 | 内容 | 来源 |
|--------|---------|------|------|
| 短期记忆 | LangGraph State | 滑动窗口保留最近 15 轮对话；超窗时 LLM 压缩为摘要写入长期记忆 | 决策 T6、独特点 56（Codex_DeepSeek 文档） |
| 长期记忆 | ChromaDB | 用户偏好向量（v_like / v_dislike）、领域知识 embedding | 共识 9、独特点 11 |
| 情节记忆 | SQLite | 执行日志（每次 Agent 运行的完整记录）、简报历史 | 共识 9、独特点 52（Codex_DeepSeek 文档） |
| 语义记忆 | ChromaDB | 领域知识、概念关系（MVP 用种子数据） | 共识 9、独特点 68 |

#### 3.2.3 执行监控与日志模块

**职责**：记录 Agent 运行状态，支持调试和优化。

| 子功能 | 设计决策 | 来源 |
|--------|---------|------|
| 结构化日志 | 使用 `structlog` 替代标准 logging，便于解析和监控 | 独特点 36（Perplexity 文档） |
| 执行日志表 | `execution_logs` 表记录 session / turn / event 三级日志 | 独特点 52（Codex_DeepSeek 文档） |
| 运行日志表 | `run_logs` 表记录每次 Agent 执行的完整日志（耗时、成功率、去重率等） | 独特点 40（Perplexity 文档） |
| 任务级错误隔离 | APScheduler 捕获异常后继续下一次定时任务，不因单次失败阻塞后续 | 独特点 44（Qwen 文档） |
| 情节记忆工程指标 | 情节记忆记录 dedup_rate 等工程指标，支持 Agent 自我诊断 | 独特点 72（Codex_Mimo 文档） |

---

### P2 — 后续迭代方向（MVP 不实现，预留扩展点）

| 方向 | 描述 | 来源 |
|------|------|------|
| Goal 驱动自主 Agent | Planner 自主决策搜索时机和推送时机，实现从"流程驱动"到"自主决策"的升级 | 决策 P1、独特点 1/2（GPT 文档） |
| Telegram 推送渠道 | 在应用内推送基础上增加 Telegram Bot 推送 | 独特点 24（GLM 文档） |
| 多用户认证 | 引入 JWT 用户认证，支持多用户 | 决策 P8、独特点 50（TRAE 文档） |
| Docker Compose 容器化 | 打包全部组件，支持 `docker compose up` 一键启动 | 决策 T10、独特点 13（DeepSeek 文档） |
| 执行仪表盘 | Streamlit 页面展示执行成功率、耗时、去重率、反馈率等历史指标 | 独特点 21（GLM 文档） |
| 主动追问式偏好校准 | Agent 发现偏好信号冲突时主动问用户澄清 | 独特点 22（GLM 文档） |
| 工具调用路由层 | 增加智能路由层，根据工具特性自动选择 FC 或 MCP | 独特点 30（Kimi 文档） |
| 双 LLM 供应商冗余 | DeepSeek 主力 + 通义千问 fallback | 独特点 19（GLM 文档） |
| 多语言 Embedding | 切换为 BGE-M3 支持多语言扩展 | 独特点 43（Qwen 文档） |

---

## 4. 技术架构选型

### 4.1 整体架构

FeedLens 采用分层架构设计：

```
┌─────────────────────────────────────────┐
│              展示层 (Streamlit)           │
├─────────────────────────────────────────┤
│              规划层 (LangGraph)           │
│    ReAct 循环 + Reflection 反思          │
├─────────────────────────────────────────┤
│              大脑层 (LLM)                │
│    DeepSeek / 通义千问                   │
├──────────┬──────────┬───────────────────┤
│  工具层   │  记忆层   │    感知层          │
│ FC + MCP │ 四层记忆  │  RSS + Search     │
├──────────┴──────────┴───────────────────┤
│              存储层                       │
│    ChromaDB (向量) + SQLite (结构化)      │
└─────────────────────────────────────────┘
```

> **来源**：共识 2（四/五层分层架构）、独特点 59（六层架构映射表，Codex_Mimo 文档）

### 4.2 技术栈选型表

| 组件 | 选型 | 决策依据 | 约束力 |
|------|------|---------|--------|
| Agent 编排框架 | **LangGraph StateGraph** | 全部 9 份文档共识 | ★★★★★ |
| LLM 后端 | **DeepSeek**（主）/ 通义千问（备） | 国内可用、支持 FC、性价比高 | ★★★★☆ |
| Embedding 模型 | **bge-small-zh-v1.5**（本地） | 免费、无速率限制、中文效果好 | ★★★☆☆ |
| 向量数据库 | **ChromaDB** | 轻量、本地运行 | ★★★★★ |
| 关系数据库 | **SQLite**（WAL 模式） | 零部署、单文件 | ★★★★★ |
| 前端框架 | **Streamlit** | 快速构建 MVP 界面 | ★★★★★ |
| 定时调度 | **APScheduler** | 轻量、Python 原生 | ★★★★★ |
| RSS 解析 | **feedparser** | 成熟稳定 | ★★★★★ |
| 中文分词 | **jieba** | 中文关键词提取 | — |
| ORM | **原生 SQL** | 透明可调试 | — |
| 日志 | **structlog** | 结构化日志 | — |
| 部署（MVP） | **本地 Python 直接运行** | 开发迭代快 | — |
| 部署（v1.0） | **Docker Compose** | 一键交付 | — |

> **来源**：共识 1/5/6/7/14/15、决策 T4/T9/T10/I2/I3

### 4.3 工具调用策略（FC + MCP）

系统采用混合工具调用策略，将工具分为两类：

| 类型 | 特征 | 工具列表 | 部署模式 |
|------|------|---------|---------|
| **MCP Server** | 需独立部署、涉及外部系统 | `search_web`（搜索采集）、`push_notification`（简报推送） | search: **SSE**；push: **stdio** |
| **Function Calling** | 逻辑简单、参数明确、紧耦合 | `fetch_rss`、`deduplicate`、`rank_items`、`generate_briefing`、`reflect`、`update_preference`、`db_read`、`db_write`、`vector_search`、`vector_add` | 进程内直接调用 |

**MCP Server 数量：2 个**

- `search_web`（SSE 模式）：搜索 API 封装为独立服务，监听本地端口，通过 SSE 流式返回结果。
- `push_notification`（stdio 模式）：推送服务作为子进程随主进程启停，无需管理端口。

> **来源**：共识 4、共识 8、决策 T1/T5、独特点 16（MCP 双 Transport，GLM 文档）

### 4.4 Agent 工作流（StateGraph 节点定义）

```
                    ┌─────────────────┐
                    │ understand_intent │
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │  collect_sources │ ← fetch_rss (FC, 并行)
                    └────────┬────────┘ ← search_web (MCP, 条件触发)
                             ↓
                    ┌─────────────────┐
                    │ normalize_items  │
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │   deduplicate    │ → (items < 3?) → 回退 collect_sources
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │    rank_items     │
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │ generate_briefing│
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │     reflect      │ → (quality < 0.7 & retries < 2?) → 回退 generate_briefing
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │ push_notification │ (MCP stdio)
                    └────────┬────────┘
                             ↓
                    ┌─────────────────┐
                    │   update_memory   │
                    └─────────────────┘

          ┌─────────────────────────────┐
          │    feedback_workflow (子图)   │ ← 异步触发
          │  feedback → update_preference │
          └─────────────────────────────┘
```


#### 4.4.1 任务生命周期管理（Session / Turn / Event）

系统采用三层任务生命周期模型，映射到 LangGraph 的运行机制：

| 层级 | 定义 | LangGraph 映射 | 数据记录位置 |
|------|------|-----------------|---------------|
| **Session（会话）** | 用户的一次使用周期（如「设置 Goal → 收到第一份简报」） | `session_id` 贯穿多次 `agent.invoke()` 调用 | `execution_logs.session_id` |
| **Turn（轮次）** | Agent 的一次完整运行（从采集到推送） | 一次 `agent.invoke()` 为一个 Turn | `execution_logs.turn` |
| **Event（事件）** | Turn 内的一个节点执行 | 一个 StateGraph 节点执行为一个 Event | `execution_logs.event` |

**生命周期流转示例**：

```
Session-001 (用户设置 Goal，session 开始)
  ├── Turn-1 (第 1 天，APScheduler 触发 daily_briefing)
  │     ├── Event: understand_intent
  │     ├── Event: collect_sources
  │     ├── Event: deduplicate
  │     ├── Event: rank_items
  │     ├── Event: generate_briefing
  │     ├── Event: reflect
  │     ├── Event: push_notification
  │     └── Event: update_memory
  │
  ├── Turn-2 (用户反馈 like，feedback_update 触发)
  │     └── Event: update_preference
  │
  └── Turn-3 (第 2 天，APScheduler 再次触发)
        └── ...（同 Turn-1 流程）
```

> **来源**：Prompt 要求 "Harness 工程：session → turn → event"；数据模型 §5.9 `execution_logs` 表已定义这三个字段。


**State 定义（TypedDict）**：

```python
class FeedLensState(TypedDict):
    # 触发信息
    trigger_type: str          # daily_briefing / manual_search / feedback_update
    user_goal: str             # 用户 Goal 文本
    user_profile: dict         # LLM 提取的结构化偏好

    # 采集结果
    raw_items: list[dict]      # 原始采集条目
    normalized_items: list[dict]

    # 去重结果
    deduped_items: list[dict]
    item_relations: list[dict] # 去重关系记录

    # 排序结果
    ranked_items: list[dict]

    # 简报
    brief_content: dict        # 结构化 JSON 简报
    brief_quality: dict        # {completeness, relevance, coherence, score}

    # 反思
    retry_count: int
    reflection_notes: str

    # 记忆
    short_term_memory: list[dict]  # 滑动窗口（最近 15 轮）
    retrieved_memories: list[dict] # 从长期记忆检索的相关记忆
```

> **来源**：共识 1/3/13、独特点 7/8/20/66（6 个 TypedDict，Codex_Mimo 文档）

---

## 5. 核心数据模型

### 5.1 users — 用户表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 用户 ID |
| `goal_text` | TEXT | 用户输入的 Goal 文本 |
| `topics` | TEXT (JSON) | LLM 提取的关注领域列表 |
| `keywords` | TEXT (JSON) | LLM 提取的关键词列表 |
| `preferred_sources` | TEXT (JSON) | 推荐 RSS 源列表 |
| `created_at` | TIMESTAMP | 创建时间 |

### 5.2 sources — 信息源表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 源 ID |
| `user_id` | INTEGER FK | 关联用户 |
| `url` | TEXT | RSS/Atom 源地址 |
| `name` | TEXT | 源名称 |
| `category` | TEXT | 分类 |
| `authority_score` | REAL | 来源可信度评分（0-1） |
| `is_active` | BOOLEAN | 是否启用 |

### 5.3 raw_items — 原始条目表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 条目 ID |
| `source_id` | INTEGER FK | 来源 ID |
| `title` | TEXT | 标题 |
| `summary` | TEXT | 摘要 |
| `content` | TEXT | 正文 |
| `url` | TEXT | 原文链接 |
| `published_at` | TIMESTAMP | 发布时间 |
| `collected_at` | TIMESTAMP | 采集时间 |
| `embedding_id` | TEXT | ChromaDB 中的向量 ID |

### 5.4 deduped_items — 去重后条目表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 条目 ID |
| `representative_item_id` | INTEGER FK | 代表条目 ID（raw_items） |
| `similar_count` | INTEGER | 合并的相似条目数 |
| `category` | TEXT | LLM 提取的分类 |
| `keywords` | TEXT (JSON) | LLM 提取的关键词 |
| `importance` | INTEGER | LLM 评估的重要性（1-5） |
| `source_diversity_bonus` | REAL | 来源多样性加分（默认 0，多源 +0.05） |
| `embedding_id` | TEXT | ChromaDB 中的向量 ID |

### 5.5 item_relations — 条目关系表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 关系 ID |
| `item_a_id` | INTEGER FK | 条目 A |
| `item_b_id` | INTEGER FK | 条目 B |
| `relation_type` | TEXT | 关系类型：duplicate_of / related_to / merged_into |
| `similarity_score` | REAL | 相似度分数 |
| `dedup_method` | TEXT | 判定方式：vector_threshold / llm_adjudication |

### 5.6 briefs — 简报表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 简报 ID |
| `user_id` | INTEGER FK | 关联用户 |
| `date` | DATE | 简报日期 |
| `content_json` | TEXT (JSON) | 结构化 JSON 简报内容 |
| `content_md` | TEXT | 渲染后的 Markdown |
| `quality_score` | REAL | 质量评分（0-1） |
| `quality_detail` | TEXT (JSON) | {completeness, relevance, coherence} |
| `retry_count` | INTEGER | 重试次数 |
| `created_at` | TIMESTAMP | 生成时间 |

### 5.7 feedback — 用户反馈表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 反馈 ID |
| `user_id` | INTEGER FK | 关联用户 |
| `brief_id` | INTEGER FK | 关联简报 |
| `item_id` | INTEGER FK | 关联条目 |
| `feedback_type` | TEXT CHECK | like / dislike / irrelevant |
| `created_at` | TIMESTAMP | 反馈时间 |

### 5.8 user_preferences — 用户偏好表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 偏好 ID |
| `user_id` | INTEGER FK | 关联用户 |
| `keyword` | TEXT | 偏好关键词 |
| `weight` | REAL | 权重值（低于 0.1 自动清理） |
| `vector_id` | TEXT | ChromaDB 中的偏好向量 ID |
| `feedback_count` | INTEGER | 累计反馈次数 |
| `updated_at` | TIMESTAMP | 最后更新时间 |

### 5.9 execution_logs — 执行日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 日志 ID |
| `session_id` | TEXT | 会话 ID |
| `turn` | INTEGER | 轮次 |
| `event` | TEXT | 事件类型 |
| `node_name` | TEXT | StateGraph 节点名 |
| `status` | TEXT | success / error / skipped |
| `duration_ms` | INTEGER | 耗时（毫秒） |
| `metadata` | TEXT (JSON) | 附加信息 |
| `created_at` | TIMESTAMP | 记录时间 |

### 5.10 run_logs — 运行日志表

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 运行 ID |
| `user_id` | INTEGER FK | 关联用户 |
| `trigger_type` | TEXT | daily_briefing / manual_search |
| `items_collected` | INTEGER | 采集条目数 |
| `items_deduped` | INTEGER | 去重后条目数 |
| `dedup_rate` | REAL | 去重率 |
| `brief_quality_score` | REAL | 简报质量评分 |
| `duration_ms` | INTEGER | 总耗时 |
| `status` | TEXT | success / error |
| `created_at` | TIMESTAMP | 运行时间 |

> **来源**：共识 5/6、独特点 35（WAL 模式，Perplexity 文档）、独特点 51（item_relations，Codex_DeepSeek 文档）、独特点 52（execution_logs，Codex_DeepSeek 文档）、独特点 40（run_logs，Perplexity 文档）、独特点 58（dataclass 定义，Codex_DeepSeek 文档）

---

## 6. API 接口设计

### 6.1 MCP 工具接口

| 工具名 | 协议 | 方法 | 参数 | 返回 | 选型理由 | 说明 |
|--------|------|------|------|------|----------|------|
| `search_web` | SSE | `search` | `query: str`, `max_results: int = 10` | `list[dict]` | 搜索 API 是外部 HTTP 服务，需独立进程管理连接池；SSE 模式支持流式返回，适合搜索场景 | 搜索采集，流式返回结果 |
| `push_notification` | stdio | `push` | `brief: dict`, `user_id: int`, `immediate: bool = False` | `bool` | 推送服务需随主进程启停，无需管理端口；MVP 阶段所有组件在同一机器，stdio 部署复杂度最低 | 推送简报；`immediate=True` 表示重大事件破例推送 |

> **选型原则**：工具需独立部署或有状态 → MCP；工具是纯函数逻辑或进程内 SDK 调用 → FC。详见 §4.3。

### 6.2 Function Calling 工具接口

| 工具名 | 方法 | 参数 | 返回 | 选型理由 | 说明 |
|--------|------|------|------|----------|------|
| `fetch_rss` | `fetch` | `sources: list[str]` | `list[dict]` | RSS 解析是纯函数逻辑（feedparser 无状态），进程内调用延迟最低 | 并行采集多个 RSS 源 |
| `enrich_metadata` | `enrich` | `items: list[dict]` | `list[dict]` | LLM 单次推理无持久状态，FC 调用最简单 | LLM 提取 category/keywords/importance |
| `normalize_items` | `normalize` | `items: list[dict]` | `list[dict]` | 字段格式化是纯数据转换（无 I/O），FC 开销最小 | 统一字段格式 |
| `deduplicate` | `dedup` | `items: list[dict]`, `threshold: float = 0.88` | `list[dict], list[dict]` | 向量检索依赖 ChromaDB 进程内 SDK，FC 直接调用无需 IPC 开销 | 返回去重后条目 + 关系记录 |
| `rank_items` | `rank` | `items: list[dict]`, `user_profile: dict`, `feedback_count: int` | `list[dict]` | 排序是纯计算逻辑（无 I/O），FC 调用性能最优 | 多因子加权排序 |
| `generate_briefing` | `generate` | `ranked_items: list[dict]`, `style: str = "concise"` | `dict` | LLM 生成是单次推理，FC 调用最简单 | 生成结构化 JSON 简报 |
| `reflect` | `reflect` | `brief: dict` | `dict` | 质量评分是纯计算 + 单次 LLM 调用（无状态），FC 最简单 | 质量评分 + 重试判断 |
| `update_preference` | `update` | `feedback: dict`, `user_id: int` | `dict` | 偏好更新最终调用 db_write（FC），链路最短 | 更新用户偏好向量 |
| `db_read` | `read` | `table: str`, `conditions: dict` | `list[dict]` | SQLite 是无状态查询，进程内调用延迟最低 | SQLite 读取 |
| `db_write` | `write` | `table: str`, `data: dict` | `bool` | SQLite 是单次写操作，进程内调用延迟最低 | SQLite 写入 |
| `vector_search` | `search` | `collection: str`, `query: str`, `top_k: int = 5` | `list[dict]` | ChromaDB SDK 是进程内调用，FC 直接调用无需 IPC 开销 | ChromaDB 相似度检索 |
| `vector_add` | `add` | `collection: str`, `documents: list[str]`, `metadatas: list[dict]` | `list[str]` | ChromaDB SDK 是进程内调用，FC 直接调用无需 IPC 开销 | ChromaDB 写入向量 |

> **选型原则**：工具需独立部署或有状态 → MCP；工具是纯函数逻辑或进程内 SDK 调用 → FC。详见 §4.3。
### 6.3 Streamlit 页面路由

| 页面 | 路径 | 功能 |
|------|------|------|
| 首页 / 简报查看 | `/` | 展示最新简报，支持查看历史简报 |
| Goal 设置 | `/settings` | 输入 Goal 文本，查看 LLM 提取的结构化字段 |
| RSS 源管理 | `/sources` | 添加/删除/启用 RSS 源 |
| 反馈记录 | `/feedback` | 查看历史反馈记录和偏好变化趋势 |
| 执行日志 | `/logs` | 查看 Agent 运行日志（P1） |

---

## 7. 里程碑规划

### 阶段一（第 1 周）：项目骨架 + 数据模型

**目标**：搭建项目结构，定义数据模型，跑通 LangGraph 基础工作流。

| 交付物 | 验收标准 |
|--------|---------|
| 项目目录结构 | 符合模块化设计，包含 config / models / nodes / tools / utils |
| SQLite 表结构初始化脚本 | 全部 10 张表创建成功，WAL 模式开启 |
| ChromaDB 集合初始化 | items / preferences / domain_knowledge 三个集合创建成功 |
| LangGraph StateGraph 骨架 | 9 个节点定义完成，边连接正确，空实现可跑通 |
| bge-small-zh-v1.5 模型加载 | 本地加载成功，推理速度 < 100ms/条 |

### 阶段二（第 2 周）：信息采集 + 智能去重

**目标**：实现 RSS 采集、搜索补充、向量去重完整链路。

| 交付物 | 验收标准 |
|--------|---------|
| `fetch_rss` FC 工具 | 并行采集 3+ 个 RSS 源，feedparser 解析成功 |
| `search_web` MCP Server (SSE) | 搜索 API 封装成功，SSE 流式返回 |
| `enrich_metadata` + `normalize_items` 节点 | LLM 提取分类/关键词/重要性，字段统一格式化 |
| `deduplicate` 节点 | 0.88 阈值向量去重 + 0.70-0.88 模糊区间 LLM 裁决 |
| `item_relations` 表写入 | 去重关系正确记录 |
| 空结果回退逻辑 | 去重后 < 3 条自动回退采集 |
| `calibrate_dedup.py` 脚本 | 标注样本 → P/R/F1 曲线 → 最优阈值输出 |

### 阶段三（第 3 周）：偏好排序 + 简报生成

**目标**：实现多因子排序和结构化简报生成。

| 交付物 | 验收标准 |
|--------|---------|
| `rank_items` 节点 | 冷启动权重 (0.40/0.25/0.10/0.25) 和有反馈权重 (0.30/0.20/0.40/0.10) 动态切换 |
| 时间衰减预筛 | 半衰期公式 τ=24h，过时内容跳过排序 |
| Min-Max 归一化 + feedback_bias | 所有因子归一化至 [0,1]，feedback_bias 叠加到 preference |
| `generate_briefing` 节点 | LLM 输出结构化 JSON，含 importance + source_url + similar_count |
| JSON → Markdown 渲染 | 简报正确渲染，计数标注显示 |
| `brief_quality` 评分 | completeness/relevance/coherence/score 四维评分 |

### 阶段四（第 4 周）：推送 + 反馈 + 反思 + 记忆

**目标**：完成业务闭环，实现推送、反馈、反思和记忆管理。

| 交付物 | 验收标准 |
|--------|---------|
| `push_notification` MCP Server (stdio) | 推送服务作为子进程运行 |
| APScheduler 定时触发 | cron job 每日定时触发工作流 |
| 重大事件破例推送 | score > 0.85 且时效 < 2h 时立即推送 |
| `reflect` 节点 | 质量评分 < 0.7 触发重试，最多 2 次 |
| `feedback_workflow` 子图 | 反馈异步处理，偏好向量更新 |
| 三级反馈 UI | like / dislike / irrelevant 三个按钮 |
| 短期记忆管理 | 滑动窗口 15 轮，超窗 LLM 压缩写入长期记忆 |
| 偏好正负分离 | v_like / v_dislike 分别维护 |
| 偏好自动清理 | 权重 < 0.1 自动清理 |

### 阶段五（第 5 周）：集成测试 + 优化 + 交付

**目标**：端到端测试，性能优化，文档交付。

| 交付物 | 验收标准 |
|--------|---------|
| 端到端集成测试 | 从 Goal 设置到简报推送全流程跑通，无报错 |
| Streamlit 前端 | 5 个页面功能完整（首页/设置/源管理/反馈/日志） |
| structlog 结构化日志 | 全部节点日志结构化输出 |
| execution_logs + run_logs | 执行日志和运行日志正确记录 |
| 任务级错误隔离 | 单次失败不阻塞下次执行 |
| 30 天数据清理 | 定期清理过期 raw_items 和 execution_logs |
| 性能基准测试 | 单次 Agent 运行 < 60s（采集 10 条 RSS 源） |
| MVP 设计文档 | 本文档定稿 |
| README + 部署指南 | 包含环境配置、启动命令、依赖列表 |

---

## 8. 其它重要补充

### 8.1 冷启动策略

MVP 阶段的冷启动是指**用户首次使用系统、尚无反馈数据**的状态。

| 维度 | 冷启动策略 | 切换条件 | 来源 |
|------|---------|---------|------|
| 排序权重 | 相似度优先（w₁=0.40, w₃=0.10） | 用户反馈 ≥ 3 条 → 切换为偏好优先（w₁=0.30, w₃=0.40） | 决策 T3 |
| 偏好向量 | 使用 Goal 文本提取的 keywords 生成初始偏好向量 | 有真实反馈后逐步替换为 v_like / v_dislike | 独特点 68（语义记忆种子数据） |
| RSS 源 | LLM 根据 Goal 文本推荐初始 RSS 源列表 | 用户可在设置页面手动增删 | 决策 P3 |
| 语义记忆 | 手动维护种子数据（领域知识、概念关系） | 数据积累后逐步自动补充 | 独特点 68 |

### 8.2 去重阈值校准流程

去重阈值（0.88）是经验初值，系统提供校准脚本持续优化：

```
1. 人工标注 200 对样本（正例/负例）
2. 计算每对的 cosine 相似度
3. 遍历阈值 0.70-0.95（步长 0.01），计算各阈值的 P/R/F1
4. 绘制 P/R/F1 曲线，选 F1 最优阈值
5. 更新配置文件中的 dedup_threshold 参数
```

> **来源**：决策 T2、独特点 15（calibrate_dedup.py，GLM 文档）、独特点 70（阈值校准方法，Codex_Mimo 文档）

### 8.3 数据生命周期管理

| 数据 | 保留策略 | 清理方式 | 来源 |
|------|---------|---------|------|
| raw_items | 30 天 | 定时任务清理过期记录 | 独特点 54（Codex_DeepSeek 文档） |
| execution_logs | 30 天 | 定时任务清理过期记录 | 独特点 54 |
| run_logs | 90 天 | 定时任务清理过期记录 | — |
| briefs | 永久保留 | 不清理 | — |
| feedback | 永久保留 | 不清理 | — |
| ChromaDB 向量 | 随 raw_items 清理同步删除 | 关联清理 | — |
| 短期记忆 | 15 轮滑动窗口 | 超窗 LLM 压缩写入长期记忆 | 决策 T6 |

### 8.4 错误处理与容错

| 场景 | 处理策略 | 来源 |
|------|---------|------|
| RSS 源不可达 | 跳过该源，记录 warning 日志，继续采集其他源 | — |
| 搜索 API 超时 | 降级为仅使用 RSS 采集结果，记录 warning | — |
| 去重后条目不足（< 3 条） | 回退到采集节点，扩大时间窗/增加来源 | 独特点 20（GLM 文档） |
| LLM 调用失败 | 重试 1 次；若仍失败，降级使用规则模板生成简报 | — |
| 简报质量连续不达标 | 2 次重试后接受当前最佳结果，记录日志供后续分析 | 决策 T8 |
| APScheduler 任务异常 | 捕获异常，记录 error 日志，继续下一次定时任务 | 独特点 44（Qwen 文档） |
| SQLite 并发冲突 | WAL 模式 + 事务包裹，自动重试 | 独特点 35（Perplexity 文档） |
| 偏好权重异常 | 权重 < 0.1 自动清理，防止噪声干扰 | 独特点 63（Codex_Mimo 文档） |

### 8.5 关键配置参数

| 参数 | 默认值 | 说明 | 可调 |
|------|--------|------|------|
| `dedup_threshold` | 0.88 | 去重相似度阈值 | 是（校准脚本） |
| `dedup_llm_lower` | 0.70 | 模糊区间下界（低于此值不重复） | 是 |
| `half_life_hours` | 24 | 时间衰减半衰期 | 是 |
| `short_term_window` | 15 | 短期记忆滑动窗口轮数 | 是 |
| `max_retry` | 2 | 反思重试上限 | 是 |
| `quality_threshold` | 0.7 | 简报质量评分阈值 | 是 |
| `min_items_for_brief` | 3 | 生成简报的最低条目数 | 是 |
| `breaking_news_score` | 0.85 | 重大事件破例推送阈值 | 是 |
| `breaking_news_freshness_hours` | 2 | 重大事件时效阈值 | 是 |
| `preference_cleanup_threshold` | 0.1 | 偏好权重自动清理阈值 | 是 |
| `data_retention_days` | 30 | 过期数据清理天数 | 是 |
| `feedback_bias_positive` | 0.15 | 正向反馈偏置 | 是 |
| `feedback_bias_negative` | -0.10 | 负向反馈偏置 | 是 |
| `feedback_bias_irrelevant` | -0.15 | 不相关反馈偏置 | 是 |
| `source_diversity_bonus` | 0.05 | 来源多样性加分 | 是 |

---

## 附录：决策来源映射

本文档中的每项设计决策均可追溯至以下输入文档：

| 输入 | 文件 | 内容 |
|------|------|------|
| 共识点（18 条） | `共识点.md` | 9 份原始 MVP 文档的共识提取 |
| 独特点（72 条） | `独特点.md` | 9 份原始 MVP 文档的独特点提取 |
| 决策清单（28 项） | `决策清单.md` | 18 项冲突决策 + 10 项实现选型 |

| 编号 | 决策项 | 编号 | 决策项 |
|------|--------|------|--------|
| P1 | 简报生成驱动模式 → 流程驱动 | T6 | 短期记忆窗口 → 15 轮 + 超窗压缩 |
| P2 | 推送机制 → 定时 + 破例 + 应用内 | T7 | 时间衰减函数 → 半衰期 τ=24h |
| P3 | 用户配置粒度 → Goal 文本 + LLM 提取 | T8 | 反思重试 → 最多 2 次 |
| P4 | 去重结果处理 → 计数标注 | T9 | 向量库交互 → FC 直接调用 |
| P5 | 搜索采集角色 → RSS 为主 + 搜索补充 | T10 | 部署方案 → 本地开发 + Docker 交付 |
| P6 | 简报输出风格 → 结构化 JSON | I1 | 偏好更新算法 → 简单累加 |
| P7 | 用户反馈选项 → 三级 | I2 | ORM 选型 → 原生 SQL |
| P8 | 用户认证 → 不需要（单用户） | I3 | RSS 采集工具 → feedparser |
| T1 | MCP 传输模式 → Push stdio / Search SSE | I4 | 搜索服务 → 商业搜索 API (SSE MCP) |
| T2 | 向量去重 → 0.88 + 纯向量 + LLM 裁决 + 校准 | | |
| T3 | 排序权重 → 冷启动相似度优先 → 偏好优先 | | |
| T4 | Embedding 模型 → 本地 bge-small-zh-v1.5 | | |
| T5 | MCP Server 数量 → 2 个 + FC 调用 DB/向量 | | |
