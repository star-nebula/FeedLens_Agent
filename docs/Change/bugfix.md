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

---

## BUG-003: 简报前端展示分裂 + 时间显示"未知时间"（2026-06-23）

**日期**：2026-06-23  
**严重程度**：P1（用户可见，展示异常）  
**改动文件**：`agents/briefing_agent.py`

### 问题1：分类标题和列表项被分开显示

**本质**：`_render_markdown` 使用 `## 分类名`（h2）+ `### 主条目`（h3）两个独立 Markdown 标题层级，加上 `home_page.py` 中 Markdown 和条目列表分别在两个 `st.expander` 中渲染，导致视觉上分裂。

**修复**：重写 `_render_markdown`，分类标题保留 h2，但主条目改用 `**粗体**` 内联格式，元信息（来源/时间/重要性/评分）合并到同一行，所有内容在一个文本块内。

### 问题2：时间显示"未知时间"

**本质**：`_backfill_briefing_items` 中，当 LLM 生成的 `published_at` 有值（即使是错误值如"未知时间"），原始数据的 `published_at` 不会被强制覆盖。因为强制覆盖条件只匹配 `isinstance(orig_val, (int, float))` 或 `source`/`url`，字符串类型的 `published_at` 不在其中。

**修复**：将 `published_at` 加入强制覆盖字段列表。

### 问题3：缺少评分显示

**修复**：
- `_BACKFILL_FIELDS` 增加 `final_score`
- 回填时自动将 ranking_agent 的 `_score` 字段映射为 `final_score`
- `_render_markdown` 元信息行增加 `评分: 0.344` 显示

### 问题4：类似报道未展开

**修复**：`_render_markdown` 中类似报道子条目以 `- xxx` 列表形式展开显示。

### 改动要点

| 位置 | 改动 |
|------|------|
| `_render_markdown()` | 重写为统一平面格式，粗体标题 + 单行元信息 |
| `_BACKFILL_FIELDS` | 新增 `final_score` |
| `_backfill_briefing_items()` | `_score` → `final_score` 映射；`published_at` 加入强制覆盖 |
| `_render_markdown` 元信息行 | 新增 `评分: 0.xxx` 字段 |

### 输出格式对比

**改前**：
```markdown
## 数据安全与隐私 (1条)          ← 分类标题

### Meta因数据安全问题...         ← h3 标题，视觉分离
**摘要**: ...
- 来源: 36氪 | 时间: 未知时间 | 重要性: 4/5
```

**改后**：
```markdown
派早报：英特尔将为苹果代工芯片

摘要: 英特尔将为苹果代工芯片；库克称iPhone涨价不可避免；美国科技公司限制员工AI成本；Modos推出开源13.3寸彩色墨水屏。

链接: https://sspai.com/post/111343

- 来源: 少数派 | 时间: 2026-06-21 23:13:00 | 重要性: 4/5 | 评分: 0.344
- [👍 喜欢] [👎 不喜欢] [🚫 不相关]    ← 可交互图标，点击后线条→填充

还有 6 篇类似报道:
- WWDC26 在现场，与 Apple 设计大奖提名开发者聊聊他们的 app
- 具透 | visionOS 27 首个开发者测试版中值得关注的新内容
- AI 工作流实践：100% Vibe Coding 完成 Game Jam 游戏开发
- Nothing Phone 杂谈：活下去再谈未来，然后呢？
- xxx
- xxx
```

### 测试结果

- `scripts/test_briefing_render.py`: 5/5 通过（新增）
- `scripts/test_thinking_disabled.py`: 8/8 通过（回归）

---

## BUG-004: 工具 schema 中 `required: ["items"]` 与 `tool_choice="required"` 冲突导致 Ranking Agent 首轮卡死

**日期**：2026-06-23  
**严重程度**：P0（用户可见，简报始终空白）  
**改动文件**：`tools/tool_registry.py`

### 本质

