# FeedLens 项目总结

> **版本**：v2.2.0 | **日期**：2026-06-25 | **状态**：✅ 已完成

---

## 一、项目一句话描述

基于 LangGraph + DeepSeek 的多 Agent 智能信息简报系统。主 Agent 通过 ReAct 循环自主编排三个子 Agent（采集 → 排序 → 简报），定时从 RSS 源采集新闻，经过去重、多因子排序、简报生成和质量审查后推送给用户，并通过用户反馈持续学习偏好。

---

## 二、核心差异化

| 维度 | 传统 RSS 阅读器 | FeedLens |
|------|----------------|----------|
| 信息获取 | 被动拉取 | 定时自主采集 + 搜索补充 |
| 信息过滤 | 按时间排序 | 向量去重 + 多因子偏好排序 |
| 个性化 | 关键词硬匹配 | 向量化偏好学习 + EMA 反馈闭环 |
| 输出形态 | 原始条目列表 | 结构化 JSON 简报 + Markdown 渲染 |
| 决策方式 | 硬编码流程 | **Planner 自主编排**，LLM 动态路由 |

---

## 三、技术栈

| 组件 | 选型 | 用途 |
|------|------|------|
| Agent 编排 | LangGraph StateGraph | 主 Agent + 子 Agent 状态图 |
| LLM | DeepSeek V4 Flash | 编排决策 + 简报生成 + 去重裁决 |
| Embedding | bge-small-zh-v1.5（本地） | 条目向量化 + 偏好向量 |
| 向量数据库 | ChromaDB | 条目历史 + 用户偏好 + 长期记忆 |
| 关系数据库 | SQLite（WAL 模式，11 张表） | 全量数据持久化 |
| 定时任务 | APScheduler | Cron 定时触发 |
| MCP 搜索 | FastMCP（SSE :8100） | 搜索补充采集 |
| 用户界面 | Streamlit | 简报展示 + 反馈 + 配置 |

---

## 四、系统架构

### 4.1 六层架构

```
展示层 (Streamlit) → 规划层 (主Agent) → 执行层 (子Agent) → 工具层 (13个工具) → 记忆层 (SQLite+ChromaDB) → 数据层
```

### 4.2 主 Agent 工作流（LangGraph StateGraph）

```
understand_intent → planner → router_node → invoke_sub_agent → router_node
       ↑              ↑           ↓                ↓                ↓
       └──────────────┴─── ReAct 循环 ────────────┘          observe_results
                                                                   ↓
                                                              router_node
                                                                   ↓
                                                          coordinator_reflect
                                                                   ↓
                                                          push_notification
                                                                   ↓
                                                          update_memory → END
```

**8 个节点，9 个节点间跳转由 router_node 决策**：
- `understand_intent`：解析用户 Goal，生成 goal_embedding
- `planner`：LLM 自主编排子 Agent 执行计划
- `router_node`：规则路由（正常流程） + LLM 路由（需要重新编排时）
- `invoke_sub_agent`：顺序执行 Collection → Ranking → Briefing
- `observe_results`：评估子 Agent 结果质量
- `coordinator_reflect`：综合质量审查（完整性 + 去重 + 追溯 + 矛盾）
- `push_notification`：MCP 推送简报
- `update_memory`：写入执行日志 + 更新 ChromaDB 偏好向量

**容错机制**：
- 连续 3 次相同路由 → 强制收敛
- agentic_turn_count ≥ 5（可配置）→ 强制结束
- 子 Agent 通过 `run_with_isolation` 隔离执行，单个失败不阻塞管线
- Planner JSON 解析三层降级：直接解析 → regex 清洗 → 逐字段提取

### 4.3 子 Agent 设计

