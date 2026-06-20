# FeedLens MVP 开发路线图

> **日期**：2026-06-20 | **状态**：✅ 已完成 | **说明**：MVP版本，保留完整交付物与验收标准

***

## 总览

```
阶段一 ──→ 阶段二 ──→ 阶段三 ──→ 阶段四 ──→ 阶段五 ──→ 阶段六
  骨架+基础设施     信息采集      排序+去重+简报    推送+反馈+记忆    P1增强+UI     集成测试+交付
  数据模型          ReAct循环     ReAct循环         业务闭环         Streamlit     性能优化
```

| 阶段 | 目标                           | 复杂度 | 依赖  | 核心交付物数 |
| -- | ---------------------------- | --- | --- | ------ |
| 一  | 项目骨架 + 基础设施 + 数据模型           | 中   | 无   | 9      |
| 二  | 信息采集 Agent（RSS + 搜索 + ReAct） | 高   | 阶段一 | 7      |
| 三  | 排序 + 去重 + 简报生成（完整处理链）        | 高   | 阶段二 | 8      |
| 四  | 推送 + 反馈 + 记忆管理（业务闭环）         | 高   | 阶段三 | 8      |
| 五  | P1 增强 + Streamlit UI（用户交互）   | 中   | 阶段四 | 6      |
| 六  | 集成测试 + 优化 + 交付               | 中   | 阶段五 | 8      |

***

## 阶段一：项目骨架 + 基础设施 + 数据模型 ✅

### 目标

搭建完整的项目基础设施，定义数据模型，跑通 LangGraph 多 Agent 基础工作流骨架。

### 关键任务

- [x] 创建项目目录结构（config / models / nodes / tools / utils / agents / mcp\_servers / scheduler / ui）
- [x] 创建 `requirements.txt` 依赖管理文件
- [x] 创建 `.env` 模板 + `config.py` 配置加载机制
- [x] SQLite 表结构初始化脚本（11 张表 + WAL 模式）
- [x] ChromaDB 集合初始化（feed\_items / user\_preference / domain\_knowledge）
- [x] 主 Agent StateGraph 骨架（understand\_intent → planner → invoke → observe → planner(再思考) → reflect → push → update\_memory）
- [x] 5 个子 Agent StateGraph 骨架（CollectionAgent / RankingAgent / BriefingAgent / FeedbackAgent / MainAgent）
- [x] 子 Agent 调用接口实现（invoke\_sub\_agent\_node）
- [x] LLMProvider 抽象接口 + DeepSeekProvider 实现
- [x] bge-small-zh-v1.5 模型加载 + 推理验证

### 交付物与验收标准

| 交付物                   | 验收标准                                      |
| --------------------- | ----------------------------------------- |
| 项目目录结构                | 符合模块化设计，包含 agents / mcp\_servers / ui 子目录 |
| 依赖管理文件                | `pip install -r requirements.txt` 可安装成功   |
| 环境配置                  | `.env` 模板完整，`config.py` 正确读取配置            |
| SQLite 初始化脚本          | 全部 11 张表创建成功，WAL 模式开启                     |
| ChromaDB 集合初始化        | 3 个集合创建成功，embedding 函数配置正确                |
| 主 Agent StateGraph 骨架 | 节点定义完成，ReAct 循环边连接正确，空实现可跑通               |
| 子 Agent StateGraph 骨架 | 5 个子 Agent 各有独立 StateGraph，主 Agent 可调度    |
| LLMProvider 接口        | DeepSeekProvider 实现完成，预留 fallback 扩展点     |
| Embedding 模型加载        | 本地加载成功，推理速度 < 100ms/条                     |

### 验证环节

- **冒烟测试**：运行主 Agent 空流程，确认 StateGraph 各节点可依次执行
- **配置测试**：验证所有配置项可正确加载

***

## 阶段二：信息采集 Agent（完整 ReAct 循环） ✅

### 目标

实现采集 Agent 的完整工作流（RSS 采集 + 搜索补充 + 元数据提取 + ReAct 循环）。

### 关键任务

