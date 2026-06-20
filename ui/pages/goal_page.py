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
    return DeepSeekProvider(
        api_key=config.get("llm", {}).get("deepseek", {}).get("api_key", ""),
        model=config.get("deepseek_model", "deepseek-chat"),
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
        content = response.get("content", "") if isinstance(response, dict) else str(response)
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
