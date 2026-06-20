### 【分析目录】

确认已读取全部 9 份文档：

1. **MVP\_DESIGN\_Codex\_DeepSeek.md**（Codex via 架构设计方案）
2. **MVP\_DESIGN\_Codex\_Mimo.md**（Codex Mimo）
3. **MVP\_DESIGN\_DeepSeek.md**（DeepSeek）
4. **MVP\_DESIGN\_GLM.md**（GLM）
5. **MVP\_DESIGN\_GPT.md**（GPT）
6. **MVP\_DESIGN\_Kimi.md**（Kimi）
7. **MVP\_DESIGN\_Perplexity.md**（Perplexity）
8. **MVP\_DESIGN\_Qwen.md**（Qwen）
9. **MVP\_DESIGN\_TRAE.md**（TRAE）

***

### 一、项目定位

FeedLens 是一个基于 LangGraph 构建的**主动式智能信息简报 Agent**，用户只需定义长期关注领域（如"AI Agent"、"新能源车"），Agent 即可自主完成从 RSS/搜索采集、向量去重、智能排序、LLM 摘要生成、结构化简报输出到用户反馈学习的完整闭环，并通过 Streamlit 前端展示和 APScheduler 定时调度实现每日自动化信息消费。

***

### 二、共识点分析

- **LangGraph StateGraph 作为核心编排框架**：所有 9 份文档均采用 LangGraph 的 StateGraph 定义 Agent 工作流，使用 TypedDict 定义共享状态，通过节点（Node）和边（Edge）实现采集→处理→生成→反思→推送的流水线。所有文档均在"Agent 工作流设计"章节详细描述了节点定义、边连接和条件分支逻辑。
- **四层记忆体系（短期/长期/情节/语义）**：所有文档均认同记忆系统应包含：短期记忆（LangGraph State/内存滑动窗口）、长期记忆（ChromaDB 向量存储用户偏好）、情节记忆（SQLite 执行日志）、语义记忆（ChromaDB 领域知识/RAG）。该共识贯穿各文档的"记忆系统设计"章节，尽管具体实现细节（如滑动窗口轮数、向量更新算法）存在差异。
- **Function Calling 与 MCP 混合工具调用策略**：所有文档均将工具分为两类——简单/本地/无状态工具（如 RSS 采集、文本摘要、向量去重）使用 Function Calling；复杂/需独立部署/跨 Agent 复用工具（如搜索服务、推送通知）使用 MCP Server。该共识在"工具清单"章节明确体现，且均提到 SSE 和 stdio 两种 MCP 传输模式。
- **DeepSeek/通义千问作为国内 LLM 主力选型**：所有文档均选择 DeepSeek-V3 或通义千问（Qwen-Max/Qwen-Plus）作为 LLM 大脑，理由均为"国内可用、无需科学上网、性价比高、支持 Function Calling"。该共识在"技术栈选择"或"大脑层"章节一致出现。
- **SQLite + ChromaDB 双存储架构**：所有文档均采用 SQLite 存储结构化数据（用户、源、条目、反馈、执行日志）和 ChromaDB 存储向量数据（条目 embedding、用户偏好向量、领域知识）。该共识在"数据模型"和"技术栈选择"章节统一体现。
- **基于向量相似度的两阶段去重策略**：所有文档均认同使用 embedding 余弦相似度进行去重，并区分"真正重复"（高相似度）和"同一事件不同角度"（中等相似度）。该共识在"去重策略设计"章节出现，尽管阈值设定（0.85/0.88/0.90）和校准方法存在差异。
- **多因子加权排序公式**：所有文档均采用 `final_score = w1*relevance + w2*recency + w3*preference + w4*authority` 的线性加权模型，且均提到时间衰减函数（指数衰减）和权重动态调整机制。该共识在"排序算法设计"章节一致体现。
- **Streamlit 作为 MVP 前端**：所有文档均选择 Streamlit 作为用户界面，用于配置管理、简报展示、反馈收集和执行监控。该共识在"技术栈选择"和"展示层"章节统一出现。
- **APScheduler 定时调度**：所有文档均使用 APScheduler 实现每日定时触发（默认 8:00），支持 cron 表达式。该共识在"技术栈选择"和"定时调度"章节出现。
- **ReAct + Reflection 规划模式**：所有文档均在规划层引入 ReAct（思考-行动-观察循环）和 Reflection（反思审查）机制，且均设置反思失败时的重试/修正逻辑（最大重试 2-3 次）。该共识在"规划层"和"Agent 工作流设计"章节体现。

