# FeedLens MVP 设计文档 — 综合分析报告

> **整合基准**：9 份原始 MVP 设计文档（事实基准） × 5 份 AI 分析报告（DeepSeek / GLM / Kimi / TRAE / WorkBuddy）
> **整合原则**：以原始文档为唯一事实基准，交叉核对5份分析报告中的每一条声明，取其精华、去其错误、补其遗漏
> **准确性保障**：所有技术参数均经原始文档逐字核对，已修正原分析报告中的全部已识别错误
> **整合日期**：2026-06-17

---

## 一、分析目录

| # | 文档代号 | 生成模型 | 阶段数 | 工具数 | FC/MCP 分配 |
|---|---------|---------|--------|--------|------------|
| 1 | GPT | ChatGPT | 5 (Phase 1-5) | 5 | Search MCP(SSE) + Push/RSS/Summary/Rank FC |
| 2 | DeepSeek | DeepSeek | 4 (Phase 1-4) | 7 | 5 FC + 2 MCP（search SSE + push stdio）+ db_read/db_write MCP(stdio) = 3 MCP |
| 3 | GLM | 智谱 GLM | 7 (Stage 0-6) | 10 | 8 FC + 2 MCP（web_search SSE + push_notifier stdio） |
| 4 | Kimi | Kimi | 5 (Phase 1-5) | 10 | 8 FC + 2 MCP（fetch_search SSE:3001 + deliver_brief stdio） |
| 5 | Perplexity | Perplexity | 6 (Phase 1-6) | 11 | 6 FC + 5 MCP（web_search SSE + save_items SSE + load_user_profile stdio + save_feedback SSE + send_notification SSE） |
| 6 | Qwen | 通义千问 | 5 (Phase 1-4) | 5 | 3 FC + 2 MCP（search_web SSE + send_notification SSE + save_preference stdio） |
| 7 | TRAE | TRAE | 10 (Phase 1-10) | 7 | 4 FC + 3 MCP（search SSE + notification stdio + vector_store stdio） |
| 8 | Codex_DeepSeek | Codex+DeepSeek | 7 (P0-P6) | 12 | 10 FC + 2 MCP（web_search SSE + push_notification SSE） |
| 9 | Codex_Mimo | Codex+MiMo | 7 (P0-P6) | 8 | 6 FC + 2 MCP（web_search + notification_push） |

> **注**：Codex_Mimo 存在内部不一致——架构图列出 3 个 MCP（web_search SSE / database_ops stdio / notification_push stdio），但工具表仅列出 2 个 MCP（web_search + notification_push），database_ops 被遗漏。且架构图标注 web_search 为 SSE，但 MCP Server 接口定义和实现任务中均标注为 stdio 模式。

> **注**：DeepSeek 文档实际有 3 个 MCP Server（search_web SSE + push_briefing stdio + db_read/db_write stdio），部分分析报告误计为 2 个。

---

## 二、项目定位

FeedLens 是一个基于 **LangGraph StateGraph** 编排的智能信息简报 Agent。它通过多源信息采集（RSS + 搜索引擎）、向量去重、多因子个性化排序、LLM 摘要生成、结构化简报输出，并借助反思机制保障质量、通过用户反馈持续学习偏好，为用户提供自动化的信息消费闭环。

**核心特征**：采集 → 去重 → 排序 → 摘要 → 反思 → 推送 → 反馈学习

---

## 三、共识点分析

经交叉核对，以下 15 个共识点在 9 份文档中一致出现：

### 3.1 架构与框架

**共识 1：LangGraph StateGraph 作为核心编排框架**
全部 9 份文档均采用 LangGraph 的 StateGraph 构建工作流，以 TypedDict 定义共享状态，通过节点（Node）+ 边（Edge）实现有状态、可分支的 Agent 流程。
> 来源：全部文档 · Agent 工作流设计 / LangGraph StateGraph 章节

**共识 2：四/五层分层架构**
全部文档均将系统划分为感知层、大脑层（LLM）、工具层、记忆层、规划层（或类似划分），体现 Agent 架构的标准化设计思维。其中 Codex_Mimo 提供了最完整的六层架构映射表。
> 来源：全部文档 · 系统架构图章节

**共识 3：ReAct + Reflection 规划模式**
全部文档均在规划层引入 ReAct（思考→行动→观察循环）和 Reflection（反思审查）机制，且均设置反思失败时的重试/修正逻辑。
> 来源：全部文档 · 规划层 / Agent 工作流设计章节

### 3.2 工具与存储

**共识 4：混合工具调用策略（FC + MCP）**
全部文档均区分了 Function Calling 工具和 MCP 工具——将"逻辑简单、参数明确、紧耦合"的工具归为 FC，将"需独立部署、跨进程复用、涉及外部系统"的工具归为 MCP。
> 来源：全部文档 · 工具清单章节

