from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta, timezone
from importlib.util import find_spec
from typing import Any, Callable

from backend.schemas import PriceSnapshot, now_iso
from backend.stock_domain.catalog import get_stock, normalize_symbol
from backend.stock_domain.provider_credentials import resolve as provider_credential
from backend.stock_domain.providers import (
    MarketDataProvider,
    ProviderError,
    _bounded_days,
    _coerce_float,
    _frame_tail,
    _first,
    _history_item,
    _number,
    _safe_float,
    _safe_iso,
)


# ──────────────────────────────────────────────
#  TickFlow — A-share tick-level & historical data
# ──────────────────────────────────────────────


class TickFlowMarketDataProvider:
    """A-share market data via TickFlow WebSocket/API.

    Requires ``tickflow`` package and ``TICKFLOW_API_KEY`` env var or config.
    Covers CN market (A-share real-time quotes, history, sector data).
    """

    name = "tickflow"

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, Any]] = {}
        self._call_lock = threading.RLock()

    @property
    def _api_key(self) -> str | None:
        return provider_credential("tickflow", "api_key")

    def is_available(self) -> bool:
        if (
            os.getenv("PYTEST_CURRENT_TEST")
            and os.getenv("WORKBENCH_TEST_ENABLE_TICKFLOW") != "1"
        ):
            return False
        return find_spec("tickflow") is not None and self._api_key is not None

    def _ensure_available(self) -> None:
        if not self.is_available():
            raise ProviderError(
                "tickflow optional dependency or TICKFLOW_API_KEY not set"
            )

    def get_quote(self, symbol: str) -> PriceSnapshot:
        self._ensure_available()
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) != "CN":
            raise ProviderError(f"tickflow only covers CN market: {normalized}")
        import tickflow as tf  # type: ignore[import-not-found]

        tf.set_token(self._api_key)
        df = tf.quote(symbol=normalized)
        row = _frame_tail(df, 1)
        if not row:
            raise ProviderError(f"tickflow empty quote for {normalized}")
        r = row[0]
        return PriceSnapshot(
            last=_coerce_float(r.get("last") or r.get("price")),
            change_pct=_coerce_float(r.get("change_pct") or r.get("changePercent")),
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": "CN",
                "mode": "real",
                "source_interface": "tickflow.quote",
            },
        )

    def get_history(self, symbol: str, days: int = 30) -> dict:
        self._ensure_available()
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) != "CN":
            raise ProviderError(f"tickflow only covers CN market: {normalized}")
        import tickflow as tf

        tf.set_token(self._api_key)
        end = datetime.now(timezone.utc).strftime("%Y%m%d")
        start = (
            datetime.now(timezone.utc)
            - timedelta(days=max(_bounded_days(days) * 2, 30))
        ).strftime("%Y%m%d")
        df = tf.kline(symbol=normalized, start=start, end=end)
        rows = _frame_tail(df, _bounded_days(days))
        items = [_history_item(r, idx + 1) for idx, r in enumerate(rows)]
        if not items:
            raise ProviderError(f"tickflow empty history for {normalized}")
        return {
            "symbol": normalized,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "coverage": {
                "market": "CN",
                "mode": "real",
                "source_interface": "tickflow.kline",
            },
            "items": items,
        }

    def search_intel(self, symbol: str, query: str = "") -> dict:
        raise ProviderError("tickflow: intel/search not supported")

    def get_market_review(self) -> dict:
        raise ProviderError("tickflow: market review not supported")

    def get_sectors(self) -> dict:
        raise ProviderError("tickflow: sectors not supported")

    def get_financial(self, symbol: str) -> dict:
        raise ProviderError("tickflow: financial not supported")


# ──────────────────────────────────────────────
#  Tushare Pro — Chinese financial data
# ──────────────────────────────────────────────


