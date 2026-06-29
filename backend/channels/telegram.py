"""Telegram adapter — long-polling (getUpdates), no public ingress.

Requires the optional ``[channels]`` extra (python-telegram-bot). The import
below raises ImportError when absent; ChannelService catches it and skips.
"""

from __future__ import annotations

import logging
from typing import Any

from telegram import Update
from telegram.ext import Application, ApplicationBuilder, ContextTypes, MessageHandler, filters

from backend.channels.base import Channel
from backend.channels.message_bus import OutboundMessage

logger = logging.getLogger("channels.telegram")


class TelegramChannel(Channel):
    name = "telegram"

    def __init__(self, bus: Any, config: dict[str, Any]) -> None:
        super().__init__(bus, config)
        self._token = str(config.get("bot_token") or "")
        self._app: Application | None = None

    async def start(self) -> None:
        if not self._token:
            logger.warning("[telegram] no bot_token; not starting")
            return
        app = ApplicationBuilder().token(self._token).build()
        app.add_handler(MessageHandler(filters.TEXT, self._on_message))
        await app.initialize()
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        self._app = app
        self._running = True

    async def stop(self) -> None:
        self._running = False
        if self._app is None:
            return
        try:
            if self._app.updater:
                await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()
        finally:
            self._app = None

    async def _on_message(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user
        if message is None or chat is None or not message.text:
            return
        text = message.text.strip()
        # Telegram deep-link bind: "/start <code>" → treat as "/connect <code>".
        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            text = f"/connect {parts[1].strip()}" if len(parts) > 1 else "/help"
        await self.bus.publish_inbound(
            self._make_inbound(
                chat_id=str(chat.id),
                user_id=str(user.id) if user else "",
                text=text,
                reply_to=str(message.message_id),
            )
        )

    async def send(self, msg: OutboundMessage) -> None:
        if self._app is None:
            return
        await self._send_with_retry(
            lambda: self._app.bot.send_message(chat_id=int(msg.chat_id), text=msg.text)
        )
