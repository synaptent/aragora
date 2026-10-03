"""
Slack Events API Handler.

This module handles incoming Slack Events API webhooks including:
- URL verification challenges
- App mentions
- Message events
- App uninstall/token revocation events
"""

import asyncio
import json
import logging
import re
from typing import Any

from aragora.audit.unified import audit_data
from aragora.server.errors import safe_error_message
from aragora.server.handlers.base import HandlerResult, error_response, json_response
from aragora.server.handlers.utils.rate_limit import rate_limit

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

from .constants import (
    MAX_TOPIC_LENGTH,
    PERM_SLACK_COMMANDS_EXECUTE,
    RBAC_AVAILABLE,
    AuthorizationContext,
    check_permission,
    _validate_slack_channel_id,
    _validate_slack_input,
    _validate_slack_team_id,
    _validate_slack_user_id,
)

logger = logging.getLogger(__name__)


def _extract_slack_attachments(
    event: dict[str, Any], max_preview: int = 2000
) -> list[dict[str, Any]]:
    """Extract Slack file and attachment metadata into a normalized list."""
    attachments: list[dict[str, Any]] = []

    files = event.get("files", [])
    if isinstance(files, list):
        for file in files:
            if not isinstance(file, dict):
                continue
            preview = (
                file.get("preview_plain_text")
                or file.get("preview")
                or file.get("initial_comment", {}).get("comment")
                or ""
            )
            if isinstance(preview, str) and len(preview) > max_preview:
                preview = preview[:max_preview] + "..."
            attachments.append(
                {
                    "type": "slack_file",
                    "file_id": file.get("id"),
                    "filename": file.get("name") or file.get("title") or "file",
                    "content_type": file.get("mimetype") or file.get("filetype"),
                    "size": file.get("size"),
                    "url": file.get("url_private_download")
                    or file.get("url_private")
                    or file.get("permalink"),
                    "text": preview,
                }
            )

    event_attachments = event.get("attachments", [])
    if isinstance(event_attachments, list):
        for attachment in event_attachments:
            if not isinstance(attachment, dict):
                continue
            text = attachment.get("text") or attachment.get("fallback") or ""
            if isinstance(text, str) and len(text) > max_preview:
                text = text[:max_preview] + "..."
            attachments.append(
                {
                    "type": "slack_attachment",
                    "filename": attachment.get("title") or "attachment",
                    "title": attachment.get("title"),
                    "url": attachment.get("title_link") or attachment.get("from_url"),
                    "text": text,
                }
            )

    return attachments


async def _hydrate_slack_attachments(
    attachments: list[dict[str, Any]],
    max_bytes: int = 2_000_000,
) -> list[dict[str, Any]]:
    """Best-effort download of Slack file attachments into attachment payloads."""
    if not attachments:
        return attachments

    try:
        from aragora.connectors.chat.registry import get_connector
    except ImportError as e:
        logger.debug("Slack connector unavailable for downloads: %s", e)
        return attachments

    connector = get_connector("slack")
    if connector is None:
        return attachments

    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        file_id = attachment.get("file_id")
        if not file_id or attachment.get("data") or attachment.get("content"):
            continue
        size = attachment.get("size")
        if isinstance(size, int) and size > max_bytes:
            logger.debug("Skipping Slack file %s (size %s > %s)", file_id, size, max_bytes)
            continue
        try:
            file_obj = await connector.download_file(str(file_id))
            content = getattr(file_obj, "content", None)
            if content:
                attachment["data"] = content
                if not attachment.get("filename") and getattr(file_obj, "filename", None):
                    attachment["filename"] = file_obj.filename
                if not attachment.get("content_type") and getattr(file_obj, "content_type", None):
                    attachment["content_type"] = file_obj.content_type
                if not attachment.get("size") and getattr(file_obj, "size", None):
                    attachment["size"] = file_obj.size
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.debug("Failed to download Slack file %s: %s", file_id, e)

    return attachments


