from __future__ import annotations

from backend.schemas import StockContext
from backend.stock_domain.market_structure import get_market_structure


def generate_stock_dashboard(context: StockContext, mode: str = "research") -> dict:
    risk_level = context.ai_state.risk_label
    weight = context.holding.weight_pct
    counter_reasons = ["provider-router 可能回退到 mock_adapter，涉及实时性判断时需要复核。"]
    if context.price.degraded_reason:
        counter_reasons.append(f"当前数据降级原因：{context.price.degraded_reason}")
    else:
        counter_reasons.append("如需优先尝试真实 quote/history/intel 数据，可安装 optional AKShare extra。")
    
    risk_bars = [
        {"name": "波动", "value": 62 if context.price.change_pct >= 0 else 74},
        {"name": "新闻", "value": 58 if context.symbol != "HK00700" else 76},
        {"name": "仓位", "value": min(95, int(weight * 5)) if weight else 35},
        {"name": "流动性", "value": 44 if context.market == "CN" else 52},
        {"name": "回撤", "value": 55 if "高" in risk_level else 42},
    ]
    
    # 生成持仓建议
    holding_advice = _generate_holding_advice(context)
    market_structure = get_market_structure(context.symbol)
    technical_analysis = _generate_technical_analysis(context, market_structure)
    
    # 生成基本面分析
    fundamental_analysis = _generate_fundamental_analysis(context)
    
    return {
        "symbol": context.symbol,
        "mode": mode,
        "conclusion": f"{context.name} 当前判断：{context.ai_state.stance}",
        "confidence": context.ai_state.confidence,
        "reasons": [
            f"风险标签为 {context.ai_state.risk_label}",
            f"行业板块：{context.sector}",
            f"当前报价源：{context.price.source}；quote/history/intel 统一通过 provider-router 输出。",
        ],
        "counter_reasons": counter_reasons,
        "risk_bars": risk_bars,
        "stance_summary": {
            "label": context.ai_state.stance,
            "risk_label": risk_level,
            "valid_for": "1 个交易日",
            "authority_level": "A2" if mode == "research" else "A4",
        },
        "holding_advice": holding_advice,
        "technical_analysis": technical_analysis,
        "fundamental_analysis": fundamental_analysis,
        "market_structure": market_structure,
        "followups": ["追问基本面变化", "比较同板块标的", "生成持仓影响"],
        "disclaimer": "仅供研究，不构成投资建议。",
    }


def _generate_holding_advice(context: StockContext) -> dict:
    """生成持仓建议"""
    weight = context.holding.weight_pct
    risk_level = context.ai_state.risk_label
    
    # 根据风险等级和权重生成建议
    if weight and weight > 25:
        suggested_weight = 20
        action = "减持"
        reason = f"当前仓位 {weight}% 超过 25% 上限，建议减持至 {suggested_weight}%"
    elif weight and weight > 15:
        suggested_weight = weight
        action = "持有"
        reason = f"当前仓位 {weight}% 在合理范围内"
    else:
        suggested_weight = min((weight or 0) + 5, 15)
        action = "可增持"
        reason = f"当前仓位 {weight}%，可适当增持至 {suggested_weight}%"
    
    return {
        "current_weight": weight,
        "suggested_weight": suggested_weight,
        "action": action,
        "reason": reason,
        "risk_level": risk_level,
    }


def _generate_technical_analysis(context: StockContext, market_structure: dict | None = None) -> dict:
    """技术面：消费 get_market_structure 的 L0，不再用现价 ±5% 假支撑。"""
    change_pct = context.price.change_pct
    ms = market_structure or {}
    tech = ms.get("technical") if isinstance(ms.get("technical"), dict) else {}

    ma_stack = tech.get("ma_stack")
    rsi = tech.get("rsi14")
    if ma_stack == "bullish" or (isinstance(rsi, (int, float)) and rsi >= 60):
        trend = "偏多"
        momentum = "强" if isinstance(rsi, (int, float)) and rsi >= 70 else "中"
    elif ma_stack == "bearish" or (isinstance(rsi, (int, float)) and rsi <= 40):
        trend = "偏空"
        momentum = "强" if isinstance(rsi, (int, float)) and rsi <= 30 else "中"
    elif change_pct >= 1:
        trend = "温和上涨"
        momentum = "中"
    elif change_pct <= -1:
        trend = "温和下跌"
        momentum = "弱"
    else:
        trend = "横盘整理"
        momentum = "弱"

    support = tech.get("support_20")
    resistance = tech.get("resistance_20")
    return {
        "trend": trend,
        "momentum": momentum,
        "change_pct": change_pct,
        "support": support,
        "resistance": resistance,
        "ma5": tech.get("ma5"),
        "ma10": tech.get("ma10"),
        "ma20": tech.get("ma20"),
        "ma60": tech.get("ma60"),
        "rsi14": rsi,
        "volume_ratio": tech.get("volume_ratio"),
        "degraded": bool(tech.get("degraded")),
        "missing": tech.get("missing") or [],
        "source": "market_structure",
    }


def _generate_fundamental_analysis(context: StockContext) -> dict:
    """生成基本面分析"""
    return {
        "sector": context.sector,
        "industry": context.industry,
        "market": context.market,
        "market_cap": None,  # 需要从其他数据源获取
        "pe_ratio": None,  # 需要从其他数据源获取
        "dividend_yield": None,  # 需要从其他数据源获取
    }
