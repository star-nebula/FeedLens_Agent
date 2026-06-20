# FeedLens — 智能信息简报 Agent MVP 设计文档

---

## 1. 系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FeedLens Agent 系统                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────── 规划层 (Planning) ────────────────────┐ │
│  │  ┌──────────────┐  ┌────────────────┐  ┌───────────────────┐  │ │
│  │  │  主调度器     │  │  ReAct 循环     │  │  反思模块          │  │ │
│  │  │  (Scheduler)  │  │  (think→act→   │  │  (Reflection)     │  │ │
│  │  │              │  │   observe)      │  │  任务后质量审查    │  │ │
│  │  └──────────────┘  └────────────────┘  └───────────────────┘  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                              ↕                                      │
│  ┌───────────────────────── 大脑层 (Brain) ──────────────────────┐  │
│  │                                                                │  │
│  │              DeepSeek / 通义千问 (LLM Core)                    │  │
│  │         意图理解 → 推理决策 → 工具调用判断 → 输出生成            │  │
│  │                                                                │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                              ↕                                      │
│  ┌─────────── 工具层 (Tools) ────┐  ┌──────── 记忆层 (Memory) ──┐  │
│  │                                │  │                            │  │
│  │  Function Calling 工具:        │  │  短期记忆                   │  │
│  │  ├─ rss_fetch                  │  │  (对话上下文窗口)            │  │
│  │  ├─ text_summarize             │  │  存储: 内存 List            │  │
│  │  ├─ content_classify           │  │  管理: 滑动窗口 15 轮       │  │
│  │  ├─ deduplicate_check          │  │                            │  │
│  │  ├─ score_and_rank             │  │  长期记忆                   │  │
│  │  └─ user_preference_query      │  │  (用户偏好/知识)            │  │
│  │                                │  │  存储: ChromaDB + SQLite    │  │
│  │  MCP 工具:                     │  │  检索: 向量相似度 RAG       │  │
│  │  ├─ web_search (SSE)          │  │  更新: 反馈事件触发          │  │
│  │  ├─ database_ops (stdio)      │  │                            │  │
│  │  └─ notification_push (stdio) │  │  情节记忆                   │  │
│  │                                │  │  (历史执行记录)              │  │
│  └────────────────────────────────┘  │  存储: SQLite              │  │
│                              ↕        │  检索: 按任务类型+时间       │  │
│  ┌───────────── 感知层 (Perception) ─┴──────────────────────────┐  │
│  │                                                               │  │
│  │  输入: RSS XML → 解析为结构化数据                              │  │
│  │  输入: 搜索结果 JSON → 标准化条目                              │  │
│  │  输入: 用户反馈 → 偏好信号                                     │  │
│  │  输入: 工具返回结果 → 中间状态更新                              │  │
│  │  输入: 定时触发信号 → 启动采集流程                              │  │
│  │                                                               │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              ↕                                      │
│  ┌─────────────── 存储层 (Storage) ──────────────────────────────┐  │
│  │  SQLite (结构化数据)  │  ChromaDB (向量数据)  │  JSON (配置)    │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                              ↕                                      │
│  ┌─────────────── 展示层 (Presentation) ─────────────────────────┐  │
│  │  Streamlit UI: 简报展示 / 偏好设置 / 反馈收集 / 状态监控        │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**各层与 Agent 架构的映射：**

| 架构层 | FeedLens 对应模块 | 职责 |
|--------|-------------------|------|
| 感知层 | RSS 解析器、搜索结果标准化、反馈信号处理 | 将外部数据转为 Agent 可处理的结构化输入 |
| 大脑层 | DeepSeek/通义千问 LLM | 核心推理引擎，驱动所有决策 |
| 工具层 | 8 个工具（6 FC + 2 MCP） | 信息获取、内容处理、数据操作、通知推送 |
| 记忆层 | 短期(内存)/长期(ChromaDB+SQLite)/情节(SQLite) | 跨时间的知识积累和经验复用 |
| 规划层 | LangGraph StateGraph 调度 + ReAct + 反思 | 任务编排、执行循环、质量审查 |

---

## 2. Agent 工作流设计

### 2.1 LangGraph StateGraph 总览

