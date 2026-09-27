"""
Tests for usage tracking system.

Tests for recording usage events, aggregation, and billing period calculations.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from aragora.billing.usage import (
    PROVIDER_PRICING,
    UsageEvent,
    UsageEventType,
    UsageSummary,
    UsageTracker,
    calculate_token_cost,
)


# =============================================================================
# Token Cost Calculation Tests
# =============================================================================


class TestTokenCostCalculation:
    """Tests for calculate_token_cost function."""

    def test_anthropic_opus_pricing(self):
        """Test Anthropic Claude Opus pricing."""
        cost = calculate_token_cost("anthropic", "claude-opus-4", 1_000_000, 100_000)
        # $5.00 per 1M input + $25.00 per 1M output * 0.1 = $5 + $2.5 = $7.5
        assert cost == Decimal("7.50")

    def test_anthropic_sonnet_pricing(self):
        """Test Anthropic Claude Sonnet pricing."""
        cost = calculate_token_cost("anthropic", "claude-sonnet-4", 1_000_000, 1_000_000)
        # $3.00 per 1M input + $15.00 per 1M output = $18
        assert cost == Decimal("18.00")

    def test_openai_gpt4o_pricing(self):
        """Test OpenAI GPT-4o pricing."""
        cost = calculate_token_cost("openai", "gpt-4o", 500_000, 200_000)
        # $2.50 per 1M input * 0.5 + $10.00 per 1M output * 0.2 = $1.25 + $2.00 = $3.25
        assert cost == Decimal("3.25")

    def test_openai_gpt55_pricing_matches_canonical_table(self):
        """Test OpenAI GPT-5.5 pricing matches the canonical live invoker table."""
        cost = calculate_token_cost("openai", "gpt-5.5", 1_000_000, 1_000_000)
        # $5.00 per 1M input + $30.00 per 1M output = $35.00 (live 2026-07-16)
        assert cost == Decimal("35.00")

    def test_openai_gpt4o_mini_pricing(self):
        """Test OpenAI GPT-4o-mini pricing."""
        cost = calculate_token_cost("openai", "gpt-4o-mini", 10_000_000, 5_000_000)
        # $0.15 per 1M * 10 + $0.60 per 1M * 5 = $1.50 + $3.00 = $4.50
        assert cost == Decimal("4.50")

    def test_google_gemini_pricing(self):
        """Test Google Gemini Pro pricing."""
        cost = calculate_token_cost("google", "gemini-pro", 2_000_000, 1_000_000)
        # $1.25 per 1M * 2 + $5.00 per 1M * 1 = $2.50 + $5.00 = $7.50
        assert cost == Decimal("7.50")

    def test_google_gemini_35_flash_pricing_matches_documented_table(self):
        """Test Gemini 3.5 Flash pricing matches the documented agentic-tier rate."""
        cost = calculate_token_cost("google", "gemini-3.5-flash", 1_000_000, 1_000_000)
        # $1.50 per 1M input + $9.00 per 1M output = $10.50
        assert cost == Decimal("10.50")

    @pytest.mark.parametrize("model", ["gemini-3.1-pro", "gemini-3.1-pro-preview"])
    def test_google_gemini_31_pro_pricing_matches_standard_tier(self, model: str):
        """Gemini 3.1 Pro aliases use the canonical standard text tier."""
        cost = calculate_token_cost("google", model, 1_000_000, 1_000_000)
        # $2.00 per 1M input + $12.00 per 1M output = $14.00
        assert cost == Decimal("14.00")

    def test_openrouter_openai_gpt55_alias_uses_canonical_pricing(self):
        """Test OpenRouter-qualified GPT-5.5 does not fall back to default pricing."""
        cost = calculate_token_cost("openrouter", "openai/gpt-5.5", 1_000_000, 1_000_000)
        # $5.00 per 1M input + $30.00 per 1M output = $35.00 (live 2026-07-16)
        assert cost == Decimal("35.00")

    def test_openrouter_google_gemini_35_flash_alias_uses_canonical_pricing(self):
        """Test OpenRouter-qualified Gemini 3.5 Flash does not fall back to default."""
        cost = calculate_token_cost("openrouter", "google/gemini-3.5-flash", 1_000_000, 1_000_000)
        # $1.50 per 1M input + $9.00 per 1M output = $10.50
        assert cost == Decimal("10.50")

    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("anthropic/claude-opus-4-8", Decimal("30.00")),
            ("anthropic/claude-opus-4.8", Decimal("30.00")),
            ("anthropic/claude-opus-4-7", Decimal("30.00")),
            ("anthropic/claude-opus-4.7", Decimal("30.00")),
            ("anthropic/claude-haiku-4-5", Decimal("6.00")),
            ("anthropic/claude-haiku-4.5", Decimal("6.00")),
            ("anthropic/claude-haiku-4-5-20251001", Decimal("6.00")),
        ],
    )
    def test_openrouter_anthropic_runtime_aliases_use_canonical_pricing(
        self, model: str, expected: Decimal
    ):
        """OpenRouter-qualified Anthropic runtime IDs must not use defaults."""
        cost = calculate_token_cost("openrouter", model, 1_000_000, 1_000_000)
        assert cost == expected

    def test_deepseek_pricing(self):
        """Test DeepSeek pricing."""
        cost = calculate_token_cost("deepseek", "deepseek-v4-pro", 10_000_000, 5_000_000)
        # $1.74 per 1M * 10 + $3.48 per 1M * 5 = $17.40 + $17.40 = $34.80
        assert cost == Decimal("34.80")

    def test_unknown_provider_uses_openrouter_default(self):
        """Test that unknown providers use OpenRouter default pricing."""
        cost = calculate_token_cost("unknown_provider", "some_model", 1_000_000, 1_000_000)
        # Default: $2.00 per 1M input + $8.00 per 1M output = $10.00
        assert cost == Decimal("10.00")

    def test_unknown_model_uses_default_pricing(self):
        """Test that unknown models use default pricing for provider."""
        cost = calculate_token_cost("anthropic", "unknown-model", 1_000_000, 1_000_000)
        # Falls back to openrouter default: $2.00 + $8.00 = $10.00
        assert cost == Decimal("10.00")

    def test_zero_tokens_zero_cost(self):
        """Test that zero tokens results in zero cost."""
        cost = calculate_token_cost("anthropic", "claude-opus-4", 0, 0)
        assert cost == Decimal("0")

    def test_small_token_counts(self):
        """Test cost calculation for small token counts."""
        cost = calculate_token_cost("anthropic", "claude-sonnet-4", 1000, 500)
        # Very small amounts: $3.00 * 0.001 + $15.00 * 0.0005 = $0.003 + $0.0075 = $0.0105
        expected = (Decimal("1000") / Decimal("1000000")) * Decimal("3.00")
        expected += (Decimal("500") / Decimal("1000000")) * Decimal("15.00")
        assert cost == expected


# =============================================================================
# UsageEvent Tests
# =============================================================================


class TestUsageEvent:
    """Tests for UsageEvent dataclass."""

    def test_create_default_event(self):
        """Test creating event with default values."""
        event = UsageEvent()
        assert event.id is not None
        assert len(event.id) == 36  # UUID format
        assert event.user_id == ""
        assert event.event_type == UsageEventType.DEBATE
        assert event.tokens_in == 0
        assert event.cost_usd == Decimal("0")

    def test_create_event_with_values(self):
        """Test creating event with specific values."""
        event = UsageEvent(
            user_id="user_123",
            org_id="org_456",
            event_type=UsageEventType.AGENT_CALL,
            tokens_in=1000,
            tokens_out=500,
            provider="anthropic",
            model="claude-sonnet-4",
        )
        assert event.user_id == "user_123"
        assert event.org_id == "org_456"
        assert event.event_type == UsageEventType.AGENT_CALL
        assert event.tokens_in == 1000

    def test_calculate_cost(self):
        """Test cost calculation on event."""
        event = UsageEvent(
            provider="anthropic",
            model="claude-sonnet-4",
            tokens_in=1_000_000,
            tokens_out=500_000,
        )
        cost = event.calculate_cost()
        # $3.00 per 1M input + $15.00 per 1M * 0.5 = $3.00 + $7.50 = $10.50
        assert cost == Decimal("10.50")
        assert event.cost_usd == Decimal("10.50")

    def test_to_dict(self):
        """Test serialization to dictionary."""
        event = UsageEvent(
            id="evt_123",
            user_id="user_456",
            org_id="org_789",
            event_type=UsageEventType.DEBATE,
            debate_id="debate_abc",
            tokens_in=1000,
            tokens_out=500,
            provider="openai",
            model="gpt-4o",
            cost_usd=Decimal("0.05"),
            metadata={"key": "value"},
        )
        d = event.to_dict()

        assert d["id"] == "evt_123"
        assert d["user_id"] == "user_456"
        assert d["event_type"] == "debate"
        assert d["tokens_in"] == 1000
        assert d["cost_usd"] == "0.05"
        assert d["metadata"] == {"key": "value"}
        assert "created_at" in d

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "id": "evt_123",
            "user_id": "user_456",
            "org_id": "org_789",
            "event_type": "agent_call",
            "tokens_in": 1000,
            "tokens_out": 500,
            "provider": "openai",
            "model": "gpt-4o",
            "cost_usd": "0.05",
            "metadata": {"agent": "claude"},
            "created_at": "2024-01-15T10:30:00",
        }
        event = UsageEvent.from_dict(data)

        assert event.id == "evt_123"
        assert event.user_id == "user_456"
        assert event.event_type == UsageEventType.AGENT_CALL
        assert event.cost_usd == Decimal("0.05")
        assert event.created_at == datetime(2024, 1, 15, 10, 30, 0)

    def test_from_dict_missing_optional_fields(self):
        """Test deserialization with missing optional fields."""
        data = {"event_type": "debate"}
        event = UsageEvent.from_dict(data)

        assert event.user_id == ""
        assert event.tokens_in == 0
        assert event.metadata == {}


# =============================================================================
# UsageSummary Tests
# =============================================================================


class TestUsageSummary:
    """Tests for UsageSummary dataclass."""

    def test_create_summary(self):
        """Test creating usage summary."""
        now = datetime.now(timezone.utc)
        summary = UsageSummary(
            org_id="org_123",
            period_start=now - timedelta(days=30),
            period_end=now,
            total_debates=50,
            total_tokens_in=1_000_000,
            total_tokens_out=500_000,
            total_cost_usd=Decimal("15.50"),
        )

        assert summary.org_id == "org_123"
        assert summary.total_debates == 50
        assert summary.total_cost_usd == Decimal("15.50")

    def test_summary_to_dict(self):
        """Test summary serialization."""
        now = datetime.now(timezone.utc)
        summary = UsageSummary(
            org_id="org_123",
            period_start=now - timedelta(days=30),
            period_end=now,
            total_debates=10,
            total_cost_usd=Decimal("5.00"),
            cost_by_provider={"anthropic": Decimal("3.00"), "openai": Decimal("2.00")},
            debates_by_day={"2024-01-15": 3, "2024-01-16": 7},
        )

        d = summary.to_dict()

        assert d["org_id"] == "org_123"
        assert d["total_debates"] == 10
        assert d["total_cost_usd"] == "5.00"
        assert d["cost_by_provider"]["anthropic"] == "3.00"
        assert d["debates_by_day"]["2024-01-15"] == 3


# =============================================================================
# UsageTracker Tests
# =============================================================================


class TestUsageTrackerInit:
    """Tests for UsageTracker initialization."""

    def test_init_creates_database(self, tmp_path):
        """Test that initialization creates the database."""
        db_path = tmp_path / "usage.db"
        tracker = UsageTracker(db_path=db_path)

        assert db_path.exists()

    def test_init_creates_parent_directories(self, tmp_path):
        """Test that initialization creates parent directories."""
        db_path = tmp_path / "subdir" / "nested" / "usage.db"
        tracker = UsageTracker(db_path=db_path)

        assert db_path.exists()

    def test_schema_creates_tables(self, tmp_path):
        """Test that schema creates required tables."""
        db_path = tmp_path / "usage.db"
        tracker = UsageTracker(db_path=db_path)

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_events'"
            )
            assert cursor.fetchone() is not None

    def test_schema_creates_indexes(self, tmp_path):
        """Test that schema creates required indexes."""
        db_path = tmp_path / "usage.db"
        tracker = UsageTracker(db_path=db_path)

        with sqlite3.connect(str(db_path)) as conn:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = [row[0] for row in cursor.fetchall()]
            assert "idx_usage_org_created" in indexes
            assert "idx_usage_user_created" in indexes
            assert "idx_usage_debate" in indexes


class TestUsageTrackerRecord:
    """Tests for recording usage events."""

    def test_record_event(self, tmp_path):
        """Test recording a usage event."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")
        event = UsageEvent(
            user_id="user_123",
            org_id="org_456",
            event_type=UsageEventType.DEBATE,
            tokens_in=1000,
            tokens_out=500,
            provider="anthropic",
            model="claude-sonnet-4",
        )

        tracker.record(event)

        # Verify it was stored
        with sqlite3.connect(str(tmp_path / "usage.db")) as conn:
            cursor = conn.execute("SELECT * FROM usage_events WHERE id = ?", (event.id,))
            row = cursor.fetchone()
            assert row is not None

    def test_record_calculates_cost_if_not_set(self, tmp_path):
        """Test that record calculates cost if not already set."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")
        event = UsageEvent(
            user_id="user_123",
            org_id="org_456",
            tokens_in=1_000_000,
            tokens_out=500_000,
            provider="anthropic",
            model="claude-sonnet-4",
        )
        assert event.cost_usd == Decimal("0")

        tracker.record(event)

        # Cost should have been calculated
        assert event.cost_usd > Decimal("0")

    def test_record_preserves_set_cost(self, tmp_path):
        """Test that record preserves manually set cost."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")
        event = UsageEvent(
            user_id="user_123",
            org_id="org_456",
            tokens_in=1000,
            tokens_out=500,
            provider="anthropic",
            model="claude-sonnet-4",
            cost_usd=Decimal("999.99"),  # Manually set
        )

        tracker.record(event)

        # Cost should be preserved
        assert event.cost_usd == Decimal("999.99")

    def test_record_debate(self, tmp_path):
        """Test record_debate convenience method."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")

        event = tracker.record_debate(
            user_id="user_123",
            org_id="org_456",
            debate_id="debate_789",
            tokens_in=5000,
            tokens_out=2000,
            provider="openai",
            model="gpt-4o",
            metadata={"topic": "AI safety"},
        )

        assert event.event_type == UsageEventType.DEBATE
        assert event.debate_id == "debate_789"
        assert event.metadata == {"topic": "AI safety"}
        assert event.cost_usd > Decimal("0")

    def test_record_agent_call(self, tmp_path):
        """Test record_agent_call convenience method."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")

        event = tracker.record_agent_call(
            user_id="user_123",
            org_id="org_456",
            debate_id="debate_789",
            agent_name="claude-3",
            tokens_in=1000,
            tokens_out=500,
            provider="anthropic",
            model="claude-sonnet-4",
        )

        assert event.event_type == UsageEventType.AGENT_CALL
        assert event.metadata["agent"] == "claude-3"


