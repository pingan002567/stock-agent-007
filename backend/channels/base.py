"""Abstract base class for IM channel adapters."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from backend.channels.message_bus import InboundMessage, MessageBus, OutboundMessage

logger = logging.getLogger("channels.base")

T = TypeVar("T")


class Channel(ABC):
    """Each adapter connects to one platform and:

    1. receives messages, wraps them as ``InboundMessage``, publishes to the bus;
    2. subscribes to outbound messages and sends replies back to the platform.

    Subclasses implement ``start``, ``stop`` and ``send``.
    """

    name: str = "base"

    def __init__(self, bus: MessageBus, config: dict[str, Any]) -> None:
        self.bus = bus
        self.config = config
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    async def send(self, msg: OutboundMessage) -> None: ...

    # -- helpers ----------------------------------------------------------

    def _make_inbound(self, chat_id: str, user_id: str, text: str, *, reply_to: str | None = None,
                      metadata: dict[str, Any] | None = None) -> InboundMessage:
        return InboundMessage(
            channel_name=self.name,
            chat_id=str(chat_id),
            user_id=str(user_id),
            text=text,
            reply_to=reply_to,
            metadata=metadata or {},
        )

    async def _on_outbound(self, msg: OutboundMessage) -> None:
        """Bus callback — only forward messages addressed to this channel."""
        if msg.channel_name != self.name:
            return
        try:
            await self.send(msg)
        except Exception:
            logger.exception("[%s] send failed (chat_id=%s)", self.name, msg.chat_id)

    async def _send_with_retry(self, op: Callable[[], Awaitable[T]], *, max_retries: int = 3) -> T:
        last: Exception | None = None
        for attempt in range(max_retries):
            try:
                return await op()
            except Exception as exc:  # noqa: BLE001
                last = exc
                if attempt < max_retries - 1:
                    await asyncio.sleep(2**attempt)
        assert last is not None
        raise last
