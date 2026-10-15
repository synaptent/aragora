"""Hook through which lower packages look up the chat connector for a platform.

``aragora.pipeline`` sits below ``aragora.connectors``, whose chat registry builds the Slack,
Teams, Discord and other chat connectors, and must not import it. The first
:func:`chat_connector_lookup` that finds no lookup runs, once per process, the registrations
declared under the ``aragora.chat_connector_lookups`` entry-point group; aragora's own
``pyproject.toml`` declares the chat registry there. A later registration replaces the
previous lookup.

:func:`chat_connector_lookup` raises :class:`ChatConnectorLookupNotRegisteredError` when no
lookup is registered after that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aragora.utils.declared_registrations import DeclaredRegistrations

CHAT_CONNECTOR_LOOKUPS_ENTRY_POINT_GROUP = "aragora.chat_connector_lookups"

# Maps a platform name such as ``"slack"`` to its connector, or None when it has none.
ChatConnectorLookup = Callable[[str], Any]


class ChatConnectorLookupNotRegisteredError(RuntimeError):
    """No chat connector lookup is registered."""


_lookup: ChatConnectorLookup | None = None
_declared = DeclaredRegistrations(CHAT_CONNECTOR_LOOKUPS_ENTRY_POINT_GROUP)


def register_chat_connector_lookup(lookup: ChatConnectorLookup) -> None:
    """Make ``lookup`` find chat connectors, replacing any earlier one."""
    global _lookup
    _lookup = lookup


def chat_connector_lookup() -> ChatConnectorLookup:
    """The registered chat connector lookup.

    Raises:
        ChatConnectorLookupNotRegisteredError: no lookup is registered, even after the
            declared registrations ran.
    """
    lookup = _lookup
    if lookup is None:
        _declared.load()
        lookup = _lookup
    if lookup is None:
        raise ChatConnectorLookupNotRegisteredError(
            "no chat connector lookup is registered; import "
            "aragora.connectors.chat.lookup_registration and call "
            "register_chat_connector_lookup_from_registry(), or declare a registration under "
            f"the {CHAT_CONNECTOR_LOOKUPS_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return lookup


__all__ = [
    "CHAT_CONNECTOR_LOOKUPS_ENTRY_POINT_GROUP",
    "ChatConnectorLookup",
    "ChatConnectorLookupNotRegisteredError",
    "chat_connector_lookup",
    "register_chat_connector_lookup",
]
