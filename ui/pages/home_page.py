"""
首页/简报查看页面。
"""

import streamlit as st
import streamlit.components.v1 as components
import subprocess
import sys
import os
import json
import re
import threading
import http.server
import socketserver
from datetime import datetime, timezone, timedelta
from models.database import Database
from utils.pipeline_runner import run_agent_pipeline
from agents.feedback_agent import process_feedback_async


def _run_pipeline_with_tee(trigger: str = "manual"):
    """启动 pipeline 子进程，输出同时到文件 + 控制台。

    通过 PIPE 捕获 stdout，后台线程 tee 到：
    1. data/pipeline.log（持久化）
    2. data/pipeline_ui.log（前端专用，每次运行覆盖）
    3. sys.stderr（后端控制台可见）
    """
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    ui_log_path = f"data/pipeline_ui_{run_id}.log"

    # 持久化日志（追加）
    persist_log = open("data/pipeline.log", "a", encoding="utf-8")
    # 前端专用日志（覆盖写入，避免历史污染）
    ui_log = open(ui_log_path, "w", encoding="utf-8")

    # 初始化 session_state
    st.session_state["pipeline_ui_log_path"] = ui_log_path
    st.session_state["pipeline_running"] = True
    st.session_state["pipeline_proc"] = None

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    proc = subprocess.Popen(
        [sys.executable, "-m", "utils.pipeline_runner", "--trigger", trigger],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        creationflags=subprocess.DETACHED_PROCESS if sys.platform == "win32" else 0,
    )
    st.session_state["pipeline_proc"] = proc

    def _reader():
        for line in iter(proc.stdout.readline, b""):
            text = line.decode("utf-8", errors="replace")
            # 1. 后端控制台可见
            sys.stderr.write(text)
            sys.stderr.flush()
            # 2. 持久化日志
            persist_log.write(text)
            persist_log.flush()
            # 3. 前端 UI 日志文件
            ui_log.write(text)
            ui_log.flush()
        proc.stdout.close()
        ui_log.close()
        persist_log.close()

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


def _ui_clean_summary(text: str, max_chars: int = 200) -> str:
    """UI 层摘要清洗：去除噪音 + 智能截断（最后一道防线）。

    处理：
      - 去除作者署名（文｜XXX、编辑｜XXX 等）
      - 去除"查看全文"/"阅读全文"尾缀
      - 去除 HTML 标签和残留碎片（如 <img）
      - 去除图片来源说明
      - 智能截断：优先在句号处断开
    """
    if not text:
        return text

    # 1. 去除 HTML 标签
    cleaned = re.sub(r'<[^>]+>', '', text)
    # 2. 去除不完整的 HTML 残留
    cleaned = re.sub(r'<\w+[^>]*$', '', cleaned)
    cleaned = re.sub(r'<\w+\b(?!\s*=)[^>]{0,50}(?![^<]*>)', '', cleaned)
    # 3. 还原 HTML 实体
    import html as _html
    cleaned = _html.unescape(cleaned)
    # 4. 去除作者署名模式
    cleaned = re.sub(r'[文编]\s*[｜|/]\s*\S{1,20}', '', cleaned)
    cleaned = re.sub(r'编辑\s*[｜|/]\s*\S{1,20}', '', cleaned)
    cleaned = re.sub(r'作者\s*[：:]\s*\S{1,20}', '', cleaned)
    # 5. 去除"查看全文"等尾缀
    cleaned = re.sub(r'[（(]?查看全文[）)]?', '', cleaned)
    cleaned = re.sub(r'[（(]?阅读全文[）)]?', '', cleaned)
    cleaned = re.sub(r'[（(]?展开全文[）)]?', '', cleaned)
    # 6. 去除图片来源标记
    cleaned = re.sub(r'图片[来源：:]\s*\S{1,50}', '', cleaned)
    cleaned = re.sub(r'[（(]图[^）)]*[）)]', '', cleaned)
    # 7. 清理多余空白
    cleaned = re.sub(r'\s+', ' ', cleaned).strip('，,。；;； ')

    # 8. 智能截断
    if len(cleaned) > max_chars:
        truncated = cleaned[:max_chars]
        last_period = max(
            truncated.rfind('。'), truncated.rfind('？'), truncated.rfind('！'),
            truncated.rfind('.'), truncated.rfind('?'), truncated.rfind('!'),
        )
        if last_period > max_chars * 0.6:
            cleaned = truncated[:last_period + 1]
        else:
            last_break = max(
                truncated.rfind('，'), truncated.rfind(','),
                truncated.rfind('；'), truncated.rfind(';'),
                truncated.rfind(' '),
            )
            if last_break > max_chars * 0.6:
                cleaned = truncated[:last_break] + '...'
            else:
                cleaned = truncated + '...'

    return cleaned


# ---- 轻量 HTTP 日志服务器 ----
# 前端 JS 通过 fetch 轮询日志文件，避免 st.rerun() 导致的整页闪烁。
# 使用 st.cache_resource 确保 HTTP 服务器在整个 Streamlit 生命周期中只启动一次。
import http.server
import socketserver

_LOG_SERVER_PORT = 18990


