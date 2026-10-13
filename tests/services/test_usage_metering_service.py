"""
Tests for Usage Metering Service.

Tests cover:
- Enum values (MeteringPeriod, UsageType)
- Dataclass records (TokenUsageRecord, DebateUsageRecord, ApiCallRecord)
- Dataclass aggregates (HourlyAggregate, UsageSummary, UsageLimits, UsageBreakdown)
- Token cost calculation
- Usage recording (tokens, debates, API calls)
- Buffer flushing
- Hourly aggregation
- Usage summary and breakdown
- Quota enforcement and limits
- Billing period boundaries
- Module-level get_usage_meter singleton
- Error handling and edge cases
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest


# =============================================================================
# Enum Tests
# =============================================================================


class TestMeteringPeriod:
    """Tests for MeteringPeriod enum."""

    def test_metering_period_values(self):
        """Test MeteringPeriod enum values."""
        from aragora.services.usage_metering import MeteringPeriod

        assert MeteringPeriod.HOUR.value == "hour"
        assert MeteringPeriod.DAY.value == "day"
        assert MeteringPeriod.WEEK.value == "week"
        assert MeteringPeriod.MONTH.value == "month"
        assert MeteringPeriod.QUARTER.value == "quarter"
        assert MeteringPeriod.YEAR.value == "year"


class TestUsageType:
    """Tests for UsageType enum."""

    def test_usage_type_values(self):
        """Test UsageType enum values."""
        from aragora.services.usage_metering import UsageType

        assert UsageType.TOKEN.value == "token"
        assert UsageType.DEBATE.value == "debate"
        assert UsageType.API_CALL.value == "api_call"
        assert UsageType.STORAGE.value == "storage"
        assert UsageType.CONNECTOR.value == "connector"


# =============================================================================
# Dataclass Tests
# =============================================================================


class TestTokenUsageRecord:
    """Tests for TokenUsageRecord dataclass."""

    def test_default_construction(self):
        """Test default values are populated."""
        from aragora.services.usage_metering import TokenUsageRecord

        record = TokenUsageRecord()
        assert record.org_id == ""
        assert record.user_id is None
        assert record.model == ""
        assert record.provider == ""
        assert record.input_tokens == 0
        assert record.output_tokens == 0
        assert record.total_tokens == 0
        assert record.input_cost == Decimal("0")
        assert record.total_cost == Decimal("0")
        assert record.debate_id is None
        assert record.endpoint is None
        assert record.metadata == {}
        assert record.id  # UUID should be generated

    def test_to_dict(self):
        """Test serialization to dictionary."""
        from aragora.services.usage_metering import TokenUsageRecord

        record = TokenUsageRecord(
            org_id="org_1",
            model="claude-opus-4",
            provider="anthropic",
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            input_cost=Decimal("0.015"),
            output_cost=Decimal("0.0375"),
            total_cost=Decimal("0.0525"),
        )
        d = record.to_dict()
        assert d["org_id"] == "org_1"
        assert d["model"] == "claude-opus-4"
        assert d["input_tokens"] == 1000
        assert d["total_cost"] == "0.0525"
        assert "timestamp" in d


class TestDebateUsageRecord:
    """Tests for DebateUsageRecord dataclass."""

    def test_default_construction(self):
        """Test default values are populated."""
        from aragora.services.usage_metering import DebateUsageRecord

        record = DebateUsageRecord()
        assert record.org_id == ""
        assert record.debate_id == ""
        assert record.agent_count == 0
        assert record.rounds == 0
        assert record.total_cost == Decimal("0")
        assert record.duration_seconds == 0

    def test_to_dict(self):
        """Test serialization to dictionary."""
        from aragora.services.usage_metering import DebateUsageRecord

        record = DebateUsageRecord(
            org_id="org_1",
            debate_id="debate_42",
            agent_count=5,
            rounds=3,
            total_tokens=15000,
            total_cost=Decimal("0.75"),
            duration_seconds=120,
        )
        d = record.to_dict()
        assert d["debate_id"] == "debate_42"
        assert d["agent_count"] == 5
        assert d["total_cost"] == "0.75"
        assert d["duration_seconds"] == 120


class TestApiCallRecord:
    """Tests for ApiCallRecord dataclass."""

    def test_default_construction(self):
        """Test default values are populated."""
        from aragora.services.usage_metering import ApiCallRecord

        record = ApiCallRecord()
        assert record.method == "GET"
        assert record.status_code == 200
        assert record.response_time_ms == 0

    def test_to_dict(self):
        """Test serialization to dictionary."""
        from aragora.services.usage_metering import ApiCallRecord

        record = ApiCallRecord(
            org_id="org_1",
            endpoint="/api/v1/debates",
            method="POST",
            status_code=201,
            response_time_ms=150,
        )
        d = record.to_dict()
        assert d["endpoint"] == "/api/v1/debates"
        assert d["method"] == "POST"
        assert d["status_code"] == 201


class TestHourlyAggregate:
    """Tests for HourlyAggregate dataclass."""

    def test_to_dict(self):
        """Test serialization includes model breakdown."""
        from aragora.services.usage_metering import HourlyAggregate, UsageType

        agg = HourlyAggregate(
            org_id="org_1",
            usage_type=UsageType.TOKEN,
            input_tokens=500,
            output_tokens=200,
            total_tokens=700,
            token_cost=Decimal("0.05"),
            tokens_by_model={"anthropic/claude-opus-4": 700},
            cost_by_model={"anthropic/claude-opus-4": Decimal("0.05")},
        )
        d = agg.to_dict()
        assert d["usage_type"] == "token"
        assert d["total_tokens"] == 700
        assert d["tokens_by_model"]["anthropic/claude-opus-4"] == 700
        assert d["cost_by_model"]["anthropic/claude-opus-4"] == "0.05"


class TestUsageSummary:
    """Tests for UsageSummary dataclass."""

    def test_to_dict_structure(self):
        """Test to_dict returns expected nested structure."""
        from aragora.services.usage_metering import MeteringPeriod, UsageSummary

        now = datetime.now(timezone.utc)
        summary = UsageSummary(
            org_id="org_1",
            period_start=now,
            period_end=now + timedelta(days=30),
            period_type=MeteringPeriod.MONTH,
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            token_cost=Decimal("0.10"),
            debate_count=5,
            api_call_count=20,
            token_limit=100_000,
            debate_limit=50,
            api_call_limit=1000,
            token_usage_percent=1.5,
            debate_usage_percent=10.0,
            api_call_usage_percent=2.0,
        )
        d = summary.to_dict()
        assert d["tokens"]["total"] == 1500
        assert d["counts"]["debates"] == 5
        assert d["limits"]["tokens"] == 100_000
        assert d["usage_percent"]["tokens"] == 1.5
        assert d["period_type"] == "month"


class TestUsageLimits:
    """Tests for UsageLimits dataclass."""

    def test_to_dict_structure(self):
        """Test to_dict returns limits, used, percent, and exceeded sections."""
        from aragora.services.usage_metering import UsageLimits

        limits = UsageLimits(
            org_id="org_1",
            tier="starter",
            max_tokens=1_000_000,
            max_debates=50,
            max_api_calls=1_000,
            tokens_used=500_000,
            tokens_percent=50.0,
            tokens_exceeded=False,
        )
        d = limits.to_dict()
        assert d["tier"] == "starter"
        assert d["limits"]["tokens"] == 1_000_000
        assert d["used"]["tokens"] == 500_000
        assert d["percent"]["tokens"] == 50.0
        assert d["exceeded"]["tokens"] is False


class TestUsageBreakdown:
    """Tests for UsageBreakdown dataclass."""

    def test_to_dict_structure(self):
        """Test to_dict returns totals and breakdown sections."""
        from aragora.services.usage_metering import UsageBreakdown

        now = datetime.now(timezone.utc)
        bd = UsageBreakdown(
            org_id="org_1",
            period_start=now,
            period_end=now + timedelta(days=30),
            total_cost=Decimal("5.25"),
            total_tokens=100_000,
            total_debates=10,
            total_api_calls=200,
        )
        d = bd.to_dict()
        assert d["totals"]["cost"] == "5.25"
        assert d["totals"]["tokens"] == 100_000
        assert d["by_model"] == []
        assert d["by_provider"] == []


# =============================================================================
# Token Cost Calculation Tests
# =============================================================================


class TestTokenCostCalculation:
    """Tests for _calculate_token_cost method."""

    def test_known_model_pricing(self):
        """Test cost calculation for a known model."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="anthropic",
            model="claude-opus-4",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # claude-opus-4 input: $5/1M, output: $25/1M
        assert input_cost == Decimal("5.00")
        assert output_cost == Decimal("25.00")

    def test_default_pricing_fallback(self):
        """Test fallback to default pricing for unknown model."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_default.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="anthropic",
            model="unknown-model-xyz",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # default anthropic: $3.00 input, $15.00 output per 1M
        assert input_cost == Decimal("3.00")
        assert output_cost == Decimal("15.00")

    def test_unknown_provider_uses_openrouter_defaults(self):
        """Test completely unknown provider falls back to openrouter pricing."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_unknown.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="some_unknown_provider",
            model="any-model",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # openrouter default: $2.00 input, $8.00 output per 1M
        assert input_cost == Decimal("2.00")
        assert output_cost == Decimal("8.00")

    def test_zero_tokens_gives_zero_cost(self):
        """Test that zero tokens results in zero cost."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_zero.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="anthropic",
            model="claude-opus-4",
            input_tokens=0,
            output_tokens=0,
        )
        assert input_cost == Decimal("0")
        assert output_cost == Decimal("0")


# =============================================================================
# Billing Period Boundary Tests
# =============================================================================


class TestBillingPeriodBoundaries:
    """Tests for _get_period_dates method."""

    def test_hour_period(self):
        """Test hour period boundaries."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        ref = datetime(2026, 1, 15, 14, 30, 45, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("hour", ref)
        assert start == datetime(2026, 1, 15, 14, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 1, 15, 15, 0, 0, tzinfo=timezone.utc)

    def test_day_period(self):
        """Test day period boundaries."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        ref = datetime(2026, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("day", ref)
        assert start == datetime(2026, 1, 15, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 1, 16, 0, 0, 0, tzinfo=timezone.utc)

    def test_month_period(self):
        """Test month period boundaries."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        ref = datetime(2026, 3, 15, 0, 0, 0, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("month", ref)
        assert start == datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_month_period_december_wraps_year(self):
        """Test December month boundary wraps to January of next year."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        ref = datetime(2026, 12, 10, 0, 0, 0, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("month", ref)
        assert start == datetime(2026, 12, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_year_period(self):
        """Test year period boundaries."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        ref = datetime(2026, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("year", ref)
        assert start == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_unknown_period_defaults_to_month(self):
        """Test that an unrecognized period falls back to month boundaries."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        ref = datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("bogus", ref)
        assert start == datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)


# =============================================================================
# Usage Recording Tests
# =============================================================================


class TestRecordTokenUsage:
    """Tests for record_token_usage."""

    @pytest.mark.asyncio
    async def test_record_token_usage_returns_record(self, tmp_path):
        """Test recording token usage returns a populated record."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1000,
            output_tokens=500,
            model="claude-sonnet-4",
            provider="anthropic",
            user_id="user_1",
        )

        assert record.org_id == "org_1"
        assert record.input_tokens == 1000
        assert record.output_tokens == 500
        assert record.total_tokens == 1500
        assert record.total_cost > Decimal("0")
        assert record.user_id == "user_1"
        await meter.close()

    @pytest.mark.asyncio
    async def test_record_token_usage_auto_initializes(self, tmp_path):
        """Test that recording auto-initializes the meter if needed."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter_auto.db")
        assert not meter._initialized

        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o",
            provider="openai",
        )

        assert meter._initialized
        assert record.org_id == "org_1"
        await meter.close()


class TestRecordDebateUsage:
    """Tests for record_debate_usage."""

    @pytest.mark.asyncio
    async def test_record_debate_with_explicit_cost(self, tmp_path):
        """Test recording debate usage with an explicit total cost."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        record = await meter.record_debate_usage(
            org_id="org_1",
            debate_id="debate_1",
            agent_count=4,
            rounds=3,
            total_tokens=10000,
            total_cost=Decimal("1.50"),
            duration_seconds=60,
        )

        assert record.debate_id == "debate_1"
        assert record.agent_count == 4
        assert record.total_cost == Decimal("1.50")
        await meter.close()

    @pytest.mark.asyncio
    async def test_record_debate_without_cost_estimates(self, tmp_path):
        """Test recording debate usage auto-calculates cost when not provided."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        record = await meter.record_debate_usage(
            org_id="org_1",
            debate_id="debate_2",
            agent_count=3,
            total_tokens=5000,
        )

        assert record.total_cost > Decimal("0")
        await meter.close()


class TestRecordApiCall:
    """Tests for record_api_call."""

    @pytest.mark.asyncio
    async def test_record_api_call_returns_record(self, tmp_path):
        """Test recording an API call returns a populated record."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        record = await meter.record_api_call(
            org_id="org_1",
            endpoint="/api/v1/debates",
            method="POST",
            status_code=201,
            response_time_ms=250,
        )

        assert record.endpoint == "/api/v1/debates"
        assert record.method == "POST"
        assert record.status_code == 201
        assert record.response_time_ms == 250
        await meter.close()


