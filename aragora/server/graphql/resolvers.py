"""
GraphQL Resolvers for Aragora API.

This module contains resolver functions that bridge GraphQL operations
to the existing REST handlers and services.

Resolvers follow a consistent pattern:
1. Extract arguments from the GraphQL field
2. Call the appropriate service/handler method
3. Transform the result to match the GraphQL schema

Note: Domain-specific resolvers are split across submodules:
- resolvers_debates: Debate queries, mutations, subscriptions, and transforms
- resolvers_agents: Agent queries, mutations, and transforms
- resolvers_tasks: Task queries, mutations, subscriptions, and transforms

This module defines shared types and utilities used by the submodules,
and re-exports everything for backward compatibility.

Usage:
    from aragora.server.graphql.resolvers import QueryResolvers, MutationResolvers
    result = await QueryResolvers.resolve_debate(context, id="debate-123")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING


if TYPE_CHECKING:
    from aragora.server.graphql.dataloaders import DataLoaderContext

logger = logging.getLogger(__name__)

# =============================================================================
# Context and Types
# =============================================================================


@dataclass
class ResolverContext:
    """Context passed to resolvers during execution.

    Attributes:
        server_context: Server context with storage, ELO system, etc.
        user_id: Authenticated user ID (if authenticated)
        org_id: Organization/workspace ID
        trace_id: Request trace ID for logging
        variables: Query variables
        loaders: DataLoaderContext for batched queries (N+1 prevention)
    """

    server_context: dict[str, Any]
    user_id: str | None = None
    org_id: str | None = None
    trace_id: str | None = None
    variables: dict[str, Any] = field(default_factory=dict)
    loaders: DataLoaderContext | None = None

    def __post_init__(self) -> None:
        pass  # variables now has proper default factory


@dataclass
class ResolverResult:
    """Result from a resolver execution.

    Attributes:
        data: Resolved data
        errors: List of error messages
    """

    data: Any = None
    errors: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        pass  # errors now has proper default factory

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


# =============================================================================
# Status Mapping Utilities
# =============================================================================


def _normalize_debate_status(status: str | None) -> str:
    """Normalize internal debate status to GraphQL enum value."""
    status_map = {
        "starting": "PENDING",
        "running": "RUNNING",
        "active": "RUNNING",
        "completed": "COMPLETED",
        "concluded": "COMPLETED",
        "failed": "FAILED",
        "cancelled": "CANCELLED",
        "canceled": "CANCELLED",
        "paused": "PENDING",
    }
    if not status:
        return "PENDING"
    return status_map.get(status.lower(), status.upper())


def _normalize_agent_status(status: str | None) -> str:
    """Normalize agent status to GraphQL enum value."""
    status_map = {
        "available": "AVAILABLE",
        "idle": "AVAILABLE",
        "busy": "BUSY",
        "running": "BUSY",
        "offline": "OFFLINE",
        "degraded": "DEGRADED",
        "error": "DEGRADED",
    }
    if not status:
        return "OFFLINE"
    return status_map.get(status.lower(), status.upper())


def _normalize_task_status(status: str | None) -> str:
    """Normalize task status to GraphQL enum value."""
    status_map = {
        "pending": "PENDING",
        "queued": "PENDING",
        "running": "RUNNING",
        "in_progress": "RUNNING",
        "completed": "COMPLETED",
        "done": "COMPLETED",
        "failed": "FAILED",
        "error": "FAILED",
        "cancelled": "CANCELLED",
        "canceled": "CANCELLED",
    }
    if not status:
        return "PENDING"
    return status_map.get(status.lower(), status.upper())


def _normalize_priority(priority: str | None) -> str:
    """Normalize priority to GraphQL enum value."""
    priority_map = {
        "low": "LOW",
        "normal": "NORMAL",
        "medium": "NORMAL",
        "high": "HIGH",
        "urgent": "URGENT",
        "critical": "URGENT",
    }
    if not priority:
        return "NORMAL"
    return priority_map.get(priority.lower(), priority.upper())


def _normalize_health_status(status: str | None) -> str:
    """Normalize health status to GraphQL enum value."""
    status_map = {
        "healthy": "HEALTHY",
        "ok": "HEALTHY",
        "degraded": "DEGRADED",
        "warning": "DEGRADED",
        "unhealthy": "UNHEALTHY",
        "error": "UNHEALTHY",
        "down": "UNHEALTHY",
    }
    if not status:
        return "HEALTHY"
    return status_map.get(status.lower(), status.upper())


def _to_iso_datetime(value: Any) -> str | None:
    """Convert various datetime formats to ISO string."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value).isoformat()
    return str(value)


