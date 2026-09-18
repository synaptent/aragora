from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/outcome_decision_quality_benchmark.py"


def test_validate_corpus_cli_reports_frozen_contract() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "validate-corpus"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(completed.stdout)

    assert completed.returncode == 0
    assert payload["ok"] is True
    assert payload["operation"] == "validate-corpus"
    assert payload["case_count"] == 24
    assert (
        payload["corpus_sha256"]
        == "3a46198fe33e4cc984cf777c6db7f046e4adb7db10840e775f83e9a46e87172b"
    )


def test_cli_exposes_only_contract_validation() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "run"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "invalid choice" in completed.stderr
