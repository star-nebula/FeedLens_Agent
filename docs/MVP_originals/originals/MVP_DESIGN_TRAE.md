# FeedLens — 智能信息简报 Agent MVP 方案

## 一、系统架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FeedLens Agent                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────┐     ┌─────────────────┐                       │
│  │   感知层(Input)  │     │   工具层(Tools)  │                       │
│  │                 │     │                 │                       │
│  │ • 用户配置输入   │     │ • RSS采集器     │ ← Function Calling    │
│  │ • 反馈交互       │     │ • 文本摘要器    │ ← Function Calling    │
│  │ • 定时触发信号   │     │ • 简报生成器    │ ← Function Calling    │
│  │ • 工具返回结果   │     │                 │                       │
│  │                 │     │ • 搜索引擎      │ ← MCP Server(SSE)     │
│  └────────┬────────┘     │ • 推送通知      │ ← MCP Server(stdio)   │
│           │              │ • 向量数据库    │ ← MCP Server(stdio)   │
│           ▼              └────────┬────────┘                       │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                    大脑(Brain) - LLM                        │   │
│  │              DeepSeek / 通义千问 API                        │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐        │   │
│  │  │ 意图理解 │ │ 推理决策 │ │ 工具调用 │ │ 反思修正 │        │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│           │              │              │                          │
│           ▼              ▼              ▼                          │
│  ┌─────────────────┐ ┌───────────┐ ┌─────────────────────┐        │
│  │   记忆层(Memory)│ │ 规划层    │ │ LangGraph StateGraph│        │
│  │                 │ │(Planning) │ │                     │        │
│  │ • 短期记忆      │ │ • ReAct   │ │ • 状态节点定义      │        │
│  │   滑动窗口      │ │   循环    │ │ • 边连接逻辑        │        │
│  │ • 长期记忆      │ │ • 反思    │ │ • 条件分支          │        │
│  │   ChromaDB      │ │   审查    │ │ • 终止条件          │        │
│  │ • 情节记忆      │ │ • 任务    │ │                     │        │
│  │   SQLite        │ │   规划    │ └─────────────────────┘        │
│  │ • 语义记忆      │ │           │                                 │
│  │   RAG检索       │ │           │                                 │
│  └─────────────────┘ └───────────┘                                 │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │                      输出层(Output)                          │   │
│  │  • Streamlit 前端展示    • 结构化简报内容    • 推送通知      │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

## 二、Agent 工作流设计（LangGraph StateGraph）

### 2.1 State 定义（TypedDict）

```python
from typing import TypedDict, List, Optional, Dict, Any
from datetime import datetime

class FeedItem(TypedDict):
    id: str
    title: str
    content: str
    source: str
    url: str
    publish_time: datetime
    category: str
    raw_content: str
    summary: Optional[str]
    embedding: Optional[List[float]]

class BriefEntry(TypedDict):
    feed_item_id: str
    importance: int  # 1-5
    tags: List[str]
    summary: str

class FeedLensState(TypedDict):
    # 配置
    user_id: str
    interests: List[str]
    sources: List[Dict[str, Any]]
    
    # 采集状态
    raw_items: List[FeedItem]
    deduped_items: List[FeedItem]
    ranked_items: List[FeedItem]
    
    # 处理状态
    current_step: str
    processed_count: int
    total_count: int
    
    # 简报状态
    brief_entries: List[BriefEntry]
    brief_content: str
    brief_generated: bool
    
    # 记忆状态
    user_preferences: Dict[str, float]
    recent_interactions: List[Dict[str, Any]]
    
    # 工具调用记录
    tool_calls: List[Dict[str, Any]]
    tool_results: List[Dict[str, Any]]
    
    # 反思状态
    reflection_notes: List[str]
    errors: List[str]
    
    # 时间状态
    run_time: datetime
    scheduled_time: Optional[datetime]
```

### 2.2 节点定义

