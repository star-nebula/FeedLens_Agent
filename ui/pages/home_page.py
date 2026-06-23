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
from agents.feedback_agent import process_feedback_async


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
    """加载简报关联的条目（含 item_id 用于反馈）。"""
    db = _get_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT bi.item_id, bi.rank, bi.final_score, bi.is_highlight,
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


def _check_item_feedback(item_id: int) -> str:
    """检查某条目是否已有用户反馈。"""
    db = _get_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            "SELECT feedback_type FROM feedback WHERE item_id = ? AND user_id = 1 ORDER BY created_at DESC LIMIT 1",
            (item_id,),
        )
        row = cursor.fetchone()
        return row["feedback_type"] if row else None


def _add_feedback_with_agent(item_id: int, feedback_type: str, brief_id: int = None):
    """添加反馈并异步触发 feedback_agent 完整 pipeline。

    feedback_agent 内部会完成：
    1. record_feedback → 写入 SQLite feedback 表
    2. update_preference → EMA 更新偏好向量
    3. vector_add → 写入 ChromaDB COLLECTION_USER_PREF
    4. cleanup_preference → 清理低权重偏好
    """
    try:
        process_feedback_async(user_id=1, item_id=item_id, feedback_type=feedback_type, brief_id=brief_id)
        print(f"[home_page] 反馈已提交，feedback_agent 异步处理中: item={item_id}, type={feedback_type}", flush=True)
    except Exception as e:
        print(f"[home_page] feedback_agent 启动失败: {e}", flush=True)


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

            # 合并显示：Markdown 内容 + 反馈图标在同一个 expander 中
            items = _load_brief_items(brief_id)
            has_content = bool(brief.get("content_md"))
            has_items = bool(items)
            if has_content or has_items:
                item_count = len(items) if items else 0
                label = f"📄 查看简报内容 ({item_count} 条)"
                with st.expander(label, expanded=False):
                    # 1) Markdown 正文
                    if has_content:
                        st.markdown(brief["content_md"])
                    # 2) 逐条目反馈图标行（紧接 Markdown 下方）
                    if items:
                        # 用 JSON 解析 content_json 获取 categories 结构，匹配 item_id
                        item_map = {item["item_id"]: item for item in items}
                        brief_json = {}
                        try:
                            brief_json = json.loads(brief.get("content_json", "{}"))
                        except (json.JSONDecodeError, TypeError):
                            pass
                        categories = brief_json.get("categories", [])
                        for cat in categories:
                            cat_items = cat.get("items", [])
                            for idx, entry in enumerate(cat_items):
                                entry_id = entry.get("id", "")
                                # 尝试匹配 item_id（entry.id 可能是字符串/数字混合）
                                matched = None
                                for item in items:
                                    if str(item["item_id"]) == str(entry_id):
                                        matched = item
                                        break
                                if not matched:
                                    continue
                                item_id = matched["item_id"]
                                existing_fb = _check_item_feedback(item_id)
                                # 反馈图标行
                                fb_key = f"fb_{brief_id}_{item_id}"
                                if existing_fb:
                                    icon_map = {"like": "❤️", "dislike": "💔", "irrelevant": "🚫"}
                                    st.caption(f"{icon_map.get(existing_fb, '')} 已反馈：{existing_fb}")
                                else:
                                    c1, c2, c3, c4 = st.columns([1, 1, 1, 7])
                                    with c1:
                                        if st.button("👍", key=f"like_{fb_key}", help="喜欢"):
                                            _add_feedback_with_agent(item_id, "like", brief_id)
                                            st.toast("✅ 已标记：喜欢")
                                            st.rerun()
                                    with c2:
                                        if st.button("👎", key=f"dislike_{fb_key}", help="不喜欢"):
                                            _add_feedback_with_agent(item_id, "dislike", brief_id)
                                            st.toast("✅ 已标记：不喜欢")
                                            st.rerun()
                                    with c3:
                                        if st.button("🚫", key=f"irr_{fb_key}", help="不相关"):
                                            _add_feedback_with_agent(item_id, "irrelevant", brief_id)
                                            st.toast("✅ 已标记：不相关")
                                            st.rerun()
                                # 只在主条目（idx==0）显示反馈，子条目不重复显示
                                if idx == 0:
                                    st.markdown("")  # 间距

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
