"""Tests for ``scripts/settle_tier4_pr.py`` pure guard helpers."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest


def _load_module(script_name: str) -> Any:
    here = Path(__file__).resolve()
    script_path = here.parents[2] / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(f"{script_name}_under_test", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


settler = _load_module("settle_tier4_pr.py")
HEAD_COMMITTED_AT = "2026-05-22T00:00:00Z"
AUTH_CREATED_AT = "2026-05-22T00:05:00Z"


def _authorized_comment(
    head: str,
    *,
    association: str = "OWNER",
    author: str = "owner-user",
    include_branch_protection: bool = True,
) -> dict[str, Any]:
    branch_line = (
        "Authorized Action: branch_protection_reconcile on main\n"
        if include_branch_protection
        else ""
    )
    return {
        "authorAssociation": association,
        "author": {"login": author},
        "createdAt": AUTH_CREATED_AT,
        "url": "https://github.example/pr/7423#issuecomment-1",
        "body": (
            "Tier-4 Human Settlement Authorization\n"
            f"Authorized Head SHA: {head}\n"
            "Authorized Action: admin_squash_merge on PR #7423\n"
            f"{branch_line}"
        ),
    }


def _pr_view(
    head: str,
    *,
    comments: list[dict[str, Any]],
    human_settlement_state: str | None = "SUCCESS",
    human_settlement_creator: str | None = None,
    human_settlement_target_url: str = "https://github.example/pr/7423#issuecomment-1",
    extra_status_rollup: list[dict[str, Any]] | None = None,
    merge_state: str = "BLOCKED",
) -> dict[str, Any]:
    status_creator = human_settlement_creator
    if status_creator is None and comments:
        author = comments[0].get("author")
        if isinstance(author, dict):
            status_creator = str(author.get("login") or "").strip()
    if status_creator is None:
        status_creator = "owner-user"
    status_rollup = (
        [
            {
                "context": "aragora/human-settlement",
                "state": human_settlement_state,
                "creator": {"login": status_creator} if status_creator else {},
                "targetUrl": human_settlement_target_url,
            }
        ]
        if human_settlement_state is not None
        else []
    )
    status_rollup.extend(extra_status_rollup or [])
    return {
        "headRefOid": head,
        "state": "OPEN",
        "isDraft": False,
        "mergeStateStatus": merge_state,
        "headCommittedDate": HEAD_COMMITTED_AT,
        "comments": comments,
        "reviews": [],
        "statusCheckRollup": status_rollup,
    }


def _tier4_packet(
    pr: int = 7423,
    *,
    counted_reviewer_ids: list[str] | None = None,
    dogfood_evidence: list[dict[str, str]] | None = None,
    unresolved_dissent: bool = False,
) -> dict[str, Any]:
    return {
        "not_ready": [pr],
        "human_risk_settlement_required": [pr],
        "entries": [
            {
                "pr_number": pr,
                "status": "human_preapproval_required",
                "requires_human_risk_settlement": True,
                "unresolved_dissent": unresolved_dissent,
                "counted_reviewer_ids": (
                    ["codex", "grok"] if counted_reviewer_ids is None else counted_reviewer_ids
                ),
                "dogfood_evidence": (
                    [{"reviewer_id": "codex"}] if dogfood_evidence is None else dogfood_evidence
                ),
            }
        ],
    }


def _tier4_repair_packet_missing_settlement(pr: int = 7423) -> dict[str, Any]:
    packet = _tier4_packet(pr=pr)
    packet["not_ready"] = [pr]
    packet["entries"][0]["status"] = "repair_or_wait"
    packet["entries"][0]["verdict"] = "not_ready_for_settlement"
    packet["entries"][0]["requires_human_risk_settlement"] = True
    packet["entries"][0]["reasons"] = [
        "workflow/deploy/destructive surface touched",
        "checks are failing; repair before settlement",
    ]
    return packet


def test_json_read_gh_probe_prefers_app_auth_and_preserves_cwd(
    monkeypatch: Any, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_gh_subprocess_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(["gh", *args], 0, '{"ok": true}', "")

    monkeypatch.setattr(settler, "gh_subprocess_run", fake_gh_subprocess_run)

    payload = settler._run_json(["gh", "pr", "view", "7423"], cwd=tmp_path)

    assert payload == {"ok": True}
    assert calls == [
        {
            "args": ["pr", "view", "7423"],
            "cwd": tmp_path,
            "timeout": 120,
            "prefer_app": True,
            "write_op": False,
            "env": settler.os.environ,
        }
    ]


def test_current_gh_login_uses_user_auth_not_app_auth(monkeypatch: Any, tmp_path: Path) -> None:
    observed: list[dict[str, Any]] = []

    def fake_run_json(
        command: list[str],
        *,
        cwd: Path | None = None,
        prefer_app: bool = True,
        write_op: bool = False,
    ) -> dict[str, Any]:
        observed.append(
            {
                "command": command,
                "cwd": cwd,
                "prefer_app": prefer_app,
                "write_op": write_op,
            }
        )
        return {"login": "scarmani"}

    monkeypatch.setattr(settler, "_run_json", fake_run_json)

    assert settler._current_gh_login(cwd=tmp_path) == "scarmani"
    assert observed == [
        {
            "command": ["gh", "api", "user"],
            "cwd": tmp_path,
            "prefer_app": False,
            "write_op": False,
        }
    ]


def test_write_command_uses_user_auth_not_app_auth(monkeypatch: Any, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_gh_subprocess_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(["gh", *args], 0, "", "")

    monkeypatch.setattr(settler, "gh_subprocess_run", fake_gh_subprocess_run)

    settler._run_command(["gh", "pr", "comment", "7423", "--body", "settled"], cwd=tmp_path)

    assert calls == [
        {
            "args": ["pr", "comment", "7423", "--body", "settled"],
            "cwd": tmp_path,
            "timeout": 180,
            "prefer_app": True,
            "write_op": True,
            "env": settler.os.environ,
        }
    ]


def _valid_checks() -> list[dict[str, str]]:
    return [
        {"name": "lint", "state": "SUCCESS"},
        {"name": "aragora-merge-quorum", "state": "SUCCESS"},
    ]


def test_run_json_timeout_reports_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(settler, "gh_subprocess_run", None)
    monkeypatch.setattr(settler.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match=r"gh pr view 7423 timed out after 120s"):
        settler._run_json(["gh", "pr", "view", "7423"], cwd=Path.cwd())


def test_run_json_timeout_preserves_zero_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=0)

    monkeypatch.setattr(settler, "gh_subprocess_run", None)
    monkeypatch.setattr(settler.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match=r"gh pr view 7423 timed out after 0s"):
        settler._run_json(["gh", "pr", "view", "7423"], cwd=Path.cwd())


def test_run_json_any_timeout_preserves_zero_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=0)

    monkeypatch.setattr(settler, "gh_subprocess_run", None)
    monkeypatch.setattr(settler.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match=r"gh pr view 7423 timed out after 0s"):
        settler._run_json_any(["gh", "pr", "view", "7423"], cwd=Path.cwd())


def test_run_json_includes_stdout_json_error_when_command_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    command = [
        sys.executable,
        "-m",
        "aragora.cli.main",
        "review-queue",
        "merge-packet",
        "--json",
    ]

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert args[0] == command
        assert kwargs["cwd"] == tmp_path
        return subprocess.CompletedProcess(
            command,
            1,
            stdout='{"ok": false, "error": "merge-packet transport blocked"}\n',
            stderr="",
        )

    monkeypatch.setattr(settler.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="merge-packet transport blocked"):
        settler._run_json(command, cwd=tmp_path)


def test_main_json_reports_live_probe_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

    monkeypatch.setattr(settler, "gh_subprocess_run", None)
    monkeypatch.setattr(settler.subprocess, "run", fake_run)

    exit_code = settler.main(
        [
            "--check",
            "--pr",
            "7423",
            "--head",
            "57c740022e3c432718462efa12ca79f1df4f674d",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 2
    assert payload == {
        "error": "gh pr view 7423 --repo synaptent/aragora --json headRefOid,state,isDraft,mergeStateStatus,baseRefName,comments,reviews,commits,statusCheckRollup,url timed out after 120s",
        "ok": False,
    }


def _rest_pull(head: str) -> dict[str, Any]:
    return {
        "number": 7423,
        "title": "Tier 4 helper test",
        "html_url": "https://github.example/pr/7423",
        "state": "open",
        "draft": False,
        "merged_at": None,
        "mergeable": True,
        "mergeable_state": "clean",
        "head": {"sha": head, "ref": "codex/tier4-helper-test"},
        "base": {"sha": "base-sha", "ref": "main"},
        "user": {"login": "author-user"},
        "labels": [],
        "additions": 1,
        "deletions": 0,
        "changed_files": 1,
        "body": "",
    }


def _rest_authorized_comment(head: str) -> dict[str, Any]:
    comment = _authorized_comment(head)
    return {
        "user": {"login": comment["author"]["login"]},
        "author_association": comment["authorAssociation"],
        "created_at": comment["createdAt"],
        "html_url": comment["url"],
        "body": comment["body"],
    }


def _rest_commit(head: str) -> dict[str, Any]:
    return {
        "sha": head,
        "commit": {"author": {"date": HEAD_COMMITTED_AT}},
    }


def _rest_human_settlement_status() -> dict[str, Any]:
    return {
        "context": settler.HUMAN_SETTLEMENT_CONTEXT,
        "state": "success",
        "target_url": "https://github.example/pr/7423#issuecomment-1",
        "creator": {"login": "owner-user"},
        "created_at": AUTH_CREATED_AT,
        "updated_at": AUTH_CREATED_AT,
    }


def test_load_live_inputs_uses_rest_pr_view_when_graphql_is_rate_limited(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    def fake_run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        if command[:3] == ["gh", "pr", "view"]:
            raise RuntimeError("gh pr view 7423 failed: GraphQL: API rate limit already exceeded")
        if command[:4] == [sys.executable, "-m", "aragora.cli.main", "review-queue"]:
            return _tier4_packet()
        raise AssertionError(f"unexpected _run_json command: {command}")

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        if command[:3] == ["gh", "pr", "checks"]:
            return _valid_checks()
        if command[:2] != ["gh", "api"]:
            raise AssertionError(f"unexpected _run_json_any command: {command}")
        endpoint = command[2]
        if endpoint == "repos/synaptent/aragora/pulls/7423":
            return _rest_pull(head)
        if endpoint.startswith("repos/synaptent/aragora/pulls/7423/files"):
            return []
        if endpoint.startswith("repos/synaptent/aragora/issues/7423/comments"):
            return [_rest_authorized_comment(head)]
        if endpoint.startswith("repos/synaptent/aragora/pulls/7423/reviews"):
            return []
        if endpoint.startswith("repos/synaptent/aragora/pulls/7423/commits"):
            return [_rest_commit(head)]
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/statuses"):
            return [_rest_human_settlement_status()]
        raise AssertionError(f"unexpected REST endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json", fake_run_json)
    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    pr_view, merge_packet, required_checks = settler._load_live_inputs(
        7423,
        cwd=tmp_path,
        repo="synaptent/aragora",
    )

    assert pr_view["headRefOid"] == head
    assert pr_view["comments"][0]["authorAssociation"] == "OWNER"
    assert pr_view["commitStatuses"][0]["context"] == settler.HUMAN_SETTLEMENT_CONTEXT
    assert pr_view["commitStatuses"][0]["creator"] == {"login": "owner-user"}
    assert pr_view["mergeStateStatus"] == "CLEAN"
    assert merge_packet["entries"][0]["pr_number"] == 7423
    assert required_checks == _valid_checks()
    gate = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=merge_packet,
        required_checks=required_checks,
    )
    assert gate["ok"] is True


def test_rest_normalized_human_status_without_creator_fails_closed() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    status = _rest_human_settlement_status()
    status.pop("creator")
    pr_view = _pr_view(head, comments=[_authorized_comment(head)], human_settlement_state=None)
    pr_view["commitStatuses"] = [settler._normalize_rest_status_for_gate(status)]

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "untrusted or unbound aragora/human-settlement status" in result["blockers"]


def test_load_live_inputs_uses_rest_required_checks_when_graphql_checks_rate_limited(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    packet = _tier4_packet()

    def fake_run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        if command[:3] == ["gh", "pr", "view"]:
            return _pr_view(head, comments=[_authorized_comment(head)])
        if command[:4] == [sys.executable, "-m", "aragora.cli.main", "review-queue"]:
            return packet
        raise AssertionError(f"unexpected _run_json command: {command}")

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        if command[:3] == ["gh", "pr", "checks"]:
            raise RuntimeError("gh pr checks 7423 failed: GraphQL: API rate limit already exceeded")
        if command[:2] != ["gh", "api"]:
            raise AssertionError(f"unexpected _run_json_any command: {command}")
        endpoint = command[2]
        if endpoint == "repos/synaptent/aragora/branches/main/protection/required_status_checks":
            return {
                "strict": False,
                "checks": [
                    {"context": "lint", "app_id": 15368},
                    {"context": "aragora-merge-quorum", "app_id": 15368},
                ],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/check-runs"):
            return {
                "total_count": 2,
                "check_runs": [
                    {
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "success",
                        "completed_at": AUTH_CREATED_AT,
                        "app": {"id": 15368},
                    },
                    {
                        "name": "aragora-merge-quorum",
                        "status": "completed",
                        "conclusion": "success",
                        "completed_at": AUTH_CREATED_AT,
                        "app": {"id": 15368},
                    },
                ],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/statuses"):
            return []
        raise AssertionError(f"unexpected _run_json_any command: {command}")

    monkeypatch.setattr(settler, "_run_json", fake_run_json)
    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    pr_view, merge_packet, required_checks = settler._load_live_inputs(
        7423,
        cwd=tmp_path,
        repo="synaptent/aragora",
    )

    assert merge_packet is packet
    assert required_checks == [
        {"name": "lint", "state": "SUCCESS"},
        {"name": "aragora-merge-quorum", "state": "SUCCESS"},
    ]
    gate = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=merge_packet,
        required_checks=required_checks,
    )
    assert gate["ok"] is True


def test_load_live_inputs_fills_missing_required_check_rows_from_direct_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    def fake_run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        if command[:3] == ["gh", "pr", "view"]:
            return {
                "headRefOid": head,
                "state": "OPEN",
                "isDraft": False,
                "mergeStateStatus": "BLOCKED",
                "baseRefName": "main",
                "comments": [],
                "reviews": [],
                "commits": [],
                "statusCheckRollup": [],
                "url": "https://github.example/pr/7423",
            }
        if command[:4] == [sys.executable, "-m", "aragora.cli.main", "review-queue"]:
            return _tier4_packet()
        raise AssertionError(f"unexpected _run_json command: {command}")

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        if command[:4] == ["gh", "pr", "checks", "7423"]:
            return [{"name": "lint", "state": "SUCCESS"}]
        if command[:2] != ["gh", "api"]:
            raise AssertionError(f"unexpected _run_json_any command: {command}")
        endpoint = command[2]
        if endpoint == "repos/example/project/branches/main/protection/required_status_checks":
            return {
                "strict": False,
                "contexts": [],
                "checks": [
                    {"context": "lint", "app_id": 15368},
                    {"context": "aragora-merge-quorum", "app_id": 15368},
                ],
            }
        if endpoint.startswith(f"repos/example/project/commits/{head}/check-runs"):
            return {
                "total_count": 2,
                "check_runs": [
                    {
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 15368},
                    },
                    {
                        "name": "aragora-merge-quorum",
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 15368},
                    },
                ],
            }
        if endpoint.startswith(f"repos/example/project/commits/{head}/statuses"):
            return []
        raise AssertionError(f"unexpected REST endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json", fake_run_json)
    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    _, _, required_checks = settler._load_live_inputs(7423, cwd=tmp_path, repo="example/project")

    assert required_checks == [
        {"name": "lint", "state": "SUCCESS"},
        {
            "name": "aragora-merge-quorum",
            "state": "SUCCESS",
            "workflow": "direct required check-run fallback",
            "source": "direct_commit_check_run",
        },
    ]


def test_direct_required_check_fallback_preserves_strict_freshness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        endpoint = command[2]
        if endpoint == "repos/synaptent/aragora/branches/main/protection/required_status_checks":
            return {
                "strict": True,
                "contexts": [],
                "checks": [{"context": "lint", "app_id": 15368}],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/check-runs"):
            return {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 15368},
                    }
                ],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/statuses"):
            return []
        if endpoint == f"repos/synaptent/aragora/compare/main...{head}":
            return {"status": "ahead"}
        raise AssertionError(f"unexpected REST endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    checks = settler._required_checks_with_direct_fallback(
        [],
        _pr_view(head, comments=[]),
        cwd=tmp_path,
        repo="synaptent/aragora",
    )

    assert checks == [
        {"name": "lint", "state": "SUCCESS"},
        {"name": "strict branch-protection freshness", "state": "SUCCESS"},
    ]


def test_strict_fallback_preserves_existing_failing_required_checks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        endpoint = command[2]
        if endpoint == "repos/synaptent/aragora/branches/main/protection/required_status_checks":
            return {
                "strict": True,
                "contexts": [],
                "checks": [{"context": "lint", "app_id": 15368}],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/check-runs"):
            return {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 15368},
                    }
                ],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/statuses"):
            return []
        if endpoint == f"repos/synaptent/aragora/compare/main...{head}":
            return {"status": "ahead"}
        raise AssertionError(f"unexpected REST endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    required_checks = settler._required_checks_with_direct_fallback(
        [{"name": "ruleset-required", "state": "FAILURE"}],
        _pr_view(head, comments=[]),
        cwd=tmp_path,
        repo="synaptent/aragora",
    )

    assert required_checks == [
        {"name": "ruleset-required", "state": "FAILURE"},
        {"name": "lint", "state": "SUCCESS"},
        {"name": "strict branch-protection freshness", "state": "SUCCESS"},
    ]
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head)]),
        merge_packet=_tier4_packet(),
        required_checks=required_checks,
    )
    assert result["ok"] is False
    assert "required check ruleset-required is FAILURE" in result["blockers"]


def test_direct_required_check_fallback_does_not_treat_completed_without_conclusion_as_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        endpoint = command[2]
        if endpoint == "repos/synaptent/aragora/branches/main/protection/required_status_checks":
            return {
                "strict": False,
                "contexts": [],
                "checks": [{"context": "lint", "app_id": 15368}],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/check-runs"):
            return {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "",
                        "app": {"id": 15368},
                    }
                ],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/statuses"):
            return []
        raise AssertionError(f"unexpected REST endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    required_checks = settler._required_checks_with_direct_fallback(
        [],
        _pr_view(head, comments=[]),
        cwd=tmp_path,
        repo="synaptent/aragora",
    )

    assert required_checks == [
        {
            "name": "lint",
            "state": "UNKNOWN",
            "workflow": "direct required check-run fallback",
            "source": "direct_commit_check_run",
        }
    ]
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head)]),
        merge_packet=_tier4_packet(),
        required_checks=required_checks,
    )
    assert result["ok"] is False
    assert "required check lint is UNKNOWN" in result["blockers"]


def test_rate_limited_required_checks_fail_closed_without_rest_protection_surface(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    packet = _tier4_packet()

    def fake_run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        if command[:3] == ["gh", "pr", "view"]:
            return _pr_view(head, comments=[_authorized_comment(head)])
        if command[:4] == [sys.executable, "-m", "aragora.cli.main", "review-queue"]:
            return packet
        raise AssertionError(f"unexpected _run_json command: {command}")

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        if command[:3] == ["gh", "pr", "checks"]:
            raise RuntimeError("gh pr checks 7423 failed: GraphQL: API rate limit already exceeded")
        if command[:3] == [
            "gh",
            "api",
            "repos/synaptent/aragora/branches/main/protection/required_status_checks",
        ]:
            raise RuntimeError("branch protection unavailable")
        raise AssertionError(f"unexpected _run_json_any command: {command}")

    monkeypatch.setattr(settler, "_run_json", fake_run_json)
    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    pr_view, merge_packet, required_checks = settler._load_live_inputs(
        7423,
        cwd=tmp_path,
        repo="synaptent/aragora",
    )

    assert required_checks == []
    gate = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=merge_packet,
        required_checks=required_checks,
    )
    assert gate["ok"] is False
    assert settler.REQUIRED_CHECKS_BLOCKER in gate["blockers"]


def test_load_live_inputs_does_not_rest_fallback_for_non_rate_limit_graphql_error(
    monkeypatch: Any, tmp_path: Path
) -> None:
    def fake_run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        if command[:3] == ["gh", "pr", "view"]:
            raise RuntimeError("gh pr view 7423 failed: GraphQL: field unavailable")
        raise AssertionError(f"unexpected _run_json command: {command}")

    monkeypatch.setattr(settler, "_run_json", fake_run_json)

    with pytest.raises(RuntimeError, match="field unavailable"):
        settler._load_live_inputs(7423, cwd=tmp_path, repo="synaptent/aragora")


def test_load_live_inputs_does_not_rest_fallback_for_rest_rate_limit_error(
    monkeypatch: Any, tmp_path: Path
) -> None:
    def fake_run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        if command[:3] == ["gh", "pr", "view"]:
            raise RuntimeError("gh api failed: REST API rate limit exceeded")
        raise AssertionError(f"unexpected _run_json command: {command}")

    monkeypatch.setattr(settler, "_run_json", fake_run_json)

    with pytest.raises(RuntimeError, match="REST API rate limit exceeded"):
        settler._load_live_inputs(7423, cwd=tmp_path, repo="synaptent/aragora")


def test_gh_pr_rate_limit_without_graphql_word_still_uses_rest_fallback(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    def fake_run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        if command[:3] == ["gh", "pr", "view"]:
            raise RuntimeError("gh pr view 7423 failed: API rate limit exceeded")
        if command[:4] == [sys.executable, "-m", "aragora.cli.main", "review-queue"]:
            return _tier4_packet()
        raise AssertionError(f"unexpected _run_json command: {command}")

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        if command[:3] == ["gh", "pr", "checks"]:
            return _valid_checks()
        if command[:2] != ["gh", "api"]:
            raise AssertionError(f"unexpected _run_json_any command: {command}")
        endpoint = command[2]
        if endpoint == "repos/synaptent/aragora/pulls/7423":
            return _rest_pull(head)
        if endpoint.startswith("repos/synaptent/aragora/pulls/7423/files"):
            return []
        if endpoint.startswith("repos/synaptent/aragora/issues/7423/comments"):
            return [_rest_authorized_comment(head)]
        if endpoint.startswith("repos/synaptent/aragora/pulls/7423/reviews"):
            return []
        if endpoint.startswith("repos/synaptent/aragora/pulls/7423/commits"):
            return [_rest_commit(head)]
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/statuses"):
            return [_rest_human_settlement_status()]
        raise AssertionError(f"unexpected REST endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json", fake_run_json)
    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    pr_view, _, _ = settler._load_live_inputs(7423, cwd=tmp_path, repo="synaptent/aragora")

    assert pr_view["headRefOid"] == head
    assert pr_view["_rest_fallback"]["enabled"] is True


def test_rest_required_checks_prove_strict_branch_freshness(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        endpoint = command[2]
        if endpoint == "repos/synaptent/aragora/branches/main/protection/required_status_checks":
            return {
                "strict": True,
                "checks": [{"context": "lint", "app_id": 15368}],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/check-runs"):
            return {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 15368},
                    }
                ],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/statuses"):
            return []
        if endpoint == f"repos/synaptent/aragora/compare/main...{head}":
            return {"status": "ahead"}
        raise AssertionError(f"unexpected REST endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    checks = settler._required_checks_from_rest(
        _pr_view(head, comments=[]),
        cwd=tmp_path,
        repo="synaptent/aragora",
    )

    assert checks == [
        {"name": "lint", "state": "SUCCESS"},
        {"name": "strict branch-protection freshness", "state": "SUCCESS"},
    ]


def test_rest_required_checks_fail_closed_when_strict_branch_is_stale(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        endpoint = command[2]
        if endpoint == "repos/synaptent/aragora/branches/main/protection/required_status_checks":
            return {
                "strict": True,
                "checks": [{"context": "lint", "app_id": 15368}],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/check-runs"):
            return {
                "total_count": 1,
                "check_runs": [
                    {
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "success",
                        "app": {"id": 15368},
                    }
                ],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/statuses"):
            return []
        if endpoint == f"repos/synaptent/aragora/compare/main...{head}":
            return {"status": "diverged"}
        raise AssertionError(f"unexpected REST endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    checks = settler._required_checks_from_rest(
        _pr_view(head, comments=[]),
        cwd=tmp_path,
        repo="synaptent/aragora",
    )

    assert checks[-1] == {"name": "strict branch-protection freshness", "state": "FAILURE"}


def test_rest_required_checks_surface_visibility_fetch_failure(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        endpoint = command[2]
        if endpoint == "repos/synaptent/aragora/branches/main/protection/required_status_checks":
            return {
                "strict": False,
                "checks": [{"context": "lint", "app_id": 15368}],
            }
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/check-runs"):
            raise RuntimeError("check-runs unavailable")
        if endpoint.startswith(f"repos/synaptent/aragora/commits/{head}/statuses"):
            return []
        raise AssertionError(f"unexpected REST endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    checks = settler._required_checks_from_rest(
        _pr_view(head, comments=[]),
        cwd=tmp_path,
        repo="synaptent/aragora",
    )

    assert checks[0] == {"name": settler.REQUIRED_CHECK_REST_VISIBILITY_CONTEXT, "state": "UNKNOWN"}
    assert {"name": "lint", "state": "PENDING"} in checks


def _valid_branch_protection_snapshot() -> dict[str, dict[str, Any]]:
    return {
        "branch_protection": {
            "required_pull_request_reviews": {"url": "https://github.example/reviews"},
            "required_status_checks": {"url": "https://github.example/checks"},
            "enforce_admins": {"enabled": True},
        },
        "required_pull_request_reviews": {
            "required_approving_review_count": 0,
            "require_code_owner_reviews": False,
        },
        "required_status_checks": {"strict": False, "contexts": ["lint"]},
        "enforce_admins": {"enabled": True},
    }


def test_missing_operator_comment_blocks_settlement() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[{"body": "looks good"}]),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "missing repo-visible Tier 4 operator settlement comment" in result["blockers"]


def test_exact_head_operator_comment_allows_check_result() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, include_branch_protection=False)],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_graphql_unknown_mergeability_does_not_block_check_result() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, include_branch_protection=False)],
            merge_state="UNKNOWN",
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_rest_unknown_mergeability_blocks_check_result() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    pr_view = _pr_view(
        head,
        comments=[_authorized_comment(head, include_branch_protection=False)],
        merge_state="UNKNOWN",
    )
    pr_view["_rest_fallback"] = {"enabled": True}
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "PR #7423 mergeability is UNKNOWN" in result["blockers"]


def test_rest_unknown_mergeability_blocks_settlement_preconditions() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    pr_view = _pr_view(head, comments=[], human_settlement_state=None, merge_state="UNKNOWN")
    pr_view["_rest_fallback"] = {"enabled": True}
    result = settler.evaluate_tier4_settlement_preconditions(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "PR #7423 mergeability is UNKNOWN" in result["blockers"]


def test_member_operator_comment_with_status_and_evidence_allows_check_result() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[
                _authorized_comment(
                    head,
                    association="MEMBER",
                    author="trusted-member",
                    include_branch_protection=False,
                )
            ],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        trusted_operator_logins=["trusted-member"],
        permission_checker=lambda login: login == "trusted-member",
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_operator_comment_without_human_status_does_not_authorize() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head)],
            human_settlement_state=None,
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "missing or unsuccessful aragora/human-settlement status" in result["blockers"]
    assert "missing repo-visible Tier 4 operator settlement comment" not in result["blockers"]


def test_human_status_target_url_must_match_accepted_operator_comment() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head)],
            human_settlement_target_url="https://github.example/pr/7423#issuecomment-stale",
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "untrusted or unbound aragora/human-settlement status" in result["blockers"]
    assert "missing repo-visible Tier 4 operator settlement comment" not in result["blockers"]


def test_human_status_creator_must_match_accepted_operator_comment_author() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head)],
            human_settlement_creator="github-actions",
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "untrusted or unbound aragora/human-settlement status" in result["blockers"]
    assert "missing repo-visible Tier 4 operator settlement comment" not in result["blockers"]


def test_duplicate_rest_and_rollup_human_success_authorizes() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    pr_view = _pr_view(head, comments=[_authorized_comment(head)])
    pr_view["commitStatuses"] = [
        {
            "context": settler.HUMAN_SETTLEMENT_CONTEXT,
            "state": "success",
            "creator": {"login": "owner-user"},
            "target_url": "https://github.example/pr/7423#issuecomment-1",
            "updated_at": "2026-05-22T00:06:00Z",
        }
    ]

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_direct_rest_human_status_authorizes_with_incomplete_started_at_rollup() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    pr_view = _pr_view(
        head,
        comments=[_authorized_comment(head)],
        human_settlement_state=None,
    )
    pr_view["statusCheckRollup"] = [
        {
            "context": settler.HUMAN_SETTLEMENT_CONTEXT,
            "state": "SUCCESS",
            "startedAt": "2026-05-22T00:06:00Z",
        }
    ]
    pr_view["commitStatuses"] = [
        settler._normalize_rest_status_for_gate(_rest_human_settlement_status())
    ]

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_newer_pending_human_status_blocks_older_success() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    pr_view = _pr_view(head, comments=[_authorized_comment(head)])
    pr_view["statusCheckRollup"][0]["updatedAt"] = "2026-05-22T00:04:00Z"
    pr_view["commitStatuses"] = [
        {
            "context": settler.HUMAN_SETTLEMENT_CONTEXT,
            "state": "pending",
            "creator": {"login": "owner-user"},
            "target_url": "https://github.example/pr/7423#issuecomment-1",
            "updatedAt": "2026-05-22T00:06:00Z",
        }
    ]

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert settler.HUMAN_SETTLEMENT_STATUS_BLOCKER in result["blockers"]


def test_newer_bound_human_success_authorizes_despite_older_pending() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    pr_view = _pr_view(head, comments=[_authorized_comment(head)])
    pr_view["statusCheckRollup"][0]["state"] = "PENDING"
    pr_view["statusCheckRollup"][0]["updatedAt"] = "2026-05-22T00:04:00Z"
    pr_view["commitStatuses"] = [
        {
            "context": settler.HUMAN_SETTLEMENT_CONTEXT,
            "state": "success",
            "creator": {"login": "owner-user"},
            "target_url": "https://github.example/pr/7423#issuecomment-1",
            "updatedAt": "2026-05-22T00:06:00Z",
        }
    ]

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_conflicting_human_statuses_without_timestamps_fail_closed() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    pr_view = _pr_view(head, comments=[_authorized_comment(head)])
    pr_view["commitStatuses"] = [
        {
            "context": settler.HUMAN_SETTLEMENT_CONTEXT,
            "state": "pending",
            "creator": {"login": "owner-user"},
            "target_url": "https://github.example/pr/7423#issuecomment-1",
        }
    ]

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert settler.HUMAN_SETTLEMENT_STATUS_BLOCKER in result["blockers"]


def test_human_status_bound_to_accepted_operator_comment_authorizes() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, author="trusted-member", association="MEMBER")],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        trusted_operator_logins=["trusted-member"],
        permission_checker=lambda login: login == "trusted-member",
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_operator_comment_without_counted_evidence_does_not_authorize() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head)]),
        merge_packet=_tier4_packet(counted_reviewer_ids=["codex"]),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "missing Tier 4 model/dogfood settlement evidence" in result["blockers"]
    assert "missing repo-visible Tier 4 operator settlement comment" not in result["blockers"]


def test_missing_required_checks_report_distinct_blocker() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head)]),
        merge_packet=_tier4_packet(),
        required_checks=[],
    )

    assert result["ok"] is False
    assert "required checks are missing" in result["blockers"]
    assert "missing repo-visible Tier 4 operator settlement comment" not in result["blockers"]


def test_branch_protection_mode_requires_branch_protection_token() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, include_branch_protection=False)],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        require_branch_protection_token=True,
    )

    assert result["ok"] is False
    assert "missing repo-visible Tier 4 operator settlement comment" in result["blockers"]


def test_branch_protection_mode_accepts_branch_protection_token() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head)]),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        require_branch_protection_token=True,
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_numeric_not_ready_is_allowed_when_packet_marks_tier4_human_settlement() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, include_branch_protection=False)],
        ),
        merge_packet=_tier4_packet(),
        required_checks=[{"name": "lint", "state": "SUCCESS"}],
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_draft_tier4_preapproval_numeric_not_ready_is_diagnostic_only() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    packet = _tier4_packet()
    packet["entries"][0]["status"] = "repair_or_wait"
    packet["entries"][0]["verdict"] = "not_ready_for_settlement"
    packet["entries"][0]["requires_human_risk_settlement"] = True
    packet["entries"][0]["requires_human_preapproval"] = True
    packet["human_risk_settlement_required"] = []
    pr_view = _pr_view(
        head,
        comments=[_authorized_comment(head, include_branch_protection=False)],
    )
    pr_view["isDraft"] = True

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=pr_view,
        merge_packet=packet,
        required_checks=[{"name": "lint", "state": "SUCCESS"}],
    )

    assert result["ok"] is False
    assert result["blockers"] == ["PR #7423 is draft"]


def test_non_draft_repair_or_wait_preapproval_not_ready_is_unexpected() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    packet = _tier4_packet()
    packet["entries"][0]["status"] = "repair_or_wait"
    packet["entries"][0]["verdict"] = "not_ready_for_settlement"
    packet["entries"][0]["requires_human_risk_settlement"] = True
    packet["entries"][0]["requires_human_preapproval"] = True
    packet["human_risk_settlement_required"] = []

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, include_branch_protection=False)],
        ),
        merge_packet=packet,
        required_checks=[{"name": "lint", "state": "SUCCESS"}],
    )

    assert result["ok"] is False
    assert "merge-packet has unexpected blockers: 7423" in result["blockers"]


def test_untrusted_author_comment_does_not_authorize() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, association="CONTRIBUTOR")],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "missing repo-visible Tier 4 operator settlement comment" in result["blockers"]


def test_untrusted_member_comment_does_not_authorize() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, association="MEMBER", author="random-member")],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "missing repo-visible Tier 4 operator settlement comment" in result["blockers"]


def test_configured_trusted_member_comment_authorizes(monkeypatch: Any) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    monkeypatch.setenv("ARAGORA_TIER4_TRUSTED_OPERATORS", "trusted-member")
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, association="MEMBER", author="trusted-member")],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        permission_checker=lambda login: login == "trusted-member",
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_configured_trusted_member_permission_check_runs_once(monkeypatch: Any) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    checked_logins: list[str] = []
    monkeypatch.setenv("ARAGORA_TIER4_TRUSTED_OPERATORS", "trusted-member")

    def permission_checker(login: str) -> bool:
        checked_logins.append(login)
        return login == "trusted-member"

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, association="MEMBER", author="trusted-member")],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        permission_checker=permission_checker,
    )

    assert result["ok"] is True
    assert checked_logins == ["trusted-member"]


def test_trusted_member_comment_requires_admin_permission(monkeypatch: Any) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    monkeypatch.setenv("ARAGORA_TIER4_TRUSTED_OPERATORS", "trusted-member")
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, association="MEMBER", author="trusted-member")],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        permission_checker=lambda login: False,
    )

    assert result["ok"] is False
    assert "missing repo-visible Tier 4 operator settlement comment" in result["blockers"]


def test_admin_member_comment_does_not_require_explicit_allowlist() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[_authorized_comment(head, association="MEMBER", author="an0mium")],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        permission_checker=lambda login: login == "an0mium",
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_allowlisted_admin_collaborator_comment_authorizes() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[
                _authorized_comment(
                    head,
                    association="COLLABORATOR",
                    author="trusted-admin",
                )
            ],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        trusted_operator_logins=["trusted-admin"],
        permission_checker=lambda login: login == "trusted-admin",
    )

    assert result["ok"] is True
    assert result["blockers"] == []
    diagnostic = result["authorization_diagnostics"][0]
    assert diagnostic["accepted"] is True
    assert diagnostic["admin_permission_required"] is True
    assert diagnostic["admin_permission_evaluated"] is True


def test_collaborator_comment_requires_explicit_allowlist() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[
                _authorized_comment(
                    head,
                    association="COLLABORATOR",
                    author="admin-collaborator",
                )
            ],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        permission_checker=lambda login: login == "admin-collaborator",
    )

    assert result["ok"] is False
    assert "missing repo-visible Tier 4 operator settlement comment" in result["blockers"]
    assert result["authorization_diagnostics"][0]["rejection_reasons"] == [
        "COLLABORATOR login admin-collaborator requires explicit trusted operator allowlist"
    ]


def test_allowlisted_collaborator_comment_requires_admin_permission() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[
                _authorized_comment(
                    head,
                    association="COLLABORATOR",
                    author="trusted-collaborator",
                )
            ],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        trusted_operator_logins=["trusted-collaborator"],
        permission_checker=lambda login: False,
    )

    assert result["ok"] is False
    assert "missing repo-visible Tier 4 operator settlement comment" in result["blockers"]
    assert result["authorization_diagnostics"][0]["rejection_reasons"] == [
        "trusted collaborator trusted-collaborator lacks admin permission"
    ]


def test_cli_trusted_operator_login_authorizes_member_comment(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(
                head,
                comments=[_authorized_comment(head, association="MEMBER", author="trusted-member")],
            ),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(
        settler,
        "_login_has_admin_permission",
        lambda login, repo, cwd: login == "trusted-member",
    )
    monkeypatch.setattr(
        settler,
        "_preflight_branch_protection_reconcile",
        lambda repo, cwd: None,
    )

    rc = settler.main(
        [
            "--check",
            "--pr",
            "7423",
            "--head",
            head,
            "--trusted-operator-login",
            "trusted-member",
            "--cwd",
            str(tmp_path),
        ]
    )

    assert rc == 0


def test_cli_check_uses_rest_fallback_when_pr_view_and_checks_hit_graphql_limit(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    comment = _authorized_comment(head, include_branch_protection=False)
    api_calls: list[str] = []

    def fake_run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        if command[:3] == ["gh", "pr", "view"]:
            assert "--repo" in command
            assert command[command.index("--repo") + 1] == "synaptent/aragora"
            raise RuntimeError("gh pr view 7423 failed: GraphQL: API rate limit already exceeded")
        if command[:4] == [
            sys.executable,
            "-m",
            "aragora.cli.main",
            "review-queue",
        ]:
            return _tier4_packet()
        raise AssertionError(f"unexpected JSON command: {command}")

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        if command[:3] == ["gh", "pr", "checks"]:
            assert "--repo" in command
            assert command[command.index("--repo") + 1] == "synaptent/aragora"
            raise RuntimeError("gh pr checks 7423 failed: GraphQL: API rate limit already exceeded")
        if command[:2] != ["gh", "api"]:
            raise AssertionError(f"unexpected JSON command: {command}")
        endpoint = command[2]
        api_calls.append(endpoint)
        if endpoint == "repos/synaptent/aragora/pulls/7423":
            return {
                "number": 7423,
                "title": "Tier 4 fallback probe",
                "html_url": "https://github.com/synaptent/aragora/pull/7423",
                "state": "open",
                "merged_at": None,
                "merge_commit_sha": "",
                "draft": False,
                "mergeable": True,
                "mergeable_state": "clean",
                "user": {"login": "an0mium"},
                "head": {"ref": "codex/tier4-fallback-probe", "sha": head},
                "base": {"ref": "main", "sha": "base-sha"},
                "labels": [],
                "additions": 1,
                "deletions": 0,
                "changed_files": 1,
                "body": "",
            }
        if endpoint == "repos/synaptent/aragora/pulls/7423/files?per_page=100":
            return [{"filename": "scripts/settle_tier4_pr.py"}]
        if endpoint == "repos/synaptent/aragora/issues/7423/comments?per_page=100":
            return [
                {
                    "user": {"login": "owner-user"},
                    "author_association": "OWNER",
                    "body": comment["body"],
                    "created_at": AUTH_CREATED_AT,
                    "html_url": "https://github.example/pr/7423#issuecomment-1",
                }
            ]
        if endpoint == "repos/synaptent/aragora/pulls/7423/reviews?per_page=100":
            return []
        if endpoint == "repos/synaptent/aragora/pulls/7423/commits?per_page=100":
            return [
                {
                    "sha": head,
                    "commit": {"author": {"date": HEAD_COMMITTED_AT}},
                }
            ]
        if endpoint == f"repos/synaptent/aragora/commits/{head}/statuses?per_page=100":
            return [
                {
                    "context": "aragora/human-settlement",
                    "state": "success",
                    "target_url": "https://github.example/pr/7423#issuecomment-1",
                    "creator": {"login": "owner-user"},
                    "created_at": AUTH_CREATED_AT,
                    "updated_at": AUTH_CREATED_AT,
                }
            ]
        if endpoint == "repos/synaptent/aragora/branches/main/protection/required_status_checks":
            return {
                "contexts": ["lint", "aragora-merge-quorum"],
                "checks": [
                    {"context": "lint", "app_id": None},
                    {"context": "aragora-merge-quorum", "app_id": None},
                ],
                "strict": False,
            }
        if endpoint == f"repos/synaptent/aragora/commits/{head}/check-runs?per_page=100":
            return {
                "check_runs": [
                    {
                        "name": "lint",
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.example/actions/lint",
                    },
                    {
                        "name": "aragora-merge-quorum",
                        "status": "completed",
                        "conclusion": "success",
                        "html_url": "https://github.example/actions/quorum",
                    },
                ]
            }
        raise AssertionError(f"unexpected gh api endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json", fake_run_json)
    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    rc = settler.main(
        [
            "--check",
            "--pr",
            "7423",
            "--head",
            head,
            "--repo",
            "synaptent/aragora",
            "--cwd",
            str(tmp_path),
            "--json",
        ]
    )

    assert rc == 0
    payload = settler.json.loads(capsys.readouterr().out)
    gate = payload["gate"]
    assert gate["ok"] is True
    assert gate["actual_head"] == head
    assert gate["blockers"] == []
    assert gate["authorization_diagnostics"][0]["authorAssociation"] == "OWNER"
    assert f"repos/synaptent/aragora/commits/{head}/check-runs?per_page=100" in api_calls


def test_rest_fallback_reports_strict_branch_protection_required_contexts(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    comment = _authorized_comment(head, include_branch_protection=False)

    def fake_run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        if command[:3] == ["gh", "pr", "view"]:
            raise RuntimeError("gh pr view 7423 failed: GraphQL: API rate limit already exceeded")
        if command[:4] == [
            sys.executable,
            "-m",
            "aragora.cli.main",
            "review-queue",
        ]:
            return _tier4_packet()
        raise AssertionError(f"unexpected JSON command: {command}")

    def fake_run_json_any(command: list[str], *, cwd: Path | None = None) -> Any:
        if command[:3] == ["gh", "pr", "checks"]:
            raise RuntimeError("gh pr checks 7423 failed: GraphQL: API rate limit already exceeded")
        if command[:2] != ["gh", "api"]:
            raise AssertionError(f"unexpected JSON command: {command}")
        endpoint = command[2]
        if endpoint == "repos/synaptent/aragora/pulls/7423":
            return {
                "number": 7423,
                "title": "Tier 4 fallback probe",
                "html_url": "https://github.com/synaptent/aragora/pull/7423",
                "state": "open",
                "merged_at": None,
                "merge_commit_sha": "",
                "draft": False,
                "mergeable": True,
                "mergeable_state": "clean",
                "user": {"login": "an0mium"},
                "head": {"ref": "codex/tier4-fallback-probe", "sha": head},
                "base": {"ref": "main", "sha": "base-sha"},
                "labels": [],
                "additions": 1,
                "deletions": 0,
                "changed_files": 1,
                "body": "",
            }
        if endpoint == "repos/synaptent/aragora/pulls/7423/files?per_page=100":
            return [{"filename": "scripts/settle_tier4_pr.py"}]
        if endpoint == "repos/synaptent/aragora/issues/7423/comments?per_page=100":
            return [
                {
                    "user": {"login": "owner-user"},
                    "author_association": "OWNER",
                    "body": comment["body"],
                    "created_at": AUTH_CREATED_AT,
                    "html_url": "https://github.example/pr/7423#issuecomment-1",
                }
            ]
        if endpoint == "repos/synaptent/aragora/pulls/7423/reviews?per_page=100":
            return []
        if endpoint == "repos/synaptent/aragora/pulls/7423/commits?per_page=100":
            return [{"sha": head, "commit": {"author": {"date": HEAD_COMMITTED_AT}}}]
        if endpoint == f"repos/synaptent/aragora/commits/{head}/statuses?per_page=100":
            return [
                {
                    "context": "aragora/human-settlement",
                    "state": "success",
                    "target_url": "https://github.example/pr/7423#issuecomment-1",
                    "creator": {"login": "owner-user"},
                    "created_at": AUTH_CREATED_AT,
                    "updated_at": AUTH_CREATED_AT,
                }
            ]
        if endpoint == "repos/synaptent/aragora/branches/main/protection/required_status_checks":
            return {
                "contexts": ["lint", "aragora-merge-quorum"],
                "checks": [
                    {"context": "lint", "app_id": None},
                    {"context": "aragora-merge-quorum", "app_id": None},
                ],
                "strict": True,
            }
        raise AssertionError(f"unexpected gh api endpoint: {endpoint}")

    monkeypatch.setattr(settler, "_run_json", fake_run_json)
    monkeypatch.setattr(settler, "_run_json_any", fake_run_json_any)

    rc = settler.main(
        [
            "--check",
            "--pr",
            "7423",
            "--head",
            head,
            "--repo",
            "synaptent/aragora",
            "--cwd",
            str(tmp_path),
            "--json",
        ]
    )

    assert rc == 1
    payload = settler.json.loads(capsys.readouterr().out)
    gate = payload["gate"]
    assert gate["ok"] is False
    assert "required check required check REST visibility is UNKNOWN" in gate["blockers"]
    assert "required check lint is PENDING" in gate["blockers"]
    assert "required check aragora-merge-quorum is PENDING" in gate["blockers"]
    assert not any("STRICT_BASE_REQUIRED" in blocker for blocker in gate["blockers"])


def test_collaborator_permission_payload_only_treats_admin_as_admin() -> None:
    assert settler._collaborator_permission_is_admin({"permission": "admin"}) is True
    assert settler._collaborator_permission_is_admin({"role_name": "admin"}) is True
    for permission in ("maintain", "write", "triage", "read"):
        assert settler._collaborator_permission_is_admin({"permission": permission}) is False


def test_admin_permission_check_uses_rest_collaborator_permission_endpoint(
    monkeypatch: Any, tmp_path: Path
) -> None:
    commands: list[list[str]] = []

    def fake_run_json(command: list[str], *, cwd: Path | None = None) -> dict[str, Any]:
        commands.append(command)
        return {"permission": "admin"}

    monkeypatch.setattr(settler, "_run_json", fake_run_json)

    assert settler._login_has_admin_permission(
        "trusted-admin@example.com",
        "owner/repo",
        tmp_path,
    )
    assert commands == [
        [
            "gh",
            "api",
            "repos/owner/repo/collaborators/trusted-admin%40example.com/permission",
        ]
    ]


def test_authorization_comment_for_different_head_does_not_authorize() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment("different-head")]),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "missing repo-visible Tier 4 operator settlement comment" in result["blockers"]


def test_stale_authorization_comment_does_not_authorize() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    stale = _authorized_comment(head)
    stale["createdAt"] = "2026-05-21T23:59:00Z"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[stale]),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        trusted_operator_logins=["trusted-member"],
    )

    assert result["ok"] is False
    assert "missing repo-visible Tier 4 operator settlement comment" in result["blockers"]


def test_head_mismatch_blocks_before_authorization() -> None:
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head="expected",
        pr_view={
            "headRefOid": "actual",
            "state": "OPEN",
            "isDraft": False,
            "mergeStateStatus": "BLOCKED",
            "headCommittedDate": HEAD_COMMITTED_AT,
            "comments": [],
            "reviews": [],
        },
        merge_packet={},
    )

    assert result["ok"] is False
    assert "head mismatch: expected expected, got actual" in result["blockers"]


def test_head_mismatch_skips_member_permission_check(monkeypatch: Any) -> None:
    monkeypatch.setenv("ARAGORA_TIER4_TRUSTED_OPERATORS", "trusted-member")

    def permission_checker(login: str) -> bool:
        raise AssertionError(f"permission check should be lazy, got {login}")

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head="expected",
        pr_view={
            "headRefOid": "actual",
            "state": "OPEN",
            "isDraft": False,
            "mergeStateStatus": "BLOCKED",
            "headCommittedDate": HEAD_COMMITTED_AT,
            "comments": [
                _authorized_comment(
                    "expected",
                    association="MEMBER",
                    author="trusted-member",
                )
            ],
            "reviews": [],
            "statusCheckRollup": [{"context": "aragora/human-settlement", "state": "SUCCESS"}],
        },
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        permission_checker=permission_checker,
    )

    diagnostic = result["authorization_diagnostics"][0]
    assert result["admin_permission_evaluation"] == "skipped_early_gate_blockers"
    assert diagnostic["admin_permission_required"] is True
    assert diagnostic["admin_permission_evaluated"] is False
    assert (
        "trusted operator admin permission was not evaluated because earlier gate blockers are present"
        in diagnostic["rejection_reasons"]
    )


def test_failed_required_check_blocks_settlement() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head)]),
        merge_packet=_tier4_packet(),
        required_checks=[
            {"name": "lint", "state": "FAILURE"},
            {"name": "aragora-merge-quorum", "state": "SUCCESS"},
        ],
    )

    assert result["ok"] is False
    assert "required check lint is FAILURE" in result["blockers"]
    assert "missing repo-visible Tier 4 operator settlement comment" not in result["blockers"]


def test_failed_required_check_skips_member_permission_check(monkeypatch: Any) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    monkeypatch.setenv("ARAGORA_TIER4_TRUSTED_OPERATORS", "trusted-member")

    def permission_checker(login: str) -> bool:
        raise AssertionError(f"permission check should be lazy, got {login}")

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[
                _authorized_comment(
                    head,
                    association="MEMBER",
                    author="trusted-member",
                )
            ],
        ),
        merge_packet=_tier4_packet(),
        required_checks=[
            {"name": "lint", "state": "FAILURE"},
            {"name": "aragora-merge-quorum", "state": "SUCCESS"},
        ],
        permission_checker=permission_checker,
    )

    diagnostic = result["authorization_diagnostics"][0]
    assert result["admin_permission_evaluation"] == "skipped_early_gate_blockers"
    assert diagnostic["admin_permission_required"] is True
    assert diagnostic["admin_permission_evaluated"] is False
    assert (
        "trusted operator admin permission was not evaluated because earlier gate blockers are present"
        in diagnostic["rejection_reasons"]
    )


def test_missing_merge_quorum_check_is_allowed_before_apply_reconciles_protection() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head)]),
        merge_packet=_tier4_packet(),
        required_checks=[{"name": "lint", "state": "SUCCESS"}],
    )

    assert result["ok"] is True
    assert result["blockers"] == []


def test_present_failed_merge_quorum_required_check_blocks_settlement() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head)]),
        merge_packet=_tier4_packet(),
        required_checks=[
            {"name": "lint", "state": "SUCCESS"},
            {"name": "aragora-merge-quorum", "state": "FAILURE"},
        ],
    )

    assert result["ok"] is False
    assert "required check aragora-merge-quorum is FAILURE" in result["blockers"]
    assert "missing repo-visible Tier 4 operator settlement comment" not in result["blockers"]


def test_unexpected_merge_packet_blocker_blocks_settlement() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    packet = _tier4_packet()
    packet["not_ready"] = ["human_risk_settlement", "model_quorum"]
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head)]),
        merge_packet=packet,
        required_checks=_valid_checks(),
    )

    assert result["ok"] is False
    assert "merge-packet has unexpected blockers: model_quorum" in result["blockers"]


def test_unexpected_packet_blocker_does_not_report_missing_trusted_member_comment(
    monkeypatch: Any,
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    packet = _tier4_packet()
    packet["not_ready"] = ["human_risk_settlement", "model_quorum"]
    monkeypatch.setenv("ARAGORA_TIER4_TRUSTED_OPERATORS", "trusted-member")

    def permission_checker(login: str) -> bool:
        raise AssertionError(f"permission check should be lazy, got {login}")

    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(
            head,
            comments=[
                _authorized_comment(
                    head,
                    association="MEMBER",
                    author="trusted-member",
                )
            ],
        ),
        merge_packet=packet,
        required_checks=_valid_checks(),
        permission_checker=permission_checker,
    )

    diagnostic = result["authorization_diagnostics"][0]
    assert result["ok"] is False
    assert "merge-packet has unexpected blockers: model_quorum" in result["blockers"]
    assert "missing repo-visible Tier 4 operator settlement comment" not in result["blockers"]
    assert result["admin_permission_evaluation"] == "skipped_early_gate_blockers"
    assert diagnostic["admin_permission_required"] is True
    assert diagnostic["admin_permission_evaluated"] is False
    assert (
        "trusted operator admin permission was not evaluated because earlier gate blockers are present"
        in diagnostic["rejection_reasons"]
    )


def test_authorization_diagnostics_explain_member_rejection() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head, association="MEMBER")]),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        trusted_operator_logins=["trusted-member"],
    )

    assert result["ok"] is False
    assert result["required_author_associations"] == ["OWNER"]
    assert "Tier-4 Human Settlement Authorization" in result["settlement_comment_template"]
    assert "PR: #7423" in result["settlement_comment_template"]
    assert f"Exact head: {head}" in result["settlement_comment_template"]
    assert (
        "admin_squash_merge and branch_protection_reconcile"
        in result["settlement_comment_template"]
    )
    diagnostics = result["authorization_diagnostics"]
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic["kind"] == "comment"
    assert diagnostic["author"] == "owner-user"
    assert diagnostic["authorAssociation"] == "MEMBER"
    assert diagnostic["url"] == "https://github.example/pr/7423#issuecomment-1"
    assert diagnostic["marker_present"] is True
    assert diagnostic["trusted_author_association"] is False
    assert diagnostic["fresh_after_head_commit"] is True
    assert diagnostic["exact_head_present"] is True
    assert diagnostic["merge_action_present"] is True
    assert diagnostic["branch_protection_action_present"] is True
    assert diagnostic["accepted"] is False
    assert diagnostic["rejection_reasons"] == [
        "MEMBER login owner-user is not in trusted operator allowlist"
    ]


def test_authorization_diagnostics_accept_owner_comment() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[_authorized_comment(head)]),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["ok"] is True
    assert result["authorization_diagnostics"][0]["accepted"] is True
    assert result["authorization_diagnostics"][0]["rejection_reasons"] == []


def test_authorization_diagnostics_report_stale_comment() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    stale = _authorized_comment(head)
    stale["createdAt"] = "2026-05-21T23:59:00Z"
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[stale]),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
    )

    assert result["authorization_diagnostics"][0]["fresh_after_head_commit"] is False
    assert result["authorization_diagnostics"][0]["rejection_reasons"] == [
        "authorization is older than head commit"
    ]


def test_authorization_diagnostics_report_missing_head_and_tokens() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    bad = _authorized_comment("different-head")
    bad["body"] = (
        "Tier-4 Human Settlement Authorization\n"
        "PR: #7423\n"
        "Exact head: different-head\n"
        "Authorized action: admin_squash_merge only\n"
    )
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[bad]),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        require_branch_protection_token=True,
    )

    diagnostic = result["authorization_diagnostics"][0]
    assert diagnostic["exact_head_present"] is False
    assert diagnostic["merge_action_present"] is True
    assert diagnostic["branch_protection_action_present"] is False
    assert diagnostic["rejection_reasons"] == [
        "exact head is missing",
        "branch_protection_reconcile action is missing",
    ]


def test_check_json_includes_authorization_diagnostics(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[_authorized_comment(head, association="MEMBER")]),
            _tier4_packet(),
            _valid_checks(),
        ),
    )

    rc = settler.main(
        [
            "--check",
            "--pr",
            "7423",
            "--head",
            head,
            "--trusted-operator-login",
            "trusted-member",
            "--cwd",
            str(tmp_path),
            "--json",
        ]
    )

    assert rc == 1
    payload = settler.json.loads(capsys.readouterr().out)
    gate = payload["gate"]
    assert gate["required_author_associations"] == ["OWNER"]
    assert gate["authorization_diagnostics"][0]["rejection_reasons"] == [
        "MEMBER login owner-user is not in trusted operator allowlist"
    ]


def test_check_json_blocks_on_branch_protection_preflight_failure(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[_authorized_comment(head)]),
            _tier4_packet(),
            _valid_checks(),
        ),
    )

    def fail_preflight(*, repo: str, cwd: Path) -> None:
        raise settler.Tier4ApplyError(
            "Tier 4 branch-protection preflight failed before merge mutation: "
            "repos/owner/repo/branches/main/protection: gh: Resource not accessible "
            "by integration (HTTP 403)",
            phase="preflight",
            mutation_occurred=False,
            completed_commands=0,
            recovery_action="verify the active gh identity has branch-protection admin access",
        )

    monkeypatch.setattr(settler, "_preflight_branch_protection_reconcile", fail_preflight)

    rc = settler.main(["--check", "--pr", "7423", "--head", head, "--cwd", str(tmp_path), "--json"])

    assert rc == 1
    payload = settler.json.loads(capsys.readouterr().out)
    gate = payload["gate"]
    assert gate["ok"] is False
    assert gate["settle_eligible"] is False
    assert any(
        blocker.startswith(settler.BRANCH_PROTECTION_PREFLIGHT_BLOCKER)
        for blocker in gate["blockers"]
    )
    preflight = gate["branch_protection_preflight"]
    assert preflight["required"] is True
    assert preflight["ok"] is False
    assert preflight["phase"] == "preflight"
    assert preflight["mutation_occurred"] is False
    assert preflight["completed_commands"] == 0
    assert "HTTP 403" in preflight["error"]


def test_check_json_does_not_block_on_observational_non_admin_preflight(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[_authorized_comment(head)]),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "reviewer-user")
    monkeypatch.setattr(settler, "_login_has_admin_permission", lambda login, repo, cwd: False)
    monkeypatch.setattr(
        settler,
        "_run_json",
        lambda command, cwd, **kwargs: pytest.fail(
            "observational non-admin checks should not read branch-protection endpoints"
        ),
    )

    rc = settler.main(["--check", "--pr", "7423", "--head", head, "--cwd", str(tmp_path), "--json"])

    assert rc == 0
    gate = settler.json.loads(capsys.readouterr().out)["gate"]
    assert gate["ok"] is True
    assert gate["settle_eligible"] is True
    preflight = gate["branch_protection_preflight"]
    assert preflight["required"] is True
    assert preflight["ok"] is True
    assert preflight["advisory"] is True
    assert "lacks admin permission" in preflight["error"]
    assert "eventual --merge-apply operator" in preflight["non_blocking_reason"]


def test_branch_protection_preflight_report_failure_keys_fail_closed(
    monkeypatch: Any, tmp_path: Path
) -> None:
    def fail_preflight(*, repo: str, cwd: Path) -> None:
        raise settler.Tier4ApplyError(
            "real preflight failure",
            phase="preflight",
            mutation_occurred=False,
            completed_commands=0,
            recovery_action="recover",
        )

    def conflicting_payload(self: Any) -> dict[str, Any]:
        return {
            "required": False,
            "ok": True,
            "error": "payload override",
            "phase": self.phase,
            "mutation_occurred": self.mutation_occurred,
            "completed_commands": self.completed_commands,
            "rollback_errors": self.rollback_errors,
            "recovery_action": self.recovery_action,
        }

    monkeypatch.setattr(settler, "_preflight_branch_protection_reconcile", fail_preflight)
    monkeypatch.setattr(settler.Tier4ApplyError, "to_payload", conflicting_payload)

    preflight = settler._branch_protection_preflight_report(
        repo="owner/repo",
        cwd=tmp_path,
        authorized_actions={"branch_protection"},
    )

    assert preflight["required"] is True
    assert preflight["ok"] is False
    assert preflight["error"] == "real preflight failure"
    assert preflight["phase"] == "preflight"


def test_branch_protection_preflight_report_wraps_auth_probe_runtime_error(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        settler,
        "_current_gh_login",
        lambda cwd: (_ for _ in ()).throw(RuntimeError("gh auth unavailable")),
    )

    preflight = settler._branch_protection_preflight_report(
        repo="owner/repo",
        cwd=tmp_path,
        authorized_actions={"branch_protection"},
    )

    assert preflight["required"] is True
    assert preflight["ok"] is False
    assert preflight["phase"] == "preflight"
    assert preflight["mutation_occurred"] is False
    assert preflight["completed_commands"] == 0
    assert "could not probe gh admin permission" in preflight["error"]
    assert "gh auth unavailable" in preflight["error"]


def test_check_skips_branch_protection_preflight_for_merge_only_authorization(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(
                head,
                comments=[
                    _authorized_comment(
                        head,
                        include_branch_protection=False,
                    )
                ],
            ),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(
        settler,
        "_preflight_branch_protection_reconcile",
        lambda repo, cwd: pytest.fail("merge-only authorization should not preflight"),
    )

    rc = settler.main(["--check", "--pr", "7423", "--head", head, "--cwd", str(tmp_path), "--json"])

    assert rc == 0
    gate = settler.json.loads(capsys.readouterr().out)["gate"]
    assert gate["ok"] is True
    assert gate["authorized_actions"] == ["merge"]
    assert gate["branch_protection_preflight"]["required"] is False


def test_settle_only_posts_comment_and_status_without_merge(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    text_commands: list[tuple[list[str], str | None]] = []
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[], human_settlement_state=None),
            _tier4_packet(),
            [
                {"name": "lint", "state": "SUCCESS"},
                {"name": "aragora-merge-quorum", "state": "FAILURE"},
            ],
        ),
    )
    monkeypatch.setattr(
        settler,
        "_run_text_command",
        lambda command, cwd, input_text=None: (
            text_commands.append((command, input_text))
            or "https://github.example/pr/7423#issuecomment-1\n"
        ),
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )
    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "trusted-member")
    monkeypatch.setattr(
        settler,
        "_login_has_admin_permission",
        lambda login, repo, cwd: login == "trusted-member",
    )

    rc = settler.main(
        [
            "--settle-only",
            "--pr",
            "7423",
            "--head",
            head,
            "--trusted-operator-login",
            "trusted-member",
            "--cwd",
            str(tmp_path),
        ]
    )

    assert rc == 0
    all_commands = [command for command, _ in [*text_commands, *commands]]
    assert not any(command[:3] == ["gh", "pr", "merge"] for command in all_commands)
    assert text_commands[0][0][:3] == ["gh", "pr", "comment"]
    assert any("Tier-4 Human Settlement Authorization" in arg for arg in text_commands[0][0])
    assert commands == [
        (
            [
                "gh",
                "api",
                "--method",
                "POST",
                f"repos/synaptent/aragora/statuses/{head}",
                "-f",
                "state=success",
                "-f",
                "context=aragora/human-settlement",
                "-f",
                "description=Tier 4 exact-head human-risk settlement recorded for PR #7423",
                "-f",
                "target_url=https://github.example/pr/7423#issuecomment-1",
            ],
            None,
        )
    ]


def test_settle_only_refuses_unbound_status_when_comment_url_missing(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    text_commands: list[tuple[list[str], str | None]] = []
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[], human_settlement_state=None),
            _tier4_packet(),
            [
                {"name": "lint", "state": "SUCCESS"},
                {"name": "aragora-merge-quorum", "state": "FAILURE"},
            ],
        ),
    )
    monkeypatch.setattr(
        settler,
        "_run_text_command",
        lambda command, cwd, input_text=None: text_commands.append((command, input_text)) or "\n",
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )
    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "trusted-member")
    monkeypatch.setattr(
        settler,
        "_login_has_admin_permission",
        lambda login, repo, cwd: login == "trusted-member",
    )

    rc = settler.main(
        [
            "--settle-only",
            "--pr",
            "7423",
            "--head",
            head,
            "--trusted-operator-login",
            "trusted-member",
            "--cwd",
            str(tmp_path),
            "--json",
        ]
    )

    assert rc == 2
    assert text_commands[0][0][:3] == ["gh", "pr", "comment"]
    assert commands == []


def test_settle_only_requires_proof_for_quorum_only_repair_packet() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    result = settler.evaluate_tier4_settlement_preconditions(
        pr=7423,
        expected_head=head,
        pr_view=_pr_view(head, comments=[], human_settlement_state=None),
        merge_packet=_tier4_repair_packet_missing_settlement(),
        required_checks=[
            {"name": "lint", "state": "SUCCESS"},
            {"name": "aragora-merge-quorum", "state": "FAILURE"},
        ],
    )

    assert result["ok"] is False
    assert (
        "aragora-merge-quorum failure is not proven to be missing human settlement"
        in result["blockers"]
    )


def test_settle_only_allows_quorum_only_repair_packet_with_log_proof(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    text_commands: list[tuple[list[str], str | None]] = []
    commands: list[tuple[list[str], str | None]] = []
    proof_calls: list[tuple[list[dict[str, str]], str]] = []
    required_checks = [
        {"name": "lint", "state": "SUCCESS"},
        {
            "name": "aragora-merge-quorum",
            "state": "FAILURE",
            "link": "https://github.example/synaptent/aragora/actions/runs/123/job/456",
        },
    ]

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, *, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[], human_settlement_state=None),
            _tier4_repair_packet_missing_settlement(),
            required_checks,
        ),
    )

    def fake_quorum_proof(checks: list[dict[str, str]], *, repo: str, cwd: Path, head: str) -> bool:
        proof_calls.append((checks, head))
        return True

    monkeypatch.setattr(settler, "_quorum_failure_log_proves_missing_settlement", fake_quorum_proof)
    monkeypatch.setattr(
        settler,
        "_run_text_command",
        lambda command, cwd, input_text=None: (
            text_commands.append((command, input_text))
            or "https://github.example/pr/7423#issuecomment-1\n"
        ),
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )
    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "trusted-member")
    monkeypatch.setattr(
        settler,
        "_login_has_admin_permission",
        lambda login, repo, cwd: login == "trusted-member",
    )

    rc = settler.main(
        [
            "--settle-only",
            "--pr",
            "7423",
            "--head",
            head,
            "--trusted-operator-login",
            "trusted-member",
            "--cwd",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert proof_calls == [(required_checks, head)]
    assert text_commands[0][0][:3] == ["gh", "pr", "comment"]
    assert commands[0][0][:3] == ["gh", "api", "--method"]


def test_quorum_failure_log_proves_missing_human_settlement(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    calls: list[list[str]] = []

    def fake_run_text_command(
        command: list[str], *, cwd: Path, input_text: str | None = None
    ) -> str:
        calls.append(command)
        return (
            "Tier 4: model quorum prepared the risk packet, but no human "
            f"settlement signal is recorded for head {head[:12]}. "
            "The operator must record settlement and set the "
            "'Aragora/Human-Settlement' commit status."
        )

    monkeypatch.setattr(settler, "_run_text_command", fake_run_text_command)

    assert (
        settler._quorum_failure_log_proves_missing_settlement(
            [
                {"name": "lint", "state": "SUCCESS"},
                {
                    "name": "aragora-merge-quorum",
                    "state": "FAILURE",
                    "link": "https://github.example/synaptent/aragora/actions/runs/123/job/456",
                },
            ],
            repo="synaptent/aragora",
            cwd=tmp_path,
            head=head,
        )
        is True
    )
    assert calls == [
        ["gh", "run", "view", "--repo", "synaptent/aragora", "--job", "456", "--log-failed"]
    ]

    assert (
        settler._quorum_failure_log_proves_missing_settlement(
            [
                {"name": "lint", "state": "SUCCESS"},
                {
                    "name": "aragora-merge-quorum",
                    "state": "FAILURE",
                    "link": "https://github.example/synaptent/aragora/actions/runs/123/job/456",
                },
            ],
            repo="synaptent/aragora",
            cwd=tmp_path,
            head="short",
        )
        is False
    )


def test_settle_only_rejects_untrusted_invoking_login(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[], human_settlement_state=None),
            _tier4_packet(),
            [
                {"name": "lint", "state": "SUCCESS"},
                {"name": "aragora-merge-quorum", "state": "FAILURE"},
            ],
        ),
    )
    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "untrusted-member")
    monkeypatch.setattr(
        settler,
        "_run_text_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)) or "",
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )

    rc = settler.main(
        [
            "--settle-only",
            "--pr",
            "7423",
            "--head",
            head,
            "--trusted-operator-login",
            "trusted-member",
            "--cwd",
            str(tmp_path),
            "--json",
        ]
    )

    assert rc == 2
    assert commands == []
    payload = settler.json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": False,
        "error": (
            "Tier 4 settlement invoker is not trusted; refusing --settle-only: "
            "gh login untrusted-member is not in trusted operator allowlist"
        ),
    }


def test_settle_only_rejects_trusted_invoker_without_admin_permission(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[], human_settlement_state=None),
            _tier4_packet(),
            [
                {"name": "lint", "state": "SUCCESS"},
                {"name": "aragora-merge-quorum", "state": "FAILURE"},
            ],
        ),
    )
    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "trusted-member")
    monkeypatch.setattr(settler, "_login_has_admin_permission", lambda login, repo, cwd: False)
    monkeypatch.setattr(
        settler,
        "_run_text_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)) or "",
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )

    rc = settler.main(
        [
            "--settle-only",
            "--pr",
            "7423",
            "--head",
            head,
            "--trusted-operator-login",
            "trusted-member",
            "--cwd",
            str(tmp_path),
            "--json",
        ]
    )

    assert rc == 2
    assert commands == []
    payload = settler.json.loads(capsys.readouterr().out)
    assert payload == {
        "ok": False,
        "error": (
            "Tier 4 settlement invoker is not trusted; refusing --settle-only: "
            "gh login trusted-member lacks admin/OWNER permission required for --settle-only"
        ),
    }


def test_settle_only_requires_trusted_operator_allowlist(monkeypatch: Any, tmp_path: Path) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[], human_settlement_state=None),
            _tier4_packet(),
            [
                {"name": "lint", "state": "SUCCESS"},
                {"name": "aragora-merge-quorum", "state": "FAILURE"},
            ],
        ),
    )
    monkeypatch.setattr(
        settler,
        "_current_gh_login",
        lambda cwd: pytest.fail("gh identity should not be queried without an allowlist"),
    )
    monkeypatch.setattr(
        settler,
        "_run_text_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)) or "",
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )

    rc = settler.main(["--settle-only", "--pr", "7423", "--head", head, "--cwd", str(tmp_path)])

    assert rc == 2
    assert commands == []


def test_settle_only_rejects_unrelated_required_failure(monkeypatch: Any, tmp_path: Path) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[], human_settlement_state=None),
            _tier4_packet(),
            [
                {"name": "lint", "state": "FAILURE"},
                {"name": "aragora-merge-quorum", "state": "FAILURE"},
            ],
        ),
    )
    monkeypatch.setattr(
        settler,
        "_run_text_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)) or "",
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )

    rc = settler.main(
        ["--settle-only", "--pr", "7423", "--head", head, "--cwd", str(tmp_path), "--json"]
    )

    assert rc == 2
    assert commands == []


def test_ambiguous_apply_mode_is_rejected() -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"

    with pytest.raises(SystemExit) as exc:
        settler.main(["--apply", "--pr", "7423", "--head", head])

    assert exc.value.code == 2


def test_script_direct_help_invocation_imports_local_package() -> None:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "settle_tier4_pr.py"

    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=script_path.parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0
    assert "Check, record, or merge-apply" in result.stdout


def test_merge_apply_uses_valid_command_sequence(monkeypatch: Any, tmp_path: Path) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []
    events: list[str] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[_authorized_comment(head)]),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: (
            events.append("command") or commands.append((command, input_text))
        ),
    )
    monkeypatch.setattr(
        settler,
        "_required_status_check_patch",
        lambda repo, cwd: (["gh", "api", "--method", "PATCH", "checks"], '{"contexts": []}'),
    )
    monkeypatch.setattr(
        settler,
        "_branch_protection_snapshot",
        lambda repo, cwd: _valid_branch_protection_snapshot(),
    )
    monkeypatch.setattr(
        settler,
        "_preflight_branch_protection_reconcile",
        lambda repo, cwd: events.append("preflight"),
    )

    rc = settler.main(["--merge-apply", "--pr", "7423", "--head", head, "--cwd", str(tmp_path)])

    assert rc == 0
    assert events[0] == "preflight"
    assert commands[0][0] == [
        "gh",
        "pr",
        "merge",
        "7423",
        "--squash",
        "--admin",
        "--match-head-commit",
        head,
    ]
    assert "required_approving_review_count" in str(commands[1][1])
    assert commands[-1][0][-1].endswith("/protection/enforce_admins")


def test_merge_apply_branch_protection_preflight_failure_prevents_merge(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[_authorized_comment(head)]),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "admin-user")
    monkeypatch.setattr(settler, "_login_has_admin_permission", lambda login, repo, cwd: True)

    def fail_run_json(command: list[str], cwd: Path, *, write_op: bool = False) -> dict[str, Any]:
        assert write_op is True
        raise RuntimeError("gh: Not Found (HTTP 404)")

    monkeypatch.setattr(settler, "_run_json", fail_run_json)
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )

    rc = settler.main(
        ["--merge-apply", "--pr", "7423", "--head", head, "--cwd", str(tmp_path), "--json"]
    )

    assert rc == 2
    assert commands == []
    payload = settler.json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["phase"] == "preflight"
    assert payload["mutation_occurred"] is False
    assert payload["completed_commands"] == 0
    assert "Not Found" in payload["error"]
    assert "verify the active gh identity" in payload["recovery_action"]


def test_branch_protection_preflight_reads_all_privileged_endpoints(
    monkeypatch: Any, tmp_path: Path
) -> None:
    commands: list[tuple[list[str], bool]] = []

    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "admin-user")
    monkeypatch.setattr(
        settler,
        "_login_has_admin_permission",
        lambda login, repo, cwd: login == "admin-user",
    )

    def fake_run_json(command: list[str], cwd: Path, *, write_op: bool = False) -> dict[str, Any]:
        commands.append((command, write_op))
        return {"ok": True}

    monkeypatch.setattr(settler, "_run_json", fake_run_json)

    settler._preflight_branch_protection_reconcile(repo="owner/repo", cwd=tmp_path)

    endpoints = [command[-1] for command, _write_op in commands]
    assert endpoints == [
        "repos/owner/repo/branches/main/protection",
        "repos/owner/repo/branches/main/protection/required_pull_request_reviews",
        "repos/owner/repo/branches/main/protection/required_status_checks",
        "repos/owner/repo/branches/main/protection/enforce_admins",
    ]
    assert [write_op for _command, write_op in commands] == [True, True, True, True]


def test_branch_protection_preflight_allows_absent_optional_subresource_404(
    monkeypatch: Any, tmp_path: Path
) -> None:
    commands: list[tuple[str, bool]] = []

    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "admin-user")
    monkeypatch.setattr(settler, "_login_has_admin_permission", lambda login, repo, cwd: True)

    def fake_run_json(command: list[str], cwd: Path, *, write_op: bool = False) -> dict[str, Any]:
        endpoint = command[-1]
        commands.append((endpoint, write_op))
        if endpoint.endswith("/protection"):
            return {
                "required_pull_request_reviews": None,
                "required_status_checks": None,
                "enforce_admins": {"enabled": True},
            }
        if endpoint.endswith("/required_pull_request_reviews") or endpoint.endswith(
            "/required_status_checks"
        ):
            raise RuntimeError("gh: Not Found (HTTP 404)")
        return {"enabled": True}

    monkeypatch.setattr(settler, "_run_json", fake_run_json)

    settler._preflight_branch_protection_reconcile(repo="owner/repo", cwd=tmp_path)

    assert commands == [
        ("repos/owner/repo/branches/main/protection", True),
        ("repos/owner/repo/branches/main/protection/required_pull_request_reviews", True),
        ("repos/owner/repo/branches/main/protection/required_status_checks", True),
        ("repos/owner/repo/branches/main/protection/enforce_admins", True),
    ]


def test_branch_protection_preflight_blocks_present_optional_subresource_404(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "admin-user")
    monkeypatch.setattr(settler, "_login_has_admin_permission", lambda login, repo, cwd: True)

    def fake_run_json(command: list[str], cwd: Path, *, write_op: bool = False) -> dict[str, Any]:
        assert write_op is True
        endpoint = command[-1]
        if endpoint.endswith("/protection"):
            return {
                "required_pull_request_reviews": {"url": "https://github.example/reviews"},
                "required_status_checks": None,
                "enforce_admins": {"enabled": True},
            }
        if endpoint.endswith("/required_pull_request_reviews"):
            raise RuntimeError("gh: Not Found (HTTP 404)")
        return {"ok": True}

    monkeypatch.setattr(settler, "_run_json", fake_run_json)

    with pytest.raises(settler.Tier4ApplyError) as exc:
        settler._preflight_branch_protection_reconcile(repo="owner/repo", cwd=tmp_path)

    assert exc.value.phase == "preflight"
    assert exc.value.mutation_occurred is False
    assert "required_pull_request_reviews" in str(exc.value)


def test_branch_protection_preflight_blocks_non_admin_invoker(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setattr(settler, "_current_gh_login", lambda cwd: "member-user")
    monkeypatch.setattr(settler, "_login_has_admin_permission", lambda login, repo, cwd: False)
    monkeypatch.setattr(
        settler,
        "_run_json",
        lambda command, cwd, **kwargs: pytest.fail(
            "branch-protection endpoints should not be read"
        ),
    )

    with pytest.raises(settler.Tier4ApplyError) as exc:
        settler._preflight_branch_protection_reconcile(repo="owner/repo", cwd=tmp_path)

    assert exc.value.phase == "preflight"
    assert exc.value.mutation_occurred is False
    assert exc.value.completed_commands == 0
    assert "lacks admin permission" in str(exc.value)


def test_branch_protection_snapshot_records_absent_optional_subresource_404(
    monkeypatch: Any, tmp_path: Path
) -> None:
    commands: list[bool] = []

    def fake_run_json(command: list[str], cwd: Path, *, write_op: bool = False) -> dict[str, Any]:
        commands.append(write_op)
        endpoint = command[-1]
        if endpoint.endswith("/protection"):
            return {
                "required_pull_request_reviews": None,
                "required_status_checks": None,
                "enforce_admins": {"enabled": True},
            }
        if endpoint.endswith("/required_pull_request_reviews") or endpoint.endswith(
            "/required_status_checks"
        ):
            raise RuntimeError("gh: Not Found (HTTP 404)")
        return {"enabled": True}

    monkeypatch.setattr(settler, "_run_json", fake_run_json)

    snapshot = settler._branch_protection_snapshot(repo="owner/repo", cwd=tmp_path)

    assert snapshot["required_pull_request_reviews"] is None
    assert snapshot["required_status_checks"] is None
    assert snapshot["enforce_admins"] == {"enabled": True}
    assert settler._branch_protection_snapshot_errors(snapshot) == []
    assert commands == [True, True, True, True]


def test_branch_protection_top_level_snapshot_failure_prevents_merge(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[_authorized_comment(head)]),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(
        settler,
        "_preflight_branch_protection_reconcile",
        lambda repo, cwd: None,
    )
    monkeypatch.setattr(
        settler,
        "_branch_protection_snapshot",
        lambda repo, cwd: {"branch_protection": {"snapshot_error": "gh: Not Found (HTTP 404)"}},
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )

    rc = settler.main(
        ["--merge-apply", "--pr", "7423", "--head", head, "--cwd", str(tmp_path), "--json"]
    )

    assert rc == 2
    assert commands == []
    payload = settler.json.loads(capsys.readouterr().out)
    assert payload["phase"] == "branch_protection_snapshot"
    assert payload["mutation_occurred"] is False
    assert payload["completed_commands"] == 0
    assert "branch_protection" in payload["error"]


def test_merge_apply_branch_protection_snapshot_failure_prevents_merge(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[_authorized_comment(head)]),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(
        settler,
        "_preflight_branch_protection_reconcile",
        lambda repo, cwd: None,
    )
    monkeypatch.setattr(
        settler,
        "_branch_protection_snapshot",
        lambda repo, cwd: {
            "branch_protection": {
                "required_pull_request_reviews": {"url": "https://github.example/reviews"},
                "required_status_checks": {"url": "https://github.example/checks"},
                "enforce_admins": {"enabled": True},
            },
            "required_pull_request_reviews": {"snapshot_error": "gh: Not Found (HTTP 404)"},
            "required_status_checks": {"strict": False, "contexts": ["lint"]},
            "enforce_admins": {"enabled": True},
        },
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )

    rc = settler.main(
        ["--merge-apply", "--pr", "7423", "--head", head, "--cwd", str(tmp_path), "--json"]
    )

    assert rc == 2
    assert commands == []
    payload = settler.json.loads(capsys.readouterr().out)
    assert payload["phase"] == "branch_protection_snapshot"
    assert payload["mutation_occurred"] is False
    assert payload["completed_commands"] == 0
    assert "required_pull_request_reviews" in payload["error"]
    assert "before any merge mutation" in payload["recovery_action"]


def test_merge_apply_merge_command_failure_reports_possible_mutation(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[_authorized_comment(head)]),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(
        settler,
        "_preflight_branch_protection_reconcile",
        lambda repo, cwd: None,
    )
    monkeypatch.setattr(
        settler,
        "_branch_protection_snapshot",
        lambda repo, cwd: _valid_branch_protection_snapshot(),
    )
    monkeypatch.setattr(
        settler,
        "_restore_branch_protection",
        lambda repo, cwd, snapshot: ["restore skipped in test"],
    )

    def fake_run_command(command: list[str], cwd: Path, input_text: str | None = None) -> None:
        commands.append((command, input_text))
        if command[:3] == ["gh", "pr", "merge"]:
            raise subprocess.CalledProcessError(1, command, stderr="transport lost")

    monkeypatch.setattr(settler, "_run_command", fake_run_command)

    rc = settler.main(
        ["--merge-apply", "--pr", "7423", "--head", head, "--cwd", str(tmp_path), "--json"]
    )

    assert rc == 2
    assert commands[0][0][:3] == ["gh", "pr", "merge"]
    payload = settler.json.loads(capsys.readouterr().out)
    assert payload["phase"] == "merge"
    assert payload["mutation_occurred"] is True
    assert payload["completed_commands"] == 0
    assert "merge_invoked=True" in payload["error"]
    assert "inspect PR state and branch protection" in payload["recovery_action"]


def test_merge_apply_branch_protection_failure_reports_partial_mutation(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[_authorized_comment(head)]),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(
        settler,
        "_preflight_branch_protection_reconcile",
        lambda repo, cwd: None,
    )
    monkeypatch.setattr(
        settler,
        "_branch_protection_snapshot",
        lambda repo, cwd: _valid_branch_protection_snapshot(),
    )

    def fake_run_command(command: list[str], cwd: Path, input_text: str | None = None) -> None:
        commands.append((command, input_text))
        if "required_pull_request_reviews" in " ".join(command):
            raise subprocess.CalledProcessError(1, command, stderr="Not Found")

    monkeypatch.setattr(settler, "_run_command", fake_run_command)

    rc = settler.main(
        ["--merge-apply", "--pr", "7423", "--head", head, "--cwd", str(tmp_path), "--json"]
    )

    assert rc == 2
    assert commands[0][0][:3] == ["gh", "pr", "merge"]
    payload = settler.json.loads(capsys.readouterr().out)
    assert payload["phase"] == "branch_protection_restore"
    assert payload["mutation_occurred"] is True
    assert payload["completed_commands"] == 1
    assert "inspect PR state and branch protection" in payload["recovery_action"]


def test_merge_apply_refuses_stale_failed_required_rollup_before_merge(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(
                head,
                comments=[_authorized_comment(head)],
                extra_status_rollup=[
                    {
                        "__typename": "CheckRun",
                        "name": "aragora-merge-quorum",
                        "status": "COMPLETED",
                        "conclusion": "FAILURE",
                        "detailsUrl": "https://github.example/actions/failing-quorum",
                        "completedAt": "2026-06-13T01:49:55Z",
                    },
                    {
                        "__typename": "CheckRun",
                        "name": "aragora-merge-quorum",
                        "status": "COMPLETED",
                        "conclusion": "SUCCESS",
                        "detailsUrl": "https://github.example/actions/passing-quorum",
                        "completedAt": "2026-06-13T01:50:41Z",
                    },
                ],
            ),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )

    rc = settler.main(
        ["--merge-apply", "--pr", "7423", "--head", head, "--cwd", str(tmp_path), "--json"]
    )

    assert rc == 2
    assert commands == []
    payload = settler.json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["blocker"] == "required_check_visibility_skew"
    skew = payload["required_check_visibility_skew"]
    assert skew["stale_failed_required_contexts"] == [
        {
            "context": "aragora-merge-quorum",
            "rollup_state": "FAILURE",
            "rollup_status": "COMPLETED",
            "details_url": "https://github.example/actions/failing-quorum",
            "completed_at": "2026-06-13T01:49:55Z",
            "required_state": "SUCCESS",
            "required_link": "",
        }
    ]
    assert "wait/recheck persistent required-check visibility skew" in payload["next_prompt"]


def test_required_status_check_patch_skips_when_quorum_already_required(
    monkeypatch: Any, tmp_path: Path
) -> None:
    def fake_run_json(command: list[str], cwd: Path, *, write_op: bool = False) -> dict[str, Any]:
        assert write_op is True
        return {
            "strict": False,
            "contexts": ["Generate & Validate", "aragora-merge-quorum", "lint"],
        }

    monkeypatch.setattr(settler, "_run_json", fake_run_json)

    patch = settler._required_status_check_patch(repo="owner/repo", cwd=tmp_path)

    assert patch is None


def test_required_status_check_patch_adds_missing_quorum_from_checks(
    monkeypatch: Any, tmp_path: Path
) -> None:
    def fake_run_json(command: list[str], cwd: Path, *, write_op: bool = False) -> dict[str, Any]:
        assert write_op is True
        return {
            "strict": False,
            "checks": [
                {"context": "Generate & Validate", "app_id": 15368},
                {"context": "lint", "app_id": 15368},
            ],
        }

    monkeypatch.setattr(settler, "_run_json", fake_run_json)

    command, payload = settler._required_status_check_patch(repo="owner/repo", cwd=tmp_path)

    assert command == [
        "gh",
        "api",
        "--method",
        "PATCH",
        "repos/owner/repo/branches/main/protection/required_status_checks",
        "--input",
        "-",
    ]
    assert settler.json.loads(payload) == {
        "strict": False,
        "contexts": ["Generate & Validate", "aragora-merge-quorum", "lint"],
    }


def test_merge_apply_skips_required_status_check_patch_when_quorum_already_required(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(head, comments=[_authorized_comment(head)]),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )
    monkeypatch.setattr(
        settler,
        "_required_status_check_patch",
        lambda repo, cwd: None,
    )
    monkeypatch.setattr(
        settler,
        "_branch_protection_snapshot",
        lambda repo, cwd: _valid_branch_protection_snapshot(),
    )
    monkeypatch.setattr(
        settler,
        "_preflight_branch_protection_reconcile",
        lambda repo, cwd: None,
    )

    rc = settler.main(["--merge-apply", "--pr", "7423", "--head", head, "--cwd", str(tmp_path)])

    assert rc == 0
    command_lines = [" ".join(command) for command, _payload in commands]
    assert command_lines[0].endswith(head)
    assert any("required_pull_request_reviews" in line for line in command_lines)
    assert not any("required_status_checks" in line for line in command_lines)
    assert any("enforce_admins" in line for line in command_lines)


def test_merge_apply_merge_only_authorization_skips_branch_protection(
    monkeypatch: Any, tmp_path: Path
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    commands: list[tuple[list[str], str | None]] = []

    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo=settler.DEFAULT_REPO: (
            _pr_view(
                head,
                comments=[_authorized_comment(head, include_branch_protection=False)],
            ),
            _tier4_packet(),
            _valid_checks(),
        ),
    )
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )
    monkeypatch.setattr(
        settler,
        "_branch_protection_snapshot",
        lambda repo, cwd: {"unexpected": "snapshot"},
    )

    rc = settler.main(["--merge-apply", "--pr", "7423", "--head", head, "--cwd", str(tmp_path)])

    assert rc == 0
    assert commands == [
        (
            [
                "gh",
                "pr",
                "merge",
                "7423",
                "--squash",
                "--admin",
                "--match-head-commit",
                head,
            ],
            None,
        )
    ]


# --- --check merge-packet diagnostics enrichment -----------------------------

HEAD_57 = "57c740022e3c432718462efa12ca79f1df4f674d"


def _diagnostic_packet(pr: int = 7423) -> dict[str, Any]:
    """A not-ready Tier 4 packet carrying the rich human-readable entry fields."""
    return {
        "not_ready": [pr],
        "human_risk_settlement_required": [pr],
        "entries": [
            {
                "pr_number": pr,
                "tier": 4,
                "tier_name": "tier_4_preapproval_required",
                "status": "repair_or_wait",
                "verdict": "not_ready_for_settlement",
                "machine_recommendation": "repair_first",
                "checks_summary": "1 failing / 42 total",
                "counted_model_families": [],
                "requires_human_risk_settlement": True,
                "requires_human_preapproval": True,
                "reasons": [
                    "merge-authority/destructive surface touched",
                    "checks are failing; repair before settlement",
                    "model quorum incomplete: 0/2 signal(s)",
                    "focused adversarial dogfood evidence is required",
                ],
            }
        ],
    }


def _failing_checks() -> list[dict[str, str]]:
    return [
        {"name": "lint", "state": "SUCCESS"},
        {"name": "aragora-merge-quorum", "state": "FAILURE"},
    ]


def test_gate_surfaces_merge_packet_diagnostics_when_blocked() -> None:
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=HEAD_57,
        pr_view=_pr_view(HEAD_57, comments=[]),
        merge_packet=_diagnostic_packet(),
        required_checks=_failing_checks(),
    )

    assert result["ok"] is False
    assert result["settle_eligible"] is False
    assert result["head_match"] is True
    assert "aragora-merge-quorum=FAILURE" in result["required_failing"]
    diag = result["merge_packet"]
    assert diag["tier"] == 4
    assert diag["tier_name"] == "tier_4_preapproval_required"
    assert diag["status"] == "repair_or_wait"
    assert diag["verdict"] == "not_ready_for_settlement"
    assert diag["checks_summary"] == "1 failing / 42 total"
    assert diag["counted_model_families"] == []
    assert "model quorum incomplete: 0/2 signal(s)" in diag["reasons"]
    # Top-level convenience mirror for downstream automation.
    assert result["reasons"] == diag["reasons"]


def test_gate_head_mismatch_sets_head_match_false() -> None:
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head="expected",
        pr_view={
            "headRefOid": "actual",
            "state": "OPEN",
            "isDraft": False,
            "mergeStateStatus": "BLOCKED",
            "headCommittedDate": HEAD_COMMITTED_AT,
            "comments": [],
            "reviews": [],
        },
        merge_packet=_diagnostic_packet(),
    )

    assert result["ok"] is False
    assert result["head_match"] is False
    assert result["settle_eligible"] is False
    assert "head mismatch: expected expected, got actual" in result["blockers"]


def test_gate_ready_case_is_settle_eligible() -> None:
    result = settler.evaluate_tier4_gate(
        pr=7423,
        expected_head=HEAD_57,
        pr_view=_pr_view(
            HEAD_57,
            comments=[
                _authorized_comment(
                    HEAD_57,
                    association="MEMBER",
                    author="trusted-member",
                    include_branch_protection=False,
                )
            ],
        ),
        merge_packet=_tier4_packet(),
        required_checks=_valid_checks(),
        trusted_operator_logins=["trusted-member"],
        permission_checker=lambda login: login == "trusted-member",
    )

    assert result["ok"] is True
    assert result["settle_eligible"] is True
    assert result["head_match"] is True
    assert result["required_failing"] == []
    assert result["merge_packet_blockers"] == []


def test_check_json_includes_merge_packet_reasons(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo="synaptent/aragora": (
            _pr_view(HEAD_57, comments=[]),
            _diagnostic_packet(),
            _failing_checks(),
        ),
    )

    rc = settler.main(
        ["--check", "--pr", "7423", "--head", HEAD_57, "--cwd", str(tmp_path), "--json"]
    )

    assert rc == 1
    gate = settler.json.loads(capsys.readouterr().out)["gate"]
    assert gate["head_match"] is True
    assert gate["settle_eligible"] is False
    assert "aragora-merge-quorum=FAILURE" in gate["required_failing"]
    assert "model quorum incomplete: 0/2 signal(s)" in gate["reasons"]
    assert gate["merge_packet"]["tier_name"] == "tier_4_preapproval_required"


def test_check_text_prints_merge_packet_reasons_when_blocked(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    monkeypatch.setattr(
        settler,
        "_load_live_inputs",
        lambda pr, cwd, repo="synaptent/aragora": (
            _pr_view(HEAD_57, comments=[]),
            _diagnostic_packet(),
            _failing_checks(),
        ),
    )

    rc = settler.main(["--check", "--pr", "7423", "--head", HEAD_57, "--cwd", str(tmp_path)])

    out = capsys.readouterr().out
    assert rc == 1
    assert out.startswith("blocked")
    assert "merge-packet: tier=4 (tier_4_preapproval_required)" in out
    assert "checks: 1 failing / 42 total" in out
    assert "counted_model_families: 0 []" in out
    assert "reason: model quorum incomplete: 0/2 signal(s)" in out


# --- #8742: --skew-auto-resolve (bounded rerun-and-wait) --------------------


def _skew_report(run_url: str) -> dict[str, Any]:
    return {
        "blocker": "required_check_visibility_skew",
        "stale_failed_required_contexts": [
            {"context": "aragora-merge-quorum", "details_url": run_url}
        ],
        "next_prompt": "…",
    }


def _incrementing_clock(step: float = 1.0):
    state = {"t": 0.0}

    def _now() -> float:
        state["t"] += step
        return state["t"]

    return _now


def test_superseded_run_ids_extracts_from_details_url() -> None:
    report = {
        "stale_failed_required_contexts": [
            {"details_url": "https://github.com/o/r/actions/runs/28535700881/job/84596779648"},
            {"details_url": "https://github.com/o/r/actions/runs/999/job/1"},
            {"details_url": "no-run-here"},
            {"details_url": "https://github.com/o/r/actions/runs/28535700881/job/2"},  # dup
        ]
    }
    assert settler._superseded_run_ids(report) == ["28535700881", "999"]


def test_auto_resolve_clears_after_rerun(monkeypatch: Any) -> None:
    url = "https://github.com/o/r/actions/runs/123/job/9"
    reports = [_skew_report(url), None]  # still skewed on 1st poll, clear on 2nd
    calls = {"i": 0}

    def _report(**_kwargs: Any):
        i = calls["i"]
        calls["i"] += 1
        return reports[i] if i < len(reports) else None

    monkeypatch.setattr(settler, "_required_check_visibility_skew_report", _report)
    reran: list[str] = []
    result = settler._auto_resolve_visibility_skew(
        pr=1,
        head="h",
        repo="r",
        cwd=Path("."),
        skew_report=_skew_report(url),
        max_reruns=1,
        timeout_seconds=1000.0,
        poll_seconds=1.0,
        load_inputs=lambda: ({}, {}, []),
        rerun_run=lambda rid: (reran.append(rid) or True),
        sleep=lambda _s: None,
        monotonic=_incrementing_clock(step=1.0),
    )
    assert result["cleared"] is True
    assert reran == ["123"]
    assert result["reruns"] == [{"run_id": "123", "ok": True}]


def test_auto_resolve_times_out_when_skew_persists(monkeypatch: Any) -> None:
    url = "https://github.com/o/r/actions/runs/123/job/9"
    monkeypatch.setattr(
        settler, "_required_check_visibility_skew_report", lambda **_k: _skew_report(url)
    )
    reran: list[str] = []
    result = settler._auto_resolve_visibility_skew(
        pr=1,
        head="h",
        repo="r",
        cwd=Path("."),
        skew_report=_skew_report(url),
        max_reruns=1,
        timeout_seconds=5.0,
        poll_seconds=1.0,
        load_inputs=lambda: ({}, {}, []),
        rerun_run=lambda rid: (reran.append(rid) or True),
        sleep=lambda _s: None,
        monotonic=_incrementing_clock(step=2.0),  # expires the 5s window fast
    )
    assert result["cleared"] is False
    assert reran == ["123"]  # it did try
    assert "exhausted" in result["reason"]


def test_auto_resolve_abstains_without_parseable_run_id() -> None:
    report = _skew_report("no-run-id-here")
    result = settler._auto_resolve_visibility_skew(
        pr=1,
        head="h",
        repo="r",
        cwd=Path("."),
        skew_report=report,
        max_reruns=1,
        timeout_seconds=10.0,
        poll_seconds=1.0,
        load_inputs=lambda: ({}, {}, []),
        rerun_run=lambda _rid: True,
        sleep=lambda _s: None,
        monotonic=_incrementing_clock(),
    )
    assert result["cleared"] is False
    assert "no parseable" in result["reason"]


def _skewed_then_clean_inputs(head: str, monkeypatch: Any):
    """_load_live_inputs stub: skewed rollup on call 1, clean on calls >=2."""
    state = {"n": 0}
    stale = {
        "__typename": "CheckRun",
        "name": "aragora-merge-quorum",
        "status": "COMPLETED",
        "conclusion": "FAILURE",
        "detailsUrl": "https://github.com/o/r/actions/runs/456/job/1",
        "completedAt": "2026-06-13T01:49:55Z",
    }
    ok = {
        "__typename": "CheckRun",
        "name": "aragora-merge-quorum",
        "status": "COMPLETED",
        "conclusion": "SUCCESS",
        "detailsUrl": "https://github.com/o/r/actions/runs/457/job/1",
        "completedAt": "2026-06-13T01:50:41Z",
    }

    def _load(pr, cwd, repo=settler.DEFAULT_REPO):
        state["n"] += 1
        rollup = [stale, ok] if state["n"] == 1 else [ok]
        return (
            _pr_view(head, comments=[_authorized_comment(head)], extra_status_rollup=rollup),
            _tier4_packet(),
            _valid_checks(),
        )

    monkeypatch.setattr(settler, "_load_live_inputs", _load)
    return state


def test_merge_apply_auto_resolve_clears_skew_and_merges(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    _skewed_then_clean_inputs(head, monkeypatch)
    commands: list[tuple[list[str], str | None]] = []
    reran: list[str] = []
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )
    monkeypatch.setattr(
        settler,
        "_rerun_workflow_run",
        lambda run_id, cwd, repo: (reran.append(run_id) or True),
    )

    rc = settler.main(
        [
            "--merge-apply",
            "--pr",
            "7423",
            "--head",
            head,
            "--cwd",
            str(tmp_path),
            "--json",
            "--skew-auto-resolve",
            "--skew-poll-seconds",
            "0",
        ]
    )

    assert reran == ["456"]  # re-ran the superseded failed run
    assert commands != []  # merge proceeded after the skew cleared
    assert rc == 0


def test_merge_apply_auto_resolve_reblocks_if_gate_regresses(
    monkeypatch: Any, tmp_path: Path, capsys: Any
) -> None:
    # #8750 openai [P1]: after --skew-auto-resolve clears and reloads inputs, the
    # gate is RE-EVALUATED; if it is no longer ok on the fresh inputs, the merge
    # must be refused (never merge on the stale pre-resolve gate).
    head = "57c740022e3c432718462efa12ca79f1df4f674d"
    _skewed_then_clean_inputs(head, monkeypatch)
    commands: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(
        settler,
        "_run_command",
        lambda command, cwd, input_text=None: commands.append((command, input_text)),
    )
    monkeypatch.setattr(settler, "_rerun_workflow_run", lambda run_id, cwd, repo: True)
    # Gate ok on the initial evaluation (so we enter merge-apply), then NOT ok on
    # the post-resolve re-evaluation.
    gate_calls = {"n": 0}
    real_gate = settler.evaluate_tier4_gate

    def _flaky_gate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        gate_calls["n"] += 1
        g = real_gate(*args, **kwargs)
        if gate_calls["n"] >= 2:
            g = dict(g)
            g["ok"] = False
            g["blockers"] = ["regressed after reload"]
        return g

    monkeypatch.setattr(settler, "evaluate_tier4_gate", _flaky_gate)

    rc = settler.main(
        [
            "--merge-apply",
            "--pr",
            "7423",
            "--head",
            head,
            "--cwd",
            str(tmp_path),
            "--skew-auto-resolve",
            "--skew-poll-seconds",
            "0",
        ]
    )

    assert rc == 2
    assert commands == []  # merge NOT applied
    assert gate_calls["n"] >= 2  # the gate was re-evaluated post-resolve
