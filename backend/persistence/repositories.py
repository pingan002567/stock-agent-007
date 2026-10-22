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
    RiskPolicyRules,
    StockDaily,
    StockFinancial,
    StockMaster,
    StockQuote,
    StrategySpec,
    ToolExecution,
    WatchlistItem,
    default_capital_tiers,
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
from backend.persistence.repo_devices import DevicesRepoMixin


class WorkbenchRepository(
    CatalogRepoMixin,
    CopilotRepoMixin,
    MonitorRepoMixin,
    StrategyRepoMixin,
    RiskRepoMixin,
    TradingRepoMixin,
    ReportsRepoMixin,
    ConfigRepoMixin,
    DevicesRepoMixin,
):
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self._lock = RLock()

    def seed_defaults(self) -> None:
        self.purge_demo_portfolio()
        if not self.list_risk_policies():
            policy = self.save_risk_policy(
                RiskPolicy(
                    policy_id="default-conservative",
                    name="Default Conservative",
                    description="默认保守型风险偏好：资金分层 + ETF 独立上限 + 单票亏损约束；仅影响研究、提醒、回测与拟单草案。",
                    rules=RiskPolicyRules(
                        single_position_max_weight_pct=15,
                        single_position_warning_weight_pct=12,
                        sector_max_weight_pct=35,
                        min_holdings_count=7,
                        etf_max_weight_pct=100,
                        single_position_max_loss_pct_of_nav=3,
                        capital_tiers=default_capital_tiers(),
                    ),
                )
            )
            self.activate_risk_policy(policy.policy_id or "default-conservative")
        else:
            self._soft_merge_default_risk_tiers()
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
                StockMaster(
                    symbol="510300",
                    name="沪深300ETF",
                    market="CN",
                    industry="ETF",
                    sector="宽基指数 / ETF",
                    aliases=["510300", "沪深300"],
                    instrument_type="etf",
                ),
                StockMaster(
                    symbol="510500",
                    name="中证500ETF",
                    market="CN",
                    industry="ETF",
                    sector="宽基指数 / ETF",
                    aliases=["510500", "中证500"],
                    instrument_type="etf",
                ),
                StockMaster(
                    symbol="512880",
                    name="证券ETF",
                    market="CN",
                    industry="ETF",
                    sector="行业主题 / ETF",
                    aliases=["512880", "证券ETF"],
                    instrument_type="etf",
                ),
                StockMaster(
                    symbol="512800",
                    name="银行ETF",
                    market="CN",
                    industry="ETF",
                    sector="行业主题 / ETF",
                    aliases=["512800", "银行ETF"],
                    instrument_type="etf",
                ),
                StockMaster(
                    symbol="SPY",
                    name="SPDR S&P 500 ETF",
                    market="US",
                    industry="ETF",
                    sector="美股宽基 / ETF",
                    aliases=["SPY", "标普500"],
                    instrument_type="etf",
                ),
            ]:
                self.upsert_stock_master(item)
        self._ensure_etf_master_rows()

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
        if not self.get_monitor_status():
            self.save_monitor_status(MonitorStatus(status="paused", auto_start=False))
        self._normalize_seed_concentration_strategy()

    def _soft_merge_default_risk_tiers(self) -> None:
        """已有 default-conservative 若缺 capital_tiers，补上出厂分层（不强制覆盖用户改过的策略）。"""
        policy = self.get_risk_policy("default-conservative")
        if not policy:
            return
        raw = model_to_dict(policy.rules) if policy.rules else {}
        # 仅当 payload 里原本没有 capital_tiers 键时合并（Pydantic 缺省会填好，需看 DB 原文）
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM risk_policy WHERE policy_id = ?",
                ("default-conservative",),
            ).fetchone()
        if not row:
            return
        from backend.persistence.repo_base import _loads

        payload = _loads(row["payload"])
        rules = payload.get("rules") or {}
        if "capital_tiers" in rules and rules.get("capital_tiers") is not None:
            return
        if policy.version > 1:
            # 用户曾编辑过：仍补缺字段，但不改 base 15/12/35
            pass
        merged = RiskPolicyRules(
            **{
                **raw,
                "capital_tiers": default_capital_tiers(),
                "etf_max_weight_pct": rules.get("etf_max_weight_pct", 100),
                "single_position_max_loss_pct_of_nav": rules.get(
                    "single_position_max_loss_pct_of_nav", 3
                ),
                "min_holdings_count": rules.get("min_holdings_count", 7),
            }
        )
        updated = policy.model_copy(
            update={
                "rules": merged,
                "updated_at": now_iso(),
                "description": policy.description
                or "默认保守型风险偏好：资金分层 + ETF 独立上限 + 单票亏损约束；仅影响研究、提醒、回测与拟单草案。",
            }
        )
        self.save_risk_policy(updated)

    def _ensure_etf_master_rows(self) -> None:
        seeds = [
            StockMaster(
                symbol="510300",
                name="沪深300ETF",
                market="CN",
                industry="ETF",
                sector="宽基指数 / ETF",
                aliases=["510300", "沪深300"],
                instrument_type="etf",
            ),
            StockMaster(
                symbol="510500",
                name="中证500ETF",
                market="CN",
                industry="ETF",
                sector="宽基指数 / ETF",
                aliases=["510500", "中证500"],
                instrument_type="etf",
            ),
            StockMaster(
                symbol="512880",
                name="证券ETF",
                market="CN",
                industry="ETF",
                sector="行业主题 / ETF",
                aliases=["512880", "证券ETF"],
                instrument_type="etf",
            ),
            StockMaster(
                symbol="512800",
                name="银行ETF",
                market="CN",
                industry="ETF",
                sector="行业主题 / ETF",
                aliases=["512800", "银行ETF"],
                instrument_type="etf",
            ),
        ]
        for item in seeds:
            existing = self.get_stock_master(item.symbol)
            if existing is None:
                self.upsert_stock_master(item)
            elif (existing.instrument_type or "stock") == "stock":
                self.upsert_stock_master(
                    existing.model_copy(
                        update={
                            "instrument_type": "etf",
                            "industry": existing.industry or "ETF",
                            "sector": existing.sector or item.sector,
                            "updated_at": now_iso(),
                        }
                    )
                )

    def seed_demo_portfolio(self) -> None:
        """Test-only sample book. Production startup never calls this."""
        if not self.list_watchlist():
            for item in [
                WatchlistItem(
                    symbol="600519",
                    name="贵州茅台",
                    group="核心持仓",
                    tags=["白酒", "持仓", "示例"],
                    monitored=True,
                ),
                WatchlistItem(
                    symbol="HK00700",
                    name="腾讯控股",
                    group="事件池",
                    tags=["互联网", "港股", "示例"],
                    monitored=True,
                ),
                WatchlistItem(
                    symbol="AAPL",
                    name="Apple",
                    group="核心持仓",
                    tags=["大型科技", "美股", "示例"],
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
            self.set_config("demo_portfolio", {"active": True, "symbols": ["600519", "HK00700", "AAPL"]})

    def purge_demo_portfolio(self) -> None:
        """Drop the first-run sample watchlist and holdings. Real books are left alone."""
        demo_symbols = {"600519", "HK00700", "AAPL"}
        for item in self.list_watchlist():
            if item.symbol.upper() in demo_symbols and "示例" in (item.tags or []):
                self.delete_watchlist_item(item.symbol)
        if self.is_demo_portfolio():
            self.clear_demo_portfolio()
        with self._lock:
            self.conn.execute(
                "DELETE FROM monitor_event WHERE evidence_json LIKE ?",
                ('%"seed_event"%',),
            )
            self.conn.commit()

    def is_demo_portfolio(self) -> bool:
        flag = self.get_config("demo_portfolio", {}) or {}
        if flag.get("cleared") or flag.get("replaced"):
            return False
        if flag.get("active"):
            return True
        if "active" in flag:
            return False
        symbols = {item.symbol.upper() for item in self.list_holdings()}
        return symbols == {"600519", "HK00700", "AAPL"}

    def mark_demo_portfolio_real(self) -> None:
        flag = dict(self.get_config("demo_portfolio", {}) or {})
        flag["active"] = False
        flag["replaced"] = True
        self.set_config("demo_portfolio", flag)

    def clear_demo_portfolio(self) -> dict[str, Any]:
        removed: list[str] = []
        for symbol in ("600519", "HK00700", "AAPL"):
            if self.delete_holding(symbol):
                removed.append(symbol)
        self.set_config("demo_portfolio", {"active": False, "cleared": True, "symbols": ["600519", "HK00700", "AAPL"]})
        return {"removed": removed, "demo": False}

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
