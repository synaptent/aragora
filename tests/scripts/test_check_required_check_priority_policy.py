from __future__ import annotations

from pathlib import Path

from scripts.check_required_check_priority_policy import (
    REQUIRED_CONTEXT_TO_WORKFLOW_PATH,
    check_repo,
    find_required_check_priority_violations,
)


def _valid_workflow_text() -> str:
    return """
jobs:
  prioritize-required-checks:
    steps:
      - name: Cancel queued non-required workflow runs for superseded PR heads
        uses: actions/github-script@v7
        with:
          script: |
            const owner = context.repo.owner;
            const repo = context.repo.repo;
            const pr = context.payload.pull_request;
            const headSha = pr.head.sha;
            const alwaysKeepWorkflowPaths = new Set([
              '.github/workflows/aragora-merge-quorum.yml',
              '.github/workflows/aragora-review-gate.yml',
              '.github/workflows/autopilot-worktree-e2e.yml',
              '.github/workflows/build.yml',
              '.github/workflows/contract-drift-governance.yml',
              '.github/workflows/core-suites.yml',
              '.github/workflows/lint.yml',
              '.github/workflows/live-deploy-mode-gate.yml',
              '.github/workflows/sdk-parity.yml',
              '.github/workflows/sdk-generate.yml',
              '.github/workflows/sdk-test.yml',
              '.github/workflows/test.yml',
              '.github/workflows/openapi.yml',
              '.github/workflows/pr-admission-controller.yml',
              '.github/workflows/quality-smoke.yml',
              '.github/workflows/release-readiness.yml',
              '.github/workflows/security-gate.yml',
              '.github/workflows/self-hosted-shadow.yml',
              '.github/workflows/smoke.yml',
              '.github/workflows/smoke-offline.yml',
              '.github/workflows/required-check-priority.yml',
            ]);
            const alwaysKeepWorkflowNames = new Set([
              'Aragora Merge Quorum',
              'Aragora Code Review',
              'Autopilot Worktree E2E',
              'Build Documentation (PR Check)',
              'Contract Drift Governance',
              'Core Suites (Decision Integrity)',
              'Generate SDK Types',
              'Offline Golden Path',
              'Live Deploy Mode Gate',
              'PR Admission Controller',
              'Quality Pipeline Smoke',
              'Required Check Priority',
              'Release Readiness Gate',
              'Security Gate',
              'Lint',
              'Self-Hosted Shadow CI',
              'SDK Parity Check',
              'SDK Tests',
              'Smoke Tests',
              'Tests',
              'OpenAPI Spec',
            ]);
            async function getLiveHeadSha() {
              const { data: livePr } = await github.rest.pulls.get({
                owner,
                repo,
                pull_number: pr.number,
              });
              return String(livePr.head?.sha || '').trim();
            }
            for (let pass = 1; pass <= sweeps; pass++) {
              const liveHeadSha = await getLiveHeadSha();
              if (!liveHeadSha || liveHeadSha !== headSha) break;
              for (const run of runs) {
                if (run.head_sha === liveHeadSha) continue;
                if (run.id === selfRunId) continue;
                const runHeadRepo = String(run.head_repository?.full_name || '').trim();
                const prHeadRepo = String(pr.head?.repo?.full_name || '').trim();
                if (!runHeadRepo || !prHeadRepo || runHeadRepo !== prHeadRepo) continue;
                if (String(run.head_branch || '').trim() !== headBranch) continue;
                const runPrNumbers = (run.pull_requests || []).map((item) => item.number);
                if (runPrNumbers.length > 0 && !runPrNumbers.includes(pr.number)) continue;
                if (run.status !== 'queued') continue;
                const confirmedLiveHeadSha = await getLiveHeadSha();
                if (!confirmedLiveHeadSha || confirmedLiveHeadSha !== headSha) break;
                await github.rest.actions.cancelWorkflowRun({
                  owner,
                  repo,
                  run_id: run.id,
                });
              }
            }
"""


def _write_policy_repo(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo"
    workflow_dir = repo_root / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)

    workflow_paths = {
        line.split("'")[1]
        for line in _valid_workflow_text().splitlines()
        if ".github/workflows/" in line
    }
    for rel in workflow_paths:
        (repo_root / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo_root / rel).write_text(
            f"name: {Path(rel).stem}\njobs:\n  placeholder:\n    runs-on: ubuntu-latest\n",
            encoding="utf-8",
        )

    for context, rel in REQUIRED_CONTEXT_TO_WORKFLOW_PATH.items():
        (repo_root / rel).write_text(
            f"""
name: {Path(rel).stem}
on:
  push:
    branches: [main]
jobs:
  required-context:
    name: {context}
    runs-on: ubuntu-latest
""",
            encoding="utf-8",
        )

    return repo_root


