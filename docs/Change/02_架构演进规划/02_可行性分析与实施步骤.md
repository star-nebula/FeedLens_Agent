# FeedLens 架构演进 — 可行性 / 优先级 / MVP 实施步骤

> **版本**：v1.0 | **日期**：2026-06-21 | **作者**：Codex [via: Codex]
> **配套文档**：`docs/架构演进/借鉴OpenClaw改进方案.md`（本文件是其落地细化版）
> **约束**：复用现有代码；不引入新框架/大型库；每个改动点 ≤50 行；可验证。

---

## 一、可行性分析（P0~P5 逐条）

评估口径：技术可行性（现有代码是否支撑）、风险、工作量（人天）、能否采用最简方式。

### P0 记忆接入 Planner

| 维度 | 评估 |
|------|------|
| **可行性** | ✅ 高。`utils/memory_manager.py` 已实现 `get_context(query, n_recent, n_long_term)` 和 `add_memory(session_id, event, node_name, content, status)`，均为同步函数。`_build_planner_context` 是纯函数，插一段记忆检索即可。 |
| **风险** | 低。① 记忆系统首次运行时 ChromaDB 长期记忆为空，`get_context` 返回空列表——planner 上下文多一个空 `memory` 字段，不影响决策，prompt 已写「无历史时以当前数据为准」。② ChromaDB 不可用时 `get_context` 内部已有 try/except，返回空。 |
| **工作量** | 0.5~1 人天。`_build_planner_context` 改 ~15 行；`update_memory_node` 改 ~10 行；`PLANNER_SYSTEM_PROMPT` 加 ~5 行指引。 |
| **为何可最简** | 记忆系统已建好，只是没接线。最简方式 = 直接调用现有 `get_context`/`add_memory`，不新建任何类、不改 state 结构、不动 LangGraph 图。任何额外抽象（如独立的 ContextEngine 类）都是过度设计。 |

### P1 Hook 化策略点

| 维度 | 评估 |
|------|------|
| **可行性** | ✅ 中高。`observe_results_node`/`coordinator_reflect_node`/`should_push_now` 的策略逻辑都是同步纯函数，可提取。需要新建一个极简 `HookRegistry`（dict + run 循环，~30 行）。 |
| **风险** | 中。① 提取逻辑时若漏搬分支会导致行为回归——必须有对照测试。② Hook 执行顺序若依赖注册顺序，后续多 Hook 注册时可能出现顺序耦合。缓解：MVP 阶段每个 hook 点只注册 1 个默认实现，不引入优先级。 |
| **工作量** | 2~3 人天。`hooks.py` ~30 行；5 个 hook 点迁移各 ~10 行；回归测试调试占大头。 |
| **为何不能纯最简** | 不能「零抽象」——Hook 的价值就在于可替换，必须有一个注册表容器。但可以「最简抽象」：`HookRegistry` 只做 `register` + `run`（顺序执行、合并返回 dict），不上优先级、不上异步、不上取消机制。这是满足「可扩展」的最小集。 |

### P2 执行栅栏防并发

| 维度 | 评估 |
|------|------|
| **可行性** | ✅ 高。`pipeline_runner.run_agent_pipeline` 是唯一管线入口（UI 和 CLI 都走它）。加一个 per-user 的 `threading.Lock` 即可。APScheduler 的 `BackgroundScheduler` 在同进程内触发，线程锁有效。 |
| **风险** | 低。① 锁泄漏：用 `try/finally` 保证释放。② 跨进程：若未来拆成多进程部署，线程锁失效——但 MVP 是单进程 Streamlit + APScheduler，不涉及。文档标注此假设即可。 |
| **工作量** | 0.5 人天。`execution_fence.py` ~20 行；`run_agent_pipeline` 入口改 ~8 行。 |
| **为何可最简** | 场景是「同进程内防止同 user 并发」，`threading.Lock` 就是最简且正确的解。不需要 Redis 分布式锁、不需要文件锁、不需要队列。`RLock` 都不需要（无重入场景）。 |

### P3 工具注册表 + ToolContext

