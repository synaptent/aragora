"""Keep the live PR gates, coverage and documented build contract connected."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
LIVE = ROOT / "aragora/live"


def dry_run(*targets: str) -> str:
    result = subprocess.run(
        ["make", "-n", *targets], cwd=ROOT, text=True, capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_size_limit_pins_and_client_asset_budgets() -> None:
    deps = json.loads((LIVE / "package.json").read_text())["devDependencies"]
    assert deps["size-limit"] == deps["@size-limit/file"] == "13.0.3"
    budgets = json.loads((LIVE / ".size-limit.json").read_text())
    assert {entry["path"] for entry in budgets} == {
        ".next/static/**/*.js",
        ".next/static/**/*.css",
    }
    for entry in budgets:
        assert entry["name"]
        assert re.fullmatch(r"[1-9]\d* B", entry["limit"])


def test_heavy_target_is_separate_from_all_aggregates() -> None:
    heavy = dry_run("readiness-heavy-live")
    assert heavy.index("npm run build:local") < heavy.index("npx size-limit")
    assert "SKIP live:" in heavy and "node_modules" in heavy
    assert not re.search(r"\b(PORT=|--port|next start|next dev)\b", heavy)
    fast = dry_run("readiness-lint", "readiness-typecheck", "readiness-test")
    for command in ("build:local", "size-limit", "next build"):
        assert command not in fast
    assert "npx jest --ci --coverage --maxWorkers=4" in dry_run("readiness-test-live")


def test_jest_collects_coverage_with_thresholds_and_junit() -> None:
    if not shutil.which("node") or not (LIVE / "node_modules/next").is_dir():
        pytest.skip("live Node toolchain not installed")
    result = subprocess.run(
        [
            "node",
            "-e",
            "require('./jest.config.js')().then(c => console.log(JSON.stringify(c)))",
        ],
        cwd=LIVE,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["collectCoverage"] is True
    assert config["testMatch"] == ["**/__tests__/**/*.[jt]s?(x)", "**/*.test.[jt]s?(x)"]
    thresholds = config["coverageThreshold"]["global"]
    assert set(thresholds) == {"statements", "branches", "functions", "lines"}
    assert all(20 <= value <= 100 for value in thresholds.values())
    reporter = next(r for r in config["reporters"] if isinstance(r, list))
    assert reporter == ["jest-junit", {"outputDirectory": ".", "outputName": "junit.xml"}]
    assert (
        subprocess.run(
            ["git", "check-ignore", "-q", "aragora/live/junit.xml"], cwd=ROOT, timeout=10
        ).returncode
        == 0
    )


def test_frontend_job_is_scoped_to_ready_frontend_prs() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/lint.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert "ready_for_review" in triggers["pull_request"]["types"]
    jobs = workflow["jobs"]
    assert jobs["changes"]["outputs"]["frontend"] == "${{ steps.scope.outputs.frontend }}"
    job = jobs["frontend-lint"]
    assert job["needs"] == ["changes"]
    assert job["if"] == (
        "(github.event_name != 'pull_request' || "
        "(!github.event.pull_request.draft && needs.changes.outputs.frontend == 'true'))"
    )
    assert job["timeout-minutes"] <= 10
    assert not job.get("continue-on-error")
    for action in ("actions/checkout", "actions/upload-artifact"):
        step = next(s for s in job["steps"] if s.get("uses", "").startswith(action + "@"))
        assert re.fullmatch(action + r"@[0-9a-f]{40}", step["uses"])
        if action == "actions/checkout":
            assert step["with"]["persist-credentials"] is False


def test_frontend_job_runs_every_live_gate() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/lint.yml").read_text())
    job = workflow["jobs"]["frontend-lint"]
    for target in ("readiness-lint-live", "readiness-typecheck-live", "readiness-test-live"):
        step = next(s for s in job["steps"] if target in s.get("run", ""))
        assert step["working-directory"] == "."
        assert not step.get("continue-on-error") and "if" not in step
    heavy = next(s for s in job["steps"] if "readiness-heavy-live" in s.get("run", ""))
    assert heavy["working-directory"] == "." and not heavy.get("continue-on-error")
    assert "if" not in heavy
    for step in job["steps"]:
        if "make readiness-" in step.get("run", ""):
            assert step["shell"] == "bash"
            assert "set -euo pipefail" in step["run"]
            assert "! grep -q '^SKIP live:'" in step["run"]
    actions = {step.get("uses"): step for step in job["steps"]}
    assert actions["./.github/actions/setup-python-safe"]["with"]["python-version"] == "3.11"
    assert "./.github/actions/setup-node-safe" in actions
    assert any(step.get("run") == "npm ci" for step in job["steps"])
    commands = dry_run("readiness-lint-live", "readiness-typecheck-live", "readiness-test-live")
    for command in (
        "npm run typecheck",
        "npm run lint",
        "npm run format:check",
        "check_tool_baseline.py --tool knip",
        "npx jscpd --config .jscpd.json",
        "check_file_sizes.py --glob 'aragora/live/src/**/*.{ts,tsx}'",
        "npx jest --ci --coverage",
    ):
        assert command in commands


def test_readme_sections_and_environment_inventory() -> None:
    readme = (LIVE / "README.md").read_text()
    parts = re.split(r"^## (.+)$", readme, flags=re.MULTILINE)
    sections = dict(zip(parts[1::2], parts[2::2]))
    for name in ("Run", "Build", "Test", "Lint", "Env vars", "Observability", "Health"):
        assert sections[name].strip()
    assert sections["Run"].index("npm ci") < sections["Run"].index("npm run dev")
    for command in ("npm run build:local", "npx size-limit", "server.js"):
        assert command in sections["Build"]
    assert "/healthz/" in sections["Health"]
    sources = [LIVE / "next.config.js", *sorted((LIVE / "src").rglob("*.ts*"))]
    for path in sources:
        if "__tests__" in path.parts or ".test." in path.name or path.name.endswith(".d.ts"):
            continue
        for name in re.findall(r"process\.env\.([A-Z][A-Z_0-9]+)", path.read_text()):
            assert name in sections["Env vars"], f"{path}: undocumented {name}"
    flags = (LIVE / "src/lib/featureFlags.ts").read_text().split("} as const;", 1)[0]
    for flag in re.findall(r"^  ([A-Z_]+): \{", flags, flags=re.MULTILINE):
        assert f"NEXT_PUBLIC_FEATURE_{flag}" in sections["Env vars"]
