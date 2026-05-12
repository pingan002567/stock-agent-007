from __future__ import annotations

from typing import Iterable, List

from backend.schemas import HoldingPosition, RiskPolicyRef, RiskPolicyRules, model_to_dict
from backend.stock_domain.catalog import get_stock


def analyze_portfolio_risk(
    holdings: Iterable[HoldingPosition],
    *,
    rules: RiskPolicyRules | dict | None = None,
    risk_policy_ref: RiskPolicyRef | dict | None = None,
) -> dict:
    resolved_rules = _coerce_rules(rules)
    resolved_ref = _coerce_ref(risk_policy_ref)
    items = list(holdings)
    risks: List[dict] = []
    sector_exposure: dict[str, float] = {}
    for item in items:
        sector = str((get_stock(item.symbol) or {}).get("sector") or "unknown")
        sector_exposure[sector] = round(sector_exposure.get(sector, 0.0) + item.weight_pct, 2)
        if item.weight_pct > resolved_rules.single_position_max_weight_pct:
            risks.append(
                {
                    "kind": "single_position_max",
                    "symbol": item.symbol,
                    "severity": "high",
                    "message": f"单股仓位超过 {resolved_rules.single_position_max_weight_pct:g}% 规则",
                }
            )
        elif item.weight_pct > resolved_rules.single_position_warning_weight_pct:
            risks.append(
                {
                    "kind": "single_position_warning",
                    "symbol": item.symbol,
                    "severity": "medium",
                    "message": f"单股仓位接近 {resolved_rules.single_position_warning_weight_pct:g}% 预警线",
                }
            )
    for sector, weight in sector_exposure.items():
        if weight > resolved_rules.sector_max_weight_pct:
            risks.append(
                {
                    "kind": "sector_exposure_max",
                    "symbol": sector,
                    "sector": sector,
                    "severity": "high",
                    "message": f"板块暴露超过 {resolved_rules.sector_max_weight_pct:g}% 规则",
                }
            )
    if any(item["severity"] == "high" for item in risks):
        decision = "先处理超限仓位与板块暴露，再评估调仓草案。"
    elif risks:
        decision = "优先关注接近上限的仓位风险，并继续观察板块暴露。"
    else:
        decision = "当前组合在活动风险策略约束内，可继续研究。"
    return {
        "risk_count": len(risks),
        "risks": risks,
        "decision": decision,
        "sector_exposure": sector_exposure,
        "thresholds": model_to_dict(resolved_rules),
        "risk_policy_ref": resolved_ref,
    }


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
