from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI

os.environ.setdefault("ARAGORA_USE_SECRETS_MANAGER", "0")

from aragora.server.fastapi.routes import swarm_status
from aragora.swarm.preflight import PreflightReceipt
from aragora.swarm.shift_ledger import ShiftLedger


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def test_swarm_status_summary_counts_deliverables_as_success(tmp_path: Path) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    _write_jsonl(
        metrics_path,
        [
            {
                "timestamp": "2026-04-14T02:20:00Z",
                "issue_number": 101,
                "terminal_class": "deliverable_pr_created",
                "outcome": "completed",
                "elapsed_seconds": 12,
            },
            {
                "timestamp": "2026-04-14T02:21:00Z",
                "issue_number": 102,
                "terminal_class": "success_pr_created",
                "outcome": "completed",
                "elapsed_seconds": 18,
            },
        ],
    )

    summary = swarm_status.swarm_status_summary(metrics_path=metrics_path)

    assert summary["status"] == "active"
    assert summary["total_ticks"] == 2
    assert summary["unique_issues_attempted"] == 2
    assert summary["unique_issues_succeeded"] == 2
    assert summary["success_rate"] == 1.0
    assert summary["tick_success_rate"] == 1.0
    assert summary["terminal_class_distribution"] == {
        "deliverable_pr_created": 1,
        "success_pr_created": 1,
    }
    assert summary["latest_tick"]["issue_number"] == 102


def test_swarm_status_summary_uses_issue_truth_for_success_rate(tmp_path: Path) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    _write_jsonl(
        metrics_path,
        [
            {
                "timestamp": "2026-04-14T02:20:00Z",
                "issue_number": 101,
                "terminal_class": "blocked_auth_failure",
                "outcome": "needs_human",
                "elapsed_seconds": 12,
            },
            {
                "timestamp": "2026-04-14T02:21:00Z",
                "issue_number": 101,
                "terminal_class": "deliverable_pr_created",
                "outcome": "completed",
                "elapsed_seconds": 18,
            },
        ],
    )

    summary = swarm_status.swarm_status_summary(metrics_path=metrics_path)

    assert summary["unique_issues_attempted"] == 1
    assert summary["unique_issues_succeeded"] == 1
    assert summary["success_rate"] == 1.0
    assert summary["tick_success_rate"] == 0.5
    assert summary["recent_blockers"] == [
        {
            "issue_number": 101,
            "terminal_class": "blocked_auth_failure",
            "failure_reason": None,
            "blocker_kind": None,
            "blocker_evidence": None,
            "issue_title": None,
        }
    ]


def test_swarm_status_summary_surfaces_compact_blocker_evidence(tmp_path: Path) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    _write_jsonl(
        metrics_path,
        [
            {
                "timestamp": "2026-04-14T02:20:00Z",
                "issue_number": 201,
                "terminal_class": "blocked_auth_failure",
                "outcome": "needs_human",
                "failure_reason": "auth",
                "blocker_kind": "credentials",
                "blocker_evidence": "  API key missing   for Anthropic provider  " + ("x" * 260),
                "issue_title": "Repair auth preflight",
                "elapsed_seconds": 12,
            }
        ],
    )

    summary = swarm_status.swarm_status_summary(metrics_path=metrics_path)

    assert summary["recent_blockers"] == [
        {
            "issue_number": 201,
            "terminal_class": "blocked_auth_failure",
            "failure_reason": "auth",
            "blocker_kind": "credentials",
            "blocker_evidence": "API key missing for Anthropic provider " + ("x" * 198) + "...",
            "issue_title": "Repair auth preflight",
        }
    ]


def test_swarm_status_summary_prefers_ledger_truth_when_present(tmp_path: Path) -> None:
    metrics_path = tmp_path / "boss_metrics.jsonl"
    _write_jsonl(metrics_path, [])
    ledger = ShiftLedger(path=tmp_path / ".aragora" / "proof_first_shift" / "shift_ledger.jsonl")
    ledger.record_shift_start(
        shift_id="shift-1",
        max_hours=12.0,
        benchmark_mode="hybrid",
        queue_size=0,
    )
    ledger.record_cycle_tick(
        queue_size=0,
        open_prs=0,
        boss_running=False,
        merge_running=True,
        benchmark_fresh=True,
        actions=["steady_state"],
        stop_reason="completed",
    )
    ledger.record_pr_merged(pr_number=5857)
    ledger.record_shift_stop(
        shift_id="shift-1",
        reason="completed",
        cycles=1,
        duration_seconds=45.0,
    )

    summary = swarm_status.swarm_status_summary(metrics_path=metrics_path, repo_root=tmp_path)

    assert summary["status"] == "active"
    assert summary["ledger_status"]["current_benchmark_fresh"] is True
    assert summary["queue_depth"] == 0
    assert summary["boss_running"] is False
    assert summary["merge_running"] is True
    assert summary["last_stop_reason"] == "completed"
    assert summary["prs_merged_recent"] == 1
    assert summary["merged_pr_numbers"] == [5857]


