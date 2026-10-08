from __future__ import annotations

import json
import subprocess
from pathlib import Path

import scripts.github_cli_health as gh_health


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "automation_pr_preflight.sh"


def _run(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-b", "main"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=repo)
    _run(["git", "commit", "-m", "init"], cwd=repo)
    _run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo)
    return repo


def test_automation_pr_preflight_accepts_docs_diff(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/docs-update"], cwd=repo)
    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("note\n", encoding="utf-8")
    _run(["git", "add", "docs/note.md"], cwd=repo)
    _run(["git", "commit", "-m", "docs: add note"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 0
    assert "preflight: ok" in proc.stdout


def test_automation_pr_preflight_json_accepts_docs_diff(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/docs-json"], cwd=repo)
    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("note\n", encoding="utf-8")
    _run(["git", "add", "docs/note.md"], cwd=repo)
    _run(["git", "commit", "-m", "docs: add json note"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "--json", "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["base_ref"] == "origin/main"
    assert payload["head_ref"] == "HEAD"
    assert payload["changed_files"] == ["docs/note.md"]
    assert payload["docs_only"] is True
    assert payload["source_without_tests"] is False
    assert payload["forbidden_files"] == []
    assert payload["rescue_publish_files"] == []
    assert payload["suggested_validation_commands"] == []


def test_automation_pr_preflight_rejects_worker_artifacts(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/bad-artifact"], cwd=repo)
    (repo / ".swarm_worker_stdout.log").write_text("worker log\n", encoding="utf-8")
    _run(["git", "add", ".swarm_worker_stdout.log"], cwd=repo)
    _run(["git", "commit", "-m", "bad: commit worker log"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    assert "automation/session artifacts" in proc.stderr


def test_automation_pr_preflight_json_rejects_worker_artifacts(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/bad-artifact-json"], cwd=repo)
    (repo / ".swarm_worker_stdout.log").write_text("worker log\n", encoding="utf-8")
    _run(["git", "add", ".swarm_worker_stdout.log"], cwd=repo)
    _run(["git", "commit", "-m", "bad: commit worker log"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "--json", "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert payload["forbidden_files"] == [".swarm_worker_stdout.log"]
    assert payload["error"] == "automation/session artifacts must not be committed"


def test_automation_pr_preflight_json_suggests_validation_for_source_without_tests(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/source-json"], cwd=repo)
    source = repo / "scripts" / "tool.py"
    source.parent.mkdir()
    source.write_text("print('hi')\n", encoding="utf-8")
    _run(["git", "add", "scripts/tool.py"], cwd=repo)
    _run(["git", "commit", "-m", "feat: add tool"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "--json", "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["docs_only"] is False
    assert payload["source_without_tests"] is True
    assert payload["suggested_validation_commands"] == [
        "python3 scripts/nomic_ci_test_selector.py --changed-files scripts/tool.py --dry-run",
        "python3 -m ruff check scripts/tool.py",
    ]


def test_automation_pr_preflight_json_suggests_publisher_startup_smoke(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/publisher-startup-json"], cwd=repo)
    source = repo / "scripts" / "publish_codex_automation_branches.py"
    source.parent.mkdir()
    source.write_text("print('publisher')\n", encoding="utf-8")
    _run(["git", "add", "scripts/publish_codex_automation_branches.py"], cwd=repo)
    _run(["git", "commit", "-m", "fix: update publisher startup"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "--json", "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    startup_command = next(
        command
        for command in payload["suggested_validation_commands"]
        if command.startswith('python3 -c "import importlib;')
    )
    assert "scripts.publish_codex_automation_branches" in startup_command
    assert "scripts.github_cli_health" in startup_command
    assert "'scripts.github_cli_health'" in startup_command


def test_automation_pr_preflight_json_suggests_benchmark_truth_status_smoke(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/benchmark-truth-json"], cwd=repo)
    source = repo / "scripts" / "render_benchmark_truth_status.py"
    source.parent.mkdir()
    source.write_text("print('benchmark truth')\n", encoding="utf-8")
    _run(["git", "add", "scripts/render_benchmark_truth_status.py"], cwd=repo)
    _run(["git", "commit", "-m", "fix: update benchmark truth status"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "--json", "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert (
        "python3 -m py_compile scripts/render_benchmark_truth_status.py"
        in payload["suggested_validation_commands"]
    )
    assert (
        "python3 -m pytest tests/scripts/test_render_benchmark_truth_status.py -q"
        in payload["suggested_validation_commands"]
    )


def test_automation_pr_preflight_json_suggests_agent_bridge_smoke(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/agent-bridge-json"], cwd=repo)
    source = repo / "scripts" / "agent_bridge.py"
    source.parent.mkdir()
    source.write_text("print('bridge')\n", encoding="utf-8")
    _run(["git", "add", "scripts/agent_bridge.py"], cwd=repo)
    _run(["git", "commit", "-m", "fix: update agent bridge"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "--json", "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["docs_only"] is False
    assert payload["source_without_tests"] is True
    assert payload["suggested_validation_commands"] == [
        "python3 scripts/nomic_ci_test_selector.py --changed-files scripts/agent_bridge.py --dry-run",
        "python3 -m ruff check scripts/agent_bridge.py",
        "python3 scripts/agent_bridge.py operator-snapshot --json --summary-only",
    ]


def test_automation_pr_preflight_rejects_synthetic_preflight_commit_subject(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/preflight-preflight-repro"], cwd=repo)
    workflow_dir = repo / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "benchmark-truth-publication.yml").write_text(
        "2026-04-14T19:38:09-0500\n",
        encoding="utf-8",
    )
    _run(["git", "add", ".github/workflows/benchmark-truth-publication.yml"], cwd=repo)
    _run(["git", "commit", "-m", "chore: preflight worker check"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    assert "synthetic preflight validation commits" in proc.stderr


def test_automation_pr_preflight_rejects_scratch_preflight_diff(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/preflight-scratch-repro"], cwd=repo)
    scratch_dir = repo / "scratch"
    scratch_dir.mkdir()
    (scratch_dir / "preflight_worker_check.txt").write_text(
        "2026-04-15T03:10:00Z\n", encoding="utf-8"
    )
    _run(["git", "add", "scratch/preflight_worker_check.txt"], cwd=repo)
    _run(["git", "commit", "-m", "docs: publish scratch preflight artifact"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    assert "synthetic preflight validation scratch diffs" in proc.stderr


def test_automation_pr_preflight_rejects_aragora_coordination_artifacts(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/bad-aragora-artifact"], cwd=repo)
    artifact = repo / ".aragora" / "automation-outbox" / "open-pr-demo.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"idempotency_key": "demo"}\n', encoding="utf-8")
    _run(["git", "add", ".aragora/automation-outbox/open-pr-demo.json"], cwd=repo)
    _run(["git", "commit", "-m", "bad: commit outbox artifact"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    assert "automation/session artifacts" in proc.stderr
    assert ".aragora/automation-outbox/open-pr-demo.json" in proc.stderr


def test_automation_pr_preflight_rejects_rescue_publish_artifacts(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/bad-rescue-publish"], cwd=repo)
    artifact = (
        repo / "published" / "rescue_productization" / "rescue-productization-20260516T120000Z.json"
    )
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    _run(
        [
            "git",
            "add",
            "published/rescue_productization/rescue-productization-20260516T120000Z.json",
        ],
        cwd=repo,
    )
    _run(["git", "commit", "-m", "bad: commit rescue publish artifact"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    assert "rescue productization publish artifacts" in proc.stderr
    assert (
        "published/rescue_productization/rescue-productization-20260516T120000Z.json" in proc.stderr
    )


def test_automation_pr_preflight_allows_canonical_rescue_status_artifacts(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/tw03-proof-surface"], cwd=repo)
    generated_dir = repo / "docs" / "status" / "generated" / "rescue_productization"
    latest = generated_dir / "latest.json"
    timestamped = generated_dir / "rescue-productization-20260721T184000Z.json"
    generated_dir.mkdir(parents=True)
    latest.write_text('{"generated_at": "2026-07-21T18:40:00Z"}\n', encoding="utf-8")
    timestamped.write_text(
        '{"generated_at": "2026-07-21T18:40:00Z"}\n',
        encoding="utf-8",
    )
    _run(
        [
            "git",
            "add",
            "docs/status/generated/rescue_productization/latest.json",
            "docs/status/generated/rescue_productization/rescue-productization-20260721T184000Z.json",
        ],
        cwd=repo,
    )
    _run(["git", "commit", "-m", "docs: refresh tw03 proof surface"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "--json", "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["rescue_publish_files"] == []


def test_automation_pr_preflight_rejects_reports_rescue_publish_artifacts(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/bad-reports-rescue-publish"], cwd=repo)
    publish_dir = repo / "reports" / "rescue_productization"
    publish_dir.mkdir(parents=True)
    latest = publish_dir / "latest.json"
    timestamped = publish_dir / "rescue-productization-20260516T162243Z.json"
    latest.write_text('{"generated_at": "2026-05-16T16:22:43Z"}\n', encoding="utf-8")
    timestamped.write_text(
        '{"generated_at": "2026-05-16T16:22:43Z"}\n',
        encoding="utf-8",
    )
    _run(
        [
            "git",
            "add",
            "reports/rescue_productization/latest.json",
            "reports/rescue_productization/rescue-productization-20260516T162243Z.json",
        ],
        cwd=repo,
    )
    _run(["git", "commit", "-m", "bad: commit rescue publish artifacts"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    assert "rescue productization publish artifacts" in proc.stderr
    assert "reports/rescue_productization/latest.json" in proc.stderr
    assert (
        "reports/rescue_productization/rescue-productization-20260516T162243Z.json" in proc.stderr
    )


def test_automation_pr_preflight_rejects_rescue_publish_latest_pointer(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/bad-rescue-latest"], cwd=repo)
    artifact = repo / "published" / "rescue-productization" / "latest.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    _run(["git", "add", "published/rescue-productization/latest.json"], cwd=repo)
    _run(["git", "commit", "-m", "bad: commit rescue latest artifact"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    assert "rescue productization publish artifacts" in proc.stderr
    assert "published/rescue-productization/latest.json" in proc.stderr


def test_automation_pr_preflight_rejects_nested_rescue_publish_pointers(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/bad-nested-rescue-publish"], cwd=repo)
    timestamped = repo / "published" / "rescue-productization-20260516T162243Z.json"
    latest = repo / "published" / "rescue_productization" / "snapshots" / "latest.json"
    latest.parent.mkdir(parents=True)
    timestamped.write_text("{}\n", encoding="utf-8")
    latest.write_text("{}\n", encoding="utf-8")
    _run(
        [
            "git",
            "add",
            "published/rescue-productization-20260516T162243Z.json",
            "published/rescue_productization/snapshots/latest.json",
        ],
        cwd=repo,
    )
    _run(["git", "commit", "-m", "bad: commit nested rescue publish artifacts"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    assert "rescue productization publish artifacts" in proc.stderr
    assert "published/rescue-productization-20260516T162243Z.json" in proc.stderr
    assert "published/rescue_productization/snapshots/latest.json" in proc.stderr


def test_automation_pr_preflight_rejects_noncanonical_rescue_status_artifacts(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/bad-tw03-proof-surface"], cwd=repo)
    paths = [
        "docs/status/generated/rescue_productization/rescue-productization-latest.json",
        "docs/status/generated/rescue_productization/snapshots/latest.json",
        "rescue-productization-20260721T184000Z.json",
        "scratch/rescue_productization/latest.json",
    ]
    for path in paths:
        artifact = repo / path
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}\n", encoding="utf-8")
    _run(["git", "add", *paths], cwd=repo)
    _run(["git", "commit", "-m", "bad: commit noncanonical rescue artifacts"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "--json", "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert payload["error"] == "rescue productization publish artifacts must not be committed"
    assert payload["rescue_publish_files"] == paths


def test_automation_pr_preflight_accepts_unrelated_latest_json(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/unrelated-latest-json"], cwd=repo)
    artifact = repo / "docs" / "fixtures" / "latest.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{}\n", encoding="utf-8")
    _run(["git", "add", "docs/fixtures/latest.json"], cwd=repo)
    _run(["git", "commit", "-m", "docs: add fixture latest json"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 0
    assert "preflight: ok" in proc.stdout


def test_automation_pr_preflight_json_rejects_stale_next_steps_proof_state(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/stale-next-steps"], cwd=repo)
    next_steps = repo / "docs" / "status" / "NEXT_STEPS_CANONICAL.md"
    next_steps.parent.mkdir(parents=True)
    next_steps.write_text(
        "# Next Steps\n\n"
        "Current May 28 proof-loop state: full-corpus truth remains 38.5%.\n"
        "truth_success_rate_verified over five verified entries.\n",
        encoding="utf-8",
    )
    _run(["git", "add", "docs/status/NEXT_STEPS_CANONICAL.md"], cwd=repo)
    _run(["git", "commit", "-m", "docs: refresh next steps"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "--json", "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 1
    payload = json.loads(proc.stdout)
    assert payload["status"] == "failed"
    assert payload["changed_files"] == ["docs/status/NEXT_STEPS_CANONICAL.md"]
    assert (
        payload["error"]
        == "docs/status/NEXT_STEPS_CANONICAL.md still contains stale proof-loop percentages"
    )


def test_automation_pr_preflight_accepts_next_steps_with_current_proof_refs(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _run(["git", "switch", "-c", "codex/current-next-steps"], cwd=repo)
    next_steps = repo / "docs" / "status" / "NEXT_STEPS_CANONICAL.md"
    next_steps.parent.mkdir(parents=True)
    next_steps.write_text(
        "# Next Steps\n\n"
        "Current proof-loop state: use live proof surfaces instead of copied rates.\n"
        "- B0_BENCHMARK_TRUTH_STATUS\n"
        "- TW03_RESCUE_PRODUCTIZATION_STATUS\n",
        encoding="utf-8",
    )
    _run(["git", "add", "docs/status/NEXT_STEPS_CANONICAL.md"], cwd=repo)
    _run(["git", "commit", "-m", "docs: refresh next steps"], cwd=repo)

    proc = _run(["bash", str(SCRIPT), "--json", "origin/main", "HEAD"], cwd=repo)

    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["status"] == "ok"
    assert payload["docs_only"] is True
    assert payload["changed_files"] == ["docs/status/NEXT_STEPS_CANONICAL.md"]


def test_github_cli_health_classifies_raw_dial_tcp_errors_as_connectivity() -> None:
    assert gh_health.is_github_connectivity_error(
        'Get "https://api.github.com/rate_limit": dial tcp 140.82.112.5:443: i/o timeout'
    )
