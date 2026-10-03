from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_boss_cycle.sh"


def _write_fake_python3(tmp_path: Path) -> tuple[Path, Path]:
    log_path = tmp_path / "python3.log"
    fake_python3 = tmp_path / "python3"
    fake_python3.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
{
  first=1
  for arg in "$@"; do
    if [[ "$first" -eq 0 ]]; then
      printf '\\t'
    fi
    printf '%s' "$arg"
    first=0
  done
  printf '\\n'
} >> "${FAKE_PYTHON3_LOG}"
if [[ "${1:-}" == "-u" ]]; then
  exit "${FAKE_PYTHON3_BOSS_EXIT:-0}"
fi
if [[ "${1:-}" == "-c" && "${2:-}" == *"${FAKE_PYTHON3_IMPORT_FAIL_PATTERN:-__never_match__}"* ]]; then
  exit "${FAKE_PYTHON3_IMPORT_FAIL_EXIT:-23}"
fi
if [[ "${1:-}" == "-c" ]]; then
  exit 0
fi
exit "${FAKE_PYTHON3_REFILL_EXIT:-0}"
""",
        encoding="utf-8",
    )
    fake_python3.chmod(0o755)
    return fake_python3, log_path


def _read_calls(log_path: Path) -> list[list[str]]:
    if not log_path.exists():
        return []
    return [line.split("\t") for line in log_path.read_text(encoding="utf-8").splitlines() if line]


def _runtime_calls(log_path: Path) -> list[list[str]]:
    return [call for call in _read_calls(log_path) if call[:1] != ["-c"]]


@pytest.mark.parametrize("refill_exit", [0, 1])
def test_run_boss_cycle_propagates_post_loop_refill_status(
    tmp_path: Path, refill_exit: int
) -> None:
    _fake_python3, log_path = _write_fake_python3(tmp_path)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin"
    env["FAKE_PYTHON3_LOG"] = str(log_path)
    env["FAKE_PYTHON3_BOSS_EXIT"] = "0"
    env["FAKE_PYTHON3_REFILL_EXIT"] = str(refill_exit)
    env["ARAGORA_POST_LOOP_DRY_RUN"] = "1"
    env["ARAGORA_POST_LOOP_MAX_ISSUES"] = "7"
    env["ARAGORA_POST_LOOP_ISSUE_REFILL"] = "1"
    env["ARAGORA_SUBSTRATE_CAP"] = "0.3"
    env["ARAGORA_CLOSURE_FLOOR"] = "0.25"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--boss-repo",
            "org/repo",
            "--label",
            "lane:test",
            "--worker-model",
            "codex",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == refill_exit
    calls = _runtime_calls(log_path)
    assert len(calls) == 2
    assert calls[0][:5] == ["-u", "-m", "aragora.cli.main", "swarm", "boss-loop"]
    assert "--boss-repo" in calls[0]
    assert "org/repo" in calls[0]
    assert calls[1] == [
        "scripts/generate_boss_issues.py",
        "--repo",
        "org/repo",
        "--max-issues",
        "7",
        "--label",
        "lane:test",
        "--substrate-cap",
        "0.3",
        "--closure-floor",
        "0.25",
        "--dry-run",
    ]


def test_run_boss_cycle_skips_post_loop_refill_after_failure(tmp_path: Path) -> None:
    _fake_python3, log_path = _write_fake_python3(tmp_path)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:{env['PATH']}"
    env["FAKE_PYTHON3_LOG"] = str(log_path)
    env["FAKE_PYTHON3_BOSS_EXIT"] = "9"
    env["FAKE_PYTHON3_REFILL_EXIT"] = "0"
    env["ARAGORA_POST_LOOP_ISSUE_REFILL"] = "1"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--boss-repo",
            "org/repo",
            "--label",
            "boss-ready",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 9
    calls = _runtime_calls(log_path)
    assert len(calls) == 1
    assert calls[0][:5] == ["-u", "-m", "aragora.cli.main", "swarm", "boss-loop"]
    assert "Skipping post-loop issue refill because boss loop exited non-zero." in result.stderr


def test_run_boss_cycle_rejects_python_without_boss_loop_imports(tmp_path: Path) -> None:
    _fake_python3, log_path = _write_fake_python3(tmp_path)
    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}:/usr/bin:/bin:/usr/sbin:/sbin"
    env["FAKE_PYTHON3_LOG"] = str(log_path)
    env["FAKE_PYTHON3_IMPORT_FAIL_PATTERN"] = "aragora.cli.commands.swarm"

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT_PATH),
            "--boss-repo",
            "org/repo",
            "--label",
            "boss-ready",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert _runtime_calls(log_path) == []
    assert "Skipping Python candidate without usable boss-loop imports:" in result.stderr
    assert (
        "No usable python interpreter with pydantic and boss-loop imports found for boss-loop runtime."
        in result.stderr
    )
