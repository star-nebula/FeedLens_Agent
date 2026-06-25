# FeedLens Agentic 升级 Changelog

## v2.2.0 — 去重链路修复与摘要清洗增强（2026-06-25）

> 修复跨批次去重失效问题，优化去重算法性能，增强摘要清洗能力。

### 子方案 A：历史去重纯标题编码 + 全量写入（3af4404 → 6be31d6）

- **问题**：预过滤仅写入 `ranked_items`（top 10）到 ChromaDB，导致 84% 条目无法被跨批次拦截，每次采集固定 63 条
- **修复**：
  1. **写入端**（`agents/main_agent.py`）：`update_memory_node` 写入范围从 `ranked_items` → `collected_items`（全量），编码文本从 `title + summary` → 纯 `title`
  2. **查询端**（`agents/collection_agent.py`）：`_prefilter_against_history` 编码文本从 `title + summary` → 纯 `title`，与写入端保持一致
  3. **测试脚本**（`scripts/test_prefilter_real.py`）：同步编码改为纯标题
- **设计决策**：纯标题编码原因——
  - 预过滤是 `feed_items` 集合唯一实际读取场景，标题语义足够判断重复
  - summary 在向量去重中可能引入噪音，稀释标题核心语义
  - 两边统一编码保证向量空间一致
- **兼容性**：`collected_items` 为空时自动回退到 `ranked_items`，无破坏性
- **涉及文件**：`agents/main_agent.py`, `agents/collection_agent.py`, `scripts/test_prefilter_real.py`

### 子方案 B：去重算法批量 LLM 裁决（8810282）

- **问题**：批次内去重（`tools/fc_tools.py` 的 `deduplicate()`）对中间相似度区间的条目逐对调用 LLM，HTTP 往返次数多
- **修复**：实现两阶段去重策略
  1. 高相似度区间 → 直接硬判为重复（无 LLM 调用）
  2. 中间区间 → 收集所有待裁决 pair，**一次性批量调用 LLM** 裁决
- **溢出保护**：超限部分硬判为重复，避免单次调用过大
- **兼容性**：保留原有单对裁决函数 `llm_adjudicate_duplicates` 作为兼容支持
- **涉及文件**：`tools/fc_tools.py`

### 子方案 C：摘要清洗增强 + Planner 容错 + VectorStore 单例（3af4404）

- **摘要清洗**（`agents/briefing_agent.py`, `ui/pages/home_page.py`）：
  - 新增 `_clean_summary` 函数，去除作者署名、查看全文、HTML 标签等噪音
  - 智能截断，优先在句号处断开
  - UI 层增加摘要清洗作为最后一道防线
  - 摘要长度限制从 100 → 500 字符（`7b42078`）
- **Planner 容错**（`agents/main_agent.py`）：
  - 实现三层降级 JSON 解析策略（直接解析 → regex 提取 → 兜底修复）
  - 添加 JSON 格式错误的自动修复逻辑
  - 规范输出约束，禁止 reason 字段使用特殊字符
- **VectorStore 单例**（`models/vector_store.py`）：
  - 避免同一持久化目录创建多个实例导致数据丢失
  - 修复 embedding function conflict 错误
- **涉及文件**：`agents/briefing_agent.py`, `agents/main_agent.py`, `models/vector_store.py`, `ui/pages/home_page.py`

### 子方案 D：简报结构重构 — 平铺格式 + UI 兼容（ab02ae3, d54bbb4, 00cb499）

- **问题**：旧版简报按 categories 分类组织，结构复杂、前端渲染困难
- **修复**（`d54bbb4`, `ab02ae3`）：
  1. **移除 categories 分类逻辑**，采用 items 平铺格式，每条条目独立呈现
  2. **条目结构完善**：URL 必填、主条目 ★ 标记、类似报道作为子条目展示
  3. **HTML 标签清理**：生成简报时自动去除 HTML 标签
  4. **反馈按钮优化**：仅主条目显示反馈按钮，子条目不显示
- **ChromaDB 稳定性**（`ab02ae3`）：
  - 修复空集合查询导致的异常
  - 修复 numpy 布尔判断异常（`.bool()` 错误）
- **UI 兼容**（`00cb499`, `ab02ae3`）：
  - 简报列表项显示格式优化，标题/数量智能回退
  - 兼容新旧两种简报格式（categories / items），无破坏性切换
