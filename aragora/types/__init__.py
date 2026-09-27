"""
Type definitions and protocols for Aragora.

Provides structural typing via protocols to enable
duck typing while maintaining type safety.
"""

from aragora.protocols import (
    EventHandlerProtocol,
    LegacyEventEmitterProtocol as EventEmitterProtocol,
    SyncEventHandlerProtocol,
)

__all__ = [
    "EventEmitterProtocol",
    "EventHandlerProtocol",
    "SyncEventHandlerProtocol",
]
