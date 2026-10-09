"""Hand a decision run to the debate runner.

Intake (and rerun) commits a decision in status ``debating`` with a
``running`` run, then calls :func:`launch_decision_run`. The runner registers
itself with :func:`set_decision_debate_starter`. When no runner is
registered, or the runner cannot schedule the run, the run is finished as
``failed`` with the reason, so the decision becomes ``failed`` and can be
rerun instead of staying ``debating``. The starter is called on the request
thread, so it must schedule the debate and return rather than run it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aragora.utils.error_sanitizer import sanitize_error

if TYPE_CHECKING:
    from aragora.decision_workspace.store import WorkspaceStore

logger = logging.getLogger(__name__)

NO_RUNNER_ERROR = (
    "The debate runner is not available on this server, so the debate did not start. "
    "Rerun the decision once the server has finished starting."
)


@dataclass(frozen=True, slots=True)
class DebateStartRequest:
    """What the runner needs to debate one decision; owner fields come from auth."""

    plan_id: str
    org_id: str
    user_id: str
    question: str
    agents: tuple[str, ...]
    rounds: int
    run_id: str


class DebateNotStartedError(RuntimeError):
    """The run could not be handed to a runner; the message is safe to show."""


DecisionDebateStarter = Callable[[DebateStartRequest], object]

_starter: DecisionDebateStarter | None = None


def set_decision_debate_starter(starter: DecisionDebateStarter | None) -> None:
    """Register the debate runner (``None`` unregisters it)."""
    global _starter
    _starter = starter


def get_decision_debate_starter() -> DecisionDebateStarter | None:
    return _starter


def start_decision_debate(request: DebateStartRequest) -> None:
    """Give ``request`` to the runner; raises :class:`DebateNotStartedError` when it cannot."""
    starter = _starter
    if starter is None:
        raise DebateNotStartedError(NO_RUNNER_ERROR)
    try:
        starter(request)
    except Exception as exc:
        logger.exception("Decision debate runner failed to start decision %s", request.plan_id)
        raise DebateNotStartedError(
            "The debate could not be started: "
            + sanitize_error(f"{type(exc).__name__}: {exc}", max_length=300)
        ) from exc


def launch_decision_run(store: WorkspaceStore, request: DebateStartRequest) -> bool:
    """Start the run, or finish it ``failed`` with the reason; True when it started."""
    from aragora.decision_workspace.store import RUN_FAILED

    try:
        start_decision_debate(request)
    except DebateNotStartedError as exc:
        logger.warning("Decision %s run %s did not start: %s", request.plan_id, request.run_id, exc)
        store.finish_run(request.run_id, request.org_id, status=RUN_FAILED, error=str(exc))
        return False
    return True


__all__ = [
    "DebateNotStartedError",
    "DebateStartRequest",
    "DecisionDebateStarter",
    "NO_RUNNER_ERROR",
    "get_decision_debate_starter",
    "launch_decision_run",
    "set_decision_debate_starter",
    "start_decision_debate",
]
