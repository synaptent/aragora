"""Registers the decision pipeline as the debate engine's pipeline backend.

Reached through the ``aragora.debate_pipeline_backends`` entry point in ``pyproject.toml``
on the debate engine's first pipeline lookup, so the debate engine never imports
``aragora.pipeline``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aragora.debate.pipeline_backends import register_pipeline_backend


class DecisionPipelineBackend:
    """Hands the debate engine the decision pipeline's classes and functions.

    Each method imports its module when called, as the debate engine's own imports did,
    so a patched module attribute applies and a module that cannot be imported (including
    one set to ``None`` in ``sys.modules``) raises ``ImportError`` to the caller.
    """

    def decision_plan_factory(self) -> Any:
        from aragora.pipeline.decision_plan import DecisionPlanFactory

        return DecisionPlanFactory

    def plan_executor(self) -> Any:
        from aragora.pipeline.executor import PlanExecutor

        return PlanExecutor

    def plan_registry(self) -> tuple[Callable[..., Any], Callable[..., Any]]:
        from aragora.pipeline.executor import get_plan, store_plan

        return get_plan, store_plan

    def backbone_plan_runs(self) -> tuple[Callable[..., Any], ...]:
        from aragora.pipeline.decision_integrity_utils import (
            ensure_decision_plan_backbone_run,
            execute_decision_plan_with_backbone,
            sync_decision_plan_backbone_receipt,
        )

        return (
            ensure_decision_plan_backbone_run,
            execute_decision_plan_with_backbone,
            sync_decision_plan_backbone_receipt,
        )

    def backbone_runtime(self) -> Any:
        from aragora.pipeline.backbone_runtime import BackboneRuntime

        return BackboneRuntime

    def integrity_package_builder(self) -> Callable[..., Any]:
        from aragora.pipeline.decision_integrity import build_integrity_package_from_result

        return build_integrity_package_from_result

    def idea_to_execution_pipeline(self) -> Any:
        from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline

        return IdeaToExecutionPipeline

    def decision_memo(self) -> Any:
        from aragora.pipeline.pr_generator import DecisionMemo

        return DecisionMemo


def register_debate_pipeline_backend() -> None:
    """Register the decision pipeline backend; safe to call more than once."""
    register_pipeline_backend(DecisionPipelineBackend())


__all__ = ["DecisionPipelineBackend", "register_debate_pipeline_backend"]
