from __future__ import annotations

import json
import sqlite3
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional

from backend.schemas import (
    AgentTask,
    AuthorityLevel,
    AuditLog,
    BacktestRun,
    CopilotRunLog,
    CopilotMessage,
    CopilotSession,
    DecisionJournalEntry,
    HoldingPosition,
    MonitorRule,
    MonitorStatus,
    now_iso,
    PaperOrder,
    PaperPortfolioSnapshot,
    PreTradeReview,
    ProviderCallLog,
    Report,
    RuntimeMetricSnapshot,
    ReviewInboxState,
    ReportQualityCheck,
    ReportTemplate,
    RebalanceDraft,
    RiskPolicy,
    StockDaily,
    StockFinancial,
    StockMaster,
    StockQuote,
    StrategySpec,
    ToolExecution,
    WatchlistItem,
    EventContext,
    model_to_dict,
    now_iso,
)
from backend.persistence.repo_base import _json, _loads
from backend.persistence.repo_catalog import CatalogRepoMixin
from backend.persistence.repo_copilot import CopilotRepoMixin
from backend.persistence.repo_monitor import MonitorRepoMixin
from backend.persistence.repo_strategy import StrategyRepoMixin
from backend.persistence.repo_risk import RiskRepoMixin
from backend.persistence.repo_trading import TradingRepoMixin
from backend.persistence.repo_reports import ReportsRepoMixin
from backend.persistence.repo_config import ConfigRepoMixin


