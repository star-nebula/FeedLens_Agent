# FeedLens MVP 设计文档 — 结构化提取分析

> 分析基准：9 份有效文档（全部纳入分析）
> 分析角色：资深全栈架构师
> 分析日期：2026-06-17（修订版，补入 Codex_Mimo）

---

## 【分析目录】

| # | 文档代号 | 生成模型 | 阶段数 | 工具数 | FC/MCP 分配 | 有效页 |
|---|---------|---------|--------|--------|------------|--------|
| 1 | Codex_DeepSeek | Codex+DeepSeek | 6 (P0-P6) | 12 | 10 FC + 2 MCP | ✅ |
| 2 | TRAE | TRAE | 10 | — | ChromaDB MCP + vector_store MCP | ✅ |
| 3 | GPT | ChatGPT | 5 | — | 未明确区分 FC/MCP | ✅ |
| 4 | Qwen | 通义千问 | 5 | — | 未明确区分 FC/MCP | ✅ |
| 5 | DeepSeek | DeepSeek | 4 | — | db_read/db_write MCP(stdio) | ✅ |
| 6 | Perplexity | Perplexity | 6 | 11 | 6 FC + 5 MCP | ✅ |
| 7 | GLM | 智谱 GLM | 7 (Stage 0-6) | — | 未明确区分 FC/MCP | ✅ |
| 8 | Kimi | Kimi | 5 | — | 未明确区分 FC/MCP | ✅ |
| 9 | Codex_Mimo | Codex+MiMo | 7 (P0-P6) | 8 | 6 FC + 2 MCP + 架构图含3 MCP | ✅ |

---

## 【项目定位】

FeedLens 是一款**主动推送式智能信息简报 Agent**——基于用户订阅的 RSS/搜索源，自动采集、去重、排序、摘要生成，并按优先级推送个性化信息简报，解决"信息过载但关键信息仍遗漏"的痛点。

---

## 【共识点分析】

### 1. 核心工作流：采集 → 解析 → 去重 → 排序 → 生成 → 推送

**全部 9 份文档一致**。均采用 LangGraph StateGraph 驱动，节点按上述流水线排列。

> 来源：Codex_DeepSeek §P1-P4 / TRAE §Phase 1-8 / GPT §Planner / Qwen §Stage 1-4 / DeepSeek §Phase 1-3 / Perplexity §Phase 1-5 / GLM §Stage 1-5 / Kimi §Phase 1-4 / Codex_Mimo §2.1 StateGraph

### 2. LLM 选型：DeepSeek 为主力模型

9/9 文档选择 DeepSeek API 作为主 LLM，GLM 和 Codex_Mimo 额外增加 Qwen 作为 fallback/备选。

> 来源：全部文档 · GLM §Stage 0 双供应商 · Codex_Mimo §8 技术栈 "DeepSeek / 通义千问 (备选)"

### 3. 向量存储：ChromaDB

9/9 文档选择 ChromaDB 做向量检索，理由一致：轻量、本地运行、MVP 阶段够用。

> 来源：全部文档 §技术栈

### 4. 结构化存储：SQLite

9/9 文档选择 SQLite 做结构化数据（用户偏好、订阅源、推送记录等），理由：零部署、单文件、MVP 友好。

> 来源：全部文档 §技术栈 · Perplexity 额外建议 SQLite WAL 模式

### 5. 去重：两阶段策略（规则预筛 + 向量相似度）

9/9 文档均采用"先粗筛再精判"的两阶段去重：

| 阶段 | 通用做法 | 文档 |
|------|---------|------|
| 第一阶段 | URL/标题精确匹配 / 规则过滤 | 全部 |
| 第二阶段 | 向量余弦相似度，阈值 ~0.85-0.95 判定严格重复 | 全部 |

> 来源：Codex_DeepSeek §P2 / Qwen §Stage 2 / DeepSeek §Phase 2 / Perplexity §Phase 2 / GLM §Stage 3 / Kimi §Phase 2 / Codex_Mimo §6 去重策略（0.85 严格 / 0.70 同事件不同角度）

### 6. 排序：多因子加权评分

9/9 文档均使用加权公式，核心因子一致：

**Score = w₁·similarity + w₂·recency + w₃·preference + w₄·authority**

