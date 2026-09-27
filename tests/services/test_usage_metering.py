"""
Comprehensive Tests for Usage Metering Service.

Enterprise billing module with revenue impact - requires thorough testing.

Tests cover:
1. Token usage recording (input/output, per-model, per-provider)
2. Cost calculation (pricing per model, decimal precision, currency handling)
3. Hourly aggregation (bucket boundaries, midnight rollover, DST edge cases)
4. Usage summary queries (daily, monthly, by model/provider breakdowns)
5. Multi-org isolation (no billing cross-contamination)
6. Edge cases (zero usage, very large token counts, concurrent recording)
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from unittest.mock import patch, AsyncMock
import threading

import pytest


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_db_path(tmp_path):
    """Temporary database path for each test."""
    return tmp_path / "test_usage_metering.db"


@pytest.fixture
async def meter(temp_db_path):
    """Fresh UsageMeter instance with temporary database."""
    from aragora.services.usage_metering import UsageMeter

    m = UsageMeter(db_path=temp_db_path)
    await m.initialize()
    yield m
    await m.close()


@pytest.fixture
async def meter_small_buffer(temp_db_path):
    """UsageMeter with small buffer size for testing auto-flush."""
    from aragora.services.usage_metering import UsageMeter

    m = UsageMeter(db_path=temp_db_path)
    m._buffer_size = 3
    await m.initialize()
    yield m
    await m.close()


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

    def test_metering_period_from_value(self):
        """Test creating MeteringPeriod from string value."""
        from aragora.services.usage_metering import MeteringPeriod

        assert MeteringPeriod("hour") == MeteringPeriod.HOUR
        assert MeteringPeriod("month") == MeteringPeriod.MONTH


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

    def test_to_dict_serialization(self):
        """Test serialization to dictionary with cost as string."""
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

    def test_unique_id_generation(self):
        """Test each record gets unique ID."""
        from aragora.services.usage_metering import TokenUsageRecord

        r1 = TokenUsageRecord()
        r2 = TokenUsageRecord()
        assert r1.id != r2.id


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

    def test_to_dict_serialization(self):
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

    def test_to_dict_serialization(self):
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

    def test_to_dict_includes_model_breakdown(self):
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

    def test_to_dict_nested_structure(self):
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
# Token Cost Calculation Tests - Decimal Precision
# =============================================================================


class TestTokenCostCalculation:
    """Tests for _calculate_token_cost method with focus on precision."""

    def test_known_model_anthropic_opus(self):
        """Test cost calculation for Claude Opus 4."""
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

    def test_known_model_anthropic_sonnet(self):
        """Test cost calculation for Claude Sonnet 4."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="anthropic",
            model="claude-sonnet-4",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # claude-sonnet-4 input: $3/1M, output: $15/1M
        assert input_cost == Decimal("3.00")
        assert output_cost == Decimal("15.00")

    def test_known_model_anthropic_haiku(self):
        """Test cost calculation for Claude Haiku 4."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="anthropic",
            model="claude-haiku-4",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # claude-haiku-4 input: $0.25/1M, output: $1.25/1M
        assert input_cost == Decimal("0.25")
        assert output_cost == Decimal("1.25")

    def test_known_model_openai_gpt4o(self):
        """Test cost calculation for GPT-4o."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="openai",
            model="gpt-4o",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # gpt-4o input: $2.50/1M, output: $10/1M
        assert input_cost == Decimal("2.50")
        assert output_cost == Decimal("10.00")

    def test_known_model_openai_gpt4o_mini(self):
        """Test cost calculation for GPT-4o-mini."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # gpt-4o-mini input: $0.15/1M, output: $0.60/1M
        assert input_cost == Decimal("0.15")
        assert output_cost == Decimal("0.60")

    def test_known_model_openai_o1(self):
        """Test cost calculation for o1."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="openai",
            model="o1",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # o1 input: $15/1M, output: $60/1M
        assert input_cost == Decimal("15.00")
        assert output_cost == Decimal("60.00")

    @pytest.mark.parametrize(
        ("provider", "model", "input_price", "output_price"),
        [
            ("anthropic", "claude-opus-4-8", Decimal("5.00"), Decimal("25.00")),
            ("anthropic", "claude-opus-4-7", Decimal("5.00"), Decimal("25.00")),
            ("anthropic", "claude-opus-4", Decimal("5.00"), Decimal("25.00")),
            ("anthropic", "claude-haiku-4.5", Decimal("1.00"), Decimal("5.00")),
            ("openai", "gpt-5.5", Decimal("5.00"), Decimal("30.00")),  # live 2026-07-16
            ("google", "gemini-3.5-flash", Decimal("1.50"), Decimal("9.00")),
            ("google", "gemini-3.1-pro", Decimal("2.00"), Decimal("12.00")),
            ("google", "gemini-3.1-pro-preview", Decimal("2.00"), Decimal("12.00")),
            ("openrouter", "openai/gpt-5.5", Decimal("5.00"), Decimal("30.00")),
            (
                "openrouter",
                "anthropic/claude-opus-4-8",
                Decimal("5.00"),
                Decimal("25.00"),
            ),
            (
                "openrouter",
                "anthropic/claude-opus-4.8",
                Decimal("5.00"),
                Decimal("25.00"),
            ),
            (
                "openrouter",
                "anthropic/claude-opus-4-7",
                Decimal("5.00"),
                Decimal("25.00"),
            ),
            (
                "openrouter",
                "anthropic/claude-haiku-4-5",
                Decimal("1.00"),
                Decimal("5.00"),
            ),
            (
                "openrouter",
                "anthropic/claude-haiku-4.5",
                Decimal("1.00"),
                Decimal("5.00"),
            ),
            (
                "openrouter",
                "anthropic/claude-haiku-4-5-20251001",
                Decimal("1.00"),
                Decimal("5.00"),
            ),
            (
                "openrouter",
                "google/gemini-3.5-flash",
                Decimal("1.50"),
                Decimal("9.00"),
            ),
            ("anthropic", "claude-haiku-4-5", Decimal("1.00"), Decimal("5.00")),
            (
                "anthropic",
                "claude-haiku-4-5-20251001",
                Decimal("1.00"),
                Decimal("5.00"),
            ),
        ],
    )
    def test_calibrated_models_use_explicit_usage_meter_prices(
        self,
        provider: str,
        model: str,
        input_price: Decimal,
        output_price: Decimal,
    ):
        """Calibrated models must not fall back to provider defaults."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider=provider,
            model=model,
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )

        assert input_cost == input_price
        assert output_cost == output_price

    def test_known_model_google_gemini_pro(self):
        """Test cost calculation for Gemini Pro."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="google",
            model="gemini-pro",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # gemini-pro input: $1.25/1M, output: $5/1M
        assert input_cost == Decimal("1.25")
        assert output_cost == Decimal("5.00")

    def test_known_model_deepseek_v4_pro(self):
        """Test cost calculation for DeepSeek V4 Pro."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="deepseek",
            model="deepseek-v4-pro",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # deepseek-v4-pro input: $1.74/1M, output: $3.48/1M
        assert input_cost == Decimal("1.74")
        assert output_cost == Decimal("3.48")

    def test_known_model_xai_grok(self):
        """Test cost calculation for Grok 2."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="xai",
            model="grok-2",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # grok-2 input: $2/1M, output: $10/1M
        assert input_cost == Decimal("2.00")
        assert output_cost == Decimal("10.00")

    def test_known_model_mistral_large(self):
        """Test cost calculation for Mistral Large."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="mistral",
            model="mistral-large",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # mistral-large input: $2/1M, output: $6/1M
        assert input_cost == Decimal("2.00")
        assert output_cost == Decimal("6.00")

    def test_known_model_mistral_codestral(self):
        """Test cost calculation for Codestral."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_calc.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="mistral",
            model="codestral",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
        )
        # codestral input: $0.20/1M, output: $0.60/1M
        assert input_cost == Decimal("0.20")
        assert output_cost == Decimal("0.60")

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

    def test_cost_decimal_precision_small_tokens(self):
        """Test decimal precision is preserved for small token counts."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_precision.db"))
        input_cost, output_cost = meter._calculate_token_cost(
            provider="anthropic",
            model="claude-sonnet-4",
            input_tokens=1,  # Single token
            output_tokens=1,
        )
        # 1 token * $3 / 1M = $0.000003
        # 1 token * $15 / 1M = $0.000015
        assert input_cost == Decimal("0.000003")
        assert output_cost == Decimal("0.000015")

    def test_cost_decimal_precision_no_floating_point_errors(self):
        """Test decimal calculation avoids floating point errors."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_cost_fp.db"))
        # Use numbers that would cause floating point errors
        input_cost, output_cost = meter._calculate_token_cost(
            provider="openai",
            model="gpt-4o-mini",
            input_tokens=333333,
            output_tokens=666667,
        )
        # Verify result is exact Decimal, not float-approximated
        assert isinstance(input_cost, Decimal)
        assert isinstance(output_cost, Decimal)
        # Verify precision: 333333 * 0.15 / 1000000 = 0.04999995
        expected_input = Decimal("333333") * Decimal("0.15") / Decimal("1000000")
        assert input_cost == expected_input


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

    def test_week_period(self):
        """Test week period boundaries (Monday start)."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        # Jan 15, 2026 is a Thursday
        ref = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("week", ref)
        # Monday Jan 12, 2026
        assert start == datetime(2026, 1, 12, 0, 0, 0, tzinfo=timezone.utc)
        # Monday Jan 19, 2026
        assert end == datetime(2026, 1, 19, 0, 0, 0, tzinfo=timezone.utc)

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

    def test_quarter_period_q1(self):
        """Test Q1 quarter period boundaries."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        ref = datetime(2026, 2, 15, 0, 0, 0, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("quarter", ref)
        assert start == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 4, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_quarter_period_q4(self):
        """Test Q4 quarter period boundaries (year wrap)."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        ref = datetime(2026, 11, 15, 0, 0, 0, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("quarter", ref)
        assert start == datetime(2026, 10, 1, 0, 0, 0, tzinfo=timezone.utc)
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

    def test_midnight_boundary(self):
        """Test period boundaries at midnight."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        # Exactly at midnight
        ref = datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("day", ref)
        assert start == datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2026, 3, 2, 0, 0, 0, tzinfo=timezone.utc)

    def test_leap_year_february(self):
        """Test February boundaries in leap year."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=Path("/tmp/test_period.db"))
        # 2028 is a leap year
        ref = datetime(2028, 2, 15, 0, 0, 0, tzinfo=timezone.utc)
        start, end = meter._get_period_dates("month", ref)
        assert start == datetime(2028, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert end == datetime(2028, 3, 1, 0, 0, 0, tzinfo=timezone.utc)


# =============================================================================
# Token Usage Recording Tests
# =============================================================================


class TestRecordTokenUsage:
    """Tests for record_token_usage method."""

    @pytest.mark.asyncio
    async def test_record_token_usage_returns_record(self, meter):
        """Test recording token usage returns a populated record."""
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

    @pytest.mark.asyncio
    async def test_record_token_usage_auto_initializes(self, temp_db_path):
        """Test that recording auto-initializes the meter if needed."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=temp_db_path)
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

    @pytest.mark.asyncio
    async def test_record_token_usage_with_metadata(self, meter):
        """Test recording token usage with metadata."""
        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o",
            provider="openai",
            metadata={"debate_phase": "proposal", "agent": "claude"},
        )

        assert record.metadata == {"debate_phase": "proposal", "agent": "claude"}

    @pytest.mark.asyncio
    async def test_record_token_usage_with_debate_id(self, meter):
        """Test recording token usage linked to debate."""
        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o",
            provider="openai",
            debate_id="debate_123",
        )

        assert record.debate_id == "debate_123"

    @pytest.mark.asyncio
    async def test_record_token_usage_calculates_cost_correctly(self, meter):
        """Test cost calculation is correct for known model."""
        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model="claude-opus-4",
            provider="anthropic",
        )

        # claude-opus-4: $5/1M input, $25/1M output
        assert record.input_cost == Decimal("5.00")
        assert record.output_cost == Decimal("25.00")
        assert record.total_cost == Decimal("30.00")

    @pytest.mark.parametrize(
        ("provider", "model", "input_price", "output_price"),
        [
            ("anthropic", "claude-opus-4-8", Decimal("5.00"), Decimal("25.00")),
            ("anthropic", "claude-opus-4", Decimal("5.00"), Decimal("25.00")),
            ("anthropic", "claude-haiku-4.5", Decimal("1.00"), Decimal("5.00")),
            ("openai", "gpt-5.5", Decimal("5.00"), Decimal("30.00")),  # live 2026-07-16
            ("google", "gemini-3.5-flash", Decimal("1.50"), Decimal("9.00")),
            ("google", "gemini-3.1-pro", Decimal("2.00"), Decimal("12.00")),
            ("google", "gemini-3.1-pro-preview", Decimal("2.00"), Decimal("12.00")),
            ("openrouter", "openai/gpt-5.5", Decimal("5.00"), Decimal("30.00")),
            (
                "openrouter",
                "anthropic/claude-opus-4-8",
                Decimal("5.00"),
                Decimal("25.00"),
            ),
            (
                "openrouter",
                "anthropic/claude-opus-4.8",
                Decimal("5.00"),
                Decimal("25.00"),
            ),
            (
                "openrouter",
                "anthropic/claude-opus-4-7",
                Decimal("5.00"),
                Decimal("25.00"),
            ),
            (
                "openrouter",
                "anthropic/claude-haiku-4-5",
                Decimal("1.00"),
                Decimal("5.00"),
            ),
            (
                "openrouter",
                "anthropic/claude-haiku-4.5",
                Decimal("1.00"),
                Decimal("5.00"),
            ),
            (
                "openrouter",
                "anthropic/claude-haiku-4-5-20251001",
                Decimal("1.00"),
                Decimal("5.00"),
            ),
            (
                "openrouter",
                "google/gemini-3.5-flash",
                Decimal("1.50"),
                Decimal("9.00"),
            ),
            ("anthropic", "claude-haiku-4-5", Decimal("1.00"), Decimal("5.00")),
            (
                "anthropic",
                "claude-haiku-4-5-20251001",
                Decimal("1.00"),
                Decimal("5.00"),
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_record_token_usage_uses_calibrated_prices(
        self,
        meter,
        provider: str,
        model: str,
        input_price: Decimal,
        output_price: Decimal,
    ):
        """Recording must use calibrated prices, not provider defaults."""
        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            model=model,
            provider=provider,
        )

        assert record.input_cost == input_price
        assert record.output_cost == output_price
        assert record.total_cost == input_price + output_price

    @pytest.mark.asyncio
    async def test_record_per_model_tracking(self, meter):
        """Test multiple models are tracked separately."""
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1000,
            output_tokens=500,
            model="claude-opus-4",
            provider="anthropic",
        )
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=2000,
            output_tokens=1000,
            model="gpt-4o",
            provider="openai",
        )
        await meter.flush_all()

        summary = await meter.get_usage_summary(org_id="org_1", period="month")
        assert "anthropic/claude-opus-4" in summary.tokens_by_model
        assert "openai/gpt-4o" in summary.tokens_by_model
        assert summary.tokens_by_model["anthropic/claude-opus-4"] == 1500
        assert summary.tokens_by_model["openai/gpt-4o"] == 3000

    @pytest.mark.asyncio
    async def test_record_per_provider_tracking(self, meter):
        """Test multiple providers are tracked separately."""
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1000,
            output_tokens=500,
            model="claude-opus-4",
            provider="anthropic",
        )
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=2000,
            output_tokens=1000,
            model="gpt-4o",
            provider="openai",
        )
        await meter.flush_all()

        summary = await meter.get_usage_summary(org_id="org_1", period="month")
        assert "anthropic" in summary.tokens_by_provider
        assert "openai" in summary.tokens_by_provider


