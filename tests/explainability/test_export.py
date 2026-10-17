"""
Tests for Explainability Export Module (5D).

Tests cover:
- HTML export: structure, content, CSS, escaping
- PDF export: graceful fallback when weasyprint absent
- Markdown export: uses ExplanationBuilder.generate_summary
- Handler export endpoint: format param routing, 404, fallback
- Decision with/without optional components
"""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.explainability.decision import (
    ConfidenceAttribution,
    Counterfactual,
    Decision,
    EvidenceLink,
    VotePivot,
)
from aragora.explainability.export import (
    export_decision_html,
    export_decision_markdown,
    export_decision_pdf,
)
from tests.utils.weasyprint_isolation import hide_weasyprint, refuse_in_process_render


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def _no_in_process_weasyprint_render(monkeypatch):
    refuse_in_process_render(monkeypatch)


@pytest.fixture
def minimal_decision() -> Decision:
    """A minimal Decision with only required fields."""
    return Decision(
        decision_id="dec-test-001",
        debate_id="debate-abc",
        conclusion="We should proceed with option A.",
        consensus_reached=True,
        confidence=0.85,
        rounds_used=3,
        agents_participated=["claude", "gpt-4"],
    )


@pytest.fixture
def full_decision() -> Decision:
    """A Decision with all optional components populated."""
    return Decision(
        decision_id="dec-test-002",
        debate_id="debate-xyz",
        conclusion="Option B is better for long-term scalability.",
        consensus_reached=False,
        confidence=0.62,
        consensus_type="majority",
        task="Architecture review",
        domain="engineering",
        rounds_used=5,
        agents_participated=["claude", "gpt-4", "gemini"],
        evidence_chain=[
            EvidenceLink(
                id="ev-1",
                content="Microservices improve scalability",
                source="claude",
                relevance_score=0.9,
                grounding_type="argument",
            ),
            EvidenceLink(
                id="ev-2",
                content="Monolith is simpler to deploy",
                source="gpt-4",
                relevance_score=0.75,
                grounding_type="critique",
            ),
        ],
        vote_pivots=[
            VotePivot(
                agent="claude",
                choice="option-b",
                confidence=0.8,
                weight=1.2,
                reasoning_summary="Scalability wins long-term",
                influence_score=0.6,
                flip_detected=False,
            ),
            VotePivot(
                agent="gpt-4",
                choice="option-a",
                confidence=0.7,
                weight=1.0,
                reasoning_summary="Simplicity for current team size",
                influence_score=0.3,
                flip_detected=True,
            ),
        ],
        confidence_attribution=[
            ConfidenceAttribution(
                factor="consensus_strength",
                contribution=0.45,
                explanation="Moderate agreement among agents",
                raw_value=0.62,
            ),
            ConfidenceAttribution(
                factor="evidence_quality",
                contribution=0.35,
                explanation="Good quality evidence presented",
                raw_value=0.82,
            ),
        ],
        counterfactuals=[
            Counterfactual(
                condition="If claude had voted differently",
                outcome_change="Option A would have won",
                likelihood=0.3,
                sensitivity=0.6,
                affected_agents=["claude"],
            ),
        ],
        evidence_quality_score=0.82,
        agent_agreement_score=0.33,
        belief_stability_score=0.7,
    )


# ===========================================================================
# HTML Export Tests
# ===========================================================================


class TestExportDecisionHTML:
    """Test HTML export functionality."""

    def test_returns_valid_html(self, minimal_decision):
        html = export_decision_html(minimal_decision)
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "<head>" in html
        assert "<body>" in html

    def test_includes_decision_data(self, minimal_decision):
        html = export_decision_html(minimal_decision)
        assert "dec-test-001" in html
        assert "debate-abc" in html
        assert "85%" in html  # confidence
        assert "option A" in html  # conclusion

    def test_includes_css(self, minimal_decision):
        html = export_decision_html(minimal_decision)
        assert "<style>" in html
        assert "font-family" in html

    def test_consensus_badge_reached(self, minimal_decision):
        html = export_decision_html(minimal_decision)
        assert "Consensus Reached" in html
        assert "badge-success" in html

    def test_consensus_badge_not_reached(self, full_decision):
        html = export_decision_html(full_decision)
        assert "No Consensus" in html
        assert "badge-warning" in html

    def test_includes_evidence_chain(self, full_decision):
        html = export_decision_html(full_decision)
        assert "Evidence Chain" in html
        assert "Microservices improve scalability" in html
        assert "evidence-card" in html

    def test_includes_vote_pivots(self, full_decision):
        html = export_decision_html(full_decision)
        assert "Vote Analysis" in html
        assert "claude" in html
        assert "option-b" in html

    def test_includes_confidence_factors(self, full_decision):
        html = export_decision_html(full_decision)
        assert "Confidence Factors" in html
        assert "consensus_strength" in html

    def test_includes_counterfactuals(self, full_decision):
        html = export_decision_html(full_decision)
        assert "Counterfactual Analysis" in html
        assert "If claude had voted differently" in html

    def test_custom_title(self, minimal_decision):
        html = export_decision_html(minimal_decision, title="Custom Title")
        assert "<title>Custom Title</title>" in html

    def test_default_title_uses_debate_id(self, minimal_decision):
        html = export_decision_html(minimal_decision)
        assert "debate-abc" in html

    def test_escapes_html_in_conclusion(self):
        decision = Decision(
            decision_id="dec-xss",
            debate_id="debate-xss",
            conclusion='<script>alert("xss")</script>',
            consensus_reached=True,
            confidence=0.5,
        )
        html = export_decision_html(decision)
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ===========================================================================
# PDF Export Tests
# ===========================================================================


