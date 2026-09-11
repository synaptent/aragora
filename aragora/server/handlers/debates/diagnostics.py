"""
Debate diagnostics handler mixin.

Provides a diagnostics endpoint for SME self-service debugging of debates.
Helps users understand why a debate failed, timed out, or had issues.

Endpoint:
- GET /api/v1/debates/{id}/diagnostics - Get diagnostic report for a debate
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from aragora.models.catalog import CATALOG

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..openapi_decorator import api_endpoint
from .response_formatting import normalize_status

logger = logging.getLogger(__name__)

# Known provider mappings for agent names. Hand-written HISTORICAL rows
# (kept verbatim, and they WIN a key collision: their POSITION drives
# ``_infer_provider``'s prefix fallback, so "claude" must keep coming before
# any full Claude model id) plus one generated row per spelling of every
# active catalog model, so a debate that names an agent by its current
# frontier id no longer reports "unknown" (2026-09-04 controller ruling,
# wave 3).
_LEGACY_AGENT_PROVIDER_MAP: dict[str, str] = {
    "claude": "anthropic",
    "claude-sonnet": "anthropic",
    "claude-opus": "anthropic",
    "claude-haiku": "anthropic",
    "gpt-4": "openai",
    "gpt-4.1": "openai",
    "gpt-5.4": "openai",
    "gpt-4o": "openai",
    "gpt-4o-mini": "openai",
    "gpt-4.1-mini": "openai",
    "gpt-3.5-turbo": "openai",
    "o1": "openai",
    "o1-mini": "openai",
    "o3-mini": "openai",
    "gemini": "google",
    "gemini-pro": "google",
    "gemini-flash": "google",
    "gemini-3.1-pro": "google",
    "gemini-3-flash": "google",
    "grok": "xai",
    "grok-2": "xai",
    "grok-4": "xai",
    "mistral": "mistral",
    "mistral-large": "mistral",
    "mistral-large-3": "mistral",
    "codestral": "mistral",
    "deepseek": "openrouter",
    "deepseek-r1": "openrouter",
    "deepseek-v3": "openrouter",
    "llama": "openrouter",
    "llama4-maverick": "openrouter",
    "llama4-scout": "openrouter",
    "qwen": "openrouter",
    # NOTE (frontier-model-refresh, 2026-09-05): "qwen-3.5" and "yi" are
    # deliberately absent. Both registrations were removed with their models
    # (Qwen3.5 Plus and Yi Large are off the live OpenRouter catalog), so a
    # diagnostics row for either described an agent type the server rejects.
    "kimi": "openrouter",
}

# API key environment variable names per provider
_PROVIDER_API_KEY_MAP: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "google": "GEMINI_API_KEY",
    "xai": "XAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def _catalog_provider_rows() -> dict[str, str]:
    """Spelling -> provider for every spelling of every ACTIVE catalog row.

    The value this map exists to produce is a credential hint, so a catalog
    ``provider`` Aragora has no direct credential for (``moonshot``,
    ``perplexity``, ``cohere``, ``ai21`` -- families it reaches only through
    OpenRouter) is reported as ``openrouter``. That is exactly the
    convention the hand-written rows above already use for deepseek, llama,
    qwen and kimi, and it keeps ``_PROVIDER_API_KEY_MAP`` able to name a
    real environment variable instead of falling through to the generic
    "check agent configuration" message.
    """
    return {
        spelling: (spec.provider if spec.provider in _PROVIDER_API_KEY_MAP else "openrouter")
        for spec in CATALOG.values()
        if not spec.retired
        for spelling in spec.all_ids()
    }


_AGENT_PROVIDER_MAP: dict[str, str] = {
    **_LEGACY_AGENT_PROVIDER_MAP,
    **{k: v for k, v in _catalog_provider_rows().items() if k not in _LEGACY_AGENT_PROVIDER_MAP},
}


def _infer_provider(agent_name: str) -> str:
    """Infer provider from agent name.

    Args:
        agent_name: The agent/model name.

    Returns:
        Provider string or "unknown".
    """
    name_lower = agent_name.lower()
    # Direct match
    if name_lower in _AGENT_PROVIDER_MAP:
        return _AGENT_PROVIDER_MAP[name_lower]
    # Prefix match
    for prefix, provider in _AGENT_PROVIDER_MAP.items():
        if name_lower.startswith(prefix):
            return provider
    return "unknown"


def _extract_agent_diagnostics(
    debate: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract per-agent diagnostic information from a debate record.

    Looks at messages, proposals, critiques, and agent_failures to build
    a per-agent participation report.

    Args:
        debate: The stored debate record dict.

    Returns:
        List of agent diagnostic dicts.
    """
    agents_info: dict[str, dict[str, Any]] = {}

    # Get participant list
    participants = debate.get("participants") or debate.get("agents") or []
    if isinstance(participants, str):
        participants = [p.strip() for p in participants.split(",") if p.strip()]

    # Initialize each agent
    for agent_name in participants:
        agents_info[agent_name] = {
            "name": agent_name,
            "provider": _infer_provider(agent_name),
            "status": "success",
            "rounds_participated": 0,
            "proposals": 0,
            "critiques": 0,
            "error": None,
        }

    # Count from messages
    messages = debate.get("messages") or []
    for msg in messages:
        agent = None
        if isinstance(msg, dict):
            agent = msg.get("agent") or msg.get("name")
        elif hasattr(msg, "agent"):
            agent = getattr(msg, "agent", None) or getattr(msg, "name", None)

        if not agent:
            continue

        if agent not in agents_info:
            agents_info[agent] = {
                "name": agent,
                "provider": _infer_provider(agent),
                "status": "success",
                "rounds_participated": 0,
                "proposals": 0,
                "critiques": 0,
                "error": None,
            }

        info = agents_info[agent]
        role = msg.get("role", "") if isinstance(msg, dict) else getattr(msg, "role", "")
        round_num = msg.get("round", 0) if isinstance(msg, dict) else getattr(msg, "round", 0)

        if round_num > info["rounds_participated"]:
            info["rounds_participated"] = round_num

        if role in ("proposer", "proposal"):
            info["proposals"] += 1
        elif role in ("critic", "critique"):
            info["critiques"] += 1

    # Check proposals dict
    proposals = debate.get("proposals") or {}
    if isinstance(proposals, dict):
        for agent_name in proposals:
            if agent_name in agents_info:
                # Only count if not already counted from messages
                if agents_info[agent_name]["proposals"] == 0:
                    agents_info[agent_name]["proposals"] = 1

    # Check critiques list
    critiques = debate.get("critiques") or []
    for critique in critiques:
        agent = None
        if isinstance(critique, dict):
            agent = critique.get("agent") or critique.get("critic")
        elif hasattr(critique, "agent"):
            agent = getattr(critique, "agent", None)

        if agent and agent in agents_info:
            # Only add if not already counted from messages
            pass  # Already counted from messages above

    # Mark failed agents from agent_failures
    agent_failures = debate.get("agent_failures") or {}
    if isinstance(agent_failures, dict):
        for agent_name, failures in agent_failures.items():
            if agent_name not in agents_info:
                agents_info[agent_name] = {
                    "name": agent_name,
                    "provider": _infer_provider(agent_name),
                    "status": "failed",
                    "rounds_participated": 0,
                    "proposals": 0,
                    "critiques": 0,
                    "error": None,
                }

            info = agents_info[agent_name]
            info["status"] = "failed"
            if isinstance(failures, list) and failures:
                last_failure = failures[-1]
                if isinstance(last_failure, dict):
                    info["error"] = last_failure.get("error") or last_failure.get(
                        "message", "Agent failed"
                    )
                elif isinstance(last_failure, str):
                    info["error"] = last_failure
                else:
                    info["error"] = "Agent failed"
            elif isinstance(failures, str):
                info["error"] = failures

    # Detect agents that participated zero rounds as timeout/failed
    for info in agents_info.values():
        if info["rounds_participated"] == 0 and info["proposals"] == 0 and info["critiques"] == 0:
            if info["status"] == "success":
                info["status"] = "timeout"

    return list(agents_info.values())


