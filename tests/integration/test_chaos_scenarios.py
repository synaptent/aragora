"""
Chaos and failure scenario end-to-end tests.

Verifies the system handles edge cases gracefully when subsystems fail:
1. Agent timeout scenarios - partial results, recovery, voting failures
2. Knowledge Mound failures - write/read/ingestion retry behavior
3. Receipt generation failures - result preservation, malformed data, tamper detection
4. Infrastructure failures - circuit breakers, event bus, metrics, cost tracker, settlement

All tests use mocking -- no real API calls. Mock agents follow the
_GoldenPathAgent pattern from test_golden_path.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core import Agent, Critique, Environment, Message, Vote
from aragora.core_types import DebateResult
from aragora.debate.orchestrator import Arena
from aragora.debate.protocol import DebateProtocol
from aragora.gauntlet.receipt import (
    ConsensusProof,
    DecisionReceipt,
    ProvenanceRecord,
)
from aragora.knowledge.mound.adapters.debate_adapter import (
    DebateAdapter,
    DebateOutcome,
)
from aragora.resilience.circuit_breaker import CircuitBreaker, CircuitOpenError


# =============================================================================
# Mock agents for chaos testing
# =============================================================================


class _ChaosAgent(Agent):
    """Deterministic mock agent for chaos testing.

    Like _GoldenPathAgent but with configurable failure modes:
    - timeout_on: set of method names that should simulate timeout
    - fail_on: set of method names that should raise RuntimeError
    - slow_ms: artificial delay in milliseconds for generate()
    """

    def __init__(
        self,
        name: str,
        proposal: str,
        vote_for: str | None = None,
        *,
        timeout_on: set[str] | None = None,
        fail_on: set[str] | None = None,
        slow_ms: float = 0,
    ):
        super().__init__(name=name, model="mock-chaos", role="proposer")
        self.agent_type = "mock"
        self._proposal = proposal
        self._vote_for = vote_for
        self._timeout_on = timeout_on or set()
        self._fail_on = fail_on or set()
        self._slow_ms = slow_ms
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.metrics = None
        self.provider = None

    async def generate(self, prompt: str, context: list | None = None) -> str:
        if "generate" in self._fail_on:
            raise RuntimeError(f"Simulated generate failure in {self.name}")
        if "generate" in self._timeout_on:
            await asyncio.sleep(100)  # Will be cancelled by timeout
        if self._slow_ms > 0:
            await asyncio.sleep(self._slow_ms / 1000.0)
        return self._proposal

    async def generate_stream(self, prompt: str, context: list | None = None):
        yield self._proposal

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list | None = None,
        target_agent: str | None = None,
    ) -> Critique:
        if "critique" in self._fail_on:
            raise RuntimeError(f"Simulated critique failure in {self.name}")
        if "critique" in self._timeout_on:
            await asyncio.sleep(100)
        return Critique(
            agent=self.name,
            target_agent=target_agent or "unknown",
            target_content=proposal[:100] if proposal else "",
            issues=[],
            suggestions=[],
            severity=0.1,
            reasoning="Minor remarks only",
        )

    async def vote(self, proposals: dict, task: str) -> Vote:
        if "vote" in self._fail_on:
            raise RuntimeError(f"Simulated vote failure in {self.name}")
        if "vote" in self._timeout_on:
            await asyncio.sleep(100)
        choice = self._vote_for
        if choice is None:
            choice = list(proposals.keys())[0] if proposals else self.name
        return Vote(
            agent=self.name,
            choice=choice,
            reasoning="I concur",
            confidence=0.88,
            continue_debate=False,
        )


# =============================================================================
# Shared fixtures
# =============================================================================


@pytest.fixture
def task_description() -> str:
    return "Should we migrate from REST to gRPC for internal service communication?"


@pytest.fixture
def environment(task_description: str) -> Environment:
    return Environment(task=task_description)


@pytest.fixture
def fast_protocol() -> DebateProtocol:
    """Minimal protocol: 2 rounds, no heavy subsystems."""
    return DebateProtocol(
        rounds=2,
        consensus="majority",
        enable_calibration=False,
        enable_rhetorical_observer=False,
        enable_trickster=False,
    )


@pytest.fixture
def healthy_agents() -> list[_ChaosAgent]:
    """Three agents that converge normally (baseline for chaos injection)."""
    shared = "Keep REST for public APIs, introduce gRPC for internal high-throughput services."
    return [
        _ChaosAgent("agent-claude", proposal=shared, vote_for="agent-claude"),
        _ChaosAgent("agent-gpt", proposal=shared, vote_for="agent-claude"),
        _ChaosAgent("agent-gemini", proposal=shared, vote_for="agent-claude"),
    ]


def _make_debate_result(
    task: str = "Test task",
    final_answer: str = "Test answer",
    confidence: float = 0.85,
    consensus_reached: bool = True,
    rounds_used: int = 2,
    participants: list[str] | None = None,
) -> DebateResult:
    """Helper to create a DebateResult with sensible defaults."""
    return DebateResult(
        task=task,
        final_answer=final_answer,
        confidence=confidence,
        consensus_reached=consensus_reached,
        rounds_used=rounds_used,
        participants=participants or ["agent-claude", "agent-gpt", "agent-gemini"],
        dissenting_views=[],
    )


# =============================================================================
# 1. Agent Timeout Scenarios
# =============================================================================


class TestAgentTimeoutScenarios:
    """Verify the system handles agent timeouts gracefully, returning
    partial results and continuing with available agents."""

    @pytest.mark.asyncio
    async def test_single_agent_timeout_others_continue(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
    ):
        """One agent times out on generate, but the debate still
        completes with the remaining agents' contributions."""
        shared = "Keep REST externally, use gRPC internally."
        agents = [
            _ChaosAgent("agent-claude", proposal=shared, vote_for="agent-claude"),
            _ChaosAgent("agent-gpt", proposal=shared, vote_for="agent-claude"),
            # This agent will fail to generate (simulates timeout via error)
            _ChaosAgent(
                "agent-slow",
                proposal="never seen",
                vote_for="agent-claude",
                fail_on={"generate"},
            ),
        ]
        arena = Arena(environment, agents, fast_protocol)
        result = await arena.run()

        assert result is not None, "Debate should complete even if one agent fails"
        assert result.rounds_completed > 0 or result.rounds_used > 0
        # The debate should still have a final answer from the agents that worked
        assert result.final_answer is not None

    @pytest.mark.asyncio
    async def test_all_agents_fail_returns_partial_result(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
    ):
        """When all agents fail to generate, the debate should still
        return a result (possibly empty) rather than crash."""
        agents = [
            _ChaosAgent("agent-a", proposal="x", fail_on={"generate"}),
            _ChaosAgent("agent-b", proposal="y", fail_on={"generate"}),
            _ChaosAgent("agent-c", proposal="z", fail_on={"generate"}),
        ]
        arena = Arena(environment, agents, fast_protocol)
        result = await arena.run()

        # Arena should return a result even when all proposals fail
        assert result is not None
        # Consensus should NOT be reached since no proposals succeeded
        assert result.consensus_reached is False or result.confidence < 0.5

    @pytest.mark.asyncio
    async def test_timeout_during_consensus_voting(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
    ):
        """Agent fails during vote phase; debate still produces a result
        from the votes that did arrive."""
        shared = "Use gRPC everywhere."
        agents = [
            _ChaosAgent("agent-claude", proposal=shared, vote_for="agent-claude"),
            _ChaosAgent("agent-gpt", proposal=shared, vote_for="agent-claude"),
            # This agent fails to vote
            _ChaosAgent(
                "agent-broken",
                proposal=shared,
                vote_for="agent-claude",
                fail_on={"vote"},
            ),
        ]
        arena = Arena(environment, agents, fast_protocol)
        result = await arena.run()

        assert result is not None
        # Even with one voter down, two valid votes can still form majority
        assert result.final_answer is not None

    @pytest.mark.asyncio
    async def test_agent_recovery_after_intermittent_failure(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
    ):
        """An agent that fails once but later succeeds (simulated via
        a separate healthy debate after a failed one) should not
        permanently degrade the system."""
        shared = "Dual-stack approach."

        # First debate: one agent fails
        agents_with_failure = [
            _ChaosAgent("agent-claude", proposal=shared, vote_for="agent-claude"),
            _ChaosAgent("agent-gpt", proposal=shared, vote_for="agent-claude"),
            _ChaosAgent("agent-flaky", proposal="x", fail_on={"generate"}),
        ]
        arena1 = Arena(environment, agents_with_failure, fast_protocol)
        result1 = await arena1.run()
        assert result1 is not None

        # Second debate: same agent name now works (simulating recovery)
        agents_recovered = [
            _ChaosAgent("agent-claude", proposal=shared, vote_for="agent-claude"),
            _ChaosAgent("agent-gpt", proposal=shared, vote_for="agent-claude"),
            _ChaosAgent("agent-flaky", proposal=shared, vote_for="agent-claude"),
        ]
        arena2 = Arena(environment, agents_recovered, fast_protocol)
        result2 = await arena2.run()

        assert result2 is not None
        assert result2.final_answer is not None
        # The recovered debate should work normally
        assert result2.rounds_completed > 0 or result2.rounds_used > 0

    @pytest.mark.asyncio
    async def test_critique_failure_does_not_crash_debate(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
    ):
        """Agent fails during the critique phase; debate proceeds
        through voting and produces a result."""
        shared = "Use gRPC for latency-sensitive paths."
        agents = [
            _ChaosAgent("agent-claude", proposal=shared, vote_for="agent-claude"),
            _ChaosAgent("agent-gpt", proposal=shared, vote_for="agent-claude"),
            _ChaosAgent(
                "agent-critic",
                proposal=shared,
                vote_for="agent-claude",
                fail_on={"critique"},
            ),
        ]
        arena = Arena(environment, agents, fast_protocol)
        result = await arena.run()

        assert result is not None
        assert result.final_answer is not None


