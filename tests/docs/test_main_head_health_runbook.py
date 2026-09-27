from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = REPO_ROOT / "docs" / "runbooks" / "RUNBOOK_MAIN_HEAD_HEALTH.md"


def test_generate_validate_proxy_uses_one_unique_spec_path() -> None:
    row = next(
        line
        for line in RUNBOOK.read_text(encoding="utf-8").splitlines()
        if line.startswith("| `Generate & Validate` |")
    )

    assert "/tmp/openapi_ci_required.json" not in row
    assert row.count("mktemp -d") == 1
    assert row.count('SPEC="$SPEC_DIR/openapi.json"') == 1
    assert row.count('--output "$SPEC"') == 1
    assert row.count('--spec "$SPEC"') == 4
    assert row.count('--extra-spec "$SPEC"') == 1


def test_historical_snapshot_cannot_claim_red_main_from_wrong_python() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    snapshot = text.split("## Historical Snapshot: 2026-07-08", maxsplit=1)[1]

    assert "`non_comparable_environment`" in snapshot
    assert "Python 3.11.11 does not match the required Python 3.12.12" in snapshot
    assert "not evidence that\n`origin/main` was red" in snapshot
    assert "Disposition: `origin/main` is not locally green" not in snapshot
