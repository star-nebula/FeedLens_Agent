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
        """初始化 3 个集合（幂等）。

        feed_items 集合使用 cosine 距离度量，确保 1 - distance 可直接得到余弦相似度。

        自动检测维度不匹配：如果 ChromaDB 中已有集合的向量维度与当前 embedding 模型
        不一致（如旧数据是 512 维，当前模型是 384 维），自动删除旧集合并重建。
        """
        kwargs = {}
        if self.chroma_embedding_fn is not None:
            kwargs["embedding_function"] = self.chroma_embedding_fn

        # 获取当前 embedding 模型的目标维度
        expected_dim = self._get_expected_embedding_dim()

        # 每个集合的 metadata，feed_items 需要指定 hnsw:space=cosine
        collections = [
            (self.COLLECTION_FEED_ITEMS, {"description": "条目向量：去重 + 相似度检索", "hnsw:space": "cosine"}),
            (self.COLLECTION_USER_PREF, {"description": "用户偏好向量：v_like / v_dislike 正负分离"}),
            (self.COLLECTION_DOMAIN_KNOWLEDGE, {"description": "语义记忆种子数据（MVP 手动维护）"}),
        ]

        for name, metadata in collections:
            try:
                if force_recreate:
                    self.client.delete_collection(name)
                    print(f"[VectorStore] 强制重建集合: {name}", flush=True)

                # 检查已存在集合的维度是否匹配
                if expected_dim is not None and not force_recreate:
                    self._check_and_fix_dimension_mismatch(name, expected_dim)

                self._collections[name] = self.client.get_or_create_collection(
                    name=name,
                    metadata=metadata,
                    **kwargs,
                )
            except ValueError as e:
                if "embedding function conflict" in str(e).lower():
                    self.client.delete_collection(name)
                    self._collections[name] = self.client.create_collection(
                        name=name,
                        metadata=metadata,
                        **kwargs,
                    )
                else:
                    raise

    def _get_expected_embedding_dim(self) -> int | None:
        """获取当前 embedding 模型的目标输出维度。"""
        if self.embedding_fn is None:
            return None
        try:
            # 用一条短文本编码一次获取维度
            sample = self.embedding_fn(["test"])
            if hasattr(sample, 'shape'):
                return sample.shape[1] if len(sample.shape) > 1 else len(sample[0])
            return len(sample[0])
        except Exception:
            return None

    def _check_and_fix_dimension_mismatch(self, collection_name: str, expected_dim: int):
        """检查集合中已有向量的维度是否匹配，不匹配则自动删除重建。"""
        try:
            existing_names = [c.name for c in self.client.list_collections()]
        except Exception:
            return

        if collection_name not in existing_names:
            return

        try:
            col = self.client.get_collection(collection_name)
            # 🔧 空集合快速返回：count()==0 时无需维度检测，且避免后续
            # col.get() 返回空 numpy array 导致 ambiguous truth value 错误。
            try:
                cnt = col.count()
            except Exception as count_err:
                # ChromaDB 内部错误（如 WAL 损坏、backfill 失败），
                # 此时集合数据已不可靠，强制删除重建。
                print(f"[VectorStore] count() 失败: {count_err}，强制重建 {collection_name}", flush=True)
                self._force_recreate_collection(collection_name)
                return
            if cnt == 0:
                return
            result = col.get(limit=1, include=["embeddings"])
            emb_list = result.get("embeddings")
            # 🔧 安全处理：ChromaDB 返回的 embeddings 可能是 numpy array，
            # 空 numpy array 的布尔判断会抛出 "ambiguous truth value" 错误。
            # 使用显式检查替代隐式布尔转换。
            if emb_list is not None and hasattr(emb_list, '__len__') and len(emb_list) > 0:
                emb = emb_list[0]
                if emb is not None and hasattr(emb, '__len__') and len(emb) > 0:
                    if len(emb) != expected_dim:
                        print(f"[VectorStore] 维度不匹配: {collection_name} 现有 {len(emb)} 维, "
                              f"模型 {expected_dim} 维，自动重建", flush=True)
                        self._force_recreate_collection(collection_name)
        except Exception as e:
            # ChromaDB 底层异常（如 SQLite 文件损坏、WAL 损坏等），
            # 此时集合数据已不可靠，强制删除重建。
            print(f"[VectorStore] 检测 {collection_name} 维度失败: {e}，强制重建", flush=True)
            self._force_recreate_collection(collection_name)

    def _force_recreate_collection(self, collection_name: str):
        """强制删除并重建集合（处理 ChromaDB 底层损坏）。"""
        try:
            self.client.delete_collection(collection_name)
        except Exception as del_err:
            # delete_collection 也失败（如 SQLite 文件级损坏），
            # 此时只能手动清理持久化目录。
            print(f"[VectorStore] ⚠️ delete_collection 也失败: {del_err}", flush=True)
            print(f"[VectorStore] ⚠️ 请手动删除 data/chroma/ 目录后重启应用", flush=True)

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

    def search_by_embedding(
        self,
        query_embedding: list[float],
        n_results: int = 5,
        collection: str = COLLECTION_FEED_ITEMS,
    ) -> dict:
        """按原始 embedding 向量查询（不经过 ChromaDB 内置 embedding_fn）。

        用于预过滤场景：先用 bge-small 生成向量，再用此方法查 ChromaDB。
        feed_items 集合使用 cosine 距离度量，distances 中的值即为余弦距离，
        1 - distance 可直接得到余弦相似度。

        Returns:
            ChromaDB query result dict，含 ids, distances, metadatas, documents 等字段。
        """
        col = self.get_collection(collection)
        return col.query(query_embeddings=[query_embedding], n_results=n_results)

    def upsert_items(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict],
        embeddings: Optional[list[list[float]]] = None,
    ):
        """幂等写入条目向量（upsert 避免重复 ID 报错）。

        用于 update_memory_node：已存在的条目 ID 静默更新，新条目新增。
        """
        col = self.get_collection(collection)
        if embeddings is None and self.embedding_fn is not None:
            embeddings = self.embedding_fn(documents)
            if hasattr(embeddings, 'tolist'):
                embeddings = embeddings.tolist()
        col.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)

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
