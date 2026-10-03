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


def _sample_cruxes() -> dict[str, Any]:
    return {
        "items": [
            {
                "claim_id": "c1",
                "statement": "The latency budget holds under burst load",
                "author": "agent-alpha",
                "crux_score": 0.82,
                "contesting_agents": ["agent-beta"],
            }
        ],
        "total_claims": 5,
        "total_disagreements": 1,
        "convergence_barrier": 0.41,
        "detector": "belief_network",
    }


class TestCruxReceiptIntegrity:
    """Crux receipts (schema >= 1.2) through the flagship `aragora verify`.

    Regression for #9506 round 5: an earlier inline hash copy omitted the
    cruxes branch, so every untampered --crux-cards receipt was reported
    tampered by this command (while `aragora receipt verify` passed).
    """

    def _crux_receipt_data(self) -> dict[str, Any]:
        data = _make_receipt_data(schema_version="1.2", include_checksum=False)
        data["input_hash"] = "deadbeef"
        data["risk_summary"] = {"critical": 0, "high": 0, "medium": 0, "low": 0, "total": 0}
        data["cruxes"] = _sample_cruxes()
        return data

    def test_untampered_crux_receipt_from_canonical_producer_verifies(self):
        """Round-trip: canonical producer hash -> _verify_receipt passes."""
        from aragora.gauntlet.receipt_models import DecisionReceipt

        data = self._crux_receipt_data()
        receipt_dict = DecisionReceipt.from_dict(data).to_dict()
        assert receipt_dict["cruxes"] == data["cruxes"]

        result = _verify_receipt(receipt_dict)

        assert result["valid"] is True
        integrity = next(c for c in result["checks"] if c["name"] == "integrity")
        assert integrity["passed"] is True
        # Honest coverage: crux receipts report cruxes + schema_version too.
        assert "cruxes" in integrity["covers"]
        assert "schema_version" in integrity["covers"]

    def test_tampered_cruxes_detected(self):
        data = self._crux_receipt_data()
        data["artifact_hash"] = _recompute_artifact_hash(data)
        data["cruxes"]["items"][0]["statement"] = "tampered"

        result = _verify_receipt(data)

        assert result["valid"] is False

    def test_schema_downgrade_detected(self):
        """1.2 -> 1.1 downgrade must fail: schema_version is bound into the
        hash for crux receipts, so the version signal cannot be stripped."""
        data = self._crux_receipt_data()
        data["artifact_hash"] = _recompute_artifact_hash(data)
        data["schema_version"] = "1.1"

        result = _verify_receipt(data)

        assert result["valid"] is False

    def test_pre_stamp_crux_receipt_with_11_schema_still_verifies(self):
        """#9414 shipped crux binding on main BEFORE the 1.2 stamp existed:
        persisted receipts carry cruxes + schema_version 1.1 with a hash
        computed WITHOUT schema_version. The version binding is gated on the
        1.2 stamp, so those audit receipts must keep verifying."""
        data = self._crux_receipt_data()
        data["schema_version"] = "1.1"
        pre_pr_material = json.dumps(
            {
                "receipt_id": data["receipt_id"],
                "gauntlet_id": data["gauntlet_id"],
                "input_hash": data["input_hash"],
                "risk_summary": data["risk_summary"],
                "verdict": data["verdict"],
                "confidence": data["confidence"],
                "cruxes": data["cruxes"],
            },
            sort_keys=True,
        )
        data["artifact_hash"] = hashlib.sha256(pre_pr_material.encode()).hexdigest()

        result = _verify_receipt(data)

        assert result["valid"] is True
        integrity = next(c for c in result["checks"] if c["name"] == "integrity")
        assert "cruxes" in integrity["covers"]
        assert "schema_version" not in integrity["covers"]

    def test_stripped_artifact_hash_crux_receipt_rejected(self):
        """Stripping artifact_hash from a crux receipt must not downgrade
        verification to the legacy 16-char checksum, which covers neither
        cruxes nor schema_version."""
        data = self._crux_receipt_data()
        data.pop("artifact_hash", None)
        data["checksum"] = _recompute_checksum(data)

        result = _verify_receipt(data)

        assert result["valid"] is False
        integrity = next(c for c in result["checks"] if c["name"] == "integrity")
        assert "requires the full" in integrity["detail"]

    def test_legacy_pre_crux_receipt_via_checksum_still_valid(self):
        """Pre-crux receipts keep the legacy checksum fallback."""
        data = _make_receipt_data(include_checksum=True)

        result = _verify_receipt(data)

        assert result["valid"] is True

    def test_legacy_receipt_hash_recipe_unchanged(self):
        """Pre-crux (1.1) receipts keep the original recipe: schema_version
        and cruxes are NOT bound, so existing stored hashes keep verifying."""
        data = _make_receipt_data(schema_version="1.1", include_checksum=False)
        legacy_material = json.dumps(
            {
                "receipt_id": data["receipt_id"],
                "gauntlet_id": data["gauntlet_id"],
                "input_hash": data.get("input_hash", ""),
                "risk_summary": data.get("risk_summary", {}),
                "verdict": data["verdict"],
                "confidence": data["confidence"],
            },
            sort_keys=True,
        )
        data["artifact_hash"] = hashlib.sha256(legacy_material.encode()).hexdigest()

        result = _verify_receipt(data)

        assert result["valid"] is True
        integrity = next(c for c in result["checks"] if c["name"] == "integrity")
        assert "schema_version" not in integrity["covers"]

    def test_inline_fallback_matches_canonical_recipe(self):
        """The no-gauntlet fallback must stay byte-equivalent to the shared
        canonical recipe for pre-crux, 1.2-stamped crux, and pre-stamp
        (#9414-era, schema 1.1) crux receipts."""
        from aragora.cli.commands.verify import _inline_artifact_hash
        from aragora.gauntlet.receipt_models import compute_receipt_artifact_hash

        plain = _make_receipt_data(include_checksum=False)
        crux = self._crux_receipt_data()
        pre_stamp_crux = self._crux_receipt_data()
        pre_stamp_crux["schema_version"] = "1.1"
        for data in (plain, crux, pre_stamp_crux):
            assert _inline_artifact_hash(data) == compute_receipt_artifact_hash(data)
            assert _recompute_artifact_hash(data) == _inline_artifact_hash(data)


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