| 维度 | 评估 |
|------|------|
| **可行性** | ✅ 中。`tools/fc_tools.py` 的函数签名是 `fetch_rss(source_urls, max_workers, timeout)` 这类纯函数，包装成 `AgentTool` 需要写一层 adapter。`AgentTool.execute(params, ctx)` 调用时把 params 解包传给原函数即可。 |
| **风险** | 中。① 包装层若参数映射写错，工具行为变化。② `ToolContext` 引入后，现有节点函数改为从 registry 取工具，调用方式变化大，回归面广。③ MVP 的工具是「节点内直接调用」而非「LLM function calling 动态选择」，注册表的「动态 surface」价值在 MVP 阶段尚未体现。 |
| **工作量** | 2 人天。`registry.py` ~40 行；8 个工具包装各 ~5 行；节点调用改造 + 测试。 |
| **为何不应急** | FeedLens 当前工具是固定集合，新增频率低。注册表的真正价值在「按 state 动态选工具表面」或「第三方插件接入」，这两个场景 MVP 都没有。建议 P3 推迟到有 2 个以上新采集源需求时再做，避免现在引入只用一次的抽象。 |

### P4 模型回退链

| 维度 | 评估 |
|------|------|
| **可行性** | ✅ 高。`LLMProvider` 已是 ABC，`DeepSeekProvider` 已实现。新建 `LLMRouter(list[LLMProvider])` 实现 ABC，`chat` 内部循环 try 即可。调用方 `_get_llm_provider()` 返回类型不变（都是 `LLMProvider`），调用代码零改动。 |
| **风险** | 低。① 回退 Provider 配置缺失时，Router 只有一个 Provider，行为等同现状。② 备用 Provider 与主 Provider 输出风格差异可能影响 planner 决策质量——但「有回退」远优于「全链路降级」。 |
| **工作量** | 0.5~1 人天。`LLMRouter` ~30 行；`_get_llm_provider` 改 ~10 行（读 config 的 fallback 段）。 |
| **为何可最简** | ABC 已定义好合约，Router 就是「列表 + 循环 try」，不需要探测机制、不需要健康检查、不需要自动标记不可用——那是 OpenClaw 的生产级特性，FeedLens MVP 用不上。最简 = 顺序尝试，全失败才抛。 |

### P5 Agent 间消息通道

| 维度 | 评估 |
|------|------|
| **可行性** | ⚠️ 中低。`FeedLensState` 加 `agent_messages` 字段简单，但「反向协作」需要改变 `invoke_sub_agent_node` 的调度逻辑——当前是按 `sub_agent_plan` 顺序执行，反向消息要求在循环内动态调整后续 plan，这会打破现有的「planner 预先编排」模型。 |
| **风险** | 高。① 改变调度模型易引入无限循环（Ranking↔Collection 互相请求补充）。② MVP 的 Collection→Ranking→Briefing 流水线已能工作，反向协作是「锦上添花」非「雪中送炭」。③ 与 P0 记忆接入有功能重叠——planner 有记忆后，很多「反向请求」可由 planner 主动预判。 |
| **工作量** | 2 人天 + 调试。state 字段、invoke 调度改造、防循环保护。 |
| **为何不建议现在做** | ROI 低、风险高、与 P0 部分重叠。等 P0/P1/P2 落地后，观察 planner 在记忆驱动下是否能自主预判跨 Agent 需求，再决定是否需要显式消息通道。很可能 P0 完成后 P5 就不必要了。 |

### 可行性总表

| 项 | 可行性 | 风险 | 工作量 | 最简方式 | 结论 |
|----|-------|------|-------|---------|------|
| P0 记忆接入 | 高 | 低 | 0.5~1d | ✅ 可最简 | 立即做 |
| P1 Hook 化 | 中高 | 中 | 2~3d | 需最小抽象 | 排第二批 |
| P2 执行栅栏 | 高 | 低 | 0.5d | ✅ 可最简 | 立即做 |
| P3 工具注册表 | 中 | 中 | 2d | 推迟 | 待需求触发 |
| P4 模型回退 | 高 | 低 | 0.5~1d | ✅ 可最简 | 排第二批 |
| P5 Agent 间消息 | 中低 | 高 | 2d+ | 不建议现在做 | 暂缓 |

---

## 二、实施优先级排序（推荐）

```
第一批（本周）：P0 记忆接入 + P2 执行栅栏
第二批（下周）：P1 Hook 化 + P4 模型回退
暂缓：P3 工具注册表（待需求触发）
暂缓：P5 Agent 间消息（P0 落地后重新评估必要性）
```

### 排序理由

**为什么 P0 + P2 一起做第一批**：

