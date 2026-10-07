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

DEEPSEEK_V4_PRO_MODEL = "deepseek/deepseek-v4-pro"
KIMI_K3_MODEL = CATALOG["kimi-k3"].openrouter_id
QWEN_3_8_MAX_MODEL = CATALOG["qwen3.8-max"].openrouter_id
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

# Fallback model chain for resilience when primary models fail
# Maps primary model -> fallback model (used after max_retries exhausted)
OPENROUTER_FALLBACK_MODELS: dict[str, str] = {
    # Qwen models -> DeepSeek
    QWEN_3_8_MAX_MODEL: DEEPSEEK_V4_PRO_MODEL,
    "qwen/qwen-2.5-72b-instruct": DEEPSEEK_V4_PRO_MODEL,
    "qwen/qwen3-235b-a22b": DEEPSEEK_V4_PRO_MODEL,
    "qwen/qwen3-max": DEEPSEEK_V4_PRO_MODEL,
    "qwen/qwen3.7-max": DEEPSEEK_V4_PRO_MODEL,
    "qwen/qwen3.5-plus-02-15": DEEPSEEK_V4_PRO_MODEL,
    # DeepSeek -> GPT-5.5 (fast, reliable). Keep legacy keys so
    # callers that pin an older OpenRouter id still get a safe fallback.
    DEEPSEEK_V4_PRO_MODEL: "openai/gpt-5.5",
    "deepseek/deepseek-chat": "openai/gpt-5.5",
    "deepseek/deepseek-chat-v3-0324": "openai/gpt-5.5",
    "deepseek/deepseek-v3.2": "openai/gpt-5.5",
    "deepseek/deepseek-v3.2-exp": "openai/gpt-5.5",
    "deepseek/deepseek-chat-v3.1": "openai/gpt-5.5",
    "deepseek/deepseek-r1": "openai/gpt-5.5",
    "deepseek/deepseek-reasoner": "openai/gpt-5.5",
    # Kimi -> Claude Opus 5
    KIMI_K3_MODEL: "anthropic/claude-opus-5",
    "moonshotai/kimi-k2.7-code": "anthropic/claude-opus-5",
    "moonshotai/kimi-k2.6": "anthropic/claude-opus-5",
    "moonshotai/kimi-k2.5": "anthropic/claude-opus-5",
    "moonshotai/kimi-k2-0905": "anthropic/claude-opus-5",
    "moonshotai/kimi-k2-thinking": "anthropic/claude-opus-5",
    "moonshot/moonshot-v1-128k": "anthropic/claude-opus-5",
    # Retired OpenRouter defaults -> live replacements. The replacement rows
    # themselves retain a separate frontier fallback for provider outages.
    "perplexity/sonar-reasoning": "perplexity/sonar-reasoning-pro",
    "perplexity/sonar-reasoning-pro": "openai/gpt-5.5",
    "cohere/command-r-plus": "cohere/command-a",
    "cohere/command-a": "openai/gpt-5.5",
    "ai21/jamba-1.6-large": "ai21/jamba-large-1.7",
    "ai21/jamba-large-1.7": "openai/gpt-5.5",
    "x-ai/grok-4": "x-ai/grok-4.5",
    "x-ai/grok-4.5": "openai/gpt-5.5",
    # Mistral -> GPT-5.5
    "mistralai/mistral-large-2411": "openai/gpt-5.5",
    "mistralai/mistral-large-2512": "openai/gpt-5.5",
    # Yi -> DeepSeek
    "01-ai/yi-large": DEEPSEEK_V4_PRO_MODEL,
    # Llama -> GPT-5.5
    "meta-llama/llama-3.3-70b-instruct": "openai/gpt-5.5",
    "meta-llama/llama-4-maverick": "openai/gpt-5.5",
    "meta-llama/llama-4-scout": "openai/gpt-5.5",
}


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
    - deepseek/deepseek-v4-pro (DeepSeek V4 Pro, 1M context)
    - meta-llama/llama-4-maverick (Llama 4 Maverick 400B MoE)
    - meta-llama/llama-4-scout (Llama 4 Scout 109B MoE)
    - meta-llama/llama-3.3-70b-instruct
    - mistralai/mistral-large-2512 (Mistral Large 3)
    - qwen/qwen3.8-max (Qwen 3.8 Max)
    - qwen/qwen3.7-max (Qwen 3.7 Max compatibility)
    - qwen/qwen3.5-plus-02-15 (Qwen3.5 Plus)
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
            fallback = OPENROUTER_FALLBACK_MODELS.get(self.model)
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
        # OpenRouter routes Claude too (OPENROUTER_MODEL_MAP targets
        # anthropic/claude-opus-5), and Opus 4.7+ reject sampling params with a
        # 400. Key off payload["model"], NOT self.model: on the quota-fallback
        # path a non-Claude primary (e.g. Kimi) is re-sent as Opus 5, and
        # self.model would still name the primary. No-ops for non-Claude models.
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
        # OpenRouter routes Claude too (OPENROUTER_MODEL_MAP targets
        # anthropic/claude-opus-5), and Opus 4.7+ reject sampling params with a
        # 400. Key off payload["model"], NOT self.model: on the quota-fallback
        # path a non-Claude primary (e.g. Kimi) is re-sent as Opus 5, and
        # self.model would still name the primary. No-ops for non-Claude models.
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
    default_model="meta-llama/llama-3.3-70b-instruct",
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Llama 3.3 70B Instruct",
)
class LlamaAgent(OpenRouterAgent):
    """Llama 3.3 70B via OpenRouter."""

    def __init__(
        self,
        name: str = "llama",
        role: AgentRole = "analyst",
        model: str = "meta-llama/llama-3.3-70b-instruct",
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
    default_model="mistralai/mistral-large-2512",
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
        model: str = "mistralai/mistral-large-2512",
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


@AgentRegistry.register(
    "qwen-3.5",
    default_model="qwen/qwen3.5-plus-02-15",
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Qwen3.5 Plus - Alibaba's latest, native multimodal, 1M context (hosted)",
)
class Qwen35PlusAgent(OpenRouterAgent):
    """Alibaba Qwen3.5 Plus via OpenRouter - native multimodal with 1M context."""

    def __init__(
        self,
        name: str = "qwen-3.5",
        role: AgentRole = "analyst",
        model: str = "qwen/qwen3.5-plus-02-15",
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "qwen-3.5"


@AgentRegistry.register(
    "yi",
    default_model="01-ai/yi-large",
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Yi Large - 01.AI's flagship model with balanced capabilities",
)
class YiAgent(OpenRouterAgent):
    """01.AI Yi Large via OpenRouter - balanced reasoning with cross-cultural perspective."""

    def __init__(
        self,
        name: str = "yi",
        role: AgentRole = "analyst",
        model: str = "01-ai/yi-large",
        system_prompt: str | None = None,
    ):
        super().__init__(
            name=name,
            role=role,
            model=model,
            system_prompt=system_prompt,
        )
        self.agent_type = "yi"


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
    default_model="moonshotai/kimi-k2-thinking",
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Kimi K2 Thinking - reasoning model that outperforms GPT-5 on agentic tasks",
)
class KimiThinkingAgent(OpenRouterAgent):
    """Moonshot AI Kimi K2 Thinking via OpenRouter - reasoning model with chain-of-thought."""

    def __init__(
        self,
        name: str = "kimi-thinking",
        role: AgentRole = "analyst",
        model: str = "moonshotai/kimi-k2-thinking",
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
    default_model="moonshot-v1-8k",
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
        model: str = "moonshot-v1-8k",
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


# === Llama 4 Models ===


@AgentRegistry.register(
    "llama4-maverick",
    default_model="meta-llama/llama-4-maverick",
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Llama 4 Maverick - 400B MoE, 1M context, native multimodal",
)
class Llama4MaverickAgent(OpenRouterAgent):
    """Meta Llama 4 Maverick via OpenRouter - 400B MoE with 1M token context."""

    def __init__(
        self,
        name: str = "llama4-maverick",
        role: AgentRole = "analyst",
        model: str = "meta-llama/llama-4-maverick",
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
    default_model="meta-llama/llama-4-scout",
    agent_type="API (OpenRouter)",
    env_vars="OPENROUTER_API_KEY",
    description="Llama 4 Scout - 109B MoE, 10M context window, multimodal",
)
class Llama4ScoutAgent(OpenRouterAgent):
    """Meta Llama 4 Scout via OpenRouter - 109B MoE with 10M token context."""

    def __init__(
        self,
        name: str = "llama4-scout",
        role: AgentRole = "analyst",
        model: str = "meta-llama/llama-4-scout",
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
    "Qwen35PlusAgent",
    "YiAgent",
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
]
