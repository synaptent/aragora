"""
Tests for HTTP Client Pool Shutdown Integration.

Tests cover:
- HTTP client pool close is called during shutdown execution
- Shutdown completes within overall_timeout
- HTTP client pool close failure does not block shutdown (non-critical)
- Phase timeout budgets sum to less than overall_timeout
- HTTP client pool aclose handles already-closed pool gracefully
- drain_requests phase uses the updated 15s timeout
- wait_for_debates phase uses the updated 12s timeout
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.server.shutdown_sequence import (
    ShutdownPhase,
    ShutdownSequence,
    create_server_shutdown_sequence,
)


class TestHTTPClientPoolShutdown:
    """Tests for HTTP client pool shutdown integration."""

    @pytest.mark.asyncio
    async def test_http_client_pool_close_called_during_shutdown(self):
        """Test that HTTP client pool aclose is called during shutdown execution."""
        mock_pool = MagicMock()
        mock_pool._closed = False
        mock_pool.aclose = AsyncMock()

        async def close_http_client_pool():
            from aragora.observability.http_client_pool import HTTPClientPool

            pool = HTTPClientPool.get_instance()
            if pool and not pool._closed:
                await pool.aclose()

        with patch(
            "aragora.observability.http_client_pool.HTTPClientPool.get_instance",
            return_value=mock_pool,
        ):
            sequence = ShutdownSequence()
            sequence.add_phase(
                ShutdownPhase(
                    name="Close HTTP client pool",
                    execute=close_http_client_pool,
                    timeout=5.0,
                    critical=False,
                )
            )

            result = await sequence.execute_all(overall_timeout=30.0)
            assert "Close HTTP client pool" in result["completed"]
            mock_pool.aclose.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_shutdown_completes_within_overall_timeout(self):
        """Test that shutdown completes within overall_timeout."""
        # Create a sequence with a few quick phases
        sequence = ShutdownSequence()

        async def quick_phase():
            await asyncio.sleep(0.01)

        sequence.add_phase(ShutdownPhase(name="Phase 1", execute=quick_phase, timeout=5.0))
        sequence.add_phase(ShutdownPhase(name="Phase 2", execute=quick_phase, timeout=5.0))
        sequence.add_phase(ShutdownPhase(name="Phase 3", execute=quick_phase, timeout=5.0))

        result = await sequence.execute_all(overall_timeout=30.0)

        assert result["elapsed"] < 30.0
        assert len(result["completed"]) == 3
        assert len(result["failed"]) == 0

    @pytest.mark.asyncio
    async def test_http_client_pool_close_failure_continues_shutdown(self):
        """Test that if HTTP client pool close fails, shutdown continues (non-critical)."""
        mock_pool = MagicMock()
        mock_pool._closed = False
        mock_pool.aclose = AsyncMock(side_effect=RuntimeError("Pool close error"))

        async def close_http_client_pool():
            from aragora.observability.http_client_pool import HTTPClientPool

            pool = HTTPClientPool.get_instance()
            if pool and not pool._closed:
                await pool.aclose()

        async def quick_phase():
            await asyncio.sleep(0.01)

        with patch(
            "aragora.observability.http_client_pool.HTTPClientPool.get_instance",
            return_value=mock_pool,
        ):
            sequence = ShutdownSequence()
            sequence.add_phase(
                ShutdownPhase(
                    name="Close HTTP client pool",
                    execute=close_http_client_pool,
                    timeout=5.0,
                    critical=False,
                )
            )
            sequence.add_phase(
                ShutdownPhase(
                    name="After pool close",
                    execute=quick_phase,
                    timeout=5.0,
                )
            )

            result = await sequence.execute_all(overall_timeout=30.0)

            # Pool close should fail but shutdown should continue
            assert "Close HTTP client pool" in result["failed"]
            assert "After pool close" in result["completed"]

    @pytest.mark.asyncio
    async def test_phase_timeout_budgets_sum_less_than_overall(self):
        """Test that main critical phase timeout budgets are reasonable.

        The key requirement is that drain_requests (15s) + wait_for_debates (12s)
        leaves room for other phases within the 30s overall timeout.
        Individual phase timeouts are capped by remaining time via min(phase.timeout, remaining).
        """
        mock_server = MagicMock()
        mock_server._shutting_down = False

        sequence = create_server_shutdown_sequence(mock_server)

        # Find the two main long-running phases
        drain_timeout = 0.0
        debates_timeout = 0.0

        for phase in sequence._phases:
            if phase.name == "Drain in-flight requests":
                drain_timeout = phase.timeout
            elif phase.name == "Wait for in-flight debates":
                debates_timeout = phase.timeout

        # The main critical phases should leave buffer for others
        main_critical_sum = drain_timeout + debates_timeout
        assert main_critical_sum == 27.0, (
            f"Expected drain (15s) + debates (12s) = 27s, got {main_critical_sum}s"
        )
        assert main_critical_sum <= 27.0, (
            f"Main critical phases ({main_critical_sum}s) should leave at least 3s buffer"
        )

    @pytest.mark.asyncio
    async def test_http_client_pool_aclose_handles_already_closed(self):
        """Test that HTTP client pool aclose handles already-closed pool gracefully."""
        mock_pool = MagicMock()
        mock_pool._closed = True  # Pool already closed
        mock_pool.aclose = AsyncMock()

        async def close_http_client_pool():
            try:
                from aragora.observability.http_client_pool import HTTPClientPool

                pool = HTTPClientPool.get_instance()
                if pool and not pool._closed:
                    await pool.aclose()
            except RuntimeError:
                # Pool already closed - this is expected
                pass

        with patch(
            "aragora.observability.http_client_pool.HTTPClientPool.get_instance",
            return_value=mock_pool,
        ):
            sequence = ShutdownSequence()
            sequence.add_phase(
                ShutdownPhase(
                    name="Close HTTP client pool",
                    execute=close_http_client_pool,
                    timeout=5.0,
                    critical=False,
                )
            )

            result = await sequence.execute_all(overall_timeout=30.0)

            # Should complete without calling aclose (pool already closed)
            assert "Close HTTP client pool" in result["completed"]
            mock_pool.aclose.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_drain_requests_phase_timeout_is_15s(self):
        """Test that drain_requests phase uses the updated 15s timeout."""
        mock_server = MagicMock()
        mock_server._shutting_down = False

        sequence = create_server_shutdown_sequence(mock_server)

        # Find the drain requests phase
        drain_phase = None
        for phase in sequence._phases:
            if phase.name == "Drain in-flight requests":
                drain_phase = phase
                break

        assert drain_phase is not None, "Drain in-flight requests phase not found"
        assert drain_phase.timeout == 15.0, (
            f"Expected drain_requests timeout of 15.0s, got {drain_phase.timeout}s"
        )
        assert drain_phase.critical is True

    @pytest.mark.asyncio
    async def test_wait_for_debates_phase_timeout_is_12s(self):
        """Test that wait_for_debates phase uses the updated 12s timeout."""
        mock_server = MagicMock()
        mock_server._shutting_down = False

        sequence = create_server_shutdown_sequence(mock_server)

        # Find the wait for debates phase
        debates_phase = None
        for phase in sequence._phases:
            if phase.name == "Wait for in-flight debates":
                debates_phase = phase
                break

        assert debates_phase is not None, "Wait for in-flight debates phase not found"
        assert debates_phase.timeout == 12.0, (
            f"Expected wait_for_debates timeout of 12.0s, got {debates_phase.timeout}s"
        )
        assert debates_phase.critical is True


class TestShutdownSequencePhases:
    """Tests for shutdown sequence phase configuration."""

    def test_http_client_pool_phase_exists(self):
        """Test that Close HTTP client pool phase exists in shutdown sequence."""
        mock_server = MagicMock()
        mock_server._shutting_down = False

        sequence = create_server_shutdown_sequence(mock_server)

        phase_names = [phase.name for phase in sequence._phases]
        assert "Close HTTP client pool" in phase_names

    def test_http_client_pool_phase_is_non_critical(self):
        """Test that Close HTTP client pool phase is non-critical."""
        mock_server = MagicMock()
        mock_server._shutting_down = False

        sequence = create_server_shutdown_sequence(mock_server)

        pool_phase = None
        for phase in sequence._phases:
            if phase.name == "Close HTTP client pool":
                pool_phase = phase
                break

        assert pool_phase is not None, "Close HTTP client pool phase not found"
        assert pool_phase.critical is False, "HTTP client pool phase should be non-critical"

    def test_http_client_pool_phase_after_http_connector(self):
        """Test that Close HTTP client pool phase comes after Close HTTP connector."""
        mock_server = MagicMock()
        mock_server._shutting_down = False

        sequence = create_server_shutdown_sequence(mock_server)

        phase_names = [phase.name for phase in sequence._phases]

        connector_index = phase_names.index("Close HTTP connector")
        pool_index = phase_names.index("Close HTTP client pool")

        assert pool_index > connector_index, (
            "HTTP client pool phase should come after HTTP connector phase"
        )


class TestShutdownSequenceTimeoutBudget:
    """Tests for shutdown sequence timeout budget management."""

    def test_main_critical_phases_fit_in_timeout_budget(self):
        """Test that main critical phase timeouts fit within 30s overall timeout.

        The execute_all method uses min(phase.timeout, remaining) to cap each phase,
        so the overall execution is bounded by overall_timeout regardless of individual
        phase timeouts. However, the main long-running phases (drain_requests and
        wait_for_debates) should have reasonable individual timeouts.
        """
        mock_server = MagicMock()
        mock_server._shutting_down = False

        sequence = create_server_shutdown_sequence(mock_server)

        # Find the two main long-running critical phases
        drain_timeout = 0.0
        debates_timeout = 0.0

        for phase in sequence._phases:
            if phase.name == "Drain in-flight requests":
                drain_timeout = phase.timeout
            elif phase.name == "Wait for in-flight debates":
                debates_timeout = phase.timeout

        # Main phases should leave buffer (15s + 12s = 27s, leaving 3s buffer)
        main_sum = drain_timeout + debates_timeout
        assert main_sum <= 27.0, (
            f"Main critical phases ({main_sum}s) exceed 27s budget, leaving insufficient buffer"
        )

    def test_drain_and_debates_phases_leave_buffer(self):
        """Test that drain + debates phases leave buffer for other phases."""
        mock_server = MagicMock()
        mock_server._shutting_down = False

        sequence = create_server_shutdown_sequence(mock_server)

        # Find the two main phases
        drain_timeout = 0.0
        debates_timeout = 0.0

        for phase in sequence._phases:
            if phase.name == "Drain in-flight requests":
                drain_timeout = phase.timeout
            elif phase.name == "Wait for in-flight debates":
                debates_timeout = phase.timeout

        combined = drain_timeout + debates_timeout

        # Should be 15 + 12 = 27s, leaving 3s buffer
        assert combined == 27.0, f"Expected 27s combined, got {combined}s"
        assert combined <= 27.0, "Combined timeout should leave at least 3s buffer"