# =============================================================================
# Debate Usage Recording Tests
# =============================================================================


class TestRecordDebateUsage:
    """Tests for record_debate_usage method."""

    @pytest.mark.asyncio
    async def test_record_debate_with_explicit_cost(self, meter):
        """Test recording debate usage with an explicit total cost."""
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

    @pytest.mark.asyncio
    async def test_record_debate_without_cost_estimates(self, meter):
        """Test recording debate usage auto-calculates cost when not provided."""
        record = await meter.record_debate_usage(
            org_id="org_1",
            debate_id="debate_2",
            agent_count=3,
            total_tokens=5000,
        )

        assert record.total_cost > Decimal("0")

    @pytest.mark.asyncio
    async def test_record_debate_with_user_id(self, meter):
        """Test recording debate usage with user_id."""
        record = await meter.record_debate_usage(
            org_id="org_1",
            debate_id="debate_1",
            agent_count=3,
            user_id="user_123",
        )

        assert record.user_id == "user_123"


# =============================================================================
# API Call Recording Tests
# =============================================================================


class TestRecordApiCall:
    """Tests for record_api_call method."""

    @pytest.mark.asyncio
    async def test_record_api_call_returns_record(self, meter):
        """Test recording an API call returns a populated record."""
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

    @pytest.mark.asyncio
    async def test_record_api_call_with_metadata(self, meter):
        """Test recording API call with metadata."""
        record = await meter.record_api_call(
            org_id="org_1",
            endpoint="/api/v1/debates",
            metadata={"client": "web", "version": "1.0"},
        )

        assert record.metadata == {"client": "web", "version": "1.0"}


