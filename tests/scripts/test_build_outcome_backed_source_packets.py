from __future__ import annotations

import subprocess
import sys


def test_cli_requires_explicit_split() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build_outcome_backed_source_packets.py"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "--split" in result.stderr


def test_cli_help_declares_outcome_blind_contract() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build_outcome_backed_source_packets.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "outcome-blind" in result.stdout
    assert "development" in result.stdout
    assert "holdout" in result.stdout
