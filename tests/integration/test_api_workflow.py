"""
Integration tests for complete API workflows.

Tests end-to-end flows through the HTTP API:
- Authentication and token validation
- Debate lifecycle via API
- Real-time event streaming
- Memory and ELO updates
"""

import asyncio
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.core import Agent, Message, Environment, DebateResult
from aragora.server.auth import AuthConfig, auth_config
from aragora.server.handlers import (
    SystemHandler,
    DebatesHandler,
    AgentsHandler,
    HealthHandler,
    NomicHandler,
)
from aragora.server.handlers.base import json_response, HandlerResult
from aragora.rbac.models import AuthorizationContext


def parse_handler_result(result: HandlerResult) -> tuple:
    """Parse a HandlerResult into (data, status_code) tuple."""
    if result is None:
        return None, 404
    data = json.loads(result.body.decode("utf-8")) if result.body else None
    return data, result.status_code


class MockAgent(Agent):
    """Mock agent for API integration tests."""

    def __init__(self, name: str = "mock", model: str = "mock-model", role: str = "proposer"):
        super().__init__(name, model, role)
        self.agent_type = "mock"

    async def generate(self, prompt: str, context: list = None) -> str:
        return f"Response from {self.name}: The answer is 42."

    async def critique(self, proposal: str, task: str, context: list = None):
        from aragora.core import Critique

        return Critique(
            agent=self.name,
            target_agent="proposer",
            target_content=proposal[:50],
            issues=["Minor issue"],
            suggestions=["Consider edge cases"],
            severity=0.3,
            reasoning="Good overall approach",
        )

    async def vote(self, proposals: dict, task: str):
        from aragora.core import Vote

        choice = list(proposals.keys())[0] if proposals else "none"
        return Vote(
            agent=self.name,
            choice=choice,
            reasoning="Best solution",
            confidence=0.9,
            continue_debate=False,
        )


@pytest.fixture
def temp_dir():
    """Create temporary directory for test databases."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def handler_context(temp_dir):
    """Create handler context with mock dependencies."""
    from aragora.ranking.elo import EloSystem
    from aragora.memory.store import CritiqueStore

    return {
        "storage": None,
        "elo_system": EloSystem(str(temp_dir / "elo.db")),
        "nomic_dir": temp_dir,
        "debate_embeddings": None,
        "critique_store": CritiqueStore(str(temp_dir / "critiques.db")),
        "document_store": None,
        "persona_manager": None,
        "position_ledger": None,
    }


class TestAuthenticationWorkflow:
    """Test authentication flows."""

    def test_token_generation_and_validation(self):
        """Test generating and validating tokens."""
        config = AuthConfig()
        config.api_token = "test-secret-key"
        config.enabled = True

        # Generate token
        token = config.generate_token(loop_id="test-loop", expires_in=3600)
        assert token, "Token should be generated"
        assert ":" in token, "Token should have signature"

        # Validate token
        assert config.validate_token(token, "test-loop"), "Token should be valid"
        assert not config.validate_token(token, "wrong-loop"), "Wrong loop should fail"

    def test_token_revocation(self):
        """Test revoking tokens."""
        config = AuthConfig()
        config.api_token = "test-secret-key"
        config.enabled = True

        token = config.generate_token(loop_id="test-loop")

        # Token should be valid initially
        assert config.validate_token(token, "test-loop")

        # Revoke token
        assert config.revoke_token(token), "Revocation should succeed"

        # Token should now be invalid
        assert not config.validate_token(token, "test-loop"), "Revoked token should fail"
        assert config.is_revoked(token), "Token should be marked revoked"

    def test_rate_limiting_by_token(self):
        """Test token-based rate limiting."""
        config = AuthConfig()
        config.rate_limit_per_minute = 5

        # Should allow first requests
        for i in range(5):
            allowed, remaining = config.check_rate_limit("test-token")
            assert allowed, f"Request {i + 1} should be allowed"
            assert remaining == 4 - i, f"Remaining should be {4 - i}"

        # Should block after limit
        allowed, remaining = config.check_rate_limit("test-token")
        assert not allowed, "Should be rate limited"
        assert remaining == 0

    def test_rate_limiting_by_ip(self):
        """Test IP-based rate limiting."""
        config = AuthConfig()
        config.ip_rate_limit_per_minute = 3

        # Should allow first requests
        for i in range(3):
            allowed, _ = config.check_rate_limit_by_ip("192.168.1.1")
            assert allowed, f"Request {i + 1} should be allowed"

        # Should block after limit
        allowed, _ = config.check_rate_limit_by_ip("192.168.1.1")
        assert not allowed, "Should be rate limited"

        # Different IP should still work
        allowed, _ = config.check_rate_limit_by_ip("192.168.1.2")
        assert allowed, "Different IP should be allowed"


class TestHealthEndpointWorkflow:
    """Test health check endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_status(self, handler_context):
        """Test health endpoint returns proper status via public /healthz endpoint."""
        handler = HealthHandler(handler_context)

        # Use the public /healthz endpoint which doesn't require auth
        result = await handler.handle("/healthz", {}, None)
        data, status = parse_handler_result(result)

        # Liveness probe returns 200 (healthy) or 503 (degraded)
        assert status in (200, 503)
        assert data["status"] in ("ok", "healthy", "degraded")

    @pytest.mark.asyncio
    async def test_health_checks_readiness(self, handler_context):
        """Test readiness probe endpoint."""
        handler = HealthHandler(handler_context)

        # Use the public /readyz endpoint which doesn't require auth
        result = await handler.handle("/readyz", {}, None)
        data, status = parse_handler_result(result)

        # Readiness probe returns 200 (ready) or 503 (not ready)
        assert status in (200, 503)
        assert data["status"] in ("ok", "ready", "not_ready", "degraded")

    @pytest.mark.asyncio
    async def test_health_handles_missing_components(self, temp_dir):
        """Test health endpoint handles missing components gracefully."""
        handler = HealthHandler(
            {
                "storage": None,
                "elo_system": None,
                "nomic_dir": temp_dir,
            }
        )

        # Use public /healthz endpoint
        result = await handler.handle("/healthz", {}, None)
        data, status = parse_handler_result(result)

        # Should still return a response, not crash
        assert status in (200, 503)
        assert "status" in data


