# 2.5 P2 — Collection Agent 流程固定化（Pipeline 替代 ReAct）实施规划

> 对应《优化规划_性能与API消耗》2.5 P2 项，从「分析清楚改哪里」到「防止引入 bug」的全链路规划。

---

## 一、影响链全貌

Collection Agent 的当前数据流链路：

```
planner 编排 plan=[Collection, ...]
  └─ invoke_sub_agent (main_agent.py:641)
       └─ build_collection_agent().invoke(state) → _ReActAgentWrapper
            └─ run_collection_agent(state)
                 └─ ReAct 循环 (max_turns=5):
                      Turn 1: LLM 思考 → 调用 fetch_rss
                      Turn 2: LLM 思考 → 调用 normalize_items
                      Turn 3: LLM 思考 → 调用 finish_task
                      每轮: LLM API 调用 1 次 (max_tokens=4096)
```

**核心发现**：Collection Agent 的流程是**完全确定**的：

```
fetch_rss → [可选: enrich_metadata] → normalize_items → finish_task
```

这个流程不依赖任何运行时判断——无论 RSS 返回多少条、无论用户目标是什么，步骤顺序都不变。唯一可能的变体是 `search_web`（当 RSS 返回 < 5 条时），但这个决策也可以用简单规则替代（`if len(items) < 5: search_web()`），不需要 LLM 参与。

---

## 二、需要修改的文件（3 个）

### 2.1 `agents/collection_agent.py` — 新增 `run_collection_pipeline()` 函数

**当前代码** (`:112-256`)：`run_collection_agent()` — 完整 ReAct 循环

**改动**：新增一个无 LLM 的固定流水线函数，保持与 `run_collection_agent()` 相同的输入输出签名。

```python
def run_collection_pipeline(state: FeedLensState) -> dict:
    """固定流水线采集 — 无 LLM 参与，顺序执行 fetch_rss → normalize_items → finish_task。
    
    仅当 fetch_rss 返回 < 5 条时才调用 search_web 补充（规则判断，不调 LLM）。
    
    Args:
        state: FeedLensState

    Returns:
        dict: {collected_items, search_supplemented, collection_summary}
    """
    sources = _get_rss_sources(state)
    query = _get_search_query(state)
    
    collected_items = []
    search_supplemented = False
    
    # Step 1: fetch_rss（直接调用工具，不经过 LLM）
    print("[collection_pipeline] Step 1: fetch_rss", flush=True)
    rss_result = tool_registry.dispatch("fetch_rss", {"sources": sources})
    rss_items = rss_result.get("items", [])
    valid_items = [it for it in rss_items if "error" not in it]
    collected_items.extend(valid_items)
    print(f"[collection_pipeline] fetch_rss 完成: {len(collected_items)} 条", flush=True)
    
    # Step 2: search_web 补充（仅当 RSS 不足 5 条时规则触发）
    if len(collected_items) < 5:
        print(f"[collection_pipeline] Step 2: search_web 补充（当前仅 {len(collected_items)} 条）", flush=True)
        search_result = tool_registry.dispatch("search_web", {"query": query})
        search_items = search_result.get("items", [])
        if search_items:
            search_supplemented = True
            collected_items.extend(search_items)
            print(f"[collection_pipeline] search_web 完成: +{len(search_items)} 条", flush=True)
    
    # Step 3: normalize_items（统一字段格式）
    if collected_items:
        print(f"[collection_pipeline] Step 3: normalize_items ({len(collected_items)} 条)", flush=True)
        norm_result = tool_registry.dispatch("normalize_items", {"items": collected_items})
        normalized = norm_result.get("items", [])
        if normalized:
            collected_items = normalized
    else:
        print("[collection_pipeline] 无条目，跳过 normalize_items", flush=True)
    
    # Step 4: 完成
    summary = f"采集完成：共 {len(collected_items)} 条（RSS + {'搜索补充' if search_supplemented else '仅 RSS'}）"
    print(f"[collection_pipeline] {summary}", flush=True)
    
    return {
        "collected_items": collected_items,
        "search_supplemented": search_supplemented,
        "collection_summary": summary,
    }
```