class WorkbenchRepository(
    CatalogRepoMixin,
    CopilotRepoMixin,
    MonitorRepoMixin,
    StrategyRepoMixin,
    RiskRepoMixin,
    TradingRepoMixin,
    ReportsRepoMixin,
    ConfigRepoMixin,
):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._lock = RLock()

    def seed_defaults(self) -> None:
        if not self.list_watchlist():
            for item in [
                WatchlistItem(
                    symbol="600519",
                    name="贵州茅台",
                    group="核心持仓",
                    tags=["白酒", "持仓"],
                    monitored=True,
                ),
                WatchlistItem(
                    symbol="HK00700",
                    name="腾讯控股",
                    group="事件池",
                    tags=["互联网", "港股"],
                    monitored=True,
                ),
                WatchlistItem(
                    symbol="AAPL",
                    name="Apple",
                    group="核心持仓",
                    tags=["大型科技", "美股"],
                    monitored=True,
                ),
            ]:
                self.upsert_watchlist_item(item)
        if not self.list_holdings():
            for position in [
                HoldingPosition(
                    symbol="600519",
                    name="贵州茅台",
                    quantity=100,
                    market_value=167840,
                    weight_pct=14.2,
                ),
                HoldingPosition(
                    symbol="HK00700",
                    name="腾讯控股",
                    quantity=400,
                    market_value=154720,
                    weight_pct=11.8,
                ),
                HoldingPosition(
                    symbol="AAPL",
                    name="Apple",
                    quantity=120,
                    market_value=23244,
                    weight_pct=18.6,
                ),
            ]:
                self.upsert_holding(position)
        if not self.list_risk_policies():
            policy = self.save_risk_policy(
                RiskPolicy(
                    policy_id="default-conservative",
                    name="Default Conservative",
                    description="默认保守型风险偏好；仅影响研究、提醒、回测与拟单草案。",
                )
            )
            self.activate_risk_policy(policy.policy_id or "default-conservative")
        if not self.list_strategy_specs():
            self.save_strategy_spec(
                StrategySpec(
                    strategy_id="concentration-control",
                    name="集中度控制",
                    description="对单一持仓与板块暴露做只读回测，验证是否需要降低集中度。",
                    strategy_type="concentration_control",
                    enabled=True,
                    risk_level="medium",
                    universe=["AAPL", "600519", "HK00700"],
                    parameters={"lookback_days": 30},
                    tags=["risk", "governance", "seed"],
                )
            )
        if not self.list_stock_master():
            for item in [
                StockMaster(
                    symbol="600519",
                    name="贵州茅台",
                    market="CN",
                    industry="白酒",
                    sector="消费 / 白酒",
                    aliases=["maotai", "茅台", "贵州茅台"],
                ),
                StockMaster(
                    symbol="000858",
                    name="五粮液",
                    market="CN",
                    industry="白酒",
                    sector="消费 / 白酒",
                    aliases=["五粮液", "000858", "wuliangye"],
                ),
                StockMaster(
                    symbol="688256",
                    name="寒武纪",
                    market="CN",
                    industry="半导体",
                    sector="电子 / 半导体",
                    aliases=["寒武纪", "688256", "cambricon"],
                ),
                StockMaster(
                    symbol="HK00700",
                    name="腾讯控股",
                    market="HK",
                    industry="互联网",
                    sector="港股互联网",
                    aliases=["00700", "tencent", "腾讯", "腾讯控股"],
                ),
                StockMaster(
                    symbol="AAPL",
                    name="Apple",
                    market="US",
                    industry="消费电子",
                    sector="大型科技",
                    aliases=["apple", "苹果", "aapl"],
                ),
            ]:
                self.upsert_stock_master(item)
        if not self.list_monitor_rules():
            seed_rules: list[MonitorRule] = [
                MonitorRule(
                    rule_id="seed-degraded",
                    rule_type="data_provider_degraded",
                    severity="medium",
                    enabled=True,
                    cooldown_seconds=7200,
                    title="行情/情报数据提供方降级",
                    trigger_rule="data_provider_degraded == true",
                    source="system",
                ),
                MonitorRule(
                    rule_id="seed-price-move",
                    rule_type="price_change_pct_gt",
                    severity="medium",
                    enabled=True,
                    cooldown_seconds=3600,
                    threshold=5.0,
                    title="持股涨跌幅超过 5%",
                    trigger_rule="abs(price_change_pct) > 5%",
                    source="system",
                ),
                MonitorRule(
                    rule_id="seed-hk-price-move",
                    rule_type="price_change_pct_gt",
                    severity="medium",
                    enabled=True,
                    cooldown_seconds=3600,
                    threshold=5.0,
                    title="港股涨跌幅超过 5%",
                    trigger_rule="abs(price_change_pct) > 5%",
                    source="system",
                ),
                MonitorRule(
                    rule_id="seed-us-price-move",
                    rule_type="price_change_pct_gt",
                    severity="medium",
                    enabled=True,
                    cooldown_seconds=3600,
                    threshold=5.0,
                    title="美股涨跌幅超过 5%",
                    trigger_rule="abs(price_change_pct) > 5%",
                    source="system",
                ),
            ]
            for r in seed_rules:
                self.save_monitor_rule(r)
        if not self.has_monitor_events():
            import uuid

            _ts = now_iso()
            seed_events: list[EventContext] = [
                EventContext(
                    event_id=f"seed-event-{uuid.uuid4().hex[:8]}",
                    source="system",
                    symbol="DATA",
                    title="系统启动：数据层运行正常",
                    severity="low",
                    triggered_at=_ts,
                    trigger_rule="system_startup",
                    evidence=[{"type": "system_event", "value": "workbench started"}],
                    suggested_actions=["open_stock_context"],
                ),
                EventContext(
                    event_id=f"seed-event-{uuid.uuid4().hex[:8]}",
                    source="system",
                    symbol="600519",
                    title="贵州茅台 今日价格波动关注",
                    severity="info",
                    triggered_at=_ts,
                    trigger_rule="system_startup",
                    evidence=[{"type": "seed_event", "value": "seed data"}],
                    suggested_actions=["open_stock_context"],
                ),
                EventContext(
                    event_id=f"seed-event-{uuid.uuid4().hex[:8]}",
                    source="system",
                    symbol="HK00700",
                    title="腾讯控股 今日价格波动关注",
                    severity="info",
                    triggered_at=_ts,
                    trigger_rule="system_startup",
                    evidence=[{"type": "seed_event", "value": "seed data"}],
                    suggested_actions=["open_stock_context"],
                ),
                EventContext(
                    event_id=f"seed-event-{uuid.uuid4().hex[:8]}",
                    source="system",
                    symbol="AAPL",
                    title="Apple 今日价格波动关注",
                    severity="info",
                    triggered_at=_ts,
                    trigger_rule="system_startup",
                    evidence=[{"type": "seed_event", "value": "seed data"}],
                    suggested_actions=["open_stock_context"],
                ),
            ]
            for ev in seed_events:
                self.save_monitor_event(ev)
        if not self.get_monitor_status():
            self.save_monitor_status(MonitorStatus(status="paused", auto_start=False))
        self._normalize_seed_concentration_strategy()

    def seed_report_templates(self, templates: Iterable[ReportTemplate]) -> None:
        for template in templates:
            self.save_report_template(template)

    def _normalize_seed_concentration_strategy(self) -> None:
        seed = self.get_strategy_spec("concentration-control")
        if not seed or "seed" not in seed.tags:
            return
        filtered = dict(seed.parameters)
        changed = False
        for key in (
            "max_position_weight_pct",
            "rebalance_band_pct",
            "sector_limit_pct",
        ):
            if key in filtered:
                filtered.pop(key, None)
                changed = True
        if not changed:
            return
        self.save_strategy_spec(
            seed.model_copy(
                update={
                    "parameters": filtered,
                    "version": max(seed.version + 1, 1),
                    "updated_at": now_iso(),
                }
            )
        )

    # ── Stock Master ────────────────────────────────────────────────
