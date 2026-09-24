"""
Tests for GauntletStreamEmitter - real-time event streaming for Gauntlet stress-tests.

Tests lifecycle events, phase transitions, findings, probes, and verdict emission.
"""

from __future__ import annotations

import time
import pytest
from unittest.mock import MagicMock

from aragora.server.stream.gauntlet_emitter import (
    GauntletStreamEmitter,
    GauntletPhase,
    create_gauntlet_emitter,
)
from aragora.events.types import StreamEventType


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def capture_events():
    """Create a broadcast function that captures events."""
    events = []

    def broadcast(event):
        events.append(event)

    broadcast.events = events
    return broadcast


@pytest.fixture
def emitter(capture_events):
    """Create a GauntletStreamEmitter with event capture."""
    return GauntletStreamEmitter(broadcast_fn=capture_events, gauntlet_id="test-gauntlet")


# =============================================================================
# Test GauntletPhase
# =============================================================================


class TestGauntletPhase:
    """Tests for GauntletPhase constants."""

    def test_phase_values(self):
        """Phase constants should have expected values."""
        assert GauntletPhase.INIT == "init"
        assert GauntletPhase.RISK_ASSESSMENT == "risk_assessment"
        assert GauntletPhase.REDTEAM == "redteam"
        assert GauntletPhase.PROBING == "probing"
        assert GauntletPhase.DEEP_AUDIT == "deep_audit"
        assert GauntletPhase.VERIFICATION == "verification"
        assert GauntletPhase.AGGREGATION == "aggregation"
        assert GauntletPhase.VERDICT == "verdict"
        assert GauntletPhase.COMPLETE == "complete"


# =============================================================================
# Test GauntletStreamEmitter Initialization
# =============================================================================


class TestGauntletStreamEmitterInit:
    """Tests for GauntletStreamEmitter initialization."""

    def test_init_with_broadcast_fn(self, capture_events):
        """Should initialize with broadcast function."""
        emitter = GauntletStreamEmitter(broadcast_fn=capture_events)

        assert emitter.broadcast_fn is capture_events
        assert emitter._seq == 0
        assert emitter._phase == GauntletPhase.INIT

    def test_init_without_broadcast_fn(self):
        """Should work without broadcast function (logging only)."""
        emitter = GauntletStreamEmitter()

        assert emitter.broadcast_fn is None
        # Events should not raise error
        emitter._emit(StreamEventType.GAUNTLET_START, {"test": "data"})

    def test_init_with_gauntlet_id(self, capture_events):
        """Should store gauntlet ID."""
        emitter = GauntletStreamEmitter(
            broadcast_fn=capture_events,
            gauntlet_id="my-gauntlet-123",
        )

        assert emitter.gauntlet_id == "my-gauntlet-123"

    def test_init_default_gauntlet_id(self, capture_events):
        """Should default to empty gauntlet ID."""
        emitter = GauntletStreamEmitter(broadcast_fn=capture_events)

        assert emitter.gauntlet_id == ""


# =============================================================================
# Test Lifecycle Events
# =============================================================================


