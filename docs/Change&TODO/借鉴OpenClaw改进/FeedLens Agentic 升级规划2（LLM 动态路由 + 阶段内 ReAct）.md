# FeedLens Agentic 升级规划（方案二：LLM 动态路由 + 阶段内 ReAct）

> 创建时间：2026-06-22
> 目标：将当前「LLM 辅助编排的智能流水线」改造为「层级自主 Agent」
> 执行约束：**每个 Phase 完成后必须自测通过才能进入下一 Phase**

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

## 三、执行顺序（关键：每个 Phase 独立可验证）

```
Phase 1:  工具层扁平化 (tools/tool_registry.py)
          ↓ 验证: 所有工具 schema 可序列化，dispatch 正确调用
Phase 2:  State 扩展 (agents/state.py)
          ↓ 验证: 新字段可正常读写，不影响现有流程
Phase 3a: collection_agent ReAct 化
          ↓ 验证: 单独调用采集 Agent，LLM 自主选工具并正确结束
Phase 3b: ranking_agent ReAct 化
          ↓ 验证: 单独调用排序 Agent，LLM 自主选工具并正确结束
Phase 3c: briefing_agent ReAct 化
          ↓ 验证: 单独调用简报 Agent，LLM 自主选工具并正确结束
Phase 4a: 主 Agent 部分路由改造（planner → invoke 段）
          ↓ 验证: 主流程中 planner 到 invoke 的跳转由 LLM 决定
Phase 4b: 主 Agent 全部路由改造（所有边）
          ↓ 验证: 完整主流程跑通，LLM 自主路由到结束
Phase 5:  pipeline_runner 适配 + 集成测试
          ↓ 验证: pipeline_runner.py 触发完整管线
Phase 6:  真机验证
          ↓ 验证: python utils/pipeline_runner.py --trigger manual
```

**为什么拆开**：每个子步骤独立可验证，出问题立刻定位到具体 Phase，不会全线崩溃。

---

## 四、Phase 详细规格

---

### Phase 1: 工具层扁平化

**目标**：将所有工具函数包装为标准 OpenAI function calling schema，让 LLM 能自主选择调用。

**改动文件**：新建 `tools/tool_registry.py`

**数据结构**：每个工具 = `{name, description, parameters(JSON Schema), fn(可调用函数)}`

**完整工具清单**（必须一次性全部定义，避免后续 Phase 发现缺工具回头补）：

| 工具名 | 描述 | 所属阶段 |
|--------|------|---------|
| `fetch_rss` | 从 RSS 源采集内容 | 采集 |
| `search_web` | MCP 搜索补充内容 | 采集 |
| `enrich_metadata` | LLM 增强元数据（分类/关键词/重要性） | 采集 |
| `normalize_items` | 字段标准化（标题/时间/来源格式统一） | 采集 |
| `deduplicate` | 向量相似度去重 | 排序 |
| `rank_items` | 多因子偏好排序 | 排序 |
| `generate_briefing` | 生成结构化简报 | 简报 |
| `quality_check` | 四维质量审查 | 简报 |
| `push_notification` | 推送简报到 Streamlit | 推送 |
| `record_feedback` | 记录用户反馈并更新偏好向量 | 反馈 |
| `read_memory` | 读取用户历史决策记忆 | 通用 |
| `write_memory` | 写入本轮决策经验 | 通用 |
| `finish_task` | 标记当前阶段完成，返回结果摘要 | 通用 |

**必须实现的 API**：

```python
# tools/tool_registry.py

class ToolRegistry:
    def get_schemas(self) -> list[dict]:
        """返回所有工具的 OpenAI function calling schema 列表"""
    
    def get_schemas_for_phase(self, phase: str) -> list[dict]:
        """返回指定阶段的工具 schema 列表
        phase: "collection" | "ranking" | "briefing" | "main"
        """
    
    def dispatch(self, tool_name: str, arguments: dict) -> Any:
        """根据 tool_name 执行对应函数，传入 arguments"""
```

**验证标准**（Phase 1 完成后必须通过）：
1. `get_schemas()` 返回的每个 schema 包含 `name`/`description`/`parameters` 三个字段
2. `parameters` 是合法的 JSON Schema 格式
3. `dispatch("fetch_rss", {"sources": [...], "max_workers": 3})` 能正确调用现有采集逻辑
4. 所有 13 个工具都能 dispatch 成功，无 KeyError

---

### Phase 2: State 扩展

**目标**：新增路由控制字段，不改动现有字段。

**改动文件**：`agents/state.py`

**新增字段**（追加到现有 `FeedLensState` TypedDict 末尾）：

