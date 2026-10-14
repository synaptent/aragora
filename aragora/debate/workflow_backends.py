"""Hook through which the debate engine runs post-debate workflows.

The debate engine sits below ``aragora.workflow``, whose engine runs workflow definitions
and whose triggers match decision receipts to workflow templates, and must not import it.
The first :func:`workflow_backend` that finds no backend runs, once per process, the
registrations declared under the ``aragora.debate_workflow_backends`` entry-point group;
aragora's own ``pyproject.toml`` declares the workflow engine there. A later registration
replaces the previous backend.

:func:`workflow_backend` raises :class:`WorkflowBackendNotRegisteredError` when no backend is
registered after that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from aragora.utils.declared_registrations import DeclaredRegistrations

WORKFLOW_BACKENDS_ENTRY_POINT_GROUP = "aragora.debate_workflow_backends"


class DebateWorkflowBackend(Protocol):
    """What the debate engine needs from a workflow engine."""

    def default_post_debate_workflow(self) -> Any:
        """The workflow definition to run after a debate when the caller supplied none."""
        ...

    async def execute(self, definition: Any, inputs: dict[str, Any]) -> Any:
        """Run ``definition`` on ``inputs``; the result has ``success``, ``final_output`` and
        ``error``."""
        ...

    def receipt_rule_matches(
        self,
        name: str,
        condition: Callable[[dict[str, Any]], bool],
        workflow_template: str,
        receipt: dict[str, Any],
    ) -> bool:
        """Whether a trigger rule named ``name`` fires ``workflow_template`` for ``receipt``."""
        ...


class WorkflowBackendNotRegisteredError(RuntimeError):
    """No post-debate workflow backend is registered."""


_backend: DebateWorkflowBackend | None = None
_declared = DeclaredRegistrations(WORKFLOW_BACKENDS_ENTRY_POINT_GROUP)


def register_workflow_backend(backend: DebateWorkflowBackend) -> None:
    """Make ``backend`` run post-debate workflows, replacing any earlier one."""
    global _backend
    _backend = backend


def workflow_backend() -> DebateWorkflowBackend:
    """The registered post-debate workflow backend.

    Raises:
        WorkflowBackendNotRegisteredError: no backend is registered, even after the declared
            registrations ran.
    """
    backend = _backend
    if backend is None:
        _declared.load()
        backend = _backend
    if backend is None:
        raise WorkflowBackendNotRegisteredError(
            "no post-debate workflow backend is registered; import "
            "aragora.workflow.debate_registration and call register_debate_workflow_backend(), "
            f"or declare a registration under the {WORKFLOW_BACKENDS_ENTRY_POINT_GROUP!r} "
            "entry-point group"
        )
    return backend


__all__ = [
    "WORKFLOW_BACKENDS_ENTRY_POINT_GROUP",
    "DebateWorkflowBackend",
    "WorkflowBackendNotRegisteredError",
    "register_workflow_backend",
    "workflow_backend",
]
