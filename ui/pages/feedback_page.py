"""
反馈记录页面。
"""

import streamlit as st
from models.database import Database
from agents.feedback_agent import process_feedback_async


def _get_db() -> Database:
    """获取数据库实例。"""
    return Database("data/feedlens.db")


def _load_feedback_history(limit: int = 50) -> list:
    """加载反馈历史。"""
    db = _get_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT f.id, f.feedback_type, f.created_at,
                   ri.title, ri.summary, ri.url
            FROM feedback f
            LEFT JOIN deduped_items di ON f.item_id = di.id
            LEFT JOIN raw_items ri ON di.representative_item_id = ri.id
            ORDER BY f.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def _load_recent_items(limit: int = 20) -> list:
    """加载最近条目供反馈。"""
    db = _get_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT di.id, ri.title, ri.summary, ri.url
            FROM deduped_items di
            JOIN raw_items ri ON di.representative_item_id = ri.id
            ORDER BY di.created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def _add_feedback(item_id: int, feedback_type: str, brief_id: int = None):
    """添加反馈并触发 feedback_agent 完整 pipeline。

    feedback_agent 内部会完成：
    1. record_feedback → 写入 SQLite feedback 表
    2. update_preference → EMA 更新偏好向量
    3. vector_add → 写入 ChromaDB COLLECTION_USER_PREF
    4. cleanup_preference → 清理低权重偏好
    """
    try:
        process_feedback_async(user_id=1, item_id=item_id, feedback_type=feedback_type, brief_id=brief_id)
    except Exception as e:
        print(f"[feedback_page] feedback_agent 启动失败: {e}", flush=True)


def _get_feedback_stats() -> dict:
    """获取反馈统计。"""
    db = _get_db()
    with db.get_connection() as conn:
        like_count = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE feedback_type = 'like'"
        ).fetchone()[0]
        dislike_count = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE feedback_type = 'dislike'"
        ).fetchone()[0]
        irrelevant_count = conn.execute(
            "SELECT COUNT(*) FROM feedback WHERE feedback_type = 'irrelevant'"
        ).fetchone()[0]
        total = like_count + dislike_count + irrelevant_count

    return {
        "like": like_count,
        "dislike": dislike_count,
        "irrelevant": irrelevant_count,
        "total": total,
    }


def render():
    """渲染反馈记录页面。"""
    st.title("👍 反馈记录")
    st.markdown("对条目进行反馈，系统将学习您的偏好。")

    # 统计信息
    stats = _get_feedback_stats()
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("👍 喜欢", stats["like"])
    with col2:
        st.metric("👎 不喜欢", stats["dislike"])
    with col3:
        st.metric("🚫 不相关", stats["irrelevant"])
    with col4:
        st.metric("总计", stats["total"])

    st.markdown("---")

    # 添加反馈
    st.subheader("添加反馈")

    items = _load_recent_items(30)
    if not items:
        st.info("暂无条目可供反馈，请先运行采集。")
    else:
        # 选择条目
        item_options = {f"{i['title'][:50]}... (ID: {i['id']})": i for i in items}
        selected_item_label = st.selectbox("选择条目", list(item_options.keys()))
        selected_item = item_options[selected_item_label]

        # 显示条目详情
        with st.expander("📋 条目详情", expanded=True):
            st.markdown(f"**标题:** {selected_item['title']}")
            if selected_item["summary"]:
                st.markdown(f"**摘要:** {selected_item['summary'][:300]}...")
            if selected_item["url"]:
                st.markdown(f"**链接:** [查看原文]({selected_item['url']})")

        # 反馈按钮
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("👍 喜欢", use_container_width=True, type="primary"):
                _add_feedback(selected_item["id"], "like")
                st.success("已记录喜欢！")
                st.rerun()

        with col2:
            if st.button("👎 不喜欢", use_container_width=True):
                _add_feedback(selected_item["id"], "dislike")
                st.success("已记录不喜欢！")
                st.rerun()

        with col3:
            if st.button("🚫 不相关", use_container_width=True):
                _add_feedback(selected_item["id"], "irrelevant")
                st.success("已记录不相关！")
                st.rerun()

    st.markdown("---")

    # 反馈历史
    st.subheader("反馈历史")

    feedbacks = _load_feedback_history(50)
    if not feedbacks:
        st.info("暂无反馈记录。")
        return

    for fb in feedbacks:
        with st.container():
            col1, col2 = st.columns([1, 4])

            with col1:
                if fb["feedback_type"] == "like":
                    st.markdown("👍 **喜欢**")
                elif fb["feedback_type"] == "dislike":
                    st.markdown("👎 **不喜欢**")
                else:
                    st.markdown("🚫 **不相关**")
                st.caption(fb["created_at"])

            with col2:
                st.markdown(f"**{fb['title'] or '无标题'}**")
                if fb["url"]:
                    st.markdown(f"[查看原文]({fb['url']})")

            st.markdown("---")
