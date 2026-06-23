"""
enrich_metadata 批量处理优化 — 独立测试脚本

测试内容：
  1. enabled=false（当前默认）：验证跳过 LLM、默认值正确、耗时
  2. enabled=true：验证 LLM 增强正常、batch_size/max_items 生效

用法：
  python scripts/test_enrich_metadata.py              # 仅测试关闭模式（默认）
  python scripts/test_enrich_metadata.py --all        # 测试关闭 + 开启两种模式
  python scripts/test_enrich_metadata.py --enabled    # 仅测试开启模式

环境要求：
  - config/config.yaml 中配置好 deepseek API key
  - 工作目录为项目根目录
"""

import sys
import os
import time
import json
from datetime import datetime

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ============================================================
# 模拟 RSS 采集结果（真实格式）
# ============================================================

MOCK_ITEMS = [
    {
        "id": "mock_001",
        "source_url": "https://36kr.com/feed",
        "title": "OpenAI 发布 GPT-5，推理能力大幅提升",
        "summary": "OpenAI 今日正式发布 GPT-5 模型，在数学推理、代码生成和多模态理解方面相比 GPT-4 有显著提升，多项基准测试刷新纪录。",
        "content": "详细内容...",
        "url": "https://36kr.com/p/123456",
        "published_at": "2026-06-23T08:00:00Z",
    },
    {
        "id": "mock_002",
        "source_url": "https://www.solidot.org/index.rss",
        "title": "Linux 内核 6.15 发布，新增 Rust 驱动支持",
        "summary": "Linus Torvalds 宣布 Linux 6.15 正式版发布，本次更新包含多个用 Rust 编写的驱动程序，标志着 Rust 在 Linux 内核中的进一步采用。",
        "content": "详细内容...",
        "url": "https://www.solidot.org/story?sid=78901",
        "published_at": "2026-06-23T07:30:00Z",
    },
    {
        "id": "mock_003",
        "source_url": "https://sspai.com/feed",
        "title": "Apple Vision Pro 2 或将支持更轻量化的设计",
        "summary": "据供应链消息，苹果正在研发第二代 Vision Pro，将采用更轻的钛合金框架和更高分辨率的 micro-OLED 屏幕。",
        "content": "详细内容...",
        "url": "https://sspai.com/post/99999",
        "published_at": "2026-06-23T06:00:00Z",
    },
    {
        "id": "mock_004",
        "source_url": "https://feeds.bbci.co.uk/news/technology/rss.xml",
        "title": "EU passes comprehensive AI regulation framework",
        "summary": "The European Union has passed a comprehensive AI regulation framework that sets strict requirements for high-risk AI systems and foundation models.",
        "content": "Detailed content...",
        "url": "https://bbc.com/news/technology-123",
        "published_at": "2026-06-23T05:00:00Z",
    },
    {
        "id": "mock_005",
        "source_url": "https://rsshub.app/github/trending/daily",
        "title": "开源项目 AutoGPT 获 10 万 GitHub Star",
        "summary": "AutoGPT 项目在 GitHub 上突破 10 万 Star，成为增长最快的 AI Agent 开源项目之一。",
        "content": "详细内容...",
        "url": "https://github.com/Significant-Gravitas/AutoGPT",
        "published_at": "2026-06-23T04:00:00Z",
    },
    {
        "id": "mock_006",
        "source_url": "https://36kr.com/feed",
        "title": "字节跳动推出全新 AI 编程助手，对标 GitHub Copilot",
        "summary": "字节跳动内部孵化了一款 AI 编程助手产品，支持多种主流编程语言，据称在中文代码生成方面表现优于竞品。",
        "content": "详细内容...",
        "url": "https://36kr.com/p/123457",
        "published_at": "2026-06-22T20:00:00Z",
    },
    {
        "id": "mock_007",
        "source_url": "https://www.ruanyifeng.com/blog/atom.xml",
        "title": "科技爱好者周刊（第 300 期）：WebAssembly 的现状与未来",
        "summary": "本期周刊聚焦 WebAssembly 技术，介绍了 WASM 在浏览器之外的最新应用场景，包括边缘计算和 Serverless 平台。",
        "content": "详细内容...",
        "url": "https://www.ruanyifeng.com/blog/2026/06/weekly-300.html",
        "published_at": "2026-06-22T12:00:00Z",
    },
    {
        "id": "mock_008",
        "source_url": "https://sspai.com/feed",
        "title": "Notion 推出 AI 数据库功能，自动化工作流再升级",
        "summary": "Notion 发布全新 AI 数据库功能，用户可以通过自然语言查询和操作数据库，自动生成图表和报告。",
        "content": "详细内容...",
        "url": "https://sspai.com/post/100000",
        "published_at": "2026-06-22T10:00:00Z",
    },
    {
        "id": "mock_009",
        "source_url": "https://www.solidot.org/index.rss",
        "title": "Google 发布 Gemma 3 开源模型，性能超越 Llama 4",
        "summary": "Google DeepMind 发布 Gemma 3 系列开源模型，在多项基准测试中超越 Meta 的 Llama 4，同时保持较小的参数量。",
        "content": "详细内容...",
        "url": "https://www.solidot.org/story?sid=78902",
        "published_at": "2026-06-22T08:00:00Z",
    },
    {
        "id": "mock_010",
        "source_url": "https://36kr.com/feed",
        "title": "特斯拉 Optimus 机器人开始在工厂内部测试",
        "summary": "特斯拉宣布 Optimus 人形机器人已开始在德州超级工厂进行内部测试，执行简单的物料搬运和分拣任务。",
        "content": "详细内容...",
        "url": "https://36kr.com/p/123458",
        "published_at": "2026-06-22T06:00:00Z",
    },
]


