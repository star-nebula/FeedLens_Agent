# FeedLens — 智能信息简报 Agent · MVP 设计方案

## 1. 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        外部触发 / 用户交互层                              │
│   APScheduler(每日定时)   ──┐         Streamlit UI(查看简报/反馈)          │
└──────────────────────────────┼─────────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  感知层 Perception                                                        │
│   ─ 定时触发信号        ─ 用户偏好设定       ─ 用户反馈(👍/👎/不相关)        │
│   ─ RSS 原始 feed       ─ 搜索结果 JSON      ─ 工具返回结果                │
└──────────────────────────────┬──────────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  规划层 Planning (LangGraph StateGraph)                                   │
│   ┌─────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐  ┌──────┐  │
│   │plan_src │→ │collect │→ │dedup   │→ │score   │→ │generate│→ │reflect│ │
│   └─────────┘  └────────┘  └────────┘  └────────┘  └────────┘  └──────┘  │
│        ReAct 循环(失败回退重采)         反思: 简报质量自检→重生成           │
└──────────────────────────────┬──────────────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────────────┐
│  大脑 Brain (LLM)                                                         │
│   DeepSeek-V3 (推理/工具调用/简报生成)   通义千问(降级备份)                  │
│   职责: 意图理解 · 工具调用判断 · 摘要/分类 · 反思审查                       │
└──────────────────────────────┬──────────────────────────────────────────┘
                               ▼
┌─────────────────────── 工具层 Tools ────────────────────────────────────┐
│  Function Calling(进程内)              MCP Server(独立进程)               │
│  ─ rss_fetch          ─ vector_dedup   ─ web_search   [SSE, 端口 8100]    │
│  ─ content_extractor  ─ embed_text     ─ push_notifier [stdio]            │
│  ─ scorer             ─ briefing_gen                                      │
│  ─ feedback_recorder  ─ preference_learner                                │
└──────────────────────────────┬──────────────────────────────────────────┘
                               ▼
┌──────────────────────── 记忆层 Memory ──────────────────────────────────┐
│  短期: LangGraph State(本次执行上下文, 进程内)                              │
│  长期: ChromaDB(向量) + SQLite(元数据)  ─ 偏好向量/条目向量/知识            │
│  情节: SQLite.episodes + ChromaDB摘要向量  ─ 历史任务执行记录              │
│  语义: ChromaDB.knowledge  ─ 领域事实/来源可靠性/话题分类                   │
└─────────────────────────────────────────────────────────────────────────┘
```

每一层都对应你框架里的概念：感知层接入外部信号；规划层用 StateGraph 编排 ReAct + 反思；大脑是 LLM 推理核心；工具层按特性分流 Function Calling / MCP；记忆层四类存储各司其职。

---

## 2. Agent 工作流设计（LangGraph StateGraph）

### 2.1 State 定义（TypedDict）

```python
from typing import TypedDict, List, Optional, Literal

class FeedItem(TypedDict):
    item_id: str
    source: str
    title: str
    url: str
    snippet: str
    published_at: str
    embedding: List[float]
    cluster_id: Optional[str]

class Briefing(TypedDict):
    date: str
    categories: List[dict]   # [{category, items:[{title,summary,importance,source,url}]}]
    overview: str

class FeedLensState(TypedDict):
    # 身份与偏好
    user_id: str
    preferences: dict                 # {topics:[...], weights:{...}}
    # 采集
    target_sources: List[dict]
    raw_items: List[FeedItem]
    normalized_items: List[FeedItem]
    # 去重
    deduped_items: List[FeedItem]
    clusters: List[List[str]]         # 同事件分组
    # 排序
    scored_items: List[dict]          # [{item, score, breakdown}]
    selected_items: List[FeedItem]    # top-N
    # 生成
    briefing: Optional[Briefing]
    reflection_notes: Optional[str]
    reflection_pass: bool
    # 执行
    execution_log: List[str]
    errors: List[str]
    retries: int
```

### 2.2 节点与边

```
START
  │
  ▼
[load_profile]   ── 从长期记忆加载偏好/话题/来源配置
  │
  ▼
