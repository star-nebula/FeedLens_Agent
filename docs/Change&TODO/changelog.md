# FeedLens Agentic 升级 Changelog

## v2.1.0 — 向量预过滤跨批次去重（2026-06-23 规划中）

- 新增优化规划文档 `docs/Change&TODO/优化规划_向量预过滤跨批次去重.md`
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

### 2.1 enrich_metadata 批量处理优化

**改动文件**：`agents/collection_agent.py`, `tools/tool_registry.py`, `tools/fc_tools.py`, `config/config.yaml`

**本质**：将元数据增强从「逐条 LLM 调用」改为「批量处理 + 可关闭」模式。原来每条 RSS 条目都单独调一次 LLM 生成 category/keywords/importance，现在支持批量和开关控制。

**改动要点**：
- `config.yaml` 新增 `enrich_metadata` 段：`enabled`（开关）、`batch_size`（批量大小）、`max_items`（上限）
- `enrich_metadata` 工具支持批量输入，单次调用处理多条
- 关闭时（`enabled: false`）跳过 LLM 调用，直接返回默认元数据（category="其他", keywords="", importance=0.5）
- 所有消费点（简报分类、排序权重、偏好学习）均有默认值兜底，关闭不影响系统稳定性

### 2.2 observe_results 判断逻辑优化（避免不必要重跑）

**改动文件**：`agents/main_agent.py`, `agents/ranking_agent.py`, `config/config.yaml`

**本质**：把 observe 信号从「排序有问题，重来」修正为「窗口太窄，放宽就行」，让 LLM planner 做对决策的概率大幅提高。

**根因**：采集 62 条 → 预筛 7 天 → 仅剩 1 条 → `top_score=0.25 < 0.3` → `ranking_ok=False` → `needs_retry=True` → 触发完整三板斧重跑。问题不在排序算法，而在预筛窗口过窄丢掉了太多条目。

**改动要点**：
- `_default_observe_evaluate` 新增 `prescreen_too_strict` 检测：采集充足但排序后条目极少时，强制 `ranking_ok=True`，`suggested_action="expand_threshold"`，避免误判为排序失败
- `ranking_agent.py` 预筛窗口从硬编码 168h → 读 `config.yaml` 的 `ranking.prescreen_hours`（默认 72h）
- `main_agent.py` `max_turns` 从硬编码 8 → 读 `config.yaml` 的 `agents.max_turns`（默认 5）
- `config.yaml` 新增 `agents.max_turns: 5` 和 `ranking.prescreen_hours: 72`

### 2.3 简报管线耗时统计

**改动文件**：`utils/pipeline_runner.py`, `agents/briefing_agent.py`, `agents/main_agent.py`

**本质**：为简报获取全链路添加三层耗时计时，让每次运行的性能瓶颈一目了然。之前没有任何计时，用户无法感知管线跑了多久、哪个环节最慢。

**改动要点**：

- **`utils/pipeline_runner.py` — 整体管线总耗时**
  - `agent.invoke()` 前后包裹 `time.perf_counter()` 计时
  - 日志输出：`[pipeline] ⏱️ 管线总耗时: 87.32s (1.5min)`
  - 返回值新增 `elapsed_seconds` 字段

- **`agents/briefing_agent.py` — 简报 Agent 细粒度计时（改动最大）**
  - Agent 整体计时：从 `run_briefing_agent()` 入口到所有 return 出口的完整耗时
  - ReAct 每轮计时：每轮 LLM 调用耗时 + 本轮总耗时（含所有工具执行）
  - 各工具调用计时：`generate_briefing` / `quality_check` / `finish_task` 各自独立耗时
  - 返回值新增 `briefing_timing` 结构化数据：`{llm_calls: [{turn, elapsed}, ...], tool_calls: [{turn, tool, elapsed}, ...]}`
  - 日志示例：
    ```
    [briefing_react] 第 1 轮思考...
    [briefing_react]   └─ LLM 调用耗时: 3.21s
    [briefing_react]   └─ 工具 generate_briefing 耗时: 12.35s
    [briefing_react] 第 1 轮完成，耗时: 15.56s
    [briefing_react] ⏱️ 简报 Agent 总耗时: 24.90s, ReAct 轮数: 3
    ```

- **`agents/main_agent.py` — 各子 Agent 耗时**
  - `invoke_sub_agent_node` 中为 Collection / Ranking / Briefing 三个子 Agent 各自计时
  - 日志示例：`[invoke_sub_agent] Briefing 完成, 耗时=24.90s`
  - 返回值新增 `agent_timing` 字段：`{"Collection": 15.2, "Ranking": 8.7, "Briefing": 24.9}`

**不影响项**：仅新增计时日志和返回值字段，不改变任何业务逻辑、流程控制或 API 调用。

### 2.4 Briefing Agent 质量检查与重试策略优化

**改动文件**：`agents/briefing_agent.py`