- [x] `fetch_rss` FC 工具实现（feedparser 并行采集）
- [x] `search_web` MCP Server (SSE :8100) 实现与部署
- [x] `enrich_metadata` FC 工具实现（LLM 提取 category/keywords/importance）
- [x] `normalize_items` FC 工具实现（字段标准化）
- [x] 采集 Agent ReAct 循环实现（Think→Act→Observe→Think）
- [x] SSE 连接断线降级逻辑
- [x] 采集结果写入 SQLite（raw\_items / feed\_items 表）

### 交付物与验收标准

| 交付物                                 | 验收标准                                |
| ----------------------------------- | ----------------------------------- |
| fetch\_rss                          | 并行采集 3+ 个 RSS 源，feedparser 解析成功     |
| search\_web MCP                     | 搜索 API 封装成功，SSE 流式返回，监听 :8100       |
| enrich\_metadata + normalize\_items | LLM 提取分类/关键词/重要性，字段统一格式化            |
| 采集 Agent ReAct 循环                   | 判断采集策略→执行→评估→决定补充搜索，自主判断            |
| SSE 断线降级                            | MCP SSE 断线→立即降级仅 RSS 模式，不阻塞流程       |
| 数据写入                                | 采集结果正确写入 raw\_items 和 feed\_items 表 |

### 验证环节

- **采集测试**：配置 3 个 RSS 源，验证采集→元数据提取→标准化完整流程
- **补充搜索测试**：当 RSS 结果不足时，验证自动触发搜索补充
- **降级测试**：断开 SSE 连接，验证仅 RSS 模式仍可正常运行

***

## 阶段三：排序 + 去重 + 简报生成（完整处理链） ✅

### 目标

实现排序 Agent 的完整功能（去重 + 偏好排序 + ReAct 循环），实现简报 Agent 的生成和审查功能。

### 关键任务

- [x] `deduplicate` FC 工具实现（0.88 阈值 + 模糊区间 LLM 裁决）
- [x] `rank_items` FC 工具实现（多因子加权 + 动态权重切换）
- [x] `vector_search` FC 工具实现（ChromaDB 偏好向量检索）
- [x] `db_read` FC 工具实现（SQLite 读取反馈历史）
- [x] 排序 Agent ReAct 循环实现（检索偏好→规划排序策略→去重+排序→评估→调参或Done）
- [x] 时间衰减预筛 + Min-Max 归一化 + feedback\_bias 逻辑
- [x] `generate_briefing` FC 工具实现（沿用 category/importance/keywords）
- [x] JSON → Markdown 渲染逻辑
- [x] `reflect` FC 工具实现（brief\_quality 评分 + 矛盾检查 + 重试判断）
- [x] 简报 Agent StateGraph 实现（generate → reflect → 重试或Done）
- [x] `calibrate_dedup.py` 校准脚本

### 交付物与验收标准

| 交付物                 | 验收标准                                       |
| ------------------- | ------------------------------------------ |
| deduplicate         | 0.88 阈值 + 模糊区间 LLM 裁决（上限 20 对）             |
| rank\_items         | 冷启动/有反馈两套权重动态切换                            |
| 排序 Agent ReAct      | 检索偏好→规划→去重+排序→评估→调参或Done                   |
| feedback\_bias      | 即时补偿偏好因子，EMA 更新后归零                         |
| generate\_briefing  | 沿用 enrich\_metadata 字段，items 按 category 分组 |
| JSON→Markdown       | 简报正确渲染，计数标注显示                              |
| reflect             | 四维评分 + 矛盾检测 + score<0.7 触发重试（最多2次）         |
| calibrate\_dedup.py | 标注样本→P/R/F1 曲线→最优阈值输出                      |
| 性能基准                | 单次排序+简报 < 30s                              |

### 验证环节

- **去重测试**：准备 20 条含重复的测试数据，验证去重准确率 > 90%
- **排序测试**：验证冷启动和有反馈两种权重模式切换正确
- **简报测试**：验证生成→审查→重试完整流程，质量评分 > 0.7

***

## 阶段四：推送 + 反馈 + 记忆管理（业务闭环） ✅

### 目标

完成业务闭环，实现推送、反馈、记忆管理功能。

### 关键任务

