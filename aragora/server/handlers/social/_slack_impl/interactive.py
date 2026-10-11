"""
Slack interactive component handlers.

Handles button clicks, menu selections, and other interactive components
from Slack messages (votes, view details, etc.).
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import parse_qs

from .config import (
    HandlerResult,
    auto_error_response,
    error_response,
    _get_audit_logger,
    json_response,
)
from .config import rate_limit
from .messaging import MessagingMixin

logger = logging.getLogger(__name__)


class InteractiveMixin(MessagingMixin):
    """Mixin providing interactive component handling for the Slack handler."""

    @auto_error_response("handle slack interactive")
    @rate_limit(requests_per_minute=60, limiter_name="slack_interactive")
    def _handle_interactive(self, handler: Any) -> HandlerResult:
        """Handle interactive component callbacks.

        This handles button clicks, menu selections, etc. from Slack messages.
        """
        try:
            # Use pre-read body from handle()
            body = getattr(handler, "_slack_body", "")
            # Workspace context available for future use
            _workspace = getattr(handler, "_slack_workspace", None)  # noqa: F841
            _team_id = getattr(handler, "_slack_team_id", None)  # noqa: F841

            # Interactive payloads come as form-encoded with a 'payload' field
            params = parse_qs(body)
            payload_str = params.get("payload", ["{}"])[0]
            try:
                payload = json.loads(payload_str)
            except json.JSONDecodeError as e:
                logger.error("Invalid JSON in Slack interactive payload: %s", e)
                return error_response("Invalid JSON payload", 400)

            action_type = payload.get("type")
            user = payload.get("user", {})
            user_id = user.get("id", "unknown")
            team = payload.get("team", {})
            team_id = team.get("id", _team_id or "")

            logger.info("Interactive action from %s: %s", user_id, action_type)

            # Audit log the interactive action
            audit = _get_audit_logger()
            if audit:
                audit.log_event(
                    workspace_id=team_id,
                    event_type=f"interactive:{action_type}",
                    payload_summary={"action_type": action_type},
                    user_id=user_id,
                    success=True,
                )

            if action_type == "block_actions":
                actions = payload.get("actions", [])
                if actions:
                    action = actions[0]
                    action_id = action.get("action_id", "")

                    if action_id.startswith("vote_"):
                        return self._handle_vote_action(payload, action)
                    elif action_id == "view_details":
                        return self._handle_view_details(payload, action)

            # Acknowledge the action
            return json_response({"text": "Action received"})

        except (ValueError, KeyError, TypeError) as e:
            logger.warning("Invalid interactive payload data: %s", e)
            return json_response(
                {"text": "Sorry, an error occurred while processing your request."}
            )
        except (ValueError, KeyError, TypeError, RuntimeError, OSError, ConnectionError) as e:
            logger.exception("Unexpected interactive handler error: %s", e)
            return json_response(
                {"text": "Sorry, an error occurred while processing your request."}
            )

    def _handle_vote_action(self, payload: dict[str, Any], action: dict[str, Any]) -> HandlerResult:
        """Handle vote button clicks."""
        action_id = action.get("action_id", "")
        user = payload.get("user", {})
        user_id = user.get("id", "unknown")

        # Extract debate_id and vote from action
        # Expected format: vote_<debate_id>_<option>
        parts = action_id.split("_")
        if len(parts) >= 3:
            debate_id = parts[1]
            vote_option = parts[2]  # 'agree' or 'disagree'

            logger.info("Vote received: %s -> %s from %s", debate_id, vote_option, user_id)

            # Record vote in debate system
            try:
                from aragora.storage.debate_storage import get_debates_db

                db = get_debates_db()
                if db and hasattr(db, "record_vote"):
                    db.record_vote(
                        debate_id=debate_id,
                        voter_id=f"slack:{user_id}",
                        vote=vote_option,
                        source="slack",
                    )
                    logger.info("Vote recorded: %s -> %s", debate_id, vote_option)
            except (ImportError, KeyError, OSError, RuntimeError) as e:
                logger.warning("Failed to record vote in storage: %s", e)

            # Try to record in vote aggregator if available
            try:
                from aragora.debate.vote_aggregator import VoteAggregator

                aggregator = VoteAggregator.get_instance()
                if aggregator:
                    position = "for" if vote_option == "agree" else "against"
                    aggregator.record_vote(debate_id, f"slack:{user_id}", position)
            except (ImportError, AttributeError) as e:
                logger.debug("Vote aggregator not available: %s", e)

            emoji = "\U0001f44d" if vote_option == "agree" else "\U0001f44e"
            return json_response(
                {
                    "text": f"{emoji} Your vote for '{vote_option}' has been recorded!",
                    "replace_original": False,
                }
            )

        return json_response({"text": "Vote recorded"})

    def _handle_view_details(
        self, payload: dict[str, Any], action: dict[str, Any]
    ) -> HandlerResult:
        """Handle view details button clicks."""
        debate_id = action.get("value", "")

        if not debate_id:
            return json_response(
                {
                    "text": "Error: No debate ID provided",
                    "replace_original": False,
                }
            )

        # Fetch debate details
        debate_data = None
        try:
            from aragora.storage.debate_storage import get_debates_db

            db = get_debates_db()
            if db:
                debate_data = db.get(debate_id)
        except (ImportError, KeyError, OSError, RuntimeError) as e:
            logger.warning("Failed to fetch debate details: %s", e)

        if not debate_data:
            return json_response(
                {
                    "text": f"Debate `{debate_id}` not found",
                    "replace_original": False,
                }
            )

        # Build detailed response
        task = debate_data.get("task", "Unknown topic")
        final_answer = debate_data.get("final_answer", "No conclusion")
        consensus = debate_data.get("consensus_reached", False)
        confidence = debate_data.get("confidence", 0)
        rounds_used = debate_data.get("rounds_used", 0)
        agents = debate_data.get("agents", [])
        created_at = debate_data.get("created_at", "Unknown")

        # Format agent names
        agent_list = ", ".join(agents[:5]) if agents else "Unknown"
        if len(agents) > 5:
            agent_list += f" (+{len(agents) - 5} more)"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Debate Details",
                    "emoji": True,
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Topic:*\n{task[:200]}",
                },
            },
            {
                "type": "divider",
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Debate ID:*\n`{debate_id}`"},
                    {"type": "mrkdwn", "text": f"*Created:*\n{created_at}"},
                    {"type": "mrkdwn", "text": f"*Consensus:*\n{'Yes' if consensus else 'No'}"},
                    {"type": "mrkdwn", "text": f"*Confidence:*\n{confidence:.1%}"},
                    {"type": "mrkdwn", "text": f"*Rounds:*\n{rounds_used}"},
                    {"type": "mrkdwn", "text": f"*Agents:*\n{agent_list}"},
                ],
            },
            {
                "type": "divider",
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Conclusion:*\n{final_answer[:800] if final_answer else 'No conclusion available'}",
                },
            },
        ]

        return json_response(
            {
                "response_type": "ephemeral",
                "text": f"Details for debate {debate_id}",
                "blocks": blocks,
                "replace_original": False,
            }
        )
