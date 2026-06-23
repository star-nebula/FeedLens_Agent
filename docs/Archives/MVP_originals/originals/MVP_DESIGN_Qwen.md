### 1. 系统架构图

以下是 FeedLens 的整体架构，清晰划分了 Agent 的五层结构及工程组件：

```mermaid
graph TD
    subgraph 感知层 Perception
        Scheduler[定时调度器 APScheduler] -->|触发| TriggerNode
        UserUI[Streamlit 前端] -->|手动触发/反馈| TriggerNode
    end

    subgraph 大脑 Brain & 规划 Planning
        LLM[DeepSeek / Qwen LLM]
        Planner[意图理解 & 任务拆解]
        Reflector[反思与质量审查]
    end

    subgraph 工具层 Tools
        direction TB
        subgraph Function Calling (轻量/强上下文)
            FC1[fetch_rss_feeds]
            FC2[calculate_embeddings]
            FC3[format_briefing_text]
        end
        subgraph MCP Servers (解耦/跨进程/外部交互)
            MCP1[search_web_server]
            MCP2[memory_vector_server]
            MCP3[notification_server]
        end
    end

    subgraph 记忆层 Memory
        ShortMem[(短期记忆: LangGraph State)]
        LongMem[(长期/语义记忆: ChromaDB)]
        EpisodicMem[(情节记忆: SQLite task_logs)]
    end

    TriggerNode --> Planner
    Planner -->|ReAct 循环| FC1 & MCP1
    FC1 & MCP1 -->|返回数据| ShortMem
    ShortMem --> FC2 & MCP2
    FC2 & MCP3 -->|处理结果| ShortMem
    ShortMem --> Reflector
    Reflector -->|修正/通过| LLM
    LLM -->|生成简报| MCP3
    MCP3 -->|推送| UserUI
    
    MCP2 <-->|读写偏好| LongMem
    Planner <-->|读写经验| EpisodicMem
```

---

### 2. Agent 工作流设计 (LangGraph)

使用 `StateGraph` 定义工作流，核心思想是**状态驱动**和**反思闭环**。

#### State 定义 (TypedDict)
```python
from typing import TypedDict, Annotated
import operator

class FeedLensState(TypedDict):
    user_id: str
    topics: list[str]
    # 使用 operator.add 实现列表的追加（Reducer）
    raw_items: Annotated[list[dict], operator.add] 
    deduplicated_items: list[dict]
    sorted_items: list[dict]
    briefing_draft: str
    briefing_final: str
    reflection_feedback: str # 反思节点的输出
    error_msg: str
```

#### 节点与边 (Nodes & Edges)
```python
from langgraph.graph import StateGraph, END

workflow = StateGraph(FeedLensState)

# 1. 节点定义
workflow.add_node("fetch_data", fetch_data_node)       # 调用 FC/MCP 采集
workflow.add_node("process_data", process_data_node)   # 去重、排序 (内部调用工具)
workflow.add_node("generate_draft", generate_draft_node) # 大脑生成初稿
workflow.add_node("reflect", reflect_node)             # 大脑反思审查
workflow.add_node("finalize", finalize_node)           # 保存记忆、推送

# 2. 边定义
workflow.set_entry_point("fetch_data")
workflow.add_edge("fetch_data", "process_data")
workflow.add_edge("process_data", "generate_draft")
workflow.add_edge("generate_draft", "reflect")

# 条件边：反思后决定是否重新生成
workflow.add_conditional_edges(
    "reflect",
    should_regenerate, # 路由函数：检查 reflection_feedback 是否包含 "REJECT"
    {
        True: "generate_draft",  # 不满意，回到生成节点（携带反思反馈）
        False: "finalize"        # 满意，进入收尾
    }
)
workflow.add_edge("finalize", END)

app = workflow.compile()
```

---

### 3. 工具清单与调用方式设计

**设计原则**：
- **Function Calling (FC)**：无状态、参数简单、强依赖当前上下文、无需独立部署的内部逻辑。
- **MCP**：有状态、需要独立部署、跨进程/跨 Agent 复用、涉及外部系统交互（数据库、第三方 API）。

| 工具名称 | 描述 | 调用方式 | 选择理由 | MCP 部署与接口 (若适用) |
| :--- | :--- | :--- | :--- | :--- |
| `fetch_rss_feeds` | 解析指定 URL 的 RSS 源获取文章 | **FC** | 纯数据解析，无状态，参数仅为 URL 列表，强依赖当前 topics 上下文。 | - |
| `search_web` | 搜索最新新闻和资讯 | **MCP** | 搜索服务需独立维护 API Key、代理池和并发控制，解耦后其他 Agent 也可复用。 | **SSE 部署**。<br>接口：`{query: str, time_range: str}` |
| `calculate_embeddings` | 将文本转为向量 | **FC** | 调用本地 BGE 模型或简单的 API，无需独立服务，与上下文紧密耦合。 | - |
| `save_preference` | 将用户偏好/反馈存入向量库 | **MCP** | 操作外部 ChromaDB，涉及连接池管理和数据持久化，解耦存储层。 | **stdio 部署** (本地单机)。<br>接口：`{user_id: str, items: list[dict]}` |
| `send_notification` | 推送简报到微信/邮件/钉钉 | **MCP** | 涉及第三方 OAuth 认证、Token 刷新、消息模板，必须独立部署维护。 | **SSE 部署**。<br>接口：`{user_id: str, content: str, channel: str}` |

