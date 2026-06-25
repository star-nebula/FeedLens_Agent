# FeedLens 文档导航

> **项目**：基于 LangGraph + DeepSeek 的多 Agent 智能信息简报系统  
> **当前版本**：v2.2.0 | **更新日期**：2026-06-25

---

## 阅读路径指南

根据你的目的，选择不同的阅读路径：

| 目的 | 推荐路径 | 预计耗时 |
|------|---------|---------|
| **快速了解项目** | ①→② | 15 分钟 |
| **面试准备** | ①→②→⑥→③→⑤ | 2 小时 |
| **深入理解架构** | ③→④→⑦→⑤ | 3 小时 |
| **排查问题 / 了解变更** | ⑧→⑨ | 30 分钟 |
| **追溯设计决策** | ⑩ | 1 小时 |

---

## 一、文档地图

### ① 项目概览（4 篇）

快速建立对项目的高层认知。

| 文档 | 定位 | 适合 |
|------|------|------|
| [FeedLens 项目背景.md](./FeedLens%20项目背景.md) | 行业痛点、市场机会、竞品对比 | 所有人 |
| [FeedLens_项目总结.md](./FeedLens_项目总结.md) | 一句话描述 + 核心差异化 + 技术栈 + 10项优化 | 面试 / 简历 |
| [系统运行流程详解.md](./系统运行流程详解.md) | 全链路执行流程（含架构图、状态流转） | 新人 Onboarding |
| [ARCHITECTURE_FOR_RESUME.md](./ARCHITECTURE_FOR_RESUME.md) | 简历级深度剖析（Mermaid 图 + 代码片段 + 面试问答） | **面试准备** |

### ② 架构设计（3 篇，版本演进）

从 MVP 到当前 v2.2 的架构演进全记录。

| 文档 | 版本 | 状态 |
|------|------|------|
| [FeedLens_MVP.md](./架构演进/FeedLens_MVP.md) | MVP (06-20) | 📦 历史参考 |
| [FeedLens_v1.0.md](./架构演进/FeedLens_v1.0.md) | v2.0 (06-23) | ⚠️ 已废弃架构 |
| [FeedLens_v2.2.md](./架构演进/FeedLens_v2.2.md) | **v2.2.0 (06-25)** | ✅ 当前版本 |

### ③ 模块设计（7 篇）

每个核心模块的详细设计思路。

| 文档 | 模块 | 关键设计点 |
|------|------|-----------|
| [main_agent.md](./项目各模块的设计思路/main_agent.md) | 主 Agent | 8 节点 StateGraph、规则优先路由、ReAct 循环 |
| [collection_agent.md](./项目各模块的设计思路/collection_agent.md) | 采集 Agent | Pipeline/ReAct 双模式、向量预过滤、RSS+搜索补充 |
| [ranking_agent.md](./项目各模块的设计思路/ranking_agent.md) | 排序 Agent | 两阶段去重、四因子排序、冷启动/偏好动态切换 |
| [briefing_agent.md](./项目各模块的设计思路/briefing_agent.md) | 简报 Agent | 结构化 JSON、代码层质量评分、自动重试 |
| [push_server.md](./项目各模块的设计思路/push_server.md) | 推送服务 | FastMCP stdio、JSONL 通知队列 |
| [state.md](./项目各模块的设计思路/state.md) | 共享状态 | 39 字段 TypedDict、字段分类与数据流 |
| [tool_registry.md](./项目各模块的设计思路/tool_registry.md) | 工具系统 | 统一注册/Schema 管理/阶段隔离/分发执行 |

### ④ 架构图

可视化架构资源。

```
Architecture/
├── FeedLens_Architecture.drawio    # 整体架构图（可编辑）
└── FeedLens_Architecture.png       # 整体架构图（导出）
```

### ⑤ 面试准备（核心）

专为面试场景准备的深度技术文档。

| 文档 | 内容 | 亮点 |
|------|------|------|
| [ARCHITECTURE_FOR_RESUME.md](./ARCHITECTURE_FOR_RESUME.md) | 系统顶层架构、数据模型、关键设计决策 | Mermaid 图 + 代码片段 |
| [FeedLens_项目总结.md](./FeedLens_项目总结.md) | 一句话描述、差异化对比、技术栈、优化历程 | 面试开场 3 分钟介绍 |

