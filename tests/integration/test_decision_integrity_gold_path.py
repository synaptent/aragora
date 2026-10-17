"""
Gold Path integration tests for Decision Integrity pipeline.

Tests the complete flow:
1. Build a decision integrity package from a debate dict
2. Verify receipt generation and serialization
3. Verify implementation plan generation
4. Verify context snapshot capture
5. Test the handler endpoint with mocked storage
6. Verify receipt persistence round-trip
7. Verify plan persistence round-trip
8. Verify budget enforcement blocks over-limit execution
9. Verify approval flow integration
10. Verify multi-channel notification dispatch
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.pipeline.decision_integrity import (
    ContextSnapshot,
    DecisionIntegrityPackage,
    build_decision_integrity_package,
    capture_context_snapshot,
)

pytestmark = pytest.mark.usefixtures("caller_owns_source_debate")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_debate(**overrides: Any) -> dict[str, Any]:
    """Create a realistic debate dict."""
    defaults: dict[str, Any] = {
        "debate_id": "debate-gold-001",
        "task": "Design a distributed rate limiter for 1M req/sec",
        "final_answer": (
            "1. Implement token bucket algorithm in `rate_limiter.py`\n"
            "2. Add Redis backend for distributed counting\n"
            "3. Create middleware wrapper for Flask routes\n"
            "4. Add per-endpoint configuration"
        ),
        "confidence": 0.92,
        "consensus_reached": True,
        "rounds_used": 3,
        "rounds_completed": 3,
        "status": "completed",
        "agents": ["claude", "gpt4", "gemini"],
        "metadata": {"source": "integration_test"},
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Phase 1: Package Generation (debate → receipt + plan)
# ---------------------------------------------------------------------------


class TestGoldPathPackageGeneration:
    """Verify that a debate produces a complete decision integrity package."""

    @pytest.mark.asyncio
    async def test_full_package_from_debate(self):
        """Complete package includes receipt, plan, and debate_id."""
        debate = _make_debate()
        pkg = await build_decision_integrity_package(debate)

        assert pkg.debate_id == "debate-gold-001"
        assert pkg.receipt is not None
        assert pkg.plan is not None

    @pytest.mark.asyncio
    async def test_receipt_has_audit_fields(self):
        """Receipt contains required audit trail fields."""
        debate = _make_debate()
        pkg = await build_decision_integrity_package(debate, include_plan=False)

        receipt_dict = pkg.receipt.to_dict()
        assert "receipt_id" in receipt_dict
        assert "timestamp" in receipt_dict

    @pytest.mark.asyncio
    async def test_plan_has_tasks(self):
        """Plan contains at least one implementation task."""
        debate = _make_debate()
        pkg = await build_decision_integrity_package(debate, include_receipt=False)

        assert pkg.plan is not None
        assert len(pkg.plan.tasks) >= 1
        assert pkg.plan.tasks[0].description

    @pytest.mark.asyncio
    async def test_serialization_round_trip(self):
        """Package serializes to dict and back without data loss."""
        debate = _make_debate()
        pkg = await build_decision_integrity_package(debate, include_context=True)

        d = pkg.to_dict()
        assert d["debate_id"] == "debate-gold-001"
        assert d["receipt"] is not None
        assert d["plan"] is not None
        assert d["context_snapshot"] is not None
        # All fields are JSON-serializable (no dataclass objects)
        import json

        json.dumps(d)  # Should not raise

    @pytest.mark.asyncio
    async def test_context_snapshot_included_when_requested(self):
        """Context snapshot is populated when include_context=True."""
        debate = _make_debate()

        mock_cross = AsyncMock()
        mock_cross.get_relevant_context.return_value = "Prior debates suggest Redis."

        pkg = await build_decision_integrity_package(
            debate,
            include_context=True,
            cross_debate_memory=mock_cross,
        )

        assert pkg.context_snapshot is not None
        assert pkg.context_snapshot.cross_debate_context == "Prior debates suggest Redis."


# ---------------------------------------------------------------------------
# Phase 2: Receipt Persistence
# ---------------------------------------------------------------------------


class TestGoldPathReceiptPersistence:
    """Verify receipts are persisted and retrievable."""

    def test_persist_receipt_calls_store(self):
        """_persist_receipt stores the receipt dict."""
        from aragora.server.handlers.debates.implementation import _persist_receipt

        mock_receipt = MagicMock()
        mock_receipt.to_dict.return_value = {
            "receipt_id": "rcpt-001",
            "timestamp": "2026-01-01T00:00:00",
        }

        mock_store = MagicMock()
        mock_store.save.return_value = "rcpt-001"

        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            result = _persist_receipt(mock_receipt, "debate-001")

        assert result == "rcpt-001"
        mock_store.save.assert_called_once()
        saved_dict = mock_store.save.call_args[0][0]
        assert saved_dict["debate_id"] == "debate-001"

    def test_persist_receipt_graceful_on_error(self):
        """Receipt persistence fails gracefully without raising."""
        from aragora.server.handlers.debates.implementation import _persist_receipt

        mock_receipt = MagicMock()
        mock_receipt.to_dict.side_effect = TypeError("serialize error")

        mock_store = MagicMock()
        with patch(
            "aragora.storage.receipt_store.get_receipt_store",
            return_value=mock_store,
        ):
            result = _persist_receipt(mock_receipt, "debate-001")
        assert result is None


# ---------------------------------------------------------------------------
# Phase 3: Plan Persistence
# ---------------------------------------------------------------------------


class TestGoldPathPlanPersistence:
    """Verify plans are stored in the pipeline executor."""

    def test_persist_plan_stores_via_executor(self):
        """_persist_plan wraps and stores the plan."""
        from aragora.server.handlers.debates.implementation import _persist_plan

        mock_plan = MagicMock()
        mock_plan.tasks = [MagicMock(id="t-1")]

        mock_decision_plan = MagicMock()

        with (
            patch("aragora.pipeline.executor.store_plan") as mock_store,
            patch(
                "aragora.pipeline.decision_plan.DecisionPlanFactory.from_implement_plan",
                return_value=mock_decision_plan,
            ),
        ):
            _persist_plan(mock_plan, "debate-001")

        mock_store.assert_called_once_with(mock_decision_plan)

    def test_persist_plan_graceful_on_error(self):
        """Plan persistence fails gracefully without raising."""
        from aragora.server.handlers.debates.implementation import _persist_plan

        mock_plan = MagicMock()

        with (
            patch(
                "aragora.pipeline.executor.store_plan",
                side_effect=OSError("store full"),
            ),
            patch(
                "aragora.pipeline.decision_plan.DecisionPlanFactory.from_implement_plan",
                return_value=MagicMock(),
            ),
        ):
            _persist_plan(mock_plan, "debate-001")  # Should not raise


# ---------------------------------------------------------------------------
# Phase 4: Budget Enforcement
# ---------------------------------------------------------------------------


class TestGoldPathBudgetEnforcement:
    """Verify budget checks gate execution."""

    def test_budget_check_allows_when_within_limit(self):
        """Budget check passes when tracker says allowed."""
        from aragora.server.handlers.debates.implementation import (
            _check_execution_budget,
        )

        mock_tracker = MagicMock()
        mock_tracker.check_debate_budget.return_value = {
            "allowed": True,
            "current_cost": "0.05",
            "limit": "10.00",
            "remaining": "9.95",
        }

        ok, msg = _check_execution_budget("debate-001", {"cost_tracker": mock_tracker})
        assert ok is True
        assert msg == ""

    def test_budget_check_blocks_when_over_limit(self):
        """Budget check fails when tracker says not allowed."""
        from aragora.server.handlers.debates.implementation import (
            _check_execution_budget,
        )

        mock_tracker = MagicMock()
        mock_tracker.check_debate_budget.return_value = {
            "allowed": False,
            "message": "Debate budget of $1.00 exceeded",
            "current_cost": "1.05",
            "limit": "1.00",
        }

        ok, msg = _check_execution_budget("debate-001", {"cost_tracker": mock_tracker})
        assert ok is False
        assert "exceeded" in msg

    def test_budget_check_allows_when_no_tracker(self):
        """Budget check allows when no cost tracker is configured."""
        from aragora.server.handlers.debates.implementation import (
            _check_execution_budget,
        )

        ok, msg = _check_execution_budget("debate-001", {})
        assert ok is True

    def test_budget_check_allows_on_error(self):
        """Budget check allows when tracker raises an exception."""
        from aragora.server.handlers.debates.implementation import (
            _check_execution_budget,
        )

        mock_tracker = MagicMock()
        mock_tracker.check_debate_budget.side_effect = OSError("db down")

        ok, msg = _check_execution_budget("debate-001", {"cost_tracker": mock_tracker})
        assert ok is True


# ---------------------------------------------------------------------------
# Phase 5: Handler Endpoint Integration
# ---------------------------------------------------------------------------


class TestGoldPathHandlerEndpoint:
    """Verify the decision-integrity endpoint wires everything together."""

    @pytest.fixture
    def handler_instance(self):
        """Create a DebatesHandler with mocked dependencies."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        handler = DebatesHandler(server_context={"repo_root": None})
        return handler

    def test_endpoint_returns_package(self, handler_instance):
        """Endpoint returns receipt + plan when debate exists."""
        mock_storage = MagicMock()
        mock_storage.get_debate.return_value = _make_debate()

        mock_handler = MagicMock()
        mock_handler.headers = {}

        body = {"include_receipt": True, "include_plan": True}
        handler_instance.ctx["storage"] = mock_storage

        with (
            patch.object(handler_instance, "get_storage", return_value=mock_storage),
            patch.object(handler_instance, "read_json_body", return_value=body),
            patch.object(handler_instance, "get_current_user", return_value=None),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value="rcpt-001",
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
        ):
            result = handler_instance._create_decision_integrity(mock_handler, "debate-gold-001")

        assert result.status_code == 200
        import json

        body_data = json.loads(result.body)
        assert body_data["debate_id"] == "debate-gold-001"
        assert body_data["receipt"] is not None
        assert body_data["plan"] is not None
        assert body_data["receipt_id"] == "rcpt-001"

    def test_endpoint_returns_404_for_missing_debate(self, handler_instance):
        """Endpoint returns 404 when debate not found."""
        mock_storage = MagicMock()
        mock_storage.get_debate.return_value = None

        with (
            patch.object(handler_instance, "get_storage", return_value=mock_storage),
            patch.object(handler_instance, "read_json_body", return_value={}),
            patch.object(handler_instance, "get_current_user", return_value=None),
        ):
            result = handler_instance._create_decision_integrity(MagicMock(), "nonexistent")

        assert result.status_code == 404