`deduplicate`、`rank_items`、`generate_briefing` 三个工具在 schema 中将 `items` 标记为 `required: ["items"]`，与全局 `tool_choice="required"` 产生冲突：

1. `tool_choice="required"` 强制 LLM 必须调用工具
2. `required: ["items"]` 强制 LLM 必须传入 `items` 参数
3. 但 LLM 手中只有用户消息中的文本摘要，没有结构化的 `items` 数组可传

两个强制约束互相矛盾，LLM 无法满足任何一个，导致首轮不调用任何工具直接返回空响应（`finish_reason="stop"` 而非 `"tool_calls"`）。Ranking Agent 首轮失败后直接 break 退出，`ranked_items` 始终为空，后续 Briefing Agent 无数据可生成。

### 为什么 Collection Agent 不受影响

Collection Agent 第一个调用的 `fetch_rss` 没有 `required` 约束，LLM 可以无参调用，系统自动注入 `sources`。这建立了一个"无参调用成功"的先例模式，后续 `normalize_items` 等工具即使有 `required: ["items"]`，LLM 也会模仿前面的模式不传参调用。而 Ranking Agent 第一轮就面对 `deduplicate`（`required: ["items"]`），没有成功的先例参考。

### 为什么测试代码通过了

`scripts/test_thinking_disabled.py` 长上下文测试中使用的工具 schema 已将 `required` 设为空数组 `[]`，与生产代码不一致：

```python
# 测试代码（通过）:
{"name": "deduplicate", "parameters": {"type": "object", "properties": {}, "required": []}}

# 生产代码（卡死）:
{"name": "deduplicate", "parameters": {"type": "object", "properties": {...}, "required": ["items"]}}
```

### 问题链路

```
tool_choice="required" (全局)
  + required: ["items"] (deduplicate/rank_items schema)
  → LLM 被强制调用工具，但不知道 items 该传什么
  → 返回 finish_reason="stop", content="" (不调用任何工具)
  → ranking_react 第1轮进入 else 分支 → break 退出
  → ranked_items = []
  → Briefing Agent 收到空数据 → 简报质量 0.5
```

### 表现

- 日志显示 `[ranking_react] LLM 未调用工具，回复:` （content 为空）
- `[ranking_react] 超过 5 轮未完成，强制返回`（实际第1轮就退出了）
- `collected=63, ranked=0, quality=0.5` 反复出现
- planner 正确决策了 `expand_threshold` 也无法挽回（因为 Ranking 根本没执行到 `rank_items`）

### 改动要点

| 工具 | 改动 |
|------|------|
| `deduplicate` | `required: ["items"]` → `required: []`；description 增加 "⚠️ items 参数由系统自动注入" |
| `rank_items` | `required: ["items"]` → `required: []`；description 增加 "⚠️ items 参数由系统自动注入" |
| `generate_briefing` | `required: ["items"]` → `required: []`；description 增加 "⚠️ items 参数由系统自动注入" |

参数注入逻辑（`ranking_agent.py` 第481行 `"items" not in tool_args`）保持不变，当 LLM 不传 `items` 时自动注入 `collected_items`。

### 不影响项

- `_execute_deduplicate` / `_execute_rank_items` / `_execute_generate_briefing` 内部逻辑不变
- `ranking_agent.py` / `collection_agent.py` / `briefing_agent.py` 参数注入逻辑不变
- `llm_provider.py` 的 `tool_choice="required"` 保持不变（与修复后的空 required 兼容）
- 其他工具（`normalize_items`、`enrich_metadata`）暂不修改（Collection Agent 不受影响）

### 验证方式

- 修改后，LLM 可以无参调用 `deduplicate` / `rank_items` / `generate_briefing`
- 系统自动注入 `items` 参数，数据流正常
- 参考 `scripts/test_thinking_disabled.py` 长上下文测试（已使用相同的 `required: []` 模式并通过）
