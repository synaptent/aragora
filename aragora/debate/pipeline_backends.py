"""Hook through which the debate engine reaches the decision pipeline.

The debate engine sits below ``aragora.pipeline``, which builds decision plans from debate
results, executes and stores them, writes the backbone run ledger, and turns debates into
integrity packages, canvases and decision memos. It must not import it.
The first :func:`pipeline_backend` that finds no backend runs, once per process, the
registrations declared under the ``aragora.debate_pipeline_backends`` entry-point group;
aragora's own ``pyproject.toml`` declares the decision pipeline there. A later registration
replaces the previous backend.

:func:`pipeline_backend` raises :class:`PipelineBackendNotRegisteredError` when no backend is
registered after that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from aragora.utils.declared_registrations import DeclaredRegistrations

PIPELINE_BACKENDS_ENTRY_POINT_GROUP = "aragora.debate_pipeline_backends"


class DebatePipelineBackend(Protocol):
    """What the debate engine needs from the decision pipeline.

    Each method returns the pipeline's own class or function, so callers use it as they
    would an imported name. A method raises ``ImportError`` when the pipeline module that
    defines the object cannot be imported.
    """

    def decision_plan_factory(self) -> Any:
        """``DecisionPlanFactory``, which builds decision plans from debate results."""
        ...

    def plan_executor(self) -> Any:
        """``PlanExecutor``, which executes decision plans."""
        ...

    def plan_registry(self) -> tuple[Callable[..., Any], Callable[..., Any]]:
        """``(get_plan, store_plan)`` of the in-process decision plan registry."""
        ...

    def backbone_plan_runs(self) -> tuple[Callable[..., Any], ...]:
        """``(ensure_decision_plan_backbone_run, execute_decision_plan_with_backbone,
        sync_decision_plan_backbone_receipt)``."""
        ...

    def backbone_runtime(self) -> Any:
        """``BackboneRuntime``, which writes the backbone run ledger."""
        ...

    def integrity_package_builder(self) -> Callable[..., Any]:
        """``build_integrity_package_from_result``."""
        ...

    def idea_to_execution_pipeline(self) -> Any:
        """``IdeaToExecutionPipeline``, which turns a debate's argument graph into a canvas."""
        ...

    def decision_memo(self) -> Any:
        """``DecisionMemo``, the stakeholder summary of a debate's conclusions."""
        ...


class PipelineBackendNotRegisteredError(RuntimeError):
    """No decision pipeline backend is registered."""


_backend: DebatePipelineBackend | None = None
_declared = DeclaredRegistrations(PIPELINE_BACKENDS_ENTRY_POINT_GROUP)


def register_pipeline_backend(backend: DebatePipelineBackend) -> None:
    """Make ``backend`` the decision pipeline the debate engine uses, replacing any earlier one."""
    global _backend
    _backend = backend


def pipeline_backend() -> DebatePipelineBackend:
    """The registered decision pipeline backend.

    Raises:
        PipelineBackendNotRegisteredError: no backend is registered, even after the declared
            registrations ran.
    """
    backend = _backend
    if backend is None:
        _declared.load()
        backend = _backend
    if backend is None:
        raise PipelineBackendNotRegisteredError(
            "no decision pipeline backend is registered; import "
            "aragora.pipeline.debate_registration and call register_debate_pipeline_backend(), "
            f"or declare a registration under the {PIPELINE_BACKENDS_ENTRY_POINT_GROUP!r} "
            "entry-point group"
        )
    return backend


__all__ = [
    "PIPELINE_BACKENDS_ENTRY_POINT_GROUP",
    "DebatePipelineBackend",
    "PipelineBackendNotRegisteredError",
    "pipeline_backend",
    "register_pipeline_backend",
]
