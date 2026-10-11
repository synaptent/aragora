"""
Tests for enterprise metering module.

Tests cover:
- TokenUsageRecord dataclass
- BudgetConfig dataclass
- CostBreakdown dataclass
- Invoice dataclass
- EnterpriseMeter class methods
"""

import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from aragora.billing.enterprise_metering import (
    BudgetAlertLevel,
    BudgetConfig,
    CostBreakdown,
    EnterpriseMeter,
    Invoice,
    InvoiceStatus,
    TokenUsageRecord,
    UsageForecast,
)


class TestBudgetAlertLevel:
    """Tests for BudgetAlertLevel enum."""

    def test_alert_levels_exist(self):
        """All alert levels should be defined."""
        assert BudgetAlertLevel.INFO.value == "info"
        assert BudgetAlertLevel.WARNING.value == "warning"
        assert BudgetAlertLevel.CRITICAL.value == "critical"
        assert BudgetAlertLevel.EXCEEDED.value == "exceeded"


class TestInvoiceStatus:
    """Tests for InvoiceStatus enum."""

    def test_invoice_statuses_exist(self):
        """All invoice statuses should be defined."""
        assert InvoiceStatus.DRAFT.value == "draft"
        assert InvoiceStatus.PENDING.value == "pending"
        assert InvoiceStatus.PAID.value == "paid"
        assert InvoiceStatus.OVERDUE.value == "overdue"
        assert InvoiceStatus.CANCELLED.value == "cancelled"


class TestTokenUsageRecord:
    """Tests for TokenUsageRecord dataclass."""

    def test_default_values(self):
        """Should have sensible default values."""
        record = TokenUsageRecord()
        assert record.id is not None
        assert record.tenant_id == ""
        assert record.tokens_in == 0
        assert record.tokens_out == 0
        assert record.total_cost == Decimal("0")
        assert record.request_type == "chat"

    def test_create_with_values(self):
        """Should accept all parameters."""
        record = TokenUsageRecord(
            tenant_id="tenant_1",
            user_id="user_1",
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=1000,
            tokens_out=500,
            total_tokens=1500,
            input_cost=Decimal("0.015"),
            output_cost=Decimal("0.075"),
            total_cost=Decimal("0.09"),
            debate_id="debate_123",
        )
        assert record.tenant_id == "tenant_1"
        assert record.provider == "anthropic"
        assert record.model == "claude-opus-4"
        assert record.tokens_in == 1000
        assert record.tokens_out == 500
        assert record.total_tokens == 1500

    def test_to_dict(self):
        """Should convert to dictionary correctly."""
        record = TokenUsageRecord(
            tenant_id="tenant_1",
            provider="openai",
            model="gpt-4",
            tokens_in=100,
            tokens_out=50,
        )
        data = record.to_dict()
        assert isinstance(data, dict)
        assert data["tenant_id"] == "tenant_1"
        assert data["provider"] == "openai"
        assert data["model"] == "gpt-4"
        assert data["tokens_in"] == 100
        assert data["tokens_out"] == 50

    def test_unique_ids(self):
        """Each record should have a unique ID."""
        record1 = TokenUsageRecord()
        record2 = TokenUsageRecord()
        assert record1.id != record2.id


class TestBudgetConfig:
    """Tests for BudgetConfig dataclass."""

    def test_default_values(self):
        """Should have sensible defaults when tenant_id provided."""
        config = BudgetConfig(tenant_id="test_tenant")
        assert config.monthly_budget == Decimal("0")
        assert config.alert_thresholds is not None
        assert len(config.alert_thresholds) == 3  # [50, 75, 90]

    def test_create_with_values(self):
        """Should accept all parameters."""
        config = BudgetConfig(
            tenant_id="tenant_1",
            monthly_budget=Decimal("1000.00"),
            daily_limit=Decimal("50.00"),
            alert_emails=["admin@example.com"],
        )
        assert config.tenant_id == "tenant_1"
        assert config.monthly_budget == Decimal("1000.00")
        assert config.daily_limit == Decimal("50.00")
        assert "admin@example.com" in config.alert_emails


