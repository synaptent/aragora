"""Workflow construction for ``AutonomousOrchestrator``.

``AutonomousWorkflowMixin`` holds the methods that turn an agent assignment
into a ``WorkflowDefinition``: the default per-subtask workflow, the
risk-aware workflow built from a ``DecisionPlan``, and the two static helpers
they use. ``AutonomousOrchestrator`` inherits the mixin, so
``HardenedOrchestrator``'s ``super()._build_subtask_workflow`` call and
``BranchCoordinator``'s ``AutonomousOrchestrator._infer_test_paths`` call
resolve to the same functions as before.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from aragora.observability import get_logger
from aragora.workflow.types import StepDefinition, WorkflowDefinition

if TYPE_CHECKING:
    from pathlib import Path

    from aragora.nomic.agent_router import AgentRouter
    from aragora.nomic.types import AgentAssignment, HierarchyConfig, Track, TrackConfig

# The facade's logger name, so records from these methods keep the name that
# log filters and caplog assertions already use.
logger = get_logger("aragora.nomic.autonomous_orchestrator")


class AutonomousWorkflowMixin:
    """Workflow-building methods of ``AutonomousOrchestrator``."""

    # Set by AutonomousOrchestrator.__init__.
    aragora_path: Path
    track_configs: dict[Track, TrackConfig]
    branch_coordinator: Any
    hierarchy: HierarchyConfig
    router: AgentRouter
    use_harness: bool
    enable_gauntlet_gate: bool
    use_decision_plan: bool

    @staticmethod
    def _extract_hints(feedback: dict[str, Any]) -> list[str]:
        """Extract actionable hints from a FeedbackLoop analysis result.

        Normalizes hints into a flat list of strings so they can be injected
        into the next retry's workflow inputs.
        """
        hints: list[str] = []
        raw = feedback.get("hints", [])
        if isinstance(raw, str):
            hints.append(raw)
        elif isinstance(raw, list):
            for h in raw:
                if isinstance(h, str):
                    hints.append(h)
                elif isinstance(h, dict):
                    # Rich hint from testfixer (has file, line, error, suggestion)
                    parts = []
                    if h.get("file"):
                        parts.append(h["file"])
                    if h.get("line"):
                        parts.append(f"line {h['line']}")
                    if h.get("error"):
                        parts.append(h["error"])
                    if h.get("suggestion"):
                        parts.append(f"Fix: {h['suggestion']}")
                    hints.append(": ".join(parts) if parts else str(h))
        if feedback.get("reason"):
            hints.insert(0, feedback["reason"])
        return hints

    def _build_subtask_workflow(self, assignment: AgentAssignment) -> WorkflowDefinition:
        """Build a workflow definition for a subtask.

        Uses the gold path: agent(design) -> implementation -> verification.

        The "implementation" step type bridges to HybridExecutor which spawns
        Claude/Codex subprocesses to write code. The "verification" step type
        runs pytest against the changed files.
        """
        subtask = assignment.subtask

        # Check if agent needs a coding harness (e.g., KiloCode for Gemini)
        coding_harness = self.router.get_coding_harness(
            assignment.agent_type,
            assignment.track,
        )

        # Resolve repo path: prefer worktree path for isolation
        repo_path = self.aragora_path
        if self.branch_coordinator is not None:
            # Look up if this assignment's track has a worktree
            for branch, wt_path in getattr(self.branch_coordinator, "_worktree_paths", {}).items():
                if assignment.track.value in branch:
                    repo_path = wt_path
                    break

        # Build implementation step config matching ImplementationStep's expected format
        implement_config: dict[str, Any] = {
            "task_id": subtask.id,
            "description": subtask.description,
            "files": subtask.file_scope,
            "complexity": subtask.estimated_complexity,
            "repo_path": str(repo_path),
        }

        # If agent needs a coding harness, add it to the config
        if coding_harness:
            implement_config["coding_harness"] = coding_harness
            logger.info(
                "subtask_using_kilocode agent=%s provider=%s track=%s",
                assignment.agent_type,
                coding_harness["provider_id"],
                assignment.track.value,
            )

        # Derive test paths from file scope for verification
        test_paths = self._infer_test_paths(subtask.file_scope)

        # Create workflow with phases aligned to nomic loop gold path
        #
        # With hierarchy enabled, the workflow becomes:
        #   design (planner) -> plan_approval (judge) -> [gauntlet] -> implement (worker)
        #   -> verify -> judge_review (judge)
        #
        # With gauntlet gate enabled (no hierarchy):
        #   design -> gauntlet -> implement -> verify
        #
        # Without either:
        #   design -> implement -> verify

        hierarchy_enabled = self.hierarchy.enabled

        # Determine the step that follows design (before implement)
        # Priority: plan_approval (hierarchy) > gauntlet > implement
        if hierarchy_enabled:
            design_next = ["plan_approval"]
        elif self.enable_gauntlet_gate:
            design_next = ["gauntlet"]
        else:
            design_next = ["implement"]

        # The step that feeds into implement
        if self.enable_gauntlet_gate and hierarchy_enabled:
            plan_approval_next = ["gauntlet"]
        elif hierarchy_enabled:
            plan_approval_next = ["implement"]
        else:
            plan_approval_next = ["implement"]

        # Override agent types when hierarchy is active
        design_agent = self.hierarchy.planner_agent if hierarchy_enabled else assignment.agent_type
        implement_agent = assignment.agent_type
        if hierarchy_enabled and self.hierarchy.worker_agents:
            # Pick the first worker agent that matches the track, or fallback to first
            implement_agent = self.hierarchy.worker_agents[0]
            for wa in self.hierarchy.worker_agents:
                if wa in (
                    config.agent_types
                    if (config := self.track_configs.get(assignment.track))
                    else []
                ):
                    implement_agent = wa
                    break

        steps = [
            StepDefinition(
                id="design",
                name="Design Solution",
                step_type="agent",
                config={
                    "agent_type": design_agent,
                    "prompt_template": "design",
                    "task": subtask.description,
                },
                next_steps=design_next,
            ),
        ]

        if hierarchy_enabled:
            steps.append(
                StepDefinition(
                    id="plan_approval",
                    name="Plan Approval Gate",
                    step_type="agent",
                    config={
                        "agent_type": self.hierarchy.judge_agent,
                        "prompt_template": "review",
                        "task": (
                            f"Review the design plan for: {subtask.description}\n\n"
                            "Evaluate the plan for:\n"
                            "1. Feasibility: Can this be implemented as described?\n"
                            "2. Completeness: Are all edge cases addressed?\n"
                            "3. Risk: Are there security or correctness risks?\n\n"
                            "Respond with APPROVE or REJECT (with reasons)."
                        ),
                        "gate": True,
                        "blocking": self.hierarchy.plan_gate_blocking,
                        "max_revisions": self.hierarchy.max_plan_revisions,
                    },
                    next_steps=plan_approval_next,
                )
            )

        # Insert gauntlet adversarial validation step between design and implement
        if self.enable_gauntlet_gate:
            # Use stricter threshold for high-complexity subtasks
            severity_threshold = "medium" if subtask.estimated_complexity == "high" else "high"
            steps.append(
                StepDefinition(
                    id="gauntlet",
                    name="Adversarial Validation",
                    step_type="gauntlet",
                    config={
                        "input_key": "content",
                        "severity_threshold": severity_threshold,
                        "require_passing": True,
                        "attack_categories": [
                            "prompt_injection",
                            "hallucination",
                            "safety",
                        ],
                        "probe_categories": [
                            "reasoning",
                            "consistency",
                        ],
                    },
                    next_steps=["implement"],
                )
            )

        steps.append(
            StepDefinition(
                id="implement",
                name="Implement Changes",
                step_type="implementation",
                config={
                    **implement_config,
                    "agent_type": implement_agent,
                },
                next_steps=["verify"],
            ),
        )

        verify_next = (
            ["harness_scan"]
            if self.use_harness
            else (["judge_review"] if hierarchy_enabled else [])
        )
        steps.append(
            StepDefinition(
                id="verify",
                name="Verify Changes",
                step_type="verification",
                config={
                    "run_tests": True,
                    "test_paths": test_paths,
                    "test_count": len(test_paths),
                },
                next_steps=verify_next,
            ),
        )

        # Harness scan: run code analysis for security/quality after tests pass
        if self.use_harness:
            harness_next = ["judge_review"] if hierarchy_enabled else []
            steps.append(
                StepDefinition(
                    id="harness_scan",
                    name="Harness Security/Quality Scan",
                    step_type="harness_analysis",
                    config={
                        "analysis_types": ["security", "quality"],
                        "file_scope": subtask.file_scope or [],
                        "fail_on_critical": True,
                    },
                    next_steps=harness_next,
                ),
            )

        if hierarchy_enabled:
            steps.append(
                StepDefinition(
                    id="judge_review",
                    name="Judge Final Review",
                    step_type="agent",
                    config={
                        "agent_type": self.hierarchy.judge_agent,
                        "prompt_template": "review",
                        "task": (
                            f"Final review for: {subtask.description}\n\n"
                            "Review the implementation and verification results.\n"
                            "Check that the implementation matches the approved plan.\n"
                            "Respond with APPROVE or REJECT (with reasons)."
                        ),
                        "gate": True,
                        "blocking": self.hierarchy.final_review_blocking,
                    },
                    next_steps=[],
                )
            )

        return WorkflowDefinition(
            id=f"subtask_{subtask.id}",
            name=f"Execute: {subtask.title}",
            description=subtask.description,
            steps=steps,
            entry_step="design",
        )

    @staticmethod
    def _infer_test_paths(file_scope: list[str]) -> list[str]:
        """Infer test file paths from source file paths.

        Maps source files like ``aragora/foo/bar.py`` to
        ``tests/foo/test_bar.py`` if no explicit test paths are provided.
        """
        test_paths: list[str] = []
        for path in file_scope:
            if path.startswith("tests/"):
                test_paths.append(path)
                continue
            # aragora/foo/bar.py -> tests/foo/test_bar.py
            if path.startswith("aragora/"):
                rel = path[len("aragora/") :]
                parts = rel.rsplit("/", 1)
                if len(parts) == 2:
                    directory, filename = parts
                    if filename.endswith(".py"):
                        test_file = f"tests/{directory}/test_{filename}"
                        test_paths.append(test_file)
        return test_paths

    # =========================================================================
    # DecisionPlan integration
    # =========================================================================

    def _build_workflow_from_plan(
        self,
        assignment: AgentAssignment,
        debate_result: Any,
    ) -> WorkflowDefinition | None:
        """Build a risk-aware workflow using DecisionPlanFactory.

        When ``use_decision_plan`` is enabled and a debate result is available,
        creates a DecisionPlan which includes risk assessment, verification
        plan, and approval routing based on risk level.

        Returns None if the factory is unavailable or the debate result is
        missing, in which case the caller should fall back to
        ``_build_subtask_workflow``.
        """
        if not self.use_decision_plan or debate_result is None:
            return None

        try:
            from aragora.pipeline.decision_plan.factory import DecisionPlanFactory
            from aragora.pipeline.decision_plan.core import ApprovalMode

            plan = DecisionPlanFactory.from_debate_result(
                debate_result,
                approval_mode=ApprovalMode.RISK_BASED,
                repo_path=self.aragora_path,
            )

            # Convert the plan's implement tasks to workflow steps
            steps: list[StepDefinition] = []
            if plan.implement_plan and plan.implement_plan.tasks:
                for i, task in enumerate(plan.implement_plan.tasks):
                    step_id = f"plan_task_{task.id}"
                    next_id = (
                        f"plan_task_{plan.implement_plan.tasks[i + 1].id}"
                        if i + 1 < len(plan.implement_plan.tasks)
                        else "verify"
                    )
                    steps.append(
                        StepDefinition(
                            id=step_id,
                            name=f"Implement: {task.description[:50]}",
                            step_type="implementation",
                            config={
                                "task_id": task.id,
                                "description": task.description,
                                "files": task.files,
                                "complexity": task.complexity,
                                "repo_path": str(self.aragora_path),
                                "agent_type": assignment.agent_type,
                            },
                            next_steps=[next_id],
                        )
                    )

            # Add verification step
            test_paths = self._infer_test_paths(assignment.subtask.file_scope)
            steps.append(
                StepDefinition(
                    id="verify",
                    name="Verify Changes",
                    step_type="verification",
                    config={
                        "run_tests": True,
                        "test_paths": test_paths,
                    },
                    next_steps=[],
                ),
            )

            # Add approval gate if plan requires human approval
            if plan.requires_human_approval:
                # Insert approval step before implementation
                approval_step = StepDefinition(
                    id="risk_approval",
                    name="Risk-Based Approval Gate",
                    step_type="agent",
                    config={
                        "agent_type": "claude",
                        "prompt_template": "review",
                        "task": (
                            f"Risk review for: {assignment.subtask.description}\n"
                            f"Risk level: {plan.risk_register.get_critical_risks()[0].level.value if plan.risk_register and plan.risk_register.get_critical_risks() else 'unknown'}\n"
                            "Review and approve/reject."
                        ),
                        "gate": True,
                        "blocking": True,
                    },
                    next_steps=[steps[0].id] if steps else [],
                )
                steps.insert(0, approval_step)

            entry = steps[0].id if steps else "verify"
            return WorkflowDefinition(
                id=f"plan_{assignment.subtask.id}",
                name=f"DecisionPlan: {assignment.subtask.title}",
                description=assignment.subtask.description,
                steps=steps,
                entry_step=entry,
            )

        except ImportError:
            logger.debug("DecisionPlanFactory not available, using standard workflow")
            return None
        except (RuntimeError, ValueError, KeyError) as e:
            logger.warning("Failed to build DecisionPlan workflow: %s", e)
            return None
