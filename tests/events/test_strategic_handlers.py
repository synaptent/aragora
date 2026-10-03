"""Tests for strategic cross-subscriber feedback loop handlers."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from aragora.events.types import StreamEvent, StreamEventType


@pytest.fixture
def make_event():
    """Factory for creating StreamEvent instances."""

    def _make(event_type: StreamEventType, data: dict | None = None) -> StreamEvent:
        return StreamEvent(type=event_type, data=data or {})

    return _make


# =========================================================================
# Risk Warning → Health Registry
# =========================================================================


class TestRiskWarningToHealth:
    """Test risk warning → health registry degradation handler."""

    def _get_handler(self):
        from aragora.events.cross_subscribers.manager import CrossSubscriberManager

        return CrossSubscriberManager()

    def test_skips_when_no_component(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.RISK_WARNING,
            {
                "risk_type": "security_anomaly",
                "severity": "high",
            },
        )
        # Should not raise
        handler._handle_risk_warning_to_health(event)

    def test_skips_low_severity(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.RISK_WARNING,
            {
                "risk_type": "security_anomaly",
                "severity": "low",
                "component": "agent_claude",
            },
        )
        with patch("aragora.resilience.health.get_global_health_registry") as mock_fn:
            handler._handle_risk_warning_to_health(event)
            mock_fn.assert_not_called()

    def test_degrades_health_on_high_severity(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.RISK_WARNING,
            {
                "risk_type": "security_anomaly",
                "severity": "high",
                "component": "agent_claude",
                "description": "Unusual behavior detected",
            },
        )

        mock_checker = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get_or_create.return_value = mock_checker

        with patch(
            "aragora.resilience.health.get_global_health_registry", return_value=mock_registry
        ):
            handler._handle_risk_warning_to_health(event)
            mock_registry.get_or_create.assert_called_once_with("agent_claude")
            mock_checker.record_failure.assert_called_once()
            call_kwargs = mock_checker.record_failure.call_args
            assert "security_anomaly" in str(call_kwargs)

    def test_creates_checker_via_get_or_create(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.RISK_WARNING,
            {
                "risk_type": "injection_attempt",
                "severity": "critical",
                "component": "api_gateway",
            },
        )

        mock_checker = MagicMock()
        mock_registry = MagicMock()
        mock_registry.get_or_create.return_value = mock_checker

        with patch(
            "aragora.resilience.health.get_global_health_registry", return_value=mock_registry
        ):
            handler._handle_risk_warning_to_health(event)
            mock_registry.get_or_create.assert_called_once_with("api_gateway")
            mock_checker.record_failure.assert_called_once()

    def test_graceful_on_import_error(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.RISK_WARNING,
            {
                "severity": "high",
                "component": "test",
            },
        )
        with patch.dict("sys.modules", {"aragora.resilience.health": None}):
            # Should not raise
            handler._handle_risk_warning_to_health(event)


# =========================================================================
# Genesis → Control Plane
# =========================================================================


class TestGenesisToControlPlane:
    """Test genesis events → control plane registry sync handler."""

    def _get_handler(self):
        from aragora.events.cross_subscribers.manager import CrossSubscriberManager

        return CrossSubscriberManager()

    def test_skips_when_no_agent_id(self, make_event):
        handler = self._get_handler()
        event = make_event(StreamEventType.AGENT_BIRTH, {"event_type": "birth"})
        handler._handle_genesis_to_control_plane(event)

    def test_schedules_born_agent_registration(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.AGENT_BIRTH,
            {
                "event_type": "birth",
                "agent_id": "agent_new_42",
                "agent_type": "evolved",
                "capabilities": ["reasoning", "coding"],
                "generation": 3,
            },
        )

        mock_registry_cls = MagicMock()
        with patch("aragora.control_plane.registry.AgentRegistry", mock_registry_cls):
            # No event loop → logs but doesn't crash
            handler._handle_genesis_to_control_plane(event)
            mock_registry_cls.assert_called_once()

    def test_schedules_dead_agent_removal(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.AGENT_DEATH,
            {
                "event_type": "death",
                "agent_id": "agent_retired_7",
            },
        )

        mock_registry_cls = MagicMock()
        with patch("aragora.control_plane.registry.AgentRegistry", mock_registry_cls):
            handler._handle_genesis_to_control_plane(event)
            mock_registry_cls.assert_called_once()

    def test_schedules_evolved_agent_update(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.AGENT_EVOLUTION,
            {
                "event_type": "mutation",
                "agent_id": "agent_mutant_5",
                "capabilities": ["advanced_reasoning"],
            },
        )

        mock_registry_cls = MagicMock()
        with patch("aragora.control_plane.registry.AgentRegistry", mock_registry_cls):
            handler._handle_genesis_to_control_plane(event)
            mock_registry_cls.assert_called_once()

    @pytest.mark.asyncio
    async def test_registers_born_agent_with_event_loop(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.AGENT_BIRTH,
            {
                "event_type": "birth",
                "agent_id": "agent_async_1",
                "agent_type": "evolved",
                "capabilities": ["reasoning"],
                "generation": 1,
            },
        )

        import asyncio

        async def mock_register(**kwargs):
            return None

        mock_registry_instance = MagicMock()
        mock_registry_instance.register = mock_register

        mock_registry_cls = MagicMock(return_value=mock_registry_instance)
        with patch("aragora.control_plane.registry.AgentRegistry", mock_registry_cls):
            handler._handle_genesis_to_control_plane(event)
            # With event loop running, task should be created
            await asyncio.sleep(0.05)

    def test_graceful_on_import_error(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.AGENT_BIRTH,
            {
                "event_type": "birth",
                "agent_id": "test",
            },
        )
        with patch.dict("sys.modules", {"aragora.control_plane.registry": None}):
            handler._handle_genesis_to_control_plane(event)


# =========================================================================
# Approval Approved → KM Reinforcement
# =========================================================================


class TestApprovalToKMReinforcement:
    """Test approval approved → KM confidence reinforcement handler.

    Relocated to ``KnowledgeEventSubscriber`` (P4a Batch E2c): it is
    knowledge-coupled, unlike ``CrossSubscriberManager``'s other
    domain-free built-in handlers.
    """

    def _get_handler(self):
        from aragora.knowledge.event_subscribers import KnowledgeEventSubscriber

        return KnowledgeEventSubscriber()

    def test_skips_when_no_topic(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.APPROVAL_APPROVED,
            {
                "decision_id": "dec_123",
            },
        )
        handler._handle_approval_to_km_reinforcement(event)

    def test_boosts_km_confidence(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.APPROVAL_APPROVED,
            {
                "decision_id": "dec_456",
                "debate_id": "debate_789",
                "topic": "Should we migrate to microservices?",
            },
        )

        mock_mound = MagicMock()
        with patch("aragora.knowledge.mound.get_knowledge_mound", return_value=mock_mound):
            handler._handle_approval_to_km_reinforcement(event)
            mock_mound.boost_importance.assert_called_once_with(
                source="debate:debate_789",
                factor=1.15,
            )

    def test_uses_decision_id_when_no_debate_id(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.APPROVAL_APPROVED,
            {
                "decision_id": "dec_standalone",
                "topic": "Approve budget increase",
            },
        )

        mock_mound = MagicMock()
        with patch("aragora.knowledge.mound.get_knowledge_mound", return_value=mock_mound):
            handler._handle_approval_to_km_reinforcement(event)
            mock_mound.boost_importance.assert_called_once_with(
                source="decision:dec_standalone",
                factor=1.15,
            )

    def test_graceful_when_mound_unavailable(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.APPROVAL_APPROVED,
            {
                "topic": "Test topic",
            },
        )
        with patch("aragora.knowledge.mound.get_knowledge_mound", return_value=None):
            handler._handle_approval_to_km_reinforcement(event)


# =========================================================================
# Budget Alert → Team Selection
# =========================================================================


class TestBudgetAlertToTeamSelection:
    """Test budget alert → team selection constraint handler.

    Relocated to ``DebateEventSubscriber`` (P4a Batch E4): it is
    debate-coupled, unlike ``CrossSubscriberManager``'s other
    domain-free built-in handlers.
    """

    def _get_handler(self):
        from aragora.debate.event_subscribers import DebateEventSubscriber

        return DebateEventSubscriber()

    def test_records_budget_constraint_via_method(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.BUDGET_ALERT,
            {
                "alert_type": "soft_limit",
                "threshold": 100.0,
                "current_spend": 95.0,
                "workspace_id": "ws_123",
            },
        )

        mock_selector = MagicMock()
        mock_selector.record_budget_constraint = MagicMock()
        with patch("aragora.debate.team_selector.TeamSelector", mock_selector):
            handler._handle_budget_alert_to_team_selection(event)
            mock_selector.record_budget_constraint.assert_called_once()

    def test_falls_back_to_class_attr(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.BUDGET_ALERT,
            {
                "alert_type": "hard_limit",
                "threshold": 200.0,
                "current_spend": 210.0,
                "workspace_id": "ws_456",
            },
        )

        mock_selector = MagicMock(spec=[])  # No methods
        delattr(mock_selector, "record_budget_constraint") if hasattr(
            mock_selector, "record_budget_constraint"
        ) else None
        with patch("aragora.debate.team_selector.TeamSelector", mock_selector):
            handler._handle_budget_alert_to_team_selection(event)
            assert hasattr(mock_selector, "_budget_constraints")
            assert mock_selector._budget_constraints["ws_456"]["constrained"] is True

    def test_graceful_on_import_error(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.BUDGET_ALERT,
            {
                "threshold": 100.0,
            },
        )
        with patch.dict("sys.modules", {"aragora.debate.team_selector": None}):
            handler._handle_budget_alert_to_team_selection(event)


# =========================================================================
# Alert Escalated → Workflow Brake
# =========================================================================


class TestAlertEscalatedToWorkflowBrake:
    """Test alert escalated → workflow emergency brake handler.

    Relocated to ``WorkflowEventSubscriber`` (P4a Batch E5): it is
    workflow-coupled, unlike ``CrossSubscriberManager``'s other
    domain-free built-in handlers.
    """

    def _get_handler(self):
        from aragora.workflow.event_subscribers import WorkflowEventSubscriber

        return WorkflowEventSubscriber()

    def test_skips_non_critical_severity(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.ALERT_ESCALATED,
            {
                "severity": "warning",
                "alert_id": "alert_1",
            },
        )
        with patch("aragora.workflow.engine.WorkflowEngine.pause_all") as pause_all:
            handler._handle_alert_escalated_to_workflow_brake(event)
            pause_all.assert_not_called()

    def test_pauses_workflows_on_critical(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.ALERT_ESCALATED,
            {
                "severity": "critical",
                "alert_id": "alert_99",
                "reason": "Database connection pool exhausted",
            },
        )

        with patch("aragora.workflow.engine.WorkflowEngine.pause_all") as pause_all:
            handler._handle_alert_escalated_to_workflow_brake(event)
            pause_all.assert_called_once()
            call_kwargs = pause_all.call_args[1]
            assert "Database connection pool" in call_kwargs["reason"]

    def test_pauses_workflows_on_emergency(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.ALERT_ESCALATED,
            {
                "severity": "emergency",
                "alert_id": "alert_critical",
                "reason": "System overload",
            },
        )

        with patch("aragora.workflow.engine.WorkflowEngine.pause_all") as pause_all:
            handler._handle_alert_escalated_to_workflow_brake(event)
            pause_all.assert_called_once()

    def test_graceful_on_import_error(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.ALERT_ESCALATED,
            {
                "severity": "critical",
            },
        )
        with patch.dict("sys.modules", {"aragora.workflow.engine": None}):
            handler._handle_alert_escalated_to_workflow_brake(event)


# =========================================================================
# Meta-Learning Adjusted → Team Selection
# =========================================================================


class TestMetaLearningToTeamSelection:
    """Test meta-learning → team selection recalibration handler.

    Relocated to ``DebateEventSubscriber`` (P4a Batch E4): it is
    debate-coupled, unlike ``CrossSubscriberManager``'s other
    domain-free built-in handlers.
    """

    def _get_handler(self):
        from aragora.debate.event_subscribers import DebateEventSubscriber

        return DebateEventSubscriber()

    def test_skips_when_no_adjustments(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.META_LEARNING_ADJUSTED,
            {
                "adjustments": {},
                "learning_rate": 0.01,
            },
        )
        handler._handle_meta_learning_to_team_selection(event)

    def test_applies_meta_learning_via_method(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.META_LEARNING_ADJUSTED,
            {
                "adjustments": {"elo_weight": 0.35, "calibration_weight": 0.25},
                "learning_rate": 0.01,
                "total_adjustments": 2,
            },
        )

        mock_selector = MagicMock()
        mock_selector.apply_meta_learning = MagicMock()
        with patch("aragora.debate.team_selector.TeamSelector", mock_selector):
            handler._handle_meta_learning_to_team_selection(event)
            mock_selector.apply_meta_learning.assert_called_once_with(
                adjustments={"elo_weight": 0.35, "calibration_weight": 0.25},
                learning_rate=0.01,
            )

    def test_falls_back_to_class_attr(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.META_LEARNING_ADJUSTED,
            {
                "adjustments": {"diversity_bonus": 0.1},
                "learning_rate": 0.005,
                "total_adjustments": 1,
            },
        )

        mock_selector = MagicMock(spec=[])
        with patch("aragora.debate.team_selector.TeamSelector", mock_selector):
            handler._handle_meta_learning_to_team_selection(event)
            assert hasattr(mock_selector, "_meta_learning_state")
            state = mock_selector._meta_learning_state
            assert state["learning_rate"] == 0.005

    def test_graceful_on_import_error(self, make_event):
        handler = self._get_handler()
        event = make_event(
            StreamEventType.META_LEARNING_ADJUSTED,
            {
                "adjustments": {"x": 1},
            },
        )
        with patch.dict("sys.modules", {"aragora.debate.team_selector": None}):
            handler._handle_meta_learning_to_team_selection(event)


# =========================================================================
# Integration: Manager Registration
# =========================================================================


class TestStrategicHandlersRegistration:
    """Verify strategic handlers are registered in CrossSubscriberManager."""

    def test_all_strategic_handlers_registered(self):
        from aragora.events.cross_subscribers.manager import CrossSubscriberManager

        manager = CrossSubscriberManager()
        registered_names = set()
        for handlers in manager._subscribers.values():
            for name, _ in handlers:
                registered_names.add(name)

        expected = {
            "risk_warning_to_health",
            "agent_birth_to_control_plane",
            "agent_death_to_control_plane",
            "agent_evolution_to_control_plane",
        }
        assert expected.issubset(registered_names), (
            f"Missing handlers: {expected - registered_names}"
        )
        # approval_to_km_reinforcement relocated to KnowledgeEventSubscriber
        # (P4a Batch E2c); a bare manager no longer registers it directly.
        assert "approval_to_km_reinforcement" not in registered_names
        # budget_alert_to_team_selection / meta_learning_to_team_selection
        # relocated to DebateEventSubscriber (P4a Batch E4); a bare manager no
        # longer registers them directly.
        assert "budget_alert_to_team_selection" not in registered_names
        assert "meta_learning_to_team_selection" not in registered_names
        # alert_escalated_to_workflow_brake relocated to WorkflowEventSubscriber
        # (P4a Batch E5, application-tier home); a bare manager no longer
        # registers it directly.
        assert "alert_escalated_to_workflow_brake" not in registered_names

    def test_strategic_event_types_have_subscribers(self):
        from aragora.events.cross_subscribers.manager import CrossSubscriberManager

        manager = CrossSubscriberManager()

        # APPROVAL_APPROVED excluded: its only bare-manager subscriber
        # (approval_to_km_reinforcement) relocated to KnowledgeEventSubscriber
        # (P4a Batch E2c) and is wired only via apply_registered_subscribers.
        # BUDGET_ALERT / META_LEARNING_ADJUSTED excluded: their only bare-manager
        # subscribers (budget_alert_to_team_selection, meta_learning_to_team_selection)
        # relocated to DebateEventSubscriber (P4a Batch E4) and are wired only via
        # apply_registered_subscribers.
        # ALERT_ESCALATED excluded: its only bare-manager subscriber
        # (alert_escalated_to_workflow_brake) relocated to WorkflowEventSubscriber
        # (P4a Batch E5, application-tier home) and is wired only via
        # apply_registered_subscribers (interface-superset bootstrap only - a
        # pure-domain manager has no workflow engine to react through).
        expected_event_types = {
            StreamEventType.RISK_WARNING,
            StreamEventType.AGENT_BIRTH,
            StreamEventType.AGENT_DEATH,
            StreamEventType.AGENT_EVOLUTION,
        }

        for event_type in expected_event_types:
            assert event_type in manager._subscribers, f"No subscriber for {event_type.value}"