class TestLifecycleEvents:
    """Tests for gauntlet lifecycle events."""

    def test_emit_start(self, emitter, capture_events):
        """emit_start should emit GAUNTLET_START event."""
        emitter.emit_start(
            gauntlet_id="g-123",
            input_type="text",
            input_summary="Test input summary",
            agents=["claude", "gpt4"],
            config_summary={"max_rounds": 3},
        )

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_START
        assert event.data["gauntlet_id"] == "g-123"
        assert event.data["input_type"] == "text"
        assert event.data["input_summary"] == "Test input summary"
        assert event.data["agents"] == ["claude", "gpt4"]
        assert event.data["config"] == {"max_rounds": 3}
        assert "message" in event.data

    def test_emit_start_updates_state(self, emitter, capture_events):
        """emit_start should update emitter state."""
        emitter.emit_start("g-123", "text", "summary", [], {})

        assert emitter.gauntlet_id == "g-123"
        assert emitter._start_time is not None
        assert emitter._phase == GauntletPhase.INIT

    def test_emit_start_truncates_long_input(self, emitter, capture_events):
        """emit_start should truncate long input summaries."""
        long_input = "x" * 1000

        emitter.emit_start("g-123", "text", long_input, [], {})

        event = capture_events.events[0]
        assert len(event.data["input_summary"]) == 500

    def test_emit_complete(self, emitter, capture_events):
        """emit_complete should emit GAUNTLET_COMPLETE event."""
        emitter._start_time = time.time() - 60  # 60 seconds ago
        emitter._attack_count = 5
        emitter._probe_count = 10

        emitter.emit_complete(
            gauntlet_id="g-123",
            verdict="ROBUST",
            confidence=0.95,
            findings_count=3,
            duration_seconds=60.0,
        )

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_COMPLETE
        assert event.data["verdict"] == "ROBUST"
        assert event.data["confidence"] == 0.95
        assert event.data["findings_count"] == 3
        assert event.data["attacks_run"] == 5
        assert event.data["probes_run"] == 10
        assert event.data["duration_seconds"] == 60.0

    def test_emit_complete_updates_phase(self, emitter, capture_events):
        """emit_complete should update phase to COMPLETE."""
        emitter.emit_complete("g-123", "ROBUST", 0.9, 0, 30.0)

        assert emitter._phase == GauntletPhase.COMPLETE


# =============================================================================
# Test Phase Events
# =============================================================================


class TestPhaseEvents:
    """Tests for phase transition events."""

    def test_emit_phase(self, emitter, capture_events):
        """emit_phase should emit GAUNTLET_PHASE event."""
        emitter._start_time = time.time()

        emitter.emit_phase(GauntletPhase.REDTEAM, "Starting red team attacks")

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_PHASE
        assert event.data["phase"] == GauntletPhase.REDTEAM
        assert event.data["message"] == "Starting red team attacks"
        assert "elapsed_seconds" in event.data

    def test_emit_phase_updates_state(self, emitter, capture_events):
        """emit_phase should update current phase."""
        emitter.emit_phase(GauntletPhase.VERIFICATION)

        assert emitter._phase == GauntletPhase.VERIFICATION

    def test_emit_phase_default_message(self, emitter, capture_events):
        """emit_phase should provide default message."""
        emitter.emit_phase(GauntletPhase.PROBING)

        event = capture_events.events[0]
        assert "probing" in event.data["message"].lower()

    def test_emit_progress(self, emitter, capture_events):
        """emit_progress should emit GAUNTLET_PROGRESS event."""
        emitter._start_time = time.time()
        emitter._finding_count = 2
        emitter._attack_count = 5
        emitter._probe_count = 10
        emitter._phase = GauntletPhase.DEEP_AUDIT

        emitter.emit_progress(0.75, message="75% complete")

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_PROGRESS
        assert event.data["progress"] == 0.75
        assert event.data["phase"] == GauntletPhase.DEEP_AUDIT
        assert event.data["findings_count"] == 2
        assert event.data["attacks_run"] == 5
        assert event.data["probes_run"] == 10


# =============================================================================
# Test Agent Events
# =============================================================================


class TestAgentEvents:
    """Tests for agent-related events."""

    def test_emit_agent_active(self, emitter, capture_events):
        """emit_agent_active should emit GAUNTLET_AGENT_ACTIVE event."""
        emitter.emit_agent_active("claude", "red_team")

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_AGENT_ACTIVE
        assert event.data["agent"] == "claude"
        assert event.data["role"] == "red_team"
        assert event.agent == "claude"


# =============================================================================
# Test Attack Events
# =============================================================================


