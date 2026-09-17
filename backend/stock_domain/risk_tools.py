from __future__ import annotations

from typing import Iterable, List

from backend.schemas import (
    EffectiveRiskRules,
    HoldingPosition,
    RiskPolicyRef,
    RiskPolicyRules,
    model_to_dict,
)
from backend.stock_domain.catalog import get_stock, is_etf_like


def resolve_effective_rules(
    rules: RiskPolicyRules | dict | None,
    portfolio_nav: float | None = None,
) -> EffectiveRiskRules:
    """按组合 NAV 选资金分层，输出分析/拟单共用的有效阈值。"""
    resolved = _coerce_rules(rules)
    nav = max(float(portfolio_nav or 0.0), 0.0)
    tiers = sorted(
        [t for t in (resolved.capital_tiers or []) if t.max_nav is not None],
        key=lambda t: float(t.max_nav or 0.0),
    )
    matched = None
    for tier in tiers:
        if nav < float(tier.max_nav or 0.0):
            matched = tier
            break
    if matched is not None:
        label = f"nav<{int(matched.max_nav)}" if matched.max_nav else "tier"
        return EffectiveRiskRules(
            single_position_max_weight_pct=matched.single_position_max_weight_pct,
            single_position_warning_weight_pct=matched.single_position_warning_weight_pct,
            sector_max_weight_pct=matched.sector_max_weight_pct,
            min_holdings_count=matched.min_holdings_count,
            etf_max_weight_pct=resolved.etf_max_weight_pct,
            single_position_max_loss_pct_of_nav=resolved.single_position_max_loss_pct_of_nav,
            draft_valid_hours=resolved.draft_valid_hours,
            rebalance_min_delta_pct=resolved.rebalance_min_delta_pct,
            monitor_default_cooldown_seconds=resolved.monitor_default_cooldown_seconds,
            capital_tier_label=label,
            portfolio_nav=nav,
        )
    return EffectiveRiskRules(
        single_position_max_weight_pct=resolved.single_position_max_weight_pct,
        single_position_warning_weight_pct=resolved.single_position_warning_weight_pct,
        sector_max_weight_pct=resolved.sector_max_weight_pct,
        min_holdings_count=resolved.min_holdings_count,
        etf_max_weight_pct=resolved.etf_max_weight_pct,
        single_position_max_loss_pct_of_nav=resolved.single_position_max_loss_pct_of_nav,
        draft_valid_hours=resolved.draft_valid_hours,
        rebalance_min_delta_pct=resolved.rebalance_min_delta_pct,
        monitor_default_cooldown_seconds=resolved.monitor_default_cooldown_seconds,
        capital_tier_label="base",
        portfolio_nav=nav,
    )


