决策框架：
- **产品冲突**（P系列）→ 优先选能最快验证核心价值假设的方案
- **技术冲突**（T系列）→ 优先选开发成本最低、复杂度最可控的方案，预留扩展点
- 每个决策必须引用原始文档的具体依据

---

## 🏆 决策清单

---

#### 冲突 P1：简报生成驱动模式（类型：产品逻辑）

- **阵营A（流程驱动）**：按预设工作流每日定时采集并生成日报。依据：Codex_DeepSeek 2.1节"定时触发→采集→去重→排序→生成→推送"；DeepSeek 2.2节"八节点工作流"；GLM/Kimi/Perplexity/Qwen/TRAE 均有明确的阶段划分和调度触发描述。
- **阵营B（Goal驱动）**：Agent 围绕用户长期目标自主决定何时搜索、何时推送。依据：GPT 第三节"Planner输出JSON action"、工作流图中 Reflection→Continue?→Planner 的自主循环。
- **🏆 最终决策：阵营A（流程驱动）**
- **📝 决策理由**：MVP 核心目标是验证"个性化信息简报是否有用户价值"，而非验证"自主 Agent 规划能力"。流程驱动开发成本远低于 Goal 驱动（无需实现 Planner 决策循环、Reflection 重试判断等复杂逻辑），能让产品在 2 周内跑通完整闭环，拿到真实用户反馈后再考虑升级为 Goal 驱动。

---

#### 冲突 P2：推送机制（类型：产品逻辑）

- **阵营A（定时/手动推送）**：每日固定时间推送简报，或通过 Streamlit 手动查看。依据：Codex_DeepSeek 2.1节" scheduler 触发"；DeepSeek 2.2节" push_notification 为独立节点"；GLM/Kimi 均在阶段末尾触发推送。
- **阵营B（自主推送）**：Planner 判断"重大事件立即推送，普通事件积累成日报"。依据：GPT 第四节排序公式中的 freshness 因子、action 含 PushNow。
- **🏆 最终决策：阵营A（定时推送）+ 重大事件破例立即推送**
- **📝 决策理由**：MVP 阶段先实现固定时间每日推送（开发成本最低，仅需 APScheduler 一个 cron job）。同时为 v1.1 预留接口：当单条内容 score > 0.85 且 freshness < 2小时 时，破例立即推送。这样既保证 MVP 简单可交付，又预留了 Goal 驱动的核心差异化能力。

---

#### 冲突 P3：用户配置粒度（类型：产品逻辑）

- **阵营A（多维度配置）**：用户配置多个关注领域、关键词、RSS 源列表。依据：Codex_Mimo 3.1节工具清单中 user_profile 含 topics/keywords/sources 字段；DeepSeek 4.1节"用户画像十几个字段"；Kimi 2.2节 State 定义含 user_profile 详细结构。
- **阵营B（仅需 Goal）**：用户只需输入一个长期目标文本。依据：GPT 文档开篇"用户只需告诉我她的 Goal"。
- **🏆 最终决策：阵营B（仅需 Goal）+ 后端 LLM 提取结构化字段**
- **📝 决策理由**：从 PM 视角，表单填写是用户流失的高风险点。Goal 文本输入（类似 ChatGPT 的 system prompt 输入）用户体验远优于结构化表单。技术上可行：用 LLM 从 Goal 文本中提取 topics/keywords/sources 结构化字段，存入 user_profile 表，完全兼容阵营A的后端设计。开发成本：+1 个 LLM 调用（一次性），节省前端表单开发 ~1天。

---

#### 冲突 P4：去重结果处理（类型：产品逻辑）

- **阵营A（折叠分组）**：同事件不同角度归入同一 cluster，简报中展示为"相关报道"折叠组。依据：GLM 6.2节"NER实体校验辅助去重，同事件合并"；Codex_Mimo 6.1节"同事件不同角度保留策略"。
- **阵营B（计数标注）**：保留一篇代表，简报中标注"还有 N 篇类似报道"。依据：DeepSeek 6.2节"strict 阶段仅保留 score 最高的一条"。
- **🏆 最终决策：阵营B（计数标注）**
- **📝 决策理由**：MVP 前端基于 Streamlit，实现折叠分组 UI 需要自定义 CSS/JS 组件（+0.5天开发）。计数标注仅需文本模板 `{title}（还有 {n} 篇类似报道）`，零额外前端成本。信息密度足够，用户能感知到"有多篇相关报道"但不被 UI 复杂度干扰。