***

### 三、冲突点对比

| 冲突类型     | 冲突事项                      | 阵营A观点及依据章节                                                                                                                                                                                                                                                                                                                         | 阵营B观点及依据章节                                                                                                                                                                                                                                                                                                                                        | 核心分歧点                                                                                                                                             |
| -------- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| **产品逻辑** | **简报触发模式：定时推送 vs 自主决策推送** | **定时推送阵营**：Codex\_DeepSeek（阶段P5-定时调度）、Codex\_Mimo（P1-定时采集）、DeepSeek（阶段四-定时调度）、Kimi（Phase 4-定时自动运行）、Perplexity（阶段1-定时触发）、Qwen（Phase 4-定时自动运行）、TRAE（阶段八-定时调度）均明确采用 APScheduler 每日固定时间（如 8:00）生成并推送简报。                                                                                                                                | **自主决策推送阵营**：GPT（第十节-自主推送机制）明确提出"不是每天9点推送，而是 Planner 决定"，当检测到重大事件（如 GPT-6 发布）时立即推送，普通新闻积累到一定数量再生成日报。                                                                                                                                                                                                                                              | 核心分歧在于 Agent 的主动性边界：定时推送将 Agent 视为"自动化工具"，自主决策将 Agent 视为"自主决策体"，后者更强调 Planner 节点的决策权和事件驱动的即时性。                                                    |
| **产品逻辑** | **MVP 用户数量：单用户 vs 多用户**   | **单用户阵营**：Kimi（9.2-后续迭代才加多用户支持）、Qwen（9.1-MVP 只支持一个用户）、TRAE（9.1-用户注册/登录但工程结构预留多用户）明确将多用户支持列为 P1/P2 后续迭代。                                                                                                                                                                                                                            | **多用户阵营**：Codex\_DeepSeek（SQLite 表设计含 user\_id 外键）、Codex\_Mimo（users 表设计）、DeepSeek（users 表）、GLM（users 表）、Perplexity（users 表）在数据模型中直接设计多用户表结构，但 TRAE 在 9.2 中将多用户列为 P1。                                                                                                                                                                             | 分歧在于 MVP 边界划定：单用户阵营认为简历项目应快速验证核心闭环，多用户阵营认为数据模型应提前预留扩展性。                                                                                           |
| **技术架构** | **MCP 工具数量与部署方式**         | **多 MCP 阵营（3+个）**：TRAE（3.4-3.6 明确部署 search\_engine/notification\_service/vector\_store 三个 MCP Server，分别使用 SSE/stdio/stdio）、Kimi（3.1-10 个工具中 2 个 MCP：fetch\_search SSE + deliver\_brief stdio）、Perplexity（3.1-5 个 MCP：web\_search SSE + save\_items SSE + load\_user\_profile stdio + save\_feedback SSE + send\_notification SSE）。 | **少 MCP 阵营（2 个）**：Codex\_DeepSeek（十三-10 个 FC + 2 个 MCP：web\_search SSE + push\_notification stdio）、Codex\_Mimo（3-2 个 MCP：web\_search SSE + notification\_push stdio）、DeepSeek（3.1-2 个 MCP：search\_web SSE + push\_briefing stdio）、GLM（3-2 个 MCP：web\_search SSE + push\_notifier stdio）、Qwen（3-2 个 MCP：search\_web SSE + save\_preference stdio）。 | 核心分歧在于"向量数据库操作是否应封装为 MCP"：多 MCP 阵营（TRAE/Perplexity）将 ChromaDB 操作独立为 MCP Server，认为可跨 Agent 共享；少 MCP 阵营认为 ChromaDB 是本地库操作，Function Calling 直接调用更高效。 |
| **技术架构** | **数据库操作工具：FC vs MCP**     | **FC 阵营**：Codex\_DeepSeek（3.7-3.8 vector\_search/update\_user\_preference 均为 FC）、Codex\_Mimo（user\_preference\_query 为 FC）、DeepSeek（db\_read/db\_write 为 MCP 但 Codex 为 FC）、GLM（feedback\_recorder/preference\_learner 为 FC）、Qwen（update\_memory/retrieve\_memory 为 FC）。                                                            | **MCP 阵营**：TRAE（3.6 vector\_store 为 MCP stdio）、Perplexity（3.1 save\_items/load\_user\_profile/save\_feedback/write\_run\_log 均为 MCP）。                                                                                                                                                                                                             | 分歧在于数据库操作是否应解耦：FC 阵营认为 SQLite/ChromaDB 是本地资源，直接操作更高效；MCP 阵营认为数据库操作应服务化，便于前后端共享和事务管理。                                                              |
| **技术架构** | **Embedding 模型选择**        | **本地模型阵营**：Codex\_DeepSeek（八-sentence-transformers paraphrase-multilingual-MiniLM-L12-v2）、Codex\_Mimo（八-text2vec-base-chinese）、GLM（八-bge-small-zh）、TRAE（八-sentence-transformers）。                                                                                                                                                  | **API 阵营**：DeepSeek（3.2.3 提到 DeepSeek Embedding 模型）、Kimi（3.3 deduplicate 工具默认使用 BAAI/bge-small-zh-v1.5 但 8 中提及阿里云 text-embedding-v3）、Qwen（八-BGE-M3 本地或阿里云 text-embedding-v3）。                                                                                                                                                                     | 分歧在于本地推理 vs API 调用：本地模型零成本但需下载维护；API 免维护但增加延迟和成本。部分文档（Kimi/Qwen）采用双轨策略。                                                                           |
| **技术架构** | **去重阈值设定**                | **高阈值阵营（0.88-0.90）**：DeepSeek（6.1-初始阈值 0.88）、GLM（6.2-严格去重 0.90）、Kimi（6.2-严格去重 0.90）。                                                                                                                                                                                                                                               | **中阈值阵营（0.85）**：Codex\_DeepSeek（六-6.1 阈值 0.85）、Codex\_Mimo（6.2-semantic\_dedup\_threshold 0.85）、Perplexity（6.2-初始阈值 0.88 但 0.78-0.88 为 LLM 精排）、Qwen（6.2-阈值 0.88 但 0.70-0.88 为 LLM 精排）、TRAE（6.2-严格去重 0.90 但合并去重 0.75）。                                                                                                                             | 分歧在于去重严格度：高阈值减少误杀但可能漏重复；中阈值更激进但需配合 LLM 精排或人工校准。                                                                                                   |
| **技术架构** | **排序权重分配**                | **偏好主导阵营（w\_pref ≥ 0.30）**：Codex\_DeepSeek（五-w3=0.40/0.10）、Codex\_Mimo（五-w\_pref=0.45）、GLM（五-w3=0.30）、Kimi（五-γ=0.30）、Qwen（五-Feedback 权重 0.2 但 Sim 0.4）。                                                                                                                                                                            | **均衡阵营**：DeepSeek（五-α=0.4, β=0.3, γ=0.1, δ=0.2）、Perplexity（五-w1=0.40, w2=0.25, w3=0.25, w4=0.10）、TRAE（五-w\_sim=0.35, w\_time=0.30, w\_pref=0.25, w\_cat=0.10）。                                                                                                                                                                                    | 分歧在于个性化权重是否应主导：偏好主导阵营强调"越用越准"的个性化体验；均衡阵营强调时效性和相关性基础。                                                                                              |
| **技术架构** | **短期记忆窗口大小**              | **10 轮阵营**：Codex\_DeepSeek（4.2-最近10轮交互）。                                                                                                                                                                                                                                                                                           | **15-20 轮阵营**：Codex\_Mimo（4.1-保留最近 15 轮）、DeepSeek（4-滑动窗口保留最近 15 轮）、Kimi（4.1-10-20 轮）。                                                                                                                                                                                                                                                             | 分歧在于上下文长度与精度的权衡，但所有文档均支持超窗压缩为摘要。                                                                                                                  |

