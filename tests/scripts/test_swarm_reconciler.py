"""Tests for scripts/swarm_reconciler.py daemon wrapper."""

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
        assert config.limit == 20


class TestSwarmReconciler:
    @pytest.mark.asyncio
    async def test_single_pass_uses_core_reconciler(self):
        config = ReconcilerConfig(once=True)
        reconciler = SwarmReconciler(config)

        core = MagicMock()
        core.tick_open_runs = AsyncMock(return_value=[])

        with patch("scripts.swarm_reconciler.CoreSwarmReconciler", return_value=core):
            await reconciler.run()

        core.tick_open_runs.assert_awaited_once_with(limit=20)

    @pytest.mark.asyncio
    async def test_passes_limit_to_core_reconciler(self):
        config = ReconcilerConfig(once=True, limit=7)
        reconciler = SwarmReconciler(config)

        core = MagicMock()
        core.tick_open_runs = AsyncMock(return_value=[])

        with patch("scripts.swarm_reconciler.CoreSwarmReconciler", return_value=core):
            await reconciler.run()

        core.tick_open_runs.assert_awaited_once_with(limit=7)

    @pytest.mark.asyncio
    async def test_stop_method(self):
        config = ReconcilerConfig(poll_interval_seconds=60)
        reconciler = SwarmReconciler(config)

        core = MagicMock()
        core.tick_open_runs = AsyncMock(return_value=[])

        async def stop_after_first():
            await asyncio.sleep(0.05)
            reconciler.stop()

        with patch("scripts.swarm_reconciler.CoreSwarmReconciler", return_value=core):
            await asyncio.gather(reconciler.run(), stop_after_first())

        assert core.tick_open_runs.await_count >= 1

    @pytest.mark.asyncio
    async def test_handles_core_exception(self):
        config = ReconcilerConfig(once=True)
        reconciler = SwarmReconciler(config)

        core = MagicMock()
        core.tick_open_runs = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("scripts.swarm_reconciler.CoreSwarmReconciler", return_value=core):
            await reconciler.run()

        core.tick_open_runs.assert_awaited_once_with(limit=20)