---

#### 冲突 P5：搜索采集角色（类型：产品逻辑）

- **阵营A（搜索为并列通道）**：搜索与 RSS 并行采集。依据：Codex_Mimo 2.1节"三路并行采集（fetch_rss / search_web / recall_memory）"；Kimi 2.1节点图中 init_state 后并行 fetch_rss 和 fetch_search；TRAE 3.2节工具清单中 search_web 与 rss_fetch 并列。
- **阵营B（搜索为补充）**：搜索仅在 RSS 条目不足时触发。依据：DeepSeek 2.2节工作流图中 collect_sources 节点优先 RSS、失败时 fallback search；Qwen/Perplexity 未明确描述并行采集。
- **🏆 最终决策：阵营B（搜索为补充）+ RSS 并行多源**
- **📝 决策理由**："搜索为并列通道"意味着每次运行都调用搜索 API（成本：每次 +1 次搜索 API 调用，可能触发速率限制）。"搜索为补充"更经济：先并行采集多个 RSS 源（免费），仅当去重后条目 < 5 条时触发搜索 API 补充。开发成本相当，但运营成本阵营B低得多。注意：这里的"RSS 并行多源"指并行采集用户配置的多个 RSS URL，而非与搜索并行。

---

#### 冲突 P6：简报输出风格（类型：技术架构）

- **阵营A（结构化 JSON 输出）**：LLM 输出 JSON 再渲染为 Markdown。依据：GLM 5.2节"LLM 输出 JSON {title, summary, items: [...], score}"；Kimi 5.3节"brief_quality 结构化评分 {completeness, relevance, coherence, score}"。
- **阵营B（直接 Markdown 生成）**：LLM 直接输出 Markdown 文本。依据：Codex_DeepSeek 第五节"generate_digest 节点输出 Markdown"；DeepSeek/Perplexity/Qwen/TRAE 均未要求 JSON 中间格式。
- **🏆 最终决策：阵营A（结构化 JSON 输出）**
- **📝 决策理由**：CTO 视角：JSON 输出可验证、可测试、可复用。Markdown 直接生成的问题是：LLM 输出格式不稳定，难以做质量检查和自动重试。JSON 格式的额外成本仅仅是输出 schema 约束（+1 个 system prompt 段落），但换来的是：① 输出可 JSON Schema 校验 ② 质量评分可自动化（Kimi 的 brief_quality 评分）③ 前端渲染与内容生成解耦。这是"复杂度换取可维护性"的典型场景，值得。

---

#### 冲突 P7：用户反馈选项（类型：产品逻辑）

- **阵营A（多元反馈）**：like / dislike / irrelevant / valuable 四级。依据：Kimi 4.3节"四级反馈 like/valuable/dislike/irrelevant"；Codex_Mimo 反馈类型含 like/dislike/neutral；Qwen task_logs 表含 like/dislike/ignore。
- **阵营B（二元反馈）**：仅 like / dislike 两选项。依据：Codex_DeepSeek feedback 表 CHECK 约束含 like/dislike（实际含 read/irrelevant 四选项，但 UI 仅展示 like/dislike）；DeepSeek/Perplexity 简报推送后仅含点赞/踩。
- **🏆 最终决策：阵营A（多元反馈，三级：like / dislike / irrelevant）**
- **📝 决策理由**："irrelevant"是很是不一样的信号——它表示"这个项目不属于我的关注领域"，而非"属于但质量差"。有了 irrelevant 信号，系统可以更新用户的 negative preference vector（DeepSeek 4.1节已有 v_dislike 设计），这比只有 like/dislike 能更快收敛到用户的真实偏好。valuable 与 like 语义重叠，舍去。最终保留三级：like（+偏好）/ dislike（-偏好）/ irrelevant（从候选集移除此类内容）。开发成本：前端仅需 3 个按钮（+0.5小时），但偏好学习速度显著提升。

