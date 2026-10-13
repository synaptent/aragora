"""Execution Bridge — auto-triggers downstream actions from debate outcomes.

Connects the PostDebateCoordinator to the workflow trigger system,
enabling automatic action execution based on decision properties.

When a debate completes with sufficient confidence:
1. Receipt triggers are evaluated against configured rules
2. Matching workflows are executed automatically
3. Notifications are dispatched to configured channels
4. Outcome verification is registered for feedback loop
5. Improvement suggestions are queued for the Nomic Loop

The bridge is the "act on decisions" layer that transforms Aragora
from a deliberation engine into an autonomous decision-action system.

Usage:
    bridge = ExecutionBridge()

    # Register custom triggers
    bridge.register_action(
        name="deploy_on_confidence",
        condition=lambda r: r.get("confidence", 0) > 0.9 and r.get("domain") == "deployment",
        action=ActionType.WORKFLOW,
        workflow_template="auto_deploy",
    )

    # Evaluate after debate
    results = bridge.evaluate_and_execute(debate_result, confidence=0.92, domain="deployment")
"""

from __future__ import annotations

__all__ = [
    "ExecutionBridge",
    "ActionType",
    "ActionResult",
    "BridgeConfig",
    "create_default_bridge",
]

import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)


class ActionType(enum.Enum):
    """Types of downstream actions the bridge can trigger."""

    WORKFLOW = "workflow"
    NOTIFICATION = "notification"
    OUTCOME_VERIFICATION = "outcome_verification"
    IMPROVEMENT_QUEUE = "improvement_queue"
    WEBHOOK = "webhook"
    PR_CREATION = "pr_creation"


@dataclass
class ActionRule:
    """A rule mapping debate properties to a downstream action."""

    name: str
    condition: Callable[[dict[str, Any]], bool]
    action_type: ActionType
    config: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    enabled: bool = True
    min_confidence: float = 0.0

    def matches(self, context: dict[str, Any]) -> bool:
        """Check if this rule matches the given context."""
        confidence = context.get("confidence", 0.0)
        if confidence < self.min_confidence:
            return False
        try:
            return self.condition(context)
        except (KeyError, TypeError, ValueError):
            return False


@dataclass
class ActionResult:
    """Result of executing a downstream action."""

    rule_name: str
    action_type: ActionType
    success: bool
    detail: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_name": self.rule_name,
            "action_type": self.action_type.value,
            "success": self.success,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


@dataclass
class BridgeConfig:
    """Configuration for the ExecutionBridge."""

    enable_auto_workflows: bool = True
    enable_auto_notifications: bool = True
    enable_outcome_verification: bool = True
    enable_improvement_queue: bool = True
    enable_pr_creation: bool = False  # Requires explicit opt-in
    default_min_confidence: float = 0.7
    pr_min_confidence: float = 0.85
    improvement_min_confidence: float = 0.75


