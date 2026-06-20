# FeedLens — 智能信息简报 Agent MVP 设计文档

> **版本**：MVP | **日期**：2026-06-20 | **状态**：✅ 已完成** **

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

FeedLens 是一个**主动式信息聚合 Agent 系统**。它不是被动问答工具，也不是 cron + pipeline，而是能**自主规划、调度子 Agent、定时执行、个性化筛选**的多 Agent 智能体系统。

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

1. 用户输入一个长期关注目标（如「AI Agent 技术进展」），系统通过 LLM 自动提取结构化字段（关注领域、关键词、推荐 RSS 源）。
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
    │   ┌── 采集 Agent（条件触发补充搜索）
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
| **采集 Agent**                        | RSS采集 + 搜索补充 + 元数据提取 + 标准化 | ❌ 条件触发（MVP简化）                   | fetch\_rss(FC) + search\_web(MCP SSE) + enrich\_metadata(FC) + normalize\_items(FC) |
| **排序 Agent**                        | 智能去重 + 偏好排序 + 记忆辅助         | ✅ Think→Act→Observe 循环          | deduplicate(FC) + rank\_items(FC) + vector\_search(FC) + db\_read(FC)               |
| **简报 Agent**                        | 简报生成 + 质量审查                | ❌ 线性流程（一次生成+审查）                 | generate\_briefing(FC) + brief\_quality\_check(FC)                                  |
| **反馈 Agent** (异步)                   | 反馈处理 + 偏好向量更新              | ❌ 单次执行                          | update\_preference(FC) + vector\_add(FC) + db\_write(FC)                            |

> **MVP 简化说明**：采集 Agent 内部未实现独立 ReAct 循环，补充搜索由主 Agent 的 Planner 统一决策后条件触发（`collected_items < 5` 时自动补充）。这是 MVP 阶段的合理简化，不影响整体架构运行。

***

## 3. 功能模块设计

### 3.1 设计原则与范围界定

**优先级体系**：

| 优先级    | 定义            | MVP 约束   |
| ------ | ------------- | -------- |
| **P0** | 自主决策闭环骨架，缺一不可 | 不可裁剪     |
| **P1** | 首版增强，深化差异化价值  | 尽量实现，可裁剪 |
| **P2** | 后续迭代方向，预留扩展点  | MVP 不实现  |

**P0 核心叙事——Planner 自主编排能力**：

FeedLens 的 P0 核心是 **planner 节点的自主编排能力**。planner 通过 ReAct 循环自主决定本轮调用哪些子 Agent、什么顺序、是否需要补充数据。

| 决策场景     | planner 编排                                                                  | 涉及模块        | 说明                    |
| -------- | --------------------------------------------------------------------------- | ----------- | --------------------- |
| ① 正常每日简报 | `[Collection → Ranking → Briefing]`                                         | 采集+排序+简报    | 标准编排                  |
| ② 采集不足   | `[Collection → (Observe: items<5) → Collection(补充搜索) → Ranking → Briefing]` | 采集+排序+简报    | 观察采集不够→补充搜索           |
| ③ 排序不理想  | `[Collection → Ranking → (Observe: 偏好匹配低) → Ranking(调参) → Briefing]`        | 排序(ReAct)   | 观察排序不佳→调参重排           |
| ④ 重大事件推送 | `[Collection → Ranking → Briefing → PushNow]`                               | 采集+排序+简报+推送 | 发现重大事件，直接推送           |
| ⑤ 跳过采集   | `[Ranking → Briefing]`                                                      | 排序+简报       | **MVP未实现**：使用上轮采集结果   |
| ⑥ 跳过简报   | `[Collection → Ranking → Push摘要]`                                           | 采集+排序+推送    | **MVP未实现**：内容太多不做详细简报 |
| ⑦ 空数据回退  | `[Collection → (Observe: 0 items) → Collection(扩大时间窗)]`                     | 采集          | 采集结果为空，扩大时间窗重采        |

