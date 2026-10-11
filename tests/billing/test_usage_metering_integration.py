"""
Tests for Usage Metering Integration.

Covers:
- Debate token recording
- Agent token recording
- API call recording
- MeteredUsageTracker dual-recording
- Error handling and graceful degradation
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

import pytest

from aragora.billing.usage_metering_integration import (
    MeteredUsageTracker,
    get_metered_usage_tracker,
    record_agent_tokens,
    record_api_call,
    record_debate_tokens,
)


@dataclass
class MockTokenRecord:
    """Mock token usage record."""

    id: str = "record-123"
    total_cost: Decimal = Decimal("0.0125")
    input_cost: Decimal = Decimal("0.0050")
    output_cost: Decimal = Decimal("0.0075")


@dataclass
class MockAPIRecord:
    """Mock API call record."""

    id: str = "api-456"


@pytest.fixture
def mock_meter():
    """Create a mock usage meter."""
    meter = MagicMock()
    meter.record_token_usage = AsyncMock(return_value=MockTokenRecord())
    meter.record_debate_usage = AsyncMock(return_value=None)
    meter.record_api_call = AsyncMock(return_value=MockAPIRecord())
    return meter


@pytest.fixture
def mock_agent():
    """Create a mock agent with metrics."""
    agent = MagicMock()
    agent.name = "claude-agent"
    agent.provider = "anthropic"
    agent.model = "claude-3-opus"
    agent.metrics = MagicMock()
    agent.metrics.total_input_tokens = 1000
    agent.metrics.total_output_tokens = 500
    return agent


@pytest.fixture
def mock_api_agent():
    """Create a mock API-style agent."""
    agent = MagicMock()
    agent.name = "openai-agent"
    agent.agent_type = "openai"
    agent.model = "gpt-4"
    # API style uses total_tokens_in/out instead of metrics
    del agent.metrics  # No metrics attribute
    agent.total_tokens_in = 2000
    agent.total_tokens_out = 1000
    return agent


class TestRecordDebateTokens:
    """Tests for record_debate_tokens function."""

    @pytest.mark.asyncio
    async def test_records_agent_tokens(self, mock_meter, mock_agent):
        """Should record token usage for each agent."""
        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            result = await record_debate_tokens(
                org_id="org-123",
                debate_id="debate-456",
                agents=[mock_agent],
                user_id="user-789",
                rounds=3,
            )

            assert result["total_tokens"] == 1500  # 1000 + 500
            assert result["input_tokens"] == 1000
            assert result["output_tokens"] == 500
            assert result["agents_recorded"] == 1
            assert result["debate_recorded"] is True
            assert result["total_cost"] == "0.0125"

            # Verify token recording was called
            mock_meter.record_token_usage.assert_called_once()
            call_kwargs = mock_meter.record_token_usage.call_args[1]
            assert call_kwargs["org_id"] == "org-123"
            assert call_kwargs["input_tokens"] == 1000
            assert call_kwargs["output_tokens"] == 500

    @pytest.mark.asyncio
    async def test_records_api_agent_tokens(self, mock_meter, mock_api_agent):
        """Should handle API-style agents with different token attributes."""
        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            result = await record_debate_tokens(
                org_id="org-123",
                debate_id="debate-456",
                agents=[mock_api_agent],
            )

            assert result["total_tokens"] == 3000  # 2000 + 1000
            assert result["input_tokens"] == 2000
            assert result["output_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_records_multiple_agents(self, mock_meter, mock_agent, mock_api_agent):
        """Should aggregate tokens from multiple agents."""
        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            result = await record_debate_tokens(
                org_id="org-123",
                debate_id="debate-456",
                agents=[mock_agent, mock_api_agent],
            )

            assert result["total_tokens"] == 4500  # (1000+500) + (2000+1000)
            assert result["agents_recorded"] == 2
            assert mock_meter.record_token_usage.call_count == 2

    @pytest.mark.asyncio
    async def test_records_debate_summary(self, mock_meter, mock_agent):
        """Should record debate-level summary."""
        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            await record_debate_tokens(
                org_id="org-123",
                debate_id="debate-456",
                agents=[mock_agent],
                rounds=5,
                duration_seconds=120,
                user_id="user-789",
            )

            mock_meter.record_debate_usage.assert_called_once()
            call_kwargs = mock_meter.record_debate_usage.call_args[1]
            assert call_kwargs["org_id"] == "org-123"
            assert call_kwargs["debate_id"] == "debate-456"
            assert call_kwargs["rounds"] == 5
            assert call_kwargs["duration_seconds"] == 120

    @pytest.mark.asyncio
    async def test_handles_zero_tokens(self, mock_meter):
        """Should handle agents with zero tokens gracefully."""
        zero_agent = MagicMock()
        zero_agent.metrics = MagicMock()
        zero_agent.metrics.total_input_tokens = 0
        zero_agent.metrics.total_output_tokens = 0

        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            result = await record_debate_tokens(
                org_id="org-123",
                debate_id="debate-456",
                agents=[zero_agent],
            )

            assert result["total_tokens"] == 0
            assert result["agents_recorded"] == 0
            assert result["debate_recorded"] is False
            mock_meter.record_token_usage.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_agent_recording_failure(self, mock_meter, mock_agent):
        """Should continue on agent recording failure."""
        mock_meter.record_token_usage.side_effect = RuntimeError("Recording failed")

        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            result = await record_debate_tokens(
                org_id="org-123",
                debate_id="debate-456",
                agents=[mock_agent],
            )

            # Should still aggregate tokens even if recording failed
            assert result["total_tokens"] == 1500
            assert result["agents_recorded"] == 0  # Recording failed

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("attributes", "expected_provider"),
        [
            ({"provider": None, "agent_type": None}, "unknown"),
            ({"provider": "", "agent_type": None}, "unknown"),
            ({"provider": None}, "unknown"),
            ({}, "unknown"),
            ({"provider": None, "agent_type": "openai"}, "openai"),
            ({"agent_type": "gemini"}, "gemini"),
            ({"provider": "anthropic", "agent_type": "api"}, "anthropic"),
        ],
    )
    async def test_provider_is_always_a_string(self, mock_meter, attributes, expected_provider):
        """Missing or None providers are recorded as "unknown"; real identifiers pass through."""
        agent = SimpleNamespace(
            name="plain-agent",
            model="test-model",
            metrics=None,
            total_tokens_in=10,
            total_tokens_out=5,
            **attributes,
        )

        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            result = await record_debate_tokens(
                org_id="org-123",
                debate_id="debate-456",
                agents=[agent],
            )

        assert result["agents_recorded"] == 1
        provider = mock_meter.record_token_usage.call_args.kwargs["provider"]
        assert isinstance(provider, str)
        assert provider == expected_provider


class TestRecordAgentTokens:
    """Tests for record_agent_tokens function."""

    @pytest.mark.asyncio
    async def test_records_tokens(self, mock_meter):
        """Should record agent token usage."""
        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            result = await record_agent_tokens(
                org_id="org-123",
                agent_name="test-agent",
                provider="anthropic",
                model="claude-3-sonnet",
                input_tokens=500,
                output_tokens=200,
                user_id="user-456",
                debate_id="debate-789",
            )

            assert result["record_id"] == "record-123"
            assert result["total_cost"] == "0.0125"
            assert result["input_cost"] == "0.0050"
            assert result["output_cost"] == "0.0075"

    @pytest.mark.asyncio
    async def test_handles_recording_failure(self, mock_meter):
        """Should return error info on failure."""
        mock_meter.record_token_usage.side_effect = RuntimeError("Service unavailable")

        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            result = await record_agent_tokens(
                org_id="org-123",
                agent_name="test-agent",
                provider="openai",
                model="gpt-4",
                input_tokens=100,
                output_tokens=50,
            )

            assert result["record_id"] is None
            assert result["total_cost"] == "0"
            assert "error" in result


class TestRecordAPICall:
    """Tests for record_api_call function."""

    @pytest.mark.asyncio
    async def test_records_api_call(self, mock_meter):
        """Should record API call."""
        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            result = await record_api_call(
                org_id="org-123",
                endpoint="/api/v1/debates",
                method="POST",
                status_code=201,
                response_time_ms=150,
                user_id="user-456",
            )

            assert result["record_id"] == "api-456"
            assert result["endpoint"] == "/api/v1/debates"

            mock_meter.record_api_call.assert_called_once()
            call_kwargs = mock_meter.record_api_call.call_args[1]
            assert call_kwargs["endpoint"] == "/api/v1/debates"
            assert call_kwargs["method"] == "POST"
            assert call_kwargs["status_code"] == 201

    @pytest.mark.asyncio
    async def test_handles_recording_failure(self, mock_meter):
        """Should return error info on failure."""
        mock_meter.record_api_call.side_effect = RuntimeError("Database error")

        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            result = await record_api_call(
                org_id="org-123",
                endpoint="/api/v1/health",
            )

            assert result["record_id"] is None
            assert "error" in result


class TestMeteredUsageTracker:
    """Tests for MeteredUsageTracker class."""

    def test_init(self):
        """Should initialize with org_id and optional parameters."""
        tracker = MeteredUsageTracker(
            org_id="org-123",
            user_id="user-456",
        )

        assert tracker.org_id == "org-123"
        assert tracker.user_id == "user-456"
        assert tracker._legacy_tracker is None
        assert tracker._meter is None

    def test_init_with_legacy_tracker(self):
        """Should accept a legacy tracker."""
        legacy = MagicMock()
        tracker = MeteredUsageTracker(
            org_id="org-123",
            legacy_tracker=legacy,
        )

        assert tracker._legacy_tracker is legacy

    def test_lazy_meter_loading(self, mock_meter):
        """Should lazy-load the meter on first use."""
        tracker = MeteredUsageTracker(org_id="org-123")
        assert tracker._meter is None

        with patch(
            "aragora.billing.usage_metering.get_usage_meter",
            return_value=mock_meter,
        ):
            meter = tracker._get_meter()
            assert meter is mock_meter
            assert tracker._meter is mock_meter

    def test_get_summary_with_legacy(self):
        """Should delegate get_summary to legacy tracker."""
        legacy = MagicMock()
        legacy.get_summary.return_value = {"total": 1000}

        tracker = MeteredUsageTracker(org_id="org-123", legacy_tracker=legacy)
        result = tracker.get_summary(org_id="org-123")

        assert result == {"total": 1000}
        legacy.get_summary.assert_called_once()

    def test_get_summary_without_legacy(self):
        """Should return None without legacy tracker."""
        tracker = MeteredUsageTracker(org_id="org-123")
        result = tracker.get_summary(org_id="org-123")

        assert result is None


class TestGetMeteredUsageTracker:
    """Tests for get_metered_usage_tracker factory function."""

    def test_creates_tracker(self):
        """Should create a MeteredUsageTracker instance."""
        tracker = get_metered_usage_tracker(
            org_id="org-123",
            user_id="user-456",
        )

        assert isinstance(tracker, MeteredUsageTracker)
        assert tracker.org_id == "org-123"
        assert tracker.user_id == "user-456"

    def test_accepts_legacy_tracker(self):
        """Should pass legacy tracker to instance."""
        legacy = MagicMock()
        tracker = get_metered_usage_tracker(
            org_id="org-123",
            legacy_tracker=legacy,
        )

        assert tracker._legacy_tracker is legacy


class TestModuleExports:
    """Tests for module exports."""

    def test_all_exports(self):
        """Should export expected symbols."""
        from aragora.billing import usage_metering_integration

        assert hasattr(usage_metering_integration, "record_debate_tokens")
        assert hasattr(usage_metering_integration, "record_agent_tokens")
        assert hasattr(usage_metering_integration, "record_api_call")
        assert hasattr(usage_metering_integration, "MeteredUsageTracker")
        assert hasattr(usage_metering_integration, "get_metered_usage_tracker")

        assert "record_debate_tokens" in usage_metering_integration.__all__
        assert "record_agent_tokens" in usage_metering_integration.__all__
        assert "record_api_call" in usage_metering_integration.__all__