def _extract_consensus_info(debate: dict[str, Any]) -> dict[str, Any]:
    """Extract consensus information from a debate record.

    Args:
        debate: The stored debate record dict.

    Returns:
        Consensus info dict with reached, method, and confidence.
    """
    consensus_reached = debate.get("consensus_reached", False)
    consensus_method = debate.get("consensus_method") or debate.get("consensus", "majority")
    confidence = debate.get("confidence", 0.0)

    # Try to get from metadata
    metadata = debate.get("metadata") or {}
    if isinstance(metadata, dict):
        if "consensus_method" in metadata:
            consensus_method = metadata["consensus_method"]
        if "confidence" in metadata and not confidence:
            confidence = metadata["confidence"]

    return {
        "reached": bool(consensus_reached),
        "method": str(consensus_method),
        "confidence": round(float(confidence), 4) if confidence else 0.0,
    }


def _generate_suggestions(
    debate: dict[str, Any],
    agents_diagnostics: list[dict[str, Any]],
    debate_status: str,
) -> list[str]:
    """Generate actionable suggestions based on debate diagnostics.

    Args:
        debate: The stored debate record dict.
        agents_diagnostics: Per-agent diagnostic data.
        debate_status: Normalized debate status.

    Returns:
        List of human-readable suggestion strings.
    """
    suggestions: list[str] = []

    # Check for failed agents
    failed_agents = [a for a in agents_diagnostics if a["status"] == "failed"]
    timed_out_agents = [a for a in agents_diagnostics if a["status"] == "timeout"]

    for agent in failed_agents:
        error = agent.get("error", "")
        provider = agent["provider"]
        api_key_env = _PROVIDER_API_KEY_MAP.get(provider, "")

        if error and (
            "key" in error.lower() or "auth" in error.lower() or "quota" in error.lower()
        ):
            if api_key_env:
                suggestions.append(f"Agent {agent['name']} failed - check your {api_key_env}")
            else:
                suggestions.append(
                    f"Agent {agent['name']} failed with authentication error - verify API credentials"
                )
        elif error and "timeout" in error.lower():
            suggestions.append(
                f"Agent {agent['name']} timed out - consider increasing timeout or using a faster model"
            )
        elif error and ("rate" in error.lower() or "429" in error.lower()):
            suggestions.append(
                f"Agent {agent['name']} hit rate limits - wait and retry, or add OPENROUTER_API_KEY as fallback"
            )
        else:
            if api_key_env:
                suggestions.append(
                    f"Agent {agent['name']} failed - check your {api_key_env} and provider status"
                )
            else:
                suggestions.append(f"Agent {agent['name']} failed - check provider connectivity")

    for agent in timed_out_agents:
        provider = agent["provider"]
        api_key_env = _PROVIDER_API_KEY_MAP.get(provider, "")
        if api_key_env:
            suggestions.append(
                f"Agent {agent['name']} did not participate - verify {api_key_env} is set and valid"
            )
        else:
            suggestions.append(
                f"Agent {agent['name']} did not participate - check agent configuration"
            )

    # Check for no consensus
    consensus_reached = debate.get("consensus_reached", False)
    if not consensus_reached and debate_status == "completed":
        rounds_used = debate.get("rounds_used") or debate.get("rounds", 0)
        suggestions.append(
            f"No consensus reached after {rounds_used} rounds - consider increasing round count or reducing agent count"
        )

    # Check for overall failure
    if debate_status == "failed":
        error = debate.get("error") or debate.get("failure_reason", "")
        if error:
            suggestions.append(f"Debate failed: {error}")
        else:
            suggestions.append(
                "Debate failed without a specific error - check server logs for details"
            )

    # Suggest fallback provider if any agent failed
    if failed_agents and not any("OPENROUTER_API_KEY" in s for s in suggestions):
        suggestions.append("Consider adding OPENROUTER_API_KEY as fallback for failed providers")

    # If all agents timed out, suggest fewer agents
    total_agents = len(agents_diagnostics)
    if total_agents > 0 and len(timed_out_agents) == total_agents:
        suggestions.append(
            "All agents failed to participate - verify API keys and network connectivity"
        )

    return suggestions