**共识 5：ChromaDB + SQLite 双存储**
全部文档均使用 ChromaDB 作为向量数据库（存储条目 embedding、用户偏好向量、领域知识），SQLite 作为关系数据库（存储用户、源、条目、反馈、执行日志等结构化数据）。Perplexity 额外建议启用 SQLite WAL 模式提升并发读写。
> 来源：全部文档 · 技术栈选择 / 数据模型章节

**共识 6：feedparser 作为 RSS 解析库**
全部 9 份文档均使用 feedparser 解析 RSS/Atom 格式。
> 来源：全部文档 · 技术栈 / 工具清单章节
> **修正说明**：部分分析报告将 Codex_Mimo 归入"httpx + 自定义解析"阵营，经核实 Codex_Mimo 原始文档明确使用 feedparser。

**共识 7：MCP Search 部署统一使用 SSE 模式**
全部 9 份文档的搜索服务 MCP Server 均采用 SSE（Server-Sent Events）部署模式。这是统一共识，不存在阵营分歧。
> 来源：全部文档 · 工具清单 / MCP Server 章节
> **修正说明**：部分分析报告声称 DeepSeek 文档 search_web 使用 stdio 模式，经核实 DeepSeek 原始文档第 3.2.2 节明确标注"本地 HTTP SSE 服务，监听 localhost:8100"。所有 9 份文档的搜索 MCP 均为 SSE。

### 3.3 记忆与学习

**共识 8：四类记忆系统**
全部文档均设计了"短期记忆（State/滑动窗口）+ 长期记忆（ChromaDB 用户偏好向量）+ 情节记忆（SQLite 执行日志）+ 语义记忆（ChromaDB 领域知识）"的四层记忆架构。
> 来源：全部文档 · 记忆系统设计章节

**共识 9：用户反馈驱动的偏好学习**
全部文档均支持用户点赞/踩反馈，并基于反馈更新长期记忆中的偏好向量，影响后续排序。
> 来源：全部文档 · 反馈闭环 / 偏好学习章节

**共识 10：向量相似度去重 + "同事件不同角度"区分**
全部文档均基于 embedding 余弦相似度进行去重，并专门设计了区分"真正重复"（高相似度）和"同一事件不同角度"（中等相似度）的机制。
> 来源：全部文档 · 去重策略设计章节

### 3.4 算法与流程

**共识 11：多因子加权排序公式**
全部文档均采用线性加权的打分公式：`final_score = w₁·similarity + w₂·recency + w₃·preference + w₄·authority`（部分文档增加第 5 因子或使用三因子变体）。
> 来源：全部文档 · 排序算法设计章节

**共识 12：核心数据处理流水线**
全部文档均包含"采集 → 去重 → 排序 → 摘要 → 简报生成 → 反思 → 推送/反馈"的核心闭环。
> 来源：全部文档 · 工作流设计 / 节点定义章节

**共识 13：反思（Reflection）机制**
全部文档都在工作流中设计了反思节点，对简报质量进行 LLM 自检，不合格则触发重新生成（retry 机制）。
> 来源：全部文档 · 节点与边 / 反思章节

### 3.5 技术选型与交付

**共识 14：DeepSeek / 通义千问作为 LLM 后端**
8/9 份文档明确选用 DeepSeek 或通义千问作为 LLM 后端，理由均为"国内可用、无需科学上网、性价比高、支持 Function Calling"。GPT 文档未明确指定 LLM 供应商，但提及 LangGraph 框架。GLM 和 Codex_Mimo 额外提出双供应商 fallback 策略。
> 来源：全部文档 · 技术栈选择章节
> **修正说明**：部分分析报告声称"全部 9 份文档均选用 DeepSeek 或通义千问"，但 GPT 文档未明确指定 LLM 供应商。

**共识 15：Streamlit 前端 + APScheduler 定时调度 + 阶段性交付**
全部 9 份文档均采用 Streamlit 作为 MVP 前端、APScheduler 实现定时调度、并将 MVP 拆分为 5-10 个阶段交付。
> 来源：全部文档 · 技术栈选择 / MVP 范围章节
> **修正说明**：部分分析报告声称"GPT 文档不使用 APScheduler"，经核实 GPT 文档第十节明确列出 APScheduler。GPT 额外增加了自主推送机制（Planner 决定推送时机），但并未替代 APScheduler。

---

## 四、冲突点对比

### 4.1 产品 / 业务逻辑冲突