class TestAttackEvents:
    """Tests for attack-related events."""

    def test_emit_attack(self, emitter, capture_events):
        """emit_attack should emit GAUNTLET_ATTACK event."""
        emitter.emit_attack(
            attack_type="prompt_injection",
            agent="claude",
            target_summary="Test prompt with injection",
            success=True,
            severity=0.8,
        )

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_ATTACK
        assert event.data["attack_type"] == "prompt_injection"
        assert event.data["agent"] == "claude"
        assert event.data["success"] is True
        assert event.data["severity"] == 0.8
        assert event.data["attack_number"] == 1

    def test_emit_attack_increments_counter(self, emitter, capture_events):
        """emit_attack should increment attack counter."""
        assert emitter._attack_count == 0

        emitter.emit_attack("type1", "agent", "target", False)
        assert emitter._attack_count == 1

        emitter.emit_attack("type2", "agent", "target", True)
        assert emitter._attack_count == 2

        # Check attack numbers in events
        assert capture_events.events[0].data["attack_number"] == 1
        assert capture_events.events[1].data["attack_number"] == 2

    def test_emit_attack_truncates_target(self, emitter, capture_events):
        """emit_attack should truncate long target summaries."""
        long_target = "x" * 500

        emitter.emit_attack("type", "agent", long_target, False)

        event = capture_events.events[0]
        assert len(event.data["target_summary"]) == 200


# =============================================================================
# Test Finding Events
# =============================================================================


class TestFindingEvents:
    """Tests for finding-related events."""

    def test_emit_finding(self, emitter, capture_events):
        """emit_finding should emit GAUNTLET_FINDING event."""
        emitter.emit_finding(
            finding_id="f-001",
            severity="HIGH",
            category="prompt_injection",
            title="Critical vulnerability found",
            description="Detailed description of the finding",
            source="red_team_agent",
        )

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_FINDING
        assert event.data["finding_id"] == "f-001"
        assert event.data["severity"] == "HIGH"
        assert event.data["category"] == "prompt_injection"
        assert event.data["title"] == "Critical vulnerability found"
        assert event.data["source"] == "red_team_agent"
        assert event.data["finding_number"] == 1

    def test_emit_finding_increments_counter(self, emitter, capture_events):
        """emit_finding should increment finding counter."""
        emitter.emit_finding("f1", "LOW", "cat", "title1", "desc", "src")
        emitter.emit_finding("f2", "HIGH", "cat", "title2", "desc", "src")

        assert emitter._finding_count == 2

    def test_emit_finding_truncates_description(self, emitter, capture_events):
        """emit_finding should truncate long descriptions."""
        long_desc = "x" * 500

        emitter.emit_finding("f1", "LOW", "cat", "title", long_desc, "src")

        event = capture_events.events[0]
        assert len(event.data["description"]) == 300


# =============================================================================
# Test Probe Events
# =============================================================================


class TestProbeEvents:
    """Tests for probe-related events."""

    def test_emit_probe(self, emitter, capture_events):
        """emit_probe should emit GAUNTLET_PROBE event."""
        emitter.emit_probe(
            probe_type="jailbreak",
            agent="gpt4",
            vulnerability_found=True,
            severity="HIGH",
            description="Successfully bypassed safety filters",
        )

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_PROBE
        assert event.data["probe_type"] == "jailbreak"
        assert event.data["agent"] == "gpt4"
        assert event.data["vulnerability_found"] is True
        assert event.data["severity"] == "HIGH"
        assert event.data["probe_number"] == 1

    def test_emit_probe_increments_counter(self, emitter, capture_events):
        """emit_probe should increment probe counter."""
        emitter.emit_probe("p1", "agent", False)
        emitter.emit_probe("p2", "agent", True)

        assert emitter._probe_count == 2

    def test_emit_probe_without_severity(self, emitter, capture_events):
        """emit_probe should work without severity."""
        emitter.emit_probe("test", "agent", False)

        event = capture_events.events[0]
        assert event.data["severity"] is None


# =============================================================================
# Test Verification Events
# =============================================================================