def _get_log_server():
    """用 st.cache_resource 确保 HTTP 服务器全局只启动一次。"""
    _start_http_server()
    return _LOG_SERVER_PORT


@st.cache_resource(show_spinner=False)
def _start_http_server():
    """启动轻量 HTTP 服务，暴露 data/ 目录下日志文件（cache_resource 保证只执行一次）。"""

    class _LogHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=os.path.abspath("data"), **kwargs)

        def log_message(self, format, *args):
            pass  # 静默

        def end_headers(self):
            # 允许跨域（Streamlit iframe 发起的请求）
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

    # 尝试启动，如果端口被占用则复用已有服务
    try:
        server = socketserver.ThreadingTCPServer(("127.0.0.1", _LOG_SERVER_PORT), _LogHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        print(f"[home_page] HTTP 日志服务器已启动: http://127.0.0.1:{_LOG_SERVER_PORT}/", flush=True)
    except OSError:
        print(f"[home_page] HTTP 日志服务器端口 {_LOG_SERVER_PORT} 已被占用，复用已有服务", flush=True)


def _render_terminal():
    """渲染实时日志终端显示框。

    黑底绿字终端风格，JS 定时 fetch 日志文件实现局部刷新，
    不触发 st.rerun()，无整页闪烁。
    """
    running = st.session_state.get("pipeline_running", False)
    log_path = st.session_state.get("pipeline_ui_log_path", "")

    if not running and not log_path:
        return

    # 确保日志服务器已启动（cache_resource 保证幂等）
    _get_log_server()

    # 检查进程是否已结束
    proc = st.session_state.get("pipeline_proc")
    if proc is not None and proc.poll() is not None:
        st.session_state["pipeline_running"] = False
        running = False

    # 日志文件名（供 JS fetch）
    log_filename = os.path.basename(log_path) if log_path else ""

    # 状态栏
    if running:
        status_text = "⏳ 管线运行中..."
        status_color = "#ffa500"
    else:
        exit_code = proc.returncode if proc else None
        if exit_code == 0:
            status_text = "✅ 管线执行完成"
            status_color = "#4caf50"
        elif exit_code is not None:
            status_text = f"❌ 管线执行失败 (exit={exit_code})"
            status_color = "#f44336"
        else:
            status_text = "⏹️ 管线已结束"
            status_color = "#888"

    st.markdown(
        f'<span style="color:{status_color};font-weight:bold;font-size:14px;">{status_text}</span>',
        unsafe_allow_html=True,
    )

    # 终端组件：JS 自刷新，不依赖 st.rerun()
    terminal_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
#term-box {{
    background-color: #0c0c1d;
    color: #00ff88;
    font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.5;
    padding: 12px 16px;
    border-radius: 6px;
    border: 1px solid #333;
    height: 350px;
    overflow-y: auto;
    white-space: pre-wrap;
    word-break: break-all;
}}
</style></head><body>
<div id="term-box">（等待输出...）</div>
<script>
(function() {{
    var box = document.getElementById("term-box");
    var running = {str(running).lower()};
    var timer = null;
    var emptyCount = 0;

    function fetchLog() {{
        fetch("http://127.0.0.1:{_LOG_SERVER_PORT}/{log_filename}?_t=" + Date.now())
            .then(function(r) {{
                if (!r.ok) throw new Error("HTTP " + r.status);
                return r.text();
            }})
            .then(function(text) {{
                if (text && text.trim()) {{
                    box.textContent = text;
                    box.scrollTop = box.scrollHeight;
                    emptyCount = 0;
                }} else if (!running) {{
                    // 进程已结束，不再等待
                    emptyCount++;
                    if (emptyCount > 3) {{
                        if (timer) clearInterval(timer);
                    }}
                }}
            }})
            .catch(function(err) {{
                console.log("fetchLog error:", err.message);
            }});
    }}

    // 立即拉取一次
    fetchLog();

    // 运行中每 2 秒拉取；停止后最多再拉 3 次（6 秒后停止）
    if (running) {{
        timer = setInterval(fetchLog, 2000);
    }} else {{
        timer = setInterval(fetchLog, 2000);
    }}
}})();
</script></body></html>"""

    components.html(terminal_html, height=400, scrolling=False)

    # 完成后提示
    if not running:
        st.caption("💡 管线已完成，点击 🔄 刷新 查看最新简报")


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
                st.rerun()
            except Exception as e:
                st.error(f"管线启动失败: {e}")

    # ---- 终端显示框 ----
    _render_terminal()

    st.markdown("---")

    # 如果数据库没有源，自动导入默认源
    briefs = _load_briefs(20)

    if not briefs:
        st.info("暂无简报，请设置 Goal 后点击下方按钮运行采集。")

        col_a, col_b = st.columns([1, 3])
        with col_a:
            if st.button("🚀 立即运行", type="primary", key="run_empty", use_container_width=True):
                _run_pipeline_with_tee("manual")
                st.rerun()
        with col_b:
            st.markdown("👉 前往 **Goal 设置** 页面配置您的信息需求。")

        # 无简报时也显示终端框
        _render_terminal()
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
                            summary = _ui_clean_summary(summary, max_chars=150)
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
                                item_summary = _ui_clean_summary(item_summary, max_chars=200)
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
