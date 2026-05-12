from __future__ import annotations

from backend.schemas import EventContext, now_iso
from backend.stock_domain.provider_router import provider_router


def get_monitor_events() -> list[EventContext]:
    status = provider_router.status()
    provider_title = "provider-router 已回退到 mock_adapter" if status.active_provider == status.fallback_provider else "provider-router 已启用 optional AKShare"
    provider_rule = "primary_provider_unavailable" if status.active_provider == status.fallback_provider else "primary_provider_available"
    return [
        EventContext(
            event_id="event_aapl_concentration",
            source="risk_rule",
            symbol="AAPL",
            title="AAPL 仓位超过规则上限",
            severity="high",
            triggered_at=now_iso(),
            trigger_rule="single_position_weight > 15%",
            rule_type="single_position_weight_gt",
            evidence=[{"type": "portfolio_snapshot", "ref": "local_sqlite"}],
            suggested_actions=["open_stock_context", "run_risk_review", "generate_rebalance_plan"],
            payload={"symbol": "AAPL", "weight_pct": 18.6, "threshold": 15},
        ),
        EventContext(
            event_id="event_hk00700_sentiment",
            source="mock_news",
            symbol="HK00700",
            title="腾讯控股新闻情绪转弱",
            severity="medium",
            triggered_at=now_iso(),
            trigger_rule="negative_news_density >= medium",
            rule_type="intel_keyword_match",
            evidence=[{"type": "news_cluster", "ref": "mock_intel"}],
            suggested_actions=["open_stock_context", "tighten_monitor_rule"],
            payload={"symbol": "HK00700", "keyword": "情绪"},
        ),
        EventContext(
            event_id="event_data_source_fallback",
            source="provider-router",
            symbol="DATA",
            title=provider_title,
            severity="low",
            triggered_at=now_iso(),
            trigger_rule=provider_rule,
            rule_type="data_provider_degraded",
            evidence=[
                {"type": "active_provider", "ref": status.active_provider},
                {"type": "fallback_provider", "ref": status.fallback_provider},
            ],
            suggested_actions=["show_degraded_state"],
            payload={"active_provider": status.active_provider, "fallback_provider": status.fallback_provider},
        ),
    ]
