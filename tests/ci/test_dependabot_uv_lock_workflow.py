"""Tests for the ``Regenerate uv.lock`` step of ``dependabot-uv-lock.yml``.

Structural checks read the parsed workflow. Behaviour checks run the step's
``run`` script the way ``shell: bash`` does, in a temporary git repository whose
``refs/remotes/origin/main`` commit carries a copy of the real cooldown helper,
with a fake ``python`` and the fake ``uv`` from ``test_uv_lock_with_cooldown``
first on PATH. ``ARAGORA_TEST_BASH`` selects the bash.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from tests.ci.test_uv_lock_with_cooldown import (
    BASH,
    COOLED,
    FETCH_FAILURE,
    HELPER,
    NO_SOLUTION,
    ORIGINAL,
    RFC3339_UTC,
    SYSTEM_PATH,
    clean_env,
    fake_uv_config,
    read_calls,
    render_lock,
    write_fake_bin,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "dependabot-uv-lock.yml"
RELOCK_STEP = "Regenerate uv.lock"
HELPER_PATH = "scripts/ci/uv_lock_with_cooldown.sh"

POLICY_MARKERS = [
    "github.event.pull_request.head.repo.full_name == github.repository",
    "github.event.pull_request.user.login == 'app/dependabot'",
    "grep -vx 'uv.lock'",
    "uv lock --check",
    'git push origin "HEAD:${{ steps.target.outputs.branch }}"',
]

RESOLVE_TARGET_RUN = """\
set -euo pipefail
if [[ "${EVENT_NAME}" == "workflow_dispatch" ]]; then
  if [[ -z "${PR_NUMBER}" ]]; then
    echo "::error::workflow_dispatch requires pr_number"
    exit 1
  fi
  pr_json="$(gh pr view "${PR_NUMBER}" --json author,headRefName,headRepositoryOwner,isDraft)"
  author="$(jq -r '.author.login' <<< "${pr_json}")"
  owner="$(jq -r '.headRepositoryOwner.login' <<< "${pr_json}")"
  draft="$(jq -r '.isDraft' <<< "${pr_json}")"
  if [[ "${author}" != "app/dependabot" && "${author}" != "dependabot" && "${author}" != "dependabot[bot]" ]]; then
    echo "::error::PR #${PR_NUMBER} is authored by ${author}, not dependabot"
    exit 1
  fi
  if [[ "${owner}" != "${GITHUB_REPOSITORY_OWNER}" ]]; then
    echo "::error::PR #${PR_NUMBER} is not from the base repository owner"
    exit 1
  fi
  if [[ "${draft}" == "true" ]]; then
    echo "::notice::PR #${PR_NUMBER} is draft; skipping"
    echo "skip=true" >> "${GITHUB_OUTPUT}"
    exit 0
  fi
  echo "branch=$(jq -r '.headRefName' <<< "${pr_json}")" >> "${GITHUB_OUTPUT}"
else
  echo "branch=${HEAD_REF}" >> "${GITHUB_OUTPUT}"
