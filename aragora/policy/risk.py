"""
Risk levels, blast radius, and risk budgets.

This module defines the risk taxonomy for Aragora's policy engine,
enabling fine-grained control over action severity and resource limits.

Blast Radius Levels:
- 0: Read-only (no side effects)
- 1: Draft (changes visible only to agent)
- 2: Write behind feature flag (reversible)
- 3: Write to staging (requires approval)
- 4: Deploy to production (requires multi-agent consensus + human)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import TypeAlias

logger = logging.getLogger(__name__)

RiskActionRecord: TypeAlias = dict[str, str | float | bool | None]


class RiskLevel(IntEnum):
    """Risk level for tools and actions.

    Higher levels require more scrutiny and may need approval.
    """

    NONE = 0  # Pure observation, no side effects
    LOW = 1  # Minor side effects, easily reversible
    MEDIUM = 2  # Moderate side effects, reversible with effort
    HIGH = 3  # Significant side effects, may need human review
    CRITICAL = 4  # Major side effects, requires human approval


class BlastRadius(IntEnum):
    """Blast radius - how far can damage spread?

    This measures the scope of potential harm, not the likelihood.
    """

    READ_ONLY = 0  # No mutations possible
    DRAFT = 1  # Changes visible only to agent, discardable
    LOCAL = 2  # Changes to local files, reversible via git
    SHARED = 3  # Changes visible to team (staging, shared DB)
    PRODUCTION = 4  # Changes affect live users


@dataclass
class RiskBudget:
    """Risk budget for a task or session.

    Each run gets a risk budget. Actions consume budget based on their
    risk level and blast radius. When budget is exceeded, the run must
    stop or escalate to human approval.

    Usage:
        budget = RiskBudget(total=100, human_approval_threshold=80)

        # Check if action is within budget
        cost = budget.calculate_cost(RiskLevel.MEDIUM, BlastRadius.LOCAL)
        if budget.can_afford(cost):
            budget.spend(cost, "write config.py")
        else:
            # Escalate to human or abort
    """

    total: float = 100.0  # Total budget for this session
    spent: float = 0.0  # Budget consumed so far
    human_approval_threshold: float = 80.0  # Above this, require human
    max_single_action: float = 30.0  # Max cost for any single action

    # Tracking
    actions: list[RiskActionRecord] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_action_at: str | None = None

    @property
    def remaining(self) -> float:
        """Remaining budget."""
        return max(0, self.total - self.spent)

    @property
    def utilization(self) -> float:
        """Budget utilization as fraction (0-1)."""
        return self.spent / self.total if self.total > 0 else 1.0

    @property
    def requires_human_approval(self) -> bool:
        """True if current spend level requires human approval."""
        return self.spent >= self.human_approval_threshold

    def calculate_cost(
        self,
        risk_level: RiskLevel,
        blast_radius: BlastRadius,
        multiplier: float = 1.0,
    ) -> float:
        """Calculate the cost of an action.

        Cost = risk_level * blast_radius * multiplier

        Args:
            risk_level: The risk level of the action
            blast_radius: How far damage could spread
            multiplier: Optional multiplier for context-specific adjustments
        """
        # Base cost: risk * blast radius
        # This means READ_ONLY (0) actions are always free
        # and CRITICAL + PRODUCTION = 4 * 4 = 16 base cost
        base_cost = risk_level.value * (blast_radius.value + 1)
        return base_cost * multiplier

    def can_afford(self, cost: float) -> bool:
        """Check if action is within budget."""
        if cost > self.max_single_action:
            return False
        return self.spent + cost <= self.total

    def can_afford_without_approval(self, cost: float) -> bool:
        """Check if action is within budget without needing human approval."""
        if not self.can_afford(cost):
            return False
        return self.spent + cost < self.human_approval_threshold

    def spend(
        self,
        cost: float,
        description: str,
        agent: str = "unknown",
        tool: str = "unknown",
    ) -> bool:
        """Spend budget on an action.

        Args:
            cost: The cost of the action
            description: Human-readable description
            agent: Which agent performed the action
            tool: Which tool was used

        Returns:
            True if action was within budget, False if exceeded
        """
        within_budget = self.can_afford(cost)

        self.spent += cost
        self.last_action_at = datetime.now().isoformat()
        self.actions.append(
            {
                "cost": cost,
                "description": description,
                "agent": agent,
                "tool": tool,
                "timestamp": self.last_action_at,
                "remaining_after": self.remaining,
                "within_budget": within_budget,
            }
        )

        if not within_budget:
            logger.warning(
                f"Risk budget exceeded: spent {self.spent:.1f}/{self.total:.1f} "
                f"after '{description}' by {agent}"
            )

        return within_budget

    def to_dict(self) -> dict[str, object]:
        """Convert to dictionary for serialization."""
        return {
            "total": self.total,
            "spent": self.spent,
            "remaining": self.remaining,
            "utilization": self.utilization,
            "human_approval_threshold": self.human_approval_threshold,
            "max_single_action": self.max_single_action,
            "requires_human_approval": self.requires_human_approval,
            "action_count": len(self.actions),
            "created_at": self.created_at,
            "last_action_at": self.last_action_at,
        }


# Risk level descriptions for UI/logs
RISK_LEVEL_DESCRIPTIONS = {
    RiskLevel.NONE: "No risk - pure observation",
    RiskLevel.LOW: "Low risk - easily reversible",
    RiskLevel.MEDIUM: "Medium risk - reversible with effort",
    RiskLevel.HIGH: "High risk - may need human review",
    RiskLevel.CRITICAL: "Critical risk - requires human approval",
}

BLAST_RADIUS_DESCRIPTIONS = {
    BlastRadius.READ_ONLY: "Read-only - no mutations",
    BlastRadius.DRAFT: "Draft - changes discardable",
    BlastRadius.LOCAL: "Local - reversible via git",
    BlastRadius.SHARED: "Shared - affects team/staging",
    BlastRadius.PRODUCTION: "Production - affects live users",
}


def get_risk_color(level: RiskLevel) -> str:
    """Get color for UI display."""
    colors = {
        RiskLevel.NONE: "gray",
        RiskLevel.LOW: "green",
        RiskLevel.MEDIUM: "yellow",
        RiskLevel.HIGH: "orange",
        RiskLevel.CRITICAL: "red",
    }
    return colors.get(level, "gray")


def get_blast_radius_color(radius: BlastRadius) -> str:
    """Get color for UI display."""
    colors = {
        BlastRadius.READ_ONLY: "gray",
        BlastRadius.DRAFT: "blue",
        BlastRadius.LOCAL: "green",
        BlastRadius.SHARED: "yellow",
        BlastRadius.PRODUCTION: "red",
    }
    return colors.get(radius, "gray")


__all__ = [
    "RiskLevel",
    "BlastRadius",
    "RiskBudget",
    "RISK_LEVEL_DESCRIPTIONS",
    "BLAST_RADIUS_DESCRIPTIONS",
    "get_risk_color",
    "get_blast_radius_color",
]