# =============================================================================
# Buffer Flushing Tests
# =============================================================================


class TestBufferFlushing:
    """Tests for buffer flushing behavior."""

    @pytest.mark.asyncio
    async def test_flush_all_persists_buffered_records(self, meter):
        """Test that flush_all writes buffered records to the database."""
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

        # Records are buffered
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

    @pytest.mark.asyncio
    async def test_auto_flush_when_buffer_full(self, meter_small_buffer):
        """Test that buffer auto-flushes when reaching buffer_size."""
        meter = meter_small_buffer

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

    @pytest.mark.asyncio
    async def test_flush_empty_buffers_is_noop(self, meter):
        """Test flushing empty buffers is a no-op."""
        # Should not raise
        await meter.flush_all()
        await meter.flush_all()  # Call twice


# =============================================================================
# Hourly Aggregation Tests
# =============================================================================


class TestHourlyAggregation:
    """Tests for hourly aggregate updates."""

    @pytest.mark.asyncio
    async def test_token_usage_updates_hourly_aggregate(self, meter):
        """Test that recording tokens updates hourly aggregates."""
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

    @pytest.mark.asyncio
    async def test_multiple_recordings_accumulate_in_aggregate(self, meter):
        """Test that multiple recordings in the same hour accumulate."""
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

    @pytest.mark.asyncio
    async def test_hourly_aggregate_tracks_model_breakdown(self, meter):
        """Test hourly aggregate tracks per-model token breakdown."""
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
            model="claude-opus-4",
            provider="anthropic",
        )

        cursor = meter._conn.cursor()
        cursor.execute("SELECT tokens_by_model FROM hourly_aggregates WHERE org_id = 'org_1'")
        row = cursor.fetchone()
        tokens_by_model = json.loads(row["tokens_by_model"])
        assert "openai/gpt-4o" in tokens_by_model
        assert "anthropic/claude-opus-4" in tokens_by_model
        assert tokens_by_model["openai/gpt-4o"] == 150
        assert tokens_by_model["anthropic/claude-opus-4"] == 300

    @pytest.mark.asyncio
    async def test_hourly_aggregate_debate_count(self, meter):
        """Test hourly aggregate tracks debate count."""
        await meter.record_debate_usage(
            org_id="org_1",
            debate_id="d1",
            agent_count=3,
        )
        await meter.record_debate_usage(
            org_id="org_1",
            debate_id="d2",
            agent_count=4,
        )

        cursor = meter._conn.cursor()
        cursor.execute("SELECT debate_count FROM hourly_aggregates WHERE org_id = 'org_1'")
        row = cursor.fetchone()
        assert row["debate_count"] == 2

    @pytest.mark.asyncio
    async def test_hourly_aggregate_api_call_count(self, meter):
        """Test hourly aggregate tracks API call count."""
        await meter.record_api_call(org_id="org_1", endpoint="/a")
        await meter.record_api_call(org_id="org_1", endpoint="/b")
        await meter.record_api_call(org_id="org_1", endpoint="/c")

        cursor = meter._conn.cursor()
        cursor.execute("SELECT api_call_count FROM hourly_aggregates WHERE org_id = 'org_1'")
        row = cursor.fetchone()
        assert row["api_call_count"] == 3