**关键设计决策**：

| 决策 | 说明 |
|------|------|
| 不调用 `enrich_metadata` | 当前 config 中 `enrich_metadata.enabled: false`（P0 已关闭），pipeline 模式下也默认跳过。如果未来需要启用，可通过 config 控制 |
| `search_web` 规则判断 | 阈值为 5 条，与 ReAct 模式 System Prompt 一致。可配置化（见 config 改动） |
| 不调用 LLM 的 `finish_task` | ReAct 模式下 `finish_task` 的作用是让 LLM 生成摘要文字，pipeline 模式下用固定模板生成 summary |
| 返回值签名不变 | 与 `run_collection_agent()` 完全一致，`invoke_sub_agent` 无需改动 |

---

### 2.2 `agents/collection_agent.py` — 修改 `build_collection_agent()` 支持模式切换

**当前代码** (`:273-278`)：

```python
def build_collection_agent():
    """构建采集 Agent（兼容旧接口）。"""
    return _ReActAgentWrapper(run_collection_agent)
```

**改动**：根据 config 选择 pipeline 或 ReAct 模式：

```python
def build_collection_agent():
    """构建采集 Agent（兼容旧接口）。
    
    根据 config 中 agents.collection_mode 选择模式：
    - "pipeline": 固定流水线，无 LLM 参与（默认）
    - "react": 传统 ReAct 循环（兼容模式）
    """
    config = load_config()
    mode = config.get("agents", {}).get("collection_mode", "pipeline")
    
    if mode == "react":
        print("[collection_agent] 模式: ReAct（LLM 自主决策）", flush=True)
        return _ReActAgentWrapper(run_collection_agent)
    else:
        print("[collection_agent] 模式: Pipeline（固定流水线，省 API）", flush=True)
        return _ReActAgentWrapper(run_collection_pipeline)
```

**不改**：
- `_ReActAgentWrapper` 类保持不变（pipeline 函数也返回 dict，兼容 `.invoke()` 签名）
- `run_collection_agent()` 函数保留（作为 `react` 模式的回退）
- `COLLECTION_SYSTEM_PROMPT` 保留（ReAct 模式仍然需要）

---

### 2.3 `config/config.yaml` — 新增 `collection_mode` 配置

**当前 `agents` 段**：

```yaml
agents:
  max_react_cycles: 3
  max_retry: 2
  max_sub_agents_per_plan: 3
  max_same_agent_calls: 2
  max_turns: 5
```

**新增**：

```yaml
agents:
  max_react_cycles: 3
  max_retry: 2
  max_sub_agents_per_plan: 3
  max_same_agent_calls: 2
  max_turns: 5
  collection_mode: pipeline      # P2-2.5: 采集模式 pipeline | react
  collection_search_threshold: 5 # P2-2.5: RSS 不足 N 条时自动触发 search_web
```

**不改**：
- 其他 `agents` 配置项保持不变
- `ranking`、`weights_cold`、`weights_warm` 等段不变

---

## 三、不需要修改的文件（确认清单）

| 文件 | 不修改原因 |
|------|-----------|
| `agents/main_agent.py` | `invoke_sub_agent` 通过 `build_collection_agent().invoke(state)` 调用，pipeline 返回 dict 格式与 ReAct 完全一致，无需改动 |
| `agents/state.py` | `FeedLensState` 无 Collection 专用字段变更 |
| `tools/tool_registry.py` | pipeline 直接调用 `tool_registry.dispatch()`，不经过 LLM function calling，工具 schema 不变 |
| `tools/fc_tools.py` | `fetch_rss`、`search_web`、`normalize_items` 函数逻辑不变 |
| `agents/ranking_agent.py` | 只消费 `collected_items`，不关心来源是 ReAct 还是 Pipeline |
| `agents/briefing_agent.py` | 同上 |
| `utils/llm_provider.py` | 不变 |

---

## 四、Bug 预防分析

### 4.1 关键防御点