| # | 冲突事项 | 阵营 A | 阵营 B | 核心分歧点 |
|---|---------|--------|--------|-----------|
| P1 | **简报生成驱动模式** | **流程驱动**（8 份）：按预设工作流每日定时采集并生成日报 — Codex_DeepSeek / Codex_Mimo / DeepSeek / GLM / Kimi / Perplexity / Qwen / TRAE | **Goal 驱动**（1 份）：Agent 围绕用户长期目标自主决定何时搜索、何时推送 — GPT | Agent 的自主性边界：是"按流程执行"还是"自主决策是否执行" |
| P2 | **推送机制** | **定时/手动推送**（8 份）：每日固定时间推送简报，或通过 Streamlit 展示 — 同上 8 份 | **自主推送**（1 份）：Planner 判断"重大事件立即推送，普通事件积累成日报" — GPT | 推送策略是"基于重要性实时触发"还是"固定周期批量推送" |
| P3 | **用户配置粒度** | **多维度配置**（8 份）：用户需配置多个关注领域、关键词、RSS 源列表 — 同上 8 份 | **仅需 Goal**（1 份）：用户只需输入一个长期目标文本 — GPT | 用户交互复杂度：极简 goal vs 结构化表单 |
| P4 | **去重结果处理** | **折叠分组**：同事件不同角度归入同一 cluster，简报中展示为"相关报道"折叠组 — GLM / Codex_Mimo | **计数标注**：保留一篇代表，简报中标注"还有 N 篇类似报道" — DeepSeek | 简报中如何处理"同事件多来源" |
| P5 | **搜索采集角色** | **搜索为并列通道**：搜索与 RSS 并行采集 — Codex_Mimo / Kimi / TRAE | **搜索为补充**：搜索仅在 RSS 条目不足时触发 — 其余文档 | 搜索引擎在采集体系中的角色 |
| P6 | **简报输出风格** | **结构化 JSON 输出**：LLM 输出 JSON 再渲染为 Markdown — GLM / Kimi | **直接 Markdown 生成**：LLM 直接输出 Markdown 文本 — 其余文档 | 简报生成管道的结构化程度 |
| P7 | **用户反馈选项** | **多元反馈**（3-4 选项）：like / dislike / irrelevant / valuable — Kimi（四级）/ Codex_Mimo（三级）/ Qwen | **二元反馈**（2 选项）：仅 like / dislike — Codex_DeepSeek / DeepSeek / Perplexity | 反馈信号丰富度 |

### 4.2 技术架构冲突

| # | 冲突事项 | 阵营 A | 阵营 B | 核心分歧点 |
|---|---------|--------|--------|-----------|
| T1 | **MCP Push 部署模式** | **stdio 模式**（5 份）：DeepSeek / GLM / Kimi / TRAE / Codex_Mimo | **SSE 模式**（3 份）：Codex_DeepSeek / Perplexity / Qwen | 推送服务的 MCP 传输协议选择 |
| | | > **修正说明**：部分分析报告将 Codex_DeepSeek 归入 stdio 阵营，经核实 Codex_DeepSeek 原始文档第 3.6 节明确标注"MCP 部署: SSE 协议"。 | | |
| T2 | **向量去重阈值** | **高阈值（≥0.90）**：DeepSeek（0.88 初始 / 0.95 严格）/ GLM（0.90）/ Kimi（0.90）/ TRAE（0.90 严格） | **中阈值（0.85-0.88）**：Codex_DeepSeek（0.85）/ Codex_Mimo（0.85）/ Perplexity（0.88）/ Qwen（0.88） | 去重敏感度：高阈值保留更多 vs 中阈值删除更多 |
| T3 | **Embedding 模型选择** | **本地 sentence-transformers**：Codex_DeepSeek（paraphrase-multilingual-MiniLM-L12-v2）/ GLM（bge-small-zh）/ TRAE（sentence-transformers）/ Codex_Mimo（text2vec-base-chinese）/ Kimi（BAAI/bge-small-zh-v1.5） | **API 调用**：DeepSeek（DeepSeek Embedding text-embedding-v3）/ Qwen（BGE-M3 本地或阿里云 text-embedding-v3 双轨） | Embedding 生成方式：本地免费 vs API 便捷 |
| T4 | **MCP Server 数量** | **3+ 个 MCP**：DeepSeek（3：search SSE + push stdio + db stdio）/ Perplexity（5）/ TRAE（3：search SSE + notification stdio + vector_store stdio） | **2 个 MCP**：Codex_DeepSeek（2：web_search SSE + push_notification SSE）/ Codex_Mimo（2）/ GLM（2）/ Kimi（2）/ Qwen（2） | 数据库/向量操作是否封装为 MCP |
| T5 | **排序权重配置** | **偏好权重较高（w_pref ≥ 0.30）**：Codex_DeepSeek（初始 w3=0.10，有反馈后 w3=0.40）/ Codex_Mimo（w_pref=0.45）/ GLM（w3=0.30）/ Kimi（γ=0.30） | **相似度/相关性权重较高（w_sim ≥ 0.35）**：GPT（relevance=0.40）/ DeepSeek（α=0.40）/ Perplexity（w1=0.40）/ TRAE（w_sim=0.35）/ Qwen（w1=0.40） | 排序核心信号：用户偏好 vs 内容相关性 |
| | | > **修正说明**：部分分析报告声称 TRAE 的 w_sim=0.40，经核实 TRAE 原始文档 5.2 节 w_sim=0.35。 | | |
| T6 | **去重技术路线** | **纯向量去重**：Codex_DeepSeek / DeepSeek / GPT — 仅依赖 embedding 相似度 + 阈值 | **多信号组合去重**：Codex_Mimo（向量 0.6 + 编辑距离 0.4）/ GLM（NER 实体 + 向量双验证）/ Qwen（向量 + LLM 裁决）/ Perplexity（规则 + 向量 + LLM 三阶段） | 去重精度与成本的权衡 |
| T7 | **短期记忆窗口大小** | **10 轮**：Codex_DeepSeek | **15 轮**：Codex_Mimo / DeepSeek | **10-20 轮滑动窗口**：Kimi | 上下文窗口的容量设定差异 |
| T8 | **时间衰减函数** | **指数衰减 exp(-λ·Δt)**：GPT（λ=0.05）/ Codex_Mimo / DeepSeek / Kimi / Qwen | **半衰期公式 exp(-Δt/τ)**：GLM（τ=24h）/ TRAE（HALF_LIFE=24h） | 数学表达差异（实质等价，参数符号不同） |
| T9 | **反思重试次数** | **2-3 次**：GLM（max 2）/ Codex_Mimo（max 2）/ Kimi（max_retry=3）/ Codex_DeepSeek（不合格返回重生成） | **不明确/1 次**：GPT（工作流图中 Reflection→Continue?→Planner 循环暗示单次反思决策） | 反思修正的容错程度 |
| | | > **修正说明**：部分分析报告将"reflect 最多 3 次重试"标注来源为 GPT 文档，经核实此内容来自 Kimi 文档（retry_count < 3, max_retry=3）。 | | |
| T10 | **向量库交互方式** | **本地嵌入式直接调用（FC）**：Codex_DeepSeek / Codex_Mimo / DeepSeek（db_read/db_write 除外）/ GLM / Kimi / Perplexity | **封装为 MCP Server 解耦**：TRAE（vector_store MCP stdio）/ DeepSeek（db_read/db_write MCP stdio）/ Qwen（save_preference MCP stdio） | 架构耦合度：FC 直调更简 vs MCP 解耦更扩展 |
| T11 | **部署方案** | **本地开发运行**（7 份）：python 直接启动 | **Docker Compose**（2 份）：GLM / Perplexity / DeepSeek（docker-compose 打包） | 是否容器化部署 |