| 节点名称 | 功能描述 | 输入 | 输出 |
|---------|---------|------|------|
| `init_planning` | 初始化任务规划，确定采集策略 | 用户配置 | 采集任务列表 |
| `collect_rss` | 从 RSS 源采集内容 | 源列表 | 原始条目 |
| `collect_search` | 从搜索引擎采集补充内容 | 兴趣关键词 | 搜索结果 |
| `deduplicate` | 向量去重处理 | 原始条目 | 去重后条目 |
| `rank_items` | 根据偏好和相似度排序 | 去重条目 | 排序后条目 |
| `generate_summary` | 生成单条内容摘要 | 条目列表 | 带摘要条目 |
| `compile_brief` | 编译结构化简报 | 排序条目 | 简报内容 |
| `push_notification` | 推送简报给用户 | 简报内容 | 推送状态 |
| `reflect` | 反思本次执行，记录经验 | 完整执行记录 | 反思笔记 |
| `update_memory` | 更新长期记忆 | 执行结果+反馈 | 记忆更新 |

### 2.3 边连接逻辑

```
init_planning → collect_rss → collect_search → deduplicate 
                                                    │
                                                    ▼
                                              rank_items → generate_summary → compile_brief 
                                                                                 │
                                              ┌─────────────────────────────────┘
                                              ▼
                                        push_notification → reflect → update_memory → END
                                              │
                                              ▼
                                         (用户反馈)
                                              │
                                              ▼
                                        update_memory → END
```

### 2.4 条件分支

```python
# 分支1: 是否需要补充搜索
if len(raw_items) < MIN_ITEMS_PER_TOPIC:
    edge: collect_rss → collect_search
else:
    edge: collect_rss → deduplicate

# 分支2: 是否有新内容
if len(deduped_items) == 0:
    edge: deduplicate → END (跳过简报生成)

# 分支3: 推送失败重试
if push_notification.failed:
    edge: push_notification → push_notification (重试最多3次)
else:
    edge: push_notification → reflect
```

## 三、工具清单

### 3.1 RSS 采集器 — Function Calling

**选择理由**：逻辑简单（HTTP 请求 + XML 解析），参数明确，无需跨进程复用，直接作为函数调用更高效。

```python
# 工具定义
name: "collect_rss_feed"
description: "从指定的 RSS 订阅源采集最新文章内容"
parameters:
  type: object
  properties:
    feed_url:
      type: string
      description: "RSS feed 的 URL 地址"
    max_items:
      type: integer
      description: "每个源最多采集的条目数"
      default: 10
    category:
      type: string
      description: "内容分类标签"
  required: [feed_url, category]

# 返回格式
returns: List[FeedItem]
```

### 3.2 文本摘要器 — Function Calling

**选择理由**：纯文本处理，输入输出明确，无需外部服务，适合 Function Calling。

```python
# 工具定义
name: "generate_text_summary"
description: "对文章内容生成简洁摘要（100-200字）"
parameters:
  type: object
  properties:
    content:
      type: string
      description: "需要摘要的原始文本内容"
    max_length:
      type: integer
      description: "摘要最大长度（字符数）"
      default: 200
    language:
      type: string
      description: "输出语言"
      default: "zh"
  required: [content]

# 返回格式
returns: str (摘要文本)
```

### 3.3 简报生成器 — Function Calling

**选择理由**：基于排序后的条目生成结构化简报，逻辑集中，参数明确。

```python
# 工具定义
name: "compile_daily_brief"
description: "将排序后的信息条目编译成结构化日报简报"
parameters:
  type: object
  properties:
    items:
      type: array
      items: FeedItem
      description: "排序后的信息条目列表"
    user_interests:
      type: array
      items: string
      description: "用户关注的领域关键词"
    date:
      type: string
      description: "简报日期（YYYY-MM-DD）"
  required: [items, user_interests, date]

# 返回格式
returns: str (Markdown 格式简报)
```

### 3.4 搜索引擎 — MCP Server（SSE 模式）

**选择理由**：需要独立部署（避免 API Key 暴露在 Agent 代码中），跨进程复用，支持流式返回，适合 SSE 模式。

```yaml
# MCP Server 配置
name: "search_engine"
description: "基于关键词的网络搜索服务"
deployment_mode: "SSE"  # Server-Sent Events 流式返回
port: 8001

# 工具定义
tools:
  - name: "web_search"
    description: "搜索与关键词相关的最新网络内容"
    parameters:
      type: object
      properties:
        query:
          type: string
          description: "搜索关键词"
        max_results:
          type: integer
          description: "返回结果数量"
          default: 10
        time_range:
          type: string
          description: "时间范围：day/week/month"
          default: "day"
      required: [query]
    returns: List[Dict[str, Any]]

# 部署方式
# 独立 FastAPI 服务，通过 SSE 流式返回搜索结果
```

