"""Tests for development coordination primitives."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aragora.nomic.dev_coordination import (
    CompletionReceipt,
    DevCoordinationStore,
    IntegrationDecisionType,
    LeaseConflictError,
    SalvageStatus,
)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "git", "init", "-b", "main")
    _run(repo, "git", "config", "user.email", "test@example.com")
    _run(repo, "git", "config", "user.name", "Test User")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _run(repo, "git", "add", "README.md")
    _run(repo, "git", "commit", "-m", "initial")
    _run(repo, "git", "remote", "add", "origin", str(repo))
    _run(repo, "git", "update-ref", "refs/remotes/origin/main", "HEAD")
    return repo


@pytest.fixture()
def store(repo: Path) -> DevCoordinationStore:
    return DevCoordinationStore(repo_root=repo)


def _run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=True,
    )


def test_claim_lease_detects_conflicting_scope(store: DevCoordinationStore) -> None:
    lease = store.claim_lease(
        task_id="clb-1",
        title="Spec path hardening",
        owner_agent="codex",
        owner_session_id="sess-a",
        branch="codex/a",
        worktree_path="/tmp/wt-a",
        allowed_globs=["aragora/prompt_engine/**"],
        expected_tests=["python -m pytest tests/prompt_engine -q"],
    )

    assert lease.is_active is True
    assert store.fleet_store.list_claims()[0]["path"] == "aragora/prompt_engine/**"

    with pytest.raises(LeaseConflictError) as exc_info:
        store.claim_lease(
            task_id="clb-2",
            title="Overlapping spec change",
            owner_agent="claude",
            owner_session_id="sess-b",
            branch="codex/b",
            worktree_path="/tmp/wt-b",
            claimed_paths=["aragora/prompt_engine/spec_builder.py"],
        )

    assert exc_info.value.conflicts[0]["lease_id"] == lease.lease_id


def test_claim_lease_detects_existing_fleet_claim(store: DevCoordinationStore) -> None:
    store.fleet_store.claim_paths(
        session_id="external-session",
        paths=["aragora/server/auth_checks.py"],
        branch="codex/external",
    )

    with pytest.raises(LeaseConflictError) as exc_info:
        store.claim_lease(
            task_id="clb-fleet",
            title="Auth checks hardening",
            owner_agent="codex",
            owner_session_id="sess-local",
            branch="codex/local",
            worktree_path="/tmp/wt-local",
            claimed_paths=["aragora/server/auth_checks.py"],
        )

    assert exc_info.value.conflicts[0]["source"] == "fleet_claim"


def test_claim_lease_allows_disjoint_scopes(store: DevCoordinationStore) -> None:
    store.claim_lease(
        task_id="clb-1",
        title="Spec path hardening",
        owner_agent="codex",
        owner_session_id="sess-a",
        branch="codex/a",
        worktree_path="/tmp/wt-a",
        allowed_globs=["aragora/prompt_engine/**"],
    )

    second = store.claim_lease(
        task_id="clb-3",
        title="Frontend polish",
        owner_agent="claude",
        owner_session_id="sess-c",
        branch="codex/c",
        worktree_path="/tmp/wt-c",
        allowed_globs=["aragora/live/src/**"],
    )

    assert second.is_active is True
    assert len(store.list_active_leases()) == 2
    assert len(store.fleet_store.list_claims()) == 2


def test_record_completion_creates_pending_integration(store: DevCoordinationStore) -> None:
    lease = store.claim_lease(
        task_id="clb-4",
        title="Receipt gate",
        owner_agent="codex",
        owner_session_id="sess-a",
        branch="codex/a",
        worktree_path="/tmp/wt-a",
        claimed_paths=["aragora/pipeline/backbone_contracts.py"],
        expected_tests=["python -m pytest tests/pipeline/test_backbone_contracts.py -q"],
    )

    receipt = store.record_completion(
        lease_id=lease.lease_id,
        owner_agent="codex",
        owner_session_id="sess-a",
        branch="codex/a",
        worktree_path="/tmp/wt-a",
        commit_shas=["deadbeef"],
        changed_paths=["aragora/pipeline/backbone_contracts.py"],
        tests_run=["python -m pytest tests/pipeline/test_backbone_contracts.py -q"],
        assumptions=["No schema drift"],
        confidence=0.82,
    )

    assert isinstance(receipt, CompletionReceipt)
    assert receipt.artifact_hash
    assert store.list_active_leases() == []

    pending = store.list_integration_decisions(only_pending=True)
    assert len(pending) == 1
    assert pending[0].receipt_id == receipt.receipt_id
    assert pending[0].decision == IntegrationDecisionType.PENDING_REVIEW.value
    assert store.fleet_store.list_claims() == []
    merge_queue = store.fleet_store.list_merge_queue()
    assert len(merge_queue) == 1
    assert merge_queue[0]["metadata"]["receipt_id"] == receipt.receipt_id


def test_record_integration_decision_updates_queue(store: DevCoordinationStore) -> None:
    lease = store.claim_lease(
        task_id="clb-5",
        title="Merge lane",
        owner_agent="codex",
        owner_session_id="sess-a",
        branch="codex/a",
        worktree_path="/tmp/wt-a",
        claimed_paths=["aragora/server/handlers/playground.py"],
    )
    receipt = store.record_completion(
        lease_id=lease.lease_id,
        owner_agent="codex",
        owner_session_id="sess-a",
        branch="codex/a",
        worktree_path="/tmp/wt-a",
        commit_shas=["abc12345"],
    )

    decision = store.record_integration_decision(
        receipt_id=receipt.receipt_id,
        decision=IntegrationDecisionType.CHERRY_PICK,
        decided_by="integrator",
        rationale="Keep only the isolated handler fix",
        chosen_commits=["abc12345"],
        followups=["run share-flow tests"],
    )

    assert decision.decision == IntegrationDecisionType.CHERRY_PICK.value
    assert len(store.list_integration_decisions(receipt_id=receipt.receipt_id)) == 2
    assert (
        store.pending_work_items()[0].metadata["decision"]
        == IntegrationDecisionType.PENDING_REVIEW.value
    )
    merge_queue = store.fleet_store.list_merge_queue()
    assert merge_queue[0]["status"] == "integrating"
    assert merge_queue[0]["metadata"]["integration_decision"] == "cherry_pick"


def test_heartbeat_lease_refreshes_expiry_and_fleet_claim(store: DevCoordinationStore) -> None:
    lease = store.claim_lease(
        task_id="clb-heartbeat",
        title="Heartbeat path",
        owner_agent="codex",
        owner_session_id="sess-heartbeat",
        branch="codex/heartbeat",
        worktree_path="/tmp/wt-heartbeat",
        claimed_paths=["aragora/server/auth_checks.py"],
        ttl_hours=0.01,
    )

    original_expiry = lease.expires_at
    refreshed = store.heartbeat_lease(lease.lease_id, ttl_hours=2.0)

    assert refreshed.expires_at > original_expiry
    claims = store.fleet_store.list_claims()
    assert len(claims) == 1
    assert claims[0]["session_id"] == "sess-heartbeat"


def test_reap_expired_leases_releases_fleet_claims(store: DevCoordinationStore) -> None:
    lease = store.claim_lease(
        task_id="clb-expired",
        title="Expired path",
        owner_agent="codex",
        owner_session_id="sess-expired",
        branch="codex/expired",
        worktree_path="/tmp/wt-expired",
        claimed_paths=["aragora/server/auth_checks.py"],
        ttl_hours=2.0,
    )
    assert store.fleet_store.list_claims()

    conn = store._connect()
    try:
        conn.execute(
            "UPDATE leases SET expires_at = ?, updated_at = ? WHERE lease_id = ?",
            (
                "2000-01-01T00:00:00+00:00",
                "2000-01-01T00:00:00+00:00",
                lease.lease_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    expired = store.reap_expired_leases()

    assert [item.lease_id for item in expired] == [lease.lease_id]
    assert store.list_active_leases() == []
    assert store.fleet_store.list_claims() == []


def test_status_summary_does_not_reap_expired_leases(store: DevCoordinationStore) -> None:
    lease = store.claim_lease(
        task_id="clb-status-read",
        title="Status read should be side-effect free",
        owner_agent="codex",
        owner_session_id="sess-status",
        branch="codex/status",
        worktree_path="/tmp/wt-status",
        claimed_paths=["aragora/server/auth_checks.py"],
        ttl_hours=2.0,
    )

    conn = store._connect()
    try:
        conn.execute(
            "UPDATE leases SET expires_at = ?, updated_at = ? WHERE lease_id = ?",
            (
                "2000-01-01T00:00:00+00:00",
                "2000-01-01T00:00:00+00:00",
                lease.lease_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    summary = store.status_summary()

    assert summary["counts"]["active_leases"] == 0
    assert summary["counts"]["fleet_claims"] == 1
    claims = store.fleet_store.list_claims()
    assert len(claims) == 1
    assert claims[0]["session_id"] == "sess-status"


def test_claim_lease_reaps_expired_claims_before_conflict_check(
    store: DevCoordinationStore,
) -> None:
    lease = store.claim_lease(
        task_id="clb-reclaim",
        title="Original lease",
        owner_agent="codex",
        owner_session_id="sess-old",
        branch="codex/old",
        worktree_path="/tmp/wt-old",
        claimed_paths=["aragora/server/auth_checks.py"],
        ttl_hours=2.0,
    )

    conn = store._connect()
    try:
        conn.execute(
            "UPDATE leases SET expires_at = ?, updated_at = ? WHERE lease_id = ?",
            (
                "2000-01-01T00:00:00+00:00",
                "2000-01-01T00:00:00+00:00",
                lease.lease_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    replacement = store.claim_lease(
        task_id="clb-reclaim-2",
        title="Replacement lease",
        owner_agent="claude",
        owner_session_id="sess-new",
        branch="codex/new",
        worktree_path="/tmp/wt-new",
        claimed_paths=["aragora/server/auth_checks.py"],
    )

    claims = store.fleet_store.list_claims()
    assert replacement.is_active is True
    assert len(claims) == 1
    assert claims[0]["session_id"] == "sess-new"


def test_scan_salvage_sources_finds_worktree_and_stash(
    repo: Path, store: DevCoordinationStore
) -> None:
    worktree_path = repo.parent / "dirty-wt"
    _run(repo, "git", "worktree", "add", "-b", "codex/dirty", str(worktree_path), "main")
    (worktree_path / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    (repo / "stashed.txt").write_text("stash me\n", encoding="utf-8")
    _run(repo, "git", "add", "stashed.txt")
    _run(repo, "git", "stash", "push", "-u", "-m", "useful stash")

    candidates = store.scan_salvage_sources()
    by_kind = {item.source_kind: item for item in candidates}

    assert "worktree" in by_kind
    assert by_kind["worktree"].source_ref == "codex/dirty"
    assert by_kind["worktree"].status == SalvageStatus.DETECTED.value
    assert "stash" in by_kind
    assert by_kind["stash"].source_ref.startswith("stash@{")

    work_items = store.pending_work_items()
    assert any(item.metadata.get("source_kind") == "worktree" for item in work_items)
    assert any(item.metadata.get("source_kind") == "stash" for item in work_items)


def test_release_lease_releases_fleet_claims(store: DevCoordinationStore) -> None:
    lease = store.claim_lease(
        task_id="clb-release",
        title="Release path",
        owner_agent="codex",
        owner_session_id="sess-release",
        branch="codex/release",
        worktree_path="/tmp/wt-release",
        claimed_paths=["aragora/server/handlers/playground.py"],
    )

    assert store.fleet_store.list_claims()

    released = store.release_lease(lease.lease_id)

    assert released.status == "released"
    assert store.fleet_store.list_claims() == []
