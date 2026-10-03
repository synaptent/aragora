from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import scripts.reconcile_automation_outbox as mod

REPO_ROOT = Path(__file__).resolve().parents[2]
WRAPPER_SCRIPT_PATH = REPO_ROOT / "scripts" / "reconcile_automation_handoffs.py"


def _unhealthy_github() -> SimpleNamespace:
    return SimpleNamespace(
        ready=False,
        mode="connectivity_failed",
        error="error connecting to api.github.com",
    )


def _ready_github() -> SimpleNamespace:
    return SimpleNamespace(ready=True, mode="ready", error="")


def _write_outbox_handoff(
    outbox_dir: Path,
    *,
    branch: str,
    key: str,
    local_evidence: dict[str, Any] | None = None,
) -> Path:
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"{key}.json"
    payload = {
        "task": f"Publish {branch}",
        "requires_github": True,
        "requested_action": {"type": "open_pr", "branch": branch},
        "repo": "synaptent/aragora",
        "idempotency_key": key,
    }
    if local_evidence is not None:
        payload["local_evidence"] = local_evidence
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    return path


def _write_non_handoff_report(outbox_dir: Path, *, key: str) -> Path:
    outbox_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_dir / f"{key}.json"
    path.write_text(
        json.dumps(
            {
                "candidate_notes": [{"pr": 9001, "selected": False, "reason": "parked elsewhere"}],
                "cycle_dir": ".aragora/goal_cycles/20260708T121303Z",
                "idempotency_key": key,
                "main_required_check_state": [],
                "rows": [],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_terminal_receipt_keys_falls_back_to_receipt_filename(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir()
    key = "open-pr-codex-example-abc123"
    (receipt_dir / f"{key}.json").write_text(
        json.dumps({"status": "published"}),
        encoding="utf-8",
    )

    assert mod._terminal_receipt_keys(receipt_dir) == {key}


def test_dry_run_does_not_write_report_by_default(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})

    rc = mod.main(["--repo", str(tmp_path), "--base", "origin/main"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "report: not written in dry-run" in out
    assert not (tmp_path / ".aragora" / "cleanup-state").exists()


def test_repo_defaults_to_current_working_directory(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    key = "open-pr-codex-default-repo-abc123"
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    _write_outbox_handoff(outbox_dir, branch="codex/default-repo", key=key)
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps({"idempotency_key": key, "status": "published"}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    rc = mod.main(["--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["repo"] == str(tmp_path.resolve())
    assert payload["state_root"] == str(tmp_path.resolve())
    assert payload["outbox_dir"] == str(outbox_dir.resolve())
    assert payload["receipt_dir"] == str(receipt_dir.resolve())
    assert payload["counts"]["satisfied_by_existing_receipt"] == 1


def test_explicit_dry_run_flag_keeps_read_only_default(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})

    rc = mod.main(["--repo", str(tmp_path), "--dry-run"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "mode: DRY-RUN" in out
    assert "DRY-RUN" in out
    assert not (tmp_path / ".aragora" / "cleanup-state").exists()


def test_branchless_report_classifies_as_non_handoff_report_without_mutation(
    tmp_path: Path, capsys: Any
) -> None:
    key = "queue-drain-park-reconciliation-20260708T121926Z"
    report = _write_non_handoff_report(
        tmp_path / ".aragora" / "automation-outbox",
        key=key,
    )

    rc = mod.main(["--repo", str(tmp_path), "--dry-run", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["counts"]["non_handoff_report"] == 1
    assert payload["counts"]["skipped_unparseable"] == 0
    assert payload["actions"][0]["decision"] == "archive_report"
    assert payload["actions"][0]["terminal_disposition"]["disposition"] == ("non_handoff_report")
    assert report.exists()
    assert not (tmp_path / ".aragora" / "automation-outbox-archive").exists()


def test_apply_archives_non_handoff_report_with_terminal_disposition(
    tmp_path: Path, capsys: Any
) -> None:
    key = "queue-drain-park-reconciliation-20260708T121926Z"
    report = _write_non_handoff_report(
        tmp_path / ".aragora" / "automation-outbox",
        key=key,
    )

    rc = mod.main(["--repo", str(tmp_path), "--apply", "--json"])

    payload = json.loads(capsys.readouterr().out)
    archive = tmp_path / ".aragora" / "automation-outbox-archive" / report.name
    archived = json.loads(archive.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["counts"]["non_handoff_report"] == 1
    assert payload["counts"]["skipped_unparseable"] == 0
    assert payload["archived"] == 1
    assert not report.exists()
    assert archived["idempotency_key"] == key
    assert archived["terminal_disposition"]["disposition"] == "non_handoff_report"
    assert "not an automation handoff" in archived["terminal_disposition"]["reason"]


def test_branch_backed_handoff_still_uses_missing_branch_classification(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    _write_outbox_handoff(outbox_dir, branch="codex/missing", key="open-pr-codex-missing")

    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    monkeypatch.setattr(
        mod,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git"], returncode=128, stdout="", stderr="missing ref"
        ),
    )

    rc = mod.main(["--repo", str(tmp_path), "--dry-run", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["counts"]["missing_branch"] == 1
    assert payload["counts"]["non_handoff_report"] == 0
    assert payload["counts"]["skipped_unparseable"] == 0
    assert payload["actions"][0]["decision"] == "archive"
    assert payload["actions"][0]["reason"] == "branch no longer exists"


def test_malformed_report_without_idempotency_key_stays_unparseable(
    tmp_path: Path, capsys: Any
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    outbox_dir.mkdir(parents=True)
    (outbox_dir / "branchless-report-without-key.json").write_text(
        json.dumps({"rows": [], "candidate_notes": []}),
        encoding="utf-8",
    )

    rc = mod.main(["--repo", str(tmp_path), "--dry-run", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["counts"]["non_handoff_report"] == 0
    assert payload["counts"]["skipped_unparseable"] == 1


def test_branchless_generic_check_payload_is_not_non_handoff_report(
    tmp_path: Path, capsys: Any
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    outbox_dir.mkdir(parents=True)
    (outbox_dir / "branchless-generic-check-payload.json").write_text(
        json.dumps(
            {
                "idempotency_key": "branchless-generic-check-payload",
                "required_contexts": ["lint", "typecheck"],
                "rows": [],
            }
        ),
        encoding="utf-8",
    )

    rc = mod.main(["--repo", str(tmp_path), "--dry-run", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["counts"]["non_handoff_report"] == 0
    assert payload["counts"]["skipped_unparseable"] == 1
    assert payload["actions"] == []
    assert not (tmp_path / ".aragora" / "automation-outbox-archive").exists()


def test_branchless_preservation_payload_is_not_non_handoff_report(
    tmp_path: Path, capsys: Any
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    outbox_dir.mkdir(parents=True)
    (outbox_dir / "open-pr-preservation-marker.json").write_text(
        json.dumps(
            {
                "constraints": ["preserve local work before cleanup"],
                "idempotency_key": "open-pr-preservation-marker",
                "worktree": str(tmp_path / "preserved-worktree"),
            }
        ),
        encoding="utf-8",
    )

    rc = mod.main(["--repo", str(tmp_path), "--dry-run", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["counts"]["non_handoff_report"] == 0
    assert payload["counts"]["skipped_unparseable"] == 1
    assert payload["actions"] == []
    assert not (tmp_path / ".aragora" / "automation-outbox-archive").exists()


def test_branchless_preservation_payload_with_report_keys_stays_protected(
    tmp_path: Path, capsys: Any
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    outbox_dir.mkdir(parents=True)
    (outbox_dir / "open-pr-preservation-with-report-keys.json").write_text(
        json.dumps(
            {
                "desired_head": "abc123",
                "idempotency_key": "open-pr-preservation-with-report-keys",
                "required_contexts": ["lint", "typecheck"],
                "rows": [{"name": "lint", "state": "success"}],
                "worktree": str(tmp_path / "preserved-worktree"),
            }
        ),
        encoding="utf-8",
    )

    rc = mod.main(["--repo", str(tmp_path), "--dry-run", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["counts"]["non_handoff_report"] == 0
    assert payload["counts"]["skipped_unparseable"] == 1
    assert payload["actions"] == []
    assert not (tmp_path / ".aragora" / "automation-outbox-archive").exists()


@pytest.mark.parametrize("head_key", ["head", "commit"])
def test_branchless_top_level_head_preservation_payload_stays_protected(
    tmp_path: Path, capsys: Any, head_key: str
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    outbox_dir.mkdir(parents=True)
    (outbox_dir / f"open-pr-preservation-with-{head_key}.json").write_text(
        json.dumps(
            {
                head_key: "abc123",
                "idempotency_key": f"open-pr-preservation-with-{head_key}",
                "required_contexts": ["lint", "typecheck"],
                "rows": [{"name": "lint", "state": "success"}],
            }
        ),
        encoding="utf-8",
    )

    rc = mod.main(["--repo", str(tmp_path), "--dry-run", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["counts"]["non_handoff_report"] == 0
    assert payload["counts"]["skipped_unparseable"] == 1
    assert payload["actions"] == []
    assert not (tmp_path / ".aragora" / "automation-outbox-archive").exists()


def test_github_open_pr_state_fails_closed_when_open_pr_fetch_returns_none(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setattr(mod, "check_github_cli_health", lambda *_args: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: None)

    open_prs, available, message = mod._github_open_pr_state(tmp_path, "synaptent/aragora")

    assert open_prs == {}
    assert available is False
    assert message == "open PR fetch returned no usable data"


def test_github_open_pr_state_loads_all_branch_prefixes(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(mod, "check_github_cli_health", lambda *_args: _ready_github())

    def fake_open_pr_heads(_root: Path, _repo: str, prefix: str) -> dict[str, int]:
        assert prefix == ""
        return {"structex/p2-docs-ci-tooling": 8501}

    monkeypatch.setattr(mod, "open_pr_heads", fake_open_pr_heads)

    open_prs, available, message = mod._github_open_pr_state(tmp_path, "synaptent/aragora")

    assert open_prs == {"structex/p2-docs-ci-tooling": 8501}
    assert available is True
    assert message == "1 open PRs"


def test_json_output_reports_reconciliation_without_human_preamble(
    tmp_path: Path,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    key = "open-pr-codex-json-output-abc123"
    _write_outbox_handoff(outbox_dir, branch="codex/json-output", key=key)
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps({"idempotency_key": key, "status": "published"}),
        encoding="utf-8",
    )

    rc = mod.main(["--repo", str(tmp_path), "--json"])

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert not out.startswith("outbox_dir:")
    assert payload["dry_run"] is True
    assert payload["applied"] is False
    assert payload["report"] is None
    assert payload["outbox_count"] == 1
    assert payload["terminal_receipt_count"] == 1
    assert payload["counts"]["satisfied_by_existing_receipt"] == 1
    assert payload["archived"] == 1
    assert payload["kept"] == 0
    assert payload["actions"][0]["branch"] == "codex/json-output"


def test_json_summary_only_omits_action_details(
    tmp_path: Path,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    key = "open-pr-codex-summary-only-abc123"
    _write_outbox_handoff(outbox_dir, branch="codex/summary-only", key=key)
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps({"idempotency_key": key, "status": "published"}),
        encoding="utf-8",
    )

    rc = mod.main(["--repo", str(tmp_path), "--json", "--summary-only"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["archived"] == 1
    assert payload["kept"] == 0
    assert payload["action_count"] == 1
    assert payload["actions_omitted"] is True
    assert payload["reason_counts"] == {"matching receipt exists": 1}
    assert "actions" not in payload


def test_json_output_suppresses_flush_time_broken_pipe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FlushBrokenStdout:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, text: str) -> int:
            self.writes.append(text)
            return len(text)

        def flush(self) -> None:
            raise BrokenPipeError("downstream closed")

    stream = FlushBrokenStdout()
    monkeypatch.setattr(mod.sys, "stdout", stream)

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    assert stream.writes
    assert mod.sys.stdout is not stream
    mod.sys.stdout.close()


def test_emit_output_suppresses_write_time_broken_pipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class WriteBrokenStdout:
        def write(self, _text: str) -> int:
            raise BrokenPipeError("downstream closed")

        def flush(self) -> None:
            raise AssertionError("flush should not run after write failure")

    stream = WriteBrokenStdout()
    monkeypatch.setattr(mod.sys, "stdout", stream)

    mod._emit_output("payload")

    assert mod.sys.stdout is not stream
    mod.sys.stdout.close()


def test_reconcile_automation_handoffs_wrapper_executes_primary_script(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(WRAPPER_SCRIPT_PATH),
            "--repo",
            str(tmp_path),
            "--json",
            "--summary-only",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["repo"] == str(tmp_path.resolve())
    assert payload["outbox_count"] == 0
    assert payload["actions_omitted"] is True


def test_state_root_can_point_at_direct_dot_aragora(
    tmp_path: Path,
    capsys: Any,
) -> None:
    repo = tmp_path / "disposable-worktree"
    repo.mkdir()
    state_root = tmp_path / "shared-checkout" / ".aragora"
    outbox_dir = state_root / "automation-outbox"
    receipt_dir = state_root / "automation-receipts"
    key = "open-pr-codex-shared-state-abc123"
    _write_outbox_handoff(outbox_dir, branch="codex/shared-state", key=key)
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps({"idempotency_key": key, "status": "published"}),
        encoding="utf-8",
    )

    rc = mod.main(["--repo", str(repo), "--state-root", str(state_root), "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["state_root"] == str(state_root.resolve())
    assert payload["outbox_dir"] == str(outbox_dir.resolve())
    assert payload["receipt_dir"] == str(receipt_dir.resolve())
    assert payload["archive_dir"] == str((state_root / "automation-outbox-archive").resolve())
    assert payload["counts"]["satisfied_by_existing_receipt"] == 1


def test_apply_uses_explicit_shared_state_dirs(
    tmp_path: Path,
    capsys: Any,
) -> None:
    repo = tmp_path / "disposable-worktree"
    repo.mkdir()
    shared_state = tmp_path / "shared-state"
    outbox_dir = shared_state / "outbox"
    receipt_dir = shared_state / "receipts"
    archive_dir = shared_state / "archive"
    key = "open-pr-codex-explicit-state-abc123"
    handoff = _write_outbox_handoff(outbox_dir, branch="codex/explicit-state", key=key)
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps({"idempotency_key": key, "status": "published"}),
        encoding="utf-8",
    )

    rc = mod.main(
        [
            "--repo",
            str(repo),
            "--outbox-dir",
            str(outbox_dir),
            "--receipt-dir",
            str(receipt_dir),
            "--archive-dir",
            str(archive_dir),
            "--apply",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["outbox_dir"] == str(outbox_dir.resolve())
    assert payload["receipt_dir"] == str(receipt_dir.resolve())
    assert payload["archive_dir"] == str(archive_dir.resolve())
    assert payload["archived"] == 1
    assert handoff.exists() is False
    assert (archive_dir / handoff.name).exists()


def test_idempotency_key_filter_limits_reconciliation_scope(
    tmp_path: Path,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    selected_key = "open-pr-codex-selected-abc123"
    skipped_key = "open-pr-codex-skipped-def456"
    _write_outbox_handoff(outbox_dir, branch="codex/selected", key=selected_key)
    _write_outbox_handoff(outbox_dir, branch="codex/skipped", key=skipped_key)
    receipt_dir.mkdir(parents=True)
    for key in (selected_key, skipped_key):
        (receipt_dir / f"{key}.json").write_text(
            json.dumps({"idempotency_key": key, "status": "published"}),
            encoding="utf-8",
        )

    rc = mod.main(
        [
            "--repo",
            str(tmp_path),
            "--idempotency-key",
            selected_key,
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["outbox_count"] == 1
    assert payload["total_outbox_count"] == 2
    assert payload["archived"] == 1
    assert payload["actions"][0]["branch"] == "codex/selected"
    assert payload["target"]["idempotency_keys"] == [selected_key]


def test_apply_outbox_file_filter_archives_only_selected_handoff(
    tmp_path: Path,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    selected_key = "open-pr-codex-file-selected-abc123"
    skipped_key = "open-pr-codex-file-skipped-def456"
    selected = _write_outbox_handoff(
        outbox_dir,
        branch="codex/file-selected",
        key=selected_key,
    )
    skipped = _write_outbox_handoff(
        outbox_dir,
        branch="codex/file-skipped",
        key=skipped_key,
    )
    receipt_dir.mkdir(parents=True)
    for key in (selected_key, skipped_key):
        (receipt_dir / f"{key}.json").write_text(
            json.dumps({"idempotency_key": key, "status": "published"}),
            encoding="utf-8",
        )

    rc = mod.main(
        [
            "--repo",
            str(tmp_path),
            "--outbox-file",
            selected.name,
            "--apply",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    archived = tmp_path / ".aragora" / "automation-outbox-archive" / selected.name
    assert rc == 0
    assert payload["outbox_count"] == 1
    assert payload["total_outbox_count"] == 2
    assert payload["archived"] == 1
    assert selected.exists() is False
    assert archived.exists()
    assert skipped.exists()


def test_missing_target_filter_fails_closed(
    tmp_path: Path,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-present-abc123"
    _write_outbox_handoff(outbox_dir, branch="codex/present", key=key)

    rc = mod.main(
        [
            "--repo",
            str(tmp_path),
            "--idempotency-key",
            "open-pr-codex-missing-def456",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["error"] == "target outbox handoff not found"
    assert payload["missing_idempotency_keys"] == ["open-pr-codex-missing-def456"]
    assert payload["total_outbox_count"] == 1
    assert (outbox_dir / f"{key}.json").exists()


def test_explicit_outbox_dir_defaults_archive_beside_outbox(
    tmp_path: Path,
    capsys: Any,
) -> None:
    repo = tmp_path / "disposable-worktree"
    repo.mkdir()
    shared_state = tmp_path / "shared-state"
    outbox_dir = shared_state / "automation-outbox"
    receipt_dir = shared_state / "automation-receipts"
    key = "open-pr-codex-explicit-outbox-abc123"
    _write_outbox_handoff(outbox_dir, branch="codex/explicit-outbox", key=key)
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps({"idempotency_key": key, "status": "published"}),
        encoding="utf-8",
    )

    rc = mod.main(
        [
            "--repo",
            str(repo),
            "--outbox-dir",
            str(outbox_dir),
            "--receipt-dir",
            str(receipt_dir),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["archive_dir"] == str((shared_state / "automation-outbox-archive").resolve())


def test_apply_archives_outbox_handoff_superseded_by_active_handoff(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    old_key = "open-pr-codex-example-oldaaaa"
    new_key = "open-pr-codex-example-restack-newbbbb"
    old_path = _write_outbox_handoff(
        outbox_dir,
        branch="codex/example",
        key=old_key,
        local_evidence={
            "branch": "codex/example",
            "head_sha": "oldaaaa1111",
        },
    )
    new_path = _write_outbox_handoff(
        outbox_dir,
        branch="codex/example-restack",
        key=new_key,
        local_evidence={
            "branch": "codex/example-restack",
            "head_sha": "newbbbb2222",
            "supersedes_branch": "codex/example",
            "supersedes_head_sha": "oldaaaa1111",
        },
    )

    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})

    def fake_run_git(args: list[str], *_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess:
        if args[:2] == ["rev-parse", "--verify"]:
            return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="head\n")
        if args and args[0] == "merge-base":
            return subprocess.CompletedProcess(args=["git"], returncode=1, stdout="")
        if args and args[0] == "cherry":
            return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="+ newbbbb\n")
        return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="")

    monkeypatch.setattr(mod, "run_git", fake_run_git)

    assert mod.main(["--repo", str(tmp_path), "--apply", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["satisfied_by_superseded_handoff"] == 1
    assert payload["archived"] == 1
    assert old_path.exists() is False
    assert new_path.exists() is True
    archived = tmp_path / ".aragora" / "automation-outbox-archive" / old_path.name
    receipt = tmp_path / ".aragora" / "automation-receipts" / f"{old_key}.json"
    assert archived.exists()
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt_payload["status"] == "already_satisfied"
    assert receipt_payload["synthetic_reason"] == f"superseded by active handoff {new_key}"


def test_apply_archives_outbox_handoff_superseded_by_idempotency_key(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    old_key = "open-pr-codex-example-oldaaaa"
    new_key = "open-pr-codex-example-restack-newbbbb"
    old_path = _write_outbox_handoff(
        outbox_dir,
        branch="codex/example",
        key=old_key,
        local_evidence={
            "branch": "codex/example",
            "head_sha": "oldaaaa1111",
        },
    )
    new_path = _write_outbox_handoff(
        outbox_dir,
        branch="codex/example-restack",
        key=new_key,
        local_evidence={
            "branch": "codex/example-restack",
            "head_sha": "newbbbb2222",
            "supersedes_outbox_keys": [old_key],
            "source_candidates": [
                {
                    "idempotency_key": old_key,
                    "source_branch": "codex/example",
                    "head_sha": "oldaaaa1111",
                }
            ],
        },
    )

    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})

    def fake_run_git(args: list[str], *_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess:
        if args[:2] == ["rev-parse", "--verify"]:
            return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="head\n")
        if args and args[0] == "merge-base":
            return subprocess.CompletedProcess(args=["git"], returncode=1, stdout="")
        if args and args[0] == "cherry":
            return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="+ newbbbb\n")
        return subprocess.CompletedProcess(args=["git"], returncode=0, stdout="")

    monkeypatch.setattr(mod, "run_git", fake_run_git)

    assert mod.main(["--repo", str(tmp_path), "--apply", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["satisfied_by_superseded_handoff"] == 1
    assert payload["archived"] == 1
    assert old_path.exists() is False
    assert new_path.exists() is True
    archived = tmp_path / ".aragora" / "automation-outbox-archive" / old_path.name
    receipt = tmp_path / ".aragora" / "automation-receipts" / f"{old_key}.json"
    assert archived.exists()
    receipt_payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt_payload["status"] == "already_satisfied"
    assert receipt_payload["synthetic_reason"] == f"superseded by active handoff {new_key}"


def test_dry_run_can_write_report_when_requested(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})

    rc = mod.main(["--repo", str(tmp_path), "--base", "origin/main", "--write-report"])

    out = capsys.readouterr().out
    reports = list((tmp_path / ".aragora" / "cleanup-state").glob("*.json"))
    assert rc == 0
    assert "report:" in out
    assert len(reports) == 1
    payload = json.loads(reports[0].read_text(encoding="utf-8"))
    assert payload["applied"] is False


def test_dry_run_out_writes_explicit_report_path(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    report_path = tmp_path / "artifacts" / "reconcile-report.json"

    rc = mod.main(["--repo", str(tmp_path), "--json", "--out", str(report_path)])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["report"] == str(report_path)
    assert report_path.exists()
    report_payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_payload["applied"] is False
    assert not (tmp_path / ".aragora" / "cleanup-state").exists()


def test_branch_from_payload_tolerates_list_local_evidence() -> None:
    payload = {
        "branch": "codex/openrouter-kimi-fallback-haiku",
        "local_evidence": [
            "older handoffs sometimes stored local evidence as bullet text",
        ],
    }

    assert mod._branch_from_payload(payload) == "codex/openrouter-kimi-fallback-haiku"


def test_branch_from_payload_uses_list_local_evidence_mapping() -> None:
    payload = {
        "requested_action": "open_pr",
        "local_evidence": [
            "older handoffs sometimes stored local evidence as bullet text",
            {"branch": "codex/list-evidence"},
        ],
    }

    assert mod._branch_from_payload(payload) == "codex/list-evidence"


def test_branch_from_payload_prefers_structured_local_evidence() -> None:
    payload = {
        "branch": "codex/stale-top-level",
        "local_evidence": {"branch": "codex/structured"},
    }

    assert mod._branch_from_payload(payload) == "codex/structured"


def test_reconcile_existing_receipt_uses_structured_requested_action_branch(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    outbox_dir.mkdir(parents=True)
    receipt_dir.mkdir(parents=True)
    key = "open-pr-codex-structured-action-abc123"
    (outbox_dir / "structured-action.json").write_text(
        json.dumps(
            {
                "task": "Publish structured-action branch",
                "requires_github": True,
                "requested_action": {
                    "type": "open_pr",
                    "branch": "codex/structured-action",
                },
                "repo": "synaptent/aragora",
                "local_evidence": {},
                "validation": ["pytest tests/example.py -q"],
                "idempotency_key": key,
                "created_at": "2026-04-27T10:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (receipt_dir / f"{key}.json").write_text(
        json.dumps({"idempotency_key": key, "status": "published"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})

    assert mod.main(["--repo", str(tmp_path), "--write-report"]) == 0

    reports = sorted((tmp_path / ".aragora" / "cleanup-state").glob("*.json"))
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["counts"]["satisfied_by_existing_receipt"] == 1
    assert payload["counts"]["skipped_unparseable"] == 0
    assert payload["actions"][0]["branch"] == "codex/structured-action"


@pytest.mark.parametrize(
    ("status", "reason", "issue_key"),
    [
        ("already_satisfied", "existing_issue", "existing_issue_url"),
        ("published", "published", "created_issue_url"),
    ],
)
def test_reconcile_keeps_pr_handoff_with_issue_only_receipt(
    tmp_path: Path,
    capsys: Any,
    status: str,
    reason: str,
    issue_key: str,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    key = "open-pr-codex-issue-only-receipt-abc123"
    handoff = _write_outbox_handoff(
        outbox_dir,
        branch="codex/issue-only-receipt",
        key=key,
    )
    payload = json.loads(handoff.read_text(encoding="utf-8"))
    payload["requested_action"] = {
        "type": "open_or_update_pr",
        "base": "main",
        "branch": "codex/issue-only-receipt",
        "desired_head_sha": "abcdef1234567890abcdef1234567890abcdef12",
    }
    handoff.write_text(json.dumps(payload), encoding="utf-8")
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "idempotency_key": key,
                "status": status,
                "reason": reason,
                issue_key: "https://github.com/synaptent/aragora/issues/7320",
                "existing_pr_url": None,
            }
        ),
        encoding="utf-8",
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["blocked_receipt_issue_only"] == 1
    assert result["counts"]["satisfied_by_existing_receipt"] == 0
    assert result["counts"]["still_protecting_active_work"] == 1
    assert result["actions"][0]["decision"] == "keep"
    assert "issue-only receipt" in result["actions"][0]["reason"]
    assert handoff.exists()


def test_reconcile_archives_issue_only_pr_handoff_when_merged_pr_proves_head_preserved(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    key = "open-pr-codex-issue-only-merged-pr-proof-abc123"
    branch = "codex/issue-only-merged-pr-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    handoff = _write_outbox_handoff(
        outbox_dir,
        branch=branch,
        key=key,
        local_evidence={
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree": str(tmp_path / "missing-worktree"),
        },
    )
    payload = json.loads(handoff.read_text(encoding="utf-8"))
    payload["requested_action"] = {
        "type": "open_or_update_pr",
        "base": "main",
        "branch": branch,
        "desired_head_sha": desired_head,
    }
    handoff.write_text(json.dumps(payload), encoding="utf-8")
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "idempotency_key": key,
                "status": "published",
                "reason": "published",
                "created_issue_url": "https://github.com/synaptent/aragora/issues/8581",
                "existing_pr_url": None,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [str(tmp_path / "missing-worktree")],
            "worktree_inspections": [
                {
                    "path": str(tmp_path / "missing-worktree"),
                    "absent_noop": True,
                    "source": "safe_worktree_cleanup.inspect",
                    "classification": "absent_noop",
                }
            ],
            "upstream_preservation": {
                "proven": True,
                "method": "merged_pr_commit_list",
                "pr_number": 8583,
                "repo": "synaptent/aragora",
                "base_ref": "main",
            },
        },
    )

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", branch]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{desired_head}\n")
        if args == ["rev-parse", "--verify", desired_head]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{desired_head}\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0 if args[2] == desired_head else 1,
                stdout="",
                stderr="",
            )
        if args[0] == "cherry":
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=f"+ {desired_head}\n"
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(
        mod,
        "open_pr_heads",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("open PR fetch should not run once merged PR proof is available")
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--apply", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["satisfied_by_merged_pr_commit_proof"] == 1
    assert result["counts"]["blocked_receipt_issue_only"] == 0
    assert result["counts"]["still_protecting_active_work"] == 0
    assert result["actions"][0]["decision"] == "archive"
    assert result["actions"][0]["synthetic_receipt"] is False
    assert "merged PR commit list (PR #8583)" in result["actions"][0]["reason"]
    assert not handoff.exists()
    archived = tmp_path / ".aragora" / "automation-outbox-archive" / handoff.name
    archive_payload = json.loads(archived.read_text(encoding="utf-8"))
    disposition = archive_payload["terminal_disposition"]
    assert disposition["reason"] == "desired head preserved by merged PR commit list (PR #8583)"
    assert disposition["preservation_proof"]["upstream_preservation"]["method"] == (
        "merged_pr_commit_list"
    )


def test_reconcile_keeps_target_pr_receipt_when_desired_head_not_published(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    key = "open-pr-codex-target-pr-refresh-newhead"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    stale_remote_head = "1111111234567890abcdef1234567890abcdef12"
    handoff = _write_outbox_handoff(
        outbox_dir,
        branch="codex/target-pr-refresh",
        key=key,
        local_evidence={
            "branch": "codex/target-pr-refresh",
            "desired_head_sha": desired_head,
        },
    )
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "idempotency_key": key,
                "status": "already_satisfied",
                "reason": "target_open_pr",
                "existing_pr_url": "https://github.com/synaptent/aragora/pull/7105",
            }
        ),
        encoding="utf-8",
    )

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", "refs/remotes/origin/codex/target-pr-refresh"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=stale_remote_head)
        if args == ["rev-parse", "--verify", "codex/target-pr-refresh"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=desired_head)
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        if args[0] == "cherry":
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=f"+ {desired_head}\n",
                stderr="",
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "_target_pr_state", lambda *_args: None)
    monkeypatch.setattr(
        mod,
        "open_pr_heads",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("open PR fetch should not run for mismatched target PR receipts")
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["blocked_receipt_pr_head_mismatch"] == 1
    assert payload["counts"]["satisfied_by_existing_receipt"] == 0
    assert payload["counts"]["still_protecting_active_work"] == 1
    assert payload["actions"][0]["decision"] == "keep"
    assert "not desired head" in payload["actions"][0]["reason"]
    assert handoff.exists()
    assert not (tmp_path / ".aragora" / "automation-outbox-archive").exists()


def test_reconcile_keeps_existing_pr_receipt_when_desired_head_not_published(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    key = "open-pr-codex-existing-pr-refresh-newhead"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    stale_remote_head = "1111111234567890abcdef1234567890abcdef12"
    handoff = _write_outbox_handoff(
        outbox_dir,
        branch="codex/existing-pr-refresh",
        key=key,
        local_evidence={
            "branch": "codex/existing-pr-refresh",
            "desired_head_sha": desired_head,
        },
    )
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "idempotency_key": key,
                "status": "already_satisfied",
                "reason": "existing_pr",
                "existing_pr_url": "https://github.com/synaptent/aragora/pull/7475",
            }
        ),
        encoding="utf-8",
    )

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", "refs/remotes/origin/codex/existing-pr-refresh"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=stale_remote_head)
        if args == ["rev-parse", "--verify", "codex/existing-pr-refresh"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=desired_head)
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "_target_pr_state", lambda *_args: None)
    monkeypatch.setattr(
        mod,
        "open_pr_heads",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("open PR fetch should not run for mismatched existing PR receipts")
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["blocked_receipt_pr_head_mismatch"] == 1
    assert payload["counts"]["satisfied_by_existing_receipt"] == 0
    assert payload["counts"]["still_protecting_active_work"] == 1
    assert payload["actions"][0]["decision"] == "keep"
    assert "existing_pr receipt exists" in payload["actions"][0]["reason"]
    assert "not desired head" in payload["actions"][0]["reason"]
    assert handoff.exists()
    assert not (tmp_path / ".aragora" / "automation-outbox-archive").exists()


def test_reconcile_archives_target_pr_receipt_when_pr_merged_at_desired_head(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    key = "open-pr-codex-target-pr-merged"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    handoff = _write_outbox_handoff(
        outbox_dir,
        branch="codex/target-pr-merged",
        key=key,
        local_evidence={
            "branch": "codex/target-pr-merged",
            "desired_head_sha": desired_head,
        },
    )
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "idempotency_key": key,
                "status": "already_satisfied",
                "reason": "target_open_pr",
                "existing_pr_url": "https://github.com/synaptent/aragora/pull/7105",
                "repo": "synaptent/aragora",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod,
        "_target_pr_state",
        lambda *_args: {
            "number": 7105,
            "state": "MERGED",
            "headRefOid": desired_head,
        },
    )
    monkeypatch.setattr(
        mod,
        "run_git",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("git ref checks should not run for merged target PR receipts")
        ),
    )
    monkeypatch.setattr(
        mod,
        "open_pr_heads",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("open PR fetch should not run for matched target PR receipts")
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["satisfied_by_existing_receipt"] == 1
    assert payload["counts"]["blocked_receipt_pr_head_mismatch"] == 0
    assert payload["counts"]["still_protecting_active_work"] == 0
    assert payload["actions"][0]["decision"] == "archive"
    assert payload["actions"][0]["reason"] == "matching receipt exists"
    assert handoff.exists()
    assert not (tmp_path / ".aragora" / "automation-outbox-archive").exists()


def test_reconcile_keeps_target_pr_receipt_when_merged_pr_head_differs(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    key = "open-pr-codex-target-pr-merged-mismatch"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    merged_head = "1111111234567890abcdef1234567890abcdef12"
    handoff = _write_outbox_handoff(
        outbox_dir,
        branch="codex/target-pr-merged-mismatch",
        key=key,
        local_evidence={
            "branch": "codex/target-pr-merged-mismatch",
            "desired_head_sha": desired_head,
        },
    )
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "idempotency_key": key,
                "status": "already_satisfied",
                "reason": "target_open_pr",
                "existing_pr_url": "https://github.com/synaptent/aragora/pull/7105",
                "repo": "synaptent/aragora",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        mod,
        "_target_pr_state",
        lambda *_args: {
            "number": 7105,
            "state": "MERGED",
            "headRefOid": merged_head,
        },
    )
    monkeypatch.setattr(
        mod,
        "run_git",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("git ref checks should not run for mismatched merged PR receipts")
        ),
    )
    monkeypatch.setattr(
        mod,
        "open_pr_heads",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("open PR fetch should not run for mismatched merged PR receipts")
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["blocked_receipt_pr_head_mismatch"] == 1
    assert payload["counts"]["satisfied_by_existing_receipt"] == 0
    assert payload["counts"]["still_protecting_active_work"] == 1
    assert payload["actions"][0]["decision"] == "keep"
    assert "merged PR #7105" in payload["actions"][0]["reason"]
    assert "not desired head" in payload["actions"][0]["reason"]
    assert handoff.exists()
    assert not (tmp_path / ".aragora" / "automation-outbox-archive").exists()


def test_apply_preserves_missing_branch_when_open_pr_state_unavailable(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    key = "open-pr-codex-missing-abc123"
    handoff = _write_outbox_handoff(outbox_dir, branch="codex/missing", key=key)
    receipt_dir.mkdir(parents=True)

    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _unhealthy_github())
    monkeypatch.setattr(
        mod,
        "open_pr_heads",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("open PR fetch should be skipped when GitHub is unhealthy")
        ),
    )
    monkeypatch.setattr(
        mod,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git"], returncode=128, stdout="", stderr="missing ref"
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--apply"]) == 0

    reports = sorted((tmp_path / ".aragora" / "cleanup-state").glob("*.json"))
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["counts"]["blocked_missing_branch_open_pr_unknown"] == 1
    assert payload["counts"]["missing_branch"] == 0
    assert payload["actions"][0]["decision"] == "keep"
    assert "open PR state is unavailable" in payload["actions"][0]["reason"]
    assert handoff.exists()
    assert not (receipt_dir / f"{key}.json").exists()
    assert not list((tmp_path / ".aragora" / "automation-outbox-archive").glob("*.json"))


def test_missing_branch_archives_when_open_pr_state_is_available(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-missing-abc123"
    _write_outbox_handoff(outbox_dir, branch="codex/missing", key=key)

    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    monkeypatch.setattr(
        mod,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git"], returncode=128, stdout="", stderr="missing ref"
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--write-report"]) == 0

    reports = sorted((tmp_path / ".aragora" / "cleanup-state").glob("*.json"))
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["counts"]["missing_branch"] == 1
    assert payload["counts"]["blocked_missing_branch_open_pr_unknown"] == 0
    assert payload["actions"][0]["decision"] == "archive"
    assert payload["actions"][0]["reason"] == "branch no longer exists"


def test_missing_local_branch_keeps_when_exact_remote_branch_preserves_desired_head(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-remote-preserved-abc123"
    branch = "codex/remote-preserved"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    _write_outbox_handoff(
        outbox_dir,
        branch=branch,
        key=key,
        local_evidence={
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree": str(tmp_path / "missing-worktree"),
        },
    )

    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    monkeypatch.setattr(
        mod,
        "run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git"], returncode=128, stdout="", stderr="missing ref"
        ),
    )
    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [str(tmp_path / "missing-worktree")],
            "worktree_inspections": [
                {
                    "path": str(tmp_path / "missing-worktree"),
                    "absent_noop": True,
                    "source": "safe_worktree_cleanup.inspect",
                    "classification": "absent_noop",
                }
            ],
            "upstream_preservation": {
                "proven": True,
                "method": "remote_branch_exact_head",
                "remote_head_sha": desired_head,
            },
        },
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["missing_branch"] == 0
    assert payload["counts"]["still_protecting_active_work"] == 1
    assert payload["actions"][0]["decision"] == "keep"
    assert "desired head preserved by exact remote branch" in payload["actions"][0]["reason"]


def test_missing_local_branch_keeps_when_live_remote_lookup_fails(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-remote-lookup-failed-abc123"
    branch = "codex/remote-lookup-failed"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    _write_outbox_handoff(
        outbox_dir,
        branch=branch,
        key=key,
        local_evidence={
            "branch": branch,
            "desired_head_sha": desired_head,
        },
    )

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", branch]:
            return subprocess.CompletedProcess(args=args, returncode=128, stdout="", stderr="")
        if args == ["rev-parse", "--verify", desired_head]:
            return subprocess.CompletedProcess(args=args, returncode=128, stdout="", stderr="")
        if args == ["ls-remote", "origin", f"refs/heads/{branch}"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=128,
                stdout="",
                stderr="could not read from remote repository",
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    monkeypatch.setattr(mod, "run_git", fake_run_git)

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["blocked_missing_branch_remote_unknown"] == 1
    assert payload["counts"]["missing_branch"] == 0
    assert payload["counts"]["still_protecting_active_work"] == 1
    assert payload["actions"][0]["decision"] == "keep"
    assert "live remote branch state" in payload["actions"][0]["reason"]
    assert "unavailable" in payload["actions"][0]["reason"]


def test_unique_branch_keep_reason_notes_unavailable_open_pr_state(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-unique-abc123"
    _write_outbox_handoff(outbox_dir, branch="codex/unique", key=key)

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", "codex/unique"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="abc123\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="")
        if args[0] == "cherry":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="+ abc123\n")
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _unhealthy_github())
    monkeypatch.setattr(
        mod,
        "open_pr_heads",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("open PR fetch should be skipped when GitHub is unhealthy")
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["still_protecting_active_work"] == 1
    assert payload["actions"][0]["decision"] == "keep"
    assert "open PR state is unavailable" in payload["actions"][0]["reason"]
    assert "no open PR" not in payload["actions"][0]["reason"]


def test_unique_non_codex_branch_is_protected_by_open_pr(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-structex-p2-docs-ci-tooling-docs-sync-repair-20260616-e806c51e"
    branch = "structex/p2-docs-ci-tooling"
    _write_outbox_handoff(outbox_dir, branch=branch, key=key)

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", branch]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="e806c51e\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="")
        if args[0] == "cherry":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="+ e806c51e\n")
        raise AssertionError(f"unexpected git call: {args}")

    def fake_open_pr_heads(_root: Path, _repo: str, prefix: str) -> dict[str, int]:
        return {branch: 8501} if prefix == "" else {}

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", fake_open_pr_heads)

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["still_protecting_active_work"] == 1
    assert payload["actions"][0]["decision"] == "keep"
    assert payload["actions"][0]["reason"] == "branch has open PR #8501"


def test_unique_branch_archives_when_desired_head_is_patch_equivalent_to_main(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-merged-pr-proof-abc123"
    branch = "codex/merged-pr-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    _write_outbox_handoff(
        outbox_dir,
        branch=branch,
        key=key,
        local_evidence={
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree": str(tmp_path / "missing-worktree"),
        },
    )

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", branch]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{desired_head}\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        if args[0] == "cherry":
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=f"- {desired_head}\n"
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    monkeypatch.setattr(mod, "_gh_api_paginated_items", lambda *_args: [])
    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [str(tmp_path / "missing-worktree")],
            "worktree_inspections": [
                {
                    "path": str(tmp_path / "missing-worktree"),
                    "absent_noop": True,
                    "source": "safe_worktree_cleanup.inspect",
                    "classification": "absent_noop",
                }
            ],
            "upstream_preservation": {
                "proven": True,
                "method": "merged_pr_commit_list",
                "pr_number": 8583,
                "repo": "synaptent/aragora",
                "base_ref": "main",
            },
        },
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["satisfied_by_landed_on_main"] == 1
    assert payload["counts"]["still_protecting_active_work"] == 0
    assert payload["actions"][0]["decision"] == "archive"
    assert (
        payload["actions"][0]["reason"] == "branch work landed on main (merge or patch-equivalent)"
    )


def test_unique_branch_keeps_when_preservation_proof_is_remote_branch_only(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-remote-only-proof-abc123"
    branch = "codex/remote-only-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    _write_outbox_handoff(
        outbox_dir,
        branch=branch,
        key=key,
        local_evidence={
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree": str(tmp_path / "missing-worktree"),
        },
    )

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", branch]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{desired_head}\n")
        if args == ["rev-parse", "--verify", desired_head]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{desired_head}\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0 if args[2] == desired_head else 1,
                stdout="",
                stderr="",
            )
        if args[0] == "cherry":
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=f"+ {desired_head}\n"
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [str(tmp_path / "missing-worktree")],
            "worktree_inspections": [
                {
                    "path": str(tmp_path / "missing-worktree"),
                    "absent_noop": True,
                    "source": "safe_worktree_cleanup.inspect",
                    "classification": "absent_noop",
                }
            ],
            "upstream_preservation": {
                "proven": True,
                "method": "remote_branch_exact_head",
                "remote_head_sha": desired_head,
            },
        },
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["satisfied_by_merged_pr_commit_proof"] == 0
    assert payload["counts"]["still_protecting_active_work"] == 1
    assert payload["actions"][0]["decision"] == "keep"
    assert "actively protecting" in payload["actions"][0]["reason"]


def test_remote_branch_preservation_proof_accepts_head_only_exact_remote_head(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    branch = "codex/head-only-remote-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    payload = {
        "requested_action": {"type": "open_pr", "branch": branch},
        "local_evidence": {
            "branch": branch,
            "desired_head_sha": desired_head,
        },
    }

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["ls-remote", "origin", f"refs/heads/{branch}"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=f"{desired_head}\trefs/heads/{branch}\n",
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("head-only proof should not call worktree preservation")
        ),
    )

    proof = mod._remote_branch_exact_preservation_proof(
        root=tmp_path,
        state_root=tmp_path,
        payload=payload,
        branch=branch,
    )

    assert proof is not None
    assert proof["available"] is True
    assert proof["upstream_preservation"]["proven"] is True
    assert proof["upstream_preservation"]["method"] == "remote_branch_exact_head"
    assert proof["upstream_preservation"]["source"] == "git_ls_remote"


def test_remote_branch_preservation_proof_rejects_stale_head_only_tracking_ref(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    branch = "codex/head-only-stale-remote-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    live_remote_head = "1111111234567890abcdef1234567890abcdef12"
    payload = {
        "requested_action": {"type": "open_pr", "branch": branch},
        "local_evidence": {
            "branch": branch,
            "desired_head_sha": desired_head,
        },
    }

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["ls-remote", "origin", f"refs/heads/{branch}"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=f"{live_remote_head}\trefs/heads/{branch}\n",
            )
        if args == ["rev-parse", "--verify", f"refs/remotes/origin/{branch}"]:
            raise AssertionError("head-only remote proof must not trust local tracking refs")
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("head-only proof should not call worktree preservation")
        ),
    )

    proof = mod._remote_branch_exact_preservation_proof(
        root=tmp_path,
        state_root=tmp_path,
        payload=payload,
        branch=branch,
    )

    assert proof is None


def test_remote_branch_preservation_proof_rejects_head_only_prefix_match(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    branch = "codex/head-only-prefix-proof"
    full_remote_head = "abcdef1234567890abcdef1234567890abcdef12"
    payload = {
        "requested_action": {"type": "open_pr", "branch": branch},
        "local_evidence": {
            "branch": branch,
            "desired_head_sha": full_remote_head[:12],
        },
    }

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["ls-remote", "origin", f"refs/heads/{branch}"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=f"{full_remote_head}\trefs/heads/{branch}\n",
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)

    proof = mod._remote_branch_exact_preservation_proof(
        root=tmp_path,
        state_root=tmp_path,
        payload=payload,
        branch=branch,
    )

    assert proof is None


def test_remote_branch_preservation_proof_rejects_malformed_live_remote_head(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    branch = "codex/head-only-malformed-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    payload = {
        "requested_action": {"type": "open_pr", "branch": branch},
        "local_evidence": {
            "branch": branch,
            "desired_head_sha": desired_head,
        },
    }

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["ls-remote", "origin", f"refs/heads/{branch}"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout=f"not-a-sha\trefs/heads/{branch}\n",
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)

    proof = mod._remote_branch_exact_preservation_proof(
        root=tmp_path,
        state_root=tmp_path,
        payload=payload,
        branch=branch,
    )

    assert proof is None


def test_remote_branch_preservation_proof_rejects_head_only_local_work_marker(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    branch = "codex/head-only-dirty-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    payload = {
        "requested_action": {"type": "open_pr", "branch": branch},
        "local_evidence": {
            "branch": branch,
            "desired_head_sha": desired_head,
            "unpushed_commits": True,
        },
    }

    monkeypatch.setattr(
        mod,
        "run_git",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dirty head-only evidence must fail before git lookup")
        ),
    )
    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dirty head-only evidence must fail before worktree proof")
        ),
    )

    proof = mod._remote_branch_exact_preservation_proof(
        root=tmp_path,
        state_root=tmp_path,
        payload=payload,
        branch=branch,
    )

    assert proof is None


def test_remote_branch_preservation_proof_checks_all_local_evidence_records(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    branch = "codex/multi-remote-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    payload = {
        "requested_action": {"type": "open_pr", "branch": branch},
        "local_evidence": [
            {
                "branch": branch,
                "desired_head_sha": desired_head,
                "worktree": str(tmp_path / "missing-worktree"),
            },
            {
                "branch": branch,
                "desired_head_sha": desired_head,
                "unpushed_commits": True,
            },
        ],
    }

    def fake_preservation_proof(record: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        assert record.get("worktree")
        return {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [str(record["worktree"])],
            "worktree_inspections": [
                {
                    "path": str(record["worktree"]),
                    "absent_noop": True,
                    "source": "safe_worktree_cleanup.inspect",
                    "classification": "absent_noop",
                }
            ],
            "upstream_preservation": {
                "proven": True,
                "method": "remote_branch_exact_head",
                "remote_head_sha": desired_head,
            },
        }

    monkeypatch.setattr(mod, "build_worktree_reference_preservation_proof", fake_preservation_proof)
    monkeypatch.setattr(
        mod,
        "run_git",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dirty second record must fail before git lookup")
        ),
    )

    proof = mod._remote_branch_exact_preservation_proof(
        root=tmp_path,
        state_root=tmp_path,
        payload=payload,
        branch=branch,
    )

    assert proof is None


def test_remote_branch_preservation_proof_requires_upstream_proven(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    branch = "codex/unproven-remote-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    payload = {
        "requested_action": {"type": "open_pr", "branch": branch},
        "local_evidence": {
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree": str(tmp_path / "missing-worktree"),
        },
    }

    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [str(tmp_path / "missing-worktree")],
            "upstream_preservation": {
                "proven": False,
                "method": "remote_branch_exact_head",
                "remote_head_sha": desired_head,
            },
        },
    )

    proof = mod._remote_branch_exact_preservation_proof(
        root=tmp_path,
        state_root=tmp_path,
        payload=payload,
        branch=branch,
    )

    assert proof is None


def test_remote_branch_preservation_proof_requires_absent_worktree_inspection(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    branch = "codex/missing-absent-inspection-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    payload = {
        "requested_action": {"type": "open_pr", "branch": branch},
        "local_evidence": {
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree": str(tmp_path / "missing-worktree"),
        },
    }

    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [str(tmp_path / "missing-worktree")],
            "upstream_preservation": {
                "proven": True,
                "method": "remote_branch_exact_head",
                "remote_head_sha": desired_head,
            },
        },
    )

    proof = mod._remote_branch_exact_preservation_proof(
        root=tmp_path,
        state_root=tmp_path,
        payload=payload,
        branch=branch,
    )

    assert proof is None


def test_merged_pr_preservation_proof_rejects_non_base_pr(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    branch = "codex/feature-base-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    payload = {
        "requested_action": {"type": "open_pr", "branch": branch, "base": "main"},
        "local_evidence": {
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree": str(tmp_path / "missing-worktree"),
        },
    }

    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [str(tmp_path / "missing-worktree")],
            "upstream_preservation": {
                "proven": True,
                "method": "merged_pr_commit_list",
                "pr_number": 8583,
                "repo": "synaptent/aragora",
                "base_ref": "codex/feature-integration",
            },
        },
    )

    proof = mod._merged_pr_commit_preservation_proof(
        root=tmp_path,
        state_root=tmp_path,
        payload=payload,
        branch=branch,
        repo_name="synaptent/aragora",
        base="origin/main",
    )

    assert proof is None


def test_merged_pr_preservation_proof_checks_all_local_evidence_worktrees(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    branch = "codex/multi-worktree-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    worktrees = [tmp_path / "missing-worktree-a", tmp_path / "missing-worktree-b"]
    payload = {
        "requested_action": {"type": "open_pr", "branch": branch, "base": "main"},
        "local_evidence": [
            {"branch": branch, "desired_head_sha": desired_head, "worktree": str(worktrees[0])},
            {"branch": branch, "desired_head_sha": desired_head, "worktree": str(worktrees[1])},
        ],
    }

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", branch]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{desired_head}\n")
        if args == ["rev-parse", "--verify", desired_head]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{desired_head}\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0 if args[2] == desired_head else 1,
                stdout="",
                stderr="",
            )
        if args[0] == "cherry":
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=f"+ {desired_head}\n"
            )
        raise AssertionError(f"unexpected git call: {args}")

    seen_worktrees: list[str] = []

    def fake_preservation_proof(record: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        worktree = str(record.get("worktree") or "")
        seen_worktrees.append(worktree)
        return {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [worktree],
            "upstream_preservation": {
                "proven": True,
                "method": "merged_pr_commit_list",
                "pr_number": 8583,
                "repo": "synaptent/aragora",
                "base_ref": "main",
            },
        }

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "build_worktree_reference_preservation_proof", fake_preservation_proof)

    proof = mod._merged_pr_commit_preservation_proof(
        root=tmp_path,
        state_root=tmp_path,
        payload=payload,
        branch=branch,
        repo_name="synaptent/aragora",
        base="origin/main",
    )

    assert sorted(seen_worktrees) == sorted(str(path) for path in worktrees)
    assert proof is not None
    assert len(proof["worktree_proofs"]) == 2


def test_unique_branch_archives_when_merged_pr_proof_is_squash_merged(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-remote-and-merged-proof-abc123"
    branch = "codex/remote-and-merged-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    _write_outbox_handoff(
        outbox_dir,
        branch=branch,
        key=key,
        local_evidence={
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree": str(tmp_path / "missing-worktree"),
        },
    )

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", branch]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{desired_head}\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        if args[0] == "cherry":
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=f"+ {desired_head}\n"
            )
        raise AssertionError(f"unexpected git call: {args}")

    def fake_gh_items(_root: Path, endpoint: str) -> list[dict[str, Any]]:
        if endpoint == f"repos/synaptent/aragora/commits/{desired_head}/pulls":
            return [
                {
                    "number": 8583,
                    "merged_at": "2026-06-24T00:00:00Z",
                    "base": {"ref": "main"},
                }
            ]
        if endpoint == "repos/synaptent/aragora/pulls/8583/commits?per_page=100":
            return [
                {"sha": "1111111111111111111111111111111111111111"},
                {"sha": desired_head},
            ]
        raise AssertionError(f"unexpected gh endpoint: {endpoint}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    monkeypatch.setattr(mod, "_gh_api_paginated_items", fake_gh_items)
    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [str(tmp_path / "missing-worktree")],
            "worktree_inspections": [
                {
                    "path": str(tmp_path / "missing-worktree"),
                    "absent_noop": True,
                    "source": "safe_worktree_cleanup.inspect",
                    "classification": "absent_noop",
                }
            ],
            "upstream_preservation": {
                "proven": True,
                "method": "remote_branch_exact_head",
                "remote_head_sha": desired_head,
            },
        },
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["satisfied_by_merged_pr_commit_proof"] == 1
    assert payload["counts"]["still_protecting_active_work"] == 0
    assert payload["actions"][0]["decision"] == "archive"
    assert "merged PR commit list (PR #8583)" in payload["actions"][0]["reason"]


def test_missing_local_branch_archives_before_remote_exact_keep_when_merged_pr_proves_head(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-missing-local-merged-proof-abc123"
    branch = "codex/missing-local-merged-proof"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    _write_outbox_handoff(
        outbox_dir,
        branch=branch,
        key=key,
        local_evidence={
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree": str(tmp_path / "missing-worktree"),
        },
    )

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", branch]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        if args == ["ls-remote", "origin", f"refs/heads/{branch}"]:
            raise AssertionError("merged PR proof should run before exact remote keep")
        raise AssertionError(f"unexpected git call: {args}")

    def fake_gh_items(_root: Path, endpoint: str) -> list[dict[str, Any]]:
        if endpoint == f"repos/synaptent/aragora/commits/{desired_head}/pulls":
            return [
                {
                    "number": 8583,
                    "merged_at": "2026-06-24T00:00:00Z",
                    "base": {"ref": "main"},
                }
            ]
        if endpoint == "repos/synaptent/aragora/pulls/8583/commits?per_page=100":
            return [
                {"sha": "1111111111111111111111111111111111111111"},
                {"sha": desired_head},
            ]
        raise AssertionError(f"unexpected gh endpoint: {endpoint}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    monkeypatch.setattr(mod, "_gh_api_paginated_items", fake_gh_items)
    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: {
            "available": True,
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree_paths": [str(tmp_path / "missing-worktree")],
            "worktree_inspections": [
                {
                    "path": str(tmp_path / "missing-worktree"),
                    "absent_noop": True,
                    "source": "safe_worktree_cleanup.inspect",
                    "classification": "absent_noop",
                }
            ],
            "upstream_preservation": {
                "proven": True,
                "method": "remote_branch_exact_head",
                "remote_head_sha": desired_head,
            },
        },
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["satisfied_by_merged_pr_commit_proof"] == 1
    assert payload["counts"]["missing_branch"] == 0
    assert payload["counts"]["still_protecting_active_work"] == 0
    assert payload["actions"][0]["decision"] == "archive"
    assert payload["actions"][0]["synthetic_receipt"] is True
    assert "merged PR commit list (PR #8583)" in payload["actions"][0]["reason"]


def test_unique_branch_keeps_head_only_handoff_with_top_level_local_work_marker(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-head-only-dirty-abc123"
    branch = "codex/head-only-dirty"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    handoff = _write_outbox_handoff(
        outbox_dir,
        branch=branch,
        key=key,
        local_evidence={
            "branch": branch,
            "desired_head_sha": desired_head,
        },
    )
    payload = json.loads(handoff.read_text(encoding="utf-8"))
    payload["dirty"] = True
    handoff.write_text(json.dumps(payload), encoding="utf-8")

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", branch]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{desired_head}\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        if args[0] == "cherry":
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=f"+ {desired_head}\n"
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("dirty head-only handoff must fail before worktree proof")
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["satisfied_by_merged_pr_commit_proof"] == 0
    assert result["counts"]["still_protecting_active_work"] == 1
    assert result["actions"][0]["decision"] == "keep"


def test_unique_branch_keeps_when_preservation_proof_is_unavailable(
    tmp_path: Path,
    monkeypatch: Any,
    capsys: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-proof-unavailable-abc123"
    branch = "codex/proof-unavailable"
    desired_head = "abcdef1234567890abcdef1234567890abcdef12"
    _write_outbox_handoff(
        outbox_dir,
        branch=branch,
        key=key,
        local_evidence={
            "branch": branch,
            "desired_head_sha": desired_head,
            "worktree": str(tmp_path / "missing-worktree"),
        },
    )

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", branch]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout=f"{desired_head}\n")
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        if args[0] == "cherry":
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout=f"+ {desired_head}\n"
            )
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(mod, "check_github_cli_health", lambda _root: _ready_github())
    monkeypatch.setattr(mod, "open_pr_heads", lambda *_args: {})
    monkeypatch.setattr(
        mod,
        "build_worktree_reference_preservation_proof",
        lambda *_args, **_kwargs: {
            "available": False,
            "reason": "upstream_preservation_unproven",
        },
    )

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["satisfied_by_merged_pr_commit_proof"] == 0
    assert payload["counts"]["still_protecting_active_work"] == 1
    assert payload["actions"][0]["decision"] == "keep"
    assert "actively protecting" in payload["actions"][0]["reason"]


def test_landed_branch_archives_without_github_lookup(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    key = "open-pr-codex-landed-abc123"
    _write_outbox_handoff(outbox_dir, branch="codex/landed", key=key)

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["rev-parse", "--verify"]:
            return subprocess.CompletedProcess(
                args=args, returncode=0, stdout="abc123\n", stderr=""
            )
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(
        mod,
        "check_github_cli_health",
        lambda _root: (_ for _ in ()).throw(
            AssertionError("GitHub should not be queried for locally landed work")
        ),
    )
    monkeypatch.setattr(
        mod,
        "open_pr_heads",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("open PR fetch should not run for locally landed work")
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--write-report"]) == 0

    reports = sorted((tmp_path / ".aragora" / "cleanup-state").glob("*.json"))
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["counts"]["satisfied_by_landed_on_main"] == 1
    assert payload["counts"]["still_protecting_active_work"] == 0
    assert payload["actions"][0]["decision"] == "archive"
    assert (
        payload["actions"][0]["reason"] == "branch work landed on main (merge or patch-equivalent)"
    )


def test_patch_equivalent_target_pr_receipt_archives_before_remote_check(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    key = "open-pr-codex-patch-equivalent-target-pr-abc123"
    _write_outbox_handoff(
        outbox_dir,
        branch="codex/landed-patch",
        key=key,
        local_evidence={"desired_head_sha": "abc1234"},
    )
    receipt_dir.mkdir(parents=True)
    (receipt_dir / f"{key}.json").write_text(
        json.dumps(
            {
                "idempotency_key": key,
                "reason": "target_open_pr",
                "status": "already_satisfied",
            }
        ),
        encoding="utf-8",
    )

    def fake_run_git(
        args: list[str],
        _root: Path,
        *,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rev-parse", "--verify", "refs/remotes/origin/codex/landed-patch"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        if args == ["rev-parse", "--verify", "codex/landed-patch"]:
            return subprocess.CompletedProcess(
                args=args,
                returncode=0,
                stdout="abc1234567890\n",
                stderr="",
            )
        if args[:2] == ["merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
        if args[0] == "cherry":
            return subprocess.CompletedProcess(args=args, returncode=0, stdout="- abc1234\n")
        raise AssertionError(f"unexpected git call: {args}")

    monkeypatch.setattr(mod, "run_git", fake_run_git)
    monkeypatch.setattr(
        mod,
        "check_github_cli_health",
        lambda _root: (_ for _ in ()).throw(
            AssertionError("GitHub should not be queried for patch-equivalent work")
        ),
    )
    monkeypatch.setattr(
        mod,
        "open_pr_heads",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("open PR fetch should not run for patch-equivalent work")
        ),
    )

    assert mod.main(["--repo", str(tmp_path), "--write-report"]) == 0

    reports = sorted((tmp_path / ".aragora" / "cleanup-state").glob("*.json"))
    payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert payload["counts"]["satisfied_by_landed_on_main"] == 1
    assert payload["counts"]["blocked_receipt_pr_head_mismatch"] == 0
    assert payload["counts"]["still_protecting_active_work"] == 0
    assert payload["actions"][0]["decision"] == "archive"
    assert (
        payload["actions"][0]["reason"] == "branch work landed on main (merge or patch-equivalent)"
    )


def _write_existing_issue_deadlock_fixture(
    tmp_path: Path,
    *,
    key: str = "open-pr-codex-existing-issue-deadlock-abc123",
    branch: str = "codex/existing-issue-deadlock",
    created_at: str = "2026-06-01T00:00:00+00:00",
    issue_url: str = "https://github.com/synaptent/aragora/issues/7808",
    receipt_reason: str = "existing_issue",
    receipt_status: str = "already_satisfied",
) -> tuple[Path, Path]:
    """Write an outbox handoff + receipt pair representing the archival deadlock."""
    outbox_dir = tmp_path / ".aragora" / "automation-outbox"
    receipt_dir = tmp_path / ".aragora" / "automation-receipts"
    handoff = _write_outbox_handoff(outbox_dir, branch=branch, key=key)
    payload = json.loads(handoff.read_text(encoding="utf-8"))
    payload["requested_action"] = {
        "type": "open_or_update_pr",
        "base": "main",
        "branch": branch,
        "desired_head_sha": "abcdef1234567890abcdef1234567890abcdef12",
    }
    payload["created_at"] = created_at
    handoff.write_text(json.dumps(payload), encoding="utf-8")
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{key}.json"
    receipt_path.write_text(
        json.dumps(
            {
                "idempotency_key": key,
                "status": receipt_status,
                "reason": receipt_reason,
                "existing_issue_url": issue_url,
                "existing_pr_url": None,
                "recorded_at": "2026-06-12T02:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return handoff, receipt_path


def _issue_state_response(
    *,
    number: int = 7808,
    state: str = "OPEN",
    state_reason: str = "",
    url: str = "https://github.com/synaptent/aragora/issues/7808",
) -> dict[str, Any]:
    return {"number": number, "state": state, "stateReason": state_reason, "url": url}


def _patch_issue_state(monkeypatch: Any, response: dict[str, Any] | None) -> list[Any]:
    """Patch the gh-backed issue lookup; record calls. None simulates gh failure."""
    calls: list[Any] = []

    def fake_fetch(self: Any, repo: str, number: int) -> tuple[dict[str, Any] | None, str | None]:
        calls.append((repo, number))
        if response is None:
            return None, "gh issue view exited 1: connectivity failed"
        return response, None

    monkeypatch.setattr(mod._IssueStateChecker, "_fetch", fake_fetch)
    return calls


def test_existing_issue_deadlock_archives_with_terminal_receipt(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    handoff, _receipt = _write_existing_issue_deadlock_fixture(tmp_path)
    calls = _patch_issue_state(monkeypatch, _issue_state_response())
    archive_dir = tmp_path / ".aragora" / "automation-outbox-archive"

    assert mod.main(["--repo", str(tmp_path), "--apply", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["archived_superseded_by_existing_issue"] == 1
    assert result["counts"]["blocked_receipt_issue_only"] == 0
    assert calls == [("synaptent/aragora", 7808)]
    assert not handoff.exists()

    archived = json.loads((archive_dir / handoff.name).read_text(encoding="utf-8"))
    disposition = archived["terminal_disposition"]
    assert disposition["disposition"] == "superseded_by_existing_issue"
    assert disposition["issue_url"] == "https://github.com/synaptent/aragora/issues/7808"
    assert disposition["issue_state"] == "OPEN"
    assert disposition["decision_evidence"]["publisher_decision"] == "existing_issue"
    assert disposition["decision_evidence"]["receipt_reason"] == "existing_issue"
    assert disposition["item_age_days"] >= 3.0
    assert disposition["issue_state_checked_at"]
    assert "__source_file" not in archived


def test_existing_issue_archive_accepts_closed_completed_issue(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    handoff, _receipt = _write_existing_issue_deadlock_fixture(tmp_path)
    _patch_issue_state(monkeypatch, _issue_state_response(state="CLOSED", state_reason="COMPLETED"))

    assert mod.main(["--repo", str(tmp_path), "--apply", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["archived_superseded_by_existing_issue"] == 1
    assert not handoff.exists()


def test_existing_issue_archive_refuses_not_planned_issue(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    handoff, _receipt = _write_existing_issue_deadlock_fixture(tmp_path)
    _patch_issue_state(
        monkeypatch, _issue_state_response(state="CLOSED", state_reason="NOT_PLANNED")
    )

    assert mod.main(["--repo", str(tmp_path), "--apply", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["archived_superseded_by_existing_issue"] == 0
    assert result["counts"]["blocked_receipt_issue_only"] == 1
    assert result["counts"]["still_protecting_active_work"] == 1
    assert handoff.exists()
    assert "CLOSED/NOT_PLANNED" in result["actions"][0]["reason"]


def test_existing_issue_archive_refuses_when_issue_state_unverifiable(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    handoff, _receipt = _write_existing_issue_deadlock_fixture(tmp_path)
    _patch_issue_state(monkeypatch, None)

    assert mod.main(["--repo", str(tmp_path), "--apply", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["archived_superseded_by_existing_issue"] == 0
    assert result["counts"]["blocked_receipt_issue_only"] == 1
    assert handoff.exists()
    assert "issue state unverified" in result["actions"][0]["reason"]


def test_existing_issue_archive_refuses_young_items(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    from datetime import datetime, timedelta

    recent = (datetime.now(mod.UTC) - timedelta(hours=6)).isoformat()
    handoff, _receipt = _write_existing_issue_deadlock_fixture(tmp_path, created_at=recent)
    calls = _patch_issue_state(monkeypatch, _issue_state_response())

    assert mod.main(["--repo", str(tmp_path), "--apply", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["archived_superseded_by_existing_issue"] == 0
    assert result["counts"]["blocked_receipt_issue_only"] == 1
    assert handoff.exists()
    assert calls == []  # age gate blocks before any gh call
    assert "item age" in result["actions"][0]["reason"]


def test_existing_issue_archive_honors_per_pass_cap(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    handoffs = []
    for index in range(3):
        handoff, _receipt = _write_existing_issue_deadlock_fixture(
            tmp_path,
            key=f"open-pr-codex-existing-issue-cap-{index:02d}",
            branch=f"codex/existing-issue-cap-{index}",
        )
        handoffs.append(handoff)
    _patch_issue_state(monkeypatch, _issue_state_response())

    assert (
        mod.main(
            [
                "--repo",
                str(tmp_path),
                "--apply",
                "--json",
                "--existing-issue-archive-cap",
                "2",
            ]
        )
        == 0
    )

    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["archived_superseded_by_existing_issue"] == 2
    assert result["counts"]["blocked_receipt_issue_only"] == 1
    assert result["existing_issue_policy"]["archived_this_pass"] == 2
    assert sum(1 for h in handoffs if h.exists()) == 1
    capped = [a for a in result["actions"] if "per-pass archive cap 2 reached" in a["reason"]]
    assert len(capped) == 1 and capped[0]["decision"] == "keep"


def test_existing_issue_dry_run_lists_would_archive_without_moving(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    handoff, _receipt = _write_existing_issue_deadlock_fixture(tmp_path)
    _patch_issue_state(monkeypatch, _issue_state_response())
    archive_dir = tmp_path / ".aragora" / "automation-outbox-archive"

    assert mod.main(["--repo", str(tmp_path), "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["dry_run"] is True
    assert result["counts"]["archived_superseded_by_existing_issue"] == 1
    action = result["actions"][0]
    assert action["decision"] == "archive"
    assert action["terminal_disposition"]["disposition"] == "superseded_by_existing_issue"
    assert handoff.exists()
    assert not archive_dir.exists() or not list(archive_dir.iterdir())


def test_existing_issue_valve_ignores_non_existing_issue_receipts(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    """The new path must never archive an item whose decision is not existing_issue."""
    handoff, _receipt = _write_existing_issue_deadlock_fixture(
        tmp_path, receipt_reason="created_issue"
    )
    calls = _patch_issue_state(monkeypatch, _issue_state_response())

    assert mod.main(["--repo", str(tmp_path), "--apply", "--json"]) == 0

    result = json.loads(capsys.readouterr().out)
    assert result["counts"]["archived_superseded_by_existing_issue"] == 0
    assert result["counts"]["blocked_receipt_issue_only"] == 1
    assert handoff.exists()
    assert calls == []


def test_issue_state_checker_circuit_stops_after_repeated_failures(
    tmp_path: Path, monkeypatch: Any
) -> None:
    checker = mod._IssueStateChecker(tmp_path, "synaptent/aragora")
    attempts: list[int] = []

    def failing_fetch(
        self: Any, repo: str, number: int
    ) -> tuple[dict[str, Any] | None, str | None]:
        attempts.append(number)
        return None, "boom"

    monkeypatch.setattr(mod._IssueStateChecker, "_fetch", failing_fetch)
    for number in range(1, 6):
        state, error = checker.state(f"https://github.com/synaptent/aragora/issues/{number}", {})
        assert state is None
        assert error
    assert attempts == [1, 2, 3]


def test_issue_number_from_url_parsing() -> None:
    assert mod._issue_number_from_url("https://github.com/o/r/issues/123") == 123
    assert mod._issue_number_from_url("https://github.com/o/r/issues/123/") == 123
    assert mod._issue_number_from_url("https://github.com/o/r/pull/123") is None
    assert mod._issue_number_from_url("") is None
