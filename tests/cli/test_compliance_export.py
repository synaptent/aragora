"""Tests for the compliance export CLI command.

Tests cover:
- Demo mode (synthetic data)
- Receipt file loading
- Missing inputs (error handling)
- Markdown, HTML, and JSON format output
- Article mapping completeness
- Manifest generation
- Bundle integrity hash
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_receipt() -> dict:
    """A minimal receipt dict for testing."""
    import hashlib
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    return {
        "receipt_id": "TEST-RCP-001",
        "gauntlet_id": "test-gauntlet-001",
        "timestamp": now,
        "input_summary": (
            "Evaluate AI-powered recruitment and CV screening system for "
            "automated candidate filtering in hiring decisions."
        ),
        "input_hash": hashlib.sha256(b"test-input").hexdigest(),
        "risk_summary": {
            "total": 3,
            "critical": 0,
            "high": 1,
            "medium": 1,
            "low": 1,
        },
        "attacks_attempted": 5,
        "attacks_successful": 0,
        "probes_run": 8,
        "vulnerabilities_found": 1,
        "verdict": "APPROVED",
        "confidence": 0.85,
        "robustness_score": 0.80,
        "verdict_reasoning": "The hiring system passed all adversarial checks.",
        "dissenting_views": ["Agent-Critic: minor bias concern in age dimension"],
        "consensus_proof": {
            "reached": True,
            "confidence": 0.85,
            "supporting_agents": ["claude-analyst", "gpt4-auditor"],
            "dissenting_agents": ["gemini-critic"],
            "method": "weighted_majority",
            "agreement_ratio": 0.67,
            "evidence_hash": hashlib.sha256(b"test-evidence").hexdigest(),
        },
        "provenance_chain": [
            {"event_type": "debate_started", "timestamp": now, "actor": "system"},
            {"event_type": "proposal_submitted", "timestamp": now, "actor": "claude-analyst"},
            {"event_type": "critique_submitted", "timestamp": now, "actor": "gemini-critic"},
            {"event_type": "vote_cast", "timestamp": now, "actor": "claude-analyst"},
            {"event_type": "vote_cast", "timestamp": now, "actor": "gpt4-auditor"},
            {"event_type": "vote_cast", "timestamp": now, "actor": "gemini-critic"},
            {"event_type": "human_approval", "timestamp": now, "actor": "hr@test.com"},
            {"event_type": "receipt_generated", "timestamp": now, "actor": "system"},
        ],
        "schema_version": "1.0",
        "artifact_hash": hashlib.sha256(b"test-artifact").hexdigest(),
        "signature": "ed25519:test_signature",
        "config_used": {
            "protocol": "adversarial",
            "rounds": 3,
            "require_approval": True,
            "human_in_loop": True,
            "approver": "hr@test.com",
        },
    }


@pytest.fixture()
def receipt_file(sample_receipt: dict, tmp_path: Path) -> Path:
    """Write sample receipt to a temp file and return path."""
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(sample_receipt))
    return path


# ---------------------------------------------------------------------------
# Module import tests
# ---------------------------------------------------------------------------


class TestModuleImport:
    """Verify the module can be imported without side effects."""

    def test_import_compliance_export(self):
        from aragora.cli.commands import compliance_export  # noqa: F401

    def test_import_cmd_function(self):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        assert callable(cmd_compliance_export)

    def test_import_add_export_subparser(self):
        from aragora.cli.commands.compliance_export import add_export_subparser

        assert callable(add_export_subparser)


# ---------------------------------------------------------------------------
# Demo mode
# ---------------------------------------------------------------------------


class TestDemoMode:
    """Test --demo flag generates output without real data."""

    def test_demo_creates_output_dir(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "demo-pack"
        args = _make_args(demo=True, output_dir=str(output_dir))
        cmd_compliance_export(args)

        assert output_dir.exists()
        assert (output_dir / "bundle.json").exists()

    def test_demo_creates_all_markdown_files(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "demo-pack"
        args = _make_args(demo=True, output_dir=str(output_dir), output_format="markdown")
        cmd_compliance_export(args)

        expected_files = [
            "bundle.json",
            "receipt.md",
            "audit_trail.md",
            "transparency_report.md",
            "human_oversight.md",
            "accuracy_report.md",
            "README.md",
        ]
        for fname in expected_files:
            assert (output_dir / fname).exists(), f"Missing: {fname}"

    def test_demo_bundle_json_has_required_keys(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "demo-pack"
        args = _make_args(demo=True, output_dir=str(output_dir))
        cmd_compliance_export(args)

        bundle = json.loads((output_dir / "bundle.json").read_text())
        assert "meta" in bundle
        assert "risk_classification" in bundle
        assert "conformity_report" in bundle
        assert "receipt" in bundle
        assert "audit_trail" in bundle
        assert "transparency_report" in bundle
        assert "human_oversight" in bundle
        assert "accuracy_report" in bundle

    def test_demo_integrity_hash_present(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "demo-pack"
        args = _make_args(demo=True, output_dir=str(output_dir))
        cmd_compliance_export(args)

        bundle = json.loads((output_dir / "bundle.json").read_text())
        assert len(bundle["meta"]["integrity_hash"]) == 64  # SHA-256 hex

    def test_demo_risk_classification_is_high(self, tmp_path: Path):
        """Synthetic receipt is an HR/employment use case => HIGH risk."""
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "demo-pack"
        args = _make_args(demo=True, output_dir=str(output_dir))
        cmd_compliance_export(args)

        bundle = json.loads((output_dir / "bundle.json").read_text())
        assert bundle["risk_classification"]["risk_level"] == "high"


# ---------------------------------------------------------------------------
# Receipt file mode
# ---------------------------------------------------------------------------


class TestReceiptFileMode:
    """Test loading receipt from a JSON file."""

    def test_receipt_file_produces_bundle(self, receipt_file: Path, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "from-file"
        args = _make_args(receipt_file=str(receipt_file), output_dir=str(output_dir))
        cmd_compliance_export(args)

        assert (output_dir / "bundle.json").exists()
        bundle = json.loads((output_dir / "bundle.json").read_text())
        assert bundle["meta"]["receipt_id"] == "TEST-RCP-001"

    def test_receipt_file_not_found_exits(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        args = _make_args(
            receipt_file="/nonexistent/receipt.json", output_dir=str(tmp_path / "out")
        )
        with pytest.raises(SystemExit):
            cmd_compliance_export(args)

    def test_invalid_json_exits(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json {{{")
        args = _make_args(receipt_file=str(bad_file), output_dir=str(tmp_path / "out"))
        with pytest.raises(SystemExit):
            cmd_compliance_export(args)


# ---------------------------------------------------------------------------
# Missing input
# ---------------------------------------------------------------------------


class TestMissingInput:
    """Test error handling when no input is provided."""

    def test_no_input_exits_with_helpful_message(self, tmp_path: Path, capsys):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        args = _make_args(output_dir=str(tmp_path / "out"))
        with pytest.raises(SystemExit):
            cmd_compliance_export(args)

        captured = capsys.readouterr()
        assert "--demo" in captured.err


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------


class TestOutputFormats:
    """Test markdown, HTML, and JSON output."""

    def test_json_format(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "json-pack"
        args = _make_args(demo=True, output_dir=str(output_dir), output_format="json")
        cmd_compliance_export(args)

        for name in [
            "receipt",
            "audit_trail",
            "transparency_report",
            "human_oversight",
            "accuracy_report",
        ]:
            path = output_dir / f"{name}.json"
            assert path.exists(), f"Missing: {name}.json"
            data = json.loads(path.read_text())
            assert isinstance(data, dict)

    def test_html_format(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "html-pack"
        args = _make_args(demo=True, output_dir=str(output_dir), output_format="html")
        cmd_compliance_export(args)

        for name in [
            "receipt",
            "audit_trail",
            "transparency_report",
            "human_oversight",
            "accuracy_report",
        ]:
            path = output_dir / f"{name}.html"
            assert path.exists(), f"Missing: {name}.html"
            content = path.read_text()
            assert "<html" in content
            assert "</html>" in content

    def test_markdown_format_contains_article_references(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "md-pack"
        args = _make_args(demo=True, output_dir=str(output_dir), output_format="markdown")
        cmd_compliance_export(args)

        # Check that transparency report references Article 13
        transparency = (output_dir / "transparency_report.md").read_text()
        assert "Article 13" in transparency

        # Check that human oversight references Article 14
        oversight = (output_dir / "human_oversight.md").read_text()
        assert "Article 14" in oversight

        # Check accuracy references Article 15
        accuracy = (output_dir / "accuracy_report.md").read_text()
        assert "Article 15" in accuracy


# ---------------------------------------------------------------------------
# Article mapping completeness
# ---------------------------------------------------------------------------


class TestArticleMapping:
    """Verify all five articles are covered in the bundle."""

    def test_all_articles_present_in_conformity(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "articles"
        args = _make_args(demo=True, output_dir=str(output_dir))
        cmd_compliance_export(args)

        bundle = json.loads((output_dir / "bundle.json").read_text())
        articles_found = {m["article"] for m in bundle["conformity_report"]["article_mappings"]}
        assert "Article 9" in articles_found
        assert "Article 12" in articles_found
        assert "Article 13" in articles_found
        assert "Article 14" in articles_found
        assert "Article 15" in articles_found

    def test_article_artifacts_present(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "artifacts"
        args = _make_args(demo=True, output_dir=str(output_dir))
        cmd_compliance_export(args)

        bundle = json.loads((output_dir / "bundle.json").read_text())
        assert "article_12" in bundle["article_artifacts"]
        assert "article_13" in bundle["article_artifacts"]
        assert "article_14" in bundle["article_artifacts"]


# ---------------------------------------------------------------------------
# Manifest (README)
# ---------------------------------------------------------------------------


class TestManifest:
    """Test README.md manifest generation."""

    def test_readme_contains_file_listing(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "manifest"
        args = _make_args(demo=True, output_dir=str(output_dir))
        cmd_compliance_export(args)

        readme = (output_dir / "README.md").read_text()
        assert "bundle.json" in readme
        assert "receipt.md" in readme
        assert "audit_trail.md" in readme
        assert "Article 9" in readme
        assert "Article 12" in readme
        assert "Article 13" in readme
        assert "Article 14" in readme
        assert "Article 15" in readme

    def test_readme_contains_integrity_hash(self, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "manifest-hash"
        args = _make_args(demo=True, output_dir=str(output_dir))
        cmd_compliance_export(args)

        readme = (output_dir / "README.md").read_text()
        assert "Integrity Hash" in readme


# ---------------------------------------------------------------------------
# Transparency report content
# ---------------------------------------------------------------------------


class TestTransparencyReport:
    """Test that transparency report includes agent participation."""

    def test_agents_listed(self, receipt_file: Path, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "transparency"
        args = _make_args(
            receipt_file=str(receipt_file),
            output_dir=str(output_dir),
            output_format="json",
        )
        cmd_compliance_export(args)

        data = json.loads((output_dir / "transparency_report.json").read_text())
        assert data["agent_count"] >= 2
        assert len(data["agents_participating"]) >= 2

    def test_dissenting_views_included(self, receipt_file: Path, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "dissent"
        args = _make_args(
            receipt_file=str(receipt_file),
            output_dir=str(output_dir),
            output_format="json",
        )
        cmd_compliance_export(args)

        data = json.loads((output_dir / "transparency_report.json").read_text())
        assert len(data["dissenting_views"]) >= 1


# ---------------------------------------------------------------------------
# Human oversight report
# ---------------------------------------------------------------------------


class TestHumanOversightReport:
    """Test that human oversight data is correctly extracted."""

    def test_human_oversight_detected(self, receipt_file: Path, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "oversight"
        args = _make_args(
            receipt_file=str(receipt_file),
            output_dir=str(output_dir),
            output_format="json",
        )
        cmd_compliance_export(args)

        data = json.loads((output_dir / "human_oversight.json").read_text())
        assert data["human_oversight_detected"] is True
        assert data["oversight_model"] == "Human-in-the-Loop (HITL)"
        assert data["require_approval"] is True

    def test_voting_record_present(self, receipt_file: Path, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "votes"
        args = _make_args(
            receipt_file=str(receipt_file),
            output_dir=str(output_dir),
            output_format="json",
        )
        cmd_compliance_export(args)

        data = json.loads((output_dir / "human_oversight.json").read_text())
        assert data["voting_record"]["total_votes"] >= 1


# ---------------------------------------------------------------------------
# Accuracy report
# ---------------------------------------------------------------------------


class TestAccuracyReport:
    """Test accuracy and robustness metrics."""

    def test_confidence_and_robustness(self, receipt_file: Path, tmp_path: Path):
        from aragora.cli.commands.compliance_export import cmd_compliance_export

        output_dir = tmp_path / "accuracy"
        args = _make_args(
            receipt_file=str(receipt_file),
            output_dir=str(output_dir),
            output_format="json",
        )
        cmd_compliance_export(args)

        data = json.loads((output_dir / "accuracy_report.json").read_text())
        assert data["confidence"] == 0.85
        assert data["robustness_score"] == 0.80
        assert data["integrity_hash_present"] is True
        assert data["signature_present"] is True


# ---------------------------------------------------------------------------
# Subparser registration
# ---------------------------------------------------------------------------


class TestSubparserRegistration:
    """Test that the export subcommand registers correctly."""

    def test_compliance_command_dispatches_export(self, tmp_path: Path):
        """Verify the compliance dispatcher routes to export."""
        from aragora.cli.commands.compliance import cmd_compliance

        output_dir = tmp_path / "dispatch"
        args = _make_args(
            demo=True,
            output_dir=str(output_dir),
            compliance_command="export",
        )
        # Also set the generate_artifacts flag to False to avoid fallthrough
        args.generate_artifacts = False
        cmd_compliance(args)

        assert (output_dir / "bundle.json").exists()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**kwargs) -> mock.MagicMock:
    """Create a Namespace-like object with defaults for compliance export."""
    defaults = {
        "framework": "eu-ai-act",
        "debate_id": None,
        "receipt_file": None,
        "output_dir": "./compliance-pack",
        "output_format": "markdown",
        "include_receipts": True,
        "include_audit_trail": True,
        "demo": False,
        "generate_artifacts": False,
        "compliance_command": None,
    }
    defaults.update(kwargs)
    args = mock.MagicMock()
    for key, value in defaults.items():
        setattr(args, key, value)
    # Make getattr work correctly for compliance_export's getattr calls
    args.__contains__ = lambda self, key: key in defaults
    return args