> **注意**：场景⑤（跳过采集）和⑥（跳过简报）在 Planner System Prompt 中有描述，但代码注释明确标记"MVP 约束：不实现 skip\_collection / skip\_briefing 跳过逻辑"。当前版本仅实现①②③④⑦。

### 3.2 P0 核心功能

#### 3.2.1 主 Agent — Coordinator + Planner

**职责**：自主规划本轮执行策略，调度子 Agent，审查结果质量。

**StateGraph 流程**：

```
understand_intent → planner → invoke_sub_agent → observe_results
         ↑                                              ↓
         └────────── ReAct 循环（最多 3 次）─────────────┘
                                                            ↓
                              coordinator_reflect → push_notification → update_memory → END
```

**核心节点**：

| 节点                         | 职责                                                        |
| -------------------------- | --------------------------------------------------------- |
| `understand_intent_node`   | 识别触发类型，加载/提取 structured\_goal，生成 goal\_embedding          |
| `planner_node`             | LLM 自主编排，输出 sub\_agent\_plan + push\_immediate            |
| `invoke_sub_agent_node`    | 按 plan 顺序调度子 Agent，通过 `run_with_isolation` 隔离错误           |
| `observe_results_node`     | 评估采集/排序/简报质量，输出 needs\_retry + suggested\_action          |
| `coordinator_reflect_node` | 三维度审查（completeness / dedup\_quality / traceability）+ 矛盾检查 |
| `push_notification_node`   | MCP stdio 推送简报                                            |
| `update_memory_node`       | 写入执行日志 + 保存简报 + 更新 ChromaDB 偏好向量                          |

**Planner 上下文构建**（`_build_planner_context`）：

```python
{
    "trigger": state.trigger_type,
    "goal": state.goal_text,
    "react_cycle": state.react_cycle_count,
    "collection": {"count": len(collected_items), "search_supplemented": bool},
    "ranking": {"count": len(ranked_items), "top_score": float},
    "briefing": {"quality": state.brief_quality},
    "last_observation": state.observation_result,
}
```

**降级策略**：LLM 调用失败时回退标准三板斧 `[Collection → Ranking → Briefing]`；react\_cycle >= 2 时收敛为 `[Ranking → Briefing]`。

#### 3.2.2 子 Agent — 采集 Agent

**职责**：从多个信息源采集最新内容，条件触发搜索补充。

**StateGraph 流程**：

```
fetch_rss → enrich_metadata → normalize_items
```

> **MVP 简化**：采集 Agent 内部**无 ReAct 循环**。补充搜索由主 Agent Planner 统一决策，通过 `search_web_node` 条件触发（`collected_items < 5` 时执行）。

| 子功能      | 设计决策                                                              |
| -------- | ----------------------------------------------------------------- |
| RSS 采集   | `feedparser` 并行采集，`max_workers=5`                                 |
| 搜索补充     | `SearchMCPClient` (SSE :8100)，`asyncio.run` 驱动异步客户端兼容同步 LangGraph |
| 元数据提取    | `enrich_metadata`：LLM 提取 category / keywords / importance         |
| 条目标准化    | `normalize_items`：统一字段格式                                          |
| SSE 断线降级 | 异常时返回原始数据，不阻塞流程                                                   |

**采集策略**：

- 三路优先级获取 RSS 源：`sources` 表（用户配置）→ `structured_goal.preferred_sources` → `DEFAULT_RSS_SOURCES`（兜底）
- 搜索查询构建：`topics[:3]` → `keywords[:3]` → `goal_text[:50]`

#### 3.2.3 子 Agent — 排序 Agent

**职责**：智能去重 + 偏好排序，具备 ReAct 循环自主判断排序质量。

**StateGraph 流程**：

```
vector_search → deduplicate → rank_items → (should_rerank?) → rank_items 或 END
```

**去重策略**：

