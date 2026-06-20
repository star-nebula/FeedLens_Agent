# FeedLens MVP 设计文档 v1.1 — 改进补充

>   版本  : v1.1 |   日期  : 2026-06-19
>   基础文档  : [FeedLens\_MVP\_Design\_Document.md](./FeedLens_MVP_Design_Document.md) (v1.0 / 修订稿)
>   说明  : 本文档记录开发过程中对原 MVP 设计的改进和补充，保留原文档不变。

***

## 一、算法改进

### 1.1 排序公式实现细化

原 MVP 文档定义的排序公式已完全实现，并在以下方面做了工程化改进：

| 改进项            | 原设计                                              | v1.1 实现                                       |
| -------------- | ------------------------------------------------ | --------------------------------------------- |
| similarity 因子  | `cosine(item_embedding, goal_embedding)`         | 内联 cosine 计算（无需依赖外部库）                         |
| recency 因子     | `exp(-Δt / 24h)`                                 | `math.exp(-hours_diff / 24.0)`                |
| importance 归一化 | LLM 1-5 分归一化至 0-1                                | `(raw_importance - 1.0) / 4.0`                |
| preference 因子  | `cosine(item_embedding, user_preference_vector)` | 冷启动阶段用 similarity 代理；有反馈阶段由 feedback\_bias 驱动 |
| 时间衰减预筛         | τ=24h 应用于排序权重                                    | 新增 Δt > 7 天直接丢弃的预筛步骤                          |
| 反馈偏差           | like+0.15, dislike-0.10, irrelevant-0.15         | `feedback_bias_map` 时序互补，EMA 更新后归零            |

### 1.2 EMA 参数修正

原设计 `ema_alpha = 0.3`（config.yaml 默认值），实现初始用了 `0.8`，已修正回 `0.3`。

### 1.3 偏好向量正负分离

`v_like` 和 `v_dislike` 分别存储于 ChromaDB `user_preference` 集合，支持独立的 EMA 更新。

***

## 二、架构改进

### 2.1 记忆管理独立模块

原设计中短期/长期/情节记忆分布在主 Agent 内部，v1.1 抽取为独立 `MemoryManager`（`utils/memory_manager.py`），包含：

- `ShortTermMemory` — 15 轮滑动窗口 (deque)
- `LongTermMemory` — ChromaDB domain\_knowledge 集合
- `EpisodicMemory` — SQLite execution\_logs 表
- `MemoryManager` — 三层整合 + LLM 压缩

### 2.2 错误隔离机制

新增 `utils/error_isolation.py`，提供：

- `task_error_isolation` 装饰器 — 任务失败不阻断流程
- `TaskErrorIsolator` 上下文管理器
- `isolate_agent_node` — LangGraph 节点专用隔离

### 2.3 调度器独立模块

推送调度从主流程中解耦为 `scheduler/push_scheduler.py`：

- `FeedLensScheduler` — APScheduler CronTrigger 定时 + 重大事件破例
- `is_breaking_news` / `detect_breaking_events` — 独立的检测逻辑
- `get_scheduler()` — 单例模式

### 2.4 简报 Agent JSON Schema 输出

LLM 生成简报使用 `BRIEFING_SCHEMA` 约束的结构化 JSON，再渲染为 Markdown。JSON→Markdown 渲染在 `_render_markdown()` 中完成。

***

## 三、配置调整

### 3.1 新增配置项

| 配置路径                       | 说明           | 默认值                           |
| -------------------------- | ------------ | ----------------------------- |
| `llm.deepseek.base_url`    | API 地址       | `https://api.deepseek.com/v1` |
| `llm.deepseek.temperature` | 生成温度         | `0.7`                         |
| `llm.deepseek.max_tokens`  | 最大 token     | `4096`                        |
| `embedding.model_name`     | Embedding 模型 | `BAAI/bge-small-zh-v1.5`      |
| `embedding.device`         | 推理设备         | `cpu`                         |
| `data.db_path`             | 数据库路径        | `data/feedlens.db`            |
| `data.chroma_path`         | ChromaDB 路径  | `data/chroma`                 |
| `memory.short_term_window` | 短期记忆窗口       | `15`                          |
| `data.min_items_for_brief` | 生成简报最低条目数    | `3`                           |

### 3.2 权重配置独立

冷启动和有反馈两套权重在 `config.yaml` 中以 `weights_cold` 和 `weights_warm` 分别定义，`rank_items_node` 根据 `feedback_count < 3` 动态选择。

***

## 四、开发约束验证

| 约束                      | 设计值                   | 实现验证                        |
| ----------------------- | --------------------- | --------------------------- |
| max\_react\_cycles      | 3                     | `should_continue_react` 硬上限 |
| max\_llm\_adjudications | 20                    | `deduplicate` 参数控制          |
| 简报质量阈值                  | < 0.7 重试，最多 2 次       | `should_retry_brief` 完整实现   |
| 冷启动阈值                   | 反馈 < 3 条              | `is_cold_start` 判断          |
| 偏好清理阈值                  | 权重 < 0.1              | `cleanup_preference_node`   |
| 重大事件阈值                  | score > 0.85 且时效 < 2h | `is_breaking_news` 完整实现     |

***

## 五、已知限制

1.   MCP SSE 搜索需先启动 search\_server   — 未实现自动拉起
2.   Streamlit 前端需手动启动   — 未打包为单一命令
3.   单用户模式   — MVP 仅支持 user\_id=1
4.   RSS 采集无缓存   — 每次全量拉取
5.   LLM 压缩在 memory\_manager 中   — 配置 key 路径已修正但尚未通过全链路验证

