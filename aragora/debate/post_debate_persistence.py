"""RunLedger and Knowledge Mound writes for ``PostDebateCoordinator``.

``PostDebatePersistenceMixin`` holds the helpers that mirror post-debate progress into
the backbone RunLedger (plan, receipt and execution events) and that build and write
the receipt and outcome summaries to Knowledge Mound.
``PostDebateCoordinator`` (``aragora.debate.post_debate_coordinator``) inherits the
mixin and keeps the pipeline steps that call these helpers, plus ``_seed_backbone_run``
(the backbone entrypoint inventory is keyed by its path). Import the coordinator
from ``aragora.debate.post_debate_coordinator``.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from aragora.debate.post_debate_config import PostDebateConfig
from aragora.pipeline.execution_mode import ExecutionMode

# The coordinator's logger name, so log filters and caplog assertions keyed on
# "aragora.debate.post_debate_coordinator" still see records from these methods.
logger = logging.getLogger("aragora.debate.post_debate_coordinator")


class PostDebatePersistenceMixin:
    """RunLedger mirroring and Knowledge Mound writeback for ``PostDebateCoordinator``."""

    # Set by PostDebateCoordinator.__init__.
    config: PostDebateConfig
    _backbone_runtime: Any | None
    _backbone_runtime_failed: bool

    if TYPE_CHECKING:
        # Defined on PostDebateCoordinator.
        def _is_execution_blocked(self, gate: dict[str, Any] | None) -> bool: ...

    def _backbone_required(self) -> bool:
        return self.config.execution_mode == ExecutionMode.INTERACTIVE

    def _backbone_failure(self, message: str, exc: Exception | None = None) -> None:
        if self._backbone_required():
            raise RuntimeError(message) from exc
        if exc is None:
            logger.warning(message)
        else:
            logger.warning("%s: %s", message, exc)

    def _ensure_backbone_write(self, result: Any, message: str) -> None:
        if result is False:
            self._backbone_failure(message)

    def _get_backbone_runtime(self) -> Any | None:
        """Lazily initialize the backbone runtime used for post-debate ledger writes."""
        if self._backbone_runtime is not None:
            return self._backbone_runtime
        if self._backbone_runtime_failed:
            self._backbone_failure("Post-debate backbone runtime unavailable")
            return None
        try:
            from aragora.pipeline.backbone_runtime import BackboneRuntime

            self._backbone_runtime = BackboneRuntime()
        except (ImportError, RuntimeError, OSError, ValueError, TypeError) as e:
            self._backbone_runtime_failed = True
            self._backbone_failure("Post-debate backbone runtime unavailable", e)
            return None
        return self._backbone_runtime

    @staticmethod
    def _plan_object(plan_data: dict[str, Any] | None) -> Any | None:
        if not isinstance(plan_data, dict):
            return None
        if "plan" in plan_data:
            return plan_data.get("plan")
        return plan_data

    @staticmethod
    def _plan_id(plan_obj: Any) -> str:
        if isinstance(plan_obj, dict):
            candidates = (plan_obj.get("id"), plan_obj.get("plan_id"))
        else:
            candidates = (getattr(plan_obj, "id", None), getattr(plan_obj, "plan_id", None))

        for candidate in candidates:
            if isinstance(candidate, str):
                normalized = candidate.strip()
                if normalized:
                    return normalized
        return ""

    @staticmethod
    def _current_run_id(debate_result: Any) -> str:
        """Extract the backbone run_id previously seeded onto the debate result."""
        metadata = getattr(debate_result, "metadata", None)
        if not isinstance(metadata, dict):
            return ""
        return str(metadata.get("backbone_run_id", "") or "").strip()

    def _record_backbone_plan(
        self,
        run_id: str | None,
        debate_id: str,
        plan_data: dict[str, Any] | None,
    ) -> None:
        """Mirror plan creation into the RunLedger when available."""
        if not run_id:
            return

        plan_obj = self._plan_object(plan_data)
        plan_id = self._plan_id(plan_obj)
        if not plan_id:
            return

        runtime = self._get_backbone_runtime()
        if runtime is None:
            return

        try:
            if isinstance(plan_obj, dict):
                plan_obj.setdefault("backbone_run_id", run_id)
            elif plan_obj is not None:
                from aragora.pipeline.backbone_runtime import BackboneRuntime

                BackboneRuntime.ensure_plan_metadata(
                    plan_obj,
                    run_id,
                    "post_debate_coordinator.run",
                )

            self._ensure_backbone_write(
                runtime.update_run(
                    run_id,
                    status="plan_ready",
                    plan_id=plan_id,
                    debate_id=debate_id,
                ),
                "Post-debate plan state was not persisted",
            )
            self._ensure_backbone_write(
                runtime.append_stage_event(
                    run_id,
                    "plan",
                    status="created",
                    artifact_ref=plan_id,
                ),
                "Post-debate plan stage was not persisted",
            )
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            self._backbone_failure(f"Post-debate backbone plan record failed for {debate_id}", e)

    def _record_backbone_receipt(self, run_id: str | None, receipt_id: str) -> None:
        """Attach signed receipt state to the RunLedger."""
        if not run_id or not receipt_id:
            return

        runtime = self._get_backbone_runtime()
        if runtime is None:
            return

        try:
            self._ensure_backbone_write(
                runtime.update_run(
                    run_id,
                    receipt_id=receipt_id,
                    metadata={"signed_receipt_persisted": True},
                ),
                "Post-debate receipt state was not persisted",
            )
            self._ensure_backbone_write(
                runtime.append_stage_event(
                    run_id,
                    "receipt",
                    status="approved",
                    artifact_ref=receipt_id,
                ),
                "Post-debate receipt stage was not persisted",
            )
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            self._backbone_failure(f"Post-debate backbone receipt record failed for {run_id}", e)

    def _record_backbone_execution(
        self,
        run_id: str | None,
        plan_data: dict[str, Any] | None,
        execution_result: dict[str, Any] | None,
        *,
        execution_gate: dict[str, Any] | None,
    ) -> None:
        """Mirror execution requests and terminal state into the RunLedger."""
        if not run_id:
            return

        runtime = self._get_backbone_runtime()
        if runtime is None:
            return

        plan_id = self._plan_id(self._plan_object(plan_data))

        try:
            if self._is_execution_blocked(execution_gate):
                blocked_status = "blocked"
                if execution_result and execution_result.get("reason") == "execution_gate_blocked":
                    blocked_status = "pending_approval"
                self._ensure_backbone_write(
                    runtime.update_run(run_id, status=blocked_status),
                    "Post-debate execution block state was not persisted",
                )
                self._ensure_backbone_write(
                    runtime.append_stage_event(
                        run_id,
                        "execution",
                        status=blocked_status,
                        artifact_ref=plan_id,
                    ),
                    "Post-debate execution block event was not persisted",
                )
                return

            self._ensure_backbone_write(
                runtime.update_run(run_id, status="execution_requested"),
                "Post-debate execution request was not persisted",
            )
            self._ensure_backbone_write(
                runtime.append_stage_event(
                    run_id,
                    "execution",
                    status="requested",
                    artifact_ref=plan_id,
                ),
                "Post-debate execution request event was not persisted",
            )

            terminal_status = "failed"
            artifact_ref = plan_id
            if isinstance(execution_result, dict):
                if execution_result.get("skipped"):
                    terminal_status = "skipped"
                elif execution_result.get("error"):
                    terminal_status = "failed"
                else:
                    terminal_status = "completed"
                    artifact_ref = str(execution_result.get("url", "") or plan_id)

            run_status_map = {
                "completed": "execution_completed",
                "skipped": "execution_skipped",
                "failed": "execution_failed",
            }
            self._ensure_backbone_write(
                runtime.update_run(run_id, status=run_status_map[terminal_status]),
                "Post-debate execution result was not persisted",
            )
            self._ensure_backbone_write(
                runtime.append_stage_event(
                    run_id,
                    "execution",
                    status=terminal_status,
                    artifact_ref=artifact_ref,
                ),
                "Post-debate execution result event was not persisted",
            )
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            self._backbone_failure(
                f"Post-debate backbone execution record failed for {run_id}",
                e,
            )

    @staticmethod
    def _debate_consensus_reached(debate_result: Any) -> bool:
        """Return whether the debate reached consensus."""
        consensus_reached = getattr(debate_result, "consensus_reached", None)
        if consensus_reached is not None:
            return bool(consensus_reached)
        return bool(getattr(debate_result, "consensus", None))

    @staticmethod
    def _debate_final_answer(debate_result: Any) -> str:
        """Extract the best available final answer text from a debate result."""
        return str(
            getattr(
                debate_result,
                "final_answer",
                getattr(debate_result, "consensus", ""),
            )
        )

    @staticmethod
    def _task_slug(task: str) -> str:
        """Build a stable task slug for adapter-local cache lookups."""
        words = re.findall(r"[a-z0-9]+", str(task or "").lower())
        if not words:
            return "debate"
        return "-".join(words[:6])

    def _build_receipt_km_payload(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
        confidence: float,
        cost_breakdown: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build the receipt summary payload for ReceiptAdapter.ingest()."""
        resolved_task = str(task or getattr(debate_result, "task", ""))
        resolved_confidence = float(confidence or getattr(debate_result, "confidence", 0.0) or 0.0)
        payload: dict[str, Any] = {
            "debate_id": debate_id,
            "task": resolved_task,
            "confidence": resolved_confidence,
            "consensus_reached": self._debate_consensus_reached(debate_result),
            "final_answer": self._debate_final_answer(debate_result),
            "participants": [str(a) for a in (getattr(debate_result, "participants", []) or [])],
        }
        if cost_breakdown:
            payload["cost_summary"] = cost_breakdown
        return payload

    def _build_outcome_km_payload(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
        confidence: float,
        cost_breakdown: dict[str, Any] | None = None,
        decision_id: str | None = None,
    ) -> dict[str, Any]:
        """Build the outcome summary payload for OutcomeAdapter.ingest()."""
        resolved_task = str(task or getattr(debate_result, "task", ""))
        resolved_confidence = float(confidence or getattr(debate_result, "confidence", 0.0) or 0.0)
        consensus_reached = self._debate_consensus_reached(debate_result)
        final_answer = self._debate_final_answer(debate_result)
        outcome_type = "success" if consensus_reached else "partial"
        task_slug = self._task_slug(resolved_task)
        dissenting_views = [
            str(view) for view in (getattr(debate_result, "dissenting_views", []) or [])
        ]
        cruxes = [
            str(crux.get("claim", crux) if isinstance(crux, dict) else crux)
            for crux in (getattr(debate_result, "debate_cruxes", []) or [])
        ]

        lessons: list[str] = []
        if dissenting_views:
            lessons.append(f"Dissent preserved: {'; '.join(dissenting_views[:2])}")
        if cruxes:
            lessons.append(f"Debate cruxes: {'; '.join(cruxes[:2])}")
        if cost_breakdown and cost_breakdown.get("total_cost_usd") is not None:
            lessons.append(f"Debate cost captured: {cost_breakdown['total_cost_usd']} USD")

        return {
            "outcome_id": f"outcome-{debate_id}-{task_slug}",
            "decision_id": decision_id or debate_id,
            "debate_id": debate_id,
            "outcome_type": outcome_type,
            "outcome_description": (
                f"Debate outcome for '{resolved_task}': {final_answer}"
                if resolved_task
                else final_answer
            ),
            "impact_score": max(0.0, min(resolved_confidence, 1.0)),
            "kpis_before": {},
            "kpis_after": {},
            "lessons_learned": "\n".join(lessons),
            "tags": [
                "debate_completion",
                "institutional_memory",
                "decision_outcome",
                f"task:{task_slug}",
            ],
        }

    def _persist_receipt_summary_to_km(self, receipt_data: dict[str, Any]) -> bool:
        """Persist the canonical receipt summary through ReceiptAdapter."""
        try:
            from aragora.knowledge.mound.adapters.receipt_adapter import (
                get_receipt_adapter,
            )

            adapter = get_receipt_adapter()
            persisted = bool(adapter.ingest(receipt_data))
            if persisted:
                logger.info("Receipt persisted to KM for %s", receipt_data.get("debate_id", ""))
            return persisted
        except ImportError:
            logger.debug("ReceiptAdapter not available, skipping KM receipt persistence")
            return False
        except (ValueError, TypeError, OSError, AttributeError, KeyError) as e:
            logger.warning("Receipt KM persistence failed: %s", e)
            return False

    def _persist_outcome_summary_to_km(self, outcome_data: dict[str, Any]) -> bool:
        """Persist the canonical debate outcome through OutcomeAdapter."""
        try:
            from aragora.knowledge.mound.adapters.outcome_adapter import (
                get_outcome_adapter,
            )

            adapter = get_outcome_adapter()
            persisted = bool(adapter.ingest(outcome_data))
            if persisted:
                logger.info("Outcome persisted to KM for %s", outcome_data.get("debate_id", ""))
            return persisted
        except ImportError:
            logger.debug("OutcomeAdapter not available, skipping KM outcome persistence")
            return False
        except (ValueError, TypeError, OSError, AttributeError, KeyError) as e:
            logger.warning("Outcome KM persistence failed: %s", e)
            return False
