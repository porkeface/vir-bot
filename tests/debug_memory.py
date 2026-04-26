"""调试语义记忆问题。"""
import json
import sys
sys.path.insert(0, "D:/code Project/vir-bot")

from vir_bot.core.memory.semantic_store import SemanticMemoryStore

# 直接读取语义记忆文件
store = SemanticMemoryStore(persist_path="data/memory/semantic_memory.json")

print(f"Total records: {len(store._records)}")
print(f"\n所有记录:")
for rid, r in store._records.items():
    print(f"  ID: {r.memory_id[:8]}...")
    print(f"    user_id: {r.user_id!r}")
    print(f"    predicate: {r.predicate}")
    print(f"    object: {r.object}")
    print(f"    confidence: {r.confidence}")
    print(f"    is_active: {r.is_active}")
    print()

print(f"\n按 user_id 分组:")
from collections import defaultdict
by_user = defaultdict(list)
for r in store._records.values():
    by_user[r.user_id].append(r)

for uid, records in by_user.items():
    print(f"  user_id={uid!r}: {len(records)} records")
    for r in records:
        print(f"    - {r.predicate}: {r.object} (conf={r.confidence:.2f})")
