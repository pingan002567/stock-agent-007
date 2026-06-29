"""ChannelManager — consume inbound IM messages, run the Copilot, reply."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from backend.app_services.copilot_service import CopilotService
from backend.app_services.permission_guard import PermissionDenied
from backend.channels.binding import BindingStore
from backend.channels.message_bus import InboundMessage, MessageBus, OutboundMessage
from backend.schemas import AuthorityLevel, CopilotRequest

logger = logging.getLogger("channels.manager")

_HELP = (
    "可用命令：\n"
    "/connect <code> — 绑定本会话（先在网页端生成连接码）\n"
    "/new — 开启新对话（清空多轮上下文）\n"
    "/status — 查看绑定状态\n"
    "/help — 显示帮助\n"
    "直接发消息即可与 AI 投研助手对话。"
)
_MAX_CONCURRENCY = 4
_MAX_REPLY_CHARS = 3500


class ChannelManager:
    def __init__(
        self,
        *,
        bus: MessageBus,
        copilot_service: CopilotService,
        binding_store: BindingStore,
        require_binding: bool = True,
        authority_level: str = "A2",
    ) -> None:
        self.bus = bus
        self.copilot = copilot_service
        self.bindings = binding_store
        self.require_binding = require_binding
        self.authority_level = authority_level
        self._task: asyncio.Task[None] | None = None
        self._sem = asyncio.Semaphore(_MAX_CONCURRENCY)
        self._convo_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._inflight: set[asyncio.Task[None]] = set()  # hold refs so tasks aren't GC'd

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._dispatch_loop(), name="channels-dispatch")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _dispatch_loop(self) -> None:
        while True:
            msg = await self.bus.get_inbound()
            task = asyncio.create_task(self._handle(msg))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    # -- dispatch ---------------------------------------------------------

    async def _reply(self, msg: InboundMessage, text: str) -> None:
        await self.bus.publish_outbound(
            OutboundMessage(
                channel_name=msg.channel_name,
                chat_id=msg.chat_id,
                text=text[:_MAX_REPLY_CHARS],
                reply_to=msg.reply_to,
            )
        )

    async def _handle(self, msg: InboundMessage) -> None:
        try:
            text = (msg.text or "").strip()
            # /connect is processed BEFORE the binding gate so a new chat can bind.
            if text.lower().startswith("/connect"):
                await self._handle_connect(msg, text)
                return
            if self.require_binding and not self.bindings.is_bound(msg.channel_name, msg.chat_id):
                await self._reply(msg, "本会话未绑定。请在网页端「IM 渠道」生成连接码，然后发送 /connect <code>。")
                return
            if text.startswith("/"):
                await self._handle_command(msg, text)
                return
            await self._handle_chat(msg, text)
        except Exception:
            logger.exception("[manager] handle failed (%s:%s)", msg.channel_name, msg.chat_id)
            await self._reply(msg, "处理消息时出错，请稍后重试。")

    async def _handle_connect(self, msg: InboundMessage, text: str) -> None:
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        if not code:
            await self._reply(msg, "用法：/connect <code>")
            return
        if self.bindings.consume_code(code):
            self.bindings.bind(msg.channel_name, msg.chat_id, label=msg.user_id)
            await self._reply(msg, "✅ 绑定成功！现在可以直接对话了。发送 /help 查看命令。")
        else:
            await self._reply(msg, "❌ 连接码无效或已过期，请在网页端重新生成。")

    async def _handle_command(self, msg: InboundMessage, text: str) -> None:
        command = text.split(maxsplit=1)[0].lower().removeprefix("/")
        if command == "help":
            await self._reply(msg, _HELP)
        elif command == "new":
            self.bindings.rotate_session(msg.channel_name, msg.chat_id)
            await self._reply(msg, "🆕 已开启新对话。")
        elif command == "status":
            bound = self.bindings.is_bound(msg.channel_name, msg.chat_id)
            session = self.bindings.session_key(msg.channel_name, msg.chat_id)
            await self._reply(msg, f"绑定：{'已绑定' if bound else '未绑定'}\n会话：{session}")
        else:
            await self._reply(msg, f"未知命令 /{command}。\n\n{_HELP}")

    async def _handle_chat(self, msg: InboundMessage, text: str) -> None:
        session_key = self.bindings.session_key(msg.channel_name, msg.chat_id)
        lock = self._convo_locks[session_key]
        if lock.locked():
            await self._reply(msg, "⏳ 上一条还在处理中，请稍候。")
            return
        async with self._sem, lock:
            reply = await self._run_copilot(session_key, text, page=msg.metadata.get("page", "overview"))
            await self._reply(msg, reply)

    async def _run_copilot(self, session_key: str, text: str, *, page: str) -> str:
        request = CopilotRequest(
            message=text,
            page=page,
            session_id=session_key,
            authority_level=AuthorityLevel(self.authority_level),
        )
        try:
            run = self.copilot.create_run(request)
        except PermissionDenied:
            return "该请求需要更高权限，请在网页端操作。"
        except (KeyError, ValueError) as exc:
            return f"无法处理该请求：{exc}"

        final_text = ""
        try:
            async for event in self.copilot.stream_run(run.run_id, session_id=session_key):
                payload: dict[str, Any] = event.payload or {}
                if event.type in ("final", "final_answer"):
                    conclusion = str(payload.get("conclusion") or "").strip()
                    if conclusion:
                        final_text = conclusion
                elif event.type == "error" and not final_text:
                    final_text = f"AI 处理出错：{payload.get('error') or '未知错误'}"
        except Exception:
            logger.exception("[manager] copilot stream failed")
            return "AI 流处理异常中断，请重试。"
        return final_text or "（AI 未返回内容）"