- [x] `push_notification` MCP Server (stdio) 实现与部署
- [x] APScheduler cron job 定时触发配置
- [x] 重大事件破例推送逻辑（score > 0.85 且时效 < 2h）
- [x] 反馈子 Agent 实现（feedback → update\_preference → vector\_add）
- [x] 偏好正负分离实现（v\_like / v\_dislike）
- [x] EMA 偏好更新逻辑
- [x] 偏好自动清理逻辑（权重 < 0.1）
- [x] 短期记忆管理（15 轮滑动窗口 + 超窗压缩）

### 交付物与验收标准

| 交付物                    | 验收标准                                |
| ---------------------- | ----------------------------------- |
| push\_notification MCP | 推送服务作为子进程运行，stdio 模式正常              |
| APScheduler            | cron job 每日定时触发主 Agent              |
| 破例推送                   | score > 0.85 且时效 < 2h 时立即推送         |
| 反馈子 Agent              | 异步处理反馈，偏好向量更新                       |
| 偏好正负分离                 | v\_like / v\_dislike 分别维护于 ChromaDB |
| EMA 更新                 | 偏好向量平滑更新，无剧烈波动                      |
| 偏好清理                   | 权重 < 0.1 自动清理                       |
| 短期记忆                   | 15 轮窗口 + 超窗压缩写入 ChromaDB            |

### 验证环节

- **推送测试**：验证定时推送和破例推送两种模式
- **反馈测试**：验证三级反馈（like/dislike/irrelevant）触发偏好更新
- **记忆测试**：验证偏好向量 EMA 更新和短期记忆管理

***

## 阶段五：P1 增强 + Streamlit UI（用户交互） ✅

### 目标

实现 P1 核心增强功能和用户界面，完成用户交互闭环。

### 关键任务

- [x] 主 Agent reflect 增强（三维度审查 + 矛盾检查）
- [x] planner 自主编排能力增强（支持跳过采集/跳过简报/空数据回退等场景）
- [x] 冷启动→偏好自适应切换完整链路（反馈数 >= 3 条）
- [x] Streamlit 基础页面（首页 + Goal 设置 + RSS 管理 + 简报阅读 + 反馈 + 日志）
- [x] 三级反馈 UI（like / dislike / irrelevant 按钮）
- [x] 执行仪表盘（成功率、耗时、去重率、反馈率等指标）

### 交付物与验收标准

| 交付物             | 验收标准                       |
| --------------- | -------------------------- |
| 主 Agent reflect | 三维度审查（完整性/去重遗漏/可追溯性）+ 矛盾检查 |
| planner 增强      | 支持跳过采集/跳过简报/空数据回退等场景       |
| 权重切换            | 反馈数 >= 3 条时自动切换为偏好优先       |
| Streamlit 页面    | 6 个页面功能完整，导航清晰             |
| 三级反馈 UI         | 三个按钮正确触发反馈子 Agent          |
| 执行仪表盘           | 显示关键指标，数据实时更新              |

### 验证环节

- **UI 测试**：验证所有页面功能可用，反馈按钮正常工作
- **planner 测试**：验证跳过采集、跳过简报、空数据回退等场景
- **端到端测试**：Goal 设置 → 主 Agent 执行 → 简报展示 → 反馈闭环

***

## 阶段六：集成测试 + 优化 + 交付 ✅

### 目标

端到端集成测试，性能优化，文档交付。

### 关键任务

- [x] 端到端集成测试（Goal设置 → 主Agent ReAct循环 → 子Agent调度 → 简报推送 → 反馈闭环）
- [x] structlog 结构化日志配置
- [x] execution\_logs + run\_logs 日志记录
- [x] 任务级错误隔离（单次失败不阻塞下次执行）
- [x] 30 天数据清理定时任务
- [x] 性能基准测试（单次 Agent 运行 < 60s）
- [x] MVP 设计文档定稿（docs/技术决策记录/）
- [x] README + 部署指南

### 交付物与验收标准

| 交付物    | 验收标准                                |
| ------ | ----------------------------------- |
| 端到端测试  | 从 Goal 到简报推送全流程跑通，含 ReAct 循环        |
| 结构化日志  | 全部节点日志结构化输出                         |
| 错误隔离   | 单次失败不阻塞下次执行                         |
| 数据清理   | 定期清理过期 raw\_items 和 execution\_logs |
| 性能基准   | 单次 Agent 运行 < 60s（采集 10 条 RSS 源）    |
| 设计文档   | ADR 技术决策记录完成（10项）                   |
| README | 包含环境配置、启动命令、依赖列表                    |

