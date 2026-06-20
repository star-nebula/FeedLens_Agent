# FeedLens — 智能信息简报 Agent MVP 设计文档

***

## Executive Summary

**做什么**：FeedLens 是一个主动式信息聚合 Agent 系统——每天自动采集、去重、排序、生成简报并推送给用户，用户反馈后系统持续学习偏好。

**为什么不同**：不是 cron + 线性流水线。核心差异化是 **planner 节点的自主规划能力**——主 Agent 的 planner 通过 ReAct 循环自主决定本轮调用哪些子 Agent、什么顺序、是否补充数据，而非硬编码执行。

**MVP 做哪几件事**：

1. 主 Agent planner 自主编排子 Agent（采集 / 排序 / 简报）
2. 多因子偏好排序 + 反馈闭环个性化
3. APScheduler 定时触发 + 重大事件破例推送
4. Streamlit 应用内交付（简报 + 反馈 + 配置）

**不做什么**：多用户认证、Telegram推送、Docker容器化、跨类别配额、简报风格切换。

***

## 1. 项目概述（愿景与核心价值）

### 1.1 项目定位

FeedLens 是一个**主动式信息聚合 Agent 系统**。它不是被动问答工具，也不是 cron + pipeline，而是能**自主规划、调度子 Agent、定时执行、个性化筛选**的多 Agent 智能体系统。核心差异化在于展示 Agent 的「自主规划 + 多 Agent 协调 + 定时执行 + 个性化筛选」能力——planner 节点自主决定本轮调用哪些子 Agent、什么顺序、是否需要补充数据。

### 1.2 核心价值主张

| 维度   | 传统 RSS 阅读器   | FeedLens Agent           |
| ---- | ------------ | ------------------------ |
| 采集方式 | 被动拉取，用户自行浏览  | 定时自主采集 + 搜索补充            |
| 信息过滤 | 按时间排序，用户自行筛选 | 智能去重 + 偏好排序，推送高价值内容      |
| 个性化  | 基于关键词的硬匹配    | 基于用户反馈动态学习偏好向量           |
| 输出形态 | 原始条目列表       | 结构化简报（分类 + 重要性标注 + 来源引用） |
| 交互方式 | 用户主动查看       | Agent 定时推送 + 用户反馈闭环      |

### 1.3 MVP 核心假设

> **假设**：用户愿意每天收到一份「5-10 条高价值、已去重、按个人偏好排序」的信息简报，并通过反馈持续改善推送质量。

MVP 阶段的一切设计决策均围绕**最快验证此假设**展开。

***

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
    ┌── 主 Agent planner 自主编排子 Agent
    │     ↓
    │   ┌── 采集 Agent（ReAct: 判断是否需要补充搜索）
    │   │     ↓
    │   ├── 排序 Agent（ReAct: 判断排序质量是否足够）
    │   │     ↓
    │   ├── 简报 Agent（生成 + 质量审查）
    │   │     ↓
    │   └── 主 Agent coordinator_reflect（综合质量审查）
    │         ↓
    └── 推送（定时推送 + 重大事件破例）
          ↓
    用户反馈（like / dislike / irrelevant）
          ↓
    反馈子 Agent → 偏好向量更新 → 影响下一轮排序