class TestUsageTrackerQueries:
    """Tests for usage query methods."""

    @pytest.fixture
    def tracker_with_data(self, tmp_path):
        """Create a tracker with sample data."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")

        # Record various events
        now = datetime.now(timezone.utc)

        # Debates
        for i in range(5):
            event = UsageEvent(
                user_id="user_1",
                org_id="org_1",
                event_type=UsageEventType.DEBATE,
                debate_id=f"debate_{i}",
                tokens_in=10000 * (i + 1),
                tokens_out=5000 * (i + 1),
                provider="anthropic",
                model="claude-sonnet-4",
            )
            event.created_at = now - timedelta(days=i)
            event.calculate_cost()
            tracker.record(event)

        # API calls
        for i in range(3):
            event = UsageEvent(
                user_id="user_1",
                org_id="org_1",
                event_type=UsageEventType.API_CALL,
                tokens_in=1000,
                tokens_out=500,
                provider="openai",
                model="gpt-4o",
            )
            event.created_at = now - timedelta(days=i)
            event.calculate_cost()
            tracker.record(event)

        # Different org
        event = UsageEvent(
            user_id="user_2",
            org_id="org_2",
            event_type=UsageEventType.DEBATE,
            tokens_in=50000,
            tokens_out=25000,
            provider="google",
            model="gemini-pro",
        )
        event.calculate_cost()
        tracker.record(event)

        return tracker

    def test_get_summary_org(self, tracker_with_data):
        """Test getting usage summary for an organization."""
        summary = tracker_with_data.get_summary("org_1")

        assert summary.org_id == "org_1"
        assert summary.total_debates == 5
        assert summary.total_api_calls == 3
        assert summary.total_tokens_in > 0
        assert summary.total_cost_usd > Decimal("0")

    def test_get_summary_with_date_range(self, tracker_with_data):
        """Test getting summary for specific date range."""
        now = datetime.now(timezone.utc)
        summary = tracker_with_data.get_summary(
            "org_1",
            period_start=now - timedelta(days=2),
            period_end=now,
        )

        # Should only include events from last 2 days
        assert summary.total_debates <= 3  # At most 3 days of data

    def test_get_summary_cost_by_provider(self, tracker_with_data):
        """Test that summary includes cost breakdown by provider."""
        summary = tracker_with_data.get_summary("org_1")

        assert "anthropic" in summary.cost_by_provider
        assert "openai" in summary.cost_by_provider
        assert summary.cost_by_provider["anthropic"] > Decimal("0")

    def test_get_summary_empty_org(self, tmp_path):
        """Test getting summary for org with no data."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")
        summary = tracker.get_summary("nonexistent_org")

        assert summary.total_debates == 0
        assert summary.total_cost_usd == Decimal("0")

    def test_get_user_usage(self, tracker_with_data):
        """Test getting usage for a specific user."""
        usage = tracker_with_data.get_user_usage("user_1", days=30)

        assert usage["user_id"] == "user_1"
        assert usage["debates"] == 5
        assert usage["total_tokens"] > 0
        assert Decimal(usage["total_cost_usd"]) > Decimal("0")

    def test_get_user_usage_no_data(self, tmp_path):
        """Test getting usage for user with no data."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")
        usage = tracker.get_user_usage("nonexistent_user")

        assert usage["debates"] == 0
        assert usage["total_tokens"] == 0

    def test_get_debate_cost(self, tmp_path):
        """Test getting total cost for a debate."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")

        # Record multiple events for same debate
        for i in range(3):
            event = UsageEvent(
                user_id="user_1",
                org_id="org_1",
                event_type=UsageEventType.AGENT_CALL,
                debate_id="debate_123",
                tokens_in=10000,
                tokens_out=5000,
                provider="anthropic",
                model="claude-sonnet-4",
            )
            event.calculate_cost()
            tracker.record(event)

        cost = tracker.get_debate_cost("debate_123")
        assert cost > Decimal("0")

    def test_get_debate_cost_nonexistent(self, tmp_path):
        """Test getting cost for non-existent debate."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")
        cost = tracker.get_debate_cost("nonexistent_debate")
        assert cost == Decimal("0")

    def test_count_debates_this_month(self, tmp_path):
        """Test counting debates in current billing month."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")
        now = datetime.now(timezone.utc)

        # Record debates this month
        for i in range(7):
            event = UsageEvent(
                user_id="user_1",
                org_id="org_1",
                event_type=UsageEventType.DEBATE,
                debate_id=f"debate_{i}",
            )
            event.created_at = now - timedelta(days=i)
            # Only count if still in current month
            if event.created_at.month == now.month:
                tracker.record(event)

        count = tracker.count_debates_this_month("org_1")
        assert count >= 1  # At least today's debate

    def test_count_debates_this_month_empty(self, tmp_path):
        """Test counting debates when none exist."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")
        count = tracker.count_debates_this_month("nonexistent_org")
        assert count == 0


class TestUsageTrackerConcurrency:
    """Tests for concurrent usage tracking."""

    def test_multiple_records_same_connection(self, tmp_path):
        """Test recording multiple events in sequence."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")

        for i in range(100):
            event = UsageEvent(
                user_id="user_1",
                org_id="org_1",
                event_type=UsageEventType.DEBATE,
                tokens_in=1000,
            )
            tracker.record(event)

        summary = tracker.get_summary("org_1")
        assert summary.total_debates == 100


