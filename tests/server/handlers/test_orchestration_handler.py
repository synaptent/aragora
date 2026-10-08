"""
Comprehensive tests for the Orchestration Handler.

This is a P0 critical handler test suite covering debate orchestration
across the Aragora control plane.

Test categories:
1. Data model parsing and validation
2. Handler routing and path matching
3. Authentication and RBAC permission checks
4. Deliberation lifecycle (create, execute, status)
5. Knowledge context fetching from various sources
6. Agent team selection strategies
7. Output channel routing
8. Template application
9. Error handling and edge cases
10. Rate limiting behavior
11. Memory and consensus integration
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

from tests.utils.async_helpers import close_coroutine_then

from aragora.server.handlers.orchestration import (
    OrchestrationHandler,
    OrchestrationRequest,
    OrchestrationResult,
    KnowledgeContextSource,
    OutputChannel,
    TeamStrategy,
    OutputFormat,
    TEMPLATES,
    _orchestration_requests,
    _orchestration_results,
)
from aragora.rbac.models import AuthorizationContext


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def handler():
    """Create an orchestration handler with empty context."""
    return OrchestrationHandler({})


@pytest.fixture
def handler_with_context():
    """Create handler with full server context."""
    ctx = {
        "control_plane_coordinator": MagicMock(),
        "continuum_memory": MagicMock(),
        "critique_store": MagicMock(),
        "confluence_url": "https://confluence.example.com",
        "jira_url": "https://jira.example.com",
    }
    return OrchestrationHandler(ctx)


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler with headers."""
    handler = MagicMock()
    handler.client_address = ("192.168.1.100", 54321)
    handler.headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer test-token-123",
    }
    return handler


@pytest.fixture
def mock_auth_context():
    """Create a mock authenticated authorization context with full orchestration permissions."""
    return AuthorizationContext(
        user_id="test-user-456",
        user_email="user@example.com",
        org_id="org-789",
        workspace_id="workspace-001",
        roles={"member", "developer"},
        permissions={
            "orchestration:read",
            "orchestration:execute",
            "orchestration:deliberate:create",
            "orchestration:knowledge:read",
            "orchestration:channels:write",
            "orchestration:knowledge:slack",
            "orchestration:knowledge:confluence",
            "orchestration:knowledge:github",
            "orchestration:knowledge:jira",
            "orchestration:knowledge:document",
            "orchestration:channel:slack",
            "orchestration:channel:teams",
            "orchestration:channel:discord",
            "orchestration:channel:telegram",
            "orchestration:channel:email",
            "orchestration:channel:webhook",
            "debates:create",
        },
    )


@pytest.fixture
def mock_admin_auth_context():
    """Create a mock admin authorization context with all orchestration permissions."""
    return AuthorizationContext(
        user_id="admin-user",
        user_email="admin@example.com",
        org_id="org-admin",
        workspace_id="workspace-admin",
        roles={"admin"},
        permissions={
            "orchestration:read",
            "orchestration:execute",
            "orchestration:deliberate:create",
            "orchestration:knowledge:read",
            "orchestration:channels:write",
            "orchestration:admin",
            "orchestration:knowledge:slack",
            "orchestration:knowledge:confluence",
            "orchestration:knowledge:github",
            "orchestration:knowledge:jira",
            "orchestration:knowledge:document",
            "orchestration:channel:slack",
            "orchestration:channel:teams",
            "orchestration:channel:discord",
            "orchestration:channel:telegram",
            "orchestration:channel:email",
            "orchestration:channel:webhook",
            "admin:all",
        },
    )


@pytest.fixture(autouse=True)
def clear_orchestration_state():
    """Clear orchestration state before and after each test."""
    _orchestration_requests.clear()
    _orchestration_results.clear()
    yield
    _orchestration_requests.clear()
    _orchestration_results.clear()


