# FeedLens API 接口文档 (v1.0)

## 一、Agent 节点接口

### 主 Agent 节点

| 节点 | 函数 | 输入 (State 字段) | 输出 (State 更新) |
|------|------|------------------|------------------|
| understand_intent | `understand_intent_node` | `goal_text`, `user_id` | `trigger_type`, `structured_goal`, `goal_embedding` |
| planner | `planner_node` | `react_cycle_count`, `observation_result`, `ranked_items` | `sub_agent_plan`, `push_immediate`, `planner_reason` |
| invoke_sub_agent | `invoke_sub_agent_node` | `sub_agent_plan` | `collection_result`, `ranking_result`, `briefing_result` |
| observe_results | `observe_results_node` | `collected_items`, `ranked_items`, `ranking_detail` | `observation_result` |
| coordinator_reflect | `coordinator_reflect_node` | `observation_result`, `ranking_result`, `briefing_result` | `coordinator_observation`, `briefing` |
| push_notification | `push_notification_node` | `briefing`, `user_id`, `push_immediate`, `ranked_items` | `push_status`, `push_message` |
| update_memory | `update_memory_node` | `ranked_items`, `briefing`, `coordinator_observation` | `execution_log`, `status` |

### 子 Agent 节点

| Agent | 节点 | 输入 | 输出 |
|-------|------|------|------|
| Collection | `fetch_rss_node` | `structured_goal.preferred_sources` | `collected_items` |
| Collection | `search_web_node` | `collected_items`, `structured_goal` | `collected_items`, `search_supplemented` |
| Collection | `enrich_metadata_node` | `collected_items` | `collected_items` (含 category/keywords/importance) |
| Collection | `normalize_items_node` | `collected_items` | `collected_items` (标准化格式) |
| Ranking | `vector_search_node` | `user_id`, `structured_goal` | `user_preferences`, `feedback_history` |
| Ranking | `deduplicate_node` | `collected_items` | `collected_items` (去重后), `item_relations` |
| Ranking | `rank_items_node` | `collected_items`, `goal_embedding`, `feedback_history` | `ranked_items`, `ranking_detail` |
| Briefing | `generate_briefing_node` | `ranked_items`, `goal_text` | `briefing`, `briefing_result` |
| Briefing | `brief_quality_check_node` | `briefing`, `ranked_items` | `brief_quality`, `quality_detail` |
| Feedback | `record_feedback_node` | `user_id`, `item_id`, `feedback_type` | `feedback_recorded` |
| Feedback | `update_preference_node` | `user_id`, `item_id`, `feedback_type` | `v_like`, `v_dislike`, `preference_updated` |
| Feedback | `vector_add_node` | `user_id`, `v_like`, `v_dislike` | `vector_added` |
| Feedback | `cleanup_preference_node` | `user_id` | `cleanup_done`, `removed_count` |

## 二、FC 工具函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `fetch_rss` | `(source_urls, max_workers) -> List[dict]` | 并行采集 RSS 源 |
| `enrich_metadata` | `(items, llm_provider, batch_size) -> List[dict]` | LLM 增强元数据 |
| `normalize_items` | `(items) -> List[dict]` | 统一字段格式化 |
| `deduplicate` | `(items, vector_store, embedding_model, llm_provider, threshold_high, threshold_low, max_llm_adjudications) -> (unique_items, duplicate_pairs)` | 向量去重 |
| `db_read` | `(db_path, query, params) -> List[dict]` | SQLite 读取 |
| `db_write` | `(db_path, query, params) -> int` | SQLite 写入 |
| `vector_search` | `(persist_dir, query_text, n_results) -> List[dict]` | ChromaDB 检索 |
| `vector_add` | `(persist_dir, ids, documents, metadatas) -> int` | ChromaDB 写入 |

## 三、MCP Server

### search_web (SSE :8100)

**工具**: `search`

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| query | string | — | 搜索关键词 |
| max_results | int | 10 | 最大结果数 |

**返回**: `List[{"title", "url", "snippet", "source"}]`

### push_notification (stdio)

**工具**: `push`

| 参数 | 类型 | 说明 |
|------|------|------|
| brief | dict | 简报内容 (title, sections, summary) |
| user_id | int | 用户 ID |
| immediate | bool | 是否立即推送 |

**返回**: `bool`

## 四、State 数据结构 (FeedLensState)

核心字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | str | 会话 ID |
| trigger_type | str | daily_briefing / manual / breaking_news |
| user_id | int | 用户 ID（MVP 固定 1） |
| goal_text | str | 用户目标文本 |
| structured_goal | dict | LLM 提取的结构化目标 (topics, keywords, preferred_sources) |
| goal_embedding | list[float] | 目标向量 (384 维) |
| react_cycle_count | int | ReAct 循环计数 |
| sub_agent_plan | list[dict] | Planner 输出的子 Agent 编排计划 |
| collected_items | list[dict] | 采集到的条目 |
| deduped_items | list[dict] | 去重后的条目 |
| ranked_items | list[dict] | 排序后的条目 |
| briefing | dict | 简报 JSON |
| brief_quality | float | 简报质量评分 |
| push_status | str | pending / sent / failed |
| push_immediate | bool | 是否立即推送 |
| observation_result | dict | 观察评估结果 |
| coordinator_observation | dict | 综合审查结果 |
| execution_log | dict | 执行日志 |
| user_preferences | list[dict] | 用户偏好 |
| feedback_history | list[dict] | 反馈历史 |
| short_term_memory | list[dict] | 短期记忆（15 轮） |

## 五、数据库

### SQLite 表 (11 张)

users, sources, raw_items, deduped_items, item_relations, briefs, briefing_items, feedback, user_preferences, execution_logs, run_logs

### ChromaDB 集合 (3 个)

feed_items, user_preference, domain_knowledge

## 六、排序公式

```
final_score = w1 * similarity + w2 * recency + w3 * preference + w4 * importance
```

| 因子 | 计算方式 |
|------|---------|
| similarity | cosine(item_embedding, goal_embedding) |
| recency | exp(-Δt / 24h) |
| preference | cold_start: similarity 代理; 有反馈: feedback_bias 驱动 |
| importance | (LLM 1-5 分) → (score - 1) / 4 |

**权重**:

| 阶段 | w1 | w2 | w3 | w4 |
|------|----|----|----|----|
| 冷启动 (反馈 < 3) | 0.40 | 0.25 | 0.10 | 0.25 |
| 有反馈 (反馈 >= 3) | 0.30 | 0.20 | 0.40 | 0.10 |