# =============================================================================
# Buffer Flushing Tests
# =============================================================================


class TestBufferFlushing:
    """Tests for buffer flushing behavior."""

    @pytest.mark.asyncio
    async def test_flush_all_persists_buffered_records(self, tmp_path):
        """Test that flush_all writes buffered records to the database."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o",
            provider="openai",
        )
        await meter.record_debate_usage(
            org_id="org_1",
            debate_id="d1",
            agent_count=2,
        )
        await meter.record_api_call(
            org_id="org_1",
            endpoint="/test",
        )

        # Records are buffered, not yet in DB
        assert len(meter._token_buffer) == 1
        assert len(meter._debate_buffer) == 1
        assert len(meter._api_buffer) == 1

        await meter.flush_all()

        # Buffers should be empty after flush
        assert len(meter._token_buffer) == 0
        assert len(meter._debate_buffer) == 0
        assert len(meter._api_buffer) == 0

        # Verify records exist in database
        cursor = meter._conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM token_usage WHERE org_id = 'org_1'")
        assert cursor.fetchone()["c"] == 1
        cursor.execute("SELECT COUNT(*) as c FROM debate_usage WHERE org_id = 'org_1'")
        assert cursor.fetchone()["c"] == 1
        cursor.execute("SELECT COUNT(*) as c FROM api_usage WHERE org_id = 'org_1'")
        assert cursor.fetchone()["c"] == 1

        await meter.close()

    @pytest.mark.asyncio
    async def test_auto_flush_when_buffer_full(self, tmp_path):
        """Test that buffer auto-flushes when reaching buffer_size."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        meter._buffer_size = 3  # Small buffer for testing
        await meter.initialize()

        for i in range(3):
            await meter.record_api_call(
                org_id="org_1",
                endpoint=f"/api/test/{i}",
            )

        # Buffer should have been auto-flushed
        assert len(meter._api_buffer) == 0

        cursor = meter._conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM api_usage WHERE org_id = 'org_1'")
        assert cursor.fetchone()["c"] == 3

        await meter.close()


