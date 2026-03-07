"""
Tests for EU AI Act compliance module.

Covers:
- RiskClassifier: all 4 risk levels + all 8 Annex III categories
- ConformityReportGenerator: article mapping, report generation
- ConformityReport: serialization, markdown export
- CLI commands: audit and classify
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from aragora.compliance.eu_ai_act import (
    ANNEX_III_CATEGORIES,
    Article10Artifact,
    Article11Artifact,
    Article12Artifact,
    Article13Artifact,
    Article14Artifact,
    Article43Artifact,
    Article49Artifact,
    ArticleMapping,
    ComplianceArtifactBundle,
    ComplianceArtifactGenerator,
    ConformityReport,
    ConformityReportGenerator,
    RiskClassification,
    RiskClassifier,
    RiskLevel,
    _detect_human_oversight,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def classifier():
    return RiskClassifier()


@pytest.fixture
def generator():
    return ConformityReportGenerator()


@pytest.fixture
def sample_receipt() -> dict:
    """A well-formed receipt dict with all fields."""
    return {
        "receipt_id": "test-receipt-001",
        "gauntlet_id": "gauntlet-001",
        "timestamp": "2026-02-12T00:00:00Z",
        "input_summary": "Evaluate hiring algorithm for recruitment decisions",
        "input_hash": "abc123",
        "risk_summary": {
            "critical": 0,
            "high": 1,
            "medium": 2,
            "low": 0,
            "total": 3,
        },
        "attacks_attempted": 5,
        "attacks_successful": 1,
        "probes_run": 10,
        "vulnerabilities_found": 3,
        "verdict": "CONDITIONAL",
        "confidence": 0.75,
        "robustness_score": 0.8,
        "verdict_reasoning": "Recruitment system shows bias risk in CV screening",
        "dissenting_views": ["Agent-B: potential gender bias not fully mitigated"],
        "consensus_proof": {
            "reached": True,
            "confidence": 0.75,
            "supporting_agents": ["Agent-A", "Agent-C"],
            "dissenting_agents": ["Agent-B"],
            "method": "majority",
            "evidence_hash": "deadbeef",
        },
        "provenance_chain": [
            {
                "timestamp": "2026-02-12T00:00:01Z",
                "event_type": "attack",
                "agent": "Agent-A",
                "description": "[HIGH] Bias test",
                "evidence_hash": "1234",
            },
            {
                "timestamp": "2026-02-12T00:00:02Z",
                "event_type": "verdict",
                "agent": None,
                "description": "Verdict: CONDITIONAL",
                "evidence_hash": "5678",
            },
        ],
        "schema_version": "1.0",
        "artifact_hash": "abcdef1234567890",
        "config_used": {"require_approval": True},
    }


@pytest.fixture
def minimal_receipt() -> dict:
    """A receipt with minimal fields."""
    return {
        "receipt_id": "minimal-001",
        "gauntlet_id": "g-001",
        "timestamp": "2026-02-12T00:00:00Z",
        "input_summary": "Simple chatbot for customer FAQ",
        "input_hash": "xyz",
        "risk_summary": {},
        "verdict": "PASS",
        "confidence": 0.0,
        "robustness_score": 0.0,
        "verdict_reasoning": "",
        "provenance_chain": [],
        "config_used": {},
    }


# ---------------------------------------------------------------------------
# RiskClassifier Tests
# ---------------------------------------------------------------------------


class TestRiskClassifier:
    """Tests for EU AI Act risk classification."""

    def test_unacceptable_social_scoring(self, classifier):
        result = classifier.classify("AI system for social scoring of citizens")
        assert result.risk_level == RiskLevel.UNACCEPTABLE
        assert "social scoring" in result.matched_keywords
        assert "Article 5" in result.applicable_articles[0]

    def test_unacceptable_subliminal_manipulation(self, classifier):
        result = classifier.classify("System using subliminal manipulation techniques")
        assert result.risk_level == RiskLevel.UNACCEPTABLE

    def test_high_risk_biometrics(self, classifier):
        result = classifier.classify("Real-time facial recognition for public surveillance")
        assert result.risk_level == RiskLevel.HIGH
        assert result.annex_iii_category == "Biometrics"
        assert result.annex_iii_number == 1

    def test_high_risk_critical_infrastructure(self, classifier):
        result = classifier.classify("AI managing water supply distribution systems")
        assert result.risk_level == RiskLevel.HIGH
        assert result.annex_iii_category == "Critical infrastructure"
        assert result.annex_iii_number == 2

    def test_high_risk_education(self, classifier):
        result = classifier.classify("Automated student assessment and grading system")
        assert result.risk_level == RiskLevel.HIGH
        assert result.annex_iii_category == "Education and vocational training"
        assert result.annex_iii_number == 3

    def test_high_risk_employment(self, classifier):
        result = classifier.classify("AI for recruitment and CV screening of job applicants")
        assert result.risk_level == RiskLevel.HIGH
        assert result.annex_iii_category == "Employment and worker management"
        assert result.annex_iii_number == 4

    def test_high_risk_essential_services(self, classifier):
        result = classifier.classify("Credit scoring system for loan decision making")
        assert result.risk_level == RiskLevel.HIGH
        assert result.annex_iii_category == "Access to essential services"
        assert result.annex_iii_number == 5

    def test_high_risk_law_enforcement(self, classifier):
        result = classifier.classify("Predictive policing crime prediction system")
        assert result.risk_level == RiskLevel.HIGH
        assert result.annex_iii_category == "Law enforcement"
        assert result.annex_iii_number == 6

    def test_high_risk_migration(self, classifier):
        result = classifier.classify("AI for visa application processing at border control")
        assert result.risk_level == RiskLevel.HIGH
        assert result.annex_iii_category == "Migration, asylum and border control"
        assert result.annex_iii_number == 7

    def test_high_risk_justice(self, classifier):
        result = classifier.classify("AI-assisted judicial sentencing recommendation system")
        assert result.risk_level == RiskLevel.HIGH
        assert result.annex_iii_category == "Administration of justice and democratic processes"
        assert result.annex_iii_number == 8

    def test_limited_risk_chatbot(self, classifier):
        result = classifier.classify("Customer-facing chatbot for product FAQ")
        assert result.risk_level == RiskLevel.LIMITED
        assert "chatbot" in result.matched_keywords
        assert any("Article 50" in a for a in result.applicable_articles)

    def test_limited_risk_deepfake(self, classifier):
        result = classifier.classify("System generating deepfake videos for entertainment")
        assert result.risk_level == RiskLevel.LIMITED

    def test_minimal_risk(self, classifier):
        result = classifier.classify("AI spam filter for internal email")
        assert result.risk_level == RiskLevel.MINIMAL

    def test_minimal_risk_no_keywords(self, classifier):
        result = classifier.classify("Simple data aggregation tool")
        assert result.risk_level == RiskLevel.MINIMAL
        assert not result.matched_keywords

    def test_high_risk_has_obligations(self, classifier):
        result = classifier.classify("Employee performance evaluation system")
        assert result.risk_level == RiskLevel.HIGH
        assert len(result.obligations) > 0
        assert any("risk management" in o.lower() for o in result.obligations)

    def test_high_risk_has_applicable_articles(self, classifier):
        result = classifier.classify("AI for credit scoring decisions")
        assert "Article 9 (Risk management)" in result.applicable_articles
        assert "Article 13 (Transparency)" in result.applicable_articles
        assert "Article 14 (Human oversight)" in result.applicable_articles

    def test_classification_to_dict(self, classifier):
        result = classifier.classify("Biometric identification system")
        d = result.to_dict()
        assert d["risk_level"] == "high"
        assert d["annex_iii_category"] == "Biometrics"
        assert isinstance(d["obligations"], list)

    def test_classify_receipt(self, classifier, sample_receipt):
        result = classifier.classify_receipt(sample_receipt)
        # sample_receipt mentions "recruitment" and "CV screening"
        assert result.risk_level == RiskLevel.HIGH
        assert result.annex_iii_number == 4


# ---------------------------------------------------------------------------
# ConformityReportGenerator Tests
# ---------------------------------------------------------------------------


class TestConformityReportGenerator:
    """Tests for EU AI Act conformity report generation."""

    def test_generate_report_from_receipt(self, generator, sample_receipt):
        report = generator.generate(sample_receipt)
        assert report.receipt_id == "test-receipt-001"
        assert report.report_id.startswith("EUAIA-")
        assert report.risk_classification.risk_level == RiskLevel.HIGH
        assert len(report.article_mappings) > 0

    def test_article_9_risk_management_mapping(self, generator, sample_receipt):
        report = generator.generate(sample_receipt)
        art9 = [m for m in report.article_mappings if m.article == "Article 9"]
        assert len(art9) == 1
        assert "risk" in art9[0].evidence.lower()

    def test_article_12_record_keeping(self, generator, sample_receipt):
        report = generator.generate(sample_receipt)
        art12 = [m for m in report.article_mappings if m.article == "Article 12"]
        assert len(art12) == 1
        # sample_receipt has 2 provenance events -> satisfied
        assert art12[0].status == "satisfied"

    def test_article_13_transparency(self, generator, sample_receipt):
        report = generator.generate(sample_receipt)
        art13 = [m for m in report.article_mappings if m.article == "Article 13"]
        assert len(art13) == 1
        assert "Agent-A" in art13[0].evidence or "3 agents" in art13[0].evidence

    def test_article_14_human_oversight_present(self, generator, sample_receipt):
        report = generator.generate(sample_receipt)
        art14 = [m for m in report.article_mappings if m.article == "Article 14"]
        assert len(art14) == 1
        # sample_receipt has require_approval in config
        assert art14[0].status == "satisfied"

    def test_article_14_human_oversight_absent(self, generator, minimal_receipt):
        report = generator.generate(minimal_receipt)
        art14 = [m for m in report.article_mappings if m.article == "Article 14"]
        assert len(art14) == 1
        assert art14[0].status == "partial"

    def test_article_15_accuracy_robustness(self, generator, sample_receipt):
        report = generator.generate(sample_receipt)
        art15 = [m for m in report.article_mappings if m.article == "Article 15"]
        assert len(art15) == 1
        # robustness_score 0.8 -> satisfied
        assert art15[0].status == "satisfied"

    def test_low_robustness_partial(self, generator, sample_receipt):
        sample_receipt["robustness_score"] = 0.3
        report = generator.generate(sample_receipt)
        art15 = [m for m in report.article_mappings if m.article == "Article 15"]
        assert art15[0].status == "partial"

    def test_very_low_robustness_not_satisfied(self, generator, sample_receipt):
        sample_receipt["robustness_score"] = 0.1
        report = generator.generate(sample_receipt)
        art15 = [m for m in report.article_mappings if m.article == "Article 15"]
        assert art15[0].status == "not_satisfied"

    def test_overall_status_conformant(self, generator, sample_receipt):
        # Make everything pass
        sample_receipt["risk_summary"]["critical"] = 0
        sample_receipt["risk_summary"]["high"] = 0
        sample_receipt["robustness_score"] = 0.9
        report = generator.generate(sample_receipt)
        assert report.overall_status == "conformant"

    def test_overall_status_non_conformant(self, generator):
        receipt = {
            "receipt_id": "bad-001",
            "input_summary": "Credit scoring AI",
            "risk_summary": {"critical": 5, "high": 3, "medium": 0, "low": 0, "total": 8},
            "confidence": 0.2,
            "robustness_score": 0.1,
            "verdict_reasoning": "High bias in credit scoring",
            "provenance_chain": [],
            "config_used": {},
        }
        report = generator.generate(receipt)
        assert report.overall_status == "non_conformant"

    def test_recommendations_for_failing_articles(self, generator):
        receipt = {
            "receipt_id": "rec-002",
            "input_summary": "Simple tool",
            "risk_summary": {},
            "confidence": 0.0,
            "robustness_score": 0.0,
            "verdict_reasoning": "",
            "provenance_chain": [],
            "config_used": {},
        }
        report = generator.generate(receipt)
        assert len(report.recommendations) > 0

    def test_report_integrity_hash(self, generator, sample_receipt):
        report = generator.generate(sample_receipt)
        assert report.integrity_hash
        assert len(report.integrity_hash) == 64  # SHA-256


# ---------------------------------------------------------------------------
# ConformityReport serialization tests
# ---------------------------------------------------------------------------


class TestConformityReport:
    """Tests for ConformityReport serialization."""

    def test_to_dict(self, generator, sample_receipt):
        report = generator.generate(sample_receipt)
        d = report.to_dict()
        assert d["report_id"].startswith("EUAIA-")
        assert d["receipt_id"] == "test-receipt-001"
        assert "risk_classification" in d
        assert "article_mappings" in d
        assert isinstance(d["article_mappings"], list)

    def test_to_json(self, generator, sample_receipt):
        report = generator.generate(sample_receipt)
        j = report.to_json()
        parsed = json.loads(j)
        assert parsed["receipt_id"] == "test-receipt-001"

    def test_to_markdown(self, generator, sample_receipt):
        report = generator.generate(sample_receipt)
        md = report.to_markdown()
        assert "# EU AI Act Conformity Report" in md
        assert "Article 9" in md
        assert "Article 13" in md
        assert "Article 14" in md
        assert "Risk Level:" in md

    def test_markdown_includes_recommendations(self, generator, minimal_receipt):
        report = generator.generate(minimal_receipt)
        md = report.to_markdown()
        if report.recommendations:
            assert "## Recommendations" in md


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelpers:
    """Tests for helper functions."""

    def test_detect_human_oversight_from_config(self):
        config = {"require_approval": True}
        assert _detect_human_oversight(config, {"provenance_chain": []})

    def test_detect_human_oversight_from_provenance(self):
        receipt = {
            "provenance_chain": [
                {"event_type": "plan_approved", "description": "Approved by admin"},
            ],
        }
        assert _detect_human_oversight({}, receipt)

    def test_no_human_oversight(self):
        assert not _detect_human_oversight({}, {"provenance_chain": []})

    def test_annex_iii_has_8_categories(self):
        assert len(ANNEX_III_CATEGORIES) == 8

    def test_annex_iii_categories_numbered_1_to_8(self):
        numbers = [c["number"] for c in ANNEX_III_CATEGORIES]
        assert numbers == list(range(1, 9))


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestComplianceCLI:
    """Tests for the compliance CLI commands."""

    def test_audit_command_json_output(self, sample_receipt, tmp_path):
        from aragora.cli.commands.compliance import _cmd_audit
        import argparse

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(sample_receipt))

        output_file = tmp_path / "report.json"
        args = argparse.Namespace(
            receipt_file=str(receipt_file),
            output_format="json",
            output=str(output_file),
        )
        _cmd_audit(args)

        report = json.loads(output_file.read_text())
        assert report["receipt_id"] == "test-receipt-001"
        assert "article_mappings" in report

    def test_audit_command_markdown_output(self, sample_receipt, tmp_path):
        from aragora.cli.commands.compliance import _cmd_audit
        import argparse

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(sample_receipt))

        output_file = tmp_path / "report.md"
        args = argparse.Namespace(
            receipt_file=str(receipt_file),
            output_format="markdown",
            output=str(output_file),
        )
        _cmd_audit(args)

        md = output_file.read_text()
        assert "# EU AI Act Conformity Report" in md

    def test_audit_command_missing_file(self, tmp_path):
        from aragora.cli.commands.compliance import _cmd_audit
        import argparse

        args = argparse.Namespace(
            receipt_file=str(tmp_path / "nonexistent.json"),
            output_format="json",
            output=None,
        )
        with pytest.raises(SystemExit):
            _cmd_audit(args)

    def test_classify_command(self, capsys):
        from aragora.cli.commands.compliance import _cmd_classify
        import argparse

        args = argparse.Namespace(description=["AI", "for", "credit", "scoring"])
        _cmd_classify(args)
        captured = capsys.readouterr()
        assert "HIGH" in captured.out
        assert "Annex III" in captured.out

    def test_classify_command_minimal(self, capsys):
        from aragora.cli.commands.compliance import _cmd_classify
        import argparse

        args = argparse.Namespace(description=["simple", "data", "tool"])
        _cmd_classify(args)
        captured = capsys.readouterr()
        assert "MINIMAL" in captured.out


# =============================================================================
# Test ComplianceArtifactGenerator
# =============================================================================


class TestComplianceArtifactGenerator:
    """Tests for the Art. 12/13/14 artifact generator."""

    @pytest.fixture
    def artifact_generator(self):
        return ComplianceArtifactGenerator(
            provider_name="Test Corp",
            provider_contact="test@example.com",
            eu_representative="Test EU GmbH",
            system_name="Test Platform",
            system_version="1.0.0",
        )

    @pytest.fixture
    def high_risk_receipt(self) -> dict:
        """Receipt with full fields for a high-risk use case."""
        return {
            "receipt_id": "art-test-001",
            "input_summary": "AI-powered recruitment and CV screening for hiring decisions",
            "verdict": "CONDITIONAL",
            "verdict_reasoning": "The hiring algorithm needs bias auditing",
            "confidence": 0.78,
            "robustness_score": 0.72,
            "risk_summary": {"total": 3, "critical": 0, "high": 1, "medium": 2, "low": 0},
            "consensus_proof": {
                "method": "weighted_majority",
                "supporting_agents": ["agent-a", "agent-c"],
                "dissenting_agents": ["agent-b"],
                "agreement_ratio": 0.67,
            },
            "dissenting_views": [
                {"agent": "agent-b", "view": "Bias risk too high"},
            ],
            "provenance_chain": [
                {
                    "event_type": "debate_started",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "actor": "system",
                },
                {
                    "event_type": "proposal_submitted",
                    "timestamp": "2026-01-01T00:01:00Z",
                    "actor": "agent-a",
                },
                {
                    "event_type": "human_approval",
                    "timestamp": "2026-01-01T00:10:00Z",
                    "actor": "admin@test.com",
                },
                {
                    "event_type": "receipt_generated",
                    "timestamp": "2026-01-01T00:10:05Z",
                    "actor": "system",
                },
            ],
            "config_used": {
                "protocol": "adversarial",
                "rounds": 2,
                "require_approval": True,
                "human_in_loop": True,
            },
            "artifact_hash": "abc123",
            "signature": "ed25519:test",
        }

    def test_generate_returns_bundle(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        assert isinstance(bundle, ComplianceArtifactBundle)
        assert bundle.bundle_id.startswith("EUAIA-")
        assert bundle.receipt_id == "art-test-001"

    def test_bundle_has_integrity_hash(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        assert len(bundle.integrity_hash) == 64  # SHA-256 hex

    def test_bundle_risk_classification(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        assert bundle.risk_classification.risk_level == RiskLevel.HIGH
        assert bundle.risk_classification.annex_iii_category == "Employment and worker management"

    def test_bundle_to_dict(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        d = bundle.to_dict()
        assert d["regulation"] == "EU AI Act (Regulation 2024/1689)"
        assert d["compliance_deadline"] == "2026-08-02"
        assert "article_12_record_keeping" in d
        assert "article_13_transparency" in d
        assert "article_14_human_oversight" in d

    def test_bundle_to_json(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        j = bundle.to_json()
        parsed = json.loads(j)
        assert parsed["bundle_id"] == bundle.bundle_id

    # -- Article 12 tests --

    def test_art12_event_log(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        art12 = bundle.article_12
        assert isinstance(art12, Article12Artifact)
        assert len(art12.event_log) == 4
        assert art12.event_log[0]["event_type"] == "debate_started"

    def test_art12_input_record(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        art12 = bundle.article_12
        assert art12.input_record["input_hash"]  # non-empty
        assert len(art12.input_record["input_hash"]) == 64  # SHA-256

    def test_art12_technical_documentation(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        tech = bundle.article_12.technical_documentation
        assert tech["annex_iv_sec1_general"]["system_name"] == "Test Platform"
        assert tech["annex_iv_sec1_general"]["version"] == "1.0.0"
        assert tech["annex_iv_sec1_general"]["provider"] == "Test Corp"

    def test_art12_retention_policy(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        policy = bundle.article_12.retention_policy
        assert policy["minimum_months"] == 6
        assert policy["provenance_events"] == 4

    def test_art12_to_dict(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        d = bundle.article_12.to_dict()
        assert d["article"] == "Article 12"
        assert d["title"] == "Record-Keeping"

    # -- Article 13 tests --

    def test_art13_provider_identity(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        art13 = bundle.article_13
        assert isinstance(art13, Article13Artifact)
        assert art13.provider_identity["name"] == "Test Corp"
        assert art13.provider_identity["eu_representative"] == "Test EU GmbH"

    def test_art13_known_risks(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        risks = bundle.article_13.known_risks
        assert len(risks) == 3
        risk_names = [r["risk"] for r in risks]
        assert "Automation bias" in risk_names
        assert "Hollow consensus" in risk_names
        assert "Model hallucination" in risk_names

    def test_art13_output_interpretation(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        interp = bundle.article_13.output_interpretation
        assert interp["confidence"] == 0.78
        assert "Moderate" in interp["confidence_interpretation"]
        assert interp["dissent_count"] == 1

    def test_art13_human_oversight_detected(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        assert bundle.article_13.human_oversight_reference["human_approval_detected"] is True

    def test_art13_to_dict(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        d = bundle.article_13.to_dict()
        assert d["article"] == "Article 13"
        assert "known_risks" in d

    # -- Article 14 tests --

    def test_art14_oversight_model_hitl(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        art14 = bundle.article_14
        assert isinstance(art14, Article14Artifact)
        assert "Human-in-the-Loop" in art14.oversight_model["primary"]
        assert art14.oversight_model["human_approval_detected"] is True

    def test_art14_oversight_model_hotl_when_no_human(self, artifact_generator):
        receipt = {
            "receipt_id": "no-human-001",
            "input_summary": "Weather prediction model",
            "verdict": "PASS",
            "confidence": 0.9,
            "robustness_score": 0.85,
            "config_used": {"protocol": "quick"},
            "provenance_chain": [],
            "consensus_proof": {"supporting_agents": ["a"], "dissenting_agents": []},
        }
        bundle = artifact_generator.generate(receipt)
        assert "Human-on-the-Loop" in bundle.article_14.oversight_model["primary"]

    def test_art14_automation_bias_safeguards(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        safeguards = bundle.article_14.automation_bias_safeguards
        assert safeguards["warnings_present"] is True
        assert len(safeguards["mechanisms"]) >= 3

    def test_art14_override_capabilities(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        overrides = bundle.article_14.override_capability
        assert overrides["override_available"] is True
        assert len(overrides["mechanisms"]) == 3
        actions = [m["action"] for m in overrides["mechanisms"]]
        assert "Reject verdict" in actions
        assert "Override with reason" in actions

    def test_art14_intervention_stop(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        intervention = bundle.article_14.intervention_capability
        assert intervention["stop_available"] is True
        assert len(intervention["mechanisms"]) == 2
        for mech in intervention["mechanisms"]:
            assert mech["safe_state"] is True

    def test_art14_to_dict(self, artifact_generator, high_risk_receipt):
        bundle = artifact_generator.generate(high_risk_receipt)
        d = bundle.article_14.to_dict()
        assert d["article"] == "Article 14"
        assert "oversight_model" in d
        assert "override_capability" in d

    # -- Edge cases --

    def test_minimal_receipt_produces_bundle(self, artifact_generator):
        """Even a near-empty receipt should produce a valid bundle."""
        receipt = {"receipt_id": "min-001", "input_summary": "test"}
        bundle = artifact_generator.generate(receipt)
        assert bundle.bundle_id.startswith("EUAIA-")
        assert bundle.article_12.event_log == []
        assert bundle.article_13.output_interpretation["confidence"] == 0.0

    def test_confidence_interpretation_high(self, artifact_generator):
        receipt = {
            "receipt_id": "high-conf",
            "input_summary": "test",
            "confidence": 0.95,
            "consensus_proof": {"supporting_agents": ["a"], "dissenting_agents": []},
        }
        bundle = artifact_generator.generate(receipt)
        assert "High" in bundle.article_13.output_interpretation["confidence_interpretation"]

    def test_confidence_interpretation_low(self, artifact_generator):
        receipt = {
            "receipt_id": "low-conf",
            "input_summary": "test",
            "confidence": 0.3,
            "consensus_proof": {"supporting_agents": ["a"], "dissenting_agents": ["b", "c"]},
        }
        bundle = artifact_generator.generate(receipt)
        assert "Low" in bundle.article_13.output_interpretation["confidence_interpretation"]

    def test_custom_provider_settings(self):
        gen = ComplianceArtifactGenerator(
            provider_name="Acme AI",
            provider_contact="ai@acme.com",
            eu_representative="Acme EU Ltd.",
            system_name="AcmeDecider",
            system_version="3.0.0",
        )
        receipt = {
            "receipt_id": "custom-001",
            "input_summary": "test recruitment screening",
            "config_used": {},
            "provenance_chain": [],
            "consensus_proof": {"supporting_agents": [], "dissenting_agents": []},
        }
        bundle = gen.generate(receipt)
        assert bundle.article_13.provider_identity["name"] == "Acme AI"
        tech = bundle.article_12.technical_documentation
        assert tech["annex_iv_sec1_general"]["system_name"] == "AcmeDecider"
        assert tech["annex_iv_sec1_general"]["version"] == "3.0.0"


# =============================================================================
# Test CLI eu-ai-act generate command
# =============================================================================


class TestEuAiActGenerateCLI:
    """Tests for the aragora compliance eu-ai-act generate command."""

    def test_generate_with_receipt_file(self, sample_receipt, tmp_path):
        from aragora.cli.commands.compliance import _cmd_eu_ai_act_generate
        import argparse

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(sample_receipt))
        output_dir = tmp_path / "bundle-out"

        args = argparse.Namespace(
            receipt_file=str(receipt_file),
            output=str(output_dir),
            provider_name="Test Corp",
            provider_contact="test@example.com",
            eu_representative="Test EU GmbH",
            system_name="Test Platform",
            system_version="1.0.0",
            output_format="all",
        )
        _cmd_eu_ai_act_generate(args)

        # Verify all expected files exist
        assert (output_dir / "compliance_bundle.json").exists()
        assert (output_dir / "article_12_record_keeping.json").exists()
        assert (output_dir / "article_13_transparency.json").exists()
        assert (output_dir / "article_14_human_oversight.json").exists()
        assert (output_dir / "conformity_report.md").exists()
        assert (output_dir / "conformity_report.json").exists()

    def test_generate_bundle_json_valid(self, sample_receipt, tmp_path):
        from aragora.cli.commands.compliance import _cmd_eu_ai_act_generate
        import argparse

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(sample_receipt))
        output_dir = tmp_path / "bundle-json"

        args = argparse.Namespace(
            receipt_file=str(receipt_file),
            output=str(output_dir),
            provider_name="",
            provider_contact="",
            eu_representative="",
            system_name="",
            system_version="",
            output_format="json",
        )
        _cmd_eu_ai_act_generate(args)

        bundle_path = output_dir / "compliance_bundle.json"
        assert bundle_path.exists()
        bundle = json.loads(bundle_path.read_text())
        assert bundle["regulation"] == "EU AI Act (Regulation 2024/1689)"
        assert bundle["compliance_deadline"] == "2026-08-02"
        assert "integrity_hash" in bundle
        assert len(bundle["integrity_hash"]) == 64

    def test_generate_json_only_no_article_files(self, sample_receipt, tmp_path):
        from aragora.cli.commands.compliance import _cmd_eu_ai_act_generate
        import argparse

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(sample_receipt))
        output_dir = tmp_path / "bundle-json-only"

        args = argparse.Namespace(
            receipt_file=str(receipt_file),
            output=str(output_dir),
            provider_name="",
            provider_contact="",
            eu_representative="",
            system_name="",
            system_version="",
            output_format="json",
        )
        _cmd_eu_ai_act_generate(args)

        # Only bundle JSON, no individual article files
        assert (output_dir / "compliance_bundle.json").exists()
        assert not (output_dir / "article_12_record_keeping.json").exists()
        assert not (output_dir / "conformity_report.md").exists()

    def test_generate_without_receipt_uses_synthetic(self, tmp_path):
        from aragora.cli.commands.compliance import _cmd_eu_ai_act_generate
        import argparse

        output_dir = tmp_path / "demo-bundle"

        args = argparse.Namespace(
            receipt_file=None,
            output=str(output_dir),
            provider_name="Demo Corp",
            provider_contact="demo@example.com",
            eu_representative="",
            system_name="Demo System",
            system_version="0.1.0",
            output_format="all",
        )
        _cmd_eu_ai_act_generate(args)

        bundle_path = output_dir / "compliance_bundle.json"
        assert bundle_path.exists()
        bundle = json.loads(bundle_path.read_text())
        assert bundle["receipt_id"] == "DEMO-RCP-001"
        assert bundle["risk_classification"]["risk_level"] == "high"

    def test_generate_missing_receipt_file(self, tmp_path):
        from aragora.cli.commands.compliance import _cmd_eu_ai_act_generate
        import argparse

        args = argparse.Namespace(
            receipt_file=str(tmp_path / "nonexistent.json"),
            output=str(tmp_path / "out"),
            provider_name="",
            provider_contact="",
            eu_representative="",
            system_name="",
            system_version="",
            output_format="all",
        )
        with pytest.raises(SystemExit):
            _cmd_eu_ai_act_generate(args)

    def test_generate_conformity_report_md_content(self, sample_receipt, tmp_path):
        from aragora.cli.commands.compliance import _cmd_eu_ai_act_generate
        import argparse

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(sample_receipt))
        output_dir = tmp_path / "md-check"

        args = argparse.Namespace(
            receipt_file=str(receipt_file),
            output=str(output_dir),
            provider_name="",
            provider_contact="",
            eu_representative="",
            system_name="",
            system_version="",
            output_format="all",
        )
        _cmd_eu_ai_act_generate(args)

        md_content = (output_dir / "conformity_report.md").read_text()
        assert "# EU AI Act Conformity Report" in md_content
        assert "Article 9" in md_content
        assert "Article 14" in md_content

    def test_generate_article_12_content(self, sample_receipt, tmp_path):
        from aragora.cli.commands.compliance import _cmd_eu_ai_act_generate
        import argparse

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(sample_receipt))
        output_dir = tmp_path / "art12-check"

        args = argparse.Namespace(
            receipt_file=str(receipt_file),
            output=str(output_dir),
            provider_name="",
            provider_contact="",
            eu_representative="",
            system_name="",
            system_version="",
            output_format="all",
        )
        _cmd_eu_ai_act_generate(args)

        art12 = json.loads((output_dir / "article_12_record_keeping.json").read_text())
        assert art12["article"] == "Article 12"
        assert art12["title"] == "Record-Keeping"
        assert "event_log" in art12
        assert "retention_policy" in art12
        assert art12["retention_policy"]["minimum_months"] == 6

    def test_synthetic_receipt_function(self):
        from aragora.cli.commands.compliance import _synthetic_receipt

        receipt = _synthetic_receipt()
        assert receipt["receipt_id"] == "DEMO-RCP-001"
        assert receipt["confidence"] == 0.78
        assert receipt["robustness_score"] == 0.72
        assert len(receipt["provenance_chain"]) == 10
        assert receipt["config_used"]["require_approval"] is True

    def test_cmd_compliance_dispatch_eu_ai_act(self, sample_receipt, tmp_path, capsys):
        """Test that cmd_compliance dispatches eu-ai-act generate correctly."""
        from aragora.cli.commands.compliance import cmd_compliance
        import argparse

        receipt_file = tmp_path / "receipt.json"
        receipt_file.write_text(json.dumps(sample_receipt))
        output_dir = tmp_path / "dispatch-test"

        args = argparse.Namespace(
            compliance_command="eu-ai-act",
            eu_ai_act_command="generate",
            receipt_file=str(receipt_file),
            output=str(output_dir),
            provider_name="",
            provider_contact="",
            eu_representative="",
            system_name="",
            system_version="",
            output_format="all",
        )
        cmd_compliance(args)

        assert (output_dir / "compliance_bundle.json").exists()
        captured = capsys.readouterr()
        assert "EU AI Act Compliance Artifact Bundle Generated" in captured.out


# Minimal receipt fixture shared by Article 9 and 15 tests
_MINIMAL_RECEIPT = {
    "receipt_id": "rcpt-test001",
    "topic": "Should we migrate to microservices?",
    "verdict": "Conditional: migrate incrementally with circuit breakers",
    "confidence": 0.82,
    "robustness_score": 0.75,
    "consensus_reached": True,
    "participants": ["claude-3", "gpt-4o", "mistral-large"],
    "risk_summary": {"critical": 0, "high": 1, "medium": 2, "low": 3},
    "dissenting_agents": ["mistral-large"],
    "artifact_hash": "abc123def456",
    "signature": "sig-xyz",
    "votes": [
        {"agent": "claude-3", "choice": "yes", "confidence": 0.9},
        {"agent": "gpt-4o", "choice": "yes", "confidence": 0.85},
        {"agent": "mistral-large", "choice": "no", "confidence": 0.6},
    ],
}


class TestArticle9Artifact:
    def test_generate_returns_article9_artifact(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator, Article9Artifact

        gen = ComplianceArtifactGenerator()
        art9 = gen._generate_art9(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art9, Article9Artifact)

    def test_article9_has_required_fields(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art9 = gen._generate_art9(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert art9.risk_identification_methodology
        assert isinstance(art9.identified_risks, list)
        assert isinstance(art9.risk_mitigation_measures, list)
        assert art9.overall_residual_risk_level in ("acceptable", "conditional", "unacceptable")
        assert art9.integrity_hash

    def test_bundle_includes_article9(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        bundle = gen.generate(_MINIMAL_RECEIPT)
        assert bundle.article_9 is not None
        assert bundle.article_9.artifact_id.startswith("ART9-")

    def test_article9_serializes_to_dict(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art9 = gen._generate_art9(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        d = art9.to_dict()
        assert "identified_risks" in d
        assert "overall_residual_risk_level" in d
        assert "integrity_hash" in d


class TestArticle15Artifact:
    def test_generate_returns_article15_artifact(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator, Article15Artifact

        gen = ComplianceArtifactGenerator()
        art15 = gen._generate_art15(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art15, Article15Artifact)

    def test_article15_has_required_fields(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art15 = gen._generate_art15(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art15.accuracy_metrics, dict)
        assert 0.0 <= art15.robustness_score <= 1.0
        assert isinstance(art15.cryptographic_controls, dict)
        assert art15.integrity_hash

    def test_bundle_includes_article15(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        bundle = gen.generate(_MINIMAL_RECEIPT)
        assert bundle.article_15 is not None
        assert bundle.article_15.artifact_id.startswith("ART15-")

    def test_article15_serializes_to_dict(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art15 = gen._generate_art15(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        d = art15.to_dict()
        assert "accuracy_metrics" in d
        assert "robustness_score" in d
        assert "cryptographic_controls" in d


class TestArticle10Artifact:
    def test_generate_returns_article10_artifact(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art10 = gen._generate_art10(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art10, Article10Artifact)

    def test_article10_has_required_fields(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art10 = gen._generate_art10(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art10.data_sources, list)
        assert isinstance(art10.data_quality_measures, list)
        assert isinstance(art10.bias_detection_methods, list)
        assert art10.training_data_provenance
        assert art10.data_governance_policy
        assert art10.integrity_hash

    def test_bundle_includes_article10(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        bundle = gen.generate(_MINIMAL_RECEIPT)
        assert bundle.article_10 is not None
        assert bundle.article_10.artifact_id.startswith("ART10-")

    def test_article10_serializes_to_dict(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art10 = gen._generate_art10(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        d = art10.to_dict()
        assert d["article"] == "Article 10"
        assert d["title"] == "Data and Data Governance"
        assert "data_sources" in d
        assert "bias_detection_methods" in d
        assert "integrity_hash" in d

    def test_article10_with_explicit_data_sources(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        receipt = {**_MINIMAL_RECEIPT, "data_sources": ["internal_db", "public_api"]}
        gen = ComplianceArtifactGenerator()
        art10 = gen._generate_art10(receipt, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert art10.data_sources == ["internal_db", "public_api"]

    def test_article10_compliance_notes_for_high_risk(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art10 = gen._generate_art10(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        # _MINIMAL_RECEIPT has high: 1
        assert any("High/critical" in n for n in art10.compliance_notes)


class TestArticle11Artifact:
    def test_generate_returns_article11_artifact(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art11 = gen._generate_art11(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art11, Article11Artifact)

    def test_article11_has_required_fields(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art11 = gen._generate_art11(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert art11.system_description
        assert isinstance(art11.design_specifications, list)
        assert len(art11.design_specifications) > 0
        assert art11.development_process
        assert isinstance(art11.monitoring_capabilities, list)
        assert isinstance(art11.performance_metrics, dict)
        assert art11.integrity_hash

    def test_bundle_includes_article11(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        bundle = gen.generate(_MINIMAL_RECEIPT)
        assert bundle.article_11 is not None
        assert bundle.article_11.artifact_id.startswith("ART11-")

    def test_article11_serializes_to_dict(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art11 = gen._generate_art11(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        d = art11.to_dict()
        assert d["article"] == "Article 11"
        assert d["title"] == "Technical Documentation"
        assert "system_description" in d
        assert "design_specifications" in d
        assert "performance_metrics" in d
        assert "integrity_hash" in d

    def test_article11_performance_metrics(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art11 = gen._generate_art11(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        metrics = art11.performance_metrics
        assert metrics["consensus_confidence"] == 0.82
        assert metrics["robustness_score"] == 0.75
        assert metrics["agent_count"] == 3

    def test_article11_custom_provider_in_description(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator(
            provider_name="Acme AI",
            system_name="AcmeDecider",
            system_version="3.0.0",
        )
        art11 = gen._generate_art11(
            {"receipt_id": "test", "input_summary": "test"},
            "test",
            "2026-03-05T00:00:00Z",
        )
        assert "AcmeDecider" in art11.system_description
        assert "Acme AI" in art11.system_description


class TestArticle43Artifact:
    def test_generate_returns_article43_artifact(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art43 = gen._generate_art43(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art43, Article43Artifact)

    def test_article43_has_required_fields(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art43 = gen._generate_art43(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert art43.assessment_type in ("internal", "third_party")
        assert art43.assessment_date
        assert art43.assessor
        assert isinstance(art43.standards_applied, list)
        assert isinstance(art43.findings, list)
        assert art43.conformity_status in ("conformant", "partial", "non_conformant")
        assert art43.integrity_hash

    def test_bundle_includes_article43(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        bundle = gen.generate(_MINIMAL_RECEIPT)
        assert bundle.article_43 is not None
        assert bundle.article_43.artifact_id.startswith("ART43-")

    def test_article43_serializes_to_dict(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art43 = gen._generate_art43(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        d = art43.to_dict()
        assert d["article"] == "Article 43"
        assert d["title"] == "Conformity Assessment"
        assert "assessment_type" in d
        assert "findings" in d
        assert "conformity_status" in d
        assert "integrity_hash" in d

    def test_article43_partial_conformity_for_high_risk(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art43 = gen._generate_art43(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        # _MINIMAL_RECEIPT has high: 1, confidence: 0.82, robustness: 0.75
        assert art43.conformity_status == "partial"

    def test_article43_non_conformant_for_critical(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        receipt = {
            **_MINIMAL_RECEIPT,
            "risk_summary": {"critical": 3, "high": 0, "medium": 0, "low": 0},
        }
        gen = ComplianceArtifactGenerator()
        art43 = gen._generate_art43(receipt, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert art43.conformity_status == "non_conformant"

    def test_article43_conformant_when_clean(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        receipt = {
            **_MINIMAL_RECEIPT,
            "risk_summary": {"critical": 0, "high": 0, "medium": 0, "low": 0},
            "confidence": 0.95,
            "robustness_score": 0.9,
        }
        gen = ComplianceArtifactGenerator()
        art43 = gen._generate_art43(receipt, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert art43.conformity_status == "conformant"

    def test_article43_internal_assessment_note(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art43 = gen._generate_art43(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert any("Internal conformity" in n for n in art43.compliance_notes)


class TestArticle49Artifact:
    def test_generate_returns_article49_artifact(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art49 = gen._generate_art49(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert isinstance(art49, Article49Artifact)

    def test_article49_has_required_fields(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art49 = gen._generate_art49(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert art49.registration_id
        assert art49.registered_date
        assert art49.eu_database_entry
        assert isinstance(art49.provider_info, dict)
        assert art49.system_purpose
        assert art49.risk_level
        assert art49.integrity_hash

    def test_bundle_includes_article49(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        bundle = gen.generate(_MINIMAL_RECEIPT)
        assert bundle.article_49 is not None
        assert bundle.article_49.artifact_id.startswith("ART49-")

    def test_article49_serializes_to_dict(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art49 = gen._generate_art49(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        d = art49.to_dict()
        assert d["article"] == "Article 49"
        assert d["title"] == "Registration"
        assert "registration_id" in d
        assert "provider_info" in d
        assert "risk_level" in d
        assert "integrity_hash" in d

    def test_article49_high_risk_from_receipt(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art49 = gen._generate_art49(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        # _MINIMAL_RECEIPT has high: 1
        assert art49.risk_level == "high"

    def test_article49_pending_registration_note(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator()
        art49 = gen._generate_art49(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert any("Registration in the EU database" in n for n in art49.compliance_notes)

    def test_article49_provider_info_defaults(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator(
            provider_name="Test Corp",
            provider_contact="test@example.com",
            eu_representative="Test EU GmbH",
        )
        art49 = gen._generate_art49(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert art49.provider_info["name"] == "Test Corp"
        assert art49.provider_info["contact"] == "test@example.com"
        assert art49.provider_info["eu_representative"] == "Test EU GmbH"

    def test_article49_no_eu_rep_compliance_note(self):
        from aragora.compliance.eu_ai_act import ComplianceArtifactGenerator

        gen = ComplianceArtifactGenerator(eu_representative="")
        art49 = gen._generate_art49(_MINIMAL_RECEIPT, "rcpt-test001", "2026-03-05T00:00:00Z")
        assert any("authorized representative" in n for n in art49.compliance_notes)