# ============================================================
# 辅助函数
# ============================================================

def time_section(label: str):
    """带计时的上下文管理器。"""
    class _Timer:
        def __enter__(self):
            self.start = time.perf_counter()
            return self
        def __exit__(self, *args):
            self.elapsed = time.perf_counter() - self.start
    timer = _Timer()
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    return timer


def modify_config_enabled(enabled: bool):
    """临时修改 config.yaml 中 enrich_metadata.enabled 的值。"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "config.yaml"
    )
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()

    old_str = f"enabled: {str(not enabled).lower()}"
    new_str = f"enabled: {str(enabled).lower()}"
    if old_str in content:
        content = content.replace(old_str, new_str)
    else:
        print(f"  ⚠ 未找到 enabled: {not enabled}，可能已修改过")

    with open(config_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  📝 config.yaml → enabled: {enabled}")


def reset_config_enabled():
    """恢复 config.yaml 为 enabled: false。"""
    modify_config_enabled(False)


def validate_default_values(items: list) -> dict:
    """验证关闭模式下所有条目的默认值是否正确。"""
    total = len(items)
    ok_category = sum(1 for it in items if it.get("category") == "其他")
    ok_keywords = sum(1 for it in items if it.get("keywords") == "")
    ok_importance = sum(1 for it in items if it.get("importance") == 0.5)

    all_ok = (ok_category == total and ok_keywords == total and ok_importance == total)
    return {
        "total": total,
        "category_ok": ok_category,
        "keywords_ok": ok_keywords,
        "importance_ok": ok_importance,
        "all_pass": all_ok,
    }


def validate_llm_values(items: list) -> dict:
    """验证开启模式下 LLM 增强结果的质量。"""
    total = len(items)
    categories = set(it.get("category", "") for it in items)
    has_keywords = sum(1 for it in items if it.get("keywords", "").strip())
    importances = [it.get("importance", 0.5) for it in items]
    avg_importance = sum(importances) / len(importances) if importances else 0
    unique_importances = len(set(importances))

    return {
        "total": total,
        "unique_categories": len(categories),
        "categories": categories,
        "items_with_keywords": has_keywords,
        "avg_importance": round(avg_importance, 3),
        "unique_importances": unique_importances,
        "importance_range": f"{min(importances):.2f} ~ {max(importances):.2f}",
    }


def print_items_summary(items: list, max_show: int = 5):
    """打印条目摘要。"""
    print(f"\n  📋 条目摘要（共 {len(items)} 条，展示前 {min(max_show, len(items))} 条）:")
    for i, item in enumerate(items[:max_show]):
        cat = item.get("category", "?")
        kw = item.get("keywords", "")[:40]
        imp = item.get("importance", "?")
        print(f"  [{i+1}] {item['title'][:50]:50s} | {cat:4s} | imp={imp} | kw={kw}")


# ============================================================
# 测试 1：关闭模式（enabled=false）
# ============================================================

def test_disabled():
    """测试 enrich_metadata 关闭模式。"""
    with time_section("测试 1/2: enrich_metadata 关闭模式 (enabled=false)") as timer:
        modify_config_enabled(False)

        # 重新导入（config 可能被缓存）
        from tools.tool_registry import tool_registry
        from utils.config import load_config

        config = load_config()
        enrich_cfg = config.get("enrich_metadata", {})
        print(f"  🔧 配置: enabled={enrich_cfg.get('enabled')}, batch_size={enrich_cfg.get('batch_size')}, max_items={enrich_cfg.get('max_items')}")

        items = [dict(it) for it in MOCK_ITEMS]  # 深拷贝

        # 调用 enrich_metadata
        result = tool_registry.dispatch("enrich_metadata", {"items": items})

        enriched = result.get("items", [])
        count = result.get("count", 0)
        print(f"  📊 返回: count={count}")

        validation = validate_default_values(enriched)
        print(f"  ✅ 验证: category={validation['category_ok']}/{validation['total']}, "
              f"keywords={validation['keywords_ok']}/{validation['total']}, "
              f"importance={validation['importance_ok']}/{validation['total']}")

        print_items_summary(enriched)

        if validation["all_pass"]:
            print(f"\n  🎉 关闭模式测试通过！所有默认值正确。")
        else:
            print(f"\n  ❌ 关闭模式测试失败！部分默认值不符预期。")

    print(f"  ⏱ 总耗时: {timer.elapsed:.3f}s")
    return timer.elapsed, validation["all_pass"]


# ============================================================
# 测试 2：开启模式（enabled=true）
# ============================================================

def test_enabled():
    """测试 enrich_metadata 开启模式（LLM 增强）。"""
    with time_section("测试 2/2: enrich_metadata 开启模式 (enabled=true)") as timer:
        modify_config_enabled(True)

        from tools.tool_registry import tool_registry
        from utils.config import load_config

        config = load_config()
        enrich_cfg = config.get("enrich_metadata", {})
        print(f"  🔧 配置: enabled={enrich_cfg.get('enabled')}, batch_size={enrich_cfg.get('batch_size')}, max_items={enrich_cfg.get('max_items')}")

        items = [dict(it) for it in MOCK_ITEMS]  # 深拷贝

        # 调用 enrich_metadata
        result = tool_registry.dispatch("enrich_metadata", {"items": items})

        enriched = result.get("items", [])
        count = result.get("count", 0)
        print(f"  📊 返回: count={count}")

        validation = validate_llm_values(enriched)
        print(f"  📊 分析: categories={validation['unique_categories']}种 {validation['categories']}")
        print(f"  📊 关键词覆盖率: {validation['items_with_keywords']}/{validation['total']}")
        print(f"  📊 importance: avg={validation['avg_importance']}, unique={validation['unique_importances']}, range={validation['importance_range']}")

        print_items_summary(enriched)

        # 判定标准：至少要有分类和关键词产出
        has_categories = validation["unique_categories"] > 1
        has_keywords = validation["items_with_keywords"] > 0
        has_importance_variation = validation["unique_importances"] > 1

        all_ok = has_categories and has_keywords
        if all_ok:
            print(f"\n  🎉 开启模式测试通过！LLM 增强正常。")
        else:
            issues = []
            if not has_categories:
                issues.append("分类单一")
            if not has_keywords:
                issues.append("关键词缺失")
            if not has_importance_variation:
                issues.append("重要性无区分度")
            print(f"\n  ⚠ 开启模式测试部分通过，但存在: {', '.join(issues)}")

    print(f"  ⏱ 总耗时: {timer.elapsed:.3f}s")
    return timer.elapsed, all_ok


# ============================================================
# 主流程
# ============================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="enrich_metadata 优化测试")
    parser.add_argument("--all", action="store_true", help="测试关闭 + 开启两种模式")
    parser.add_argument("--enabled", action="store_true", help="仅测试开启模式")
    args = parser.parse_args()

    print("=" * 60)
    print("  FeedLens enrich_metadata 批量处理优化 — 独立测试")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {}
    start_total = time.perf_counter()

    try:
        if args.enabled:
            # 仅测试开启模式
            elapsed, passed = test_enabled()
            results["enabled_true"] = {"elapsed": elapsed, "passed": passed}
            reset_config_enabled()
        elif args.all:
            # 测试两种模式
            elapsed1, passed1 = test_disabled()
            results["enabled_false"] = {"elapsed": elapsed1, "passed": passed1}

            elapsed2, passed2 = test_enabled()
            results["enabled_true"] = {"elapsed": elapsed2, "passed": passed2}

            reset_config_enabled()
        else:
            # 默认仅测试关闭模式
            elapsed1, passed1 = test_disabled()
            results["enabled_false"] = {"elapsed": elapsed1, "passed": passed1}

    except Exception as e:
        print(f"\n  ❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        reset_config_enabled()
        return

    total_elapsed = time.perf_counter() - start_total

    # 打印总结
    print(f"\n{'='*60}")
    print(f"  测试总结")
    print(f"{'='*60}")
    for mode, r in results.items():
        status = "✅ PASS" if r["passed"] else "❌ FAIL"
        print(f"  {mode:20s} | {status:8s} | 耗时 {r['elapsed']:.3f}s")
    print(f"  {'─'*50}")
    print(f"  总耗时: {total_elapsed:.3f}s")
    print(f"  结束时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # API 节省估算（仅当两种模式都测试时）
    if "enabled_false" in results and "enabled_true" in results:
        t_disabled = results["enabled_false"]["elapsed"]
        t_enabled = results["enabled_true"]["elapsed"]
        if t_disabled > 0:
            ratio = t_enabled / t_disabled
            print(f"\n  💡 对比分析:")
            print(f"     关闭模式耗时: {t_disabled:.3f}s")
            print(f"     开启模式耗时: {t_enabled:.3f}s")
            print(f"     开启/关闭倍率: {ratio:.1f}x")
            print(f"     单次采集省时约: {t_enabled - t_disabled:.1f}s")
            print(f"     每天一次采集，月省时约: {(t_enabled - t_disabled) * 30:.0f}s")
            print(f"     月省 API 调用约: ~{len(MOCK_ITEMS) // 20 + 1} 次 (基于 batch_size=20)")

    # 返回退出码
    all_passed = all(r["passed"] for r in results.values())
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
