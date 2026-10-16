"""Registers :class:`~aragora.integrations.email.EmailIntegration` as the email sender.

Reached through the ``aragora.email_senders`` entry point in ``pyproject.toml`` on the first
email sender a lower package builds, so ``aragora.services`` never imports
``aragora.integrations``.
"""

from __future__ import annotations

from typing import Any

from aragora.integrations import email
from aragora.notifications.email_senders import register_email_sender_factory


def build_email_sender(config: Any) -> Any:
    """A new :class:`~aragora.integrations.email.EmailIntegration` for ``config``."""
    # Looked up on each call so a patched module class applies.
    return email.EmailIntegration(config)


def register_email_sender() -> None:
    """Register the email integration factory; safe to call more than once."""
    register_email_sender_factory(build_email_sender)


__all__ = ["build_email_sender", "register_email_sender"]
