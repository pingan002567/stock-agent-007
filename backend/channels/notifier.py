"""ChannelNotifier — broadcast monitor alerts to bound IM chats.

The monitor evaluation runs in a worker thread, so ``push()`` is thread-safe:
it schedules the async broadcast onto the channel service's event loop via
``run_coroutine_threadsafe``. No-op until the loop is set (i.e. before the
channel service starts), so it's safe to wire at bootstrap time.
"""

from __future__ import annotations

import asyncio
import logging

from backend.channels.binding import BindingStore
from backend.channels.message_bus import MessageBus, OutboundMessage

logger = logging.getLogger("channels.notifier")


class ChannelNotifier:
    def __init__(self, bus: MessageBus, binding_store: BindingStore) -> None:
        self._bus = bus
        self._bindings = binding_store
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def push(self, title: str, text: str) -> None:
        """Thread-safe: schedule a push to the bound chats that opted in to
        alerts. No-op if the channel service isn't running yet."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        body = f"{title}\n{text}" if title else text
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(body), loop)
        except Exception:  # noqa: BLE001
            logger.exception("failed to schedule channel alert")

    async def _broadcast(self, text: str) -> None:
        for binding in self._bindings.alert_targets():
            await self._bus.publish_outbound(
                OutboundMessage(
                    channel_name=binding["channel"],
                    chat_id=binding["chat_id"],
                    text=text,
                    metadata={"kind": "alert"},
                )
            )
