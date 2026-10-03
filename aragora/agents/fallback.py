"""
Quota detection and fallback utilities for API agents.

Provides shared logic for detecting quota/rate limit errors and falling back
to OpenRouter when the primary provider is unavailable.

Also provides AgentFallbackChain for multi-provider sequencing with
CircuitBreaker integration.
"""

from __future__ import annotations

__all__ = [
    "QUOTA_ERROR_KEYWORDS",
    "QuotaFallbackMixin",
    "FallbackMetrics",
    "AllProvidersExhaustedError",
    "FallbackTimeoutError",
    "AgentFallbackChain",
    "get_local_fallback_providers",
    "build_fallback_chain_with_local",
    "is_local_llm_available",
    "get_default_fallback_enabled",
]

import logging
import os
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast
from collections.abc import Callable

from aragora.core_types import AgentRole
from aragora.observability.metrics.agent import (
    record_fallback_activation,
    record_fallback_success,
)

_AgentRegistry: Any = None
try:
    from aragora.agents.registry import AgentRegistry

    _AgentRegistry = AgentRegistry
except (ImportError, ModuleNotFoundError):
    pass

if TYPE_CHECKING:
    from aragora.resilience import CircuitBreaker

    from .api_agents import OpenRouterAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session circuit-breaker integration (lazy import -- non-breaking)
# ---------------------------------------------------------------------------

_session_cb_module: Any = None
_session_cb_import_attempted = False


def _get_session_cb():
    """Lazily import and return the SessionCircuitBreaker singleton, or None."""
    global _session_cb_module, _session_cb_import_attempted
    if _session_cb_import_attempted:
        return _session_cb_module
    _session_cb_import_attempted = True
    try:
        from aragora.routing.session_circuit_breaker import get_session_circuit_breaker

        _session_cb_module = get_session_circuit_breaker()
    except (ImportError, ModuleNotFoundError):
        logger.debug("session_circuit_breaker not available, skipping integration")
        _session_cb_module = None
    return _session_cb_module


# Status codes that should notify the session circuit breaker.
_CB_NOTIFY_STATUS_CODES = frozenset({401, 403, 429})


# Common keywords indicating quota/rate limit errors across providers
QUOTA_ERROR_KEYWORDS = frozenset(
    [
        # Rate limiting
        "rate limit",
        "rate_limit",
        "ratelimit",
        "too many requests",
        # Quota exceeded
        "quota",
        "exceeded",
        "limit exceeded",
        "resource exhausted",
        "resource_exhausted",
        # Billing/credits
        "billing",
        "credit balance",
        "insufficient",
        "insufficient_quota",
        "purchase credits",
    ]
)