[plan_sources]   ── LLM 根据偏好决定本轮查哪些源、补哪些关键词(ReAct:思考)
  │
  ▼
[collect]        ── 并行调用 rss_fetch / web_search MCP, 汇总 raw_items
  │                 (失败→errors, 若 raw 为空走 retry 分支)
  ▼
[normalize]      ── content_extractor + embed_text, 统一结构
  │
  ▼
[dedup]          ── vector_dedup + 实体重叠校验, 产出 clusters
  │
  ▼
[score]          ── scorer: 相似度+时效+偏好+权威, 含去重惩罚
  │
  ▼
[select_top]     ── 取 top-N, 跨类别配额
  │
  ▼
[generate]       ── briefing_gen: 分类组织+重要性标注+来源引用
  │
  ▼
[reflect]        ── LLM 自检: 覆盖度?重复?来源单一?用户偏好命中?
  │
  ├─ pass=False & retries<2 ──► [generate](带 reflection_notes 重做)
  └─ pass=True
        │
        ▼
  [push]         ── 调用 push_notifier MCP (Telegram/邮件)
        │
        ▼
  [archive]      ── 写 briefings 表 + episodes 表 + 更新偏好向量
        │
        ▼
       END
```

**关键条件边：**
- `collect` → 若 `raw_items` 为空且 `retries<1`，回到 `plan_sources`（换关键词重试）
- `reflect` → `generate`（重做，最多 2 次）
- `dedup` → 若去重后剩余 < 3 条，回 `collect`（扩大时间窗/来源）

这样体现了 ReAct（思考-行动-观察-再思考）与反思（reflection）两种规划模式。

---

## 3. 工具清单

| # | Tool name | 调用方式 | 选择理由 |
|---|-----------|---------|---------|
| 1 | `rss_fetch` | **Function Calling** | 输入就是 feed URL，输出结构化列表，逻辑简单参数明确，无需独立部署 |
| 2 | `web_search` | **MCP (SSE)** | 搜索是重型外部服务，需独立部署、可被多 Agent 复用、便于切换供应商(Bing/Searxng/Tavily)，解耦价值高 |
| 3 | `content_extractor` | **Function Calling** | URL→正文，简单 I/O，与 Agent 紧耦合 |
| 4 | `embed_text` | **Function Calling** | 调 embedding 模型的薄封装，高频内部调用，进程内最快 |
| 5 | `vector_dedup` | **Function Calling** | 直接操作本地 ChromaDB + Agent 记忆状态，强耦合 |
| 6 | `scorer` | **Function Calling** | 纯计算排序逻辑，内部算法 |
| 7 | `briefing_generator` | **Function Calling** | LLM 核心能力，与 Agent 大脑深度集成 |
| 8 | `feedback_recorder` | **Function Calling** | 简单 DB 写，内部 |
| 9 | `preference_learner` | **Function Calling** | 更新长期记忆中的偏好向量，内部状态变更 |
| 10 | `push_notifier` | **MCP (stdio)** | 通知是多渠道(Telegram/邮件/Webhook)的系统级能力，可被其他 Agent 复用；用 stdio 是因为它轻量、与 Agent 同机部署、无需开端口，与 SSE 的 web_search 形成对比，体现两种 transport 取舍 |

> 这样 Function Calling(8个) 与 MCP(2个) 的划分有明确原则：**「内部状态/纯计算/紧耦合」走 Function Calling，「独立部署/跨进程复用/可换供应商」走 MCP**，且刻意让两个 MCP 分别用 SSE 和 stdio 两种 transport，简历上能体现你理解了 MCP 的部署形态差异。

### 3.1 各工具参数定义（挑代表性的展开）

**rss_fetch** (Function Calling)
```json
{
  "name": "rss_fetch",
  "description": "从给定 RSS feed URL 拉取最新条目",
  "parameters": {
    "feed_url": {"type": "string"},
    "limit": {"type": "integer", "default": 20}
  },
  "returns": [{"title","url","snippet","published_at"}]
}
```

**web_search** (MCP Server, SSE, 端口 8100)
```json
{
  "name": "web_search",
  "description": "调用搜索引擎获取最近 N 天的相关结果",
  "parameters": {
    "query": {"type": "string"},
    "days": {"type": "integer", "default": 1},
    "top_k": {"type": "integer", "default": 10}
  }
}
```
部署方式：独立 Python 进程，`mcp` SDK 启动 SSE server 监听 `0.0.0.0:8100/sse`。Agent 端用 `langchain-mcp-adapters` 的 `MultiServerMCPClient` 连接。接口遵循 MCP tools 协议（list_tools / call_tool）。

**vector_dedup** (Function Calling)
```json
{
  "name": "vector_dedup",
  "description": "对条目做向量去重+实体校验，产出簇",
  "parameters": {
    "items": {"type": "array"},
    "window_days": {"type": "integer", "default": 7},
    "threshold": {"type": "number", "default": 0.85}
  },
  "returns": {"deduped_items":[...], "clusters":[[item_id,...]]}
}
```

**briefing_generator** (Function Calling)
```json
{
  "name": "briefing_generator",
  "description": "将 top-N 条目组织为分类简报,含重要性标注和来源引用",
  "parameters": {
    "items": {"type":"array"},
    "user_preferences":{"type":"object"},
    "reflection_notes":{"type":"string"}   // 重做时传入反思意见
  }
}
```

**push_notifier** (MCP Server, stdio)
```json
{
  "name": "push_notifier",
  "description": "通过 Telegram/邮件推送简报",
  "parameters": {
    "user_id": {"type":"string"},
    "channel": {"enum":["telegram","email"]},
    "briefing": {"type":"object"}
  }
}
```
部署方式：作为子进程由 Agent 启动（`mcp` SDK stdio 模式），通过 stdin/stdout 通信。Telegram Bot Token 走环境变量。优势：Agent 重启不影响通知服务配置；其他 Agent 可直接复用此 notifier。

---

## 4. 记忆系统设计

| 记忆类型 | 存储 | 存什么 | 怎么检索 | 怎么更新 |
|---------|------|--------|---------|---------|
| **短期记忆** | LangGraph State（进程内） | 本轮任务的 raw_items、中间分数、规划轨迹、reflection_notes | 节点直接读 State | 节点 mutate State；任务结束归档到情节记忆后清空 |
| **长期记忆** | ChromaDB `items`/`prefs` collection + SQLite 元数据 | ① 条目向量（近 30 天，用于去重）② 用户偏好向量（每话题一个正/负向量）③ 来源可靠性评分 | 余弦相似 top-k | 偏好向量用 EMA 更新：`v_new = α·v_feedback + (1-α)·v_old`；条目向量插入时打 TTL |
| **情节记忆** | SQLite `episodes` 表 + ChromaDB `episode_summaries` 向量 | 每次任务的执行记录：查了什么源、去重掉什么、生成了什么简报、用户后来怎么反馈 | 摘要向量相似检索（"上次跑 AI Agent 话题时用户喜欢哪些"） | 任务结束 append；用户反馈回流时回填到对应 episode |
| **语义记忆** | ChromaDB `knowledge` collection | 领域事实、话题分类树、来源领域标签 | RAG top-k | 周期性 LLM 抽取刷新；可手工 seed |

**短期→长期的桥梁**：每轮任务结束，`archive` 节点把 State 摘要成一段文本（LLM 生成），写入情节记忆；用户反馈来时，`preference_learner` 既更新长期偏好向量，也回填到对应 episode 的 feedback 字段——这就是「从经验中学习」。

---

## 5. 排序算法设计

**打分公式：**
```
final_score = w1·sim_score + w2·recency_score + w3·pref_score + w4·authority_score − dedup_penalty
```

| 项 | 计算 | 权重 | 含义 |
|----|------|-----|------|
| sim_score | cos(item_emb, user_topic_emb) ∈[0,1] | **0.35** | 与用户关注话题的相关度，最核心 |
| recency_score | exp(−Δt/τ), τ=24h | **0.20** | 时效衰减，新闻类必须有 |
| pref_score | 来自历史反馈的同类条目偏好累积 ∈[−1,1] 归一到[0,1] | **0.30** | 个性化学习信号，体现 Agent「越用越准」 |
| authority_score | 来源可靠性配置 ∈[0,1] | **0.15** | 抑制低质来源 |
| dedup_penalty | 与已选条目最大相似度×0.5 | — | 防止簇内多条挤占名额 |

**权重取舍说明：** sim+pref 合计 0.65 是主体——简历项目要突出「个性化」，所以偏好权重给到 0.30 而非更小；recency 只给 0.20 因为简报本身是每日，时效差异不大；authority 给最低 0.15 作为兜底。所有权重写进配置文件可调，并在 Streamlit 暴露滑块做 A/B 观感。

**跨类别配额：** top-N 选取时按用户话题数均分配额（如 5 话题 × 4 条 = 20），单话题内按 final_score 降序，避免某个热门话题霸屏。

---

## 6. 去重策略设计

**两阶段去重：**

**阶段一：向量粗筛**
- 对每条新条目 `embed(title + 前 200 字 snippet)`
- 与最近 7 天已入库条目向量做余弦相似
- `sim > 0.85` → 进入"疑似重复"集

**阶段二：实体校验（区分「同事件不同角度」vs「真重复」）**

| 条件 | 判定 | 处理 |
|------|------|------|
| sim>0.85 **且** 命名实体重叠率>0.7 **且** 标题相似度>0.8 | **真重复** | 保留 authority 最高的一条 |
| 0.75 < sim ≤ 0.85 | **同事件不同角度** | 归入同一 cluster，简报里展示为「相关报道」折叠组 |
| sim ≤ 0.75 | **独立条目** | 保留 |

命名实体用 LLM 轻量抽取（或用 spaCy 中文模型，省 token）。

**阈值校准方法：**
1. 人工标注 200 对条目（dup / related / distinct 三类）
2. 扫描 threshold ∈ [0.6, 0.95] 步长 0.05，画出 P/R/F1 曲线
3. 选 F1 最优点作为初始 0.85，related 阈值取 P=0.9 对应点
4. 写成校准脚本 `scripts/calibrate_dedup.py`，简历上可写「带可复现的阈值校准流程」

这样比单纯设一个 0.85 阈值要工程化得多，也直接呼应你要求里「区分同一事件不同角度和真正重复」。

---

## 7. 数据模型（SQLite + ChromaDB）

**SQLite 表：**

```sql
-- 用户与偏好
users(id, name, email, telegram_chat_id, created_at)
topics(id, user_id, name, keywords_json, chroma_pref_vector_id, created_at)
sources(id, name, type, config_json, authority_score, enabled)

