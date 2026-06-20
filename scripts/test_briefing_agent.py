"""
简报 Agent 测试脚本
"""

import sys
import os
import json
import unittest
import unittest.mock
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from langgraph.graph import END
from agents.briefing_agent import (
    generate_briefing_node,
    brief_quality_check_node,
    should_retry_brief,
    _group_by_category,
    _render_markdown,
    _check_contradiction,
    _parse_json_response,
    BRIEFING_SCHEMA,
    MAX_ITEMS_PER_BRIEFING,
)


def _mock_state(overrides: dict) -> dict:
    """构造测试用 FeedLensState。"""
    return {
        "ranked_items": [],
        "goal_text": "关注新能源车和自动驾驶",
        "briefing": {},
        "briefing_result": {},
        "categories": ["科技", "商业", "社会", "其他"],
        **overrides,
    }


def _make_items(n: int = 5) -> list:
    """构造测试用 ranked_items。"""
    now = datetime.now().isoformat()
    items = [
        {
            "id": f"item_{i}",
            "title": f"测试新闻标题 {i}",
            "summary": f"这是第 {i} 条新闻的摘要内容",
            "source": "test_source",
            "published_at": now,
            "importance": 3 + (i % 3),
            "category": ["科技", "商业", "社会", "其他"][i % 4],
        }
        for i in range(1, n + 1)
    ]
    return items


