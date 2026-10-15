"""Status and priority values of control-plane scheduled tasks.

The control-plane scheduler stores these values, and lower packages (the agents
scheduler protocol, the knowledge mound revalidation scheduler) build or read them
when they hand work to it. They live here so those packages need not import the
control plane; :mod:`aragora.control_plane.scheduler` re-exports the same enums.
"""

from __future__ import annotations

from enum import Enum


class TaskStatus(Enum):
    """Task lifecycle status."""

    PENDING = "pending"  # Task is queued, waiting for assignment
    ASSIGNED = "assigned"  # Task assigned to an agent
    RUNNING = "running"  # Task is being executed
    COMPLETED = "completed"  # Task completed successfully
    FAILED = "failed"  # Task failed after all retries
    CANCELLED = "cancelled"  # Task was cancelled
    TIMEOUT = "timeout"  # Task timed out


class TaskPriority(Enum):
    """Task priority levels."""

    LOW = 0
    NORMAL = 50
    HIGH = 75
    URGENT = 100


__all__ = ["TaskPriority", "TaskStatus"]
