# FeedLens Agentic 升级规划1（MVP 后架构增强）

> 创建时间：2026-06-22
> 范围：MVP 交付（2026-06-20）→ 升级规划2（2026-06-22）之间的所有架构演进
> 状态：✅ 已全部实施完成

---

## 一、规划背景

### 1.1 起点：MVP 交付状态

2026-06-20，FeedLens 完成 MVP 交付（`main` 分支，tag `MVP`），具备以下能力：

| 维度 | MVP 状态 |
|------|---------|
| **主流程** | 8 节点 LangGraph DAG，6/8 边硬编码 |
| **子 Agent** | Collection / Ranking / Briefing 三个 StateGraph，内部固定 DAG |
| **记忆系统** | 三层架构（短期 deque + 情节 SQLite + 长期 ChromaDB），但 Planner 未接线 |
| **LLM 调用** | 单一 DeepSeek Provider，无容错 |
| **并发控制** | 无，定时触发与手动触发可能同时跑 |
| **策略点** | 硬编码在节点函数内，不可扩展 |
| **工具调用** | 代码直接调用函数，LLM 看不到工具列表 |
| **ADRs** | 001~010 共 10 项技术决策 |

### 1.2 核心问题识别

MVP 虽然在功能上完整跑通了「采集→排序→简报→推送」链路，但在以下维度存在明显短板：

| 问题 | 表现 | 影响 |
|------|------|------|
| **记忆未闭环** | Planner 每轮从零开始，不参考历史决策 | 重复犯错、用户偏好无法累积 |
| **LLM 单点故障** | DeepSeek 挂了管线直接中断 | 生产可用性无保障 |
| **无并发防护** | 定时触发撞上手动触发可能产生脏数据 | 稳定性风险 |
| **策略硬编码** | 排序权重、质量阈值等写死在代码里 | 扩展性差、调参需改代码 |
| **记忆架构冗余** | 三层记忆中 deque 短期记忆进程重启清零 | 跨天场景失效 |

### 1.3 设计原则

贯穿所有演进决策的核心原则：

1. **最简可行**：能用现有基础设施解决的问题，不引入新抽象
2. **渐进增强**：改动面最小化，不碰 LangGraph 图、不改 state 结构
3. **降级路径**：所有新增能力都有 try/except 降级，不可用时行为等同改动前
4. **等待需求触发**：功能等真实需求出现再做，避免为抽象而抽象

---

## 二、改动全景

### 2.1 优先级划分

| 优先级 | 项目 | 说明 | 状态 |
|--------|------|------|------|
| **P0** | 记忆接入 Planner | 让 Planner 参考历史决策经验 | ✅ 完成 |
| **P1** | Hook 化策略点 | 将硬编码策略点抽成可替换 Hook | ✅ 完成 |
| **P2** | 执行栅栏防并发 | per-user 非阻塞锁防同用户并发 | ✅ 完成 |
| **P3** | 工具注册表 | 工具 schema 化供 LLM 选择 | ⏸️ 暂缓 |
| **P4** | 模型回退链 | LLM Provider 容错链 | ✅ 完成 |
| **P5** | Agent 间消息通道 | 子 Agent 间直接通信 | ⏸️ 暂缓 |

### 2.2 时间线

```
2026-06-20  10:14  MVP Initial Commit（132 files）
2026-06-20  22:57  MVP 文档整理，tag MVP 交付
2026-06-21  10:40  创建 develop 分支
2026-06-21  20:00  P0+P1+P2+P4 集中落地（commit 3cfd567）
2026-06-22  10:00  记忆系统二层化重构（commit 25a00eb）
2026-06-22  17:04  最终迭代（commit 05f5c2，当前 HEAD）
```

---

## 三、P0：记忆接入 Planner

### 3.1 问题

Planner 每轮从零开始编排子 Agent 顺序，不参考任何历史决策经验：
- 用户偏好无法累积（用户说"游戏新闻优先"但下轮 Planner 忘了）
- 失败模式反复重演（上次搜索关键词无效，本轮又用同样的词）
- 成功的策略无法复用（上次采集+搜索组合效果好，本轮不知道）

### 3.2 方案

**核心思路**：最简接线，不新建任何抽象类，直接调现有 `get_context()` / `add_memory()`。

**改动文件**：`agents/main_agent.py`（+45 行）

**改动 1**：`_build_planner_context` 注入记忆检索结果

```python
# 在 Planner 编排前，注入近期决策经验
memory_context = get_context(user_id=state["user_id"], goal_category=state["goal_category"])
# memory_context 包含：
#   情节记忆(近7天 SQLite): 最近 10 条决策及结果
#   长期记忆(语义检索 ChromaDB): 语义相似的 2 条历史经验
```