```
                    ┌──────────┐
                    │  START   │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │  plan    │  ← 规划节点：LLM 分析本次任务需要做什么
                    └────┬─────┘
                         │
              ┌──────────┼──────────┐
              │          │          │
         ┌────▼───┐ ┌───▼────┐ ┌──▼───────┐
         │ fetch  │ │ search │ │ recall   │  ← 并行执行：采集 + 搜索 + 记忆检索
         │  RSS   │ │  Web   │ │  Memory  │
         └────┬───┘ └───┬────┘ └──┬───────┘
              │          │         │
              └──────────┼─────────┘
                         │
                    ┌────▼─────┐
                    │deduplicate│  ← 去重：向量相似度 + 标题编辑距离
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │  classify │  ← 分类：LLM 对每条内容分类 + 重要性标注
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │   rank   │  ← 排序：综合打分公式
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │summarize │  ← 生成摘要 + 结构化简报
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │reflect   │  ← 反思：LLM 审查简报质量，决定是否需要修正
                    └────┬─────┘
                         │
                   ┌─────┴─────┐
                   │  quality   │
                   │  pass?     │
                   └──┬─────┬──┘
                 Yes  │     │  No (max 2 retries)
                      │     │
                      │  ┌──▼──────┐
                      │  │revise   │  ← 修正节点：根据反思意见调整
                      │  └──┬──────┘
                      │     │
                      └──┬──┘
                         │
                    ┌────▼─────┐
                    │deliver    │  ← 推送：保存简报 + 通知用户
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │  memory   │  ← 记忆更新：写入情节记忆 + 更新偏好
                    │  update   │
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │   END    │
                    └──────────┘
```

### 2.2 State TypedDict 定义

```python
from typing import TypedDict, Optional
from langgraph.graph import MessagesState


class FeedItem(TypedDict):
    """单条信息条目"""
    id: str                          # 唯一标识 (URL hash)
    title: str                       # 标题
    content: str                     # 正文/摘要
    url: str                         # 原始链接
    source: str                      # 来源名称 (RSS源/搜索引擎)
    published_at: str                # 发布时间 ISO 8601
    fetched_at: str                  # 采集时间
    category: Optional[str]          # 分类标签
    importance: Optional[int]        # 重要性 1-5
    summary: Optional[str]           # Agent 生成的摘要
    score: Optional[float]           # 排序得分
    embedding_id: Optional[str]      # ChromaDB 中的向量 ID
    is_duplicate: bool               # 是否被标记为重复
    duplicate_of: Optional[str]      # 重复的主条目 ID


class BriefingSection(TypedDict):
    """简报分节"""
    category: str                    # 分类名
    importance_label: str            # 重要性标签: "🔴重要" / "🟡值得关注" / "🔵一般"
    items: list[FeedItem]            # 该分类下的条目列表


class Briefing(TypedDict):
    """完整简报"""
    id: str                          # 简报 ID
    generated_at: str                # 生成时间
    user_id: str                     # 目标用户
    sections: list[BriefingSection]  # 分类分节
    total_items: int                 # 原始条目总数
    final_items: int                 # 去重后条目数
    generation_summary: str          # 本次采集的总结说明


class FeedbackSignal(TypedDict):
    """用户反馈信号"""
    item_id: str
    feedback_type: str               # "positive" / "negative" / "irrelevant"
    timestamp: str


class MemoryContext(TypedDict):
    """记忆检索结果"""
    user_preferences: dict           # 用户偏好向量和关键词
    similar_past_items: list[str]    # 历史相似条目标题
    episodic_notes: str              # 相关情节记忆文本


class FeedLensState(TypedDict):
    """LangGraph 核心状态 - 所有节点共享"""
    # 输入
    user_id: str
    trigger_type: str                # "scheduled" / "manual" / "feedback"
    user_topics: list[str]           # 用户关注领域 ["AI Agent", "新能源车"]

    # 采集阶段
    raw_items: list[FeedItem]        # RSS 原始条目
    search_items: list[FeedItem]     # 搜索引擎条目
    memory_context: MemoryContext    # 记忆检索结果

    # 处理阶段
    all_items: list[FeedItem]        # 合并后所有条目
    deduplicated_items: list[FeedItem]  # 去重后条目
    classified_items: list[FeedItem]    # 分类后条目
    ranked_items: list[FeedItem]        # 排序后条目

    # 输出阶段
    briefing: Optional[Briefing]     # 生成的简报
    reflection_feedback: Optional[str]  # 反思模块的审查意见
    reflection_passed: bool          # 反思是否通过
    reflection_retries: int          # 反思重试次数 (max 2)

    # 记忆更新
    feedback_signals: list[FeedbackSignal]  # 本次收到的用户反馈
    episodic_record: Optional[str]   # 待写入的情节记忆

    # 执行追踪
    current_step: str                # 当前执行到哪个节点
    error_log: list[str]             # 错误记录
```

### 2.3 节点间的边逻辑