class TestBriefingAgent(unittest.TestCase):

    def test_schema_exists(self):
        """BRIEFING_SCHEMA 存在且格式正确"""
        self.assertIn("title", BRIEFING_SCHEMA["properties"])
        self.assertIn("summary", BRIEFING_SCHEMA["properties"])
        self.assertIn("categories", BRIEFING_SCHEMA["properties"])
        self.assertIn("required", BRIEFING_SCHEMA)
        print("[PASS] BRIEFING_SCHEMA 存在且格式正确")

    def test_max_items_constant(self):
        """MAX_ITEMS_PER_BRIEFING = 10"""
        self.assertEqual(MAX_ITEMS_PER_BRIEFING, 10)
        print("[PASS] MAX_ITEMS_PER_BRIEFING = 10")

    def test_group_by_category(self):
        """items 按 category 分组，组内按 importance 降序"""
        items = _make_items(6)
        categories = ["科技", "商业", "社会", "其他"]
        grouped = _group_by_category(items, categories)

        # 验证分组
        self.assertIn("科技", grouped)
        self.assertIn("商业", grouped)
        self.assertIn("社会", grouped)
        self.assertIn("其他", grouped)

        # 验证组内按 importance 降序
        for cat, cat_items in grouped.items():
            if len(cat_items) > 1:
                for i in range(len(cat_items) - 1):
                    self.assertGreaterEqual(
                        cat_items[i].get("importance", 0),
                        cat_items[i + 1].get("importance", 0),
                        f"{cat} 组未按 importance 降序"
                    )
        print(f"[PASS] _group_by_category 分组正确，组内按 importance 降序")
        print(f"  分组结果: {{k: len(v) for k, v in grouped.items()}}")

    def test_generate_briefing_empty(self):
        """无条目时返回空简报"""
        state = _mock_state({"ranked_items": []})
        result = generate_briefing_node(state)

        self.assertIn("briefing", result)
        self.assertIn("briefing_result", result)
        self.assertEqual(result["briefing"]["title"], "暂无内容")
        self.assertEqual(result["briefing_result"]["brief_quality"], 1.0)
        print("[PASS] 无条目时返回空简报")

    def test_generate_briefing_with_items(self):
        """有条目时生成简报（Mock LLM，验证输出质量）"""
        items = _make_items(5)
        state = _mock_state({"ranked_items": items})

        # Mock LLM 返回有效 JSON
        mock_llm = unittest.mock.MagicMock()
        valid_json = json.dumps({
            "title": "AI 技术每日简报",
            "summary": "今日 AI 领域重要进展汇总",
            "categories": [
                {"name": "科技", "items": [
                    {"id": "item_1", "title": "AI 重大突破", "summary": "某AI公司发布新模型", "source": "src1", "published_at": "2024-01-01", "importance": 4},
                    {"id": "item_2", "title": "相关报道", "summary": "相关", "source": "src2", "published_at": "2024-01-01", "importance": 3},
                ]},
                {"name": "商业", "items": [
                    {"id": "item_3", "title": "AI 融资新闻", "summary": "某AI公司获投", "source": "src3", "published_at": "2024-01-02", "importance": 3},
                ]},
            ],
            "generated_at": "2024-01-01T12:00:00",
        }, ensure_ascii=False)
        mock_llm.chat.return_value = {"content": valid_json}

        with unittest.mock.patch("agents.briefing_agent._get_llm_provider", return_value=mock_llm):
            result = generate_briefing_node(state)

        self.assertIn("briefing", result)
        briefing = result["briefing"]
        self.assertEqual(briefing["title"], "AI 技术每日简报")
        self.assertEqual(briefing["summary"], "今日 AI 领域重要进展汇总")
        self.assertIn("_markdown", briefing)
        # categories 结构验证
        cats = briefing.get("categories", [])
        self.assertGreater(len(cats), 0, "categories 不应为空")
        for cat in cats:
            if cat["items"]:
                self.assertIn("similar_count", cat["items"][0], "category {} 主条目缺少 similar_count".format(cat["name"]))
        # Markdown 内容验证
        md = briefing["_markdown"]
        self.assertIn("AI 技术每日简报", md)
        self.assertIn("AI 重大突破", md)
        cats = briefing.get("categories", [])
        print(f"[PASS] 有条目时生成简报: {briefing.get('title', '')}")
        print(f"  categories: {[c['name'] for c in cats]}, items: {sum(len(c['items']) for c in cats)}条")

    def test_generate_briefing_llm_failure(self):
        """LLM 调用失败时触发 fallback 简报（不抛异常）"""
        items = _make_items(3)
        state = _mock_state({"ranked_items": items})
        mock_llm = unittest.mock.MagicMock()
        mock_llm.chat.side_effect = Exception("API unavailable")
        with unittest.mock.patch("agents.briefing_agent._get_llm_provider", return_value=mock_llm):
            result = generate_briefing_node(state)
        briefing = result["briefing"]
        self.assertIn("title", briefing)
        self.assertIn("_markdown", briefing)
        self.assertNotEqual(briefing.get("title"), "暂无内容", "fallback 简报应有标题")
        self.assertGreater(len(briefing.get("categories", [])), 0, "fallback 简报应有 categories")
        print("[PASS] LLM 失败时正确触发 fallback 简报")

    def test_quality_check_basic(self):
        """quality_check 返回四维评分"""
        state = _mock_state({
            "briefing": {
                "title": "测试简报",
                "summary": "测试摘要",
                "categories": [
                    {
                        "name": "科技",
                        "items": [
                            {"id": "item_1", "title": "测试标题", "summary": "测试摘要", "published_at": "2024-01-01"},
                            {"id": "item_2", "title": "另一个标题", "summary": "另一个摘要", "published_at": "2024-01-08"},
                        ]
                    }
                ]
            },
            "ranked_items": [{"id": "item_1"}, {"id": "item_2"}],
            "goal_text": "测试目标",
        })
        result = brief_quality_check_node(state)

        self.assertIn("brief_quality", result)
        self.assertIn("quality_detail", result)
        detail = result["quality_detail"]
        self.assertIn("completeness", detail)
        self.assertIn("relevance", detail)
        self.assertIn("coherence", detail)
        self.assertIn("score", detail)
        self.assertIn("contradictions", detail)
        print(f"[PASS] quality_check 四维评分: completeness={detail['completeness']:.2f}, relevance={detail['relevance']:.2f}, coherence={detail['coherence']:.2f}, score={detail['score']:.4f}")

    def test_quality_check_contradiction(self):
        """时间相差超过7天的条目应被标记为矛盾"""
        item1 = {"id": "a", "published_at": "2024-01-01T00:00:00", "importance": 3}
        item2 = {"id": "b", "published_at": "2024-01-15T00:00:00", "importance": 3}
        # 相差14天 > 7天，应该返回 True
        self.assertTrue(_check_contradiction(item1, item2))

        # 相近时间不应标记为矛盾
        item3 = {"id": "c", "published_at": "2024-01-02T00:00:00", "importance": 3}
        item4 = {"id": "d", "published_at": "2024-01-03T00:00:00", "importance": 3}
        self.assertFalse(_check_contradiction(item3, item4))
        print("[PASS] 矛盾检测逻辑正确")

    def test_should_retry_brief(self):
        """质量 < 0.7 且 retry < 2 应重试"""
        # 质量低，应重试
        state1 = _mock_state({
            "brief_quality": 0.5,
            "briefing_result": {"retry_count": 0},
        })
        self.assertEqual(should_retry_brief(state1), "generate_briefing")

        # 质量高，不重试
        state2 = _mock_state({
            "brief_quality": 0.8,
            "briefing_result": {"retry_count": 0},
        })
        self.assertEqual(should_retry_brief(state2), END)

        # 质量低但已重试2次，不重试
        state3 = _mock_state({
            "brief_quality": 0.5,
            "briefing_result": {"retry_count": 2},
        })
        self.assertEqual(should_retry_brief(state3), END)
        print("[PASS] should_retry_brief 逻辑正确")

    def test_parse_json_response(self):
        """JSON 解析正确处理各种输入格式"""
        # 正常 JSON
        normal = '{"title": "test", "summary": "desc"}'
        result = _parse_json_response(normal)
        self.assertEqual(result.get("title"), "test")

        # 带 ```json 包裹
        with_code = '```json\n{"title": "test2"}\n```'
        result = _parse_json_response(with_code)
        self.assertEqual(result.get("title"), "test2")

        # 无效 JSON 返回 error
        invalid = "not json at all"
        result = _parse_json_response(invalid)
        self.assertIn("error", result)
        print("[PASS] JSON 解析处理各种输入格式正确")

    def test_render_markdown(self):
        """JSON 简报正确渲染为 Markdown"""
        briefing = {
            "title": "测试简报",
            "summary": "这是测试摘要",
            "categories": [
                {
                    "name": "科技",
                    "items": [
                        {"id": "i1", "title": "主条目", "summary": "主条目摘要", "source": "src1", "published_at": "2024-01-01", "importance": 4, "similar_count": 2},
                        {"id": "i2", "title": "其他条目1", "summary": ""},
                    ]
                }
            ],
            "generated_at": "2024-01-01T12:00:00",
        }
        md = _render_markdown(briefing)

        self.assertIn("# 测试简报", md)
        self.assertIn("> 这是测试摘要", md)
        self.assertIn("## 科技", md)
        self.assertIn("### 主条目", md)
        self.assertIn("还有 2 篇类似报道", md)
        self.assertIn("其他条目1", md)
        print("[PASS] Markdown 渲染正确")
        print(f"  Markdown 预览:\n{md[:300]}")



    def test_full_workflow(self):
        """端到端 StateGraph 工作流（generate -> quality_check -> retry -> done）"""
        from agents.briefing_agent import build_briefing_agent
        items = _make_items(5)
        state = _mock_state({"ranked_items": items})

        mock_llm = unittest.mock.MagicMock()
        valid_json = json.dumps({
            "title": "工作流测试简报",
            "summary": "全流程验证",
            "categories": [
                {"name": "科技", "items": [
                    {"id": "item_1", "title": "测试", "summary": "测试", "source": "s1", "published_at": "2024-01-01", "importance": 3},
                ]},
            ],
            "generated_at": "2024-01-01T12:00:00",
        }, ensure_ascii=False)
        mock_llm.chat.return_value = {"content": valid_json}

        with unittest.mock.patch("agents.briefing_agent._get_llm_provider", return_value=mock_llm):
            agent = build_briefing_agent()
            result = agent.invoke(state)

        self.assertIn("briefing", result)
        self.assertIn("brief_quality", result)
        self.assertGreater(result["brief_quality"], 0, "brief_quality 应 > 0")
        quality = result.get("brief_quality", 0)
        retry = result.get("briefing_result", {}).get("retry_count", 0)
        print(f"[PASS] 端到端工作流: quality={quality:.2f}, retry={retry}")

def run_tests():
    print("=" * 50)
    print("简报 Agent 单元测试")
    print("=" * 50)

    suite = unittest.TestLoader().loadTestsFromTestCase(TestBriefingAgent)
    runner = unittest.TextTestRunner(verbosity=0)
    result = runner.run(suite)

    print("")
    print("=" * 50)
    passed = result.testsRun - len(result.failures) - len(result.errors)
    total = result.testsRun
    print(f"测试结果: {passed}/{total} 通过")
    if result.failures:
        print(f"失败: {len(result.failures)}")
        for _, traceback in result.failures:
            print(traceback)
    if result.errors:
        print(f"错误: {len(result.errors)}")
        for _, traceback in result.errors:
            print(traceback)
    print("=" * 50)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