@rate_limit(rpm=60)
async def handle_slack_events(request: Any) -> HandlerResult:
    """Handle Slack Events API webhook.

    RBAC: Events from Slack are processed based on event type:
    - url_verification: No auth required (Slack challenge)
    - app_mention: Requires slack.commands.execute for command processing
    - app_uninstalled/tokens_revoked: System events, no user auth
    """
    try:
        body = await request.body()
        data = json.loads(body)

        # URL verification challenge - no auth required
        if data.get("type") == "url_verification":
            challenge = data.get("challenge", "")
            # Validate challenge to prevent injection
            if len(challenge) > 500:
                return error_response("Invalid challenge length", 400)
            return json_response({"challenge": challenge})

        # Extract team_id for workspace authorization
        team_id = data.get("team_id", "")
        event = data.get("event", {})
        event_type = event.get("type")

        # Validate team_id format for non-system events
        if event_type not in ("app_uninstalled", "tokens_revoked"):
            if team_id:
                valid, error = _validate_slack_team_id(team_id)
                if not valid:
                    logger.warning("Invalid team_id in event: %s", error)
                    return error_response(error or "Invalid team ID", 400)

        if event_type == "app_mention":
            # Bot was mentioned - could trigger a debate
            text = event.get("text", "")
            channel = event.get("channel", "")
            user = event.get("user", "")

            # Validate inputs
            valid, error = _validate_slack_user_id(user)
            if not valid:
                logger.warning("Invalid user_id in app_mention: %s", error)
                return json_response({"ok": True})  # Silent fail for invalid user

            valid, error = _validate_slack_channel_id(channel)
            if not valid:
                logger.warning("Invalid channel_id in app_mention: %s", error)
                return json_response({"ok": True})

            # Validate text input
            valid, error = _validate_slack_input(text, "text", MAX_TOPIC_LENGTH, allow_empty=True)
            if not valid:
                logger.warning("Invalid text in app_mention: %s", error)
                return json_response(
                    {
                        "response_type": "ephemeral",
                        "text": f"Invalid input: {error}",
                    }
                )

            # RBAC check for command execution
            if not RBAC_AVAILABLE:
                if rbac_fail_closed():
                    return json_response(
                        {
                            "response_type": "ephemeral",
                            "text": "Service unavailable: access control module not loaded",
                        }
                    )
            elif check_permission is not None and team_id:
                try:
                    context = None
                    if AuthorizationContext is not None:
                        context = AuthorizationContext(
                            user_id=f"slack:{user}",
                            workspace_id=team_id,
                            roles={"user"},
                        )
                    if context:
                        decision = check_permission(context, PERM_SLACK_COMMANDS_EXECUTE)
                        if not decision.allowed:
                            logger.warning(
                                "Permission denied for app_mention: user=%s, team=%s",
                                user,
                                team_id,
                            )
                            return json_response(
                                {
                                    "response_type": "ephemeral",
                                    "text": "You do not have permission to execute commands.",
                                }
                            )
                except (TypeError, ValueError, KeyError, AttributeError, RuntimeError) as e:
                    logger.debug("RBAC check failed for app_mention: %s", e)

            logger.info("Slack mention from %s in %s: %s", user, channel, text[:100])

            clean_text = re.sub(r"<@[^>]+>", "", text).strip()
            decision_integrity: dict[str, Any] | None = None
            if clean_text:
                parts = clean_text.split(maxsplit=1)
                command = parts[0].lower()
                remainder = parts[1] if len(parts) > 1 else ""
                if command in ("ask", "debate", "aragora"):
                    decision_integrity = {
                        "include_receipt": True,
                        "include_plan": False,
                        "notify_origin": True,
                    }
                    clean_text = remainder
                elif command in ("plan", "implement"):
                    decision_integrity = {
                        "include_receipt": True,
                        "include_plan": True,
                        "include_context": command == "implement",
                        "plan_strategy": "single_task",
                        "notify_origin": True,
                    }
                    if command == "implement":
                        decision_integrity["execution_mode"] = "execute"
                        decision_integrity["execution_engine"] = "hybrid"
                    clean_text = remainder

            attachments = _extract_slack_attachments(event)
            attachments = await _hydrate_slack_attachments(attachments)

            if clean_text:
                try:
                    from aragora.core import (
                        DecisionConfig,
                        DecisionRequest,
                        DecisionType,
                        InputSource,
                        RequestContext,
                        ResponseChannel,
                        get_decision_router,
                    )

                    response_channel = ResponseChannel(
                        platform="slack",
                        channel_id=channel,
                        user_id=user,
                        thread_id=event.get("thread_ts") or event.get("ts"),
                    )
                    context = RequestContext(
                        user_id=user,
                        session_id=f"slack:{channel}",
                        metadata={"team_id": team_id},
                    )
                    request_kwargs = {
                        "content": clean_text,
                        "decision_type": DecisionType.DEBATE,
                        "source": InputSource.SLACK,
                        "response_channels": [response_channel],
                        "context": context,
                        "attachments": attachments,
                    }
                    if decision_integrity is not None:
                        request_kwargs["config"] = DecisionConfig(
                            decision_integrity=decision_integrity
                        )
                    request = DecisionRequest(**request_kwargs)  # type: ignore[arg-type]
                    router = get_decision_router()
                    task = asyncio.create_task(router.route(request))
                    task.add_done_callback(
                        lambda t: logger.error("Slack debate routing failed: %s", t.exception())
                        if not t.cancelled() and t.exception()
                        else None
                    )
                except ImportError:
                    logger.debug("DecisionRouter not available for Slack app_mention")
                except (RuntimeError, ValueError, KeyError, AttributeError, TypeError) as e:
                    logger.error("Failed to route Slack app_mention: %s", e)

            # Parse command from mention
            # Format: @aragora ask "question" or @aragora status
            return json_response(
                {
                    "response_type": "in_channel",
                    "text": "Received your request. Processing...",
                }
            )

        elif event_type == "message":
            # Direct message or channel message
            pass

        elif event_type == "app_uninstalled":
            # App was uninstalled from workspace - clean up tokens
            # System event - no user permission check needed
            team_id = data.get("team_id") or event.get("team_id")
            if team_id:
                # Validate team_id even for uninstall events
                valid, _ = _validate_slack_team_id(team_id)
                if not valid:
                    logger.warning("Invalid team_id in app_uninstalled event")
                    return json_response({"ok": True})

                try:
                    from aragora.storage.slack_workspace_store import get_slack_workspace_store

                    store = get_slack_workspace_store()
                    store.revoke_token(team_id)
                    logger.info("Slack app uninstalled from workspace %s", team_id)

                    audit_data(
                        user_id="system",
                        resource_type="slack_workspace",
                        resource_id=team_id,
                        action="uninstall",
                        platform="slack",
                    )
                except (ImportError, RuntimeError, OSError, KeyError, AttributeError) as e:
                    logger.error("Failed to handle app_uninstalled for %s: %s", team_id, e)

            return json_response({"ok": True})

        elif event_type == "tokens_revoked":
            # Tokens were revoked (e.g., user deauthorized) - also clean up
            # System event - no user permission check needed
            team_id = data.get("team_id") or event.get("team_id")
            if team_id:
                # Validate team_id
                valid, _ = _validate_slack_team_id(team_id)
                if not valid:
                    logger.warning("Invalid team_id in tokens_revoked event")
                    return json_response({"ok": True})

                try:
                    from aragora.storage.slack_workspace_store import get_slack_workspace_store

                    store = get_slack_workspace_store()
                    store.revoke_token(team_id)
                    logger.info("Slack tokens revoked for workspace %s", team_id)
                except (ImportError, RuntimeError, OSError, KeyError, AttributeError) as e:
                    logger.error("Failed to handle tokens_revoked for %s: %s", team_id, e)

            return json_response({"ok": True})

        return json_response({"ok": True})

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error("Slack events handler error: %s", e)
        return error_response(safe_error_message(e, "Slack event"), 500)


__all__ = [
    "handle_slack_events",
]
