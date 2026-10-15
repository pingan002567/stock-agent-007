"""ChannelService — wire config → adapters → manager, and own their lifecycle."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from backend.channels.base import Channel
from backend.channels.binding import BindingStore
from backend.channels.manager import ChannelManager
from backend.channels.message_bus import MessageBus
from backend.channels.notifier import ChannelNotifier
from backend.persistence.repositories import WorkbenchRepository

logger = logging.getLogger("channels.service")

_CONFIG_KEY = "channels"


def resolve_channels_config(repo: WorkbenchRepository) -> dict[str, Any]:
    """Merge repo config with env fallbacks. A channel auto-enables when its
    required secrets are present (config or env)."""
    cfg = dict(repo.get_config(_CONFIG_KEY, {}) or {})

    telegram = dict(cfg.get("telegram", {}))
    telegram.setdefault("bot_token", os.getenv("TELEGRAM_BOT_TOKEN", ""))
    if telegram.get("bot_token") and "enabled" not in telegram:
        telegram["enabled"] = True
    cfg["telegram"] = telegram

    slack = dict(cfg.get("slack", {}))
    slack.setdefault("bot_token", os.getenv("SLACK_BOT_TOKEN", ""))
    slack.setdefault("app_token", os.getenv("SLACK_APP_TOKEN", ""))
    if slack.get("bot_token") and slack.get("app_token") and "enabled" not in slack:
        slack["enabled"] = True
    cfg["slack"] = slack

    wecom = dict(cfg.get("wecom", {}))
    wecom.setdefault("bot_id", os.getenv("WECOM_BOT_ID", ""))
    wecom.setdefault("bot_secret", os.getenv("WECOM_BOT_SECRET", ""))
    if wecom.get("bot_id") and wecom.get("bot_secret") and "enabled" not in wecom:
        wecom["enabled"] = True
    cfg["wecom"] = wecom

    cfg.setdefault("require_binding", True)
    cfg.setdefault("authority_level", "A2")
    return cfg


class ChannelService:
    def __init__(
        self,
        *,
        bus: MessageBus,
        manager: ChannelManager,
        notifier: ChannelNotifier,
        repo: WorkbenchRepository,
    ) -> None:
        self.bus = bus
        self.manager = manager
        self.notifier = notifier
        self._repo = repo
        self._channels: list[Channel] = []
        self._started = False
        self._reload_lock = asyncio.Lock()

    @property
    def is_running(self) -> bool:
        return self._started

    def _build_channels(self, cfg: dict[str, Any]) -> list[Channel]:
        channels: list[Channel] = []
        # Lazy imports so the SDK is optional ([channels] extra).
        if cfg.get("telegram", {}).get("enabled") and cfg["telegram"].get("bot_token"):
            try:
                from backend.channels.telegram import TelegramChannel

                channels.append(TelegramChannel(self.bus, cfg["telegram"]))
            except ImportError:
                logger.warning("telegram enabled but python-telegram-bot not installed; skipping")
        if cfg.get("slack", {}).get("enabled") and cfg["slack"].get("bot_token") and cfg["slack"].get("app_token"):
            try:
                from backend.channels.slack import SlackChannel

                channels.append(SlackChannel(self.bus, cfg["slack"]))
            except ImportError:
                logger.warning("slack enabled but slack-sdk not installed; skipping")
        if cfg.get("wecom", {}).get("enabled") and cfg["wecom"].get("bot_id") and cfg["wecom"].get("bot_secret"):
            try:
                from backend.channels.wecom import WeComChannel

                channels.append(WeComChannel(self.bus, cfg["wecom"]))
            except ImportError:
                logger.warning("wecom enabled but wecom-aibot-python-sdk not installed; skipping")
        return channels

    async def start(self) -> None:
        if self._started:
            return
        cfg = resolve_channels_config(self._repo)
        self.manager.require_binding = bool(cfg.get("require_binding", True))
        self.manager.authority_level = str(cfg.get("authority_level", "A2"))
        self.notifier.set_loop(asyncio.get_running_loop())

        self._channels = self._build_channels(cfg)
        if not self._channels:
            logger.info("no IM channels configured; channel service idle")
            return

        await self.manager.start()
        for ch in self._channels:
            self.bus.subscribe_outbound(ch._on_outbound)
            try:
                await ch.start()
                logger.info("channel started: %s", ch.name)
            except Exception:
                logger.exception("failed to start channel %s", ch.name)
        self._started = True

    async def stop(self) -> None:
        for ch in self._channels:
            try:
                await ch.stop()
            except Exception:
                logger.exception("failed to stop channel %s", ch.name)
            self.bus.unsubscribe_outbound(ch._on_outbound)
        await self.manager.stop()
        self._channels = []
        self._started = False

    async def reload(self) -> None:
        """Re-read config and restart channels (used after the config changes,
        since adapters are built once at start time)."""
        async with self._reload_lock:
            await self.stop()
            await self.start()

    def status(self) -> dict[str, Any]:
        return {
            "running": self._started,
            "channels": [{"name": c.name, "running": c.is_running} for c in self._channels],
        }


def build_channel_service(
    *, repo: WorkbenchRepository, copilot_service: Any
) -> tuple[ChannelService, BindingStore, ChannelNotifier]:
    """Composition helper used by bootstrap."""
    bus = MessageBus()
    binding_store = BindingStore(repo)
    cfg = resolve_channels_config(repo)
    manager = ChannelManager(
        bus=bus,
        copilot_service=copilot_service,
        binding_store=binding_store,
        require_binding=bool(cfg.get("require_binding", True)),
        authority_level=str(cfg.get("authority_level", "A2")),
    )
    notifier = ChannelNotifier(bus, binding_store)
    service = ChannelService(bus=bus, manager=manager, notifier=notifier, repo=repo)
    return service, binding_store, notifier