```

### 2.3 Agent 架构概览

系统采用**主 Agent + 3 个子 Agent** 的多 Agent 自主规划架构：

| Agent                               | 职责                         | ReAct 能力                        | 工具集                                                                                 |
| ----------------------------------- | -------------------------- | ------------------------------- | ----------------------------------------------------------------------------------- |
| **主 Agent** (Coordinator + Planner) | 自主编排子 Agent、综合质量审查、推送交付    | ✅ planner→invoke→observe→再思考 循环 | 子 Agent 调度 + coordinator\_reflect + push\_notification(MCP) + update\_memory        |
| **采集 Agent**                        | RSS采集 + 搜索补充 + 元数据提取 + 标准化 | ✅ Think→Act→Observe 循环          | fetch\_rss(FC) + search\_web(MCP SSE) + enrich\_metadata(FC) + normalize\_items(FC) |
| **排序 Agent**                        | 智能去重 + 偏好排序 + 记忆辅助         | ✅ Think→Act→Observe 循环          | deduplicate(FC) + rank\_items(FC) + vector\_search(FC) + db\_read(FC)               |
| **简报 Agent**                        | 简报生成 + 质量审查                | ❌ 线性流程（一次生成+审查）                 | generate\_briefing(FC) + brief\_quality\_check(FC)                                  |
| **反馈 Agent** (异步)                   | 反馈处理 + 偏好向量更新              | ❌ 单次执行                          | update\_preference(FC) + vector\_add(FC) + db\_write(FC)                            |

***

## 3. 功能模块设计

### 3.1 设计原则与范围界定

**优先级体系**（简化为三档）：

| 优先级    | 定义                                             | MVP 约束   |
| ------ | ---------------------------------------------- | -------- |
| **P0** | 自主决策闭环骨架，缺一不可——核心是 planner 自主编排子 Agent，不是线性流水线 | 不可裁剪     |
| **P1** | 首版增强，深化差异化价值但不影响核心假设验证                         | 尽量实现，可裁剪 |
| **P2** | 后续迭代方向，预留扩展点                                   | MVP 不实现  |

<br />

**P0 核心叙事——Planner 自主编排能力**：

FeedLens 的 P0 核心不是"线性流水线缺一不可"，而是 **planner 节点的自主编排能力**。planner 通过 ReAct 循环自主决定本轮调用哪些子 Agent、什么顺序、是否需要补充数据。7 个决策场景覆盖了所有 P0 功能模块的组合方式：

| 决策场景     | planner 编排                                                                  | 涉及模块        | 说明                    |
| -------- | --------------------------------------------------------------------------- | ----------- | --------------------- |
| ① 正常每日简报 | `[Collection → Ranking → Briefing]`                                         | 采集+排序+简报    | 标准编排                  |
| ② 采集不足   | `[Collection → (Observe: items<5) → Collection(补充搜索) → Ranking → Briefing]` | 采集(ReAct)   | ReAct 循环：观察采集不够→再思考补充 |
| ③ 排序不理想  | `[Collection → Ranking → (Observe: 偏好匹配低) → Ranking(调参) → Briefing]`        | 排序(ReAct)   | ReAct 循环：观察排序不佳→再思考调参 |
| ④ 重大事件推送 | `[Collection → Ranking → Briefing → PushNow]`                               | 采集+排序+简报+推送 | 发现重大事件，直接推送           |
| ⑤ 跳过采集   | `[Ranking → Briefing]`                                                      | 排序+简报       | 使用上轮采集结果，只重排+重生成      |
| ⑥ 跳过简报   | `[Collection → Ranking → Push摘要]`                                           | 采集+排序+推送    | 内容太多不做详细简报，只推送关键条目    |
| ⑦ 空数据回退  | `[Collection → (Observe: 0 items) → Collection(扩大时间窗)]`                     | 采集(ReAct)   | 采集结果为空，重新采集           |

> 每个模块的详细能力边界见 3.2.1-3.2.6。场景编号与 4.5.1 planner 决策逻辑对应。

***

### 3.2 P0 核心功能 — Planner 自主编排能力（决策闭环）

P0 的核心是 **planner 自主编排子 Agent 构成决策闭环**——不是线性流水线，而是 ReAct 循环自主决定执行路径。每个子 Agent 是独立模块，有自己的工具集和决策逻辑。

#### 3.2.1 主 Agent — Coordinator + Planner（P0 核心节点）

**职责**：自主规划本轮执行策略，调度子 Agent，审查结果质量。planner 是 P0 核心差异化节点——通过 ReAct 循环自主编排子 Agent，而非硬编码执行。

**参与决策场景**：①②③④⑤⑥⑦（全部场景，planner 是每个场景的决策核心）

| 子功能                  | 设计决策                                                                                                                                                              |
| -------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| understand\_intent   | 识别触发类型（daily\_briefing / manual\_search / feedback\_update），提取结构化偏好；同时生成 goal\_embedding（从 structured\_goal.topics 关键词拼接后调用 bge-small-zh-v1.5，缓存于 SQLite users 表） |
| **planner（P0 核心）**   | LLM 自主判断本轮应调用哪些子 Agent、执行顺序、是否需要补充数据。7 个决策场景见 3.1 场景映射表。输出编排计划：`{sub_agents: [Collection, Ranking, Briefing], skip: [], reason: str}`。这是 ReAct 的 Think 步骤         |
| ReAct 循环             | 主 Agent 在 planner 节点实现 Think→Act(调度子Agent)→Observe(收集结果)→Think(planner再判断)的循环                                                                                     |
| coordinator\_reflect | 审查所有子 Agent 输出的综合质量（简报 completeness/relevance/coherence + 矛盾检查）                                                                                                   |
| push\_notification   | 推送简报（定时 + 重大事件破例）                                                                                                                                                 |
| update\_memory       | 更新偏好向量 + 写入执行日志                                                                                                                                                   |

**planner 自主编排能力**：planner 的 7 个决策场景已在 3.1 场景映射表中定义（正常简报、采集不足、排序不理想、重大事件、跳过采集、跳过简报、空数据回退），此处不重复。

#### 3.2.2 子 Agent — 采集 Agent

**职责**：从多个信息源采集最新内容，具备 ReAct 循环自主判断是否需要补充搜索。

**参与决策场景**：①②④⑥⑦（所有需要采集的场景；⑤跳过采集时不参与）

> 采集 Agent 的 ReAct 循环实现细节见 4.5.2。

| 子功能           | 设计决策                                                                            |
| ------------- | ------------------------------------------------------------------------------- |
| 独立 StateGraph | 采集 Agent 有自己的 State 和工作流，由主 Agent 通过子 Agent 调用接口调度                              |
| ReAct 循环      | Think(判断采集策略) → Act(fetch\_rss/search\_web) → Observe(评估采集结果) → Think(是否需要补充搜索) |
| RSS 采集        | 使用 `feedparser` 解析 RSS/Atom 格式，并行采集                                             |
| 搜索补充          | 当采集结果不足时，自主触发搜索 API（MCP SSE）补充                                                  |
| 元数据提取         | `enrich_metadata` 节点：LLM 对每条原始条目提取 category / keywords / importance             |
| 条目标准化         | `normalize_items` 节点：统一字段格式                                                     |

**采集 Agent 工具集**：

| 工具                | 说明                | 详情  |
| ----------------- | ----------------- | --- |
| `fetch_rss`       | 并行采集多个 RSS 源      | 6.2 |
| `search_web`      | 条件触发搜索补充（MCP SSE） | 6.1 |
| `enrich_metadata` | LLM 元数据增强         | 6.2 |
| `normalize_items` | 字段标准化             | 6.2 |

**采集策略**：

* 两路并行采集：RSS 为主要信息源，搜索为条件补充通道

* 采集结果包含：标题、摘要、正文、来源 URL、发布时间、来源名称

#### 3.2.3 子 Agent — 排序 Agent

**职责**：智能去重 + 偏好排序，具备 ReAct 循环自主判断排序质量是否足够好。

**参与决策场景**：①②③④⑤⑥（所有需要排序的场景；⑦空数据回退时可能不参与）

> 排序 Agent 的 ReAct 循环实现细节见 4.5.2。

| 子功能           | 设计决策                                                                                                  |
| ------------- | ----------------------------------------------------------------------------------------------------- |
| 独立 StateGraph | 排序 Agent 有自己的 State 和工作流，由主 Agent 调度                                                                  |
| ReAct 循环      | Think(检索偏好→规划排序策略) → Act(去重+排序) → Observe(评估排序结果) → Think(调参或Done)                                    |
| 去重技术路线        | 纯向量去重 + 模糊区间 LLM 裁决（不增加 NER/编辑距离等第二信号）                                                                |
| 去重阈值          | ≥0.88 判定为重复；≤0.70 判定为不重复；0.70-0.88 模糊区间调用 LLM 做二元判断，最多裁决 20 对（`max_llm_adjudications=20`），超限按 0.80 硬判 |
| 去重结果处理        | 计数标注：保留一篇代表，简报中标注「还有 N 篇类似报道」                                                                         |
| 条目关系记录        | `item_relations` 表记录去重关系                                                                              |
| 来源多样性加分       | 字段预留（`source_diversity_bonus` 默认 0），P1 赋值 +0.05                                                       |
| 空结果回退         | 若去重后剩余 < 3 条，向主 Agent 报告，由 planner 决策是否重新采集                                                           |
| 阈值校准          | `calibrate_dedup.py` 脚本                                                                               |

**排序 Agent 工具集**：

| 工具              | 说明              | 详情  |
| --------------- | --------------- | --- |
| `deduplicate`   | 向量去重 + 关系记录     | 6.2 |
| `rank_items`    | 多因子加权排序 + 记忆辅助  | 6.2 |
| `vector_search` | ChromaDB 偏好向量检索 | 6.2 |
| `db_read`       | SQLite 读取反馈历史   | 6.2 |

**排序公式**：

```
final_score = w₁ · similarity + w₂ · recency + w₃ · (preference + feedback_bias) + w₄ · importance
```

> **公式说明**：`feedback_bias` 叠加到 `preference` 因子内部，而非独立因子。这是因为 feedback\_bias 是偏好向量的即时补偿——用户刚给反馈但偏好向量尚未 EMA 更新时，bias 临时补偿偏好因子的偏差；偏好向量 EMA 更新后，该轮 feedback\_bias 自动归零。二者不是独立叠加，而是时序互补。

| 因子           | 含义            | 计算方式                                                                                                                                          |
| ------------ | ------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `similarity` | 内容与用户关注领域的相似度 | cosine(item\_embedding, goal\_embedding)；goal\_embedding 由 structured\_goal 的 topics 关键词拼接后 embedding 生成，代表用户关注的领域方向                          |
| `recency`    | 时间新鲜度         | `exp(-Δt / τ)`，τ = 24h                                                                                                                        |
| `preference` | 用户偏好匹配度       | cosine(item\_embedding, user\_preference\_vector)；feedback\_bias 叠加方式见排序公式说明；user\_preference\_vector 由 v\_like/v\_dislike 合成，代表用户反馈学习到的细粒度偏好 |
| `importance` | 新闻重要性         | LLM 评估 1-5 分，线性归一化至 0-1：`(score - 1) / 4`（1→0, 3→0.5, 5→1）                                                                                    |

> **因子区分说明**：`similarity` 和 `preference` 在冷启动阶段数值接近（goal\_embedding 和初始 user\_preference\_vector 均源自 Goal 文本关键词），但在有反馈后分化——goal\_embedding 固定不变（代表宏观关注方向），user\_preference\_vector 通过 EMA 持续更新（代表微观偏好漂移）。两者参考向量不同，是真正的双因子而非退化。

**权重策略（动态切换）**：

| 阶段  | 条件         | 权重配置                               | 理由          |
| --- | ---------- | ---------------------------------- | ----------- |
| 冷启动 | 用户反馈 < 3 条 | w₁=0.40, w₂=0.25, w₃=0.10, w₄=0.25 | 无偏好数据，相似度优先 |
| 有反馈 | 用户反馈 ≥ 3 条 | w₁=0.30, w₂=0.20, w₃=0.40, w₄=0.10 | 偏好数据充分，偏好优先 |

**记忆辅助排序**：

* 偏好向量（v\_like / v\_dislike）从长期记忆检索，作为 preference 因子的输入

* goal\_embedding 从 structured\_goal 的 topics 关键词拼接生成，作为 similarity 因子的参考向量（3.2.3 因子表）

* 情节记忆不参与排序因子计算，仅在冷启动阶段提供初始权重参考值

* **feedback\_bias 与 preference 的关系**：详见排序公式说明（本节上方），此处不重复定义

* **source\_diversity\_bonus**：P1 阶段直接加到 final\_score（`final_score += source_diversity_bonus`），P0 阶段值为0不参与排序

**预处理与归一化**：

* 排序前用时间衰减函数预筛：`decay = exp(-Δt / 24h)`，低于阈值的条目跳过排序

* 排序前对所有因子做 Min-Max 归一化至 \[0, 1]

* 引入 `feedback_bias`：正向反馈 +0.15，负向反馈 -0.10，叠加到 preference 因子（定义详见排序公式说明）

> **来源**：决策 T2/T3/T7、共识 12、独特点 3/6/41/42/51/53/20/15/70

#### 3.2.4 子 Agent — 简报 Agent

**职责**：将排序后的条目组织为结构化简报，含质量审查和重试机制。不使用 ReAct（一次生成+审查即可）。

**参与决策场景**：①②③④⑤（需要完整简报的场景；⑥跳过简报时不参与）

| 子功能           | 设计决策                                                                                   |
| ------------- | -------------------------------------------------------------------------------------- |
| 独立 StateGraph | 简报 Agent 有自己的 State 和工作流，由主 Agent 调度                                                   |
| 沿用已有字段        | generate\_briefing 沿用排序 Agent 传来的 category/importance/keywords，LLM 只做摘要生成 + 分类组织       |
| 输出格式          | LLM 输出结构化 JSON，再渲染为 Markdown                                                           |
| 分组规则          | items 按 `category` 字段分组展示，每组内按 `importance` 降序排列。简报顶层 `category` 为最高 importance 条目所属类别 |
| 重要性标注         | 每条目含 importance 字段（1-5 级），来源为排序 Agent 传来的值                                             |
| 来源引用          | 每条目含 source\_url 字段                                                                    |
| 去重标注          | 计数标注：「{title}（还有 {n} 篇类似报道）」                                                           |
| 质量评分          | `brief_quality` 结构化评分：{completeness, relevance, coherence, score}，score < 0.7 触发重试     |
| 矛盾检查          | 检查简报中是否存在自相矛盾的信息                                                                       |
| 简报风格          | MVP 阶段默认 concise 风格，预留 detailed / bullet 等风格切换接口                                       |

**简报 Agent 工具集**：

| 工具                    | 说明                 | 详情  |
| --------------------- | ------------------ | --- |
| `generate_briefing`   | LLM 生成结构化 JSON 简报  | 6.2 |
| `brief_quality_check` | 质量评分 + 矛盾检查 + 重试判断 | 6.2 |

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
      "category": "AI Agent",
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

> **分组规则**：items 按 `category` 字段分组展示（同一 category 的条目连续排列），每组内按 `importance` 降序排列。简报顶层 `category` 为最高 importance 条目所属类别。

> **字段归属说明**：JSON Schema 中的 `quality` 字段与 State 中的 `brief_quality` 是同一份质量评分数据的两种形态——`quality` 嵌在简报 JSON 内用于前端渲染，`brief_quality` 作为 State 独立字段供 coordinator\_reflect 节点读取和可能更新。二者内容相同，由简报 Agent 同时写入 `briefing_result.brief_quality` 和 `briefing.quality`（详见 4.5.4）。

#### 3.2.5 推送模块

> **架构归属**：推送属于主Agent交付环节（4.5.1 流程图末尾 push\_notification 节点），反馈触发独立的反馈子Agent（4.6），两者属于不同层级。

**职责**：定时推送简报，重大事件破例推送。

| 子功能    | 设计决策                                                                                   |
| ------ | -------------------------------------------------------------------------------------- |
| 推送机制   | 定时推送（APScheduler CronTrigger）+ 重大事件破例（排序完成后 planner 判断 `push_immediate=true`，详见 4.5.1） |
| 推送渠道   | 应用内渠道（Streamlit 页面展示）                                                                  |
| 推送服务部署 | MCP Server (stdio 模式)，作为子进程随主进程启停                                                      |

#### 3.2.6 反馈模块

> **架构归属**：反馈触发独立的反馈子 Agent（4.6），异步执行不阻塞主流程。

> **P0 实现路径**：FeedbackAgent 属于 P0——没有反馈子 Agent，feedback\_bias 和 EMA 偏好更新都无法实现，P0 的"用户反馈闭环"假设无法验证。反馈子 Agent 作为独立 StateGraph 通过 `threading.Thread` 异步运行（4.6），P0 完整实现 feedback\_bias 临时补偿 + EMA 偏好向量永久更新 + ChromaDB 写入。

**职责**：接收用户反馈，触发偏好更新。

| 子功能       | 设计决策                                           |
| --------- | ---------------------------------------------- |
| 反馈选项      | 三级：like（+偏好）/ dislike（-偏好）/ irrelevant（从候选集移除） |
| 反馈子 Agent | 反馈处理独立运行，异步更新偏好向量，不阻塞主流程                       |

**反馈权重差异化**：

| 反馈类型       | feedback\_bias 值 | 语义                           |
| ---------- | ---------------- | ---------------------------- |
| like       | +0.15            | 内容有价值，临时补偿偏好因子（EMA更新后此值归零）   |
| dislike    | -0.10            | 内容质量差，临时弱化偏好因子（EMA更新后此值归零）   |
| irrelevant | -0.15            | 内容不属于关注领域，从候选集移除（EMA更新后此值归零） |

> **机制区分**：表中数值为 `feedback_bias`（偏好因子的即时临时补偿），与 EMA 偏好向量更新是两套独立机制。两者时序互补的完整定义详见 3.2.3 排序公式说明，此处不再重复。

### 3.3 P1 增强功能（可裁剪）

P1 功能**不影响 P0 核心假设验证**，尽量实现但可裁剪。P0 已定义的功能（如 EMA 偏好更新、FeedbackAgent）不在 P1 重复列出。

#### 3.3.1 反思增强模块

**职责**：增强主 Agent `coordinator_reflect` 节点和简报 Agent `brief_quality_check` 节点的审查维度。

| 子功能    | 设计决策                                             |
| ------ | ------------------------------------------------ |
| 三维度审查  | 主 Agent coordinator\_reflect 增加完整性/去重遗漏/可追溯性三个维度 |
| 矛盾检查细化 | 简报 Agent brief\_quality\_check 的矛盾检测规则细化         |

#### 3.3.2 偏好深化

**职责**：在 P0 已实现的 EMA 偏好更新基础上，增加更精细的偏好管理能力。

| 功能      | P0 已有                       | P1 新增                                        |
| ------- | --------------------------- | -------------------------------------------- |
| 偏好向量维护  | ✅ FeedbackAgent 实现基础 EMA 更新 | 偏好自动清理阈值优化、语义记忆种子数据自动补充                      |
| 来源多样性加分 | ❌ P0 默认值为 0，不参与排序           | 同一事件多角度报道合并后获得 +0.05 排序加分（直接加到 final\_score） |
| 执行仪表盘   | ❌                           | Streamlit 页面展示执行成功率、耗时、去重率、反馈率等历史指标          |

### 3.4 P2 后续迭代方向（MVP 不实现，预留扩展点）

| **方向**             | **原因**                   | **扩展点**                             |
| :----------------- | :----------------------- | :---------------------------------- |
| 多用户认证              | MVP 单用户验证假设，不需要 JWT      | 5.1 数据模型预留 `user_id FK`             |
| Telegram / 邮件推送渠道  | MVP 只做应用内推送              | P2 预留 Telegram Bot 接口               |
| Docker Compose 容器化 | 本地 Python 直接运行足够验证       | P2 `docker compose up` 一键启动         |
| 跨类别配额              | 排序逻辑够用，防止信息茧房是后续优化       | P2 预留                               |
| 主动追问式偏好校准          | 偏好学习通过反馈闭环自动完成           | P2 预留                               |
| 简报风格切换             | MVP 默认 concise 风格        | `generate_briefing` 接口预留 `style` 参数 |
| 双 LLM 供应商冗余        | MVP 单供应商（DeepSeek）足够     | `LLMProvider` 接口预留 fallback         |
| 多语言 Embedding      | bge-small-zh-v1.5 覆盖中文场景 | P2 BGE-M3                           |
| 工具调用路由层            | MVP 手动指定 FC/MCP 足够       | P2 智能路由                             |

***

## 4. 技术架构选型

### 4.1 整体架构

FeedLens 采用**六层多 Agent 架构**（感知层 → 大脑层 → 规划层 → 工具层 → 记忆层 → 展示层），以 LangGraph StateGraph 为核心编排框架。主 Agent 作为 Coordinator + Planner 自主编排子 Agent。各层级属性如下：

| 层级  | 属性           | 说明                                                   |
| --- | ------------ | ---------------------------------------------------- |
| 感知层 | **核心层**      | 信息输入 + 环境状态变化感知                                      |
| 大脑层 | **核心层**      | LLM 推理决策                                             |
| 规划层 | **核心层**      | 自主规划 + ReAct 循环（P0 核心差异化）                            |
| 工具层 | **核心层**      | 执行能力（FC + MCP + 子 Agent）                             |
| 记忆层 | **核心层**      | 知识支撑（短期/长期/情节/语义）                                    |
| 展示层 | **交付层：推送承载** | MVP 的推送交付载体（定时推送 + 反馈交互通过 Streamlit 实现），非 Agent 核心逻辑 |

```
┌─────────────────────────────────────────────────────────┐
│   展示层 (Streamlit)                    [交付层：推送承载] │
│  配置界面 | 简报阅读 | 反馈操作 | 执行仪表盘               │
└──────────────────────┬──────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────┐
│               规划层 — 主 Agent                   [核心层] │
│   Coordinator + Planner (ReAct Think→Act→Observe→Think) │
│   understand_intent → planner → invoke_sub_agent →       │
│   coordinator_reflect → push_notification → update_memory            │
│                                                          │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐                │
│   │采集子Agent│ │排序子Agent│ │简报子Agent│ ← planner调度 │
│   │ ReAct循环 │ │ ReAct循环 │ │ 线性流程  │                │
│   └──────────┘ └──────────┘ └──────────┘                │
│                                                          │
│   ┌──────────────────┐                                  │
│   │反馈子Agent(异步)  │ ← 用户反馈触发                    │
│   └──────────────────┘                                  │
├──────────────────────┬──────────────────────────────────┤
│                     大脑层 (LLM)                   [核心层] │
│          DeepSeek（主力） | LLMProvider 抽象接口           │
├──────────────────────┬──────────────────────────────────┤
│       ┌──────────────┴──────────────┐                    │
│       │         工具层              │           [核心层]    │
│   ┌───┴───┐  ┌───┴───┐  ┌───┴───┐                    │
│   │  FC   │  │  MCP  │  │  MCP  │                    │
│   │ Chroma│  │Search │  │ Push  │                    │
│   │  DB/  │  │ (SSE) │  │(stdio)│                    │
│   │ SQLite│  │ :8100 │  │       │                    │
│   └───────┘  └───────┘  └───────┘                    │
├─────────────────────────────────────────────────────────┤
│                     记忆层                        [核心层] │
│   短期(15轮State) | 长期(ChromaDB) | 语义(ChromaDB)       │
│   情节(SQLite) | 超窗压缩(LLM→ChromaDB)                   │
├─────────────────────────────────────────────────────────┤
│                     感知层                        [核心层] │
│   RSS 输入 | 搜索结果 | 用户 Goal | 用户反馈              │
└─────────────────────────────────────────────────────────┘
```

> **架构映射**：规划层包含主 Agent（Coordinator + Planner，ReAct 循环）和 3 个子 Agent（采集/排序/简报），工具层对应 Prompt 的 Tools（FC + MCP + 子 Agent），记忆层对应 Prompt 的 Memory（短期/长期/情节/语义四层）。

| **业务闭环步骤** | **层级**   | **流程节点**                         |
| :--------- | :------- | :------------------------------- |
| 用户设定 Goal  | 感知层→规划层  | `understand_intent`              |
| 采集         | 工具层→规划层  | `invoke(Collection)` → `observe` |
| 排序         | 工具层→记忆层  | `invoke(Ranking)` → `observe`    |
| 简报         | 工具层→大脑层  | `invoke(Briefing)` → `observe`   |
| 推送         | 交付层(展示层) | `push_notification`              |
| 反馈         | 感知层→记忆层  | 反馈子 Agent(异步，§4.6)               |

> **闭环机制**：六层架构构成完整的 Agent 循环——感知层获取环境变化（RSS新数据入库、用户反馈提交、APScheduler定时触发），大脑层+规划层做出决策，工具层+子Agent执行行动，记忆层支撑决策与行动，结果通过交付层（展示层）呈现给用户，用户反馈再回到感知层，启动下一轮循环。

### 4.2 技术栈选型表

| 组件           | 选型                        | 决策依据                               | 约束力   |
| ------------ | ------------------------- | ---------------------------------- | ----- |
| Agent 编排框架   | **LangGraph StateGraph**  | 全部 9 份文档共识                         | ★★★★★ |
| LLM 后端       | **DeepSeek**（主力）          | 国内可用、支持 FC、性价比高                    | ★★★★☆ |
| LLM 调用抽象     | **LLMProvider 接口**        | 预留双供应商扩展点，MVP 只实现 DeepSeekProvider | ★★★☆☆ |
| Embedding 模型 | **bge-small-zh-v1.5**（本地） | 免费、无速率限制、中文效果好                     | ★★★☆☆ |
| 向量数据库        | **ChromaDB**              | 轻量、本地运行                            | ★★★★★ |
| 关系数据库        | **SQLite**（WAL 模式）        | 零部署、单文件                            | ★★★★★ |
| 前端框架         | **Streamlit**             | 快速构建 MVP 界面                        | ★★★★★ |
| 定时调度         | **APScheduler**           | 轻量、Python 原生                       | ★★★★★ |
| RSS 解析       | **feedparser**            | 成熟稳定                               | ★★★★★ |
| 中文分词         | **jieba**（可选工具）           | 关键词提取辅助，不作为核心依赖                    | ★★★☆☆ |
| ORM          | **原生 SQL**                | 透明可调试                              | ★★★★★ |
| 日志           | **structlog**             | 结构化日志                              | ★★★☆☆ |
| 部署           | **本地 Python 直接运行**        | 开发迭代快，MVP 纯本地                      | ★★★★★ |

### 4.3 调度集成：APScheduler + LangGraph

「定时执行」是 4 大差异化之一。APScheduler 与 LangGraph 的集成模式需要明确定义：

| 集成要素       | 设计                                                                                         | 说明                                                                                                                  |
| ---------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------- |
| **触发方式**   | APScheduler 的 CronTrigger 直接调用 `agent.invoke(initial_state)`                               | `initial_state = {trigger_type: "daily_briefing", user_goal: ..., structured_goal: ...}`，从 config.yaml 读取 cron 触发时间 |
| **进程架构**   | APScheduler 使用 BackgroundScheduler 在 Streamlit 进程内的独立后台线程运行                                | 不阻塞 Streamlit 主线程的事件循环（Tornado），scheduler 和主线程共享数据库实例                                                               |
| **持久化**    | APScheduler 使用 MemoryStore（非持久化）                                                           | MVP 单机运行，进程重启后重新注册 CronTrigger；无需持久化                                                                                |
| **启动顺序**   | Streamlit 启动 → 从 config.yaml 读取 cron 触发时间 → 注册 APScheduler CronTrigger → scheduler.start() | MVP 单用户场景，cron 时间硬编码（默认 09:00），不从数据库读取；V2 多用户时改为从 users 表读取                                                         |
| **重大事件检测** | 排序 Agent 完成后 planner 判断 `push_immediate`                                                   | 重大事件在正常每日简报流程内检测，不依赖独立的定时检查（详见 4.5.1）                                                                               |

### 4.4 工具调用策略（FC + MCP）

系统采用三层工具调用策略

| 类型                   | 特征                     | 工具列表                                                                                                                                                                                        | 部署模式                            |
| -------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------- |
| **子 Agent**          | 独立 StateGraph + 自主决策能力 | `CollectionAgent`（采集+ReAct）、`RankingAgent`（去重+排序+ReAct）、`BriefingAgent`（简报生成+审查）、`FeedbackAgent`（反馈+偏好更新，异步）                                                                                | 主 Agent 通过 LangGraph 子图调用       |
| **MCP Server**       | 需独立部署、涉及外部系统           | `search_web`（搜索采集）、`push_notification`（简报推送）                                                                                                                                                | search: **SSE**；push: **stdio** |
| **Function Calling** | 逻辑简单、参数明确、紧耦合          | 子 Agent 内部工具：fetch\_rss、enrich\_metadata、normalize\_items、deduplicate、rank\_items、generate\_briefing、brief\_quality\_check、update\_preference、db\_read、db\_write、vector\_search、vector\_add | 进程内直接调用                         |

**子 Agent 注册机制**：

子 Agent 作为主 Agent 的工具注册类型，主 Agent planner 输出编排计划时指定要调用的子 Agent。LangGraph 通过 `add_node("invoke_sub_agent", invoke_sub_agent_node)` 实现调度，invoke\_sub\_agent\_node 根据当前 `sub_agent_plan` 选择并执行对应的子 Agent StateGraph。

### 4.5 Agent 工作流（多Agent ReAct 编排）

系统采用**主 Agent + 3 个子 Agent** 的多 Agent 架构。主 Agent 通过 ReAct 循环自主编排子 Agent 的调用顺序和次数。

#### 4.5.1 主 Agent StateGraph（Coordinator + Planner）

```
                    ┌─────────────────────┐
                    │   understand_intent   │
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │      planner          │ ← ReAct Think
                    │  LLM判断本轮执行策略    │
                    │  输出: sub_agent_plan  │
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │  invoke_sub_agent     │ ← ReAct Act
                    │  按 plan 调度子 Agent  │
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐     ┌──────────────┐
                    │  observe_results      │ ← ReAct Observe
                    │  评估子 Agent 输出     │
                    └──────────┬──────────┘
                               ↓ (条件路由)
                    ┌──────────┴──────────┐ → (needs_retry?) → 路由到 planner(再思考)
                    │  planner (再思考)      │ → (Done?) → 路由到 coordinator_reflect
                    └──────────┬──────────┘     └──────────────┘
                               ↓ (Done)
                    ┌─────────────────────┐
                    │ coordinator_reflect    │ 综合质量审查
                    └──────────┬──────────┘ → (quality < 0.7 & retry < 2?) → 回退 planner（重新规划）
                               ↓
                    ┌─────────────────────┐
                    │  push_notification    │ (MCP stdio)
                    │  定时推送 / 重大事件破例│ ← planner 输出 push_immediate=true 时触发立即推送
                    └──────────┬──────────┘
                               ↓
                    ┌─────────────────────┐
                    │   update_memory       │
                    └─────────────────────┘

          ┌─────────────────────────────┐
          │    反馈子 Agent (异步)        │ ← 用户反馈触发
          │  feedback → update_preference │（完整流程含 vector_add + db_write，见4.5.2）
          └─────────────────────────────┘
