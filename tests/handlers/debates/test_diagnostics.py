"""Tests for debate diagnostics handler mixin.

Tests the diagnostics API endpoint:
- GET /api/v1/debates/{id}/diagnostics - Get diagnostic report for a debate

Covers:
- Successful diagnostics for completed debates
- Diagnostics for failed debates
- Agent failure detection and per-agent status
- Consensus info extraction
- Suggestion generation
- Receipt detection
- Edge cases (no storage, missing debate, empty data)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


# =============================================================================
# Test Handler Setup
# =============================================================================


class _TestDiagnosticsHandler:
    """Test handler that includes the DiagnosticsMixin."""

    def __init__(self, storage: Any = None):
        self._storage = storage
        self.ctx = {"storage": storage}

    def get_storage(self):
        return self._storage


def _make_handler(storage=None):
    """Create a test handler with diagnostics mixin."""
    from aragora.server.handlers.debates.diagnostics import DiagnosticsMixin

    class Handler(DiagnosticsMixin, _TestDiagnosticsHandler):
        pass

    return Handler(storage=storage)


def _parse_response(result):
    """Parse HandlerResult body as JSON."""
    if result is None:
        return None
    body = result.body
    if isinstance(body, str):
        return json.loads(body)
    if isinstance(body, bytes):
        return json.loads(body.decode())
    return body


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def completed_debate():
    """A completed debate with full data."""
    return {
        "debate_id": "test-debate-001",
        "task": "Should we use Kubernetes or ECS?",
        "status": "concluded",
        "consensus_reached": True,
        "confidence": 0.85,
        "consensus_method": "majority",
        "duration_seconds": 45.2,
        "participants": ["claude-sonnet", "gpt-4", "gemini-pro"],
        "messages": [
            {"agent": "claude-sonnet", "content": "I propose...", "role": "proposer", "round": 1},
            {"agent": "gpt-4", "content": "I critique...", "role": "critic", "round": 1},
            {"agent": "gemini-pro", "content": "My view...", "role": "proposer", "round": 1},
            {"agent": "claude-sonnet", "content": "Revised...", "role": "proposer", "round": 2},
            {"agent": "gpt-4", "content": "Better...", "role": "critic", "round": 2},
            {"agent": "gemini-pro", "content": "Agreed...", "role": "proposer", "round": 2},
            {"agent": "claude-sonnet", "content": "Final...", "role": "proposer", "round": 3},
            {"agent": "gpt-4", "content": "Accept...", "role": "critic", "round": 3},
        ],
        "proposals": {
            "claude-sonnet": "Use Kubernetes for flexibility.",
            "gemini-pro": "Use ECS for simplicity.",
        },
        "agent_failures": {},
        "metadata": {"receipt_id": "receipt-abc-123"},
    }


@pytest.fixture
def failed_debate():
    """A debate where agents failed."""
    return {
        "debate_id": "test-debate-002",
        "task": "Evaluate rate limiting strategies",
        "status": "failed",
        "consensus_reached": False,
        "confidence": 0.0,
        "duration_seconds": 12.5,
        "participants": ["claude-sonnet", "gpt-4", "mistral-large"],
        "messages": [
            {"agent": "claude-sonnet", "content": "I propose...", "role": "proposer", "round": 1},
        ],
        "proposals": {},
        "agent_failures": {
            "gpt-4": [{"error": "API key invalid or quota exceeded", "round": 1}],
            "mistral-large": [{"error": "Connection timeout", "round": 1}],
        },
        "metadata": {},
        "error": "Multiple agent failures",
    }


@pytest.fixture
def no_consensus_debate():
    """A debate that completed but didn't reach consensus."""
    return {
        "debate_id": "test-debate-003",
        "task": "Best programming language for ML",
        "status": "concluded",
        "consensus_reached": False,
        "confidence": 0.35,
        "consensus_method": "supermajority",
        "duration_seconds": 120.0,
        "rounds_used": 5,
        "participants": ["claude-sonnet", "gpt-4"],
        "messages": [
            {"agent": "claude-sonnet", "content": "Python.", "role": "proposer", "round": 1},
            {"agent": "gpt-4", "content": "Rust.", "role": "proposer", "round": 1},
            {"agent": "claude-sonnet", "content": "Still Python.", "role": "proposer", "round": 2},
            {"agent": "gpt-4", "content": "Still Rust.", "role": "proposer", "round": 2},
        ],
        "proposals": {
            "claude-sonnet": "Python is the best.",
            "gpt-4": "Rust is the best.",
        },
        "agent_failures": {},
        "metadata": {},
    }