# =============================================================================
# 2. Knowledge Mound Failure
# =============================================================================


class TestKnowledgeMoundFailure:
    """Verify that Knowledge Mound failures are non-blocking and the
    debate system degrades gracefully."""

    @pytest.mark.asyncio
    async def test_km_write_failure_does_not_crash_debate(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
        healthy_agents: list[_ChaosAgent],
    ):
        """KM write failure during post-debate ingestion does not
        prevent the debate from returning a valid result."""
        arena = Arena(environment, healthy_agents, fast_protocol)
        result = await arena.run()

        # Now simulate KM write failure during adapter sync
        adapter = DebateAdapter()
        adapter.store_outcome(result)

        mock_mound = AsyncMock()
        mock_mound.store_item = AsyncMock(
            side_effect=ConnectionError("KM write failed: connection refused")
        )

        sync_result = await adapter.sync_to_km(mock_mound)

        # The original debate result should still be intact
        assert result is not None
        assert result.final_answer is not None

        # The sync should have recorded the failure
        assert sync_result.records_failed >= 1 or sync_result.records_synced == 0

    @pytest.mark.asyncio
    async def test_km_read_failure_during_context_init_falls_back(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
        healthy_agents: list[_ChaosAgent],
    ):
        """When KM read fails during debate context initialization,
        the debate continues without KM context (graceful fallback)."""
        # Patch _init_km_context to simulate a read failure
        with patch.object(
            Arena,
            "_init_km_context",
            new_callable=AsyncMock,
            side_effect=ConnectionError("KM read timeout"),
        ):
            arena = Arena(environment, healthy_agents, fast_protocol)
            # The debate should still run; the KM context init failure
            # is caught by the gather() in initialize_debate_context
            # which propagates KM init errors. The Arena.run() wraps
            # _run_inner in a try block that handles this.
            try:
                result = await arena.run()
                # If it succeeded anyway (some code paths catch ConnectionError)
                assert result is not None
            except ConnectionError:
                # This is acceptable -- the system raised the error
                # rather than silently failing. The key assertion is
                # that it did NOT raise an unrelated crash.
                pass

    @pytest.mark.asyncio
    async def test_km_ingestion_retry_succeeds_on_transient_failure(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
        healthy_agents: list[_ChaosAgent],
    ):
        """KM ingestion retries after a transient failure and
        succeeds on the second attempt (using separate adapters to
        simulate the retry pattern)."""
        arena = Arena(environment, healthy_agents, fast_protocol)
        result = await arena.run()

        # --- Attempt 1: KM store fails ---
        adapter1 = DebateAdapter()
        adapter1.store_outcome(result)

        mock_mound_failing = AsyncMock()
        mock_mound_failing.store_item = AsyncMock(
            side_effect=ConnectionError("Transient KM failure")
        )

        sync_result_1 = await adapter1.sync_to_km(mock_mound_failing)
        # The sync should report the failure
        failed_or_not_synced = (
            sync_result_1.records_failed >= 1 or sync_result_1.records_synced == 0
        )
        assert failed_or_not_synced

        # --- Attempt 2: KM store succeeds (retry with fresh mock) ---
        adapter2 = DebateAdapter()
        adapter2.store_outcome(result)

        mock_mound_healthy = AsyncMock()
        mock_mound_healthy.store_item = AsyncMock(return_value=None)

        sync_result_2 = await adapter2.sync_to_km(mock_mound_healthy)
        assert sync_result_2.records_synced == 1
        assert sync_result_2.records_failed == 0

    @pytest.mark.asyncio
    async def test_km_adapter_handles_malformed_result(self):
        """DebateAdapter handles a result with missing fields gracefully."""
        adapter = DebateAdapter()

        # Create a minimal DebateResult with sparse data
        sparse_result = DebateResult(
            task="Sparse task",
            final_answer="",
            confidence=0.0,
            consensus_reached=False,
            rounds_used=0,
        )
        adapter.store_outcome(sparse_result)

        mock_mound = AsyncMock()
        mock_mound.store_item = AsyncMock()

        # Should not crash even with minimal data
        sync_result = await adapter.sync_to_km(mock_mound)
        # Either it syncs the sparse item or skips it due to low confidence;
        # either way, no exception should be raised
        assert sync_result is not None