- **架构文档**：新增 `docs/ARCHITECTURE_FOR_RESUME.md` 架构详解文档
- **涉及文件**：`agents/briefing_agent.py`, `ui/pages/home_page.py`, `ui/pages/briefing_page.py`, `docs/ARCHITECTURE_FOR_RESUME.md`

### 子方案 E：RSS 源更新 + 反馈系统修复 + VectorStore 维度安全（7bd1c17, 743d97f）

- **RSS 源更新**（`7bd1c17`）：
  - 替换为 36氪、少数派、阮一峰直连 RSS 源，提升采集稳定性
  - `search_web` 触发条件优化：当采集来源 < 3 个时自动补充搜索
  - RSS 采集状态标识增强，明确区分成功/失败/跳过
- **反馈系统 ID 映射修复**（`743d97f`）：
  - **问题**：反馈记录中的 `item_id` 与实际简报条目 ID 不匹配，导致反馈数据无法关联
  - **修复**：JOIN 查询重建 `ranked → dedup` 映射链，`brief_id` / `item_id` 状态字段对齐
  - 新增 `scripts/fix_brief_ids.py` 修复历史数据
  - UI 重写支持分类渲染 + 条目级反馈按钮
- **VectorStore 维度安全检查**（`7bd1c17`）：
  - `feedback_agent` 写入向量前校验维度匹配，避免维度不一致导致 ChromaDB 写入失败
  - VectorStore 维度不匹配时自动检测并修复（删除旧集合重建）
  - 新增 `scripts/reset_chromadb.py` 一键重置工具
- **涉及文件**：`agents/feedback_agent.py`, `agents/collection_agent.py`, `models/vector_store.py`, `ui/pages/home_page.py`, `scripts/fix_brief_ids.py`, `scripts/reset_chromadb.py`

### 子方案 F：JSON 解析多层 fallback + Agent 文档建设（ba3b50e）

- **JSON 解析增强**（`agents/main_agent.py`, `agents/briefing_agent.py`）：
  - 实现多层 fallback JSON 解析策略：直接解析 → regex 提取 → 规则兜底
  - fallback 简报保留更多有效数据（URL、标题、摘要），避免丢失信息
  - `generate` / `quality` 调用计数分离，统计更精准
  - max_turns 从 5 降至 4，减少不必要的 LLM 重试
- **VectorStore 初始化修复**（`models/vector_store.py`）：
  - 修复 `embedding_fn` 与 ChromaDB 内置 embedding function 冲突问题
  - 确保单例模式下初始化参数一致性
- **文档建设**：
  - 新增 7 个 Agent 内部设计文档（`docs/agents/` 目录）
  - 新增 `scripts/test_prefilter_real.py` 预过滤真机验证脚本
- **涉及文件**：`agents/main_agent.py`, `agents/briefing_agent.py`, `models/vector_store.py`, `scripts/test_prefilter_real.py`, `docs/agents/`

---

## v2.1.0 — 减少 LLM 冗余调用：向量预过滤 + 简报管线深度优化（2026-06-24 规划中）

> **统一目标**：通过硬编码/规则化手段减少不必要的 LLM API 调用，把 LLM 从「判断」角色解放为「创造」角色。

### 子方案 A：向量预过滤跨批次去重（07）— Collection Agent 内部步骤

- 文档：`docs/Change/01_性能优化/07_向量预过滤跨批次去重.md`
- 方案：在 Collection Agent 内部，`fetch_rss`/`search_web` 返回条目后通过 ChromaDB 向量查重拦截历史重复条目，**Planner 无需感知**
- 触发条件：`config.prefilter.enabled=true`（feature flag 可控回退）
- 预期效果：进入 Ranking Agent 的条目减少 70%+，rank_items LLM token 消耗 -73%
- 涉及文件：`agents/collection_agent.py`, `agents/main_agent.py`, `models/vector_store.py`, `config/config.yaml`
- 核心改动：
  1. `_prefilter_against_history()` — Collection Agent 内部函数，查 ChromaDB 拦截相似度 ≥ 0.92 的条目
  2. `VectorStore.search_by_embedding()` — 按原始向量查询（新增方法）
  3. `VectorStore.upsert_items()` — 幂等写入（新增方法）
  4. `update_memory_node` — 追加 feed_items 向量写入 ChromaDB
