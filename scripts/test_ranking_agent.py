"""
排序 Agent 测试脚本（重点测试去重功能）。

测试内容：
  1. StateGraph 构建
  2. vector_search_node 节点（偏好检索）
  3. deduplicate_node 节点（向量去重核心）
  4. rank_items_node 节点（多因子排序）
  5. should_rerank 条件边逻辑
  6. 完整工作流集成测试

Usage:
    python scripts/test_ranking_agent.py
"""

import sys
import os
import asyncio
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from agents.ranking_agent import (
    build_ranking_agent,
    vector_search_node,
    deduplicate_node,
    rank_items_node,
    should_rerank,
)
from agents.state import FeedLensState


# ============================================================
# 辅助
# ============================================================

def make_state(**kwargs) -> FeedLensState:
    """构造测试状态。"""
    return {
        "session_id": "test-session",
        "user_id": 1,
        "trigger_type": "daily_briefing",
        "goal_text": "关注 AI Agent 技术进展",
        "structured_goal": {
            "topics": ["AI Agent", "大模型", "多智能体"],
            "keywords": ["AI", "Agent", "LLM"],
        },
        **kwargs,
    }


def make_test_items(count: int = 5, add_duplicates: bool = False) -> list:
    """构造测试条目。"""
    items = []
    base_title = "AI Agent 技术最新进展"
    topics = ["机器学习", "深度学习", "自然语言处理", "计算机视觉", "强化学习", "推荐系统"]
    summaries = [
        "机器学习算法在金融领域的应用越来越广泛，帮助银行实现智能风控。",
        "深度学习模型通过多层神经网络提取特征，在图像识别任务中取得突破性进展。",
        "自然语言处理技术让机器能够理解和生成人类语言，推动智能助手的发展。",
        "计算机视觉技术实现了图像分类、目标检测和语义分割等功能。",
        "强化学习通过试错学习策略，在游戏和机器人控制领域表现出色。",
        "推荐系统根据用户行为数据，为用户提供个性化的内容推荐服务。",
    ]
    for i in range(count):
        if add_duplicates and i >= 2:
            items.append({
                "id": f"item-{i}",
                "title": base_title if i % 2 == 0 else f"{base_title}（续）",
                "summary": "人工智能 Agent 技术正在快速发展，LLM 作为核心驱动力。",
                "url": f"http://example.com/{i}",
                "category": "technology",
                "importance": 0.7,
                "published_at": datetime.now().isoformat(),
            })
        else:
            topic = topics[i % len(topics)]
            summary = summaries[i % len(summaries)]
            items.append({
                "id": f"item-{i}",
                "title": f"{topic} 技术应用报告 {i+1}",
                "summary": summary,
                "url": f"http://example.com/{i}",
                "category": topic,
                "importance": 0.5 + i * 0.1,
                "published_at": datetime.now().isoformat(),
            })
    return items


# ============================================================
# 测试用例
# ============================================================

def test_build_graph():
    """测试 StateGraph 能正常编译。"""
    print("\n" + "=" * 60)
    print("[test] build_ranking_agent - StateGraph 编译")
    print("=" * 60)
    try:
        agent = build_ranking_agent()
        assert agent is not None
        print("✓ StateGraph 编译成功")
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_vector_search_node():
    """测试 vector_search_node（偏好检索）。"""
    print("\n" + "=" * 60)
    print("[test] vector_search_node - 偏好向量检索")
    print("=" * 60)

    state = make_state()
    try:
        result = vector_search_node(state)
        prefs = result.get("user_preferences", [])
        feedback = result.get("feedback_history", [])
        print(f"✓ 检索完成: preferences={len(prefs)}, feedback={len(feedback)}")
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_deduplicate_node_basic():
    """测试 deduplicate_node（基础去重逻辑）。"""
    print("\n" + "=" * 60)
    print("[test] deduplicate_node - 基础去重（无重复）")
    print("=" * 60)

    items = make_test_items(count=5, add_duplicates=False)
    state = make_state(collected_items=items)
    try:
        result = deduplicate_node(state)
        deduped = result.get("collected_items", [])
        relations = result.get("item_relations", [])
        print(f"✓ 去重完成: {len(deduped)} 条保留, {len(relations)} 对去重")
        assert len(deduped) == 5, "无重复数据应全部保留"
        assert len(relations) == 0, "无重复数据应无去重关系"
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_deduplicate_node_with_duplicates():
    """测试 deduplicate_node（含重复数据）。"""
    print("\n" + "=" * 60)
    print("[test] deduplicate_node - 含重复数据去重")
    print("=" * 60)

    items = make_test_items(count=6, add_duplicates=True)
    state = make_state(collected_items=items)
    try:
        result = deduplicate_node(state)
        deduped = result.get("collected_items", [])
        relations = result.get("item_relations", [])
        print(f"✓ 去重完成: {len(deduped)} 条保留, {len(relations)} 对去重")
        print(f"  similar_count 检查: {[item.get('similar_count', 1) for item in deduped]}")
        # 验证 similar_count 字段存在
        assert all("similar_count" in item for item in deduped)
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_deduplicate_node_empty():
    """测试 deduplicate_node（空输入）。"""
    print("\n" + "=" * 60)
    print("[test] deduplicate_node - 空输入")
    print("=" * 60)

    state = make_state(collected_items=[])
    result = deduplicate_node(state)
    assert result.get("collected_items") == []
    assert result.get("item_relations") == []
    print("✓ 空输入处理正确")
    return True


