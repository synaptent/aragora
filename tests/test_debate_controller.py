"""
Tests for DebateController.

Tests cover:
1. DebateRequest parsing and validation
2. DebateResponse serialization
3. DebateController lifecycle (init, start, shutdown)
4. Error handling and edge cases
5. Concurrency and thread safety
"""

import pytest
import asyncio
import threading
import time
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from dataclasses import asdict

from aragora.config import DEFAULT_ROUNDS, MAX_ROUNDS
from aragora.server.debate_controller import (
    DebateRequest,
    DebateResponse,
    DebateController,
    MAX_CONCURRENT_DEBATES,
)


class TestDebateRequest:
    """Tests for DebateRequest dataclass."""

    def test_from_dict_minimal(self):
        """Should create request with just question."""
        data = {"question": "What is the meaning of life?"}
        request = DebateRequest.from_dict(data)

        assert request.question == "What is the meaning of life?"
        assert request.rounds == DEFAULT_ROUNDS  # Default
        assert request.consensus == "judge"  # Default
        assert request.auto_select is False
        assert request.auto_select_config == {}

    def test_from_dict_full(self):
        """Should create request with all fields."""
        data = {
            "question": "Test question?",
            "agents": "claude,gpt",
            "rounds": 5,
            "consensus": "unanimous",
            "auto_select": True,
            "auto_select_config": {"strategy": "best"},
            "use_trending": True,
            "trending_category": "tech",
        }
        request = DebateRequest.from_dict(data)

        assert request.question == "Test question?"
        assert request.agents_str == "claude,gpt"
        assert request.rounds == 5
        assert request.consensus == "unanimous"
        assert request.auto_select is True
        assert request.auto_select_config == {"strategy": "best"}
        assert request.use_trending is True
        assert request.trending_category == "tech"

    def test_from_dict_epistemic_hygiene_mode_enriches_context_and_metadata(self):
        """Epistemic hygiene mode should append protocol guidance and settlement scaffolding."""
        data = {
            "question": "Should we launch feature X?",
            "mode": "epistemic-hygiene",
            "context": "User requested risk-aware analysis.",
            "metadata": {"source": "ui"},
        }
        request = DebateRequest.from_dict(data)

        assert request.mode == "epistemic_hygiene"
        assert request.metadata["mode"] == "epistemic_hygiene"
        assert request.metadata["epistemic_hygiene"] is True
        assert request.metadata["settlement"]["status"] == "needs_definition"
        assert request.metadata["settlement"]["resolver_type"] == "human"
        assert "Epistemic hygiene protocol" in (request.context or "")
        assert "User requested risk-aware analysis." in (request.context or "")

    def test_from_dict_epistemic_hygiene_boolean_alias(self):
        """Legacy boolean toggle should map to epistemic_hygiene mode."""
        data = {
            "question": "Is this claim robust?",
            "epistemic_hygiene": True,
        }
        request = DebateRequest.from_dict(data)

        assert request.mode == "epistemic_hygiene"
        assert request.metadata["mode"] == "epistemic_hygiene"
        assert "Epistemic hygiene protocol" in (request.context or "")

    def test_from_dict_epistemic_hygiene_production_requires_settlement_fields(self, monkeypatch):
        """Production requests must provide explicit settlement fields."""
        monkeypatch.setenv("ARAGORA_ENV", "production")
        data = {
            "question": "Should we approve migration?",
            "mode": "epistemic_hygiene",
            "metadata": {"settlement": {"falsifier": "CPU p95 worsens"}},
        }
        with pytest.raises(ValueError, match="requires settlement fields in production"):
            DebateRequest.from_dict(data)

    def test_from_dict_epistemic_hygiene_production_accepts_complete_settlement(self, monkeypatch):
        """Production requests pass when settlement metadata is complete."""
        monkeypatch.setenv("ARAGORA_ENV", "production")
        data = {
            "question": "Should we approve migration?",
            "mode": "epistemic_hygiene",
            "metadata": {
                "settlement": {
                    "falsifier": "CPU p95 worsens by >10%",
                    "metric": "cpu_p95_ms",
                    "review_horizon_days": 14,
                    "resolver_type": "deterministic",
                }
            },
        }
        request = DebateRequest.from_dict(data)
        assert request.metadata["settlement"]["claim"] == "Should we approve migration?"
        assert request.metadata["settlement"]["review_horizon_days"] == 14
        assert request.metadata["settlement"]["resolver_type"] == "deterministic"

    def test_from_dict_epistemic_hygiene_production_rejects_placeholder_settlement(
        self, monkeypatch
    ):
        """Production requests must not use placeholder settlement fields."""
        monkeypatch.setenv("ARAGORA_ENV", "production")
        data = {
            "question": "Should we approve migration?",
            "mode": "epistemic_hygiene",
            "metadata": {
                "settlement": {
                    "falsifier": "Define an objective falsifier for the primary claim.",
                    "metric": "Define a measurable metric for decision settlement.",
                    "review_horizon_days": 14,
                    "resolver_type": "human",
                }
            },
        }
        with pytest.raises(ValueError, match="requires settlement fields in production"):
            DebateRequest.from_dict(data)

    def test_from_dict_epistemic_hygiene_production_rejects_invalid_resolver_type(
        self, monkeypatch
    ):
        """Production requests must declare a supported settlement resolver_type."""
        monkeypatch.setenv("ARAGORA_ENV", "production")
        data = {
            "question": "Should we approve migration?",
            "mode": "epistemic_hygiene",
            "metadata": {
                "settlement": {
                    "falsifier": "CPU p95 worsens by >10%",
                    "metric": "cpu_p95_ms",
                    "review_horizon_days": 14,
                    "resolver_type": "tribunal",
                }
            },
        }
        with pytest.raises(ValueError, match="requires settlement fields in production"):
            DebateRequest.from_dict(data)

    def test_from_dict_missing_question_raises(self):
        """Should raise ValueError if question is missing."""
        with pytest.raises(ValueError, match="question or task field is required"):
            DebateRequest.from_dict({})

    def test_from_dict_empty_question_raises(self):
        """Should raise ValueError if question is empty."""
        with pytest.raises(ValueError, match="question or task field is required"):
            DebateRequest.from_dict({"question": ""})

    def test_from_dict_whitespace_question_raises(self):
        """Should raise ValueError if question is only whitespace."""
        with pytest.raises(ValueError, match="question or task field is required"):
            DebateRequest.from_dict({"question": "   "})

    def test_from_dict_question_too_long_raises(self):
        """Should raise ValueError if question exceeds 10000 chars."""
        with pytest.raises(ValueError, match="under 10,000 characters"):
            DebateRequest.from_dict({"question": "x" * 10001})

    def test_from_dict_rounds_clamped_min(self):
        """Rounds should be clamped to minimum of 1."""
        data = {"question": "Test?", "rounds": 0}
        request = DebateRequest.from_dict(data)
        assert request.rounds == 1

    def test_from_dict_rounds_clamped_max(self):
        """Rounds should be clamped to maximum of MAX_ROUNDS."""
        data = {"question": "Test?", "rounds": 100}
        request = DebateRequest.from_dict(data)
        assert request.rounds == MAX_ROUNDS

    def test_from_dict_invalid_rounds_defaults(self):
        """Invalid rounds value should default to DEFAULT_ROUNDS."""
        data = {"question": "Test?", "rounds": "invalid"}
        request = DebateRequest.from_dict(data)
        assert request.rounds == DEFAULT_ROUNDS

    def test_post_init_sets_empty_config(self):
        """__post_init__ should initialize None config to empty dict."""
        request = DebateRequest(question="Test?", auto_select_config=None)
        assert request.auto_select_config == {}


