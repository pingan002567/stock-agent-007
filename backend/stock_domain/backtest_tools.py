from __future__ import annotations

import math
from statistics import mean, pstdev
from typing import Any, Iterable

from backend.schemas import HoldingPosition, PriceSnapshot, RiskPolicy, StrategySpec, model_to_dict, now_iso
from backend.stock_domain.catalog import get_stock
from backend.stock_domain.provider_router import provider_router
from backend.stock_domain.risk_tools import analyze_portfolio_risk


DEFAULT_EXECUTION_GUARD = {
    "research_only": True,
    "auto_trade": False,
    "place_real_order_enabled": False,
}


def _calculate_returns(closes: list[float]) -> list[float]:
    """Calculate period returns from price series."""
    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            returns.append((closes[i] - closes[i - 1]) / closes[i - 1])
    return returns


def _total_return(closes: list[float]) -> float:
    """Calculate total return percentage."""
    if len(closes) < 2 or closes[0] == 0:
        return 0.0
    return (closes[-1] - closes[0]) / closes[0] * 100


def _annualized_return(total_return_pct: float, days: int) -> float:
    """Annualize total return."""
    if days <= 0:
        return 0.0
    return ((1 + total_return_pct / 100) ** (365 / days) - 1) * 100


def _max_drawdown(closes: list[float]) -> float:
    """Calculate maximum drawdown percentage."""
    if len(closes) < 2:
        return 0.0
    peak = closes[0]
    max_dd = 0.0
    for price in closes:
        if price > peak:
            peak = price
        dd = (peak - price) / peak * 100
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _sharpe_ratio(returns: list[float], risk_free_rate: float = 0.03) -> float:
    """Calculate Sharpe ratio (annualized)."""
    if len(returns) < 2:
        return 0.0
    excess_returns = [r - risk_free_rate / 252 for r in returns]
    avg_excess = mean(excess_returns)
    std = pstdev(returns)
    if std == 0:
        return 0.0
    return (avg_excess / std) * math.sqrt(252)


def _win_rate(returns: list[float]) -> float:
    """Calculate win rate (percentage of positive returns)."""
    if not returns:
        return 0.0
    wins = sum(1 for r in returns if r > 0)
    return wins / len(returns) * 100


