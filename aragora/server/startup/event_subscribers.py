"""Superset bootstrap for cross-subsystem event subscribers (P4a E1).

Composition root for the *running product* (server startup, CLI). It imports the
domain, application, AND interface event-subscriber home modules so every reaction
self-registers, then wires them into the cross-subscriber manager. Interface may
import every layer, so this superset lives here (in ``interface``); it must NOT
live in ``events``/``debate``, which would recreate an upward import.

See docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §4.4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.events.cross_subscribers import CrossSubscriberManager


def register_webhook_store() -> None:
    """Register durable webhook storage without loading server subscribers."""
    from aragora.events.dispatcher import register_webhook_store_provider
    from aragora.storage.webhook_config_store import get_webhook_config_store

    register_webhook_store_provider(get_webhook_config_store)


def bootstrap_event_subscribers() -> CrossSubscriberManager:
    """Import all event-subscriber home modules and wire them into the manager.

    Superset of the domain-subset bootstrap: it also imports application and
    interface home modules. Idempotent. Currently adds the workflow
    application-tier home (P4a Batch E5) and the server interface-tier home
    (P4a Batch E6): a pure-library debate with no workflow engine or HTTP server
    has no such reactions, so ``aragora.workflow.event_subscribers`` and
    ``aragora.server.event_subscribers`` are imported here rather than by the
    domain-subset bootstrap. Further application/interface
    ``import aragora.<pkg>.event_subscribers`` lines (e.g. notifications) are
    added here as remaining handlers relocate to their home layers.

    Returns:
        The registry-backed cross-subscriber manager singleton.
    """
    from aragora.debate.event_subscribers import bootstrap_debate_event_subscribers
    from aragora.server import event_subscribers as server_home
    from aragora.workflow import event_subscribers as workflow_home

    register_webhook_store()
    bootstrap_debate_event_subscribers()
    workflow_home.register()
    server_home.register()

    from aragora.events.cross_subscribers import bootstrap

    manager = bootstrap()
    expected_handlers = (
        workflow_home.WORKFLOW_EVENT_SUBSCRIBER_HANDLER_NAMES
        | server_home.SERVER_EVENT_SUBSCRIBER_HANDLER_NAMES
    )
    missing = expected_handlers - set(manager.get_stats())
    if missing:
        raise RuntimeError(
            f"Application event subscriber bootstrap incomplete; missing handlers: {sorted(missing)}"
        )
    return manager