1. **零依赖、可并行**：P0 改 `main_agent.py`，P2 改 `pipeline_runner.py` + 新建 `execution_fence.py`，文件不重叠，可并行开发互不冲突。
2. **风险都低、都可最简**：P0 是接线现有记忆系统，P2 是加一把锁，都不动 LangGraph 图结构、不改 state 字段、不引入抽象。回归面最小。
3. **ROI 最高**：P0 直接补齐「planner 失忆」这个最大短板，让 agentic 能力立刻可见；P2 堵住并发写偏好的数据安全洞。一个是「能力提升」，一个是「安全兜底」，搭配合理。
4. **工作量小**：合计 1~1.5 人天，一个工作日内可完成 + 验证。

**为什么 P1 + P4 排第二批**：

1. **P1 依赖 P0 的记忆基础设施稳定后再动**：P1 要把 `observe_results_node` 的逻辑外提，最好在 P0 已验证记忆接入无误后进行，避免两处大改叠加调试。
2. **P4 独立但非紧急**：模型回退是「保险」，当前 DeepSeek 稳定时无感知价值，放第二批和 P1 一起做，集中测试一次。
3. **P1 风险中等，需要完整回归测试**：放第二批有充足时间跑 `test_main_agent.py` + `test_integration.py`。

**为什么 P3 暂缓**：

工具注册表的真正价值是「动态工具表面」和「第三方插件接入」，FeedLens MVP 工具是固定集合且新增频率低。在出现 2 个以上新采集源需求前，引入注册表是「为抽象而抽象」。等真实需求出现再做，届时能设计出更贴合实际接口的 registry。

**为什么 P5 暂缓且可能取消**：

P0 让 planner 有了记忆后，很多跨 Agent 协作场景能由 planner 主动预判（「上次 Ranking 后条目少，这次先让 Collection 补采某主题」）。P5 的显式消息通道可能变成冗余机制。建议 P0 落地后观察 1~2 周，若 planner 记忆驱动下仍频繁出现「子 Agent 才能发现的反向需求」，再启动 P5；否则取消。

---

## 三、MVP 实施步骤（覆盖 P0、P2，含 P1 预告）

### 改动文件总览

| 文件 | 改动 | P 项 |
|------|------|------|
| `agents/main_agent.py` | `_build_planner_context` 加记忆检索；`update_memory_node` 加决策经验写入；`PLANNER_SYSTEM_PROMPT` 加记忆指引 | P0 |
| `utils/execution_fence.py` | **新建**，per-user 锁 | P2 |
| `utils/pipeline_runner.py` | `run_agent_pipeline` 入口加栅栏 | P2 |

---

### P0 记忆接入 Planner

#### 改动 1：`agents/main_agent.py` 顶部导入（+1 行）

在现有 import 区（约第 20 行附近，`from tools import db_read, db_write` 之后）加：

```python
from utils.memory_manager import get_context, add_memory
```

#### 改动 2：`PLANNER_SYSTEM_PROMPT` 增加记忆指引（+6 行，约第 88 行 `## 输出格式` 之前插入）

```
## 历史经验参考

上下文中可能包含 memory 字段：
- memory.recent_turns: 最近几轮的本会话执行记录
- memory.relevant_history: 过往类似情况的处理经验（可能为空）

若历史经验显示某策略在类似状态下有效或无效，优先参考；若 memory 为空或当前状态与历史差异明显，以当前数据为准决策。
```

#### 改动 3：`_build_planner_context` 增加记忆检索（修改现有函数，约第 222 行）

```python
def _build_planner_context(state: FeedLensState) -> dict:
    """构建 planner 的 LLM 输入上下文。"""
    obs = state.get("observation_result", {})
    ranking_detail = state.get("ranking_detail", {})
    collected = state.get("collected_items", [])
    top_score = ranking_detail.get("top_score", 0)
    brief_quality = state.get("brief_quality", 0)

    # 记忆检索：用当前状态摘要作为 query，召回相关历史经验
    memory_query = f"采集{len(collected)}条 排序top{top_score:.2f} 简报质量{brief_quality:.2f}"
    try:
        memory_ctx = get_context(query=memory_query, n_recent=3, n_long_term=3)
        memory_block = {
            "recent_turns": memory_ctx.get("short_term", []),
            "relevant_history": [m.get("document", "") for m in memory_ctx.get("long_term", [])],
        }
    except Exception as e:
        print(f"[planner] 记忆检索失败，降级为空: {e}", flush=True)
        memory_block = {"recent_turns": [], "relevant_history": []}

    return {
        "trigger": state.get("trigger_type", "daily_briefing"),
        "goal": state.get("goal_text", ""),
        "react_cycle": state.get("react_cycle_count", 0),
        "collection": {
            "count": len(collected),
            "search_supplemented": state.get("search_supplemented", False),
        },
        "ranking": {
            "count": len(state.get("ranked_items", [])),
            "top_score": top_score,
        },
        "briefing": {
            "quality": brief_quality,
        },
        "last_observation": obs,
        "memory": memory_block,  # 新增
    }
```

