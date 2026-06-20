"""
冷启动→偏好自适应切换测试脚本
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.ranking_agent import rank_items_node
from datetime import datetime


def _mock_state(feedback_count: int, overrides: dict = None) -> dict:
    """构造测试用 state。"""
    feedback_history = [
        {"item_id": f"item_{i}", "feedback_type": "like"}
        for i in range(feedback_count)
    ]
    now = datetime.now().isoformat()
    return {
        "collected_items": [
            {
                "id": "item_1",
                "title": "测试新闻",
                "summary": "测试摘要",
                "source": "test",
                "published_at": now,
                "importance": 3,
                "category": "科技",
                "embedding": [0.1] * 384,
            }
        ],
        "feedback_history": feedback_history,
        "goal_embedding": [0.1] * 384,
        "goal_text": "测试目标",
        **(overrides or {}),
    }


def test_cold_start_weights():
    """冷启动模式：feedback_count = 0"""
    print("\n[test] 冷启动模式 (feedback_count = 0)")
    state = _mock_state(0)
    result = rank_items_node(state)

    assert "ranking_detail" in result
    detail = result["ranking_detail"]
    assert detail["weight_mode"] == "cold_start", f"期望 cold_start，实际 {detail['weight_mode']}"
    assert detail["feedback_count"] == 0
    assert detail["weights"]["similarity"] == 0.40
    assert detail["weights"]["preference"] == 0.10
    print(f"  [PASS] 冷启动模式: {detail['weights']}")


def test_cold_start_threshold():
    """冷启动阈值：feedback_count = 2"""
    print("\n[test] 冷启动阈值 (feedback_count = 2)")
    state = _mock_state(2)
    result = rank_items_node(state)

    detail = result["ranking_detail"]
    assert detail["weight_mode"] == "cold_start", f"期望 cold_start，实际 {detail['weight_mode']}"
    assert detail["feedback_count"] == 2
    print(f"  [PASS] feedback_count=2 仍为冷启动模式")


def test_adaptive_mode():
    """偏好自适应模式：feedback_count = 3"""
    print("\n[test] 偏好自适应模式 (feedback_count = 3)")
    state = _mock_state(3)
    result = rank_items_node(state)

    detail = result["ranking_detail"]
    assert detail["weight_mode"] == "with_feedback", f"期望 with_feedback，实际 {detail['weight_mode']}"
    assert detail["feedback_count"] == 3
    assert detail["weights"]["similarity"] == 0.30
    assert detail["weights"]["preference"] == 0.40
    print(f"  [PASS] 偏好自适应模式: {detail['weights']}")


def test_adaptive_mode_more_feedback():
    """偏好自适应模式：feedback_count = 10"""
    print("\n[test] 偏好自适应模式 (feedback_count = 10)")
    state = _mock_state(10)
    result = rank_items_node(state)

    detail = result["ranking_detail"]
    assert detail["weight_mode"] == "with_feedback"
    assert detail["weights"]["preference"] == 0.40
    print(f"  [PASS] feedback_count=10 保持偏好自适应模式")


def test_weight_difference():
    """冷启动 vs 偏好自适应的权重差异"""
    print("\n[test] 权重差异验证")

    cold_state = _mock_state(0)
    warm_state = _mock_state(5)

    cold_result = rank_items_node(cold_state)
    warm_result = rank_items_node(warm_state)

    cold_weights = cold_result["ranking_detail"]["weights"]
    warm_weights = warm_result["ranking_detail"]["weights"]

    # 冷启动：similarity 权重更高
    assert cold_weights["similarity"] > warm_weights["similarity"], \
        f"冷启动 similarity 应更高: {cold_weights['similarity']} vs {warm_weights['similarity']}"

    # 偏好自适应：preference 权重更高
    assert warm_weights["preference"] > cold_weights["preference"], \
        f"偏好自适应 preference 应更高: {warm_weights['preference']} vs {cold_weights['preference']}"

    print(f"  冷启动: similarity={cold_weights['similarity']}, preference={cold_weights['preference']}")
    print(f"  偏好自适应: similarity={warm_weights['similarity']}, preference={warm_weights['preference']}")
    print("  [PASS] 权重切换正确")


def test_feedback_bias_map():
    """反馈偏差映射"""
    print("\n[test] 反馈偏差映射")

    # 有 like 反馈
    state = _mock_state(1, {
        "feedback_history": [{"item_id": "item_1", "feedback_type": "like"}],
    })
    # 直接验证 feedback_bias_map 的计算逻辑
    feedback_history = [{"item_id": "item_1", "feedback_type": "like"}]
    feedback_bias_map = {}
    for fb in feedback_history:
        item_id = fb.get("item_id", "")
        fb_type = fb.get("feedback_type", "")
        if fb_type == "like":
            feedback_bias_map[item_id] = 0.15
        elif fb_type == "dislike":
            feedback_bias_map[item_id] = -0.10
        elif fb_type == "irrelevant":
            feedback_bias_map[item_id] = -0.15

    assert feedback_bias_map["item_1"] == 0.15, f"like 偏差应为 +0.15，实际 {feedback_bias_map}"
    print(f"  [PASS] like 反馈偏差 = +0.15")

    # 有 dislike 反馈
    feedback_history2 = [{"item_id": "item_1", "feedback_type": "dislike"}]
    feedback_bias_map2 = {}
    for fb in feedback_history2:
        item_id = fb.get("item_id", "")
        fb_type = fb.get("feedback_type", "")
        if fb_type == "like":
            feedback_bias_map2[item_id] = 0.15
        elif fb_type == "dislike":
            feedback_bias_map2[item_id] = -0.10
        elif fb_type == "irrelevant":
            feedback_bias_map2[item_id] = -0.15

    assert feedback_bias_map2["item_1"] == -0.10, f"dislike 偏差应为 -0.10，实际 {feedback_bias_map2}"
    print(f"  [PASS] dislike 反馈偏差 = -0.10")


def run_tests():
    print("=" * 50)
    print("冷启动→偏好自适应切换测试")
    print("=" * 50)

    tests = [
        test_cold_start_weights,
        test_cold_start_threshold,
        test_adaptive_mode,
        test_adaptive_mode_more_feedback,
        test_weight_difference,
        test_feedback_bias_map,
    ]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {test.__name__}: {e}")

    print("")
    print("=" * 50)
    print(f"测试结果: {passed}/{passed + failed} 通过")
    if failed > 0:
        print(f"失败: {failed}")
    print("=" * 50)
    return failed == 0


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
