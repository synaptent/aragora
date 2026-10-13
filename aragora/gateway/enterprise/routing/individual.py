"""
Individual Tenant Routing Handler.

Provides specialized routing logic for individual/personal tenants with features:
- Personal quotas
- Usage-based throttling
- Simple endpoint selection
- Trial/subscription management
- Personal workspace isolation

Usage:
    from aragora.gateway.enterprise.routing.individual import (
        IndividualTenantHandler,
        IndividualRoutingConfig,
    )

    handler = IndividualTenantHandler()
    config = IndividualRoutingConfig(
        tenant_id="user-12345",
        user_id="user-12345",
        plan=IndividualPlan.PRO,
    )
    endpoint = await handler.select_endpoint(config, available_endpoints)
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from .quotas import TenantQuotas

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class IndividualPlan(str, Enum):
    """Individual subscription plan levels."""

    FREE = "free"
    TRIAL = "trial"
    PRO = "pro"
    PREMIUM = "premium"


class AccountStatus(str, Enum):
    """Account status for individual tenants."""

    ACTIVE = "active"
    TRIAL = "trial"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class IndividualRoutingConfig:
    """
    Routing configuration for individual tenants.

    Attributes:
        tenant_id: Unique tenant identifier.
        user_id: Associated user identifier.
        plan: Individual subscription plan.
        status: Current account status.
        trial_ends_at: When trial period ends (if applicable).
        usage_this_month: Current month's usage count.
        monthly_limit: Monthly usage limit.
        rate_limit_until: Rate limit expiry time (if throttled).
        preferred_region: Preferred geographic region.
        metadata: Additional configuration metadata.
    """

    tenant_id: str
    user_id: str
    plan: IndividualPlan = IndividualPlan.FREE
    status: AccountStatus = AccountStatus.ACTIVE
    trial_ends_at: datetime | None = None
    usage_this_month: int = 0
    monthly_limit: int = 1000
    rate_limit_until: datetime | None = None
    preferred_region: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_trial_expired(self) -> bool:
        """Check if trial has expired."""
        if self.trial_ends_at is None:
            return False
        return datetime.now(timezone.utc) > self.trial_ends_at

    def is_rate_limited(self) -> bool:
        """Check if currently rate limited."""
        if self.rate_limit_until is None:
            return False
        return datetime.now(timezone.utc) < self.rate_limit_until

    def is_at_monthly_limit(self) -> bool:
        """Check if monthly limit is reached."""
        return self.usage_this_month >= self.monthly_limit

    def get_plan_multiplier(self) -> float:
        """Get quota multiplier based on plan."""
        multipliers = {
            IndividualPlan.FREE: 1.0,
            IndividualPlan.TRIAL: 2.0,
            IndividualPlan.PRO: 5.0,
            IndividualPlan.PREMIUM: 10.0,
        }
        return multipliers.get(self.plan, 1.0)


@dataclass
class IndividualEndpoint:
    """
    Endpoint configuration for individual routing.

    Attributes:
        url: Base URL of the endpoint.
        region: Geographic region of the endpoint.
        is_free_tier: Whether this endpoint supports free tier users.
        priority: Priority for selection (lower = higher priority).
        weight: Weight for load balancing.
        current_users: Current number of active users on this endpoint.
        max_users: Maximum users this endpoint can handle.
    """

    url: str
    region: str = "us-east-1"
    is_free_tier: bool = True
    priority: int = 1
    weight: int = 100
    current_users: int = 0
    max_users: int = 1000

    @property
    def available_slots(self) -> int:
        """Get available user slots."""
        return max(0, self.max_users - self.current_users)

    @property
    def utilization(self) -> float:
        """Get current utilization percentage."""
        if self.max_users == 0:
            return 100.0
        return (self.current_users / self.max_users) * 100


@dataclass
class IndividualRoutingDecision:
    """
    Routing decision for individual tenants.

    Attributes:
        selected_endpoint: The selected endpoint URL.
        plan: Individual plan used for selection.
        is_throttled: Whether the request is being throttled.
        throttle_reason: Reason for throttling (if applicable).
        decision_reason: Human-readable reason for the decision.
        retry_after: Seconds until retry is allowed (if throttled).
        metadata: Additional decision metadata.
    """

    selected_endpoint: str
    plan: IndividualPlan
    is_throttled: bool = False
    throttle_reason: str | None = None
    decision_reason: str = ""
    retry_after: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Individual Tenant Handler
# =============================================================================


class IndividualTenantHandler:
    """
    Handler for individual tenant routing decisions.

    Implements routing logic for individual/personal tenants with
    simple selection, throttling, and trial management.
    """

    def __init__(self) -> None:
        """Initialize individual tenant handler."""
        self._plan_quotas = {
            IndividualPlan.FREE: TenantQuotas(
                requests_per_minute=10,
                requests_per_hour=100,
                requests_per_day=500,
                concurrent_requests=2,
            ),
            IndividualPlan.TRIAL: TenantQuotas(
                requests_per_minute=30,
                requests_per_hour=300,
                requests_per_day=1500,
                concurrent_requests=5,
            ),
            IndividualPlan.PRO: TenantQuotas(
                requests_per_minute=60,
                requests_per_hour=1000,
                requests_per_day=5000,
                concurrent_requests=10,
            ),
            IndividualPlan.PREMIUM: TenantQuotas(
                requests_per_minute=120,
                requests_per_hour=2000,
                requests_per_day=10000,
                concurrent_requests=20,
            ),
        }

        self._plan_monthly_limits = {
            IndividualPlan.FREE: 1000,
            IndividualPlan.TRIAL: 5000,
            IndividualPlan.PRO: 50000,
            IndividualPlan.PREMIUM: 200000,
        }

    def get_individual_quotas(
        self,
        config: IndividualRoutingConfig,
        base_quotas: TenantQuotas | None = None,
    ) -> TenantQuotas:
        """
        Get quotas for an individual based on plan.

        Args:
            config: Individual routing configuration.
            base_quotas: Optional base quotas to use instead of plan defaults.

        Returns:
            TenantQuotas for the individual.
        """
        if base_quotas:
            multiplier = config.get_plan_multiplier()
            return TenantQuotas(
                requests_per_minute=int(base_quotas.requests_per_minute * multiplier),
                requests_per_hour=int(base_quotas.requests_per_hour * multiplier),
                requests_per_day=int(base_quotas.requests_per_day * multiplier),
                concurrent_requests=int(base_quotas.concurrent_requests * multiplier),
                bandwidth_bytes_per_minute=int(base_quotas.bandwidth_bytes_per_minute * multiplier),
                warn_threshold=base_quotas.warn_threshold,
            )

        return self._plan_quotas.get(
            config.plan,
            self._plan_quotas[IndividualPlan.FREE],
        )

    def get_monthly_limit(self, plan: IndividualPlan) -> int:
        """
        Get monthly usage limit for a plan.

        Args:
            plan: Individual subscription plan.

        Returns:
            Monthly usage limit.
        """
        return self._plan_monthly_limits.get(plan, 1000)

    def check_access(
        self,
        config: IndividualRoutingConfig,
    ) -> dict[str, Any]:
        """
        Check if the individual has access to the service.

        Args:
            config: Individual routing configuration.

        Returns:
            Dictionary with access status and details.
        """
        # Check account status
        if config.status == AccountStatus.SUSPENDED:
            return {
                "has_access": False,
                "reason": "Account suspended",
                "status": config.status.value,
            }

        if config.status == AccountStatus.CANCELLED:
            return {
                "has_access": False,
                "reason": "Subscription cancelled",
                "status": config.status.value,
            }

        if config.status == AccountStatus.EXPIRED:
            return {
                "has_access": False,
                "reason": "Subscription expired",
                "status": config.status.value,
            }

        # Check trial expiry
        if config.plan == IndividualPlan.TRIAL and config.is_trial_expired():
            return {
                "has_access": False,
                "reason": "Trial period expired",
                "trial_ended_at": config.trial_ends_at.isoformat()
                if config.trial_ends_at
                else None,
            }

        # Check rate limiting
        if config.is_rate_limited():
            seconds_remaining = (
                int((config.rate_limit_until - datetime.now(timezone.utc)).total_seconds())
                if config.rate_limit_until
                else 0
            )
            return {
                "has_access": False,
                "reason": "Rate limited",
                "retry_after": max(0, seconds_remaining),
            }

        # Check monthly limit
        if config.is_at_monthly_limit():
            return {
                "has_access": False,
                "reason": "Monthly limit reached",
                "usage": config.usage_this_month,
                "limit": config.monthly_limit,
            }

        return {
            "has_access": True,
            "plan": config.plan.value,
            "status": config.status.value,
            "usage_remaining": config.monthly_limit - config.usage_this_month,
        }

    def filter_by_tier(
        self,
        endpoints: list[IndividualEndpoint],
        is_free_tier: bool,
    ) -> list[IndividualEndpoint]:
        """
        Filter endpoints by tier support.

        Args:
            endpoints: List of available endpoints.
            is_free_tier: Whether user is on free tier.

        Returns:
            Filtered endpoints.
        """
        if is_free_tier:
            # Free tier users can only use free-tier endpoints
            free_endpoints = [e for e in endpoints if e.is_free_tier]
            return free_endpoints if free_endpoints else endpoints

        # Paid users can use any endpoint
        return endpoints

    def filter_by_region(
        self,
        endpoints: list[IndividualEndpoint],
        preferred_region: str | None,
    ) -> list[IndividualEndpoint]:
        """
        Sort endpoints by regional preference.

        Args:
            endpoints: List of available endpoints.
            preferred_region: Preferred geographic region.

        Returns:
            Endpoints sorted by regional preference.
        """
        if not preferred_region:
            return endpoints

        in_region = [e for e in endpoints if e.region == preferred_region]
        out_of_region = [e for e in endpoints if e.region != preferred_region]

        return in_region + out_of_region

    def filter_by_availability(
        self,
        endpoints: list[IndividualEndpoint],
        min_slots: int = 1,
    ) -> list[IndividualEndpoint]:
        """
        Filter endpoints with available slots.

        Args:
            endpoints: List of available endpoints.
            min_slots: Minimum available slots required.

        Returns:
            Endpoints with sufficient availability.
        """
        return [e for e in endpoints if e.available_slots >= min_slots]

    def select_by_utilization(
        self,
        endpoints: list[IndividualEndpoint],
    ) -> IndividualEndpoint | None:
        """
        Select the least utilized endpoint.

        Args:
            endpoints: List of available endpoints.

        Returns:
            Least utilized endpoint or None.
        """
        if not endpoints:
            return None

        return min(endpoints, key=lambda e: e.utilization)

    def select_weighted_random(
        self,
        endpoints: list[IndividualEndpoint],
    ) -> IndividualEndpoint | None:
        """
        Select an endpoint using weighted random selection.

        Args:
            endpoints: List of available endpoints.

        Returns:
            Randomly selected endpoint based on weights.
        """
        if not endpoints:
            return None

        weights = [e.weight * (e.available_slots / max(e.max_users, 1)) for e in endpoints]
        total_weight = sum(weights)

        if total_weight == 0:
            return random.choice(endpoints)

        r = random.uniform(0, total_weight)
        cumulative = 0.0
        for i, endpoint in enumerate(endpoints):
            cumulative += weights[i]
            if r <= cumulative:
                return endpoint

        return endpoints[-1]

    async def select_endpoint(
        self,
        config: IndividualRoutingConfig,
        endpoints: list[IndividualEndpoint],
    ) -> IndividualRoutingDecision:
        """
        Select the best endpoint for an individual tenant.

        Args:
            config: Individual routing configuration.
            endpoints: List of available endpoints.

        Returns:
            IndividualRoutingDecision with the selected endpoint.
        """
        # Check access first
        access = self.check_access(config)
        if not access["has_access"]:
            return IndividualRoutingDecision(
                selected_endpoint="",
                plan=config.plan,
                is_throttled=True,
                throttle_reason=access.get("reason", "Access denied"),
                decision_reason=access.get("reason", "Access denied"),
                retry_after=access.get("retry_after"),
            )

        if not endpoints:
            return IndividualRoutingDecision(
                selected_endpoint="",
                plan=config.plan,
                decision_reason="No endpoints available",
            )

        is_free = config.plan == IndividualPlan.FREE

        # Filter by tier
        available = self.filter_by_tier(endpoints, is_free)

        # Filter by region
        available = self.filter_by_region(available, config.preferred_region)

        # Filter by availability
        available = self.filter_by_availability(available)

        if not available:
            # Fallback to any endpoint
            available = endpoints

        # Selection strategy based on plan
        if config.plan in (IndividualPlan.PRO, IndividualPlan.PREMIUM):
            # Paid plans use least-utilized for better performance
            selected = self.select_by_utilization(available)
        else:
            # Free/trial plans use weighted random
            selected = self.select_weighted_random(available)

        if selected:
            return IndividualRoutingDecision(
                selected_endpoint=selected.url,
                plan=config.plan,
                decision_reason=self._build_decision_reason(config, selected),
                metadata={
                    "region": selected.region,
                    "utilization": selected.utilization,
                },
            )

        # Final fallback
        fallback = endpoints[0]
        return IndividualRoutingDecision(
            selected_endpoint=fallback.url,
            plan=config.plan,
            decision_reason="Fallback endpoint selected",
        )

    def _build_decision_reason(
        self,
        config: IndividualRoutingConfig,
        endpoint: IndividualEndpoint,
    ) -> str:
        """Build a human-readable decision reason."""
        reasons = []

        reasons.append(f"plan={config.plan.value}")
        if config.preferred_region and endpoint.region == config.preferred_region:
            reasons.append(f"region={endpoint.region}")
        reasons.append(f"utilization={endpoint.utilization:.0f}%")

        return "Selected: " + ", ".join(reasons)

    def calculate_rate_limit_duration(
        self,
        config: IndividualRoutingConfig,
        violation_count: int = 1,
    ) -> timedelta:
        """
        Calculate rate limit duration based on plan and violations.

        Args:
            config: Individual routing configuration.
            violation_count: Number of rate limit violations.

        Returns:
            Duration of rate limit.
        """
        # Base duration in seconds by plan
        base_durations = {
            IndividualPlan.FREE: 300,  # 5 minutes
            IndividualPlan.TRIAL: 180,  # 3 minutes
            IndividualPlan.PRO: 60,  # 1 minute
            IndividualPlan.PREMIUM: 30,  # 30 seconds
        }

        base = base_durations.get(config.plan, 300)

        # Exponential backoff for repeated violations (capped at 1 hour)
        duration_seconds = min(base * (2 ** (violation_count - 1)), 3600)

        return timedelta(seconds=duration_seconds)

    def get_upgrade_recommendation(
        self,
        config: IndividualRoutingConfig,
    ) -> dict[str, Any] | None:
        """
        Get upgrade recommendation if user is near limits.

        Args:
            config: Individual routing configuration.

        Returns:
            Upgrade recommendation or None.
        """
        usage_percentage = (config.usage_this_month / config.monthly_limit) * 100

        if usage_percentage < 80:
            return None

        next_plan = {
            IndividualPlan.FREE: IndividualPlan.PRO,
            IndividualPlan.TRIAL: IndividualPlan.PRO,
            IndividualPlan.PRO: IndividualPlan.PREMIUM,
        }.get(config.plan)

        if next_plan is None:
            return None

        return {
            "current_plan": config.plan.value,
            "recommended_plan": next_plan.value,
            "current_usage_percentage": usage_percentage,
            "current_limit": config.monthly_limit,
            "recommended_limit": self.get_monthly_limit(next_plan),
            "reason": f"You've used {usage_percentage:.0f}% of your monthly limit",
        }


__all__ = [
    "IndividualPlan",
    "AccountStatus",
    "IndividualRoutingConfig",
    "IndividualEndpoint",
    "IndividualRoutingDecision",
    "IndividualTenantHandler",
]