class _DebatesHandlerProtocol(Protocol):
    """Protocol defining the interface expected by DiagnosticsMixin.

    This protocol enables proper type checking for mixin classes that
    expect to be mixed into a class providing these methods/attributes.
    """

    ctx: dict[str, Any]

    def get_storage(self) -> Any | None:
        """Get debate storage instance."""
        ...


class DiagnosticsMixin:
    """Mixin providing debate diagnostics for DebatesHandler.

    Enables SME self-service debugging by providing a comprehensive
    diagnostic report for any debate, including per-agent status,
    consensus info, and actionable suggestions.
    """

    @api_endpoint(
        method="GET",
        path="/api/v1/debates/{id}/diagnostics",
        summary="Get debate diagnostics",
        description=(
            "Get a diagnostic report for a debate including per-agent status, "
            "consensus info, receipt generation status, and actionable suggestions "
            "for resolving issues. Designed for SME self-service debugging."
        ),
        tags=["Debates", "Diagnostics"],
        parameters=[
            {
                "name": "id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
                "description": "The debate ID to diagnose",
            },
        ],
        responses={
            "200": {
                "description": "Diagnostic report returned",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "debate_id": {"type": "string"},
                                "status": {"type": "string"},
                                "duration_seconds": {"type": "number"},
                                "agents": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "name": {"type": "string"},
                                            "provider": {"type": "string"},
                                            "status": {"type": "string"},
                                            "rounds_participated": {"type": "integer"},
                                            "proposals": {"type": "integer"},
                                            "critiques": {"type": "integer"},
                                            "error": {
                                                "type": "string",
                                                "nullable": True,
                                            },
                                        },
                                    },
                                },
                                "consensus": {
                                    "type": "object",
                                    "properties": {
                                        "reached": {"type": "boolean"},
                                        "method": {"type": "string"},
                                        "confidence": {"type": "number"},
                                    },
                                },
                                "receipt_generated": {"type": "boolean"},
                                "suggestions": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                        },
                    },
                },
            },
            "404": {"description": "Debate not found"},
            "500": {"description": "Internal server error"},
        },
    )
    @handle_errors("debate diagnostics")
    def _get_diagnostics(self: _DebatesHandlerProtocol, debate_id: str) -> HandlerResult:
        """Get diagnostic report for a debate.

        Provides comprehensive debugging information including:
        - Overall debate status and duration
        - Per-agent participation, success/failure status, and errors
        - Consensus information (reached, method, confidence)
        - Whether a receipt was generated
        - Actionable suggestions for resolving issues

        Args:
            debate_id: The ID of the debate to diagnose.

        Returns:
            HandlerResult with diagnostic JSON report.
        """
        storage = self.get_storage()
        if not storage:
            return error_response("Storage not available", 503)

        debate = storage.get_debate(debate_id)
        if not debate:
            return error_response(f"Debate not found: {debate_id}", 404)

        # Extract status
        raw_status = debate.get("status", "unknown")
        status = normalize_status(raw_status)

        # Extract duration
        duration = debate.get("duration_seconds", 0.0)
        if not duration:
            # Try to compute from timestamps
            metadata = debate.get("metadata") or {}
            if isinstance(metadata, dict):
                duration = metadata.get("duration_seconds", 0.0)

        # Extract agent diagnostics
        agents_diagnostics = _extract_agent_diagnostics(debate)

        # Extract consensus info
        consensus_info = _extract_consensus_info(debate)

        # Check receipt generation
        receipt_generated = False
        metadata = debate.get("metadata") or {}
        if isinstance(metadata, dict):
            receipt_generated = bool(
                metadata.get("receipt_id")
                or metadata.get("receipt_generated")
                or metadata.get("gauntlet_receipt_id")
            )
        # Also check top-level receipt fields
        if not receipt_generated:
            receipt_generated = bool(debate.get("receipt_id") or debate.get("receipt"))

        # Generate suggestions
        suggestions = _generate_suggestions(debate, agents_diagnostics, status)

        response = {
            "debate_id": debate_id,
            "status": status,
            "duration_seconds": round(float(duration), 2) if duration else 0.0,
            "agents": agents_diagnostics,
            "consensus": consensus_info,
            "receipt_generated": receipt_generated,
            "suggestions": suggestions,
        }

        return json_response(response)


__all__ = ["DiagnosticsMixin"]
