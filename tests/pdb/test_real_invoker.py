"""Tests for :mod:`aragora.pdb.real_invoker`.

Covers:

- happy-path findings / critique / synthesis dispatch for Claude + GPT
- heterodox families raise :class:`ProviderUnavailableError`
- cost + latency recorded from the agent's ``last_tokens_*`` counters
- malformed provider responses still produce a valid dataclass
- end-to-end integration with :func:`aragora.pdb.protocol.run_protocol_b`
  using mocked agent clients — no real network calls
"""

from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence
from unittest.mock import MagicMock

import pytest

from aragora.billing.usage import PROVIDER_PRICING
from aragora.pdb.budget import PDBBudgetLedger
from aragora.pdb.panel_config import (
    PDBBudgetConfig,
    PDBPanelConfig,
    PDBPanelDefinition,
    PDBPanelSlot,
    PDBPromptSet,
)
from aragora.pdb.protocol import (
    PDBExecutionInput,
    PDBExecutionStatus,
    SlotCritiqueResponse,
    SlotFindingsResponse,
    SynthesisResponse,
    run_protocol_b,
)
from aragora.pdb.real_invoker import (
    FAMILY_CLAUDE,
    FAMILY_DEEPSEEK,
    FAMILY_GEMINI,
    FAMILY_GPT,
    FAMILY_GROK,
    FAMILY_KIMI,
    FAMILY_MISTRAL,
    FAMILY_QWEN,
    HETERODOX_FAMILIES,
    OPENROUTER_BACKED_FAMILIES,
    WIRED_FAMILIES,
    ProviderUnavailableError,
    RealProviderInvoker,
    _PRICE_PER_MTOK,
    estimate_cost_usd,
)
from aragora.review.builder import PanelVote
from aragora.review.policy import ReviewBudget, ReviewPolicy
from aragora.review.protocol import DissentPosition, ReviewBrief, ReviewRole, RoleFinding
from aragora.review.provider_slots import (
    ProviderSlotAvailabilitySummary,
    ProviderSlotDefinition,
    ProviderSlotResolution,
    ProviderSlotResolver,
)
from aragora.swarm.pr_review_protocol import (
    PRReviewBinding,
    PRReviewProtocol,
    PRReviewProtocolPacket,
    PROTOCOL_STATUS,
    PROTOCOL_VERSION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _slot(
    slot_id: str,
    *,
    family: str,
    review_role: str = "logic_reviewer",
    lens: str = "core",
    required: bool = False,
) -> PDBPanelSlot:
    return PDBPanelSlot(
        slot_id=slot_id,
        review_role=review_role,
        lens=lens,
        family=family,
        candidates=(f"{family}-cli",),
        required=required,
    )


def _binding() -> PRReviewBinding:
    return PRReviewBinding(
        repo="synaptent/aragora",
        pr_number=4242,
        base_sha="base0000",
        head_sha="head1111",
    )


def _make_mock_agent(
    *,
    model: str = "claude-sonnet-4-6",
    response_text: str = '{"recommendation": "approve", "confidence": 0.8}',
    tokens_in: int = 1000,
    tokens_out: int = 500,
) -> MagicMock:
    """Build a MagicMock that mimics the :class:`_AgentLike` contract.

    We assign ``last_tokens_in`` / ``last_tokens_out`` directly as
    attributes (not as Mock auto-children) so ``int(...)`` on them
    produces the expected numeric value.
    """
    mock = MagicMock()
    mock.model = model
    mock.last_tokens_in = tokens_in
    mock.last_tokens_out = tokens_out

    async def _generate(prompt: str, context: Any = None, **kwargs: Any) -> str:
        return response_text

    mock.generate.side_effect = _generate
    return mock


def _findings_payload_json(position: str = "approve", slot_id: str = "claude_core") -> str:
    return (
        f'{{"recommendation": "{position}", "confidence": 0.85, '
        f'"top_findings": [{{"finding_id": "{slot_id}-F1", "category": "logic", '
        f'"severity": "medium", "summary": "Looks fine.", "evidence": []}}], '
        f'"contested_finding_ids": [], '
        f'"reason": "Code reads correct."}}'
    )


def _critique_payload_json(position: str = "approve") -> str:
    return (
        f'{{"recommendation": "{position}", "confidence": 0.7, '
        f'"agrees_with": [], "disagrees_with": [], '
        f'"contested_finding_ids": [], "reason": "I stand by {position}."}}'
    )


def _synthesis_payload_json() -> str:
    return (
        '{"top_line": "Panel consensus: approve with minor notes.", '
        '"validation_summary": "CI green; no dissent.", '
        '"preserved_dissent": []}'
    )


# ---------------------------------------------------------------------------
# Cost estimator
# ---------------------------------------------------------------------------


class TestEstimateCostUsd:
    def test_known_anthropic_model(self) -> None:
        # 1M in + 1M out at (3, 15) → 18 USD
        cost = estimate_cost_usd(
            model="claude-sonnet-4-6", tokens_in=1_000_000, tokens_out=1_000_000
        )
        assert cost == pytest.approx(18.0)

    def test_known_openai_model(self) -> None:
        cost = estimate_cost_usd(model="gpt-5.5", tokens_in=1_000_000, tokens_out=1_000_000)
        # (5.00, 30.00) → 35.00 (live catalog 2026-07-16; provider repriced)
        assert cost == pytest.approx(35.0)

    def test_qwen37_max_priced_not_free(self) -> None:
        # (1.475, 4.425) → 5.90 (live catalog 2026-07-16; provider raised the
        # rate from 1.25/3.75); the quorum-reviewer default must never hit the
        # $0.00 unknown-model path (#9073 P2).
        cost = estimate_cost_usd(
            model="qwen/qwen3.7-max", tokens_in=1_000_000, tokens_out=1_000_000
        )
        assert cost == pytest.approx(5.9)

    def test_qwen38_max_priced_not_free(self) -> None:
        cost = estimate_cost_usd(
            model="qwen/qwen3.8-max", tokens_in=1_000_000, tokens_out=1_000_000
        )
        assert cost == pytest.approx(8.0)

    def test_unknown_model_returns_zero(self) -> None:
        cost = estimate_cost_usd(model="unknown-model", tokens_in=1000, tokens_out=500)
        assert cost == 0.0

    def test_handles_provider_prefix(self) -> None:
        cost = estimate_cost_usd(
            model="anthropic/claude-sonnet-4-6",
            tokens_in=1_000_000,
            tokens_out=0,
        )
        assert cost == pytest.approx(3.0)

    def test_negative_tokens_clamped(self) -> None:
        cost = estimate_cost_usd(model="gpt-5.5", tokens_in=-100, tokens_out=-100)
        assert cost == 0.0


# ---------------------------------------------------------------------------
# Unavailability
# ---------------------------------------------------------------------------


class TestProviderUnavailable:
    def test_heterodox_families_raise(self) -> None:
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(model="gpt-5.5"),
        )
        for family in HETERODOX_FAMILIES:
            slot = _slot(f"{family}_slot", family=family, lens="heterodox")
            with pytest.raises(ProviderUnavailableError) as exc:
                invoker.findings(
                    slot=slot,
                    provider="some-provider",
                    prompt="p",
                    binding=_binding(),
                )
            assert exc.value.family == family
            assert exc.value.slot_id == f"{family}_slot"

    def test_missing_claude_agent_raises_on_claude_slot(self) -> None:
        invoker = RealProviderInvoker(claude=None, gpt=_make_mock_agent())
        slot = _slot("claude_core", family=FAMILY_CLAUDE, required=True)
        with pytest.raises(ProviderUnavailableError):
            invoker.findings(slot=slot, provider="claude", prompt="p", binding=_binding())

    def test_unavailable_slots_override_respected(self) -> None:
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
            unavailable_slots=frozenset({"claude_core"}),
        )
        slot = _slot("claude_core", family=FAMILY_CLAUDE, required=True)
        with pytest.raises(ProviderUnavailableError) as exc:
            invoker.findings(slot=slot, provider="claude", prompt="p", binding=_binding())
        assert "no API key" in exc.value.reason


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


