# FeedLens MVP 开发路线图

> **版本**：v3.0 | **日期**：2026-06-18 | **说明**：只定义阶段目标、交付物、关键任务、依赖关系和预估复杂度，不绑定周数

---

## 总览

```
阶段一 ──→ 阶段二 ──→ 阶段三 ──→ 阶段四 ──→ 阶段五
  骨架        采集+去重     排序+简报      推送+反馈+P1    集成测试
  数据模型     MCP Server    偏好排序       planner增强     优化交付
```

| 阶段 | 目标 | 复杂度 | 依赖 | 核心交付物数 |
|------|------|--------|------|-------------|
| 一 | 项目骨架 + 数据模型 | 中 | 无 | 6 |
| 二 | 信息采集 + 智能去重 | 高 | 阶段一 | 7 |
| 三 | 偏好排序 + 简报生成 | 高 | 阶段二 | 7 |
| 四 | 推送 + 反馈 + 记忆 + P1增强 | 高 | 阶段三 | 12 |
| 五 | 集成测试 + 优化 + 交付 | 中 | 阶段四 | 9 |

---

## 阶段一：项目骨架 + 数据模型

### 目标

搭建项目结构，定义数据模型，跑通 LangGraph 多 Agent 基础工作流骨架。

### 关键任务

- [ ] 创建项目目录结构（config / models / nodes / tools / utils / agents）
- [ ] SQLite 表结构初始化脚本（11 张表 + WAL 模式）
- [ ] ChromaDB 集合初始化（feed_items / user_preference / domain_knowledge）
- [ ] 主 Agent StateGraph 骨架（understand_intent → planner → invoke → observe → planner(再思考) → reflect → push → update_memory）
- [ ] 3 个子 Agent StateGraph 骨架（CollectionAgent / RankingAgent / BriefingAgent）
- [ ] 反馈子 Agent StateGraph 骨架（FeedbackAgent）
- [ ] 子 Agent 调用接口实现（invoke_sub_agent_node）
- [ ] bge-small-zh-v1.5 模型加载 + 推理验证
- [ ] LLMProvider 抽象接口 + DeepSeekProvider 实现

### 交付物与验收标准

| 交付物 | 验收标准 |
|--------|---------|
| 项目目录结构 | 符合模块化设计，包含 agents 子目录 |
| SQLite 初始化脚本 | 全部 11 张表创建成功，WAL 模式开启 |
| ChromaDB 集合初始化 | 3 个集合创建成功，embedding 函数配置正确 |
| 主 Agent StateGraph 骨架 | 7 个节点定义完成，ReAct 循环边连接正确，空实现可跑通 |
| 子 Agent StateGraph 骨架 | 4 个子 Agent 各有独立 StateGraph，主 Agent 可调度 |
| Embedding 模型加载 | 本地加载成功，推理速度 < 100ms/条 |
| LLMProvider 接口 | DeepSeekProvider 实现完成，预留 fallback 扩展点 |

### 技术要点

- 主 Agent 的 ReAct 循环：planner → invoke → observe → planner(再思考)，max_react_cycles=3
- 子 Agent 调用接口：invoke_sub_agent_node 根据 sub_agent_plan 选择执行对应子 Agent
- FeedLensState TypedDict 需包含 sub_agent_plan / react_cycle_count / 子 Agent 结果字段

---

## 阶段二：信息采集 + 智能去重

### 目标

实现采集 Agent 的完整工作流（RSS 采集 + 搜索补充 + 元数据提取 + ReAct 循环），实现排序 Agent 的去重功能。

### 关键任务