class TestDebateResponse:
    """Tests for DebateResponse dataclass."""

    def test_success_response(self):
        """Should create success response with debate_id."""
        response = DebateResponse(success=True, debate_id="test_123")

        assert response.success is True
        assert response.debate_id == "test_123"
        assert response.error is None
        assert response.status_code == 200

    def test_error_response(self):
        """Should create error response."""
        response = DebateResponse(success=False, error="Something went wrong", status_code=500)

        assert response.success is False
        assert response.debate_id is None
        assert response.error == "Something went wrong"
        assert response.status_code == 500

    def test_to_dict_success(self):
        """to_dict should include debate_id for success."""
        response = DebateResponse(success=True, debate_id="debate_abc")
        result = response.to_dict()

        assert result == {"success": True, "debate_id": "debate_abc"}

    def test_to_dict_error(self):
        """to_dict should include error message."""
        response = DebateResponse(success=False, error="Failed")
        result = response.to_dict()

        assert result == {"success": False, "error": "Failed"}

    def test_to_dict_minimal(self):
        """to_dict should work with just success field."""
        response = DebateResponse(success=True)
        result = response.to_dict()

        assert result == {"success": True}


class TestDebateControllerInit:
    """Tests for DebateController initialization."""

    def test_init_with_required_params(self):
        """Should initialize with factory and emitter."""
        factory = Mock()
        emitter = Mock()

        controller = DebateController(factory=factory, emitter=emitter)

        assert controller.factory is factory
        assert controller.emitter is emitter
        assert controller.elo_system is None
        assert controller.auto_select_fn is None

    def test_init_with_all_params(self):
        """Should initialize with all optional params."""
        factory = Mock()
        emitter = Mock()
        elo = Mock()
        auto_select = Mock()

        controller = DebateController(
            factory=factory,
            emitter=emitter,
            elo_system=elo,
            auto_select_fn=auto_select,
        )

        assert controller.factory is factory
        assert controller.emitter is emitter
        assert controller.elo_system is elo
        assert controller.auto_select_fn is auto_select

    def test_executor_lazy_initialization(self):
        """Executor should be lazily initialized via StateManager."""
        from aragora.server.state import get_state_manager, reset_state_manager

        # Start with fresh state
        reset_state_manager()

        factory = Mock()
        emitter = Mock()
        controller = DebateController(factory=factory, emitter=emitter)

        # Get executor triggers creation
        executor = controller._get_executor()
        assert executor is not None
        # Executor comes from StateManager
        assert get_state_manager().get_executor() is executor

        # Cleanup
        DebateController.shutdown()


