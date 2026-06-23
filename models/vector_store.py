"""
FeedLens ChromaDB 向量存储模块。

管理 3 个集合：
  - feed_items:      条目向量 (去重 + 相似度检索)
  - user_preference: 用户偏好向量 (v_like / v_dislike 正负分离)
  - domain_knowledge: 语义记忆种子数据

Usage:
    from models.vector_store import VectorStore
    vs = VectorStore(persist_dir="data/chroma")
    vs.init_collections()
    vs.add_items("feed_items", ids=[...], documents=[...], metadatas=[...])
"""

import chromadb
from chromadb import EmbeddingFunction
import os
from typing import Optional, Callable


class BgeEmbeddingFunction(EmbeddingFunction):
    """ChromaDB EmbeddingFunction 接口封装，使用 bge-small-zh-v1.5。"""

    def __init__(self, embedding_fn: Callable):
        self._embedding_fn = embedding_fn

    def __call__(self, texts: list[str]) -> list[list[float]]:
        """ChromaDB 调用此方法生成嵌入。"""
        embeddings = self._embedding_fn(texts)
        if hasattr(embeddings, 'tolist'):
            return embeddings.tolist()
        return embeddings

    def name(self) -> str:
        """ChromaDB 需要的名称方法。"""
        return "bge-small-zh-v1.5"


class VectorStore:
    """ChromaDB 封装：持久化存储 + 3 集合管理 + CRUD 操作。"""

    COLLECTION_FEED_ITEMS = "feed_items"
    COLLECTION_USER_PREF = "user_preference"
    COLLECTION_DOMAIN_KNOWLEDGE = "domain_knowledge"

    def __init__(
        self,
        persist_dir: str = "data/chroma",
        embedding_fn: Optional[Callable] = None,
    ):
        self.persist_dir = persist_dir
        os.makedirs(persist_dir, exist_ok=True)

        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embedding_fn = embedding_fn
        self.chroma_embedding_fn = None
        if embedding_fn is not None:
            self.chroma_embedding_fn = BgeEmbeddingFunction(embedding_fn)
        self._collections: dict[str, chromadb.Collection] = {}

    def init_collections(self, force_recreate: bool = False):
        """初始化 3 个集合（幂等）。"""
        kwargs = {}
        if self.chroma_embedding_fn is not None:
            kwargs["embedding_function"] = self.chroma_embedding_fn

        collections = [
            (self.COLLECTION_FEED_ITEMS, "条目向量：去重 + 相似度检索"),
            (self.COLLECTION_USER_PREF, "用户偏好向量：v_like / v_dislike 正负分离"),
            (self.COLLECTION_DOMAIN_KNOWLEDGE, "语义记忆种子数据（MVP 手动维护）"),
        ]

        for name, description in collections:
            try:
                if force_recreate:
                    self.client.delete_collection(name)
                self._collections[name] = self.client.get_or_create_collection(
                    name=name,
                    metadata={"description": description},
                    **kwargs,
                )
            except ValueError as e:
                if "embedding function conflict" in str(e).lower():
                    self.client.delete_collection(name)
                    self._collections[name] = self.client.create_collection(
                        name=name,
                        metadata={"description": description},
                        **kwargs,
                    )
                else:
                    raise

    def get_collection(self, name: str) -> chromadb.Collection:
        """获取已初始化的集合。"""
        if name not in self._collections:
            self._collections[name] = self.client.get_collection(name)
        return self._collections[name]

    def add_items(
        self,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        embeddings: Optional[list[list[float]]] = None,
    ):
        """批量添加条目向量到 feed_items 集合。"""
        col = self.get_collection(self.COLLECTION_FEED_ITEMS)
        if embeddings is None and self.embedding_fn is not None:
            embeddings = self.embedding_fn(documents)
            if hasattr(embeddings, 'tolist'):
                embeddings = embeddings.tolist()
        col.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)

    def search_similar(
        self,
        query_text: str,
        n_results: int = 10,
        collection: str = COLLECTION_FEED_ITEMS,
    ) -> dict:
        """向量相似度检索。"""
        col = self.get_collection(collection)
        if self.embedding_fn is not None:
            query_embedding = self.embedding_fn([query_text])[0]
            if hasattr(query_embedding, 'tolist'):
                query_embedding = query_embedding.tolist()
            return col.query(query_embeddings=[query_embedding], n_results=n_results)
        else:
            return col.query(query_texts=[query_text], n_results=n_results)

    def get_by_ids(self, ids: list[str], collection: str = COLLECTION_FEED_ITEMS) -> dict:
        """按 ID 批量获取。"""
        col = self.get_collection(collection)
        return col.get(ids=ids)

    def delete_by_ids(self, ids: list[str], collection: str = COLLECTION_FEED_ITEMS):
        """按 ID 批量删除。"""
        col = self.get_collection(collection)
        col.delete(ids=ids)

    def upsert_preference(
        self,
        user_id: str,
        like_embedding: Optional[list[float]] = None,
        dislike_embedding: Optional[list[float]] = None,
    ):
        """更新用户偏好向量（正负分离）。"""
        col = self.get_collection(self.COLLECTION_USER_PREF)
        ids = []
        embeddings = []
        metadatas = []
        documents = []

        if like_embedding is not None:
            ids.append(f"user_{user_id}_like")
            embeddings.append(like_embedding)
            metadatas.append({"user_id": user_id, "pref_type": "like"})
            documents.append(f"User {user_id} positive preferences")

        if dislike_embedding is not None:
            ids.append(f"user_{user_id}_dislike")
            embeddings.append(dislike_embedding)
            metadatas.append({"user_id": user_id, "pref_type": "dislike"})
            documents.append(f"User {user_id} negative preferences")

        if ids:
            col.upsert(ids=ids, embeddings=embeddings, metadatas=metadatas, documents=documents)

    def get_preference(self, user_id: str) -> dict:
        """获取用户的 like/dislike 向量。"""
        col = self.get_collection(self.COLLECTION_USER_PREF)
        result = col.get(ids=[f"user_{user_id}_like", f"user_{user_id}_dislike"])
        pref = {"like_embedding": None, "dislike_embedding": None}
        for i, _id in enumerate(result.get("ids", [])):
            if _id.endswith("_like"):
                pref["like_embedding"] = result["embeddings"][i] if result.get("embeddings") else None
            elif _id.endswith("_dislike"):
                pref["dislike_embedding"] = result["embeddings"][i] if result.get("embeddings") else None
        return pref

    def add_knowledge(
        self,
        ids: list[str],
        documents: list[str],
        topics: list[str],
        seed_flag: bool = False,
    ):
        """添加语义记忆种子数据。"""
        col = self.get_collection(self.COLLECTION_DOMAIN_KNOWLEDGE)
        embeddings = None
        if self.embedding_fn is not None:
            embeddings = self.embedding_fn(documents)
            if hasattr(embeddings, 'tolist'):
                embeddings = embeddings.tolist()
        col.add(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=[{"topic": t, "seed_flag": seed_flag} for t in topics],
        )


    def close(self):
        """释放 ChromaDB 客户端资源，关闭 SQLite 连接池，释放 Windows 文件锁。"""
        self._collections.clear()
        if hasattr(self.client, '_system'):
            try:
                self.client._system.stop()
            except Exception:
                pass
        if hasattr(self.client, '_admin_client'):
            try:
                self.client._admin_client._system.stop()
            except Exception:
                pass
        del self.client
        self.client = None
        import gc
        gc.collect()

    def count(self, collection: str = COLLECTION_FEED_ITEMS) -> int:
        col = self.get_collection(collection)
        return col.count()