class TestFindings:
    def test_claude_findings_parses_and_dispatches(self) -> None:
        agent = _make_mock_agent(
            model="claude-sonnet-4-6",
            response_text=_findings_payload_json(slot_id="claude_core"),
            tokens_in=2000,
            tokens_out=500,
        )
        invoker = RealProviderInvoker(claude=agent, gpt=_make_mock_agent())
        slot = _slot("claude_core", family=FAMILY_CLAUDE, required=True)

        result = invoker.findings(
            slot=slot,
            provider="claude",
            prompt="findings prompt here",
            binding=_binding(),
        )

        assert isinstance(result, SlotFindingsResponse)
        assert result.slot_id == "claude_core"
        assert result.provider == "claude"
        assert result.model == "claude-sonnet-4-6"
        assert result.position is DissentPosition.APPROVE
        assert result.confidence == 0.85
        assert result.summary  # non-empty
        assert len(result.top_findings) == 1
        assert result.top_findings[0].finding_id == "claude_core-F1"
        # cost & latency recorded
        assert result.cost_usd > 0
        assert result.latency_ms >= 0
        # The mock agent was actually called once with the prompt.
        agent.generate.assert_called_once()

    def test_gpt_findings_parses_and_dispatches(self) -> None:
        agent = _make_mock_agent(
            model="gpt-5.5",
            response_text=_findings_payload_json("request_changes", slot_id="gpt_core"),
            tokens_in=1500,
            tokens_out=400,
        )
        invoker = RealProviderInvoker(claude=_make_mock_agent(), gpt=agent)
        slot = _slot("gpt_core", family=FAMILY_GPT, review_role="security_reviewer", required=True)

        result = invoker.findings(slot=slot, provider="openai-api", prompt="p", binding=_binding())
        assert result.position is DissentPosition.REQUEST_CHANGES
        assert result.cost_usd > 0

    def test_gemini_findings_dispatch(self) -> None:
        agent = _make_mock_agent(
            model="gemini-3.1-pro-preview",
            response_text=_findings_payload_json("approve", slot_id="gemini_heterodox"),
            tokens_in=1200,
            tokens_out=600,
        )
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
            gemini=agent,
        )
        slot = _slot(
            "gemini_heterodox",
            family=FAMILY_GEMINI,
            review_role="maintainability_reviewer",
            lens="heterodox",
        )
        result = invoker.findings(slot=slot, provider="gemini", prompt="p", binding=_binding())
        assert isinstance(result, SlotFindingsResponse)
        assert result.model == "gemini-3.1-pro-preview"
        assert result.slot_id == "gemini_heterodox"
        assert result.position is DissentPosition.APPROVE
        assert result.cost_usd > 0
        assert result.latency_ms >= 0
        agent.generate.assert_called_once()

    def test_grok_findings_dispatch(self) -> None:
        agent = _make_mock_agent(
            model="grok-4.2",
            response_text=_findings_payload_json("request_changes", slot_id="grok_heterodox"),
            tokens_in=800,
            tokens_out=400,
        )
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
            grok=agent,
        )
        slot = _slot(
            "grok_heterodox",
            family=FAMILY_GROK,
            review_role="skeptic",
            lens="heterodox",
        )
        result = invoker.findings(slot=slot, provider="grok", prompt="p", binding=_binding())
        assert isinstance(result, SlotFindingsResponse)
        assert result.model == "grok-4.2"
        assert result.position is DissentPosition.REQUEST_CHANGES
        assert result.cost_usd > 0

    def test_deepseek_findings_dispatch(self) -> None:
        agent = _make_mock_agent(
            model="deepseek/deepseek-v4-pro",
            response_text=_findings_payload_json("approve", slot_id="deepseek_heterodox"),
            tokens_in=1000,
            tokens_out=500,
        )
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
            deepseek=agent,
        )
        slot = _slot(
            "deepseek_heterodox",
            family=FAMILY_DEEPSEEK,
            review_role="skeptic",
            lens="heterodox",
        )
        result = invoker.findings(slot=slot, provider="deepseek", prompt="p", binding=_binding())
        assert result.model == "deepseek/deepseek-v4-pro"
        # Provider-prefixed models resolve through the price table too.
        assert result.cost_usd > 0

    def test_kimi_findings_dispatch(self) -> None:
        agent = _make_mock_agent(
            model="moonshotai/kimi-k3",
            response_text=_findings_payload_json("approve", slot_id="kimi_heterodox"),
            tokens_in=1500,
            tokens_out=700,
        )
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
            kimi=agent,
        )
        slot = _slot(
            "kimi_heterodox",
            family=FAMILY_KIMI,
            review_role="skeptic",
            lens="heterodox",
        )
        result = invoker.findings(slot=slot, provider="kimi", prompt="p", binding=_binding())
        assert result.model == "moonshotai/kimi-k3"
        assert result.cost_usd > 0

    def test_qwen_findings_dispatch(self) -> None:
        agent = _make_mock_agent(
            model="qwen/qwen3-235b-a22b",
            response_text=_findings_payload_json("approve", slot_id="qwen_heterodox"),
            tokens_in=2000,
            tokens_out=1000,
        )
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
            qwen=agent,
        )
        slot = _slot(
            "qwen_heterodox",
            family=FAMILY_QWEN,
            review_role="skeptic",
            lens="heterodox",
        )
        result = invoker.findings(slot=slot, provider="qwen", prompt="p", binding=_binding())
        assert result.model == "qwen/qwen3-235b-a22b"
        assert result.cost_usd > 0

    def test_mistral_findings_dispatch(self) -> None:
        agent = _make_mock_agent(
            model="mistral-large-2512",
            response_text=_findings_payload_json("request_changes", slot_id="mistral_regulatory"),
            tokens_in=1800,
            tokens_out=900,
        )
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
            mistral=agent,
        )
        slot = _slot(
            "mistral_regulatory",
            family=FAMILY_MISTRAL,
            review_role="skeptic",
            lens="regulatory",
        )
        result = invoker.findings(slot=slot, provider="mistral-api", prompt="p", binding=_binding())
        assert isinstance(result, SlotFindingsResponse)
        assert result.model == "mistral-large-2512"
        assert result.position is DissentPosition.REQUEST_CHANGES
        assert result.cost_usd > 0

    def test_malformed_response_yields_safe_dataclass(self) -> None:
        agent = _make_mock_agent(
            model="claude-sonnet-4-6",
            response_text="I refuse to output JSON.",
        )
        invoker = RealProviderInvoker(claude=agent, gpt=_make_mock_agent())
        slot = _slot("claude_core", family=FAMILY_CLAUDE, required=True)

        result = invoker.findings(slot=slot, provider="claude", prompt="p", binding=_binding())
        assert isinstance(result, SlotFindingsResponse)
        assert result.confidence == 0.0  # zero when parse fails
        assert result.position is DissentPosition.DEFER
        assert result.top_findings == ()

    def test_agent_exception_propagates(self) -> None:
        agent = MagicMock()
        agent.model = "claude-sonnet-4-6"
        agent.last_tokens_in = 0
        agent.last_tokens_out = 0

        async def _boom(prompt: str, context: Any = None, **kwargs: Any) -> str:
            raise RuntimeError("upstream timeout")

        agent.generate.side_effect = _boom
        invoker = RealProviderInvoker(claude=agent, gpt=_make_mock_agent())
        slot = _slot("claude_core", family=FAMILY_CLAUDE, required=True)
        with pytest.raises(RuntimeError, match="upstream timeout"):
            invoker.findings(slot=slot, provider="claude", prompt="p", binding=_binding())

    def test_agent_timeout_is_bounded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        agent = MagicMock()
        agent.model = "claude-sonnet-4-6"
        agent.last_tokens_in = 0
        agent.last_tokens_out = 0

        async def _stall(prompt: str, context: Any = None, **kwargs: Any) -> str:
            await asyncio.sleep(0.2)
            return "never reached"

        agent.generate.side_effect = _stall
        monkeypatch.setenv("ARAGORA_PDB_SLOT_TIMEOUT_SECONDS", "0.1")

        invoker = RealProviderInvoker(claude=agent, gpt=_make_mock_agent())
        slot = _slot("claude_core", family=FAMILY_CLAUDE, required=True)
        with pytest.raises(TimeoutError, match="provider call timed out after 0.1s"):
            invoker.findings(slot=slot, provider="claude", prompt="p", binding=_binding())

    def test_agent_timeout_catches_asyncio_timeout_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        agent = MagicMock()
        agent.model = "claude-sonnet-4-6"
        agent.last_tokens_in = 0
        agent.last_tokens_out = 0

        monkeypatch.setattr(
            "aragora.pdb.real_invoker._run_sync",
            lambda _coro, *, timeout_seconds: (_ for _ in ()).throw(asyncio.TimeoutError()),
        )

        invoker = RealProviderInvoker(claude=agent, gpt=_make_mock_agent())
        slot = _slot("claude_core", family=FAMILY_CLAUDE, required=True)
        with pytest.raises(TimeoutError, match=r"provider call timed out after \d+\.\d+s"):
            invoker.findings(slot=slot, provider="claude", prompt="p", binding=_binding())


