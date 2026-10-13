"""
RBAC Quota Enforcement.

Implements quota and cost center management for enterprise RBAC:
- Resource usage quotas (debates, API calls, storage)
- Cost center tracking for chargeback
- Rate limiting by role/tier
- Usage dashboard data

Usage:
    from aragora.rbac.quotas import QuotaEnforcer, QuotaPolicy

    enforcer = QuotaEnforcer()

    # Set quota policy
    enforcer.set_policy(QuotaPolicy(
        resource_type="debates",
        limit=100,
        period="daily",
        cost_per_unit=0.10,
    ))

    # Check quota before operation
    if await enforcer.check_quota(ctx, "debates"):
        # Allowed - record usage
        await enforcer.record_usage(ctx, "debates", amount=1, cost=0.10)
    else:
        raise QuotaExceededError("Daily debate limit reached")

    # Get usage report
    usage = await enforcer.get_usage(ctx, "debates", period="daily")
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from aragora.exceptions import REDIS_CONNECTION_ERRORS

logger = logging.getLogger(__name__)

# Enable Redis persistence for quota usage via env var
PERSISTENCE_ENABLED = os.environ.get("ARAGORA_QUOTA_PERSISTENCE", "").lower() in (
    "true",
    "1",
    "yes",
)


class QuotaPeriod(str, Enum):
    """Time period for quota limits."""

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    PER_REQUEST = "per_request"  # Single request limit


@dataclass
class QuotaPolicy:
    """Policy defining resource usage limits."""

    resource_type: str
    limit: int
    period: QuotaPeriod
    cost_per_unit: float = 0.0
    cost_center: str | None = None
    hard_limit: bool = True  # If True, block on exceed; if False, warn only
    burst_limit: int | None = None  # Allow short-term burst above limit
    burst_window_seconds: int = 60
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "resource_type": self.resource_type,
            "limit": self.limit,
            "period": self.period.value if isinstance(self.period, QuotaPeriod) else self.period,
            "cost_per_unit": self.cost_per_unit,
            "cost_center": self.cost_center,
            "hard_limit": self.hard_limit,
            "burst_limit": self.burst_limit,
            "burst_window_seconds": self.burst_window_seconds,
            "metadata": self.metadata,
        }


@dataclass
class QuotaUsage:
    """Current usage statistics for a quota."""

    resource_type: str
    period: QuotaPeriod
    limit: int
    used: int
    remaining: int
    cost_incurred: float
    period_start: datetime
    period_end: datetime
    is_exceeded: bool
    percentage_used: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "resource_type": self.resource_type,
            "period": self.period.value if isinstance(self.period, QuotaPeriod) else self.period,
            "limit": self.limit,
            "used": self.used,
            "remaining": self.remaining,
            "cost_incurred": self.cost_incurred,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "is_exceeded": self.is_exceeded,
            "percentage_used": self.percentage_used,
            "metadata": self.metadata,
        }


@dataclass
class UsageRecord:
    """Individual usage record for tracking."""

    user_id: str
    org_id: str | None
    workspace_id: str | None
    resource_type: str
    amount: int
    cost: float
    timestamp: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_storage_dict(self) -> dict[str, Any]:
        """Convert to dictionary for Redis storage."""
        return {
            "user_id": self.user_id,
            "org_id": self.org_id,
            "workspace_id": self.workspace_id,
            "resource_type": self.resource_type,
            "amount": self.amount,
            "cost": self.cost,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_storage_dict(cls, data: dict[str, Any]) -> UsageRecord:
        """Reconstruct from storage dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now(timezone.utc)

        return cls(
            user_id=data.get("user_id", ""),
            org_id=data.get("org_id"),
            workspace_id=data.get("workspace_id"),
            resource_type=data.get("resource_type", ""),
            amount=data.get("amount", 0),
            cost=data.get("cost", 0.0),
            timestamp=timestamp,
            metadata=data.get("metadata", {}),
        )