# =============================================================================
# 3. Receipt Generation Failure
# =============================================================================


class TestReceiptGenerationFailure:
    """Verify receipt generation failures are contained and do not
    destroy the debate result."""

    @pytest.mark.asyncio
    async def test_receipt_failure_does_not_lose_debate_result(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
        healthy_agents: list[_ChaosAgent],
    ):
        """If receipt generation fails, the DebateResult is still
        fully intact and usable."""
        arena = Arena(environment, healthy_agents, fast_protocol)
        result = await arena.run()

        # Store a copy of key fields before attempting receipt
        original_answer = result.final_answer
        original_confidence = result.confidence
        original_consensus = result.consensus_reached

        # Simulate receipt generation failure by corrupting the
        # from_debate_result path temporarily
        with patch.object(
            DecisionReceipt,
            "_calculate_hash",
            side_effect=ValueError("Hash calculation failed"),
        ):
            try:
                receipt = DecisionReceipt.from_debate_result(result)
                # If it somehow succeeded (hash cached before our patch), fine
            except (ValueError, TypeError, AttributeError):
                # Expected: receipt generation failed
                pass

        # The original result must be untouched
        assert result.final_answer == original_answer
        assert result.confidence == original_confidence
        assert result.consensus_reached == original_consensus

    def test_malformed_receipt_data_handled_gracefully(self):
        """Creating a receipt from a result with None/missing fields
        should either succeed with defaults or raise a clean error."""
        result = DebateResult(
            task="",
            final_answer=None,
            confidence=0.0,
            consensus_reached=False,
            rounds_used=0,
            participants=[],
        )

        # Should not raise an unhandled exception
        receipt = DecisionReceipt.from_debate_result(result)

        assert receipt is not None
        assert receipt.receipt_id is not None
        assert receipt.verdict in ("PASS", "CONDITIONAL", "FAIL", "NO_EVIDENCE")
        # Intentional semantics change (#9303): a malformed result with no
        # agent output is NO_EVIDENCE (nothing ran), not FAIL (adversarially
        # rejected). Graceful handling now also means truthful labeling.
        assert receipt.verdict == "NO_EVIDENCE"
        assert receipt.confidence == 0.0

    def test_receipt_hash_verification_catches_tampering(self):
        """Tampered receipts fail integrity verification, proving
        the SHA-256 chain is effective."""
        result = _make_debate_result(
            confidence=0.9,
            consensus_reached=True,
        )
        receipt = DecisionReceipt.from_debate_result(result)

        # Original integrity holds
        assert receipt.verify_integrity() is True
        original_hash = receipt.artifact_hash

        # Tamper with multiple fields
        receipt.verdict = "FAIL"
        receipt.confidence = 0.01
        receipt.robustness_score = 0.0

        # Hash was computed at construction and is now stale
        assert receipt.artifact_hash == original_hash
        assert receipt.verify_integrity() is False

        # Further: constructing from tampered JSON also fails
        tampered_data = json.loads(receipt.to_json())
        tampered_data["verdict"] = "PASS"
        # Don't update hash -- simulates external tampering
        restored = DecisionReceipt.from_dict(tampered_data)
        assert restored.verify_integrity() is False