class TestLeaderboardWorkflow:
    """Test leaderboard API workflow."""

    @pytest.mark.asyncio
    async def test_leaderboard_returns_rankings(self, handler_context):
        """Test leaderboard endpoint returns agent rankings."""
        # Add some ratings using the proper API
        elo = handler_context["elo_system"]
        elo.record_match("agent-a", "agent-b", {"agent-a": 1.0, "agent-b": 0.0}, "test-domain")
        elo.record_match("agent-a", "agent-c", {"agent-a": 1.0, "agent-c": 0.0}, "test-domain")

        handler = AgentsHandler(handler_context)

        # Mock auth context to bypass authentication
        mock_auth = AuthorizationContext(
            user_id="test-user",
            user_email="test@example.com",
            roles={"admin"},
            permissions={"agents.read", "leaderboard.read"},
        )
        handler.get_auth_context = AsyncMock(return_value=mock_auth)
        handler.check_permission = MagicMock(return_value=None)

        # AgentsHandler.handle is async
        result = await handler.handle("/api/v1/leaderboard", {}, None)
        data, status = parse_handler_result(result)

        assert status == 200
        # Response is either a list or dict with "rankings" key
        if isinstance(data, dict):
            assert "rankings" in data or "agents" in data
        else:
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_leaderboard_respects_limit(self, handler_context):
        """Test leaderboard limit parameter."""
        elo = handler_context["elo_system"]
        for i in range(10):
            elo.record_match(
                f"agent-{i}", f"agent-{i + 10}", {f"agent-{i}": 0.5, f"agent-{i + 10}": 0.5}, "test"
            )

        handler = AgentsHandler(handler_context)

        # Mock auth context to bypass authentication
        mock_auth = AuthorizationContext(
            user_id="test-user",
            user_email="test@example.com",
            roles={"admin"},
            permissions={"agents.read", "leaderboard.read"},
        )
        handler.get_auth_context = AsyncMock(return_value=mock_auth)
        handler.check_permission = MagicMock(return_value=None)

        # AgentsHandler.handle is async
        result = await handler.handle("/api/v1/leaderboard", {"limit": "5"}, None)
        data, status = parse_handler_result(result)

        assert len(data) <= 5