| 相似度范围        | 处理方式              |
| ------------ | ----------------- |
| ≥ 0.88       | 直接判定为重复，保留一条代表    |
| ≤ 0.70       | 判定为不重复，全部保留       |
| 0.70 \~ 0.88 | 模糊区间，调用 LLM 做二元判断 |
| 超限（>20 对）    | 按 0.80 硬判         |

**排序公式**：

```
final_score = w₁ · similarity + w₂ · recency + w₃ · preference + w₄ · importance
```

| 因子           | 含义            | 计算方式                                                                                          |
| ------------ | ------------- | --------------------------------------------------------------------------------------------- |
| `similarity` | 内容与用户关注领域的相似度 | `cosine(item_embedding, goal_embedding)`                                                      |
| `recency`    | 时间新鲜度         | `exp(-Δt / 24h)`                                                                              |
| `preference` | 用户偏好匹配度       | 冷启动：`similarity` 代理；有反馈：`cosine(item, v_like) - cosine(item, v_dislike)` 归一化 + feedback\_bias |
| `importance` | 新闻重要性         | LLM 1-5 分归一化至 0-1：`(score - 1) / 4`                                                           |

**权重动态切换**（`config.yaml` 配置）：

| 阶段  | 条件       | 权重配置                                                            |
| --- | -------- | --------------------------------------------------------------- |
| 冷启动 | 反馈 < 3 条 | similarity=0.40, recency=0.25, preference=0.10, importance=0.25 |
| 有反馈 | 反馈 ≥ 3 条 | similarity=0.30, recency=0.20, preference=0.40, importance=0.10 |

**预处理**：

- 时间衰减预筛：Δt > 7 天直接丢弃（`expand_threshold` 时放宽至 14 天）
- 所有因子 Min-Max 归一化至 \[0, 1]
- `feedback_bias`：like +0.15, dislike -0.10, irrelevant -0.15（EMA 更新后归零）

**ReAct 循环**：`should_rerank` 判断——最高分 < 0.3 且重排次数 < 2 时调参重排。

#### 3.2.4 子 Agent — 简报 Agent

**职责**：将排序后的条目组织为结构化简报，含质量审查和重试机制。

**StateGraph 流程**：

```
generate_briefing → brief_quality_check → (score < 0.7 ? retry : Done)
```

**关键设计**：

| 功能             | 实现                                            |
| -------------- | --------------------------------------------- |
| JSON Schema 输出 | `BRIEFING_SCHEMA` 定义结构化 JSON                  |
| 分类组织           | 按 category 分组，组内按 importance 降序               |
| 原始数据回填         | `_backfill_briefing_items` 防止 LLM 改写时间/来源/URL |
| Markdown 渲染    | `_render_markdown` 生成可读简报                     |
| 类似报道计数         | `similar_count` 标注「还有 N 篇类似报道」                |

**质量审查（`brief_quality_check_node`）**：

- LLM 一次性评估 relevance 评分 + 矛盾检测
- 四维评分：completeness / relevance / coherence / score
- 矛盾检查：时间差异 > 7 天 / 重要性差异 > 3 / URL 重复
- score < 0.7 触发重试，最多 2 次

#### 3.2.5 子 Agent — 反馈 Agent（异步）

**职责**：处理用户反馈，更新偏好向量。

**StateGraph 流程**：

```
record_feedback → update_preference → vector_add → cleanup_preference → END
```

**关键设计**：

| 功能      | 实现                                                      |
| ------- | ------------------------------------------------------- |
| 三级反馈    | like / dislike / irrelevant                             |
| EMA 更新  | `v_new = α · v_current + (1-α) · v_feedback`，α = 0.3    |
| 偏好正负分离  | `v_like` / `v_dislike` 分别存储于 ChromaDB `user_preference` |
| 关键词级别偏好 | SQLite `user_preferences` 表记录关键词权重                      |
| 自动清理    | 权重 < 0.1 的偏好项自动删除                                       |
| 异步处理    | `process_feedback_async` Thread 异步执行，不阻塞主 Agent         |

### 3.3 P1 增强功能

