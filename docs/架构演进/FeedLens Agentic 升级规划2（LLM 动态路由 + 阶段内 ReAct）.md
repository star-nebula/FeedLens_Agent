# FeedLens Agentic 升级规划（方案二：LLM 动态路由 + 阶段内 ReAct）

> 创建时间：2026-06-22
> 目标：将当前「LLM 辅助编排的智能流水线」改造为「层级自主 Agent」，增强简历展示价值

---

## 一、当前 vs 目标对比

| 维度 | 当前（Pipeline） | 目标（Agentic） |
|------|-----------------|-----------------|
| **主流程路由** | 6/8 边 `add_edge` 硬编码 | 全部改为 `add_conditional_edges`，LLM 决策 |
| **ReAct 循环控制** | 硬编码 `cycle < 3` + `needs_retry` | LLM 自主判断是否继续 |
| **Planner 自主权** | 只能选 3 个子 Agent 的顺序 | LLM 可跳过/重试/自定义策略 |
| **子 Agent 内部** | 全部固定 DAG | 阶段内 LLM 自主调用工具 |
| **工具调用** | 代码硬编码调函数 | LLM function calling 自主选择 |
| **错误恢复** | `_fallback_plan` 写死 | LLM 分析错误、自主调整 |
| **结束判断** | 硬编码走向 `update_memory` | LLM 决定：推送 / 放弃 / 重做 |

---

## 二、改造分层架构

```
┌──────────────────────────────────────────────────────┐
│  Layer 0: 主 Agent 路由层（LLM 动态路由）              │
│  understand_intent → [LLM路由] → planner → [LLM路由]  │
│  → invoke_sub_agent → [LLM路由] → push/retry/abort    │
│  → update_memory → END                                │
├──────────────────────────────────────────────────────┤
│  Layer 1: 子 Agent 执行层（阶段内 ReAct）              │
│  每个子 Agent = 一个 ReAct Agent                      │
│  LLM Thought → function_call → Observation → ...      │
├──────────────────────────────────────────────────────┤
│  Layer 2: 工具层（扁平化 function calling tools）      │
│  fetch_rss / search_web / enrich_metadata /            │
│  deduplicate / rank_items / generate_briefing /        │
│  quality_check / push_notification / db_read/write     │
└──────────────────────────────────────────────────────┘
```

---

## 三、详细改造步骤

### Phase 1: 工具层扁平化（tools/ 改造）

**目标**：将所有工具函数包装为标准 OpenAI function calling schema，让 LLM 能看到并自主选择。

**改动文件**：新建 `tools/tool_registry.py`

**内容**：每个工具 = `{name, description, parameters(JSON Schema), function}`

工具清单：
- `fetch_rss` - RSS 采集
- `search_web` - MCP 搜索补充
- `enrich_metadata` - LLM 元数据增强
- `normalize_items` - 字段标准化
- `deduplicate` - 向量去重
- `rank_items` - 多因子排序
- `generate_briefing` - 生成简报
- `quality_check` - 质量审查
- `push_notification` - 推送
- `finish_task` - 标记完成（让 LLM 能主动结束）

---

### Phase 2: State 扩展（agents/state.py）

**新增字段**：
```python
router_decision: dict[str, Any]      # router_node LLM 决策: {next_node, reason}
router_history: list[dict[str, Any]] # 路由决策历史（用于避免死循环）
agentic_turn_count: int              # 当前 Agentic 循环计数
```

---

### Phase 3: 子 Agent ReAct 化

**三个子 Agent 全部从 `StateGraph` 改为 ReAct 循环**：

- `agents/collection_agent.py` → ReAct 采集 Agent
- `agents/ranking_agent.py` → ReAct 排序 Agent
- `agents/briefing_agent.py` → ReAct 简报 Agent

**ReAct 循环模式**（以 Collection Agent 为例）：

```
System Prompt: "你是 FeedLens 的采集 Agent..."

Loop (max 5 turns):
  1. LLM 思考当前状态 → 决定调用哪个工具
  2. 执行工具调用 → 将结果追加到 messages
  3. LLM 判断是否完成 → 完成则调用 finish_collection 工具

工具列表：
  - fetch_rss(sources, max_workers)
  - search_web(query, max_results)
  - enrich_metadata(items, batch_size)
  - normalize_items(items)
  - finish_collection(summary)
```

---

### Phase 4: 主 Agent 路由层改造（agents/main_agent.py）

**改动 1：新增 `router_node`**