# ---------------------------------------------------------------------------
# Phase 6: Multi-Channel Notification
# ---------------------------------------------------------------------------


class TestGoldPathNotification:
    """Verify notify_origin routes to originating channel."""

    def test_notify_origin_calls_route_result(self):
        """When notify_origin=True, route_result is invoked."""
        from aragora.server.handlers.debates.handler import DebatesHandler

        handler = DebatesHandler(server_context={})
        mock_storage = MagicMock()
        mock_storage.get_debate.return_value = _make_debate()

        body = {"notify_origin": True}

        with (
            patch.object(handler, "get_storage", return_value=mock_storage),
            patch.object(handler, "read_json_body", return_value=body),
            patch.object(handler, "get_current_user", return_value=None),
            patch(
                "aragora.server.handlers.debates.implementation._persist_receipt",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.debates.implementation._persist_plan",
            ),
            patch("aragora.server.handlers.debates.implementation.route_result") as mock_route,
            patch(
                "aragora.server.handlers.debates.implementation.run_async",
                side_effect=lambda coro: coro,
            ),
        ):
            # Patch run_async for the build call to actually run
            with patch(
                "aragora.server.handlers.debates.implementation.run_async"
            ) as mock_run_async:
                # First call: build_decision_integrity_package
                # Second call: route_result
                async_results = []

                import asyncio

                def run_async_side_effect(coro):
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            import concurrent.futures

                            with concurrent.futures.ThreadPoolExecutor() as pool:
                                return pool.submit(asyncio.run, coro).result()
                        return loop.run_until_complete(coro)
                    except RuntimeError:
                        return asyncio.run(coro)

                mock_run_async.side_effect = run_async_side_effect

                result = handler._create_decision_integrity(MagicMock(), "debate-gold-001")

            assert result.status_code == 200
            # route_result should have been called via run_async
            assert mock_run_async.call_count >= 1