# =============================================================================
# Hourly Aggregation Tests
# =============================================================================


class TestHourlyAggregation:
    """Tests for hourly aggregate updates."""

    @pytest.mark.asyncio
    async def test_token_usage_updates_hourly_aggregate(self, tmp_path):
        """Test that recording tokens updates hourly aggregates."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=500,
            output_tokens=200,
            model="claude-sonnet-4",
            provider="anthropic",
        )

        cursor = meter._conn.cursor()
        cursor.execute("SELECT * FROM hourly_aggregates WHERE org_id = 'org_1'")
        row = cursor.fetchone()
        assert row is not None
        assert row["input_tokens"] == 500
        assert row["output_tokens"] == 200
        assert row["total_tokens"] == 700

        await meter.close()

    @pytest.mark.asyncio
    async def test_multiple_recordings_accumulate_in_aggregate(self, tmp_path):
        """Test that multiple recordings in the same hour accumulate."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o",
            provider="openai",
        )
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=200,
            output_tokens=100,
            model="gpt-4o",
            provider="openai",
        )

        cursor = meter._conn.cursor()
        cursor.execute("SELECT * FROM hourly_aggregates WHERE org_id = 'org_1'")
        row = cursor.fetchone()
        assert row["input_tokens"] == 300
        assert row["output_tokens"] == 150
        assert row["total_tokens"] == 450

        await meter.close()


