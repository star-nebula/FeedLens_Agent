# FeedLens 架构演进方案 — 借鉴 OpenClaw 强化 Agentic 能力

> **版本**：v1.0 | **日期**：2026-06-21 | **作者**：Codex [via: Codex]
> **背景**：FeedLens 已完成 MVP（多 Agent + LangGraph + Planner 自主编排）。本文档通过对比 OpenClaw 的优秀设计，提出针对性改进，使 FeedLens 的 agentic 能力更强、更可演进。

---

## 一、两套系统的定位差异（先对齐认知）

| 维度 | OpenClaw | FeedLens |
|------|----------|----------|
| **定位** | 多通道 AI 网关 / 个人 AI 助手（交互式） | 主动式信息聚合 Agent（定时自主执行） |
| **触发方式** | 用户消息驱动（30+ 渠道接入） | APScheduler 定时 + 重大事件破例 |
| **Agent 形态** | 长驻进程，多会话并发，子 Agent 通信（ACP） | 单次管线执行，子 Agent 顺序调度 |
| **扩展机制** | 完整 Plugin SDK，60+ 注册插槽 | FC 工具 + MCP Server，硬编码 |
| **记忆体系** | Context Engine + 长期 Memory + 会话持久化 | 短期 deque + ChromaDB + SQLite 情节 |

**关键结论**：FeedLens 不需要照搬 OpenClaw 的「多渠道接入」「长驻网关」「插件市场」。FeedLens 应该借鉴的是 **OpenClaw 让 Agent 更自主、更可扩展、更健壮的内部机制**，而非外部形态。

---

## 二、OpenClaw 值得借鉴的 6 个核心设计

### 2.1 Hook 系统（消息处理管线的扩展点）

**OpenClaw 做法**：`runInboundMessageHooks()` → 处理 → `runOutboundMessageHooks()`。所有扩展点通过 Hook 注册，核心零硬编码。

**FeedLens 现状**：节点逻辑全部硬编码在 `main_agent.py` 的节点函数里。例如 `observe_results_node` 的质量判断阈值（采集 < 3、top_score < 0.3、质量 < 0.7）写死在代码中；`coordinator_reflect_node` 的审查逻辑也无法外部扩展。

**改进价值**：FeedLens 的「质量评估」「破例推送判定」「偏好学习策略」都是会随业务演进的策略点。如果这些点能像 Hook 一样可注册、可替换，新增策略时就不需要改核心编排代码。

### 2.2 Context Engine（上下文窗口与记忆注入）

**OpenClaw 做法**：Context Engine 统一管理 Agent 的上下文窗口，在调用 LLM 前注入「相关记忆 + 最近会话」，planner 拿到的是结构化的、经过检索的上下文，而非原始全量状态。

**FeedLens 现状**：`_build_planner_context` 只是简单摘取 state 字段（collection.count、ranking.top_score 等），**完全没有利用已有的三层记忆体系**。`memory_manager.py` 写了完整的短期/长期/情节记忆，但 main_agent 从未调用 `get_context()` 注入历史经验。这意味着每次 planner 决策都是「失忆」的——不记得上次类似情况是怎么处理的。

**改进价值**：这是 FeedLens agentic 能力最大的短板。planner 有记忆系统却不用，等于自主决策缺少经验反馈。注入历史经验后，planner 能从「上次采集不足时 search_expand 有效」这类经验中学习。

### 2.3 Reply Fence（同一会话串行化）

**OpenClaw 做法**：Foreground Reply Fence 确保同一会话的消息串行处理，防止并发回复冲突。

**FeedLens 现状**：`push_scheduler.py` 用 APScheduler 触发管线，但**没有防止并发执行同一 user 的管线**。如果定时任务和手动触发重叠，或破例推送和定时推送撞车，会出现两个管线同时写 SQLite/ChromaDB，偏好向量可能互相覆盖。

