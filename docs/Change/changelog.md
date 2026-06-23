# FeedLens Agentic 升级 Changelog

## v2.1.0 — 向量预过滤跨批次去重（2026-06-23 规划中）

- 新增优化规划文档 `docs/Change/01_性能优化/07_向量预过滤跨批次去重.md`
- 方案：在 Collection→Ranking 之间插入 ChromaDB 向量预过滤，拦截历史重复条目
- 预期效果：进入 Ranking Agent 的条目减少 70%+，总管线耗时缩短 60%
- 涉及文件：`agents/main_agent.py`, `models/vector_store.py`, `config/config.yaml`

## v2.0.0 — LLM 动态路由 + 阶段内 ReAct（2026-06-22）

### 概述

将 FeedLens 从「LLM 辅助编排的智能流水线」升级为「层级自主 Agent」，实现 LLM 全动态路由 + 子 Agent 阶段内 ReAct。

### Phase 1: 工具层扁平化 ✅

- 新建 `tools/tool_registry.py`
- 实现 `ToolRegistry` 类：`get_schemas()` / `get_schemas_for_phase()` / `dispatch()`
- 定义全部 13 个工具 schema（OpenAI function calling 格式）：
  `fetch_rss`, `search_web`, `enrich_metadata`, `normalize_items`, `deduplicate`,
  `rank_items`, `generate_briefing`, `quality_check`, `push_notification`,
  `record_feedback`, `read_memory`, `write_memory`, `finish_task`
- dispatch 容错：未知工具名抛 KeyError 含可用工具列表

### Phase 2: State 扩展 ✅

- `agents/state.py` 新增字段：
  - `router_decision: dict[str, Any]` — LLM 路由决策
  - `router_history: list[dict[str, Any]]` — 历史决策列表（防死循环）
  - `agentic_turn_count: int` — 主循环计数
  - `agent_status: dict[str, str]` — 子 Agent 执行状态追踪（额外增强）

### Phase 3a: collection_agent ReAct 化 ✅

- `agents/collection_agent.py` 重写为 ReAct 循环
- 实现 `run_collection_agent()`：LLM Thought → tool_call → Observation → ... → finish_task
- 工具列表：`fetch_rss`, `search_web`, `enrich_metadata`, `normalize_items`, `finish_task`
- max_turns=5 硬兜底，超时返回已有数据
- 兼容接口 `build_collection_agent()` → `_ReActAgentWrapper`
- 新增测试 `scripts/test_collection_agent_react.py`

### Phase 3b: ranking_agent ReAct 化 ✅

- `agents/ranking_agent.py` 重写为 ReAct 循环
- 实现 `run_ranking_agent()`：LLM 自主决策去重+排序流程
- 工具列表：`deduplicate`, `rank_items`, `finish_task`
- 偏好向量预加载优化：避免 rank_items_node 内部重复加载
- 兼容接口 `build_ranking_agent()` → `_ReActAgentWrapper`
- 新增测试 `scripts/test_ranking_agent_react.py`

### Phase 3c: briefing_agent ReAct 化 ✅

- `agents/briefing_agent.py` 重写为 ReAct 循环
- 实现 `run_briefing_agent()`：generate_briefing → quality_check → (迭代) → finish_task
- 工具列表：`generate_briefing`, `quality_check`, `finish_task`
- 系统提示词强化收敛规则：评分 >= 0.7 立即 finish_task
- 兼容接口 `build_briefing_agent()` → `_ReActAgentWrapper`
- 新增测试 `scripts/test_briefing_agent_react.py`

### Phase 4a/4b: 主 Agent 全动态路由 ✅

- `agents/main_agent.py` 新增：
  - `router_node()` — LLM 动态路由决策节点
  - `_parse_router_response()` — 三层 JSON 容错解析（直接→regex→兜底）
  - `_fallback_router_decision()` — LLM 空响应时的规则路由降级
  - `_build_router_context()` — 路由上下文构建
  - `_router_decide()` — 条件边函数
- 所有节点间跳转由 router_node（LLM）自主决策
- 防死循环：连续 3 次相同路由 → 强制 update_memory
- 硬兜底：agentic_turn_count >= 8 → 强制结束
- ROUTER_SYSTEM_PROMPT 覆盖全部 8 个可跳转节点
- 保留固定边：`understand_intent → planner`（入口）、`update_memory → END`（终点）
- 新增测试 `scripts/test_router.py`
- **真机验证修复**：
  - LLM 空响应处理：增加 `_fallback_router_decision()` 规则路由降级
  - Router max_tokens 从 256 提升到 512，避免 JSON 截断