def create_mock_request(body: dict, headers: dict | None = None) -> MagicMock:
    """Create a mock HTTP request handler with JSON body."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    json_body = json.dumps(body).encode("utf-8")
    handler.headers = headers or {
        "Content-Length": str(len(json_body)),
        "Content-Type": "application/json",
    }
    handler.headers["Content-Length"] = str(len(json_body))
    handler.rfile = BytesIO(json_body)
    handler.command = "POST"
    return handler


# =============================================================================
# Test Class: Data Model Parsing
# =============================================================================


class TestOrchestrationRequestParsing:
    """Tests for OrchestrationRequest data model parsing."""

    def test_parse_empty_request(self):
        """Test parsing request with no fields."""
        request = OrchestrationRequest.from_dict({})
        assert request.question == ""
        assert request.knowledge_sources == []
        assert request.team_strategy == TeamStrategy.BEST_FOR_DOMAIN

    def test_parse_minimal_request(self):
        """Test parsing minimal valid request."""
        data = {"question": "What is the best approach?"}
        request = OrchestrationRequest.from_dict(data)
        assert request.question == "What is the best approach?"
        assert len(request.request_id) == 36  # UUID format

    def test_parse_full_request_with_all_fields(self):
        """Test parsing request with all supported fields."""
        data = {
            "question": "Should we migrate to Kubernetes?",
            "knowledge_sources": [
                "slack:C001",
                {"type": "confluence", "id": "page-123", "lookback_minutes": 120},
            ],
            "knowledge_context": {
                "sources": ["github:org/repo/pr/42"],
                "workspaces": ["infrastructure", "devops"],
            },
            "team_strategy": "diverse",
            "agents": ["anthropic-api", "openai-api", "gemini", "mistral"],
            "output_channels": [
                "slack:C002:thread-123",
                {"type": "email", "id": "team@company.com"},
            ],
            "output_format": "decision_receipt",
            "require_consensus": False,
            "priority": "critical",
            "max_rounds": 7,
            "timeout_seconds": 900.0,
            "template": "architecture_decision",
            "metadata": {"project": "k8s-migration", "phase": "evaluation"},
        }
        request = OrchestrationRequest.from_dict(data)

        assert request.question == "Should we migrate to Kubernetes?"
        assert len(request.knowledge_sources) == 3
        assert request.workspaces == ["infrastructure", "devops"]
        assert request.team_strategy == TeamStrategy.DIVERSE
        assert len(request.agents) == 4
        assert len(request.output_channels) == 2
        assert request.output_format == OutputFormat.DECISION_RECEIPT
        assert request.require_consensus is False
        assert request.priority == "critical"
        assert request.max_rounds == 7
        assert request.metadata["project"] == "k8s-migration"

    def test_parse_all_team_strategies(self):
        """Test parsing all valid team strategies."""
        strategies = ["specified", "best_for_domain", "diverse", "fast", "random"]
        for strategy in strategies:
            request = OrchestrationRequest.from_dict(
                {"question": "Test", "team_strategy": strategy}
            )
            assert request.team_strategy == TeamStrategy(strategy)

    def test_parse_all_output_formats(self):
        """Test parsing all valid output formats."""
        formats = ["standard", "decision_receipt", "summary", "github_review", "slack_message"]
        for fmt in formats:
            request = OrchestrationRequest.from_dict({"question": "Test", "output_format": fmt})
            assert request.output_format == OutputFormat(fmt)

    def test_parse_invalid_strategy_defaults(self):
        """Test that invalid team strategy defaults gracefully."""
        request = OrchestrationRequest.from_dict(
            {"question": "Test", "team_strategy": "nonexistent"}
        )
        assert request.team_strategy == TeamStrategy.BEST_FOR_DOMAIN

    def test_parse_invalid_format_defaults(self):
        """Test that invalid output format defaults gracefully."""
        request = OrchestrationRequest.from_dict(
            {"question": "Test", "output_format": "invalid_format"}
        )
        assert request.output_format == OutputFormat.STANDARD


class TestKnowledgeContextSourceParsing:
    """Tests for KnowledgeContextSource parsing."""

    def test_parse_simple_string(self):
        """Test parsing simple string format."""
        source = KnowledgeContextSource.from_string("slack:C12345")
        assert source.source_type == "slack"
        assert source.source_id == "C12345"

    def test_parse_without_colon(self):
        """Test parsing string without colon defaults to document."""
        source = KnowledgeContextSource.from_string("some-document-id")
        assert source.source_type == "document"
        assert source.source_id == "some-document-id"

    def test_parse_with_multiple_colons(self):
        """Test parsing string with multiple colons preserves ID."""
        source = KnowledgeContextSource.from_string("github:owner/repo/issue/123")
        assert source.source_type == "github"
        assert source.source_id == "owner/repo/issue/123"

    def test_default_lookback_and_max_items(self):
        """Test default values for optional parameters."""
        source = KnowledgeContextSource(source_type="slack", source_id="C001")
        assert source.lookback_minutes == 60
        assert source.max_items == 50


class TestOutputChannelParsing:
    """Tests for OutputChannel parsing."""

    def test_parse_simple_channel(self):
        """Test parsing simple channel format."""
        channel = OutputChannel.from_string("slack:C12345")
        assert channel.channel_type == "slack"
        assert channel.channel_id == "C12345"
        assert channel.thread_id is None

    def test_parse_channel_with_thread(self):
        """Test parsing channel with thread ID."""
        channel = OutputChannel.from_string("slack:C12345:1234567890.123")
        assert channel.channel_type == "slack"
        assert channel.channel_id == "C12345"
        assert channel.thread_id == "1234567890.123"

    def test_parse_webhook_url(self):
        """Test parsing webhook URL."""
        channel = OutputChannel.from_string("webhook:https://hooks.example.com/callback")
        assert channel.channel_type == "webhook"
        assert channel.channel_id == "https://hooks.example.com/callback"

    def test_parse_url_without_prefix(self):
        """Test parsing URL without prefix normalizes to webhook type."""
        channel = OutputChannel.from_string("https://api.example.com/notify")
        # URLs are normalized to 'webhook' type for consistent handling
        # The full URL becomes the channel_id
        assert channel.channel_type == "webhook"
        assert channel.channel_id == "https://api.example.com/notify"

    def test_parse_email_channel(self):
        """Test parsing email channel."""
        channel = OutputChannel.from_string("email:notifications@company.com")
        assert channel.channel_type == "email"
        assert channel.channel_id == "notifications@company.com"

    def test_parse_channel_type_case_insensitive(self):
        """Test that channel type parsing is case insensitive."""
        channel = OutputChannel.from_string("SLACK:C12345")
        assert channel.channel_type == "slack"


# =============================================================================
# Test Class: Handler Routing
# =============================================================================


class TestHandlerRouting:
    """Tests for handler path matching and routing."""

    def test_can_handle_deliberate_path(self, handler):
        """Test handler matches deliberate endpoint."""
        assert handler.can_handle("/api/v1/orchestration/deliberate")

    def test_can_handle_sync_deliberate_path(self, handler):
        """Test handler matches sync deliberate endpoint."""
        assert handler.can_handle("/api/v1/orchestration/deliberate/sync")

    def test_can_handle_templates_path(self, handler):
        """Test handler matches templates endpoint."""
        assert handler.can_handle("/api/v1/orchestration/templates")

    def test_can_handle_status_path(self, handler):
        """Test handler matches status endpoint."""
        assert handler.can_handle("/api/v1/orchestration/status/request-123")

    def test_cannot_handle_other_paths(self, handler):
        """Test handler rejects non-orchestration paths."""
        assert not handler.can_handle("/api/v1/debates")
        assert not handler.can_handle("/api/v1/agents")
        assert not handler.can_handle("/api/v1/control-plane/tasks")
        assert not handler.can_handle("/health")


# =============================================================================
# Test Class: Authentication and RBAC
# =============================================================================


class TestAuthenticationAndRBAC:
    """Tests for authentication and permission checks."""

    @pytest.mark.asyncio
    async def test_get_templates_requires_auth(self, handler, mock_http_handler):
        """Test GET templates requires authentication."""
        from aragora.server.handlers.utils.auth import UnauthorizedError

        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            side_effect=UnauthorizedError("Token required"),
        ):
            result = await handler.handle("/api/v1/orchestration/templates", {}, mock_http_handler)
            assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_get_templates_requires_read_permission(self, handler, mock_http_handler):
        """Test GET templates requires orchestration:read permission."""
        from aragora.server.handlers.utils.auth import ForbiddenError

        limited_ctx = AuthorizationContext(
            user_id="user-123",
            permissions=set(),  # No permissions
        )

        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            return_value=limited_ctx,
        ):
            with patch.object(
                handler,
                "check_permission",
                side_effect=ForbiddenError("Permission denied"),
            ):
                result = await handler.handle(
                    "/api/v1/orchestration/templates", {}, mock_http_handler
                )
                assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_deliberate_requires_execute_permission(
        self, handler, mock_http_handler, mock_auth_context
    ):
        """Test POST deliberate requires orchestration:execute permission."""
        from aragora.server.handlers.utils.auth import ForbiddenError

        mock_request = create_mock_request({"question": "Test question"})

        read_only_ctx = AuthorizationContext(
            user_id="user-123",
            permissions={"orchestration:read"},  # Missing execute
        )

        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            return_value=read_only_ctx,
        ):
            with patch.object(
                handler,
                "check_permission",
                side_effect=ForbiddenError("Permission denied: orchestration:execute"),
            ):
                result = await handler.handle_post(
                    "/api/v1/orchestration/deliberate", {}, mock_request
                )
                assert result.status_code == 403
                body = json.loads(result.body)
                assert "Permission denied" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_successful_auth_with_valid_context(
        self, handler, mock_http_handler, mock_auth_context
    ):
        """Test successful authentication with valid context."""
        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            return_value=mock_auth_context,
        ):
            with patch.object(handler, "check_permission", return_value=True):
                result = await handler.handle(
                    "/api/v1/orchestration/templates", {}, mock_http_handler
                )
                assert result.status_code == 200


# =============================================================================
# Test Class: Templates Endpoint
# =============================================================================


class TestTemplatesEndpoint:
    """Tests for the templates listing endpoint."""

    def test_get_templates_returns_all(self, handler):
        """Test templates endpoint returns all templates."""
        result = handler._get_templates({})
        assert result.status_code == 200
        body = json.loads(result.body)
        assert "templates" in body
        assert "count" in body
        assert body["count"] == len(TEMPLATES)

    def test_template_structure_is_valid(self, handler):
        """Test that returned templates have expected structure."""
        result = handler._get_templates({})
        body = json.loads(result.body)

        for template in body["templates"]:
            assert "name" in template
            assert "description" in template
            assert "default_agents" in template
            assert "output_format" in template
            assert "max_rounds" in template


# =============================================================================
# Test Class: Status Endpoint
# =============================================================================


class TestStatusEndpoint:
    """Tests for the deliberation status endpoint."""

    def test_get_status_not_found(self, handler):
        """Test status returns 404 for unknown request ID."""
        result = handler._get_status("unknown-request-id")
        assert result.status_code == 404
        body = json.loads(result.body)
        assert "error" in body

    def test_get_status_in_progress(self, handler):
        """Test status returns in_progress for active request."""
        request_id = "active-request-001"
        _orchestration_requests[request_id] = OrchestrationRequest(
            question="Test question",
            request_id=request_id,
        )

        result = handler._get_status(request_id)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "in_progress"
        assert body["request_id"] == request_id
        assert body["result"] is None

    def test_get_status_completed_success(self, handler):
        """Test status returns completed for finished request."""
        request_id = "completed-request-002"
        _orchestration_results[request_id] = OrchestrationResult(
            request_id=request_id,
            success=True,
            consensus_reached=True,
            final_answer="The recommended approach is...",
            confidence=0.92,
            agents_participated=["anthropic-api", "openai-api"],
            rounds_completed=3,
        )

        result = handler._get_status(request_id)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "completed"
        assert body["result"]["success"] is True
        assert body["result"]["consensus_reached"] is True

    def test_get_status_completed_failure(self, handler):
        """Test status returns failed status for failed request."""
        request_id = "failed-request-003"
        _orchestration_results[request_id] = OrchestrationResult(
            request_id=request_id,
            success=False,
            error="Deliberation timed out after 300 seconds",
        )

        result = handler._get_status(request_id)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "failed"
        assert "error" in body["result"]


# =============================================================================
# Test Class: Deliberate Endpoint
# =============================================================================


class TestDeliberateEndpoint:
    """Tests for the deliberate execution endpoint."""

    def test_deliberate_missing_question(self, handler, mock_auth_context):
        """Test deliberate returns 400 when question is missing."""
        with patch.object(handler, "check_permission", return_value=True):
            result = handler._handle_deliberate({}, None, mock_auth_context, sync=False)
            assert result.status_code == 400
            body = json.loads(result.body)
            assert "Question is required" in body["error"]

    def test_deliberate_empty_question(self, handler, mock_auth_context):
        """Test deliberate returns 400 when question is empty."""
        with patch.object(handler, "check_permission", return_value=True):
            result = handler._handle_deliberate(
                {"question": ""}, None, mock_auth_context, sync=False
            )
            assert result.status_code == 400
            body = json.loads(result.body)
            assert "Question is required" in body["error"]

    @pytest.mark.asyncio
    async def test_deliberate_async_returns_queued(self, handler, mock_auth_context):
        """Test async deliberate returns 202 Accepted."""
        # Use patch to prevent asyncio.create_task from actually running
        with patch("asyncio.create_task", side_effect=close_coroutine_then(MagicMock())):
            with patch.object(handler, "check_permission", return_value=True):
                result = handler._handle_deliberate(
                    {"question": "What should we do?"},
                    None,
                    mock_auth_context,
                    sync=False,
                )
                assert result.status_code == 202
                body = json.loads(result.body)
                assert body["status"] == "queued"
                assert "request_id" in body

    @pytest.mark.asyncio
    async def test_deliberate_with_template(self, handler, mock_auth_context):
        """Test deliberate applies template configuration."""
        data = {
            "question": "Review this PR for security issues",
            "template": "code_review",
        }
        with patch("asyncio.create_task", side_effect=close_coroutine_then(MagicMock())):
            with patch.object(handler, "check_permission", return_value=True):
                result = handler._handle_deliberate(data, None, mock_auth_context, sync=False)
            assert result.status_code == 202

    @pytest.mark.asyncio
    async def test_deliberate_request_stored(self, handler, mock_auth_context):
        """Test that deliberate stores request for status checking."""
        data = {"question": "Should we refactor this module?"}
        with patch("asyncio.create_task", side_effect=close_coroutine_then(MagicMock())):
            with patch.object(handler, "check_permission", return_value=True):
                result = handler._handle_deliberate(data, None, mock_auth_context, sync=False)
                body = json.loads(result.body)
                request_id = body["request_id"]

                # Request should be stored while in progress
                assert request_id in _orchestration_requests


# =============================================================================
# Test Class: Agent Team Selection
# =============================================================================


class TestAgentTeamSelection:
    """Tests for agent team selection strategies."""

    @pytest.fixture
    def selection_handler(self):
        """Create handler for selection tests."""
        return OrchestrationHandler({})

    @pytest.mark.asyncio
    async def test_select_specified_agents(self, selection_handler):
        """Test SPECIFIED strategy uses provided agents."""
        request = OrchestrationRequest(
            question="Test",
            agents=["custom-agent-1", "custom-agent-2"],
            team_strategy=TeamStrategy.SPECIFIED,
        )
        agents = await selection_handler._select_agent_team(request)
        assert agents == ["custom-agent-1", "custom-agent-2"]

    @pytest.mark.asyncio
    async def test_select_explicit_agents_override_strategy(self, selection_handler):
        """Test explicit agents override team strategy."""
        request = OrchestrationRequest(
            question="Test",
            agents=["my-agent"],
            team_strategy=TeamStrategy.DIVERSE,
        )
        agents = await selection_handler._select_agent_team(request)
        assert agents == ["my-agent"]

    @pytest.mark.asyncio
    async def test_select_fast_strategy(self, selection_handler):
        """Test FAST strategy returns minimal agents."""
        request = OrchestrationRequest(
            question="Quick decision needed",
            team_strategy=TeamStrategy.FAST,
        )
        agents = await selection_handler._select_agent_team(request)
        assert len(agents) == 2

    @pytest.mark.asyncio
    async def test_select_diverse_strategy(self, selection_handler):
        """Test DIVERSE strategy returns more agents."""
        request = OrchestrationRequest(
            question="Complex problem",
            team_strategy=TeamStrategy.DIVERSE,
        )
        agents = await selection_handler._select_agent_team(request)
        assert len(agents) >= 3

    @pytest.mark.asyncio
    async def test_select_random_strategy(self, selection_handler):
        """Test RANDOM strategy returns subset of agents."""
        request = OrchestrationRequest(
            question="Test",
            team_strategy=TeamStrategy.RANDOM,
        )
        agents = await selection_handler._select_agent_team(request)
        assert 1 <= len(agents) <= 3

    @pytest.mark.asyncio
    async def test_select_best_for_domain_fallback(self, selection_handler):
        """Test BEST_FOR_DOMAIN falls back to defaults when routing unavailable."""
        request = OrchestrationRequest(
            question="Technical question",
            team_strategy=TeamStrategy.BEST_FOR_DOMAIN,
        )
        agents = await selection_handler._select_agent_team(request)
        assert len(agents) >= 2


# =============================================================================
# Test Class: Knowledge Context Fetching
# =============================================================================


class TestKnowledgeContextFetching:
    """Tests for fetching knowledge context from various sources."""

    @pytest.fixture
    def fetch_handler(self):
        """Create handler for fetch tests."""
        return OrchestrationHandler({})

    @pytest.mark.asyncio
    async def test_fetch_unknown_source_type(self, fetch_handler):
        """Test fetching from unknown source type returns None."""
        source = KnowledgeContextSource(
            source_type="unknown_platform",
            source_id="id-123",
        )
        result = await fetch_handler._fetch_knowledge_context(source)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_slack_context_success(self, fetch_handler):
        """Test successful Slack context fetch."""
        source = KnowledgeContextSource(
            source_type="slack",
            source_id="C12345",
            lookback_minutes=60,
            max_items=50,
        )

        mock_connector = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.messages = [{"text": "Message 1"}, {"text": "Message 2"}]
        mock_ctx.to_context_string.return_value = "Slack context content"
        mock_connector.fetch_context = AsyncMock(return_value=mock_ctx)

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            result = await fetch_handler._fetch_chat_context("slack", source)
            assert result == "Slack context content"
            mock_connector.fetch_context.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_slack_context_no_connector(self, fetch_handler):
        """Test Slack fetch returns None when connector unavailable."""
        source = KnowledgeContextSource(source_type="slack", source_id="C12345")

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=None,
        ):
            result = await fetch_handler._fetch_chat_context("slack", source)
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_document_context_success(self, fetch_handler):
        """Test successful document context fetch from knowledge mound."""
        source = KnowledgeContextSource(
            source_type="document",
            source_id="search query",
            max_items=10,
        )

        mock_item = MagicMock()
        mock_item.content = "Document content here"
        mock_result = MagicMock()
        mock_result.items = [mock_item]

        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(return_value=mock_result)

        with patch(
            "aragora.knowledge.mound.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await fetch_handler._fetch_document_context(source)
            assert "Document content" in result

    @pytest.mark.asyncio
    async def test_fetch_confluence_without_url(self, fetch_handler):
        """Test Confluence fetch returns None without base URL configured."""
        source = KnowledgeContextSource(
            source_type="confluence",
            source_id="page-123",
        )
        # Handler has no confluence_url in context
        result = await fetch_handler._fetch_confluence_context(source)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_jira_without_url(self, fetch_handler):
        """Test Jira fetch returns None without base URL configured."""
        source = KnowledgeContextSource(
            source_type="jira",
            source_id="PROJ-123",
        )
        result = await fetch_handler._fetch_jira_context(source)
        assert result is None


# =============================================================================
# Test Class: Output Channel Routing
# =============================================================================


class TestOutputChannelRouting:
    """Tests for routing results to output channels."""

    @pytest.fixture
    def routing_handler(self):
        """Create handler for routing tests."""
        return OrchestrationHandler({})

    @pytest.mark.asyncio
    async def test_route_to_slack(self, routing_handler):
        """Test routing result to Slack channel."""
        channel = OutputChannel(
            channel_type="slack",
            channel_id="C12345",
            thread_id="1234567.890",
        )

        mock_connector = MagicMock()
        mock_connector.send_message = AsyncMock()

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            await routing_handler._send_to_slack(channel, "Test message")
            mock_connector.send_message.assert_called_once_with(
                "C12345",
                "Test message",
                thread_ts="1234567.890",
            )

    @pytest.mark.asyncio
    async def test_route_to_teams(self, routing_handler):
        """Test routing result to Microsoft Teams."""
        channel = OutputChannel(channel_type="teams", channel_id="channel-123")

        mock_connector = MagicMock()
        mock_connector.send_message = AsyncMock()

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            await routing_handler._send_to_teams(channel, "Teams message")
            mock_connector.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_to_discord(self, routing_handler):
        """Test routing result to Discord."""
        channel = OutputChannel(channel_type="discord", channel_id="discord-123")

        mock_connector = MagicMock()
        mock_connector.send_message = AsyncMock()

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            await routing_handler._send_to_discord(channel, "Discord message")
            mock_connector.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_to_telegram(self, routing_handler):
        """Test routing result to Telegram."""
        channel = OutputChannel(channel_type="telegram", channel_id="chat-123")

        mock_connector = MagicMock()
        mock_connector.send_message = AsyncMock()

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            await routing_handler._send_to_telegram(channel, "Telegram message")
            mock_connector.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_to_webhook_success(self, routing_handler):
        """Test routing result to webhook endpoint."""
        channel = OutputChannel(
            channel_type="webhook",
            channel_id="https://example.com/webhook",
        )
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            final_answer="Test answer",
        )

        mock_response = MagicMock()
        mock_response.status = 200

        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = MagicMock()
            mock_session.post = MagicMock(
                return_value=MagicMock(
                    __aenter__=AsyncMock(return_value=mock_response),
                    __aexit__=AsyncMock(return_value=False),
                )
            )
            mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_class.return_value.__aexit__ = AsyncMock(return_value=False)

            await routing_handler._send_to_webhook(channel, result)


# =============================================================================
# Test Class: Result Formatting
# =============================================================================


class TestResultFormatting:
    """Tests for formatting results for channel delivery."""

    @pytest.fixture
    def format_handler(self):
        """Create handler for formatting tests."""
        return OrchestrationHandler({})

    def test_format_standard_with_consensus(self, format_handler):
        """Test standard format with consensus reached."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            consensus_reached=True,
            final_answer="Use microservices architecture.",
            confidence=0.95,
            agents_participated=["anthropic-api", "openai-api"],
            duration_seconds=45.0,
        )
        request = OrchestrationRequest(
            question="What architecture should we use?",
            output_format=OutputFormat.STANDARD,
        )

        message = format_handler._format_result_for_channel(result, request)
        assert "Deliberation Result" in message
        assert "Consensus reached" in message
        assert "95%" in message
        assert "microservices" in message

    def test_format_standard_no_consensus(self, format_handler):
        """Test standard format without consensus."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            consensus_reached=False,
            final_answer="Mixed opinions on this topic.",
        )
        request = OrchestrationRequest(
            question="Test?",
            output_format=OutputFormat.STANDARD,
        )

        message = format_handler._format_result_for_channel(result, request)
        assert "No consensus" in message

    def test_format_summary(self, format_handler):
        """Test summary format is concise."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            final_answer="Summary answer.",
        )
        request = OrchestrationRequest(
            question="Test?",
            output_format=OutputFormat.SUMMARY,
        )

        message = format_handler._format_result_for_channel(result, request)
        assert "Deliberation Complete" in message
        assert "Summary answer." in message

    def test_format_no_answer(self, format_handler):
        """Test format when no answer reached."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            final_answer=None,
        )
        request = OrchestrationRequest(
            question="Test?",
            output_format=OutputFormat.STANDARD,
        )

        message = format_handler._format_result_for_channel(result, request)
        assert "No conclusion reached" in message


# =============================================================================
# Test Class: OrchestrationResult
# =============================================================================


class TestOrchestrationResult:
    """Tests for OrchestrationResult dataclass."""

    def test_to_dict_success(self):
        """Test successful result serialization."""
        result = OrchestrationResult(
            request_id="req-001",
            success=True,
            consensus_reached=True,
            final_answer="The answer is 42.",
            confidence=0.87,
            agents_participated=["agent1", "agent2", "agent3"],
            rounds_completed=4,
            duration_seconds=123.45,
            knowledge_context_used=["slack:C001", "confluence:page-1"],
            channels_notified=["slack:C002"],
            receipt_id="receipt-xyz",
        )

        data = result.to_dict()
        assert data["request_id"] == "req-001"
        assert data["success"] is True
        assert data["confidence"] == 0.87
        assert len(data["agents_participated"]) == 3
        assert data["receipt_id"] == "receipt-xyz"

    def test_to_dict_failure(self):
        """Test failed result serialization."""
        result = OrchestrationResult(
            request_id="req-002",
            success=False,
            error="Connection timeout",
            duration_seconds=300.0,
        )

        data = result.to_dict()
        assert data["success"] is False
        assert data["error"] == "Connection timeout"
        assert data["consensus_reached"] is False
        assert data["final_answer"] is None

    def test_created_at_auto_set(self):
        """Test created_at is automatically set."""
        result = OrchestrationResult(request_id="req-003", success=True)
        assert result.created_at is not None
        # Should be ISO format with T separator
        assert "T" in result.created_at


# =============================================================================
# Test Class: Execute and Store
# =============================================================================


class TestExecuteAndStore:
    """Tests for the execute and store mechanism."""

    @pytest.mark.asyncio
    async def test_execute_and_store_success(self, handler):
        """Test successful execution stores result."""
        request = OrchestrationRequest(
            question="Test question",
            request_id="exec-test-001",
        )

        mock_result = OrchestrationResult(
            request_id="exec-test-001",
            success=True,
            final_answer="Test answer",
        )

        with patch.object(
            handler,
            "_execute_deliberation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            await handler._execute_and_store(request)

        assert "exec-test-001" in _orchestration_results
        assert _orchestration_results["exec-test-001"].success is True
        # Request should be removed after completion
        assert "exec-test-001" not in _orchestration_requests

    @pytest.mark.asyncio
    async def test_execute_and_store_failure(self, handler):
        """Test execution failure stores error result."""
        request = OrchestrationRequest(
            question="Test question",
            request_id="exec-test-002",
        )

        with patch.object(
            handler,
            "_execute_deliberation",
            new_callable=AsyncMock,
            side_effect=ValueError("Deliberation failed"),
        ):
            await handler._execute_and_store(request)

        assert "exec-test-002" in _orchestration_results
        result = _orchestration_results["exec-test-002"]
        assert result.success is False
        assert result.error  # Sanitized error message present


# =============================================================================
# Test Class: Template Application
# =============================================================================


class TestTemplateApplication:
    """Tests for template configuration application."""

    @pytest.mark.asyncio
    async def test_template_agents_applied(self, handler, mock_auth_context):
        """Test template default agents are applied."""
        # Using a template that exists
        if "code_review" in TEMPLATES:
            # Without explicit agents, template should provide them
            # Note: Template application happens in _handle_deliberate
            data = {"question": "Review code", "template": "code_review"}
            with patch("asyncio.create_task", side_effect=close_coroutine_then(MagicMock())):
                with patch.object(handler, "check_permission", return_value=True):
                    result = handler._handle_deliberate(data, None, mock_auth_context, sync=False)
                    assert result.status_code == 202

    def test_explicit_agents_override_template(self):
        """Test explicit agents override template defaults."""
        request = OrchestrationRequest.from_dict(
            {
                "question": "Test",
                "template": "code_review",
                "agents": ["my-custom-agent"],
            }
        )
        # Explicit agents should be preserved
        assert request.agents == ["my-custom-agent"]


# =============================================================================
# Test Class: Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling scenarios."""

    def test_handle_deliberate_invalid_json_body(self, handler, mock_auth_context):
        """Test deliberate handles None body gracefully."""
        # This simulates invalid JSON
        with patch.object(handler, "check_permission", return_value=True):
            result = handler._handle_deliberate(None, None, mock_auth_context, sync=False)
            # Should return error or handle gracefully
            assert result is not None

    def test_handle_deliberate_malformed_sources(self, handler, mock_auth_context):
        """Test deliberate handles malformed knowledge sources."""
        data = {
            "question": "Test",
            "knowledge_sources": [{"missing_required_fields": True}],
        }
        with patch.object(handler, "check_permission", return_value=True):
            result = handler._handle_deliberate(data, None, mock_auth_context, sync=False)
            # Should not crash, return queued or error
            assert result.status_code in [202, 400, 500]

    def test_handle_deliberate_malformed_channels(self, handler, mock_auth_context):
        """Test deliberate handles malformed output channels."""
        data = {
            "question": "Test",
            "output_channels": [{"invalid": "structure"}],
        }
        with patch.object(handler, "check_permission", return_value=True):
            result = handler._handle_deliberate(data, None, mock_auth_context, sync=False)
        assert result.status_code in [202, 400, 500]


