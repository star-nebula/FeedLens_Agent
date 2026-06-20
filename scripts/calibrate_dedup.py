"""
去重阈值校准脚本

功能：
  - 加载标注样本（item_a, item_b, is_duplicate）
  - 计算向量相似度
  - 扫描不同阈值下的 P/R/F1
  - 输出最优阈值

用法：
  python scripts/calibrate_dedup.py --samples data/labeled_dedup_samples.json
  python scripts/calibrate_dedup.py --generate  # 生成随机测试样本
"""

import argparse
import json
import os
import sys
import random
import numpy as np
from datetime import datetime
from typing import List, Dict, Any, Tuple

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.embedding import EmbeddingModel
from tools.fc_tools import cosine_similarity


# ============================================================
# 样本数据结构
# ============================================================

def make_sample_items(n: int = 20) -> List[Dict[str, Any]]:
    """生成随机测试条目用于演示阈值校准。

    返回:
        items: 包含 title, summary, id 的测试条目列表
    """
    templates = [
        ("苹果发布iPhone 16 Pro", "苹果公司在今日发布会上推出了iPhone 16 Pro，搭载A18芯片"),
        ("Apple推出iPhone 16 Pro", "Apple Inc. announced iPhone 16 Pro with A18 chip at today's event"),
        ("iPhone 16 Pro正式发布", "iPhone 16 Pro机型今日正式发布，售价999美元起"),
        ("特斯拉Model Y降价", "特斯拉宣布Model Y车型降价5000元，起售价降至25万元"),
        ("Tesla Model Y价格下调", "Tesla reduces Model Y price by 5000 RMB, starting at 250k"),
        ("特斯拉新款Model Y上市", "特斯拉新款Model Y正式上市，续航提升10%"),
        ("OpenAI发布GPT-5", "OpenAI发布GPT-5，性能比GPT-4提升5倍"),
        ("GPT-5语言模型推出", "OpenAI launches GPT-5 language model with 5x performance improvement"),
        ("谷歌AI通过医师考试", "Google AI passes medical licensing exam with 85% accuracy"),
        ("Google AI医师考试通过", "Google's artificial intelligence system passed the medical exam"),
        ("新能源车购置税减免", "财政部宣布新能源汽车购置税减免政策延续至2027年"),
        ("电动汽车购置税优惠", "Electric vehicle purchase tax exemption policy extended to 2027"),
        ("英特尔发布新处理器", "Intel launches new processor with 20% performance boost"),
        ("Intel处理器新品发布", "Intel announced new processor generation with improved efficiency"),
        ("华为发布Mate 70", "华为发布Mate 70系列，搭载鸿蒙OS 5.0"),
        ("华为Mate 70上市", "Huawei Mate 70 series goes on sale with HarmonyOS 5.0"),
    ]

    items = []
    used_templates = set()
    for i in range(n):
        if i < len(templates):
            title, summary = templates[i]
        else:
            title = f"新闻标题{i}"
            summary = f"这是第{i}条新闻的摘要内容"
        items.append({
            "id": f"item_{i+1}",
            "title": title,
            "summary": summary,
        })
        used_templates.add(title)
    return items