**改进价值**：FeedLens 的 `feedback_agent` 偏好更新和 `update_memory` 偏好向量写入都是「读-改-写」操作，并发下会丢更新。需要一个 per-user 的执行栅栏。

### 2.4 模型回退链（fallbackModels + autoFallbackPrimaryProbe）

**OpenClaw 做法**：LLM 调用失败时按回退链自动切换模型，并有探测机制自动标记不可用模型。

**FeedLens 现状**：`DeepSeekProvider` 调用失败直接抛异常，planner 节点靠 `_fallback_plan` 降级为硬编码三板斧，`enrich_metadata` 失败则给条目打默认元数据。**没有模型级回退**——DeepSeek 整体不可用时全链路降级。

**改进价值**：FeedLens 强依赖 DeepSeek。增加一个本地/备用 Provider（如 Ollama、或备用 API key + base_url）作为回退，能让 enrich、planner、简报生成在主模型抖动时仍可工作。

### 2.5 插件化工具注册（registerTool / ToolContext）

**OpenClaw 做法**：工具通过 `registerTool(tool: AgentTool)` 动态注册，工具执行带 `ToolContext`（含会话、记忆、日志），工具表面（tool surface）按策略构建。

**FeedLens 现状**：`tools/fc_tools.py` 是扁平的函数集合，`tools/__init__.py` 直接导出。新增工具要改 `__init__.py` + 在 agent 节点里手动调用。**没有工具注册表、没有 ToolContext、没有按策略构建工具表面**。

**改进价值**：FeedLens 未来要加「网页正文提取」「微博热点」「GitHub trending」等采集源，以及「去重阈值自适应」「偏好衰减」等策略工具。插件化注册能让这些以独立模块形式接入，不改核心。

### 2.6 子 Agent 通信协议（ACP + 生命周期管理）

**OpenClaw 做法**：子 Agent 通过 ACP（Agent Communication Protocol）通信，有独立生命周期管理（spawn/ drain / close），支持子 Agent 间双向消息。

**FeedLens 现状**：子 Agent 是 LangGraph 子图，通过 `invoke_sub_agent_node` 顺序调度，**子 Agent 间无直接通信**，只能通过共享 state 间接传递。Collection→Ranking→Briefing 是固定流水线。

**改进价值**：FeedLens 当前流水线够用，但若要实现「Ranking 发现某主题条目过多 → 通知 Collection 补采该主题」「Briefing 发现来源单一 → 回溯 Ranking 调整多样性权重」这类跨 Agent 协作，需要轻量的 Agent 间消息机制。MVP 不必上完整 ACP，但可在 state 上增加 `agent_messages` 字段实现简化版。

---

## 三、FeedLens 当前 agentic 能力的诊断

基于对 `main_agent.py` / `state.py` / `collection_agent.py` / `ranking_agent.py` / `memory_manager.py` 的阅读：

| 能力维度 | 现状 | 自主程度 | 瓶颈 |
|---------|------|---------|------|
| **Planner 编排** | LLM 决策子 Agent 顺序 + params | ✅ 强 | 但上下文不含历史经验 |
| **ReAct 循环** | observe→planner 最多 3 轮 | ✅ 中 | 循环条件硬编码，无记忆引导 |
| **质量评估** | observe_results 硬编码阈值 | ❌ 弱 | 阈值不可配置、不可扩展 |
| **记忆利用** | 三层记忆已实现 | ❌ 未接入 | planner 从未调用 get_context |
| **错误处理** | run_with_isolation 隔离子 Agent | ✅ 中 | 无模型回退、无重试策略可配 |
| **并发安全** | 无 | ❌ 缺失 | 多触发源可能并发写偏好 |
| **工具扩展** | FC + MCP 硬编码 | ❌ 弱 | 无注册表、无 ToolContext |
| **跨 Agent 协作** | 共享 state 单向传递 | ❌ 弱 | 无反向消息通道 |