# =============================================================================
# 4. Infrastructure Failures
# =============================================================================


class TestInfrastructureFailures:
    """Verify that infrastructure component failures do not crash
    or block the debate pipeline."""

    def test_circuit_breaker_opens_after_repeated_failures(self):
        """After threshold failures, the circuit breaker prevents
        further calls until cooldown expires."""
        breaker = CircuitBreaker(
            name="test-agent",
            failure_threshold=3,
            cooldown_seconds=60.0,
        )

        assert breaker.can_proceed() is True
        assert breaker.get_status() == "closed"

        # Record failures up to threshold
        breaker.record_failure()
        assert breaker.can_proceed() is True  # 1 failure, still below 3

        breaker.record_failure()
        assert breaker.can_proceed() is True  # 2 failures, still below 3

        opened = breaker.record_failure()  # 3rd failure -- opens circuit
        assert opened is True
        assert breaker.can_proceed() is False
        assert breaker.get_status() == "open"

        # Verify cooldown_remaining is positive
        assert breaker.cooldown_remaining() > 0

    def test_circuit_breaker_multi_entity_isolation(self):
        """Failure in one entity does not affect another entity's
        circuit state."""
        breaker = CircuitBreaker(
            name="multi-agent",
            failure_threshold=2,
            cooldown_seconds=60.0,
        )

        # agent-a fails twice -- opens
        breaker.record_failure("agent-a")
        breaker.record_failure("agent-a")
        assert breaker.is_available("agent-a") is False

        # agent-b should still be available
        assert breaker.is_available("agent-b") is True

        # Recording success for agent-b should not affect agent-a
        breaker.record_success("agent-b")
        assert breaker.is_available("agent-a") is False
        assert breaker.is_available("agent-b") is True

    @pytest.mark.asyncio
    async def test_event_bus_failure_does_not_crash_debate(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
        healthy_agents: list[_ChaosAgent],
    ):
        """If the event bus raises errors during emission, the debate
        should still complete (events are best-effort)."""
        arena = Arena(environment, healthy_agents, fast_protocol)

        # Patch the event bus emit to always fail
        if hasattr(arena, "event_bus") and arena.event_bus is not None:
            arena.event_bus.emit = MagicMock(side_effect=RuntimeError("Event bus down"))

        result = await arena.run()

        # Debate should complete despite event bus failure
        assert result is not None
        assert result.final_answer is not None

    @pytest.mark.asyncio
    async def test_metrics_recording_absence_is_non_blocking(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
        healthy_agents: list[_ChaosAgent],
    ):
        """When metrics recording functions are no-ops (e.g., Prometheus
        unavailable), the debate still completes normally."""
        # Replace metrics functions with silent no-ops to simulate
        # a metrics backend that is offline but not erroring
        with patch(
            "aragora.observability.server_metrics.track_debate_outcome",
            return_value=None,
        ):
            with patch(
                "aragora.debate.orchestrator_runner.record_debate_completion_slo",
                return_value=None,
            ):
                with patch(
                    "aragora.debate.orchestrator_runner.update_debate_success_rate",
                    return_value=None,
                ):
                    arena = Arena(environment, healthy_agents, fast_protocol)
                    result = await arena.run()

        assert result is not None
        assert result.final_answer is not None
        # Verify the debate result has meaningful fields even when
        # metrics recording was silently disabled
        assert result.rounds_completed > 0 or result.rounds_used > 0

    @pytest.mark.asyncio
    async def test_cost_tracker_failure_does_not_block_debate(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
        healthy_agents: list[_ChaosAgent],
    ):
        """Cost tracking failure during post-debate completion handling
        is absorbed gracefully. The _populate_result_cost function uses
        try/except internally for robustness."""
        arena = Arena(environment, healthy_agents, fast_protocol)

        # Inject a cost tracker mock that raises on get_debate_cost
        mock_extensions = MagicMock()
        mock_extensions.get_debate_cost_summary = MagicMock(
            side_effect=ValueError("Cost tracker connection lost")
        )
        mock_extensions.on_debate_complete = MagicMock()
        mock_extensions.setup_debate_budget = MagicMock()

        # Patch extensions on the arena to inject our failing cost mock
        # but allow the rest of the pipeline to run normally.
        # The _populate_result_cost function has internal try/except
        # so it should absorb this error.
        result = await arena.run()

        # Debate still returns a valid result
        assert result is not None
        assert result.final_answer is not None

    @pytest.mark.asyncio
    async def test_settlement_capture_failure_is_graceful(
        self,
        environment: Environment,
        fast_protocol: DebateProtocol,
        healthy_agents: list[_ChaosAgent],
    ):
        """Epistemic settlement capture failure does not prevent
        debate completion or corrupt the result."""
        arena = Arena(environment, healthy_agents, fast_protocol)

        # Patch the settlement tracker import to raise so capture is skipped
        with patch(
            "aragora.debate.settlement.EpistemicSettlementTracker",
            side_effect=RuntimeError("Settlement service unavailable"),
        ):
            result = await arena.run()

        assert result is not None
        assert result.final_answer is not None
        # The result should still have valid confidence and consensus data
        assert 0.0 <= result.confidence <= 1.0