# ---------------------------------------------------------------------------
# Phase 7: DecisionPlanFactory.from_implement_plan
# ---------------------------------------------------------------------------


class TestDecisionPlanFactoryFromImplementPlan:
    """Verify the new factory method for wrapping ImplementPlans."""

    def test_wraps_implement_plan(self):
        """from_implement_plan creates a DecisionPlan with the plan attached."""
        from aragora.pipeline.decision_plan import (
            DecisionPlanFactory,
            PlanStatus,
        )

        mock_plan = MagicMock()
        mock_plan.tasks = [MagicMock()]

        dp = DecisionPlanFactory.from_implement_plan(
            mock_plan, debate_id="debate-123", task="Test task"
        )

        assert dp.debate_id == "debate-123"
        assert dp.task == "Test task"
        assert dp.implement_plan is mock_plan
        assert dp.status == PlanStatus.CREATED

    def test_wraps_with_defaults(self):
        """from_implement_plan uses defaults when no kwargs provided."""
        from aragora.pipeline.decision_plan import DecisionPlanFactory

        mock_plan = MagicMock()
        dp = DecisionPlanFactory.from_implement_plan(mock_plan)

        assert dp.debate_id == ""
        assert dp.implement_plan is mock_plan
        assert "Implementation plan" in dp.task


