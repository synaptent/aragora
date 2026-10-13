"""Backward-compatibility shim - consolidated into orchestrator_setup.py."""

from aragora.debate.orchestrator_setup import (
    _compute_domain_from_task,
    compute_domain_from_task,
)

__all__ = ["compute_domain_from_task", "_compute_domain_from_task"]
