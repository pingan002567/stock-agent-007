from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.api.deps import get_services
from backend.bootstrap import AppServices
from pydantic import BaseModel, Field

from backend.schemas import HoldingPosition, RebalanceDraftRequest, model_to_dict
from backend.stock_domain.catalog import get_stock, normalize_symbol
from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.portfolio_tools import _MARKET_CURRENCY
from backend.stock_domain import fx as fx_service
from backend.stock_domain.portfolio_tools import (
    holding_currency,
    mark_to_market,
    read_cash_buckets,
    read_cash_for,
    summarize_portfolio,
    to_cny_amount,
    write_available_cash,
)
from backend.persistence.repo_cash import (
    CashNotRecorded,
    InsufficientCash,
    InsufficientHolding,
)

router = APIRouter(prefix="/api/holdings", tags=["holdings"])


class AvailableCashUpdate(BaseModel):
    amount: float | None = Field(default=None, description="可用资金；null 表示清空该币种记录")
    currency: str | None = Field(default=None, description="币种，缺省 CNY")


def _fx_rates() -> tuple[dict | None, dict]:
    """当日汇率（按日缓存）。返回 (折算系数, 原始 payload)。"""
    payload = fx_service.get_rates()
    return fx_service.rates_for_conversion(payload), payload


def _portfolio_summary(services: AppServices, holdings: list[HoldingPosition]) -> dict:
    rates, payload = _fx_rates()
    return summarize_portfolio(
        holdings,
        cash_buckets=read_cash_buckets(services.repo),
        rates=rates,
        fx=payload,
    )


def _presented_holdings(services: AppServices) -> tuple[list[dict], list[HoldingPosition], int]:
    """Attach a quote and compute market value / unrealized P&L for the response."""
    from backend.stock_domain.provider_router import provider_router

    rates, _fx_payload = _fx_rates()
    items: list[dict] = []
    valued: list[HoldingPosition] = []
    degraded_count = 0
    for item in services.repo.list_holdings():
        d = model_to_dict(item)
        stock = get_stock(item.symbol)
        d["market"] = str(stock["market"]) if stock else ""
        last = None
        try:
            quote = provider_router.get_quote(item.symbol)
            coverage = quote.coverage if isinstance(quote.coverage, dict) else {}
            last = quote.last if quote.last else None
            d["quote"] = {
                "last": last,
                "change_pct": None if last is None else quote.change_pct,
                "updated_at": quote.updated_at,
                "degraded": bool(quote.degraded) or last is None,
                "degraded_reason": quote.degraded_reason,
                "stale": bool(coverage.get("stale")),
                "from_cache": bool(coverage.get("from_cache")),
                "channel": "mode_b",
            }
            if d["quote"]["degraded"]:
                degraded_count += 1
        except Exception as exc:
            d["quote"] = {
                "last": None,
                "change_pct": None,
                "degraded": True,
                "degraded_reason": str(exc)[:160],
                "channel": "mode_b",
            }
            degraded_count += 1
        native, pnl_amount, pnl_pct = mark_to_market(item, None if d["quote"]["degraded"] else last)
        currency = holding_currency(item)
        d["currency"] = currency
        # 原币市值（真相）；折算值只在能拿到汇率时给，拿不到就是 None → 前端显示「—」
        d["market_value_native"] = native
        d["market_value"] = to_cny_amount(native, currency, rates)
        d["pnl_amount"] = pnl_amount       # 价格损益，原币口径，不受汇率影响
        d["pnl_pct"] = pnl_pct
        valued.append(item.model_copy(update={"market_value": native, "pnl_pct": pnl_pct, "currency": currency}))
        items.append(d)
    return items, valued, degraded_count


@router.get("")
def list_holdings(request: Request, services: AppServices = Depends(get_services)):
    """Holdings list (Mode B). Attach quote cache status so UI can show degraded, not blank."""
    items, valued, degraded_count = _presented_holdings(services)
    return {
        "summary": _portfolio_summary(services, valued),
        "items": items,
        "demo": services.repo.is_demo_portfolio(),
        "quotes_degraded_count": degraded_count,
        "quotes_total": len(items),
        "channel": "mode_b",
        "fx": _fx_rates()[1],
    }


class HoldingUpsert(BaseModel):
    """新增/修改单笔持仓。市值按「现价优先、否则成本」计算，**存原币**。"""

    symbol: str
    quantity: float = Field(gt=0, description="数量（股 / 枚），币支持小数")
    cost: float | None = Field(default=None, ge=0, description="原币成本价")
    currency: str | None = Field(default=None, description="原币币种；留空按 market 推断")