> 来源：Codex_DeepSeek §P3 / TRAE §Ranking / Qwen §Stage 3 / DeepSeek §Phase 3 / Perplexity §Phase 3 / GLM §Stage 4 / Kimi §Phase 3 / Codex_Mimo §5 排序算法

### 7. 前端：Streamlit

9/9 文档选择 Streamlit 作为 MVP 前端。

> 来源：全部文档 §技术栈

### 8. 数据采集：feedparser + 搜索 API

9/9 文档使用 feedparser 解析 RSS，搜索 API 补充信息（Tavily/SerpAPI/SearXNG 为主）。

> 来源：全部文档 §工具设计

### 9. 调度：APScheduler / cron

8/9 文档（GPT 除外，其采用自主触发）使用 APScheduler 或系统 cron 做定时采集。

> 来源：Codex_DeepSeek §P0 / TRAE §Scheduler / Qwen §Stage 1 / DeepSeek §Phase 1 / Perplexity §Phase 1 / GLM §Stage 1 / Kimi §Phase 1 / Codex_Mimo §8 技术栈

### 10. Embedding 模型：本地中文模型

8/9 文档推荐本地中文 embedding 模型（BGE 或 text2vec），仅少数推荐 API 调用。

> 来源：Codex_DeepSeek / Qwen / DeepSeek / Perplexity / GLM（bge-small-zh）/ Kimi（bge-small-zh-v1.5）/ Codex_Mimo（text2vec-base-chinese）

---

## 【冲突点对比】

### A. 产品 / 业务逻辑冲突

| # | 冲突点 | 阵营 A | 阵营 B | 分析 |
|---|--------|--------|--------|------|
| A1 | **推送触发模式** | **定时/周期触发**（Codex_DeepSeek / TRAE / Qwen / DeepSeek / Perplexity / GLM / Kimi / Codex_Mimo）—— 用户设定时间或定时采集后推送 | **自主决策触发**（GPT）—— Agent 自判"信息量够了"或"有重大事件"时主动推送，无需固定时间 | **GPT 的方案更符合"主动推送"定位**，但实现复杂度高；定时模式 MVP 更稳。Codex_Mimo 支持 trigger_type: "scheduled"/"manual"/"feedback" 三种触发方式，是定时阵营中最灵活的。建议：MVP 用定时+手动，预留事件驱动钩子 |
| A2 | **去重边界定义** | **严格去重**（DeepSeek 0.95→0.88 聚类）—— 同主题不同角度视为重复 | **保留多角度**（Qwen 0.70-0.88 交由 LLM 判决；GLM NER+向量三级分类；Perplexity LLM 判定；Codex_Mimo 0.70-0.85 同事件不同角度保留但分组展示） | **保留多角度对信息简报更有价值**。Codex_Mimo 的方案尤为实用——同事件不同角度的两条都保留，在简报中归为一组（主条目+相关报道），兼顾去重和完整性。建议：采用 Codex_Mimo 的分组展示方案 |
| A3 | **反馈粒度** | **二元反馈**（like/dislike）—— Codex_DeepSeek / Qwen / DeepSeek / Perplexity | **多元反馈**（Kimi：四级；GLM：explicit+implicit；Codex_Mimo：positive/negative/irrelevant 三级） | **三级反馈（Codex_Mimo 方案）是最平衡的选择**——比二元精细，比四级更简洁。建议：MVP 采用 positive / negative / irrelevant 三级 |
| A4 | **是否需要用户认证** | **需要**（TRAE）—— 多用户支持，含登录/注册 | **不需要**（其余 8 份）—— 单用户 MVP，无认证 | **MVP 阶段不需要**。但 TRAE 的设计为后续扩展留了路。建议：MVP 跳过，数据模型预留 user_id 字段（Codex_Mimo 已预留） |
| A5 | **推送渠道** | **应用内推送**（Streamlit 展示）—— 8/9 份 | **Telegram 推送**（GLM）—— 选择 Telegram Bot | **应用内推送 MVP 成本最低**，但 Telegram 渠道的"主动触达"体验更好。Codex_Mimo 的 notification_push MCP 支持 channel 参数（"streamlit"/"webhook"），架构上已预留扩展。建议：MVP 用 Streamlit，二期加 Telegram/企微 |

