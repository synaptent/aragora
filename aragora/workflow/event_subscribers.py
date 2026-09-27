"""Workflow-domain event-subscriber home (P4a EventBus inversion, Batch E5).

The post-debate workflow automation reaction and the alert-escalation
emergency-brake reaction, relocated here from infrastructure
``aragora.events.subscribers.workflow_automation`` (``PostDebateWorkflowSubscriber``)
and ``aragora.events.cross_subscribers.handlers.strategic``
(``_handle_alert_escalated_to_workflow_brake``) respectively, so the
workflow-coupled reactions live in their APPLICATION home. ``WorkflowEventSubscriber``
self-registers via the domain-free registry
(``aragora.events.cross_subscribers.register_subscriber`` - application ->
infrastructure, downward = legal); the interface-superset bootstrap
(``aragora.server.startup.event_subscribers.bootstrap_event_subscribers``)
imports this module so ``CrossSubscriberManager.apply_registered_subscribers``
wires both ``debate_end_to_workflow`` and
``alert_escalated_to_workflow_brake`` in. A pure-domain debate with no workflow
engine simply has no such reactions: this module is NOT imported by the
domain-subset bootstrap
(``aragora.debate.event_subscribers.bootstrap_debate_event_subscribers``).

Per the relocate-UP no-shim exemption (AGENTS.md "P4a Contracts-Thread Shared
Rules" and docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §8) there is NO
re-export shim at the old paths; every consumer is repointed instead.

The former ``cross_subscribers.handlers.basic._handle_debate_end_to_workflow``
delegate (an unregistered, dead runtime path that instantiated a throwaway
``PostDebateWorkflowSubscriber`` on every call - see
docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §5.3) remains removed rather
than relocated. The application home owns the single production route:
``WorkflowEventSubscriber.register`` registers one keyed
``debate_end_to_workflow`` reaction that delegates to the persistent
``PostDebateWorkflowSubscriber`` instance. The interface-superset bootstrap is
idempotent, so repeating it does not duplicate that reaction.

``_trigger_workflow`` remains a construction-only seam: it builds the workflow
definition without creating an engine or executing or queuing the definition.
Production dispatch still invokes ``handle_debate_end`` exactly once so outcome
classification and the existing fail-soft behavior remain observable while
workflow execution is implemented separately.

Handles:
- Debate end -> Post-debate workflow outcome classification
- Alert escalated -> Workflow emergency brake (pause/stop active workflows)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from aragora.events.cross_subscribers import get_registered_subscribers, register_subscriber
from aragora.events.types import StreamEventType

if TYPE_CHECKING:
    from aragora.events.cross_subscribers import CrossSubscriberManager
    from aragora.events.types import StreamEvent

logger = logging.getLogger(__name__)

WORKFLOW_EVENT_SUBSCRIBER_HANDLER_NAMES = frozenset(
    {
        "alert_escalated_to_workflow_brake",
        "debate_end_to_workflow",
    }
)

# Default workflow templates for common debate outcomes
OUTCOME_WORKFLOW_MAP: dict[str, str] = {
    "consensus_high_confidence": "post_debate_implement",
    "consensus_low_confidence": "post_debate_review",
    "no_consensus": "post_debate_escalate",
    "timeout": "post_debate_retry",
}


class PostDebateWorkflowSubscriber:
    """Subscribes to DEBATE_END events and triggers workflow automation."""

    def __init__(
        self,
        workflow_map: dict[str, str] | None = None,
        min_confidence_for_auto: float = 0.7,
    ):
        self.workflow_map = (
            dict(OUTCOME_WORKFLOW_MAP) if workflow_map is None else dict(workflow_map)
        )
        self.min_confidence_for_auto = min_confidence_for_auto
        self.stats: dict[str, int] = {
            "events_processed": 0,
            "workflows_triggered": 0,
            "errors": 0,
        }

    def _get_workflow_runtime(self) -> tuple[Any, Any]:
        """Load workflow definition classes behind a unit-testable seam."""
        from aragora.workflow.types import StepDefinition, WorkflowDefinition

        return StepDefinition, WorkflowDefinition

    def handle_debate_end(self, event: Any) -> None:
        """Handle a DEBATE_END event and trigger appropriate workflow."""
        self.stats["events_processed"] += 1
        try:
            data = event.data if hasattr(event, "data") else event
            if isinstance(data, dict):
                self._process_outcome(data)
            else:
                logger.debug(
                    "PostDebateWorkflow: unexpected event data type: %s",
                    type(data).__name__,
                )
        except (KeyError, TypeError, AttributeError, ValueError) as e:
            logger.warning("PostDebateWorkflow handler error: %s", e)
            self.stats["errors"] += 1

    def _process_outcome(self, data: dict[str, Any]) -> None:
        """Process a debate outcome and determine which workflow to trigger."""
        debate_id = data.get("debate_id", "")
        consensus_reached = data.get("consensus_reached", False)
        confidence = data.get("confidence", 0.0)
        timed_out = data.get("timed_out", False)

        # Classify the outcome
        if timed_out:
            outcome_key = "timeout"
        elif consensus_reached and confidence >= self.min_confidence_for_auto:
            outcome_key = "consensus_high_confidence"
        elif consensus_reached:
            outcome_key = "consensus_low_confidence"
        else:
            outcome_key = "no_consensus"

        template_name = self.workflow_map.get(outcome_key)
        if not template_name:
            logger.debug("No workflow template for outcome: %s", outcome_key)
            return

        # Create workflow context from debate data
        workflow_context = {
            "debate_id": debate_id,
            "outcome": outcome_key,
            "confidence": confidence,
            "consensus_reached": consensus_reached,
            "task": data.get("task", "")[:500],
            "winning_position": data.get("winning_position", "")[:1000],
            "synthesis": data.get("synthesis", "")[:1000],
            "domain": data.get("domain", "general"),
        }

        self._trigger_workflow(template_name, workflow_context)

    def _trigger_workflow(self, template_name: str, context: dict[str, Any]) -> None:
        """Build a workflow definition for the given template/context.

        Stub: constructs ``WorkflowDefinition``/``WorkflowEngine`` but never
        submits either for execution (no queue/execute call is made).
        ``stats["workflows_triggered"]`` counts these construction attempts,
        not completed workflow runs.
        """
        try:
            StepDefinition, WorkflowDefinition = self._get_workflow_runtime()

            # Create a minimal workflow definition
            debate_id_short = context.get("debate_id", "unknown")[:8]
            outcome = context.get("outcome", "unknown")

            WorkflowDefinition(
                id=f"pdw_{debate_id_short}",
                name=f"{template_name}_{debate_id_short}",
                description=f"Auto-triggered by debate outcome: {outcome}",
                steps=[
                    StepDefinition(
                        id=f"{template_name}_step_1",
                        name=f"Execute {template_name}",
                        step_type="post_debate_action",
                        config=context,
                    ),
                ],
            )

            logger.debug(
                "Built post-debate workflow definition (stub, not queued or "
                "executed): template=%s debate=%s outcome=%s",
                template_name,
                context.get("debate_id", ""),
                context.get("outcome", ""),
            )
            self.stats["workflows_triggered"] += 1

        except ImportError:
            logger.debug("Workflow engine not available for post-debate automation")
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.warning("Failed to trigger post-debate workflow: %s", e)
            self.stats["errors"] += 1


def get_post_debate_subscriber(
    workflow_map: dict[str, str] | None = None,
) -> PostDebateWorkflowSubscriber:
    """Construct a new ``PostDebateWorkflowSubscriber`` (not cached/singleton;
    preserved verbatim from the pre-relocation infrastructure module - use
    ``get_workflow_event_subscriber().post_debate_workflow`` for the instance
    actually reachable from the registered ``WorkflowEventSubscriber``)."""
    return PostDebateWorkflowSubscriber(workflow_map=workflow_map)


class WorkflowEventSubscriber:
    """Workflow-domain cross-subscriber: post-debate automation + alert-escalation brake."""

    def __init__(self) -> None:
        self.post_debate_workflow = PostDebateWorkflowSubscriber()

    def _handle_debate_end_to_workflow(self, event: "StreamEvent") -> None:
        """Debate end -> post-debate workflow automation.

        Delegates to the persistent ``PostDebateWorkflowSubscriber`` instance
        to classify the debate outcome and trigger the appropriate workflow
        template.
        """
        self.post_debate_workflow.handle_debate_end(event)

    def _handle_alert_escalated_to_workflow_brake(self, event: "StreamEvent") -> bool:
        """Alert escalated → Workflow emergency brake.

        When an alert escalates to critical severity, pause all
        active workflows to prevent cascading failures. This is
        the safety valve that stops automated processes when
        something goes seriously wrong.

        Returns:
            True only when the workflow engine confirms a brake method ran.
        """
        data = event.data
        severity = data.get("new_severity", data.get("severity", ""))
        alert_id = data.get("alert_id", "")
        reason = str(data.get("reason", data.get("message", "")) or "")[:200]

        # Only brake on critical/emergency escalations
        if severity not in ("critical", "emergency", "fatal"):
            return False

        logger.warning(
            "Alert escalated → workflow brake: alert=%s severity=%s reason=%s",
            alert_id,
            severity,
            reason,
        )

        try:
            from aragora.workflow.engine import WorkflowEngine

            WorkflowEngine.pause_all(
                reason=f"Emergency brake: {reason}",
            )
            logger.warning("Paused all workflows due to critical alert %s", alert_id)
            return True
        except ImportError:
            return False
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.error("Workflow emergency brake failed: %s", e, exc_info=True)
            return False

    def register(self, manager: "CrossSubscriberManager") -> None:
        """Wire the workflow-domain reactions into ``manager`` (keyed/idempotent).

        Registry application is tracked per manager, so repeated production
        bootstrap calls apply this subscriber only once.
        """
        manager.register(
            "debate_end_to_workflow",
            StreamEventType.DEBATE_END,
            self._handle_debate_end_to_workflow,
        )
        manager.register(
            "alert_escalated_to_workflow_brake",
            StreamEventType.ALERT_ESCALATED,
            self._handle_alert_escalated_to_workflow_brake,
        )


def get_workflow_event_subscriber() -> WorkflowEventSubscriber:
    """Return the ``WorkflowEventSubscriber`` currently wired into the registry.

    Registers a fresh instance first if none is present yet, reusing the
    existing one otherwise so repeated calls resolve to the same instance
    (mirrors ``aragora.knowledge.event_subscribers.get_knowledge_event_subscriber``).
    """
    subscriber = get_registered_subscribers().get("workflow")
    if not isinstance(subscriber, WorkflowEventSubscriber):
        subscriber = WorkflowEventSubscriber()
        register_subscriber("workflow", subscriber)
    return subscriber


def register() -> None:
    """(Re-)register this home's subscriber into the domain-free registry.

    Delegates to :func:`get_workflow_event_subscriber`'s get-or-create so
    repeated calls reuse the existing instance instead of replacing it. Called
    explicitly (not just import side-effect) so registration survives a cached
    re-import after ``reset_registry`` in tests.
    """
    get_workflow_event_subscriber()


register()
