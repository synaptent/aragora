"""Tests for the PipelineTelemetryHandler REST endpoint.

Covers:
- can_handle routing
- GET /api/v1/pipeline/telemetry returns {"data": {"stages": [...]}}
- Empty store returns stage skeleton
- Transitions aggregate correctly
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.pipeline_telemetry import PipelineTelemetryHandler


def _body(result: object) -> dict:
    """Extract JSON body from a HandlerResult."""
    return json.loads(result.body)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler():
    return PipelineTelemetryHandler()


# ---------------------------------------------------------------------------
# can_handle
# ---------------------------------------------------------------------------


class TestCanHandle:
    def test_v1_telemetry(self, handler):
        assert handler.can_handle("/api/v1/pipeline/telemetry")

    def test_unversioned_telemetry(self, handler):
        assert handler.can_handle("/api/pipeline/telemetry")

    def test_unrelated_path(self, handler):
        assert not handler.can_handle("/api/v1/pipeline/graph")

    def test_wrong_path(self, handler):
        assert not handler.can_handle("/api/v1/debates")


# ---------------------------------------------------------------------------
# GET /api/v1/pipeline/telemetry -- empty store
# ---------------------------------------------------------------------------


class TestGetTelemetryEmpty:
    """When no graphs/transitions exist, return stage skeleton."""

    def test_returns_data_envelope(self, handler):
        with patch(
            "aragora.server.handlers.pipeline_telemetry._get_store",
            side_effect=ImportError("no store"),
        ):
            result = handler.handle("/api/v1/pipeline/telemetry", {}, None)
            body = _body(result)

        assert "data" in body
        assert "stages" in body["data"]

    def test_skeleton_has_three_transitions(self, handler):
        with patch(
            "aragora.server.handlers.pipeline_telemetry._get_store",
            side_effect=ImportError("no store"),
        ):
            result = handler.handle("/api/v1/pipeline/telemetry", {}, None)
            stages = _body(result)["data"]["stages"]

        assert len(stages) == 3
        assert stages[0]["from_stage"] == "ideas"
        assert stages[0]["to_stage"] == "goals"
        assert stages[1]["from_stage"] == "goals"
        assert stages[1]["to_stage"] == "actions"
        assert stages[2]["from_stage"] == "actions"
        assert stages[2]["to_stage"] == "orchestration"

    def test_skeleton_counts_are_zero(self, handler):
        with patch(
            "aragora.server.handlers.pipeline_telemetry._get_store",
            side_effect=ImportError("no store"),
        ):
            result = handler.handle("/api/v1/pipeline/telemetry", {}, None)
            stages = _body(result)["data"]["stages"]

        for stage in stages:
            assert stage["transition_count"] == 0
            assert stage["avg_confidence"] == 0.0


# ---------------------------------------------------------------------------
# GET /api/v1/pipeline/telemetry -- with transitions
# ---------------------------------------------------------------------------


def _make_transition(from_stage: str, to_stage: str, confidence: float, status: str = "pending"):
    """Create a mock StageTransition."""
    t = MagicMock()
    t.from_stage.value = from_stage
    t.from_stage.__str__ = lambda s: from_stage
    t.to_stage.value = to_stage
    t.to_stage.__str__ = lambda s: to_stage
    t.confidence = confidence
    t.status = status
    return t


class TestGetTelemetryWithData:
    """When transitions exist, aggregate them correctly."""

    def _setup_store(self, transitions):
        """Return a mock store with one graph containing the given transitions."""
        graph = MagicMock()
        graph.id = "g-1"
        graph.transitions = transitions

        store = MagicMock()
        # list returns graph summaries
        store.list.return_value = [{"id": "g-1"}]
        store.get.return_value = graph
        return store

    def test_single_transition(self, handler):
        store = self._setup_store(
            [
                _make_transition("ideas", "goals", 0.75, "approved"),
            ]
        )
        with patch(
            "aragora.server.handlers.pipeline_telemetry._get_store",
            return_value=store,
        ):
            result = handler.handle("/api/v1/pipeline/telemetry", {}, None)
            stages = _body(result)["data"]["stages"]

        assert len(stages) == 1
        assert stages[0]["from_stage"] == "ideas"
        assert stages[0]["to_stage"] == "goals"
        assert stages[0]["transition_count"] == 1
        assert stages[0]["avg_confidence"] == 0.75
        assert stages[0]["statuses"] == {"approved": 1}

    def test_multiple_transitions_aggregate(self, handler):
        store = self._setup_store(
            [
                _make_transition("ideas", "goals", 0.8, "approved"),
                _make_transition("ideas", "goals", 0.6, "pending"),
                _make_transition("goals", "actions", 0.9, "approved"),
            ]
        )
        with patch(
            "aragora.server.handlers.pipeline_telemetry._get_store",
            return_value=store,
        ):
            result = handler.handle("/api/v1/pipeline/telemetry", {}, None)
            stages = _body(result)["data"]["stages"]

        # Two stage pairs
        assert len(stages) == 2

        ideas_goals = next(s for s in stages if s["from_stage"] == "ideas")
        assert ideas_goals["transition_count"] == 2
        assert ideas_goals["avg_confidence"] == pytest.approx(0.7, abs=0.01)
        assert ideas_goals["statuses"] == {"approved": 1, "pending": 1}

        goals_actions = next(s for s in stages if s["from_stage"] == "goals")
        assert goals_actions["transition_count"] == 1
        assert goals_actions["avg_confidence"] == 0.9

    def test_status_200(self, handler):
        store = self._setup_store([])
        with patch(
            "aragora.server.handlers.pipeline_telemetry._get_store",
            side_effect=ImportError("no store"),
        ):
            result = handler.handle("/api/v1/pipeline/telemetry", {}, None)

        assert result.status_code == 200


# ---------------------------------------------------------------------------
# Dispatch returns None for non-matching paths
# ---------------------------------------------------------------------------


class TestDispatch:
    def test_non_matching_returns_none(self, handler):
        result = handler.handle("/api/v1/pipeline/graph", {}, None)
        assert result is None