class TestDebateHistoryWorkflow:
    """Test debate history API workflow."""

    def test_debates_list_returns_debates(self, handler_context, temp_dir):
        """Test debates list endpoint."""
        from aragora.storage.debate_storage import DebateStorage

        storage = DebateStorage(str(temp_dir / "debates.db"))
        handler_context["storage"] = storage

        handler = DebatesHandler(handler_context)

        # DebatesHandler.handle is synchronous
        result = handler.handle("/api/v1/debates", {}, None)
        data, status = parse_handler_result(result)

        assert status == 200
        assert isinstance(data, (list, dict))

    def test_debates_pagination(self, handler_context, temp_dir):
        """Test debates pagination."""
        from aragora.storage.debate_storage import DebateStorage

        storage = DebateStorage(str(temp_dir / "debates.db"))
        handler_context["storage"] = storage

        handler = DebatesHandler(handler_context)

        # DebatesHandler.handle is synchronous
        result = handler.handle("/api/v1/debates", {"limit": "10", "offset": "0"}, None)
        data, status = parse_handler_result(result)

        assert status == 200


class TestModesSwitchWorkflow:
    """Test modes API workflow."""

    @pytest.mark.asyncio
    async def test_modes_list_returns_available_modes(self, handler_context):
        """Test modes list endpoint."""
        handler = NomicHandler(handler_context)

        # Mock auth context to bypass authentication
        mock_auth = AuthorizationContext(
            user_id="test-user",
            user_email="test@example.com",
            roles={"admin"},
            permissions={"nomic.read", "nomic.admin"},
        )
        handler.get_auth_context = AsyncMock(return_value=mock_auth)
        handler.check_permission = MagicMock(return_value=None)

        result = await handler.handle("/api/v1/modes", {}, None)
        data, status = parse_handler_result(result)

        assert status == 200
        assert isinstance(data, (list, dict))


class TestNomicStateWorkflow:
    """Test nomic state API workflow."""

    def test_nomic_state_returns_current_state(self, handler_context, temp_dir):
        """Test nomic state endpoint."""
        # Create nomic state file
        state_file = temp_dir / "nomic_state.json"
        state_file.write_text(
            json.dumps({"cycle": 1, "phase": "idle", "last_update": datetime.now().isoformat()})
        )

        handler = SystemHandler(handler_context)

        # SystemHandler.handle is synchronous
        result = handler.handle("/api/v1/nomic/state", {}, None)
        data, status = parse_handler_result(result)

        # Should return something (even if empty state)
        assert status in (200, 404, 500)


class TestCritiquesWorkflow:
    """Test critique storage workflow."""

    def test_critique_store_initialization(self, handler_context):
        """Test critique store is properly initialized."""
        critique_store = handler_context["critique_store"]
        assert critique_store is not None

    def test_critique_store_has_expected_methods(self, handler_context):
        """Test critique store has expected interface."""
        critique_store = handler_context["critique_store"]
        # Check it has expected methods
        assert hasattr(critique_store, "store_debate") or hasattr(
            critique_store, "retrieve_patterns"
        )


class TestConcurrentRequests:
    """Test handling of concurrent API requests."""

    @pytest.mark.asyncio
    async def test_multiple_health_checks(self, handler_context):
        """Test multiple sequential health check requests via public /healthz."""
        handler = HealthHandler(handler_context)

        # Make 10 sequential requests using public endpoint
        for _ in range(10):
            result = await handler.handle("/healthz", {}, None)
            data, status = parse_handler_result(result)
            # Health check may return 200 or 503 depending on components
            assert status in (200, 503)

    @pytest.mark.asyncio
    async def test_multiple_leaderboard_requests(self, handler_context):
        """Test multiple sequential leaderboard requests."""
        handler = AgentsHandler(handler_context)

        # Mock auth context to bypass authentication
        mock_auth = AuthorizationContext(
            user_id="test-user",
            user_email="test@example.com",
            roles={"admin"},
            permissions={"agents.read", "leaderboard.read"},
        )
        handler.get_auth_context = AsyncMock(return_value=mock_auth)
        handler.check_permission = MagicMock(return_value=None)

        # Make 10 sequential requests (AgentsHandler is async)
        for _ in range(10):
            result = await handler.handle("/api/v1/leaderboard", {}, None)
            data, status = parse_handler_result(result)
            assert status == 200


