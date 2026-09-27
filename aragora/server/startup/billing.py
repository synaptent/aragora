"""Server composition for higher-layer capabilities consumed by billing."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _register_audit_sink() -> None:
    from aragora.audit.billing_sink import register_billing_audit_sink

    register_billing_audit_sink()


def _register_budget_alert_sinks() -> None:
    from aragora.connectors.chat.budget_alert_sink import register_budget_alert_sinks

    register_budget_alert_sinks()


def _register_cost_adapter() -> None:
    from aragora.knowledge.mound.cost_adapter_registration import register_billing_cost_adapter

    register_billing_cost_adapter()


def _register_notification_sink() -> None:
    from aragora.notifications.billing_sink import register_billing_notification_sink

    register_billing_notification_sink()


def init_billing_edge_adapters(*, strict: bool = False) -> bool:
    """Register audit, chat, knowledge, and notification capabilities for billing."""
    registrations = (
        ("MFA audit sink", _register_audit_sink),
        ("budget alert sinks", _register_budget_alert_sinks),
        ("cost adapter", _register_cost_adapter),
        ("notification sink", _register_notification_sink),
    )
    all_registered = True
    for label, register in registrations:
        try:
            register()
        except (ImportError, RuntimeError, OSError, ConnectionError, ValueError, TypeError) as exc:
            if strict:
                raise RuntimeError(f"Billing edge adapter registration failed: {label}") from exc
            logger.warning("Billing %s registration failed: %s", label, exc)
            all_registered = False

    if all_registered:
        logger.info("Billing edge adapters registered")
    return all_registered