---

### 4. 记忆系统设计

| 记忆类型 | 存储介质 | 存储内容 | 检索方式 | 更新机制 |
| :--- | :--- | :--- | :--- | :--- |
| **短期记忆** | LangGraph State (内存) | 当前 Turn 的原始数据、中间状态、反思反馈。 | 直接通过 State 字典读取。 | 每次 Turn 开始时初始化，结束时销毁。 |
| **长期记忆 (语义/偏好)** | ChromaDB | 1. 用户画像向量（基于历史点赞/踩提取）。<br>2. 历史高价值文章向量。 | Top-K 向量相似度检索。输入当前文章向量，检索最相关的用户偏好。 | 用户产生反馈（点赞/踩）后，异步更新偏好向量；新文章入库。 |
| **情节记忆** | SQLite (`task_logs` 表) | 历史任务执行 Trace：输入 topics、耗时、去重数量、反思结论、是否成功。 | 按时间倒序查询，或按 `status='failed'` 查询失败经验。 | 每次 Turn 结束时，由 `finalize_node` 追加一条记录。 |

---

### 5. 排序算法设计

采用**多因子加权打分**，避免纯 LLM 排序的不稳定性。

**打分公式**：
$$ Score = w_1 \cdot Sim(U, I) + w_2 \cdot Decay(t) + w_3 \cdot Feedback + w_4 \cdot Authority $$

- **$Sim(U, I)$ (偏好相似度, 权重 0.4)**：文章向量与用户长期偏好向量的余弦相似度。
- **$Decay(t)$ (时间衰减, 权重 0.3)**：$e^{-\lambda \cdot \Delta t}$，$\Delta t$ 为距当前的小时数，$\lambda$ 设为 0.05（约 14 小时半衰期）。
- **$Feedback$ (历史反馈, 权重 0.2)**：该来源或该作者的历史平均点赞率（0~1）。
- **$Authority$ (来源权重, 权重 0.1)**：人工配置的源权重（如官方媒体 1.0，个人博客 0.5）。

*工程 Trick*：先按 $Decay(t)$ 过滤掉 48 小时前的旧闻，再计算综合得分，减少计算量。

---

### 6. 去重策略设计

纯向量去重容易误杀，采用 **“向量粗排 + LLM 精排”** 的两阶段策略。

1. **第一阶段：向量粗排 (低成本)**
   - 计算新文章与库中文章的向量余弦相似度。
   - **阈值设定**：`Sim > 0.88` 直接判定为重复，丢弃。`Sim < 0.70` 直接判定为不重复，保留。
2. **第二阶段：LLM 精排 (处理模糊地带)**
   - 针对 `0.70 <= Sim <= 0.88` 的“疑似重复”文章，调用 LLM 判断。
   - **区分同事件不同角度**：Prompt 要求 LLM 判断两篇文章是“单纯重复”还是“同事件的不同视角”（例如：一篇是产品发布，一篇是深度评测）。
   - **处理逻辑**：如果是同事件不同角度，则保留两者，并在生成简报时让 LLM 将它们合并为一个事件的多角度报道。

---

### 7. 数据模型 (SQLite)

```sql
-- 用户与偏好
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    name TEXT,
    topics TEXT, -- JSON array
    created_at TIMESTAMP
);

-- 信息源管理
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY,
    name TEXT,
    url TEXT,
    type TEXT, -- 'rss' or 'search'
    authority_score REAL
);

-- 采集的条目 (核心表)
CREATE TABLE items (
    item_id TEXT PRIMARY KEY,
    source_id TEXT,
    title TEXT,
    summary TEXT,
    url TEXT,
    published_at TIMESTAMP,
    embedding BLOB, -- 存储向量 (或存 ChromaDB ID)
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

-- 用户反馈 (用于长期记忆更新)
CREATE TABLE feedbacks (
    feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    item_id TEXT,
    action TEXT, -- 'like', 'dislike', 'ignore'
    created_at TIMESTAMP
);

-- 简报记录
CREATE TABLE briefings (
    briefing_id TEXT PRIMARY KEY,
    user_id TEXT,
    content TEXT, -- Markdown 格式简报
    generated_at TIMESTAMP
);

-- 情节记忆 (Agent 执行日志)
CREATE TABLE task_logs (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    trigger_type TEXT, -- 'scheduled', 'manual'
    status TEXT, -- 'success', 'failed'
    input_topics TEXT,
    metrics TEXT, -- JSON: {fetched: 50, deduped: 10, time_cost: 12.5}
    reflection_summary TEXT, -- 反思结论
    created_at TIMESTAMP
);
```

---

### 8. 技术栈选择