fi
"""

COMMIT_RUN = """\
set -euo pipefail
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add uv.lock
git commit -m "chore(deps): refresh uv lock"
git push origin "HEAD:${{ steps.target.outputs.branch }}"
"""

JOB_IF = (
    "github.event_name == 'workflow_dispatch' || (\n"
    "  (\n"
    "    github.actor == 'dependabot[bot]' ||\n"
    "    github.event.pull_request.user.login == 'app/dependabot' ||\n"
    "    github.event.pull_request.user.login == 'dependabot[bot]' ||\n"
    "    github.event.pull_request.user.login == 'dependabot'\n"
    "  ) &&\n"
    "  github.event.pull_request.head.repo.full_name == github.repository &&\n"
    "  github.event.pull_request.head.ref != github.event.pull_request.base.ref &&\n"
    "  !github.event.pull_request.draft\n"
    ")"
)

NOT_SKIPPED = "steps.target.outputs.skip != 'true'"

# The whole workflow as of 4127ee27 minus the relock step's `run`, which is the
# only part the cooldown repair may change.
EXPECTED_OUTSIDE_RELOCK_RUN = {
    "name": "Dependabot UV Lock Refresh",
    "on": {
        "pull_request_target": {
            "types": ["opened", "synchronize", "reopened", "ready_for_review"],
            "branches": ["main"],
            "paths": [
                "pyproject.toml",
                "uv.lock",
                "aragora-debate/pyproject.toml",
                "aragora-verify/pyproject.toml",
                "sdk/python/pyproject.toml",
                ".github/workflows/dependabot-uv-lock.yml",
            ],
        },
        "workflow_dispatch": {
            "inputs": {
                "pr_number": {
                    "description": "Dependabot PR number to relock",
                    "required": False,
                    "type": "string",
                }
            }
        },
    },
    "permissions": {"contents": "write", "pull-requests": "read"},
    "concurrency": {
        "group": "dependabot-uv-lock-${{ github.event.pull_request.number || "
        "github.event.inputs.pr_number || github.run_id }}",
        "cancel-in-progress": True,
    },
    "jobs": {
        "refresh-lock": {
            "name": "Refresh uv.lock on Dependabot PRs",
            "if": JOB_IF,
            "runs-on": "ubuntu-latest",
            "timeout-minutes": 10,
            "steps": [
                {
                    "name": "Resolve target branch",
                    "id": "target",
                    "shell": "bash",
                    "env": {
                        "EVENT_NAME": "${{ github.event_name }}",
                        "PR_NUMBER": "${{ github.event.inputs.pr_number || "
                        "github.event.pull_request.number }}",
                        "HEAD_REF": "${{ github.event.pull_request.head.ref }}",
                        "GH_TOKEN": "${{ github.token }}",
                    },
                    "run": RESOLVE_TARGET_RUN,
                },
                {
                    "name": "Checkout Dependabot branch",
                    "if": NOT_SKIPPED,
                    "uses": "actions/checkout@v4",
                    "with": {
                        "ref": "${{ steps.target.outputs.branch }}",
                        "repository": "${{ github.repository }}",
                        "token": "${{ github.token }}",
                        "fetch-depth": 0,
                    },
                },
                {
                    "name": "Set up Python",
                    "if": NOT_SKIPPED,
                    "uses": "actions/setup-python@v5",
                    "with": {"python-version": "3.11"},
                },
                {"name": RELOCK_STEP, "if": NOT_SKIPPED, "id": "relock", "shell": "bash"},
                {
                    "name": "Commit refreshed lockfile",
                    "if": f"{NOT_SKIPPED} && steps.relock.outputs.changed == 'true'",
                    "shell": "bash",
                    "run": COMMIT_RUN,
                },
            ],
        }
    },
}


def load_workflow() -> dict[str, Any]:
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML follows YAML 1.1 and reads the bare `on:` key as True.
    doc["on"] = doc.pop(True)
    return doc


def relock_step(doc: dict[str, Any]) -> dict[str, Any]:
    steps = doc["jobs"]["refresh-lock"]["steps"]
    matches = [step for step in steps if step.get("name") == RELOCK_STEP]
    assert len(matches) == 1, matches
    return matches[0]


def relock_run() -> str:
    return str(relock_step(load_workflow())["run"])


def test_relock_runs_mains_cooldown_helper_with_no_bare_uv_lock() -> None:
    run = relock_run()
    commands = [line for line in run.splitlines() if not line.lstrip().startswith("#")]

    assert [line for line in commands if re.match(r"^\s*uv lock\s*$", line)] == []
    assert "--allow-package" not in run
    assert "${{" not in run
    assert 'python -m pip install "uv>=0.11.19,<0.12"' in commands
    assert f'git show origin/main:{HELPER_PATH} > "${{helper}}"' in commands
    helper_runs = [line for line in commands if 'bash "${helper}"' in line]
    assert helper_runs == ['bash "${helper}" 2>&1 | tee "${log}" || rc=$?']


def test_everything_outside_the_relock_run_is_unchanged() -> None:
    doc = load_workflow()
    del relock_step(doc)["run"]

    assert doc == EXPECTED_OUTSIDE_RELOCK_RUN


def test_branch_mutation_policy_markers_are_kept() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert [marker for marker in POLICY_MARKERS if marker not in text] == []


def test_no_workflow_file_lifts_the_cooldown() -> None:
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / ".github").rglob("*")
        if path.is_file() and "--allow-package" in path.read_text(encoding="utf-8", errors="ignore")
    ]

    assert offenders == []


GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.com",
            "-c",
            "commit.gpgsign=false",
            "-c",
            f"core.hooksPath={os.devnull}",
            *args,
        ],
        cwd=repo,
        env={**os.environ, **GIT_ENV},
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout


def make_checkout(
    tmp_path: Path,
    *,
    helper_on_main: bool = True,
    lock_packages: list[tuple[str, str]] = ORIGINAL,
) -> Path:
    """A Dependabot branch checkout (fetch-depth 0) cut before the helper existed."""
    repo = tmp_path / "checkout"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0"\ndependencies = ["dep", "pkg>=0.9"]\n',
        encoding="utf-8",
    )
    (repo / "uv.lock").write_text(render_lock(lock_packages), encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "switch", "-q", "-c", "dependabot/pip/pkg-2.0")
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "fixture"\nversion = "0"\ndependencies = ["dep", "pkg>=1.0"]\n',
        encoding="utf-8",
    )
    git(repo, "commit", "-q", "-am", "chore(deps): bump pkg")
    git(repo, "switch", "-q", "main")
    if helper_on_main:
        (repo / "scripts" / "ci").mkdir(parents=True)
        shutil.copy2(HELPER, repo / HELPER_PATH)
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "add the cooldown helper")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "switch", "-q", "dependabot/pip/pkg-2.0")
    assert not (repo / HELPER_PATH).exists()
    return repo


class StepResult:
    def __init__(self, tmp_path: Path, repo: Path, proc: subprocess.CompletedProcess[str]):
        self.proc = proc
        self.lock = (repo / "uv.lock").read_text(encoding="utf-8")
        self.status = git(repo, "status", "--porcelain")
        output = tmp_path / "github-output"
        summary = tmp_path / "step-summary.md"
        self.output = output.read_text(encoding="utf-8") if output.exists() else ""
        self.summary = summary.read_text(encoding="utf-8") if summary.exists() else ""
        self.uv_calls = read_calls(tmp_path / "uv-calls.jsonl")
        pip_log = tmp_path / "python-calls.log"
        self.python_calls = (
            pip_log.read_text(encoding="utf-8").splitlines() if pip_log.exists() else []
        )


def run_relock_step(tmp_path: Path, repo: Path, **scenario: object) -> StepResult:
    bin_dir = tmp_path / "bin"
    write_fake_bin(bin_dir)
    python = bin_dir / "python"
    python.write_text(
        f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{tmp_path / 'python-calls.log'}'\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    script = tmp_path / "relock-step.sh"
    script.write_text(relock_run(), encoding="utf-8")
    git_dir = str(Path(shutil.which("git") or "/usr/bin/git").parent)
    env = clean_env()
    env.update(GIT_ENV)
    env.update(
        PATH=":".join([str(bin_dir), git_dir, SYSTEM_PATH]),
        FAKE_UV_CONFIG=fake_uv_config(tmp_path / "uv-calls.jsonl", **scenario),
        GITHUB_OUTPUT=str(tmp_path / "github-output"),
        GITHUB_STEP_SUMMARY=str(tmp_path / "step-summary.md"),
        RUNNER_TEMP=str(runner_temp),
    )
    # GitHub runs `shell: bash` steps as `bash --noprofile --norc -eo pipefail {0}`.
    proc = subprocess.run(
        [BASH, "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return StepResult(tmp_path, repo, proc)


def summary_cutoff(summary: str) -> str:
    match = re.search(r"^exclude-newer cutoff: (\S+)$", summary, re.MULTILINE)
    assert match, summary
    return match.group(1)


def test_helper_exit_0_commits_the_cooled_lock(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path)

    result = run_relock_step(tmp_path, repo, plain=COOLED)

    assert result.proc.returncode == 0, (result.proc.stdout, result.proc.stderr)
    assert result.output.splitlines() == ["changed=true"]
    assert result.summary.startswith("### uv.lock relock under the 7-day cooldown\n")
    assert RFC3339_UTC.fullmatch(summary_cutoff(result.summary))
    assert "helper exit code: 0" in result.summary.splitlines()
    assert "held back" not in result.summary
    assert result.lock == render_lock(COOLED)
    assert [call["kind"] for call in result.uv_calls] == ["cooled", "plain", "finalize", "check"]
    assert result.python_calls == [
        "-m pip install --upgrade pip",
        "-m pip install uv>=0.11.19,<0.12",
    ]


def test_helper_exit_2_reports_held_back_packages_and_commits(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path)

    result = run_relock_step(tmp_path, repo)

    assert result.proc.returncode == 0, (result.proc.stdout, result.proc.stderr)
    assert result.output.splitlines() == ["changed=true"]
    assert "helper exit code: 2" in result.summary.splitlines()
    assert "```\nheld back: pkg 2.0 -> 1.0\n```\n" in result.summary
    assert (
        "::warning::the uv cooldown held back 1 package(s); see the job summary"
        in result.proc.stdout.splitlines()
    )
    assert result.lock == render_lock(COOLED)


def test_helper_exit_4_fails_the_step_without_plain_relock(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path)

    result = run_relock_step(tmp_path, repo, fail={"cooled": {"rc": 1, "stderr": NO_SOLUTION}})

    assert result.proc.returncode == 1, (result.proc.stdout, result.proc.stderr)
    assert (
        "::error::no resolution satisfies the 7-day uv cooldown; uv.lock not refreshed "
        "(manual security relock: docs/RATCHETS.md)" in result.proc.stdout.splitlines()
    )
    assert "helper exit code: 4" in result.summary.splitlines()
    assert result.output == ""
    assert result.lock == render_lock(ORIGINAL)
    assert result.status == ""
    assert [call["kind"] for call in result.uv_calls] == ["cooled"]


def test_other_helper_failure_fails_the_step(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path)

    result = run_relock_step(tmp_path, repo, fail={"cooled": {"rc": 1, "stderr": FETCH_FAILURE}})

    assert result.proc.returncode == 1, (result.proc.stdout, result.proc.stderr)
    assert (
        "::error::cooldown relock failed (helper exit 1); uv.lock not refreshed"
        in result.proc.stdout.splitlines()
    )
    assert "helper exit code: 1" in result.summary.splitlines()
    assert result.output == ""
    assert result.lock == render_lock(ORIGINAL)
    assert result.status == ""
    assert [call["kind"] for call in result.uv_calls] == ["cooled"]


def test_unchanged_lock_reports_changed_false(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, lock_packages=COOLED)

    result = run_relock_step(tmp_path, repo, plain=COOLED)

    assert result.proc.returncode == 0, (result.proc.stdout, result.proc.stderr)
    assert result.output.splitlines() == ["changed=false"]
    assert "uv.lock is already fresh" in result.proc.stdout.splitlines()
    assert "helper exit code: 0" in result.summary.splitlines()
    assert result.status == ""
    assert [call["kind"] for call in result.uv_calls] == ["cooled", "plain", "finalize"]


def test_missing_helper_on_main_fails_before_any_uv_call(tmp_path: Path) -> None:
    repo = make_checkout(tmp_path, helper_on_main=False)

    result = run_relock_step(tmp_path, repo, plain=COOLED)

    assert result.proc.returncode != 0, (result.proc.stdout, result.proc.stderr)
    assert result.uv_calls == []
    assert result.output == ""
    assert result.lock == render_lock(ORIGINAL)
    assert result.status == ""