### 3.5 推送通知 — MCP Server（stdio 模式）

**选择理由**：推送通道多样化（邮件/企业微信/飞书），需要独立管理凭证，适合作为 stdio 模式的 MCP Server，便于扩展新通道。

```yaml
# MCP Server 配置
name: "notification_service"
description: "多渠道推送通知服务"
deployment_mode: "stdio"

# 工具定义
tools:
  - name: "send_email"
    description: "发送邮件通知"
    parameters:
      type: object
      properties:
        to:
          type: string
          description: "收件人邮箱"
        subject:
          type: string
          description: "邮件主题"
        body:
          type: string
          description: "邮件正文（支持 Markdown）"
      required: [to, subject, body]
    returns: Dict[str, bool]

  - name: "send_wechat"
    description: "发送企业微信消息"
    parameters:
      type: object
      properties:
        user_id:
          type: string
          description: "企业微信用户ID"
        content:
          type: string
          description: "消息内容"
      required: [user_id, content]
    returns: Dict[str, bool]
```

### 3.6 向量数据库 — MCP Server（stdio 模式）

**选择理由**：ChromaDB 作为独立服务运行，支持跨 Agent 共享，需要标准化的 CRUD 接口，适合 stdio 模式。

```yaml
# MCP Server 配置
name: "vector_store"
description: "向量存储与检索服务（ChromaDB）"
deployment_mode: "stdio"

# 工具定义
tools:
  - name: "add_embeddings"
    description: "添加向量到数据库"
    parameters:
      type: object
      properties:
        collection_name:
          type: string
          description: "集合名称"
        documents:
          type: array
          items: string
          description: "文档内容列表"
        metadatas:
          type: array
          items: object
          description: "元数据列表"
        ids:
          type: array
          items: string
          description: "文档ID列表"
      required: [collection_name, documents, metadatas, ids]
    returns: Dict[str, Any]

  - name: "query_embeddings"
    description: "向量相似度查询"
    parameters:
      type: object
      properties:
        collection_name:
          type: string
          description: "集合名称"
        query_texts:
          type: array
          items: string
          description: "查询文本列表"
        n_results:
          type: integer
          description: "返回结果数量"
          default: 5
        where:
          type: object
          description: "过滤条件"
    returns: Dict[str, Any]

  - name: "update_embeddings"
    description: "更新已有向量"
    parameters:
      type: object
      properties:
        collection_name:
          type: string
        ids:
          type: array
          items: string
        documents:
          type: array
          items: string
        metadatas:
          type: array
          items: object
      required: [collection_name, ids]
    returns: Dict[str, Any]
```

## 四、记忆系统设计

### 4.1 短期记忆

| 项目 | 说明 |
|------|------|
| **存储方式** | LangGraph State 中的 `recent_interactions` 字段 |
| **存储内容** | 最近 10-20 轮对话/交互记录（用户反馈、工具调用结果） |
| **管理策略** | 滑动窗口，超过阈值时自动丢弃最旧记录 |
| **检索方式** | 直接从 State 读取 |
| **更新时机** | 每次用户交互或工具调用后更新 |

### 4.2 长期记忆（用户偏好）

| 项目 | 说明 |
|------|------|
| **存储方式** | ChromaDB 向量数据库 |
| **存储内容** | 用户对每条信息的反馈（点赞/踩）、偏好关键词及其权重 |
| **数据结构** | `{content: str, feedback: int, timestamp: datetime, user_id: str}` |
| **检索方式** | 向量相似度查询（与新条目计算相似度） |
| **更新时机** | 用户反馈后立即更新；定时执行时批量更新 |

### 4.3 情节记忆

| 项目 | 说明 |
|------|------|
| **存储方式** | SQLite 关系型数据库 |
| **存储内容** | 每次任务执行记录（采集源、处理条目数、去重数、用户反馈率等） |
| **数据结构** | `execution_id, user_id, start_time, end_time, status, metrics, notes` |
| **检索方式** | SQL 查询，按时间/用户筛选 |
| **更新时机** | 每次任务执行完成后写入 |

### 4.4 语义记忆

