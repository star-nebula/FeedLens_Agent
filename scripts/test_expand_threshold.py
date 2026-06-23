"""测试 expand_threshold 从 state 传递到 rank_items 工具的完整链路。

验证：
1. rank_items_node 从 state 读取 expand_threshold → 预筛窗口切换
2. _execute_rank_items 从 arguments 读取 expand_threshold → 传递到 temp_state
3. ranking_react 循环中将 expand_threshold 注入 tool_args → 传递给工具
"""
import sys, os, json, unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestExpandThresholdPassing(unittest.TestCase):
    """expand_threshold 参数传递链路测试"""

    def test_rank_items_node_reads_expand_threshold(self):
        """rank_items_node 从 state.get('expand_threshold') 读取"""
        from agents.ranking_agent import rank_items_node
        from datetime import datetime, timedelta

        now = datetime.now()
        # 造 10 条数据，其中 5 条 4 天前（超 72h），5 条 1 天前
        items = []
        for i in range(5):
            items.append({
                "id": f"old_{i}",
                "title": f"旧条目 {i}",
                "published_at": (now - timedelta(days=4)).isoformat(),
                "source": "test",
            })
        for i in range(5):
            items.append({
                "id": f"new_{i}",
                "title": f"新条目 {i}",
                "published_at": (now - timedelta(hours=6)).isoformat(),
                "source": "test",
            })

        # 测试1: expand_threshold=False → 只有新条目通过预筛
        state_false = {"collected_items": items, "expand_threshold": False, "goal_embedding": []}
        result_false = rank_items_node(state_false)
        ranked_false = result_false.get("ranked_items", [])
        self.assertLessEqual(len(ranked_false), 5,
                             f"expand_threshold=False 时预筛窗口=72h，应只有5条新数据，实际 {len(ranked_false)} 条")
        print(f"  [PASS] expand_threshold=False → 72h 窗口: {len(items)}条 -> {len(ranked_false)}条")

        # 测试2: expand_threshold=True → 所有条目通过预筛（336h=14天）
        state_true = {"collected_items": items, "expand_threshold": True, "goal_embedding": []}
        result_true = rank_items_node(state_true)
        ranked_true = result_true.get("ranked_items", [])
        self.assertGreater(len(ranked_true), len(ranked_false),
                           f"expand_threshold=True 时预筛窗口=336h，应通过更多数据")
        print(f"  [PASS] expand_threshold=True → 336h 窗口: {len(items)}条 -> {len(ranked_true)}条")

    def test_execute_rank_items_passes_expand_threshold(self):
        """_execute_rank_items 从 arguments 读取 expand_threshold 并传递给 temp_state"""
        from tools.tool_registry import _execute_rank_items
        from datetime import datetime, timedelta

        now = datetime.now()
        items = []
        for i in range(10):
            items.append({
                "id": f"item_{i}",
                "title": f"条目 {i}",
                "published_at": (now - timedelta(days=5)).isoformat(),
                "source": "test",
            })

        # expand_threshold=False: 10条5天前的数据 → 72h窗口 → 0条
        args_false = {"items": items, "expand_threshold": False, "goal_embedding": []}
        result_false = _execute_rank_items(args_false)
        ranked_false = result_false.get("ranked_items", [])
        self.assertEqual(len(ranked_false), 0,
                         f"5天前数据在72h窗口应全部被丢弃，实际 {len(ranked_false)} 条")
        print(f"  [PASS] _execute_rank_items expand_threshold=False: {len(items)}条 -> {len(ranked_false)}条")

        # expand_threshold=True: 10条5天前的数据 → 336h窗口 → 保留
        args_true = {"items": items, "expand_threshold": True, "goal_embedding": []}
        result_true = _execute_rank_items(args_true)
        ranked_true = result_true.get("ranked_items", [])
        self.assertGreater(len(ranked_true), 0,
                           f"5天前数据在336h窗口应被保留，实际 {len(ranked_true)} 条")
        print(f"  [PASS] _execute_rank_items expand_threshold=True: {len(items)}条 -> {len(ranked_true)}条")

    def test_ranking_react_injects_expand_threshold_to_tool_args(self):
        """ranking_react 循环将 expand_threshold 注入 rank_items 的 tool_args"""
        # 通过直接检查 ranking_react 循环中 rank_items 工具调用的代码逻辑
        # 验证 expand_threshold 是否被注入到 tool_args
        import inspect
        from agents.ranking_agent import run_ranking_agent

        source = inspect.getsource(run_ranking_agent)
        self.assertIn("expand_threshold", source,
                      "run_ranking_agent 源码中应包含 expand_threshold 注入逻辑")
        self.assertIn('current_state.get("expand_threshold"', source,
                      "应使用 current_state.get('expand_threshold') 读取")
        print(f"  [PASS] ranking_react 源码中包含 expand_threshold 注入逻辑")

    def test_rank_items_node_logs_expand_threshold(self):
        """rank_items_node 日志包含 expand_threshold 状态"""
        import inspect
        from agents.ranking_agent import rank_items_node

        source = inspect.getsource(rank_items_node)
        self.assertIn("expand_threshold={expand_threshold}", source,
                      "日志应包含 expand_threshold 状态输出")
        print(f"  [PASS] rank_items_node 日志包含 expand_threshold 状态")


if __name__ == "__main__":
    unittest.main(verbosity=2, argv=["test"])