class TushareMarketDataProvider:
    """Chinese market data via Tushare Pro API.

    Requires ``tushare`` package and ``TUSHARE_TOKEN`` env var.
    Covers CN market (A-share quotes, history, financials).
    """

    name = "tushare"

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, Any]] = {}
        self._call_lock = threading.RLock()
        self._pro: Any = None

    @property
    def _token(self) -> str | None:
        return provider_credential("tushare", "token")

    def is_available(self) -> bool:
        if (
            os.getenv("PYTEST_CURRENT_TEST")
            and os.getenv("WORKBENCH_TEST_ENABLE_TUSHARE") != "1"
        ):
            return False
        return find_spec("tushare") is not None and self._token is not None

    def _api(self):
        if find_spec("tushare") is None:
            raise ProviderError("tushare package is not installed")
        if not self._token:
            raise ProviderError("TUSHARE_TOKEN not set")
        if not self.is_available():
            raise ProviderError("tushare is not available")
        if self._pro is None:
            import tushare as ts  # type: ignore[import-not-found]

            self._pro = ts.pro_api(self._token)
        return self._pro

    def get_quote(self, symbol: str) -> PriceSnapshot:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) not in ("CN", "HK"):
            raise ProviderError(f"tushare only covers CN/HK markets: {normalized}")
        pro = self._api()
        # Try daily_basic for most recent trading day
        try:
            df = pro.daily_basic(
                ts_code=_ts_code(normalized, stock), fields="close,pct_chg"
            )
            row = _frame_tail(df, 1)
            if row:
                r = row[0]
                return PriceSnapshot(
                    last=_coerce_float(r.get("close")),
                    change_pct=_coerce_float(r.get("pct_chg")),
                    updated_at=now_iso(),
                    source=self.name,
                    degraded=False,
                    coverage={
                        "market": str(stock["market"]),
                        "mode": "real",
                        "source_interface": "tushare.daily_basic",
                    },
                )
        except Exception:
            pass
        # Fallback to daily
        df = pro.daily(ts_code=_ts_code(normalized, stock), limit=1)
        row = _frame_tail(df, 1)
        if not row:
            raise ProviderError(f"tushare empty quote for {normalized}")
        r = row[0]
        return PriceSnapshot(
            last=_coerce_float(r.get("close")),
            change_pct=_coerce_float(r.get("pct_chg")),
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": str(stock["market"]),
                "mode": "real",
                "source_interface": "tushare.daily",
            },
        )

    def get_history(self, symbol: str, days: int = 30) -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) not in ("CN", "HK"):
            raise ProviderError(f"tushare only covers CN/HK markets: {normalized}")
        pro = self._api()
        end = datetime.now(timezone.utc).strftime("%Y%m%d")
        start = (
            datetime.now(timezone.utc)
            - timedelta(days=max(_bounded_days(days) * 2, 30))
        ).strftime("%Y%m%d")
        ts = _ts_code(normalized, stock)
        from backend.stock_domain.catalog import is_etf_like

        items: list[dict] = []
        source_interface = "tushare.daily"
        if is_etf_like(normalized, stock) and str(stock["market"]) == "CN":
            try:
                df = pro.fund_daily(ts_code=ts, start_date=start, end_date=end)
                if hasattr(df, "sort_values"):
                    df = df.sort_values("trade_date")
                rows = _frame_tail(df, _bounded_days(days))
                items = [
                    _history_item(
                        r,
                        idx + 1,
                        date_keys=("trade_date",),
                        open_keys=("open",),
                        high_keys=("high",),
                        low_keys=("low",),
                        close_keys=("close",),
                        volume_keys=("vol",),
                        amount_keys=("amount",),
                    )
                    for idx, r in enumerate(rows)
                ]
                source_interface = "tushare.fund_daily"
            except Exception:
                items = []
        if not items:
            df = pro.daily(ts_code=ts, start_date=start, end_date=end)
            if hasattr(df, "sort_values"):
                df = df.sort_values("trade_date")
            rows = _frame_tail(df, _bounded_days(days))
            items = [
                _history_item(
                    r,
                    idx + 1,
                    date_keys=("trade_date",),
                    open_keys=("open",),
                    high_keys=("high",),
                    low_keys=("low",),
                    close_keys=("close",),
                    volume_keys=("vol",),
                    amount_keys=("amount",),
                )
                for idx, r in enumerate(rows)
            ]
            source_interface = "tushare.daily"
        if not items:
            raise ProviderError(f"tushare empty history for {normalized}")
        return {
            "symbol": normalized,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "coverage": {
                "market": str(stock["market"]),
                "mode": "real",
                "source_interface": source_interface,
            },
            "items": items,
        }

    def search_intel(self, symbol: str, query: str = "") -> dict:
        raise ProviderError("tushare: intel/search not supported")

    def get_market_review(self) -> dict:
        raise ProviderError("tushare: market review not supported")

    def get_sectors(self) -> dict:
        raise ProviderError("tushare: sectors not supported")

    def get_financial(self, symbol: str) -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) != "CN":
            raise ProviderError(f"tushare financials only cover CN: {normalized}")
        pro = self._api()
        df = pro.financial_report(ts_code=_ts_code(normalized, stock), limit=4)
        rows = _frame_tail(df, 4)
        items = []
        for r in rows:
            items.append(
                {
                    "report_date": str(r.get("end_date", "")),
                    "report_type": "annual"
                    if str(r.get("end_date", "")).endswith("1231")
                    else "quarterly",
                    "revenue": _coerce_float(r.get("revenue")),
                    "profit": _coerce_float(r.get("net_profit")),
                    "total_assets": _coerce_float(r.get("total_assets")),
                    "total_liabilities": _coerce_float(r.get("total_liabilities")),
                }
            )
        return {
            "symbol": normalized,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "coverage": {
                "market": "CN",
                "mode": "real",
                "source_interface": "tushare.financial_report",
            },
            "items": items,
        }

    def fetch_fund_flow_rows(self, symbol: str, limit: int = 12) -> list[dict[str, Any]]:
        """A-share moneyflow, mapped onto the Eastmoney row shape the structure block reads.

        ``moneyflow`` needs 2000 points and updates around 19:00. Amounts are 万元;
        the structure layer stores 元, matching AKShare 主力净流入-净额.
        """
        normalized, stock = self._cn_stock(symbol)
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=40)).strftime("%Y%m%d")
        frame = self._api().moneyflow(
            ts_code=_ts_code(normalized, stock),
            start_date=start,
            end_date=end,
        )
        rows = [_moneyflow_row(item) for item in _frame_tail(frame, 80)]
        rows = [row for row in rows if row.get("日期")]
        rows.sort(key=lambda row: str(row.get("日期")))
        if limit > 0:
            rows = rows[-limit:]
        return rows

    def fetch_chip_cyq(self, symbol: str) -> list[dict[str, Any]]:
        """Daily chip summary (cyq_perf), not the Eastmoney price histogram.

        Official points table puts 每日筹码及胜率 at 10000. The call fails closed
        if the account is refused; nothing is invented from the distribution API.
        """
        normalized, stock = self._cn_stock(symbol)
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        frame = self._api().cyq_perf(
            ts_code=_ts_code(normalized, stock),
            start_date=start,
            end_date=end,
        )
        rows = [_cyq_perf_row(item) for item in _frame_tail(frame, 40)]
        return [row for row in rows if row.get("日期")]

    def fetch_spot_snapshot(self, symbol: str) -> dict[str, Any]:
        """Valuation and liquidity from daily_basic. Not a live quote."""
        normalized, stock = self._cn_stock(symbol)
        ts_code = _ts_code(normalized, stock)
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=15)).strftime("%Y%m%d")
        basic = _frame_tail(
            self._api().daily_basic(ts_code=ts_code, start_date=start, end_date=end),
            1,
        )
        daily = _frame_tail(
            self._api().daily(ts_code=ts_code, start_date=start, end_date=end),
            1,
        )
        if not basic and not daily:
            return {}
        return _tushare_snapshot(basic[0] if basic else {}, daily[0] if daily else {})

    def fetch_northbound_hold(self, symbol: str) -> dict[str, Any]:
        """沪深股通持股快照（hk_hold）。日度北向自 2024-08-20 起改季度披露。"""
        normalized, stock = self._cn_stock(symbol)
        ts_code = _ts_code(normalized, stock)
        try:
            frame = self._api().hk_hold(ts_code=ts_code)
        except Exception as exc:
            raise ProviderError(f"tushare hk_hold failed: {exc}") from exc
        rows = _frame_tail(frame, 40) if frame is not None else []
        rows = sorted(
            [r for r in rows if r.get("trade_date")],
            key=lambda r: str(r.get("trade_date")),
        )
        note = (
            "交易所自2024-08-20起停发日度北向资金数据、改为季度披露；"
            "本字段为沪深股通持股快照，as_of 可能滞后"
        )
        if not rows:
            return {
                "degraded": False,
                "on_list": False,
                "as_of": None,
                "vol": None,
                "ratio": None,
                "exchange": None,
                "source": "tushare.hk_hold",
                "note": note,
            }
        latest = rows[-1]
        return {
            "degraded": False,
            "on_list": True,
            "as_of": _ts_date(latest.get("trade_date")),
            "vol": _coerce_float(latest.get("vol")),
            "ratio": _coerce_float(latest.get("ratio")),
            "exchange": str(latest.get("exchange") or "") or None,
            "name": str(latest.get("name") or "") or None,
            "source": "tushare.hk_hold",
            "note": note,
        }

    def fetch_margin_detail(self, symbol: str) -> dict[str, Any]:
        """个股融资融券明细最新一行（margin_detail）。"""
        normalized, stock = self._cn_stock(symbol)
        ts_code = _ts_code(normalized, stock)
        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=40)).strftime("%Y%m%d")
        try:
            frame = self._api().margin_detail(
                ts_code=ts_code, start_date=start, end_date=end
            )
        except Exception as exc:
            raise ProviderError(f"tushare margin_detail failed: {exc}") from exc
        rows = _frame_tail(frame, 40) if frame is not None else []
        rows = sorted(
            [r for r in rows if r.get("trade_date")],
            key=lambda r: str(r.get("trade_date")),
        )
        if not rows:
            return {
                "degraded": False,
                "available": False,
                "as_of": None,
                "source": "tushare.margin_detail",
            }
        latest = rows[-1]
        return {
            "degraded": False,
            "available": True,
            "as_of": _ts_date(latest.get("trade_date")),
            "rzye": _coerce_float(latest.get("rzye")),
            "rqye": _coerce_float(latest.get("rqye")),
            "rzmre": _coerce_float(latest.get("rzmre")),
            "rzche": _coerce_float(latest.get("rzche")),
            "rqyl": _coerce_float(latest.get("rqyl")),
            "rzrqye": _coerce_float(latest.get("rzrqye")),
            "source": "tushare.margin_detail",
        }

    def fetch_lhb(self, symbol: str, *, lookback_days: int = 20, limit: int = 5) -> dict[str, Any]:
        """龙虎榜 top_list；有上榜日时附带 top_inst 机构摘要。"""
        normalized, stock = self._cn_stock(symbol)
        ts_code = _ts_code(normalized, stock)
        pro = self._api()
        collected: list[dict[str, Any]] = []
        day = datetime.now()
        checked = 0
        max_checks = max(int(lookback_days), 5)
        while checked < max_checks and len(collected) < max(int(limit), 1):
            if day.weekday() < 5:
                trade_date = day.strftime("%Y%m%d")
                try:
                    frame = pro.top_list(trade_date=trade_date, ts_code=ts_code)
                except Exception as exc:
                    if checked == 0 and not collected:
                        raise ProviderError(f"tushare top_list failed: {exc}") from exc
                    checked += 1
                    day -= timedelta(days=1)
                    continue
                for row in _frame_tail(frame, 20) if frame is not None else []:
                    item = {
                        "trade_date": _ts_date(row.get("trade_date") or trade_date),
                        "reason": str(row.get("reason") or "") or None,
                        "close": _coerce_float(row.get("close")),
                        "pct_change": _coerce_float(row.get("pct_change")),
                        "net_amount": _coerce_float(row.get("net_amount")),
                        "l_buy": _coerce_float(row.get("l_buy")),
                        "l_sell": _coerce_float(row.get("l_sell")),
                        "l_amount": _coerce_float(row.get("l_amount")),
                        "net_rate": _coerce_float(row.get("net_rate")),
                    }
                    try:
                        inst_frame = pro.top_inst(trade_date=trade_date, ts_code=ts_code)
                        inst_rows = _frame_tail(inst_frame, 8) if inst_frame is not None else []
                        institutions: list[str] = []
                        for inst in inst_rows:
                            name = str(
                                inst.get("exalter")
                                or inst.get("broker")
                                or inst.get("buy_member")
                                or inst.get("sell_member")
                                or ""
                            ).strip()
                            if name and name not in institutions:
                                institutions.append(name[:40])
                            if len(institutions) >= 4:
                                break
                        if institutions:
                            item["institutions"] = institutions
                    except Exception:
                        pass
                    collected.append(item)
                    if len(collected) >= max(int(limit), 1):
                        break
                checked += 1
            day -= timedelta(days=1)
        collected.sort(key=lambda r: str(r.get("trade_date") or ""), reverse=True)
        return {
            "degraded": False,
            "on_list": bool(collected),
            "as_of": collected[0].get("trade_date") if collected else None,
            "items": collected[: max(int(limit), 1)],
            "count": len(collected),
            "source": "tushare.top_list",
            "lookback_trading_days": checked,
        }

    def fetch_share_float(self, symbol: str, *, limit: int = 10) -> dict[str, Any]:
        """限售解禁：过去 90 天～未来 180 天。"""
        normalized, stock = self._cn_stock(symbol)
        ts_code = _ts_code(normalized, stock)
        today = datetime.now().date()
        start = (today - timedelta(days=90)).strftime("%Y%m%d")
        end = (today + timedelta(days=180)).strftime("%Y%m%d")
        try:
            frame = self._api().share_float(
                ts_code=ts_code, start_date=start, end_date=end
            )
        except Exception as exc:
            raise ProviderError(f"tushare share_float failed: {exc}") from exc
        rows = _frame_tail(frame, 200) if frame is not None else []
        upcoming: list[dict[str, Any]] = []
        recent: list[dict[str, Any]] = []
        today_s = today.isoformat()
        for row in rows:
            float_date = _ts_date(row.get("float_date"))
            if not float_date:
                continue
            entry = {
                "float_date": float_date,
                "ann_date": _ts_date(row.get("ann_date")) or None,
                "float_share": _coerce_float(row.get("float_share")),
                "float_ratio": _coerce_float(row.get("float_ratio")),
                "holder_name": (str(row.get("holder_name") or "")[:40] or None),
                "share_type": str(row.get("share_type") or "") or None,
            }
            if float_date >= today_s:
                upcoming.append(entry)
            else:
                recent.append(entry)
        upcoming.sort(key=lambda r: str(r.get("float_date") or ""))
        recent.sort(key=lambda r: str(r.get("float_date") or ""), reverse=True)
        cap = max(int(limit), 1)
        return {
            "degraded": False,
            "upcoming": upcoming[:cap],
            "recent": recent[:cap],
            "upcoming_count": len(upcoming),
            "recent_count": len(recent),
            "source": "tushare.share_float",
            "window": {"start": _ts_date(start), "end": _ts_date(end)},
        }

    def _cn_stock(self, symbol: str) -> tuple[str, dict]:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock.get("market")) != "CN":
            raise ProviderError(f"tushare chip/fund-flow only cover CN: {normalized}")
        return normalized, stock