# ---------------------------------------------------------------------------
# Critique
# ---------------------------------------------------------------------------


class TestCritique:
    def test_critique_parses(self) -> None:
        agent = _make_mock_agent(
            model="claude-sonnet-4-6",
            response_text=_critique_payload_json("request_changes"),
            tokens_in=1000,
            tokens_out=300,
        )
        invoker = RealProviderInvoker(claude=agent, gpt=_make_mock_agent())
        slot = _slot("claude_core", family=FAMILY_CLAUDE, required=True)

        result = invoker.critique(
            slot=slot,
            provider="claude",
            prompt="critique prompt",
            peer_findings={},
            binding=_binding(),
        )
        assert isinstance(result, SlotCritiqueResponse)
        assert result.position is DissentPosition.REQUEST_CHANGES
        assert result.confidence == 0.7

    def test_heterodox_families_critique_dispatch(self) -> None:
        # Parametrized structural test: every family's agent is invoked
        # via the critique path and the response is parsed into a
        # valid SlotCritiqueResponse.
        fixtures = [
            (FAMILY_GEMINI, "gemini-3.1-pro-preview", "gemini"),
            (FAMILY_GROK, "grok-4.2", "grok"),
            (FAMILY_DEEPSEEK, "deepseek/deepseek-v4-pro", "deepseek"),
            (FAMILY_KIMI, "moonshotai/kimi-k3", "kimi"),
            (FAMILY_QWEN, "qwen/qwen3-235b-a22b", "qwen"),
            (FAMILY_MISTRAL, "mistral-large-2512", "mistral"),
        ]
        for family, model, provider in fixtures:
            agent = _make_mock_agent(
                model=model,
                response_text=_critique_payload_json("approve"),
                tokens_in=800,
                tokens_out=300,
            )
            invoker = RealProviderInvoker(
                claude=_make_mock_agent(),
                gpt=_make_mock_agent(),
                **{family: agent},  # type: ignore[arg-type]
            )
            slot = _slot(
                f"{family}_slot",
                family=family,
                lens="heterodox" if family != FAMILY_MISTRAL else "regulatory",
            )
            result = invoker.critique(
                slot=slot,
                provider=provider,
                prompt="p",
                peer_findings={},
                binding=_binding(),
            )
            assert isinstance(result, SlotCritiqueResponse), family
            assert result.position is DissentPosition.APPROVE, family
            assert result.cost_usd >= 0, family  # non-negative; > 0 for known models
            agent.generate.assert_called_once()


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


