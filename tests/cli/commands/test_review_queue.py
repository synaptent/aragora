"""Tests for aragora review-queue packet + settlement flows."""

from __future__ import annotations

import argparse
import io
import json
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from aragora.cli.commands.review_queue import (
    ADVISORY_NOTE,
    HIGH_RISK_PATHS,
    LARGE_DIFF_THRESHOLD,
    MODEL_REVIEW_QUEUE_CAP,
    PARKED_LABELS,
    QueueItem,
    ReviewPacket,
    _build_merge_authorization_packet,
    _build_model_review_quorum,
    _build_packet,
    _build_queue,
    _classify_pr,
    _classify_model_review_tier,
    _dogfood_evidence_from_comments,
    _has_blocking_or_negative_verdict,
    _extract_validation_commands,
    _effective_required_pr_check_count,
    _filter_lanes,
    _GhError,
    _gh_json,
    _gh_text,
    _is_high_risk_path,
    _is_github_transport_error,
    _is_merge_quorum_check,
    _parse_pr_number,
    _record_external_settlement,
    _render_merge_authorization_packet,
    _render_packet,
    _requested_action,
    _settle_packet,
    _subsystem_for,
    _summarize_checks,
    _summarize_required_pr_checks,
    add_review_queue_parser,
    cmd_review_queue,
)
from aragora.cli.commands import review_queue_tier4_settlement as tier4_settlement
from aragora.cli.commands import review_queue_rest_fallback as rest_fallback
from aragora.review import (
    EvidenceKind,
    EvidenceRef,
    FindingCategory,
    FindingSeverity,
    Recommendation,
    ReviewerFinding,
    ReviewerOutput,
)
from aragora.swarm.pr_review_protocol import EXECUTED_PROTOCOL_STATUS
from aragora.triage.auto_handle_calibration import AutoHandleDriftAlert


# --- Synthetic PR payload builder ------------------------------------------


def _make_pr(
    *,
    number: int = 1,
    title: str = "test PR",
    state: str = "OPEN",
    merged_at: str = "",
    is_draft: bool = False,
    mergeable: str = "MERGEABLE",
    review_decision: str = "",
    labels: list[str] | None = None,
    additions: int = 10,
    deletions: int = 5,
    changed_files: int = 2,
    checks: list[dict[str, Any]] | None = None,
    files: list[str] | None = None,
    author: str = "an0mium",
    body: str = "",
    merge_state_status: str = "CLEAN",
) -> dict[str, Any]:
    """Build a synthetic gh-pr-list-style payload."""
    return {
        "number": number,
        "title": title,
        "url": f"https://github.com/synaptent/aragora/pull/{number}",
        "state": state,
        "mergedAt": merged_at,
        "headRefName": f"branch-{number}",
        "headRefOid": f"sha{number:08d}",
        "baseRefName": "main",
        "baseRefOid": "basesha0001",
        "isDraft": is_draft,
        "mergeable": mergeable,
        "mergeStateStatus": merge_state_status,
        "reviewDecision": review_decision,
        "labels": [{"name": lab} for lab in (labels or [])],
        "author": {"login": author},
        "additions": additions,
        "deletions": deletions,
        "changedFiles": changed_files,
        "statusCheckRollup": checks
        or [{"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"}],
        "files": [{"path": p} for p in (files or [])],
        "body": body,
    }


def _make_reviewer_output(
    *,
    slot_id: str,
    provider: str,
    family: str,
    recommendation: Recommendation,
) -> ReviewerOutput:
    return ReviewerOutput(
        reviewer_id=f"{provider}:{slot_id}",
        slot_id=slot_id,
        provider=provider,
        lens="core" if slot_id in {"logic", "security"} else "heterodox",
        family=family,
        recommendation_class=recommendation,
        confidence=0.63,
        summary=f"{slot_id} summary",
        top_findings=(
            ReviewerFinding(
                category=FindingCategory.VALIDATION,
                severity=FindingSeverity.MEDIUM,
                claim=f"{slot_id} reviewed the diff",
                evidence=(f"{slot_id} evidence",),
                files=(),
            ),
        ),
        evidence_refs=(
            EvidenceRef(
                kind=EvidenceKind.FILE,
                path=f"aragora/{slot_id}.py",
                line_range=(1, 2),
                quote="example",
            ),
        ),
        risk_flags=(),
        open_questions=(),
        round_index=1,
        latency_ms=100,
        cost_usd=0.2,
    )


def _write_admin_squash_receipt(
    review_queue_root: Path,
    *,
    pr_number: int,
    head_sha: str,
) -> Path:
    receipts_dir = review_queue_root / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    path = receipts_dir / f"pr-{pr_number}-recorded-{head_sha[:12]}-admin_squash_merge.json"
    path.write_text(
        json.dumps(
            {
                "pr_number": pr_number,
                "head_sha": head_sha,
                "action": "admin_squash_merge",
                "github_event": "ADMIN_SQUASH_MERGE",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _write_human_risk_settlement_receipt(
    review_queue_root: Path,
    *,
    pr_number: int,
    head_sha: str,
    action: str = "approve",
    github_event: str = "APPROVE",
    payload_pr_number: int | None = None,
) -> Path:
    receipts_dir = review_queue_root / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    path = receipts_dir / f"pr-{pr_number}-recorded-{head_sha[:12]}-approve.json"
    path.write_text(
        json.dumps(
            {
                "pr_number": pr_number if payload_pr_number is None else payload_pr_number,
                "head_sha": head_sha,
                "action": action,
                "github_event": github_event,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _dogfood_comment(
    body: str = "## Cross-author adversarial dogfood (Claude)\n6/6 pass",
) -> dict[str, Any]:
    return {"author": {"login": "an0mium"}, "body": body}


def _codex_openai_body(
    heading: str = "## Codex focused dogfood",
    body: str = "local checks pass",
) -> str:
    return (
        f"{heading}\n\n"
        "**Reviewer harness:** codex\n"
        "**Model family:** openai\n"
        "**Model id:** gpt-5-codex\n"
        "**Receipt artifact:** /tmp/codex-review.md\n\n"
        f"{body}"
    )


def _codex_openai_comment(
    *,
    heading: str = "## Codex focused dogfood",
    body: str = "local checks pass",
    created_at: str | None = None,
) -> dict[str, Any]:
    comment = _dogfood_comment(_codex_openai_body(heading=heading, body=body))
    if created_at is not None:
        comment["createdAt"] = created_at
    return comment


def _codex_openai_review_comment(
    *,
    body: str = "Verdict: approve.\nFocused adversarial dogfood passed.",
    created_at: str | None = None,
) -> dict[str, Any]:
    return _codex_openai_comment(heading="## Codex review", body=body, created_at=created_at)


def _executed_protocol(*, dissent: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": EXECUTED_PROTOCOL_STATUS,
        "validation_summary": {
            "reviewer_execution": {
                "status": EXECUTED_PROTOCOL_STATUS,
                "reviewer_count": 3,
                "reviewer_ids": ["claude:logic", "openai-api:security", "gemini:maintainability"],
                "providers": ["claude", "openai-api", "gemini"],
                "dissent_count": 1 if dissent else 0,
            }
        },
        "dissenting_views": [],
    }
    if dissent:
        payload["dissenting_views"] = [
            {
                "agent": "openai-api:security",
                "position": "request_changes",
                "reason": "security reviewer found a blocker",
            }
        ]
    return payload


def _model_review_comment(model: str) -> dict[str, Any]:
    """A current-head model-review comment attributed to ``model``'s family.

    The heading names the model and contains the recognized "independent model
    review" token, so ``_model_review_signals_from_comments`` counts it as a
    distinct family signal (e.g. ``deepseek``, ``qwen``, ``grok``).
    """
    return {
        "author": {"login": "an0mium"},
        "body": f"## {model} independent model review\nVerdict: approve.",
    }


def _family_dogfood_comment(model: str) -> dict[str, Any]:
    """Adversarial-dogfood evidence attributed to ``model``'s family.

    Used to satisfy the Tier 1+ dogfood requirement without smuggling in an
    extra Western *signal* (the dogfood family is counted, so picking a
    non-Western family keeps the jurisdiction tests honest).
    """
    return {
        "author": {"login": "an0mium"},
        "body": f"## Cross-author adversarial dogfood ({model})\n6/6 pass",
    }


# --- _summarize_checks -----------------------------------------------------


class TestSummarizeChecks:
    def test_all_green(self) -> None:
        checks = [
            {"status": "COMPLETED", "conclusion": "SUCCESS"},
            {"status": "COMPLETED", "conclusion": "SUCCESS"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert "2/2 green" in summary
        assert not has_fail
        assert not has_pending

    def test_one_failing(self) -> None:
        checks = [
            {"status": "COMPLETED", "conclusion": "SUCCESS"},
            {"status": "COMPLETED", "conclusion": "FAILURE"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert has_fail
        assert "1 failing" in summary

    def test_pending(self) -> None:
        checks = [
            {"status": "IN_PROGRESS", "conclusion": ""},
            {"status": "COMPLETED", "conclusion": "SUCCESS"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert has_pending
        assert not has_fail
        assert "1 pending" in summary

    def test_state_based_green_rollups_are_counted_as_green(self) -> None:
        checks = [
            {"context": "lint", "state": "SUCCESS"},
            {"context": "ci/unit", "state": "SUCCESS"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert summary == "2/2 green"
        assert not has_fail
        assert not has_pending

    def test_state_based_pending_and_failure_rollups_are_preserved(self) -> None:
        checks = [
            {"context": "lint", "state": "SUCCESS"},
            {"context": "ci/unit", "state": "PENDING"},
            {"context": "security", "state": "FAILURE"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert summary == "1 failing / 3 total"
        assert has_fail
        assert has_pending

    def test_skipped_excluded_from_meaningful_total(self) -> None:
        checks = [
            {"status": "COMPLETED", "conclusion": "SUCCESS"},
            {"status": "COMPLETED", "conclusion": "SKIPPED"},
            {"status": "COMPLETED", "conclusion": "CANCELLED"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert not has_fail
        assert not has_pending
        assert "1/1 green" in summary

    def test_current_merge_quorum_self_check_pending_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "26288586838")
        monkeypatch.setenv("GITHUB_REPOSITORY", "synaptent/aragora")
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "detailsUrl": (
                    "https://github.com/synaptent/aragora/actions/runs/26288586838/job/77396719826"
                ),
            },
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert summary == "1/1 green"
        assert not has_fail
        assert not has_pending

    def test_merge_quorum_pending_outside_current_run_still_blocks(self) -> None:
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "detailsUrl": (
                    "https://github.com/synaptent/aragora/actions/runs/26288586838/job/77396719826"
                ),
            },
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert summary == "1 pending / 2 total"
        assert not has_fail
        assert has_pending

    def test_completed_merge_quorum_failure_still_blocks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "26288586838")
        monkeypatch.setenv("GITHUB_REPOSITORY", "synaptent/aragora")
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "detailsUrl": (
                    "https://github.com/synaptent/aragora/actions/runs/26288586838/job/77396719826"
                ),
            },
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert summary == "1 failing / 2 total"
        assert has_fail
        assert not has_pending

    def test_unrelated_failure_still_blocks_with_merge_quorum_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "26288586838")
        monkeypatch.setenv("GITHUB_REPOSITORY", "synaptent/aragora")
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "detailsUrl": (
                    "https://github.com/synaptent/aragora/actions/runs/26288586838/job/77396719826"
                ),
            },
            {"name": "typecheck", "status": "COMPLETED", "conclusion": "FAILURE"},
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert summary == "1 failing / 2 total"
        assert has_fail
        assert not has_pending

    def test_unrelated_pending_still_blocks_with_merge_quorum_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "26288586838")
        monkeypatch.setenv("GITHUB_REPOSITORY", "synaptent/aragora")
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "detailsUrl": (
                    "https://github.com/synaptent/aragora/actions/runs/26288586838/job/77396719826"
                ),
            },
            {"name": "typecheck", "status": "IN_PROGRESS", "conclusion": ""},
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]
        summary, has_fail, has_pending = _summarize_checks(checks)
        assert summary == "1 pending / 2 total"
        assert not has_fail
        assert has_pending

    def test_no_checks(self) -> None:
        summary, has_fail, has_pending = _summarize_checks([])
        assert summary == "no checks"
        assert not has_fail
        assert not has_pending

    def test_malformed_check_ignored(self) -> None:
        checks: list[Any] = ["not a dict", None, {"status": "COMPLETED", "conclusion": "SUCCESS"}]
        summary, _, _ = _summarize_checks(checks)
        assert "1/1 green" in summary

    def test_superseded_historical_failure_ignored_by_latest_check_identity(self) -> None:
        checks = [
            {
                "name": "build",
                "workflowName": "Build Documentation (PR Check)",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "completedAt": "2026-04-19T00:39:02Z",
            },
            {
                "name": "build",
                "workflowName": "Build Documentation (PR Check)",
                "status": "COMPLETED",
                "conclusion": "SKIPPED",
                "completedAt": "2026-05-21T15:28:50Z",
            },
            {
                "name": "lint",
                "workflowName": "Lint",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "completedAt": "2026-05-21T15:29:19Z",
            },
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1/1 green"
        assert not has_fail
        assert not has_pending

    def test_latest_failure_for_same_check_identity_still_blocks(self) -> None:
        checks = [
            {
                "name": "build",
                "workflowName": "Build Documentation (PR Check)",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "completedAt": "2026-05-21T15:28:50Z",
            },
            {
                "name": "build",
                "workflowName": "Build Documentation (PR Check)",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "completedAt": "2026-05-21T15:30:50Z",
            },
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1 failing / 1 total"
        assert has_fail
        assert not has_pending

    def test_merge_quorum_self_check_pending_outside_current_run_blocks(self) -> None:
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "startedAt": "2026-05-22T14:08:46Z",
            },
            {
                "name": "lint",
                "workflowName": "Lint",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "completedAt": "2026-05-22T13:01:00Z",
            },
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1 pending / 2 total"
        assert not has_fail
        assert has_pending

    def test_merge_quorum_self_check_failure_is_preserved(self) -> None:
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "completedAt": "2026-05-22T14:09:40Z",
            },
            {
                "name": "Generate & Validate",
                "workflowName": "OpenAPI Spec",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "completedAt": "2026-05-22T12:46:43Z",
            },
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1 failing / 2 total"
        assert has_fail
        assert not has_pending

    def test_merge_quorum_self_check_requires_matching_repo_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "26311249200")
        monkeypatch.setenv("GITHUB_REPOSITORY", "synaptent/aragora")
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "detailsUrl": (
                    "https://github.com/fork/aragora/actions/runs/26311249200/job/77460233891"
                ),
            },
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1 pending / 2 total"
        assert not has_fail
        assert has_pending

    def test_merge_quorum_self_check_requires_path_match_not_query(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "26311249200")
        monkeypatch.setenv("GITHUB_REPOSITORY", "synaptent/aragora")
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "detailsUrl": (
                    "https://github.com/synaptent/aragora/pull/7436?"
                    "next=/synaptent/aragora/actions/runs/26311249200/job/77460233891"
                ),
            },
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1 pending / 2 total"
        assert not has_fail
        assert has_pending

    def test_merge_quorum_self_check_requires_path_match_not_fragment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "26311249200")
        monkeypatch.setenv("GITHUB_REPOSITORY", "synaptent/aragora")
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "detailsUrl": (
                    "https://github.com/synaptent/aragora/pull/7436#"
                    "/synaptent/aragora/actions/runs/26311249200/job/77460233891"
                ),
            },
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1 pending / 2 total"
        assert not has_fail
        assert has_pending

    def test_merge_quorum_self_check_requires_server_host(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "26311249200")
        monkeypatch.setenv("GITHUB_REPOSITORY", "synaptent/aragora")
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.enterprise.example")
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "detailsUrl": (
                    "https://github.com/synaptent/aragora/actions/runs/26311249200/job/77460233891"
                ),
            },
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1 pending / 2 total"
        assert not has_fail
        assert has_pending

    def test_merge_quorum_self_check_requires_repository_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "26311249200")
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "IN_PROGRESS",
                "conclusion": "",
                "detailsUrl": (
                    "https://github.com/synaptent/aragora/actions/runs/26311249200/job/77460233891"
                ),
            },
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1 pending / 2 total"
        assert not has_fail
        assert has_pending

    def test_similarly_named_check_in_other_workflow_still_blocks(self) -> None:
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Release Readiness Gate",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
                "completedAt": "2026-05-22T14:09:40Z",
            },
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1 failing / 1 total"
        assert has_fail
        assert not has_pending

    def test_cancelled_merge_quorum_check_blocks_settlement_summary(self) -> None:
        checks = [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "COMPLETED",
                "conclusion": "CANCELLED",
                "completedAt": "2026-05-27T17:13:53Z",
            },
            {
                "name": "lint",
                "workflowName": "Tests",
                "status": "COMPLETED",
                "conclusion": "SUCCESS",
                "completedAt": "2026-05-27T17:14:53Z",
            },
        ]

        summary, has_fail, has_pending = _summarize_checks(checks)

        assert summary == "1 failing / 2 total"
        assert has_fail
        assert not has_pending


# --- B2: --ignore-own-quorum-check (diagnostic only) -----------------------


class TestIgnoreOwnQuorumCheck:
    """B2: a diagnostic-only switch that additionally excludes a *concluded*
    merge-quorum self-check so out-of-CI callers observe the real check state.
    The enforcing CI path never sets the flag, so default behavior is unchanged.
    """

    @staticmethod
    def _quorum_failure_plus_green() -> list[dict[str, Any]]:
        return [
            {
                "name": "aragora-merge-quorum",
                "workflowName": "Aragora Merge Quorum",
                "status": "COMPLETED",
                "conclusion": "FAILURE",
            },
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ]

    @staticmethod
    def _clear_ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
        for var in ("GITHUB_WORKFLOW", "GITHUB_JOB", "GITHUB_RUN_ID", "GITHUB_REPOSITORY"):
            monkeypatch.delenv(var, raising=False)

    def test_default_blocks_on_concluded_quorum_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_ci_env(monkeypatch)
        summary, has_fail, has_pending = _summarize_checks(self._quorum_failure_plus_green())
        assert has_fail
        assert summary == "1 failing / 2 total"

    def test_flag_excludes_concluded_quorum_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._clear_ci_env(monkeypatch)
        summary, has_fail, has_pending = _summarize_checks(
            self._quorum_failure_plus_green(), ignore_quorum_check=True
        )
        assert not has_fail
        assert not has_pending
        assert summary == "1/1 green"

    def test_flag_does_not_hide_unrelated_failures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._clear_ci_env(monkeypatch)
        checks = self._quorum_failure_plus_green() + [
            {"name": "typecheck", "status": "COMPLETED", "conclusion": "FAILURE"},
        ]
        summary, has_fail, _ = _summarize_checks(checks, ignore_quorum_check=True)
        assert has_fail  # the real typecheck failure is preserved
        assert summary == "1 failing / 2 total"

    def test_required_summary_flag_excludes_quorum(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._clear_ci_env(monkeypatch)
        required = [
            {"name": "aragora-merge-quorum", "workflow": "Aragora Merge Quorum", "bucket": "fail"},
            {"name": "required-lint", "bucket": "pass"},
        ]
        _, default_fail, _ = _summarize_required_pr_checks(required)
        assert default_fail
        summary, has_fail, _ = _summarize_required_pr_checks(required, ignore_quorum_check=True)
        assert not has_fail
        assert summary == "1/1 required green"

    def test_effective_required_count_flag_excludes_quorum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._clear_ci_env(monkeypatch)
        required = [
            {"name": "aragora-merge-quorum", "workflow": "Aragora Merge Quorum", "bucket": "fail"},
            {"name": "required-lint", "bucket": "pass"},
        ]
        assert _effective_required_pr_check_count(required) == 2
        assert _effective_required_pr_check_count(required, ignore_quorum_check=True) == 1

    def test_is_merge_quorum_check_matches_rollup_and_required_rows(self) -> None:
        assert _is_merge_quorum_check(
            {"name": "aragora-merge-quorum", "workflowName": "Aragora Merge Quorum"}
        )
        assert _is_merge_quorum_check(
            {"name": "aragora-merge-quorum", "workflow": "Aragora Merge Quorum"}
        )
        assert not _is_merge_quorum_check({"name": "lint", "workflow": "Tests"})


# --- _classify_pr lane logic -----------------------------------------------


class TestClassifyPR:
    def test_ready_now_when_all_green_small_diff(self) -> None:
        pr = _make_pr()
        item = _classify_pr(pr)
        assert item.lane == "ready_now"

    def test_state_based_green_rollups_are_ready_now(self) -> None:
        pr = _make_pr(
            checks=[
                {"context": "lint", "state": "SUCCESS"},
                {"context": "ci/unit", "state": "SUCCESS"},
            ]
        )
        item = _classify_pr(pr)
        assert item.lane == "ready_now"

    def test_draft_is_parked(self) -> None:
        pr = _make_pr(is_draft=True)
        item = _classify_pr(pr)
        assert item.lane == "parked"
        assert "draft" in item.lane_reason.lower()

    def test_parked_label_parks_pr(self) -> None:
        for label in PARKED_LABELS:
            pr = _make_pr(labels=[label])
            item = _classify_pr(pr)
            assert item.lane == "parked", f"label={label} should park PR"

    def test_merge_conflict_is_parked(self) -> None:
        pr = _make_pr(mergeable="CONFLICTING")
        item = _classify_pr(pr)
        assert item.lane == "parked"
        assert "conflict" in item.lane_reason.lower()

    def test_failing_check_is_repairable(self) -> None:
        pr = _make_pr(
            checks=[
                {"status": "COMPLETED", "conclusion": "SUCCESS"},
                {"status": "COMPLETED", "conclusion": "FAILURE"},
            ]
        )
        item = _classify_pr(pr)
        assert item.lane == "repairable"

    def test_pending_check_needs_attention(self) -> None:
        pr = _make_pr(
            checks=[
                {"status": "IN_PROGRESS", "conclusion": ""},
            ]
        )
        item = _classify_pr(pr)
        assert item.lane == "needs_attention"

    def test_state_based_pending_check_needs_attention(self) -> None:
        pr = _make_pr(
            checks=[
                {"context": "ci/unit", "state": "PENDING"},
            ]
        )
        item = _classify_pr(pr)
        assert item.lane == "needs_attention"

    def test_state_based_failure_is_repairable(self) -> None:
        pr = _make_pr(
            checks=[
                {"context": "ci/unit", "state": "FAILURE"},
            ]
        )
        item = _classify_pr(pr)
        assert item.lane == "repairable"

    def test_large_diff_needs_attention(self) -> None:
        pr = _make_pr(additions=LARGE_DIFF_THRESHOLD + 100, deletions=10)
        item = _classify_pr(pr)
        assert item.lane == "needs_attention"
        assert "large diff" in item.lane_reason.lower()

    def test_priority_order_draft_beats_failing(self) -> None:
        # A draft PR with failing checks should still be parked, not repairable.
        pr = _make_pr(
            is_draft=True,
            checks=[{"status": "COMPLETED", "conclusion": "FAILURE"}],
        )
        item = _classify_pr(pr)
        assert item.lane == "parked"

    def test_priority_order_conflict_beats_failing(self) -> None:
        # Conflict parks the PR even when checks also fail.
        pr = _make_pr(
            mergeable="CONFLICTING",
            checks=[{"status": "COMPLETED", "conclusion": "FAILURE"}],
        )
        item = _classify_pr(pr)
        assert item.lane == "parked"


# --- _filter_lanes ---------------------------------------------------------


class TestFilterLanes:
    def _items(self) -> list[QueueItem]:
        # Build 4 items, one per lane, smallest synthetic representation.
        out: list[QueueItem] = []
        for lane in ("ready_now", "needs_attention", "repairable", "parked"):
            out.append(
                _classify_pr(
                    _make_pr(
                        number=hash(lane) & 0xFFFF,
                        is_draft=(lane == "parked"),
                        checks=[{"status": "COMPLETED", "conclusion": "FAILURE"}]
                        if lane == "repairable"
                        else (
                            [{"status": "IN_PROGRESS", "conclusion": ""}]
                            if lane == "needs_attention"
                            else [{"status": "COMPLETED", "conclusion": "SUCCESS"}]
                        ),
                    )
                )
            )
        return out

    def test_ready_only(self) -> None:
        items = self._items()
        result = _filter_lanes(items, ready_only=True, include_parked=False)
        assert {it.lane for it in result} == {"ready_now"}

    def test_default_excludes_parked(self) -> None:
        items = self._items()
        result = _filter_lanes(items, ready_only=False, include_parked=False)
        assert "parked" not in {it.lane for it in result}

    def test_include_parked_keeps_all(self) -> None:
        items = self._items()
        result = _filter_lanes(items, ready_only=False, include_parked=True)
        assert "parked" in {it.lane for it in result}


# --- _subsystem_for + _is_high_risk_path -----------------------------------


class TestSubsystemAndRisk:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("aragora/cli/commands/review_pr.py", "aragora/cli"),
            ("tests/cli/commands/test_review_queue.py", "tests/cli"),
            ("docs/CI_LANES.md", "docs"),
            ("scripts/automation_pr_preflight.sh", "scripts"),
            ("benchmarks/bench_readiness/README.md", "benchmarks"),
            (".github/workflows/test.yml", ".github"),
            ("README.md", "README.md"),
        ],
    )
    def test_subsystem_mapping(self, path: str, expected: str) -> None:
        assert _subsystem_for(path) == expected

    def test_high_risk_exact_paths(self) -> None:
        for path in HIGH_RISK_PATHS:
            assert _is_high_risk_path(path), f"{path} should be flagged"

    @pytest.mark.parametrize(
        "path",
        [
            "aragora/security/encryption.py",
            "aragora/auth/oidc.py",
            "aragora/blockchain/wallet.py",
            "aragora/rbac/checker.py",
            "scripts/auto_revert_main_required_failures.py",
            ".github/workflows/release.yml",
        ],
    )
    def test_high_risk_prefixes(self, path: str) -> None:
        assert _is_high_risk_path(path)

    def test_non_high_risk(self) -> None:
        assert not _is_high_risk_path("aragora/cli/commands/review_queue.py")
        assert not _is_high_risk_path("aragora/cli/commands/swarm.py")
        assert not _is_high_risk_path("docs/CI_LANES.md")
        assert not _is_high_risk_path("tests/cli/commands/test_review_queue.py")


# --- model-review tier + quorum -------------------------------------------