# =============================================================================
# Usage Summary and Breakdown Tests
# =============================================================================


class TestGetUsageSummary:
    """Tests for get_usage_summary."""

    @pytest.mark.asyncio
    async def test_summary_with_no_usage(self, tmp_path):
        """Test summary for an org with no recorded usage."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        summary = await meter.get_usage_summary(
            org_id="org_empty",
            period="month",
            tier="starter",
        )

        assert summary.org_id == "org_empty"
        assert summary.total_tokens == 0
        assert summary.debate_count == 0
        assert summary.api_call_count == 0
        assert summary.token_limit == 1_000_000
        assert summary.debate_limit == 50

        await meter.close()

    @pytest.mark.asyncio
    async def test_summary_calculates_usage_percent(self, tmp_path):
        """Test that summary correctly calculates usage percentages."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        # Record some usage within current month
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=50_000,
            output_tokens=50_000,
            model="gpt-4o",
            provider="openai",
        )

        summary = await meter.get_usage_summary(
            org_id="org_1",
            period="month",
            tier="free",
        )

        # free tier: max_tokens=100,000
        assert summary.total_tokens == 100_000
        assert summary.token_usage_percent == 100.0
        assert summary.token_limit == 100_000

        await meter.close()


class TestGetUsageBreakdown:
    """Tests for get_usage_breakdown."""

    @pytest.mark.asyncio
    async def test_breakdown_with_recorded_data(self, tmp_path):
        """Test breakdown includes recorded token, debate, and API data."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1000,
            output_tokens=500,
            model="claude-sonnet-4",
            provider="anthropic",
            user_id="user_A",
        )
        await meter.record_debate_usage(
            org_id="org_1",
            debate_id="d1",
            agent_count=3,
        )
        await meter.record_api_call(
            org_id="org_1",
            endpoint="/test",
        )

        await meter.flush_all()

        breakdown = await meter.get_usage_breakdown(org_id="org_1")
        assert breakdown.total_tokens > 0

        await meter.close()


# =============================================================================
# Quota Enforcement Tests
# =============================================================================


class TestGetUsageLimits:
    """Tests for get_usage_limits and quota enforcement."""

    @pytest.mark.asyncio
    async def test_limits_for_free_tier(self, tmp_path):
        """Test limits reflect free tier caps."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        limits = await meter.get_usage_limits(org_id="org_1", tier="free")

        assert limits.max_tokens == 100_000
        assert limits.max_debates == 10
        assert limits.max_api_calls == 100
        assert limits.tokens_exceeded is False

        await meter.close()

    @pytest.mark.asyncio
    async def test_limits_exceeded_flag(self, tmp_path):
        """Test that exceeded flag is set when usage surpasses limits."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        # Record enough tokens to exceed free tier (100k)
        for _ in range(5):
            await meter.record_token_usage(
                org_id="org_quota",
                input_tokens=15_000,
                output_tokens=15_000,
                model="gpt-4o-mini",
                provider="openai",
            )

        limits = await meter.get_usage_limits(org_id="org_quota", tier="free")

        # 5 * 30_000 = 150_000 > 100_000
        assert limits.tokens_used == 150_000
        assert limits.tokens_exceeded is True
        assert limits.tokens_percent > 100.0

        await meter.close()

    @pytest.mark.asyncio
    async def test_enterprise_effectively_unlimited(self, tmp_path):
        """Test enterprise tier has very high caps."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()

        limits = await meter.get_usage_limits(org_id="org_1", tier="enterprise")

        assert limits.max_tokens == 999_999_999
        assert limits.max_debates == 999_999
        assert limits.tokens_exceeded is False

        await meter.close()


