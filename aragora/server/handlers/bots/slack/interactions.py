"""
Slack Interactive Components Handler.

This module handles interactive component callbacks from Slack including:
- Button clicks (votes, summary requests)
- Shortcuts
- Modal submissions
"""

import json
import logging
from typing import Any
from urllib.parse import parse_qs

from aragora.audit.unified import audit_data
from aragora.config import DEFAULT_ROUNDS
from aragora.api_errors import safe_error_message
from aragora.server.handlers.base import HandlerResult, error_response, json_response
from aragora.server.handlers.utils.rate_limit import rate_limit

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

from .blocks import build_start_debate_modal
from .constants import (
    AGENT_DISPLAY_NAMES,
    MAX_COMMAND_LENGTH,
    MAX_TOPIC_LENGTH,
    PERM_SLACK_DEBATES_CREATE,
    PERM_SLACK_INTERACTIVE,
    PERM_SLACK_VOTES_RECORD,
    RBAC_AVAILABLE,
    AuthorizationContext,
    check_permission,
    _validate_slack_input,
    _validate_slack_team_id,
    _validate_slack_user_id,
)
from .state import _active_debates, _user_votes

logger = logging.getLogger(__name__)


@rate_limit(rpm=60)
async def handle_slack_interactions(request: Any) -> HandlerResult:
    """Handle Slack interactive components (button clicks, votes).

    RBAC Permissions:
    - slack.votes.record: Required for recording votes
    - slack.debates.create: Required for creating debates via modal
    - slack.interactive.respond: Required for interactive component responses
    """
    try:
        body = await request.body()

        # Parse form-encoded payload
        parsed = parse_qs(body.decode("utf-8"))
        payload_str = parsed.get("payload", ["{}"])[0]
        payload = json.loads(payload_str)

        interaction_type = payload.get("type")
        user = payload.get("user", {})
        user_id = user.get("id", "unknown")
        user_name = user.get("name", "unknown")

        # Extract team_id for RBAC
        team = payload.get("team", {})
        team_id = team.get("id", "")

        # Validate user_id and team_id
        if user_id != "unknown":
            valid, error = _validate_slack_user_id(user_id)
            if not valid:
                logger.warning("Invalid user_id in interaction: %s", error)
                return json_response(
                    {
                        "response_type": "ephemeral",
                        "text": "Invalid user identification.",
                    }
                )

        if team_id:
            valid, error = _validate_slack_team_id(team_id)
            if not valid:
                logger.warning("Invalid team_id in interaction: %s", error)
                return json_response(
                    {
                        "response_type": "ephemeral",
                        "text": "Invalid workspace identification.",
                    }
                )

        # Helper to check permission for interactions
        def _check_interaction_permission(permission: str) -> HandlerResult | None:
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
                            "Permission denied for interaction %s: user=%s, team=%s",
                            permission,
                            user_id,
                            team_id,
                        )
                        audit_data(
                            user_id=f"slack:{user_id}",
                            resource_type="slack_permission",
                            resource_id=permission,
                            action="denied",
                            platform="slack",
                            team_id=team_id,
                        )
                        return json_response(
                            {
                                "response_type": "ephemeral",
                                "text": "Permission denied",
                            }
                        )
            except (PermissionError, ValueError, TypeError, AttributeError, RuntimeError) as e:
                logger.debug("RBAC check failed for interaction: %s", e)
            return None

        if interaction_type == "block_actions":
            actions = payload.get("actions", [])

            for action in actions:
                action_id = action.get("action_id", "")
                value = action.get("value", "")

                # Validate action_id
                valid, error = _validate_slack_input(action_id, "action_id", MAX_COMMAND_LENGTH)
                if not valid:
                    logger.warning("Invalid action_id: %s", error)
                    continue

                # Handle vote action
                if action_id.startswith("vote_"):
                    # RBAC: Check vote permission
                    perm_error = _check_interaction_permission(PERM_SLACK_VOTES_RECORD)
                    if perm_error:
                        return perm_error

                    try:
                        vote_data = json.loads(value)
                        debate_id = vote_data.get("debate_id", "")
                        agent = vote_data.get("agent", "")

                        # Validate debate_id (UUID format)
                        if not debate_id or len(debate_id) > 100:
                            return json_response(
                                {
                                    "response_type": "ephemeral",
                                    "text": "Invalid debate ID.",
                                }
                            )

                        # Validate agent name
                        valid, error = _validate_slack_input(agent, "agent", 100, allow_empty=False)
                        if not valid:
                            return json_response(
                                {
                                    "response_type": "ephemeral",
                                    "text": f"Invalid agent: {error}",
                                }
                            )

                        # Record user vote
                        if debate_id not in _user_votes:
                            _user_votes[debate_id] = {}

                        _user_votes[debate_id][user_id] = agent

                        logger.info(
                            "User %s voted for %s in debate %s", user_name, agent, debate_id
                        )

                        audit_data(
                            user_id=f"slack:{user_id}",
                            resource_type="debate_vote",
                            resource_id=debate_id,
                            action="create",
                            vote_option=agent,
                            platform="slack",
                            team_id=team_id,
                        )

                        # Return ephemeral confirmation
                        return json_response(
                            {
                                "response_type": "ephemeral",
                                "text": f" Your vote for *{agent}* has been recorded!",
                                "replace_original": False,
                            }
                        )

                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON in vote value")
                        pass

                # Handle summary request
                elif action_id.startswith("summary_"):
                    # RBAC: Check interactive permission
                    perm_error = _check_interaction_permission(PERM_SLACK_INTERACTIVE)
                    if perm_error:
                        return perm_error

                    debate_id = value
                    # Validate debate_id
                    if not debate_id or len(debate_id) > 100:
                        return json_response(
                            {
                                "response_type": "ephemeral",
                                "text": "Invalid debate ID.",
                            }
                        )
                    # Would fetch and return debate summary
                    return json_response(
                        {
                            "response_type": "ephemeral",
                            "text": f"Fetching summary for debate `{debate_id[:8]}...`",
                        }
                    )

        elif interaction_type == "shortcut":
            # Global shortcut triggered
            # RBAC: Check interactive permission
            perm_error = _check_interaction_permission(PERM_SLACK_INTERACTIVE)
            if perm_error:
                return perm_error

            callback_id = payload.get("callback_id", "")
            # Validate callback_id
            valid, error = _validate_slack_input(callback_id, "callback_id", 100)
            if not valid:
                logger.warning("Invalid callback_id: %s", error)
                return json_response({"ok": True})

            if callback_id == "start_debate":
                # Open modal to start debate
                return json_response(
                    {
                        "response_action": "open_modal",
                        "view": build_start_debate_modal(),
                    }
                )

        elif interaction_type == "view_submission":
            # Modal form submitted
            view = payload.get("view", {})
            callback_id = view.get("callback_id", "")

            # Validate callback_id
            valid, error = _validate_slack_input(callback_id, "callback_id", 100)
            if not valid:
                logger.warning("Invalid view callback_id: %s", error)
                return json_response({"ok": True})

            if callback_id == "start_debate_modal":
                # RBAC: Check debate creation permission
                perm_error = _check_interaction_permission(PERM_SLACK_DEBATES_CREATE)
                if perm_error:
                    return json_response(
                        {
                            "response_action": "errors",
                            "errors": {
                                "task_block": "You do not have permission to create debates."
                            },
                        }
                    )

                # Parse submitted values and start debate
                values = view.get("state", {}).get("values", {})

                # Extract task from task_block
                task = values.get("task_block", {}).get("task_input", {}).get("value", "")

                # Validate task input
                valid, error = _validate_slack_input(task, "task", MAX_TOPIC_LENGTH)
                if not valid:
                    return json_response(
                        {
                            "response_action": "errors",
                            "errors": {"task_block": error or "Invalid task input"},
                        }
                    )

                # Extract agents from agents_block (multi-select returns list)
                agents_data = (
                    values.get("agents_block", {})
                    .get("agents_select", {})
                    .get("selected_options", [])
                )
                agents = [opt.get("value", "") for opt in agents_data]

                # Validate agent names
                for agent in agents:
                    valid, error = _validate_slack_input(agent, "agent", 50)
                    if not valid:
                        return json_response(
                            {
                                "response_action": "errors",
                                "errors": {"agents_block": f"Invalid agent: {error}"},
                            }
                        )

                # Extract rounds from rounds_block
                rounds_str = (
                    values.get("rounds_block", {})
                    .get("rounds_select", {})
                    .get("selected_option", {})
                    .get("value", str(DEFAULT_ROUNDS))
                )
                # Validate rounds is a digit and in reasonable range
                if not rounds_str.isdigit() or not (1 <= int(rounds_str) <= 20):
                    rounds = DEFAULT_ROUNDS
                else:
                    rounds = int(rounds_str)

                if not task:
                    return json_response(
                        {
                            "response_action": "errors",
                            "errors": {"task_block": "Please enter a debate task"},
                        }
                    )

                if not agents:
                    return json_response(
                        {
                            "response_action": "errors",
                            "errors": {"agents_block": "Please select at least one agent"},
                        }
                    )

                # Generate debate ID and store in active debates
                import uuid

                debate_id = str(uuid.uuid4())

                # Map agent values to display names using module-level constant
                agent_display_names = [AGENT_DISPLAY_NAMES.get(a, a) for a in agents]

                _active_debates[debate_id] = {
                    "task": task,
                    "agents": agent_display_names,
                    "rounds": rounds,
                    "current_round": 1,
                    "status": "running",
                    "user_id": user.get("id"),
                    "team_id": team_id,  # Track workspace for RBAC
                }

                logger.info(
                    "Started debate %s from Slack modal: task='%s...', agents=%s, rounds=%s",
                    debate_id,
                    task[:50],
                    agents,
                    rounds,
                )

                audit_data(
                    user_id=f"slack:{user.get('id', 'unknown')}",
                    resource_type="debate",
                    resource_id=debate_id,
                    action="create",
                    platform="slack",
                    task_preview=task[:100],
                    team_id=team_id,
                )

                return json_response({"response_action": "clear"})

        return json_response({"ok": True})

    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error("Slack interactions handler error: %s", e)
        return error_response(safe_error_message(e, "Slack interaction"), 500)


__all__ = [
    "handle_slack_interactions",
]