class TestVerificationEvents:
    """Tests for verification-related events."""

    def test_emit_verification(self, emitter, capture_events):
        """emit_verification should emit GAUNTLET_VERIFICATION event."""
        emitter.emit_verification(
            claim="The system is secure",
            verified=True,
            method="z3",
            proof_hash="abc123",
        )

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_VERIFICATION
        assert event.data["verified"] is True
        assert event.data["method"] == "z3"
        assert event.data["proof_hash"] == "abc123"

    def test_emit_verification_truncates_claim(self, emitter, capture_events):
        """emit_verification should truncate long claims."""
        long_claim = "x" * 500

        emitter.emit_verification(long_claim, True, "test")

        event = capture_events.events[0]
        assert len(event.data["claim"]) == 200


# =============================================================================
# Test Risk Events
# =============================================================================


class TestRiskEvents:
    """Tests for risk-related events."""

    def test_emit_risk(self, emitter, capture_events):
        """emit_risk should emit GAUNTLET_RISK event."""
        emitter.emit_risk(
            risk_type="data_leakage",
            level="HIGH",
            description="Potential data exposure detected",
            confidence=0.85,
        )

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_RISK
        assert event.data["risk_type"] == "data_leakage"
        assert event.data["level"] == "HIGH"
        assert event.data["confidence"] == 0.85


# =============================================================================
# Test Verdict Events
# =============================================================================


class TestVerdictEvents:
    """Tests for verdict-related events."""

    def test_emit_verdict(self, emitter, capture_events):
        """emit_verdict should emit GAUNTLET_VERDICT event."""
        emitter.emit_verdict(
            verdict="VULNERABLE",
            confidence=0.92,
            risk_score=0.75,
            robustness_score=0.25,
            critical_count=1,
            high_count=3,
            medium_count=5,
            low_count=2,
        )

        assert len(capture_events.events) == 1
        event = capture_events.events[0]

        assert event.type == StreamEventType.GAUNTLET_VERDICT
        assert event.data["verdict"] == "VULNERABLE"
        assert event.data["confidence"] == 0.92
        assert event.data["risk_score"] == 0.75
        assert event.data["robustness_score"] == 0.25
        assert event.data["findings"]["critical"] == 1
        assert event.data["findings"]["high"] == 3
        assert event.data["findings"]["total"] == 11

    def test_emit_verdict_updates_phase(self, emitter, capture_events):
        """emit_verdict should update phase to VERDICT."""
        emitter.emit_verdict("OK", 0.9, 0.1, 0.9, 0, 0, 0, 0)

        assert emitter._phase == GauntletPhase.VERDICT


# =============================================================================
# Test Helper Methods
# =============================================================================


class TestHelperMethods:
    """Tests for helper methods."""

    def test_set_gauntlet_id(self, capture_events):
        """set_gauntlet_id should update gauntlet ID."""
        emitter = GauntletStreamEmitter(broadcast_fn=capture_events)

        emitter.set_gauntlet_id("new-id")

        assert emitter.gauntlet_id == "new-id"

    def test_sequence_numbers_increment(self, emitter, capture_events):
        """Events should have incrementing sequence numbers."""
        emitter.emit_phase("phase1")
        emitter.emit_phase("phase2")
        emitter.emit_phase("phase3")

        assert capture_events.events[0].seq == 1
        assert capture_events.events[1].seq == 2
        assert capture_events.events[2].seq == 3

    def test_broadcast_failure_handled(self, capture_events):
        """Broadcast failures should be handled gracefully."""

        def failing_broadcast(event):
            raise RuntimeError("Broadcast failed")

        emitter = GauntletStreamEmitter(broadcast_fn=failing_broadcast)

        # Should not raise
        emitter.emit_phase("test")


# =============================================================================
# Test Factory Function
# =============================================================================


