"""Keep advisory root gates observable without joining required checks."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/lint.yml").read_text())


def test_job_is_advisory_independent_and_provisions_tools() -> None:
    jobs = workflow()["jobs"]
    job = jobs["ratchets"]
    assert job["continue-on-error"] is True
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == 15
    assert "needs" not in job and "if" not in job
    for other in jobs.values():
        assert "ratchets" not in other.get("needs", [])
    uses = [step.get("uses", "") for step in job["steps"]]
    assert "./.github/actions/setup-python-safe" in uses
    assert "./.github/actions/setup-node-safe" in uses
    for action in ("checkout", "upload-artifact"):
        assert any(re.fullmatch(rf"actions/{action}@[0-9a-f]{{40}}", use) for use in uses)
    assert any(
        "python -m pip install -e '.[dev,test,readiness]'" in step.get("run", "")
        for step in job["steps"]
    )
    assert not any(
        re.search(r"(?<!-m[ \t])\bpip install\b", line)
        for step in job["steps"]
        for line in step.get("run", "").splitlines()
    )
    assert any(
        "GITHUB_STEP_SUMMARY" in step.get("run", "") and step.get("if") == "always()"
        for step in job["steps"]
    )
    upload = next(
        step for step in job["steps"] if "actions/upload-artifact@" in step.get("uses", "")
    )
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == "/tmp/ratchets/*.report.json"
    manifest = json.loads((ROOT / "scripts/ci/required_workflow_manifest.json").read_text())
    assert "ratchets" not in json.dumps(manifest)
    assert all((ROOT / path).is_file() for path in manifest["workflow_paths"])


@pytest.mark.parametrize(
    ("output", "status", "expected"),
    [
        ("all gates ran", 0, 0),
        ("SKIP root: missing tool", 0, 1),
        ("tool failed", 1, 1),
    ],
)
def test_ci_script_rejects_failure_and_vacuous_skip(
    tmp_path: Path, output: str, status: int, expected: int
) -> None:
    steps = workflow()["jobs"]["ratchets"]["steps"]
    step = next(step for step in steps if "make readiness-lint-root" in step.get("run", ""))
    assert step["shell"] == "bash"
    assert step["working-directory"] == "."
    fake = tmp_path / "make"
    fake.write_text(f"#!/bin/sh\nprintf '%s\\n' '{output}'\nexit {status}\n")
    fake.chmod(0o755)
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"},
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == expected, result.stdout + result.stderr
    assert (tmp_path / "ratchets.log").read_text().strip() == output


def test_every_shared_baseline_writes_a_report() -> None:
    makefile = (ROOT / "Makefile").read_text()
    recipe = makefile.split("readiness-lint-root:\n", 1)[1].split("\nreadiness-typecheck-root:", 1)[
        0
    ]
    for line in recipe.split("&&"):
        if "scripts/ci/check_" not in line or "check_file_sizes.py" in line:
            continue
        assert "--report-json" in line
        assert "$(READINESS_REPORT_DIR)" in line


def test_all_extra_does_not_reclassify_readiness_tools_as_runtime() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    extras = project["project"]["optional-dependencies"]
    deptry = project["tool"]["deptry"]
    assert {"dev", "test", "readiness", "all"} <= set(deptry["optional_dependencies_dev_groups"])
    # Every non-tool entry remains declared in an independently scanned runtime
    # extra; treating the convenience bundle as dev must not hide runtime debt.
    runtime = {
        spec
        for name, specs in extras.items()
        if name not in deptry["optional_dependencies_dev_groups"]
        for spec in specs
    }
    assert set(extras["all"]) - set(extras["readiness"]) <= runtime
    assert deptry["per_rule_ignores"]["DEP002"] == ["python-dateutil"]


def test_debt_register_covers_baselines_both_ways_and_counts() -> None:
    text = (ROOT / "docs/TECH_DEBT.md").read_text()
    for heading in ("Overview", "Ratchets", "Known debt items"):
        assert f"## {heading}" in text
    table = text.split("## Ratchets", 1)[1].split("## Known debt items", 1)[0]
    assert "| Tool | Baseline file | Current count | Owner | Regeneration command |" in table
    rows = {}
    for line in table.splitlines():
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        for path in re.findall(r"`(scripts/baselines/[^`]+\.json)`", cells[2]):
            assert (ROOT / path).is_file()
            rows[path] = int(cells[3].strip())
    expected = {}
    for path in (ROOT / "scripts/baselines").glob("*.json"):
        data = json.loads(path.read_text())
        if isinstance(data.get("tool"), str) and isinstance(data.get("findings"), dict):
            expected[path.relative_to(ROOT).as_posix()] = len(data["findings"])
        elif path.name == "file_size_baseline.json" or path.name.endswith("-file-sizes.json"):
            assert isinstance(data["files"], dict)
            expected[path.relative_to(ROOT).as_posix()] = len(data["files"])
    assert rows == expected
    for phrase in (
        "check_todo_ratchet.py",
        "scripts/todo_audit.py",
        "aragora/.todo_baseline",
        "coexist",
        "[tool.deptry]",
        ".jscpd.json",
        "threshold-only",
    ):
        assert phrase in table
    extras = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
        "optional-dependencies"
    ]
    assert extras["readiness"] == ["vulture>=2.16,<3.0", "deptry>=0.25.1,<1.0"]
    assert set(extras["readiness"]) <= set(extras["all"])