def _ts_date(value: Any) -> str:
    raw = str(value or "").strip()
    if len(raw) >= 8 and raw[:8].isdigit():
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    return raw[:10]


def _wan_to_yuan(value: Any) -> float | None:
    amount = _coerce_float(value)
    if amount is None:
        return None
    return round(amount * 10000.0, 2)


def _order_net_yuan(row: dict[str, Any], buy_key: str, sell_key: str) -> float | None:
    buy = _coerce_float(row.get(buy_key))
    sell = _coerce_float(row.get(sell_key))
    if buy is None or sell is None:
        return None
    return round((buy - sell) * 10000.0, 2)


def _moneyflow_row(row: dict[str, Any]) -> dict[str, Any]:
    super_net = _order_net_yuan(row, "buy_elg_amount", "sell_elg_amount")
    large_net = _order_net_yuan(row, "buy_lg_amount", "sell_lg_amount")
    main_net = None
    if super_net is not None or large_net is not None:
        main_net = round((super_net or 0.0) + (large_net or 0.0), 2)
    return {
        "日期": _ts_date(row.get("trade_date")),
        "主力净流入-净额": main_net,
        "超大单净流入-净额": super_net,
        "大单净流入-净额": large_net,
        "source": "tushare.moneyflow",
    }


def _cyq_perf_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "日期": _ts_date(row.get("trade_date")),
        "获利比例": row.get("winner_rate"),
        "平均成本": row.get("weight_avg"),
        "90成本-低": row.get("cost_5pct"),
        "90成本-高": row.get("cost_95pct"),
        "70成本-低": row.get("cost_15pct"),
        "70成本-高": row.get("cost_85pct"),
        "method": "tushare_cyq_perf",
    }