### Phase 5: pipeline_runner 适配 ✅

- `utils/pipeline_runner.py` 无需改动（`build_main_agent()` 内部已适配 ReAct）
- 子 Agent 通过 `_ReActAgentWrapper` 兼容 `.invoke()` 接口

### Phase 6: 真机验证 ✅

- 执行 `python utils/pipeline_runner.py --trigger manual` 3 轮验证
- 验证通过项：
  - ✅ 管线正常启动，不被 execution_fence 阻塞
  - ✅ LLM 正确路由各阶段（invoke_sub_agent / observe_results / planner 重试 / update_memory）
  - ✅ 子 Agent ReAct 循环正确执行并退出（Collection 4轮/Ranking 3轮/Briefing 迭代完成）
  - ✅ 简报正常生成（质量 0.75-0.88）
  - ✅ 记忆正常写入（情节记忆 + 长期记忆 + 执行日志 + 偏好向量）
  - ✅ 容错机制生效（死循环检测、规则路由降级、max_turns 兜底）
- 验证中发现并修复的问题：
  1. Router LLM 返回空内容 → 增加 `_fallback_router_decision()` 规则路由降级
  2. Router JSON 被 max_tokens=256 截断 → 提升到 512
  3. Briefing 系统提示词收敛性不足 → 强化 finish_task 触发条件

### 不改动的文件

- `config/config.yaml` — 无新增配置
- `agents/feedback_agent.py` — 保持不变
- Streamlit UI (`ui/`) — 保持不变
- 无新增第三方依赖

### 回退策略

改动在 develop 分支进行，main 分支保持 MVP 可用状态。任何问题可回退到上一 commit。

---

## P0 性能与 API 消耗优化（2026-06-23）

> 实施细节见 [`01_性能优化/`](./01_性能优化/) 目录下的各子项文档。

| 编号 | 优化项 | 涉及文件 | 核心效果 | 详情 |
|------|--------|---------|---------|------|
| 2.1 | enrich_metadata 批量处理 | `collection_agent.py`, `tool_registry.py`, `config.yaml` | 可关闭，关闭时节省 13 次 API 调用 | [`01_enrich_metadata批量处理.md`](./01_性能优化/01_enrich_metadata批量处理.md) |
| 2.2 | observe 结果判断优化 | `main_agent.py`, `ranking_agent.py`, `config.yaml` | 修复误判排序失败，避免无效三板斧重跑 | [`02_observe结果判断优化.md`](./01_性能优化/02_observe结果判断优化.md) |
| 2.3 | 简报管线耗时统计 | `pipeline_runner.py`, `briefing_agent.py`, `main_agent.py` | 三层计时，性能瓶颈可见 | 无独立 detail（纯观测改动） |
| 2.4 | briefing 质量检查与重试 | `briefing_agent.py` | completeness 分母修正 + generate_count 硬限制 | [`03_briefing质量检查与重试.md`](./01_性能优化/03_briefing质量检查与重试.md) |
| 2.5 | Planner/Router 规则化降级 | `main_agent.py` | 正常流程节省 6 次 router LLM 调用 | [`04_Planner_Router规则化降级.md`](./01_性能优化/04_Planner_Router规则化降级.md) |
| 2.6 | thinking_mode 关闭 + tool_choice | `llm_provider.py`, 三个 Agent | 修复 V4 function calling 不稳定 | [`06_thinking_mode关闭与tool_choice.md`](./01_性能优化/06_thinking_mode关闭与tool_choice.md) |
| 2.7 | expand_threshold 漏传修复 | `ranking_agent.py` | 修复排序始终 0 条 | 详见 [`bugfix.md#bug-001`](./bugfix.md) |
| 2.8 | collection pipeline 固定化 | `collection_agent.py`, `config.yaml` | 采集 LLM 调用 -100%，耗时 -60~70% | [`05_collection_pipeline固定化.md`](./01_性能优化/05_collection_pipeline固定化.md) |

**整体指标变化**：

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| 单次执行耗时 | ~8分36秒 | ≤3分钟 |
| LLM API 调用次数 | ~35+次 | ≤12次 |
| API 浪费占比 | ~65% | ≤20% |
| 最终质量 | 0.746 | ≥0.7（保持） |