> 改动量：新增约 12 行（记忆检索块）+ 1 行（memory 字段），其余是原结构。

#### 改动 4：`update_memory_node` 增加本轮决策经验写入（约第 593 行函数体开头，`print(f"[update_memory] 更新记忆...")` 之后插入）

```python
    # 写入本轮 planner 决策经验到记忆系统（供后续 planner 检索）
    try:
        obs = state.get("observation_result", {})
        add_memory(
            session_id=session_id,
            event="planner_decision",
            node_name="planner",
            content={
                "situation": f"采集{len(state.get('collected_items', []))} 排序top{state.get('ranking_detail', {}).get('top_score', 0):.2f} 简报质量{state.get('brief_quality', 0):.2f}",
                "decision": state.get("sub_agent_plan", []),
                "reason": planner_reason,
                "outcome": "retry_needed" if obs.get("needs_retry") else "ok",
                "trigger": state.get("trigger_type", ""),
            },
            status="completed",
        )
        print(f"[update_memory] planner 决策经验已写入记忆系统", flush=True)
    except Exception as e:
        print(f"[update_memory] 决策经验写入失败: {e}", flush=True)
```

> 改动量：新增约 14 行。放在现有「写入执行日志」逻辑之前，互不影响。

#### P0 验收方式

1. **记忆字段可见**：运行一次管线，在 `[planner] LLM 决策:` 日志前，`_build_planner_context` 返回的 context 应包含 `memory` 键。可在 `planner_node` 的 `print` 处临时加 `print(f"[planner] memory: {len(context['memory']['relevant_history'])} 条历史")` 验证。
2. **首次运行为空不报错**：首次运行时 ChromaDB 长期记忆为空，`relevant_history` 应为 `[]`，planner 正常决策不抛异常。
3. **二次运行有记忆**：连续运行两次管线，第二次运行时 `relevant_history` 应非空（含第一次的 `planner_decision` 压缩记录或短期记忆）。
4. **回归**：`python scripts/test_main_agent.py` 全部通过，行为与改动前一致（除新增 memory 字段外）。

---

### P2 执行栅栏防并发

#### 改动 1：新建 `utils/execution_fence.py`（~22 行）

```python
"""执行栅栏 — 同一用户的管线串行化，防止并发写偏好向量。"""

import threading


class ExecutionFence:
    """per-user 锁管理器。

    同一 user_id 的管线串行执行；不同 user_id 可并行。
    单进程内有效（Streamlit + APScheduler 同进程场景）。
    """

    def __init__(self):
        self._locks: dict[int, threading.Lock] = {}
        self._guard = threading.Lock()

    def acquire(self, user_id: int) -> threading.Lock:
        with self._guard:
            if user_id not in self._locks:
                self._locks[user_id] = threading.Lock()
            return self._locks[user_id]


# 全局单例
_fence = ExecutionFence()


def try_acquire_pipeline(user_id: int) -> threading.Lock | None:
    """尝试获取管线锁。返回锁对象则获取成功；返回 None 表示已有管线在跑。"""
    lock = _fence.acquire(user_id)
    if lock.acquire(blocking=False):
        return lock
    return None
```

#### 改动 2：`utils/pipeline_runner.py` 入口加栅栏（约第 20 行 import 区加导入，`run_agent_pipeline` 函数开头加锁检查）

import 区加：
```python
from utils.execution_fence import try_acquire_pipeline
```

`run_agent_pipeline` 函数体开头（`# 确保项目根目录在 sys.path 中` 之前）加：

```python
    # 执行栅栏：同一 user 的管线串行化，防止并发写偏好
    lock = try_acquire_pipeline(user_id if "user_id" in dir() else 1)
```

> 注意：`user_id` 在原函数中靠后才从 DB 读取，栅栏需要提前。调整方案：把 `user_id` 的读取提到函数最前，或在栅栏调用处先读。最简做法——栅栏用固定 user_id=1（MVP 单用户），代码如下：

