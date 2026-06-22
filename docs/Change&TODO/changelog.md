# FeedLens 变更日志

> MVP 已于 **2026-06-20** 完成交付（详见 `docs/FeedLens_MVP.md`）。
> 本文件记录 MVP 交付后的架构演进、重构和收尾变更。

---

## 2026-06-22 — 记忆系统二层化重构

### 背景

原三层记忆架构（短期 deque + 情节 SQLite + 长期 ChromaDB）中，短期记忆的 deque 15 轮窗口在进程重启后清零，跨天运行场景下失效；压缩流程（满 15 条 → LLM 压缩 → 写入 ChromaDB）引入不必要的延迟。

### 改动

- 删除 `ShortTermMemory`（deque）和 `compress_window` 压缩流程
- 每次 `update_memory_node` 执行后直接 LLM 摘要写入 ChromaDB
- `get_context()` 改为读情节（近7天 SQLite）+ 长期（语义检索 ChromaDB）
- 架构图更新为 v2（`FeedLens_Simple_Architecture2.drawio`）

### 改动文件

`utils/memory_manager.py`、`agents/state.py`、`agents/main_agent.py`、`scripts/test_main_agent.py`、`scripts/test_memory_manager.py`、`docs/architecture/FeedLens_Simple_Architecture2.drawio`

### 真机验证

```
[planner] memory: 情节(近7天)=10条 长期(语义)=2条
[update_memory] planner 决策经验已写入记忆系统（SQLite + ChromaDB）
[pipeline] 完成: collected=56, ranked=10, quality=0.49
```

### 已知缺口（暂缓，非阻塞）

| # | 事项 | 状态 |
|---|------|------|
| 1 | dedup_hard_threshold 0.80 真门限 | 暂缓 — 当前两级阈值够用 |
| 2 | EMA α=0.3 语义确认 | 暂缓 — 代码与注释一致，无 Bug |

---

## 2026-06-21 — 架构演进 P0/P1/P2/P4 落地

详见 `docs/架构演进/借鉴OpenClaw改进方案.md` 和 `docs/架构演进/可行性分析与MVP实施步骤.md`。

### P0 记忆接入 Planner ✅

- `agents/main_agent.py`（+45 行）：`_build_planner_context` 注入 `get_context()` 检索结果；`update_memory_node` 调用 `add_memory()` 写入决策经验。
- 形成「决策 → 记忆 → 下次决策参考」闭环。

### P1 Hook 化策略点 ✅

- 新增 `utils/hooks.py`（46 行）：`HookRegistry` + 全局单例
- 4 个 hook 点：`observe.evaluate` / `reflect.check` / `push.decide` / `rank.weights`
- 测试 24/24 + 8/8 零回归

### P2 执行栅栏防并发 ✅

- 新增 `utils/execution_fence.py`（44 行）：per-user `threading.Lock`
- `pipeline_runner.py` 入口加锁，并发安全

### P4 模型回退链 ✅

- `utils/llm_provider.py` 新增 `LLMRouter`：顺序尝试多 Provider，全失败才抛异常
- `config/config.yaml` 新增 `fallback` 注释段

### 附带修复

- `scripts/test_main_agent.py`：9/19 → 24/24（重写）
- `understand_intent` 返回格式兼容修复
- 既存问题修复：Dashboard 页注册、测试 mock 不匹配、feedback_count 告警、docstring 乱码、SQLite 表名 goals→users

### 新增工具

- `scripts/observe_planner.py`：单独运行 planner_node 观察预判能力，支持 5 个典型场景

---

## 文档版本

| 版本 | 日期 | 说明 |
|------|------|------|
| v2.0 | 2026-06-22 | 重写：以 MVP 交付（6/20）为分界线，仅记录交付后变更 |

`[via: Codex]`