**本质**：修复 completeness 评分分母不合理导致的无效重试，并在代码层加入 generate_briefing 调用次数硬限制。原来 completeness 分母为全部 ranked_items（可能 60+），即使简报完美覆盖前 10 条也只能得 0.16，导致总分被压低至 0.7 以下，触发无意义的反复重试。

**核心问题**：
- completeness 分母取 `len(ranked_items)`，但简报最多展示 10 条（`MAX_ITEMS_PER_BRIEFING=10`），当 ranked=62 时 `completeness=10/62≈0.16`
- 重试无法提升 completeness（ranked_items 不变），也无法保证 LLM 给更高 relevance，形成无效重试循环
- LLM 可能不遵守 prompt 中的"最多重试 2 次"约束，代码层缺少 generate_briefing 独立计数器

**改动要点**：

- **completeness 分母修正（`brief_quality_check_node`，第 393-395 行）**
  ```python
  # 改前
  completeness = min(1.0, total_items_in_brief / max(1, len(ranked_items)))
  # 改后
  effective_max = min(len(ranked_items), 10)  # 简报最多展示 10 条
  completeness = min(1.0, total_items_in_brief / max(1, effective_max))
  ```
  效果：ranked=62, 简报覆盖 10 条 → completeness 从 0.16 → 1.0，score 从 0.67 → 0.92

- **generate_count 硬限制（`run_briefing_agent`，第 522、583、615-625 行）**
  - 循环开始前初始化 `generate_count = 0`
  - 每次调用 `generate_briefing` 时 `generate_count += 1`
  - 当 `generate_count >= 3` 时，代码层强制返回当前结果，不再等待 LLM 决策
  - 覆盖所有出口（finish_task 正常结束、超过 max_turns 兜底）

**不改的部分**：
- 质量阈值 0.7 保持不变（方案 A 修复 completeness 后正常场景可达标）
- `BRIEFING_SYSTEM_PROMPT` 不变（已包含 LLM 层面重试约束，代码层兜底即可）
- `_llm_assess_quality()` 不变（relevance 评分逻辑本身合理）
- `generate_briefing_node()` 不变（简报生成逻辑正确）

**验证场景**：

| 场景 | 改前 completeness | 改后 completeness | 改前 score | 改后 score |
|------|------------------|------------------|-----------|-----------|
| ranked=62, 简报覆盖 10 条 | 10/62≈0.16 | 10/10=1.0 | 0.67 ❌ | 0.92 ✅ |
| ranked=3, 简报覆盖 3 条 | 3/3=1.0 | min(3,10)=3, 3/3=1.0 | 不变 | 不变 |
| ranked=0（空） | 0 | 0 | 不变 | 不变 |

### 2.5 Planner/Router 规则化降级

**改动文件**：`agents/main_agent.py`, `scripts/test_router.py`

**本质**：将 router 从「每次都调 LLM 做路由决策」改为「规则优先，LLM 兜底」。正常流程中 90% 的路由决策是确定性的（plan 非空→执行、执行完→观察、观察 OK→审查、审查通过→推送、推送完→记忆），只有 `needs_retry=true` 或 `overall_pass=false` 需要 planner 重新编排时才路由到 planner（planner 内部会调 LLM）。

**改动前**：`router_node()` 每次调用都调 LLM（max_tokens=512），一次简报生成调用约 6 次 router LLM。

**改动后**：router 优先走规则判断，规则覆盖的场景直接返回，不再调 LLM。正常流程节省 5 次 router LLM 调用（仅 needs_retry 场景仍需 planner 调 LLM 重新编排 sub_agent_plan）。

**改动要点**：

- **`_fallback_router_decision()` → `_rule_based_router_decision()`**（第 471-522 行）
  - 返回类型从 JSON 字符串改为 `dict | None`
  - 返回 `None` 表示规则无法覆盖，需走 LLM（needs_retry / overall_pass=false 场景）
  - 新增两个边界规则：
    - `needs_retry` 达上限 + 采集为 0 → `abort`（放弃执行）
    - `needs_retry` 达上限 + 有数据 → `update_memory`（强制收敛）
    - `overall_pass=false` 达上限 → `push_notification`（强制推送）
  - 规则覆盖场景：`invoke_sub_agent`、`observe_results`、`coordinator_reflect`、`push_notification`、`update_memory`、`abort`

- **`router_node()`**（第 580-587 行）
  - LLM 调用前先调用 `_rule_based_router_decision(state)`
  - 规则返回 dict → 直接使用，跳过 LLM
  - 规则返回 `None` → 路由到 `planner`（planner 内调 LLM 重新编排）

**不改的部分**：
- `planner_node()` 不变 — planner 仍然调 LLM 生成 sub_agent_plan（needs_retry 场景需要）
- `understand_intent_node` 不变 — 本来就不调 LLM 做路由（只做 state/DB 读取 + embedding）
- 死循环检测、硬兜底逻辑不变
- `ROUTER_SYSTEM_PROMPT` 保留（代码中已不再使用，但保留以便未来可能需要回退或参考）
- `_build_router_context()` 和 `_parse_router_response()` 保留（未来可能需要或用于调试）
- StateGraph 构建逻辑不变