def analyze_portfolio_risk(
    holdings: Iterable[HoldingPosition],
    *,
    rules: RiskPolicyRules | dict | None = None,
    risk_policy_ref: RiskPolicyRef | dict | None = None,
    portfolio_nav: float | None = None,
) -> dict:
    items = list(holdings)
    nav = float(portfolio_nav) if portfolio_nav is not None else sum(
        float(item.market_value or 0.0) for item in items
    )
    effective = resolve_effective_rules(rules, nav)
    risks: List[dict] = []
    sector_exposure: dict[str, float] = {}
    loss_check_skipped: list[str] = []

    for item in items:
        stock = get_stock(item.symbol) or {}
        sector = str(stock.get("sector") or "unknown")
        sector_exposure[sector] = round(sector_exposure.get(sector, 0.0) + item.weight_pct, 2)
        etf = is_etf_like(item.symbol, stock)
        max_weight = (
            effective.etf_max_weight_pct if etf else effective.single_position_max_weight_pct
        )
        warn_weight = None if etf else effective.single_position_warning_weight_pct
        kind_prefix = "etf_position" if etf else "single_position"
        if item.weight_pct > max_weight:
            risks.append(
                {
                    "kind": f"{kind_prefix}_max",
                    "symbol": item.symbol,
                    "severity": "high",
                    "message": (
                        f"{'ETF' if etf else '单股'}仓位超过 {max_weight:g}% 规则"
                    ),
                }
            )
        elif warn_weight is not None and item.weight_pct > warn_weight:
            risks.append(
                {
                    "kind": "single_position_warning",
                    "symbol": item.symbol,
                    "severity": "medium",
                    "message": f"单股仓位接近 {warn_weight:g}% 预警线",
                }
            )

        loss_pct = _position_loss_pct_of_nav(item, nav)
        if loss_pct is None:
            if nav > 0:
                loss_check_skipped.append(item.symbol)
        elif loss_pct > effective.single_position_max_loss_pct_of_nav:
            risks.append(
                {
                    "kind": "single_position_loss_of_nav",
                    "symbol": item.symbol,
                    "severity": "high",
                    "message": (
                        f"单票浮亏 {loss_pct:.2f}% NAV，超过 "
                        f"{effective.single_position_max_loss_pct_of_nav:g}% 上限"
                    ),
                    "actual_value": round(loss_pct, 4),
                    "threshold_value": effective.single_position_max_loss_pct_of_nav,
                }
            )

    for sector, weight in sector_exposure.items():
        if weight > effective.sector_max_weight_pct:
            risks.append(
                {
                    "kind": "sector_exposure_max",
                    "symbol": sector,
                    "sector": sector,
                    "severity": "high",
                    "message": f"板块暴露超过 {effective.sector_max_weight_pct:g}% 规则",
                }
            )

    holdings_count = len(items)
    if holdings_count > 0 and holdings_count < effective.min_holdings_count:
        risks.append(
            {
                "kind": "min_holdings",
                "symbol": "portfolio",
                "severity": "medium",
                "message": (
                    f"持仓数 {holdings_count} 低于最少 {effective.min_holdings_count} 只"
                ),
                "actual_value": holdings_count,
                "threshold_value": effective.min_holdings_count,
            }
        )

    if any(item["severity"] == "high" for item in risks):
        decision = "先处理超限仓位、板块暴露或单票亏损，再评估调仓草案。"
    elif risks:
        decision = "优先关注接近上限的仓位风险，并继续观察板块暴露与持仓分散度。"
    else:
        decision = "当前组合在活动风险策略约束内，可继续研究。"
    return {
        "risk_count": len(risks),
        "risks": risks,
        "decision": decision,
        "sector_exposure": sector_exposure,
        "thresholds": model_to_dict(_coerce_rules(rules)),
        "effective_rules": model_to_dict(effective),
        "capital_tier": effective.capital_tier_label,
        "portfolio_nav": round(nav, 2),
        "loss_check_skipped": loss_check_skipped,
        "risk_policy_ref": _coerce_ref(risk_policy_ref),
    }


def position_max_weight_for_symbol(
    effective: EffectiveRiskRules,
    symbol: str,
    *,
    stock: dict | None = None,
) -> float:
    info = stock if stock is not None else (get_stock(symbol) or {})
    if is_etf_like(symbol, info):
        return effective.etf_max_weight_pct
    return effective.single_position_max_weight_pct


def _position_loss_pct_of_nav(item: HoldingPosition, nav: float) -> float | None:
    """单票浮亏占 NAV 的百分比；无成本/无法估算时返回 None。"""
    if nav <= 0:
        return None
    if item.cost is not None and item.quantity is not None:
        cost = float(item.cost)
        qty = float(item.quantity)
        if cost > 0 and qty > 0:
            # cost 按单价理解：浮亏 = max(0, cost*qty - market_value)
            loss_amount = max(0.0, cost * qty - float(item.market_value or 0.0))
            return (loss_amount / nav) * 100.0
    if item.pnl_pct is not None and item.pnl_pct < 0:
        # 近似：|pnl_pct| * weight_pct / 100
        return abs(float(item.pnl_pct)) * float(item.weight_pct) / 100.0
    return None


def _coerce_rules(rules: RiskPolicyRules | dict | None) -> RiskPolicyRules:
    if isinstance(rules, RiskPolicyRules):
        return rules
    if isinstance(rules, dict):
        return RiskPolicyRules(**rules)
    return RiskPolicyRules()


def _coerce_ref(risk_policy_ref: RiskPolicyRef | dict | None) -> dict | None:
    if risk_policy_ref is None:
        return None
    if isinstance(risk_policy_ref, RiskPolicyRef):
        return model_to_dict(risk_policy_ref)
    return dict(risk_policy_ref)