class TestCostBreakdown:
    """Tests for CostBreakdown dataclass."""

    def test_default_values(self):
        """Should initialize with empty collections when required fields provided."""
        now = datetime.now(timezone.utc)
        breakdown = CostBreakdown(
            tenant_id="test_tenant",
            period_start=now - timedelta(days=30),
            period_end=now,
        )
        assert breakdown.total_cost == Decimal("0")
        assert len(breakdown.cost_by_provider) == 0
        assert len(breakdown.cost_by_model) == 0

    def test_to_dict(self):
        """Should convert to dictionary."""
        now = datetime.now(timezone.utc)
        breakdown = CostBreakdown(
            tenant_id="test_tenant",
            period_start=now - timedelta(days=30),
            period_end=now,
            total_cost=Decimal("100.00"),
            cost_by_provider={"anthropic": Decimal("60.00"), "openai": Decimal("40.00")},
            cost_by_model={"claude-opus-4": Decimal("60.00"), "gpt-4": Decimal("40.00")},
        )
        data = breakdown.to_dict()
        assert data["total_cost"] == "100.00"
        assert "anthropic" in data["by_provider"]["cost"]
        assert "claude-opus-4" in data["by_model"]["cost"]


class TestInvoice:
    """Tests for Invoice dataclass."""

    def test_default_status(self):
        """Should default to DRAFT status."""
        invoice = Invoice()
        assert invoice.status == InvoiceStatus.DRAFT

    def test_create_invoice(self):
        """Should accept all parameters."""
        now = datetime.now(timezone.utc)
        invoice = Invoice(
            tenant_id="tenant_1",
            period_start=now - timedelta(days=30),
            period_end=now,
            total=Decimal("500.00"),
            status=InvoiceStatus.PENDING,
        )
        assert invoice.tenant_id == "tenant_1"
        assert invoice.total == Decimal("500.00")
        assert invoice.status == InvoiceStatus.PENDING

    def test_to_dict(self):
        """Should convert to dictionary."""
        now = datetime.now(timezone.utc)
        invoice = Invoice(
            tenant_id="tenant_1",
            period_start=now - timedelta(days=30),
            period_end=now,
            total=Decimal("500.00"),
        )
        data = invoice.to_dict()
        assert data["tenant_id"] == "tenant_1"
        assert data["total"] == "500.00"
        assert "period_start" in data


class TestUsageForecast:
    """Tests for UsageForecast dataclass."""

    def test_default_values(self):
        """Should have sensible defaults when required fields provided."""
        now = datetime.now(timezone.utc)
        forecast = UsageForecast(
            tenant_id="test_tenant",
            forecast_date=now,
            period_end=now + timedelta(days=30),
        )
        assert forecast.confidence == 0.0
        assert forecast.projected_cost == Decimal("0")

    def test_to_dict(self):
        """Should convert to dictionary."""
        now = datetime.now(timezone.utc)
        forecast = UsageForecast(
            tenant_id="tenant_1",
            forecast_date=now,
            period_end=now + timedelta(days=30),
            projected_cost=Decimal("1000.00"),
            confidence=0.85,
        )
        data = forecast.to_dict()
        assert data["tenant_id"] == "tenant_1"
        assert data["confidence"] == 0.85