class TestSynthesize:
    def test_synthesize_parses(self) -> None:
        agent = _make_mock_agent(
            model="claude-sonnet-4-6",
            response_text=_synthesis_payload_json(),
            tokens_in=3000,
            tokens_out=700,
        )
        invoker = RealProviderInvoker(claude=agent, gpt=_make_mock_agent())
        slot = _slot("claude_core", family=FAMILY_CLAUDE, required=True)

        # Build a votes tuple with majority APPROVE
        votes = (
            PanelVote(
                finding=RoleFinding(
                    role=ReviewRole.LOGIC,
                    agent="claude_core:claude",
                    model="claude-sonnet-4-6",
                    confidence=0.8,
                    finding_text="",
                ),
                position=DissentPosition.APPROVE,
                reason="ok",
            ),
            PanelVote(
                finding=RoleFinding(
                    role=ReviewRole.SECURITY,
                    agent="gpt_core:openai",
                    model="gpt-5.5",
                    confidence=0.7,
                    finding_text="",
                ),
                position=DissentPosition.APPROVE,
                reason="ok",
            ),
        )
        result = invoker.synthesize(
            synthesizer_slot=slot,
            provider="claude",
            prompt="synth prompt",
            votes=votes,
            binding=_binding(),
        )
        assert isinstance(result, SynthesisResponse)
        assert "consensus" in result.top_line.lower() or "approve" in result.top_line.lower()
        assert result.position is DissentPosition.APPROVE
        assert result.cost_usd > 0

    def test_mistral_synthesize_dispatch(self) -> None:
        # Mistral is registered as a potential synthesizer only in
        # exotic configurations, but the invoker must still route a
        # synthesize() call to it if the panel yaml selects that slot.
        agent = _make_mock_agent(
            model="mistral-large-2512",
            response_text=_synthesis_payload_json(),
            tokens_in=2000,
            tokens_out=600,
        )
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
            mistral=agent,
        )
        slot = _slot(
            "mistral_regulatory",
            family=FAMILY_MISTRAL,
            lens="regulatory",
        )
        votes = (
            PanelVote(
                finding=RoleFinding(
                    role=ReviewRole.LOGIC,
                    agent="claude_core:claude",
                    model="claude-sonnet-4-6",
                    confidence=0.8,
                    finding_text="",
                ),
                position=DissentPosition.APPROVE,
                reason="ok",
            ),
        )
        result = invoker.synthesize(
            synthesizer_slot=slot,
            provider="mistral-api",
            prompt="s",
            votes=votes,
            binding=_binding(),
        )
        assert isinstance(result, SynthesisResponse)
        assert result.model == "mistral-large-2512"
        assert result.cost_usd > 0


