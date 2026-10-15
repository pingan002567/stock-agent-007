"""Slack adapter — Socket Mode (outbound WebSocket), no public ingress.

Requires the optional ``[channels]`` extra (slack-sdk). Needs both a bot token
(xoxb-, Web API) and an app-level token (xapp-, Socket Mode).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

from backend.channels.base import Channel
from backend.channels.message_bus import OutboundMessage

logger = logging.getLogger("channels.slack")


class SlackChannel(Channel):
    name = "slack"

    def __init__(self, bus: Any, config: dict[str, Any]) -> None:
        super().__init__(bus, config)
        self._bot_token = str(config.get("bot_token") or "")
        self._app_token = str(config.get("app_token") or "")
        self._web: WebClient | None = None
        self._client: SocketModeClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def start(self) -> None:
        if not (self._bot_token and self._app_token):
            logger.warning("[slack] missing bot_token/app_token; not starting")
            return
        self._loop = asyncio.get_running_loop()
        self._web = WebClient(token=self._bot_token)
        self._client = SocketModeClient(app_token=self._app_token, web_client=self._web)
        self._client.socket_mode_request_listeners.append(self._on_request)
        # connect() starts the websocket in a background thread (non-blocking).
        self._client.connect()
        self._running = True

    async def stop(self) -> None:
        self._running = False
        if self._client is not None:
            try:
                self._client.disconnect()
            finally:
                self._client = None
        self._web = None

    def _on_request(self, client: SocketModeClient, req: SocketModeRequest) -> None:
        # Called from the slack-sdk websocket thread. Ack first, then bridge.
        try:
            client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        except Exception:
            logger.exception("[slack] ack failed")
        if req.type != "events_api":
            return
        event = (req.payload or {}).get("event", {})
        if event.get("type") != "message" or event.get("bot_id") or event.get("subtype"):
            return
        text = (event.get("text") or "").strip()
        channel = event.get("channel")
        user = event.get("user")
        if not text or not channel:
            return
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        inbound = self._make_inbound(
            chat_id=str(channel),
            user_id=str(user or ""),
            text=text,
            reply_to=event.get("ts"),
            metadata={"team_id": (req.payload or {}).get("team_id")},
        )
        asyncio.run_coroutine_threadsafe(self.bus.publish_inbound(inbound), loop)

    async def send(self, msg: OutboundMessage) -> None:
        if self._web is None:
            return
        await self._send_with_retry(
            lambda: asyncio.to_thread(
                self._web.chat_postMessage, channel=msg.chat_id, text=msg.text
            )
        )