---

## 五、独特点提取

以下独特点按来源文档分组，每条均经原始文档核实，已过滤过度推断和来源标注错误。

### 5.1 GPT 文档独特点

| # | 独特点 | 价值 |
|---|--------|------|
| 1 | **Goal 驱动的自主 Agent 设计**：Planner 自主决策"是否搜索、是否继续、是否立即推送"，而非执行固定日报流程。输出 JSON action（Search / SearchMore / GenerateBrief / PushNow / Stop） | 体现 Agent 自主规划能力，是"Agent 决策"而非"流水线"的差异化亮点 |
| 2 | **自主推送机制**：重大事件立即推送，普通事件积累成日报。突破"每日定时日报"的静态逻辑 | 从"自动化工具"到"自主 Agent"的关键设计跃迁 |
| 3 | **LLM 评估新闻重要性（1-5 分）**：引入 LLM 对新闻重要性进行 1-5 分评估，作为排序公式的独立因子 | 将 LLM 判断力引入排序信号 |
| 4 | **低代码 Prompt 模板设计**：Planner 的 Prompt 直接输出 JSON 格式的 action，极简设计 | 便于快速迭代和调试 |

### 5.2 DeepSeek 文档独特点

| # | 独特点 | 价值 |
|---|--------|------|
| 5 | **db_read / db_write 作为 MCP(stdio)**：将数据库读写封装为 MCP 服务，Agent 通过 MCP 协议与数据库交互 | 最干净的 FC/MCP 分层示范——MCP 处理有状态存储层，FC 处理无状态工具函数 |
| 6 | **feedback_bias + Min-Max 归一化**：引入 feedback_bias（正向 +0.15 / 负向 -0.1），排序前对所有因子做 Min-Max 归一化 | 归一化是多因子排序的工程基本功，feedback_bias 体现"用户行为比 LLM 打分更可靠" |
| 7 | **意图理解节点（understand_intent）**：将任务类型识别（daily_briefing / manual_search / feedback_update）显式化为独立节点 | 支持多种触发模式 |
| 8 | **反馈子图独立触发（feedback_workflow）**：将反馈处理从主流程解耦为独立子图 | 支持异步处理用户反馈 |
| 9 | **反思节点矛盾检查**：反思节点检查简报中是否存在自相矛盾的信息 | 将质量检查细化到逻辑一致性层面 |
| 10 | **人工标注样本计算 F1 评估去重效果**：在 dev 集上人工标注 100 对样本计算 F1 最优阈值 | 数据驱动的阈值选择（注：原文为"人工标注"，非"LLM 评估"） |
| 11 | **用户偏好向量的正负分离**：分别维护用户点赞条目向量 v_like 和点踩条目向量 v_dislike | 偏好表达更精细 |
| 12 | **Docker Compose 一键部署**：打包 Agent + Streamlit + ChromaDB + MCP Server | 大幅降低项目演示门槛 |

