让我先全面分析 Planner 和 Router 的当前实现，以及相关文档。
现在我已经完全理解了 Planner 和 Router 的实现。让我再确认一下规划文档中的相关内容：
现在我对所有相关信息都有了完整的理解。让我来分析并制定详细的实施规划。

---

## 2.4 P1 — Planner/Router 规则化降级 分析报告

### 一、当前架构回顾

当前主 Agent 的每次跳转都走 **LLM 动态路由**：

```
planner_node() → [每次调 LLM 编排]
    ↓
router_node() → [每次调 LLM 决策跳转]
    ↓
invoke_sub_agent → observe_results → coordinator_reflect → push_notification → update_memory
    ↑                        ↑                      ↑                      ↑                ↑
    └──── 每次执行后都回到 router_node 调 LLM 决策 ─────────────────────────────┘
```

一次完整的简报生成，`router_node` 会被调用约 6 次，每次都调 LLM（每次 `max_tokens=512`）。

### 二、已经存在的降级机制

| 机制 | 位置 | 触发条件 |
|------|------|----------|
| `_fallback_router_decision()` | `main_agent.py:471-515` | 仅在 LLM 返回空内容时触发（第 598-600 行） |
| 死循环检测 | `router_node():530-553` | 连续 3 次路由到同一节点 |
| 硬兜底 | `router_node():556-578` | `agentic_turn_count >= max_turns` |
| `_fallback_plan()` | `planner_node()` 异常处理 | LLM 调用失败时 |

**关键发现**：`_fallback_router_decision()` 已经包含了一套完整的规则路由逻辑（7 条规则，覆盖所有场景），但**目前仅作为 LLM 失败后的降级兜底**，正常流程从不走规则。

### 三、哪些场景可以用规则替代 LLM

分析正常流程中 router_node 被调用的场景：

| 轮次 | 当前状态 | 下一步 | 规则可判断？ |
|------|----------|--------|-------------|
| 1 | plan 非空 + executed=false | invoke_sub_agent | ✅ 100% 确定 |
| 2 | executed=true + observation 为空 | observe_results | ✅ 100% 确定 |
| 3 | observation 有结果 + needs_retry=false | coordinator_reflect | ✅ 100% 确定 |
| 4 | coordinator_obs + overall_pass=true | push_notification | ✅ 100% 确定 |
| 5 | push_status=sent | update_memory | ✅ 100% 确定 |
| 6 | 在 update_memory | END | ✅ 100% 确定 |

**结论**：正常流程中 router 的 6 次调用全部可以用规则判断，一次 LLM 都不需要。只有异常/边界场景（如 needs_retry=true 需要重新 planner）才需要 LLM。

### 四、方案 A：router 优先规则判断

**改动位置**：`router_node()` 第 580-605 行

**改动内容**：在调 LLM 之前，先调用 `_fallback_router_decision()` 做规则判断。规则能覆盖的场景直接返回，只有规则无法覆盖的场景（如 needs_retry=true、ambiguous 状态）才调 LLM。

**需要注意的问题**：
1. 当前 `_fallback_router_decision()` 返回的是 JSON 字符串（`'{"next_node": "..."}'`），需要统一返回格式
2. 规则路由仍需通过 `_router_decide` 条件边函数，所以需要返回标准 `{"next_node": "...", "reason": "..."}` 格式
3. 死循环检测和硬兜底仍然需要保留（在规则判断之前执行）

### 五、方案 C：合并 understand_intent

**分析**：`understand_intent_node` 做了三件事：
1. 识别 trigger_type（直接从 state 读，不需要 LLM）
2. 从 SQLite 读用户结构化偏好
3. 生成 goal_embedding（调 embedding 模型，非 LLM）

**结论**：`understand_intent_node` **本来就不调 LLM**！它只是从 state/DB 读数据 + 调 embedding 模型。所以方案 C 没有实际的 LLM 调用可节省。

### 六、方案 B：planner 缓存决策

**分析**：当前 planner 在以下场景被调用：
- 首次（react_cycle=0）：编排三板斧
- needs_retry=true 时：重新编排

**风险**：
- 缓存逻辑需要考虑 state 变化（collect/rank/brief 的结果变化），引入状态管理复杂度
- planner 的 params（如 expand_threshold）依赖当前 observe 结果，缓存可能导致用错参数
- 真机验证中 planner 被调用 3 次，如果缓存逻辑有 bug，可能导致错误的编排计划

