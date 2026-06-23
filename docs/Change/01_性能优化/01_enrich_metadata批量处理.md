# enrich_metadata 批量处理优化 — 实施规划

> 对应《优化规划_性能与API消耗》2.1 P0 项，从「分析清楚改哪里」到「防止引入 bug」的全链路规划。

---

## 一、影响链全貌

`enrich_metadata` 的数据流链路：

```
Collection Agent (ReAct)
  └─ LLM 决策调用 enrich_metadata 工具
       └─ tool_registry.dispatch("enrich_metadata", args)
            └─ _execute_enrich_metadata(arguments)     ← tool_registry.py:72
                 └─ enrich_metadata(items, llm, batch_size)   ← fc_tools.py:158
                      └─ 分批调 LLM (batch_size=5)
                           └─ 输出: category, keywords, importance
                                └─ 回到 Collection Agent state
                                     └─ collected_items 流入 Ranking Agent
                                          └─ rank_items_node 使用 item["importance"]  ← ranking_agent.py:303
                                               └─ 权重: cold_start=0.25, warm=0.10
```

**核心发现**：`importance` 字段只在 `rank_items_node` 中被消费，在冷启动模式下权重为 0.25（warm 为 0.10），而 `category` 和 `keywords` 在后续链路中**完全未被任何排序/简报逻辑消费**（仅在 UI 展示时可能用到）。

---

## 二、需要修改的文件（4个）

### 2.1 `tools/fc_tools.py` — enrich_metadata 函数

**当前代码** (`:158-205`)：
```python
def enrich_metadata(items, llm_provider, batch_size=5):
    # 逐批调 LLM，每批 batch_size=5 条
    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        response = llm_provider.chat(...)
        ...
```

**改动**：
| 项目 | 说明 |
|------|------|
| `batch_size` 默认值 | `5` → `20`（从 config 读取，如配置不存在则用 20） |
| 空列表处理 | 已有 `if not items: return []` 在 tool_registry 层，此处无需额外处理 |
| 异常兜底 | 保持不变（单批失败写入 `enrich_error` 字段，不中断其他批次） |

**不改**：
- `build_enrich_prompt()` — prompt 模板不变，只是每批条目数变多
- `parse_enrich_response()` — 解析逻辑不变

**潜在风险**：
- batch_size 增大 → prompt token 增多，可能超模型上下文限制 → 需设置 `max_items` 上限（建议 30 条）
- LLM 返回的 JSON 数组长度可能 < 期望值 → 现有兜底逻辑已处理（`if j < len(results)` 否则填默认值）

---

### 2.2 `tools/tool_registry.py` — _execute_enrich_metadata 函数

**当前代码** (`:72-92`)：
```python
def _execute_enrich_metadata(arguments: dict) -> dict:
    items = arguments.get("items", [])
    batch_size = arguments.get("batch_size", 5)    # ← 硬编码默认 5

    if not items:
        return {"items": [], "count": 0}

    config = load_config()
    llm_cfg = config.get("llm", {}).get("deepseek", {})
    llm = DeepSeekProvider(...)
    enriched = _fn(items, llm_provider=llm, batch_size=batch_size)
    return {"items": enriched, "count": len(enriched)}
```

**改动**：
| 项目 | 说明 |
|------|------|
| 读取 config 控制开关 | 新增 `enrich_cfg = config.get("enrich_metadata", {})`，若 `enabled: false` 则直接返回原始 items（打上默认值） |
| batch_size 默认值 | 从 `arguments.get("batch_size", 5)` 改为 `arguments.get("batch_size", enrich_cfg.get("batch_size", 20))` |
| max_items 限制 | 新增 `max_items = enrich_cfg.get("max_items", 30)`，超过时只处理前 max_items 条 |
| 关闭时的兜底 | 当 `enabled=false` 时，给每个 item 填默认值（category="其他", keywords="", importance=0.5），保证下游不报 KeyError |

**关键防护**：
```python
# 关闭 enrich_metadata 时必须填充默认字段，否则 rank_items_node:303 会报 KeyError
if not enrich_cfg.get("enabled", True):
    for item in items:
        item.setdefault("category", "其他")
        item.setdefault("keywords", "")
        item.setdefault("importance", 0.5)
    return {"items": items, "count": len(items), "enriched": False}
```

**不改**：
- `TOOLS` 列表中 `enrich_metadata` 的 schema 定义不变（LLM 仍能看到这个工具）
- `DeepSeekProvider` 的初始化方式不变

---

### 2.3 `config/config.yaml` — 新增配置段

**新增内容**：
```yaml
# --- 元数据增强（LLM 提取 category/keywords/importance）---
enrich_metadata:
  enabled: false              # 默认关闭；冷启动阶段 importance 权重仅 0.25，收益小
  batch_size: 20              # 启用时每批处理条数
  max_items: 30               # 单次最多处理条目数（防止 token 超限）
```

**不改**：
- 其他配置段（`llm`, `ranking`, `weights_cold`, `weights_warm` 等）保持不变
- `ranking.quality_threshold` 不变

---

### 2.4 `agents/collection_agent.py` — COLLECTION_SYSTEM_PROMPT