# =============================================================================
# Usage Summary Tests
# =============================================================================


class TestGetUsageSummary:
    """Tests for get_usage_summary method."""

    @pytest.mark.asyncio
    async def test_summary_with_no_usage(self, meter):
        """Test summary for an org with no recorded usage."""
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

    @pytest.mark.asyncio
    async def test_summary_calculates_usage_percent(self, meter):
        """Test that summary correctly calculates usage percentages."""
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

    @pytest.mark.asyncio
    async def test_summary_by_model_breakdown(self, meter):
        """Test summary includes by-model breakdown."""
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1000,
            output_tokens=500,
            model="claude-opus-4",
            provider="anthropic",
        )
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=2000,
            output_tokens=1000,
            model="gpt-4o",
            provider="openai",
        )
        await meter.flush_all()

        summary = await meter.get_usage_summary(org_id="org_1", period="month")

        assert len(summary.tokens_by_model) == 2
        assert len(summary.cost_by_model) == 2

    @pytest.mark.asyncio
    async def test_summary_by_provider_breakdown(self, meter):
        """Test summary includes by-provider breakdown."""
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1000,
            output_tokens=500,
            model="claude-opus-4",
            provider="anthropic",
        )
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=2000,
            output_tokens=1000,
            model="gpt-4o",
            provider="openai",
        )
        await meter.flush_all()

        summary = await meter.get_usage_summary(org_id="org_1", period="month")

        assert "anthropic" in summary.tokens_by_provider
        assert "openai" in summary.tokens_by_provider

    @pytest.mark.asyncio
    async def test_summary_with_explicit_dates(self, meter):
        """Test summary with explicit start/end dates."""
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1000,
            output_tokens=500,
            model="gpt-4o",
            provider="openai",
        )
        await meter.flush_all()

        now = datetime.now(timezone.utc)
        summary = await meter.get_usage_summary(
            org_id="org_1",
            start_date=now - timedelta(days=1),
            end_date=now + timedelta(days=1),
        )

        assert summary.total_tokens == 1500


