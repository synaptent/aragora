"""Debate-domain event-subscriber home + domain-subset bootstrap (P4a EventBus
inversion; E1 skeleton, home content added by Batch E4).

This module has two roles:

1. The debate-domain's own event-subscriber **home**: the debate-coupled
   cross-subsystem reactions, relocated here from infrastructure
   ``aragora.events.cross_subscribers.handlers.{basic,strategic}`` (P4a Batch E4
   relocate-UP) so they live in their DOMAIN home. ``DebateEventSubscriber``
   self-registers via the domain-free registry
   (``aragora.events.cross_subscribers.register_subscriber`` - domain ->
   infrastructure, downward = legal).
2. Domain-subset **composition root** for the *domain* layer (Arena / pure-library
   debate): ``bootstrap_debate_event_subscribers`` imports sibling domain home
   modules so their subscribers self-register, then wires every domain subscriber
   (including this module's own) into the cross-subscriber manager.
   Application/interface reactions (workflow, nomic, server) register when *those*
   subsystems initialize; a pure-library debate with no server/workflow engine
   simply has no such reactions (matching today's try/except fallbacks).

Per the relocate-UP no-shim exemption (AGENTS.md "P4a Contracts-Thread Shared Rules"
and docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §8) there is NO re-export shim at
the old path; every consumer is repointed instead.

Handles:
- Agent ELO → Debate: Performance updates propagate to agent-pool team selection weights
- Calibration → Agent: Confidence weight updates propagate to the agent pool
- Consensus → Selection feedback learning
- Agent message → Rhetorical analysis
- Budget alert → Team selection constraint
- Meta-learning adjustment → Team selection recalibration

This module lives in ``debate`` (domain) and imports only sibling-domain home
modules plus ``aragora.events.cross_subscribers`` (domain -> infrastructure,
downward = legal). It must NOT be promoted to the interface superset - that would
recreate an upward import. See docs/architecture/P4A_EVENTS_QUEUE_INVERSION.md §4.4.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, cast

from aragora.events.cross_subscribers import get_registered_subscribers, register_subscriber
from aragora.events.types import StreamEventType

if TYPE_CHECKING:
    from aragora.events.cross_subscribers import CrossSubscriberManager
    from aragora.events.types import StreamEvent

logger = logging.getLogger(__name__)

DEBATE_EVENT_SUBSCRIBER_HANDLER_NAMES = frozenset(
    {
        "elo_to_debate",
        "calibration_to_agent",
        "consensus_to_learning",
        "agent_message_to_rhetorical",
        "budget_alert_to_team_selection",
        "meta_learning_to_team_selection",
    }
)

# Registry home names (the keys home modules pass to ``register_subscriber``/
# ``register_factory``, NOT the handler names above) that this domain-only
# bootstrap is allowed to wire. Passed as ``bootstrap(include_names=...)`` so
# that an application/interface-tier home already sitting in the process-wide
# registry - because something else imported it first - cannot silently get
# applied here too; see ``CrossSubscriberManager.apply_registered_subscribers``.
DOMAIN_EVENT_SUBSCRIBER_HOME_NAMES = frozenset(
    {
        "knowledge",
        "memory",
        "reasoning",
        "debate",
    }
)


class AgentPoolProtocol(Protocol):
    """Protocol for agent pool with ELO and calibration updates."""

    def update_elo_weight(self, agent_name: str, elo: float) -> None:
        """Update the ELO weight for an agent."""
        ...

    def update_calibration(
        self,
        agent_name: str,
        score: float,
        brier_score: float | None = None,
    ) -> None:
        """Update calibration data for an agent."""
        ...


class DebateEventSubscriber:
    """Debate-domain cross-subscriber: ELO/calibration/consensus/rhetoric/team-selection reactions."""

    def _handle_elo_to_debate(self, event: "StreamEvent") -> None:
        """
        ELO update → Debate team selection weights.

        When agent ELO changes, update team selection weights
        for future debates. Significant changes are logged.
        """
        data = event.data
        agent_name = data.get("agent", "")
        new_elo = data.get("elo", 1500)
        delta = data.get("delta", 0)
        debate_id = data.get("debate_id", "")

        # Log significant ELO changes
        if abs(delta) > 50:
            logger.info(
                "Significant ELO change: %s -> %s (Δ%+.0f) in debate %s",
                agent_name,
                new_elo,
                delta,
                debate_id,
            )

        # Update agent pool weights for future team selection
        try:
            import aragora.debate.agent_pool as agent_pool_module

            # get_agent_pool may not exist yet (planned feature)
            get_agent_pool = getattr(agent_pool_module, "get_agent_pool", None)
            if get_agent_pool is None:
                return

            pool: AgentPoolProtocol | None = get_agent_pool()
            if pool and hasattr(pool, "update_elo_weight"):
                pool.update_elo_weight(agent_name, new_elo)
        except ImportError:
            pass  # AgentPool module not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("AgentPool weight update failed: %s", e)

    def _handle_calibration_to_agent(self, event: "StreamEvent") -> None:
        """
        Calibration update → Agent confidence weights.

        When calibration data changes, update agent confidence
        weights for vote weighting and team selection.
        """
        data = event.data
        agent_name = data.get("agent", "")
        calibration_score = data.get("score", 0.5)
        brier_score = data.get("brier_score", None)
        prediction_count = data.get("prediction_count", 0)

        logger.debug(
            "Calibration update: %s -> %.2f (predictions: %s)",
            agent_name,
            calibration_score,
            prediction_count,
        )

        # Update agent pool with calibration data
        try:
            from aragora.debate.agent_pool import get_agent_pool

            pool = cast("AgentPoolProtocol | None", get_agent_pool())
            if pool and hasattr(pool, "update_calibration"):
                pool.update_calibration(
                    agent_name=agent_name,
                    score=calibration_score,
                    brier_score=brier_score,
                )
        except (ImportError, AttributeError):
            pass  # AgentPool or get_agent_pool not available
        except (RuntimeError, TypeError, ValueError) as e:
            logger.debug("AgentPool calibration update failed: %s", e)

    def _handle_consensus_to_learning(self, event: "StreamEvent") -> None:
        """Consensus → Selection feedback learning.

        When consensus is reached, feed the outcome to the
        SelectionFeedbackLoop for performance-based agent selection.
        """
        data = event.data
        debate_id = data.get("debate_id", "")
        confidence = data.get("confidence", 0.0)
        agents_used = data.get("agents", [])

        if not agents_used or confidence < 0.5:
            return

        logger.debug("Learning from consensus: %s confidence=%.2f", debate_id, confidence)

        try:
            from aragora.debate.selection_feedback import SelectionFeedbackLoop

            loop = SelectionFeedbackLoop()
            if hasattr(loop, "process_debate_outcome"):
                loop.process_debate_outcome(
                    debate_id=debate_id,
                    participants=agents_used,
                    winner=None,
                    confidence=confidence,
                )
        except ImportError:
            pass  # SelectionFeedbackLoop not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("Selection feedback learning failed: %s", e)

    def _handle_agent_message_to_rhetorical(self, event: "StreamEvent") -> None:
        """Agent message → Rhetorical analysis.

        When an agent sends a message, pass it to the RhetoricalObserver
        for argumentation quality analysis.
        """
        data = event.data
        agent_name = data.get("agent", "")
        content = data.get("content", "")

        if not content or len(content) < 20:
            return

        try:
            from aragora.debate.rhetorical_observer import get_rhetorical_observer

            observer = get_rhetorical_observer()
            if observer and hasattr(observer, "analyze_message"):
                observer.analyze_message(
                    agent_name=agent_name,
                    content=content,
                    metadata=data,
                )
        except ImportError:
            pass  # RhetoricalObserver not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("Rhetorical analysis failed: %s", e)

    def _handle_budget_alert_to_team_selection(self, event: "StreamEvent") -> None:
        """Budget alert → Team selection constraint.

        When a budget threshold is exceeded, record the constraint
        so that future debate team selections prefer cheaper agents
        and smaller team sizes. This prevents cost overruns while
        maintaining decision quality.
        """
        data = event.data
        alert_type = data.get("alert_type", data.get("type", ""))
        threshold = data.get("threshold", 0.0)
        current_spend = data.get("current_spend", data.get("current", 0.0))
        workspace_id = data.get("workspace_id", "default")

        logger.info(
            "Budget alert → team selection: type=%s spend=%.2f threshold=%.2f workspace=%s",
            alert_type,
            current_spend,
            threshold,
            workspace_id,
        )

        try:
            from aragora.debate.team_selector import TeamSelector

            # Record budget constraint in TeamSelector's class-level state
            if hasattr(TeamSelector, "record_budget_constraint"):
                TeamSelector.record_budget_constraint(
                    workspace_id=workspace_id,
                    alert_type=alert_type,
                    threshold=threshold,
                    current_spend=current_spend,
                )
            else:
                # Fallback: store in module-level dict for TeamSelector to query
                if not hasattr(TeamSelector, "_budget_constraints"):
                    TeamSelector._budget_constraints = {}  # type: ignore[attr-defined]
                TeamSelector._budget_constraints[workspace_id] = {  # type: ignore[attr-defined]
                    "alert_type": alert_type,
                    "threshold": threshold,
                    "current_spend": current_spend,
                    "constrained": True,
                }
                logger.debug(
                    "Stored budget constraint for workspace %s (fallback)",
                    workspace_id,
                )
        except ImportError:
            pass  # TeamSelector not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("Budget alert → team selection failed: %s", e)

    def _handle_meta_learning_to_team_selection(self, event: "StreamEvent") -> None:
        """Meta-learning adjustment → Team selection recalibration.

        When the MetaLearner auto-tunes hyperparameters based on
        debate outcomes, propagate the adjustments to the team
        selector so it can adapt its scoring weights accordingly.
        This creates a self-improving selection loop.
        """
        data = event.data
        adjustments = data.get("adjustments", {})
        learning_rate = data.get("learning_rate", 0.0)
        total_adjustments = data.get("total_adjustments", 0)

        if not adjustments:
            return

        logger.debug(
            "Meta-learning → team selection: %d adjustments, lr=%.4f",
            total_adjustments,
            learning_rate,
        )

        try:
            from aragora.debate.team_selector import TeamSelector

            # Propagate relevant hyperparameter adjustments
            if hasattr(TeamSelector, "apply_meta_learning"):
                TeamSelector.apply_meta_learning(
                    adjustments=adjustments,
                    learning_rate=learning_rate,
                )
            else:
                # Fallback: store adjustments for TeamSelector to query
                if not hasattr(TeamSelector, "_meta_learning_state"):
                    TeamSelector._meta_learning_state = {}  # type: ignore[attr-defined]
                TeamSelector._meta_learning_state.update(  # type: ignore[attr-defined]
                    {
                        "adjustments": adjustments,
                        "learning_rate": learning_rate,
                        "total_adjustments": total_adjustments,
                    }
                )
                logger.debug("Stored meta-learning state for team selection (fallback)")
        except ImportError:
            pass  # TeamSelector not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("Meta-learning → team selection failed: %s", e)

    def register(self, manager: "CrossSubscriberManager") -> None:
        """Wire the debate-domain reactions into ``manager`` (keyed/idempotent)."""
        manager.register(
            "elo_to_debate",
            StreamEventType.AGENT_ELO_UPDATED,
            self._handle_elo_to_debate,
        )
        manager.register(
            "calibration_to_agent",
            StreamEventType.CALIBRATION_UPDATE,
            self._handle_calibration_to_agent,
        )
        manager.register(
            "consensus_to_learning",
            StreamEventType.CONSENSUS,
            self._handle_consensus_to_learning,
        )
        manager.register(
            "agent_message_to_rhetorical",
            StreamEventType.AGENT_MESSAGE,
            self._handle_agent_message_to_rhetorical,
        )
        manager.register(
            "budget_alert_to_team_selection",
            StreamEventType.BUDGET_ALERT,
            self._handle_budget_alert_to_team_selection,
        )
        manager.register(
            "meta_learning_to_team_selection",
            StreamEventType.META_LEARNING_ADJUSTED,
            self._handle_meta_learning_to_team_selection,
        )


def get_debate_event_subscriber() -> DebateEventSubscriber:
    """Return the ``DebateEventSubscriber`` currently wired into the registry.

    Registers a fresh instance first if none is present yet, reusing the
    existing one otherwise so repeated calls resolve to the same instance
    (mirrors ``aragora.knowledge.event_subscribers.get_knowledge_event_subscriber``).
    """
    subscriber = get_registered_subscribers().get("debate")
    if not isinstance(subscriber, DebateEventSubscriber):
        subscriber = DebateEventSubscriber()
        register_subscriber("debate", subscriber)
    return subscriber


def register() -> None:
    """(Re-)register this home's subscriber into the domain-free registry.

    Delegates to :func:`get_debate_event_subscriber`'s get-or-create so repeated
    calls reuse the existing instance instead of replacing it. Called explicitly
    (not just import side-effect) so registration survives a cached re-import
    after ``reset_registry`` in tests.
    """
    get_debate_event_subscriber()


register()


def bootstrap_debate_event_subscribers() -> CrossSubscriberManager:
    """Import domain event-subscriber home modules and wire them into the manager.

    Idempotent (registration is keyed by name). Wires knowledge, memory,
    reasoning, and this module's own debate-domain subscriber. Further DOMAIN-tier
    ``import aragora.<domain>.event_subscribers`` lines are added here as more
    domain-coupled handlers relocate. APPLICATION/interface-tier homes (e.g.
    ``aragora.workflow.event_subscribers``, P4a Batch E5) are deliberately NOT
    imported here - importing an application-tier module from this domain-tier
    bootstrap would recreate the very upward edge this inversion removes. They
    are instead imported only by the interface-superset bootstrap
    (``aragora.server.startup.event_subscribers.bootstrap_event_subscribers``);
    a pure-domain debate with no workflow engine simply has no such reaction.
    This holds even if an application/interface-tier home was already
    imported elsewhere in-process (e.g. by an earlier, unrelated call to the
    interface-superset bootstrap): ``bootstrap(include_names=...)`` below
    restricts THIS call to the domain-tier homes, so a wider-tier home that
    already self-registered into the process-wide registry cannot be
    silently picked up here too.

    Returns:
        The registry-backed cross-subscriber manager singleton.
    """
    # Domain home modules register their subscribers here. ``register()`` is called
    # explicitly (not just import side-effect) so registration survives a cached
    # re-import after ``reset_registry`` in tests. More are added here as further
    # DOMAIN-tier handlers relocate; application/interface-tier homes are wired
    # only by the interface-superset bootstrap (see docstring above).
    from aragora.knowledge import event_subscribers as knowledge_home
    from aragora.memory import event_subscribers as memory_home
    from aragora.reasoning import event_subscribers as reasoning_home

    # A second domain-side composition root -- alongside aragora.debate.
    # orchestrator's module-level import -- that guarantees aragora.events.
    # security_events has a registered security debate runner. This one
    # covers callers that reach this bootstrap (server startup via the
    # interface superset, or any of this module's other domain callers such
    # as orchestrator_memory/knowledge_manager/extensions) WITHOUT ever
    # constructing an Arena (which is what orchestrator.py's import would
    # otherwise depend on). aragora.events never imports aragora.debate.
    #
    # ensure_registered() is called explicitly rather than relying on the
    # import's self-registration side effect alone: this bootstrap function
    # is documented as idempotent and safe to call repeatedly, and a bare
    # import is a no-op once security_response is already cached in
    # sys.modules, so it would not recover from a registry reset that
    # happens between calls.
    from aragora.debate import security_response as _security_response

    _security_response.ensure_registered()

    knowledge_home.register()
    memory_home.register()
    reasoning_home.register()
    register()  # this module's own debate-domain subscriber

    from aragora.events.cross_subscribers import bootstrap

    manager = bootstrap(include_names=set(DOMAIN_EVENT_SUBSCRIBER_HOME_NAMES))
    expected_handlers = (
        knowledge_home.KNOWLEDGE_EVENT_SUBSCRIBER_HANDLER_NAMES
        | memory_home.MEMORY_EVENT_SUBSCRIBER_HANDLER_NAMES
        | reasoning_home.REASONING_EVENT_SUBSCRIBER_HANDLER_NAMES
        | DEBATE_EVENT_SUBSCRIBER_HANDLER_NAMES
    )
    missing = expected_handlers - set(manager.get_stats())
    if missing:
        raise RuntimeError(
            f"Domain event subscriber bootstrap incomplete; missing handlers: {sorted(missing)}"
        )
    return manager