| Agent | 模式 | 核心逻辑 |
|-------|------|---------|
| **Collection** | Pipeline（固定流水线） | fetch_rss → 向量预过滤 → search_web 补充 → normalize_items |
| **Ranking** | ReAct（LLM 决策） | deduplicate → rank_items（四因子加权）→ finish_task |
| **Briefing** | ReAct（代码层驱动） | generate_briefing → 自动质量评估 → 达标即完成，不达标重试 |

**Collection Agent** 默认使用 Pipeline 模式（`collection_mode: pipeline`），0 次 LLM 调用。仅在 `collection_mode: react` 时恢复 LLM 自主决策。

**Ranking Agent** 使用 ReAct 模式，LLM 自主决定调用 deduplicate → rank_items 的顺序和参数。

**Briefing Agent** 关键设计：移除 `quality_check` 工具暴露给 LLM，改为代码层自动调用 `brief_quality_check_node`。生成后立即评估，质量 ≥ 0.7 直接完成，否则自动重试（最多 2 次）。ReAct 思考 -100%。

### 4.4 共享状态（FeedLensState）

所有 Agent 通过 TypedDict 共享同一个 State，包含：
- 会话元信息（session_id, trigger_type, user_id）
- 用户 Goal（goal_text, structured_goal, goal_embedding）
- 编排控制（sub_agent_plan, react_cycle_count, router_decision）
- 子 Agent 结果（collected_items, ranked_items, briefing, brief_quality）
- 观察审查（observation_result, coordinator_observation）
- 记忆（execution_log, short_term_memory）
- 路由控制（router_history, agentic_turn_count, agent_status）

---

## 五、关键技术决策

### 5.1 去重策略：向量 + LLM 两阶段

```
余弦相似度 ≥ 0.88 → 直接判重（无 LLM）
余弦相似度 ≤ 0.70 → 直接保留
0.70 < 余弦相似度 < 0.88 → 收集所有待裁决 pair，一次性批量 LLM 裁决
```

超限保护：待裁决 pair 超过 20 对时，超限部分硬判为重复（`dedup_hard_threshold: 0.80`）。

### 5.2 排序策略：四因子加权 + 冷启动/偏好动态切换

**冷启动**（反馈 < 3 条）：similarity 0.40 + recency 0.25 + preference 0.10 + importance 0.25
**有反馈**（反馈 ≥ 3 条）：similarity 0.30 + recency 0.20 + **preference 0.40** + importance 0.10

偏好向量正负分离（v_like / v_dislike），通过 EMA（α=0.3）平滑更新。

### 5.3 路由策略：规则优先 + LLM 兜底

正常流程 7 个路由场景全部由规则覆盖（`_rule_based_router_decision`），0 次 LLM 调用。仅在 `needs_retry` 或 `overall_pass=false` 需要 Planner 重新编排时，才路由到 Planner 调用 LLM。节省 6 次 router LLM 调用。

### 5.4 模型回退链

`LLMRouter` 按顺序尝试多个 Provider，首个成功即返回。配置备用 Provider 后，主 LLM 不可用时自动切换。

---

## 六、性能优化历程

### 整体指标变化

| 指标 | 优化前（v2.0 初版） | 当前（v2.2.0） |
|------|---------------------|----------------|
| 单次执行耗时 | ~8分36秒 | ≤2分钟 |
| LLM API 调用次数 | ~35+次 | ≤6-8次 |
| API 浪费占比 | ~65% | ≤10% |
| 简报质量 | 0.746 | ≥0.7（保持） |

### 10 项关键优化

| 编号 | 优化项 | 效果 |
|------|--------|------|
| 01 | enrich_metadata 批量处理 + 可关闭 | 关闭时节省 13 次 API |
| 02 | observe 结果判断优化 | 修复误判，避免无效重跑 |
| 03 | briefing 质量检查与重试 | completeness 分母修正 |
| 04 | Planner/Router 规则化降级 | 正常流程节省 6 次 router LLM |
| 05 | collection pipeline 固定化 | 采集 LLM 调用 -100% |
| 06 | thinking_mode 关闭 + tool_choice | 修复 V4 function calling 不稳定 |
| 07 | 向量预过滤跨批次去重 | 进入 Ranking 条目 -70%+ |
| 08 | briefing 管线深度优化 | ReAct 思考 -100%，重试 3→2 |
| 09 | 去重算法批量 LLM 裁决 | HTTP 往返 -80~95% |
| 10 | 摘要清洗 + Planner 容错 + VS 单例 | 三层清洗 + 三层 JSON 解析 + 防数据丢失 |