**当前代码** (`:90-106`)：
```
COLLECTION_SYSTEM_PROMPT = """...
可用工具：
- fetch_rss: ...
- search_web: ...
- enrich_metadata: 使用 LLM 对条目提取分类、关键词、重要性评分
- normalize_items: ...
- finish_task: ...

工作流程建议：
1. 先调用 fetch_rss 采集 RSS 源
2. 如果采集量 < 5 条，调用 search_web 补充搜索
3. 调用 enrich_metadata 提取元数据          ← 强引导
4. 调用 normalize_items 标准化字段
5. 调用 finish_task 结束
```

**改动**：
| 项目 | 说明 |
|------|------|
| 工作流程引导 | 第 3 步从"调用 enrich_metadata"改为"可选：调用 enrich_metadata 提取元数据（非必须）" |
| 工具描述 | 在 `enrich_metadata` 描述后加注 `（可选，非必须调用）` |

**改动后的 prompt**：
```
工作流程建议：
1. 先调用 fetch_rss 采集 RSS 源
2. 如果采集量 < 5 条，调用 search_web 补充搜索
3. 调用 normalize_items 标准化字段
4. 调用 finish_task 结束

enrich_metadata 是可选的增强工具，仅在需要时调用。
完成后必须调用 finish_task。"""
```

**不改**：
- ReAct 循环逻辑（`run_collection_agent`）不变——LLM 仍能看到 enrich_metadata 工具 schema，只是不被强引导调用
- `tool_registry.dispatch` 不变

---

## 三、不需要修改的文件（确认清单）

| 文件 | 不修改原因 |
|------|-----------|
| `agents/main_agent.py` | observe/planner/router 不直接依赖 enrich_metadata，通过 collected_items 间接消费 |
| `agents/ranking_agent.py` | `item["importance"]` 读取处（`:303`）有 `float(item.get("importance", 0.5))` 默认值兜底，关闭 enrich 不会报错 |
| `agents/briefing_agent.py` | 不直接使用 category/keywords/importance |
| `agents/state.py` | FeedLensState 无 enrich_metadata 专用字段 |
| `tools/fc_tools.py` 其他函数 | `fetch_rss`, `normalize_items`, `deduplicate`, `rank_items` 均不依赖 enrich_metadata 的输出 |
| `utils/config.py` | `load_config()` 通用函数，无需改动 |
| `utils/llm_provider.py` | 不变 |

---

## 四、Bug 预防分析

### 4.1 关键防御点

| # | 风险场景 | 预防措施 | 检查位置 |
|---|---------|---------|---------|
| 1 | 关闭 enrich 后 `item["importance"]` 不存在 → rank_items_node KeyError | `_execute_enrich_metadata` 关闭时填充默认值 `importance=0.5` | `tool_registry.py:72-92` |
| 2 | 关闭 enrich 后 `item["category"]` 不存在 → 简报生成可能报错 | 同上填充 `category="其他"` | `tool_registry.py` |
| 3 | batch_size 过大导致 prompt 超 token 限制 | `max_items=30` 上限截断 | `tool_registry.py` + `config.yaml` |
| 4 | LLM 返回 JSON 长度 < 期望值 | 已有兜底：`if j < len(results) else 默认值` | `fc_tools.py:188-195` |
| 5 | config.yaml 没有 `enrich_metadata` 段（旧版兼容） | `.get("enrich_metadata", {})` + `.get("enabled", True)` 默认启用（向后兼容） | `tool_registry.py` |
| 6 | LLM 仍然调用 enrich_metadata（prompt 弱引导后） | 工具实际执行时 `enabled=false` 跳过 LLM 调用，返回默认值，不报错 | `tool_registry.py` |

### 4.2 回归验证点

修改完成后需验证：
1. **关闭 enrich_metadata** → pipeline 正常走完，rank_items 不报 KeyError
2. **开启 enrich_metadata + batch_size=20** → 62 条只调 ~4 次 LLM（不是 13 次）
3. **旧版 config.yaml 无 enrich_metadata 段** → 行为不变（默认启用，batch_size=20）
4. **采集 0 条** → enrich_metadata 收到空列表，直接返回 `{"items": [], "count": 0}`
5. **单批 LLM 失败** → 该批填默认值 + `enrich_error`，不阻断其他批次

---

## 五、修改顺序（推荐）

```
Step 1: config/config.yaml          ← 新增 enrich_metadata 配置段
Step 2: tools/fc_tools.py           ← batch_size 默认值改为 20
Step 3: tools/tool_registry.py      ← _execute_enrich_metadata 读取 config 控制开关 + 填充默认值
Step 4: agents/collection_agent.py  ← COLLECTION_SYSTEM_PROMPT 弱化 enrich 引导
Step 5: 运行手动触发验证            ← 确认 pipeline 正常 + API 调用减少
```

这个顺序遵循"配置 → 底层工具 → 中间层调度 → 上层 prompt"的依赖链，每一步完成后都不会破坏已有功能。

---

## 六、实施记录

**实施日期**：2026-06-23

**修改文件**：
1. `config/config.yaml` — 新增 `enrich_metadata` 配置段（`enabled: false`, `batch_size: 20`, `max_items: 30`）
2. `tools/fc_tools.py` — `enrich_metadata()` 函数 `batch_size` 默认值 5→20
3. `tools/tool_registry.py` — `_execute_enrich_metadata()` 读取 config 控制开关：关闭时填充默认值，开启时使用 config 的 batch_size/max_items；更新 schema 描述中的 batch_size 默认值
4. `agents/collection_agent.py` — `COLLECTION_SYSTEM_PROMPT` 弱化 enrich_metadata 强引导，从强制调用改为可选