```python
from langgraph.graph import StateGraph, END

graph = StateGraph(FeedLensState)

# 注册节点
graph.add_node("plan", plan_node)
graph.add_node("fetch_rss", fetch_rss_node)
graph.add_node("search_web", search_web_node)
graph.add_node("recall_memory", recall_memory_node)
graph.add_node("deduplicate", deduplicate_node)
graph.add_node("classify", classify_node)
graph.add_node("rank", rank_node)
graph.add_node("summarize", summarize_node)
graph.add_node("reflect", reflect_node)
graph.add_node("revise", revise_node)
graph.add_node("deliver", deliver_node)
graph.add_node("memory_update", memory_update_node)

# 定义边
graph.set_entry_point("plan")

# plan → 并行分支（LangGraph 支持）
graph.add_edge("plan", "fetch_rss")
graph.add_edge("plan", "search_web")
graph.add_edge("plan", "recall_memory")

# 并行分支汇合 → deduplicate
graph.add_edge("fetch_rss", "deduplicate")
graph.add_edge("search_web", "deduplicate")
graph.add_edge("recall_memory", "deduplicate")

# 线性流程
graph.add_edge("deduplicate", "classify")
graph.add_edge("classify", "rank")
graph.add_edge("rank", "summarize")
graph.add_edge("summarize", "reflect")

# 条件边：反思通过则交付，否则修正
def should_continue(state: FeedLensState) -> str:
    if state["reflection_passed"] or state["reflection_retries"] >= 2:
        return "deliver"
    return "revise"

graph.add_conditional_edges("reflect", should_continue, {
    "deliver": "deliver",
    "revise": "revise"
})
graph.add_edge("revise", "reflect")  # 修正后重新反思

graph.add_edge("deliver", "memory_update")
graph.add_edge("memory_update", END)

workflow = graph.compile()
```

---

## 3. 工具清单

### Function Calling 工具（6 个）

| # | Tool Name | Description | Parameters | 选择理由 |
|---|-----------|-------------|------------|----------|
| 1 | `rss_fetch` | 从配置的 RSS 源获取最新条目 | `sources: list[str]` (RSS URL 列表), `max_age_hours: int` (仅获取 N 小时内的条目, 默认 24) | **FC** — 逻辑简单（HTTP GET + XML 解析），参数明确，不需要独立部署，每次调用是无状态的单次请求 |
| 2 | `text_summarize` | 对长文本生成 2-3 句摘要 | `text: str` (原文), `max_length: int` (可选, 默认 150) | **FC** — 纯 LLM 调用封装，逻辑简单，不需要跨进程复用 |
| 3 | `content_classify` | 对信息条目进行分类和重要性评估 | `title: str`, `content: str`, `user_topics: list[str]` | **FC** — 本质是 prompt → 结构化输出，参数固定，无外部依赖 |
| 4 | `deduplicate_check` | 检查两条内容是否重复 | `item_a: dict`, `item_b: dict`, `threshold: float` (默认 0.85) | **FC** — 计算密集但逻辑自包含（向量余弦 + 标题编辑距离），不依赖外部服务 |
| 5 | `score_and_rank` | 对条目列表进行综合打分排序 | `items: list[FeedItem]`, `user_preferences: dict`, `decay_factor: float` | **FC** — 纯计算逻辑，公式固定，不需要独立部署 |
| 6 | `user_preference_query` | 查询用户的历史偏好画像 | `user_id: str`, `topic: str` | **FC** — 简单的数据库查询，返回偏好向量和关键词权重 |

### MCP 工具（2 个）

| # | Tool Name | Description | Parameters | MCP Server | 选择理由 |
|---|-----------|-------------|------------|------------|----------|
| 7 | `web_search` | 通过搜索引擎 API 搜索指定关键词的最新信息 | `query: str`, `num_results: int` (默认 5), `freshness: str` ("day"/"week") | **feedlens-search-server** | **MCP** — 搜索 API 需要管理 API Key 和调用配额，独立进程可独立升级/替换搜索引擎（SearXNG/Bing/DuckDuckGo），未来可跨多个 Agent 共享 |
| 8 | `notification_push` | 将生成的简报推送给用户 | `user_id: str`, `channel: str` ("streamlit"/"webhook"), `briefing: dict` | **feedlens-notify-server** | **MCP** — 推送渠道可能扩展（邮件/微信/Bot），独立进程方便添加新渠道，与 Agent 核心解耦 |

### MCP Server 接口定义

**feedlens-search-server** (stdio 模式):
```python
# 部署方式: stdio (Agent 作为父进程启动)
# 理由: 搜索服务轻量，stdio 避免端口管理，MCP Client SDK 直接管理生命周期

# MCP Tool 定义
{
    "name": "web_search",
    "description": "Search the web for latest information on a given topic",
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query string"},
            "num_results": {"type": "integer", "default": 5, "description": "Number of results to return"},
            "freshness": {"type": "string", "enum": ["day", "week", "month"], "default": "day"}
        },
        "required": ["query"]
    }
}

# 返回格式
{
    "results": [
        {
            "title": "...",
            "url": "...",
            "snippet": "...",
            "published_date": "..."
        }
    ]
}
```

**feedlens-notify-server** (stdio 模式):
```python
# 部署方式: stdio
# 理由: MVP 阶段推送只写 Streamlit session state，stdio 最简单

# MCP Tool 定义
{
    "name": "notification_push",
    "description": "Push a briefing notification to the user via specified channel",
    "inputSchema": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "channel": {"type": "string", "enum": ["streamlit", "webhook"]},
            "briefing": {"type": "object", "description": "Briefing content to deliver"}
        },
        "required": ["user_id", "channel", "briefing"]
    }
}
```

