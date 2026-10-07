"""
Tests for ForkOperationsMixin in DebatesHandler.

Endpoints tested:
- POST /api/debates/{id}/fork - Fork debate at a branch point
- POST /api/debates/{id}/verify - Record verification of debate outcome
- GET /api/debates/{id}/followups - Get follow-up suggestions
- POST /api/debates/{id}/followup - Create follow-up debate
"""

import json
import pytest
from dataclasses import dataclass, field
from unittest.mock import Mock, MagicMock, patch

from aragora.server.handlers import DebatesHandler, HandlerResult
from aragora.server.handlers.base import clear_cache

# Import rate limiting modules for clearing between tests
import importlib

_rate_limit_mod = importlib.import_module("aragora.server.handlers.utils.rate_limit")
_user_limiter_mod = importlib.import_module("aragora.server.middleware.rate_limit.user_limiter")


# ============================================================================
# Mock Classes for Counterfactual Types
# ============================================================================


@dataclass
class MockPivotClaim:
    """Mock PivotClaim for tests."""

    claim_id: str = "pivot-abc123"
    statement: str = "Test assumption"
    author: str = "user"
    disagreement_score: float = 1.0
    importance_score: float = 1.0
    blocking_agents: list = field(default_factory=list)
    branch_reason: str = "User-initiated fork"


@dataclass
class MockCounterfactualBranch:
    """Mock CounterfactualBranch for tests."""

    branch_id: str = "fork-test-001"
    parent_debate_id: str = "debate-001"
    pivot_claim: MockPivotClaim = field(default_factory=MockPivotClaim)
    assumption: bool = True
    messages: list = field(default_factory=list)


@dataclass
class MockDisagreementCrux:
    """Mock DisagreementCrux for tests."""

    description: str = "Test crux description"
    divergent_agents: list = field(default_factory=lambda: ["agent1", "agent2"])
    evidence_needed: str = "More evidence needed"
    severity: float = 0.7
    crux_id: str = "crux-12345"

    def to_dict(self):
        return {
            "id": self.crux_id,
            "description": self.description,
            "agents": self.divergent_agents,
            "evidence_needed": self.evidence_needed,
            "severity": self.severity,
        }


@dataclass
class MockFollowUpSuggestion:
    """Mock FollowUpSuggestion for tests."""

    crux: MockDisagreementCrux = field(default_factory=MockDisagreementCrux)
    suggested_task: str = "Investigate the crux"
    priority: float = 0.8
    parent_debate_id: str = "debate-001"
    suggested_agents: list = field(default_factory=lambda: ["agent1", "agent2"])

    def to_dict(self):
        return {
            "crux_id": self.crux.crux_id,
            "crux_description": self.crux.description,
            "suggested_task": self.suggested_task,
            "priority": self.priority,
            "parent_debate_id": self.parent_debate_id,
            "suggested_agents": self.suggested_agents,
        }


@dataclass
class MockDisagreementMetrics:
    """Mock DisagreementMetrics for tests."""

    cruxes: list = field(default_factory=list)
    overall_disagreement: float = 0.5


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_storage():
    """Create a mock storage instance with sample debate data."""
    storage = Mock()
    storage.get_debate.return_value = {
        "id": "debate-001",
        "slug": "test-debate",
        "topic": "Test Topic",
        "messages": [
            {"round": 1, "agent": "claude", "content": "Message 1", "role": "proposer"},
            {"round": 2, "agent": "gpt4", "content": "Message 2", "role": "proposer"},
            {"round": 3, "agent": "claude", "content": "Message 3", "role": "critic"},
        ],
        "votes": [
            {
                "agent": "judge",
                "choice": "claude",
                "confidence": 0.8,
                "reasoning": "Good arguments",
            },
        ],
        "proposals": {"claude": "Proposal A", "gpt4": "Proposal B"},
        "agents": ["claude", "gpt4", "gemini"],
        "consensus_reached": False,
        "uncertainty_metrics": {
            "cruxes": [
                {
                    "id": "crux-001",
                    "description": "Is the premise correct?",
                    "agents": ["claude", "gpt4"],
                    "severity": 0.7,
                    "evidence_needed": "Empirical data",
                },
            ],
        },
    }
    # Every debate id resolves to a private debate of the test user's org.
    storage.get_access_info.side_effect = lambda ref: (ref, "test-org-001", False)
    return storage