# =============================================================================
# Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_very_large_token_count(self, tmp_path):
        """Test handling very large token counts."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")

        event = UsageEvent(
            user_id="user_1",
            org_id="org_1",
            tokens_in=1_000_000_000,  # 1 billion tokens
            tokens_out=500_000_000,
            provider="anthropic",
            model="claude-opus-4",
        )
        event.calculate_cost()
        tracker.record(event)

        summary = tracker.get_summary("org_1")
        assert summary.total_tokens_in == 1_000_000_000
        # Cost should be very high: $5 per 1M * 1000 + $25 per 1M * 500 = $17,500
        assert summary.total_cost_usd > Decimal("10000")

    def test_unicode_in_metadata(self, tmp_path):
        """Test handling unicode in metadata."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")

        event = UsageEvent(
            user_id="user_1",
            org_id="org_1",
            metadata={"topic": "Debate about AI - Discussion"},
        )
        tracker.record(event)

        # Should not raise
        summary = tracker.get_summary("org_1")
        assert summary is not None

    def test_empty_string_ids(self, tmp_path):
        """Test handling empty string IDs."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")

        event = UsageEvent(
            user_id="",
            org_id="",
            event_type=UsageEventType.DEBATE,
        )
        tracker.record(event)

        # Should be recorded but won't show in org-specific queries
        summary = tracker.get_summary("")
        assert summary.total_debates == 1

    def test_special_characters_in_ids(self, tmp_path):
        """Test handling special characters in IDs."""
        tracker = UsageTracker(db_path=tmp_path / "usage.db")

        event = UsageEvent(
            user_id="user@example.com",
            org_id="org-with-dashes_and_underscores",
            debate_id="debate:123:456",
        )
        tracker.record(event)

        summary = tracker.get_summary("org-with-dashes_and_underscores")
        assert summary.total_debates == 1
