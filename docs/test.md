# enrich_metadata 批量处理优化 — 测试脚本说明

## 脚本路径

`scripts/test_enrich_metadata.py`

## 目的

独立测试 `enrich_metadata` 工具在两种模式下的行为与性能：

1. **关闭模式（enabled=false，当前默认）** — 验证跳过 LLM、默认值正确、耗时极低
2. **开启模式（enabled=true）** — 验证 LLM 增强正常（分类/关键词/重要性），以及 `batch_size` / `max_items` 生效

## 用法

```bash
# 仅测试关闭模式（默认）
python scripts/test_enrich_metadata.py

# 测试关闭 + 开启两种模式
python scripts/test_enrich_metadata.py --all

# 仅测试开启模式
python scripts/test_enrich_metadata.py --enabled
```

## 环境要求

- `config/config.yaml` 中配置好 DeepSeek API key
- 工作目录为项目根目录

## 测试数据

脚本内置 10 条模拟 RSS 采集结果（`MOCK_ITEMS`），覆盖中英文、多数据源，模拟真实采集格式。每条包含 `id`、`source_url`、`title`、`summary`、`content`、`url`、`published_at`。

## 测试内容

### 测试 1：关闭模式（`test_disabled`--默认）

| 验证项 | 预期值 |
|--------|--------|
| `category` | 全部为 `"其他"` |
| `keywords` | 全部为空串 `""` |
| `importance` | 全部为 `0.5` |
| LLM 调用次数 | 0 |

### 测试 2：开启模式（`test_enabled`）

| 验证项 | 判定标准 |
|--------|----------|
| `category` | 至少有 2 种不同分类 |
| `keywords` | 至少 1 条有关键词 |
| `importance` | 至少 2 种不同重要性 |

## 关键设计

- **动态修改 config**：通过 `modify_config_enabled()` 临时修改 `config.yaml` 中 `enrich_metadata.enabled` 的值，测试结束后自动恢复为 `false`
- **工具注册表调用**：不走直接函数调用，而是通过 `tool_registry.dispatch("enrich_metadata", ...)` 模拟真实工具调度路径
- **性能对比**：当 `--all` 时，自动计算两种模式的耗时倍率和 API 调用节省估算

## 输出示例

```
============================================================
  FeedLens enrich_metadata 批量处理优化 — 独立测试
  开始时间: 2026-06-23 10:00:00
============================================================

============================================================
  测试 1/2: enrich_metadata 关闭模式 (enabled=false)
============================================================
  📝 config.yaml → enabled: false
  🔧 配置: enabled=False, batch_size=20, max_items=100
  📊 返回: count=10
  ✅ 验证: category=10/10, keywords=10/10, importance=10/10
  🎉 关闭模式测试通过！所有默认值正确。
  ⏱ 总耗时: 0.015s

============================================================
  测试总结
============================================================
  enabled_false         | ✅ PASS   | 耗时 0.015s
  enabled_true          | ✅ PASS   | 耗时 2.347s
  ──────────────────────────────────────────
  总耗时: 2.367s

  💡 对比分析:
     关闭模式耗时: 0.015s
     开启模式耗时: 2.347s
     开启/关闭倍率: 156.5x
     月省 API 调用约: ~1 次 (基于 batch_size=20)
```