# ---------------------------------------------------------------------------
# Availability wiring
# ---------------------------------------------------------------------------


class TestAvailabilityWiring:
    def test_heterodox_families_are_all_wired_in_phase_b(self) -> None:
        # Phase B contract: every heterodox family now lives in
        # WIRED_FAMILIES. The invoker's family-level blocking lives in
        # the agent-None check, not the family set.
        for family in HETERODOX_FAMILIES:
            assert family in WIRED_FAMILIES, family

    def test_openrouter_backed_families_disjoint_from_direct(self) -> None:
        assert OPENROUTER_BACKED_FAMILIES.issubset(HETERODOX_FAMILIES)
        assert OPENROUTER_BACKED_FAMILIES == {
            FAMILY_DEEPSEEK,
            FAMILY_KIMI,
            FAMILY_QWEN,
        }

    def test_missing_gemini_agent_raises(self) -> None:
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
            gemini=None,
        )
        slot = _slot("gemini_heterodox", family=FAMILY_GEMINI, lens="heterodox")
        with pytest.raises(ProviderUnavailableError) as exc:
            invoker.findings(slot=slot, provider="gemini", prompt="p", binding=_binding())
        assert exc.value.family == FAMILY_GEMINI
        assert "no agent instance" in exc.value.reason

    def test_unavailable_slots_override_blocks_wired_heterodox(self) -> None:
        # Even with the agent registered, an unavailable_slots entry
        # still wins — that's how the factory degrades an OpenRouter
        # slot when OPENROUTER_API_KEY is absent.
        agent = _make_mock_agent(model="qwen/qwen3-235b-a22b")
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
            qwen=agent,
            unavailable_slots=frozenset({"qwen_heterodox"}),
        )
        slot = _slot("qwen_heterodox", family=FAMILY_QWEN, lens="heterodox")
        with pytest.raises(ProviderUnavailableError) as exc:
            invoker.findings(slot=slot, provider="qwen", prompt="p", binding=_binding())
        assert "no API key" in exc.value.reason

    def test_unknown_family_raises(self) -> None:
        # A panel yaml typo ('clade' instead of 'claude') must surface
        # as a slot-level degrade, never silently dispatch to the
        # wrong agent.
        invoker = RealProviderInvoker(
            claude=_make_mock_agent(),
            gpt=_make_mock_agent(),
        )
        slot = _slot("oops", family="clade", lens="core")
        with pytest.raises(ProviderUnavailableError) as exc:
            invoker.findings(slot=slot, provider="x", prompt="p", binding=_binding())
        assert "no wiring" in exc.value.reason