class QuotaEnforcer:
    """
    Enforces resource quotas and tracks usage.

    Features:
    - Per-user, per-org, per-workspace quotas
    - Multiple time periods (hourly, daily, weekly, monthly)
    - Cost tracking for chargeback
    - Burst allowance for temporary spikes
    - Usage analytics and reporting
    """

    # Default quotas by resource type
    DEFAULT_QUOTAS = {
        "debates": QuotaPolicy("debates", 100, QuotaPeriod.DAILY, cost_per_unit=0.10),
        "api_calls": QuotaPolicy("api_calls", 10000, QuotaPeriod.DAILY, cost_per_unit=0.001),
        "storage_mb": QuotaPolicy("storage_mb", 1000, QuotaPeriod.MONTHLY, cost_per_unit=0.01),
        "agents": QuotaPolicy("agents", 50, QuotaPeriod.MONTHLY, cost_per_unit=0.0),
        "workflows": QuotaPolicy("workflows", 100, QuotaPeriod.DAILY, cost_per_unit=0.05),
        "exports": QuotaPolicy("exports", 50, QuotaPeriod.DAILY, cost_per_unit=0.02),
    }

    def __init__(self, enable_persistence: bool | None = None):
        """Initialize quota enforcer.

        Args:
            enable_persistence: Enable Redis persistence. If None, uses ARAGORA_QUOTA_PERSISTENCE env var.
        """
        self._policies: dict[str, QuotaPolicy] = dict(self.DEFAULT_QUOTAS)
        self._org_policies: dict[str, dict[str, QuotaPolicy]] = {}  # org_id -> policies
        self._usage: dict[str, list[UsageRecord]] = {}  # key -> records

        # Redis persistence
        self._persistence_enabled = (
            enable_persistence if enable_persistence is not None else PERSISTENCE_ENABLED
        )
        self._redis: Any | None = None
        self._redis_checked = False

        if self._persistence_enabled:
            self._load_from_persistence()

    def _get_redis(self) -> Any | None:
        """Get Redis client (lazy initialization)."""
        if self._redis_checked:
            return self._redis

        self._redis_checked = True

        try:
            from aragora.utils.redis_config import get_redis_client

            self._redis = get_redis_client()
            if self._redis:
                logger.info("Quota enforcer using Redis persistence")
        except REDIS_CONNECTION_ERRORS as e:
            logger.warning("Redis not available for quota persistence: %s", e)
            self._redis = None

        return self._redis

    def _usage_redis_key(self, usage_key: str) -> str:
        """Generate Redis key for usage records."""
        return f"aragora:quota:usage:{usage_key}"

    def _persist_usage(self, usage_key: str, record: UsageRecord) -> None:
        """Persist a usage record to Redis."""
        if not self._persistence_enabled:
            return

        redis = self._get_redis()
        if not redis:
            return

        try:
            redis_key = self._usage_redis_key(usage_key)
            record_json = json.dumps(record.to_storage_dict())

            # Use RPUSH to append to list, LTRIM to keep max 10000 records per key
            redis.rpush(redis_key, record_json)
            redis.ltrim(redis_key, -10000, -1)  # Keep last 10000 records

            # Set TTL of 90 days on the key
            redis.expire(redis_key, 90 * 24 * 3600)
        except (OSError, ConnectionError, TimeoutError, TypeError) as e:
            logger.warning("Failed to persist quota usage to Redis: %s", e)

    def _load_from_persistence(self) -> None:
        """Load usage records from Redis on startup."""
        redis = self._get_redis()
        if not redis:
            return

        try:
            # Scan for all quota usage keys
            cursor = 0
            loaded_count = 0

            while True:
                cursor, keys = redis.scan(cursor, match="aragora:quota:usage:*", count=100)

                for redis_key in keys:
                    usage_key = redis_key.decode() if isinstance(redis_key, bytes) else redis_key
                    usage_key = usage_key.replace("aragora:quota:usage:", "")

                    # Load records from Redis list
                    records_json = redis.lrange(self._usage_redis_key(usage_key), 0, -1)

                    if records_json:
                        self._usage[usage_key] = []
                        for record_json in records_json:
                            try:
                                if isinstance(record_json, bytes):
                                    record_json = record_json.decode()
                                data = json.loads(record_json)
                                record = UsageRecord.from_storage_dict(data)
                                self._usage[usage_key].append(record)
                                loaded_count += 1
                            except (ValueError, TypeError, KeyError) as e:
                                logger.warning("Failed to parse quota record: %s", e)

                if cursor == 0:
                    break

            if loaded_count > 0:
                logger.info("Loaded %s quota usage records from Redis", loaded_count)
        except (OSError, ConnectionError, TimeoutError, ValueError) as e:
            logger.warning("Failed to load quota usage from Redis: %s", e)

    def set_policy(
        self,
        policy: QuotaPolicy,
        org_id: str | None = None,
    ) -> None:
        """
        Set a quota policy.

        Args:
            policy: QuotaPolicy to set
            org_id: Organization ID for org-specific policy
        """
        if org_id:
            if org_id not in self._org_policies:
                self._org_policies[org_id] = {}
            self._org_policies[org_id][policy.resource_type] = policy
        else:
            self._policies[policy.resource_type] = policy

        logger.info(
            "Quota policy set: resource=%s, limit=%s/%s, org=%s",
            policy.resource_type,
            policy.limit,
            policy.period.value,
            org_id,
        )

    def get_policy(
        self,
        resource_type: str,
        org_id: str | None = None,
    ) -> QuotaPolicy | None:
        """
        Get quota policy for a resource type.

        Args:
            resource_type: Type of resource
            org_id: Organization ID for org-specific policy

        Returns:
            QuotaPolicy or None if not found
        """
        # Check org-specific first
        if org_id and org_id in self._org_policies:
            policy = self._org_policies[org_id].get(resource_type)
            if policy:
                return policy

        # Fall back to global
        return self._policies.get(resource_type)

    async def check_quota(
        self,
        user_id: str,
        resource_type: str,
        amount: int = 1,
        org_id: str | None = None,
        workspace_id: str | None = None,
    ) -> bool:
        """
        Check if a quota allows the requested usage.

        Args:
            user_id: User requesting usage
            resource_type: Type of resource
            amount: Amount to use
            org_id: Organization context
            workspace_id: Workspace context

        Returns:
            True if usage is allowed
        """
        policy = self.get_policy(resource_type, org_id)
        if not policy:
            return True  # No policy = no limit

        # Get current usage
        current = await self._get_current_usage(
            user_id, resource_type, policy.period, org_id, workspace_id
        )

        # Check against limit
        if current + amount > policy.limit:
            # Check burst allowance
            if policy.burst_limit:
                burst_usage = await self._get_burst_usage(
                    user_id, resource_type, policy.burst_window_seconds, org_id
                )
                if burst_usage + amount <= policy.burst_limit:
                    return True

            # Hard limit or soft limit?
            if policy.hard_limit:
                logger.warning(
                    "Quota exceeded: user=%s, resource=%s, current=%s, limit=%s",
                    user_id,
                    resource_type,
                    current,
                    policy.limit,
                )
                return False
            else:
                logger.info(
                    "Quota soft limit exceeded: user=%s, resource=%s", user_id, resource_type
                )
                return True  # Allow but warn

        return True

    async def record_usage(
        self,
        user_id: str,
        resource_type: str,
        amount: int = 1,
        cost: float | None = None,
        org_id: str | None = None,
        workspace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UsageRecord:
        """
        Record resource usage.

        Args:
            user_id: User using the resource
            resource_type: Type of resource
            amount: Amount used
            cost: Cost incurred (if None, calculated from policy)
            org_id: Organization context
            workspace_id: Workspace context
            metadata: Additional metadata

        Returns:
            UsageRecord created
        """
        # Get policy for cost calculation
        policy = self.get_policy(resource_type, org_id)
        if cost is None and policy:
            cost = amount * policy.cost_per_unit
        cost = cost or 0.0

        record = UsageRecord(
            user_id=user_id,
            org_id=org_id,
            workspace_id=workspace_id,
            resource_type=resource_type,
            amount=amount,
            cost=cost,
            timestamp=datetime.now(timezone.utc),
            metadata=metadata or {},
        )

        # Store record
        key = self._usage_key(user_id, resource_type, org_id, workspace_id)
        if key not in self._usage:
            self._usage[key] = []
        self._usage[key].append(record)

        # Persist to Redis
        self._persist_usage(key, record)

        logger.debug(
            "Usage recorded: user=%s, resource=%s, amount=%s, cost=%s",
            user_id,
            resource_type,
            amount,
            cost,
        )

        return record

    async def get_usage(
        self,
        user_id: str,
        resource_type: str,
        period: QuotaPeriod | None = None,
        org_id: str | None = None,
        workspace_id: str | None = None,
    ) -> QuotaUsage:
        """
        Get usage statistics for a resource.

        Args:
            user_id: User to check
            resource_type: Type of resource
            period: Time period (uses policy default if not specified)
            org_id: Organization context
            workspace_id: Workspace context

        Returns:
            QuotaUsage with current statistics
        """
        policy = self.get_policy(resource_type, org_id)
        if period is None:
            period = policy.period if policy else QuotaPeriod.DAILY

        limit = policy.limit if policy else 0
        period_start, period_end = self._get_period_bounds(period)

        # Calculate usage
        used = await self._get_current_usage(user_id, resource_type, period, org_id, workspace_id)

        # Calculate cost
        cost = await self._get_cost_for_period(user_id, resource_type, period, org_id, workspace_id)

        remaining = max(0, limit - used)
        is_exceeded = used >= limit if limit > 0 else False
        percentage = (used / limit * 100) if limit > 0 else 0

        return QuotaUsage(
            resource_type=resource_type,
            period=period,
            limit=limit,
            used=used,
            remaining=remaining,
            cost_incurred=cost,
            period_start=period_start,
            period_end=period_end,
            is_exceeded=is_exceeded,
            percentage_used=percentage,
        )

    async def get_all_usage(
        self,
        user_id: str,
        org_id: str | None = None,
        workspace_id: str | None = None,
    ) -> dict[str, QuotaUsage]:
        """
        Get usage for all tracked resources.

        Args:
            user_id: User to check
            org_id: Organization context
            workspace_id: Workspace context

        Returns:
            Dict mapping resource_type to QuotaUsage
        """
        result = {}

        # Get all resource types with policies
        resource_types = set(self._policies.keys())
        if org_id and org_id in self._org_policies:
            resource_types.update(self._org_policies[org_id].keys())

        for resource_type in resource_types:
            result[resource_type] = await self.get_usage(
                user_id, resource_type, org_id=org_id, workspace_id=workspace_id
            )

        return result

    async def get_cost_report(
        self,
        org_id: str,
        period: QuotaPeriod = QuotaPeriod.MONTHLY,
        cost_center: str | None = None,
    ) -> dict[str, Any]:
        """
        Get cost report for an organization.

        Args:
            org_id: Organization ID
            period: Reporting period
            cost_center: Filter by cost center

        Returns:
            Cost report with breakdown
        """
        period_start, period_end = self._get_period_bounds(period)
        total_cost = 0.0
        by_resource: dict[str, float] = {}
        by_user: dict[str, float] = {}

        # Aggregate costs from all usage records
        for key, records in self._usage.items():
            for record in records:
                if record.org_id != org_id:
                    continue
                if record.timestamp < period_start or record.timestamp > period_end:
                    continue

                # Check cost center filter
                if cost_center:
                    policy = self.get_policy(record.resource_type, org_id)
                    if policy and policy.cost_center != cost_center:
                        continue

                total_cost += record.cost

                if record.resource_type not in by_resource:
                    by_resource[record.resource_type] = 0.0
                by_resource[record.resource_type] += record.cost

                if record.user_id not in by_user:
                    by_user[record.user_id] = 0.0
                by_user[record.user_id] += record.cost

        return {
            "org_id": org_id,
            "period": period.value,
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "cost_center": cost_center,
            "total_cost": total_cost,
            "by_resource": by_resource,
            "by_user": by_user,
            "top_users": sorted(by_user.items(), key=lambda x: x[1], reverse=True)[:10],
        }

    async def cleanup_old_records(self, days: int = 90) -> int:
        """
        Clean up usage records older than specified days.

        Args:
            days: Records older than this are removed

        Returns:
            Number of records removed
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = 0

        for key in list(self._usage.keys()):
            original_len = len(self._usage[key])
            self._usage[key] = [r for r in self._usage[key] if r.timestamp >= cutoff]
            count += original_len - len(self._usage[key])

            if not self._usage[key]:
                del self._usage[key]

        if count > 0:
            logger.info("Cleaned up %s old usage records", count)

        return count

    def _usage_key(
        self,
        user_id: str,
        resource_type: str,
        org_id: str | None,
        workspace_id: str | None,
    ) -> str:
        """Generate storage key for usage records."""
        parts = [user_id, resource_type]
        if org_id:
            parts.append(f"org:{org_id}")
        if workspace_id:
            parts.append(f"ws:{workspace_id}")
        return ":".join(parts)

    async def _get_current_usage(
        self,
        user_id: str,
        resource_type: str,
        period: QuotaPeriod,
        org_id: str | None,
        workspace_id: str | None,
    ) -> int:
        """Get current usage for a period."""
        period_start, _ = self._get_period_bounds(period)
        key = self._usage_key(user_id, resource_type, org_id, workspace_id)
        records = self._usage.get(key, [])

        total = sum(r.amount for r in records if r.timestamp >= period_start)
        return total

    async def _get_burst_usage(
        self,
        user_id: str,
        resource_type: str,
        window_seconds: int,
        org_id: str | None,
    ) -> int:
        """Get usage in burst window."""
        window_start = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        key = self._usage_key(user_id, resource_type, org_id, None)
        records = self._usage.get(key, [])

        total = sum(r.amount for r in records if r.timestamp >= window_start)
        return total

    async def _get_cost_for_period(
        self,
        user_id: str,
        resource_type: str,
        period: QuotaPeriod,
        org_id: str | None,
        workspace_id: str | None,
    ) -> float:
        """Get total cost for a period."""
        period_start, _ = self._get_period_bounds(period)
        key = self._usage_key(user_id, resource_type, org_id, workspace_id)
        records = self._usage.get(key, [])

        total = sum(r.cost for r in records if r.timestamp >= period_start)
        return total

    def _get_period_bounds(
        self,
        period: QuotaPeriod,
    ) -> tuple[datetime, datetime]:
        """Get start and end times for a period."""
        now = datetime.now(timezone.utc)

        if period == QuotaPeriod.HOURLY:
            start = now.replace(minute=0, second=0, microsecond=0)
            end = start + timedelta(hours=1)
        elif period == QuotaPeriod.DAILY:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif period == QuotaPeriod.WEEKLY:
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(weeks=1)
        elif period == QuotaPeriod.MONTHLY:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            # Next month
            if now.month == 12:
                end = start.replace(year=now.year + 1, month=1)
            else:
                end = start.replace(month=now.month + 1)
        else:  # PER_REQUEST
            start = now
            end = now

        return start, end


# Decorator for quota enforcement
def require_quota(resource_type: str, amount: int = 1):
    """
    Decorator to enforce quota on a function.

    Usage:
        @require_quota("debates", amount=1)
        async def create_debate(ctx, ...):
            ...
    """

    def decorator(func):
        async def wrapper(*args, **kwargs):
            # Extract context from args
            ctx = kwargs.get("ctx") or (args[0] if args else None)
            if not ctx:
                return await func(*args, **kwargs)

            user_id = getattr(ctx, "user_id", None)
            org_id = getattr(ctx, "org_id", None)
            workspace_id = getattr(ctx, "workspace_id", None)

            if not user_id:
                return await func(*args, **kwargs)

            enforcer = get_quota_enforcer()
            if not await enforcer.check_quota(user_id, resource_type, amount, org_id, workspace_id):
                raise QuotaExceededError(f"Quota exceeded for {resource_type}")

            result = await func(*args, **kwargs)

            # Record usage on success
            await enforcer.record_usage(
                user_id, resource_type, amount, org_id=org_id, workspace_id=workspace_id
            )

            return result

        return wrapper

    return decorator


class QuotaExceededError(Exception):
    """Raised when a quota limit is exceeded."""

    def __init__(self, message: str, resource_type: str = "", limit: int = 0):
        super().__init__(message)
        self.resource_type = resource_type
        self.limit = limit


# Singleton instance
_enforcer: QuotaEnforcer | None = None


def get_quota_enforcer() -> QuotaEnforcer:
    """Get the global QuotaEnforcer instance."""
    global _enforcer
    if _enforcer is None:
        _enforcer = QuotaEnforcer()
    return _enforcer


__all__ = [
    "QuotaPeriod",
    "QuotaPolicy",
    "QuotaUsage",
    "UsageRecord",
    "QuotaEnforcer",
    "QuotaExceededError",
    "require_quota",
    "get_quota_enforcer",
]
