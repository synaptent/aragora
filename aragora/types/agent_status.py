"""Lifecycle status of agents registered with the control plane.

The control-plane agent registry stores these values, and debate team selection reads
them to score agent health. They live here so the debate engine need not import the
control plane; :mod:`aragora.control_plane.registry` re-exports the same enum.
"""

from __future__ import annotations

from enum import Enum


class AgentStatus(Enum):
    """Agent lifecycle status."""

    STARTING = "starting"  # Agent is initializing
    READY = "ready"  # Agent is ready to accept tasks
    BUSY = "busy"  # Agent is processing a task
    DRAINING = "draining"  # Agent is completing current task, no new tasks
    OFFLINE = "offline"  # Agent is not responding
    FAILED = "failed"  # Agent has failed


__all__ = ["AgentStatus"]