### B. 技术架构冲突

| # | 冲突点 | 阵营 A | 阵营 B | 分析 |
|---|--------|--------|--------|------|
| B1 | **MCP 工具划分** | **DB 操作作为 MCP**（DeepSeek：db_read/db_write MCP(stdio)；TRAE：ChromaDB MCP + vector_store MCP；Codex_Mimo 架构图含 database_ops MCP(stdio)）—— 理由：DB 是独立进程/可替换组件 | **无 MCP 或仅外部服务 MCP**（Codex_DeepSeek 10FC+2MCP；Perplexity 6FC+5MCP，MCP 用于外部搜索/API；Codex_Mimo 工具表仅 web_search+notification_push MCP）—— 理由：MCP 适合跨进程外部服务 | **Codex_Mimo 存在内部不一致**：架构图列出 3 个 MCP（web_search SSE + database_ops stdio + notification_push stdio），但工具表只列出 2 个 MCP（web_search SSE + notification_push stdio），database_ops 被遗漏。这恰好说明 DB-MCP 的边界在实践中容易混淆。建议：MVP 用 FC，接口预留 MCP 迁移空间 |
| B2 | **去重技术路线** | **纯向量去重**（Codex_DeepSeek / DeepSeek / GPT）—— 仅依赖 embedding 相似度 + 阈值 | **向量 + 编辑距离组合**（Codex_Mimo：0.6·cosine + 0.4·edit_distance）—— 双信号联合判定 | **NER 实体 + 向量双重验证**（GLM）—— 先抽取实体重叠度，再叠加向量相似度 | Codex_Mimo 的编辑距离方案是一个折中选择——不需要额外 LLM 调用（不像 NER），但比纯向量多了一层符号级校验。用 `python-Levenshtein` 计算成本极低。建议：MVP 用 Codex_Mimo 的向量+编辑距离方案，二期可选引入 NER |
| B3 | **向量去重 + LLM 精判** | **阈值内一律去重**（Codex_DeepSeek / DeepSeek / Codex_Mimo）—— Codex_Mimo 的 0.70-0.85 区间保留但分组，不用 LLM 裁决 | **模糊区间交由 LLM 裁决**（Qwen 0.70-0.88 区间由 LLM 判断；Kimi 规则+向量后 LLM 二次验证） | **LLM 精判更准确但成本更高**。Codex_Mimo 的方案是"零 LLM 裁决"的替代——用阈值+分组展示代替 LLM 判断，成本更低。建议：MVP 用 Codex_Mimo 的阈值分组方案，性能允许时升级为 Qwen 的 LLM 裁决 |
| B4 | **ORM 选型** | **原生 SQL**（8/9 份）—— 直接 sqlite3 / aiosqlite | **SQLAlchemy ORM**（TRAE）—— 面向对象操作 | **MVP 用原生 SQL 更透明**，调试方便。ORM 优势在多表关联和迁移，MVP 阶段表不多。建议：MVP 原生 SQL |
| B5 | **搜索服务** | **商业 API**（Tavily / SerpAPI）—— 6/9 份 | **自托管 Searxng**（GLM / Codex_Mimo）—— 免费但需自建。Codex_Mimo 选 SearXNG 为主 + Tavily 为 fallback | **Codex_Mimo 的主备方案最务实**——SearXNG 省钱，Tavily 兜底。建议：MVP 用 Tavily 免费层快速验证，同时部署 SearXNG 作为降级方案 |
| B6 | **Embedding 方案** | **API 调用**（DeepSeek embedding / OpenAI embedding）—— 少数文档 | **本地模型**（GLM：bge-small-zh；Kimi：bge-small-zh-v1.5；Codex_Mimo：text2vec-base-chinese）—— 离线运行，零 API 成本 | **Codex_Mimo 选择 text2vec-base-chinese 而非 BGE**，理由是"中文语义向量化效果好，本地推理零成本"。两者都是本地模型，text2vec 在短文本语义匹配上与 BGE 各有千秋。建议：MVP 用 bge-small-zh（社区更活跃、文档更全），但 text2vec 可作为备选 |
| B7 | **部署方案** | **本地开发运行**（8/9 份）—— python 直接启动 | **Docker Compose**（DeepSeek）—— 容器化部署 | **Docker Compose 对简历项目有加分**，展示工程化能力。但增加 MVP 复杂度。建议：MVP 本地跑通，二期补 Dockerfile + docker-compose |
| B8 | **偏好更新算法** | **直接覆盖/简单累加**（Codex_DeepSeek / Qwen / DeepSeek / Perplexity / Codex_Mimo：positive +0.1 / negative -0.05 / irrelevant -0.15）—— 收到反馈后直接修改权重 | **指数移动平均 EMA**（GLM）—— α·new + (1-α)·old，平滑更新 | **EMA 更稳定**，避免单次反馈剧烈波动。但 Codex_Mimo 的权重范围 [0.0, 1.0] + 低于 0.1 自动清理 机制也很实用。建议：采用 EMA + Codex_Mimo 的自动清理机制 |
| B9 | **MCP 传输模式** | **stdio 模式**（DeepSeek / TRAE / Codex_Mimo 的 database_ops + notification_push）—— 最简，Agent 作为父进程管理生命周期 | **SSE 模式**（Codex_Mimo 的 web_search）—— 适合长连接、流式响应、跨网络 | **Codex_Mimo 是唯一区分不同 MCP 传输模式的文档**——搜索用 SSE（适合流式返回大量结果），DB/推送用 stdio（适合短请求响应）。这个区分很有道理。建议：MVP 全部 stdio（最简），二期搜索服务考虑 SSE |