**面试高频问题速查**：

| 问题 | 参考文档 |
|------|---------|
| "为什么选择 LangGraph 而不是 LangChain Agent？" | [ADR-001](./技术决策记录/ADR-001-Agent编排框架选型.md) |
| "去重策略为什么用向量+LLM两阶段？" | [ADR-004](./技术决策记录/ADR-004-向量去重策略.md) + [ranking_agent.md](./项目各模块的设计思路/ranking_agent.md) |
| "冷启动和偏好模式怎么切换？" | [ADR-005](./技术决策记录/ADR-005-排序权重动态切换.md) + [ranking_agent.md](./项目各模块的设计思路/ranking_agent.md) |
| "为什么路由用规则优先而不是全 LLM？" | [FeedLens_v2.2.md](./架构演进/FeedLens_v2.2.md) §3.2 + [main_agent.md](./项目各模块的设计思路/main_agent.md) |
| "为什么用 bge-small-zh-v1.5 而不是 OpenAI Embedding？" | [ADR-006](./技术决策记录/ADR-006-Embedding模型选型.md) |
| "为什么用 SQLite + ChromaDB 混合存储？" | [ADR-007](./技术决策记录/ADR-007-数据存储选型.md) |
| "简报质量检查为什么不用 LLM 自评？" | [briefing_agent.md](./项目各模块的设计思路/briefing_agent.md) + [ADR-008](./技术决策记录/ADR-008-简报输出格式.md) |
| "用户反馈怎么影响排序？" | [ADR-009](./技术决策记录/ADR-009-用户反馈机制.md) + [ranking_agent.md](./项目各模块的设计思路/ranking_agent.md) |
| "单次执行从 8 分钟优化到 2 分钟做了什么？" | [FeedLens_项目总结.md](./FeedLens_项目总结.md) §六 + [Change/01_性能优化/](./Change/01_性能优化/) |

### ⑥ 技术决策记录（14 篇，ADR）

13 个独立 ADR + 1 篇汇总，记录每个关键技术选型的上下文、方案对比、最终决策。

| ADR | 决策主题 | 状态 |
|-----|---------|------|
| [ADR-001](./技术决策记录/ADR-001-Agent编排框架选型.md) | Agent 编排框架：LangGraph StateGraph | ✅ 已采纳 |
| [ADR-002](./技术决策记录/ADR-002-多Agent自主规划架构.md) | 多 Agent 自主规划 vs 单 Agent 线性 | ✅ 已采纳 |
| [ADR-003](./技术决策记录/ADR-003-MCP传输模式选型.md) | MCP 传输模式：Push stdio / Search SSE | ✅ 已采纳 |
| [ADR-004](./技术决策记录/ADR-004-向量去重策略.md) | 向量去重：0.88 阈值 + 模糊区间批量 LLM | ✅ 已采纳 |
| [ADR-005](./技术决策记录/ADR-005-排序权重动态切换.md) | 排序权重：冷启动/偏好动态切换 | ✅ 已采纳 |
| [ADR-006](./技术决策记录/ADR-006-Embedding模型选型.md) | Embedding：本地 bge-small-zh-v1.5 | ✅ 已采纳 |
| [ADR-007](./技术决策记录/ADR-007-数据存储选型.md) | 数据存储：SQLite + ChromaDB | ✅ 已采纳 |
| [ADR-008](./技术决策记录/ADR-008-简报输出格式.md) | 简报格式：结构化 JSON + Markdown | ✅ 已采纳 |
| [ADR-009](./技术决策记录/ADR-009-用户反馈机制.md) | 反馈机制：三级反馈 + EMA 更新 | ✅ 已采纳 |
| [ADR-010](./技术决策记录/ADR-010-部署方案.md) | 部署方案：MVP 纯本地 Python | ✅ 已采纳 |
| [ADR-011](./技术决策记录/ADR-011-记忆接入Planner.md) | 记忆接入：Planner 经验驱动 | ✅ 已实现 |
| [ADR-012](./技术决策记录/ADR-012-执行栅栏.md) | 执行栅栏：per-user threading.Lock | ✅ 已采纳 |
| [ADR-013](./技术决策记录/ADR-013-模型回退链.md) | 模型回退：LLMRouter 顺序 try | ✅ 已采纳 |
| [技术决策汇总.md](./技术决策记录/技术决策汇总.md) | 13 项 ADR 总览表 | 📋 汇总 |

