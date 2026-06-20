"""
FeedLens Embedding 模块（离线模式：本地缓存模型 ~/.cache/huggingface/hub/models--BAAI--bge-small-zh-v1.5/）。

加载 bge-small-zh-v1.5 模型，提供 encode() 编码接口。
目标推理速度 < 100ms/条。

Usage:
    from utils.embedding import EmbeddingModel
    model = EmbeddingModel()
    embeddings = model.encode(["文本1", "文本2"])
"""

import numpy as np
import time
import os
from sentence_transformers import SentenceTransformer


class EmbeddingModel:
    """bge-small-zh-v1.5 本地推理封装（单例模式）。"""

    _instance = None

    def __new__(cls, model_name: str = "BAAI/bge-small-zh-v1.5", device: str = "cpu"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5", device: str = "cpu"):
        if self._initialized:
            return
        self.model_name = model_name
        self.device = device
        self._model: SentenceTransformer | None = None
        self._initialized = True

    def load(self):
        """加载模型（延迟加载，首次调用 encode 时自动触发）。"""
        if self._model is not None:
            return
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        self._model = SentenceTransformer(self.model_name, device=self.device, local_files_only=True)

    def encode(
        self,
        texts: list[str],
        normalize: bool = True,
        show_progress_bar: bool = False,
    ) -> np.ndarray:
        """将文本列表编码为向量。

        Returns:
            np.ndarray, shape=(len(texts), 384)
        """
        self.load()
        embeddings = self._model.encode(
            texts,
            normalize_embeddings=normalize,
            show_progress_bar=show_progress_bar,
        )
        return np.array(embeddings)

    def encode_single(self, text: str) -> np.ndarray:
        """编码单条文本。"""
        return self.encode([text])[0]

    def verify_speed(self, sample_texts: list[str] = None) -> float:
        """验证推理速度，返回 ms/条。"""
        if sample_texts is None:
            sample_texts = ["测试文本片段，用于验证 embedding 推理速度。" * 3]
        self.load()
        start = time.perf_counter()
        self.encode(sample_texts)
        elapsed_ms = (time.perf_counter() - start) * 1000
        per_item = elapsed_ms / len(sample_texts)
        return per_item

