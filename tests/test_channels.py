"""Core tests for the IM channel layer — no platform SDK required."""

from __future__ import annotations

import asyncio
from typing import Any

from backend.channels.base import Channel
from backend.channels.binding import BindingStore
from backend.channels.manager import ChannelManager
from backend.channels.message_bus import MessageBus, OutboundMessage
from backend.channels.notifier import ChannelNotifier
from backend.schemas import SSEEvent


class FakeRepo:
    """Minimal config-store stand-in for BindingStore."""

    def __init__(self) -> None:
        self._cfg: dict[str, Any] = {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._cfg.get(key, default if default is not None else {})

    def set_config(self, key: str, payload: Any) -> Any:
        self._cfg[key] = payload
        return payload


class FakeRun:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.task_id = "task_x"
        self.session_id = None


class FakeCopilot:
    def __init__(self, conclusion: str = "你好，我是投研助手") -> None:
        self.conclusion = conclusion
        self.requests: list[Any] = []

    def create_run(self, request: Any) -> FakeRun:
        self.requests.append(request)
        return FakeRun("run_fake")

    async def stream_run(self, run_id: str, session_id: str | None = None):
        yield SSEEvent(run_id=run_id, task_id="task_x", type="final", payload={"conclusion": self.conclusion})


class FakeChannel(Channel):
    name = "fake"

    def __init__(self, bus: MessageBus) -> None:
        super().__init__(bus, {})
        self.sent: list[OutboundMessage] = []

    async def start(self) -> None:
        self._running = True

    async def stop(self) -> None:
        self._running = False

    async def send(self, msg: OutboundMessage) -> None:
        self.sent.append(msg)


def _setup(require_binding: bool = True):
    bus = MessageBus()
    repo = FakeRepo()
    store = BindingStore(repo)
    copilot = FakeCopilot()
    manager = ChannelManager(bus=bus, copilot_service=copilot, binding_store=store, require_binding=require_binding)
    channel = FakeChannel(bus)
    bus.subscribe_outbound(channel._on_outbound)
    return bus, repo, store, copilot, manager, channel


def _inbound(bus, text, chat_id="c1"):
    from backend.channels.message_bus import InboundMessage

    return InboundMessage(channel_name="fake", chat_id=chat_id, user_id="u1", text=text)


def test_connect_code_is_single_use():
    store = BindingStore(FakeRepo())
    code = store.create_code()
    assert store.consume_code(code) is True
    assert store.consume_code(code) is False  # already consumed
    assert store.consume_code("bogus") is False


def test_unbound_chat_is_rejected():
    async def run():
        bus, repo, store, copilot, manager, channel = _setup(require_binding=True)
        await manager._handle(_inbound(bus, "你好"))
        return copilot, channel

    copilot, channel = asyncio.run(run())
    assert copilot.requests == []  # copilot never invoked
    assert channel.sent and "未绑定" in channel.sent[0].text


def test_connect_then_chat_flows_to_copilot():
    async def run():
        bus, repo, store, copilot, manager, channel = _setup(require_binding=True)
        code = store.create_code()
        await manager._handle(_inbound(bus, f"/connect {code}"))
        await manager._handle(_inbound(bus, "分析一下贵州茅台"))
        return store, copilot, channel

    store, copilot, channel = asyncio.run(run())
    assert store.is_bound("fake", "c1")
    assert any("绑定成功" in m.text for m in channel.sent)
    assert len(copilot.requests) == 1
    assert copilot.requests[0].message == "分析一下贵州茅台"
    assert any(m.text == "你好，我是投研助手" for m in channel.sent)


def test_commands_help_new_status():
    async def run():
        bus, repo, store, copilot, manager, channel = _setup(require_binding=False)
        await manager._handle(_inbound(bus, "/help"))
        s0 = store.session_key("fake", "c1")
        await manager._handle(_inbound(bus, "/new"))
        s1 = store.session_key("fake", "c1")
        await manager._handle(_inbound(bus, "/status"))
        return channel, s0, s1

    channel, s0, s1 = asyncio.run(run())
    assert any("可用命令" in m.text for m in channel.sent)
    assert s0 != s1  # /new rotated the session


def test_notifier_broadcasts_to_bound_chats():
    async def run():
        bus = MessageBus()
        store = BindingStore(FakeRepo())
        store.bind("fake", "c1")
        store.bind("fake", "c2")
        channel = FakeChannel(bus)
        bus.subscribe_outbound(channel._on_outbound)
        notifier = ChannelNotifier(bus, store)
        await notifier._broadcast("🔴 盯盘告警")
        return channel

    channel = asyncio.run(run())
    assert {m.chat_id for m in channel.sent} == {"c1", "c2"}
    assert all("盯盘告警" in m.text for m in channel.sent)