```

**ReAct 循环机制**：

* 主 Agent 在 planner → invoke → observe → planner(再思考) 构成 ReAct 循环

* planner 输出编排计划：`{sub_agent_plan: [{agent: "Collection", params: {...}}, {agent: "Ranking", ...}], reason: str}`

* observe 评估子 Agent 输出质量，决定是否需要补充（如采集不足→再调度 Collection 补充搜索）

* 最多 3 个 ReAct 循环（防止无限循环），超过后强制进入 coordinator\_reflect

**planner 节点 Prompt 设计**：

planner 是 P0 核心差异化节点，其 LLM 调用的输入、输出和安全约束需要明确定义，以确保「自主规划」能力可落地实现。

**planner 输入 context（LLM 可见信息）**：

| 信息                  | 来源                                                      | 说明                                                          |
| ------------------- | ------------------------------------------------------- | ----------------------------------------------------------- |
| `trigger_type`      | understand\_intent 输出                                   | 本次触发类型（daily\_briefing / manual\_search / feedback\_update） |
| `structured_goal`   | understand\_intent 输出                                   | 用户关注领域结构化字段                                                 |
| 当前轮次子 Agent 结果      | collection\_result / ranking\_result / briefing\_result | 已执行的子 Agent 返回值（首轮为空）                                       |
| `react_cycle_count` | State 字段                                                | 已执行的 ReAct 循环次数（上限 3）                                       |
| 短期记忆摘要              | short\_term\_memory                                     | 最近 3 轮执行摘要（State 存 15 轮，planner 仅取最近 3 轮摘要，避免 context 过长）   |
| 环境状态                | 动态计算                                                    | RSS 源可用数、ChromaDB 偏好向量状态、上次简报质量评分                           |

**planner 输出格式**：

```json
{
  "sub_agent_plan": [
    {"agent": "Collection", "params": {"structured_goal": {...}, "search_count": 5}},
    {"agent": "Ranking", "params": {"normalized_items": "...", "feedback_count": 7}},
    {"agent": "Briefing", "params": {"ranked_items": "...", "style": "concise"}}
  ],
  "skip": [],
  "reason": "标准每日简报流程，采集结果预计充足",
  "push_immediate": false
}
```

**planner 安全约束**：

| 约束                 | 限制    | 理由                                                                         |
| ------------------ | ----- | -------------------------------------------------------------------------- |
| 单次 plan 子 Agent 数量 | ≤ 3   | 3.2.1 所有场景单步最多 3 个子 Agent；防止 LLM 编排出过长的执行链                                 |
| 同一子 Agent 重复调度     | ≤ 2 次 | 最多场景为 Collection 补充搜索（调用 2 次）或 Ranking 调参重排（调用 2 次）；防止 LLM 对同一子 Agent 无限重试 |
| 输出必含 reason 字段     | 强制    | 可观测性要求——planner 的决策依据必须可追溯（8.4 日志记录依赖此字段）                                  |
| ReAct 循环上限         | 3 次   | 防止无限循环，超过后强制进入 coordinator\_reflect（4.5.1 ReAct 循环机制）                      |

> **planner 决策场景**：planner 的具体编排决策规则已在 3.1 场景映射表中详细定义（正常简报、采集不足、排序不理想、重大事件、跳过采集、跳过简报、空数据回退），此处不再重复。

> **最大子Agent调用数估算**：3循环 × 最多3子Agent/循环 = 9次理论上限，但同一子Agent≤2次约束将实际上限降为约6次（典型场景：Collection×2 + Ranking×1 + Briefing×1 = 4次）。

#### 4.5.2 子 Agent StateGraph

**采集 Agent（ReAct 循环）**：

```
planner → fetch_rss → observe → (items < 5?) → search_web → observe → Done
```

Think: 判断采集策略 → Act: 执行采集 → Observe: 评估结果 → Think: 是否需要补充搜索

> **简化展示**：此流程图省略了 ReAct 回退路径（如 observe 不达标后回到 Think 重新规划），实际采集 Agent 含完整 ReAct 循环（详见 4.5.1）。

**排序 Agent（ReAct 循环）**：

```
planner → vector_search(偏好) → deduplicate → rank_items → observe → Done
```

Think: 检索偏好向量、规划排序策略 → Act: 去重+排序 → Observe: 评估排序结果 → Think: 是否需要调参

> **简化展示**：此流程图省略了 ReAct 回退路径（如 observe 不达标后回到 Think 调参重排），实际排序 Agent 含完整 ReAct 循环（详见 4.5.1）。

**简报 Agent（线性流程）**：

```
generate_briefing → brief_quality_check(FC) → (quality < 0.7 & retries < 2?) → 重试 → Done
```

不使用 ReAct——一次生成+质量审查即可，不合格重试。

> **reflect 命名统一**：简报 Agent 内部质量审查工具命名为 `brief_quality_check`（FC），主 Agent 综合质量审查节点命名为 `coordinator_reflect`（StateGraph 节点）。两者职责不同：前者负责简报质量评分+矛盾检查，后者负责综合审查所有子 Agent 输出。

**反馈子 Agent（异步触发）**：

```
feedback → update_preference(EMA) → vector_add(偏好向量) → db_write(反馈表+偏好表) → Done
```

#### 4.5.3 任务生命周期管理（Session / Turn / Event）

系统采用三层任务生命周期模型，映射到多 Agent 的运行机制：

| 层级              | 定义                                       | LangGraph 映射                          | 数据记录位置                      |
| --------------- | ---------------------------------------- | ------------------------------------- | --------------------------- |
| **Session（会话）** | 用户的一次使用周期                                | `session_id` 贯穿多次 `agent.invoke()` 调用 | `execution_logs.session_id` |
| **Turn（轮次）**    | 主 Agent 的一次完整 ReAct 循环（从 planner 到 push） | 一次 `agent.invoke()` 为一个 Turn          | `execution_logs.turn`       |
| **Event（事件）**   | Turn 内的一个节点执行（含子 Agent 调度）               | 一个 StateGraph 节点执行为一个 Event           | `execution_logs.event`      |

**生命周期流转示例**：

```
Session-001 (用户设置 Goal，session 开始)
  ├── Turn-1 (第 1 天，APScheduler 触发 daily_briefing)
  │     ├── Event: understand_intent
  │     ├── Event: planner (输出 plan: Collection → Ranking → Briefing)
  │     ├── Event: invoke_sub_agent(Collection)
  │     │     └── 采集 Agent 内部: fetch_rss → observe → search_web → Done
  │     ├── Event: observe_results (采集: 12 items)
  │     ├── Event: planner (再思考: 采集足够，继续)
  │     ├── Event: invoke_sub_agent(Ranking)
  │     │     └── 排序 Agent 内部: vector_search → deduplicate → rank_items → Done
  │     ├── Event: observe_results (排序: 8 items)
  │     ├── Event: planner (再思考: Done)
  │     ├── Event: invoke_sub_agent(Briefing)
  │     │     └── 简报 Agent 内部: generate_briefing → brief_quality_check → Done
  │     ├── Event: coordinator_reflect (综合质量审查)
  │     ├── Event: push_notification
  │     └── Event: update_memory
  │
  ├── [非主Agent Turn] (用户反馈 like → 反馈子 Agent 独立异步执行，不属于主Agent Turn序列)
  │     反馈子 Agent: feedback → update_preference → vector_add → db_write → Done
  │
  └── Turn-2 (第 2 天，APScheduler 再次触发)
        └── ...（主 Agent 自主决定本轮编排）
