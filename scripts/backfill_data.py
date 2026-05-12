from __future__ import annotations

import argparse
from multiprocessing import Pool
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.bootstrap import create_services
from backend.schemas import StockDaily


def _worker(args: tuple[list[str], str, int]) -> dict[str, Any]:
    """Worker process: backfill a chunk of symbols using its own services/repo/provider."""
    symbols, db_path, days = args
    services = create_services(db_path=db_path)
    repo = services.repo
    from backend.stock_domain.provider_router import provider_router

    total_fetched = 0
    total_stored = 0
    errors: list[str] = []
    import time as _time
    for symbol in symbols:
        try:
            result = provider_router.get_history(symbol, days=days)
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
            continue
        items_raw = result.get("items", [])
        count = len(items_raw)
        total_fetched += count
        if result.get("degraded") or not items_raw:
            continue
        items = [
            StockDaily(
                symbol=symbol,
                trade_date=str(item.get("date", "")),
                open=float(item.get("open", 0)),
                high=float(item.get("high", 0)),
                low=float(item.get("low", 0)),
                close=float(item.get("close", 0)),
                volume=float(item.get("volume", 0)),
                amount=float(item.get("amount", 0)),
                source=result.get("source", ""),
            )
            for item in items_raw
        ]
        total_stored += repo.batch_upsert_stock_daily(items)
        _time.sleep(0.3)
    return {"fetched": total_fetched, "stored": total_stored, "errors": errors, "symbols": len(symbols)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill historical daily data into stock_daily")
    parser.add_argument("--db", default="data/workbench.sqlite3", help="SQLite DB path")
    parser.add_argument("--symbols", nargs="*", default=None, help="Stock symbols to backfill (default: all CN active stocks)")
    parser.add_argument("--days", type=int, default=252 * 3, help="Trading days of history per symbol (default: 3 years)")
    parser.add_argument("--workers", type=int, default=1, help="Parallel worker processes (default: 1)")
    parser.add_argument("--chunk-size", type=int, default=50, help="Symbols per worker chunk")
    parser.add_argument("--max-stocks", type=int, default=0, help="Max CN stocks to backfill (0=all, only without --symbols)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip symbols that already have data in stock_daily")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without fetching")
    args = parser.parse_args()

    services = create_services(db_path=args.db)
    repo = services.repo

    if args.symbols:
        symbols = args.symbols
    else:
        all_stocks = repo.list_stock_master(active_only=True)
        symbols = [s.symbol for s in all_stocks if s.market == "CN"]
        if args.max_stocks:
            symbols = symbols[:args.max_stocks]

    if not symbols:
        print("No symbols to backfill.")
        return 0

    if args.skip_existing:
        existing_rows = repo.conn.execute("SELECT DISTINCT symbol FROM stock_daily").fetchall()
        existing = {r["symbol"] for r in existing_rows}
        before = len(symbols)
        symbols = [s for s in symbols if s not in existing]
        skipped = before - len(symbols)
        print(f"Skipping {skipped} stocks already in stock_daily. {len(symbols)} remaining.")

    if not symbols:
        print("All symbols already have daily data.")
        return 0

    print(f"Backfilling {len(symbols)} CN stock(s) for ~{args.days} trading days each (workers={args.workers})...")

    if args.dry_run:
        for symbol in symbols:
            stock = repo.get_stock_master(symbol)
            name = stock.name if stock else symbol
            print(f"  [{symbol}] {name} ... would fetch ~{args.days} days")
        return 0

    # Split symbols into chunks for workers
    chunks = [symbols[i:i + args.chunk_size] for i in range(0, len(symbols), args.chunk_size)]
    worker_args = [(chunk, args.db, args.days) for chunk in chunks]

    total_start = time.perf_counter()
    total_fetched = 0
    total_stored = 0
    total_errors = 0

    if args.workers <= 1:
        # Sequential
        for wa in worker_args:
            result = _worker(wa)
            total_fetched += result["fetched"]
            total_stored += result["stored"]
            total_errors += len(result["errors"])
            perc = int(len(chunks) and (worker_args.index(wa) + 1) / len(chunks) * 100)
            print(f"  [{perc}%] {result['symbols']} stocks: {result['stored']} stored, {len(result['errors'])} errors")
    else:
        # Parallel
        with Pool(processes=args.workers) as pool:
            for result in pool.imap_unordered(_worker, worker_args):
                total_fetched += result["fetched"]
                total_stored += result["stored"]
                total_errors += len(result["errors"])
                print(f"  [{result['symbols']} stocks] {result['stored']} stored, {len(result['errors'])} errors")

    total_elapsed = time.perf_counter() - total_start
    err_detail = f", {total_errors} errors" if total_errors else ""
    print(f"\nDone. {total_fetched} records fetched, {total_stored} stored across {len(symbols)} stocks in {total_elapsed:.1f}s{err_detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
