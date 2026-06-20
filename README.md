# FeedLens — 主动式信息聚合 Agent 系统

FeedLens 是一个基于 LangGraph 的多 Agent 智能体系统，能够**自主规划、定时执行、个性化筛选**信息，生成每日简报并推送。

## 技术栈

| 组件 | 选型 |
|------|------|
| Agent 编排 | LangGraph StateGraph |
| LLM | DeepSeek Chat |
| Embedding | bge-small-zh-v1.5 |
| 向量数据库 | ChromaDB |
| 关系数据库 | SQLite (WAL 模式) |
| 定时任务 | APScheduler |
| 搜索补充 | MCP Server (SSE :8100) |
| 推送服务 | MCP Server (stdio) |
| 用户界面 | Streamlit |
| 日志 | structlog |

## 环境要求

- Python 3.10+
- 8GB+ RAM（Embedding 模型需要）
- 网络连接（用于 LLM API 调用和 RSS 采集）

## 安装

```bash
# 克隆或进入项目目录后
pip install -r requirements.txt
```

## 配置

编辑 `config/config.yaml`，填写 DeepSeek API Key：

```yaml
llm:
  deepseek:
    api_key: "sk-your-api-key"
```

其余参数（调度时间、排序权重、去重阈值等）已预设 MVP 推荐值，可直接使用。

## 初始化数据库

```bash
python scripts/init_db.py
```

## 启动

```bash
# 启动 Streamlit 前端（含 APScheduler 后台定时任务）
streamlit run app.py

# 如需测试 MCP 搜索服务（单独启动）
python -m mcp_servers.search_server
```

## 运行测试

```bash
# 全 mock，无需外部依赖
python scripts/test_main_agent.py
python scripts/test_briefing_agent.py
python scripts/test_feedback_agent.py
python scripts/test_memory_manager.py
python scripts/test_integration.py
python scripts/test_logging_monitoring.py
python scripts/test_cold_start_switch.py
python scripts/test_push_scheduler.py

# 需要 Embedding 模型 + ChromaDB
python scripts/test_ranking_agent.py
python scripts/test_collection_agent.py
python scripts/test_fc_tools.py

# 需要先启动 MCP search_server
python scripts/test_mcp_servers.py

# 性能基准（需 Embedding 模型）
python scripts/test_performance.py
```

## 项目结构

```
FeedLens_Agent/
├── agents/            # Agent StateGraph 实现
│   ├── main_agent.py          # 主 Agent（Coordinator + Planner）
│   ├── collection_agent.py    # 采集 Agent（RSS + 搜索补充）
│   ├── ranking_agent.py       # 排序 Agent（去重 + 偏好排序）
│   ├── briefing_agent.py      # 简报 Agent（生成 + 质量审查）
│   ├── feedback_agent.py      # 反馈 Agent（偏好更新）
│   └── state.py               # FeedLensState 定义
├── tools/             # FC 工具 + MCP 客户端
│   ├── fc_tools.py            # RSS/去重/排序/简报 工具函数
│   └── mcp_client.py          # MCP 客户端封装
├── mcp_servers/       # MCP Server
│   ├── search_server.py       # 搜索服务 (SSE :8100)
│   └── push_server.py         # 推送服务 (stdio)
├── models/            # 数据模型
│   ├── database.py            # SQLite 数据库 (11 表)
│   └── vector_store.py        # ChromaDB 向量存储 (3 集合)
├── utils/             # 工具模块
│   ├── llm_provider.py        # LLM Provider 抽象
│   ├── embedding.py           # bge-small-zh-v1.5 封装
│   ├── memory_manager.py      # 记忆管理（短期/长期/情节）
│   ├── logging_config.py      # structlog 配置
│   └── error_isolation.py     # 任务级错误隔离
├── scheduler/         # 调度器
│   └── push_scheduler.py      # APScheduler 定时推送
├── ui/                # Streamlit 前端
│   ├── app.py                 # 入口
│   └── pages/                 # 页面
├── config/            # 配置
│   └── config.yaml
├── scripts/           # 脚本 + 测试
│   ├── init_db.py
│   ├── calibrate_dedup.py
│   ├── test_data/sample_feed.xml
│   ├── test_*.py              # 测试脚本
│   └── ...
└── docs/              # 文档
    ├── FeedLens_MVP_Design_Document.md   # MVP 设计文档 (v1.0)
    ├── FeedLens_MVP_Design_Document_v1.1.md  # 改进补充 (v1.1)
    ├── FeedLens 项目背景与规范.md
    ├── 开发规范.md
    ├── TODO.md
    └── API.md
```
