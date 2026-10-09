"""
Anthropic API agent with OpenRouter fallback support.

Supports web search tool for web-capable responses when URLs
or web-related keywords are detected in the prompt.
"""

import asyncio
import logging
import re
from collections.abc import AsyncGenerator
from typing import Any, ClassVar

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
    upgrade_retired_model_id,
)
from aragora.agents.fallback import QuotaFallbackMixin
from aragora.agents.registry import AgentRegistry
from aragora.config.model_pins import FABLE_51_DIRECT, OPUS_5_VIA_OPENROUTER
from aragora.models.catalog import spec_or_none
from aragora.models.compat import (
    allows_forced_tool_choice,
    first_text_block,
    strip_sampling_params,
    thinks_by_default,
)
from aragora.observability.metrics.agents import (
    ErrorType,
    record_circuit_breaker_rejection,
    record_fallback_triggered,
    record_provider_call,
    record_provider_token_usage,
    record_rate_limit_detected,
)

logger = logging.getLogger(__name__)

# Frontier pick for the Anthropic API agent (2026-09-04 frontier-model-refresh).
DEFAULT_MODEL = FABLE_51_DIRECT

# Fallback default max_tokens for a model with no catalog row (today's
# historical default, unchanged by the Task 7 request-shape hardening).
_UNKNOWN_MODEL_DEFAULT_MAX_TOKENS = 4096
# Default max_tokens caps for a cataloged model when the caller does not pass
# one explicitly: min(catalog max_output_tokens, this cap). The STREAM cap is
# the shipped default for ``ARAGORA_ANTHROPIC_STREAM_MAX_TOKENS`` and the
# value used when settings cannot be read; see _stream_max_tokens_cap.
_DEFAULT_MAX_TOKENS_NON_STREAM = 16_000
_DEFAULT_MAX_TOKENS_STREAM = 64_000

# Models whose refusal-fallback is wired up server-side (Task 7,
# frontier-model-refresh): only these canonical ids, and only within the
# "anthropic" catalog family, ever get "fallbacks": "default" + the
# server-side-fallback beta header — and then only when the request targets
# the official api.anthropic.com endpoint (see
# _is_official_anthropic_endpoint) and settings.anthropic_refusal_fallback
# is on.
_REFUSAL_FALLBACK_MODEL_IDS = frozenset({"claude-fable-5-1", "claude-opus-5"})

# PAIRING RULE (verified against the Claude API reference; 2026-09-05
# merge-gate ruling on finding C-P3 of #9989). The refusal fallback beta has
# exactly two request shapes, and the payload form and the beta header are
# NOT interchangeable -- mixing them is a 400:
#
#   scalar form   payload {"fallbacks": "default"}
#                 header  anthropic-beta: server-side-fallback-2026-07-01
#   array form    payload {"fallbacks": [{"model": ...}, ...]}
#                 header  anthropic-beta: server-side-fallback-2026-06-01
#
# Aragora ships the SCALAR form only (server-side default target, no
# hand-picked fallback list), so the 07-01 header is the only one it ever
# sends and "fallbacks" is always a str, never a list. Changing one of these
# two constants without the other is the bug this comment exists to prevent;
# tests/agents/api_agents/test_request_shapes.py pins the pairing in both
# directions.
_REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"
_REFUSAL_FALLBACK_PAYLOAD_VALUE = "default"

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


_ANTHROPIC_DEFAULT_BASE_URL = "https://api.anthropic.com/v1"


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


def _is_official_anthropic_endpoint(base_url: str | None) -> bool:
    """True when ``base_url`` names Anthropic's own public API endpoint.

    The single place this repo answers "am I talking to api.anthropic.com or
    to somebody else's gateway?". Two behaviours depend on the answer and
    must not drift apart:

    * the constructor's retired-id upgrade (a BYOK gateway may serve ids the
      public catalog does not know, so rewriting them would silently target
      the wrong model), and
    * the server-side refusal fallback (the ``anthropic-beta:
      server-side-fallback-*`` header plus ``"fallbacks"`` in the body are an
      api.anthropic.com request extension; a LiteLLM / VibeProxy / enterprise
      gateway that does not implement it may reject the request outright --
      findings O-P3 and C-P3 on #9989).

    Compared against the NORMALIZED url rather than raw env-var presence, so
    an ``ANTHROPIC_BASE_URL`` set to a spelling of the same official endpoint
    (e.g. missing the ``/v1`` suffix) still counts as official. An empty
    value means "no override", i.e. the official endpoint.
    """
    raw = str(base_url or "").strip().rstrip("/")
    if not raw:
        return True
    normalized = raw if raw.endswith("/v1") else raw + "/v1"
    return normalized == _ANTHROPIC_DEFAULT_BASE_URL