---

## 4. 记忆系统设计

### 4.1 短期记忆 (Short-term Memory)

| 属性 | 设计 |
|------|------|
| **存储** | 内存中的 Python `list[dict]`（LangGraph State 的对话历史字段） |
| **内容** | 当前采集任务的执行上下文：已获取的条目、工具调用结果、中间决策 |
| **管理策略** | 滑动窗口，保留最近 15 轮（一轮 = 一个节点的输入/输出） |
| **检索方式** | 顺序访问，随 State 流转自动携带 |
| **更新时机** | 每个节点执行后自动追加；窗口满时丢弃最早的 3 轮 |
| **生命周期** | 单次任务结束后清空 |

### 4.2 长期记忆 (Long-term Memory)

| 属性 | 设计 |
|------|------|
| **存储** | ChromaDB (向量) + SQLite (结构化) 双存储 |
| **ChromaDB Collection** | `user_preferences` — 用户偏好向量 |
| **ChromaDB Collection** | `content_embeddings` — 历史条目的 embedding（用于去重和相似度检索） |
| **SQLite 表** | `user_preference_keywords` — 关键词权重表（结构化，精确查询） |
| **内容** | 用户偏好的向量表示、关键词权重、历史条目的 embedding 向量 |
| **检索方式** | 向量检索：ChromaDB cosine similarity top-k；结构化检索：SQLite 按关键词和时间范围 |
| **更新时机** | 每次用户反馈（点赞/踩）后，重新计算偏好向量并更新 |
| **Embedding 模型** | `text2vec-base-chinese`（本地推理，国内可用，中文效果好） |

**偏好更新机制：**
```
用户 positive 反馈 → 对该条目的 category/keyword 权重 +0.1
用户 negative 反馈 → 对该条目的 category/keyword 权重 -0.05
用户 irrelevant 反馈 → 该条目的 topic 权重 -0.15
权重范围: [0.0, 1.0]，低于 0.1 的关键词自动清理
```

### 4.3 情节记忆 (Episodic Memory)

| 属性 | 设计 |
|------|------|
| **存储** | SQLite `episodic_memory` 表 |
| **内容** | 每次简报生成的任务记录：触发时间、采集来源、条目数、去重率、用户反馈统计、执行耗时、异常记录 |
| **记录格式** | 每次任务完成后写入一条 JSON 格式的记录 |
| **检索方式** | 按任务类型 + 时间范围查询（"上次 AI Agent 领域的简报采集了多少条？"） |
| **更新时机** | 每次 `memory_update` 节点执行时写入 |
| **用途** | 帮助 Agent 理解历史执行模式，例如："上次搜索新能源车时 SearXNG 超时了，这次要加 fallback" |

**情节记忆记录示例：**
```json
{
    "task_id": "2026-06-17-001",
    "trigger": "scheduled",
    "topics": ["AI Agent", "新能源车"],
    "sources_used": ["36kr_rss", "huxiu_rss", "searxng"],
    "raw_count": 87,
    "after_dedup": 52,
    "dedup_rate": 0.40,
    "categories": {"AI Agent": 18, "新能源车": 22, "其他": 12},
    "feedback_summary": null,
    "errors": [],
    "duration_seconds": 45,
    "created_at": "2026-06-17T08:00:00+08:00"
}
```

### 4.4 语义记忆 (Semantic Memory)

| 属性 | 设计 |
|------|------|
| **存储** | ChromaDB `domain_knowledge` collection |
| **内容** | 领域事实知识，如 "DeepSeek 是一家中国 AI 公司"、"RAG 是检索增强生成的缩写" |
| **检索方式** | 向量检索，作为 LLM 生成摘要和分类时的 RAG 上下文补充 |
| **更新时机** | MVP 阶段手动维护（预置种子数据），后续通过 Agent 自主学习扩展 |
| **MVP 简化** | 通过 `user_topics` 关键词匹配 SQLite 中的种子知识表，不做全量 RAG |

---

## 5. 排序算法设计

### 5.1 综合打分公式

每条信息条目 `i` 的最终得分：

```
Score(i) = w_sim × S_sim(i) + w_time × S_time(i) + w_pref × S_pref(i)
```

**默认权重（可在用户设置中调整）：**
- `w_sim = 0.3` （相关性权重）
- `w_time = 0.25` （时效性权重）
- `w_pref = 0.45` （偏好权重）

### 5.2 各分项计算

**相关性得分 S_sim(i)：**
```
S_sim(i) = cosine_similarity(embedding(title + content), user_topic_embedding)
```
- 用用户关注领域的文本 embedding 与条目 embedding 的余弦相似度
- 范围 [0, 1]

