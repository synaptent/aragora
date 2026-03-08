"""Tests for shared fleet coordination utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from aragora.worktree.fleet import (
    FleetCoordinationStore,
    infer_orchestration_pattern,
)


def test_infer_orchestration_pattern_from_framework() -> None:
    pattern = infer_orchestration_pattern({"framework": "CrewAI"})
    assert pattern == "crewai"


def test_infer_orchestration_pattern_from_command() -> None:
    pattern = infer_orchestration_pattern({"command": "python scripts/gastown_migrate_state.py"})
    assert pattern == "gastown"


def test_claim_paths_detects_conflicts(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    first = store.claim_paths(
        session_id="session-a",
        paths=["aragora/server/handlers/a.py"],
        mode="exclusive",
    )
    assert first["conflicts"] == []

    second = store.claim_paths(
        session_id="session-b",
        paths=["aragora/server/handlers/a.py"],
        mode="exclusive",
    )
    assert len(second["conflicts"]) == 1
    assert second["conflicts"][0]["session_id"] == "session-a"


def test_claim_paths_detects_glob_to_file_conflicts(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    first = store.claim_paths(
        session_id="session-a",
        paths=["aragora/server/**"],
        mode="exclusive",
    )
    assert first["conflicts"] == []

    second = store.claim_paths(
        session_id="session-b",
        paths=["aragora/server/handlers/a.py"],
        mode="exclusive",
    )
    assert len(second["conflicts"]) == 1
    assert second["conflicts"][0]["session_id"] == "session-a"


def test_audit_session_paths_detects_unowned_and_foreign_claims(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    store.claim_paths(
        session_id="session-a",
        paths=["aragora/server/**"],
        mode="exclusive",
    )
    store.claim_paths(
        session_id="session-b",
        paths=["aragora/cli/**"],
        mode="exclusive",
    )

    audit = store.audit_session_paths(
        session_id="session-a",
        paths=["aragora/server/handlers/a.py", "aragora/cli/main.py"],
        branch="codex/session-a",
    )

    assert audit["owned_paths"] == ["aragora/server/handlers/a.py"]
    assert audit["unowned_paths"] == ["aragora/cli/main.py"]
    assert audit["conflicts"][0]["session_id"] == "session-b"
    assert audit["ok"] is False


def test_release_paths_by_subset(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    store.claim_paths(session_id="session-a", paths=["a.py", "b.py"])
    result = store.release_paths(session_id="session-a", paths=["a.py"])
    assert result["released"] == 1
    claims = store.list_claims()
    assert len(claims) == 1
    assert claims[0]["path"] == "b.py"


def test_enqueue_merge_deduplicates_active_branch(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    first = store.enqueue_merge(session_id="session-a", branch="codex/session-a", priority=70)
    assert first["queued"] is True
    second = store.enqueue_merge(session_id="session-b", branch="codex/session-a", priority=80)
    assert second["duplicate"] is True
    queue = store.list_merge_queue()
    assert len(queue) == 1


def test_claim_next_merge_prefers_highest_priority(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    store.enqueue_merge(session_id="session-a", branch="codex/low", priority=20)
    high = store.enqueue_merge(session_id="session-b", branch="codex/high", priority=90)

    claimed = store.claim_next_merge(worker_session_id="integrator-1")

    assert claimed is not None
    assert claimed["id"] == high["item"]["id"]
    assert claimed["status"] == "validating"
    assert claimed["metadata"]["worker_session_id"] == "integrator-1"


def test_update_merge_queue_item_persists_status_and_metadata(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    queued = store.enqueue_merge(session_id="session-a", branch="codex/session-a", priority=50)

    updated = store.update_merge_queue_item(
        item_id=queued["item"]["id"],
        status="integrating",
        metadata={"receipt_id": "rcpt-1", "note": "approved"},
    )

    assert updated["status"] == "integrating"
    assert updated["metadata"]["receipt_id"] == "rcpt-1"
    listed = store.list_merge_queue()
    assert listed[0]["status"] == "integrating"


def test_update_merge_queue_item_enforces_expected_status(tmp_path: Path) -> None:
    store = FleetCoordinationStore(tmp_path)
    queued = store.enqueue_merge(session_id="session-a", branch="codex/session-a", priority=50)
    item_id = queued["item"]["id"]

    store.update_merge_queue_item(
        item_id=item_id,
        status="validating",
        expected_status="queued",
        metadata={"worker_session_id": "integrator-1"},
    )

    with pytest.raises(KeyError):
        store.update_merge_queue_item(
            item_id=item_id,
            status="integrating",
            expected_status="queued",
            metadata={"worker_session_id": "integrator-2"},
        )
