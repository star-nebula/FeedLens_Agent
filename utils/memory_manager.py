"""
记忆管理模块 — 短期记忆 + 长期记忆 + 情节记忆。

架构：
  - 短期记忆：内存中滑动窗口（15轮对话/执行）
  - 长期记忆：ChromaDB domain_knowledge 集合（LLM压缩后存储）
  - 情节记忆：SQLite execution_logs 表（持久化执行记录）

工作流：
  1. add_to_short_term() → 添加到滑动窗口
  2. check_window_overflow() → 超过15轮触发压缩
  3. compress_to_long_term() → LLM压缩写入ChromaDB
  4. write_episodic() → 写入SQLite execution_logs
"""

import json
import os
from collections import deque
from datetime import datetime
from typing import Optional, List, Dict, Any

import numpy as np

from models.database import Database
from models.vector_store import VectorStore
from utils.config import load_config


# ============================================================
# 配置
# ============================================================

SHORT_TERM_WINDOW_SIZE = 15
COMPRESSION_THRESHOLD = 15


# ============================================================
# 短期记忆（滑动窗口）
# ============================================================

class ShortTermMemory:
    """短期记忆：内存中滑动窗口（默认15轮）。"""

    def __init__(self, window_size: int = SHORT_TERM_WINDOW_SIZE):
        self.window_size = window_size
        self._buffer: deque = deque(maxlen=window_size)

    def add(self, entry: Dict[str, Any]) -> None:
        """添加一条记忆到窗口。"""
        entry["timestamp"] = datetime.now().isoformat()
        entry["turn"] = len(self._buffer) + 1
        self._buffer.append(entry)
        print(f"[short_term] 添加记忆: turn={entry['turn']}, buffer_size={len(self._buffer)}", flush=True)

    def get_all(self) -> List[Dict[str, Any]]:
        """获取窗口内所有记忆。"""
        return list(self._buffer)

    def get_recent(self, n: int = 5) -> List[Dict[str, Any]]:
        """获取最近 n 条记忆。"""
        return list(self._buffer)[-n:]

    def is_overflow(self) -> bool:
        """检查是否超出窗口大小。"""
        return len(self._buffer) >= self.window_size

    def clear(self) -> None:
        """清空窗口。"""
        self._buffer.clear()
        print("[short_term] 窗口已清空", flush=True)

    def size(self) -> int:
        """返回当前窗口大小。"""
        return len(self._buffer)


# ============================================================
# 长期记忆（ChromaDB）
# ============================================================

class LongTermMemory:
    """长期记忆：ChromaDB domain_knowledge 集合。"""

    def __init__(self, persist_dir: str = "data/chroma"):
        self.persist_dir = persist_dir
        self._vector_store: Optional[VectorStore] = None

    def _get_vector_store(self) -> VectorStore:
        if self._vector_store is None:
            try:
                from utils.embedding import EmbeddingModel
                emb_model = EmbeddingModel()
                self._vector_store = VectorStore(self.persist_dir, embedding_fn=emb_model.encode)
            except Exception:
                self._vector_store = VectorStore(self.persist_dir)
        return self._vector_store

    def add_compressed(self, compressed_text: str, metadata: Optional[Dict] = None) -> str:
        """添加压缩后的记忆到 ChromaDB。"""
        vs = self._get_vector_store()
        collection = vs.client.get_or_create_collection(
            VectorStore.COLLECTION_DOMAIN_KNOWLEDGE,
            embedding_function=vs.chroma_embedding_fn,
        )

        doc_id = f"memory_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        meta = metadata or {}
        meta["created_at"] = datetime.now().isoformat()
        meta["type"] = "compressed_memory"

        try:
            collection.add(
                ids=[doc_id],
                documents=[compressed_text],
                metadatas=[meta],
            )
            print(f"[long_term] 压缩记忆已写入: id={doc_id}", flush=True)
            return doc_id
        except Exception as e:
            print(f"[long_term] 写入失败: {e}", flush=True)
            return ""

    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """检索相关记忆。"""
        vs = self._get_vector_store()
        collection = vs.client.get_or_create_collection(
            VectorStore.COLLECTION_DOMAIN_KNOWLEDGE,
            embedding_function=vs.chroma_embedding_fn,
        )

        try:
            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                where={"type": "compressed_memory"},
            )
            memories = []
            for i, doc_id in enumerate(results["ids"][0]):
                memories.append({
                    "id": doc_id,
                    "document": results["documents"][0][i] if results["documents"] else "",
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else 0.0,
                })
            return memories
        except Exception as e:
            print(f"[long_term] 检索失败: {e}", flush=True)
            return []


# ============================================================
# 情节记忆（SQLite）
# ============================================================