**时效性得分 S_time(i)：**
```
S_time(i) = e^(-λ × hours_elapsed)
```
- `hours_elapsed` = 当前时间 - 条目发布时间（小时）
- `λ = 0.05` （衰减系数，24 小时内保持 > 0.3，72 小时后趋近 0）
- 范围 (0, 1]

**偏好得分 S_pref(i)：**
```
S_pref(i) = α × topic_weight(category) + β × keyword_match(title, user_keywords)
```
- `α = 0.6`, `β = 0.4`
- `topic_weight(category)` = 该分类在用户历史反馈中的平均权重
- `keyword_match(title, user_keywords)` = 标题中命中用户偏好关键词的比例
- 范围 [0, 1]

### 5.3 重排序调整

- `importance = 5` 的条目：Score × 1.3（重要性加分）
- `importance = 1` 的条目：Score × 0.7（降权）
- 同一分类下最多保留 8 条（避免单个分类霸榜）

---

## 6. 去重策略设计

### 6.1 两阶段去重

**第一阶段：快速过滤（精确去重）**
- 基于 URL 的 MD5 hash：相同 URL 直接去重
- 基于标题完全匹配：标题去除标点后完全一致则去重
- 时间复杂度 O(n)，用于快速去除明显重复

**第二阶段：语义去重（向量 + 编辑距离）**

```python
def is_duplicate(item_a, item_b, config):
    # 1. 向量相似度
    cosine_sim = cosine_similarity(item_a.embedding, item_b.embedding)
    
    # 2. 标题编辑距离归一化
    title_sim = 1 - (levenshtein(item_a.title, item_b.title) / max(len(item_a.title), len(item_b.title)))
    
    # 3. 综合判定
    combined = 0.6 * cosine_sim + 0.4 * title_sim
    
    return combined >= config.dedup_threshold
```

### 6.2 阈值设定

| 阈值 | 值 | 说明 |
|------|-----|------|
| `exact_dedup_threshold` | 1.0 | URL hash 或标题完全一致 |
| `semantic_dedup_threshold` | 0.85 | 向量+编辑距离综合分 ≥ 0.85 判定为重复 |
| `merge_threshold` | 0.70 | 0.70-0.85 之间：同事件不同角度，保留信息量更大的那条 |

### 6.3 区分「同事件不同角度」vs「真正重复」

```
综合分 ≥ 0.85  →  真正重复，标记 is_duplicate=True，保留原文更长的那条
0.70 ≤ 综合分 < 0.85  →  可能是同事件不同报道，保留两条但标记 duplicate_of 关联
综合分 < 0.70  →  不同事件，保留
```

**对于"同事件不同角度"的处理：**
- 两条都保留，但在简报中归为一组
- 选择信息量更大（content 更长）的那条作为"主条目"
- 另一条作为"相关报道"附在主条目下方

### 6.4 校准方法

MVP 阶段通过以下方式校准阈值：
1. 手动构造 20 对测试数据（10 对真正重复 + 10 对同事件不同报道）
2. 调整阈值直到准确率 ≥ 90%
3. 将校准结果记录在情节记忆中

---

## 7. 数据模型

### SQLite 表结构