class TestCreateGauntletEmitter:
    """Tests for create_gauntlet_emitter factory function."""

    def test_creates_emitter(self, capture_events):
        """create_gauntlet_emitter should create configured emitter."""
        emitter = create_gauntlet_emitter(broadcast_fn=capture_events)

        assert isinstance(emitter, GauntletStreamEmitter)
        assert emitter.broadcast_fn is capture_events

    def test_creates_emitter_without_broadcast(self):
        """create_gauntlet_emitter should work without broadcast function."""
        emitter = create_gauntlet_emitter()

        assert isinstance(emitter, GauntletStreamEmitter)
        assert emitter.broadcast_fn is None


# =============================================================================
# Integration Tests
# =============================================================================


class TestGauntletEmitterIntegration:
    """Integration tests for GauntletStreamEmitter."""

    def test_full_gauntlet_lifecycle(self, capture_events):
        """Should emit events for complete gauntlet lifecycle."""
        emitter = GauntletStreamEmitter(broadcast_fn=capture_events)

        # Start
        emitter.emit_start("g-001", "text", "Test input", ["claude"], {})

        # Phases
        emitter.emit_phase(GauntletPhase.RISK_ASSESSMENT)
        emitter.emit_agent_active("claude", "assessor")
        emitter.emit_progress(0.1)

        emitter.emit_phase(GauntletPhase.REDTEAM)
        emitter.emit_attack("injection", "claude", "test", False)
        emitter.emit_progress(0.3)

        emitter.emit_phase(GauntletPhase.PROBING)
        emitter.emit_probe("jailbreak", "claude", False)
        emitter.emit_progress(0.5)

        emitter.emit_phase(GauntletPhase.VERIFICATION)
        emitter.emit_verification("Claim", True, "z3")
        emitter.emit_progress(0.8)

        # Finding
        emitter.emit_finding("f1", "LOW", "cat", "Minor issue", "desc", "src")

        # Verdict and complete
        emitter.emit_verdict("ROBUST", 0.95, 0.1, 0.9, 0, 0, 0, 1)
        emitter.emit_complete("g-001", "ROBUST", 0.95, 1, 30.0)

        # Verify event sequence
        event_types = [e.type for e in capture_events.events]
        assert StreamEventType.GAUNTLET_START in event_types
        assert StreamEventType.GAUNTLET_PHASE in event_types
        assert StreamEventType.GAUNTLET_PROGRESS in event_types
        assert StreamEventType.GAUNTLET_ATTACK in event_types
        assert StreamEventType.GAUNTLET_PROBE in event_types
        assert StreamEventType.GAUNTLET_VERIFICATION in event_types
        assert StreamEventType.GAUNTLET_FINDING in event_types
        assert StreamEventType.GAUNTLET_VERDICT in event_types
        assert StreamEventType.GAUNTLET_COMPLETE in event_types

        # Verify all events have gauntlet_id
        for event in capture_events.events:
            assert event.data.get("gauntlet_id") == "g-001"

    def test_counters_persist_across_events(self, capture_events):
        """Counters should persist across different event types."""
        emitter = GauntletStreamEmitter(broadcast_fn=capture_events)
        emitter.gauntlet_id = "test"
        emitter._start_time = time.time()

        # Generate various events
        for i in range(3):
            emitter.emit_attack(f"attack_{i}", "agent", "target", i % 2 == 0)

        for i in range(5):
            emitter.emit_probe(f"probe_{i}", "agent", i % 3 == 0)

        for i in range(2):
            emitter.emit_finding(f"f{i}", "HIGH", "cat", f"title{i}", "desc", "src")

        # Verify final progress includes all counters
        emitter.emit_progress(1.0)

        progress_event = [
            e for e in capture_events.events if e.type == StreamEventType.GAUNTLET_PROGRESS
        ][0]
        assert progress_event.data["attacks_run"] == 3
        assert progress_event.data["probes_run"] == 5
        assert progress_event.data["findings_count"] == 2
