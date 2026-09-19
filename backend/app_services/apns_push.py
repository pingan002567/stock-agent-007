"""APNs push helper for monitor alerts and scheduled-task outcomes.

Optional credentials via env:
  APNS_KEY_ID, APNS_TEAM_ID, APNS_BUNDLE_ID, APNS_KEY_PATH
Without credentials, device registration still works; send is a logged no-op.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class APNsPushService:
    def __init__(self, list_devices: Callable[[], list[dict]]) -> None:
        self._list_devices = list_devices
        self._key_id = _env("APNS_KEY_ID")
        self._team_id = _env("APNS_TEAM_ID")
        self._bundle_id = _env("APNS_BUNDLE_ID", "com.stockagent.app")
        self._key_path = Path(
            _env("APNS_KEY_PATH", "/opt/stock-agent/secrets/AuthKey_APNS.p8")
        )
        self._jwt: str | None = None
        self._jwt_exp = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._key_id and self._team_id and self._key_path.is_file())

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "bundle_id": self._bundle_id,
            "device_count": len(self._list_devices()),
            "key_path_exists": self._key_path.is_file(),
        }

    def push(
        self,
        title: str,
        body: str = "",
        *,
        symbol: str | None = None,
        event_id: str | None = None,
        kind: str | None = None,
        session_id: str | None = None,
        report_id: str | None = None,
        task_id: str | None = None,
        **_: Any,
    ) -> None:
        devices = self._list_devices()
        if not devices:
            return
        if not self.configured:
            logger.info(
                "APNs not configured; skip push to %s device(s): %s",
                len(devices),
                title[:80],
            )
            return
        for device in devices:
            try:
                self._send(
                    device_token=device["device_token"],
                    environment=device.get("environment") or "sandbox",
                    title=title,
                    body=body,
                    symbol=symbol,
                    event_id=event_id,
                    kind=kind,
                    session_id=session_id,
                    report_id=report_id,
                    task_id=task_id,
                )
            except Exception:
                logger.exception("APNs send failed for %s…", device["device_token"][:8])

    def _send(
        self,
        *,
        device_token: str,
        environment: str,
        title: str,
        body: str,
        symbol: str | None,
        event_id: str | None = None,
        kind: str | None = None,
        session_id: str | None = None,
        report_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        import httpx

        token = self._bearer()
        host = (
            "api.push.apple.com"
            if environment == "production"
            else "api.sandbox.push.apple.com"
        )
        payload: dict[str, Any] = {
            "aps": {
                "alert": {"title": title, "body": body or title},
                "sound": "default",
            },
        }
        if kind:
            payload["kind"] = kind
        if symbol:
            payload["symbol"] = symbol
        if event_id:
            payload["event_id"] = event_id
        if session_id:
            payload["session_id"] = session_id
        if report_id:
            payload["report_id"] = report_id
        if task_id:
            payload["task_id"] = task_id
        url = f"https://{host}/3/device/{device_token}"
        headers = {
            "authorization": f"bearer {token}",
            "apns-topic": self._bundle_id,
            "apns-push-type": "alert",
            "apns-priority": "10",
        }
        # Apple requires HTTP/2; fall back gracefully if h2 extra missing.
        try:
            client = httpx.Client(http2=True, timeout=15.0)
        except Exception:
            logger.warning("httpx HTTP/2 unavailable; APNs send skipped")
            return
        with client:
            resp = client.post(url, headers=headers, content=json.dumps(payload))
            if resp.status_code >= 300:
                logger.warning("APNs HTTP %s: %s", resp.status_code, resp.text[:200])

    def _bearer(self) -> str:
        now = time.time()
        if self._jwt and now < self._jwt_exp - 60:
            return self._jwt
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import ec, utils
        except ImportError as exc:
            raise RuntimeError("cryptography package required for APNs JWT") from exc

        key_pem = self._key_path.read_bytes()
        private_key = serialization.load_pem_private_key(key_pem, password=None)
        header = _b64url(json.dumps({"alg": "ES256", "kid": self._key_id}, separators=(",", ":")).encode())
        claims = _b64url(json.dumps({"iss": self._team_id, "iat": int(now)}, separators=(",", ":")).encode())
        signing_input = f"{header}.{claims}".encode("ascii")
        signature = private_key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
        # Convert DER ECDSA signature to raw r||s (64 bytes) for JWT.
        r, s = utils.decode_dss_signature(signature)
        sig = _b64url(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
        self._jwt = f"{header}.{claims}.{sig}"
        self._jwt_exp = now + 3500
        return self._jwt


class CompositeAlertSink:
    """Fan-out alerts to IM channel sink and APNs."""

    def __init__(self, *sinks: Callable[..., None] | None) -> None:
        self._sinks = [s for s in sinks if s is not None]

    def __call__(
        self,
        title: str,
        body: str = "",
        *,
        symbol: str | None = None,
        event_id: str | None = None,
        kind: str | None = None,
        session_id: str | None = None,
        report_id: str | None = None,
        task_id: str | None = None,
        **extra: Any,
    ) -> None:
        kwargs = {
            "symbol": symbol,
            "event_id": event_id,
            "kind": kind,
            "session_id": session_id,
            "report_id": report_id,
            "task_id": task_id,
            **extra,
        }
        for sink in self._sinks:
            try:
                try:
                    sink(title, body, **kwargs)
                except TypeError:
                    sink(title, body)
            except Exception:
                logger.exception("alert sink failed")
