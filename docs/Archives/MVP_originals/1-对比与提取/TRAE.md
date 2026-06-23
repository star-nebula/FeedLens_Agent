## 【分析目录】

| # | 文档名称 | 生成来源 | 关键章节 |
|---|---------|---------|---------|
| 1 | MVP_DESIGN_Codex_DeepSeek.md | Codex | 架构图/State定义/去重阈值 |
| 2 | MVP_DESIGN_Codex_Mimo.md | Mimo | 规划层ReAct/Planner设计 |
| 3 | MVP_DESIGN_DeepSeek.md | DeepSeek | 并行分支/数据库表结构 |
| 4 | MVP_DESIGN_GLM.md | GLM | 自建Searxng/情节记忆RAG |
| 5 | MVP_DESIGN_GPT.md | GPT | 两阶段去重/质量反射节点 |
| 6 | MVP_DESIGN_Kimi.md | Kimi | 自主Agent/PushDecision |
| 7 | MVP_DESIGN_Perplexity.md | Perplexity | Web UI集成/MCP三层部署 |
| 8 | MVP_DESIGN_Qwen.md | Qwen | Docker Compose/技术栈细节 |
| 9 | MVP_DESIGN_TRAE.md | TRAE | 推送stdio vs 搜索SSE对比 |

---

## 一、项目定位

**FeedLens 是一个基于 LangGraph 的主动式信息简报 Agent，通过定时自主采集、多源去重、偏好排序，生成个性化简报并持续从用户反馈中学习优化。**

---

## 二、共识点分析

| 共识点 | 内容描述 | 主要来源章节 |
|--------|---------|-------------|
| **1. Agent 架构分层** | 所有文档都认同感知层→大脑层→工具层→记忆层→规划层的五层架构 | Codex-DeepSeek/架构图章、GPT-架构图、Qwen-架构图 |
| **2. LangGraph StateGraph** | 统一采用 StateGraph + TypedDict 定义 State，节点串行+条件分支 | Codex-DeepSeek-State章、DeepSeek-节点边章、GPT-State定义 |
| **3. 工具调用策略** | Function Calling 用于简单/内部工具，MCP 用于外部/可复用服务 | Codex-DeepSeek-工具清单、DeepSeek-工具总览、GPT-工具选择 |
| **4. 四层记忆体系** | 短期(LangGraph State)、长期(ChromaDB)、情节(SQLite)、语义(RAG) | Codex-DeepSeek-记忆层、DeepSeek-记忆设计、GPT-记忆系统 |
| **5. 多因子排序公式** | `final_score = α·sim + β·recency + γ·preference + δ·authority` | Codex-DeepSeek-排序算法、DeepSeek-排序公式、GPT-打分公式 |
| **6. 向量去重核心流程** | 相似度阈值判断 → 重复/相关/独立分类 | Codex-DeepSeek-去重策略、GPT-去重流程、Perplexity-去重设计 |
| **7. Streamlit 前端** | 统一使用 Streamlit 作为 MVP 前端框架 | Qwen-技术栈、DeepSeek-前端、GPT-Streamlit |
| **8. DeepSeek/通义千问 LLM** | 国内可用 API 作为大脑核心 | Codex-DeepSeek-技术栈、Qwen-LLM选型、GPT-LLM |
| **9. ChromaDB 向量库** | 轻量单机向量存储，用于长期记忆和去重 | Codex-DeepSeek-存储层、GPT-ChromaDB、Perplexity-向量库 |
| **10. 反思机制** | 简报生成后有 LLM 审查→不满意则重生成的反思闭环 | Codex-DeepSeek-reflect节点、DeepSeek-反思修正、GPT-reflect_quality |

---

## 三、冲突点对比