@AgentRegistry.register(
    "anthropic-api",
    default_model=DEFAULT_MODEL,
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

    # No static OPENROUTER_MODEL_MAP: QuotaFallbackMixin.get_fallback_model()
    # (aragora/agents/fallback.py) resolves the current model through the
    # catalog/upgrade-map instead, so every legacy or retired Anthropic
    # spelling (not just a hand-enumerated subset) transparently upgrades to
    # its frontier via OpenRouter.
    DEFAULT_FALLBACK_MODEL = OPUS_5_VIA_OPENROUTER

    # Model ids we've already logged the "ignoring thinking_budget" notice
    # for (see _log_adaptive_thinking_once); process-lifetime, shared across
    # instances so the notice does not repeat on every single call.
    _ADAPTIVE_THINKING_LOGGED: ClassVar[set[str]] = set()

    # (requested, served) pairs already logged by _note_served_model.
    # Process-lifetime and shared across instances, like the set above, so a
    # steady-state server-side fallback logs once rather than per call.
    _SERVED_MODEL_LOGGED: ClassVar[set[tuple[str, str]]] = set()

    def __init__(
        self,
        name: str = "claude-api",
        model: str = DEFAULT_MODEL,
        role: AgentRole = "proposer",
        timeout: int = 120,
        api_key: str | None = None,
        enable_fallback: bool | None = None,  # None = use config setting
        thinking_budget: int | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
    ) -> None:
        # A retired or known-dead explicit id is upgraded before it can be
        # sent to the native endpoint (finding O-P2a); active and unknown
        # ids pass through untouched. See upgrade_retired_model_id. Skipped
        # for a custom ANTHROPIC_BASE_URL (BYOK gateway/proxy, issue #9304):
        # that endpoint may serve ids under names the public catalog does
        # not recognize, so rewriting them would silently target the wrong
        # model on someone else's endpoint. Compared against the RESOLVED
        # (normalized) URL rather than raw env-var presence, so an env var
        # set to a spelling of the same official endpoint (e.g. missing the
        # /v1 suffix) still counts as official.
        resolved_base_url = _resolve_base_url("ANTHROPIC_BASE_URL", _ANTHROPIC_DEFAULT_BASE_URL)
        if _is_official_anthropic_endpoint(resolved_base_url):
            model = upgrade_retired_model_id(model)
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
            base_url=resolved_base_url,
            temperature=temperature,
            top_p=top_p,
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
        self._last_served_model: str | None = None
        # Ordered (requested, served) observation per successful call, for
        # the CURRENT debate. See _note_served_model / reset_served_model_log.
        self._served_model_log: list[dict[str, Any]] = []

    @property
    def last_thinking_trace(self) -> str | None:
        """Return the thinking trace from the most recent generation."""
        return self._last_thinking_trace

    @property
    def last_served_model(self) -> str | None:
        """Model the server actually answered with on the most recent
        generation, when it DIFFERED from the requested id; ``None``
        otherwise. See :meth:`_note_served_model`.

        Last-call-only by construction. A receipt covers a whole debate, so
        it reads :attr:`served_model_log` instead — this property answers
        only "what happened on the last call".
        """
        return self._last_served_model

    @property
    def served_model_log(self) -> list[dict[str, Any]]:
        """Every ``(requested, served)`` observation made since the last
        :meth:`reset_served_model_log`, oldest first.

        One entry per call that produced a response, as
        ``{"requested": <id we asked for>, "served": <id the server echoed,
        or None when it echoed nothing>, "fallback": <bool>}``. ``fallback``
        carries THIS agent's catalog-aware verdict on the pair (see
        :meth:`_is_same_model`) so a consumer never has to re-decide whether
        two spellings name one model.

        A debate makes several calls per agent, and
        :attr:`last_served_model` remembers only the last one: a round-1
        proposal answered by the server-side fallback followed by a round-2
        critique answered as asked left the receipt claiming no fallback ever
        happened, while a different model had in fact written part of the
        decision (finding C-P2 on #9989). The log is what
        ``aragora.debate.orchestrator_runner.collect_served_models`` reads.

        Returns a copy: mutating it cannot corrupt the agent's record.
        """
        return [dict(entry) for entry in self._served_model_log]

    def reset_served_model_log(self) -> None:
        """Start a fresh debate-scoped served-model record.

        Called by the debate runner at debate start. Agents are supplied by
        the caller and are commonly reused across debates (the Arena keeps
        whatever list it was constructed with, and ``arena.run()`` can be
        called more than once), so a fresh agent per debate is NOT
        guaranteed and the log has to be cleared explicitly or one debate's
        fallback would be reported in the next debate's receipt.
        """
        self._served_model_log.clear()
        self._last_served_model = None

    @staticmethod
    def _is_same_model(requested: str, served: str) -> bool:
        """True when two model spellings name the SAME catalog row.

        Falls back to string equality for a spelling the catalog does not
        carry, so an id newer than the catalog still compares sanely against
        itself and still counts as a swap against anything else.
        """
        if requested == served:
            return True
        from aragora.models.catalog import spec_or_none

        requested_spec = spec_or_none(requested)
        served_spec = spec_or_none(served)
        if requested_spec is None or served_spec is None:
            return False
        return requested_spec.canonical_id == served_spec.canonical_id

    def _note_served_model(self, served: str | None) -> None:
        """Record the response's ``model`` field when it names a DIFFERENT
        model from the one we asked for.

        Anthropic echoes the model that actually produced the response. With
        the server-side refusal fallback enabled by default for Fable 5.1 /
        Opus 5, a request can legitimately be answered by a DIFFERENT model,
        and a receipt that attributes the output to the requested id is then
        wrong about which model made the decision (finding C-P3 on #9989).
        Surfaced through ``get_metadata()["served_model"]`` and logged once
        per (requested, served) pair at INFO -- it is normal operation, not a
        fault, but it must be visible.

        "Different" is decided through the CATALOG, not by string equality:
        an agent pinned to the active alias ``claude-fable-5.1`` sends that
        spelling verbatim and the server echoes the canonical
        ``claude-fable-5-1``, which the first cut reported as a server-side
        fallback -- a receipt claiming a model swap that never happened (the
        round-4 re-review of the same finding). Two spellings that resolve to
        one catalog row are one model. A served id the catalog does not know
        IS recorded: an unrecognized answer is exactly the case a receipt
        must not silently absorb.

        EVERY call is appended to :attr:`served_model_log` -- matching and
        differing alike, and a call the server answered without echoing any
        model id at all (``served is None``) too, so the call count stays
        truthful. ``_last_served_model`` is additionally reset to ``None`` on
        every call, so a stale value from an earlier generation can never be
        attributed to this one; the debate-wide claim comes from the log, not
        from that single value (finding C-P2 on #9989).
        """
        is_fallback = bool(served) and not self._is_same_model(self.model, served or "")
        self._served_model_log.append(
            {"requested": self.model, "served": served, "fallback": is_fallback}
        )
        if not is_fallback or served is None:
            self._last_served_model = None
            return
        self._last_served_model = served
        pair = (self.model, served)
        if pair not in self._SERVED_MODEL_LOGGED:
            self._SERVED_MODEL_LOGGED.add(pair)
            logger.info(
                "[%s] Anthropic served %s for requested model %s "
                "(server-side fallback); recorded as served_model",
                self.name,
                served,
                self.model,
            )

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
            Dict with ``thinking`` (str or None), ``thinking_budget`` (int or
            None) and ``served_model`` (str or None -- set only when the
            server answered with a model other than the requested one, e.g.
            via the server-side refusal fallback).
        """
        return {
            "thinking": self._last_thinking_trace,
            "thinking_budget": self.thinking_budget,
            "served_model": self._last_served_model,
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

    def _supports_refusal_fallback(self) -> bool:
        """True when ``self.model`` is one of the two catalog rows the
        server-side refusal fallback is wired up for (Fable 5.1, Opus 5),
        resolved via the catalog so any known spelling/alias of those ids
        qualifies. A model outside the "anthropic" catalog family, or absent
        from the catalog entirely, never qualifies."""
        spec = spec_or_none(self.model)
        if spec is None or spec.family != "anthropic":
            return False
        return spec.canonical_id in _REFUSAL_FALLBACK_MODEL_IDS

    def _refusal_fallback_enabled(self) -> bool:
        """``_supports_refusal_fallback()`` gated by the target ENDPOINT and
        the ``anthropic_refusal_fallback`` setting (default on).

        The beta header and the ``"fallbacks"`` body field are an
        api.anthropic.com request extension. A custom ``ANTHROPIC_BASE_URL``
        (BYOK gateway, LiteLLM, VibeProxy, an enterprise proxy) is a
        different server that need not implement it, and sending an
        unrecognised beta/body field there can fail the whole request --
        so a non-official endpoint gets NEITHER, regardless of the model or
        the setting (findings O-P3 and C-P3 on #9989). Reuses the same
        resolved-URL gate as the constructor's retired-id upgrade.
        """
        if not _is_official_anthropic_endpoint(self.base_url):
            return False
        if not self._supports_refusal_fallback():
            return False
        try:
            from aragora.config import get_settings

            return bool(get_settings().agent.anthropic_refusal_fallback)
        except (ImportError, AttributeError):
            # Settings unavailable for some reason: default to the
            # documented default (on) rather than silently disabling a
            # reliability feature.
            return True

    def _log_adaptive_thinking_once(self) -> None:
        """Log (once per model id) that an explicit thinking_budget is being
        ignored because the model thinks by default and cannot be given an
        explicit budget the way older models can."""
        if self.model in self._ADAPTIVE_THINKING_LOGGED:
            return
        self._ADAPTIVE_THINKING_LOGGED.add(self.model)
        logger.info(
            "[%s] %s thinks by default; ignoring explicit thinking_budget "
            "(adaptive thinking has no budget_tokens knob)",
            self.name,
            self.model,
        )

    def _stream_max_tokens_cap(self) -> int:
        """Default ``max_tokens`` cap for a STREAMED call, from settings.

        ``generate_stream`` exposes no caller-facing ``max_tokens``, so on
        that path the default IS the ceiling: raising it from a flat 4096 to
        64k is a 16x per-call output-spend change an operator had no way to
        undo (finding C-P3 on #9989). ``ARAGORA_ANTHROPIC_STREAM_MAX_TOKENS``
        is that knob. It only lowers the *default*; the catalog's
        ``max_output_tokens`` still caps the result in
        :meth:`_resolve_max_tokens`, so configuring more than the model can
        emit changes nothing. Settings unavailable (import cycle at startup,
        a stub config) falls back to the shipped 64k rather than silently
        shrinking every streamed answer.
        """
        try:
            from aragora.config import get_settings

            configured = int(get_settings().agent.anthropic_stream_max_tokens)
        except (ImportError, AttributeError, TypeError, ValueError):
            return _DEFAULT_MAX_TOKENS_STREAM
        return configured if configured > 0 else _DEFAULT_MAX_TOKENS_STREAM

    def _resolve_max_tokens(self, requested: int | None, *, stream: bool) -> int:
        """Resolve the ``max_tokens`` payload value.

        * No catalog row for ``self.model``: keep today's flat 4096 default,
          respecting whatever the caller explicitly requested (uncapped —
          there is no catalog ceiling to enforce).
        * Cataloged model, caller passed nothing: ``min(catalog
          max_output_tokens, cap)``, where ``cap`` is 16_000 non-streaming
          and :meth:`_stream_max_tokens_cap` (default 64_000, settable via
          ``ARAGORA_ANTHROPIC_STREAM_MAX_TOKENS``) when streaming.
        * Cataloged model, caller passed a value: respected, but capped at
          the catalog's ``max_output_tokens``. The stream setting does NOT
          override an explicit caller value — it is a default, not a policy
          ceiling.
        """
        spec = spec_or_none(self.model)
        if spec is None:
            return requested if requested is not None else _UNKNOWN_MODEL_DEFAULT_MAX_TOKENS
        if requested is None:
            cap = self._stream_max_tokens_cap() if stream else _DEFAULT_MAX_TOKENS_NON_STREAM
            return min(spec.max_output_tokens, cap)
        return min(requested, spec.max_output_tokens)

    def _request_headers(self, *, use_web_search: bool = False) -> dict[str, str]:
        """Build request headers shared by ``generate`` and
        ``generate_stream``. Combines every ``anthropic-beta`` value this
        request needs (web search, refusal fallback, ...) into one
        comma-joined header rather than overwriting one with the other."""
        # ``api_key`` is ``str | None`` on the base agent; a request without
        # one is already refused upstream, so send the empty string rather
        # than a ``None`` header value the return type cannot carry.
        headers: dict[str, str] = {
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            **get_trace_headers(),  # Distributed tracing
        }
        beta_values: list[str] = []
        if use_web_search:
            beta_values.append("web-search-2025-03-05")
        if self._refusal_fallback_enabled():
            beta_values.append(_REFUSAL_FALLBACK_BETA)
        if beta_values:
            headers["anthropic-beta"] = ", ".join(beta_values)
        return headers

    def _build_payload(
        self,
        prompt: str,
        *,
        stream: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
        thinking_budget: int | None = None,
        use_web_search: bool = False,
        tool_choice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the Anthropic Messages API request payload.

        Shared by ``generate`` and ``generate_stream`` so every catalog-driven
        behaviour (sampling-param support, thinking-by-default, forced
        ``tool_choice``, refusal fallback, max_tokens defaults/caps) is
        applied in exactly one place instead of two independently-drifting
        inline builders.
        """
        spec = spec_or_none(self.model)
        resolved_max_tokens = self._resolve_max_tokens(max_tokens, stream=stream)

        message_content = prompt
        resolved_tool_choice = tool_choice
        if tool_choice is not None:
            choice_type = tool_choice.get("type") if isinstance(tool_choice, dict) else None
            if choice_type in ("any", "tool") and not allows_forced_tool_choice(self.model):
                tool_name = tool_choice.get("name") if isinstance(tool_choice, dict) else None
                hint = f"Use the {tool_name} tool." if tool_name else "Use the appropriate tool."
                message_content = f"{hint}\n\n{message_content}" if message_content else hint
                resolved_tool_choice = {"type": "auto"}

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": resolved_max_tokens,
            "messages": [{"role": "user", "content": message_content}],
        }
        if stream:
            payload["stream"] = True
        if resolved_tool_choice is not None:
            payload["tool_choice"] = resolved_tool_choice

        model_thinks_by_default = thinks_by_default(self.model)
        effective_thinking_budget = (
            thinking_budget if thinking_budget is not None else self.thinking_budget
        )
        effective_temperature = self.temperature if self.temperature is not None else temperature

        if model_thinks_by_default:
            if effective_thinking_budget and effective_thinking_budget > 0:
                # Thinking is already on for this family; there is no
                # budget_tokens knob to set, so no "thinking" key is emitted.
                self._log_adaptive_thinking_once()
        elif effective_thinking_budget and effective_thinking_budget > 0:
            payload["thinking"] = {
                "type": "enabled",
                "budget_tokens": effective_thinking_budget,
            }
            effective_temperature = None  # Anthropic constraint: thinking + temperature conflict
            bumped = max(payload["max_tokens"], effective_thinking_budget + 4096)
            payload["max_tokens"] = min(bumped, spec.max_output_tokens) if spec else bumped

        if effective_temperature is not None:
            payload["temperature"] = effective_temperature
        if self.top_p is not None:
            payload["top_p"] = self.top_p

        if use_web_search:
            payload["tools"] = [
                {
                    "type": "web_search_20250305",
                    "name": "web_search",
                }
            ]

        # Claude Opus 4.7+ (incl. Opus 5 / Sonnet 5 / Fable 5.1) removed
        # sampling parameters: a non-default temperature/top_p/top_k returns
        # a 400. Strip them centrally so persona configs (e.g. the vertical
        # specialists, which set temperature 0.1-0.3 + top_p) do not
        # hard-fail on those models. Guide behaviour with prompting instead.
        strip_sampling_params(payload, self.model)

        if self._refusal_fallback_enabled():
            # Scalar form only -- see the _REFUSAL_FALLBACK_BETA pairing rule.
            payload["fallbacks"] = _REFUSAL_FALLBACK_PAYLOAD_VALUE

        if self.system_prompt:
            payload["system"] = self.system_prompt

        return payload

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
        if use_web_search:
            logger.info("[%s] Enabling web search tool for web content", self.name)

        headers = self._request_headers(use_web_search=use_web_search)

        payload = self._build_payload(
            full_prompt,
            stream=False,
            max_tokens=kwargs.get("max_tokens"),
            temperature=kwargs.get("temperature"),
            thinking_budget=kwargs.get("thinking_budget", self.thinking_budget),
            use_web_search=use_web_search,
            tool_choice=kwargs.get("tool_choice"),
        )

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

                    # The server echoes the model that actually answered; with
                    # the server-side refusal fallback on by default that can
                    # differ from what we asked for (finding C-P3).
                    self._note_served_model(data.get("model"))

                    # Record token usage for billing
                    usage = data.get("usage", {})
                    input_tokens = usage.get("input_tokens", 0)
                    output_tokens = usage.get("output_tokens", 0)
                    self._record_token_usage(
                        tokens_in=input_tokens,
                        tokens_out=output_tokens,
                    )

                    # A 200 response can still be a declared refusal (e.g. the
                    # cyber-classifier on Fable 5.1 / Opus 5): surface it as a
                    # structured failure, never as empty-string output.
                    if data.get("stop_reason") == "refusal":
                        stop_details = data.get("stop_details")
                        category = (
                            stop_details.get("category") if isinstance(stop_details, dict) else None
                        )
                        if self._circuit_breaker is not None:
                            self._circuit_breaker.record_failure()
                        record_provider_call(
                            provider="anthropic",
                            success=False,
                            error_type=ErrorType.API_ERROR,
                            latency_seconds=time.perf_counter() - start_time,
                            model=self.model,
                        )
                        message = "Anthropic declined to generate a response (stop_reason=refusal)"
                        if category:
                            message = f"{message}: {category}"
                        raise AgentAPIError(
                            message,
                            agent_name=self.name,
                            reason="refusal",
                            category=category,
                            # A refusal is terminal: retrying reproduces it.
                            # recoverable=False also stops @handle_agent_errors
                            # falling through to its own record_failure(), which
                            # would double-count the manual one above and trip
                            # the breaker on half the refusals it takes.
                            recoverable=False,
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
        if use_web_search:
            logger.info("[%s] Enabling web search tool for streaming", self.name)

        headers = self._request_headers(use_web_search=use_web_search)

        payload = self._build_payload(
            full_prompt,
            stream=True,
            thinking_budget=self.thinking_budget,
            use_web_search=use_web_search,
        )

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
                parser = create_anthropic_sse_parser()
                try:
                    async for content in parser.parse_stream(response.content, self.name):
                        yield content
                except RuntimeError as e:
                    raise AgentStreamError(str(e), agent_name=self.name)
                finally:
                    # A stream carries the served model on its "message_start"
                    # event rather than in a response body (finding C-P3). In
                    # a finally so a stream that errors part-way still records
                    # which model produced what was already yielded.
                    self._note_served_model(parser.served_model)

                # A streamed refusal carries stop_reason on a "message_delta"
                # event rather than in the (nonexistent, for a stream) single
                # JSON body generate() inspects: surface it the same
                # structured way once the stream completes. Any text already
                # yielded above stays yielded; the error is raised after it.
                if parser.stop_reason == "refusal":
                    category = (
                        parser.stop_details.get("category")
                        if isinstance(parser.stop_details, dict)
                        else None
                    )
                    if self._circuit_breaker is not None:
                        self._circuit_breaker.record_failure()
                    message = "Anthropic declined to generate a response (stop_reason=refusal)"
                    if category:
                        message = f"{message}: {category}"
                    raise AgentAPIError(
                        message,
                        agent_name=self.name,
                        reason="refusal",
                        category=category,
                        # Terminal, and not a second breaker failure — see the
                        # non-streaming refusal branch above.
                        recoverable=False,
                    )

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
