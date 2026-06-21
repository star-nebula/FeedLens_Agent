# FeedLens MVP 开发 TODO 清单

## 阶段一：项目骨架 + 数据模型 ✅

### 1.1 项目结构搭建

- [x] 创建项目目录结构：`config/`, `models/`, `nodes/`, `tools/`, `utils/`, `agents/`, `ui/`, `mcp/`, `scripts/`
- [x] 创建 `requirements.txt` 依赖列表
- [x] 创建 `config.yaml` 配置文件模板

### 1.2 SQLite 数据模型

- [x] 创建 `models/database.py` - 数据库连接和初始化
- [x] 创建 `scripts/init_db.py` - 表结构初始化脚本（11张表）
- [x] 实现 users 表（goal\_text, topics, keywords, preferred\_sources）
- [x] 实现 sources 表（url, name, category, authority\_score, is\_active）
- [x] 实现 raw\_items 表（title, summary, content, url, published\_at, embedding\_id）
- [x] 实现 deduped\_items 表（representative\_item\_id, similar\_count, category, keywords, importance, source\_diversity\_bonus）
- [x] 实现 item\_relations 表（item\_a\_id, item\_b\_id, relation\_type, similarity\_score, dedup\_method）
- [x] 实现 briefs 表（content\_json, content\_md, quality\_score, quality\_detail, retry\_count）
- [x] 实现 briefing\_items 表（briefing\_id, item\_id, rank, final\_score, is\_highlight）
- [x] 实现 feedback 表（feedback\_type: like/dislike/irrelevant）
- [x] 实现 user\_preferences 表（keyword, weight, vector\_id, feedback\_count）
- [x] 实现 execution\_logs 表（session\_id, turn, event, node\_name, status, duration\_ms, metadata）
- [x] 实现 run\_logs 表（trigger\_type, items\_collected, items\_deduped, dedup\_rate, brief\_quality\_score）

### 1.3 ChromaDB 向量模型

- [x] 创建 `models/vector_store.py` - ChromaDB 连接和操作封装
- [x] 初始化 feed\_items 集合（title, content, embedding, metadata）
- [x] 初始化 user\_preference 集合（user\_id, like\_embedding, dislike\_embedding）
- [x] 初始化 domain\_knowledge 集合（topic, content, embedding, seed\_flag）

### 1.4 LLM Provider 抽象

- [x] 创建 `utils/llm_provider.py` - LLMProvider 抽象接口
- [x] 实现 `DeepSeekProvider` - DeepSeek Chat 调用封装
- [x] 预留 fallback 扩展点

### 1.5 Embedding 模型加载

- [x] 创建 `utils/embedding.py` - bge-small-zh-v1.5 模型加载和推理封装
- [x] 验证推理速度 < 100ms/条（需模型环境就绪后执行）：推理速度: 6.73 ms/条

### 1.6 LangGraph StateGraph 骨架

- [x] 创建 `agents/state.py` - FeedLensState TypedDict 定义
- [x] 创建 `agents/main_agent.py` - 主 Agent StateGraph 骨架
- [x] 创建 `agents/collection_agent.py` - 采集 Agent StateGraph 骨架
- [x] 创建 `agents/ranking_agent.py` - 排序 Agent StateGraph 骨架
- [x] 创建 `agents/briefing_agent.py` - 简报 Agent StateGraph 骨架
- [x] 创建 `agents/feedback_agent.py` - 反馈 Agent StateGraph 骨架

***

## 阶段二：信息采集 + 智能去重 ✅

### 2.1 FC 工具实现&#x20;

- [x] 实现 `fetch_rss` - 并行采集多个 RSS 源（feedparser）
- [x] 实现 `enrich_metadata` - LLM 提取 category/keywords/importance
- [x] 实现 `normalize_items` - 统一字段格式化
- [x] 实现 `deduplicate` - 向量去重（0.88阈值 + 0.70-0.88 LLM裁决，上限20对）
- [x] 实现 `db_read` - SQLite 读取
- [x] 实现 `db_write` - SQLite 写入
- [x] 实现 `vector_search` - ChromaDB 相似度检索
- [x] 实现 `vector_add` - ChromaDB 写入向量

### 2.2 MCP Server 实现

