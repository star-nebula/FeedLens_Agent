"""
FeedLens 工具模块。

FC Tools:
    fetch_rss          - 并行采集多个 RSS 源
    enrich_metadata    - LLM 提取 category/keywords/importance
    normalize_items    - 统一字段格式化
    deduplicate        - 向量去重（阈值 + LLM 裁决）
    db_read            - SQLite 读取
    db_write           - SQLite 写入
    vector_search      - ChromaDB 相似度检索
    vector_add         - ChromaDB 写入向量
"""

from .fc_tools import (
    fetch_rss,
    enrich_metadata,
    normalize_items,
    deduplicate,
    db_read,
    db_write,
    vector_search,
    vector_add,
)