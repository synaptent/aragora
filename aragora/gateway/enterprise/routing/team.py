"""
Team Tenant Routing Handler.

Provides specialized routing logic for team tenants with features:
- Shared resource pools
- Team-level quotas
- Member-aware routing
- Workspace isolation
- Collaborative features

Usage:
    from aragora.gateway.enterprise.routing.team import (
        TeamTenantHandler,
        TeamRoutingConfig,
        TeamMember,
    )

    handler = TeamTenantHandler()
    config = TeamRoutingConfig(
        tenant_id="team-alpha",
        team_name="Alpha Team",
        max_members=50,
    )
    endpoint = await handler.select_endpoint(config, available_endpoints)
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .quotas import TenantQuotas

logger = logging.getLogger(__name__)


# =============================================================================
# Enums
# =============================================================================


class TeamPlan(str, Enum):
    """Team subscription plan levels."""

    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    BUSINESS = "business"


class MemberRole(str, Enum):
    """Roles within a team."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
    GUEST = "guest"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class TeamMember:
    """
    Team member configuration.

    Attributes:
        user_id: Unique user identifier.
        role: Role within the team.
        quota_allocation: Percentage of team quota allocated to this member.
        is_active: Whether the member is active.
        joined_at: When the member joined.
    """

    user_id: str
    role: MemberRole = MemberRole.MEMBER
    quota_allocation: float = 0.0  # 0 means equal share
    is_active: bool = True
    joined_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TeamRoutingConfig:
    """
    Routing configuration for team tenants.

    Attributes:
        tenant_id: Unique tenant identifier.
        team_name: Human-readable team name.
        plan: Team subscription plan.
        max_members: Maximum allowed team members.
        members: List of team members.
        shared_quota: Whether quota is shared across all members.
        workspace_id: Associated workspace identifier.
        priority_members: Set of member IDs with priority routing.
        fallback_enabled: Whether automatic failover is enabled.
        metadata: Additional configuration metadata.
    """

    tenant_id: str
    team_name: str = ""
    plan: TeamPlan = TeamPlan.FREE
    max_members: int = 5
    members: list[TeamMember] = field(default_factory=list)
    shared_quota: bool = True
    workspace_id: str | None = None
    priority_members: set[str] = field(default_factory=set)
    fallback_enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_plan_multiplier(self) -> float:
        """Get quota multiplier based on team plan."""
        multipliers = {
            TeamPlan.FREE: 1.0,
            TeamPlan.STARTER: 2.0,
            TeamPlan.PROFESSIONAL: 5.0,
            TeamPlan.BUSINESS: 10.0,
        }
        return multipliers.get(self.plan, 1.0)

    def get_active_member_count(self) -> int:
        """Get count of active team members."""
        return sum(1 for m in self.members if m.is_active)


@dataclass
class TeamEndpoint:
    """
    Endpoint configuration for team routing.

    Attributes:
        url: Base URL of the endpoint.
        capacity: Maximum concurrent requests this endpoint can handle.
        current_load: Current number of active requests.
        supports_collaboration: Whether endpoint supports real-time collaboration.
        priority: Priority for failover (lower = higher priority).
        weight: Weight for load balancing.
    """

    url: str
    capacity: int = 50
    current_load: int = 0
    supports_collaboration: bool = False
    priority: int = 1
    weight: int = 100

    @property
    def available_capacity(self) -> int:
        """Get available capacity."""
        return max(0, self.capacity - self.current_load)

    @property
    def load_percentage(self) -> float:
        """Get current load as a percentage."""
        if self.capacity == 0:
            return 100.0
        return (self.current_load / self.capacity) * 100


@dataclass
class TeamRoutingDecision:
    """
    Routing decision for team tenants.

    Attributes:
        selected_endpoint: The selected endpoint URL.
        plan: Team plan used for selection.
        member_id: Member ID that triggered the request.
        is_priority_member: Whether the member has priority routing.
        decision_reason: Human-readable reason for the decision.
        fallback_used: Whether a fallback was used.
        metadata: Additional decision metadata.
    """

    selected_endpoint: str
    plan: TeamPlan
    member_id: str | None = None
    is_priority_member: bool = False
    decision_reason: str = ""
    fallback_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Team Tenant Handler