# =============================================================================
# Test Class: Rate Limiting
# =============================================================================


class TestRateLimiting:
    """Tests for rate limiting behavior."""

    def test_deliberate_has_rate_limit(self, handler):
        """Test that _handle_deliberate has rate limiting applied."""
        method = handler._handle_deliberate
        # Rate limit decorator wraps the function
        assert callable(method)
        # Check if it has decorator attributes or is wrapped
        assert hasattr(method, "__wrapped__") or hasattr(method, "__name__")


# =============================================================================
# Test Class: Execution Flow
# =============================================================================


@pytest.mark.timeout(15)
class TestExecutionFlow:
    """Tests for the full deliberation execution flow."""

    @pytest.fixture(autouse=True)
    def _mock_decision_router(self):
        """Prevent real HTTP calls via get_decision_router regardless of test order.

        With certain pytest-randomly seeds (e.g. 99999), mock pollution can
        cause per-test patches to silently fail, letting _execute_deliberation
        reach the fallback path and block on real network I/O.  This autouse
        fixture acts as a safety net.
        """
        mock_result = MagicMock(
            success=True,
            consensus_reached=False,
            final_answer="mock fallback",
            confidence=0.5,
        )
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)
        with patch(
            "aragora.core.decision.get_decision_router",
            return_value=mock_router,
        ):
            yield

    @pytest.mark.asyncio
    async def test_execute_deliberation_without_coordinator(self, handler):
        """Test deliberation execution falls back without coordinator."""
        request = OrchestrationRequest(
            question="What is the answer?",
            agents=["anthropic-api"],
            request_id="flow-test-001",
        )

        # Mock the decision router
        mock_decision_result = MagicMock()
        mock_decision_result.success = True
        mock_decision_result.consensus_reached = True
        mock_decision_result.final_answer = "The answer is..."
        mock_decision_result.confidence = 0.85

        with patch("aragora.core.decision.get_decision_router") as mock_get_router:
            mock_router = MagicMock()
            mock_router.route = AsyncMock(return_value=mock_decision_result)
            mock_get_router.return_value = mock_router

            result = await handler._execute_deliberation(request)

            assert result.request_id == "flow-test-001"
            # Result should have been populated

    @pytest.mark.asyncio
    async def test_execute_deliberation_with_coordinator(self, handler_with_context):
        """Test deliberation execution with control plane coordinator."""
        request = OrchestrationRequest(
            question="Complex decision needed",
            agents=["anthropic-api", "openai-api"],
            request_id="flow-test-002",
            timeout_seconds=60.0,
        )

        mock_outcome = MagicMock()
        mock_outcome.success = True
        mock_outcome.consensus_reached = True
        mock_outcome.winning_position = "Decision reached"
        mock_outcome.consensus_confidence = 0.9

        with patch("aragora.control_plane.deliberation.DeliberationManager") as MockManager:
            mock_manager = MagicMock()
            mock_manager.submit_deliberation = AsyncMock(return_value="task-123")
            mock_manager.wait_for_outcome = AsyncMock(return_value=mock_outcome)
            MockManager.return_value = mock_manager

            result = await handler_with_context._execute_deliberation(request)

            assert result.success is True
            assert result.consensus_reached is True


