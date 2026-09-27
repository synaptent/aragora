"""Server-domain (interface) event-subscriber home (P4a EventBus inversion, Batch E6).

The webhook-delivery, knowledge-staleness-to-debate, and gauntlet-notification
reactions are relocated here from infrastructure ``aragora.events`` so
server-coupled reactions live in their INTERFACE home. ``ServerEventSubscriber``
self-registers via the domain-free registry
(``aragora.events.cross_subscribers.register_subscriber`` - interface ->
infrastructure, downward = legal); the interface-superset bootstrap
(``aragora.server.startup.event_subscribers.bootstrap_event_subscribers``)
imports this module so ``CrossSubscriberManager.apply_registered_subscribers``
wires the reactions in. A pure-domain/pure-library debate with no HTTP server or
notification delivery has no interface reaction to run, so this module is NOT
imported by the domain-subset bootstrap
(``aragora.debate.event_subscribers.bootstrap_debate_event_subscribers``) -
importing an interface-tier module from that domain-tier bootstrap would
recreate the very upward edge this inversion removes.

Per the relocate-UP no-shim exemption (AGENTS.md "P4a Contracts-Thread Shared
Rules" and docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §8) there is NO
re-export shim at the old paths; every consumer is repointed instead.

This home clears the subscriber-side ``aragora.events -> aragora.server``
contributors, including the corrective gauntlet-notification boundary. The
aggregate baseline string is intentionally NOT hand-shrunk here: tracing-shim,
control-plane channel, and seal-authorized exception routes remain under their
separately assigned P4a features.

Handles:
- Any subscribable event -> Webhook delivery (registered under 8 ``webhook_<event>`` names)
- Knowledge stale -> Debate warning (active-debate citation check)
- Gauntlet complete -> Notification delivery
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aragora.events.cross_subscribers import get_registered_subscribers, register_subscriber
from aragora.events.types import StreamEventType

if TYPE_CHECKING:
    from aragora.config.settings import Settings
    from aragora.events.cross_subscribers import CrossSubscriberManager
    from aragora.events.types import StreamEvent

# Import metrics stub - will be overwritten if metrics available (mirrors the
# pre-relocation aragora.events.cross_subscribers.handlers.culture import).
try:
    from aragora.observability.prometheus_cross_pollination import record_km_outbound_event
except ImportError:

    def record_km_outbound_event(target: str, event_type: str) -> None:
        pass


# Feature-flag settings (mirrors the manager helper so the subscriber needs no
# manager state at construction time; same self-contained-copy pattern as
# aragora.knowledge.event_subscribers.KnowledgeEventSubscriber).
try:
    from aragora.config.settings import get_settings as _get_settings

    _SETTINGS_AVAILABLE = True

    def get_settings() -> "Settings | None":
        return _get_settings()

except ImportError:
    _SETTINGS_AVAILABLE = False

    def get_settings() -> "Settings | None":
        return None


logger = logging.getLogger(__name__)

SERVER_EVENT_SUBSCRIBER_HANDLER_NAMES = frozenset(
    {
        "gauntlet_to_notification",
        "staleness_to_debate",
        "webhook_memory_stored",
        "webhook_memory_retrieved",
        "webhook_agent_elo_updated",
        "webhook_knowledge_indexed",
        "webhook_knowledge_queried",
        "webhook_mound_updated",
        "webhook_calibration_update",
        "webhook_evidence_found",
    }
)


class ServerEventSubscriber:
    """Interface cross-subscriber: webhook, staleness, and notification reactions."""

    def __init__(self) -> None:
        self._settings = get_settings() if _SETTINGS_AVAILABLE else None

    def _is_km_handler_enabled(self, handler_name: str) -> bool:
        """Check whether a KM handler is enabled via feature flags (default on)."""
        if self._settings is None:
            return True
        try:
            integration = self._settings.integration
            return integration.is_km_handler_enabled(handler_name)
        except (AttributeError, TypeError):
            return True

    def _handle_gauntlet_complete_to_notification(self, event: "StreamEvent") -> None:
        """Gauntlet complete → Notification dispatch.

        When a gauntlet stress-test finishes, notify stakeholders with
        the verdict and finding counts.
        """
        data = event.data
        gauntlet_id = data.get("gauntlet_id", "")
        verdict = data.get("verdict", "unknown")
        confidence = data.get("confidence", 0.0)
        total_findings = data.get("total_findings", 0)
        critical_count = data.get("critical_count", 0)

        logger.debug("Gauntlet complete: %s verdict=%s", gauntlet_id, verdict)

        try:
            import asyncio

            from aragora.notifications.service import notify_gauntlet_completed

            coro = notify_gauntlet_completed(
                gauntlet_id=gauntlet_id,
                verdict=verdict,
                confidence=confidence,
                total_findings=total_findings,
                critical_count=critical_count,
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(coro)
            except RuntimeError:
                asyncio.run(coro)
        except ImportError:
            pass  # Notification service not available
        except (RuntimeError, TypeError, ValueError, OSError) as e:
            logger.debug("Gauntlet notification failed: %s", e)

    def _handle_webhook_delivery(self, event: "StreamEvent") -> None:
        """
        Event → Webhook delivery.

        When any subscribable event occurs, deliver to registered webhooks.
        This enables external systems to receive real-time notifications.
        """
        try:
            from aragora.server.handlers.webhook_management import get_webhook_store
            from aragora.events.dispatcher import dispatch_webhook_with_retry

            # Get registered webhooks for this event type
            store = get_webhook_store()
            event_type_str = event.type.value.lower()  # Convert enum to string
            webhooks = store.get_for_event(event_type_str)

            if not webhooks:
                return  # No webhooks registered for this event

            # Build payload
            import time
            import uuid

            payload = {
                "event": event_type_str,
                "delivery_id": str(uuid.uuid4()),
                "timestamp": time.time(),
                "data": event.data or {},
            }

            # Deliver to each matching webhook
            for webhook in webhooks:
                try:
                    result = dispatch_webhook_with_retry(webhook, payload)
                    if not result.success:
                        logger.warning(
                            "Webhook delivery failed for %s: %s", webhook.id, result.error
                        )
                except (OSError, ConnectionError, RuntimeError, ValueError, TypeError) as e:
                    logger.error("Webhook dispatch error for %s: %s", webhook.id, e)

        except ImportError:
            logger.debug("Webhook modules not available for event delivery")
        except (KeyError, AttributeError, TypeError, ValueError) as e:
            logger.debug("Webhook delivery handler error: %s", e)

    def _handle_staleness_to_debate(self, event: "StreamEvent") -> None:
        """
        Knowledge stale → Debate warning.

        When knowledge becomes stale, check if any active debate cites it.
        """
        if not self._is_km_handler_enabled("staleness_to_debate"):
            return

        data = event.data
        node_id = data.get("node_id", "")
        staleness_reason = data.get("reason", "")
        data.get("last_verified", "")

        logger.debug("Knowledge stale: %s - %s", node_id, staleness_reason)

        # Record KM outbound metric (staleness warning to debate)
        record_km_outbound_event("debate", event.type.value)

        try:
            from aragora.server.stream.state_manager import get_active_debates

            active_debates = get_active_debates()

            # Check if any active debate references this node
            for debate_id, debate_state in active_debates.items():
                cited_nodes = debate_state.get("cited_knowledge", [])
                if node_id in cited_nodes:
                    logger.warning("Active debate %s cites stale knowledge: %s", debate_id, node_id)
                    # Could emit a warning event to the debate here

        except ImportError:
            pass
        except (RuntimeError, TypeError, AttributeError, ValueError, KeyError) as e:
            logger.debug("Staleness→Debate check failed: %s", e)

    def register(self, manager: "CrossSubscriberManager") -> None:
        """Wire the server-domain reactions into ``manager`` (keyed/idempotent)."""
        manager.register(
            "gauntlet_to_notification",
            StreamEventType.GAUNTLET_COMPLETE,
            self._handle_gauntlet_complete_to_notification,
        )
        manager.register(
            "staleness_to_debate",
            StreamEventType.KNOWLEDGE_STALE,
            self._handle_staleness_to_debate,
        )

        webhook_event_types = [
            StreamEventType.MEMORY_STORED,
            StreamEventType.MEMORY_RETRIEVED,
            StreamEventType.AGENT_ELO_UPDATED,
            StreamEventType.KNOWLEDGE_INDEXED,
            StreamEventType.KNOWLEDGE_QUERIED,
            StreamEventType.MOUND_UPDATED,
            StreamEventType.CALIBRATION_UPDATE,
            StreamEventType.EVIDENCE_FOUND,
        ]
        for event_type in webhook_event_types:
            manager.register(
                f"webhook_{event_type.value.lower()}",
                event_type,
                self._handle_webhook_delivery,
            )


def get_server_event_subscriber() -> ServerEventSubscriber:
    """Return the ``ServerEventSubscriber`` currently wired into the registry.

    Registers a fresh instance first if none is present yet, reusing the
    existing one otherwise so repeated calls resolve to the same instance
    (mirrors ``aragora.knowledge.event_subscribers.get_knowledge_event_subscriber``).
    """
    subscriber = get_registered_subscribers().get("server")
    if not isinstance(subscriber, ServerEventSubscriber):
        subscriber = ServerEventSubscriber()
        register_subscriber("server", subscriber)
    return subscriber


def register() -> None:
    """(Re-)register this home's subscriber into the domain-free registry.

    Delegates to :func:`get_server_event_subscriber`'s get-or-create so repeated
    calls reuse the existing instance instead of replacing it. Called explicitly
    (not just import side-effect) so registration survives a cached re-import
    after ``reset_registry`` in tests.
    """
    get_server_event_subscriber()


register()
