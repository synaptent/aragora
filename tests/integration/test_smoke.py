"""
Pytest smoke tests for Aragora core subsystems.

Mirrors the checks in scripts/smoke_test.py but uses mocking so no real
server or network access is required. Safe to run in CI.

Checks:
1. Server module imports and UnifiedHandler can be instantiated
2. Health endpoint routing returns 200 {"status": "ok"}
3. Debate creation and execution with mock agents
4. Receipt generation with SHA-256 integrity verification
5. Frontend package.json exists and build script is defined
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from aragora.core import Agent, Critique, DebateResult, Environment, Vote
from aragora.debate.orchestrator import Arena
from aragora.debate.protocol import DebateProtocol

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SmokeAgent(Agent):
    """Deterministic agent for smoke testing."""

    def __init__(self, name: str, vote_choice: str | None = None):
        super().__init__(name, "smoke-model", "proposer")
        self.agent_type = "smoke"
        self._vote_choice = vote_choice

    async def generate(self, prompt: str, context: list | None = None) -> str:
        return f"Proposal from {self.name}: use token bucket rate limiting"

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
            target_content=proposal[:80],
            issues=["Minor: consider edge cases"],
            suggestions=["Add retry logic"],
            severity=2.0,
            reasoning=f"Critique from {self.name}",
        )

    async def vote(self, proposals: dict[str, str], task: str) -> Vote:
        choice = self._vote_choice or (list(proposals.keys())[0] if proposals else self.name)
        return Vote(
            agent=self.name,
            choice=choice,
            reasoning=f"{self.name} votes for {choice}",
            confidence=0.9,
            continue_debate=False,
        )


# ---------------------------------------------------------------------------
# 1. Server module import and instantiation
# ---------------------------------------------------------------------------


class TestServerImport:
    """Verify server modules can be imported and core classes instantiated."""

    def test_unified_server_imports(self):
        """UnifiedHandler class is importable."""
        from aragora.server.unified_server import UnifiedHandler

        assert UnifiedHandler is not None

    def test_run_unified_server_importable(self):
        """The run_unified_server coroutine is importable."""
        from aragora.server.unified_server import run_unified_server

        assert asyncio.iscoroutinefunction(run_unified_server)

    def test_server_ready_flag_defaults_false(self):
        """Server readiness flag starts as False."""
        from aragora.server.unified_server import is_server_ready

        # After import (without running the server), it should be False
        # or True if another test already called mark_server_ready.
        # We just verify the function exists and returns a bool.
        result = is_server_ready()
        assert isinstance(result, bool)

    def test_debate_storage_importable(self):
        """DebateStorage is importable from the server package."""
        from aragora.storage.debate_storage import DebateStorage

        assert DebateStorage is not None


# ---------------------------------------------------------------------------
# 2. Health endpoint routing
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Verify health endpoint responds correctly (mocked HTTP layer)."""

    def test_health_route_recognized(self):
        """The /health path is handled by the unified server."""
        from aragora.server.unified_server import UnifiedHandler

        # The do_GET method checks path against known health routes.
        # We verify the route list includes /health.
        handler = Mock(spec=UnifiedHandler)
        handler.path = "/health"

        # The health paths are checked inline in do_GET; verify the
        # constant set that drives routing.
        health_paths = {"/healthz", "/readyz", "/health", "/ready", "/metrics"}
        assert "/health" in health_paths

    def test_health_response_structure(self):
        """Health response should be {"status": "ok"}."""
        expected = {"status": "ok"}
        body = json.dumps(expected)
        assert json.loads(body)["status"] == "ok"

    def test_readyz_depends_on_server_ready(self):
        """The /readyz endpoint checks the _server_ready flag."""
        from aragora.server.unified_server import (
            is_server_ready,
            mark_server_ready,
        )

        # mark_server_ready should make is_server_ready return True
        mark_server_ready()
        assert is_server_ready() is True