**核心判断**：FeedLens 的 Planner 已经有「自主决策的壳」，但缺「自主决策的养料」（记忆注入）和「自主决策的边界」（可配置策略 + 并发安全）。这正是 OpenClaw 做得好的地方。

---

## 四、改进方案（按优先级排序）

### P0 — 接入记忆到 Planner（最高 ROI，1-2 天）

**目标**：让 planner 决策时能看到历史经验，从「失忆决策」变为「经验驱动决策」。

**改动点**：

1. `agents/main_agent.py` `_build_planner_context` 增加记忆检索：
   ```python
   from utils.memory_manager import get_context
   # 用当前状态摘要作为 query 检索相关历史经验
   memory_ctx = get_context(
       query=f"采集{len(collected)}条 排序top{top_score} 简报质量{brief_quality}",
       n_recent=3, n_long_term=3
   )
   context["memory"] = {
       "recent_turns": memory_ctx["short_term"],
       "relevant_history": [m["document"] for m in memory_ctx["long_term"]]
   }
   ```

2. `PLANNER_SYSTEM_PROMPT` 增加记忆利用指引：
   ```
   ## 历史经验参考
   上下文中的 memory.recent_turns 和 memory.relevant_history 是过往类似情况的处理记录。
   若历史经验显示某策略有效/无效，优先参考；但若当前状态与历史差异大，以当前数据为准。
   ```

3. `update_memory_node` 增加本轮决策经验写入：
   ```python
   add_memory(
       session_id=session_id,
       event="planner_decision",
       node_name="planner",
       content={
           "situation": f"采集{len(collected)} 排序top{top_score} 简报质量{brief_quality}",
           "decision": sub_agent_plan,
           "outcome": "ok" if not needs_retry else "retry_needed",
       },
       status="completed"
   )
   ```

**验收**：planner 的 LLM 输入中能看到 `memory` 字段；连续两次相同触发条件下，第二次 planner 决策理由引用了第一次的经验。

### P1 — Hook 化质量评估与策略点（2-3 天）

**目标**：把硬编码的质量阈值和策略逻辑提取为可注册的 Hook，核心编排不再硬编码业务规则。

**设计**：新增 `utils/hooks.py`：
```python
# hooks.py
class HookRegistry:
    def __init__(self):
        self._hooks: dict[str, list[Callable]] = {}
    def register(self, hook_name: str, fn: Callable): ...
    def run(self, hook_name: str, context: dict) -> dict:
        """依次执行该 hook 下所有 fn，每个 fn 可修改并返回 context"""
        for fn in self._hooks.get(hook_name, []):
            context = fn(context) or context
        return context

# 全局单例
hooks = HookRegistry()
```

**Hook 点**（从 OpenClaw 的 inbound/outbound 模式借鉴）：

| Hook 名 | 触发位置 | 作用 | 现状对应硬编码 |
|--------|---------|------|--------------|
| `observe.evaluate` | observe_results_node | 评估各环节质量、产出 issues | 阈值 3/0.3/0.7 写死 |
| `planner.suggest` | observe_results_node | 产出 suggested_action | search_expand/expand_threshold 硬逻辑 |
| `push.decide` | should_push_now | 判断是否破例推送 | push_immediate 简单透传 |
| `reflect.check` | coordinator_reflect_node | 综合质量审查 | 审查逻辑内嵌节点 |
| `rank.weights` | rank_items_node | 动态选择排序权重 | 冷/热切换硬编码 |

**迁移策略**：先把现有硬编码逻辑原样搬进默认 Hook 实现注册到 `hooks`，节点改为 `hooks.run("observe.evaluate", context)`。保证行为不变，只是把逻辑从节点函数里「外提」到可替换的注册项。之后再新增策略就是 `hooks.register("observe.evaluate", my_custom_eval)`。

**验收**：默认 Hook 实现下行为与 MVP 完全一致；注册一个自定义 `observe.evaluate` 能改变 issues 输出，且无需改 main_agent.py。

