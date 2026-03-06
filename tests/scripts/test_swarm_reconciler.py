"""Tests for swarm_reconciler.py daemon."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.swarm_reconciler import ReconcilerConfig, SwarmReconciler


class TestReconcilerConfig:
    def test_defaults(self):
        config = ReconcilerConfig()
        assert config.repo_root == "."
        assert config.poll_interval_seconds == 30
        assert config.collect_timeout_seconds == 5.0
        assert config.once is False


class TestSwarmReconciler:
    @pytest.mark.asyncio
    async def test_single_pass_no_active_runs(self):
        """With no active runs, reconciler should complete without dispatching."""
        config = ReconcilerConfig(once=True)
        reconciler = SwarmReconciler(config)

        mock_supervisor = MagicMock()
        mock_supervisor.status_summary.return_value = {
            "runs": [],
            "counts": {"runs": 0, "queued_work_orders": 0, "completed_work_orders": 0},
        }

        with patch("aragora.swarm.supervisor.SwarmSupervisor", return_value=mock_supervisor):
            await reconciler.run()

        mock_supervisor.status_summary.assert_called_once_with(refresh_scaling=True)

    @pytest.mark.asyncio
    async def test_dispatches_leased_orders(self):
        """Should dispatch workers for runs with leased work orders."""
        config = ReconcilerConfig(once=True)
        reconciler = SwarmReconciler(config)

        mock_supervisor = MagicMock()
        mock_supervisor.status_summary.return_value = {
            "runs": [
                {
                    "run_id": "run-123",
                    "status": "active",
                    "work_orders": [
                        {"status": "leased"},
                        {"status": "leased"},
                    ],
                }
            ],
            "counts": {"runs": 1, "queued_work_orders": 0, "completed_work_orders": 0},
        }
        mock_supervisor.dispatch_workers = AsyncMock(return_value=["worker1"])
        mock_supervisor.collect_results = AsyncMock(return_value=[])

        with patch("aragora.swarm.supervisor.SwarmSupervisor", return_value=mock_supervisor):
            await reconciler.run()

        mock_supervisor.dispatch_workers.assert_called_once_with("run-123")

    @pytest.mark.asyncio
    async def test_collects_dispatched_results(self):
        """Should collect results for runs with dispatched work orders."""
        config = ReconcilerConfig(once=True, collect_timeout_seconds=2.0)
        reconciler = SwarmReconciler(config)

        mock_supervisor = MagicMock()
        mock_supervisor.status_summary.return_value = {
            "runs": [
                {
                    "run_id": "run-456",
                    "status": "active",
                    "work_orders": [
                        {"status": "dispatched"},
                        {"status": "dispatched"},
                    ],
                }
            ],
            "counts": {"runs": 1},
        }
        mock_supervisor.dispatch_workers = AsyncMock(return_value=[])
        mock_supervisor.collect_results = AsyncMock(return_value=["result1"])

        with patch("aragora.swarm.supervisor.SwarmSupervisor", return_value=mock_supervisor):
            await reconciler.run()

        mock_supervisor.collect_results.assert_called_once_with("run-456", timeout=2.0)

    @pytest.mark.asyncio
    async def test_handles_dispatch_error(self):
        """Dispatch errors should be logged but not crash the reconciler."""
        config = ReconcilerConfig(once=True)
        reconciler = SwarmReconciler(config)

        mock_supervisor = MagicMock()
        mock_supervisor.status_summary.return_value = {
            "runs": [
                {
                    "run_id": "run-err",
                    "status": "active",
                    "work_orders": [{"status": "leased"}],
                }
            ],
            "counts": {},
        }
        mock_supervisor.dispatch_workers = AsyncMock(side_effect=RuntimeError("CLI not found"))
        mock_supervisor.collect_results = AsyncMock(return_value=[])

        with patch("aragora.swarm.supervisor.SwarmSupervisor", return_value=mock_supervisor):
            await reconciler.run()  # Should not raise

    @pytest.mark.asyncio
    async def test_handles_collect_error(self):
        """Collect errors should be logged but not crash the reconciler."""
        config = ReconcilerConfig(once=True)
        reconciler = SwarmReconciler(config)

        mock_supervisor = MagicMock()
        mock_supervisor.status_summary.return_value = {
            "runs": [
                {
                    "run_id": "run-err2",
                    "status": "active",
                    "work_orders": [{"status": "dispatched"}],
                }
            ],
            "counts": {},
        }
        mock_supervisor.dispatch_workers = AsyncMock(return_value=[])
        mock_supervisor.collect_results = AsyncMock(side_effect=TimeoutError("timed out"))

        with patch("aragora.swarm.supervisor.SwarmSupervisor", return_value=mock_supervisor):
            await reconciler.run()  # Should not raise

    @pytest.mark.asyncio
    async def test_stop_method(self):
        """stop() should cause the run loop to exit."""
        config = ReconcilerConfig(poll_interval_seconds=60)
        reconciler = SwarmReconciler(config)

        mock_supervisor = MagicMock()
        mock_supervisor.status_summary.return_value = {"runs": [], "counts": {}}

        async def stop_after_first():
            await asyncio.sleep(0.05)
            reconciler.stop()

        with patch("aragora.swarm.supervisor.SwarmSupervisor", return_value=mock_supervisor):
            await asyncio.gather(reconciler.run(), stop_after_first())

        assert mock_supervisor.status_summary.call_count >= 1

    @pytest.mark.asyncio
    async def test_mixed_statuses_in_run(self):
        """Run with both leased and dispatched orders should handle both."""
        config = ReconcilerConfig(once=True)
        reconciler = SwarmReconciler(config)

        mock_supervisor = MagicMock()
        mock_supervisor.status_summary.return_value = {
            "runs": [
                {
                    "run_id": "run-mix",
                    "status": "active",
                    "work_orders": [
                        {"status": "leased"},
                        {"status": "dispatched"},
                        {"status": "completed"},
                    ],
                }
            ],
            "counts": {},
        }
        mock_supervisor.dispatch_workers = AsyncMock(return_value=["w1"])
        mock_supervisor.collect_results = AsyncMock(return_value=["r1"])

        with patch("aragora.swarm.supervisor.SwarmSupervisor", return_value=mock_supervisor):
            await reconciler.run()

        mock_supervisor.dispatch_workers.assert_called_once_with("run-mix")
        mock_supervisor.collect_results.assert_called_once_with("run-mix", timeout=5.0)

    @pytest.mark.asyncio
    async def test_skips_non_active_runs(self):
        """Non-active runs should be skipped."""
        config = ReconcilerConfig(once=True)
        reconciler = SwarmReconciler(config)

        mock_supervisor = MagicMock()
        mock_supervisor.status_summary.return_value = {
            "runs": [
                {
                    "run_id": "run-done",
                    "status": "completed",
                    "work_orders": [{"status": "leased"}],
                },
            ],
            "counts": {"runs": 1},
        }
        mock_supervisor.dispatch_workers = AsyncMock()
        mock_supervisor.collect_results = AsyncMock()

        with patch("aragora.swarm.supervisor.SwarmSupervisor", return_value=mock_supervisor):
            await reconciler.run()

        mock_supervisor.dispatch_workers.assert_not_called()
        mock_supervisor.collect_results.assert_not_called()
