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


def _json(data: Any) -> str:
    if hasattr(data, "json") or hasattr(data, "model_dump"):
        data = model_to_dict(data)
    return json.dumps(data, ensure_ascii=False)


def _loads(raw: str) -> Dict[str, Any]:
    return json.loads(raw)


class WorkbenchRepository:
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

    def list_watchlist(self) -> List[WatchlistItem]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM watchlist_item ORDER BY position, symbol"
            ).fetchall()
        return [
            WatchlistItem(
                symbol=row["symbol"],
                name=row["name"],
                group=row["group_name"],
                tags=json.loads(row["tags"] or "[]"),
                monitored=bool(row["monitored"]),
            )
            for row in rows
        ]

    def upsert_watchlist_item(self, item: WatchlistItem) -> WatchlistItem:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO watchlist_item(symbol, name, group_name, tags, monitored, position)
                VALUES (?, ?, ?, ?, ?, COALESCE((SELECT MAX(position) FROM watchlist_item), 0) + 1)
                ON CONFLICT(symbol) DO UPDATE SET
                  name=excluded.name,
                  group_name=excluded.group_name,
                  tags=excluded.tags,
                  monitored=excluded.monitored
                """,
                (
                    item.symbol.upper(),
                    item.name,
                    item.group,
                    _json(item.tags),
                    int(item.monitored),
                ),
            )
            self.conn.commit()
        return item

    def update_watchlist_position(self, symbol: str, pos: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE watchlist_item SET position = ? WHERE symbol = ?",
                (pos, symbol.upper()),
            )
            self.conn.commit()

    def list_watchlist_groups(self) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM watchlist_group ORDER BY sort_order, name"
            ).fetchall()
        return [{"name": r["name"], "color": r["color"], "sort_order": r["sort_order"]} for r in rows]

    def upsert_watchlist_group(self, name: str, color: str = "#6366f1") -> None:
        with self._lock:
            self.conn.execute(
                """INSERT INTO watchlist_group(name, color, sort_order)
                   VALUES (?, ?, COALESCE((SELECT MAX(sort_order) FROM watchlist_group), 0) + 1)
                   ON CONFLICT(name) DO UPDATE SET color=excluded.color""",
                (name, color),
            )
            self.conn.commit()

    def rename_watchlist_group(self, old_name: str, new_name: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE watchlist_group SET name = ? WHERE name = ?", (new_name, old_name))
            self.conn.execute("UPDATE watchlist_item SET group_name = ? WHERE group_name = ?", (new_name, old_name))
            self.conn.commit()

    def delete_watchlist_group(self, name: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE watchlist_item SET group_name = '默认' WHERE group_name = ?", (name,))
            self.conn.execute("DELETE FROM watchlist_group WHERE name = ?", (name,))
            self.conn.commit()

    def update_group_sort(self, name: str, sort_order: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE watchlist_group SET sort_order = ? WHERE name = ?",
                (sort_order, name),
            )
            self.conn.commit()

    def delete_watchlist_item(self, symbol: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM watchlist_item WHERE symbol = ?", (symbol.upper(),)
            )
            self.conn.commit()
        return cur.rowcount > 0

    def list_holdings(self) -> List[HoldingPosition]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM holding_position ORDER BY weight_pct DESC"
            ).fetchall()
        return [HoldingPosition(**dict(row)) for row in rows]

    def upsert_holding(self, position: HoldingPosition) -> HoldingPosition:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO holding_position(symbol, name, quantity, market_value, weight_pct, cost, pnl_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                  name=excluded.name,
                  quantity=excluded.quantity,
                  market_value=excluded.market_value,
                  weight_pct=excluded.weight_pct,
                  cost=excluded.cost,
                  pnl_pct=excluded.pnl_pct
                """,
                (
                    position.symbol.upper(),
                    position.name,
                    position.quantity,
                    position.market_value,
                    position.weight_pct,
                    position.cost,
                    position.pnl_pct,
                ),
            )
            self.conn.commit()
        return position

    def save_task(self, task: AgentTask) -> AgentTask:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO agent_task(task_id, payload, created_at)
                VALUES (?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET payload=excluded.payload
                """,
                (task.task_id, _json(task), task.created_at),
            )
            self.conn.commit()
        return task

    def save_provider_call_log(self, log: ProviderCallLog) -> ProviderCallLog:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO provider_call_log(
                  call_id, capability, market, symbol, provider, fallback_provider,
                  status, degraded_reason, duration_ms, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.call_id,
                    log.capability,
                    log.market,
                    log.symbol,
                    log.provider,
                    log.fallback_provider,
                    log.status,
                    log.degraded_reason,
                    log.duration_ms,
                    log.created_at,
                    _json(log.payload),
                ),
            )
            self.conn.commit()
        return log

    def list_provider_call_logs(
        self, *, limit: int = 100, capability: str | None = None
    ) -> List[ProviderCallLog]:
        query = "SELECT * FROM provider_call_log"
        params: list[Any] = []
        if capability:
            query += " WHERE capability = ?"
            params.append(capability)
        query += " ORDER BY created_at DESC, call_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [
            ProviderCallLog(
                call_id=row["call_id"],
                capability=row["capability"],
                market=row["market"],
                symbol=row["symbol"],
                provider=row["provider"],
                fallback_provider=row["fallback_provider"],
                status=row["status"],
                degraded_reason=row["degraded_reason"],
                duration_ms=row["duration_ms"],
                created_at=row["created_at"],
                payload=_loads(row["payload"]),
            )
            for row in rows
        ]

    def cleanup_provider_call_logs(self, *, keep_days: int = 7) -> int:
        import datetime as _dt
        cutoff = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=keep_days)).isoformat()
        with self._lock:
            cur = self.conn.execute("DELETE FROM provider_call_log WHERE created_at < ?", (cutoff,))
            return cur.rowcount

    def save_copilot_run_log(self, log: CopilotRunLog) -> CopilotRunLog:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO copilot_run_log(
                  run_id, session_id, task_id, mode, active_client, model_name, status,
                  error_category, runtime_error, tool_call_count, usage_input_tokens,
                  usage_output_tokens, cost, latency_ms, started_at,
                  created_at, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                  session_id=excluded.session_id,
                  task_id=excluded.task_id,
                  mode=excluded.mode,
                  active_client=excluded.active_client,
                  model_name=excluded.model_name,
                  status=excluded.status,
                  error_category=excluded.error_category,
                  runtime_error=excluded.runtime_error,
                  tool_call_count=excluded.tool_call_count,
                  usage_input_tokens=excluded.usage_input_tokens,
                  usage_output_tokens=excluded.usage_output_tokens,
                  cost=excluded.cost,
                  latency_ms=excluded.latency_ms,
                  started_at=excluded.started_at,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (
                    log.run_id,
                    log.session_id,
                    log.task_id,
                    log.mode,
                    log.active_client,
                    log.model_name,
                    log.status,
                    log.error_category,
                    log.runtime_error,
                    log.tool_call_count,
                    log.usage_input_tokens,
                    log.usage_output_tokens,
                    log.cost,
                    log.latency_ms,
                    log.started_at,
                    log.created_at,
                    log.updated_at,
                    _json(log.payload),
                ),
            )
            self.conn.commit()
        return log

    def list_copilot_run_logs(
        self, *, limit: int = 100, status: str | None = None
    ) -> List[CopilotRunLog]:
        query = "SELECT * FROM copilot_run_log"
        params: list[Any] = []
        if status:
            query += " WHERE status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC, run_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [
            CopilotRunLog(
                run_id=row["run_id"],
                session_id=row["session_id"],
                task_id=row["task_id"],
                mode=row["mode"],
                active_client=row["active_client"],
                model_name=row["model_name"],
                status=row["status"],
                error_category=row["error_category"],
                runtime_error=row["runtime_error"],
                tool_call_count=row["tool_call_count"],
                usage_input_tokens=row["usage_input_tokens"],
                usage_output_tokens=row["usage_output_tokens"],
                cost=row["cost"],
                latency_ms=row["latency_ms"],
                started_at=row["started_at"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                payload=_loads(row["payload"]),
            )
            for row in rows
        ]

    def get_copilot_run_log(self, run_id: str) -> Optional[CopilotRunLog]:
        rows = self.list_copilot_run_logs(limit=1)
        row = next((item for item in rows if item.run_id == run_id), None)
        if row is not None:
            return row
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM copilot_run_log WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return CopilotRunLog(
            run_id=row["run_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            mode=row["mode"],
            active_client=row["active_client"],
            model_name=row["model_name"],
            status=row["status"],
            error_category=row["error_category"],
            runtime_error=row["runtime_error"],
            tool_call_count=row["tool_call_count"],
            usage_input_tokens=row["usage_input_tokens"],
            usage_output_tokens=row["usage_output_tokens"],
            cost=row["cost"],
            latency_ms=row["latency_ms"],
            started_at=row["started_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            payload=_loads(row["payload"]),
        )

    def save_runtime_metric_snapshot(
        self, snapshot: RuntimeMetricSnapshot
    ) -> RuntimeMetricSnapshot:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO runtime_metric_snapshot(snapshot_id, created_at, payload)
                VALUES (?, ?, ?)
                """,
                (snapshot.snapshot_id, snapshot.created_at, _json(snapshot.payload)),
            )
            self.conn.commit()
        return snapshot

    def list_runtime_metric_snapshots(
        self, *, limit: int = 50
    ) -> List[RuntimeMetricSnapshot]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM runtime_metric_snapshot ORDER BY created_at DESC, snapshot_id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            RuntimeMetricSnapshot(
                snapshot_id=row["snapshot_id"],
                created_at=row["created_at"],
                payload=_loads(row["payload"]),
            )
            for row in rows
        ]

    def save_strategy_spec(self, spec: StrategySpec) -> StrategySpec:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO strategy_spec(
                  strategy_id, name, strategy_type, enabled, risk_level, tags, payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                  name=excluded.name,
                  strategy_type=excluded.strategy_type,
                  enabled=excluded.enabled,
                  risk_level=excluded.risk_level,
                  tags=excluded.tags,
                  payload=excluded.payload,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at
                """,
                (
                    spec.strategy_id,
                    spec.name,
                    spec.strategy_type,
                    int(spec.enabled),
                    spec.risk_level,
                    _json(spec.tags),
                    _json(spec),
                    spec.created_at,
                    spec.updated_at,
                ),
            )
            self.conn.commit()
        return spec

    def list_strategy_specs(self, enabled: bool | None = None) -> List[StrategySpec]:
        query = "SELECT payload FROM strategy_spec"
        params: list[Any] = []
        if enabled is not None:
            query += " WHERE enabled = ?"
            params.append(int(enabled))
        query += " ORDER BY updated_at DESC, strategy_id ASC"
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [StrategySpec(**_loads(row["payload"])) for row in rows]

    def get_strategy_spec(self, strategy_id: str) -> Optional[StrategySpec]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM strategy_spec WHERE strategy_id = ?",
                (strategy_id,),
            ).fetchone()
        return StrategySpec(**_loads(row["payload"])) if row else None

    def delete_strategy_spec(self, strategy_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM strategy_spec WHERE strategy_id = ?", (strategy_id,)
            )
            self.conn.commit()
        return cur.rowcount > 0

    def save_backtest_run(self, run: BacktestRun) -> BacktestRun:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO backtest_run(
                  run_id, strategy_id, strategy_name, strategy_type, degraded, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.run_id,
                    run.strategy_id,
                    run.strategy_name,
                    run.strategy_type,
                    int(run.degraded),
                    run.created_at,
                    _json(run),
                ),
            )
            self.conn.commit()
        return run

    def list_backtest_runs(
        self, strategy_id: str | None = None, limit: int = 20
    ) -> List[BacktestRun]:
        query = "SELECT payload FROM backtest_run"
        params: list[Any] = []
        if strategy_id is not None:
            query += " WHERE strategy_id = ?"
            params.append(strategy_id)
        query += " ORDER BY created_at DESC, run_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [BacktestRun(**_loads(row["payload"])) for row in rows]

    def get_backtest_run(self, run_id: str) -> Optional[BacktestRun]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM backtest_run WHERE run_id = ?", (run_id,)
            ).fetchone()
        return BacktestRun(**_loads(row["payload"])) if row else None

    def save_risk_policy(self, policy: RiskPolicy) -> RiskPolicy:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO risk_policy(
                  policy_id, name, is_active, is_default, created_at, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_id) DO UPDATE SET
                  name=excluded.name,
                  is_active=excluded.is_active,
                  is_default=excluded.is_default,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (
                    policy.policy_id,
                    policy.name,
                    int(policy.is_active),
                    int(policy.is_default),
                    policy.created_at,
                    policy.updated_at,
                    _json(policy),
                ),
            )
            self.conn.commit()
        return policy

    def list_risk_policies(self) -> List[RiskPolicy]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT payload FROM risk_policy ORDER BY is_active DESC, updated_at DESC, policy_id ASC"
            ).fetchall()
        return [RiskPolicy(**_loads(row["payload"])) for row in rows]

    def get_risk_policy(self, policy_id: str) -> Optional[RiskPolicy]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM risk_policy WHERE policy_id = ?", (policy_id,)
            ).fetchone()
        return RiskPolicy(**_loads(row["payload"])) if row else None

    def get_active_risk_policy(self) -> Optional[RiskPolicy]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT payload FROM risk_policy
                WHERE is_active = 1 OR is_default = 1
                ORDER BY is_active DESC, is_default DESC, updated_at DESC
                LIMIT 1
                """
            ).fetchone()
        return RiskPolicy(**_loads(row["payload"])) if row else None

    def activate_risk_policy(
        self, policy_id: str, updated_at: str | None = None
    ) -> Optional[RiskPolicy]:
        with self._lock:
            activated: RiskPolicy | None = None
            target_updated_at = updated_at or now_iso()
            with self.conn:
                self.conn.execute("BEGIN IMMEDIATE")
                row = self.conn.execute(
                    "SELECT payload FROM risk_policy WHERE policy_id = ?", (policy_id,)
                ).fetchone()
                if not row:
                    return None
                policy = RiskPolicy(**_loads(row["payload"]))
                self.conn.execute(
                    "UPDATE risk_policy SET is_active = 0, is_default = 0 WHERE policy_id <> ?",
                    (policy_id,),
                )
                other_rows = self.conn.execute(
                    "SELECT policy_id, payload FROM risk_policy WHERE policy_id <> ?",
                    (policy_id,),
                ).fetchall()
                for other_row in other_rows:
                    other = RiskPolicy(**_loads(other_row["payload"]))
                    cleared = other.model_copy(
                        update={"is_active": False, "is_default": False}
                    )
                    self.conn.execute(
                        "UPDATE risk_policy SET payload = ? WHERE policy_id = ?",
                        (_json(cleared), cleared.policy_id),
                    )
                activated = policy.model_copy(
                    update={
                        "is_active": True,
                        "is_default": True,
                        "updated_at": target_updated_at,
                    }
                )
                self.conn.execute(
                    """
                    UPDATE risk_policy
                    SET name = ?, is_active = 1, is_default = 1, created_at = ?, updated_at = ?, payload = ?
                    WHERE policy_id = ?
                    """,
                    (
                        activated.name,
                        activated.created_at,
                        activated.updated_at,
                        _json(activated),
                        activated.policy_id,
                    ),
                )
        return activated

    def save_monitor_rule(self, rule: MonitorRule) -> MonitorRule:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO monitor_rule(
                  rule_id, symbol, rule_type, severity, title, trigger_rule,
                  cooldown_seconds, enabled, payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(rule_id) DO UPDATE SET
                  symbol=excluded.symbol,
                  rule_type=excluded.rule_type,
                  severity=excluded.severity,
                  title=excluded.title,
                  trigger_rule=excluded.trigger_rule,
                  cooldown_seconds=excluded.cooldown_seconds,
                  enabled=excluded.enabled,
                  payload=excluded.payload,
                  updated_at=excluded.updated_at
                """,
                (
                    rule.rule_id,
                    rule.symbol,
                    rule.rule_type,
                    rule.severity,
                    rule.title,
                    rule.trigger_rule,
                    rule.cooldown_seconds,
                    int(rule.enabled),
                    _json(rule),
                    rule.created_at,
                    rule.updated_at,
                ),
            )
            self.conn.commit()
        return rule

    def list_monitor_rules(self) -> List[MonitorRule]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT payload FROM monitor_rule ORDER BY updated_at DESC, rule_id DESC"
            ).fetchall()
        return [MonitorRule(**_loads(row["payload"])) for row in rows]

    def delete_monitor_rule(self, rule_id: str) -> bool:
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM monitor_rule WHERE rule_id = ?", (rule_id,)
            )
            self.conn.commit()
        return cur.rowcount > 0

    def save_monitor_event(self, event: EventContext) -> EventContext:
        evidence = event.evidence
        payload = event.payload or {}
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO monitor_event(
                  event_id, rule_id, rule_type, symbol, source, severity, title,
                  trigger_rule, dedupe_key, triggered_at, cooldown_until,
                  evidence_json, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                  rule_id=excluded.rule_id,
                  rule_type=excluded.rule_type,
                  symbol=excluded.symbol,
                  source=excluded.source,
                  severity=excluded.severity,
                  title=excluded.title,
                  trigger_rule=excluded.trigger_rule,
                  dedupe_key=excluded.dedupe_key,
                  triggered_at=excluded.triggered_at,
                  cooldown_until=excluded.cooldown_until,
                  evidence_json=excluded.evidence_json,
                  payload=excluded.payload,
                  created_at=excluded.created_at
                """,
                (
                    event.event_id,
                    event.rule_id,
                    event.rule_type,
                    event.symbol,
                    event.source,
                    event.severity,
                    event.title,
                    event.trigger_rule,
                    event.dedupe_key,
                    event.triggered_at,
                    event.cooldown_until,
                    _json(evidence),
                    _json(event),
                    event.triggered_at,
                ),
            )
            self.conn.commit()
        return event

    def list_monitor_events(
        self,
        *,
        symbol: str | None = None,
        severity: str | None = None,
        limit: int = 50,
    ) -> List[EventContext]:
        query = "SELECT * FROM monitor_event"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if severity is not None:
            clauses.append("severity = ?")
            params.append(severity)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY triggered_at DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_monitor_event(row) for row in rows]

    def has_monitor_events(self) -> bool:
        with self._lock:
            row = self.conn.execute("SELECT 1 FROM monitor_event LIMIT 1").fetchone()
        return row is not None

    def get_monitor_event(self, event_id: str) -> Optional[EventContext]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM monitor_event WHERE event_id = ?", (event_id,)
            ).fetchone()
        return self._row_to_monitor_event(row) if row else None

    def get_latest_monitor_event_by_dedupe_key(
        self, dedupe_key: str
    ) -> Optional[EventContext]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT * FROM monitor_event
                WHERE dedupe_key = ?
                ORDER BY triggered_at DESC, created_at DESC
                LIMIT 1
                """,
                (dedupe_key,),
            ).fetchone()
        return self._row_to_monitor_event(row) if row else None

    def save_monitor_status(self, status: MonitorStatus) -> MonitorStatus:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO monitor_status(status_key, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(status_key) DO UPDATE SET
                  payload=excluded.payload,
                  updated_at=excluded.updated_at
                """,
                ("default", _json(status), status.updated_at),
            )
            self.conn.commit()
        return status

    def get_monitor_status(self) -> Optional[MonitorStatus]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM monitor_status WHERE status_key = 'default'"
            ).fetchone()
        return MonitorStatus(**_loads(row["payload"])) if row else None

    def list_tasks(self) -> List[AgentTask]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT payload FROM agent_task ORDER BY created_at DESC"
            ).fetchall()
        return [AgentTask(**_loads(row["payload"])) for row in rows]

    def get_task(self, task_id: str) -> Optional[AgentTask]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM agent_task WHERE task_id = ?", (task_id,)
            ).fetchone()
        return AgentTask(**_loads(row["payload"])) if row else None

    def get_task_by_run_id(self, run_id: str) -> Optional[AgentTask]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM agent_task WHERE json_extract(payload, '$.run_id') = ? ORDER BY created_at DESC LIMIT 1",
                (run_id,),
            ).fetchone()
        return AgentTask(**_loads(row["payload"])) if row else None

    def save_copilot_session(self, session: CopilotSession) -> CopilotSession:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO copilot_session(
                  session_id, title, status, current_page, anchor_symbol, authority_level,
                  created_at, updated_at, last_message_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  title=excluded.title,
                  status=excluded.status,
                  current_page=excluded.current_page,
                  anchor_symbol=excluded.anchor_symbol,
                  authority_level=excluded.authority_level,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  last_message_at=excluded.last_message_at
                """,
                (
                    session.session_id,
                    session.title,
                    session.status,
                    session.current_page,
                    session.anchor_symbol,
                    session.authority_level.value,
                    session.created_at,
                    session.updated_at,
                    session.last_message_at,
                ),
            )
            self.conn.commit()
        return session

    def list_copilot_sessions(self, limit: int | None = 50) -> List[CopilotSession]:
        query = "SELECT * FROM copilot_session ORDER BY COALESCE(last_message_at, updated_at) DESC, created_at DESC"
        params: list[Any] = []
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_copilot_session(row) for row in rows]

    def delete_copilot_session(self, session_id: str) -> None:
        with self._lock:
            self.conn.execute(
                "DELETE FROM copilot_message WHERE session_id = ?", (session_id,)
            )
            self.conn.execute(
                "DELETE FROM copilot_session WHERE session_id = ?", (session_id,)
            )
            self.conn.commit()

    def get_copilot_session(self, session_id: str) -> Optional[CopilotSession]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM copilot_session WHERE session_id = ?", (session_id,)
            ).fetchone()
        return self._row_to_copilot_session(row) if row else None

    def save_copilot_message(self, message: CopilotMessage) -> CopilotMessage:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO copilot_message(
                  message_id, session_id, role, kind, text, page, symbol,
                  run_id, task_id, client_message_id, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                  session_id=excluded.session_id,
                  role=excluded.role,
                  kind=excluded.kind,
                  text=excluded.text,
                  page=excluded.page,
                  symbol=excluded.symbol,
                  run_id=excluded.run_id,
                  task_id=excluded.task_id,
                  client_message_id=excluded.client_message_id,
                  created_at=excluded.created_at,
                  payload=excluded.payload
                """,
                (
                    message.message_id,
                    message.session_id,
                    message.role,
                    message.kind,
                    message.text,
                    message.page,
                    message.symbol,
                    message.run_id,
                    message.task_id,
                    message.client_message_id,
                    message.created_at,
                    _json(message.payload),
                ),
            )
            session = self.get_copilot_session(message.session_id)
            if session:
                updated = session.model_copy(
                    update={
                        "current_page": message.page or session.current_page,
                        "anchor_symbol": message.symbol or session.anchor_symbol,
                        "updated_at": message.created_at,
                        "last_message_at": message.created_at,
                    }
                )
                self.conn.execute(
                    """
                    UPDATE copilot_session
                    SET current_page = ?, anchor_symbol = ?, updated_at = ?, last_message_at = ?
                    WHERE session_id = ?
                    """,
                    (
                        updated.current_page,
                        updated.anchor_symbol,
                        updated.updated_at,
                        updated.last_message_at,
                        updated.session_id,
                    ),
                )
            self.conn.commit()
        return message

    def list_copilot_messages(
        self,
        *,
        session_id: str,
        run_id: str | None = None,
    ) -> List[CopilotMessage]:
        query = "SELECT * FROM copilot_message WHERE session_id = ?"
        params: list[Any] = [session_id]
        if run_id is not None:
            query += " AND run_id = ?"
            params.append(run_id)
        query += " ORDER BY created_at ASC, message_id ASC"
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_copilot_message(row) for row in rows]

    def get_copilot_user_message_by_run_id(
        self, run_id: str
    ) -> Optional[CopilotMessage]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT * FROM copilot_message
                WHERE run_id = ? AND role = 'user'
                ORDER BY created_at ASC, message_id ASC
                LIMIT 1
                """,
                (run_id,),
            ).fetchone()
        return self._row_to_copilot_message(row) if row else None

    def list_copilot_run_messages(self, run_id: str) -> List[CopilotMessage]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM copilot_message WHERE run_id = ? ORDER BY created_at ASC, message_id ASC",
                (run_id,),
            ).fetchall()
        return [self._row_to_copilot_message(row) for row in rows]

    def save_rebalance_draft(self, draft: RebalanceDraft) -> RebalanceDraft:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO rebalance_draft(
                  draft_id, symbol, status, authority_level, target_weight_pct, valid_until, created_at, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                  symbol=excluded.symbol,
                  status=excluded.status,
                  authority_level=excluded.authority_level,
                  target_weight_pct=excluded.target_weight_pct,
                  valid_until=excluded.valid_until,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (
                    draft.draft_id,
                    draft.symbol,
                    draft.status.value,
                    draft.authority_level.value,
                    draft.target_weight_pct,
                    draft.valid_until,
                    draft.created_at,
                    draft.updated_at,
                    _json(draft),
                ),
            )
            self.conn.commit()
        return draft

    def get_rebalance_draft(self, draft_id: str) -> Optional[RebalanceDraft]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM rebalance_draft WHERE draft_id = ?", (draft_id,)
            ).fetchone()
        return RebalanceDraft(**_loads(row["payload"])) if row else None

    def list_rebalance_drafts(
        self,
        *,
        symbol: str | None = None,
        status: str | None = None,
        limit: int | None = 50,
    ) -> List[RebalanceDraft]:
        query = "SELECT payload FROM rebalance_draft"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, draft_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [RebalanceDraft(**_loads(row["payload"])) for row in rows]

    def save_pre_trade_review(self, review: PreTradeReview) -> PreTradeReview:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO pre_trade_review(
                  review_id, source_draft_id, symbol, status, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(review_id) DO UPDATE SET
                  source_draft_id=excluded.source_draft_id,
                  symbol=excluded.symbol,
                  status=excluded.status,
                  created_at=excluded.created_at,
                  payload=excluded.payload
                """,
                (
                    review.review_id,
                    review.source_draft_id,
                    review.symbol,
                    review.status.value,
                    review.created_at,
                    _json(review),
                ),
            )
            self.conn.commit()
        return review

    def get_pre_trade_review(self, review_id: str) -> Optional[PreTradeReview]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM pre_trade_review WHERE review_id = ?", (review_id,)
            ).fetchone()
        return PreTradeReview(**_loads(row["payload"])) if row else None

    def list_pre_trade_reviews(
        self,
        *,
        draft_id: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        limit: int | None = 50,
    ) -> List[PreTradeReview]:
        query = "SELECT payload FROM pre_trade_review"
        clauses: list[str] = []
        params: list[Any] = []
        if draft_id is not None:
            clauses.append("source_draft_id = ?")
            params.append(draft_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, review_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [PreTradeReview(**_loads(row["payload"])) for row in rows]

    def save_paper_order(self, order: PaperOrder) -> PaperOrder:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO paper_order(
                  order_id, review_id, source_draft_id, symbol, status, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                  review_id=excluded.review_id,
                  source_draft_id=excluded.source_draft_id,
                  symbol=excluded.symbol,
                  status=excluded.status,
                  created_at=excluded.created_at,
                  payload=excluded.payload
                """,
                (
                    order.order_id,
                    order.review_id,
                    order.source_draft_id,
                    order.symbol,
                    order.status.value,
                    order.created_at,
                    _json(order),
                ),
            )
            self.conn.commit()
        return order

    def get_paper_order(self, order_id: str) -> Optional[PaperOrder]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM paper_order WHERE order_id = ?", (order_id,)
            ).fetchone()
        return PaperOrder(**_loads(row["payload"])) if row else None

    def list_paper_orders(
        self,
        *,
        review_id: str | None = None,
        draft_id: str | None = None,
        symbol: str | None = None,
        status: str | None = None,
        limit: int | None = 50,
    ) -> List[PaperOrder]:
        query = "SELECT payload FROM paper_order"
        clauses: list[str] = []
        params: list[Any] = []
        if review_id is not None:
            clauses.append("review_id = ?")
            params.append(review_id)
        if draft_id is not None:
            clauses.append("source_draft_id = ?")
            params.append(draft_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, order_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [PaperOrder(**_loads(row["payload"])) for row in rows]

    def save_paper_portfolio_snapshot(
        self, snapshot: PaperPortfolioSnapshot
    ) -> PaperPortfolioSnapshot:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO paper_portfolio_snapshot(
                  snapshot_id, baseline_id, as_of, degraded, market_value, cash_estimate,
                  equity_estimate, pnl_estimate, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.baseline_id,
                    snapshot.as_of,
                    int(snapshot.degraded),
                    snapshot.market_value,
                    snapshot.cash_estimate,
                    snapshot.equity_estimate,
                    snapshot.pnl_estimate,
                    snapshot.created_at,
                    _json(snapshot),
                ),
            )
            self.conn.commit()
        return snapshot

    def get_paper_portfolio_snapshot(
        self, snapshot_id: str
    ) -> Optional[PaperPortfolioSnapshot]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM paper_portfolio_snapshot WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        return PaperPortfolioSnapshot(**_loads(row["payload"])) if row else None

    def list_paper_portfolio_snapshots(
        self,
        *,
        baseline_id: str | None = None,
        limit: int | None = 50,
    ) -> List[PaperPortfolioSnapshot]:
        query = "SELECT payload FROM paper_portfolio_snapshot"
        clauses: list[str] = []
        params: list[Any] = []
        if baseline_id is not None:
            clauses.append("baseline_id = ?")
            params.append(baseline_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY as_of DESC, created_at DESC, snapshot_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [PaperPortfolioSnapshot(**_loads(row["payload"])) for row in rows]

    def save_decision_journal_entry(
        self, entry: DecisionJournalEntry
    ) -> DecisionJournalEntry:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO decision_journal_entry(
                  entry_id, decision_id, draft_id, review_id, paper_order_id, snapshot_id,
                  report_id, symbol, status, source_type, closed_at, close_note, created_at, updated_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(entry_id) DO UPDATE SET
                  decision_id=excluded.decision_id,
                  draft_id=excluded.draft_id,
                  review_id=excluded.review_id,
                  paper_order_id=excluded.paper_order_id,
                  snapshot_id=excluded.snapshot_id,
                  report_id=excluded.report_id,
                  symbol=excluded.symbol,
                  status=excluded.status,
                  source_type=excluded.source_type,
                  closed_at=excluded.closed_at,
                  close_note=excluded.close_note,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at,
                  payload=excluded.payload
                """,
                (
                    entry.entry_id,
                    entry.decision_id,
                    entry.draft_id,
                    entry.review_id,
                    entry.paper_order_id,
                    entry.snapshot_id,
                    entry.report_id,
                    entry.symbol,
                    entry.status,
                    entry.source_type,
                    entry.closed_at,
                    entry.close_note,
                    entry.created_at,
                    entry.updated_at,
                    _json(entry),
                ),
            )
            self.conn.commit()
        return entry

    def get_decision_journal_entry(
        self, entry_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def get_decision_journal_entry_by_decision_id(
        self, decision_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def get_decision_journal_entry_by_draft_id(
        self, draft_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def get_decision_journal_entry_by_review_id(
        self, review_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def get_decision_journal_entry_by_paper_order_id(
        self, paper_order_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE paper_order_id = ?",
                (paper_order_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def get_decision_journal_entry_by_snapshot_id(
        self, snapshot_id: str
    ) -> Optional[DecisionJournalEntry]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM decision_journal_entry WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        return DecisionJournalEntry(**_loads(row["payload"])) if row else None

    def list_decision_journal_entries(
        self,
        *,
        symbol: str | None = None,
        status: str | None = None,
        source_type: str | None = None,
        limit: int | None = 50,
    ) -> List[DecisionJournalEntry]:
        query = "SELECT payload FROM decision_journal_entry"
        clauses: list[str] = []
        params: list[Any] = []
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if source_type is not None:
            clauses.append("source_type = ?")
            params.append(source_type)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY updated_at DESC, created_at DESC, entry_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [DecisionJournalEntry(**_loads(row["payload"])) for row in rows]

    def save_report_template(self, template: ReportTemplate) -> ReportTemplate:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO report_template(template_id, report_type, visible, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id) DO UPDATE SET
                  report_type=excluded.report_type,
                  visible=excluded.visible,
                  payload=excluded.payload,
                  created_at=excluded.created_at,
                  updated_at=excluded.updated_at
                """,
                (
                    template.template_id,
                    template.report_type,
                    int(template.visible),
                    _json(template),
                    template.created_at,
                    template.updated_at,
                ),
            )
            self.conn.commit()
        return template

    def list_report_templates(
        self, *, visible_only: bool = True
    ) -> List[ReportTemplate]:
        query = "SELECT payload FROM report_template"
        params: list[Any] = []
        if visible_only:
            query += " WHERE visible = ?"
            params.append(1)
        query += " ORDER BY report_type ASC, created_at ASC, template_id ASC"
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [ReportTemplate(**_loads(row["payload"])) for row in rows]

    def get_report_template(self, template_id: str) -> Optional[ReportTemplate]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM report_template WHERE template_id = ?",
                (template_id,),
            ).fetchone()
        return ReportTemplate(**_loads(row["payload"])) if row else None

    def save_report(self, report: Report) -> Report:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO report(
                  report_id, report_type, source_type, source_id, symbol, quality_status,
                  latest_quality_check_id, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(report_id) DO UPDATE SET
                  report_type=excluded.report_type,
                  source_type=excluded.source_type,
                  source_id=excluded.source_id,
                  symbol=excluded.symbol,
                  quality_status=excluded.quality_status,
                  latest_quality_check_id=excluded.latest_quality_check_id,
                  payload=excluded.payload,
                  created_at=excluded.created_at
                """,
                (
                    report.report_id,
                    report.report_type,
                    report.source_type,
                    report.source_id,
                    report.symbol,
                    report.quality_status,
                    report.latest_quality_check_id,
                    _json(report),
                    report.created_at,
                ),
            )
            self.conn.commit()
        return report

    def list_reports(
        self,
        *,
        report_type: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> List[Report]:
        query = "SELECT payload FROM report"
        clauses: list[str] = []
        params: list[Any] = []
        if report_type is not None:
            clauses.append("report_type = ?")
            params.append(report_type)
        if source_type is not None:
            clauses.append("source_type = ?")
            params.append(source_type)
        if source_id is not None:
            clauses.append("source_id = ?")
            params.append(source_id)
        if symbol is not None:
            clauses.append("symbol = ?")
            params.append(symbol.upper())
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, report_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [Report(**_loads(row["payload"])) for row in rows]

    def get_report(self, report_id: str) -> Optional[Report]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM report WHERE report_id = ?", (report_id,)
            ).fetchone()
        return Report(**_loads(row["payload"])) if row else None

    def save_report_quality_check(
        self, check: ReportQualityCheck
    ) -> ReportQualityCheck:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO report_quality_check(check_id, report_id, template_id, status, created_at, payload)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    check.check_id,
                    check.report_id,
                    check.template_id,
                    check.status,
                    check.created_at,
                    _json(check),
                ),
            )
            self.conn.commit()
        return check

    def list_report_quality_checks(self, report_id: str) -> List[ReportQualityCheck]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT payload FROM report_quality_check
                WHERE report_id = ?
                ORDER BY created_at DESC, check_id DESC
                """,
                (report_id,),
            ).fetchall()
        return [ReportQualityCheck(**_loads(row["payload"])) for row in rows]

    def get_latest_report_quality_check(
        self, report_id: str
    ) -> Optional[ReportQualityCheck]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT payload FROM report_quality_check
                WHERE report_id = ?
                ORDER BY created_at DESC, check_id DESC
                LIMIT 1
                """,
                (report_id,),
            ).fetchone()
        return ReportQualityCheck(**_loads(row["payload"])) if row else None

    def save_audit(self, log: AuditLog) -> AuditLog:
        with self._lock:
            self.conn.execute(
                "INSERT INTO audit_log(audit_id, payload, created_at) VALUES (?, ?, ?)",
                (log.audit_id, _json(log), log.created_at),
            )
            self.conn.commit()
        return log

    def list_audit(self, limit: int = 100) -> List[AuditLog]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT payload FROM audit_log ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [AuditLog(**_loads(row["payload"])) for row in rows]

    def save_tool_execution(self, execution: ToolExecution) -> ToolExecution:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO tool_execution(
                  execution_id, task_id, run_id, call_id, tool, domain, status, authority_level,
                  arguments, source_mode, evidence_refs, result_summary, error, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id) DO UPDATE SET
                  task_id=excluded.task_id,
                  run_id=excluded.run_id,
                  call_id=excluded.call_id,
                  tool=excluded.tool,
                  domain=excluded.domain,
                  status=excluded.status,
                  authority_level=excluded.authority_level,
                  arguments=excluded.arguments,
                  source_mode=excluded.source_mode,
                  evidence_refs=excluded.evidence_refs,
                  result_summary=excluded.result_summary,
                  error=excluded.error,
                  payload=excluded.payload,
                  created_at=excluded.created_at
                """,
                (
                    execution.execution_id,
                    execution.task_id,
                    execution.run_id,
                    execution.call_id,
                    execution.tool,
                    execution.domain,
                    execution.status,
                    execution.authority_level,
                    _json(execution.arguments),
                    execution.source_mode,
                    _json(execution.evidence_refs),
                    execution.result_summary,
                    execution.error,
                    _json(execution),
                    execution.created_at,
                ),
            )
            self.conn.commit()
        return execution

    def list_tool_executions(
        self, task_id: str | None = None, run_id: str | None = None, limit: int = 100
    ) -> List[ToolExecution]:
        query = "SELECT payload FROM tool_execution"
        clauses: list[str] = []
        params: list[Any] = []
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at ASC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [ToolExecution(**_loads(row["payload"])) for row in rows]

    def save_review_inbox_state(self, state: ReviewInboxState) -> ReviewInboxState:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO review_inbox_state(item_key, status, snoozed_until, note, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(item_key) DO UPDATE SET
                  status=excluded.status,
                  snoozed_until=excluded.snoozed_until,
                  note=excluded.note,
                  updated_at=excluded.updated_at
                """,
                (
                    state.item_key,
                    state.status.value,
                    state.snoozed_until,
                    state.note,
                    state.updated_at,
                ),
            )
            self.conn.commit()
        return state

    def get_review_inbox_state(self, item_key: str) -> Optional[ReviewInboxState]:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT item_key, status, snoozed_until, note, updated_at
                FROM review_inbox_state
                WHERE item_key = ?
                """,
                (item_key,),
            ).fetchone()
        return ReviewInboxState(**dict(row)) if row else None

    def list_review_inbox_states(self) -> List[ReviewInboxState]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT item_key, status, snoozed_until, note, updated_at
                FROM review_inbox_state
                ORDER BY updated_at DESC, item_key DESC
                """
            ).fetchall()
        return [ReviewInboxState(**dict(row)) for row in rows]

    def set_config(self, key: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO app_config(key, payload)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET payload=excluded.payload
                """,
                (key, _json(payload)),
            )
            self.conn.commit()
        return payload

    def get_config(
        self, key: str, default: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM app_config WHERE key = ?", (key,)
            ).fetchone()
        return _loads(row["payload"]) if row else (default or {})

    def _row_to_copilot_session(self, row: sqlite3.Row) -> CopilotSession:
        return CopilotSession(
            session_id=row["session_id"],
            title=row["title"],
            status=row["status"],
            current_page=row["current_page"],
            anchor_symbol=row["anchor_symbol"],
            authority_level=AuthorityLevel(row["authority_level"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_message_at=row["last_message_at"],
        )

    def _row_to_copilot_message(self, row: sqlite3.Row) -> CopilotMessage:
        return CopilotMessage(
            message_id=row["message_id"],
            session_id=row["session_id"],
            role=row["role"],
            kind=row["kind"],
            text=row["text"],
            page=row["page"],
            symbol=row["symbol"],
            run_id=row["run_id"],
            task_id=row["task_id"],
            client_message_id=row["client_message_id"],
            created_at=row["created_at"],
            payload=_loads(row["payload"]),
        )

    def _row_to_monitor_event(self, row: sqlite3.Row) -> EventContext:
        payload = _loads(row["payload"])
        payload.setdefault("rule_id", row["rule_id"])
        payload.setdefault("rule_type", row["rule_type"])
        payload.setdefault("symbol", row["symbol"])
        payload.setdefault("source", row["source"])
        payload.setdefault("severity", row["severity"])
        payload.setdefault("title", row["title"])
        payload.setdefault("trigger_rule", row["trigger_rule"])
        payload.setdefault("dedupe_key", row["dedupe_key"])
        payload.setdefault("triggered_at", row["triggered_at"] or row["created_at"])
        payload.setdefault("cooldown_until", row["cooldown_until"])
        payload.setdefault("evidence", json.loads(row["evidence_json"] or "[]"))
        payload.setdefault("payload", payload.get("payload", {}))
        payload.setdefault("suggested_actions", payload.get("suggested_actions", []))
        return EventContext(**payload)

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

    def list_stock_master(self, *, active_only: bool = True) -> List[StockMaster]:
        with self._lock:
            if active_only:
                rows = self.conn.execute(
                    "SELECT * FROM stock_master WHERE is_active = 1 ORDER BY symbol"
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM stock_master ORDER BY symbol"
                ).fetchall()
        result: List[StockMaster] = []
        for row in rows:
            result.append(
                StockMaster(
                    symbol=row["symbol"],
                    name=row["name"],
                    market=row["market"],
                    industry=row["industry"] or "",
                    sector=row["sector"] or "",
                    aliases=json.loads(row["aliases"] or "[]"),
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            )
        return result

    def get_stock_master(self, symbol: str) -> Optional[StockMaster]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM stock_master WHERE symbol = ?", (symbol,)
            ).fetchone()
        if not row:
            return None
        return StockMaster(
            symbol=row["symbol"],
            name=row["name"],
            market=row["market"],
            industry=row["industry"] or "",
            sector=row["sector"] or "",
            aliases=json.loads(row["aliases"] or "[]"),
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def search_stock_master(self, query: str) -> List[StockMaster]:
        q = query.strip().lower()
        if not q:
            return self.list_stock_master()
        all_stocks = self.list_stock_master(active_only=True)
        result: List[StockMaster] = []
        for s in all_stocks:
            haystack = " ".join(
                [
                    s.symbol,
                    s.name,
                    s.market,
                ]
                + s.aliases
            ).lower()
            if q in haystack:
                result.append(s)
        return result

    def upsert_stock_master(self, item: StockMaster) -> StockMaster:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO stock_master(symbol, name, market, industry, sector, aliases, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                  name=excluded.name,
                  market=excluded.market,
                  industry=excluded.industry,
                  sector=excluded.sector,
                  aliases=excluded.aliases,
                  is_active=excluded.is_active,
                  updated_at=excluded.updated_at
                """,
                (
                    item.symbol.upper(),
                    item.name,
                    item.market,
                    item.industry,
                    item.sector,
                    json.dumps(item.aliases, ensure_ascii=False),
                    int(item.is_active),
                    item.created_at,
                    item.updated_at,
                ),
            )
            self.conn.commit()
        return item

    def batch_upsert_stock_master(self, items: List[StockMaster]) -> int:
        if not items:
            return 0
        from backend.schemas import now_iso

        now_val = now_iso()
        placeholders = ",".join("(?, ?, ?, ?, ?, ?, ?, ?, ?)" for _ in items)
        flat_params: list[Any] = []
        for item in items:
            flat_params.extend(
                (
                    item.symbol.upper(),
                    item.name,
                    item.market,
                    item.industry,
                    item.sector,
                    json.dumps(item.aliases, ensure_ascii=False),
                    int(item.is_active),
                    now_val,
                    now_val,
                )
            )
        sql = f"""
            INSERT INTO stock_master(symbol, name, market, industry, sector, aliases, is_active, created_at, updated_at)
            VALUES {placeholders}
            ON CONFLICT(symbol) DO UPDATE SET
              name=excluded.name,
              market=excluded.market,
              industry=excluded.industry,
              sector=excluded.sector,
              aliases=excluded.aliases,
              is_active=excluded.is_active,
              updated_at=excluded.updated_at
        """
        with self._lock:
            self.conn.execute(sql, flat_params)
            self.conn.commit()
        return len(items)

    # ── Stock Daily ─────────────────────────────────────────────────

    def upsert_stock_daily(self, item: StockDaily) -> StockDaily:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO stock_daily(symbol, trade_date, open, high, low, close, volume, amount, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, trade_date) DO UPDATE SET
                  open=excluded.open,
                  high=excluded.high,
                  low=excluded.low,
                  close=excluded.close,
                  volume=excluded.volume,
                  amount=excluded.amount,
                  source=excluded.source
                """,
                (
                    item.symbol.upper(),
                    item.trade_date,
                    item.open,
                    item.high,
                    item.low,
                    item.close,
                    item.volume,
                    item.amount,
                    item.source,
                    item.created_at,
                ),
            )
            self.conn.commit()
        return item

    def batch_upsert_stock_daily(self, items: List[StockDaily]) -> int:
        """Upsert many stock_daily rows in a single transaction.
        Returns the number of rows inserted/updated.
        """
        if not items:
            return 0
        placeholders = ",".join(
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))" for _ in items
        )
        flat_params: list[Any] = []
        for item in items:
            flat_params.extend(
                (
                    item.symbol.upper(),
                    item.trade_date,
                    item.open,
                    item.high,
                    item.low,
                    item.close,
                    item.volume,
                    item.amount,
                    item.source,
                )
            )
        sql = f"""
            INSERT INTO stock_daily(symbol, trade_date, open, high, low, close, volume, amount, source, created_at)
            VALUES {placeholders}
            ON CONFLICT(symbol, trade_date) DO UPDATE SET
              open=excluded.open,
              high=excluded.high,
              low=excluded.low,
              close=excluded.close,
              volume=excluded.volume,
              amount=excluded.amount,
              source=excluded.source
        """
        with self._lock:
            self.conn.execute(sql, flat_params)
            self.conn.commit()
        return len(items)

    def list_stock_daily(
        self,
        symbol: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        limit: int = 90,
    ) -> List[StockDaily]:
        query = "SELECT * FROM stock_daily WHERE symbol = ?"
        params: List[Any] = [symbol.upper()]
        if start_date:
            query += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            query += " AND trade_date <= ?"
            params.append(end_date)
        query += " ORDER BY trade_date DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [
            StockDaily(
                symbol=row["symbol"],
                trade_date=row["trade_date"],
                open=row["open"],
                high=row["high"],
                low=row["low"],
                close=row["close"],
                volume=row["volume"],
                amount=row["amount"],
                source=row["source"] or "",
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def get_stock_daily(self, symbol: str, trade_date: str) -> Optional[StockDaily]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM stock_daily WHERE symbol = ? AND trade_date = ?",
                (symbol.upper(), trade_date),
            ).fetchone()
        if not row:
            return None
        return StockDaily(
            symbol=row["symbol"],
            trade_date=row["trade_date"],
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
            amount=row["amount"],
            source=row["source"] or "",
            created_at=row["created_at"],
        )

    def count_stock_daily(self, symbol: str) -> int:
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS cnt FROM stock_daily WHERE symbol = ?",
                (symbol.upper(),),
            ).fetchone()
        return row["cnt"] if row else 0

    # ── Stock Quote ─────────────────────────────────────────────────

    def upsert_stock_quote(self, item: StockQuote) -> StockQuote:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO stock_quote(symbol, last, change_pct, volume, amount, source, provider, hit_count, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                  last=excluded.last,
                  change_pct=excluded.change_pct,
                  volume=excluded.volume,
                  amount=excluded.amount,
                  source=excluded.source,
                  provider=excluded.provider,
                  hit_count=excluded.hit_count,
                  updated_at=excluded.updated_at
                """,
                (
                    item.symbol.upper(),
                    item.last,
                    item.change_pct,
                    item.volume,
                    item.amount,
                    item.source,
                    item.provider,
                    item.hit_count,
                    item.updated_at,
                ),
            )
            self.conn.commit()
        return item

    def list_stock_quotes(self) -> list[StockQuote]:
        """Return all cached stock quotes (for staleness checks)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM stock_quote ORDER BY symbol"
            ).fetchall()
        return [
            StockQuote(
                symbol=row["symbol"],
                last=row["last"],
                change_pct=row["change_pct"],
                volume=row["volume"],
                amount=row["amount"],
                source=row["source"] or "",
                provider=row["provider"] or "",
                hit_count=row["hit_count"] if row["hit_count"] is not None else 0,
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def get_stock_quote(self, symbol: str) -> Optional[StockQuote]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM stock_quote WHERE symbol = ?", (symbol.upper(),)
            ).fetchone()
        if not row:
            return None
        return StockQuote(
            symbol=row["symbol"],
            last=row["last"],
            change_pct=row["change_pct"],
            volume=row["volume"],
            amount=row["amount"],
            source=row["source"] or "",
            provider=row.get("provider", "") or "",
            hit_count=row.get("hit_count", 0) if row.get("hit_count") is not None else 0,
            updated_at=row["updated_at"],
        )

    # ── Stock Financial ─────────────────────────────────────────────

    def upsert_stock_financial(self, item: StockFinancial) -> StockFinancial:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO stock_financial(symbol, report_date, report_type, revenue, profit, total_assets, total_liabilities, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, report_date, report_type) DO UPDATE SET
                  revenue=excluded.revenue,
                  profit=excluded.profit,
                  total_assets=excluded.total_assets,
                  total_liabilities=excluded.total_liabilities,
                  payload=excluded.payload
                """,
                (
                    item.symbol.upper(),
                    item.report_date,
                    item.report_type,
                    item.revenue,
                    item.profit,
                    item.total_assets,
                    item.total_liabilities,
                    json.dumps(item.payload, ensure_ascii=False),
                    item.created_at,
                ),
            )
            self.conn.commit()
        return item

    def list_stock_financial(
        self, symbol: str, *, report_type: str | None = None
    ) -> List[StockFinancial]:
        query = "SELECT * FROM stock_financial WHERE symbol = ?"
        params: List[Any] = [symbol.upper()]
        if report_type:
            query += " AND report_type = ?"
            params.append(report_type)
        query += " ORDER BY report_date DESC"
        with self._lock:
            rows = self.conn.execute(query, tuple(params)).fetchall()
        return [
            StockFinancial(
                symbol=row["symbol"],
                report_date=row["report_date"],
                report_type=row["report_type"],
                revenue=row["revenue"],
                profit=row["profit"],
                total_assets=row["total_assets"],
                total_liabilities=row["total_liabilities"],
                payload=json.loads(row["payload"] or "{}"),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    # ── Capability Cache ────────────────────────────────────────────
    def upsert_capability_cache(
        self, capability: str, payload: dict, symbol: str = ""
    ) -> None:
        from backend.schemas import now_iso

        now_val = now_iso()
        payload_str = json.dumps(payload, ensure_ascii=False, default=str)
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO capability_cache(capability, symbol, payload, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(capability, symbol) DO UPDATE SET
                  payload=excluded.payload,
                  created_at=excluded.created_at
                """,
                (capability, symbol, payload_str, now_val),
            )
            self.conn.commit()

    def get_capability_cache(self, capability: str, symbol: str = "") -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT payload FROM capability_cache WHERE capability = ? AND symbol = ?",
                (capability, symbol),
            ).fetchone()
        if row is None:
            return None
        return json.loads(row["payload"])
