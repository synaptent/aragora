"""Runtime helpers for canonical RunLedger side effects.

This module centralizes run-ledger mutations that were previously spread
across handlers, orchestrators, and execution bridges. Persistence stays in
``PlanStore`` while this service owns the higher-level runtime wiring:
stage events, trust/taint gate lookup, receipt mirroring, feedback, and
shadow attestation.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from aragora.pipeline.backbone_contracts import (
    BackboneStage,
    OutcomeFeedbackRecord,
    ReceiptEnvelope,
    RunLedger,
    RunStageEvent,
    TaintChecker,
)

if TYPE_CHECKING:
    from aragora.pipeline.decision_plan import PlanOutcome
    from aragora.pipeline.plan_store import PlanStore
    from aragora.pipeline.receipt_gate import PlanExecutionGateDecision

logger = logging.getLogger(__name__)


class BackboneRuntime:
    """Service layer for RunLedger runtime mutations."""

    def __init__(self, plan_store: PlanStore | None = None) -> None:
        self._plan_store = plan_store

    @property
    def plan_store(self) -> PlanStore:
        if self._plan_store is None:
            from aragora.pipeline.plan_store import get_plan_store

            self._plan_store = get_plan_store()
        return self._plan_store

    def create_run(
        self,
        run: RunLedger,
        *,
        org_id: str | None = None,
        created_by: str | None = None,
    ) -> None:
        self.plan_store.create_run(run, org_id=org_id, created_by=created_by)

    def get_run(self, run_id: str) -> RunLedger | None:
        return self.plan_store.get_run(run_id)

    def update_run(self, run_id: str, **kwargs: Any) -> bool:
        return self.plan_store.update_run(run_id, **kwargs)

    def append_stage_event(
        self,
        run_id: str,
        stage: BackboneStage | str,
        *,
        status: str,
        artifact_ref: str = "",
        details: dict[str, Any] | None = None,
    ) -> bool:
        if not run_id:
            return False
        return self.plan_store.append_run_stage_event(
            run_id,
            RunStageEvent.create(
                stage,
                status=status,
                artifact_ref=artifact_ref,
                details=details,
            ),
        )

    @staticmethod
    def ensure_plan_metadata(plan: Any, run_id: str, entrypoint: str) -> None:
        metadata = getattr(plan, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            setattr(plan, "metadata", metadata)
        metadata.setdefault("backbone_run_id", run_id)
        metadata.setdefault("backbone_entrypoint", entrypoint)

    def evaluate_execution_gate(self, plan: Any) -> PlanExecutionGateDecision:
        from aragora.pipeline.receipt_gate import evaluate_plan_execution_gate

        return evaluate_plan_execution_gate(plan, plan_store=self.plan_store)

    def sync_plan_receipt_to_run(
        self,
        plan: Any,
        *,
        append_event: bool = False,
    ) -> bool:
        metadata = getattr(plan, "metadata", None)
        if not isinstance(metadata, dict):
            return False

        run_id = str(metadata.get("backbone_run_id", "") or "").strip()
        if not run_id:
            return False

        receipt_meta = metadata.get("decision_receipt")
        receipt_id = ""
        if isinstance(receipt_meta, dict):
            receipt_id = str(receipt_meta.get("receipt_id", "") or "").strip()
        if not receipt_id:
            receipt_id = str(metadata.get("decision_receipt_id", "") or "").strip()
        if not receipt_id:
            return False

        try:
            from aragora.pipeline.receipt_store_facade import get_receipt_store_facade

            canonical = get_receipt_store_facade().get_canonical(receipt_id)
        except (ImportError, RuntimeError, OSError, TypeError, ValueError) as exc:
            logger.warning("Backbone receipt fetch failed for %s: %s", receipt_id, exc)
            return False

        if not isinstance(canonical, dict):
            return False

        receipt_payload = canonical.get("receipt_data")
        if isinstance(receipt_payload, dict):
            receipt_payload = dict(receipt_payload)
            receipt_payload.setdefault("receipt_id", receipt_id)
            receipt_payload.setdefault("signature", canonical.get("signature"))
            receipt_payload.setdefault("signature_key_id", canonical.get("signature_key_id"))
            receipt_payload.setdefault("signed_at", canonical.get("signed_at"))
            receipt_payload.setdefault("signature_algorithm", canonical.get("signature_algorithm"))
            receipt_payload["state"] = canonical.get("state", receipt_payload.get("state"))
        else:
            receipt_payload = canonical

        if not isinstance(receipt_payload, dict):
            return False

        run = self.get_run(run_id)
        taint_summary = TaintChecker.collect_taint_summary(
            intake=getattr(run, "intake_bundle", None),
            spec=getattr(run, "spec_bundle", None),
            deliberation=getattr(run, "deliberation_bundle", None),
            verification=getattr(run, "receipt_envelope", None),
        )
        gate = metadata.get("execution_gate")
        envelope = ReceiptEnvelope.from_decision_receipt(
            receipt_payload,
            policy_gate_result=dict(gate or {}) if isinstance(gate, dict) else {},
            taint_summary=taint_summary,
        )
        updated = self.update_run(
            run_id,
            receipt_id=receipt_id,
            receipt_envelope=envelope,
            metadata={"plan_receipt_state": str(receipt_payload.get("state", "")).lower()},
        )
        if append_event:
            appended = self.append_stage_event(
                run_id,
                BackboneStage.RECEIPT,
                status=str(receipt_payload.get("state", "created") or "created").lower(),
                artifact_ref=receipt_id,
                details={"source": "plan_status_transition", "plan_id": getattr(plan, "id", "")},
            )
            return updated and appended
        return updated

    def record_execution_stage(
        self,
        run_id: str,
        *,
        status: str,
        artifact_ref: str = "",
        run_status: str | None = None,
        execution_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        if not run_id:
            return False

        update_kwargs: dict[str, Any] = {}
        if run_status is not None:
            update_kwargs["status"] = run_status
        if execution_id is not None:
            update_kwargs["execution_id"] = execution_id
        if metadata:
            update_kwargs["metadata"] = metadata
        updated = True
        if update_kwargs:
            updated = self.update_run(run_id, **update_kwargs)
            if not updated:
                return False

        return updated and self.append_stage_event(
            run_id,
            BackboneStage.EXECUTION,
            status=status,
            artifact_ref=artifact_ref,
            details=details,
        )

    def build_feedback_record(
        self,
        plan: Any,
        outcome: PlanOutcome,
        *,
        receipt_ref: str,
        execution_mode: str,
    ) -> OutcomeFeedbackRecord:
        quality_score = 1.0 if outcome.success else 0.25
        metadata = getattr(plan, "metadata", None)
        pipeline_like = SimpleNamespace(
            pipeline_id=getattr(plan, "id", ""),
            run_type="decision_plan_execution",
            domain=metadata.get("domain", "") if isinstance(metadata, dict) else "",
            overall_quality_score=quality_score,
            spec_completeness=1.0 if outcome.success else 0.5,
            execution_succeeded=outcome.success,
            tests_passed=int(getattr(outcome, "tests_passed", 0) or 0),
            tests_failed=int(getattr(outcome, "tests_failed", 0) or 0),
            files_changed=int(getattr(outcome, "files_changed", 0) or 0),
            human_interventions=0,
            rollback_triggered=bool(getattr(outcome, "rollback_triggered", False)),
            total_duration_s=outcome.duration_seconds,
        )
        next_action = ""
        if not outcome.success and int(getattr(outcome, "tests_failed", 0) or 0) > 0:
            next_action = "run_bug_fix_loop"
        return OutcomeFeedbackRecord.from_pipeline_outcome(
            pipeline_like,
            receipt_ref=receipt_ref or getattr(plan, "id", ""),
            next_action_recommendation=next_action,
        )

    async def attach_execution_receipt(
        self,
        run_id: str,
        plan: Any,
        outcome: PlanOutcome,
    ) -> str:
        from aragora.blockchain.receipt_settlement import ReceiptSettlementService
        from aragora.gauntlet.receipt_models import DecisionReceipt
        from aragora.pipeline.canonical_execution import build_decision_receipt_payload

        if not run_id:
            return str(getattr(outcome, "receipt_id", "") or getattr(plan, "id", ""))

        run = self.get_run(run_id)
        receipt_payload = build_decision_receipt_payload(plan, outcome)
        receipt_ref = str(getattr(outcome, "receipt_id", "") or getattr(plan, "id", ""))

        if not isinstance(receipt_payload, dict):
            return receipt_ref

        taint_summary = TaintChecker.collect_taint_summary(
            intake=getattr(run, "intake_bundle", None),
            spec=getattr(run, "spec_bundle", None),
            deliberation=getattr(run, "deliberation_bundle", None),
            verification=getattr(run, "receipt_envelope", None),
        )
        metadata = getattr(plan, "metadata", None)
        gate = metadata.get("execution_gate", {}) if isinstance(metadata, dict) else {}
        envelope = ReceiptEnvelope.from_decision_receipt(
            receipt_payload,
            policy_gate_result=dict(gate or {}),
            taint_summary=taint_summary,
        )
        receipt_ref = envelope.receipt_id or receipt_ref
        self.update_run(
            run_id,
            receipt_id=receipt_ref,
            receipt_envelope=envelope,
        )
        self.append_stage_event(
            run_id,
            BackboneStage.RECEIPT,
            status="completed",
            artifact_ref=receipt_ref,
            details={"source": "decision_plan_execution"},
        )

        try:
            settled_receipt = await ReceiptSettlementService().anchor_receipt(
                DecisionReceipt.from_dict(receipt_payload)
            )
            attestation = getattr(settled_receipt, "settlement_status", None)
            if isinstance(attestation, dict):
                self.update_run(run_id, attestation=attestation)
                self.append_stage_event(
                    run_id,
                    BackboneStage.ATTESTATION,
                    status="completed",
                    artifact_ref=receipt_ref,
                    details=attestation,
                )
        except (ImportError, RuntimeError, ConnectionError, OSError, TypeError, ValueError) as exc:
            logger.warning("Backbone shadow attestation failed for %s: %s", receipt_ref, exc)

        return receipt_ref

    def attach_feedback_record(
        self,
        run_id: str,
        feedback_record: OutcomeFeedbackRecord,
        *,
        artifact_ref: str = "",
        details: dict[str, Any] | None = None,
    ) -> bool:
        if not run_id:
            return False
        updated = self.update_run(run_id, feedback_record=feedback_record)
        if not updated:
            return False
        payload = {"next_action": feedback_record.next_action_recommendation}
        if details:
            payload.update(details)
        return updated and self.append_stage_event(
            run_id,
            BackboneStage.FEEDBACK,
            status="completed",
            artifact_ref=artifact_ref or feedback_record.receipt_ref,
            details=payload,
        )


__all__ = ["BackboneRuntime"]
