"""Registers the workflow engine as the debate engine's post-debate workflow backend.

Reached through the ``aragora.debate_workflow_backends`` entry point in ``pyproject.toml``
on the debate engine's first workflow lookup, so the debate engine never imports
``aragora.workflow``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aragora.debate.workflow_backends import register_workflow_backend
from aragora.workflow import engine, triggers
from aragora.workflow.patterns import post_debate


class WorkflowEngineBackend:
    """Runs post-debate workflows on the process-wide workflow engine.

    Module attributes are looked up on each call so a patched engine, trigger or pattern
    applies.
    """

    def default_post_debate_workflow(self) -> Any:
        return post_debate.get_default_post_debate_workflow()

    async def execute(self, definition: Any, inputs: dict[str, Any]) -> Any:
        return await engine.get_workflow_engine().execute(definition=definition, inputs=inputs)

    def receipt_rule_matches(
        self,
        name: str,
        condition: Callable[[dict[str, Any]], bool],
        workflow_template: str,
        receipt: dict[str, Any],
    ) -> bool:
        trigger = triggers.ReceiptWorkflowTrigger()
        trigger.register_rule(name=name, condition=condition, workflow_template=workflow_template)
        return len(trigger.evaluate(receipt)) > 0


def register_debate_workflow_backend() -> None:
    """Register the workflow engine backend; safe to call more than once."""
    register_workflow_backend(WorkflowEngineBackend())


__all__ = ["WorkflowEngineBackend", "register_debate_workflow_backend"]
