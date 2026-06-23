# 06 — DeepSeek V4 Thinking Mode 关闭 + tool_choice="required"

> **日期**：2026-06-23 | **状态**：✅ 已完成 | **关联 changelog**：v2.0.0 §2.6

---

## 一、问题分析

### 1.1 本质

修复 deepseek-v4-flash 在长上下文场景下 function calling 不稳定的 bug。

V4 系列默认开启 Thinking Mode（`thinking.type="enabled"`），该模式下 `tool_choice="required"` 会返回 HTTP 400，只能使用 `tool_choice="auto"`（默认）。当输入上下文较长（如 62 条数据，~14K tokens）时，模型倾向于回复纯文本确认而非调用工具，导致 Ranking Agent 连续 5 轮"思考但不调用工具"，浪费 135 秒 + 5 次 LLM API 调用，最终 ranked=0。

### 1.2 问题链路

```
deepseek-v4-flash 默认 Thinking Mode=enabled
  → tool_choice="required" 不可用（400 错误）
  → 只能 tool_choice="auto"（模型自主决定）
  → 长上下文下模型选择回复纯文本而非调用工具
  → 纯文本重试策略追加 user 消息但未改变任何 LLM 调用参数
  → 连续 5 轮返回纯文本，最终超时退出
```

---

## 二、改动要点

### 2.1 `utils/llm_provider.py` — `chat_with_tools()` 添加 `extra_body` + `tool_choice` 参数

（第 72-101 行）

- 新增 `tool_choice` 参数，默认 `"required"`（强制调用工具）
- 新增 `extra_body={"thinking": {"type": "disabled"}}` 关闭 V4 默认的思考模式
- `tool_choice=None` 时不传该参数（回退到模型默认行为）
- `tool_choice="auto"` 可显式覆盖为自主模式

### 2.2 三个 Agent 纯文本重试策略收紧

`turn < max_turns-1` → `turn < 1`：

| 文件 | 行号 | 说明 |
|------|------|------|
| `agents/ranking_agent.py` | 第 539 行 | 仅首次纯文本时重试 1 次 |
| `agents/collection_agent.py` | 第 243 行 | 同上 |
| `agents/briefing_agent.py` | 第 640 行 | 同上 |

原因：`tool_choice="required"` 下极少出现纯文本返回，保留 1 次重试仅作为极端兜底。

### 2.3 新增测试

`scripts/test_thinking_disabled.py`（8 项测试，全部通过）：

- 参数验证：`extra_body` 和 `tool_choice` 正确传入
- `tool_choice` 覆盖：`auto` / `None` 行为正确
- 三个 Agent 纯文本重试限为 1 次
- **真实 API 验证**：基础 tool call 正常
- **真实 API 验证**：长上下文（62 条模拟数据）连续 3 轮正确调用工具

---

## 三、不改的部分

- `chat()` 方法不变（不需要 tools 参数的调用不受影响）
- `LLMRouter.chat_with_tools()` 签名不变（通过 `**kwargs` 透传）
- 三个 Agent 的 ReAct 循环核心逻辑不变

---

## 四、效果对比

| 维度 | 改前（V4 Thinking Mode） | 改后（Thinking disabled） |
|------|--------------------------|--------------------------|
| tool_choice="required" | HTTP 400 ❌ | 正常 ✅ |
| 长上下文 function calling | 不稳定（5 轮纯文本） | 稳定（连续 3 轮正常调用） |
| 纯文本浪费 | 最多 5 轮 | 最多 1 轮 |
| 思考链内容 | 返回（增加 token 消耗） | 不返回 |

---

## 五、测试结果

- `scripts/test_thinking_disabled.py`：8/8 全部通过（含 2 项真实 API 测试）
- 真实 API 长上下文测试：第 1 轮 deduplicate → 第 2 轮 rank_items → 第 3 轮 finish_task ✅
