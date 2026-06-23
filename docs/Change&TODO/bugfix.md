# Bug 修复记录

---

## BUG-001: expand_threshold 在 ReAct 循环中漏传导致排序始终 0 条

**日期**：2026-06-23  
**严重程度**：P0（用户可见，简报空白）  
**改动文件**：`agents/ranking_agent.py`

### 本质

planner 正确决策了 `expand_threshold=true` 并通过 `current_state = {**current_state, **params}` 注入到 state，但 `ranking_agent` 的 ReAct 循环在调用 `rank_items` 工具时，`tool_args` 中没有包含 `expand_threshold`，导致 `_execute_rank_items` 读到的始终是默认值 `False`。预筛窗口始终为 72h（3天），当所有采集数据都超过 3 天时，排序结果始终为 0 条。

### 问题链路

```
planner 决策 expand_threshold=true
  → main_agent 注入 state: current_state["expand_threshold"] = True  ✅
  → ranking_react 循环: tool_args 中没有 expand_threshold            ❌
  → _execute_rank_items: arguments.get("expand_threshold", False) → False ❌
  → rank_items_node: state.get("expand_threshold", False) → False      ❌
  → prefilter_hours = 72h（而非 336h）
  → 所有超过3天的数据被丢弃 → ranked=0
```

### 表现

- 前端简报空白（items=0），用户看到"暂无内容"
- 日志显示 `collected=63, ranked=0, quality=0.5`，planner 已决策 expand_threshold 但结果仍为 0
- `execution_logs` 中多次出现 "采集充足但排序过严导致0条入简报"

### 改动要点

- **`agents/ranking_agent.py` 第 483-494 行 — ranking_react 循环中注入 expand_threshold**
  ```python
  if "expand_threshold" not in tool_args:
      et = current_state.get("expand_threshold", False)
      tool_args["expand_threshold"] = et
      if et:
          print(f"[ranking_react] expand_threshold=True 已注入 rank_items 工具调用", flush=True)
  ```

- **`agents/ranking_agent.py` 第 222 行 — 日志增强**
  - `[rank_items] 开始排序: N 条, expand_threshold=True/False`

- **新增测试** `scripts/test_expand_threshold.py`（4 项测试，全部通过）
  - `expand_threshold=False`: 10条5天前数据 → 72h窗口 → 0条保留
  - `expand_threshold=True`: 10条5天前数据 → 336h窗口 → 10条全部保留
  - `_execute_rank_items` 参数传递正确性
  - `ranking_react` 源码包含注入逻辑

### 不影响项

- `rank_items_node` 逻辑不变（本来就支持 expand_threshold）
- `_execute_rank_items` 逻辑不变（本来就支持 expand_threshold）
- Collection/Briefing Agent 不涉及 expand_threshold

### 测试结果

- `scripts/test_expand_threshold.py`: 4/4 通过
- `scripts/test_thinking_disabled.py`: 8/8 通过（回归验证）

---

## BUG-002: DeepSeek V4 Thinking Mode 下 tool_choice="required" 报 400 错误

**日期**：2026-06-22  
**严重程度**：P1（功能阻塞）  
**改动文件**：`utils/llm_provider.py`

### 本质

DeepSeek V4 在启用 thinking mode 时，`tool_choice="required"` 参数不被支持，导致 HTTP 400 错误。关闭 thinking mode（`chat()` 不传 `tools` 参数时自动禁用）后恢复正常。

### 表现

- `chat_with_tools()` 调用返回 HTTP 400
- 长上下文 function calling 不稳定（最多 5 轮纯文本后停止调用工具）

### 改动要点

- `utils/llm_provider.py`：`chat()` 方法在检测到 `tools` 参数时自动设置 `thinking=None` 禁用思考链
- `LLMRouter.chat_with_tools()` 通过 `**kwargs` 透传，无需修改签名

### 测试结果

- `scripts/test_thinking_disabled.py`: 8/8 通过
- 真实 API 长上下文测试：连续 3 轮正常 function calling
