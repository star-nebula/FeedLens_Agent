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