```python
# 路由控制（新增）
router_decision: dict[str, Any]       # 格式: {"next_node": "planner", "reason": "需要重新编排"}
router_history: list[dict[str, Any]]  # 历史决策列表，用于死循环检测
agentic_turn_count: int               # 当前主循环计数，默认 0
```

**验证标准**：
1. 现有 `scripts/test_main_agent.py` 全部测试仍然通过（新增字段有默认值，不影响旧流程）
2. 可以正常创建 `FeedLensState` 实例并读写新字段

---

### Phase 3a: collection_agent ReAct 化

**目标**：将 `agents/collection_agent.py` 从 StateGraph 改为 ReAct 循环。

**改动文件**：`agents/collection_agent.py`

**ReAct 循环伪代码**：

```python
def run_collection_agent(state: FeedLensState) -> dict:
    """ReAct 采集 Agent"""
    tools = tool_registry.get_schemas_for_phase("collection")
    # tools: [fetch_rss, search_web, enrich_metadata, normalize_items, finish_task]
    
    messages = [
        {"role": "system", "content": COLLECTION_SYSTEM_PROMPT},
        {"role": "user", "content": f"用户目标: {state['goal_category']}, 偏好: {state.get('user_prefs', {})}"}
    ]
    
    max_turns = 5
    for turn in range(max_turns):
        response = llm.chat(messages=messages, tools=tools)
        
        if response.has_tool_calls:
            for tool_call in response.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                
                # 执行工具
                result = tool_registry.dispatch(tool_name, tool_args)
                
                # 将结果追加到 messages
                messages.append(response.assistant_message)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })
                
                # 如果调用了 finish_task，结束循环
                if tool_name == "finish_task":
                    return result
        else:
            # LLM 没调工具直接回复，视为异常，强制调 finish_task
            break
    
    # 兜底：超过 max_turns 未 finish，强制返回已有数据
    return {"status": "timeout", "items": state.get("raw_items", [])}
```

**系统提示词要点**（`COLLECTION_SYSTEM_PROMPT`）：
- 你是采集 Agent，目标是从多个来源采集信息
- 你可以自主决定：先 fetch_rss 还是 search_web？是否需要 enrich_metadata？
- 采集完成后必须调用 `finish_task` 返回结果
- 如果某个工具失败，可以尝试替代方案（如 RSS 失败则 search_web）

**验证标准**：
1. 编写 `scripts/test_collection_agent_react.py`，mock LLM 返回 tool_calls，验证：
   - LLM 调 `fetch_rss` → 返回采集结果
   - LLM 调 `search_web` → 返回搜索结果
   - LLM 调 `finish_task` → 循环正确退出
2. 超过 5 轮未调 `finish_task` → 强制退出并返回已有数据

---

### Phase 3b: ranking_agent ReAct 化

**目标**：将 `agents/ranking_agent.py` 从 StateGraph 改为 ReAct 循环。

**改动文件**：`agents/ranking_agent.py`

**工具列表**：`[deduplicate, rank_items, finish_task]`

**系统提示词要点**：
- 你是排序 Agent，目标是对采集到的内容去重并按用户偏好排序
- 你可以自主决定：先 deduplicate 再 rank_items？还是直接 rank？
- 完成后必须调用 `finish_task` 返回排序结果

**验证标准**：
1. 编写 `scripts/test_ranking_agent_react.py`，mock LLM 返回 tool_calls，验证：
   - LLM 调 `deduplicate` → `rank_items` → `finish_task` 流程
   - LLM 直接调 `rank_items` → `finish_task`（跳过去重）
2. 超过 5 轮未调 `finish_task` → 强制退出并返回已有数据

---

### Phase 3c: briefing_agent ReAct 化

**目标**：将 `agents/briefing_agent.py` 从 StateGraph 改为 ReAct 循环。

**改动文件**：`agents/briefing_agent.py`

**工具列表**：`[generate_briefing, quality_check, finish_task]`

**注意**：简报 Agent 是轻量 ReAct，只能在这两个工具之间迭代，不允许调到采集/排序工具。

**系统提示词要点**：
- 你是简报 Agent，目标是根据排序结果生成高质量信息简报
- 标准流程：generate_briefing → quality_check → 如果质量不达标则重新 generate_briefing → ...
- 最多迭代 3 轮，达到质量要求或超过轮数后调用 `finish_task`
- 完成后必须调用 `finish_task` 返回简报内容

**验证标准**：
1. 编写 `scripts/test_briefing_agent_react.py`，mock LLM 返回 tool_calls，验证：
   - LLM 调 `generate_briefing` → `quality_check` → `finish_task`
   - quality_check 返回低分 → LLM 重新调 `generate_briefing`