### ⑦ 变更记录（20 篇）

系统化记录所有变更、优化、Bug 修复。

| 文档/目录 | 内容 |
|-----------|------|
| [Change/README.md](./Change/README.md) | 变更目录导航与阅读顺序 |
| [Change/changelog.md](./Change/changelog.md) | 版本变更日志（v2.0 → v2.2.0） |
| [Change/bugfix.md](./Change/bugfix.md) | Bug 修复记录 |
| [Change/01_性能优化/](./Change/01_性能优化/) | 10 项性能优化 detail（00 规划 + 01~10 实施） |
| [Change/02_架构演进规划/](./Change/02_架构演进规划/) | 借鉴 OpenClaw 的架构增强方案 |

### ⑧ 历史归档（34 篇）

MVP 开发阶段的原始文档，已完成历史使命。

| 目录/文件 | 说明 |
|-----------|------|
| [Archives/MVP_API.md](./Archives/MVP_API.md) | MVP 阶段 API 接口文档 |
| [Archives/MVP_TODO.md](./Archives/MVP_TODO.md) | MVP 开发 TODO（已全部完成） |
| [Archives/Roadmap_MVP.md](./Archives/Roadmap_MVP.md) | MVP 开发路线图 |
| [Archives/OpenClaw_Technical Architecture.md](./Archives/OpenClaw_Technical%20Architecture.md) | OpenClaw 参考架构分析 |
| [Archives/MVP_originals/](./Archives/MVP_originals/) | 29 篇原始设计过程文档 |

---

## 二、项目版本演进速览

```
MVP (06-20)          v2.0 (06-22)          v2.2 (06-25)
    │                     │                     │
    ├─ 多Agent架构        ├─ LLM全动态路由       ├─ 规则优先路由
    ├─ Planner编排        ├─ 子Agent ReAct化     ├─ 向量预过滤
    ├─ 多因子排序         ├─ 单Agent线性DAG      ├─ 批量LLM裁决
    └─ Streamlit UI       └─ 首次交付             ├─ Pipeline/ReAct双模式
                                                   ├─ 质量检查代码化
                                                   ├─ 执行栅栏
                                                   ├─ Hook系统
                                                   ├─ 记忆注入
                                                   ├─ 模型回退链
                                                   └─ 执行从8分钟→2分钟
```

---

## 三、关键数字速记

| 指标 | 数值 |
|------|------|
| Agent 数量 | 1 主 Agent + 3 子 Agent |
| LangGraph 节点数 | 8 |
| 工具数量 | 14（6 个 phase 分组） |
| SQLite 表数 | 11 |
| ChromaDB Collection 数 | 3 |
| State 字段数 | 39 |
| ReAct 循环上限 | 3（可配置 max_react_cycles） |
| 去重向量阈值 | 0.88（硬判重）/ 0.70~0.88（LLM 裁决） |
| 预过滤阈值 | 0.92 |
| 简报质量达标线 | ≥ 0.7 |
| 简报重试上限 | 2 次 |
| 排序因子数 | 4（similarity / recency / preference / importance） |
| 冷启动反馈阈值 | < 3 条 |
| 偏好 EMA α | 0.3 |
| 单次执行耗时 | ≤ 2 分钟（v2.2） |
| LLM API 调用次数 | ≤ 6-8 次（v2.2） |
| 性能优化项数 | 10 |
| ADR 数量 | 13 |

---

## 四、文档维护约定

- **当前版本文档**：`架构演进/FeedLens_v2.2.md` 是唯一权威架构文档
- **模块设计文档**：`项目各模块的设计思路/` 下的 7 篇应与代码保持一致
- **变更记录**：每次重要变更在 `Change/changelog.md` 追加条目，detail 放 `Change/01_性能优化/`
- **版本标注**：所有文档应在标题下方标注版本号和日期