# ---------------------------------------------------------------------------
# Cost tracking for the new families
# ---------------------------------------------------------------------------


class TestNewFamilyCostTracking:
    def test_gemini_3_1_pro_cost_nonzero(self) -> None:
        assert estimate_cost_usd(
            model="gemini-3.1-pro-preview",
            tokens_in=1_000_000,
            tokens_out=0,
        ) == pytest.approx(2.0)

    @pytest.mark.parametrize(
        ("provider", "model"),
        [
            ("anthropic", "claude-opus-4.8"),
            ("anthropic", "claude-haiku-3"),
            ("anthropic", "claude-haiku-4.5"),
            ("anthropic", "claude-haiku-4-5-20251001"),
            ("openai", "gpt-5.5"),
            ("google", "gemini-3.5-flash"),
            ("google", "gemini-3.1-pro"),
            ("google", "gemini-3.1-pro-preview"),
        ],
    )
    def test_calibrated_billing_rates_have_pdb_cost_entries(
        self, provider: str, model: str
    ) -> None:
        provider_prices = PROVIDER_PRICING[provider]
        expected = float(provider_prices[model] + provider_prices[f"{model}-output"])
        assert estimate_cost_usd(
            model=model,
            tokens_in=1_000_000,
            tokens_out=1_000_000,
        ) == pytest.approx(expected)

    def test_gpt_5_5_pdb_price_entry_is_explicit(self) -> None:
        assert _PRICE_PER_MTOK["gpt-5.5"] == (5.00, 30.00)

    @pytest.mark.parametrize(
        ("provider", "model"),
        [
            ("anthropic", "claude-opus-4.8"),
            ("anthropic", "claude-haiku-3"),
            ("anthropic", "claude-haiku-4.5"),
            ("anthropic", "claude-haiku-4-5-20251001"),
            ("openai", "gpt-5.5"),
            ("google", "gemini-3.5-flash"),
            ("google", "gemini-3.1-pro"),
            ("google", "gemini-3.1-pro-preview"),
        ],
    )
    def test_prefixed_calibrated_models_resolve_to_pdb_cost_entries(
        self, provider: str, model: str
    ) -> None:
        provider_prices = PROVIDER_PRICING[provider]
        expected = float(provider_prices[model] + provider_prices[f"{model}-output"])
        assert estimate_cost_usd(
            model=f"{provider}/{model}",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
        ) == pytest.approx(expected)

    def test_grok_4_cost_nonzero(self) -> None:
        # grok-4 legacy tier: (3.00, 15.00) → 18.0 at 1M/1M
        assert estimate_cost_usd(
            model="grok-4", tokens_in=1_000_000, tokens_out=1_000_000
        ) == pytest.approx(18.0)

    def test_grok_4_20_reasoning_cost_matches_published_rate(self) -> None:
        # grok-4.20-0309-reasoning (the new panel default): (2.00, 6.00)
        # → $8.00 at 1M/1M. Verified against
        # https://docs.x.ai/developers/models (April 2026).
        assert estimate_cost_usd(
            model="grok-4.20-0309-reasoning",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
        ) == pytest.approx(8.0)

    def test_deepseek_chat_cost_with_prefix(self) -> None:
        assert (
            estimate_cost_usd(
                model="deepseek/deepseek-v4-pro",
                tokens_in=1_000_000,
                tokens_out=1_000_000,
            )
            == pytest.approx(5.22)  # 1.74 + 3.48
        )

    def test_kimi_k2_cost(self) -> None:
        assert (
            estimate_cost_usd(
                model="moonshotai/kimi-k2.7-code",
                tokens_in=1_000_000,
                tokens_out=1_000_000,
            )
            == pytest.approx(4.21)  # 0.71 + 3.50 (k2.7-code, live catalog 2026-08-16)
        )

    def test_kimi_k3_cost(self) -> None:
        assert estimate_cost_usd(
            model="moonshotai/kimi-k3",
            tokens_in=1_000_000,
            tokens_out=1_000_000,
        ) == pytest.approx(18.0)

    def test_qwen3_235b_cost(self) -> None:
        assert (
            estimate_cost_usd(
                model="qwen/qwen3-235b-a22b",
                tokens_in=1_000_000,
                tokens_out=1_000_000,
            )
            == pytest.approx(0.42)  # 0.14 + 0.28
        )

    def test_mistral_large_cost(self) -> None:
        assert (
            estimate_cost_usd(
                model="mistral-large-2512",
                tokens_in=1_000_000,
                tokens_out=1_000_000,
            )
            == pytest.approx(8.0)  # 2.00 + 6.00
        )