```sql
-- 用户表
CREATE TABLE users (
    user_id         TEXT PRIMARY KEY,           -- 用户唯一 ID
    username        TEXT NOT NULL,              -- 用户名
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    settings_json   TEXT DEFAULT '{}'           -- 用户设置 JSON（偏好权重等）
);

-- 信息源表
CREATE TABLE sources (
    source_id       TEXT PRIMARY KEY,           -- 源 ID（如 "36kr_rss"）
    source_type     TEXT NOT NULL,              -- "rss" / "search_engine"
    url             TEXT,                       -- RSS URL 或搜索引擎标识
    name            TEXT NOT NULL,              -- 显示名称
    is_active       INTEGER DEFAULT 1,          -- 是否启用
    last_fetched_at TEXT,                       -- 上次采集时间
    fetch_config    TEXT DEFAULT '{}'           -- 采集配置 JSON
);

-- 信息源-用户关联表
CREATE TABLE user_sources (
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    source_id       TEXT NOT NULL REFERENCES sources(source_id),
    PRIMARY KEY (user_id, source_id)
);

-- 信息条目表
CREATE TABLE items (
    item_id         TEXT PRIMARY KEY,           -- 条目唯一 ID（URL hash）
    title           TEXT NOT NULL,              -- 标题
    content         TEXT,                       -- 正文内容
    url             TEXT NOT NULL,              -- 原始链接
    source_id       TEXT REFERENCES sources(source_id),
    published_at    TEXT,                       -- 发布时间
    fetched_at      TEXT NOT NULL DEFAULT (datetime('now')),
    category        TEXT,                       -- 分类标签
    importance      INTEGER DEFAULT 3,          -- 重要性 1-5
    summary         TEXT,                       -- Agent 生成的摘要
    score           REAL,                       -- 排序得分
    embedding_id    TEXT,                       -- ChromaDB 向量 ID
    is_duplicate    INTEGER DEFAULT 0,          -- 是否重复
    duplicate_of    TEXT REFERENCES items(item_id),  -- 重复的主条目
    content_hash    TEXT                        -- 内容 hash（快速去重用）
);

CREATE INDEX idx_items_published ON items(published_at);
CREATE INDEX idx_items_category ON items(category);
CREATE INDEX idx_items_score ON items(score DESC);

-- 用户反馈表
CREATE TABLE feedback (
    feedback_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    item_id         TEXT NOT NULL REFERENCES items(item_id),
    feedback_type   TEXT NOT NULL CHECK (feedback_type IN ('positive', 'negative', 'irrelevant')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, item_id)
);

-- 简报表
CREATE TABLE briefings (
    briefing_id     TEXT PRIMARY KEY,           -- 简报 ID
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    generated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    content_json    TEXT NOT NULL,              -- 完整简报 JSON
    total_items     INTEGER,                   -- 原始条目数
    final_items     INTEGER,                   -- 去重后条目数
    status          TEXT DEFAULT 'delivered'    -- "generating" / "delivered" / "failed"
);

-- 简报-条目关联表
CREATE TABLE briefing_items (
    briefing_id     TEXT NOT NULL REFERENCES briefings(briefing_id),
    item_id         TEXT NOT NULL REFERENCES items(item_id),
    section         TEXT,                      -- 分类名
    display_order   INTEGER,                   -- 显示顺序
    PRIMARY KEY (briefing_id, item_id)
);

-- 用户偏好关键词表
CREATE TABLE user_preference_keywords (
    user_id         TEXT NOT NULL REFERENCES users(user_id),
    keyword         TEXT NOT NULL,              -- 关键词
    weight          REAL DEFAULT 0.5,           -- 权重 [0.0, 1.0]
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, keyword)
);

-- 情节记忆表
CREATE TABLE episodic_memory (
    record_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,              -- 任务 ID
    task_type       TEXT NOT NULL,              -- "briefing_generation" / "feedback_learning"
    trigger_type    TEXT,                       -- "scheduled" / "manual" / "feedback"
    topics          TEXT,                       -- JSON 数组
    details_json    TEXT NOT NULL,              -- 完整执行记录 JSON
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_episodic_task_type ON episodic_memory(task_type, created_at);
```

---

## 8. 技术栈选择

| 层级 | 技术选型 | 选择理由 |
|------|----------|----------|
| **LLM** | DeepSeek API (`deepseek-chat`) | 国内可用，性价比高，支持 Function Calling，中文能力强 |
| **LLM 备选** | 通义千问 (`qwen-plus`) | 备选方案，DeepSeek 不可用时切换 |
| **Agent 框架** | LangGraph | 有状态工作流，支持并行节点、条件边、持久化，比纯 LangChain Agent 更可控 |
| **Embedding** | `text2vec-base-chinese` (本地) | 中文语义向量化效果好，本地推理零成本，ChromaDB 兼容 |
| **向量数据库** | ChromaDB | 轻量嵌入式，单机可跑，Python 原生，与 LangGraph 集成简单 |
| **关系数据库** | SQLite | MVP 阶段足够，无需额外部署，事务支持好 |
| **RSS 解析** | `feedparser` | Python 生态最成熟的 RSS 解析库，支持 RSS 2.0 / Atom |
| **搜索引擎** | SearXNG (自建) / Tavily (API) | SearXNG 开源免费可自建，Tavily 作为 fallback |
| **文本处理** | `jieba` 分词 + 自定义停用词表 | 中文关键词提取和匹配 |
| **标题相似度** | `python-Levenshtein` | 编辑距离计算，去重的辅助判定 |
| **定时调度** | `APScheduler` | Python 内置调度器，支持 cron 表达式，MVP 阶段单机运行 |
| **前端** | Streamlit | 快速搭建，Python 全栈，支持 session state 做实时更新 |
| **MCP** | `mcp` Python SDK (官方) | MCP 标准化协议，stdio 模式最简 |
| **配置管理** | `pydantic-settings` | 类型安全的配置管理，支持 `.env` 文件 |
| **日志** | `loguru` | 比标准库 logging 更易用，结构化输出 |

---

## 9. MVP 范围界定

### MVP 必须实现（P0）

