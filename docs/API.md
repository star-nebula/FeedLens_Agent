# FeedLens API 接口文档 (MVP)

> **版本**：MVP | **日期**：2026-06-20 | **状态**：✅ 已完成

***

## 一、Agent 节点接口

### 主 Agent 节点

| 节点                   | 函数                         | 输入 (State 字段)                                                                            | 输出 (State 更新)                                                                     |
| -------------------- | -------------------------- | ---------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| understand\_intent   | `understand_intent_node`   | `goal_text`, `user_id`                                                                   | `trigger_type`, `structured_goal`, `goal_embedding`                               |
| planner              | `planner_node`             | `react_cycle_count`, `observation_result`, `ranked_items`, `collected_items`, `briefing` | `sub_agent_plan`, `push_immediate`, `planner_reason`                              |
| invoke\_sub\_agent   | `invoke_sub_agent_node`    | `sub_agent_plan`                                                                         | `collected_items`, `ranked_items`, `briefing_result`, `briefing`, `brief_quality` |
| observe\_results     | `observe_results_node`     | `collected_items`, `ranked_items`, `ranking_detail`, `briefing`                          | `observation_result`                                                              |
| coordinator\_reflect | `coordinator_reflect_node` | `observation_result`, `ranked_items`, `briefing`                                         | `coordinator_observation`                                                         |
| push\_notification   | `push_notification_node`   | `briefing`, `user_id`, `push_immediate`, `ranked_items`                                  | `push_status`, `push_message`                                                     |
| update\_memory       | `update_memory_node`       | `ranked_items`, `briefing`, `coordinator_observation`                                    | `execution_log`, `status`                                                         |

### 子 Agent 节点

| Agent      | 节点                         | 输入                                                                      | 输出                                                 |
| ---------- | -------------------------- | ----------------------------------------------------------------------- | -------------------------------------------------- |
| Collection | `fetch_rss_node`           | `structured_goal.preferred_sources`                                     | `collected_items`                                  |
| Collection | `search_web_node`          | `collected_items`, `structured_goal`                                    | `collected_items`, `search_supplemented`           |
| Collection | `enrich_metadata_node`     | `collected_items`                                                       | `collected_items` (含 category/keywords/importance) |
| Collection | `normalize_items_node`     | `collected_items`                                                       | `collected_items` (标准化格式)                          |
| Collection | `should_search`            | `collected_items`                                                       | — (条件路由：len<5 → search_web，否则 → enrich_metadata) |
| Ranking    | `vector_search_node`       | `user_id`, `structured_goal`                                            | `user_preferences`, `feedback_history`             |
| Ranking    | `deduplicate_node`         | `collected_items`                                                       | `deduped_items`, `item_relations`                  |
| Ranking    | `rank_items_node`          | `deduped_items`, `goal_embedding`, `feedback_history`, `feedback_count` | `ranked_items`, `ranking_detail`                   |
| Briefing   | `generate_briefing_node`   | `ranked_items`, `goal_text`                                             | `briefing_result`                                  |
| Briefing   | `brief_quality_check_node` | `briefing_result`, `ranked_items`                                       | `briefing`, `brief_quality`                        |
| Briefing   | `should_retry_brief`       | `brief_quality`                                                         | — (条件路由：score<0.7 且 retry_count<2 → `generate_briefing`，否则 `END`) |
| Feedback   | `record_feedback_node`     | `user_id`, `item_id`, `feedback_type`                                   | `feedback_recorded`                                |
| Feedback   | `update_preference_node`   | `user_id`, `item_id`, `feedback_type`                                   | `v_like`, `v_dislike`, `preference_updated`        |
| Feedback   | `vector_add_node`          | `user_id`, `v_like`, `v_dislike`                                        | `vector_added`                                     |
| Feedback   | `cleanup_preference_node`  | `user_id`                                                               | `cleanup_done`, `removed_count`                    |

***

## 二、FC 工具函数

