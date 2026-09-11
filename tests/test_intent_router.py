"""Stub-only keyword → skill mapping. Production routing is DeerFlow Lead Agent."""

from __future__ import annotations

from backend.agent_runtime.deerflow_client import DeerFlowClientAdapter


def _skill(message: str, page: str = "overview") -> str:
    adapter = DeerFlowClientAdapter(mode="stub")
    return adapter._stub_skill_from_message("lead-agent", message, {"page": page})


def test_stub_maps_research_risk_rebalance_and_report():
    assert _skill("研究 AAPL 的基本面", "stock") == "stock-researcher"
    assert _skill("当前持仓有什么风险", "holdings") == "risk-officer"
    assert _skill("生成 AAPL 调仓方案", "holdings") == "rebalance-planner"
    assert _skill("回测 concentration-control 策略", "strategy") == "strategy-analyst"
    assert _skill("今天有什么异动", "overview") == "stock-monitor"
    assert _skill("给我出一份报告", "stock") == "report-writer"


def test_stub_maps_inbox_journal_and_paper_before_report():
    assert _skill("今天我需要处理什么") == "risk-officer"
    assert _skill("打开决策档案") == "risk-officer"
    assert _skill("复盘 paper 调仓效果") == "risk-officer"


def test_stub_keyword_priority_rebalance_over_risk():
    assert _skill("调仓 A 股风险如何", "holdings") == "rebalance-planner"


def test_stub_holdings_page_without_keywords_falls_to_risk():
    assert _skill("随便看看", "holdings") == "risk-officer"


def test_stub_scheduled_briefing_uses_duty_path():
    msg = (
        "[定时任务·盘前简报 09-04 08:30]\n你是值班研究员。只做研究，不出买卖指令，禁止自动交易。\n"
        "用户任务：汇总自选与持仓相关的隔夜要闻。"
    )
    assert _skill(msg, "chat") == "risk-officer"