def _tushare_snapshot(basic: dict[str, Any], daily: dict[str, Any]) -> dict[str, Any]:
    pre_close = _coerce_float(daily.get("pre_close"))
    high = _coerce_float(daily.get("high"))
    low = _coerce_float(daily.get("low"))
    amplitude = None
    if pre_close and high is not None and low is not None and pre_close > 0:
        amplitude = round((high - low) / pre_close * 100.0, 4)
    return {
        "last": _coerce_float(basic.get("close") or daily.get("close")),
        "open": _coerce_float(daily.get("open")),
        "high": high,
        "low": low,
        "volume": _coerce_float(daily.get("vol")),
        "amount": _wan_to_yuan(daily.get("amount")),
        "turnover_pct": _coerce_float(basic.get("turnover_rate")),
        "amplitude_pct": amplitude,
        "volume_ratio": _coerce_float(basic.get("volume_ratio")),
        "pe": _coerce_float(basic.get("pe_ttm") or basic.get("pe")),
        "pb": _coerce_float(basic.get("pb")),
        "total_market_cap": _wan_to_yuan(basic.get("total_mv")),
        "float_market_cap": _wan_to_yuan(basic.get("circ_mv")),
        "as_of": _ts_date(basic.get("trade_date") or daily.get("trade_date")),
        "source": "tushare.daily_basic",
    }


def _ts_code(symbol: str, stock: dict) -> str:
    """Convert normalized symbol to Tushare ts_code format.

    CN: '000001.SZ' or '600519.SH' / '510300.SH'
    HK: '00700.HK'
    """
    market = str(stock.get("market", ""))
    if market == "HK":
        code = symbol.removeprefix("HK")
        return f"{code}.HK"
    # CN: SH — 6/688 股票、5 开头 ETF/基金、11 债；其余默认 SZ
    if symbol.startswith(("5", "6", "688", "11")):
        return f"{symbol}.SH"
    return f"{symbol}.SZ"


# ──────────────────────────────────────────────
#  Pytdx — 通达信行情数据
# ──────────────────────────────────────────────