@pytest.fixture
def mock_nomic_dir(tmp_path):
    """Create a temporary nomic directory."""
    nomic_dir = tmp_path / "nomic"
    nomic_dir.mkdir()
    return nomic_dir


@pytest.fixture
def debates_handler(mock_storage, mock_nomic_dir):
    """Create a DebatesHandler with mock storage."""
    ctx = {
        "storage": mock_storage,
        "nomic_dir": mock_nomic_dir,
    }
    handler = DebatesHandler(ctx)
    return handler


@pytest.fixture
def mock_handler_with_body():
    """Factory for creating mock handlers with JSON body."""

    def _create(body: dict):
        mock_handler = Mock()
        body_bytes = json.dumps(body).encode()
        # Use MagicMock for headers to properly support get()
        mock_handler.headers = MagicMock()
        mock_handler.headers.get.side_effect = lambda key, default="": {
            "Content-Type": "application/json",
            "Content-Length": str(len(body_bytes)),
        }.get(key, default)
        mock_handler.rfile = Mock()
        mock_handler.rfile.read = Mock(return_value=body_bytes)
        return mock_handler

    return _create


@pytest.fixture
def mock_empty_handler():
    """Create a mock handler with empty body."""
    mock_handler = Mock()
    # Use MagicMock for headers to properly support get()
    mock_handler.headers = MagicMock()
    mock_handler.headers.get.side_effect = lambda key, default="": {
        "Content-Type": "application/json",
        "Content-Length": "0",
    }.get(key, default)
    mock_handler.rfile = Mock()
    mock_handler.rfile.read = Mock(return_value=b"")
    return mock_handler


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear caches and rate limits before and after each test."""
    clear_cache()
    with _rate_limit_mod._limiters_lock:
        for limiter in _rate_limit_mod._limiters.values():
            limiter.clear()
    _user_limiter_mod._user_limiter = None
    yield
    clear_cache()
    with _rate_limit_mod._limiters_lock:
        for limiter in _rate_limit_mod._limiters.values():
            limiter.clear()
    _user_limiter_mod._user_limiter = None


# ============================================================================
# Route Matching Tests
# ============================================================================


class TestForkHandlerRouting:
    """Tests for fork-related route matching."""

    def test_can_handle_fork_endpoint(self, debates_handler):
        """Should handle POST /api/debates/{id}/fork."""
        assert debates_handler.can_handle("/api/v1/debates/debate-001/fork") is True

    def test_can_handle_verify_endpoint(self, debates_handler):
        """Should handle POST /api/debates/{id}/verify."""
        assert debates_handler.can_handle("/api/v1/debates/debate-001/verify") is True

    def test_can_handle_followups_endpoint(self, debates_handler):
        """Should handle GET /api/debates/{id}/followups."""
        assert debates_handler.can_handle("/api/v1/debates/debate-001/followups") is True

    def test_can_handle_followup_post_endpoint(self, debates_handler):
        """Should handle POST /api/debates/{id}/followup."""
        assert debates_handler.can_handle("/api/v1/debates/debate-001/followup") is True


# ============================================================================
# Fork Debate Validation Tests
# ============================================================================


class TestForkDebateValidation:
    """Tests for fork debate input validation."""

    def test_fork_requires_json_body(self, debates_handler, mock_storage, mock_empty_handler):
        """Should return 400 for missing JSON body."""
        result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, mock_empty_handler)

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "error" in data

    def test_fork_requires_branch_point(self, debates_handler, mock_handler_with_body):
        """Should return 400 when branch_point is missing."""
        handler = mock_handler_with_body({"modified_context": "New context"})

        result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, handler)

        assert result.status_code == 400

    def test_fork_validates_branch_point_type(self, debates_handler, mock_handler_with_body):
        """Should return 400 for non-integer branch_point."""
        handler = mock_handler_with_body({"branch_point": "not-a-number"})

        result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, handler)

        assert result.status_code == 400

    def test_fork_validates_branch_point_negative(self, debates_handler, mock_handler_with_body):
        """Should return 400 for negative branch_point."""
        handler = mock_handler_with_body({"branch_point": -1})

        result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, handler)

        assert result.status_code == 400

    def test_fork_validates_branch_point_max(self, debates_handler, mock_handler_with_body):
        """Should return 400 for branch_point exceeding max (100)."""
        handler = mock_handler_with_body({"branch_point": 101})

        result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, handler)

        assert result.status_code == 400


# ============================================================================
# Fork Debate Logic Tests
# ============================================================================


class TestForkDebateLogic:
    """Tests for fork debate business logic."""

    def test_fork_returns_404_for_missing_debate(
        self, debates_handler, mock_storage, mock_handler_with_body
    ):
        """Should return 404 when debate doesn't exist."""
        mock_storage.get_debate.return_value = None
        handler = mock_handler_with_body({"branch_point": 1})

        result = debates_handler.handle_post("/api/debates/nonexistent/fork", {}, handler)

        assert result.status_code == 404
        data = json.loads(result.body)
        assert "not found" in data["error"].lower()

    def test_fork_returns_400_when_branch_point_exceeds_messages(
        self, debates_handler, mock_storage, mock_handler_with_body
    ):
        """Should return 400 when branch_point exceeds message count."""
        handler = mock_handler_with_body({"branch_point": 10})  # Only 3 messages

        result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, handler)

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "exceeds" in data["error"].lower()

    def test_fork_creates_branch_successfully(
        self, debates_handler, mock_handler_with_body, mock_nomic_dir
    ):
        """Should create a fork successfully with valid data."""
        handler = mock_handler_with_body({"branch_point": 2, "modified_context": "New context"})

        # Mock the counterfactual imports
        mock_counterfactual = MagicMock()
        mock_counterfactual.PivotClaim = MockPivotClaim
        mock_counterfactual.CounterfactualBranch = MockCounterfactualBranch
        mock_counterfactual.CounterfactualOrchestrator = MagicMock()

        with patch.dict("sys.modules", {"aragora.debate.counterfactual": mock_counterfactual}):
            result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, handler)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["success"] is True
        assert "branch_id" in data
        assert data["branch_point"] == 2
        assert data["messages_inherited"] == 2

    def test_fork_stores_branch_file(self, debates_handler, mock_handler_with_body, mock_nomic_dir):
        """Should store branch metadata in nomic directory."""
        handler = mock_handler_with_body({"branch_point": 1})

        mock_counterfactual = MagicMock()
        mock_counterfactual.PivotClaim = MockPivotClaim
        mock_counterfactual.CounterfactualBranch = MockCounterfactualBranch
        mock_counterfactual.CounterfactualOrchestrator = MagicMock()

        with patch.dict("sys.modules", {"aragora.debate.counterfactual": mock_counterfactual}):
            result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, handler)

        assert result.status_code == 200

        # Check that branch file was created
        branches_dir = mock_nomic_dir / "branches"
        assert branches_dir.exists()
        branch_files = list(branches_dir.glob("fork-*.json"))
        assert len(branch_files) == 1

    def test_fork_returns_503_when_counterfactual_unavailable(
        self, debates_handler, mock_handler_with_body
    ):
        """Should return 503 when counterfactual module is not available."""
        handler = mock_handler_with_body({"branch_point": 1})

        # Force ImportError by removing the module from sys.modules
        with patch.dict("sys.modules", {"aragora.debate.counterfactual": None}):
            import builtins

            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if "counterfactual" in name:
                    raise ImportError(f"No module named '{name}'")
                return original_import(name, *args, **kwargs)

            with patch.object(builtins, "__import__", mock_import):
                result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, handler)

        assert result.status_code == 503

    def test_fork_with_zero_branch_point(
        self, debates_handler, mock_handler_with_body, mock_nomic_dir
    ):
        """Should handle branch_point=0 (fork from start)."""
        handler = mock_handler_with_body({"branch_point": 0})

        mock_counterfactual = MagicMock()
        mock_counterfactual.PivotClaim = MockPivotClaim
        mock_counterfactual.CounterfactualBranch = MockCounterfactualBranch
        mock_counterfactual.CounterfactualOrchestrator = MagicMock()

        with patch.dict("sys.modules", {"aragora.debate.counterfactual": mock_counterfactual}):
            result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, handler)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["messages_inherited"] == 0


