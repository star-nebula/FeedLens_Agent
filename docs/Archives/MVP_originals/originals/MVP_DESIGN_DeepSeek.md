## 1. 系统架构图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           FeedLens 系统架构                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐    ┌──────────────────────────────┐                   │
│  │   Streamlit  │    │      定时调度器 (scheduler)    │                   │
│  │   前端界面    │    │      APScheduler / Cron       │                   │
│  └──────┬───────┘    └──────────────┬───────────────┘                   │
│         │ 用户交互                 │ 触发每日采集任务                     │
│         ▼                          ▼                                    │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                     LangGraph  Agent 核心                         │   │
│  │                                                                   │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐              │   │
│  │  │  感知层      │  │  大脑 (LLM) │  │  规划循环     │              │   │
│  │  │  - 工具输出  │  │  DeepSeek   │  │  ReAct +      │              │   │
│  │  │  - 用户输入  │  │  推理/决策  │  │  Reflection   │              │   │
│  │  └─────────────┘  └──────┬──────┘  └──────┬───────┘              │   │
│  │                          │                │                       │   │
│  │  ┌───────────────────────┴────────────────┴─────────────┐        │   │
│  │  │                     工具层                            │        │   │
│  │  │  ┌───────────┐ ┌───────────┐ ┌───────────┐          │        │   │
│  │  │  │RSS采集    │ │去重分析   │ │简报生成   │          │        │   │
│  │  │  │(Func.Call)│ │(Func.Call)│ │(Func.Call)│          │        │   │
│  │  │  └───────────┘ └───────────┘ └───────────┘          │        │   │
│  │  │  ┌───────────┐ ┌───────────┐ ┌───────────┐          │        │   │
│  │  │  │搜索服务   │ │推送通知   │ │数据库操作 │          │        │   │
│  │  │  │(MCP)      │ │(MCP)      │ │(MCP)      │          │        │   │
│  │  │  └───────────┘ └───────────┘ └───────────┘          │        │   │
│  │  └────────────────────────────────────────────────────┘        │   │
│  │                                                                   │   │
│  │  ┌───────────────────────────────────────────────────────────┐   │   │
│  │  │                      记忆系统                              │   │   │
│  │  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────┐     │   │   │
│  │  │  │短期记忆     │  │长期记忆      │  │情节记忆      │     │   │   │
│  │  │  │会话上下文   │  │ChromaDB      │  │SQLite        │     │   │   │
│  │  │  │滑动窗口     │  │用户偏好向量  │  │历史任务记录  │     │   │   │
│  │  │  └─────────────┘  └──────────────┘  └──────────────┘     │   │   │
│  │  └───────────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                    │                                     │
│                          ┌─────────┴─────────┐                           │
│                          ▼                   ▼                           │
│                    ┌──────────┐       ┌──────────────┐                   │
│                    │ SQLite   │       │  ChromaDB    │                   │
│                    │ 结构化   │       │  向量存储    │                   │
│                    └──────────┘       └──────────────┘                   │
└─────────────────────────────────────────────────────────────────────────┘
```

**层级对应关系**：
- **感知层**：用户输入、工具返回（RSS 内容、搜索结果、去重判断、推送结果）
- **大脑**：DeepSeek API 负责意图理解、推理决策、调用工具、生成简报文本
- **工具层**：RSS 采集、搜索、去重、摘要生成、推送、数据库 CRUD
- **记忆**：短期（会话上下文）、长期（用户偏好向量/条目向量）、情节（历史执行记录）
- **规划**：ReAct 循环在 LangGraph 节点中实现，反思节点对简报质量进行审查

---

## 2. Agent 工作流设计（LangGraph StateGraph）

### State 定义（TypedDict）

```python
from typing import TypedDict, List, Dict, Any, Optional
from datetime import datetime