class PytdxMarketDataProvider:
    """Chinese market data via Pytdx (通达信) TCP protocol.

    Requires ``pytdx`` package. No API key needed.
    Connects directly to TDX market data servers.
    Covers CN market A-share quotes and history.
    """

    name = "pytdx"

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, Any]] = {}
        self._call_lock = threading.RLock()
        self._api_instance: Any = None

    def is_available(self) -> bool:
        if (
            os.getenv("PYTEST_CURRENT_TEST")
            and os.getenv("WORKBENCH_TEST_ENABLE_PYTDX") != "1"
        ):
            return False
        return find_spec("pytdx") is not None

    def _api(self):
        if not self.is_available():
            raise ProviderError("pytdx optional dependency not installed")
        if self._api_instance is None:
            from pytdx.hq import TDX_HQ_API  # type: ignore[import-not-found]

            self._api_instance = TDX_HQ_API()
        return self._api_instance

    def _tdx_code(self, symbol: str) -> tuple[str, int]:
        """Convert normalized symbol to (code, exchange) for TDX.

        Returns (code, exchange) where exchange=1 for SH, 0 for SZ.
        """
        if symbol.startswith(("6", "688")):
            return symbol, 1
        return symbol, 0

    def get_quote(self, symbol: str) -> PriceSnapshot:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) != "CN":
            raise ProviderError(f"pytdx only covers CN market: {normalized}")
        api = self._api()
        code, exchange = self._tdx_code(normalized)
        with self._call_lock:
            quotes = api.get_security_quotes([(exchange, code)])
        if not quotes:
            raise ProviderError(f"pytdx empty quote for {normalized}")
        q = quotes[0]
        last = _coerce_float(q.get("price", 0))
        pre_close = _coerce_float(q.get("last_close", 0))
        change_pct = (
            round((last - pre_close) / pre_close * 100, 2) if pre_close else 0.0
        )
        return PriceSnapshot(
            last=last,
            change_pct=change_pct,
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": "CN",
                "mode": "real",
                "source_interface": "pytdx.get_security_quotes",
            },
        )

    def get_history(self, symbol: str, days: int = 30) -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) != "CN":
            raise ProviderError(f"pytdx only covers CN market: {normalized}")
        api = self._api()
        code, exchange = self._tdx_code(normalized)
        # TDX stores bars in reverse chronological order, ask for more than needed
        count = min(_bounded_days(days) + 10, 800)
        with self._call_lock:
            bars = api.get_security_bars(9, exchange, code, 0, count)
        if not bars:
            raise ProviderError(f"pytdx empty history for {normalized}")
        # bars are newest-first; reverse to oldest-first
        bars = list(reversed(bars))
        items = []
        for idx, bar in enumerate(bars[-_bounded_days(days) :]):
            date_str = str(bar.get("datetime", bar.get("date", "")))
            if len(date_str) == 8:
                date_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"
            items.append(
                {
                    "day": idx + 1,
                    "date": date_str,
                    "open": _coerce_float(bar.get("open")),
                    "high": _coerce_float(bar.get("high")),
                    "low": _coerce_float(bar.get("low")),
                    "close": _coerce_float(bar.get("close")),
                    "volume": _coerce_float(bar.get("vol", 0)),
                    "amount": _coerce_float(bar.get("amount", 0)),
                }
            )
        if not items:
            raise ProviderError(f"pytdx empty history for {normalized}")
        return {
            "symbol": normalized,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "coverage": {
                "market": "CN",
                "mode": "real",
                "source_interface": "pytdx.get_security_bars",
            },
            "items": items,
        }

    def search_intel(self, symbol: str, query: str = "") -> dict:
        raise ProviderError("pytdx: intel/search not supported")

    def get_market_review(self) -> dict:
        raise ProviderError("pytdx: market review not supported")

    def get_sectors(self) -> dict:
        raise ProviderError("pytdx: sectors not supported")

    def get_financial(self, symbol: str) -> dict:
        raise ProviderError("pytdx: financial not supported")


# ──────────────────────────────────────────────
#  Baostock — 证券宝 (free Chinese stock data)
# ──────────────────────────────────────────────