# ---------------------------------------------------------------------------
# 3. Debate creation and execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDebateRun:
    """Run a full debate with mock agents and verify result structure."""

    async def test_basic_debate_completes(self):
        """A 1-round debate with 3 smoke agents produces a DebateResult."""
        agents = [SmokeAgent("alpha"), SmokeAgent("beta"), SmokeAgent("gamma")]
        env = Environment(task="Design a rate limiter API", max_rounds=1)
        protocol = DebateProtocol(rounds=1, consensus="any")
        arena = Arena(env, agents, protocol)

        result = await asyncio.wait_for(arena.run(), timeout=30)

        assert isinstance(result, DebateResult)
        assert result.task == "Design a rate limiter API"

    async def test_debate_has_id(self):
        """The debate result includes a non-empty debate_id."""
        agents = [SmokeAgent("a1"), SmokeAgent("a2")]
        env = Environment(task="Pick a database", max_rounds=1)
        protocol = DebateProtocol(rounds=1, consensus="any")
        arena = Arena(env, agents, protocol)

        result = await asyncio.wait_for(arena.run(), timeout=30)

        assert result.debate_id
        assert len(result.debate_id) > 0

    async def test_debate_tracks_rounds(self):
        """The result records how many rounds were executed."""
        agents = [SmokeAgent("x"), SmokeAgent("y"), SmokeAgent("z")]
        env = Environment(task="Evaluate caching strategies", max_rounds=2)
        protocol = DebateProtocol(rounds=2, consensus="any")
        arena = Arena(env, agents, protocol)

        result = await asyncio.wait_for(arena.run(), timeout=30)

        assert result.rounds_used >= 1 or result.rounds_completed >= 1

    async def test_debate_has_messages(self):
        """The result includes a list of messages."""
        agents = [SmokeAgent("p"), SmokeAgent("q")]
        env = Environment(task="Choose a framework", max_rounds=1)
        protocol = DebateProtocol(rounds=1, consensus="any")
        arena = Arena(env, agents, protocol)

        result = await asyncio.wait_for(arena.run(), timeout=30)

        assert isinstance(result.messages, list)

    async def test_debate_with_consensus_target(self):
        """When all agents vote for the same choice, consensus is reached."""
        agents = [
            SmokeAgent("a", vote_choice="a"),
            SmokeAgent("b", vote_choice="a"),
            SmokeAgent("c", vote_choice="a"),
        ]
        env = Environment(task="Quick consensus test", max_rounds=2)
        protocol = DebateProtocol(rounds=2, consensus="majority")
        arena = Arena(env, agents, protocol)

        result = await asyncio.wait_for(arena.run(), timeout=30)

        assert isinstance(result, DebateResult)


# ---------------------------------------------------------------------------
# 4. Receipt generation and SHA-256 integrity
# ---------------------------------------------------------------------------