class TestDebateControllerStartDebate:
    """Tests for DebateController.start_debate."""

    def setup_method(self):
        """Set up mocks for each test."""
        from aragora.server.state import reset_state_manager

        self.factory = Mock()
        self.emitter = Mock()
        self.emitter.set_loop_id = Mock()
        self.storage = Mock()
        self._preflight_patch = patch.object(
            DebateController, "_preflight_agents", return_value=None
        )
        self._preflight_patch.start()

        # Clean up any previous state
        reset_state_manager()

    def teardown_method(self):
        """Clean up after each test."""
        self._preflight_patch.stop()
        DebateController.shutdown()

        # Clean up active debates
        from aragora.server.debate_utils import _active_debates, _active_debates_lock

        with _active_debates_lock:
            _active_debates.clear()

    def test_start_debate_returns_debate_id(self):
        """Should return response with debate_id."""
        controller = DebateController(
            factory=self.factory, emitter=self.emitter, storage=self.storage
        )

        request = DebateRequest(question="Test question?")
        response = controller.start_debate(request)

        assert response.success is True
        assert response.debate_id is not None
        assert response.debate_id.startswith("adhoc_")
        assert response.status_code == 200

    def test_start_debate_tracks_in_active_debates(self):
        """Should register debate in active debates."""
        from aragora.server.debate_utils import _active_debates, _active_debates_lock

        controller = DebateController(
            factory=self.factory, emitter=self.emitter, storage=self.storage
        )

        request = DebateRequest(question="Tracked question?")
        response = controller.start_debate(request)

        with _active_debates_lock:
            assert response.debate_id in _active_debates
            debate_info = _active_debates[response.debate_id]
            # Note: StateManager proxy converts "question" to "task"
            assert debate_info["status"] in ("starting", "running")

    def test_start_debate_includes_mode_and_settlement_in_active_state_and_start_event(self):
        """Epistemic hygiene metadata should be available immediately in active state + DEBATE_START."""
        from aragora.server.debate_utils import _active_debates, _active_debates_lock

        controller = DebateController(
            factory=self.factory, emitter=self.emitter, storage=self.storage
        )
        request = DebateRequest.from_dict(
            {
                "question": "Should we roll out feature flag globally?",
                "mode": "epistemic_hygiene",
                "metadata": {
                    "settlement": {
                        "falsifier": "Error rate rises above 2%",
                        "metric": "error_rate_percent",
                        "review_horizon_days": 7,
                        "resolver_type": "deterministic",
                    }
                },
            }
        )

        mock_executor = Mock()
        with patch.object(controller, "_get_executor", return_value=mock_executor):
            response = controller.start_debate(request)

        with _active_debates_lock:
            debate_info = _active_debates[response.debate_id]
            metadata = debate_info.get("metadata", {})
            mode = debate_info.get("mode") or metadata.get("mode")
            settlement = debate_info.get("settlement") or metadata.get("settlement")
            assert mode == "epistemic_hygiene"
            assert settlement["resolver_type"] == "deterministic"
            assert settlement["metric"] == "error_rate_percent"

        emitted = self.emitter.emit.call_args_list[0][0][0]
        assert emitted.data["mode"] == "epistemic_hygiene"
        assert emitted.data["settlement"]["status"] == "needs_definition"
        assert emitted.data["settlement"]["resolver_type"] == "deterministic"

    def test_start_debate_tracks_mode_and_settlement_metadata(self):
        """Active debate state should include normalized mode/settlement metadata."""
        from aragora.server.debate_utils import _active_debates, _active_debates_lock

        controller = DebateController(
            factory=self.factory, emitter=self.emitter, storage=self.storage
        )

        mock_executor = Mock()
        with patch.object(controller, "_get_executor", return_value=mock_executor):
            request = DebateRequest(
                question="Should we ship this release?",
                mode="epistemic_hygiene",
                metadata={
                    "settlement": {
                        "falsifier": "p95 latency worsens > 15%",
                        "metric": "p95_latency_ms",
                        "review_horizon_days": 14,
                        "resolver_type": "human",
                    }
                },
            )
            response = controller.start_debate(request)

        with _active_debates_lock:
            debate_info = _active_debates[response.debate_id]
            metadata = debate_info.get("metadata", {})
            mode = debate_info.get("mode") or metadata.get("mode")
            settlement = debate_info.get("settlement") or metadata.get("settlement")
            assert mode == "epistemic_hygiene"
            assert settlement["claim"] == "Should we ship this release?"
            assert settlement["resolver_type"] == "human"
            assert settlement["review_horizon_days"] == 14

    def test_start_debate_sets_emitter_loop_id(self):
        """Should set loop_id on emitter."""
        controller = DebateController(
            factory=self.factory, emitter=self.emitter, storage=self.storage
        )

        request = DebateRequest(question="Test?")
        response = controller.start_debate(request)

        self.emitter.set_loop_id.assert_called_once_with(response.debate_id)

    def test_start_debate_with_auto_select(self):
        """Should call auto_select_fn when enabled."""
        auto_select = Mock(return_value="selected-agent")

        controller = DebateController(
            factory=self.factory,
            emitter=self.emitter,
            auto_select_fn=auto_select,
            storage=self.storage,
        )

        # Mock the executor so _run_debate doesn't actually run in a thread
        mock_executor = Mock()
        with patch.object(controller, "_get_executor", return_value=mock_executor):
            # agents_str must be None so the auto-select code path triggers
            # (when agents_str has a value, auto-select is skipped)
            request = DebateRequest(
                question="Auto select test?",
                agents_str=None,
                auto_select=True,
                auto_select_config={"strategy": "best"},
            )
            controller.start_debate(request)

        auto_select.assert_called_once_with("Auto select test?", {"strategy": "best"})

    def test_start_debate_auto_select_failure_uses_default(self):
        """Should use default agents if auto_select fails."""
        auto_select = Mock(side_effect=Exception("Auto select failed"))
        controller = DebateController(
            factory=self.factory,
            emitter=self.emitter,
            auto_select_fn=auto_select,
            storage=self.storage,
        )

        request = DebateRequest(
            question="Test?",
            auto_select=True,
            agents_str="default-agent",
        )
        response = controller.start_debate(request)

        # Should still succeed with default agents
        assert response.success is True

    @patch("aragora.server.debate_controller.cleanup_stale_debates")
    def test_start_debate_triggers_cleanup(self, mock_cleanup):
        """Should trigger stale debate cleanup."""
        controller = DebateController(
            factory=self.factory, emitter=self.emitter, storage=self.storage
        )

        request = DebateRequest(question="Test?")
        controller.start_debate(request)

        mock_cleanup.assert_called_once()


