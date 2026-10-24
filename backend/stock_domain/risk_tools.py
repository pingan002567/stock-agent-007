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
            crypto_max_weight_pct=resolved.crypto_max_weight_pct,
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
        crypto_max_weight_pct=resolved.crypto_max_weight_pct,
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
    # 权重按**折算后的人民币市值**实时算：库里的 weight_pct 恒为 0（历史遗留），
    # 用它判断会导致「单票超限」永远不触发。NAV 也必须折算，否则
    # USDT/USD/HKD 会和人民币直接相加，权重与资金分层全是错的。
    from backend.stock_domain import fx as fx_service
    from backend.stock_domain.portfolio_tools import holding_currency, to_cny_amount

    fx_payload = fx_service.get_rates()
    rates = fx_service.rates_for_conversion(fx_payload)
    converted_ok = rates is not None

    cny_values: dict[str, float | None] = {}
    for item in items:
        cny_values[item.symbol] = to_cny_amount(
            float(item.market_value or 0.0), holding_currency(item), rates
        )

    if portfolio_nav is not None:
        nav = float(portfolio_nav)
    elif converted_ok:
        nav = sum(v or 0.0 for v in cny_values.values())
    else:
        # 无汇率时退回「原币直加」的旧口径，但结论里必须标明未折算
        nav = sum(float(item.market_value or 0.0) for item in items)

    effective = resolve_effective_rules(rules, nav)
    risks: List[dict] = []
    sector_exposure: dict[str, float] = {}
    loss_check_skipped: list[str] = []
    crypto_weight = 0.0

    def _weight_of(item: HoldingPosition) -> float:
        """该持仓占 NAV 的百分比。"""
        if nav <= 0:
            return 0.0
        base = cny_values.get(item.symbol)
        if base is None:
            base = float(item.market_value or 0.0)
        return round(base / nav * 100, 2)

    for item in items:
        stock = get_stock(item.symbol) or {}
        sector = str(stock.get("sector") or "unknown")
        weight = _weight_of(item)
        sector_exposure[sector] = round(sector_exposure.get(sector, 0.0) + weight, 2)
        if str(stock.get("market") or "") == "CRYPTO":
            crypto_weight = round(crypto_weight + weight, 2)
        etf = is_etf_like(item.symbol, stock)
        max_weight = (
            effective.etf_max_weight_pct if etf else effective.single_position_max_weight_pct
        )
        warn_weight = None if etf else effective.single_position_warning_weight_pct
        is_crypto = str(stock.get("market") or "") == "CRYPTO"
        kind_prefix = "etf_position" if etf else "single_position"
        label = "ETF" if etf else ("加密货币" if is_crypto else "单股")
        if weight > max_weight:
            risks.append(
                {
                    "kind": f"{kind_prefix}_max",
                    "symbol": item.symbol,
                    "severity": "high",
                    "message": (
                        f"{label}仓位 {weight:g}% 超过 {max_weight:g}% 规则"
                    ),
                    "actual_value": weight,
                    "threshold_value": max_weight,
                }
            )
        elif warn_weight is not None and item.weight_pct > warn_weight:
            risks.append(
                {
                    "kind": "single_position_warning",
                    "symbol": item.symbol,
                    "severity": "medium",
                    "message": f"{label}仓位 {weight:g}% 接近 {warn_weight:g}% 预警线",
                    "actual_value": weight,
                    "threshold_value": warn_weight,
                }
            )

        loss_pct = _position_loss_pct_of_nav(
            item,
            nav,
            value=cny_values.get(item.symbol) or float(item.market_value or 0.0),
            rate=(rates or {}).get(holding_currency(item)),
        )
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
                        f"{label}浮亏 {loss_pct:.2f}% 组合净值，超过 "
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
                    "message": (
                        f"板块 {sector} 暴露 {weight:g}% 超过 "
                        f"{effective.sector_max_weight_pct:g}% 规则"
                    ),
                    "actual_value": weight,
                    "threshold_value": effective.sector_max_weight_pct,
                }
            )

    if crypto_weight > effective.crypto_max_weight_pct:
        risks.append(
            {
                "kind": "crypto_exposure_max",
                "symbol": "crypto",
                "severity": "high",
                "message": (
                    f"加密资产合计 {crypto_weight:g}% 超过 "
                    f"{effective.crypto_max_weight_pct:g}% 上限"
                ),
                "actual_value": crypto_weight,
                "threshold_value": effective.crypto_max_weight_pct,
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
        "nav_converted": converted_ok,
        "crypto_weight_pct": crypto_weight,
        "fx": fx_payload,
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


def _position_loss_pct_of_nav(
    item: HoldingPosition,
    nav: float,
    *,
    value: float | None = None,
    rate: float | None = None,
) -> float | None:
    """单票浮亏占 NAV 的百分比；无成本/无法估算时返回 None。

    `value` 是该持仓**折算后**的市值（默认取原币市值），保证与 NAV 同币种。
    """
    if nav <= 0:
        return None
    market_value = float(value if value is not None else (item.market_value or 0.0))
    if item.cost is not None and item.quantity is not None:
        cost = float(item.cost)
        qty = float(item.quantity)
        if cost > 0 and qty > 0:
            # 成本也是原币：先折算到人民币，再和人民币市值比（否则单位混了）
            cost_value = cost * qty * (rate if rate is not None else 1.0)
            loss_amount = max(0.0, cost_value - market_value)
            return (loss_amount / nav) * 100.0
    if item.pnl_pct is not None and item.pnl_pct < 0:
        # 近似：|pnl_pct| * weight_pct / 100
        return abs(float(item.pnl_pct)) * (market_value / nav)
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