```

#### 4.5.4 主 Agent State 定义（TypedDict）

```python
class FeedLensState(TypedDict):
    # 触发信息
    trigger_type: str          # daily_briefing / manual_search / feedback_update
    user_goal: str             # 用户 Goal 文本
    structured_goal: dict      # LLM 提取的结构化偏好

    # planner 编排（P0 核心）
    sub_agent_plan: list[dict] # planner 输出的子 Agent 调度计划
    react_cycle_count: int     # 当前 ReAct 循环次数（上限 3）

    # 子 Agent 结果
    collection_result: dict    # 采集 Agent 返回的结果
    ranking_result: dict       # 排序 Agent 返回的结果
    briefing_result: dict      # 简报 Agent 返回的完整结构（包含 briefing + brief_quality）

    # 简报（简报 Agent 输出的最终格式）
    briefing: dict             # 结构化 JSON 简报内容（从 briefing_result.briefing 提取，供 push_notification 和前端渲染使用）
    brief_quality: dict        # {completeness, relevance, coherence, score}
                              # 初始由简报Agent写入 briefing_result.brief_quality
                              # coordinator_reflect 节点可能重新评分后更新此独立字段

    # 反思
    retry_count: int
    reflection_notes: str
    observation_result: dict      # observe_results 输出的条件路由摘要（{quality_summary, needs_retry, suggested_action}）

    # 记忆
    short_term_memory: list[dict]  # 滑动窗口（最近 15 轮）
    retrieved_memories: list[dict] # 从长期记忆检索的相关记忆（检索条件：user_goal keywords + 最近简报 top-3 keywords）
    feedback_history: list[dict]   # 本轮反馈记录

    # 执行指标
    execution_metrics: dict    # 耗时、去重率、采集数等