class FeedLensState(TypedDict):
    # 任务元信息
    task_type: str              # "daily_briefing" | "manual_search" | "feedback_update"
    user_id: str
    session_id: str
    
    # 用户输入
    user_query: Optional[str]   # 手动查询时的输入
    user_feedback: Optional[Dict[str, Any]]  # {"item_id": ..., "action": "like"|"dislike"}
    
    # 关注领域配置
    topics: List[str]           # ["AI Agent", "新能源车"]
    
    # 采集与处理
    raw_items: List[Dict]       # 原始采集条目
    deduped_items: List[Dict]   # 去重后条目
    ranked_items: List[Dict]    # 排序后条目
    
    # 简报
    briefing_text: str          # 最终简报 Markdown
    
    # 反思修正
    reflection_notes: str
    revised_briefing: str
    
    # 控制流
    next_step: str              # 下一个节点名称
    error: Optional[str]
    tool_calls: List[Dict]      # 待执行的工具调用队列
```

### 节点与边

```python
from langgraph.graph import StateGraph, END

workflow = StateGraph(FeedLensState)

# 节点定义（每个节点是一个可调用对象或函数）
workflow.add_node("understand_intent", understand_intent_node)   # 大脑：理解任务意图
workflow.add_node("collect_sources", collect_sources_node)       # 工具：调用RSS/搜索
workflow.add_node("deduplicate", deduplicate_node)               # 工具：向量去重
workflow.add_node("rank_items", rank_items_node)                 # 工具：偏好排序
workflow.add_node("generate_briefing", generate_briefing_node)   # 大脑：生成简报
workflow.add_node("reflect", reflect_node)                      # 规划反思：审查简报
workflow.add_node("push_notification", push_notification_node)   # 工具：推送
workflow.add_node("update_memory", update_memory_node)           # 记忆更新
workflow.add_node("handle_feedback", handle_feedback_node)       # 用户反馈学习

# 边与条件路由
workflow.set_entry_point("understand_intent")
workflow.add_edge("understand_intent", "collect_sources")
workflow.add_edge("collect_sources", "deduplicate")
workflow.add_edge("deduplicate", "rank_items")
workflow.add_edge("rank_items", "generate_briefing")
workflow.add_edge("generate_briefing", "reflect")
workflow.add_conditional_edges(
    "reflect",
    lambda s: "revise" if s.get("reflection_notes") else "push",
    {"revise": "generate_briefing", "push": "push_notification"}
)
workflow.add_edge("push_notification", "update_memory")
workflow.add_edge("update_memory", END)