@pytest.fixture
def mock_storage(completed_debate):
    """Mock storage that returns the completed debate."""
    storage = MagicMock()
    storage.get_debate.return_value = completed_debate
    return storage


# =============================================================================
# Tests: Basic Diagnostics
# =============================================================================


class TestDiagnosticsEndpoint:
    """Test the _get_diagnostics method."""

    def test_successful_completed_debate(self, mock_storage, completed_debate):
        """Test diagnostics for a successfully completed debate."""
        handler = _make_handler(storage=mock_storage)
        result = handler._get_diagnostics("test-debate-001")

        assert result is not None
        assert result.status_code == 200

        data = _parse_response(result)
        assert data["debate_id"] == "test-debate-001"
        assert data["status"] == "completed"  # normalized from "concluded"
        assert data["duration_seconds"] == 45.2
        assert data["receipt_generated"] is True
        assert len(data["agents"]) == 3
        assert data["consensus"]["reached"] is True
        assert data["consensus"]["method"] == "majority"
        assert data["consensus"]["confidence"] == 0.85

    def test_debate_not_found(self):
        """Test diagnostics when debate doesn't exist."""
        storage = MagicMock()
        storage.get_debate.return_value = None
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("nonexistent-id")

        assert result is not None
        assert result.status_code == 404

    def test_no_storage_available(self):
        """Test diagnostics when storage is unavailable."""
        handler = _make_handler(storage=None)

        result = handler._get_diagnostics("test-debate-001")

        assert result is not None
        assert result.status_code == 503


class TestAgentDiagnostics:
    """Test per-agent diagnostic extraction."""

    def test_agent_participation_counts(self, mock_storage):
        """Test that agent proposal and critique counts are extracted."""
        handler = _make_handler(storage=mock_storage)
        result = handler._get_diagnostics("test-debate-001")

        data = _parse_response(result)
        agents = {a["name"]: a for a in data["agents"]}

        # claude-sonnet: 3 proposals (rounds 1, 2, 3)
        assert agents["claude-sonnet"]["proposals"] == 3
        assert agents["claude-sonnet"]["status"] == "success"
        assert agents["claude-sonnet"]["provider"] == "anthropic"

        # gpt-4: 3 critiques (rounds 1, 2, 3)
        assert agents["gpt-4"]["critiques"] == 3
        assert agents["gpt-4"]["status"] == "success"
        assert agents["gpt-4"]["provider"] == "openai"

        # gemini-pro: 2 proposals (rounds 1, 2)
        assert agents["gemini-pro"]["proposals"] == 2
        assert agents["gemini-pro"]["provider"] == "google"

    def test_failed_agents_detected(self, failed_debate):
        """Test that failed agents are properly marked."""
        storage = MagicMock()
        storage.get_debate.return_value = failed_debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("test-debate-002")
        data = _parse_response(result)
        agents = {a["name"]: a for a in data["agents"]}

        assert agents["gpt-4"]["status"] == "failed"
        assert "API key invalid" in agents["gpt-4"]["error"]
        assert agents["mistral-large"]["status"] == "failed"
        assert "timeout" in agents["mistral-large"]["error"].lower()

    def test_agents_with_zero_participation_marked_timeout(self):
        """Test that agents with no messages are marked as timeout."""
        debate = {
            "debate_id": "d1",
            "status": "concluded",
            "participants": ["claude", "gpt-4"],
            "messages": [
                {"agent": "claude", "content": "Hello", "role": "proposer", "round": 1},
            ],
            "agent_failures": {},
            "metadata": {},
        }
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("d1")
        data = _parse_response(result)
        agents = {a["name"]: a for a in data["agents"]}

        assert agents["gpt-4"]["status"] == "timeout"
        assert agents["claude"]["status"] == "success"

    def test_agent_from_messages_not_in_participants(self):
        """Test that agents appearing only in messages are included."""
        debate = {
            "debate_id": "d2",
            "status": "concluded",
            "participants": [],
            "messages": [
                {"agent": "surprise-agent", "content": "Here", "role": "proposer", "round": 1},
            ],
            "agent_failures": {},
            "metadata": {},
        }
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("d2")
        data = _parse_response(result)

        assert len(data["agents"]) == 1
        assert data["agents"][0]["name"] == "surprise-agent"

    def test_rounds_participated_tracks_max_round(self, mock_storage):
        """Test that rounds_participated is the max round number seen."""
        handler = _make_handler(storage=mock_storage)
        result = handler._get_diagnostics("test-debate-001")

        data = _parse_response(result)
        agents = {a["name"]: a for a in data["agents"]}

        assert agents["claude-sonnet"]["rounds_participated"] == 3
        assert agents["gpt-4"]["rounds_participated"] == 3
        assert agents["gemini-pro"]["rounds_participated"] == 2


