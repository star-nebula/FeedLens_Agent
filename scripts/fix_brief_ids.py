"""
修复历史简报数据：将 content_json 中 LLM 生成的条目 ID 替换为 dedup_id，
使得前端反馈按钮能正确匹配。

匹配策略：briefing_items 按 rank 排序后，与 content_json 中 categories[].items[]
按顺序一一对应（两者都按 rank 排序写入）。
"""
import sqlite3, json, sys

DB_PATH = 'data/feedlens.db'

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

# 1. 找出所有有 briefing_items 记录的简报
brief_ids = conn.execute('''
    SELECT DISTINCT briefing_id FROM briefing_items ORDER BY briefing_id
''').fetchall()

fixed_count = 0

for (brief_id,) in brief_ids:
    # 读取 briefing_items（按 rank 排序）
    items_rows = conn.execute('''
        SELECT item_id, rank FROM briefing_items
        WHERE briefing_id = ?
        ORDER BY rank
    ''', (brief_id,)).fetchall()
    
    if not items_rows:
        continue
    
    # 按 rank 顺序取出 dedup_id 列表
    dedup_ids = [row["item_id"] for row in items_rows]
    
    # 读取 content_json
    brief = conn.execute('SELECT content_json FROM briefs WHERE id = ?', (brief_id,)).fetchone()
    if not brief:
        continue
    
    try:
        data = json.loads(brief["content_json"])
    except (json.JSONDecodeError, TypeError):
        continue
    
    categories = data.get("categories", [])
    if not categories:
        continue
    
    # 展开所有条目（按 categories 顺序，每个 category 内 items 按顺序）
    all_entries = []
    for cat in categories:
        for item in cat.get("items", []):
            all_entries.append(item)
    
    # 检查：如果 entry.id 已经是整数类型，说明已修复过，跳过
    if all_entries and isinstance(all_entries[0].get("id"), int):
        continue
    
    # 按顺序替换 ID
    replaced = 0
    for i, entry in enumerate(all_entries):
        if i < len(dedup_ids):
            old_id = entry.get("id", "")
            entry["id"] = dedup_ids[i]
            if str(old_id) != str(dedup_ids[i]):
                replaced += 1
    
    if replaced > 0:
        new_json = json.dumps(data, ensure_ascii=False)
        conn.execute('UPDATE briefs SET content_json = ? WHERE id = ?', (new_json, brief_id))
        fixed_count += 1
        print(f'  brief_id={brief_id}: 替换了 {replaced}/{len(all_entries)} 个条目 ID')

conn.commit()
conn.close()

print(f'\n修复完成，共处理 {fixed_count} 条简报')
