"""Who may act on merge-packet's optional-only ``UNSTABLE`` proof.

The packet's own admin-squash verdict for an ``UNSTABLE`` PR stays as on main
(only a verified cancellation receipt admits it), so packet consumers such as
the value drain and settle_one keep refusing such a PR. Only the unattended
Tier 0-2 executors read the separate ``optional_only_unstable_executor_proof``
field, match every live failing row to the packet's named sample, and record
what they waived.

Every packet here comes from the real merge-packet builder; only the per-PR
``ReviewPacket`` hydration is stubbed, so no ``gh`` call runs.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

import scripts.auto_merge_quorum_green as quorum_green
import scripts.drain_codex_automation_value as drain
import scripts.settle_one_pr as settle_one_pr
from aragora.cli.commands import review_queue
from aragora.swarm.auto_merge_green import REQUIRED_CHECKS

PR = 9453
HEAD = "a" * 40
WORKFLOW = "Security Gate"
OPTIONAL_FAILURES = ("npm Security Scan", "Security Gate Summary")
PROOF_COUNTS = {
    "non_green_count": 2,
    "non_required_non_green_count": 2,
    "failing_or_cancelled_count": 2,
    "pending_count": 0,
    "unverified_cancelled_non_required_count": 0,
}
EXPECTED_WAIVER = {
    "waived_failing_checks": [
        "Security Gate / Security Gate Summary",
        "Security Gate / npm Security Scan",
    ],
    "optional_only_unstable_proof": PROOF_COUNTS,
}


def _load_merge_executor() -> Any:
    script = Path(__file__).resolve().parents[2] / "scripts" / "merge_executor.py"
    spec = importlib.util.spec_from_file_location("merge_executor_consumers_under_test", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load spec for {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


merge_executor = _load_merge_executor()


def _review_packet(*, labels: list[str] | None = None) -> review_queue.ReviewPacket:
    return review_queue.ReviewPacket(
        pr_number=PR,
        title="Optional scans fail on an otherwise green PR",
        url=f"https://github.com/synaptent/aragora/pull/{PR}",
        head_sha=HEAD,
        base_sha="b" * 40,
        author="codex",
        is_draft=False,
        additions=1,
        deletions=1,
        changed_files=1,
        queue_bucket="ready_now",
        touched_subsystems=["docs"],
        high_risk_paths_touched=[],
        validation=[],
        checks_summary="6/6 required green",
        risk_flags=[],
        machine_recommendation="approve_candidate",
        machine_recommendation_reason="required checks authoritative",
        packet_sha="sha256:test",
        generated_at="2026-10-12T00:00:00+00:00",
        check_surfaces={
            "effective_gate": {"source": "required_pr_checks", "summary": "6/6 required green"},
            "required_pr_checks": {
                "available": True,
                "effective_total": 6,
                "gate_selected": True,
                "gate_blocked_reason": "",
                "failing_or_cancelled": [],
                "pending": [],
            },
            "pr_rollup": {
                "available": True,
                **PROOF_COUNTS,
                "non_required_non_green_sample": [
                    f"{WORKFLOW} / {name}" for name in OPTIONAL_FAILURES
                ],
                "unverified_cancelled_non_required_sample": [],
            },
            "unstable_receipt_guard": {"modifies_guarded_paths": False},
        },
        labels=list(labels or []),
        merge_state_status="UNSTABLE",
        model_review_quorum={
            "tier": 2,
            "tier_name": "Tier 2",
            "status": "satisfied",
            "verdict": "admin_squash_allowed",
            "admin_squash_allowed": True,
            "requires_human_risk_settlement": False,
            "unresolved_dissent": False,
            "reviewer_signals": [],
            "dogfood_evidence": [],
            "counted_reviewer_ids": ["claude", "openai"],
            "reasons": ["clean exact-head quorum"],
        },
    )


def _merge_packet(monkeypatch: pytest.MonkeyPatch, **packet_kwargs: Any) -> dict[str, Any]:
    monkeypatch.setattr(
        review_queue, "_build_packet", lambda _ref, **_kwargs: _review_packet(**packet_kwargs)
    )
    monkeypatch.setattr(
        review_queue, "_explicit_merged_pr_merge_packet_entry", lambda _ref, _repo: None
    )
    return review_queue._build_merge_authorization_packet(
        pr_refs=[str(PR)], limit=30, repo_override="synaptent/aragora"
    )


def _live_view() -> dict[str, Any]:
    rows: list[dict[str, Any]] = [
        {"name": name, "conclusion": "SUCCESS"}
        for name in sorted(REQUIRED_CHECKS | {"aragora-merge-quorum"})
    ]
    rows.extend(
        {"name": name, "workflowName": WORKFLOW, "conclusion": "FAILURE"}
        for name in OPTIONAL_FAILURES
    )
    return {
        "number": PR,
        "title": "Optional scans fail on an otherwise green PR",
        "url": f"https://github.com/synaptent/aragora/pull/{PR}",
        "state": "OPEN",
        "headRefOid": HEAD,
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "UNSTABLE",
        "statusCheckRollup": rows,
    }


def _run_merge_executor(entry: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    main_runs = [
        {"id": index, "name": name, "status": "completed", "conclusion": "success"}
        for index, name in enumerate(sorted(REQUIRED_CHECKS), start=1)
    ]
    return merge_executor.run_pass(
        repo="synaptent/aragora",
        prs=[PR],
        apply=False,
        max_merges=1,
        receipt_dir=tmp_path / "receipts",
        halt_file=tmp_path / "halt.json",
        disarm_file=tmp_path / "disarm",
        fetch_view={PR: _live_view()}.get,
        fetch_packet={PR: entry}.get,
        promising=lambda _view: True,
        merge_fn=lambda *_args: pytest.fail("a dry run must not merge"),
        fetch_main_checks=lambda: main_runs,
        fetch_main_statuses=lambda: [],
    )


def _run_quorum_green_sweeper(
    entry: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> dict[str, Any]:
    monkeypatch.setattr(quorum_green, "fetch_view", lambda _repo, _pr: _live_view())
    monkeypatch.setattr(quorum_green, "fetch_packet_entry", lambda _repo, _pr: entry)
    capsys.readouterr()
    assert quorum_green.main(["--repo", "synaptent/aragora", "--pr", str(PR), "--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_packet_verdict_for_an_optional_only_unstable_pr_stays_blocked(monkeypatch) -> None:
    packet = _merge_packet(monkeypatch)
    entry = packet["entries"][0]

    assert entry["status"] == "blocked_by_live_gate"
    assert entry["verdict"] == "admin_squash_blocked_by_live_gate"
    assert entry["admin_squash_allowed"] is False
    assert entry["admin_squash_gate_blockers"] == [
        "mergeStateStatus=UNSTABLE; admin squash requires CLEAN or BLOCKED"
    ]
    assert packet["admin_squash_order"] == []
    assert PR in packet["not_ready"]
    assert entry["optional_only_unstable_executor_proof"] == {
        "model_quorum_status": "satisfied",
        "model_quorum_verdict": "admin_squash_allowed",
        "model_quorum_admin_squash_allowed": True,
        "proof_counts": PROOF_COUNTS,
    }


def test_value_drain_refuses_the_optional_only_unstable_pr(monkeypatch) -> None:
    packet = _merge_packet(monkeypatch)

    evaluation = drain.evaluate_merge_candidate(
        pr_view=_live_view(),
        required_checks=[
            {"name": "lint", "state": "SUCCESS", "bucket": "pass", "workflow": "Lint"}
        ],
        merge_packet=packet,
        settle_one={"blockers": []},
        owner={},
    )

    assert evaluation.eligible is False
    assert evaluation.reason == f"merge-packet not_ready is non-empty: [{PR}]"


def test_settle_one_neither_selects_nor_authorizes_the_optional_only_unstable_pr(
    monkeypatch,
) -> None:
    packet = _merge_packet(monkeypatch)

    selected, blockers = settle_one_pr.select_candidate(packet)
    assert selected is None
    assert blockers == ["no Tier 0-2 non-human-risk green PR needs only settlement evidence"]

    # Asked for this PR explicitly, settle_one reports packet_authorized_dry_run
    # only when the entry is admin_squash_allowed with status satisfied.
    explicit, _ = settle_one_pr.select_candidate(packet, explicit_pr=PR)
    assert explicit is not None
    assert explicit["admin_squash_allowed"] is False
    assert explicit["status"] != "satisfied"


def test_merge_executor_merges_through_the_executor_proof_and_records_the_waiver(
    monkeypatch, tmp_path
) -> None:
    entry = _merge_packet(monkeypatch)["entries"][0]

    summary = _run_merge_executor(entry, tmp_path)

    record = summary["results"][0]
    assert record["action"] == "would-merge"
    assert {key: record[key] for key in EXPECTED_WAIVER} == EXPECTED_WAIVER


def test_quorum_green_sweeper_merges_through_the_executor_proof_and_records_the_waiver(
    monkeypatch, capsys
) -> None:
    entry = _merge_packet(monkeypatch)["entries"][0]

    summary = _run_quorum_green_sweeper(entry, monkeypatch, capsys)

    assert summary["eligible"] == 1
    record = summary["results"][0]
    assert record["action"] == "would-merge"
    assert {key: record[key] for key in EXPECTED_WAIVER} == EXPECTED_WAIVER


def test_executors_refuse_the_entry_without_the_executor_proof(
    monkeypatch, tmp_path, capsys
) -> None:
    entry = _merge_packet(monkeypatch)["entries"][0]
    entry.pop("optional_only_unstable_executor_proof")

    executor_record = _run_merge_executor(entry, tmp_path)["results"][0]
    sweeper_record = _run_quorum_green_sweeper(entry, monkeypatch, capsys)["results"][0]

    for record in (executor_record, sweeper_record):
        assert record["action"] == "skip"
        assert "merge-packet status not satisfied (blocked_by_live_gate)" in record["blockers"]
        assert "merge state not safe (mergeStateStatus=UNSTABLE)" in record["blockers"]
        assert "waived_failing_checks" not in record


def test_operator_review_label_withholds_the_executor_proof(monkeypatch, tmp_path, capsys) -> None:
    entry = _merge_packet(monkeypatch, labels=["operator-review-required"])["entries"][0]

    assert "optional_only_unstable_executor_proof" not in entry
    assert entry["admin_squash_gate_blockers"] == [
        "operator-review-required label present",
        "mergeStateStatus=UNSTABLE; admin squash requires CLEAN or BLOCKED",
    ]
    assert _run_merge_executor(entry, tmp_path)["results"][0]["action"] == "skip"
    assert _run_quorum_green_sweeper(entry, monkeypatch, capsys)["results"][0]["action"] == "skip"
