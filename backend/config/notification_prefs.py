"""User notification preferences (scheduled-task completion push, etc.)."""

from __future__ import annotations

from typing import Any

CONFIG_KEY = "notification_prefs"

DEFAULT_NOTIFICATION_PREFS: dict[str, Any] = {
    # Success completion for duty / discovery scheduled tasks → alert_sink (IM + APNs).
    # Failures always notify regardless of this flag.
    "duty_completion_push": True,
}


def normalize_notification_prefs(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    return {
        "duty_completion_push": bool(
            source.get(
                "duty_completion_push",
                DEFAULT_NOTIFICATION_PREFS["duty_completion_push"],
            )
        ),
    }


def load_notification_prefs(repo: Any) -> dict[str, Any]:
    if repo is None:
        return dict(DEFAULT_NOTIFICATION_PREFS)
    try:
        stored = repo.get_config(CONFIG_KEY, DEFAULT_NOTIFICATION_PREFS)
    except Exception:
        stored = DEFAULT_NOTIFICATION_PREFS
    return normalize_notification_prefs(stored)