```

#### 4.5.5 主 Agent 节点接口映射表

| 节点                    | 输入（读取 State 字段）                                                                                             | 输出（写入 State 字段）                                                                        | 说明                                                                                               |
| --------------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `understand_intent`   | user\_goal, short\_term\_memory                                                                             | trigger\_type, structured\_goal                                                        | 识别任务类型 + 结构化提取                                                                                   |
| `planner`             | trigger\_type, structured\_goal, collection\_result, ranking\_result, briefing\_result, react\_cycle\_count | sub\_agent\_plan, react\_cycle\_count                                                  | **P0 核心**：LLM 自主编排子 Agent                                                                        |
| `invoke_sub_agent`    | sub\_agent\_plan                                                                                            | collection\_result/ranking\_result/briefing\_result                                    | 按计划调度子 Agent                                                                                     |
| `observe_results`     | collection\_result, ranking\_result, briefing\_result                                                       | `observation_result: dict`（条件评估摘要：{quality\_summary, needs\_retry, suggested\_action}） | 读取子 Agent 输出 → 评估质量 → 生成条件路由摘要；条件边根据 observation\_result 路由到 planner(再思考) 或 coordinator\_reflect |
| `coordinator_reflect` | briefing, brief\_quality, retry\_count                                                                      | brief\_quality, retry\_count, reflection\_notes                                        | 综合质量审查 + 矛盾检查。读取 briefing\_result.brief\_quality（简报Agent写入），可能重新评分后更新 brief\_quality 独立字段        |
| `push_notification`   | briefing                                                                                                    | —                                                                                      | 推送交付                                                                                             |
| `update_memory`       | feedback\_history, briefing, execution\_metrics                                                             | short\_term\_memory, retrieved\_memories                                               | 偏好更新 + 执行记录                                                                                      |

#### 4.5.6 子 Agent 调用接口

子 Agent 作为主 Agent 的工具注册类型

| 子 Agent              | 输入参数                                                                   | 输出                                                             | 说明               |
| -------------------- | ---------------------------------------------------------------------- | -------------------------------------------------------------- | ---------------- |
| `CollectionAgent`    | `{structured_goal: dict, search_count: int}`                           | `{raw_items: list, normalized_items: list, items_count: int}`  | 采集 + 元数据提取 + 标准化 |
| `RankingAgent`       | `{normalized_items: list, structured_goal: dict, feedback_count: int}` | `{deduped_items: list, ranked_items: list, dedup_rate: float}` | 去重 + 偏好排序        |
| `BriefingAgent`      | `{ranked_items: list, style: str}`                                     | `{briefing: dict, brief_quality: dict}`                        | 简报生成 + 质量审查      |
| `FeedbackAgent` (异步) | `{feedback: dict, user_id: int}`                                       | `{preference_updated: bool}`                                   | 反馈处理 + 偏好更新      |

### 4.6 反馈回路与个性化闭环

FeedLens 的「个性化筛选」能力依赖完整的反馈回路。回路路径如下：

```
环境变化（用户提交反馈）
    ↓
感知层（feedback_update 触发类型）
    ↓
反馈子 Agent（异步执行，不阻塞主流程）
    ├── update_preference: EMA 更新偏好向量
    ├── vector_add: 写入 ChromaDB user_preference collection
    └── db_write: 写入 SQLite feedback 表 + user_preferences 表
    ↓
偏好向量变化
    ↓