| 功能 | 说明 |
|------|------|
| RSS 采集 | 从 3-5 个配置的 RSS 源获取最新条目 |
| 搜索采集 | 通过 SearXNG API 搜索用户关注的关键词 |
| 向量去重 | 基于 embedding 的语义去重 + 标题编辑距离 |
| LLM 分类 | DeepSeek 对每条内容分类 + 重要性评估 |
| LLM 摘要 | DeepSeek 生成 2-3 句中文摘要 |
| 综合排序 | 向量相似度 + 时间衰减 + 偏好权重打分 |
| 简报生成 | 结构化简报（分类组织 + 来源引用） |
| 用户偏好存储 | SQLite 关键词权重 + ChromaDB 偏好向量 |
| 反馈学习 | 点赞/踩 → 更新偏好权重 |
| Streamlit 展示 | 简报展示页面 + 反馈按钮 |
| Streamlit 设置 | 用户关注领域配置 + RSS 源管理 |
| LangGraph 工作流 | 完整的 StateGraph + ReAct + 反思 |
| 情节记忆 | 每次任务的执行记录写入 SQLite |
| 单用户 | MVP 只支持一个用户 |

### 后续迭代才加（P1-P3）

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 定时调度 | P1 | APScheduler 按 cron 定时触发 |
| 多用户支持 | P1 | 多用户注册 + 偏好隔离 |
| 推送通知 | P1 | 微信/Bot/邮件推送简报 |
| MCP 搜索服务 | P1 | 独立 MCP Server 管理搜索 API |
| MCP 推送服务 | P2 | 独立 MCP Server 管理多渠道推送 |
| 反思修正闭环 | P2 | 反思后自动调整 prompt 重试 |
| 长期记忆 RAG | P2 | 语义记忆的完整 RAG 检索 |
| 图片/多媒体条目 | P2 | RSS 中的图片和视频内容处理 |
| 数据导出 | P3 | 简报导出为 Markdown/PDF |
| API 接口 | P3 | RESTful API 供外部调用 |
| 多语言支持 | P3 | 英文/日文信息源 |
| A/B 测试 | P3 | 排序算法对比实验 |

---

## 10. 阶段性目标与任务拆解

### 阶段 P0：脚手架搭建

**阶段目标：** 项目基础骨架跑通，能验证 LLM 调用和基本数据流

**交付物：**
- 可运行的 Python 项目结构
- LangGraph StateGraph 框架搭建完成（空节点可执行）
- DeepSeek API 调用成功，能返回结构化 JSON
- SQLite 数据库初始化脚本，所有表创建成功
- ChromaDB 集合初始化成功
- 验证方式：运行 `python -m feedlens` 能走完一个空的 StateGraph 流程

**关键任务：**
1. 搭建项目目录结构（`feedlens/`、`config/`、`tests/`）
2. 配置管理：`pydantic-settings` 管理 API Key、数据库路径等
3. 实现 `FeedLensState` TypedDict
4. 实现空的 LangGraph StateGraph（所有节点先做 pass-through）
5. DeepSeek API 调用封装（支持 Function Calling 格式）
6. SQLite 数据库迁移脚本（创建所有表）
7. ChromaDB 连接和 Collection 初始化
8. 基础日志和错误处理

**依赖的前一阶段：** 无

**预估复杂度：** 中

---

### 阶段 P1：RSS 采集 + 搜索采集流水线

**阶段目标：** 能从真实 RSS 源和搜索引擎采集到信息条目

**交付物：**
- `rss_fetch` 工具实现，能从 RSS URL 获取并解析条目
- `web_search` MCP Server 实现（SearXNG 封装）
- `feedparser` 解析 + 条目标准化逻辑
- 原始条目写入 SQLite `items` 表
- 验证方式：运行采集流程后，SQLite 中有 ≥20 条来自不同 RSS 源的条目

**关键任务：**
1. 实现 `rss_fetch` 工具（feedparser 解析 + 时间过滤）
2. 配置初始 RSS 源列表（36kr、虎嗅、InfoQ 等）
3. 实现 `feedlens-search-server` MCP Server（stdio 模式）
4. 搜索结果 → `FeedItem` 标准化转换
5. `fetch_rss` 和 `search_web` 节点接入 LangGraph StateGraph
6. 条目写入 SQLite `items` 表
7. 验证 RSS 采集的覆盖度和稳定性

**依赖的前一阶段：** P0

**预估复杂度：** 中

---

### 阶段 P2：去重 + 分类 + 摘要

**阶段目标：** 采集到的条目能自动去重、分类、生成摘要

**交付物：**
- 向量去重实现（ChromaDB embedding 存储 + 余弦相似度）
- 标题编辑距离去重实现
- `content_classify` 工具实现（LLM 分类 + 重要性标注）
- `text_summarize` 工具实现（LLM 生成中文摘要）
- 去重率 ≥ 30%（对于有重叠的 RSS 源）
- 验证方式：对 50 条原始条目执行去重+分类+摘要后，输出条目数量合理、分类标签正确、摘要通顺