| 层级 | 技术选择 | 选择理由 |
| :--- | :--- | :--- |
| **LLM** | DeepSeek-V3 / Qwen-Max | 国内可用，性价比高，Function Calling 和长文本能力优秀。 |
| **Embedding** | BGE-M3 (本地) / 阿里云 text-embedding-v3 | BGE-M3 中文效果极佳，本地部署无 API 限制；若追求轻量可用阿里云 API。 |
| **Agent 框架** | LangGraph | 状态机设计完美契合“采集-处理-生成-反思”的复杂工作流，支持持久化和人工介入。 |
| **MCP 框架** | `mcp` (Python SDK) | 官方标准 SDK，支持 stdio 和 SSE，易于开发 Server 和 Client。 |
| **向量数据库** | ChromaDB | 轻量级，单机运行，Python 原生支持，非常适合 MVP 和单机 Agent。 |
| **关系数据库** | SQLite | 零配置，单文件，足够支撑 MVP 的单机数据量。 |
| **前端** | Streamlit | 开发极快，适合数据展示和简单的交互（点赞/踩），无需前端基础。 |
| **定时调度** | APScheduler | 纯 Python 实现，轻量，支持 Cron 表达式，适合单机定时任务。 |

---

### 9. MVP 范围界定

| 模块 | MVP 必须实现 (Must Have) | 后续迭代 (Nice to Have) |
| :--- | :--- | :--- |
| **采集** | RSS 解析 + 1 个搜索引擎 API (如 SerpAPI/必应) | 更多搜索源、网页正文深度提取、反爬虫代理池 |
| **处理** | 基础向量去重 + 时间/偏好排序 | 复杂 LLM 视角去重、多模态内容处理 |
| **生成** | 结构化 Markdown 简报生成 + 1 次反思 | 多风格简报、语音简报、自动配图 |
| **记忆** | 短期 State + 长期偏好向量 + 基础情节日志 | 复杂的经验图谱、跨用户偏好迁移 |
| **交互** | Streamlit 展示简报、手动触发、基础点赞/踩 | 微信/钉钉自动推送、多用户权限管理 |
| **工程** | 单机运行、APScheduler 定时、基础 MCP | Docker 容器化、分布式调度、监控告警 |

---

### 10. 阶段性目标与任务拆解

#### Phase 1: 数据管道与基础设施 (感知与存储)
- **阶段目标**：跑通数据采集链路，能在前端看到原始数据。
- **交付物**：
  1. 可运行的 RSS 解析和搜索 API 调用脚本。
  2. SQLite 数据库初始化及数据写入逻辑。
  3. Streamlit 基础页面，能展示采集到的原始文章列表。
- **关键任务**：
  - 设计并创建 SQLite 表结构。
  - 实现 `fetch_rss_feeds` (FC) 和 `search_web` (MCP) 工具。
  - 搭建 Streamlit 骨架，实现数据展示。
- **依赖**：无。
- **预估复杂度**：低。

#### Phase 2: Agent 大脑与核心工具链 (规划与执行)
- **阶段目标**：实现 LangGraph 工作流，完成去重、排序和简报生成。
- **交付物**：
  1. 完整的 LangGraph StateGraph 代码。
  2. 能够输入 topics，输出结构化 Markdown 简报。
- **关键任务**：
  - 定义 `FeedLensState`，实现节点函数。
  - 实现 `calculate_embeddings` (FC)，接入 BGE-M3 或阿里云 Embedding。
  - 实现两阶段去重逻辑（向量粗排 + LLM 精排）。
  - 实现多因子排序算法。
  - 编写简报生成 Prompt，集成 DeepSeek/Qwen。
- **依赖**：Phase 1。
- **预估复杂度**：高（核心业务逻辑）。

#### Phase 3: 记忆系统与个性化闭环 (记忆与反思)
- **阶段目标**：引入长期记忆和情节记忆，实现用户反馈驱动的学习。
- **交付物**：
  1. 集成 ChromaDB，实现偏好向量的存取。
  2. Streamlit 上的“点赞/踩”按钮，点击后能影响下一次简报的排序。
  3. 反思节点生效，能自动修正不合格的简报。
- **关键任务**：
  - 部署 ChromaDB，实现 `save_preference` (MCP) 工具。
  - 在排序算法中接入长期偏好向量。
  - 实现 `reflect_node`，编写反思 Prompt，实现条件边路由。
  - 实现情节记忆写入（`task_logs`）。
- **依赖**：Phase 2。
- **预估复杂度**：中。

#### Phase 4: 工程化、自动化与交付 (系统整合)
- **阶段目标**：实现定时自动运行，完善异常处理，达到可演示的 MVP 状态。
- **交付物**：
  1. 定时任务配置，每天自动运行并生成简报。
  2. 完善的错误处理和日志记录。
  3. 完整的 README 和演示视频/截图。
- **关键任务**：
  - 集成 APScheduler，实现定时触发 `TriggerNode`。
  - 实现 `send_notification` (MCP) 工具（可选，或仅在前端展示）。
  - 添加全局异常捕获，确保单次失败不阻塞后续调度。
  - 优化 Streamlit UI，增加配置 topics 的表单。
  - 撰写项目文档，突出架构设计和技术难点。
- **依赖**：Phase 3。
- **预估复杂度**：中。