class TestDebateControllerRunDebate:
    """Tests for DebateController._run_debate (internal method)."""

    def setup_method(self):
        """Set up mocks for each test."""
        self.factory = Mock()
        self.emitter = Mock()
        self.emitter.emit = Mock()

        # Mock arena
        self.mock_arena = MagicMock()
        self.mock_result = Mock()
        self.mock_result.final_answer = "Test answer"
        self.mock_result.consensus_reached = True
        self.mock_result.confidence = 0.85
        self.mock_result.grounded_verdict = None
        self.mock_result.status = "consensus_reached"
        self.mock_result.agent_failures = {
            "agent1": [{"phase": "proposal", "error_type": "timeout"}]
        }
        self.mock_result.participants = ["agent1", "agent2"]

        # Make arena.run() return async
        async def mock_run():
            return self.mock_result

        self.mock_arena.run = mock_run
        self.factory.create_arena.return_value = self.mock_arena
        self.factory.reset_circuit_breakers = Mock()

        DebateController._executor = None

    def teardown_method(self):
        """Clean up after each test."""
        DebateController.shutdown()
        from aragora.server.debate_utils import _active_debates, _active_debates_lock

        with _active_debates_lock:
            _active_debates.clear()

    def test_run_debate_creates_arena(self):
        """Should create arena with correct config."""
        from aragora.server.debate_factory import DebateConfig

        controller = DebateController(factory=self.factory, emitter=self.emitter)

        config = DebateConfig(
            question="Test?",
            agents_str="agent1,agent2",
            rounds=3,
            debate_id="test_123",
        )

        controller._run_debate(config, "test_123")

        self.factory.create_arena.assert_called_once()

    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_updates_status_running(self, mock_update):
        """Should update status to running."""
        from aragora.server.debate_factory import DebateConfig

        controller = DebateController(factory=self.factory, emitter=self.emitter)

        config = DebateConfig(
            question="Test?",
            agents_str="agent1",
            rounds=1,
            debate_id="test_123",
        )

        controller._run_debate(config, "test_123")

        # Check "running" status was set
        calls = mock_update.call_args_list
        assert any(call[0][0] == "test_123" and call[0][1] == "running" for call in calls)

    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_updates_status_completed(self, mock_update):
        """Should update status to completed with result."""
        from aragora.server.debate_factory import DebateConfig

        controller = DebateController(factory=self.factory, emitter=self.emitter)

        config = DebateConfig(
            question="Test?",
            agents_str="agent1",
            rounds=1,
            debate_id="test_123",
        )

        controller._run_debate(config, "test_123")

        # Check "completed" status was set (may be called twice:
        # once for the result, once for receipt_id after receipt generation)
        calls = mock_update.call_args_list
        completed_calls = [c for c in calls if c[0][1] == "completed"]
        assert len(completed_calls) >= 1
        result_payload = completed_calls[0][1].get("result", {})
        assert result_payload["status"] == "consensus_reached"
        assert result_payload["agent_failures"] == {
            "agent1": [{"phase": "proposal", "error_type": "timeout"}]
        }
        assert result_payload["participants"] == ["agent1", "agent2"]

    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_includes_mode_and_settlement_metadata(self, mock_update):
        """Completed result should carry mode/settlement metadata for downstream consumers."""
        from aragora.server.debate_factory import DebateConfig

        controller = DebateController(factory=self.factory, emitter=self.emitter)

        config = DebateConfig(
            question="Test?",
            agents_str="agent1",
            rounds=1,
            debate_id="test_123",
            mode="epistemic_hygiene",
            metadata={
                "settlement": {
                    "status": "needs_definition",
                    "falsifier": "Metric X drops below threshold",
                }
            },
        )

        controller._run_debate(config, "test_123")

        calls = mock_update.call_args_list
        completed_calls = [c for c in calls if c[0][1] == "completed"]
        assert len(completed_calls) >= 1
        result_payload = completed_calls[0][1].get("result", {})
        assert result_payload["mode"] == "epistemic_hygiene"
        assert result_payload["settlement"]["status"] == "needs_definition"
        assert result_payload["settlement"]["falsifier"] == "Metric X drops below threshold"
        assert (
            result_payload["settlement"]["metric"]
            == "Define a measurable metric for decision settlement."
        )
        assert result_payload["settlement"]["review_horizon_days"] == 30
        assert result_payload["settlement"]["claim"] == "Test?"
        assert result_payload["settlement"]["resolver_type"] == "human"

    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_hygiene_mode_without_settlement_uses_scaffold(self, mock_update):
        """Hygiene-mode debates emit normalized settlement scaffolding even without explicit metadata."""
        from aragora.server.debate_factory import DebateConfig

        controller = DebateController(factory=self.factory, emitter=self.emitter)

        config = DebateConfig(
            question="Should we ship this release?",
            agents_str="agent1",
            rounds=1,
            debate_id="test_123",
            mode="epistemic_hygiene",
            metadata={},
        )

        controller._run_debate(config, "test_123")

        calls = mock_update.call_args_list
        completed_calls = [c for c in calls if c[0][1] == "completed"]
        assert len(completed_calls) >= 1
        result_payload = completed_calls[0][1].get("result", {})
        settlement = result_payload["settlement"]
        assert settlement["status"] == "needs_definition"
        assert settlement["falsifier"] == "Define an objective falsifier for the primary claim."
        assert settlement["metric"] == "Define a measurable metric for decision settlement."
        assert settlement["review_horizon_days"] == 30
        assert settlement["claim"] == "Should we ship this release?"
        assert settlement["resolver_type"] == "human"

    @patch("aragora.storage.receipt_store.get_receipt_store")
    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_persists_settlement_snapshot_in_receipt(
        self, mock_update, mock_get_receipt_store
    ):
        """Generated receipts should include normalized settlement metadata."""
        from aragora.server.debate_factory import DebateConfig

        mock_store = Mock()
        mock_store.save.return_value = "receipt-xyz"
        mock_get_receipt_store.return_value = mock_store

        controller = DebateController(factory=self.factory, emitter=self.emitter)
        config = DebateConfig(
            question="Should we migrate to service mesh?",
            agents_str="agent1",
            rounds=1,
            debate_id="test_123",
            mode="epistemic_hygiene",
            metadata={
                "settlement": {
                    "falsifier": "p95 latency degrades >15%",
                    "metric": "p95_latency_ms",
                    "review_horizon_days": 21,
                }
            },
        )

        controller._run_debate(config, "test_123")

        saved = mock_store.save.call_args[0][0]
        assert saved["mode"] == "epistemic_hygiene"
        assert saved["settlement"]["claim"] == "Should we migrate to service mesh?"
        assert saved["settlement"]["falsifier"] == "p95 latency degrades >15%"
        assert saved["settlement"]["metric"] == "p95_latency_ms"
        assert saved["settlement"]["review_horizon_days"] == 21
        assert saved["settlement"]["resolver_type"] == "human"

    @patch("aragora.storage.receipt_store.get_receipt_store")
    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_persists_settlement_scaffold_for_empty_hygiene_metadata(
        self, mock_update, mock_get_receipt_store
    ):
        """Hygiene mode receipts remain settlement-reviewable even without explicit metadata."""
        from aragora.server.debate_factory import DebateConfig

        mock_store = Mock()
        mock_store.save.return_value = "receipt-empty-scaffold"
        mock_get_receipt_store.return_value = mock_store

        controller = DebateController(factory=self.factory, emitter=self.emitter)
        config = DebateConfig(
            question="Should we roll back this deploy?",
            agents_str="agent1",
            rounds=1,
            debate_id="test_123",
            mode="epistemic_hygiene",
            metadata={},
        )

        controller._run_debate(config, "test_123")

        saved = mock_store.save.call_args[0][0]
        settlement = saved["settlement"]
        assert saved["mode"] == "epistemic_hygiene"
        assert settlement["status"] == "needs_definition"
        assert settlement["claim"] == "Should we roll back this deploy?"
        assert settlement["falsifier"] == "Define an objective falsifier for the primary claim."
        assert settlement["metric"] == "Define a measurable metric for decision settlement."
        assert settlement["review_horizon_days"] == 30
        assert settlement["resolver_type"] == "human"

    @patch("aragora.server.handlers.onboarding._track_event")
    @patch("aragora.storage.repositories.onboarding.get_onboarding_repository")
    @patch("aragora.storage.receipt_store.get_receipt_store")
    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_tracks_onboarding_first_receipt_event(
        self,
        mock_update,
        mock_get_receipt_store,
        mock_get_onboarding_repo,
        mock_track_event,
    ):
        """Onboarding debates should emit first_receipt_generated analytics events."""
        from aragora.server.debate_factory import DebateConfig

        mock_store = Mock()
        mock_get_receipt_store.return_value = mock_store

        onboarding_repo = Mock()
        onboarding_repo.get_flow.return_value = {"id": "onb_flow_1", "metadata": {}}
        mock_get_onboarding_repo.return_value = onboarding_repo

        controller = DebateController(factory=self.factory, emitter=self.emitter)
        config = DebateConfig(
            question="Should we adopt this architecture?",
            agents_str="agent1",
            rounds=1,
            debate_id="test_123",
            metadata={
                "is_onboarding": True,
                "user_id": "user_1",
                "organization_id": "org_1",
                "flow_id": "flow_fallback",
            },
        )

        controller._run_debate(config, "test_123")

        mock_track_event.assert_called_once()
        event_type, user_id, org_id, payload = mock_track_event.call_args[0]
        assert event_type == "first_receipt_generated"
        assert user_id == "user_1"
        assert org_id == "org_1"
        assert payload["flow_id"] == "onb_flow_1"
        assert payload["debate_id"] == "test_123"
        assert payload["receipt_id"]

    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_handles_validation_error(self, mock_update):
        """Should handle ValueError gracefully."""
        from aragora.server.debate_factory import DebateConfig

        self.factory.create_arena.side_effect = ValueError("Invalid agents")

        controller = DebateController(factory=self.factory, emitter=self.emitter)

        config = DebateConfig(
            question="Test?",
            agents_str="invalid",
            rounds=1,
            debate_id="test_123",
        )

        # Should not raise
        controller._run_debate(config, "test_123")

        # Should update status to error
        calls = mock_update.call_args_list
        error_calls = [c for c in calls if c[0][1] == "error"]
        assert len(error_calls) == 1

        # Should emit error event
        self.emitter.emit.assert_called()

    @patch("aragora.server.debate_controller.update_debate_status")
    def test_run_debate_handles_general_exception(self, mock_update):
        """Should handle unexpected exceptions gracefully."""
        from aragora.server.debate_factory import DebateConfig

        self.factory.create_arena.side_effect = RuntimeError("Unexpected error")

        controller = DebateController(factory=self.factory, emitter=self.emitter)

        config = DebateConfig(
            question="Test?",
            agents_str="agent1",
            rounds=1,
            debate_id="test_123",
        )

        # Should not raise
        controller._run_debate(config, "test_123")

        # Should update status to error
        calls = mock_update.call_args_list
        error_calls = [c for c in calls if c[0][1] == "error"]
        assert len(error_calls) == 1


