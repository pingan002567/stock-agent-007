"""MessageBus — async pub/sub decoupling channel adapters from the dispatcher."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("channels.bus")


@dataclass
class InboundMessage:
    """A message arriving from an IM platform toward the dispatcher."""

    channel_name: str
    chat_id: str
    user_id: str
    text: str
    reply_to: str | None = None  # platform message id, for threaded replies
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


@dataclass
class OutboundMessage:
    """A message from the dispatcher back to a channel."""

    channel_name: str
    chat_id: str
    text: str
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


OutboundCallback = Callable[[OutboundMessage], Awaitable[None]]


class MessageBus:
    """Channels publish inbound; the dispatcher consumes. The dispatcher
    publishes outbound; channels receive via registered callbacks."""

    def __init__(self) -> None:
        self._inbound: asyncio.Queue[InboundMessage] = asyncio.Queue()
        self._outbound_listeners: list[OutboundCallback] = []

    async def publish_inbound(self, msg: InboundMessage) -> None:
        await self._inbound.put(msg)
        logger.info("[bus] inbound %s:%s qsize=%d", msg.channel_name, msg.chat_id, self._inbound.qsize())

    async def get_inbound(self) -> InboundMessage:
        return await self._inbound.get()

    def subscribe_outbound(self, callback: OutboundCallback) -> None:
        self._outbound_listeners.append(callback)

    def unsubscribe_outbound(self, callback: OutboundCallback) -> None:
        self._outbound_listeners = [cb for cb in self._outbound_listeners if cb != callback]

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        for cb in self._outbound_listeners:
            try:
                await cb(msg)
            except Exception:
                logger.exception("[bus] outbound callback failed for %s", msg.channel_name)
