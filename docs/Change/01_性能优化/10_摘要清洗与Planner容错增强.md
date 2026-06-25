# 10 P1 — 摘要清洗增强 + Planner 容错 + VectorStore 单例

> 跨模块质量与稳定性修复：增强摘要清洗去除噪音、三层 JSON 解析降级、VectorStore 单例防数据丢失。
> 状态：✅ 已实施（2026-06-25，commit `3af4404`）

---

## 一、改动概览

本次提交包含 3 个独立子改动，共同目标是提升输出质量和系统稳定性：

| 子改动 | 涉及文件 | 类型 | 优先级 |
|--------|---------|------|--------|
| A. 摘要清洗增强 | `briefing_agent.py`, `home_page.py` | 质量增强 | P1 |
| B. Planner 三层 JSON 解析 | `main_agent.py` | 稳定性修复 | P1 |
| C. VectorStore 单例模式 | `vector_store.py` | 稳定性修复 | P1 |

---

## 二、子改动 A：摘要清洗增强

### 2.1 问题

LLM 生成的摘要中常混入噪音内容：
- 作者署名（"文｜张三"、"编辑/李四"）
- "查看全文"、"阅读全文" 等无意义尾缀
- HTML 残留标签（`<img>`、`<br>` 等）
- 重复标点、多余空白

这些噪音直接展示给用户，严重影响阅读体验。

### 2.2 修复

**新增 `_clean_summary()` 函数**（`agents/briefing_agent.py:164`）：

```python
def _clean_summary(text: str, max_chars: int = 200) -> str:
    # 1. 去除 HTML 标签（复用 _strip_html）
    # 2. 去除作者署名模式（文｜XXX、编辑/XXX、作者：XXX 等）
    # 3. 去除"查看全文"/"阅读全文"等尾缀
    # 4. 去除图片来源/转载标记
    # 5. 清理多余空白和重复标点
    # 6. 智能截断：优先在句号处断开，max_chars=200
```

**清洗覆盖点**：

| 调用位置 | 说明 |
|---------|------|
| `briefing_agent.py` 简报生成后 | `_backfill_briefing_items()` 中对每个条目的 summary 调用 `_clean_summary()` |
| `briefing_agent.py` 渲染前 | `_render_markdown()` 中对展示摘要做二次清洗 |
| `ui/pages/home_page.py` | UI 层作为最后一道防线，展示前再次清洗 |

### 2.3 设计决策

三层清洗策略确保即使某一层遗漏，后续层也能兜底：
1. **数据层**：写入数据库前清洗（`_backfill_briefing_items`）
2. **渲染层**：生成 Markdown 前清洗（`_render_markdown`）
3. **UI 层**：前端展示前清洗（`home_page.py`）

---

## 三、子改动 B：Planner 三层 JSON 解析降级

### 3.1 问题

DeepSeek V4 在 `planner_node()` 中有时输出格式不合法的 JSON：
- reason 字段包含中文引号、换行等未转义特殊字符
- JSON 被 markdown 代码块包裹
- 响应被截断（max_tokens 不足）

原有解析只做一次 `json.loads()`，失败即抛异常，依赖 `_fallback_plan` 兜底。但 fallback 是固定流程，丧失了 Planner 的动态编排能力。

### 3.2 修复

**重构 `_parse_planner_response()`**（`agents/main_agent.py:376`）：

```
Layer 1: 直接 json.loads（最快路径）
  ↓ 失败
Layer 2: regex 提取 {...} → 清洗常见 JSON 错误 → 再解析
  - 移除 markdown 代码块标记
  - 修复未转义的中文引号
  - 修复尾部多余逗号
  ↓ 失败
Layer 3: 逐字段提取关键信息（最后防线）
  - 用 regex 提取 action/params/reason 等字段
  - 拼装成合法 dict
  ↓ 全部失败
_parse_planner_response() 抛异常 → _fallback_plan() 兜底
```

**同步重构 `_parse_router_response()`**（`agents/main_agent.py:477`）：
- 同样的三层降级策略
- Layer 3 兜底返回 `{"next_node": "planner"}`

### 3.3 额外约束

Planner system prompt 中新增输出规范：
- 禁止 reason 字段使用中文引号、换行符
- JSON 必须直接输出，不得包裹 markdown 代码块

---

## 四、子改动 C：VectorStore 单例模式

### 4.1 问题

同一持久化目录（`data/chroma`）可能被多个模块创建 `VectorStore` 实例：
- `collection_agent.py` 的预过滤
- `main_agent.py` 的 `update_memory_node`
- `ranking_agent.py` 的偏好向量写入

Chromadb 的 `PersistentClient` 对同一路径创建多个实例时会产生 **embedding function conflict** 错误，且可能导致数据写入丢失（后创建的实例覆盖前一个的集合状态）。

### 4.2 修复

**`VectorStore` 单例化**（`models/vector_store.py`）：

```python
_instances: dict[str, "VectorStore"] = {}

class VectorStore:
    def __new__(cls, persist_dir: str, embedding_fn=None):
        key = os.path.abspath(persist_dir)
        if key not in _instances:
            instance = super().__new__(cls)
            _instances[key] = instance
            instance._initialized = False
        return _instances[key]
```

- 同一 `persist_dir` 始终返回同一实例
- 保留防御性逻辑：如果检测到 embedding function 冲突，自动重建集合

### 4.3 兼容性

- 对外 API 完全不变（`search_similar`、`add_items`、`upsert_items` 等）
- 调用方无需任何代码修改

---

## 五、代码变更清单

| # | 文件 | 位置 | 改动内容 |
|---|------|------|---------|
| 1 | `agents/briefing_agent.py` | L147-204 | 新增 `_strip_html()` 和 `_clean_summary()` |
| 2 | `agents/briefing_agent.py` | 多处 | `_backfill_briefing_items`、`_render_markdown` 中调用清洗 |
| 3 | `agents/main_agent.py` | L376-475 | `_parse_planner_response()` 三层降级解析 |
| 4 | `agents/main_agent.py` | L477-510 | `_parse_router_response()` 三层降级解析 |
| 5 | `models/vector_store.py` | L55-60 | VectorStore 单例模式 |
| 6 | `ui/pages/home_page.py` | — | UI 层摘要清洗 |

---

## 六、防 bug 验证

### 场景 1：摘要含作者署名

- 输入：`"文｜张三 小米发布新车，查看全文"`
- 输出：`"小米发布新车"`
- ✅ 正确清洗

### 场景 2：Planner JSON 含中文引号

- 输入：`{"reason": "用户说了"想看科技新闻"", "action": "invoke_sub_agent"}`
- Layer 1 失败 → Layer 2 修复中文引号 → 成功解析
- ✅ 不触发 fallback

### 场景 3：同一 persist_dir 两次创建 VectorStore

- 第一次：`VectorStore("data/chroma")` → 创建实例，初始化集合
- 第二次：`VectorStore("data/chroma")` → 返回同一实例
- ✅ 无 embedding function conflict

### 场景 4：embedding 维度不匹配

- 已有集合用 384 维 bge-small 创建，新模型返回 768 维
- 检测到维度不匹配 → 自动删除重建集合
- ✅ 无崩溃