**预估效果**：
| 场景 | 改前 router LLM 调用 | 改后 router LLM 调用 | 节省 |
|------|---------------------|---------------------|------|
| 正常流程（无重试） | 6 次 | 0 次 | 6 次 |
| 1 次 ReAct 重试 | ~8 次 | 0 次 | ~8 次 |
| 2 次 ReAct 重试 | ~10 次 | 0 次 | ~10 次 |

注：planner_node 在 needs_retry 场景仍然会调 LLM，这是必要的（需要 LLM 重新编排 sub_agent_plan），不属于 router 调用。

---

### 2.6 deepseek-v4-flash Thinking Mode 关闭 + tool_choice="required"（2026-06-23）

**改动文件**：`utils/llm_provider.py`, `agents/ranking_agent.py`, `agents/collection_agent.py`, `agents/briefing_agent.py`

**本质**：修复 deepseek-v4-flash 在长上下文场景下 function calling 不稳定的 bug。V4 系列默认开启 Thinking Mode（`thinking.type="enabled"`），该模式下 `tool_choice="required"` 会返回 HTTP 400，只能使用 `tool_choice="auto"`（默认）。当输入上下文较长（如 62 条数据，~14K tokens）时，模型倾向于回复纯文本确认而非调用工具，导致 Ranking Agent 连续 5 轮"思考但不调用工具"，浪费 135 秒 + 5 次 LLM API 调用，最终 ranked=0。

**问题链路**：
```
deepseek-v4-flash 默认 Thinking Mode=enabled
  → tool_choice="required" 不可用（400 错误）
  → 只能 tool_choice="auto"（模型自主决定）
  → 长上下文下模型选择回复纯文本而非调用工具
  → 纯文本重试策略追加 user 消息但未改变任何 LLM 调用参数
  → 连续 5 轮返回纯文本，最终超时退出
```

**改动要点**：

- **`utils/llm_provider.py` — `chat_with_tools()` 添加 `extra_body` + `tool_choice` 参数**（第 72-101 行）
  - 新增 `tool_choice` 参数，默认 `"required"`（强制调用工具）
  - 新增 `extra_body={"thinking": {"type": "disabled"}}` 关闭 V4 默认的思考模式
  - `tool_choice=None` 时不传该参数（回退到模型默认行为）
  - `tool_choice="auto"` 可显式覆盖为自主模式

- **三个 Agent 纯文本重试策略收紧**（`turn < max_turns-1` → `turn < 1`）
  - `agents/ranking_agent.py` 第 539 行：仅首次纯文本时重试 1 次
  - `agents/collection_agent.py` 第 243 行：同上
  - `agents/briefing_agent.py` 第 640 行：同上
  - 原因：`tool_choice="required"` 下极少出现纯文本返回，保留 1 次重试仅作为极端兜底

- **新增测试** `scripts/test_thinking_disabled.py`（8 项测试，全部通过）
  - 参数验证：`extra_body` 和 `tool_choice` 正确传入
  - `tool_choice` 覆盖：`auto` / `None` 行为正确
  - 三个 Agent 纯文本重试限为 1 次
  - **真实 API 验证**：基础 tool call 正常
  - **真实 API 验证**：长上下文（62 条模拟数据）连续 3 轮正确调用工具

**不影响项**：
- `chat()` 方法不变（不需要 tools 参数的调用不受影响）
- `LLMRouter.chat_with_tools()` 签名不变（通过 `**kwargs` 透传）
- 三个 Agent 的 ReAct 循环核心逻辑不变

**效果对比**：

| 维度 | 改前（V4 Thinking Mode） | 改后（Thinking disabled） |
|------|--------------------------|--------------------------|
| tool_choice="required" | HTTP 400 ❌ | 正常 ✅ |
| 长上下文 function calling | 不稳定（5 轮纯文本） | 稳定（连续 3 轮正常调用） |
| 纯文本浪费 | 最多 5 轮 | 最多 1 轮 |
| 思考链内容 | 返回（增加 token 消耗） | 不返回 |

**测试结果**（`scripts/test_thinking_disabled.py`）：
- 8/8 全部通过（含 2 项真实 API 测试）
- 真实 API 长上下文测试：第 1 轮 deduplicate → 第 2 轮 rank_items → 第 3 轮 finish_task ✅

---

### 2.7 expand_threshold 在 ReAct 循环中漏传导致排序始终 0 条（2026-06-23）

> 详见 `docs/Change&TODO/bugfix.md#bug-001`

- 修复 `agents/ranking_agent.py`：ranking_react 循环中注入 `expand_threshold` 到 `rank_items` 工具调用
- 新增测试 `scripts/test_expand_threshold.py`（4/4 通过）
