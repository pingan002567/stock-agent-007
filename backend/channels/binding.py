"""Connect-code + allowlist binding, persisted via the repo config store.

Single-user simplification of deer-flow's multi-tenant channel_connections:
a binding is just an allowlist entry ``(channel, chat_id)`` that may talk to
the agent. A ``/connect <code>`` consumes a one-time browser-generated code and
adds the entry. Codes are 128-bit, expire in 10 minutes, and are single-use.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from typing import Any

from backend.persistence.repositories import WorkbenchRepository

_BINDINGS_KEY = "channels_bindings"
_CODES_KEY = "channels_connect_codes"
_SESSIONS_KEY = "channels_sessions"
_CODE_TTL_SECONDS = 600
_MAX_PENDING_CODES = 5


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


class BindingStore:
    def __init__(self, repo: WorkbenchRepository) -> None:
        self._repo = repo
        self._lock = threading.Lock()

    # -- allowlist --------------------------------------------------------

    @staticmethod
    def _key(channel: str, chat_id: str) -> str:
        return f"{channel}:{chat_id}"

    def is_bound(self, channel: str, chat_id: str) -> bool:
        bindings = self._repo.get_config(_BINDINGS_KEY, {}) or {}
        return self._key(channel, chat_id) in bindings

    def bind(self, channel: str, chat_id: str, *, label: str = "") -> None:
        with self._lock:
            bindings = self._repo.get_config(_BINDINGS_KEY, {}) or {}
            key = self._key(channel, chat_id)
            prev = bindings.get(key) or {}
            bindings[key] = {
                "label": label,
                "bound_at": prev.get("bound_at", time.time()),
                # re-binding keeps the prior alert preference; new bindings opt in
                "alerts_enabled": prev.get("alerts_enabled", True),
            }
            self._repo.set_config(_BINDINGS_KEY, bindings)

    def set_alerts_enabled(self, channel: str, chat_id: str, enabled: bool) -> bool:
        """Toggle whether this bound chat receives monitor alert pushes."""
        with self._lock:
            bindings = self._repo.get_config(_BINDINGS_KEY, {}) or {}
            meta = bindings.get(self._key(channel, chat_id))
            if meta is None:
                return False
            meta["alerts_enabled"] = bool(enabled)
            bindings[self._key(channel, chat_id)] = meta
            self._repo.set_config(_BINDINGS_KEY, bindings)
            return True

    def alert_targets(self) -> list[dict[str, Any]]:
        """Bindings that opted in to receive monitor alerts."""
        return [b for b in self.list_bindings() if b.get("alerts_enabled", True)]

    def unbind(self, channel: str, chat_id: str) -> bool:
        with self._lock:
            bindings = self._repo.get_config(_BINDINGS_KEY, {}) or {}
            removed = bindings.pop(self._key(channel, chat_id), None) is not None
            if removed:
                self._repo.set_config(_BINDINGS_KEY, bindings)
            return removed

    def list_bindings(self) -> list[dict[str, Any]]:
        bindings = self._repo.get_config(_BINDINGS_KEY, {}) or {}
        out: list[dict[str, Any]] = []
        for key, meta in bindings.items():
            channel, _, chat_id = key.partition(":")
            meta = meta or {}
            out.append(
                {
                    "channel": channel,
                    "chat_id": chat_id,
                    **meta,
                    "alerts_enabled": meta.get("alerts_enabled", True),
                }
            )
        return out

    # -- one-time connect codes ------------------------------------------

    def create_code(self) -> str:
        """Generate a one-time bind code; returns the plaintext (shown once)."""
        code = secrets.token_urlsafe(16)
        now = time.time()
        with self._lock:
            codes = self._repo.get_config(_CODES_KEY, {}) or {}
            # prune expired, then cap pending
            codes = {h: m for h, m in codes.items() if (m or {}).get("expires_at", 0) > now}
            if len(codes) >= _MAX_PENDING_CODES:
                # drop the soonest-to-expire to make room
                oldest = min(codes, key=lambda h: codes[h].get("expires_at", 0))
                codes.pop(oldest, None)
            codes[_hash(code)] = {"created_at": now, "expires_at": now + _CODE_TTL_SECONDS}
            self._repo.set_config(_CODES_KEY, codes)
        return code

    def consume_code(self, code: str) -> bool:
        """Validate + single-use-consume a code. Returns True if valid."""
        now = time.time()
        h = _hash(code.strip())
        with self._lock:
            codes = self._repo.get_config(_CODES_KEY, {}) or {}
            meta = codes.get(h)
            if not meta or meta.get("expires_at", 0) <= now:
                # also prune the expired entry if present
                if h in codes:
                    codes.pop(h, None)
                    self._repo.set_config(_CODES_KEY, codes)
                return False
            codes.pop(h, None)  # single use
            self._repo.set_config(_CODES_KEY, codes)
            return True

    # -- IM conversation -> CopilotService session id mapping -------------
    # CopilotService requires a real persisted session id (not a synthetic
    # key), so we store the mapping here and create the session on demand.

    def get_session_id(self, channel: str, chat_id: str) -> str | None:
        sessions = self._repo.get_config(_SESSIONS_KEY, {}) or {}
        return sessions.get(self._key(channel, chat_id))

    def set_session_id(self, channel: str, chat_id: str, session_id: str) -> None:
        with self._lock:
            sessions = self._repo.get_config(_SESSIONS_KEY, {}) or {}
            sessions[self._key(channel, chat_id)] = session_id
            self._repo.set_config(_SESSIONS_KEY, sessions)

    def clear_session(self, channel: str, chat_id: str) -> None:
        """Drop the mapping so the next message starts a fresh session (/new)."""
        with self._lock:
            sessions = self._repo.get_config(_SESSIONS_KEY, {}) or {}
            if sessions.pop(self._key(channel, chat_id), None) is not None:
                self._repo.set_config(_SESSIONS_KEY, sessions)
