"""
记忆管理模块 — 情节记忆 + 长期记忆。

FeedLens 场景适配：
  - FeedLens 是「每天一次独立管线执行」的定时系统，不存在同进程多轮积累。
  - 因此删除 ShortTermMemory（滑动窗口），改为两层架构：
    1. 情节记忆：SQLite execution_logs 表（持久化执行记录，planner 检索近N天记录）
    2. 长期记忆：ChromaDB domain_knowledge 集合（每次执行后 LLM 摘要写入，语义检索）

工作流：
  1. write_episodic() → 写入 SQLite execution_logs
  2. summarize_to_long_term() → LLM 对本次执行做摘要，写入 ChromaDB
  3. get_context() → 检索 SQLite 近N天记录 + ChromaDB 语义相似经验
"""

import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any

from models.database import Database
from models.vector_store import VectorStore
from utils.config import load_config


# ============================================================
# 配置
# ============================================================

# 情节记忆检索：默认回溯最近 N 天的执行记录
EPISODIC_LOOKBACK_DAYS = 7


# ============================================================
# 情节记忆（SQLite）
# ============================================================

class EpisodicMemory:
    """情节记忆：SQLite execution_logs 表。

    FeedLens 场景下，每次执行是一条独立的执行记录。
    不再有「轮次」概念，每次执行对应一条 execution_log。
    """

    def __init__(self, db_path: str = "data/feedlens.db"):
        self.db = Database(db_path)

    def write(
        self,
        session_id: str,
        event: str,
        node_name: str,
        status: str = "completed",
        duration_ms: Optional[int] = None,
        metadata: Optional[Dict] = None,
    ) -> int:
        """写入一条情节记忆到 execution_logs 表。

        turn 字段固定为 1（FeedLens 每次执行只有一轮）。
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    """INSERT INTO execution_logs
                       (session_id, turn, event, node_name, status, duration_ms, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        session_id,
                        1,  # FeedLens 每次执行就是一轮
                        event,
                        node_name,
                        status,
                        duration_ms,
                        json.dumps(metadata, ensure_ascii=False) if metadata else None,
                    ),
                )
                log_id = cursor.lastrowid
            print(f"[episodic] 写入日志: session={session_id}, node={node_name}", flush=True)
            return log_id
        except Exception as e:
            print(f"[episodic] 写入失败: {e}", flush=True)
            return -1

    def get_recent_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """获取最近的日志记录。"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM execution_logs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                )
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
        except Exception as e:
            print(f"[episodic] 查询失败: {e}", flush=True)
            return []

    def get_recent_days_logs(self, days: int = EPISODIC_LOOKBACK_DAYS, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近 N 天的执行日志。

        用于 planner 回顾近期执行效果：采集量、排序质量、简报质量等。
        """
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    f"""SELECT id, session_id, event, node_name, status,
                               duration_ms, metadata, created_at
                        FROM execution_logs
                        WHERE created_at >= datetime('now', '-{days} days')
                        ORDER BY created_at DESC
                        LIMIT ?""",
                    (limit,),
                )
                rows = cursor.fetchall()
                logs = []
                for row in rows:
                    d = dict(row)
                    # 解析 metadata JSON
                    if d.get("metadata"):
                        try:
                            d["metadata"] = json.loads(d["metadata"])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    logs.append(d)
                print(f"[episodic] 近{days}天检索: {len(logs)}条", flush=True)
                return logs
        except Exception as e:
            print(f"[episodic] 近{days}天检索失败: {e}", flush=True)
            return []


# ============================================================
# 长期记忆（ChromaDB）
# ============================================================

