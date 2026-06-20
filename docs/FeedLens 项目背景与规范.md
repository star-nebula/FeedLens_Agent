# FeedLens 项目背景与规范

***

## 一、项目背景

### 1.1 项目愿景

FeedLens 是一个**主动式信息聚合 Agent 系统**。它不是被动问答工具，也不是 cron + pipeline，而是能**自主规划、调度子 Agent、定时执行、个性化筛选**的多 Agent 智能体系统。

核心差异化在于展示 Agent 的「自主规划 + 多 Agent 协调 + 定时执行 + 个性化筛选」能力——planner 节点自主决定本轮调用哪些子 Agent、什么顺序、是否需要补充数据。

### 1.2 MVP 核心假设

> **假设**：用户愿意每天收到一份「5-10 条高价值、已去重、按个人偏好排序」的信息简报，并通过反馈持续改善推送质量。

***

## 二、技术栈选型

| 组件           | 选型                     | 说明                           |
| :----------- | :--------------------- | :--------------------------- |
| Agent 编排框架   | LangGraph StateGraph   | 支持多 Agent 自主规划、ReAct 循环、条件分支 |
| LLM          | DeepSeek Chat          | 性价比高，支持 Function Calling     |
| Embedding 模型 | bge-small-zh-v1.5      | 轻量级、中文支持好、推理速度 < 100ms/条     |
| 向量数据库        | ChromaDB               | 轻量、易用、支持元数据过滤                |
| 关系型数据库       | SQLite + WAL 模式        | 轻量、无需部署、支持并发读写               |
| 定时任务         | APScheduler            | Python 原生、灵活、支持 cron         |
| 搜索补充         | MCP Server (SSE :8100) | 支持流式搜索结果返回                   |
| 推送服务         | MCP Server (stdio)     | 作为子进程随主进程启停                  |
| 用户界面         | Streamlit              | 快速构建数据应用                     |
| 日志           | structlog              | 结构化日志，便于调试和分析                |

***

## 三、架构设计

### 3.1 六层架构

```
展示层 (Streamlit) → 规划层 (主Agent) → 执行层 (子Agent) → 工具层 (FC/MCP) → 记忆层 → 数据层
```

### 3.2 多 Agent 架构

| Agent        | 职责                      | ReAct 能力               |
| :----------- | :---------------------- | :--------------------- |
| **主 Agent**  | 自主编排子 Agent、综合质量审查、推送交付 | ✅ Planner 自主决策         |
| **采集 Agent** | RSS 采集 + 搜索补充 + 元数据提取   | ✅ Think→Act→Observe 循环 |
| **排序 Agent** | 智能去重 + 偏好排序             | ✅ Think→Act→Observe 循环 |
| **简报 Agent** | 简报生成 + 质量审查             | ❌ 线性流程                 |
| **反馈 Agent** | 反馈处理 + 偏好向量更新           | ❌ 单次执行                 |

### 3.3 主 Agent 工作流

```
understand_intent → planner → invoke_sub_agent → observe → 
  planner(再思考) → reflect → push_notification → update_memory
```

***

## 四、核心算法

### 4.1 排序公式

```
final_score = w₁·similarity + w₂·recency + w₃·preference + w₄·importance
```

| 因子         | 含义            | 计算方式                                              |
| :--------- | :------------ | :------------------------------------------------ |
| similarity | 内容与用户关注领域的相似度 | cosine(item\_embedding, user\_preference\_vector) |
| recency    | 时间新鲜度         | exp(-Δt / τ)，τ = 24h                              |
| preference | 用户偏好匹配度       | cosine(item\_embedding, user\_preference\_vector) |
| importance | 新闻重要性         | LLM 评估 1-5 分，归一化至 0-1                             |

### 4.2 权重动态切换

| 阶段  | 条件         | w₁   | w₂   | w₃   | w₄   |
| :-- | :--------- | :--- | :--- | :--- | :--- |
| 冷启动 | 用户反馈 < 3 条 | 0.40 | 0.25 | 0.10 | 0.25 |
| 有反馈 | 用户反馈 ≥ 3 条 | 0.30 | 0.20 | 0.40 | 0.10 |

