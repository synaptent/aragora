"""Execute semantic checker/runtime scenarios, not just their collection."""

from __future__ import annotations

import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CHECKER_CASES = {
    "test_checker_cli_aligned[default]",
    "test_checker_cli_aligned[check]",
    "test_checker_cli_fix",
    "test_checker_cli_minor",
    *{
        f"test_checker_cli_stale[{case}]"
        for case in ("manifest", "sdk", "lock", "doc", "date", "later")
    },
    *{
        f"test_checker_cli_unusable[{case}]"
        for case in ("manifest", "pattern", "canonical", "malformed")
    },
}
RUNTIME_CASES = {
    *{
        f"test_runner_capability[{state}-{outcome}]"
        for state in ("absent", "none", "injected")
        for outcome in ("return", "error")
    },
    "test_native_sync[result]",
    "test_native_sync[error]",
    "test_offline_cli",
}


@pytest.mark.parametrize(
    ("suite", "required", "selection"),
    [
        (
            "scripts/test_check_version_alignment.py",
            CHECKER_CASES,
            "test_checker_cli or test_repo_docs_are_aligned",
        ),
        (
            "cli/test_quickstart.py",
            RUNTIME_CASES,
            "test_runner_capability or test_native_sync or test_offline_cli "
            "or test_run_sync_prefers_runner_when_available",
        ),
    ],
    ids=["checker", "runtime"],
)
def test_required_scenarios_execute(suite, required, selection, tmp_path):
    report = tmp_path / "scenarios.xml"
    env = {
        "HOME": str(tmp_path),
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": f"{ROOT}:{ROOT / 'aragora-verify/src'}",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "ARAGORA_USE_SECRETS_MANAGER": "false",
        "ARAGORA_SECRETS_STRICT": "false",
        "ARAGORA_DB_BACKEND": "sqlite",
        "ARAGORA_DATA_DIR": str(tmp_path / "data"),
        "ARAGORA_LOG_DIR": str(tmp_path / "logs"),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(ROOT / "tests" / suite),
            "-c",
            str(ROOT / "pyproject.toml"),
            "--rootdir",
            str(tmp_path),
            "-k",
            selection,
            "-q",
            "-ra",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(tmp_path / "child"),
            "--junitxml",
            str(report),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert report.exists(), result.stdout + result.stderr
    cases = ET.parse(report).findall(".//testcase")
    names = {case.attrib["name"] for case in cases}
    assert required <= names, f"Missing semantic scenarios: {sorted(required - names)}"
    bad = [
        case.attrib["name"]
        for case in cases
        if any(case.find(tag) is not None for tag in ("skipped", "failure", "error"))
    ]
    assert not bad, f"Unsuccessful semantic scenarios: {bad}\n{result.stdout}"
    # Non-strict XPASS has a successful JUnit testcase and exit status.
    xpasses = [line for line in result.stdout.splitlines() if line.startswith("XPASS ")]
    assert not xpasses, f"XPASS semantic scenarios: {xpasses}\n{result.stdout}"
    assert result.returncode == 0, result.stdout + result.stderr
