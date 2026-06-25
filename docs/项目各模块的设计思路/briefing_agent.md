# Briefing Agent 设计思路

> 简报生成 Agent 的运转逻辑，描述从排序结果到最终简报的完整流程。

---

## 整体定位

Briefing Agent 的职责是：**接收排序后的条目列表，生成结构化 JSON 简报（平铺 items 格式），并自动评估质量、必要时重试**。

核心原则：**LLM 只做创造（生成简报文案），不做判断（质量评分由代码层计算）。**

---

## 输入与输出

| | 内容 |
|---|---|
| **输入** | `ranked_items`（排序后的条目列表）+ `goal_text`（用户目标） |
| **输出** | 结构化 JSON 简报 + Markdown 渲染 + 质量评分 + 耗时统计 |

---

## 完整流程

```
ranked_items + goal_text
  │
  ▼
┌─ ① 预检（硬编码，不调用 LLM）────────────────────────────┐
│                                                         │
│  · 过滤低分条目（_score < 0.15 或无标题）                  │
│  · URL 完全相同 → 合并（保留 importance 更高的）           │
│  · 时间跨度 > 7 天 → 生成警告                             │
│  · 条目数 < 5 → 生成警告                                  │
│                                                         │
│  输出: cleaned_items + warnings                         │
└─────────────────────────────────────────────────────────┘
  │
  ▼
┌─ ② 构建 Prompt ─────────────────────────────────────────┐
│                                                         │
│  · 条目按 importance 排序，取 top N（MAX_ITEMS_PER_BRIEFING=10）│
│  · 拼接：用户目标 + 条目列表 + JSON Schema + 预检警告      │
│  · 要求 LLM 直接输出 JSON，不加 markdown 代码块            │
└─────────────────────────────────────────────────────────┘
  │
  ▼
┌─ ③ ReAct 循环（最多 `config.yaml` `agents.max_retry`=2 次重试）─┐
│                                                         │
│   LLM 思考 → 调用 generate_briefing                     │
│      │                                                  │
│      ├─ 生成简报 JSON                                    │
│      │   · LLM 输出结构化 JSON                           │
│      │   · 3 层解析 fallback（代码块 → 花括号 → 全文）    │
│      │   · 解析失败 → 硬编码 fallback 简报（不报错）       │
│      │                                                  │
│      ├─ 回填真实数据                                     │
│      │   · 用原始条目覆盖 LLM 可能编造的数据               │
│      │   · 强制覆盖：published_at / source / url / importance│
│      │                                                  │
│      ├─ 代码层自动质量评估                                │
│      │   · completeness（覆盖比例 × 0.3）                 │
│      │   · relevance（LLM 相关性评估 × 0.4，首次后缓存）   │
│      │   · coherence（LLM 事实矛盾检测 × 0.3）            │
│      │                                                  │
│      ├─ score ≥ 0.7？ → YES → 直接返回，结束              │
│      │                                                  │
│      └─ NO → 重试次数达上限？                             │
│              ├─ YES → 强制收敛返回                        │
│              └─ NO  → 注入质量反馈 → 回到 LLM 思考         │
│                                                         │
│   LLM 思考 → 调用 finish_task → 返回，结束                │
└─────────────────────────────────────────────────────────┘
  │
  ▼
输出: briefing (JSON) + markdown + quality + timing
```

---

## 关键设计决策

| 决策 | 做法 | 理由 |
|------|------|------|
| **质量检查代码化** | 不暴露给 LLM 作为工具（phase=briefing_legacy），代码层直接调用 | 消除 LLM 对质量判断的无效"思考"，避免循环 |
| **数据回填** | LLM 生成后用原始条目强制覆盖关键字段 | LLM 可能编造日期、来源，不可信 |
| **relevance 缓存** | 首次质量评估的 relevance 评分缓存，重试复用 | 节省 LLM 调用成本 |
| **平铺 items 格式** | 移除 categories 分组，直接平铺条目列表 | 与展示端 Markdown 渲染直接对齐，消除分组→平铺转换 |
| **预检前置** | URL 去重、低分过滤在生成前完成 | 减少 LLM 需要处理的噪音，降低 token 消耗 |
| **最多重试 2 次** | `generate_count >= config.yaml agents.max_retry` 即强制收敛 | 防止无限重试，保证响应时间可控 |
| **fallback 不报错** | JSON 解析失败时用原始数据直接拼接平铺简报 | 保证一定有输出，不因 LLM 格式问题中断流程 |

---

---

## 最终简报的完整结构

简报最终产出一个 **JSON 对象**，同时附带 **Markdown 渲染文本**，结构如下：

### JSON Schema（v2.2.0 平铺 items 格式）

```json
{
  "title": "string          // 简报标题，简洁有力",
  "summary": "string        // 简报摘要，200字以内",
  "items": [
    {
      "id": "string           // 条目唯一 ID（从原始数据复制，禁止编造）",
      "title": "string         // 条目标题",
      "summary": "string       // 条目摘要，200字以内",
      "source": "string        // 来源名称（回填强制覆盖）",
      "url": "string           // 原文链接（回填强制覆盖）",
      "published_at": "string  // 发布时间 ISO 格式（回填强制覆盖）",
      "importance": "number    // 重要性评分 1-5（回填强制覆盖）"
    }
  ],
  "generated_at": "string    // 生成时间 ISO 格式",
  "_markdown": "string       // Markdown 渲染文本（代码层追加，不在 Schema 中）"
}
```

> **v2.2.0 格式变更**：已从 `categories` 分组格式改为平铺 `items` 数组，与展示端 Markdown 渲染直接对齐。

### Markdown 渲染格式

```
# {简报标题}

> {简报摘要}

**{条目标题}**

摘要: {摘要内容}
链接: {原文URL}

- 来源: {source} | 时间: 2026-06-21 23:13:00 | 重要性: 4/5 | 评分: 0.344
👍 👎 🚫                            ← 反馈按钮（嵌入条目内部）

---

*生成时间: 2026-06-21T23:13:00*
```

### 数据回填规则

LLM 生成 JSON 后，代码层会用原始 `ranked_items` 强制覆盖以下字段，防止 LLM 编造：

| 字段 | 回填策略 | 原因 |
|------|----------|------|
| `published_at` | 强制覆盖 | LLM 可能生成不准确的日期 |
| `source` | 强制覆盖 | LLM 可能编造来源 |
| `url` | 强制覆盖 | LLM 可能虚构链接 |
| `importance` | 强制覆盖 | LLM 可能随意打分 |

### 解析容错（3 层 Fallback）

LLM 返回的文本可能格式不规范，解析采用 3 层容错：

```
1. 提取 ```json ... ``` 代码块 → json.loads()
   ↓ 失败
2. 正则提取最外层 { ... } → json.loads()
   ↓ 失败
3. 直接 json.loads(全文)
   ↓ 失败
4. 硬编码 fallback：用原始条目直接拼接简报（不中断流程）
```

---

## 一句话总结

> 预处理条目 → LLM 生成平铺 items JSON 简报 → 代码回填真实数据 → 代码自动打分 → 达标返回 / 不达标注入反馈重试（最多 2 次）→ 强制收敛。