---

## 【独特点提取】

### 1. GPT — 目标驱动自主 Agent 模式

- **独特点**：将 FeedLens 设计为**目标驱动自主 Agent**（Goal-driven autonomous agent），而非传统的"定时采集→流水线处理"模式。Planner 节点作为中央决策者，自主决定何时搜索、何时推送、何时停止；重大事件立即推送，普通信息累积推送。
- **价值理由**：这是唯一一份突破"定时批处理"范式的方案，更接近真正的 Agent 自主性。虽然 MVP 实现成本高，但作为架构预留（事件驱动钩子）极具价值。面试时可重点讨论"定时 vs 自主"的权衡。
- **来源**：GPT §Planner 设计 / §自主推送机制

### 2. Codex_Mimo — 最完整的 Agent 六层架构映射

- **独特点**：设计了一份**从 Agent 架构到 FeedLens 模块的完整映射表**——感知层（RSS 解析器/搜索标准化/反馈信号）→ 大脑层（DeepSeek/Qwen）→ 工具层（8 个工具 FC/MCP）→ 记忆层（短期/长期/情节/语义四层）→ 规划层（Scheduler + ReAct + Reflection）→ 存储层 → 展示层。这是所有文档中**唯一一份显式对应 XMind 五层 Agent 架构**的设计。
- **价值理由**：面试时可以直接展示"我是如何将 Agent 理论架构映射到具体项目的"，这是从"学过"到"会用"的关键证明。映射表本身就是最好的面试素材。
- **来源**：Codex_Mimo §1 系统架构图 + 架构层映射表

### 3. Codex_Mimo — ReAct 循环 + 反思（Reflection）模块

- **独特点**：在规划层显式设计 **ReAct 循环**（think → act → observe）和 **反思模块**（Reflection）。工作流中 summarize → reflect → (quality pass?) → deliver/revise，反思不通过则修正后重新反思（最多 2 次重试）。
- **价值理由**：这是所有文档中**唯一一个完整落地 ReAct + Reflection 的方案**。其他文档只提了 ReAct 概念但未在工作流中体现，而 Codex_Mimo 把反思做成了 StateGraph 的显式节点和条件边。面试时可展示"反思闭环如何提升简报质量"。
- **来源**：Codex_Mimo §1 规划层 / §2.1 StateGraph（reflect/revise 节点） / §2.3 should_continue 条件边

### 4. Codex_Mimo — 向量 + 编辑距离组合去重 + 同事件分组展示

- **独特点**：
  - 去重综合分 = **0.6 × cosine_sim + 0.4 × title_edit_distance**，双信号联合判定
  - 三级分类：≥0.85 严格去重 / 0.70-0.85 同事件不同角度（两条保留，分组展示）/ <0.70 不同事件
  - **分组展示**：同事件不同角度的条目在简报中归为一组，主条目 + "相关报道"附在下方
