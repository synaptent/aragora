"""
HTTP API Handlers for Email Actions.

Provides REST APIs for email actions across providers:
- Send and reply to emails
- Archive, trash, restore messages
- Snooze messages until a specific time
- Mark as read/unread, star/unstar
- Move to folders, manage labels
- Batch operations
- Action logs for compliance

Endpoints:
- POST /api/v1/inbox/messages/send - Send a new email
- POST /api/v1/inbox/messages/{id}/reply - Reply to an email
- POST /api/v1/inbox/messages/{id}/archive - Archive a message
- POST /api/v1/inbox/messages/{id}/trash - Move to trash
- POST /api/v1/inbox/messages/{id}/restore - Restore from trash
- POST /api/v1/inbox/messages/{id}/snooze - Snooze until time
- POST /api/v1/inbox/messages/{id}/read - Mark as read
- POST /api/v1/inbox/messages/{id}/unread - Mark as unread
- POST /api/v1/inbox/messages/{id}/star - Star message
- POST /api/v1/inbox/messages/{id}/unstar - Unstar message
- POST /api/v1/inbox/messages/{id}/move - Move to folder
- POST /api/v1/inbox/messages/batch/archive - Batch archive
- POST /api/v1/inbox/messages/batch/trash - Batch trash
- GET /api/v1/inbox/actions/logs - Get action logs
- GET /api/v1/inbox/actions/export - Export logs for compliance
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from aragora.server.handlers.base import (
    error_response,
    success_response,
    require_permission,
)
from aragora.server.handlers.utils.responses import HandlerResult

logger = logging.getLogger(__name__)

# Thread-safe service instance
_email_actions_service: Any | None = None
_email_actions_service_lock = threading.Lock()
_inbox_trust_wedge_service: Any | None = None
_inbox_trust_wedge_service_lock = threading.Lock()


def get_email_actions_service_instance():
    """Get or create email actions service (thread-safe)."""
    global _email_actions_service
    if _email_actions_service is not None:
        return _email_actions_service

    with _email_actions_service_lock:
        if _email_actions_service is None:
            from aragora.services.email_actions import get_email_actions_service

            _email_actions_service = get_email_actions_service()
        return _email_actions_service


def get_inbox_trust_wedge_service_instance():
    """Get or create inbox trust wedge service (thread-safe)."""
    global _inbox_trust_wedge_service
    if _inbox_trust_wedge_service is not None:
        return _inbox_trust_wedge_service

    with _inbox_trust_wedge_service_lock:
        if _inbox_trust_wedge_service is None:
            from aragora.inbox import get_inbox_trust_wedge_service

            _inbox_trust_wedge_service = get_inbox_trust_wedge_service()
        return _inbox_trust_wedge_service


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _content_hash_from_payload(data: dict[str, Any], message_id: str) -> str:
    from aragora.inbox import ActionIntent

    raw_parts: list[str] = [message_id]
    for key in ("content_hash", "subject", "snippet", "body", "preview", "message_text"):
        value = data.get(key)
        if isinstance(value, str) and value:
            raw_parts.append(value)

    message = data.get("message")
    if isinstance(message, dict):
        for key in ("subject", "snippet", "body", "preview", "text"):
            value = message.get(key)
            if isinstance(value, str) and value:
                raw_parts.append(value)

    return ActionIntent.compute_content_hash(*raw_parts)


def _single_label_from_payload(data: dict[str, Any]) -> str | None:
    label_id = data.get("label_id")
    if isinstance(label_id, str) and label_id.strip():
        return label_id.strip()

    labels = data.get("labels")
    if isinstance(labels, list):
        string_labels = [str(label).strip() for label in labels if str(label).strip()]
        if len(string_labels) == 1:
            return string_labels[0]
    return None


def _receipt_response_payload(
    envelope: Any,
    *,
    action_name: str,
    message_id: str,
    executed: bool = False,
    execution_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "action": action_name,
        "success": True,
        "receipt": envelope.receipt.to_dict(),
        "intent": envelope.intent.to_dict(),
        "decision": envelope.decision.to_dict(),
        "provider_route": envelope.provider_route,
        "debate_id": envelope.debate_id,
        "requires_approval": envelope.receipt.state.value == "created",
        "executed": executed,
        "execution_result": execution_result,
    }


async def _maybe_handle_wedge_action(
    data: dict[str, Any],
    *,
    message_id: str,
    user_id: str,
    action: str,
    provider: str,
    action_name: str,
    requires_label: bool = False,
) -> HandlerResult | None:
    from aragora.inbox import (
        ActionIntent,
        InboxWedgeAction,
        ReceiptState,
        TriageDecision,
    )

    receipt_id = str(data.get("receipt_id", "") or "").strip()
    create_receipt = bool(data.get("create_receipt"))
    if not receipt_id and not create_receipt:
        return None

    wedge_service = get_inbox_trust_wedge_service_instance()
    expected_action = InboxWedgeAction.parse(action)
    label_id = _single_label_from_payload(data) if requires_label else None

    if requires_label and create_receipt and not label_id:
        return error_response(
            "Inbox trust wedge LABEL actions require exactly one label_id or labels entry",
            status=400,
        )

    if receipt_id:
        validation = wedge_service.validate_receipt(receipt_id, require_state=ReceiptState.APPROVED)
        if not validation.valid or validation.envelope is None:
            return error_response(validation.error or "receipt validation failed", status=400)

        envelope = validation.envelope
        if envelope.intent.provider != provider:
            return error_response("receipt provider mismatch", status=400)
        if envelope.intent.user_id != user_id:
            return error_response("receipt user mismatch", status=400)
        if envelope.intent.message_id != message_id:
            return error_response("receipt message mismatch", status=400)
        if envelope.intent.action is not expected_action:
            return error_response("receipt action mismatch", status=400)
        if (
            requires_label
            and label_id is not None
            and (envelope.intent.label_id or envelope.decision.label_id) != label_id
        ):
            return error_response("receipt label mismatch", status=400)

        try:
            result = await wedge_service.execute_receipt(receipt_id)
        except ValueError as exc:
            return error_response(str(exc), status=400)
        except (
            AttributeError,
            RuntimeError,
            OSError,
            ConnectionError,
            TypeError,
            KeyError,
        ):
            logger.exception("Failed to execute inbox trust wedge receipt")
            return error_response("Receipt execution failed", status=500)

        updated = wedge_service.store.get_receipt(receipt_id)
        if updated is None:
            return error_response("Receipt disappeared after execution", status=500)
        return success_response(
            _receipt_response_payload(
                updated,
                action_name=action_name,
                message_id=message_id,
                executed=True,
                execution_result=result.to_dict(),
            )
        )

    intent = ActionIntent.create(
        provider=provider,
        user_id=user_id,
        message_id=message_id,
        action=expected_action,
        content_hash=_content_hash_from_payload(data, message_id),
        synthesized_rationale=str(
            data.get("synthesized_rationale") or data.get("rationale") or data.get("reason") or ""
        ),
        confidence=_safe_float(data.get("confidence", data.get("debate_confidence")), 0.0),
        provider_route=str(data.get("provider_route", "direct")),
        debate_id=str(data["debate_id"]) if data.get("debate_id") else None,
        label_id=label_id,
    )
    decision = TriageDecision.create(
        final_action=expected_action,
        confidence=_safe_float(data.get("confidence", data.get("debate_confidence")), 0.0),
        dissent_summary=str(data.get("dissent_summary", "")),
        label_id=label_id,
        blocked_by_policy=bool(data.get("blocked_by_policy", False)),
        cost_usd=(_safe_float(data.get("cost_usd")) if data.get("cost_usd") is not None else None),
        latency_seconds=(
            _safe_float(data.get("latency_seconds"))
            if data.get("latency_seconds") is not None
            else None
        ),
    )

    try:
        envelope = wedge_service.create_receipt(
            intent,
            decision,
            expires_in_hours=_safe_float(data.get("expires_in_hours"), 24.0),
            auto_approve=bool(data.get("auto_approve", False)),
        )
    except ValueError as exc:
        return error_response(str(exc), status=400)
    except (
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
        TypeError,
        KeyError,
    ):
        logger.exception("Failed to create inbox trust wedge receipt")
        return error_response("Receipt creation failed", status=500)

    auto_execute = bool(data.get("auto_execute", False))
    if auto_execute and envelope.receipt.state is ReceiptState.APPROVED:
        try:
            result = await wedge_service.execute_receipt(envelope.receipt.receipt_id)
        except ValueError as exc:
            return error_response(str(exc), status=400)
        except (
            AttributeError,
            RuntimeError,
            OSError,
            ConnectionError,
            TypeError,
            KeyError,
        ):
            logger.exception("Failed to auto-execute inbox trust wedge receipt")
            return error_response("Receipt execution failed", status=500)
        updated = wedge_service.store.get_receipt(envelope.receipt.receipt_id)
        if updated is None:
            return error_response("Receipt disappeared after execution", status=500)
        return success_response(
            _receipt_response_payload(
                updated,
                action_name=action_name,
                message_id=message_id,
                executed=True,
                execution_result=result.to_dict(),
            )
        )

    return success_response(
        _receipt_response_payload(
            envelope,
            action_name=action_name,
            message_id=message_id,
        )
    )


# =============================================================================
# Send / Reply Handlers
# =============================================================================


@require_permission("email:create")
async def handle_send_email(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Send a new email.

    POST /api/v1/inbox/messages/send
    Body: {
        provider: str ("gmail" or "outlook"),
        to: list[str],
        subject: str,
        body: str,
        cc: list[str] (optional),
        bcc: list[str] (optional),
        reply_to: str (optional),
        html_body: str (optional)
    }
    """
    try:
        from aragora.services.email_actions import SendEmailRequest

        service = get_email_actions_service_instance()

        provider = data.get("provider", "gmail")
        to_addresses = data.get("to", [])
        subject = data.get("subject", "")
        body = data.get("body", "")

        if not to_addresses:
            return error_response("'to' field is required", status=400)
        if not subject and not body:
            return error_response("Either subject or body is required", status=400)

        request = SendEmailRequest(
            to=to_addresses,
            subject=subject,
            body=body,
            cc=data.get("cc"),
            bcc=data.get("bcc"),
            reply_to=data.get("reply_to"),
            html_body=data.get("html_body"),
        )

        result = await service.send(
            provider=provider,
            user_id=user_id,
            request=request,
        )

        if result.success:
            return success_response(result.to_dict())
        else:
            return error_response(result.error or "Send failed", status=500)

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to send email")
        return error_response("Email send failed", status=500)


