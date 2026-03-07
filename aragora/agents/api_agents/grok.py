"""
Grok agent for xAI's Grok API.
"""

from aragora.agents.api_agents.base import APIAgent
from aragora.core_types import AgentRole
from aragora.agents.api_agents.common import get_primary_api_key
from aragora.agents.api_agents.openai_compatible import OpenAICompatibleMixin
from aragora.agents.registry import AgentRegistry


@AgentRegistry.register(
    "grok",
    default_model="grok-4.2",
    agent_type="API",
    env_vars="XAI_API_KEY or GROK_API_KEY",
)
class GrokAgent(OpenAICompatibleMixin, APIAgent):
    """Agent that uses xAI's Grok API (OpenAI-compatible).

    Uses the xAI API at https://api.x.ai/v1 with models like grok-4-latest.

    Supports automatic fallback to OpenRouter when xAI API returns
    rate limit/quota errors.

    Uses OpenAICompatibleMixin for standard OpenAI-compatible API implementation.
    """

    OPENROUTER_MODEL_MAP = {
        "grok-4.2": "x-ai/grok-4",  # grok-4.2 not yet on OpenRouter; use grok-4
        "grok-4-2": "x-ai/grok-4",
        "grok-4-1-fast": "x-ai/grok-4.1-fast",
        "grok-4-1-fast-reasoning": "x-ai/grok-4.1-fast",
        "grok-4-latest": "x-ai/grok-4",
        "grok-4": "x-ai/grok-4",
        "grok-4-fast": "x-ai/grok-4-fast",
        "grok-3": "x-ai/grok-3",
        "grok-2": "x-ai/grok-2-1212",
        "grok-2-1212": "x-ai/grok-2-1212",
        "grok-beta": "x-ai/grok-beta",
    }
    DEFAULT_FALLBACK_MODEL = "x-ai/grok-4"

    def __init__(
        self,
        name: str = "grok",
        model: str = "grok-4.2",
        role: AgentRole = "proposer",
        timeout: int = 120,
        api_key: str | None = None,
        enable_fallback: bool | None = None,  # None = use config setting
    ) -> None:
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key=api_key
            or get_primary_api_key(
                "XAI_API_KEY",
                "GROK_API_KEY",
                allow_openrouter_fallback=True,
            ),
            base_url="https://api.x.ai/v1",
        )
        self.agent_type = "grok"
        # Use config setting if not explicitly provided
        if enable_fallback is None:
            from aragora.agents.fallback import get_default_fallback_enabled

            self.enable_fallback = get_default_fallback_enabled()
        else:
            self.enable_fallback = enable_fallback
        self._fallback_agent = None

    def is_quota_error(self, status_code: int, error_text: str) -> bool:
        """Treat xAI live-search deprecation as a fallback-triggering provider error."""
        error_lower = (error_text or "").lower()
        if status_code == 410 and (
            "live search is deprecated" in error_lower or "agent tools api" in error_lower
        ):
            return True
        return super().is_quota_error(status_code, error_text)


__all__ = ["GrokAgent"]
