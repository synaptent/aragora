"""
Slack Slash Commands Handler.

This module handles /aragora slash commands from Slack including:
- /aragora ask <question> - Start a new debate
- /aragora plan <question> - Debate + implementation plan
- /aragora implement <question> - Debate + plan with context snapshot
- /aragora status - Show active debates
- /aragora vote - Vote in active debate
- /aragora leaderboard - Show agent rankings
- /aragora help - Show help message
"""

import json
import logging
from typing import Any
from urllib.parse import parse_qs

from aragora.audit.unified import audit_data
from aragora.config import DEFAULT_AGENTS, DEFAULT_ROUNDS
from aragora.server.handlers.base import HandlerResult, json_response
from aragora.server.handlers.utils.rate_limit import rate_limit

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

from .blocks import build_debate_message_blocks
from .constants import (
    AGENT_DISPLAY_NAMES,
    MAX_COMMAND_LENGTH,
    MAX_TOPIC_LENGTH,
    PERM_SLACK_COMMANDS_READ,
    PERM_SLACK_DEBATES_CREATE,
    PERM_SLACK_VOTES_RECORD,
    RBAC_AVAILABLE,
    AuthorizationContext,
    check_permission,
    _validate_slack_channel_id,
    _validate_slack_input,
    _validate_slack_team_id,
    _validate_slack_user_id,
)
from .debates import start_slack_debate
from .state import _active_debates

logger = logging.getLogger(__name__)