2. 超过 5 轮未调 `finish_task` → 强制退出并返回已有简报

---

### Phase 4a: 主 Agent 部分路由改造（planner → invoke 段）

**目标**：先将 `planner → invoke_sub_agent` 这段改为 LLM 决策，其他边保持不变。这是最小改动验证路由机制可行。

**改动文件**：`agents/main_agent.py`

**具体操作**：

1. 新增 `router_node` 函数：

```python
def router_node(state: FeedLensState) -> dict:
    """LLM 动态路由决策节点"""
    
    # 防死循环：检查最近 3 次决策是否相同
    recent = state.get("router_history", [])[-3:]
    if len(recent) >= 3 and len(set(d["next_node"] for d in recent)) == 1:
        return {"router_decision": {"next_node": "update_memory", "reason": "死循环检测，强制结束"}}
    
    # 硬兜底：超过 max_turns
    if state.get("agentic_turn_count", 0) >= 5:
        return {"router_decision": {"next_node": "update_memory", "reason": "超过最大轮数"}}
    
    # 构建状态摘要
    state_summary = {
        "intent": state.get("intent", {}),
        "plan": state.get("plan", []),
        "has_raw_items": len(state.get("raw_items", [])) > 0,
        "has_ranked_items": len(state.get("ranked_items", [])) > 0,
        "has_briefing": state.get("briefing_text") is not None,
        "quality_score": state.get("quality_score"),
        "turn_count": state.get("agentic_turn_count", 0),
    }
    
    # 调用 LLM 决策
    response = llm.chat(messages=[
        {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(state_summary, ensure_ascii=False)}
    ])
    
    # JSON 解析容错（关键：LLM 返回可能不是纯 JSON）
    decision = _parse_router_response(response)
    
    return {
        "router_decision": decision,
        "router_history": state.get("router_history", []) + [decision],
        "agentic_turn_count": state.get("agentic_turn_count", 0) + 1,
    }
```

2. `_parse_router_response` 必须实现 JSON 容错：

```python
def _parse_router_response(response: str) -> dict:
    """容错解析 LLM 路由决策，必须返回有效 dict"""
    # 尝试 1: 直接 json.loads
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass
    
    # 尝试 2: regex 提取 {...} 
    import re
    match = re.search(r'\{[^{}]*\}', response)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    
    # 尝试 3: 兜底，默认走 planner
    return {"next_node": "planner", "reason": "router parse fallback"}
```

3. **仅改这一条边**：`planner → router_node`（`add_conditional_edges`），router 可返回 `invoke_sub_agent` 或 `planner`（重新编排）。

其他边保持原有硬编码不变。

**ROUTER_SYSTEM_PROMPT**（本次只用两个节点）：
```
你是 FeedLens 的自主路由决策者。根据当前状态，决定下一步。

可跳转节点：
- "invoke_sub_agent": 执行 planner 编排的子 Agent
- "planner": 需要重新编排执行计划

请只返回 JSON：{"next_node": "...", "reason": "..."}
```

**验证标准**：
1. 编写 `scripts/test_router.py`，测试各种输入：
   - `plan` 有内容 + 无 raw_items → 返回 `invoke_sub_agent`
   - `plan` 为空 → 返回 `planner`
   - 模拟 LLM 返回非 JSON 文本 → `_parse_router_response` 正确降级
2. 主流程中 planner 完成后由 LLM 决定走 invoke 还是重新 planner

---

### Phase 4b: 主 Agent 全部路由改造

**目标**：将剩余所有硬编码边改为 router_node 决策。

**改动文件**：`agents/main_agent.py`

**具体操作**：

1. 将以下硬编码边全部改为 `add_conditional_edges(node, router_node, path_map)`：
   - `understand_intent → router_node`
   - `planner → router_node`（Phase 4a 已完成）
   - `invoke_sub_agent → router_node`
   - `coordinator_reflect → router_node`

2. 更新 `ROUTER_SYSTEM_PROMPT` 加入全部可跳转节点：
```
你是 FeedLens 的自主路由决策者。根据当前状态，决定下一步。

可跳转节点：
- "planner": 需要重新编排子 Agent 执行计划
- "invoke_sub_agent": 执行 planner 编排的子 Agent
- "push_notification": 简报已就绪，执行推送
- "update_memory": 记录执行日志并结束
- "abort": 放弃本次执行

当前状态：{state_summary}

请只返回 JSON：{"next_node": "...", "reason": "..."}
```

3. 移除硬编码的 `should_continue_react` / `should_push_now` 函数（路由统一由 router_node 处理）

4. 保留 `observe_results` / `coordinator_reflect` 节点，但改为纯状态更新（计算质量指标写入 state），不再做路由决策。