class QuotaFallbackMixin:
    """Mixin providing shared quota detection and OpenRouter fallback logic.

    This mixin extracts the common quota error detection and fallback pattern
    used by Gemini, Anthropic, OpenAI, and Grok agents.

    The mixin expects the following attributes on the class:
        - name: str - Agent name for logging
        - enable_fallback: bool - Whether fallback is enabled
        - model: str - Current model name
        - timeout: int - Timeout setting
        - role: str - Agent role (optional, defaults to "proposer")
        - system_prompt: str - System prompt (optional)

    Class attributes that can be overridden:
        - OPENROUTER_MODEL_MAP: dict[str, str] - Maps provider models to OpenRouter models
        - DEFAULT_FALLBACK_MODEL: str - Default model if no mapping found

    Usage:
        class MyAgent(APIAgent, QuotaFallbackMixin):
            OPENROUTER_MODEL_MAP = {
                "gpt-4o": "openai/gpt-5.4",
                "gpt-4": "openai/gpt-4",
            }
            DEFAULT_FALLBACK_MODEL = "openai/gpt-5.4"

            async def generate(self, prompt, context):
                # ... make API call ...
                if self.is_quota_error(status, error_text):
                    result = await self.fallback_generate(prompt, context)
                    if result is not None:
                        return result
                    raise RuntimeError("Quota exceeded and fallback unavailable")
    """

    # Override these in subclasses for provider-specific model mappings
    OPENROUTER_MODEL_MAP: dict[str, str] = {}
    DEFAULT_FALLBACK_MODEL: str = "anthropic/claude-opus-5"

    # Instance-level cached fallback agent (set by _get_cached_fallback_agent)
    _fallback_agent: OpenRouterAgent | None = None

    def _get_cached_fallback_agent(self) -> OpenRouterAgent | None:
        """Get or create a cached OpenRouter fallback agent.

        Unlike _get_openrouter_fallback(), this caches the agent for reuse.
        """
        if self._fallback_agent is None:
            self._fallback_agent = self._get_openrouter_fallback()
            if self._fallback_agent:
                name = getattr(self, "name", "unknown")
                logger.debug(
                    "[%s] Created OpenRouter fallback agent with model %s",
                    name,
                    self._fallback_agent.model,
                )
        return self._fallback_agent

    # ------------------------------------------------------------------
    # Session circuit-breaker helpers
    # ------------------------------------------------------------------

    def _derive_provider_name(self) -> str:
        """Derive a short provider name from the agent class name.

        Maps class names to canonical provider strings used by the
        session circuit breaker (e.g. ``"anthropic"``, ``"openai"``).
        Falls back to the lowercased class name.
        """
        cls_name = type(self).__name__.lower()
        for key in ("anthropic", "openai", "gemini", "grok", "mistral"):
            if key in cls_name:
                return key
        # Use the agent ``name`` attribute if set (e.g. "claude-api")
        agent_name = getattr(self, "name", cls_name)
        return str(agent_name).split("-")[0].split("_")[0].lower()

    def _notify_session_circuit_breaker(self, status_code: int) -> None:
        """Notify the session circuit breaker of a provider failure.

        Only notifies for auth/quota status codes (401, 403, 429).
        Safe to call even when the circuit breaker module is unavailable.
        """
        if status_code not in _CB_NOTIFY_STATUS_CODES:
            return
        cb = _get_session_cb()
        if cb is None:
            return
        provider = self._derive_provider_name()
        reason = f"HTTP {status_code}"
        logger.debug(
            "Notifying session circuit breaker: provider=%s status=%d",
            provider,
            status_code,
        )
        cb.mark_provider_failed(provider, reason=reason, status_code=status_code)

    def is_provider_pinned(self) -> bool:
        """Check whether this provider is pinned as failed for the session.

        Returns ``False`` when the circuit breaker module is unavailable
        (i.e. never blocks calls when the module is missing).
        """
        cb = _get_session_cb()
        if cb is None:
            return False
        provider = self._derive_provider_name()
        return not cb.is_provider_available(provider)

    # ------------------------------------------------------------------

    def get_fallback_model(self) -> str:
        """Get the OpenRouter model for fallback based on current model.

        Uses the class's OPENROUTER_MODEL_MAP to find a matching model,
        falling back to DEFAULT_FALLBACK_MODEL if no match is found.
        """
        model = getattr(self, "model", "")
        return self.OPENROUTER_MODEL_MAP.get(model, self.DEFAULT_FALLBACK_MODEL)

    def is_quota_error(self, status_code: int, error_text: str) -> bool:
        """Check if an error indicates quota/rate limit issues or timeouts.

        This is a unified check that works across providers:
        - 401: Authentication failure (invalid/expired API key)
        - 429: Rate limit (all providers)
        - 403: Can indicate quota exceeded (Gemini)
        - 408, 504, 524: Timeout errors (should trigger fallback)

        Args:
            status_code: HTTP status code from response
            error_text: Error message text from response body

        Returns:
            True if this appears to be a quota/rate limit/timeout error
        """
        # 401 is universally an auth failure (invalid/expired key)
        if status_code == 401:
            return True

        # 429 is universally rate limit
        if status_code == 429:
            return True

        # Timeout status codes - treat as quota to trigger fallback
        # 408: Request Timeout, 504: Gateway Timeout, 524: Cloudflare timeout
        if status_code in (408, 504, 524):
            return True

        # 403 can indicate quota exceeded (especially for Gemini)
        if status_code == 403:
            error_lower = error_text.lower()
            if any(
                kw in error_lower
                for kw in [
                    "quota",
                    "exceeded",
                    "billing",
                    "resource exhausted",
                    "insufficient_quota",
                ]
            ):
                return True

        # 400 can indicate billing/credit exhaustion (especially Anthropic)
        # Anthropic returns 400 with "credit balance is too low" when credits are exhausted
        if status_code == 400:
            error_lower = error_text.lower()
            billing_keywords = [
                "credit balance",
                "billing",
                "insufficient",
                "purchase credits",
                "payment",
            ]
            if any(kw in error_lower for kw in billing_keywords):
                return True

        # Check for timeout keywords in error text
        error_lower = error_text.lower()
        if "timeout" in error_lower or "timed out" in error_lower:
            return True

        # Check for quota-related keywords in any error
        return any(kw in error_lower for kw in QUOTA_ERROR_KEYWORDS)

    def _get_openrouter_fallback(self) -> OpenRouterAgent | None:
        """Get an OpenRouter fallback agent if available.

        Returns:
            OpenRouterAgent instance if OPENROUTER_API_KEY is set, None otherwise
        """
        try:
            from aragora.config import get_api_key

            openrouter_key = get_api_key("OPENROUTER_API_KEY", required=False)
        except (ImportError, KeyError, OSError) as e:
            # ImportError: config module not available
            # KeyError: API key not in config
            # OSError: file-based config read failure
            logger.debug("Config-based API key retrieval failed: %s", e)
            openrouter_key = None
        if not openrouter_key:
            return None

        # Lazy import to avoid circular dependency
        from .api_agents import OpenRouterAgent

        # Use the class's model mapping to get the fallback model
        fallback_model = self.get_fallback_model()

        # Get agent attributes with sensible defaults
        name = getattr(self, "name", "fallback")
        role = cast(AgentRole, getattr(self, "role", "proposer"))
        timeout = getattr(self, "timeout", 120)
        system_prompt = getattr(self, "system_prompt", None)

        agent = OpenRouterAgent(
            name=f"{name}_fallback",
            model=fallback_model,
            role=role,
            timeout=timeout,
        )
        if system_prompt:
            agent.system_prompt = system_prompt

        return agent

    # -----------------------------------------------------------------
    # Content-policy error detection (non-retryable)
    # -----------------------------------------------------------------

    _CONTENT_POLICY_KEYWORDS = frozenset(
        [
            "content policy",
            "content_policy",
            "content filter",
            "content_filter",
            "safety filter",
            "safety_filter",
            "harmful content",
            "violates our usage policies",
            "violates usage policies",
            "moderation",
        ]
    )

    # Status codes worth retrying across providers
    _RETRYABLE_STATUS_CODES = frozenset({402, 408, 429, 504})

    @staticmethod
    def _is_content_policy_error(status_code: int, error_text: str) -> bool:
        """Return True when the error is a content-policy rejection (non-retryable).

        Content-policy errors (400 with policy keywords) will fail on *every*
        provider, so there is no point in trying another one.
        """
        if status_code != 400:
            return False
        lower = error_text.lower()
        return any(kw in lower for kw in QuotaFallbackMixin._CONTENT_POLICY_KEYWORDS)

    # -----------------------------------------------------------------
    # Multi-provider fallback helpers
    # -----------------------------------------------------------------

    # Mapping: env-var name -> (provider key, factory builder)
    # The factory builder receives (name, role, timeout, system_prompt)
    # and returns an agent instance.
    _PROVIDER_ENV_KEYS: list[tuple[str, str]] = [
        ("OPENROUTER_API_KEY", "openrouter"),
        ("OPENAI_API_KEY", "openai"),
        ("ANTHROPIC_API_KEY", "anthropic"),
        ("GEMINI_API_KEY", "gemini"),
        ("MISTRAL_API_KEY", "mistral"),
        ("XAI_API_KEY", "grok"),
    ]
    _PROVIDER_ENV_BY_KEY = {provider_key: env_var for env_var, provider_key in _PROVIDER_ENV_KEYS}
    _PROVIDER_ALIASES = {
        "anthropic": "anthropic",
        "anthropic-api": "anthropic",
        "claude": "anthropic",
        "gemini": "gemini",
        "gemini-cli": "gemini",
        "grok": "grok",
        "grok-cli": "grok",
        "mistral": "mistral",
        "mistral-api": "mistral",
        "codestral": "mistral",
        "openai": "openai",
        "openai-api": "openai",
        "openrouter": "openrouter",
        "xai": "grok",
    }

    def _normalize_fallback_provider_key(self, provider_name: str) -> str | None:
        """Map config/provider aliases onto the runtime fallback provider keys."""
        normalized = provider_name.strip().lower()
        if not normalized:
            return None
        return self._PROVIDER_ALIASES.get(normalized, normalized)

    def _get_configured_fallback_order(self) -> list[str]:
        """Return normalized providers requested by agent config, preserving order."""
        configured_chain = getattr(getattr(self, "_config", None), "fallback_chain", None)
        if configured_chain is None:
            configured_chain = getattr(self, "fallback_chain", None)

        ordered: list[str] = []
        for provider_name in configured_chain or []:
            provider_key = self._normalize_fallback_provider_key(str(provider_name))
            if provider_key not in self._PROVIDER_ENV_BY_KEY or provider_key in ordered:
                continue
            ordered.append(provider_key)
        return ordered

    def _get_available_fallback_providers(self) -> list[tuple[str, Any]]:
        """Build an ordered list of ``(provider_name, agent)`` pairs for fallback.

        Skips the provider that ``self`` belongs to (no point falling back to
        itself). When the agent was created from YAML config, its declared
        ``fallback_chain`` is preferred first and any remaining default providers
        are appended afterwards. Returns only providers whose API keys are set in
        the environment.
        """
        own_provider = self._derive_provider_name()
        name = getattr(self, "name", "fallback")
        role = cast(AgentRole, getattr(self, "role", "proposer"))
        timeout = getattr(self, "timeout", 120)
        system_prompt = getattr(self, "system_prompt", None)

        providers: list[tuple[str, Any]] = []
        configured_order = self._get_configured_fallback_order()
        ordered_provider_keys = configured_order + [
            provider_key
            for _, provider_key in self._PROVIDER_ENV_KEYS
            if provider_key not in configured_order
        ]

        for provider_key in ordered_provider_keys:
            # Skip self
            if provider_key == own_provider:
                continue

            env_var = self._PROVIDER_ENV_BY_KEY[provider_key]
            api_key = os.environ.get(env_var)
            if not api_key:
                continue

            agent = self._create_fallback_agent(
                provider_key, api_key, name, role, timeout, system_prompt
            )
            if agent is not None:
                providers.append((provider_key, agent))

        return providers

    @staticmethod
    def _create_fallback_agent(
        provider_key: str,
        api_key: str,
        name: str,
        role: AgentRole,
        timeout: int,
        system_prompt: str | None,
    ) -> Any | None:
        """Create a fallback agent for the given provider.

        Returns None if the required agent class cannot be imported.
        """
        try:
            agent: Any
            if provider_key == "openrouter":
                from .api_agents import OpenRouterAgent

                agent = OpenRouterAgent(
                    name=f"{name}_fallback_openrouter",
                    role=role,
                    timeout=timeout,
                )
            elif provider_key == "openai":
                from .api_agents.openai import OpenAIAPIAgent

                agent = OpenAIAPIAgent(
                    name=f"{name}_fallback_openai",
                    role=role,
                    timeout=timeout,
                    api_key=api_key,
                    enable_fallback=False,  # prevent recursive fallback
                )
            elif provider_key == "anthropic":
                from .api_agents.anthropic import AnthropicAPIAgent

                agent = AnthropicAPIAgent(
                    name=f"{name}_fallback_anthropic",
                    role=role,
                    timeout=timeout,
                    api_key=api_key,
                    enable_fallback=False,
                )
            elif provider_key == "gemini":
                from .api_agents.gemini import GeminiAgent

                agent = GeminiAgent(
                    name=f"{name}_fallback_gemini",
                    role=role,
                    timeout=timeout,
                    api_key=api_key,
                    enable_fallback=False,
                )
            elif provider_key == "mistral":
                from .api_agents.mistral import MistralAPIAgent

                agent = MistralAPIAgent(
                    name=f"{name}_fallback_mistral",
                    role=role,
                    timeout=timeout,
                    api_key=api_key,
                    enable_fallback=False,
                )
            elif provider_key == "grok":
                from .api_agents.grok import GrokAgent

                agent = GrokAgent(
                    name=f"{name}_fallback_grok",
                    role=role,
                    timeout=timeout,
                    api_key=api_key,
                    enable_fallback=False,
                )
            else:
                return None

            if system_prompt:
                agent.system_prompt = system_prompt
            return agent
        except (ImportError, ModuleNotFoundError, TypeError, ValueError) as e:
            logger.debug("Could not create fallback agent for %s: %s", provider_key, e)
            return None

    def _get_preconfigured_fallback_agent(self) -> OpenRouterAgent | None:
        """Return an explicitly injected fallback agent without auto-creating one.

        ``fallback_generate()`` should respect pre-seeded or test-injected
        fallback agents, but it should not auto-create a real OpenRouter agent
        ahead of an explicitly patched provider chain. Auto-creation remains
        available through ``_get_cached_fallback_agent()`` for callers that
        explicitly opt into it.
        """
        cached_fallback = getattr(self, "_fallback_agent", None)
        if cached_fallback is not None:
            return cast("OpenRouterAgent | None", cached_fallback)

        instance_getter = getattr(self, "__dict__", {}).get("_get_cached_fallback_agent")
        if callable(instance_getter):
            return cast("OpenRouterAgent | None", instance_getter())

        return None

    def _build_fallback_providers(self) -> list[tuple[str, Any]]:
        """Build the fallback provider chain without auto-creating OpenRouter."""
        fallback_providers: list[tuple[str, Any]] = []
        seen_provider_keys: set[str] = set()

        cached_fallback = self._get_preconfigured_fallback_agent()
        if cached_fallback is not None and self._derive_provider_name() != "openrouter":
            fallback_providers.append(("openrouter", cached_fallback))
            seen_provider_keys.add("openrouter")

        for provider_key, agent in self._get_available_fallback_providers():
            if provider_key in seen_provider_keys:
                continue
            fallback_providers.append((provider_key, agent))
            seen_provider_keys.add(provider_key)

        return fallback_providers

    async def fallback_generate(
        self,
        prompt: str,
        context: list | None = None,
        status_code: int | None = None,
    ) -> str | None:
        """Attempt to generate using multiple fallback providers.

        Tries providers in order: OpenRouter first (existing behavior), then
        other providers that have API keys set. Skips the provider that ``self``
        belongs to. Only retries on billing/rate-limit errors (402, 429, 408, 504),
        not on content-policy errors (400 with policy keywords).

        Args:
            prompt: The prompt to send
            context: Optional conversation context
            status_code: Optional HTTP status code that triggered the fallback

        Returns:
            Generated response string if fallback succeeded, None otherwise
        """
        # Notify session circuit breaker of the failure
        if status_code is not None:
            self._notify_session_circuit_breaker(status_code)

        if not getattr(self, "enable_fallback", True):
            return None

        name = getattr(self, "name", "unknown")
        status_info = f" (status {status_code})" if status_code else ""
        error_type = "rate_limit" if status_code == 429 else "quota"

        fallback_providers = self._build_fallback_providers()
        if not fallback_providers:
            logger.warning(
                "API quota/rate limit error%s for %s but no fallback provider API keys are set",
                status_info,
                name,
            )
            return None

        logger.info(
            "API quota/rate limit error%s for %s, trying %d fallback provider(s): %s",
            status_info,
            name,
            len(fallback_providers),
            ", ".join(p[0] for p in fallback_providers),
        )

        last_error: Exception | None = None
        for provider_key, agent in fallback_providers:
            # Record fallback activation telemetry
            record_fallback_activation(
                primary_agent=name,
                fallback_provider=provider_key,
                error_type=error_type,
            )

            start_time = time.time()
            try:
                result = await agent.generate(prompt, context)
                latency = time.time() - start_time
                record_fallback_success(provider_key, success=True, latency_seconds=latency)
                logger.info(
                    "Fallback to %s succeeded for %s (%.2fs)",
                    provider_key,
                    name,
                    latency,
                )
                return result
            except Exception as e:  # noqa: BLE001 - Intentional catch-all: fallback handler must try all providers before giving up
                latency = time.time() - start_time
                record_fallback_success(provider_key, success=False, latency_seconds=latency)
                last_error = e

                # Check if this is a content-policy error (non-retryable)
                error_str = str(e).lower()
                if any(kw in error_str for kw in self._CONTENT_POLICY_KEYWORDS):
                    logger.debug(
                        "Content policy error from %s fallback, not retrying other providers: %s",
                        provider_key,
                        e,
                    )
                    return None

                logger.debug(
                    "Fallback provider %s failed for %s (%.2fs): %s",
                    provider_key,
                    name,
                    latency,
                    e,
                )
                continue

        # All fallback providers exhausted
        logger.warning(
            "All fallback providers exhausted for %s. Last error: %s",
            name,
            last_error,
        )
        return None

    async def fallback_generate_stream(
        self,
        prompt: str,
        context: list | None = None,
        status_code: int | None = None,
    ):
        """Attempt to stream using multiple fallback providers.

        Tries providers in order: OpenRouter first, then other providers
        with valid API keys. Skips the provider that ``self`` belongs to.

        Args:
            prompt: The prompt to send
            context: Optional conversation context
            status_code: Optional HTTP status code that triggered the fallback

        Yields:
            Content tokens from fallback stream, or nothing if fallback unavailable
        """
        # Notify session circuit breaker of the failure
        if status_code is not None:
            self._notify_session_circuit_breaker(status_code)

        if not getattr(self, "enable_fallback", True):
            return

        name = getattr(self, "name", "unknown")
        error_type = "rate_limit" if status_code == 429 else "quota"

        fallback_providers = self._build_fallback_providers()
        if not fallback_providers:
            status_info = f" (status {status_code})" if status_code else ""
            logger.warning(
                "API quota/rate limit error%s for %s but no fallback streaming provider API keys are set",
                status_info,
                name,
            )
            return

        status_info = f" (status {status_code})" if status_code else ""
        logger.info(
            "API quota/rate limit error%s for %s, trying %d fallback streaming provider(s): %s",
            status_info,
            name,
            len(fallback_providers),
            ", ".join(p[0] for p in fallback_providers),
        )

        for provider_key, agent in fallback_providers:
            if not hasattr(agent, "generate_stream"):
                logger.debug(
                    "Fallback provider %s has no streaming support, skipping", provider_key
                )
                continue

            # Record fallback activation telemetry
            record_fallback_activation(
                primary_agent=name,
                fallback_provider=provider_key,
                error_type=error_type,
            )

            start_time = time.time()
            success = False
            try:
                async for token in agent.generate_stream(prompt, context):
                    if not success:
                        success = True  # First token received = success
                    yield token
                latency = time.time() - start_time
                record_fallback_success(provider_key, success=True, latency_seconds=latency)
                logger.info(
                    "Fallback stream to %s succeeded for %s (%.2fs)",
                    provider_key,
                    name,
                    latency,
                )
                return
            except Exception as e:  # noqa: BLE001 - Intentional catch-all: fallback handler must try all providers before giving up
                latency = time.time() - start_time
                record_fallback_success(provider_key, success=False, latency_seconds=latency)

                # Content policy error - stop trying
                error_str = str(e).lower()
                if any(kw in error_str for kw in self._CONTENT_POLICY_KEYWORDS):
                    logger.debug(
                        "Content policy error from %s stream fallback, stopping: %s",
                        provider_key,
                        e,
                    )
                    return

                logger.debug(
                    "Fallback stream provider %s failed for %s (%.2fs): %s",
                    provider_key,
                    name,
                    latency,
                    e,
                )
                continue

        logger.warning("All fallback streaming providers exhausted for %s", name)


