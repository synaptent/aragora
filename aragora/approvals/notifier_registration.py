"""Registers the chat approval notifier with :mod:`aragora.events.approval_requests`.

Called from the package init, and reached through the ``aragora.approval_notifiers``
entry point in ``pyproject.toml`` by a process that asks for an approval without
importing ``aragora.approvals``.
"""

from __future__ import annotations

from typing import Any

from aragora.approvals import chat
from aragora.events.approval_requests import register_approval_notifier


class ChatApprovalRequestNotifier:
    """Sends approval requests with :mod:`aragora.approvals.chat`."""

    # The chat functions are looked up on each call so a patched module function applies.
    def parse_targets(self, targets: list[str] | None) -> dict[str, list[str]]:
        return chat.parse_chat_targets(targets)

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
        return await chat.send_chat_approval_request(
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


CHAT_APPROVAL_NOTIFIER = ChatApprovalRequestNotifier()


def register_chat_approval_notifier() -> None:
    """Register the chat approval notifier; safe to call more than once."""
    register_approval_notifier(CHAT_APPROVAL_NOTIFIER)


__all__ = [
    "CHAT_APPROVAL_NOTIFIER",
    "ChatApprovalRequestNotifier",
    "register_chat_approval_notifier",
]
