"""
FeedLens FC (Function Calling) 工具模块。

实现所有供 Agent 调用的工具函数，包含：
  - RSS 采集工具
  - LLM 元数据增强工具
  - 数据格式化工具
  - 向量去重工具
  - SQLite 读写工具
  - ChromaDB 向量工具

Usage:
    from tools.fc_tools import (
        fetch_rss, enrich_metadata, normalize_items, deduplicate,
        db_read, db_write, vector_search, vector_add
    )
"""

import feedparser
import json
import hashlib
import asyncio
import requests
from typing import Optional, List, Dict, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from models.database import Database
from models.vector_store import VectorStore
from utils.llm_provider import LLMProvider, DeepSeekProvider
from utils.embedding import EmbeddingModel


# 创建全局请求会话（带连接池和重试）
def _create_session() -> requests.Session:
    """创建优化的 HTTP 会话。"""
    session = requests.Session()

    # 配置连接池
    adapter = HTTPAdapter(
        pool_connections=20,
        pool_maxsize=20,
        max_retries=Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        ),
    )

    session.mount("http://", adapter)
    session.mount("https://", adapter)

    # 设置全局超时
    session.timeout = 10

    return session


# ====================
# RSS 采集工具
# ====================

def fetch_rss(
    source_urls: List[str],
    max_workers: int = 10,
    timeout: int = 10,
) -> List[Dict[str, Any]]:
    """
    并行采集多个 RSS 源（性能优化版）。

    优化点:
    - 增加默认线程数到 10
    - 添加请求超时处理
    - 使用 requests 连接池
    - 优化日期格式化

    Args:
        source_urls: RSS 源 URL 列表
        max_workers: 并行线程数（默认 10）
        timeout: 请求超时时间（秒）

    Returns:
        采集到的条目列表
    """
    all_items = []
    session = _create_session()

    def _format_published(parsed_time) -> str:
        """优化的日期格式化。"""
        if not parsed_time:
            return ""
        return datetime(
            parsed_time.tm_year,
            parsed_time.tm_mon,
            parsed_time.tm_mday,
            parsed_time.tm_hour,
            parsed_time.tm_min,
        ).isoformat() + "Z"

    def fetch_single(url: str) -> List[Dict]:
        try:
            # 使用 requests 获取 RSS 内容（带超时）
            response = session.get(url, timeout=timeout)
            response.raise_for_status()

            # 使用 feedparser 解析
            feed = feedparser.parse(response.content)

            items = []
            for entry in feed.entries:
                content = ""
                if hasattr(entry, 'content') and entry.content:
                    content = entry.content[0].get('value', '')
                elif hasattr(entry, 'description'):
                    content = entry.description

                published_at = _format_published(
                    entry.published_parsed if hasattr(entry, 'published_parsed') else entry.updated_parsed if hasattr(entry, 'updated_parsed') else None
                )

                item = {
                    "source_url": url,
                    "title": entry.get('title', ''),
                    "summary": entry.get('summary', '') or content[:300],
                    "content": content,
                    "url": entry.get('link', ''),
                    "published_at": published_at,
                    "raw_entry": dict(entry),
                }
                items.append(item)
            return items
        except TimeoutError:
            return [{"source_url": url, "error": "timeout"}]
        except requests.RequestException as e:
            return [{"source_url": url, "error": f"http_error: {str(e)}"}]
        except Exception as e:
            return [{"source_url": url, "error": str(e)}]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(fetch_single, url): url for url in source_urls}
        for future in as_completed(future_to_url, timeout=max_workers * timeout + 10):
            url = future_to_url[future]
            try:
                items = future.result()
                all_items.extend(items)
            except TimeoutError:
                all_items.append({"source_url": url, "error": "pool_timeout"})

    return all_items


# ====================
# LLM 元数据增强工具
# ====================