class LongTermMemory:
    """长期记忆：ChromaDB domain_knowledge 集合。

    FeedLens 场景下，每次执行后直接对本次决策+结果做 LLM 摘要，
    写入 ChromaDB，供后续 planner 语义检索。
    """

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

    def summarize_and_store(
        self,
        session_id: str,
        planner_decision: Dict[str, Any],
        execution_result: Dict[str, Any],
        trigger_type: str = "daily_briefing",
    ) -> str:
        """对本次执行做 LLM 摘要，写入 ChromaDB。

        直接对单次执行做摘要，不再依赖窗口积累。
        """
        # 构建摘要 prompt
        summary_input = {
            "trigger": trigger_type,
            "decision": planner_decision,
            "result": execution_result,
        }
        input_text = json.dumps(summary_input, ensure_ascii=False)

        prompt = f"""请将以下 FeedLens Agent 执行记录压缩为一段简洁的摘要（200字以内），
保留关键信息：触发了什么、做了什么决策、结果如何（采集量、排序质量、简报质量）。

执行记录：
{input_text}

摘要："""

        compressed_text = ""
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
            print(f"[long_term] LLM 摘要: {compressed_text[:80]}...", flush=True)
        except Exception as e:
            print(f"[long_term] LLM 摘要失败，降级为结构化文本: {e}", flush=True)
            # 降级：结构化拼接
            parts = []
            if execution_result.get("collected_count"):
                parts.append(f"采集{execution_result['collected_count']}条")
            if execution_result.get("ranked_count"):
                parts.append(f"排序后{execution_result['ranked_count']}条")
            if execution_result.get("brief_quality"):
                parts.append(f"简报质量{execution_result['brief_quality']:.2f}")
            compressed_text = "；".join(parts) if parts else input_text[:200]

        # 写入 ChromaDB
        return self._store_compressed(session_id, compressed_text, execution_result)

    def _store_compressed(
        self,
        session_id: str,
        compressed_text: str,
        execution_result: Dict[str, Any],
    ) -> str:
        """将摘要写入 ChromaDB。"""
        vs = self._get_vector_store()
        collection = vs.client.get_or_create_collection(
            VectorStore.COLLECTION_DOMAIN_KNOWLEDGE,
            embedding_function=vs.chroma_embedding_fn,
        )

        doc_id = f"memory_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{session_id[:8]}"
        meta = {
            "created_at": datetime.now().isoformat(),
            "type": "execution_summary",
            "session_id": session_id,
            "trigger_type": execution_result.get("trigger_type", ""),
            "collected_count": execution_result.get("collected_count", 0),
            "brief_quality": execution_result.get("brief_quality", 0.0),
        }

        try:
            collection.add(
                ids=[doc_id],
                documents=[compressed_text],
                metadatas=[meta],
            )
            print(f"[long_term] 执行摘要已写入: id={doc_id}", flush=True)
            return doc_id
        except Exception as e:
            print(f"[long_term] 写入失败: {e}", flush=True)
            return ""

    def search(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """检索相关历史执行经验。"""
        vs = self._get_vector_store()
        collection = vs.client.get_or_create_collection(
            VectorStore.COLLECTION_DOMAIN_KNOWLEDGE,
            embedding_function=vs.chroma_embedding_fn,
        )

        try:
            results = collection.query(
                query_texts=[query],
                n_results=n_results,
                where={"type": "execution_summary"},
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
# 记忆管理器（整合两层）
# ============================================================

class MemoryManager:
    """记忆管理器：整合情节记忆 + 长期记忆。

    FeedLens 场景适配：
      - 不再维护短期记忆滑动窗口
      - 每次执行后：写入 SQLite + LLM 摘要写入 ChromaDB
      - planner 检索：SQLite 近N天记录 + ChromaDB 语义检索
    """

    def __init__(
        self,
        persist_dir: str = "data/chroma",
        db_path: str = "data/feedlens.db",
    ):
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
        execution_result: Optional[Dict[str, Any]] = None,
        planner_decision: Optional[Dict[str, Any]] = None,
        trigger_type: str = "daily_briefing",
    ) -> Dict[str, Any]:
        """添加记忆到两层存储。

        1. 写入情节记忆（SQLite execution_logs）
        2. 对本次执行做 LLM 摘要，写入长期记忆（ChromaDB）

        Args:
            session_id: 会话ID
            event: 事件类型（如 "planner_decision"）
            node_name: 节点名称
            content: 决策/执行内容
            status: 状态
            duration_ms: 耗时
            execution_result: 执行结果摘要（含 collected_count, ranked_count, brief_quality 等）
            planner_decision: planner 的编排决策
            trigger_type: 触发类型
        """
        # 写入情节记忆
        log_id = self.episodic.write(
            session_id=session_id,
            event=event,
            node_name=node_name,
            status=status,
            duration_ms=duration_ms,
            metadata=content,
        )

        # LLM 摘要写入长期记忆
        doc_id = ""
        result_info = execution_result or {}
        decision_info = planner_decision or content.get("decision", [])
        try:
            doc_id = self.long_term.summarize_and_store(
                session_id=session_id,
                planner_decision=decision_info if isinstance(decision_info, dict) else {"plan": decision_info},
                execution_result=result_info,
                trigger_type=trigger_type,
            )
        except Exception as e:
            print(f"[memory_manager] 长期记忆摘要失败: {e}", flush=True)

        return {
            "log_id": log_id,
            "chroma_doc_id": doc_id,
        }

    def get_context(
        self,
        query: str,
        n_episodic: int = 10,
        n_long_term: int = 3,
        lookback_days: int = EPISODIC_LOOKBACK_DAYS,
    ) -> Dict[str, Any]:
        """获取上下文：情节记忆（近N天）+ 长期记忆（语义检索）。

        Args:
            query: 语义检索查询文本
            n_episodic: 从 SQLite 检索最近几条记录
            n_long_term: 从 ChromaDB 检索几条语义相似经验
            lookback_days: 情节记忆回溯天数

        Returns:
            {
                "episodic": [...],    # 近N天执行记录
                "long_term": [...],   # 语义相似历史经验
                "episodic_count": int,
                "long_term_count": int,
            }
        """
        # 情节记忆：近N天执行记录
        episodic_logs = self.episodic.get_recent_days_logs(
            days=lookback_days,
            limit=n_episodic,
        )

        # 长期记忆：语义检索
        long_term_results = self.long_term.search(query, n_results=n_long_term)

        return {
            "episodic": episodic_logs,
            "long_term": long_term_results,
            "episodic_count": len(episodic_logs),
            "long_term_count": len(long_term_results),
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


def summarize_execution(
    session_id: str,
    planner_decision: Dict[str, Any],
    execution_result: Dict[str, Any],
    trigger_type: str = "daily_briefing",
) -> str:
    """对本次执行做 LLM 摘要并写入 ChromaDB（便捷函数）。"""
    return get_memory_manager().long_term.summarize_and_store(
        session_id=session_id,
        planner_decision=planner_decision,
        execution_result=execution_result,
        trigger_type=trigger_type,
    )