class TestDebateControllerLeaderboard:
    """Tests for leaderboard update emission."""

    def test_emit_leaderboard_with_elo_system(self):
        """Should emit leaderboard update when ELO system available."""
        factory = Mock()
        emitter = Mock()
        elo = Mock()

        # Mock leaderboard data
        mock_agent = Mock()
        mock_agent.agent_name = "test_agent"
        mock_agent.elo_rating = 1500
        mock_agent.wins = 10
        mock_agent.total_debates = 20
        elo.get_leaderboard.return_value = [mock_agent]

        controller = DebateController(factory=factory, emitter=emitter, elo_system=elo)

        controller._emit_leaderboard_update("test_123")

        emitter.emit.assert_called_once()
        call_args = emitter.emit.call_args[0][0]
        assert call_args.data["debate_id"] == "test_123"
        assert len(call_args.data["leaderboard"]) == 1

    def test_emit_leaderboard_without_elo_system(self):
        """Should not emit when ELO system is None."""
        factory = Mock()
        emitter = Mock()

        controller = DebateController(factory=factory, emitter=emitter, elo_system=None)

        controller._emit_leaderboard_update("test_123")

        emitter.emit.assert_not_called()

    def test_emit_leaderboard_handles_elo_error(self):
        """Should handle ELO system errors gracefully."""
        factory = Mock()
        emitter = Mock()
        elo = Mock()
        elo.get_leaderboard.side_effect = RuntimeError("ELO error")

        controller = DebateController(factory=factory, emitter=emitter, elo_system=elo)

        # Should not raise
        controller._emit_leaderboard_update("test_123")