**关键任务：**
1. Embedding 模型集成（`text2vec-base-chinese` 本地推理）
2. 实现 `deduplicate_check` 工具（两阶段去重逻辑）
3. ChromaDB `content_embeddings` collection 管理
4. 实现 `content_classify` 工具（prompt 设计 + 结构化输出解析）
5. 实现 `text_summarize` 工具
6. `deduplicate`、`classify`、`summarize` 节点接入 StateGraph
7. 去重阈值校准（20 对测试数据）
8. 分类 prompt 调优（确保类别一致性）

**依赖的前一阶段：** P1

**预估复杂度：** 高

---

### 阶段 P3：排序 + 简报生成

**阶段目标：** 排序后的条目能生成结构化简报

**交付物：**
- `score_and_rank` 工具实现（综合打分公式）
- 简报生成逻辑（LLM 生成分类组织 + 重要性标注 + 来源引用的 Markdown 简报）
- 反思模块实现（LLM 审查简报质量）
- 验证方式：生成的简报包含 ≥3 个分类，每个分类有重要性标签，来源链接可点击

**关键任务：**
1. 实现 `score_and_rank` 工具（打分公式 + 重排序逻辑）
2. 实现 `rank` 节点（调用打分工具 + 排序）
3. 简报生成 prompt 设计（输出结构化 JSON）
4. 简报 JSON → Markdown 渲染
5. 反思模块 prompt 设计（质量审查标准）
6. 反思 → 修正 → 重新反思的循环逻辑
7. `rank`、`summarize`、`reflect`、`revise` 节点接入 StateGraph
8. 简报质量手动验证（10 份简报人工评估）

**依赖的前一阶段：** P2

**预估复杂度：** 高

---

### 阶段 P4：用户偏好 + 反馈学习

**阶段目标：** 用户反馈能影响后续排序和筛选

**交付物：**
- 用户偏好查询工具实现
- 反馈处理流程（点赞/踩 → 更新偏好权重）
- 偏好向量重算逻辑
- 验证方式：对 5 条内容点赞后重新排序，偏好相关条目排名上升

**关键任务：**
1. 实现 `user_preference_query` 工具
2. `user_preference_keywords` 表的读写逻辑
3. ChromaDB `user_preferences` collection 管理
4. 反馈事件处理：positive/negative/irrelevant → 权重更新
5. 偏好向量重算（关键词权重变化 → embedding 更新）
6. `recall_memory` 节点实现（偏好检索 + 情节记忆检索）
7. `memory_update` 节点实现（写入情节记忆 + 更新偏好）
8. 偏好影响排序的端到端验证

**依赖的前一阶段：** P3

**预估复杂度：** 中

---

### 阶段 P5：Streamlit UI

**阶段目标：** 有可用的前端界面，用户能操作整个系统

**交付物：**
- 简报展示页面（分类展示 + 重要性标注 + 反馈按钮）
- 设置页面（关注领域管理 + RSS 源管理）
- 手动触发采集按钮
- 验证方式：用户通过 Streamlit UI 完成一次完整流程：设置领域 → 触发采集 → 查看简报 → 提交反馈

**关键任务：**
1. Streamlit 项目结构搭建
2. 简报展示页面：分类卡片 + 重要性标签 + 来源链接 + 反馈按钮
3. 设置页面：领域标签管理（增删改）+ RSS 源管理
4. 手动触发按钮 → 调用 LangGraph workflow
5. 实时状态展示（采集进度、去重统计）
6. 反馈交互 → 写入 feedback 表 + 触发偏好更新
7. session state 管理（当前简报、用户配置）
8. 基础样式美化（Streamlit 原生组件 + 自定义 CSS 微调）

**依赖的前一阶段：** P4

**预估复杂度：** 中

---

### 阶段 P6：工程化 + 部署

**阶段目标：** 项目工程化完成，可作为简历项目展示

**交付物：**
- 完整的 `README.md`（项目介绍 + 架构图 + 快速开始）
- `requirements.txt` / `pyproject.toml`
- 配置文件模板（`.env.example`）
- 单元测试覆盖核心逻辑（去重、排序、打分）
- 验证方式：新人 clone 项目后 3 步启动（安装依赖 → 配置 → 运行）

**关键任务：**
1. 项目打包（pyproject.toml）
2. README 撰写（架构说明 + 技术选型理由 + 效果展示）
3. `.env.example` 模板（API Key、数据库路径、RSS 源配置）
4. 核心逻辑单元测试（去重阈值、打分公式、偏好更新）
5. 集成测试（端到端采集→简报生成流程）
6. Docker 化（可选，MVP 可跳过）
7. 代码清理和注释
8. 效果截图和演示 GIF

**依赖的前一阶段：** P5

**预估复杂度：** 中

---

**阶段依赖关系：**

```
P0 → P1 → P2 → P3 → P4 → P5 → P6
```

每个阶段都是独立可验证的交付单元。P0-P3 构成核心数据管线（采集→去重→分类→排序→简报），P4 加入记忆和学习能力，P5 加入用户界面，P6 做收尾工程化。