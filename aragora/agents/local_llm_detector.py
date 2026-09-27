"""
Local LLM Detector - Discovers running local LLM servers.

Detects:
- Ollama (http://localhost:11434)
- LM Studio (http://localhost:1234)
- Other OpenAI-compatible servers

Use this to automatically discover available local models
for privacy-first deployments.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import cast

import httpx

from aragora.observability.http_client_pool import get_http_pool

logger = logging.getLogger(__name__)


@dataclass
class LocalLLMServer:
    """Information about a detected local LLM server."""

    name: str  # "ollama", "lm-studio", "openai-compatible"
    base_url: str
    available: bool
    models: list[str] = field(default_factory=list)
    default_model: str | None = None
    version: str | None = None


@dataclass
class LocalLLMStatus:
    """Overall status of local LLM availability."""

    servers: list[LocalLLMServer] = field(default_factory=list)
    total_models: int = 0
    recommended_server: str | None = None
    recommended_model: str | None = None

    @property
    def any_available(self) -> bool:
        """Check if any local LLM server is available."""
        return any(s.available for s in self.servers)

    def get_available_agents(self) -> list[str]:
        """Get list of available agent type names."""
        agents = []
        for server in self.servers:
            if server.available:
                agents.append(server.name)
        return agents


class LocalLLMDetector:
    """
    Detects and probes local LLM servers.

    Usage:
        detector = LocalLLMDetector()
        status = await detector.detect_all()

        if status.any_available:
            print(f"Recommended: {status.recommended_server}/{status.recommended_model}")
        else:
            print("No local LLMs available")
    """

    # Default server configurations
    SERVERS = {
        "ollama": {
            "base_url": "http://localhost:11434",
            "env_var": "OLLAMA_HOST",
            "health_endpoint": "/api/tags",
            "models_key": "models",
            "model_name_key": "name",
        },
        "lm-studio": {
            "base_url": "http://localhost:1234/v1",
            "env_var": "LM_STUDIO_HOST",
            "health_endpoint": "/models",
            "models_key": "data",
            "model_name_key": "id",
        },
    }

    # Model preference order (more capable models first)
    MODEL_PREFERENCES = [
        "llama3.2",
        "llama3.1",
        "llama3",
        "codellama",
        "mistral",
        "mixtral",
        "qwen",
        "deepseek",
        "phi",
        "gemma",
    ]

    def __init__(self, timeout: float = 5.0):
        """Initialize detector.

        Args:
            timeout: Timeout in seconds for health checks
        """
        self.timeout = timeout

    async def detect_all(self) -> LocalLLMStatus:
        """Detect all local LLM servers.

        Returns:
            LocalLLMStatus with information about available servers
        """
        # Probe servers in parallel
        tasks = [self._probe_server(name, config) for name, config in self.SERVERS.items()]
        servers = await asyncio.gather(*tasks)

        # Calculate totals and recommendations
        status = LocalLLMStatus(servers=list(servers))
        status.total_models = sum(len(s.models) for s in servers if s.available)

        # Find recommended server/model
        for server in servers:
            if server.available and server.models:
                if status.recommended_server is None:
                    status.recommended_server = server.name
                    status.recommended_model = self._pick_best_model(server.models)

        return status

    async def detect_ollama(self) -> LocalLLMServer:
        """Detect Ollama server specifically."""
        return await self._probe_server("ollama", self.SERVERS["ollama"])

    async def detect_lm_studio(self) -> LocalLLMServer:
        """Detect LM Studio server specifically."""
        return await self._probe_server("lm-studio", self.SERVERS["lm-studio"])

    async def _probe_server(self, name: str, config: dict) -> LocalLLMServer:
        """Probe a single server for availability.

        Args:
            name: Server name
            config: Server configuration dict

        Returns:
            LocalLLMServer with probe results
        """
        # Check for environment variable override
        base_url = os.environ.get(config["env_var"], config["base_url"])

        server = LocalLLMServer(name=name, base_url=base_url, available=False)

        try:
            pool = get_http_pool()
            health_url = base_url.rstrip("/") + config["health_endpoint"]

            async with pool.get_session("local_llm") as pooled_client:
                client = cast(httpx.AsyncClient, pooled_client)
                response = await client.get(health_url, timeout=self.timeout)
                if response.status_code != 200:
                    return server

                data = response.json()
                server.available = True

                # Extract model list
                models_data = data.get(config["models_key"], [])
                server.models = [
                    m.get(config["model_name_key"], str(m))
                    for m in models_data
                    if isinstance(m, dict)
                ]

                if server.models:
                    server.default_model = self._pick_best_model(server.models)

                return server

        except (OSError, ConnectionError) as e:
            logger.debug("%s not available at %s: %s", name, base_url, e)
            return server
        except asyncio.TimeoutError:
            logger.debug("%s timed out at %s", name, base_url)
            return server
        except (ValueError, KeyError, TypeError) as e:
            # JSON parsing or data extraction issues
            logger.debug("Error parsing %s response: %s", name, e)
            return server
        except (RuntimeError, AttributeError) as e:
            # Unexpected - log at info level
            logger.info("Unexpected error probing %s: %s: %s", name, type(e).__name__, e)
            return server

    def _pick_best_model(self, models: list[str]) -> str:
        """Pick the best model from a list based on preferences.

        Args:
            models: List of available model names

        Returns:
            Best model name, or first model if no preferences match
        """
        models_lower = {m.lower(): m for m in models}

        for preferred in self.MODEL_PREFERENCES:
            for model_lower, model_orig in models_lower.items():
                if preferred in model_lower:
                    return model_orig

        # No preference match, return first
        return models[0] if models else "default"


async def detect_local_llms() -> LocalLLMStatus:
    """Convenience function to detect all local LLMs.

    Returns:
        LocalLLMStatus with available servers and models

    Example:
        status = await detect_local_llms()
        if status.any_available:
            from aragora.agents.registry import AgentRegistry
            agent = AgentRegistry.create(status.recommended_server)
    """
    detector = LocalLLMDetector()
    return await detector.detect_all()


def detect_local_llms_sync() -> LocalLLMStatus:
    """Synchronous version of detect_local_llms.

    Returns:
        LocalLLMStatus with available servers and models
    """
    return asyncio.run(detect_local_llms())


__all__ = [
    "LocalLLMDetector",
    "LocalLLMServer",
    "LocalLLMStatus",
    "detect_local_llms",
    "detect_local_llms_sync",
]
