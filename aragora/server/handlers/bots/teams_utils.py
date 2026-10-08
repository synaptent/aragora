"""
Teams Bot utility functions.

Extracted from teams.py to reduce file size. Contains:
- Conversation reference management
- Bot Framework availability checks
- JWT token verification
- Adaptive Card builders (debate, consensus)
- Debate orchestration (start, fallback, vote counting)
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from collections.abc import Callable
from typing import Any, cast

logger = logging.getLogger(__name__)

# Store active debates for Teams (in production, use Redis/database)
_active_debates: dict[str, dict[str, Any]] = {}
_user_votes: dict[str, dict[str, str]] = {}  # debate_id -> {user_id: vote}

# Conversation reference store for proactive messaging.
_conversation_references: dict[str, dict[str, Any]] = {}


# =============================================================================
# Conversation Reference Management
# =============================================================================


def _store_conversation_reference(activity: dict[str, Any]) -> None:
    """Store conversation reference from an activity for proactive messaging.

    The conversation reference contains everything needed to send a proactive
    message later (service URL, conversation ID, bot identity, tenant info).

    Args:
        activity: Bot Framework activity payload.
    """
    conversation = activity.get("conversation", {})
    conversation_id = conversation.get("id", "")
    if not conversation_id:
        return

    _conversation_references[conversation_id] = {
        "service_url": activity.get("serviceUrl", ""),
        "conversation": conversation,
        "bot": activity.get("recipient", {}),
        "tenant_id": conversation.get("tenantId", ""),
        "channel_data": activity.get("channelData", {}),
    }


def get_conversation_reference(conversation_id: str) -> dict[str, Any] | None:
    """Get stored conversation reference for proactive messaging.

    Args:
        conversation_id: The conversation ID to look up.

    Returns:
        Conversation reference dict or None if not found.
    """
    return _conversation_references.get(conversation_id)


# =============================================================================
# Availability Checks
# =============================================================================


def _check_botframework_available() -> tuple[bool, str | None]:
    """Check if Bot Framework SDK is available."""
    try:
        from botbuilder.core import TurnContext  # noqa: F401 - availability check

        return True, None
    except ImportError:
        return False, "botbuilder-core not installed"


def _check_connector_available() -> tuple[bool, str | None]:
    """Check if Teams connector is available."""
    try:
        from aragora.connectors.chat.teams import TeamsConnector  # noqa: F401

        return True, None
    except ImportError:
        return False, "Teams connector not available"


# =============================================================================
# Token Verification
# =============================================================================


async def _verify_teams_token(auth_header: str, app_id: str) -> bool:
    """Verify Bot Framework JWT token from the Authorization header.

    Validates the incoming JWT against Microsoft's JWKS signing keys,
    checking signature, issuer, audience, and expiry claims.

    The function delegates to the centralized JWT verifier in
    ``aragora.connectors.chat.jwt_verify`` which handles:
    - OpenID metadata discovery to resolve the JWKS endpoint
    - JWKS key caching with TTL to avoid per-request network calls
    - RS256 signature verification
    - Issuer validation against known Bot Framework issuers
    - Audience validation against the configured app ID

    Security: This function follows a fail-closed model. If PyJWT is not
    installed or the verification module is unavailable, tokens are rejected
    in production environments. In development, unverified tokens may be
    allowed if ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS is explicitly set.

    Args:
        auth_header: The full Authorization header value (e.g., "Bearer eyJ...")
        app_id: The Microsoft Bot Application ID to validate the audience claim against.
                Sourced from TEAMS_APP_ID or MS_APP_ID environment variable.

    Returns:
        True if the token is valid, False otherwise (fail-closed)
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        logger.warning("Teams auth rejected: missing or malformed Authorization header")
        return False

    try:
        from aragora.connectors.chat.jwt_verify import HAS_JWT, verify_teams_webhook

        if HAS_JWT:
            return verify_teams_webhook(auth_header, app_id)
        else:
            # PyJWT not installed - check if dev bypass is allowed
            from aragora.connectors.chat.webhook_security import should_allow_unverified

            if should_allow_unverified("teams"):
                logger.warning(
                    "Teams token verification skipped - PyJWT not available (dev mode). "
                    "Install pyjwt[crypto] for production use."
                )
                return True
            logger.error(
                "Teams token rejected - PyJWT library not available. "
                "Install with: pip install pyjwt[crypto]"
            )
            return False
    except ImportError:
        # jwt_verify module itself not available - check environment
        env = os.environ.get("ARAGORA_ENV", "production").lower()
        is_production = env not in ("development", "dev", "local", "test")
        if is_production:
            logger.error(
                "SECURITY: Teams JWT verification module not available in production. "
                "Ensure aragora.connectors.chat.jwt_verify is importable."
            )
            return False
        logger.warning("Teams token verification skipped (dev mode - jwt_verify not importable)")
        return True