- [x] 实现 `search_web` MCP Server（SSE :8100）
- [x] 实现 `push_notification` MCP Server（stdio）

### 2.3 采集 Agent 完整实现

- [x] 实现采集 Agent ReAct 循环（Think→Act→Observe→Think）
- [x] 实现 `fetch_rss` 节点
- [x] 实现 `search_web` 条件触发（items < 5 时补充搜索）
- [x] 实现 `enrich_metadata` 节点
- [x] 实现 `normalize_items` 节点

### 2.4 排序 Agent 去重部分

- [x] 实现 `vector_search` 检索偏好向量
- [x] 实现 `deduplicate` 节点（向量去重 + LLM裁决）
- [x] 实现 `item_relations` 表写入
- [x] 实现空结果回退逻辑（去重后 < 3 条自动回退采集）

### 2.5 主 Agent planner 节点

- [x] 实现 `understand_intent` 节点（识别触发类型 + 结构化提取 + goal\_embedding生成）
- [x] 实现 `planner` 节点（LLM自主编排子Agent，输出 sub\_agent\_plan + reason + push\_immediate）
- [x] 实现 `invoke_sub_agent` 节点（按计划调度子Agent）
- [x] 实现 `observe_results` 节点（评估子Agent输出质量）
- [x] 实现 ReAct 循环（planner→invoke→observe→planner(再思考)）
- [x] 实现循环上限控制（最多3个ReAct循环）

### 2.6 去重阈值校准

- [x] 创建 `scripts/calibrate_dedup.py` 校准脚本
- [x] 标注样本 → P/R/F1 曲线 → 最优阈值输出

***

## 阶段三：偏好排序 + 简报生成

### 3.1 排序 Agent 排序部分

- [x] 实现 `rank_items` 节点（多因子加权排序）
- [x] 实现排序公式：`final_score = w₁·similarity + w₂·recency + w₃·(preference + feedback_bias) + w₄·importance`
- [x] 实现权重动态切换（冷启动 vs 有反馈）
- [x] 实现 similarity 因子（cosine(item\_embedding, goal\_embedding)）
- [x] 实现 recency 因子（exp(-Δt/24h)）
- [x] 实现 preference 因子（cosine(item\_embedding, user\_preference\_vector)）
- [x] 实现 importance 因子（LLM评估1-5分，归一化至0-1）
- [x] 实现 feedback\_bias 叠加（like+0.15, dislike-0.10, irrelevant-0.15）
- [x] 实现时间衰减预筛（τ=24h）
- [x] 实现 Min-Max 归一化至\[0,1]

### 3.2 简报 Agent 完整实现

- [x] 实现 `generate_briefing` 节点（LLM生成结构化JSON简报）
- [x] 实现 `brief_quality_check` 节点（completeness/relevance/coherence/score四维评分 + 矛盾检查）
- [x] 实现简报 JSON Schema 输出
- [x] 实现 items 按 category 分组、组内按 importance 降序
- [x] 实现计数标注（「还有N篇类似报道」）
- [x] 实现 JSON → Markdown 渲染
- [x] 实现质量评分 < 0.7 重试（最多2次）

***

## 阶段四：推送 + 反馈 + 记忆 + P1 增强

### 4.1 主 Agent 收尾节点

- [x] 实现 `coordinator_reflect` 节点（综合质量审查 + 矛盾检查）
- [x] 实现 `push_notification` 节点（调用 MCP stdio）
- [x] 实现 `update_memory` 节点（偏好更新 + 执行日志写入）

### 4.2 推送机制

- [x] 实现 APScheduler CronTrigger 定时触发
- [x] 实现重大事件破例推送（score > 0.85 且时效 < 2h）
- [x] 实现 planner 输出 push\_immediate=true 时立即推送

### 4.3 反馈子 Agent

- [x] 实现 FeedbackAgent StateGraph（异步执行）
- [x] 实现 `update_preference` 节点（EMA更新偏好向量）
- [x] 实现偏好正负分离（v\_like / v\_dislike）
- [x] 实现 feedback\_bias 时序互补机制
- [x] 实现偏好自动清理（权重 < 0.1）

### 4.4 记忆管理

