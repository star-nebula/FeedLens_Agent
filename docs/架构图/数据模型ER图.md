# FeedLens 数据模型 ER 图（v3.0）

> 本文档替代 `数据模型ER图.drawio`，以结构化 Markdown 描述 SQLite 11张关系表 + ChromaDB 3个向量Collection 的完整数据模型。

---

## 一、存储架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│ SQLite（WAL 模式） — 11 张关系表                                 │
│                                                                 │
│  users ──1:N── sources ──1:N── raw_items                       │
│    │                            │                               │
│    │1:N                    1:N  │── item_relations              │
│    │                            │                               │
│  briefs ──1:N── briefing_items ──1:N── deduped_items            │
│    │                            │                               │
│    │1:N                    1:N  │                               │
│  feedback ──────────────────────┘                               │
│                                                                 │
│  user_preferences ──vector_id──→ ChromaDB user_preference       │
│  execution_logs  |  run_logs                                    │
├─────────────────────────────────────────────────────────────────┤
│ ChromaDB — 3 个向量 Collection（bge-small-zh-v1.5 Embedding）   │
│                                                                 │
│  feed_items          | user_preference     | domain_knowledge   │
│  (条目向量+去重)      | (偏好向量v_like/v_dislike) | (语义记忆种子) │
└─────────────────────────────────────────────────────────────────┘
```

**跨存储关联**（紫色虚线）：
- `user_preferences.vector_id` → `ChromaDB user_preference` 的 id
- `raw_items.embedding_id` → `ChromaDB feed_items` 的 id

---

## 二、SQLite 关系表详细定义

### 2.1 users — 用户表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 用户ID |
| goal_text | TEXT | — | 用户偏好Goal文本 |
| topics | TEXT (JSON) | — | 关注话题列表 |
| keywords | TEXT (JSON) | — | 关键词列表 |
| preferred_sources | TEXT (JSON) | — | 偏好信息源列表 |
| created_at | TIMESTAMP | — | 创建时间 |

**外键被引用**：users.id 被 sources, briefs, feedback, user_preferences, run_logs 五张表引用。

---

### 2.2 sources — 信息源表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 信息源ID |
| *user_id* | INTEGER | **FK → users** | 所属用户 |
| url | TEXT | — | RSS源URL |
| name | TEXT | — | 源名称 |
| category | TEXT | — | 源分类（科技/财经/…） |
| authority_score | REAL | 0-1 | 权威度评分 |
| is_active | BOOLEAN | — | 是否启用 |

**外键关系**：1个user → N个sources（用户管理多个RSS源）。

---

### 2.3 raw_items — 原始条目表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 条目ID |
| *source_id* | INTEGER | **FK → sources** | 来源信息源 |
| title | TEXT | — | 条目标题 |
| summary | TEXT | — | 条目摘要 |
| content | TEXT | — | 条目正文 |
| url | TEXT | — | 条目链接 |
| published_at | TIMESTAMP | — | 发布时间 |
| collected_at | TIMESTAMP | — | 采集时间 |
| embedding_id | TEXT | → ChromaDB feed_items | 跨存储关联：向量ID |

**外键关系**：
- 1个source → N个raw_items
- raw_items → item_relations (item_a_id / item_b_id)
- raw_items → deduped_items (representative_item_id)

---

### 2.4 item_relations — 条目关系表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 关系ID |
| *item_a_id* | INTEGER | **FK → raw_items** | 条目A |
| *item_b_id* | INTEGER | **FK → raw_items** | 条目B |
| relation_type | TEXT | — | 关系类型：`duplicate_of` / `related_to` / `merged_into` |
| similarity_score | REAL | — | 向量相似度分数 |
| dedup_method | TEXT | — | 去重方法：`vector_threshold` / `llm_adjudication` |

**用途**：记录去重过程中发现的条目间关系，供 deduped_items 表引用。

---

### 2.5 deduped_items — 去重后条目表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 去重条目ID |
| *representative_item_id* | INTEGER | **FK → raw_items** | 代表条目（合并后保留的） |
| similar_count | INTEGER | — | 被合并的相似条目数 |
| category | TEXT | — | 分类（enrich_metadata提取） |
| keywords | TEXT (JSON) | — | 关键词列表 |
| importance | INTEGER | 1-5 | 重要性评分 |
| source_diversity_bonus | REAL | P0:0 | 来源多样性加分 |

**外键关系**：
- 1个raw_item → N个deduped_items (representative)
- deduped_items → briefing_items (item_id)
- deduped_items → feedback (item_id)

---

### 2.6 briefs — 简报表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 简报ID |
| *user_id* | INTEGER | **FK → users** | 所属用户 |
| date | DATE | — | 简报日期 |
| content_json | TEXT (JSON) | — | 简报JSON内容（generate_briefing输出） |
| content_md | TEXT | — | 简报Markdown内容（渲染后） |
| quality_score | REAL | 0-1 | 简报质量分数 |
| quality_detail | TEXT (JSON) | — | 质量评分详情（completeness/relevance/coherence） |
| retry_count | INTEGER | — | reflect重试次数（最大2） |

**外键关系**：
- 1个user → N个briefs
- briefs → briefing_items (briefing_id)
- briefs → feedback (brief_id)

---

### 2.7 briefing_items — 简报条目关联表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 关联ID |
| *briefing_id* | INTEGER | **FK → briefs** | 所属简报 |
| *item_id* | INTEGER | **FK → deduped_items** | 关联的去重条目 |
| rank | INTEGER | — | 简报中的排序位置 |
| final_score | REAL | — | 最终综合分数 |
| is_highlight | BOOLEAN | — | 是否为高亮推荐 |

**用途**：简报与条目的多对多关联，记录每个条目在简报中的排序和分数。

---

### 2.8 feedback — 用户反馈表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 反馈ID |
| *user_id* | INTEGER | **FK → users** | 反馈用户 |
| *brief_id* | INTEGER | **FK → briefs** | 反馈关联的简报 |
| *item_id* | INTEGER | **FK → deduped_items** | 反馈关联的条目 |
| feedback_type | TEXT | **CHECK** (like/dislike/irrelevant) | 反馈类型 |
| created_at | TIMESTAMP | — | 反馈时间 |

**反馈权重**：
- `like` → +0.15
- `dislike` → -0.10
- `irrelevant` → -0.15

---

### 2.9 user_preferences — 用户偏好表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 偏好ID |
| *user_id* | INTEGER | **FK → users** | 所属用户 |
| keyword | TEXT | — | 偏好关键词 |
| weight | REAL | <0.1自动清理 | 偏好权重 |
| vector_id | TEXT | → ChromaDB user_preference | 跨存储关联：偏好向量ID |
| feedback_count | INTEGER | — | 该关键词收到的反馈次数 |
| updated_at | TIMESTAMP | — | 最后更新时间 |

**跨存储关联**：`vector_id` 指向 ChromaDB `user_preference` Collection 中的向量记录。

---

### 2.10 execution_logs — 执行日志表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 日志ID |
| session_id | TEXT | — | Session标识 |
| turn | INTEGER | — | Turn序号 |
| event | TEXT | — | Event描述 |
| node_name | TEXT | — | StateGraph节点名 |
| status | TEXT | — | success / error / skipped |
| duration_ms | INTEGER | — | 执行耗时(ms) |

**用途**：Harness工程的Session/Turn/Event三层日志记录。

---

### 2.11 run_logs — 运行日志表

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| **id** | INTEGER | **PK** | 运行ID |
| *user_id* | INTEGER | **FK → users** | 所属用户 |
| trigger_type | TEXT | — | daily_briefing / manual_search |
| items_collected | INTEGER | — | 采集条目数 |
| items_deduped | INTEGER | — | 去重后条目数 |
| dedup_rate | REAL | — | 去重率 |
| brief_quality_score | REAL | — | 简报质量分数 |
| duration_ms | INTEGER | — | 总运行耗时(ms) |

**用途**：每次完整运行（一次 `agent.invoke()`）的汇总指标。

---

## 三、ChromaDB 向量Collection详细定义

### 3.1 feed_items Collection

| 属性 | 值 |
|------|---|
| **名称** | `feed_items` |
| **用途** | 条目向量检索与去重 |
| **关联** | `raw_items.embedding_id` → `feed_items.id` |

**核心字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | str | 向量记录ID |
| title | str | 条目标题 |
| content | str | 条目正文 |
| embedding | float[] | bge-small-zh-v1.5 向量 |

**metadata**：

| 字段 | 类型 | 说明 |
|------|------|------|
| category | str | 分类 |
| source | str | 来源 |
| importance | int | 重要性(1-5) |
| date | str | 采集日期 |

---

### 3.2 user_preference Collection

| 属性 | 值 |
|------|---|
| **名称** | `user_preference` |
| **用途** | 用户长期偏好向量（正负分离） |
| **关联** | `user_preferences.vector_id` → `user_preference.id` |
| **机制** | EMA平滑更新，v_like / v_dislike 分离维护 |

**核心字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | int | 用户ID |
| like_embedding | float[] | 喜好偏好向量 (v_like) |
| dislike_embedding | float[] | 不喜好偏好向量 (v_dislike) |
| updated_at | str | 最后更新时间 |

**更新机制**：
- 反馈触发 `update_preference` → EMA平滑计算新向量
- 正负分离维护：like反馈更新 v_like，dislike反馈更新 v_dislike
- 反馈bias归零后EMA接管（防止初期反馈过度影响）

---

### 3.3 domain_knowledge Collection

| 属性 | 值 |
|------|---|
| **名称** | `domain_knowledge` |
| **用途** | 语义记忆种子数据 |
| **机制** | MVP阶段手动维护种子数据，数据积累后逐步自动补充 |

**核心字段**：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | str | 记录ID |
| topic | str | 主题 |
| content | str | 内容 |
| embedding | float[] | 向量 |
| seed_flag | bool | 是否为种子数据 |

**用途说明**：冷启动阶段提供初始权重参考，避免排序Agent在无反馈时完全随机排序。

---

## 四、外键关系汇总

### SQLite内部关系

| 父表 | 子表 | 关系 | FK字段 |
|------|------|------|--------|
| users | sources | 1:N | `sources.user_id` |
| users | briefs | 1:N | `briefs.user_id` |
| users | feedback | 1:N | `feedback.user_id` |
| users | user_preferences | 1:N | `user_preferences.user_id` |
| users | run_logs | 1:N | `run_logs.user_id` |
| sources | raw_items | 1:N | `raw_items.source_id` |
| raw_items | item_relations | 1:N | `item_relations.item_a_id`, `item_b_id` |
| raw_items | deduped_items | 1:N | `deduped_items.representative_item_id` |
| briefs | briefing_items | 1:N | `briefing_items.briefing_id` |
| deduped_items | briefing_items | 1:N | `briefing_items.item_id` |
| briefs | feedback | 1:N | `feedback.brief_id` |
| deduped_items | feedback | 1:N | `feedback.item_id` |

### 跨存储关联（SQLite → ChromaDB）

| SQLite表 | SQLite字段 | ChromaDB Collection | 说明 |
|----------|-----------|---------------------|------|
| raw_items | embedding_id | feed_items | 条目向量ID |
| user_preferences | vector_id | user_preference | 偏好向量ID |

---

## 五、关键设计要点

1. **SQLite WAL模式** — 支持并发读写，避免写锁阻塞读取
2. **ChromaDB进程内SDK** — 无IPC开销，deduplicate/vector_search 直接调用
3. **跨存储关联用文本ID** — SQLite用TEXT字段存储ChromaDB的向量ID，不做强FK约束
4. **权重<0.1自动清理** — user_preferences中低权重偏好自动删除，防止偏好膨胀
5. **正负偏好分离** — user_preference Collection 维护 v_like 和 v_dislike 两个向量
6. **domain_knowledge种子数据** — MVP阶段手动维护，为冷启动排序提供初始参考
7. **execution_logs三层记录** — Session/Turn/Event完整追踪