- **价值理由**：编辑距离是纯符号计算（`python-Levenshtein`），成本接近零，但对中文标题改写很有效。分组展示是**最实用的去重处理方式**——不是简单保留或删除，而是让用户自己判断。这比 LLM 裁决更省成本，比严格去重更保信息量。
- **来源**：Codex_Mimo §6 去重策略设计 / §6.3 同事件不同角度处理

### 5. Codex_Mimo — 三因子排序 + 重要性乘数 + 分类上限

- **独特点**：
  - 排序公式仅三因子：**w_sim(0.3) × S_sim + w_time(0.25) × S_time + w_pref(0.45) × S_pref**——偏好权重最高
  - **重要性乘数**：importance=5 → Score×1.3，importance=1 → Score×0.7
  - **每分类上限 8 条**，防止单个类别霸榜
- **价值理由**：三因子比四因子更简洁，偏好权重 0.45 体现了"用户行为 > 内容相关性"的产品哲学。重要性乘数让 LLM 分类结果直接放大/缩小排序影响，而分类上限是信息茧房问题的最简工程解。
- **来源**：Codex_Mimo §5 排序算法设计 / §5.3 重排序调整

### 6. Codex_Mimo — 偏好权重自动清理 + 反馈权重差异化

- **独特点**：
  - 反馈权重差异化：positive +0.1 / negative -0.05 / irrelevant -0.15——**不相关比不喜欢惩罚更重**
  - 权重范围 [0.0, 1.0] + **低于 0.1 的关键词自动清理**
- **价值理由**："不相关 > 不喜欢"的差异化设计有产品洞察——不相关意味着领域偏移，应更强烈地纠正；不喜欢可能只是对某篇文章的不满，不一定是领域问题。自动清理避免偏好表无限膨胀。
- **来源**：Codex_Mimo §4.2 长期记忆偏好更新机制

### 7. Codex_Mimo — 四层记忆体系 + 语义记忆种子数据

- **独特点**：
  - 完整的**四层记忆体系**：短期（内存 List，滑动窗口 15 轮）→ 长期（ChromaDB + SQLite）→ 情节（SQLite episodic_memory 表）→ 语义（ChromaDB domain_knowledge collection）
  - 语义记忆 MVP 阶段用**手动维护种子数据**（预置领域事实知识），不做全量 RAG
  - 情节记忆记录包含 dedup_rate、duration_seconds 等工程指标
- **价值理由**：四层记忆是 Agent 架构理论的完整落地。语义记忆的"种子数据+简化检索"策略很务实——MVP 不需要完整的 RAG pipeline，用 SQLite 关键词匹配即可。情节记忆记录 dedup_rate 等指标，让 Agent 可自我诊断（"上次去重率 40%，这次 RSS 源是否重叠太多？"）。
- **来源**：Codex_Mimo §4 记忆系统设计 / §4.4 语义记忆

### 8. Codex_Mimo — 阈值校准方法 + 测试数据构造

- **独特点**：提出明确的**阈值校准流程**：
  1. 手动构造 20 对测试数据（10 对真重复 + 10 对同事件不同报道）
  2. 调整阈值直到准确率 ≥ 90%
  3. 将校准结果记录在情节记忆中
- **价值理由**：这是所有文档中**唯一给出具体去重校准方法的方案**。其他文档只给了阈值数字，没有说怎么验证这些数字是否合理。校准流程让阈值选择从"拍脑袋"变成"有据可查"。
- **来源**：Codex_Mimo §6.4 校准方法

### 9. Codex_Mimo — 采集+搜索+记忆检索三路并行

- **独特点**：StateGraph 中 plan 节点后**三路并行**：fetch_rss / search_web / recall_memory，三路结果汇合后进入 deduplicate。
- **价值理由**：并行化是 LangGraph 的核心优势之一，其他文档大多只提到串行流水线。三路并行可显著减少总执行时间（采集+搜索+记忆检索同时进行）。面试时可展示"如何利用 LangGraph 的并行节点优化 Agent 性能"。
- **来源**：Codex_Mimo §2.1 StateGraph 总览 / §2.3 边逻辑