***

## 关键依赖链

```
阶段一 ──→ 阶段二 ──→ 阶段三 ──→ 阶段四 ──→ 阶段五 ──→ 阶段六
    │         │         │         │         │         │
    │         │         │         │         │         └── 端到端测试 + 文档交付
    │         │         │         │         └── P1增强 + Streamlit UI
    │         │         │         └── 推送 + 反馈 + 记忆管理
    │         │         └── 排序 + 去重 + 简报生成
    │         └── 信息采集 Agent ReAct
    └── 骨架 + 基础设施 + 数据模型
```

***

## 风险与缓解

| 风险              | 影响         | 缓解策略                          |
| --------------- | ---------- | ----------------------------- |
| ReAct 循环无限递归    | 主 Agent 卡死 | max\_react\_cycles=3 强制退出     |
| 模糊区间 LLM 裁决过多   | 去重步骤极慢     | max\_llm\_adjudications=20 上限 |
| ChromaDB 并发写入冲突 | 偏好数据丢失     | feedback\_workflow 串行化队列      |
| SSE 连接不稳定       | 搜索采集失败     | 断线降级仅 RSS 模式                  |
| 冷启动反馈数不足        | 偏好排序无法切换   | Goal 文本提取初始偏好向量作为种子           |
| 性能不达标           | 用户体验差      | 阶段三完成后进行初步性能测试                |

***

## 版本演进说明

> 以下记录基于实际 Git 提交历史整理

| 版本     | 日期               | 提交        | 主要变化                                                                                                                                                                     |
| ------ | ---------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| v0.1   | 2026-06-20 10:14 | `15825f4` | **Initial Commit：MVP 完整骨架**。一次性提交 132 个文件，涵盖项目基础设施、5 个 Agent StateGraph、MCP Servers、数据模型、向量存储、16 个测试脚本、Streamlit UI 页面、工具模块及 10 份 ADR 技术决策记录                             |
| v0.1.1 | 2026-06-20 10:17 | `3b2651e` | **文档迁移**。测试文档 `test_docs.md` 归入 `docs/` 目录，规范项目结构                                                                                                                        |
| v0.2   | 2026-06-20 10:45 | `fdbd283` | **Planner 质量评分修复**。重构 `briefing_agent.py` 和 `main_agent.py` 的 LLM-driven planner 逻辑；修复 `state.py` 状态定义；新增 `data/notifications.jsonl` 推送记录；完善 `sources_page.py` RSS 源管理功能 |
| v0.2.1 | 2026-06-20 15:40 | `52457a4` | **MVP 适配性修复**。修复简报字段（时间/来源）显示问题，提升简报数据完整性                                                                                                                                |
| v0.2.2 | 2026-06-20 15:57 | `1a34b7d` | **简报格式化修复**。统一简报时间格式化逻辑；统一分类语言标签，解决来源多样性导致的分类不一致问题                                                                                                                       |
| v0.3   | 2026-06-20 17:22 | `f045565` | **Planner 自主扩容 + 简报增强**。新增 `importance` 星级显示格式；实现 Planner 自主扩容策略（采集不足时自动触发补充搜索）；为简报条目添加原文链接；新增 `docs/TODO.md` 记录后续优化点                                                    |
| v0.3.1 | 2026-06-20 18:08 | `2f242f2` | **UI 重构与日志增强**。重构首页 `home_page.py` 的 pipeline 启动逻辑；新增日志双输出功能（控制台 + 文件）；完善 README 说明；更新推送通知记录                                                                             |

***

## 技术栈总结

| 组件        | 选型                      |
| --------- | ----------------------- |
| Agent编排   | LangGraph StateGraph    |
| LLM       | DeepSeek Chat           |
| Embedding | bge-small-zh-v1.5（本地）   |
| 向量数据库     | ChromaDB（3个Collections） |
| 关系数据库     | SQLite（WAL模式，11张表）      |
| MCP框架     | FastMCP                 |
| 搜索补充      | MCP SSE (:8100)         |
| 推送服务      | MCP stdio               |
| 定时任务      | APScheduler             |
| 用户界面      | Streamlit               |
| 日志        | structlog               |