@router.post("")
def add_or_update_holding(
    payload: HoldingUpsert,
    request: Request,
    services: AppServices = Depends(get_services),
):
    """加一笔持仓（同一个 symbol 再提交就是覆盖数量/成本）。"""
    symbol = normalize_symbol(payload.symbol)
    stock = get_stock(symbol)
    if stock is None:
        raise HTTPException(status_code=400, detail=f"未知标的：{payload.symbol}")
    market = str(stock.get("market") or "")
    currency = (payload.currency or "").upper() or _MARKET_CURRENCY.get(market, "CNY")

    last: float | None = None
    try:
        quote = provider_router.get_quote(symbol)
        if not quote.degraded and quote.last:
            last = float(quote.last)
    except Exception:  # noqa: BLE001 - 拿不到报价就用成本价
        last = None

    unit_price = last if last and last > 0 else (payload.cost or 0.0)
    if unit_price <= 0:
        raise HTTPException(status_code=400, detail="需要现价或成本价至少一个才能算市值")

    item = HoldingPosition(
        symbol=symbol,
        name=str(stock.get("name") or symbol),
        quantity=float(payload.quantity),
        market_value=round(unit_price * float(payload.quantity), 2),
        weight_pct=0.0,
        cost=payload.cost,
        currency=currency,
    )
    services.repo.upsert_holding(item)
    services.repo.mark_demo_portfolio_real()
    services.audit_service.record(
        "holding added", f"{symbol} qty={payload.quantity} ccy={currency}"
    )
    return list_holdings(request=request, services=services)


class TradeRequest(BaseModel):
    """一笔买入/卖出。成交价必填（扣现金要按真实成交价，不是实时价）。"""

    action: str = Field(pattern="^(buy|sell)$")
    symbol: str
    quantity: float = Field(gt=0, description="数量（股 / 枚）")
    fill_price: float = Field(gt=0, description="成交价（原币）")
    fee: float = Field(default=0.0, ge=0, description="手续费（原币）")
    currency: str | None = Field(default=None, description="结算币种；留空按市场推断")
    idempotency_key: str | None = Field(default=None, description="幂等键，重放不重复扣款")
    note: str | None = None


@router.post("/trades")
def execute_trade(payload: TradeRequest, request: Request, services: AppServices = Depends(get_services)):
    """买入/卖出：**原子地**改现金与持仓，现金不足直接拒绝（不允许透支）。

    - 现金按币种扣：A 股扣 CNY，港股扣 HKD，美股扣 USD，加密扣 USDT
    - 该币种现金没记录过 → 409（先设置可用现金，避免"看起来扣了其实没扣"）
    - 持仓不足 → 409
    - 带 `idempotency_key` 重放 → 原样返回上次结果，不重复扣
    """
    symbol = normalize_symbol(payload.symbol)
    stock = get_stock(symbol)
    if stock is None:
        raise HTTPException(status_code=400, detail=f"未知标的：{payload.symbol}")
    market = str(stock.get("market") or "")
    currency = (payload.currency or "").upper() or _MARKET_CURRENCY.get(market, "CNY")

    if not hasattr(services.repo, "execute_trade"):
        raise HTTPException(status_code=501, detail="当前仓储不支持交易记账")

    try:
        result = services.repo.execute_trade(
            symbol=symbol,
            name=str(stock.get("name") or symbol),
            quantity=payload.quantity,
            fill_price=payload.fill_price,
            currency=currency,
            is_buy=payload.action == "buy",
            fee=payload.fee,
            idempotency_key=payload.idempotency_key,
            note=payload.note,
        )
    except CashNotRecorded as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "cash_not_recorded",
                "message": str(exc),
                "currency": exc.currency,
            },
        ) from exc
    except InsufficientCash as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "insufficient_cash",
                "message": str(exc),
                "currency": exc.currency,
                "required": round(exc.required, 2),
                "available": round(exc.available, 2),
                "shortfall": round(exc.required - exc.available, 2),
            },
        ) from exc
    except InsufficientHolding as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "insufficient_holding",
                "message": str(exc),
                "symbol": exc.symbol,
                "held": exc.held,
                "requested": exc.requested,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    services.audit_service.record(
        f"holding {payload.action}",
        f"{symbol} qty={payload.quantity} @{payload.fill_price} fee={payload.fee} ccy={currency}",
    )
    _items, valued, _degraded = _presented_holdings(services)
    return {
        "trade": result,
        "currency": currency,
        "available_cash": read_cash_for(services.repo, currency),
        "summary": _portfolio_summary(services, valued),
    }