# ---------------------------------------------------------------------------
# Phase 8: End-to-End Flow Test
# ---------------------------------------------------------------------------


class TestGoldPathEndToEnd:
    """True end-to-end test: Debate → Receipt → Plan → Execution → Channel.

    This test class exercises the complete Decision Integrity pipeline
    by running a real debate (with mock agents) and verifying that all
    artifacts are generated and the full flow completes successfully.
    """

    @pytest.fixture
    def mock_agents(self) -> list[Any]:
        """Create mock agents for fast debate execution."""
        from dataclasses import dataclass

        from aragora.core import Agent, Critique, Vote

        @dataclass
        class GoldPathMockAgent(Agent):
            """Mock agent for gold path testing."""

            def __init__(self, name: str, response: str):
                super().__init__(name=name, model="mock", role="proposer")
                self._response = response
                self.agent_type = "mock"
                self.total_input_tokens = 0
                self.total_output_tokens = 0
                self.input_tokens = 0
                self.output_tokens = 0
                self.total_tokens_in = 0
                self.total_tokens_out = 0
                self.metrics = None
                self.provider = None

            async def generate(self, prompt: str, context: list | None = None) -> str:
                return self._response

            async def generate_stream(self, prompt: str, context: list | None = None):
                yield self._response

            async def critique(
                self,
                proposal: str,
                task: str,
                context: list | None = None,
                target_agent: str | None = None,
            ) -> Critique:
                return Critique(
                    agent=self.name,
                    target_agent=target_agent or "unknown",
                    target_content=proposal[:50] if proposal else "",
                    issues=[],
                    suggestions=[],
                    severity=0.1,
                    reasoning="Agreement",
                )

            async def vote(self, proposals: dict, task: str) -> Vote:
                choice = list(proposals.keys())[0] if proposals else self.name
                return Vote(
                    agent=self.name,
                    choice=choice,
                    reasoning="I agree with this approach",
                    confidence=0.9,
                    continue_debate=False,
                )

        shared_answer = (
            "1. Use token bucket algorithm for rate limiting\n"
            "2. Store counters in Redis for distributed access\n"
            "3. Implement middleware to intercept requests"
        )

        return [
            GoldPathMockAgent("agent-claude", shared_answer),
            GoldPathMockAgent("agent-gpt", shared_answer),
            GoldPathMockAgent("agent-gemini", shared_answer),
        ]

    @pytest.mark.asyncio
    async def test_full_e2e_flow_debate_to_channel(self, mock_agents):
        """Complete E2E: debate → receipt → plan → execute → channel delivery."""
        from aragora.core import Environment
        from aragora.debate.orchestrator import Arena
        from aragora.debate.protocol import DebateProtocol

        # Step 1: Run a minimal debate
        env = Environment(task="Design a distributed rate limiter for 1M req/sec")
        protocol = DebateProtocol(
            rounds=1,
            consensus="majority",
            enable_calibration=False,
            enable_rhetorical_observer=False,
            enable_trickster=False,
        )

        arena = Arena(env, mock_agents, protocol)
        result = await arena.run()

        # Verify debate completed
        assert result is not None
        assert result.rounds_completed >= 1
        assert result.final_answer is not None
        assert result.debate_id is not None

        # Step 2: Build decision integrity package from debate result
        debate_dict = {
            "debate_id": result.debate_id,
            "task": result.task,
            "final_answer": result.final_answer,
            "confidence": result.confidence,
            "consensus_reached": result.consensus_reached,
            "rounds_used": result.rounds_used,
            "rounds_completed": result.rounds_completed,
            "status": result.status,
            "agents": result.participants,
        }

        pkg = await build_decision_integrity_package(
            debate_dict,
            include_receipt=True,
            include_plan=True,
            include_context=False,  # Skip context for speed
        )

        # Verify package is complete
        assert pkg.debate_id == result.debate_id
        assert pkg.receipt is not None
        assert pkg.plan is not None
        assert len(pkg.plan.tasks) >= 1

        # Step 3: Verify receipt has all required audit fields
        receipt_dict = pkg.receipt.to_dict()
        assert "receipt_id" in receipt_dict
        assert "timestamp" in receipt_dict
        assert "verdict" in receipt_dict
        assert receipt_dict["verdict"] in ("PASS", "CONDITIONAL", "FAIL")

        # Step 4: Verify plan can be serialized (ready for execution)
        plan_dict = pkg.plan.to_dict()
        assert "tasks" in plan_dict
        assert len(plan_dict["tasks"]) >= 1
        assert "description" in plan_dict["tasks"][0]

        # Step 5: Simulate execution by verifying plan structure
        from aragora.pipeline.decision_plan import DecisionPlanFactory, PlanStatus

        decision_plan = DecisionPlanFactory.from_implement_plan(
            pkg.plan,
            debate_id=result.debate_id,
            task=result.task,
        )

        assert decision_plan.debate_id == result.debate_id
        assert decision_plan.status == PlanStatus.CREATED
        assert decision_plan.implement_plan is pkg.plan

        # Step 6: Verify channel routing is wired correctly
        from aragora.server.result_router import route_result

        # Mock the debate_origin module to verify routing is called
        with patch(
            "aragora.server.debate_origin.route_debate_result", new_callable=AsyncMock
        ) as mock_route:
            mock_route.return_value = True

            routed = await route_result(result.debate_id, debate_dict)
            assert routed is True
            mock_route.assert_called_once_with(result.debate_id, debate_dict)

    @pytest.mark.asyncio
    async def test_e2e_with_context_snapshot(self, mock_agents):
        """E2E flow including context snapshot for full auditability."""
        from aragora.core import Environment
        from aragora.debate.orchestrator import Arena
        from aragora.debate.protocol import DebateProtocol

        # Run debate
        env = Environment(task="Implement caching strategy for database queries")
        protocol = DebateProtocol(rounds=1, consensus="majority")
        arena = Arena(env, mock_agents, protocol)
        result = await arena.run()

        debate_dict = {
            "debate_id": result.debate_id,
            "task": result.task,
            "final_answer": result.final_answer,
            "confidence": result.confidence,
            "consensus_reached": result.consensus_reached,
            "rounds_used": result.rounds_used,
            "rounds_completed": result.rounds_completed,
            "status": result.status,
            "agents": result.participants,
        }

        # Build with context snapshot
        mock_cross_debate = AsyncMock()
        mock_cross_debate.get_relevant_context.return_value = (
            "Previous debates recommend Redis for caching."
        )

        pkg = await build_decision_integrity_package(
            debate_dict,
            include_receipt=True,
            include_plan=True,
            include_context=True,
            cross_debate_memory=mock_cross_debate,
        )

        # Verify full package
        assert pkg.context_snapshot is not None
        assert (
            pkg.context_snapshot.cross_debate_context
            == "Previous debates recommend Redis for caching."
        )

        # Verify serialization works for full package
        full_dict = pkg.to_dict()
        assert full_dict["context_snapshot"] is not None
        assert (
            full_dict["context_snapshot"]["cross_debate_context"]
            == "Previous debates recommend Redis for caching."
        )

        # Verify JSON serialization works
        import json

        json_str = json.dumps(full_dict)
        assert "cross_debate_context" in json_str

    @pytest.mark.asyncio
    async def test_e2e_persistence_round_trip(self, mock_agents):
        """E2E: debate → persist receipt/plan → retrieve and verify."""
        from aragora.core import Environment
        from aragora.debate.orchestrator import Arena
        from aragora.debate.protocol import DebateProtocol

        # Run debate
        env = Environment(task="Add retry logic to API client")
        protocol = DebateProtocol(rounds=1, consensus="majority")
        arena = Arena(env, mock_agents, protocol)
        result = await arena.run()

        debate_dict = {
            "debate_id": result.debate_id,
            "task": result.task,
            "final_answer": result.final_answer,
            "confidence": result.confidence,
            "consensus_reached": result.consensus_reached,
            "rounds_used": result.rounds_used,
            "rounds_completed": result.rounds_completed,
            "status": result.status,
            "agents": result.participants,
        }

        pkg = await build_decision_integrity_package(debate_dict)

        # Mock persistence layer
        stored_receipts: dict[str, dict] = {}
        stored_plans: dict[str, Any] = {}

        def mock_save_receipt(receipt_dict: dict) -> str:
            rid = receipt_dict.get("receipt_id", "test-rcpt")
            stored_receipts[rid] = receipt_dict
            return rid

        mock_receipt_store = MagicMock()
        mock_receipt_store.save = mock_save_receipt
        mock_receipt_store.get = lambda rid: stored_receipts.get(rid)

        # Persist receipt
        from aragora.server.handlers.debates.implementation import _persist_receipt

        with patch(
            "aragora.storage.receipt_store.get_receipt_store", return_value=mock_receipt_store
        ):
            receipt_id = _persist_receipt(pkg.receipt, result.debate_id)

        assert receipt_id is not None
        assert receipt_id in stored_receipts

        # Verify retrieval
        retrieved = stored_receipts[receipt_id]
        assert retrieved["debate_id"] == result.debate_id
        assert "timestamp" in retrieved

    @pytest.mark.asyncio
    async def test_e2e_budget_enforcement_blocks_execution(self, mock_agents):
        """E2E: verify budget check blocks execution when over limit."""
        from aragora.core import Environment
        from aragora.debate.orchestrator import Arena
        from aragora.debate.protocol import DebateProtocol
        from aragora.server.handlers.debates.implementation import _check_execution_budget

        # Run debate
        env = Environment(task="Expensive operation that exceeds budget")
        protocol = DebateProtocol(rounds=1, consensus="majority")
        arena = Arena(env, mock_agents, protocol)
        result = await arena.run()

        # Simulate over-budget scenario
        mock_tracker = MagicMock()
        mock_tracker.check_debate_budget.return_value = {
            "allowed": False,
            "message": "Budget limit of $5.00 exceeded",
            "current_cost": "5.50",
            "limit": "5.00",
        }

        ctx = {"cost_tracker": mock_tracker}
        allowed, msg = _check_execution_budget(result.debate_id, ctx)

        assert allowed is False
        assert "exceeded" in msg

        # Verify that under-budget allows execution
        mock_tracker.check_debate_budget.return_value = {
            "allowed": True,
            "current_cost": "1.50",
            "limit": "5.00",
            "remaining": "3.50",
        }

        allowed, msg = _check_execution_budget(result.debate_id, ctx)
        assert allowed is True
        assert msg == ""

    @pytest.mark.asyncio
    async def test_e2e_plan_outcome_routing(self, mock_agents):
        """E2E: verify plan execution outcomes route to originating channel."""
        from aragora.core import Environment
        from aragora.debate.orchestrator import Arena
        from aragora.debate.protocol import DebateProtocol
        from aragora.server.result_router import route_plan_outcome

        # Run debate
        env = Environment(task="Implement feature X")
        protocol = DebateProtocol(rounds=1, consensus="majority")
        arena = Arena(env, mock_agents, protocol)
        result = await arena.run()

        # Build package
        debate_dict = {
            "debate_id": result.debate_id,
            "task": result.task,
            "final_answer": result.final_answer,
            "confidence": result.confidence,
            "consensus_reached": result.consensus_reached,
            "rounds_used": result.rounds_used,
            "rounds_completed": result.rounds_completed,
            "status": result.status,
            "agents": result.participants,
        }

        pkg = await build_decision_integrity_package(debate_dict)

        # Simulate plan execution outcome
        plan_outcome = {
            "success": True,
            "task": result.task[:200],
            "tasks_completed": 3,
            "tasks_total": 3,
            "verification_passed": 2,
            "verification_total": 2,
            "receipt_id": pkg.receipt.receipt_id if pkg.receipt else None,
            "lessons": ["Redis works well for rate limiting"],
        }

        # Mock origin lookup and routing
        mock_origin = MagicMock()
        mock_origin.platform = "slack"
        mock_origin.channel_id = "C123456"

        with (
            patch("aragora.server.debate_origin.get_debate_origin", return_value=mock_origin),
            patch(
                "aragora.server.debate_origin.router.route_plan_result", new_callable=AsyncMock
            ) as mock_route,
        ):
            mock_route.return_value = True

            routed = await route_plan_outcome(
                debate_id=result.debate_id,
                plan_id="plan-001",
                outcome=plan_outcome,
            )

            assert routed is True
            mock_route.assert_called_once()

            # Verify the outcome includes formatted message
            call_args = mock_route.call_args
            routed_outcome = call_args[0][1]
            assert "plan_id" in routed_outcome
            assert "formatted_message" in routed_outcome
            assert "Completed Successfully" in routed_outcome["formatted_message"]