替换以下硬编码边为 LLM 决策：
- `understand_intent → planner` → `understand_intent → router_node`
- `planner → invoke_sub_agent` → `planner → router_node`
- `invoke_sub_agent → observe_results` → `invoke_sub_agent → router_node`
- `coordinator_reflect → push_notification` → `coordinator_reflect → router_node`

**Router System Prompt 设计**：
```
你是 FeedLens 的自主路由决策者。根据当前状态，决定下一步应该去哪个节点。

可跳转节点：
- "planner": 需要重新编排子 Agent 执行计划
- "invoke_sub_agent": 执行 planner 编排的子 Agent
- "push_notification": 简报已就绪，执行推送
- "update_memory": 记录执行日志并结束
- "abort": 放弃本次执行

当前状态：{state_summary}

请只返回 JSON：{"next_node": "...", "reason": "..."}
```

**改动 2：替换所有 `add_edge` 为 `add_conditional_edges`**

**改动 3：移除硬编码的 `should_continue_react` / `should_push_now`**（由 router_node 统一决策）

**改动 4：保留 `observe_results` / `coordinator_reflect` 作为状态更新节点**（计算质量指标供 router 参考，不再做路由）

---

### Phase 5: invoke_sub_agent 适配

从 `builder().invoke()` 改为直接调用 ReAct 函数。

---

### Phase 6: pipeline_runner + 测试适配

`utils/pipeline_runner.py` 调用方式不变，适配新路由。
`scripts/test_main_agent.py` 测试用例适配。

---

## 四、文件改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| **新建** `tools/tool_registry.py` | 新建 | 工具 schema 定义 + 执行分发 |
| **修改** `agents/main_agent.py` | 重写路由 | 新增 router_node，替换所有 add_edge |
| **修改** `agents/collection_agent.py` | 重写 | StateGraph → ReAct 循环 |
| **修改** `agents/ranking_agent.py` | 重写 | StateGraph → ReAct 循环 |
| **修改** `agents/briefing_agent.py` | 重写 | StateGraph → ReAct 循环 |
| **修改** `agents/state.py` | 扩展 | 新增路由控制字段 |
| **修改** `utils/pipeline_runner.py` | 适配 | 调用方式不变 |
| **修改** `scripts/test_main_agent.py` | 适配 | 测试用例适配 |
| **修改** `docs/changelog.md` | 追加 | 记录改造 |

---

## 五、验证方案

### 5.1 单元测试

| 测试项 | 验证内容 |
|--------|---------|
| `test_tool_registry.py` | 所有工具 schema 格式正确，dispatch 正确调用 |
| `test_collection_agent_react.py` | ReAct 采集：模拟 LLM 返回 tool_calls，验证工具执行 |
| `test_ranking_agent_react.py` | ReAct 排序：同上 |
| `test_briefing_agent_react.py` | ReAct 简报：同上 |
| `test_router.py` | LLM 路由：各种状态下输出正确 next_node |

### 5.2 集成测试

| 测试项 | 验证内容 |
|--------|---------|
| `test_main_agent.py` (更新) | 完整管线：采集→排序→简报→推送 |
| 边界情况 | 采集为0→abort；简报质量低→重做 |

### 5.3 真机验证

```bash
python utils/pipeline_runner.py --trigger manual
```

---

## 六、风险与回退

| 风险 | 缓解措施 |
|------|---------|
| LLM 路由死循环 | `router_history` 检测重复 + max_turns=10 硬兜底 |
| ReAct 不收敛 | 每个子 Agent max 5 turns + 超时 fallback |
| function calling 成本增加 | 保留 `_fallback_plan` 降级路径 |
| 改造期间主流程不可用 | 分支开发，测试通过再合并 |

---

## 七、执行顺序

```
Phase 1: 工具层扁平化 (tools/tool_registry.py)          ← 无依赖，先做
Phase 2: State 扩展 (agents/state.py)                   ← 无依赖
Phase 3: 子 Agent ReAct 化 (collection/ranking/briefing) ← 依赖 Phase 1
Phase 4: 主 Agent 路由改造 (main_agent.py)               ← 依赖 Phase 2,3
Phase 5: pipeline_runner + 测试适配                      ← 依赖 Phase 4
Phase 6: 集成测试 + 真机验证                             ← 依赖 Phase 5
```

预计总工作量：**1-2 天**（Phase 1-2 半天，Phase 3 半天，Phase 4 半天，Phase 5-6 半天）
