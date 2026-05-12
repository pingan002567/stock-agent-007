from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from backend.app_services.monitor_service import MonitorService
from backend.app_services.paper_portfolio_service import PaperPortfolioService
from backend.app_services.pre_trade_review_service import PreTradeReviewService
from backend.app_services.rebalance_draft_service import RebalanceDraftService
from backend.persistence.repositories import WorkbenchRepository
from backend.schemas import RebalanceDraftStatus, ReviewInboxItem, ReviewInboxState, ReviewInboxStateStatus, ReviewInboxSummary, now_iso


@dataclass(frozen=True)
class _OverlayedItem:
    item: ReviewInboxItem
    visible: bool
    snoozed: bool
    overdue: bool


class ReviewInboxService:
    def __init__(
        self,
        *,
        repo: WorkbenchRepository,
        rebalance_draft_service: RebalanceDraftService,
        pre_trade_review_service: PreTradeReviewService,
        monitor_service: MonitorService,
        paper_portfolio_service: PaperPortfolioService,
    ) -> None:
        self.repo = repo
        self.rebalance_draft_service = rebalance_draft_service
        self.pre_trade_review_service = pre_trade_review_service
        self.monitor_service = monitor_service
        self.paper_portfolio_service = paper_portfolio_service

    def list_items(self, *, priority: str | None = None, limit: int | None = None) -> list[ReviewInboxItem]:
        items = [entry.item for entry in self._overlay_items() if entry.visible]
        if priority:
            items = [item for item in items if item.priority == priority]
        if limit is not None:
            items = items[:limit]
        return items

    def summarize(self) -> ReviewInboxSummary:
        overlayed = self._overlay_items()
        visible = [entry for entry in overlayed if entry.visible]
        return ReviewInboxSummary(
            open_count=len(visible),
            high_count=sum(1 for entry in visible if entry.item.priority == "high"),
            overdue_count=sum(1 for entry in visible if entry.overdue),
            snoozed_count=sum(1 for entry in overlayed if entry.snoozed),
        )

    def get_current_item(self, item_key: str) -> ReviewInboxItem:
        states = self._state_map()
        for item in self._generate_items():
            if item.item_key == item_key:
                return self._apply_overlay(item, states.get(item.item_key)).item
        raise KeyError(item_key)

    def dismiss(self, item_key: str, *, note: str = "") -> ReviewInboxState:
        self.get_current_item(item_key)
        return self.repo.save_review_inbox_state(
            ReviewInboxState(
                item_key=item_key,
                status=ReviewInboxStateStatus.DISMISSED,
                snoozed_until=None,
                note=note or None,
                updated_at=now_iso(),
            )
        )

    def mark_done(self, item_key: str, *, note: str = "") -> ReviewInboxState:
        self.get_current_item(item_key)
        return self.repo.save_review_inbox_state(
            ReviewInboxState(
                item_key=item_key,
                status=ReviewInboxStateStatus.DONE,
                snoozed_until=None,
                note=note or None,
                updated_at=now_iso(),
            )
        )

    def snooze(self, item_key: str, *, snoozed_until: str, note: str = "") -> ReviewInboxState:
        self.get_current_item(item_key)
        return self.repo.save_review_inbox_state(
            ReviewInboxState(
                item_key=item_key,
                status=ReviewInboxStateStatus.OPEN,
                snoozed_until=snoozed_until,
                note=note or None,
                updated_at=now_iso(),
            )
        )

    def _overlay_items(self) -> list[_OverlayedItem]:
        states = self._state_map()
        items = [self._apply_overlay(item, states.get(item.item_key)) for item in self._generate_items()]
        items.sort(
            key=lambda entry: (
                0 if entry.item.priority == "high" else 1,
                0 if entry.overdue else 1,
                entry.item.occurred_at,
                entry.item.item_key,
            ),
        )
        return items

    def _state_map(self) -> dict[str, ReviewInboxState]:
        return {item.item_key: item for item in self.repo.list_review_inbox_states()}

    def _apply_overlay(self, item: ReviewInboxItem, state: ReviewInboxState | None) -> _OverlayedItem:
        status = state.status if state else ReviewInboxStateStatus.OPEN
        snoozed_until = state.snoozed_until if state else None
        note = state.note if state else None
        updated_at = state.updated_at if state else item.updated_at
        snooze_at = _parse_iso(snoozed_until)
        snoozed = bool(snooze_at and snooze_at > _utc_now())
        overdue = self._is_overdue(item)
        visible = status == ReviewInboxStateStatus.OPEN and not snoozed
        return _OverlayedItem(
            item=item.model_copy(
                update={
                    "status": status,
                    "snoozed_until": snoozed_until,
                    "note": note,
                    "updated_at": updated_at,
                }
            ),
            visible=visible,
            snoozed=snoozed,
            overdue=overdue,
        )

    def _generate_items(self) -> list[ReviewInboxItem]:
        items: list[ReviewInboxItem] = []
        items.extend(self._draft_items())
        items.extend(self._review_items())
        items.extend(self._journal_items())
        items.extend(self._monitor_items())
        items.extend(self._report_items())
        items.extend(self._snapshot_items())
        return items

    def _draft_items(self) -> list[ReviewInboxItem]:
        items: list[ReviewInboxItem] = []
        for draft in self.rebalance_draft_service.list(limit=200):
            if draft.status == RebalanceDraftStatus.PENDING_USER_CONFIRMATION:
                items.append(
                    ReviewInboxItem(
                        item_key=f"rebalance_draft:{draft.draft_id}:pending",
                        item_type="rebalance_draft_pending",
                        source_type="rebalance_draft",
                        source_id=draft.draft_id,
                        title=f"{draft.symbol} 调仓草案待人工确认",
                        summary=(
                            f"{draft.action} 目标仓位 {draft.target_weight_pct:.1f}% ，"
                            f"当前有效期至 {draft.valid_until[:19]}。"
                        ),
                        priority="medium",
                        severity=draft.status.value,
                        occurred_at=draft.created_at,
                        updated_at=draft.updated_at,
                        evidence_refs=list(draft.evidence_refs),
                        draft_id=draft.draft_id,
                    )
                )
            if draft.status == RebalanceDraftStatus.EXPIRED:
                items.append(
                    ReviewInboxItem(
                        item_key=f"rebalance_draft:{draft.draft_id}:expired",
                        item_type="rebalance_draft_expired",
                        source_type="rebalance_draft",
                        source_id=draft.draft_id,
                        title=f"{draft.symbol} 调仓草案已过期",
                        summary=(
                            f"{draft.action} 目标仓位 {draft.target_weight_pct:.1f}% 已过期，"
                            "需要重新确认是否重建草案。"
                        ),
                        priority="high",
                        severity=draft.status.value,
                        occurred_at=draft.expired_at or draft.valid_until,
                        updated_at=draft.updated_at,
                        evidence_refs=list(draft.evidence_refs),
                        draft_id=draft.draft_id,
                    )
                )
        return items

    def _review_items(self) -> list[ReviewInboxItem]:
        items: list[ReviewInboxItem] = []
        for review in self.pre_trade_review_service.list(limit=200):
            blockers = len(review.blocker_codes)
            warnings = sum(1 for item in review.checklist if item.get("status") == "warning")
            items.append(
                ReviewInboxItem(
                    item_key=f"pre_trade_review:{review.review_id}",
                    item_type="pre_trade_review",
                    source_type="pre_trade_review",
                    source_id=review.review_id,
                    title=f"{review.symbol} 交易前审查待处理",
                    summary=f"状态 {review.status.value}，blockers={blockers}，warnings={warnings}。",
                    priority="high" if review.status.value == "blocked" else "medium",
                    severity=review.status.value,
                    occurred_at=review.created_at,
                    updated_at=review.created_at,
                    evidence_refs=list(review.evidence_refs),
                    draft_id=review.source_draft_id,
                    review_id=review.review_id,
                )
            )
        return items

    def _journal_items(self) -> list[ReviewInboxItem]:
        items: list[ReviewInboxItem] = []
        for entry in self.repo.list_decision_journal_entries(limit=None):
            if entry.status != "paper_tracked":
                continue
            if not entry.snapshot_id:
                items.append(
                    ReviewInboxItem(
                        item_key=f"decision_journal:{entry.entry_id}:missing_snapshot",
                        item_type="decision_journal_missing_snapshot",
                        source_type="decision_journal_entry",
                        source_id=entry.entry_id,
                        title=f"{entry.symbol} 决策档案缺少 Snapshot",
                        summary="Paper tracked 链路尚未链接 snapshot，无法进入完整复盘闭环。",
                        priority="high",
                        severity=entry.status,
                        occurred_at=entry.updated_at,
                        updated_at=entry.updated_at,
                        evidence_refs=["decision_journal_entry", "paper_order", "paper_portfolio_snapshot"],
                        draft_id=entry.draft_id,
                        review_id=entry.review_id,
                        entry_id=entry.entry_id,
                    )
                )
                continue
            items.append(
                ReviewInboxItem(
                    item_key=f"decision_journal:{entry.entry_id}:not_closed",
                    item_type="decision_journal_not_closed",
                    source_type="decision_journal_entry",
                    source_id=entry.entry_id,
                    title=f"{entry.symbol} 决策档案待关闭",
                    summary="Snapshot 已链接，但该 paper tracked 链路尚未显式关闭。",
                    priority="medium",
                    severity=entry.status,
                    occurred_at=entry.updated_at,
                    updated_at=entry.updated_at,
                    evidence_refs=["decision_journal_entry", "paper_order", "paper_portfolio_snapshot"],
                    draft_id=entry.draft_id,
                    review_id=entry.review_id,
                    entry_id=entry.entry_id,
                    snapshot_id=entry.snapshot_id,
                    report_id=entry.report_id,
                )
            )
        return items

    def _monitor_items(self) -> list[ReviewInboxItem]:
        items: list[ReviewInboxItem] = []
        for event in self.monitor_service.list_events(limit=200):
            if event.severity not in {"high", "medium"}:
                continue
            items.append(
                ReviewInboxItem(
                    item_key=f"monitor_event:{event.event_id}",
                    item_type="monitor_event",
                    source_type="monitor_event",
                    source_id=event.event_id,
                    title=event.title,
                    summary=f"{event.symbol} · 规则 {event.trigger_rule} · 严重度 {event.severity}。",
                    priority="high" if event.severity == "high" else "medium",
                    severity=event.severity,
                    occurred_at=event.triggered_at,
                    updated_at=event.triggered_at,
                    evidence_refs=[ref.get("ref", "") for ref in event.evidence if ref.get("ref")] or ["monitor_event"],
                    event_id=event.event_id,
                )
            )
        return items

    def _report_items(self) -> list[ReviewInboxItem]:
        items: list[ReviewInboxItem] = []
        for report in self.repo.list_reports(limit=None):
            if report.quality_status not in {"warning", "failed"}:
                continue
            latest_check = self.repo.get_latest_report_quality_check(report.report_id)
            evidence_refs = list(latest_check.evidence_refs) if latest_check else list(report.evidence_refs)
            items.append(
                ReviewInboxItem(
                    item_key=f"report:{report.report_id}:quality",
                    item_type="report_quality",
                    source_type="report",
                    source_id=report.report_id,
                    title=f"{report.title} 质量待复核",
                    summary=report.quality_summary or "报告质量检查需要人工复核。",
                    priority="high" if report.quality_status == "failed" or report.degraded else "medium",
                    severity=report.quality_status,
                    occurred_at=report.created_at,
                    updated_at=latest_check.created_at if latest_check else report.created_at,
                    evidence_refs=evidence_refs,
                    event_id=report.source_id if report.source_type == "monitor_event" else None,
                    report_id=report.report_id,
                    snapshot_id=report.source_id if report.source_type == "paper_portfolio_snapshot" else None,
                )
            )
        return items

    def _snapshot_items(self) -> list[ReviewInboxItem]:
        items: list[ReviewInboxItem] = []
        for snapshot in self.paper_portfolio_service.list_snapshots(limit=200):
            if not snapshot.degraded:
                continue
            items.append(
                ReviewInboxItem(
                    item_key=f"paper_portfolio_snapshot:{snapshot.snapshot_id}:degraded",
                    item_type="paper_portfolio_snapshot_degraded",
                    source_type="paper_portfolio_snapshot",
                    source_id=snapshot.snapshot_id,
                    title=f"{snapshot.snapshot_id} Snapshot 已降级",
                    summary="Snapshot 基于降级行情生成，需要人工复核数据质量后再继续使用。",
                    priority="high",
                    severity="degraded",
                    occurred_at=snapshot.as_of,
                    updated_at=snapshot.created_at,
                    evidence_refs=["paper_portfolio_snapshot", "paper_portfolio_projection", "provider_router"],
                    snapshot_id=snapshot.snapshot_id,
                )
            )
        return items

    def _is_overdue(self, item: ReviewInboxItem) -> bool:
        return (
            item.item_key.endswith(":expired")
            or item.item_key.endswith(":missing_snapshot")
            or item.item_key.endswith(":not_closed")
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)