@dataclass
class FallbackMetrics:
    """Metrics for tracking fallback chain behavior."""

    primary_attempts: int = 0
    primary_successes: int = 0
    fallback_attempts: int = 0
    fallback_successes: int = 0
    total_failures: int = 0
    last_fallback_time: float = 0.0
    fallback_providers_used: dict[str, int] = field(default_factory=dict)

    def record_primary_attempt(self, success: bool) -> None:
        """Record a primary provider attempt."""
        self.primary_attempts += 1
        if success:
            self.primary_successes += 1
        else:
            self.total_failures += 1

    def record_fallback_attempt(self, provider: str, success: bool) -> None:
        """Record a fallback provider attempt."""
        self.fallback_attempts += 1
        self.fallback_providers_used[provider] = self.fallback_providers_used.get(provider, 0) + 1
        self.last_fallback_time = time.time()
        if success:
            self.fallback_successes += 1
        else:
            self.total_failures += 1

    @property
    def fallback_rate(self) -> float:
        """Percentage of requests that needed fallback."""
        total = self.primary_attempts + self.fallback_attempts
        if total == 0:
            return 0.0
        return self.fallback_attempts / total

    @property
    def success_rate(self) -> float:
        """Overall success rate including fallbacks."""
        total = self.primary_successes + self.fallback_successes
        attempts = self.primary_attempts + self.fallback_attempts
        if attempts == 0:
            return 0.0
        return total / attempts