def enrich_metadata(
    items: List[Dict[str, Any]],
    llm_provider: LLMProvider,
    batch_size: int = 5,
) -> List[Dict[str, Any]]:
    """
    使用 LLM 提取条目元数据（category/keywords/importance）。

    Args:
        items: 条目列表
        llm_provider: LLM Provider 实例
        batch_size: 批量处理大小

    Returns:
        增强后的条目列表，新增字段:
        - category: str (分类)
        - keywords: str (逗号分隔关键词)
        - importance: float (0-1 重要性评分)
    """
    enriched_items = []

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        prompt = build_enrich_prompt(batch)

        try:
            response = llm_provider.chat([{"role": "user", "content": prompt}])
            results = parse_enrich_response(response, len(batch))

            for j, item in enumerate(batch):
                if j < len(results):
                    item["category"] = results[j]["category"]
                    item["keywords"] = results[j]["keywords"]
                    item["importance"] = results[j]["importance"]
                else:
                    item["category"] = "other"
                    item["keywords"] = ""
                    item["importance"] = 0.5
                enriched_items.append(item)
        except Exception as e:
            for item in batch:
                item["category"] = "other"
                item["keywords"] = ""
                item["importance"] = 0.5
                item["enrich_error"] = str(e)
                enriched_items.append(item)

    return enriched_items


def build_enrich_prompt(items: List[Dict]) -> str:
    """构建元数据增强的 LLM 提示词。"""
    items_text = "\n\n".join([
        f"条目 {i + 1}:\n标题: {item['title']}\n内容: {item['summary'][:500]}"
        for i, item in enumerate(items)
    ])

    prompt = f"""请分析以下新闻条目，提取元数据。

要求：
1. category: 从 [technology, business, science, entertainment, sports, politics, other] 中选择一个
2. keywords: 提取3-5个关键词，逗号分隔
3. importance: 0-1 的重要性评分（影响大的事件评分高）

返回格式：
```json
[
  {{"category": "xxx", "keywords": "关键词1,关键词2", "importance": 0.8}}
]
```

条目列表：
{items_text}"""

    return prompt


def parse_enrich_response(response: str, expected_count: int) -> List[Dict]:
    """解析 LLM 元数据增强响应。"""
    try:
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0].strip()
        elif "```" in response:
            response = response.split("```")[1].split("```")[0].strip()

        results = json.loads(response)
        if isinstance(results, list):
            return results[:expected_count]
    except Exception:
        pass

    return [{"category": "other", "keywords": "", "importance": 0.5}] * expected_count


# ====================
# 数据格式化工具
# ====================


def _extract_source_name(source_url: str) -> str:
    """从 source_url 提取可读的源名称。"""
    if not source_url:
        return "unknown"
    known_names = {
        # 新源（国内可直连）
        "https://36kr.com/feed": "36氪",
        "https://sspai.com/feed": "少数派",
        "https://www.ruanyifeng.com/blog/atom.xml": "阮一峰周刊",
        "https://www.solidot.org/index.rss": "Solidot",
        "https://feeds.bbci.co.uk/news/technology/rss.xml": "BBC",
        # 旧源（rsshub.app，保留映射以便历史数据回显）
        "https://rsshub.app/solidot/": "Solidot",
        "https://rsshub.app/36kr/information/web_news/": "36氪",
        "https://rsshub.app/36kr/news/latest": "36氪",
        "https://rsshub.app/zhihu/daily": "知乎日报",
        "https://rsshub.app/v2ex/topics/latest": "V2EX",
        "https://rsshub.app/github/trending/daily": "GitHub",
    }
    if source_url in known_names:
        return known_names[source_url]
    import re
    m = re.search(r'https?://([^/]+)', source_url)
    if m:
        return m.group(1).replace("www.", "").replace("feeds.", "").split(".")[0]
    return source_url


def normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    统一字段格式化，确保所有条目有一致的字段结构。

    Args:
        items: 原始条目列表

    Returns:
        规范化后的条目列表
    """
    normalized = []

    for item in items:
        norm_item = {
            "id": item.get("id", ""),
            "source_url": item.get("source_url", ""),
            "source_id": item.get("source_id", None),
            "source": item.get("source", "") or _extract_source_name(item.get("source_url", "")),
            "title": item.get("title", "").strip(),
            "summary": item.get("summary", "").strip()[:500],
            "content": item.get("content", "").strip()[:2000],
            "url": item.get("url", "").strip(),
            "published_at": item.get("published_at", ""),
            "fetched_at": item.get("fetched_at", ""),
            "category": item.get("category", "other"),
            "keywords": item.get("keywords", ""),
            "importance": float(item.get("importance", 0.5)),
            "embedding": item.get("embedding", None),
            "embedding_id": item.get("embedding_id", ""),
            "similarity_score": item.get("similarity_score", 0.0),
        }

        if not norm_item["id"]:
            norm_item["id"] = generate_item_id(norm_item["title"], norm_item["url"])

        normalized.append(norm_item)

    return normalized


def generate_item_id(title: str, url: str) -> str:
    """基于标题和URL生成唯一ID。"""
    content = f"{title}|{url}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()


# ====================
# 向量去重工具
# ====================

def deduplicate(
    items: List[Dict[str, Any]],
    vector_store: VectorStore,
    embedding_model: EmbeddingModel,
    llm_provider: LLMProvider,
    threshold_high: float = 0.88,
    threshold_low: float = 0.70,
    max_llm_adjudications: int = 20,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    向量去重：高阈值直接判重，低阈值保留，中间区间 LLM 裁决。

    Args:
        items: 待去重条目列表
        vector_store: 向量存储实例
        embedding_model: Embedding 模型实例
        llm_provider: LLM Provider 实例
        threshold_high: 高阈值（>= 此值判重）
        threshold_low: 低阈值（<= 此值保留）
        max_llm_adjudications: LLM 裁决上限

    Returns:
        (unique_items, duplicate_pairs)
        - unique_items: 去重后的条目
        - duplicate_pairs: 去重关系记录
    """
    if len(items) < 2:
        return items, []

    documents = [f"{item['title']} {item['summary']}" for item in items]
    embeddings = embedding_model.encode(documents).tolist()

    for i, item in enumerate(items):
        item["embedding"] = embeddings[i]

    pairs = []
    n = len(items)
    for i in range(n):
        for j in range(i + 1, n):
            sim = cosine_similarity(embeddings[i], embeddings[j])
            if sim >= threshold_low:
                pairs.append({
                    "item_a_index": i,
                    "item_b_index": j,
                    "similarity_score": sim,
                    "items": [items[i], items[j]],
                })

    pairs.sort(key=lambda x: x["similarity_score"], reverse=True)

    duplicate_set = set()
    duplicate_pairs = []
    llm_adjudicated = 0

    for pair in pairs:
        i, j = pair["item_a_index"], pair["item_b_index"]
        if i in duplicate_set or j in duplicate_set:
            continue

        score = pair["similarity_score"]

        if score >= threshold_high:
            duplicate_set.add(j)
            duplicate_pairs.append({
                "item_a_id": items[i]["id"],
                "item_b_id": items[j]["id"],
                "similarity_score": score,
                "dedup_method": "vector_threshold",
                "relation_type": "duplicate",
            })
        elif threshold_low <= score < threshold_high:
            if llm_adjudicated < max_llm_adjudications:
                is_duplicate = llm_adjudicate_duplicate(
                    items[i], items[j], score, llm_provider
                )
                llm_adjudicated += 1

                if is_duplicate:
                    duplicate_set.add(j)
                    duplicate_pairs.append({
                        "item_a_id": items[i]["id"],
                        "item_b_id": items[j]["id"],
                        "similarity_score": score,
                        "dedup_method": "llm_adjudication",
                        "relation_type": "duplicate",
                    })
            else:
                duplicate_set.add(j)
                duplicate_pairs.append({
                    "item_a_id": items[i]["id"],
                    "item_b_id": items[j]["id"],
                    "similarity_score": score,
                    "dedup_method": "hard_limit",
                    "relation_type": "duplicate",
                })

    unique_items = [item for idx, item in enumerate(items) if idx not in duplicate_set]

    for item in unique_items:
        item["similar_count"] = 1

    return unique_items, duplicate_pairs


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """计算余弦相似度。"""
    dot = sum(a * b for a, b in zip(vec1, vec2))
    mag1 = (sum(a * a for a in vec1)) ** 0.5
    mag2 = (sum(b * b for b in vec2)) ** 0.5
    return dot / (mag1 * mag2) if mag1 * mag2 > 0 else 0.0