---

#### 冲突 T1：MCP Push 部署模式（类型：技术架构）

- **阵营A（stdio 模式）**：依据：DeepSeek 3.2.6节"push_briefing [MCP, stdio 部署]"；GLM 第3节"push_notifier [stdio]"；Kimi 3.2节 Tool 8"MCP - stdio"；TRAE 3.5节"push_notification deployment_mode: stdio"；Codex_Mimo 架构图标注 notification_push [stdio]。
- **阵营B（SSE 模式）**：依据：Codex_DeepSeek 3.6节"push_notification MCP 部署: SSE 协议"；Perplexity 3.2节"send_notification [MCP, SSE]"；Qwen 第3节"send_notification SSE 部署"。
- **🏆 最终决策：stdio 模式（阵营A）**
- **📝 决策理由**：CTO 视角：stdio 模式下 MCP Server 作为子进程随主进程启停，无需管理端口、无需处理 HTTP 连接池，部署复杂度显著更低。SSE 模式的优势是跨进程/跨机器调用，但 MVP 阶段所有组件在同一进程/同一机器上，stdio 完全够用。注意：search_web 用 SSE（因为搜索 API 可能已是独立服务），但 push_notification 用 stdio（本地桌面通知或 Streamlit 内嵌推送）。

---

#### 冲突 T2：向量去重阈值（类型：技术架构）

- **阵营A（高阈值 ≥0.90）**：依据：DeepSeek 6.2节"initial 0.88 / strict 0.95"；GLM 第6节"两阶段去重，strict 阶段 0.90"；Kimi 6.1节"严格去重 0.90"；TRAE 6.2节"严格 0.90 / 合并 0.75"。
- **阵营B（中阈值 0.85-0.88）**：依据：Codex_DeepSeek 6.1节"去重阈值 0.85"；Codex_Mimo 6.1节"快速过滤 0.85"；Perplexity 第6节"向量相似度 0.88"；Qwen 第6节"0.88 初始"。
- **🏆 最终决策：0.88 初始 + GLM 的校准脚本**
- **📝 决策理由**：阈值选择本质是经验问题，不是理论问题。0.88 是双方重叠最多的数值（Perplexity、Qwen、DeepSeek initial 都用 0.88），选它争议最小。更重要的是：采用 GLM 的 calibrate_dedup.py 方案（人工标注 200 对样本 → P/R/F1 曲线 → 选最优阈值），让阈值成为"可随着数据积累自动优化"的系统参数，而非硬编码常量。开发成本：+1 个校准脚本（~100行 Python），但换来数据驱动的阈值选择。

---

#### 冲突 T3：Embedding 模型选择（类型：技术架构）

- **阵营A（本地 sentence-transformers）**：依据：Codex_DeepSeek 第八节"paraphrase-multilingual-MiniLM-L12-v2"；GLM 第八节"bge-small-zh（本地）"；TRAE 第八节"vector 计算 sentence-transformers"；Codex_Mimo 第八节"text2vec-base-chinese"；Kimi 第八节"BAAI/bge-small-zh-v1.5"。
- **阵营B（API 调用）**：依据：DeepSeek 第8节"text-embedding-v3 (DeepSeek)"；Qwen 第八节"BGE-M3 本地或阿里云 text-embedding-v3 双轨"。
- **🏆 最终决策：阵营A（本地 sentence-transformers，选 bge-small-zh-v1.5）**
- **📝 决策理由**：CTO 视角：MVP 阶段调用量不稳定，API Embedding 的成本难以预测（每 1000 次调用 ~$0.0004，但 MVP 测试阶段可能频繁重跑）。本地模型一次下载、无限调用、无速率限制，开发调试体验远优于 API。bge-small-zh-v1.5（Kimi 选择）在中文语义相似度任务上表现优秀，153M 参数，推理速度 ~50ms/条，完全满足 MVP 需求。预留切换 API 的接口（Qwen 的双轨思路），当用量稳定后再评估是否切换。

---

#### 冲突 T4：MCP Server 数量（类型：技术架构）

