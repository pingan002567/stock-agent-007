"""修复历史 reasoning 文本里丢掉的空格（一次性清洗）。

## 为什么会有这种数据
推理分片的解析层曾经对**每个流式增量**做 `.strip()`，把 `' need'` 变成 `'need'`，
拼起来就是 `Letmestartbygatheringrequireddata`。代码已修，但已落库的历史仍是粘连的。

## 修复策略（分层，保守优先）
1. **保护不可拆的东西**：snake_case 标识符（`get_crypto_derivatives`）、
   大写缩写（`BTC`/`ETH`/`TRX`）、数字、引号内文本、URL —— 这些整段保留
2. **标点后断句**：`.` `,` `:` `;` `!` `?` `—` 后面紧跟字母时插空格
3. **驼峰/大小写边界**：`[a-z][A-Z]` 之间插空格
4. **剩余长串用词表做最长匹配切分**：词表 = 库里**没粘连**的那些 reasoning 文本
   里出现过的词 + 一份常见词表（语料来自同一模型，切分结果更贴近原意）
5. 切不动（有词不在词表里）的长串**保持原样**，并在报告里列出来 ——
   宁可留着粘连，也不要切出一堆错误的碎片

用法：
    .venv/bin/python scripts/repair_reasoning_spacing.py --dry-run
    .venv/bin/python scripts/repair_reasoning_spacing.py --apply
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
import re
import sqlite3
from pathlib import Path

try:  # 可选的英文分词器：装了就比词表最长匹配准得多
    import wordninja
except ImportError:  # pragma: no cover - 没装时退回词表切分
    wordninja = None  # type: ignore[assignment]

#: 常见英文词（模型思考里高频），补库里语料没覆盖到的
COMMON_WORDS = """
a about after all also an and any are as at be because been before being between both but by
can could did do does doing done for from get gets got had has have having he her here him his
how i if in into is it its just let lets like look make makes may me might more most much must
my need needs no nor not now of off on once only or other our out over own same see should since
so some still such take than that the their them then there these they this those through to too
under until up use used uses using very was way we were what when where which while who why will
with would yes yet you your
data need want check call tool tools list lists result results value values time times first
second next last also then because since while market markets price prices stock stocks crypto
funding rate rates position positions portfolio watchlist holdings holding report reports brief
briefing duty session history context sentiment structure industry news search fetch get set
add remove update create delete run start stop show tell write read open close keep find found
give given says said say mean means part parts step steps note notes thing things point points
risk risks limit limits cap caps weight weights rule rules policy policies plan plans
available unavailable degraded stale missing empty full single double multiple parallel
before after above below inside outside around across against without within between during
per just same both each every more less than then there here where which while who whom whose
able unable need needs needed needed trying try tries tried want wants wanted check checks checked
listed listing cover covers covered covering include includes included including note noted
tracked track tracking record records recorded records remove removed added adding update updated
calculate calculated compare compared review reviewed review summarize summarized summary
spread spreads close closed opening opened high low higher lower large small larger smaller
normal normalized normalized percent percent percentile crowded crowded funding funding
""".split()

#: 不可拆的片段：引号/反引号内容、URL、snake_case 标识符、全大写缩写、数字、
#: 斜杠分隔的代码（BTC/ETH）。**一次扫描**，避免后一条规则把前一条的占位符再包一层。
def _known_identifiers() -> list[str]:
    """工具名等「不能拆」的标识符：用后端工具注册表当白名单，按长度倒序。"""
    names: set[str] = set()
    try:
        from backend.config.tool_labels import TOOL_LABELS

        names.update(TOOL_LABELS)
    except Exception:  # noqa: BLE001 - 独立运行时后端包不可导入也没关系
        pass
    names.update({"write_todos", "web_search", "web_fetch", "read_file", "write_file", "bash", "task"})
    # 厂商/数据源名：拆开很难看（tushare → tush are）
    names.update({
        "tushare", "eastmoney", "tonghuashun", "akshare", "yfinance", "longbridge",
        "pytdx", "baostock", "tickflow", "gate_spot", "coingecko", "defillama", "okx",
    })
    # 只用「有辨识度」的：短单词（task/bash/grep）出现在粘连串里会把词切成碎片
    return sorted((n for n in names if "_" in n or len(n) >= 8), key=len, reverse=True)


IDENTIFIERS = _known_identifiers()

PROTECT_RE = re.compile(
    "|".join(
        [
            r"`[^`]*`",
            r'"[^"]*"',
            r"https?://\S+",
            # 已知工具/标识符（任意位置，大小写敏感）
            *(re.escape(name) for name in IDENTIFIERS),
            r"\b[A-Z]{2,}(?:/[A-Z]{2,})+\b",
            r"\b[A-Z]{2,}\b",
            r"\d+(?:[.,]\d+)?",
        ]
    )
)

PUNCT_AFTER = re.compile(r"([.,;:!?—])(?=[A-Za-z\x01])")
CAMEL = re.compile(r"([a-z])([A-Z])")
#: 大写缩写紧贴小写（`BTCfundingrate`），缩写后补空格
ACRONYM_THEN_LOWER = re.compile(r"(?<=[A-Z]{2})(?=[a-z])")
#: 小写紧贴大写缩写（`rateBTC`）
LOWER_THEN_ACRONYM = re.compile(r"(?<=[a-z])(?=[A-Z]{2,})")
#: 缩写后接一个首字母大写的词（`BTCFunding`）
ACRONYM_THEN_WORD = re.compile(r"(?<=[A-Z]{2})(?=[A-Z][a-z])")


def _vocab_from_db(conn: sqlite3.Connection) -> set[str]:
    """用库里「没粘连」的历史推理文本作为语料，切分更贴近模型用词。"""
    vocab: set[str] = set()
    for (payload,) in conn.execute("SELECT payload FROM copilot_message WHERE kind='reasoning'"):
        try:
            text = str((json.loads(payload) or {}).get("text") or "")
        except (TypeError, ValueError):
            continue
        if " " not in text:
            continue
        for word in re.findall(r"[A-Za-z]{2,}", text):
            vocab.add(word.lower())
    return vocab


def _segment(run: str, vocab: set[str], max_len: int, *, inflection: bool = False) -> list[str] | None:
    """最长匹配切分；任一段落无法覆盖就返回 None（保持原样）。

    先做**精确匹配**，失败再允许词形变化：否则 `portfolios`（portfolio+s）
    会抢先吃掉 `portfolio`，剩下 `napshot` 切不动，整段被判失败。
    """
    out: list[str] = []
    i = 0
    n = len(run)
    while i < n:
        for size in range(min(max_len, n - i), 0, -1):
            piece = run[i : i + size]
            if _known(piece, vocab, inflection=inflection):
                out.append(piece)
                i += size
                break
        else:
            return None
    return out


def _known(piece: str, vocab: set[str], *, inflection: bool = False) -> bool:
    """词表命中判断；inflection=True 时允许常见词形变化（复数/过去式/ing）。"""
    word = piece.lower()
    if word in vocab:
        return True
    if not inflection:
        return False
    for suffix in ("s", "es", "ed", "ing", "d"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            if word[: -len(suffix)] in vocab:
                return True
    return False


def repair_text(text: str, vocab: set[str], max_len: int = 20) -> tuple[str, bool]:
    """返回 (修复后文本, 是否完全修复)。"""
    # 不能因为「有空格」就跳过：历史里大量是**部分粘连**
    # （`Theuserwantsapre-market...Todayis 2026-10-25`），整体有空格但局部还是粘的。
    if not re.search(r"[A-Za-z]", text):
        return text, True

    # 1) 一次扫描完成占位（占位符用 \x01 包裹，后续规则不会把它当单词/数字）
    placeholders: list[str] = []

    def stash(match: re.Match[str]) -> str:
        placeholders.append(match.group(0))
        return f"\x01{len(placeholders) - 1}\x02"

    work = PROTECT_RE.sub(stash, text)

    # 2) 标点断句 + 3) 驼峰/缩写边界
    work = PUNCT_AFTER.sub(r"\1 ", work)
    work = CAMEL.sub(r"\1 \2", work)
    work = ACRONYM_THEN_LOWER.sub(" ", work)
    work = LOWER_THEN_ACRONYM.sub(" ", work)
    work = ACRONYM_THEN_WORD.sub(" ", work)

    # 4) 剩余长串切分：wordninja 优先（按词频切，`Theuserwantsa` → `The user wants a`），
    #    没装时退回词表最长匹配
    ok = True

    def split_run(match: re.Match[str]) -> str:
        nonlocal ok
        run = match.group(0)
        if len(run) <= 2:
            return run
        if wordninja is not None:
            pieces = wordninja.split(run)
            if len(pieces) >= 1:
                return " ".join(pieces)
        pieces = _segment(run, vocab, max_len) or _segment(run, vocab, max_len, inflection=True)
        if pieces is None:
            ok = False
            return run
        return " ".join(pieces)

    # 只有「连续字母 >= 7」才是粘连候选：正常单词（derivatives/opportunity）
    # 不该被拆，短串也不值得拆错
    # 剩下的下划线片段（未命中白名单的）当作分隔符：宁可丢下划线，也要可读
    work = re.sub(r"[A-Za-z0-9]*_[A-Za-z0-9_]*", lambda m: m.group(0).replace("_", " "), work)
    work = re.sub(r"[A-Za-z]{7,}", split_run, work)

    # 5) 还原占位
    def restore(match: re.Match[str]) -> str:
        return placeholders[int(match.group(1))]

    work = re.sub(r"\x01(\d+)\x02", restore, work)
    work = re.sub(r"\s{2,}", " ", work).strip()
    return work, ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/workbench.sqlite3")
    ap.add_argument("--apply", action="store_true", help="写回数据库（默认只演练）")
    ap.add_argument("--mark-unfixable", action="store_true",
                    help="把切不动的历史行替换成说明文字（原文备份到 data/）")
    ap.add_argument("--show", type=int, default=5, help="打印多少条前后对比")
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        raise SystemExit(f"找不到数据库：{db}")

    conn = sqlite3.connect(db)
    vocab = set(COMMON_WORDS) | _vocab_from_db(conn)

    rows = conn.execute(
        "SELECT message_id, payload FROM copilot_message WHERE kind='reasoning' ORDER BY rowid"
    ).fetchall()

    # 挑出粘连行（有空格 / 中文为主的都不动）
    targets: list[tuple[str, str]] = []
    skipped = 0
    for message_id, payload in rows:
        try:
            text = str((json.loads(payload) or {}).get("text") or "")
        except (TypeError, ValueError):
            skipped += 1
            continue
        # 粘连判据：存在 >=12 个连续字母的片段（正常英文单词很少这么长）
        if not text or not re.search(r"[A-Za-z]{7,}", PROTECT_RE.sub(" ", text)):
            skipped += 1
            continue
        targets.append((message_id, text))

    # 多轮：修成功的那批会贡献新词，下一轮用它重试失败项
    repair: dict[str, str] = {}
    remaining = list(targets)
    for round_no in range(4):
        if not remaining:
            break
        still: list[tuple[str, str]] = []
        for message_id, text in remaining:
            new_text, ok = repair_text(text, vocab)
            if ok and new_text != text:
                repair[message_id] = new_text
                for word in re.findall(r"[A-Za-z]{2,}", new_text):
                    vocab.add(word.lower())
            else:
                still.append((message_id, text))
        progressed = len(still) < len(remaining)
        remaining = still
        if not progressed:
            break

    print(f"推理共 {len(rows)} 条；粘连待修 {len(targets)} 条；"
          f"可修 {len(repair)} 条；切不动 {len(remaining)} 条；跳过 {skipped} 条")
    for message_id, text in targets[: args.show]:
        print(f"--- {message_id}")
        print(f"  原：{text[:110]}")
        print(f"  新：{repair.get(message_id, '（切不动，未改）')[:110]}")

    if not args.apply:
        print("\n[dry-run] 未写入。确认效果后加 --apply（可再带 --mark-unfixable）。")
        return

    backups = {mid: text for mid, text in targets}
    if backups:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = db.parent / f"reasoning_backup_{stamp}.json"
        backup_path.write_text(json.dumps(backups, ensure_ascii=False, indent=1))
        print(f"\n原文已备份：{backup_path}")

    changed = 0
    for message_id, new_text in repair.items():
        _write(conn, message_id, new_text)
        changed += 1

    marked = 0
    if args.mark_unfixable:
        for message_id, _text in remaining:
            _write(conn, message_id, "（这段思考产生于旧版本，空格丢失且无法可靠恢复，已省略）")
            marked += 1

    conn.commit()
    print(f"已写回：修复 {changed} 条" + (f"，标记不可修 {marked} 条" if marked else ""))


def _write(conn: sqlite3.Connection, message_id: str, text: str) -> None:
    row = conn.execute(
        "SELECT payload FROM copilot_message WHERE message_id=?", (message_id,)
    ).fetchone()
    if not row:
        return
    data = json.loads(row[0]) or {}
    data["text"] = text
    conn.execute(
        "UPDATE copilot_message SET payload=? WHERE message_id=?",
        (json.dumps(data, ensure_ascii=False), message_id),
    )


if __name__ == "__main__":
    main()