# =============================================================================
# Re-export domain-specific resolvers for backward compatibility
# =============================================================================

from .resolvers_debates import (
    DebateMutationResolvers,
    DebateQueryResolvers,
    DebateSubscriptionResolvers,
)

from .resolvers_agents import (
    AgentMutationResolvers,
    AgentQueryResolvers,
)

from .resolvers_tasks import (
    TaskMutationResolvers,
    TaskQueryResolvers,
    TaskSubscriptionResolvers,
)


# =============================================================================
# Backward-compatible aggregated resolver classes
# =============================================================================


class QueryResolvers:
    """Resolvers for GraphQL Query operations.

    Aggregates domain-specific query resolvers for backward compatibility.
    """

    # Debate queries
    resolve_debate = DebateQueryResolvers.resolve_debate
    resolve_debates = DebateQueryResolvers.resolve_debates
    resolve_search_debates = DebateQueryResolvers.resolve_search_debates

    # Agent queries
    resolve_agent = AgentQueryResolvers.resolve_agent
    resolve_agents = AgentQueryResolvers.resolve_agents
    resolve_leaderboard = AgentQueryResolvers.resolve_leaderboard

    # Task queries
    resolve_task = TaskQueryResolvers.resolve_task
    resolve_tasks = TaskQueryResolvers.resolve_tasks

    # System queries
    resolve_system_health = TaskQueryResolvers.resolve_system_health
    resolve_stats = TaskQueryResolvers.resolve_stats


class MutationResolvers:
    """Resolvers for GraphQL Mutation operations.

    Aggregates domain-specific mutation resolvers for backward compatibility.
    """

    # Debate mutations
    resolve_start_debate = DebateMutationResolvers.resolve_start_debate
    resolve_submit_vote = DebateMutationResolvers.resolve_submit_vote
    resolve_cancel_debate = DebateMutationResolvers.resolve_cancel_debate

    # Task mutations
    resolve_submit_task = TaskMutationResolvers.resolve_submit_task
    resolve_cancel_task = TaskMutationResolvers.resolve_cancel_task

    # Agent mutations
    resolve_register_agent = AgentMutationResolvers.resolve_register_agent
    resolve_unregister_agent = AgentMutationResolvers.resolve_unregister_agent


class SubscriptionResolvers:
    """Resolvers for GraphQL Subscription operations.

    Aggregates domain-specific subscription resolvers for backward compatibility.
    """

    subscribe_debate_updates = DebateSubscriptionResolvers.subscribe_debate_updates
    subscribe_task_updates = TaskSubscriptionResolvers.subscribe_task_updates


# =============================================================================
# Resolver Registry
# =============================================================================

QUERY_RESOLVERS = {
    "debate": QueryResolvers.resolve_debate,
    "debates": QueryResolvers.resolve_debates,
    "searchDebates": QueryResolvers.resolve_search_debates,
    "agent": QueryResolvers.resolve_agent,
    "agents": QueryResolvers.resolve_agents,
    "leaderboard": QueryResolvers.resolve_leaderboard,
    "task": QueryResolvers.resolve_task,
    "tasks": QueryResolvers.resolve_tasks,
    "systemHealth": QueryResolvers.resolve_system_health,
    "stats": QueryResolvers.resolve_stats,
}

MUTATION_RESOLVERS = {
    "startDebate": MutationResolvers.resolve_start_debate,
    "submitVote": MutationResolvers.resolve_submit_vote,
    "cancelDebate": MutationResolvers.resolve_cancel_debate,
    "submitTask": MutationResolvers.resolve_submit_task,
    "cancelTask": MutationResolvers.resolve_cancel_task,
    "registerAgent": MutationResolvers.resolve_register_agent,
    "unregisterAgent": MutationResolvers.resolve_unregister_agent,
}

SUBSCRIPTION_RESOLVERS = {
    "debateUpdates": SubscriptionResolvers.subscribe_debate_updates,
    "taskUpdates": SubscriptionResolvers.subscribe_task_updates,
}
