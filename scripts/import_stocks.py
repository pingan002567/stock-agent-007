from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.bootstrap import create_services
from backend.schemas import StockMaster


def main() -> int:
    parser = argparse.ArgumentParser(description="Import A-share stock codes into stock_master from AKShare")
    parser.add_argument("--db", default="data/workbench.sqlite3", help="SQLite DB path")
    parser.add_argument("--market", default="CN", choices=["CN", "HK", "US"], help="Market to import")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    parser.add_argument("--limit", type=int, default=0, help="Max stocks to import (0=all)")
    args = parser.parse_args()

    if args.market != "CN":
        print(f"Sorry, only CN market import is supported (HK/US mock only).")
        return 1

    # Fetch all A-share codes from AKShare
    try:
        import urllib.request
        urllib.request.getproxies = lambda: {}
        import akshare as ak
        frame = ak.stock_info_a_code_name()
    except Exception as exc:
        print(f"Failed to fetch stock list from AKShare: {exc}")
        return 1

    total = len(frame)
    print(f"AKShare returned {total} A-share stocks.")

    if args.limit:
        frame = frame.head(args.limit)
    processing = len(frame)

    services = create_services(db_path=args.db)
    repo = services.repo

    # Check which symbols already exist
    existing_rows = repo.conn.execute("SELECT symbol FROM stock_master WHERE market='CN'").fetchall()
    existing = {row["symbol"] for row in existing_rows}

    items_to_insert: list[StockMaster] = []
    for _, row in frame.iterrows():
        code = str(row["code"]).strip()
        name = str(row["name"]).strip().replace("\u3000", "")
        if code in existing:
            continue
        items_to_insert.append(
            StockMaster(symbol=code, name=name, market="CN")
        )

    new_count = len(items_to_insert)
    skipped = processing - new_count

    print(f"Processing {processing} stocks ({skipped} already in DB, {new_count} new)")

    if args.dry_run:
        if items_to_insert:
            print(f"Would import {new_count} stocks (first 5):")
            for s in items_to_insert[:5]:
                print(f"  {s.symbol} {s.name}")
            if new_count > 5:
                print(f"  ... and {new_count - 5} more")
        return 0

    if not items_to_insert:
        print("No new stocks to import.")
        return 0

    start = time.perf_counter()
    stored = repo.batch_upsert_stock_master(items_to_insert)
    elapsed = time.perf_counter() - start

    print(f"Imported {stored} stocks into stock_master in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