### 5.3 GLM 文档独特点

| # | 独特点 | 价值 |
|---|--------|------|
| 13 | **NER 实体重叠 + 向量双验证去重**：去重时同时计算 NER 实体重叠率和向量相似度，双指标联合判定（same_event / same_topic_different_angle / different_event 三级分类） | 纯向量对中文短文本鲁棒性有限，NER 提供符号层面锚点。原文提供 LLM 和 spaCy 两种 NER 选项 |
| 14 | **带可复现校准流程的去重阈值**：设计了"人工标注 200 对样本 → 扫描阈值区间 → 绘制 P/R/F1 曲线 → 选最优阈值"的校准脚本 `scripts/calibrate_dedup.py` | 体现数据驱动的工程思维 |
| 15 | **MCP 双 Transport 对比实现**：刻意让 web_search 使用 SSE、push_notifier 使用 stdio，展示对 MCP 协议两种部署形态的理解 | 体现对 MCP 协议的深度掌握 |
| 16 | **EMA 偏好更新 + 跨类别配额**：偏好向量用 EMA（指数移动平均）平滑更新 `pref = α·new + (1-α)·old`；排序后按用户话题数均分配额（如 5 话题 × 4 条 = 20） | EMA 防止单次反馈剧烈波动；跨类别配额解决"信息茧房" |
| 17 | **情节记忆向量化检索**：不仅将情节记忆存入 SQLite，还将其摘要向量化存入 ChromaDB，支持"相似执行经验检索" | 让 Agent 从历史成功/失败经验中学习 |
| 18 | **双 LLM 供应商冗余**：DeepSeek 主力 + Qwen fallback 双供应商 | 生产级可用性保障 |
| 19 | **条件边的空结果回退**：若去重后剩余 < 3 条，自动回退到采集节点扩大时间窗/来源 | LangGraph 条件边的容错设计（注：原文为条件边路由逻辑，非"LLM 进行空结果回退"） |
| 20 | **执行仪表盘**：Streamlit 页面展示执行成功率、耗时、去重率、反馈率等历史指标 | 可视化 Agent 运行效果 |
| 21 | **主动追问式偏好校准**：Agent 发现偏好信号冲突时主动问用户澄清 | 从"被动接收反馈"升级为"主动澄清偏好" |

### 5.4 Kimi 文档独特点

| # | 独特点 | 价值 |
|---|--------|------|
| 22 | **enrich_metadata 显式节点**：LLM 对每条原始条目提取 category / keywords / importance，标准化元数据后再进入去重/排序 | 数据质量前置的工程思维 |
| 23 | **简报质量结构化评分**：State 中定义 brief_quality 字段（含 completeness / relevance / coherence / score 四维度），质量分 < 0.7 触发重试（max_retry=3） | 质量评估可量化、可追踪 |
| 24 | **四级反馈 + 动态权重自调**：四级反馈（like +1.0 / valuable +1.5 / dislike -0.8 / irrelevant -1.2）；连续 3 次 like → α 自动 +0.05 上限 0.5，连续 2 次 irrelevant → α -0.05 下限 0.1 | 偏好建模最精细的方案 |
| 25 | **简报多风格输出**：支持用户选择 concise / detailed / bullet 等简报风格 | 提升个性化体验 |
| 26 | **用户满意度评分（1-5 星）**：briefs 表有 user_rating 字段，用户对简报进行 1-5 星评分 | 用户显式评分作为情节记忆质量指标（注：为用户评分，非 LLM 评分） |
| 27 | **工具调用路由层**：增加智能路由层，根据工具特性自动选择 FC 或 MCP | 而非硬编码 |
| 28 | **渐进式推送渠道加载**：stdio 模式的 MCP Server 支持按需启动子进程，用户可按需启用邮件/微信/钉钉 | 灵活的推送渠道管理 |

### 5.5 Perplexity 文档独特点

| # | 独特点 | 价值 |
|---|--------|------|
| 29 | **normalize_items 显式节点**：将"条目标准化"设计为 StateGraph 中的显式节点，在去重前统一格式 | 比隐式处理更可调试、可观察 |
| 30 | **duplicate_penalty 第 5 因子**：排序公式加入 `duplicate_penalty`（w5=0.30），同一主题已有多条时惩罚后续条目 | 从排序层面解决"同类信息刷屏"问题 |
| 31 | **三阶段去重 + LLM 事件判别**：规则预过滤 → 向量相似度（0.88）→ LLM 事件判别（0.78-0.88 模糊区间），区分 same_event / same_topic_different_angle / different_event | 去重精度最高的方案 |
| 32 | **SQLite WAL 模式 + 事务包裹**：开启 WAL 提升并发读写，事务包裹确保简报生成流程的原子性 | 生产级数据库实践 |
| 33 | **structlog 结构化日志**：比标准 logging 更易解析和监控 | 适合结构化分析和日志聚合 |
| 34 | **来源可信度评分（authority_score）**：为每个来源配置可信度权重，抑制低质来源 | 排序信号更丰富 |
| 35 | **情节记忆相似失败模式检索**：不仅按时间查，还按"相似失败模式"查询，如"上次搜索某话题时超时了，这次要加 fallback" | Agent 避免重复踩坑 |
| 36 | **反思节点修改初稿**：Reflection 从"通过/不通过"升级为"具体修改"，输出可追踪的修正记录 | 更精细的质量修正 |
| 37 | **run_logs 执行日志表**：记录每次 Agent 执行的完整日志 | 为执行仪表盘提供数据 |

