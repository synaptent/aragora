"""Real :class:`ProviderInvoker` wiring for PDB Mode 3 Protocol B.

This module ships the non-mock invoker: it dispatches findings,
critique, and synthesis calls to the real class-based agent
instances in :mod:`aragora.agents.api_agents` and coerces their
free-form text output into the structured response shapes the
:mod:`aragora.pdb.protocol` executor consumes.

Phase A scope:

- :data:`FAMILY_CLAUDE` → :class:`AnthropicAPIAgent`
- :data:`FAMILY_GPT` → :class:`OpenAIAPIAgent`

Phase B scope (this PR extends the invoker to cover the rest of the
panel roster):

- :data:`FAMILY_GEMINI` → :class:`GeminiAgent` (direct Google API)
- :data:`FAMILY_GROK` → :class:`GrokAgent` (xAI API)
- :data:`FAMILY_DEEPSEEK` → :class:`OpenRouterAgent` with DeepSeek model
- :data:`FAMILY_KIMI` → :class:`OpenRouterAgent` with Moonshot Kimi model
- :data:`FAMILY_QWEN` → :class:`OpenRouterAgent` with Qwen model
- :data:`FAMILY_MISTRAL` → :class:`MistralAPIAgent` (regulatory lens)

With all eight families wired, a fully-configured environment produces
the heterogeneous two-core + five-heterodox + one-regulatory brief as
designed.

The class holds a pre-initialized agent per family (not per call) so
each invocation reuses the underlying HTTP session setup the base
:class:`APIAgent` constructs.

Token + cost tracking. Every call wraps the underlying agent in
:func:`time.monotonic` for latency and reads ``last_tokens_in`` /
``last_tokens_out`` off the agent after ``generate`` returns, then
looks up a conservative per-model rate to compute ``cost_usd``.
Unknown models log a warning and record ``0.0`` so the budget layer
still receives a valid float. Rate-limit / retry / fallback logic
lives in the base :class:`APIAgent` classes — the invoker stays a
thin dispatch layer.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol as _TypingProtocol, Sequence

from aragora.models import by_any_id
from aragora.pdb.panel_config import PDBPanelSlot
from aragora.pdb.protocol import (
    SlotCritiqueResponse,
    SlotFindingsResponse,
    SynthesisResponse,
)
from aragora.pdb.response_parser import (
    parse_critique_response,
    parse_findings_response,
    parse_synthesis_response,
)
from aragora.review.builder import PanelVote
from aragora.review.protocol import DissentPosition
from aragora.swarm.pr_review_protocol import PRReviewBinding, PRReviewFinding

__all__ = [
    "FAMILY_CLAUDE",
    "FAMILY_DEEPSEEK",
    "FAMILY_GEMINI",
    "FAMILY_GPT",
    "FAMILY_GROK",
    "FAMILY_KIMI",
    "FAMILY_MISTRAL",
    "FAMILY_QWEN",
    "WIRED_FAMILIES",
    "HETERODOX_FAMILIES",
    "OPENROUTER_BACKED_FAMILIES",
    "ProviderUnavailableError",
    "RealProviderInvoker",
    "estimate_cost_usd",
]


logger = logging.getLogger(__name__)

_SLOT_TIMEOUT_ENV = "ARAGORA_PDB_SLOT_TIMEOUT_SECONDS"
# Default per-slot provider-call timeout.
#
# Deliberately generous (5 minutes). The goal of this timeout is to
# surface a genuinely-hung provider — never to cap a legitimately
# slow reasoning response. Empirically:
#   - Haiku:     typical 5-15s, worst ~30s
#   - Sonnet:    typical 20-45s, worst ~90s
#   - Opus:      typical 60s, worst 120-180s on large diffs
#   - Gemini / Grok / DeepSeek / Kimi / Qwen via OpenRouter: wide variance
#
# Earlier iterations set this to 20s and then 90s, both of which
# false-positive tripped on legitimately-long Opus reviews during
# Mode 3 dogfood. 300s ensures timeout is only a last-resort safety
# net, not a review-blocking heuristic. Operators who want tighter
# bounds (e.g. CI) can override via ARAGORA_PDB_SLOT_TIMEOUT_SECONDS.
_DEFAULT_SLOT_TIMEOUT_SECONDS = 300.0

FAMILY_CLAUDE = "claude"
FAMILY_GPT = "gpt"
FAMILY_GEMINI = "gemini"
FAMILY_GROK = "grok"
FAMILY_DEEPSEEK = "deepseek"
FAMILY_KIMI = "kimi"
FAMILY_QWEN = "qwen"
FAMILY_MISTRAL = "mistral"

WIRED_FAMILIES: frozenset[str] = frozenset(
    {
        FAMILY_CLAUDE,
        FAMILY_GPT,
        FAMILY_GEMINI,
        FAMILY_GROK,
        FAMILY_DEEPSEEK,
        FAMILY_KIMI,
        FAMILY_QWEN,
        FAMILY_MISTRAL,
    }
)
"""Families the Phase B invoker dispatches to real agents.

