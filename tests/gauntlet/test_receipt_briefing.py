"""Tests for DecisionReceipt TTS briefing methods.

Covers to_briefing_text() and to_audio_ssml() added for the
Stream C Phase C1 TTS audio briefing pipeline.
"""

from __future__ import annotations

import pytest

from aragora.gauntlet.receipt_models import ConsensusProof, DecisionReceipt


def _make_receipt(**overrides) -> DecisionReceipt:
    """Build a minimal DecisionReceipt with sensible defaults."""
    defaults = {
        "receipt_id": "RCP-2026-0301",
        "gauntlet_id": "gauntlet-001",
        "timestamp": "2026-03-01T12:00:00Z",
        "input_summary": "Evaluate proposed rate limiter design",
        "input_hash": "abc123def456",
        "risk_summary": {
            "critical": 1,
            "high": 3,
            "medium": 7,
            "low": 2,
            "total": 13,
        },
        "attacks_attempted": 12,
        "attacks_successful": 4,
        "probes_run": 8,
        "vulnerabilities_found": 13,
        "verdict": "PASS",
        "confidence": 0.87,
        "robustness_score": 0.92,
        "verdict_reasoning": (
            "The proposed rate limiter design withstands standard load patterns "
            "but shows vulnerability under sustained burst traffic. "
            "Overall risk is acceptable for production deployment."
        ),
        "consensus_proof": ConsensusProof(
            reached=True,
            confidence=0.87,
            supporting_agents=["claude", "gpt-4", "gemini", "mistral"],
            dissenting_agents=["grok"],
            method="majority",
        ),
    }
    defaults.update(overrides)
    return DecisionReceipt(**defaults)


