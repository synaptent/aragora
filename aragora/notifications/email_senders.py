"""Factory hook for the email sender that lower packages build from an email config.

``aragora.services`` and the other packages below ``aragora.integrations``, whose
``EmailIntegration`` sends mail over SMTP, SendGrid or SES, must not import it. The first
:func:`create_email_sender` that finds no factory runs, once per process, the registrations
declared under the ``aragora.email_senders`` entry-point group; aragora's own
``pyproject.toml`` declares the email integration there. A later registration replaces the
previous factory.

:func:`create_email_sender` raises :class:`EmailSenderNotRegisteredError` when no factory is
registered after that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aragora.utils.declared_registrations import DeclaredRegistrations

EMAIL_SENDERS_ENTRY_POINT_GROUP = "aragora.email_senders"

# Builds, from an email config, an object with
# ``async _send_email(recipient=..., subject=..., html_body=..., text_body=...) -> bool``.
EmailSenderFactory = Callable[[Any], Any]


class EmailSenderNotRegisteredError(RuntimeError):
    """No email sender factory is registered."""


_factory: EmailSenderFactory | None = None
_declared = DeclaredRegistrations(EMAIL_SENDERS_ENTRY_POINT_GROUP)


def register_email_sender_factory(factory: EmailSenderFactory) -> None:
    """Make ``factory`` build email senders, replacing any earlier one."""
    global _factory
    _factory = factory


def create_email_sender(config: Any) -> Any:
    """Build an email sender for ``config`` with the registered factory.

    Raises:
        EmailSenderNotRegisteredError: no factory is registered, even after the declared
            registrations ran.
    """
    factory = _factory
    if factory is None:
        _declared.load()
        factory = _factory
    if factory is None:
        raise EmailSenderNotRegisteredError(
            "no email sender is registered; import aragora.integrations.email_sender_registration "
            "and call register_email_sender(), or declare a registration under the "
            f"{EMAIL_SENDERS_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return factory(config)


__all__ = [
    "EMAIL_SENDERS_ENTRY_POINT_GROUP",
    "EmailSenderFactory",
    "EmailSenderNotRegisteredError",
    "create_email_sender",
    "register_email_sender_factory",
]
