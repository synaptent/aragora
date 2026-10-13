from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from aragora.epistemic.executable_claim import ClaimManifest, ExecutableClaim


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "report_claim_freshness.py"
SPEC = importlib.util.spec_from_file_location("report_claim_freshness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _claim(*, state: str | None, last_verified_at: str | None = None) -> ExecutableClaim:
    raw = {
        "claim_id": f"test.{state or 'legacy'}",
        "statement": "A test claim.",
        "owner": "tests",
        "scope": "repo",
        "confidence": "high",
        "evidence": [{"note": "test"}],
        "freshness_sla_hours": 24,
        "verification": {"kind": "manual", "command": "inspect"},
        "failure": {
            "severity": "info",
            "allowed_action": "report_only",
            "repair_note": "Recheck it.",
        },
        "receipts": [{"type": "test"}],
    }
    if state is not None:
        raw["truth_status"] = {"state": state, "note": "Declared for test."}
        if last_verified_at is not None:
            raw["truth_status"]["last_verified_at"] = last_verified_at
    return ExecutableClaim.from_dict(raw)


def test_classifies_live_stale_unsupported_aspirational_and_legacy() -> None:
    as_of = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)
    cases = [
        (_claim(state="live", last_verified_at="2026-07-11T06:00:00Z"), "live"),
        (_claim(state="live", last_verified_at="2026-07-10T06:00:00Z"), "stale"),
        (_claim(state="unsupported"), "unsupported"),
        (_claim(state="aspirational"), "aspirational"),
        (_claim(state=None), "unsupported"),
    ]
    assert [MODULE.classify_claim(claim, as_of=as_of).status for claim, _ in cases] == [
        expected for _, expected in cases
    ]


def test_future_live_timestamp_fails_closed() -> None:
    row = MODULE.classify_claim(
        _claim(state="live", last_verified_at="2026-07-12T00:00:00Z"),
        as_of=datetime(2026, 7, 11, 12, tzinfo=timezone.utc),
    )
    assert row.status == "unsupported"
    assert row.age_hours is None
    assert "future" in row.note


def test_build_report_is_explicitly_non_mutating() -> None:
    manifest = ClaimManifest(
        schema_version=1,
        manifest_id="test",
        claims=[_claim(state="unsupported")],
    )
    report = MODULE.build_report(
        [manifest],
        as_of=datetime(2026, 7, 11, 12, tzinfo=timezone.utc),
    )
    assert report["queue_mutation"] is False
    assert report["summary"] == {
        "live": 0,
        "stale": 0,
        "unsupported": 1,
        "aspirational": 0,
    }


def test_cli_emits_json_and_does_not_execute_verification(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    marker = tmp_path / "must-not-exist"
    raw = _claim(state="unsupported").to_dict()
    raw["verification"] = {
        "kind": "command",
        "command": f"touch {marker}",
    }
    (claims_dir / "test.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "manifest_id": "test", "claims": [raw]}),
        encoding="utf-8",
    )
    output = tmp_path / "report.json"
    rc = MODULE.main(
        [
            "--claims-dir",
            str(claims_dir),
            "--format",
            "json",
            "--as-of",
            "2026-07-11T12:00:00Z",
            "--output",
            str(output),
        ]
    )
    assert rc == 0
    assert json.loads(output.read_text())["claims"][0]["status"] == "unsupported"
    assert not marker.exists()


def test_cli_rejects_malformed_live_metadata(tmp_path: Path, capsys) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    raw = _claim(state="unsupported").to_dict()
    raw["truth_status"] = {"state": "live"}
    (claims_dir / "bad.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "manifest_id": "bad", "claims": [raw]}),
        encoding="utf-8",
    )
    assert MODULE.main(["--claims-dir", str(claims_dir)]) == 2
    assert "requires last_verified_at" in capsys.readouterr().err