- [ ] `fetch_rss` FC 工具实现（feedparser 并行采集）
- [ ] `search_web` MCP Server (SSE :8100) 实现与部署
- [ ] `enrich_metadata` FC 工具实现（LLM 提取 category/keywords/importance）
- [ ] `normalize_items` FC 工具实现（字段标准化）
- [ ] 采集 Agent ReAct 循环实现（Think→Act→Observe→Think）
- [ ] `deduplicate` FC 工具实现（0.88 阈值 + 模糊区间 LLM 裁决）
- [ ] `item_relations` 表写入逻辑
- [ ] 空结果回退逻辑（去重后 < 3 条向主 Agent 报告）
- [ ] SSE 连接断线降级逻辑
- [ ] `calibrate_dedup.py` 校准脚本

### 交付物与验收标准

| 交付物 | 验收标准 |
|--------|---------|
| fetch_rss | 并行采集 3+ 个 RSS 源，feedparser 解析成功 |
| search_web MCP | 搜索 API 封装成功，SSE 流式返回，监听 :8100 |
| enrich_metadata + normalize_items | LLM 提取分类/关键词/重要性，字段统一格式化 |
| 采集 Agent ReAct 循环 | 判断采集策略→执行→评估→决定补充搜索，自主判断 |
| deduplicate | 0.88 阈值 + 模糊区间 LLM 裁决（上限 20 对，超限按 0.80 硬判） |
| item_relations | 去重关系正确记录（relation_type + dedup_method） |
| SSE 断线降级 | MCP SSE 断线→立即降级仅 RSS 模式，不阻塞流程 |
| calibrate_dedup.py | 标注样本→P/R/F1 曲线→最优阈值输出 |

---

## 阶段三：偏好排序 + 简报生成

### 目标

实现排序 Agent 的偏好排序功能（含 ReAct 循环），实现简报 Agent 的生成和审查功能。

### 关键任务

- [ ] `rank_items` FC 工具实现（多因子加权 + 动态权重切换）
- [ ] `vector_search` FC 工具实现（ChromaDB 偏好向量检索）
- [ ] `db_read` FC 工具实现（SQLite 读取反馈历史）
- [ ] 排序 Agent ReAct 循环实现（检索偏好→规划排序策略→去重+排序→评估→调参或Done）
- [ ] 时间衰减预筛（半衰期公式 τ=24h）
- [ ] Min-Max 归一化 + feedback_bias 逻辑
- [ ] 冷启动→偏好自适应切换逻辑（反馈数 >= 3 条）
- [ ] `generate_briefing` FC 工具实现（沿用 category/importance/keywords，只做摘要+分组）
- [ ] JSON → Markdown 渲染逻辑
- [ ] `reflect` FC 工具实现（brief_quality 评分 + 矛盾检查 + 重试判断）
- [ ] 简报 Agent StateGraph 实现（generate → reflect → 重试或Done）

### 交付物与验收标准

| 交付物 | 验收标准 |
|--------|---------|
| rank_items | 冷启动/有反馈两套权重动态切换 |
| 排序 Agent ReAct | 检索偏好→规划→去重+排序→评估→调参或Done |
| 记忆辅助排序 | 偏好向量参与 preference 因子；情节记忆仅冷启动提供初始权重参考值 |
| feedback_bias | 即时补偿偏好因子，EMA 更新后归零 |
| generate_briefing | 沿用 enrich_metadata 字段，items 按 category 分组、组内 importance 降序 |
| JSON→Markdown | 简报正确渲染，计数标注显示 |
| reflect | 四维评分 + 矛盾检测 + score<0.7 触发重试（最多2次） |

---

## 阶段四：推送 + 反馈 + 记忆 + P1 增强

### 目标

完成业务闭环，实现推送、反馈、反思、记忆管理，加入 P1 核心增强（planner 自主编排 + 反思增强 + 偏好更新 + 反馈子 Agent）。

### 关键任务