```python
def run_agent_pipeline(trigger_type: str = "manual") -> dict:
    """运行完整 Agent 管线（采集 → 去重/排序 → 简报生成）。"""
    # 执行栅栏：MVP 单用户，user_id=1；防止定时/手动/破例推送并发
    lock = try_acquire_pipeline(1)
    if lock is None:
        print("[pipeline] 已有管线在执行，跳过本次触发", flush=True)
        return {"status": "skipped", "reason": "pipeline already running"}

    try:
        # 确保项目根目录在 sys.path 中
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)

        from agents.main_agent import build_main_agent
        # ... 原有全部逻辑保持不变 ...
        return {
            "status": result.get("status", "completed"),
            # ... 原有返回字段 ...
        }
    finally:
        lock.release()
```

> 改动量：`execution_fence.py` 22 行新建；`pipeline_runner.py` +6 行（import + try/finally 框架），原有逻辑整体缩进进 try 块。

#### P2 验收方式

1. **并发模拟**：用两个线程同时调用 `run_agent_pipeline`：
   ```python
   import threading
   from utils.pipeline_runner import run_agent_pipeline
   t1 = threading.Thread(target=run_agent_pipeline)
   t2 = threading.Thread(target=run_agent_pipeline)
   t1.start(); t2.start(); t1.join(); t2.join()
   ```
   预期：一个返回正常结果，另一个返回 `{"status": "skipped"}`，日志出现 `已有管线在执行，跳过本次触发`。
2. **正常单次不误锁**：单独调用 `run_agent_pipeline` 应正常完成，锁在 finally 释放，下次调用不受影响。
3. **异常路径释放**：模拟管线抛异常（如临时改坏 config），确认 finally 仍 `lock.release()`，下次调用不会被死锁。

---

### P1 Hook 化（第二批预告，本批不实施）

为便于第二批启动，这里给出最小 `HookRegistry` 设计（落地时再写）：

```python
# utils/hooks.py（第二批新建）
from typing import Callable

class HookRegistry:
    def __init__(self):
        self._hooks: dict[str, list[Callable]] = {}
    def register(self, name: str, fn: Callable) -> None:
        self._hooks.setdefault(name, []).append(fn)
    def run(self, name: str, ctx: dict) -> dict:
        for fn in self._hooks.get(name, []):
            result = fn(ctx)
            if isinstance(result, dict):
                ctx.update(result)
        return ctx

hooks = HookRegistry()
```

落地步骤（第二批）：
1. 把 `observe_results_node` 的阈值判断逻辑搬进 `default_observe_evaluate(ctx)`，`hooks.register("observe.evaluate", default_observe_evaluate)`。
2. `observe_results_node` 改为 `ctx = hooks.run("observe.evaluate", ctx)`，行为不变。
3. 同理迁移 `coordinator_reflect_node`（`reflect.check`）、`should_push_now`（`push.decide`）、`rank_items_node` 权重选择（`rank.weights`）。
4. 每个 hook 点迁移后跑对应测试，确认行为零回归。

**不在第一批做的原因**：P1 风险中等，需要完整回归测试周期；P0/P2 落地稳定后再动更安全。

---

## 四、风险控制与回归策略

| 改动 | 回归测试 | 风险点 | 缓解 |
|------|---------|-------|------|
| P0 | `test_main_agent.py` + 手动观察 planner 日志 memory 字段 | 记忆检索异常导致 planner 报错 | `get_context` 外包 try/except，降级空 memory |
| P2 | 并发模拟脚本 + 单次正常调用 | 锁泄漏导致后续全 skipped | `try/finally` 保证释放 |
| P1（第二批） | `test_main_agent` + `test_ranking_agent` + `test_integration` | 逻辑迁移漏分支 | 逐 hook 迁移，每个迁完即测 |

**统一原则**：每个 P 项完成后，先跑对应单元测试，再手动触发一次完整管线，确认 `[planner]`/`[observe]`/`[update_memory]` 日志正常，最后才进入下一个 P 项。

---

## 五、与方案文档的关系

本文档是 `借鉴OpenClaw改进方案.md` 的落地细化：
- 方案文档给出「做什么、为什么」
- 本文档给出「可行性、顺序、具体怎么改到代码行」
- 两文档配合使用，实施时以本文档代码指导为准

实施完成后，建议为 P0、P2 各补一份 ADR（`docs/技术决策记录/ADR-011-记忆接入Planner.md`、`ADR-012-执行栅栏.md`），记录决策理由和 trade-off。