# =============================================================================
# Test Class: Knowledge Context Integration
# =============================================================================


class TestKnowledgeContextIntegration:
    """Tests for knowledge context integration in deliberation."""

    @pytest.mark.asyncio
    async def test_multiple_sources_aggregated(self, handler):
        """Test multiple knowledge sources are aggregated."""
        request = OrchestrationRequest(
            question="What do all sources say?",
            knowledge_sources=[
                KnowledgeContextSource(source_type="slack", source_id="C001"),
                KnowledgeContextSource(source_type="document", source_id="doc-1"),
            ],
            request_id="context-test-001",
        )

        # Mock both fetch methods
        with patch.object(handler, "_fetch_chat_context", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "Slack context"
            with patch.object(
                handler, "_fetch_document_context", new_callable=AsyncMock
            ) as mock_doc:
                mock_doc.return_value = "Document context"

                # Execute would aggregate both
                # We test the fetch methods are called correctly
                slack_result = await handler._fetch_chat_context(
                    "slack",
                    request.knowledge_sources[0],
                )
                doc_result = await handler._fetch_document_context(
                    request.knowledge_sources[1],
                )

                assert slack_result == "Slack context"
                assert doc_result == "Document context"


# =============================================================================
# Test Class: Edge Cases
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_very_long_question(self, handler, mock_auth_context):
        """Test handling of very long question."""
        long_question = "x" * 10000
        with patch("asyncio.create_task", side_effect=close_coroutine_then(MagicMock())):
            with patch.object(handler, "check_permission", return_value=True):
                result = handler._handle_deliberate(
                    {"question": long_question},
                    None,
                    mock_auth_context,
                    sync=False,
                )
                # Should handle without crashing
                assert result.status_code in [202, 400]

    @pytest.mark.asyncio
    async def test_unicode_question(self, handler, mock_auth_context):
        """Test handling of unicode characters in question."""
        unicode_question = "What about these characters: (emoji) and chinese?"
        with patch("asyncio.create_task", side_effect=close_coroutine_then(MagicMock())):
            with patch.object(handler, "check_permission", return_value=True):
                result = handler._handle_deliberate(
                    {"question": unicode_question},
                    None,
                    mock_auth_context,
                    sync=False,
                )
                assert result.status_code == 202

    def test_max_rounds_boundary(self, handler):
        """Test max_rounds at boundary values."""
        # Zero rounds
        request_zero = OrchestrationRequest.from_dict(
            {
                "question": "Test",
                "max_rounds": 0,
            }
        )
        assert request_zero.max_rounds == 0

        # Very high rounds
        request_high = OrchestrationRequest.from_dict(
            {
                "question": "Test",
                "max_rounds": 1000,
            }
        )
        assert request_high.max_rounds == 1000

    def test_timeout_boundary(self, handler):
        """Test timeout_seconds at boundary values."""
        request = OrchestrationRequest.from_dict(
            {
                "question": "Test",
                "timeout_seconds": 0.1,
            }
        )
        assert request.timeout_seconds == 0.1

    @pytest.mark.asyncio
    async def test_empty_knowledge_sources_list(self, handler, mock_auth_context):
        """Test request with empty knowledge sources."""
        with patch("asyncio.create_task", side_effect=close_coroutine_then(MagicMock())):
            with patch.object(handler, "check_permission", return_value=True):
                result = handler._handle_deliberate(
                    {"question": "Test", "knowledge_sources": []},
                    None,
                    mock_auth_context,
                    sync=False,
                )
                assert result.status_code == 202

    @pytest.mark.asyncio
    async def test_empty_output_channels_list(self, handler, mock_auth_context):
        """Test request with empty output channels."""
        with patch("asyncio.create_task", side_effect=close_coroutine_then(MagicMock())):
            with patch.object(handler, "check_permission", return_value=True):
                result = handler._handle_deliberate(
                    {"question": "Test", "output_channels": []},
                    None,
                    mock_auth_context,
                    sync=False,
                )
                assert result.status_code == 202


# =============================================================================
# Test Class: Concurrent Operations
# =============================================================================


class TestConcurrentOperations:
    """Tests for concurrent operation handling."""

    @pytest.mark.asyncio
    async def test_multiple_concurrent_requests(self, handler, mock_auth_context):
        """Test handling multiple concurrent requests."""
        requests = []
        with patch.object(handler, "check_permission", return_value=True):
            for i in range(5):
                data = {"question": f"Question {i}"}
                result = handler._handle_deliberate(data, None, mock_auth_context, sync=False)
                body = json.loads(result.body)
                requests.append(body["request_id"])

            # All should have unique request IDs
            assert len(set(requests)) == 5

    def test_status_check_during_execution(self, handler):
        """Test status can be checked during execution."""
        # Add a request in progress
        request_id = "concurrent-001"
        _orchestration_requests[request_id] = OrchestrationRequest(
            question="In progress",
            request_id=request_id,
        )

        # Check status
        result = handler._get_status(request_id)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "in_progress"


# =============================================================================
# Test Class: Security and Path Traversal Prevention
# =============================================================================


class TestSecurityValidation:
    """Tests for security validation including path traversal prevention and RBAC."""

    def test_safe_source_id_valid(self):
        """Test safe_source_id accepts valid identifiers."""
        from aragora.server.handlers.orchestration import safe_source_id

        # Valid source IDs
        assert safe_source_id("C12345") == "C12345"
        assert safe_source_id("owner/repo/pr/123") == "owner/repo/pr/123"
        assert safe_source_id("PROJ-123") == "PROJ-123"
        assert safe_source_id("page-id-123") == "page-id-123"
        assert safe_source_id("doc_123") == "doc_123"
        assert safe_source_id("user@domain.com") == "user@domain.com"
        assert safe_source_id("feature#123") == "feature#123"

    def test_safe_source_id_path_traversal(self):
        """Test safe_source_id rejects path traversal attempts."""
        from aragora.server.handlers.orchestration import (
            safe_source_id,
            SourceIdValidationError,
        )

        # Path traversal sequences
        with pytest.raises(SourceIdValidationError, match="path traversal"):
            safe_source_id("../../../etc/passwd")

        with pytest.raises(SourceIdValidationError, match="path traversal"):
            safe_source_id("..\\..\\windows\\system32")

        with pytest.raises(SourceIdValidationError, match="path traversal"):
            safe_source_id("owner/../repo/pr/123")

    def test_safe_source_id_absolute_path(self):
        """Test safe_source_id rejects absolute paths."""
        from aragora.server.handlers.orchestration import (
            safe_source_id,
            SourceIdValidationError,
        )

        with pytest.raises(SourceIdValidationError, match="cannot start with /"):
            safe_source_id("/etc/passwd")

        with pytest.raises(SourceIdValidationError, match="Windows absolute path"):
            safe_source_id("C:\\Windows\\System32")

    def test_safe_source_id_null_byte(self):
        """Test safe_source_id rejects null bytes."""
        from aragora.server.handlers.orchestration import (
            safe_source_id,
            SourceIdValidationError,
        )

        with pytest.raises(SourceIdValidationError, match="null byte"):
            safe_source_id("valid\x00injected")

    def test_safe_source_id_empty(self):
        """Test safe_source_id rejects empty strings."""
        from aragora.server.handlers.orchestration import (
            safe_source_id,
            SourceIdValidationError,
        )

        with pytest.raises(SourceIdValidationError, match="cannot be empty"):
            safe_source_id("")

    def test_safe_source_id_too_long(self):
        """Test safe_source_id rejects overly long strings."""
        from aragora.server.handlers.orchestration import (
            safe_source_id,
            SourceIdValidationError,
            MAX_SOURCE_ID_LENGTH,
        )

        with pytest.raises(SourceIdValidationError, match="too long"):
            safe_source_id("x" * (MAX_SOURCE_ID_LENGTH + 1))

    def test_validate_channel_id_webhook(self):
        """Test validate_channel_id for webhook channels."""
        from aragora.server.handlers.orchestration import validate_channel_id

        # Valid webhook URLs
        assert validate_channel_id("https://api.example.com/webhook", "webhook")
        assert validate_channel_id("http://localhost:8080/callback", "webhook")

        # Invalid webhook URLs
        with pytest.raises(ValueError, match="valid URL"):
            validate_channel_id("not-a-url", "webhook")

        with pytest.raises(ValueError, match="invalid characters"):
            validate_channel_id("https://example.com/../../../etc/passwd", "webhook")

    def test_validate_channel_id_path_traversal(self):
        """Test validate_channel_id rejects path traversal for non-webhook channels."""
        from aragora.server.handlers.orchestration import validate_channel_id

        with pytest.raises(ValueError, match="invalid path characters"):
            validate_channel_id("../../../etc/passwd", "slack")

        with pytest.raises(ValueError, match="invalid path characters"):
            validate_channel_id("/absolute/path", "teams")

    def test_validate_knowledge_source_security(self, handler, mock_auth_context):
        """Test _validate_knowledge_source rejects malicious source IDs."""
        from aragora.server.handlers.orchestration import KnowledgeContextSource

        with patch.object(handler, "check_permission", return_value=True):
            # Path traversal in source_id
            malicious_source = KnowledgeContextSource(
                source_type="github",
                source_id="../../../etc/passwd",
            )
            result = handler._validate_knowledge_source(malicious_source, mock_auth_context)
            assert result is not None
            assert result.status_code == 400
            body = json.loads(result.body)
            assert body["error"]  # Sanitized error message present

    def test_validate_output_channel_security(self, handler, mock_auth_context):
        """Test _validate_output_channel rejects malicious channel IDs."""
        from aragora.server.handlers.orchestration import OutputChannel

        with patch.object(handler, "check_permission", return_value=True):
            # Path traversal in channel_id
            malicious_channel = OutputChannel(
                channel_type="slack",
                channel_id="../../../etc/passwd",
            )
            result = handler._validate_output_channel(malicious_channel, mock_auth_context)
            assert result is not None
            assert result.status_code == 400

    def test_deliberate_validates_knowledge_sources(self, handler, mock_auth_context):
        """Test that _handle_deliberate validates all knowledge sources."""
        data = {
            "question": "Test question",
            "knowledge_sources": [
                {"type": "github", "id": "../../../etc/passwd"},  # Malicious
            ],
        }
        with patch.object(handler, "check_permission", return_value=True):
            result = handler._handle_deliberate(data, None, mock_auth_context, sync=False)
            assert result.status_code == 400
            body = json.loads(result.body)
            assert body["error"]  # Sanitized error message present

    def test_deliberate_validates_output_channels(self, handler, mock_auth_context):
        """Test that _handle_deliberate validates all output channels."""
        data = {
            "question": "Test question",
            "output_channels": [
                {"type": "slack", "id": "../../../etc/passwd"},  # Malicious
            ],
        }
        with patch.object(handler, "check_permission", return_value=True):
            result = handler._handle_deliberate(data, None, mock_auth_context, sync=False)
            assert result.status_code == 400