- 架构优势：预过滤是 Collection Agent 的内部质量保证，Planner 保持自主编排能力

### 子方案 B：简报管线深度优化（08）— 生成前预检 + 消除 ReAct + 降低重试

- 文档：`docs/Change/01_性能优化/08_briefing生成与质量检查合并.md`
- 架构文档：`docs/Change/02_架构演进规划/05_简报管线深度优化_生成前预筛与合并调用.md`
- 方案：取消不可靠的 LLM 自评，通过「生成前硬编码预检 + 分离 coherence + quality 仅评 relevance + 降低重试上限」减少无效 LLM 调用
- 预期效果：Briefing ReAct 思考 -100%，quality LLM 仅首次调用，重试上限 3→2
- 涉及文件：`agents/briefing_agent.py`, `tools/tool_registry.py`, `config/config.yaml`
- 核心改动：
  1. **生成前硬编码预检**：`_preflight_for_briefing()` 过滤低质条目 + URL 去重合并 + 时间跨度/条目数量警告
  2. **分离 coherence 到生成前**：规则检测（URL/时间/重要性）移到预检阶段，quality_check 仅基于 LLM 矛盾计算 coherence
  3. **quality LLM 缓存复用**：relevance 仅首次调用，后续重试复用缓存
  4. **ReAct 思考消除**：确定性"生成→自动评估→(重试)→完成"流程由代码层直接控制
  5. **重试上限降低**：3→2 次（因可控扣分因素已消除）
- 架构原则：**LLM 只做「创造」不做「判断」**，拒绝 LLM 自评（存在利益冲突）

### 两个子方案的关系

```
当前管线:
  Collection (0 LLM) → Ranking (dedup LLM + rank LLM) → Briefing (ReAct思考 + generate + quality)

子方案 A (向量预过滤):
  Collection [内部预过滤] → Ranking (条目-73%) → Briefing (不变)
  节省: rank_items token -73%

子方案 B (简报管线优化):
  Collection → Ranking (不变) → Briefing (预检+消除ReAct+quality缓存, -33~50% LLM)
  节省: Briefing API -33~50%, ReAct思考 -100%

A+B 叠加:
  Collection [内部预过滤] → Ranking (条目-73%) → Briefing (预检+消除ReAct+quality缓存)
  总 API: ≤6-8 次，总耗时 ≤2 分钟
```

**实施建议**：先 A 后 B。A 是 Collection Agent 内部变更，B 是 Briefing Agent 内部重构。两者独立、可分别回退。

## v2.0.0 — LLM 动态路由 + 阶段内 ReAct（2026-06-22）

### 概述

将 FeedLens 从「LLM 辅助编排的智能流水线」升级为「层级自主 Agent」，实现 LLM 全动态路由 + 子 Agent 阶段内 ReAct。

### Phase 1: 工具层扁平化 ✅

- 新建 `tools/tool_registry.py`
- 实现 `ToolRegistry` 类：`get_schemas()` / `get_schemas_for_phase()` / `dispatch()`
- 定义全部 13 个工具 schema（OpenAI function calling 格式）：
  `fetch_rss`, `search_web`, `enrich_metadata`, `normalize_items`, `deduplicate`,
  `rank_items`, `generate_briefing`, `quality_check`, `push_notification`,
  `record_feedback`, `read_memory`, `write_memory`, `finish_task`
- dispatch 容错：未知工具名抛 KeyError 含可用工具列表

### Phase 2: State 扩展 ✅

- `agents/state.py` 新增字段：
  - `router_decision: dict[str, Any]` — LLM 路由决策
  - `router_history: list[dict[str, Any]]` — 历史决策列表（防死循环）
  - `agentic_turn_count: int` — 主循环计数
  - `agent_status: dict[str, str]` — 子 Agent 执行状态追踪（额外增强）

### Phase 3a: collection_agent ReAct 化 ✅

- `agents/collection_agent.py` 重写为 ReAct 循环
- 实现 `run_collection_agent()`：LLM Thought → tool_call → Observation → ... → finish_task
- 工具列表：`fetch_rss`, `search_web`, `enrich_metadata`, `normalize_items`, `finish_task`
- max_turns=5 硬兜底，超时返回已有数据
- 兼容接口 `build_collection_agent()` → `_ReActAgentWrapper`
- 新增测试 `scripts/test_collection_agent_react.py`

