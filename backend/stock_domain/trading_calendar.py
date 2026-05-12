from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


# ── helpers ──────────────────────────────────────────────────────

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return date(year, month, 1 + offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    last_day = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    diff = (last_day.weekday() - weekday) % 7
    return last_day - timedelta(days=diff)


def _nearest_weekday(d: date) -> date:
    w = d.weekday()
    if w == 5:
        return d - timedelta(days=1)
    if w == 6:
        return d + timedelta(days=1)
    return d


# ── US holidays (algorithmic, any year) ──────────────────────────

def _us_holidays(year: int) -> set[date]:
    return {
        _nearest_weekday(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _good_friday(year),
        _last_weekday(year, 5, 0),
        _nearest_weekday(date(year, 6, 19)),
        _nearest_weekday(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _nearest_weekday(date(year, 12, 25)),
    }


def _good_friday(year: int) -> date:
    """Gauss Easter algorithm — works for 1900–2099."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    easter = date(year, month, day)
    return easter - timedelta(days=2)


# ── CN holidays (AKShare API → known years fallback) ─────────────
_CN_HOLIDAYS_KNOWN: dict[int, set[date]] = {
    2024: {
        date(2024, 1, 1),
        date(2024, 2, 10), date(2024, 2, 11), date(2024, 2, 12),
        date(2024, 2, 13), date(2024, 2, 14), date(2024, 2, 15), date(2024, 2, 16), date(2024, 2, 17),
        date(2024, 4, 4), date(2024, 4, 5), date(2024, 4, 6),
        date(2024, 5, 1), date(2024, 5, 2), date(2024, 5, 3), date(2024, 5, 4), date(2024, 5, 5),
        date(2024, 6, 8), date(2024, 6, 9), date(2024, 6, 10),
        date(2024, 9, 15), date(2024, 9, 16), date(2024, 9, 17),
        date(2024, 10, 1), date(2024, 10, 2), date(2024, 10, 3),
        date(2024, 10, 4), date(2024, 10, 5), date(2024, 10, 6), date(2024, 10, 7),
    },
    2025: {
        date(2025, 1, 1),
        date(2025, 1, 28), date(2025, 1, 29), date(2025, 1, 30), date(2025, 1, 31),
        date(2025, 2, 1), date(2025, 2, 2), date(2025, 2, 3), date(2025, 2, 4),
        date(2025, 4, 4), date(2025, 4, 5), date(2025, 4, 6),
        date(2025, 5, 1), date(2025, 5, 2), date(2025, 5, 3), date(2025, 5, 4), date(2025, 5, 5),
        date(2025, 5, 31), date(2025, 6, 1), date(2025, 6, 2),
        date(2025, 10, 1), date(2025, 10, 2), date(2025, 10, 3),
        date(2025, 10, 4), date(2025, 10, 5), date(2025, 10, 6), date(2025, 10, 7), date(2025, 10, 8),
    },
    2026: {
        date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3),
        date(2026, 2, 15), date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),
        date(2026, 2, 19), date(2026, 2, 20), date(2026, 2, 21),
        date(2026, 4, 4), date(2026, 4, 5), date(2026, 4, 6),
        date(2026, 5, 1), date(2026, 5, 2), date(2026, 5, 3),
        date(2026, 6, 19), date(2026, 6, 20), date(2026, 6, 21),
        date(2026, 9, 27), date(2026, 9, 28), date(2026, 9, 29),
        date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 3),
        date(2026, 10, 4), date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8),
    },
    2027: {
        date(2027, 1, 1), date(2027, 1, 2), date(2027, 1, 3),
        date(2027, 2, 6), date(2027, 2, 7), date(2027, 2, 8), date(2027, 2, 9),
        date(2027, 2, 10), date(2027, 2, 11), date(2027, 2, 12),
        date(2027, 4, 4), date(2027, 4, 5),
        date(2027, 5, 1), date(2027, 5, 2), date(2027, 5, 3), date(2027, 5, 4), date(2027, 5, 5),
        date(2027, 6, 12), date(2027, 6, 13), date(2027, 6, 14),
        date(2027, 9, 19), date(2027, 9, 20), date(2027, 9, 21),
        date(2027, 10, 1), date(2027, 10, 2), date(2027, 10, 3),
        date(2027, 10, 4), date(2027, 10, 5), date(2027, 10, 6), date(2027, 10, 7),
    },
}


def _fetch_cn_calendar_akshare(year: int) -> set[date] | None:
    try:
        from importlib.util import find_spec
        if find_spec("akshare") is None:
            return None
        import akshare as ak
        cal = ak.tool_market_trade_date_tc()
        target = str(year)
        holidays: set[date] = set()
        import pandas as pd
        for _, row in cal.iterrows():
            trade_date_str = str(row.get("trade_date", ""))
            if not trade_date_str.startswith(target):
                continue
            if not bool(row.get("is_trading", 1)):
                try:
                    holidays.add(date.fromisoformat(trade_date_str))
                except ValueError:
                    continue
        return holidays if holidays else None
    except Exception:
        return None


@lru_cache(maxsize=8)
def _cn_holidays(year: int) -> frozenset[date]:
    api_result = _fetch_cn_calendar_akshare(year)
    if api_result is not None:
        return frozenset(api_result)
    known = _CN_HOLIDAYS_KNOWN.get(year)
    if known is not None:
        return frozenset(known)
    return frozenset()


# ── HK holidays (known years → fixed-date fallback) ──────────────

_HK_HOLIDAYS_KNOWN: dict[int, set[date]] = {
    2024: {
        date(2024, 1, 1),
        date(2024, 2, 10), date(2024, 2, 11), date(2024, 2, 12),
        date(2024, 2, 13), date(2024, 3, 29), date(2024, 4, 1),
        date(2024, 4, 4), date(2024, 5, 1), date(2024, 5, 15),
        date(2024, 6, 10), date(2024, 7, 1), date(2024, 9, 18),
        date(2024, 10, 1), date(2024, 10, 11),
        date(2024, 12, 25), date(2024, 12, 26),
    },
    2025: {
        date(2025, 1, 1), date(2025, 1, 29), date(2025, 1, 30), date(2025, 1, 31),
        date(2025, 4, 4), date(2025, 4, 18), date(2025, 4, 21),
        date(2025, 5, 1), date(2025, 5, 5), date(2025, 5, 31),
        date(2025, 7, 1), date(2025, 10, 1), date(2025, 10, 7),
        date(2025, 10, 29), date(2025, 12, 25), date(2025, 12, 26),
    },
    2026: {
        date(2026, 1, 1),
        date(2026, 2, 17), date(2026, 2, 18), date(2026, 2, 19),
        date(2026, 4, 4), date(2026, 4, 6), date(2026, 4, 7),
        date(2026, 5, 1), date(2026, 5, 25),
        date(2026, 6, 19), date(2026, 7, 1),
        date(2026, 9, 28), date(2026, 9, 29),
        date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 21),
        date(2026, 12, 25),
    },
    2027: {
        date(2027, 1, 1),
        date(2027, 2, 8), date(2027, 2, 9), date(2027, 2, 10),
        date(2027, 3, 29), date(2027, 4, 5),
        date(2027, 5, 1), date(2027, 5, 3),
        date(2027, 6, 14), date(2027, 7, 1),
        date(2027, 9, 20), date(2027, 9, 21),
        date(2027, 10, 1), date(2027, 12, 25), date(2027, 12, 26),
    },
}


@lru_cache(maxsize=8)
def _hk_holidays(year: int) -> frozenset[date]:
    known = _HK_HOLIDAYS_KNOWN.get(year)
    if known is not None:
        return frozenset(known)
    fixed: set[date] = {
        date(year, 1, 1),
        date(year, 7, 1),
        date(year, 10, 1),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    return frozenset(fixed)


# ── Public API ───────────────────────────────────────────────────


def is_trading_day(market: str | None, day: date | None = None) -> bool:
    if day is None:
        day = date.today()
    if day.weekday() >= 5:
        return False
    if market == "CN":
        return day not in _cn_holidays(day.year)
    if market == "US":
        return day not in _us_holidays(day.year)
    if market == "HK":
        return day not in _hk_holidays(day.year)
    return True


def prev_trading_day(market: str | None, day: date | None = None) -> date:
    if day is None:
        day = date.today()
    candidate = day - timedelta(days=1)
    while not is_trading_day(market, candidate):
        candidate -= timedelta(days=1)
    return candidate


def next_trading_day(market: str | None, day: date | None = None) -> date:
    if day is None:
        day = date.today()
    candidate = day + timedelta(days=1)
    while not is_trading_day(market, candidate):
        candidate += timedelta(days=1)
    return candidate


def trading_days_between(market: str | None, start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        if is_trading_day(market, current):
            days.append(current)
        current += timedelta(days=1)
    return days