class BaostockMarketDataProvider:
    """Chinese market data via Baostock (证券宝).

    Requires ``baostock`` package. Free, no API key needed.
    Covers CN market A-share quotes, history, financials.
    """

    name = "baostock"

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, Any]] = {}
        self._call_lock = threading.RLock()
        self._logged_in = False

    def is_available(self) -> bool:
        if (
            os.getenv("PYTEST_CURRENT_TEST")
            and os.getenv("WORKBENCH_TEST_ENABLE_BAOSTOCK") != "1"
        ):
            return False
        return find_spec("baostock") is not None

    def _ensure_login(self):
        if not self.is_available():
            raise ProviderError("baostock optional dependency not installed")
        if not self._logged_in:
            import baostock as bs  # type: ignore[import-not-found]

            lg = bs.login()
            if lg.error_code != "0":
                raise ProviderError(f"baostock login failed: {lg.error_msg}")
            self._logged_in = True

    def _bs_code(self, symbol: str) -> str:
        """Convert to baostock code format: 'sh.600519' or 'sz.000001'."""
        if symbol.startswith(("6", "688")):
            return f"sh.{symbol}"
        return f"sz.{symbol}"

    def get_quote(self, symbol: str) -> PriceSnapshot:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) != "CN":
            raise ProviderError(f"baostock only covers CN market: {normalized}")
        self._ensure_login()
        import baostock as bs

        code = self._bs_code(normalized)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Query recent K-line, last row is most recent
        with self._call_lock:
            rs = bs.query_history_k_data_plus(
                code,
                "close,preClose,volume,amount",
                start_date=today,
                end_date=today,
                frequency="d",
                adjustflag="3",
            )
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            # Fallback: query last 5 days
            start = (datetime.now(timezone.utc) - timedelta(days=5)).strftime(
                "%Y-%m-%d"
            )
            with self._call_lock:
                rs = bs.query_history_k_data_plus(
                    code,
                    "date,close,preClose,volume,amount",
                    start_date=start,
                    end_date=today,
                    frequency="d",
                    adjustflag="3",
                )
            while rs.next():
                rows.append(rs.get_row_data())
        if not rows:
            raise ProviderError(f"baostock empty quote for {normalized}")
        latest = rows[-1]
        col_map = {"close": 1, "preClose": 2, "volume": 3, "amount": 4}
        # If we got date column, indices shift
        offset = 1 if len(latest) > 4 else 0
        close = _coerce_float(latest[1 + offset])
        pre_close_val = _coerce_float(latest[2 + offset])
        change_pct = (
            round((close - pre_close_val) / pre_close_val * 100, 2)
            if pre_close_val
            else 0.0
        )
        return PriceSnapshot(
            last=close,
            change_pct=change_pct,
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": "CN",
                "mode": "real",
                "source_interface": "baostock.query_history_k_data_plus",
            },
        )

    def get_history(self, symbol: str, days: int = 30) -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) != "CN":
            raise ProviderError(f"baostock only covers CN market: {normalized}")
        self._ensure_login()
        import baostock as bs

        code = self._bs_code(normalized)
        end = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start = (
            datetime.now(timezone.utc)
            - timedelta(days=max(_bounded_days(days) * 2, 30))
        ).strftime("%Y-%m-%d")
        with self._call_lock:
            rs = bs.query_history_k_data_plus(
                code,
                "date,open,high,low,close,volume,amount",
                start_date=start,
                end_date=end,
                frequency="d",
                adjustflag="3",
            )
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        items = []
        for idx, r in enumerate(rows[-_bounded_days(days) :]):
            items.append(
                {
                    "day": idx + 1,
                    "date": str(r[0]),
                    "open": _coerce_float(r[1]),
                    "high": _coerce_float(r[2]),
                    "low": _coerce_float(r[3]),
                    "close": _coerce_float(r[4]),
                    "volume": _coerce_float(r[5]),
                    "amount": _coerce_float(r[6]),
                }
            )
        if not items:
            raise ProviderError(f"baostock empty history for {normalized}")
        return {
            "symbol": normalized,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "coverage": {
                "market": "CN",
                "mode": "real",
                "source_interface": "baostock.query_history_k_data_plus",
            },
            "items": items,
        }

    def search_intel(self, symbol: str, query: str = "") -> dict:
        raise ProviderError("baostock: intel/search not supported")

    def get_market_review(self) -> dict:
        raise ProviderError("baostock: market review not supported")

    def get_sectors(self) -> dict:
        raise ProviderError("baostock: sectors not supported")

    def get_financial(self, symbol: str) -> dict:
        raise ProviderError(
            "baostock: financial not supported (use baostock query_stock_basic instead)"
        )


# ──────────────────────────────────────────────
#  YFinance — Yahoo Finance (US stocks)
# ──────────────────────────────────────────────