**验证标准**：
1. `scripts/test_router.py` 扩展测试，验证所有路由场景：
   - 采集为 0 条 → `abort`
   - 简报质量 < 阈值 → `planner`（重做）
   - 简报质量达标 → `push_notification`
   - 推送完成 → `update_memory`
2. `scripts/test_main_agent.py`（更新后）全部通过

---

### Phase 5: pipeline_runner 适配 + 集成测试

**目标**：适配 `pipeline_runner.py` 调用方式，确保新旧接口兼容。

**改动文件**：`utils/pipeline_runner.py`、`scripts/test_main_agent.py`

**具体操作**：
1. `pipeline_runner.py` 中调用子 Agent 的方式从 `builder().invoke()` 改为调用 ReAct 函数
2. 更新 `scripts/test_main_agent.py` 测试用例适配新的路由逻辑
3. 边界测试：
   - 采集返回 0 条 → 主流程 abort
   - 简报质量低（score < 0.3）→ router 决定重做
   - 正常流程：采集→排序→简报→推送→记忆写入

**验证标准**：
1. `scripts/test_main_agent.py` 全部通过
2. `python utils/pipeline_runner.py --trigger manual` 不报错

---

### Phase 6: 真机验证

**目标**：在真实环境跑完整管线，确认端到端可用。

**验证命令**：
```bash
python utils/pipeline_runner.py --trigger manual
```

**验证内容**：
1. 管线正常启动，不被 execution_fence 阻塞
2. LLM 正确路由各阶段
3. 子 Agent ReAct 循环正确执行并退出
4. 简报正常生成并推送
5. 记忆正常写入

---

## 五、文件改动清单

| 文件 | 改动类型 | Phase |
|------|---------|-------|
| `tools/tool_registry.py` | **新建** | P1 |
| `agents/state.py` | 修改（追加字段） | P2 |
| `agents/collection_agent.py` | 重写（StateGraph→ReAct） | P3a |
| `agents/ranking_agent.py` | 重写（StateGraph→ReAct） | P3b |
| `agents/briefing_agent.py` | 重写（StateGraph→ReAct） | P3c |
| `agents/main_agent.py` | 修改（新增 router_node + 改边） | P4a, P4b |
| `utils/pipeline_runner.py` | 适配 | P5 |
| `scripts/test_main_agent.py` | 更新 | P5 |
| `scripts/test_collection_agent_react.py` | **新建** | P3a |
| `scripts/test_ranking_agent_react.py` | **新建** | P3b |
| `scripts/test_briefing_agent_react.py` | **新建** | P3c |
| `scripts/test_router.py` | **新建** | P4a |
| `docs/changelog.md` | 追加 | P6 |

---

## 六、开发约束（Agent 执行时必须遵守）

### 6.1 每次只改一个 Phase

改完 → 自测通过 → 再改下一个。禁止跨 Phase 同时改动多个文件。

### 6.2 每个 Phase 的"完成"定义

- 代码已写入
- 对应的验证测试已通过
- 不引入新的 linter 错误
- 已有的其他测试没有退化

### 6.3 容错要求（必须实现，不是可选项）

| 位置 | 容错措施 |
|------|---------|
| `router_node` | `_parse_router_response` 必须处理 LLM 返回非 JSON 的情况，降级到 `planner` |
| 子 Agent ReAct 循环 | 超过 `max_turns=5` 必须强制退出并返回已有数据 |
| `tool_registry.dispatch` | 工具名不存在时抛出明确异常（含可用工具列表） |
| 主循环 | `router_history` 检测连续 3 次相同路由 → 强制 `update_memory` 结束 |

### 6.4 不做的事

- 不要新增任何配置文件
- 不要修改 `config/config.yaml`（除非工具需要新参数）
- 不要修改 Streamlit UI
- 不要修改 `agents/feedback_agent.py`
- 不要引入新的第三方依赖

---

## 七、风险与回退

| 风险 | 缓解措施 |
|------|---------|
| LLM 路由死循环 | `router_history` 连续 3 次相同 → 强制结束 |
| LLM 返回非 JSON | `_parse_router_response` 三层容错（直接解析→regex 提取→降级） |
| ReAct 不收敛 | 每个子 Agent max 5 turns 硬兜底 |
| 单 Phase 改动导致全流程挂 | 每个 Phase 独立验证，出问题只影响当前 Phase |
| function calling 成本增加 | 开发阶段 max_turns=3，真机验证调到 5 |

**回退策略**：改动在 develop 分支进行，main 分支保持 MVP 可用状态。任何 Phase 失败可回退到上一 Phase 的 commit。
