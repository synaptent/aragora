"""
Tests for RBAC Quota Enforcement.

Tests cover:
- QuotaPolicy configuration
- QuotaEnforcer behavior
- Usage tracking and recording
- Quota limit enforcement
- Cost tracking
- Period calculations
- Redis persistence
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.rbac.quotas import (
    QuotaEnforcer,
    QuotaExceededError,
    QuotaPeriod,
    QuotaPolicy,
    QuotaUsage,
    UsageRecord,
    get_quota_enforcer,
    require_quota,
)


# ============================================================================
# QuotaPeriod Tests
# ============================================================================


class TestQuotaPeriod:
    """Tests for QuotaPeriod enum."""

    def test_period_values(self):
        """Test all period values are defined."""
        assert QuotaPeriod.HOURLY == "hourly"
        assert QuotaPeriod.DAILY == "daily"
        assert QuotaPeriod.WEEKLY == "weekly"
        assert QuotaPeriod.MONTHLY == "monthly"
        assert QuotaPeriod.PER_REQUEST == "per_request"

    def test_period_is_string(self):
        """Test periods are string-based."""
        assert isinstance(QuotaPeriod.DAILY.value, str)


# ============================================================================
# QuotaPolicy Tests
# ============================================================================


class TestQuotaPolicy:
    """Tests for QuotaPolicy dataclass."""

    def test_create_basic_policy(self):
        """Test creating a basic policy."""
        policy = QuotaPolicy(
            resource_type="debates",
            limit=100,
            period=QuotaPeriod.DAILY,
        )

        assert policy.resource_type == "debates"
        assert policy.limit == 100
        assert policy.period == QuotaPeriod.DAILY
        assert policy.cost_per_unit == 0.0
        assert policy.hard_limit is True

    def test_create_full_policy(self):
        """Test creating a policy with all options."""
        policy = QuotaPolicy(
            resource_type="api_calls",
            limit=10000,
            period=QuotaPeriod.DAILY,
            cost_per_unit=0.001,
            cost_center="engineering",
            hard_limit=False,
            burst_limit=15000,
            burst_window_seconds=120,
            metadata={"tier": "premium"},
        )

        assert policy.cost_per_unit == 0.001
        assert policy.cost_center == "engineering"
        assert policy.hard_limit is False
        assert policy.burst_limit == 15000
        assert policy.burst_window_seconds == 120
        assert policy.metadata["tier"] == "premium"

    def test_to_dict(self):
        """Test policy serialization."""
        policy = QuotaPolicy(
            resource_type="storage_mb",
            limit=1000,
            period=QuotaPeriod.MONTHLY,
            cost_per_unit=0.01,
        )

        data = policy.to_dict()

        assert data["resource_type"] == "storage_mb"
        assert data["limit"] == 1000
        assert data["period"] == "monthly"
        assert data["cost_per_unit"] == 0.01


# ============================================================================
# QuotaUsage Tests
# ============================================================================


class TestQuotaUsage:
    """Tests for QuotaUsage dataclass."""

    def test_create_usage(self):
        """Test creating usage report."""
        now = datetime.now(timezone.utc)
        usage = QuotaUsage(
            resource_type="debates",
            period=QuotaPeriod.DAILY,
            limit=100,
            used=75,
            remaining=25,
            cost_incurred=7.50,
            period_start=now,
            period_end=now + timedelta(days=1),
            is_exceeded=False,
            percentage_used=75.0,
        )

        assert usage.used == 75
        assert usage.remaining == 25
        assert usage.is_exceeded is False
        assert usage.percentage_used == 75.0

    def test_to_dict(self):
        """Test usage serialization."""
        now = datetime.now(timezone.utc)
        usage = QuotaUsage(
            resource_type="debates",
            period=QuotaPeriod.DAILY,
            limit=100,
            used=50,
            remaining=50,
            cost_incurred=5.0,
            period_start=now,
            period_end=now + timedelta(days=1),
            is_exceeded=False,
            percentage_used=50.0,
        )

        data = usage.to_dict()

        assert data["used"] == 50
        assert data["remaining"] == 50
        assert "period_start" in data
        assert "period_end" in data


# ============================================================================
# UsageRecord Tests
# ============================================================================


class TestUsageRecord:
    """Tests for UsageRecord dataclass."""

    def test_create_record(self):
        """Test creating a usage record."""
        now = datetime.now(timezone.utc)
        record = UsageRecord(
            user_id="user-123",
            org_id="org-456",
            workspace_id="ws-789",
            resource_type="debates",
            amount=1,
            cost=0.10,
            timestamp=now,
        )

        assert record.user_id == "user-123"
        assert record.org_id == "org-456"
        assert record.amount == 1
        assert record.cost == 0.10

    def test_to_storage_dict(self):
        """Test serialization for Redis storage."""
        now = datetime.now(timezone.utc)
        record = UsageRecord(
            user_id="user-123",
            org_id=None,
            workspace_id=None,
            resource_type="api_calls",
            amount=5,
            cost=0.005,
            timestamp=now,
            metadata={"endpoint": "/api/v1/debates"},
        )

        data = record.to_storage_dict()

        assert data["user_id"] == "user-123"
        assert data["org_id"] is None
        assert data["amount"] == 5
        assert data["cost"] == 0.005
        assert "timestamp" in data
        assert data["metadata"]["endpoint"] == "/api/v1/debates"

    def test_from_storage_dict(self):
        """Test deserialization from Redis storage."""
        data = {
            "user_id": "user-123",
            "org_id": "org-456",
            "workspace_id": None,
            "resource_type": "debates",
            "amount": 3,
            "cost": 0.30,
            "timestamp": "2024-01-15T10:30:00+00:00",
            "metadata": {"source": "api"},
        }

        record = UsageRecord.from_storage_dict(data)

        assert record.user_id == "user-123"
        assert record.org_id == "org-456"
        assert record.amount == 3
        assert record.cost == 0.30
        assert record.timestamp.year == 2024

    def test_from_storage_dict_missing_fields(self):
        """Test deserialization with missing fields uses defaults."""
        data = {"user_id": "user-123"}

        record = UsageRecord.from_storage_dict(data)

        assert record.user_id == "user-123"
        assert record.amount == 0
        assert record.cost == 0.0


# ============================================================================
# QuotaEnforcer Tests
# ============================================================================


class TestQuotaEnforcer:
    """Tests for QuotaEnforcer class."""

    def setup_method(self):
        """Set up test enforcer."""
        self.enforcer = QuotaEnforcer(enable_persistence=False)

    def test_default_quotas(self):
        """Test default quotas are set."""
        assert "debates" in self.enforcer._policies
        assert "api_calls" in self.enforcer._policies
        assert "storage_mb" in self.enforcer._policies

    def test_set_policy_global(self):
        """Test setting a global policy."""
        policy = QuotaPolicy(
            resource_type="custom",
            limit=50,
            period=QuotaPeriod.DAILY,
        )

        self.enforcer.set_policy(policy)

        assert "custom" in self.enforcer._policies
        assert self.enforcer._policies["custom"].limit == 50

    def test_set_policy_org_specific(self):
        """Test setting an org-specific policy."""
        policy = QuotaPolicy(
            resource_type="debates",
            limit=200,
            period=QuotaPeriod.DAILY,
        )

        self.enforcer.set_policy(policy, org_id="org-premium")

        # Global should be unchanged
        assert self.enforcer._policies["debates"].limit == 100
        # Org-specific should be set
        assert self.enforcer._org_policies["org-premium"]["debates"].limit == 200

    def test_get_policy_global(self):
        """Test getting global policy."""
        policy = self.enforcer.get_policy("debates")

        assert policy is not None
        assert policy.limit == 100

    def test_get_policy_org_specific(self):
        """Test org-specific policy takes precedence."""
        org_policy = QuotaPolicy(
            resource_type="debates",
            limit=500,
            period=QuotaPeriod.DAILY,
        )
        self.enforcer.set_policy(org_policy, org_id="org-enterprise")

        policy = self.enforcer.get_policy("debates", org_id="org-enterprise")

        assert policy.limit == 500

    def test_get_policy_not_found(self):
        """Test returns None for unknown resource."""
        policy = self.enforcer.get_policy("unknown_resource")
        assert policy is None

    @pytest.mark.asyncio
    async def test_check_quota_allowed(self):
        """Test quota check allows usage under limit."""
        result = await self.enforcer.check_quota(
            user_id="user-123",
            resource_type="debates",
            amount=1,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_check_quota_denied(self):
        """Test quota check denies usage over limit."""
        # Record max usage
        for i in range(100):
            await self.enforcer.record_usage("user-123", "debates", amount=1)

        # Next request should be denied
        result = await self.enforcer.check_quota(
            user_id="user-123",
            resource_type="debates",
            amount=1,
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_check_quota_no_policy(self):
        """Test no policy means no limit."""
        result = await self.enforcer.check_quota(
            user_id="user-123",
            resource_type="unknown_resource",
            amount=1000000,
        )

        assert result is True  # No policy = no limit

    @pytest.mark.asyncio
    async def test_check_quota_soft_limit(self):
        """Test soft limit allows but warns."""
        soft_policy = QuotaPolicy(
            resource_type="soft_resource",
            limit=5,
            period=QuotaPeriod.DAILY,
            hard_limit=False,
        )
        self.enforcer.set_policy(soft_policy)

        # Use up limit
        for i in range(5):
            await self.enforcer.record_usage("user-123", "soft_resource", amount=1)

        # Should still be allowed (soft limit)
        result = await self.enforcer.check_quota(
            user_id="user-123",
            resource_type="soft_resource",
            amount=1,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_check_quota_burst_allowance(self):
        """Test burst allowance above regular limit."""
        burst_policy = QuotaPolicy(
            resource_type="burst_resource",
            limit=10,
            period=QuotaPeriod.DAILY,
            burst_limit=15,
            burst_window_seconds=60,
        )
        self.enforcer.set_policy(burst_policy)

        # Use up regular limit
        for i in range(10):
            await self.enforcer.record_usage("user-123", "burst_resource", amount=1)

        # Should still be allowed within burst
        result = await self.enforcer.check_quota(
            user_id="user-123",
            resource_type="burst_resource",
            amount=1,
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_record_usage(self):
        """Test recording usage."""
        record = await self.enforcer.record_usage(
            user_id="user-123",
            resource_type="debates",
            amount=1,
        )

        assert record.user_id == "user-123"
        assert record.resource_type == "debates"
        assert record.amount == 1

    @pytest.mark.asyncio
    async def test_record_usage_calculates_cost(self):
        """Test usage recording calculates cost from policy."""
        record = await self.enforcer.record_usage(
            user_id="user-123",
            resource_type="debates",
            amount=5,
        )

        # Default debates policy has cost_per_unit=0.10
        assert record.cost == 0.50

    @pytest.mark.asyncio
    async def test_record_usage_custom_cost(self):
        """Test usage recording with custom cost."""
        record = await self.enforcer.record_usage(
            user_id="user-123",
            resource_type="debates",
            amount=1,
            cost=1.00,  # Override default cost
        )

        assert record.cost == 1.00

    @pytest.mark.asyncio
    async def test_get_usage(self):
        """Test getting usage statistics."""
        await self.enforcer.record_usage("user-123", "debates", amount=10)
        await self.enforcer.record_usage("user-123", "debates", amount=5)

        usage = await self.enforcer.get_usage("user-123", "debates")

        assert usage.used == 15
        assert usage.remaining == 85  # 100 - 15
        assert usage.is_exceeded is False
        assert usage.percentage_used == 15.0

    @pytest.mark.asyncio
    async def test_get_usage_exceeded(self):
        """Test usage shows exceeded status."""
        for i in range(110):
            await self.enforcer.record_usage("user-123", "debates", amount=1)

        usage = await self.enforcer.get_usage("user-123", "debates")

        assert usage.used == 110
        assert usage.remaining == 0
        assert usage.is_exceeded is True

    @pytest.mark.asyncio
    async def test_get_all_usage(self):
        """Test getting all resource usage."""
        await self.enforcer.record_usage("user-123", "debates", amount=5)
        await self.enforcer.record_usage("user-123", "api_calls", amount=100)

        all_usage = await self.enforcer.get_all_usage("user-123")

        assert "debates" in all_usage
        assert "api_calls" in all_usage
        assert all_usage["debates"].used == 5
        assert all_usage["api_calls"].used == 100

    @pytest.mark.asyncio
    async def test_get_cost_report(self):
        """Test cost report generation."""
        await self.enforcer.record_usage("user-1", "debates", amount=10, org_id="org-123")
        await self.enforcer.record_usage("user-2", "debates", amount=5, org_id="org-123")
        await self.enforcer.record_usage("user-1", "api_calls", amount=1000, org_id="org-123")

        report = await self.enforcer.get_cost_report(
            org_id="org-123",
            period=QuotaPeriod.MONTHLY,
        )

        assert report["org_id"] == "org-123"
        assert report["total_cost"] > 0
        assert "debates" in report["by_resource"]
        assert "api_calls" in report["by_resource"]
        assert "user-1" in report["by_user"]

    @pytest.mark.asyncio
    async def test_cleanup_old_records(self):
        """Test cleanup of old records."""
        # Create a record with old timestamp
        old_record = UsageRecord(
            user_id="user-123",
            org_id=None,
            workspace_id=None,
            resource_type="debates",
            amount=1,
            cost=0.10,
            timestamp=datetime.now(timezone.utc) - timedelta(days=100),
        )
        key = self.enforcer._usage_key("user-123", "debates", None, None)
        self.enforcer._usage[key] = [old_record]

        # Add a recent record
        await self.enforcer.record_usage("user-123", "debates", amount=1)

        # Cleanup records older than 90 days
        count = await self.enforcer.cleanup_old_records(days=90)

        assert count == 1
        # Should have 1 record remaining (the recent one)
        assert len(self.enforcer._usage[key]) == 1

    def test_usage_key_generation(self):
        """Test usage key generation."""
        key1 = self.enforcer._usage_key("user-1", "debates", None, None)
        key2 = self.enforcer._usage_key("user-1", "debates", "org-1", None)
        key3 = self.enforcer._usage_key("user-1", "debates", "org-1", "ws-1")

        assert key1 == "user-1:debates"
        assert key2 == "user-1:debates:org:org-1"
        assert key3 == "user-1:debates:org:org-1:ws:ws-1"


# ============================================================================
# Period Boundary Tests
# ============================================================================


class TestPeriodBoundaries:
    """Tests for period calculation."""

    def test_hourly_bounds(self):
        """Test hourly period boundaries."""
        enforcer = QuotaEnforcer(enable_persistence=False)
        start, end = enforcer._get_period_bounds(QuotaPeriod.HOURLY)

        assert start.minute == 0
        assert start.second == 0
        assert end - start == timedelta(hours=1)

    def test_daily_bounds(self):
        """Test daily period boundaries."""
        enforcer = QuotaEnforcer(enable_persistence=False)
        start, end = enforcer._get_period_bounds(QuotaPeriod.DAILY)

        assert start.hour == 0
        assert start.minute == 0
        assert end - start == timedelta(days=1)

    def test_weekly_bounds(self):
        """Test weekly period boundaries."""
        enforcer = QuotaEnforcer(enable_persistence=False)
        start, end = enforcer._get_period_bounds(QuotaPeriod.WEEKLY)

        assert start.weekday() == 0  # Monday
        assert end - start == timedelta(weeks=1)


# ============================================================================
# Decorator Tests
# ============================================================================


class TestRequireQuotaDecorator:
    """Tests for @require_quota decorator."""

    @pytest.mark.asyncio
    async def test_decorator_allows_under_quota(self):
        """Test decorator allows when under quota."""

        @require_quota("debates", amount=1)
        async def create_debate(ctx):
            return "created"

        ctx = MagicMock()
        ctx.user_id = "user-123"
        ctx.org_id = None
        ctx.workspace_id = None

        with patch("aragora.rbac.quotas.get_quota_enforcer") as mock_get:
            mock_enforcer = MagicMock()
            mock_enforcer.check_quota = AsyncMock(return_value=True)
            mock_enforcer.record_usage = AsyncMock()
            mock_get.return_value = mock_enforcer

            result = await create_debate(ctx=ctx)

            assert result == "created"
            mock_enforcer.record_usage.assert_called_once()

    @pytest.mark.asyncio
    async def test_decorator_raises_when_exceeded(self):
        """Test decorator raises QuotaExceededError when exceeded."""

        @require_quota("debates", amount=1)
        async def create_debate(ctx):
            return "created"

        ctx = MagicMock()
        ctx.user_id = "user-123"
        ctx.org_id = None
        ctx.workspace_id = None

        with patch("aragora.rbac.quotas.get_quota_enforcer") as mock_get:
            mock_enforcer = MagicMock()
            mock_enforcer.check_quota = AsyncMock(return_value=False)
            mock_get.return_value = mock_enforcer

            with pytest.raises(QuotaExceededError):
                await create_debate(ctx=ctx)

    @pytest.mark.asyncio
    async def test_decorator_skips_without_user_id(self):
        """Test decorator allows without user context."""

        @require_quota("debates", amount=1)
        async def create_debate(ctx):
            return "created"

        ctx = MagicMock()
        ctx.user_id = None

        # Should not call enforcer and just pass through
        result = await create_debate(ctx=ctx)
        assert result == "created"


# ============================================================================
# Singleton Tests
# ============================================================================


class TestSingleton:
    """Tests for singleton behavior."""

    @pytest.fixture(autouse=True)
    def _reset_quota_enforcer_singleton(self):
        """Reset quota enforcer singleton before/after each test."""
        import aragora.rbac.quotas as quotas_module

        quotas_module._enforcer = None
        yield
        quotas_module._enforcer = None

    def test_get_quota_enforcer(self):
        """Test singleton returns same instance."""
        enforcer1 = get_quota_enforcer()
        enforcer2 = get_quota_enforcer()

        assert enforcer1 is enforcer2


# ============================================================================
# Redis Persistence Tests
# ============================================================================


class TestRedisPersistence:
    """Tests for Redis persistence functionality."""

    def test_persistence_disabled_by_default(self):
        """Test persistence is disabled when env var not set."""
        enforcer = QuotaEnforcer()
        # Default should be disabled since env var isn't set
        assert enforcer._persistence_enabled is False

    def test_persistence_explicit_enable(self):
        """Test persistence can be explicitly enabled."""
        enforcer = QuotaEnforcer(enable_persistence=True)
        assert enforcer._persistence_enabled is True

    def test_usage_redis_key_format(self):
        """Test Redis key format."""
        enforcer = QuotaEnforcer(enable_persistence=False)
        key = enforcer._usage_redis_key("user-123:debates")
        assert key == "aragora:quota:usage:user-123:debates"

    @pytest.mark.asyncio
    async def test_persist_usage_when_enabled(self):
        """Test usage is persisted when enabled."""
        mock_redis = MagicMock()
        mock_redis.rpush = MagicMock()
        mock_redis.ltrim = MagicMock()
        mock_redis.expire = MagicMock()

        enforcer = QuotaEnforcer(enable_persistence=True)
        enforcer._redis = mock_redis
        enforcer._redis_checked = True

        await enforcer.record_usage("user-123", "debates", amount=1)

        mock_redis.rpush.assert_called_once()

    def test_get_redis_lazy_init(self):
        """Test Redis client is lazily initialized."""
        # When persistence is disabled, _get_redis is never called during init
        enforcer = QuotaEnforcer(enable_persistence=False)

        # Manually enable for testing
        enforcer._persistence_enabled = True
        enforcer._redis_checked = False  # Reset for test

        # After calling _get_redis (will fail without actual Redis)
        with patch("aragora.utils.redis_config.get_redis_client", return_value=None):
            result = enforcer._get_redis()

        assert enforcer._redis_checked is True
        assert result is None  # No Redis available


# ============================================================================
# Error Handling Tests
# ============================================================================


class TestQuotaExceededError:
    """Tests for QuotaExceededError."""

    def test_error_basic(self):
        """Test basic error creation."""
        error = QuotaExceededError("Limit reached")
        assert str(error) == "Limit reached"

    def test_error_with_details(self):
        """Test error with resource details."""
        error = QuotaExceededError(
            "Daily debate limit exceeded",
            resource_type="debates",
            limit=100,
        )

        assert error.resource_type == "debates"
        assert error.limit == 100
