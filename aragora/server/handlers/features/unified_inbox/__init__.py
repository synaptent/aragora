"""Unified Inbox package.

Re-exports all public names for backward compatibility.
"""

from .handler import (
    UnifiedInboxHandler,
    get_unified_inbox_handler,
    handle_unified_inbox,
)
from .models import (
    AccountStatus,
    ConnectedAccount,
    EmailProvider,
    InboxStats,
    TriageAction,
    TriageResult,
    UnifiedMessage,
)

__all__ = [
    "UnifiedInboxHandler",
    "handle_unified_inbox",
    "get_unified_inbox_handler",
    "EmailProvider",
    "AccountStatus",
    "TriageAction",
    "ConnectedAccount",
    "UnifiedMessage",
    "TriageResult",
    "InboxStats",
]
