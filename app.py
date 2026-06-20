"""
FeedLens Streamlit 前端主入口。

运行方式:
    streamlit run app.py
"""

import streamlit as st
from ui.pages import (
    home_page,
    goal_page,
    sources_page,
    feedback_page,
    logs_page,
)

# 页面配置
st.set_page_config(
    page_title="FeedLens - 智能信息简报",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 侧边栏导航
st.sidebar.title("📰 FeedLens")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "导航",
    ["首页", "Goal 设置", "RSS 源管理", "反馈记录", "执行日志"],
    label_visibility="collapsed",
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    """
    <div style="font-size: 12px; color: #888;">
    FeedLens MVP v1.0<br>
    智能信息简报系统
    </div>
    """,
    unsafe_allow_html=True,
)

# 路由到各页面
if page == "首页":
    home_page.render()
elif page == "Goal 设置":
    goal_page.render()
elif page == "RSS 源管理":
    sources_page.render()
elif page == "反馈记录":
    feedback_page.render()
elif page == "执行日志":
    logs_page.render()