### P2 — 执行栅栏防并发（1 天）

**目标**：同一 user 的管线串行执行，防止定时/手动/破例推送并发导致偏好向量丢更新。

**设计**：新增 `utils/execution_fence.py`：
```python
import threading
class ExecutionFence:
    def __init__(self):
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()
    def acquire(self, user_id: int) -> threading.Lock:
        with self._guard:
            if user_id not in self._locks:
                self._locks[user_id] = threading.Lock()
        return self._locks[user_id]

fence = ExecutionFence()
```

`pipeline_runner.run_agent_pipeline` 入口处：
```python
lock = fence.acquire(user_id)
if not lock.acquire(blocking=False):
    return {"status": "skipped", "reason": "another pipeline running for this user"}
try:
    # 原有管线执行
finally:
    lock.release()
```

**验收**：同时触发两次同一 user 的管线，第二次返回 `skipped`，不产生并发写入。

### P3 — 工具注册表与 ToolContext（2 天）

**目标**：工具以插件形式注册，带执行上下文（会话、记忆、日志），为新采集源/策略工具提供统一接入点。

**设计**：新增 `tools/registry.py`：
```python
@dataclass
class ToolContext:
    session_id: str
    user_id: int
    state: dict
    memory: "MemoryManager"

@dataclass
class AgentTool:
    name: str
    description: str
    parameters: dict  # JSON schema
    execute: Callable[[dict, ToolContext], Any]

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, AgentTool] = {}
    def register(self, tool: AgentTool): ...
    def get(self, name: str) -> AgentTool | None: ...
    def surface(self, names: list[str] | None = None) -> list[AgentTool]:
        """按策略构建工具表面，供 LLM function calling"""
```

**迁移**：把 `fc_tools.py` 里的 `fetch_rss`/`enrich_metadata`/`deduplicate` 等包装成 `AgentTool` 注册到 registry，节点函数改为 `tools.surface(["fetch_rss", ...])` 取用。MVP 阶段 surface 策略可固定，后续按 state 动态选择。

**验收**：新增一个 `web_extract` 工具只需 `tools/registry.py` 里 `register(AgentTool(...))`，无需改 `__init__.py` 或 agent 节点。

### P4 — 模型回退链（1 天）

**目标**：主 LLM 不可用时自动回退，避免全链路降级。

**设计**：`utils/llm_provider.py` 增加 `LLMRouter`：
```python
class LLMRouter:
    def __init__(self, providers: list[LLMProvider]):
        self._providers = providers
    def chat(self, messages, **kw):
        for p in self._providers:
            try:
                return p.chat(messages, **kw)
            except Exception as e:
                log.warning(f"provider {p.name} failed: {e}")
                continue
        raise RuntimeError("all providers failed")
```

`_get_llm_provider()` 改为返回 `LLMRouter([DeepSeekProvider(...), FallbackProvider(...)])`。FallbackProvider 可以是备用 key、或本地 Ollama。

**验收**：模拟主 Provider 抛异常，Router 自动用 FallbackProvider 返回结果，管线不中断。

### P5 — 轻量 Agent 间消息通道（2 天，可选）

**目标**：支持子 Agent 向前序 Agent 反向传递需求，打破单向流水线。

**设计**：`FeedLensState` 增加：
```python
agent_messages: list[dict[str, Any]]  # [{from: "Ranking", to: "Collection", msg: "supplement_topic:AI", priority: "high"}]
```

`invoke_sub_agent_node` 调度前检查 `agent_messages`，若有发给当前子 Agent 的消息，注入其 params。子 Agent 节点可 `state["agent_messages"].append({...})` 发消息。

**验收**：Ranking 发现某主题条目稀少 → append 消息 → 下一轮 planner 看到消息 → 调度 Collection 带补充主题参数。

---

## 五、不建议借鉴的部分（避免过度设计）