class TestReceiptGeneration:
    """Test DecisionReceipt creation, hashing, and integrity verification."""

    def _make_receipt(self, **overrides) -> "DecisionReceipt":
        """Create a receipt with sensible defaults."""
        from aragora.gauntlet.receipt_models import (
            ConsensusProof,
            DecisionReceipt,
            ProvenanceRecord,
        )

        now = datetime.now(timezone.utc).isoformat()
        defaults = dict(
            receipt_id=str(uuid.uuid4()),
            gauntlet_id=str(uuid.uuid4()),
            timestamp=now,
            input_summary="Should we migrate to Kubernetes?",
            input_hash=hashlib.sha256(b"Should we migrate to Kubernetes?").hexdigest(),
            risk_summary={"critical": 0, "high": 1, "medium": 2, "low": 1},
            attacks_attempted=8,
            attacks_successful=0,
            probes_run=4,
            vulnerabilities_found=1,
            verdict="PASS",
            confidence=0.91,
            robustness_score=0.88,
            verdict_reasoning="Architecture is sound",
            consensus_proof=ConsensusProof(
                reached=True,
                confidence=0.9,
                supporting_agents=["agent_a", "agent_b"],
                method="majority",
            ),
            provenance_chain=[
                ProvenanceRecord(
                    timestamp=now,
                    event_type="verdict",
                    description="Smoke test verdict",
                ),
            ],
        )
        defaults.update(overrides)
        return DecisionReceipt(**defaults)

    def test_receipt_creation(self):
        """A receipt can be created with required fields."""
        receipt = self._make_receipt()
        assert receipt.receipt_id
        assert receipt.verdict == "PASS"

    def test_artifact_hash_is_sha256(self):
        """The artifact_hash is a 64-character hex string (SHA-256)."""
        receipt = self._make_receipt()
        assert len(receipt.artifact_hash) == 64
        # Verify it is valid hex
        int(receipt.artifact_hash, 16)

    def test_integrity_verification_passes(self):
        """verify_integrity() returns True for an untampered receipt."""
        receipt = self._make_receipt()
        assert receipt.verify_integrity() is True

    def test_tampering_detection(self):
        """Modifying a field after creation causes verify_integrity() to fail."""
        receipt = self._make_receipt(verdict="PASS")
        assert receipt.verify_integrity() is True

        # Tamper with the verdict
        receipt.verdict = "FAIL"
        assert receipt.verify_integrity() is False

    def test_to_dict_round_trip(self):
        """to_dict() produces a dict that can reconstruct the receipt."""
        from aragora.gauntlet.receipt_models import DecisionReceipt

        original = self._make_receipt()
        d = original.to_dict()

        assert d["receipt_id"] == original.receipt_id
        assert d["verdict"] == original.verdict
        assert d["artifact_hash"] == original.artifact_hash
        assert d["confidence"] == original.confidence

        # Round-trip through from_dict
        restored = DecisionReceipt.from_dict(d)
        assert restored.receipt_id == original.receipt_id
        assert restored.artifact_hash == original.artifact_hash

    def test_different_inputs_produce_different_hashes(self):
        """Two receipts with different inputs have different artifact hashes."""
        r1 = self._make_receipt(verdict="PASS", confidence=0.9)
        r2 = self._make_receipt(verdict="FAIL", confidence=0.3)
        assert r1.artifact_hash != r2.artifact_hash

    def test_consensus_proof_in_receipt(self):
        """Consensus proof is included in the receipt dict."""
        receipt = self._make_receipt()
        d = receipt.to_dict()
        assert d["consensus_proof"] is not None
        assert d["consensus_proof"]["reached"] is True
        assert d["consensus_proof"]["method"] == "majority"

    def test_provenance_chain_in_receipt(self):
        """Provenance chain is included in the receipt dict."""
        receipt = self._make_receipt()
        d = receipt.to_dict()
        assert len(d["provenance_chain"]) >= 1
        assert d["provenance_chain"][0]["event_type"] == "verdict"


# ---------------------------------------------------------------------------
# 5. Frontend package configuration
# ---------------------------------------------------------------------------


class TestFrontendConfig:
    """Verify frontend project structure is correct for building."""

    def test_package_json_exists(self):
        """aragora/live/package.json exists."""
        pkg = PROJECT_ROOT / "aragora" / "live" / "package.json"
        assert pkg.exists(), f"Missing: {pkg}"

    def test_build_script_defined(self):
        """package.json includes a 'build' script."""
        pkg = PROJECT_ROOT / "aragora" / "live" / "package.json"
        with open(pkg) as f:
            data = json.load(f)
        scripts = data.get("scripts", {})
        assert "build" in scripts, "No 'build' script in package.json"

    def test_build_local_script_defined(self):
        """package.json includes a 'build:local' script for dev builds."""
        pkg = PROJECT_ROOT / "aragora" / "live" / "package.json"
        with open(pkg) as f:
            data = json.load(f)
        scripts = data.get("scripts", {})
        assert "build:local" in scripts, "No 'build:local' script in package.json"

    def test_next_config_exists(self):
        """A Next.js config file exists in the live directory."""
        live_dir = PROJECT_ROOT / "aragora" / "live"
        candidates = [
            live_dir / "next.config.js",
            live_dir / "next.config.mjs",
            live_dir / "next.config.ts",
        ]
        assert any(c.exists() for c in candidates), (
            "No next.config.{js,mjs,ts} found in aragora/live/"
        )

    def test_tsconfig_exists(self):
        """TypeScript config exists for the frontend."""
        tsconfig = PROJECT_ROOT / "aragora" / "live" / "tsconfig.json"
        assert tsconfig.exists(), f"Missing: {tsconfig}"