class ExecutionBridge:
    """Bridges debate outcomes to automatic downstream actions.

    Evaluates debate results against configured rules and executes
    matching actions. Each action is independent and failure-tolerant.
    """

    def __init__(self, config: BridgeConfig | None = None):
        self.config = config or BridgeConfig()
        self._rules: list[ActionRule] = []
        self._results: list[ActionResult] = []

    @property
    def rules(self) -> list[ActionRule]:
        return list(self._rules)

    @property
    def results(self) -> list[ActionResult]:
        return list(self._results)

    def register_action(
        self,
        name: str,
        condition: Callable[[dict[str, Any]], bool],
        action_type: ActionType,
        config: dict[str, Any] | None = None,
        priority: int = 0,
        min_confidence: float | None = None,
    ) -> ActionRule:
        """Register a downstream action rule."""
        rule = ActionRule(
            name=name,
            condition=condition,
            action_type=action_type,
            config=config or {},
            priority=priority,
            min_confidence=min_confidence
            if min_confidence is not None
            else self.config.default_min_confidence,
        )
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)
        return rule

    def evaluate_and_execute(
        self,
        debate_id: str,
        debate_result: Any,
        confidence: float = 0.0,
        domain: str = "general",
        task: str = "",
        agents: list[str] | None = None,
    ) -> list[ActionResult]:
        """Evaluate all rules and execute matching actions.

        Args:
            debate_id: Unique debate identifier
            debate_result: The debate result object
            confidence: Debate confidence score
            domain: Domain classification
            task: The debate task/question
            agents: List of participating agent names

        Returns:
            List of ActionResult for each executed action
        """
        context = {
            "debate_id": debate_id,
            "confidence": confidence,
            "domain": domain,
            "task": task,
            "agents": agents or [],
            "consensus_reached": bool(getattr(debate_result, "consensus", None)),
            "final_answer": str(
                getattr(debate_result, "final_answer", getattr(debate_result, "consensus", ""))
            ),
            "rounds_used": getattr(debate_result, "rounds_used", 0),
        }

        results = []
        for rule in self._rules:
            if not rule.enabled or not rule.matches(context):
                continue

            result = self._execute_action(rule, context, debate_result)
            results.append(result)
            self._results.append(result)

            logger.info(
                "execution_bridge action=%s rule=%s success=%s debate_id=%s",
                rule.action_type.value,
                rule.name,
                result.success,
                debate_id,
            )

        return results

    def _execute_action(
        self,
        rule: ActionRule,
        context: dict[str, Any],
        debate_result: Any,
    ) -> ActionResult:
        """Execute a single action rule."""
        try:
            if rule.action_type == ActionType.WORKFLOW:
                return self._execute_workflow(rule, context)
            elif rule.action_type == ActionType.NOTIFICATION:
                return self._execute_notification(rule, context)
            elif rule.action_type == ActionType.OUTCOME_VERIFICATION:
                return self._execute_outcome_verification(rule, context)
            elif rule.action_type == ActionType.IMPROVEMENT_QUEUE:
                return self._execute_improvement_queue(rule, context)
            elif rule.action_type == ActionType.WEBHOOK:
                return self._execute_webhook(rule, context)
            elif rule.action_type == ActionType.PR_CREATION:
                return self._execute_pr_creation(rule, context, debate_result)
            else:
                return ActionResult(
                    rule_name=rule.name,
                    action_type=rule.action_type,
                    success=False,
                    detail=f"Unknown action type: {rule.action_type}",
                )
        except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
            logger.warning("Action %s failed: %s", rule.name, e)
            return ActionResult(
                rule_name=rule.name,
                action_type=rule.action_type,
                success=False,
                detail=str(e),
            )

    def _execute_workflow(self, rule: ActionRule, context: dict[str, Any]) -> ActionResult:
        """Execute a workflow template."""
        if not self.config.enable_auto_workflows:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.WORKFLOW,
                success=False,
                detail="Auto-workflows disabled",
            )

        try:
            from aragora.workflow.triggers import ReceiptWorkflowTrigger

            trigger = ReceiptWorkflowTrigger()
            template = rule.config.get("workflow_template", "default")

            # Register the rule's condition as a trigger
            trigger.register_rule(
                name=rule.name,
                condition=rule.condition,
                workflow_template=template,
            )

            results = trigger.evaluate(context)
            matched = len(results) > 0

            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.WORKFLOW,
                success=matched,
                detail=f"Workflow '{template}' {'triggered' if matched else 'not matched'}",
            )
        except ImportError:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.WORKFLOW,
                success=False,
                detail="Workflow triggers not available",
            )

    def _execute_notification(self, rule: ActionRule, context: dict[str, Any]) -> ActionResult:
        """Send notification about debate outcome."""
        if not self.config.enable_auto_notifications:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.NOTIFICATION,
                success=False,
                detail="Auto-notifications disabled",
            )

        try:
            from aragora.notifications.service import notify_debate_completed

            import asyncio

            coro = notify_debate_completed(
                debate_id=context["debate_id"],
                task=context.get("task", ""),
                verdict=str(context.get("final_answer", "")),
                confidence=context.get("confidence", 0.0),
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(coro)
            except RuntimeError:
                asyncio.run(coro)
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.NOTIFICATION,
                success=True,
                detail=f"Notification sent for debate {context['debate_id']}",
            )
        except (ImportError, RuntimeError, ConnectionError, OSError) as e:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.NOTIFICATION,
                success=False,
                detail=str(e),
            )

    def _execute_outcome_verification(
        self, rule: ActionRule, context: dict[str, Any]
    ) -> ActionResult:
        """Register decision for outcome verification."""
        if not self.config.enable_outcome_verification:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.OUTCOME_VERIFICATION,
                success=False,
                detail="Outcome verification disabled",
            )

        try:
            from aragora.debate.outcome_verifier import OutcomeVerifier

            verifier = OutcomeVerifier()
            verifier.record_decision(
                debate_id=context["debate_id"],
                agents=context.get("agents", []),
                consensus_confidence=context.get("confidence", 0.0),
                consensus_text=context.get("final_answer", ""),
                domain=context.get("domain", "general"),
                task=context.get("task", ""),
            )
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.OUTCOME_VERIFICATION,
                success=True,
                detail=f"Decision registered for verification: {context['debate_id']}",
            )
        except (ImportError, OSError) as e:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.OUTCOME_VERIFICATION,
                success=False,
                detail=str(e),
            )

    def _execute_improvement_queue(self, rule: ActionRule, context: dict[str, Any]) -> ActionResult:
        """Queue improvement suggestion for Nomic Loop."""
        if not self.config.enable_improvement_queue:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.IMPROVEMENT_QUEUE,
                success=False,
                detail="Improvement queue disabled",
            )

        try:
            from aragora.nomic.improvement_queue import (
                ImprovementSuggestion,
                get_improvement_queue,
            )

            queue = get_improvement_queue()
            queue.enqueue(
                ImprovementSuggestion(
                    debate_id=context["debate_id"],
                    task=context.get("task", "")[:100],
                    suggestion=f"Debate outcome (confidence={context.get('confidence', 0):.2f}, "
                    f"domain={context.get('domain', 'general')})",
                    category="code_quality",
                    confidence=context.get("confidence", 0.5),
                )
            )
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.IMPROVEMENT_QUEUE,
                success=True,
                detail=f"Queued improvement for debate {context['debate_id']}",
            )
        except (ImportError, OSError, AttributeError) as e:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.IMPROVEMENT_QUEUE,
                success=False,
                detail=str(e),
            )

    def _execute_webhook(self, rule: ActionRule, context: dict[str, Any]) -> ActionResult:
        """Send webhook notification."""
        webhook_url = rule.config.get("webhook_url")
        if not webhook_url:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.WEBHOOK,
                success=False,
                detail="No webhook_url configured",
            )

        try:
            import json
            import urllib.request

            payload = json.dumps(
                {
                    "event": "debate_completed",
                    "debate_id": context["debate_id"],
                    "confidence": context.get("confidence", 0.0),
                    "domain": context.get("domain", "general"),
                    "consensus_reached": context.get("consensus_reached", False),
                    "task": context.get("task", "")[:200],
                }
            ).encode()

            req = urllib.request.Request(  # webhook URL from config
                webhook_url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status

            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.WEBHOOK,
                success=200 <= status < 300,
                detail=f"Webhook responded with status {status}",
            )
        except (OSError, ValueError, TimeoutError) as e:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.WEBHOOK,
                success=False,
                detail=str(e),
            )

    def _execute_pr_creation(
        self, rule: ActionRule, context: dict[str, Any], debate_result: Any
    ) -> ActionResult:
        """Create a draft PR from debate outcome."""
        if not self.config.enable_pr_creation:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.PR_CREATION,
                success=False,
                detail="PR creation disabled",
            )

        try:
            from aragora.pipeline.executor import PlanExecutor
            from aragora.pipeline.decision_plan.factory import DecisionPlanFactory

            plan = DecisionPlanFactory.from_debate_result(
                debate_result,
                metadata={"debate_id": context["debate_id"], "task": context.get("task", "")},
            )
            if plan:
                executor = PlanExecutor()
                pr_result = executor.execute_to_github_pr(plan, draft=True)
                return ActionResult(
                    rule_name=rule.name,
                    action_type=ActionType.PR_CREATION,
                    success=True,
                    detail=f"Draft PR created: {pr_result}",
                )
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.PR_CREATION,
                success=False,
                detail="No plan generated from debate result",
            )
        except (ImportError, RuntimeError, ValueError, OSError) as e:
            return ActionResult(
                rule_name=rule.name,
                action_type=ActionType.PR_CREATION,
                success=False,
                detail=str(e),
            )