# 反馈子图可单独触发
feedback_workflow = StateGraph(FeedLensState)
feedback_workflow.add_node("process_feedback", handle_feedback_node)
feedback_workflow.set_entry_point("process_feedback")
feedback_workflow.add_edge("process_feedback", END)
```

**工作流说明**：
1. **understand_intent**：LLM 分析任务类型（每日定时/手动查询），提取用户兴趣领域。
2. **collect_sources**：并行调用 RSS 采集工具和搜索工具，返回原始条目列表。
3. **deduplicate**：调用去重工具，基于向量相似度对原始条目聚类，每个簇保留一篇。
4. **rank_items**：调用排序工具，结合用户长期偏好向量、时间衰减、点赞/踩权重进行打分排序。
5. **generate_briefing**：LLM 根据排序后的条目和模板生成结构化简报（分类、重要性、来源）。
6. **reflect**：LLM 对简报进行自我审查，检查是否遗漏重要信息、是否存在矛盾。若发现问题，返回 `revise` 重新生成；否则进入推送。
7. **push_notification**：调用推送工具（邮件/微信/Webhook），将简报发送给用户。
8. **update_memory**：将本次简报中的条目向量存入长期记忆，更新情节记忆（记录本次采集的源数量、去重率、用户反馈等）。

---

## 3. 工具清单

### 3.1 工具总览

| 工具名称 | 调用方式 | 选择理由 |
|---------|---------|---------|
| `fetch_rss` | Function Calling | 逻辑简单，参数固定（URL），LLM 直接调用获取内容 |
| `search_web` | MCP (SSE) | 搜索 API 涉及密钥管理、QPS 限制，独立部署为 MCP Server 便于跨任务复用和限流 |
| `deduplicate_entries` | Function Calling | 纯计算逻辑，依赖 ChromaDB 本地调用，无外部依赖，参数简单 |
| `rank_entries` | Function Calling | 排序算法本地运行，参数为条目列表和用户偏好向量，适合直接调用 |
| `generate_summary` | Function Calling | 调用 LLM 生成摘要，作为工具封装便于统一日志和错误处理 |
| `push_briefing` | MCP (stdio) | 推送渠道可能多变（邮件/企业微信/钉钉），独立 MCP Server 便于切换和复用 |
| `db_read / db_write` | MCP (stdio) | 数据库操作作为通用服务，可被多个 Agent 或子任务共享，保证连接池管理和事务一致性 |

### 3.2 工具详细定义

#### 3.2.1 fetch_rss (Function Calling)
```python
{
    "name": "fetch_rss",
    "description": "从指定 RSS 源抓取最新内容条目",
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "RSS 源的完整 URL"
            },
            "max_items": {
                "type": "integer",
                "default": 20,
                "description": "最多返回条数"
            }
        },
        "required": ["url"]
    }
}
```
**内部实现**：使用 `feedparser` 解析，返回标准化字段（title, link, summary, published, source）。

#### 3.2.2 search_web (MCP, SSE 部署)
MCP Server 部署方式：本地 HTTP SSE 服务（`mcp-server-search`），监听 `localhost:8100`。
接口定义：
```json
{
    "method": "tools/call",
    "params": {
        "name": "search_web",
        "arguments": {
            "query": "AI Agent 最新进展",
            "num": 10,
            "time_range": "week"
        }
    }
}
```
Server 内部封装百度/必应 API 调用，统一返回格式。选择 MCP 的原因：搜索 API 需要独立的密钥配置、请求限流和结果缓存，解耦后 Agent 无需关注实现细节。

#### 3.2.3 deduplicate_entries (Function Calling)
```python
{
    "name": "deduplicate_entries",
    "description": "对一组信息条目进行去重，返回去重后列表",
    "parameters": {
        "type": "object",
        "properties": {
            "entries": {
                "type": "array",
                "items": {"type": "object"},
                "description": "原始条目列表，每个条目至少包含 title 和 summary"
            },
            "threshold": {
                "type": "number",
                "default": 0.85,
                "description": "余弦相似度阈值，高于此值视为重复"
            }
        },
        "required": ["entries"]
    }
}
```
内部流程：将 title+summary 拼接后向量化 → 存入临时 ChromaDB collection → 对每条记录查询最相似 top-1 → 相似度 > threshold 则归为同簇，保留发布时间最早的那条。

#### 3.2.4 rank_entries (Function Calling)
```python
{
    "name": "rank_entries",
    "description": "根据用户偏好、时间衰减和热度对条目进行综合打分排序",
    "parameters": {
        "type": "object",
        "properties": {
            "entries": {"type": "array", "items": {"type": "object"}},
            "user_id": {"type": "string"},
            "top_k": {"type": "integer", "default": 15}
        },
        "required": ["entries", "user_id"]
    }
}
```
排序公式见第5节。

#### 3.2.5 generate_summary (Function Calling)
```python
{
    "name": "generate_summary",
    "description": "调用 LLM 为一条信息条目生成简短摘要",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "max_length": {"type": "integer", "default": 200}
        },
        "required": ["title", "content"]
    }
}
```
这个工具封装了 LLM 调用，便于统一 token 计费和异常重试。

#### 3.2.6 push_briefing (MCP, stdio 部署)
MCP Server：`mcp-server-push`，通过 stdio 与 Agent 进程通信。
```json
{
    "method": "tools/call",
    "params": {
        "name": "push_briefing",
        "arguments": {
            "user_id": "u_001",
            "channel": "email",
            "content": "# 今日简报\n...",
            "subject": "FeedLens 每日简报 - 2026-06-17"
        }
    }
}
```
支持 email（SMTP）、企业微信 Webhook 等渠道，配置在 Server 端环境变量中，Agent 无需感知。

#### 3.2.7 db_read / db_write (MCP, stdio 部署)
MCP Server：`mcp-server-db`，封装 SQLite 操作，提供标准化 CRUD 接口。
```json
{
    "method": "tools/call",
    "params": {
        "name": "db_read",
        "arguments": {
            "query": "SELECT * FROM items WHERE user_id = ? AND published > ?",
            "params": ["u_001", "2026-06-10"]
        }
    }
}
```
选择 MCP 原因：数据库连接管理、事务控制、连接池统一封装，可被多个子 Agent 安全共享；未来切换 PostgreSQL 只需更改 Server 实现。

---

## 4. 记忆系统设计

| 记忆类型 | 存储介质 | 存储内容 | 检索方式 | 更新策略 |
|---------|---------|---------|---------|---------|
| **短期记忆** | LangGraph State（会话内） | 当前 task 的上下文：用户输入、工具调用历史、已获取的条目列表、简报草稿 | State 字段直接访问，滑动窗口保留最近 15 轮 tool call 结果 | 每个 task 结束后清空，仅保留关键摘要（如简报最终版）存入情节记忆 |
| **长期记忆（语义）** | ChromaDB | 用户兴趣向量（由用户点赞过的条目向量加权平均得到）；全局知识条目向量（所有已处理条目的向量，供去重和排序检索） | 余弦相似度检索（top-k=20），用于排序时计算条目与用户兴趣的匹配度 | 用户每次点赞/踩时更新兴趣向量；每次采集新条目后插入条目向量（自动过期清理） |
| **情节记忆** | SQLite 表 `episodic_memory` | 每次任务执行的元数据：时间、任务类型、采集源数量、去重率、简报内容摘要、用户反馈得分、错误日志 | SQL 按时间范围查询，用于反思节点分析历史效果，也可生成“执行报告” | 每次 `update_memory` 节点插入一条新记录 |

**长期记忆更新算法（用户兴趣向量）**：
- 用户点赞条目向量 v_like，踩条目向量 v_dislike
- 新兴趣向量 = 0.9 * 旧兴趣向量 + 0.1 * v_like - 0.05 * v_dislike（移动平均，保持归一化）

---

## 5. 排序算法设计

总得分公式：
```
Score(item) = α * Sim(item_vec, user_vec) 
            + β * (1 - e^(-λ * age_days))   // 时间衰减，负向
            + γ * source_weight
            + δ * feedback_bias