class TestConsensusDiagnostics:
    """Test consensus info extraction."""

    def test_consensus_reached(self, mock_storage):
        """Test consensus info when consensus was reached."""
        handler = _make_handler(storage=mock_storage)
        result = handler._get_diagnostics("test-debate-001")

        data = _parse_response(result)
        assert data["consensus"]["reached"] is True
        assert data["consensus"]["method"] == "majority"
        assert data["consensus"]["confidence"] == 0.85

    def test_no_consensus(self, no_consensus_debate):
        """Test consensus info when no consensus was reached."""
        storage = MagicMock()
        storage.get_debate.return_value = no_consensus_debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("test-debate-003")
        data = _parse_response(result)

        assert data["consensus"]["reached"] is False
        assert data["consensus"]["method"] == "supermajority"
        assert data["consensus"]["confidence"] == 0.35

    def test_consensus_from_metadata(self):
        """Test that consensus method is read from metadata if not top-level."""
        debate = {
            "debate_id": "d3",
            "status": "concluded",
            "consensus_reached": True,
            "confidence": 0.9,
            "participants": [],
            "messages": [],
            "agent_failures": {},
            "metadata": {"consensus_method": "unanimous"},
        }
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("d3")
        data = _parse_response(result)

        assert data["consensus"]["method"] == "unanimous"


class TestSuggestionGeneration:
    """Test actionable suggestion generation."""

    def test_failed_agent_api_key_suggestion(self, failed_debate):
        """Test suggestions for agents with API key errors."""
        storage = MagicMock()
        storage.get_debate.return_value = failed_debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("test-debate-002")
        data = _parse_response(result)

        suggestions = data["suggestions"]
        assert any("OPENAI_API_KEY" in s for s in suggestions)

    def test_timeout_agent_suggestion(self, failed_debate):
        """Test suggestions for agents with timeout errors."""
        storage = MagicMock()
        storage.get_debate.return_value = failed_debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("test-debate-002")
        data = _parse_response(result)

        suggestions = data["suggestions"]
        # mistral-large had a timeout error
        assert any("timeout" in s.lower() for s in suggestions)

    def test_no_consensus_suggestion(self, no_consensus_debate):
        """Test suggestion when no consensus was reached."""
        storage = MagicMock()
        storage.get_debate.return_value = no_consensus_debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("test-debate-003")
        data = _parse_response(result)

        suggestions = data["suggestions"]
        assert any("consensus" in s.lower() for s in suggestions)

    def test_overall_failure_suggestion(self, failed_debate):
        """Test suggestions for overall debate failure."""
        storage = MagicMock()
        storage.get_debate.return_value = failed_debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("test-debate-002")
        data = _parse_response(result)

        suggestions = data["suggestions"]
        assert any("failed" in s.lower() for s in suggestions)

    def test_fallback_provider_suggestion(self, failed_debate):
        """Test that OPENROUTER_API_KEY fallback suggestion is generated."""
        storage = MagicMock()
        storage.get_debate.return_value = failed_debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("test-debate-002")
        data = _parse_response(result)

        suggestions = data["suggestions"]
        assert any("OPENROUTER_API_KEY" in s for s in suggestions)

    def test_no_suggestions_for_healthy_debate(self, mock_storage):
        """Test that a healthy debate generates no suggestions."""
        handler = _make_handler(storage=mock_storage)
        result = handler._get_diagnostics("test-debate-001")
        data = _parse_response(result)

        assert data["suggestions"] == []

    def test_all_agents_failed_suggestion(self):
        """Test suggestion when all agents failed to participate."""
        debate = {
            "debate_id": "d4",
            "status": "failed",
            "consensus_reached": False,
            "participants": ["claude", "gpt-4"],
            "messages": [],
            "agent_failures": {},
            "metadata": {},
            "error": "No agents responded",
        }
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("d4")
        data = _parse_response(result)

        suggestions = data["suggestions"]
        assert any("all agents" in s.lower() for s in suggestions)


