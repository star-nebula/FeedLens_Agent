"""
Embedding 推理速度测试脚本。

Usage:
    python scripts/test_embedding_speed.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.embedding import EmbeddingModel


def main():
    print("[test_embedding_speed] 初始化 Embedding 模型...")
    model = EmbeddingModel()
    
    print("[test_embedding_speed] 加载模型（首次加载可能需要下载）...")
    model.load()
    
    print("[test_embedding_speed] 开始速度测试...")
    
    sample_texts = [
        "AI Agent 技术最新进展和应用案例",
        "新能源车行业政策动向和市场分析",
        "大语言模型推理优化技术",
        "计算机视觉领域最新研究成果",
        "深度学习框架性能对比评测"
    ]
    
    speed = model.verify_speed(sample_texts)
    
    print(f"\n[test_embedding_speed] 测试完成！")
    print(f"  推理速度: {speed:.2f} ms/条")
    print(f"  达标要求: < 100 ms/条")
    print(f"  {'✅ 达标' if speed < 100 else '❌ 未达标'}")


if __name__ == "__main__":
    main()