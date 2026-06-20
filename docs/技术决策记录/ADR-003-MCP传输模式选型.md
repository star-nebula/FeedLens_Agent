# ADR-003: MCP 传输模式 — Push stdio / Search SSE

| 元数据 | |
|--------|--------|
| **状态** | 已采纳 |
| **日期** | 2026-06-17 |
| **决策者** | 项目决策组 |
| **来源** | WB+TRAE 共识、决策 T1 |

## 上下文

FeedLens 有 2 个 MCP Server：
- `search_web`：搜索采集，对接外部搜索 API
- `push_notification`：简报推送，本地 Streamlit 通知服务

MCP 支持两种 Transport 模式：stdio（子进程通信）和 SSE（HTTP 流式通信）。需要为每个 MCP Server 选择合适的 Transport。

| 方案 | 支持文档 |
|------|---------|
| Push: stdio（5份） vs SSE（3份） | DeepSeek/GLM/Kimi/TRAE/Codex_Mimo vs Codex_DeepSeek/Perplexity/Qwen |
| Search: SSE（7份共识） vs stdio（0份） | 7/7 文档共识 SSE |

## 决策

- `push_notification` → **stdio 模式**
- `search_web` → **SSE 模式**（监听 :8100）

## 理由

**Push 用 stdio**：
1. 推送是本地操作（Streamlit 应用内通知），无跨机器调用需求
2. stdio 随主进程启停，无需端口管理、无需守护进程
3. SSE 的优势是跨机器远程调用，但 MVP 所有组件同机运行
4. 5/8 文档共识 Push 用 stdio

**Search 用 SSE**：
1. 搜索对接外部 HTTP API，SSE 支持流式返回（大搜索结果集可逐步返回）
2. 独立进程管理连接池，与主 Agent 进程隔离
3. 7/7 文档共识 Search 用 SSE，零争议
4. SSE 支持 MCP 客户端通过 HTTP 端点发现和连接服务

## 影响

- MVP 有 2 个 MCP Server，使用不同的 Transport 模式
- search_web 需管理 :8100 端口的生命周期（启动/停止/重连）
- push_notification 作为子进程，无需端口管理
- SSE 连接需要处理断线降级（已设计：断线→降级仅 RSS 模式）

## 容错设计

| 场景 | 处理策略 |
|------|---------|
| SSE 连接中断 | 立即降级为仅 RSS 模式，不阻塞采集流程 |
| Search API 超时 | 降级为仅使用 RSS 采集结果 |
| Push 进程崩溃 | 主进程捕获异常，记录日志，下次推送时重新启动子进程 |
