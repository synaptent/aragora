import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest


RUNBOOK = Path(__file__).resolve().parents[2] / "docs/runbooks/main-green-rearm-evidence.md"


def _reconciliation_program(text: str) -> str:
    match = re.search(
        r"jq -n \\\n.*?\n  '(\{\n.*?\n  \})' \\\n  \| tee",
        text,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def _collection_shell_program(text: str) -> str:
    match = re.search(
        r"\n(RULESET_REQUIRED_RAW=.*?\n\)\" \|\| exit 1)\n\n"
        r"jq -n \\\n",
        text,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def _policy_program(text: str) -> str:
    block = text.split('REQUIRED_POLICY_JSON="$(')[1]
    match = re.search(
        r"--argjson protection .*? \\\n    '(\{\n.*?\n    \})'\n\)\" \|\| exit 1",
        block,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def _ruleset_program(text: str) -> str:
    block = text.split('RULESET_REQUIRED_JSON="$(')[1]
    match = re.search(
        r"\| jq -e '\n(.*?)\n    '\n\)\" \|\| exit 1",
        block,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def _branch_protection_program(text: str) -> str:
    block = text.split('BRANCH_PROTECTION_REQUIRED_JSON="$(')[1]
    match = re.search(
        r"\| jq -e '\n(.*?)\n    '\n\)\" \|\| exit 1",
        block,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def _reconciliation_guard(text: str) -> str:
    match = re.search(
        r"jq -e \\\n  '(.*?)' \\\n"
        r'  "\$EVIDENCE_DIR/required-contexts\.json"',
        text,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def _rearm_shell_program(text: str) -> str:
    match = re.search(
        r"```bash\nsh -euc '\n(.*?)\n' sh \"\$HALT_FILE\"",
        text,
        flags=re.DOTALL,
    )
    assert match is not None
    return match.group(1)


def _reconcile(
    text: str,
    *,
    policy: dict[str, object],
    runs: list[dict[str, object]],
    statuses: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    result = subprocess.run(
        [
            "jq",
            "-n",
            "--argjson",
            "policy",
            json.dumps(policy),
            "--argjson",
            "runs",
            json.dumps(runs),
            "--argjson",
            "statuses",
            json.dumps(statuses or []),
            _reconciliation_program(text),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def _write_fake_gh(tmp_path: Path) -> Path:
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/bin/sh
args=$*
case "$args" in
  *rules/branches/main*)
    payload='[[{"type":"required_status_checks","parameters":{"required_status_checks":[{"context":"lint","integration_id":15368}]}}]]'
    ;;
  *branches/main/protection*)
    payload='{"checks":[{"context":"lint","app_id":15368}],"contexts":[]}'
    ;;
  *check-runs*)
    payload='[{"check_runs":[{"id":1,"name":"lint","app":{"id":15368},"status":"completed","conclusion":"success"}]}]'
    ;;
  */statuses*)
    payload='[[]]'
    ;;
  *)
    exit 2
    ;;
esac
if [ -n "${MALFORMED_MATCH:-}" ]; then
  case "$args" in
    *"$MALFORMED_MATCH"*) payload='{}' ;;
  esac
fi
printf '%s\n' "$payload"
if [ -n "${FAIL_MATCH:-}" ]; then
  case "$args" in
    *"$FAIL_MATCH"*) exit 23 ;;
  esac
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    return fake_gh


def _write_fake_rearm_tools(tmp_path: Path) -> Path:
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()

    fake_git = tool_dir / "git"
    fake_git.write_text(
        """#!/bin/sh
case "$3" in
  fetch)
    if [ -n "${MUTATE_HALT_FILE:-}" ]; then
      printf 'main_red_changed\n' > "$MUTATE_HALT_FILE"
    fi
    ;;
  rev-parse)
    printf '%s\n' "$EXPECTED_CANDIDATE_SHA"
    ;;
  *)
    exit 2
    ;;
esac
""",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    fake_shasum = tool_dir / "shasum"
    fake_shasum.write_text(
        """#!/usr/bin/env python3
import hashlib
from pathlib import Path
import sys

path = Path(sys.argv[-1])
print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path}")
""",
        encoding="utf-8",
    )
    fake_shasum.chmod(0o755)
    return tool_dir


def test_toolchain_requirement_is_read_from_candidate_commit() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    assert 'git show "${CANDIDATE_SHA}:pyproject.toml"' in text
    assert "grep -nE '\"mypy[<>=]'" in text
    assert '"$REPO_ROOT/pyproject.toml"' not in text


def test_required_context_reconciliation_consumes_all_check_run_pages() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "gh api --paginate --slurp" in text
    assert "check-runs?filter=latest&per_page=100" in text
    assert "statuses?per_page=100" in text
    assert '"repos/synaptent/aragora/rules/branches/main?per_page=100"' in text
    assert ".parameters.required_status_checks[]" in text
    assert "repos/synaptent/aragora/branches/main/protection/required_status_checks" in text
    assert 'source: "ruleset"' in text
    assert 'source: "branch_protection"' in text
    assert "status_or_checks:" in text
    assert "- [$ruleset[].context]" in text
    assert "sources:" in text
    assert "app_id: .app.id" in text
    assert "else ($matches | max_by(.id))" in text
    assert ".app_id == $requirement.app_id" in text
    assert "[.[].check_runs[] | {" in text
    assert "check-run pagination response has an invalid page schema" in text
    assert "commit-status pagination response is not an array of pages" in text
    assert 'tee "$EVIDENCE_DIR/required-contexts.json"' in text
    assert "sh -eu <<'REQUIRED_CONTEXT_EVIDENCE'" in text
    assert "sh -eu <<'HEAD_RECHECK'" in text
    assert "HEAD DRIFT:" in text
    assert "REQUIRED_CONTEXT_EVIDENCE\n```" in text
    assert "`jq` is older than 1.7" in text
    assert "gh` is older than 2.40" in text
    assert '.latest.conclusion == "success"' in text
    assert 'expected_skip: ($requirement.context == "aragora-merge-quorum")' in text
    assert ".expected_skip and .latest.conclusion" in text
    assert '.latest.conclusion == "skipped"' in text
    assert 'all(.statuses[]; .found and .latest.state == "success")' in text
    assert ".sources.ruleset" not in text


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq is required for runbook fixtures")
class TestJqPrograms:
    @pytest.mark.parametrize(
        "failure_match",
        [
            "rules/branches/main",
            "branches/main/protection",
            "check-runs",
            "/statuses",
        ],
    )
    def test_context_collection_rejects_output_from_failed_api(
        self,
        tmp_path: Path,
        failure_match: str,
    ) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        _write_fake_gh(tmp_path)
        env = os.environ.copy()
        env.update(
            {
                "CANDIDATE_SHA": "deadbeef",
                "FAIL_MATCH": failure_match,
                "PATH": f"{tmp_path}:{env['PATH']}",
            }
        )

        result = subprocess.run(
            ["sh", "-c", f"{_collection_shell_program(text)}\nprintf 'CERTIFIED\\n'"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0
        assert "CERTIFIED" not in result.stdout

    def test_context_collection_accepts_complete_api_responses(self, tmp_path: Path) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        _write_fake_gh(tmp_path)
        env = os.environ.copy()
        env.update(
            {
                "CANDIDATE_SHA": "deadbeef",
                "PATH": f"{tmp_path}:{env['PATH']}",
            }
        )

        result = subprocess.run(
            ["sh", "-c", f"{_collection_shell_program(text)}\nprintf 'CERTIFIED\\n'"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0, result.stderr
        assert result.stdout == "CERTIFIED\n"

    @pytest.mark.parametrize(
        "malformed_match",
        [
            "rules/branches/main",
            "branches/main/protection",
            "check-runs",
            "/statuses",
        ],
    )
    def test_context_collection_rejects_successful_malformed_api_response(
        self,
        tmp_path: Path,
        malformed_match: str,
    ) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        _write_fake_gh(tmp_path)
        env = os.environ.copy()
        env.update(
            {
                "CANDIDATE_SHA": "deadbeef",
                "MALFORMED_MATCH": malformed_match,
                "PATH": f"{tmp_path}:{env['PATH']}",
            }
        )

        result = subprocess.run(
            ["sh", "-c", f"{_collection_shell_program(text)}\nprintf 'CERTIFIED\\n'"],
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0
        assert "CERTIFIED" not in result.stdout

    @pytest.mark.parametrize(
        "payload",
        [
            {"unexpected": "top-level-shape"},
            [[{"type": "required_status_checks", "parameters": {}}]],
            [
                [
                    {
                        "type": "required_status_checks",
                        "parameters": {"required_status_checks": "lint"},
                    }
                ]
            ],
        ],
    )
    def test_ruleset_normalization_rejects_incomplete_schema(self, payload: object) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")

        result = subprocess.run(
            ["jq", "-e", _ruleset_program(text)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0

    @pytest.mark.parametrize(
        "payload",
        [
            {"contexts": []},
            {"checks": []},
            {"checks": None, "contexts": []},
            {"checks": [], "contexts": None},
        ],
    )
    def test_branch_protection_normalization_rejects_incomplete_schema(
        self, payload: object
    ) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")

        result = subprocess.run(
            ["jq", "-e", _branch_protection_program(text)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0

    def test_required_policy_unions_rulesets_and_branch_protection(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        ruleset = [
            {"context": "ruleset-only", "app_id": 15368},
            {"context": "status-or-check", "app_id": None},
        ]
        protection = {
            "checks": [
                {"context": "lint", "app_id": 15368},
                {"context": "branch-status", "app_id": None},
            ],
            "legacy_contexts": [
                "legacy",
                "ruleset-only",
                "status-or-check",
                "branch-status",
            ],
        }

        result = subprocess.run(
            [
                "jq",
                "-n",
                "--argjson",
                "ruleset",
                json.dumps(ruleset),
                "--argjson",
                "protection",
                json.dumps(protection),
                _policy_program(text),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        policy = json.loads(result.stdout)
        assert policy["checks"] == [
            {
                "context": "lint",
                "app_id": 15368,
                "sources": ["branch_protection"],
            },
            {"context": "ruleset-only", "app_id": 15368, "sources": ["ruleset"]},
        ]
        assert policy["status_or_checks"] == [
            {"context": "branch-status", "sources": ["branch_protection"]},
            {"context": "status-or-check", "sources": ["ruleset"]},
        ]
        assert policy["legacy_contexts"] == ["legacy"]
        assert "sources" not in policy

    def test_unbound_branch_protection_check_accepts_legacy_status(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        ruleset: list[dict[str, object]] = []
        raw_protection = {
            "contexts": ["external-ci"],
            "checks": [{"context": "external-ci", "app_id": None}],
        }
        normalization_result = subprocess.run(
            ["jq", _branch_protection_program(text)],
            input=json.dumps(raw_protection),
            check=True,
            capture_output=True,
            text=True,
        )
        protection = json.loads(normalization_result.stdout)

        policy_result = subprocess.run(
            [
                "jq",
                "-n",
                "--argjson",
                "ruleset",
                json.dumps(ruleset),
                "--argjson",
                "protection",
                json.dumps(protection),
                _policy_program(text),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        policy = json.loads(policy_result.stdout)
        statuses = [
            {
                "id": 12,
                "context": "external-ci",
                "state": "success",
                "updated_at": "2026-07-21T08:00:00Z",
            }
        ]

        evidence = _reconcile(text, policy=policy, runs=[], statuses=statuses)
        guard = subprocess.run(
            ["jq", "-e", _reconciliation_guard(text)],
            input=json.dumps(evidence),
            capture_output=True,
            text=True,
        )

        assert policy["checks"] == []
        assert protection == {
            "checks": [{"context": "external-ci", "app_id": None}],
            "legacy_contexts": [],
        }
        assert policy["status_or_checks"] == [
            {"context": "external-ci", "sources": ["branch_protection"]}
        ]
        assert guard.returncode == 0, guard.stderr
        assert evidence["status_or_checks"][0]["latest_status"]["id"] == 12

    def test_required_context_reconciliation_prefers_newer_queued_run(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        policy = {
            "checks": [
                {
                    "context": "lint",
                    "app_id": 15368,
                    "sources": ["branch_protection"],
                }
            ],
            "status_or_checks": [],
            "legacy_contexts": [],
            "sources": {"ruleset": True, "branch_protection": True},
        }
        runs = [
            {
                "id": 100,
                "name": "lint",
                "app_id": 15368,
                "status": "completed",
                "conclusion": "success",
                "started_at": "2026-07-17T10:00:01Z",
            },
            {
                "id": 101,
                "name": "lint",
                "app_id": 15368,
                "status": "queued",
                "conclusion": None,
                "started_at": None,
            },
        ]

        evidence = _reconcile(text, policy=policy, runs=runs)
        assert evidence["checks"][0]["latest"]["id"] == 101
        assert evidence["checks"][0]["latest"]["status"] == "queued"

    @pytest.mark.parametrize(
        "runs",
        [
            [],
            [
                {
                    "id": 101,
                    "name": "ruleset-only",
                    "app_id": 15368,
                    "status": "completed",
                    "conclusion": "failure",
                }
            ],
        ],
    )
    def test_ruleset_only_missing_or_red_check_blocks(
        self,
        runs: list[dict[str, object]],
    ) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        policy = {
            "checks": [
                {
                    "context": "ruleset-only",
                    "app_id": 15368,
                    "sources": ["ruleset"],
                }
            ],
            "status_or_checks": [],
            "legacy_contexts": [],
            "sources": {"ruleset": True, "branch_protection": True},
        }
        evidence = _reconcile(text, policy=policy, runs=runs)

        result = subprocess.run(
            ["jq", "-e", _reconciliation_guard(text)],
            input=json.dumps(evidence),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0

    def test_unbound_ruleset_context_accepts_green_legacy_status(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        policy = {
            "checks": [],
            "status_or_checks": [{"context": "ruleset-status", "sources": ["ruleset"]}],
            "legacy_contexts": [],
            "sources": {"ruleset": True, "branch_protection": True},
        }
        statuses = [
            {
                "id": 7,
                "context": "ruleset-status",
                "state": "success",
                "updated_at": "2026-07-20T12:00:00Z",
            }
        ]

        evidence = _reconcile(text, policy=policy, runs=[], statuses=statuses)
        result = subprocess.run(
            ["jq", "-e", _reconciliation_guard(text)],
            input=json.dumps(evidence),
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert evidence["status_or_checks"][0]["latest_status"]["id"] == 7
        assert evidence["status_or_checks"][0]["latest_check"] is None

    def test_unbound_ruleset_context_rejects_conflicting_surfaces(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        policy = {
            "checks": [],
            "status_or_checks": [{"context": "ruleset-status", "sources": ["ruleset"]}],
            "legacy_contexts": [],
            "sources": {"ruleset": True, "branch_protection": True},
        }
        runs = [
            {
                "id": 8,
                "name": "ruleset-status",
                "app_id": 15368,
                "status": "completed",
                "conclusion": "success",
            }
        ]
        statuses = [
            {
                "id": 9,
                "context": "ruleset-status",
                "state": "failure",
                "updated_at": "2026-07-20T12:01:00Z",
            }
        ]

        evidence = _reconcile(text, policy=policy, runs=runs, statuses=statuses)
        result = subprocess.run(
            ["jq", "-e", _reconciliation_guard(text)],
            input=json.dumps(evidence),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert evidence["status_or_checks"][0]["conflict"] is True

    def test_unbound_ruleset_context_uses_numeric_id_for_latest_status(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        policy = {
            "checks": [],
            "status_or_checks": [{"context": "ruleset-status", "sources": ["ruleset"]}],
            "legacy_contexts": [],
            "sources": {"ruleset": True, "branch_protection": True},
        }
        statuses = [
            {
                "id": 7,
                "context": "ruleset-status",
                "state": "success",
                "updated_at": "2026-07-20T12:00:00Z",
            },
            {
                "id": 8,
                "context": "ruleset-status",
                "state": "failure",
                "updated_at": "2026-07-20T12:00:00Z",
            },
        ]

        evidence = _reconcile(text, policy=policy, runs=[], statuses=statuses)
        result = subprocess.run(
            ["jq", "-e", _reconciliation_guard(text)],
            input=json.dumps(evidence),
            capture_output=True,
            text=True,
        )

        assert evidence["status_or_checks"][0]["latest_status"]["id"] == 8
        assert result.returncode != 0

    def test_unbound_ruleset_context_rejects_malformed_alternate_proof(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        policy = {
            "checks": [],
            "status_or_checks": [{"context": "ruleset-status", "sources": ["ruleset"]}],
            "legacy_contexts": [],
            "sources": {"ruleset": True, "branch_protection": True},
        }
        runs = [
            {
                "id": "not-numeric",
                "name": "ruleset-status",
                "status": "completed",
                "conclusion": "success",
            }
        ]
        statuses = [
            {
                "id": 10,
                "context": "ruleset-status",
                "state": "success",
                "updated_at": "2026-07-20T12:02:00Z",
            }
        ]

        evidence = _reconcile(text, policy=policy, runs=runs, statuses=statuses)
        result = subprocess.run(
            ["jq", "-e", _reconciliation_guard(text)],
            input=json.dumps(evidence),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert evidence["status_or_checks"][0]["proof_complete"] is False

    def test_app_bound_ruleset_context_rejects_status_only_proof(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        policy = {
            "checks": [
                {
                    "context": "app-bound",
                    "app_id": 15368,
                    "sources": ["ruleset"],
                }
            ],
            "status_or_checks": [],
            "legacy_contexts": [],
            "sources": {"ruleset": True, "branch_protection": True},
        }
        statuses = [
            {
                "id": 11,
                "context": "app-bound",
                "state": "success",
                "updated_at": "2026-07-20T12:03:00Z",
            }
        ]

        evidence = _reconcile(text, policy=policy, runs=[], statuses=statuses)
        result = subprocess.run(
            ["jq", "-e", _reconciliation_guard(text)],
            input=json.dumps(evidence),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert evidence["checks"][0]["found"] is False

    def test_empty_normalized_policy_fails_closed(self) -> None:
        text = RUNBOOK.read_text(encoding="utf-8")
        policy = {
            "checks": [],
            "status_or_checks": [],
            "legacy_contexts": [],
            "sources": {"ruleset": True, "branch_protection": True},
        }

        evidence = _reconcile(text, policy=policy, runs=[])
        result = subprocess.run(
            ["jq", "-e", _reconciliation_guard(text)],
            input=json.dumps(evidence),
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert evidence["policy_requirement_count"] == 0


def test_failed_first_rearm_guard_cannot_delete_halt_marker(tmp_path: Path) -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    halt_file = tmp_path / "merge_executor.halt"
    halt_file.write_text("main_red\n", encoding="utf-8")
    tool_dir = _write_fake_rearm_tools(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "EXPECTED_CANDIDATE_SHA": "deadbeef",
            "PATH": f"{tool_dir}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        [
            "sh",
            "-euc",
            _rearm_shell_program(text),
            "sh",
            str(halt_file),
            "definitely-not-the-marker-hash",
            str(tmp_path),
            "deadbeef",
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert halt_file.read_text(encoding="utf-8") == "main_red\n"


def test_rearm_guard_deletes_unchanged_authorized_halt_marker(tmp_path: Path) -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    halt_file = tmp_path / "merge_executor.halt"
    halt_file.write_text("main_red\n", encoding="utf-8")
    expected_hash = hashlib.sha256(halt_file.read_bytes()).hexdigest()
    candidate_sha = "deadbeef"
    tool_dir = _write_fake_rearm_tools(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "EXPECTED_CANDIDATE_SHA": candidate_sha,
            "PATH": f"{tool_dir}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        [
            "sh",
            "-euc",
            _rearm_shell_program(text),
            "sh",
            str(halt_file),
            expected_hash,
            str(tmp_path),
            candidate_sha,
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert not halt_file.exists()


def test_rearm_guard_preserves_marker_changed_during_fetch(tmp_path: Path) -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    halt_file = tmp_path / "merge_executor.halt"
    halt_file.write_text("main_red\n", encoding="utf-8")
    expected_hash = hashlib.sha256(halt_file.read_bytes()).hexdigest()
    candidate_sha = "deadbeef"
    tool_dir = _write_fake_rearm_tools(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "EXPECTED_CANDIDATE_SHA": candidate_sha,
            "MUTATE_HALT_FILE": str(halt_file),
            "PATH": f"{tool_dir}:{env['PATH']}",
        }
    )

    result = subprocess.run(
        [
            "sh",
            "-euc",
            _rearm_shell_program(text),
            "sh",
            str(halt_file),
            expected_hash,
            str(tmp_path),
            candidate_sha,
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode != 0
    assert halt_file.read_text(encoding="utf-8") == "main_red_changed\n"