- [x] 实现短期记忆（滑动窗口15轮）
- [x] 实现超窗压缩（LLM压缩写入ChromaDB长期记忆）
- [x] 实现情节记忆（SQLite execution\_logs）

### 4.5 冷启动→偏好自适应切换

- [x] 实现反馈数 ≥ 3 条时权重自动切换（相似度优先 → 偏好优先）

***

## 阶段五：集成测试 + 优化

### 5.1 Streamlit 前端

- [x] 实现首页/简报查看页面（展示最新简报 + 历史简报）
- [x] 实现 Goal 设置页面（输入Goal文本 + 查看结构化字段）
- [x] 实现 RSS 源管理页面（添加/删除/启用）
- [x] 实现反馈记录页面（like/dislike/irrelevant 按钮 + 历史记录）
- [x] 实现执行日志页面（查看Agent运行日志）

### 5.2 集成测试

- [x] 端到端集成测试（Goal设置 → 采集 → 排序 → 简报 → 推送 → 反馈全流程）
- [x] 测试 planner 7个决策场景覆盖
- [x] 测试 ReAct 循环上限控制
- [x] 测试去重阈值和LLM裁决
- [x] 测试权重动态切换
- [x] 测试反馈闭环（偏好更新 → 影响下一轮排序）

### 5.3 日志和监控

- [x] 实现 structlog 结构化日志
- [x] 实现 execution\_logs + run\_logs 正确记录
- [x] 实现任务级错误隔离（单次失败不阻塞下次执行）
- [x] 实现 30 天数据清理（定期清理过期 raw\_items 和 execution\_logs）

### 5.4 性能优化

- [x] 性能基准测试（单次Agent运行 < 60s，Embedding推理 < 100ms/条，排序+简报 < 30s）
- [x] SQLite WAL 模式优化
- [x] RSS 并行采集优化

### 5.5 文档交付

- [x] 更新 README（环境配置、启动命令、依赖列表）
- [x] MVP 设计文档定稿（v1.0 保留，补充 v1.1 改进记录）
- [x] API 接口文档

***

## P1 增强功能（可选）

### P1.1 反思增强

- [ ] coordinator\_reflect 增加三维度审查（完整性/去重遗漏/可追溯性）
- [ ] brief\_quality\_check 矛盾检测规则细化

### P1.2 偏好深化

- [x] 偏好自动清理阈值优化
- [x] 来源多样性加分（+0.05）
- [x] 执行仪表盘（成功率、耗时、去重率、反馈率）

### P1.3 简报风格切换

- [x] 实现 `generate_briefing` 接口 `style` 参数
- [x] 支持 concise / detailed / bullet 风格

***

## 2026-06-20 — MVP 达标度审计 + 修复（第二轮）

**审计结论**：项目约 85-90% 达到 MVP 设计要求，核心能力（planner 自主编排、ReAct、多因子排序、反馈闭环、定时推送）均已落地。下列 P0/P1/P2 缺口已修复。

### 已修复（本批次）

**P0**
- [x] **偏好因子改用真实余弦**：
anking_agent.py warm 路径现用 cosine(item_emb, v_like) - cosine(item_emb, v_dislike) 归一化参与排序，并从 ChromaDB user_preference 集合读取 user_{id}_like/dislike 向量（新增 _load_preference_vectors / _cosine 辅助）。冷启动或偏好未就绪时降级为 similarity 代理。
- [x] **coordinator_reflect 读错 key**：main_agent.py 由 obs.get("brief_quality") 改为 obs.get("briefing_quality", state.get("brief_quality", 0.0))，消除恒为 0.0 的假「简报质量过低」告警。
- [x] **async 节点跑在 sync graph**：collection_agent.py 的 search_web_node 改为同步函数，内部用 syncio.run() 驱动异步 MCP 客户端，避免在 sync .invoke() 中返回协程。
- [x] **错误隔离接入**：main_agent.py invoke_sub_agent_node 改用 utils.error_isolation.run_with_isolation 包装每个子 Agent 调度，单个失败不阻断本轮其余子 Agent。