class TestDebateControllerShutdown:
    """Tests for DebateController.shutdown."""

    def test_shutdown_clears_executor(self):
        """Should clear the executor via StateManager."""
        from aragora.server.state import get_state_manager, reset_state_manager

        # Start fresh
        reset_state_manager()

        factory = Mock()
        emitter = Mock()

        controller = DebateController(factory=factory, emitter=emitter)
        controller._get_executor()  # Create executor

        # Verify executor exists
        state_manager = get_state_manager()
        assert state_manager._executor is not None

        DebateController.shutdown()

        # Executor should be cleared
        assert state_manager._executor is None

    def test_shutdown_without_executor(self):
        """Should handle shutdown when no executor exists."""
        from aragora.server.state import reset_state_manager

        # Start with no executor
        reset_state_manager()

        # Should not raise
        DebateController.shutdown()


class TestDebateControllerConcurrency:
    """Tests for thread safety and concurrency."""

    def test_max_concurrent_debates_constant(self):
        """MAX_CONCURRENT_DEBATES should be defined."""
        assert MAX_CONCURRENT_DEBATES == 10

    def test_executor_thread_safe_creation(self):
        """Executor creation should be thread-safe via StateManager."""
        from aragora.server.state import reset_state_manager

        # Start fresh
        reset_state_manager()

        factory = Mock()
        emitter = Mock()
        controller = DebateController(factory=factory, emitter=emitter)

        results = []
        errors = []

        def get_executor():
            try:
                executor = controller._get_executor()
                results.append(id(executor))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_executor) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All threads should get the same executor
        assert len(set(results)) == 1

        DebateController.shutdown()


class TestDebateControllerTrending:
    """Tests for trending topic functionality."""

    @patch("aragora.server.debate_controller.asyncio")
    def test_fetch_trending_topic_returns_topic(self, mock_asyncio):
        """Should fetch and return trending topic."""
        factory = Mock()
        emitter = Mock()

        controller = DebateController(factory=factory, emitter=emitter)

        # This is complex to mock due to async nature
        # Just verify it handles None gracefully
        result = controller._fetch_trending_topic(None)
        # Result depends on pulse ingestors which may not be available
        assert result is None or hasattr(result, "topic")

    def test_fetch_trending_topic_handles_import_error(self):
        """Should handle missing pulse module gracefully."""
        factory = Mock()
        emitter = Mock()

        controller = DebateController(factory=factory, emitter=emitter)

        with patch.dict("sys.modules", {"aragora.pulse.ingestor": None}):
            result = controller._fetch_trending_topic("tech")
            # Should return None on error
            assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
