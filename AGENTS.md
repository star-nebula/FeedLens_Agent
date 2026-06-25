# AGENTS.md — FeedLens Agent 项目指引

## 项目概述

基于 LangGraph + DeepSeek 的多 Agent 智能信息简报系统。主 Agent 编排 Collection → Ranking → Briefing 三个子 Agent，通过 ReAct 循环自主决策。

## 快速启动

```bash
pip install -r requirements.txt
python scripts/init_db.py          # 初始化 SQLite（11 张表）
streamlit run app.py               # 启动 UI + APScheduler 后台
```

配置 `config/config.yaml`，填写 DeepSeek API Key（支持环境变量 `${DEEPSEEK_API_KEY}`）。

## 运行测试

```bash
# 全 mock，无需外部依赖（推荐先跑这些）
python scripts/test_main_agent.py
python scripts/test_briefing_agent.py
python scripts/test_feedback_agent.py
python scripts/test_memory_manager.py
python scripts/test_integration.py

# 需要 Embedding 模型 + ChromaDB（首次运行会自动下载模型 ~130MB）
python scripts/test_ranking_agent.py
python scripts/test_collection_agent.py

# 需要先启动 MCP search_server
python -m mcp_servers.search_server   # SSE :8100
python scripts/test_mcp_servers.py
```

## 核心架构

- **入口**: `app.py` → Streamlit UI，点"立即运行"触发 `utils/pipeline_runner.py`（子进程）
- **主 Agent**: `agents/main_agent.py` — LangGraph StateGraph，Router(LLM动态路由) + Planner(编排) + Observer(审查)
- **子 Agent**: `agents/collection_agent.py`(RSS采集+搜索补充) → `agents/ranking_agent.py`(向量去重+多因子排序) → `agents/briefing_agent.py`(简报生成+质量检查)
- **共享状态**: `agents/state.py` — `FeedLensState(TypedDict)`，所有 Agent 读写同一 State
- **工具注册**: `tools/tool_registry.py` — 13 个工具 schema，统一 dispatch
- **MCP 服务**: `mcp_servers/search_server.py`(SSE :8100) + `mcp_servers/push_server.py`(stdio)

## 关键配置 (config/config.yaml)

- `agents.max_react_cycles: 3` — ReAct 循环上限
- `agents.collection_mode: pipeline` — 采集模式（pipeline/react）
- `ranking.dedup_threshold: 0.88` — 去重向量阈值
- `enrich_metadata.enabled: false` — LLM 元数据增强默认关闭（省 API）
- `prefilter.enabled: true` — 跨批次向量预过滤
- 支持模型回退链：`llm.fallback` 配置备用 Provider

## LLM Provider

`utils/llm_provider.py` — 统一接口，支持 DeepSeek（主）+ 可扩展备用 Provider。所有 LLM 调用通过 `LLMProvider.chat()` / `chat_with_tools()`。

## Embedding

`utils/embedding.py` — 本地 bge-small-zh-v1.5，首次运行自动下载。`models/vector_store.py` 管理 ChromaDB（3 个集合）。

## 注意事项

- SQLite 使用 WAL 模式，数据库文件在 `data/feedlens.db`
- ChromaDB 持久化在 `data/chroma/`，向量预过滤依赖此数据
- `utils/execution_fence.py` — 执行栅栏，防止并发执行
- `utils/error_isolation.py` — 子 Agent 执行隔离，单个失败不阻塞整条管线
- 测试脚本在 `scripts/test_*.py`，不是 pytest 风格，直接 `python scripts/test_xxx.py` 运行