- **阵营A（3+ 个 MCP）**：依据：DeepSeek 3.1节"3个 MCP Server（search SSE + push stdio + db stdio）"；Perplexity 3.1节"5个 MCP Server"；TRAE 3.2节"3个 MCP Server（search SSE + notification stdio + vector_store stdio）"。
- **阵营B（2 个 MCP）**：依据：Codex_DeepSeek 3.3节"2个 MCP（web_search SSE + push_notification SSE）"；Codex_Mimo 架构图"2个 MCP（web_search SSE + notification_push stdio）"；GLM/Kimi/Qwen 均仅 2 个 MCP。
- **🏆 最终决策：阵营B（2 个 MCP）+ DB/向量操作改为 FC（Function Calling）**
- **📝 决策理由**：MCP Server 的引入理由是"工具需要跨语言复用"或"工具是有状态服务"。但 MVP 阶段：① 所有组件用 Python 编写，无需跨语言 ② DB 操作（SQLite）是无状态的函数调用，封装为 MCP 只增加复杂度 ③ 向量操作（ChromaDB）同理。仅保留 2 个 MCP：search_web（因为搜索是外部 API，适合封装为独立服务）和 push_notification（因为推送涉及桌面通知权限，适合独立进程）。其余工具全部改为 FC。减少 1-3 个 MCP Server = 减少相应数量的进程管理和通信代码。

---

#### 冲突 T5：排序权重配置（类型：技术架构）

- **阵营A（偏好权重较高 w_pref ≥ 0.30）**：依据：Codex_DeepSeek 第五节"w3=0.10（初始）/ 0.40（有反馈后）"；Codex_Mimo 5.1节"w_pref=0.45"；GLM 第5节"w3=0.30"；Kimi 5.2节"γ=0.30"。
- **阵营B（相似度/相关性权重较高 w_sim ≥ 0.35）**：依据：GPT 第四节"score=0.4*relevance+0.25*preference+0.20*importance+0.15*freshness"；DeepSeek 第五节"α=0.40"；Perplexity 第5节"w1=0.40"；TRAE 5.2节"w_sim=0.35"；Qwen 第5节"w1=0.4"。
- **🏆 最终决策：冷启动用阵营B（相似度优先），有反馈后动态切换为阵营A（偏好优先）**
- **📝 决策理由**：PM 视角：冷启动阶段（用户无反馈历史）只能用内容相似度排序，因为没有偏好数据。当用户的反馈积累到 ≥ 3 条时，系统应自动切换到偏好权重更高的公式。这本质上是 Codex_DeepSeek 的设计（w3 从 0.10 动态调到 0.40），但初始公式采用 GPT 的 4 因子版本（relevance + preference + importance + freshness），而非 Codex_DeepSeek 的 3 因子版本。这样冷启动和有反馈后都有合理的排序逻辑。

---

#### 冲突 T6：去重技术路线（类型：技术架构）

- **阵营A（纯向量去重）**：依据：Codex_DeepSeek 6.1节"向量相似度 > 0.85 判定为重复"；DeepSeek 6.2节"两阶段向量去重"；GPT 未详细描述去重技术细节。
- **阵营B（多信号组合去重）**：依据：Codex_Mimo 6.1节"0.6·cosine + 0.4·edit_distance"；GLM 第6节"NER 实体校验 + 向量双验证"；Qwen 第6节"向量粗排 + LLM 精排"；Perplexity 第6节"规则预过滤 → 向量相似度 → LLM 事件判别三阶段"。
- **🏆 最终决策：阵营A（纯向量）+ 模糊区间 LLM 裁决（借鉴 Qwen）**
- **📝 决策理由**：纯向量去重开发成本最低（已有 Embedding 管道，只需加一个阈值判断）。但 Pure 向量去重在"同事件不同表述"场景（如"苹果发布新 iPhone" vs "Apple 推出 iPhone 16"）容易漏去重。解决方案：不增加第二个向量以外的信号（NER/edit_distance 增加维护成本），而是采用 Qwen 的"模糊区间 LLM 裁决"思路：当相似度在 0.70-0.88 之间时，用 LLM 做二元判断"是否同一事件"。这样：① 高置信度（≥0.88）直接判定为重复 ② 低置信度（<0.70）直接判定为不重复 ③ 模糊区间才调用 LLM，控制成本。开发成本：+1 个 LLM 调用模板，但只在模糊区间触发，实际调用量很小。