```
- `α, β, γ, δ` 为权重，初始值 `α=0.4, β=0.3, γ=0.1, δ=0.2`，可通过简单 AB 测试调整。
- `Sim(item_vec, user_vec)`：条目向量（title+summary）与用户兴趣向量的余弦相似度。
- `age_days`：条目发布日期距今天数。`λ=0.5` 控制衰减速度，越新分数越高。
- `source_weight`：信息源的可信度权重（如权威媒体 1.0，个人博客 0.5），用户可在配置中调整。
- `feedback_bias`：基于用户历史反馈的同话题加成。如果条目话题标签与用户之前点赞过的条目话题相同，加 0.15；若与踩过的话题相同，减 0.1。

**归一化**：所有分数计算前先对 `Sim`、时间衰减、`source_weight` 做 Min-Max 归一化到 [0,1]，确保量纲一致。

---

## 6. 去重策略设计

### 向量去重流程
1. 将所有原始条目的 `title + summary` 用 DeepSeek Embedding 模型向量化。
2. 新建临时 ChromaDB Collection，插入所有向量（附带原始条目 ID）。
3. 对每个条目查询最相似的 top-1（自身除外），得到相似度 `s`。
4. 若 `s >= 0.88`（初始阈值），归入同一重复簇。
5. 同一簇内保留 **发布时间最早** 的条目作为代表（确保信息来源溯源准确）。

### 阈值校准
- **初始值 0.88** 来自经验设定，通过在 dev 集上人工标注 100 对样本（重复/不重复）计算 F1 最优阈值。
- **校准方法**：每周从用户反馈中抽样，若用户频繁标记“还是不相关”（可能是误去重或未去重），则调整阈值 ±0.02，记录版本。

### 区分“同一事件不同角度”与“真正重复”
- 真正重复：标题高度相似（编辑距离小 + 向量 sim > 0.95），内容几乎一致。阈值设高（0.95）单独过滤。
- 同一事件不同角度：向量 sim 在 0.88~0.95 之间，保留一篇代表，同时在简报中标注“还有 N 篇类似报道”，避免信息单一化。
- 实现：两阶段去重——第一阶段严格匹配（0.95）去除转载，第二阶段宽松匹配（0.88）聚合同事件，保留代表并计数。

---

## 7. 数据模型（SQLite 表结构）

```sql
-- 用户表
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT,
    preferences TEXT,  -- JSON: {"topics": [...], "source_weights": {...}}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 信息源表
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,          -- 'rss' | 'search'
    url TEXT,                    -- RSS URL 或搜索模板
    topic_tag TEXT,              -- 关联领域
    weight REAL DEFAULT 1.0,     -- 可信度权重
    enabled INTEGER DEFAULT 1
);

