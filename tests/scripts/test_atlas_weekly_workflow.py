"""Exercise the actual Atlas workflow shell without contacting GitHub."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/metrics-drift.yml"


def atlas_job() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["atlas"]


def publish_job() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["publish-atlas"]


def step(name: str, *, publish: bool = False) -> dict[str, Any]:
    job = publish_job() if publish else atlas_job()
    return next(s for s in job["steps"] if s["name"] == name)


def run_step(
    name: str, env: dict[str, str], *, publish: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            "--noprofile",
            "--norc",
            "-e",
            "-o",
            "pipefail",
            "-c",
            step(name, publish=publish)["run"],
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def executable(path: Path, body: str) -> None:
    path.write_text(f"#!{sys.executable}\n{body}")
    path.chmod(0o755)


@pytest.fixture
def shell_env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    out = tmp_path / "atlas"
    out.mkdir()
    manifest = json.loads((ROOT / "docs/atlas/manifest.json").read_text())
    (out / "manifest.json").write_text(json.dumps(manifest))
    (out / "atlas-v1.jsonl").write_bytes((ROOT / "docs/atlas/atlas-v1.sample.jsonl").read_bytes())
    (out / "summary.md").write_bytes((ROOT / "docs/atlas/summary.md").read_bytes())
    executable(
        bin_dir / "date",
        """import os, pathlib
p = pathlib.Path(os.environ["DATE_CALLS"])
p.write_text(p.read_text() + "date\\n" if p.exists() else "date\\n")
print("2026-09-10" if len(p.read_text().splitlines()) == 1 else "2026-09-11")
""",
    )
    executable(
        bin_dir / "gh",
        """import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps(args) + "\\n")
mode = os.environ.get("MODE", "changed")
operation = args[1]
if operation == "view":
    if mode == "exists":
        sys.exit(0)
    print("HTTP 403" if mode == "view_error" else "release not found", file=sys.stderr)
    sys.exit(1)
if operation == "list":
    if mode == "list_error":
        sys.exit(1)
    print("" if mode == "first" else "atlas-v1")
elif operation == "download":
    if mode == "download_error":
        sys.exit(1)
    dest = pathlib.Path(args[args.index("--dir") + 1])
    manifest = json.loads((pathlib.Path(os.environ["ATLAS_OUT"]) / "manifest.json").read_text())
    if mode != "unchanged":
        manifest["dataset"]["sha256"] = "0" * 64
    (dest / "manifest.json").write_text("invalid" if mode == "invalid" else json.dumps(manifest))
elif operation == "create":
    assert args[2] == "atlas-2026-09-10"
    for name in ("atlas-v1.jsonl", "manifest.json", "summary.md"):
        assert str(pathlib.Path(os.environ["ATLAS_OUT"]) / name) in args
    assert args[args.index("--target") + 1] == "main"
else:
    raise AssertionError(args)
