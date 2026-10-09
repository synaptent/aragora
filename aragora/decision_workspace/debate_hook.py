"""Hand a newly created workspace decision to the debate runner.

Intake commits a decision in status ``debating`` and then calls
:func:`start_decision_debate`. The runner registers itself with
:func:`set_decision_debate_starter`; while none is registered the decision
stays ``debating``. The starter is called on the request thread, so it must
schedule the debate and return rather than run it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DebateStartRequest:
    """What the runner needs to debate one decision; owner fields come from auth."""

    plan_id: str
    org_id: str
    user_id: str
    question: str
    agents: tuple[str, ...]
    rounds: int


DecisionDebateStarter = Callable[[DebateStartRequest], object]

_starter: DecisionDebateStarter | None = None


def set_decision_debate_starter(starter: DecisionDebateStarter | None) -> None:
    """Register the debate runner (``None`` unregisters it)."""
    global _starter
    _starter = starter


def start_decision_debate(request: DebateStartRequest) -> bool:
    """Start the debate for ``request``; False when no runner took it."""
    starter = _starter
    if starter is None:
        logger.info(
            "No decision debate runner is registered; decision %s stays debating",
            request.plan_id,
        )
        return False
    try:
        starter(request)
    except Exception:  # noqa: BLE001 - the decision is already committed; the runner owns failures
        logger.exception("Decision debate runner failed to start decision %s", request.plan_id)
        return False
    return True


__all__ = [
    "DebateStartRequest",
    "DecisionDebateStarter",
    "set_decision_debate_starter",
    "start_decision_debate",
]
