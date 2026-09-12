"""Regression contract for the future required, single-workflow fast gate."""

from __future__ import annotations

import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
FAST_SHARDS = {
    "agents",
    "reasoning",
    "workflow-client",
    "knowledge",
    "storage",
    "infra",
    "server-handlers-am",
    "server-handlers-nz",
    "server-rest",
    "handlers-features",
    "handlers-amk-no-features",
    "handlers-lz",
}
DEBATE_SHARDS = {"debate-phases", "debate-1", "debate-2", "debate-3"}
CURRENT_CONTEXTS = [
    "lint",
    "typecheck",
    "sdk-parity",
    "Generate & Validate",
    "TypeScript SDK Type Check",
    "aragora-merge-quorum",
]
SCOPE_CLAUSE = "needs.test-shard-scope.outputs.in_scope == 'true'"
# PR trigger and allowlist provenance: test.yml at mission-base 23909906e8.
MISSION_BASE_PR_TRIGGER = {
    "types": ["opened", "synchronize", "reopened", "ready_for_review"],
    "branches": ["main"],
}
SCOPE_ALLOWLIST = [
    "aragora/**",
    "aragora-debate/**",
    "tests/**",
    "pyproject.toml",
    "requirements.txt",
    "scripts/capability_gap_report.py",
    "scripts/generate_capability_matrix.py",
    "scripts/check_capability_matrix_sync.py",
    "scripts/check_legacy_entrypoints.py",
    "scripts/check_legacy_collab_flags.py",
    "scripts/capability_matrix_delta.py",
    "scripts/generate_cli_reference.py",
    "aragora/capabilities.yaml",
    "aragora/capability_surfaces.yaml",
    "docs/CAPABILITY_MATRIX.md",
    "docs/reference/CLI_REFERENCE.md",
    "docs-site/docs/contributing/capability-matrix.md",
    "docs-site/docs/api/cli.md",
    ".github/workflows/test.yml",
]
EXPECTED_ROOT_IF = {
    "scope": SCOPE_CLAUSE,
    "version-check": "(github.event_name != 'pull_request' || !github.event.pull_request.draft) && "
    + SCOPE_CLAUSE,
    "skip-audit": "(github.event_name != 'pull_request' || !github.event.pull_request.draft) && "
    + SCOPE_CLAUSE,
    "status-reconciliation": "(github.event_name != 'pull_request' || !github.event.pull_request.draft) && "
    + SCOPE_CLAUSE,
    "security": "(github.event_name != 'pull_request' || !github.event.pull_request.draft) && "
    + SCOPE_CLAUSE,
    "typecheck": "(github.event_name != 'pull_request' || !github.event.pull_request.draft) && "
    + SCOPE_CLAUSE,
    "migration-test": "(github.event_name != 'pull_request' || !github.event.pull_request.draft) && "
    + SCOPE_CLAUSE,
}
SHARD_SCOPE_NAMES = {
    "core",
    "agents",
    "reasoning",
    "workflow_client",
    "server_handlers",
    "server_rest",
    "handlers",
    "knowledge",
    "storage",
    "infra",
}


def _workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text())


def _triggers(workflow: dict) -> dict:
    # PyYAML's YAML 1.1 loader treats the unquoted GitHub Actions key as True.
    return workflow.get("on", workflow.get(True))


def _scope_filters(workflow: dict) -> dict:
    steps = workflow["jobs"]["test-shard-scope"]["steps"]
    step = next(s for s in steps if s.get("uses", "").startswith("dorny/paths-filter@"))
    return yaml.safe_load(step["with"]["filters"])


def test_fast_gate_dependencies_timeout_and_shared_shards() -> None:
    jobs = _workflow("test.yml")["jobs"]
    worker = jobs["test-fast-gate-run"]
    assert worker["needs"] == ["test-shard-scope"]
    assert worker["timeout-minutes"] == 10
    assert worker["if"] == jobs["test-fast"]["if"]
    assert "!github.event.pull_request.draft" in worker["if"]
    assert SCOPE_CLAUSE in worker["if"]
    assert worker["strategy"]["fail-fast"] is False
    assert worker["strategy"]["matrix"] == jobs["test-fast"]["strategy"]["matrix"]
    assert worker["steps"] == jobs["test-fast"]["steps"]
    assert {c["name"] for c in worker["strategy"]["matrix"]["category"]} == FAST_SHARDS
    assert "continue-on-error" not in worker
    assert all(not step.get("continue-on-error") for step in worker["steps"])
    gate = jobs["test-fast-gate"]
    assert set(gate["needs"]) == {"test-shard-scope", "test-fast-gate-run"}
    assert gate["if"] == "always()"
    assert gate["timeout-minutes"] == 2
    assert not gate.get("continue-on-error")


