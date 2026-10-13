"""Registers the control-plane task scheduler with :mod:`aragora.agents.scheduler_protocol`."""

from __future__ import annotations

from aragora.agents.scheduler_protocol import register_distributed_scheduler_factory
from aragora.control_plane import scheduler as _scheduler


def build_distributed_scheduler() -> _scheduler.TaskScheduler:
    """Create a control-plane task scheduler with its default configuration."""
    # Read at call time so a patched ``aragora.control_plane.scheduler.TaskScheduler`` applies.
    return _scheduler.TaskScheduler()


def register_distributed_scheduler() -> None:
    """Register :func:`build_distributed_scheduler`; safe to call more than once."""
    register_distributed_scheduler_factory(build_distributed_scheduler)


__all__ = ["build_distributed_scheduler", "register_distributed_scheduler"]