def create_default_bridge(config: BridgeConfig | None = None) -> ExecutionBridge:
    """Create an ExecutionBridge with standard action rules.

    Default rules:
    - High-confidence decisions → notify stakeholders
    - All decisions → register for outcome verification
    - Domain-specific decisions → queue improvement suggestions
    - Failed gauntlet → escalation workflow
    """
    bridge = ExecutionBridge(config=config)

    # Always register decisions for outcome verification
    bridge.register_action(
        name="auto_verify_outcome",
        condition=lambda r: True,
        action_type=ActionType.OUTCOME_VERIFICATION,
        priority=100,
        min_confidence=0.0,
    )

    # Notify on high-confidence consensus
    bridge.register_action(
        name="notify_high_confidence",
        condition=lambda r: r.get("confidence", 0) >= 0.85 and r.get("consensus_reached", False),
        action_type=ActionType.NOTIFICATION,
        priority=50,
        min_confidence=0.85,
    )

    # Queue improvement for low-confidence or non-consensus outcomes
    bridge.register_action(
        name="improve_low_confidence",
        condition=lambda r: r.get("confidence", 0) < 0.6 or not r.get("consensus_reached", False),
        action_type=ActionType.IMPROVEMENT_QUEUE,
        priority=30,
        min_confidence=0.0,  # Always eligible — condition handles the threshold
    )

    # Escalation workflow for failed gauntlet validations
    bridge.register_action(
        name="escalate_gauntlet_failure",
        condition=lambda r: r.get("gauntlet_verdict") == "FAIL",
        action_type=ActionType.WORKFLOW,
        config={"workflow_template": "escalation_review"},
        priority=90,
        min_confidence=0.0,
    )

    return bridge
