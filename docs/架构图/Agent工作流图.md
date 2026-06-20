# FeedLens Agent 工作流图（v3.0 多Agent ReAct编排）

> 本文档替代 `Agent工作流图.drawio`，以结构化 Markdown 描述主Agent ReAct循环 + 4个子Agent的完整工作流程。

---

## 一、主Agent工作流（Coordinator + Planner）

### 1.1 核心ReAct循环

主Agent的核心不再是线性流水线，而是 **planner 自主编排的 ReAct 循环**：

```
understand_intent → planner(Think) → invoke_sub_agent(Act) → observe_results(Observe)
                                                          │
                                          ┌───────────────┘
                                          │ planner 再思考
                                          │ 需要补充? → 回到 invoke
                                          │ Done? → 继续 reflect
```

### 1.2 完整节点序列

| 步骤 | 节点 | ReAct步骤 | 职责 | 关键输出 |
|------|------|-----------|------|---------|
| 1 | `understand_intent` | — | 识别触发类型、提取结构化偏好 | `trigger_type`, `structured_goal` |
| 2 | **`planner`** | **Think** | LLM自主编排子Agent调用计划 | `sub_agent_plan`, `planner_reasoning` |
| 3 | `invoke_sub_agent` | **Act** | 按plan调度子Agent执行 | `sub_agent_results` |
| 4 | `observe_results` | **Observe** | 评估子Agent输出质量 | 观察评估结论 |
| 5 | `planner (再思考)` | **Think** | 决策：需要补充? Done? | 循环或前进 |
| 6 | `reflect` | — | 综合质量审查、矛盾检查 | `brief_quality`, `reflection_notes` |
| 7 | `push_notification` | — | MCP stdio推送简报 | 推送状态 |
| 8 | `update_memory` | — | 偏好向量更新、执行日志写入 | 更新完成 |

### 1.3 回退路径

| 回退场景 | 起点 → 目标 | 条件 |
|----------|-------------|------|
| **ReAct循环回退** | planner(再思考) → invoke_sub_agent | planner判断"需要补充" |
| **reflect重试回退** | reflect → invoke_sub_agent | `brief_quality < 0.7`，最多重试2次 |

### 1.4 ReAct循环约束

- 最多 **3个ReAct循环**（防止无限循环）
- 每次循环 planner 决定：调用哪个子Agent、传什么参数、是否跳过
- 循环结束条件：planner 判断 "Done" 或达到最大循环数

---

## 二、触发源

| 触发源 | 触发类型 | 触发方式 | 调用入口 |
|--------|---------|---------|---------|
| **APScheduler** | `daily_briefing` | 每日定时触发 | `understand_intent` |
| **用户手动** | `manual_search` | Streamlit界面触发 | `understand_intent` |
| **用户反馈** | `feedback_update` | like/dislike/irrelevant | `FeedbackAgent`（独立入口） |

---

## 三、子Agent内部流程

### 3.1 采集Agent（CollectionAgent）— ReAct循环

```
Think(判断采集策略)
  │ 是否需要搜索补充?
  ↓
Act: fetch_rss (FC, feedparser, 并行采集多个源)
  │
  ↓
Act: search_web (MCP SSE :8100, 条件触发搜索补充) ←── 条件触发
  │
  ↓
Observe(评估采集结果)
  │ items < 5? → 补充搜索
  │ items >= 5? → 继续处理
  ↓
enrich_metadata (FC, LLM提取分类/关键词/重要性)
  │
  ↓
normalize_items (FC, 统一字段格式)
  │
  ↓
Done → 返回 normalized_items → 主Agent observe
```

**ReAct循环点**：
- Think → 判断是否需要搜索补充
- Observe → 评估采集结果是否足够

**输入/输出**：
- 输入：`{goal: dict, search_count: int}`
- 输出：`{raw_items: list, normalized_items: list, items_count: int}`

---

### 3.2 排序Agent（RankingAgent）— ReAct循环

```
Think(检索偏好向量, 规划排序策略)
  │
  ↓
Act: vector_search (FC, ChromaDB, 检索偏好向量)
  │
  ↓
Act: deduplicate (FC)
  │ ≥0.88 → 重复 (直接合并)
  │ 0.70-0.88 → LLM裁决 (最多20次)
  │ ≤0.70 → 不重复 (独立条目)
  ↓
Act: rank_items (FC, 多因子动态权重)
  │ 冷启动: w1=0.40(相似度), w2=0.30(时效), w3=0.20(权威), w4=0.10(多样性)
  │ 有反馈: w1=0.25, w2=0.20, w3=0.40(偏好), w4=0.15
  │ 时间衰减: exp(-Δt/τ), τ=24h
  ↓
Observe(评估排序结果)
  │ 偏好匹配度? 需要调参?
  │ 不满意 → 回退到 Think 重新规划
  ↓
Done → 返回 ranked_items → 主Agent observe
```

**ReAct循环点**：
- Think → 检索偏好向量、规划排序策略
- Observe → 评估排序结果是否满意

**输入/输出**：
- 输入：`{normalized_items: list, goal: dict, feedback_count: int}`
- 输出：`{deduped_items: list, ranked_items: list, dedup_rate: float}`