def test_preflight_check_returns_receipt_dict() -> None:
    fake_receipt = MagicMock()
    fake_receipt.to_dict.return_value = {"receipt_id": "receipt-1", "passed": True}

    with (
        patch(
            "aragora.swarm.credential_envelope.CredentialEnvelope.from_environment",
            return_value=object(),
        ) as from_environment,
        patch("aragora.swarm.preflight.run_preflight", return_value=fake_receipt) as run_preflight,
    ):
        result = swarm_status.preflight_check(
            agent="codex",
            base_ref="origin/main",
            skip_publication=False,
        )

    assert result == {"receipt_id": "receipt-1", "passed": True}
    from_environment.assert_called_once()
    assert run_preflight.call_args.kwargs["repo_root"] == Path.cwd()
    assert run_preflight.call_args.kwargs["agent"] == "codex"
    assert run_preflight.call_args.kwargs["base_ref"] == "origin/main"
    assert run_preflight.call_args.kwargs["skip_publication"] is False


def test_list_preflight_receipts_returns_empty_without_receipt_dir(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    assert swarm_status.list_preflight_receipts() == []


def test_list_preflight_receipts_reads_valid_receipts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    receipt_dir = tmp_path / ".aragora" / "receipts" / "preflight"
    receipt_dir.mkdir(parents=True)

    receipt = PreflightReceipt(
        receipt_id="preflight-scratch-1",
        envelope_seal="seal-1",
        repo_root=str(tmp_path),
        check_type="scratch_validation",
        started_at="2026-04-14T02:20:00Z",
        finished_at="2026-04-14T02:21:00Z",
        passed=True,
        cache_key="scratch-key",
        ttl_seconds=600,
        expires_at="2026-04-14T02:31:00Z",
    )
    (receipt_dir / "receipt-ok.json").write_text(
        json.dumps(receipt.to_dict()),
        encoding="utf-8",
    )
    (receipt_dir / "receipt-bad.json").write_text("{not-json", encoding="utf-8")

    receipts = swarm_status.list_preflight_receipts()

    assert receipts == [
        {
            "receipt_id": "preflight-scratch-1",
            "check_type": "scratch_validation",
            "passed": True,
            "started_at": "2026-04-14T02:20:00Z",
            "finished_at": "2026-04-14T02:21:00Z",
            "expires_at": "2026-04-14T02:31:00Z",
            "cache_key": "scratch-key",
        }
    ]


def test_register_routes_adds_swarm_status_endpoints() -> None:
    app = FastAPI()

    swarm_status.register_routes(app)

    # FastAPI 0.138+ stores included routers behind an internal wrapper, so
    # direct app.routes path inspection is version- and import-order-dependent
    # (the '_IncludedRouter has no attribute path' shard failure). Assert the
    # supported route-lookup contract instead.
    assert str(app.url_path_for("get_swarm_status")) == "/api/v1/swarm/status"
    assert str(app.url_path_for("run_swarm_preflight")) == "/api/v1/swarm/preflight"
    assert str(app.url_path_for("get_preflight_receipts")) == "/api/v1/swarm/preflight/receipts"


# ---------------------------------------------------------------------------
# Round 2026-04-30c Phase C: B0 publication freshness fields surfaced to the
# FastAPI swarm-status route.  Closes the Optional Fix C from the #6798
# design note: dashboard consumers can now distinguish "ledger says fresh"
# (the existing ``benchmark_fresh`` field, which reads from the ledger
# last-tick payload) from "the on-disk artifact actually IS fresh"
# (``current_benchmark_fresh`` populated by ``_detect_benchmark_freshness``).
# ---------------------------------------------------------------------------


def _write_b0_artifact(repo_root: Path, generated_at: str | None) -> Path:
    """Write a stub B0 truth artifact at the canonical relative path."""
    target = (
        repo_root
        / "docs"
        / "status"
        / "generated"
        / "benchmark_scorecards"
        / "tw-01-bounded-execution-v1"
        / "latest.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {"corpus_id": "tw-01-bounded-execution-v1", "revision": 3}
    if generated_at is not None:
        payload["generated_at"] = generated_at
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_swarm_status_no_data_includes_benchmark_freshness_keys(tmp_path: Path) -> None:
    """Even on the no-data path the three new keys must be present (None)."""
    metrics_path = tmp_path / "boss_metrics.jsonl"
    summary = swarm_status.swarm_status_summary(metrics_path=metrics_path, repo_root=tmp_path)
    assert summary["status"] == "no_data"
    assert summary["current_benchmark_fresh"] is None
    assert summary["current_benchmark_age_hours"] is None
    assert summary["current_benchmark_generated_at"] is None


def test_swarm_status_active_with_fresh_b0_artifact(tmp_path: Path) -> None:
    """Active path with a recent B0 artifact reports current_benchmark_fresh=True."""
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    _write_b0_artifact(tmp_path, recent)

    metrics_path = tmp_path / "boss_metrics.jsonl"
    _write_jsonl(
        metrics_path,
        [{"timestamp": "2026-04-30T01:00:00Z", "terminal_class": "deliverable_pr_created"}],
    )

    summary = swarm_status.swarm_status_summary(metrics_path=metrics_path, repo_root=tmp_path)
    assert summary["status"] == "active"
    assert summary["current_benchmark_fresh"] is True
    assert summary["current_benchmark_age_hours"] is not None
    assert 0 <= summary["current_benchmark_age_hours"] <= 2.0
    assert summary["current_benchmark_generated_at"] == recent


def test_swarm_status_active_with_stale_b0_artifact(tmp_path: Path) -> None:
    """Active path with a stale B0 artifact reports current_benchmark_fresh=False."""
    from datetime import datetime, timedelta, timezone

    stale = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat().replace("+00:00", "Z")
    _write_b0_artifact(tmp_path, stale)

    metrics_path = tmp_path / "boss_metrics.jsonl"
    _write_jsonl(
        metrics_path,
        [{"timestamp": "2026-04-30T01:00:00Z", "terminal_class": "deliverable_pr_created"}],
    )

    summary = swarm_status.swarm_status_summary(metrics_path=metrics_path, repo_root=tmp_path)
    assert summary["status"] == "active"
    assert summary["current_benchmark_fresh"] is False
    assert summary["current_benchmark_age_hours"] is not None
    assert summary["current_benchmark_age_hours"] >= 24.0


def test_swarm_status_active_with_missing_b0_artifact(tmp_path: Path) -> None:
    """Active path with no B0 artifact at all reports None for all freshness keys.

    A missing artifact is its own degraded state; we don't synthesise a
    boolean from absent data.
    """
    metrics_path = tmp_path / "boss_metrics.jsonl"
    _write_jsonl(
        metrics_path,
        [{"timestamp": "2026-04-30T01:00:00Z", "terminal_class": "deliverable_pr_created"}],
    )

    summary = swarm_status.swarm_status_summary(metrics_path=metrics_path, repo_root=tmp_path)
    assert summary["status"] == "active"
    assert summary["current_benchmark_fresh"] is None
    assert summary["current_benchmark_age_hours"] is None
    assert summary["current_benchmark_generated_at"] is None


def test_swarm_status_legacy_benchmark_fresh_field_preserved(tmp_path: Path) -> None:
    """The legacy ``benchmark_fresh`` field (ledger-driven) is kept side-by-side
    with the new artifact-driven fields. Callers that were reading
    ``benchmark_fresh`` continue to work; callers that want artifact-grounded
    truth read ``current_benchmark_fresh``.
    """
    metrics_path = tmp_path / "boss_metrics.jsonl"
    _write_jsonl(
        metrics_path,
        [{"timestamp": "2026-04-30T01:00:00Z", "terminal_class": "deliverable_pr_created"}],
    )

    summary = swarm_status.swarm_status_summary(metrics_path=metrics_path, repo_root=tmp_path)
    # Legacy field still in the payload, alongside the new ones.
    assert "benchmark_fresh" in summary
    assert "current_benchmark_fresh" in summary
    assert "current_benchmark_age_hours" in summary
    assert "current_benchmark_generated_at" in summary


# ---------------------------------------------------------------------------
# Observer truth on FastAPI sibling surface — closes the Do-now item from
# docs/status/NEXT_STEPS_CANONICAL.md ("swarm shift-status AND sibling
# operator surfaces report whether the observer itself is dirty, ahead, or
# behind origin/main").  The FastAPI route already exposed benchmark
# freshness; this round adds the observer-state keys so that dashboards
# consuming /api/v1/swarm/status can distinguish a real product regression
# from a stale or dirty observer checkout without shell forensics.
# ---------------------------------------------------------------------------


def test_swarm_status_no_data_includes_observer_state_when_clean(tmp_path: Path) -> None:
    """No-data path: observer keys flow through when the helper returns data."""
    metrics_path = tmp_path / "boss_metrics.jsonl"
    with patch(
        "aragora.server.fastapi.routes.swarm_status._detect_observer_state",
        return_value={
            "observer_branch": "main",
            "observer_head": "abc123",
            "observer_origin_main_head": "abc123",
            "observer_behind_origin_main": 0,
            "observer_ahead_of_origin_main": 0,
            "observer_has_uncommitted_changes": False,
        },
    ):
        summary = swarm_status.swarm_status_summary(
            metrics_path=metrics_path,
            repo_root=tmp_path,
        )

    assert summary["status"] == "no_data"
    assert summary["observer_branch"] == "main"
    assert summary["observer_head"] == "abc123"
    assert summary["observer_origin_main_head"] == "abc123"
    assert summary["observer_behind_origin_main"] == 0
    assert summary["observer_ahead_of_origin_main"] == 0
    assert summary["observer_has_uncommitted_changes"] is False
    assert "observer_warning" not in summary


def test_swarm_status_active_with_dirty_observer_surfaces_warning(tmp_path: Path) -> None:
    """Active path: a dirty observer flows through to observer_warning."""
    metrics_path = tmp_path / "boss_metrics.jsonl"
    _write_jsonl(
        metrics_path,
        [{"timestamp": "2026-05-15T16:31:15Z", "terminal_class": "deliverable_pr_created"}],
    )

    with patch(
        "aragora.server.fastapi.routes.swarm_status._detect_observer_state",
        return_value={
            "observer_branch": "main",
            "observer_head": "deadbeef",
            "observer_origin_main_head": "deadbeef",
            "observer_behind_origin_main": 0,
            "observer_ahead_of_origin_main": 0,
            "observer_has_uncommitted_changes": True,
            "observer_warning": "observer checkout is dirty checkout",
        },
    ):
        summary = swarm_status.swarm_status_summary(
            metrics_path=metrics_path,
            repo_root=tmp_path,
        )

    assert summary["status"] == "active"
    assert summary["observer_has_uncommitted_changes"] is True
    assert summary["observer_warning"] == "observer checkout is dirty checkout"


def test_swarm_status_active_with_diverged_observer_reports_ahead_behind(
    tmp_path: Path,
) -> None:
    """Active path: an observer that diverged from origin/main reports both counts."""
    metrics_path = tmp_path / "boss_metrics.jsonl"
    _write_jsonl(
        metrics_path,
        [{"timestamp": "2026-05-15T16:31:15Z", "terminal_class": "deliverable_pr_created"}],
    )

    with patch(
        "aragora.server.fastapi.routes.swarm_status._detect_observer_state",
        return_value={
            "observer_branch": "founder-notes",
            "observer_head": "0000",
            "observer_origin_main_head": "1111",
            "observer_behind_origin_main": 12,
            "observer_ahead_of_origin_main": 3,
            "observer_has_uncommitted_changes": False,
            "observer_warning": (
                "observer checkout is 12 behind origin/main, 3 ahead of origin/main"
            ),
        },
    ):
        summary = swarm_status.swarm_status_summary(
            metrics_path=metrics_path,
            repo_root=tmp_path,
        )

    assert summary["observer_branch"] == "founder-notes"
    assert summary["observer_behind_origin_main"] == 12
    assert summary["observer_ahead_of_origin_main"] == 3
    assert "12 behind" in summary["observer_warning"]
    assert "3 ahead" in summary["observer_warning"]


def test_swarm_status_no_observer_state_when_helper_returns_empty(tmp_path: Path) -> None:
    """A sandboxed root with no git metadata yields no observer keys; the
    route still returns valid JSON for both no-data and active paths."""
    metrics_path = tmp_path / "boss_metrics.jsonl"
    with patch(
        "aragora.server.fastapi.routes.swarm_status._detect_observer_state",
        return_value={},
    ):
        no_data_summary = swarm_status.swarm_status_summary(
            metrics_path=metrics_path,
            repo_root=tmp_path,
        )

    assert no_data_summary["status"] == "no_data"
    for key in (
        "observer_branch",
        "observer_head",
        "observer_origin_main_head",
        "observer_behind_origin_main",
        "observer_ahead_of_origin_main",
        "observer_has_uncommitted_changes",
        "observer_warning",
    ):
        assert key not in no_data_summary

    _write_jsonl(
        metrics_path,
        [{"timestamp": "2026-05-15T16:31:15Z", "terminal_class": "deliverable_pr_created"}],
    )
    with patch(
        "aragora.server.fastapi.routes.swarm_status._detect_observer_state",
        return_value={},
    ):
        active_summary = swarm_status.swarm_status_summary(
            metrics_path=metrics_path,
            repo_root=tmp_path,
        )

    assert active_summary["status"] == "active"
    for key in (
        "observer_branch",
        "observer_head",
        "observer_origin_main_head",
        "observer_behind_origin_main",
        "observer_ahead_of_origin_main",
        "observer_has_uncommitted_changes",
        "observer_warning",
    ):
        assert key not in active_summary