***

### 四、独特点提取

- **自主推送决策机制（重大事件即时推送）**：来自 **GPT 文档-第十节"自主推送机制"**。价值在于突破了传统定时日报模式，Planner 节点根据内容重要性自主决定即时推送 vs 积累生成日报，这是从"自动化工具"到"自主 Agent"的关键设计跃迁。
- **去重阈值校准脚本（可复现的 ROC 曲线选优）**：来自 **GLM 文档-6.4 阈值校准**。价值在于将去重从"经验设定"升级为"工程化流程"：人工标注 200 对样本 → 扫描阈值区间 → 绘制 P/R/F1 曲线 → 选 F1 最优点，并写成 `scripts/calibrate_dedup.py` 脚本。
- **跨类别配额机制（避免单话题霸屏）**：来自 **GLM 文档-5.3 重排序调整**。价值在于排序算法的公平性设计：按用户话题数均分配额（如 5 话题 × 4 条 = 20），单话题内按 final\_score 降序，避免热门话题垄断简报版面。
- **两阶段去重（向量粗筛 + LLM 精排）**：来自 **Qwen 文档-6 去重策略设计**。价值在于用 LLM 处理 0.70-0.88 相似度的"模糊地带"，区分"单纯重复"和"同事件不同视角"（如产品发布 vs 深度评测）。
- **情节记忆的 meta-learning（从多次执行中总结规律）**：来自 **GLM 文档-9.2 后续迭代**。价值在于将情节记忆从"日志记录"升级为"经验学习"——如总结"周二科技类简报用户更喜欢短摘要"。
- **执行仪表盘（成功率/耗时/反馈率可视化）**：来自 **GLM 文档-阶段 5 交付物**。价值在于将技术系统可视化，便于调试和简历展示。
- **权重动态调权机制（连续反馈自动调整 α）**：来自 **Kimi 文档-5.3 动态调权**。价值在于将排序从"静态公式"升级为"自适应学习"：连续 3 次 like → α+0.05，连续 2 次 irrelevant → α-0.05。
- **反思节点修改初稿（可追踪的修正记录）**：来自 **Perplexity 文档-阶段 5**。价值在于将 Reflection 从"通过/不通过"升级为"具体修改"，输出可追踪的修正记录。
- **LLM 轻量抽取命名实体（辅助去重判定）**：来自 **GLM 文档-6.2 实体校验**。价值在于用 spaCy/LLM 抽取命名实体计算重叠率，作为向量相似度的辅助判定。
- **Docker Compose 一键部署（含 Searxng）**：来自 **GLM 文档-8 技术栈** 和 **TRAE 文档-阶段十**。价值在于工程化完整性，将 Agent + Streamlit + ChromaDB + MCP Server 打包为 `docker-compose up` 一键启动。
- **简历话术量化指标提炼**：来自 **GLM 文档-阶段 6 关键任务**。价值在于将项目成果转化为可量化的简历 bullet 点（如"LangGraph 编排 X 节点工作流""向量去重 F1 达 X"）。
- **工具调用路由层（自动选择 FC/MCP）**：来自 **Kimi 文档-Phase 4 关键任务**。价值在于增加智能路由层，根据工具特性自动选择 Function Calling 或 MCP，而非硬编码。
- **MCP 搜索服务的流式返回（SSE 模式）**：来自 **Kimi 文档-3.2 fetch\_search**。价值在于 SSE 支持流式返回搜索结果，提升用户体验和系统响应性。
- **BGE-M3 多语言 Embedding 模型**：来自 **Qwen 文档-8 技术栈**。价值在于 BGE-M3 支持 100+ 语言、多粒度（句子/段落/文档）和密集+稀疏向量，为后续多语言扩展预留空间。
- **用户反馈的"不相关"选项（超越 like/dislike）**：来自 **Kimi 文档-3.2 update\_memory**。价值在于增加"irrelevant"和"valuable"反馈类型，使偏好学习更精细（irrelevant → topic 权重 -0.15）。
- **简报质量评分（completeness/relevance/coherence/score）**：来自 **Kimi 文档-2.2 State 定义**。价值在于将反思从定性升级为定量，用结构化评分（0-1）驱动重试决策。
- **任务级错误隔离（单次失败不阻塞后续调度）**：来自 **Qwen 文档-Phase 4 关键任务**。价值在于生产级稳定性设计，APScheduler 捕获异常后继续下一次定时任务。
- **LLM 判别同事件不同角度（same\_event / same\_topic\_different\_angle / different\_event）**：来自 **Perplexity 文档-6.3**。价值在于将去重结果显式分类为三种语义关系，为后续简报合并展示提供结构化依据。
- **SQLite WAL 模式与事务包裹**：来自 **Perplexity 文档-7 数据模型**。价值在于生产级数据库实践，WAL 模式提升并发读写，事务包裹确保简报生成流程的原子性。
- **结构化日志（structlog）**：来自 **Perplexity 文档-8 技术栈**。价值在于比标准 logging 更易解析和监控，适合结构化分析和日志聚合。
- **推送渠道的渐进式加载（按需启用/禁用）**：来自 **Kimi 文档-3.2 deliver\_brief**。价值在于 stdio 模式的 MCP Server 支持按需启动子进程，用户可按需启用邮件/微信/钉钉。
- **LLM 意图理解节点（understand\_intent）**：来自 **DeepSeek 文档-2 节点与边**。价值在于将任务类型识别（daily\_briefing/manual\_search/feedback\_update）显式化为独立节点，支持多种触发模式。
- **反馈子图独立触发（feedback\_workflow）**：来自 **DeepSeek 文档-2 节点与边**。价值在于将反馈处理从主流程解耦为独立子图，支持异步处理用户反馈。
- **embedding 模型下载进度条与备选方案**：来自 **Codex\_DeepSeek 文档-十四-风险与缓解措施**。价值在于工程细节：首次自动下载 sentence-transformers 模型时显示进度条，备选 LLM API 做 embedding。
- **30 天数据清理策略**：来自 **Codex\_DeepSeek 文档-阶段 P5**。价值在于数据生命周期管理，避免 SQLite/ChromaDB 无限增长。
- **LLM 评估排序准确率（A/B 测试）**：来自 **DeepSeek 文档-5 排序算法**。价值在于将算法优化从"经验调参"升级为"数据驱动"。
- **情节记忆的"相似失败模式"查询**：来自 **Perplexity 文档-4.3 情节记忆**。价值在于不仅记录执行日志，还支持按"相似失败模式"检索，如"上次搜索新能源车时 SearXNG 超时了，这次要加 fallback"。
- **用户偏好关键词自动清理（权重低于 0.1 自动清理）**：来自 **Codex\_Mimo 文档-4.2 长期记忆**。价值在于防止偏好向量膨胀，自动淘汰低权重关键词。
- **LLM 生成情节记忆摘要（增量总结压缩）**：来自 **Codex\_DeepSeek 文档-4.2 短期记忆管理**。价值在于超窗的早期对话通过 LLM 生成摘要压缩后存入长期记忆，而非简单丢弃。
- **来源多样性加分（source\_diversity\_bonus = +0.05）**：来自 **Codex\_DeepSeek 文档-6.3 同事件不同角度**。价值在于鼓励多源验证，同一事件的多角度报道合并后获得额外加分。
- **LLM 反思的具体审查维度（完整性、去重遗漏、可追溯性）**：来自 **Codex\_DeepSeek 文档-阶段 P3**。价值在于将反思从"质量检查"细化为三个具体维度。
- **LLM 生成执行轨迹摘要（自然语言摘要）**：来自 **GLM 文档-4.3 情节记忆**。价值在于每次任务完成后用 LLM 生成自然语言摘要，便于人类阅读和检索。
- **LLM 主动追问式偏好校准（Agent 发现偏好信号冲突时主动问用户）**：来自 **GLM 文档-9.2 后续迭代**。价值在于将 Agent 从"被动接收反馈"升级为"主动澄清偏好"。
- **LLM 作为排序的 importance 评估（1-5 分）**：来自 **GPT 文档-八-排序设计**。价值在于引入 LLM 对新闻重要性进行 1-5 分评估，作为排序公式的独立因子。
- **LLM 评估去重结果的 precision/recall**：来自 **DeepSeek 文档-6.1 阈值校准**。价值在于用 LLM 辅助评估去重效果，通过在 dev 集上人工标注 100 对样本计算 F1。
- **LLM 生成简报的多风格输出（concise/detailed/bullet）**：来自 **Kimi 文档-3.2 generate\_brief**。价值在于支持用户选择简报风格，提升个性化体验。
- **LLM 生成领域知识种子数据（语义记忆预置）**：来自 **Codex\_Mimo 文档-4.4 语义记忆**。价值在于通过 LLM 预置领域知识，为 RAG 检索提供基础语义支撑。
- **LLM 作为简报生成的"修正节点"（revise）**：来自 **Codex\_Mimo 文档-2.1**。价值在于反思不通过时，携带反思意见进入修正节点，针对性调整。
- **LLM 对简报进行"覆盖率"检查（是否遗漏高分内容）**：来自 **Perplexity 文档-2.3 分支逻辑**。价值在于反思节点检查是否遗漏了高分条目。
- **LLM 对搜索关键词进行动态扩展（ReAct 换关键词重试）**：来自 **GLM 文档-2.2 条件边**。价值在于采集失败时，Planner 可动态更换关键词重试。
- **LLM 对推送渠道进行智能选择（根据内容类型选渠道）**：来自 **TRAE 文档-3.5**。价值在于推送服务支持多渠道，未来可根据内容类型智能选择。
- **LLM 对 RSS 源进行可信度评分（authority\_score）**：来自 **Perplexity 文档-7 数据模型**。价值在于为每个来源配置可信度权重，抑制低质来源。
- **LLM 对简报进行"用户满意度"评分（1-5 星）**：来自 **Kimi 文档-7 数据模型**。价值在于增加用户显式评分，作为情节记忆的质量指标。
- **LLM 对执行过程进行"自然语言摘要"（episodic\_notes）**：来自 **Codex\_Mimo 文档-4.3 情节记忆**。价值在于将执行日志转化为自然语言摘要。
- **LLM 对偏好向量进行"正负分离"（positive/negative 向量）**：来自 **DeepSeek 文档-4 长期记忆**。价值在于分别维护点赞和点踩的向量。
- **LLM 对简报进行"信息单一化"检查（避免来源单一）**：来自 **GLM 文档-2.2 反思节点**。价值在于反思检查"来源单一化"，确保多源覆盖。
- **LLM 对采集结果进行"空结果回退"（扩大时间窗/来源）**：来自 **GLM 文档-2.2 条件边**。价值在于去重后剩余 < 3 条时自动回退到采集节点扩大时间窗。
- **LLM 对简报进行"信息冗余"检查**：来自 **Codex\_Mimo 文档-2.1**。价值在于反思节点检查简报内部是否存在信息冗余。
- **LLM 对执行进行"耗时统计"（duration\_seconds）**：来自 **Codex\_Mimo 文档-4.3 情节记忆**。价值在于记录每次任务执行耗时。
- **LLM 对简报进行"矛盾检查"**：来自 **DeepSeek 文档-2 工作流说明**。价值在于反思节点检查简报中是否存在自相矛盾的信息。