**P1**
- [x] **Goal 页 LLM 提取接线**：ui/pages/goal_page.py 新增 Goal 输入框 + 「LLM 提取结构化字段」按钮 + 提取结果展示（主题/关键词/推荐 RSS 来源）+「保存 Goal」按钮；修复 _get_llm 错读 config key、_extract_goal_fields 对 str 调 .get() 两个 Bug。
- [x] **is_breaking_news 时区 Bug**：scheduler/push_scheduler.py 统一把带时区 pub_time 转本地 naive datetime 再与 datetime.now() 相减，消除 aware-naive TypeError 导致破例推送静默失效。
- [x] **排序/去重参数改 config 驱动**：
anking_agent.py 权重、冷启动阈值、source_diversity_bonus、feedback_bias 三档、去重  .88/0.70/20 阈值均改为从 config.yaml 读取（新增 _load_ranking_config），不再硬编码。

**P2**
- [x] **FeedLensState 补 eedback_count** 字段（设计要求但原缺失）。

### 验证

- 6 个改动文件语法 + import 全部 OK。
- 	est_feedback_agent.py 8/8、	est_ranking_agent.py 8/8（含真实 Embedding+ChromaDB 偏好余弦链路）。
- 	est_main_agent.py 7/19 → 9/19（coordinator_reflect 审查通过测试因 P0-2 修复转 PASS）。
- 	est_integration.py 端到端管线（ReAct→planner→coordinator_reflect→去重校准）通过。
- 未引入回归；剩余 main_agent/integration 失败为**既存测试 mock 不匹配**（测试 patch gents.*._load_config 但模块从未定义该属性，仅从 utils.config 导入 load_config），与本次修复无关。

### 尚未处理（既存问题，非本次范围）

- [ ] Dashboard 页（dashboard_page.py）未注册到 pp.py、无 
ender()、内容是 P1 指标仪表盘而非设计的「简报阅读 + 三级反馈」页。
- [ ] dedup_hard_threshold: 0.80 未作为真门限实现（超 20 对上限后无脑合并）。
- [ ] EMA 操作数语义（α·current + (1-α)·feedback vs 设计字面 α·current + (1-α)·old）需确认意图。
- [ ] 既存测试 mock 不匹配（_load_config 属性、collected_count/suggested_action 键、planner 动态计划）需修测试以反映真实 API。
- [ ] eedback_agent._update_keyword_preference 的 'feedback_count' dict 访问告警（既存，非阻塞）。
- [ ] 多个源文件 docstring GBK/UTF-8 mojibake（仅影响可读性）。
- [ ] SQLite 表名与设计不一致（goals→users、user_preference→user_preferences、eed_items 拆分），功能等价但命名偏差。

### 记忆库说明

本次尝试按 AGENTS.md 写入 Obsidian 记忆库 E:/BaiduSyncdisk/obsidian/AgentLog，但该路径多次访问超时（疑似 BaiduSyncdisk 同步占用），改记于项目内 docs/TODO.md。


***

## 2026-06-20 — 简报字段修复（时间留空 + 来源单一）

**问题**：简报中每条内容来源都是 BBC、时间字段留空。

### 根因
- **时间留空**：`briefing_agent._build_briefing_prompt` 喂给 LLM 的条目文本里没有 `published_at` 字段，LLM 无法填充；且 `generate_briefing_node` 解析 LLM JSON 后不回填原始结构化字段。
- **来源全 BBC**：`sources` 表 7 个源中 6 个走 `rsshub.app`（当前网络不可达），只有 BBC 能采集；且 source 字段不回填校验，LLM 可能改写丢失来源多样性。

### 已修复（三步）

**方案 A — prompt 补时间**
- [x] `agents/briefing_agent.py` `_build_briefing_prompt` 每条条目新增 `时间: {published_at}` 字段喂给 LLM。

**方案 B — 回填结构化字段**
- [x] 新增 `_build_item_index` / `_backfill_briefing_items`；`generate_briefing_node` 解析 LLM JSON 后按 id 用原始 `ranked_items` 回填 `published_at/source/url/importance/category`，原始缺失时给默认值（`未知时间`/`unknown`/`3`）。

**第①步 — source/url 强制以原始为准**
- [x] `_backfill_briefing_items` 把 `source`/`url` 从「文本类保留 LLM」改为「客观事实字段强制覆盖」，杜绝 LLM 把多源改写成单一来源。

