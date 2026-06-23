## 1. 系统架构图

FeedLens 可以拆成五层：感知层负责接收 RSS/搜索结果/用户反馈；大脑负责基于 LLM 做规划、筛选和摘要决策；工具层负责抓取、去重、向量化、推送；记忆层负责用户偏好、历史事件和长期画像；规划层用 LangGraph 串起定时执行、ReAct 和反思。 [api-docs.deepseek](https://api-docs.deepseek.com/zh-cn/guides/tool_calls)

```text
┌─────────────────────────────────────────────────────────────────────┐
│                           FeedLens Web UI                            │
│                        Streamlit Dashboard                           │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           感知层 Perception                          │
│  - RSS feeds                                                        │
│  - 搜索结果                                                         │
│  - 用户点赞/踩反馈                                                  │
│  - 定时任务触发器                                                   │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                             大脑 Brain                               │
│  - LLM 意图理解                                                     │
│  - 信息相关性判断                                                   │
│  - 简报结构化生成                                                   │
│  - 工具调用决策                                                     │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        规划层 Planning / LangGraph                   │
│  - Schedule node                                                    │
│  - Collect node                                                     │
│  - Normalize node                                                   │
│  - Dedup node                                                       │
│  - Rank node                                                        │
│  - Summarize node                                                   │
│  - Reflect node                                                     │
│  - Notify node                                                      │
└─────────────────────────────────────────────────────────────────────┘
                              │
      ┌───────────────────────┼────────────────────────┐
      ▼                       ▼                        ▼
┌───────────────┐   ┌──────────────────┐   ┌─────────────────────────┐
│   工具层 Tools │   │   记忆层 Memory  │   │   外部服务 / 数据源      │
│ - RSS fetch    │   │ - 短期记忆       │   │ - RSS 源                │
│ - Web search   │   │ - 长期记忆       │   │ - 搜索引擎              │
│ - Embed        │   │ - 情节记忆       │   │ - Telegram/Email/Push   │
│ - Notify       │   │ - 语义记忆       │   │ - SQLite + ChromaDB     │
└───────────────┘   └──────────────────┘   └─────────────────────────┘
```

***

## 2. Agent 工作流设计

LangGraph 的核心是 `StateGraph`，状态用 `TypedDict` 定义，节点对共享状态做增量更新。 [medium](https://medium.com/ai-agents/langgraph-for-beginners-part-4-stategraph-794004555369)

### State 设计

```python
from typing_extensions import TypedDict
from typing import List, Dict, Optional, Any

class FeedLensState(TypedDict, total=False):
    session_id: str
    user_id: str
    run_id: str

    user_profile: Dict[str, Any]
    topics: List[str]
    sources: List[Dict[str, Any]]

    raw_items: List[Dict[str, Any]]
    normalized_items: List[Dict[str, Any]]
    deduped_items: List[Dict[str, Any]]
    scored_items: List[Dict[str, Any]]

    brief_sections: List[Dict[str, Any]]
    notification_payload: Dict[str, Any]

    user_feedback: List[Dict[str, Any]]
    reflection_notes: List[str]

    errors: List[str]
    status: str
    updated_at: str
```

### LangGraph 节点与边

```text
START
  → load_profile
  → load_sources
  → collect_items
  → normalize_items
  → embed_items
  → dedup_items
  → score_items
  → summarize_brief
  → reflect_brief
  → notify_user
  → save_run
  → END
```

### 节点职责

- `load_profile`：从长期记忆和 SQLite 读用户偏好、主题、历史反馈。 [docs.agno](https://docs.agno.com/knowledge/vector-stores/chroma/overview)
- `load_sources`：读取用户订阅的 RSS/搜索配置。
- `collect_items`：拉取 RSS、搜索结果，形成原始条目。
- `normalize_items`：统一字段结构，标准化标题、摘要、时间、来源。
- `embed_items`：为标题+摘要生成 embedding，写入 ChromaDB。
- `dedup_items`：先规则后向量去重，合并同事件多来源报道。 [medium](https://medium.com/@bella.belgarokova_79633/mastering-chromadb-for-semantic-search-a-comprehensive-guide-875a7f42c39e)
- `score_items`：按主题相似度、时间衰减、偏好权重排序。
- `summarize_brief`：生成结构化简报，按分类输出。
- `reflect_brief`：做反思审查，检查是否重复、是否过长、是否漏掉高分内容。
- `notify_user`：把简报推送到 Streamlit 页面或消息渠道。
- `save_run`：写入情节记忆和反馈闭环数据。

### 分支逻辑

- 若 `collect_items` 返回空结果，则直接进入 `save_run`，并标记 `status=empty`.
- 若 `dedup_items` 后高分条目不足，允许 `search_web` 补抓一次。
- 若 `reflect_brief` 发现重复率过高或摘要太长，则回到 `summarize_brief` 进行一次修正。

***

## 3. 工具清单

下面按 MVP 必需工具列出。选择原则是：简单、参数明确、频繁内部调用的工具优先 Function Calling；跨进程复用、独立部署、未来可扩展的工具优先 MCP。 [qwen-ai](https://qwen-ai.chat/docs/api/)

### 3.1 工具总表

| name | description | parameters | 调用方式 | 理由 |
|---|---|---|---|---|
| `fetch_rss_items` | 拉取 RSS/Atom 源最新条目 | `source_url, since, max_items` | Function Calling | 参数简单、低延迟、与 Agent 同进程即可 |
| `web_search_items` | 搜索关键词相关新闻/文章 | `query, max_results, recency_days` | MCP | 搜索服务适合独立部署和复用，便于后续替换为自建搜索后端 |
| `normalize_item` | 标准化条目字段 | `raw_item` | Function Calling | 纯数据转换，简单直接 |
| `embed_texts` | 生成向量并写入 ChromaDB | `texts, ids, metadatas` | Function Calling | 内部计算和本地存储，参数固定 |
| `dedup_candidates` | 计算重复候选和簇 | `item_ids, threshold` | Function Calling | 逻辑在本地，便于快速迭代阈值 |
| `save_items` | 写入 SQLite 条目表 | `items` | MCP | 数据库操作建议与 Agent 解耦，后续前后端都可复用 |
| `load_user_profile` | 读取用户画像和偏好 | `user_id` | MCP | 多处都会读，适合独立 service 化 |
| `save_feedback` | 写入点赞/踩反馈 | `user_id, item_id, rating, reason` | MCP | 需要可靠写入和审计 |
| `generate_brief` | 生成结构化简报文本 | `items, profile, brief_style` | Function Calling | LLM 直接负责生成，简单封装即可 |
| `send_notification` | 推送简报到渠道 | `user_id, payload, channel` | MCP | 通知系统适合独立部署和异步重试 |
| `write_run_log` | 写入情节记忆/运行日志 | `run_info` | MCP | 便于统一审计和跨 Agent 共享 |

### 3.2 MCP 工具部署建议

#### `web_search_items`
- **部署方式**：SSE。
- **理由**：搜索服务可能需要长连接、异步返回、独立扩缩容，SSE 比 stdio 更适合服务化部署。 [docs.ag2](https://docs.ag2.ai/latest/docs/user-guide/advanced-concepts/tools/mcp/client/)
- **接口定义**：
  - `POST /search` 或工具名 `search_web`
  - 入参：`query`, `max_results`, `recency_days`
  - 出参：`[{title, url, snippet, published_at, source}]`

#### `save_items`
- **部署方式**：stdio 或 SSE 都可，MVP 建议 SSE。
- **理由**：虽然是本地 SQLite，但把数据库操作包在 MCP 内，可以保持 Agent 层纯净，后续前端、定时任务、后台 worker 都能复用同一套接口。 [docs.python](https://docs.python.org/3/library/sqlite3.html)
- **接口定义**：
  - `save_items(items: List[Item]) -> {inserted_ids, updated_ids}`

#### `load_user_profile`
- **部署方式**：stdio。
- **理由**：本地读取为主，开发期调试简单。
- **接口定义**：
  - `get_profile(user_id) -> {topics, weights, muted_keywords, source_prefs}`

#### `save_feedback`
- **部署方式**：stdio 或 SSE，推荐 SSE。
- **理由**：写入要可靠，未来可以接事件总线。
- **接口定义**：
  - `create_feedback(user_id, item_id, rating, reason, context)`

#### `send_notification`
- **部署方式**：SSE。
- **理由**：天然异步、需要重试、可能接多个渠道。
- **接口定义**：
  - `send(channel, user_id, title, body, payload)`

***

## 4. 记忆系统设计

LangGraph 负责流程，记忆系统负责“这类用户、这类条目、这类任务过去怎么处理”。短期记忆放在运行状态中，长期记忆和情节记忆分别存 ChromaDB 和 SQLite，形成可检索、可追溯、可更新的闭环。 [docs.langchain](https://docs.langchain.com/oss/python/langgraph/graph-api)

### 短期记忆
- **存储**：LangGraph State + Redis/内存缓存。
- **内容**：当前会话里用户刚说过的偏好、当前 run 的中间条目、临时反思结果。
- **检索**：按滑动窗口保留最近 10–20 轮；同一 run 内直接从 state 读。
- **更新**：每个节点返回增量状态，超窗内容进入总结压缩。

### 长期记忆
- **存储**：ChromaDB。
- **内容**：用户偏好文本、历史反馈摘要、常见高价值主题、曾经喜欢的内容表示向量。 [docs.agno](https://docs.agno.com/knowledge/vector-stores/chroma/overview)
- **检索**：用当前候选条目 embedding 检索最相似的用户偏好片段，返回 top-k。
- **更新**：点赞/踩后，把“用户偏好变化摘要”写成短文本并重嵌入；定期做合并去重。

### 情节记忆
- **存储**：SQLite `run_logs` / `brief_versions` 表。
- **内容**：每次执行的输入、输出、异常、反思结论、失败原因、修正动作。
- **检索**：按 `user_id + topic + time` 过滤，或按“相似失败模式”查询。
- **更新**：每次 run 结束写入一条，反思节点额外写一条 `reflection_note`。

### 语义记忆
- **存储**：ChromaDB 的另一 collection，或与长期记忆同库但 metadata 区分。
- **内容**：领域知识、常见事件类型、分类规则、排序策略提示。
- **检索**：当模型判断当前主题属于“新领域”或“难分类”时触发 RAG。
- **更新**：从高质量简报和人工修正中抽取知识短句，定期沉淀。

***

## 5. 排序算法设计

排序目标是：既要“相关”，又要“新”，还要“符合用户口味”。建议用一个可解释的线性加权公式，便于你在简历里讲清楚，也方便后续调参。 [api-docs.deepseek](https://api-docs.deepseek.com/zh-cn/guides/tool_calls)

### 打分公式

\[
score(item) = w_1 \cdot sim(item, profile) + w_2 \cdot freshness(item) + w_3 \cdot preference(item) + w_4 \cdot source\_quality(item) - w_5 \cdot duplicate\_penalty(item)
\]

### 各项定义

- `sim(item, profile)`：条目 embedding 与用户画像 embedding 的余弦相似度。
- `freshness(item)`：时间衰减函数，建议 \(\exp(-\Delta t / \tau)\)。
- `preference(item)`：来自历史点赞/踩学习到的偏好分数。
- `source_quality(item)`：来源可信度与历史点击率。
- `duplicate_penalty(item)`：与同簇条目过于接近时的惩罚。

### 权重建议

- `w1 = 0.40`，语义相关性最重要。
- `w2 = 0.25`，信息简报必须体现“新鲜”。
- `w3 = 0.25`，体现个性化。
- `w4 = 0.10`，用于微调来源质量。
- `w5 = 0.30`，重复惩罚单独扣分。

### 实现建议
- 先把所有条目归一化到 `[0,1]`。
- 用简单线性模型起步，不要一开始就上复杂排序模型。
- 后续可以基于用户反馈做在线更新，把 `w3` 按用户点击率动态调整。

***

## 6. 去重策略设计

去重不要只靠阈值，要分成“候选合并”和“事件判断”两步。真正难的是区分“同一事件不同角度”与“完全重复”，这恰好能展示你的 Agent 设计能力。 [medium](https://medium.com/@bella.belgarokova_79633/mastering-chromadb-for-semantic-search-a-comprehensive-guide-875a7f42c39e)

### 去重流程
1. 规则预过滤：URL 相同、标题高度相似、发布时间接近，直接判重复。
2. 向量相似度：标题+摘要 embedding 余弦相似度超过阈值，进入候选簇。
3. LLM 事件判别：让模型判断“是否为同一事件”，并输出 `same_event / same_topic_different_angle / different_event`。
4. 簇内保留：同一事件保留最权威来源或信息最完整条目，其余作为补充来源挂到主条目 metadata。

### 阈值建议
- 初始阈值：`cosine >= 0.88` 进入强重复候选。
- 中间区间：`0.78 ~ 0.88` 交给 LLM 判别。
- 低于 `0.78` 默认不重复，除非标题关键词完全一致。

### 校准方法
- 做一个小型标注集：100–200 对条目，标成 `duplicate / same_event / different`.
- 观察 precision/recall，优先保证 duplicate precision 高，因为误合并比漏合并更伤体验。
- 按主题分桶校准：科技新闻和公司财报的重复阈值通常不同。

### 区分规则
- **同一事件不同角度**：时间一致、主体一致、核心事实一致，但视角/细节不同。
- **真正重复**：核心事实、主体、时间点、结论都一致，仅措辞不同。
- **不同事件**：虽然关键词相近，但触发动作或结论不同，例如“发布预告”与“正式发布”。

***

## 7. 数据模型

SQLite 适合这个 MVP：轻量、单机、零运维，足够支撑简历项目。 [docs.python](https://docs.python.org/zh-cn/3/library/sqlite3.html)

### 表结构设计

```sql
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT,
  email TEXT UNIQUE,
  timezone TEXT DEFAULT 'Asia/Shanghai',
  created_at TEXT,
  updated_at TEXT
);

CREATE TABLE sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  type TEXT NOT NULL,              -- rss/search
  name TEXT NOT NULL,
  url TEXT NOT NULL,
  enabled INTEGER DEFAULT 1,
  credibility_score REAL DEFAULT 0.8,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  source_id INTEGER,
  canonical_id INTEGER,
  title TEXT NOT NULL,
  summary TEXT,
  content TEXT,
  url TEXT UNIQUE,
  published_at TEXT,
  fetched_at TEXT,
  category TEXT,
  lang TEXT,
  embedding_id TEXT,
  sim_score REAL,
  freshness_score REAL,
  preference_score REAL,
  final_score REAL,
  duplicate_group_id TEXT,
  status TEXT DEFAULT 'active',
  metadata_json TEXT,
  created_at TEXT,
  updated_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  item_id INTEGER NOT NULL,
  rating INTEGER NOT NULL,         -- 1 like, -1 dislike
  reason TEXT,
  context_json TEXT,
  created_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id),
  FOREIGN KEY(item_id) REFERENCES items(id)
);

CREATE TABLE briefs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  run_id TEXT NOT NULL,
  title TEXT,
  content TEXT,
  items_json TEXT,
  generated_at TEXT,
  sent_at TEXT,
  status TEXT DEFAULT 'generated',
  reflection_json TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE run_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT UNIQUE NOT NULL,
  user_id INTEGER NOT NULL,
  stage TEXT,
  input_json TEXT,
  output_json TEXT,
  error_text TEXT,
  reflection_note TEXT,
  created_at TEXT,
  updated_at TEXT
);
```

### 索引建议
- `items(user_id, published_at)`
- `items(user_id, duplicate_group_id)`
- `feedback(user_id, item_id)`
- `briefs(user_id, generated_at)`

### SQLite 实践建议
- 开启 WAL 模式以提升并发读写体验。
- 用事务包裹一次简报生成流程，避免半写入状态。 [www3.sqlite](https://www3.sqlite.org/src/info/cf8a0c71cf1032bd)

***

## 8. 技术栈选择

这一套技术选型很适合“国内可用 + 能展示工程能力 + 适合简历讲述”。 [qwen-ai](https://qwen-ai.chat/docs/api/)

| 层级 | 技术选择 | 理由 |
|---|---|---|
| 前端 | Streamlit | 快速搭 MVP，适合展示简报、反馈按钮、历史记录 |
| 编排框架 | LangGraph | 适合显式状态流、节点边、反思闭环，不是黑盒 Agent |
| LLM | DeepSeek / 通义千问 | 国内可用，支持 function calling，便于落地工具调用。 [api-docs.deepseek](https://api-docs.deepseek.com/zh-cn/guides/tool_calls) |
| 向量库 | ChromaDB | 本地轻量、单机可跑，适合长期记忆和语义检索。 [docs.agno](https://docs.agno.com/knowledge/vector-stores/chroma/overview) |
| 数据库 | SQLite | 零运维，项目最稳，适合个人简历项目。 [docs.python](https://docs.python.org/3/library/sqlite3.html) |
| 定时调度 | APScheduler / Celery beat | 定时拉取与每日简报生成 |
| 搜索服务 | MCP Search Server | 可独立扩展，支持 SSE/stdio 接入。 [docs.ag2](https://docs.ag2.ai/latest/docs/user-guide/advanced-concepts/tools/mcp/client/) |
| 通知推送 | MCP Notification Server | 未来可复用 Telegram/Email/企业微信 |
| 日志监控 | structlog + SQLite logs | 简单可追踪 |
| 部署 | Docker Compose | 一键起服务，展示工程化 |

***

## 9. MVP 范围界定

MVP 的目标不是“全功能产品”，而是证明你能做出一个完整 Agent 闭环：采集、理解、去重、排序、摘要、反馈、记忆更新。 [docs.langchain](https://docs.langchain.com/oss/python/langgraph/graph-api)

### 必须实现
- 用户配置主题和 RSS 源。
- 定时采集 RSS 和搜索结果。
- 条目标准化。
- 向量去重。
- 基于相似度、时间、偏好的排序。
- 自动生成结构化简报。
- 用户点赞/踩反馈。
- 反馈写回长期记忆。
- Streamlit 展示简报和历史记录。
- LangGraph 形式化工作流。

### 后续迭代再加
- 多用户团队版。
- 多渠道推送（邮件、Telegram、企业微信）。
- 更复杂的个性化排序模型。
- 事件级知识图谱。
- 自动追问式交互。
- 多 Agent 分工协作。
- 复杂网页抓取与浏览器自动化。

***

## 10. 阶段性目标与拆解

下面按“可验证交付单元”拆，不按天数拆，这样更适合项目管理和简历呈现。

### 阶段 1：最小闭环
- **阶段目标**：实现“采集 → 入库 → 展示”的最小链路。
- **交付物**：能从 3–5 个 RSS 源抓取条目，并在 Streamlit 显示列表；验证方式是条目能稳定落库并显示。
- **关键任务**
  - 建 SQLite 表。
  - 实现 RSS 采集工具。
  - 实现条目标准化。
  - Streamlit 页面展示。
- **依赖**：无。
- **复杂度**：低。

### 阶段 2：Agent 编排
- **阶段目标**：把采集流程改造成 LangGraph 状态机。
- **交付物**：一次运行可自动完成采集、处理、输出简报；验证方式是每个节点都有状态流转日志。
- **关键任务**
  - 定义 `FeedLensState`。
  - 实现 `collect → normalize → save` 节点。
  - 接入定时器。
- **依赖**：阶段 1。
- **复杂度**：中。

### 阶段 3：去重与排序
- **阶段目标**：让简报“像人写的”，减少重复和噪音。
- **交付物**：同一事件多来源只保留主条目；排序能体现相关性和新鲜度；验证方式是人工抽检重复率下降。
- **关键任务**
  - 生成 embedding。
  - 向量相似度去重。
  - 排序公式实现。
  - 简单阈值调参。
- **依赖**：阶段 2。
- **复杂度**：中高。

### 阶段 4：反馈闭环
- **阶段目标**：引入用户偏好学习。
- **交付物**：点赞/踩会影响下一次排序；验证方式是同类内容排序发生可解释变化。
- **关键任务**
  - 写反馈表。
  - 更新偏好权重。
  - 从反馈中生成长期记忆摘要。
- **依赖**：阶段 3。
- **复杂度**：中。

### 阶段 5：反思与质量控制
- **阶段目标**：让 Agent 会自检。
- **交付物**：简报会自动检查重复、缺失、过长等问题并修正；验证方式是反思节点能修改初稿。
- **关键任务**
  - 实现 reflection node。
  - 定义质量检查规则。
  - 输出可追踪的修正记录。
- **依赖**：阶段 4。
- **复杂度**：中。

### 阶段 6：工程化包装
- **阶段目标**：让项目具备简历展示度和可部署性。
- **交付物**：Docker Compose 一键启动，含 Worker、Streamlit、SQLite、ChromaDB；验证方式是本地可复现运行。
- **关键任务**
  - 拆分配置。
  - 容器化部署。
  - 日志与错误处理。
- **依赖**：阶段 5。
- **复杂度**：中。

***