### 5.6 Qwen 文档独特点

| # | 独特点 | 价值 |
|---|--------|------|
| 38 | **Decay(t) 时间衰减预筛**：在排序前用 `Decay(t) = e^(-λ·Δt)` 对条目做预筛，低于阈值的直接跳过排序 | 避免对过时内容做无意义的向量计算和排序，性能优化 |
| 39 | **模糊区间 LLM 裁决去重**：向量相似度分为三区间——0.88 以上严格去重、0.70 以下保留、0.70-0.88 交由 LLM 做语义裁决 | 比二元阈值更精细，LLM 裁决成本可控 |
| 40 | **BGE-M3 多语言 Embedding 模型**：支持 100+ 语言、多粒度、密集+稀疏向量 | 为后续多语言扩展预留空间 |
| 41 | **任务级错误隔离**：APScheduler 捕获异常后继续下一次定时任务，单次失败不阻塞后续调度 | 生产级稳定性设计 |
| 42 | **短期记忆超窗压缩 + Redis 缓存**：对超出滑动窗口的早期对话进行"总结压缩"而非直接丢弃 | 更好保留长会话上下文连贯性 |

### 5.7 TRAE 文档独特点

| # | 独特点 | 价值 |
|---|--------|------|
| 43 | **权重动态调整（在线学习）**：根据用户连续反馈自动微调排序权重（relevant → w_pref +0.02, w_sim +0.01），并做权重归一化 | 比静态权重更体现"持续学习" |
| 44 | **三层 MCP 部署架构**：search_engine SSE + notification_service stdio + vector_store stdio，按服务特征选择传输模式 | 分层设计更精细 |
| 45 | **SQLAlchemy ORM**：唯一使用 ORM 的文档，面向对象操作 | 面向多表关联和迁移场景 |
| 46 | **用户认证模块（JWT）**：唯一包含用户认证的方案 | 为多用户扩展铺路 |

### 5.8 Codex_DeepSeek 文档独特点

| # | 独特点 | 价值 |
|---|--------|------|
| 47 | **item_relations 关系表**：记录条目间关系（duplicate_of / related_to / merged_into），保留去重推理链 | 去重结果可解释——"为什么这两条合并了"有据可查 |
| 48 | **execution_logs 执行日志表**：记录每次 Agent 执行的完整日志（session/turn/event 三级），可回溯调试 | Harness Engineering 层面的落地 |
| 49 | **来源多样性加分（source_diversity_bonus = +0.05）**：同一事件多角度报道合并后获得额外加分 | 鼓励多源验证 |
| 50 | **30 天数据清理策略**：定期清理过期数据，避免 SQLite/ChromaDB 无限增长 | 数据生命周期管理 |
| 51 | **Embedding 模型下载进度条与备选方案**：首次自动下载 sentence-transformers 模型时显示进度条，备选 LLM API 做 embedding | 工程细节考虑 |
| 52 | **超窗对话 LLM 摘要压缩**：超窗的早期对话通过 LLM 生成摘要压缩后存入长期记忆，而非简单丢弃 | 保留长会话上下文 |
| 53 | **反思审查三维度**：将反思细化为完整性、去重遗漏、可追溯性三个具体维度 | 比二元"通过/不通过"更精细 |
| 54 | **最详细的 dataclass 定义**：FeedItem / DedupedItem / RankedItem / BriefingOutput 等完整数据类 | 工程落地骨架 |

### 5.9 Codex_Mimo 文档独特点