### Phase 3b: ranking_agent ReAct 化 ✅

- `agents/ranking_agent.py` 重写为 ReAct 循环
- 实现 `run_ranking_agent()`：LLM 自主决策去重+排序流程
- 工具列表：`deduplicate`, `rank_items`, `finish_task`
- 偏好向量预加载优化：避免 rank_items_node 内部重复加载
- 兼容接口 `build_ranking_agent()` → `_ReActAgentWrapper`
- 新增测试 `scripts/test_ranking_agent_react.py`

### Phase 3c: briefing_agent ReAct 化 ✅

- `agents/briefing_agent.py` 重写为 ReAct 循环
- 实现 `run_briefing_agent()`：generate_briefing → quality_check → (迭代) → finish_task
- 工具列表：`generate_briefing`, `quality_check`, `finish_task`
- 系统提示词强化收敛规则：评分 >= 0.7 立即 finish_task
- 兼容接口 `build_briefing_agent()` → `_ReActAgentWrapper`
- 新增测试 `scripts/test_briefing_agent_react.py`

### Phase 4a/4b: 主 Agent 全动态路由 ✅

- `agents/main_agent.py` 新增：
  - `router_node()` — LLM 动态路由决策节点
  - `_parse_router_response()` — 三层 JSON 容错解析（直接→regex→兜底）
  - `_fallback_router_decision()` — LLM 空响应时的规则路由降级
  - `_build_router_context()` — 路由上下文构建
  - `_router_decide()` — 条件边函数
- 所有节点间跳转由 router_node（LLM）自主决策
- 防死循环：连续 3 次相同路由 → 强制 update_memory
- 硬兜底：agentic_turn_count >= 8 → 强制结束
- ROUTER_SYSTEM_PROMPT 覆盖全部 8 个可跳转节点
- 保留固定边：`understand_intent → planner`（入口）、`update_memory → END`（终点）
- 新增测试 `scripts/test_router.py`
- **真机验证修复**：
  - LLM 空响应处理：增加 `_fallback_router_decision()` 规则路由降级
  - Router max_tokens 从 256 提升到 512，避免 JSON 截断

### Phase 5: pipeline_runner 适配 ✅

- `utils/pipeline_runner.py` 无需改动（`build_main_agent()` 内部已适配 ReAct）
- 子 Agent 通过 `_ReActAgentWrapper` 兼容 `.invoke()` 接口

### Phase 6: 真机验证 ✅

- 执行 `python utils/pipeline_runner.py --trigger manual` 3 轮验证
- 验证通过项：
  - ✅ 管线正常启动，不被 execution_fence 阻塞
  - ✅ LLM 正确路由各阶段（invoke_sub_agent / observe_results / planner 重试 / update_memory）
  - ✅ 子 Agent ReAct 循环正确执行并退出（Collection 4轮/Ranking 3轮/Briefing 迭代完成）
  - ✅ 简报正常生成（质量 0.75-0.88）
  - ✅ 记忆正常写入（情节记忆 + 长期记忆 + 执行日志 + 偏好向量）
  - ✅ 容错机制生效（死循环检测、规则路由降级、max_turns 兜底）
- 验证中发现并修复的问题：
  1. Router LLM 返回空内容 → 增加 `_fallback_router_decision()` 规则路由降级
  2. Router JSON 被 max_tokens=256 截断 → 提升到 512
  3. Briefing 系统提示词收敛性不足 → 强化 finish_task 触发条件

### Phase 7: UI 重构 — Pipeline 启动逻辑 + 日志双输出（2f242f2）✅

- **Pipeline 启动逻辑重构**（`ui/pages/home_page.py`）：
  - 将管线启动从同步阻塞改为子进程模式，Streamlit UI 不再被管线阻塞
  - 日志双输出：同时写入文件 + 终端实时显示
  - 进程状态追踪：通过 `st.session_state` 管理 `pipeline_proc` / `pipeline_running` 状态
  - 前端终端组件：黑底绿字终端风格，JS 定时 fetch 日志文件实现局部刷新，避免 `st.rerun()` 导致的整页闪烁