---

#### 冲突 T7：短期记忆窗口大小（类型：技术架构）

- **阵营A（10 轮）**：依据：Codex_DeepSeek 4.2节"短期记忆 10 轮"；Perplexity 4.1节"10-20 轮滑动窗口"。
- **阵营B（15 轮）**：依据：Codex_Mimo 4.1节"短期记忆 15 轮"；DeepSeek 第4节"滑动窗口保留最近 15 轮"；Kimi 同样标注 15 轮。
- **阵营C（10-20 轮滑动，动态）**：依据：Kimi 4.1节"10-20 轮滑动窗口，超窗时压缩为情节记忆"。
- **🏆 最终决策：15 轮（阵营B），超窗时压缩写入情节记忆（采纳 Kimi 的设计）**
- **📝 决策理由**：15 轮是双方重叠的默认值，足够容纳一个完整的工作流对话（采集→去重→排序→生成→推送 = 约 5-8 轮），又有余量。更重要的是采纳 Kimi 的"超窗压缩"设计：当对话超过 15 轮时，将前 10 轮的内容压缩为一段情节记忆写入 SQLite，这样短期记忆始终保持 15 轮的窗口，但长期上下文不会丢失。这个设计开发成本不高（+1 个 LLM 调用做压缩），但显著提升了多轮对话的连贯性。

---

#### 冲突 T8：时间衰减函数（类型：技术架构）

- **阵营A（指数衰减 exp(-λ·Δt)）**：依据：GPT 第四节"freshness = exp(-0.05 * age_hours)"；Codex_Mimo 5.2节"Decay(t) = exp(-λ·Δt)"；DeepSeek/Kimi/Qwen 均采用类似公式。
- **阵营B（半衰期公式 exp(-Δt/τ)）**：依据：GLM 第5节"时间衰减函数 exp(-Δt/τ), τ=24h"；TRAE 5.3节"HALF_LIFE=24 小时，decay = exp(-Δt/HALF_LIFE)"。
- **🏆 最终决策：阵营B（半衰期公式），τ=24h**
- **📝 决策理由**：数学上完全等价（λ = 1/τ），但半衰期形式对产品经理和非技术人员更直观："24小时前的内容得分减半"比"λ=0.05 的指数衰减"更容易理解和调参。采用 GLM/TRAE 的实现，τ 设为可配置参数（默认 24h），未来 PM 想调整衰减速度时无需找工程师改代码，改配置即可。

---

#### 冲突 T9：反思重试次数（类型：技术架构）

- **阵营A（2-3 次）**：依据：GLM 2.2节"pass=False & retries < 2 时重新生成"；Codex_Mimo 2.2节"max 2 retries"；Kimi 5.3节"max_retry=3，brief_quality.score < 0.7 触发重试"。
- **阵营B（不明确 / 1 次）**：依据：GPT 工作流图暗示单次反思决策；Codex_DeepSeek"不合格返回重生成"但未明确次数上限。
- **🏆 最终决策：最多 2 次重试（阵营A 的 GLM/Codex_Mimo 方案）**
- **📝 决策理由**：0 次重试（不反思）质量无保障，1 次可能不够（第一次反思可能仍然不合格），3 次成本较高（每次重试 = 1 次 LLM 调用，且边际收益递减）。2 次是实验上合理的默认值。具体实现借鉴 Kimi 的 brief_quality 评分触发机制：生成简报后自动评分，< 0.7 触发重试，最多 2 次。若 2 次后仍 < 0.7，接受当前最佳结果并记录日志供后续分析。

---

#### 冲突 T10：向量库交互方式（类型：技术架构）

