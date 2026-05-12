from __future__ import annotations

from backend.app_services.intent_router import IntentRouter


def test_stock_research_intent():
    router = IntentRouter()
    for msg, page, sym in [
        ("研究 AAPL 的基本面", "stock", "AAPL"),
        ("分析 600519 的财务状况", "holdings", "600519"),
        ("深研腾讯的战略", "overview", "HK00700"),
        ("research AI stocks", "overview", "AAPL"),
    ]:
        intent = router.route(msg, page, sym)
        assert intent.name == "stock_research", f"failed for {msg}"
        assert intent.symbol == sym
        assert intent.required_authority == "A2"


def test_risk_review_intent():
    router = IntentRouter()
    for msg, page in [
        ("当前持仓有什么风险", "holdings"),
        ("风控扫描一下", "holdings"),
        ("检查集中度风险", "stock"),
    ]:
        intent = router.route(msg, page)
        assert intent.name == "risk_review", f"failed for {msg}"
        assert intent.skill == "risk-officer"
        assert intent.required_authority == "A3"

    intent = router.route("看看我的持仓", page="holdings")
    assert intent.name == "risk_review"


def test_rebalance_plan_intent():
    router = IntentRouter()
    for msg in [
        "生成 AAPL 调仓方案",
        "给我一个拟单",
        "调整仓位到 10%",
    ]:
        intent = router.route(msg, page="holdings", symbol="AAPL")
        assert intent.name == "rebalance_plan", f"failed for {msg}"
        assert intent.skill == "rebalance-planner"
        assert intent.required_authority == "A4"


def test_strategy_backtest_intent():
    router = IntentRouter()
    for msg in [
        "回测 concentration-control 策略",
        "策略对比一下",
        "run backtest for momentum",
    ]:
        intent = router.route(msg, page="strategy")
        assert intent.name == "strategy_backtest", f"failed for {msg}"
        assert intent.skill == "strategy-analyst"
        assert intent.required_authority == "A3"


def test_monitor_event_intent():
    router = IntentRouter()
    for msg in [
        "今天有什么异动",
        "盯盘提醒我看看",
        "给我一个提醒汇总",
    ]:
        intent = router.route(msg, page="overview")
        assert intent.name == "monitor_event", f"failed for {msg}"
        assert intent.skill == "stock-monitor"
        assert intent.required_authority == "A2"


def test_report_write_intent():
    router = IntentRouter()
    for msg in [
        "给我出一份报告",
        "复盘 AAPL 最近走势",
        "总结一下操作",
        "generate report",
    ]:
        intent = router.route(msg, page="stock", symbol="AAPL")
        assert intent.name == "report_write", f"failed for {msg}"
        assert intent.required_authority == "A2"

    monitor_msg = "复盘盯盘异动"
    intent = router.route(monitor_msg, page="monitor")
    assert intent.name == "report_write"
    assert intent.skill == "report-writer"


def test_review_inbox_intent():
    router = IntentRouter()
    for msg in [
        "今天我需要处理什么",
        "列出高优先级待办",
        "解释这条待办为什么重要",
        "高优先级待办",
    ]:
        intent = router.route(msg, page="overview")
        assert intent.name == "review_inbox", f"failed for {msg}"
        assert intent.skill == "risk-officer"
        assert intent.required_authority == "A3"


def test_decision_journal_review_intent():
    router = IntentRouter()
    for msg in [
        "打开决策档案",
        "AI 调仓建议复盘",
        "建议链路是什么",
        "哪些 paper 调仓建议表现最好",
    ]:
        intent = router.route(msg, page="journal")
        assert intent.name == "decision_journal_review", f"failed for {msg}"
        assert intent.skill == "risk-officer"
        assert intent.required_authority == "A3"


def test_paper_portfolio_review_intent():
    router = IntentRouter()
    for msg in [
        "复盘 paper 调仓效果",
        "paper 绩效归因",
        "sandbox 绩效分析",
    ]:
        intent = router.route(msg, page="overview")
        assert intent.name == "paper_portfolio_review", f"failed for {msg}"
        assert intent.skill == "risk-officer"
        assert intent.required_authority == "A3"


def test_pre_trade_review_intent():
    router = IntentRouter()
    for msg in [
        "交易前审查一下",
        "查看执行前审查",
        "审查拟单草案",
        "审查执行方案",
        "这个方案适合执行吗",
    ]:
        intent = router.route(msg, page="holdings")
        assert intent.name == "pre_trade_review", f"failed for {msg}"
        assert intent.required_authority == "A4"


def test_execution_request_intent_is_blocked():
    router = IntentRouter()
    for msg in [
        "帮我下单买入 AAPL",
        "真实下单",
        "卖出 100 股",
        "券商执行调仓",
        "实盘买入",
        "place real order",
    ]:
        intent = router.route(msg, page="holdings")
        assert intent.name == "execution_request", f"failed for {msg}"
        assert intent.skill == "execution-agent-disabled"
        assert intent.required_authority == "A5"


def test_copilot_chat_fallback():
    router = IntentRouter()
    for msg, page in [
        ("你好", "overview"),
        ("今天天气不错", "overview"),
        ("什么是股票", "overview"),
    ]:
        intent = router.route(msg, page)
        assert intent.name == "copilot_chat", f"failed for {msg}"
        assert intent.skill == "stock-researcher"
        assert intent.required_authority == "A2"


def test_holdings_page_fallback_to_risk():
    """Holdings page without explicit intent keywords falls back to risk_review."""
    router = IntentRouter()
    intent = router.route("随便看看", page="holdings")
    assert intent.name == "risk_review"
    assert intent.required_authority == "A3"


def test_empty_message_falls_to_copilot_chat():
    router = IntentRouter()
    intent = router.route("", page="overview")
    assert intent.name == "copilot_chat"


def test_symbol_preserved_through_routing():
    router = IntentRouter()
    intent = router.route("研究一下", page="stock", symbol="600519")
    assert intent.name == "stock_research"
    assert intent.symbol == "600519"

    intent = router.route("调仓", page="holdings", symbol="AAPL")
    assert intent.symbol == "AAPL"


def test_report_with_monitor_keywords():
    """report_write intent with 盯盘 keywords should route to report-writer skill.
    The actual multi-skill pipeline is resolved by copilot_service._resolve_plan."""
    router = IntentRouter()
    intent = router.route("出一个盯盘异动报告", page="monitor")
    assert intent.name == "report_write"
    assert intent.skill == "report-writer"


def test_report_with_backtest_keywords():
    router = IntentRouter()
    intent = router.route("出一个策略回测报告", page="strategy")
    assert intent.name == "report_write"


def test_report_with_risk_keywords():
    router = IntentRouter()
    intent = router.route("出一个风控报告", page="holdings")
    assert intent.name == "report_write"


def test_keyword_priority_order():
    """'调仓' keyword should win over '风险' when both present."""
    router = IntentRouter()
    intent = router.route("调仓 A 股风险如何", page="holdings")
    assert intent.name == "rebalance_plan", "调仓 should take priority"

    intent = router.route("盯盘异动报告", page="monitor")
    assert intent.name == "report_write", "report + monitor = report_write"