| 函数                | 签名                                                                                                                                                                                                                                        | 说明            |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| `fetch_rss`       | `(source_urls: List[str], max_workers: int = 10, timeout: int = 10) -> List[dict]`                                                                                                                                                        | 并行采集 RSS 源    |
| `enrich_metadata` | `(items: List[dict], llm_provider: LLMProvider, batch_size: int = 5) -> List[dict]`                                                                                                                                                       | LLM 增强元数据     |
| `normalize_items` | `(items: List[dict]) -> List[dict]`                                                                                                                                                                                                       | 统一字段格式化       |
| `deduplicate`     | `(items: List[dict], vector_store: VectorStore, embedding_model: EmbeddingModel, llm_provider: LLMProvider, threshold_high: float = 0.88, threshold_low: float = 0.70, max_llm_adjudications: int = 20) -> Tuple[List[dict], List[dict]]` | 向量去重 + LLM 裁决 |
| `db_read`         | `(db_path: str, query: str, params: tuple) -> List[dict]`                                                                                                                                                                                 | SQLite 读取     |
| `db_write`        | `(db_path: str, query: str, params: tuple) -> int`                                                                                                                                                                                        | SQLite 写入     |
| `vector_search`   | `(persist_dir: str, query_text: str, n_results: int = 10, collection: str = "feed_items") -> dict`                                                                                                                                        | ChromaDB 检索   |
| `vector_add`      | `(persist_dir: str, ids: List[str], documents: List[str], metadatas: List[dict], embeddings: List[List[float]] = None) -> None`                                                                                                           | ChromaDB 写入   |

***

## 三、MCP Server

### search\_web (SSE :8100)

**服务名**：FeedLensSearch\
**工具名**：`search`

| 参数           | 类型     | 默认值 | 说明    |
| ------------ | ------ | --- | ----- |
| query        | string | —   | 搜索关键词 |
| max\_results | int    | 10  | 最大结果数 |

**返回**：`List[{"title": str, "url": str, "snippet": str, "source": str}]`

**数据源**：DuckDuckGo Instant Answer API（无需 API Key），失败时降级为模拟数据

### push\_notification (stdio)

**服务名**：FeedLensPush\
**工具名**：`push`

| 参数        | 类型   | 默认值   | 说明                              |
| --------- | ---- | ----- | ------------------------------- |
| brief     | dict | —     | 简报内容 (title, sections, summary) |
| user\_id  | int  | —     | 用户 ID                           |
| immediate | bool | False | 是否立即推送（重大事件破例）                  |

**返回**：`bool`

**存储位置**：`data/notifications.jsonl`（JSONL 文件，非数据库表）

***

## 四、State 数据结构 (FeedLensState)

### 会话元信息

| 字段             | 类型  | 说明                                        |
| -------------- | --- | ----------------------------------------- |
| `session_id`   | str | 会话 ID                                     |
| `trigger_type` | str | daily\_briefing / manual / breaking\_news |
| `user_id`      | int | 用户 ID（MVP 固定 1）                           |

### 用户 Goal

| 字段                | 类型           | 说明                                                   |
| ----------------- | ------------ | ---------------------------------------------------- |
| `goal_text`       | str          | 用户原始 Goal 文本                                         |
| `structured_goal` | dict         | LLM 提取的结构化字段: {topics, keywords, preferred\_sources} |
| `goal_embedding`  | list\[float] | structured\_goal.topics 拼接后的 embedding (384 维)       |

### 主 Agent 编排控制

| 字段                  | 类型                              | 说明                                  |
| ------------------- | ------------------------------- | ----------------------------------- |
| `messages`          | Annotated\[list, add\_messages] | LangGraph 消息累积                      |
| `sub_agent_plan`    | list\[dict]                     | planner 输出: \[{agent, params, ...}] |
| `react_cycle_count` | int                             | 当前 ReAct 循环计数                       |
| `current_sub_agent` | str                             | 当前被调度的子 Agent 名称                    |
| `planner_reason`    | str                             | planner 决策理由                        |
| `push_immediate`    | bool                            | planner 判断是否需要立即推送                  |

### 子 Agent 结果

| 字段                    | 类型          | 说明                                 |
| --------------------- | ----------- | ---------------------------------- |
| `collected_items`     | list\[dict] | 采集 Agent 输出                        |
| `search_supplemented` | bool        | 是否进行了搜索补充                          |
| `deduped_items`       | list\[dict] | 去重后条目                              |
| `item_relations`      | list\[dict] | 去重关系记录                             |
| `ranked_items`        | list\[dict] | 排序后条目                              |
| `ranking_detail`      | dict        | 排序详情 (各因子得分)                       |
| `briefing_result`     | dict        | 简报完整结构: {briefing, brief\_quality} |
| `briefing`            | dict        | 提取的简报 JSON 内容                      |
| `brief_quality`       | float       | brief\_quality\_check 综合评分         |

