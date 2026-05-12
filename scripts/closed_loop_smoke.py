from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import create_app
from backend.schemas import PriceSnapshot


def _pre_trade_quote(symbol: str) -> PriceSnapshot:
    return PriceSnapshot(
        last=386.8 if symbol.upper() == "HK00700" else 193.7,
        change_pct=0.3,
        updated_at="2026-05-13T08:00:00+00:00",
        source="mock_adapter",
        degraded=False,
        degraded_reason=None,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="closed-loop-smoke-") as temp_dir:
        root = Path(temp_dir)
        app = create_app(db_path=root / "closed-loop.sqlite3", files_root=root / "files")
        services = app.state.services
        paper_prices = {
            item.symbol: round(item.market_value / item.quantity, 6) if item.quantity > 0 else 0.0
            for item in services.repo.list_holdings()
        }
        paper_prices["HK00700"] = 386.8
        pre_trade_original = services.pre_trade_review_service.create.__globals__["provider_router"].get_quote
        paper_original = services.paper_portfolio_service.get_projection.__globals__["provider_router"].get_quote
        services.pre_trade_review_service.create.__globals__["provider_router"].get_quote = _pre_trade_quote
        services.paper_portfolio_service.get_projection.__globals__["provider_router"].get_quote = lambda symbol: PriceSnapshot(
            last=paper_prices[symbol.upper()],
            change_pct=0.0,
            updated_at="2026-05-13T08:00:00+00:00",
            source="mock_adapter",
            degraded=False,
            degraded_reason=None,
        )
        try:
            client = TestClient(app)
            risk = client.get("/api/holdings/risk")
            if risk.status_code != 200:
                print(risk.text, file=sys.stderr)
                return 1

            draft = client.post("/api/rebalance-drafts", json={"symbol": "HK00700", "target_weight_pct": 8})
            if draft.status_code != 200:
                print(draft.text, file=sys.stderr)
                return 1
            draft_payload = draft.json()

            confirmed = client.post(
                f"/api/rebalance-drafts/{draft_payload['draft_id']}/confirm",
                json={"note": "closed-loop smoke"},
            )
            if confirmed.status_code != 200:
                print(confirmed.text, file=sys.stderr)
                return 1

            review = client.post("/api/pre-trade-reviews", json={"draft_id": draft_payload["draft_id"]})
            if review.status_code != 200:
                print(review.text, file=sys.stderr)
                return 1
            review_payload = review.json()

            order = client.post("/api/paper-orders", json={"review_id": review_payload["review_id"]})
            if order.status_code != 200:
                print(order.text, file=sys.stderr)
                return 1
            order_payload = order.json()

            snapshot = client.post("/api/paper-portfolio/snapshots")
            if snapshot.status_code != 200:
                print(snapshot.text, file=sys.stderr)
                return 1
            snapshot_payload = snapshot.json()

            report = client.post(
                "/api/reports/generate",
                json={
                    "report_type": "paper_portfolio_review",
                    "source_type": "paper_portfolio_snapshot",
                    "source_id": snapshot_payload["snapshot_id"],
                },
            )
            if report.status_code != 200:
                print(report.text, file=sys.stderr)
                return 1
            report_payload = report.json()

            entry = next(
                item
                for item in client.get("/api/decision-journal").json()["items"]
                if item["decision_id"] == draft_payload["decision_id"]
            )

            linked = client.post(
                f"/api/decision-journal/{entry['entry_id']}/link-snapshot",
                json={"snapshot_id": snapshot_payload["snapshot_id"]},
            )
            if linked.status_code != 200:
                print(linked.text, file=sys.stderr)
                return 1

            closed = client.post(
                f"/api/decision-journal/{entry['entry_id']}/close",
                json={"close_note": "smoke complete"},
            )
            if closed.status_code != 200:
                print(closed.text, file=sys.stderr)
                return 1

            done = client.post(
                f"/api/review-inbox/pre_trade_review:{review_payload['review_id']}/mark-done",
                json={"note": "smoke archived"},
            )
            if done.status_code != 200:
                print(done.text, file=sys.stderr)
                return 1

            summary = {
                "review_status": review_payload["status"],
                "paper_order_status": order_payload["status"],
                "journal_status": closed.json()["status"],
                "closed_count": client.get("/api/decision-journal/summary").json()["closed_count"],
                "open_inbox_count": client.get("/api/review-inbox/summary").json()["open_count"],
            }

            print(f"risk_decision={risk.json()['decision']}")
            print(f"draft_id={draft_payload['draft_id']}")
            print(f"review_id={review_payload['review_id']}")
            print(f"paper_order_id={order_payload['order_id']}")
            print(f"snapshot_id={snapshot_payload['snapshot_id']}")
            print(f"report_id={report_payload['report_id']}")
            print(f"journal_entry_id={entry['entry_id']}")
            print("summary=" + json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return 0
        finally:
            services.pre_trade_review_service.create.__globals__["provider_router"].get_quote = pre_trade_original
            services.paper_portfolio_service.get_projection.__globals__["provider_router"].get_quote = paper_original


if __name__ == "__main__":
    raise SystemExit(main())