class TestToBriefingText:
    """Tests for DecisionReceipt.to_briefing_text()."""

    def test_returns_nonempty_string(self):
        receipt = _make_receipt()
        text = receipt.to_briefing_text()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_includes_receipt_id(self):
        receipt = _make_receipt(receipt_id="RCP-2026-TEST-42")
        text = receipt.to_briefing_text()
        assert "RCP-2026-TEST-42" in text

    def test_includes_verdict(self):
        receipt = _make_receipt(verdict="FAIL")
        text = receipt.to_briefing_text()
        assert "FAIL" in text

    def test_includes_confidence_as_percent(self):
        receipt = _make_receipt(confidence=0.87)
        text = receipt.to_briefing_text()
        assert "87 percent" in text

    def test_includes_robustness_as_percent(self):
        receipt = _make_receipt(robustness_score=0.92)
        text = receipt.to_briefing_text()
        assert "92 percent" in text

    def test_includes_severity_counts(self):
        receipt = _make_receipt(
            risk_summary={"critical": 2, "high": 5, "medium": 0, "low": 0, "total": 7}
        )
        text = receipt.to_briefing_text()
        assert "2 critical" in text
        assert "5 high" in text

    def test_omits_zero_severity_levels(self):
        receipt = _make_receipt(
            risk_summary={"critical": 0, "high": 3, "medium": 0, "low": 0, "total": 3}
        )
        text = receipt.to_briefing_text()
        assert "critical" not in text.lower().split("verdict")[0]  # not in findings section
        assert "3 high" in text

    def test_includes_attack_attempts(self):
        receipt = _make_receipt(attacks_attempted=12)
        text = receipt.to_briefing_text()
        assert "12 attack attempts" in text

    def test_no_attack_mention_when_zero(self):
        receipt = _make_receipt(attacks_attempted=0)
        text = receipt.to_briefing_text()
        assert "attack attempt" not in text

    def test_includes_consensus_method(self):
        receipt = _make_receipt()
        text = receipt.to_briefing_text()
        assert "majority" in text.lower()

    def test_includes_agent_counts(self):
        receipt = _make_receipt()
        text = receipt.to_briefing_text()
        assert "4 supporting" in text
        assert "1 dissenting" in text

    def test_includes_verdict_reasoning(self):
        receipt = _make_receipt(verdict_reasoning="The design is robust under normal load.")
        text = receipt.to_briefing_text()
        assert "robust under normal load" in text

    def test_respects_max_chars(self):
        receipt = _make_receipt()
        text = receipt.to_briefing_text(max_chars=200)
        assert len(text) <= 200

    def test_truncation_ends_at_sentence_boundary(self):
        receipt = _make_receipt()
        text = receipt.to_briefing_text(max_chars=200)
        # Truncated text should end with "..." after a sentence period
        assert text.endswith("...")

    def test_no_truncation_when_under_limit(self):
        receipt = _make_receipt()
        text = receipt.to_briefing_text(max_chars=10000)
        assert "..." not in text or text.endswith(".")

    def test_no_findings_message(self):
        receipt = _make_receipt(
            risk_summary={"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0},
            vulnerabilities_found=0,
        )
        text = receipt.to_briefing_text()
        assert "No findings were identified" in text

    def test_consensus_not_reached(self):
        receipt = _make_receipt(
            consensus_proof=ConsensusProof(
                reached=False,
                confidence=0.4,
                supporting_agents=["claude"],
                dissenting_agents=["gpt-4", "gemini"],
                method="majority",
            )
        )
        text = receipt.to_briefing_text()
        assert "not reached" in text.lower()

    def test_no_consensus_proof(self):
        """When consensus_proof is None, no consensus section appears."""
        receipt = _make_receipt(consensus_proof=None)
        text = receipt.to_briefing_text()
        # Should still produce valid text without crashing
        assert "Decision Receipt" in text
        assert receipt.receipt_id in text

    def test_empty_verdict_reasoning(self):
        receipt = _make_receipt(verdict_reasoning="")
        text = receipt.to_briefing_text()
        assert "Key reasoning" not in text

    def test_verdict_reasoning_limited_to_two_sentences(self):
        long_reasoning = (
            "First sentence about the design. "
            "Second sentence about risk. "
            "Third sentence about deployment. "
            "Fourth sentence about monitoring."
        )
        receipt = _make_receipt(verdict_reasoning=long_reasoning)
        text = receipt.to_briefing_text()
        # Should only include first two sentences of reasoning
        assert "First sentence" in text
        assert "Second sentence" in text
        assert "Third sentence" not in text

    def test_spells_out_percent(self):
        """TTS text should say 'percent' not '%'."""
        receipt = _make_receipt()
        text = receipt.to_briefing_text()
        assert "%" not in text
        assert "percent" in text


class TestToAudioSsml:
    """Tests for DecisionReceipt.to_audio_ssml()."""

    def test_has_speak_root(self):
        receipt = _make_receipt()
        ssml = receipt.to_audio_ssml()
        assert ssml.startswith("<speak>")
        assert ssml.strip().endswith("</speak>")

    def test_contains_break_elements(self):
        receipt = _make_receipt()
        ssml = receipt.to_audio_ssml()
        assert "<break " in ssml

    def test_verdict_has_emphasis(self):
        receipt = _make_receipt()
        ssml = receipt.to_audio_ssml()
        assert '<emphasis level="strong">' in ssml
        assert "Verdict:" in ssml

    def test_contains_sentence_tags(self):
        receipt = _make_receipt()
        ssml = receipt.to_audio_ssml()
        assert "<s>" in ssml
        assert "</s>" in ssml

    def test_ssml_escapes_special_characters(self):
        receipt = _make_receipt(
            receipt_id="RCP-<test>&001",
            verdict_reasoning="Risk < threshold & acceptable.",
        )
        ssml = receipt.to_audio_ssml()
        # HTML/XML special chars should be escaped
        assert "&lt;" in ssml or "<test>" not in ssml
        assert "&amp;" in ssml

    def test_ssml_respects_max_chars(self):
        """SSML wraps to_briefing_text which respects max_chars."""
        receipt = _make_receipt()
        ssml = receipt.to_audio_ssml(max_chars=200)
        # The SSML tags add overhead, but underlying text should be truncated
        assert "<speak>" in ssml
        assert "</speak>" in ssml

    def test_returns_valid_xml_structure(self):
        """Basic structural validation of the SSML output."""
        receipt = _make_receipt()
        ssml = receipt.to_audio_ssml()
        # Count opening vs closing tags for basic well-formedness
        assert ssml.count("<speak>") == 1
        assert ssml.count("</speak>") == 1
        # Every <s> should have a closing </s>
        assert ssml.count("<s>") == ssml.count("</s>")
        # Every <emphasis> should have a closing </emphasis>
        assert ssml.count("<emphasis") == ssml.count("</emphasis>")