def llm_adjudicate_duplicate(
    item_a: Dict[str, Any],
    item_b: Dict[str, Any],
    similarity_score: float,
    llm_provider: LLMProvider,
) -> bool:
    """LLM 裁决两条目是否重复。"""
    prompt = f"""以下两条新闻条目，向量相似度为 {similarity_score:.4f}。请判断它们是否属于同一事件的重复报道。

条目A: {item_a['title']}
条目B: {item_b['title']}

条目A摘要: {item_a['summary'][:300]}
条目B摘要: {item_b['summary'][:300]}

请回答 YES 或 NO。"""

    try:
        response = llm_provider.chat([{"role": "user", "content": prompt}])
        return "YES" in response.upper()
    except Exception:
        return True


# ====================
# SQLite 读写工具
# ====================

def db_read(
    db_path: str,
    query: str,
    params: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """
    SQLite 读取操作。

    Args:
        db_path: 数据库路径
        query: SQL 查询语句
        params: 查询参数列表

    Returns:
        查询结果列表，每行转为字典
    """
    db = Database(db_path)
    with db.get_connection() as conn:
        cursor = conn.execute(query, params or [])
        rows = cursor.fetchall()
        result = []
        for row in rows:
            result.append(dict(row))
        return result


def db_write(
    db_path: str,
    query: str,
    params: Optional[List[Any]] = None,
) -> int:
    """
    SQLite 写入操作。

    Args:
        db_path: 数据库路径
        query: SQL 语句（INSERT/UPDATE/DELETE）
        params: 查询参数列表

    Returns:
        影响的行数
    """
    db = Database(db_path)
    with db.get_connection() as conn:
        cursor = conn.execute(query, params or [])
        return cursor.rowcount


# ====================
# ChromaDB 向量工具
# ====================

def vector_search(
    persist_dir: str,
    query_text: str,
    n_results: int = 10,
    collection_name: str = "feed_items",
) -> List[Dict[str, Any]]:
    """
    ChromaDB 相似度检索。

    Args:
        persist_dir: ChromaDB 持久化目录
        query_text: 查询文本
        n_results: 返回结果数
        collection_name: 集合名称

    Returns:
        检索结果列表，包含 id, distance, metadata
    """
    embedding_model = EmbeddingModel()
    vs = VectorStore(persist_dir=persist_dir, embedding_fn=embedding_model.encode)
    vs.init_collections()

    result = vs.search_similar(query_text, n_results=n_results, collection=collection_name)

    hits = []
    ids = result.get("ids", [[]])[0]
    distances = result.get("distances", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    documents = result.get("documents", [[]])[0]

    for i in range(len(ids)):
        hits.append({
            "id": ids[i],
            "distance": distances[i],
            "similarity": 1.0 - distances[i],
            "metadata": metadatas[i] if metadatas else {},
            "document": documents[i] if documents else "",
        })

    return hits


def vector_add(
    persist_dir: str,
    ids: List[str],
    documents: List[str],
    metadatas: Optional[List[Dict]] = None,
    embeddings: Optional[List[List[float]]] = None,
    collection_name: str = "feed_items",
) -> int:
    """
    ChromaDB 写入向量。

    Args:
        persist_dir: ChromaDB 持久化目录
        ids: 文档 ID 列表
        documents: 文档内容列表
        metadatas: 元数据列表
        embeddings: 预计算的向量列表（可选）
        collection_name: 集合名称

    Returns:
        添加的文档数量
    """
    embedding_model = EmbeddingModel()
    vs = VectorStore(persist_dir=persist_dir, embedding_fn=embedding_model.encode)
    vs.init_collections()

    if embeddings is None:
        embeddings = embedding_model.encode(documents).tolist()

    vs.add_items(
        ids=ids,
        documents=documents,
        metadatas=metadatas or [{}] * len(ids),
        embeddings=embeddings,
    )

    return len(ids)
