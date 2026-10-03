"""Zero-evidence receipts must never assert PASS/APPROVED (issue #9303).

Measured live 2026-07-15 (dim-8 instrument): a debate where every agent
returned provider/error placeholders minted verdict=PASS at 80% confidence,
and a gauntlet run with 0 attacks / 0 probes / 0 findings minted APPROVED at
95%. These tests pin the fail-closed behavior.
"""

from __future__ import annotations

from aragora.agents.failure_semantics import (
    all_responses_are_failures,
    looks_like_agent_failure_response,
)
from aragora.core_types import DebateResult, Message
from aragora.gauntlet.orchestrator import _no_adversarial_work
from aragora.gauntlet.receipt_models import DecisionReceipt


def _placeholder_result() -> DebateResult:
    return DebateResult(
        debate_id="d-zero",
        task="Should we adopt a monorepo?",
        final_answer="anthropic-api got confused and needs to recalibrate.",
        confidence=0.8,
        consensus_reached=True,
        rounds_used=1,
        participants=["anthropic-api"],
        messages=[
            Message(
                role="proposal",
                agent="anthropic-api",
                content="anthropic-api got confused and needs to recalibrate.",
            )
        ],
        winner="anthropic-api",
    )


class TestFailureSemantics:
    def test_placeholders_recognized(self) -> None:
        assert looks_like_agent_failure_response(
            "anthropic-api got confused and needs to recalibrate."
        )
        assert looks_like_agent_failure_response("")
        assert looks_like_agent_failure_response(None)
        assert not looks_like_agent_failure_response("Use a monorepo because ...")

    def test_all_responses(self) -> None:
        assert all_responses_are_failures([])  # zero responses = zero evidence
        assert all_responses_are_failures(["agent timed out", ""])
        assert not all_responses_are_failures(["agent timed out", "real answer"])


class TestDebateZeroEvidenceReceipt:
    def test_placeholder_only_debate_mints_no_evidence(self) -> None:
        receipt = DecisionReceipt.from_debate_result(_placeholder_result())
        assert receipt.verdict == "NO_EVIDENCE"
        assert receipt.confidence == 0.0
        assert receipt.robustness_score == 0.0
        assert "NO EVIDENCE" in receipt.verdict_reasoning

    def test_real_answer_still_passes(self) -> None:
        result = _placeholder_result()
        result.final_answer = "Adopt a monorepo: single CI surface, atomic refactors."
        result.messages = [Message(role="proposal", agent="claude", content=result.final_answer)]
        receipt = DecisionReceipt.from_debate_result(result)
        assert receipt.verdict == "PASS"
        assert receipt.confidence == 0.8


class TestGauntletZeroWork:
    def test_no_work_is_zero_evidence(self) -> None:
        assert _no_adversarial_work(None, None, None, [], [], []) is True

    class _Redteam:
        total_attacks = 3

    def test_any_real_work_counts(self) -> None:
        assert _no_adversarial_work(self._Redteam(), None, None, [], [], []) is False
        assert _no_adversarial_work(None, None, object(), [], [], []) is False
        assert _no_adversarial_work(None, None, None, ["claim"], [], []) is False
        assert _no_adversarial_work(None, None, None, [], [], ["finding"]) is False


class TestRoundTwoHardening:
    def test_no_evidence_verdict_is_verify_valid(self) -> None:
        from aragora.cli.commands.verify import _is_valid_verdict

        assert _is_valid_verdict("NO_EVIDENCE")
        assert _is_valid_verdict("no_evidence")

    def test_long_answer_quoting_error_is_not_a_placeholder(self) -> None:
        text = (
            "The root cause is that the retry loop swallows 'connection failed' "
            "errors from the pool. " + "Detailed analysis follows. " * 30
        )
        assert len(text) >= 500
        assert not looks_like_agent_failure_response(text)

    def test_short_real_outage_answer_not_a_placeholder(self) -> None:
        text = (
            "Root cause: the LB health check failed after the pool's connection "
            "failed during cert rotation; fix is to pin the CA bundle and retry."
        )
        assert 120 < len(text) < 500
        assert not looks_like_agent_failure_response(text)

    def test_strong_placeholder_still_classified(self) -> None:
        assert looks_like_agent_failure_response(
            "claude tripped over an edge case and is recovering"
        )

    def test_schema_accepts_no_evidence(self) -> None:
        from aragora.gauntlet.api.schema import validate_receipt

        _ok, errors = validate_receipt({"verdict": "NO_EVIDENCE", "confidence": 0.0})
        assert not any("verdict must be" in e for e in errors)

    def test_long_bracketed_error_body_is_still_a_placeholder(self) -> None:
        text = "[Error generating proposal: " + "traceback line\n" * 100 + "]"
        assert len(text) > 500
        assert looks_like_agent_failure_response(text)

    def test_zero_evidence_receipt_has_no_supportive_consensus(self) -> None:
        receipt = DecisionReceipt.from_debate_result(_placeholder_result())
        assert receipt.consensus_proof.reached is False
        assert receipt.consensus_proof.confidence == 0.0
        assert receipt.consensus_proof.supporting_agents == []
        assert "Winner" not in receipt.verdict_reasoning
        assert "Consensus reached" not in receipt.verdict_reasoning

    def test_zero_work_result_reports_zero_robustness(self) -> None:
        # Pin the orchestrator constants: the zero-evidence branch must zero
        # robustness/coverage (defaults are 1.0/derived when redteam is None).
        import inspect

        from aragora.gauntlet import orchestrator as go

        src = inspect.getsource(go)
        gate = src[src.index("if zero_evidence:") :]
        assert "robustness_score = 0.0" in gate[:600]
        assert "coverage_score = 0.0" in gate[:600]

    def test_substantive_proposals_prevent_zero_evidence(self) -> None:
        result = _placeholder_result()
        result.proposals = {
            "claude": "Monorepo: one CI surface, atomic refactors, single review gate."
        }
        receipt = DecisionReceipt.from_debate_result(result)
        assert receipt.verdict != "NO_EVIDENCE"

    def test_substantive_agent_responses_prevent_zero_evidence(self) -> None:
        from types import SimpleNamespace

        result = _placeholder_result()
        result.agent_responses = [
            SimpleNamespace(response="Real analysis: adopt the monorepo for atomic refactors.")
        ]
        receipt = DecisionReceipt.from_debate_result(result)
        assert receipt.verdict != "NO_EVIDENCE"

    def test_dict_backed_agent_responses_prevent_zero_evidence(self) -> None:
        result = _placeholder_result()
        result.agent_responses = [{"agent": "claude", "response": "Real monorepo analysis."}]
        receipt = DecisionReceipt.from_debate_result(result)
        assert receipt.verdict != "NO_EVIDENCE"

    def test_all_chaos_theater_families_classified(self) -> None:
        # claude #9306 terminal [P2]: TIMEOUT and CONNECTION families were
        # unrecognized. Fragments now derive from chaos_theater's own
        # templates — every family, current and future.
        samples = [
            "claude is wrestling with the complexity of your question.",
            "gpt's signal has faded into the digital ether.",
            "codex is taking longer than expected to respond...",
            "[claude stares into the abyss of computation for 90 seconds...]",
        ]
        for text in samples:
            assert looks_like_agent_failure_response(text), text

    def test_real_answer_mentioning_wrestling_is_not_classified(self) -> None:
        assert not looks_like_agent_failure_response(
            "Our analysis: the wrestling industry monorepo should be split."
        )