| 功能              | 实现状态 | 说明                                          |
| --------------- | ---- | ------------------------------------------- |
| 来源多样性加分         | ✅    | `source_diversity_bonus` 配置项（默认 0，可设 0.05）  |
| 简报链接回填          | ✅    | `_backfill_briefing_items` 确保 URL 不丢失       |
| importance 星级显示 | ✅    | `_format_importance` 格式化为 "X/5"             |
| 执行仪表盘           | ✅    | Streamlit `dashboard_page` 显示成功率/耗时/去重率/反馈率 |

***

## 4. 工具集与 MCP 设计

### 4.1 工具分类

| 工具                     | 类型          | 说明            | 所在文件                            |
| ---------------------- | ----------- | ------------- | ------------------------------- |
| `fetch_rss`            | FC          | 并行 RSS 采集     | `tools/fc_tools.py`             |
| `enrich_metadata`      | FC          | LLM 元数据增强     | `tools/fc_tools.py`             |
| `normalize_items`      | FC          | 字段标准化         | `tools/fc_tools.py`             |
| `deduplicate`          | FC          | 向量去重 + LLM 裁决 | `tools/fc_tools.py`             |
| `rank_items`           | FC          | 多因子加权排序       | `agents/ranking_agent.py`（节点实现） |
| `vector_search`        | FC          | ChromaDB 偏好检索 | `tools/fc_tools.py`             |
| `db_read` / `db_write` | FC          | SQLite 读写     | `tools/fc_tools.py`             |
| `search_web`           | MCP (SSE)   | 搜索补充，:8100    | `mcp_servers/search_server.py`  |
| `push_notification`    | MCP (stdio) | 推送通知          | `mcp_servers/push_server.py`    |

### 4.2 MCP 传输模式

| 服务     | 传输模式        | 理由           |
| ------ | ----------- | ------------ |
| Search | SSE (:8100) | 支持流式返回大搜索结果集 |
| Push   | stdio       | 本地操作，随主进程启停  |

### 4.3 错误隔离

`utils/error_isolation.py` 提供：

- `task_error_isolation` 装饰器 — 任务失败不阻塞流程
- `TaskErrorIsolator` 上下文管理器
- `run_with_isolation` — LangGraph 节点级隔离（主 Agent 调度子 Agent 时使用）

***

## 5. 数据模型

### 5.1 SQLite（11 张表，WAL 模式）

| 表名                 | 用途                        |
| ------------------ | ------------------------- |
| `users`            | 用户基础信息 + structured\_goal |
| `sources`          | RSS 源管理                   |
| `raw_items`        | 原始采集条目                    |
| `deduped_items`    | 去重后条目                     |
| `briefs`           | 生成简报记录                    |
| `feedback`         | 用户反馈记录                    |
| `user_preferences` | 关键词级别偏好权重                 |
| `item_relations`   | 去重关系记录                    |
| `execution_logs`   | 执行日志                      |
| `run_logs`         | 运行统计                      |
| `notifications`    | 推送通知记录                    |

### 5.2 ChromaDB（3 个 Collections）

| 集合                 | 用途                        |
| ------------------ | ------------------------- |
| `feed_items`       | 条目 embedding              |
| `user_preference`  | v\_like / v\_dislike 偏好向量 |
| `domain_knowledge` | 领域知识（长期记忆）                |

### 5.3 状态定义（FeedLensState）

所有 Agent 共享的 TypedDict，关键字段：

```python
# 编排控制
sub_agent_plan: list[dict]      # planner 输出
react_cycle_count: int          # ReAct 循环计数
push_immediate: bool            # 是否立即推送

# 子 Agent 结果
collected_items: list
deduped_items: list
ranked_items: list
ranking_detail: dict
briefing: dict
brief_quality: float

# 观察与审查
observation_result: dict
coordinator_observation: dict

# 反馈与记忆
feedback_results: list
short_term_memory: list
```

***

## 6. 配置项（config.yaml）

