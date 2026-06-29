"""企业微信智能机器人 adapter — WebSocket (wecom-aibot-python-sdk), no public ingress.

Requires the optional ``[channels]`` extra (wecom-aibot-python-sdk>=1.0.0).
Unlike Telegram/Slack, WeCom replies are tied to the *inbound frame*: we stash
the frame + a stream id per message, open a streaming reply immediately ("处理
中…") to keep the session alive while the agent runs, then finalise it when the
outbound message arrives. Proactive alerts (no frame) use ``send_message``.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import Any

from aibot import WSClient, WSClientOptions, generate_req_id

from backend.channels.base import Channel
from backend.channels.message_bus import OutboundMessage

logger = logging.getLogger("channels.wecom")

_MAX_TRACKED = 256


class WeComChannel(Channel):
    name = "wecom"

    def __init__(self, bus: Any, config: dict[str, Any]) -> None:
        super().__init__(bus, config)
        self._bot_id = str(config.get("bot_id") or "")
        self._bot_secret = str(config.get("bot_secret") or "")
        self._working_message = str(config.get("working_message") or "处理中…")
        self._client: WSClient | None = None
        self._task: asyncio.Task[Any] | None = None
        # msg_id -> (frame, stream_id); bounded to avoid unbounded growth
        self._frames: OrderedDict[str, tuple[dict, str]] = OrderedDict()

    async def start(self) -> None:
        if not (self._bot_id and self._bot_secret):
            logger.warning("[wecom] missing bot_id/bot_secret; not starting")
            return
        client = WSClient(WSClientOptions(bot_id=self._bot_id, secret=self._bot_secret, logger=logger))
        client.on("message.text", self._on_text)
        client.on("message.mixed", self._on_mixed)
        client.on("error", lambda e: logger.error("[wecom] ws error: %s", e))
        client.on("disconnected", lambda *a: logger.warning("[wecom] disconnected; will reconnect"))
        self._client = client
        self._task = asyncio.create_task(client.connect())
        self._task.add_done_callback(self._on_connect_done)
        self._running = True

    def _on_connect_done(self, task: asyncio.Task[Any]) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "[wecom] WebSocket 连接任务退出：%s。检查 bot_id/bot_secret 是否正确、"
                "网络是否放通 wss://openws.work.weixin.qq.com",
                exc,
            )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
        self._frames.clear()

    # -- inbound ----------------------------------------------------------

    async def _on_text(self, frame: dict[str, Any]) -> None:
        body = frame.get("body", {}) or {}
        text = ((body.get("text") or {}).get("content") or "").strip()
        await self._ingest(frame, text)

    async def _on_mixed(self, frame: dict[str, Any]) -> None:
        body = frame.get("body", {}) or {}
        items = (body.get("mixed") or {}).get("msg_item") or []
        parts = [
            ((it or {}).get("text") or {}).get("content", "").strip()
            for it in items
            if (it or {}).get("msgtype") == "text"
        ]
        await self._ingest(frame, "\n".join(p for p in parts if p).strip())

    async def _ingest(self, frame: dict[str, Any], text: str) -> None:
        if not text or self._client is None:
            return
        body = frame.get("body", {}) or {}
        msg_id = body.get("msgid")
        user_id = (body.get("from") or {}).get("userid")
        if not msg_id or not user_id:
            return
        stream_id = generate_req_id("stream")
        self._frames[msg_id] = (frame, stream_id)
        while len(self._frames) > _MAX_TRACKED:
            self._frames.popitem(last=False)
        # Open the stream so the WeCom session stays alive while the agent runs.
        try:
            await self._client.reply_stream(frame, stream_id, self._working_message, False)
        except Exception:
            logger.exception("[wecom] failed to open reply stream")
        await self.bus.publish_inbound(
            self._make_inbound(chat_id=str(user_id), user_id=str(user_id), text=text, reply_to=str(msg_id))
        )

    # -- outbound ---------------------------------------------------------

    async def send(self, msg: OutboundMessage) -> None:
        if self._client is None:
            return
        tracked = self._frames.pop(msg.reply_to, None) if msg.reply_to else None
        if tracked is not None:
            frame, stream_id = tracked
            try:
                await self._client.reply_stream(frame, stream_id, msg.text, True)
                return
            except Exception:
                logger.exception("[wecom] reply_stream finalize failed; falling back to send_message")
        # Proactive (alert) or expired frame → send by chat id (WeCom userid).
        await self._send_with_retry(
            lambda: self._client.send_message(msg.chat_id, {"text": {"content": msg.text}})
        )