| # | 风险场景 | 预防措施 | 检查位置 |
|---|---------|---------|---------|
| 1 | `fetch_rss` 全部失败返回空列表 | 自动触发 `search_web` 补充（`< 5` 条件包含 0 条场景） | `run_collection_pipeline()` |
| 2 | `normalize_items` 收到空列表 | `if collected_items:` 守卫，空列表跳过 | `run_collection_pipeline()` |
| 3 | `search_web` 也失败 | 不阻断流程，`collected_items` 可能为 0，下游 Ranking 正常处理空列表 | `run_collection_pipeline()` |
| 4 | 用户有旧版 config（无 `collection_mode` 字段） | `.get("collection_mode", "pipeline")` 默认 pipeline | `build_collection_agent()` |
| 5 | `search_supplemented` 字段缺失 | pipeline 始终返回该字段（初始 `False`，搜索成功后 `True`） | `run_collection_pipeline()` |
| 6 | pipeline 模式下的日志格式不一致 | 统一使用 `[collection_pipeline]` 前缀，便于区分 | `run_collection_pipeline()` |

### 4.2 回归验证点

修改完成后需验证：

1. **Pipeline 模式 + RSS 正常** → 顺序执行 fetch_rss → normalize_items → 返回结果，不调 LLM
2. **Pipeline 模式 + RSS 失败** → 自动触发 search_web → normalize_items → 返回结果
3. **Pipeline 模式 + RSS=0 + search_web=0** → 返回空 `collected_items`，下游正常处理
4. **ReAct 模式** → 行为与修改前完全一致（`collection_mode: react`）
5. **旧版 config（无 `collection_mode`）** → 默认 pipeline 模式
6. **`invoke_sub_agent` 兼容** → pipeline 返回的 dict 被正确消费，`collected_items` 流入 Ranking

---

## 五、预估效果

| 指标 | 优化前 (ReAct) | 优化后 (Pipeline) | 改善 |
|------|---------------|-------------------|------|
| 每轮 API 调用 | 3-4 次 | 0 次 | **-100%** |
| 每轮耗时（API 部分） | ~6-10s | 0s | **-100%** |
| 采集总耗时 | ~12-15s | ~3-5s（仅 I/O） | **-60~70%** |

按每次执行 1 轮采集计算，节省 **3-4 次 LLM API 调用**，约 **6-10 秒**。

---

## 六、修改顺序（推荐）

```
Step 1: config/config.yaml              ← 新增 collection_mode 和 collection_search_threshold
Step 2: agents/collection_agent.py      ← 新增 run_collection_pipeline() + 修改 build_collection_agent()
Step 3: 运行手动触发验证                  ← 确认 pipeline 正常 + 数据正确流入下游
```

这个顺序遵循"配置 → 代码"的依赖链，每一步完成后都不会破坏已有功能。

---

## 七、实施记录

**实施日期**：2026-06-23  
**状态**：✅ 已完成

**修改文件**：
1. `config/config.yaml` — `agents` 段新增 `collection_mode: pipeline` 和 `collection_search_threshold: 5`
2. `agents/collection_agent.py` — 新增 `run_collection_pipeline()` 固定流水线函数；修改 `build_collection_agent()` 支持 pipeline/react 模式切换

**测试结果**：
- `scripts/test_collection_pipeline.py`：**10/10 通过**（新增）
  - Pipeline RSS 正常采集
  - Pipeline RSS 不足触发搜索
  - Pipeline 全部失败降级
  - Pipeline fetch_rss 异常降级
  - build_collection_agent pipeline 模式
  - build_collection_agent react 兼容模式
  - build_collection_agent 默认 pipeline（旧版 config）
  - Pipeline 返回值字段完整性
  - Pipeline 无 LLM 调用验证
  - Pipeline search_threshold 可配置
- `scripts/test_collection_agent_react.py`：**7/7 通过**（回归）
- `scripts/test_router.py`：**29/29 通过**（回归）

**变更记录**：`docs/Change&TODO/changelog.md` — 2.8 节