**建议**：暂缓 B，先做 A。

### 七、最终实施计划

**只做方案 A**：router 优先规则判断

| 改什么 | 不改什么 |
|--------|----------|
| `_fallback_router_decision()` 返回格式改为 dict | `planner_node()` 不改 |
| `router_node()` 在 LLM 调用前先走规则判断 | `understand_intent_node()` 不改（本来就不调 LLM） |
| 规则覆盖的场景直接返回，跳过 LLM | 死循环检测逻辑不改 |
| 规则无法覆盖时（needs_retry 或 ambiguous）仍调 LLM | 硬兜底逻辑不改 |

### 八、详细改动

**改动 1**：`_fallback_router_decision()` 返回 dict 而非 JSON 字符串

当前：
```python
return '{"next_node": "invoke_sub_agent", "reason": "规则降级：执行计划中的子Agent"}'
```

改为返回标准 dict：
```python
return {"next_node": "invoke_sub_agent", "reason": "规则路由：执行计划中的子Agent"}
```

**改动 2**：`router_node()` 优先规则判断

在第 580 行（`context = _build_router_context(state)`）之前插入规则判断逻辑。规则能覆盖的场景直接返回，只有规则覆盖不到时才走 LLM。

需要给 `_fallback_router_decision` 增加一个返回值标记，区分"规则明确决策"和"规则无法决策需要 LLM"。考虑规则覆盖的场景：

- 当规则返回 `invoke_sub_agent`、`observe_results`、`coordinator_reflect`、`push_notification`、`update_memory` 时，这些都是确定性路由，跳过 LLM
- 当规则返回 `planner` 时（如 needs_retry），需要 LLM 来编排具体的 sub_agent_plan，所以**仍需调 LLM**

**改动 3**：`_fallback_router_decision()` 增加 `needs_retry` 分支处理

当前 `_fallback_router_decision` 在 needs_retry 时直接返回 `planner`，这是正确的——因为 planner 需要 LLM 来重新编排。但规则路由到 `planner` 后，planner 会调 LLM 生成新的 sub_agent_plan。这个逻辑保持不变。

### 九、不改的部分

| 不改 | 原因 |
|------|------|
| `planner_node()` | 需要 LLM 编排 sub_agent_plan + params，规则无法替代 |
| `understand_intent_node()` | 本来就不调 LLM，只做 state/DB 读取和 embedding |
| 死循环检测 | 安全兜底，必须在规则之前执行 |
| 硬兜底（max_turns） | 安全兜底，必须在规则之前执行 |
| `_fallback_plan()` | planner 的 LLM 失败降级，属于不同层级 |
| `_router_decide()` | 条件边函数，不调 LLM，不需要改 |
| `observe_results_node()` | 属于 2.2 已完成的优化，不在此范围 |
| StateGraph 构建 | 节点和边的拓扑不变 |

### 十、防 bug 分析

**场景 1：正常首次执行**
- 状态：plan=[Collection,Ranking,Briefing], executed=false
- 规则判断 → invoke_sub_agent ✅（不走 LLM）

**场景 2：执行完成后观察**
- 状态：executed=true, observation 为空
- 规则判断 → observe_results ✅（不走 LLM）

**场景 3：观察通过，进入审查**
- 状态：observation.needs_retry=false
- 规则判断 → coordinator_reflect ✅（不走 LLM）

**场景 4：审查通过，推送**
- 状态：coordinator_obs.overall_pass=true
- 规则判断 → push_notification ✅（不走 LLM）

**场景 5：需要重试**
- 状态：observation.needs_retry=true, react_cycle=0
- 规则判断 → planner（需要 LLM 重新编排，仍然调 LLM）✅

**场景 6：LLM 调用失败**
- 规则判断返回明确路由 → 直接使用规则结果 ✅
- 规则判断返回 planner → 走 LLM 调用，LLM 失败 → 降级到 planner ✅

**场景 7：死循环检测**
- 在规则判断之前执行，不受影响 ✅

### 十一、预估效果

正常流程中 router 的 6 次调用 → 5 次走规则（invoke_sub_agent → observe_results → coordinator_reflect → push_notification → update_memory），1 次走 LLM（planner 首次编排后）。

**节省 5 次 router LLM 调用**，每次 `max_tokens=512`。

---

以上是分析报告，要开始实施改动吗？