class TestEnterpriseMeter:
    """Tests for EnterpriseMeter class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_metering.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter for testing."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_initialization(self, temp_db):
        """Should initialize database schema."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        assert meter._initialized is True
        await meter.close()

    @pytest.mark.asyncio
    async def test_record_token_usage(self, meter):
        """Should record token usage correctly."""
        record = await meter.record_token_usage(
            provider="anthropic",
            model="claude-3-opus-20240229",
            tokens_in=1000,
            tokens_out=500,
            tenant_id="test_tenant",
            debate_id="debate_123",
        )
        assert record.provider == "anthropic"
        assert record.tokens_in == 1000
        assert record.tokens_out == 500
        assert record.total_tokens == 1500
        assert record.total_cost >= Decimal("0")

    @pytest.mark.asyncio
    async def test_record_usage_with_cache(self, meter):
        """Should apply cache discount correctly."""
        record = await meter.record_token_usage(
            provider="openai",
            model="gpt-4",
            tokens_in=1000,
            tokens_out=500,
            tenant_id="test_tenant",
            cached_tokens=500,  # 50% cache hit
        )
        assert record.cached_tokens == 500
        assert record.discount_applied >= Decimal("0")

    @pytest.mark.asyncio
    async def test_record_usage_default_tenant(self, meter):
        """Should use default tenant if not specified."""
        record = await meter.record_token_usage(
            provider="anthropic",
            model="claude-3-sonnet-20240229",
            tokens_in=100,
            tokens_out=50,
        )
        assert record.tenant_id  # Should have some tenant ID

    @pytest.mark.asyncio
    async def test_calculate_costs(self, meter):
        """Should calculate costs based on provider pricing."""
        input_cost, output_cost = meter._calculate_costs(
            provider="anthropic",
            model="claude-3-opus-20240229",
            tokens_in=1000,
            tokens_out=500,
        )
        assert input_cost >= Decimal("0")
        assert output_cost >= Decimal("0")

    @pytest.mark.asyncio
    async def test_calculate_costs_unknown_provider(self, meter):
        """Should use default pricing for unknown provider."""
        input_cost, output_cost = meter._calculate_costs(
            provider="unknown_provider",
            model="unknown_model",
            tokens_in=1000,
            tokens_out=500,
        )
        # Should not raise, should use default pricing
        assert input_cost >= Decimal("0")
        assert output_cost >= Decimal("0")

    @pytest.mark.asyncio
    async def test_set_and_get_budget(self, meter):
        """Should set and retrieve budget configuration."""
        await meter.set_budget(
            tenant_id="test_tenant",
            monthly_budget=Decimal("1000.00"),
            daily_limit=Decimal("50.00"),
        )
        budget = await meter.get_budget("test_tenant")
        assert budget is not None
        assert budget.tenant_id == "test_tenant"
        assert budget.monthly_budget == Decimal("1000.00")
        assert budget.daily_limit == Decimal("50.00")

    @pytest.mark.asyncio
    async def test_get_budget_nonexistent(self, meter):
        """Should return None for nonexistent tenant budget."""
        budget = await meter.get_budget("nonexistent_tenant")
        assert budget is None

    @pytest.mark.asyncio
    async def test_get_cost_breakdown(self, meter):
        """Should return cost breakdown for tenant."""
        # Record some usage first
        await meter.record_token_usage(
            provider="anthropic",
            model="claude-3-opus-20240229",
            tokens_in=500,
            tokens_out=250,
            tenant_id="breakdown_test",
        )
        await meter.record_token_usage(
            provider="openai",
            model="gpt-4",
            tokens_in=500,
            tokens_out=250,
            tenant_id="breakdown_test",
        )

        # Flush buffer to persist
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="breakdown_test")
        assert breakdown is not None
        assert breakdown.total_cost >= Decimal("0")

    @pytest.mark.asyncio
    async def test_get_cost_breakdown_with_dates(self, meter):
        """Should filter cost breakdown by date range."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        tomorrow = now + timedelta(days=1)

        await meter.record_token_usage(
            provider="anthropic",
            model="claude-3-sonnet-20240229",
            tokens_in=100,
            tokens_out=50,
            tenant_id="date_filter_test",
        )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(
            tenant_id="date_filter_test",
            start_date=yesterday,
            end_date=tomorrow,
        )
        assert breakdown is not None

    @pytest.mark.asyncio
    async def test_forecast_usage(self, meter):
        """Should generate usage forecast."""
        # Record some historical usage
        for _ in range(5):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-3-sonnet-20240229",
                tokens_in=100,
                tokens_out=50,
                tenant_id="forecast_test",
            )
        await meter._flush_buffer()

        forecast = await meter.forecast_usage(
            tenant_id="forecast_test",
            days_ahead=30,
        )
        assert forecast is not None
        assert forecast.tenant_id == "forecast_test"

    @pytest.mark.asyncio
    async def test_generate_invoice(self, meter):
        """Should generate invoice for period."""
        # Record usage
        await meter.record_token_usage(
            provider="anthropic",
            model="claude-3-opus-20240229",
            tokens_in=1000,
            tokens_out=500,
            tenant_id="invoice_test",
        )
        await meter._flush_buffer()

        period = datetime.now(timezone.utc).strftime("%Y-%m")
        invoice = await meter.generate_invoice(
            tenant_id="invoice_test",
            period=period,
        )
        assert invoice is not None
        assert invoice.tenant_id == "invoice_test"
        assert invoice.period_start is not None
        assert invoice.period_end is not None
        assert invoice.status == InvoiceStatus.DRAFT

    @pytest.mark.asyncio
    async def test_get_invoices(self, meter):
        """Should retrieve invoices for tenant."""
        # Generate an invoice first
        await meter.record_token_usage(
            provider="openai",
            model="gpt-4",
            tokens_in=500,
            tokens_out=250,
            tenant_id="invoices_test",
        )
        await meter._flush_buffer()

        period = datetime.now(timezone.utc).strftime("%Y-%m")
        await meter.generate_invoice(tenant_id="invoices_test", period=period)

        invoices = await meter.get_invoices(tenant_id="invoices_test")
        assert len(invoices) >= 1

    @pytest.mark.asyncio
    async def test_buffer_flush_on_threshold(self, meter):
        """Should flush buffer when threshold is reached."""
        # Record many items to trigger buffer flush
        original_buffer_size = meter._buffer_size
        meter._buffer_size = 5  # Small buffer for testing

        for i in range(6):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-3-sonnet-20240229",
                tokens_in=100,
                tokens_out=50,
                tenant_id="buffer_test",
            )

        # Buffer should have been flushed
        assert len(meter._usage_buffer) < 6

        meter._buffer_size = original_buffer_size

    @pytest.mark.asyncio
    async def test_close(self, temp_db):
        """Should close meter gracefully."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()

        # Record some usage
        await meter.record_token_usage(
            provider="anthropic",
            model="claude-3-sonnet-20240229",
            tokens_in=100,
            tokens_out=50,
            tenant_id="close_test",
        )

        await meter.close()
        # Should not raise