# =============================================================================
# Usage Breakdown Tests
# =============================================================================


class TestGetUsageBreakdown:
    """Tests for get_usage_breakdown method."""

    @pytest.mark.asyncio
    async def test_breakdown_with_recorded_data(self, meter):
        """Test breakdown includes recorded token, debate, and API data."""
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

    @pytest.mark.asyncio
    async def test_breakdown_by_user(self, meter):
        """Test breakdown includes by-user breakdown."""
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1000,
            output_tokens=500,
            model="gpt-4o",
            provider="openai",
            user_id="user_A",
        )
        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=2000,
            output_tokens=1000,
            model="gpt-4o",
            provider="openai",
            user_id="user_B",
        )
        await meter.flush_all()

        breakdown = await meter.get_usage_breakdown(org_id="org_1")
        assert len(breakdown.by_user) >= 2


# =============================================================================
# Usage Limits Tests
# =============================================================================


class TestGetUsageLimits:
    """Tests for get_usage_limits and quota enforcement."""

    @pytest.mark.asyncio
    async def test_limits_for_free_tier(self, meter):
        """Test limits reflect free tier caps."""
        limits = await meter.get_usage_limits(org_id="org_1", tier="free")

        assert limits.max_tokens == 100_000
        assert limits.max_debates == 10
        assert limits.max_api_calls == 100
        assert limits.tokens_exceeded is False

    @pytest.mark.asyncio
    async def test_limits_for_starter_tier(self, meter):
        """Test limits reflect starter tier caps."""
        limits = await meter.get_usage_limits(org_id="org_1", tier="starter")

        assert limits.max_tokens == 1_000_000
        assert limits.max_debates == 50
        assert limits.max_api_calls == 1_000

    @pytest.mark.asyncio
    async def test_limits_for_professional_tier(self, meter):
        """Test limits reflect professional tier caps."""
        limits = await meter.get_usage_limits(org_id="org_1", tier="professional")

        assert limits.max_tokens == 10_000_000
        assert limits.max_debates == 200
        assert limits.max_api_calls == 10_000

    @pytest.mark.asyncio
    async def test_limits_for_enterprise_tier(self, meter):
        """Test limits reflect enterprise tier caps."""
        limits = await meter.get_usage_limits(org_id="org_1", tier="enterprise")

        assert limits.max_tokens == 999_999_999
        assert limits.max_debates == 999_999
        assert limits.max_api_calls == 999_999

    @pytest.mark.asyncio
    async def test_limits_exceeded_flag(self, meter):
        """Test that exceeded flag is set when usage surpasses limits."""
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

    @pytest.mark.asyncio
    async def test_enterprise_effectively_unlimited(self, meter):
        """Test enterprise tier has very high caps."""
        limits = await meter.get_usage_limits(org_id="org_1", tier="enterprise")

        assert limits.max_tokens == 999_999_999
        assert limits.max_debates == 999_999
        assert limits.tokens_exceeded is False


# =============================================================================
# Multi-Org Isolation Tests
# =============================================================================