class TestExportDecisionPDF:
    """Test PDF export functionality."""

    def test_returns_none_without_weasyprint(self, minimal_decision):
        with patch.dict("sys.modules", {"weasyprint": None}):
            result = export_decision_pdf(minimal_decision)
            assert result is None

    def test_returns_bytes_with_mock_weasyprint(self, minimal_decision):
        mock_wp = MagicMock()
        mock_html_instance = MagicMock()
        mock_html_instance.write_pdf.return_value = b"%PDF-1.4 mock content"
        mock_wp.HTML.return_value = mock_html_instance

        with patch.dict("sys.modules", {"weasyprint": mock_wp}):
            # Need to reimport since weasyprint is imported inside the function
            from importlib import reload
            from aragora.explainability import export as export_mod

            reload(export_mod)
            result = export_mod.export_decision_pdf(minimal_decision)
            assert result == b"%PDF-1.4 mock content"

    def test_graceful_on_weasyprint_error(self, minimal_decision, monkeypatch):
        # WeasyPrint imports, but its native libraries fail at render time
        mock_wp = MagicMock()
        mock_wp.HTML.return_value.write_pdf.side_effect = OSError(
            "cannot load library 'libpango-1.0-0'"
        )
        monkeypatch.setitem(sys.modules, "weasyprint", mock_wp)

        assert export_decision_pdf(minimal_decision) is None


# ===========================================================================
# Markdown Export Tests
# ===========================================================================


class TestExportDecisionMarkdown:
    """Test markdown export functionality."""

    def test_returns_markdown_string(self, minimal_decision):
        md = export_decision_markdown(minimal_decision)
        assert isinstance(md, str)
        assert "## Decision Summary" in md

    def test_includes_confidence(self, minimal_decision):
        md = export_decision_markdown(minimal_decision)
        assert "85%" in md

    def test_includes_consensus_status(self, minimal_decision):
        md = export_decision_markdown(minimal_decision)
        assert "Reached" in md

    def test_full_decision_has_evidence(self, full_decision):
        md = export_decision_markdown(full_decision)
        assert "Evidence" in md


# ===========================================================================
# Handler Export Endpoint Tests
# ===========================================================================


class TestExportEndpoint:
    """Test the explainability handler export endpoint."""

    @pytest.fixture
    def handler(self):
        from aragora.server.handlers.explainability import ExplainabilityHandler

        return ExplainabilityHandler({})

    def test_can_handle_export_route(self, handler):
        assert handler.can_handle("/api/v1/debates/test-123/explainability/export") is True

    def test_cannot_handle_wrong_route(self, handler):
        assert handler.can_handle("/api/v1/debates/test-123/other") is False

    async def test_export_html_format(self, handler, full_decision):
        with patch.object(handler, "_get_or_build_decision", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = full_decision
            result = await handler._handle_export("debate-xyz", {"format": "html"})
            assert result.status_code == 200
            assert result.content_type == "text/html"
            body = result.body.decode("utf-8")
            assert "<!DOCTYPE html>" in body

    async def test_export_markdown_format(self, handler, full_decision):
        with patch.object(handler, "_get_or_build_decision", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = full_decision
            result = await handler._handle_export("debate-xyz", {"format": "markdown"})
            assert result.status_code == 200
            assert result.content_type == "text/markdown"

    async def test_export_default_format_is_markdown(self, handler, full_decision):
        with patch.object(handler, "_get_or_build_decision", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = full_decision
            result = await handler._handle_export("debate-xyz", {})
            assert result.status_code == 200
            assert result.content_type == "text/markdown"

    async def test_export_pdf_fallback_to_html(self, handler, full_decision, monkeypatch):
        hide_weasyprint(monkeypatch)
        with patch.object(handler, "_get_or_build_decision", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = full_decision
            result = await handler._handle_export("debate-xyz", {"format": "pdf"})
            assert result.status_code == 200
            assert result.content_type == "text/html"
            assert result.headers.get("X-PDF-Fallback") == "true"

    async def test_export_not_found(self, handler):
        with patch.object(handler, "_get_or_build_decision", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = None
            result = await handler._handle_export("nonexistent", {"format": "html"})
            assert result.status_code == 404
