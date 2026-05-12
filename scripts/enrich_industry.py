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
from backend.schemas import StockMaster


def _map_sector(industry: str) -> str:
    if not industry:
        return ""
    if "白酒" in industry or ("酒" in industry and "饮料" in industry):
        return "消费 / 白酒"
    if "酒" in industry or "饮料" in industry:
        return "消费 / 食品饮料"
    if "医药" in industry or "生物" in industry or "医疗" in industry or "制药" in industry:
        return "医药"
    if "银行" in industry or "证券" in industry or "保险" in industry or "金融" in industry:
        return "金融"
    if "房地产" in industry or "置业" in industry or "物业" in industry or "住宅" in industry:
        return "地产"
    if "科技" in industry or "信息技术" in industry or "计算机" in industry or "电子" in industry or "软件" in industry:
        return "科技"
    if "汽车" in industry or "新能源车" in industry or "整车" in industry:
        return "汽车"
    if "能源" in industry or "煤炭" in industry or "石油" in industry or "天然气" in industry or "新能源" in industry:
        return "能源"
    if "电力" in industry or "发电" in industry or "电网" in industry:
        return "电力"
    if "通信" in industry or "电信" in industry or "5G" in industry:
        return "通信"
    if "建筑" in industry or "建材" in industry or "基建" in industry or "工程" in industry or "装修" in industry:
        return "建筑"
    if "机械" in industry or "设备" in industry or "装备" in industry or "机床" in industry or "动力" in industry:
        return "机械"
    if "化工" in industry or "化学" in industry or "化纤" in industry or "塑料" in industry or "橡胶" in industry:
        return "化工"
    if "有色" in industry or "钢铁" in industry or "金属" in industry or "采矿" in industry or "矿产" in industry or "冶炼" in industry:
        return "原材料"
    if "农业" in industry or "牧业" in industry or "渔业" in industry or "种植" in industry or "林业" in industry:
        return "农业"
    if "国防" in industry or "军工" in industry or "航天" in industry or "航空" in industry or "船舶" in industry:
        return "军工"
    if "传媒" in industry or "影视" in industry or "游戏" in industry or "广告" in industry or "出版" in industry:
        return "传媒"
    if "零售" in industry or "贸易" in industry or "商贸" in industry or "批发" in industry or "百货" in industry:
        return "商业贸易"
    if "运输" in industry or "物流" in industry or "航空" in industry or "铁路" in industry or "航运" in industry or "港口" in industry:
        return "交通运输"
    if "环保" in industry or "水务" in industry or "固废" in industry:
        return "环保"
    if "纺织" in industry or "服装" in industry or "鞋" in industry or "布" in industry or "面料" in industry:
        return "纺织服装"
    if "食品" in industry:
        return "消费 / 食品"
    if "综合" in industry:
        return "综合"
    if "服务" in industry or "租赁" in industry or "商务" in industry:
        return "商业服务"
    if "互联网" in industry or "云计算" in industry or "大数据" in industry or "人工智能" in industry or "AI" in industry.upper():
        return "互联网"
    if "教育" in industry or "培训" in industry or "学校" in industry:
        return "教育"
    if "旅游" in industry or "酒店" in industry or "餐饮" in industry or "住宿" in industry:
        return "旅游餐饮"
    return "其他"


def _worker(args: tuple[list[str], str]) -> dict[str, Any]:
    symbols, db_path = args
    import urllib.request
    urllib.request.getproxies = lambda: {}
    import akshare as ak

    services = create_services(db_path=db_path)
    repo = services.repo
    enriched = 0
    errors: list[str] = []
    for symbol in symbols:
        try:
            frame = ak.stock_profile_cninfo(symbol=symbol)
            if frame.empty:
                continue
            profile = frame.iloc[0].to_dict()
            industry = str(profile.get("所属行业", "") or "")
            if not industry:
                continue
            sector = _map_sector(industry)
            repo.upsert_stock_master(StockMaster(
                symbol=symbol,
                name=str(profile.get("A股简称", "")),
                market="CN",
                industry=industry,
                sector=sector,
            ))
            enriched += 1
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
    return {"enriched": enriched, "errors": errors, "symbols": len(symbols)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich stock_master industry/sector from AKShare profile")
    parser.add_argument("--db", default="data/workbench.sqlite3", help="SQLite DB path")
    parser.add_argument("--workers", type=int, default=1, help="Parallel worker processes")
    parser.add_argument("--chunk-size", type=int, default=50, help="Symbols per worker chunk")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be done without writing")
    args = parser.parse_args()

    services = create_services(db_path=args.db)
    repo = services.repo

    # All CN stocks with empty industry
    rows = repo.conn.execute("""
        SELECT symbol FROM stock_master
        WHERE market='CN' AND (industry IS NULL OR industry = '')
        ORDER BY symbol
    """).fetchall()
    symbols = [r["symbol"] for r in rows]

    if not symbols:
        print("All CN stocks already have industry data.")
        return 0

    print(f"Enriching {len(symbols)} CN stocks (workers={args.workers})...")

    if args.dry_run:
        for s in symbols[:10]:
            print(f"  [{s}] would fetch profile")
        if len(symbols) > 10:
            print(f"  ... and {len(symbols) - 10} more")
        return 0

    chunks = [symbols[i:i + args.chunk_size] for i in range(0, len(symbols), args.chunk_size)]
    worker_args = [(chunk, args.db) for chunk in chunks]

    total_start = time.perf_counter()
    total_enriched = 0
    total_errors = 0

    if args.workers <= 1:
        for wa in worker_args:
            result = _worker(wa)
            total_enriched += result["enriched"]
            total_errors += len(result["errors"])
            perc = int(worker_args.index(wa) / len(worker_args) * 100) if worker_args else 0
            elapsed = time.perf_counter() - total_start
            print(f"  [{perc}%] {result['symbols']} stocks: {result['enriched']} enriched, {len(result['errors'])} errors ({elapsed:.0f}s)")
    else:
        with Pool(processes=args.workers) as pool:
            for result in pool.imap_unordered(_worker, worker_args):
                total_enriched += result["enriched"]
                total_errors += len(result["errors"])
                elapsed = time.perf_counter() - total_start
                print(f"  [{result['symbols']} stocks] {result['enriched']} enriched, {len(result['errors'])} errors ({elapsed:.0f}s)")

    total_elapsed = time.perf_counter() - total_start
    err_detail = f", {total_errors} errors" if total_errors else ""
    print(f"\nDone. {total_enriched}/{len(symbols)} enriched in {total_elapsed:.1f}s{err_detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