| 冲突类型 | 冲突事项 | 阵营A观点及章节 | 阵营B观点及章节 | 核心分歧点 |
|---------|---------|----------------|----------------|-----------|
| **产品逻辑** | P0功能优先级 | **自主决策优先**：Kimi提出"Agent自主决定何时采集/推送"，不是固定日报，强调Goal驱动 | **定时任务优先**：Codex-DeepSeek/DeepSeek采用APScheduler固定时间触发，更像RSS阅读器 | 核心定位差异：信息助手 vs 主动Agent |
| **产品逻辑** | 推送机制 | **即时推送**：Kimi提出"Agent判断有价值就推"，Perplexity提出WebSocket实时推送 | **定时汇总推送**：DeepSeek/GPT采用每日简报打包推送 | 用户打扰频率 vs 信息完整性 |
| **产品逻辑** | 反馈粒度 | **三元反馈**：Codex-DeepSeek用`like/dislike/irrelevant`，Perplexity增加`valuable` | **二元反馈**：Kimi简化为`+1/-1`数值 | 偏好学习精度 vs 操作成本 |
| **技术架构** | MCP Server部署模式 | **全部stdio**：Codex-DeepSeek将搜索也放在stdio，Mimo建议轻量都用stdio | **SSE优先**：DeepSeek/GPT认为搜索服务需SSE便于独立扩缩容 | 简单性 vs 可扩展性 |
| **技术架构** | 去重阈值 | **固定阈值**：Codex-DeepSeek设定`0.85`，Qwen用`0.88` | **双阈值+LLM精排**：GPT设`0.70-0.88`模糊区LLM判断，DeepSeek用两阶段`0.95/0.88` | 准确性 vs 成本 |
| **技术架构** | 数据库操作方式 | **Function Calling直调**：Qwen认为SQLite简单应直接调用 | **MCP封装db_ops**：DeepSeek/GPT建议数据库操作走MCP Server | 耦合度 vs 可复用性 |
| **技术架构** | 搜索服务选型 | **自建Searxng**：GLM明确推荐，可控且国内可用 | **直接API调用**：Codex-DeepSeek直接调Bing API | 自主可控 vs 快速实现 |
| **技术架构** | 推送渠道 | **邮件为主**：Codex-DeepSeek/DeepSeek以邮件为MVP推送 | **Telegram优先**：GLM/Qwen认为Telegram调试方便 | 通用性 vs 便利性 |
| **技术架构** | Embedding模型 | **本地BGE**：GLM/Perplexity推荐bge-small-zh-v1.5，本地零成本 | **云端API**：Codex-DeepSeek倾向DashScope/text-embedding-v2 | 离线能力 vs 效果质量 |
| **技术架构** | State设计粒度 | **粗粒度State**：Kimi只保留`goal/current_plan/observations`等核心字段 | **细粒度State**：DeepSeek/GPT包含`raw_items/deduped_items/ranked_items`完整流水线状态 | 灵活性 vs 可观测性 |

---

## 四、独特点提取

| 亮点名称 | 来源文档-章节 | 价值原因 |
|---------|--------------|---------|
| **1. Planner Agent独立设计** | Kimi-第四章 Planner设计 | 提出用独立的Planner Agent做ReAct决策循环，而非把所有逻辑放在StateGraph节点，更符合Multi-Agent设计理念 |
| **2. PushDecision节点** | Kimi-第九章 自主推送机制 | 不是"每天9点推"，而是Agent判断"这条值得推→立即推"，真正体现Agent自主性 |
| **3. 搜索服务SSE vs 推送stdio对比** | TRAE-工具清单 | 明确说明"搜索用SSE因为需长连接独立扩缩容，推送用stdio因为轻量无需端口"，体现MCP部署决策思考 |
| **4. 跨类别配额机制** | GLM-排序算法/Perplexity-排序设计 | 避免某热门话题霸屏，按用户话题数均分配额（如5话题×4条=20条），提升简报多样性 |
| **5. 来源多样性加分** | Codex-DeepSeek-去重策略 | `source_diversity_bonus = +0.05`，同一事件多源报道比单一来源加权，体现新闻聚合价值 |
| **6. 三层MCP部署架构** | Perplexity-3.2 MCP工具部署 | `web_search`用SSE(长连接)、`save_items`用SSE(可靠写入)、`load_user_profile`用stdio(轻量读取)，分层设计更精细 |
| **7. 情节记忆RAG检索** | GLM-语义记忆/Perplexity-情节记忆 | 情节记忆不仅存SQLite，还生成摘要向量做RAG检索，"上次AI Agent话题时用户喜欢哪些"可被召回 |
| **8. 权重动态A/B测试** | GLM-排序权重/Perplexity-权重建议 | 在Streamlit暴露权重滑块，让用户可实时调整并观察效果，简历可写"带可观测的调参机制" |
| **9. 候选合并+事件判断两步** | GPT-去重策略 | 先规则(URL/编辑距)粗筛，再向量相似度+LLM判断是否同一事件，两阶段策略比单纯阈值更精准 |
| **10. 自建Searxng搜索** | GLM-技术栈选择 | 国内可用、可控、无API成本，适合个人开发者，简历可写"搜索服务自主可控" |
| **11. SQLite WAL模式** | Perplexity-7.数据模型 | 开启WAL提升并发读写体验，体现数据库工程细节 |
| **12. 情节记忆失败模式检索** | Perplexity-4.情节记忆 | 不仅按时间查，还按"相似失败模式"查询，帮助Agent避免重复踩坑 |
| **13. Docker Compose一键部署** | Qwen-技术栈 | agent + web_search MCP + Searxng 一键起服务，简历可写"容器化部署" |
| **14. reflect最多3次重试** | GPT-2.2关键边逻辑 | 设置`max_retry=3`防死循环，体现工程健壮性设计 |
| **15. 用户画像embedding** | DeepSeek-长期记忆 | 不仅存用户点赞的条目，还生成用户画像向量用于相似度计算，更个性化 |