class TestMultiOrgIsolation:
    """Tests to ensure no billing cross-contamination between orgs."""

    @pytest.mark.asyncio
    async def test_token_usage_isolated_by_org(self, meter):
        """Test token usage is isolated by organization."""
        await meter.record_token_usage(
            org_id="org_A",
            input_tokens=1000,
            output_tokens=500,
            model="gpt-4o",
            provider="openai",
        )
        await meter.record_token_usage(
            org_id="org_B",
            input_tokens=5000,
            output_tokens=2500,
            model="gpt-4o",
            provider="openai",
        )

        summary_a = await meter.get_usage_summary(org_id="org_A", period="month")
        summary_b = await meter.get_usage_summary(org_id="org_B", period="month")

        assert summary_a.total_tokens == 1500
        assert summary_b.total_tokens == 7500

    @pytest.mark.asyncio
    async def test_debate_usage_isolated_by_org(self, meter):
        """Test debate usage is isolated by organization."""
        await meter.record_debate_usage(org_id="org_A", debate_id="d1", agent_count=3)
        await meter.record_debate_usage(org_id="org_B", debate_id="d2", agent_count=4)
        await meter.record_debate_usage(org_id="org_B", debate_id="d3", agent_count=5)

        summary_a = await meter.get_usage_summary(org_id="org_A", period="month")
        summary_b = await meter.get_usage_summary(org_id="org_B", period="month")

        assert summary_a.debate_count == 1
        assert summary_b.debate_count == 2

    @pytest.mark.asyncio
    async def test_api_call_usage_isolated_by_org(self, meter):
        """Test API call usage is isolated by organization."""
        await meter.record_api_call(org_id="org_A", endpoint="/a")
        await meter.record_api_call(org_id="org_B", endpoint="/b")
        await meter.record_api_call(org_id="org_B", endpoint="/c")
        await meter.record_api_call(org_id="org_B", endpoint="/d")

        summary_a = await meter.get_usage_summary(org_id="org_A", period="month")
        summary_b = await meter.get_usage_summary(org_id="org_B", period="month")

        assert summary_a.api_call_count == 1
        assert summary_b.api_call_count == 3

    @pytest.mark.asyncio
    async def test_cost_isolated_by_org(self, meter):
        """Test cost calculations are isolated by organization."""
        await meter.record_token_usage(
            org_id="org_A",
            input_tokens=1_000_000,
            output_tokens=500_000,
            model="claude-opus-4",
            provider="anthropic",
        )
        await meter.record_token_usage(
            org_id="org_B",
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o-mini",
            provider="openai",
        )

        summary_a = await meter.get_usage_summary(org_id="org_A", period="month")
        summary_b = await meter.get_usage_summary(org_id="org_B", period="month")

        # org_A: expensive usage, org_B: cheap usage
        assert summary_a.token_cost > summary_b.token_cost
        assert summary_a.token_cost == Decimal("17.50")
        assert summary_b.token_cost < Decimal("1")  # mini is cheap

    @pytest.mark.asyncio
    async def test_limits_isolated_by_org(self, meter):
        """Test limit tracking is isolated by organization."""
        for _ in range(5):
            await meter.record_token_usage(
                org_id="org_heavy",
                input_tokens=25_000,
                output_tokens=25_000,
                model="gpt-4o",
                provider="openai",
            )

        limits_heavy = await meter.get_usage_limits(org_id="org_heavy", tier="free")
        limits_empty = await meter.get_usage_limits(org_id="org_empty", tier="free")

        # org_heavy exceeded, org_empty has no usage
        assert limits_heavy.tokens_exceeded is True
        assert limits_heavy.tokens_used == 250_000
        assert limits_empty.tokens_exceeded is False
        assert limits_empty.tokens_used == 0