@require_permission("email:create")
async def handle_reply_email(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Reply to an email.

    POST /api/v1/inbox/messages/{id}/reply
    Body: {
        provider: str ("gmail" or "outlook"),
        body: str,
        cc: list[str] (optional),
        html_body: str (optional)
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        provider = data.get("provider", "gmail")
        body = data.get("body", "")

        if not body:
            return error_response("'body' is required", status=400)

        result = await service.reply(
            provider=provider,
            user_id=user_id,
            message_id=message_id,
            body=body,
            cc=data.get("cc"),
            html_body=data.get("html_body"),
        )

        if result.success:
            return success_response(result.to_dict())
        else:
            return error_response(result.error or "Reply failed", status=500)

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to reply to email")
        return error_response("Email reply failed", status=500)


# =============================================================================
# Archive / Trash Handlers
# =============================================================================


@require_permission("email:update")
async def handle_archive_message(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Archive a message.

    POST /api/v1/inbox/messages/{id}/archive
    Body: {
        provider: str ("gmail" or "outlook")
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        provider = data.get("provider", "gmail")
        wedge_result = await _maybe_handle_wedge_action(
            data,
            message_id=message_id,
            user_id=user_id,
            action="archive",
            provider=provider,
            action_name="archive",
        )
        if wedge_result is not None:
            return wedge_result

        result = await service.archive(
            provider=provider,
            user_id=user_id,
            message_id=message_id,
        )

        if result.success:
            return success_response(
                {
                    "message_id": message_id,
                    "action": "archive",
                    "success": True,
                    **result.to_dict(),
                }
            )
        else:
            return error_response(result.error or "Archive failed", status=500)

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to archive message")
        return error_response("Archive operation failed", status=500)


@require_permission("email:delete")
async def handle_trash_message(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Move a message to trash.

    POST /api/v1/inbox/messages/{id}/trash
    Body: {
        provider: str ("gmail" or "outlook")
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        provider = data.get("provider", "gmail")

        result = await service.trash(
            provider=provider,
            user_id=user_id,
            message_id=message_id,
        )

        if result.success:
            return success_response(
                {
                    "message_id": message_id,
                    "action": "trash",
                    "success": True,
                    **result.to_dict(),
                }
            )
        else:
            return error_response(result.error or "Trash failed", status=500)

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to trash message")
        return error_response("Trash operation failed", status=500)


@require_permission("email:update")
async def handle_restore_message(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Restore a message from trash.

    POST /api/v1/inbox/messages/{id}/restore
    Body: {
        provider: str ("gmail" or "outlook")
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        provider = data.get("provider", "gmail")

        # Get connector and call untrash
        connector = await service._get_connector(provider, user_id)
        await connector.untrash_message(message_id)

        return success_response(
            {
                "message_id": message_id,
                "action": "restore",
                "success": True,
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to restore message")
        return error_response("Restore operation failed", status=500)


# =============================================================================
# Snooze Handlers
# =============================================================================


@require_permission("email:update")
async def handle_snooze_message(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Snooze a message until a specific time.

    POST /api/v1/inbox/messages/{id}/snooze
    Body: {
        provider: str ("gmail" or "outlook"),
        snooze_until: str (ISO format datetime),
        snooze_hours: int (alternative - hours from now),
        snooze_days: int (alternative - days from now)
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        provider = data.get("provider", "gmail")

        # Parse snooze time
        snooze_until = None

        if data.get("snooze_until"):
            try:
                snooze_until_str = data["snooze_until"]
                snooze_until = datetime.fromisoformat(snooze_until_str.replace("Z", "+00:00"))
            except ValueError:
                return error_response("Invalid snooze_until format. Use ISO 8601.", status=400)
        elif data.get("snooze_hours"):
            hours = int(data["snooze_hours"])
            snooze_until = datetime.now(timezone.utc) + timedelta(hours=hours)
        elif data.get("snooze_days"):
            days = int(data["snooze_days"])
            snooze_until = datetime.now(timezone.utc) + timedelta(days=days)
        else:
            return error_response(
                "One of snooze_until, snooze_hours, or snooze_days is required",
                status=400,
            )

        # Validate snooze time is in future
        if snooze_until <= datetime.now(timezone.utc):
            return error_response("snooze_until must be in the future", status=400)

        result = await service.snooze(
            provider=provider,
            user_id=user_id,
            message_id=message_id,
            snooze_until=snooze_until,
        )

        if result.success:
            return success_response(
                {
                    "message_id": message_id,
                    "action": "snooze",
                    "snooze_until": snooze_until.isoformat(),
                    "success": True,
                    **result.to_dict(),
                }
            )
        else:
            return error_response(result.error or "Snooze failed", status=500)

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to snooze message")
        return error_response("Snooze operation failed", status=500)


# =============================================================================
# Read / Star Handlers
# =============================================================================


@require_permission("email:update")
async def handle_mark_read(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Mark a message as read.

    POST /api/v1/inbox/messages/{id}/read
    Body: {
        provider: str ("gmail" or "outlook")
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        provider = data.get("provider", "gmail")

        result = await service.mark_read(
            provider=provider,
            user_id=user_id,
            message_id=message_id,
        )

        if result.success:
            return success_response(
                {
                    "message_id": message_id,
                    "action": "mark_read",
                    "success": True,
                }
            )
        else:
            return error_response(result.error or "Mark read failed", status=500)

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to mark message as read")
        return error_response("Mark read operation failed", status=500)


@require_permission("email:update")
async def handle_mark_unread(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Mark a message as unread.

    POST /api/v1/inbox/messages/{id}/unread
    Body: {
        provider: str ("gmail" or "outlook")
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        provider = data.get("provider", "gmail")

        # Get connector and call mark_as_unread
        connector = await service._get_connector(provider, user_id)
        await connector.mark_as_unread(message_id)

        return success_response(
            {
                "message_id": message_id,
                "action": "mark_unread",
                "success": True,
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to mark message as unread")
        return error_response("Mark unread operation failed", status=500)


@require_permission("email:update")
async def handle_star_message(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Star a message.

    POST /api/v1/inbox/messages/{id}/star
    Body: {
        provider: str ("gmail" or "outlook")
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        provider = data.get("provider", "gmail")
        wedge_result = await _maybe_handle_wedge_action(
            data,
            message_id=message_id,
            user_id=user_id,
            action="star",
            provider=provider,
            action_name="star",
        )
        if wedge_result is not None:
            return wedge_result

        result = await service.star(
            provider=provider,
            user_id=user_id,
            message_id=message_id,
        )

        if result.success:
            return success_response(
                {
                    "message_id": message_id,
                    "action": "star",
                    "success": True,
                }
            )
        else:
            return error_response(result.error or "Star failed", status=500)

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to star message")
        return error_response("Star operation failed", status=500)


@require_permission("email:update")
async def handle_unstar_message(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Unstar a message.

    POST /api/v1/inbox/messages/{id}/unstar
    Body: {
        provider: str ("gmail" or "outlook")
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        provider = data.get("provider", "gmail")

        # Get connector and call unstar
        connector = await service._get_connector(provider, user_id)
        await connector.unstar_message(message_id)

        return success_response(
            {
                "message_id": message_id,
                "action": "unstar",
                "success": True,
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to unstar message")
        return error_response("Unstar operation failed", status=500)


# =============================================================================
# Folder / Label Handlers
# =============================================================================


@require_permission("email:update")
async def handle_move_to_folder(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Move a message to a folder.

    POST /api/v1/inbox/messages/{id}/move
    Body: {
        provider: str ("gmail" or "outlook"),
        folder: str (folder/label name),
        remove_from_inbox: bool (optional, default true)
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        folder = data.get("folder", "")
        if not folder:
            return error_response("'folder' is required", status=400)

        provider = data.get("provider", "gmail")

        result = await service.move_to_folder(
            provider=provider,
            user_id=user_id,
            message_id=message_id,
            folder=folder,
        )

        if result.success:
            return success_response(
                {
                    "message_id": message_id,
                    "action": "move_to_folder",
                    "folder": folder,
                    "success": True,
                }
            )
        else:
            return error_response(result.error or "Move failed", status=500)

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to move message")
        return error_response("Move operation failed", status=500)


@require_permission("email:update")
async def handle_add_label(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Add a label to a message.

    POST /api/v1/inbox/messages/{id}/labels/add
    Body: {
        provider: str ("gmail" or "outlook"),
        labels: list[str]
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        provider = data.get("provider", "gmail")
        wedge_result = await _maybe_handle_wedge_action(
            data,
            message_id=message_id,
            user_id=user_id,
            action="label",
            provider=provider,
            action_name="add_labels",
            requires_label=True,
        )
        if wedge_result is not None:
            return wedge_result

        labels = data.get("labels", [])
        if not labels:
            return error_response("'labels' is required", status=400)

        # Get connector and call modify_message
        connector = await service._get_connector(provider, user_id)
        await connector.modify_message(message_id, add_labels=labels)

        return success_response(
            {
                "message_id": message_id,
                "action": "add_labels",
                "labels": labels,
                "success": True,
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to add labels")
        return error_response("Add labels operation failed", status=500)


@require_permission("email:update")
async def handle_remove_label(
    data: dict[str, Any],
    message_id: str = "",
    user_id: str = "default",
) -> HandlerResult:
    """
    Remove a label from a message.

    POST /api/v1/inbox/messages/{id}/labels/remove
    Body: {
        provider: str ("gmail" or "outlook"),
        labels: list[str]
    }
    """
    try:
        service = get_email_actions_service_instance()

        if not message_id:
            message_id = data.get("message_id", "")
        if not message_id:
            return error_response("message_id is required", status=400)

        labels = data.get("labels", [])
        if not labels:
            return error_response("'labels' is required", status=400)

        provider = data.get("provider", "gmail")

        # Get connector and call modify_message
        connector = await service._get_connector(provider, user_id)
        await connector.modify_message(message_id, remove_labels=labels)

        return success_response(
            {
                "message_id": message_id,
                "action": "remove_labels",
                "labels": labels,
                "success": True,
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to remove labels")
        return error_response("Remove labels operation failed", status=500)


# =============================================================================
# Batch Operations
# =============================================================================


@require_permission("email:update")
async def handle_batch_archive(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Archive multiple messages.

    POST /api/v1/inbox/messages/batch/archive
    Body: {
        provider: str ("gmail" or "outlook"),
        message_ids: list[str]
    }
    """
    try:
        service = get_email_actions_service_instance()

        message_ids = data.get("message_ids", [])
        if not message_ids:
            return error_response("'message_ids' is required", status=400)
        if len(message_ids) > 100:
            return error_response("Maximum 100 messages per batch", status=400)

        provider = data.get("provider", "gmail")

        result = await service.batch_archive(
            provider=provider,
            user_id=user_id,
            message_ids=message_ids,
        )

        if result.success:
            return success_response(
                {
                    "action": "batch_archive",
                    "message_ids": message_ids,
                    "count": len(message_ids),
                    "success": True,
                }
            )
        else:
            return error_response(result.error or "Batch archive failed", status=500)

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to batch archive")
        return error_response("Batch archive failed", status=500)


@require_permission("email:delete")
async def handle_batch_trash(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Trash multiple messages.

    POST /api/v1/inbox/messages/batch/trash
    Body: {
        provider: str ("gmail" or "outlook"),
        message_ids: list[str]
    }

    Returns partial success if some messages fail.
    """
    try:
        service = get_email_actions_service_instance()

        message_ids = data.get("message_ids", [])
        if not message_ids:
            return error_response("'message_ids' is required", status=400)
        if len(message_ids) > 100:
            return error_response("Maximum 100 messages per batch", status=400)

        provider = data.get("provider", "gmail")

        connector = await service._get_connector(provider, user_id)

        # Try batch call first; fall back to per-item on failure
        successful_ids: list[str] = []
        failed_items: list[dict[str, str]] = []

        try:
            await connector.batch_trash(message_ids)
            successful_ids = list(message_ids)
        except (OSError, ConnectionError, RuntimeError, AttributeError) as batch_err:
            logger.warning("Batch trash failed, falling back to per-item: %s", batch_err)
            for msg_id in message_ids:
                try:
                    await connector.trash_message(msg_id)
                    successful_ids.append(msg_id)
                except (OSError, ConnectionError, RuntimeError, AttributeError) as item_err:
                    failed_items.append({"id": msg_id, "error": str(item_err)})

        return success_response(
            {
                "action": "batch_trash",
                "total_count": len(message_ids),
                "successful_count": len(successful_ids),
                "error_count": len(failed_items),
                "successful_ids": successful_ids,
                "failed_items": failed_items,
                "success": len(failed_items) == 0,
                "partial_success": len(successful_ids) > 0 and len(failed_items) > 0,
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to batch trash")
        return error_response("Batch trash failed", status=500)


@require_permission("email:update")
async def handle_batch_modify(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Modify labels on multiple messages.

    POST /api/v1/inbox/messages/batch/modify
    Body: {
        provider: str ("gmail" or "outlook"),
        message_ids: list[str],
        add_labels: list[str] (optional),
        remove_labels: list[str] (optional)
    }

    Returns partial success if some messages fail.
    """
    try:
        service = get_email_actions_service_instance()

        message_ids = data.get("message_ids", [])
        if not message_ids:
            return error_response("'message_ids' is required", status=400)
        if len(message_ids) > 100:
            return error_response("Maximum 100 messages per batch", status=400)

        add_labels = data.get("add_labels", [])
        remove_labels = data.get("remove_labels", [])

        if not add_labels and not remove_labels:
            return error_response(
                "At least one of 'add_labels' or 'remove_labels' is required",
                status=400,
            )

        provider = data.get("provider", "gmail")

        connector = await service._get_connector(provider, user_id)

        # Try batch call first; fall back to per-item on failure
        successful_ids: list[str] = []
        failed_items: list[dict[str, str]] = []

        try:
            await connector.batch_modify(
                message_ids,
                add_labels=add_labels or None,
                remove_labels=remove_labels or None,
            )
            successful_ids = list(message_ids)
        except (OSError, ConnectionError, RuntimeError, AttributeError) as batch_err:
            logger.warning("Batch modify failed, falling back to per-item: %s", batch_err)
            for msg_id in message_ids:
                try:
                    await connector.modify_labels(
                        msg_id,
                        add_labels=add_labels or None,
                        remove_labels=remove_labels or None,
                    )
                    successful_ids.append(msg_id)
                except (OSError, ConnectionError, RuntimeError, AttributeError) as item_err:
                    failed_items.append({"id": msg_id, "error": str(item_err)})

        return success_response(
            {
                "action": "batch_modify",
                "total_count": len(message_ids),
                "successful_count": len(successful_ids),
                "error_count": len(failed_items),
                "successful_ids": successful_ids,
                "failed_items": failed_items,
                "add_labels": add_labels,
                "remove_labels": remove_labels,
                "success": len(failed_items) == 0,
                "partial_success": len(successful_ids) > 0 and len(failed_items) > 0,
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to batch modify")
        return error_response("Batch modify failed", status=500)


# =============================================================================
# Action Logs
# =============================================================================


@require_permission("email:read")
async def handle_get_action_logs(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Get action logs for audit/compliance.

    GET /api/v1/inbox/actions/logs
    Query params:
        action_type: str (optional) - Filter by action type
        provider: str (optional) - Filter by provider
        since: str (optional) - ISO datetime to filter from
        limit: int (optional, default 100) - Max results
    """
    try:
        from aragora.services.email_actions import ActionType, EmailProvider

        service = get_email_actions_service_instance()

        action_type_str = data.get("action_type")
        provider_str = data.get("provider")
        since_str = data.get("since")
        limit = min(int(data.get("limit", 100)), 1000)

        # Parse filters
        action_type = None
        if action_type_str:
            try:
                action_type = ActionType(action_type_str)
            except ValueError:
                return error_response(f"Invalid action_type: {action_type_str}", status=400)

        provider = None
        if provider_str:
            try:
                provider = EmailProvider(provider_str)
            except ValueError:
                return error_response(f"Invalid provider: {provider_str}", status=400)

        since = None
        if since_str:
            try:
                since = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
            except ValueError:
                return error_response("Invalid since format. Use ISO 8601.", status=400)

        logs = await service.get_action_logs(
            user_id=user_id,
            action_type=action_type,
            provider=provider,
            since=since,
            limit=limit,
        )

        return success_response(
            {
                "logs": [log.to_dict() for log in logs],
                "count": len(logs),
                "limit": limit,
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to get action logs")
        return error_response("Failed to retrieve logs", status=500)


@require_permission("admin:audit")
async def handle_export_action_logs(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Export action logs for compliance reporting.

    GET /api/v1/inbox/actions/export
    Query params:
        start_date: str (ISO date, required)
        end_date: str (ISO date, required)
    """
    try:
        service = get_email_actions_service_instance()

        start_date_str = data.get("start_date")
        end_date_str = data.get("end_date")

        if not start_date_str or not end_date_str:
            return error_response("Both start_date and end_date are required", status=400)

        try:
            start_date = datetime.fromisoformat(start_date_str.replace("Z", "+00:00"))
            end_date = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
        except ValueError:
            return error_response("Invalid date format. Use ISO 8601.", status=400)

        if end_date < start_date:
            return error_response("end_date must be after start_date", status=400)

        # Limit to 90 days for export
        max_range = timedelta(days=90)
        if (end_date - start_date) > max_range:
            return error_response("Maximum date range is 90 days", status=400)

        logs = await service.export_action_logs(
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
        )

        return success_response(
            {
                "logs": logs,
                "count": len(logs),
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "user_id": user_id,
                "exported_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ):
        logger.exception("Failed to export action logs")
        return error_response("Export operation failed", status=500)


# =============================================================================
# Handler Registration
# =============================================================================


def get_email_actions_handlers() -> dict[str, Any]:
    """Get all email actions handlers for registration."""
    return {
        # Send / Reply
        "send_email": handle_send_email,
        "reply_email": handle_reply_email,
        # Archive / Trash
        "archive_message": handle_archive_message,
        "trash_message": handle_trash_message,
        "restore_message": handle_restore_message,
        # Snooze
        "snooze_message": handle_snooze_message,
        # Read / Star
        "mark_read": handle_mark_read,
        "mark_unread": handle_mark_unread,
        "star_message": handle_star_message,
        "unstar_message": handle_unstar_message,
        # Folder / Label
        "move_to_folder": handle_move_to_folder,
        "add_label": handle_add_label,
        "remove_label": handle_remove_label,
        # Batch
        "batch_archive": handle_batch_archive,
        "batch_trash": handle_batch_trash,
        "batch_modify": handle_batch_modify,
        # Logs
        "get_action_logs": handle_get_action_logs,
        "export_action_logs": handle_export_action_logs,
    }


__all__ = [
    "get_email_actions_service_instance",
    "get_inbox_trust_wedge_service_instance",
    # Send / Reply
    "handle_send_email",
    "handle_reply_email",
    # Archive / Trash
    "handle_archive_message",
    "handle_trash_message",
    "handle_restore_message",
    # Snooze
    "handle_snooze_message",
    # Read / Star
    "handle_mark_read",
    "handle_mark_unread",
    "handle_star_message",
    "handle_unstar_message",
    # Folder / Label
    "handle_move_to_folder",
    "handle_add_label",
    "handle_remove_label",
    # Batch
    "handle_batch_archive",
    "handle_batch_trash",
    "handle_batch_modify",
    # Logs
    "handle_get_action_logs",
    "handle_export_action_logs",
    # Registration
    "get_email_actions_handlers",
]
