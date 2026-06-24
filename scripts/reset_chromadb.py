"""彻底清理 ChromaDB 数据 - 包括 HNSW 索引文件目录"""
import sqlite3, os, shutil

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

chroma_dir = "data/chroma"

# 1. 删除 HNSW 索引目录
for item in os.listdir(chroma_dir):
    item_path = os.path.join(chroma_dir, item)
    if os.path.isdir(item_path) and item != "__pycache__":
        shutil.rmtree(item_path)
        print(f"Deleted: {item_path}")

# 2. 清理 SQLite 中的 collections/segments/embeddings 等表
conn = sqlite3.connect(os.path.join(chroma_dir, "chroma.sqlite3"))
tables_to_clear = [
    "collections", "segments", "embeddings", "embedding_metadata",
    "embedding_fulltext_search", "embedding_fulltext_search_data",
    "embedding_fulltext_search_idx", "embedding_fulltext_search_content",
    "embedding_fulltext_search_docsize", "embedding_fulltext_search_config",
    "embedding_metadata_array", "embeddings_queue", "embeddings_queue_config",
    "max_seq_id"
]
for table in tables_to_clear:
    try:
        conn.execute(f"DELETE FROM {table}")
        print(f"Cleared: {table}")
    except Exception as e:
        print(f"Skip {table}: {e}")

conn.commit()
conn.close()
print("\nChromaDB 完全清空，下次运行时将用 bge-small-zh-v1.5 (384维) 重新初始化。")