# ---------------------------------------------------------------------------
# End-to-end: run_protocol_b + RealProviderInvoker with mocked agents
# ---------------------------------------------------------------------------


class _StubResolver(ProviderSlotResolver):
    """Resolver that returns canned resolutions without touching real agents."""

    def __init__(self, resolved: set[str], all_slots: Sequence[PDBPanelSlot]) -> None:
        self._resolved = set(resolved)
        self._slots = {s.slot_id: s for s in all_slots}

    def resolve_slot(self, slot: ProviderSlotDefinition) -> ProviderSlotResolution:
        meta = self._slots.get(slot.slot_id)
        if slot.slot_id in self._resolved and meta is not None:
            return ProviderSlotResolution(
                slot_id=slot.slot_id,
                review_role=slot.review_role,
                lens=slot.lens,
                family=slot.family,
                selected_provider=slot.candidates[0],
                status="available",
                detail="stub",
                candidates=list(slot.candidates),
            )
        return ProviderSlotResolution(
            slot_id=slot.slot_id,
            review_role=slot.review_role,
            lens=slot.lens,
            family=slot.family,
            selected_provider=None,
            status="unavailable",
            detail="stub",
            candidates=list(slot.candidates),
        )

    def resolve_slots(self, slot_definitions: Sequence[ProviderSlotDefinition]):
        return [self.resolve_slot(s) for s in slot_definitions]


def _mini_config(slots: Sequence[PDBPanelSlot], synthesizer: str) -> PDBPanelConfig:
    slot_map = {s.slot_id: s for s in slots}
    panel = PDBPanelDefinition(
        panel_id="p",
        findings_slots=tuple(s.slot_id for s in slots),
        critique_slots=tuple(s.slot_id for s in slots),
        synthesizer_slot=synthesizer,
    )
    return PDBPanelConfig(
        version=1,
        default_panel="p",
        default_prompt_set="ps",
        budget=PDBBudgetConfig(
            per_brief_usd=20.0,
            per_day_usd=200.0,
            reserve_for_manual_escalation_usd=10.0,
        ),
        slots=slot_map,
        panels={"p": panel},
        prompt_sets={
            "ps": PDBPromptSet(
                prompt_set_id="ps",
                findings_prompt="f",
                critique_prompt="c",
                synthesis_prompt="s",
            ),
        },
    )


def _heuristic_packet(binding: PRReviewBinding) -> PRReviewProtocolPacket:
    return PRReviewProtocolPacket(
        protocol_version=PROTOCOL_VERSION,
        status=PROTOCOL_STATUS,
        binding=binding,
        review_roles=list(PRReviewProtocol.default().review_roles),
        provider_slots=[],
        availability_summary=ProviderSlotAvailabilitySummary(total_slots=0, resolved_slots=0),
        recommendation_class="needs_human_attention",
        recommendation_reason="pre-execution",
        confidence=0.5,
        confidence_basis=PROTOCOL_STATUS,
        dissent_summary="",
        dissenting_views=[],
        validation_summary={},
        top_findings=[],
        cost_estimate={},
    )


