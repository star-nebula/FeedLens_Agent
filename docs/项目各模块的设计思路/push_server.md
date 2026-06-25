# Push Server（MCP 推送）设计思路

> 简报推送的最后一环，基于 FastMCP 的 stdio 传输，将简报写入本地 JSONL 通知队列供前端消费。

---

## 整体定位

Push Server 是管线的**出口**，负责：
- 接收简报内容（Markdown + JSON）
- 写入本地 JSONL 通知队列文件
- 供 Streamlit 前端读取展示

---

## 完整流程

```
main_agent.push_notification_node
  │
  ▼
MCP Client（stdio 传输）
  │
  ▼
┌─ Push Server（FastMCP stdio server）─────────────────────┐
│                                                         │
│  push(brief, user_id, immediate)                        │
│    │                                                    │
│    ├─ 构建通知对象：                                      │
│    │    {                                               │
│    │      user_id,                                      │
│    │      brief (含 title/summary/items/_markdown),     │
│    │      immediate (是否紧急推送),                       │
│    │      pushed_at (ISO 时间戳),                        │
│    │      read: false                                   │
│    │    }                                               │
│    │                                                    │
│    ├─ 追加写入 data/notifications.jsonl                  │
│    │                                                    │
│    └─ 返回 true / false                                 │
│                                                         │
└─────────────────────────────────────────────────────────┘
  │
  ▼
Streamlit 前端读取 notifications.jsonl → 渲染展示
```

---

## 通知队列格式

```jsonl
{"user_id": 1, "brief": {"title": "...", "markdown": "# ..."}, "immediate": false, "pushed_at": "2026-06-24T16:00:00", "read": false}
{"user_id": 1, "brief": {"title": "...", "markdown": "# ..."}, "immediate": true,  "pushed_at": "2026-06-24T17:00:00", "read": false}
```

---

## 推送内容的优先级

| 优先级 | 内容 | 说明 |
|--------|------|------|
| 1 | `briefing._markdown` | 简报的完整 Markdown 渲染版本 |
| 2 | `briefing` (JSON) | 结构化 JSON，含 title/summary/items |
| 3 | `ranked_items` 摘要 | 无简报时的降级方案（top 5 标题+链接） |

---

## 启动方式

```
# 由主进程通过 MCP stdio client 自动启动
python -m mcp_servers.push_server
```

MCP Client 通过 stdio 与 Push Server 通信，无需 HTTP 端口。

---

## 关键设计决策

| 决策 | 做法 | 理由 |
|------|------|------|
| **JSONL 文件队列** | 追加写文件，不依赖消息队列中间件 | MVP 阶段零外部依赖 |
| **stdio 传输** | FastMCP stdio 而非 HTTP | 进程级通信，无需端口管理 |
| **降级推送** | 无简报时推送 ranked_items 摘要 | 保证用户始终能收到内容 |
| **immediate 标记** | 紧急推送（重大事件）可破例推送 | 支持 breaking_news 触发类型 |

---

## 一句话总结

> 接收简报 → 构建通知对象 → 追加写入 JSONL 文件 → 前端轮询读取展示。
