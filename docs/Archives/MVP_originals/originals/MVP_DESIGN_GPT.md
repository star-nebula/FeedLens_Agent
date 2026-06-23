# FeedLens MVP

## 项目定位

FeedLens 是一个基于 LangGraph 的主动式信息发现 Agent。

用户不再订阅固定日报。

用户只定义长期目标：

```text
持续关注 AI Agent

持续关注新能源

持续关注跨境电商
```

之后 Agent 自主：

* 决定是否采集信息
* 决定调用哪些工具
* 决定是否继续搜索
* 决定是否生成简报
* 决定是否立即推送

---

# 一、Agent 架构

```text
┌───────────────────────────────┐
│            User Goal          │
└───────────────┬───────────────┘
                │
                ▼

┌───────────────────────────────┐
│          Planner Agent        │
│                               │
│ 当前应该做什么？               │
│ 是否需要搜索？                 │
│ 是否需要推送？                 │
└───────────────┬───────────────┘
                │
                ▼

        ┌───────┼────────┐

        ▼       ▼        ▼

   Search    Memory    Push

    MCP       Tool      MCP

        ▼       ▼        ▼

          Observation

                ▼

          Reflection

                ▼

           Re-Planning
```

---

# 二、核心 Goal

用户配置：

```json
{
  "goal": "持续关注AI Agent领域的重要进展"
}
```

Agent每次运行都围绕：

```text
Goal
```

而不是：

```text
执行日报流程
```

---

# 三、LangGraph 工作流

## State

```python
class FeedLensState(TypedDict):

    user_id: str

    goal: str

    current_plan: str

    observations: list

    collected_news: list

    selected_news: list

    report: str

    reflection: str

    should_continue: bool

    execution_count: int
```

---

## Graph

```text
START

↓

LoadGoal

↓

Planner

↓

ToolExecutor

↓

Observe

↓

Reflection

↓

Continue?

├─ YES ──────► Planner
│
└─ NO

↓

GenerateBrief

↓

PushDecision

↓

END
```

---

# 四、Planner设计

这是整个项目最重要的节点。

Planner Prompt：

```text
你是FeedLens的信息发现Agent。

用户长期目标：

{goal}

当前已获取的信息：

{observations}

历史偏好：

{memory}

请决定下一步：

1 Search
2 SearchMore
3 GenerateBrief
4 PushNow
5 Stop

输出JSON格式。
```

---

输出：

```json
{
  "action":"Search",
  "query":"AI Agent framework"
}
```

---

# 五、工具体系

## Tool 1

RSS Reader

### Function Calling

```python
get_rss_feed(
    keyword,
    limit
)
```

原因：

简单工具

本地调用

---

## Tool 2

Search MCP

### MCP

```python
search_news(
    query,
    days
)
```

原因：

未来可复用

多个Agent共享

---

部署：

```text
SSE
```

---

## Tool 3

Memory Search

### Function Calling

```python
search_memory(
    query
)
```

---

返回：

```text
用户最近点赞：

Claude Code
OpenHands
Cursor
```

---

## Tool 4

Push MCP

### MCP

```python
push_report(
    user,
    content
)
```

支持：

```text
邮箱
飞书
企业微信
```

---

# 六、长期记忆

## 用户兴趣

存储：

```text
用户点赞文章
```

ChromaDB

---

例如：

```text
Agent工程
Claude Code
MCP
```

---

向量化：

```python
embedding(article)
```

---

检索：

```python
top_k_similarity()
```

---

# 七、情节记忆

这是自主Agent的重要部分。

SQLite：

```sql
agent_experience
```

记录：

```text
任务

动作

结果

评分
```

例如：

```text
搜索Reddit

获得高质量内容

score=0.92
```

---

下一次：

Planner看到：

```text
Reddit效果很好
```

优先搜索。

---

# 八、排序设计

每条新闻：

```text
总分
=
相关性
+
兴趣匹配
+
重要性
+
新鲜度
```

---

公式：

```python
score =
0.4 * relevance
+
0.25 * preference
+
0.20 * importance
+
0.15 * freshness
```

---

### relevance

```python
cos(
news_embedding,
goal_embedding
)
```

---

### preference

来自用户反馈

```text
点赞
+1

点踩
-1
```

---

### importance

LLM评估：

```text
1~5
```

例如：

```text
GPT-6发布

5分

某个人发博客

1分
```

---

### freshness

```python
exp(-0.05 * age_hours)
```

---

# 九、自主推送机制

这是自主Agent和日报系统最大的区别。

不是：

```text
每天9点推送
```

---

而是：

Planner决定。

例如：

```text
发现重大事件
```

```text
OpenAI发布GPT-6
```

↓

Reflection

↓

重要性=5

↓

立即推送

````

---

普通新闻：

```text
积累到一定数量

再生成日报
````

---

# 十、MVP范围

必须实现：

### Agent

* Goal
* Planner
* Reflection
* Memory

---

### Tool

* RSS
* Search
* Push

---

### Memory

* ChromaDB
* Feedback Learning

---

### UI

Streamlit

---

### 调度

APScheduler

---

# 十一、阶段拆解

## Phase1

### Agent骨架

目标：

```text
Planner能够输出Action
```

验证：

```json
{
  "action":"Search"
}
```

---

## Phase2

### Tool Use

目标：

```text
Planner能够驱动工具
```

验证：

```text
Search
↓
返回结果
↓
Observe
```

---

## Phase3

### Reflection

目标：

```text
Agent能够判断是否继续
```

验证：

```text
继续搜索
或
结束
```

---

## Phase4

### Memory

目标：

```text
用户反馈影响决策
```

验证：

```text
点赞Agent新闻

下一轮推荐增加
```

---

## Phase5

### Autonomous Briefing

目标：

```text
Agent自主决定

推送
还是不推送
```

验证：

```text
重大事件立即通知

普通事件进入日报
```