影响下一轮排序 Agent 的 preference 因子 + 冷启动→偏好优先切换
```

**关键时序约束**：

| 约束                  | 说明                                                 | 来源    |
| ------------------- | -------------------------------------------------- | ----- |
| 反馈异步不阻塞             | 反馈子 Agent 异步执行，不影响主 Agent 当前 Turn 的推进              | 3.2.6 |
| feedback\_bias 时序互补 | feedback\_bias 与 preference 的时序互补关系详见 3.2.3 排序公式说明 | 3.2.3 |
| 冷启动→偏好切换            | 用户反馈 ≥ 3 条时，排序权重从「相似度优先」自动切换为「偏好优先」                | 8.1   |
| 反馈写入失败降级            | 若反馈写入失败，记录 error 日志，不影响主流程继续运行                     | 8.4   |
| 偏好自动清理              | 权重 < 0.1 的偏好关键词自动清理，防止噪声干扰                         | 8.4   |

**实现模式**：反馈子 Agent 作为独立的 StateGraph，通过 `threading.Thread` 在主进程内独立线程异步调用。与主 Agent 无 State 共享，通过 ChromaDB 和 SQLite 的读后写一致性保证数据同步。

> **闭环完整性**：反馈回路是 4.1 闭环机制中「用户反馈 → 感知层」的关键环节，确保个性化筛选能力持续迭代。

***

## 5. 核心数据模型

### 5.1 结构化数据（SQLite）

> **设计意图**：MVP 单用户运行，但数据模型预留 `user_id FK` 为多用户扩展做准备。MVP 阶段 `user_id` 固定为 1。

#### 5.1.1 users — 用户表

| 字段                  | 类型          | 说明            |
| ------------------- | ----------- | ------------- |
| `id`                | INTEGER PK  | 用户 ID         |
| `goal_text`         | TEXT        | 用户输入的 Goal 文本 |
| `topics`            | TEXT (JSON) | LLM 提取的关注领域列表 |
| `keywords`          | TEXT (JSON) | LLM 提取的关键词列表  |
| `preferred_sources` | TEXT (JSON) | 推荐 RSS 源列表    |
| `created_at`        | TIMESTAMP   | 创建时间          |

#### 5.1.2 sources — 信息源表

| 字段                | 类型         | 说明                           |
| ----------------- | ---------- | ---------------------------- |
| `id`              | INTEGER PK | 源 ID                         |
| `user_id`         | INTEGER FK | 关联用户                         |
| `url`             | TEXT       | RSS/Atom 源地址                 |
| `name`            | TEXT       | 源名称                          |
| `category`        | TEXT       | 分类                           |
| `authority_score` | REAL       | 来源可信度评分（0-1）；预留扩展因子，P0 不参与排序 |
| `is_active`       | BOOLEAN    | 是否启用                         |

#### 5.1.3 raw\_items — 原始条目表

| 字段             | 类型         | 说明               |
| -------------- | ---------- | ---------------- |
| `id`           | INTEGER PK | 条目 ID            |
| `source_id`    | INTEGER FK | 来源 ID            |
| `title`        | TEXT       | 标题               |
| `summary`      | TEXT       | 摘要               |
| `content`      | TEXT       | 正文               |
| `url`          | TEXT       | 原文链接             |
| `published_at` | TIMESTAMP  | 发布时间             |
| `collected_at` | TIMESTAMP  | 采集时间             |
| `embedding_id` | TEXT       | ChromaDB 中的向量 ID |

#### 5.1.4 deduped\_items — 去重后条目表

| 字段                       | 类型          | 说明                           |
| ------------------------ | ----------- | ---------------------------- |
| `id`                     | INTEGER PK  | 条目 ID                        |
| `representative_item_id` | INTEGER FK  | 代表条目 ID（raw\_items）          |
| `similar_count`          | INTEGER     | 合并的相似条目数                     |
| `category`               | TEXT        | LLM 提取的分类                    |
| `keywords`               | TEXT (JSON) | LLM 提取的关键词                   |
| `importance`             | INTEGER     | LLM 评估的重要性（1-5）              |
| `source_diversity_bonus` | REAL        | 来源多样性加分（P0 默认 0，P1 赋值 +0.05） |
| `embedding_id`           | TEXT        | ChromaDB 中的向量 ID             |

#### 5.1.5 item\_relations — 条目关系表

| 字段                 | 类型         | 说明                                                                                           |
| ------------------ | ---------- | -------------------------------------------------------------------------------------------- |
| `id`               | INTEGER PK | 关系 ID                                                                                        |
| `item_a_id`        | INTEGER FK | 条目 A                                                                                         |
| `item_b_id`        | INTEGER FK | 条目 B                                                                                         |
| `relation_type`    | TEXT       | 关系类型：duplicate\_of / related\_to / merged\_into；P2 扩展类型，MVP 仅使用 duplicate\_of 和 merged\_into |
| `similarity_score` | REAL       | 相似度分数                                                                                        |
| `dedup_method`     | TEXT       | 判定方式：vector\_threshold / llm\_adjudication                                                   |

#### 5.1.6 briefs — 简报表

| 字段               | 类型          | 说明                                                                                                      |
| ---------------- | ----------- | ------------------------------------------------------------------------------------------------------- |
| `id`             | INTEGER PK  | 简报 ID                                                                                                   |
| `user_id`        | INTEGER FK  | 关联用户                                                                                                    |
| `date`           | DATE        | 简报日期                                                                                                    |
| `content_json`   | TEXT (JSON) | 结构化 JSON 简报内容                                                                                           |
| `content_md`     | TEXT        | 渲染后的 Markdown                                                                                           |
| `quality_score`  | REAL        | 质量评分（0-1）                                                                                               |
| `quality_detail` | TEXT (JSON) | {completeness, relevance, coherence}；`score` 作为独立列 `quality_score` 存储，便于直接查询排序；`quality_detail` 仅存子维度分数 |
| `retry_count`    | INTEGER     | 重试次数                                                                                                    |
| `created_at`     | TIMESTAMP   | 生成时间                                                                                                    |

#### 5.1.7 briefing\_items — 简报条目关联表

| 字段             | 类型         | 说明        |
| -------------- | ---------- | --------- |
| `id`           | INTEGER PK | 关联 ID     |
| `briefing_id`  | INTEGER FK | 关联简报      |
| `item_id`      | INTEGER FK | 关联条目      |
| `rank`         | INTEGER    | 在简报中的排序位置 |
| `final_score`  | REAL       | 最终排序分数    |
| `is_highlight` | BOOLEAN    | 是否为突出展示条目 |

> **新增说明**：此表将简报与条目解耦为多对多关系，支持跨简报的条目分析（如某条目在不同简报中的反馈表现）。

#### 5.1.8 feedback — 用户反馈表

| 字段              | 类型         | 说明                          |
| --------------- | ---------- | --------------------------- |
| `id`            | INTEGER PK | 反馈 ID                       |
| `user_id`       | INTEGER FK | 关联用户                        |
| `brief_id`      | INTEGER FK | 关联简报                        |
| `item_id`       | INTEGER FK | 关联条目                        |
| `feedback_type` | TEXT CHECK | like / dislike / irrelevant |
| `created_at`    | TIMESTAMP  | 反馈时间                        |

#### 5.1.9 user\_preferences — 用户偏好表

| 字段               | 类型         | 说明                 |
| ---------------- | ---------- | ------------------ |
| `id`             | INTEGER PK | 偏好 ID              |
| `user_id`        | INTEGER FK | 关联用户               |
| `keyword`        | TEXT       | 偏好关键词              |
| `weight`         | REAL       | 权重值（低于 0.1 自动清理）   |
| `vector_id`      | TEXT       | ChromaDB 中的偏好向量 ID |
| `feedback_count` | INTEGER    | 累计反馈次数             |
| `updated_at`     | TIMESTAMP  | 最后更新时间             |

#### 5.1.10 execution\_logs — 执行日志表

| 字段            | 类型          | 说明                                                      |
| ------------- | ----------- | ------------------------------------------------------- |
| `id`          | INTEGER PK  | 日志 ID                                                   |
| `session_id`  | TEXT        | 会话 ID                                                   |
| `turn`        | INTEGER     | 轮次                                                      |
| `event`       | TEXT        | 事件类型；语义与 node\_name 重叠，多数场景值相同（MVP 阶段保留两列便于细粒度查询，未来可合并） |
| `node_name`   | TEXT        | StateGraph 节点名                                          |
| `status`      | TEXT        | success / error / skipped                               |
| `duration_ms` | INTEGER     | 耗时（毫秒）                                                  |
| `metadata`    | TEXT (JSON) | 附加信息                                                    |
| `created_at`  | TIMESTAMP   | 记录时间                                                    |

#### 5.1.11 run\_logs — 运行日志表

| 字段                    | 类型         | 说明                               |
| --------------------- | ---------- | -------------------------------- |
| `id`                  | INTEGER PK | 运行 ID                            |
| `user_id`             | INTEGER FK | 关联用户                             |
| `trigger_type`        | TEXT       | daily\_briefing / manual\_search |
| `items_collected`     | INTEGER    | 采集条目数                            |
| `items_deduped`       | INTEGER    | 去重后条目数                           |
| `dedup_rate`          | REAL       | 去重率                              |
| `brief_quality_score` | REAL       | 简报质量评分                           |
| `duration_ms`         | INTEGER    | 总耗时                              |
| `status`              | TEXT       | success / error                  |
| `created_at`          | TIMESTAMP  | 运行时间                             |

### 5.2 向量数据（ChromaDB Collections）

| Collection            | 核心字段                                                                        | 用途                 |
| --------------------- | --------------------------------------------------------------------------- | ------------------ |
| **feed\_items**       | id, title, content, embedding, metadata(category, source, importance, date) | 条目向量检索与去重          |
| **user\_preference**  | user\_id, like\_embedding, dislike\_embedding, updated\_at                  | 用户长期偏好，正负分离        |
| **domain\_knowledge** | id, topic, content, embedding, seed\_flag                                   | 语义记忆种子数据（MVP 手动维护） |

> **goal\_embedding 来源说明**：排序公式 similarity 因子使用的 `goal_embedding` 不存储于 ChromaDB，而是在 understand\_intent 阶段由 `structured_goal.topics` 关键词以空格分隔拼接为单句文本（如"AI Agent 智能体 自主规划"），调用 bge-small-zh-v1.5 生成单一向量，缓存于 SQLite users 表的 topics/keywords 字段。排序 Agent 通过 State 读取 goal\_embedding，不需要重复调用 embedding 模型。P1 阶段可改为每个关键词单独 embedding 后加权平均，以获得更细粒度的领域表达。

***

## 6. API 接口设计

### 6.1 MCP 工具接口

| 工具名                 | 协议          | 方法       | 参数                                                       | 返回           | 选型理由                                       | 说明                               |
| ------------------- | ----------- | -------- | -------------------------------------------------------- | ------------ | ------------------------------------------ | -------------------------------- |
| `search_web`        | SSE (:8100) | `search` | `query: str`, `max_results: int = 10`                    | `list[dict]` | 搜索 API 是外部 HTTP 服务，需独立进程管理连接池；SSE 模式支持流式返回 | 搜索采集，流式返回结果                      |
| `push_notification` | stdio       | `push`   | `brief: dict`, `user_id: int`, `immediate: bool = False` | `bool`       | 推送服务需随主进程启停，无需管理端口；stdio 部署复杂度最低           | 推送简报；`immediate=True` 表示重大事件破例推送 |

> **选型原则**：工具需独立部署或有状态 → MCP；工具是纯函数逻辑或进程内 SDK 调用 → FC。详见 4.4。

### 6.2 Function Calling 工具接口

| 工具名                   | 方法                    | 参数                                                                  | 返回                       | 选型理由                                     | 说明                                                  |
| --------------------- | --------------------- | ------------------------------------------------------------------- | ------------------------ | ---------------------------------------- | --------------------------------------------------- |
| `fetch_rss`           | `fetch`               | `sources: list[str]`                                                | `list[dict]`             | RSS 解析是纯函数逻辑（feedparser 无状态），进程内调用延迟最低   | 并行采集多个 RSS 源                                        |
| `enrich_metadata`     | `enrich`              | `items: list[dict]`                                                 | `list[dict]`             | LLM 单次推理无持久状态，FC 调用最简单                   | LLM 提取 category/keywords/importance                 |
| `normalize_items`     | `normalize`           | `items: list[dict]`                                                 | `list[dict]`             | 字段格式化是纯数据转换（无 I/O），FC 开销最小               | 统一字段格式                                              |
| `deduplicate`         | `dedup`               | `items: list[dict]`, `threshold: float = 0.88`                      | `list[dict], list[dict]` | 向量检索依赖 ChromaDB 进程内 SDK，FC 直接调用无需 IPC 开销 | 返回去重后条目 + 关系记录                                      |
| `rank_items`          | `rank`                | `items: list[dict]`, `structured_goal: dict`, `feedback_count: int` | `list[dict]`             | 排序是纯计算逻辑（无 I/O），FC 调用性能最优                | 多因子加权排序 + 记忆辅助；`structured_goal` 与 4.5.4 State 定义一致 |
| `generate_briefing`   | `generate`            | `ranked_items: list[dict]`, `style: str = "concise"`                | `dict`                   | 合并摘要+简报生成为单次 LLM 调用，减少调用次数               | 生成结构化 JSON 简报                                       |
| `brief_quality_check` | `brief_quality_check` | `brief: dict`                                                       | `dict`                   | 质量评分 + 矛盾检查是纯计算 + 单次 LLM 调用              | 质量评分 + 重试判断                                         |
| `update_preference`   | `update`              | `feedback: dict`, `user_id: int`                                    | `dict`                   | 偏好更新最终调用 db\_write（FC），链路最短              | 更新用户偏好向量                                            |
| `db_read`             | `read`                | `table: str`, `conditions: dict`                                    | `list[dict]`             | SQLite 是无状态查询，进程内调用延迟最低                  | SQLite 读取                                           |
| `db_write`            | `write`               | `table: str`, `data: dict`                                          | `bool`                   | SQLite 是单次写操作，进程内调用延迟最低                  | SQLite 写入                                           |
| `vector_search`       | `search`              | `collection: str`, `query: str`, `top_k: int = 5`                   | `list[dict]`             | ChromaDB SDK 是进程内调用，FC 直接调用无需 IPC 开销     | ChromaDB 相似度检索                                      |
| `vector_add`          | `add`                 | `collection: str`, `documents: list[str]`, `metadatas: list[dict]`  | `list[str]`              | ChromaDB SDK 是进程内调用，FC 直接调用无需 IPC 开销     | ChromaDB 写入向量                                       |

> **注意**：planner 节点已在 4.5.1 详细定义（P0 核心差异化），此处不作为 FC 工具列出（planner 是 StateGraph 节点，不是 FC 工具）。

### 6.3 Streamlit 页面路由

| 页面        | 路径          | 功能                         |
| --------- | ----------- | -------------------------- |
| 首页 / 简报查看 | `/`         | 展示最新简报，支持查看历史简报            |
| Goal 设置   | `/settings` | 输入 Goal 文本，查看 LLM 提取的结构化字段 |
| RSS 源管理   | `/sources`  | 添加/删除/启用 RSS 源             |
| 反馈记录      | `/feedback` | 查看历史反馈记录和偏好变化趋势            |
| 执行日志      | `/logs`     | 查看 Agent 运行日志（P1）          |

***

## 7. 里程碑规划

### 阶段一：项目骨架 + 数据模型

**目标**：搭建项目结构，定义数据模型，跑通 LangGraph 基础工作流。

**依赖**：无

**复杂度**：中

| 交付物                     | 验收标准                                                        |
| ----------------------- | ----------------------------------------------------------- |
| 项目目录结构                  | 符合模块化设计，包含 config / models / nodes / tools / utils          |
| SQLite 表结构初始化脚本         | 全部 11 张表创建成功，WAL 模式开启                                       |
| ChromaDB 集合初始化          | feed\_items / user\_preference / domain\_knowledge 三个集合创建成功 |
| LangGraph StateGraph 骨架 | 主 Agent + 4 个子 Agent StateGraph 骨架定义完成，节点和边连接正确，空实现可跑通      |
| bge-small-zh-v1.5 模型加载  | 本地加载成功，推理速度 < 100ms/条                                       |
| LLMProvider 抽象接口        | DeepSeekProvider 实现完成，接口预留 fallback 扩展点                     |

### 阶段二：信息采集 + 智能去重

**目标**：实现 RSS 采集、搜索补充、向量去重完整链路。

**依赖**：阶段一

**复杂度**：高

| 交付物                                      | 验收标准                                                                                                       |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `fetch_rss` FC 工具                        | 并行采集 3+ 个 RSS 源，feedparser 解析成功                                                                            |
| `search_web` MCP Server (SSE)            | 搜索 API 封装成功，SSE 流式返回，监听 :8100                                                                              |
| `enrich_metadata` + `normalize_items` 节点 | LLM 提取分类/关键词/重要性，字段统一格式化                                                                                   |
| `deduplicate` 节点                         | 0.88 阈值向量去重 + 0.70-0.88 模糊区间 LLM 裁决（上限 20 对，超限按 0.80 硬判）                                                   |
| `item_relations` 表写入                     | 去重关系正确记录                                                                                                   |
| 空结果回退逻辑                                  | 去重后 < 3 条自动回退采集                                                                                            |
| **主 Agent planner 节点**                   | planner 输出编排计划（sub\_agent\_plan + reason + push\_immediate），ReAct 循环跑通：planner→invoke→observe→planner(再思考) |
| `calibrate_dedup.py` 脚本                  | 标注样本 → P/R/F1 曲线 → 最优阈值输出                                                                                  |

### 阶段三：偏好排序 + 简报生成

**目标**：实现多因子排序和结构化简报生成。

**依赖**：阶段二

**复杂度**：高

| 交付物                          | 验收标准                                                                                                                  |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `rank_items` 节点              | 冷启动权重 (0.40/0.25/0.10/0.25) 和有反馈权重 (0.30/0.20/0.40/0.10) 动态切换                                                         |
| 记忆辅助排序                       | 偏好向量从 ChromaDB 检索参与 preference 因子计算；情节记忆仅在冷启动阶段提供初始权重参考值                                                              |
| 时间衰减预筛                       | 半衰期公式 τ=24h，过时内容跳过排序                                                                                                  |
| Min-Max 归一化 + feedback\_bias | 所有因子归一化至 \[0,1]，feedback\_bias 叠加到 preference                                                                         |
| `generate_briefing` 节点       | LLM 输出结构化 JSON（沿用 enrich\_metadata 已提取的 category/importance/keywords，只做摘要+分组组织），items 按 category 分组、组内按 importance 降序 |
| JSON → Markdown 渲染           | 简报正确渲染，计数标注显示                                                                                                         |
| `brief_quality` 评分 + 矛盾检查    | completeness/relevance/coherence/score 四维评分 + 矛盾检测                                                                    |

### 阶段四：推送 + 反馈 + 记忆 + P1 增强

**目标**：完成业务闭环，实现推送、反馈、反思、记忆管理，加入 P1 增强。

**依赖**：阶段三

**复杂度**：高

| 交付物                                    | 验收标准                                |
| -------------------------------------- | ----------------------------------- |
| `push_notification` MCP Server (stdio) | 推送服务作为子进程运行                         |
| APScheduler CronTrigger 定时触发           | 每日定时触发 LangGraph 工作流                |
| 重大事件破例推送                               | score > 0.85 且时效 < 2h 时立即推送         |
| `coordinator_reflect` 节点增强             | 三维度审查（完整性/去重遗漏/可追溯性）+ 矛盾检查          |
| 反馈子 Agent（FeedbackAgent）               | 反馈异步处理，偏好向量更新                       |
| 三级反馈 UI                                | like / dislike / irrelevant 三个按钮    |
| 偏好正负分离                                 | v\_like / v\_dislike 分别维护           |
| EMA 偏好更新                               | 偏好向量平滑更新，防剧烈波动                      |
| 偏好自动清理                                 | 权重 < 0.1 自动清理                       |
| 短期记忆管理                                 | 滑动窗口 15 轮，超窗 LLM 压缩写入 ChromaDB 长期记忆 |
| 冷启动 → 偏好自适应切换                          | 反馈数 >= 3 条时权重自动切换                   |

### 阶段五：集成测试 + 优化

**目标**：端到端测试，性能优化，文档交付。

**依赖**：阶段四

**复杂度**：中

| 交付物                         | 验收标准                                |
| --------------------------- | ----------------------------------- |
| 端到端集成测试                     | 从 Goal 设置到简报推送全流程跑通，无报错             |
| Streamlit 前端                | 5 个页面功能完整（首页/设置/源管理/反馈/日志）          |
| structlog 结构化日志             | 全部节点日志结构化输出                         |
| execution\_logs + run\_logs | 执行日志和运行日志正确记录                       |
| 任务级错误隔离                     | 单次失败不阻塞下次执行                         |
| 30 天数据清理                    | 定期清理过期 raw\_items 和 execution\_logs |
| 性能基准测试                      | 单次 Agent 运行 < 60s（采集 10 条 RSS 源）    |
| MVP 设计文档                    | 本文档定稿                               |
| README + 部署指南               | 包含环境配置、启动命令、依赖列表                    |

***

## 8. 其它重要补充

### 8.1 冷启动策略

MVP 阶段的冷启动是指**用户首次使用系统、尚无反馈数据**的状态。

| 维度    | 冷启动策略                           | 切换条件                                   |
| ----- | ------------------------------- | -------------------------------------- |
| 排序权重  | 相似度优先（w₁=0.40, w₃=0.10）         | 用户反馈 ≥ 3 条 → 切换为偏好优先（w₁=0.30, w₃=0.40） |
| 偏好向量  | 使用 Goal 文本提取的 keywords 生成初始偏好向量 | 有真实反馈后逐步替换为 v\_like / v\_dislike       |
| RSS 源 | LLM 根据 Goal 文本推荐初始 RSS 源列表      | 用户可在设置页面手动增删                           |
| 语义记忆  | 手动维护种子数据（领域知识、概念关系）             | 数据积累后逐步自动补充                            |

### 8.2 去重阈值校准流程

去重阈值（0.88）是经验初值，系统提供校准脚本持续优化：

```
1. 人工标注 200 对样本（正例/负例）
2. 计算每对的 cosine 相似度
3. 遍历阈值 0.70-0.95（步长 0.01），计算各阈值的 P/R/F1
4. 绘制 P/R/F1 曲线，选 F1 最优阈值
5. 更新配置文件中的 dedup_threshold 参数
```

### 8.3 数据生命周期管理

| data            | 保留策略                 | 清理方式                                                                  |
| --------------- | -------------------- | --------------------------------------------------------------------- |
| raw\_items      | 30 天                 | 定时任务清理过期记录；清理时仅删除原始文本（content/summary），deduped\_items 保留摘要+关键字供历史简报引用 |
| deduped\_items  | 30 天（随 briefs 引用期保留） | 定时任务清理过期记录；被 briefs 引用的条目延长保留至对应 briefs 生成后 30 天                      |
| execution\_logs | 30 天                 | 定时任务清理过期记录                                                            |
| run\_logs       | 90 天                 | 定时任务清理过期记录                                                            |
| briefs          | 永久保留                 | 不清理                                                                   |
| feedback        | 永久保留                 | 不清理                                                                   |
| ChromaDB 向量     | 随 raw\_items 清理同步删除  | 关联清理                                                                  |
| 短期记忆            | 15 轮滑动窗口             | 超窗 LLM 压缩写入 ChromaDB 长期记忆                                             |

### 8.4 错误处理与容错

| 场景               | 处理策略                                                                                                                                                         |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| RSS 源不可达         | 跳过该源，记录 warning 日志，继续采集其他源                                                                                                                                   |
| 搜索 API 超时        | 降级为仅使用 RSS 采集结果，记录 warning                                                                                                                                   |
| SSE 连接中断         | MCP SSE 连接断线时，立即降级为仅 RSS 模式，不阻塞采集流程；记录 warning 日志                                                                                                            |
| 去重后条目不足（< 3 条）   | 回退到采集节点，扩大时间窗/增加来源                                                                                                                                           |
| LLM 调用失败         | 重试 1 次；若仍失败，降级使用规则模板生成简报                                                                                                                                     |
| 简报质量连续不达标        | 2 次重试后接受当前最佳结果，记录日志供后续分析                                                                                                                                     |
| APScheduler 任务异常 | 捕获异常，记录 error 日志，继续下一次定时任务                                                                                                                                   |
| SQLite 并发冲突      | WAL 模式 + 事务包裹，自动重试                                                                                                                                           |
| ChromaDB 并发写入    | StateGraph 串行执行保证同一 Turn 内节点不会并发写同一 collection；反馈子 Agent（FeedbackAgent）与主流程异步运行时，对 user\_preference collection 的写入通过串行化队列（Python `queue.Queue` + 单线程消费者）保证顺序 |
| 偏好权重异常           | 权重 < 0.1 自动清理，防止噪声干扰                                                                                                                                         |

### 8.5 Embedding 工程细节

* **本地加载**：bge-small-zh-v1.5 首次下载约 100MB，应显示进度条避免用户困惑

* **备选方案**：LLM API（text-embedding-v3）作为 fallback note，MVP 不实现

* **中文分词**：jieba 分词 + 自定义停用词表作为可选关键词提取工具，不作为核心依赖（enrich\_metadata 用 LLM 提取关键词）

* **向量存储**：存于 ChromaDB，FC 直接调用 SDK，不通过 MCP

### 8.6 关键配置参数

#### 8.6.1 LLM 调用频率估算

一次完整每日简报的 LLM 调用链路（不含 ReAct 重试）：

| 节点                             | LLM 调用次数 | 说明                                                                  |
| ------------------------------ | -------- | ------------------------------------------------------------------- |
| understand\_intent             | 1        | 触发类型识别 + 结构化提取                                                      |
| planner (Think)                | 1        | 编排决策                                                                |
| 采集 Agent Think                 | 1        | 采集策略判断                                                              |
| enrich\_metadata               | N（条目数）   | 每条目 LLM 提取 category/keywords/importance（importance 归一化由排序 Agent 完成） |
| 采集 Agent Observe               | 1        | 评估采集结果                                                              |
| 排序 Agent Think                 | 1        | 排序策略                                                                |
| 排序 Agent Observe               | 1        | 评估排序结果                                                              |
| Briefing generate              | 1        | 生成简报                                                                |
| Briefing brief\_quality\_check | 1        | 质量评分                                                                |
| coordinator\_reflect           | 1        | 综合审查                                                                |

**最低估算**：12 次 + N 次 enrich\_metadata。若 N=10（典型采集量），总调用 ≈ **22 次**。
**ReAct 重试**：每多 1 个循环 ≈ +3 次（planner + observe + 子Agent Think）。

> **用途**：评估 DeepSeek API 成本和延迟预算，优化 ReAct 循环次数和 enrich\_metadata 批量策略。

#### 8.6.2 参数表

| 参数                              | 默认值               | 说明                                                                                                                                                                 | 可调      |
| ------------------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------- |
| `dedup_threshold`               | 0.88              | 去重相似度阈值                                                                                                                                                            | 是（校准脚本） |
| `dedup_llm_lower`               | 0.70              | 模糊区间下界（低于此值不重复）                                                                                                                                                    | 是       |
| `max_llm_adjudications`         | 20                | 模糊区间 LLM 裁决上限（超限按 0.80 硬判）                                                                                                                                         | 是       |
| `dedup_hard_threshold`          | 0.80              | LLM 裁决超限时的硬判阈值                                                                                                                                                     | 是       |
| `half_life_hours`               | 24                | 时间衰减半衰期                                                                                                                                                            | 是       |
| `short_term_window`             | 15                | 短期记忆滑动窗口轮数                                                                                                                                                         | 是       |
| `max_retry`                     | 2                 | 反思重试上限                                                                                                                                                             | 是       |
| `quality_threshold`             | 0.7               | 简报质量评分阈值                                                                                                                                                           | 是       |
| `min_items_for_brief`           | 3                 | 生成简报的最低条目数                                                                                                                                                         | 是       |
| `breaking_news_score`           | 0.85              | 重大事件破例推送阈值；当排序Agent输出中存在 score > breaking\_news\_score 且 published\_at 在 breaking\_news\_freshness\_hours 内的条目时，planner 应设置 push\_immediate=true（LLM自主判断，参数提供阈值引导） | 是       |
| `breaking_news_freshness_hours` | 2                 | 重大事件时效阈值                                                                                                                                                           | 是       |
| `cold_start_feedback_threshold` | 3                 | 冷启动→偏好优先切换所需反馈数                                                                                                                                                    | 是       |
| `preference_cleanup_threshold`  | 0.1               | 偏好权重自动清理阈值                                                                                                                                                         | 是       |
| `data_retention_days`           | 30                | 过期数据清理天数                                                                                                                                                           | 是       |
| `feedback_bias_positive`        | 0.15              | 正向反馈偏置                                                                                                                                                             | 是       |
| `feedback_bias_negative`        | -0.10             | 负向反馈偏置                                                                                                                                                             | 是       |
| `feedback_bias_irrelevant`      | -0.15             | 不相关反馈偏置                                                                                                                                                            | 是       |
| `ema_alpha`                     | 0.3               | EMA 平滑因子（偏好向量更新时新反馈的权重：v\_new = α·v\_current + (1-α)·v\_old）                                                                                                       | 是       |
| `source_diversity_bonus`        | 0（P0默认）→ 0.05（P1） | 来源多样性加分（3.2.3）                                                                                                                                                     | 是       |
| `w_sim_cold` / `w_sim_warm`     | 0.40 / 0.30       | 相似度权重（冷启动/有反馈，理由见 3.2.3）                                                                                                                                           | 是       |
| `w_recency`                     | 0.25 / 0.20       | 时间衰减权重（冷启动/有反馈，理由见 3.2.3）                                                                                                                                          | 是       |
| `w_pref_cold` / `w_pref_warm`   | 0.10 / 0.40       | 偏好权重（冷启动/有反馈，理由见 3.2.3）                                                                                                                                            | 是       |
| `w_importance`                  | 0.25 / 0.10       | 重要性权重（冷启动/有反馈，理由见 3.2.3）                                                                                                                                           | 是       |

> **config.yaml 结构**：8.6.2 中标注"可调"的参数均通过 `config.yaml` 配置文件读取，代码常量仅包含不可调参数（如模型名称、数据模型字段名等）。以下为 config.yaml 示例片段：

```yaml
# config.yaml — FeedLens MVP 配置
scheduler:
  cron_time: "06:00"          # 每日简报触发时间（4.3）
  timezone: "Asia/Shanghai"

