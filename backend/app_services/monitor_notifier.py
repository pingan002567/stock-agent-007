from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib.request import Request, urlopen

from backend.schemas import EventContext

logger = logging.getLogger("monitor_notifier")

FEISHU_WEBHOOK_URL = os.getenv("MONITOR_FEISHU_WEBHOOK_URL", "")
DINGTALK_WEBHOOK_URL = os.getenv("MONITOR_DINGTALK_WEBHOOK_URL", "")


def _feishu_payload(event: EventContext) -> dict[str, Any]:
    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"⚠ {event.title}"},
                "severity": "critical" if event.severity == "high" else "warning",
            },
            "elements": [
                {"tag": "markdown", "content": f"**标的**: {event.symbol}\n**规则**: {event.trigger_rule}\n**时间**: {event.triggered_at}"},
                {"tag": "hr" },
                {"tag": "markdown", "content": f"**建议操作**: {', '.join(event.suggested_actions[:3]) if event.suggested_actions else '查看详情'}"},
            ],
        },
    }


def _dingtalk_payload(event: EventContext) -> dict[str, Any]:
    title = f"[{event.severity.upper()}] {event.title}"
    text = f"### {title}\n- **标的**: {event.symbol}\n- **规则**: {event.trigger_rule}\n- **时间**: {event.triggered_at}\n- **建议**: {', '.join(event.suggested_actions[:3]) if event.suggested_actions else '查看详情'}"
    return {
        "msgtype": "markdown",
        "markdown": {"title": title[:64], "text": text},
    }


def dispatch_notification(event: EventContext) -> None:
    """Send event to configured webhooks."""
    if not FEISHU_WEBHOOK_URL and not DINGTALK_WEBHOOK_URL:
        return
    if event.severity not in ("high", "medium"):
        return
    for url, builder in [(FEISHU_WEBHOOK_URL, _feishu_payload), (DINGTALK_WEBHOOK_URL, _dingtalk_payload)]:
        if not url:
            continue
        try:
            payload = json.dumps(builder(event)).encode("utf-8")
            req = Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
            resp = urlopen(req, timeout=10)
            logger.info("notification sent to %s: %s", url[:40], resp.status)
        except Exception as exc:
            logger.warning("notification failed for %s: %s", url[:40], exc)