**改动 2**：`update_memory_node` 调用 `add_memory()` 写入决策经验

```python
# 管线完成后，将本轮的 Planner 决策及结果写入记忆
add_memory(
    user_id=state["user_id"],
    entry={
        "decision": state.get("plan"),           # Planner 的编排策略
        "result": {
            "collected": len(state.get("raw_items", [])),
            "ranked": len(state.get("ranked_items", [])),
            "quality": state.get("quality_score", 0)
        }
    }
)
```

**改动 3**：`PLANNER_SYSTEM_PROMPT` 增加记忆利用指引

```
你可以参考以下历史决策经验：
{memory_context}

请根据历史经验调整编排策略：
- 如果某类策略历史上效果好，优先复用
- 如果某类策略历史上效果差，主动规避
- 如果没有相关经验，按默认逻辑编排
```

### 3.3 效果

```
改造前: Planner(本轮状态) → 输出 plan
改造后: Planner(本轮状态 + 记忆上下文) → 输出 plan → 执行 → 结果写入记忆
         ↑__________________________________________________________↓
                      「决策 → 记忆 → 下次决策参考」闭环
```

### 3.4 关键决策：拒绝过度抽象

当时考虑过新建 `ContextEngine` 抽象类做记忆上下文管理，最终拒绝了：

| 选项 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 新建 ContextEngine 类 | 封装清晰、可复用 | 新增抽象层、改动面大 | ❌ 拒绝 |
| 直接调现有函数 | 改动最小、零新增文件 | 代码耦合稍高 | ✅ 采纳 |

**理由**：`get_context()` 和 `add_memory()` 已经封装好了接口，Planner 只需要接线，不需要另一层抽象。等有 3+ 个 Agent 需要不同上下文策略时再抽象不迟。

---

## 四、P1：Hook 化策略点

### 4.1 问题

系统中有多处策略逻辑硬编码在节点函数内：

| 策略点 | 位置 | 硬编码内容 |
|--------|------|-----------|
| `observe.evaluate` | `observe_results` 节点 | 质量评分算法、阈值判断 |
| `reflect.check` | `coordinator_reflect` 节点 | 是否重试的判断逻辑 |
| `push.decide` | 推送前逻辑 | 是否推送的条件 |
| `rank.weights` | `ranking_agent` | 冷/热权重切换逻辑 |

调参需要改代码、重新部署，无法运行时动态调整。

### 4.2 方案

**新增文件**：`utils/hooks.py`（46 行）

**设计**：`HookRegistry` 类（dict + run 循环）+ 全局单例 `hooks`

```python
class HookRegistry:
    def __init__(self):
        self._hooks: dict[str, list[Callable]] = {}

    def register(self, name: str, fn: Callable):
        """注册一个 Hook 函数"""
        self._hooks.setdefault(name, []).append(fn)

    def run(self, name: str, **context) -> dict:
        """运行指定 Hook 点的所有注册函数"""
        results = {}
        for fn in self._hooks.get(name, []):
            results[fn.__name__] = fn(**context)
        return results

# 全局单例
hooks = HookRegistry()
```

**4 个 Hook 点**：

```python
# 1. 质量评估后
hooks.run("observe.evaluate", score=quality_score, items=ranked_items, state=state)

# 2. 协调者反思时
hooks.run("reflect.check", quality=quality_score, cycle=cycle_count, state=state)

# 3. 推送决策
hooks.run("push.decide", briefing=briefing_text, quality=quality_score, state=state)

# 4. 排序权重选择
hooks.run("rank.weights", goal_category=goal_category, user_prefs=preferences)
```

**迁移策略**：
- 硬编码逻辑原样搬进**默认 Hook 实现**（注册到 Hook 点）
- 节点改为 `hooks.run("hook_name", context)`
- 行为零回归——默认 Hook 输出与原来硬编码逻辑完全一致
- 后续扩展只需 `hooks.register("observe.evaluate", my_custom_logic)` 即可替换策略

### 4.3 验证

```
scripts/test_main_agent.py: 24/24 通过（含新增 Hook 相关用例）
scripts/test_hooks.py: 8/8 通过
```

---

## 五、P2：执行栅栏防并发

### 5.1 问题

FeedLens 有定时触发（scheduler）和手动触发（UI 按钮）两种启动方式。同用户可能同时触发两条管线：

```
定时触发(用户A) → pipeline 正在采集 RSS
手动触发(用户A) → pipeline 也在采集 RSS → 重复数据、状态混乱
```

### 5.2 方案

**新增文件**：`utils/execution_fence.py`（44 行）

**设计**：per-user `threading.Lock`，非阻塞获取

