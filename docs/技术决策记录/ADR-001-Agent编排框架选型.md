# ADR-001: Agent 编排框架选型 — LangGraph StateGraph

| 元数据 | |
|--------|--------|
| **状态** | 已采纳 |
| **日期** | 2026-06-17 |
| **决策者** | 项目决策组 |
| **来源** | 9/9 文档共识 |

## 上下文

FeedLens 需要一个 Agent 编排框架来实现多 Agent 自主规划架构。主 Agent (Coordinator + Planner) 通过 ReAct 循环自主编排子 Agent（采集/排序/简报/反馈），每个子 Agent 有独立的 StateGraph 和决策逻辑。

可选方案：
- **LangGraph StateGraph**：有状态图编排，支持条件边、子图、ReAct 循环
- **CrewAI**：多角色协作框架，预定义角色和任务
- **AutoGen**：微软多 Agent 对话框架
- **纯 Python asyncio**：自定义编排逻辑

## 决策

**采用 LangGraph StateGraph**。

## 理由

1. **9/9 文档共识**：所有分析报告都推荐 LangGraph，零争议
2. **原生支持 ReAct 循环**：主 Agent 的 planner → invoke → observe → planner(再思考) 循环可以用条件边直接实现，无需额外框架
3. **原生支持子图（Subgraph）**：子 Agent 作为 LangGraph 子图被主 Agent 调度，天然适配多 Agent 架构
4. **State TypedDict**：有状态的 State 传递机制，与 Prompt 要求的 "Harness 工程 session→turn→event" 天然映射
5. **Python 原生**：与 MVP 技术栈（Python + Streamlit + ChromaDB + SQLite）无缝集成

## 影响

- 所有 Agent 工作流以 LangGraph StateGraph 定义
- 主 Agent 和子 Agent 各有独立的 StateGraph
- 节点间通过共享 State（TypedDict）传递数据
- 子 Agent 通过 LangGraph 子图调用接口被主 Agent 调度

## 不采纳的方案

| 方案 | 不采纳理由 |
|------|----------|
| CrewAI | 角色预设太强，不支持自定义 ReAct 循环；不适合需要灵活编排的场景 |
| AutoGen | 以对话为核心设计，不适合定时执行的 pipeline-like Agent |
| 纯 Python asyncio | 无编排框架支持，需手动实现状态管理、条件路由、重试逻辑，开发成本显著增加 |