| 项目 | 说明 |
|------|------|
| **存储方式** | ChromaDB 向量数据库（独立 collection） |
| **存储内容** | 领域知识、术语定义、历史事件摘要 |
| **检索方式** | RAG 检索，在生成摘要/简报时补充背景知识 |
| **更新时机** | 定期从权威来源同步；用户手动添加 |

## 五、排序算法设计

### 5.1 打分公式

```
score(item) = w_sim * sim_score + w_time * time_score + w_pref * pref_score + w_cat * cat_score
```

### 5.2 权重配置

| 权重 | 符号 | 默认值 | 说明 |
|------|------|--------|------|
| 相似度权重 | w_sim | 0.35 | 与用户偏好的向量相似度 |
| 时间权重 | w_time | 0.30 | 内容新鲜度 |
| 偏好权重 | w_pref | 0.25 | 用户历史反馈学习 |
| 分类权重 | w_cat | 0.10 | 匹配用户关注领域 |

### 5.3 各因子计算

```python
# 1. 相似度分数 (0-1)
sim_score = cosine_similarity(item.embedding, user_preferences_embedding)

# 2. 时间分数 (0-1)
# 指数衰减：越新的内容分数越高
time_diff_hours = (now - item.publish_time).total_seconds() / 3600
time_score = exp(-time_diff_hours / HALF_LIFE_HOURS)  # HALF_LIFE = 24小时

# 3. 偏好分数 (-1 到 +1)
# 基于用户历史反馈学习
pref_score = sum(feedback * similarity(item, historical_item) 
                 for feedback, historical_item in user_history)

# 4. 分类分数 (0-1)
cat_score = 1.0 if item.category in user_interests else 0.5
```

### 5.4 权重动态调整

```python
# 根据用户反馈调整权重
if user_feedback == "relevant" and current_score < 0.7:
    w_pref += 0.02
    w_sim += 0.01
    
if user_feedback == "irrelevant" and current_score > 0.3:
    w_pref += 0.03
    w_sim -= 0.01

# 权重归一化
total = w_sim + w_time + w_pref + w_cat
w_sim /= total; w_time /= total; w_pref /= total; w_cat /= total
```

## 六、去重策略设计

### 6.1 向量去重流程

```
原始条目 → 生成向量 → 相似度比对 → 阈值判断 → 去重结果
```

### 6.2 阈值设定

| 场景 | 阈值 | 说明 |
|------|------|------|
| **严格去重** | cosine_similarity > 0.90 | 同一事件的完全重复报道 |
| **合并去重** | 0.75 < cosine_similarity ≤ 0.90 | 同一事件不同来源的报道，保留信息最完整的 |
| **不同角度** | cosine_similarity ≤ 0.75 | 不同事件或同一事件的不同视角，保留 |

### 6.3 校准方法

```python
# 定期校准：用人工标注的重复/非重复样本测试阈值
def calibrate_threshold(samples: List[Tuple[FeedItem, FeedItem, bool]]):
    thresholds = [0.7, 0.75, 0.8, 0.85, 0.9, 0.95]
    for threshold in thresholds:
        tp = fp = tn = fn = 0
        for item1, item2, is_duplicate in samples:
            sim = cosine_similarity(item1.embedding, item2.embedding)
            predicted = sim > threshold
            if is_duplicate and predicted: tp += 1
            elif not is_duplicate and predicted: fp += 1
            elif not is_duplicate and not predicted: tn += 1
            else: fn += 1
        # 选择 F1 分数最高的阈值
```

### 6.4 区分策略

```python
def is_duplicate(item1: FeedItem, item2: FeedItem, threshold: float = 0.85):
    sim = cosine_similarity(item1.embedding, item2.embedding)
    
    if sim > 0.90:
        # 完全重复：保留来源更权威、内容更完整的
        return True, "strict"
    elif sim > 0.75:
        # 需要进一步判断是否为同一事件不同角度
        if share_same_event(item1, item2):
            return True, "merge"
        else:
            return False, "different_angle"
    else:
        return False, "different"

def share_same_event(item1, item2):
    # 判断是否为同一事件：标题关键词重叠率 > 60%
    keywords1 = extract_keywords(item1.title)
    keywords2 = extract_keywords(item2.title)
    overlap = len(set(keywords1) & set(keywords2)) / max(len(keywords1), len(keywords2))
    return overlap > 0.6
```