def _execution_input() -> PDBExecutionInput:
    b = _binding()
    return PDBExecutionInput(
        binding=b,
        packet=_heuristic_packet(b),
        packet_sha="",
        pr_title="Tighten rate limiter",
        pr_body="",
        labels=("backend",),
        changed_files=("aragora/server/rate_limit.py",),
        diff_excerpt="diff --git a b\n+ pass\n",
        validation_summary={"checks_summary": "green"},
        panel_id="p",
        policy=ReviewPolicy(budget=ReviewBudget(per_pr_usd_cap=0.0)),
    )


class TestEndToEndWithRealInvoker:
    def test_run_protocol_b_with_mocked_agents_produces_brief(self) -> None:
        # Stateful mocks that return the right payload per call phase.
        claude_mock = MagicMock()
        claude_mock.model = "claude-sonnet-4-6"
        claude_mock.last_tokens_in = 1000
        claude_mock.last_tokens_out = 500

        call_counter = {"n": 0}

        async def _claude_generate(prompt: str, context: Any = None, **kwargs: Any) -> str:
            # Phase detection via prompt markers the templates use.
            call_counter["n"] += 1
            if "findings round" in prompt:
                return _findings_payload_json("approve", slot_id="claude_core")
            if "critique round" in prompt:
                return _critique_payload_json("approve")
            if "synthesis" in prompt:
                return _synthesis_payload_json()
            return "{}"

        claude_mock.generate.side_effect = _claude_generate

        gpt_mock = MagicMock()
        gpt_mock.model = "gpt-5.5"
        gpt_mock.last_tokens_in = 900
        gpt_mock.last_tokens_out = 400

        async def _gpt_generate(prompt: str, context: Any = None, **kwargs: Any) -> str:
            if "findings round" in prompt:
                return _findings_payload_json("approve", slot_id="gpt_core")
            if "critique round" in prompt:
                return _critique_payload_json("approve")
            return "{}"

        gpt_mock.generate.side_effect = _gpt_generate

        invoker = RealProviderInvoker(claude=claude_mock, gpt=gpt_mock)

        slots = [
            _slot(
                "claude_core",
                family=FAMILY_CLAUDE,
                review_role="logic_reviewer",
                lens="core",
                required=True,
            ),
            _slot(
                "gpt_core",
                family=FAMILY_GPT,
                review_role="security_reviewer",
                lens="core",
                required=True,
            ),
            # Heterodox slot — resolver says "available" (stub) but the
            # RealProviderInvoker will raise ProviderUnavailableError
            # which the executor records in degrade_reasons.
            _slot(
                "grok_heterodox",
                family="grok",
                review_role="skeptic",
                lens="heterodox",
                required=False,
            ),
        ]
        config = _mini_config(slots, synthesizer="claude_core")
        resolver = _StubResolver({"claude_core", "gpt_core", "grok_heterodox"}, slots)
        ledger = PDBBudgetLedger(daily_cap_usd=config.budget.per_day_usd)

        result = run_protocol_b(
            _execution_input(),
            invoker=invoker,
            config=config,
            ledger=ledger,
            resolver=resolver,
        )

        # Heterodox slot was attempted and degraded; core slots produced a brief.
        assert result.status in (PDBExecutionStatus.SUCCESS, PDBExecutionStatus.DEGRADED)
        assert isinstance(result.brief, ReviewBrief)
        assert "claude_core" in result.active_roster
        assert "gpt_core" in result.active_roster
        assert "grok_heterodox" not in result.active_roster
        # Degrade reason mentions the grok slot
        assert any("grok" in reason for reason in result.degrade_reasons)

    def test_heterogeneity_floor_fails_closed_with_only_one_family(self) -> None:
        # Only claude wired + only claude_core in the panel would fail
        # validation (≥2 core required); we use resolver-level collapse
        # to exercise the runtime heterogeneity check.
        claude_mock = _make_mock_agent(
            model="claude-sonnet-4-6",
            response_text=_findings_payload_json(),
        )
        invoker = RealProviderInvoker(claude=claude_mock, gpt=None)

        slots = [
            _slot("claude_core", family=FAMILY_CLAUDE, lens="core", required=True),
            _slot(
                "gpt_core",
                family=FAMILY_GPT,
                review_role="security_reviewer",
                lens="core",
                required=True,
            ),
            _slot(
                "grok_heterodox",
                family="grok",
                review_role="skeptic",
                lens="heterodox",
            ),
        ]
        config = _mini_config(slots, synthesizer="claude_core")
        # Resolver: only claude resolves. gpt_core is required + missing →
        # executor fails closed before any agent is called.
        resolver = _StubResolver({"claude_core"}, slots)

        result = run_protocol_b(
            _execution_input(),
            invoker=invoker,
            config=config,
            resolver=resolver,
        )
        assert result.status is PDBExecutionStatus.FAILED_CLOSED
        assert result.brief is None