class TestModelReviewQuorum:
    @pytest.mark.parametrize(
        ("files", "expected_tier"),
        [
            (["docs/status/queue.md"], 0),
            (["tests/swarm/test_handoff_contract.py"], 0),
            (["AGENTS.md", "CLAUDE.md", "docs/COORDINATION.md"], 0),
            (["aragora/agents/router.py"], 1),
            (["aragora/cli/commands/swarm.py"], 2),
            (["scripts/publish_automation_handoffs.py"], 2),
            (["aragora/metrics/manifold_brier.py"], 3),
            (["aragora/debate/team_selector.py"], 3),
            (["aragora/reputation/store.py"], 3),
            (["aragora/auth/session.py"], 3),
            (["sdk/typescript/src/index.ts"], 3),
            ([".github/workflows/tests.yml"], 4),
            (["deploy/k8s/app.yaml"], 4),
            # Merge-authority self-modification: see TIER_4_PREFIXES rationale.
            (["aragora/cli/commands/review_queue.py"], 4),
            (["aragora/swarm/quorum_evidence.py"], 4),
            (["aragora/cli/parser.py"], 4),
            (["scripts/settle_tier4_pr.py"], 4),
            (["scripts/settle_one_pr.py"], 4),
            (["scripts/merge_codex_automation_prs.py"], 4),
        ],
    )
    def test_classifies_merge_tiers(self, files: list[str], expected_tier: int) -> None:
        tier, _, _ = _classify_model_review_tier(files, pr=_make_pr(files=files))
        assert tier == expected_tier

    @pytest.mark.parametrize(
        "title",
        [
            "[AGT-03] Calibration curve reporting for ManifoldBrierScorer",
            "[AGT-05] Wire enable_agt05_reputation_selection into TeamSelectionConfig",
            "fix: semantic scoring correction",
        ],
    )
    def test_classifies_semantic_titles_as_tier_three(self, title: str) -> None:
        files = ["aragora/agents/router.py"]
        tier, _, reason = _classify_model_review_tier(
            files,
            pr=_make_pr(title=title, files=files),
        )
        assert tier == 3
        assert "semantic" in reason

    def test_tier_zero_satisfied_by_one_dogfood_note(self) -> None:
        pr = _make_pr(files=["docs/status/report.md"])
        pr["comments"] = [_dogfood_comment()]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["docs/status/report.md"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 0
        assert quorum["status"] == "satisfied"
        assert quorum["admin_squash_allowed"] is True

    def test_tier_two_requires_dogfood_even_with_executed_reviewers(self) -> None:
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = []
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 2
        assert quorum["status"] == "needs_model_review_quorum"
        assert quorum["admin_squash_allowed"] is False
        assert "focused adversarial dogfood evidence is required" in quorum["reasons"]

    def test_tier_two_allows_admin_squash_when_quorum_and_dogfood_clean(self) -> None:
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = [_dogfood_comment()]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["status"] == "satisfied"
        assert quorum["verdict"] == "admin_squash_allowed"
        assert quorum["admin_squash_allowed"] is True
        assert set(quorum["counted_reviewer_ids"]) == {"claude", "gemini", "openai"}

    def test_single_western_frontier_signal_satisfies_tier_two_quorum(self) -> None:
        # Tiered gate: Tier 2 settles on ONE western-frontier (openai/codex) signal
        # + dogfood. Duplicate same-family comments still dedup to a single distinct
        # family (counted_reviewer_ids == ["openai"]); they don't inflate the count,
        # but one western-frontier signal is sufficient at this tier.
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = [
            _codex_openai_comment(),
            {
                "author": {"login": "an0mium"},
                "body": _codex_openai_body(
                    heading="## Codex review",
                    body="LGTM after local dogfood.",
                ),
            },
            {
                "author": {"login": "an0mium"},
                "body": _codex_openai_body(
                    heading="## Codex review",
                    body="Second same-model note.",
                ),
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 2
        assert quorum["status"] == "satisfied"
        assert quorum["admin_squash_allowed"] is True
        assert quorum["counted_reviewer_ids"] == ["openai"]
        assert quorum["requires_western_frontier_signal"] is True
        assert quorum["has_western_frontier_signal"] is True

    def test_dogfood_only_western_frontier_signal_does_not_satisfy_tier_two_quorum(
        self,
    ) -> None:
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = [
            _codex_openai_comment(),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 2
        assert quorum["status"] == "needs_model_review_quorum"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["counted_reviewer_ids"] == ["grok", "openai"]
        assert quorum["counted_model_families"] == ["grok", "openai"]
        assert quorum["has_western_frontier_signal"] is False
        assert any("western-frontier" in reason for reason in quorum["reasons"])
        assert quorum["dogfood_evidence"][0]["surface_reviewer_id"] == "codex"
        assert quorum["dogfood_evidence"][0]["model_family"] == "openai"

    def test_changes_requested_comment_blocks_even_when_quorum_satisfied(self) -> None:
        head = "cd87c5a1b2db34f04167906553502db3ede9525e"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head
        pr["comments"] = [
            _codex_openai_review_comment(
                body=f"Current head: {head}\nVerdict: approve.\nFocused adversarial dogfood passed."
            ),
            {
                "author": {"login": "an0mium"},
                "body": f"## Grok independent model review\nCurrent head: {head}\nVerdict: approve.",
            },
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Claude independent model review\n"
                    f"Current head: {head}\n"
                    "Verdict: CHANGES-REQUESTED\n"
                    "[P1] Merge gate dissent is unresolved."
                ),
            },
        ]

        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )

        assert quorum["unresolved_dissent"] is True
        assert quorum["status"] == "unresolved_dissent"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["counted_reviewer_ids"] == ["grok", "openai"]
        assert "unresolved model dissent is present" in quorum["reasons"]

    def test_severity_gated_p2_only_changes_requested_is_advisory(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        head = "cd87c5a1b2db34f04167906553502db3ede9525e"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head
        pr["comments"] = [
            _codex_openai_review_comment(
                body=f"Current head: {head}\nVerdict: approve.\nFocused adversarial dogfood passed."
            ),
            {
                "author": {"login": "an0mium"},
                "body": f"## Grok independent model review\nCurrent head: {head}\nVerdict: approve.",
            },
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Claude independent model review\n"
                    f"Current head: {head}\n"
                    "Verdict: CHANGES-REQUESTED\n"
                    "[P2] Add stronger smoke coverage in a follow-up."
                ),
            },
        ]

        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )

        assert quorum["unresolved_dissent"] is False
        assert quorum["dissenting_views"] == []
        assert len(quorum["advisory_views"]) == 1
        assert quorum["advisory_views"][0]["position"] == "advisory_changes_requested"
        assert quorum["advisory_views"][0]["blocking"] is False
        assert quorum["advisory_views"][0]["highest_severity"] is None
        assert quorum["status"] == "satisfied"
        assert quorum["admin_squash_allowed"] is True
        assert quorum["counted_reviewer_ids"] == ["grok", "openai"]

    def test_severity_gated_protocol_dissent_still_blocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        protocol = _executed_protocol()
        protocol["dissenting_views"] = [
            {
                "agent": "openai-api:security",
                "position": "request_changes",
                "reason": "[P2] Add a follow-up smoke test.",
            }
        ]
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = [_dogfood_comment()]

        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol=protocol,
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )

        assert quorum["unresolved_dissent"] is True
        assert quorum["status"] == "unresolved_dissent"
        assert quorum["admin_squash_allowed"] is False

    def test_severity_gated_explicit_p2_blocker_still_blocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        head = "cd87c5a1b2db34f04167906553502db3ede9525e"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head
        pr["comments"] = [
            _codex_openai_review_comment(
                body=f"Current head: {head}\nVerdict: approve.\nFocused adversarial dogfood passed."
            ),
            {
                "author": {"login": "an0mium"},
                "body": f"## Grok independent model review\nCurrent head: {head}\nVerdict: approve.",
            },
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Claude independent model review\n"
                    f"Current head: {head}\n"
                    "Verdict: CHANGES-REQUESTED\n"
                    "Blockers:\n"
                    "- [P2] Merge gate can be bypassed."
                ),
            },
        ]

        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )

        assert quorum["unresolved_dissent"] is True
        assert quorum["status"] == "unresolved_dissent"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["dissenting_views"][0]["agent"] == "claude"

    def test_severity_gated_p1_changes_requested_still_blocks(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        head = "cd87c5a1b2db34f04167906553502db3ede9525e"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head
        pr["comments"] = [
            _codex_openai_review_comment(
                body=f"Current head: {head}\nVerdict: approve.\nFocused adversarial dogfood passed."
            ),
            {
                "author": {"login": "an0mium"},
                "body": f"## Grok independent model review\nCurrent head: {head}\nVerdict: approve.",
            },
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Claude independent model review\n"
                    f"Current head: {head}\n"
                    "Verdict: CHANGES-REQUESTED\n"
                    "[P1] Merge gate dissent is unresolved."
                ),
            },
        ]

        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )

        assert quorum["unresolved_dissent"] is True
        assert quorum["status"] == "unresolved_dissent"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["dissenting_views"][0]["agent"] == "claude"

    def test_github_actions_bot_changes_requested_comment_blocks_quorum(self) -> None:
        head = "cd87c5a1b2db34f04167906553502db3ede9525e"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head
        pr["comments"] = [
            _codex_openai_review_comment(
                body=f"Current head: {head}\nVerdict: approve.\nFocused adversarial dogfood passed."
            ),
            {
                "author": {"login": "an0mium"},
                "body": f"## Grok independent model review\nCurrent head: {head}\nVerdict: approve.",
            },
            {
                "author": {"login": "github-actions[bot]"},
                "body": (
                    "## Claude independent model review\n"
                    f"Current head: {head}\n"
                    "Verdict: CHANGES-REQUESTED\n"
                    "[P1] Automated exact-head dissent must block."
                ),
            },
        ]

        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )

        assert quorum["unresolved_dissent"] is True
        assert quorum["status"] == "unresolved_dissent"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["dissenting_views"][0]["github_author"] == "github-actions[bot]"
        assert "unresolved model dissent is present" in quorum["reasons"]

    def test_p1_comment_blocks_even_without_negative_verdict(self) -> None:
        head = "cd87c5a1b2db34f04167906553502db3ede9525e"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head
        pr["comments"] = [
            _codex_openai_review_comment(
                body=f"Current head: {head}\nVerdict: approve.\nFocused adversarial dogfood passed."
            ),
            {
                "author": {"login": "an0mium"},
                "body": f"## Grok independent model review\nCurrent head: {head}\nVerdict: approve.",
            },
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Claude independent semantic review on head "
                    f"{head}\n\n"
                    "**Reviewer harness:** claude\n"
                    "**Model family:** claude\n"
                    "**Model id:** Claude Code\n"
                    "**Receipt artifact:** /tmp/receipt.md\n\n"
                    "[P1] Exact-head evidence still has a blocking dependency drift finding.\n\n"
                    "Focused adversarial dogfood: I reviewed the exact-head diff."
                ),
            },
        ]

        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )

        assert quorum["unresolved_dissent"] is True
        assert quorum["status"] == "unresolved_dissent"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["counted_model_families"] == ["grok", "openai"]
        assert quorum["dissenting_views"][0]["model_family"] == "claude"

    def test_github_actions_bot_pass_comment_remains_uncounted_support(self) -> None:
        head = "cd87c5a1b2db34f04167906553502db3ede9525e"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head
        pr["comments"] = [
            {
                "author": {"login": "github-actions[bot]"},
                "body": (
                    "## OpenAI independent model review\n"
                    f"Current head: {head}\n"
                    "Verdict: PASS\n"
                    "Automated supportive evidence must remain advisory-only."
                ),
            },
            {
                "author": {"login": "an0mium"},
                "body": f"## Grok independent model review\nCurrent head: {head}\nVerdict: approve.",
            },
        ]

        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )

        assert quorum["unresolved_dissent"] is False
        assert quorum["reviewer_signals"][0]["reviewer_id"] == "grok"
        assert quorum["counted_reviewer_ids"] == ["grok"]
        assert quorum["status"] == "needs_model_review_quorum"

    def test_unknown_dogfood_does_not_count_or_satisfy_required_dogfood(self) -> None:
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = [
            _dogfood_comment("## Focused dogfood\nlocal checks pass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 2
        assert quorum["status"] == "needs_model_review_quorum"
        assert quorum["counted_reviewer_ids"] == ["grok"]
        assert "focused adversarial dogfood evidence is required" in quorum["reasons"]

    def test_branch_name_substring_in_body_does_not_phantom_tag_reviewer(self) -> None:
        """A comment that mentions ``codex/...`` branch in a code block but
        has no model-review heading must not be tagged as a Codex signal."""
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = [
            _codex_openai_comment(),
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Rebased over current main after queue drain\n"
                    "Rebased `codex/model-review-quorum-settlement` onto current "
                    "`origin/main` after #6783 and #6787 merged.\n"
                    "Conflict resolution kept both parser surfaces:\n"
                    "- `review-queue baseline` from #6783\n"
                    "- `review-queue merge-packet` from this PR\n"
                ),
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        # The rebase note's heading does not contain a model name.  The
        # heuristic must NOT scan the entire body and pick up the branch
        # name ``codex/...`` in line 2 of the body.
        assert quorum["counted_reviewer_ids"] == ["openai"]
        # The dogfood evidence list should still include both comments
        # (the rebase note matches "rebased" → not a marker; "drain"
        # → not a marker; but the body does not actually contain any
        # of dogfood/adversarial/cross-author/recheck), so it is not
        # added to dogfood_evidence at all.
        dogfood_authors = [entry.get("reviewer_id") for entry in quorum["dogfood_evidence"]]
        assert "openai" in dogfood_authors
        # Ensure the rebase note didn't sneak into reviewer_signals.
        for sig in quorum["reviewer_signals"]:
            assert "rebase" not in (sig.get("summary", "") or "").lower()

    def test_inferrer_uses_first_heading_only(self) -> None:
        """If a comment's first heading does not name a model, the
        inferrer must fall back to first 200 chars and NOT scan the
        entire body."""
        from aragora.cli.commands.review_queue import _infer_model_reviewer_from_text

        body_with_phantom_codex_deep_in_body = (
            "## Cross-author adversarial dogfood (no model named in heading)\n"
            "Local checks pass.\n\n"
            + ("Filler line that does not name any model.\n" * 30)
            + "Reference: https://github.com/example/repo/blob/main/codex/x.py\n"
        )
        # No model name in heading or first 200 chars → unknown.
        assert (
            _infer_model_reviewer_from_text(body_with_phantom_codex_deep_in_body)
            == "unknown_model_reviewer"
        )

        body_with_codex_heading = "## Codex review\nVerdict: approve.\n"
        assert _infer_model_reviewer_from_text(body_with_codex_heading) == "codex"

        body_with_grok_in_lead = (
            "Grok independent semantic review of head SHA abc1234.\n"
            "No heading present; relying on first-200-chars fallback.\n"
        )
        assert _infer_model_reviewer_from_text(body_with_grok_in_lead) == "grok"

    def test_stale_comments_excluded_when_predate_head_commit(self) -> None:
        """Comments posted before the current head was committed must
        be excluded from quorum unless they explicitly cite the head SHA."""
        head_sha = "abcdef1234567890abcdef1234567890abcdef12"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head_sha
        pr["commits"] = [
            {"oid": head_sha, "committedDate": "2026-04-28T20:00:00Z"},
        ]
        pr["comments"] = [
            # Posted BEFORE the head was committed → stale.
            {
                "author": {"login": "an0mium"},
                "body": _codex_openai_body(),
                "createdAt": "2026-04-28T18:00:00Z",
            },
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
                "createdAt": "2026-04-28T18:30:00Z",
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        # Both stale → quorum empty.
        assert quorum["counted_reviewer_ids"] == []
        assert quorum["status"] == "needs_model_review_quorum"

    def test_fresh_comments_after_head_commit_count(self) -> None:
        head_sha = "abcdef1234567890abcdef1234567890abcdef12"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head_sha
        pr["commits"] = [
            {"oid": head_sha, "committedDate": "2026-04-28T20:00:00Z"},
        ]
        pr["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": _codex_openai_body(
                    heading="## Codex review",
                    body="Verdict: approve.\nFocused adversarial dogfood passed.",
                ),
                "createdAt": "2026-04-28T20:05:00Z",
            },
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
                "createdAt": "2026-04-28T20:10:00Z",
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["counted_reviewer_ids"] == ["grok", "openai"]
        assert quorum["status"] == "satisfied"

    def test_stale_comment_with_head_sha_citation_still_counts(self) -> None:
        """A reviewer who explicitly cites the current head SHA in
        their body counts even if their createdAt predates the head."""
        head_sha = "abcdef1234567890abcdef1234567890abcdef12"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head_sha
        pr["commits"] = [
            {"oid": head_sha, "committedDate": "2026-04-28T20:00:00Z"},
        ]
        pr["comments"] = [
            # Predates head BUT cites head SHA → grounded.
            {
                "author": {"login": "an0mium"},
                "body": _codex_openai_body(
                    heading="## Codex review",
                    body=(
                        f"Reviewed at head {head_sha[:7]}.\n"
                        "Verdict: approve.\n"
                        "Focused adversarial dogfood passed."
                    ),
                ),
                "createdAt": "2026-04-28T18:00:00Z",
            },
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
                "createdAt": "2026-04-28T20:10:00Z",
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["counted_reviewer_ids"] == ["grok", "openai"]
        assert quorum["status"] == "satisfied"

    def test_unresolved_dissent_forces_human_risk_settlement(self) -> None:
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = [_dogfood_comment()]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol=_executed_protocol(dissent=True),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["status"] == "unresolved_dissent"
        assert quorum["requires_human_risk_settlement"] is True
        assert quorum["admin_squash_allowed"] is False

    def test_needs_attention_risk_signal_can_still_admin_squash_when_quorum_clean(self) -> None:
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = [_dogfood_comment()]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol=_executed_protocol(),
            machine_recommendation="needs_human_attention",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["status"] == "satisfied"
        assert quorum["admin_squash_allowed"] is True

    def test_draft_state_blocks_settlement_even_with_quorum(self) -> None:
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"], is_draft=True)
        pr["comments"] = [_dogfood_comment()]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol=_executed_protocol(),
            machine_recommendation="needs_human_attention",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["status"] == "repair_or_wait"
        assert quorum["admin_squash_allowed"] is False

    def test_merged_state_blocks_settlement_even_with_quorum(self) -> None:
        pr = _make_pr(
            files=["docs/README.md"],
            state="MERGED",
            merged_at="2026-05-27T00:19:36Z",
        )
        pr["comments"] = [_dogfood_comment("## Claude focused dogfood\npass")]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["docs/README.md"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["status"] == "repair_or_wait"
        assert quorum["verdict"] == "not_ready_for_settlement"
        assert quorum["admin_squash_allowed"] is False
        assert "PR is MERGED; settlement applies only to open PRs" in quorum["reasons"]

    def test_tier_three_never_admin_squashes_without_human_risk_settlement(self) -> None:
        pr = _make_pr(files=["aragora/reputation/store.py"])
        pr["comments"] = [_dogfood_comment()]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/reputation/store.py"],
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 3
        assert quorum["status"] == "human_risk_settlement_required"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["requires_human_risk_settlement"] is True

    def test_tier_three_human_risk_settlement_allows_admin_squash(self) -> None:
        pr = _make_pr(files=["aragora/reputation/store.py"])
        pr["comments"] = [_dogfood_comment()]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/reputation/store.py"],
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
            human_risk_settlement_recorded=True,
        )
        assert quorum["tier"] == 3
        assert quorum["status"] == "satisfied"
        assert quorum["verdict"] == "admin_squash_allowed"
        assert quorum["admin_squash_allowed"] is True
        assert quorum["requires_human_risk_settlement"] is False
        assert quorum["human_risk_settlement_recorded"] is True
        assert "exact-head human risk settlement receipt recorded" in quorum["reasons"]

    # --- Jurisdiction enforcement at the live gate (claude/grok #8507 P2/P3) ----
    # These exercise the security-critical Western-only / at-least-one-Western
    # rejections at the enforcement layer (_build_model_review_quorum), which the
    # prior suite never covered because it contained zero Chinese-routed families.

    def test_tier_three_chinese_routed_family_is_advisory_not_counted(self) -> None:
        # Tier 3 (security surface): claude + deepseek. deepseek is advisory-only,
        # so the Western-only counted quorum drops it → only 1 Western < 2 required.
        pr = _make_pr(files=["aragora/security/encryption.py"])
        pr["comments"] = [
            _family_dogfood_comment("Claude"),
            _model_review_comment("Claude"),
            _model_review_comment("DeepSeek"),
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/security/encryption.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 3
        # deepseek remains in counted_reviewer_ids for the audit trail.
        assert quorum["counted_reviewer_ids"] == ["claude", "deepseek"]
        # But it does not count toward the quorum → incomplete, no admin squash.
        assert quorum["status"] == "needs_model_review_quorum"
        assert quorum["admin_squash_allowed"] is False
        assert any("1/2 signal(s)" in reason for reason in quorum["reasons"])
        assert any("Western-only counted quorum" in reason for reason in quorum["reasons"])

    def test_tier_three_two_western_families_satisfy_quorum(self) -> None:
        # Same Tier 3 surface, claude + grok: both Western, so the quorum is met
        # (Tier 3 then advances to the human-risk-settlement requirement, which is
        # the satisfied-quorum state — not needs_model_review_quorum).
        pr = _make_pr(files=["aragora/security/encryption.py"])
        pr["comments"] = [
            _family_dogfood_comment("Claude"),
            _model_review_comment("Claude"),
            _model_review_comment("Grok"),
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/security/encryption.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 3
        assert quorum["counted_reviewer_ids"] == ["claude", "grok"]
        # Quorum is satisfied: no "incomplete" / "Western-only" reasons remain.
        assert quorum["status"] == "human_risk_settlement_required"
        assert quorum["requires_human_risk_settlement"] is True
        assert not any("signal(s)" in reason for reason in quorum["reasons"])
        assert not any("Western-only counted quorum" in reason for reason in quorum["reasons"])

    def test_tier_two_no_western_family_fails_quorum_flag_off(self, monkeypatch) -> None:
        # Tier 2, tiered relaxation OFF: deepseek + qwen are two distinct families
        # but neither is Western, so the at-least-one-Western rule blocks the merge.
        monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "0")
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = [
            _family_dogfood_comment("DeepSeek"),
            _model_review_comment("DeepSeek"),
            _model_review_comment("Qwen"),
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 2
        assert quorum["counted_reviewer_ids"] == ["deepseek", "qwen"]
        assert quorum["status"] == "needs_model_review_quorum"
        assert quorum["admin_squash_allowed"] is False
        assert any(
            "at least one counted model signal must be from a Western family" in reason
            for reason in quorum["reasons"]
        )

    def test_tier_two_one_western_family_satisfies_quorum_flag_off(self, monkeypatch) -> None:
        # Tier 2, tiered relaxation OFF: claude + deepseek. Two distinct families
        # and ≥1 Western (claude), so the quorum is satisfied. deepseek counts
        # toward the 2-distinct bar at Tier 2 (Western-only counting is Tier 3-4).
        monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "0")
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["comments"] = [
            _family_dogfood_comment("Claude"),
            _model_review_comment("Claude"),
            _model_review_comment("DeepSeek"),
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 2
        assert quorum["counted_reviewer_ids"] == ["claude", "deepseek"]
        assert quorum["status"] == "satisfied"
        assert quorum["admin_squash_allowed"] is True
        assert not any("Western family" in reason for reason in quorum["reasons"])

    def test_human_risk_settlement_does_not_clear_unresolved_dissent(self) -> None:
        pr = _make_pr(files=["aragora/reputation/store.py"])
        pr["comments"] = [_dogfood_comment()]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/reputation/store.py"],
            protocol=_executed_protocol(dissent=True),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
            human_risk_settlement_recorded=True,
        )
        assert quorum["status"] == "unresolved_dissent"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["requires_human_risk_settlement"] is True

    @pytest.mark.parametrize(
        ("has_failures", "has_pending"),
        [
            (True, False),
            (False, True),
        ],
    )
    def test_human_risk_settlement_does_not_clear_failing_or_pending_checks(
        self,
        *,
        has_failures: bool,
        has_pending: bool,
    ) -> None:
        pr = _make_pr(files=["aragora/reputation/store.py"])
        pr["comments"] = [_dogfood_comment()]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/reputation/store.py"],
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=has_pending,
            has_failures=has_failures,
            human_risk_settlement_recorded=True,
        )
        assert quorum["status"] == "repair_or_wait"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["requires_human_risk_settlement"] is True

    def test_independent_model_review_comment_counts_as_quorum_signal(self) -> None:
        pr = _make_pr(files=["aragora/debate/team_selector.py"])
        pr["comments"] = [
            _codex_openai_comment(body="10/10 pass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent semantic review\nVerdict: approve after human risk settlement.",
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/debate/team_selector.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 3
        assert quorum["status"] == "human_risk_settlement_required"
        assert len(quorum["reviewer_signals"]) == 1
        assert quorum["reviewer_signals"][0]["reviewer_id"] == "grok"
        assert len(quorum["dogfood_evidence"]) == 1
        assert quorum["counted_reviewer_ids"] == ["grok", "openai"]

    def test_github_actions_advisory_review_does_not_count_as_model_signal(self) -> None:
        pr = _make_pr(files=["aragora/debate/team_selector.py"])
        pr["comments"] = [
            _dogfood_comment("## Codex focused dogfood\n10/10 pass"),
            {
                "author": {"login": "github-actions"},
                "body": "## Aragora Code Review\n\nAdvisory-only review. No issues found.",
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/debate/team_selector.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 3
        assert quorum["status"] == "needs_model_review_quorum"
        assert len(quorum["reviewer_signals"]) == 0
        assert len(quorum["dogfood_evidence"]) == 1

    def test_current_head_review_pr_object_warns_that_comment_form_is_required(
        self,
    ) -> None:
        head_sha = "abcdef1234567890abcdef1234567890abcdef12"
        # Tier-3 surface (security): a lone counted western-frontier signal is NOT
        # sufficient there, so the "review-object form does not count" intent still
        # leaves the quorum incomplete under tiered settlement.
        pr = _make_pr(files=["aragora/security/encryption.py"])
        pr["headRefOid"] = head_sha
        pr["commits"] = [
            {"oid": head_sha, "committedDate": "2026-04-28T20:00:00Z"},
        ]
        pr["comments"] = [
            {
                **_dogfood_comment("## Claude focused dogfood\n10/10 pass"),
                "createdAt": "2026-04-28T20:05:00Z",
            },
        ]
        pr["reviews"] = [
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Aragora review-pr: advisory pass\n\n"
                    "- Reviewer: `codex`\n"
                    "- Model family: `openai`\n"
                    "- Model id: `gpt-5-codex`\n"
                    f"- Head SHA: `{head_sha}`\n"
                    "- Final status: `passed`\n"
                ),
                "commit": {"oid": head_sha},
                "state": "COMMENTED",
                "submittedAt": "2026-04-28T20:10:00Z",
            }
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/security/encryption.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["counted_reviewer_ids"] == ["claude"]
        assert quorum["status"] == "needs_model_review_quorum"
        assert any(
            "GitHub review object from openai" in reason and "PR comment" in reason
            for reason in quorum["reasons"]
        )
        assert not any("GitHub review object from codex" in reason for reason in quorum["reasons"])

    def test_review_pr_object_with_router_reviewer_requires_model_family_metadata(
        self,
    ) -> None:
        head_sha = "abcdef1234567890abcdef1234567890abcdef12"
        # Tier-3 surface (still requires two distinct signals) so the lone counted
        # claude leaves the quorum incomplete and the codex-metadata warning fires.
        pr = _make_pr(files=["aragora/security/encryption.py"])
        pr["headRefOid"] = head_sha
        pr["commits"] = [
            {"oid": head_sha, "committedDate": "2026-04-28T20:00:00Z"},
        ]
        pr["comments"] = [
            {
                **_dogfood_comment("## Claude focused dogfood\n10/10 pass"),
                "createdAt": "2026-04-28T20:05:00Z",
            },
        ]
        pr["reviews"] = [
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Aragora review-pr: advisory pass\n\n"
                    "- Reviewer: `codex`\n"
                    f"- Head SHA: `{head_sha}`\n"
                    "- Final status: `passed`\n"
                ),
                "commit": {"oid": head_sha},
                "state": "COMMENTED",
                "submittedAt": "2026-04-28T20:10:00Z",
            }
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/security/encryption.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["counted_reviewer_ids"] == ["claude"]
        assert any(
            "GitHub review object from codex lacks lineage-bound model family metadata" in reason
            for reason in quorum["reasons"]
        )

    def test_off_head_review_pr_object_does_not_warn_as_current_evidence(
        self,
    ) -> None:
        head_sha = "abcdef1234567890abcdef1234567890abcdef12"
        pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
        pr["headRefOid"] = head_sha
        pr["commits"] = [
            {"oid": head_sha, "committedDate": "2026-04-28T20:00:00Z"},
        ]
        pr["comments"] = [
            {
                **_dogfood_comment("## Claude focused dogfood\n10/10 pass"),
                "createdAt": "2026-04-28T20:05:00Z",
            },
        ]
        pr["reviews"] = [
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Aragora review-pr: advisory pass\n\n"
                    "- Reviewer: `codex`\n"
                    "- Model family: `openai`\n"
                    "- Model id: `gpt-5-codex`\n"
                    "- Final status: `passed`\n"
                ),
                "commit": {"oid": "0000000000000000000000000000000000000000"},
                "state": "COMMENTED",
                "submittedAt": "2026-04-28T20:10:00Z",
            }
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=["aragora/cli/commands/swarm.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["counted_reviewer_ids"] == ["claude"]
        assert not any("GitHub review object" in reason for reason in quorum["reasons"])

    # --- Finding 6: merge-authority self-modification elevation ------------

    def test_review_queue_self_modification_classified_tier_four(self) -> None:
        """``aragora/cli/commands/review_queue.py`` is the merge-authority code.

        Modifying it must elevate to Tier 4 so the quorum gating the change
        is not the version of the gate the change is trying to land.
        """
        files = ["aragora/cli/commands/review_queue.py"]
        tier, name, reason = _classify_model_review_tier(files, pr=_make_pr(files=files))
        assert tier == 4
        assert "destructive" in reason or "workflow" in reason or "preapproval" in name

    def test_tier_four_review_queue_blocks_admin_squash_even_with_full_quorum(
        self,
    ) -> None:
        """Even with executed protocol + full dogfood, Tier 4 self-modification
        cannot admin-squash on its own — human preapproval is required."""
        files = ["aragora/cli/commands/review_queue.py"]
        pr = _make_pr(files=files)
        pr["comments"] = [
            _codex_openai_comment(),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["tier"] == 4
        assert quorum["admin_squash_allowed"] is False
        assert quorum["verdict"] == "tier_4_human_preapproval_required"
        assert quorum["requires_human_preapproval"] is True

    def test_tier_four_local_receipt_alone_does_not_clear_preapproval(self) -> None:
        files = ["aragora/cli/commands/review_queue.py"]
        pr = _make_pr(files=files)
        pr["comments"] = [
            _codex_openai_comment(),
            {
                "author": {"login": "an0mium"},
                "body": "## Claude independent model review\nVerdict: approve.",
            },
        ]

        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
            human_risk_settlement_recorded=True,
        )

        assert quorum["tier"] == 4
        assert quorum["status"] == "human_preapproval_required"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["requires_human_preapproval"] is True

    def test_tier_four_repo_visible_helper_settlement_clears_preapproval(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        files = ["aragora/cli/commands/review_queue.py"]
        pr = _make_pr(number=8406, files=files)
        head_sha = str(pr["headRefOid"])
        pr["commits"] = [{"oid": head_sha, "committedDate": "2026-06-15T02:21:41Z"}]
        settlement_url = "https://github.example/pr/8406#issuecomment-settlement"
        pr["comments"] = [
            _codex_openai_comment(body=f"Reviewed exact head {head_sha}."),
            {
                "author": {"login": "scarmani"},
                "body": (
                    "## Claude independent model review\n\n"
                    "Model family: claude\n"
                    f"Current head: {head_sha}\n\n"
                    "Verdict: approve."
                ),
            },
            {
                "author": {"login": "scarmani"},
                "authorAssociation": "OWNER",
                "createdAt": "2026-06-15T02:22:41Z",
                "url": settlement_url,
                "body": (
                    "Tier-4 Human Settlement Authorization\n\n"
                    "PR: #8406\n"
                    f"Exact head: {head_sha}\n"
                    "Authorized action: admin_squash_merge and "
                    "branch_protection_reconcile, only if #8406 is non-draft "
                    "and live exact-head checks/merge-packet remain otherwise "
                    "green.\n\n"
                    "Human-risk settlement: I accept the Tier 4 risk for this PR."
                ),
            },
        ]
        pr["statusCheckRollup"] = [
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"context": "aragora/human-settlement", "state": "SUCCESS"},
        ]

        def _gh_json_dispatch(args: list[str]) -> Any:
            endpoint = str(args[-1])
            if "/collaborators/scarmani/permission" in endpoint:
                return {"permission": "admin"}
            if "/statuses" in endpoint:
                return [
                    {
                        "context": "aragora/human-settlement",
                        "state": "success",
                        "creator": {"login": "scarmani"},
                        "target_url": settlement_url,
                    }
                ]
            raise AssertionError(f"unexpected gh api call: {args}")

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            _gh_json_dispatch,
        )

        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
            repo_slug="synaptent/aragora",
        )

        assert quorum["status"] == "satisfied"
        assert quorum["verdict"] == "admin_squash_allowed"
        assert quorum["admin_squash_allowed"] is True
        assert quorum["human_risk_settlement_recorded"] is False
        assert quorum["human_preapproval_recorded"] is True
        assert quorum["requires_human_risk_settlement"] is False
        assert quorum["requires_human_preapproval"] is False
        assert "repo-visible exact-head human risk settlement recorded" in quorum["reasons"]

    def test_open_tier_four_with_exact_helper_settlement_is_authorized(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        files = ["aragora/cli/commands/review_queue.py"]
        pr_payload = _make_pr(number=7736, files=files)
        head_sha = str(pr_payload["headRefOid"])
        pr_payload["commits"] = [{"oid": head_sha, "committedDate": "2026-06-15T02:21:41Z"}]
        settlement_url = "https://github.example/pr/7736#issuecomment-settlement"
        pr_payload["comments"] = [
            _codex_openai_comment(body=f"Reviewed exact head {head_sha}."),
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Claude independent model review\n\n"
                    "Model family: claude\n"
                    f"Current head: {head_sha}\n\n"
                    "Verdict: approve."
                ),
            },
            {
                "author": {"login": "scarmani"},
                "authorAssociation": "OWNER",
                "createdAt": "2026-06-15T02:22:41Z",
                "url": settlement_url,
                "body": (
                    "Tier-4 Human Settlement Authorization\n\n"
                    "PR: #7736\n"
                    f"Exact head: {head_sha}\n"
                    "Authorized action: admin_squash_merge and "
                    "branch_protection_reconcile, only if #7736 is non-draft "
                    "and live exact-head checks/merge-packet remain otherwise "
                    "green.\n\n"
                    "Human-risk settlement: I accept the Tier 4 risk for this PR."
                ),
            },
        ]
        pr_payload["statusCheckRollup"] = [
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"context": "aragora/human-settlement", "state": "SUCCESS"},
        ]
        review_queue_root = tmp_path / "review-queue"
        _write_human_risk_settlement_receipt(
            review_queue_root,
            pr_number=7736,
            head_sha=head_sha,
            github_event="RECORDED_EXTERNAL_APPROVE",
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_queue",
            lambda limit, repo_override=None: [_classify_pr(_make_pr(number=7736))],
        )

        def _gh_json_dispatch(args: list[str]) -> Any:
            # TET H2: the settlement-creator pin fetches the head commit's
            # statuses via the REST API; everything else hydrates the PR.
            endpoint = str(args[-1])
            if "/collaborators/scarmani/permission" in endpoint:
                return {"permission": "admin"}
            if "/statuses" in endpoint:
                return [
                    {
                        "context": "aragora/human-settlement",
                        "state": "success",
                        "creator": {"login": "scarmani"},
                        "target_url": settlement_url,
                    }
                ]
            return pr_payload

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            _gh_json_dispatch,
        )

        packet = _build_merge_authorization_packet(
            pr_refs=["7736"],
            limit=10,
            repo_override=None,
            review_queue_root=review_queue_root,
        )

        entry = packet["entries"][0]
        assert entry["status"] == "satisfied"
        assert entry["verdict"] == "admin_squash_allowed"
        assert entry["admin_squash_allowed"] is True
        assert entry["requires_human_risk_settlement"] is False
        assert entry["requires_human_preapproval"] is False
        assert entry["human_preapproval_recorded"] is True
        assert entry["settlement_creator_pin"]["checked"] is True
        assert entry["settlement_creator_pin"]["verified"] is True
        assert entry["settlement_creator_pin"]["trusted_creator"] == "scarmani"
        assert "exact-head Tier 4 human preapproval verified" in entry["reasons"]
        assert packet["admin_squash_order"] == [7736]
        assert packet["human_risk_settlement_required"] == []
        assert packet["not_ready"] == []

    # --- TET H2: settlement-creator pin (docs/specs/TAMPER_EVIDENT_TRAIL.md) ---

    def _tier_four_settled_pr(self, *, number: int = 7900) -> tuple[dict[str, Any], list[str]]:
        """A Tier 4 PR with full quorum + comment + rollup settlement evidence.

        Everything short of the settlement-creator pin passes, so each test
        isolates exactly what the pin adds on top of the pre-H2 gate.
        """
        files = ["aragora/cli/commands/review_queue.py"]
        pr = _make_pr(number=number, files=files)
        head_sha = str(pr["headRefOid"])
        pr["commits"] = [{"oid": head_sha, "committedDate": "2026-06-15T02:21:41Z"}]
        settlement_url = f"https://github.example/pr/{number}#issuecomment-settlement"
        pr["comments"] = [
            _codex_openai_comment(body=f"Reviewed exact head {head_sha}."),
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Claude independent model review\n\n"
                    "Model family: claude\n"
                    f"Current head: {head_sha}\n\n"
                    "Verdict: approve."
                ),
            },
            {
                "author": {"login": "scarmani"},
                "authorAssociation": "OWNER",
                "createdAt": "2026-06-15T02:22:41Z",
                "url": settlement_url,
                "body": (
                    "Tier-4 Human Settlement Authorization\n\n"
                    f"PR: #{number}\n"
                    f"Exact head: {head_sha}\n"
                    "Authorized action: admin_squash_merge only if checks stay green.\n\n"
                    "Human-risk settlement: I accept the Tier 4 risk for this PR."
                ),
            },
        ]
        pr["statusCheckRollup"] = [
            {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"context": "aragora/human-settlement", "state": "SUCCESS"},
        ]
        return pr, files

    @staticmethod
    def _settlement_status(
        login: str | None,
        *,
        state: str = "success",
        context: str = "aragora/human-settlement",
        target_url: str = "https://github.example/pr/7900#issuecomment-settlement",
        updated_at: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        status: dict[str, Any] = {
            "context": context,
            "state": state,
            "target_url": target_url,
        }
        if login is not None:
            status["creator"] = {"login": login}
        if updated_at is not None:
            status["updated_at"] = updated_at
        if created_at is not None:
            status["created_at"] = created_at
        return status

    def _pin_quorum(
        self,
        monkeypatch: pytest.MonkeyPatch,
        statuses: Any,
        *,
        pr: dict[str, Any] | None = None,
        files: list[str] | None = None,
    ) -> dict[str, Any]:
        if pr is None or files is None:
            pr, files = self._tier_four_settled_pr()

        def _gh_json_dispatch(args: list[str]) -> Any:
            endpoint = str(args[-1])
            if "/collaborators/" in endpoint and endpoint.endswith("/permission"):
                return {"permission": "admin"}
            if not any("/statuses" in str(arg) for arg in args):
                raise AssertionError(f"unexpected gh api call: {args}")
            if isinstance(statuses, Exception):
                raise statuses
            return statuses

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            _gh_json_dispatch,
        )
        return _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
            human_risk_settlement_recorded=True,
            repo_slug="synaptent/aragora",
        )

    def test_settlement_creator_scarmani_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        quorum = self._pin_quorum(monkeypatch, [self._settlement_status("scarmani")])
        assert quorum["human_preapproval_recorded"] is True
        assert quorum["admin_squash_allowed"] is True
        pin = quorum["settlement_creator_pin"]
        assert pin["checked"] is True
        assert pin["verified"] is True
        assert pin["trusted_creator"] == "scarmani"
        assert any("settlement-creator pin" in reason for reason in quorum["reasons"])

    def test_untrusted_preapproval_comment_with_trusted_status_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr, files = self._tier_four_settled_pr()
        settlement_comment = pr["comments"][-1]
        settlement_comment["author"] = {"login": "random-contributor"}
        settlement_comment["authorAssociation"] = "CONTRIBUTOR"
        settlement_url = settlement_comment["url"]

        def _gh_json_dispatch(args: list[str]) -> Any:
            assert any("/statuses" in str(arg) for arg in args), (
                "untrusted settlement comments must fail before collaborator permission lookup"
            )
            return [self._settlement_status("scarmani", target_url=settlement_url)]

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            _gh_json_dispatch,
        )

        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
            human_risk_settlement_recorded=True,
            repo_slug="synaptent/aragora",
        )

        assert quorum["human_preapproval_recorded"] is False
        assert quorum["admin_squash_allowed"] is False
        assert quorum["settlement_creator_pin"]["checked"] is False

    def test_trusted_admin_collaborator_comment_with_bound_status_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr, files = self._tier_four_settled_pr()
        settlement_comment = pr["comments"][-1]
        settlement_comment["author"] = {"login": "scarmani"}
        settlement_comment["authorAssociation"] = "COLLABORATOR"
        settlement_url = settlement_comment["url"]

        def _gh_json_dispatch(args: list[str]) -> Any:
            endpoint = str(args[-1])
            if "/collaborators/scarmani/permission" in endpoint:
                return {"permission": "admin"}
            if "/statuses" in endpoint:
                return [self._settlement_status("scarmani", target_url=settlement_url)]
            raise AssertionError(f"unexpected gh api call: {args}")

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            _gh_json_dispatch,
        )

        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
            human_risk_settlement_recorded=True,
            repo_slug="synaptent/aragora",
        )

        assert quorum["human_preapproval_recorded"] is True
        assert quorum["admin_squash_allowed"] is True

    def test_owner_preapproval_comment_requires_live_admin_permission(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr, files = self._tier_four_settled_pr()

        def _gh_json_dispatch(args: list[str]) -> Any:
            endpoint = str(args[-1])
            if "/collaborators/scarmani/permission" in endpoint:
                return {"permission": "write"}
            raise AssertionError(f"unexpected gh api call: {args}")

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            _gh_json_dispatch,
        )

        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
            human_risk_settlement_recorded=True,
            repo_slug="synaptent/aragora",
        )

        assert quorum["human_preapproval_recorded"] is False
        assert quorum["admin_squash_allowed"] is False
        assert quorum["settlement_creator_pin"]["checked"] is False

    def test_non_admin_collaborator_preapproval_comment_is_rejected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr, files = self._tier_four_settled_pr()
        settlement_comment = pr["comments"][-1]
        settlement_comment["author"] = {"login": "scarmani"}
        settlement_comment["authorAssociation"] = "COLLABORATOR"

        def _gh_json_dispatch(args: list[str]) -> Any:
            endpoint = str(args[-1])
            if "/collaborators/scarmani/permission" in endpoint:
                return {"permission": "write"}
            raise AssertionError(f"unexpected gh api call: {args}")

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            _gh_json_dispatch,
        )

        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
            human_risk_settlement_recorded=True,
            repo_slug="synaptent/aragora",
        )

        assert quorum["human_preapproval_recorded"] is False
        assert quorum["admin_squash_allowed"] is False
        assert quorum["settlement_creator_pin"]["checked"] is False

    def test_settlement_status_target_url_must_match_trusted_comment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr, files = self._tier_four_settled_pr()

        quorum = self._pin_quorum(
            monkeypatch,
            [
                self._settlement_status(
                    "scarmani",
                    target_url="https://github.example/pr/7900#issuecomment-wrong",
                )
            ],
            pr=pr,
            files=files,
        )

        assert quorum["human_preapproval_recorded"] is False
        assert quorum["admin_squash_allowed"] is False
        assert "target_url does not match" in quorum["settlement_creator_pin"]["reason"]

    def test_newer_trusted_settlement_comment_status_pair_counts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr, files = self._tier_four_settled_pr()
        head_sha = str(pr["headRefOid"])
        newer_url = "https://github.example/pr/7900#issuecomment-settlement-retry"
        pr["comments"].append(
            {
                "author": {"login": "scarmani"},
                "authorAssociation": "OWNER",
                "createdAt": "2026-06-15T02:24:41Z",
                "url": newer_url,
                "body": (
                    "Tier-4 Human Settlement Authorization\n\n"
                    "PR: #7900\n"
                    f"Exact head: {head_sha}\n"
                    "Authorized action: admin_squash_merge only if checks stay green.\n\n"
                    "Human-risk settlement: I accept the Tier 4 risk for this PR."
                ),
            }
        )

        quorum = self._pin_quorum(
            monkeypatch,
            [self._settlement_status("scarmani", target_url=newer_url)],
            pr=pr,
            files=files,
        )

        assert quorum["human_preapproval_recorded"] is True
        assert quorum["admin_squash_allowed"] is True

    def test_older_settlement_comment_target_rejected_after_newer_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr, files = self._tier_four_settled_pr()
        head_sha = str(pr["headRefOid"])
        older_url = str(pr["comments"][-1]["url"])
        pr["comments"].append(
            {
                "author": {"login": "scarmani"},
                "authorAssociation": "OWNER",
                "createdAt": "2026-06-15T02:24:41Z",
                "url": "https://github.example/pr/7900#issuecomment-settlement-retry",
                "body": (
                    "Tier-4 Human Settlement Authorization\n\n"
                    "PR: #7900\n"
                    f"Exact head: {head_sha}\n"
                    "Authorized action: admin_squash_merge only if checks stay green.\n\n"
                    "Human-risk settlement: I accept the Tier 4 risk for this PR."
                ),
            }
        )

        quorum = self._pin_quorum(
            monkeypatch,
            [self._settlement_status("scarmani", target_url=older_url)],
            pr=pr,
            files=files,
        )

        assert quorum["human_preapproval_recorded"] is False
        assert quorum["admin_squash_allowed"] is False
        assert "target_url does not match" in quorum["settlement_creator_pin"]["reason"]

    def test_settlement_creator_an0mium_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The #8169 precedent gap: an automation-capable login posting the
        status must NOT count, even though every other condition holds."""
        quorum = self._pin_quorum(monkeypatch, [self._settlement_status("an0mium")])
        assert quorum["human_preapproval_recorded"] is False
        assert quorum["admin_squash_allowed"] is False
        assert quorum["status"] == "human_preapproval_required"
        pin = quorum["settlement_creator_pin"]
        assert pin["checked"] is True
        assert pin["verified"] is False
        assert "an0mium" in pin["reason"]
        assert "scarmani" in pin["reason"]
        assert any("settlement-creator pin" in reason for reason in quorum["reasons"])

    def test_settlement_creator_missing_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        quorum = self._pin_quorum(monkeypatch, [self._settlement_status(None)])
        assert quorum["human_preapproval_recorded"] is False
        assert quorum["admin_squash_allowed"] is False
        pin = quorum["settlement_creator_pin"]
        assert pin["verified"] is False
        assert "no creator login" in pin["reason"]

    def test_settlement_creator_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_SETTLEMENT_CREATOR", "alice-oversight")
        pr, files = self._tier_four_settled_pr()
        pr["comments"][-1]["author"] = {"login": "alice-oversight"}
        quorum = self._pin_quorum(
            monkeypatch,
            [self._settlement_status("alice-oversight")],
            pr=pr,
            files=files,
        )
        assert quorum["human_preapproval_recorded"] is True
        assert quorum["settlement_creator_pin"]["trusted_creator"] == "alice-oversight"

    def test_env_override_rejects_default_creator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ARAGORA_SETTLEMENT_CREATOR", "alice-oversight")
        quorum = self._pin_quorum(monkeypatch, [self._settlement_status("scarmani")])
        assert quorum["human_preapproval_recorded"] is False
        assert quorum["settlement_creator_pin"]["verified"] is False

    def test_transport_error_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        quorum = self._pin_quorum(monkeypatch, _GhError("api unavailable"))
        assert quorum["human_preapproval_recorded"] is False
        assert quorum["admin_squash_allowed"] is False
        assert "failing closed" in quorum["settlement_creator_pin"]["reason"]

    def test_unexpected_payload_shape_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        quorum = self._pin_quorum(monkeypatch, {"not": "a list"})
        assert quorum["human_preapproval_recorded"] is False
        assert "failing closed" in quorum["settlement_creator_pin"]["reason"]

    def test_missing_status_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        quorum = self._pin_quorum(monkeypatch, [])
        assert quorum["human_preapproval_recorded"] is False
        assert (
            "no 'aragora/human-settlement' status" in (quorum["settlement_creator_pin"]["reason"])
        )

    def test_newest_untrusted_status_shadows_older_trusted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The statuses API is newest-first; an untrusted overwrite on top of a
        genuine scarmani status must reject (the rollup reflects the newest)."""
        quorum = self._pin_quorum(
            monkeypatch,
            [
                self._settlement_status(
                    "aragora-automation-fable[bot]",
                    updated_at="2026-06-15T02:25:41Z",
                ),
                self._settlement_status("scarmani", updated_at="2026-06-15T02:22:41Z"),
            ],
        )
        assert quorum["human_preapproval_recorded"] is False
        assert "aragora-automation-fable[bot]" in (quorum["settlement_creator_pin"]["reason"])

    def test_newest_pending_status_rejected_despite_trusted_older(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        quorum = self._pin_quorum(
            monkeypatch,
            [
                self._settlement_status(
                    "scarmani",
                    state="pending",
                    updated_at="2026-06-15T02:25:41Z",
                ),
                self._settlement_status("scarmani", updated_at="2026-06-15T02:22:41Z"),
            ],
        )
        assert quorum["human_preapproval_recorded"] is False
        assert "not success" in quorum["settlement_creator_pin"]["reason"]

    @pytest.mark.parametrize("newer_state", ["pending", "failure"])
    def test_newer_non_success_status_blocks_older_trusted_success_even_if_returned_later(
        self, monkeypatch: pytest.MonkeyPatch, newer_state: str
    ) -> None:
        quorum = self._pin_quorum(
            monkeypatch,
            [
                self._settlement_status(
                    "scarmani",
                    updated_at="2026-06-15T02:22:41Z",
                    created_at="2026-06-15T02:22:41Z",
                ),
                self._settlement_status(
                    "scarmani",
                    state=newer_state,
                    updated_at="2026-06-15T02:25:41Z",
                    created_at="2026-06-15T02:25:41Z",
                ),
            ],
        )

        assert quorum["human_preapproval_recorded"] is False
        assert "not success" in quorum["settlement_creator_pin"]["reason"]

    @pytest.mark.parametrize("older_state", ["pending", "failure"])
    def test_newer_trusted_success_counts_despite_older_non_success_returned_first(
        self, monkeypatch: pytest.MonkeyPatch, older_state: str
    ) -> None:
        quorum = self._pin_quorum(
            monkeypatch,
            [
                self._settlement_status(
                    "scarmani",
                    state=older_state,
                    updated_at="2026-06-15T02:22:41Z",
                    created_at="2026-06-15T02:22:41Z",
                ),
                self._settlement_status(
                    "scarmani",
                    updated_at="2026-06-15T02:25:41Z",
                    created_at="2026-06-15T02:25:41Z",
                ),
            ],
        )

        assert quorum["human_preapproval_recorded"] is True
        assert quorum["admin_squash_allowed"] is True

    def test_conflicting_human_statuses_without_timestamps_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        quorum = self._pin_quorum(
            monkeypatch,
            [
                self._settlement_status("scarmani"),
                self._settlement_status("scarmani", state="pending"),
            ],
        )

        assert quorum["human_preapproval_recorded"] is False
        assert "timestamp" in quorum["settlement_creator_pin"]["reason"]

    def test_tied_newest_human_status_timestamps_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        quorum = self._pin_quorum(
            monkeypatch,
            [
                self._settlement_status(
                    "scarmani",
                    updated_at="2026-06-15T02:25:41Z",
                ),
                self._settlement_status(
                    "scarmani",
                    state="pending",
                    updated_at="2026-06-15T02:25:41Z",
                ),
            ],
        )

        assert quorum["human_preapproval_recorded"] is False
        assert "timestamp" in quorum["settlement_creator_pin"]["reason"]

    def test_settlement_comment_without_matching_head_timestamp_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr, files = self._tier_four_settled_pr()
        pr.pop("headCommittedDate", None)
        pr["commits"] = [{"committedDate": "2026-06-15T02:21:41Z"}]

        def _gh_json_dispatch(args: list[str]) -> Any:
            raise AssertionError(f"missing head timestamp should fail before gh call: {args}")

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            _gh_json_dispatch,
        )

        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
            human_risk_settlement_recorded=True,
            repo_slug="synaptent/aragora",
        )

        assert quorum["human_preapproval_recorded"] is False
        assert tier4_settlement._head_committed_at_from_pr(pr) == ""

    def test_pin_not_consulted_below_tier_four(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Non-Tier-4 packets must not pay the statuses API call at all."""

        def _explode(args: list[str]) -> Any:
            raise AssertionError(f"unexpected gh call from quorum builder: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", _explode)
        files = ["aragora/agents/router.py"]  # Tier 1
        quorum = _build_model_review_quorum(
            pr=_make_pr(files=files),
            files=files,
            protocol=_executed_protocol(),
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["settlement_creator_pin"]["checked"] is False
        assert quorum["settlement_creator_pin"]["trusted_creator"] == "scarmani"

    def test_creator_check_helper_requires_repo_and_head(self) -> None:
        from aragora.cli.commands.review_queue import (
            _human_settlement_status_creator_verified,
        )

        ok, reason = _human_settlement_status_creator_verified(repo_slug="", head_sha="abc")
        assert ok is False
        assert "failing closed" in reason
        ok, reason = _human_settlement_status_creator_verified(
            repo_slug="synaptent/aragora", head_sha=""
        )
        assert ok is False

    def test_creator_check_helper_requires_comment_target_url(self) -> None:
        from aragora.cli.commands.review_queue import (
            _human_settlement_status_creator_verified,
        )

        def _explode(args: list[str]) -> Any:
            raise AssertionError(f"missing target_url should fail before gh call: {args}")

        ok, reason = _human_settlement_status_creator_verified(
            repo_slug="synaptent/aragora",
            head_sha="abc123",
            gh_json=_explode,
        )

        assert ok is False
        assert "missing trusted settlement comment target_url" in reason

    # --- Finding 2: source-side filter on _dogfood_evidence_from_comments ---

    def test_dogfood_with_unknown_model_is_excluded_at_source(self) -> None:
        """A dogfood comment whose first heading does not name a known model
        must not appear in ``dogfood_evidence`` at all (parallel to the signals
        path's behaviour). This keeps the evidence list interpretable for
        downstream consumers; the counting boundary already neutralised the
        inflation, but the source-side filter prevents misleading artifacts."""
        files = ["aragora/agents/router.py"]  # Tier 1
        pr = _make_pr(files=files)
        pr["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": "## Generic dogfood note (no model named)\n2 cases pass",
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["dogfood_evidence"] == []
        # And quorum still incomplete because dogfood is required but absent.
        assert quorum["admin_squash_allowed"] is False

    @pytest.mark.parametrize("bot_login", ("github-actions", "github-actions[bot]"))
    def test_dogfood_from_github_actions_is_excluded_at_source(self, bot_login: str) -> None:
        """Bot-authored dogfood comments must not count as model evidence,
        mirroring the existing filter in ``_model_review_signals_from_comments``."""
        files = ["aragora/agents/router.py"]
        pr = _make_pr(files=files)
        pr["comments"] = [
            {
                "author": {"login": bot_login},
                "body": _codex_openai_body(body="automated regression sweep"),
            },
            _codex_openai_comment(),
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        # The bot comment is filtered; the real reviewer comment passes.
        assert len(quorum["dogfood_evidence"]) == 1
        assert quorum["dogfood_evidence"][0]["github_author"] == "an0mium"
        assert quorum["counted_reviewer_ids"] == ["openai"]

    def test_model_review_signal_from_github_actions_bot_is_excluded_at_source(
        self,
    ) -> None:
        """The real GitHub Actions bot login must not count as a model reviewer."""
        files = ["aragora/agents/router.py"]
        pr = _make_pr(files=files)
        pr["comments"] = [
            {
                "author": {"login": "github-actions[bot]"},
                "body": _codex_openai_body(
                    heading="## Codex review",
                    body="independent semantic review with structured lineage metadata",
                ),
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )

        assert quorum["reviewer_signals"] == []
        assert quorum["dogfood_evidence"] == []
        assert quorum["counted_reviewer_ids"] == []

    # --- Plain-headed dogfood with body-named model (PR #7587 regression) ---
    #
    # A dogfood comment headed `## Focused adversarial dogfood` (no `(claude)`
    # in the heading) but whose BODY discloses the model family must count, so
    # long as it is head-grounded, not bot-authored, and carries the dogfood
    # tokens. This mirrors the model-review-signal recognizer, which already
    # reads the model family from structured metadata rather than the heading.

    def test_plain_headed_dogfood_with_model_family_line_counts(self) -> None:
        """`## Focused adversarial dogfood` heading + `Model family: claude`
        line in the body must be recognized as Claude dogfood evidence."""
        files = ["aragora/agents/router.py"]  # Tier 1
        pr = _make_pr(files=files)
        pr["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Focused adversarial dogfood\n\n"
                    "**Reviewer harness:** claude-code\n"
                    "**Model family:** claude\n"
                    "**Model id:** claude-opus-4-8\n"
                    "**Receipt artifact:** /tmp/claude-dogfood.md\n\n"
                    "6/6 adversarial cases pass."
                ),
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert len(quorum["dogfood_evidence"]) == 1
        entry = quorum["dogfood_evidence"][0]
        assert entry["model_family"] == "claude"
        assert entry["reviewer_id"] == "claude"
        assert "claude" in quorum["counted_reviewer_ids"]

    def test_plain_headed_dogfood_with_far_model_family_line_counts(self) -> None:
        """The `Model family:` disclosure may appear anywhere in the body,
        not only in the first lines after the heading."""
        files = ["aragora/agents/router.py"]
        pr = _make_pr(files=files)
        pr["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Focused adversarial dogfood\n\n"
                    + ("Walked each adversarial case manually.\n" * 30)
                    + "\n**Model family:** openai\n"
                    + "**Model id:** gpt-5-codex\n"
                    + "**Receipt artifact:** /tmp/openai-dogfood.md\n"
                ),
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert len(quorum["dogfood_evidence"]) == 1
        assert quorum["dogfood_evidence"][0]["model_family"] == "openai"
        assert "openai" in quorum["counted_reviewer_ids"]

    def test_plain_headed_dogfood_without_model_named_still_excluded(self) -> None:
        """A plain-headed dogfood comment that names NO model anywhere in the
        body must still be excluded — the relaxation only applies when a known
        model family is discoverable in the body."""
        files = ["aragora/agents/router.py"]
        pr = _make_pr(files=files)
        pr["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": "## Focused adversarial dogfood\n\n6/6 cases pass, no model named.",
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["dogfood_evidence"] == []
        assert quorum["counted_reviewer_ids"] == []

    def test_plain_headed_dogfood_not_head_grounded_still_excluded(self) -> None:
        """Even with a body-named model, a stale (non-head-grounded) dogfood
        comment must NOT count — head-grounding is preserved."""
        head_sha = "abcdef1234567890abcdef1234567890abcdef12"
        files = ["aragora/agents/router.py"]
        pr = _make_pr(files=files)
        pr["headRefOid"] = head_sha
        pr["commits"] = [{"oid": head_sha, "committedDate": "2026-04-28T20:00:00Z"}]
        pr["comments"] = [
            {
                "author": {"login": "an0mium"},
                # Posted BEFORE head commit and does not cite the head SHA.
                "createdAt": "2026-04-28T18:00:00Z",
                "body": (
                    "## Focused adversarial dogfood\n\n"
                    "**Model family:** claude\n"
                    "**Model id:** claude-opus-4-8\n"
                    "**Receipt artifact:** /tmp/r.md\n\n"
                    "6/6 cases pass."
                ),
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["dogfood_evidence"] == []
        assert quorum["counted_reviewer_ids"] == []

    def test_plain_headed_dogfood_from_github_actions_still_excluded(self) -> None:
        """Even with a body-named model, a github-actions-authored dogfood
        comment must NOT count — the bot exclusion is preserved."""
        files = ["aragora/agents/router.py"]
        pr = _make_pr(files=files)
        pr["comments"] = [
            {
                "author": {"login": "github-actions[bot]"},
                "body": (
                    "## Focused adversarial dogfood\n\n"
                    "**Model family:** claude\n"
                    "**Model id:** claude-opus-4-8\n"
                    "**Receipt artifact:** /tmp/r.md\n\n"
                    "6/6 cases pass."
                ),
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["dogfood_evidence"] == []
        assert quorum["counted_reviewer_ids"] == []

    def test_plain_headed_dogfood_with_unknown_model_family_excluded(self) -> None:
        """A `Model family:` line that names something we cannot normalize to a
        known family must NOT count (no phantom inflation)."""
        files = ["aragora/agents/router.py"]
        pr = _make_pr(files=files)
        pr["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Focused adversarial dogfood\n\n"
                    "**Model family:** acme-frontier-9000\n\n"
                    "6/6 cases pass."
                ),
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["dogfood_evidence"] == []
        assert quorum["counted_reviewer_ids"] == []

    def test_dogfood_heading_body_family_conflict_is_not_counted(self) -> None:
        """Finding 1 (fail-closed bypass): when the heading names one family and
        post-heading metadata names a *conflicting* family, the original
        resolver blocks the comment with ``heading_model_family_conflict``. The
        body-family fallback must NOT override that block — the comment stays
        uncounted."""
        from aragora.cli.commands.review_queue import _resolve_dogfood_identity

        body = (
            "## Claude focused adversarial dogfood\n\n"
            "**Reviewer harness:** claude-code\n"
            "**Model family:** openai\n"  # conflicts with the heading's "claude"
            "**Model id:** gpt-5-codex\n"
            "**Receipt artifact:** /tmp/r.md\n\n"
            "6/6 cases pass."
        )
        identity = _resolve_dogfood_identity(body)
        assert "heading_model_family_conflict" in identity.identity_problems
        assert identity.identity_source != "dogfood_body_model_family"

        files = ["aragora/agents/router.py"]  # Tier 1
        pr = _make_pr(files=files)
        pr["comments"] = [{"author": {"login": "an0mium"}, "body": body}]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["counted_reviewer_ids"] == []

    def test_dogfood_model_family_inside_code_fence_is_not_counted(self) -> None:
        """Finding 2 (code-fence inflation): a `Model family:` line that appears
        only inside a fenced code block (e.g. a pasted example template) must NOT
        be treated as a real disclosure."""
        from aragora.cli.commands.review_queue import _model_family_from_body

        body = (
            "## Focused adversarial dogfood\n\n"
            "Reviewers should disclose their model like this:\n\n"
            "```\n"
            "**Model family:** claude\n"
            "```\n\n"
            "6/6 cases pass (no real disclosure outside the fence)."
        )
        assert _model_family_from_body(body) == ""

        files = ["aragora/agents/router.py"]
        pr = _make_pr(files=files)
        pr["comments"] = [{"author": {"login": "an0mium"}, "body": body}]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert quorum["dogfood_evidence"] == []
        assert quorum["counted_reviewer_ids"] == []

    def test_dogfood_model_family_in_inline_code_span_is_not_counted(self) -> None:
        """An inline-code back-ticked `Model family:` mention must not be parsed
        as a disclosure either."""
        from aragora.cli.commands.review_queue import _model_family_from_body

        body = (
            "## Focused adversarial dogfood\n\n"
            "I left a note saying `Model family: claude` as an example only.\n\n"
            "6/6 cases pass."
        )
        assert _model_family_from_body(body) == ""

    def test_dogfood_real_family_line_outside_fence_still_counts(self) -> None:
        """A genuine `Model family:` disclosure outside any code fence still
        counts even when an example fence is also present — the fence stripping
        must not eat the real line."""
        from aragora.cli.commands.review_queue import _model_family_from_body

        body = (
            "## Focused adversarial dogfood\n\n"
            "Template for reference:\n\n"
            "```\n"
            "**Model family:** <family>\n"
            "```\n\n"
            "**Model family:** claude\n"
            "**Receipt artifact:** /tmp/r.md\n\n"
            "6/6 cases pass."
        )
        assert _model_family_from_body(body) == "claude"

        files = ["aragora/agents/router.py"]
        pr = _make_pr(files=files)
        pr["comments"] = [{"author": {"login": "an0mium"}, "body": body}]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        assert len(quorum["dogfood_evidence"]) == 1
        assert quorum["dogfood_evidence"][0]["model_family"] == "claude"
        assert "claude" in quorum["counted_reviewer_ids"]

    def test_dogfood_negative_verdict_is_not_counted(self) -> None:
        head = "cd87c5a1b2db34f04167906553502db3ede9525e"
        comments = [
            _codex_openai_comment(
                body=(
                    f"Current head: {head}\n"
                    "Verdict: FAIL\n"
                    "Blocking findings: found - exact-head evidence is stale."
                )
            )
        ]

        assert _dogfood_evidence_from_comments(comments, head_sha=head) == []


_QUORUM_ONLY_FAILURE_SURFACES = {
    "required_pr_checks": {
        "quorum_only_failure": True,
        # External settle-tooling shape: the merge-quorum row is a distinct failing
        # required check, so the surface is also advisory_settle-clear.
        "advisory_settle_surface_clear": True,
    }
}

# In-job (#8739) shape: inside the enforcing Aragora Merge Quorum job the quorum row
# is the excluded current self-check, so ``quorum_only_failure`` is False even though
# the quorum signal is exactly what is missing. No NON-quorum required check is
# failing/pending, so ``advisory_settle_surface_clear`` is True and advisory_settle
# must still be reachable.
_INJOB_QUORUM_SELF_CHECK_SURFACES = {
    "required_pr_checks": {
        "quorum_only_failure": False,
        "advisory_settle_surface_clear": True,
    }
}


class TestAdvisoryDissentSettleGate:
    """The opt-in advisory_settle path (ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE).

    Default OFF — byte-identical to today. When ON, a Tier 0-2 PR whose only
    failing required check is the model-quorum check settles via
    verdict=advisory_settle when (and only when): a western-frontier review is
    present at head IN ANY VERDICT, there is GENUINE advisory dissent being waived
    (advisory_findings non-empty), zero [P0]/[P1] blocking findings across all
    reviews, and nothing else is pending/unavailable/blocking.

    These tests exercise the REAL caller shape: the quorum-only failure means the
    merge-quorum required check IS failing, so ``has_failures=True`` (the first
    cut's ``has_failures=False`` masked the dead-code path — #8729 claude [P1]).
    """

    HEAD = "cd87c5a1b2db34f04167906553502db3ede9525e"

    @pytest.fixture(autouse=True)
    def _strict_tiered_gate(self, monkeypatch) -> None:
        # Pin the (separate) tiered-merge-gate flag OFF so a lone western-frontier
        # signal does NOT satisfy strict Tier 1-2 quorum on its own — keeps these
        # tests on the advisory_settle rescue path, not the tiered-gate relaxation.
        monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "0")

    def _wf_advisory_cr_comment(self) -> dict[str, Any]:
        # A western-frontier (claude) review at head whose verdict is an advisory
        # [P2] CHANGES-REQUESTED (no [P0]/[P1]). Advisory only when the severity
        # gate is ON.
        return {
            "author": {"login": "an0mium"},
            "body": (
                "## Claude independent model review\n"
                "Model family: claude\n"
                f"Current head: {self.HEAD}\n"
                "Verdict: CHANGES-REQUESTED\n"
                "[P2] Add stronger smoke coverage in a follow-up."
            ),
        }

    def _pr_wf_advisory_cr(self, files: list[str]) -> dict[str, Any]:
        pr = _make_pr(files=files)
        pr["headRefOid"] = self.HEAD
        pr["comments"] = [self._wf_advisory_cr_comment()]
        return pr

    def _tier1_pr_wf_advisory_cr(self) -> dict[str, Any]:
        return self._pr_wf_advisory_cr(["aragora/agents/router.py"])

    def _tier1_pr_lone_approval(self) -> dict[str, Any]:
        # A single western-frontier APPROVAL and no dissent at all.
        pr = _make_pr(files=["aragora/agents/router.py"])
        pr["headRefOid"] = self.HEAD
        pr["comments"] = [
            _codex_openai_review_comment(
                body=(
                    f"Current head: {self.HEAD}\nVerdict: approve.\n"
                    "Focused adversarial dogfood passed."
                )
            ),
        ]
        return pr

    def _quorum(self, pr, *, has_failures=True, has_pending=False, files=None, check_surfaces=None):
        return _build_model_review_quorum(
            pr=pr,
            files=files or ["aragora/agents/router.py"],
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="repair_first" if has_failures else "approve_candidate",
            has_pending=has_pending,
            has_failures=has_failures,
            check_surfaces=check_surfaces
            if check_surfaces is not None
            else _QUORUM_ONLY_FAILURE_SURFACES,
        )

    def test_flag_on_settles_in_enforcing_job_via_surface_clear(self, monkeypatch) -> None:
        # #8739 regression: inside the enforcing merge-quorum job the quorum row is
        # the excluded self-check, so quorum_only_failure is False. advisory_settle
        # must still be reachable via the self-check-independent
        # advisory_settle_surface_clear predicate — otherwise enabling the flag
        # (#8738) is a no-op in CI.
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        q = self._quorum(
            self._tier1_pr_wf_advisory_cr(),
            has_failures=True,
            check_surfaces=_INJOB_QUORUM_SELF_CHECK_SURFACES,
        )
        assert q["tier"] == 1
        assert q["status"] == "satisfied"
        assert q["verdict"] == "advisory_settle"
        assert q["admin_squash_allowed"] is True
        assert q["unresolved_dissent"] is False

    def test_flag_off_advisory_cr_still_blocked(self, monkeypatch) -> None:
        # Flag OFF (default): advisory_settle dormant; behavior byte-identical.
        monkeypatch.delenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", raising=False)
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        q = self._quorum(self._tier1_pr_wf_advisory_cr())
        assert q["verdict"] != "advisory_settle"
        assert q["admin_squash_allowed"] is False

    @pytest.mark.parametrize(
        ("expected_tier", "files"),
        [
            (0, ["docs/status/queue.md"]),
            (1, ["aragora/agents/router.py"]),
            (2, ["aragora/cli/commands/swarm.py"]),
        ],
    )
    def test_flag_on_wf_advisory_cr_settles_only_for_tier_zero_to_two(
        self, monkeypatch, expected_tier: int, files: list[str]
    ) -> None:
        # THE regression: real caller passes has_failures=True (merge-quorum is the
        # failing check). advisory_settle must still be REACHED (not masked by the
        # repair_or_wait branch — #8729 claude [P1]), but only for Tier 0-2.
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        q = self._quorum(
            self._pr_wf_advisory_cr(files),
            has_failures=True,
            files=files,
        )
        assert q["tier"] == expected_tier
        assert q["status"] == "satisfied"
        assert q["verdict"] == "advisory_settle"
        assert q["admin_squash_allowed"] is True
        assert q["unresolved_dissent"] is False

    def test_flag_on_surfaces_advisory_findings(self, monkeypatch) -> None:
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        q = self._quorum(self._tier1_pr_wf_advisory_cr())
        assert q["verdict"] == "advisory_settle"
        assert len(q["advisory_findings"]) >= 1

    def test_flag_on_lone_approval_no_dissent_does_not_settle(self, monkeypatch) -> None:
        # #8729 openai [P1]: a lone approving WF comment with NO advisory dissent
        # must NOT settle (that would be a one-review quorum bypass).
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        q = self._quorum(self._tier1_pr_lone_approval())
        assert q["verdict"] != "advisory_settle"
        assert q["admin_squash_allowed"] is False

    @pytest.mark.parametrize("severity", ["P0", "P1"])
    def test_flag_on_p0_p1_finding_still_blocked(self, monkeypatch, severity: str) -> None:
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        pr = self._tier1_pr_wf_advisory_cr()
        pr["comments"].append(
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Codex review\nModel family: openai\n"
                    f"Current head: {self.HEAD}\n"
                    "Verdict: CHANGES-REQUESTED\n"
                    f"[{severity}] Merge gate dissent is unresolved."
                ),
            }
        )
        q = self._quorum(pr)
        assert q["verdict"] != "advisory_settle"
        assert q["admin_squash_allowed"] is False

    @pytest.mark.parametrize(
        ("expected_tier", "files"),
        [
            (3, ["aragora/auth/session.py"]),
            (4, [".github/workflows/aragora-merge-quorum.yml"]),
        ],
    )
    def test_flag_on_tier_three_and_four_unaffected(
        self, monkeypatch, expected_tier: int, files: list[str]
    ) -> None:
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        q = self._quorum(self._pr_wf_advisory_cr(files), files=files)
        assert q["tier"] == expected_tier
        assert q["verdict"] != "advisory_settle"
        assert q["admin_squash_allowed"] is False
        assert q["requires_human_risk_settlement"] is True

    def test_flag_on_non_wf_only_does_not_settle(self, monkeypatch) -> None:
        # Only a NON-western-frontier (grok) review at head -> no WF review present.
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        pr = _make_pr(files=["aragora/agents/router.py"])
        pr["headRefOid"] = self.HEAD
        pr["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Grok independent model review\nModel family: grok\n"
                    f"Current head: {self.HEAD}\n"
                    "Verdict: CHANGES-REQUESTED\n[P2] follow-up."
                ),
            },
        ]
        q = self._quorum(pr)
        assert q["verdict"] != "advisory_settle"
        assert q["admin_squash_allowed"] is False

    def test_flag_on_pending_checks_does_not_settle(self, monkeypatch) -> None:
        # A pending check is a real "wait" condition; advisory_settle must not fire.
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        q = self._quorum(self._tier1_pr_wf_advisory_cr(), has_failures=False, has_pending=True)
        assert q["verdict"] != "advisory_settle"
        assert q["admin_squash_allowed"] is False

    def test_flag_on_spoofed_wf_identity_does_not_settle(self, monkeypatch) -> None:
        # #8729 openai [P1]: a conflicted/uncountable identity (a "## Grok" heading
        # with a claimed "Model family: claude") must NOT satisfy the WF requirement
        # — it is not a countable western-frontier signal on the strict path either.
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        pr = _make_pr(files=["aragora/agents/router.py"])
        pr["headRefOid"] = self.HEAD
        pr["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Grok independent model review\n"
                    "Model family: claude\n"  # conflicts with the Grok heading
                    f"Current head: {self.HEAD}\n"
                    "Verdict: CHANGES-REQUESTED\n[P2] follow-up."
                ),
            },
        ]
        q = self._quorum(pr)
        assert q["verdict"] != "advisory_settle"
        assert q["admin_squash_allowed"] is False

    def test_flag_on_bot_authored_advisory_cr_is_not_genuine_dissent(self, monkeypatch) -> None:
        # #8729 openai [P1] (r4): a valid WF approval PLUS a github-actions[bot]
        # advisory CR must NOT settle — the bot CR is not genuine (validated-source)
        # advisory dissent, so there is nothing legitimate to waive.
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        pr = _make_pr(files=["aragora/agents/router.py"])
        pr["headRefOid"] = self.HEAD
        pr["comments"] = [
            _codex_openai_review_comment(
                body=f"Current head: {self.HEAD}\nVerdict: approve.\nFocused adversarial dogfood passed."
            ),
            {
                "author": {"login": "github-actions[bot]"},
                "body": (
                    "## Claude independent model review\nModel family: claude\n"
                    f"Current head: {self.HEAD}\nVerdict: CHANGES-REQUESTED\n[P2] nit."
                ),
            },
        ]
        q = self._quorum(pr)
        assert q["verdict"] != "advisory_settle"
        assert q["admin_squash_allowed"] is False

    def test_flag_on_bot_authored_wf_review_does_not_settle(self, monkeypatch) -> None:
        # #8729 openai [P1] (r2): a github-actions[bot]-authored "Claude" advisory
        # comment must NOT satisfy the WF prerequisite — the strict signal path
        # rejects synthetic authors, and so must advisory_settle.
        monkeypatch.setenv("ARAGORA_ENABLE_ADVISORY_DISSENT_SETTLE", "1")
        monkeypatch.setenv("ARAGORA_ENABLE_SEVERITY_GATED_DISSENT", "1")
        pr = _make_pr(files=["aragora/agents/router.py"])
        pr["headRefOid"] = self.HEAD
        pr["comments"] = [
            {
                "author": {"login": "github-actions[bot]"},
                "body": (
                    "## Claude independent model review\n"
                    "Model family: claude\n"
                    f"Current head: {self.HEAD}\n"
                    "Verdict: CHANGES-REQUESTED\n[P2] follow-up."
                ),
            },
        ]
        q = self._quorum(pr)
        assert q["verdict"] != "advisory_settle"
        assert q["admin_squash_allowed"] is False


class TestHasBlockingOrNegativeVerdict:
    def test_blocker_value_starting_with_no_letters_is_still_blocking(self) -> None:
        # Word-boundary regression: "node"/"not working" must not be swallowed
        # by the non-blocking prefix "no".
        assert _has_blocking_or_negative_verdict("Blockers: node crashes on startup")
        assert _has_blocking_or_negative_verdict("Blocking findings: not working under load")

    def test_markdown_heading_labels_are_recognized(self) -> None:
        assert _has_blocking_or_negative_verdict("### Verdict: FAIL")
        assert _has_blocking_or_negative_verdict("> **Verdict:** blocked on stale evidence")

    def test_dash_separated_negative_labels_are_recognized(self) -> None:
        assert _has_blocking_or_negative_verdict("Verdict - FAIL")
        assert _has_blocking_or_negative_verdict("Blocking findings — found stale evidence")

    def test_multi_line_blocker_lists_are_blocking(self) -> None:
        assert _has_blocking_or_negative_verdict("Blocking findings:\n- Crash on startup")
        assert _has_blocking_or_negative_verdict("Blockers:\n\n1. Stale exact-head evidence")

    def test_multi_line_non_blocking_values_remain_countable(self) -> None:
        assert not _has_blocking_or_negative_verdict("Blockers:\nNone found.")
        assert not _has_blocking_or_negative_verdict("Blocking findings:")

    def test_decorated_and_numbered_labels_are_recognized(self) -> None:
        assert _has_blocking_or_negative_verdict("1. Verdict: FAIL")
        assert _has_blocking_or_negative_verdict("*Verdict*: FAIL")
        assert _has_blocking_or_negative_verdict("__Verdict__: FAIL")

    def test_failure_verdict_and_inline_list_blockers_are_negative(self) -> None:
        assert _has_blocking_or_negative_verdict("Verdict: Failure")
        assert _has_blocking_or_negative_verdict("Blockers: - broken auth flow")

    def test_boolean_and_zero_values_remain_countable(self) -> None:
        assert not _has_blocking_or_negative_verdict("Blockers: false")
        assert not _has_blocking_or_negative_verdict("Blocking findings: zero")

    def test_word_boundary_does_not_flag_blockchain_verdict(self) -> None:
        assert not _has_blocking_or_negative_verdict("Verdict: blockchain summary attached")

    def test_inline_empty_markers_never_consume_the_next_section(self) -> None:
        # "Blockers: []" is an explicit empty list; the following unrelated
        # section must not be read as a blocker entry.
        assert not _has_blocking_or_negative_verdict("Blockers: []\nVerdict: PASS")
        assert not _has_blocking_or_negative_verdict("Blockers: -\nScope reviewed: full diff")
        assert not _has_blocking_or_negative_verdict("Blocking findings: [ ]\n\nVerdict: passed")

    def test_empty_blockers_followed_by_new_section_or_heading_is_countable(self) -> None:
        assert not _has_blocking_or_negative_verdict("Blockers:\nVerdict: PASS")
        assert not _has_blocking_or_negative_verdict("Blockers:\n### Validation notes")

    def test_lookahead_still_catches_list_items_with_colons(self) -> None:
        assert _has_blocking_or_negative_verdict("Blockers:\n- crash: stack overflow in parser")
        assert _has_blocking_or_negative_verdict("Blockers:\n1. regression: settle gate bypassed")

    def test_non_blocking_values_remain_countable(self) -> None:
        assert not _has_blocking_or_negative_verdict("Blockers: none")
        assert not _has_blocking_or_negative_verdict("Blocking findings: no blocking findings")
        assert not _has_blocking_or_negative_verdict("#### Blockers: N/A")
        assert not _has_blocking_or_negative_verdict("Verdict: **passed**, zero findings.")

    def test_high_priority_finding_markers_are_blocking(self) -> None:
        assert _has_blocking_or_negative_verdict("[P0] settlement gate bypass")
        assert _has_blocking_or_negative_verdict("- [P1] stale exact-head evidence")
        assert _has_blocking_or_negative_verdict("**[P1]** dependency drift is unresolved")
        assert _has_blocking_or_negative_verdict("1. [P1] stale exact-head evidence")
        assert _has_blocking_or_negative_verdict("1) [P0] settlement gate bypass")
        assert _has_blocking_or_negative_verdict("> [P1] stale exact-head evidence")
        assert _has_blocking_or_negative_verdict("## [P1] stale exact-head evidence")
        assert _has_blocking_or_negative_verdict("[P2] follow-up cleanup")


# --- parenthetical model-family disclosure ---------------------------------


class TestParentheticalModelFamily:
    """Agents commonly disclose `**Model family:** openai (gpt-5.5, harness)`.

    The trailing parenthetical detail used to contaminate the value so the
    canonical/alias lookup returned "" → ``unknown_model_family`` → the reviewer
    was NOT counted → the merge quorum stalled at 1/2. The normalizer now
    tolerates the parenthetical without weakening the gate.
    """

    def test_paren_openai_normalizes_to_openai(self) -> None:
        from aragora.cli.commands.review_queue import _normalize_model_family

        assert _normalize_model_family("openai (gpt-5.5, harness)") == "openai"
        assert _normalize_model_family("openai (gpt-5.5)") == "openai"
        assert _normalize_model_family("openai(gpt-5.5)") == "openai"

    def test_paren_claude_normalizes_to_claude(self) -> None:
        from aragora.cli.commands.review_queue import _normalize_model_family

        assert _normalize_model_family("claude (opus-4.8)") == "claude"

    def test_bare_tokens_still_work(self) -> None:
        from aragora.cli.commands.review_queue import _normalize_model_family

        assert _normalize_model_family("openai") == "openai"
        assert _normalize_model_family("claude") == "claude"

    def test_codex_and_gpt_aliases_resolve_to_openai(self) -> None:
        # A disclosed "Model family: codex" / "gpt" must count at the gate, since
        # the collector now emits canonical "openai" for those CLI/product names.
        from aragora.cli.commands.review_queue import _normalize_model_family

        assert _normalize_model_family("codex") == "openai"
        assert _normalize_model_family("gpt") == "openai"
        assert _normalize_model_family("chatgpt") == "openai"
        assert _normalize_model_family("codex (gpt-5.5 harness)") == "openai"

    def test_aliases_still_resolve_including_multiword(self) -> None:
        from aragora.cli.commands.review_queue import _normalize_model_family

        # Single-token alias.
        assert _normalize_model_family("anthropic") == "claude"
        # Multi-word alias must NOT be truncated to its first token.
        assert _normalize_model_family("nous hermes") == "hermes"
        assert _normalize_model_family("nous-hermes") == "hermes"
        # Multi-word alias with a trailing parenthetical still resolves.
        assert _normalize_model_family("nous hermes (8x7b)") == "hermes"

    def test_unknown_leading_token_still_unknown(self) -> None:
        from aragora.cli.commands.review_queue import _normalize_model_family

        # A genuinely-unknown leading token must still fail-closed even when a
        # parenthetical is present — the gate is not weakened.
        assert _normalize_model_family("mystery (x)") == ""
        assert _normalize_model_family("acme-frontier-9000") == ""
        assert _normalize_model_family("acme (gpt-5.5)") == ""

    def test_non_parenthetical_extra_text_stays_unknown(self) -> None:
        """Codex-review regression (PR #7743): the first-token fallback must be
        scoped to the parenthetical-stripped path ONLY. A malformed multi-word
        disclosure with NO parenthetical — e.g. ``openai claude`` or
        ``openai not-a-valid-family`` — must still resolve to "" and stay a
        ``unknown_model_family`` blocker, exactly as before this fix. Otherwise
        the gate would be weakened beyond the stated scope by silently accepting
        the leading token of any multi-word value."""
        from aragora.cli.commands.review_queue import _normalize_model_family

        assert _normalize_model_family("openai claude") == ""
        assert _normalize_model_family("claude unknown") == ""
        assert _normalize_model_family("openai not-a-valid-family") == ""
        # The fix's intended cases (parenthetical present) still resolve.
        assert _normalize_model_family("openai (gpt-5.5)") == "openai"

    def test_malformed_or_non_trailing_parenthetical_stays_unknown(self) -> None:
        """Second codex-review regression (PR #7743): only a *well-formed,
        trailing, closed* ``(...)`` suffix is tolerated. Text after the closing
        paren, an unclosed paren, or a multi-word head must all stay "" so they
        remain ``unknown_model_family`` blockers — the relaxation must not be a
        blanket "strip from the first ``(`` to end of string"."""
        from aragora.cli.commands.review_queue import _normalize_model_family

        # Text after the closing parenthetical -> not a trailing suffix.
        assert _normalize_model_family("openai (gpt-5.5) claude") == ""
        # Unclosed parenthetical.
        assert _normalize_model_family("openai (") == ""
        assert _normalize_model_family("openai (not actually closed") == ""
        # Multi-word head before a closed parenthetical.
        assert _normalize_model_family("openai gpt (x)") == ""
        # Well-formed trailing suffix (incl. multi-word alias head) still works.
        assert _normalize_model_family("openai (gpt-5.5)") == "openai"
        assert _normalize_model_family("nous hermes (8x7b)") == "hermes"

    def test_paren_disclosure_still_detects_heading_conflict(self) -> None:
        """A real heading/disclosed conflict must STILL fire even after the
        parenthetical is stripped — the disclosed family resolves correctly
        (``openai``) but it conflicts with the ``claude`` heading."""
        from aragora.cli.commands.review_queue import (
            _resolve_model_review_identity,
        )

        body = (
            "## Claude review\n\n"
            "**Model family:** openai (gpt-5.5, codex exec --sandbox read-only)\n"
            "**Model id:** gpt-5.5\n"
            "**Receipt artifact:** /tmp/r.md\n\n"
            "review."
        )
        ident = _resolve_model_review_identity(body)
        assert "heading_model_family_conflict" in ident.identity_problems

    def test_paren_disclosure_non_conflict_now_counts(self) -> None:
        """An ``openai (gpt-5.5)`` disclosure under a codex/openai heading must
        resolve to ``openai`` with NO ``unknown_model_family`` blocker, so the
        reviewer is counted (the bug that stalled the tail PRs)."""
        from aragora.cli.commands.review_queue import (
            _resolve_model_review_identity,
        )

        body = (
            "## Codex review\n\n"
            "**Reviewer harness:** codex\n"
            "**Model family:** openai (gpt-5.5)\n"
            "**Model id:** gpt-5.5\n"
            "**Receipt artifact:** /tmp/r.md\n\n"
            "review."
        )
        ident = _resolve_model_review_identity(body)
        assert ident.model_family == "openai"
        assert "unknown_model_family" not in ident.identity_problems
        assert "heading_model_family_conflict" not in ident.identity_problems

    def test_paren_disclosure_counts_in_full_quorum(self) -> None:
        """End-to-end: a dogfood comment disclosing ``openai (gpt-5.5)`` under a
        codex heading is counted in the model-review quorum (previously it was
        silently dropped, stalling quorum at 1/2)."""
        files = ["aragora/agents/router.py"]  # Tier 1
        pr = _make_pr(files=files)
        pr["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": (
                    "## Codex review\n\n"
                    "**Reviewer harness:** codex\n"
                    "**Model family:** openai (gpt-5.5, codex exec)\n"
                    "**Model id:** gpt-5.5\n"
                    "**Receipt artifact:** /tmp/r.md\n\n"
                    "codex review: 6/6 cases pass."
                ),
            },
        ]
        quorum = _build_model_review_quorum(
            pr=pr,
            files=files,
            protocol={"status": "metadata_heuristic"},
            machine_recommendation="approve_candidate",
            has_pending=False,
            has_failures=False,
        )
        # The reviewer is now counted (previously the parenthetical de-counted
        # it, leaving counted_reviewer_ids empty). The quorum credits the
        # resolved model family, so "openai" appears.
        assert quorum["counted_reviewer_ids"] == ["openai"]


# --- _parse_pr_number ------------------------------------------------------


class TestParsePRNumber:
    @pytest.mark.parametrize(
        ("ref", "expected"),
        [
            ("6280", 6280),
            ("#6280", 6280),
            ("https://github.com/synaptent/aragora/pull/6280", 6280),
            ("https://github.com/synaptent/aragora/pull/6280/", 6280),
        ],
    )
    def test_parses(self, ref: str, expected: int) -> None:
        assert _parse_pr_number(ref) == expected

    def test_rejects_invalid(self) -> None:
        with pytest.raises(_GhError):
            _parse_pr_number("not a number")


class TestValidationExtraction:
    def test_extracts_validation_bullets(self) -> None:
        body = """
## Summary
- one

## Validation
- `python3 -m pytest tests/cli/commands/test_review_queue.py -q`
- `bash scripts/automation_pr_preflight.sh origin/main HEAD`

## Notes
- later
"""
        assert _extract_validation_commands(body) == [
            "`python3 -m pytest tests/cli/commands/test_review_queue.py -q`",
            "`bash scripts/automation_pr_preflight.sh origin/main HEAD`",
        ]


class TestGhTimeouts:
    def test_gh_json_fails_closed_on_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
            captured["args"] = args
            captured["kwargs"] = kwargs
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout"))

        monkeypatch.setattr("aragora.cli.commands.review_queue_transport.subprocess.run", fake_run)

        with pytest.raises(_GhError, match=r"gh pr view 7811 timed out after \d+s"):
            _gh_json(["pr", "view", "7811"])

        assert captured["kwargs"]["timeout"] > 0

    def test_gh_json_fails_closed_on_startup_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise OSError("gh executable unavailable")

        monkeypatch.setattr("aragora.cli.commands.review_queue_transport.subprocess.run", fake_run)

        with pytest.raises(_GhError) as exc_info:
            _gh_json(["pr", "view", "7811"])

        assert "gh pr view 7811 failed to start: gh executable unavailable" in str(exc_info.value)
        assert _is_github_transport_error(exc_info.value) is True

    def test_gh_text_fails_closed_on_startup_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            raise OSError("permission denied")

        monkeypatch.setattr("aragora.cli.commands.review_queue_transport.subprocess.run", fake_run)

        with pytest.raises(_GhError) as exc_info:
            _gh_text(["repo", "view"])

        assert "gh repo view failed to start: permission denied" in str(exc_info.value)
        assert _is_github_transport_error(exc_info.value) is True


# --- _build_queue + _build_packet (with mocked gh) -------------------------


class TestBuildQueueAndPacket:
    def test_command_parser_accepts_build_repo_override(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        add_review_queue_parser(subparsers)

        args = parser.parse_args(
            ["review-queue", "build", "--repo", "synaptent/aragora", "--limit", "7"]
        )

        assert args.command == "review-queue"
        assert args.review_queue_command == "build"
        assert args.repo == "synaptent/aragora"
        assert args.limit == 7

    def test_merge_packet_explicit_pr_refs_do_not_hydrate_open_queue(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_build_queue(*_args: Any, **_kwargs: Any) -> list[QueueItem]:
            raise AssertionError("explicit --pr merge-packet must not call _build_queue")

        def fake_build_packet(ref: str, **_kwargs: Any) -> ReviewPacket:
            return ReviewPacket(
                pr_number=int(ref),
                title=f"PR {ref}",
                url=f"https://github.com/synaptent/aragora/pull/{ref}",
                head_sha="abc123",
                base_sha="def456",
                author="codex",
                is_draft=False,
                additions=1,
                deletions=1,
                changed_files=1,
                queue_bucket="ready_now",
                touched_subsystems=["scripts"],
                high_risk_paths_touched=[],
                validation=[],
                checks_summary="4/4 green",
                risk_flags=[],
                machine_recommendation="approve_candidate",
                machine_recommendation_reason="bounded test packet",
                packet_sha="sha256:test",
                generated_at="2026-05-30T00:00:00+00:00",
                merge_state_status="CLEAN",
                model_review_quorum={
                    "tier": 0,
                    "tier_name": "Tier 0",
                    "status": "satisfied",
                    "verdict": "admin_squash_allowed",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": False,
                    "unresolved_dissent": False,
                    "reviewer_signals": [],
                    "dogfood_evidence": [],
                    "counted_reviewer_ids": ["codex"],
                    "reasons": ["docs/tests/status-only change"],
                },
            )

        preflighted_refs: list[tuple[str, str | None]] = []

        def fake_explicit_merged_entry(
            ref: str, repo_override: str | None
        ) -> dict[str, Any] | None:
            preflighted_refs.append((ref, repo_override))
            return None

        monkeypatch.setattr("aragora.cli.commands.review_queue._build_queue", fail_build_queue)
        monkeypatch.setattr("aragora.cli.commands.review_queue._build_packet", fake_build_packet)
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._explicit_merged_pr_merge_packet_entry",
            fake_explicit_merged_entry,
        )

        packet = _build_merge_authorization_packet(
            pr_refs=["7528"],
            limit=30,
            repo_override=None,
        )

        assert packet["queue_pressure"] == {
            "current_open_prs": 1,
            "cap": MODEL_REVIEW_QUEUE_CAP,
            "active": False,
            "scope": "explicit_pr_refs",
        }
        assert preflighted_refs == [("7528", None)]
        assert packet["admin_squash_order"] == [7528]

    @pytest.mark.parametrize(
        ("merge_state_status", "labels", "expected_blocker"),
        [
            (
                "UNSTABLE",
                [],
                "mergeStateStatus=UNSTABLE; admin squash requires CLEAN or BLOCKED",
            ),
            (
                "CLEAN",
                ["operator-review-required"],
                "operator-review-required label present",
            ),
            (
                "",
                [],
                "mergeStateStatus unavailable; admin squash requires CLEAN or BLOCKED",
            ),
        ],
    )
    def test_merge_packet_live_state_blocks_admin_squash_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
        merge_state_status: str,
        labels: list[str],
        expected_blocker: str,
    ) -> None:
        def fake_build_packet(ref: str, **_kwargs: Any) -> ReviewPacket:
            return ReviewPacket(
                pr_number=int(ref),
                title=f"PR {ref}",
                url=f"https://github.com/synaptent/aragora/pull/{ref}",
                head_sha="abc123",
                base_sha="def456",
                author="codex",
                is_draft=False,
                additions=1,
                deletions=1,
                changed_files=1,
                queue_bucket="ready_now",
                touched_subsystems=["scripts"],
                high_risk_paths_touched=[],
                validation=[],
                checks_summary="4/4 green",
                risk_flags=[],
                machine_recommendation="approve_candidate",
                machine_recommendation_reason="bounded test packet",
                packet_sha="sha256:test",
                generated_at="2026-05-30T00:00:00+00:00",
                labels=labels,
                merge_state_status=merge_state_status,
                model_review_quorum={
                    "tier": 0,
                    "tier_name": "Tier 0",
                    "status": "satisfied",
                    "verdict": "admin_squash_allowed",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": False,
                    "unresolved_dissent": False,
                    "reviewer_signals": [],
                    "dogfood_evidence": [],
                    "counted_reviewer_ids": ["codex"],
                    "reasons": ["docs/tests/status-only change"],
                },
            )

        monkeypatch.setattr("aragora.cli.commands.review_queue._build_packet", fake_build_packet)
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._explicit_merged_pr_merge_packet_entry",
            lambda ref, repo_override: None,
        )

        packet = _build_merge_authorization_packet(
            pr_refs=["8958"],
            limit=30,
            repo_override=None,
        )

        entry = packet["entries"][0]
        assert entry["model_quorum_admin_squash_allowed"] is True
        assert entry["admin_squash_allowed"] is False
        assert expected_blocker in entry["admin_squash_gate_blockers"]
        assert packet["admin_squash_order"] == []
        # The live-gate flip must be visible in the human-readable fields, not
        # just via omission from admin_squash_order (#8965 openai [P3]).
        assert entry["status"] == "blocked_by_live_gate"
        assert entry["verdict"] == "admin_squash_blocked_by_live_gate"
        assert 8958 in packet["not_ready"]

    def test_merge_packet_text_renderer_prints_live_gate_blockers(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        def fake_build_packet(ref: str, **_kwargs: Any) -> ReviewPacket:
            return ReviewPacket(
                pr_number=int(ref),
                title=f"PR {ref}",
                url=f"https://github.com/synaptent/aragora/pull/{ref}",
                head_sha="abc123",
                base_sha="def456",
                author="codex",
                is_draft=False,
                additions=1,
                deletions=1,
                changed_files=1,
                queue_bucket="ready_now",
                touched_subsystems=["scripts"],
                high_risk_paths_touched=[],
                validation=[],
                checks_summary="4/4 green",
                risk_flags=[],
                machine_recommendation="approve_candidate",
                machine_recommendation_reason="bounded test packet",
                packet_sha="sha256:test",
                generated_at="2026-05-30T00:00:00+00:00",
                labels=["operator-review-required"],
                merge_state_status="CLEAN",
                model_review_quorum={
                    "tier": 0,
                    "tier_name": "Tier 0",
                    "status": "satisfied",
                    "verdict": "admin_squash_allowed",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": False,
                    "unresolved_dissent": False,
                    "reviewer_signals": [],
                    "dogfood_evidence": [],
                    "counted_reviewer_ids": ["codex"],
                    "reasons": ["docs/tests/status-only change"],
                },
            )

        monkeypatch.setattr("aragora.cli.commands.review_queue._build_packet", fake_build_packet)
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._explicit_merged_pr_merge_packet_entry",
            lambda ref, repo_override: None,
        )

        packet = _build_merge_authorization_packet(
            pr_refs=["8958"],
            limit=30,
            repo_override=None,
        )
        _render_merge_authorization_packet(packet)

        out = capsys.readouterr().out
        assert "blocked_by_live_gate | admin_squash_blocked_by_live_gate" in out
        assert "admin squash live-gate blockers:" in out
        assert "operator-review-required label present" in out
        assert "satisfied | admin_squash_allowed" not in out
        assert "admin squash order: (none)" in out
        assert "not ready: #8958" in out

    def test_merge_packet_clean_live_state_allows_admin_squash_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_build_packet(ref: str, **_kwargs: Any) -> ReviewPacket:
            return ReviewPacket(
                pr_number=int(ref),
                title=f"PR {ref}",
                url=f"https://github.com/synaptent/aragora/pull/{ref}",
                head_sha="abc123",
                base_sha="def456",
                author="codex",
                is_draft=False,
                additions=1,
                deletions=1,
                changed_files=1,
                queue_bucket="ready_now",
                touched_subsystems=["scripts"],
                high_risk_paths_touched=[],
                validation=[],
                checks_summary="4/4 green",
                risk_flags=[],
                machine_recommendation="approve_candidate",
                machine_recommendation_reason="bounded test packet",
                packet_sha="sha256:test",
                generated_at="2026-05-30T00:00:00+00:00",
                labels=[],
                merge_state_status="CLEAN",
                model_review_quorum={
                    "tier": 0,
                    "tier_name": "Tier 0",
                    "status": "satisfied",
                    "verdict": "admin_squash_allowed",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": False,
                    "unresolved_dissent": False,
                    "reviewer_signals": [],
                    "dogfood_evidence": [],
                    "counted_reviewer_ids": ["codex"],
                    "reasons": ["docs/tests/status-only change"],
                },
            )

        monkeypatch.setattr("aragora.cli.commands.review_queue._build_packet", fake_build_packet)
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._explicit_merged_pr_merge_packet_entry",
            lambda ref, repo_override: None,
        )

        packet = _build_merge_authorization_packet(
            pr_refs=["8958"],
            limit=30,
            repo_override=None,
        )

        entry = packet["entries"][0]
        assert entry["model_quorum_admin_squash_allowed"] is True
        assert entry["admin_squash_allowed"] is True
        assert entry["admin_squash_gate_blockers"] == []
        assert packet["admin_squash_order"] == [8958]

    def test_merge_packet_blocked_live_state_allows_satisfied_admin_squash_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fake_build_packet(ref: str, **_kwargs: Any) -> ReviewPacket:
            return ReviewPacket(
                pr_number=int(ref),
                title=f"PR {ref}",
                url=f"https://github.com/synaptent/aragora/pull/{ref}",
                head_sha="abc123",
                base_sha="def456",
                author="codex",
                is_draft=False,
                additions=1,
                deletions=1,
                changed_files=1,
                queue_bucket="ready_now",
                touched_subsystems=["scripts"],
                high_risk_paths_touched=[],
                validation=[],
                checks_summary="4/4 green",
                risk_flags=[],
                machine_recommendation="approve_candidate",
                machine_recommendation_reason="bounded test packet",
                packet_sha="sha256:test",
                generated_at="2026-05-30T00:00:00+00:00",
                labels=[],
                merge_state_status="BLOCKED",
                model_review_quorum={
                    "tier": 0,
                    "tier_name": "Tier 0",
                    "status": "satisfied",
                    "verdict": "admin_squash_allowed",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": False,
                    "unresolved_dissent": False,
                    "reviewer_signals": [],
                    "dogfood_evidence": [],
                    "counted_reviewer_ids": ["codex"],
                    "reasons": ["docs/tests/status-only change"],
                },
            )

        monkeypatch.setattr("aragora.cli.commands.review_queue._build_packet", fake_build_packet)
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._explicit_merged_pr_merge_packet_entry",
            lambda ref, repo_override: None,
        )

        packet = _build_merge_authorization_packet(
            pr_refs=["8958"],
            limit=30,
            repo_override=None,
        )

        entry = packet["entries"][0]
        assert entry["model_quorum_admin_squash_allowed"] is True
        assert entry["admin_squash_allowed"] is True
        assert entry["admin_squash_gate_blockers"] == []
        assert packet["admin_squash_order"] == [8958]

    def test_build_queue_classifies_and_sorts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        prs = [
            _make_pr(number=10, is_draft=True),  # parked
            _make_pr(number=20),  # ready_now
            _make_pr(
                number=30,
                checks=[{"status": "COMPLETED", "conclusion": "FAILURE"}],
            ),  # repairable
            _make_pr(
                number=40,
                checks=[{"status": "IN_PROGRESS", "conclusion": ""}],
            ),  # needs_attention
        ]
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: prs,
        )
        items = _build_queue(limit=100)
        assert [it.number for it in items] == [20, 40, 30, 10]
        assert [it.lane for it in items] == [
            "ready_now",
            "needs_attention",
            "repairable",
            "parked",
        ]

    def test_build_queue_passes_repo_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen_args: list[list[str]] = []

        def fake_gh_json(args: list[str]) -> list[dict[str, Any]]:
            seen_args.append(args)
            return []

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        assert _build_queue(limit=7, repo_override="synaptent/aragora") == []
        assert seen_args
        assert seen_args[0][-2:] == ["--repo", "synaptent/aragora"]

    def test_merge_packet_open_queue_uses_repo_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen_repo_overrides: list[str | None] = []

        def fake_build_queue(*, limit: int, repo_override: str | None = None) -> list[QueueItem]:
            seen_repo_overrides.append(repo_override)
            return []

        monkeypatch.setattr("aragora.cli.commands.review_queue._build_queue", fake_build_queue)

        packet = _build_merge_authorization_packet(
            pr_refs=[],
            limit=7,
            repo_override="synaptent/aragora",
        )

        assert seen_repo_overrides == ["synaptent/aragora"]
        assert packet["queue_pressure"]["current_open_prs"] == 0

    def test_build_packet_sets_recommendation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pr_payload = _make_pr(
            number=6280,
            files=["aragora/cli/commands/review_pr.py", "tests/cli/commands/test_review_pr.py"],
            body=(
                "## Validation\n"
                "- `python3 -m pytest tests/cli/commands/test_review_pr.py -q`\n"
                "- `bash scripts/automation_pr_preflight.sh origin/main HEAD`\n"
            ),
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("6280", repo_override=None)
        assert packet.pr_number == 6280
        assert packet.advisory_only is True
        assert packet.settlement_note == ADVISORY_NOTE
        assert packet.machine_recommendation == "approve_candidate"
        assert packet.queue_bucket == "ready_now"
        assert packet.base_sha == "basesha0001"
        assert packet.packet_sha.startswith("sha256:")
        assert "aragora/cli" in packet.touched_subsystems
        assert "tests/cli" in packet.touched_subsystems
        assert packet.high_risk_paths_touched == []
        assert packet.protocol["binding"]["repo"] == "synaptent/aragora"
        assert packet.protocol["binding"]["base_sha"] == "basesha0001"
        assert packet.protocol["availability_summary"]["total_slots"] == 5
        assert packet.protocol["recommendation_class"] == "approve_candidate"
        assert packet.model_review_quorum["tier"] == 2
        assert packet.model_review_quorum["status"] == "needs_model_review_quorum"
        assert packet.validation == [
            "`python3 -m pytest tests/cli/commands/test_review_pr.py -q`",
            "`bash scripts/automation_pr_preflight.sh origin/main HEAD`",
        ]

    def test_build_packet_accepts_state_based_green_rollups(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=6280,
            checks=[
                {"context": "lint", "state": "SUCCESS"},
                {"context": "ci/unit", "state": "SUCCESS"},
            ],
            files=["aragora/cli/commands/review_pr.py"],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("6280", repo_override=None)
        assert packet.machine_recommendation == "approve_candidate"
        assert packet.checks_summary == "2/2 green"

    def test_merged_pr_fails_closed_before_admin_authorization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7470,
            files=["docs/status/focus.md"],
            state="MERGED",
            merged_at="2026-05-27T00:19:36Z",
        )
        pr_payload["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("7470", repo_override=None)
        quorum = packet.model_review_quorum

        assert packet.machine_recommendation == "needs_human_attention"
        assert "PR is MERGED; settlement applies only to open PRs" in packet.risk_flags
        assert quorum["admin_squash_allowed"] is False
        assert quorum["status"] == "repair_or_wait"
        assert "PR is MERGED; settlement applies only to open PRs" in quorum["reasons"]

    def test_merged_pr_short_circuits_heavy_packet_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7470,
            files=["docs/status/focus.md"],
            state="MERGED",
            merged_at="2026-05-27T00:19:36Z",
        )
        requested_fields: list[str] = []

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            fields = args[args.index("--json") + 1]
            requested_fields.append(fields)
            assert "statusCheckRollup" not in fields
            assert "comments" not in fields
            assert "reviews" not in fields
            assert "commits" not in fields
            return pr_payload

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_merge_authorization_packet(
            pr_refs=["7470"],
            limit=10,
            repo_override=None,
        )

        assert len(requested_fields) == 1
        assert packet["entries"][0]["status"] == "already_merged"
        assert packet["entries"][0]["verdict"] == "already_merged_noop"
        assert packet["entries"][0]["checks_summary"] == (
            "failing PR state (already merged; checks obsolete for merge-packet)"
        )
        assert packet["entries"][0]["admin_squash_allowed"] is False
        assert packet["admin_squash_order"] == []
        assert packet["not_ready"] == []

    def test_closed_pr_fails_closed_before_admin_authorization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7471, files=["docs/status/closed.md"], state="CLOSED")
        pr_payload["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("7471", repo_override=None)

        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"
        assert (
            "PR is CLOSED; settlement applies only to open PRs"
            in packet.model_review_quorum["reasons"]
        )

    def test_open_authorized_pr_still_allows_admin_squash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7472, files=["docs/status/open.md"])
        pr_payload["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("7472", repo_override=None)

        assert packet.machine_recommendation == "approve_candidate"
        assert packet.model_review_quorum["admin_squash_allowed"] is True
        assert packet.model_review_quorum["status"] == "satisfied"

    def test_open_pr_with_missing_check_rollup_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload["statusCheckRollup"] = None
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("7465", repo_override=None)

        assert packet.checks_summary == "no checks reported"
        assert packet.machine_recommendation == "needs_human_attention"
        assert "check rollup unavailable" in packet.risk_flags
        assert packet.check_surfaces["pr_rollup"] == {
            "available": False,
            "count": None,
            "summary": "no checks reported",
        }
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"
        assert (
            "checks are unavailable; wait for GitHub check rollup before settlement"
            in packet.model_review_quorum["reasons"]
        )

    def test_missing_check_rollup_reports_direct_commit_check_surface(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload["statusCheckRollup"] = []
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:1] == ["api"] and "required_status_checks" in args[1]:
                return {"contexts": ["lint", "typecheck"]}
            if args[:1] == ["api"] and "check-runs" in args[1]:
                return {
                    "check_runs": [
                        {"name": "lint", "status": "completed", "conclusion": "success"},
                        {"name": "typecheck", "status": "completed", "conclusion": "success"},
                        {
                            "name": "Python SDK Tests (3.11)",
                            "status": "completed",
                            "conclusion": "failure",
                        },
                    ]
                }
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert packet.check_surfaces["pr_rollup"] == {
            "available": False,
            "count": 0,
            "summary": "no checks reported",
        }
        assert packet.checks_summary == "2/2 required green (direct check-runs fallback)"
        assert "check rollup unavailable" not in packet.risk_flags
        assert direct["total"] == 3
        assert direct["branch_protection_strict"] is False
        assert direct["successful_required_contexts"] == ["lint", "typecheck"]
        assert direct["missing_required_contexts"] == []
        assert direct["non_success_required_contexts"] == []
        assert direct["required_contexts_satisfied"] is True
        assert direct["non_green_sample"] == ["Python SDK Tests (3.11)"]
        assert (
            "non-required direct check-runs are non-green; "
            "fallback gates only branch-protection required contexts"
        ) in packet.risk_flags
        assert packet.check_surfaces["effective_gate"] == {
            "source": "direct_commit_check_runs",
            "summary": "2/2 required green (direct check-runs fallback)",
        }
        assert (
            "every branch-protection required context successful"
            in packet.check_surfaces["diagnosis"]
        )
        assert packet.machine_recommendation == "approve_candidate"
        assert (
            "non-required direct check-runs are non-green" in packet.machine_recommendation_reason
        )
        assert packet.model_review_quorum["admin_squash_allowed"] is True
        assert packet.model_review_quorum["status"] == "satisfied"
        assert not any(
            "checks are unavailable" in reason for reason in packet.model_review_quorum["reasons"]
        )
        rendered = io.StringIO()
        with redirect_stdout(rendered):
            _render_packet(packet)
        rendered_packet = rendered.getvalue()
        assert "check surfaces:" in rendered_packet
        assert "direct_commit_check_runs=3" in rendered_packet
        assert "diagnosis:" in rendered_packet
        assert "remediation:" in rendered_packet

    def test_build_packet_uses_rest_fallback_when_pr_view_transport_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        head = "abc1234567890abcdef"
        rest_pr = {
            "number": 7466,
            "title": "docs status fallback",
            "html_url": "https://github.com/synaptent/aragora/pull/7466",
            "state": "open",
            "merged_at": None,
            "merge_commit_sha": "",
            "draft": False,
            "mergeable": True,
            "mergeable_state": "clean",
            "user": {"login": "an0mium"},
            "head": {"ref": "codex/rest-fallback-test", "sha": head},
            "base": {"ref": "main", "sha": "basesha0001"},
            "labels": [],
            "additions": 1,
            "deletions": 0,
            "changed_files": 1,
            "body": "",
        }
        comment_body = (
            "## Grok independent model review\n\n"
            f"Head: abc1234 ({head}).\n"
            "PR: #7466.\n"
            "Model family: grok\n\n"
            "Verdict: PASS\n"
            "- adversarial dogfood recheck found no blocker.\n"
            "dogfood: yes\n"
        )

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                raise _GhError("GraphQL: API rate limit already exceeded")
            if args[:1] != ["api"]:
                raise AssertionError(f"unexpected gh call: {args}")
            endpoint = args[1]
            if endpoint == "repos/synaptent/aragora/pulls/7466":
                return rest_pr
            if endpoint == "repos/synaptent/aragora/pulls/7466/files?per_page=100":
                return [{"filename": "docs/status/fallback.md"}]
            if endpoint == "repos/synaptent/aragora/issues/7466/comments?per_page=100":
                return [
                    {
                        "user": {"login": "an0mium"},
                        "body": comment_body,
                        "created_at": "2026-06-12T00:01:00Z",
                    }
                ]
            if endpoint == "repos/synaptent/aragora/pulls/7466/reviews?per_page=100":
                return []
            if endpoint == "repos/synaptent/aragora/pulls/7466/commits?per_page=100":
                return [
                    {
                        "sha": head,
                        "commit": {"author": {"date": "2026-06-12T00:00:00Z"}},
                    }
                ]
            if endpoint == f"repos/synaptent/aragora/commits/{head}/status":
                return {
                    "statuses": [
                        {
                            "context": "legacy/status",
                            "state": "success",
                            "created_at": "2026-06-12T00:02:00Z",
                            "updated_at": "2026-06-12T00:02:00Z",
                        }
                    ]
                }
            if (
                endpoint
                == "repos/synaptent/aragora/branches/main/protection/required_status_checks"
            ):
                return {"contexts": ["legacy/status"], "checks": [], "strict": False}
            if endpoint == f"repos/synaptent/aragora/commits/{head}/check-runs?per_page=100":
                return {"check_runs": []}
            raise AssertionError(f"unexpected gh api endpoint: {endpoint}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7466", repo_override="synaptent/aragora")
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert packet.head_sha == head
        assert packet.touched_subsystems == ["docs"]
        assert packet.check_surfaces["metadata_transport_fallback"]["enabled"] is True
        assert packet.check_surfaces["metadata_transport_fallback"]["repo"] == "synaptent/aragora"
        assert packet.checks_summary == "1/1 required green (direct check-runs fallback)"
        assert direct["total"] == 0
        assert direct["statuses_total"] == 1
        assert direct["successful_required_contexts"] == ["legacy/status"]
        assert direct["required_contexts_satisfied"] is True
        assert packet.model_review_quorum["counted_model_families"] == ["grok"]
        assert packet.model_review_quorum["admin_squash_allowed"] is True

    def test_rest_fallback_paginates_rest_surfaces(self) -> None:
        head = "f" * 40
        calls: list[str] = []

        def page_payload(prefix: str, page: int) -> list[dict[str, Any]]:
            if prefix == "files":
                return [{"filename": f"docs/page-{page}-{index}.md"} for index in range(100)]
            if prefix == "comments":
                return [
                    {"user": {"login": "an0mium"}, "body": f"comment {page}-{index}"}
                    for index in range(100)
                ]
            if prefix == "reviews":
                return [{"user": {"login": "reviewer"}, "state": "APPROVED"}]
            if prefix == "commits":
                return [
                    {
                        "sha": f"{page:02d}{index:038d}",
                        "commit": {"author": {"date": "2026-06-12T00:00:00Z"}},
                    }
                    for index in range(100)
                ]
            if prefix == "statuses":
                return [
                    {"context": f"legacy/{page}-{index}", "state": "success"}
                    for index in range(100)
                ]
            raise AssertionError(prefix)

        def fake_gh_json(args: list[str]) -> Any:
            assert args[:1] == ["api"]
            endpoint = args[1]
            calls.append(endpoint)
            if endpoint == "repos/synaptent/aragora/pulls/7466":
                return {
                    "number": 7466,
                    "title": "rest fallback",
                    "html_url": "https://github.com/synaptent/aragora/pull/7466",
                    "state": "open",
                    "draft": False,
                    "mergeable": True,
                    "mergeable_state": "clean",
                    "user": {"login": "an0mium"},
                    "head": {"ref": "codex/rest-fallback-test", "sha": head},
                    "base": {"ref": "main", "sha": "basesha0001"},
                    "labels": [],
                    "additions": 1,
                    "deletions": 0,
                    "changed_files": 101,
                    "body": "",
                }
            if endpoint.endswith("/files?per_page=100"):
                return page_payload("files", 1)
            if endpoint.endswith("/files?per_page=100&page=2"):
                return [{"filename": "docs/page-2-final.md"}]
            if endpoint.endswith("/comments?per_page=100"):
                return page_payload("comments", 1)
            if endpoint.endswith("/comments?per_page=100&page=2"):
                return [{"user": {"login": "an0mium"}, "body": "comment page 2"}]
            if endpoint.endswith("/reviews?per_page=100"):
                return page_payload("reviews", 1)
            if endpoint.endswith("/commits?per_page=100"):
                return page_payload("commits", 1)
            if endpoint.endswith("/commits?per_page=100&page=2"):
                return [{"sha": head, "commit": {"author": {"date": "2026-06-12T00:00:00Z"}}}]
            if endpoint.endswith(f"/commits/{head}/statuses?per_page=100"):
                return page_payload("statuses", 1)
            if endpoint.endswith(f"/commits/{head}/statuses?per_page=100&page=2"):
                return [{"context": "legacy/final", "state": "success"}]
            if endpoint.endswith(f"/commits/{head}/check-runs?per_page=100"):
                return {
                    "total_count": 101,
                    "check_runs": [
                        {"name": f"check-{index}", "status": "completed", "conclusion": "success"}
                        for index in range(100)
                    ],
                }
            if endpoint.endswith(f"/commits/{head}/check-runs?per_page=100&page=2"):
                return {
                    "total_count": 101,
                    "check_runs": [
                        {"name": "check-final", "status": "completed", "conclusion": "success"}
                    ],
                }
            raise AssertionError(f"unexpected endpoint: {endpoint}")

        pr = rest_fallback._hydrate_pr_with_rest_fallback(
            number=7466,
            repo_slug="synaptent/aragora",
            source_error="GraphQL rate limit",
            gh_json=fake_gh_json,
        )
        check_runs = rest_fallback._fetch_direct_commit_check_runs(
            "synaptent/aragora", head, gh_json=fake_gh_json
        )

        assert len(pr["files"]) == 101
        assert len(pr["comments"]) == 101
        assert len(pr["reviews"]) == 1
        assert len(pr["commits"]) == 101
        assert len(pr["commitStatuses"]) == 101
        assert len(check_runs) == 101
        assert "repos/synaptent/aragora/pulls/7466/files?per_page=100&page=2" in calls
        assert "repos/synaptent/aragora/issues/7466/comments?per_page=100&page=2" in calls
        assert f"repos/synaptent/aragora/commits/{head}/check-runs?per_page=100&page=2" in calls

    def test_non_required_rollup_failures_use_required_pr_checks_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7465,
            files=["docs/status/open.md"],
            checks=[
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "typecheck", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {
                    "name": "Mac TypeScript SDK Shadow",
                    "status": "QUEUED",
                    "conclusion": "",
                },
                {"name": "Docs Consistency", "status": "COMPLETED", "conclusion": "FAILURE"},
            ],
        )
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:2] == ["pr", "checks"]:
                return [
                    {
                        "name": "lint",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "Lint",
                    },
                    {
                        "name": "typecheck",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "Lint",
                    },
                ]
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)

        assert packet.checks_summary == "2/2 required green (required PR checks)"
        assert packet.check_surfaces["effective_gate"] == {
            "source": "required_pr_checks",
            "summary": "2/2 required green (required PR checks)",
        }
        assert (
            "non-required PR checks are non-green; "
            "effective gate uses branch-protection required checks"
        ) in packet.risk_flags
        assert "non-required PR checks are non-green" in packet.machine_recommendation_reason
        assert packet.machine_recommendation == "approve_candidate"
        assert packet.model_review_quorum["admin_squash_allowed"] is True
        assert packet.model_review_quorum["status"] == "satisfied"
        assert packet.check_surfaces["required_pr_checks"]["gate_selected"] is True

    def test_required_pr_checks_gate_ignores_stale_self_row_inside_quorum_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7465,
            files=["docs/status/open.md"],
            checks=[
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "typecheck", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {
                    "name": "Mac TypeScript SDK Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "QUEUED",
                    "conclusion": "",
                    "runner_id": 0,
                    "runner_name": "",
                    "queuedDurationSeconds": 7200,
                },
                {
                    "name": "Hetzner Offline Golden Path Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "QUEUED",
                    "conclusion": "",
                    "runner_id": 0,
                    "runner_name": "",
                    "queuedDurationSeconds": 7200,
                },
                {
                    "name": "aragora-merge-quorum",
                    "workflowName": "Aragora Merge Quorum",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                },
            ],
        )
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:2] == ["pr", "checks"]:
                return [
                    {
                        "name": "aragora-merge-quorum",
                        "state": "FAILURE",
                        "bucket": "fail",
                        "workflow": "Aragora Merge Quorum",
                        "link": "https://github.com/synaptent/aragora/actions/runs/old/job/1",
                    },
                    {
                        "name": "lint",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "Lint",
                    },
                    {
                        "name": "typecheck",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "Lint",
                    },
                ]
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        required = packet.check_surfaces["required_pr_checks"]
        rollup = packet.check_surfaces["pr_rollup"]

        assert packet.checks_summary == "2/2 required green (required PR checks)"
        assert required["effective_total"] == 2
        assert required["failing_or_cancelled"] == []
        assert required["pending"] == []
        assert packet.machine_recommendation == "approve_candidate"
        assert packet.model_review_quorum["admin_squash_allowed"] is True
        assert packet.model_review_quorum["status"] == "satisfied"
        assert rollup["optional_runner_capacity_noise_count"] == 2
        assert rollup["optional_runner_capacity_noise_sample"] == [
            "Self-Hosted Shadow CI / Mac TypeScript SDK Shadow",
            "Self-Hosted Shadow CI / Hetzner Offline Golden Path Shadow",
        ]
        assert rollup["long_queued_self_hosted_shadow_without_runner_metadata_count"] == 0

    def test_ignore_own_quorum_flag_drops_required_quorum_row_out_of_ci(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Out-of-CI: the self-check helper does NOT ignore the merge-quorum row,
        # so by default a concluded merge-quorum FAILURE blocks. The B2 flag is
        # the only thing that excludes it from gating + diagnostics. An unrelated
        # typecheck failure keeps the rollup non-green so the required surface is
        # still fetched even when the flag drops the merge-quorum row.
        for var in ("GITHUB_WORKFLOW", "GITHUB_JOB", "GITHUB_RUN_ID", "GITHUB_REPOSITORY"):
            monkeypatch.delenv(var, raising=False)
        pr_payload = _make_pr(
            number=7465,
            files=["docs/status/open.md"],
            checks=[
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "typecheck", "status": "COMPLETED", "conclusion": "FAILURE"},
                {
                    "name": "aragora-merge-quorum",
                    "workflowName": "Aragora Merge Quorum",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                },
            ],
        )

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:2] == ["pr", "checks"]:
                return [
                    {
                        "name": "aragora-merge-quorum",
                        "state": "FAILURE",
                        "bucket": "fail",
                        "workflow": "Aragora Merge Quorum",
                        "link": "https://github.com/synaptent/aragora/actions/runs/old/job/1",
                    },
                    {"name": "lint", "state": "SUCCESS", "bucket": "pass", "workflow": "Lint"},
                    {"name": "typecheck", "state": "FAILURE", "bucket": "fail", "workflow": "Lint"},
                ]
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        default_required = _build_packet("7465", repo_override=None).check_surfaces[
            "required_pr_checks"
        ]
        assert default_required["effective_total"] == 3
        assert "aragora-merge-quorum" in default_required["failing_or_cancelled"]
        assert default_required["ignored_by_ignore_own_quorum_flag_count"] == 0

        flagged_required = _build_packet(
            "7465", repo_override=None, ignore_own_quorum_check=True
        ).check_surfaces["required_pr_checks"]
        assert flagged_required["effective_total"] == 2
        # The real typecheck failure is preserved; only the merge-quorum row is dropped.
        assert flagged_required["failing_or_cancelled"] == ["typecheck"]
        assert flagged_required["ignored_by_ignore_own_quorum_flag_count"] == 1
        # Diagnostic accounting stays self-consistent: total - effective_total equals
        # the self-check exclusions plus the flag exclusions.
        assert flagged_required["total"] - flagged_required["effective_total"] == (
            flagged_required["ignored_current_merge_quorum_self_check_count"]
            + flagged_required["ignored_by_ignore_own_quorum_flag_count"]
        )

    def test_required_gate_classifies_real_rollup_shaped_long_queued_shadows(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7465,
            files=["docs/status/open.md"],
            checks=[
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "typecheck", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {
                    "__typename": "CheckRun",
                    "name": "Mac TypeScript SDK Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "QUEUED",
                    "conclusion": "",
                    "createdAt": "2026-05-31T15:51:16Z",
                    "startedAt": "",
                    "detailsUrl": ("https://github.com/synaptent/aragora/actions/runs/1/job/10"),
                },
                {
                    "__typename": "CheckRun",
                    "name": "Hetzner Offline Golden Path Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "QUEUED",
                    "conclusion": "",
                    "createdAt": "2026-05-31T15:51:16Z",
                    "startedAt": "",
                    "detailsUrl": ("https://github.com/synaptent/aragora/actions/runs/1/job/11"),
                },
            ],
        )
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:2] == ["pr", "checks"]:
                return [
                    {
                        "name": "lint",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "Lint",
                    },
                    {
                        "name": "typecheck",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "Lint",
                    },
                ]
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        rollup = packet.check_surfaces["pr_rollup"]

        assert packet.checks_summary == "2/2 required green (required PR checks)"
        assert rollup["non_required_non_green_count"] == 2
        assert rollup["optional_runner_capacity_noise_count"] == 0
        assert rollup["optional_runner_capacity_noise_sample"] == []
        assert rollup["long_queued_self_hosted_shadow_without_runner_metadata_count"] == 2
        assert rollup["long_queued_self_hosted_shadow_without_runner_metadata_sample"] == [
            "Self-Hosted Shadow CI / Mac TypeScript SDK Shadow",
            "Self-Hosted Shadow CI / Hetzner Offline Golden Path Shadow",
        ]
        assert packet.model_review_quorum["admin_squash_allowed"] is True

        rendered = io.StringIO()
        with redirect_stdout(rendered):
            _render_packet(packet)
        rendered_packet = rendered.getvalue()
        assert "optional_runner_capacity_noise=" not in rendered_packet
        assert (
            "long_queued_self_hosted_shadow_without_runner_metadata=Self-Hosted Shadow CI"
            in rendered_packet
        )

    def test_required_pr_checks_gate_preserves_self_row_outside_quorum_run(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7465,
            files=["docs/status/open.md"],
            checks=[
                {
                    "name": "Mac TypeScript SDK Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "QUEUED",
                    "conclusion": "",
                    "runner_id": 0,
                    "runner_name": "",
                    "queuedDurationSeconds": 7200,
                },
                {
                    "name": "Hetzner Offline Golden Path Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "COMPLETED",
                    "conclusion": "CANCELLED",
                },
                {
                    "name": "Smoke Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "COMPLETED",
                    "conclusion": "SKIPPED",
                },
                {
                    "name": "aragora-merge-quorum",
                    "workflowName": "Aragora Merge Quorum",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                },
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
            ],
        )
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:2] == ["pr", "checks"]:
                return [
                    {
                        "name": "aragora-merge-quorum",
                        "state": "FAILURE",
                        "bucket": "fail",
                        "workflow": "Aragora Merge Quorum",
                    },
                    {
                        "name": "lint",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "Lint",
                    },
                ]
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        required = packet.check_surfaces["required_pr_checks"]
        rollup = packet.check_surfaces["pr_rollup"]

        assert packet.check_surfaces["effective_gate"] == {
            "source": "required_pr_checks",
            "summary": "1 failing / 2 required (required PR checks; only merge-quorum failing)",
        }
        assert required["gate_selected"] is True
        assert required["quorum_only_failure"] is True
        assert rollup["optional_runner_capacity_noise_count"] == 1
        assert rollup["long_queued_self_hosted_shadow_without_runner_metadata_count"] == 0
        assert packet.machine_recommendation == "repair_first"
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"
        assert (
            "checks are failing; repair before settlement" in packet.model_review_quorum["reasons"]
        )
        assert not any(
            "checks are pending" in reason for reason in packet.model_review_quorum["reasons"]
        )

    def test_required_pr_checks_gate_routes_quorum_only_failure_to_model_quorum(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=8374,
            files=["scripts/audit_test_skips.py", "tests/scripts/test_audit_test_skips.py"],
            checks=[
                {
                    "name": "aragora-merge-quorum",
                    "workflowName": "Aragora Merge Quorum",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                },
                {"name": "Version Alignment", "status": "COMPLETED", "conclusion": "FAILURE"},
                {
                    "name": "Status Doc Reconciliation",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                },
                {"name": "Generate & Validate", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {
                    "name": "TypeScript SDK Type Check",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                },
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "sdk-parity", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "typecheck", "status": "COMPLETED", "conclusion": "SUCCESS"},
            ],
        )

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:2] == ["pr", "checks"]:
                return [
                    {
                        "name": "aragora-merge-quorum",
                        "state": "FAILURE",
                        "bucket": "fail",
                        "workflow": "Aragora Merge Quorum",
                    },
                    {
                        "name": "Generate & Validate",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "OpenAPI Spec",
                    },
                    {
                        "name": "TypeScript SDK Type Check",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "SDK Tests",
                    },
                    {"name": "lint", "state": "SUCCESS", "bucket": "pass", "workflow": "Lint"},
                    {
                        "name": "sdk-parity",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "SDK Parity Check",
                    },
                    {
                        "name": "typecheck",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "Lint",
                    },
                ]
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("8374", repo_override=None)
        required = packet.check_surfaces["required_pr_checks"]
        rollup = packet.check_surfaces["pr_rollup"]
        quorum = packet.model_review_quorum

        assert required["available"] is True
        assert required["failing_or_cancelled"] == ["aragora-merge-quorum"]
        assert required["gate_selected"] is True
        assert packet.check_surfaces["effective_gate"] == {
            "source": "required_pr_checks",
            "summary": "1 failing / 6 required (required PR checks; only merge-quorum failing)",
        }
        assert rollup["non_required_non_green_count"] == 2
        assert rollup["non_required_non_green_sample"] == [
            "Version Alignment",
            "Status Doc Reconciliation",
        ]
        assert quorum["status"] == "needs_model_review_quorum"
        assert quorum["verdict"] == "collect_model_quorum_before_merge"
        # Tier 2 under the tiered gate needs one western-frontier signal; with zero
        # model signals present the incomplete message reads 0/1.
        assert "model quorum incomplete: 0/1 signal(s)" in quorum["reasons"]
        assert "checks are failing; repair before settlement" not in quorum["reasons"]

    def test_required_pr_checks_gate_keeps_non_self_required_failure_blocking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7465,
            files=["docs/status/open.md"],
            checks=[
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"name": "typecheck", "status": "COMPLETED", "conclusion": "FAILURE"},
                {
                    "name": "Mac TypeScript SDK Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "QUEUED",
                    "conclusion": "",
                    "runner_id": 0,
                    "runner_name": "",
                    "queuedDurationSeconds": 7200,
                },
                {
                    "name": "aragora-merge-quorum",
                    "workflowName": "Aragora Merge Quorum",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                },
            ],
        )
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:2] == ["pr", "checks"]:
                return [
                    {
                        "name": "aragora-merge-quorum",
                        "state": "FAILURE",
                        "bucket": "fail",
                        "workflow": "Aragora Merge Quorum",
                    },
                    {
                        "name": "lint",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "Lint",
                    },
                    {
                        "name": "typecheck",
                        "state": "FAILURE",
                        "bucket": "fail",
                        "workflow": "Lint",
                    },
                ]
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        required = packet.check_surfaces["required_pr_checks"]
        rollup = packet.check_surfaces["pr_rollup"]

        assert "effective_gate" not in packet.check_surfaces
        assert required["failing_or_cancelled"] == ["typecheck"]
        assert rollup["optional_runner_capacity_noise_count"] == 1
        assert rollup["optional_runner_capacity_noise_sample"] == [
            "Self-Hosted Shadow CI / Mac TypeScript SDK Shadow"
        ]
        assert rollup["long_queued_self_hosted_shadow_without_runner_metadata_count"] == 0
        assert packet.machine_recommendation == "repair_first"
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"

    def test_required_pr_checks_gate_fails_closed_when_only_self_check_visible(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7465,
            files=["docs/status/open.md"],
            checks=[
                {"name": "Docs Consistency", "status": "COMPLETED", "conclusion": "FAILURE"},
            ],
        )
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "123456")
        monkeypatch.setenv("GITHUB_REPOSITORY", "synaptent/aragora")
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:2] == ["pr", "checks"]:
                return [
                    {
                        "name": "aragora-merge-quorum",
                        "state": "PENDING",
                        "bucket": "pending",
                        "workflow": "Aragora Merge Quorum",
                        "link": "https://github.com/synaptent/aragora/actions/runs/123456/job/1",
                    },
                ]
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        required = packet.check_surfaces["required_pr_checks"]

        assert required["effective_total"] == 0
        assert required["summary"] == "no required checks"
        assert required["gate_selected"] is False
        assert required["ignored_current_merge_quorum_self_check_count"] == 1
        assert "no effective branch-protection required checks" in required["gate_blocked_reason"]
        assert "effective_gate" not in packet.check_surfaces
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"

    def test_merge_quorum_self_check_uses_required_gate_despite_shadow_jobs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7465,
            files=["pyproject.toml", "uv.lock"],
            checks=[
                {
                    "name": "aragora-merge-quorum",
                    "workflowName": "Aragora Merge Quorum",
                    "status": "QUEUED",
                    "conclusion": "",
                    "detailsUrl": (
                        "https://github.com/synaptent/aragora/actions/runs/123456/job/1"
                    ),
                },
                {
                    "name": "lint",
                    "workflowName": "Lint",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                },
                {
                    "name": "TypeScript SDK Type Check",
                    "workflowName": "SDK Tests",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                },
                {
                    "name": "Mac TypeScript SDK Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "QUEUED",
                    "conclusion": "",
                    "runner_id": 0,
                    "runner_name": "",
                    "queuedDurationSeconds": 7200,
                },
                {
                    "name": "Hetzner Offline Golden Path Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "QUEUED",
                    "conclusion": "",
                    "runner_id": 0,
                    "runner_name": "",
                    "queuedDurationSeconds": 7200,
                },
            ],
        )
        pr_payload["comments"] = [
            _codex_openai_review_comment(),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setenv("GITHUB_WORKFLOW", "Aragora Merge Quorum")
        monkeypatch.setenv("GITHUB_JOB", "merge-quorum")
        monkeypatch.setenv("GITHUB_RUN_ID", "123456")
        monkeypatch.setenv("GITHUB_REPOSITORY", "synaptent/aragora")
        monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:2] == ["pr", "checks"]:
                return [
                    {
                        "name": "aragora-merge-quorum",
                        "state": "PENDING",
                        "bucket": "pending",
                        "workflow": "Aragora Merge Quorum",
                        "link": "https://github.com/synaptent/aragora/actions/runs/123456/job/1",
                    },
                    {
                        "name": "lint",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "Lint",
                    },
                    {
                        "name": "TypeScript SDK Type Check",
                        "state": "SUCCESS",
                        "bucket": "pass",
                        "workflow": "SDK Tests",
                    },
                ]
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        required = packet.check_surfaces["required_pr_checks"]
        rollup = packet.check_surfaces["pr_rollup"]

        assert packet.checks_summary == "2/2 required green (required PR checks)"
        assert required["effective_total"] == 2
        assert required["ignored_current_merge_quorum_self_check_count"] == 1
        assert required["gate_selected"] is True
        assert required["pending"] == []
        assert rollup["non_required_non_green_count"] == 2
        assert rollup["non_required_non_green_sample"] == [
            "Self-Hosted Shadow CI / Mac TypeScript SDK Shadow",
            "Self-Hosted Shadow CI / Hetzner Offline Golden Path Shadow",
        ]
        assert rollup["optional_runner_capacity_noise_count"] == 2
        assert rollup["optional_runner_capacity_noise_sample"] == [
            "Self-Hosted Shadow CI / Mac TypeScript SDK Shadow",
            "Self-Hosted Shadow CI / Hetzner Offline Golden Path Shadow",
        ]
        assert rollup["long_queued_self_hosted_shadow_without_runner_metadata_count"] == 0
        assert packet.model_review_quorum["status"] == "satisfied"
        assert packet.model_review_quorum["admin_squash_allowed"] is True

        rendered = io.StringIO()
        with redirect_stdout(rendered):
            _render_packet(packet)
        rendered_packet = rendered.getvalue()
        assert "gate_selected=true" in rendered_packet
        assert "non_required_non_green_rollup=Self-Hosted Shadow CI" in rendered_packet
        assert "optional_runner_capacity_noise=Self-Hosted Shadow CI" in rendered_packet

    def test_required_pr_checks_unavailable_explains_gate_not_selected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7465,
            files=["pyproject.toml", "uv.lock"],
            checks=[
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {
                    "name": "Mac TypeScript SDK Shadow",
                    "workflowName": "Self-Hosted Shadow CI",
                    "status": "QUEUED",
                    "conclusion": "",
                },
            ],
        )
        pr_payload["comments"] = [
            _dogfood_comment("## Codex focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Claude review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> Any:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:2] == ["pr", "checks"]:
                raise _GhError("required checks request timed out")
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        required = packet.check_surfaces["required_pr_checks"]

        assert required["available"] is False
        assert required["effective_total"] == 0
        assert required["gate_selected"] is False
        assert "cannot distinguish required checks" in required["gate_blocked_reason"]
        assert "required checks request timed out" in required["error"]
        assert "effective_gate" not in packet.check_surfaces
        assert packet.model_review_quorum["status"] == "repair_or_wait"
        assert packet.model_review_quorum["admin_squash_allowed"] is False

        rendered = io.StringIO()
        with redirect_stdout(rendered):
            _render_packet(packet)
        assert "required_gate_blocker:" in rendered.getvalue()

    def test_missing_check_rollup_uses_modern_checks_field_and_skipped_neutral(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload["statusCheckRollup"] = []
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:1] == ["api"] and "required_status_checks" in args[1]:
                return {
                    "contexts": [],
                    "checks": [
                        {"context": "lint", "app_id": 15368},
                        {"context": "typecheck", "app_id": 15368},
                    ],
                    "strict": False,
                }
            if args[:1] == ["api"] and "check-runs" in args[1]:
                return {
                    "check_runs": [
                        {
                            "name": "lint",
                            "status": "completed",
                            "conclusion": "skipped",
                            "app": {"id": 15368},
                        },
                        {
                            "name": "typecheck",
                            "status": "completed",
                            "conclusion": "neutral",
                            "app": {"id": 15368},
                        },
                    ]
                }
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert packet.checks_summary == "2/2 required green (direct check-runs fallback)"
        assert direct["required_contexts"] == ["lint", "typecheck"]
        assert direct["required_checks"] == [
            {"context": "lint", "app_id": 15368},
            {"context": "typecheck", "app_id": 15368},
        ]
        assert direct["successful_required_contexts"] == ["lint", "typecheck"]
        assert direct["non_success_required_contexts"] == []
        assert direct["required_contexts_satisfied"] is True
        assert packet.model_review_quorum["admin_squash_allowed"] is True

    def test_missing_check_rollup_fails_closed_when_required_app_binding_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload["statusCheckRollup"] = []
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:1] == ["api"] and "required_status_checks" in args[1]:
                return {
                    "contexts": [],
                    "checks": [{"context": "lint", "app_id": 15368}],
                    "strict": False,
                }
            if args[:1] == ["api"] and "check-runs" in args[1]:
                return {
                    "check_runs": [
                        {
                            "name": "lint",
                            "status": "completed",
                            "conclusion": "success",
                            "app": {"id": 99999},
                        },
                    ]
                }
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert direct["required_contexts"] == ["lint"]
        assert direct["required_checks"] == [{"context": "lint", "app_id": 15368}]
        assert direct["missing_required_contexts"] == ["lint"]
        assert direct["required_contexts_satisfied"] is False
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"

    def test_missing_check_rollup_fails_closed_when_branch_protection_is_strict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload["statusCheckRollup"] = []
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:1] == ["api"] and "required_status_checks" in args[1]:
                return {"contexts": ["lint", "typecheck"], "strict": True}
            if args[:1] == ["api"] and "check-runs" in args[1]:
                return {
                    "check_runs": [
                        {"name": "lint", "status": "completed", "conclusion": "success"},
                        {"name": "typecheck", "status": "completed", "conclusion": "success"},
                    ]
                }
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert packet.checks_summary == "no checks reported"
        assert direct["branch_protection_strict"] is True
        assert direct["successful_required_contexts"] == ["lint", "typecheck"]
        assert direct["required_contexts_satisfied"] is False
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"
        assert "strict base freshness" in packet.check_surfaces["diagnosis"]

    def test_missing_check_rollup_fails_closed_when_base_ref_is_unknown(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload.pop("baseRefName", None)
        pr_payload["statusCheckRollup"] = []
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:1] == ["api"] and "required_status_checks" in args[1]:
                raise AssertionError("must not query a fabricated default base ref")
            if args[:1] == ["api"] and "check-runs" in args[1]:
                return {
                    "check_runs": [
                        {"name": "lint", "status": "completed", "conclusion": "success"},
                    ]
                }
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert direct["branch_protection_required_status_checks_available"] is False
        assert direct["required_contexts"] == []
        assert direct["required_contexts_satisfied"] is False
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"

    def test_missing_check_rollup_fails_closed_when_required_status_fetch_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload["statusCheckRollup"] = []
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:1] == ["api"] and "required_status_checks" in args[1]:
                raise RuntimeError("branch protection endpoint timed out")
            if args[:1] == ["api"] and "check-runs" in args[1]:
                return {
                    "check_runs": [
                        {"name": "lint", "status": "completed", "conclusion": "success"},
                    ]
                }
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert packet.checks_summary == "no checks reported"
        assert packet.risk_flags == ["check rollup unavailable"]
        assert direct["branch_protection_required_status_checks_available"] is False
        assert direct["required_contexts"] == []
        assert direct["required_contexts_satisfied"] is False
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"

    def test_missing_check_rollup_fails_closed_when_direct_check_fetch_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload["statusCheckRollup"] = []
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:1] == ["api"] and "required_status_checks" in args[1]:
                return {
                    "contexts": ["lint"],
                    "checks": [{"context": "lint", "app_id": None}],
                    "strict": False,
                }
            if args[:1] == ["api"] and "check-runs" in args[1]:
                raise RuntimeError("check-runs endpoint timed out")
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert packet.checks_summary == "no checks reported"
        assert packet.risk_flags == ["check rollup unavailable"]
        assert direct["branch_protection_required_status_checks_available"] is True
        assert direct["required_contexts"] == ["lint"]
        assert direct["missing_required_contexts"] == ["lint"]
        assert direct["required_contexts_satisfied"] is False
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"

    def test_missing_check_rollup_fails_closed_when_required_context_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload["statusCheckRollup"] = []
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:1] == ["api"] and "required_status_checks" in args[1]:
                return {"contexts": ["lint", "typecheck"]}
            if args[:1] == ["api"] and "check-runs" in args[1]:
                return {
                    "check_runs": [
                        {"name": "lint", "status": "completed", "conclusion": "success"},
                    ]
                }
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert packet.checks_summary == "no checks reported"
        assert direct["missing_required_contexts"] == ["typecheck"]
        assert direct["required_contexts_satisfied"] is False
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"
        assert (
            "checks are unavailable; wait for GitHub check rollup before settlement"
            in packet.model_review_quorum["reasons"]
        )

    def test_missing_check_rollup_fails_closed_when_required_context_not_successful(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload["statusCheckRollup"] = []
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:1] == ["api"] and "required_status_checks" in args[1]:
                return {"contexts": ["lint", "typecheck"]}
            if args[:1] == ["api"] and "check-runs" in args[1]:
                return {
                    "check_runs": [
                        {"name": "lint", "status": "completed", "conclusion": "success"},
                        {
                            "name": "typecheck",
                            "status": "completed",
                            "conclusion": "failure",
                        },
                    ]
                }
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert packet.checks_summary == "no checks reported"
        assert direct["non_success_required_contexts"] == ["typecheck"]
        assert direct["required_contexts_satisfied"] is False
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"

    def test_missing_check_rollup_fails_closed_without_required_contexts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=7465, files=["docs/status/open.md"])
        pr_payload["statusCheckRollup"] = []
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return pr_payload
            if args[:1] == ["api"] and "required_status_checks" in args[1]:
                return {"contexts": []}
            if args[:1] == ["api"] and "check-runs" in args[1]:
                return {
                    "check_runs": [
                        {"name": "lint", "status": "completed", "conclusion": "success"},
                    ]
                }
            raise AssertionError(f"unexpected gh call: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_packet("7465", repo_override=None)
        direct = packet.check_surfaces["direct_commit_check_runs"]

        assert direct["required_contexts"] == []
        assert direct["required_contexts_satisfied"] is False
        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"

    def test_cancelled_merge_quorum_blocks_admin_squash_authorization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7456,
            files=["docs/status/open.md"],
            checks=[
                {
                    "name": "aragora-merge-quorum",
                    "workflowName": "Aragora Merge Quorum",
                    "status": "COMPLETED",
                    "conclusion": "CANCELLED",
                    "completedAt": "2026-05-27T17:13:53Z",
                },
                {
                    "name": "lint",
                    "workflowName": "Tests",
                    "status": "COMPLETED",
                    "conclusion": "SUCCESS",
                    "completedAt": "2026-05-27T17:14:53Z",
                },
            ],
        )
        pr_payload["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("7456", repo_override=None)
        quorum = packet.model_review_quorum

        assert packet.checks_summary == "1 failing / 2 total"
        assert packet.machine_recommendation == "repair_first"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["status"] == "repair_or_wait"
        assert "checks are failing; repair before settlement" in quorum["reasons"]

    def test_inconsistent_open_state_with_merged_at_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7473,
            files=["docs/status/stale.md"],
            merged_at="2026-05-27T00:19:36Z",
        )
        pr_payload["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("7473", repo_override=None)

        assert packet.model_review_quorum["admin_squash_allowed"] is False
        assert packet.model_review_quorum["status"] == "repair_or_wait"
        assert (
            "PR state is OPEN but mergedAt is set; settlement applies only to open unmerged PRs"
        ) in packet.model_review_quorum["reasons"]

    def test_merge_packet_omits_merged_pr_from_admin_squash_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7470,
            files=["docs/status/focus.md"],
            state="MERGED",
            merged_at="2026-05-27T00:19:36Z",
        )
        pr_payload["comments"] = [
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_queue",
            lambda limit, repo_override=None: [_classify_pr(_make_pr(number=7470))],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )

        packet = _build_merge_authorization_packet(
            pr_refs=["7470"],
            limit=10,
            repo_override=None,
        )

        assert packet["entries"][0]["status"] == "already_merged"
        assert packet["entries"][0]["verdict"] == "already_merged_noop"
        assert packet["entries"][0]["admin_squash_allowed"] is False
        assert packet["admin_squash_order"] == []
        assert packet["not_ready"] == []

    def test_merge_packet_short_circuits_explicit_merged_pr_before_full_hydration(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=7470,
            title="merged docs update",
            files=["docs/status/focus.md"],
            state="MERGED",
            merged_at="2026-05-27T00:19:36Z",
        )

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            assert args[:3] == ["pr", "view", "7470"]
            assert "comments" not in str(args)
            assert "reviews" not in str(args)
            assert "commits" not in str(args)
            return pr_payload

        def fail_build_packet(*_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("merged PRs must not build a full readiness packet")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_packet",
            fail_build_packet,
        )

        packet = _build_merge_authorization_packet(
            pr_refs=["7470"],
            limit=10,
            repo_override=None,
        )

        entry = packet["entries"][0]
        assert entry["status"] == "already_merged"
        assert entry["verdict"] == "already_merged_noop"
        assert entry["machine_recommendation"] == "settled_noop"
        assert entry["admin_squash_allowed"] is False
        assert entry["requires_human_risk_settlement"] is False
        assert entry["reasons"] == [
            "PR is already merged; merge-packet readiness is obsolete",
        ]
        assert packet["admin_squash_order"] == []
        assert packet["human_risk_settlement_required"] == []
        assert packet["not_ready"] == []

    def test_merge_packet_preserves_explicit_ref_order_with_merged_short_circuit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        merged_payload = _make_pr(
            number=7470,
            files=["docs/status/focus.md"],
            state="MERGED",
            merged_at="2026-05-27T00:19:36Z",
        )
        open_payload = _make_pr(
            number=7471,
            files=["docs/status/next.md"],
        )

        def fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:3] == ["pr", "view", "7470"]:
                return merged_payload
            if args[:3] == ["pr", "view", "7471"]:
                return open_payload
            raise AssertionError(f"unexpected gh args: {args}")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", fake_gh_json)

        packet = _build_merge_authorization_packet(
            pr_refs=["7471", "7470"],
            limit=10,
            repo_override=None,
        )

        assert [entry["pr_number"] for entry in packet["entries"]] == [7471, 7470]
        assert packet["entries"][1]["status"] == "already_merged"

    def test_merged_pr_with_exact_settlement_receipt_is_settled_noop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pr_payload = _make_pr(
            number=7447,
            files=["aragora/cli/commands/review_queue.py"],
            state="MERGED",
            merged_at="2026-05-27T02:57:31Z",
        )
        review_queue_root = tmp_path / "review-queue"
        _write_admin_squash_receipt(
            review_queue_root,
            pr_number=7447,
            head_sha=str(pr_payload["headRefOid"]),
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_queue",
            lambda limit, repo_override=None: [_classify_pr(_make_pr(number=7447))],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )

        packet = _build_packet(
            "7447",
            repo_override=None,
            review_queue_root=review_queue_root,
        )

        quorum = packet.model_review_quorum
        assert quorum["status"] == "settled"
        assert quorum["verdict"] == "already_merged_settlement_recorded"
        assert quorum["admin_squash_allowed"] is False
        assert quorum["requires_human_risk_settlement"] is False
        assert quorum["reasons"] == [
            "workflow/deploy/destructive surface touched",
            "exact-head admin_squash_merge settlement receipt recorded",
        ]

    @pytest.mark.parametrize("github_event", ["APPROVE", "RECORDED_EXTERNAL_APPROVE"])
    def test_open_tier_three_with_exact_human_risk_receipt_is_authorized(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        github_event: str,
    ) -> None:
        pr_payload = _make_pr(
            number=7466,
            files=["aragora/reputation/store.py"],
        )
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        review_queue_root = tmp_path / "review-queue"
        _write_human_risk_settlement_receipt(
            review_queue_root,
            pr_number=7466,
            head_sha=str(pr_payload["headRefOid"]),
            github_event=github_event,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_queue",
            lambda limit, repo_override=None: [_classify_pr(_make_pr(number=7466))],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )

        packet = _build_merge_authorization_packet(
            pr_refs=["7466"],
            limit=10,
            repo_override=None,
            review_queue_root=review_queue_root,
        )

        entry = packet["entries"][0]
        assert entry["status"] == "satisfied"
        assert entry["verdict"] == "admin_squash_allowed"
        assert entry["admin_squash_allowed"] is True
        assert entry["requires_human_risk_settlement"] is False
        assert entry["reasons"] == [
            "semantic, persistence, security, API, or SDK surface touched",
            "exact-head human risk settlement receipt recorded",
        ]
        assert packet["admin_squash_order"] == [7466]
        assert packet["human_risk_settlement_required"] == []
        assert packet["not_ready"] == []

    @pytest.mark.parametrize(
        ("head_sha", "action", "github_event", "payload_pr_number"),
        [
            ("stale-head-sha", "approve", "APPROVE", None),
            (None, "request_changes", "APPROVE", None),
            (None, "approve", "COMMENT", None),
            (None, "approve", "APPROVE", 9999),
        ],
    )
    def test_open_tier_three_with_invalid_human_risk_receipt_stays_blocked(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        head_sha: str | None,
        action: str,
        github_event: str,
        payload_pr_number: int | None,
    ) -> None:
        pr_payload = _make_pr(
            number=7466,
            files=["aragora/reputation/store.py"],
        )
        pr_payload["comments"] = [
            _dogfood_comment("## Claude focused dogfood\npass"),
            {
                "author": {"login": "an0mium"},
                "body": "## Grok independent model review\nVerdict: approve.",
            },
        ]
        review_queue_root = tmp_path / "review-queue"
        _write_human_risk_settlement_receipt(
            review_queue_root,
            pr_number=7466,
            head_sha=head_sha or str(pr_payload["headRefOid"]),
            action=action,
            github_event=github_event,
            payload_pr_number=payload_pr_number,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_queue",
            lambda limit, repo_override=None: [_classify_pr(_make_pr(number=7466))],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )

        packet = _build_merge_authorization_packet(
            pr_refs=["7466"],
            limit=10,
            repo_override=None,
            review_queue_root=review_queue_root,
        )

        entry = packet["entries"][0]
        assert entry["status"] == "human_risk_settlement_required"
        assert entry["admin_squash_allowed"] is False
        assert entry["requires_human_risk_settlement"] is True
        assert packet["admin_squash_order"] == []
        assert packet["human_risk_settlement_required"] == [7466]
        assert packet["not_ready"] == []

    def test_merged_pr_with_stale_settlement_receipt_stays_fail_closed(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        pr_payload = _make_pr(
            number=7447,
            files=["docs/status/focus.md"],
            state="MERGED",
            merged_at="2026-05-27T02:57:31Z",
        )
        review_queue_root = tmp_path / "review-queue"
        _write_admin_squash_receipt(
            review_queue_root,
            pr_number=7447,
            head_sha="stale-head-sha",
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )

        packet = _build_packet(
            "7447",
            repo_override=None,
            review_queue_root=review_queue_root,
        )

        quorum = packet.model_review_quorum
        assert quorum["status"] == "repair_or_wait"
        assert quorum["verdict"] == "not_ready_for_settlement"
        assert quorum["admin_squash_allowed"] is False
        assert "PR is MERGED; settlement applies only to open PRs" in quorum["reasons"]

    def test_build_packet_preserves_completed_merge_quorum_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=6281,
            checks=[
                {
                    "name": "aragora-merge-quorum",
                    "workflowName": "Aragora Merge Quorum",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                },
                {"name": "lint", "status": "COMPLETED", "conclusion": "SUCCESS"},
            ],
            files=["scripts/build_next_prompt.py"],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("6281", repo_override=None)
        assert packet.machine_recommendation == "repair_first"
        assert packet.checks_summary == "1 failing / 2 total"
        assert "checks failing (1 failing / 2 total)" in packet.risk_flags
        assert (
            "checks are failing; repair before settlement" in packet.model_review_quorum["reasons"]
        )

    def test_build_packet_preserves_non_self_check_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=6282,
            checks=[
                {
                    "name": "aragora-merge-quorum",
                    "status": "COMPLETED",
                    "conclusion": "FAILURE",
                },
                {"name": "lint", "status": "COMPLETED", "conclusion": "FAILURE"},
                {"name": "typecheck", "status": "COMPLETED", "conclusion": "SUCCESS"},
            ],
            files=["scripts/build_next_prompt.py"],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("6282", repo_override=None)
        assert packet.machine_recommendation == "repair_first"
        assert packet.checks_summary == "2 failing / 3 total"
        assert "checks failing (2 failing / 3 total)" in packet.risk_flags
        assert (
            "checks are failing; repair before settlement" in packet.model_review_quorum["reasons"]
        )

    def test_build_packet_flags_high_risk_paths(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pr_payload = _make_pr(
            number=42,
            files=["aragora/security/encryption.py", "aragora/cli/commands/review_pr.py"],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("42", repo_override=None)
        assert packet.machine_recommendation == "needs_human_attention"
        assert "aragora/security/encryption.py" in packet.high_risk_paths_touched

    def test_build_packet_failures_recommend_repair(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pr_payload = _make_pr(
            number=99,
            checks=[{"status": "COMPLETED", "conclusion": "FAILURE"}],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("99", repo_override=None)
        assert packet.machine_recommendation == "repair_first"

    def test_build_packet_draft_needs_attention(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pr_payload = _make_pr(number=101, is_draft=True)
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("101", repo_override=None)
        assert packet.machine_recommendation == "needs_human_attention"
        assert "draft" in packet.machine_recommendation_reason.lower()
        assert "draft PR" in packet.risk_flags

    def test_build_packet_parked_label_needs_attention(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(number=102, labels=["blocked"])
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("102", repo_override=None)
        assert packet.machine_recommendation == "needs_human_attention"
        assert "parked label" in packet.machine_recommendation_reason.lower()
        assert "parked label (blocked)" in packet.risk_flags

    def test_build_packet_pending_checks_need_attention(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=100,
            checks=[{"status": "IN_PROGRESS", "conclusion": ""}],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("100", repo_override=None)
        assert packet.machine_recommendation == "needs_human_attention"
        assert "checks still pending" in packet.machine_recommendation_reason

    def test_build_packet_state_based_pending_checks_need_attention(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pr_payload = _make_pr(
            number=100,
            checks=[{"context": "ci/unit", "state": "PENDING"}],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        packet = _build_packet("100", repo_override=None)
        assert packet.machine_recommendation == "needs_human_attention"
        assert "checks still pending" in packet.machine_recommendation_reason

    def test_build_packet_raises_when_pr_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: None,
        )
        with pytest.raises(_GhError, match="not found"):
            _build_packet("9999", repo_override=None)

    def test_build_packet_can_execute_live_reviewers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pr_payload = _make_pr(
            number=6280,
            files=["aragora/cli/commands/review_pr.py"],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: pr_payload,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_text",
            lambda args: (
                "diff --git a/aragora/cli/commands/review_pr.py b/aragora/cli/commands/review_pr.py"
            ),
        )
        outputs = [
            _make_reviewer_output(
                slot_id="logic",
                provider="claude",
                family="claude",
                recommendation=Recommendation.APPROVE_CANDIDATE,
            ),
            _make_reviewer_output(
                slot_id="security",
                provider="openai-api",
                family="gpt",
                recommendation=Recommendation.REPAIR_FIRST,
            ),
            _make_reviewer_output(
                slot_id="maintainability",
                provider="gemini-cli",
                family="gemini",
                recommendation=Recommendation.APPROVE_CANDIDATE,
            ),
        ]
        monkeypatch.setattr(
            "aragora.swarm.pr_review_protocol.PRReviewProtocol.execute_live_reviewers",
            lambda self, **kwargs: (outputs, []),
        )

        packet = _build_packet("6280", repo_override=None, execute_reviewers=True)

        assert packet.protocol["status"] == EXECUTED_PROTOCOL_STATUS
        assert packet.protocol["validation_summary"]["reviewer_execution"]["reviewer_count"] == 3
        assert len(packet.protocol["dissenting_views"]) == 1
        assert packet.model_review_quorum["unresolved_dissent"] is True


# --- JSON output schema ----------------------------------------------------


class TestJsonOutput:
    def test_queue_item_to_dict_keys(self) -> None:
        item = _classify_pr(_make_pr())
        d = item.to_dict()
        for key in (
            "number",
            "title",
            "url",
            "head_sha",
            "author",
            "is_draft",
            "mergeable",
            "labels",
            "additions",
            "deletions",
            "changed_files",
            "checks_summary",
            "lane",
            "lane_reason",
        ):
            assert key in d, f"QueueItem dict missing key: {key}"

    def test_packet_to_dict_keys(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: _make_pr(number=1, files=["aragora/cli/main.py"]),
        )
        packet = _build_packet("1", repo_override=None)
        d = packet.to_dict()
        for key in (
            "pr_number",
            "title",
            "url",
            "head_sha",
            "base_sha",
            "author",
            "is_draft",
            "additions",
            "deletions",
            "changed_files",
            "queue_bucket",
            "touched_subsystems",
            "high_risk_paths_touched",
            "validation",
            "checks_summary",
            "check_surfaces",
            "risk_flags",
            "machine_recommendation",
            "machine_recommendation_reason",
            "packet_sha",
            "generated_at",
            "protocol",
            "model_review_quorum",
            "advisory_only",
            "settlement_note",
        ):
            assert key in d, f"ReviewPacket dict missing key: {key}"
        # ReviewPacket.advisory_only must always be True (signature property).
        assert d["advisory_only"] is True
        assert d["protocol"]["binding"]["repo"] == "synaptent/aragora"
        assert d["model_review_quorum"]["version"] == "model_review_quorum.v1"

    def test_packet_json_round_trip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: _make_pr(number=1, files=["aragora/cli/main.py"]),
        )
        packet = _build_packet("1", repo_override=None)
        roundtrip = json.loads(json.dumps(packet.to_dict()))
        assert roundtrip["pr_number"] == 1
        assert roundtrip["advisory_only"] is True
        assert roundtrip["protocol"]["protocol_version"] == "pr_review_protocol.v1"
        assert "model_review_quorum" in roundtrip

    def test_merge_packet_json_transport_blocked_envelope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def raise_transport(**_kwargs: object) -> dict[str, object]:
            raise _GhError("gh pr view 7885 failed: TLS handshake timeout")

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_merge_authorization_packet",
            raise_transport,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda _args: (_ for _ in ()).throw(_GhError("REST fallback unavailable")),
        )
        ns = argparse.Namespace(
            review_queue_command="merge-packet",
            pr=["7885"],
            repo="synaptent/aragora",
            limit=1,
            review_queue_root=None,
            execute_reviewers=False,
            ignore_own_quorum_check=False,
            json=True,
        )
        out_buf = io.StringIO()
        err_buf = io.StringIO()

        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = cmd_review_queue(ns)

        assert rc == 1
        assert err_buf.getvalue() == ""
        payload = json.loads(out_buf.getvalue())
        assert payload["version"] == "merge_authorization_packet.v1"
        assert payload["status"] == "transport_blocked"
        assert payload["transport_blocked"] is True
        assert payload["preserve_no_mutate"] is True
        assert payload["error_kind"] == "github_transport"
        assert payload["not_ready"] == [7885]
        assert payload["entries"] == []
        assert payload["admin_squash_allowed"] is False
        assert payload["rest_fallback"]["available"] is False

    def test_conductor_json_transport_blocked_envelope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import aragora.cli.commands.review_queue_conductor as conductor

        def raise_transport(**_kwargs: object) -> dict[str, object]:
            raise _GhError("gh pr view 7885 failed: read: connection reset by peer")

        monkeypatch.setattr(conductor, "build_queue_conductor_packet", raise_transport)
        ns = argparse.Namespace(
            review_queue_command="conductor",
            pr=["7885"],
            repo="synaptent/aragora",
            limit=1,
            review_queue_root=None,
            owner_timeout_seconds=1.0,
            mode="ready-boundary",
            json=True,
        )
        out_buf = io.StringIO()
        err_buf = io.StringIO()

        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = cmd_review_queue(ns)

        assert rc == 1
        assert err_buf.getvalue() == ""
        payload = json.loads(out_buf.getvalue())
        assert payload["version"] == "queue_conductor.v1"
        assert payload["status"] == "transport_blocked"
        assert payload["transport_blocked"] is True
        assert payload["preserve_no_mutate"] is True
        assert payload["error_kind"] == "github_transport"
        assert payload["mode"] == "ready-boundary"
        assert payload["not_ready"] == [7885]
        assert payload["candidates"] == []


# --- cmd_review_queue dispatch + parser ------------------------------------


class TestCommandDispatch:
    def test_parser_registers_build_packet_run_and_act(self) -> None:
        root = argparse.ArgumentParser()
        sub = root.add_subparsers()
        add_review_queue_parser(sub)
        # build invocation parses
        ns_build = root.parse_args(["review-queue", "build", "--limit", "5", "--json"])
        assert ns_build.review_queue_command == "build"
        assert ns_build.limit == 5
        assert ns_build.json is True
        # packet invocation parses
        ns_packet = root.parse_args(
            ["review-queue", "packet", "6280", "--execute-reviewers", "--json"]
        )
        assert ns_packet.review_queue_command == "packet"
        assert ns_packet.pr == "6280"
        assert ns_packet.execute_reviewers is True
        # merge-packet invocation parses
        ns_merge_packet = root.parse_args(["review-queue", "merge-packet", "--pr", "6280"])
        assert ns_merge_packet.review_queue_command == "merge-packet"
        assert ns_merge_packet.pr == ["6280"]
        ns_merge_packet_root = root.parse_args(
            [
                "review-queue",
                "merge-packet",
                "--pr",
                "6280",
                "--review-queue-root",
                "/tmp/review-queue",
            ]
        )
        assert ns_merge_packet_root.review_queue_command == "merge-packet"
        assert ns_merge_packet_root.review_queue_root == "/tmp/review-queue"
        # evidence-lint invocation parses
        ns_evidence_lint = root.parse_args(
            [
                "review-queue",
                "evidence-lint",
                "--pr",
                "6280",
                "--head-sha",
                "headsha123",
                "--body",
                "## Codex focused dogfood\nCurrent head: headsha123",
                "--json",
            ]
        )
        assert ns_evidence_lint.review_queue_command == "evidence-lint"
        assert ns_evidence_lint.pr == "6280"
        assert ns_evidence_lint.head_sha == "headsha123"
        assert ns_evidence_lint.body_file is None
        assert ns_evidence_lint.json is True
        # collect-evidence invocation parses through the fast-path command parser
        ns_collect = root.parse_args(
            [
                "review-queue",
                "collect-evidence",
                "--repo",
                "synaptent/aragora",
                "--pr",
                "6280",
                "--reviewers",
                "claude",
                "openai",
                "--author",
                "an0mium",
                "--reviewer-timeout",
                "90",
                "--overall-timeout",
                "150",
                "--json",
            ]
        )
        assert ns_collect.review_queue_command == "collect-evidence"
        assert ns_collect.repo == "synaptent/aragora"
        assert ns_collect.pr == 6280
        assert ns_collect.reviewers == ["claude", "openai"]
        assert ns_collect.author == "an0mium"
        assert ns_collect.reviewer_timeout == 90.0
        assert ns_collect.overall_timeout == 150.0
        assert ns_collect.apply is False
        assert ns_collect.json_output is True
        # run invocation parses
        ns_run = root.parse_args(["review-queue", "run", "--limit", "3", "--ready-only"])
        assert ns_run.review_queue_command == "run"
        assert ns_run.limit == 3
        assert ns_run.ready_only is True
        # health invocation parses through the standalone command parser
        ns_health = root.parse_args(["review-queue", "health", "--json"])
        assert ns_health.review_queue_command == "health"
        assert ns_health.json_output is True
        # health-alert invocation parses through the standalone command parser
        ns_alert = root.parse_args(["review-queue", "health-alert", "--heartbeat", "--json"])
        assert ns_alert.review_queue_command == "health-alert"
        assert ns_alert.heartbeat is True
        assert ns_alert.json_output is True
        # act invocation parses
        ns_act = root.parse_args(
            ["review-queue", "act", "6280", "--request-changes", "--reason", "needs a test"]
        )
        assert ns_act.review_queue_command == "act"
        assert ns_act.pr == "6280"
        assert ns_act.request_changes is True
        assert ns_act.reason == "needs a test"
        # local-only external settlement recording parses
        ns_record = root.parse_args(
            [
                "review-queue",
                "record-settlement",
                "6280",
                "--head-sha",
                "headsha123",
                "--action",
                "admin_squash_merge",
                "--reason",
                "operator authorized exact-head merge",
                "--apply-post-merge-lane-audit",
                "--json",
            ]
        )
        assert ns_record.review_queue_command == "record-settlement"
        assert ns_record.pr == "6280"
        assert ns_record.head_sha == "headsha123"
        assert ns_record.action == "admin_squash_merge"
        assert ns_record.reason == "operator authorized exact-head merge"
        assert ns_record.apply_post_merge_lane_audit is True

    def test_cmd_review_queue_with_no_subcommand_returns_2(self) -> None:
        ns = argparse.Namespace(review_queue_command=None)
        rc = cmd_review_queue(ns)
        assert rc == 2

    def test_top_level_parser_registers_record_settlement(self) -> None:
        from aragora.cli.parser import build_parser

        parser = build_parser()
        ns = parser.parse_args(
            [
                "review-queue",
                "record-settlement",
                "6280",
                "--head-sha",
                "headsha123",
                "--action",
                "admin_squash_merge",
                "--reason",
                "operator authorized exact-head merge",
                "--apply-post-merge-lane-audit",
                "--json",
            ]
        )

        assert ns.command == "review-queue"
        assert ns.review_queue_command == "record-settlement"
        assert ns.pr == "6280"
        assert ns.head_sha == "headsha123"
        assert ns.action == "admin_squash_merge"
        assert ns.reason == "operator authorized exact-head merge"
        assert ns.apply_post_merge_lane_audit is True
        assert ns.json_output is True

    def test_top_level_parser_registers_evidence_lint(self) -> None:
        from aragora.cli.parser import build_parser

        parser = build_parser()
        ns = parser.parse_args(
            [
                "review-queue",
                "evidence-lint",
                "--pr",
                "7445",
                "--head-sha",
                "cd87c5a1b2db34f04167906553502db3ede9525e",
                "--body",
                "## Claude review\nCurrent head: cd87c5a1b2db34f04167906553502db3ede9525e",
                "--json",
            ]
        )

        assert ns.command == "review-queue"
        assert ns.review_queue_command == "evidence-lint"
        assert ns.pr == "7445"
        assert ns.head_sha == "cd87c5a1b2db34f04167906553502db3ede9525e"
        assert ns.body_file is None
        assert ns.json_output is True

    def test_top_level_parser_registers_lint_comment_alias(self) -> None:
        from aragora.cli.parser import build_parser

        parser = build_parser()
        ns = parser.parse_args(
            [
                "review-queue",
                "lint-comment",
                "--pr",
                "7445",
                "--head",
                "cd87c5a1b2db34f04167906553502db3ede9525e",
                "--body-file",
                "comment.md",
                "--json",
            ]
        )

        assert ns.command == "review-queue"
        assert ns.review_queue_command == "lint-comment"
        assert ns.pr == "7445"
        assert ns.head_sha == "cd87c5a1b2db34f04167906553502db3ede9525e"
        assert ns.body_file == "comment.md"
        assert ns.json_output is True

    def test_evidence_lint_counts_current_head_dogfood(self) -> None:
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="2026-05-23T19:00:00Z",
            body=_codex_openai_body(
                body=(
                    "Current head: cd87c5a1b2db34f04167906553502db3ede9525e\n"
                    "Validation passed for the exact touched surface."
                )
            ),
            body_file=None,
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 0
        assert payload["mode"] == "evidence_lint"
        assert payload["would_count"] is True
        assert payload["counted_reviewer_ids"] == ["openai"]
        assert payload["dogfood_evidence"][0]["reviewer_id"] == "openai"
        assert payload["current_head_grounding_method"] == "head_sha_citation"
        assert payload["problems"] == []

    def test_evidence_lint_rejects_github_actions_bot_author(self) -> None:
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="2026-05-23T19:00:00Z",
            body=_codex_openai_body(
                body=(
                    "Current head: cd87c5a1b2db34f04167906553502db3ede9525e\n"
                    "Automated structured evidence must remain advisory-only."
                )
            ),
            body_file=None,
            author="github-actions[bot]",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 1
        assert payload["would_count"] is False
        assert payload["reviewer_signals"] == []
        assert payload["dogfood_evidence"] == []
        assert "github_actions_author_not_counted" in payload["problems"]
        assert "no_counted_model_family" in payload["problems"]

    def test_evidence_lint_rejects_ungrounded_comment(self) -> None:
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="2026-05-23T19:00:00Z",
            body="## Claude review\n\nLooks good, but no exact head citation.",
            body_file=None,
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 1
        assert payload["would_count"] is False
        assert payload["current_head_grounding_method"] == "missing_head_sha_citation"
        assert "missing_current_head_grounding" in payload["problems"]
        assert "no_counted_model_reviewer" in payload["problems"]

    def test_evidence_lint_rejects_wrong_pr_reference(self) -> None:
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="2026-05-23T19:00:00Z",
            body=_codex_openai_body(
                body=(
                    "PR: #9999\n"
                    "Current head: cd87c5a1b2db34f04167906553502db3ede9525e\n"
                    "Focused adversarial dogfood found no blockers."
                )
            ),
            body_file=None,
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 1
        assert payload["would_count"] is False
        assert payload["current_head_grounding_method"] == "head_sha_citation"
        assert payload["current_pr_grounding_method"] == "wrong_pr_citation"
        assert payload["dogfood_evidence"] == []
        assert "wrong_pr_reference" in payload["problems"]
        assert "no_counted_model_reviewer" in payload["problems"]

    def test_evidence_lint_rejects_wrong_pr_number_label(self) -> None:
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="2026-05-23T19:00:00Z",
            body=_codex_openai_body(
                body=(
                    "PR Number: #9999\n"
                    "Current head: cd87c5a1b2db34f04167906553502db3ede9525e\n"
                    "Focused adversarial dogfood found no blockers."
                )
            ),
            body_file=None,
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 1
        assert payload["would_count"] is False
        assert payload["current_pr_grounding_method"] == "wrong_pr_citation"
        assert payload["dogfood_evidence"] == []
        assert "wrong_pr_reference" in payload["problems"]

    def test_evidence_lint_rejects_wrong_pr_url_reference(self) -> None:
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="2026-05-23T19:00:00Z",
            body=_codex_openai_body(
                body=(
                    "Evidence comment: https://github.com/synaptent/aragora/pull/9999"
                    "#issuecomment-123\n"
                    "Exact head reviewed: cd87c5a1b2db34f04167906553502db3ede9525e\n"
                    "Focused adversarial dogfood found no blockers."
                )
            ),
            body_file=None,
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 1
        assert payload["would_count"] is False
        assert payload["current_head_grounding_method"] == "head_sha_citation"
        assert payload["current_pr_grounding_method"] == "wrong_pr_citation"
        assert payload["dogfood_evidence"] == []
        assert "wrong_pr_reference" in payload["problems"]
        assert "no_counted_model_reviewer" in payload["problems"]

    def test_evidence_lint_rejects_explicit_blocking_verdict(self) -> None:
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="2026-05-23T19:00:00Z",
            body=_codex_openai_body(
                body=(
                    "PR: #7445\n"
                    "Current head: cd87c5a1b2db34f04167906553502db3ede9525e\n"
                    "Verdict: FAIL\n"
                    "Blocking findings: found - helper can still misclassify stale evidence."
                )
            ),
            body_file=None,
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 1
        assert payload["would_count"] is False
        assert payload["reviewer_signals"] == []
        assert payload["dogfood_evidence"] == []
        assert "blocking_or_negative_verdict" in payload["problems"]
        assert "no_counted_model_reviewer" in payload["problems"]

    def test_evidence_lint_rejects_p1_finding_without_negative_verdict(self) -> None:
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="2026-05-23T19:00:00Z",
            body=(
                "## Claude independent semantic review on head "
                "cd87c5a1b2db34f04167906553502db3ede9525e\n\n"
                "**Reviewer harness:** claude\n"
                "**Model family:** claude\n"
                "**Model id:** Claude Code\n"
                "**Receipt artifact:** /tmp/receipt.md\n\n"
                "[P1] This exact-head diff still has a blocking dependency drift finding.\n\n"
                "Focused adversarial dogfood: I reviewed the exact-head diff."
            ),
            body_file=None,
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 1
        assert payload["would_count"] is False
        assert payload["reviewer_signals"] == []
        assert payload["dogfood_evidence"] == []
        assert "blocking_or_negative_verdict" in payload["problems"]

    @pytest.mark.parametrize(
        "finding_line",
        [
            "1. [P1] This exact-head diff still has a blocking finding.",
            "1) [P0] This exact-head diff still has a blocking finding.",
            "> [P1] This exact-head diff still has a blocking finding.",
            "## [P1] This exact-head diff still has a blocking finding.",
        ],
    )
    def test_evidence_lint_rejects_decorated_p1_findings_without_negative_verdict(
        self,
        finding_line: str,
    ) -> None:
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="2026-05-23T19:00:00Z",
            body=(
                "## Claude independent semantic review on head "
                "cd87c5a1b2db34f04167906553502db3ede9525e\n\n"
                "**Reviewer harness:** claude\n"
                "**Model family:** claude\n"
                "**Model id:** Claude Code\n"
                "**Receipt artifact:** /tmp/receipt.md\n\n"
                f"{finding_line}\n\n"
                "Focused adversarial dogfood: I reviewed the exact-head diff."
            ),
            body_file=None,
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 1
        assert payload["would_count"] is False
        assert payload["reviewer_signals"] == []
        assert payload["dogfood_evidence"] == []
        assert "blocking_or_negative_verdict" in payload["problems"]

    def test_evidence_lint_requires_head_sha_when_timestamp_omitted(self) -> None:
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="",
            body="## Codex focused dogfood\n\nValidation passed, but no SHA citation.",
            body_file=None,
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 1
        assert payload["would_count"] is False
        assert payload["current_head_grounding_method"] == "missing_head_sha_citation"
        assert "missing_current_head_grounding" in payload["problems"]

    def test_evidence_lint_reads_body_file(self, tmp_path: Path) -> None:
        body_file = tmp_path / "comment.md"
        body_file.write_text(
            "## Claude review\n\n"
            "Current head: cd87c5a1b2db34f04167906553502db3ede9525e\n"
            "I reviewed the exact-head evidence-lint diff.",
            encoding="utf-8",
        )
        ns = argparse.Namespace(
            review_queue_command="evidence-lint",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="2026-05-23T19:00:00Z",
            body=None,
            body_file=str(body_file),
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 0
        assert payload["would_count"] is True
        assert payload["counted_reviewer_ids"] == ["claude"]
        assert payload["current_head_grounding_method"] == "head_sha_citation"
        assert payload["reviewer_signals"][0]["reviewer_id"] == "claude"

    def test_lint_comment_alias_reads_body_file(self, tmp_path: Path) -> None:
        body_file = tmp_path / "comment.md"
        body_file.write_text(
            "## Claude review - current head cd87c5a1b2db34f04167906553502db3ede9525e\n\n"
            "**Reviewer harness:** droid\n"
            "**Model family:** claude\n"
            "**Model id:** claude-opus-4-7\n"
            "**Receipt artifact:** droid exec --auto high\n\n"
            "Focused adversarial dogfood found no blockers.",
            encoding="utf-8",
        )
        ns = argparse.Namespace(
            review_queue_command="lint-comment",
            pr="7445",
            head_sha="cd87c5a1b2db34f04167906553502db3ede9525e",
            head_committed_at="",
            body=None,
            body_file=str(body_file),
            author="an0mium",
            json=True,
        )

        out = io.StringIO()
        with redirect_stdout(out):
            rc = cmd_review_queue(ns)

        payload = json.loads(out.getvalue())
        assert rc == 0
        assert payload["would_count"] is True
        assert payload["counted_reviewer_ids"] == ["claude"]
        assert payload["reviewer_signals"][0]["reviewer_id"] == "claude"
        assert payload["dogfood_evidence"][0]["reviewer_id"] == "claude"


class TestSettlementHelpers:
    def test_requested_action(self) -> None:
        assert (
            _requested_action(argparse.Namespace(approve=True, request_changes=False, defer=False))
            == "approve"
        )
        assert (
            _requested_action(argparse.Namespace(approve=False, request_changes=True, defer=False))
            == "request_changes"
        )
        assert (
            _requested_action(argparse.Namespace(approve=False, request_changes=False, defer=True))
            == "defer"
        )

    def test_settle_packet_writes_receipt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        recorded: list[list[str]] = []

        def _record_gh_text(args: list[str]) -> str:
            recorded.append(args)
            return ""

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._current_head_sha",
            lambda pr_number, repo_override=None: "headsha123",
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_text",
            _record_gh_text,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._github_actor",
            lambda: "an0mium",
        )
        packet = ReviewPacket(
            pr_number=6294,
            title="route PR-targeted handoffs out of boss queue",
            url="https://github.com/synaptent/aragora/pull/6294",
            head_sha="headsha123",
            base_sha="basesha123",
            author="codex",
            is_draft=False,
            additions=10,
            deletions=2,
            changed_files=1,
            queue_bucket="ready_now",
            touched_subsystems=["scripts"],
            high_risk_paths_touched=[],
            validation=["`python3 -m pytest -q tests/scripts/test_publish_automation_handoffs.py`"],
            checks_summary="5/5 green",
            risk_flags=[],
            machine_recommendation="approve_candidate",
            machine_recommendation_reason="all green, bounded diff, no high-risk paths",
            packet_sha="sha256:testpacket",
            generated_at="2026-04-19T05:00:00+00:00",
        )
        receipt = _settle_packet(
            packet=packet,
            action="approve",
            reason="looks bounded",
            repo_root=tmp_path,
            repo_override=None,
            session_id="session-1",
            elapsed_seconds=1.25,
        )
        assert recorded and "--approve" in recorded[0]
        assert receipt.actor == "an0mium"
        assert receipt.github_event == "APPROVE"
        assert receipt.receipt_path.endswith("pr-6294-session-1-approve.json")
        saved = json.loads(Path(receipt.receipt_path).read_text())
        assert saved["packet_sha"] == "sha256:testpacket"
        assert saved["reason"] == "looks bounded"

    def test_settle_packet_rejects_stale_head(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._current_head_sha",
            lambda pr_number, repo_override=None: "new-head",
        )
        packet = ReviewPacket(
            pr_number=1,
            title="stale",
            url="https://github.com/synaptent/aragora/pull/1",
            head_sha="old-head",
            base_sha="basesha123",
            author="codex",
            is_draft=False,
            additions=1,
            deletions=1,
            changed_files=1,
            queue_bucket="ready_now",
            touched_subsystems=["aragora/cli"],
            high_risk_paths_touched=[],
            validation=[],
            checks_summary="1/1 green",
            risk_flags=[],
            machine_recommendation="approve_candidate",
            machine_recommendation_reason="clean",
            packet_sha="sha256:testpacket",
            generated_at="2026-04-19T05:00:00+00:00",
        )
        with pytest.raises(_GhError, match="refresh the packet"):
            _settle_packet(
                packet=packet,
                action="approve",
                reason="",
                repo_root=tmp_path,
                repo_override=None,
                session_id="session-2",
            )

    def test_record_external_settlement_writes_local_receipt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return {
                    "number": 6294,
                    "url": "https://github.com/synaptent/aragora/pull/6294",
                    "headRefOid": "headsha123",
                    "baseRefOid": "basesha123",
                    "state": "MERGED",
                    "mergedAt": "2026-05-10T08:00:00Z",
                }
            if args == ["api", "user"]:
                return {"login": "an0mium"}
            raise AssertionError(args)

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", _fake_gh_json)

        result = _record_external_settlement(
            pr_ref="6294",
            head_sha="headsha123",
            action="admin_squash_merge",
            reason="operator authorized exact-head merge",
            repo_root=tmp_path,
            repo_override=None,
            review_queue_root=None,
        )

        assert result.written is True
        assert result.idempotent is False
        assert result.receipt_sha256.startswith("sha256:")
        assert result.receipt.action == "admin_squash_merge"
        assert result.receipt.actor == "an0mium"
        assert result.receipt.reviewed_at == "2026-05-10T08:00:00+00:00"
        assert result.receipt.github_event == "ADMIN_SQUASH_MERGE"
        assert result.receipt.queue_bucket == "external_settlement"
        assert result.receipt.machine_recommendation == "operator_recorded_external_settlement"
        saved = json.loads(Path(result.receipt.receipt_path).read_text())
        assert saved["pr_number"] == 6294
        assert saved["head_sha"] == "headsha123"
        assert saved["packet_sha"].startswith("sha256:")

    def test_record_external_admin_merge_includes_post_merge_lane_audit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return {
                    "number": 6294,
                    "url": "https://github.com/synaptent/aragora/pull/6294",
                    "headRefOid": "headsha123",
                    "baseRefOid": "basesha123",
                    "state": "MERGED",
                    "mergedAt": "2026-05-10T08:00:00Z",
                }
            if args == ["api", "user"]:
                return {"login": "an0mium"}
            raise AssertionError(args)

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", _fake_gh_json)
        audit_calls: list[tuple[int, bool]] = []

        def audit_provider(pr_number: int, apply: bool = False) -> dict[str, Any]:
            audit_calls.append((pr_number, apply))
            return {
                "finding_count": 1,
                "resolved_count": 0,
                "blocked_reason": None,
                "owner_steering_text": "",
                "owner_release_commands": [],
                "operator_apply_command": "python3 scripts/resolve_lane_conflicts.py --apply ...",
                "receipt_paths": [],
                "github_state": {"state": "MERGED", "mergeCommit": "merge-sha"},
                "audit_ok": True,
                "audit_applied": False,
            }

        result = _record_external_settlement(
            pr_ref="6294",
            head_sha="headsha123",
            action="admin_squash_merge",
            reason="operator authorized exact-head merge",
            repo_root=tmp_path,
            repo_override=None,
            review_queue_root=None,
            post_merge_lane_audit_provider=audit_provider,
        )

        assert audit_calls == [(6294, False)]
        assert result.post_merge_lane_audit is not None
        assert result.to_dict()["post_merge_lane_audit"]["operator_apply_command"].startswith(
            "python3 scripts/resolve_lane_conflicts.py"
        )
        saved = json.loads(Path(result.receipt.receipt_path).read_text())
        assert saved["post_merge_lane_audit"]["finding_count"] == 1

    def test_record_external_non_merge_settlement_does_not_run_post_merge_lane_audit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return {
                    "number": 6294,
                    "url": "https://github.com/synaptent/aragora/pull/6294",
                    "headRefOid": "headsha123",
                    "baseRefOid": "basesha123",
                    "state": "OPEN",
                    "mergedAt": "",
                }
            if args == ["api", "user"]:
                return {"login": "an0mium"}
            raise AssertionError(args)

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", _fake_gh_json)

        def audit_provider(pr_number: int, apply: bool = False) -> dict[str, Any]:
            raise AssertionError("post-merge audit should only run for admin_squash_merge")

        result = _record_external_settlement(
            pr_ref="6294",
            head_sha="headsha123",
            action="comment",
            reason="operator recorded a comment",
            repo_root=tmp_path,
            repo_override=None,
            review_queue_root=None,
            post_merge_lane_audit_provider=audit_provider,
        )

        assert result.post_merge_lane_audit is None
        assert "post_merge_lane_audit" not in result.to_dict()

    def test_record_external_settlement_is_idempotent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return {
                    "number": 6294,
                    "url": "https://github.com/synaptent/aragora/pull/6294",
                    "headRefOid": "headsha123",
                    "baseRefOid": "basesha123",
                    "state": "MERGED",
                    "mergedAt": "2026-05-10T08:00:00Z",
                }
            if args == ["api", "user"]:
                return {"login": "an0mium"}
            raise AssertionError(args)

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", _fake_gh_json)

        first = _record_external_settlement(
            pr_ref="6294",
            head_sha="headsha123",
            action="admin_squash_merge",
            reason="operator authorized exact-head merge",
            repo_root=tmp_path,
            repo_override=None,
            review_queue_root=None,
        )
        second = _record_external_settlement(
            pr_ref="6294",
            head_sha="headsha123",
            action="admin_squash_merge",
            reason="operator authorized exact-head merge",
            repo_root=tmp_path,
            repo_override=None,
            review_queue_root=None,
        )

        assert first.receipt.receipt_path == second.receipt.receipt_path
        assert second.written is False
        assert second.idempotent is True
        assert second.receipt_sha256 == first.receipt_sha256

    def test_record_external_settlement_rejects_conflicting_existing_receipt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return {
                    "number": 6294,
                    "url": "https://github.com/synaptent/aragora/pull/6294",
                    "headRefOid": "headsha123",
                    "baseRefOid": "basesha123",
                    "state": "MERGED",
                    "mergedAt": "2026-05-10T08:00:00Z",
                }
            if args == ["api", "user"]:
                return {"login": "an0mium"}
            raise AssertionError(args)

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", _fake_gh_json)

        _record_external_settlement(
            pr_ref="6294",
            head_sha="headsha123",
            action="admin_squash_merge",
            reason="operator authorized exact-head merge",
            repo_root=tmp_path,
            repo_override=None,
            review_queue_root=None,
        )
        with pytest.raises(_GhError, match="conflicting settlement receipt"):
            _record_external_settlement(
                pr_ref="6294",
                head_sha="headsha123",
                action="admin_squash_merge",
                reason="different operator reason",
                repo_root=tmp_path,
                repo_override=None,
                review_queue_root=None,
            )

    def test_record_external_settlement_rejects_head_mismatch(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: {
                "number": 6294,
                "url": "https://github.com/synaptent/aragora/pull/6294",
                "headRefOid": "new-head",
                "baseRefOid": "basesha123",
                "state": "MERGED",
                "mergedAt": "2026-05-10T08:00:00Z",
            },
        )

        with pytest.raises(_GhError, match="exact externally settled head"):
            _record_external_settlement(
                pr_ref="6294",
                head_sha="headsha123",
                action="admin_squash_merge",
                reason="operator authorized exact-head merge",
                repo_root=tmp_path,
                repo_override=None,
                review_queue_root=None,
            )

    def test_record_external_settlement_rejects_unmerged_admin_merge(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: {
                "number": 6294,
                "url": "https://github.com/synaptent/aragora/pull/6294",
                "headRefOid": "headsha123",
                "baseRefOid": "basesha123",
                "state": "OPEN",
                "mergedAt": "",
            },
        )

        with pytest.raises(_GhError, match="require the PR to be MERGED"):
            _record_external_settlement(
                pr_ref="6294",
                head_sha="headsha123",
                action="admin_squash_merge",
                reason="operator authorized exact-head merge",
                repo_root=tmp_path,
                repo_override=None,
                review_queue_root=None,
            )

    def test_record_settlement_command_surfaces_github_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue.resolve_repo_root",
            lambda cwd: tmp_path,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._require_clean_worktree",
            lambda repo_root: None,
        )

        def _raise_gh(args: list[str]) -> None:
            raise _GhError("gh unavailable")

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", _raise_gh)
        ns = argparse.Namespace(
            review_queue_command="record-settlement",
            pr="6294",
            repo=None,
            head_sha="headsha123",
            action="admin_squash_merge",
            reason="operator authorized exact-head merge",
            review_queue_root=None,
            json=False,
        )

        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            rc = cmd_review_queue(ns)

        assert rc == 1
        assert "gh unavailable" in err_buf.getvalue()

    def test_record_settlement_post_status_targets_trusted_comment(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue.resolve_repo_root",
            lambda cwd: tmp_path,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._require_clean_worktree",
            lambda repo_root: None,
        )
        settlement_url = "https://github.example/pr/6294#issuecomment-settlement"
        status_posts: list[list[str]] = []

        def _fake_gh_json(args: list[str]) -> dict[str, Any]:
            fields = str(args[4]) if args[:4] == ["pr", "view", "6294", "--json"] else ""
            if args[:2] == ["pr", "view"] and "comments,commits" not in fields:
                return {
                    "number": 6294,
                    "url": "https://github.com/synaptent/aragora/pull/6294",
                    "headRefOid": "headsha123",
                    "baseRefOid": "basesha123",
                    "state": "OPEN",
                    "mergedAt": "",
                }
            if args[:2] == ["pr", "view"] and "comments,commits" in fields:
                return {
                    "number": 6294,
                    "url": "https://github.com/synaptent/aragora/pull/6294",
                    "headRefOid": "headsha123",
                    "commits": [{"oid": "headsha123", "committedDate": "2026-06-15T20:38:38Z"}],
                    "comments": [
                        {
                            "author": {"login": "scarmani"},
                            "authorAssociation": "OWNER",
                            "createdAt": "2026-06-15T20:39:38Z",
                            "url": settlement_url,
                            "body": (
                                "Tier-4 Human Settlement Authorization\n\n"
                                "PR: #6294\n"
                                "Exact head: headsha123\n"
                                "Authorized action: admin_squash_merge only if checks stay green.\n\n"
                                "Human-risk settlement: I accept the Tier 4 risk for this PR."
                            ),
                        }
                    ],
                }
            if args == ["api", "user"]:
                return {"login": "scarmani"}
            if args == ["repo", "view", "--json", "nameWithOwner"]:
                return {"nameWithOwner": "synaptent/aragora"}
            if args == ["api", "repos/synaptent/aragora/collaborators/scarmani/permission"]:
                return {"permission": "admin"}
            if args[:4] == [
                "api",
                "--method",
                "POST",
                "repos/synaptent/aragora/statuses/headsha123",
            ]:
                status_posts.append(args)
                return {"state": "success", "context": "aragora/human-settlement"}
            raise AssertionError(args)

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", _fake_gh_json)
        ns = argparse.Namespace(
            review_queue_command="record-settlement",
            pr="6294",
            repo=None,
            head_sha="headsha123",
            action="comment",
            reason="operator authorized exact-head human settlement",
            review_queue_root=None,
            apply_post_merge_lane_audit=False,
            post_github_status=True,
            github_status_context="aragora/human-settlement",
            json=True,
            json_output=True,
        )

        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            rc = cmd_review_queue(ns)

        payload = json.loads(out_buf.getvalue())
        assert rc == 0
        assert payload["github_status"]["target_url"] == settlement_url
        assert status_posts == [
            [
                "api",
                "--method",
                "POST",
                "repos/synaptent/aragora/statuses/headsha123",
                "-f",
                "state=success",
                "-f",
                "context=aragora/human-settlement",
                "-f",
                f"description=Settlement receipt {payload['receipt_sha256']} recorded for PR #6294",
                "-f",
                f"target_url={settlement_url}",
            ]
        ]
        ok, reason = tier4_settlement._human_settlement_status_creator_verified(
            repo_slug="synaptent/aragora",
            head_sha="headsha123",
            target_url=settlement_url,
            gh_json=lambda args: [
                {
                    "context": "aragora/human-settlement",
                    "state": "success",
                    "creator": {"login": "scarmani"},
                    "target_url": settlement_url,
                }
            ],
        )
        assert ok is True
        assert "status created by trusted settlement creator 'scarmani'" in reason

    def test_record_settlement_post_status_requires_trusted_comment_target(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue.resolve_repo_root",
            lambda cwd: tmp_path,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._require_clean_worktree",
            lambda repo_root: None,
        )
        status_posts: list[list[str]] = []

        def _fake_gh_json(args: list[str]) -> dict[str, Any]:
            fields = str(args[4]) if args[:4] == ["pr", "view", "6294", "--json"] else ""
            if args[:2] == ["pr", "view"] and "comments,commits" not in fields:
                return {
                    "number": 6294,
                    "url": "https://github.com/synaptent/aragora/pull/6294",
                    "headRefOid": "headsha123",
                    "baseRefOid": "basesha123",
                    "state": "OPEN",
                    "mergedAt": "",
                }
            if args[:2] == ["pr", "view"] and "comments,commits" in fields:
                return {
                    "number": 6294,
                    "url": "https://github.com/synaptent/aragora/pull/6294",
                    "headRefOid": "headsha123",
                    "commits": [{"oid": "headsha123", "committedDate": "2026-06-15T20:38:38Z"}],
                    "comments": [],
                }
            if args == ["api", "user"]:
                return {"login": "scarmani"}
            if args == ["repo", "view", "--json", "nameWithOwner"]:
                return {"nameWithOwner": "synaptent/aragora"}
            if args[:4] == [
                "api",
                "--method",
                "POST",
                "repos/synaptent/aragora/statuses/headsha123",
            ]:
                status_posts.append(args)
                return {"state": "success", "context": "aragora/human-settlement"}
            raise AssertionError(args)

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", _fake_gh_json)
        ns = argparse.Namespace(
            review_queue_command="record-settlement",
            pr="6294",
            repo=None,
            head_sha="headsha123",
            action="comment",
            reason="operator authorized exact-head human settlement",
            review_queue_root=None,
            apply_post_merge_lane_audit=False,
            post_github_status=True,
            github_status_context="aragora/human-settlement",
            json=True,
            json_output=True,
        )

        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = cmd_review_queue(ns)

        payload = json.loads(out_buf.getvalue())
        assert rc == 1
        assert status_posts == []
        assert payload["github_status"]["posted"] is False
        assert (
            "no trusted exact-head Tier 4 settlement comment URL found"
            in payload["github_status"]["error"]
        )
        assert "receipt written but GitHub status POST failed" in err_buf.getvalue()

    def test_record_settlement_command_records_audit_apply_failure_then_returns_1(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue.resolve_repo_root",
            lambda cwd: tmp_path,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._require_clean_worktree",
            lambda repo_root: None,
        )

        def _fake_gh_json(args: list[str]) -> dict[str, Any]:
            if args[:2] == ["pr", "view"]:
                return {
                    "number": 6294,
                    "url": "https://github.com/synaptent/aragora/pull/6294",
                    "headRefOid": "headsha123",
                    "baseRefOid": "basesha123",
                    "state": "MERGED",
                    "mergedAt": "2026-05-10T08:00:00Z",
                }
            if args == ["api", "user"]:
                return {"login": "an0mium"}
            raise AssertionError(args)

        def _audit_failure(
            pr_number: int,
            *,
            repo_root: Path | None = None,
            apply: bool = False,
        ) -> dict[str, Any]:
            assert pr_number == 6294
            assert apply is True
            return {
                "finding_count": 1,
                "resolved_count": 0,
                "blocked_reason": "merge_commit_mismatch",
                "operator_apply_command": "python3 scripts/resolve_lane_conflicts.py --apply ...",
                "receipt_paths": [],
                "github_state": {"state": "MERGED", "mergeCommit": "merge-sha"},
                "audit_ok": False,
                "audit_applied": False,
                "audit_error": "merge_commit_mismatch",
            }

        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", _fake_gh_json)
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue.run_post_merge_lane_audit",
            _audit_failure,
        )
        ns = argparse.Namespace(
            review_queue_command="record-settlement",
            pr="6294",
            repo=None,
            head_sha="headsha123",
            action="admin_squash_merge",
            reason="operator authorized exact-head merge",
            review_queue_root=None,
            apply_post_merge_lane_audit=True,
            json=True,
        )

        out_buf = io.StringIO()
        with redirect_stdout(out_buf):
            rc = cmd_review_queue(ns)

        payload = json.loads(out_buf.getvalue())
        assert rc == 1
        assert payload["post_merge_lane_audit_failed"] is True
        assert payload["post_merge_lane_audit"]["blocked_reason"] == "merge_commit_mismatch"
        assert Path(payload["receipt_path"]).is_file()

    def test_build_command_renders_table(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: [_make_pr(number=1)],
        )
        ns = argparse.Namespace(
            review_queue_command="build",
            limit=10,
            ready_only=False,
            include_parked=False,
            json=False,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_review_queue(ns)
        assert rc == 0
        out = buf.getvalue()
        assert "Review queue" in out
        assert "advisory only" in out

    def test_build_command_surfaces_active_auto_handle_drift_alerts(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: [_make_pr(number=1)],
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue.AutoHandleCalibrationStore.list_active_alerts",
            lambda self, limit=3: [
                AutoHandleDriftAlert(
                    alert_id="alert-1",
                    auto_handle_path="fire_and_forget",
                    decision_class="tier=1|lanes=1|files=1|scope=aragora",
                    previous_success_rate=1.0,
                    current_success_rate=0.5,
                    window_days=30,
                    min_samples=20,
                    min_success_rate=0.95,
                    drift_threshold=0.05,
                    detected_at=0.0,
                    remediation_action="require_human_review_for_class",
                )
            ],
        )
        ns = argparse.Namespace(
            review_queue_command="build",
            limit=10,
            ready_only=False,
            include_parked=False,
            json=False,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_review_queue(ns)
        assert rc == 0
        out = buf.getvalue()
        assert "ACTIVE AUTO-HANDLE DRIFT ALERTS" in out
        assert "fire_and_forget" in out

    def test_build_command_warns_when_calibration_store_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: [_make_pr(number=1)],
        )

        def _raise_store_error(self, limit=3):
            raise RuntimeError("db unavailable")

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue.AutoHandleCalibrationStore.list_active_alerts",
            _raise_store_error,
        )
        ns = argparse.Namespace(
            review_queue_command="build",
            limit=10,
            ready_only=False,
            include_parked=False,
            json=False,
        )
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            rc = cmd_review_queue(ns)
        assert rc == 0
        assert "warning: auto-handle calibration unavailable: db unavailable" in err_buf.getvalue()

    def test_build_command_json_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: [_make_pr(number=1), _make_pr(number=2)],
        )
        ns = argparse.Namespace(
            review_queue_command="build",
            limit=10,
            ready_only=False,
            include_parked=False,
            json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_review_queue(ns)
        assert rc == 0
        payload = json.loads(buf.getvalue())
        assert isinstance(payload, list)
        assert {item["number"] for item in payload} == {1, 2}

    def test_packet_command_json_output(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda args: _make_pr(number=42, files=["aragora/cli/main.py"]),
        )
        ns = argparse.Namespace(
            review_queue_command="packet",
            pr="42",
            repo=None,
            json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_review_queue(ns)
        assert rc == 0
        payload = json.loads(buf.getvalue())
        assert payload["pr_number"] == 42
        assert payload["advisory_only"] is True
        assert payload["settlement_note"] == ADVISORY_NOTE

    def test_merge_packet_json_output_with_queue_pressure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        queue = [_classify_pr(_make_pr(number=i)) for i in range(1, MODEL_REVIEW_QUEUE_CAP + 2)]

        def _fake_build_packet(
            pr_ref: str,
            *,
            repo_override: str | None,
            execute_reviewers: bool = False,
            ignore_own_quorum_check: bool = False,
        ) -> ReviewPacket:
            return ReviewPacket(
                pr_number=int(pr_ref),
                title="bounded docs",
                url=f"https://github.com/synaptent/aragora/pull/{pr_ref}",
                head_sha="headsha",
                base_sha="basesha",
                author="codex",
                is_draft=False,
                additions=1,
                deletions=1,
                changed_files=1,
                queue_bucket="ready_now",
                touched_subsystems=["docs"],
                high_risk_paths_touched=[],
                validation=[],
                checks_summary="5/5 green",
                risk_flags=[],
                machine_recommendation="approve_candidate",
                machine_recommendation_reason="clean",
                packet_sha="sha256:test",
                generated_at="2026-04-28T00:00:00+00:00",
                merge_state_status="CLEAN",
                model_review_quorum={
                    "tier": 0,
                    "tier_name": "tier_0_docs_tests_status",
                    "status": "satisfied",
                    "verdict": "admin_squash_allowed",
                    "admin_squash_allowed": True,
                    "requires_human_risk_settlement": False,
                    "unresolved_dissent": False,
                    "reviewer_signals": [],
                    "dogfood_evidence": [{"reviewer_id": "claude"}],
                    "counted_reviewer_ids": ["claude"],
                    "reasons": ["docs/tests/status-only change"],
                },
            )

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_queue",
            lambda limit, repo_override=None: queue,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_packet",
            _fake_build_packet,
        )
        ns = argparse.Namespace(
            review_queue_command="merge-packet",
            pr=[],
            repo=None,
            limit=10,
            execute_reviewers=False,
            json=True,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cmd_review_queue(ns)
        assert rc == 0
        payload = json.loads(buf.getvalue())
        assert payload["queue_pressure"]["active"] is True
        assert payload["queue_pressure"]["scope"] == "open_pr_queue"
        assert payload["admin_squash_order"] == list(range(1, MODEL_REVIEW_QUEUE_CAP + 2))
        assert payload["entries"][0]["verdict"] == "admin_squash_allowed"

    def test_merge_packet_json_reports_transport_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_transport(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise _GhError(
                "gh pr view 1 --json number failed: error connecting to api.github.com\n"
                "check your internet connection or https://githubstatus.com"
            )

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_merge_authorization_packet",
            fail_transport,
        )
        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._gh_json",
            lambda _args: (_ for _ in ()).throw(_GhError("REST fallback unavailable")),
        )
        ns = argparse.Namespace(
            review_queue_command="merge-packet",
            pr=["1"],
            repo="synaptent/aragora",
            review_queue_root=None,
            limit=30,
            execute_reviewers=False,
            ignore_own_quorum_check=False,
            json=True,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cmd_review_queue(ns)

        assert rc == 1
        assert stderr.getvalue() == ""
        payload = json.loads(stdout.getvalue())
        assert payload["status"] == "transport_blocked"
        assert payload["transport_blocked"] is True
        assert payload["preserve_no_mutate"] is True
        assert payload["error_kind"] == "github_transport"
        assert payload["command"] == "review-queue merge-packet"
        assert payload["repo"] == "synaptent/aragora"
        assert payload["pr_refs"] == ["1"]
        assert payload["not_ready"] == [1]
        assert payload["entries"] == []
        assert payload["admin_squash_order"] == []
        assert payload["rest_fallback"]["available"] is False
        assert "do not mark ready" in payload["next_prompt"]

    def test_merge_packet_json_reports_graphql_rate_limit_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_rate_limit(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise _GhError(
                "gh pr view 7841 --json number failed: GraphQL: "
                "API rate limit already exceeded for user ID 33477136."
            )

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_merge_authorization_packet",
            fail_rate_limit,
        )
        ns = argparse.Namespace(
            review_queue_command="merge-packet",
            pr=["7841"],
            repo=None,
            review_queue_root=None,
            limit=30,
            execute_reviewers=False,
            ignore_own_quorum_check=False,
            json=True,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cmd_review_queue(ns)

        assert rc == 1
        assert stderr.getvalue() == ""
        payload = json.loads(stdout.getvalue())
        assert payload["status"] == "transport_blocked"
        assert payload["error_kind"] == "github_transport"
        assert payload["retryable"] is True
        assert payload["pr_refs"] == ["7841"]
        assert payload["not_ready"] == [7841]
        assert "API rate limit already exceeded" in payload["error"]

    def test_merge_packet_transport_blocked_includes_rest_fallback_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_rate_limit(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise _GhError(
                "gh pr view 8313 --json number failed: GraphQL: "
                "API rate limit already exceeded for user ID 33477136."
            )

        def rest_json(args: list[str]) -> dict[str, Any] | list[dict[str, Any]]:
            if args == ["api", "repos/synaptent/aragora/pulls/8313"]:
                return {
                    "number": 8313,
                    "title": "fix(proof): report capability matrix generator failures",
                    "html_url": "https://github.com/synaptent/aragora/pull/8313",
                    "state": "open",
                    "draft": True,
                    "head": {"ref": "codex/proof-matrix-failures", "sha": "head8313"},
                    "base": {"ref": "main", "sha": "base"},
                    "mergeable": True,
                    "mergeable_state": "clean",
                    "updated_at": "2026-06-12T00:00:00Z",
                    "changed_files": 2,
                }
            if args == ["api", "repos/synaptent/aragora/pulls/8313/files?per_page=100"]:
                return [
                    {"filename": "scripts/generate_capability_matrix.py"},
                    {"filename": "tests/scripts/test_generate_capability_matrix.py"},
                ]
            if args == [
                "api",
                "repos/synaptent/aragora/commits/head8313/check-runs?per_page=100",
            ]:
                return {
                    "check_runs": [
                        {
                            "name": "lint",
                            "status": "completed",
                            "conclusion": "success",
                            "html_url": "https://example.test/lint",
                            "check_suite": {"app": {"name": "GitHub Actions"}},
                        },
                        {
                            "name": "Tests / test-fast",
                            "status": "queued",
                            "conclusion": "",
                            "html_url": "https://example.test/tests",
                            "check_suite": {"app": {"name": "GitHub Actions"}},
                        },
                    ]
                }
            raise AssertionError(args)

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_merge_authorization_packet",
            fail_rate_limit,
        )
        monkeypatch.setattr("aragora.cli.commands.review_queue._gh_json", rest_json)
        ns = argparse.Namespace(
            review_queue_command="merge-packet",
            pr=["8313"],
            repo="synaptent/aragora",
            review_queue_root=None,
            limit=1,
            execute_reviewers=False,
            ignore_own_quorum_check=False,
            json=True,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cmd_review_queue(ns)

        assert rc == 1
        assert stderr.getvalue() == ""
        payload = json.loads(stdout.getvalue())
        assert payload["status"] == "transport_blocked"
        assert payload["transport_blocked"] is True
        assert payload["preserve_no_mutate"] is True
        assert payload["entries"] == []
        fallback = payload["rest_fallback"]
        assert fallback["available"] is True
        assert fallback["mutation_forbidden"] is True
        assert fallback["pr"]["number"] == 8313
        assert fallback["pr"]["head_sha"] == "head8313"
        assert fallback["pr"]["merge_state_status"] == "CLEAN"
        assert fallback["files"] == [
            "scripts/generate_capability_matrix.py",
            "tests/scripts/test_generate_capability_matrix.py",
        ]
        assert fallback["check_runs_available"] is True
        assert fallback["check_runs_summary"]["total"] == 2
        assert fallback["check_runs_summary"]["non_green_count"] == 1

    def test_merge_packet_json_keeps_non_transport_errors_on_stderr(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_permission(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise _GhError("gh pr view 1 failed: GraphQL: Resource not accessible by integration")

        monkeypatch.setattr(
            "aragora.cli.commands.review_queue._build_merge_authorization_packet",
            fail_permission,
        )
        ns = argparse.Namespace(
            review_queue_command="merge-packet",
            pr=["1"],
            repo="synaptent/aragora",
            review_queue_root=None,
            limit=30,
            execute_reviewers=False,
            ignore_own_quorum_check=False,
            json=True,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = cmd_review_queue(ns)

        assert rc == 1
        assert stdout.getvalue() == ""
        assert "Resource not accessible by integration" in stderr.getvalue()

    def test_act_command_requires_reason_for_request_changes(self) -> None:
        ns = argparse.Namespace(
            review_queue_command="act",
            pr="42",
            repo=None,
            approve=False,
            request_changes=True,
            defer=False,
            reason="",
            json=False,
        )
        rc = cmd_review_queue(ns)
        assert rc == 2


def test_quorum_evidence_is_tier4_merge_authority():
    """quorum_evidence.py (the evidence composer/classifier) must classify Tier-4."""
    from aragora.cli.commands.review_queue import (
        TIER_4_PREFIXES,
        _classify_model_review_tier,
        _matches_prefix,
    )

    assert "aragora/swarm/quorum_evidence.py" in TIER_4_PREFIXES
    assert _matches_prefix("aragora/swarm/quorum_evidence.py", TIER_4_PREFIXES) is True
    # Behavioral: a changeset touching it classifies Tier 4 (not auto-settleable Tier-2).
    tier, _verdict, _reason = _classify_model_review_tier(["aragora/swarm/quorum_evidence.py"])
    assert tier == 4
    # And the serialized mirror used by the merge train stays in sync (CI guard).
    from scripts.tier4_merge_train import SERIALIZED_TIER4_PREFIXES

    assert "aragora/swarm/quorum_evidence.py" in SERIALIZED_TIER4_PREFIXES


def test_tier_requirement_is_tiered_for_low_tiers():
    # Tiered gate: Tier 1-2 settle on ONE western-frontier model signal (claude/
    # openai) + dogfood; Tier 3-4 retain the full two-family gate + settlement.
    from aragora.cli.commands.review_queue import _tier_requirement

    for tier in (1, 2):
        req = _tier_requirement(tier)
        assert req["required_model_signals"] == 1, tier
        assert req["requires_western_frontier_signal"] is True, tier
        assert req["requires_adversarial_dogfood"] is True, tier
        assert req["requires_human_risk_settlement"] is False, tier

    for tier in (3, 4):
        req = _tier_requirement(tier)
        assert req["required_model_signals"] == 2, tier
        assert req["requires_western_frontier_signal"] is False, tier
        assert req["requires_human_risk_settlement"] is True, tier

    tier0 = _tier_requirement(0)
    assert tier0["required_model_signals"] == 1
    assert tier0["requires_western_frontier_signal"] is False


def test_western_frontier_families_match_quorum_evidence():
    # The WF allowlist now has a SINGLE canonical definition in quorum_evidence,
    # re-exported by review_queue. Assert object IDENTITY (not just equality) so the
    # merge-gate and the auto-settle path can never drift — the duplication that the
    # old parity guard merely policed is gone (claude #8507 P2).
    from aragora.cli.commands.review_queue import WESTERN_FRONTIER_FAMILIES as rq_wf
    from aragora.swarm.quorum_evidence import WESTERN_FRONTIER_FAMILIES as qe_wf

    assert rq_wf is qe_wf
    assert rq_wf == frozenset({"claude", "openai"})


def test_western_frontier_signal_set_is_subset_of_counted():
    # The WF check derives from model-review signals ONLY (empty dogfood), while
    # signal_count derives from the dogfood-inclusive set. Pin the structural
    # invariant claude #8507 P2 relies on: the signal-only set is always a subset of
    # the counted set, so a WF signal that satisfies the requirement is also counted —
    # the two derivations can never grant WF without counting it.
    from aragora.cli.commands.review_queue import _counted_model_reviewer_ids

    reviewer_signals = [{"model_family": "claude"}]
    dogfood_evidence = [{"model_family": "grok"}]

    signal_only = set(_counted_model_reviewer_ids(reviewer_signals, []))
    counted = set(_counted_model_reviewer_ids(reviewer_signals, dogfood_evidence))

    assert signal_only == {"claude"}
    assert counted == {"claude", "grok"}
    assert signal_only <= counted  # dogfood only ADDS ids; never removes a signal
    assert "grok" not in signal_only  # dogfood-only id cannot satisfy the WF check


def test_tier_two_lone_non_western_frontier_signal_omits_misleading_count():
    # A lone grok signal meets the 1-signal count at Tier 2 but grok is not a
    # western-frontier family. The real blocker is the WF requirement, so the
    # reasons must NOT print the self-contradictory "1/1 signal(s)" line; they
    # must name the western-frontier requirement instead.
    pr = _make_pr(files=["aragora/cli/commands/swarm.py"])
    pr["comments"] = [
        {
            "author": {"login": "an0mium"},
            "body": "## Grok independent model review\nVerdict: approve.",
        },
    ]
    quorum = _build_model_review_quorum(
        pr=pr,
        files=["aragora/cli/commands/swarm.py"],
        protocol={"status": "metadata_heuristic"},
        machine_recommendation="approve_candidate",
        has_pending=False,
        has_failures=False,
    )
    assert quorum["tier"] == 2
    assert quorum["counted_reviewer_ids"] == ["grok"]
    assert quorum["has_western_frontier_signal"] is False
    assert quorum["status"] == "needs_model_review_quorum"
    reasons = quorum["reasons"]
    assert any("western-frontier" in r for r in reasons)
    assert not any("signal(s)" in r for r in reasons)


@pytest.fixture(autouse=True)
def _enable_tiered_gate(monkeypatch):
    # This module exercises the opt-in tiered merge gate, so enable it by default.
    # The production default is OFF (strict 2-distinct-family); the strict-default
    # test below sets ARAGORA_ENABLE_TIERED_MERGE_GATE="0" explicitly.
    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "1")


def test_tier_requirement_strict_when_flag_off(monkeypatch):
    # Production default: the tiered relaxation is OFF, so Tier 1-2 keep the full
    # two-signal bar and impose no western-frontier requirement. Tier 0 preserves
    # current-main one-signal behavior.
    from aragora.cli.commands.review_queue import _tier_requirement

    monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", "0")
    tier0 = _tier_requirement(0)
    assert tier0["required_model_signals"] == 1
    assert tier0["requires_western_frontier_signal"] is False
    for tier in (1, 2):
        req = _tier_requirement(tier)
        assert req["required_model_signals"] == 2, tier
        assert req["requires_western_frontier_signal"] is False, tier


def test_tier_requirement_matches_shared_rule(monkeypatch):
    # The merge gate (_tier_requirement) and the shared tier_quorum_rule (used by
    # the auto-settle path's has_supportive_quorum) must agree on signals + WF for
    # every tier under both flag states, so the two gate halves cannot drift.
    from aragora.cli.commands.review_queue import _tier_requirement
    from aragora.swarm.quorum_evidence import tier_quorum_rule

    for flag in ("0", "1"):
        monkeypatch.setenv("ARAGORA_ENABLE_TIERED_MERGE_GATE", flag)
        for tier in (0, 1, 2, 3, 4):
            req = _tier_requirement(tier)
            rule = tier_quorum_rule(tier, tiered_gate=(flag == "1"))
            assert req["required_model_signals"] == rule.required_signals, (tier, flag)
            assert req["requires_western_frontier_signal"] == rule.requires_western_frontier, (
                tier,
                flag,
            )
            assert req["western_only_counted"] == rule.western_only_counted, (tier, flag)
            assert req["requires_at_least_one_western"] == rule.requires_at_least_one_western, (
                tier,
                flag,
            )
