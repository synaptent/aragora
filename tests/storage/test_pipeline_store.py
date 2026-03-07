"""Tests for PipelineResultStore persistence layer."""

from __future__ import annotations

import time

import pytest

from aragora.storage.pipeline_store import PipelineResultStore


@pytest.fixture
def store(tmp_path):
    """Create a fresh PipelineResultStore in a temp directory."""
    db_path = str(tmp_path / "test_pipeline.db")
    return PipelineResultStore(db_path)


def _make_result(
    stage_status: dict | None = None,
    ideas: dict | None = None,
    goals: dict | None = None,
    actions: dict | None = None,
    orchestration: dict | None = None,
    transitions: list | None = None,
    provenance_count: int = 0,
    integrity_hash: str = "",
    receipt: dict | None = None,
    execution: dict | None = None,
    duration: float = 0.0,
) -> dict:
    return {
        "stage_status": stage_status or {"ideas": "complete", "goals": "pending"},
        "ideas": ideas,
        "goals": goals,
        "actions": actions,
        "orchestration": orchestration,
        "transitions": transitions or [],
        "provenance_count": provenance_count,
        "integrity_hash": integrity_hash,
        "receipt": receipt,
        "execution": execution,
        "duration": duration,
    }


class TestSave:
    """Test PipelineResultStore.save()."""

    def test_save_and_get(self, store):
        result = _make_result(ideas={"nodes": [{"id": "n1"}]})
        store.save("pipe-1", result)

        retrieved = store.get("pipe-1")
        assert retrieved is not None
        assert retrieved["pipeline_id"] == "pipe-1"
        assert retrieved["ideas"] == {"nodes": [{"id": "n1"}]}

    def test_save_overwrites(self, store):
        store.save("pipe-1", _make_result(ideas={"v": 1}))
        store.save("pipe-1", _make_result(ideas={"v": 2}))

        retrieved = store.get("pipe-1")
        assert retrieved["ideas"] == {"v": 2}

    def test_save_derives_complete_status(self, store):
        result = _make_result(stage_status={"ideas": "complete", "goals": "complete"})
        store.save("pipe-1", result)

        retrieved = store.get("pipe-1")
        assert retrieved["status"] == "complete"

    def test_save_derives_failed_status(self, store):
        result = _make_result(stage_status={"ideas": "complete", "goals": "failed"})
        store.save("pipe-1", result)

        retrieved = store.get("pipe-1")
        assert retrieved["status"] == "failed"

    def test_save_derives_in_progress_status(self, store):
        result = _make_result(stage_status={"ideas": "complete", "goals": "pending"})
        store.save("pipe-1", result)

        retrieved = store.get("pipe-1")
        assert retrieved["status"] == "in_progress"

    def test_save_derives_pending_status(self, store):
        result = _make_result(stage_status={"ideas": "pending", "goals": "pending"})
        store.save("pipe-1", result)

        retrieved = store.get("pipe-1")
        assert retrieved["status"] == "pending"

    def test_save_preserves_receipt(self, store):
        receipt = {"hash": "abc123", "decision": "approved"}
        store.save("pipe-1", _make_result(receipt=receipt))

        retrieved = store.get("pipe-1")
        assert retrieved["receipt"] == receipt

    def test_save_preserves_execution(self, store):
        execution = {
            "plan_id": "plan-123",
            "execution_id": "exec-123",
            "correlation_id": "corr-123",
            "status": "running",
        }
        store.save("pipe-1", _make_result(execution=execution))

        retrieved = store.get("pipe-1")
        assert retrieved["execution"] == execution

    def test_save_preserves_transitions(self, store):
        transitions = [{"from": "ideas", "to": "goals", "timestamp": 1234.5}]
        store.save("pipe-1", _make_result(transitions=transitions))

        retrieved = store.get("pipe-1")
        assert retrieved["transitions"] == transitions

    def test_save_preserves_provenance(self, store):
        store.save(
            "pipe-1",
            _make_result(
                provenance_count=5,
                integrity_hash="sha256:abc",
            ),
        )

        retrieved = store.get("pipe-1")
        assert retrieved["provenance_count"] == 5
        assert retrieved["integrity_hash"] == "sha256:abc"

    def test_save_sets_timestamps(self, store):
        before = time.time()
        store.save("pipe-1", _make_result())
        after = time.time()

        retrieved = store.get("pipe-1")
        assert before <= retrieved["created_at"] <= after
        assert before <= retrieved["updated_at"] <= after