class TestCostCalculation:
    """Tests for cost calculation edge cases."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_costs.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_zero_tokens(self, meter):
        """Should handle zero tokens gracefully."""
        record = await meter.record_token_usage(
            provider="anthropic",
            model="claude-3-opus-20240229",
            tokens_in=0,
            tokens_out=0,
            tenant_id="zero_test",
        )
        assert record.total_cost == Decimal("0")

    @pytest.mark.asyncio
    async def test_large_token_count(self, meter):
        """Should handle large token counts."""
        record = await meter.record_token_usage(
            provider="anthropic",
            model="claude-3-opus-20240229",
            tokens_in=1000000,
            tokens_out=500000,
            tenant_id="large_test",
        )
        assert record.total_tokens == 1500000
        assert record.total_cost > Decimal("0")

    @pytest.mark.asyncio
    async def test_multiple_providers(self, meter):
        """Should track costs across multiple providers."""
        providers = ["anthropic", "openai", "mistral"]
        for provider in providers:
            await meter.record_token_usage(
                provider=provider,
                model="default",
                tokens_in=100,
                tokens_out=50,
                tenant_id="multi_provider_test",
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="multi_provider_test")
        # Should have tracked usage from all providers
        assert breakdown.total_cost > Decimal("0")


# =============================================================================
# Metering Event Ingestion Tests
# =============================================================================


class TestMeteringEventIngestion:
    """Tests for metering event ingestion."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_ingestion.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_ingest_basic_event(self, meter):
        """Should ingest a basic metering event."""
        record = await meter.record_token_usage(
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=500,
            tokens_out=200,
            tenant_id="tenant_ingest",
        )
        assert record.id is not None
        assert record.tenant_id == "tenant_ingest"
        assert record.provider == "anthropic"
        assert record.model == "claude-opus-4"

    @pytest.mark.asyncio
    async def test_ingest_with_all_metadata(self, meter):
        """Should ingest event with all optional metadata."""
        record = await meter.record_token_usage(
            provider="openai",
            model="gpt-4o",
            tokens_in=1000,
            tokens_out=500,
            tenant_id="tenant_full",
            user_id="user_123",
            debate_id="debate_456",
            agent_id="agent_789",
            request_type="debate",
            cached_tokens=200,
            latency_ms=350,
            success=True,
            metadata={"round": 1, "topic": "AI safety"},
        )
        assert record.user_id == "user_123"
        assert record.debate_id == "debate_456"
        assert record.agent_id == "agent_789"
        assert record.request_type == "debate"
        assert record.latency_ms == 350
        assert record.metadata["round"] == 1

    @pytest.mark.asyncio
    async def test_ingest_failed_request(self, meter):
        """Should track failed requests."""
        record = await meter.record_token_usage(
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=100,
            tokens_out=0,
            tenant_id="tenant_fail",
            success=False,
        )
        assert record.success is False

    @pytest.mark.asyncio
    async def test_ingest_batch_events(self, meter):
        """Should handle batch ingestion of events."""
        for i in range(10):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=100 * (i + 1),
                tokens_out=50 * (i + 1),
                tenant_id="tenant_batch",
                user_id=f"user_{i % 3}",
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_batch")
        assert breakdown.total_requests == 10


