"""
Platform Configuration handler.

Serves runtime configuration for the frontend, eliminating the need
to rebuild when agents change or feature flags are toggled.

Endpoints:
    GET /api/v1/platform/config  - Full platform configuration
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.handlers.base import (
    HandlerResult,
    json_response,
)
from aragora.server.handlers.secure import SecureHandler

logger = logging.getLogger(__name__)


# Agent display names mapping (canonical source of truth for the frontend).
# Kept in sync with the frontend's AGENT_DISPLAY_NAMES in config.ts.
AGENT_DISPLAY_NAMES: dict[str, str] = {
    "grok": "Grok 4",
    "anthropic-api": "Opus 4.6",
    "openai-api": "GPT 5.2",
    "deepseek": "DeepSeek V3",
    "mistral": "Mistral Large 3",
    "gemini": "Gemini 3.1 Pro",
    "qwen": "Qwen 3.8 Max",
    "qwen-max": "Qwen 3.8 Max",
    "kimi": "Kimi K3",
    "kimi-thinking": "Kimi K2 Thinking",
    "llama": "Llama 3.3",
    "llama4-maverick": "Llama 4 Maverick",
    "llama4-scout": "Llama 4 Scout",
    "sonar": "Perplexity Sonar",
    "command-r": "Cohere Command R+",
    "jamba": "AI21 Jamba",
    # NOTE (frontier-model-refresh, 2026-09-05): "yi" is deliberately absent.
    # The YiAgent registration is gone (01.AI Yi Large is off the live
    # OpenRouter catalog), so offering it here let the UI present an agent
    # type the server now rejects at construction.
    "openrouter": "OpenRouter",
    "deepseek-r1": "DeepSeek V4 Pro",
    "ollama": "Ollama (Local)",
    "claude": "Claude",
    "codex": "Codex",
    "demo": "Demo",
}

# Default agents used in a standard debate.
DEFAULT_AGENTS = [
    "grok",
    "anthropic-api",
    "openai-api",
    "deepseek",
    "mistral",
    "gemini",
    "qwen",
    "kimi",
]

# Agents that support streaming responses.
STREAMING_CAPABLE_AGENTS = [
    "grok",
    "anthropic-api",
    "openai-api",
    "mistral",
]


class PlatformConfigHandler(SecureHandler):
    """Serves runtime platform configuration for the frontend.

    Returns agent lists, display names, default debate settings,
    feature flags, and version information so the frontend does not
    need to be rebuilt when these values change.
    """

    RESOURCE_TYPE = "platform_config"

    ROUTES = [
        "/api/v1/platform/config",
        "/api/platform/config",
    ]

    ROUTE_PREFIXES = [
        "/api/v1/platform/config",
        "/api/platform/config",
    ]

    def __init__(self, server_context: dict[str, Any]) -> None:
        super().__init__(server_context)

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can handle the given path."""
        if path in ("/api/v1/platform/config", "/api/platform/config"):
            return method == "GET"
        return False

    def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Handle GET /api/v1/platform/config."""
        if path not in ("/api/v1/platform/config", "/api/platform/config"):
            return None
        return self._get_platform_config()

    def _get_platform_config(self) -> HandlerResult:
        """Build and return the full platform configuration payload."""
        available_agents = self._collect_available_agents()
        display_names = self._collect_display_names(available_agents)
        features = self._collect_feature_flags()
        version = self._get_version()

        return json_response(
            {
                "data": {
                    "available_agents": available_agents,
                    "agent_display_names": display_names,
                    "default_agents": DEFAULT_AGENTS,
                    "streaming_capable_agents": STREAMING_CAPABLE_AGENTS,
                    "default_debate_config": {
                        "rounds": 9,
                        "max_rounds": 12,
                        "consensus_mode": "judge",
                    },
                    "features": features,
                    "version": version,
                }
            }
        )

    def _collect_available_agents(self) -> list[str]:
        """Collect the list of available agent type names from the registry.

        Falls back to the hardcoded DEFAULT_AGENTS if the registry
        cannot be loaded.
        """
        try:
            from aragora.agents.registry import AgentFactory, register_all_agents

            # Ensure agents are registered.
            if not AgentFactory.get_registered_types():
                register_all_agents()

            return sorted(AgentFactory.get_registered_types())
        except (ImportError, AttributeError, RuntimeError) as exc:
            logger.debug("Agent registry unavailable, using defaults: %s", exc)
            return sorted(DEFAULT_AGENTS)

    def _collect_display_names(self, available_agents: list[str]) -> dict[str, str]:
        """Build display-name mapping for all available agents.

        Uses the canonical AGENT_DISPLAY_NAMES dict, falling back to
        a title-cased version of the agent id for unknown agents.
        """
        names: dict[str, str] = {}
        for agent_id in available_agents:
            names[agent_id] = AGENT_DISPLAY_NAMES.get(
                agent_id,
                agent_id.replace("-", " ").replace("_", " ").title(),
            )
        # Also include any display names for agents not in the available list
        # (e.g., agents that are known but not currently registered).
        for agent_id, display_name in AGENT_DISPLAY_NAMES.items():
            if agent_id not in names:
                names[agent_id] = display_name
        return names

    def _collect_feature_flags(self) -> dict[str, bool]:
        """Collect feature flags from environment/config."""
        import os

        return {
            "streaming": os.environ.get("NEXT_PUBLIC_ENABLE_STREAMING", "true").lower() != "false",
            "audience": os.environ.get("NEXT_PUBLIC_ENABLE_AUDIENCE", "true").lower() != "false",
            "spectate": True,
            "receipts": True,
            "knowledge_mound": True,
            "pulse": True,
        }

    def _get_version(self) -> str:
        """Get the current Aragora version string."""
        try:
            import aragora

            return getattr(aragora, "__version__", "unknown")
        except (ImportError, AttributeError):
            return "unknown"
