"""下载 Embedding 模型到本地缓存（使用 HuggingFace 镜像站）。"""

import os
import sys

# 使用 HuggingFace 镜像站加速
os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"

MODELS = [
    "BAAI/bge-small-zh-v1.5",
]


def download_model(model_name: str):
    """下载模型到本地 HuggingFace 缓存目录。"""
    print(f"Downloading {model_name} ...")
    try:
        from sentence_transformers import SentenceTransformer
        _ = SentenceTransformer(model_name, device="cpu")
        print(f"  ✓ {model_name} downloaded/cached successfully")
    except Exception as e:
        print(f"  ✗ {model_name} download failed: {e}")
        sys.exit(1)


def main():
    print("=" * 50)
    print("FeedLens 模型下载工具")
    print("(使用 HuggingFace 镜像: hf-mirror.com)")
    print("=" * 50)

    for model in MODELS:
        download_model(model)

    print("\nAll models downloaded. 缓存路径:")
    print(f"  {os.path.expanduser('~/.cache/huggingface/hub/')}")
    print("\n后续运行 Streamlit 时，建议设置环境变量避免网络检查:")
    print("  $env:HF_HUB_OFFLINE='1'")


if __name__ == "__main__":
    main()