class YFinanceMarketDataProvider:
    """US market data via yfinance.

    Requires ``yfinance`` package. Free, no API key.
    Covers US market quotes, history, financials.
    Supports: quote, history, financial.
    """

    name = "yfinance"

    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, Any]] = {}
        self._last_call_time: float = 0.0
        self._min_call_interval: float = 2.0  # yfinance rate limit behind proxy

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_call_interval:
            time.sleep(self._min_call_interval - elapsed)
        self._last_call_time = time.time()

    def is_available(self) -> bool:
        if (
            os.getenv("PYTEST_CURRENT_TEST")
            and os.getenv("WORKBENCH_TEST_ENABLE_YFINANCE") != "1"
        ):
            return False
        return find_spec("yfinance") is not None

    def _get_ticker(self, symbol: str):
        if not self.is_available():
            raise ProviderError("yfinance optional dependency not installed")
        self._rate_limit()
        import yfinance as yf  # type: ignore[import-not-found]

        return yf.Ticker(symbol)

    def _cached(self, key: str, ttl: int, loader: Callable) -> Any:
        now = time.time()
        cached = getattr(self, "_cache", {}).get(key)
        if cached and cached[0] > now:
            return cached[1]
        if not hasattr(self, "_cache"):
            self._cache: dict[str, tuple[float, Any]] = {}
        value = loader()
        self._cache[key] = (now + ttl, value)
        return value

    def get_quote(self, symbol: str) -> PriceSnapshot:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) != "US":
            raise ProviderError(f"yfinance only covers US market: {normalized}")
        ticker = self._get_ticker(normalized)

        def _load_info():
            return ticker.info or {}

        info = self._cached(f"yf_info_{normalized}", 60, _load_info)
        last = _coerce_float(
            info.get("currentPrice")
            or info.get("regularMarketPrice")
            or info.get("previousClose")
        )
        prev_close = _coerce_float(
            info.get("previousClose") or info.get("regularMarketPreviousClose") or last
        )
        change_pct = (
            round((last - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        )
        return PriceSnapshot(
            last=last,
            change_pct=change_pct,
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": "US",
                "mode": "real",
                "source_interface": "yfinance.Ticker.info",
            },
        )

    def get_history(self, symbol: str, days: int = 30) -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) != "US":
            raise ProviderError(f"yfinance only covers US market: {normalized}")
        ticker = self._get_ticker(normalized)

        def _load_hist():
            return ticker.history(period=f"{_bounded_days(days) + 5}d")

        df = self._cached(f"yf_hist_{normalized}", 300, _load_hist)
        rows = _frame_tail(df, _bounded_days(days))
        items = []
        for idx, r in enumerate(rows):
            date_str = str(r.get("Date") or r.get("date") or "")
            if not date_str and "index" in r.__class__.__name__.lower():
                date_str = (
                    str(df.index[idx])
                    if hasattr(df, "index") and idx < len(df.index)
                    else ""
                )
            items.append(
                {
                    "day": idx + 1,
                    "date": date_str[:10] if date_str else "",
                    "open": _coerce_float(r.get("Open", 0)),
                    "high": _coerce_float(r.get("High", 0)),
                    "low": _coerce_float(r.get("Low", 0)),
                    "close": _coerce_float(r.get("Close", 0)),
                    "volume": _coerce_float(r.get("Volume", 0)),
                }
            )
        if not items:
            raise ProviderError(f"yfinance empty history for {normalized}")
        return {
            "symbol": normalized,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "coverage": {
                "market": "US",
                "mode": "real",
                "source_interface": "yfinance.Ticker.history",
            },
            "items": items,
        }

    def search_intel(self, symbol: str, query: str = "") -> dict:
        raise ProviderError("yfinance: intel/search not supported")

    def get_market_review(self) -> dict:
        raise ProviderError("yfinance: market review not supported")

    def get_sectors(self) -> dict:
        raise ProviderError("yfinance: sectors not supported")

    def get_financial(self, symbol: str) -> dict:
        """Fetch US stock financials from yfinance."""
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        if str(stock["market"]) != "US":
            raise ProviderError(f"yfinance only covers US market: {normalized}")
        ticker = self._get_ticker(normalized)

        def _load_fin():
            frame = ticker.financials
            if frame is None or getattr(frame, "empty", False):
                return None
            return frame

        def _load_bs():
            frame = ticker.balance_sheet
            if frame is None or getattr(frame, "empty", False):
                return None
            return frame

        fin = self._cached(f"yf_fin_{normalized}", 86400, _load_fin)
        bs = self._cached(f"yf_bs_{normalized}", 86400, _load_bs)
        items = []

        def _row_value(frame, *labels: str) -> float:
            if frame is None or not hasattr(frame, "index"):
                return 0.0
            for label in labels:
                if label in frame.index:
                    for col in frame.columns[:1]:
                        val = _coerce_float(frame.at[label, col], default=0.0)
                        if val:
                            return val
            return 0.0

        if fin is not None and hasattr(fin, "columns"):
            for col in fin.columns[:4]:
                report_date = str(col.date()) if hasattr(col, "date") else str(col)[:10]
                items.append(
                    {
                        "report_date": report_date,
                        "report_type": "annual",
                        "revenue": _row_value(fin, "Total Revenue", "TotalRevenue"),
                        "profit": _row_value(fin, "Net Income", "Net Income Common Stockholders"),
                        "total_assets": _row_value(bs, "Total Assets"),
                        "total_liabilities": _row_value(
                            bs,
                            "Total Liabilities Net Minority Interest",
                            "Total Liab",
                        ),
                    }
                )
        if not items:
            info = self._get_ticker(normalized).info or {}
            revenue = _coerce_float(info.get("totalRevenue", 0))
            profit = _coerce_float(info.get("netIncomeToCommon", info.get("netIncome", 0)))
            if revenue <= 0 and profit <= 0:
                raise ProviderError(f"empty yfinance financials for {normalized}")
            items.append(
                {
                    "report_date": now_iso()[:10],
                    "report_type": "annual",
                    "revenue": revenue,
                    "profit": profit,
                    "total_assets": 0.0,
                    "total_liabilities": 0.0,
                }
            )
        return {
            "symbol": normalized,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "coverage": {
                "market": "US",
                "mode": "real",
                "source_interface": "yfinance.Ticker.financials",
            },
            "items": items,
        }

    def fetch_spot_snapshot(self, symbol: str) -> dict[str, Any]:
        ticker = self._get_ticker(normalize_symbol(symbol))

        def _load_info():
            return ticker.info or {}

        info = self._cached(f"yf_info_{normalize_symbol(symbol)}", 60, _load_info)
        if not info:
            return {}
        volume = _safe_float(info.get("volume"))
        avg_volume = _safe_float(info.get("averageVolume"))
        volume_ratio = (
            round(volume / avg_volume, 3)
            if volume is not None and avg_volume
            else None
        )
        return {
            "last": _safe_float(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")),
            "pe": _safe_float(info.get("trailingPE") or info.get("forwardPE")),
            "pb": _safe_float(info.get("priceToBook")),
            "turnover_pct": None,
            "amplitude_pct": None,
            "volume_ratio": volume_ratio,
            "total_market_cap": _safe_float(info.get("marketCap")),
            "float_market_cap": None,
            "industry": str(info.get("industry") or info.get("sector") or "").strip() or None,
        }

    def fetch_us_positioning(self, symbol: str) -> dict[str, Any]:
        ticker = self._get_ticker(normalize_symbol(symbol))

        def _load_info():
            return ticker.info or {}

        info = self._cached(f"yf_info_{normalize_symbol(symbol)}", 60, _load_info)
        return {
            "short_percent_of_float": _safe_float(info.get("shortPercentOfFloat")),
            "held_percent_insiders": _safe_float(info.get("heldPercentInsiders")),
            "held_percent_institutions": _safe_float(info.get("heldPercentInstitutions")),
            "float_shares": _safe_float(info.get("floatShares")),
            "note": "美股持仓/空头占比，不是 A 股筹码获利/套牢盘",
        }


# ──────────────────────────────────────────────
#  Longbridge — 长桥证券 OpenAPI
# ──────────────────────────────────────────────


class LongbridgeMarketDataProvider:
    """Multi-market data via Longbridge (长桥证券) OpenAPI.

    Requires ``longbridge`` package.
    Requires ``LONGBRIDGE_APP_KEY``, ``LONGBRIDGE_APP_SECRET`` env vars.
    Covers HK, US, CN markets (real-time quotes, history).
    """

    name = "longbridge"

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], tuple[float, Any]] = {}
        self._call_lock = threading.RLock()
        self._client: Any = None

    @property
    def _config_valid(self) -> bool:
        return (
            provider_credential("longbridge", "app_key") is not None
            and provider_credential("longbridge", "app_secret") is not None
        )

    def is_available(self) -> bool:
        if (
            os.getenv("PYTEST_CURRENT_TEST")
            and os.getenv("WORKBENCH_TEST_ENABLE_LONGBRIDGE") != "1"
        ):
            return False
        return find_spec("longbridge") is not None and self._config_valid

    def _ensure_client(self):
        if not self.is_available():
            raise ProviderError("longbridge optional dependency or credentials not set")
        if self._client is None:
            from longbridge import Config, QuoteContext  # type: ignore[import-not-found]

            config = Config(
                app_key=provider_credential("longbridge", "app_key"),
                app_secret=provider_credential("longbridge", "app_secret"),
            )
            self._client = QuoteContext(config)
        return self._client

    def _lb_symbol(self, symbol: str, market: str) -> str:
        """Convert to Longbridge symbol format."""
        if market == "CN":
            return (
                f"SHSE.{symbol}"
                if symbol.startswith(("6", "688"))
                else f"SZSE.{symbol}"
            )
        if market == "HK":
            code = symbol.removeprefix("HK")
            return f"HK.{code}"
        return symbol  # US: plain ticker

    def get_quote(self, symbol: str) -> PriceSnapshot:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        market = str(stock["market"])
        client = self._ensure_client()
        lb_sym = self._lb_symbol(normalized, market)
        with self._call_lock:
            result = client.get_quote(lb_sym)
        if not result:
            raise ProviderError(f"longbridge empty quote for {normalized}")
        return PriceSnapshot(
            last=_coerce_float(result.get("lastDone") or result.get("price")),
            change_pct=_coerce_float(result.get("changeRate", 0))
            * 100,  # LB returns 0.01 = 1%
            updated_at=now_iso(),
            source=self.name,
            degraded=False,
            coverage={
                "market": market,
                "mode": "real",
                "source_interface": "longbridge.QuoteContext.get_quote",
            },
        )

    def get_history(self, symbol: str, days: int = 30) -> dict:
        normalized = normalize_symbol(symbol)
        stock = get_stock(normalized)
        if not stock:
            raise ProviderError(f"unknown stock: {symbol}")
        market = str(stock["market"])
        client = self._ensure_client()
        lb_sym = self._lb_symbol(normalized, market)
        with self._call_lock:
            bars = client.get_candlesticks(lb_sym, count=_bounded_days(days) + 5)
        if not bars:
            raise ProviderError(f"longbridge empty history for {normalized}")
        items = []
        for idx, bar in enumerate(bars[-_bounded_days(days) :]):
            date_str = str(bar.get("timestamp") or bar.get("date") or "")
            if date_str and len(date_str) > 10:
                date_str = date_str[:10]
            items.append(
                {
                    "day": idx + 1,
                    "date": date_str,
                    "open": _coerce_float(bar.get("open")),
                    "high": _coerce_float(bar.get("high")),
                    "low": _coerce_float(bar.get("low")),
                    "close": _coerce_float(bar.get("close")),
                    "volume": _coerce_float(bar.get("volume", 0)),
                }
            )
        return {
            "symbol": normalized,
            "source": self.name,
            "updated_at": now_iso(),
            "degraded": False,
            "coverage": {
                "market": market,
                "mode": "real",
                "source_interface": "longbridge.QuoteContext.get_candlesticks",
            },
            "items": items,
        }

    def search_intel(self, symbol: str, query: str = "") -> dict:
        raise ProviderError("longbridge: intel/search not supported")

    def get_market_review(self) -> dict:
        raise ProviderError("longbridge: market review not supported")

    def get_sectors(self) -> dict:
        raise ProviderError("longbridge: sectors not supported")

    def get_financial(self, symbol: str) -> dict:
        raise ProviderError("longbridge: financial not supported")