### 10. Codex_Mimo — 最完整的 State TypedDict + 数据模型定义

- **独特点**：
  - 定义了 **6 个 TypedDict**：FeedItem / BriefingSection / Briefing / FeedbackSignal / MemoryContext / FeedLensState——覆盖输入、处理、输出、反馈、记忆、核心状态全链路
  - FeedLensState 包含 **trigger_type**（scheduled/manual/feedback）、**error_log**、**current_step** 等运行时追踪字段
  - BriefingSection 使用**重要性 emoji 标签**（🔴重要 / 🟡值得关注 / 🔵一般）
  - SQLite 表结构最完整（8 张表），含 user_sources 关联表、briefing_items 展示排序表
- **价值理由**：TypedDict 定义是 LangGraph 工程落地的第一步，Codex_Mimo 给出了可直接使用的骨架。trigger_type 字段为多触发模式（定时/手动/反馈驱动）预留了扩展点。emoji 重要性标签提升简报可读性。
- **来源**：Codex_Mimo §2.2 State TypedDict / §7 数据模型

### 11. Codex_Mimo — MCP SSE + stdio 混合传输 + database_ops 架构图遗漏

- **独特点**：
  - **唯一区分 MCP 传输模式的文档**：web_search 用 SSE（适合流式返回大量搜索结果），notification_push 用 stdio（适合短请求-响应）
  - 架构图列出 3 个 MCP（web_search SSE / database_ops stdio / notification_push stdio），但工具表只列 2 个 MCP（web_search + notification_push），**database_ops 存在遗漏**
- **价值理由**：SSE vs stdio 的区分展示了对 MCP 协议的深入理解——不是一刀切，而是根据服务特征选择传输模式。database_ops 的遗漏恰好是一个**可讨论的架构决策点**：DB 操作到底该不该做 MCP？面试时可展示"我注意到了这个问题，我的选择是……"
- **来源**：Codex_Mimo §1 系统架构图 / §3 工具清单

### 12. Codex_Mimo — jieba 分词 + text2vec-base-chinese 本地 embedding

- **独特点**：
  - 选择 **text2vec-base-chinese** 而非 BGE 做本地 embedding
  - 引入 **jieba 分词** + 自定义停用词表做中文关键词提取和匹配
  - 使用 **python-Levenshtein** 计算编辑距离
- **价值理由**：text2vec-base-chinese 在中文短文本语义匹配上与 BGE 各有千秋，选择它说明有独立调研而非盲从。jieba 分词是中文 NLP 的基础设施，其他文档大多忽略了中文分词问题。
- **来源**：Codex_Mimo §8 技术栈

---

**以下为之前已提取的其他文档独特点（保持不变）：**

### 13. Qwen — Decay(t) 时间衰减预筛

- **独特点**：在排序前用 `Decay(t) = e^(-λ·Δt)` 对条目做**预筛**，低于阈值的直接跳过排序，减少计算量。
- **价值理由**：实用的工程优化——避免对过时内容做无意义的向量计算和排序。实现极简（1 行公式），但能显著降低排序阶段输入量。适合写进简历作为"性能优化"亮点。
- **来源**：Qwen §Stage 3 排序预筛

### 14. Qwen — 模糊区间 LLM 裁决去重

- **独特点**：将向量相似度分为三个区间——0.88 以上严格去重、0.70 以下保留、0.70-0.88 交界区交由 LLM 做语义裁决（same_event / same_topic_different_angle / different_event）。
- **价值理由**：比二元阈值更精细，避免"误杀不同角度"和"漏合并真重复"。LLM 裁决成本可控（仅对模糊区间调用）。这是去重策略中最平衡的方案。
- **来源**：Qwen §Stage 2 去重

### 15. DeepSeek — feedback_bias + Min-Max 归一化

- **独特点**：引入 `feedback_bias`（正向 +0.15 / 负向 -0.1），并在排序前对所有因子做 **Min-Max 归一化**，确保各维度量纲一致。
- **价值理由**：归一化是多因子排序的工程基本功——不做归一化直接加权会导致量纲不同因子权重失衡。feedback_bias 体现"用户行为比 LLM 打分更可靠"的设计哲学。
- **来源**：DeepSeek §Phase 3 排序

