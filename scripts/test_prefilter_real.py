"""
向量预过滤真实数据测试 — 使用数据库 raw_items 中的历史数据验证过滤效果。

测试流程:
  Step 1: 从 SQLite raw_items 读取历史采集的真实条目
  Step 2: 清空 ChromaDB，取前 N 条写入作为"历史"（模拟上次执行）
  Step 3: 取后 M 条（与历史部分重叠）作为"新采集"条目
  Step 4: 对新采集条目执行 _prefilter_against_history
  Step 5: 验证重叠部分是否被正确拦截，输出统计

用法:
  python scripts/test_prefilter_real.py
  python scripts/test_prefilter_real.py --threshold 0.88 --detailed
"""

import sys
import os
import json
import hashlib
import argparse
import sqlite3
from datetime import datetime
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.collection_agent import _prefilter_against_history
from models.vector_store import VectorStore
from utils.embedding import EmbeddingModel


def _print_separator(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def _load_raw_items_from_db(db_path: str = "data/feedlens.db", limit: int = 200) -> List[Dict[str, Any]]:
    """从 SQLite raw_items 表读取历史采集的条目。"""
    if not os.path.exists(db_path):
        print(f"[DB] 数据库文件不存在: {db_path}")
        return []

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, title, summary, url, source_id, published_at, fetched_at "
        "FROM raw_items ORDER BY fetched_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()

    items = []
    for row in rows:
        items.append({
            "id": row["id"],
            "title": row["title"] or "",
            "summary": row["summary"] or "",
            "url": row["url"] or "",
            "source_id": row["source_id"],
            "published_at": row["published_at"] or "",
            "fetched_at": row["fetched_at"] or "",
        })

    print(f"[DB] 从 raw_items 读取 {len(items)} 条历史条目")
    return items


def _clean_chromadb():
    """清空 feed_items 集合。"""
    try:
        em = EmbeddingModel()
        vs = VectorStore(persist_dir="data/chroma", embedding_fn=em.encode)
        vs.init_collections()
        col = vs.get_collection("feed_items")
        count_before = col.count()
        if count_before > 0:
            results = col.get()
            if results["ids"]:
                col.delete(ids=results["ids"])
                print(f"[clean] 已清空 ChromaDB feed_items: {count_before} -> 0 条")
            else:
                print("[clean] feed_items 为空，无需清空")
        else:
            print("[clean] feed_items 已为空")
    except Exception as e:
        print(f"[clean] 清空失败: {e}")


def _write_to_history(items: List[Dict[str, Any]], label: str = "") -> int:
    """将条目写入 ChromaDB feed_items 集合。"""
    if not items:
        print(f"[history] {label} 无条目可写入")
        return 0

    em = EmbeddingModel()
    vs = VectorStore(persist_dir="data/chroma", embedding_fn=em.encode)
    vs.init_collections()

    now_iso = datetime.now().isoformat()
    ids, docs, metas = [], [], []
    for item in items:
        url = item.get("url", "")
        title = item.get("title", "")
        text = title.strip() if title else ""
        if not text:
            continue
        content_key = f"{url}|{title}"
        item_hash = hashlib.sha256(content_key.encode("utf-8")).hexdigest()[:32]
        ids.append(item_hash)
        docs.append(text)
        metas.append({
            "created_at": now_iso,
            "url": url,
            "source": str(item.get("source_id", "")),
            "title": title[:200],
        })

    if ids:
        vs.upsert_items(collection="feed_items", ids=ids, documents=docs, metadatas=metas)
        print(f"[history] {label} 写入 ChromaDB: {len(ids)} 条")
    return len(ids)


def _get_chroma_stats() -> dict:
    """获取 ChromaDB feed_items 集合统计信息。"""
    try:
        em = EmbeddingModel()
        vs = VectorStore(persist_dir="data/chroma", embedding_fn=em.encode)
        vs.init_collections()
        col = vs.get_collection("feed_items")
        count = col.count()
        return {"count": count, "status": "ok"}
    except Exception as e:
        return {"count": 0, "status": f"error: {e}"}


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="向量预过滤真实数据测试")
    parser.add_argument("--threshold", type=float, default=0.92, help="相似度阈值 (默认 0.92)")
    parser.add_argument("--detailed", action="store_true", help="逐条显示相似度")
    parser.add_argument("--history-ratio", type=float, default=0.6,
                        help="用作历史数据的比例 (默认 0.6，即 60%% 写入历史，40%% 作为新采集)")
    parser.add_argument("--db", type=str, default="data/feedlens.db", help="数据库路径")
    args = parser.parse_args()

    _print_separator("向量预过滤真实数据测试 (数据库模式)")
    print(f"  时间: {datetime.now().isoformat()}")
    print(f"  阈值: {args.threshold}")
    print(f"  历史比例: {args.history_ratio}")

    # Step 1: 从数据库读取真实历史条目
    all_items = _load_raw_items_from_db(args.db, limit=200)
    if len(all_items) < 10:
        print(f"\n[ERROR] 数据库条目不足 ({len(all_items)} 条)，需要至少 10 条")
        return

    # Step 2: 清空 ChromaDB，划分数据
    _clean_chromadb()

    split_idx = int(len(all_items) * args.history_ratio)
    history_items = all_items[:split_idx]
    # 新采集条目 = 全部条目（模拟再次采集，包含历史已有 + 部分新内容）
    # 故意让"新采集"包含部分历史条目来验证拦截效果
    new_items = all_items[split_idx // 2:]  # 后半部分与前半有重叠

    print(f"\n  数据划分:")
    print(f"    历史条目 (写入 ChromaDB): {len(history_items)} 条")
    print(f"    新采集条目 (待过滤):     {len(new_items)} 条")
    print(f"    重叠条目 (预期被拦截):   约 {split_idx - split_idx // 2} 条")

    # Step 3: 写入历史
    written = _write_to_history(history_items, label="History")
    if written == 0:
        print("\n[ERROR] 历史写入失败，退出")
        return

    stats = _get_chroma_stats()
    print(f"  ChromaDB feed_items: {stats['count']} 条")

    # Step 4: 执行预过滤
    _print_separator("执行预过滤")
    kept, discarded = _prefilter_against_history(new_items, threshold=args.threshold, top_k=1)

    total = len(new_items)
    drop_rate = len(discarded) / total * 100 if total else 0

    print(f"\n  预过滤结果:")
    print(f"    输入: {total} 条")
    print(f"    保留: {len(kept)} 条 (新内容)")
    print(f"    丢弃: {len(discarded)} 条 ({drop_rate:.1f}% 历史重复)")

    # 验证被丢弃的条目确实在历史中
    history_urls = {item.get("url", "") for item in history_items}
    discarded_in_history = sum(1 for item in discarded if item.get("url", "") in history_urls)
    discarded_not_in_history = len(discarded) - discarded_in_history

    print(f"\n  丢弃条目分析:")
    print(f"    在历史数据中: {discarded_in_history} 条 (正确拦截)")
    print(f"    不在历史数据中: {discarded_not_in_history} 条 (相似度 >= 阈值但不是完全相同的 URL)")

    # 显示丢弃条目
    if discarded:
        print(f"\n  被丢弃条目 (前 10 条):")
        for i, item in enumerate(discarded[:10]):
            title = item.get("title", "")[:60]
            in_history = "[H]" if item.get("url", "") in history_urls else "[S]"
            print(f"    {i+1}. {in_history} {title}")

    if kept:
        print(f"\n  保留条目 (前 10 条):")
        for i, item in enumerate(kept[:10]):
            title = item.get("title", "")[:60]
            in_history = "[H]" if item.get("url", "") in history_urls else "[N]"
            print(f"    {i+1}. {in_history} {title}")

    # Step 5: 详细分析
    if args.detailed and new_items:
        _print_separator(f"逐条相似度分析 (阈值={args.threshold})")

        em = EmbeddingModel()
        vs = VectorStore(persist_dir="data/chroma", embedding_fn=em.encode)
        vs.init_collections()

        results = []
        for item in new_items:
            title = item.get("title", "")
            text = title.strip() if title else ""
            if not text:
                continue
            try:
                vec = em.encode_single(text)
                sr = vs.search_by_embedding(vec.tolist(), n_results=1, collection="feed_items")
                distances = sr.get("distances", [[]])
                if distances and distances[0] and len(distances[0]) > 0:
                    cos_sim = 1.0 - distances[0][0]
                    verdict = "DISCARD" if cos_sim >= args.threshold else "KEEP"
                    results.append((cos_sim, verdict, title[:55]))
            except Exception:
                pass

        results.sort(key=lambda x: x[0], reverse=True)

        print(f"\n  {'Sim':<8} {'Verdict':<10} {'Title'}")
        print(f"  {'-'*8} {'-'*10} {'-'*55}")
        for sim, verdict, title in results[:30]:
            print(f"  {sim:.4f}   {verdict:<8} {title}")

        above = sum(1 for s, _, _ in results if s >= args.threshold)
        below = len(results) - above
        print(f"\n  相似度分布: >= {args.threshold}: {above} 条, < {args.threshold}: {below} 条")

    # 最终判定
    _print_separator("测试结论")

    # 关键验证点
    if discarded_in_history > 0:
        print(f"  [OK] 历史重复拦截成功: {discarded_in_history} 条与历史 URL 完全匹配的条目被正确丢弃")
    else:
        print("  [WARN] 没有 URL 完全匹配的条目被丢弃，检查阈值是否过高")

    if written == stats.get("count", 0):
        print(f"  [OK] ChromaDB 写入验证通过: 写入 {written} 条 == 集合 {stats.get('count', 0)} 条")
    else:
        print(f"  [WARN] ChromaDB 写入验证异常: 写入 {written} 条 != 集合 {stats.get('count', 0)} 条")
        print("    可能原因: embedding_fn 冲突导致集合被删除重建、upsert ID 冲突等")

    if len(discarded) > 0:
        print(f"\n  ===> 预过滤功能正常！拦截率 {drop_rate:.1f}%")
    else:
        print(f"\n  ===> 预过滤未拦截任何条目，请使用 --detailed 检查相似度分布")


if __name__ == "__main__":
    main()