class AllProvidersExhaustedError(RuntimeError):
    """Raised when all providers in a fallback chain have failed."""

    def __init__(self, providers: list[str], last_error: Exception | None = None):
        self.providers = providers
        self.last_error = last_error
        super().__init__(
            f"All providers exhausted: {', '.join(providers)}. Last error: {last_error}"
        )


class FallbackTimeoutError(Exception):
    """Raised when fallback chain exceeds time limit."""

    def __init__(self, elapsed: float, limit: float, tried: list[str]):
        self.elapsed = elapsed
        self.limit = limit
        self.tried_providers = tried
        super().__init__(
            f"Fallback chain timeout after {elapsed:.1f}s (limit {limit}s). "
            f"Tried: {', '.join(tried)}"
        )


class AgentFallbackChain:
    """Sequences agent providers with automatic fallback and CircuitBreaker integration.

    This class manages a chain of providers (e.g., OpenAI -> OpenRouter -> Anthropic -> CLI)
    and automatically falls back to the next provider when one fails. It integrates with
    CircuitBreaker to track provider health and avoid repeatedly calling failing providers.

    Usage:
        from aragora.resilience import get_circuit_breaker

        chain = AgentFallbackChain(
            providers=["openai", "openrouter", "anthropic"],
            circuit_breaker=get_circuit_breaker("fallback_chain", failure_threshold=3, cooldown_seconds=60),
            max_retries=3,  # Only try 3 providers before giving up
            max_fallback_time=30.0,  # Give up after 30 seconds total
        )

        # Register provider factories
        chain.register_provider("openai", lambda: OpenAIAPIAgent())
        chain.register_provider("openrouter", lambda: OpenRouterAgent())
        chain.register_provider("anthropic", lambda: AnthropicAPIAgent())

        # Generate with automatic fallback
        result = await chain.generate(prompt, context)

        # Check metrics
        print(f"Fallback rate: {chain.metrics.fallback_rate:.1%}")
    """

    # Default limits
    DEFAULT_MAX_RETRIES = 5
    DEFAULT_MAX_FALLBACK_TIME = 120.0  # 2 minutes

    def __init__(
        self,
        providers: list[Any],
        circuit_breaker: CircuitBreaker | None = None,
        max_retries: int | None = None,
        max_fallback_time: float | None = None,
    ):
        """Initialize the fallback chain.

        Args:
            providers: Ordered list of provider names or agent instances (first is primary)
            circuit_breaker: CircuitBreaker instance for tracking provider health
            max_retries: Maximum number of providers to try (default: 5)
            max_fallback_time: Maximum time in seconds for the entire fallback chain (default: 120)
        """
        self.providers = providers
        self.circuit_breaker = circuit_breaker
        self.max_retries = max_retries if max_retries is not None else self.DEFAULT_MAX_RETRIES
        self.max_fallback_time = (
            max_fallback_time if max_fallback_time is not None else self.DEFAULT_MAX_FALLBACK_TIME
        )
        self.metrics = FallbackMetrics()
        self._provider_factories: dict[str, Callable[[], Any]] = {}
        self._cached_agents: dict[str, Any] = {}

    def _provider_key(self, provider: Any) -> str:
        """Return the name used for metrics/circuit breaker tracking."""
        if isinstance(provider, str):
            return provider
        return getattr(provider, "name", str(provider))

    def register_provider(
        self,
        name: str,
        factory: Callable[[], Any],
    ) -> None:
        """Register a factory function for creating a provider agent.

        Args:
            name: Provider name (must be in self.providers)
            factory: Callable that returns an agent instance
        """
        if name not in self.providers:
            logger.warning("Registering provider '%s' not in chain: %s", name, self.providers)
        self._provider_factories[name] = factory

    def _get_agent(self, provider: Any) -> Any | None:
        """Get or create an agent for the given provider."""
        if not isinstance(provider, str):
            return provider

        if provider in self._cached_agents:
            return self._cached_agents[provider]

        factory = self._provider_factories.get(provider)
        if not factory:
            logger.debug("No factory registered for provider '%s'", provider)
            return None

        try:
            agent = factory()
            self._cached_agents[provider] = agent
            return agent
        except (ValueError, TypeError, RuntimeError, OSError) as e:
            # ValueError/TypeError: invalid factory arguments or return type
            # RuntimeError: factory execution failure
            # OSError: network/file access issues during agent creation
            logger.warning("Failed to create agent for provider '%s': %s", provider, e)
            return None

    def _is_available(self, provider: str) -> bool:
        """Check if a provider is available (not tripped in circuit breaker)."""
        if not self.circuit_breaker:
            return True
        return self.circuit_breaker.is_available(provider)

    def _record_success(self, provider: str) -> None:
        """Record a successful call to a provider."""
        if self.circuit_breaker:
            self.circuit_breaker.record_success(provider)

    def _record_failure(self, provider: str) -> None:
        """Record a failed call to a provider."""
        if self.circuit_breaker:
            self.circuit_breaker.record_failure(provider)

    def get_available_providers(self) -> list[str]:
        """Get list of providers currently available (not circuit-broken)."""
        available: list[str] = []
        for provider in self.providers:
            provider_key = self._provider_key(provider)
            if self._is_available(provider_key):
                available.append(provider_key)
        return available

    async def generate(
        self,
        prompt: str,
        context: list | None = None,
    ) -> str:
        """Generate a response using the fallback chain.

        Tries each provider in order, skipping those that are circuit-broken,
        until one succeeds or all fail. Respects max_retries and max_fallback_time limits.

        Args:
            prompt: The prompt to send
            context: Optional conversation context

        Returns:
            Generated response string

        Raises:
            AllProvidersExhaustedError: If all providers fail
            FallbackTimeoutError: If max_fallback_time is exceeded
        """
        last_error: Exception | None = None
        tried_providers: list[str] = []
        start_time = time.time()
        retry_count = 0

        for i, provider in enumerate(self.providers):
            provider_key = self._provider_key(provider)
            # Check retry limit
            if retry_count >= self.max_retries:
                logger.warning(
                    "Max retries (%s) reached, stopping fallback chain", self.max_retries
                )
                break

            # Check time limit
            elapsed = time.time() - start_time
            if elapsed > self.max_fallback_time:
                raise FallbackTimeoutError(elapsed, self.max_fallback_time, tried_providers)

            # Skip if circuit breaker has this provider tripped
            if not self._is_available(provider_key):
                logger.debug("Skipping circuit-broken provider: %s", provider_key)
                continue

            agent = self._get_agent(provider)
            if not agent:
                continue

            tried_providers.append(provider_key)
            retry_count += 1
            is_primary = i == 0

            call_start = time.time()
            try:
                result = await agent.generate(prompt, context)
                call_latency = time.time() - call_start

                # Record success
                self._record_success(provider_key)
                if is_primary:
                    self.metrics.record_primary_attempt(success=True)
                else:
                    self.metrics.record_fallback_attempt(provider_key, success=True)
                    # Record Prometheus telemetry for fallback success
                    record_fallback_success(
                        provider_key, success=True, latency_seconds=call_latency
                    )
                    logger.debug(
                        f"fallback_success provider={provider_key} "
                        f"fallback_rate={self.metrics.fallback_rate:.1%}"
                    )

                return result

            except Exception as e:  # noqa: BLE001 - Intentional catch-all: fallback chain must handle any provider failure to try next provider
                call_latency = time.time() - call_start
                last_error = e
                self._record_failure(provider_key)

                # Determine error type for telemetry
                error_type = "rate_limit" if self._is_rate_limit_error(e) else "error"

                if is_primary:
                    self.metrics.record_primary_attempt(success=False)
                    logger.debug(
                        "Primary provider '%s' failed: %s, trying fallback", provider_key, e
                    )
                    # Record activation of fallback chain (next provider will be fallback)
                    if len(self.providers) > 1:
                        next_provider = self._provider_key(self.providers[1])
                        record_fallback_activation(
                            primary_agent=provider_key,
                            fallback_provider=next_provider,
                            error_type=error_type,
                        )
                else:
                    self.metrics.record_fallback_attempt(provider_key, success=False)
                    # Record Prometheus telemetry for fallback failure
                    record_fallback_success(
                        provider_key, success=False, latency_seconds=call_latency
                    )
                    logger.debug("Fallback provider '%s' failed: %s", provider_key, e)

                # Check if this looks like a rate limit error
                if error_type == "rate_limit":
                    logger.debug("Rate limit detected for %s, moving to next", provider_key)

                continue

        raise AllProvidersExhaustedError(tried_providers, last_error)

    async def generate_stream(
        self,
        prompt: str,
        context: list | None = None,
    ):
        """Stream a response using the fallback chain.

        Tries each provider in order until one succeeds or all fail.
        Respects max_retries and max_fallback_time limits.

        Args:
            prompt: The prompt to send
            context: Optional conversation context

        Yields:
            Content tokens from the successful provider

        Raises:
            AllProvidersExhaustedError: If all providers fail
            FallbackTimeoutError: If max_fallback_time is exceeded
        """
        last_error: Exception | None = None
        tried_providers: list[str] = []
        start_time = time.time()
        retry_count = 0

        for i, provider in enumerate(self.providers):
            provider_key = self._provider_key(provider)
            # Check retry limit
            if retry_count >= self.max_retries:
                logger.debug("Max retries (%s) reached for stream, stopping", self.max_retries)
                break

            # Check time limit
            elapsed = time.time() - start_time
            if elapsed > self.max_fallback_time:
                raise FallbackTimeoutError(elapsed, self.max_fallback_time, tried_providers)

            if not self._is_available(provider_key):
                logger.debug("Skipping circuit-broken provider: %s", provider_key)
                continue

            agent = self._get_agent(provider)
            if not agent:
                continue

            # Check if agent supports streaming
            if not hasattr(agent, "generate_stream"):
                logger.debug("Provider %s doesn't support streaming, skipping", provider_key)
                continue

            tried_providers.append(provider_key)
            retry_count += 1
            is_primary = i == 0
            call_start = time.time()

            try:
                # Try to get first token to verify stream works
                first_token = None
                async for token in agent.generate_stream(prompt, context):
                    if first_token is None:
                        first_token = token
                        call_latency = time.time() - call_start
                        # Stream started successfully
                        self._record_success(provider_key)
                        if is_primary:
                            self.metrics.record_primary_attempt(success=True)
                        else:
                            self.metrics.record_fallback_attempt(provider_key, success=True)
                            # Record Prometheus telemetry for fallback success
                            record_fallback_success(
                                provider_key, success=True, latency_seconds=call_latency
                            )
                            logger.debug("fallback_stream_success provider=%s", provider_key)
                    yield token

                # If we got here, stream completed successfully
                return

            except Exception as e:  # noqa: BLE001 - Intentional catch-all: fallback chain must handle any provider failure to try next provider
                call_latency = time.time() - call_start
                last_error = e
                self._record_failure(provider_key)

                # Determine error type for telemetry
                error_type = "rate_limit" if self._is_rate_limit_error(e) else "error"

                if is_primary:
                    self.metrics.record_primary_attempt(success=False)
                    logger.debug("Primary provider '%s' stream failed: %s", provider_key, e)
                    # Record activation of fallback chain
                    if len(self.providers) > 1:
                        next_provider = self._provider_key(self.providers[1])
                        record_fallback_activation(
                            primary_agent=provider_key,
                            fallback_provider=next_provider,
                            error_type=error_type,
                        )
                else:
                    self.metrics.record_fallback_attempt(provider_key, success=False)
                    # Record Prometheus telemetry for fallback failure
                    record_fallback_success(
                        provider_key, success=False, latency_seconds=call_latency
                    )
                    logger.debug("Fallback provider '%s' stream failed: %s", provider_key, e)

                continue

        raise AllProvidersExhaustedError(tried_providers, last_error)

    def _is_rate_limit_error(self, error: Exception) -> bool:
        """Check if an exception indicates a rate limit error."""
        error_str = str(error).lower()
        return any(kw in error_str for kw in QUOTA_ERROR_KEYWORDS)

    def reset_metrics(self) -> None:
        """Reset all metrics counters."""
        self.metrics = FallbackMetrics()

    def get_status(self) -> dict:
        """Get current status of the fallback chain."""
        return {
            "providers": [self._provider_key(provider) for provider in self.providers],
            "available_providers": self.get_available_providers(),
            "limits": {
                "max_retries": self.max_retries,
                "max_fallback_time": self.max_fallback_time,
            },
            "metrics": {
                "primary_attempts": self.metrics.primary_attempts,
                "primary_successes": self.metrics.primary_successes,
                "fallback_attempts": self.metrics.fallback_attempts,
                "fallback_successes": self.metrics.fallback_successes,
                "fallback_rate": f"{self.metrics.fallback_rate:.1%}",
                "success_rate": f"{self.metrics.success_rate:.1%}",
                "providers_used": self.metrics.fallback_providers_used,
            },
        }


