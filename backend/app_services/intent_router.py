from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Intent:
    name: str
    skill: str
    required_authority: str
    symbol: Optional[str] = None


class IntentRouter:
    def route(self, message: str, page: str = "overview", symbol: Optional[str] = None) -> Intent:
        text = message.lower()
        wants_review_inbox = (
            "今天我需要处理什么" in message
            or "列出高优先级待办" in message
            or "解释这条待办为什么重要" in message
            or ("待办" in message and any(word in message for word in ["高优先级", "今天", "为什么重要"]))
            or any(phrase in message for phrase in ["标记已处理", "处理待办", "处理收件箱", "清理收件箱"])
            or ("处理" in message and "收件箱" in message)
            or ("处理" in message and "待办" in message)
        )
        wants_decision_journal_review = (
            "决策档案" in message
            or "建议链路" in message
            or ("ai" in text and any(word in message for word in ["调仓建议", "复盘", "建议链路"]))
            or ("paper" in text and any(word in message for word in ["调仓建议", "表现最好", "建议链路"]))
            or any(phrase in message for phrase in ["复盘最近一次 AI 调仓建议", "哪些 paper 调仓建议表现最好", "AAPL 的建议链路是什么"])
        )
        wants_paper_portfolio_review = (
            ("paper" in text and any(word in message for word in ["复盘", "调仓效果", "绩效归因"]))
            or ("paper portfolio" in text)
            or ("sandbox" in text and any(word in message for word in ["复盘", "绩效"]))
        )
        wants_report = any(word in message for word in ["报告", "复盘", "总结"]) or any(word in text for word in ["report"])
        wants_pre_trade_review = (
            any(word in message for word in ["交易前审查", "执行前审查"])
            or ("审查" in message and any(word in message for word in ["拟单", "草案", "执行"]))
            or ("review" in text and any(word in text for word in ["draft", "execution", "pre-trade"]))
            or "适合执行" in message
        )
        if wants_review_inbox:
            return Intent("review_inbox", "risk-officer", "A3", symbol)
        if wants_decision_journal_review:
            return Intent("decision_journal_review", "risk-officer", "A3", symbol)
        if wants_paper_portfolio_review:
            return Intent("paper_portfolio_review", "risk-officer", "A3", symbol)
        if wants_pre_trade_review:
            return Intent("pre_trade_review", "rebalance-planner", "A4", symbol)
        if any(word in message for word in ["真实下单", "下单", "买入", "卖出", "券商执行", "实盘"]) or any(
            word in text for word in ["real order", "trade"]
        ):
            return Intent("execution_request", "execution-agent-disabled", "A5", symbol)
        if wants_report:
            return Intent("report_write", "report-writer", "A2", symbol)
        if any(word in message for word in ["回测", "策略"]) or any(word in text for word in ["backtest", "strategy"]):
            return Intent("strategy_backtest", "strategy-analyst", "A3", symbol)
        if any(word in message for word in ["调仓", "拟单", "仓位"]):
            return Intent("rebalance_plan", "rebalance-planner", "A4", symbol)
        if any(word in message for word in ["风险", "风控", "集中度"]):
            return Intent("risk_review", "risk-officer", "A3", symbol)
        if any(word in message for word in ["盯盘", "异动", "提醒"]):
            return Intent("monitor_event", "stock-monitor", "A2", symbol)
        if "research" in text or any(word in message for word in ["研究", "深研", "分析"]):
            return Intent("stock_research", "stock-researcher", "A2", symbol)
        if page == "holdings":
            return Intent("risk_review", "risk-officer", "A3", symbol)
        return Intent("copilot_chat", "stock-researcher", "A2", symbol)
