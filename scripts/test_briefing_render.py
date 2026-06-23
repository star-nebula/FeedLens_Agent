"""测试简报渲染修复：统一格式、时间回填、评分显示、类似报道展开"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.briefing_agent import _render_markdown, _backfill_briefing_items

def test_render_unified_format():
    """测试1: 分类标题和条目在同一文本框内，无 h3 分割"""
    briefing = {
        "title": "派早报：英特尔将为苹果代工芯片",
        "summary": "英特尔将为苹果代工芯片，库克称iPhone涨价不可避免。",
        "categories": [
            {
                "name": "数据安全与隐私",
                "count": 1,
                "items": [{
                    "title": "Meta因数据安全问题暂停追踪员工鼠标活动的AI训练项目",
                    "summary": "Meta暂停用于AI训练的内部数据追踪项目。",
                    "url": "https://36kr.com/p/12345",
                    "source": "36氪",
                    "published_at": "2026-06-21T23:13:00Z",
                    "importance": 4,
                    "final_score": 0.344,
                    "similar_count": 0,
                }]
            }
        ],
        "generated_at": "2026-06-23T14:30:00Z",
    }
    md = _render_markdown(briefing)
    
    # 不应该有 h3 (###) 标题——所有内容在一个文本块
    assert "###" not in md, f"不应出现 ### 分割标题，但发现:\n{md}"
    # 应该有粗体标题
    assert "**Meta因数据安全问题" in md, f"主条目应为粗体格式:\n{md}"
    # 应该有评分
    assert "评分: 0.344" in md, f"应显示评分:\n{md}"
    # 应该有来源和时间
    assert "来源: 36氪" in md, f"应显示来源:\n{md}"
    assert "2026-06-21 23:13:00" in md, f"应显示格式化时间:\n{md}"
    # 应该有重要性
    assert "重要性: 4/5" in md, f"应显示重要性:\n{md}"
    # 元信息应在同一行
    lines = md.split("\n")
    meta_line = [l for l in lines if "来源:" in l and "时间:" in l and "评分:" in l]
    assert meta_line, f"元信息应在同一行，但未找到合并行:\n{md}"
    print(f"[PASS] 测试1: 统一格式 ✅")
    print(f"  输出:\n{md}")

def test_backfill_published_at():
    """测试2: published_at 回填强制覆盖（即使 LLM 生成了值）"""
    briefing = {
        "categories": [{
            "items": [{
                "id": "item_1",
                "published_at": "未知时间",  # LLM 生成的错误值
                "source": "",
                "url": "",
            }]
        }]
    }
    item_index = {
        "item_1": {
            "published_at": "2026-06-21T23:13:00Z",
            "source": "36氪",
            "url": "https://36kr.com/p/12345",
            "importance": 4,
        }
    }
    _backfill_briefing_items(briefing, item_index)
    item = briefing["categories"][0]["items"][0]
    assert item["published_at"] == "2026-06-21T23:13:00Z", \
        f"published_at 应被强制覆盖为原始值，实际: {item['published_at']}"
    assert item["source"] == "36氪", f"source 应被回填，实际: {item['source']}"
    print(f"[PASS] 测试2: published_at 强制覆盖 ✅")

def test_backfill_final_score():
    """测试3: _score → final_score 映射回填"""
    briefing = {
        "categories": [{
            "items": [{
                "id": "item_1",
                "title": "test",
            }]
        }]
    }
    item_index = {
        "item_1": {
            "_score": 0.567,
            "title": "test",
            "published_at": "2026-06-21T23:13:00Z",
            "source": "test",
            "url": "",
            "importance": 3,
            "category": "tech",
        }
    }
    _backfill_briefing_items(briefing, item_index)
    item = briefing["categories"][0]["items"][0]
    assert item.get("final_score") == 0.567, \
        f"final_score 应从 _score 映射，实际: {item.get('final_score')}"
    print(f"[PASS] 测试3: _score → final_score 映射 ✅")

def test_similar_items_expand():
    """测试4: 类似报道子条目展开显示"""
    briefing = {
        "title": "测试简报",
        "summary": "测试摘要",
        "categories": [{
            "name": "科技",
            "count": 4,
            "items": [
                {
                    "title": "主条目标题",
                    "summary": "主条目摘要",
                    "url": "https://example.com/1",
                    "source": "来源A",
                    "published_at": "2026-06-21T10:00:00Z",
                    "importance": 4,
                    "final_score": 0.5,
                    "similar_count": 3,
                },
                {"title": "子条目1"},
                {"title": "子条目2"},
                {"title": "子条目3"},
            ]
        }],
        "generated_at": "2026-06-23T14:30:00Z",
    }
    md = _render_markdown(briefing)
    assert "还有 3 篇类似报道" in md, f"应显示类似报道数量:\n{md}"
    assert "- 子条目1" in md, f"应显示子条目1:\n{md}"
    assert "- 子条目2" in md, f"应显示子条目2:\n{md}"
    assert "- 子条目3" in md, f"应显示子条目3:\n{md}"
    # 子条目不应包含 ### 标题
    assert "###" not in md, f"不应有 ### 分割:\n{md}"
    print(f"[PASS] 测试4: 类似报道展开 ✅")
    print(f"  输出:\n{md}")

def test_no_score_when_missing():
    """测试5: 无评分时不显示评分字段"""
    briefing = {
        "title": "测试",
        "summary": "",
        "categories": [{
            "name": "测试分类",
            "count": 1,
            "items": [{
                "title": "无评分条目",
                "summary": "",
                "url": "",
                "source": "test",
                "published_at": "2026-06-21T10:00:00Z",
                "importance": 3,
            }]
        }],
        "generated_at": "",
    }
    md = _render_markdown(briefing)
    assert "评分:" not in md, f"无评分时不应显示评分:\n{md}"
    print(f"[PASS] 测试5: 无评分时不显示 ✅")

if __name__ == "__main__":
    test_render_unified_format()
    test_backfill_published_at()
    test_backfill_final_score()
    test_similar_items_expand()
    test_no_score_when_missing()
    print("\n🎉 全部 5 项测试通过！")