agents:
  max_react_cycles: 3         # ReAct 循环上限（4.5.1）
  max_retry: 2                # 反思重试上限
  max_sub_agents_per_plan: 3  # 单次 plan 子Agent数量上限
  max_same_agent_calls: 2     # 同一子Agent重复调度上限

ranking:
  dedup_threshold: 0.88
  dedup_llm_lower: 0.70
  max_llm_adjudications: 20
  dedup_hard_threshold: 0.80
  quality_threshold: 0.7
  cold_start_feedback_threshold: 3
  half_life_hours: 24
  source_diversity_bonus: 0   # P0 默认0，P1 改为 0.05

feedback:
  feedback_bias_positive: 0.15
  feedback_bias_negative: -0.10
  feedback_bias_irrelevant: -0.15
  ema_alpha: 0.3
  preference_cleanup_threshold: 0.1

weights_cold:                 # 冷启动权重（反馈 < 3 条）
  similarity: 0.40
  recency: 0.25
  preference: 0.10
  importance: 0.25

weights_warm:                 # 有反馈权重（反馈 ≥ 3 条）
  similarity: 0.30
  recency: 0.20
  preference: 0.40
  importance: 0.10

breaking_news:
  score_threshold: 0.85       # 重大事件破例推送阈值
  freshness_hours: 2          # 重大事件时效阈值

memory:
  short_term_window: 15       # 短期记忆滑动窗口轮数

data:
  retention_days: 30          # 过期数据清理天数
  min_items_for_brief: 3      # 生成简报的最低条目数
```