class TestGet:
    """Test PipelineResultStore.get()."""

    def test_get_missing_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_get_deserializes_json_fields(self, store):
        store.save(
            "pipe-1",
            _make_result(
                ideas={"nodes": [1, 2]},
                goals={"goals": ["g1"]},
                actions={"steps": ["s1"]},
                orchestration={"agents": ["a1"]},
            ),
        )

        retrieved = store.get("pipe-1")
        assert retrieved["ideas"] == {"nodes": [1, 2]}
        assert retrieved["goals"] == {"goals": ["g1"]}
        assert retrieved["actions"] == {"steps": ["s1"]}
        assert retrieved["orchestration"] == {"agents": ["a1"]}

    def test_get_handles_null_fields(self, store):
        store.save("pipe-1", _make_result())

        retrieved = store.get("pipe-1")
        # Null JSON fields deserialize to empty dict
        assert retrieved["ideas"] == {}
        assert retrieved["goals"] == {}


class TestListPipelines:
    """Test PipelineResultStore.list_pipelines()."""

    def test_list_empty(self, store):
        assert store.list_pipelines() == []

    def test_list_returns_summaries(self, store):
        store.save("pipe-1", _make_result())
        store.save("pipe-2", _make_result())

        results = store.list_pipelines()
        assert len(results) == 2
        # Should have summary fields but not full stage data
        for r in results:
            assert "id" in r
            assert "status" in r
            assert "stage_status" in r

    def test_list_ordered_by_created_desc(self, store):
        store.save("pipe-1", _make_result())
        store.save("pipe-2", _make_result())

        results = store.list_pipelines()
        # Most recent first
        assert results[0]["id"] == "pipe-2"
        assert results[1]["id"] == "pipe-1"

    def test_list_filters_by_status(self, store):
        store.save("pipe-1", _make_result(stage_status={"ideas": "complete", "goals": "complete"}))
        store.save("pipe-2", _make_result(stage_status={"ideas": "complete", "goals": "failed"}))

        complete = store.list_pipelines(status="complete")
        assert len(complete) == 1
        assert complete[0]["id"] == "pipe-1"

        failed = store.list_pipelines(status="failed")
        assert len(failed) == 1
        assert failed[0]["id"] == "pipe-2"

    def test_list_with_limit(self, store):
        for i in range(5):
            store.save(f"pipe-{i}", _make_result())

        results = store.list_pipelines(limit=3)
        assert len(results) == 3

    def test_list_with_offset(self, store):
        for i in range(5):
            store.save(f"pipe-{i}", _make_result())

        results = store.list_pipelines(limit=2, offset=2)
        assert len(results) == 2


class TestDelete:
    """Test PipelineResultStore.delete()."""

    def test_delete_existing(self, store):
        store.save("pipe-1", _make_result())
        assert store.delete("pipe-1") is True
        assert store.get("pipe-1") is None

    def test_delete_missing(self, store):
        assert store.delete("nonexistent") is False


class TestCount:
    """Test PipelineResultStore.count()."""

    def test_count_empty(self, store):
        assert store.count() == 0

    def test_count_all(self, store):
        store.save("pipe-1", _make_result())
        store.save("pipe-2", _make_result())
        assert store.count() == 2

    def test_count_by_status(self, store):
        store.save("pipe-1", _make_result(stage_status={"ideas": "complete", "goals": "complete"}))
        store.save("pipe-2", _make_result(stage_status={"ideas": "failed"}))
        store.save("pipe-3", _make_result(stage_status={"ideas": "pending"}))

        assert store.count(status="complete") == 1
        assert store.count(status="failed") == 1
        assert store.count(status="pending") == 1


class TestUpdateTimestamp:
    """Test that updates preserve created_at but bump updated_at."""

    def test_update_bumps_updated_at(self, store):
        store.save("pipe-1", _make_result(ideas={"v": 1}))
        first = store.get("pipe-1")

        # Small delay to ensure timestamp differs
        import time

        time.sleep(0.01)

        store.save("pipe-1", _make_result(ideas={"v": 2}))
        second = store.get("pipe-1")

        # updated_at should be newer
        assert second["updated_at"] >= first["updated_at"]