-- 信息条目表（经过去重和处理的条目）
CREATE TABLE items (
    item_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    url TEXT UNIQUE,
    published_at TIMESTAMP,
    source_id TEXT,
    cluster_id TEXT,             -- 去重簇 ID
    embedding BLOB,              -- 可选，或存 ChromaDB ID
    vector_id TEXT,              -- ChromaDB 中的向量 ID
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

-- 用户反馈表
CREATE TABLE feedbacks (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    action TEXT CHECK(action IN ('like', 'dislike', 'mark_irrelevant', 'view')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (item_id) REFERENCES items(item_id),
    UNIQUE(user_id, item_id, action)  -- 防止重复反馈
);

-- 简报历史表
CREATE TABLE briefings (
    briefing_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    task_type TEXT NOT NULL,  -- 'daily' | 'manual'
    content TEXT,             -- Markdown 简报全文
    items_covered TEXT,       -- JSON 数组，包含的 item_id 列表
    reflection_notes TEXT,
    delivered INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- 情节记忆表
CREATE TABLE episodic_memory (
    episode_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    task_type TEXT,
    metrics TEXT,  -- JSON: {"sources_count":5, "raw_items":120, "deduped":30, "briefing_len":1500}
    summary TEXT,  -- 自然语言摘要
    errors TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 8. 技术栈选择

| 层级/组件 | 技术选型 | 理由 |
|----------|---------|------|
| **LLM 大脑** | DeepSeek-V3 API (或 Qwen-Max) | 国内可直接访问，兼容 OpenAI SDK，成本低，推理能力强 |
| **Embedding 模型** | text-embedding-v3 (DeepSeek) 或 bge-large-zh | 本地/API 均可，中文语义理解优秀 |
| **Agent 框架** | LangGraph (StateGraph) | 精确控制流程，状态显式传递，便于调试和反思循环 |
| **MCP 实现** | `mcp` (Python SDK) + FastMCP | 官方工具包，支持 stdio/SSE，轻松构建 Server |
| **前端** | Streamlit | 极低代码，快速搭建交互式 UI，适合 MVP |
| **向量数据库** | ChromaDB | 轻量级，单机可运行，无需额外服务，完美契合 MVP |
| **关系数据库** | SQLite | 零配置，数据可打包为单文件，便于求职作品展示和迁移 |
| **任务调度** | APScheduler | 轻量级 Python 调度库，支持 Cron 表达式，满足每日定时采集 |
| **RSS 解析** | feedparser | 成熟稳定，解析各类 RSS/Atom 格式 |
| **部署** | 单机 Docker Compose（Agent + MCP Server + Streamlit） | 方便演示，所有服务打包在一起 |

---

## 9. MVP 范围界定

### 必须实现（MVP v1.0）

- 用户可注册并设定至少 3 个关注领域
- 系统每日定时从 ≥2 个 RSS 源和 1 个搜索源采集内容
- 基于向量的去重（阈值固定），保序去重
- 基于简单偏好（初始兴趣向量）和时间衰减的排序
- 生成结构化 Markdown 简报，含标题、摘要、来源、时间
- 简报通过邮件（或标准输出）推送
- Streamlit 界面查看历史简报、反馈点赞/踩
- 反馈更新用户兴趣向量（简单加权移动平均）
- 情节记忆记录每次任务的执行统计

### 后续迭代（v1.1+）

- 更多信息源类型：Twitter/X API、Reddit、微信公众号搜狗引擎
- 动态阈值自动校准（基于用户反馈的 A/B 测试）
- 更复杂的用户兴趣模型（主题建模、话题聚类、短期兴趣检测）
- 推送渠道扩展：企业微信、钉钉 Webhook、Telegram Bot
- 多用户管理及权限
- 简报个性化模板（用户可自定义分类方式）
- 反思节点对简报质量自动打分和 A/B 版本选择
- 基于情节记忆的“学习型调度”（自动调整采集频率和源权重）

---

## 10. 阶段性目标与任务拆解

### 阶段一：基础骨架与 Agent 流程跑通

- **阶段目标**：搭建 LangGraph 工作流骨架，能通过命令行或 Streamlit 触发完整流程（模拟采集 → 去重 → 排序 → 简报生成），跑通所有节点，不依赖真实外部工具。
- **交付物**：
  - 可运行的 `main.py`，执行 `python main.py --task daily` 后输出 Markdown 简报到控制台。
  - StateGraph 定义完整，包含所有节点和条件边。
  - 使用 Mock 数据（硬编码 10 条新闻条目）验证去重和排序逻辑。
  - SQLite 表结构自动初始化脚本。
- **关键任务**：
  - 初始化 LangGraph 项目结构，定义 `FeedLensState`。
  - 实现所有节点的占位函数（返回虚拟数据）。
  - 完成 SQLite 建表脚本和 ChromaDB 连接测试。
  - 编写 `main.py` 入口，集成 APScheduler 定时触发。
- **依赖**：无
- **复杂度**：低

### 阶段二：工具实现与记忆系统

- **阶段目标**：所有 MVP 工具真实可用，记忆系统（长期/情节）能正常读写，真实数据流跑通。
- **交付物**：
  - `mcp-server-search`（SSE）和 `mcp-server-db`（stdio）可独立运行，通过 MCP 协议与 Agent 交互。
  - Function Calling 工具 `fetch_rss`、`deduplicate_entries`、`rank_entries` 真实实现，与 ChromaDB 集成。
  - 用户兴趣向量初始化与更新逻辑生效（点赞/踩可改变排序结果）。
  - 每日简报可通过 `push_briefing` 发送到文件或测试邮箱。
- **关键任务**：
  - 实现 RSS 解析器，注册至少 3 个真实中文 RSS 源（如机器之心、36Kr）。
  - 搭建搜索 MCP Server，封装免费搜索 API 或 DuckDuckGo（国内可用替代）。
  - 完善去重算法，将向量存入 ChromaDB 并实现两阶段去重。
  - 实现排序公式，从 ChromaDB 读取用户兴趣向量。
  - 开发 `mcp-server-db`，提供安全的参数化查询接口。
- **依赖**：阶段一
- **复杂度**：中

### 阶段三：简报生成优化与反思循环

- **阶段目标**：简报生成不再是简单模板拼接，而是经过 LLM 深度理解、分类、重要性标注，并引入反思节点自动审查修正简报缺陷。
- **交付物**：
  - 简报包含“今日要闻”、“深度解读”、“行业趋势”等分类，重要条目用⭐标注。
  - 反思节点能识别简报中“信息冗余”、“遗漏重大事件”等情况并触发重新生成。
  - Streamlit 前端可展示最近 7 天简报，支持反馈按钮。
- **关键任务**：
  - 设计简报 Prompt 模板，要求 LLM 结构化输出。
  - 实现 `reflect` 节点的 Prompt（对比原始排序列表和简报，检查覆盖率和矛盾）。
  - 开发 Streamlit 页面：简报列表、反馈交互、用户偏好设置。
  - 整合反馈 API 到用户兴趣向量更新流程。
- **依赖**：阶段二
- **复杂度**：中

### 阶段四：定时调度、推送集成与演示就绪

- **阶段目标**：系统可无人值守自主运行，每日自动采集并推送简报；前端可配置信息源和推送渠道；项目 Docker 化，能够一键演示。
- **交付物**：
  - APScheduler 每日早 8:00 自动触发，采集→处理→推送全链路无人工干预。
  - 邮件推送真实可用（或企业微信 Webhook）。
  - Streamlit 设置页可管理 RSS 源和搜索关键词。
  - `docker-compose.yml` 打包 Agent + Streamlit + ChromaDB + MCP Server，一键启动即可在浏览器中体验。
  - README.md 含架构图、快速开始、功能演示 GIF。
- **关键任务**：
  - 配置 APScheduler，添加错误重试和日志记录。
  - 实现 `mcp-server-push` 的邮件发送（SMTP）。
  - 完善 Streamlit UI：信息源管理 CRUD、简报浏览、反馈统计。
  - Docker Compose 集成所有服务，确保数据持久化（volume）。
  - 录制 2 分钟功能演示视频或 GIF 放入 README。
- **依赖**：阶段三
- **复杂度**：中
