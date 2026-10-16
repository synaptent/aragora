"""Registers the chat connector registry with :mod:`aragora.events.chat_connectors`.

Reached through the ``aragora.chat_connector_lookups`` entry point in ``pyproject.toml`` on
the first chat connector lookup, so ``aragora.pipeline`` never imports the connectors.
"""

from __future__ import annotations

from typing import Any

from aragora.connectors.chat import registry
from aragora.events.chat_connectors import register_chat_connector_lookup


def lookup_chat_connector(platform: str) -> Any:
    """The connector for ``platform`` from :func:`aragora.connectors.chat.registry.get_connector`."""
    # Looked up on each call so a patched registry function applies.
    return registry.get_connector(platform)


def register_chat_connector_lookup_from_registry() -> None:
    """Register the chat registry lookup; safe to call more than once."""
    register_chat_connector_lookup(lookup_chat_connector)


__all__ = ["lookup_chat_connector", "register_chat_connector_lookup_from_registry"]
