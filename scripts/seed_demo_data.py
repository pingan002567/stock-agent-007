import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.persistence.db import connect
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import (
    HoldingPosition,
    WatchlistItem,
    StockDaily,
    StockFinancial,
    EventContext,
    now_iso,
)


class _DetRNG:
    def __init__(self, seed: int):
        self.state = seed & 0x7FFFFFFF

    def next(self) -> float:
        self.state = (self.state * 1103515245 + 12345) & 0x7FFFFFFF
        return self.state / 0x7FFFFFFF

    def uniform(self, low: float, high: float) -> float:
        return low + self.next() * (high - low)


def _get_price_from_holding(holding: HoldingPosition) -> float:
    if holding.quantity > 0:
        return holding.market_value / holding.quantity
    return 100.0


def _generate_trading_dates(end: datetime, count: int) -> List[str]:
    dates: List[str] = []
    current = end
    while len(dates) < count:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y-%m-%d"))
        current -= timedelta(days=1)
    dates.reverse()
    return dates


def _generate_daily_rows(
    symbol: str,
    base_price: float,
    dates: List[str],
    seed: int,
) -> List[StockDaily]:
    rng = _DetRNG(seed)
    rows: List[StockDaily] = []
    close = base_price
    for trade_date in dates:
        ret = rng.uniform(0.003 - 0.04, 0.003 + 0.04)
        change = rng.uniform(-0.01, 0.01)
        open_price = close * (1 + change)
        close = close * (1 + ret)
        high = max(open_price, close) * (1 + abs(rng.uniform(0, 0.015)))
        low = min(open_price, close) * (1 - abs(rng.uniform(0, 0.015)))
        vol_factor = max(1.0, 500.0 / base_price) if base_price > 0 else 1.0
        volume = int(abs(rng.uniform(2e5, 5e6) * vol_factor))
        amount = volume * (open_price + close) / 2
        rows.append(StockDaily(
            symbol=symbol,
            trade_date=trade_date,
            open=round(open_price, 2),
            high=round(high, 2),
            low=round(low, 2),
            close=round(close, 2),
            volume=volume,
            amount=round(amount, 2),
            source="seed_demo",
        ))
    return rows


def _generate_financial_rows(
    symbol: str,
    base_price: float,
    seed: int,
) -> List[StockFinancial]:
    rng = _DetRNG(seed + 999)
    rows: List[StockFinancial] = []
    base_revenue = base_price * rng.uniform(50, 200)
    quarter_end = {1: "03-31", 2: "06-30", 3: "09-30", 4: "12-31"}
    for i in range(8):
        year = 2023 + i // 4
        q = (i % 4) + 1
        report_date = f"{year}-{quarter_end[q]}"
        growth = 1.0 + (i / 7.0) * 0.4
        noise = 1.0 + rng.uniform(-0.05, 0.05)
        revenue = base_revenue * growth * noise
        profit_margin = rng.uniform(0.10, 0.15)
        profit = revenue * profit_margin
        total_assets = revenue * rng.uniform(2.0, 3.0)
        total_liabilities = total_assets * rng.uniform(0.8, 1.5)
        rows.append(StockFinancial(
            symbol=symbol,
            report_date=report_date,
            report_type="quarterly",
            revenue=round(revenue, 2),
            profit=round(profit, 2),
            total_assets=round(total_assets, 2),
            total_liabilities=round(total_liabilities, 2),
        ))
    return rows


