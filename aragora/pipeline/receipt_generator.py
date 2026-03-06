"""Pipeline provenance receipt generator.

Generates DecisionReceipts that capture the full Idea-to-Execution
provenance chain: ideas -> goals -> actions -> orchestration results.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.pipeline.backbone_contracts import ReceiptEnvelope

logger = logging.getLogger(__name__)


async def generate_pipeline_receipt(
    pipeline_id: str,
    execution_result: dict[str, Any],
) -> dict[str, Any]:
    """Generate a DecisionReceipt for a completed pipeline execution.

    Loads the UniversalGraph for the pipeline, extracts stage data,
    and creates a receipt with full provenance.

    Args:
        pipeline_id: The pipeline that was executed
        execution_result: Results from the execution (cycle_id, status, etc.)

    Returns:
        Receipt dictionary with provenance chain
    """
    # Load pipeline graph for provenance data
    stages: dict[str, list[dict[str, Any]]] = {}
    try:
        from aragora.canvas.stages import PipelineStage  # type: ignore[attr-defined]
        from aragora.pipeline.graph_store import get_graph_store

        graph_store = get_graph_store()
        stage_mapping = {
            "ideas": PipelineStage.IDEAS,
            "goals": PipelineStage.GOALS,
            "actions": PipelineStage.ACTIONS,
            "orchestration": PipelineStage.ORCHESTRATION,
        }

        for stage_name, stage in stage_mapping.items():
            stage_nodes = graph_store.query_nodes(
                graph_id=pipeline_id,
                stage=stage,
            )
            stages[stage_name] = [
                {
                    "id": getattr(n, "id", ""),
                    "label": getattr(n, "label", ""),
                    "type": getattr(n, "node_subtype", ""),
                }
                for n in (stage_nodes or [])
            ]
    except (ImportError, RuntimeError, ValueError, OSError, AttributeError) as e:
        logger.debug("Pipeline graph loading skipped: %s", type(e).__name__)

    # Build the receipt
    receipt_id = f"receipt-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()

    # Create content hash for integrity
    content_str = f"{pipeline_id}:{execution_result}:{stages}"
    content_hash = hashlib.sha256(content_str.encode()).hexdigest()

    receipt = {
        "receipt_id": receipt_id,
        "pipeline_id": pipeline_id,
        "generated_at": now,
        "content_hash": content_hash,
        "provenance": {
            "ideas": stages.get("ideas", []),
            "goals": stages.get("goals", []),
            "actions": stages.get("actions", []),
            "orchestration": stages.get("orchestration", []),
        },
        "execution": {
            "cycle_id": execution_result.get("cycle_id"),
            "status": execution_result.get("status", "unknown"),
            "started_at": execution_result.get("started_at"),
            "completed_at": execution_result.get("completed_at"),
            "files_changed": execution_result.get("files_changed", []),
            "test_results": execution_result.get("test_results"),
            "improvement_score": execution_result.get("improvement_score"),
            "convoy_id": execution_result.get("convoy_id"),
        },
        "summary": {
            "total_ideas": len(stages.get("ideas", [])),
            "total_goals": len(stages.get("goals", [])),
            "total_actions": len(stages.get("actions", [])),
            "total_orchestration_nodes": len(stages.get("orchestration", [])),
        },
    }

    # Persist to KM if available
    try:
        from aragora.knowledge.mound.adapters.receipt_adapter import ReceiptAdapter

        adapter = ReceiptAdapter()
        adapter.ingest(receipt)
        logger.info("Pipeline receipt %s persisted to KM", receipt_id)
    except (ImportError, RuntimeError, ValueError, OSError, AttributeError) as e:
        logger.debug("Receipt KM persistence skipped: %s", type(e).__name__)

    return receipt


def generate_receipt_envelope(
    receipt: dict[str, Any],
    *,
    policy_gate_result: dict[str, Any] | None = None,
    taint_summary: dict[str, Any] | None = None,
    blocked: bool = False,
) -> "ReceiptEnvelope":
    """Normalize a pipeline receipt into a stable ReceiptEnvelope (CLB-009).

    Both successful and blocked outcomes share the same shape so downstream
    stages (outcome feedback, audit, settlement) never need to branch on
    the receipt format.

    Args:
        receipt: Raw receipt dict from generate_pipeline_receipt().
        policy_gate_result: Policy evaluation result (allowed/blocked/reason).
        taint_summary: Taint flags accumulated across the pipeline.
        blocked: When True, overrides the verdict to "blocked" regardless of
            the execution status in the receipt.

    Returns:
        ReceiptEnvelope with normalized fields, provenance chain, and
        policy/taint data always present (defaulting to empty dicts).
    """
    from aragora.pipeline.backbone_contracts import ReceiptEnvelope

    envelope = ReceiptEnvelope.from_pipeline_receipt(
        receipt,
        policy_gate_result=policy_gate_result,
        taint_summary=taint_summary,
    )
    if blocked:
        envelope.verdict = "blocked"
    return envelope