**第②步 — sources 表换可达源**
- [x] `data/feedlens.db` sources 表从 7 个（6 个走不可达 rsshub.app）换成 5 个可达源：36氪 `https://36kr.com/feed`、少数派 `https://sspai.com/feed`、阮一峰周刊 `https://www.ruanyifeng.com/blog/atom.xml`、Solidot `https://www.solidot.org/index.rss`、BBC（备用）。已备份 `data/feedlens.db.bak.sources`。采集验证：国内 4 源拿到 63 条、来自 4 个不同源、published_at 均有真实时间。

**第③步 — known_names 映射更新**
- [x] `tools/fc_tools.py` `_extract_source_name` 的 `known_names` 新增 4 个新源映射，source 字段显示中文名（36氪/少数派/阮一峰周刊/Solidot）而非域名；保留旧 rsshub 映射以便历史数据回显。

### 验证
- 语法/import 全 OK；回填单测通过（LLM 改写来源被纠正回真实来源、空时间被回填）；`test_briefing_agent.py` 12/12 无回归；端到端串联（采集→normalize→回填）多来源 + 中文 source 名 + 时间回填全部正常。
- 注意：网络可达性会波动（BBC 本次反而超时），多源是关键，不依赖单一源。


***

## 2026-06-20 — 简报时间格式 + 来源多样性（分类语言统一）

### 问题
1. **时间格式**：简报显示 `生成时间: 2026-06-20T08:00:00Z`，`T` 和 `Z` 是 ISO-8601 标记，希望显示为 `2026-06-20 08:00:00`。
2. **来源单一**：简报只有 36氪一个来源（采集实际有 5 个源 84 条，来源分布正常）。

### 根因
- **时间格式**：`_render_markdown` 直接输出原始 `published_at` 字符串，无格式化。
- **来源单一**：`enrich_metadata` 的 prompt 要求 LLM 从**英文**列表 `[technology, business, ...]` 选 category，而简报 `DEFAULT_CATEGORIES = ["科技","商业","社会","其他"]` 是**中文**。`_group_by_category` 里 `if item_cat not in categories: item_cat = "其他"` 导致所有英文 category 匹配不上、74 条几乎全部归到「其他」一类。再叠加「取 top-N + 每类只选 1 条主条目」，简报退化为单类单来源，来源分布随 LLM 的 importance 评分波动（某次 36氪分高就全是 36氪）。

### 已修复

**时间格式化**
- [x] `agents/briefing_agent.py` 新增 `_format_datetime` 辅助函数，把 ISO 字符串（`...T...Z` / `...+08:00` / `YYYY-MM-DD HH:MM:SS`）统一格式化为 `YYYY-MM-DD HH:MM:SS`；`_render_markdown` 渲染时间时调用它。

**分类语言统一（方案 1）**
- [x] `tools/fc_tools.py` `build_enrich_prompt` 的 category 列表从英文 `[technology, business, science, entertainment, sports, politics, other]` 改为中文 `[科技, 商业, 社会, 娱乐, 体育, 政治, 其他]`，与 `DEFAULT_CATEGORIES` 对齐。
- [x] 4 处 category 兜底 `"other"` 改为 `"其他"`（enrich_metadata 异常分支、parse_enrich_response 默认返回、normalize_items 默认值）。

### 验证
- 语法 OK；`_format_datetime` 单测全通过（`2026-06-20T08:00:00Z`→`2026-06-20 08:00:00`，兼容带时区/无时区/空值）。
- 真实 LLM 验证：enrich 后 category 全部为中文，20 条样本正确分类 16/20、归到「其他」0/20，条目被正确分到「科技/社会/娱乐」等多个中文类。
- `test_briefing_agent.py` 12/12 无回归。

### 效果
- 时间显示为 `2026-06-20 08:00:00`，无 T/Z。
- 条目不再全堆「其他」一类，分散到多个中文类别；简报按 category 分组、每类选主条目后自然呈现多分类多来源，而非单类单来源。

### 备注
- 来源分布仍会随 LLM 的 importance 评分波动，分类统一已大幅改善；若需更强来源多样性保证，可在 `generate_briefing_node` 取 top-N 时加「同来源最多占 N 条」的去重策略（P1 可选优化，未做）。


***

## 2026-06-20 — importance 显示格式 + planner 自主扩容策略

