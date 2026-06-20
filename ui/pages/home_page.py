"""
首页/简报查看页面。
"""

import streamlit as st
import subprocess
import sys
import os
import json
import threading
from datetime import datetime, timezone, timedelta
from models.database import Database
from utils.pipeline_runner import run_agent_pipeline


def _run_pipeline_with_tee(trigger: str = "manual"):
    """启动 pipeline 子进程，输出同时写入日志文件和终端。"""
    log_path = "data/pipeline.log"
    log_file = open(log_path, "a", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "-m", "utils.pipeline_runner", "--trigger", trigger],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=subprocess.DETACHED_PROCESS,
    )

    def _reader():
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="replace")
            log_file.write(text)
            log_file.flush()
            sys.stderr.buffer.write(line)
            sys.stderr.buffer.flush()
        proc.stdout.close()
        log_file.close()

    threading.Thread(target=_reader, daemon=True).start()
    return proc


def _get_db() -> Database:
    """获取数据库实例。"""
    return Database("data/feedlens.db")


def _load_briefs(limit: int = 10) -> list:
    """加载简报列表。"""
    db = _get_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, content_json, content_md, quality_score, created_at
            FROM briefs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(row) for row in cursor.fetchall()]


def _load_brief_items(brief_id: int) -> list:
    """加载简报关联的条目。"""
    db = _get_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT bi.rank, bi.final_score, bi.is_highlight,
                   ri.title, ri.summary, ri.url, ri.source_id
            FROM briefing_items bi
            JOIN deduped_items di ON bi.item_id = di.id
            JOIN raw_items ri ON di.representative_item_id = ri.id
            WHERE bi.briefing_id = ?
            ORDER BY bi.rank
            """,
            (brief_id,),
        )
        return [dict(row) for row in cursor.fetchall()]


def _delete_brief(brief_id: int):
    """删除简报及相关关联条目。"""
    db = _get_db()
    with db.get_connection() as conn:
        conn.execute("DELETE FROM briefing_items WHERE briefing_id = ?", (brief_id,))
        conn.execute("DELETE FROM briefs WHERE id = ?", (brief_id,))


def render():
    """渲染首页。"""
    st.title("📰 首页")
    st.markdown("查看最新简报和历史简报")

    # 操作按钮
    col1, col2, col3 = st.columns([3, 1, 1])
    with col2:
        if st.button("🔄 刷新", use_container_width=True):
            st.rerun()
    with col3:
        if st.button("🚀 立即运行", type="primary", key="run_header", use_container_width=True):
            try:
                _run_pipeline_with_tee("manual")
                st.success("🚀 管线已后台启动，完成后刷新页面查看简报")
                st.toast("⏳ 管线运行中（约 1-3 分钟）")
            except Exception as e:
                st.error(f"管线启动失败: {e}")

    st.markdown("---")

    # 如果数据库没有源，自动导入默认源
    briefs = _load_briefs(20)

    if not briefs:
        st.info("暂无简报，请设置 Goal 后点击下方按钮运行采集。")

        col_a, col_b = st.columns([1, 3])
        with col_a:
            if st.button("🚀 立即运行", type="primary", key="run_empty", use_container_width=True):
                _run_pipeline_with_tee("manual")
                st.success("🚀 管线已后台启动，完成后刷新页面查看简报")
        with col_b:
            st.markdown("👉 前往 **Goal 设置** 页面配置您的信息需求。")
        return

    # 显示简报列表
    for brief in briefs:
        brief_id = brief["id"]
        created_at = brief["created_at"]
        quality_score = brief["quality_score"] or 0

        # 简报卡片
        with st.container():
            col1, col2, col3 = st.columns([3, 1, 1])
            with col1:
                st.subheader(f"简报 #{brief_id}")
            with col2:
                st.metric("质量分", f"{quality_score:.2f}")
            with col3:
                if st.button("🗑️", key=f"del_{brief_id}", use_container_width=True):
                    _delete_brief(brief_id)
                    st.rerun()

            # 时区转换
            try:
                dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                local_dt = dt.astimezone(timezone(timedelta(hours=8)))
                created_at_display = local_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                created_at_display = created_at
            st.caption(f"生成时间: {created_at_display}")

            # 显示 Markdown 内容
            if brief["content_md"]:
                with st.expander("📄 查看简报内容", expanded=False):
                    st.markdown(brief["content_md"])

            # 显示关联条目
            items = _load_brief_items(brief_id)
            if items:
                with st.expander(f"📋 关联条目 ({len(items)} 条)", expanded=False):
                    for item in items:
                        title = item["title"] or "无标题"
                        score = item["final_score"] or 0
                        highlight = "⭐ " if item["is_highlight"] else ""

                        st.markdown(
                            f"""
                            **{highlight}{item['rank']}. {title}**
                            - 评分: {score:.3f}
                            - [查看原文]({item['url'] or '#'})
                            """
                        )
                        if item["summary"]:
                            st.caption(item["summary"][:200] + "...")

            st.markdown("---")


def render_sidebar():
    """渲染侧边栏统计信息。"""
    db = _get_db()
    with db.get_connection() as conn:
        brief_count = conn.execute("SELECT COUNT(*) FROM briefs").fetchone()[0]
        item_count = conn.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
        feedback_count = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]

    st.sidebar.metric("简报总数", brief_count)
    st.sidebar.metric("采集条目", item_count)
    st.sidebar.metric("用户反馈", feedback_count)