| # | 独特点 | 价值 |
|---|--------|------|
| 55 | **Agent 六层架构映射表**：从 Agent 理论架构到 FeedLens 模块的完整映射（感知→大脑→工具→记忆→规划→展示） | 唯一显式对应 XMind 五层 Agent 架构的设计 |
| 56 | **向量 + 编辑距离组合去重**：去重综合分 = 0.6 × cosine_sim + 0.4 × title_edit_distance，双信号联合判定 | 编辑距离成本接近零，对中文标题改写有效 |
| 57 | **同事件不同角度分组展示**：同事件不同角度的条目在简报中归为一组，主条目 + "相关报道"附在下方 | 最实用的去重处理方式——不是简单保留或删除，而是让用户自己判断 |
| 58 | **三因子排序 + 重要性乘数 + 分类上限**：w_sim(0.3) + w_time(0.25) + w_pref(0.45)，偏好权重最高；importance=5 → Score×1.3；每分类上限 8 条 | 偏好权重 0.45 体现"用户行为 > 内容相关性"的产品哲学 |
| 59 | **偏好权重自动清理 + 反馈权重差异化**：positive +0.1 / negative -0.05 / irrelevant -0.15（不相关比不喜欢惩罚更重）；权重范围 [0,1]，低于 0.1 自动清理 | "不相关 > 不喜欢"的差异化设计有产品洞察——不相关意味着领域偏移 |
| 60 | **三路并行采集**：StateGraph 中 plan 节点后三路并行——fetch_rss / search_web / recall_memory | 显著减少总执行时间 |
| 61 | **ReAct + Reflection 完整落地**：工作流中 summarize → reflect → (quality pass?) → deliver/revise，反思不通过则修正后重新反思（最多 2 次重试） | 唯一在 StateGraph 中把反思做成显式节点和条件边的方案 |
| 62 | **6 个 TypedDict 完整定义**：FeedItem / BriefingSection / Briefing / FeedbackSignal / MemoryContext / FeedLensState，含 trigger_type / error_log / current_step 等运行时追踪字段 | 可直接使用的 LangGraph 工程骨架 |
| 63 | **语义记忆种子数据**：MVP 阶段用手动维护种子数据（预置领域事实知识），不做全量 RAG | 务实的 MVP 策略 |
| 64 | **jieba 分词 + 自定义停用词表**：中文关键词提取和匹配 | 其他文档大多忽略了中文分词问题 |
| 65 | **阈值校准方法 + 测试数据构造**：手动构造 20 对测试数据（10 对真重复 + 10 对同事件不同报道），调整阈值至准确率 ≥ 90% | 唯一给出具体去重校准方法的方案 |

---

## 六、设计决策图谱

| 维度 | 主流方案（7+ 文档） | 少数方案（1-2 文档） |
|------|-------------------|-------------------|
| 驱动模式 | 流程驱动（定时执行） | Goal 驱动（自主决策）— GPT |
| 推送策略 | 定时推送 / Streamlit 展示 | 基于重要性自主推送 — GPT |
| 用户配置 | 多维度结构化配置 | 单 Goal 文本配置 — GPT |
| MCP Search | **全部 SSE**（无分歧） | — |
| MCP Push | stdio 模式（5 份） | SSE 模式（3 份：Codex_DeepSeek / Perplexity / Qwen） |
| Embedding | 本地 sentence-transformers / BGE / text2vec | API 调用 — DeepSeek / Qwen 双轨 |
| 去重阶段 | 两阶段（向量 + 规则/NER/编辑距离） | 三阶段（+ LLM 精排）— Perplexity；两阶段 + LLM — Qwen |
| 排序核心 | 相似度/相关性优先（w_sim ≥ 0.35） | 偏好优先（w_pref ≥ 0.30）— Codex_DeepSeek(反馈后) / Codex_Mimo / GLM / Kimi |
| 去重阈值 | 0.85-0.90 | 0.95 — DeepSeek |
| MCP 数量 | 2 个（search + push） | 3-5 个（+ db + vector）— DeepSeek / Perplexity / TRAE |
| 短期记忆窗口 | 15 轮 | 10 轮 — Codex_DeepSeek；10-20 轮 — Kimi |
| 反思重试 | 2-3 次 | 不明确/1 次 — GPT |
| RSS 解析 | **全部 feedparser**（无分歧） | — |
| 部署 | 本地运行 | Docker Compose — GLM / Perplexity / DeepSeek |
| ORM | 原生 SQL | SQLAlchemy — TRAE |

---

## 七、MVP 最优方案融合建议

基于以上分析，推荐的 MVP 融合方案（兼顾可行性、工程质量和简历亮点）：