### importance 显示格式
- **问题**：简报显示 `重要性: 0.8/5`，importance 实际是 0-1 小数却套了 /5 分母。
- **修复**：`agents/briefing_agent.py` 新增 `_format_importance`，把 0-1 换算成 1-5 整数显示（0.8→4/5），渲染处和 prompt 输入处都调用。兼容 0-1 与 1-5 两种输入范围。

### planner 自主扩容策略（简报条目不足时）
- **需求**：简报不足 10 条时，让 agent 自主规划，把已采集但分数不够高的条目也纳入简报（而非重新采集）。
- **实现**（4 处改动，复用现有 ReAct 循环）：
  1. `agents/main_agent.py` `observe_results_node` 增加简报条目数判断：`len(ranked)<10` 时标记 issues + `suggested_action`。区分两种情况——采集足够但排序后少→`expand_threshold`；采集本身就少→`search_expand`。
  2. `agents/main_agent.py` `PLANNER_SYSTEM_PROMPT` 增加扩容策略：简报条目<10且采集足够→调 Ranking 设 `expand_threshold=true` 放宽门槛（不重新采集）；params 可选值补充 `expand_threshold`。
  3. `agents/main_agent.py` `invoke_sub_agent_node` 把 plan 的 `params` 注入 `current_state`，让子 Agent 能读到 `expand_threshold`。
  4. `agents/ranking_agent.py` `rank_items_node` 响应 `expand_threshold`：预筛窗口 7天→14天，截断上限 10→20，纳入稍旧/分数较低的已采集条目。
- **验证**：
  - observe 单测三场景通过（采集15/排序5→expand_threshold；采集2/排序2→search_expand；正常→不重试）。
  - rank_items 单测通过（默认丢弃8天前旧闻+上限10；expand 保留8天前+上限20）。
  - 端到端真实 LLM 验证：observe 检测「简报条目不足5/10」→ planner 自主返回 `{"agent":"Ranking","params":{"expand_threshold":true}}`，理由「采集已足够，无需重新采集，放宽排序门槛」。
  - test_main_agent 9/19（无回归）、test_ranking_agent 8/8、test_briefing_agent 12/12。
- **防无限循环**：靠现有 `max_react_cycles=3` 硬上限兜底。
- **效果**：强化了项目核心卖点「planner 自主规划」——planner 不只会重试采集，还会自主调整排序策略。


## 2026-06-21 — Planner 预判观察脚本 + 集成测试修复

### 新增：scripts/observe_planner.py
- 用途：单独运行 planner_node（真实 LLM），针对 5 个典型状态打印 LLM 原始返回 + 解析后的编排计划，直观判断 Planner 是否「主动预判跨 Agent 需求」。
- 观察要点：单次 plan 多 Agent 链式编排、主动注入 params（search_expand/expand_threshold/rerank）、根据 top_score 预判 push_immediate、根据 memory 复用历史经验。
- 关键前提：必须真实 LLM 可达。LLM 失败时走 _fallback_plan（硬编码三段式），看不到任何预判。
- 运行：python scripts/observe_planner.py（全场景）或 --scene 1 单场景。

### 修复：scripts/test_integration.py
- 问题1：test_planner_* 四个场景断言精确中文字符串 reason，但既没 mock LLM 又对不上 fallback 的 reason，网络不通时必然 FAIL。已补上 _get_llm_provider mock。
- 问题2：test_full_pipeline mock 目标 agents.collection_agent._load_config / agents.ranking_agent._load_config 不存在（实际是 load_config），导致 patch 报错。已改为正确目标并补齐 collection_agent 依赖 mock。
- 结果：8/8 通过（DEEPSEEK_API_KEY 置空、无网络环境下）。

### 待跟进
- [ ] 在有网络的真实环境跑 observe_planner.py，记录 DeepSeek 在各场景下的实际预判表现，评估是否需要强化 PLANNER_SYSTEM_PROMPT。
- [ ] 评估是否给 observe_planner.py 增加 memory 注入场景，验证历史经验对预判的影响。
- [ ] 记忆库 E:/BaiduSyncdisk/obsidian/AgentLog 在当前 sandbox 无读写权限，本次会话记忆暂存于项目内 docs/MVP_TODO.md，待环境恢复后同步到记忆库。