def _calculate_enhanced_metrics(
    closes: list[float],
    days: int,
    benchmark_closes: list[float] | None = None,
) -> dict[str, Any]:
    """Calculate enhanced backtest metrics."""
    returns = _calculate_returns(closes)
    total_ret = _total_return(closes)
    ann_ret = _annualized_return(total_ret, days)
    max_dd = _max_drawdown(closes)
    sharpe = _sharpe_ratio(returns)
    win = _win_rate(returns)
    volatility = pstdev(returns) * math.sqrt(252) * 100 if len(returns) > 1 else 0.0
    
    metrics = {
        "total_return_pct": round(total_ret, 2),
        "annualized_return_pct": round(ann_ret, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio": round(sharpe, 2),
        "win_rate": round(win, 1),
        "volatility_pct": round(volatility, 2),
        "sample_size": len(closes),
        "lookback_days": days,
    }
    
    if benchmark_closes and len(benchmark_closes) >= 2:
        bench_ret = _total_return(benchmark_closes)
        metrics["benchmark_return_pct"] = round(bench_ret, 2)
        metrics["excess_return_pct"] = round(total_ret - bench_ret, 2)
    
    return metrics


def evaluate_strategy_backtest(
    spec: StrategySpec,
    *,
    holdings: Iterable[HoldingPosition],
    period: dict[str, Any] | None = None,
    universe: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
    risk_policy: RiskPolicy | None = None,
) -> dict[str, Any]:
    resolved_parameters = {**spec.parameters, **(parameters or {})}
    resolved_period = {"days": int((period or {}).get("days") or resolved_parameters.get("lookback_days") or 30)}
    resolved_period["days"] = max(5, min(int(resolved_period["days"]), 90))
    resolved_universe = _resolve_universe(spec, holdings, universe)
    sector_snapshot = provider_router.get_sectors()
    inputs, degraded_reasons = _collect_inputs(resolved_universe, resolved_period["days"])
    if sector_snapshot.get("degraded"):
        degraded_reasons.append(str(sector_snapshot.get("degraded_reason") or "sector snapshot degraded"))
    if not inputs:
        degraded_reasons.append("no symbols available for evaluation")

    strategies = {
        "concentration_control": _evaluate_concentration_control,
        "price_momentum": _evaluate_price_momentum,
        "sector_watch": _evaluate_sector_watch,
    }
    evaluator = strategies.get(spec.strategy_type, _evaluate_concentration_control)
    result = evaluator(
        spec=spec,
        holdings=list(holdings),
        period=resolved_period,
        universe=resolved_universe,
        parameters=resolved_parameters,
        inputs=inputs,
        sector_snapshot=sector_snapshot,
        risk_policy=risk_policy,
    )
    risk_summary = result["risk_summary"]
    risk_summary.setdefault("decision", analyze_portfolio_risk(holdings, rules=risk_policy.rules if risk_policy else None).get("decision"))
    evidence_refs = [
        "strategy_spec",
        "provider_router",
        "daily_history",
        "realtime_quote",
        "holding_position",
        "sector_snapshot",
    ]
    degraded = bool(degraded_reasons or result.get("degraded"))
    degraded_reason = "; ".join(dict.fromkeys(reason for reason in degraded_reasons if reason))
    return {
        "strategy_snapshot": model_to_dict(spec),
        "period": resolved_period,
        "universe": resolved_universe,
        "parameters": resolved_parameters,
        "metrics": result["metrics"],
        "signals": result["signals"],
        "risk_summary": risk_summary,
        "candidate_actions": [_ensure_read_only_action(item) for item in result["candidate_actions"]],
        "evidence_refs": evidence_refs,
        "execution_guard": dict(DEFAULT_EXECUTION_GUARD),
        "degraded": degraded,
        "degraded_reason": degraded_reason or None,
    }


def _resolve_universe(
    spec: StrategySpec,
    holdings: Iterable[HoldingPosition],
    override_universe: list[str] | None,
) -> list[str]:
    if override_universe:
        return list(dict.fromkeys(symbol.upper() for symbol in override_universe))
    if spec.universe:
        return list(dict.fromkeys(symbol.upper() for symbol in spec.universe))
    return list(dict.fromkeys(item.symbol.upper() for item in holdings))


def _collect_inputs(universe: list[str], days: int) -> tuple[list[dict[str, Any]], list[str]]:
    inputs: list[dict[str, Any]] = []
    degraded_reasons: list[str] = []
    for symbol in universe:
        quote = provider_router.get_quote(symbol)
        if quote is None:
            quote = PriceSnapshot(
                last=0.0, change_pct=0.0,
                updated_at=now_iso(), source="unavailable",
                degraded=True, degraded_reason="quote unavailable",
            )
            degraded_reasons.append(f"{symbol} quote unavailable")
        history = provider_router.get_history(symbol, days)
        closes = [float(item.get("close") or 0) for item in history.get("items", []) if item.get("close") is not None]
        if len(closes) < min(days, 5):
            degraded_reasons.append(f"{symbol} sample insufficient")
        if quote.degraded:
            degraded_reasons.append(str(quote.degraded_reason or f"{symbol} quote degraded"))
        if history.get("degraded"):
            degraded_reasons.append(str(history.get("degraded_reason") or f"{symbol} history degraded"))
        inputs.append(
            {
                "symbol": symbol,
                "quote": model_to_dict(quote),
                "history": history,
                "closes": closes,
                "stock": get_stock(symbol) or {"symbol": symbol, "sector": "unknown", "name": symbol},
            }
        )
    return inputs, degraded_reasons


def _evaluate_concentration_control(
    *,
    spec: StrategySpec,
    holdings: list[HoldingPosition],
    period: dict[str, Any],
    universe: list[str],
    parameters: dict[str, Any],
    inputs: list[dict[str, Any]],
    sector_snapshot: dict[str, Any],
    risk_policy: RiskPolicy | None = None,
) -> dict[str, Any]:
    max_weight = float(parameters.get("max_position_weight_pct") or 15)
    rebalance_band = float(parameters.get("rebalance_band_pct") or 2)
    sector_limit = float(parameters.get("sector_limit_pct") or 35)
    holdings_by_symbol = {item.symbol.upper(): item for item in holdings}
    selected = [holdings_by_symbol[symbol] for symbol in universe if symbol in holdings_by_symbol]

    breaches = [item for item in selected if item.weight_pct > max_weight]
    warnings = [item for item in selected if max_weight - rebalance_band < item.weight_pct <= max_weight]
    signals = [
        {
            "symbol": item.symbol,
            "name": item.name,
            "weight_pct": item.weight_pct,
            "threshold_pct": max_weight,
            "severity": "high" if item.weight_pct > max_weight else "medium",
            "message": "单股权重超过规则上限" if item.weight_pct > max_weight else "单股权重接近规则上限",
        }
        for item in breaches + warnings
    ]

    sector_weights: dict[str, float] = {}
    for item in selected:
        sector = str((get_stock(item.symbol) or {}).get("sector") or "unknown")
        sector_weights[sector] = round(sector_weights.get(sector, 0.0) + item.weight_pct, 2)
    for sector, weight in sector_weights.items():
        if weight > sector_limit:
            signals.append(
                {
                    "sector": sector,
                    "weight_pct": weight,
                    "threshold_pct": sector_limit,
                    "severity": "high",
                    "message": "板块暴露超过规则上限",
                }
            )

    candidate_actions = [
        {
            "symbol": item.symbol,
            "action": "reduce_exposure_review",
            "reason": f"当前 {item.weight_pct:.1f}% 高于 {max_weight:.1f}% 上限",
            "current_weight_pct": item.weight_pct,
            "target_weight_pct": max_weight,
            "delta_weight_pct": round(max_weight - item.weight_pct, 2),
        }
        for item in breaches
    ]
    for sector, weight in sector_weights.items():
        if weight > sector_limit:
            candidate_actions.append(
                {
                    "sector": sector,
                    "action": "rebalance_sector_review",
                    "reason": f"板块暴露 {weight:.1f}% 高于 {sector_limit:.1f}% 上限",
                    "sector_weight_pct": weight,
                    "target_weight_pct": sector_limit,
                }
            )

    risk_summary = analyze_portfolio_risk(selected or holdings, rules=risk_policy.rules if risk_policy else None)
    risk_summary["max_position_weight_pct"] = max((item.weight_pct for item in selected), default=0.0)
    risk_summary["sector_exposure"] = sector_weights

    # Calculate enhanced metrics from price data
    all_closes = []
    for item in inputs:
        all_closes.extend(item.get("closes", []))
    enhanced_metrics = _calculate_enhanced_metrics(all_closes, period["days"]) if all_closes else {}

    return {
        "metrics": {
            **enhanced_metrics,
            "sample_size": len(inputs),
            "positions_evaluated": len(selected),
            "rule_breach_count": len(breaches),
            "warning_count": len(warnings),
            "max_position_weight_pct": round(max((item.weight_pct for item in selected), default=0.0), 2),
            "sector_breach_count": len([weight for weight in sector_weights.values() if weight > sector_limit]),
            "lookback_days": period["days"],
        },
        "signals": signals,
        "risk_summary": risk_summary,
        "candidate_actions": candidate_actions,
    }


def _evaluate_price_momentum(
    *,
    spec: StrategySpec,
    holdings: list[HoldingPosition],
    period: dict[str, Any],
    universe: list[str],
    parameters: dict[str, Any],
    inputs: list[dict[str, Any]],
    sector_snapshot: dict[str, Any],
    risk_policy: RiskPolicy | None = None,
) -> dict[str, Any]:
    threshold = float(parameters.get("momentum_threshold_pct") or 3)
    momentum_values: list[float] = []
    signals: list[dict[str, Any]] = []
    candidate_actions: list[dict[str, Any]] = []

    for item in inputs:
        closes = item["closes"]
        if len(closes) < 2:
            continue
        momentum = round((closes[-1] / closes[0] - 1) * 100, 2)
        momentum_values.append(momentum)
        volatility = round(_volatility_pct(closes), 2)
        positive = momentum >= threshold
        signals.append(
            {
                "symbol": item["symbol"],
                "momentum_pct": momentum,
                "volatility_pct": volatility,
                "severity": "low" if positive else "medium",
                "message": "趋势延续" if positive else "动量不足，需复核假设",
            }
        )
        candidate_actions.append(
            {
                "symbol": item["symbol"],
                "action": "observe_momentum" if positive else "review_momentum_break",
                "reason": f"{item['symbol']} {period['days']} 日动量 {momentum:.2f}%",
                "confidence": "medium" if positive else "low",
            }
        )

    positive_count = len([value for value in momentum_values if value >= threshold])
    risk_summary = {
        "risk_count": len([value for value in momentum_values if value < 0]),
        "risks": [
            {
                "symbol": signal["symbol"],
                "severity": "medium",
                "message": "价格动量为负，避免直接放大敞口",
            }
            for signal in signals
            if signal["momentum_pct"] < 0
        ],
        "decision": "只读评估价格趋势，不触发真实交易。",
    }

    return {
        "metrics": {
            "sample_size": len(inputs),
            "positive_ratio": round(positive_count / len(momentum_values), 2) if momentum_values else 0.0,
            "average_momentum_pct": round(mean(momentum_values), 2) if momentum_values else 0.0,
            "max_momentum_pct": round(max(momentum_values), 2) if momentum_values else 0.0,
            "min_momentum_pct": round(min(momentum_values), 2) if momentum_values else 0.0,
            "lookback_days": period["days"],
        },
        "signals": signals,
        "risk_summary": risk_summary,
        "candidate_actions": candidate_actions,
    }


def _evaluate_sector_watch(
    *,
    spec: StrategySpec,
    holdings: list[HoldingPosition],
    period: dict[str, Any],
    universe: list[str],
    parameters: dict[str, Any],
    inputs: list[dict[str, Any]],
    sector_snapshot: dict[str, Any],
    risk_policy: RiskPolicy | None = None,
) -> dict[str, Any]:
    items = sector_snapshot.get("items", [])
    quote_change_avg = round(
        mean(float(item["quote"]["change_pct"]) for item in inputs),
        2,
    ) if inputs else 0.0
    matched_signals: list[dict[str, Any]] = []
    candidate_actions: list[dict[str, Any]] = []
    negative_count = 0

    for sector in items:
        symbols = [symbol for symbol in sector.get("symbols", []) if symbol in universe]
        if not symbols:
            continue
        signal_text = str(sector.get("signal") or "")
        severity = "high" if any(word in signal_text for word in ["转弱", "放大"]) else "medium"
        if severity == "high":
            negative_count += 1
        matched_signals.append(
            {
                "sector": sector.get("sector"),
                "signal": signal_text,
                "symbols": symbols,
                "severity": severity,
                "message": f"{sector.get('sector')} 主题监控命中 {len(symbols)} 个标的",
            }
        )
        candidate_actions.append(
            {
                "sector": sector.get("sector"),
                "symbols": symbols,
                "action": "review_sector_exposure",
                "reason": signal_text,
            }
        )

    risk_summary = {
        "risk_count": negative_count,
        "risks": [
            {
                "sector": signal["sector"],
                "severity": signal["severity"],
                "message": signal["message"],
            }
            for signal in matched_signals
            if signal["severity"] != "medium" or "转弱" in signal["signal"]
        ],
        "decision": "优先复核板块暴露与主题集中度。",
    }

    # Calculate enhanced metrics from price data
    all_closes = []
    for item in inputs:
        all_closes.extend(item.get("closes", []))
    enhanced_metrics = _calculate_enhanced_metrics(all_closes, period["days"]) if all_closes else {}

    return {
        "metrics": {
            **enhanced_metrics,
            "sample_size": len(inputs),
            "watched_sector_count": len(matched_signals),
            "negative_sector_count": negative_count,
            "average_quote_change_pct": quote_change_avg,
            "lookback_days": period["days"],
        },
        "signals": matched_signals,
        "risk_summary": risk_summary,
        "candidate_actions": candidate_actions,
    }


def _ensure_read_only_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        **action,
        "auto_trade": False,
    }


def _volatility_pct(closes: list[float]) -> float:
    if len(closes) < 2:
        return 0.0
    returns = []
    for previous, current in zip(closes, closes[1:]):
        if previous == 0:
            continue
        returns.append((current / previous - 1) * 100)
    return pstdev(returns) if returns else 0.0