- [ ] `push_notification` MCP Server (stdio) 实现与部署
- [ ] APScheduler cron job 定时触发配置
- [ ] 重大事件破例推送逻辑（score > 0.85 且时效 < 2h）
- [ ] 主 Agent reflect 增强（三维度审查 + 矛盾检查）
- [ ] 反馈子 Agent 实现（feedback → update_preference → vector_add）
- [ ] 偏好正负分离实现（v_like / v_dislike）
- [ ] EMA 偏好更新逻辑
- [ ] 偏好自动清理逻辑（权重 < 0.1）
- [ ] 短期记忆管理（15 轮滑动窗口 + 超窗压缩）
- [ ] 冷启动→偏好自适应切换完整链路
- [ ] Streamlit 基础页面（首页 + Goal 设置 + RSS 管理 + 反馈 + 日志）
- [ ] 三级反馈 UI（like / dislike / irrelevant 按钮）

### 交付物与验收标准

| 交付物 | 验收标准 |
|--------|---------|
| push_notification MCP | 推送服务作为子进程运行 |
| APScheduler | cron job 每日定时触发主 Agent |
| 破例推送 | score > 0.85 且时效 < 2h 时立即推送 |
| 反馈子 Agent | 异步处理反馈，偏好向量更新 |
| 偏好正负分离 | v_like / v_dislike 分别维护于 ChromaDB |
| EMA 更新 | 偏好向量平滑更新，无剧烈波动 |
| 偏好清理 | 权重 < 0.1 自动清理 |
| 短期记忆 | 15 轮窗口 + 超窗压缩写入 ChromaDB |
| 权重切换 | 反馈数 >= 3 条时自动切换为偏好优先 |
| Streamlit | 5 个页面功能完整 |
| 三级反馈 UI | 三个按钮正确触发反馈子 Agent |

---

## 阶段五：集成测试 + 优化 + 交付

### 目标

端到端集成测试，性能优化，文档交付。

### 关键任务

- [ ] 端到端集成测试（Goal设置 → 主Agent ReAct循环 → 子Agent调度 → 简报推送 → 反馈闭环）
- [ ] structlog 结构化日志配置
- [ ] execution_logs + run_logs 日志记录
- [ ] 任务级错误隔离（单次失败不阻塞下次执行）
- [ ] 30 天数据清理定时任务
- [ ] 性能基准测试（单次 Agent 运行 < 60s）
- [ ] MVP 设计文档定稿
- [ ] README + 部署指南

### 交付物与验收标准

| 交付物 | 验收标准 |
|--------|---------|
| 端到端测试 | 从 Goal 到简报推送全流程跑通，含 ReAct 循环 |
| 结构化日志 | 全部节点日志结构化输出 |
| 错误隔离 | 单次失败不阻塞下次执行 |
| 数据清理 | 定期清理过期 raw_items 和 execution_logs |
| 性能基准 | 单次 Agent 运行 < 60s（采集 10 条 RSS 源） |
| 设计文档 | 定稿完成 |
| README | 包含环境配置、启动命令、依赖列表 |

---

## 关键依赖链

```
阶段一 ─┬─→ 阶段二 ───→ 阶段三 ───→ 阶段四 ───→ 阶段五
         │
         │  LangGraph 骨架是所有后续阶段的基础
         │
阶段一关键: 主Agent StateGraph + 子Agent 骨架 + 数据模型
阶段二关键: 采集Agent ReAct + MCP Server + 去重逻辑
阶段三关键: 排序Agent ReAct + 偏好排序 + 简报Agent
阶段四关键: 反馈闭环 + P1增强(planner+反思+偏好更新)
阶段五关键: 端到端测试 + 文档交付
```

## 风险与缓解

| 风险 | 影响 | 缓解策略 |
|------|------|---------|
| ReAct 循环无限递归 | 主 Agent 卡死 | max_react_cycles=3 强制退出 |
| 模糊区间 LLM 裁决过多 | 去重步骤极慢 | max_llm_adjudications=20 上限 |
| ChromaDB 并发写入冲突 | 偏好数据丢失 | feedback_workflow 串行化队列 |
| SSE 连接不稳定 | 搜索采集失败 | 断线降级仅 RSS 模式 |
| 冷启动反馈数不足 | 偏好排序无法切换 | Goal 文本提取初始偏好向量作为种子 |
