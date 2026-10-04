"""Post-Debate Coordinator - Orchestrates post-debate processing pipeline.

Sequences post-debate actions so each step can use outputs from previous steps:
  explanation -> plan -> notification -> execution

This replaces ad-hoc sequential calls with a structured pipeline where
context flows between steps and failures in one step don't cascade.

Usage:
    coordinator = PostDebateCoordinator(
        config=PostDebateConfig(
            auto_explain=True,
            auto_create_plan=True,
            auto_notify=True,
            auto_execute_plan=False,
        )
    )
    result = coordinator.run(debate_id, debate_result, agents)
    # result.explanation, result.plan, result.notification_sent, etc.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import threading
import uuid
from typing import Any

from aragora.debate.post_debate_config import PostDebateConfig, PostDebateResult
from aragora.pipeline.backbone_contracts import BackboneStage, RunLedger, RunStageEvent
from aragora.pipeline.execution_mode import ExecutionMode

logger = logging.getLogger(__name__)
# Per-step timeout for async callables run from the sync coordinator.
# Reduced from 30s to 10s: the coordinator now runs in a background thread
# (fire-and-forget) so individual steps should fail fast rather than stall.
ASYNC_RUN_TIMEOUT_SECONDS = float(os.getenv("ARAGORA_POST_DEBATE_ASYNC_TIMEOUT", "10.0"))


class PostDebateCoordinator:
    """Orchestrates post-debate processing in a structured pipeline.

    Runs configurable steps in sequence, passing context between them:
    1. Explanation: Generate decision rationale (ExplanationBuilder)
    2. Plan: Create implementation plan (DecisionPlanFactory)
    3. Notification: Send alerts via configured channels
    4. Execution: Execute approved plans (PlanExecutor)

    Each step is independent and failure-tolerant: a failed step
    records the error but doesn't prevent subsequent steps from running.
    """

    def __init__(
        self,
        config: PostDebateConfig | None = None,
        settlement_tracker: Any | None = None,
        knowledge_mound: Any | None = None,
    ):
        self.config = config or PostDebateConfig()
        self._settlement_tracker = settlement_tracker
        self._knowledge_mound = knowledge_mound
        self._ledger: RunLedger | None = None
        self._backbone_runtime: Any | None = None
        self._backbone_runtime_failed = False

    @staticmethod
    def _run_async_callable(async_fn: Any, /, *args: Any, **kwargs: Any) -> Any:
        """Run an async callable from sync code, including loop-owning contexts."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(async_fn(*args, **kwargs))

        result: dict[str, Any] = {}
        error: dict[str, Exception] = {}

        def _runner() -> None:
            try:
                result["value"] = asyncio.run(async_fn(*args, **kwargs))
            except Exception as exc:  # noqa: BLE001 - shuttle exact exception to caller
                error["error"] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join(timeout=ASYNC_RUN_TIMEOUT_SECONDS)

        if thread.is_alive():
            logger.warning(
                "_run_async_callable timed out after %ss",
                ASYNC_RUN_TIMEOUT_SECONDS,
            )
            return None

        if "error" in error:
            raise error["error"]
        return result.get("value")

    @staticmethod
    def _coerce_receipt_id(candidate: Any) -> str | None:
        """Normalize receipt IDs while ignoring mock objects and empty values."""
        if not isinstance(candidate, str):
            return None
        normalized = candidate.strip()
        return normalized or None

    def _get_settlement_tracker(self) -> Any:
        """Reuse an injected/shared settlement tracker when available."""
        if self._settlement_tracker is None:
            from aragora.debate.settlement import SettlementTracker

            self._settlement_tracker = SettlementTracker()
        return self._settlement_tracker

    def run(
        self,
        debate_id: str,
        debate_result: Any,
        agents: list[Any] | None = None,
        confidence: float = 0.0,
        task: str = "",
    ) -> PostDebateResult:
        """Run the post-debate processing pipeline.

        Args:
            debate_id: Unique identifier for the debate
            debate_result: The debate result object
            agents: List of participating agents
            confidence: Debate confidence score
            task: The debate task/question

        Returns:
            PostDebateResult with outputs from each pipeline step
        """
        result = PostDebateResult(debate_id=debate_id)
        result.run_id = self._seed_backbone_run(debate_id, debate_result, task)

        # Keep an in-memory ledger for traceability alongside persisted backbone writes.
        ledger = RunLedger(
            run_id=f"post-debate-{uuid.uuid4().hex[:12]}",
            entrypoint="post_debate_coordinator",
            debate_id=debate_id,
        )
        self._ledger = ledger

        # Step 0: Collect cost data (always attempted, used by downstream steps)
        result.cost_breakdown = self._step_collect_cost_data(debate_id, debate_result)

        # Step 1: Auto-generate explanation
        if self.config.auto_explain:
            result.explanation = self._step_explain(debate_id, debate_result, task)

        # Step 2: Create decision plan
        if self.config.auto_create_plan and confidence >= self.config.plan_min_confidence:
            result.plan = self._step_create_plan(debate_id, debate_result, task, result.explanation)
            self._record_backbone_plan(result.run_id, debate_id, result.plan)
            if result.plan is not None:
                plan_id = self._plan_id(self._plan_object(result.plan))
                ledger.plan_id = plan_id
                ledger.add_event(
                    RunStageEvent.create(
                        BackboneStage.PLAN,
                        status="plan_created",
                        details={"debate_id": debate_id, "plan_id": plan_id},
                    )
                )

        # Step 2.5: Gauntlet adversarial validation
        if self.config.auto_gauntlet_validate and confidence >= self.config.gauntlet_min_confidence:
            result.gauntlet_result = self._step_gauntlet_validate(
                debate_id, debate_result, task, confidence
            )

        # Step 2.7: Argument structure verification
        if self.config.auto_verify_arguments:
            result.argument_verification = self._step_argument_verification(
                debate_id, debate_result, task
            )

        # Step 2.75: Persist signed receipt BEFORE execution gate (trust-wedge).
        # The execution safety gate must validate a previously-persisted receipt
        # rather than building and signing one inline (attestation inversion fix).
        if self.config.auto_persist_receipt and self.config.require_persisted_receipt:
            receipt_id = self._step_persist_signed_receipt(
                debate_id,
                debate_result,
                task,
                confidence,
                cost_breakdown=result.cost_breakdown,
            )
            if receipt_id:
                result.receipt_persisted = True
                result.receipt_id = receipt_id
                self._record_backbone_receipt(result.run_id, receipt_id)

        # Step 2.8: Execution safety gate (signed receipts + diversity + taint checks)
        if self.config.enforce_execution_safety_gate:
            result.execution_gate = self._step_execution_gate(
                debate_result, agents, receipt_id=result.receipt_id
            )
            self._apply_execution_gate_to_plan(result.plan, result.execution_gate)

        # Step 3: Send notifications
        if self.config.auto_notify:
            result.notification_sent = self._step_notify(
                debate_id, debate_result, result.explanation, result.plan
            )

        # Step 4: Execute plan if approved
        if self.config.auto_execute_plan and result.plan:
            plan_id = ledger.plan_id or self._plan_id(self._plan_object(result.plan))
            ledger.plan_id = plan_id
            if self._is_execution_blocked(result.execution_gate):
                result.execution_result = {
                    "skipped": True,
                    "reason": "execution_gate_blocked",
                    "gate": result.execution_gate,
                }
                ledger.add_event(
                    RunStageEvent.create(
                        BackboneStage.EXECUTION,
                        status="execution_blocked",
                        details={"debate_id": debate_id, "plan_id": plan_id},
                    )
                )
            else:
                ledger.add_event(
                    RunStageEvent.create(
                        BackboneStage.EXECUTION,
                        status="execution_requested",
                        details={"debate_id": debate_id, "plan_id": plan_id},
                    )
                )
                result.execution_result = self._step_execute_plan(result.plan, result.explanation)
            self._record_backbone_execution(
                result.run_id,
                result.plan,
                result.execution_result,
                execution_gate=result.execution_gate,
            )
            if not self._is_execution_blocked(result.execution_gate):
                ledger.add_event(
                    RunStageEvent.create(
                        BackboneStage.EXECUTION,
                        status="execution_completed",
                        details={"debate_id": debate_id, "plan_id": plan_id},
                    )
                )

        # Step 4.5: Create draft PR for code-related debates
        if (
            self.config.auto_create_pr
            and result.plan
            and confidence >= self.config.pr_min_confidence
        ):
            if self._is_execution_blocked(result.execution_gate):
                result.pr_result = {
                    "skipped": True,
                    "reason": "execution_gate_blocked",
                    "gate": result.execution_gate,
                }
            else:
                result.pr_result = self._step_create_pr(result.plan, task)

        # Step 5: Build decision integrity package
        if self.config.auto_build_integrity_package:
            result.integrity_package = self._step_build_integrity_package(debate_id, debate_result)

        # Step 6: Persist receipt to Knowledge Mound (the flywheel)
        # Skip if already persisted in step 2.75 (trust-wedge path)
        if self.config.auto_persist_receipt and not result.receipt_persisted:
            result.receipt_persisted = self._step_persist_receipt(
                debate_id,
                debate_result,
                task,
                confidence,
                cost_breakdown=result.cost_breakdown,
            )

        # Step 6.5: Ingest debate outcome into Knowledge Mound (read-write feedback loop)
        if (
            self.config.auto_ingest_outcome
            and confidence >= self.config.ingest_outcome_min_confidence
        ):
            result.outcome_ingested = self._step_ingest_outcome(debate_id, debate_result, task)

        # Step 7: Queue improvement suggestion
        if (
            self.config.auto_queue_improvement
            and confidence >= self.config.improvement_min_confidence
        ):
            result.improvement_queued = self._step_queue_improvement(
                debate_id, debate_result, task, confidence
            )

        # Step 7.5: Push calibration data to ERC-8004 blockchain reputation
        if self.config.auto_push_calibration:
            self._step_push_calibration(debate_id, agents)

        # Step 7.6: Staking rewards/penalties based on epistemic accuracy
        if self.config.enable_staking:
            result.staking_result = self._step_staking_rewards(
                debate_id, debate_result, agents, confidence
            )

        # Step 7.6a: Anchor receipt hash on blockchain (ERC-8004)
        if self.config.auto_anchor_receipt:
            result.receipt_settlement = self._step_anchor_receipt(debate_id, debate_result)

        # Step 7.6b: Sync ELO rating changes to ERC-8004 ReputationRegistry
        if self.config.auto_sync_elo_reputation:
            self._step_elo_reputation_sync(debate_id, agents, debate_result)

        # Step 7.7: Outcome feedback — feed systematic errors to Nomic Loop
        if self.config.auto_outcome_feedback:
            result.outcome_feedback = self._step_outcome_feedback(debate_id)

        # Step 7.9: Settlement tracking — extract verifiable claims for future resolution
        if self.config.auto_settlement_tracking:
            result.settlement_batch = self._step_settlement_tracking(
                debate_id,
                debate_result,
                receipt_id=(
                    result.receipt_id
                    or self._coerce_receipt_id(getattr(debate_result, "receipt_id", None))
                ),
            )

        # Step 8.5: Canvas pipeline — auto-trigger idea-to-execution visualization
        if self.config.auto_trigger_canvas and confidence >= self.config.canvas_min_confidence:
            result.canvas_result = self._step_trigger_canvas(debate_id, debate_result, task)
            if result.canvas_result:
                result.pipeline_id = result.canvas_result.get("pipeline_id")

        # Step 8.7: LLM-as-Judge — evaluate agent contributions
        if self.config.auto_llm_judge:
            result.llm_judge_scores = self._step_llm_judge(
                debate_id,
                debate_result,
                task,
                agents,
            )

        # Step 8: Execution bridge — auto-trigger downstream actions
        if (
            self.config.auto_execution_bridge
            and confidence >= self.config.execution_bridge_min_confidence
        ):
            if self._is_execution_blocked(result.execution_gate):
                logger.warning(
                    "Execution bridge blocked by execution gate debate_id=%s reasons=%s",
                    debate_id,
                    (result.execution_gate or {}).get("reason_codes", []),
                )
            else:
                bridge_results = self._step_execution_bridge(
                    debate_id,
                    debate_result,
                    task,
                    confidence,
                    agents,
                )
                result.bridge_results = bridge_results

        # Step 8.1: Decision bridge — route plan to Jira/Linear/n8n
        if (
            result.plan
            and self.config.auto_execution_bridge
            and not self._is_execution_blocked(result.execution_gate)
        ):
            decision_bridge_result = self._step_decision_bridge(result.plan)
            if decision_bridge_result:
                result.bridge_results.append(decision_bridge_result)

        return result

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

    def _seed_backbone_run(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
    ) -> str | None:
        """Ensure post-debate processing has a RunLedger anchor."""
        runtime = self._get_backbone_runtime()
        if runtime is None:
            return None

        metadata = getattr(debate_result, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            try:
                setattr(debate_result, "metadata", metadata)
            except (AttributeError, TypeError):
                pass

        existing_run_id = str(metadata.get("backbone_run_id", "") or "").strip()
        if existing_run_id:
            metadata.setdefault("backbone_entrypoint", "post_debate_coordinator.run")
            return existing_run_id

        if not hasattr(runtime, "create_run"):
            self._backbone_failure(
                "Post-debate backbone runtime does not support run creation for seeded ledgers"
            )
            return None

        try:
            from aragora.pipeline.backbone_contracts import (
                DeliberationBundle,
                IntakeBundle,
                RunLedger,
            )

            resolved_task = str(task or getattr(debate_result, "task", "") or "").strip()
            intake = IntakeBundle(
                source_kind="post_debate_coordinator",
                raw_intent=resolved_task,
                context_refs=[{"kind": "debate", "id": debate_id}] if debate_id else [],
                trust_tiers=["service-authored"],
                origin_metadata={"debate_id": debate_id},
            )
            try:
                deliberation = DeliberationBundle.from_debate_result(debate_result)
            except (ValueError, TypeError, AttributeError):
                deliberation = DeliberationBundle(
                    debate_id=debate_id,
                    verdict=self._debate_final_answer(debate_result),
                    confidence=float(getattr(debate_result, "confidence", 0.0) or 0.0),
                    consensus_reached=self._debate_consensus_reached(debate_result),
                )

            run_id = f"run-{uuid.uuid4().hex[:12]}"
            runtime.create_run(
                RunLedger(
                    run_id=run_id,
                    entrypoint="post_debate_coordinator.run",
                    status="deliberation_completed",
                    intake_bundle=intake,
                    deliberation_bundle=deliberation,
                    debate_id=debate_id,
                    taint_flags=list(intake.taint_flags) + list(deliberation.taint_flags),
                    metadata={
                        "source_surface": "post_debate_coordinator",
                        "execution_mode": self.config.execution_mode.value,
                    },
                )
            )
            if hasattr(runtime, "append_stage_event"):
                self._ensure_backbone_write(
                    runtime.append_stage_event(
                        run_id,
                        "intake",
                        status="completed",
                        artifact_ref=debate_id,
                    ),
                    "Post-debate intake stage was not persisted",
                )
                self._ensure_backbone_write(
                    runtime.append_stage_event(
                        run_id,
                        "deliberation",
                        status="completed",
                        artifact_ref=debate_id,
                    ),
                    "Post-debate deliberation stage was not persisted",
                )
            metadata["backbone_run_id"] = run_id
            metadata["backbone_entrypoint"] = "post_debate_coordinator.run"
            return run_id
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            self._backbone_failure(f"Post-debate backbone seed failed for {debate_id}", e)
            return None

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

    def _is_execution_blocked(self, gate: dict[str, Any] | None) -> bool:
        """Return True when execution gate exists and denies auto-execution."""
        if not gate:
            return False
        return not bool(gate.get("allow_auto_execution", True))

    def _step_execution_gate(
        self,
        debate_result: Any,
        agents: list[Any] | None = None,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate execution safety gate for high-impact automation."""
        try:
            from aragora.debate.execution_safety import (
                ExecutionSafetyPolicy,
                evaluate_auto_execution_safety,
            )

            policy = ExecutionSafetyPolicy(
                require_verified_signed_receipt=(
                    self.config.execution_gate_require_verified_signed_receipt
                ),
                require_receipt_signer_allowlist=(
                    self.config.execution_gate_enforce_receipt_signer_allowlist
                ),
                allowed_receipt_signer_keys=(
                    self.config.execution_gate_allowed_receipt_signer_keys
                ),
                require_signed_receipt_timestamp=(
                    self.config.execution_gate_require_signed_receipt_timestamp
                ),
                receipt_max_age_seconds=self.config.execution_gate_receipt_max_age_seconds,
                receipt_max_future_skew_seconds=(
                    self.config.execution_gate_receipt_max_future_skew_seconds
                ),
                min_provider_diversity=self.config.execution_gate_min_provider_diversity,
                min_model_family_diversity=self.config.execution_gate_min_model_family_diversity,
                block_on_context_taint=self.config.execution_gate_block_on_context_taint,
                block_on_high_severity_dissent=(
                    self.config.execution_gate_block_on_high_severity_dissent
                ),
                high_severity_dissent_threshold=(
                    self.config.execution_gate_high_severity_dissent_threshold
                ),
            )

            decision = evaluate_auto_execution_safety(
                debate_result,
                agents=agents,
                policy=policy,
                receipt_id=receipt_id,
            )
            gate = decision.to_dict()
            try:
                from aragora.observability.server_metrics import track_execution_gate_decision

                track_execution_gate_decision(
                    gate,
                    path="post_debate_coordinator",
                    domain=str(getattr(debate_result, "domain", "general") or "general"),
                )
            except ImportError:
                logger.debug("Execution gate metrics unavailable")
            except (ValueError, TypeError, AttributeError, RuntimeError):
                logger.debug("Execution gate metrics emission failed", exc_info=True)
            if not gate.get("allow_auto_execution", True):
                logger.warning(
                    "execution_gate_blocked reasons=%s",
                    gate.get("reason_codes", []),
                )
            return gate
        except ImportError:
            logger.debug("Execution safety gate unavailable")
            return {"allow_auto_execution": False, "reason_codes": ["gate_unavailable"]}
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Execution safety gate failed closed: %s", e)
            return {"allow_auto_execution": False, "reason_codes": ["gate_evaluation_failed"]}

    def _apply_execution_gate_to_plan(
        self,
        plan_data: dict[str, Any] | None,
        gate: dict[str, Any] | None,
    ) -> None:
        """Force manual approval when execution gate blocks automation."""
        if not plan_data or not self._is_execution_blocked(gate):
            return

        plan_obj = plan_data.get("plan")
        if plan_obj is None:
            return

        try:
            from aragora.pipeline.decision_plan.core import ApprovalMode, PlanStatus

            if not isinstance(getattr(plan_obj, "metadata", None), dict):
                setattr(plan_obj, "metadata", {})
            plan_obj.metadata["execution_gate"] = gate
            plan_obj.approval_mode = ApprovalMode.ALWAYS
            plan_obj.status = PlanStatus.AWAITING_APPROVAL
        except ImportError:
            logger.debug("DecisionPlan core unavailable for gate plan enforcement")
        except (ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("Failed to apply execution gate to plan: %s", e)

    def _step_explain(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
    ) -> dict[str, Any] | None:
        """Step 1: Generate decision explanation."""
        try:
            from aragora.explainability.builder import ExplanationBuilder

            builder = ExplanationBuilder()
            decision = self._run_async_callable(builder.build, result=debate_result)
            explanation = builder.generate_summary(decision)

            logger.info("Post-debate explanation generated for %s", debate_id)
            return {
                "debate_id": debate_id,
                "explanation": explanation,
                "decision": decision.to_dict() if hasattr(decision, "to_dict") else {},
                "task": task,
            }
        except ImportError:
            logger.debug("ExplanationBuilder not available")
            return None
        except (ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("Explanation generation failed: %s", e)
            return None

    def _step_create_plan(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
        explanation: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Step 2: Create decision plan, enriched with explanation context.

        When a BackboneRuntime is available the plan is persisted through its
        PlanStore and annotated with the backbone run_id so downstream stages
        (execution, receipt, feedback) can correlate back to the same ledger
        entry.
        """
        try:
            from aragora.pipeline.decision_plan.factory import DecisionPlanFactory

            # Include explanation in plan metadata if available
            metadata = {"debate_id": debate_id, "task": task}
            if explanation:
                metadata["explanation"] = explanation.get("explanation", "")

            plan = DecisionPlanFactory.from_debate_result(
                debate_result,
                metadata=metadata,
            )

            # Wire plan through BackboneRuntime for persistence & metadata.
            runtime = self._get_backbone_runtime()
            if runtime is not None:
                try:
                    # Stamp backbone run_id onto the plan so execution and
                    # receipt stages can look it up from the plan object alone.
                    run_id = self._current_run_id(debate_result)
                    if run_id:
                        from aragora.pipeline.backbone_runtime import BackboneRuntime as _BR

                        _BR.ensure_plan_metadata(plan, run_id, "post_debate_coordinator.run")

                    # Persist the full plan object into the backbone PlanStore.
                    if hasattr(runtime, "plan_store"):
                        store = runtime.plan_store
                        if hasattr(store, "create"):
                            store.create(plan)
                            logger.debug(
                                "Plan %s persisted via backbone for debate %s",
                                getattr(plan, "id", "?"),
                                debate_id,
                            )
                except (
                    ImportError,
                    ValueError,
                    TypeError,
                    AttributeError,
                    RuntimeError,
                    OSError,
                ) as e:
                    # Best-effort: plan creation succeeded, persistence is bonus.
                    self._backbone_failure(f"Backbone plan persistence failed for {debate_id}", e)

            logger.info("Decision plan created for %s", debate_id)
            return {
                "debate_id": debate_id,
                "plan": plan,
                "has_explanation_context": explanation is not None,
            }
        except ImportError:
            logger.debug("DecisionPlanFactory not available")
            return None
        except (ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("Plan creation failed: %s", e)
            return None

    def _step_notify(
        self,
        debate_id: str,
        debate_result: Any,
        explanation: dict[str, Any] | None,
        plan: dict[str, Any] | None,
    ) -> bool:
        """Step 3: Send notifications with full context from prior steps."""
        try:
            from aragora.notifications.service import notify_debate_completed

            # Build notification with context from prior steps
            extra_context: dict[str, Any] = {}
            if explanation:
                extra_context["has_explanation"] = True
            if plan:
                extra_context["has_plan"] = True
                plan_obj = plan.get("plan")
                if plan_obj and hasattr(plan_obj, "status"):
                    extra_context["plan_status"] = str(plan_obj.status)

            import asyncio

            coro = notify_debate_completed(
                debate_id=debate_id,
                task=getattr(debate_result, "task", ""),
                verdict=str(getattr(debate_result, "final_answer", "")),
                confidence=getattr(debate_result, "confidence", 0.0),
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(coro)
            except RuntimeError:
                asyncio.run(coro)

            logger.info("Post-debate notification sent for %s", debate_id)
            return True
        except ImportError:
            logger.debug("Notification service not available")
            return False
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError, ConnectionError) as e:
            logger.warning("Notification failed: %s", e)
            return False

    def _step_execute_plan(
        self,
        plan_data: dict[str, Any],
        explanation: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Step 4: Execute approved plan, using explanation as issue body context."""
        try:
            from aragora.pipeline.executor import PlanExecutor

            executor = PlanExecutor()
            plan_obj = plan_data.get("plan")
            if not plan_obj:
                return None

            # Check if plan is approved
            status = getattr(plan_obj, "status", None)
            if status and str(status).lower() != "approved":
                logger.info("Plan not approved, skipping execution")
                return {"skipped": True, "reason": f"status={status}"}

            result = executor.execute_to_github_issue(plan_obj)
            logger.info("Plan executed: %s", result)
            return result
        except ImportError:
            logger.debug("PlanExecutor not available")
            return None
        except (
            ValueError,
            TypeError,
            AttributeError,
            RuntimeError,
            OSError,
            ConnectionError,
            KeyError,
        ) as e:
            logger.warning("Plan execution failed: %s", e)
            return None

    def _step_create_pr(
        self,
        plan_data: dict[str, Any],
        task: str,
    ) -> dict[str, Any] | None:
        """Step 4.5: Create a draft PR for code-related debate outcomes."""
        try:
            from aragora.pipeline.executor import PlanExecutor

            executor = PlanExecutor()
            plan_obj = plan_data.get("plan")
            if not plan_obj:
                return None

            result = executor.execute_to_github_pr(plan_obj, draft=True)
            logger.info("Draft PR created for task: %s", task[:80])
            return result
        except ImportError:
            logger.debug("PlanExecutor not available for PR creation")
            return None
        except (RuntimeError, ValueError, OSError, KeyError) as e:
            logger.warning("PR creation failed: %s", e)
            return None

    def _step_build_integrity_package(
        self,
        debate_id: str,
        debate_result: Any,
    ) -> dict[str, Any] | None:
        """Step 5: Build a DecisionIntegrityPackage from the debate result."""
        try:
            from aragora.core_types import DebateResult
            from aragora.pipeline.decision_integrity import build_integrity_package_from_result

            # Coerce to DebateResult if needed
            if isinstance(debate_result, DebateResult):
                dr = debate_result
            else:
                dr = DebateResult(
                    debate_id=debate_id,
                    task=str(getattr(debate_result, "task", "")),
                    final_answer=str(
                        getattr(
                            debate_result, "final_answer", getattr(debate_result, "consensus", "")
                        )
                    ),
                    confidence=float(getattr(debate_result, "confidence", 0.0)),
                    consensus_reached=bool(getattr(debate_result, "consensus", None)),
                    participants=[
                        str(a) for a in (getattr(debate_result, "participants", []) or [])
                    ],
                )

            package = build_integrity_package_from_result(
                dr,
                include_receipt=True,
                include_plan=False,
            )

            logger.info("Decision integrity package built for %s", debate_id)
            return package.to_dict()
        except ImportError:
            logger.debug("Decision integrity pipeline not available")
            return None
        except (ValueError, TypeError, AttributeError, RuntimeError, KeyError) as e:
            logger.warning("Integrity package generation failed: %s", e)
            return None

    def _step_persist_receipt(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
        confidence: float,
        cost_breakdown: dict[str, Any] | None = None,
    ) -> bool:
        """Step 6: Persist debate completion memory to Knowledge Mound.

        This reuses the canonical receipt/outcome adapters so debate completion
        writes both a receipt summary and an outcome summary into Knowledge
        Mound as institutional memory.

        Args:
            debate_id: Unique identifier for the debate.
            debate_result: The debate result object.
            task: The debate task/question.
            confidence: Debate confidence score.
            cost_breakdown: Optional per-debate cost breakdown dict from
                _step_collect_cost_data().
        """
        receipt_persisted = self._persist_receipt_summary_to_km(
            self._build_receipt_km_payload(
                debate_id=debate_id,
                debate_result=debate_result,
                task=task,
                confidence=confidence,
                cost_breakdown=cost_breakdown,
            )
        )
        self._persist_outcome_summary_to_km(
            self._build_outcome_km_payload(
                debate_id=debate_id,
                debate_result=debate_result,
                task=task,
                confidence=confidence,
                cost_breakdown=cost_breakdown,
            )
        )
        return receipt_persisted

    def _step_ingest_outcome(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
    ) -> bool:
        """Step 6.5: Ingest debate outcome into Knowledge Mound.

        Stores the consensus conclusion and metadata from high-confidence
        debates into the Knowledge Mound for future retrieval, closing the
        read-write feedback loop.

        Args:
            debate_id: Unique identifier for the debate.
            debate_result: The debate result object.
            task: The debate task/question.
        """
        if not self._knowledge_mound:
            return False

        try:
            from aragora.core import Environment
            from aragora.debate.knowledge_mound_ops import KnowledgeMoundOperations

            ops = KnowledgeMoundOperations(
                knowledge_mound=self._knowledge_mound,
                enable_ingestion=True,
            )
            env = Environment(task=task) if task else None
            self._run_async_callable(ops.ingest_debate_outcome, debate_result, env=env)
            logger.info(
                "post_debate_outcome_ingested debate_id=%s",
                debate_id,
            )
            return True
        except (ImportError, RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.warning(
                "post_debate_outcome_ingestion_failed debate_id=%s error=%s",
                debate_id,
                type(e).__name__,
            )
            return False

    def _step_persist_signed_receipt(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
        confidence: float,
        cost_breakdown: dict[str, Any] | None = None,
    ) -> str | None:
        """Persist a *fully signed* DecisionReceipt before the execution gate.

        This fixes the attestation inversion: the execution safety gate must
        validate a previously-persisted receipt rather than building and
        signing one inline. After the durable receipt store write succeeds,
        the same canonical KM receipt/outcome bridge is reused for memory
        writeback.

        Returns the ``receipt_id`` on success, ``None`` on failure.
        """
        try:
            from aragora.gauntlet.receipt_models import DecisionReceipt
            from aragora.gauntlet.receipt_store import ReceiptState, get_receipt_store
            from aragora.gauntlet.signing import get_default_signer

            # Build a full DecisionReceipt from the debate result
            receipt = DecisionReceipt.from_debate_result(
                debate_result,
                cost_summary=cost_breakdown,
            )

            # Sign with the durable signer
            signer = get_default_signer()
            receipt.sign(signer)

            # Build the dict to persist (includes signature fields)
            receipt_dict = receipt.to_dict()

            # Persist to the receipt store
            store = get_receipt_store()
            store.persist(
                receipt_id=receipt.receipt_id,
                receipt_data=receipt_dict,
                signature=receipt.signature,
                signature_key_id=receipt.signature_key_id,
                signed_at=receipt.signed_at,
                signature_algorithm=receipt.signature_algorithm,
                state=ReceiptState.CREATED,
            )

            # Auto-approve if no manual approval is required
            store.transition(receipt.receipt_id, ReceiptState.APPROVED)

            self._persist_receipt_summary_to_km(
                self._build_receipt_km_payload(
                    debate_id=debate_id,
                    debate_result=debate_result,
                    task=task,
                    confidence=confidence,
                    cost_breakdown=cost_breakdown,
                )
            )
            self._persist_outcome_summary_to_km(
                self._build_outcome_km_payload(
                    debate_id=debate_id,
                    debate_result=debate_result,
                    task=task,
                    confidence=confidence,
                    cost_breakdown=cost_breakdown,
                    decision_id=receipt.receipt_id,
                )
            )

            logger.info("Signed receipt persisted: %s (debate=%s)", receipt.receipt_id, debate_id)
            return receipt.receipt_id

        except ImportError:
            logger.debug("Receipt models/store not available, skipping signed persistence")
            return None
        except (ValueError, TypeError, OSError, AttributeError, KeyError, RuntimeError) as e:
            logger.warning("Signed receipt persistence failed: %s", e)
            return None

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

    def _step_collect_cost_data(
        self,
        debate_id: str,
        debate_result: Any,
    ) -> dict[str, Any] | None:
        """Step 0: Collect per-debate cost data for inclusion in receipts.

        Attempts to pull cost data from the DebateCostTracker singleton
        (rich per-agent/per-round/per-model breakdowns).  Falls back to
        lightweight cost fields on the debate result object itself.

        Returns None when no cost data is available (graceful degradation).

        Args:
            debate_id: Unique identifier for the debate.
            debate_result: The debate result object.

        Returns:
            Cost breakdown dict or None if cost tracking is unavailable.
        """
        # Primary source: DebateCostTracker singleton (has per-agent, per-round, per-model)
        try:
            from aragora.billing.debate_costs import get_debate_cost_tracker

            tracker = get_debate_cost_tracker()
            summary = tracker.get_debate_cost(debate_id)
            if summary and summary.total_calls > 0:
                logger.debug(
                    "Cost data collected from DebateCostTracker for %s: $%s",
                    debate_id,
                    summary.total_cost_usd,
                )
                return summary.to_dict()
        except ImportError:
            logger.debug("DebateCostTracker not available")
        except (RuntimeError, ValueError, TypeError, AttributeError) as e:
            logger.debug("DebateCostTracker query failed (non-critical): %s", e)

        # Fallback: build minimal summary from DebateResult fields
        try:
            total_cost = float(getattr(debate_result, "total_cost_usd", 0.0) or 0.0)
            per_agent_cost = getattr(debate_result, "per_agent_cost", None)
            if not isinstance(per_agent_cost, dict):
                per_agent_cost = {}

            if total_cost > 0 or per_agent_cost:
                logger.debug(
                    "Cost data collected from DebateResult fields for %s: $%s",
                    debate_id,
                    total_cost,
                )
                return {
                    "debate_id": debate_id,
                    "total_cost_usd": str(total_cost),
                    "total_tokens_in": 0,
                    "total_tokens_out": 0,
                    "total_calls": 0,
                    "per_agent": {
                        name: {"agent_name": name, "total_cost_usd": str(cost)}
                        for name, cost in per_agent_cost.items()
                    },
                    "per_round": {},
                    "model_usage": {},
                }
        except (TypeError, ValueError, AttributeError):
            pass

        logger.debug("No cost data available for %s", debate_id)
        return None

    def _step_gauntlet_validate(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
        confidence: float,
    ) -> dict[str, Any] | None:
        """Step 2.5: Run lightweight adversarial stress test on high-confidence decisions."""
        try:
            from aragora.gauntlet.runner import GauntletRunner

            runner = GauntletRunner()
            input_content = str(
                getattr(debate_result, "final_answer", getattr(debate_result, "consensus", ""))
            )
            verdict = self._run_async_callable(
                runner.run,
                input_content=input_content,
                context=task,
            )

            logger.info(
                "Gauntlet validation completed for %s: %s",
                debate_id,
                getattr(verdict, "verdict", "unknown"),
            )
            return {
                "debate_id": debate_id,
                "verdict": verdict,
            }
        except ImportError:
            logger.debug("GauntletRunner not available")
            return None
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError, ConnectionError) as e:
            logger.warning("Gauntlet validation failed: %s", e)
            return None

    def _step_argument_verification(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
    ) -> dict[str, Any] | None:
        """Step 2.7: Verify logical structure of debate argument chains.

        Builds an argument graph from debate messages and runs formal
        verification to detect invalid chains, contradictions, circular
        dependencies, and unsupported conclusions.
        """
        try:
            from aragora.verification.argument_verifier import (
                ArgumentStructureVerifier,
            )
            from aragora.visualization.mapper import ArgumentCartographer
        except ImportError:
            logger.debug("ArgumentStructureVerifier not available for debate %s", debate_id)
            return None

        try:
            # Build argument graph from debate messages
            graph = ArgumentCartographer()
            graph.set_debate_context(debate_id, task)

            messages = getattr(debate_result, "messages", [])
            if isinstance(messages, list):
                for msg in messages:
                    agent = getattr(msg, "agent", "unknown")
                    content = getattr(msg, "content", "")
                    role = getattr(msg, "role", "proposal")
                    round_num = getattr(msg, "round", 0) or 0
                    if content:
                        graph.update_from_message(
                            agent=str(agent),
                            content=str(content),
                            role=str(role),
                            round_num=int(round_num),
                        )

            if not graph.nodes:
                logger.debug("No argument nodes to verify for debate %s", debate_id)
                return None

            verifier = ArgumentStructureVerifier()
            verification_result = self._run_async_callable(verifier.verify, graph)

            logger.info(
                "Argument verification completed for %s: soundness=%s",
                debate_id,
                verification_result.soundness_score,
            )
            return {
                "debate_id": debate_id,
                "verification": verification_result.to_dict(),
                "is_sound": verification_result.is_sound,
                "soundness_score": verification_result.soundness_score,
            }
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Argument verification failed for %s: %s", debate_id, e)
            return None

    def _step_queue_improvement(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
        confidence: float,
    ) -> bool:
        """Step 7: Queue improvement suggestion for self-improvement pipeline."""
        try:
            from aragora.nomic.improvement_queue import (
                ImprovementSuggestion,
                get_improvement_queue,
            )

            consensus = str(
                getattr(
                    debate_result,
                    "final_answer",
                    getattr(debate_result, "consensus", ""),
                )
            )
            if not consensus:
                return False

            category = self._classify_improvement_category(task)

            suggestion = ImprovementSuggestion(
                debate_id=debate_id,
                task=task,
                suggestion=consensus,
                category=category,
                confidence=confidence,
            )

            queue = get_improvement_queue()
            queue.enqueue(suggestion)
            logger.info("Improvement suggestion queued for %s (category=%s)", debate_id, category)
            return True
        except ImportError:
            logger.debug("ImprovementQueue not available")
            return False
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError, KeyError) as e:
            logger.warning("Improvement queue failed: %s", e)
            return False

    def _step_execution_bridge(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
        confidence: float,
        agents: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Step 8: Run execution bridge to auto-trigger downstream actions."""
        try:
            from aragora.debate.execution_bridge import create_default_bridge

            bridge = create_default_bridge()
            agent_names = [getattr(a, "name", str(a)) for a in (agents or [])]
            domain = "general"
            if hasattr(debate_result, "domain"):
                domain = debate_result.domain

            results = bridge.evaluate_and_execute(
                debate_id=debate_id,
                debate_result=debate_result,
                confidence=confidence,
                domain=domain,
                task=task,
                agents=agent_names,
            )

            executed = [r.to_dict() for r in results]
            if executed:
                logger.info(
                    "Execution bridge triggered %d actions for %s",
                    len(executed),
                    debate_id,
                )
            return executed
        except ImportError:
            logger.debug("ExecutionBridge not available")
            return []
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Execution bridge failed: %s", e)
            return []

    def _step_decision_bridge(self, plan: dict[str, Any]) -> dict[str, Any] | None:
        """Route decision plan to external project management tools."""
        try:
            from aragora.integrations.decision_bridge import DecisionBridge

            bridge = DecisionBridge()
            bridge_result = self._run_async_callable(bridge.handle_decision_plan, plan)
            if bridge_result:
                result_dict = (
                    bridge_result.to_dict() if hasattr(bridge_result, "to_dict") else bridge_result
                )
                logger.info("Decision bridge completed: %s", result_dict)
                return {"type": "decision_bridge", **result_dict}
            return None
        except ImportError:
            logger.debug("DecisionBridge not available")
            return None
        except (ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning("Decision bridge failed: %s", e)
            return None

    def _step_push_calibration(
        self,
        debate_id: str,
        agents: list[Any] | None = None,
    ) -> bool:
        """Step 7.5: Push agent calibration scores to ERC-8004 blockchain reputation.

        For each agent with sufficient prediction history, converts Brier score
        to a reputation signal and pushes it to the on-chain registry.
        """
        try:
            from aragora.knowledge.mound.adapters.erc8004_adapter import ERC8004Adapter

            adapter = ERC8004Adapter()
            pushed = 0

            for agent in agents or []:
                agent_name = getattr(agent, "name", str(agent))
                calibration_tracker = getattr(agent, "calibration_tracker", None)
                if calibration_tracker is None:
                    continue

                # Get calibration data
                cal_data = None
                if hasattr(calibration_tracker, "get_calibration"):
                    cal_data = calibration_tracker.get_calibration(agent_name)
                elif hasattr(calibration_tracker, "get_calibration_score"):
                    cal_data = {
                        "brier_score": calibration_tracker.get_calibration_score(agent_name)
                    }

                if not cal_data:
                    continue

                prediction_count = cal_data.get("prediction_count", cal_data.get("count", 0))
                if prediction_count < self.config.calibration_min_predictions:
                    continue

                brier = cal_data.get("brier_score", cal_data.get("brier", 1.0))
                # Convert Brier score (0=perfect, 1=worst) to reputation (0-100)
                reputation = max(0, min(100, int((1.0 - brier) * 100)))

                adapter.push_reputation(
                    agent_id=agent_name,
                    score=reputation,
                    domain="calibration",
                    metadata={
                        "debate_id": debate_id,
                        "brier_score": brier,
                        "prediction_count": prediction_count,
                    },
                )
                pushed += 1

            if pushed:
                logger.info(
                    "Pushed calibration reputation for %d agents (debate %s)",
                    pushed,
                    debate_id,
                )
            return pushed > 0
        except ImportError:
            logger.debug("ERC8004Adapter not available, skipping calibration push")
            return False
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Calibration push failed: %s", e)
            return False

    def _step_staking_rewards(
        self,
        debate_id: str,
        debate_result: Any,
        agents: list[Any] | None = None,
        confidence: float = 0.0,
    ) -> dict[str, Any] | None:
        """Step 7.6: Distribute staking rewards/penalties based on epistemic accuracy.

        Agents that contributed to high-confidence, accurate outcomes receive rewards.
        Agents involved in hollow consensus (detected by Trickster) face slashing.
        """
        try:
            from aragora.blockchain.contracts.staking import StakingRegistry

            registry = StakingRegistry()
            results: dict[str, Any] = {"rewarded": [], "slashed": [], "debate_id": debate_id}

            # Check for hollow consensus (Trickster detection)
            hollow_consensus = False
            if hasattr(debate_result, "metadata") and isinstance(debate_result.metadata, dict):
                hollow_consensus = debate_result.metadata.get("hollow_consensus_detected", False)

            for agent in agents or []:
                agent_name = getattr(agent, "name", str(agent))

                if hollow_consensus and self.config.staking_slash_on_hollow_consensus:
                    # Slash agents that participated in hollow consensus
                    try:
                        position = self._run_async_callable(registry.get_stake, agent_name)
                        if position is None:
                            logger.debug("Agent %s has no stake, skipping slash", agent_name)
                            continue
                        slash_amount = max(
                            1,
                            int(position.effective_stake * 0.10 * self.config.staking_reward_scale),
                        )
                        evidence_bytes = json.dumps(
                            {
                                "debate_id": debate_id,
                                "confidence": confidence,
                                "hollow_consensus": True,
                            }
                        ).encode()
                        # Anchor evidence on-chain before slashing for traceability
                        anchor_id = self._anchor_slash_evidence(
                            debate_id, agent_name, evidence_bytes
                        )
                        self._run_async_callable(
                            registry.slash,
                            agent_name,
                            slash_amount,
                            "hollow_consensus",
                            evidence_bytes,
                        )
                        slashed_entry = {"agent": agent_name, "amount": slash_amount}
                        if anchor_id:
                            slashed_entry["evidence_anchor"] = anchor_id
                        results["slashed"].append(slashed_entry)
                    except (RuntimeError, ValueError, OSError) as e:
                        logger.warning("Slash failed for %s: %s", agent_name, e)
                elif confidence >= 0.8:
                    # Reward agents contributing to high-confidence outcomes
                    reward_amount = int(100 * confidence * self.config.staking_reward_scale)
                    try:
                        self._run_async_callable(
                            registry.reward,
                            agent_name,
                            reward_amount,
                            "high_confidence_contribution",
                        )
                        results["rewarded"].append({"agent": agent_name, "amount": reward_amount})
                    except (RuntimeError, ValueError, OSError) as e:
                        logger.warning("Reward failed for %s: %s", agent_name, e)

            if results["rewarded"] or results["slashed"]:
                logger.info(
                    "Staking: rewarded %d, slashed %d agents (debate %s)",
                    len(results["rewarded"]),
                    len(results["slashed"]),
                    debate_id,
                )
            return results
        except ImportError:
            logger.debug("StakingRegistry not available, skipping staking rewards")
            return None
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Staking rewards failed: %s", e)
            return None

    def _step_elo_reputation_sync(
        self,
        debate_id: str,
        agents: list[Any] | None = None,
        debate_result: Any = None,
    ) -> bool:
        """Step 7.6b: Sync ELO rating adjustments to ERC-8004 ReputationRegistry.

        Reads Trickster ELO adjustments and agent ELO ratings from the debate
        result metadata, then pushes them to the on-chain ReputationRegistry
        via the ERC8004Adapter.
        """
        try:
            from aragora.knowledge.mound.adapters.erc8004_adapter import ERC8004Adapter

            adapter = ERC8004Adapter()
            synced = 0

            # Extract ELO adjustments from metadata if available
            elo_adjustments: dict[str, float] = {}
            if (
                debate_result
                and hasattr(debate_result, "metadata")
                and isinstance(debate_result.metadata, dict)
            ):
                elo_adjustments = debate_result.metadata.get("elo_adjustments", {})

            for agent in agents or []:
                agent_name = getattr(agent, "name", str(agent))
                # Get ELO rating from agent if available
                elo_rating = None
                elo_system = getattr(agent, "elo_system", None)
                if elo_system and hasattr(elo_system, "get_rating"):
                    elo_rating = elo_system.get_rating(agent_name)

                adjustment = elo_adjustments.get(agent_name, 0.0)

                if elo_rating is not None or adjustment != 0.0:
                    # Convert ELO (typically 800-1200) to reputation (0-100)
                    reputation = 50  # neutral default
                    if elo_rating is not None:
                        reputation = max(0, min(100, int((elo_rating - 800) / 4)))

                    adapter.push_reputation(
                        agent_id=agent_name,
                        score=reputation,
                        domain="elo",
                        metadata={
                            "debate_id": debate_id,
                            "elo_rating": elo_rating,
                            "adjustment": adjustment,
                        },
                    )
                    synced += 1

            if synced:
                logger.info(
                    "Synced ELO reputation for %d agents (debate %s)",
                    synced,
                    debate_id,
                )
            return synced > 0
        except ImportError:
            logger.debug("ERC8004Adapter not available, skipping ELO reputation sync")
            return False
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("ELO reputation sync failed: %s", e)
            return False

    def _anchor_slash_evidence(
        self,
        debate_id: str,
        agent_name: str,
        evidence_bytes: bytes,
    ) -> str | None:
        """Anchor slash evidence via ReceiptAnchor for on-chain traceability.

        Returns the anchor ID (local or tx_hash) on success, None on failure.
        Failure does NOT block the slash — it's best-effort anchoring.
        """
        try:
            from aragora.blockchain.receipt_anchor import ReceiptAnchor

            evidence_hash = hashlib.sha256(evidence_bytes).hexdigest()
            anchor = ReceiptAnchor()
            anchor_id = self._run_async_callable(
                anchor.anchor_receipt,
                evidence_hash,
                {"debate_id": debate_id, "agent": agent_name, "type": "slash_evidence"},
            )
            logger.debug("Anchored slash evidence for %s: %s", agent_name, anchor_id)
            return anchor_id
        except (ImportError, RuntimeError, ValueError, OSError, TypeError) as e:
            logger.debug("Evidence anchoring unavailable: %s", e)
            return None

    def _step_anchor_receipt(
        self,
        debate_id: str,
        debate_result: Any,
    ) -> dict[str, Any] | None:
        """Step 7.6a: Anchor receipt hash on blockchain via ERC-8004.

        Creates a DecisionReceipt from the debate result (if one exists in
        metadata), then anchors its content hash on-chain. Falls back to
        local anchoring when no chain is configured.

        Returns a settlement status dict or None on failure.
        """
        try:
            from aragora.blockchain.receipt_settlement import ReceiptSettlementService

            # Try to find or build a receipt from the debate result
            receipt = self._extract_receipt_from_result(debate_result)
            if receipt is None:
                logger.debug("No receipt available for anchoring in debate %s", debate_id)
                return None

            service = ReceiptSettlementService()
            anchored = self._run_async_callable(service.anchor_receipt, receipt)
            status = getattr(anchored, "settlement_status", None)
            if status:
                logger.info(
                    "Receipt anchored for debate %s: local=%s",
                    debate_id,
                    status.get("local_only", True),
                )
            return status
        except (ImportError, RuntimeError, ValueError, OSError, TypeError) as e:
            logger.debug("Receipt anchoring unavailable: %s", e)
            return None

    def _extract_receipt_from_result(self, debate_result: Any) -> Any:
        """Extract or build a DecisionReceipt from a debate result.

        Looks for a receipt in the result's metadata, or builds a minimal one
        from the result's fields.
        """
        # Check if the result already has a receipt attached
        receipt = getattr(debate_result, "receipt", None)
        if receipt is not None:
            return receipt

        # Check metadata for a receipt dict
        metadata = getattr(debate_result, "metadata", {}) or {}
        receipt_data = metadata.get("receipt")
        if isinstance(receipt_data, dict):
            try:
                from aragora.gauntlet.receipt_models import DecisionReceipt

                return DecisionReceipt.from_dict(receipt_data)
            except (ValueError, TypeError, KeyError):
                pass

        return None

    def _step_outcome_feedback(
        self,
        debate_id: str,
    ) -> dict[str, Any] | None:
        """Step 7.7: Run outcome feedback cycle to detect systematic errors.

        Analyzes outcome patterns across past debates and queues
        improvement goals for the Nomic Loop MetaPlanner.
        """
        try:
            from aragora.nomic.outcome_feedback import OutcomeFeedbackBridge

            bridge = OutcomeFeedbackBridge()
            cycle_result = bridge.run_feedback_cycle()

            if cycle_result.get("goals_generated", 0) > 0:
                logger.info(
                    "Outcome feedback: %d goals generated, %d queued (debate %s)",
                    cycle_result["goals_generated"],
                    cycle_result["suggestions_queued"],
                    debate_id,
                )
            return cycle_result
        except ImportError:
            logger.debug("OutcomeFeedbackBridge not available, skipping outcome feedback")
            return None
        except (ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.debug("Outcome feedback failed (non-critical): %s", e)
            return None

    def _step_settlement_tracking(
        self,
        debate_id: str,
        debate_result: Any,
        receipt_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Step 7.9: Extract verifiable claims for future settlement.

        Scans the debate result for claims that contain measurable predictions,
        registers them in the SettlementTracker for later resolution, keeping
        a truthful link to the persisted debate receipt when one exists.
        """
        try:
            tracker = self._get_settlement_tracker()
            batch = tracker.extract_verifiable_claims(
                debate_id=debate_id,
                debate_result=debate_result,
                min_confidence=self.config.settlement_min_confidence,
                domain=self.config.settlement_domain,
                receipt_id=receipt_id,
            )

            if batch.settlements_created > 0:
                logger.info(
                    "Settlement tracking: %d claims registered from debate %s",
                    batch.settlements_created,
                    debate_id,
                )
            return batch.to_dict()
        except ImportError:
            logger.debug("SettlementTracker not available, skipping settlement tracking")
            return None
        except (ValueError, TypeError, AttributeError, RuntimeError) as e:
            logger.debug("Settlement tracking failed (non-critical): %s", e)
            return None

    def _step_trigger_canvas(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
    ) -> dict[str, Any] | None:
        """Step 8.5: Trigger idea-to-execution canvas pipeline from debate result.

        Converts the debate's argument graph into a visual canvas pipeline,
        progressing through ideas -> goals -> actions -> orchestration stages.
        Uses ArgumentCartographer when available, falls back to
        _build_cartographer_data for lightweight conversion.
        """
        try:
            from aragora.pipeline.idea_to_execution import IdeaToExecutionPipeline
        except ImportError:
            logger.debug("Canvas pipeline not available")
            return None

        try:
            # Try ArgumentCartographer first for richer graph
            export_data = None
            try:
                from aragora.visualization.mapper import ArgumentCartographer

                cartographer = ArgumentCartographer()
                cartographer.set_debate_context(debate_id, task)

                messages = getattr(debate_result, "messages", [])
                if isinstance(messages, list):
                    for msg in messages:
                        agent = getattr(msg, "agent", "unknown")
                        content = getattr(msg, "content", "")
                        role = getattr(msg, "role", "proposal")
                        round_num = getattr(msg, "round", 0) or 0
                        if content:
                            cartographer.update_from_message(
                                agent=str(agent),
                                content=str(content),
                                role=str(role),
                                round_num=int(round_num),
                            )

                if cartographer.nodes:
                    export_data = cartographer.to_dict()
            except (ImportError, AttributeError, TypeError, RuntimeError):
                pass

            # Fallback: build cartographer data directly from debate result
            if not export_data:
                export_data = self._build_cartographer_data(debate_result)

            if not export_data.get("nodes"):
                logger.debug("No argument nodes for canvas pipeline (debate %s)", debate_id)
                return None

            pipeline = IdeaToExecutionPipeline()
            pipeline_result = pipeline.from_debate(
                cartographer_data=export_data,
                auto_advance=True,
            )

            pipeline_id = getattr(pipeline_result, "pipeline_id", None)
            logger.info(
                "post_debate_canvas_pipeline debate_id=%s pipeline_id=%s",
                debate_id,
                pipeline_id,
            )
            return {
                "debate_id": debate_id,
                "pipeline_id": pipeline_id,
                "stages_completed": [
                    k
                    for k, v in getattr(pipeline_result, "stage_status", {}).items()
                    if v == "complete"
                ],
            }
        except (ImportError, ValueError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Canvas pipeline auto-trigger failed: %s", e)
            return None

    def _step_llm_judge(
        self,
        debate_id: str,
        debate_result: Any,
        task: str,
        agents: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        """Step 8.7: Evaluate agent contributions via LLM-as-Judge.

        Uses LLMJudge to score each agent's final response across multiple
        quality dimensions, then feeds scores to the ELO system.
        """
        try:
            from aragora.evaluation.llm_judge import LLMJudge, JudgeConfig
        except ImportError:
            logger.debug("LLMJudge not available")
            return None

        try:
            config = JudgeConfig(
                use_case=self.config.llm_judge_use_case,
                pass_threshold=self.config.llm_judge_threshold,
            )
            judge = LLMJudge(config)

            # Extract per-agent responses from the debate result
            agent_responses: dict[str, str] = {}
            messages = getattr(debate_result, "messages", []) or []
            for msg in messages:
                agent_name = str(getattr(msg, "agent", ""))
                content = getattr(msg, "content", "")
                if agent_name and content:
                    # Keep last response per agent
                    agent_responses[agent_name] = str(content)

            if not agent_responses:
                logger.debug("No agent responses to evaluate for %s", debate_id)
                return None

            scores: dict[str, Any] = {}

            for agent_name, response in agent_responses.items():
                try:
                    evaluation = self._run_async_callable(
                        judge.evaluate,
                        query=task,
                        response=response,
                        response_id=f"{debate_id}:{agent_name}",
                    )
                    overall = getattr(evaluation, "overall_score", 0.0)
                    raw_dims = getattr(evaluation, "dimension_scores", {})
                    serialized_dims = (
                        {
                            (d.value if hasattr(d, "value") else str(d)): (
                                s.score if hasattr(s, "score") else float(s)
                            )
                            for d, s in raw_dims.items()
                        }
                        if raw_dims
                        else {}
                    )
                    scores[agent_name] = {
                        "overall": overall,
                        "dimensions": serialized_dims,
                    }
                except (RuntimeError, ValueError, TypeError) as exc:
                    logger.debug("LLMJudge eval failed for %s: %s", agent_name, exc)

            # Feed scores to ELO system
            if scores:
                try:
                    from aragora.ranking.elo import EloSystem

                    elo = EloSystem()
                    for agent_name, score_data in scores.items():
                        elo.record_quality_score(
                            agent_name=agent_name,
                            debate_id=debate_id,
                            score=score_data["overall"],
                            dimension_scores=score_data.get("dimensions"),
                        )
                except (ImportError, RuntimeError, ValueError) as exc:
                    logger.debug("ELO quality score recording skipped: %s", exc)

            # Feed judge scores into SelectionFeedbackLoop for agent weight adjustment
            if scores:
                try:
                    from aragora.debate.selection_feedback import SelectionFeedbackLoop

                    feedback_loop = SelectionFeedbackLoop()
                    # Determine winner as highest-scoring agent
                    best_agent = max(scores, key=lambda a: scores[a]["overall"])
                    feedback_loop.process_debate_outcome(
                        debate_id=f"{debate_id}_llm_judge",
                        participants=list(scores.keys()),
                        winner=best_agent,
                        domain=self.config.llm_judge_use_case,
                    )
                    logger.debug(
                        "llm_judge_selection_feedback debate=%s best_agent=%s",
                        debate_id,
                        best_agent,
                    )
                except (ImportError, RuntimeError, ValueError, TypeError) as exc:
                    logger.debug("Selection feedback from LLM judge skipped: %s", exc)

            logger.info(
                "llm_judge_evaluated debate=%s agents=%d",
                debate_id,
                len(scores),
            )
            return {"debate_id": debate_id, "agent_scores": scores}

        except (RuntimeError, ValueError, TypeError, OSError) as e:
            logger.warning("LLM judge evaluation failed: %s", e)
            return None
        except Exception as e:  # noqa: BLE001 - optional post-debate step must not crash debate
            logger.warning("LLM judge evaluation failed (unexpected): %s: %s", type(e).__name__, e)
            return None

    @staticmethod
    def _build_cartographer_data(debate_result: Any) -> dict[str, Any]:
        """Convert DebateResult into ArgumentCartographer-compatible data.

        Extracts proposals, evidence, critiques, and consensus from the
        debate result and formats them as cartographer nodes/edges.
        """
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        # Extract from messages
        messages = getattr(debate_result, "messages", []) or []
        for i, msg in enumerate(messages):
            node_type = "proposal"
            content = getattr(msg, "content", str(msg))
            agent = getattr(msg, "agent", "unknown")
            round_num = getattr(msg, "round", 0)

            # Classify message type based on content/metadata
            msg_type = getattr(msg, "type", None) or getattr(msg, "message_type", None)
            if msg_type:
                type_str = str(msg_type).lower()
                if "critique" in type_str or "counter" in type_str:
                    node_type = "critique"
                elif "evidence" in type_str or "support" in type_str:
                    node_type = "evidence"
                elif "consensus" in type_str or "agree" in type_str:
                    node_type = "consensus"

            node_id = f"debate-msg-{i}"
            nodes.append(
                {
                    "id": node_id,
                    "type": node_type,
                    "summary": content[:100] if content else "",
                    "content": content or "",
                    "agent": agent,
                    "round": round_num,
                }
            )

        # Extract from consensus/final decision
        consensus = getattr(debate_result, "consensus", None)
        if consensus:
            consensus_text = (
                getattr(consensus, "text", None)
                or getattr(consensus, "summary", None)
                or str(consensus)
            )
            nodes.append(
                {
                    "id": "debate-consensus",
                    "type": "consensus",
                    "summary": consensus_text[:100],
                    "content": consensus_text,
                }
            )

        # Build edges: sequential message flow
        for i in range(1, len(nodes)):
            edges.append(
                {
                    "source_id": nodes[i - 1]["id"],
                    "target_id": nodes[i]["id"],
                    "relation": "responds_to",
                }
            )

        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def _classify_improvement_category(task: str) -> str:
        """Classify improvement category from task text."""
        task_lower = task.lower()
        if any(w in task_lower for w in ("test", "coverage", "assertion")):
            return "test_coverage"
        if any(w in task_lower for w in ("perf", "speed", "latency", "slow")):
            return "performance"
        if any(w in task_lower for w in ("reliab", "resilien", "fault", "retry")):
            return "reliability"
        if any(w in task_lower for w in ("doc", "readme", "comment")):
            return "documentation"
        return "code_quality"


DEFAULT_POST_DEBATE_CONFIG = PostDebateConfig(
    execution_mode=ExecutionMode.AUTONOMOUS,
    auto_explain=True,
    auto_create_plan=False,
    auto_notify=False,
    auto_execute_plan=False,
    auto_create_pr=False,
    auto_build_integrity_package=False,
    auto_persist_receipt=True,
    auto_gauntlet_validate=True,
    auto_push_calibration=True,
    auto_queue_improvement=True,
    auto_outcome_feedback=True,
    auto_ingest_outcome=True,
)


__all__ = [
    "PostDebateCoordinator",
    "PostDebateConfig",
    "PostDebateResult",
    "DEFAULT_POST_DEBATE_CONFIG",
]
