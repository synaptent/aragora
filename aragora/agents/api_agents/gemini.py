"""
Gemini agent for Google Generative AI API.

Supports Google Search grounding for web-capable responses when URLs
or web-related keywords are detected in the prompt.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncGenerator

import aiohttp

from aragora.agents.api_agents.base import APIAgent
from aragora.core_types import AgentRole
from aragora.agents.api_agents.common import (
    AgentAPIError,
    AgentConnectionError,
    AgentRateLimitError,
    AgentStreamError,
    AgentTimeoutError,
    Critique,
    Message,
    _sanitize_error_message,
    create_client_session,
    get_primary_api_key,
    get_stream_buffer_size,
    handle_agent_errors,
    iter_chunks_with_timeout,
    native_model_id,
)
from aragora.agents.fallback import QuotaFallbackMixin
from aragora.agents.registry import AgentRegistry
from aragora.config.model_pins import GEMINI_31_PRO_DIRECT, GEMINI_31_PRO_VIA_OPENROUTER

logger = logging.getLogger(__name__)

# Frontier pick for the Gemini API agent (2026-09-04 frontier-model-refresh).
DEFAULT_MODEL = GEMINI_31_PRO_DIRECT

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


@AgentRegistry.register(
    "gemini",
    default_model=DEFAULT_MODEL,
    agent_type="API",
    env_vars="GEMINI_API_KEY or GOOGLE_API_KEY",
    accepts_api_key=True,
)
class GeminiAgent(QuotaFallbackMixin, APIAgent):
    """Agent that uses Google Gemini API directly (not CLI).

    Note: The gemini CLI sends massive folder context by default and
    can exhaust quota quickly. This API agent is much more efficient.

    Supports automatic fallback to OpenRouter when Google API returns
    rate limit/quota errors.

    Uses QuotaFallbackMixin for shared quota detection and fallback logic.
    """

    # No OPENROUTER_MODEL_MAP: QuotaFallbackMixin.get_fallback_model()
    # resolves the current model through the catalog/upgrade-map instead
    # (frontier-model-refresh, 2026-09-04), so every legacy or retired
    # Gemini spelling upgrades to its family frontier, not just a
    # hand-enumerated subset. A map here would be read by nothing.
    DEFAULT_FALLBACK_MODEL = GEMINI_31_PRO_VIA_OPENROUTER

    def __init__(
        self,
        name: str = "gemini",
        model: str = DEFAULT_MODEL,  # Gemini 3.1 Pro Preview - frontier model
        role: AgentRole = "proposer",
        timeout: int = 120,
        api_key: str | None = None,
        enable_fallback: bool | None = None,  # None = use config setting
    ) -> None:
        # Normalize legacy/short names via the shared catalog + upgrade map
        # (frontier-model-refresh, 2026-09-04) instead of a hand-maintained
        # GEMINI_MODEL_ALIASES dict. ``native_model_id`` (not the bare
        # ``resolve_model_id``) because this value is the WIRE id for
        # generativelanguage.googleapis.com: the catalog's ``canonical_id``
        # is an internal name that is not guaranteed to be a code the
        # provider accepts (finding C-P3 on #9989).
        normalized_model = native_model_id(model)
        super().__init__(
            name=name,
            model=normalized_model,
            role=role,
            timeout=timeout,
            api_key=api_key
            or get_primary_api_key(
                "GEMINI_API_KEY",
                "GOOGLE_API_KEY",
                allow_openrouter_fallback=True,
            ),
            base_url="https://generativelanguage.googleapis.com/v1beta",
        )
        self.agent_type = "gemini"
        self._original_model = model  # Keep original for OpenRouter mapping
        # Use config setting if not explicitly provided
        if enable_fallback is None:
            from aragora.agents.fallback import get_default_fallback_enabled

            self.enable_fallback = get_default_fallback_enabled()
        else:
            self.enable_fallback = enable_fallback
        self._fallback_agent = None  # Cached by QuotaFallbackMixin
        self.enable_web_search = True  # Enable Google Search grounding by default

    def _needs_web_search(self, prompt: str) -> bool:
        """Detect if the prompt would benefit from web search grounding.

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
    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Generate a response using Gemini API."""
        # Fail-closed monthly budget cap (no-op unless ARAGORA_MONTHLY_BUDGET_USD set).
        self._enforce_budget_precall()
        if not self.api_key:
            logger.warning("[%s] Missing API key, attempting OpenRouter fallback", self.name)
            result = await self.fallback_generate(prompt, context, status_code=401)
            if result is not None:
                return result
            raise AgentAPIError(
                "Gemini API key not configured",
                agent_name=self.name,
                status_code=401,
            )

        full_prompt = prompt
        if context:
            full_prompt = self._build_context_prompt(context) + prompt

        if self.system_prompt:
            full_prompt = f"System context: {self.system_prompt}\n\n{full_prompt}"

        url = f"{self.base_url}/models/{self.model}:generateContent"

        # Build generation config with persona temperature if set
        generation_config = {
            "temperature": self.temperature if self.temperature is not None else 0.7,
            "maxOutputTokens": 65536,  # Gemini 2.5 supports up to 65k output tokens
        }
        if self.top_p is not None:
            generation_config["topP"] = self.top_p

        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": generation_config,
        }

        # Add Google Search grounding if web search is needed
        if self._needs_web_search(full_prompt):
            logger.info("[%s] Enabling Google Search grounding for web content", self.name)
            payload["tools"] = [{"googleSearch": {}}]

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        async with create_client_session(timeout=float(self.timeout)) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    sanitized = _sanitize_error_message(error_text)

                    if response.status in (401, 403):
                        result = await self.fallback_generate(
                            prompt, context, status_code=response.status
                        )
                        if result is not None:
                            return result

                    # Check if this is a quota/rate limit error and fallback is enabled
                    if self.is_quota_error(response.status, error_text):
                        result = await self.fallback_generate(prompt, context, response.status)
                        if result is not None:
                            return result

                    raise AgentAPIError(
                        f"Gemini API error {response.status}: {sanitized}",
                        agent_name=self.name,
                        status_code=response.status,
                    )

                data = await response.json()

                # Record token usage for billing (Gemini format)
                usage_metadata = data.get("usageMetadata", {})
                self._record_token_usage(
                    tokens_in=usage_metadata.get("promptTokenCount", 0),
                    tokens_out=usage_metadata.get("candidatesTokenCount", 0),
                )

                # Extract text from response with robust error handling
                try:
                    candidate = data["candidates"][0]
                    finish_reason = candidate.get("finishReason", "UNKNOWN")

                    # Handle empty content (MAX_TOKENS, SAFETY, etc.)
                    content = candidate.get("content", {})
                    parts = content.get("parts", [])
                    text = parts[0].get("text", "") if parts else ""

                    # Handle truncation: if we have partial text, use it with a warning
                    if finish_reason == "MAX_TOKENS" and text.strip():
                        # Got partial content - use it but log warning
                        logger.warning(
                            "Gemini response truncated at %s chars, using partial content",
                            len(text),
                        )
                        return text

                    if not text.strip():
                        if finish_reason == "MAX_TOKENS":
                            raise AgentAPIError(
                                "Gemini response truncated (MAX_TOKENS): output limit reached with no content. "
                                "Consider reducing prompt length or increasing maxOutputTokens.",
                                agent_name=self.name,
                            )
                        elif finish_reason == "SAFETY":
                            raise AgentAPIError(
                                "Gemini blocked response (SAFETY filter)",
                                agent_name=self.name,
                            )
                        else:
                            raise AgentAPIError(
                                f"Gemini returned empty content (finishReason: {finish_reason})",
                                agent_name=self.name,
                            )

                    return text
                except (KeyError, IndexError):
                    raise AgentAPIError(
                        f"Unexpected Gemini response format: {data}",
                        agent_name=self.name,
                    )

    async def generate_stream(
        self, prompt: str, context: list[Message] | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream tokens from Gemini API.

        Yields chunks of text as they arrive from the API.
        Falls back to OpenRouter streaming if rate limit errors are encountered.
        """
        if not self.api_key:
            logger.warning(
                "[%s] Missing API key, attempting OpenRouter streaming fallback",
                self.name,
            )
            async for chunk in self.fallback_generate_stream(prompt, context, status_code=401):
                yield chunk
            raise AgentStreamError(
                "Gemini API key not configured",
                agent_name=self.name,
            )

        full_prompt = prompt
        if context:
            full_prompt = self._build_context_prompt(context) + prompt

        if self.system_prompt:
            full_prompt = f"System context: {self.system_prompt}\n\n{full_prompt}"

        # Use streamGenerateContent for streaming
        url = f"{self.base_url}/models/{self.model}:streamGenerateContent"

        # Build generation config with persona temperature if set
        generation_config = {
            "temperature": self.temperature if self.temperature is not None else 0.7,
            "maxOutputTokens": 65536,
        }
        if self.top_p is not None:
            generation_config["topP"] = self.top_p

        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": generation_config,
        }
        estimated_budget_usd = self._estimate_budget_cost_from_text_usd(
            full_prompt,
            int(generation_config["maxOutputTokens"]),
        )
        self._enforce_budget_precall(estimated_budget_usd)
        from aragora.billing import budget_guard

        # Add Google Search grounding if web search is needed
        if self._needs_web_search(full_prompt):
            logger.info("[%s] Enabling Google Search grounding for streaming", self.name)
            payload["tools"] = [{"googleSearch": {}}]

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        async with create_client_session(timeout=float(self.timeout)) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status != 200:
                    error_text = await response.text()
                    sanitized = _sanitize_error_message(error_text)

                    if response.status in (401, 403):
                        async for chunk in self.fallback_generate_stream(
                            prompt, context, status_code=response.status
                        ):
                            yield chunk
                        return

                    # Check for quota/rate limit errors and fallback to OpenRouter
                    if self.is_quota_error(response.status, error_text):
                        async for chunk in self.fallback_generate_stream(
                            prompt, context, response.status
                        ):
                            yield chunk
                        return

                    raise AgentStreamError(
                        f"Gemini streaming API error {response.status}: {sanitized}",
                        agent_name=self.name,
                    )

                # Gemini streams as JSON array chunks
                buffer = b""
                try:
                    # Use timeout wrapper to prevent hanging on stalled streams
                    async for chunk in iter_chunks_with_timeout(response.content):
                        buffer += chunk
                        # Prevent unbounded buffer growth (DoS protection)
                        if len(buffer) > get_stream_buffer_size():
                            raise AgentStreamError(
                                "Streaming buffer exceeded maximum size",
                                agent_name=self.name,
                            )

                        # Try to parse complete JSON objects from buffer
                        # Gemini streams as a JSON array: [{...}, {...}, ...]
                        text = buffer.decode("utf-8", errors="ignore")

                        # Find complete candidate objects
                        # Max iterations guard to prevent infinite loop on malformed data
                        max_parse_iterations = 100
                        parse_iterations = 0
                        while parse_iterations < max_parse_iterations:
                            parse_iterations += 1
                            # Look for text content in the buffer
                            try:
                                # Parse as JSON array (Gemini format)
                                if text.strip().startswith("["):
                                    # Remove trailing incomplete parts
                                    bracket_count = 0
                                    last_complete = -1
                                    for i, c in enumerate(text):
                                        if c == "[":
                                            bracket_count += 1
                                        elif c == "]":
                                            bracket_count -= 1
                                            if bracket_count == 0:
                                                last_complete = i

                                    if last_complete > 0:
                                        complete_json = text[: last_complete + 1]
                                        data = json.loads(complete_json)

                                        # Extract text from all candidates
                                        for item in data:
                                            if "candidates" in item:
                                                for candidate in item["candidates"]:
                                                    content = candidate.get("content", {})
                                                    for part in content.get("parts", []):
                                                        if "text" in part:
                                                            yield part["text"]

                                        # Clear processed data from buffer
                                        buffer = text[last_complete + 1 :].encode("utf-8")
                                        text = buffer.decode("utf-8", errors="ignore")
                                    else:
                                        break
                                else:
                                    break
                            except json.JSONDecodeError:
                                break
                    if estimated_budget_usd > 0:
                        budget_guard.record_spend(estimated_budget_usd)
                except asyncio.TimeoutError:
                    logger.warning("[%s] Streaming timeout", self.name)
                    raise
                except aiohttp.ClientError as e:
                    logger.warning("[%s] Streaming connection error: %s", self.name, e)
                    raise AgentStreamError(
                        f"Streaming connection error: {e}",
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
        """Critique a proposal using Gemini."""
        target_desc = f" from {target_agent}" if target_agent else ""
        critique_prompt = f"""You are a critical reviewer. Analyze this proposal{target_desc} for the given task.

Task: {task}

Proposal to critique:
{proposal}

Provide a structured critique with:
1. ISSUES: List specific problems, errors, or weaknesses (use bullet points)
2. SUGGESTIONS: List concrete improvements (use bullet points)
3. SEVERITY: Rate 0-10 (0=trivial, 10=critical)
4. REASONING: Brief explanation of your assessment

Be constructive but thorough."""

        response = await self.generate(critique_prompt, context)
        return self._parse_critique(response, target_agent or "proposal", proposal)


__all__ = ["GeminiAgent"]