@router.post("/available-cash")
def set_available_cash(payload: AvailableCashUpdate, request: Request, services: AppServices = Depends(get_services)):
    """设置某个币种的可用现金（会写一条 adjust 流水，可回溯）。"""
    currency = (payload.currency or "CNY").upper()
    try:
        if hasattr(services.repo, "set_cash_bucket"):
            result = services.repo.set_cash_bucket(currency, payload.amount, note="manual set")
            amount = result.get("balance_after")
        else:  # 旧仓储兜底
            amount = write_available_cash(services.repo, payload.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _items, valued, _degraded = _presented_holdings(services)
    services.audit_service.record(
        "holdings available cash updated",
        f"{currency} " + ("cleared" if amount is None else f"amount={amount}"),
    )
    return {
        "available_cash": read_cash_for(services.repo, currency),
        "currency": currency,
        "summary": _portfolio_summary(services, valued),
    }


class CashCalibration(BaseModel):
    """多币种一次性校准（首次建账 / 与券商对账后修正）。"""

    amounts: dict[str, float] = Field(
        default_factory=dict, description="币种 → 金额；只写传入的币种，未传的保持不变"
    )
    note: str | None = Field(default=None, description="校准原因，写进流水，便于回溯")


@router.post("/cash-calibration")
def calibrate_cash(payload: CashCalibration, request: Request, services: AppServices = Depends(get_services)):
    """把多个币种的可用现金一次性设成实际值，每个币种写一条 `adjust` 流水。"""
    amounts = {
        str(ccy).upper(): float(amount)
        for ccy, amount in (payload.amounts or {}).items()
        if amount is not None
    }
    if not amounts:
        raise HTTPException(status_code=400, detail="没有要校准的币种")
    for ccy, amount in amounts.items():
        if amount < 0:
            raise HTTPException(status_code=400, detail=f"{ccy} 可用资金不能为负")
    try:
        if hasattr(services.repo, "calibrate_cash"):
            services.repo.calibrate_cash(amounts, note=payload.note or "manual calibrate")
        else:
            for ccy, amount in amounts.items():
                write_available_cash(services.repo, amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    services.audit_service.record(
        "holdings cash calibrated",
        ", ".join(f"{ccy}={amount:.2f}" for ccy, amount in sorted(amounts.items())),
    )
    _items, valued, _degraded = _presented_holdings(services)
    return {
        "cash_by_currency": read_cash_buckets(services.repo) or {},
        "summary": _portfolio_summary(services, valued),
    }


@router.get("/performance")
def daily_performance(services: AppServices = Depends(get_services)):
    """盘后表现：今日收益（日K口径）/ 贡献 / 现金变动 / 基准对比 / 回撤 / 距成本。

    给盘后报告和前端用；**不看 quote.change_pct**（盘后它常是 0）。
    """
    from backend.stock_domain.performance_tools import build_daily_performance

    return build_daily_performance(services)


@router.get("/cash-ledger.csv")
def cash_ledger_csv(limit: int = 500, services: AppServices = Depends(get_services)):
    """资金流水导出（CSV，带 BOM 便于 Excel 直接打开）。"""
    rows = services.repo.list_cash_ledger(limit=limit) if hasattr(services.repo, "list_cash_ledger") else []
    header = ["created_at", "currency", "delta", "balance_after", "reason", "ref_type", "ref_id", "note"]
    lines = [",".join(header)]
    for row in rows:
        values = []
        for key in header:
            raw = row.get(key)
            text = "" if raw is None else str(raw)
            values.append('"' + text.replace('"', '""') + '"')
        lines.append(",".join(values))
    body = "\ufeff" + "\n".join(lines) + "\n"
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="cash-ledger.csv"'},
    )


@router.get("/cash-ledger")
def cash_ledger(limit: int = 100, services: AppServices = Depends(get_services)):
    """资金流水：每笔买入/卖出/校准的 delta 与余额，用来对账。"""
    rows = services.repo.list_cash_ledger(limit=limit) if hasattr(services.repo, "list_cash_ledger") else []
    return {"items": rows, "cash_by_currency": read_cash_buckets(services.repo) or {}}


@router.post("/import-preview")
def import_preview(items: List[HoldingPosition]):
    return {"valid": True, "count": len(items), "items": [model_to_dict(item) for item in items]}


@router.post("/import-confirm")
def import_confirm(items: List[HoldingPosition], request: Request, services: AppServices = Depends(get_services)):
    saved = [services.repo.upsert_holding(item) for item in items]
    services.repo.mark_demo_portfolio_real()
    services.audit_service.record("holdings import confirmed", f"count={len(saved)}")
    return {"imported": len(saved), "items": [model_to_dict(item) for item in saved]}


@router.post("/clear-demo")
def clear_demo_holdings(request: Request, services: AppServices = Depends(get_services)):
    if not services.repo.is_demo_portfolio():
        return {"ok": True, "demo": False, "removed": []}
    result = services.repo.clear_demo_portfolio()
    services.audit_service.record("demo holdings cleared", f"removed={len(result['removed'])}")
    return {"ok": True, **result}


@router.get("/risk")
def holdings_risk(request: Request, services: AppServices = Depends(get_services)):
    risk = services.risk_policy_service.analyze_portfolio_risk(services.repo.list_holdings())
    services.audit_service.record("holdings risk review", risk["decision"])
    return risk


@router.post("/rebalance-draft")
def rebalance_draft(payload: RebalanceDraftRequest, request: Request, services: AppServices = Depends(get_services)):
    draft = services.rebalance_draft_service.create(payload, source_mode="http")
    return services.rebalance_draft_service.to_decision_summary(draft)
