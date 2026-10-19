"""
OpenRouter agent and provider-specific subclasses.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any

import aiohttp

from aragora.agents.api_agents.base import APIAgent
from aragora.agents.errors.decorators import handle_stream_errors
from aragora.core_types import AgentRole
from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentCircuitOpenError,
    AgentConnectionError,
    AgentRateLimitError,
    AgentStreamError,
    AgentTimeoutError,
    Critique,
    Message,
    _sanitize_error_message,
    create_client_session,
    create_openai_sse_parser,
    get_api_key,
    get_trace_headers,
    handle_agent_errors,
)
from aragora.agents.api_agents.rate_limiter import get_openrouter_limiter
from aragora.agents.registry import AgentRegistry
from aragora.config import DB_TIMEOUT_SECONDS
from aragora.config.model_pins import (
    FABLE_51_VIA_OPENROUTER,
    GEMINI_31_PRO_VIA_OPENROUTER,
    GEMINI_38_FLASH_VIA_OPENROUTER,
    GPT6_ASTRA_VIA_OPENROUTER,
    GPT56_TERRA_VIA_OPENROUTER,
    GROK_46_VIA_OPENROUTER,
    MISTRAL_MEDIUM_VIA_OPENROUTER,
    OPUS_5_VIA_OPENROUTER,
)
from aragora.exceptions import ExternalServiceError
from aragora.models import CATALOG
from aragora.models.compat import strip_sampling_params
from aragora.observability.metrics.agents import (
    ErrorType,
    record_fallback_chain_depth,
    record_provider_call,
    record_provider_token_usage,
    record_rate_limit_detected,
)

logger = logging.getLogger(__name__)

DEEPSEEK_V4_PRO_MODEL = CATALOG["deepseek-v4-pro-0813"].openrouter_id
KIMI_K3_MODEL = CATALOG["kimi-k3"].openrouter_id
# Model code KimiLegacyAgent sends to api.moonshot.cn, which it calls
# directly rather than through OpenRouter. Deliberately a literal and NOT
# CATALOG["kimi-k3"].direct_id: Moonshot's own API takes its own model codes
# and no live call has confirmed it accepts a bare "kimi-k3", so substituting
# one would turn a stale-but-working default into a 404. Cost accounting is
# unaffected -- "moonshot-v1-8k" resolves through the upgrade map to the
# active, priced kimi-k3 row (tests/models/test_reachable_defaults.py).
KIMI_LEGACY_DIRECT_MODEL = "moonshot-v1-8k"
QWEN_3_8_MAX_MODEL = CATALOG["qwen3.8-2.4t-a95b"].openrouter_id
# Meta family frontier (frontier-model-refresh, 2026-09-04): supersedes the
# retired Llama 3.3/4 lines for the "llama"/"llama4-maverick"/"llama4-scout"
# registrations below (kept as distinct registry entries for backward
# compatibility even though they now share one underlying model).
MUSE_SPARK_MODEL = CATALOG["muse-spark-1.3"].openrouter_id
MISTRAL_LARGE_MODEL = CATALOG["mistral-large-2512"].openrouter_id
GLM_MODEL = CATALOG["glm-5.2"].openrouter_id
MINIMAX_MODEL = CATALOG["minimax-m3"].openrouter_id
# OpenRouter Fusion: a multi-model council+judge endpoint (panel of models +
# synthesis). It is itself a *blend*, so it must never be treated as an
# independent quorum family (see aragora.swarm.quorum_evidence) -- it is a single
# high-confidence participant/judge option, gated behind feature flags.
# Slug per the vendor page (openrouter.ai/openrouter/fusion); NOT yet
# runtime-verified against the live OpenRouter API here (no key in this env).
# Safe because the agent is gated OFF by default (see routing enforcement +
# enable_fusion) and never dispatches until explicitly enabled; confirm the slug
# and pricing (TODO in billing/usage.py) before enabling for real debates.
FUSION_MODEL = "openrouter/fusion"

# Fallback model chain for resilience when primary models fail.
# Maps primary model -> fallback model (used after max_retries exhausted).
#
# Two invariants (frontier-model-refresh, 2026-09-04):
#  1. Every VALUE is an ACTIVE catalog row. A fallback target is only useful
#     if a live request to it succeeds; the table previously routed nearly
#     everything to the now-retired "openai/gpt-5.5" (and "x-ai/grok-4"
#     retired->retired), so the resilience path itself was dead.
#  2. Every current default has a KEY. The new frontier slugs had no entry at
#     all, meaning the models the fleet actually runs had no fallback.
# A fallback should also be cross-family wherever possible: a provider outage
# that takes out the primary usually takes out its siblings too.
OPENROUTER_FALLBACK_MODELS: dict[str, str] = {
    # Qwen models -> DeepSeek
    QWEN_3_8_MAX_MODEL: DEEPSEEK_V4_PRO_MODEL,
    "qwen/qwen-2.5-72b-instruct": DEEPSEEK_V4_PRO_MODEL,
    "qwen/qwen3-235b-a22b": DEEPSEEK_V4_PRO_MODEL,
    "qwen/qwen3-max": DEEPSEEK_V4_PRO_MODEL,
    "qwen/qwen3.7-max": DEEPSEEK_V4_PRO_MODEL,
    "qwen/qwen3.5-plus-02-15": DEEPSEEK_V4_PRO_MODEL,
    # DeepSeek -> the cheap/bulk OpenAI route (fast, reliable). Keep legacy
    # keys so callers that pin an older OpenRouter id still get a safe
    # fallback.
    DEEPSEEK_V4_PRO_MODEL: GPT56_TERRA_VIA_OPENROUTER,
    # Retired spelling -> the live DeepSeek slug (same retired-to-live hop as
    # the perplexity/cohere/ai21 rows below). Restored in the 2026-09-05
    # gate-fix wave: it was the key the pre-refresh DEEPSEEK_V4_PRO_MODEL
    # constant supplied, and dropping it left every caller still pinning the
    # bare slug with no fallback at all (finding C-P2 on #9989).
    "deepseek/deepseek-v4-pro": DEEPSEEK_V4_PRO_MODEL,
    "deepseek/deepseek-chat": GPT56_TERRA_VIA_OPENROUTER,
    "deepseek/deepseek-chat-v3-0324": GPT56_TERRA_VIA_OPENROUTER,
    "deepseek/deepseek-v3.2": GPT56_TERRA_VIA_OPENROUTER,
    "deepseek/deepseek-v3.2-exp": GPT56_TERRA_VIA_OPENROUTER,
    "deepseek/deepseek-chat-v3.1": GPT56_TERRA_VIA_OPENROUTER,
    "deepseek/deepseek-r1": GPT56_TERRA_VIA_OPENROUTER,
    "deepseek/deepseek-reasoner": GPT56_TERRA_VIA_OPENROUTER,
    # Kimi -> Claude Opus 5
    KIMI_K3_MODEL: OPUS_5_VIA_OPENROUTER,
    "moonshotai/kimi-k2.7-code": OPUS_5_VIA_OPENROUTER,
    "moonshotai/kimi-k2.6": OPUS_5_VIA_OPENROUTER,
    "moonshotai/kimi-k2.5": OPUS_5_VIA_OPENROUTER,
    "moonshotai/kimi-k2-0905": OPUS_5_VIA_OPENROUTER,
    "moonshotai/kimi-k2-thinking": OPUS_5_VIA_OPENROUTER,
    "moonshot/moonshot-v1-128k": OPUS_5_VIA_OPENROUTER,
    # Retired OpenRouter defaults -> live replacements. The replacement rows
    # themselves retain a separate frontier fallback for provider outages.
    "perplexity/sonar-reasoning": "perplexity/sonar-reasoning-pro",
    "perplexity/sonar-reasoning-pro": GPT56_TERRA_VIA_OPENROUTER,
    "cohere/command-r-plus": "cohere/command-a",
    "cohere/command-a": GPT56_TERRA_VIA_OPENROUTER,
    "ai21/jamba-1.6-large": "ai21/jamba-large-1.7",
    "ai21/jamba-large-1.7": GPT56_TERRA_VIA_OPENROUTER,
    "x-ai/grok-4": GROK_46_VIA_OPENROUTER,
    "x-ai/grok-4.5": GROK_46_VIA_OPENROUTER,
    # Mistral -> the cheap/bulk OpenAI route
    "mistralai/mistral-large-2411": GPT56_TERRA_VIA_OPENROUTER,
    MISTRAL_LARGE_MODEL: GPT56_TERRA_VIA_OPENROUTER,
    MISTRAL_MEDIUM_VIA_OPENROUTER: GPT56_TERRA_VIA_OPENROUTER,
    # Yi -> DeepSeek
    "01-ai/yi-large": DEEPSEEK_V4_PRO_MODEL,
    # Llama -> the cheap/bulk OpenAI route
    "meta-llama/llama-3.3-70b-instruct": GPT56_TERRA_VIA_OPENROUTER,
    "meta-llama/llama-4-maverick": GPT56_TERRA_VIA_OPENROUTER,
    "meta-llama/llama-4-scout": GPT56_TERRA_VIA_OPENROUTER,
    # Current frontier defaults. Without these the models the fleet actually
    # runs today had no fallback entry at all.
    FABLE_51_VIA_OPENROUTER: GPT6_ASTRA_VIA_OPENROUTER,
    OPUS_5_VIA_OPENROUTER: GPT6_ASTRA_VIA_OPENROUTER,
    GPT6_ASTRA_VIA_OPENROUTER: FABLE_51_VIA_OPENROUTER,
    GPT56_TERRA_VIA_OPENROUTER: FABLE_51_VIA_OPENROUTER,
    GROK_46_VIA_OPENROUTER: GPT6_ASTRA_VIA_OPENROUTER,
    GEMINI_31_PRO_VIA_OPENROUTER: FABLE_51_VIA_OPENROUTER,
    GEMINI_38_FLASH_VIA_OPENROUTER: GPT56_TERRA_VIA_OPENROUTER,
    MUSE_SPARK_MODEL: GPT56_TERRA_VIA_OPENROUTER,
    GLM_MODEL: DEEPSEEK_V4_PRO_MODEL,
    MINIMAX_MODEL: DEEPSEEK_V4_PRO_MODEL,
}


def fallback_model_for(model: str) -> str | None:
    """OpenRouter fallback target for ``model``, or ``None`` if there is none.

    An exact ``OPENROUTER_FALLBACK_MODELS`` key wins (legacy spellings are
    deliberately kept as keys so a caller pinning an old id still gets a
    safe target). Only when the exact spelling misses does this fall back to
    the model's CURRENT spellings -- ``resolve_model_id`` plus the resolved
    row's other ids -- so a retired or renamed spelling finds its
    successor's entry instead of losing the resilience path entirely
    (finding C-P2 on #9989: ``OpenRouterAgent`` does no retired-id upgrade at
    construction, so a stale ``model`` reached this lookup verbatim).

    A target equal to ``model`` itself is never returned: falling back to the
    id that just exhausted its retries is a no-op retry loop, not resilience.
    """
    from aragora.models.catalog import spec_or_none
    from aragora.models.upgrade_map import resolve_model_id

    if not model:
        return None
    candidates: list[str] = [model]
    resolved = resolve_model_id(model)
    if resolved and resolved != model:
        candidates.append(resolved)
    spec = spec_or_none(resolved or model)
    if spec is not None:
        candidates.extend(mid for mid in spec.all_ids() if mid not in candidates)
    for candidate in candidates:
        fallback = OPENROUTER_FALLBACK_MODELS.get(candidate)
        if fallback is not None and fallback != model:
            return fallback
    return None


@AgentRegistry.register(
    "openrouter",
    default_model=DEEPSEEK_V4_PRO_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Generic OpenRouter - specify model via 'model' parameter",
)
class OpenRouterAgent(APIAgent):
    """Agent that uses OpenRouter API for access to many models.

    OpenRouter provides unified access to models like DeepSeek, Llama, Mistral,
    and others through an OpenAI-compatible API.

    Supported models (via model parameter):
    - deepseek/deepseek-v4-pro-0813 (DeepSeek V4 Pro, 1M context)
    - meta/muse-spark-1.3 (supersedes retired Llama 3.3/4 lines)
    - mistralai/mistral-large-2512 (Mistral Large 3)
    - qwen/qwen3.8-2.4t-a95b (Qwen 3.8, supersedes retired qwen3.8-max)
    - qwen/qwen3.7-max (Qwen 3.7 Max compatibility)
    - moonshotai/kimi-k3 (Kimi K3)
    - perplexity/sonar-reasoning-pro (Sonar Reasoning Pro)
    - cohere/command-a (Command A)
    - ai21/jamba-large-1.7 (Jamba Large 1.7)
    - google/gemini-3.1-pro-preview (Gemini 3.1 Pro)
    - anthropic/claude-opus-5
    - openai/gpt-5.5
    """

    def __init__(
        self,
        name: str = "openrouter",
        role: AgentRole = "proposer",
        model: str = DEEPSEEK_V4_PRO_MODEL,
        system_prompt: str | None = None,
        timeout: int = 300,
        # Generation parameters (used by SpecialistFactory and elsewhere)
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        enable_fallback: bool | None = None,
        **_kwargs: Any,
    ) -> None:
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key=get_api_key("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
            temperature=temperature,
            top_p=top_p,
        )
        self.agent_type = "openrouter"
        self.max_tokens = max_tokens  # Store for use in API calls
        if system_prompt:
            self.system_prompt = system_prompt
        else:
            # Default system prompt with language enforcement for multilingual models
            from aragora.config import DEFAULT_DEBATE_LANGUAGE, ENFORCE_RESPONSE_LANGUAGE

            if ENFORCE_RESPONSE_LANGUAGE:
                self.system_prompt = (
                    f"You are a helpful AI assistant participating in a structured debate. "
                    f"You MUST respond entirely in {DEFAULT_DEBATE_LANGUAGE}. "
                    f"Do not use any other language in your responses."
                )

    def _build_context_prompt(
        self,
        context: list[Message] | None = None,
        truncate: bool = False,
        sanitize_fn: object | None = None,
    ) -> str:
        """Build context prompt from message history.

        OpenRouter-specific: limits to 5 messages, truncates each to 500 chars.

        Args:
            context: List of previous messages
            truncate: Ignored (OpenRouter always truncates for rate limiting)
            sanitize_fn: Ignored (OpenRouter uses simple truncation)
        """
        if not context:
            return ""
        prompt = "Previous discussion:\n"
        for msg in context[-5:]:
            prompt += f"- {msg.agent} ({msg.role}): {msg.content[:500]}...\n"
        return prompt + "\n"

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using OpenRouter API with rate limiting, retry, and fallback.

        Wraps _generate_with_model via @handle_agent_errors for retry/backoff,
        then falls back to an alternate model if all retries are exhausted.
        """
        # Fail-closed monthly budget cap (no-op unless ARAGORA_MONTHLY_BUDGET_USD
        # is set). OpenRouter is the common metered fallback path, so gate here too.
        self._enforce_budget_precall()
        try:
            return await self._generate_with_model(self.model, prompt, context)
        except (AgentRateLimitError, AgentConnectionError, AgentTimeoutError):
            # All retries exhausted - try fallback model if available
            fallback = fallback_model_for(self.model)
            if fallback:
                logger.warning(
                    "OpenRouter %s exhausted retries, falling back to %s",
                    self.model,
                    fallback,
                )
                record_fallback_chain_depth(1)
                return await self._generate_with_model(fallback, prompt, context)
            raise

    @handle_agent_errors(
        max_retries=3,
        retry_delay=2.0,
        retry_backoff=2.0,
        max_delay=300.0,
        retryable_exceptions=(AgentRateLimitError, AgentConnectionError, AgentTimeoutError),
    )
    async def _generate_with_model(
        self,
        model: str,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        """Single-attempt generate for a specific model.

        The @handle_agent_errors decorator provides retry with exponential backoff
        for AgentRateLimitError, AgentConnectionError, and AgentTimeoutError.
        OpenRouter-specific rate limiter integration and metrics are handled here.
        """
        import time

        start_time = time.perf_counter()

        full_prompt = prompt
        if context:
            full_prompt = self._build_context_prompt(context) + prompt

        url = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://aragora.ai",
            "X-Title": "Aragora Multi-Agent Debate",
            **get_trace_headers(),  # Distributed tracing
        }

        messages = [{"role": "user", "content": full_prompt}]
        if self.system_prompt:
            messages.insert(0, {"role": "system", "content": self.system_prompt})

        payload: dict = {
            "model": model,
            "messages": messages,
            "max_tokens": self.max_tokens if self.max_tokens is not None else 4096,
        }

        # Apply persona generation parameters if set (for response diversity)
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            payload["frequency_penalty"] = self.frequency_penalty
        # OpenRouter routes Claude too -- get_fallback_model() (see
        # aragora/agents/fallback.py) resolves a model through the catalog and
        # upgrade map, so an Anthropic row's own openrouter_id is a live
        # fallback target -- and Opus 4.7+ reject sampling params with a 400.
        # Key off payload["model"], NOT self.model: on the quota-fallback path
        # a non-Claude primary (e.g. Kimi) is re-sent as a Claude slug, and
        # self.model would still name the primary. No-ops for non-Claude
        # models.
        strip_sampling_params(payload, payload["model"])

        # Acquire rate limit token
        limiter = get_openrouter_limiter()
        if not await limiter.acquire(timeout=DB_TIMEOUT_SECONDS):
            record_provider_call(
                provider="openrouter",
                success=False,
                error_type=ErrorType.RATE_LIMIT,
                latency_seconds=time.perf_counter() - start_time,
                model=model,
            )
            raise AgentRateLimitError(
                "OpenRouter rate limit exceeded, request timed out",
                agent_name=self.name,
            )

        try:
            async with create_client_session(timeout=self.timeout) as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                ) as response:
                    # Update rate limit state from headers
                    limiter.update_from_headers(dict(response.headers))

                    if response.status == 429:
                        # Rate limited - record and raise for decorator retry
                        backoff_delay = limiter.record_rate_limit_error(429)
                        record_rate_limit_detected("openrouter", backoff_delay)
                        record_provider_call(
                            provider="openrouter",
                            success=False,
                            error_type=ErrorType.RATE_LIMIT,
                            latency_seconds=time.perf_counter() - start_time,
                            model=model,
                        )
                        raise AgentRateLimitError(
                            f"OpenRouter rate limited (429) for {model}",
                            agent_name=self.name,
                        )

                    if response.status != 200:
                        error_text = await response.text()
                        sanitized = _sanitize_error_message(error_text)
                        record_provider_call(
                            provider="openrouter",
                            success=False,
                            error_type=ErrorType.API_ERROR,
                            latency_seconds=time.perf_counter() - start_time,
                            model=model,
                        )
                        raise AgentAPIError(
                            f"OpenRouter API error {response.status}: {sanitized}",
                            agent_name=self.name,
                            status_code=response.status,
                        )

                    data = await response.json()

                    # Record token usage for billing (OpenAI format)
                    usage = data.get("usage", {})
                    input_tokens = usage.get("prompt_tokens", 0)
                    output_tokens = usage.get("completion_tokens", 0)
                    self._record_token_usage(
                        tokens_in=input_tokens,
                        tokens_out=output_tokens,
                    )

                    try:
                        content = data["choices"][0]["message"]["content"]
                    except (KeyError, IndexError):
                        record_provider_call(
                            provider="openrouter",
                            success=False,
                            error_type=ErrorType.API_ERROR,
                            latency_seconds=time.perf_counter() - start_time,
                            model=model,
                        )
                        raise AgentAPIError(
                            f"Unexpected OpenRouter response format: {data}",
                            agent_name=self.name,
                        )

                    # Validate content is non-empty
                    if not content or not content.strip():
                        record_provider_call(
                            provider="openrouter",
                            success=False,
                            error_type=ErrorType.API_ERROR,
                            latency_seconds=time.perf_counter() - start_time,
                            model=model,
                        )
                        raise AgentAPIError(
                            f"Model {model} returned empty response",
                            agent_name=self.name,
                        )

                    # Success - reset backoff state
                    limiter.record_success()

                    # Record successful provider metrics
                    latency = time.perf_counter() - start_time
                    record_provider_call(
                        provider="openrouter",
                        success=True,
                        latency_seconds=latency,
                        model=model,
                    )
                    record_provider_token_usage(
                        provider="openrouter",
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    )

                    record_fallback_chain_depth(0)

                    return content
        except (AgentAPIError, AgentRateLimitError):
            raise  # Re-raise for decorator handling
        except aiohttp.ClientError:
            limiter.release_on_error()
            raise  # Decorator transforms to AgentConnectionError
        except asyncio.TimeoutError:
            limiter.release_on_error()
            raise  # Decorator transforms to AgentTimeoutError

    @handle_stream_errors()
    async def generate_stream(
        self, prompt: str, context: list[Message] | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from OpenRouter API with rate limiting, retry, and circuit breaker.

        Yields chunks of text as they arrive from the API using SSE.
        Implements retry logic with exponential backoff for 429 rate limit errors.
        Circuit breaker prevents cascading failures when the API is consistently down.
        The @handle_stream_errors decorator wraps streaming iteration errors.
        """
        # Check circuit breaker before streaming (fail fast)
        if self._circuit_breaker is not None and not self._circuit_breaker.can_proceed():
            raise AgentCircuitOpenError(
                f"Circuit breaker open for {self.name} streaming - too many recent failures",
                agent_name=self.name,
            )

        max_retries = 3
        base_delay = 2.0

        full_prompt = prompt
        if context:
            full_prompt = self._build_context_prompt(context) + prompt

        url = f"{self.base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://aragora.ai",
            "X-Title": "Aragora Multi-Agent Debate",
            **get_trace_headers(),  # Distributed tracing
        }

        messages = [{"role": "user", "content": full_prompt}]
        if self.system_prompt:
            messages.insert(0, {"role": "system", "content": self.system_prompt})

        payload: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "stream": True,
        }

        # Apply persona generation parameters if set (for response diversity)
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.top_p is not None:
            payload["top_p"] = self.top_p
        if self.frequency_penalty is not None:
            payload["frequency_penalty"] = self.frequency_penalty
        # OpenRouter routes Claude too -- get_fallback_model() (see
        # aragora/agents/fallback.py) resolves a model through the catalog and
        # upgrade map, so an Anthropic row's own openrouter_id is a live
        # fallback target -- and Opus 4.7+ reject sampling params with a 400.
        # Key off payload["model"], NOT self.model: on the quota-fallback path
        # a non-Claude primary (e.g. Kimi) is re-sent as a Claude slug, and
        # self.model would still name the primary. No-ops for non-Claude
        # models.
        strip_sampling_params(payload, payload["model"])

        estimated_budget_usd = self._estimate_budget_cost_from_text_usd(
            full_prompt,
            int(payload["max_tokens"]),
        )
        self._enforce_budget_precall(estimated_budget_usd)
        from aragora.billing import budget_guard

        last_error = None
        for attempt in range(max_retries):
            # Acquire rate limit token for each attempt
            limiter = get_openrouter_limiter()
            if not await limiter.acquire(timeout=DB_TIMEOUT_SECONDS):
                raise AgentRateLimitError(
                    "OpenRouter rate limit exceeded, request timed out",
                    agent_name=self.name,
                )

            try:
                async with create_client_session(timeout=self.timeout) as session:
                    async with session.post(
                        url,
                        headers=headers,
                        json=payload,
                    ) as response:
                        # Update rate limit state from headers
                        limiter.update_from_headers(dict(response.headers))

                        if response.status == 429:
                            # Rate limited - use centralized backoff
                            backoff_delay = limiter.record_rate_limit_error(429)

                            # Check for Retry-After header override
                            retry_after_header = response.headers.get("Retry-After")
                            if retry_after_header:
                                try:
                                    wait_time = min(float(retry_after_header), 300)
                                except ValueError:
                                    wait_time = min(backoff_delay, 300)
                            else:
                                wait_time = min(backoff_delay, 300)

                            if attempt < max_retries - 1:
                                logger.warning(
                                    f"OpenRouter streaming rate limited (429), waiting {wait_time:.0f}s before retry {attempt + 2}/{max_retries}"
                                )
                                await asyncio.sleep(wait_time)
                                last_error = "Rate limited (429)"
                                continue
                            else:
                                if self._circuit_breaker is not None:
                                    self._circuit_breaker.record_failure()
                                raise AgentRateLimitError(
                                    f"OpenRouter streaming rate limited (429) after {max_retries} retries",
                                    agent_name=self.name,
                                )

                        if response.status != 200:
                            error_text = await response.text()
                            sanitized = _sanitize_error_message(error_text)
                            if self._circuit_breaker is not None:
                                self._circuit_breaker.record_failure()
                            raise AgentStreamError(
                                f"OpenRouter streaming API error {response.status}: {sanitized}",
                                agent_name=self.name,
                            )

                        # Use SSEStreamParser for consistent SSE parsing (OpenAI-compatible)
                        try:
                            parser = create_openai_sse_parser()
                            async for content in parser.parse_stream(response.content, self.name):
                                yield content
                            # Success - reset backoff state and circuit breaker
                            limiter.record_success()
                            if self._circuit_breaker is not None:
                                self._circuit_breaker.record_success()
                            if estimated_budget_usd > 0:
                                budget_guard.record_spend(estimated_budget_usd)
                        except RuntimeError as e:
                            if self._circuit_breaker is not None:
                                self._circuit_breaker.record_failure()
                            raise AgentStreamError(str(e), agent_name=self.name)
                        # Successfully streamed - exit retry loop
                        return

            except aiohttp.ClientError as e:
                limiter.release_on_error()
                last_error = str(e)
                if attempt < max_retries - 1:
                    wait_time = base_delay * (2**attempt)
                    logger.warning(
                        "OpenRouter streaming connection error, waiting %.0fs before retry: %s",
                        wait_time,
                        e,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
                raise AgentConnectionError(
                    f"OpenRouter streaming failed after {max_retries} retries: {last_error}",
                    agent_name=self.name,
                    cause=e,
                )

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique a proposal using OpenRouter API."""
        target_desc = f" from {target_agent}" if target_agent else ""
        critique_prompt = f"""Critically analyze this proposal{target_desc}:

Task: {task}
Proposal: {proposal}

Format your response as:
ISSUES:
- issue 1
- issue 2

SUGGESTIONS:
- suggestion 1
- suggestion 2

SEVERITY: X.X
REASONING: explanation"""

        response = await self.generate(critique_prompt, context)
        return self._parse_critique(response, target_agent or "proposal", proposal)


# Convenience aliases for specific OpenRouter models
@AgentRegistry.register(
    "deepseek",
    default_model=DEEPSEEK_V4_PRO_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="DeepSeek V4 Pro via OpenRouter - frontier long-context model",
)
class DeepSeekAgent(OpenRouterAgent):
    """DeepSeek V4 Pro via OpenRouter - frontier long-context model."""

    def __init__(
        self,
        name: str = "deepseek",
        role: AgentRole = "analyst",
        model: str = DEEPSEEK_V4_PRO_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "deepseek"


@AgentRegistry.register(
    "deepseek-r1",
    default_model=DEEPSEEK_V4_PRO_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="DeepSeek V4 Pro via OpenRouter - reasoning-capable compatibility alias",
)
class DeepSeekReasonerAgent(OpenRouterAgent):
    """Compatibility alias for DeepSeek V4 Pro via OpenRouter."""

    def __init__(
        self,
        name: str = "deepseek-r1",
        role: AgentRole = "analyst",
        model: str = DEEPSEEK_V4_PRO_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "deepseek-r1"


class DeepSeekV3Agent(OpenRouterAgent):
    """Compatibility alias for DeepSeek V4 Pro via OpenRouter."""

    def __init__(
        self,
        name: str = "deepseek-v3",
        role: AgentRole = "analyst",
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=DEEPSEEK_V4_PRO_MODEL,
            system_prompt=system_prompt,
        )
        self.agent_type = "deepseek-v3"


@AgentRegistry.register(
    "llama",
    default_model=MUSE_SPARK_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Meta Muse Spark 1.3 (supersedes retired Llama 3.3 70B Instruct)",
)
class LlamaAgent(OpenRouterAgent):
    """Meta Muse Spark 1.3 via OpenRouter (frontier-model-refresh, 2026-09-04;
    supersedes the retired Llama 3.3 70B Instruct)."""

    def __init__(
        self,
        name: str = "llama",
        role: AgentRole = "analyst",
        model: str = MUSE_SPARK_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "llama"


@AgentRegistry.register(
    "mistral",
    default_model=MISTRAL_LARGE_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Mistral Large 3 - 675B MoE, 256K context, multimodal",
)
class MistralAgent(OpenRouterAgent):
    """Mistral Large 3 via OpenRouter - 675B MoE with 256K context."""

    def __init__(
        self,
        name: str = "mistral",
        role: AgentRole = "analyst",
        model: str = MISTRAL_LARGE_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "mistral"


@AgentRegistry.register(
    "qwen",
    default_model=QWEN_3_8_MAX_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Qwen 3.8 Max - Alibaba's frontier model with 1M context",
)
class QwenAgent(OpenRouterAgent):
    """Alibaba Qwen 3.8 Max via OpenRouter."""

    def __init__(
        self,
        name: str = "qwen",
        role: AgentRole = "analyst",
        model: str = QWEN_3_8_MAX_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "qwen"


@AgentRegistry.register(
    "qwen-max",
    default_model=QWEN_3_8_MAX_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Qwen 3.8 Max - Alibaba's frontier model with 1M context",
)
class QwenMaxAgent(OpenRouterAgent):
    """Alibaba Qwen 3.8 Max via OpenRouter."""

    def __init__(
        self,
        name: str = "qwen-max",
        role: AgentRole = "analyst",
        model: str = QWEN_3_8_MAX_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "qwen-max"


# NOTE (frontier-model-refresh, 2026-09-04): the "qwen-3.5" (Qwen3.5 Plus,
# qwen/qwen3.5-plus-02-15) and "yi" (01.AI Yi Large, 01-ai/yi-large)
# registrations were removed here. Qwen3.5 Plus is superseded by
# qwen3.8-2.4t-a95b (see QwenAgent/QwenMaxAgent above); Yi Large is retired
# with no catalog row. Both spellings still resolve via
# aragora.models.upgrade_map.resolve_model_id / OPENROUTER_FALLBACK_MODELS
# for any caller still pinning them.


@AgentRegistry.register(
    "kimi",
    default_model=KIMI_K3_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Kimi K3 - Moonshot AI's frontier multimodal reasoning model on OpenRouter",
)
class KimiK3Agent(OpenRouterAgent):
    """Moonshot AI Kimi K3 via OpenRouter."""

    def __init__(
        self,
        name: str = "kimi",
        role: AgentRole = "analyst",
        model: str = KIMI_K3_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "kimi"


# Public compatibility for callers importing the pre-K3 class name.
KimiK2Agent = KimiK3Agent


@AgentRegistry.register(
    "kimi-thinking",
    default_model=KIMI_K3_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description=(
        "Kimi K3 (supersedes retired Kimi K2 Thinking; frontier-model-refresh, 2026-09-04)"
    ),
)
class KimiThinkingAgent(OpenRouterAgent):
    """Moonshot AI Kimi K3 via OpenRouter (supersedes the retired Kimi K2 Thinking)."""

    def __init__(
        self,
        name: str = "kimi-thinking",
        role: AgentRole = "analyst",
        model: str = KIMI_K3_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "kimi-thinking"


# Legacy Kimi agent using direct Moonshot API (requires KIMI_API_KEY)
@AgentRegistry.register(
    "kimi-legacy",
    default_model=KIMI_LEGACY_DIRECT_MODEL,
    agent_type="API (Kimi/Moonshot)",
    env_vars="KIMI_API_KEY",
    description="Kimi Legacy - direct Moonshot API (requires KIMI_API_KEY)",
)
class KimiLegacyAgent(APIAgent):
    """Moonshot AI Kimi - strong reasoning and Chinese language capabilities.

    Uses Moonshot's OpenAI-compatible API directly.
    """

    def __init__(
        self,
        name: str = "kimi",
        role: AgentRole = "analyst",
        model: str = KIMI_LEGACY_DIRECT_MODEL,
        system_prompt: str | None = None,
        api_key: str | None = None,
    ):
        super().__init__(name=name, model=model, role=role)
        self.system_prompt = system_prompt or ""
        resolved_api_key = api_key or get_api_key("KIMI_API_KEY")
        if not resolved_api_key:
            raise ValueError("KIMI_API_KEY environment variable not set")
        self.api_key = resolved_api_key
        self.base_url = "https://api.moonshot.cn/v1"
        self.agent_type = "kimi"

    async def generate(self, prompt: str, context: list | None = None) -> str:
        """Generate response using Moonshot API."""

        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        # Add context
        context_str = self._build_context_prompt(context)
        if context_str:
            messages.append({"role": "user", "content": context_str})

        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **get_trace_headers(),  # Distributed tracing
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
        }

        async with create_client_session(timeout=self.timeout) as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise ExternalServiceError(
                        service="Kimi API", reason=error_text, status_code=response.status
                    )

                data = await response.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError):
                    raise ExternalServiceError(
                        service="Kimi API",
                        reason=f"Unexpected response format: {data}",
                        status_code=response.status,
                    )

                # Validate content is non-empty
                if not content or not content.strip():
                    raise AgentAPIError(
                        "Kimi returned empty response",
                        agent_name=self.name,
                    )
                return content

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique a proposal using Kimi/Moonshot API."""
        target_desc = f" from {target_agent}" if target_agent else ""
        critique_prompt = f"""Critically analyze this proposal{target_desc}:

Task: {task}
Proposal: {proposal}

Format your response as:
ISSUES:
- issue 1
- issue 2

SUGGESTIONS:
- suggestion 1
- suggestion 2

SEVERITY: X.X
REASONING: explanation"""

        response = await self.generate(critique_prompt, context)
        return self._parse_critique(response, target_agent or "proposal", proposal)


# === Llama 4 Models (superseded 2026-09-04 by Meta Muse Spark 1.3) ===


@AgentRegistry.register(
    "llama4-maverick",
    default_model=MUSE_SPARK_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Meta Muse Spark 1.3 (supersedes retired Llama 4 Maverick)",
)
class Llama4MaverickAgent(OpenRouterAgent):
    """Meta Muse Spark 1.3 via OpenRouter (supersedes the retired Llama 4 Maverick)."""

    def __init__(
        self,
        name: str = "llama4-maverick",
        role: AgentRole = "analyst",
        model: str = MUSE_SPARK_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "llama4-maverick"


@AgentRegistry.register(
    "llama4-scout",
    default_model=MUSE_SPARK_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Meta Muse Spark 1.3 (supersedes retired Llama 4 Scout)",
)
class Llama4ScoutAgent(OpenRouterAgent):
    """Meta Muse Spark 1.3 via OpenRouter (supersedes the retired Llama 4 Scout)."""

    def __init__(
        self,
        name: str = "llama4-scout",
        role: AgentRole = "analyst",
        model: str = MUSE_SPARK_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "llama4-scout"


# === Perplexity Sonar Models ===


@AgentRegistry.register(
    "sonar",
    default_model="perplexity/sonar-reasoning-pro",
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Perplexity Sonar Reasoning Pro - reasoning with live web search",
)
class SonarAgent(OpenRouterAgent):
    """Perplexity Sonar Reasoning Pro via OpenRouter with live web search."""

    def __init__(
        self,
        name: str = "sonar",
        role: AgentRole = "analyst",
        model: str = "perplexity/sonar-reasoning-pro",
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "sonar"


# === Cohere Command Models ===


@AgentRegistry.register(
    "command-r",
    default_model="cohere/command-a",
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Cohere Command A - tool use, RAG, and enterprise agents",
)
class CommandRAgent(OpenRouterAgent):
    """Cohere Command A via OpenRouter - optimized for tool use and RAG."""

    def __init__(
        self,
        name: str = "command-r",
        role: AgentRole = "analyst",
        model: str = "cohere/command-a",
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "command-r"


# === AI21 Jamba Models ===


@AgentRegistry.register(
    "jamba",
    default_model="ai21/jamba-large-1.7",
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="AI21 Jamba Large 1.7 - SSM-Transformer hybrid, 256K context",
)
class JambaAgent(OpenRouterAgent):
    """AI21 Jamba Large 1.7 via OpenRouter - hybrid architecture with 256K context."""

    def __init__(
        self,
        name: str = "jamba",
        role: AgentRole = "analyst",
        model: str = "ai21/jamba-large-1.7",
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "jamba"


@AgentRegistry.register(
    "fusion",
    default_model=FUSION_MODEL,
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="OpenRouter Fusion - multi-model council+judge endpoint (high cost, high confidence)",
)
class FusionAgent(OpenRouterAgent):
    """OpenRouter Fusion via OpenRouter - a multi-model council that runs a panel
    of models plus a judge and returns a synthesized answer.

    Inherits OpenRouterAgent's resilience (circuit breaker, rate limiting, token
    tracking, streaming) for free. It is ~4-5x the cost/latency of a single model
    and is opt-in only -- callers gate it behind the ``enable_fusion`` feature
    flag and a budget cap. Because Fusion blends multiple families internally, it
    is NOT a distinct quorum reviewer family.
    """

    def __init__(
        self,
        name: str = "fusion",
        role: AgentRole = "analyst",
        model: str = FUSION_MODEL,
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "fusion"


__all__ = [
    "OpenRouterAgent",
    "DeepSeekAgent",
    "DeepSeekReasonerAgent",
    "DeepSeekV3Agent",
    "LlamaAgent",
    "MistralAgent",
    "QwenAgent",
    "QwenMaxAgent",
    "KimiK3Agent",
    "KimiK2Agent",
    "KimiThinkingAgent",
    "KimiLegacyAgent",
    "Llama4MaverickAgent",
    "Llama4ScoutAgent",
    "SonarAgent",
    "CommandRAgent",
    "JambaAgent",
    "FusionAgent",
    "FUSION_MODEL",
    "OPENROUTER_FALLBACK_MODELS",
    "fallback_model_for",
]