A family appears in ``WIRED_FAMILIES`` whenever the module knows *how*
to dispatch to it. Whether the slot is actually live for a given brief
is the product of ``WIRED_FAMILIES`` × ``unavailable_slots`` × the
runtime agent registration in :class:`RealProviderInvoker`.
"""

HETERODOX_FAMILIES: frozenset[str] = frozenset(
    {
        FAMILY_GEMINI,
        FAMILY_GROK,
        FAMILY_DEEPSEEK,
        FAMILY_KIMI,
        FAMILY_QWEN,
        FAMILY_MISTRAL,
    }
)
"""Families considered heterodox/regulatory (everything but Claude+GPT).

Preserved as a public set so the factory and tests can reason about
which slots are optional vs. required, even though the invoker no
longer short-circuits them automatically — a heterodox slot is live
iff its family's API key is set *and* an agent instance is registered.
"""

OPENROUTER_BACKED_FAMILIES: frozenset[str] = frozenset({FAMILY_DEEPSEEK, FAMILY_KIMI, FAMILY_QWEN})
"""Families that share a single :data:`OPENROUTER_API_KEY` credential."""


# Conservative per-model rates (USD per 1M tokens). Kept minimal and
# self-contained rather than reusing the full billing pipeline so the
# invoker has a predictable, test-friendly cost surface.
#
# Sources consulted (April 2026):
# - Anthropic pricing page (Claude Opus / Sonnet / Haiku tiers)
# - OpenAI pricing page (GPT-5 / GPT-4.1 family)
# - Google Gemini API pricing (Gemini 3.1 Pro / 3 Flash)
# - xAI docs (Grok 4 / 4.2 pricing)
# - OpenRouter model catalog (DeepSeek chat, Moonshot Kimi K3 and legacy K2,
#   Qwen3-235B-A22B and Qwen3 Max variants)
# - Mistral La Plateforme pricing (Mistral Large 2411 / 2512)
_PRICE_PER_MTOK: Mapping[str, tuple[float, float]] = {
    # Anthropic
    # Live catalog 2026-07-16 (enforced by tests/models/test_catalog.py).
    "claude-fable-5": (10.00, 50.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-opus-4.8": (5.00, 25.00),
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4.7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4": (5.00, 25.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-haiku-3": (0.25, 1.25),
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-haiku-4.5": (1.00, 5.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    # OpenAI
    "gpt-5.6-sol": (5.00, 30.00),
    "gpt-5.5": (5.00, 30.00),  # repriced by provider ~2026-07-14
    "gpt-5.4": (2.50, 10.00),
    "gpt-5.4-pro": (5.00, 20.00),
    "gpt-5.3": (2.50, 10.00),
    "gpt-5.3-chat-latest": (2.50, 10.00),
    "gpt-5.3-codex": (2.50, 10.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    # Google Gemini (direct API). Gemini 3.1 Pro uses the standard text tier.
    "gemini-3.1-pro-preview": (2.00, 12.00),
    "gemini-3.1-pro": (2.00, 12.00),
    "gemini-3-pro-preview": (1.25, 10.00),
    "gemini-3-pro": (1.25, 10.00),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3-flash-preview": (0.30, 2.50),
    "gemini-3-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.0-flash": (0.15, 0.60),
    "gemini-2.0-flash-001": (0.15, 0.60),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-1.5-flash": (0.075, 0.30),
    # xAI Grok. Prices verified against https://docs.x.ai/developers/models
    # (April 2026). Grok 4.20 tier is $2.00/$6.00 per 1M tokens; the
    # fast-reasoning tier is $0.20/$0.50. ``grok-4.2`` is NOT a valid
    # model id — it is retained only as a legacy alias for callers that
    # still reference the old default.
    "grok-4.5": (2.00, 6.00),
    "grok-4.3": (1.25, 2.50),
    "grok-4.20-0309-reasoning": (2.00, 6.00),
    "grok-4.20-0309-non-reasoning": (2.00, 6.00),
    "grok-4.20-multi-agent-0309": (2.00, 6.00),
    "grok-4.20": (2.00, 6.00),
    "grok-4.2": (2.00, 6.00),
    "grok-4-2": (2.00, 6.00),
    "grok-4": (3.00, 15.00),
    "grok-4-latest": (3.00, 15.00),
    "grok-4-0709": (3.00, 15.00),
    "grok-4-fast": (0.20, 0.50),
    "grok-4-1-fast": (0.20, 0.50),
    "grok-4-1-fast-reasoning": (0.20, 0.50),
    "grok-4-1-fast-non-reasoning": (0.20, 0.50),
    "grok-4-fast-reasoning": (0.20, 0.50),
    "grok-3": (2.00, 10.00),
    # OpenRouter-routed families. Prices are what OpenRouter passes
    # through (plus the standard platform markup); both the ``family/``
    # and un-prefixed forms below work because ``estimate_cost_usd``
    # strips provider prefixes before lookup.
    "deepseek-v4-pro": (1.74, 3.48),
    # Legacy DeepSeek aliases are retained for older env overrides and
    # historical receipts, but new defaults should use ``deepseek-v4-pro``.
    "deepseek-chat": (0.27, 1.10),
    "deepseek-chat-v3-0324": (0.27, 1.10),
    "deepseek-chat-v3.1": (0.27, 1.10),
    "deepseek-v3.2": (0.27, 1.10),
    "deepseek-v3.2-exp": (0.27, 1.10),
    "deepseek-r1": (0.55, 2.19),
    "deepseek-reasoner": (0.55, 2.19),
    "kimi-k3": (3.00, 15.00),
    "kimi-k2.7-code": (0.71, 3.50),
    "kimi-k2.6": (0.7448, 4.655),
    "kimi-k2.5": (0.44, 2.00),
    "kimi-k2": (0.57, 2.30),
    "kimi-k2-0905": (0.57, 2.30),
    "kimi-k2-thinking": (0.57, 2.30),
    "moonshot-v1-128k": (0.57, 2.30),
    "qwen3.8-max": (2.00, 6.00),
    "qwen3-235b-a22b": (0.14, 0.28),
    "qwen3-max": (0.60, 1.80),
    "qwen3.7-max": (1.475, 4.425),
    "qwen3.5-plus-02-15": (0.60, 1.80),
    "qwen-2.5-72b-instruct": (0.30, 0.80),
    "sonar-reasoning-pro": (2.00, 8.00),
    "command-a": (2.50, 10.00),
    "command-a-03-2025": (2.50, 10.00),
    "jamba-large-1.7": (2.00, 8.00),
    "jamba-large": (2.00, 8.00),
    # Mistral (direct API)
    "mistral-large-2512": (2.00, 6.00),
    "mistral-large-2411": (2.00, 6.00),
    "mistral-large-latest": (2.00, 6.00),
    "mistral-medium-latest": (0.40, 2.00),
    "mistral-small-latest": (0.10, 0.30),
    "codestral-latest": (0.30, 0.90),
    "codestral-2501": (0.30, 0.90),
    "ministral-8b-latest": (0.10, 0.10),
    "ministral-3b-latest": (0.04, 0.04),
}


def estimate_cost_usd(
    *,
    model: str,
    tokens_in: int,
    tokens_out: int,
) -> float:
    """Return a best-effort USD cost for a model call.

    Unknown models log once and return ``0.0`` so the budget layer
    never crashes on an unrecognised response. Both token counts are
    normalised to ``max(0, value)`` so a malformed usage dict cannot
    produce negative cost.
    """
    tokens_in = max(0, int(tokens_in or 0))
    tokens_out = max(0, int(tokens_out or 0))
    spec = by_any_id(model)
    if spec is not None:
        # Tier-aware catalog rates (documented long-context pricing);
        # identical to the flat row below the threshold.
        in_price, out_price = spec.rates_for(tokens_in)
        cost = (tokens_in / 1_000_000.0) * in_price + (tokens_out / 1_000_000.0) * out_price
        return round(cost, 6)
    rates = _PRICE_PER_MTOK.get(model)
    if rates is None:
        # Strip provider prefixes (``anthropic/...`` etc.) and try again.
        stripped = model.split("/", 1)[-1] if model else model
        rates = _PRICE_PER_MTOK.get(stripped)
    if rates is None:
        logger.warning(
            "pdb.real_invoker: no price entry for model %r; recording cost=0.0",
            model,
        )
        return 0.0
    in_price, out_price = rates
    cost = (tokens_in / 1_000_000.0) * in_price + (tokens_out / 1_000_000.0) * out_price
    return round(cost, 6)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProviderUnavailableError(RuntimeError):
    """Raised when a slot's family has no wired provider.

    The executor in :mod:`aragora.pdb.protocol` catches this from
    per-slot phases and records the slot in ``degrade_reasons`` /
    ``missing_slots`` without tearing down the whole brief — as long
    as the slot is optional and the heterogeneity floor still holds.
    """

    def __init__(self, slot_id: str, family: str, reason: str) -> None:
        self.slot_id = slot_id
        self.family = family
        self.reason = reason
        super().__init__(f"slot {slot_id!r} (family {family!r}) is unavailable: {reason}")


# ---------------------------------------------------------------------------
# Minimal structural type for the agents we consume
# ---------------------------------------------------------------------------


class _AgentLike(_TypingProtocol):
    """The tiny surface of :class:`APIAgent` the invoker actually touches.

    Narrowed to make tests trivial: any object with ``model``,
    ``last_tokens_in``, ``last_tokens_out`` and an async ``generate``
    method satisfies the contract.
    """

    model: str
    last_tokens_in: int
    last_tokens_out: int

    async def generate(self, prompt: str, context: Any = None, **kwargs: Any) -> str: ...


# ---------------------------------------------------------------------------
# Invoker
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _AgentCallResult:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float


class RealProviderInvoker:
    """Phase A + B :class:`aragora.pdb.protocol.ProviderInvoker` implementation.

    Parameters
    ----------
    claude:
        An :class:`AnthropicAPIAgent`-like object, or ``None`` if the
        Anthropic core slot should be treated as unavailable.
    gpt:
        An :class:`OpenAIAPIAgent`-like object, or ``None`` if the
        OpenAI core slot should be treated as unavailable.
    gemini:
        A :class:`GeminiAgent`-like object for the ``gemini_heterodox``
        slot, or ``None`` if Gemini should be treated as unavailable.
    grok:
        A :class:`GrokAgent`-like object, or ``None``.
    deepseek:
        An :class:`OpenRouterAgent`-like object targeting a DeepSeek
        model, or ``None``.
    kimi:
        An :class:`OpenRouterAgent`-like object targeting a Moonshot
        Kimi model, or ``None``.
    qwen:
        An :class:`OpenRouterAgent`-like object targeting a Qwen model,
        or ``None``.
    mistral:
        A :class:`MistralAPIAgent`-like object, or ``None``.
    unavailable_slots:
        Optional override marking specific slot ids as unavailable
        regardless of family routing (used by the factory when a
        family-specific env var is absent).
    """

    def __init__(
        self,
        *,
        claude: _AgentLike | None = None,
        gpt: _AgentLike | None = None,
        gemini: _AgentLike | None = None,
        grok: _AgentLike | None = None,
        deepseek: _AgentLike | None = None,
        kimi: _AgentLike | None = None,
        qwen: _AgentLike | None = None,
        mistral: _AgentLike | None = None,
        unavailable_slots: frozenset[str] = frozenset(),
    ) -> None:
        self._agents: dict[str, _AgentLike | None] = {
            FAMILY_CLAUDE: claude,
            FAMILY_GPT: gpt,
            FAMILY_GEMINI: gemini,
            FAMILY_GROK: grok,
            FAMILY_DEEPSEEK: deepseek,
            FAMILY_KIMI: kimi,
            FAMILY_QWEN: qwen,
            FAMILY_MISTRAL: mistral,
        }
        self._unavailable_slots = frozenset(unavailable_slots)

    # ------------------------------------------------------------------
    # Public surface — ProviderInvoker protocol methods
    # ------------------------------------------------------------------

    def findings(
        self,
        *,
        slot: PDBPanelSlot,
        provider: str,
        prompt: str,
        binding: PRReviewBinding,
    ) -> SlotFindingsResponse:
        """Run the findings phase for a single slot."""
        self._assert_available(slot)
        agent = self._require_agent(slot)
        call = self._call_agent(agent, prompt)
        parsed = parse_findings_response(call.text, slot_id=slot.slot_id)

        top_findings = _to_findings_tuple(parsed["top_findings"], slot_id=slot.slot_id)
        confidence = float(parsed["confidence"])
        # If the response failed to parse, hold confidence at 0 so the
        # builder's weighted policy cannot treat garbage as signal.
        if not parsed["parsed"]:
            confidence = 0.0

        return SlotFindingsResponse(
            slot_id=slot.slot_id,
            provider=provider,
            model=call.model,
            position=parsed["position"],
            confidence=confidence,
            summary=parsed["summary"],
            top_findings=top_findings,
            contested_finding_ids=tuple(parsed["contested_finding_ids"]),
            reason=parsed["reason"] or parsed["summary"],
            latency_ms=call.latency_ms,
            cost_usd=call.cost_usd,
        )

    def critique(
        self,
        *,
        slot: PDBPanelSlot,
        provider: str,
        prompt: str,
        peer_findings: Mapping[str, SlotFindingsResponse],
        binding: PRReviewBinding,
    ) -> SlotCritiqueResponse:
        """Run the critique phase for a single slot."""
        self._assert_available(slot)
        agent = self._require_agent(slot)
        call = self._call_agent(agent, prompt)
        parsed = parse_critique_response(call.text, slot_id=slot.slot_id)

        confidence = float(parsed["confidence"])
        if not parsed["parsed"]:
            confidence = 0.0

        return SlotCritiqueResponse(
            slot_id=slot.slot_id,
            provider=provider,
            position=parsed["position"],
            confidence=confidence,
            reason=parsed["reason"],
            agrees_with=tuple(parsed["agrees_with"]),
            disagrees_with=tuple(parsed["disagrees_with"]),
            contested_finding_ids=tuple(parsed["contested_finding_ids"]),
            latency_ms=call.latency_ms,
            cost_usd=call.cost_usd,
        )

    def synthesize(
        self,
        *,
        synthesizer_slot: PDBPanelSlot,
        provider: str,
        prompt: str,
        votes: Sequence[PanelVote],
        binding: PRReviewBinding,
    ) -> SynthesisResponse:
        """Run the synthesis pass."""
        self._assert_available(synthesizer_slot)
        agent = self._require_agent(synthesizer_slot)
        call = self._call_agent(agent, prompt)
        parsed = parse_synthesis_response(call.text)

        # The synthesizer's position for :class:`SynthesisResponse` is
        # a derived view: we pick the majority :class:`DissentPosition`
        # across the panel votes so a malformed synthesis cannot flip
        # the brief's recommendation. The builder still computes the
        # final :class:`Recommendation` deterministically from the
        # votes; this field is informational only.
        majority_position = _majority_position(votes)
        # We don't ask the synthesizer for a confidence score in the
        # prompt; use a mid-range default when parsing succeeded so
        # the synthesizer's SYNTHESIZER-role vote does not dominate
        # the builder's weighted aggregation. A parse failure zeros
        # the confidence so the builder ignores it.
        confidence = 0.6 if parsed["parsed"] else 0.0

        return SynthesisResponse(
            slot_id=synthesizer_slot.slot_id,
            provider=provider,
            model=call.model,
            top_line=parsed["top_line"],
            validation_summary=parsed["validation_summary"],
            position=majority_position,
            confidence=confidence,
            preserved_dissent=tuple(parsed["preserved_dissent"]),
            latency_ms=call.latency_ms,
            cost_usd=call.cost_usd,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _assert_available(self, slot: PDBPanelSlot) -> None:
        """Raise :class:`ProviderUnavailableError` if ``slot`` is not wired.

        Order of checks:

        1. Slot id is on the factory-supplied ``unavailable_slots`` set
           (the env-var did not surface an API key for this slot).
        2. The family has no wiring in this module at all — that's a
           config bug, not a missing key.
        3. The family is wired but no agent instance was registered
           at construction time.
        """
        if slot.slot_id in self._unavailable_slots:
            raise ProviderUnavailableError(
                slot_id=slot.slot_id,
                family=slot.family,
                reason="slot marked unavailable by invoker factory (no API key)",
            )
        if slot.family not in WIRED_FAMILIES:
            raise ProviderUnavailableError(
                slot_id=slot.slot_id,
                family=slot.family,
                reason=f"family {slot.family!r} has no wiring in RealProviderInvoker",
            )
        if self._agents.get(slot.family) is None:
            raise ProviderUnavailableError(
                slot_id=slot.slot_id,
                family=slot.family,
                reason=f"no agent instance registered for family {slot.family!r}",
            )

    def _require_agent(self, slot: PDBPanelSlot) -> _AgentLike:
        agent = self._agents.get(slot.family)
        if agent is None:
            # _assert_available runs before this, so this is defensive.
            raise ProviderUnavailableError(
                slot_id=slot.slot_id,
                family=slot.family,
                reason="agent reference is None at call time",
            )
        return agent

    def _call_agent(self, agent: _AgentLike, prompt: str) -> _AgentCallResult:
        """Invoke ``agent.generate`` synchronously with latency + cost tracking."""
        start = time.monotonic()
        timeout_seconds = _slot_timeout_seconds()
        try:
            text = _run_sync(agent.generate(prompt), timeout_seconds=timeout_seconds)
        except (TimeoutError, asyncio.TimeoutError) as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "pdb.real_invoker: agent call timed out after %.1fs (model=%r)",
                timeout_seconds,
                getattr(agent, "model", "unknown"),
            )
            raise TimeoutError(f"provider call timed out after {timeout_seconds:.1f}s") from exc
        except Exception:
            latency_ms = int((time.monotonic() - start) * 1000)
            logger.warning(
                "pdb.real_invoker: agent call raised after %dms (model=%r)",
                latency_ms,
                getattr(agent, "model", "unknown"),
            )
            raise
        latency_ms = int((time.monotonic() - start) * 1000)
        tokens_in = int(getattr(agent, "last_tokens_in", 0) or 0)
        tokens_out = int(getattr(agent, "last_tokens_out", 0) or 0)
        model = str(getattr(agent, "model", "unknown"))
        cost = estimate_cost_usd(model=model, tokens_in=tokens_in, tokens_out=tokens_out)
        return _AgentCallResult(
            text=text or "",
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            cost_usd=cost,
        )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _slot_timeout_seconds() -> float:
    """Return the per-slot timeout for live provider calls.

    The default keeps a single slow provider from wedging the entire
    Protocol B run indefinitely. Operators can tune the bound via
    ``ARAGORA_PDB_SLOT_TIMEOUT_SECONDS`` when dogfooding or running
    in production-like environments.
    """
    raw = os.environ.get(_SLOT_TIMEOUT_ENV, "").strip()
    if not raw:
        return _DEFAULT_SLOT_TIMEOUT_SECONDS
    try:
        parsed = float(raw)
    except ValueError:
        logger.warning(
            "pdb.real_invoker: invalid %s=%r; using default %.1fs",
            _SLOT_TIMEOUT_ENV,
            raw,
            _DEFAULT_SLOT_TIMEOUT_SECONDS,
        )
        return _DEFAULT_SLOT_TIMEOUT_SECONDS
    if parsed <= 0:
        logger.warning(
            "pdb.real_invoker: non-positive %s=%r; using default %.1fs",
            _SLOT_TIMEOUT_ENV,
            raw,
            _DEFAULT_SLOT_TIMEOUT_SECONDS,
        )
        return _DEFAULT_SLOT_TIMEOUT_SECONDS
    return parsed


def _run_sync(coro: Any, *, timeout_seconds: float) -> str:
    """Run ``coro`` on a fresh event loop and return its string result.

    The worker's :func:`asyncio.to_thread` already ensures this helper
    runs on a thread distinct from the worker's event loop, so
    :func:`asyncio.run` is safe here. Returning an empty string on
    ``None`` keeps the downstream parsers happy.
    """

    async def _runner() -> Any:
        return await asyncio.wait_for(coro, timeout=timeout_seconds)

    result = asyncio.run(_runner())
    if result is None:
        return ""
    return str(result)


def _to_findings_tuple(
    findings: Sequence[Mapping[str, Any]],
    *,
    slot_id: str,
) -> tuple[PRReviewFinding, ...]:
    """Build :class:`PRReviewFinding` instances from parsed finding dicts."""
    out: list[PRReviewFinding] = []
    for idx, raw in enumerate(findings):
        finding_id = str(raw.get("finding_id") or f"{slot_id}-F{idx + 1}")
        out.append(
            PRReviewFinding(
                finding_id=finding_id,
                category=str(raw.get("category") or "general"),
                severity=str(raw.get("severity") or "medium"),
                summary=str(raw.get("summary") or ""),
                evidence=list(raw.get("evidence") or []),
                source=f"slot:{slot_id}",
            )
        )
    return tuple(out)


def _majority_position(votes: Sequence[PanelVote]) -> DissentPosition:
    """Return the most-common :class:`DissentPosition` across votes.

    On a tie we return ``DEFER`` so the synthesizer's informational
    position reflects the panel-level uncertainty rather than an
    accidental approve.
    """
    if not votes:
        return DissentPosition.DEFER
    counts: dict[DissentPosition, int] = {}
    for vote in votes:
        counts[vote.position] = counts.get(vote.position, 0) + 1
    top = max(counts.values())
    winners = [pos for pos, n in counts.items() if n == top]
    if len(winners) == 1:
        return winners[0]
    return DissentPosition.DEFER