class TestReceiptDetection:
    """Test receipt generation detection."""

    def test_receipt_from_metadata(self, mock_storage):
        """Test receipt detection from metadata.receipt_id."""
        handler = _make_handler(storage=mock_storage)
        result = handler._get_diagnostics("test-debate-001")
        data = _parse_response(result)

        assert data["receipt_generated"] is True

    def test_no_receipt(self, failed_debate):
        """Test receipt_generated is False when no receipt exists."""
        storage = MagicMock()
        storage.get_debate.return_value = failed_debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("test-debate-002")
        data = _parse_response(result)

        assert data["receipt_generated"] is False

    def test_receipt_from_top_level_field(self):
        """Test receipt detection from top-level receipt_id."""
        debate = {
            "debate_id": "d5",
            "status": "concluded",
            "participants": [],
            "messages": [],
            "agent_failures": {},
            "receipt_id": "r-123",
            "metadata": {},
        }
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("d5")
        data = _parse_response(result)

        assert data["receipt_generated"] is True

    def test_receipt_from_gauntlet_receipt_id(self):
        """Test receipt detection from gauntlet_receipt_id in metadata."""
        debate = {
            "debate_id": "d6",
            "status": "concluded",
            "participants": [],
            "messages": [],
            "agent_failures": {},
            "metadata": {"gauntlet_receipt_id": "gr-456"},
        }
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("d6")
        data = _parse_response(result)

        assert data["receipt_generated"] is True


class TestProviderInference:
    """Test provider inference from agent names."""

    def test_known_providers(self):
        """Test provider inference for known agent names."""
        from aragora.server.handlers.debates.diagnostics import _infer_provider

        assert _infer_provider("claude-sonnet") == "anthropic"
        assert _infer_provider("gpt-4") == "openai"
        assert _infer_provider("gemini-pro") == "google"
        assert _infer_provider("grok") == "xai"
        assert _infer_provider("mistral-large") == "mistral"
        assert _infer_provider("deepseek") == "openrouter"

    def test_unknown_provider(self):
        """Test provider inference for unknown agent name."""
        from aragora.server.handlers.debates.diagnostics import _infer_provider

        assert _infer_provider("custom-agent-xyz") == "unknown"

    def test_retired_agent_types_are_not_inferred(self):
        """C-P3 (#9989 merge-gate, round 2): the frontier refresh removed the
        ``yi`` and ``qwen-3.5`` registrations (both models are off the live
        OpenRouter catalog), but this map still described them, so diagnostics
        reported a provider for an agent type the server rejects at
        construction. They now fall through to "unknown" like any other
        unregistered name; ``qwen`` itself is unaffected."""
        from aragora.server.handlers.debates.diagnostics import (
            _AGENT_PROVIDER_MAP,
            _infer_provider,
        )

        assert "yi" not in _AGENT_PROVIDER_MAP
        assert "qwen-3.5" not in _AGENT_PROVIDER_MAP
        assert _infer_provider("yi") == "unknown"
        assert _infer_provider("yi-large") == "unknown"
        assert _infer_provider("qwen-3.5") == "openrouter"  # prefix "qwen"
        assert _infer_provider("qwen") == "openrouter"

    def test_case_insensitive(self):
        """Test provider inference is case insensitive."""
        from aragora.server.handlers.debates.diagnostics import _infer_provider

        assert _infer_provider("Claude-Sonnet") == "anthropic"
        assert _infer_provider("GPT-4") == "openai"


