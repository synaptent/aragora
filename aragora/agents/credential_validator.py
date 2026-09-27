"""
Credential validation for agents.

Provides pre-creation validation to check which agents have valid API keys
configured, enabling auto-trim of unavailable agents before debate starts.

Usage:
    from aragora.agents.credential_validator import (
        validate_agent_credentials,
        filter_available_agents,
        get_agent_credential_status,
    )

    # Check if a specific agent type has credentials
    is_valid = validate_agent_credentials("anthropic-api")

    # Filter a list of agent specs to only those with valid credentials
    available_specs = filter_available_agents(specs)

    # Get full status for all known agent types
    status = get_agent_credential_status()
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.agents.spec import AgentSpec

logger = logging.getLogger(__name__)

# Mapping of agent types to their required environment variables
# Uses the same names as secrets.py MANAGED_SECRETS
AGENT_CREDENTIAL_MAP: dict[str, list[str]] = {
    # Anthropic
    "anthropic-api": ["ANTHROPIC_API_KEY"],
    "claude": ["ANTHROPIC_API_KEY"],  # CLI uses same key
    # OpenAI
    "openai-api": ["OPENAI_API_KEY"],
    "codex": ["OPENAI_API_KEY"],  # CLI uses same key
    "gpt": ["OPENAI_API_KEY"],
    # Google
    "gemini": ["GEMINI_API_KEY"],
    "gemini-api": ["GEMINI_API_KEY"],
    # xAI
    "grok": ["XAI_API_KEY"],
    "grok-api": ["XAI_API_KEY"],
    # Mistral
    "mistral-api": ["MISTRAL_API_KEY"],
    "codestral": ["MISTRAL_API_KEY"],
    # OpenRouter (fallback for many models)
    "openrouter": ["OPENROUTER_API_KEY"],
    "deepseek": ["OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"],  # Direct or via OpenRouter
    "deepseek-v4-pro": ["OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"],
    "deepseek-v3": ["OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"],
    "deepseek-reasoner": ["OPENROUTER_API_KEY", "DEEPSEEK_API_KEY"],
    "llama": ["OPENROUTER_API_KEY"],
    "llama4-maverick": ["OPENROUTER_API_KEY"],
    "llama4-scout": ["OPENROUTER_API_KEY"],
    "qwen": ["OPENROUTER_API_KEY"],
    "qwen-max": ["OPENROUTER_API_KEY"],
    "yi": ["OPENROUTER_API_KEY"],
    "kimi": ["OPENROUTER_API_KEY"],
    "kimi-k3": ["OPENROUTER_API_KEY"],
    "kimi-k2": ["OPENROUTER_API_KEY"],
    "kimi-k2.6": ["OPENROUTER_API_KEY"],
    "kimi-thinking": ["OPENROUTER_API_KEY"],
    "kimi-legacy": ["KIMI_API_KEY"],
    "sonar": ["OPENROUTER_API_KEY"],
    "command-r": ["OPENROUTER_API_KEY"],
    "jamba": ["OPENROUTER_API_KEY"],
    "mistral": ["OPENROUTER_API_KEY", "MISTRAL_API_KEY"],  # Via OpenRouter or direct
    # Local models (no credentials required)
    "ollama": [],
    "lm-studio": [],
    "local": [],
    # Demo/test agents
    "demo": [],
    "mock": [],
}

FALLBACK_ELIGIBLE_PROVIDERS = frozenset(
    {
        "anthropic-api",
        "openai-api",
        "gpt",
        "codex",
        "gemini",
        "gemini-api",
        "grok",
        "grok-api",
        "mistral-api",
        "codestral",
    }
)


def _openrouter_fallback_available() -> bool:
    """Check if OpenRouter fallback is enabled and configured."""
    try:
        from aragora.agents.fallback import get_default_fallback_enabled
    except ImportError:
        return False

    if not get_default_fallback_enabled():
        return False

    return bool(_get_secret("OPENROUTER_API_KEY"))


@dataclass
class CredentialStatus:
    """Status of credentials for an agent type."""

    agent_type: str
    is_available: bool
    required_vars: list[str]
    missing_vars: list[str]
    available_via: str | None = None  # Which key makes it available
    config_present: bool = False
    live_ready: bool = False
    status: str = "missing_config"
    next_action: str | None = None
    next_actions: list[str] = field(default_factory=list)


def _get_secret(name: str) -> str | None:
    """Get a secret from environment or AWS Secrets Manager.

    Uses the central secrets module for unified access.
    """
    try:
        from aragora.config.secrets import get_secret

        return get_secret(name)
    except ImportError:
        # Fallback to environment only
        return os.environ.get(name)


def validate_agent_credentials(agent_type: str) -> bool:
    """Check if an agent type has valid credentials configured.

    Args:
        agent_type: The agent type identifier (e.g., "anthropic-api", "gemini")

    Returns:
        True if credentials are available, False otherwise
    """
    return get_credential_status(agent_type).is_available


def get_credential_status(agent_type: str) -> CredentialStatus:
    """Get detailed credential status for an agent type.

    Args:
        agent_type: The agent type identifier

    Returns:
        CredentialStatus with availability details
    """
    required_vars = AGENT_CREDENTIAL_MAP.get(agent_type, [])

    if not required_vars:
        return CredentialStatus(
            agent_type=agent_type,
            is_available=True,
            required_vars=[],
            missing_vars=[],
            available_via="no_credentials_required",
            config_present=True,
            live_ready=True,
            status="ready",
        )

    missing = []
    available_via = None

    for var in required_vars:
        value = _get_secret(var)
        if value:
            available_via = var
            break
        else:
            missing.append(var)

    is_available = available_via is not None

    if not is_available and agent_type in FALLBACK_ELIGIBLE_PROVIDERS:
        if _openrouter_fallback_available():
            return CredentialStatus(
                agent_type=agent_type,
                is_available=True,
                required_vars=required_vars,
                missing_vars=[],
                available_via="OPENROUTER_API_KEY (fallback)",
                config_present=True,
                live_ready=False,
                status="configured",
                next_action="Verify provider connectivity before treating it as live-ready.",
                next_actions=[
                    "Run a provider preflight or quickstart live check before routing live debates.",
                    "If the provider is unreachable, keep the path blocked instead of silently simulating it.",
                ],
            )

    return CredentialStatus(
        agent_type=agent_type,
        is_available=is_available,
        required_vars=required_vars,
        missing_vars=missing if not is_available else [],
        available_via=available_via,
        config_present=is_available,
        live_ready=False,
        status="configured" if is_available else "missing_config",
        next_action=(
            "Verify provider connectivity before treating it as live-ready."
            if is_available
            else f"Set one of: {', '.join(required_vars)}"
        ),
        next_actions=(
            [
                "Run a provider preflight or quickstart live check before routing live debates.",
                "If the provider is unreachable, keep the path blocked instead of silently simulating it.",
            ]
            if is_available
            else [
                f"Export one of the required credentials: {', '.join(required_vars)}.",
                "Retry the live preflight after credentials are configured.",
            ]
        ),
    )


def filter_available_agents(
    specs: list[AgentSpec],
    log_filtered: bool = True,
    min_agents: int = 2,
) -> tuple[list[AgentSpec], list[tuple[str, str]]]:
    """Filter agent specs to only those with valid credentials.

    Args:
        specs: List of agent specifications to filter
        log_filtered: Whether to log which agents were filtered out
        min_agents: Minimum number of agents required (raises ValueError if not met)

    Returns:
        Tuple of (available_specs, filtered_specs) where filtered_specs is
        list of (agent_type, reason) tuples

    Raises:
        ValueError: If fewer than min_agents would remain after filtering
    """
    available = []
    filtered = []

    for spec in specs:
        status = get_credential_status(spec.provider)

        if status.is_available:
            available.append(spec)
        else:
            reason = f"Missing credentials: {', '.join(status.missing_vars)}"
            filtered.append((spec.provider, reason))
            if log_filtered:
                logger.warning(
                    "Agent '%s' unavailable: %s. Set one of: %s",
                    spec.provider,
                    reason,
                    ", ".join(status.required_vars),
                )

    if len(available) < min_agents:
        available_names = [s.provider for s in available]
        filtered_names = [f[0] for f in filtered]
        raise ValueError(
            f"Only {len(available)} agents have valid credentials "
            f"(need at least {min_agents}). "
            f"Available: {', '.join(available_names) or 'none'}. "
            f"Missing credentials: {', '.join(filtered_names)}."
        )

    return available, filtered


def get_agent_credential_status() -> dict[str, CredentialStatus]:
    """Get credential status for all known agent types.

    Returns:
        Dict mapping agent type to CredentialStatus
    """
    return {agent_type: get_credential_status(agent_type) for agent_type in AGENT_CREDENTIAL_MAP}


def get_available_agent_types() -> list[str]:
    """Get list of agent types with valid credentials.

    Returns:
        List of agent type names that have valid credentials
    """
    return [
        agent_type for agent_type in AGENT_CREDENTIAL_MAP if validate_agent_credentials(agent_type)
    ]


def get_missing_credentials_summary() -> dict[str, list[str]]:
    """Get summary of missing credentials by agent type.

    Returns:
        Dict mapping agent type to list of missing environment variables
    """
    summary = {}
    for agent_type in AGENT_CREDENTIAL_MAP:
        status = get_credential_status(agent_type)
        if not status.is_available and status.missing_vars:
            summary[agent_type] = status.missing_vars
    return summary


def log_credential_status() -> None:
    """Log credential status for all agent types at startup."""
    available = []
    missing = []

    for agent_type in sorted(AGENT_CREDENTIAL_MAP.keys()):
        status = get_credential_status(agent_type)
        if status.is_available:
            if status.available_via:
                available.append(f"{agent_type} (via {status.available_via})")
            else:
                available.append(agent_type)
        else:
            missing.append(f"{agent_type} (needs: {', '.join(status.required_vars)})")

    if available:
        logger.info("Available agents (%s): %s", len(available), ", ".join(available))
    if missing:
        logger.warning("Unavailable agents (%s): %s", len(missing), ", ".join(missing))