### 观察与审查

| 字段                        | 类型   | 说明                                                                                     |
| ------------------------- | ---- | -------------------------------------------------------------------------------------- |
| `observation_result`      | dict | observe\_results 输出: {collection\_ok, ranking\_ok, briefing\_ok, needs\_retry, issues} |
| `coordinator_observation` | dict | coordinator_reflect 综合审查结果（含 6 项检查）：{completeness, dedup_coverage, traceability, dedup_quality, brief_quality, contradictions, issues, dimensions, overall_pass} |

### 推送

| 字段             | 类型  | 说明                      |
| -------------- | --- | ----------------------- |
| `push_status`  | str | pending / sent / failed |
| `push_message` | str | 推送消息                    |

### 反馈

| 字段                 | 类型          | 说明                  |
| ------------------ | ----------- | ------------------- |
| `feedback_results` | list\[dict] | 反馈子 Agent 处理结果      |
| `feedback_count`   | int         | 累计反馈数（用于冷启动/偏好切换判断） |

### 记忆

| 字段                  | 类型          | 说明                         |
| ------------------- | ----------- | -------------------------- |
| `short_term_memory` | list\[dict] | 最近 15 轮摘要                  |
| `execution_log`     | dict        | 当前执行日志（写入 execution\_logs） |

### 错误与状态

| 字段       | 类型             | 说明                           |
| -------- | -------------- | ---------------------------- |
| `error`  | Optional\[str] | 错误信息                         |
| `status` | str            | running / completed / failed |

***

## 五、数据库

### SQLite 表 (11 张)

| 表名                 | 用途                        |
| ------------------ | ------------------------- |
| `users`            | 用户基础信息 + structured\_goal |
| `sources`          | RSS 源管理                   |
| `raw_items`        | 原始采集条目                    |
| `deduped_items`    | 去重后条目                     |
| `item_relations`   | 去重关系记录                    |
| `briefs`           | 生成简报记录                    |
| `briefing_items`   | 简报条目关联（UI 页面查询用，简报 Agent 主流程未写入） |
| `feedback`         | 用户反馈记录                    |
| `user_preferences` | 关键词级别偏好权重                 |
| `execution_logs`   | 执行日志                      |
| `run_logs`         | 运行统计                      |

> **注意**：推送通知存储在 `data/notifications.jsonl` 文件中，非数据库表。

### ChromaDB 集合 (3 个)

| 集合名                | 用途                                |
| ------------------ | --------------------------------- |
| `feed_items`       | 条目向量（去重 + 相似度检索）                  |
| `user_preference`  | 用户偏好向量（v\_like / v\_dislike 正负分离） |
| `domain_knowledge` | 语义记忆种子数据（MVP 手动维护，记忆压缩模块已就绪但主流程未接入） |

***

## 六、排序公式

```
final_score = w₁ · similarity + w₂ · recency + w₃ · preference + w₄ · importance
```

### 因子计算

| 因子           | 计算方式                                                                                          |
| ------------ | --------------------------------------------------------------------------------------------- |
| `similarity` | `cosine(item_embedding, goal_embedding)`                                                      |
| `recency`    | `exp(-Δt / 24h)`                                                                              |
| `preference` | 冷启动：`similarity` 代理；有反馈：`cosine(item, v_like) - cosine(item, v_dislike)` 归一化 + feedback\_bias |
| `importance` | `(LLM 1-5 分 - 1) / 4`                                                                         |

### 权重配置

| 阶段  | 条件       | w₁   | w₂   | w₃   | w₄   |
| --- | -------- | ---- | ---- | ---- | ---- |
| 冷启动 | 反馈 < 3 条 | 0.40 | 0.25 | 0.10 | 0.25 |
| 有反馈 | 反馈 ≥ 3 条 | 0.30 | 0.20 | 0.40 | 0.10 |

### 预处理

- 时间衰减预筛：Δt > 7 天丢弃（`expand_threshold` 时放宽至 14 天）
- 所有因子 Min-Max 归一化至 \[0, 1]
- `feedback_bias`：like +0.15, dislike -0.10, irrelevant -0.15（EMA 更新后归零）

***

## 七、版本说明

| 版本  | 日期         | 说明    |
| --- | ---------- | ----- |
| MVP | 2026-06-20 | MVP版本 |

