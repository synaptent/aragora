"""
OpenAI-compatible API agent mixin.

Provides common implementation for agents using OpenAI-compatible APIs:
- OpenAI
- Grok (xAI)
- OpenRouter (and its model variants)
- Any other OpenAI-compatible endpoint

This eliminates ~150 lines of duplicate code per agent.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol, cast
from collections.abc import AsyncGenerator

from aragora.core import Critique, Message

if TYPE_CHECKING:
    pass


class _APIAgentProtocol(Protocol):
    """Protocol describing methods expected from APIAgent in the MRO.

    This enables proper typing for super() calls in OpenAICompatibleMixin,
    which is designed to be used with classes that inherit from APIAgent.
    """

    def _record_token_usage(self, tokens_in: int, tokens_out: int) -> None: ...

    def _build_context_prompt(
        self,
        context: list[Message] | None = None,
        truncate: bool = False,
        sanitize_fn: object | None = None,
    ) -> str: ...

    def _parse_critique(
        self,
        response: str,
        target_agent: str,
        target_content: str,
    ) -> Critique: ...


from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentCircuitOpenError,
    AgentConnectionError,
    AgentRateLimitError,
    AgentStreamError,
    AgentTimeoutError,
    _sanitize_error_message,
    create_client_session,
    create_openai_sse_parser,
    get_trace_headers,
    handle_agent_errors,
)
from aragora.agents.fallback import QuotaFallbackMixin
from aragora.observability.metrics.agents import (
    ErrorType,
    record_circuit_breaker_rejection,
    record_fallback_triggered,
    record_provider_call,
    record_provider_token_usage,
    record_rate_limit_detected,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleMixin(QuotaFallbackMixin):
    """
    Mixin providing OpenAI-compatible API implementation.

    Subclasses must define:
    - OPENROUTER_MODEL_MAP: dict mapping models to OpenRouter equivalents
    - DEFAULT_FALLBACK_MODEL: default OpenRouter model for fallback
    - agent_type: str identifying the agent type
    - base_url: API base URL
    - api_key: API key

    Optional overrides:
    - _build_extra_headers(): Add provider-specific headers
    - _build_extra_payload(): Add provider-specific payload fields
    - max_tokens: Default 4096
    """

    # Subclasses should define these
    OPENROUTER_MODEL_MAP: dict[str, str] = {}
    DEFAULT_FALLBACK_MODEL: str = "openai/gpt-5.3"

    # Default max tokens (can be overridden)
    max_tokens: int = 4096

    # Expected from base class (APIAgent) - declared for type checking
    api_key: str | None
    base_url: str | None
    model: str
    name: str
    agent_type: str
    timeout: int

    def _record_token_usage(self, tokens_in: int, tokens_out: int) -> None:
        """Record token usage (delegates to APIAgent base class).

        This mixin uses cooperative inheritance via super(). The type checker
        cannot verify that the MRO will include APIAgent, but the class is
        designed to be mixed with APIAgent-derived classes only.
        """
        # super() returns the next class in MRO which should be APIAgent or a subclass
        cast(Any, super())._record_token_usage(tokens_in, tokens_out)

    # Methods inherited from CritiqueMixin (via APIAgent) - delegate to parent
    def _build_context_prompt(
        self,
        context: list[Message] | None = None,
        truncate: bool = False,
        sanitize_fn: object | None = None,
    ) -> str:
        """Build context from previous messages (delegates to CritiqueMixin).

        This mixin uses cooperative inheritance via super(). The type checker
        cannot verify that the MRO will include CritiqueMixin, but the class is
        designed to be mixed with APIAgent-derived classes only.
        """
        # super() returns the next class in MRO which should include CritiqueMixin
        return cast(Any, super())._build_context_prompt(context, truncate, sanitize_fn)

    def _parse_critique(
        self,
        response: str,
        target_agent: str,
        target_content: str,
    ) -> Critique:
        """Parse critique response (delegates to CritiqueMixin).

        This mixin uses cooperative inheritance via super(). The type checker
        cannot verify that the MRO will include CritiqueMixin, but the class is
        designed to be mixed with APIAgent-derived classes only.
        """
        # super() returns the next class in MRO which should include CritiqueMixin
        return cast(Any, super())._parse_critique(response, target_agent, target_content)

    def _build_headers(self) -> dict:
        """Build request headers. Override to add provider-specific headers."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **get_trace_headers(),  # Distributed tracing
        }
        extra = self._build_extra_headers()
        if extra:
            headers.update(extra)
        return headers

    def _build_extra_headers(self) -> dict | None:
        """Override to add provider-specific headers."""
        return None

    def _build_messages(self, full_prompt: str) -> list[dict]:
        """Build messages array with optional system prompt."""
        messages = [{"role": "user", "content": full_prompt}]
        if hasattr(self, "system_prompt") and self.system_prompt:
            messages.insert(0, {"role": "system", "content": self.system_prompt})
        return messages

    def _build_payload(self, messages: list[dict], stream: bool = False) -> dict:
        """Build request payload. Override to add provider-specific fields."""
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
        }
        if stream:
            payload["stream"] = True

        # Apply generation parameters from persona if set (from APIAgent)
        if hasattr(self, "temperature") and self.temperature is not None:
            payload["temperature"] = self.temperature
        if hasattr(self, "top_p") and self.top_p is not None:
            payload["top_p"] = self.top_p
        if hasattr(self, "frequency_penalty") and self.frequency_penalty is not None:
            payload["frequency_penalty"] = self.frequency_penalty

        extra = self._build_extra_payload()
        if extra:
            payload.update(extra)
        return payload

    def _build_extra_payload(self) -> dict | None:
        """Override to add provider-specific payload fields."""
        return None

    def _parse_response(self, data: dict) -> str:
        """Parse response content from API response."""
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            raise AgentAPIError(
                f"Unexpected {self.agent_type} response format: {data}",
                agent_name=self.name,
            )

    def _get_endpoint_url(self) -> str:
        """Get the chat completions endpoint URL."""
        return f"{self.base_url}/chat/completions"

    def _get_error_prefix(self) -> str:
        """Get error message prefix for this agent type."""
        return self.agent_type.title() if hasattr(self, "agent_type") else "API"

    @handle_agent_errors(
        max_retries=3,
        retry_delay=1.0,
        retry_backoff=2.0,
        retryable_exceptions=(AgentRateLimitError, AgentConnectionError, AgentTimeoutError),
    )
    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using the OpenAI-compatible API.

        Includes circuit breaker protection to prevent cascading failures.
        Records per-provider metrics for monitoring.
        """
        import time

        start_time = time.perf_counter()

        if not self.api_key:
            logger.warning(
                "[%s] Missing API key, attempting OpenRouter fallback",
                getattr(self, "name", "agent"),
            )
            record_provider_call(
                provider=self.agent_type,
                success=False,
                error_type=ErrorType.AUTH,
                model=self.model,
            )
            record_fallback_triggered(
                primary_provider=self.agent_type,
                fallback_provider="openrouter",
                trigger_reason="auth",
            )
            result = await self.fallback_generate(prompt, context, status_code=401)
            if result is not None:
                return result
            raise AgentAPIError(
                f"{self._get_error_prefix()} API key not configured",
                agent_name=self.name,
                status_code=401,
            )

        # Check circuit breaker before attempting API call
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

        full_prompt = prompt
        if context:
            full_prompt = self._build_context_prompt(context) + prompt
        url = self._get_endpoint_url()
        headers = self._build_headers()
        messages = self._build_messages(full_prompt)
        payload = self._build_payload(messages, stream=False)

        try:
            # Use shared connection pool for better resource management
            async with create_client_session(timeout=self.timeout) as session:

                async def _post_payload(request_payload: dict) -> tuple[dict | None, str | None]:
                    async with session.post(
                        url,
                        headers=headers,
                        json=request_payload,
                    ) as response:
                        if response.status != 200:
                            error_text = await response.text()
                            sanitized = _sanitize_error_message(error_text)

                            # Record failure for circuit breaker (non-quota errors)
                            if cb is not None and not self.is_quota_error(
                                response.status, error_text
                            ):
                                cb.record_failure()

                            # Determine error type for metrics
                            error_type = ErrorType.API_ERROR
                            if response.status == 429:
                                error_type = ErrorType.RATE_LIMIT
                                record_rate_limit_detected(self.agent_type)
                            elif response.status in (401, 403):
                                error_type = ErrorType.AUTH
                            elif self.is_quota_error(response.status, error_text):
                                error_type = ErrorType.QUOTA

                            if response.status in (401, 403):
                                record_fallback_triggered(
                                    primary_provider=self.agent_type,
                                    fallback_provider="openrouter",
                                    trigger_reason="auth",
                                )
                                result = await self.fallback_generate(
                                    prompt, context, status_code=response.status
                                )
                                if result is not None:
                                    return None, result

                            # Check for quota/billing errors and fallback
                            if self.is_quota_error(response.status, error_text):
                                record_fallback_triggered(
                                    primary_provider=self.agent_type,
                                    fallback_provider="openrouter",
                                    trigger_reason="quota",
                                )
                                result = await self.fallback_generate(
                                    prompt, context, response.status
                                )
                                if result is not None:
                                    return None, result

                            # Record the failed call metric
                            record_provider_call(
                                provider=self.agent_type,
                                success=False,
                                error_type=error_type,
                                latency_seconds=time.perf_counter() - start_time,
                                model=self.model,
                            )

                            raise AgentAPIError(
                                f"{self._get_error_prefix()} API error {response.status}: {sanitized}",
                                agent_name=self.name,
                                status_code=response.status,
                            )

                        return await response.json(), None

                data, fallback_result = await _post_payload(payload)
                if fallback_result is not None:
                    return fallback_result
                if data is None:
                    record_provider_call(
                        provider=self.agent_type,
                        success=False,
                        error_type=ErrorType.API_ERROR,
                        latency_seconds=time.perf_counter() - start_time,
                        model=self.model,
                    )
                    raise AgentAPIError(
                        f"{self._get_error_prefix()} returned empty response",
                        agent_name=self.name,
                    )

                message = None
                try:
                    message = data.get("choices", [{}])[0].get("message", {})
                except (AttributeError, IndexError, TypeError):
                    message = {}

                tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
                content_hint = message.get("content") if isinstance(message, dict) else None
                if tool_calls and (content_hint is None or not str(content_hint).strip()):
                    logger.warning(
                        "[%s] Tool call returned empty content; retrying without tools",
                        getattr(self, "name", "agent"),
                    )
                    retry_payload = dict(payload)
                    retry_payload.pop("tools", None)
                    retry_payload["tool_choice"] = "none"
                    data, fallback_result = await _post_payload(retry_payload)
                    if fallback_result is not None:
                        return fallback_result
                    if data is None:
                        record_provider_call(
                            provider=self.agent_type,
                            success=False,
                            error_type=ErrorType.API_ERROR,
                            latency_seconds=time.perf_counter() - start_time,
                            model=self.model,
                        )
                        raise AgentAPIError(
                            f"{self._get_error_prefix()} returned empty response",
                            agent_name=self.name,
                        )

                # Record token usage for billing (OpenAI format)
                usage = data.get("usage", {})
                input_tokens = usage.get("prompt_tokens", 0)
                output_tokens = usage.get("completion_tokens", 0)
                self._record_token_usage(
                    tokens_in=input_tokens,
                    tokens_out=output_tokens,
                )

                content = self._parse_response(data)
                if not content or not content.strip():
                    if cb is not None:
                        cb.record_failure()
                    record_provider_call(
                        provider=self.agent_type,
                        success=False,
                        error_type=ErrorType.API_ERROR,
                        latency_seconds=time.perf_counter() - start_time,
                        model=self.model,
                    )
                    raise AgentAPIError(
                        f"{self._get_error_prefix()} returned empty response",
                        agent_name=self.name,
                    )

                # Record success for circuit breaker
                if cb is not None:
                    cb.record_success()

                # Record successful provider metrics
                latency = time.perf_counter() - start_time
                record_provider_call(
                    provider=self.agent_type,
                    success=True,
                    latency_seconds=latency,
                    model=self.model,
                )
                record_provider_token_usage(
                    provider=self.agent_type,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )

                return content
        except (AgentAPIError, AgentCircuitOpenError):
            raise  # Re-raise without double-recording
        except asyncio.TimeoutError:
            # Record failure for timeout errors
            if cb is not None:
                cb.record_failure()
            record_provider_call(
                provider=self.agent_type,
                success=False,
                error_type=ErrorType.TIMEOUT,
                latency_seconds=time.perf_counter() - start_time,
                model=self.model,
            )
            raise
        except (OSError, ValueError, TypeError, RuntimeError):
            # Record failure for unexpected errors
            if cb is not None:
                cb.record_failure()
            record_provider_call(
                provider=self.agent_type,
                success=False,
                error_type=ErrorType.UNKNOWN,
                latency_seconds=time.perf_counter() - start_time,
                model=self.model,
            )
            raise

    async def generate_stream(
        self, prompt: str, context: list[Message] | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from the OpenAI-compatible API."""
        if not self.api_key:
            logger.warning(
                "[%s] Missing API key, attempting OpenRouter streaming fallback",
                getattr(self, "name", "agent"),
            )
            async for chunk in self.fallback_generate_stream(prompt, context, status_code=401):
                yield chunk
            raise AgentAPIError(
                f"{self._get_error_prefix()} API key not configured",
                agent_name=self.name,
                status_code=401,
            )

        full_prompt = prompt
        if context:
            full_prompt = self._build_context_prompt(context) + prompt
        url = self._get_endpoint_url()
        headers = self._build_headers()
        messages = self._build_messages(full_prompt)
        payload = self._build_payload(messages, stream=True)

        # Use shared connection pool for better resource management
        async with create_client_session(timeout=self.timeout) as session:
            async with session.post(
                url,
                headers=headers,
                json=payload,
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    sanitized = _sanitize_error_message(error_text)

                    if response.status in (401, 403):
                        async for chunk in self.fallback_generate_stream(
                            prompt, context, status_code=response.status
                        ):
                            yield chunk
                        return

                    # Check for quota errors and fallback
                    if self.is_quota_error(response.status, error_text):
                        async for chunk in self.fallback_generate_stream(
                            prompt, context, response.status
                        ):
                            yield chunk
                        return

                    raise AgentStreamError(
                        f"{self._get_error_prefix()} streaming API error {response.status}: {sanitized}",
                        agent_name=self.name,
                    )

                # Use SSE parser for consistent streaming
                try:
                    parser = create_openai_sse_parser()
                    async for content in parser.parse_stream(response.content, self.name):
                        yield content
                except RuntimeError as e:
                    raise AgentStreamError(str(e), agent_name=self.name)

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        """Critique a proposal using the API."""
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


__all__ = ["OpenAICompatibleMixin"]