class EpisodicMemory:
    """情节记忆：SQLite execution_logs 表。"""

    def __init__(self, db_path: str = "data/feedlens.db"):
        self.db = Database(db_path)

    def write(
        self,
        session_id: str,
        turn: int,
        event: str,
        node_name: str,
        status: str = "completed",
        duration_ms: Optional[int] = None,
        metadata: Optional[Dict] = None,
    ) -> int:
        """写入情节记忆到 execution_logs 表。"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    """INSERT INTO execution_logs
                       (session_id, turn, event, node_name, status, duration_ms, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        turn,
                        event,
                        node_name,
                        status,
                        duration_ms,
                        json.dumps(metadata, ensure_ascii=False) if metadata else None,
                    ),
                )
                log_id = cursor.lastrowid
            print(f"[episodic] 写入日志: session={session_id}, turn={turn}, node={node_name}", flush=True)
            return log_id
        except Exception as e:
            print(f"[episodic] 写入失败: {e}", flush=True)
            return -1

    def get_session_logs(self, session_id: str) -> List[Dict[str, Any]]:
        """获取某个会话的所有日志。"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM execution_logs WHERE session_id = ? ORDER BY turn",
                    (session_id,),
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[episodic] 查询失败: {e}", flush=True)
            return []

    def get_recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近的日志记录。"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    f"SELECT * FROM execution_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[episodic] 查询失败: {e}", flush=True)
            return []


# ============================================================
# 记忆管理器（整合三层）
# ============================================================

class MemoryManager:
    """记忆管理器：整合短期、长期、情节记忆。"""

    def __init__(
        self,
        window_size: int = SHORT_TERM_WINDOW_SIZE,
        persist_dir: str = "data/chroma",
        db_path: str = "data/feedlens.db",
    ):
        self.short_term = ShortTermMemory(window_size)
        self.long_term = LongTermMemory(persist_dir)
        self.episodic = EpisodicMemory(db_path)

    def add_memory(
        self,
        session_id: str,
        event: str,
        node_name: str,
        content: Dict[str, Any],
        status: str = "completed",
        duration_ms: Optional[int] = None,
    ) -> Dict[str, Any]:
        """添加记忆到三层存储。

        1. 添加到短期记忆窗口
        2. 写入情节记忆（SQLite）
        3. 如果窗口溢出，压缩到长期记忆
        """
        turn = self.short_term.size() + 1

        # 添加到短期记忆
        short_term_entry = {
            "session_id": session_id,
            "turn": turn,
            "event": event,
            "node_name": node_name,
            "content": content,
            "status": status,
        }
        self.short_term.add(short_term_entry)

        # 写入情节记忆
        log_id = self.episodic.write(
            session_id=session_id,
            turn=turn,
            event=event,
            node_name=node_name,
            status=status,
            duration_ms=duration_ms,
            metadata=content,
        )

        result = {
            "turn": turn,
            "log_id": log_id,
            "short_term_size": self.short_term.size(),
        }

        # 检查是否需要压缩
        if self.short_term.is_overflow():
            compressed = self.compress_window()
            result["compressed"] = compressed

        return result

    def compress_window(self) -> Dict[str, Any]:
        """压缩短期记忆窗口到长期记忆。

        使用 LLM 提取关键信息，写入 ChromaDB。
        """
        entries = self.short_term.get_all()
        if not entries:
            return {"success": False, "reason": "窗口为空"}

        print(f"[memory_manager] 开始压缩 {len(entries)} 条短期记忆", flush=True)

        # 构建 LLM 压缩 prompt
        entries_text = "\n".join([
            f"[Turn {e['turn']}] {e['node_name']}: {json.dumps(e.get('content', {}), ensure_ascii=False)[:200]}"
            for e in entries
        ])

        prompt = f"""请将以下执行记录压缩为一段简洁的摘要（200字以内），保留关键信息：

{entries_text}

摘要：
"""

        # 调用 LLM 压缩
        try:
            from utils.llm_provider import DeepSeekProvider
            config = load_config()
            llm_cfg = config.get("llm", {})
            deepseek_cfg = llm_cfg.get("deepseek", {})
            api_key = deepseek_cfg.get("api_key", "")
            model = deepseek_cfg.get("model", "deepseek-chat")
            llm = DeepSeekProvider(api_key=api_key, model=model)
            response = llm.chat([{"role": "user", "content": prompt}])
            compressed_text = response.get("content", "") if isinstance(response, dict) else str(response)
        except Exception as e:
            print(f"[memory_manager] LLM 压缩失败: {e}", flush=True)
            # 降级：简单拼接
            compressed_text = f"压缩失败，原始记录数: {len(entries)}"

        # 写入长期记忆
        doc_id = self.long_term.add_compressed(
            compressed_text,
            metadata={
                "source": "short_term_compression",
                "entry_count": len(entries),
                "turn_range": f"{entries[0]['turn']}-{entries[-1]['turn']}",
            },
        )

        # 清空短期记忆窗口
        self.short_term.clear()

        print(f"[memory_manager] 压缩完成: doc_id={doc_id}", flush=True)

        return {
            "success": True,
            "doc_id": doc_id,
            "entry_count": len(entries),
            "compressed_text": compressed_text[:100] + "..." if len(compressed_text) > 100 else compressed_text,
        }

    def get_context(self, query: str, n_recent: int = 5, n_long_term: int = 3) -> Dict[str, Any]:
        """获取上下文：短期记忆 + 长期记忆检索。"""
        recent = self.short_term.get_recent(n_recent)
        long_term_results = self.long_term.search(query, n_results=n_long_term)

        return {
            "short_term": recent,
            "long_term": long_term_results,
            "short_term_size": self.short_term.size(),
        }


# ============================================================
# 全局单例
# ============================================================

_memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    """获取记忆管理器单例。"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager


# ============================================================
# 便捷函数
# ============================================================

def add_memory(
    session_id: str,
    event: str,
    node_name: str,
    content: Dict[str, Any],
    **kwargs,
) -> Dict[str, Any]:
    """添加记忆（便捷函数）。"""
    return get_memory_manager().add_memory(
        session_id=session_id,
        event=event,
        node_name=node_name,
        content=content,
        **kwargs,
    )


def get_context(query: str, **kwargs) -> Dict[str, Any]:
    """获取上下文（便捷函数）。"""
    return get_memory_manager().get_context(query, **kwargs)