def main():
    db_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "workbench.sqlite3",
    )
    print(f"Connecting to {db_path}")
    conn = connect(db_path)
    repo = WorkbenchRepository(conn)

    existing_holdings_map = {h.symbol.upper(): h for h in repo.list_holdings()}
    existing_watchlist_map = {w.symbol.upper(): w for w in repo.list_watchlist()}

    new_holdings = [
        ("000858", "五粮液", 500, 68500.0, 7.6, 72000.0, -4.86),
        ("300750", "宁德时代", 200, 45200.0, 5.0, 41000.0, 10.24),
        ("601318", "中国平安", 800, 39200.0, 4.3, 40000.0, -2.0),
        ("03690", "美团-W", 300, 45000.0, 5.0, 43500.0, 3.45),
        ("MSFT", "Microsoft", 50, 22500.0, 2.5, 21000.0, 7.14),
        ("NVDA", "NVIDIA", 30, 28500.0, 3.2, 24000.0, 18.75),
        ("00005", "汇丰控股", 2000, 156000.0, 17.3, 148000.0, 5.41),
        ("TSLA", "Tesla", 40, 14000.0, 1.6, 16000.0, -12.5),
        ("688981", "中芯国际", 500, 32500.0, 3.6, 35000.0, -7.14),
        ("BABA", "Alibaba", 100, 12500.0, 1.4, 13000.0, -3.85),
    ]
    holdings_added = 0
    holdings_skipped_no_master = 0
    for sym, name, qty, mv, wp, cost, pnl in new_holdings:
        s = sym.upper()
        if s in existing_holdings_map:
            continue
        master = repo.get_stock_master(s)
        if master is None:
            holdings_skipped_no_master += 1
            continue
        repo.upsert_holding(HoldingPosition(
            symbol=sym, name=name, quantity=qty,
            market_value=mv, weight_pct=wp, cost=cost, pnl_pct=pnl,
        ))
        holdings_added += 1

    watchlist_specs = [
        ("MSFT", "Microsoft", "核心持仓", ["大型科技", "美股"], True),
        ("300750", "宁德时代", "核心持仓", ["新能源"], True),
        ("000858", "五粮液", "核心持仓", ["白酒"], True),
        ("NVDA", "NVIDIA", "AI 关注", ["AI芯片", "美股"]),
        ("BABA", "Alibaba", "AI 关注", ["互联网", "美股"]),
        ("688041", "海光信息", "AI 关注", ["AI芯片"]),
        ("688111", "金山办公", "AI 关注", ["AI应用"]),
        ("00005", "汇丰控股", "事件池", ["银行", "港股"]),
        ("03690", "美团-W", "事件池", ["互联网", "港股"]),
        ("TSLA", "Tesla", "事件池", ["新能源", "美股"]),
        ("601318", "中国平安", "事件池", ["保险"]),
        ("600276", "恒瑞医药", "观察池", ["医药"]),
        ("002475", "立讯精密", "观察池", ["消费电子"]),
        ("JPM", "JPMorgan Chase", "观察池", ["银行", "美股"]),
        ("KO", "Coca-Cola", "观察池", ["消费", "美股"]),
        ("SPY", "SPDR S&P 500 ETF", "观察池", ["ETF", "美股"]),
    ]
    watchlist_added = 0
    watchlist_skipped_no_master = 0
    for sym, name, group, tags, *mon in watchlist_specs:
        s = sym.upper()
        if s in existing_watchlist_map:
            continue
        master = repo.get_stock_master(s)
        if master is None:
            watchlist_skipped_no_master += 1
            continue
        monitored = mon[0] if mon else False
        repo.upsert_watchlist_item(WatchlistItem(
            symbol=sym, name=name, group=group, tags=tags, monitored=monitored,
        ))
        watchlist_added += 1

    all_holdings = repo.list_holdings()
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    dates = _generate_trading_dates(yesterday, 90)
    all_daily: List[StockDaily] = []
    for h in all_holdings:
        seed = abs(hash(h.symbol))
        base_price = _get_price_from_holding(h)
        all_daily.extend(_generate_daily_rows(h.symbol, base_price, dates, seed))
    daily_added = repo.batch_upsert_stock_daily(all_daily)

    financial_added = 0
    for h in all_holdings:
        seed = abs(hash(h.symbol))
        base_price = _get_price_from_holding(h)
        fin_rows = _generate_financial_rows(h.symbol, base_price, seed)
        for f in fin_rows:
            repo.upsert_stock_financial(f)
            financial_added += 1

    monitor_events_added = 0
    held_symbols = [h.symbol for h in all_holdings]
    if held_symbols:
        ev = now_iso()
        price_event_symbols = held_symbols[:3]
        for i, sym in enumerate(price_event_symbols):
            pct_change = [5.2, -3.8, 4.1][i]
            direction = "上涨" if pct_change > 0 else "下跌"
            event = EventContext(
                event_id=f"seed-demo-price-{uuid.uuid4().hex[:8]}",
                source="system",
                symbol=sym,
                title=f"{sym} 日内价格{direction} {abs(pct_change):.1f}%",
                severity="medium",
                triggered_at=ev,
                trigger_rule="abs(price_change_pct) > 3%",
                rule_id="seed-price-move",
                rule_type="price_change_pct_gt",
                evidence=[{"type": "price_alert", "value": f"{sym} price moved {pct_change:+.1f}%"}],
                suggested_actions=["open_stock_context"],
            )
            repo.save_monitor_event(event)
            monitor_events_added += 1

    parts = [f"Done. Seeded {holdings_added} holdings"]
    if holdings_skipped_no_master:
        parts.append(f"[{holdings_skipped_no_master} holding stocks skipped (not in stock_master)]")
    parts.append(f"{watchlist_added} watchlist")
    if watchlist_skipped_no_master:
        parts.append(f"[{watchlist_skipped_no_master} watchlist items skipped (not in stock_master)]")
    parts.append(f"{daily_added} daily rows")
    parts.append(f"{financial_added} financial rows")
    if monitor_events_added:
        parts.append(f"{monitor_events_added} monitor events")
    print(", ".join(parts))


if __name__ == "__main__":
    main()