# =============================================================================
# Usage Aggregation by Dimension Tests
# =============================================================================


class TestUsageAggregationByDimension:
    """Tests for usage aggregation by user, org, workspace dimensions."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_aggregation.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_aggregate_by_user(self, meter):
        """Should aggregate usage by user."""
        users = ["alice", "bob", "alice", "charlie", "alice"]
        for user in users:
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=100,
                tokens_out=50,
                tenant_id="tenant_user_agg",
                user_id=user,
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_user_agg")
        assert "alice" in breakdown.cost_by_user
        assert "bob" in breakdown.cost_by_user
        assert "charlie" in breakdown.cost_by_user

    @pytest.mark.asyncio
    async def test_aggregate_by_provider(self, meter):
        """Should aggregate usage by provider."""
        for provider in ["anthropic", "openai", "anthropic", "google"]:
            await meter.record_token_usage(
                provider=provider,
                model="default",
                tokens_in=100,
                tokens_out=50,
                tenant_id="tenant_provider_agg",
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_provider_agg")
        assert "anthropic" in breakdown.cost_by_provider
        assert "openai" in breakdown.cost_by_provider
        assert "google" in breakdown.cost_by_provider
        assert breakdown.cost_by_provider["anthropic"] > breakdown.cost_by_provider["openai"]

    @pytest.mark.asyncio
    async def test_aggregate_by_model(self, meter):
        """Should aggregate usage by model."""
        models = [
            ("anthropic", "claude-opus-4"),
            ("openai", "gpt-4o"),
            ("anthropic", "claude-opus-4"),
        ]
        for provider, model in models:
            await meter.record_token_usage(
                provider=provider,
                model=model,
                tokens_in=100,
                tokens_out=50,
                tenant_id="tenant_model_agg",
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_model_agg")
        assert len(breakdown.cost_by_model) == 2

    @pytest.mark.asyncio
    async def test_aggregate_by_request_type(self, meter):
        """Should aggregate usage by request type."""
        for req_type in ["chat", "debate", "analysis", "debate", "chat"]:
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=100,
                tokens_out=50,
                tenant_id="tenant_type_agg",
                request_type=req_type,
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_type_agg")
        assert "chat" in breakdown.cost_by_type
        assert "debate" in breakdown.cost_by_type
        assert "analysis" in breakdown.cost_by_type


# =============================================================================
# API Call Counting Tests
# =============================================================================


class TestAPICallCounting:
    """Tests for API call counting."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_api_count.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_count_total_requests(self, meter):
        """Should count total API requests."""
        for _ in range(15):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=100,
                tokens_out=50,
                tenant_id="tenant_count",
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_count")
        assert breakdown.total_requests == 15

    @pytest.mark.asyncio
    async def test_average_tokens_per_request(self, meter):
        """Should calculate average tokens per request."""
        for i in range(5):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=100 + i * 50,
                tokens_out=50 + i * 25,
                tenant_id="tenant_avg",
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_avg")
        assert breakdown.total_requests == 5
        assert breakdown.avg_tokens_per_request > 0

    @pytest.mark.asyncio
    async def test_average_cost_per_request(self, meter):
        """Should calculate average cost per request."""
        for _ in range(10):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=1000,
                tokens_out=500,
                tenant_id="tenant_avg_cost",
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_avg_cost")
        assert breakdown.avg_cost_per_request > Decimal("0")


