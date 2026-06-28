from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import logging
import os
import re
from statistics import mean
from typing import Any, AsyncIterator, Callable
from uuid import uuid4

from backend.app_services.audit_service import AuditService
from backend.app_services.context_builder import ContextBuilder
from backend.app_services.monitor_notifier import dispatch_notification
from backend.app_services.risk_policy_service import RiskPolicyService
from backend.schemas import EventContext, MonitorRule, MonitorStatus, SSEEvent, model_to_dict, now_iso
from backend.persistence.repositories import WorkbenchRepository
from backend.stock_domain.intel_tools import search_stock_intel
from backend.stock_domain.monitor_tools import get_monitor_events as get_fallback_monitor_events
from backend.stock_domain.provider_router import provider_router

logger = logging.getLogger("monitor_service")

DEFAULT_MONITOR_INTERVAL_SECONDS = 60
DEFAULT_MONITOR_STREAM_SECONDS = 5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class MonitorService:
    def __init__(
        self,
        repo: WorkbenchRepository,
        context_builder: ContextBuilder,
        audit_service: AuditService,
        risk_policy_service: RiskPolicyService,
    ) -> None:
        self.repo = repo
        self.context_builder = context_builder
        self.audit_service = audit_service
        self.risk_policy_service = risk_policy_service
        self._loop_task: asyncio.Task[None] | None = None
        # Per-instance, persisted accuracy feedback (was a shared class-level
        # dict that leaked across instances/tests and vanished on restart).
        self._accuracy_log: dict[str, deque[bool]] = defaultdict(lambda: deque(maxlen=20))
        self._load_accuracy_log()

    def get_status(self) -> MonitorStatus:
        persisted = self.repo.get_monitor_status()
        if persisted:
            if not persisted.interval_seconds:
                persisted.interval_seconds = self._default_interval_seconds()
            return persisted
        return MonitorStatus(
            status="paused",
            auto_start=False,
            interval_seconds=self._default_interval_seconds(),
        )

    def save_status(self, status: MonitorStatus) -> MonitorStatus:
        status.updated_at = now_iso()
        return self.repo.save_monitor_status(status)

    def start(self) -> MonitorStatus:
        status = self.get_status()
        status.status = "running"
        status.last_error = None
        saved = self.save_status(status)
        self.audit_service.record("monitor started", "stock monitor enabled")
        return saved

    def pause(self) -> MonitorStatus:
        status = self.get_status()
        status.status = "paused"
        saved = self.save_status(status)
        self.audit_service.record("monitor paused", "stock monitor paused")
        return saved

    def upsert_rule(self, payload: dict[str, Any] | MonitorRule) -> MonitorRule:
        rule = payload if isinstance(payload, MonitorRule) else self._coerce_rule(payload)
        rule.updated_at = now_iso()
        saved = self.repo.save_monitor_rule(rule)
        self.audit_service.record("monitor rules updated", f"{saved.rule_id} {saved.rule_type}")
        return saved

    def list_rules(self) -> list[MonitorRule]:
        return self.repo.list_monitor_rules()

    def delete_rule(self, rule_id: str) -> bool:
        deleted = self.repo.delete_monitor_rule(rule_id)
        if deleted:
            self.audit_service.record("monitor rule deleted", rule_id)
        return deleted

    def evaluate_one_rule(
        self,
        rule: MonitorRule,
        *,
        source: str,
        now: datetime,
        force: bool,
        ctx_cache: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {"rule_id": rule.rule_id, "checked": 1, "matched": 0, "created": 0, "suppressed": 0, "errors": [], "event_ids": []}
        try:
            matches = self._evaluate_rule(rule, source=source, now=now, ctx_cache=ctx_cache)
        except Exception as exc:
            result["errors"].append({"rule_id": rule.rule_id, "error": str(exc)})
            return result
        for match in matches:
            result["matched"] += 1
            latest = self.repo.get_latest_monitor_event_by_dedupe_key(match["dedupe_key"])
            active_cooldown = latest and _parse_iso(latest.cooldown_until) and _parse_iso(latest.cooldown_until) > now
            if active_cooldown and not force:
                result["suppressed"] += 1
                continue
            event = self._build_event(rule, match, source=source, now=now)
            self.repo.save_monitor_event(event)
            result["created"] += 1
            result["event_ids"].append(event.event_id)
            if event.severity in ("high", "medium"):
                try:
                    dispatch_notification(event)
                except Exception:
                    pass
        return result

    def evaluate_once(self, source: str = "manual", force: bool = False) -> dict[str, Any]:
        now = _utc_now()
        summary: dict[str, Any] = {
            "checked": 0, "matched": 0, "created": 0, "suppressed": 0,
            "errors": [], "event_ids": [],
        }
        rules = [rule for rule in self.list_rules() if rule.enabled]
        # Build each needed StockContext once per cycle and share it read-only
        # across the parallel rule evaluations, so the same symbol isn't fetched
        # repeatedly by price_change / combined / sector rules in one pass.
        ctx_cache = self._prebuild_context_cache(rules)
        # Evaluate all rules in parallel using threads (I/O bound: provider calls)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(rules) or 1)) as pool:
            futures = {
                pool.submit(
                    self.evaluate_one_rule, rule, source=source, now=now, force=force, ctx_cache=ctx_cache
                ): rule
                for rule in rules
            }
            for future in concurrent.futures.as_completed(futures):
                try:
                    result = future.result()
                except Exception as exc:
                    summary["errors"].append({"rule_id": "unknown", "error": str(exc)})
                    continue
                summary["checked"] += result["checked"]
                summary["matched"] += result["matched"]
                summary["created"] += result["created"]
                summary["suppressed"] += result["suppressed"]
                summary["errors"].extend(result["errors"])
                summary["event_ids"].extend(result["event_ids"])
        status = self.get_status()
        status.last_checked_at = now_iso()
        status.last_matched_at = now_iso() if summary["matched"] else status.last_matched_at
        status.last_error = summary["errors"][0]["error"] if summary["errors"] else None
        self.save_status(status)
        return summary

    def list_events(
        self,
        *,
        symbol: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        offset: int = 0,
        allow_fallback: bool = True,
    ) -> list[EventContext]:
        persisted = self.repo.list_monitor_events(
            symbol=symbol, severity=severity, limit=limit, offset=offset
        )
        # Demo/onboarding fallback is opt-out: UI-facing surfaces (events list,
        # dashboard summary) pass allow_fallback=False so synthetic events never
        # inflate real statistics. The agent tool / review inbox keep it on.
        if persisted or not allow_fallback or self.repo.has_monitor_events():
            return persisted
        items = self._fallback_events(symbol, severity)
        return items[offset : offset + limit]

    def count_events(
        self,
        *,
        symbol: str | None = None,
        severity: str | None = None,
        allow_fallback: bool = True,
    ) -> int:
        count = self.repo.count_monitor_events(symbol=symbol, severity=severity)
        if count or not allow_fallback or self.repo.has_monitor_events():
            return count
        return len(self._fallback_events(symbol, severity))

    def _fallback_events(
        self, symbol: str | None, severity: str | None
    ) -> list[EventContext]:
        items = get_fallback_monitor_events()
        if symbol:
            items = [item for item in items if item.symbol.upper() == symbol.upper()]
        if severity:
            items = [item for item in items if item.severity == severity]
        return items

    def explain_event(self, event_id: str | None = None, event: EventContext | None = None) -> dict[str, Any]:
        event = event or (self.repo.get_monitor_event(event_id) if event_id else None)
        if event is None:
            fallback = self.list_events(limit=1)
            event = fallback[0] if fallback else None
        if event is None:
            return {"summary": "暂无盯盘事件。", "evidence": [], "suggested_actions": [], "event": None}
        return self._build_event_explanation(event)

    def empty_explanation(self) -> dict[str, Any]:
        return {"summary": "当前筛选条件下暂无盯盘事件。", "evidence": [], "suggested_actions": [], "event": None}

    def _build_event_explanation(self, event: EventContext) -> dict[str, Any]:
        summary = f"{event.title}，触发规则 {event.trigger_rule}，严重度 {event.severity}。"
        return {
            "summary": summary,
            "evidence": event.evidence,
            "suggested_actions": event.suggested_actions,
            "event": model_to_dict(event),
        }

    def build_monitor_summary(self) -> dict[str, Any]:
        # Dashboard KPIs must reflect only real events — no synthetic fallback.
        events = self.list_events(limit=20, allow_fallback=False)
        status = self.get_status()
        provider_status = provider_router.status()
        latest = model_to_dict(events[0]) if events else None
        # Build proactive diagnosis hints for Copilot
        diagnosis_hints: list[str] = []
        if events:
            high_events = [e for e in events if e.severity == "high"]
            if high_events:
                diagnosis_hints.append(f"发现 {len(high_events)} 条高风险盯盘事件，建议主动分析影响")
            for e in events[:3]:
                if "sector" in e.payload:
                    diagnosis_hints.append(f"板块联动异动 ({e.payload.get('sector', '')})，建议检查相关持仓风险")
                if e.rule_type == "volume_spike":
                    diagnosis_hints.append(f"{e.symbol} 成交量异常，建议搜索相关舆情")
                break
        return {
            "status": status.status,
            "available": True,
            "provider_degraded": provider_status.degraded,
            "event_count": len(events),
            "high_count": sum(1 for item in events if item.severity == "high"),
            "latest": latest,
            "diagnosis_hints": diagnosis_hints,
        }

    def _snapshot_events(self) -> list[SSEEvent]:
        status = self.get_status()
        events = self.list_events(limit=20, allow_fallback=False)
        return [
            SSEEvent(run_id="monitor", task_id="monitor", type="status", payload=model_to_dict(status)),
            SSEEvent(
                run_id="monitor",
                task_id="monitor",
                type="events",
                payload={"items": [model_to_dict(item) for item in events]},
            ),
            SSEEvent(run_id="monitor", task_id="monitor", type="summary", payload=self.build_monitor_summary()),
        ]

    async def stream_snapshot(self, *, once: bool = False) -> AsyncIterator[SSEEvent]:
        """SSE stream of monitor state.

        With ``once`` it emits a single status/events/summary snapshot and
        returns — the original behaviour (used by callers that can't consume an
        open-ended stream, e.g. the in-process TestClient).

        Otherwise it stays alive and pushes a fresh snapshot whenever monitor
        state changes, with a lightweight heartbeat in between. Previously the
        endpoint yielded one snapshot and closed, so the browser's EventSource
        silently reconnected every few seconds — a polling loop dressed up as a
        stream. Keeping the generator alive makes it a real push: new events
        from the background loop or a manual evaluation reach the UI within one
        tick, and the heartbeat keeps proxies / EventSource from timing out.
        """
        if once:
            for event in self._snapshot_events():
                yield event
            return

        last_signature: tuple[Any, ...] | None = None
        first = True
        try:
            while True:
                status = self.get_status()
                events = self.list_events(limit=20, allow_fallback=False)
                signature = (
                    status.status,
                    status.last_checked_at,
                    status.last_matched_at,
                    len(events),
                    events[0].event_id if events else None,
                )
                if first or signature != last_signature:
                    for event in self._snapshot_events():
                        yield event
                    last_signature = signature
                    first = False
                else:
                    yield SSEEvent(run_id="monitor", task_id="monitor", type="ping", payload={})
                await asyncio.sleep(self._stream_push_seconds())
        except (asyncio.CancelledError, GeneratorExit):
            # Client disconnected — stop cleanly without noise.
            return

    async def startup(self) -> None:
        status = self.get_status()
        if status.auto_start and status.status == "running":
            await self.start_loop()

    async def shutdown(self) -> None:
        await self.stop_loop()

    async def start_loop(self) -> None:
        if self.is_loop_running():
            return
        self._loop_task = asyncio.create_task(self._run_loop(), name="workbench-monitor-loop")

    async def stop_loop(self) -> None:
        if not self._loop_task:
            return
        self._loop_task.cancel()
        try:
            await self._loop_task
        except asyncio.CancelledError:
            pass
        self._loop_task = None

    def is_loop_running(self) -> bool:
        return self._loop_task is not None and not self._loop_task.done()

    async def _run_loop(self) -> None:
        while True:
            status = self.get_status()
            if status.status == "running":
                await asyncio.to_thread(self.evaluate_once, "loop", False)
            await asyncio.sleep(max(1, status.interval_seconds or self._default_interval_seconds()))

    def _build_event(self, rule: MonitorRule, match: dict[str, Any], *, source: str, now: datetime) -> EventContext:
        cooldown_until = (now + timedelta(seconds=max(0, rule.cooldown_seconds))).isoformat()
        payload = dict(match["payload"])
        payload.setdefault("source", source)
        payload.setdefault("symbol", match["symbol"])
        payload.setdefault("rule_id", rule.rule_id)
        payload.setdefault("rule_type", rule.rule_type)
        return EventContext(
            event_id=f"event_{uuid4().hex[:12]}",
            rule_id=rule.rule_id,
            rule_type=rule.rule_type,
            source=source,
            symbol=match["symbol"],
            title=match["title"],
            severity=match["severity"],
            triggered_at=now.isoformat(),
            trigger_rule=match["trigger_rule"],
            dedupe_key=match["dedupe_key"],
            cooldown_until=cooldown_until,
            evidence=match["evidence"],
            suggested_actions=match["suggested_actions"],
            payload=payload,
        )

    def _coerce_rule(self, payload: dict[str, Any]) -> MonitorRule:
        defaults = self.risk_policy_service.get_monitor_defaults()
        if "rule_type" in payload:
            symbol = str(payload.get("symbol")).upper() if payload.get("symbol") else None
            return MonitorRule(
                rule_id=str(payload.get("rule_id") or f"rule_{uuid4().hex[:10]}"),
                rule_type=str(payload["rule_type"]),
                symbol=symbol,
                severity=str(payload.get("severity") or "medium"),
                enabled=bool(payload.get("enabled", True)),
                threshold=(
                    float(payload["threshold"])
                    if payload.get("threshold") is not None
                    else float(defaults["threshold"]) if payload["rule_type"] == "single_position_weight_gt" else None
                ),
                keyword=str(payload["keyword"]) if payload.get("keyword") else None,
                cooldown_seconds=(
                    int(payload["cooldown_seconds"])
                    if payload.get("cooldown_seconds") is not None
                    else int(defaults["cooldown_seconds"])
                ),
                title=str(payload["title"]) if payload.get("title") else None,
                trigger_rule=str(payload["trigger_rule"]) if payload.get("trigger_rule") else None,
                source=str(payload.get("source") or "user"),
                rule_text=str(payload["rule_text"]) if payload.get("rule_text") else None,
                metadata=dict(payload.get("metadata") or {}),
                created_at=str(payload.get("created_at") or now_iso()),
                updated_at=str(payload.get("updated_at") or now_iso()),
            )
        symbol = str(payload.get("symbol") or "").upper() or None
        rule_text = str(payload.get("rule") or "").strip()
        if not rule_text:
            threshold = float(defaults["threshold"])
        else:
            match = re.fullmatch(r"single_position_weight\s*>\s*([0-9]+(?:\.[0-9]+)?)%?", rule_text)
            if not match:
                raise ValueError(f"unsupported legacy monitor rule: {rule_text}")
            threshold = float(match.group(1))
        if rule_text and not re.fullmatch(r"single_position_weight\s*>\s*([0-9]+(?:\.[0-9]+)?)%?", rule_text):
            raise ValueError(f"unsupported legacy monitor rule: {rule_text}")
        return MonitorRule(
            rule_id=f"rule_{uuid4().hex[:10]}",
            rule_type="single_position_weight_gt",
            symbol=symbol,
            threshold=threshold,
            severity="high",
            cooldown_seconds=int(defaults["cooldown_seconds"]),
            title=f"{symbol or '持仓'} 仓位超过 {threshold:g}%",
            trigger_rule=f"single_position_weight > {threshold:g}%",
            source="legacy_rule",
            rule_text=rule_text or f"single_position_weight > {threshold:g}%",
        )

    def _evaluate_rule(
        self,
        rule: MonitorRule,
        *,
        source: str,
        now: datetime,
        ctx_cache: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        # Fatigue suppression: skip rule if suppression score is too high
        if self._suppression_score(rule.rule_id) >= 0.7:
            logger.info("rule %s suppressed by accuracy feedback", rule.rule_id)
            return []
        if rule.rule_type == "single_position_weight_gt":
            return self._match_single_position_weight(rule)
        if rule.rule_type == "price_change_pct_gt":
            return self._match_price_change(rule, ctx_cache=ctx_cache)
        if rule.rule_type == "data_provider_degraded":
            return self._match_data_provider_degraded(rule)
        if rule.rule_type == "intel_keyword_match":
            return self._match_intel_keyword(rule, source=source)
        if rule.rule_type == "ma_crossover":
            return self._match_ma_crossover(rule)
        if rule.rule_type == "volume_spike":
            return self._match_volume_spike(rule)
        if rule.rule_type == "sector_correlation":
            return self._match_sector_correlation(rule, ctx_cache=ctx_cache)
        if rule.rule_type == "combined_condition":
            return self._match_combined_condition(rule, source=source, now=now, ctx_cache=ctx_cache)
        raise ValueError(f"unsupported monitor rule_type: {rule.rule_type}")

    def _match_single_position_weight(self, rule: MonitorRule) -> list[dict[str, Any]]:
        threshold = float(rule.threshold if rule.threshold is not None else self.risk_policy_service.get_monitor_defaults()["threshold"])
        holdings = self.repo.list_holdings()
        if rule.symbol:
            holdings = [item for item in holdings if item.symbol.upper() == rule.symbol.upper()]
        matches = []
        for item in holdings:
            if item.weight_pct <= threshold:
                continue
            matches.append(
                {
                    "symbol": item.symbol.upper(),
                    "title": rule.title or f"{item.symbol.upper()} 仓位超过规则上限",
                    "severity": "high" if item.weight_pct >= threshold + 2 else rule.severity,
                    "trigger_rule": rule.trigger_rule or f"single_position_weight > {threshold:g}%",
                    "dedupe_key": f"{rule.rule_id}:{item.symbol.upper()}:single_position_weight_gt:{threshold:g}",
                    "evidence": [
                        {"type": "holding_weight_pct", "value": item.weight_pct},
                        {"type": "threshold_pct", "value": threshold},
                        {"type": "portfolio_snapshot", "ref": "holding_position"},
                    ],
                    "suggested_actions": ["open_stock_context", "run_risk_review", "generate_rebalance_plan"],
                    "payload": {"symbol": item.symbol.upper(), "weight_pct": item.weight_pct, "threshold": threshold},
                }
            )
        return matches

    def _match_price_change(
        self, rule: MonitorRule, *, ctx_cache: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        threshold = float(rule.threshold if rule.threshold is not None else 3)
        symbols = self._rule_symbols(rule)
        matches = []
        for symbol in symbols:
            ctx = self._context_for(symbol, ctx_cache)
            price = ctx.price
            if price is None:
                continue
            if abs(price.change_pct) <= threshold:
                continue
            direction = "上涨" if price.change_pct > 0 else "下跌"
            matches.append(
                {
                    "symbol": symbol,
                    "title": rule.title or f"{symbol} {direction}幅度超过 {threshold:g}%",
                    "severity": "high" if abs(price.change_pct) >= threshold * 2 else rule.severity,
                    "trigger_rule": rule.trigger_rule or f"abs(price_change_pct) > {threshold:g}%",
                    "dedupe_key": f"{rule.rule_id}:{symbol}:price_change_pct_gt:{threshold:g}:{direction}",
                    "evidence": [
                        {"type": "price_change_pct", "value": price.change_pct},
                        {"type": "quote_source", "ref": price.source},
                    ],
                    "suggested_actions": ["open_stock_context", "review_intraday_move"],
                    "payload": {"symbol": symbol, "change_pct": price.change_pct, "threshold": threshold},
                }
            )
        return matches

    def _match_data_provider_degraded(self, rule: MonitorRule) -> list[dict[str, Any]]:
        status = provider_router.status()
        if not status.degraded:
            return []
        return [
            {
                "symbol": "DATA",
                "title": rule.title or "行情/情报数据提供方已降级",
                "severity": rule.severity,
                "trigger_rule": rule.trigger_rule or "data_provider_degraded == true",
                "dedupe_key": f"{rule.rule_id}:DATA:data_provider_degraded:{status.active_provider}:{status.fallback_provider}",
                "evidence": [
                    {"type": "active_provider", "ref": status.active_provider},
                    {"type": "fallback_provider", "ref": status.fallback_provider},
                    {"type": "degraded_reason", "value": status.degraded_reason},
                ],
                "suggested_actions": ["show_degraded_state"],
                "payload": {
                    "active_provider": status.active_provider,
                    "fallback_provider": status.fallback_provider,
                    "degraded_reason": status.degraded_reason,
                },
            }
        ]

    def _match_intel_keyword(self, rule: MonitorRule, *, source: str) -> list[dict[str, Any]]:
        if not rule.keyword:
            return []
        keyword = rule.keyword.lower()
        matches = []
        for symbol in self._rule_symbols(rule):
            intel = search_stock_intel(symbol, rule.keyword)
            hit_items = [item for item in intel["items"] if keyword in str(item.get("title", "")).lower()]
            if not hit_items:
                continue
            matches.append(
                {
                    "symbol": symbol,
                    "title": rule.title or f"{symbol} 命中情报关键词 {rule.keyword}",
                    "severity": rule.severity,
                    "trigger_rule": rule.trigger_rule or f"intel_keyword_match({rule.keyword})",
                    "dedupe_key": f"{rule.rule_id}:{symbol}:intel_keyword_match:{keyword}",
                    "evidence": [{"type": "intel_hit", "items": hit_items[:3]}, {"type": "intel_source", "ref": intel["source"]}],
                    "suggested_actions": ["open_stock_context", "review_news_cluster"],
                    "payload": {"symbol": symbol, "keyword": rule.keyword, "source": source},
                }
            )
        return matches

    # ── new rule types ──────────────────────────────────────────────────────

    def _match_ma_crossover(self, rule: MonitorRule) -> list[dict[str, Any]]:
        """Detect moving average golden cross / death cross.
        metadata: {fast_period: 5, slow_period: 20, lookback_days: 30}
        """
        meta = rule.metadata or {}
        fast = int(meta.get("fast_period", 5))
        slow = int(meta.get("slow_period", 20))
        lookback = int(meta.get("lookback_days", 30))
        symbols = self._rule_symbols(rule)
        matches: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                history = provider_router.get_history(symbol, days=lookback)
            except Exception:
                continue
            bars = history.get("bars", history.get("items", []))
            closes = [b["close"] for b in bars if b.get("close") is not None]
            if len(closes) < slow + 1:
                continue
            prev_fast = mean(closes[-(fast + 1):-1])
            prev_slow = mean(closes[-(slow + 1):-1])
            curr_fast = mean(closes[-fast:])
            curr_slow = mean(closes[-slow:])
            # golden cross: fast crosses ABOVE slow
            if prev_fast <= prev_slow and curr_fast > curr_slow:
                title = rule.title or f"{symbol} MA{fast} 上穿 MA{slow}（金叉）"
                direction = "golden_cross"
            # death cross: fast crosses BELOW slow
            elif prev_fast >= prev_slow and curr_fast < curr_slow:
                title = rule.title or f"{symbol} MA{fast} 下穿 MA{slow}（死叉）"
                direction = "death_cross"
            else:
                continue
            matches.append({
                "symbol": symbol,
                "title": title,
                "severity": rule.severity,
                "trigger_rule": rule.trigger_rule or f"ma_crossover({fast},{slow})",
                "dedupe_key": f"{rule.rule_id}:{symbol}:ma_crossover:{fast}_{slow}:{direction}",
                "evidence": [
                    {"type": "ma_fast", "period": fast, "value": round(curr_fast, 2)},
                    {"type": "ma_slow", "period": slow, "value": round(curr_slow, 2)},
                    {"type": "direction", "value": direction},
                ],
                "suggested_actions": ["open_stock_context", "review_intraday_move"],
                "payload": {"symbol": symbol, "fast_ma": round(curr_fast, 2), "slow_ma": round(curr_slow, 2), "direction": direction},
            })
        return matches

    def _match_volume_spike(self, rule: MonitorRule) -> list[dict[str, Any]]:
        """Detect abnormal volume spikes.
        metadata: {volume_multiplier: 3.0, baseline_days: 20, lookback_days: 30}
        threshold: volume_multiplier (fallback)
        """
        meta = rule.metadata or {}
        multiplier = float(rule.threshold if rule.threshold is not None else meta.get("volume_multiplier", 3.0))
        baseline_days = int(meta.get("baseline_days", 20))
        lookback = int(meta.get("lookback_days", 30))
        symbols = self._rule_symbols(rule)
        matches: list[dict[str, Any]] = []
        for symbol in symbols:
            try:
                history = provider_router.get_history(symbol, days=lookback)
            except Exception:
                continue
            bars = history.get("bars", history.get("items", []))
            volumes = [b.get("volume", 0) for b in bars if b.get("volume") is not None]
            if len(volumes) < baseline_days + 1:
                continue
            baseline = mean(volumes[-(baseline_days + 1):-1])
            if baseline <= 0:
                continue
            current_volume = volumes[-1]
            ratio = current_volume / baseline
            if ratio < multiplier:
                continue
            matches.append({
                "symbol": symbol,
                "title": rule.title or f"{symbol} 成交量异常放大 {ratio:.1f}x（基准 {multiplier:.0f}x）",
                "severity": "high" if ratio >= multiplier * 2 else rule.severity,
                "trigger_rule": rule.trigger_rule or f"volume_spike > {multiplier:.0f}x",
                "dedupe_key": f"{rule.rule_id}:{symbol}:volume_spike",
                "evidence": [
                    {"type": "volume_ratio", "value": round(ratio, 2)},
                    {"type": "current_volume", "value": current_volume},
                    {"type": "baseline_volume", "value": round(baseline, 1)},
                ],
                "suggested_actions": ["open_stock_context", "review_news_cluster"],
                "payload": {"symbol": symbol, "volume_ratio": round(ratio, 2), "current_volume": current_volume, "baseline_volume": round(baseline, 1)},
            })
        return matches

    def _match_sector_correlation(
        self, rule: MonitorRule, *, ctx_cache: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Detect sector-wide anomalies: more than N symbols in same sector triggering.
        metadata: {min_symbols: 2, sector: "白酒"} (omit sector to scan all)
        threshold: min_symbols (fallback)
        """
        meta = rule.metadata or {}
        min_symbols = int(rule.threshold if rule.threshold is not None else meta.get("min_symbols", 2))
        target_sector = meta.get("sector") or None
        holdings = self.repo.list_holdings()
        # Group holdings by sector
        from backend.stock_domain.catalog import get_stock
        sector_map: dict[str, list[str]] = {}
        for h in holdings:
            info = get_stock(h.symbol) or {}
            sec = str(info.get("sector", "unknown"))
            if target_sector and sec != target_sector:
                continue
            sector_map.setdefault(sec, []).append(h.symbol.upper())
        matches: list[dict[str, Any]] = []
        for sector, syms in sector_map.items():
            if len(syms) < min_symbols:
                continue
            # Check each symbol for price anomaly
            triggered = []
            for sym in syms:
                try:
                    ctx = self._context_for(sym, ctx_cache)
                    if ctx.price is None:
                        continue
                    if abs(ctx.price.change_pct) >= 2.0:
                        triggered.append({"symbol": sym, "change_pct": ctx.price.change_pct})
                except Exception:
                    continue
            if len(triggered) < min_symbols:
                continue
            avg_change = mean(t["change_pct"] for t in triggered)
            matches.append({
                "symbol": ",".join(t["symbol"] for t in triggered),
                "title": rule.title or f"板块联动 {sector}：{len(triggered)} 只异动（均幅 {avg_change:.1f}%）",
                "severity": rule.severity,
                "trigger_rule": rule.trigger_rule or f"sector_correlation({sector})",
                "dedupe_key": f"{rule.rule_id}:{sector}:sector_correlation",
                "evidence": [
                    {"type": "sector", "value": sector},
                    {"type": "symbol_count", "value": len(triggered)},
                    {"type": "avg_change_pct", "value": round(avg_change, 2)},
                    {"type": "triggered_symbols", "items": triggered[:5]},
                ],
                "suggested_actions": ["open_stock_context", "run_risk_review"],
                "payload": {"sector": sector, "symbol_count": len(triggered), "avg_change_pct": round(avg_change, 2), "triggered": triggered[:5]},
            })
        return matches

    def _match_combined_condition(
        self, rule: MonitorRule, *, source: str, now: datetime, ctx_cache: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Composite condition: price_change AND volume_spike AND/OR keyword_match in a time window.
        metadata: {
          conditions: [
            {type: "price_change", threshold: 2.0},
            {type: "volume_spike", multiplier: 2.0},
            {type: "keyword_match", keyword: "财报"}
          ],
          require_all: true,        # false = any condition triggers
          confidence_threshold: 60  # minimum total score out of 100
        }
        """
        meta = rule.metadata or {}
        conditions = meta.get("conditions", [])
        require_all = bool(meta.get("require_all", True))
        confidence_threshold = int(meta.get("confidence_threshold", 60))
        if not conditions:
            return []
        symbols = self._rule_symbols(rule)
        matches: list[dict[str, Any]] = []
        for symbol in symbols:
            scores: list[int] = []
            evidence: list[dict[str, Any]] = []
            hit_details: list[str] = []
            for cond in conditions:
                ctype = str(cond.get("type", ""))
                score = 0
                detail = ""
                if ctype == "price_change":
                    try:
                        ctx = self._context_for(symbol, ctx_cache)
                        if ctx.price is None:
                            continue
                        threshold = float(cond.get("threshold", 2.0))
                        pct = abs(ctx.price.change_pct)
                        if pct >= threshold:
                            s = min(40, int(pct / threshold * 25))
                            score = s
                            detail = f"价格波动 {ctx.price.change_pct:.1f}%"
                            evidence.append({"type": "price_change_pct", "value": ctx.price.change_pct, "score": s})
                    except Exception:
                        pass
                elif ctype == "volume_spike":
                    try:
                        multiplier = float(cond.get("multiplier", 2.0))
                        history = provider_router.get_history(symbol, days=30)
                        bars = history.get("bars", history.get("items", []))
                        volumes = [b["volume"] for b in bars if b.get("volume") is not None]
                        if len(volumes) >= 6:
                            baseline = mean(volumes[-6:-1]) or 1
                            ratio = volumes[-1] / baseline
                            if ratio >= multiplier:
                                s = min(35, int((ratio - multiplier) * 15))
                                score = s
                                detail = f"量比 {ratio:.1f}x"
                                evidence.append({"type": "volume_ratio", "value": round(ratio, 2), "score": s})
                    except Exception:
                        pass
                elif ctype == "keyword_match":
                    keyword = str(cond.get("keyword", ""))
                    if keyword:
                        try:
                            intel = search_stock_intel(symbol, keyword)
                            hits = [item for item in intel.get("items", []) if keyword.lower() in str(item.get("title", "")).lower()]
                            if hits:
                                s = min(25, len(hits) * 10)
                                score = s
                                detail = f"情报命中 {keyword}"
                                evidence.append({"type": "intel_hit", "count": len(hits), "score": s, "items": hits[:2]})
                        except Exception:
                            pass
                if score > 0:
                    hit_details.append(detail)
                scores.append(score)
            # Determine if triggered
            total = sum(scores)
            if require_all and any(s == 0 for s in scores):
                continue
            if not require_all and total <= 0:
                continue
            if total < confidence_threshold:
                continue
            matches.append({
                "symbol": symbol,
                "title": rule.title or f"{symbol} 复合条件命中（置信度 {total}/100）",
                "severity": rule.severity if total < 80 else "high",
                "trigger_rule": rule.trigger_rule or f"combined_condition(score={total})",
                "dedupe_key": f"{rule.rule_id}:{symbol}:combined_condition:{now.strftime('%H')}",
                "evidence": [
                    *evidence,
                    {"type": "total_score", "value": total},
                    {"type": "condition_hits", "items": hit_details},
                ],
                "suggested_actions": ["open_stock_context", "review_news_cluster", "run_risk_review"],
                "payload": {"symbol": symbol, "total_score": total, "conditions": hit_details, "require_all": require_all},
            })
        return matches

    # ── alert fatigue suppression ───────────────────────────────────────────

    _ACCURACY_CONFIG_KEY = "monitor_accuracy_log"

    def _load_accuracy_log(self) -> None:
        try:
            raw = self.repo.get_config(self._ACCURACY_CONFIG_KEY, {}) or {}
        except Exception:
            return
        for rule_id, values in raw.items():
            if isinstance(values, list):
                self._accuracy_log[rule_id] = deque((bool(v) for v in values[-20:]), maxlen=20)

    def _persist_accuracy_log(self) -> None:
        try:
            self.repo.set_config(
                self._ACCURACY_CONFIG_KEY,
                {rule_id: list(log) for rule_id, log in self._accuracy_log.items() if log},
            )
        except Exception:
            logger.warning("failed to persist monitor accuracy log", exc_info=True)

    def record_accuracy(self, rule_id: str, was_useful: bool) -> None:
        self._accuracy_log[rule_id].append(bool(was_useful))
        self._persist_accuracy_log()

    # Back-compat alias (route + tests historically called the private name).
    _record_accuracy = record_accuracy

    def _suppression_score(self, rule_id: str) -> float:
        """Return 0.0 (no suppression) to 1.0 (fully suppressed) based on recent accuracy."""
        log = self._accuracy_log.get(rule_id)
        if not log or len(log) < 3:
            return 0.0
        accuracy = sum(1 for v in log if v) / len(log)
        if accuracy >= 0.7:
            return 0.0
        if accuracy >= 0.4:
            return 0.3
        return 0.7

    def _context_for(self, symbol: str, ctx_cache: dict[str, Any] | None):
        """Return a StockContext, reusing the per-cycle cache when present."""
        if ctx_cache is not None:
            cached = ctx_cache.get(symbol.upper())
            if cached is not None:
                return cached
        return self.context_builder.build_stock_context(symbol)

    def _prebuild_context_cache(self, rules: list[MonitorRule]) -> dict[str, Any]:
        """Build each StockContext a cycle needs exactly once.

        The returned dict is populated before the parallel phase and only read
        (never written) by the worker threads, so no locking is required.
        """
        symbols: set[str] = set()
        holdings_symbols: list[str] | None = None
        for rule in rules:
            if rule.rule_type in ("price_change_pct_gt", "combined_condition"):
                symbols.update(self._rule_symbols(rule))
            elif rule.rule_type == "sector_correlation":
                if holdings_symbols is None:
                    holdings_symbols = [item.symbol.upper() for item in self.repo.list_holdings()]
                symbols.update(holdings_symbols)
        cache: dict[str, Any] = {}
        for symbol in symbols:
            try:
                cache[symbol.upper()] = self.context_builder.build_stock_context(symbol)
            except Exception:
                continue  # rebuilt/handled inside the individual match method
        return cache

    def _rule_symbols(self, rule: MonitorRule) -> list[str]:
        if rule.symbol:
            return [rule.symbol.upper()]
        watchlist = [item.symbol.upper() for item in self.repo.list_watchlist() if item.monitored]
        holdings = [item.symbol.upper() for item in self.repo.list_holdings()]
        seen: list[str] = []
        for symbol in watchlist + holdings:
            if symbol not in seen:
                seen.append(symbol)
        return seen

    def _default_interval_seconds(self) -> int:
        raw = os.getenv("WORKBENCH_MONITOR_INTERVAL_SECONDS", str(DEFAULT_MONITOR_INTERVAL_SECONDS))
        try:
            return max(1, int(raw))
        except ValueError:
            return DEFAULT_MONITOR_INTERVAL_SECONDS

    def _stream_push_seconds(self) -> float:
        raw = os.getenv("WORKBENCH_MONITOR_STREAM_SECONDS", str(DEFAULT_MONITOR_STREAM_SECONDS))
        try:
            return max(1.0, float(raw))
        except ValueError:
            return float(DEFAULT_MONITOR_STREAM_SECONDS)