---

### 3.3 简报Agent（BriefingAgent）— 线性流程

```
generate_briefing (FC, LLM→JSON)
  │ 沿用 category/importance
  │ items 按 category 分组
  │ 组内按 importance 降序
  ↓
reflect (FC, 质量评分)
  │ completeness / relevance / coherence 三维度
  │ score < 0.7? → 重试(最多2次)
  │ score >= 0.7? → 继续
  ↓
JSON → Markdown 渲染
  │ 计数标注显示
  ↓
Done → 返回 briefing + brief_quality → 主Agent reflect
```

**无ReAct循环** — 简报生成是确定性流程，只有重试机制（score < 0.7时回退到 generate_briefing）。

**输入/输出**：
- 输入：`{ranked_items: list, goal: dict}`
- 输出：`{briefing: dict, brief_quality: dict}`

---

### 3.4 反馈Agent（FeedbackAgent）— 异步触发

```
用户反馈触发
  │ like (+0.15) / dislike (-0.10) / irrelevant (-0.15)
  ↓
update_preference (FC, EMA平滑更新)
  │ 正负分离: v_like / v_dislike
  │ 反馈bias归零后EMA接管
  ↓
vector_add (FC, ChromaDB)
  │ 偏好向量写入
  │ 权重 < 0.1 自动清理
  ↓
完成 → 偏好向量影响后续排序Agent的 preference 因子
```

**独立运行**：反馈Agent由用户反馈直接触发，不经过主Agent的planner编排，不阻塞主流程。

**偏好影响路径**：
```
FeedbackAgent → vector_add(偏好向量) → 排序Agent.vector_search → rank_items.preference因子
```

---

## 四、任务生命周期（Harness工程）

FeedLens 采用 **Session → Turn → Event** 三层嵌套生命周期管理：

| 层级 | 定义 | ID | 对应操作 |
|------|------|----|---------|
| **Session** | 用户的一次使用周期 | `session_id` | 贯穿多次 `agent.invoke()` |
| **Turn** | 主Agent一次完整ReAct循环 | `session_id + turn` | = 一次 `agent.invoke()` |
| **Event** | Turn内一个节点执行 | `session_id + turn + event` | 含子Agent调度记录 |

**日志记录**：所有Event写入 `execution_logs` 表，记录节点名、状态(success/error/skipped)、耗时(ms)。

---

## 五、planner自主编排场景

planner 的自主决策能力体现在以下6种编排场景：

| 场景 | 编排路径 | 触发条件 |
|------|---------|---------|
| **① 正常流程** | C → R → B | 采集充足、排序满意 |
| **② 采集不足** | C → (补充搜索) → R → B | 采集Agent Observe 发现 items < 5 |
| **③ 排序不佳** | C → R → (调参重排) → B | 排序Agent Observe 发现偏好匹配度低 |
| **④ 重大事件** | C → R → B → **PushNow** | 条目 score > 0.85 且时效 < 2h |
| **⑤ 跳过采集** | R → B (用上轮数据) | 定时触发但距上次采集间隔短 |
| **⑥ 空数据重采** | C → (0 items) → 重新采集 | RSS源全部返回空 |

> **C = 采集Agent, R = 排序Agent, B = 简报Agent**

---

## 六、State定义

```python
class FeedLensState(TypedDict):
    # 多Agent新增字段
    sub_agent_plan: list[dict]      # Planner输出: 哪些子Agent被调用
    sub_agent_results: dict          # 各子Agent的执行结果
    planner_reasoning: str           # Planner的推理过程

    # 原有字段
    trigger_type: str               # daily_briefing / manual_search / feedback_update
    user_goal: str                  # 用户偏好Goal文本
    structured_goal: dict           # LLM结构化后的偏好
    raw_items: list[dict]           # 采集原始条目
    normalized_items: list[dict]    # 标准化条目
    deduped_items: list[dict]       # 去重后条目
    ranked_items: list[dict]        # 排序后条目
    briefing: dict                  # 简报内容(JSON)
    brief_quality: dict             # 简报质量评分
    retry_count: int                # reflect重试计数(最大2)
    reflection_notes: str           # 反思笔记
    short_term_memory: list[dict]   # 15轮滑动窗口
    retrieved_memories: list[dict]  # 从ChromaDB检索的长期记忆
    feedback_history: list[dict]    # 反馈历史
    execution_metrics: dict         # 执行指标(采集数/去重率/质量分数)
```

---

## 七、关键设计要点

1. **planner是P0核心闭环** — 每次执行都必须经过planner决策，不是可选增强
2. **ReAct只在需要自主决策的地方** — 采集Agent和排序Agent有ReAct，简报Agent线性
3. **反馈Agent完全异步** — 不经过planner，直接由用户反馈触发
4. **3层回退保护** — ReAct循环最多3次、reflect重试最多2次、空数据重新采集
5. **planner编排场景覆盖** — 6种场景涵盖正常、异常、跳过、重采全部情况
6. **Session/Turn/Event三层** — 完整的执行日志追踪体系