- **阵营A（本地嵌入式直接调用，FC）**：依据：Codex_DeepSeek/Codex_Mimo/DeepSeek（db_read/db_write 除外）/GLM/Kimi/Perplexity 均通过 Function Calling 直接调用 ChromaDB Python SDK。
- **阵营B（封装为 MCP Server 解耦）**：依据：TRAE 3.2节"vector_store MCP stdio"；DeepSeek 3.2节"db_read/db_write MCP stdio"；Qwen 第3节"save_preference MCP stdio"。
- **🏆 最终决策：阵营A（FC 直接调用 ChromaDB SDK）**
- **📝 决策理由**：CTO 视角：MCP Server 的核心价值是"工具复用"和"独立部署"。向量库操作（add/get/search）是 ChromaDB 的标准 SDK 调用，无需独立进程，无需跨语言复用，封装为 MCP 只增加进程间通信开销和代码复杂度。FC 直接调用开发成本更低（无需写 MCP Server 实现，只需 import chromadb），延迟更低（无 IPC 开销）。未来如果需要将向量库迁移到独立服务器时，再封装为 MCP SSE 模式，届时改动是纯增量的。

---

#### 冲突 T11：部署方案（类型：技术架构）

- **阵营A（本地开发运行）**：依据：Codex_DeepSeek/Codex_Mimo/DeepSeek/Kimi/Perplexity/Qwen/TRAE 均描述"python main.py"或"streamlit run app.py"启动方式。
- **阵营B（Docker Compose）**：依据：GLM 第7节"Docker Compose 一键部署，含 Streamlit/ChromaDB/SQLite/APScheduler"；Perplexity 部署章节同样提及 Docker。
- **🏆 最终决策：阵营A（本地开发运行）for MVP，+ Docker Compose for v1.0 交付**
- **📝 决策理由**：MVP 开发阶段，团队需要频繁修改代码、重启服务、查看日志。Docker Compose 每次改代码都要 rebuild image（或 mount volume + 重启容器），开发迭代速度显著低于本地运行。正确策略：MVP 开发用本地运行（阵营A），但当产品达到 v1.0 交付给用户时，必须提供 Docker Compose 一键启动方案（阵营B）。GLM 的 Docker Compose 设计很好，保留作为 v1.0 交付物，但 MVP 开发阶段不用。

---

## 📋 决策汇总表

| # | 冲突 | 最终决策 | 核心理由摘要 |
|:---:|-------|---------|------------|
| P1 | 简报生成驱动模式 | 流程驱动 | MVP 跑闭环优先，Goal 驱动是 v2.0 |
| P2 | 推送机制 | 定时推送 + 重大事件破例 | 最小可用，预留升级接口 |
| P3 | 用户配置粒度 | Goal 文本 + LLM 提取 | 用户体验最优，开发成本相当 |
| P4 | 去重结果处理 | 计数标注 | Streamlit 实现成本最低 |
| P5 | 搜索采集角色 | RSS 为主 + 搜索补充 | 运营成本更低 |
| P6 | 简报输出风格 | 结构化 JSON | 可测试、可校验、可复用 |
| P7 | 用户反馈选项 | 三级（like/dislike/irrelevant） | irrelevant 信号价值高，开发成本可忽略 |
| T1 | MCP Push 部署模式 | stdio | MVP 部署复杂度最低 |
| T2 | 向量去重阈值 | 0.88 + 校准脚本 | 数据驱动，可自动优化 |
| T3 | Embedding 模型 | 本地 bge-small-zh-v1.5 | 免费、无速率限制、中文效果好 |
| T4 | MCP Server 数量 | 2 个（search + push） | DB/向量操作改 FC，降低复杂度 |
| T5 | 排序权重配置 | 冷启动相似度优先，有反馈后偏好优先 | 兼顾冷启动和个性化 |
| T6 | 去重技术路线 | 纯向量 + 模糊区间 LLM 裁决 | 最小成本覆盖边界情况 |
| T7 | 短期记忆窗口 | 15 轮 + 超窗压缩 | 平衡连贯性和成本 |
| T8 | 时间衰减函数 | 半衰期公式 τ=24h | 更直观，可调参 |
| T9 | 反思重试次数 | 最多 2 次 | 质量与成本的平衡点 |
| T10 | 向量库交互方式 | FC 直接调用 | 最低开发成本和延迟 |
| T11 | 部署方案 | 本地开发 + Docker Compose 交付 | 开发效率优先，交付用容器化 |
