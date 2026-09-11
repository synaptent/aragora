"""
OpenAI API agent with OpenRouter fallback support.

Supports web search tool for web-capable responses when URLs
or web-related keywords are detected in the prompt.
"""

import asyncio
import logging
import re
import time
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor

from aragora.agents.api_agents.base import APIAgent
from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentCircuitOpenError,
    get_primary_api_key,
    upgrade_retired_model_id,
)
from aragora.agents.api_agents.openai_compatible import OpenAICompatibleMixin
from aragora.agents.registry import AgentRegistry
from aragora.agents.transports.vibeproxy import (
    ModelTransportPolicy,
    OpenAIProtocol,
    TransportMode,
    VibeProxyConfigurationError,
    VibeProxyResponseError,
    VibeProxyTimeoutError,
    VibeProxyUnavailableError,
)
from aragora.config.model_pins import GPT6_ASTRA_DIRECT, GPT6_ASTRA_VIA_OPENROUTER
from aragora.core import Message
from aragora.core_types import AgentRole
from aragora.observability.metrics.agents import (
    ErrorType,
    record_circuit_breaker_rejection,
    record_provider_call,
    record_provider_token_usage,
)

logger = logging.getLogger(__name__)

# Frontier pick for the OpenAI API agent (2026-09-04 frontier-model-refresh).
DEFAULT_MODEL = GPT6_ASTRA_DIRECT

# Pre-compiled patterns that indicate web search would be helpful
# Compiled at module load time for performance (avoids recompilation on each call)
_WEB_SEARCH_PATTERNS = [
    re.compile(r"https?://", re.IGNORECASE),  # URLs
    re.compile(r"github\.com", re.IGNORECASE),  # GitHub repos
    re.compile(r"\brepo\b", re.IGNORECASE),  # Repository mentions
    re.compile(r"\bwebsite\b", re.IGNORECASE),  # Website mentions
    re.compile(r"\bweb\s*page\b", re.IGNORECASE),  # Web page mentions
    re.compile(r"\bonline\b", re.IGNORECASE),  # Online content
    re.compile(r"\blatest\s+(news|updates?|release|releases|version|versions)\b", re.IGNORECASE),
    re.compile(r"\bcurrent\s+(events|status|market|prices?|pricing)\b", re.IGNORECASE),
    re.compile(r"\brecent\s+(news|developments|changes|updates?|articles?)\b", re.IGNORECASE),
    re.compile(r"\bnews\b", re.IGNORECASE),  # News
    re.compile(r"\barticle\b", re.IGNORECASE),  # Articles
]


# Cap for VibeProxy catalog discovery (4x the client's 1.5s connect timeout):
# bounds how long a wedged proxy can delay PREFER-mode fallback to direct.
_PROXY_DISCOVERY_TIMEOUT_SECONDS = 6.0

# Dedicated bounded executor for blocking VibeProxy legs so slow proxy
# inferences cannot starve the event loop's shared default executor.
# Threads are spawned lazily on first use.
_PROXY_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="vibeproxy-openai")


_OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _resolve_openai_base_url() -> str:
    """OPENAI_BASE_URL override for gateways/proxies (issue #9304)."""
    import os

    raw = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    if not raw:
        return _OPENAI_DEFAULT_BASE_URL
    return raw if raw.endswith("/v1") else raw + "/v1"


def _targets_official_openai_endpoint() -> bool:
    """Whether requests will actually reach ``api.openai.com``.

    Used ONLY to decide whether a retired explicit model id may be rewritten
    (finding O-P2a). Deliberately separate from
    ``self._uses_official_openai_endpoint``, which gates VibeProxy exact-chat
    routing and keeps its own "no OPENAI_BASE_URL is set at all" meaning: the
    proxy slice is contract-tested against an unconfigured client, so an env
    var naming the official endpoint is still outside it.

    The upgrade decision has no such reason to care about the raw env var --
    it cares where the request lands. Comparing the RESOLVED, normalized URL
    (as the anthropic/grok/mistral paths do) means
    ``OPENAI_BASE_URL=https://api.openai.com``, ``.../v1`` and ``.../v1/``
    all still upgrade a retired id, while any other host does not.
    """
    return _resolve_openai_base_url() == _OPENAI_DEFAULT_BASE_URL