```python
import threading

_user_locks: dict[str, threading.Lock] = {}
_global_lock = threading.Lock()

def try_acquire_pipeline(user_id: str) -> bool:
    """尝试获取管线执行权，失败则说明已有管线在跑"""
    with _global_lock:
        if user_id not in _user_locks:
            _user_locks[user_id] = threading.Lock()
        lock = _user_locks[user_id]
    return lock.acquire(blocking=False)

def release_pipeline(user_id: str):
    """释放管线执行权"""
    with _global_lock:
        lock = _user_locks.get(user_id)
    if lock:
        lock.release()
```

**改动文件**：`utils/pipeline_runner.py` 入口加锁

```python
def run_pipeline(user_id: str, trigger: str):
    if not try_acquire_pipeline(user_id):
        logger.warning(f"[fence] 用户 {user_id} 已有管线在跑，跳过本次 {trigger}")
        return {"status": "skipped", "reason": "already_running"}
    try:
        # 原有管线逻辑
        ...
    finally:
        release_pipeline(user_id)
```

### 5.3 关键决策：拒绝分布式锁

| 选项 | 适用场景 | 本系统需要吗 | 结论 |
|------|---------|-------------|------|
| `threading.Lock` | 同进程内 | ✅ FeedLens 是单进程应用 | ✅ 采纳 |
| Redis 分布式锁 | 跨进程/跨机器 | ❌ 无此场景 | ❌ 过度设计 |
| 文件锁 | 跨进程 | ❌ 无此场景 | ❌ 过度设计 |
| 消息队列 | 高并发排队 | ❌ 无此场景 | ❌ 过度设计 |

**关键设计**：非阻塞获取（`blocking=False`），定时触发撞上正在跑的管线时**跳过而非排队**，避免任务堆积。

---

## 六、P4：模型回退链

### 6.1 问题

MVP 仅使用单一 DeepSeek Provider。如果 DeepSeek API 挂了、限流了、返回异常了，整条管线中断，用户得不到简报。

### 6.2 方案

**改动文件**：`utils/llm_provider.py`

**新增**：`LLMRouter` 类，实现 `LLMProvider` ABC

```python
class LLMRouter(LLMProvider):
    """LLM Provider 路由器，按顺序尝试各 Provider，自动降级"""
    
    def __init__(self, config: dict):
        self._providers: list[LLMProvider] = []
        for provider_config in config.get("fallback", []):
            provider = create_provider(provider_config)
            self._providers.append(provider)
    
    def chat(self, messages, **kwargs):
        last_error = None
        for provider in self._providers:
            try:
                return provider.chat(messages, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(f"[llm_router] Provider {provider.name} 失败: {e}，尝试下一个")
                continue
        raise RuntimeError(f"所有 LLM Provider 均已失败，最后错误: {last_error}")
```

**配置**：`config/config.yaml` 新增 fallback 段

```yaml
llm:
  primary:
    provider: deepseek
    model: deepseek-chat
    api_key: ${DEEPSEEK_API_KEY}
  fallback:
    - provider: xiaomi
      model: mimo-v2.5
      api_key: ${XIAOMI_API_KEY}
```

### 6.3 关键决策

| 设计点 | 决策 | 理由 |
|--------|------|------|
| 回退策略 | 顺序 try，全失败抛异常 | 最简实现，无需健康检查 |
| 健康检查 | 不做 | 无状态存储，做了也是浪费 |
| 探测机制 | 不做 | 实际调用即探测 |
| 权重路由 | 不做 | 无负载均衡需求 |
| 未配置 fallback | 行为等同改动前 | 退化路径完整 |

---

## 七、记忆系统二层化重构（2026-06-22）

### 7.1 问题

MVP 的三层记忆架构存在设计冗余：

```
原架构（三层）：
  短期记忆(deque, 15轮窗口) → 满15条 → LLM压缩 → 长期记忆(ChromaDB)
  情节记忆(SQLite, 永久)
```

- **短期记忆 deque 进程重启清零**：跨天运行时，之前积累的上下文全丢失
- **压缩流程引入延迟**：满 15 条才压缩，导致「压缩—写入 ChromaDB」成为阻塞点
- **三层中有两层做相似的事**：短期（最近上下文）vs 情节（时间窗口）功能重叠

### 7.2 方案

**改为二层架构**：

```
新架构（二层）：
  情节记忆(SQLite, 近7天) → 每次 update_memory 直接 LLM 摘要写入 ChromaDB
  长期记忆(ChromaDB, 语义检索)
```

**具体改动**：

| 操作 | 改动 |
|------|------|
| 删除 | `ShortTermMemory` 类（deque） |
| 删除 | `compress_window` 压缩流程 |
| 修改 | `update_memory_node` 每次执行后直接 LLM 摘要写入 ChromaDB |
| 修改 | `get_context()` 改为读「情节(近7天 SQLite) + 长期(语义检索 ChromaDB)」 |
| 更新 | 架构图 v1 → v2 |