# ──────────────────────────────────────────────
#  AKShare 子源：东方财富 / 同花顺（独立 provider id，底层仍走 AKShare）
# ──────────────────────────────────────────────


def _akshare_delegate_class(provider_id: str) -> type:
    from backend.stock_domain.providers import AkShareMarketDataProvider

    class _DelegatedAkShareProvider(AkShareMarketDataProvider):
        name = provider_id

    _DelegatedAkShareProvider.__name__ = f"{provider_id.title()}MarketDataProvider"
    return _DelegatedAkShareProvider


EastMoneyMarketDataProvider = _akshare_delegate_class("eastmoney")
TonghuashunMarketDataProvider = _akshare_delegate_class("tonghuashun")


# ──────────────────────────────────────────────
#  Provider registry — maps provider_id → class
# ──────────────────────────────────────────────

PROVIDER_CLASSES: dict[str, type] = {
    "akshare": None,  # defined in providers.py, loaded lazily
    "eastmoney": EastMoneyMarketDataProvider,
    "tonghuashun": TonghuashunMarketDataProvider,
    "tickflow": TickFlowMarketDataProvider,
    "tushare": TushareMarketDataProvider,
    "pytdx": PytdxMarketDataProvider,
    "baostock": BaostockMarketDataProvider,
    "yfinance": YFinanceMarketDataProvider,
    "longbridge": LongbridgeMarketDataProvider,
}


def _get_provider_class(provider_id: str) -> type:
    """Get provider class by id, with lazy import for akshare."""
    if provider_id == "akshare":
        from backend.stock_domain.providers import AkShareMarketDataProvider

        return AkShareMarketDataProvider
    if provider_id in ("mock", "none"):
        raise ValueError(f"provider {provider_id!r} is disabled; use a real data source")
    cls = PROVIDER_CLASSES.get(provider_id)
    if cls is None:
        raise ValueError(f"unknown provider: {provider_id}")
    return cls


def create_provider(provider_id: str) -> MarketDataProvider:
    """Create a provider instance by id."""
    cls = _get_provider_class(provider_id)
    return cls()