@AgentRegistry.register(
    "openai-api",
    default_model=DEFAULT_MODEL,
    default_name="openai-api",
    agent_type="API",
    env_vars="OPENAI_API_KEY",
    accepts_api_key=True,
)
class OpenAIAPIAgent(OpenAICompatibleMixin, APIAgent):
    """Agent that uses OpenAI API directly.

    Includes automatic fallback to OpenRouter when OpenAI quota is exceeded (429 error).
    The fallback uses the same GPT model via OpenRouter's API.

    Supports web search tool for web-capable responses when URLs or web-related
    keywords are detected in the prompt.

    Uses OpenAICompatibleMixin for standard OpenAI API implementation.
    """

    # No static OPENROUTER_MODEL_MAP: QuotaFallbackMixin.get_fallback_model()
    # (aragora/agents/fallback.py) resolves the current model through the
    # catalog/upgrade-map instead, so every legacy or retired OpenAI
    # spelling (not just a hand-enumerated subset) transparently upgrades
    # to its frontier via OpenRouter.
    DEFAULT_FALLBACK_MODEL = GPT6_ASTRA_VIA_OPENROUTER

    def __init__(
        self,
        name: str = "openai-api",
        model: str = DEFAULT_MODEL,
        role: AgentRole = "proposer",
        timeout: int = 120,
        api_key: str | None = None,
        enable_fallback: bool | None = None,  # None = use config setting
        model_transport: ModelTransportPolicy | None = None,  # None = from env
        reasoning_effort: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> None:
        import os

        # VibeProxy exact-chat routing gate: unchanged raw-env-var semantics
        # (the proxy slice is contract-tested against a client with no
        # OPENAI_BASE_URL set at all).
        self._uses_official_openai_endpoint = not os.environ.get("OPENAI_BASE_URL", "").strip()
        # A retired or known-dead explicit id is upgraded before it can be
        # sent to the native endpoint (finding O-P2a); active and unknown
        # ids pass through untouched. See upgrade_retired_model_id. Skipped
        # for a custom OPENAI_BASE_URL (BYOK gateway/proxy, issue #9304):
        # that endpoint may serve ids under names the public catalog does
        # not recognize, so rewriting them would silently target the wrong
        # model on someone else's endpoint. Gated on the RESOLVED URL, not
        # raw env-var presence, so OPENAI_BASE_URL set to a spelling of the
        # official endpoint still upgrades (finding O-P2a, round 2).
        if _targets_official_openai_endpoint():
            model = upgrade_retired_model_id(model)
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key=api_key
            or get_primary_api_key("OPENAI_API_KEY", allow_openrouter_fallback=True),
            # OPENAI_BASE_URL supports BYOK gateways/proxies (issue #9304).
            base_url=_resolve_openai_base_url(),
            temperature=temperature,
            top_p=top_p,
        )
        self.agent_type = "openai"
        # Explicit per-instance override (e.g. the reviewer role passing
        # "xhigh"); falls back to the catalog's reasoning_effort_default for
        # the model when unset (see OpenAICompatibleMixin._build_payload).
        self.reasoning_effort = reasoning_effort
        # Use config setting if not explicitly provided
        if enable_fallback is None:
            from aragora.agents.fallback import get_default_fallback_enabled

            self.enable_fallback = get_default_fallback_enabled()
        else:
            self.enable_fallback = enable_fallback
        self._fallback_agent = None
        self.enable_web_search = True  # Enable web search tool by default
        self._current_prompt = ""  # Track current prompt for web search detection
        if model_transport is not None:
            # Per-instance override: callers that must stay on a fixed
            # transport (e.g. server surfaces pinning DIRECT) are immune to the
            # ambient ARAGORA_MODEL_TRANSPORT environment opt-in.
            self._model_transport_policy = model_transport
            return
        try:
            self._model_transport_policy = ModelTransportPolicy.from_env(
                default_mode=TransportMode.DIRECT
            )
        except VibeProxyConfigurationError as exc:
            # REQUIRED stays fail-closed on a bad environment; every other mode
            # degrades to the direct path so agent construction never fails for
            # callers that never touch VibeProxy.
            raw_mode = os.environ.get("ARAGORA_MODEL_TRANSPORT", "").strip().lower()
            if raw_mode == TransportMode.REQUIRED.value:
                raise
            logger.warning(
                "[%s] invalid VibeProxy transport configuration; using direct transport: %s",
                name,
                exc,
            )
            self._model_transport_policy = ModelTransportPolicy(TransportMode.DIRECT)

    def _needs_web_search(self, prompt: str) -> bool:
        """Detect if the prompt would benefit from web search.

        Returns True if the prompt contains URLs, GitHub references,
        or keywords indicating need for current/web information.
        """
        if not self.enable_web_search:
            return False

        # Use pre-compiled patterns for performance
        for pattern in _WEB_SEARCH_PATTERNS:
            if pattern.search(prompt):
                return True
        return False

    def _build_messages(self, full_prompt: str) -> list[dict]:
        """Build messages and track prompt for web search detection."""
        # Store prompt for _build_extra_payload to use
        self._current_prompt = full_prompt
        return super()._build_messages(full_prompt)

    def _build_extra_payload(self) -> dict | None:
        """Add web search tool if prompt indicates web content is needed."""
        if self._needs_web_search(self._current_prompt):
            logger.info("[%s] Enabling web search tool for web content", self.name)
            return {
                "tools": [
                    {
                        "type": "web_search",
                        "web_search": {},
                    }
                ]
            }
        return None

    def _can_route_exact_chat(self, full_prompt: str) -> bool:
        """Return whether this request is inside the contract-tested proxy slice."""

        return (
            self._model_transport_policy.mode is not TransportMode.DIRECT
            and self._uses_official_openai_endpoint
            and not self._needs_web_search(full_prompt)
        )

    def _reject_if_required_ineligible(self, reason: str) -> None:
        """REQUIRED mode is an egress boundary: never silently fall back to a
        direct api.openai.com call for requests the proxy slice cannot serve."""

        if self._model_transport_policy.mode is TransportMode.REQUIRED:
            raise AgentAPIError(
                f"vibeproxy-required cannot serve this request ({reason}); "
                "web search, tools, custom endpoints, and streaming are outside "
                "the contract-tested proxy slice",
                agent_name=self.name,
            )

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Route exact, non-streaming OpenAI Chat requests through VibeProxy.

        In PREFER mode, web search, streaming, custom endpoints, and any request
        the policy does not resolve exactly continue through the established
        direct path. In REQUIRED mode those requests fail closed instead.
        """

        full_prompt = prompt
        if context:
            full_prompt = self._build_context_prompt(context) + prompt
        if not self._can_route_exact_chat(full_prompt):
            self._reject_if_required_ineligible("web search or custom endpoint requested")
            return await super().generate(prompt, context)

        start_time = time.perf_counter()
        cb = getattr(self, "_circuit_breaker", None)
        if cb is not None and not cb.can_proceed():
            record_circuit_breaker_rejection(self.agent_type)
            record_provider_call(
                provider=self.agent_type,
                success=False,
                error_type=ErrorType.CIRCUIT_OPEN,
                latency_seconds=time.perf_counter() - start_time,
                model=self.model,
            )
            raise AgentCircuitOpenError(
                f"Circuit breaker open for {self.name} - too many recent failures",
                agent_name=self.name,
            )

        messages = self._build_messages(full_prompt)
        payload = self._build_payload(messages, stream=False)
        # Defensively keep future tool-bearing extensions on the direct path.
        if payload.get("tools"):
            self._reject_if_required_ineligible("tool-bearing payload")
            return await super().generate(prompt, context)

        estimated_budget_usd = self._estimate_budget_cost_usd(payload)
        from aragora.billing import budget_guard

        budget_guard.assert_within_budget(
            estimated_budget_usd,
            label=getattr(self, "name", None),
        )

        deadline = time.monotonic() + float(self.timeout)

        def remaining_timeout() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise VibeProxyTimeoutError("VibeProxy OpenAI request timed out")
            return remaining

        loop = asyncio.get_running_loop()
        try:
            # Blocking legs run on a dedicated bounded executor (not the shared
            # default one), and each leg computes its timeout at thread start so
            # executor queue wait consumes the deadline instead of escaping it.
            # Discovery is wall-clock bounded by wait_for — covering executor
            # queue wait, not just the socket timeout — so a wedged proxy can
            # never delay PREFER-mode fallback by more than the discovery cap.
            discovery_cap = min(remaining_timeout(), _PROXY_DISCOVERY_TIMEOUT_SECONDS)
            try:
                # asyncio.TimeoutError is distinct from builtin TimeoutError on
                # Python 3.10; catch both (they unify from 3.11 onward).
                route = await asyncio.wait_for(
                    loop.run_in_executor(
                        _PROXY_EXECUTOR,
                        lambda: self._model_transport_policy.resolve(
                            "openai",
                            self.model,
                            ("chat",),
                            timeout=discovery_cap,
                        ),
                    ),
                    timeout=discovery_cap,
                )
            except (TimeoutError, asyncio.TimeoutError) as exc:
                raise VibeProxyTimeoutError(
                    "VibeProxy discovery exceeded the wall-clock cap"
                ) from exc
            if route.transport == "direct":
                # resolve() downgrades proxy unavailability to a direct route in
                # PREFER mode; record the proxy-leg failure so a wedged proxy is
                # not metrically invisible on this path.
                if route.fallback_reason:
                    logger.warning(
                        "[%s] VibeProxy route unavailable; using direct path: %s",
                        self.name,
                        route.fallback_reason,
                    )
                    record_provider_call(
                        provider="vibeproxy",
                        success=False,
                        error_type=ErrorType.API_ERROR,
                        latency_seconds=time.perf_counter() - start_time,
                        model=self.model,
                    )
                return await super().generate(prompt, context)

            client = self._model_transport_policy.client
            if client is None:
                raise VibeProxyUnavailableError("VibeProxy client is not configured")
            proxy_payload = dict(payload)
            proxy_payload["model"] = route.resolved_model
            # The request leg is deliberately NOT wrapped in wait_for: the
            # executor job cannot be cancelled, so abandoning it on a wall-clock
            # race could run a duplicate inference (proxy completes after the
            # direct fallback starts). remaining_timeout() evaluated at thread
            # start already bounds the leg — it raises immediately if executor
            # queue wait exhausted the deadline, and otherwise caps the socket
            # wait at the remaining budget — so the caller is bounded without
            # an orphaned in-flight inference.
            data = await loop.run_in_executor(
                _PROXY_EXECUTOR,
                lambda: client.openai_request(
                    protocol=OpenAIProtocol.CHAT,
                    model=route.resolved_model,
                    payload=proxy_payload,
                    timeout=remaining_timeout(),
                ),
            )
            # A well-formed HTTP 200 whose body is malformed or empty is still
            # proxy unavailability: PREFER falls back, REQUIRED fails closed.
            # Shape surprises (choices not a list, message None, content not a
            # str) must not escape as raw TypeError/AttributeError.
            try:
                content = self._parse_response(data)
                if not isinstance(content, str) or not content.strip():
                    raise VibeProxyResponseError("VibeProxy returned an empty response")
            except VibeProxyResponseError:
                raise
            except (AgentAPIError, TypeError, AttributeError) as exc:
                raise VibeProxyResponseError(
                    "VibeProxy returned a malformed OpenAI response"
                ) from exc
        except (VibeProxyConfigurationError, VibeProxyUnavailableError) as exc:
            if self._model_transport_policy.mode is TransportMode.PREFER:
                logger.warning(
                    "[%s] VibeProxy OpenAI request unavailable; using direct path: %s",
                    self.name,
                    exc,
                )
                # Record the proxy-leg failure under its own provider label so a
                # wedged proxy is visible without skewing openai failure rates
                # (the direct fallback records its own outcome).
                record_provider_call(
                    provider="vibeproxy",
                    success=False,
                    error_type=(
                        ErrorType.TIMEOUT
                        if isinstance(exc, VibeProxyTimeoutError)
                        else ErrorType.API_ERROR
                    ),
                    latency_seconds=time.perf_counter() - start_time,
                    model=self.model,
                )
                return await super().generate(prompt, context)
            if cb is not None:
                cb.record_failure()
            record_provider_call(
                provider=self.agent_type,
                success=False,
                error_type=(
                    ErrorType.TIMEOUT
                    if isinstance(exc, VibeProxyTimeoutError)
                    else ErrorType.API_ERROR
                ),
                latency_seconds=time.perf_counter() - start_time,
                model=self.model,
            )
            raise AgentAPIError(
                f"required VibeProxy OpenAI request failed: {exc}",
                agent_name=self.name,
            ) from exc

        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0
        output_tokens = usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            input_tokens = 0
            output_tokens = 0
        usage_has_tokens = bool(input_tokens or output_tokens)
        self._record_token_usage(tokens_in=input_tokens, tokens_out=output_tokens)

        if not usage_has_tokens and estimated_budget_usd > 0:
            budget_guard.record_spend(estimated_budget_usd)
        if cb is not None:
            cb.record_success()
        # The proxy leg records under "vibeproxy" only (successes and failures
        # both), never additionally under the agent provider: one logical
        # inference must not increment two provider series.
        record_provider_call(
            provider="vibeproxy",
            success=True,
            latency_seconds=time.perf_counter() - start_time,
            model=self.model,
        )
        record_provider_token_usage(
            provider=self.agent_type,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        return content

    async def generate_stream(
        self, prompt: str, context: list[Message] | None = None
    ) -> AsyncGenerator[str, None]:
        """Streaming is outside the contract-tested proxy slice.

        PREFER mode streams through the established direct path; REQUIRED mode
        fails closed so the egress boundary also covers streaming requests.
        """

        self._reject_if_required_ineligible("streaming requested")
        async for chunk in super().generate_stream(prompt, context):
            yield chunk


__all__ = ["OpenAIAPIAgent"]