def test_policy_accepts_required_keep_entries() -> None:
    violations = find_required_check_priority_violations(_valid_workflow_text())
    assert violations == []


def test_policy_requires_required_keep_workflow_path() -> None:
    text = _valid_workflow_text().replace(
        ".github/workflows/openapi.yml", ".github/workflows/other.yml"
    )
    violations = find_required_check_priority_violations(text)
    assert violations
    assert any(
        "missing required keep workflow path: .github/workflows/openapi.yml" == v
        for v in violations
    )


def test_policy_requires_context_mapped_workflow_path_in_keep_list() -> None:
    text = _valid_workflow_text().replace(
        ".github/workflows/lint.yml", ".github/workflows/lint-alt.yml"
    )
    violations = find_required_check_priority_violations(text)
    assert violations
    assert any(
        "required context `lint` maps to workflow path not in keep-list: .github/workflows/lint.yml"
        == v
        for v in violations
    )


def test_policy_requires_required_keep_workflow_name() -> None:
    text = _valid_workflow_text().replace("SDK Tests", "SDK Smoke")
    violations = find_required_check_priority_violations(text)
    assert violations
    assert any("missing required keep workflow name: SDK Tests" == v for v in violations)


def test_policy_detects_stale_workflow_paths() -> None:
    text = _valid_workflow_text().replace(
        ".github/workflows/autopilot-worktree-e2e.yml",
        ".github/workflows/does-not-exist.yml",
    )
    repo_root = Path(__file__).resolve().parents[2]
    violations = find_required_check_priority_violations(text, repo_root=repo_root)
    assert violations
    assert any("does not exist" in v for v in violations)


