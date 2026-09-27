"""Tests for aragora.epistemic.claim_verifier (DIC-14 / #6024).

All tests run without network access or subprocess calls — command
execution is injected via the ``command_runner`` hook.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml

from aragora.epistemic.claim_verifier import ClaimResult, ClaimStatus, ClaimVerifier


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _stub_pass(args: list[str]) -> tuple[int, str, str]:
    return 0, "ok", ""


def _stub_fail(args: list[str]) -> tuple[int, str, str]:
    return 1, "", "something went wrong"


def _stub_raise(args: list[str]) -> tuple[int, str, str]:
    raise RuntimeError("injected runner error")


def _make_claim(
    *,
    claim_id: str = "test.claim",
    kind: str = "command",
    command: str = "python3 -c 'pass'",
    freshness_sla_hours: int = 24,
    evidence: list[dict] | None = None,
    severity: str = "info",
    allowed_action: str = "report_only",
) -> dict:
    return {
        "claim_id": claim_id,
        "statement": "Test claim.",
        "owner": "test",
        "scope": "repo",
        "confidence": "high",
        "freshness_sla_hours": freshness_sla_hours,
        "evidence": evidence or [],
        "verification": {"kind": kind, "command": command},
        "failure": {"severity": severity, "allowed_action": allowed_action},
        "receipts": [{"type": "test"}],
    }


# ---------------------------------------------------------------------------
# Status outcome tests
# ---------------------------------------------------------------------------


class TestClaimStatus:
    def test_pass_on_zero_exit(self) -> None:
        verifier = ClaimVerifier(command_runner=_stub_pass)
        result = verifier.verify_claim(_make_claim())
        assert result.status == ClaimStatus.PASS
        assert result.claim_id == "test.claim"

    def test_fail_on_nonzero_exit(self) -> None:
        verifier = ClaimVerifier(command_runner=_stub_fail)
        result = verifier.verify_claim(_make_claim())
        assert result.status == ClaimStatus.FAIL
        assert "1" in result.message

    def test_error_when_runner_raises(self) -> None:
        verifier = ClaimVerifier(command_runner=_stub_raise)
        result = verifier.verify_claim(_make_claim())
        assert result.status == ClaimStatus.ERROR
        assert "injected runner error" in result.message

    def test_unsupported_workflow_kind(self) -> None:
        verifier = ClaimVerifier(command_runner=_stub_pass)
        result = verifier.verify_claim(_make_claim(kind="workflow"))
        assert result.status == ClaimStatus.UNSUPPORTED
        assert "workflow" in result.message

    def test_unsupported_manual_kind(self) -> None:
        verifier = ClaimVerifier(command_runner=_stub_pass)
        result = verifier.verify_claim(_make_claim(kind="manual"))
        assert result.status == ClaimStatus.UNSUPPORTED

    def test_unsupported_unknown_kind(self) -> None:
        verifier = ClaimVerifier(command_runner=_stub_pass)
        result = verifier.verify_claim(_make_claim(kind="http_probe"))
        assert result.status == ClaimStatus.UNSUPPORTED
        assert "http_probe" in result.message

    def test_dry_run_skips_command(self) -> None:
        ran: list[bool] = []

        def tracking_runner(args: list[str]) -> tuple[int, str, str]:
            ran.append(True)
            return 0, "", ""

        verifier = ClaimVerifier(command_runner=tracking_runner, dry_run=True)
        result = verifier.verify_claim(_make_claim())
        assert result.status == ClaimStatus.UNSUPPORTED
        assert not ran, "runner should not have been called in dry_run mode"


# ---------------------------------------------------------------------------
# Freshness / staleness tests
# ---------------------------------------------------------------------------


class TestFreshnessCheck:
    def test_stale_when_file_exceeds_sla(self, tmp_path: Path) -> None:
        old_file = tmp_path / "old.json"
        old_file.write_text("{}")
        past = time.time() - 3601  # 1 hour 1 second ago
        import os

        os.utime(old_file, (past, past))

        claim = _make_claim(
            freshness_sla_hours=1,
            evidence=[{"path": str(old_file)}],
        )
        verifier = ClaimVerifier(command_runner=_stub_pass)
        result = verifier.verify_claim(claim)
        assert result.status == ClaimStatus.STALE
        assert str(old_file) in result.detail.get("stale_paths", [])

    def test_fresh_file_does_not_stale(self, tmp_path: Path) -> None:
        fresh_file = tmp_path / "fresh.json"
        fresh_file.write_text("{}")

        claim = _make_claim(
            freshness_sla_hours=24,
            evidence=[{"path": str(fresh_file)}],
        )
        verifier = ClaimVerifier(command_runner=_stub_pass)
        result = verifier.verify_claim(claim)
        assert result.status == ClaimStatus.PASS

    def test_missing_evidence_path_errors_before_command(self) -> None:
        claim = _make_claim(
            freshness_sla_hours=1,
            evidence=[{"path": "/nonexistent/path/that/does/not/exist.json"}],
        )

        ran: list[list[str]] = []

        def tracking_runner(args: list[str]) -> tuple[int, str, str]:
            ran.append(args)
            return _stub_pass(args)

        verifier = ClaimVerifier(command_runner=tracking_runner)
        result = verifier.verify_claim(claim)
        assert result.status == ClaimStatus.ERROR
        assert "evidence path missing" in result.message
        assert result.detail["missing_paths"] == ["/nonexistent/path/that/does/not/exist.json"]
        assert not ran, "runner should not execute when path evidence is missing"

    def test_missing_relative_evidence_path_reports_manifest_path(self, tmp_path: Path) -> None:
        claim = _make_claim(
            freshness_sla_hours=1,
            evidence=[{"path": "missing/claim-evidence.json"}],
        )
        verifier = ClaimVerifier(repo_root=tmp_path, command_runner=_stub_pass)
        result = verifier.verify_claim(claim)
        assert result.status == ClaimStatus.ERROR
        assert result.detail["missing_paths"] == ["missing/claim-evidence.json"]

    def test_non_path_evidence_skipped(self) -> None:
        claim = _make_claim(
            freshness_sla_hours=1,
            evidence=[{"workflow": "Benchmark Truth Publication"}],
        )
        verifier = ClaimVerifier(command_runner=_stub_pass)
        result = verifier.verify_claim(claim)
        assert result.status != ClaimStatus.STALE


# ---------------------------------------------------------------------------
# Severity and metadata propagation
# ---------------------------------------------------------------------------


class TestResultMetadata:
    def test_severity_propagated_on_fail(self) -> None:
        verifier = ClaimVerifier(command_runner=_stub_fail)
        result = verifier.verify_claim(
            _make_claim(severity="blocking", allowed_action="propose_bounded_issue")
        )
        assert result.severity == "blocking"
        assert result.allowed_action == "propose_bounded_issue"

    def test_elapsed_ms_positive(self) -> None:
        verifier = ClaimVerifier(command_runner=_stub_pass)
        result = verifier.verify_claim(_make_claim())
        assert result.elapsed_ms >= 0

    def test_to_dict_includes_status_string(self) -> None:
        verifier = ClaimVerifier(command_runner=_stub_pass)
        result = verifier.verify_claim(_make_claim())
        d = result.to_dict()
        assert d["status"] == "pass"
        assert isinstance(d["elapsed_ms"], float)


# ---------------------------------------------------------------------------
# JSON report
# ---------------------------------------------------------------------------


class TestReportJson:
    def test_json_structure(self) -> None:
        verifier = ClaimVerifier(command_runner=_stub_pass)
        results = [verifier.verify_claim(_make_claim())]
        raw = verifier.report_json(results)
        doc = json.loads(raw)
        assert doc["schema_version"] == 1
        assert "results" in doc
        assert "summary" in doc
        assert doc["summary"]["pass"] == 1
        assert doc["summary"]["fail"] == 0

    def test_summary_counts_all_statuses(self) -> None:
        verifier_pass = ClaimVerifier(command_runner=_stub_pass)
        verifier_fail = ClaimVerifier(command_runner=_stub_fail)
        results = [
            verifier_pass.verify_claim(_make_claim(claim_id="c1")),
            verifier_fail.verify_claim(_make_claim(claim_id="c2")),
            verifier_pass.verify_claim(_make_claim(claim_id="c3", kind="workflow")),
        ]
        doc = json.loads(ClaimVerifier.report_json(results))
        assert doc["summary"]["pass"] == 1
        assert doc["summary"]["fail"] == 1
        assert doc["summary"]["unsupported"] == 1


# ---------------------------------------------------------------------------
# Manifest loading
# ---------------------------------------------------------------------------


class TestVerifyManifest:
    def test_verify_manifest_from_yaml(self, tmp_path: Path) -> None:
        manifest = {
            "schema_version": 1,
            "manifest_id": "test_manifest",
            "claims": [
                _make_claim(claim_id="m.pass"),
                _make_claim(claim_id="m.unsupported", kind="workflow"),
            ],
        }
        path = tmp_path / "test_claims.yaml"
        path.write_text(yaml.dump(manifest))

        verifier = ClaimVerifier(command_runner=_stub_pass)
        results = verifier.verify_manifest(path)
        assert len(results) == 2
        assert results[0].claim_id == "m.pass"
        assert results[0].status == ClaimStatus.PASS
        assert results[1].claim_id == "m.unsupported"
        assert results[1].status == ClaimStatus.UNSUPPORTED

    def test_verify_real_proof_first_claims(self) -> None:
        """Smoke test: the DIC-13 manifest parses and every claim returns a result."""
        manifest_path = (
            Path(__file__).parents[2] / "docs" / "status" / "claims" / "proof_first_claims.yaml"
        )
        assert manifest_path.exists(), "required proof-first claims manifest is missing"

        verifier = ClaimVerifier(dry_run=True)
        results = verifier.verify_manifest(manifest_path)
        assert len(results) >= 3
        statuses = {r.claim_id: r.status for r in results}
        # In dry_run all command-kind claims → unsupported (not error)
        assert ClaimStatus.ERROR not in statuses.values()