### 16. DeepSeek — db_read / db_write 作为 MCP(stdio)

- **独特点**：将数据库读写封装为 MCP(stdio) 服务，Agent 通过 MCP 协议与数据库交互，而非直接 import sqlite3。
- **价值理由**：这是最干净的 FC/MCP 分层示范——MCP 处理有状态、可替换的存储层，FC 处理无状态工具函数。面试时可清晰解释"为什么 DB 操作适合 MCP"。
- **来源**：DeepSeek §工具设计 / §MCP 设计

### 17. Perplexity — normalize_items 显式节点 + duplicate_penalty 第 5 因子

- **独特点**：
  - 将"条目标准化"设计为 StateGraph 中的**显式节点**（normalize_items），在去重前统一格式
  - 排序公式加入 `duplicate_penalty` 作为第 5 因子——同一主题已有多条时惩罚后续条目
- **价值理由**：显式节点比隐式处理更可调试、可观察。duplicate_penalty 从排序层面解决"同类信息刷屏"问题，比纯去重更灵活（不是不收，是降权）。
- **来源**：Perplexity §Phase 2 normalize_items / §Phase 3 排序公式

### 18. GLM — NER 实体重叠 + 向量双验证去重

- **独特点**：去重时同时计算 **NER 实体重叠率** 和 向量相似度，双指标联合判定（same_event / same_topic_different_angle / different_event 三级分类）。
- **价值理由**：纯向量对中文同义不同表述的鲁棒性有限（短文本 embedding 容易漂移），NER 提供了符号层面的锚点。这是去重策略中最严谨的方案，但需额外 LLM 调用做 NER。
- **来源**：GLM §Stage 3 去重 · entity_overlap_verification

### 19. GLM — EMA 偏好更新 + 跨类别配额

- **独特点**：
  - 偏好向量用 **EMA（指数移动平均）** 平滑更新：`pref = α·new + (1-α)·old`
  - 排序时引入**跨类别配额**，避免高偏好类别占满推送位
- **价值理由**：EMA 防止单次反馈造成偏好剧烈波动，比直接覆盖更稳定。跨类别配额解决"信息茧房"——这是产品设计层面的亮点，体现对推荐系统常见问题的认知。
- **来源**：GLM §Stage 4 偏好更新 / §排序配额

### 20. GLM — 双 LLM 供应商 + Searxng 自托管搜索 + Telegram 推送

- **独特点**：GLM 是唯一提出**生产级冗余方案**的文档：
  - DeepSeek 主力 + Qwen fallback 双 LLM 供应商
  - Searxng 自托管元搜索引擎（替代商业 API）
  - Telegram Bot 推送渠道（替代应用内展示）
  - calibrate_dedup.py 校准脚本
- **价值理由**：双供应商提高可用性，Searxng 降低长期成本，Telegram 渠道实现真正的"主动触达"。但这些增加 MVP 复杂度，适合二期引入。
- **来源**：GLM §Stage 0 技术栈 / §Stage 6 推送 / §calibrate_dedup.py

### 21. Kimi — enrich_metadata 显式节点 + 四级反馈 + 动态权重自调

- **独特点**：
  - 设计 **enrich_metadata 节点**——LLM 对每条原始条目提取 category / keywords / importance，标准化元数据后再进入去重/排序
  - 四级反馈粒度：like(+1.0) / valuable(+1.5) / dislike(-0.8) / irrelevant(-1.2)
  - **动态权重自调**：连续 3 次 like → α 自动 +0.05，连续 2 次 dislike → α -0.05
- **价值理由**：enrich_metadata 让后续所有环节（去重、排序、偏好建模）都在结构化数据上工作，而非原始文本——这是数据质量前置的工程思维。四级反馈+动态自调是偏好建模最精细的方案。面试时可深入讨论"反馈设计如何影响推荐效果"。
- **来源**：Kimi §Phase 1 enrich_metadata / §Phase 3 反馈设计 / §动态权重

### 22. Codex_DeepSeek — item_relations 关系表 + execution_logs 执行日志表

- **独特点**：
  - 设计 **item_relations 表**记录条目间关系（duplicate_of / related_to / merged_into），保留去重推理链
  - 设计 **execution_logs 表**记录每次 Agent 执行的完整日志（session/turn/event 三级），可回溯调试
  - 最详细的 State/dataclass 定义（FeedItem / DedupResult / RankedItem / BriefingOutput）
