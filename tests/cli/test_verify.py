"""Tests for ``aragora verify`` CLI command.

Validates that the verify command correctly:
- Detects valid receipts and returns exit code 0
- Detects tampered receipts and returns exit code 1
- Handles missing files gracefully
- Produces valid JSON output with --format json
- Handles receipts missing schema_version gracefully
"""

from __future__ import annotations

import argparse
import hashlib
import json
import textwrap
from pathlib import Path
from typing import Any

import pytest

from aragora.cli.commands.verify import (
    _is_valid_iso_timestamp,
    _is_valid_verdict,
    _has_epistemic_hash_fields,
    _recompute_legacy_artifact_hash,
    _recompute_artifact_hash,
    _recompute_checksum,
    _verify_receipt,
    cmd_verify,
    create_verify_parser,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_receipt_data(
    *,
    receipt_id: str = "rcpt_test123",
    verdict: str = "approved",
    confidence: float = 0.85,
    schema_version: str = "1.0",
    timestamp: str = "2026-02-11T10:00:00+00:00",
    findings: list[dict[str, Any]] | None = None,
    critical_count: int = 0,
    audit_trail_id: str | None = None,
    include_checksum: bool = True,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a minimal valid receipt dict with a correct checksum."""
    data: dict[str, Any] = {
        "receipt_id": receipt_id,
        "gauntlet_id": "gauntlet_test456",
        "timestamp": timestamp,
        "input_summary": "Test receipt",
        "input_type": "spec",
        "schema_version": schema_version,
        "verdict": verdict,
        "confidence": confidence,
        "risk_level": "LOW",
        "risk_score": 0.15,
        "robustness_score": 0.85,
        "coverage_score": 0.9,
        "verification_coverage": 0.0,
        "findings": findings or [],
        "critical_count": critical_count,
        "high_count": 0,
        "medium_count": 0,
        "low_count": 0,
        "mitigations": [],
        "dissenting_views": [],
        "unresolved_tensions": [],
        "verified_claims": [],
        "unverified_claims": [],
        "agents_involved": ["agent-a", "agent-b"],
        "rounds_completed": 3,
        "duration_seconds": 12.5,
        "audit_trail_id": audit_trail_id,
        "cost_usd": 0.0,
        "tokens_used": 0,
        "budget_limit_usd": None,
    }
    if extra:
        data.update(extra)
    if include_checksum:
        data["checksum"] = _recompute_checksum(data)
    return data


def _write_receipt(tmp_path: Path, data: dict[str, Any], filename: str = "receipt.json") -> Path:
    """Write receipt data to a temp JSON file and return the path."""
    path = tmp_path / filename
    path.write_text(json.dumps(data, indent=2))
    return path


def _old_vulnerable_artifact_hash(data: dict[str, Any]) -> str:
    """Recreate the pre-fix standalone verifier hash construction."""
    payload: dict[str, Any] = {
        "receipt_id": data.get("receipt_id", ""),
        "gauntlet_id": data.get("gauntlet_id", ""),
        "input_hash": data.get("input_hash", ""),
        "risk_summary": data.get("risk_summary", {}),
        "verdict": data.get("verdict", ""),
        "confidence": data.get("confidence", 0.0),
    }
    if data.get("unverified"):
        payload["unverified"] = data.get("unverified", []) or []
    if data.get("assumptions"):
        payload["assumptions"] = data.get("assumptions", []) or []
    if data.get("falsification"):
        payload["falsification"] = data.get("falsification")
    content = json.dumps(payload, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()


class _FakeArgs:
    """Minimal argparse.Namespace stand-in for cmd_verify."""

    def __init__(self, receipt_path: str, output_format: str = "text", verbose: bool = False):
        self.receipt_path = receipt_path
        self.output_format = output_format
        self.verbose = verbose


# ---------------------------------------------------------------------------
# Unit tests for internal helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Tests for the internal helper functions."""

    def test_is_valid_verdict_canonical(self):
        assert _is_valid_verdict("approved")
        assert _is_valid_verdict("approved_with_conditions")
        assert _is_valid_verdict("needs_review")
        assert _is_valid_verdict("rejected")

    def test_is_valid_verdict_case_insensitive(self):
        assert _is_valid_verdict("APPROVED")
        assert _is_valid_verdict("Rejected")

    def test_is_valid_verdict_invalid(self):
        assert not _is_valid_verdict("maybe")
        assert not _is_valid_verdict("")
        assert not _is_valid_verdict("unknown_verdict")

    def test_is_valid_iso_timestamp_valid(self):
        assert _is_valid_iso_timestamp("2026-02-11T10:00:00+00:00")
        assert _is_valid_iso_timestamp("2026-02-11T10:00:00")
        assert _is_valid_iso_timestamp("2026-02-11")

    def test_is_valid_iso_timestamp_invalid(self):
        assert not _is_valid_iso_timestamp("not-a-date")
        assert not _is_valid_iso_timestamp("")
        assert not _is_valid_iso_timestamp("2026/02/11")

    def test_recompute_checksum_deterministic(self):
        data = _make_receipt_data()
        c1 = _recompute_checksum(data)
        c2 = _recompute_checksum(data)
        assert c1 == c2
        assert len(c1) == 16  # SHA-256 truncated to 16 hex chars

    def test_has_epistemic_hash_fields_ignores_empty_defaults(self):
        data = {
            "unverified": [],
            "assumptions": [],
            "falsification": None,
        }

        assert _has_epistemic_hash_fields(data) is False

        data["unverified"] = ["Load test not run."]
        assert _has_epistemic_hash_fields(data) is True

    def test_has_epistemic_hash_fields_treats_malformed_fields_as_epistemic(self):
        assert _has_epistemic_hash_fields({"unverified": [" "]}) is True
        assert _has_epistemic_hash_fields(
            {"falsification": {"observation": "Latency rose above threshold."}}
        )


# ---------------------------------------------------------------------------
# Integration tests for _verify_receipt
# ---------------------------------------------------------------------------


class TestVerifyReceipt:
    """Tests for the _verify_receipt function."""

    def test_valid_receipt(self):
        data = _make_receipt_data()
        result = _verify_receipt(data)
        assert result["valid"] is True
        assert all(c["passed"] for c in result["checks"])

    def test_tampered_verdict(self):
        """Changing the verdict after checksum computation should fail."""
        data = _make_receipt_data(verdict="approved")
        # Tamper: change verdict without recomputing checksum
        data["verdict"] = "rejected"
        result = _verify_receipt(data)
        assert result["valid"] is False
        checksum_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert checksum_check["passed"] is False

    def test_tampered_confidence(self):
        """Changing confidence after checksum computation should fail."""
        data = _make_receipt_data(confidence=0.95)
        data["confidence"] = 0.1
        result = _verify_receipt(data)
        assert result["valid"] is False

    def test_dual_integrity_fields_require_both_to_match(self):
        """A valid artifact_hash must not mask a mismatched legacy checksum."""
        data = _make_receipt_data()
        data["artifact_hash"] = _recompute_artifact_hash(data)
        data["timestamp"] = "2026-02-11T10:00:01+00:00"

        result = _verify_receipt(data)

        assert result["valid"] is False
        integrity_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is False
        assert "checksum mismatch" in integrity_check["detail"]

    def test_checksum_artifact_hash_alias_is_supported(self):
        """Some canonicalized receipts mirror artifact_hash into checksum."""
        data = _make_receipt_data(include_checksum=False)
        artifact_hash = _recompute_artifact_hash(data)
        data["artifact_hash"] = artifact_hash
        data["checksum"] = artifact_hash

        result = _verify_receipt(data)

        assert result["valid"] is True
        integrity_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is True
        assert "checksum artifact_hash alias" in integrity_check["detail"]

    def test_artifact_hash_covers_epistemic_fields(self):
        """Audit-relevant epistemic fields are part of artifact_hash coverage."""
        data = _make_receipt_data(
            include_checksum=False,
            extra={
                "unverified": ["Load test not run."],
                "assumptions": ["Manual support can absorb rollout."],
                "falsification": {
                    "observation": "P95 latency exceeds 600ms.",
                    "check_by": "2026-07-15",
                },
            },
        )
        data["artifact_hash"] = _recompute_artifact_hash(data)

        result = _verify_receipt(data)

        assert result["valid"] is True
        integrity_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert {"unverified", "assumptions", "falsification"} <= set(integrity_check["covers"])

        data["falsification"]["observation"] = "Trial conversion drops below target."
        tampered = _verify_receipt(data)
        assert tampered["valid"] is False
        tampered_integrity = next(c for c in tampered["checks"] if c["name"] == "integrity")
        assert tampered_integrity["passed"] is False

    def test_artifact_hash_rejects_malformed_epistemic_fields_even_when_hash_matches(self):
        """Malformed epistemic fields must not be accepted by recomputing their hash."""
        data = _make_receipt_data(
            include_checksum=False,
            extra={
                "unverified": "claims without review",
                "falsification": {"observation": "Latency rose above threshold."},
            },
        )
        data["artifact_hash"] = _old_vulnerable_artifact_hash(data)

        result = _verify_receipt(data)

        assert result["valid"] is False
        integrity_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is False
        assert "malformed epistemic hash fields" in integrity_check["detail"]
        assert "unverified" in integrity_check["detail"]
        assert "falsification" in integrity_check["detail"]

    def test_legacy_artifact_hash_verifies_without_epistemic_fields(self):
        """Receipts hashed before epistemic fields existed remain verifiable."""
        data = _make_receipt_data(include_checksum=False)
        data["artifact_hash"] = _recompute_legacy_artifact_hash(data)

        result = _verify_receipt(data)

        assert result["valid"] is True
        integrity_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is True

        data["confidence"] = 0.1
        tampered = _verify_receipt(data)
        assert tampered["valid"] is False

    def test_legacy_artifact_hash_rejects_added_epistemic_fields(self):
        """Legacy hashes must not bless newly added audit-relevant fields."""
        data = _make_receipt_data(include_checksum=False)
        data["artifact_hash"] = _recompute_legacy_artifact_hash(data)
        data["unverified"] = ["Load test not run."]
        data["assumptions"] = ["Manual support can absorb rollout."]
        data["falsification"] = {
            "observation": "P95 latency exceeds 600ms.",
            "check_by": "2026-07-15",
        }

        result = _verify_receipt(data)

        assert result["valid"] is False
        integrity_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is False
        assert "legacy artifact_hash cannot validate epistemic fields" in integrity_check["detail"]

    def test_legacy_checksum_allows_empty_default_epistemic_fields(self):
        """Legacy checksums should not reject default fields with no epistemic content."""
        data = _make_receipt_data()
        data["unverified"] = []
        data["assumptions"] = []
        data["falsification"] = None

        result = _verify_receipt(data)

        assert result["valid"] is True
        integrity_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is True
        assert "checksum=" in integrity_check["detail"]

    def test_legacy_checksum_alias_rejects_added_epistemic_fields(self):
        """Legacy checksum artifact-hash aliases must fail closed on new epistemic fields."""
        data = _make_receipt_data(include_checksum=False)
        data["checksum"] = _recompute_legacy_artifact_hash(data)
        data["unverified"] = ["Load test not run."]
        data["assumptions"] = ["Manual support can absorb rollout."]
        data["falsification"] = {
            "observation": "P95 latency exceeds 600ms.",
            "check_by": "2026-07-15",
        }

        result = _verify_receipt(data)

        assert result["valid"] is False
        integrity_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is False
        assert (
            "legacy checksum artifact_hash alias cannot validate epistemic fields"
            in integrity_check["detail"]
        )

    def test_legacy_checksum_rejects_added_epistemic_fields(self):
        """Legacy 16-char checksums must fail closed on new epistemic fields."""
        data = _make_receipt_data()
        data["unverified"] = ["Load test not run."]
        data["assumptions"] = ["Manual support can absorb rollout."]
        data["falsification"] = {
            "observation": "P95 latency exceeds 600ms.",
            "check_by": "2026-07-15",
        }

        result = _verify_receipt(data)

        assert result["valid"] is False
        integrity_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is False
        assert "legacy checksum cannot validate epistemic fields" in integrity_check["detail"]

    def test_legacy_checksum_rejects_malformed_epistemic_fields(self):
        """Malformed epistemic fields still fail closed even if they normalize empty."""
        data = _make_receipt_data()
        data["unverified"] = [" "]

        result = _verify_receipt(data)

        assert result["valid"] is False
        integrity_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert integrity_check["passed"] is False
        assert "legacy checksum cannot validate epistemic fields" in integrity_check["detail"]

    def test_missing_schema_version(self):
        data = _make_receipt_data()
        del data["schema_version"]
        result = _verify_receipt(data)
        assert result["valid"] is False
        sv_check = next(c for c in result["checks"] if c["name"] == "schema_version")
        assert sv_check["passed"] is False

    def test_invalid_verdict_value(self):
        data = _make_receipt_data(verdict="banana")
        result = _verify_receipt(data)
        assert result["valid"] is False
        verdict_check = next(c for c in result["checks"] if c["name"] == "verdict")
        assert verdict_check["passed"] is False

    def test_missing_checksum(self):
        data = _make_receipt_data(include_checksum=False)
        result = _verify_receipt(data)
        assert result["valid"] is False
        checksum_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert checksum_check["passed"] is False

    def test_invalid_timestamp(self):
        data = _make_receipt_data(timestamp="not-a-date")
        result = _verify_receipt(data)
        assert result["valid"] is False
        ts_check = next(c for c in result["checks"] if c["name"] == "timestamp")
        assert ts_check["passed"] is False

    def test_verbose_shows_recomputed(self):
        data = _make_receipt_data()
        result = _verify_receipt(data, verbose=True)
        checksum_check = next(c for c in result["checks"] if c["name"] == "integrity")
        assert "recomputed=" in checksum_check["detail"]


# ---------------------------------------------------------------------------
# CLI cmd_verify tests
# ---------------------------------------------------------------------------


class TestCmdVerify:
    """End-to-end tests for cmd_verify through argparse namespace."""

    def test_verify_valid_receipt(self, tmp_path: Path):
        """A valid receipt should return exit code 0."""
        data = _make_receipt_data()
        path = _write_receipt(tmp_path, data)
        args = _FakeArgs(receipt_path=str(path))
        rc = cmd_verify(args)
        assert rc == 0

    def test_verify_invalid_receipt(self, tmp_path: Path):
        """A tampered receipt should return exit code 1."""
        data = _make_receipt_data()
        data["verdict"] = "rejected"  # tamper without recomputing checksum
        path = _write_receipt(tmp_path, data)
        args = _FakeArgs(receipt_path=str(path))
        rc = cmd_verify(args)
        assert rc == 1

    def test_verify_missing_file(self, tmp_path: Path, capsys):
        """A missing file should return exit code 1 with error message."""
        args = _FakeArgs(receipt_path=str(tmp_path / "nonexistent.json"))
        rc = cmd_verify(args)
        assert rc == 1
        captured = capsys.readouterr()
        assert "File not found" in captured.err or "not found" in captured.err.lower()

    def test_verify_json_output(self, tmp_path: Path, capsys):
        """--format json should produce valid JSON output."""
        data = _make_receipt_data()
        path = _write_receipt(tmp_path, data)
        args = _FakeArgs(receipt_path=str(path), output_format="json")
        rc = cmd_verify(args)
        assert rc == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["valid"] is True
        assert isinstance(output["checks"], list)
        assert output["receipt_id"] == "rcpt_test123"

    def test_verify_json_output_invalid(self, tmp_path: Path, capsys):
        """--format json with invalid receipt should produce valid JSON with valid=false."""
        data = _make_receipt_data()
        data["verdict"] = "rejected"  # tamper
        path = _write_receipt(tmp_path, data)
        args = _FakeArgs(receipt_path=str(path), output_format="json")
        rc = cmd_verify(args)
        assert rc == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["valid"] is False

    def test_verify_invalid_schema(self, tmp_path: Path, capsys):
        """Receipt missing schema_version should be handled gracefully."""
        data = _make_receipt_data()
        del data["schema_version"]
        path = _write_receipt(tmp_path, data)
        args = _FakeArgs(receipt_path=str(path), output_format="json")
        rc = cmd_verify(args)
        assert rc == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["valid"] is False
        sv_check = next(c for c in output["checks"] if c["name"] == "schema_version")
        assert sv_check["passed"] is False

    def test_verify_missing_file_json_output(self, tmp_path: Path, capsys):
        """Missing file with --format json should produce valid JSON error."""
        args = _FakeArgs(
            receipt_path=str(tmp_path / "gone.json"),
            output_format="json",
        )
        rc = cmd_verify(args)
        assert rc == 1
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["valid"] is False
        assert "error" in output

    def test_verify_malformed_json(self, tmp_path: Path, capsys):
        """A file with invalid JSON should return exit code 1."""
        path = tmp_path / "bad.json"
        path.write_text("{ not valid json !!!")
        args = _FakeArgs(receipt_path=str(path))
        rc = cmd_verify(args)
        assert rc == 1

    def test_verify_verbose(self, tmp_path: Path, capsys):
        """--verbose should show additional details in text output."""
        data = _make_receipt_data()
        path = _write_receipt(tmp_path, data)
        args = _FakeArgs(receipt_path=str(path), verbose=True)
        rc = cmd_verify(args)
        assert rc == 0
        captured = capsys.readouterr()
        assert "PASS" in captured.out
        assert "VALID" in captured.out

    def test_verify_non_dict_json(self, tmp_path: Path, capsys):
        """A JSON file containing a list (not dict) should fail gracefully."""
        path = tmp_path / "list.json"
        path.write_text("[1, 2, 3]")
        args = _FakeArgs(receipt_path=str(path))
        rc = cmd_verify(args)
        assert rc == 1

    def test_verify_receipt_with_findings(self, tmp_path: Path):
        """A receipt with findings should still verify if checksum is valid."""
        findings = [
            {
                "id": "f1",
                "severity": "MEDIUM",
                "category": "test",
                "title": "Test finding",
                "description": "A test finding",
                "mitigation": None,
                "source": "agent-a",
                "verified": False,
            }
        ]
        data = _make_receipt_data(findings=findings)
        path = _write_receipt(tmp_path, data)
        args = _FakeArgs(receipt_path=str(path))
        rc = cmd_verify(args)
        assert rc == 0


# ---------------------------------------------------------------------------
# Help-text tests: `aragora receipt verify --help` (VAL-VERIFY-013)
#
# The `receipt verify` subcommand (aragora/cli/commands/receipt.py) is a
# separate implementation from the top-level `verify` command tested above:
# it checks artifact_hash presence, recomputes the SHA-256 decision-integrity
# hash, checks required-field presence, and (if present) verifies a
# cryptographic signature -- but unlike `cmd_verify` it does NOT fall back to
# a legacy `checksum` field. Its --help text must describe that real behavior
# instead of being blank, and must stay disambiguated from the standalone
# `aragora-verify` ODR verifier per docs/specs/INDEPENDENT_VERIFIER_GUIDE.md.
# ---------------------------------------------------------------------------


def _build_receipt_verify_subparser() -> argparse.ArgumentParser:
    """Construct just the 'receipt verify' subparser for help-text inspection."""
    from aragora.cli.commands.receipt import add_receipt_parser

    root = argparse.ArgumentParser(prog="aragora")
    subparsers = root.add_subparsers(dest="command")
    add_receipt_parser(subparsers)
    receipt_parser = subparsers.choices["receipt"]

    receipt_subparsers_action = next(
        action
        for action in receipt_parser._actions  # noqa: SLF001
        if isinstance(getattr(action, "choices", None), dict)
    )
    return receipt_subparsers_action.choices["verify"]


def _build_top_level_verify_parser() -> argparse.ArgumentParser:
    """Construct just the top-level 'verify' parser for help-text inspection."""
    root = argparse.ArgumentParser(prog="aragora")
    subparsers = root.add_subparsers(dest="command")
    create_verify_parser(subparsers)
    return subparsers.choices["verify"]


# Terms that must appear (case-insensitively) in help text describing native
# DecisionReceipt integrity verification, per the disambiguation table in
# docs/specs/INDEPENDENT_VERIFIER_GUIDE.md: native = in-repo DecisionReceipt
# checks (SHA-256 hash recompute + tamper detection + signature check), as
# opposed to the standalone `aragora-verify` ODR document verifier.
_NATIVE_INTEGRITY_TERMS = ("sha-256", "artifact_hash", "tamper", "signature")


class TestReceiptVerifyHelpText:
    """`aragora receipt verify --help` must describe what it actually verifies."""

    def test_receipt_verify_has_nonempty_description(self):
        """The subparser must declare a description, not rely on `help=` alone."""
        verify_subparser = _build_receipt_verify_subparser()
        assert verify_subparser.description, "receipt verify must have a description"

    def test_receipt_verify_description_mentions_native_integrity_terms(self):
        """Description must name the real checks: SHA-256 hash, tamper, signature."""
        verify_subparser = _build_receipt_verify_subparser()
        description = verify_subparser.description.lower()
        for term in _NATIVE_INTEGRITY_TERMS:
            assert term in description, f"expected {term!r} in receipt verify description"
        assert "decisionreceipt" in description

    def test_receipt_verify_description_disambiguates_from_odr_verifier(self):
        """Description should point ODR holders at the standalone verifier instead."""
        verify_subparser = _build_receipt_verify_subparser()
        description = verify_subparser.description.lower()
        assert "aragora-verify" in description or "odr" in description

    def test_receipt_verify_help_exits_zero_and_prints_native_terms(self, capsys):
        """`aragora receipt verify --help` must exit 0 and print the description."""
        verify_subparser = _build_receipt_verify_subparser()
        with pytest.raises(SystemExit) as exc_info:
            verify_subparser.parse_args(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        output = captured.out.lower()
        for term in _NATIVE_INTEGRITY_TERMS:
            assert term in output

    def test_top_level_verify_help_still_exits_zero_and_prints_native_terms(self, capsys):
        """`aragora verify --help` keeps describing native verification (no regression)."""
        verify_parser = _build_top_level_verify_parser()
        with pytest.raises(SystemExit) as exc_info:
            verify_parser.parse_args(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        output = captured.out.lower()
        for term in _NATIVE_INTEGRITY_TERMS:
            assert term in output
