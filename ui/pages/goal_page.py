"""
Goal 设置页面。
"""

import streamlit as st
import json
from models.database import Database
import subprocess
import sys
from utils.pipeline_runner import run_agent_pipeline
from utils.llm_provider import DeepSeekProvider
import os
from utils.config import load_config


def _get_db() -> Database:
    """获取数据库实例。"""
    return Database("data/feedlens.db")


def _get_llm() -> DeepSeekProvider:
    """获取 LLM 实例。"""
    config = load_config()
    deepseek_cfg = config.get("llm", {}).get("deepseek", {})
    return DeepSeekProvider(
        api_key=deepseek_cfg.get("api_key", ""),
        base_url=deepseek_cfg.get("base_url", "https://api.deepseek.com/v1"),
        model=deepseek_cfg.get("model", "deepseek-chat"),
    )


def _extract_goal_fields(goal_text: str) -> dict:
    """使用 LLM 提取 Goal 结构化字段。"""
    llm = _get_llm()
    prompt = f"""请从以下用户 Goal 文本中提取结构化字段，返回 JSON 格式：

Goal 文本:
{goal_text}

请提取以下字段：
- topics: 主题列表（数组）
- keywords: 关键词列表（数组）
- preferred_sources: 偏好来源列表（数组，可选）

返回格式示例：
{{"topics": ["科技", "AI"], "keywords": ["GPT", "大模型"], "preferred_sources": ["36kr", "techcrunch"]}}

只返回 JSON，不要其他内容。"""

    try:
        response = llm.chat([{"role": "user", "content": prompt}])
        if isinstance(response, dict):
            content = response.get("content", "")
        else:
            content = str(response)
        # 提取 JSON
        import re
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
    except Exception as e:
        st.error(f"提取失败: {e}")
    return {}


def _load_current_goal() -> dict:
    """加载当前 Goal。"""
    db = _get_db()
    with db.get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT id, goal_text, topics, keywords, preferred_sources, created_at, updated_at
            FROM users
            ORDER BY updated_at DESC
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def _save_goal(goal_text: str, topics: list, keywords: list, preferred_sources: list):
    """保存 Goal。"""
    db = _get_db()
    with db.get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (goal_text, topics, keywords, preferred_sources)
            VALUES (?, ?, ?, ?)
            """,
            (goal_text, json.dumps(topics), json.dumps(keywords), json.dumps(preferred_sources)),
        )


def render():
    """渲染 Goal 设置页面。"""
    st.title("🎯 Goal 设置")
    st.markdown("设置您的信息需求目标，系统将根据 Goal 为您采集和筛选内容。")

    # 加载当前 Goal
    current_goal = _load_current_goal()

    # 显示当前 Goal
    if current_goal:
        with st.expander("📋 当前 Goal", expanded=True):
            st.markdown(f"**目标文本:** {current_goal['goal_text']}")

            col1, col2 = st.columns(2)
            with col1:
                if current_goal["topics"]:
                    topics = json.loads(current_goal["topics"])
                    st.markdown("**主题:**")
                    st.markdown(", ".join(topics))
                if current_goal["keywords"]:
                    keywords = json.loads(current_goal["keywords"])
                    st.markdown("**关键词:**")
                    st.write(", ".join(keywords))
            with col2:
                if current_goal["preferred_sources"]:
                    sources = json.loads(current_goal["preferred_sources"])
                    st.markdown("**偏好来源:**")
                    st.write(", ".join(sources))

            st.caption(f"更新时间: {current_goal['updated_at']}")

    st.markdown("---")

    # 设置 / 更新 Goal
    st.markdown("### ✍️ 设置新 Goal")
    st.markdown("输入您长期关注的目标，系统将用 LLM 自动提取主题、关键词并推荐 RSS 来源。")
    goal_input = st.text_area("Goal 文本", value="", height=120, key="goal_input", help="例如：AI Agent 技术进展 / 新能源车行业动态")

    col_extract, col_save = st.columns(2)
    extracted = None
    with col_extract:
        if st.button("🧠 LLM 提取结构化字段", key="extract_goal", use_container_width=True):
            if not goal_input.strip():
                st.warning("请先输入 Goal 文本")
            else:
                with st.spinner("LLM 提取中..."):
                    extracted = _extract_goal_fields(goal_input)
                if not extracted:
                    st.error("提取失败，请检查 LLM 配置或重试")
                else:
                    st.session_state["extracted_goal"] = extracted

    # 展示提取结果（跨按钮交互保留）
    if "extracted_goal" in st.session_state:
        extracted = st.session_state["extracted_goal"]
        with st.expander("🔍 提取的结构化字段", expanded=True):
            topics = extracted.get("topics", [])
            keywords = extracted.get("keywords", [])
            preferred_sources = extracted.get("preferred_sources", [])
            st.markdown(f"**主题:** {', '.join(topics) if topics else '（无）'}")
            st.markdown(f"**关键词:** {', '.join(keywords) if keywords else '（无）'}")
            if preferred_sources:
                st.markdown(f"**推荐 RSS 来源:** {', '.join(preferred_sources)}")
                st.caption("可在「RSS 源管理」页面添加这些来源")
            else:
                st.caption("未推荐具体来源")

    with col_save:
        if st.button("💾 保存 Goal", key="save_goal", use_container_width=True, type="primary"):
            if not goal_input.strip():
                st.warning("请先输入 Goal 文本")
            else:
                fields = extracted if extracted else _extract_goal_fields(goal_input)
                if not fields:
                    fields = {"topics": [], "keywords": [], "preferred_sources": []}
                try:
                    _save_goal(
                        goal_text=goal_input.strip(),
                        topics=fields.get("topics", []),
                        keywords=fields.get("keywords", []),
                        preferred_sources=fields.get("preferred_sources", []),
                    )
                    st.success("✅ Goal 已保存")
                    st.session_state.pop("extracted_goal", None)
                    st.rerun()
                except Exception as e:
                    st.error(f"保存失败: {e}")


    # 立即可运行
    st.markdown("### 🚀 运行管线")
    st.markdown("保存 Goal 后，点击下方按钮立即执行一次完整采集 → 简报生成。")

    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("🚀 立即运行", type="primary", key="run_goal", use_container_width=True):
            try:
                subprocess.Popen(
                    [sys.executable, "-m", "utils.pipeline_runner", "--trigger", "manual"],
                    stdout=open("data/pipeline.log", "a"), stderr=subprocess.STDOUT,
                    creationflags=subprocess.DETACHED_PROCESS,
                )
                st.success("🚀 管线已后台启动，完成后前往首页查看简报")
            except Exception as e:
                st.error(f"管线启动失败: {e}")