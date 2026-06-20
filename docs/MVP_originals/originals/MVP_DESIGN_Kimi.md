# FeedLens — 智能信息简报 Agent MVP 方案

> 目标岗位：AI 应用开发 | 框架：LangGraph | 前端：Streamlit | 向量库：ChromaDB | LLM：DeepSeek/通义千问

---

## 1. 系统架构图

**架构图下载：** [FeedLens 系统架构图](sandbox:///mnt/agents/output/feedlens_architecture.png)

| 层级 | 模块 | 功能说明 |
|------|------|----------|
| **感知层** | RSS Feed 采集器、搜索引擎采集器、用户反馈输入 | 接收外部信息输入，作为 Agent 的感知信号 |
| **大脑层** | 意图理解、ReAct 推理、工具调用判断、反思修正、LangGraph StateGraph、Function Calling + MCP 路由 | LLM 决策中枢，负责推理、规划和工具调度 |
| **工具层** | 信息采集工具、内容处理工具（去重/摘要/排序）、推送工具 | 执行具体动作，分为 Function Calling 和 MCP 两种调用方式 |
| **规划层** | 定时触发器、任务分解、反思机制、循环优化 | 编排任务执行顺序，支持 ReAct 循环和反思修正 |
| **记忆层** | 短期记忆（滑动窗口）、长期记忆（ChromaDB 向量）、情节记忆（执行记录）、语义记忆（RAG 知识） | 四层记忆体系，支持个性化和持续学习 |
| **数据层** | SQLite、ChromaDB、本地文件、Streamlit 前端 | 持久化存储和交互界面 |

---

## 2. Agent 工作流设计（LangGraph StateGraph）

**工作流图下载：** [LangGraph StateGraph 工作流](sandbox:///mnt/agents/output/feedlens_langgraph.png)

### 2.1 节点与边

```
START ──→ init_state ──┬──→ fetch_rss ──┐
                       │                  ├──→ merge_sources ──→ deduplicate ──→ enrich_metadata ──→ score_rank
                       └──→ fetch_search ─┘                                      │
                                                                                ↓
                                    ┌─────────────────────────────────────── generate_brief
                                    │                                              │
                                    │                                              ↓
                                    │                                       reflect_quality
                                    │                                              │
                                    │                                              ↓
                                    │                                    [质量是否达标?]
                                    │                                    /              \
                                    │                              否 /                \ 是
                                    │                                  /                  \
                                    └──────────────────── regenerate (max_retry=3)   deliver_brief
                                                                                         │
                                                                                         ↓
                                                                                  collect_feedback
                                                                                         │
                                                                                         ↓
                                                                                  update_memory
                                                                                         │
                                                                                         ↓
                                                                                        END
```

### 2.2 State TypedDict 定义

```python
from typing import TypedDict, List, Dict, Optional

class FeedLensState(TypedDict):
    # 元信息
    session_id: str          # 会话标识
    trigger_type: str        # "cron" | "manual" | "feedback"
    timestamp: str           # ISO 格式时间戳
    
    # 采集数据
    raw_items: List[Dict]    # 原始采集条目 [{source, title, url, content, pub_date}]
    merged_items: List[Dict] # 合并后条目
    
    # 处理数据
    deduped_items: List[Dict]      # 去重后条目 (含 similarity_score)
    enriched_items: List[Dict]     # 增强后条目 (含 category, keywords, importance)
    ranked_items: List[Dict]       # 排序后条目 (含 final_score, rank)
    
    # 生成数据
    brief_content: str       # 生成的简报 Markdown
    brief_quality: Dict        # 质量评估 {completeness, relevance, coherence, score}
    reflection_notes: str      # 反思记录
    retry_count: int           # 重试计数器 (防死循环, max=3)
    
    # 推送与反馈
    delivery_status: str       # "pending" | "delivered" | "failed"
    user_feedback: List[Dict]  # 用户反馈 [{item_id, feedback_type, timestamp}]
    
    # 记忆引用
    user_profile: Dict         # 用户偏好快照 (从长期记忆加载)
    retrieved_memories: List     # RAG 检索到的相关记忆
```

### 2.3 关键边逻辑

| 边 | 条件 | 说明 |
|----|------|------|
| `init_state → fetch_rss / fetch_search` | 无条件 | 并行执行两个采集节点 |
| `reflect_quality → generate_brief` | `retry_count < 3 AND brief_quality.score < 0.7` | 质量不达标，反思后重新生成 |
| `reflect_quality → deliver_brief` | `brief_quality.score >= 0.7 OR retry_count >= 3` | 质量达标或达到最大重试次数 |

---

## 3. 工具清单

### 3.1 工具总览与调用方式选择

| # | 工具名称 | 调用方式 | 选择理由 |
|---|----------|----------|----------|
| 1 | `fetch_rss` | **Function Calling** | 逻辑简单、参数明确（URL + 时间范围），无需独立进程 |
| 2 | `fetch_search` | **MCP (SSE)** | 搜索服务可能需要独立部署（避免被封、代理管理），且可被其他 Agent 复用 |
| 3 | `deduplicate` | **Function Calling** | 纯本地计算（向量相似度），无外部依赖，参数简单 |
| 4 | `enrich_metadata` | **Function Calling** | 调用 LLM 进行元数据提取，参数明确，直接通过 Function Calling 调用 LLM |
| 5 | `score_rank` | **Function Calling** | 本地计算排序公式，无需外部服务 |
| 6 | `generate_brief` | **Function Calling** | 调用 LLM 生成文本，标准 Function Calling 场景 |
| 7 | `reflect_quality` | **Function Calling** | 调用 LLM 做质量评估，参数明确 |
| 8 | `deliver_brief` | **MCP (stdio)** | 推送渠道多样（邮件/微信/钉钉），通过 MCP 解耦，支持渐进式接入新渠道 |
| 9 | `update_memory` | **Function Calling** | 直接操作本地 ChromaDB/SQLite，无需独立进程 |
| 10 | `retrieve_memory` | **Function Calling** | 本地向量检索，直接调用 |

### 3.2 工具详细定义

#### Tool 1: `fetch_rss` (Function Calling)

```python
{
    "name": "fetch_rss",
    "description": "从指定的 RSS 源采集最新文章条目，支持时间过滤和数量限制",
    "parameters": {
        "type": "object",
        "properties": {
            "feed_urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "RSS 源 URL 列表"
            },
            "since_hours": {
                "type": "integer",
                "default": 24,
                "description": "只采集最近 N 小时的内容"
            },
            "max_items_per_source": {
                "type": "integer",
                "default": 20,
                "description": "每个源最多采集条目数"
            }
        },
        "required": ["feed_urls"]
    }
}
```

#### Tool 2: `fetch_search` (MCP - SSE)

**选择理由：** 搜索服务涉及 API Key 管理、请求频率控制、代理配置、结果解析等复杂逻辑，独立为 MCP Server 可实现：
- 与主 Agent 进程解耦，避免搜索被封影响主服务
- 多个 Agent 可共享同一搜索服务
- 支持渐进式接入不同搜索引擎（百度、必应、SearXNG）

**MCP Server 部署方式：** SSE (Server-Sent Events)

```python
# MCP Server 接口定义 (mcp-search-server)
{
    "name": "fetch_search",
    "description": "通过搜索引擎采集与主题相关的最新信息",
    "parameters": {
        "type": "object",
        "properties": {
            "queries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "搜索查询词列表"
            },
            "top_n": {
                "type": "integer",
                "default": 10,
                "description": "每个查询返回结果数"
            },
            "source": {
                "type": "string",
                "enum": ["baidu", "bing", "searxng"],
                "default": "searxng",
                "description": "搜索引擎选择"
            }
        },
        "required": ["queries"]
    }
}

# MCP Server 启动配置
# transport: sse
# endpoint: http://localhost:3001/sse
# 启动命令: python -m mcp_search_server --transport sse --port 3001
```

#### Tool 3: `deduplicate` (Function Calling)

```python
{
    "name": "deduplicate",
    "description": "基于向量相似度对信息条目进行去重，保留最早/最权威的来源",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "source": {"type": "string"},
                        "url": {"type": "string"}
                    }
                },
                "description": "待去重的条目列表"
            },
            "similarity_threshold": {
                "type": "number",
                "default": 0.85,
                "description": "向量相似度阈值，超过则视为重复"
            },
            "embedding_model": {
                "type": "string",
                "default": "BAAI/bge-small-zh-v1.5",
                "description": "使用的 embedding 模型"
            }
        },
        "required": ["items"]
    }
}
```

#### Tool 4: `enrich_metadata` (Function Calling)

```python
{
    "name": "enrich_metadata",
    "description": "使用 LLM 为信息条目提取分类、关键词、重要性等级等元数据",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "待增强的条目列表"
            },
            "categories": {
                "type": "array",
                "items": {"type": "string"},
                "default": ["AI Agent", "New Energy Vehicles", "Cross-border E-commerce"],
                "description": "预定义分类标签"
            }
        },
        "required": ["items"]
    }
}
```

#### Tool 5: `score_rank` (Function Calling)

```python
{
    "name": "score_rank",
    "description": "根据向量相似度、时间衰减和用户偏好权重对条目进行排序打分",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "待排序的条目列表（需已包含 embedding 和 metadata）"
            },
            "user_profile": {
                "type": "object",
                "description": "用户偏好向量快照"
            },
            "top_k": {
                "type": "integer",
                "default": 15,
                "description": "返回前 K 条"
            }
        },
        "required": ["items", "user_profile"]
    }
}
```

#### Tool 6: `generate_brief` (Function Calling)

```python
{
    "name": "generate_brief",
    "description": "基于排序后的条目生成结构化 Markdown 简报，包含分类组织、重要性标注和来源引用",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "排序后的条目列表"
            },
            "style": {
                "type": "string",
                "enum": ["concise", "detailed", "bullet"],
                "default": "detailed",
                "description": "简报风格"
            },
            "language": {
                "type": "string",
                "default": "zh",
                "description": "输出语言"
            }
        },
        "required": ["items"]
    }
}
```

#### Tool 7: `reflect_quality` (Function Calling)

```python
{
    "name": "reflect_quality",
    "description": "对生成的简报进行质量评估，检查完整性、相关性和连贯性",
    "parameters": {
        "type": "object",
        "properties": {
            "brief_content": {"type": "string"},
            "original_items": {"type": "array"},
            "user_profile": {"type": "object"}
        },
        "required": ["brief_content", "original_items"]
    }
}
```

#### Tool 8: `deliver_brief` (MCP - stdio)

**选择理由：** 推送渠道（邮件/微信/钉钉/飞书）各自有独立的 SDK 和认证流程，通过 MCP stdio 方式：
- 每个渠道可作为独立 MCP Server 进程运行
- 主 Agent 通过 stdio 启动子进程，隔离推送服务的依赖
- 用户可按需启用/禁用某个渠道，渐进式加载

```python
# MCP Server 接口定义 (mcp-delivery-server)
{
    "name": "deliver_brief",
    "description": "将生成的简报推送到指定渠道",
    "parameters": {
        "type": "object",
        "properties": {
            "brief_content": {"type": "string"},
            "channel": {
                "type": "string",
                "enum": ["email", "wechat", "dingtalk", "web"],
                "default": "web"
            },
            "recipient": {"type": "string"}
        },
        "required": ["brief_content", "channel"]
    }
}

# MCP Server 启动配置
# transport: stdio
# 启动命令: python -m mcp_delivery_server --channel web --transport stdio
# 主 Agent 通过 subprocess 启动并通信
```

#### Tool 9: `update_memory` (Function Calling)

```python
{
    "name": "update_memory",
    "description": "根据用户反馈更新长期记忆和偏好向量",
    "parameters": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "feedback_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_id": {"type": "string"},
                        "feedback_type": {"type": "string", "enum": ["like", "dislike", "irrelevant", "valuable"]},
                        "item_embedding": {"type": "array"}
                    }
                }
            }
        },
        "required": ["user_id", "feedback_items"]
    }
}
```

#### Tool 10: `retrieve_memory` (Function Calling)

```python
{
    "name": "retrieve_memory",
    "description": "从长期记忆中检索与用户当前兴趣相关的偏好向量和历史反馈",
    "parameters": {
        "type": "object",
        "properties": {
            "user_id": {"type": "string"},
            "query_embedding": {"type": "array"},
            "top_k": {"type": "integer", "default": 5}
        },
        "required": ["user_id", "query_embedding"]
    }
}
```

---

## 4. 记忆系统设计

### 4.1 四层记忆架构

| 记忆类型 | 存储介质 | 存储内容 | 检索方式 | 更新机制 |
|----------|----------|----------|----------|----------|
| **短期记忆** | Python 内存 (deque) | 当前会话的 10-20 轮对话历史 | 滑动窗口直接读取 | 每轮对话追加，超窗自动丢弃 |
| **长期记忆** | ChromaDB (本地) | 用户偏好向量、兴趣主题 embedding、正负反馈记录 | 向量相似度检索 (cosine) | 反馈触发增量更新，定期合并 |
| **情节记忆** | SQLite (`task_history` 表) | 历史任务执行记录：触发时间、采集源、去重率、简报质量分、用户满意度 | SQL 查询 + 时间范围过滤 | 每次任务完成后自动记录 |
| **语义记忆** | ChromaDB (独立 collection) | 领域知识文档（如"AI Agent 技术栈"、"新能源车产业链"）的 embedding | RAG 检索，top-k 相似度 | 手动导入或定期爬取更新 |

### 4.2 记忆交互流程

```
用户反馈 ──→ 短期记忆记录 ──→ 反馈分析节点 ──┬──→ 更新长期记忆 (ChromaDB 偏好向量)
                                              └──→ 更新情节记忆 (SQLite 执行记录)
                                              
定时任务触发 ──→ 检索长期记忆 (用户偏好) ──→ 加载到 State.user_profile
            ──→ 检索语义记忆 (领域知识) ──→ 加载到 State.retrieved_memories
```

### 4.3 长期记忆向量设计

ChromaDB Collection: `user_preferences`

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | string | `user_id#topic#timestamp` |
| `embedding` | float[] | 主题/条目的向量表示 |
| `metadata` | dict | `{user_id, topic, feedback_type, weight, timestamp}` |
| `document` | string | 原始文本内容 |

---

## 5. 排序算法设计

### 5.1 打分公式

```
final_score(item) = α · sim(item, user_profile) + β · time_decay(item) + γ · preference_weight(item) + δ · source_authority(item)

其中:
  sim(item, user_profile) = cosine_similarity(item_embedding, user_preference_vector)
  
  time_decay(item) = exp(-λ · (now - pub_time) / 3600)  # 小时为单位，λ=0.1
  
  preference_weight(item) = Σ[feedback_type · weight · decay_factor]
    - like: +1.0
    - valuable: +1.5  
    - dislike: -0.8
    - irrelevant: -1.2
    - decay_factor = exp(-0.05 · days_since_feedback)
  
  source_authority(item) = 预定义来源权重 (权威媒体 1.0, 自媒体 0.6, 论坛 0.4)
```

### 5.2 权重参数 (MVP 初始值)

| 参数 | 值 | 说明 |
|------|-----|------|
| α (向量相似度) | 0.35 | 核心个性化指标 |
| β (时间衰减) | 0.25 | 保证时效性 |
| γ (偏好权重) | 0.30 | 用户反馈直接影响 |
| δ (来源权威) | 0.10 | 降低噪音来源影响 |
| λ (时间衰减系数) | 0.1 | 24小时后衰减到 ~0.37 |

### 5.3 动态调权机制

用户连续 3 次对某类内容反馈 "like" → 自动提升该 topic 的 α 权重 +0.05（上限 0.5）
用户连续 2 次反馈 "irrelevant" → 自动降低该 topic 的 α 权重 -0.05（下限 0.1）

---

## 6. 去重策略设计

### 6.1 核心策略：向量相似度 + 规则校验

**步骤 1：粗筛（规则层）**
- URL 完全一致 → 直接去重（保留最早发布）
- 标题编辑距离 < 3 → 进入精筛

**步骤 2：精筛（向量层）**
- 使用 `BAAI/bge-small-zh-v1.5` 生成标题+摘要的 embedding
- 计算余弦相似度，阈值 `threshold = 0.85`

### 6.2 阈值设定与校准

| 场景 | 阈值 | 说明 |
|------|------|------|
| 严格去重（同一事件） | 0.90 | 标题高度相似 + 内容重叠 > 80% |
| 宽松去重（不同角度） | 0.75 | 同一事件但不同视角报道，保留 |
| MVP 默认 | 0.85 | 平衡去重率和信息多样性 |

### 6.3 区分「同一事件不同角度」与「真正重复」

```
if similarity > 0.90:
    → 真正重复，保留权威来源/最早来源
elif 0.75 < similarity <= 0.90:
    → 同一事件不同角度，保留但标记为 "related_group"
    → 简报中合并展示：主条目 + 相关视角链接
elif similarity <= 0.75:
    → 不同事件，独立保留
```

### 6.4 校准方法

- **冷启动期（前 50 条）**：人工标注 20 对样本，校准阈值
- **运行期**：每周抽样检查去重结果，根据用户 "dislike:重复内容" 反馈自动下调阈值 0.01

---

## 7. 数据模型（SQLite）

### 7.1 表结构

```sql
-- 用户表
CREATE TABLE users (
    user_id         TEXT PRIMARY KEY,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    topics          TEXT,           -- JSON ["AI Agent", "新能源车"]
    delivery_time   TEXT DEFAULT '08:00',  -- 每日推送时间
    delivery_channel TEXT DEFAULT 'web',
    preference_vector BLOB,         -- 序列化的偏好向量快照
    active          INTEGER DEFAULT 1
);

-- 信息源表
CREATE TABLE sources (
    source_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    source_type     TEXT CHECK(source_type IN ('rss', 'search')),
    source_name     TEXT,
    url_or_query    TEXT,
    source_weight   REAL DEFAULT 1.0,  -- 来源权威权重
    is_active       INTEGER DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- 信息条目表
CREATE TABLE items (
    item_id         TEXT PRIMARY KEY,  -- hash(url+title)
    source_id       INTEGER,
    title           TEXT,
    url             TEXT,
    content         TEXT,
    summary         TEXT,
    category        TEXT,
    keywords        TEXT,           -- JSON
    importance      INTEGER CHECK(importance IN (1,2,3)),  -- 1=高 2=中 3=低
    pub_date        TIMESTAMP,
    fetched_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    embedding       BLOB,           -- 序列化向量
    similarity_group TEXT,         -- 去重分组标识
    is_duplicate    INTEGER DEFAULT 0,
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

-- 反馈表
CREATE TABLE feedback (
    feedback_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         TEXT NOT NULL,
    item_id         TEXT NOT NULL,
    feedback_type   TEXT CHECK(feedback_type IN ('like', 'dislike', 'irrelevant', 'valuable')),
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    context         TEXT,           -- 反馈时的会话上下文摘要
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (item_id) REFERENCES items(item_id)
);

-- 简报表
CREATE TABLE briefs (
    brief_id        TEXT PRIMARY KEY,  -- session_id
    user_id         TEXT NOT NULL,
    generated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content         TEXT,           -- Markdown 内容
    item_count      INTEGER,
    quality_score   REAL,
    reflection_notes TEXT,
    delivery_status TEXT DEFAULT 'pending',
    delivered_at    TIMESTAMP,
    user_rating     INTEGER,        -- 1-5 星评分
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

-- 情节记忆表（任务执行记录）
CREATE TABLE task_history (
    task_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT,
    user_id         TEXT,
    trigger_type    TEXT,
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    items_fetched   INTEGER,
    items_deduped   INTEGER,
    items_ranked    INTEGER,
    quality_score   REAL,
    user_satisfaction INTEGER,    -- 用户是否满意
    error_log       TEXT
);
```

---

## 8. 技术栈选择

| 层级 | 技术选型 | 理由 |
|------|----------|------|
| **LLM** | DeepSeek-V3 / 通义千问 (Qwen-Max) | 国内可用、API 稳定、成本低、中文能力强 |
| **Embedding** | BAAI/bge-small-zh-v1.5 | 中文效果优秀、模型小（100MB）、本地可跑 |
| **Agent 框架** | LangGraph (StateGraph) | 状态驱动、节点可复用、支持循环和条件分支，比纯 LangChain Agent 更适合复杂工作流 |
| **定时调度** | APScheduler | Python 原生、支持 Cron 表达式、可持久化任务 |
| **向量数据库** | ChromaDB | 轻量、单机可跑、Python 原生 API、无需额外服务 |
| **结构化数据库** | SQLite | 零配置、单文件、足够支撑 MVP 数据量 |
| **前端** | Streamlit | 30 分钟搭出可用界面、支持 Markdown 渲染、适合演示 |
| **RSS 解析** | feedparser | 成熟稳定、支持各种 RSS/Atom 格式 |
| **搜索** | SearXNG (自建) / 必应 API | SearXNG 免费聚合多引擎，避免单一依赖 |
| **MCP SDK** | `mcp` (官方 Python SDK) | 标准协议、支持 stdio 和 SSE 两种传输 |
| **部署** | 本地运行 / Docker | MVP 阶段无需云服务，单机可完整演示 |

---

## 9. MVP 范围界定

### 9.1 MVP 必须实现（核心闭环）

| 模块 | 功能 | 验证标准 |
|------|------|----------|
| 用户配置 | 设置关注主题、推送时间、信息源 | Streamlit 表单可配置 |
| RSS 采集 | 从 3-5 个 RSS 源定时采集 | 每日成功获取 >50 条 |
| 搜索采集 | 基于主题关键词搜索补充 | 每日成功获取 >20 条 |
| 向量去重 | 基于 embedding 去重，阈值 0.85 | 去重率 20-40%，误删率 <5% |
| 智能排序 | 综合打分排序，取 Top 15 | 排序结果与用户偏好正相关 |
| 简报生成 | 生成结构化 Markdown 简报 | 包含分类、重要性、来源引用 |
| 质量反思 | LLM 自评 + 不达标重试 | 质量分 >0.7 或重试 3 次 |
| 推送展示 | Streamlit 展示简报 | 可阅读、可交互 |
| 反馈收集 | 点赞/踩/不相关/有价值 | 反馈存入数据库 |
| 记忆更新 | 反馈更新 ChromaDB 偏好向量 | 下次排序体现偏好变化 |

### 9.2 后续迭代（非 MVP）

| 功能 | 迭代阶段 | 说明 |
|------|----------|------|
| MCP 搜索服务独立部署 | Phase 2 | 当前搜索用 Function Calling 直连，后续拆为 MCP Server |
| 多推送渠道（微信/钉钉/邮件） | Phase 2 | MVP 仅 Web 展示 |
| 语义记忆 RAG | Phase 2 | MVP 仅长期记忆，不加领域知识库 |
| 情节记忆学习 | Phase 3 | 基于历史任务记录优化执行策略 |
| 多用户支持 | Phase 3 | MVP 单用户演示 |
| 子 Agent 协作 | Phase 4 | 采集 Agent、分析 Agent、生成 Agent 分离 |

---

## 10. 阶段性目标与任务拆解

### Phase 1：基础骨架搭建（复杂度：低）

| 项目 | 内容 |
|------|------|
| **阶段目标** | 搭建可运行的 LangGraph 骨架，实现从 RSS 采集到简报生成的端到端流程（手动触发） |
| **交付物** | 1. 可运行的 Python 脚本，输入主题 → 输出 Markdown 简报文件<br>2. LangGraph StateGraph 代码，包含 init → fetch → dedup → rank → generate 节点<br>3. 验证：运行 3 次，每次生成有效简报 |
| **关键任务** | ① 项目结构搭建（config/ src/ tests/）<br>② SQLite 表结构初始化<br>③ ChromaDB collection 创建<br>④ LangGraph StateGraph 基础节点实现<br>⑤ RSS 采集工具实现<br>⑥ 简报生成 Prompt 设计 |
| **依赖** | 无 |
| **复杂度** | 低 |

---

### Phase 2：核心算法实现（复杂度：中）

| 项目 | 内容 |
|------|------|
| **阶段目标** | 实现去重、排序、质量反思三个核心算法，形成完整数据处理闭环 |
| **交付物** | 1. 去重模块：输入 100 条模拟数据，输出去重后列表，准确率 >95%<br>2. 排序模块：给定用户偏好和条目，输出合理排序<br>3. 反思模块：LLM 自评简报质量，不达标触发重试<br>4. 验证：端到端测试，从采集到生成全流程自动化 |
| **关键任务** | ① Embedding 模型接入（bge-small-zh）<br>② 向量去重算法实现 + 阈值调优<br>③ 排序打分公式实现（α/β/γ/δ 参数可调）<br>④ 质量反思 Prompt + 评分逻辑<br>⑤ 重试循环机制（max_retry=3）<br>⑥ 单元测试覆盖核心算法 |
| **依赖** | Phase 1 |
| **复杂度** | 中 |

---

### Phase 3：记忆与反馈闭环（复杂度：中）

| 项目 | 内容 |
|------|------|
| **阶段目标** | 实现四层记忆体系和用户反馈闭环，Agent 能根据反馈调整后续输出 |
| **交付物** | 1. 用户反馈界面（Streamlit 按钮：点赞/踩/不相关/有价值）<br>2. 反馈 → 长期记忆更新链路验证：反馈后下次排序发生变化<br>3. 短期记忆滑动窗口实现<br>4. 情节记忆记录（task_history 表写入）<br>5. 验证：连续 3 天使用，观察排序偏好是否收敛 |
| **关键任务** | ① ChromaDB 偏好向量存储/检索实现<br>② 反馈权重更新算法<br>③ 短期记忆滑动窗口管理<br>④ 情节记忆表设计与写入<br>⑤ Streamlit 反馈交互界面<br>⑥ 偏好收敛性测试 |
| **依赖** | Phase 2 |
| **复杂度** | 中 |

---

### Phase 4：定时调度与 MCP 接入（复杂度：高）

| 项目 | 内容 |
|------|------|
| **阶段目标** | 实现定时自主执行，接入 MCP 协议完成工具解耦 |
| **交付物** | 1. APScheduler 定时任务：每天 8:00 自动触发简报生成<br>2. MCP 搜索 Server（SSE 模式）独立运行<br>3. MCP 推送 Server（stdio 模式）独立运行<br>4. Function Calling + MCP 混合调用路由实现<br>5. 验证：定时任务连续运行 7 天无故障 |
| **关键任务** | ① APScheduler 定时触发器配置<br>② MCP Server 开发（搜索 + 推送）<br>③ MCP Client 接入 LangGraph<br>④ 工具调用路由层（自动选择 FC/MCP）<br>⑤ 异常处理与重试机制<br>⑥ 日志系统完善 |
| **依赖** | Phase 3 |
| **复杂度** | 高 |

---

### Phase 5：工程化与演示（复杂度：中）

| 项目 | 内容 |
|------|------|
| **阶段目标** | 代码工程化、文档完善、准备面试演示 |
| **交付物** | 1. 完整 README + 架构文档<br>2. Streamlit 演示界面（配置页 + 简报页 + 反馈页 + 历史页）<br>3. 演示视频/GIF（3 分钟展示完整流程）<br>4. 性能报告：去重率、排序准确率、生成质量分统计<br>5. 代码仓库（GitHub，含 CI 基础配置） |
| **关键任务** | ① 代码重构与模块化<br>② 配置管理（YAML/环境变量）<br>③ Streamlit 多页面应用<br>④ 文档撰写（README + 架构说明 + 使用指南）<br>⑤ 演示脚本准备<br>⑥ 性能指标收集与可视化 |
| **依赖** | Phase 4 |
| **复杂度** | 中 |

---

## 总结

FeedLens 的核心竞争力在于展示 **Agent 的自主规划能力**（定时触发 → 任务分解 → ReAct 循环 → 反思修正）和 **持续学习能力**（用户反馈 → 记忆更新 → 排序优化）。通过 LangGraph 的 StateGraph 实现状态驱动的工作流，通过 Function Calling 和 MCP 的混合使用展示工程上的工具解耦思维，通过四层记忆体系展示对 Agent 记忆机制的深入理解。