# =============================================================================


class TeamTenantHandler:
    """
    Handler for team tenant routing decisions.

    Implements routing logic for team tenants with shared resources,
    member awareness, and collaborative features.
    """

    def __init__(self) -> None:
        """Initialize team tenant handler."""
        self._plan_quotas = {
            TeamPlan.FREE: TenantQuotas(
                requests_per_minute=30,
                requests_per_hour=500,
                requests_per_day=5000,
                concurrent_requests=5,
            ),
            TeamPlan.STARTER: TenantQuotas(
                requests_per_minute=60,
                requests_per_hour=1000,
                requests_per_day=10000,
                concurrent_requests=10,
            ),
            TeamPlan.PROFESSIONAL: TenantQuotas(
                requests_per_minute=150,
                requests_per_hour=2500,
                requests_per_day=25000,
                concurrent_requests=25,
            ),
            TeamPlan.BUSINESS: TenantQuotas(
                requests_per_minute=300,
                requests_per_hour=5000,
                requests_per_day=50000,
                concurrent_requests=50,
            ),
        }

    def get_team_quotas(
        self,
        config: TeamRoutingConfig,
        base_quotas: TenantQuotas | None = None,
    ) -> TenantQuotas:
        """
        Get quotas for a team based on plan.

        Args:
            config: Team routing configuration.
            base_quotas: Optional base quotas to use instead of plan defaults.

        Returns:
            TenantQuotas for the team.
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
            self._plan_quotas[TeamPlan.FREE],
        )

    def get_member_quota_share(
        self,
        config: TeamRoutingConfig,
        member_id: str,
    ) -> float:
        """
        Get the quota share for a specific team member.

        Args:
            config: Team routing configuration.
            member_id: Member identifier.

        Returns:
            Quota share as a fraction (0.0 to 1.0).
        """
        if not config.shared_quota:
            # Individual quotas - each member gets full allocation
            return 1.0

        member = next((m for m in config.members if m.user_id == member_id), None)
        if member is None:
            # Unknown member gets minimal share
            return 0.1

        if member.quota_allocation > 0:
            return member.quota_allocation

        # Equal share among active members
        active_count = config.get_active_member_count()
        if active_count == 0:
            return 1.0

        return 1.0 / active_count

    def is_priority_member(
        self,
        config: TeamRoutingConfig,
        member_id: str,
    ) -> bool:
        """
        Check if a member has priority routing.

        Args:
            config: Team routing configuration.
            member_id: Member identifier.

        Returns:
            True if member has priority routing.
        """
        if member_id in config.priority_members:
            return True

        # Owners and admins always have priority
        member = next((m for m in config.members if m.user_id == member_id), None)
        if member and member.role in (MemberRole.OWNER, MemberRole.ADMIN):
            return True

        return False

    def filter_by_capacity(
        self,
        endpoints: list[TeamEndpoint],
        min_available: int = 1,
    ) -> list[TeamEndpoint]:
        """
        Filter endpoints with sufficient available capacity.

        Args:
            endpoints: List of available endpoints.
            min_available: Minimum available capacity required.

        Returns:
            Endpoints with sufficient capacity.
        """
        return [e for e in endpoints if e.available_capacity >= min_available]

    def filter_collaborative(
        self,
        endpoints: list[TeamEndpoint],
        require_collaboration: bool = False,
    ) -> list[TeamEndpoint]:
        """
        Filter endpoints by collaboration support.

        Args:
            endpoints: List of available endpoints.
            require_collaboration: Whether collaboration support is required.

        Returns:
            Filtered endpoints.
        """
        if not require_collaboration:
            return endpoints

        collaborative = [e for e in endpoints if e.supports_collaboration]
        return collaborative if collaborative else endpoints

    def select_least_loaded(
        self,
        endpoints: list[TeamEndpoint],
    ) -> TeamEndpoint | None:
        """
        Select the least loaded endpoint.

        Args:
            endpoints: List of available endpoints.

        Returns:
            Least loaded endpoint or None.
        """
        if not endpoints:
            return None

        return min(endpoints, key=lambda e: e.load_percentage)

    def select_weighted_random(
        self,
        endpoints: list[TeamEndpoint],
    ) -> TeamEndpoint | None:
        """
        Select an endpoint using weighted random selection.

        Args:
            endpoints: List of available endpoints.

        Returns:
            Randomly selected endpoint based on weights.
        """
        if not endpoints:
            return None

        # Weight by both configured weight and available capacity
        weights = []
        for e in endpoints:
            capacity_factor = e.available_capacity / max(e.capacity, 1)
            weights.append(e.weight * capacity_factor)

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
        config: TeamRoutingConfig,
        endpoints: list[TeamEndpoint],
        member_id: str | None = None,
        require_collaboration: bool = False,
    ) -> TeamRoutingDecision:
        """
        Select the best endpoint for a team tenant.

        Args:
            config: Team routing configuration.
            endpoints: List of available endpoints.
            member_id: Optional member ID making the request.
            require_collaboration: Whether collaboration support is required.

        Returns:
            TeamRoutingDecision with the selected endpoint.
        """
        if not endpoints:
            return TeamRoutingDecision(
                selected_endpoint="",
                plan=config.plan,
                member_id=member_id,
                decision_reason="No endpoints available",
            )

        is_priority = False
        if member_id:
            is_priority = self.is_priority_member(config, member_id)

        # Filter by collaboration requirements
        available = self.filter_collaborative(endpoints, require_collaboration)

        # Filter by capacity
        min_capacity = 2 if is_priority else 1
        available = self.filter_by_capacity(available, min_capacity)

        if not available:
            # Fallback to any endpoint
            available = endpoints

        # Selection strategy based on plan
        if config.plan == TeamPlan.BUSINESS:
            # Business plans use least-loaded for optimal performance
            selected = self.select_least_loaded(available)
        else:
            # Other plans use weighted random
            selected = self.select_weighted_random(available)

        if selected:
            return TeamRoutingDecision(
                selected_endpoint=selected.url,
                plan=config.plan,
                member_id=member_id,
                is_priority_member=is_priority,
                decision_reason=self._build_decision_reason(
                    config, selected, is_priority, require_collaboration
                ),
                metadata={
                    "load_percentage": selected.load_percentage,
                    "supports_collaboration": selected.supports_collaboration,
                },
            )

        # Final fallback
        fallback = endpoints[0]
        return TeamRoutingDecision(
            selected_endpoint=fallback.url,
            plan=config.plan,
            member_id=member_id,
            decision_reason="Fallback endpoint selected",
            fallback_used=True,
        )

    def _build_decision_reason(
        self,
        config: TeamRoutingConfig,
        endpoint: TeamEndpoint,
        is_priority: bool,
        require_collaboration: bool,
    ) -> str:
        """Build a human-readable decision reason."""
        reasons = []

        reasons.append(f"plan={config.plan.value}")
        if is_priority:
            reasons.append("priority_member")
        if require_collaboration and endpoint.supports_collaboration:
            reasons.append("collaborative")
        reasons.append(f"load={endpoint.load_percentage:.0f}%")

        return "Selected: " + ", ".join(reasons)

    def validate_member_access(
        self,
        config: TeamRoutingConfig,
        member_id: str,
    ) -> dict[str, Any]:
        """
        Validate that a member has access to the team.

        Args:
            config: Team routing configuration.
            member_id: Member identifier.

        Returns:
            Dictionary with access validation result.
        """
        member = next((m for m in config.members if m.user_id == member_id), None)

        if member is None:
            return {
                "has_access": False,
                "reason": "Member not found in team",
                "member_id": member_id,
                "team_id": config.tenant_id,
            }

        if not member.is_active:
            return {
                "has_access": False,
                "reason": "Member is inactive",
                "member_id": member_id,
                "team_id": config.tenant_id,
            }

        return {
            "has_access": True,
            "role": member.role.value,
            "member_id": member_id,
            "team_id": config.tenant_id,
            "joined_at": member.joined_at.isoformat(),
        }


__all__ = [
    "TeamPlan",
    "MemberRole",
    "TeamMember",
    "TeamRoutingConfig",
    "TeamEndpoint",
    "TeamRoutingDecision",
    "TeamTenantHandler",
]
