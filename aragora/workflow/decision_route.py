"""Workflow decisions for :class:`aragora.core.decision_router.DecisionRouter`.

The core router cannot import this package, so ``aragora.workflow`` registers
:func:`route_workflow_decision` as the ``workflow`` route target when it is imported.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from aragora.core.decision_models import DecisionResult, normalize_document_ids
from aragora.core.decision_route_hooks import ROUTE_WORKFLOW, register_route_target
from aragora.core.decision_types import DecisionType
from aragora.workflow.engine import get_workflow_engine
from aragora.workflow.persistent_store import get_workflow_store

if TYPE_CHECKING:
    from aragora.core.decision_models import DecisionRequest
    from aragora.core.decision_router import DecisionRouter


async def route_workflow_decision(
    router: DecisionRouter, request: DecisionRequest, span: Any | None
) -> DecisionResult:
    """Run the stored workflow named by ``request.config.workflow_id``."""
    engine = router.workflow_engine
    if engine is None:
        engine = get_workflow_engine()
        router.workflow_engine = engine

    workflow_id = request.config.workflow_id
    if not workflow_id:
        raise ValueError("Workflow ID required for workflow decision type")

    if span:
        span.set_attribute("workflow.id", workflow_id)

    definition_result = get_workflow_store().get_workflow(workflow_id)
    # Handle both sync and async get_workflow implementations
    if inspect.iscoroutine(definition_result):
        definition = await definition_result
    else:
        definition = definition_result
    if not definition:
        raise ValueError(f"Workflow not found: {workflow_id}")

    documents = list(getattr(request, "documents", []) or [])
    metadata = request.context.metadata or {}
    metadata_docs = metadata.get("documents") or metadata.get("document_ids")
    if metadata_docs:
        documents.extend(normalize_document_ids(metadata_docs))

    workflow_result = await engine.execute(
        definition=definition,
        inputs={
            "content": request.content,
            "documents": documents,
            "attachments": request.attachments or [],
            "evidence": request.evidence or [],
            **request.config.workflow_inputs,
        },
    )

    if span:
        span.set_attribute("workflow.success", workflow_result.success)

    outputs = workflow_result.final_output if workflow_result.final_output else {}
    answer = outputs.get("answer") or outputs.get("result") or ""

    return DecisionResult(
        request_id=request.request_id,
        decision_type=DecisionType.WORKFLOW,
        answer=str(answer),
        confidence=0.9 if workflow_result.success else 0.0,
        consensus_reached=workflow_result.success,
        workflow_result=workflow_result,
    )


def register_decision_route() -> None:
    """Register :func:`route_workflow_decision` with the core decision router."""
    register_route_target(ROUTE_WORKFLOW, route_workflow_decision)
