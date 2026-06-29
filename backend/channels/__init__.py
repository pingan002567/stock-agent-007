"""Minimal IM channel adapter layer.

Bridges external IM platforms (Telegram, Slack) to the in-process
``CopilotService`` and pushes monitor alerts back out. No public ingress:
every adapter uses an outbound connection (long-polling / Socket Mode).

See doc/IM_ADAPTER_MVP_DESIGN.md for the design.
"""

from backend.channels.message_bus import InboundMessage, MessageBus, OutboundMessage

__all__ = ["InboundMessage", "OutboundMessage", "MessageBus"]
