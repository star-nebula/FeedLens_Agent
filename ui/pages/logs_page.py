"""
执行日志页面。
"""

import streamlit as st
import json
from models.database import Database


def _get_db() -> Database:
    """获取数据库实例。"""
    return Database("data/feedlens.db")


def _load_execution_logs(limit: int = 100, session_id: str = None) -> list:
    """加载执行日志。"""
    db = _get_db()
    with db.get_connection() as conn:
        if session_id:
            cursor = conn.execute(
                """
                SELECT id, session_id, turn, event, node_name, status, duration_ms, metadata, created_at
                FROM execution_logs
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            )
        else:
            cursor = conn.execute(
                """
                SELECT id, session_id, turn, event, node_name, status, duration_ms, metadata, created_at
                FROM execution_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
        return [dict(row) for row in cursor.fetchall()]


def _load_run_logs(limit: int = 50) -> list:
    """加载运行日志。"""
    db = _get_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, trigger_type, items_collected, items_deduped, dedup_rate, brief_quality_score, duration_ms, created_at
            FROM run_logs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def _get_sessions() -> list:
    """获取所有 session_id。"""
    db = _get_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT DISTINCT session_id, MIN(created_at) as start_time
            FROM execution_logs
            GROUP BY session_id
            ORDER BY start_time DESC
            LIMIT 20
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def _get_log_stats() -> dict:
    """获取日志统计。"""
    db = _get_db()
    with db.get_connection() as conn:
        total_logs = conn.execute("SELECT COUNT(*) FROM execution_logs").fetchone()[0]
        total_runs = conn.execute("SELECT COUNT(*) FROM run_logs").fetchone()[0]
        error_count = conn.execute(
            "SELECT COUNT(*) FROM execution_logs WHERE status = 'failed'"
        ).fetchone()[0]

    return {
        "total_logs": total_logs,
        "total_runs": total_runs,
        "error_count": error_count,
    }


def render():
    """渲染执行日志页面。"""
    st.title("📊 执行日志")
    st.markdown("查看 Agent 运行日志和执行记录。")

    # 统计信息
    stats = _get_log_stats()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("执行日志", stats["total_logs"])
    with col2:
        st.metric("运行次数", stats["total_runs"])
    with col3:
        st.metric("错误数", stats["error_count"])

    st.markdown("---")

    # Tab 切换
    tab1, tab2 = st.tabs(["执行日志", "运行记录"])

    # 执行日志
    with tab1:
        st.subheader("执行日志")

        # 筛选
        sessions = _get_sessions()
        if sessions:
            session_options = ["全部"] + [s["session_id"] for s in sessions]
            selected_session = st.selectbox("选择 Session", session_options)

            logs = _load_execution_logs(
                100,
                None if selected_session == "全部" else selected_session,
            )

            if not logs:
                st.info("暂无执行日志。")
            else:
                for log in logs:
                    with st.expander(
                        f"[{log['status']}] {log['node_name']} - {log['event']}",
                        expanded=False,
                    ):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Session:** {log['session_id']}")
                            st.markdown(f"**Turn:** {log['turn']}")
                            st.markdown(f"**状态:** {log['status']}")
                        with col2:
                            st.markdown(f"**耗时:** {log['duration_ms'] or 0} ms")
                            st.markdown(f"**时间:** {log['created_at']}")

                        if log["metadata"]:
                            try:
                                metadata = json.loads(log["metadata"])
                                st.json(metadata)
                            except Exception:
                                st.code(log["metadata"])

        else:
            st.info("暂无执行日志。")

    # 运行记录
    with tab2:
        st.subheader("运行记录")

        run_logs = _load_run_logs(50)
        if not run_logs:
            st.info("暂无运行记录。")
        else:
            for run in run_logs:
                with st.container():
                    col1, col2, col3 = st.columns([2, 2, 1])

                    with col1:
                        trigger_map = {
                            "daily_briefing": "📅 日常简报",
                            "manual": "👆 手动触发",
                            "breaking_news": "⚡ 突发新闻",
                            "feedback_update": "🔄 反馈更新",
                        }
                        trigger_label = trigger_map.get(
                            run["trigger_type"], run["trigger_type"]
                        )
                        st.markdown(f"**{trigger_label}**")
                        st.caption(run["created_at"])

                    with col2:
                        st.markdown(
                            f"采集: {run['items_collected'] or 0} | "
                            f"去重: {run['items_deduped'] or 0} | "
                            f"去重率: {(run.get('dedup_rate') or 0) * 100:.0f}%"
                        )
                        if run.get("brief_quality_score") is not None:
                            st.markdown("✅ 已生成简报")

                    with col3:
                        if run.get("error_msg"):
                            st.error("❌ 错误")
                        else:
                            st.success("✅ 成功")

                    if run.get("error_msg"):
                        with st.expander("查看错误详情"):
                            st.error(run.get("error_msg"))

                    st.markdown("---")


