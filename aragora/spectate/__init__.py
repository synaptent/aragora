"""Spectator Mode - Real-time debate observation."""

from aragora.events.spectate.events import SpectatorEvents
from aragora.events.spectate.stream import SpectatorStream
from aragora.events.spectate.ws_bridge import (
    SpectateEvent,
    SpectateWebSocketBridge,
    bind_spectate_context,
    get_spectate_bridge,
)

__all__ = [
    "SpectatorEvents",
    "SpectatorStream",
    "SpectateEvent",
    "SpectateWebSocketBridge",
    "bind_spectate_context",
    "get_spectate_bridge",
]
