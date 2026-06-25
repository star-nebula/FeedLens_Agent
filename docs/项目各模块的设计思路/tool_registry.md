# Tool Registry（工具系统）设计思路

> 统一的工具注册、Schema 管理、阶段隔离与分发执行系统，是所有子 Agent 的能力底座。

---

## 整体定位

Tool Registry 负责：
- 将系统中所有可调用功能包装为 OpenAI function calling 标准格式
- 按 phase（阶段）隔离工具，确保子 Agent 只能访问自己阶段的工具
- 提供统一的 `dispatch()` 分发执行入口
- 延迟导入避免循环依赖

---

## 工具全景

```
┌──────────────────────────────────────────────────────┐
│                    Tool Registry                      │
│                                                      │
│  ┌─ collection 阶段 ──────────────────────────┐      │
│  │  fetch_rss      并行采集 RSS 源              │      │
│  │  search_web     搜索引擎补充采集             │      │
│  │  enrich_metadata LLM 元数据增强（可关闭）     │      │
│  │  normalize_items 字段标准化                  │      │
│  └────────────────────────────────────────────┘      │
│                                                      │
│  ┌─ ranking 阶段 ─────────────────────────────┐      │
│  │  deduplicate    向量相似度去重               │      │
│  │  rank_items     多因子加权排序               │      │
│  └────────────────────────────────────────────┘      │
│                                                      │
│  ┌─ briefing 阶段 ────────────────────────────┐      │
│  │  generate_briefing 生成结构化 JSON 简报      │      │
│  └────────────────────────────────────────────┘      │
│                                                      │
│  ┌─ main 阶段（主 Agent）─────────────────────┐      │
│  │  push_notification  推送简报                 │      │
│  │  record_feedback    记录用户反馈             │      │
│  │  read_memory        读取历史记忆             │      │
│  │  write_memory       写入决策经验             │      │
│  └────────────────────────────────────────────┘      │
│                                                      │
│  ┌─ briefing_legacy（不暴露给 LLM，代码层调用）─┐     │
│  │  quality_check    四维质量审查                │      │
│  └────────────────────────────────────────────┘      │
│                                                      │
│  ┌─ common（所有阶段可见）────────────────────┐      │
│  │  finish_task   标记当前阶段完成              │      │
│  └────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────┘
```

---

## 核心机制

### 工具注册

```python
# 每个工具定义包含 4 个部分：
{
    "name": "fetch_rss",
    "description": "并行采集多个 RSS 源的内容...",
    "parameters": { ... },  # JSON Schema
    "fn": _execute_fetch_rss,  # 可调用函数
    "phase": "collection",  # 阶段标签
}
```

### 阶段隔离

```
get_schemas_for_phase("collection")
  → 返回 fetch_rss + search_web + enrich_metadata + normalize_items + finish_task

get_schemas_for_phase("ranking")
  → 返回 deduplicate + rank_items + finish_task

get_schemas_for_phase("briefing")
  → 返回 generate_briefing + finish_task
```

子 Agent 调用 LLM 时只传入自己阶段的工具 Schema，**无法越权调用其他阶段的工具**。

### 分发执行

```
LLM 返回 function_call → tool_registry.dispatch(tool_name, arguments)
  → 查找 tool_name 对应的 fn
  → 执行 fn(arguments)
  → 返回结果
```

### 延迟导入

所有执行函数都是薄包装，内部才 `from tools.fc_tools import ...`，避免模块级别的循环依赖。

---

## 特殊处理：系统自动注入参数

部分工具的参数由系统自动注入，LLM 无需传参：

| 工具 | 自动注入的参数 | 注入方 |
|------|--------------|--------|
| `fetch_rss` | `sources` | Collection Agent |
| `search_web` | `query` | Collection Agent |
| `enrich_metadata` | `items` | Collection Agent |
| `normalize_items` | `items` | Collection Agent |
| `deduplicate` | `items` | Ranking Agent |
| `rank_items` | `items, user_id, feedback_history, goal_embedding` | Ranking Agent |
| `generate_briefing` | `items, goal_text` | Briefing Agent |
| `quality_check` | `briefing, ranked_items, goal_text` | 代码层直接调用（不经过 LLM） |

这样设计的好处：LLM 不需要知道底层数据细节，只需要表达"我想执行这个操作"即可。

---

## 关键设计决策

| 决策 | 做法 | 理由 |
|------|------|------|
| **阶段隔离** | 每个 phase 只暴露相关工具 | 防止 LLM 误调用，减少 token 消耗 |
| **参数自动注入** | 系统补全 LLM 未传的参数 | LLM 不需要知道内部状态细节 |
| **延迟导入** | 执行函数内部才 import | 避免循环依赖，减少启动开销 |
| **薄包装模式** | tool_registry 只做路由，不包含逻辑 | 关注点分离，逻辑在 fc_tools / Agent 中 |
| **全局单例** | `tool_registry = ToolRegistry()` | 避免重复注册，保持一致性 |

---

## 一句话总结

> 15 个工具按 phase 分为 6 组（collection=4 / ranking=2 / briefing=1 / main=4 / briefing_legacy=1 / common=1 + finish_task），子 Agent 只能访问自己阶段的工具，参数由系统自动注入，通过统一的 dispatch 分发执行。