**改动文件**：`utils/memory_manager.py`、`agents/state.py`、`agents/main_agent.py`、测试脚本、架构图

### 7.3 真机验证

```
[pipeline] 用户 default 触发: manual
[planner] memory: 情节(近7天)=10条 长期(语义)=2条
[planner] 编排策略: 采集→排序→简报
[collection] 采集完成: 56 条
[ranking] 排序完成: 10 条
[briefing] 简报生成完成: quality=0.49
[update_memory] planner 决策经验已写入记忆系统（SQLite + ChromaDB）
[pipeline] 完成: collected=56, ranked=10, quality=0.49
```

---

## 八、暂缓项目（P3 + P5）

### 8.1 P3：工具注册表 — 暂缓

| 维度 | 说明 |
|------|------|
| **原计划** | 将所有工具包装为 OpenAI function calling schema，让 LLM 能自主选择工具 |
| **暂缓理由** | 当前工具是固定集合（fetch_rss / search_web / deduplicate / rank / generate_briefing），新增频率低；注册表真正价值在「动态工具表面」和「第三方插件」，MVP 无此需求 |
| **触发条件** | 等有 2+ 个新采集源需求时再做 |

> **注意**：升级规划2 中已将 P3 纳入为 Phase 1（工具层扁平化），届时一并实施。

### 8.2 P5：Agent 间消息通道 — 暂缓

| 维度 | 说明 |
|------|------|
| **原计划** | 子 Agent 间通过消息通道直接通信，而非通过 state 中转 |
| **暂缓理由** | ROI 低、风险高、与 P0 记忆接入部分重叠。P0 让 planner 有记忆后，很多跨 Agent 协作可由 planner 主动预判 |
| **后续** | 观察 1-2 周再评估，可能永久取消 |

---

## 九、与升级规划2 的衔接

升级规划1 解决的是 **「架构健壮性」** 问题：

| 规划1 成果 | 解决的痛点 |
|-----------|-----------|
| 记忆接入 Planner | Planner 不再从零开始，具备学习能力 |
| Hook 化策略点 | 策略可扩展、可替换 |
| 执行栅栏 | 并发安全 |
| 模型回退链 | LLM 调用容错 |
| 记忆二层化 | 跨天稳定、无冗余 |

升级规划2 将解决 **「Agent 自主性」** 问题：

| 规划2 目标 | 解决的痛点 |
|-----------|-----------|
| LLM 动态路由 | 流程不再硬编码，Agent 自主决定下一步 |
| 子 Agent ReAct 化 | 阶段内 LLM 自主调用工具 |
| 工具层扁平化 | LLM 能看到并选择所有工具 |

```
规划1（已完成）                        规划2（待实施）
┌─────────────────────┐              ┌─────────────────────┐
│ 架构健壮性增强        │    ────►     │ Agentic 自主性升级    │
│ · 记忆闭环           │              │ · LLM 动态路由        │
│ · Hook 化            │              │ · 阶段内 ReAct        │
│ · 并发防护           │              │ · 工具扁平化          │
│ · 模型容错           │              │ · 完全自主决策        │
└─────────────────────┘              └─────────────────────┘
```

---

## 十、新增技术决策记录

| 编号 | 名称 | 决策要点 |
|------|------|---------|
| ADR-011 | 记忆接入 Planner | 最简接线，直接调现有函数，拒绝 ContextEngine 抽象 |
| ADR-012 | 执行栅栏 | per-user threading.Lock，拒绝 Redis 分布式锁 |
| ADR-013 | 模型回退链 | LLMRouter 顺序 try，拒绝健康检查/探测 |

---

## 十一、文件改动清单

| 文件 | 改动类型 | 对应项目 |
|------|---------|---------|
| `agents/main_agent.py` | 修改（+45行） | P0 记忆接入 |
| `utils/hooks.py` | **新建**（46行） | P1 Hook 化 |
| `utils/execution_fence.py` | **新建**（44行） | P2 执行栅栏 |
| `utils/llm_provider.py` | 修改 | P4 模型回退 |
| `config/config.yaml` | 修改（+fallback 段） | P4 模型回退 |
| `utils/memory_manager.py` | 重写 | 记忆二层化 |
| `agents/state.py` | 修改 | 记忆二层化 |
| `scripts/test_main_agent.py` | 重写 | 测试适配 |
| `docs/architecture/*.drawio` | 更新 | 架构图 v2 |
| `docs/技术决策记录/ADR-011~013.md` | **新建** | 技术决策记录 |
| `docs/Change&TODO/changelog.md` | 更新 | 变更日志 |
