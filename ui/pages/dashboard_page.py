"""
P1: 执行仪表盘页面 — 成功率、耗时、去重率、反馈率。
"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import os
from models.database import Database


def _get_db() -> Database:
    return Database("data/feedlens.db")


def _query(db: Database, sql: str):
    with db.get_connection() as conn:
        return [dict(row) for row in conn.execute(sql).fetchall()]


def _render_dashboard():
    st.header("执行仪表盘")

    db = _get_db()
    now = datetime.now()
    week_ago = (now - timedelta(days=7)).isoformat()

    try:
        # 成功率
        total_runs = _query(db, "SELECT COUNT(*) as c FROM run_logs")
        success_runs = _query(db, "SELECT COUNT(*) as c FROM execution_logs WHERE status='completed'")
        total = total_runs[0]["c"] if total_runs else 0
        success = success_runs[0]["c"] if success_runs else 0

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("总运行次数", total)
        with col2:
            rate = f"{success / max(total, 1) * 100:.0f}%" if total > 0 else "N/A"
            st.metric("成功率", rate)
        with col3:
            avg_duration = _query(db, "SELECT AVG(duration_ms) as avg_ms FROM execution_logs WHERE status='completed'")
            ms = avg_duration[0]["avg_ms"] if avg_duration and avg_duration[0]["avg_ms"] else 0
            st.metric("平均耗时", f"{ms/1000:.1f}s" if ms else "N/A")
        with col4:
            feedback_count = _query(db, "SELECT COUNT(*) as c FROM feedback")
            fc = feedback_count[0]["c"] if feedback_count else 0
            st.metric("总反馈数", fc)

        st.divider()

        # 去重率趋势
        st.subheader("去重率 (近 30 天)")
        dedup_data = _query(db, f"SELECT created_at, dedup_rate FROM run_logs WHERE created_at > '{week_ago}' ORDER BY created_at")
        if dedup_data:
            df = pd.DataFrame(dedup_data)
            df["dedup_rate_pct"] = df["dedup_rate"] * 100
            st.line_chart(df.set_index("created_at")["dedup_rate_pct"])
        else:
            st.info("暂无去重数据")

        st.divider()

        # 简报质量
        st.subheader("简报质量评分")
        quality_data = _query(db, f"SELECT created_at, brief_quality_score FROM run_logs WHERE created_at > '{week_ago}' ORDER BY created_at")
        if quality_data:
            df = pd.DataFrame(quality_data)
            st.line_chart(df.set_index("created_at")["brief_quality_score"])
        else:
            st.info("暂无质量数据")

        st.divider()

        # 采集量
        st.subheader("采集与去重")
        collected_data = _query(db, f"SELECT created_at, items_collected, items_deduped FROM run_logs WHERE created_at > '{week_ago}' ORDER BY created_at")
        if collected_data:
            df = pd.DataFrame(collected_data)
            st.bar_chart(df.set_index("created_at")[["items_collected", "items_deduped"]])
        else:
            st.info("暂无采集数据")

    except Exception as e:
        st.warning(f"仪表盘数据加载失败: {e}")


def render():
    """入口函数，供 app.py 路由调用。"""
    _render_dashboard()