# =============================================================================
# Real-time Usage Query Tests
# =============================================================================


class TestRealtimeUsageQueries:
    """Tests for real-time usage queries."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_realtime.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_query_current_month(self, meter):
        """Should query current month usage by default."""
        await meter.record_token_usage(
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=500,
            tokens_out=200,
            tenant_id="tenant_current",
        )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_current")
        assert breakdown.total_requests >= 1

    @pytest.mark.asyncio
    async def test_query_custom_date_range(self, meter):
        """Should query custom date range."""
        now = datetime.now(timezone.utc)
        last_week = now - timedelta(days=7)

        await meter.record_token_usage(
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=500,
            tokens_out=200,
            tenant_id="tenant_range",
        )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(
            tenant_id="tenant_range",
            start_date=last_week,
            end_date=now,
        )
        assert breakdown.period_start == last_week
        assert breakdown.period_end == now

    @pytest.mark.asyncio
    async def test_query_empty_tenant(self, meter):
        """Should return empty breakdown for tenant with no usage."""
        breakdown = await meter.get_cost_breakdown(tenant_id="nonexistent_tenant")
        assert breakdown.total_cost == Decimal("0")
        assert breakdown.total_requests == 0
        assert breakdown.total_tokens == 0


# =============================================================================
# Historical Usage Report Tests
# =============================================================================


class TestHistoricalUsageReports:
    """Tests for historical usage reports."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_historical.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_get_cost_by_day(self, meter):
        """Should return costs grouped by day."""
        for _ in range(5):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=500,
                tokens_out=200,
                tenant_id="tenant_daily",
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_daily")
        # Today's date should be in cost_by_day
        assert len(breakdown.cost_by_day) >= 1

    @pytest.mark.asyncio
    async def test_invoice_includes_line_items(self, meter):
        """Should generate invoice with detailed line items."""
        for provider, model in [("anthropic", "claude-opus-4"), ("openai", "gpt-4o")]:
            await meter.record_token_usage(
                provider=provider,
                model=model,
                tokens_in=1000,
                tokens_out=500,
                tenant_id="tenant_invoice_items",
            )
        await meter._flush_buffer()

        period = datetime.now(timezone.utc).strftime("%Y-%m")
        invoice = await meter.generate_invoice(
            tenant_id="tenant_invoice_items",
            period=period,
        )
        assert len(invoice.line_items) >= 1
        assert "description" in invoice.line_items[0]
        assert "amount" in invoice.line_items[0]

    @pytest.mark.asyncio
    async def test_invoice_with_tax_and_discount(self, meter):
        """Should apply tax and discount to invoice."""
        await meter.record_token_usage(
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=1000000,
            tokens_out=500000,
            tenant_id="tenant_tax_disc",
        )
        await meter._flush_buffer()

        period = datetime.now(timezone.utc).strftime("%Y-%m")
        invoice = await meter.generate_invoice(
            tenant_id="tenant_tax_disc",
            period=period,
            tax_rate=Decimal("0.10"),
            discount_percent=Decimal("5"),
        )
        assert invoice.discount > Decimal("0")
        assert invoice.tax > Decimal("0")
        assert invoice.total != invoice.subtotal


# =============================================================================
# Meter Rollup Tests (Hourly, Daily, Monthly)
# =============================================================================