def test_rank_items_node():
    """测试 rank_items_node（多因子排序）。"""
    print("\n" + "=" * 60)
    print("[test] rank_items_node - 多因子排序")
    print("=" * 60)

    items = make_test_items(count=5, add_duplicates=False)
    state = make_state(
        collected_items=items,
        user_preferences=[],
        feedback_history=[],
    )
    try:
        result = rank_items_node(state)
        ranked = result.get("ranked_items", [])
        detail = result.get("ranking_detail", {})
        print(f"✓ 排序完成: {len(ranked)} 条, top_score={detail.get('top_score', 0):.4f}")
        if ranked:
            print(f"  排序前 3:")
            for i, item in enumerate(ranked[:3]):
                print(f"    [{i+1}] {item['title']} (score={item.get('_score', 0):.4f})")
            assert "_score" in ranked[0], "应有评分字段"
            assert "_score_detail" in ranked[0], "应有评分详情"
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_should_rerank():
    """测试 should_rerank 条件边逻辑。"""
    print("\n" + "=" * 60)
    print("[test] should_rerank - 条件边逻辑")
    print("=" * 60)

    # 测试1: 少于3条 → 标记需重新采集
    state = make_state(collected_items=[], ranking_detail={"top_score": 0.8})
    assert should_rerank(state) == "__end__"
    print("✓ 0 条 → END (标记需重新采集)")

    # 测试2: 2条 → 标记需重新采集
    state = make_state(collected_items=[{}, {}], ranking_detail={"top_score": 0.8})
    assert should_rerank(state) == "__end__"
    print("✓ 2 条 → END (标记需重新采集)")

    # 测试3: 3条但分低 → 调参重排
    state = make_state(collected_items=[{}, {}, {}], ranking_detail={"top_score": 0.2})
    assert should_rerank(state) == "rank_items"
    print("✓ 3 条, score=0.2 → rank_items")

    # 测试4: 3条且分高 → Done
    state = make_state(collected_items=[{}, {}, {}], ranking_detail={"top_score": 0.6})
    assert should_rerank(state) == "__end__"
    print("✓ 3 条, score=0.6 → END")

    # 测试5: 10条且分高 → Done
    state = make_state(collected_items=[{} for _ in range(10)], ranking_detail={"top_score": 0.5})
    assert should_rerank(state) == "__end__"
    print("✓ 10 条, score=0.5 → END")
    return True


async def test_full_workflow():
    """测试完整工作流。"""
    print("\n" + "=" * 60)
    print("[test] 完整工作流集成测试")
    print("=" * 60)

    agent = build_ranking_agent()

    items = make_test_items(count=8, add_duplicates=True)
    state = make_state(
        collected_items=items,
        structured_goal={"topics": ["AI"], "keywords": ["人工智能"]},
    )

    try:
        result = await agent.ainvoke(state)
        ranked = result.get("ranked_items", [])
        relations = result.get("item_relations", [])
        detail = result.get("ranking_detail", {})
        print(f"✓ 工作流完成: ranked={len(ranked)}, relations={len(relations)}, top_score={detail.get('top_score', 0):.4f}")
        if ranked:
            print(f"  字段示例: {list(ranked[0].keys())[:10]}...")
            assert "id" in ranked[0]
            assert "_score" in ranked[0]
            assert "similar_count" in ranked[0]
        return True
    except Exception as e:
        print(f"✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================
# 主流程
# ============================================================

async def main():
    print("FeedLens 排序 Agent 测试脚本（重点测试去重功能）")

    results = []
    results.append(("build_graph", test_build_graph()))
    results.append(("vector_search_node", test_vector_search_node()))
    results.append(("deduplicate_node_basic", test_deduplicate_node_basic()))
    results.append(("deduplicate_node_with_duplicates", test_deduplicate_node_with_duplicates()))
    results.append(("deduplicate_node_empty", test_deduplicate_node_empty()))
    results.append(("rank_items_node", test_rank_items_node()))
    results.append(("should_rerank", test_should_rerank()))
    results.append(("full_workflow", await test_full_workflow()))

    print("\n" + "=" * 60)
    print("[summary] 测试结果汇总")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        status = "PASS" if ok else "FAIL"
        print(f"  {status:6}  {name}")
    print(f"\n总计: {passed}/{total} 通过")

    return all(ok for _, ok in results)


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