# ============================================================================
# Verify Outcome Tests
# ============================================================================


class TestVerifyOutcome:
    """Tests for POST /api/debates/{id}/verify endpoint."""

    def test_verify_with_invalid_json(self, debates_handler):
        """Should return 400 for invalid JSON body."""
        mock_handler = Mock()
        mock_handler.headers = MagicMock()
        mock_handler.headers.get.side_effect = lambda key, default="": {
            "Content-Type": "application/json",
            "Content-Length": "10",
        }.get(key, default)
        mock_handler.rfile = Mock()
        mock_handler.rfile.read = Mock(return_value=b"not json!!")

        result = debates_handler.handle_post("/api/debates/debate-001/verify", {}, mock_handler)

        assert result.status_code == 400

    def test_verify_with_position_tracker(self, debates_handler, mock_handler_with_body):
        """Should record verification when position tracker is available."""
        handler = mock_handler_with_body({"correct": True, "source": "external"})

        mock_tracker = Mock()
        debates_handler.ctx["position_tracker"] = mock_tracker

        result = debates_handler.handle_post("/api/debates/debate-001/verify", {}, handler)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["status"] == "verified"
        assert data["correct"] is True
        mock_tracker.record_verification.assert_called_once_with("debate-001", True, "external")

    def test_verify_defaults_source_to_manual(self, debates_handler, mock_handler_with_body):
        """Should default source to 'manual' if not provided."""
        handler = mock_handler_with_body({"correct": True})

        mock_tracker = Mock()
        debates_handler.ctx["position_tracker"] = mock_tracker

        result = debates_handler.handle_post("/api/debates/debate-001/verify", {}, handler)

        assert result.status_code == 200
        mock_tracker.record_verification.assert_called_once_with("debate-001", True, "manual")