- **价值理由**：item_relations 让去重结果可解释——"为什么这两条合并了"有据可查。execution_logs 是 Harness Engineering 层面的落地，面试时可直接展示"session→turn→event"三级日志模型的理解。
- **来源**：Codex_DeepSeek §数据模型 / §item_relations / §execution_logs

### 23. TRAE — 用户认证 + SQLAlchemy ORM + ChromaDB MCP + 动态权重调整

- **独特点**：
  - 唯一包含**用户认证模块**（JWT）的方案
  - ChromaDB 和 vector_store 均封装为 MCP 服务
  - 排序权重支持**动态调整**（根据用户行为自动调优 w₁-w₄）
- **价值理由**：用户认证为多用户扩展铺路，但 MVP 不必要。ChromaDB MCP 体现了"有状态存储服务适合 MCP"的清晰分层。动态权重调整是偏好系统的进阶方向。
- **来源**：TRAE §用户认证 / §MCP 设计 / §排序权重

---

## 【综合建议：MVP 最优方案融合】

基于以上 9 份文档分析，推荐的 MVP 融合方案：

| 模块 | 推荐来源 | 理由 |
|------|---------|------|
| 工作流引擎 | 全部共识 | LangGraph StateGraph |
| LLM | 全部共识 | DeepSeek API + Qwen fallback（Codex_Mimo / GLM 共识） |
| Embedding | GLM / Kimi | bge-small-zh 本地推理，零成本，中文效果好（text2vec-base-chinese 为备选） |
| 向量存储 | 全部共识 | ChromaDB |
| 结构化存储 | 全部共识 + Perplexity | SQLite WAL 模式 |
| 架构映射 | Codex_Mimo | Agent 六层架构映射表，面试核心素材 |
| ReAct + Reflection | Codex_Mimo | reflect → revise 闭环，最多 2 次重试 |
| 去重策略 | Codex_Mimo + Qwen | 规则预筛 → 向量+编辑距离组合 → 模糊区间 LLM 裁决（三级分类）→ 同事件分组展示 |
| 去重校准 | Codex_Mimo | 20 对测试数据 + ≥90% 准确率验证 |
| 排序公式 | DeepSeek + Codex_Mimo | 三/四因子 + importance 乘数 + duplicate_penalty + Min-Max 归一化 + 分类上限 |
| 偏好更新 | GLM + Codex_Mimo | EMA 平滑更新 + 自动清理低权重关键词 |
| 反馈设计 | Codex_Mimo | positive / negative / irrelevant 三级（比二元精细，比四级简洁） |
| 元数据标准化 | Kimi | enrich_metadata 节点，LLM 提取 category/keywords/importance |
| 条目标准化 | Perplexity | normalize_items 显式节点 |
| 记忆系统 | Codex_Mimo | 四层记忆完整落地，语义记忆种子数据+简化检索 |
| FC/MCP 分层 | Codex_Mimo + DeepSeek | MVP 全部用 FC（最简），接口预留 MCP 迁移；MCP 传输按服务特征区分 SSE/stdio |
| 触发模式 | Codex_Mimo | trigger_type: scheduled / manual / feedback，预留事件驱动 |
| 并行采集 | Codex_Mimo | fetch_rss / search_web / recall_memory 三路并行 |
| 可追溯性 | Codex_DeepSeek + Codex_Mimo | item_relations 表 + episodic_memory 表（含 dedup_rate 等工程指标） |
| 推送模式 | 全部共识 + GPT | MVP 定时推送，预留事件驱动钩子 |
| 前端 | 全部共识 | Streamlit |
| 部署 | DeepSeek（二期） | MVP 本地跑通，二期补 Docker Compose |
| 时间衰减预筛 | Qwen | Decay(t) 预筛，减少无效排序 |
| 跨类别配额 | GLM + Codex_Mimo | 每分类上限 8 条，避免信息茧房 |
| 中文分词 | Codex_Mimo | jieba 分词 + 停用词表，其他文档忽略的关键细节 |

---

*分析完成。9 份文档全部纳入分析。*
