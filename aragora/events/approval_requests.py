"""Hook through which workflows, pipelines and computer use ask humans for approval.

``aragora.workflow``, ``aragora.pipeline`` and ``aragora.computer_use`` sit below
``aragora.approvals``, which delivers interactive approval requests to chat channels, and
must not import it. ``aragora.approvals`` registers its notifier here from its own init.
A process that never imports it reaches that registration through the
``aragora.approval_notifiers`` entry point, run once by the first call that finds no
notifier. A later registration replaces the previous notifier.

:func:`parse_approval_targets` and :func:`send_approval_request` raise
:class:`ApprovalNotifierNotRegisteredError` when no notifier is registered after that.
"""

from __future__ import annotations

from typing import Any, Protocol

from aragora.utils.declared_registrations import DeclaredRegistrations

APPROVAL_NOTIFIERS_ENTRY_POINT_GROUP = "aragora.approval_notifiers"


class ApprovalRequestNotifier(Protocol):
    """Delivers approval requests and parses the targets they go to."""

    def parse_targets(self, targets: list[str] | None) -> dict[str, list[str]]:
        """Map target strings such as ``"slack:#ops"`` to channels per platform."""
        ...

    async def send_request(
        self,
        *,
        title: str,
        description: str,
        fields: list[tuple[str, str]] | None,
        targets: list[str] | None,
        kind: str,
        target_id: str,
        ttl_seconds: int | None = 3600,
        extra_text: str | None = None,
        thread_id: str | None = None,
        thread_id_by_platform: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Send an interactive approval request; one result per delivery attempt."""
        ...


class ApprovalNotifierNotRegisteredError(RuntimeError):
    """No approval request notifier is registered."""


_notifier: ApprovalRequestNotifier | None = None
_declared = DeclaredRegistrations(APPROVAL_NOTIFIERS_ENTRY_POINT_GROUP)


def register_approval_notifier(notifier: ApprovalRequestNotifier) -> None:
    """Make ``notifier`` deliver approval requests, replacing any earlier one."""
    global _notifier
    _notifier = notifier


def registered_count() -> int:
    """How many notifiers are registered: 0 or 1."""
    return 0 if _notifier is None else 1


def _registered_notifier() -> ApprovalRequestNotifier:
    notifier = _notifier
    if notifier is None:
        _declared.load()
        notifier = _notifier
    if notifier is None:
        raise ApprovalNotifierNotRegisteredError(
            "no approval request notifier is registered; import aragora.approvals, or declare "
            f"a registration under the {APPROVAL_NOTIFIERS_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return notifier


def parse_approval_targets(targets: list[str] | None) -> dict[str, list[str]]:
    """Map target strings to channels per platform with the registered notifier.

    Raises:
        ApprovalNotifierNotRegisteredError: no notifier is registered, even after the
            declared registrations ran.
    """
    return _registered_notifier().parse_targets(targets)


async def send_approval_request(
    *,
    title: str,
    description: str,
    fields: list[tuple[str, str]] | None,
    targets: list[str] | None,
    kind: str,
    target_id: str,
    ttl_seconds: int | None = 3600,
    extra_text: str | None = None,
    thread_id: str | None = None,
    thread_id_by_platform: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Send an interactive approval request with the registered notifier.

    Raises:
        ApprovalNotifierNotRegisteredError: no notifier is registered, even after the
            declared registrations ran.
    """
    return await _registered_notifier().send_request(
        title=title,
        description=description,
        fields=fields,
        targets=targets,
        kind=kind,
        target_id=target_id,
        ttl_seconds=ttl_seconds,
        extra_text=extra_text,
        thread_id=thread_id,
        thread_id_by_platform=thread_id_by_platform,
    )


__all__ = [
    "APPROVAL_NOTIFIERS_ENTRY_POINT_GROUP",
    "ApprovalNotifierNotRegisteredError",
    "ApprovalRequestNotifier",
    "parse_approval_targets",
    "register_approval_notifier",
    "registered_count",
    "send_approval_request",
]