```yaml
# 大模型
llm.deepseek.api_key / base_url / model / temperature / max_tokens

# Embedding
embedding.model_name: BAAI/bge-small-zh-v1.5
embedding.device: cpu

# 调度器
scheduler.cron_time: "06:00"
scheduler.timezone: "Asia/Shanghai"

# Agent 约束
agents.max_react_cycles: 3
agents.max_retry: 2

# 排序 & 去重
ranking.dedup_threshold: 0.88
ranking.dedup_llm_lower: 0.70
ranking.max_llm_adjudications: 20
ranking.cold_start_feedback_threshold: 3

# 反馈
feedback.ema_alpha: 0.3
feedback.feedback_bias_positive: 0.15
feedback.feedback_bias_negative: -0.10
feedback.feedback_bias_irrelevant: -0.15

# 权重
weights_cold: {similarity: 0.40, recency: 0.25, preference: 0.10, importance: 0.25}
weights_warm: {similarity: 0.30, recency: 0.20, preference: 0.40, importance: 0.10}

# 重大事件
breaking_news.score_threshold: 0.85
breaking_news.freshness_hours: 2

# 记忆
memory.short_term_window: 15

# 数据
data.retention_days: 30
data.min_items_for_brief: 3
```

***

## 7. 开发约束验证清单

| 约束                      | 设计值                   | 实现验证                                      |
| ----------------------- | --------------------- | ----------------------------------------- |
| max\_react\_cycles      | 3                     | `should_continue_react` 硬上限               |
| max\_llm\_adjudications | 20                    | `deduplicate` 参数控制                        |
| 简报质量阈值                  | < 0.7 重试，最多 2 次       | `brief_quality_check_node` 完整实现           |
| 冷启动阈值                   | 反馈 < 3 条              | `is_cold_start` 判断                        |
| 偏好清理阈值                  | 权重 < 0.1              | `cleanup_preference_node`                 |
| 重大事件阈值                  | score > 0.85 且时效 < 2h | `is_breaking_news` 完整实现                   |
| EMA 平滑系数                | α = 0.3               | `feedback_agent.py` `EMA_ALPHA = 0.3`     |
| 时间衰减预筛                  | Δt > 7 天丢弃            | `rank_items_node` `prefilter_hours = 168` |

***

## 8. 已知限制与后续优化

| 限制                 | 说明                              | 优先级 |
| ------------------ | ------------------------------- | --- |
| MCP SSE 需手动启动      | `search_server.py` 需独立运行        | P1  |
| Streamlit 需手动启动    | `app.py` 需独立运行                  | P1  |
| 单用户模式              | `user_id=1` 硬编码                 | P2  |
| RSS 采集无缓存          | 每次全量拉取                          | P1  |
| 采集 Agent 无独立 ReAct | 简化为条件触发，v2.0 可增强                | P1  |
| 跳过采集/简报未实现         | 场景⑤⑥在 Planner Prompt 有描述但代码未实现  | P1  |
| LLM 压缩未全链路验证       | `memory_manager.py` 有逻辑但未经全链路测试 | P2  |

***

## 9. 文档版本说明

| 版本             | 日期             | 主要变化                               |
| -------------- | -------------- | ---------------------------------- |
| v1.0           | 2026-06-19     | 初始 MVP 设计文档                        |
| v1.1           | 2026-06-19     | 补充算法细化、架构改进、配置调整                   |
| **v1.2 Final** | **2026-06-20** | **合并 v1.0+v1.1，根据实际代码修正偏差，标记已知限制** |

**主要修正内容**：

1. 采集 Agent ReAct 循环 → 修正为"条件触发（MVP 简化）"
2. 7 个 Planner 决策场景 → 明确标注⑤⑥未实现
3. 补充 `importance` 星级显示、简报链接回填、执行仪表盘等 P1 已实现功能
4. 补充错误隔离、原始数据回填、异步反馈等工程化细节
5. 新增"已知限制与后续优化"章节，指导 v2.0 方向