## 七、数据模型（SQLite 表结构）

### 7.1 users 表 — 用户信息

```sql
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    wechat_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 7.2 interests 表 — 用户关注领域

```sql
CREATE TABLE IF NOT EXISTS interests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    keyword TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, keyword)
);
```

### 7.3 sources 表 — 信息源配置

```sql
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('rss', 'search', 'manual')),
    category TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

### 7.4 feed_items 表 — 信息条目

```sql
CREATE TABLE IF NOT EXISTS feed_items (
    id TEXT PRIMARY KEY,
    source_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    url TEXT NOT NULL,
    publish_time DATETIME,
    category TEXT,
    summary TEXT,
    embedding BLOB,
    crawled_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES sources(id)
);
```

### 7.5 feedbacks 表 — 用户反馈

```sql
CREATE TABLE IF NOT EXISTS feedbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('like', 'dislike', 'neutral')),
    reason TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (item_id) REFERENCES feed_items(id),
    UNIQUE(user_id, item_id)
);
```

### 7.6 briefs 表 — 简报记录

```sql
CREATE TABLE IF NOT EXISTS briefs (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    date DATE NOT NULL,
    item_count INTEGER DEFAULT 0,
    sent BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id),
    UNIQUE(user_id, date)
);
```

### 7.7 executions 表 — 任务执行记录（情节记忆）

