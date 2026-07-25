"""참조 목록을 UTF-8로 reference_list.txt에 저장"""
from pathlib import Path
from storage import init_collections, _reference_col

init_collections()
col = _reference_col()
result = col.get(include=["metadatas"])
metas = result.get("metadatas", [])
ids = result.get("ids", [])
lines = []
if not metas:
    lines.append("저장된 참조 기사 없음")
else:
    lines.append(f"=== 참조 기사 {len(metas)}개 ===")
    for doc_id, meta in zip(ids, metas):
        title = (meta.get("title") or "")[:80]
        source = meta.get("source") or ""
        url = meta.get("url") or ""
        lines.append(f"  [{doc_id}] {title}  ({source})")
        if url:
            lines.append(f"      {url}")
Path("reference_list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
print("OK reference_list.txt")