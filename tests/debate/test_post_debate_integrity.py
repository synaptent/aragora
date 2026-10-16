"""
Tests for DecisionIntegrityPackage integration in PostDebateCoordinator.

Covers:
- PostDebateConfig.auto_build_integrity_package flag
- PostDebateResult.integrity_package field
- Step 5: integrity package generation in coordinator.run()
- build_integrity_package_from_result adapter function
- Graceful degradation when pipeline is unavailable
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aragora.debate.pipeline_backends import pipeline_backend
from aragora.debate.post_debate_coordinator import (
    PostDebateConfig,
    PostDebateCoordinator,
    PostDebateResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_debate_result(consensus=True, confidence=0.85, task="Test task"):
    """Create a mock debate result."""
    result = MagicMock()
    result.consensus = "majority" if consensus else None
    result.confidence = confidence
    result.task = task
    result.final_answer = "Use token bucket rate limiter"
    result.messages = []
    result.participants = ["claude", "gpt4"]
    return result


# ---------------------------------------------------------------------------
# Config + Result fields
# ---------------------------------------------------------------------------


class TestConfigIntegrityFlag:
    """Test auto_build_integrity_package config flag."""

    def test_default_false(self):
        config = PostDebateConfig()
        assert config.auto_build_integrity_package is False

    def test_set_true(self):
        config = PostDebateConfig(auto_build_integrity_package=True)
        assert config.auto_build_integrity_package is True


class TestResultIntegrityField:
    """Test integrity_package field on PostDebateResult."""

    def test_default_none(self):
        r = PostDebateResult()
        assert r.integrity_package is None

    def test_set_value(self):
        r = PostDebateResult(integrity_package={"debate_id": "d1"})
        assert r.integrity_package["debate_id"] == "d1"


# ---------------------------------------------------------------------------
# build_integrity_package_from_result
# ---------------------------------------------------------------------------


class TestBuildIntegrityPackageFromResult:
    """Test the synchronous adapter for DebateResult input."""

    def test_builds_with_receipt(self):
        from aragora.core_types import DebateResult
        from aragora.pipeline.decision_integrity import build_integrity_package_from_result

        dr = DebateResult(
            debate_id="d-001",
            task="Design a rate limiter",
            final_answer="Use token bucket",
            confidence=0.9,
            consensus_reached=True,
            participants=["claude", "gpt4"],
        )

        package = build_integrity_package_from_result(dr, include_receipt=True, include_plan=False)

        assert package.debate_id == "d-001"
        assert package.receipt is not None
        assert package.plan is None

    def test_builds_without_receipt(self):
        from aragora.core_types import DebateResult
        from aragora.pipeline.decision_integrity import build_integrity_package_from_result

        dr = DebateResult(
            debate_id="d-002",
            task="Test",
            final_answer="Answer",
        )

        package = build_integrity_package_from_result(dr, include_receipt=False, include_plan=False)

        assert package.debate_id == "d-002"
        assert package.receipt is None

    def test_to_dict(self):
        from aragora.core_types import DebateResult
        from aragora.pipeline.decision_integrity import build_integrity_package_from_result

        dr = DebateResult(
            debate_id="d-003",
            task="Test",
            final_answer="Answer",
            confidence=0.8,
        )

        package = build_integrity_package_from_result(dr, include_receipt=True, include_plan=False)

        d = package.to_dict()
        assert d["debate_id"] == "d-003"
        assert d["receipt"] is not None
        assert isinstance(d["receipt"], dict)


# ---------------------------------------------------------------------------
# Coordinator Step 5: integrity package generation
# ---------------------------------------------------------------------------


class TestCoordinatorIntegrityStep:
    """Test that coordinator.run() generates integrity package when configured."""

    def test_integrity_step_disabled_by_default(self):
        config = PostDebateConfig(
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_execution_bridge=False,
        )
        coordinator = PostDebateCoordinator(config=config)

        result = coordinator.run(
            debate_id="d-100",
            debate_result=_make_debate_result(),
        )

        assert result.integrity_package is None

    def test_integrity_step_enabled(self):
        config = PostDebateConfig(
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_execution_bridge=False,
            auto_build_integrity_package=True,
        )
        coordinator = PostDebateCoordinator(config=config)

        mock_package = MagicMock()
        mock_package.to_dict.return_value = {
            "debate_id": "d-101",
            "receipt": {"hash": "abc123"},
            "plan": None,
            "context_snapshot": None,
        }

        with patch(
            "aragora.pipeline.decision_integrity.build_integrity_package_from_result",
            return_value=mock_package,
        ):
            result = coordinator.run(
                debate_id="d-101",
                debate_result=_make_debate_result(),
            )

        assert result.integrity_package is not None
        assert result.integrity_package["debate_id"] == "d-101"

    def test_integrity_step_with_debate_result_object(self):
        """When debate_result is a DebateResult, it passes through directly."""
        from aragora.core_types import DebateResult

        config = PostDebateConfig(
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_execution_bridge=False,
            auto_build_integrity_package=True,
        )
        coordinator = PostDebateCoordinator(config=config)

        dr = DebateResult(
            debate_id="d-102",
            task="Test task",
            final_answer="Answer",
            confidence=0.9,
            consensus_reached=True,
            participants=["claude"],
        )

        mock_package = MagicMock()
        mock_package.to_dict.return_value = {
            "debate_id": "d-102",
            "receipt": {},
            "plan": None,
            "context_snapshot": None,
        }

        with patch(
            "aragora.pipeline.decision_integrity.build_integrity_package_from_result",
            return_value=mock_package,
        ) as mock_build:
            result = coordinator.run(
                debate_id="d-102",
                debate_result=dr,
            )

        # Verify the DebateResult was passed directly (not coerced)
        call_args = mock_build.call_args
        assert call_args[0][0] is dr
        assert result.integrity_package is not None

    def test_integrity_step_import_error_graceful(self):
        """If pipeline module is unavailable, step fails gracefully."""
        config = PostDebateConfig(
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_execution_bridge=False,
            auto_build_integrity_package=True,
        )
        coordinator = PostDebateCoordinator(config=config)
        # The declared registrations run once per process; register before hiding a module.
        pipeline_backend()

        with patch.dict("sys.modules", {"aragora.pipeline.decision_integrity": None}):
            result = coordinator.run(
                debate_id="d-103",
                debate_result=_make_debate_result(),
            )

        assert result.integrity_package is None

    def test_integrity_step_exception_graceful(self):
        """If package generation raises, step fails without cascading."""
        config = PostDebateConfig(
            auto_explain=False,
            auto_create_plan=False,
            auto_notify=False,
            auto_execution_bridge=False,
            auto_build_integrity_package=True,
        )
        coordinator = PostDebateCoordinator(config=config)

        with patch(
            "aragora.pipeline.decision_integrity.build_integrity_package_from_result",
            side_effect=RuntimeError("boom"),
        ):
            result = coordinator.run(
                debate_id="d-104",
                debate_result=_make_debate_result(),
            )

        assert result.integrity_package is None

    def test_integrity_runs_after_other_steps(self):
        """Step 5 runs after steps 1-4 and doesn't interfere."""
        config = PostDebateConfig(
            auto_explain=True,
            auto_create_plan=False,
            auto_notify=False,
            auto_execution_bridge=False,
            auto_build_integrity_package=True,
        )
        coordinator = PostDebateCoordinator(config=config)

        mock_package = MagicMock()
        mock_package.to_dict.return_value = {
            "debate_id": "d-105",
            "receipt": {},
            "plan": None,
            "context_snapshot": None,
        }

        with (
            patch.object(coordinator, "_step_explain", return_value={"explanation": "because"}),
            patch(
                "aragora.pipeline.decision_integrity.build_integrity_package_from_result",
                return_value=mock_package,
            ),
        ):
            result = coordinator.run(
                debate_id="d-105",
                debate_result=_make_debate_result(),
            )

        assert result.explanation is not None
        assert result.integrity_package is not None