def test_policy_detects_missing_context_marker_in_mapped_workflow(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    wf_dir = repo_root / ".github" / "workflows"
    wf_dir.mkdir(parents=True)

    (wf_dir / "aragora-merge-quorum.yml").write_text(
        "name: Aragora Merge Quorum\njobs:\n  aragora-merge-quorum:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    (wf_dir / "lint.yml").write_text(
        "name: Lint\njobs:\n  lint:\n    runs-on: ubuntu-latest\n", encoding="utf-8"
    )
    (wf_dir / "aragora-review-gate.yml").write_text(
        "name: Aragora Code Review\njobs:\n  aragora-review:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    (wf_dir / "autopilot-worktree-e2e.yml").write_text(
        "name: Autopilot Worktree E2E\njobs:\n  scope:\n    name: Autopilot Scope\n",
        encoding="utf-8",
    )
    (wf_dir / "build.yml").write_text(
        "name: Build Documentation (PR Check)\njobs:\n  build:\n    name: build\n",
        encoding="utf-8",
    )
    (wf_dir / "contract-drift-governance.yml").write_text(
        "name: Contract Drift Governance\njobs:\n  governance:\n    name: governance\n",
        encoding="utf-8",
    )
    (wf_dir / "core-suites.yml").write_text(
        "name: Core Suites (Decision Integrity)\njobs:\n  core:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    (wf_dir / "sdk-parity.yml").write_text(
        "name: SDK Parity Check\njobs:\n  sdk-parity:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    (wf_dir / "sdk-generate.yml").write_text(
        "name: Generate SDK Types\njobs:\n  generate:\n    name: generate-typescript-types\n",
        encoding="utf-8",
    )
    (wf_dir / "sdk-test.yml").write_text(
        "name: SDK Tests\njobs:\n  typescript-sdk:\n    name: TypeScript SDK Type Check\n",
        encoding="utf-8",
    )
    (wf_dir / "test.yml").write_text(
        "name: Tests\njobs:\n  python-tests:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    (wf_dir / "openapi.yml").write_text(
        "name: OpenAPI Spec\njobs:\n  generate:\n    name: Generate & Validate\n",
        encoding="utf-8",
    )
    (wf_dir / "live-deploy-mode-gate.yml").write_text(
        "name: Live Deploy Mode Gate\njobs:\n  gate:\n    name: Validate Live Deploy Mode\n",
        encoding="utf-8",
    )
    (wf_dir / "pr-admission-controller.yml").write_text(
        "name: PR Admission Controller\njobs:\n  enforce:\n    name: PR Admission Signal (Advisory)\n",
        encoding="utf-8",
    )
    (wf_dir / "quality-smoke.yml").write_text(
        "name: Quality Pipeline Smoke\njobs:\n  quality:\n    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    (wf_dir / "required-check-priority.yml").write_text(
        "name: Required Check Priority\n", encoding="utf-8"
    )
    (wf_dir / "release-readiness.yml").write_text(
        "name: Release Readiness Gate\njobs:\n  release:\n    name: Release Readiness\n",
        encoding="utf-8",
    )
    (wf_dir / "security-gate.yml").write_text(
        "name: Security Gate\njobs:\n  summary:\n    name: Security Gate Summary\n",
        encoding="utf-8",
    )
    (wf_dir / "self-hosted-shadow.yml").write_text(
        "name: Self-Hosted Shadow CI\njobs:\n  shadow:\n    name: Mac TypeScript SDK Shadow\n",
        encoding="utf-8",
    )
    (wf_dir / "smoke.yml").write_text(
        "name: Smoke Tests\njobs:\n  smoke:\n    name: Smoke Tests\n",
        encoding="utf-8",
    )
    (wf_dir / "smoke-offline.yml").write_text(
        "name: Offline Golden Path\njobs:\n  offline:\n    name: Offline Demo Smoke\n",
        encoding="utf-8",
    )

    text = """
jobs:
  prioritize-required-checks:
    steps:
      - name: Cancel non-required workflow runs for this PR head
        uses: actions/github-script@v7
        with:
          script: |
            const alwaysKeepWorkflowPaths = new Set([
              '.github/workflows/aragora-merge-quorum.yml',
              '.github/workflows/aragora-review-gate.yml',
              '.github/workflows/autopilot-worktree-e2e.yml',
              '.github/workflows/build.yml',
              '.github/workflows/contract-drift-governance.yml',
              '.github/workflows/core-suites.yml',
              '.github/workflows/lint.yml',
              '.github/workflows/live-deploy-mode-gate.yml',
              '.github/workflows/sdk-parity.yml',
              '.github/workflows/sdk-generate.yml',
              '.github/workflows/sdk-test.yml',
              '.github/workflows/test.yml',
              '.github/workflows/openapi.yml',
              '.github/workflows/pr-admission-controller.yml',
              '.github/workflows/quality-smoke.yml',
              '.github/workflows/required-check-priority.yml',
              '.github/workflows/release-readiness.yml',
              '.github/workflows/security-gate.yml',
              '.github/workflows/self-hosted-shadow.yml',
              '.github/workflows/smoke.yml',
              '.github/workflows/smoke-offline.yml',
            ]);
            const alwaysKeepWorkflowNames = new Set([
              'Aragora Merge Quorum',
              'Aragora Code Review',
              'Autopilot Worktree E2E',
              'Build Documentation (PR Check)',
              'Contract Drift Governance',
              'Core Suites (Decision Integrity)',
              'Generate SDK Types',
              'Offline Golden Path',
              'Live Deploy Mode Gate',
              'PR Admission Controller',
              'Quality Pipeline Smoke',
              'Required Check Priority',
              'Release Readiness Gate',
              'Security Gate',
              'Lint',
              'Self-Hosted Shadow CI',
              'SDK Parity Check',
              'SDK Tests',
              'Smoke Tests',
              'Tests',
              'OpenAPI Spec',
            ]);
            for (const run of runs) {
              if (run.status !== 'queued') continue;
            }
"""
    violations = find_required_check_priority_violations(text, repo_root=repo_root)
    assert violations
    assert any(
        "required context marker `typecheck` not found in mapped workflow: .github/workflows/lint.yml"
        == v
        for v in violations
    )


def test_policy_allows_unfiltered_main_push_required_workflows(tmp_path: Path) -> None:
    repo_root = _write_policy_repo(tmp_path)

    violations = find_required_check_priority_violations(
        _valid_workflow_text(),
        repo_root=repo_root,
    )

    assert violations == []


def test_policy_rejects_path_filtered_main_push_required_workflow(
    tmp_path: Path,
) -> None:
    repo_root = _write_policy_repo(tmp_path)
    (repo_root / ".github/workflows/lint.yml").write_text(
        """
name: Lint
on:
  push:
    branches: [main]
    paths:
      - "aragora/**"
jobs:
  lint:
    name: lint
    runs-on: ubuntu-latest
  typecheck:
    name: typecheck
    runs-on: ubuntu-latest
""",
        encoding="utf-8",
    )

    violations = find_required_check_priority_violations(
        _valid_workflow_text(),
        repo_root=repo_root,
    )

    assert (
        "required context `lint` maps to path-filtered main push workflow: .github/workflows/lint.yml"
        in violations
    )
    assert (
        "required context `typecheck` maps to path-filtered main push workflow: .github/workflows/lint.yml"
        in violations
    )


def test_policy_rejects_flow_style_path_filtered_main_push_required_workflow(
    tmp_path: Path,
) -> None:
    repo_root = _write_policy_repo(tmp_path)
    (repo_root / ".github/workflows/lint.yml").write_text(
        """
name: Lint
on:
  push: {branches: [main], paths: ["aragora/**"]}
jobs:
  lint:
    name: lint
    runs-on: ubuntu-latest
  typecheck:
    name: typecheck
    runs-on: ubuntu-latest
""",
        encoding="utf-8",
    )

    violations = find_required_check_priority_violations(
        _valid_workflow_text(),
        repo_root=repo_root,
    )

    assert (
        "required context `lint` maps to path-filtered main push workflow: .github/workflows/lint.yml"
        in violations
    )
    assert (
        "required context `typecheck` maps to path-filtered main push workflow: .github/workflows/lint.yml"
        in violations
    )


def test_policy_rejects_top_level_flow_style_path_filtered_main_push_required_workflow(
    tmp_path: Path,
) -> None:
    repo_root = _write_policy_repo(tmp_path)
    (repo_root / ".github/workflows/lint.yml").write_text(
        """
name: Lint
on: {push: {branches: [main], paths: ["aragora/**"]}}
jobs:
  lint:
    name: lint
    runs-on: ubuntu-latest
  typecheck:
    name: typecheck
    runs-on: ubuntu-latest
""",
        encoding="utf-8",
    )

    violations = find_required_check_priority_violations(
        _valid_workflow_text(),
        repo_root=repo_root,
    )

    assert (
        "required context `lint` maps to path-filtered main push workflow: .github/workflows/lint.yml"
        in violations
    )
    assert (
        "required context `typecheck` maps to path-filtered main push workflow: .github/workflows/lint.yml"
        in violations
    )


def test_policy_rejects_multiline_flow_style_path_filtered_main_push_required_workflow(
    tmp_path: Path,
) -> None:
    repo_root = _write_policy_repo(tmp_path)
    (repo_root / ".github/workflows/lint.yml").write_text(
        """
name: Lint
on:
  push: {
    branches: [main],
    paths: ["aragora/**"],
  }
jobs:
  lint:
    name: lint
    runs-on: ubuntu-latest
  typecheck:
    name: typecheck
    runs-on: ubuntu-latest
""",
        encoding="utf-8",
    )

    violations = find_required_check_priority_violations(
        _valid_workflow_text(),
        repo_root=repo_root,
    )

    assert (
        "required context `lint` maps to path-filtered main push workflow: .github/workflows/lint.yml"
        in violations
    )
    assert (
        "required context `typecheck` maps to path-filtered main push workflow: .github/workflows/lint.yml"
        in violations
    )


def test_policy_ignores_comments_when_matching_main_push_branches(
    tmp_path: Path,
) -> None:
    repo_root = _write_policy_repo(tmp_path)
    (repo_root / ".github/workflows/lint.yml").write_text(
        """
name: Lint
on:
  push:
    branches:
      # main is intentionally handled by another workflow.
      - release
    paths:
      - "aragora/**"
jobs:
  lint:
    name: lint
    runs-on: ubuntu-latest
  typecheck:
    name: typecheck
    runs-on: ubuntu-latest
""",
        encoding="utf-8",
    )

    violations = find_required_check_priority_violations(
        _valid_workflow_text(),
        repo_root=repo_root,
    )

    assert violations == []


def test_policy_rejects_in_progress_cancellation_status_filter() -> None:
    # The pre-fix filter (`queued` OR `in_progress`) cancelled in-flight
    # advisory runs, leaving red "cancelled" conclusions the guardian never
    # reruns. The policy must reject it.
    text = _valid_workflow_text().replace(
        "if (run.status !== 'queued') continue;",
        "if (run.status !== 'queued' && run.status !== 'in_progress') continue;",
    )
    violations = find_required_check_priority_violations(text)
    assert any("not restricted to queued runs" in v for v in violations)


def test_policy_rejects_missing_queued_only_status_filter() -> None:
    lines = [line for line in _valid_workflow_text().splitlines() if "run.status" not in line]
    violations = find_required_check_priority_violations("\n".join(lines))
    assert any("not restricted to queued runs" in v for v in violations)


def test_policy_rejects_cancelling_only_current_head() -> None:
    text = _valid_workflow_text().replace(
        "if (run.head_sha === liveHeadSha) continue;",
        "if (run.head_sha !== liveHeadSha) continue;",
    )
    violations = find_required_check_priority_violations(text)
    assert any("does not skip the current PR head" in v for v in violations)


def test_policy_rejects_missing_current_head_skip() -> None:
    lines = [line for line in _valid_workflow_text().splitlines() if "run.head_sha" not in line]
    violations = find_required_check_priority_violations("\n".join(lines))
    assert any("does not skip the current PR head" in v for v in violations)


def test_policy_rejects_missing_source_repo_guard() -> None:
    lines = [line for line in _valid_workflow_text().splitlines() if "runHeadRepo" not in line]
    violations = find_required_check_priority_violations("\n".join(lines))
    assert any("source repo matches this PR's head repo" in v for v in violations)


def test_policy_rejects_missing_pr_attribution_guard() -> None:
    lines = [line for line in _valid_workflow_text().splitlines() if "runPrNumbers" not in line]
    violations = find_required_check_priority_violations("\n".join(lines))
    assert any("does not verify PR attribution" in v for v in violations)


def test_policy_rejects_missing_live_head_fetch() -> None:
    text = _valid_workflow_text().replace("github.rest.pulls.get", "github.rest.pulls.list")
    violations = find_required_check_priority_violations(text)
    assert any("does not resolve the live PR head" in v for v in violations)


def test_policy_rejects_missing_per_sweep_live_head_refresh() -> None:
    text = _valid_workflow_text().replace(
        "const liveHeadSha = await getLiveHeadSha();",
        "const liveHeadSha = headSha;",
    )
    violations = find_required_check_priority_violations(text)
    assert any("does not refresh the live PR head at the start" in v for v in violations)


def test_policy_rejects_missing_stale_event_head_guard() -> None:
    text = _valid_workflow_text().replace(
        "if (!liveHeadSha || liveHeadSha !== headSha) break;",
        "if (!liveHeadSha) break;",
        1,
    )
    violations = find_required_check_priority_violations(text)
    assert any("does not stop when its event head is stale" in v for v in violations)


def test_policy_rejects_missing_pre_cancel_head_refresh() -> None:
    text = _valid_workflow_text().replace(
        "const confirmedLiveHeadSha = await getLiveHeadSha();",
        "const confirmedLiveHeadSha = liveHeadSha;",
    )
    violations = find_required_check_priority_violations(text)
    assert any("does not refresh the live PR head" in v for v in violations)


def test_policy_accepts_double_quoted_queued_only_status_filter() -> None:
    text = _valid_workflow_text().replace(
        "if (run.status !== 'queued') continue;",
        'if (run.status !== "queued") continue;',
    )
    violations = find_required_check_priority_violations(text)
    assert violations == []


def test_unstable_allowlisted_workflows_do_not_cancel_same_pr_runs() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    workflow_paths = (
        ".github/workflows/docs-build.yml",
        ".github/workflows/docs-consistency.yml",
        ".github/workflows/portability-lint.yml",
    )

    for rel in workflow_paths:
        text = (repo_root / rel).read_text(encoding="utf-8")
        concurrency_block = text.split("concurrency:", maxsplit=1)[1].split("jobs:", maxsplit=1)[0]
        assert "cancel-in-progress: false" in concurrency_block, rel


def test_self_hosted_shadow_keeps_superseded_run_reclamation() -> None:
    # Both shadow jobs occupy the scarce self-hosted fleet, the priority sweep
    # never cancels in_progress runs, and self-hosted-shadow.yml is on the
    # sweep's keep-list — so workflow-level concurrency cancellation is the
    # only path that frees a runner when a new head supersedes a run. Cancelled
    # current-head runs are absorbed by the UNSTABLE cancellation receipt.
    repo_root = Path(__file__).resolve().parents[2]
    text = (repo_root / ".github/workflows/self-hosted-shadow.yml").read_text(encoding="utf-8")
    concurrency_block = text.split("concurrency:", maxsplit=1)[1].split("jobs:", maxsplit=1)[0]
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in concurrency_block


def test_repo_required_check_priority_policy_passes_for_current_tree() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    violations = check_repo(repo_root)
    assert violations == []