@rate_limit(rpm=60)
async def handle_slack_commands(request: Any) -> HandlerResult:
    """Handle Slack slash commands (/aragora).

    RBAC Permissions:
    - slack.commands.read: Required for help/status commands
    - slack.commands.execute: Required for executing commands
    - slack.debates.create: Required for the 'ask' command (creates debates)
    """
    try:
        body = await request.body()
        params = parse_qs(body.decode("utf-8"))

        command = params.get("command", ["/aragora"])[0]
        text = params.get("text", [""])[0]
        user_id = params.get("user_id", [""])[0]
        user_name = params.get("user_name", [""])[0]
        channel_id = params.get("channel_id", [""])[0]
        response_url = params.get("response_url", [""])[0]
        team_id = params.get("team_id", [""])[0]

        # Validate required identifiers
        if user_id:
            valid, error = _validate_slack_user_id(user_id)
            if not valid:
                logger.warning("Invalid user_id in command: %s", error)
                return json_response(
                    {
                        "response_type": "ephemeral",
                        "text": f"Invalid user identification: {error}",
                    }
                )

        if channel_id:
            valid, error = _validate_slack_channel_id(channel_id)
            if not valid:
                logger.warning("Invalid channel_id in command: %s", error)
                return json_response(
                    {
                        "response_type": "ephemeral",
                        "text": f"Invalid channel identification: {error}",
                    }
                )

        if team_id:
            valid, error = _validate_slack_team_id(team_id)
            if not valid:
                logger.warning("Invalid team_id in command: %s", error)
                return json_response(
                    {
                        "response_type": "ephemeral",
                        "text": f"Invalid workspace identification: {error}",
                    }
                )

        # Validate text input
        valid, error = _validate_slack_input(
            text, "command text", MAX_COMMAND_LENGTH, allow_empty=True
        )
        if not valid:
            return json_response(
                {
                    "response_type": "ephemeral",
                    "text": f"Invalid command: {error}",
                }
            )

        # Helper to check permission for commands
        def _check_command_permission(permission: str) -> HandlerResult | None:
            if not RBAC_AVAILABLE or check_permission is None or not team_id:
                if rbac_fail_closed():
                    return json_response(
                        {
                            "response_type": "ephemeral",
                            "text": "Service unavailable: access control module not loaded",
                        }
                    )
                return None
            try:
                context = None
                if AuthorizationContext is not None:
                    context = AuthorizationContext(
                        user_id=f"slack:{user_id}",
                        workspace_id=team_id,
                        roles={"user"},
                    )
                if context:
                    decision = check_permission(context, permission)
                    if not decision.allowed:
                        logger.warning(
                            "Permission denied for command %s: user=%s, team=%s - %s",
                            permission,
                            user_id,
                            team_id,
                            decision.reason,
                        )
                        audit_data(
                            user_id=f"slack:{user_id}",
                            resource_type="slack_permission",
                            resource_id=permission,
                            action="denied",
                            platform="slack",
                            team_id=team_id,
                            command=command,
                        )
                        return json_response(
                            {
                                "response_type": "ephemeral",
                                "text": "Permission denied",
                            }
                        )
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                logger.debug("RBAC check failed for command: %s", e)
            return None

        # Parse subcommand
        parts = text.strip().split(maxsplit=1)
        subcommand = parts[0].lower() if parts else "help"
        args = parts[1] if len(parts) > 1 else ""

        # Audit the command
        audit_data(
            user_id=f"slack:{user_id}",
            resource_type="slack_command",
            resource_id=subcommand,
            action="execute",
            platform="slack",
            team_id=team_id,
            channel_id=channel_id,
            user_name=user_name,
        )

        attachments: list[dict[str, Any]] = []
        raw_attachments = params.get("attachments", [None])[0]
        raw_files = params.get("files", [None])[0]
        for payload in (raw_attachments, raw_files):
            if not payload:
                continue
            try:
                parsed = json.loads(payload)
            except (TypeError, ValueError):
                continue
            if isinstance(parsed, list):
                attachments.extend([item for item in parsed if isinstance(item, dict)])
            elif isinstance(parsed, dict):
                attachments.append(parsed)

        if subcommand in ("ask", "plan", "implement") and args:
            # RBAC: Check debate creation permission
            perm_error = _check_command_permission(PERM_SLACK_DEBATES_CREATE)
            if perm_error:
                return perm_error

            # Validate the debate topic
            valid, error = _validate_slack_input(args, "topic", MAX_TOPIC_LENGTH)
            if not valid:
                return json_response(
                    {
                        "response_type": "ephemeral",
                        "text": f"Invalid topic: {error}",
                    }
                )

            decision_integrity: dict[str, Any] | None = None
            if subcommand == "ask":
                decision_integrity = {
                    "include_receipt": True,
                    "include_plan": False,
                    "notify_origin": True,
                }
            elif subcommand in ("plan", "implement"):
                decision_integrity = {
                    "include_receipt": True,
                    "include_plan": True,
                    "include_context": subcommand == "implement",
                    "plan_strategy": "single_task",
                    "notify_origin": True,
                }
                if subcommand == "implement":
                    decision_integrity["execution_mode"] = "execute"
                    decision_integrity["execution_engine"] = "hybrid"

            debate_id = await start_slack_debate(
                topic=args,
                channel_id=channel_id,
                user_id=user_id,
                response_url=response_url,
                attachments=attachments,
                decision_integrity=decision_integrity,
            )

            mode_label = "debate"
            if subcommand == "plan":
                mode_label = "decision plan"
            elif subcommand == "implement":
                mode_label = "implementation plan"

            return json_response(
                {
                    "response_type": "in_channel",
                    "text": (
                        f"Starting {mode_label}: _{args[:100]}_\n\n"
                        f"Agents are deliberating... (ID: {debate_id[:8]}...)"
                    ),
                    "blocks": build_debate_message_blocks(
                        debate_id=debate_id,
                        task=args,
                        agents=[AGENT_DISPLAY_NAMES.get(a, a) for a in DEFAULT_AGENTS],
                        current_round=1,
                        total_rounds=DEFAULT_ROUNDS,
                        include_vote_buttons=False,
                    ),
                }
            )

        elif subcommand == "status":
            # RBAC: Check read permission for status
            perm_error = _check_command_permission(PERM_SLACK_COMMANDS_READ)
            if perm_error:
                return perm_error

            # Get active debates status
            active_count = len(_active_debates)
            return json_response(
                {
                    "response_type": "ephemeral",
                    "text": f" {active_count} active debate(s) in this workspace",
                }
            )

        elif subcommand == "vote":
            # RBAC: Check vote permission
            perm_error = _check_command_permission(PERM_SLACK_VOTES_RECORD)
            if perm_error:
                return perm_error

            # Vote in active debate
            return json_response(
                {
                    "response_type": "ephemeral",
                    "text": " Use the vote buttons in the debate message to cast your vote",
                }
            )

        elif subcommand == "leaderboard":
            # RBAC: Check read permission for leaderboard
            perm_error = _check_command_permission(PERM_SLACK_COMMANDS_READ)
            if perm_error:
                return perm_error

            # Show agent leaderboard
            return json_response(
                {
                    "response_type": "in_channel",
                    "text": " *Agent Leaderboard*\n1.  Claude - 1850 ELO\n2.  GPT-4 - 1820 ELO\n3.  Gemini - 1780 ELO",
                }
            )

        else:  # help or unknown
            # RBAC: Help is always allowed - no permission check
            return json_response(
                {
                    "response_type": "ephemeral",
                    "text": (
                        "*Aragora Commands*\n\n"
                        "`/aragora ask <question>` - Start a new debate\n"
                        "`/aragora plan <question>` - Debate + implementation plan\n"
                        "`/aragora implement <question>` - Debate + plan with context snapshot\n"
                        "`/aragora status` - Show active debates\n"
                        "`/aragora vote` - Vote in active debate\n"
                        "`/aragora leaderboard` - Show agent rankings\n"
                        "`/aragora help` - Show this message"
                    ),
                }
            )

    except (KeyError, TypeError, ValueError, UnicodeDecodeError) as e:
        logger.error("Slack commands handler error: %s", e)
        return json_response(
            {
                "response_type": "ephemeral",
                "text": "Error: An error occurred processing your command. Please try again.",
            }
        )


__all__ = [
    "handle_slack_commands",
]
