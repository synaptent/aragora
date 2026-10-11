"""Durable webhook-store registration for interface composition roots.

This module must stay a leaf: importing it must not load
``aragora.server.startup`` or any server subsystem, because the CLI imports it
on every normal command before dispatch.
"""

from __future__ import annotations


def register_webhook_store() -> None:
    """Register durable webhook storage without loading server subsystems."""
    from aragora.events.dispatcher import register_webhook_store_provider
    from aragora.storage.webhook_config_store import get_webhook_config_store

    register_webhook_store_provider(get_webhook_config_store)
