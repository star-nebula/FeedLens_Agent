# ADR-011: 记忆接入 Planner — planner 从失忆决策到经验驱动

| 元数据 | |
|--------|--------|
| **状态** | 已采纳 |
| **日期** | 2026-06-21 |
| **决策者** | 项目决策组 |
| **来源** | 架构演进 P0（可行性分析与MVP实施步骤.md）|

## 上下文

MVP 阶段 planner 每次决策都从零开始，无法参考过往轮次的执行经验。典型的失忆表现：
- 上次「采集不足→补充搜索」成功补救，但本次采集不足时 planner 不会主动复用这个经验
- 上次「简报条目少→放宽排序窗口」有效，本次遇到相同状态仍需重新摸索
- 重复出现的状态-决策组合无法形成模式记忆

矛盾点在于：`utils/memory_manager.py` 的记忆系统早已实现（`get_context` 短期+长期检索、`add_memory` 写入），但从未接到 planner。基础设施就绪，只差接线。

## 决策

**直接调用现有 `get_context` / `add_memory`，不新建任何抽象层。**

- `_build_planner_context` 中用状态摘要作 query 调 `get_context(query, n_recent=3, n_long_term=3)`，结果注入 `memory` 字段
- `update_memory_node` 每轮调 `add_memory(event="planner_decision", ...)` 写入本轮经验
- `PLANNER_SYSTEM_PROMPT` 增加记忆指引段：有则参考、空则以当前数据为准
- 记忆检索异常时 try/except 降级为空 memory，不影响决策

## 理由

**最简方式 = 直接接线，不引入 ContextEngine 类。**

1. 记忆系统的合约（`get_context` 返回 dict、`add_memory` 写入）已稳定，再包一层 ContextEngine 是对已稳定接口的冗余封装
2. planner 上下文是纯函数 `_build_planner_context(state) -> dict`，插一段记忆检索不需要改 state 结构、不动 LangGraph 图、不引入新类——改动面最小
3. 降级路径天然存在：`get_context` 内部已有 try/except 返回空列表，首次运行长期记忆为空时 planner 拿到空 `memory` 字段，prompt 已写「无历史时以当前数据为准」，行为等同改动前
4. 任何额外抽象（ContextEngine、记忆权重、上下文压缩）都是「为未来可能的复杂度」设计，而 MVP 阶段的价值恰恰在于验证「记忆驱动决策」这个假设本身是否成立——先用最简方式跑通假设，再谈抽象

## 影响

- planner 上下文新增 `memory.recent_turns`（本会话近 3 轮）和 `memory.relevant_history`（长期记忆召回）两个字段
- 每轮管线结束时多一次 `add_memory` 写入，ChromaDB 长期记忆逐步积累
- 记忆系统不可用时静默降级，planner 仍可正常决策
- planner 决策质量随记忆积累逐步提升，但提升是渐进的、非线性的——首次运行无感知，连续运行后才显现

## 后续演进

- **P5 评估**：本 ADR 落地后观察 1-2 周，记录 planner 在记忆驱动下是否能主动预判跨 Agent 需求（如「上次 Ranking 条目少，这次先补采某主题」）。若能，P5 Agent 间消息通道可取消；若频繁出现子 Agent 才能发现的反向需求，再启动 P5
- **记忆质量治理**：若长期记忆噪音过多导致召回质量下降，再考虑给 `add_memory` 写入加过滤（如只写入 outcome=retry_needed 的经验）。当前不过滤，先积累数据再判断
- **上下文压缩**：若 `recent_turns` 过长挤占 token，再考虑压缩。当前 n_recent=3 足够小，不急

## 相关文档

- `docs/架构演进/借鉴OpenClaw改进方案.md` — P0 设计来源
- `docs/架构演进/可行性分析与MVP实施步骤.md` — 可行性分析与代码级实施
- 对比 OpenClaw：OpenClaw 有独立的 ContextEngine，FeedLens 判断 MVP 阶段不需要这层抽象
