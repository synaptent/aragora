"""Deprecated compatibility exports for protocols moved to ``aragora.protocols``.

Importing from ``aragora.types.protocols`` remains supported for one release,
but new code should use the canonical ``aragora.protocols`` package.
"""

import warnings

from aragora.protocols import (
    CacheProtocol,
    EventData,
    EventHandlerProtocol,
    LegacyAgentProtocol,
    LegacyEventEmitterProtocol,
    LegacyMemoryProtocol,
    StorageProtocol,
    SyncEventHandlerProtocol,
)

AgentProtocol = LegacyAgentProtocol
EventEmitterProtocol = LegacyEventEmitterProtocol
MemoryProtocol = LegacyMemoryProtocol

warnings.warn(
    "aragora.types.protocols is deprecated; import protocols from aragora.protocols instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = [
    "AgentProtocol",
    "CacheProtocol",
    "EventData",
    "EventEmitterProtocol",
    "EventHandlerProtocol",
    "MemoryProtocol",
    "StorageProtocol",
    "SyncEventHandlerProtocol",
]
