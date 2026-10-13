"""Chat helpers for approval requests and interactive buttons."""

from __future__ import annotations

import logging
import os
from typing import Any

from aragora.approvals.tokens import encode_approval_action

logger = logging.getLogger(__name__)

PLATFORM_ALIASES = {
    "gchat": "google_chat",
    "googlechat": "google_chat",
    "ms_teams": "teams",
    "msteams": "teams",
    "wa": "whatsapp",
}


def normalize_platform(platform: str) -> str:
    platform = platform.lower().strip()
    return PLATFORM_ALIASES.get(platform, platform)


def get_default_chat_targets() -> list[str]:
    raw = os.environ.get("ARAGORA_APPROVAL_CHAT_TARGETS", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_chat_targets(targets: list[str] | None) -> dict[str, list[str]]:
    """Parse target strings into platform -> channel list."""
    mapping: dict[str, list[str]] = {}
    if not targets:
        return mapping

    for entry in targets:
        if not entry:
            continue

        entry = entry.strip()
        if not entry:
            continue

        # Explicit platform prefix: "slack:#channel" or "teams:channel_id"
        if ":" in entry:
            prefix, dest = entry.split(":", 1)
            platform = normalize_platform(prefix)
            if dest:
                mapping.setdefault(platform, []).append(dest)
            continue

        # Slack-style shorthand (#channel or @user)
        if entry.startswith("#") or entry.startswith("@"):
            mapping.setdefault("slack", []).append(entry)
            continue

        # Email address - skip (handled by notification service)
        if "@" in entry:
            continue

        # Default to Slack if no prefix provided
        mapping.setdefault("slack", []).append(entry)

    return mapping


def build_approval_buttons(
    *,
    kind: str,
    target_id: str,
    ttl_seconds: int | None = 3600,
    approve_label: str = "Approve",
    reject_label: str = "Reject",
) -> list[Any]:
    """Build approval buttons for chat connectors."""
    try:
        from aragora.connectors.chat.models import MessageButton
    except ImportError:
        return []

    approve_token = encode_approval_action(
        kind=kind,
        target_id=target_id,
        action="approve",
        ttl_seconds=ttl_seconds,
    )
    reject_token = encode_approval_action(
        kind=kind,
        target_id=target_id,
        action="reject",
        ttl_seconds=ttl_seconds,
    )

    if not approve_token or not reject_token:
        logger.warning("Failed to build approval tokens for %s:%s", kind, target_id)
        return []

    return [
        MessageButton(
            text=approve_label,
            action_id="approval:approve",
            value=approve_token,
            style="primary",
        ),
        MessageButton(
            text=reject_label,
            action_id="approval:reject",
            value=reject_token,
            style="danger",
        ),
    ]


async def send_chat_approval_request(
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
    """Send an interactive approval request to chat channels."""
    try:
        from aragora.connectors.chat.registry import get_connector
    except ImportError:
        return []

    all_targets = targets or []
    if not all_targets:
        all_targets = get_default_chat_targets()

    parsed = parse_chat_targets(all_targets)
    if not parsed:
        return []

    buttons = build_approval_buttons(
        kind=kind,
        target_id=target_id,
        ttl_seconds=ttl_seconds,
    )

    results: list[dict[str, Any]] = []
    body_parts = [description]
    if extra_text:
        body_parts.append(extra_text)
    body = "\n".join([part for part in body_parts if part])

    for platform, channels in parsed.items():
        connector = get_connector(platform)
        if connector is None or not connector.is_configured:
            logger.debug("Chat connector not configured for %s", platform)
            continue

        try:
            blocks = connector.format_blocks(
                title=title,
                body=body,
                fields=fields,
                actions=buttons if buttons else None,
            )
        except (AttributeError, TypeError, ValueError):
            blocks = None

        platform_thread_id = None
        if thread_id_by_platform and platform in thread_id_by_platform:
            platform_thread_id = thread_id_by_platform[platform]
        elif thread_id:
            platform_thread_id = thread_id

        for channel_id in channels:
            try:
                response = await connector.send_message(
                    channel_id=channel_id,
                    text=f"{title}\n{body}".strip(),
                    blocks=blocks,
                    thread_id=platform_thread_id,
                )
                results.append(
                    {
                        "platform": platform,
                        "channel_id": channel_id,
                        "success": getattr(response, "success", True),
                        "message_id": getattr(response, "message_id", None),
                        "error": getattr(response, "error", None),
                    }
                )
            except (OSError, RuntimeError, ValueError, TypeError) as exc:
                results.append(
                    {
                        "platform": platform,
                        "channel_id": channel_id,
                        "success": False,
                        "error": str(exc),
                    }
                )
                logger.debug(
                    "Failed to send approval request to %s:%s: %s", platform, channel_id, exc
                )

    return results


__all__ = [
    "build_approval_buttons",
    "send_chat_approval_request",
    "parse_chat_targets",
    "get_default_chat_targets",
    "normalize_platform",
]
