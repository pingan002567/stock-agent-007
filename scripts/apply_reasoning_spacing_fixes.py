"""把手工校正后的历史推理文本写回数据库。

自动切分在真实语料上切不动（词表太小、模型用词随意），所以这 13 条是**人工校正**的：
只补空格，不改词、不动工具名/代码/引号内原文。校正表见
`scripts/data/reasoning_spacing_fixes.json`（message_id → 修复后文本）。

安全措施：
- 写前把**原文备份**到 `data/reasoning_backup_<时间戳>.json`
- 只处理「当前文本仍然粘连（无空格）且长度 > 30」的行；已经被修过的跳过
- 只写 payload.text，其它字段原样保留

用法：
    python scripts/apply_reasoning_spacing_fixes.py            # 演练
    python scripts/apply_reasoning_spacing_fixes.py --apply
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

FIXES = Path("scripts/data/reasoning_spacing_fixes.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/workbench.sqlite3")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = Path(args.db)
    fixes: dict[str, str] = json.loads(FIXES.read_text())
    conn = sqlite3.connect(db)

    todo: list[tuple[str, str, str]] = []
    skipped = 0
    for message_id, new_text in fixes.items():
        row = conn.execute(
            "SELECT payload FROM copilot_message WHERE message_id=? AND kind='reasoning'",
            (message_id,),
        ).fetchone()
        if not row:
            skipped += 1
            continue
        data = json.loads(row[0]) or {}
        old = str(data.get("text") or "")
        if not old:
            skipped += 1
            continue
        if " " in old or len(old) <= 30:
            skipped += 1  # 已经修过或不是粘连文本
            continue
        todo.append((message_id, old, new_text))

    print(f"校正表 {len(fixes)} 条；待写 {len(todo)} 条；跳过 {skipped} 条")
    for message_id, old, new in todo[:3]:
        print(f"--- {message_id}")
        print(f"  原：{old[:100]}")
        print(f"  新：{new[:100]}")

    if not args.apply:
        print("\n[dry-run] 未写入。加 --apply 生效。")
        return

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = db.parent / f"reasoning_backup_{stamp}.json"
    backup.write_text(json.dumps({mid: old for mid, old, _ in todo}, ensure_ascii=False, indent=1))
    print(f"\n原文备份：{backup}")

    for message_id, _old, new in todo:
        row = conn.execute("SELECT payload FROM copilot_message WHERE message_id=?", (message_id,)).fetchone()
        data = json.loads(row[0]) or {}
        data["text"] = new
        conn.execute(
            "UPDATE copilot_message SET payload=? WHERE message_id=?",
            (json.dumps(data, ensure_ascii=False), message_id),
        )
    conn.commit()
    print(f"已写回 {len(todo)} 条")


if __name__ == "__main__":
    main()