### 4.3 去重策略

| 相似度       | 判定  | 处理                         |
| :-------- | :-- | :------------------------- |
| ≥ 0.88    | 重复  | 保留代表，标注「还有 N 篇类似报道」        |
| ≤ 0.70    | 不重复 | 保留                         |
| 0.70-0.88 | 模糊  | LLM 裁决，最多 20 对，超限按 0.80 硬判 |

### 4.4 反馈权重

| 反馈         | 调整值   | 语义     |
| :--------- | :---- | :----- |
| like       | +0.15 | 强化此类偏好 |
| dislike    | -0.10 | 弱化此类偏好 |
| irrelevant | -0.15 | 从候选集移除 |

***

## 五、数据模型

### 5.1 SQLite 表（11 张）

| 表名                | 用途      |
| :---------------- | :------ |
| user\_goals       | 用户关注目标  |
| feed\_sources     | RSS 源管理 |
| raw\_items        | 原始采集条目  |
| feed\_items       | 标准化后的条目 |
| item\_relations   | 去重关系记录  |
| feedback          | 用户反馈记录  |
| execution\_logs   | 执行日志    |
| run\_logs         | 运行记录    |
| user\_preferences | 用户偏好配置  |
| categories        | 分类定义    |
| keywords          | 关键词管理   |

### 5.2 ChromaDB 集合（3 个）

| 集合名               | 用途                           |
| :---------------- | :--------------------------- |
| feed\_items       | 已处理条目的向量存储                   |
| user\_preference  | 用户偏好向量（v\_like / v\_dislike） |
| domain\_knowledge | 领域知识（种子数据）                   |

***

## 六、功能优先级

| 优先级    | 定义       | 包含功能                                             |
| :----- | :------- | :----------------------------------------------- |
| **P0** | MVP 核心功能 | 主 Agent Planner、采集 Agent、排序 Agent、简报 Agent、推送与反馈 |
| **P1** | 重要增强     | 反思增强、偏好更新、反馈子 Agent、执行仪表盘                        |
| **P2** | 后续迭代     | Telegram 推送、多用户认证、Docker Compose、跨类别配额           |

***

## 七、开发约束

| 约束                      | 值              | 说明                 |
| :---------------------- | :------------- | :----------------- |
| max\_react\_cycles      | 3              | 主 Agent ReAct 循环上限 |
| max\_llm\_adjudications | 20             | 去重模糊区间裁决上限         |
| 简报质量阈值                  | score < 0.7 重试 | 最多重试 2 次           |
| 冷启动阈值                   | 反馈数 < 3        | 使用冷启动权重            |
| 偏好清理阈值                  | 权重 < 0.1       | 自动清理               |

***

## 八、推送规则

| 类型   | 条件                    | 说明                   |
| :--- | :-------------------- | :------------------- |
| 定时推送 | 每日固定时间                | APScheduler cron job |
| 破例推送 | score > 0.85 且时效 < 2h | 重大事件立即推送             |

***

## 九、业务闭环

```
用户设定 Goal → LLM 提取偏好 → APScheduler 定时触发
       ↓
主 Agent planner 自主编排子 Agent
       ↓
采集 Agent → 排序 Agent → 简报 Agent → reflect
       ↓
推送（定时 + 重大事件破例）→ 用户反馈
       ↓
反馈子 Agent → 偏好向量更新 → 影响后续排序
```

***

## 十、性能指标

| 指标           | 目标                   |
| :----------- | :------------------- |
| 单次 Agent 运行  | < 60s（采集 10 条 RSS 源） |
| Embedding 推理 | < 100ms/条            |
| 排序+简报        | < 30s                |

***

这个规范文档涵盖了项目的核心背景、技术选型、架构设计、算法规范和数据模型，可以作为后续开发的参考依据。