| OpenClaw 设计 | 不借鉴原因 |
|--------------|-----------|
| 多渠道接入（30+ Channel Plugin） | FeedLens 是定时主动执行，无用户消息入口 |
| 长驻 Gateway 进程 + Control UI | FeedLens 用 Streamlit + APScheduler 已够 |
| 完整 Plugin SDK + API 基线哈希 | FeedLens 单项目，无第三方插件生态需求 |
| OpenAI 兼容 API 网关 | FeedLens 不对外暴露 LLM 接口 |
| ACP 完整协议 | FeedLens 子 Agent 协作简单，state 消息够用 |

**原则**：FeedLens 借鉴 OpenClaw 的「Agent 内部机制」（记忆、Hook、栅栏、工具注册、回退），不借鉴「外部产品形态」（网关、渠道、插件市场）。

---

## 六、落地路线图

```
P0 记忆接入 Planner ──→ P1 Hook 化策略点 ──→ P2 执行栅栏
                                              ↓
              P5 Agent 间消息(可选) ←── P3 工具注册表 ──→ P4 模型回退
```

| 阶段 | 改进项 | 预估 | 依赖 | 风险 |
|------|-------|------|------|------|
| 第 1 周 | P0 记忆接入 + P2 执行栅栏 | 3 天 | 无 | 低，纯增量 |
| 第 2 周 | P1 Hook 化 | 3 天 | P0 | 中，需回归测试 |
| 第 3 周 | P3 工具注册表 + P4 模型回退 | 3 天 | 无 | 低，渐进迁移 |
| 第 4 周 | P5 Agent 间消息（可选） | 2 天 | P3 | 中，改变调度模型 |

**回归保障**：每个 P 完成后跑 `scripts/test_main_agent.py` + `test_ranking_agent.py` + `test_briefing_agent.py`，确保 MVP 行为不回归。P1 Hook 化后额外跑 `test_integration.py` 验证端到端。

---

## 七、与现有 ADR 的关系

本方案不推翻任何已记录的 ADR（ADR-001 LangGraph、ADR-002 多 Agent 架构等），而是在其基础上增强：

- **P0 记忆接入**：兑现 ADR-002「多 Agent 自主规划」中「记忆驱动决策」的未完成部分
- **P1 Hook 化**：为 ADR-005「排序权重动态切换」提供更通用的策略扩展点
- **P3 工具注册表**：扩展 ADR-003「MCP 传输模式」的工具接入方式，不替换 MCP
- **P4 模型回退**：强化 ADR-006「Embedding 模型选型」未覆盖的 LLM 层容错

建议为每个 P 项新增一份 ADR 记录决策理由。

---

## 附录 A：OpenClaw 关键设计速查

| 设计 | 核心机制 | FeedLens 对应改进 |
|------|---------|-----------------|
| Hook 系统 | inbound/outbound 钩子管线 | P1 Hook 化策略点 |
| Context Engine | 记忆检索 + 上下文窗口注入 | P0 记忆接入 Planner |
| Reply Fence | 同会话串行化 | P2 执行栅栏 |
| fallbackModels | 模型回退链 + 探测 | P4 模型回退 |
| registerTool | 工具动态注册 + ToolContext | P3 工具注册表 |
| ACP | 子 Agent 通信协议 | P5 Agent 间消息 |

## 附录 B：FeedLens 现状代码引用

| 现状 | 文件 | 改进对应 |
|------|------|---------|
| planner 上下文不含记忆 | `agents/main_agent.py:_build_planner_context` | P0 |
| 质量阈值硬编码 | `agents/main_agent.py:observe_results_node` | P1 |
| 无并发防护 | `utils/pipeline_runner.py:run_agent_pipeline` | P2 |
| 工具扁平导出 | `tools/__init__.py` + `tools/fc_tools.py` | P3 |
| 单 Provider 无回退 | `utils/llm_provider.py:DeepSeekProvider` | P4 |
| 子 Agent 单向传递 | `agents/state.py:FeedLensState` | P5 |