# =============================================================================
# Edge Cases Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_zero_tokens(self, meter):
        """Test recording with zero tokens."""
        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=0,
            output_tokens=0,
            model="gpt-4o",
            provider="openai",
        )

        assert record.total_tokens == 0
        assert record.total_cost == Decimal("0")

    @pytest.mark.asyncio
    async def test_very_large_token_counts(self, meter):
        """Test recording with very large token counts."""
        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1_000_000_000,  # 1 billion
            output_tokens=500_000_000,  # 500 million
            model="claude-sonnet-4",
            provider="anthropic",
        )

        # Should not overflow
        assert record.total_tokens == 1_500_000_000
        # claude-sonnet-4: $3/1M input, $15/1M output
        # 1B * 3 / 1M = 3000, 500M * 15 / 1M = 7500
        assert record.input_cost == Decimal("3000")
        assert record.output_cost == Decimal("7500")
        assert record.total_cost == Decimal("10500")

    @pytest.mark.asyncio
    async def test_single_token(self, meter):
        """Test recording with single token."""
        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=1,
            output_tokens=1,
            model="claude-sonnet-4",
            provider="anthropic",
        )

        # Verify precision is maintained
        assert record.total_tokens == 2
        assert record.input_cost == Decimal("0.000003")
        assert record.output_cost == Decimal("0.000015")

    @pytest.mark.asyncio
    async def test_empty_metadata(self, meter):
        """Test recording with None metadata."""
        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o",
            provider="openai",
            metadata=None,
        )

        assert record.metadata == {}

    @pytest.mark.asyncio
    async def test_special_characters_in_org_id(self, meter):
        """Test org_id with special characters."""
        record = await meter.record_token_usage(
            org_id="org/with-special_chars.123",
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o",
            provider="openai",
        )
        await meter.flush_all()

        # Should handle special characters
        cursor = meter._conn.cursor()
        cursor.execute(
            "SELECT org_id FROM token_usage WHERE org_id = ?", ("org/with-special_chars.123",)
        )
        row = cursor.fetchone()
        assert row is not None

    @pytest.mark.asyncio
    async def test_unicode_in_metadata(self, meter):
        """Test unicode characters in metadata."""
        record = await meter.record_token_usage(
            org_id="org_1",
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o",
            provider="openai",
            metadata={"topic": "Artificial Intelligence in Healthcare"},
        )
        await meter.flush_all()

        cursor = meter._conn.cursor()
        cursor.execute("SELECT metadata FROM token_usage WHERE id = ?", (record.id,))
        row = cursor.fetchone()
        parsed = json.loads(row["metadata"])
        assert parsed["topic"] == "Artificial Intelligence in Healthcare"

    @pytest.mark.asyncio
    async def test_concurrent_recording(self, temp_db_path):
        """Test concurrent writes to the database."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=temp_db_path)
        await meter.initialize()

        errors = []

        async def write_events(org_id: str, count: int):
            try:
                for i in range(count):
                    await meter.record_token_usage(
                        org_id=org_id,
                        input_tokens=100,
                        output_tokens=50,
                        model="gpt-4o",
                        provider="openai",
                    )
            except Exception as e:
                errors.append(e)

        # Run multiple coroutines concurrently
        await asyncio.gather(
            write_events("org_1", 10),
            write_events("org_2", 10),
            write_events("org_3", 10),
        )

        assert len(errors) == 0

        await meter.flush_all()

        # Verify all events were recorded
        cursor = meter._conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM hourly_aggregates")
        row = cursor.fetchone()
        # Should have 3 orgs in aggregates
        assert row["c"] == 3

        await meter.close()


# =============================================================================
# Module-Level Singleton Tests
# =============================================================================


class TestGetUsageMeter:
    """Tests for get_usage_meter module-level function."""

    def test_returns_usage_meter_instance(self):
        """Test that get_usage_meter returns a UsageMeter."""
        from aragora.services import usage_metering
        from aragora.services.usage_metering import UsageMeter

        original = usage_metering._usage_meter
        usage_metering._usage_meter = None
        try:
            meter = usage_metering.get_usage_meter()
            assert isinstance(meter, UsageMeter)
        finally:
            usage_metering._usage_meter = original

    def test_returns_same_instance(self):
        """Test singleton behavior returns the same instance."""
        from aragora.services import usage_metering

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

    def test_each_tier_has_required_keys(self):
        """Test each tier has max_tokens, max_debates, max_api_calls."""
        from aragora.services.usage_metering import TIER_USAGE_CAPS

        for tier_name, caps in TIER_USAGE_CAPS.items():
            assert "max_tokens" in caps, f"{tier_name} missing max_tokens"
            assert "max_debates" in caps, f"{tier_name} missing max_debates"
            assert "max_api_calls" in caps, f"{tier_name} missing max_api_calls"


# =============================================================================
# Model Pricing Configuration Tests
# =============================================================================


class TestModelPricing:
    """Tests for MODEL_PRICING configuration."""

    def test_all_providers_have_default(self):
        """Test all providers have default pricing."""
        from aragora.services.usage_metering import MODEL_PRICING

        for provider, models in MODEL_PRICING.items():
            assert "default" in models, f"{provider} missing default pricing"
            assert "default-output" in models, f"{provider} missing default-output pricing"

    def test_pricing_values_are_decimal(self):
        """Test all pricing values are Decimal."""
        from aragora.services.usage_metering import MODEL_PRICING

        for provider, models in MODEL_PRICING.items():
            for model, price in models.items():
                assert isinstance(price, Decimal), f"{provider}/{model} price is not Decimal"

    def test_pricing_values_positive(self):
        """Test all pricing values are positive."""
        from aragora.services.usage_metering import MODEL_PRICING

        for provider, models in MODEL_PRICING.items():
            for model, price in models.items():
                assert price > 0, f"{provider}/{model} price is not positive"

    def test_output_pricing_typically_higher(self):
        """Test output pricing is typically higher than input for same model."""
        from aragora.services.usage_metering import MODEL_PRICING

        for provider, models in MODEL_PRICING.items():
            for model_name, input_price in models.items():
                if "-output" in model_name:
                    continue
                output_key = f"{model_name}-output"
                if output_key in models:
                    output_price = models[output_key]
                    assert output_price >= input_price, (
                        f"{provider}/{model_name}: output ${output_price} < input ${input_price}"
                    )

    @pytest.mark.parametrize(
        ("provider", "model"),
        [
            ("anthropic", "claude-opus-4-8"),
            ("anthropic", "claude-opus-4-7"),
            ("anthropic", "claude-opus-4.8"),
            ("anthropic", "claude-opus-4.7"),
            ("anthropic", "claude-opus-4"),
            ("anthropic", "claude-haiku-4-5"),
            ("anthropic", "claude-haiku-4-5-20251001"),
            ("anthropic", "claude-haiku-4.5"),
            ("openai", "gpt-5.5"),
            ("google", "gemini-3.5-flash"),
            ("google", "gemini-3.1-pro"),
            ("google", "gemini-3.1-pro-preview"),
            ("openrouter", "openai/gpt-5.5"),
            ("openrouter", "google/gemini-3.5-flash"),
            ("openrouter", "anthropic/claude-opus-4-8"),
            ("openrouter", "anthropic/claude-opus-4.8"),
            ("openrouter", "anthropic/claude-opus-4-7"),
            ("openrouter", "anthropic/claude-opus-4.7"),
            ("openrouter", "anthropic/claude-haiku-4-5"),
            ("openrouter", "anthropic/claude-haiku-4.5"),
            ("openrouter", "anthropic/claude-haiku-4-5-20251001"),
        ],
    )
    def test_calibrated_billing_models_have_usage_meter_prices(self, provider, model):
        """Calibrated billing models must stay mirrored in service metering."""
        from aragora.billing.usage import PROVIDER_PRICING
        from aragora.services.usage_metering import MODEL_PRICING

        provider_prices = PROVIDER_PRICING[provider]
        metering_prices = MODEL_PRICING[provider]

        assert metering_prices[model] == provider_prices[model]
        assert metering_prices[f"{model}-output"] == provider_prices[f"{model}-output"]


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    @pytest.mark.asyncio
    async def test_close_without_initialize(self, temp_db_path):
        """Test that close works even if never initialized."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=temp_db_path)
        # Should not raise
        await meter.close()

    @pytest.mark.asyncio
    async def test_double_initialize_is_idempotent(self, temp_db_path):
        """Test that calling initialize twice does not error."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=temp_db_path)
        await meter.initialize()
        await meter.initialize()  # Should be a no-op
        assert meter._initialized is True
        await meter.close()

    @pytest.mark.asyncio
    async def test_close_flushes_buffers(self, temp_db_path):
        """Test that close flushes all buffers."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=temp_db_path)
        await meter.initialize()

        await meter.record_token_usage(
            org_id="org_1",
            input_tokens=100,
            output_tokens=50,
            model="gpt-4o",
            provider="openai",
        )

        # Buffer has data
        assert len(meter._token_buffer) == 1

        await meter.close()

        # Reconnect and verify data is persisted
        conn = sqlite3.connect(str(temp_db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as c FROM token_usage WHERE org_id = 'org_1'")
        assert cursor.fetchone()["c"] == 1
        conn.close()


# =============================================================================
# Database Schema Tests
# =============================================================================


class TestDatabaseSchema:
    """Tests for database schema creation."""

    @pytest.mark.asyncio
    async def test_tables_created(self, temp_db_path):
        """Test all required tables are created."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=temp_db_path)
        await meter.initialize()

        cursor = meter._conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in cursor.fetchall()}

        assert "token_usage" in tables
        assert "debate_usage" in tables
        assert "api_usage" in tables
        assert "hourly_aggregates" in tables

        await meter.close()

    @pytest.mark.asyncio
    async def test_indexes_created(self, temp_db_path):
        """Test database indexes are created."""
        from aragora.services.usage_metering import UsageMeter

        meter = UsageMeter(db_path=temp_db_path)
        await meter.initialize()

        cursor = meter._conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indexes = {row["name"] for row in cursor.fetchall()}

        assert "idx_token_usage_org_time" in indexes
        assert "idx_token_usage_model" in indexes
        assert "idx_debate_usage_org_time" in indexes
        assert "idx_api_usage_org_time" in indexes
        assert "idx_hourly_agg_org_hour" in indexes

        await meter.close()


# =============================================================================
# Module Exports Tests
# =============================================================================


class TestModuleExports:
    """Tests for module __all__ exports."""

    def test_all_exports_importable(self):
        """Test all __all__ exports are importable."""
        from aragora.services.usage_metering import __all__

        expected = [
            "UsageMeter",
            "UsageSummary",
            "UsageBreakdown",
            "UsageLimits",
            "TokenUsageRecord",
            "DebateUsageRecord",
            "ApiCallRecord",
            "HourlyAggregate",
            "MeteringPeriod",
            "UsageType",
            "MODEL_PRICING",
            "TIER_USAGE_CAPS",
            "get_usage_meter",
        ]

        for name in expected:
            assert name in __all__, f"{name} not in __all__"

    def test_all_imports_work(self):
        """Test all exports can be imported."""
        from aragora.services.usage_metering import (
            UsageMeter,
            UsageSummary,
            UsageBreakdown,
            UsageLimits,
            TokenUsageRecord,
            DebateUsageRecord,
            ApiCallRecord,
            HourlyAggregate,
            MeteringPeriod,
            UsageType,
            MODEL_PRICING,
            TIER_USAGE_CAPS,
            get_usage_meter,
        )

        assert UsageMeter is not None
        assert UsageSummary is not None
        assert UsageBreakdown is not None
        assert UsageLimits is not None
        assert TokenUsageRecord is not None
        assert DebateUsageRecord is not None
        assert ApiCallRecord is not None
        assert HourlyAggregate is not None
        assert MeteringPeriod is not None
        assert UsageType is not None
        assert MODEL_PRICING is not None
        assert TIER_USAGE_CAPS is not None
        assert get_usage_meter is not None