@pytest.mark.parametrize(
    "classifier,in_scope,worker,draft,accepted",
    [
        ("success", "true", "success", "false", True),
        ("success", "true", "success", "", True),
        ("success", "false", "skipped", "false", True),
        ("success", "false", "skipped", "true", True),
        ("success", "true", "skipped", "true", True),
        ("success", "true", "skipped", "false", False),
        ("success", "true", "failure", "false", False),
        ("success", "true", "cancelled", "false", False),
        ("success", "false", "success", "false", False),
        ("failure", "true", "success", "false", False),
        ("cancelled", "true", "skipped", "false", False),
        ("skipped", "true", "skipped", "true", False),
        ("success", "", "skipped", "false", False),
        ("success", "bogus", "skipped", "false", False),
        ("success", "true", "", "false", False),
    ],
)
def test_umbrella_fails_closed_offline(
    classifier: str, in_scope: str, worker: str, draft: str, accepted: bool
) -> None:
    gate = _workflow("test.yml")["jobs"]["test-fast-gate"]
    assert len(gate["steps"]) == 1
    step = gate["steps"][0]
    assert step["env"] == {
        "CLASSIFIER_RESULT": "${{ needs.test-shard-scope.result }}",
        "IN_SCOPE": "${{ needs.test-shard-scope.outputs.in_scope }}",
        "WORKER_RESULT": "${{ needs.test-fast-gate-run.result }}",
        "IS_DRAFT": "${{ github.event.pull_request.draft }}",
    }
    assert "${{" not in step["run"]
    assert not step.get("continue-on-error")
    outcome = subprocess.run(
        ["bash", "-c", step["run"]],
        env={
            **os.environ,
            "CLASSIFIER_RESULT": classifier,
            "IN_SCOPE": in_scope,
            "WORKER_RESULT": worker,
            "IS_DRAFT": draft,
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert (outcome.returncode == 0) == accepted, outcome.stdout + outcome.stderr
    if not accepted:
        assert "::error::" in outcome.stdout


def test_baseline_decoupling_and_all_dependencies_resolve() -> None:
    jobs = _workflow("test.yml")["jobs"]
    assert "baseline-determinism" in jobs
    assert jobs["test-fast"]["needs"] == ["test-shard-scope"]
    for job in jobs.values():
        needs = job.get("needs", [])
        assert set([needs] if isinstance(needs, str) else needs) <= jobs.keys()


def test_debate_shards_move_to_main_and_nightly_only() -> None:
    workflow = _workflow("test-debate-shards.yml")
    assert workflow["name"] == "Tests (debate shards)"
    triggers = _triggers(workflow)
    assert set(triggers) == {"push", "schedule", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]
    assert triggers["schedule"] == [{"cron": "0 4 * * *"}]
    jobs = workflow["jobs"]
    assert len(jobs) == 1
    job = next(iter(jobs.values()))
    categories = job["strategy"]["matrix"]["category"]
    assert {c["name"] for c in categories} == DEBATE_SHARDS
    assert {c["resolver"] for c in categories} == DEBATE_SHARDS
    scripts = "\n".join(s.get("run", "") for s in job["steps"])
    assert "scripts/ci_resolve_test_shard.py" in scripts
    assert "--check" in scripts
    assert "pytest" in scripts
    assert not job.get("continue-on-error")
    for test_job in _workflow("test.yml")["jobs"].values():
        for categories in test_job.get("strategy", {}).get("matrix", {}).values():
            if isinstance(categories, list):
                assert not any(
                    isinstance(c, dict) and c.get("name") in DEBATE_SHARDS for c in categories
                )


def test_single_workflow_scope_gate() -> None:
    workflow = _workflow("test.yml")
    primary_pr = _triggers(workflow)["pull_request"]
    assert primary_pr == MISSION_BASE_PR_TRIGGER
    assert "paths" not in primary_pr and "paths-ignore" not in primary_pr
    filters = _scope_filters(workflow)
    assert len(filters["in_scope"]) == 19
    assert set(filters["in_scope"]) == set(SCOPE_ALLOWLIST)
    assert set(filters) - {"in_scope"} == SHARD_SCOPE_NAMES
    assert "core" in filters
    jobs = workflow["jobs"]
    for job_id in ("test-fast", "test-fast-gate-run"):
        assert all(
            category["scope"] in SHARD_SCOPE_NAMES
            for category in jobs[job_id]["strategy"]["matrix"]["category"]
        )
    classifier = jobs["test-shard-scope"]
    assert "github.event.pull_request.draft" not in classifier.get("if", "")
    assert classifier["timeout-minutes"] == 3
    assert classifier["outputs"] == {
        "scopes_changed": "${{ steps.filter.outputs.changes }}",
        "in_scope": "${{ steps.scope.outputs.in_scope }}",
    }
    assert {k for k, v in jobs.items() if not v.get("needs")} == {
        "test-shard-scope",
        "test-pollution-randomized",
    }
    for job_id, expected_if in EXPECTED_ROOT_IF.items():
        assert jobs[job_id]["needs"] == ["test-shard-scope"]
        assert jobs[job_id]["if"] == expected_if
    for job_id in (
        "test-fast",
        "test-fast-gate-run",
        "test-summary",
        "quality-gates",
        "test-analytics",
    ):
        assert "test-shard-scope" in jobs[job_id]["needs"]
        assert SCOPE_CLAUSE in jobs[job_id]["if"]
        assert "!github.event.pull_request.draft" in jobs[job_id]["if"]
    pollution = jobs["test-pollution-randomized"]
    assert "needs" not in pollution
    assert pollution["if"] == "github.event_name != 'pull_request'"
    assert SCOPE_CLAUSE not in pollution["if"]
    assert not (WORKFLOWS / "test-fast-gate-companion.yml").exists()
    producers = [
        (path.name, job_id)
        for path in sorted(WORKFLOWS.iterdir())
        if path.suffix in {".yml", ".yaml"}
        for job_id, job in _workflow(path.name).get("jobs", {}).items()
        if job.get("name", job_id) == "test-fast-gate"
    ]
    assert producers == [("test.yml", "test-fast-gate")]


@pytest.mark.parametrize(
    "files,in_scope",
    [
        (["README.md"], False),
        (["docs/CI_LANES.md", "docs-site/README.md"], False),
        (["aragora/debate/orchestrator.py"], True),
        (["aragora/debate/orchestrator.py", "README.md"], True),
    ],
)
def test_out_of_scope_examples(files: list[str], in_scope: bool) -> None:
    assert any(fnmatch.fnmatch(f, p) for f in files for p in SCOPE_ALLOWLIST) == in_scope


@pytest.mark.parametrize(
    "event,filtered,expected",
    [
        ("pull_request", "true", "true"),
        ("pull_request", "false", "false"),
        ("pull_request", "", "false"),
        ("pull_request", "bogus", "false"),
        ("schedule", "", "true"),
        ("workflow_dispatch", "false", "true"),
    ],
)
def test_classifier_output_offline(
    event: str, filtered: str, expected: str, tmp_path: Path
) -> None:
    classifier = _workflow("test.yml")["jobs"]["test-shard-scope"]
    step = next(s for s in classifier["steps"] if s.get("id") == "scope")
    assert step["env"] == {
        "EVENT_NAME": "${{ github.event_name }}",
        "FILTER_IN_SCOPE": "${{ steps.filter.outputs.in_scope }}",
    }
    assert "${{" not in step["run"]
    output = tmp_path / "github-output"
    outcome = subprocess.run(
        ["bash", "-c", step["run"]],
        env={
            **os.environ,
            "EVENT_NAME": event,
            "FILTER_IN_SCOPE": filtered,
            "GITHUB_OUTPUT": str(output),
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    assert output.read_text() == f"in_scope={expected}\n"


def test_existing_triggers_and_concurrency_are_preserved() -> None:
    workflow = _workflow("test.yml")
    triggers = _triggers(workflow)
    assert set(triggers) == {"pull_request", "schedule", "workflow_dispatch"}
    assert triggers["workflow_dispatch"] is None
    assert triggers["schedule"] == [{"cron": "0 4 * * *"}]
    assert "env" not in workflow
    assert workflow["concurrency"] == {
        "group": (
            "tests-${{ github.event.pull_request.number || github.ref }}"
            "${{ startsWith(github.ref, 'refs/heads/dev/') && format('-{0}', github.sha) || '' }}"
        ),
        "cancel-in-progress": (
            "${{ github.event_name == 'pull_request' && github.event.action == 'synchronize' }}"
        ),
    }


def test_required_manifest_and_auto_revert_references_remain_valid() -> None:
    manifest = json.loads((ROOT / "scripts/ci/required_workflow_manifest.json").read_text())
    assert manifest["version"] == 1
    assert "Tests" in manifest["workflow_names"]
    assert ".github/workflows/test.yml" in manifest["workflow_paths"]
    assert all((ROOT / path).exists() for path in manifest["workflow_paths"])
    assert all(
        "companion" not in entry
        for entry in [*manifest["workflow_names"], *manifest["workflow_paths"]]
    )
    names = {_workflow(p.name)["name"] for p in WORKFLOWS.glob("*.yml")}
    revert = _triggers(_workflow("main-required-checks-auto-revert.yml"))
    assert set(revert["workflow_run"]["workflows"]) <= names
    source = (ROOT / "scripts/auto_revert_main_required_failures.py").read_text()
    assert "def get_required_contexts(" in source
    assert 'self.get(f"/repos/{self.repo}/branches/{branch}/protection")' in source
    assert "return list(DEFAULT_REQUIRED_CONTEXTS)" in source


@pytest.mark.parametrize(
    "workflow_name,job_id",
    [("test.yml", "test-fast-gate-run"), ("test-debate-shards.yml", "test-debate-shards")],
)
def test_added_workers_pin_checkout_and_run_tests(workflow_name: str, job_id: str) -> None:
    steps = _workflow(workflow_name)["jobs"][job_id]["steps"]
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", checkout["uses"])
    assert checkout["with"]["persist-credentials"] is False
    for step in steps:
        if step.get("uses", "").startswith("actions/upload-artifact@"):
            assert re.fullmatch(r"actions/upload-artifact@[0-9a-f]{40}", step["uses"])
    run_tests = next(
        s["run"]
        for s in steps
        if "pytest ${{ steps.shard_paths.outputs.args }}" in s.get("run", "")
    )
    for flag in ("-n 4", "--timeout=120", "--dist loadscope", "not slow", "not integration"):
        assert flag in run_tests


def test_docs_keep_gate_future_and_preserve_exact_patch_payload() -> None:
    docs = (ROOT / "docs/CI_LANES.md").read_text()
    assert "### Fast test gate (FUTURE required check)\n" in docs
    assert (
        "Runner queue time, classification, and the short umbrella job are not bounded by\n"
        "the worker timeout, so the end-to-end target must be measured, not inferred."
    ) in docs
    assert (
        "`.github/workflows/test-debate-shards.yml`, named **Tests (debate shards)**,\n"
        "runs `debate-phases`, `debate-1`, `debate-2`, and `debate-3` on pushes to `main`,\n"
        "nightly at `0 4 * * *`, and manual dispatch, never on PRs. It preserves the shard\n"
        "resolver boundaries and 30-minute caps. The separate compatibility, integration,\n"
        "and randomized-order suites retain their existing coverage. The auto-revert\n"
        "workflow currently listens to `Lint`, `SDK Parity Check`, `OpenAPI Spec`, and\n"
        "`SDK Tests`, not `Tests`, so no workflow-name migration is needed there. Its\n"
        "script continues to read required contexts live from branch protection."
    ) in docs
    assert "FUTURE required check" in docs
    assert "at most 10 minutes" in docs
    assert "in_scope" in docs
    assert (
        "A second producer of the `test-fast-gate` check-run name must never be reintroduced."
    ) in docs
    assert "test-debate-shards.yml" in docs
    assert "M10" in docs and "M11" in docs
    assert (
        "gh api -X PATCH repos/synaptent/aragora/branches/main/protection/"
        "required_status_checks --input /tmp/aragora-readiness/required-checks.json"
    ) in docs
    payload = json.loads(re.search(r"```json\n(.*?)\n```", docs, flags=re.DOTALL).group(1))
    assert payload == {
        "strict": False,
        "contexts": [*CURRENT_CONTEXTS, "test-fast-gate"],
        "checks": [{"context": c, "app_id": 15368} for c in [*CURRENT_CONTEXTS, "test-fast-gate"]],
    }