""",
    )
    return {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "RUNNER_TEMP": str(tmp_path),
        "ATLAS_OUT": str(out),
        "ATLAS_CACHE": str(tmp_path / "cache"),
        "GH_REPO": "synaptent/aragora",
        "CALLS": str(tmp_path / "calls.jsonl"),
        "DATE_CALLS": str(tmp_path / "date-calls"),
        "GITHUB_OUTPUT": str(tmp_path / "outputs"),
        "GITHUB_ENV": str(tmp_path / "env"),
    }


def test_job_is_weekly_or_manual_with_branch_artifacts_and_main_only_releases() -> None:
    job = atlas_job()
    assert job["name"] == "Disagreement Atlas"
    assert job["if"] == (
        "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'"
    )
    assert job["permissions"] == {
        "contents": "read",
        "issues": "read",
        "pull-requests": "read",
        "statuses": "read",
    }
    assert job["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert job["timeout-minutes"] >= 90
    assert not job.get("continue-on-error", False)
    assert all("gh release" not in s.get("run", "") for s in job["steps"])
    upload = step("Upload Atlas artifact")
    assert "if" not in upload
    assert upload["id"] == "atlas_upload"
    assert job["outputs"] == {"artifact-id": "${{ steps.atlas_upload.outputs.artifact-id }}"}
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["name"] == "${{ steps.atlas_date.outputs.tag }}"
    assert upload["with"]["if-no-files-found"] == "error"
    assert set(Path(p).name for p in upload["with"]["path"].splitlines()) == {
        "atlas-v1.jsonl",
        "manifest.json",
        "summary.md",
    }
    block = WORKFLOW.read_text().split("\n  atlas:\n")[1]
    assert not re.search(r"git (push|commit)|gh pr (create|merge)|docs/atlas/cache", block)


def test_publisher_is_main_only_and_consumes_successful_same_run_artifact() -> None:
    job = publish_job()
    assert job["needs"] == "atlas"
    assert job["if"] == (
        "github.ref == 'refs/heads/main' && needs.atlas.result == 'success' && "
        "(github.event_name == 'schedule' || github.event_name == 'workflow_dispatch')"
    )
    assert job["permissions"] == {"contents": "write"}
    assert job["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert not job.get("continue-on-error", False)
    assert 0 < job["timeout-minutes"] <= 15
    assert all(not s.get("continue-on-error", False) for s in job["steps"])
    assert all("if" not in s for s in job["steps"])
    assert not any(s.get("uses", "").startswith("actions/checkout@") for s in job["steps"])
    assert not any("scripts/" in s.get("run", "") for s in job["steps"])
    validate = step("Require Atlas artifact", publish=True)
    assert validate["env"]["ATLAS_ARTIFACT_ID"] == "${{ needs.atlas.outputs.artifact-id }}"
    download = step("Download this run's Atlas artifact", publish=True)
    assert download["uses"] == "actions/download-artifact@v4"
    # No token, repository or run override: the action uses this run's artifact service.
    assert download["with"] == {
        "artifact-ids": "${{ needs.atlas.outputs.artifact-id }}",
        "path": "${{ env.ATLAS_OUT }}",
        "merge-multiple": True,
    }
    assert [s["name"] for s in job["steps"]] == [
        "Require Atlas artifact",
        "Download this run's Atlas artifact",
        "Publish dated Atlas release",
    ]


@pytest.mark.parametrize("artifact_id", ["", "0", "invalid", "123,456", "-1"])
def test_publisher_rejects_missing_or_invalid_artifact_id(
    shell_env: dict[str, str], artifact_id: str
) -> None:
    result = run_step(
        "Require Atlas artifact", {**shell_env, "ATLAS_ARTIFACT_ID": artifact_id}, publish=True
    )
    assert result.returncode != 0
    assert "missing or invalid" in result.stderr
    assert not Path(shell_env["GITHUB_ENV"]).exists()
    assert not Path(shell_env["CALLS"]).exists()


def test_publisher_accepts_exact_artifact_id(shell_env: dict[str, str]) -> None:
    result = run_step(
        "Require Atlas artifact", {**shell_env, "ATLAS_ARTIFACT_ID": "123456"}, publish=True
    )
    assert result.returncode == 0, result.stderr
    assert Path(shell_env["GITHUB_ENV"]).read_text() == (
        f"ATLAS_OUT={shell_env['RUNNER_TEMP']}/atlas-output\n"
    )


def test_cache_advances_per_run_and_index_refresh_discovers_new_prs() -> None:
    restore = step("Restore Atlas fetch cache")
    save = step("Save Atlas fetch cache")
    assert restore["uses"].startswith("actions/cache/restore@")
    assert save["uses"].startswith("actions/cache/save@")
    assert "${{ github.run_id }}" in restore["with"]["key"]
    assert "${{ github.run_attempt }}" in restore["with"]["key"]
    assert restore["with"]["restore-keys"]
    assert save["with"]["path"] == restore["with"]["path"]
    assert save["with"]["key"] == "${{ steps.atlas_cache.outputs.cache-primary-key }}"
    assert save["if"] == "always() && steps.atlas_cache.outcome == 'success'"
    collect_step = step("Collect Atlas incrementally")
    assert collect_step["id"] == "atlas_collect"
    assert collect_step["timeout-minutes"] < atlas_job()["timeout-minutes"]
    collect = step("Collect Atlas incrementally")["run"]
    assert "--refresh-index" in collect
    assert "--refresh " not in collect
    assert "continue-on-error" not in step("Collect Atlas incrementally")
    assert "|| true" not in collect


def test_date_output_is_exact_dated_artifact_name(shell_env: dict[str, str]) -> None:
    result = run_step("Name Atlas artifact", shell_env)
    assert result.returncode == 0, result.stderr
    assert Path(shell_env["GITHUB_OUTPUT"]).read_text() == "tag=atlas-2026-09-10\n"


@pytest.mark.parametrize("mode", ["exists", "unchanged", "changed", "first"])
def test_release_skips_or_publishes_three_assets(shell_env: dict[str, str], mode: str) -> None:
    result = run_step("Publish dated Atlas release", {**shell_env, "MODE": mode}, publish=True)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in Path(shell_env["CALLS"]).read_text().splitlines()]
    created = [args for args in calls if args[1] == "create"]
    assert bool(created) == (mode in {"changed", "first"})
    assert Path(shell_env["DATE_CALLS"]).read_text() == "date\n"
    if mode == "exists":
        assert len(calls) == 1
        assert "already exists; no release" in result.stdout
    if mode == "unchanged":
        sha = json.loads((ROOT / "docs/atlas/manifest.json").read_text())["dataset"]["sha256"]
        assert f"atlas: dataset unchanged ({sha}); no release" in result.stdout


@pytest.mark.parametrize("mode", ["view_error", "list_error", "download_error", "invalid"])
def test_release_fails_closed_on_read_errors(shell_env: dict[str, str], mode: str) -> None:
    result = run_step("Publish dated Atlas release", {**shell_env, "MODE": mode}, publish=True)
    assert result.returncode != 0
    calls = [json.loads(line) for line in Path(shell_env["CALLS"]).read_text().splitlines()]
    assert all(args[1] != "create" for args in calls)


def test_collect_failure_stops_before_build_or_publish(shell_env: dict[str, str]) -> None:
    bin_dir = Path(shell_env["PATH"].split(os.pathsep)[0])
    executable(bin_dir / "python3", "import sys\nsys.exit(1)\n")
    result = run_step("Collect Atlas incrementally", shell_env)
    assert result.returncode == 1
    steps = atlas_job()["steps"]
    names = [s["name"] for s in steps]
    assert names.index("Collect Atlas incrementally") < names.index("Build Atlas")
    for name in ("Build Atlas", "Upload Atlas artifact"):
        assert "always()" not in step(name).get("if", "")
        assert not step(name).get("continue-on-error", False)
    assert publish_job()["needs"] == "atlas"
    assert "needs.atlas.result == 'success'" in publish_job()["if"]
    assert "always()" not in publish_job()["if"]