# =============================================================================
# Module-Level Singleton Tests
# =============================================================================


class TestGetUsageMeter:
    """Tests for get_usage_meter module-level function."""

    def test_returns_usage_meter_instance(self):
        """Test that get_usage_meter returns a UsageMeter."""
        from aragora.billing import usage_metering
        from aragora.services.usage_metering import UsageMeter

        # Reset global state
        original = usage_metering._usage_meter
        usage_metering._usage_meter = None
        try:
            meter = usage_metering.get_usage_meter()
            assert isinstance(meter, UsageMeter)
        finally:
            usage_metering._usage_meter = original

    def test_returns_same_instance(self):
        """Test singleton behavior returns the same instance."""
        from aragora.billing import usage_metering

        original = usage_metering._usage_meter
        usage_metering._usage_meter = None
        try:
            meter1 = usage_metering.get_usage_meter()
            meter2 = usage_metering.get_usage_meter()
            assert meter1 is meter2
        finally:
            usage_metering._usage_meter = original


# =============================================================================
# Tier Usage Caps Tests
# =============================================================================


class TestTierUsageCaps:
    """Tests for TIER_USAGE_CAPS configuration."""

    def test_all_tiers_defined(self):
        """Test all expected tiers are present."""
        from aragora.services.usage_metering import TIER_USAGE_CAPS

        expected_tiers = {"free", "starter", "professional", "enterprise"}
        assert set(TIER_USAGE_CAPS.keys()) == expected_tiers

    def test_tiers_have_increasing_limits(self):
        """Test that tiers have non-decreasing token limits."""
        from aragora.services.usage_metering import TIER_USAGE_CAPS

        tier_order = ["free", "starter", "professional", "enterprise"]
        for i in range(len(tier_order) - 1):
            current = TIER_USAGE_CAPS[tier_order[i]]["max_tokens"]
            next_tier = TIER_USAGE_CAPS[tier_order[i + 1]]["max_tokens"]
            assert current <= next_tier, (
                f"{tier_order[i]} ({current}) should be <= {tier_order[i + 1]} ({next_tier})"
            )


# =============================================================================
# Error Handling and Edge Cases
# =============================================================================


class TestErrorHandlingAndEdgeCases:
    """Tests for error handling and edge cases."""

    @pytest.mark.asyncio
    async def test_close_without_initialize(self, tmp_path):
        """Test that close works even if never initialized."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        # Should not raise
        await meter.close()

    @pytest.mark.asyncio
    async def test_double_initialize_is_idempotent(self, tmp_path):
        """Test that calling initialize twice does not error."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()
        await meter.initialize()  # Should be a no-op
        assert meter._initialized is True
        await meter.close()

    @pytest.mark.asyncio
    async def test_flush_empty_buffers(self, tmp_path):
        """Test flushing empty buffers is a no-op."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=tmp_path / "meter.db")
        await meter.initialize()
        # Should not raise
        await meter.flush_all()
        await meter.close()