# =============================================================================
# Adaptive Card Builders
# =============================================================================


def build_debate_card(
    debate_id: str,
    topic: str,
    agents: list[str],
    current_round: int,
    total_rounds: int,
    include_vote_buttons: bool = True,
) -> dict[str, Any]:
    """Build an Adaptive Card for active debate display."""
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": "Active Debate",
            "weight": "Bolder",
            "size": "Large",
        },
        {
            "type": "TextBlock",
            "text": f"**Topic:** {topic[:200]}",
            "wrap": True,
        },
        {
            "type": "FactSet",
            "facts": [
                {"title": "Agents", "value": ", ".join(agents[:5])},
                {"title": "Progress", "value": f"Round {current_round}/{total_rounds}"},
            ],
        },
    ]

    actions: list[dict[str, Any]] = []

    if include_vote_buttons:
        # Add voting buttons for each agent (max 5)
        for agent in agents[:5]:
            actions.append(
                {
                    "type": "Action.Submit",
                    "title": f"Vote {agent}",
                    "data": {
                        "action": "vote",
                        "debate_id": debate_id,
                        "agent": agent,
                    },
                }
            )

        # Add view summary action
        actions.append(
            {
                "type": "Action.Submit",
                "title": "View Summary",
                "data": {"action": "summary", "debate_id": debate_id},
            }
        )

    # Footer with debate ID
    body.append(
        {
            "type": "TextBlock",
            "text": f"Debate ID: {debate_id[:8]}...",
            "size": "Small",
            "isSubtle": True,
        }
    )

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
        "actions": actions if actions else None,
    }


def build_consensus_card(
    debate_id: str,
    topic: str,
    consensus_reached: bool,
    confidence: float,
    winner: str | None,
    final_answer: str | None,
    vote_counts: dict[str, int],
) -> dict[str, Any]:
    """Build an Adaptive Card for debate consensus results."""
    status_text = "Consensus Reached" if consensus_reached else "No Consensus"
    status_color = "Good" if consensus_reached else "Warning"

    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": status_text,
            "weight": "Bolder",
            "size": "Large",
            "color": status_color,
        },
        {
            "type": "TextBlock",
            "text": f"**Topic:** {topic[:200]}",
            "wrap": True,
        },
    ]

    # Results facts
    facts = [{"title": "Confidence", "value": f"{confidence:.0%}"}]
    if winner:
        facts.append({"title": "Winner", "value": winner})

    body.append({"type": "FactSet", "facts": facts})

    # User votes if any
    if vote_counts:
        vote_text = "\n".join(
            f"- {agent}: {count} vote{'s' if count != 1 else ''}"
            for agent, count in sorted(vote_counts.items(), key=lambda x: -x[1])
        )
        body.append(
            {
                "type": "TextBlock",
                "text": f"**User Votes:**\n{vote_text}",
                "wrap": True,
            }
        )

    # Final answer preview
    if final_answer:
        preview = final_answer[:500]
        if len(final_answer) > 500:
            preview += "..."
        body.append({"type": "TextBlock", "text": "---", "separator": True})
        body.append(
            {
                "type": "TextBlock",
                "text": f"**Decision:**\n{preview}",
                "wrap": True,
            }
        )

    # Action buttons
    actions = [
        {
            "type": "Action.OpenUrl",
            "title": "View Full Report",
            "url": f"https://aragora.ai/debate/{debate_id}",
        },
        {
            "type": "Action.OpenUrl",
            "title": "Audit Trail",
            "url": f"https://aragora.ai/debates/provenance?debate={debate_id}",
        },
    ]

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
        "actions": actions,
    }


# =============================================================================
# Debate Orchestration
# =============================================================================


