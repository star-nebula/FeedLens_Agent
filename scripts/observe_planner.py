"""
Planner 预判能力观察脚本。

用途：
    单独运行 main_agent 的 planner_node（真实 LLM），针对几种典型状态
    打印 LLM 原始返回 + 解析后的编排计划，直观判断 Planner 是否
    "主动预判跨 Agent 需求"。

观察要点（"主动预判"的表现）：
    1. 单次 plan 里一次性安排多个子 Agent（如 Collection→Ranking→Briefing），
       而不是只安排眼前一步 —— 说明它预判到下游需要。
    2. 根据 observation_result 的 suggested_action 主动给 params 注入
       search_expand / expand_threshold / rerank 等，而非空 params。
    3. 根据 memory.relevant_history 调整策略（历史经验复用）。
    4. 根据 top_score / 采集数预判 push_immediate（重大事件）。

运行：
    python scripts/observe_planner.py            # 跑全部场景
    python scripts/observe_planner.py --scene 1  # 只跑场景 1
"""

import sys
import os
import json
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from agents.main_agent import planner_node, _build_planner_context, _get_llm_provider
from agents.main_agent import PLANNER_SYSTEM_PROMPT
from agents.state import FeedLensState


def _base_state(overrides: dict = None) -> dict:
    base = {
        "trigger_type": "daily_briefing",
        "session_id": f"observe_{datetime.now().strftime('%H%M%S')}",
        "user_id": 1,
        "goal_text": "关注 AI Agent 和大模型技术进展",
        "structured_goal": {"topics": ["AI Agent", "大模型"], "keywords": ["LLM", "多智能体"]},
        "goal_embedding": [0.1] * 384,
        "react_cycle_count": 0,
        "collected_items": [],
        "ranked_items": [],
        "ranking_detail": {},
        "briefing": {},
        "brief_quality": 0.0,
        "observation_result": {},
        "search_supplemented": False,
        "sub_agent_plan": [],
        "planner_reason": "",
        "push_immediate": False,
    }
    if overrides:
        base.update(overrides)
    return base


SCENES = {
    "1": ("首次编排：空状态，看是否预判标准三段链", _base_state()),
    "2": ("采集不足建议补充：看是否主动 search_expand 并衔接 Ranking", _base_state({
        "react_cycle_count": 1,
        "observation_result": {"suggested_action": "search_expand", "needs_retry": True, "collection_ok": False},
        "collected_items": [{"id": 1}],
    })),
    "3": ("采集足但简报条目不足：看是否预判 expand_threshold 而非重新采集", _base_state({
        "react_cycle_count": 1,
        "collected_items": [{"id": i} for i in range(12)],
        "ranked_items": [{"id": i, "_score": 0.6} for i in range(5)],
        "ranking_detail": {"top_score": 0.6},
        "observation_result": {"suggested_action": "expand_threshold", "needs_retry": True},
    })),
    "4": ("重大事件信号：top_score=0.9，看是否预判 push_immediate", _base_state({
        "ranked_items": [{"id": 1, "_score": 0.92, "importance": 0.95, "title": "重大突破"}],
        "ranking_detail": {"top_score": 0.92},
    })),
    "5": ("已两轮：看是否收敛/跳过非必要步骤", _base_state({
        "react_cycle_count": 2,
        "collected_items": [{"id": i} for i in range(8)],
        "ranked_items": [{"id": i, "_score": 0.55} for i in range(8)],
        "ranking_detail": {"top_score": 0.55},
        "brief_quality": 0.75,
        "observation_result": {"needs_retry": True},
    })),
}


def _print_header(title: str):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def _judge(plan: dict) -> list:
    """根据 plan 内容，标注哪些信号体现了"主动预判"。"""
    signals = []
    agents = [p.get("agent") for p in plan.get("sub_agent_plan", [])]
    params_list = [p.get("params", {}) for p in plan.get("sub_agent_plan", [])]

    if len(agents) >= 2:
        signals.append(f"多 Agent 链式编排 {agents} —— 预判下游需要")
    has_params = any(p for p in params_list)
    if has_params:
        signals.append(f"主动注入 params {params_list} —— 预判子 Agent 细节需求")
    if plan.get("push_immediate"):
        signals.append("push_immediate=True —— 预判重大事件需即时推送")
    if len(agents) == 1:
        signals.append(f"单步聚焦 {agents} —— 未预判下游（或刻意收敛）")
    if not signals:
        signals.append("无明显预判信号（可能依赖 fallback）")
    return signals


def run_scene(key: str):
    title, state = SCENES[key]
    _print_header(f"场景 {key}: {title}")

    # 先打印喂给 LLM 的上下文（含 memory）
    print("\n[上下文 _build_planner_context]")
    try:
        ctx = _build_planner_context(state)
        print(json.dumps(ctx, ensure_ascii=False, indent=2, default=str)[:1200])
    except Exception as e:
        print(f"  构建上下文失败: {e}")

    # 直接看 LLM 原始返回，绕过 planner_node 的解析，便于排查
    print("\n[LLM 原始返回]")
    try:
        llm = _get_llm_provider()
        ctx = _build_planner_context(state)
        raw = llm.chat(
            [{"role": "system", "content": PLANNER_SYSTEM_PROMPT},
             {"role": "user", "content": json.dumps(ctx, ensure_ascii=False)}],
            temperature=0.3,
            max_tokens=1024,
        )
        text = raw if isinstance(raw, str) else raw.get("content", "")
        print(text[:1500])
    except Exception as e:
        print(f"  LLM 调用失败: {e}")

    # 走正式 planner_node
    print("\n[planner_node 解析结果]")
    result = planner_node(state)
    plan = {
        "sub_agent_plan": result.get("sub_agent_plan", []),
        "reason": result.get("planner_reason", ""),
        "push_immediate": result.get("push_immediate", False),
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))

    print("\n[预判信号判定]")
    for s in _judge(plan):
        print(f"  - {s}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene", default="all", help="场景编号 1-5，或 all")
    args = parser.parse_args()

    _print_header("FeedLens Planner 预判能力观察")
    print("说明: 本脚本调用真实 DeepSeek LLM。若看到 'LLM 调用失败，回退默认'，")
    print("      说明走的是 _fallback_plan（硬编码三段式），看不到主动预判。")
    print("      请确保 .env 的 DEEPSEEK_API_KEY 有效且网络可达。")

    if args.scene == "all":
        for k in sorted(SCENES.keys()):
            run_scene(k)
    else:
        run_scene(args.scene)

    _print_header("观察结束")


if __name__ == "__main__":
    main()
