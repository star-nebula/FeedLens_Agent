# ADR-002: 多 Agent 自主规划架构 vs 单 Agent 线性流程

| 元数据 | |
|--------|--------|
| **状态** | 已采纳 |
| **日期** | 2026-06-18 |
| **决策者** | 项目决策组（用户对齐确认） |
| **来源** | Prompt 核心差异化要求 |

## 上下文

Prompt 的核心定位是「自主规划 + 定时执行 + 个性化筛选」的 Agent 系统，且明确提到「子 Agent」作为工具注册类型。之前的设计文档 v2.0 采用单 Agent 线性流水线（10 节点固定顺序），planner 放在 P1（增强），没有真正的自主决策能力。

用户明确反馈：
1. 需要的是自主规划的 Agent，不是工作流 Agent
2. Prompt 明确提到子 Agent 作为工具注册类型
3. 重大决策需要与用户对齐，而非擅自裁决

可选方案：
- **多 Agent 自主规划**：主 Agent (Coordinator + Planner) + 3 子 Agent（采集/排序/简报）+ 反馈子 Agent，planner 自主编排子 Agent 调用顺序和次数
- **单 Agent + planner 增强节点**：10 节点线性流水线，planner 在 P1 作为条件分支增强
- **单 Agent + ReAct 仅在关键节点**：只在 collect_sources 和 rank_items 有 ReAct 循环

## 决策

**采用多 Agent 自主规划架构**。

- 主 Agent 作为 Coordinator + Planner，通过 **规则优先 + LLM 兜底** 的混合路由编排子 Agent
  - 正常流程由 `_rule_based_router_decision()` 确定性规则路由覆盖，无需 LLM 参与
  - 仅当规则无法覆盖（如 `needs_retry` 或 `overall_pass=false`）时才回退到 planner 让 LLM 重新编排
- 采集 Agent 支持双模式：**Pipeline 模式**（默认，无 LLM，固定流程）和 **ReAct 模式**（LLM 自主决策）
- 排序 Agent 有 ReAct 循环（自主判断去重+排序流程）
- 简报 Agent 有内部 ReAct 循环（generate → quality_check → 迭代，max_turns=4，max_retries=2）
- 反馈子 Agent 异步运行
- planner 为 P0 核心闭环，不是 P1 增强

## 理由

1. **Prompt 核心差异化**：自主规划是核心卖点，不是增强。把核心差异化放到 P1 意味着 MVP 交付时没有展示核心价值
2. **Prompt 明确要求子 Agent**：「工具注册包含 skills（渐进式加载）、MCP、子 Agent」
3. **ReAct 模式要求**：Prompt 的规划层要求 ReAct 循环（思考→行动→观察→再思考），单 Agent 线性流程没有 ReAct
4. **简历项目差异化**：多 Agent 自主规划比 cron + pipeline 更有技术深度和展示价值

## 影响

- 架构从 v2.0 的单 Agent 线性流水线重构为 v3.0 的多 Agent 自主规划
- planner 从 P1 提升到 P0 核心闭环
- 工具注册类型从 2 类（FC + MCP）变为 3 类（子 Agent + MCP + FC）
- State TypedDict 增加 sub_agent_plan / react_cycle_count / 子 Agent 结果字段
- 开发复杂度增加（需要实现 4 个独立 StateGraph + 调度接口 + ReAct 循环）
- **v2.2.0 演进**：路由机制从"LLM 全动态"优化为"规则优先 + LLM 兜底"，正常流程节省 6 次 router LLM 调用；采集默认 Pipeline 模式（采集 LLM -100%）；简报增加内部 ReAct 循环

## 风险与缓解

| 风险 | 缓解策略 |
|------|---------|
| 开发复杂度增加 | 子 Agent 内部流程简单（3-4 节点），主 Agent 调度接口明确 |
| ReAct 循环可能无限递归 | 设置 max_react_cycles=3，超过强制进入 update_memory |
| 子 Agent 通信开销 | LangGraph 子图通过 State 传递数据，无 IPC 开销 |
| LLM 路由不稳定 | v2.2.0 引入规则优先路由，仅异常场景回退 LLM，大幅降低路由不确定性 |