- **HTTP 日志服务器**（`ui/pages/home_page.py`）：
  - 内置轻量 HTTP 服务（端口 18990），暴露 `data/` 目录日志文件
  - 使用 `st.cache_resource` 确保服务器在 Streamlit 生命周期中只启动一次
  - 支持 CORS 跨域访问（Streamlit iframe 内 fetch 请求）
- **涉及文件**：`ui/pages/home_page.py`

### 不改动的文件

- `config/config.yaml` — 无新增配置
- `agents/feedback_agent.py` — 保持不变
- 无新增第三方依赖

### 回退策略

改动在 develop 分支进行，main 分支保持 MVP 可用状态。任何问题可回退到上一 commit。

---

## P0 性能与 API 消耗优化（2026-06-23）

> 实施细节见 [`01_性能优化/`](./01_性能优化/) 目录下的各子项文档。

| 编号 | 优化项 | 涉及文件 | 核心效果 | 详情 |
|------|--------|---------|---------|------|
| 2.1 | enrich_metadata 批量处理 | `collection_agent.py`, `tool_registry.py`, `config.yaml` | 可关闭，关闭时节省 13 次 API 调用 | [`01_enrich_metadata批量处理.md`](./01_性能优化/01_enrich_metadata批量处理.md) |
| 2.2 | observe 结果判断优化 | `main_agent.py`, `ranking_agent.py`, `config.yaml` | 修复误判排序失败，避免无效三板斧重跑 | [`02_observe结果判断优化.md`](./01_性能优化/02_observe结果判断优化.md) |
| 2.3 | 简报管线耗时统计 | `pipeline_runner.py`, `briefing_agent.py`, `main_agent.py` | 三层计时，性能瓶颈可见 | 无独立 detail（纯观测改动） |
| 2.4 | briefing 质量检查与重试 | `briefing_agent.py` | completeness 分母修正 + generate_count 硬限制 | [`03_briefing质量检查与重试.md`](./01_性能优化/03_briefing质量检查与重试.md) |
| 2.5 | Planner/Router 规则化降级 | `main_agent.py` | 正常流程节省 6 次 router LLM 调用 | [`04_Planner_Router规则化降级.md`](./01_性能优化/04_Planner_Router规则化降级.md) |
| 2.6 | thinking_mode 关闭 + tool_choice | `llm_provider.py`, 三个 Agent | 修复 V4 function calling 不稳定 | [`06_thinking_mode关闭与tool_choice.md`](./01_性能优化/06_thinking_mode关闭与tool_choice.md) |
| 2.7 | expand_threshold 漏传修复 | `ranking_agent.py` | 修复排序始终 0 条 | 详见 [`bugfix.md#bug-001`](./bugfix.md) |
| 2.8 | collection pipeline 固定化 | `collection_agent.py`, `config.yaml` | 采集 LLM 调用 -100%，耗时 -60~70% | [`05_collection_pipeline固定化.md`](./01_性能优化/05_collection_pipeline固定化.md) |
| 2.9 | 向量预过滤跨批次去重 | `collection_agent.py`, `main_agent.py`, `vector_store.py`, `config.yaml` | 进入 Ranking 条目 -70%+，rank_items token -73%（Collection 内部步骤，Planner 无感知） | [`07_向量预过滤跨批次去重.md`](./01_性能优化/07_向量预过滤跨批次去重.md) |
| 2.10 | briefing 管线深度优化 | `briefing_agent.py`, `tool_registry.py`, `config.yaml` | ReAct 思考 -100%，quality 仅首次调用，重试 3→2 | [`08_briefing生成与质量检查合并.md`](./01_性能优化/08_briefing生成与质量检查合并.md) |

**整体指标变化**：

| 指标 | 优化前 | 当前（v2.0） | v2.1 目标（A+B叠加） |
|------|--------|-------------|---------------------|
| 单次执行耗时 | ~8分36秒 | ≤3分钟 | ≤2分钟 |
| LLM API 调用次数 | ~35+次 | ≤12次 | ≤6-8次 |
| API 浪费占比 | ~65% | ≤20% | ≤10% |
| 最终质量 | 0.746 | ≥0.7（保持） | ≥0.7（保持） |