-- 信息条目
items(
  id, source_id, user_id, title, url, snippet,
  published_at, collected_at,
  chroma_item_vector_id,    -- 指向 ChromaDB
  cluster_id, score, status  -- status: selected/discarded/pushed
)
item_clusters(id, summary, created_at, size)

-- 反馈与学习
feedback(id, user_id, item_id, signal, reason, created_at)
-- signal: like / dislike / not_relevant

-- 简报与情节
briefings(id, user_id, generated_at, content_json, item_ids_json)
episodes(
  id, user_id, task_type, started_at, finished_at,
  summary_text, chroma_episode_vector_id, success, log_json
)

-- 配置
source_topic_map(source_id, topic_id)   -- 多对多
```

**ChromaDB collections：**
- `item_vectors`：id ↔ SQLite items.id，存条目向量
- `preference_vectors`：id ↔ topics.id，存每话题正/负偏好向量
- `episode_summaries`：id ↔ episodes.id，存情节摘要向量
- `knowledge`：语义记忆，领域知识块

> 向量本身放 ChromaDB（高效 ANN 检索），结构化属性放 SQLite（关系查询/聚合），通过 `_id` 字段互连——这是轻量级 RAG 项目的标准做法，比把所有东西塞进一个 DB 更清晰。

---

## 8. 技术栈选择

| 层级 | 选型 | 理由 |
|------|------|------|
| LLM | **DeepSeek-V3**（主力）+ 通义千问 Qwen-Max（降级） | 国内可用、性价比高、Function Calling 支持成熟；双供应商降级体现生产意识 |
| Embedding | **bge-small-zh**（本地 sentence-transformers）+ DashScope text-embedding-v2（可选） | 中文效果好、本地零成本、无外部依赖；本地优先避免 API 限流 |
| Agent 框架 | **LangGraph** | 状态图清晰、可条件分支、原生支持 ReAct + reflection 循环 |
| MCP | **mcp Python SDK** + `langchain-mcp-adapters` | 官方 SDK，支持 stdio/SSE 两种 transport |
| 向量库 | **ChromaDB**（persistent 模式） | 轻量单机、API 简单、符合你约束 |
| 关系库 | **SQLite** + SQLAlchemy | 零运维、单文件、MVP 够用 |
| 调度 | **APScheduler** | Python 内嵌、cron 表达式、无需额外服务 |
| 前端 | **Streamlit** | 快速出 MVP、符合你约束 |
| 搜索源 | **Searxng 自建**（首选）或 Bing China API | 国内可用、可控；自建 Searxng 更显工程能力 |
| RSS | **feedparser** | Python RSS 事实标准 |
| 推送 | **Telegram Bot**（主）+ SMTP 邮件（备） | Telegram 调试方便、邮件兜底 |
| 部署 | **Docker Compose**（agent + web_search MCP + Searxng） | 一键起、简历可写「容器化部署」 |
| 配置 | pydantic-settings + .env | 类型安全配置 |

---

## 9. MVP 范围界定

**MVP 必须实现：**
- ✅ 单用户、3–5 个关注话题
- ✅ RSS（≥2 源）+ 搜索（1 源）双通道采集
- ✅ 每日定时 + 手动触发
- ✅ 向量去重（含实体校验）+ 同事件聚类
- ✅ 排序打分（4 因子加权）+ 跨类别配额
- ✅ 结构化简报生成（分类/重要性/来源引用）
- ✅ 反思节点（自检覆盖度/重复/偏好命中）
- ✅ Streamlit UI：查看简报、点👍👎/「不相关」
- ✅ 偏好向量 EMA 更新（基础学习闭环）
- ✅ 2 个 MCP Server：web_search(SSE) + push_notifier(stdio)
- ✅ 情节记忆记录每次任务执行
- ✅ Telegram 推送

**后续迭代才加：**
- ⏸ 多用户隔离与鉴权
- ⏸ 更多源（微信公众号、Twitter/X、ArXiv）
- ⏸ 跨话题智能路由（一个事件跨多个用户话题时的归并）
- ⏸ 主动追问式偏好校准（Agent 发现偏好信号冲突时主动问用户）
- ⏸ 情节记忆的 meta-learning（从多次执行中总结「周二科技类简报用户更喜欢短摘要」这类规律）
- ⏸ 周报/月报聚合
- ⏸ Web 前端替换 Streamlit

---

## 10. 阶段性目标与任务拆解

按「阶段」拆，每阶段是独立可验证的交付单元。

### 阶段 0：地基搭建
- **目标**：项目骨架能跑起来，定时器能触发空任务
- **交付物**：项目目录结构、依赖锁定、SQLite schema 初始化脚本、APScheduler 每分钟打印日志、Streamlit 首页能打开
- **验证**：`python main.py` 启动后日志出现定时触发；浏览器打开 Streamlit 看到首页
- **关键任务**：建项目结构(config/db/agent/tools/ui)；写 schema.prisma 对应的 SQLAlchemy models；APScheduler 调度器壳；Streamlit 三页骨架(简报/反馈/设置)
- **依赖**：无
- **复杂度**：低

### 阶段 1：数据采集
- **目标**：能从 RSS 和搜索源拉到真实条目并入库
- **交付物**：`rss_fetch` 工具、`web_search` MCP Server(SSE)、items 表有数据、Streamlit「原始信息流」页可看条目
- **验证**：手动触发采集，DB 出现 ≥20 条 items，UI 展示
- **关键任务**：feedparser 封装 rss_fetch；搭 web_search MCP Server（含 Searxng 或 Bing 接入）；content_extractor 抽正文；embed_text 接 bge；写入 items + ChromaDB
- **依赖**：阶段 0
- **复杂度**：中

### 阶段 2：记忆与去重
- **目标**：ChromaDB 集成完成，去重可工作
- **交付物**：`vector_dedup` 工具、item_clusters 表、去重阈值校准脚本、校准报告
- **验证**：同一篇文章从 2 个源喂入，只保留 1 条；related 类归入同 cluster
- **关键任务**：ChromaDB persistent 初始化；实体抽取(spacy/sentence-transformers NER 或 LLM)；去重两阶段逻辑；标注 200 对样本；跑校准脚本出曲线图
- **依赖**：阶段 1
- **复杂度**：中

### 阶段 3：排序与偏好学习
- **目标**：打分排序工作，反馈能反向影响后续排序
- **交付物**：`scorer`、`feedback_recorder`、`preference_learner` 工具；Streamlit 反馈交互；偏好向量 EMA 更新
- **验证**：对某话题连点 3 次👎，下一轮该话题相似条目 score 明显下降
- **关键任务**：4 因子打分实现；偏好向量 EMA；feedback 表写入；UI 反馈按钮接 API；A/B 观感滑块
- **依赖**：阶段 2
- **复杂度**：中高

### 阶段 4：LangGraph 编排 + 简报生成（核心）
- **目标**：完整 StateGraph 端到端跑通，产出结构化简报
- **交付物**：LangGraph 工作流（全部节点+条件边）、`briefing_generator`、`reflect` 节点、briefings 表、Streamlit 简报页
- **验证**：定时触发后自动跑完全流程，UI 展示分类简报（含重要性标注+来源）；reflect 失败时能重做
- **关键任务**：State TypedDict；逐节点实现；条件边(retry/重做)；briefing prompt 工程；reflect prompt 工程
- **依赖**：阶段 3
- **复杂度**：高

### 阶段 5：推送与闭环
- **目标**：MCP push_notifier 把简报推到 Telegram，情节记忆闭环
- **交付物**：`push_notifier` MCP Server(stdio)、Telegram 集成、episodes 表写入、执行仪表盘页
- **验证**：定时跑完收到 Telegram 简报；执行仪表盘可查历史 episode
- **关键任务**：Telegram Bot 接入；stdio MCP Server；archive 节点写 episodes + 摘要向量；仪表盘展示执行成功率/耗时/反馈率
- **依赖**：阶段 4
- **复杂度**：中

### 阶段 6：工程化与简历交付
- **目标**：可演示、可复现、可写进简历
- **交付物**：README（含架构图）、Docker Compose 一键起、设计文档、3 分钟演示视频、简历话术（量化指标）
- **验证**：陌生环境 `docker compose up` 能跑通完整流程；演示视频覆盖核心场景
- **关键任务**：Dockerfile×3；compose 编排；README；录屏；简历 bullet 点提炼（如「LangGraph 编排 X 节点工作流」「MCP 双 transport 解耦工具层」「向量去重 F1 达 X」「偏好学习使相关条目 CTR 提升 X%」）
- **依赖**：阶段 5
- **复杂度**：低

---

## 设计要点回顾（简历可强调的工程亮点）

1. **架构分层清晰**——感知/规划/大脑/工具/记忆五层映射到位，不是"调 API 堆功能"
2. **工具调用分流有原则**——Function Calling 与 MCP 按"耦合度/复用性/部署形态"划分，且 MCP 刻意用 SSE+stdio 两种 transport
3. **记忆四类齐全**——短期/长期/情节/语义各有存储与更新机制，偏好 EMA 体现"学习"
4. **去重非一刀切**——向量粗筛 + 实体校验两阶段，区分"真重复"与"同事件不同角度"，带可复现的阈值校准
5. **排序公式可解释**——4 因子加权 + 跨类别配额，权重可调可 A/B
6. **规划体现 ReAct + Reflection**——条件边做重试/重做，不是线性流水线
7. **技术栈国内可用**——DeepSeek + 通义 + bge + ChromaDB，无 OpenAI 依赖
8. **阶段化交付**——每阶段独立可验证，适合 AI 辅助实现