def get_local_fallback_providers() -> list[str]:
    """Get list of available local LLM providers for fallback.

    Checks for running Ollama or LM Studio instances and returns
    their provider names if available.

    Returns:
        List of provider names (e.g., ["ollama", "lm-studio"])
    """
    if _AgentRegistry is None:
        return []
    try:
        local_agents = _AgentRegistry.detect_local_agents()
        return [agent["name"] for agent in local_agents if agent.get("available", False)]
    except (AttributeError, TypeError, KeyError, OSError) as e:
        # AttributeError: detect_local_agents not available
        # TypeError: unexpected return type from detect_local_agents
        # KeyError: missing expected keys in agent dict
        # OSError: network issues when probing local LLM servers
        logger.debug("Could not detect local LLMs: %s", e)
        return []


def build_fallback_chain_with_local(
    primary_providers: list[str],
    include_local: bool = True,
    local_priority: bool = False,
) -> list[str]:
    """Build a fallback chain that includes local LLMs.

    Args:
        primary_providers: Primary cloud providers to use
        include_local: Whether to include local LLMs in the chain
        local_priority: If True, local LLMs come before OpenRouter

    Returns:
        Ordered list of providers for fallback chain

    Example:
        # Default: OpenAI -> OpenRouter -> Local -> Anthropic
        chain = build_fallback_chain_with_local(
            ["openai", "openrouter", "anthropic"],
            include_local=True,
        )

        # Priority: OpenAI -> Local -> OpenRouter -> Anthropic
        chain = build_fallback_chain_with_local(
            ["openai", "openrouter", "anthropic"],
            include_local=True,
            local_priority=True,
        )
    """
    if not include_local:
        return primary_providers

    local_providers = get_local_fallback_providers()
    if not local_providers:
        return primary_providers

    result = []
    openrouter_idx = -1

    for i, provider in enumerate(primary_providers):
        if provider == "openrouter":
            openrouter_idx = i
            if local_priority:
                # Insert local before OpenRouter
                result.extend(local_providers)
            result.append(provider)
            if not local_priority:
                # Insert local after OpenRouter
                result.extend(local_providers)
        else:
            result.append(provider)

    # If no OpenRouter in chain, append local at the end
    if openrouter_idx == -1:
        result.extend(local_providers)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_result: list[str] = []
    for p in result:
        if p not in seen:
            seen.add(p)
            unique_result.append(p)
    return unique_result