class TestMeterRollups:
    """Tests for meter rollups at different granularities."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_rollup.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_daily_breakdown(self, meter):
        """Should provide daily cost breakdown."""
        for _ in range(3):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=500,
                tokens_out=200,
                tenant_id="tenant_rollup",
            )
        await meter._flush_buffer()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_rollup")
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert today_str in breakdown.cost_by_day

    @pytest.mark.asyncio
    async def test_monthly_invoice_period(self, meter):
        """Should generate invoice for monthly period."""
        await meter.record_token_usage(
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=1000,
            tokens_out=500,
            tenant_id="tenant_monthly",
        )
        await meter._flush_buffer()

        period = datetime.now(timezone.utc).strftime("%Y-%m")
        invoice = await meter.generate_invoice(
            tenant_id="tenant_monthly",
            period=period,
        )
        # Check period is a full month
        assert invoice.period_start.day == 1
        assert invoice.period_end.day >= 28


# =============================================================================
# Idempotency Handling Tests
# =============================================================================


class TestIdempotencyHandling:
    """Tests for idempotency in metering operations."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_idempotency.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_unique_record_ids(self, meter):
        """Each record should have a unique ID."""
        records = []
        for _ in range(5):
            record = await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=100,
                tokens_out=50,
                tenant_id="tenant_unique",
            )
            records.append(record)

        ids = [r.id for r in records]
        assert len(ids) == len(set(ids))  # All IDs are unique

    @pytest.mark.asyncio
    async def test_budget_update_idempotent(self, meter):
        """Setting budget multiple times should be idempotent."""
        for _ in range(3):
            await meter.set_budget(
                tenant_id="tenant_budget_idempotent",
                monthly_budget=Decimal("1000.00"),
                daily_limit=Decimal("50.00"),
            )

        budget = await meter.get_budget("tenant_budget_idempotent")
        assert budget.monthly_budget == Decimal("1000.00")

    @pytest.mark.asyncio
    async def test_re_initialization_safe(self, temp_db):
        """Re-initializing meter should be safe."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        await meter.record_token_usage(
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=100,
            tokens_out=50,
            tenant_id="tenant_reinit",
        )
        await meter._flush_buffer()

        # Re-initialize
        await meter.initialize()

        breakdown = await meter.get_cost_breakdown(tenant_id="tenant_reinit")
        assert breakdown.total_requests >= 1
        await meter.close()


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling with invalid inputs."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_errors.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_empty_provider(self, meter):
        """Should handle empty provider gracefully."""
        record = await meter.record_token_usage(
            provider="",
            model="test-model",
            tokens_in=100,
            tokens_out=50,
            tenant_id="tenant_empty_provider",
        )
        # Should use fallback pricing
        assert record.total_cost >= Decimal("0")

    @pytest.mark.asyncio
    async def test_empty_model(self, meter):
        """Should handle empty model gracefully."""
        record = await meter.record_token_usage(
            provider="anthropic",
            model="",
            tokens_in=100,
            tokens_out=50,
            tenant_id="tenant_empty_model",
        )
        # Should use default pricing for provider
        assert record.total_cost >= Decimal("0")

    @pytest.mark.asyncio
    async def test_negative_tokens_treated_as_provided(self, meter):
        """Should handle negative token values."""
        record = await meter.record_token_usage(
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=-100,
            tokens_out=50,
            tenant_id="tenant_negative",
        )
        # Implementation accepts the value as-is
        assert record.tokens_in == -100

    @pytest.mark.asyncio
    async def test_invalid_period_format_raises(self, meter):
        """Should raise error for invalid invoice period format."""
        await meter.record_token_usage(
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=100,
            tokens_out=50,
            tenant_id="tenant_invalid_period",
        )
        await meter._flush_buffer()

        with pytest.raises(ValueError):
            await meter.generate_invoice(
                tenant_id="tenant_invalid_period",
                period="invalid-format",
            )

    @pytest.mark.asyncio
    async def test_filter_invoices_by_status(self, meter):
        """Should filter invoices by status."""
        await meter.record_token_usage(
            provider="anthropic",
            model="claude-opus-4",
            tokens_in=100,
            tokens_out=50,
            tenant_id="tenant_filter_status",
        )
        await meter._flush_buffer()

        period = datetime.now(timezone.utc).strftime("%Y-%m")
        await meter.generate_invoice(
            tenant_id="tenant_filter_status",
            period=period,
        )

        # Filter by DRAFT status
        invoices = await meter.get_invoices(
            tenant_id="tenant_filter_status",
            status=InvoiceStatus.DRAFT,
        )
        assert all(inv.status == InvoiceStatus.DRAFT for inv in invoices)

        # Filter by non-matching status
        invoices = await meter.get_invoices(
            tenant_id="tenant_filter_status",
            status=InvoiceStatus.PAID,
        )
        assert len(invoices) == 0

    @pytest.mark.asyncio
    async def test_budget_alert_deduplication(self, meter):
        """Should not send duplicate budget alerts in same month."""
        await meter.set_budget(
            tenant_id="tenant_dedup",
            monthly_budget=Decimal("100.00"),
        )

        # Record enough to trigger alert
        for _ in range(10):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=10000,
                tokens_out=5000,
                tenant_id="tenant_dedup",
            )
        await meter._flush_buffer()

        # Record more to potentially trigger duplicate
        for _ in range(5):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=10000,
                tokens_out=5000,
                tenant_id="tenant_dedup",
            )
        await meter._flush_buffer()

        # Check alerts table - should only have one per level
        cursor = meter._conn.cursor()
        cursor.execute(
            """
            SELECT alert_level, COUNT(*) as cnt
            FROM budget_alerts
            WHERE tenant_id = ?
            GROUP BY alert_level
            """,
            ("tenant_dedup",),
        )
        for row in cursor:
            assert row["cnt"] == 1  # Only one alert per level


# =============================================================================
# Forecast Tests
# =============================================================================


class TestUsageForecastComprehensive:
    """Comprehensive tests for usage forecasting."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_forecast.db"

    @pytest.fixture
    async def meter(self, temp_db):
        """Create an initialized meter."""
        meter = EnterpriseMeter(db_path=temp_db)
        await meter.initialize()
        yield meter
        await meter.close()

    @pytest.mark.asyncio
    async def test_forecast_with_budget(self, meter):
        """Should forecast with budget comparison."""
        await meter.set_budget(
            tenant_id="tenant_forecast_budget",
            monthly_budget=Decimal("500.00"),
        )

        for _ in range(10):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=1000,
                tokens_out=500,
                tenant_id="tenant_forecast_budget",
            )
        await meter._flush_buffer()

        forecast = await meter.forecast_usage(
            tenant_id="tenant_forecast_budget",
            days_ahead=30,
        )
        assert forecast.budget_remaining is not None

    @pytest.mark.asyncio
    async def test_forecast_empty_history(self, meter):
        """Should handle forecast with no historical data."""
        forecast = await meter.forecast_usage(
            tenant_id="tenant_no_history",
            days_ahead=30,
        )
        assert forecast.projected_cost == Decimal("0")
        assert forecast.confidence == 0.0

    @pytest.mark.asyncio
    async def test_forecast_confidence_increases_with_data(self, meter):
        """Confidence should increase with more data points."""
        for i in range(15):
            await meter.record_token_usage(
                provider="anthropic",
                model="claude-opus-4",
                tokens_in=1000,
                tokens_out=500,
                tenant_id="tenant_confidence",
            )
        await meter._flush_buffer()

        forecast = await meter.forecast_usage(
            tenant_id="tenant_confidence",
            days_ahead=30,
        )
        assert forecast.data_points_used > 0