| 模块 | 推荐方案 | 推荐来源 | 理由 |
|------|---------|---------|------|
| 工作流引擎 | LangGraph StateGraph | 全部共识 | 9 份文档一致选择 |
| LLM | DeepSeek API + Qwen fallback | GLM / Codex_Mimo | 双供应商保障可用性 |
| Embedding | bge-small-zh（本地） | GLM / Kimi | 零成本，社区活跃，文档全。text2vec-base-chinese 为备选 |
| 向量存储 | ChromaDB | 全部共识 | 轻量嵌入式，单机够用 |
| 结构化存储 | SQLite（WAL 模式） | Perplexity | WAL 提升并发读写 |
| RSS 解析 | feedparser | 全部共识 | 成熟稳定 |
| 中文分词 | jieba + 停用词表 | Codex_Mimo | 其他文档忽略的关键细节 |
| ReAct + Reflection | reflect → revise 闭环，max 2 次重试 | Codex_Mimo | 完整落地的反思闭环 |
| 去重策略 | 规则预筛 → 向量+编辑距离组合 → 模糊区间 LLM 裁决 → 同事件分组展示 | Codex_Mimo + Qwen | 编辑距离零成本，分组展示最实用 |
| 去重校准 | 20 对测试数据 + ≥90% 准确率验证 | Codex_Mimo | 唯一给出具体校准方法 |
| 排序公式 | 三/四因子 + importance 乘数 + Min-Max 归一化 + 分类上限 | Codex_Mimo + DeepSeek | 归一化是工程基本功，分类上限防信息茧房 |
| 偏好更新 | EMA 平滑更新 + 自动清理低权重关键词 | GLM + Codex_Mimo | EMA 防剧烈波动，自动清理防膨胀 |
| 反馈设计 | positive / negative / irrelevant 三级 | Codex_Mimo | 比二元精细，比四级简洁 |
| 元数据标准化 | enrich_metadata 节点 | Kimi | LLM 提取 category/keywords/importance |
| 条目标准化 | normalize_items 显式节点 | Perplexity | 去重前统一格式 |
| 记忆系统 | 四层记忆完整落地，语义记忆种子数据 | Codex_Mimo | 务实的 MVP 策略 |
| FC/MCP 分层 | MVP 全部用 FC，接口预留 MCP 迁移 | WorkBuddy 建议 | MVP 最简，二期按服务特征区分 SSE/stdio |
| 触发模式 | trigger_type: scheduled / manual / feedback | Codex_Mimo | 预留事件驱动扩展 |
| 并行采集 | fetch_rss / search_web / recall_memory 三路并行 | Codex_Mimo | 显著减少执行时间 |
| 可追溯性 | item_relations 表 + execution_logs 表 | Codex_DeepSeek | 去重结果可解释，执行可回溯 |
| 推送模式 | MVP 定时推送，预留事件驱动钩子 | 全部共识 + GPT | MVP 稳，二期加自主推送 |
| 前端 | Streamlit | 全部共识 | 极低代码，快速搭建 |
| 时间衰减预筛 | Decay(t) 预筛 | Qwen | 避免对过时内容做无效计算 |
| 跨类别配额 | 每分类上限 8 条 | GLM + Codex_Mimo | 避免信息茧房 |
| 部署 | MVP 本地跑通，二期补 Docker Compose | DeepSeek / GLM | 先验证功能，再工程化 |

---

## 附录：整合修正记录

本综合文档在整合 5 份分析报告过程中，修正了以下原始分析报告中的错误：

| # | 来源报告 | 错误类型 | 错误内容 | 修正为 |
|---|---------|---------|---------|--------|
| 1 | DeepSeek 报告 | 严重事实错误 | 声称 DeepSeek 文档 search_web 使用 stdio 模式 | 原始文档 3.2.2 节明确标注 SSE |
| 2 | DeepSeek 报告 | 严重事实错误 | 将 Codex_DeepSeek push 归入 stdio 阵营 | 原始文档 3.6 节明确标注 SSE 协议 |
| 3 | DeepSeek 报告 | 中等事实错误 | 将 Codex_Mimo RSS 归入"httpx+自定义解析" | 原始文档使用 feedparser |
| 4 | DeepSeek 报告 | 中等事实错误 | 声称 TRAE w_sim=0.40 | 原始文档 5.2 节 w_sim=0.35 |
| 5 | DeepSeek 报告 | 轻微事实错误 | 将 Qwen 归入"三阶段去重" | Qwen 为两阶段（向量+LLM） |
| 6 | DeepSeek 报告 | 轻微不严谨 | 声称"全部文档均使用 APScheduler"但 GPT 除外 | GPT 文档第十节明确列出 APScheduler，所有 9 份均使用 |
| 7 | Kimi 报告 | 过度推断 | "LLM 评估去重结果的 precision/recall" | 原文为"人工标注" |
| 8 | Kimi 报告 | 过度推断 | "LLM 对简报进行用户满意度评分" | 应为用户评分，非 LLM 评分 |
| 9 | Kimi 报告 | 过度推断 | "LLM 对偏好向量进行正负分离" | 原文描述的是向量数学操作 |
| 10 | Kimi 报告 | 过度推断 | "LLM 对采集结果进行空结果回退" | 原文为条件边路由逻辑 |
| 11 | TRAE 报告 | 严重事实错误 | 声称"Codex-DeepSeek 将搜索放在 stdio" | 原始文档 3.3 节明确标注 SSE 协议 |
| 12 | TRAE 报告 | 严重事实错误 | 声称"Kimi 是粗粒度 State" | Kimi 文档 2.2 节 State 含十几个字段，是细粒度 |
| 13 | TRAE 报告 | 来源标注错误 | "reflect 最多 3 次重试"标注来源为 GPT | 实际来自 Kimi 文档（max_retry=3） |
| 14 | WorkBuddy 报告 | 中等事实错误 | 声称"Codex_Mimo 是唯一区分 MCP 传输模式的文档" | GLM 文档同样区分了 web_search SSE + push_notifier stdio |
| 15 | 多份报告 | 共识过度泛化 | "全部 9 份文档均选用 DeepSeek 或通义千问" | GPT 文档未明确指定 LLM 供应商 |

---

*综合分析完成。9 份原始文档全部纳入分析，5 份 AI 分析报告全部整合并修正。*