def is_local_llm_available() -> bool:
    """Check if any local LLM server is available.

    Returns:
        True if Ollama, LM Studio, or compatible server is running
    """
    if _AgentRegistry is None:
        logger.debug("AgentRegistry not available for local LLM check")
        return False
    try:
        status = _AgentRegistry.get_local_status()
        return status.get("any_available", False)
    except (AttributeError, TypeError, KeyError, OSError) as e:
        # AttributeError: get_local_status not available
        # TypeError: unexpected return type
        # KeyError: missing expected keys
        # OSError: network issues when probing local LLM servers
        logger.warning("Failed to check local LLM availability: %s", e)
        return False


def get_default_fallback_enabled() -> bool:
    """Get the default value for enable_fallback from config.

    Returns True by default so debates degrade gracefully when a
    provider is down.  Opt out with ARAGORA_OPENROUTER_FALLBACK_ENABLED=false.

    Returns:
        True if fallback is enabled in settings, False otherwise
    """
    explicit_env = os.environ.get("ARAGORA_OPENROUTER_FALLBACK_ENABLED")
    if isinstance(explicit_env, str):
        normalized = explicit_env.strip().lower()
        if normalized:
            return normalized in {"1", "true", "yes", "on"}

    try:
        from aragora.config.settings import get_settings

        settings = get_settings()
        if settings.agent.openrouter_fallback_enabled:
            return True
    except (ImportError, AttributeError, KeyError) as e:
        # Expected errors: module not installed, missing attribute, or config key
        logger.debug("Settings not available for fallback config, defaulting to disabled: %s", e)
    except (ValueError, TypeError, OSError) as e:
        # ValueError/TypeError: invalid config values
        # OSError: file-based config read failure
        logger.warning("Unexpected error loading fallback settings, defaulting to disabled: %s", e)
    try:
        from aragora.config.secrets import get_secret

        explicit_flag = get_secret("ARAGORA_OPENROUTER_FALLBACK_ENABLED")
    except (ImportError, KeyError, OSError, ValueError) as e:
        # ImportError: secrets module not available
        # KeyError: secret not found
        # OSError: file/network access issues
        # ValueError: invalid secret value
        logger.debug("Could not load secrets config for fallback settings: %s", e)
        explicit_flag = None
    if explicit_flag is None:
        explicit_flag = os.environ.get("ARAGORA_OPENROUTER_FALLBACK_ENABLED")
    if isinstance(explicit_flag, str):
        normalized = explicit_flag.strip().lower()
        if normalized:
            return normalized in {"1", "true", "yes", "on"}

    # Default to enabled — better to fallback than to fail the debate
    return True