async def _start_teams_debate(
    topic: str,
    conversation_id: str,
    user_id: str,
    service_url: str,
    thread_id: str | None = None,
    attachments: list[dict[str, Any]] | None = None,
    decision_integrity: dict[str, Any] | bool | None = None,
) -> str:
    """Start a debate from Teams via DecisionRouter.

    Uses the unified DecisionRouter for:
    - Deduplication (prevents duplicate debates for same topic/user)
    - Caching (returns cached results if available)
    - Origin registration for result routing
    """
    debate_id = str(uuid.uuid4())

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

        # Create response channel for result routing
        response_channel = cast(Callable[..., Any], ResponseChannel)(
            platform="teams",
            channel_id=conversation_id,
            user_id=user_id,
            thread_id=thread_id,
            webhook_url=service_url,  # Teams uses service_url for proactive messaging
        )

        # Create request context
        context = cast(Callable[..., Any], RequestContext)(
            user_id=user_id,
            session_id=f"teams:{conversation_id}",
        )

        config = None
        if decision_integrity is not None:
            if isinstance(decision_integrity, bool):
                decision_integrity = {} if decision_integrity else None
            if isinstance(decision_integrity, dict):
                config = cast(Callable[..., Any], DecisionConfig)(
                    decision_integrity=decision_integrity
                )

        request_kwargs = {
            "content": topic,
            "decision_type": cast(Any, DecisionType).DEBATE,
            "source": cast(Any, InputSource).TEAMS,
            "response_channels": [response_channel],
            "context": context,
            "attachments": attachments or [],
            "request_id": debate_id,
        }
        if config is not None:
            request_kwargs["config"] = config

        # Create decision request
        request = cast(Callable[..., Any], DecisionRequest)(**request_kwargs)

        # Register origin for result routing (best-effort)
        try:
            from aragora.server.debate_origin import register_debate_origin

            register_debate_origin(
                debate_id=request.request_id,
                platform="teams",
                channel_id=conversation_id,
                user_id=user_id,
                thread_id=thread_id,
                metadata={
                    "topic": topic,
                    "service_url": service_url,
                },
            )
        except (RuntimeError, KeyError, AttributeError, OSError) as exc:
            logger.debug("Failed to register Teams debate origin: %s", exc)

        # Route through DecisionRouter
        router = cast(Callable[..., Any], get_decision_router)()
        result = await router.route(request)

        if result.request_id and result.request_id != request.request_id:
            try:
                from aragora.server.debate_origin import register_debate_origin

                register_debate_origin(
                    debate_id=result.request_id,
                    platform="teams",
                    channel_id=conversation_id,
                    user_id=user_id,
                    thread_id=thread_id,
                    metadata={
                        "topic": topic,
                        "service_url": service_url,
                    },
                )
            except (RuntimeError, KeyError, AttributeError, OSError) as exc:
                logger.debug("Failed to register dedup Teams origin: %s", exc)

        if result.request_id:
            logger.info("DecisionRouter started debate %s from Teams", result.request_id)
            _active_debates[result.request_id] = {
                "topic": topic,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "service_url": service_url,
                "thread_id": thread_id,
                "started_at": time.time(),
            }
            return result.request_id
        return debate_id

    except ImportError:
        logger.debug("DecisionRouter not available, using fallback")
        return await _fallback_start_debate(
            topic, conversation_id, user_id, debate_id, service_url, thread_id
        )
    except (RuntimeError, ValueError, KeyError, AttributeError) as e:
        logger.error("DecisionRouter failed: %s, using fallback", e)
        return await _fallback_start_debate(
            topic, conversation_id, user_id, debate_id, service_url, thread_id
        )


async def _fallback_start_debate(
    topic: str,
    conversation_id: str,
    user_id: str,
    debate_id: str,
    service_url: str,
    thread_id: str | None = None,
) -> str:
    """Fallback debate start when DecisionRouter unavailable."""
    # Register origin for result routing
    try:
        from aragora.server.debate_origin import register_debate_origin

        register_debate_origin(
            debate_id=debate_id,
            platform="teams",
            channel_id=conversation_id,
            user_id=user_id,
            thread_id=thread_id,
            metadata={
                "topic": topic,
                "service_url": service_url,
                "webhook_url": service_url,
            },
        )
    except (RuntimeError, KeyError, AttributeError, OSError) as e:
        logger.warning("Failed to register debate origin: %s", e)

    # Try to enqueue via Redis queue
    try:
        from aragora.queue import create_debate_job, create_redis_queue

        job = create_debate_job(
            question=topic,
            user_id=user_id,
            metadata={
                "debate_id": debate_id,
                "platform": "teams",
                "conversation_id": conversation_id,
                "service_url": service_url,
                "thread_id": thread_id,
            },
        )
        queue = await create_redis_queue()
        await queue.enqueue(job)
        logger.info("Debate %s enqueued via Redis queue", debate_id)
    except ImportError:
        logger.warning("Redis queue not available, debate will run inline")
    except (RuntimeError, OSError, ConnectionError) as e:
        logger.warning("Failed to enqueue debate: %s", e)

    # Track active debate
    _active_debates[debate_id] = {
        "topic": topic,
        "conversation_id": conversation_id,
        "user_id": user_id,
        "service_url": service_url,
        "thread_id": thread_id,
        "started_at": time.time(),
    }

    return debate_id


def get_debate_vote_counts(debate_id: str) -> dict[str, int]:
    """Get vote counts for a debate."""
    votes = _user_votes.get(debate_id, {})
    counts: dict[str, int] = {}
    for agent in votes.values():
        counts[agent] = counts.get(agent, 0) + 1
    return counts