### 核心设计原则

> **LLM 只做「创造」，不做「判断」** — 所有可规则化的判断逻辑（路由、预过滤、质量评估的 coherence 部分）全部由代码层硬编码处理。

---

## 七、13 个工具一览

| 工具 | 阶段 | 说明 |
|------|------|------|
| `fetch_rss` | Collection | 并行采集 RSS 源 |
| `search_web` | Collection | MCP 搜索补充 |
| `enrich_metadata` | Collection | LLM 元数据增强（默认关闭） |
| `normalize_items` | Collection | 字段标准化 |
| `deduplicate` | Ranking | 向量去重 + LLM 批量裁决 |
| `rank_items` | Ranking | 四因子加权排序 |
| `generate_briefing` | Briefing | 结构化 JSON 简报生成 |
| `quality_check` | Briefing（内部） | 三维质量审查（代码层调用） |
| `push_notification` | Main | MCP 推送简报 |
| `record_feedback` | Main | 记录用户反馈 + 更新偏好 |
| `read_memory` | Main | 读取历史记忆 |
| `write_memory` | Main | 写入决策经验 |
| `finish_task` | Common | 标记阶段完成 |

---

## 八、数据存储

### SQLite（11 张表）
`users`, `sources`, `raw_items`, `deduped_items`, `item_relations`, `briefs`, `briefing_items`, `feedback`, `execution_logs`, `run_logs`, `push_queue`

### ChromaDB（3 个集合）
- `feed_items`：条目向量（用于跨批次预过滤去重，cosine 距离度量）
- `user_preference`：用户正负偏好向量
- `domain_knowledge`：语义记忆种子数据

### 向量预过滤机制
Collection Agent 内部调用 `_prefilter_against_history()`，对每条新采集条目查询 ChromaDB feed_items，余弦相似度 ≥ 0.92 直接丢弃。纯标题编码（与写入端一致），不经过 LLM。

---

## 九、部署与运行

```bash
pip install -r requirements.txt
python scripts/init_db.py          # 初始化 SQLite
streamlit run app.py               # 启动 UI + APScheduler 后台
python -m mcp_servers.search_server  # MCP 搜索服务（可选）
```

**配置**：`config/config.yaml`，支持环境变量 `${DEEPSEEK_API_KEY}`。

**定时触发**：APScheduler 每日 06:00（可配）自动执行，支持手动触发和重大事件破例推送。

**执行栅栏**：`execution_fence.py` 防止定时/手动/破例推送并发执行。

---

## 十、项目版本演进

| 版本 | 日期 | 核心变化 |
|------|------|---------|
| MVP | 06-20 | 多 Agent 架构 + Planner 编排 + Streamlit UI |
| v2.0 | 06-22 | LLM 全动态路由 + 子 Agent ReAct 化 |
| v2.1 | 06-24 | 向量预过滤 + 简报管线深度优化（规划） |
| v2.2 | 06-25 | 去重链路修复 + 批量 LLM 裁决 + 摘要清洗 + Planner 容错 |

---

## 十一、已知限制

1. **单用户**：MVP 固定 user_id=1，无多用户认证
2. **纯本地**：无 Docker 容器化，无云部署
3. **无并行**：子 Agent 顺序执行（Collection → Ranking → Briefing）
4. **RSS 源有限**：默认 4 个源，需手动添加
5. **搜索依赖 MCP**：需单独启动 search_server
6. **简报风格单一**：无风格切换，无跨类别配额