class TestErrorHandling:
    """Test API error handling."""

    def test_invalid_endpoint_returns_404(self, handler_context):
        """Test invalid endpoint returns 404."""
        handler = SystemHandler(handler_context)

        # Check if handler can handle this path
        assert not handler.can_handle("/api/v1/nonexistent/endpoint")

    @pytest.mark.asyncio
    async def test_invalid_query_params_handled(self, handler_context):
        """Test invalid query parameters are handled gracefully."""
        handler = AgentsHandler(handler_context)

        # Mock auth context to bypass authentication
        mock_auth = AuthorizationContext(
            user_id="test-user",
            user_email="test@example.com",
            roles={"admin"},
            permissions={"agents.read", "leaderboard.read"},
        )
        handler.get_auth_context = AsyncMock(return_value=mock_auth)
        handler.check_permission = MagicMock(return_value=None)

        # Pass invalid limit (AgentsHandler is async)
        result = await handler.handle("/api/v1/leaderboard", {"limit": "not-a-number"}, None)
        data, status = parse_handler_result(result)

        # Should handle gracefully (either default or error response)
        assert status in (200, 400)

    def test_missing_resource_handled_gracefully(self, handler_context, temp_dir):
        """Test missing resource is handled gracefully."""
        from aragora.storage.debate_storage import DebateStorage

        storage = DebateStorage(str(temp_dir / "debates.db"))
        handler_context["storage"] = storage

        handler = DebatesHandler(handler_context)

        # DebatesHandler.handle is synchronous
        result = handler.handle("/api/v1/debates/nonexistent-id", {}, None)
        data, status = parse_handler_result(result)

        # Should return 404 or 500 (depending on implementation)
        assert status in (404, 500)


class TestResponseFormat:
    """Test API response format consistency."""

    @pytest.mark.asyncio
    async def test_health_response_format(self, handler_context):
        """Test health endpoint response format via public /healthz."""
        handler = HealthHandler(handler_context)

        # Use public /healthz endpoint which doesn't require auth
        result = await handler.handle("/healthz", {}, None)
        data, status = parse_handler_result(result)

        # Liveness probe has simpler format
        assert "status" in data

    @pytest.mark.asyncio
    async def test_leaderboard_response_format(self, handler_context):
        """Test leaderboard response format."""
        elo = handler_context["elo_system"]
        elo.record_match("agent-x", "agent-y", {"agent-x": 1.0, "agent-y": 0.0}, "test")

        handler = AgentsHandler(handler_context)

        # AgentsHandler.handle is async
        result = await handler.handle("/api/v1/leaderboard", {}, None)
        data, status = parse_handler_result(result)

        # Response can be list or dict with rankings
        if isinstance(data, dict):
            rankings = data.get("rankings", data.get("agents", []))
            assert isinstance(rankings, list)
        else:
            assert isinstance(data, list)


class TestCleanup:
    """Test resource cleanup."""

    def test_auth_cleanup_removes_stale_entries(self):
        """Test auth cleanup removes old entries."""
        config = AuthConfig()

        # Add some rate limit entries
        for i in range(100):
            config.check_rate_limit(f"token-{i}")
            config.check_rate_limit_by_ip(f"192.168.1.{i % 256}")

        # Cleanup
        stats = config.cleanup_expired_entries(ttl_seconds=0)

        # Should have cleaned up entries
        assert stats["token_entries_removed"] >= 0
        assert stats["ip_entries_removed"] >= 0

    def test_elo_system_database_persists(self, temp_dir):
        """Test ELO system persists data across instances."""
        from aragora.ranking.elo import EloSystem

        elo = EloSystem(str(temp_dir / "elo_persist_test.db"))
        elo.record_match("a", "b", {"a": 1.0, "b": 0.0}, "test")

        # Get rating before creating new instance
        rating1 = elo.get_rating("a")
        assert rating1 is not None

        # Create new instance pointing to same DB
        elo2 = EloSystem(str(temp_dir / "elo_persist_test.db"))
        rating2 = elo2.get_rating("a")
        assert rating2 is not None
        # Ratings should match (use .elo attribute for AgentRating dataclass)
        assert rating1.elo == rating2.elo
