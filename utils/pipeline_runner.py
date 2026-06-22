"""Pipeline 运行辅助模块 — 在 Streamlit UI 中触发完整 Agent 管线。"""

import sys
import os
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.execution_fence import try_acquire_pipeline


def run_agent_pipeline(trigger_type: str = "manual") -> dict:
    """运行完整 Agent 管线（采集 → 去重/排序 → 简报生成）。

    Args:
        trigger_type: 触发类型 (manual / daily_briefing / breaking_news)

    Returns:
        Agent 执行结果状态字典，包含 status 和主要输出

    Raises:
        Exception: 管线执行失败时抛出
    """
    # 执行栅栏：MVP 单用户，user_id=1；防止定时/手动/破例推送并发写偏好（P2）
    lock = try_acquire_pipeline(1)
    if lock is None:
        print("[pipeline] 已有管线在执行，跳过本次触发", flush=True)
        return {"status": "skipped", "reason": "pipeline already running"}

    try:
        # 确保项目根目录在 sys.path 中
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)

        from agents.main_agent import build_main_agent
        from models.database import Database

        # 读取当前用户 Goal
        db_path = "data/feedlens.db"
        db = Database(db_path)

        user_id = 1
        goal_text = ""
        with db.get_connection() as conn:
            row = conn.execute(
                "SELECT id, goal_text FROM users ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row:
                user_id = row["id"]
                goal_text = row["goal_text"] or ""

        # 构建初始状态
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        session_id = f"manual_{timestamp}_{uuid.uuid4().hex[:8]}"

        initial_state = {
            "user_id": user_id,
            "goal_text": goal_text,
            "trigger_type": trigger_type,
            "session_id": session_id,
        }

        # 运行管线
        agent = build_main_agent()
        result = agent.invoke(initial_state)

        # 返回关键状态摘要
        return {
            "status": result.get("status", "completed"),
            "session_id": session_id,
            "collected_count": len(result.get("collected_items", [])),
            "ranked_count": len(result.get("ranked_items", [])),
            "brief_quality": result.get("brief_quality", 0.0),
            "push_status": result.get("push_status", "pending"),
            "issues": result.get("coordinator_observation", {}).get("issues", []),
            "error": result.get("error", None),
        }
    finally:
        lock.release()


if __name__ == "__main__":
    """CLI 入口：独立进程运行管线。"""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--trigger", default="manual")
    parser.add_argument("--db", default="data/feedlens.db")
    args = parser.parse_args()
    result = run_agent_pipeline(trigger_type=args.trigger)
    print(f"[pipeline] 完成: collected={result.get('collected_count')}, ranked={result.get('ranked_count')}, quality={result.get('brief_quality')}")