# ============================================================================
# Get Followup Suggestions Tests
# ============================================================================


class TestGetFollowupSuggestions:
    """Tests for GET /api/debates/{id}/followups endpoint."""

    def test_followups_returns_404_for_missing_debate(self, debates_handler, mock_storage):
        """Should return 404 when debate doesn't exist."""
        mock_storage.get_debate.return_value = None

        result = debates_handler.handle("/api/debates/nonexistent/followups", {}, None)

        assert result.status_code == 404

    def test_followups_returns_empty_when_no_cruxes(self, debates_handler, mock_storage):
        """Should return empty suggestions when no cruxes identified."""
        mock_storage.get_debate.return_value = {
            "id": "debate-001",
            "messages": [],
            "votes": [],
            "proposals": {},
            "agents": ["claude"],
            "uncertainty_metrics": {},
        }

        mock_analyzer = MagicMock()
        mock_metrics = MockDisagreementMetrics(cruxes=[])
        mock_analyzer.analyze_disagreement.return_value = mock_metrics
        mock_analyzer.suggest_followups.return_value = []

        with patch(
            "aragora.uncertainty.estimator.DisagreementAnalyzer", return_value=mock_analyzer
        ):
            result = debates_handler.handle("/api/debates/debate-001/followups", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["suggestions"] == [] or data["count"] == 0

    def test_followups_returns_suggestions_from_stored_cruxes(self, debates_handler, mock_storage):
        """Should return suggestions based on stored uncertainty metrics."""
        mock_suggestion = MockFollowUpSuggestion()
        mock_analyzer = MagicMock()
        mock_analyzer.suggest_followups.return_value = [mock_suggestion]

        with patch(
            "aragora.uncertainty.estimator.DisagreementAnalyzer", return_value=mock_analyzer
        ):
            with patch("aragora.uncertainty.estimator.DisagreementCrux", MockDisagreementCrux):
                result = debates_handler.handle("/api/debates/debate-001/followups", {}, None)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert "count" in data


# ============================================================================
# Create Followup Debate Tests
# ============================================================================


class TestCreateFollowupDebate:
    """Tests for POST /api/debates/{id}/followup endpoint."""

    def test_followup_requires_crux_or_task(self, debates_handler, mock_handler_with_body):
        """Should return 400 when neither crux_id nor task provided."""
        handler = mock_handler_with_body({})

        result = debates_handler.handle_post("/api/debates/debate-001/followup", {}, handler)

        assert result.status_code == 400
        data = json.loads(result.body)
        assert "crux_id or task" in data["error"].lower()

    def test_followup_returns_404_for_missing_debate(
        self, debates_handler, mock_storage, mock_handler_with_body
    ):
        """Should return 404 when parent debate doesn't exist."""
        mock_storage.get_debate.return_value = None
        handler = mock_handler_with_body({"task": "Follow-up task"})

        result = debates_handler.handle_post("/api/debates/nonexistent/followup", {}, handler)

        assert result.status_code == 404

    def test_followup_returns_404_for_missing_crux(
        self, debates_handler, mock_storage, mock_handler_with_body
    ):
        """Should return 404 when specified crux_id not found."""
        handler = mock_handler_with_body({"crux_id": "crux-nonexistent"})

        result = debates_handler.handle_post("/api/debates/debate-001/followup", {}, handler)

        assert result.status_code == 404
        data = json.loads(result.body)
        assert "crux not found" in data["error"].lower()

    def test_followup_creates_with_custom_task(
        self, debates_handler, mock_storage, mock_handler_with_body, mock_nomic_dir
    ):
        """Should create followup with custom task."""
        handler = mock_handler_with_body({"task": "Custom follow-up task"})

        result = debates_handler.handle_post("/api/debates/debate-001/followup", {}, handler)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["success"] is True
        assert data["task"] == "Custom follow-up task"
        assert data["parent_debate_id"] == "debate-001"

    def test_followup_creates_with_crux_id(
        self, debates_handler, mock_storage, mock_handler_with_body, mock_nomic_dir
    ):
        """Should create followup based on crux_id."""
        handler = mock_handler_with_body({"crux_id": "crux-001"})

        mock_analyzer = MagicMock()
        mock_analyzer._generate_followup_task.return_value = "Generated task from crux"

        with patch(
            "aragora.uncertainty.estimator.DisagreementAnalyzer", return_value=mock_analyzer
        ):
            with patch("aragora.uncertainty.estimator.DisagreementCrux", MockDisagreementCrux):
                result = debates_handler.handle_post(
                    "/api/debates/debate-001/followup", {}, handler
                )

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["crux_id"] == "crux-001"

    def test_followup_stores_file(
        self, debates_handler, mock_storage, mock_handler_with_body, mock_nomic_dir
    ):
        """Should store followup metadata in nomic directory."""
        handler = mock_handler_with_body({"task": "Test followup"})

        result = debates_handler.handle_post("/api/debates/debate-001/followup", {}, handler)

        assert result.status_code == 200

        # Check that followup file was created
        followups_dir = mock_nomic_dir / "followups"
        assert followups_dir.exists()
        followup_files = list(followups_dir.glob("followup-*.json"))
        assert len(followup_files) == 1


# ============================================================================
# Security Tests
# ============================================================================


class TestForkSecurity:
    """Security tests for fork operations."""

    def test_fork_path_traversal_blocked(
        self, debates_handler, mock_handler_with_body, mock_storage
    ):
        """Should block path traversal attempts in debate_id."""
        handler = mock_handler_with_body({"branch_point": 1})
        mock_storage.get_debate.return_value = None  # Not found is fine

        result = debates_handler.handle_post("/api/debates/../../../etc/passwd/fork", {}, handler)

        # Should return 400 (invalid) or 404 (not found), not success
        assert result.status_code in (400, 404)

    def test_followup_path_traversal_blocked(
        self, debates_handler, mock_handler_with_body, mock_storage
    ):
        """Should block path traversal in followup endpoint."""
        handler = mock_handler_with_body({"task": "Test"})
        mock_storage.get_debate.return_value = None

        result = debates_handler.handle_post(
            "/api/debates/../../../etc/passwd/followup", {}, handler
        )

        assert result.status_code in (400, 404)

    def test_verify_path_traversal_blocked(self, debates_handler, mock_handler_with_body):
        """Should block path traversal in verify endpoint."""
        handler = mock_handler_with_body({"correct": True})

        result = debates_handler.handle_post("/api/debates/../../../etc/passwd/verify", {}, handler)

        # Should not execute dangerous code
        assert result.status_code in (400, 404, 503)


# ============================================================================
# Edge Cases
# ============================================================================


class TestForkEdgeCases:
    """Edge case tests for fork operations."""

    def test_fork_empty_debate(
        self, debates_handler, mock_storage, mock_handler_with_body, mock_nomic_dir
    ):
        """Should handle forking a debate with no messages."""
        mock_storage.get_debate.return_value = {
            "id": "empty-debate",
            "messages": [],
            "votes": [],
            "agents": [],
        }
        handler = mock_handler_with_body({"branch_point": 0})

        mock_counterfactual = MagicMock()
        mock_counterfactual.PivotClaim = MockPivotClaim
        mock_counterfactual.CounterfactualBranch = MockCounterfactualBranch
        mock_counterfactual.CounterfactualOrchestrator = MagicMock()

        with patch.dict("sys.modules", {"aragora.debate.counterfactual": mock_counterfactual}):
            result = debates_handler.handle_post("/api/debates/empty-debate/fork", {}, handler)

        assert result.status_code == 200

    def test_followup_inherits_parent_agents(
        self, debates_handler, mock_storage, mock_handler_with_body, mock_nomic_dir
    ):
        """Should inherit agents from parent debate when not specified."""
        handler = mock_handler_with_body({"task": "Follow-up task"})

        result = debates_handler.handle_post("/api/debates/debate-001/followup", {}, handler)

        assert result.status_code == 200
        data = json.loads(result.body)
        # Should have agents from parent (claude, gpt4, gemini -> take first 3)
        assert len(data["agents"]) > 0

    def test_fork_without_nomic_dir(self, debates_handler, mock_storage, mock_handler_with_body):
        """Should handle fork when nomic_dir is not configured."""
        debates_handler.ctx["nomic_dir"] = None
        handler = mock_handler_with_body({"branch_point": 1})

        mock_counterfactual = MagicMock()
        mock_counterfactual.PivotClaim = MockPivotClaim
        mock_counterfactual.CounterfactualBranch = MockCounterfactualBranch
        mock_counterfactual.CounterfactualOrchestrator = MagicMock()

        with patch.dict("sys.modules", {"aragora.debate.counterfactual": mock_counterfactual}):
            result = debates_handler.handle_post("/api/debates/debate-001/fork", {}, handler)

        # Should still succeed, just not persist to disk
        assert result.status_code == 200

    def test_followup_with_custom_agents(
        self, debates_handler, mock_storage, mock_handler_with_body, mock_nomic_dir
    ):
        """Should use custom agents when provided."""
        handler = mock_handler_with_body({"task": "Custom task", "agents": ["mistral", "llama"]})

        result = debates_handler.handle_post("/api/debates/debate-001/followup", {}, handler)

        assert result.status_code == 200
        data = json.loads(result.body)
        assert data["agents"] == ["mistral", "llama"]
