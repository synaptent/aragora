"""
Agent Factory for the Control Plane.

Bridges the gap between AgentInfo (metadata) from the AgentRegistry and
concrete Agent instances needed by the Arena debate engine.

The factory:
1. Maps AgentInfo.provider to agent type names in aragora.agents.registry
2. Loads credentials from environment variables / secrets
3. Creates Agent instances via the existing AgentRegistry.create() factory
4. Validates credentials before attempting creation
5. Falls back to demo agents for testing when credentials are missing

Usage:
    from aragora.control_plane.agent_factory import AgentFactory, get_agent_factory

    factory = get_agent_factory()

    # Single agent
    result = factory.create_from_info(agent_info)
    if result.success:
        agent = result.agent

    # Batch creation
    agents = await factory.create_agents(agent_infos)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast
from collections.abc import Sequence

if TYPE_CHECKING:
    from aragora.control_plane.registry import AgentInfo
    from aragora.core import Agent

logger = logging.getLogger(__name__)


# Provider name normalization: maps AgentInfo.provider values to
# aragora.agents.registry type names used by AgentRegistry.create()
PROVIDER_TO_AGENT_TYPE: dict[str, str] = {
    # Direct API providers
    "anthropic": "anthropic-api",
    "anthropic-api": "anthropic-api",
    "openai": "openai-api",
    "openai-api": "openai-api",
    "google": "gemini",
    "gemini": "gemini",
    "gemini-api": "gemini",
    "xai": "grok",
    "grok": "grok",
    "grok-api": "grok",
    "mistral": "mistral-api",
    "mistral-api": "mistral-api",
    "codestral": "mistral-api",
    # OpenRouter-based providers
    "deepseek": "deepseek",
    "deepseek-v4-pro": "deepseek",
    "deepseek-v3": "deepseek",
    "meta": "llama",
    "llama": "llama",
    "qwen": "qwen",
    # NOTE (frontier-model-refresh, 2026-09-05): no "yi" row. The "yi"
    # agent registration, allowlist entry and credential row were removed
    # with the Yi Large retirement (no catalog row), so mapping the
    # provider here would resolve cleanly and then fail deep inside
    # create_agent() with an unknown-agent-type error. Leaving it out makes
    # resolve_agent_type() return None and create_from_info() report
    # "Cannot resolve provider 'yi' to agent type" at the boundary instead.
    "kimi": "kimi",
    "openrouter": "openrouter",
    # CLI-based
    "claude-cli": "claude",
    "codex-cli": "codex",
    "claude": "claude",
    "codex": "codex",
    # Local
    "ollama": "ollama",
    "lm-studio": "lm-studio",
    "local": "local",
    # Demo/test
    "demo": "demo",
    "mock": "demo",
    "test": "demo",
}


@dataclass
class AgentCreationResult:
    """Result of attempting to create an agent from AgentInfo."""

    agent: Any | None = None  # Agent instance if successful
    agent_info: Any | None = None  # The AgentInfo that was used
    success: bool = False
    error: str | None = None
    credentials_missing: bool = False


@dataclass
class AgentFactoryConfig:
    """Configuration for the AgentFactory."""

    # If True, fall back to demo agents when credentials are missing
    fallback_to_demo: bool = False
    # Default role for created agents
    default_role: str = "proposer"
    # Whether to validate credentials before attempting creation
    validate_credentials: bool = True
    # Custom provider-to-type mapping overrides
    provider_overrides: dict[str, str] = field(default_factory=dict)


class AgentFactory:
    """
    Factory that converts AgentInfo metadata into concrete Agent instances.

    This bridges the Control Plane's AgentRegistry (which tracks agent metadata
    like provider, model, capabilities) with the debate engine's Agent ABC
    (which requires generate(), critique(), vote() methods).

    Usage:
        factory = AgentFactory()

        # Single agent
        result = factory.create_from_info(agent_info)
        if result.success:
            agent = result.agent

        # Batch creation
        agents = await factory.create_agents(agent_infos)
    """

    def __init__(self, config: AgentFactoryConfig | None = None):
        self._config = config or AgentFactoryConfig()
        self._provider_map = {
            **PROVIDER_TO_AGENT_TYPE,
            **self._config.provider_overrides,
        }

    def resolve_agent_type(self, agent_info: AgentInfo) -> str | None:
        """
        Resolve AgentInfo to an agent registry type name.

        Checks, in order:
        1. metadata.agent_type (explicit override in agent metadata)
        2. provider field mapped via PROVIDER_TO_AGENT_TYPE
        3. model field heuristic (e.g., "claude-3-opus" -> "anthropic-api")

        Args:
            agent_info: Agent metadata from the control plane registry

        Returns:
            Agent type string for AgentRegistry.create(), or None if unknown
        """
        # 1. Check metadata for explicit agent_type
        explicit_type = agent_info.metadata.get("agent_type")
        if explicit_type and explicit_type in self._provider_map.values():
            return explicit_type

        # 2. Map provider name
        provider_lower = agent_info.provider.lower()
        if provider_lower in self._provider_map:
            return self._provider_map[provider_lower]

        # 3. Heuristic from model name
        model_lower = agent_info.model.lower() if agent_info.model else ""
        if "claude" in model_lower or "anthropic" in model_lower:
            return "anthropic-api"
        elif "gpt" in model_lower or "o1" in model_lower or "o3" in model_lower:
            return "openai-api"
        elif "gemini" in model_lower:
            return "gemini"
        elif "grok" in model_lower:
            return "grok"
        elif "mistral" in model_lower or "codestral" in model_lower:
            return "mistral-api"
        elif "deepseek" in model_lower:
            return "deepseek"
        elif "llama" in model_lower:
            return "llama"
        elif "qwen" in model_lower:
            return "qwen"

        logger.warning(
            "agent_type_unresolved",
            extra={
                "agent_id": agent_info.agent_id,
                "provider": agent_info.provider,
                "model": agent_info.model,
            },
        )
        return None

    def create_from_info(
        self,
        agent_info: AgentInfo,
        role: str | None = None,
    ) -> AgentCreationResult:
        """
        Create a concrete Agent instance from AgentInfo metadata.

        Args:
            agent_info: Agent metadata from the control plane registry
            role: Override role (default from config)

        Returns:
            AgentCreationResult with agent or error details
        """
        agent_type = self.resolve_agent_type(agent_info)

        if agent_type is None:
            if self._config.fallback_to_demo:
                agent_type = "demo"
                logger.info(
                    "agent_factory_fallback_to_demo",
                    extra={
                        "agent_id": agent_info.agent_id,
                        "provider": agent_info.provider,
                    },
                )
            else:
                return AgentCreationResult(
                    agent_info=agent_info,
                    error=f"Cannot resolve provider '{agent_info.provider}' to agent type",
                )

        # Validate credentials if enabled
        if self._config.validate_credentials and agent_type != "demo":
            try:
                from aragora.agents.credential_validator import validate_agent_credentials

                if not validate_agent_credentials(agent_type):
                    if self._config.fallback_to_demo:
                        logger.warning(
                            "agent_factory_credentials_missing_fallback",
                            extra={
                                "agent_id": agent_info.agent_id,
                                "agent_type": agent_type,
                            },
                        )
                        agent_type = "demo"
                    else:
                        return AgentCreationResult(
                            agent_info=agent_info,
                            error=f"Credentials missing for agent type '{agent_type}'",
                            credentials_missing=True,
                        )
            except ImportError:
                logger.debug(
                    "credential_validator_unavailable",
                    extra={"agent_id": agent_info.agent_id, "agent_type": agent_type},
                )

        # Load API key from environment
        api_key = self._get_api_key(agent_type)

        # Create via existing AgentRegistry
        try:
            from aragora.agents.base import AgentType, create_agent

            agent = create_agent(
                model_type=cast(AgentType, agent_type),
                name=agent_info.agent_id,
                role=role or self._config.default_role,
                model=agent_info.model if agent_info.model != "unknown" else None,
                api_key=api_key,
            )

            logger.info(
                "agent_factory_created",
                extra={
                    "agent_id": agent_info.agent_id,
                    "agent_type": agent_type,
                    "model": agent_info.model,
                    "provider": agent_info.provider,
                },
            )

            return AgentCreationResult(
                agent=agent,
                agent_info=agent_info,
                success=True,
            )

        except (ImportError, ValueError, TypeError, RuntimeError, AttributeError, OSError) as e:
            logger.error(
                "agent_factory_creation_failed",
                extra={
                    "agent_id": agent_info.agent_id,
                    "agent_type": agent_type,
                    "error": str(e),
                },
            )
            return AgentCreationResult(
                agent_info=agent_info,
                error="Failed to create agent",
            )

    async def create_agents(
        self,
        agent_infos: Sequence[AgentInfo],
        role: str | None = None,
        min_agents: int = 0,
    ) -> list[Agent]:
        """
        Create multiple Agent instances from AgentInfo list.

        Skips agents that fail to create (missing credentials, unknown provider).

        Args:
            agent_infos: List of AgentInfo metadata
            role: Override role for all agents
            min_agents: Minimum number of agents required (raises if not met)

        Returns:
            List of successfully created Agent instances

        Raises:
            RuntimeError: If fewer than min_agents could be created
        """
        agents: list[Agent] = []
        errors: list[tuple[str, str | None]] = []

        for info in agent_infos:
            result = self.create_from_info(info, role=role)
            if result.success and result.agent:
                agents.append(result.agent)
            else:
                errors.append((info.agent_id, result.error))

        if errors:
            logger.warning(
                "agent_factory_partial_creation",
                extra={
                    "agents_created": len(agents),
                    "agents_failed": len(errors),
                    "creation_errors": errors,
                },
            )

        if len(agents) < min_agents:
            raise RuntimeError(
                f"Only {len(agents)} agents created (need {min_agents}). Failures: {errors}"
            )

        return agents

    def _get_api_key(self, agent_type: str) -> str | None:
        """Load API key for an agent type from environment/secrets."""
        try:
            from aragora.agents.credential_validator import AGENT_CREDENTIAL_MAP
        except ImportError:
            return None

        required_vars = AGENT_CREDENTIAL_MAP.get(agent_type, [])
        if not required_vars:
            return None

        # Try to get secret from config.secrets module first (supports AWS Secrets Manager)
        try:
            from aragora.config.secrets import get_secret

            for var in required_vars:
                value = get_secret(var)
                if value:
                    return value
        except ImportError:
            logger.debug("secrets_module_unavailable", extra={"agent_type": agent_type})

        # Fallback to environment variables
        import os

        for var in required_vars:
            value = os.environ.get(var)
            if value:
                return value

        return None


# Module-level singleton
_agent_factory: AgentFactory | None = None


def get_agent_factory(config: AgentFactoryConfig | None = None) -> AgentFactory:
    """Get or create the global AgentFactory singleton."""
    global _agent_factory
    if _agent_factory is None:
        _agent_factory = AgentFactory(config)
    return _agent_factory


def reset_agent_factory() -> None:
    """Reset the singleton (for testing)."""
    global _agent_factory
    _agent_factory = None