class TestEdgeCases:
    """Test edge cases and unusual data shapes."""

    def test_empty_debate(self):
        """Test diagnostics with minimal debate data."""
        debate = {
            "debate_id": "empty",
            "status": "active",
            "metadata": {},
        }
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("empty")
        data = _parse_response(result)

        assert data["debate_id"] == "empty"
        assert data["status"] == "running"  # normalized from "active"
        assert data["agents"] == []
        assert data["consensus"]["reached"] is False
        assert data["receipt_generated"] is False

    def test_participants_as_string(self):
        """Test handling participants stored as comma-separated string."""
        debate = {
            "debate_id": "str-agents",
            "status": "concluded",
            "participants": "claude,gpt-4,gemini",
            "messages": [],
            "agent_failures": {},
            "metadata": {},
        }
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("str-agents")
        data = _parse_response(result)

        agent_names = [a["name"] for a in data["agents"]]
        assert "claude" in agent_names
        assert "gpt-4" in agent_names
        assert "gemini" in agent_names

    def test_agent_failure_as_string(self):
        """Test handling agent_failures with string error values."""
        debate = {
            "debate_id": "str-fail",
            "status": "failed",
            "participants": ["claude"],
            "messages": [],
            "agent_failures": {"claude": "Connection refused"},
            "metadata": {},
        }
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("str-fail")
        data = _parse_response(result)
        agents = {a["name"]: a for a in data["agents"]}

        assert agents["claude"]["status"] == "failed"
        assert agents["claude"]["error"] == "Connection refused"

    def test_duration_from_metadata(self):
        """Test duration extraction from metadata fallback."""
        debate = {
            "debate_id": "meta-dur",
            "status": "concluded",
            "participants": [],
            "messages": [],
            "agent_failures": {},
            "metadata": {"duration_seconds": 99.5},
        }
        storage = MagicMock()
        storage.get_debate.return_value = debate
        handler = _make_handler(storage=storage)

        result = handler._get_diagnostics("meta-dur")
        data = _parse_response(result)

        assert data["duration_seconds"] == 99.5


class TestCatalogDerivedProviderMap:
    """``_AGENT_PROVIDER_MAP`` gained a row per active catalog spelling
    (2026-09-04 wave-3 ruling): a debate naming an agent by its current
    frontier model id used to report provider "unknown"."""

    def test_every_active_catalog_spelling_resolves_to_a_known_provider(self):
        from aragora.models.catalog import CATALOG
        from aragora.server.handlers.debates.diagnostics import (
            _PROVIDER_API_KEY_MAP,
            _infer_provider,
        )

        for spec in CATALOG.values():
            if spec.retired:
                continue
            for spelling in spec.all_ids():
                provider = _infer_provider(spelling)
                assert provider != "unknown", spelling
                assert provider in _PROVIDER_API_KEY_MAP, (spelling, provider)

    def test_families_reached_only_through_openrouter_report_openrouter(self):
        """The map's whole output is a credential hint, so a provider with
        no direct Aragora credential must name the key that actually
        authenticates the call -- the convention the hand-written deepseek /
        llama / qwen / kimi rows already used."""
        from aragora.server.handlers.debates.diagnostics import _infer_provider

        assert _infer_provider("kimi-k3") == "openrouter"
        assert _infer_provider("sonar-reasoning-pro") == "openrouter"
        assert _infer_provider("minimax-m3") == "openrouter"
        assert _infer_provider("deepseek-v4-pro-0813") == "openrouter"

    def test_native_providers_keep_their_own_key(self):
        from aragora.server.handlers.debates.diagnostics import _infer_provider

        assert _infer_provider("gpt-6-astra") == "openai"
        assert _infer_provider("claude-fable-5-1") == "anthropic"
        assert _infer_provider("gemini-3.1-pro-preview") == "google"
        assert _infer_provider("grok-4.6") == "xai"
        assert _infer_provider("mistral-medium-2604") == "mistral"

    def test_hand_written_rows_keep_their_value_and_their_position(self):
        """``_infer_provider`` falls back to PREFIX matching in dict
        iteration order, so a generated full-model-id row must never come
        before the family label it starts with."""
        from aragora.server.handlers.debates.diagnostics import (
            _AGENT_PROVIDER_MAP,
            _LEGACY_AGENT_PROVIDER_MAP,
        )

        keys = list(_AGENT_PROVIDER_MAP)
        assert keys[: len(_LEGACY_AGENT_PROVIDER_MAP)] == list(_LEGACY_AGENT_PROVIDER_MAP)
        for name, provider in _LEGACY_AGENT_PROVIDER_MAP.items():
            assert _AGENT_PROVIDER_MAP[name] == provider

    def test_unknown_names_are_still_unknown(self):
        from aragora.server.handlers.debates.diagnostics import _infer_provider

        assert _infer_provider("custom-agent-xyz") == "unknown"
        assert _infer_provider("yi") == "unknown"
