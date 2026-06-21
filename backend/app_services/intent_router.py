from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Intent:
    name: str
    skill: str
    required_authority: str
    symbol: Optional[str] = None


def _any(message: str, words: list[str]) -> bool:
    return any(word in message for word in words)


@dataclass(frozen=True)
class _Rule:
    """One routing rule. ``match`` receives (message, lowercased_text, page)."""

    name: str
    skill: str
    required_authority: str
    match: Callable[[str, str, str], bool]


# Ordered routing table — first matching rule wins. Each intent keeps its
# matching predicate next to its (skill, authority) so adding/auditing an intent
# is a single self-contained entry. Order encodes priority (e.g. 调仓 before 风险,
# specialized reviews before the generic report/research rules).
_RULES: list[_Rule] = [
    _Rule(
        "review_inbox", "risk-officer", "A3",
        lambda m, t, p: (
            "今天我需要处理什么" in m
            or "列出高优先级待办" in m
            or "解释这条待办为什么重要" in m
            or ("待办" in m and _any(m, ["高优先级", "今天", "为什么重要"]))
            or _any(m, ["标记已处理", "处理待办", "处理收件箱", "清理收件箱"])
            or ("处理" in m and "收件箱" in m)
            or ("处理" in m and "待办" in m)
        ),
    ),
    _Rule(
        "decision_journal_review", "risk-officer", "A3",
        lambda m, t, p: (
            "决策档案" in m
            or "建议链路" in m
            or ("ai" in t and _any(m, ["调仓建议", "复盘", "建议链路"]))
            or ("paper" in t and _any(m, ["调仓建议", "表现最好", "建议链路"]))
            or _any(m, ["复盘最近一次 AI 调仓建议", "哪些 paper 调仓建议表现最好", "AAPL 的建议链路是什么"])
        ),
    ),
    _Rule(
        "paper_portfolio_review", "risk-officer", "A3",
        lambda m, t, p: (
            ("paper" in t and _any(m, ["复盘", "调仓效果", "绩效归因"]))
            or ("paper portfolio" in t)
            or ("sandbox" in t and _any(m, ["复盘", "绩效"]))
        ),
    ),
    _Rule(
        "pre_trade_review", "rebalance-planner", "A4",
        lambda m, t, p: (
            _any(m, ["交易前审查", "执行前审查"])
            or ("审查" in m and _any(m, ["拟单", "草案", "执行"]))
            or ("review" in t and _any(t, ["draft", "execution", "pre-trade"]))
            or "适合执行" in m
        ),
    ),
    _Rule(
        "execution_request", "execution-agent-disabled", "A5",
        lambda m, t, p: (
            _any(m, ["真实下单", "下单", "买入", "卖出", "券商执行", "实盘"])
            or _any(t, ["real order", "trade"])
        ),
    ),
    _Rule(
        "report_write", "report-writer", "A2",
        lambda m, t, p: _any(m, ["报告", "复盘", "总结"]) or "report" in t,
    ),
    _Rule(
        "strategy_backtest", "strategy-analyst", "A3",
        lambda m, t, p: _any(m, ["回测", "策略"]) or _any(t, ["backtest", "strategy"]),
    ),
    _Rule(
        "rebalance_plan", "rebalance-planner", "A4",
        lambda m, t, p: _any(m, ["调仓", "拟单", "仓位"]),
    ),
    _Rule(
        "risk_review", "risk-officer", "A3",
        lambda m, t, p: _any(m, ["风险", "风控", "集中度"]),
    ),
    _Rule(
        "monitor_event", "stock-monitor", "A2",
        lambda m, t, p: _any(m, ["盯盘", "异动", "提醒"]),
    ),
    _Rule(
        "stock_research", "stock-researcher", "A2",
        lambda m, t, p: "research" in t or _any(m, ["研究", "深研", "分析"]),
    ),
    # Page-context fallback: on the holdings page, an otherwise-unmatched message
    # defaults to a risk review rather than generic chat.
    _Rule(
        "risk_review", "risk-officer", "A3",
        lambda m, t, p: p == "holdings",
    ),
]


class IntentRouter:
    def route(self, message: str, page: str = "overview", symbol: Optional[str] = None) -> Intent:
        text = message.lower()
        for rule in _RULES:
            if rule.match(message, text, page):
                return Intent(rule.name, rule.skill, rule.required_authority, symbol)
        return Intent("copilot_chat", "stock-researcher", "A2", symbol)