```sql
CREATE TABLE IF NOT EXISTS executions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
    start_time DATETIME NOT NULL,
    end_time DATETIME,
    raw_count INTEGER DEFAULT 0,
    dedup_count INTEGER DEFAULT 0,
    final_count INTEGER DEFAULT 0,
    error_message TEXT,
    reflection TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

## 八、技术栈选择

| 层级 | 技术 | 版本 | 选择理由 |
|------|------|------|----------|
| **LLM 大脑** | DeepSeek API / 通义千问 | v1.5+ | 国内可用，API 稳定，支持 Function Calling |
| **Agent 框架** | LangGraph | 0.2.x+ | 状态图驱动，支持 ReAct 模式，适合复杂工作流 |
| **向量数据库** | ChromaDB | 0.4.x+ | 轻量单机，Python 原生，适合 MVP |
| **关系数据库** | SQLite | 3.x | 零配置，文件存储，适合小规模用户 |
| **前端** | Streamlit | 1.x | 快速构建，Python 原生，无需前端经验 |
| **MCP Server** | FastAPI | 0.100+ | 高性能，支持 SSE，易于构建 API |
| **定时任务** | APScheduler | 3.x | 轻量，支持多种触发器，与 Python 无缝集成 |
| **HTTP 客户端** | requests | 2.x | 成熟稳定，广泛使用 |
| **XML 解析** | feedparser | 6.x | 专门处理 RSS/Atom，兼容性好 |
| **向量计算** | sentence-transformers | 2.x | 支持多语言模型，轻量嵌入 |

## 九、MVP 范围界定

### 9.1 MVP 必须实现

| 功能 | 描述 |
|------|------|
| 用户注册/登录 | Streamlit 简单表单，SQLite 存储 |
| 兴趣配置 | 用户设置关注领域关键词 |
| RSS 源管理 | 添加/删除/启用 RSS 订阅源 |
| 定时采集 | 每天定时从 RSS 源采集内容 |
| 向量去重 | 基于相似度的重复内容过滤 |
| 偏好排序 | 时间衰减 + 向量相似度排序 |
| 摘要生成 | LLM 生成单条内容摘要 |
| 简报生成 | 结构化日报简报（Markdown） |
| 邮件推送 | 通过 MCP Server 发送邮件 |
| 用户反馈 | 点赞/踩按钮，记录反馈 |
| 记忆更新 | 反馈影响后续排序权重 |

### 9.2 后续迭代功能

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 搜索引擎集成 | P0 | 通过 MCP 添加搜索补充 |
| 企业微信推送 | P0 | 多渠道推送 |
| RAG 语义记忆 | P1 | 补充领域知识 |
| 多用户支持 | P1 | 支持多个用户 |
| 去重阈值校准 | P2 | 自动优化阈值 |
| 可视化仪表盘 | P2 | 统计分析界面 |
| 智能分类标签 | P3 | LLM 自动打标签 |
| 离线模式 | P3 | 无网络时本地处理 |

## 十、阶段性目标与任务拆解

### 阶段一：基础设施搭建

**阶段目标**：建立项目基础结构，配置开发环境，完成核心依赖安装。

**交付物**：
- 项目目录结构
- `requirements.txt` 依赖清单
- `.env` 环境配置模板
- 数据库初始化脚本

**关键任务**：
1. 创建项目目录结构
2. 编写 `requirements.txt`
3. 配置 `.env`（LLM API Key、数据库路径等）
4. 编写 SQLite 初始化脚本
5. 验证环境可运行

**依赖**：无（起始阶段）

**预估复杂度**：低

---

### 阶段二：数据模型与记忆系统

**阶段目标**：实现 SQLite 数据模型和 ChromaDB 向量存储，建立记忆系统基础。

**交付物**：
- 数据库 ORM 模型定义
- 向量数据库 CRUD 接口
- 记忆系统封装类
- 数据存储测试用例

**关键任务**：
1. 定义 SQLAlchemy 模型
2. 实现 SQLite 数据库连接和操作
3. 实现 ChromaDB 集合管理
4. 封装 MemoryManager 类（短期/长期/情节记忆）
5. 编写单元测试验证存储/检索

**依赖**：阶段一完成

**预估复杂度**：中

---

### 阶段三：工具层实现（Function Calling）

**阶段目标**：实现 RSS 采集、文本摘要、简报生成三个 Function Calling 工具。

**交付物**：
- RSS 采集器工具
- 文本摘要器工具
- 简报生成器工具
- 工具测试脚本

**关键任务**：
1. 实现 RSS 采集函数（feedparser）
2. 实现文本摘要函数（调用 DeepSeek API）
3. 实现简报生成函数（结构化输出）
4. 编写工具描述和参数定义
5. 集成测试验证工具功能

**依赖**：阶段二完成

**预估复杂度**：中

---

### 阶段四：工具层实现（MCP Server）

**阶段目标**：实现搜索、推送、向量存储三个 MCP Server。

**交付物**：
- 搜索引擎 MCP Server（SSE 模式）
- 推送通知 MCP Server（stdio 模式）
- 向量数据库 MCP Server（stdio 模式）
- MCP 连接测试脚本

**关键任务**：
1. 实现搜索服务（调用搜索 API）
2. 实现邮件推送服务
3. 实现向量数据库 MCP 封装
4. 配置 MCP Server 部署方式
5. 测试 MCP 工具调用

**依赖**：阶段二完成

**预估复杂度**：中

---

### 阶段五：Agent 核心工作流（LangGraph）

**阶段目标**：用 LangGraph StateGraph 构建完整的 Agent 工作流，实现 ReAct 循环。

**交付物**：
- State TypedDict 定义
- 节点函数实现
- 边连接和条件分支配置
- 工作流集成测试

**关键任务**：
1. 定义 FeedLensState TypedDict
2. 实现各节点函数（采集→去重→排序→摘要→简报）
3. 配置 StateGraph 边和条件分支
4. 实现 ReAct 思考-行动-观察循环
5. 端到端测试完整工作流

**依赖**：阶段三、四完成

**预估复杂度**：高

---

### 阶段六：排序与去重算法

**阶段目标**：实现基于向量相似度的去重策略和多因子排序算法。

**交付物**：
- 去重算法实现
- 排序算法实现
- 权重动态调整机制
- 算法评估测试

**关键任务**：
1. 实现向量相似度计算
2. 实现去重阈值判断逻辑
3. 实现多因子打分公式
4. 实现权重动态调整
5. 用测试数据验证去重和排序效果

**依赖**：阶段二、五完成

**预估复杂度**：中

---

### 阶段七：前端界面（Streamlit）

**阶段目标**：用 Streamlit 构建用户界面，支持配置、查看简报、反馈交互。

**交付物**：
- 用户注册/登录页面
- 兴趣配置页面
- RSS 源管理页面
- 简报展示页面
- 反馈交互组件

**关键任务**：
1. 实现用户认证页面
2. 实现兴趣配置表单
3. 实现 RSS 源管理界面
4. 实现简报列表和详情展示
5. 实现点赞/踩反馈按钮

**依赖**：阶段二、五完成

**预估复杂度**：低

---

### 阶段八：定时调度与推送

**阶段目标**：实现定时任务调度，自动执行采集流程并推送简报。

**交付物**：
- APScheduler 定时任务配置
- 邮件推送集成
- 定时执行日志
- 推送失败重试机制

**关键任务**：
1. 配置 APScheduler 定时触发器
2. 实现定时执行入口函数
3. 集成邮件推送 MCP
4. 实现推送失败重试逻辑
5. 测试定时执行和推送

**依赖**：阶段四、五完成

**预估复杂度**：低

---

### 阶段九：反思与记忆更新

**阶段目标**：实现反思机制和记忆更新，使 Agent 能够从经验中学习。

**交付物**：
- 反思节点实现
- 用户反馈处理
- 偏好权重更新
- 学习效果验证

**关键任务**：
1. 实现反思节点（审查执行结果）
2. 实现用户反馈处理逻辑
3. 实现偏好权重动态更新
4. 实现情节记忆写入
5. 验证反馈影响后续排序

**依赖**：阶段二、五完成

**预估复杂度**：中

---

### 阶段十：集成测试与部署

**阶段目标**：完成全流程集成测试，打包项目，准备部署。

**交付物**：
- 端到端测试脚本
- 部署配置文件
- 项目 README
- MVP 演示视频

**关键任务**：
1. 编写端到端测试用例
2. 修复测试发现的问题
3. 配置 Dockerfile（可选）
4. 编写部署说明
5. 录制 MVP 演示

**依赖**：所有阶段完成

**预估复杂度**：低

---

## 项目目录结构

```
FeedLens_Agent/
├── .env                      # 环境变量配置
├── requirements.txt          # Python 依赖
├── main.py                   # Streamlit 入口
├── agent/                    # Agent 核心模块
│   ├── __init__.py
│   ├── state.py              # State TypedDict 定义
│   ├── nodes.py              # LangGraph 节点函数
│   ├── graph.py              # StateGraph 构建
│   └── tools/                # 工具定义
│       ├── __init__.py
│       ├── rss_collector.py  # RSS 采集器
│       ├── summarizer.py     # 文本摘要器
│       └── brief_generator.py # 简报生成器
├── memory/                   # 记忆系统
│   ├── __init__.py
│   ├── memory_manager.py     # 记忆管理封装
│   ├── short_term.py         # 短期记忆
│   ├── long_term.py          # 长期记忆(ChromaDB)
│   └── episodic.py           # 情节记忆(SQLite)
├── mcp_servers/              # MCP 服务端
│   ├── __init__.py
│   ├── search_engine/        # 搜索服务(SSE)
│   ├── notification/         # 推送服务(stdio)
│   └── vector_store/         # 向量存储服务(stdio)
├── database/                 # 数据库相关
│   ├── __init__.py
│   ├── models.py             # SQLAlchemy 模型
│   ├── init_db.py            # 数据库初始化
│   └── queries.py            # 查询封装
├── algorithms/               # 算法模块
│   ├── __init__.py
│   ├── deduplication.py      # 去重算法
│   ├── ranking.py            # 排序算法
│   └── similarity.py         # 相似度计算
├── scheduler/                # 定时调度
│   ├── __init__.py
│   └── scheduler.py          # APScheduler 配置
├── frontend/                 # Streamlit 页面
│   ├── __init__.py
│   ├── auth.py               # 用户认证页面
│   ├── config.py             # 配置页面
│   ├── brief.py              # 简报展示页面
│   └── feedback.py           # 反馈交互页面
└── tests/                    # 测试目录
    ├── __init__.py
    ├── test_memory.py
    ├── test_tools.py
    ├── test_algorithms.py
    └── test_workflow.py
```

---

方案的核心亮点：

1. **架构清晰**：严格按照你提供的 Agent 架构框架（感知/大脑/工具/记忆/规划）设计
2. **工具调用合理区分**：简单工具用 Function Calling，复杂/可复用工具用 MCP
3. **记忆系统完整**：包含短期、长期、情节、语义四种记忆
4. **算法可验证**：排序和去重都有明确的公式和阈值
5. **工程化落地**：SQLite + Streamlit + LangGraph 的轻量组合，适合 MVP 快速验证