def generate_labeled_pairs(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """为测试条目生成标注对（模拟人工标注结果）。

    规则：
      - 相同模板的条目对 → is_duplicate=True（跨语言同事件）
      - 相近领域但不同事件的条目对 → is_duplicate=False
      - 随机抽取部分对作为模糊样本

    Returns:
        pairs: 包含 item_a_id, item_b_id, is_duplicate 的标注列表
    """
    n = len(items)
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            title_a = items[i]["title"]
            title_b = items[j]["title"]

            # 跨语言同事件（如 "苹果" vs "Apple"）
            is_same_event = False
            same_events = [
                ("苹果发布iPhone 16 Pro", "Apple推出iPhone 16 Pro"),
                ("苹果发布iPhone 16 Pro", "iPhone 16 Pro正式发布"),
                ("Apple推出iPhone 16 Pro", "iPhone 16 Pro正式发布"),
                ("特斯拉Model Y降价", "Tesla Model Y价格下调"),
                ("特斯拉Model Y降价", "特斯拉新款Model Y上市"),
                ("Tesla Model Y价格下调", "特斯拉新款Model Y上市"),
                ("OpenAI发布GPT-5", "GPT-5语言模型推出"),
                ("谷歌AI通过医师考试", "Google AI医师考试通过"),
                ("新能源车购置税减免", "电动汽车购置税优惠"),
                ("英特尔发布新处理器", "Intel处理器新品发布"),
                ("华为发布Mate 70", "华为Mate 70上市"),
            ]
            for evt_a, evt_b in same_events:
                if (title_a == evt_a and title_b == evt_b) or \
                   (title_a == evt_b and title_b == evt_a):
                    is_same_event = True
                    break

            pairs.append({
                "item_a_id": items[i]["id"],
                "item_b_id": items[j]["id"],
                "title_a": title_a,
                "title_b": title_b,
                "is_duplicate": is_same_event,
            })

    return pairs


def load_labeled_samples(path: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """从 JSON 文件加载标注样本。

    JSON 格式：
    {
        "items": [{"id": "item_1", "title": "...", "summary": "..."}, ...],
        "pairs": [{"item_a_id": "item_1", "item_b_id": "item_2", "is_duplicate": true}, ...]
    }

    Returns:
        (items, pairs)
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"样本文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    items = data.get("items", [])
    pairs = data.get("pairs", [])
    return items, pairs


def compute_similarities(
    items: List[Dict[str, Any]],
    pairs: List[Dict[str, Any]],
    embedding_model: EmbeddingModel,
) -> List[Dict[str, Any]]:
    """计算所有标注对的向量相似度。

    Returns:
        pairs: 在原基础上增加 similarity_score 字段
    """
    # 构建 id -> item 映射
    item_map = {item["id"]: item for item in items}

    # 批量计算 embedding
    texts = [f"{item['title']} {item['summary']}" for item in items]
    embeddings = embedding_model.encode(texts)
    if hasattr(embeddings, "tolist"):
        embeddings = embeddings.tolist()

    item_embeddings = {item["id"]: emb for item, emb in zip(items, embeddings)}

    # 计算每对的相似度
    for pair in pairs:
        emb_a = item_embeddings.get(pair["item_a_id"])
        emb_b = item_embeddings.get(pair["item_b_id"])
        if emb_a is not None and emb_b is not None:
            sim = cosine_similarity(emb_a, emb_b)
            pair["similarity_score"] = sim
        else:
            pair["similarity_score"] = 0.0

    return pairs


def calculate_prf_at_threshold(
    pairs: List[Dict[str, Any]],
    threshold: float,
) -> Tuple[float, float, float]:
    """计算给定阈值下的 P/R/F1。

    预测规则：similarity_score >= threshold → 预测为重复

    Returns:
        (precision, recall, f1)
    """
    if not pairs:
        return 0.0, 0.0, 0.0

    tp = sum(1 for p in pairs if p["similarity_score"] >= threshold and p["is_duplicate"])
    fp = sum(1 for p in pairs if p["similarity_score"] >= threshold and not p["is_duplicate"])
    fn = sum(1 for p in pairs if p["similarity_score"] < threshold and p["is_duplicate"])

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    return precision, recall, f1


def sweep_thresholds(
    pairs: List[Dict[str, Any]],
    min_thresh: float = 0.50,
    max_thresh: float = 0.99,
    step: float = 0.01,
) -> List[Dict[str, Any]]:
    """扫描阈值范围，计算 P/R/F1 曲线。

    Returns:
        results: 包含 threshold, precision, recall, f1 的列表
    """
    results = []
    thresholds = np.arange(min_thresh, max_thresh + step / 2, step)
    for thresh in thresholds:
        thresh = round(thresh, 2)
        p, r, f = calculate_prf_at_threshold(pairs, thresh)
        results.append({
            "threshold": thresh,
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f, 4),
        })
    return results


def find_optimal_threshold(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从 P/R/F1 曲线中找到最优阈值（F1 最大化）。

    Returns:
        optimal: 最优阈值对应的结果
    """
    optimal = max(results, key=lambda x: x["f1"])
    return optimal


def print_prf_table(results: List[Dict[str, Any]]):
    """打印 P/R/F1 表格。"""
    print("\n阈值    P       R       F1")
    print("-" * 35)
    for r in results:
        marker = " *" if r["threshold"] == results[np.argmax([x["f1"] for x in results])]["threshold"] else ""
        print(f"{r['threshold']:.2f}   {r['precision']:.4f}  {r['recall']:.4f}  {r['f1']:.4f}{marker}")
    print("-" * 35)
    print("(* 表示最优阈值)")


def save_results(
    results: List[Dict[str, Any]],
    optimal: Dict[str, Any],
    output_path: str,
):
    """保存校准结果到 JSON 文件。"""
    output = {
        "calibrated_at": datetime.now().isoformat(),
        "optimal_threshold": optimal["threshold"],
        "optimal_f1": optimal["f1"],
        "optimal_precision": optimal["precision"],
        "optimal_recall": optimal["recall"],
        "prf_curve": results,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存至: {output_path}")


# ============================================================
# CLI 入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="去重阈值校准工具")
    parser.add_argument("--samples", type=str, help="标注样本 JSON 文件路径")
    parser.add_argument("--generate", action="store_true", help="使用随机生成样本演示校准")
    parser.add_argument("--output", type=str, default="data/dedup_calibration.json", help="输出结果路径")
    parser.add_argument("--min-thresh", type=float, default=0.50, help="最小阈值")
    parser.add_argument("--max-thresh", type=float, default=0.99, help="最大阈值")
    parser.add_argument("--step", type=float, default=0.01, help="阈值步长")
    args = parser.parse_args()

    # 初始化 Embedding 模型
    print("加载 Embedding 模型...")
    embedding_model = EmbeddingModel()

    if args.generate:
        print("=" * 50)
        print("去重阈值校准（随机样本演示）")
        print("=" * 50)
        items = make_sample_items(n=20)
        pairs = generate_labeled_pairs(items)
        total_pairs = len(pairs)
        dup_pairs = sum(1 for p in pairs if p["is_duplicate"])
        print(f"\n生成了 {len(items)} 条测试数据，{total_pairs} 个标注对（其中 {dup_pairs} 对为重复）")
    elif args.samples:
        print("=" * 50)
        print("去重阈值校准（标注样本）")
        print("=" * 50)
        items, pairs = load_labeled_samples(args.samples)
        total_pairs = len(pairs)
        dup_pairs = sum(1 for p in pairs if p["is_duplicate"])
        print(f"\n加载了 {len(items)} 条数据，{total_pairs} 个标注对（其中 {dup_pairs} 对为重复）")
    else:
        print("请指定 --samples <文件> 或使用 --generate 演示")
        parser.print_help()
        sys.exit(1)

    # 计算相似度
    print("\n计算向量相似度...")
    pairs = compute_similarities(items, pairs, embedding_model)

    # 扫描阈值
    print("扫描阈值范围...")
    results = sweep_thresholds(
        pairs,
        min_thresh=args.min_thresh,
        max_thresh=args.max_thresh,
        step=args.step,
    )

    # 找最优
    optimal = find_optimal_threshold(results)

    # 打印结果
    print_prf_table(results)
    print(f"\n最优阈值: {optimal['threshold']:.2f}")
    print(f"  P = {optimal['precision']:.4f}")
    print(f"  R = {optimal['recall']:.4f}")
    print(f"  F1 = {optimal['f1']:.4f}")

    # 打印当前默认阈值（0.88）的性能
    current = next((r for r in results if r["threshold"] == 0.88), None)
    if current:
        print(f"\n默认阈值 0.88 的性能（对比）:")
        print(f"  P = {current['precision']:.4f}")
        print(f"  R = {current['recall']:.4f}")
        print(f"  F1 = {current['f1']:.4f}")

        if current['f1'] < optimal['f1']:
            improvement = (optimal['f1'] - current['f1']) / current['f1'] * 100
            print(f"  → 优化后可提升 F1 {improvement:.1f}%")

    # 保存结果
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    save_results(results, optimal, args.output)


if __name__ == "__main__":
    main()
