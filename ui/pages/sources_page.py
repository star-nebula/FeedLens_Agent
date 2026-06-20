"""
RSS 源管理页面。
"""

import streamlit as st
from models.database import Database


def _get_db() -> Database:
    """获取数据库实例。"""
    return Database("data/feedlens.db")


def _load_sources() -> list:
    """加载 RSS 源列表。"""
    db = _get_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, url, name, category, authority_score, is_active, created_at
            FROM sources
            ORDER BY created_at DESC
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def _add_source(url: str, name: str, category: str, authority_score: float):
    """添加 RSS 源。"""
    db = _get_db()
    with db.get_connection() as conn:
        # 检查是否已存在相同 URL
        existing = conn.execute(
            "SELECT id, name, is_active FROM sources WHERE url = ?", (url,)
        ).fetchone()
        if existing:
            return {
                "added": False,
                "duplicate": True,
                "existing_id": existing["id"],
                "existing_name": existing["name"],
                "existing_active": bool(existing["is_active"]),
            }
        conn.execute(
            """
            INSERT INTO sources (url, name, category, authority_score)
            VALUES (?, ?, ?, ?)
            """,
            (url, name, category, authority_score),
        )
    return {"added": True, "duplicate": False}


def _update_source(source_id: int, is_active: bool):
    """更新 RSS 源状态。"""
    db = _get_db()
    with db.get_connection() as conn:
        conn.execute(
            """
            UPDATE sources SET is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (1 if is_active else 0, source_id),
        )


def _delete_source(source_id: int):
    """删除 RSS 源。"""
    db = _get_db()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))



def _seed_default_sources():
    """将默认 RSS 源写入数据库（仅当源表为空时自动调用）。"""
    try:
        from agents.collection_agent import DEFAULT_RSS_SOURCES
    except Exception:
        DEFAULT_RSS_SOURCES = [
            "https://rsshub.app/solidot/",
            "https://rsshub.app/36kr/information/web_news/",
            "https://rsshub.app/36kr/news/latest",
            "https://rsshub.app/zhihu/daily",
            "https://rsshub.app/v2ex/topics/latest",
            "https://feeds.bbci.co.uk/news/technology/rss.xml",
            "https://rsshub.app/github/trending/daily",
        ]

    source_meta = {
        "https://rsshub.app/solidot/": ("Solidot", "科技"),
        "https://rsshub.app/36kr/information/web_news/": ("36氪资讯", "科技"),
        "https://rsshub.app/36kr/news/latest": ("36氪最新", "科技"),
        "https://rsshub.app/zhihu/daily": ("知乎日报", "科技"),
        "https://rsshub.app/v2ex/topics/latest": ("V2EX", "科技"),
        "https://feeds.bbci.co.uk/news/technology/rss.xml": ("BBC Technology", "科技"),
        "https://rsshub.app/github/trending/daily": ("GitHub Trending", "开源"),
    }

    db = _get_db()
    with db.get_connection() as conn:
        for url in DEFAULT_RSS_SOURCES:
            name, category = source_meta.get(url, (url, "其他"))
            conn.execute(
                "INSERT INTO sources (url, name, category, authority_score, is_active) VALUES (?, ?, ?, ?, 1)",
                (url, name, category, 0.5),
            )

def render():
    """渲染 RSS 源管理页面。"""
    st.title("📡 RSS 源管理")
    st.markdown("添加、删除、启用/禁用 RSS 源。")

    # 添加新源
    with st.expander("➕ 添加新 RSS 源", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            new_url = st.text_input("RSS URL", placeholder="https://example.com/feed.xml")
            new_name = st.text_input("名称", placeholder="示例新闻")
        with col2:
            new_category = st.selectbox(
                "分类",
                ["科技", "财经", "政治", "娱乐", "体育", "其他"],
            )
            new_score = st.slider("权威度评分", 0.0, 1.0, 0.5, 0.1)

        if st.button("添加", use_container_width=True):
            if not new_url.strip():
                st.warning("请输入 RSS URL")
            else:
                result = _add_source(new_url, new_name, new_category, new_score)
                if result.get("duplicate"):
                    st.warning(
                        f"该 RSS 已存在：**{result['existing_name']}** "
                        f"（{'已启用' if result['existing_active'] else '已禁用'}）"
                    )
                else:
                    st.success("RSS 源已添加！")
                    st.rerun()

    st.markdown("---")

    # 如果数据库没有源，自动导入默认源
    sources = _load_sources()
    if not sources:
        _seed_default_sources()
        st.rerun()

    # 显示源列表
    sources = _load_sources()

    if not sources:
        st.info("暂无 RSS 源，请添加。")
        return

    # 统计信息
    active_count = sum(1 for s in sources if s["is_active"])
    st.metric("活跃源", f"{active_count} / {len(sources)}")

    st.markdown("---")

    # 源列表
    for source in sources:
        with st.container():
            col1, col2, col3, col4 = st.columns([3, 2, 1, 1])

            with col1:
                status_icon = "✅" if source["is_active"] else "❌"
                st.markdown(f"**{status_icon} {source['name'] or '未命名'}**")
                st.caption(source["url"])

            with col2:
                st.markdown(f"**分类:** {source['category'] or '未分类'}")
                st.markdown(f"**权威度:** {source['authority_score']:.2f}")

            with col3:
                # 启用/禁用开关
                new_status = st.checkbox(
                    "启用",
                    value=bool(source["is_active"]),
                    key=f"toggle_{source['id']}",
                )
                if new_status != bool(source["is_active"]):
                    _update_source(source["id"], new_status)
                    st.rerun()

            with col4:
                # 删除按钮
                if st.button("🗑️", key=f"delete_{source['id']}"):
                    _delete_source(source["id"])
                    st.success("已删除")
                    st.rerun()

            st.markdown("---")

    # 批量操作
    st.subheader("批量操作")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("✅ 全部启用", use_container_width=True):
            for source in sources:
                _update_source(source["id"], True)
            st.success("已全部启用")
            st.rerun()

    with col2:
        if st.button("❌ 全部禁用", use_container_width=True):
            for source in sources:
                _update_source(source["id"], False)
            st.success("已全部禁用")
            st.rerun()

