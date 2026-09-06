"""
Grok agent for xAI's Grok API.
"""

from aragora.agents.api_agents.base import APIAgent
from aragora.core_types import AgentRole
from aragora.agents.api_agents.common import get_primary_api_key, upgrade_retired_model_id
from aragora.agents.api_agents.openai_compatible import OpenAICompatibleMixin
from aragora.agents.registry import AgentRegistry
from aragora.config.model_pins import GROK_46_DIRECT, GROK_46_VIA_OPENROUTER

# Frontier pick for the Grok API agent (2026-09-04 frontier-model-refresh).
DEFAULT_MODEL = GROK_46_DIRECT

_GROK_DEFAULT_BASE_URL = "https://api.x.ai/v1"


def _resolve_base_url(env_name: str, default: str) -> str:
    """Resolve the API base URL from the environment (issue #9304).

    Gateway values may omit the /v1 suffix the client paths expect; normalize
    so both "https://gw.example" and "https://gw.example/v1" work.
    """
    import os

    raw = os.environ.get(env_name, "").strip().rstrip("/")
    if not raw:
        return default
    return raw if raw.endswith("/v1") else raw + "/v1"


@AgentRegistry.register(
    "grok",
    default_model=DEFAULT_MODEL,
    agent_type="API",
    env_vars="XAI_API_KEY or GROK_API_KEY",
    accepts_api_key=True,
)
class GrokAgent(OpenAICompatibleMixin, APIAgent):
    """Agent that uses xAI's Grok API (OpenAI-compatible).

    Uses the xAI API at https://api.x.ai/v1 with models like grok-4-latest.

    Supports automatic fallback to OpenRouter when xAI API returns
    rate limit/quota errors.

    Uses OpenAICompatibleMixin for standard OpenAI-compatible API implementation.
    """

    # No static OPENROUTER_MODEL_MAP: QuotaFallbackMixin.get_fallback_model()
    # (aragora/agents/fallback.py) resolves the current model through the
    # catalog/upgrade-map instead, so every legacy or retired Grok spelling
    # (not just a hand-enumerated subset) transparently upgrades to its
    # frontier via OpenRouter.
    DEFAULT_FALLBACK_MODEL = GROK_46_VIA_OPENROUTER

    def __init__(
        self,
        name: str = "grok",
        model: str = DEFAULT_MODEL,
        role: AgentRole = "proposer",
        timeout: int = 120,
        api_key: str | None = None,
        enable_fallback: bool | None = None,  # None = use config setting
    ) -> None:
        # A retired or known-dead explicit id is upgraded before it can be
        # sent to the native endpoint (finding O-P2a); active and unknown
        # ids pass through untouched. See upgrade_retired_model_id. Skipped
        # for a custom XAI_BASE_URL (BYOK gateway/proxy, issue #9304): that
        # endpoint may serve ids under names the public catalog does not
        # recognize, so rewriting them would silently target the wrong
        # model on someone else's endpoint. Compared against the RESOLVED
        # (normalized) URL rather than raw env-var presence, so an env var
        # set to a spelling of the same official endpoint (e.g. missing the
        # /v1 suffix) still counts as official.
        resolved_base_url = _resolve_base_url("XAI_BASE_URL", _GROK_DEFAULT_BASE_URL)
        if resolved_base_url == _GROK_DEFAULT_BASE_URL:
            model = upgrade_retired_model_id(model)
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
            # XAI_BASE_URL supports BYOK gateways/proxies (LiteLLM,
            # enterprise API gateways, local proxies) — issue #9304.
            base_url=resolved_base_url,
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
