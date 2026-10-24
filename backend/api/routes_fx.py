from __future__ import annotations

from fastapi import APIRouter, Query

from backend.stock_domain import fx

router = APIRouter(prefix="/api/fx", tags=["fx"])


@router.get("/rates")
def fx_rates(refresh: bool = Query(default=False)):
    """当日汇率（按日缓存）。降级时 degraded=true，调用方必须显示「—」而不是 1:1 硬算。"""
    payload = fx.get_rates(refresh=refresh)
    rates = fx.rates_for_conversion(payload)
    return {
        **payload,
        # 1 单位外币 = ? CNY；降级时为 null
        "to_cny": rates,
        "currencies": list(fx.SUPPORTED_CURRENCIES),
    }