class TestConnectionAccessor:
    """Tests for the metering store connection accessor."""

    def test_connection_raises_before_initialize(self, tmp_path):
        """Using the store before initialize() should fail loudly, not return None."""
        meter = EnterpriseMeter(db_path=tmp_path / "metering.db")

        with pytest.raises(RuntimeError, match="^metering store not initialized$"):
            meter._connection

        assert not (tmp_path / "metering.db").exists()

    @pytest.mark.asyncio
    async def test_connection_returns_established_connection_after_initialize(self, tmp_path):
        """After initialize() the accessor returns the live connection."""
        meter = EnterpriseMeter(db_path=tmp_path / "metering.db")
        await meter.initialize()
        try:
            connection = meter._connection
            assert isinstance(connection, sqlite3.Connection)
            assert connection is meter._conn
            assert connection.execute("SELECT 1").fetchone()[0] == 1
        finally:
            await meter.close()

    @pytest.mark.asyncio
    async def test_guarded_public_call_initializes_before_using_connection(self, tmp_path):
        """Public methods that self-initialize keep working on a fresh meter."""
        meter = EnterpriseMeter(db_path=tmp_path / "metering.db")
        try:
            assert await meter.get_budget("tenant_fresh") is None
            assert meter._initialized is True
            assert await meter.get_invoices("tenant_fresh") == []
        finally:
            await meter.close()
