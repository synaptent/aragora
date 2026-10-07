"""
Anthropic API agent with OpenRouter fallback support.

Supports web search tool for web-capable responses when URLs
or web-related keywords are detected in the prompt.
"""

import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any

from aragora.agents.api_agents.base import APIAgent
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
    create_anthropic_sse_parser,
    create_client_session,
    get_primary_api_key,
    get_trace_headers,
    handle_agent_errors,
)
from aragora.agents.fallback import QuotaFallbackMixin
from aragora.agents.registry import AgentRegistry
from aragora.models.compat import first_text_block, strip_sampling_params
from aragora.observability.metrics.agents import (
    ErrorType,
    record_circuit_breaker_rejection,
    record_fallback_triggered,
    record_provider_call,
    record_provider_token_usage,
    record_rate_limit_detected,
)

logger = logging.getLogger(__name__)

# Patterns that indicate web search would be helpful
WEB_SEARCH_INDICATORS = [
    r"https?://",  # URLs
    r"github\.com",  # GitHub repos
    r"\brepo\b",  # Repository mentions
    r"\bwebsite\b",  # Website mentions
    r"\bweb\s*page\b",  # Web page mentions
    r"\bonline\b",  # Online content
    r"\blatest\s+(news|updates?|release|releases|version|versions)\b",
    r"\bcurrent\s+(events|status|market|prices?|pricing)\b",
    r"\brecent\s+(news|developments|changes|updates?|articles?)\b",
    r"\bnews\b",  # News
    r"\barticle\b",  # Articles
]


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
    "anthropic-api",
    default_model="claude-opus-5",
    default_name="claude-api",
    agent_type="API",
    env_vars="ANTHROPIC_API_KEY",
    accepts_api_key=True,
)
class AnthropicAPIAgent(QuotaFallbackMixin, APIAgent):
    """Agent that uses Anthropic API directly (without CLI).

    Supports automatic fallback to OpenRouter when Anthropic API returns
    billing/quota errors (e.g., "credit balance is too low").

    Uses QuotaFallbackMixin for shared quota detection and fallback logic.
    """

    # Model mapping from Anthropic to OpenRouter format (used by QuotaFallbackMixin)
    # Every legacy Anthropic ID maps to the current frontier (Opus 5) via
    # OpenRouter so a missing or revoked direct key never blocks a debate and
    # weaker historical models are transparently upgraded.
    OPENROUTER_MODEL_MAP = {
        "claude-fable-5": "anthropic/claude-fable-5",
        "claude-opus-5": "anthropic/claude-opus-5",
        "claude-opus-4-8": "anthropic/claude-opus-5",
        "claude-opus-4-7": "anthropic/claude-opus-5",
        "claude-sonnet-4-6": "anthropic/claude-opus-5",
        "claude-opus-4-5-20251101": "anthropic/claude-opus-5",
        "claude-sonnet-4-20250514": "anthropic/claude-opus-5",
        "claude-haiku-4-5-20251001": "anthropic/claude-opus-5",
        "claude-3-5-sonnet-20241022": "anthropic/claude-opus-5",
        "claude-3-opus-20240229": "anthropic/claude-opus-5",
        "claude-3-haiku-20240307": "anthropic/claude-opus-5",
    }
    DEFAULT_FALLBACK_MODEL = "anthropic/claude-opus-5"

    def __init__(
        self,
        name: str = "claude-api",
        model: str = "claude-opus-5",
        role: AgentRole = "proposer",
        timeout: int = 120,
        api_key: str | None = None,
        enable_fallback: bool | None = None,  # None = use config setting
        thinking_budget: int | None = None,
    ) -> None:
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key=api_key
            or get_primary_api_key("ANTHROPIC_API_KEY", allow_openrouter_fallback=True),
            # ANTHROPIC_BASE_URL supports BYOK gateways/proxies (LiteLLM,
            # enterprise API gateways, local proxies) — issue #9304: the
            # hardcoded endpoint made secured providers architecturally
            # unsupported. Accepts values with or without a trailing /v1.
            base_url=_resolve_base_url("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1"),
        )
        self.agent_type = "anthropic"
        # Use config setting if not explicitly provided
        if enable_fallback is None:
            from aragora.agents.fallback import get_default_fallback_enabled

            self.enable_fallback = get_default_fallback_enabled()
        else:
            self.enable_fallback = enable_fallback
        self._fallback_agent = None  # Cached by QuotaFallbackMixin
        self.enable_web_search = True  # Enable web search tool by default
        self.thinking_budget = thinking_budget
        self._last_thinking_trace: str | None = None

    @property
    def last_thinking_trace(self) -> str | None:
        """Return the thinking trace from the most recent generation."""
        return self._last_thinking_trace

    @staticmethod
    def _parse_content_blocks(
        content_blocks: list[dict[str, Any]],
    ) -> tuple[str, str | None]:
        """Separate text and thinking blocks from API response content.

        Args:
            content_blocks: List of content block dicts from the Anthropic API response.

        Returns:
            Tuple of (text_content, thinking_content_or_none).
            Multiple text blocks are joined with ``\\n``.
            Multiple thinking blocks are joined with ``\\n\\n``.
        """
        text_parts: list[str] = []
        thinking_parts: list[str] = []

        for block in content_blocks:
            block_type = block.get("type")
            if block_type == "thinking":
                thinking_parts.append(block.get("thinking", ""))
            elif block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "web_search_tool_result":
                search_results = block.get("content", [])
                for result in search_results:
                    if result.get("type") == "web_search_result":
                        title = result.get("title", "")
                        url = result.get("url", "")
                        if title and url:
                            text_parts.append(f"\n[Source: {title}]({url})")

        text_content = "\n".join(text_parts)
        thinking_content = "\n\n".join(thinking_parts) if thinking_parts else None
        return text_content, thinking_content

    def get_metadata(self) -> dict[str, Any]:
        """Return metadata about the last generation, including thinking trace.

        Returns:
            Dict with ``thinking`` (str or None) and ``thinking_budget`` (int or None).
        """
        return {
            "thinking": self._last_thinking_trace,
            "thinking_budget": self.thinking_budget,
        }

    def _needs_web_search(self, prompt: str) -> bool:
        """Detect if the prompt would benefit from web search.

        Returns True if the prompt contains URLs, GitHub references,
        or keywords indicating need for current/web information.
        """
        if not self.enable_web_search:
            return False

        for pattern in WEB_SEARCH_INDICATORS:
            if re.search(pattern, prompt, re.IGNORECASE):
                return True
        return False

    @handle_agent_errors(
        max_retries=3,
        retry_delay=1.0,
        retry_backoff=2.0,
        retryable_exceptions=(AgentRateLimitError, AgentConnectionError, AgentTimeoutError),
    )
    async def generate(
        self, prompt: str, context: list[Message] | None = None, **kwargs: Any
    ) -> str:
        """Generate a response using Anthropic API.

        Falls back to OpenRouter if billing/quota errors are encountered
        and OPENROUTER_API_KEY is set.

        Includes circuit breaker protection to prevent cascading failures.
        Records per-provider metrics for monitoring.
        """
        import time

        start_time = time.perf_counter()

        # Fail-closed monthly budget cap (no-op unless ARAGORA_MONTHLY_BUDGET_USD
        # is set). Raises before the metered call once the cap is reached.
        self._enforce_budget_precall()

        if not self.api_key:
            logger.warning("[%s] Missing API key, attempting OpenRouter fallback", self.name)
            record_provider_call(
                provider="anthropic",
                success=False,
                error_type=ErrorType.AUTH,
                model=self.model,
            )
            record_fallback_triggered(
                primary_provider="anthropic",
                fallback_provider="openrouter",
                trigger_reason="auth",
            )
            result = await self.fallback_generate(prompt, context, status_code=401)
            if result is not None:
                return result
            raise AgentAPIError(
                "Anthropic API key not configured",
                agent_name=self.name,
                status_code=401,
            )

        # Check circuit breaker before attempting API call
        if self._circuit_breaker is not None and not self._circuit_breaker.can_proceed():
            record_circuit_breaker_rejection("anthropic")
            record_provider_call(
                provider="anthropic",
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

        url = f"{self.base_url}/messages"

        # Check if web search is needed
        use_web_search = self._needs_web_search(full_prompt)

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            **get_trace_headers(),  # Distributed tracing
        }

        # Add beta header for web search if enabled
        if use_web_search:
            logger.info("[%s] Enabling web search tool for web content", self.name)
            headers["anthropic-beta"] = "web-search-2025-03-05"

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "messages": [{"role": "user", "content": full_prompt}],
        }
        if "temperature" in kwargs:
            payload["temperature"] = kwargs["temperature"]

        # Extended thinking support
        thinking_budget = kwargs.get("thinking_budget", self.thinking_budget)
        if thinking_budget and thinking_budget > 0:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }
            payload.pop("temperature", None)  # Anthropic constraint
            payload["max_tokens"] = max(
                payload.get("max_tokens", 4096),
                thinking_budget + 4096,
            )

        # Add web search tool if enabled
        if use_web_search:
            payload["tools"] = [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                }
            ]

        # Apply generation parameters from persona if set
        if self.temperature is not None and "thinking" not in payload:
            payload["temperature"] = self.temperature
        if self.top_p is not None:
            payload["top_p"] = self.top_p

        # Claude Opus 4.7+ (incl. Opus 5 / Sonnet 5 / Fable 5) removed sampling
        # parameters: a non-default temperature/top_p/top_k returns a 400. Strip
        # them centrally so persona configs (e.g. the vertical specialists,
        # which set temperature 0.1-0.3 + top_p) do not hard-fail on those
        # models. Guide behaviour with prompting instead.
        strip_sampling_params(payload, self.model)

        if self.system_prompt:
            payload["system"] = self.system_prompt

        try:
            async with create_client_session(timeout=self.timeout) as session:
                async with session.post(
                    url,
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        sanitized = _sanitize_error_message(error_text)

                        # Record failure for circuit breaker (non-quota errors)
                        if self._circuit_breaker is not None and not self.is_quota_error(
                            response.status, error_text
                        ):
                            self._circuit_breaker.record_failure()

                        # Determine error type for metrics
                        error_type = ErrorType.API_ERROR
                        if response.status == 429:
                            error_type = ErrorType.RATE_LIMIT
                            record_rate_limit_detected("anthropic")
                        elif response.status in (401, 403):
                            error_type = ErrorType.AUTH
                        elif self.is_quota_error(response.status, error_text):
                            error_type = ErrorType.QUOTA

                        if response.status in (401, 403):
                            record_fallback_triggered(
                                primary_provider="anthropic",
                                fallback_provider="openrouter",
                                trigger_reason="auth",
                            )
                            result = await self.fallback_generate(
                                prompt, context, status_code=response.status
                            )
                            if result is not None:
                                return result

                        # Check if this is a quota/billing error and fallback is enabled
                        if self.is_quota_error(response.status, error_text):
                            record_fallback_triggered(
                                primary_provider="anthropic",
                                fallback_provider="openrouter",
                                trigger_reason="quota",
                            )
                            result = await self.fallback_generate(prompt, context, response.status)
                            if result is not None:
                                return result

                        # Record the failed call metric
                        record_provider_call(
                            provider="anthropic",
                            success=False,
                            error_type=error_type,
                            latency_seconds=time.perf_counter() - start_time,
                            model=self.model,
                        )

                        raise AgentAPIError(
                            f"Anthropic API error {response.status}: {sanitized}",
                            agent_name=self.name,
                            status_code=response.status,
                        )

                    data = await response.json()

                    # Record token usage for billing
                    usage = data.get("usage", {})
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    self._record_token_usage(
                        tokens_in=input_tokens,
                        tokens_out=output_tokens,
                    )

                    try:
                        # A response with no "content" key at all is malformed,
                        # not merely empty — surface it as a format error the way
                        # the old content[0] KeyError did.
                        if "content" not in data:
                            raise KeyError("content")

                        # Extract text and thinking from response content blocks
                        content_blocks = data.get("content", [])
                        output, thinking = self._parse_content_blocks(content_blocks)
                        self._last_thinking_trace = thinking

                        if not output:
                            # Fallback to old format. Must not index content[0]:
                            # on a thinking-by-default model that is a thinking
                            # block, not text.
                            output = first_text_block(data.get("content"))

                        if not output or not output.strip():
                            if self._circuit_breaker is not None:
                                self._circuit_breaker.record_failure()
                            record_provider_call(
                                provider="anthropic",
                                success=False,
                                error_type=ErrorType.API_ERROR,
                                latency_seconds=time.perf_counter() - start_time,
                                model=self.model,
                            )
                            raise AgentAPIError(
                                "Anthropic returned empty content",
                                agent_name=self.name,
                            )

                        # Record success for circuit breaker
                        if self._circuit_breaker is not None:
                            self._circuit_breaker.record_success()

                        # Record successful provider metrics
                        latency = time.perf_counter() - start_time
                        record_provider_call(
                            provider="anthropic",
                            success=True,
                            latency_seconds=latency,
                            model=self.model,
                        )
                        record_provider_token_usage(
                            provider="anthropic",
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                        )

                        return output
                    except (KeyError, IndexError):
                        if self._circuit_breaker is not None:
                            self._circuit_breaker.record_failure()
                        record_provider_call(
                            provider="anthropic",
                            success=False,
                            error_type=ErrorType.API_ERROR,
                            latency_seconds=time.perf_counter() - start_time,
                            model=self.model,
                        )
                        raise AgentAPIError(
                            f"Unexpected Anthropic response format: {data}",
                            agent_name=self.name,
                        )
        except (AgentAPIError, AgentCircuitOpenError):
            raise  # Re-raise without double-recording
        except asyncio.TimeoutError:
            # Record failure for timeout errors
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            record_provider_call(
                provider="anthropic",
                success=False,
                error_type=ErrorType.TIMEOUT,
                latency_seconds=time.perf_counter() - start_time,
                model=self.model,
            )
            raise
        except (OSError, ValueError, TypeError, RuntimeError):
            # Record failure for unexpected errors
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            record_provider_call(
                provider="anthropic",
                success=False,
                error_type=ErrorType.UNKNOWN,
                latency_seconds=time.perf_counter() - start_time,
                model=self.model,
            )
            raise

    async def generate_stream(
        self, prompt: str, context: list[Message] | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from Anthropic API.

        Yields chunks of text as they arrive from the API using SSE.
        """
        if not self.api_key:
            logger.warning(
                "[%s] Missing API key, attempting OpenRouter streaming fallback",
                self.name,
            )
            async for chunk in self.fallback_generate_stream(prompt, context, status_code=401):
                yield chunk
            raise AgentStreamError(
                "Anthropic API key not configured",
                agent_name=self.name,
            )

        full_prompt = prompt
        if context:
            full_prompt = self._build_context_prompt(context) + prompt

        url = f"{self.base_url}/messages"

        # Check if web search is needed
        use_web_search = self._needs_web_search(full_prompt)

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            **get_trace_headers(),  # Distributed tracing
        }

        # Add beta header for web search if enabled
        if use_web_search:
            logger.info("[%s] Enabling web search tool for streaming", self.name)
            headers["anthropic-beta"] = "web-search-2025-03-05"

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": full_prompt}],
            "stream": True,
        }

        # Add web search tool if enabled
        if use_web_search:
            payload["tools"] = [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                }
            ]

        # Apply generation parameters from persona if set
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if self.top_p is not None:
            payload["top_p"] = self.top_p

        # Claude Opus 4.7+ (incl. the Opus 5 default) reject sampling
        # params with a 400. No-ops for every other model.
        strip_sampling_params(payload, self.model)

        if self.system_prompt:
            payload["system"] = self.system_prompt

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
                            prompt, context, response.status
                        ):
                            yield chunk
                        return

                    # Check for quota/billing errors and fallback to OpenRouter
                    if self.is_quota_error(response.status, error_text):
                        async for chunk in self.fallback_generate_stream(
                            prompt, context, response.status
                        ):
                            yield chunk
                        return

                    raise AgentStreamError(
                        f"Anthropic streaming API error {response.status}: {sanitized}",
                        agent_name=self.name,
                    )

                # Use SSEStreamParser for consistent SSE parsing
                try:
                    parser = create_anthropic_sse_parser()
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
        """Critique a proposal using Anthropic API."""
        target_desc = f"from {target_agent}" if target_agent else ""
        critique_prompt = f"""Analyze this proposal {target_desc} critically:

Task: {task}

Proposal:
{proposal}

Provide structured feedback:
- ISSUES: Specific problems (bullet points)
- SUGGESTIONS: Improvements (bullet points)
- SEVERITY: 0-10 rating (0=trivial, 10=critical)
- REASONING: Brief explanation"""

        response = await self.generate(critique_prompt, context)
        return self._parse_critique(response, target_agent or "proposal", proposal)


__all__ = ["AnthropicAPIAgent"]
