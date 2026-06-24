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
            # 解析 content_json 获取条目数（提前计算用于标题行）
            items = _load_brief_items(brief_id)
            brief_json = {}
            try:
                brief_json = json.loads(brief.get("content_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                pass
            # 兼容新旧格式：新格式 items 直接是数组，旧格式 categories 嵌套
            brief_items = brief_json.get("items", [])
            if not brief_items:
                categories = brief_json.get("categories", [])
                brief_items = []
                for cat in categories:
                    brief_items.extend(cat.get("items", []))
            item_count = len(brief_items)
            if item_count == 0:
                item_count = len(items) if items else 0

            # 格式化生成时间
            try:
                dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                local_dt = dt.astimezone(timezone(timedelta(hours=8)))
                created_at_display = local_dt.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                created_at_display = str(created_at)

            if item_count > 0:
                # expander 与删除按钮并排：expander 占绝大部分，删除按钮右对齐
                exp_col, del_col = st.columns([20, 1])
                with exp_col:
                    # 简报标题优先显示，无标题时回退为"简报数量"
                    brief_title = brief_json.get("title", "") or f"简报（{item_count}条）"
                    with st.expander(f"📄 {created_at_display}  |  {brief_title}  |  质量分：{quality_score:.2f}", expanded=False):
                        # 构建 item_id → db_item 映射
                        item_map = {}
                        for item in items:
                            item_map[item["item_id"]] = item

                        # 简报标题
                        title = brief_json.get("title", "")
                        if title:
                            st.markdown(f"# {title}")

                        # 简报摘要
                        summary = brief_json.get("summary", "")
                        if summary:
                            st.markdown(f"> {summary}")
                        st.markdown("")

                        # 逐条目平铺渲染：所有条目一视同仁
                        for entry in brief_items:
                            entry_id = entry.get("id", "")
                            # 匹配 briefing_items
                            matched = None
                            for item in items:
                                if str(item["item_id"]) == str(entry_id):
                                    matched = item
                                    break

                            # 条目标题（粗体）
                            entry_title = entry.get("title", "")
                            st.markdown(f"**{entry_title}**")
                            st.markdown("")

                            # 摘要
                            item_summary = entry.get("summary", "")
                            if item_summary:
                                st.caption(f"摘要: {item_summary}")

                            # 链接
                            url = entry.get("url", "")
                            if url:
                                st.caption(f"链接: {url}")

                            # 元信息行
                            meta_parts = []
                            meta_parts.append(f"来源: {entry.get('source', 'unknown')}")
                            pub_time = entry.get("published_at", "")
                            if pub_time:
                                meta_parts.append(f"时间: {pub_time}")
                            imp = entry.get("importance", 0)
                            if imp:
                                meta_parts.append(f"重要性: {imp}/5")
                            score = entry.get("final_score")
                            if score is not None:
                                try:
                                    meta_parts.append(f"评分: {float(score):.3f}")
                                except (TypeError, ValueError):
                                    pass
                            st.caption(f"{' | '.join(meta_parts)}")

                            # 反馈按钮（所有条目都显示）
                            if matched:
                                item_id = matched["item_id"]
                                existing_fb = _check_item_feedback(item_id)
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

                            st.markdown("")  # 条目间距
                # expander 块结束 (exp_col)
                with del_col:
                    if st.button("🗑️", key=f"del_{brief_id}", help="删除简报"):
                        _delete_brief(brief_id)
                        st.rerun()



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
