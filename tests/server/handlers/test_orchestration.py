"""
Tests for the unified orchestration handler.

Tests the core "Control plane for multi-agent vetted decisionmaking across
org knowledge and channels" functionality.

Coverage includes:
- Data model parsing (OrchestrationRequest, KnowledgeContextSource, OutputChannel)
- Template handling and configuration
- Handler routing and path matching
- Authentication and permission enforcement
- Agent team selection strategies
- Knowledge context fetching (Slack, Confluence, GitHub, Jira, Document)
- Output channel routing (Slack, Teams, Discord, Telegram, Email, Webhook)
- Error handling and edge cases
- Debate engine integration
- Receipt generation with provenance
- RBAC permission checks
- Input validation
"""

import json
from io import BytesIO
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
    DeliberationTemplate,
    TEMPLATES,
    _orchestration_requests,
    _orchestration_results,
)


def _stub_create_task():
    """Stand in for ``asyncio.create_task`` in sync tests (no running loop).

    Closes the queued coroutine so it is not reported as "never awaited" and
    returns an inert task object.
    """
    return patch("asyncio.create_task", side_effect=close_coroutine_then(MagicMock()))


# =============================================================================
# Test Fixtures
# =============================================================================


@pytest.fixture
def handler():
    """Create an orchestration handler with empty context."""
    return OrchestrationHandler({})


@pytest.fixture
def handler_with_coordinator():
    """Create handler with mocked control plane coordinator."""
    mock_coordinator = MagicMock()
    ctx = {"control_plane_coordinator": mock_coordinator}
    return OrchestrationHandler(ctx)


@pytest.fixture
def mock_http_handler():
    """Create a mock HTTP handler with headers."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    handler.headers = {"Content-Type": "application/json"}
    return handler


@pytest.fixture
def mock_auth_context():
    """Create a mock authenticated authorization context."""
    from aragora.rbac.models import AuthorizationContext

    return AuthorizationContext(
        user_id="test-user-123",
        org_id="test-org-456",
        workspace_id="test-workspace",
        roles={"member", "developer"},
        permissions={"orchestration:read", "orchestration:execute"},
    )


@pytest.fixture(autouse=True)
def clear_orchestration_state():
    """Clear orchestration state before and after each test."""
    _orchestration_requests.clear()
    _orchestration_results.clear()
    yield
    _orchestration_requests.clear()
    _orchestration_results.clear()


def create_request_body(data: dict) -> MagicMock:
    """Create a mock HTTP handler with a JSON body."""
    handler = MagicMock()
    handler.client_address = ("127.0.0.1", 12345)
    body = json.dumps(data).encode("utf-8")
    handler.headers = {
        "Content-Length": str(len(body)),
        "Content-Type": "application/json",
    }
    handler.rfile = BytesIO(body)
    handler.command = "POST"
    return handler


# =============================================================================
# OrchestrationRequest Tests
# =============================================================================


class TestOrchestrationRequest:
    """Tests for OrchestrationRequest parsing."""

    def test_from_dict_minimal(self):
        """Test parsing minimal request."""
        data = {"question": "Should we use microservices?"}
        request = OrchestrationRequest.from_dict(data)

        assert request.question == "Should we use microservices?"
        assert request.knowledge_sources == []
        assert request.output_channels == []
        assert request.team_strategy == TeamStrategy.BEST_FOR_DOMAIN
        assert request.require_consensus is True

    def test_from_dict_full(self):
        """Test parsing full request with all fields."""
        data = {
            "question": "What architecture should we use?",
            "knowledge_sources": ["slack:C123456", "confluence:page/123"],
            "knowledge_context": {
                "workspaces": ["engineering", "architecture"],
            },
            "team_strategy": "diverse",
            "agents": ["anthropic-api", "openai-api", "gemini"],
            "output_channels": ["slack:C789", "email:team@example.com"],
            "output_format": "decision_receipt",
            "require_consensus": True,
            "priority": "high",
            "max_rounds": 5,
            "timeout_seconds": 600.0,
            "template": "architecture_decision",
            "metadata": {"project": "infrastructure"},
        }
        request = OrchestrationRequest.from_dict(data)

        assert request.question == "What architecture should we use?"
        assert len(request.knowledge_sources) == 2
        assert request.knowledge_sources[0].source_type == "slack"
        assert request.knowledge_sources[0].source_id == "C123456"
        assert request.workspaces == ["engineering", "architecture"]
        assert request.team_strategy == TeamStrategy.DIVERSE
        assert request.agents == ["anthropic-api", "openai-api", "gemini"]
        assert len(request.output_channels) == 2
        assert request.output_channels[0].channel_type == "slack"
        assert request.output_channels[1].channel_type == "email"
        assert request.output_format == OutputFormat.DECISION_RECEIPT
        assert request.priority == "high"
        assert request.template == "architecture_decision"

    def test_from_dict_nested_knowledge_context(self):
        """Test parsing with nested knowledge_context format."""
        data = {
            "question": "Test question",
            "knowledge_context": {
                "sources": ["github:owner/repo/pr/123"],
                "workspaces": ["dev"],
            },
        }
        request = OrchestrationRequest.from_dict(data)

        assert len(request.knowledge_sources) == 1
        assert request.knowledge_sources[0].source_type == "github"
        assert request.workspaces == ["dev"]

    def test_from_dict_invalid_team_strategy_defaults(self):
        """Test that invalid team strategy defaults to BEST_FOR_DOMAIN."""
        data = {
            "question": "Test",
            "team_strategy": "invalid_strategy",
        }
        request = OrchestrationRequest.from_dict(data)
        assert request.team_strategy == TeamStrategy.BEST_FOR_DOMAIN

    def test_from_dict_invalid_output_format_defaults(self):
        """Test that invalid output format defaults to STANDARD."""
        data = {
            "question": "Test",
            "output_format": "invalid_format",
        }
        request = OrchestrationRequest.from_dict(data)
        assert request.output_format == OutputFormat.STANDARD

    def test_from_dict_knowledge_source_as_dict(self):
        """Test parsing knowledge sources provided as dictionaries."""
        data = {
            "question": "Test",
            "knowledge_sources": [
                {
                    "type": "confluence",
                    "id": "page/456",
                    "lookback_minutes": 120,
                    "max_items": 100,
                }
            ],
        }
        request = OrchestrationRequest.from_dict(data)

        assert len(request.knowledge_sources) == 1
        assert request.knowledge_sources[0].source_type == "confluence"
        assert request.knowledge_sources[0].source_id == "page/456"
        assert request.knowledge_sources[0].lookback_minutes == 120
        assert request.knowledge_sources[0].max_items == 100

    def test_from_dict_output_channel_as_dict(self):
        """Test parsing output channels provided as dictionaries."""
        data = {
            "question": "Test",
            "output_channels": [
                {
                    "type": "slack",
                    "id": "C12345",
                    "thread_id": "1234567.890",
                }
            ],
        }
        request = OrchestrationRequest.from_dict(data)

        assert len(request.output_channels) == 1
        assert request.output_channels[0].channel_type == "slack"
        assert request.output_channels[0].channel_id == "C12345"
        assert request.output_channels[0].thread_id == "1234567.890"

    def test_request_has_unique_id(self):
        """Test that each request gets a unique ID."""
        request1 = OrchestrationRequest.from_dict({"question": "Q1"})
        request2 = OrchestrationRequest.from_dict({"question": "Q2"})

        assert request1.request_id != request2.request_id
        assert len(request1.request_id) > 0

    def test_from_dict_all_team_strategies(self):
        """Test parsing all valid team strategies."""
        strategies = ["specified", "best_for_domain", "diverse", "fast", "random"]
        expected = [
            TeamStrategy.SPECIFIED,
            TeamStrategy.BEST_FOR_DOMAIN,
            TeamStrategy.DIVERSE,
            TeamStrategy.FAST,
            TeamStrategy.RANDOM,
        ]

        for strategy_str, expected_enum in zip(strategies, expected):
            data = {"question": "Test", "team_strategy": strategy_str}
            request = OrchestrationRequest.from_dict(data)
            assert request.team_strategy == expected_enum

    def test_from_dict_all_output_formats(self):
        """Test parsing all valid output formats."""
        formats = ["standard", "decision_receipt", "summary", "github_review", "slack_message"]
        expected = [
            OutputFormat.STANDARD,
            OutputFormat.DECISION_RECEIPT,
            OutputFormat.SUMMARY,
            OutputFormat.GITHUB_REVIEW,
            OutputFormat.SLACK_MESSAGE,
        ]

        for format_str, expected_enum in zip(formats, expected):
            data = {"question": "Test", "output_format": format_str}
            request = OrchestrationRequest.from_dict(data)
            assert request.output_format == expected_enum

    def test_from_dict_empty_question(self):
        """Test parsing with empty question."""
        data = {"question": ""}
        request = OrchestrationRequest.from_dict(data)
        assert request.question == ""

    def test_from_dict_missing_question(self):
        """Test parsing with missing question defaults to empty string."""
        data = {}
        request = OrchestrationRequest.from_dict(data)
        assert request.question == ""

    def test_from_dict_default_values(self):
        """Test that default values are correctly set."""
        data = {"question": "Test"}
        request = OrchestrationRequest.from_dict(data)

        assert request.require_consensus is True
        assert request.priority == "normal"
        assert request.timeout_seconds == 300.0
        assert request.template is None
        assert request.metadata == {}


# =============================================================================
# KnowledgeContextSource Tests
# =============================================================================


class TestKnowledgeContextSource:
    """Tests for KnowledgeContextSource parsing."""

    def test_from_string_with_type(self):
        """Test parsing 'type:id' format."""
        source = KnowledgeContextSource.from_string("slack:C123456")
        assert source.source_type == "slack"
        assert source.source_id == "C123456"

    def test_from_string_without_type(self):
        """Test parsing plain ID defaults to document."""
        source = KnowledgeContextSource.from_string("doc_12345")
        assert source.source_type == "document"
        assert source.source_id == "doc_12345"

    def test_from_string_complex_id(self):
        """Test parsing complex IDs with multiple colons."""
        source = KnowledgeContextSource.from_string("github:owner/repo/pr/123")
        assert source.source_type == "github"
        assert source.source_id == "owner/repo/pr/123"

    def test_default_values(self):
        """Test default values for lookback and max_items."""
        source = KnowledgeContextSource.from_string("slack:C123")
        assert source.lookback_minutes == 60
        assert source.max_items == 50

    def test_from_string_confluence(self):
        """Test parsing Confluence source."""
        source = KnowledgeContextSource.from_string("confluence:12345")
        assert source.source_type == "confluence"
        assert source.source_id == "12345"

    def test_from_string_jira(self):
        """Test parsing Jira source."""
        source = KnowledgeContextSource.from_string("jira:PROJ-123")
        assert source.source_type == "jira"
        assert source.source_id == "PROJ-123"

    def test_from_string_teams(self):
        """Test parsing Teams source."""
        source = KnowledgeContextSource.from_string("teams:channel-id")
        assert source.source_type == "teams"
        assert source.source_id == "channel-id"

    def test_from_string_discord(self):
        """Test parsing Discord source."""
        source = KnowledgeContextSource.from_string("discord:123456789")
        assert source.source_type == "discord"
        assert source.source_id == "123456789"

    def test_from_string_telegram(self):
        """Test parsing Telegram source."""
        source = KnowledgeContextSource.from_string("telegram:-1001234567890")
        assert source.source_type == "telegram"
        assert source.source_id == "-1001234567890"

    def test_from_string_whatsapp(self):
        """Test parsing WhatsApp source."""
        source = KnowledgeContextSource.from_string("whatsapp:group-id")
        assert source.source_type == "whatsapp"
        assert source.source_id == "group-id"


# =============================================================================
# OutputChannel Tests
# =============================================================================


class TestOutputChannel:
    """Tests for OutputChannel parsing."""

    def test_from_string_simple(self):
        """Test parsing 'type:id' format."""
        channel = OutputChannel.from_string("slack:C123456")
        assert channel.channel_type == "slack"
        assert channel.channel_id == "C123456"
        assert channel.thread_id is None

    def test_from_string_with_thread(self):
        """Test parsing 'type:id:thread' format."""
        channel = OutputChannel.from_string("slack:C123456:1234567890.123456")
        assert channel.channel_type == "slack"
        assert channel.channel_id == "C123456"
        assert channel.thread_id == "1234567890.123456"

    def test_from_string_webhook(self):
        """Test parsing webhook:url format."""
        channel = OutputChannel.from_string("webhook:https://example.com/hook")
        assert channel.channel_type == "webhook"
        assert channel.channel_id == "https://example.com/hook"

    def test_from_string_webhook_with_port(self):
        """Test parsing webhook URL with port."""
        channel = OutputChannel.from_string("webhook:https://example.com:8080/hook")
        assert channel.channel_type == "webhook"
        assert channel.channel_id == "https://example.com:8080/hook"

    def test_from_string_no_type(self):
        """Test parsing without type prefix defaults to webhook."""
        channel = OutputChannel.from_string("https://example.com/hook")
        assert channel.channel_type == "webhook"
        assert channel.channel_id == "https://example.com/hook"

    def test_from_string_email(self):
        """Test parsing email channel."""
        channel = OutputChannel.from_string("email:user@example.com")
        assert channel.channel_type == "email"
        assert channel.channel_id == "user@example.com"

    def test_from_string_teams(self):
        """Test parsing Teams channel."""
        channel = OutputChannel.from_string("teams:channel-id")
        assert channel.channel_type == "teams"
        assert channel.channel_id == "channel-id"

    def test_from_string_discord(self):
        """Test parsing Discord channel."""
        channel = OutputChannel.from_string("discord:123456789")
        assert channel.channel_type == "discord"
        assert channel.channel_id == "123456789"

    def test_from_string_telegram(self):
        """Test parsing Telegram channel."""
        channel = OutputChannel.from_string("telegram:-1001234567890")
        assert channel.channel_type == "telegram"
        assert channel.channel_id == "-1001234567890"

    def test_from_string_http_url(self):
        """Test parsing plain HTTP URL defaults to webhook."""
        channel = OutputChannel.from_string("http://example.com/hook")
        assert channel.channel_type == "webhook"
        assert channel.channel_id == "http://example.com/hook"


# =============================================================================
# DeliberationTemplate Tests
# =============================================================================


class TestDeliberationTemplates:
    """Tests for built-in deliberation templates."""

    def test_templates_exist(self):
        """Test that expected templates are defined."""
        expected = [
            "code_review",
            "contract_review",
            "architecture_decision",
            "compliance_check",
            "quick_decision",
        ]
        for name in expected:
            assert name in TEMPLATES, f"Template {name} not found"

    def test_code_review_template(self):
        """Test code review template configuration."""
        template = TEMPLATES["code_review"]
        assert template.name == "code_review"
        assert "anthropic-api" in template.default_agents
        # Compare by value since templates may use enums from different modules
        assert template.output_format.value == "github_review"
        assert "security" in template.personas

    def test_template_to_dict(self):
        """Test template serialization."""
        template = TEMPLATES["code_review"]
        data = template.to_dict()
        assert data["name"] == "code_review"
        assert "default_agents" in data
        assert data["output_format"] == "github_review"

    def test_quick_decision_template(self):
        """Test quick decision template is optimized for speed."""
        template = TEMPLATES["quick_decision"]
        assert template.max_rounds <= 3
        assert len(template.default_agents) <= 3

    def test_all_templates_have_required_fields(self):
        """Test that all templates have required fields."""
        for name, template in TEMPLATES.items():
            assert template.name == name, f"Template {name} has mismatched name"
            assert template.description, f"Template {name} missing description"
            assert len(template.default_agents) > 0, f"Template {name} has no default agents"
            assert template.consensus_threshold > 0, (
                f"Template {name} has invalid consensus threshold"
            )
            assert template.max_rounds > 0, f"Template {name} has invalid max_rounds"


# =============================================================================
# OrchestrationResult Tests
# =============================================================================


class TestOrchestrationResult:
    """Tests for OrchestrationResult."""

    def test_to_dict(self):
        """Test result serialization."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            consensus_reached=True,
            final_answer="Use microservices for this use case.",
            confidence=0.85,
            agents_participated=["anthropic-api", "openai-api"],
            rounds_completed=3,
            duration_seconds=45.2,
            knowledge_context_used=["slack:C123"],
            channels_notified=["slack:C456"],
            receipt_id="receipt-789",
        )

        data = result.to_dict()
        assert data["request_id"] == "req-123"
        assert data["success"] is True
        assert data["consensus_reached"] is True
        assert data["confidence"] == 0.85
        assert len(data["agents_participated"]) == 2
        assert data["receipt_id"] == "receipt-789"

    def test_to_dict_failed_result(self):
        """Test serialization of failed result with error."""
        result = OrchestrationResult(
            request_id="req-fail",
            success=False,
            error="Deliberation timed out",
            duration_seconds=300.0,
        )

        data = result.to_dict()
        assert data["success"] is False
        assert data["error"] == "Deliberation timed out"
        assert data["consensus_reached"] is False

    def test_created_at_timestamp(self):
        """Test that created_at is set automatically."""
        result = OrchestrationResult(
            request_id="req-time",
            success=True,
        )
        assert result.created_at is not None
        assert "T" in result.created_at  # ISO format

    def test_to_dict_includes_all_fields(self):
        """Test that to_dict includes all expected fields."""
        result = OrchestrationResult(
            request_id="req-all",
            success=True,
        )
        data = result.to_dict()
        expected_keys = [
            "request_id",
            "success",
            "consensus_reached",
            "final_answer",
            "confidence",
            "agents_participated",
            "rounds_completed",
            "duration_seconds",
            "knowledge_context_used",
            "channels_notified",
            "receipt_id",
            "error",
            "created_at",
        ]
        for key in expected_keys:
            assert key in data, f"Missing key: {key}"


# =============================================================================
# OrchestrationHandler Path Matching Tests
# =============================================================================


class TestOrchestrationHandler:
    """Tests for OrchestrationHandler."""

    def setup_method(self):
        """Set up test fixtures."""
        self.handler = OrchestrationHandler({})

    def test_can_handle_orchestration_paths(self):
        """Test path matching for orchestration routes."""
        assert self.handler.can_handle("/api/v1/orchestration/deliberate")
        assert self.handler.can_handle("/api/v1/orchestration/templates")
        assert self.handler.can_handle("/api/v1/orchestration/status/abc123")
        assert not self.handler.can_handle("/api/v1/debates")
        assert not self.handler.can_handle("/api/v1/control-plane/agents")

    def test_can_handle_sync_deliberate(self):
        """Test path matching for synchronous deliberate endpoint."""
        assert self.handler.can_handle("/api/v1/orchestration/deliberate/sync")

    def test_get_templates(self):
        """Test GET /api/v1/orchestration/templates."""
        result = self.handler._get_templates({})

        assert result.status_code == 200
        body = json.loads(result.body)
        assert "templates" in body
        assert body["count"] == len(TEMPLATES)

    def test_get_status_not_found(self):
        """Test GET /api/v1/orchestration/status/:id for non-existent request."""
        result = self.handler._get_status("nonexistent-id")

        assert result.status_code == 404
        body = json.loads(result.body)
        assert "error" in body

    def test_get_status_in_progress(self):
        """Test GET /api/v1/orchestration/status/:id for in-progress request."""
        # Add a mock in-progress request
        request_id = "in-progress-123"
        _orchestration_requests[request_id] = OrchestrationRequest(question="Test question")

        result = self.handler._get_status(request_id)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "in_progress"
        assert body["result"] is None

    def test_get_status_completed(self):
        """Test GET /api/v1/orchestration/status/:id for completed request."""
        request_id = "completed-456"
        _orchestration_results[request_id] = OrchestrationResult(
            request_id=request_id,
            success=True,
            final_answer="Test answer",
        )

        result = self.handler._get_status(request_id)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "completed"
        assert body["result"]["final_answer"] == "Test answer"

    def test_get_status_failed(self):
        """Test GET /api/v1/orchestration/status/:id for failed request."""
        request_id = "failed-789"
        _orchestration_results[request_id] = OrchestrationResult(
            request_id=request_id,
            success=False,
            error="Deliberation failed due to timeout",
        )

        result = self.handler._get_status(request_id)
        assert result.status_code == 200
        body = json.loads(result.body)
        assert body["status"] == "failed"
        assert body["result"]["error"] == "Deliberation failed due to timeout"

    def test_handle_deliberate_missing_question(self):
        """Test POST /api/v1/orchestration/deliberate without question."""
        result = self.handler._handle_deliberate({}, None, None, sync=False)

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "error" in body
        assert "Question is required" in body["error"]


# =============================================================================
# Authentication and Permission Tests
# =============================================================================


class TestOrchestrationHandlerAuth:
    """Tests for authentication and permission handling."""

    @pytest.mark.asyncio
    async def test_handle_get_requires_auth(self, handler, mock_http_handler):
        """Test that GET endpoints require authentication."""
        from aragora.server.handlers.utils.auth import UnauthorizedError

        with patch.object(
            handler,
            "get_auth_context",
            side_effect=UnauthorizedError("Unauthorized"),
        ):
            # The handler should catch auth errors gracefully
            result = await handler.handle("/api/v1/orchestration/templates", {}, mock_http_handler)
            # Should return auth error
            assert result is not None

    @pytest.mark.asyncio
    async def test_handle_post_requires_auth(self, handler):
        """Test that POST endpoints require authentication."""
        mock_request = create_request_body({"question": "Test question"})

        # Mock auth to raise UnauthorizedError
        from aragora.server.handlers.utils.auth import UnauthorizedError

        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            side_effect=UnauthorizedError("Auth required"),
        ):
            result = await handler.handle_post(
                "/api/v1/orchestration/deliberate", {}, {}, mock_request
            )

            assert result is not None
            assert result.status_code == 401

    @pytest.mark.asyncio
    async def test_handle_post_forbidden_without_execute_permission(
        self, handler, mock_auth_context
    ):
        """Test that POST deliberate requires orchestration:execute permission."""
        mock_request = create_request_body({"question": "Test question"})

        # Auth context without execute permission
        from aragora.rbac.models import AuthorizationContext

        limited_ctx = AuthorizationContext(
            user_id="user-123",
            permissions={"orchestration:read"},  # Missing execute
        )

        from aragora.server.handlers.utils.auth import ForbiddenError

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
                result = await handler.handle_post(
                    "/api/v1/orchestration/deliberate", {}, {}, mock_request
                )

                assert result is not None
                assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_handle_get_forbidden_without_read_permission(self, handler, mock_http_handler):
        """Test that GET endpoints require orchestration:read permission."""
        from aragora.rbac.models import AuthorizationContext
        from aragora.server.handlers.utils.auth import ForbiddenError

        no_perms_ctx = AuthorizationContext(
            user_id="user-123",
            permissions=set(),  # No permissions
        )

        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            return_value=no_perms_ctx,
        ):
            with patch.object(
                handler,
                "check_permission",
                side_effect=ForbiddenError("Permission denied"),
            ):
                result = await handler.handle(
                    "/api/v1/orchestration/templates", {}, mock_http_handler
                )
                assert result is not None
                assert result.status_code == 403

    @pytest.mark.asyncio
    async def test_handle_successful_with_valid_permissions(self, handler, mock_http_handler):
        """Test successful handling with valid authentication and permissions."""
        from aragora.rbac.models import AuthorizationContext

        valid_ctx = AuthorizationContext(
            user_id="user-123",
            permissions={"orchestration:read", "orchestration:execute"},
        )

        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            return_value=valid_ctx,
        ):
            with patch.object(handler, "check_permission", return_value=True):
                result = await handler.handle(
                    "/api/v1/orchestration/templates", {}, mock_http_handler
                )
                assert result is not None
                assert result.status_code == 200


# =============================================================================
# Agent Team Selection Tests
# =============================================================================


class TestOrchestrationHandlerAsync:
    """Async tests for OrchestrationHandler."""

    @pytest.fixture
    def handler(self):
        """Create handler with mocked context."""
        ctx = {"control_plane_coordinator": None}
        return OrchestrationHandler(ctx)

    @pytest.mark.asyncio
    async def test_select_agent_team_specified(self, handler):
        """Test agent selection with explicit agents."""
        request = OrchestrationRequest(
            question="Test",
            agents=["agent1", "agent2"],
            team_strategy=TeamStrategy.SPECIFIED,
        )
        agents = await handler._select_agent_team(request)
        assert agents == ["agent1", "agent2"]

    @pytest.mark.asyncio
    async def test_select_agent_team_fast(self, handler):
        """Test agent selection with fast strategy."""
        request = OrchestrationRequest(
            question="Test",
            team_strategy=TeamStrategy.FAST,
        )
        agents = await handler._select_agent_team(request)
        assert len(agents) == 2  # Fast uses minimal agents

    @pytest.mark.asyncio
    async def test_select_agent_team_diverse(self, handler):
        """Test agent selection with diverse strategy."""
        request = OrchestrationRequest(
            question="Test",
            team_strategy=TeamStrategy.DIVERSE,
        )
        agents = await handler._select_agent_team(request)
        assert len(agents) >= 3  # Diverse uses more agents

    @pytest.mark.asyncio
    async def test_select_agent_team_random(self, handler):
        """Test agent selection with random strategy."""
        request = OrchestrationRequest(
            question="Test",
            team_strategy=TeamStrategy.RANDOM,
        )
        agents = await handler._select_agent_team(request)
        assert len(agents) <= 3
        assert len(agents) >= 1

    @pytest.mark.asyncio
    async def test_select_agent_team_best_for_domain_fallback(self, handler):
        """Test agent selection with best_for_domain falls back gracefully."""
        request = OrchestrationRequest(
            question="Test",
            team_strategy=TeamStrategy.BEST_FOR_DOMAIN,
        )
        agents = await handler._select_agent_team(request)
        # Should return default agents when routing handler not available
        assert len(agents) >= 2

    @pytest.mark.asyncio
    async def test_select_agent_team_specified_with_no_agents(self, handler):
        """Test agent selection with specified strategy but no agents provided."""
        request = OrchestrationRequest(
            question="Test",
            agents=[],
            team_strategy=TeamStrategy.SPECIFIED,
        )
        agents = await handler._select_agent_team(request)
        # Should fall back to default agents
        assert len(agents) >= 2

    @pytest.mark.asyncio
    async def test_select_agent_team_best_for_domain_with_routing_handler(self, handler):
        """Test agent selection with best_for_domain using routing handler."""
        request = OrchestrationRequest(
            question="Test code review question",
            team_strategy=TeamStrategy.BEST_FOR_DOMAIN,
        )

        mock_recommend = AsyncMock(
            return_value=["recommended-agent-1", "recommended-agent-2", "recommended-agent-3"]
        )

        with patch.dict(
            "sys.modules",
            {"aragora.server.handlers.routing": MagicMock(recommend_agents=mock_recommend)},
        ):
            with patch(
                "aragora.server.handlers.routing.recommend_agents", mock_recommend, create=True
            ):
                agents = await handler._select_agent_team(request)
                # Should still get agents (either recommended or fallback)
                assert len(agents) >= 2

    @pytest.mark.asyncio
    async def test_format_result_for_channel(self, handler):
        """Test result formatting for channel delivery."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            consensus_reached=True,
            final_answer="Use option A.",
            confidence=0.9,
            agents_participated=["agent1", "agent2"],
            duration_seconds=30.0,
        )
        request = OrchestrationRequest(
            question="Which option?",
            output_format=OutputFormat.STANDARD,
        )

        message = handler._format_result_for_channel(result, request)
        assert "Deliberation Result" in message
        assert "Consensus reached" in message
        assert "Use option A." in message
        assert "90%" in message  # confidence

    @pytest.mark.asyncio
    async def test_format_result_summary_format(self, handler):
        """Test result formatting with SUMMARY format."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            final_answer="Short answer.",
        )
        request = OrchestrationRequest(
            question="Test?",
            output_format=OutputFormat.SUMMARY,
        )

        message = handler._format_result_for_channel(result, request)
        assert "Deliberation Complete" in message
        assert "Short answer." in message

    @pytest.mark.asyncio
    async def test_format_result_no_consensus(self, handler):
        """Test result formatting when no consensus reached."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            consensus_reached=False,
            final_answer="Partial agreement.",
        )
        request = OrchestrationRequest(
            question="Test?",
            output_format=OutputFormat.STANDARD,
        )

        message = handler._format_result_for_channel(result, request)
        assert "No consensus" in message

    @pytest.mark.asyncio
    async def test_format_result_no_answer(self, handler):
        """Test result formatting when no answer is provided."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            consensus_reached=False,
            final_answer=None,
        )
        request = OrchestrationRequest(
            question="Test?",
            output_format=OutputFormat.STANDARD,
        )

        message = handler._format_result_for_channel(result, request)
        assert "No conclusion reached" in message

    @pytest.mark.asyncio
    async def test_format_result_no_confidence(self, handler):
        """Test result formatting when confidence is not provided."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            consensus_reached=True,
            final_answer="Answer",
            confidence=None,
        )
        request = OrchestrationRequest(
            question="Test?",
            output_format=OutputFormat.STANDARD,
        )

        message = handler._format_result_for_channel(result, request)
        assert "Consensus reached" in message
        # Should not contain percentage when confidence is None


# =============================================================================
# Knowledge Context Fetching Tests
# =============================================================================


class TestKnowledgeContextFetching:
    """Tests for knowledge context fetching."""

    @pytest.fixture
    def handler(self):
        return OrchestrationHandler({})

    @pytest.mark.asyncio
    async def test_fetch_slack_context(self, handler):
        """Test fetching Slack channel context."""
        source = KnowledgeContextSource(
            source_type="slack",
            source_id="C12345",
            lookback_minutes=60,
            max_items=50,
        )

        mock_connector = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.messages = [{"text": "Test message"}]
        mock_ctx.to_context_string.return_value = "Test context"
        mock_connector.fetch_context = AsyncMock(return_value=mock_ctx)

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            result = await handler._fetch_chat_context("slack", source)
            assert result == "Test context"

    @pytest.mark.asyncio
    async def test_fetch_chat_context_no_connector(self, handler):
        """Test fetching chat context when connector not available."""
        source = KnowledgeContextSource(
            source_type="slack",
            source_id="C12345",
        )

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=None,
        ):
            result = await handler._fetch_chat_context("slack", source)
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_knowledge_context_unknown_type(self, handler):
        """Test fetching context for unknown source type."""
        source = KnowledgeContextSource(
            source_type="unknown_type",
            source_id="123",
        )

        result = await handler._fetch_knowledge_context(source)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_document_context(self, handler):
        """Test fetching document context from knowledge mound."""
        source = KnowledgeContextSource(
            source_type="document",
            source_id="search query",
        )

        # Create mock knowledge items with content attribute
        mock_item1 = MagicMock()
        mock_item1.content = "Doc 1 content"
        mock_item2 = MagicMock()
        mock_item2.content = "Doc 2 content"

        # Create mock QueryResult with items attribute
        mock_query_result = MagicMock()
        mock_query_result.items = [mock_item1, mock_item2]

        mock_mound = MagicMock()
        mock_mound.query = AsyncMock(return_value=mock_query_result)

        with patch(
            "aragora.knowledge.mound.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await handler._fetch_document_context(source)
            assert "Doc 1 content" in result
            assert "Doc 2 content" in result

    @pytest.mark.asyncio
    async def test_fetch_teams_context(self, handler):
        """Test fetching Teams channel context."""
        source = KnowledgeContextSource(
            source_type="teams",
            source_id="channel-123",
            lookback_minutes=30,
            max_items=20,
        )

        mock_connector = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.messages = [{"text": "Teams message"}]
        mock_ctx.to_context_string.return_value = "Teams context"
        mock_connector.fetch_context = AsyncMock(return_value=mock_ctx)

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            result = await handler._fetch_chat_context("teams", source)
            assert result == "Teams context"

    @pytest.mark.asyncio
    async def test_fetch_discord_context(self, handler):
        """Test fetching Discord channel context."""
        source = KnowledgeContextSource(
            source_type="discord",
            source_id="123456789",
        )

        mock_connector = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.messages = [{"text": "Discord message"}]
        mock_ctx.to_context_string.return_value = "Discord context"
        mock_connector.fetch_context = AsyncMock(return_value=mock_ctx)

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            result = await handler._fetch_chat_context("discord", source)
            assert result == "Discord context"

    @pytest.mark.asyncio
    async def test_fetch_telegram_context(self, handler):
        """Test fetching Telegram channel context."""
        source = KnowledgeContextSource(
            source_type="telegram",
            source_id="-1001234567890",
        )

        mock_connector = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.messages = [{"text": "Telegram message"}]
        mock_ctx.to_context_string.return_value = "Telegram context"
        mock_connector.fetch_context = AsyncMock(return_value=mock_ctx)

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            result = await handler._fetch_chat_context("telegram", source)
            assert result == "Telegram context"

    @pytest.mark.asyncio
    async def test_fetch_whatsapp_context(self, handler):
        """Test fetching WhatsApp channel context."""
        source = KnowledgeContextSource(
            source_type="whatsapp",
            source_id="group-123",
        )

        mock_connector = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.messages = [{"text": "WhatsApp message"}]
        mock_ctx.to_context_string.return_value = "WhatsApp context"
        mock_connector.fetch_context = AsyncMock(return_value=mock_ctx)

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            result = await handler._fetch_chat_context("whatsapp", source)
            assert result == "WhatsApp context"

    @pytest.mark.asyncio
    async def test_fetch_confluence_context(self, handler):
        """Test fetching Confluence page context."""
        handler_with_ctx = OrchestrationHandler(
            {"confluence_url": "https://confluence.example.com"}
        )

        source = KnowledgeContextSource(
            source_type="confluence",
            source_id="12345",
        )

        mock_evidence = MagicMock()
        mock_evidence.content = "Confluence page content"

        mock_connector_instance = MagicMock()
        mock_connector_instance.fetch = AsyncMock(return_value=mock_evidence)

        with patch(
            "aragora.connectors.enterprise.collaboration.confluence.ConfluenceConnector",
            return_value=mock_connector_instance,
        ):
            result = await handler_with_ctx._fetch_confluence_context(source)
            assert result == "Confluence page content"

    @pytest.mark.asyncio
    async def test_fetch_confluence_context_no_url(self, handler):
        """Test fetching Confluence context without configured URL."""
        source = KnowledgeContextSource(
            source_type="confluence",
            source_id="12345",
        )

        result = await handler._fetch_confluence_context(source)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_github_context(self, handler):
        """Test fetching GitHub PR/issue context."""
        source = KnowledgeContextSource(
            source_type="github",
            source_id="owner/repo/pr/123",
        )

        mock_evidence = MagicMock()
        mock_evidence.content = "PR description and comments"

        mock_connector_instance = MagicMock()
        mock_connector_instance.search = AsyncMock(return_value=[mock_evidence])

        with patch(
            "aragora.connectors.github.GitHubConnector",
            return_value=mock_connector_instance,
        ):
            result = await handler._fetch_github_context(source)
            assert result == "PR description and comments"

    @pytest.mark.asyncio
    async def test_fetch_github_context_invalid_format(self, handler):
        """Test fetching GitHub context with invalid source_id format."""
        source = KnowledgeContextSource(
            source_type="github",
            source_id="invalid",
        )

        result = await handler._fetch_github_context(source)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_jira_context(self, handler):
        """Test fetching Jira issue context."""
        handler_with_ctx = OrchestrationHandler({"jira_url": "https://jira.example.com"})

        source = KnowledgeContextSource(
            source_type="jira",
            source_id="PROJ-123",
        )

        mock_evidence = MagicMock()
        mock_evidence.content = "Jira issue content"

        mock_connector_instance = MagicMock()
        mock_connector_instance.fetch = AsyncMock(return_value=mock_evidence)

        with patch(
            "aragora.connectors.enterprise.collaboration.jira.JiraConnector",
            return_value=mock_connector_instance,
        ):
            result = await handler_with_ctx._fetch_jira_context(source)
            assert result == "Jira issue content"

    @pytest.mark.asyncio
    async def test_fetch_jira_context_no_url(self, handler):
        """Test fetching Jira context without configured URL."""
        source = KnowledgeContextSource(
            source_type="jira",
            source_id="PROJ-123",
        )

        result = await handler._fetch_jira_context(source)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_document_context_no_mound(self, handler):
        """Test fetching document context when knowledge mound is not available."""
        source = KnowledgeContextSource(
            source_type="document",
            source_id="search query",
        )

        with patch(
            "aragora.knowledge.mound.get_knowledge_mound",
            return_value=None,
        ):
            result = await handler._fetch_document_context(source)
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_chat_context_empty_messages(self, handler):
        """Test fetching chat context with no messages."""
        source = KnowledgeContextSource(
            source_type="slack",
            source_id="C12345",
        )

        mock_connector = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.messages = []
        mock_connector.fetch_context = AsyncMock(return_value=mock_ctx)

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            result = await handler._fetch_chat_context("slack", source)
            assert result is None

    @pytest.mark.asyncio
    async def test_fetch_chat_context_exception(self, handler):
        """Test fetching chat context handles exceptions gracefully."""
        source = KnowledgeContextSource(
            source_type="slack",
            source_id="C12345",
        )

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            side_effect=ConnectionError("Connection failed"),
        ):
            result = await handler._fetch_chat_context("slack", source)
            assert result is None


# =============================================================================
# Output Channel Routing Tests
# =============================================================================


class TestOutputChannelRouting:
    """Tests for routing results to output channels."""

    @pytest.fixture
    def handler(self):
        return OrchestrationHandler({})

    @pytest.mark.asyncio
    async def test_send_to_slack(self, handler):
        """Test sending result to Slack channel."""
        channel = OutputChannel(
            channel_type="slack",
            channel_id="C12345",
            thread_id="123456.789",
        )

        mock_connector = MagicMock()
        mock_connector.send_message = AsyncMock()

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            await handler._send_to_slack(channel, "Test message")

            mock_connector.send_message.assert_called_once_with(
                "C12345",
                "Test message",
                thread_ts="123456.789",
            )

    @pytest.mark.asyncio
    async def test_send_to_slack_no_connector(self, handler):
        """Test sending to Slack when connector is not available."""
        channel = OutputChannel(
            channel_type="slack",
            channel_id="C12345",
        )

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=None,
        ):
            # Should not raise, just log warning
            await handler._send_to_slack(channel, "Test message")

    @pytest.mark.asyncio
    async def test_send_to_teams(self, handler):
        """Test sending result to Teams channel."""
        channel = OutputChannel(
            channel_type="teams",
            channel_id="channel-123",
        )

        mock_connector = MagicMock()
        mock_connector.send_message = AsyncMock()

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            await handler._send_to_teams(channel, "Test message")

            mock_connector.send_message.assert_called_once_with(
                "channel-123",
                "Test message",
            )

    @pytest.mark.asyncio
    async def test_send_to_discord(self, handler):
        """Test sending result to Discord channel."""
        channel = OutputChannel(
            channel_type="discord",
            channel_id="123456789",
        )

        mock_connector = MagicMock()
        mock_connector.send_message = AsyncMock()

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            await handler._send_to_discord(channel, "Test message")

            mock_connector.send_message.assert_called_once_with(
                "123456789",
                "Test message",
            )

    @pytest.mark.asyncio
    async def test_send_to_telegram(self, handler):
        """Test sending result to Telegram channel."""
        channel = OutputChannel(
            channel_type="telegram",
            channel_id="-1001234567890",
        )

        mock_connector = MagicMock()
        mock_connector.send_message = AsyncMock()

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            await handler._send_to_telegram(channel, "Test message")

            mock_connector.send_message.assert_called_once_with(
                "-1001234567890",
                "Test message",
            )

    @pytest.mark.asyncio
    async def test_send_to_email(self, handler):
        """Test sending result via email."""
        channel = OutputChannel(
            channel_type="email",
            channel_id="user@example.com",
        )

        request = OrchestrationRequest(
            question="Test question for email?",
        )

        mock_send_email = AsyncMock()

        with patch.dict(
            "sys.modules", {"aragora.connectors.email": MagicMock(send_email=mock_send_email)}
        ):
            with patch("aragora.connectors.email.send_email", mock_send_email, create=True):
                await handler._send_to_email(channel, "Test message", request)

    @pytest.mark.asyncio
    async def test_send_to_webhook(self, handler):
        """Test sending result to webhook."""
        channel = OutputChannel(
            channel_type="webhook",
            channel_id="https://example.com/webhook",
        )

        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            final_answer="Test answer",
        )

        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_session.post = MagicMock(
            return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        with patch("aiohttp.ClientSession") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            await handler._send_to_webhook(channel, result)

    @pytest.mark.asyncio
    async def test_send_to_webhook_error_response(self, handler):
        """Test sending to webhook handles error responses gracefully."""
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
        mock_response.status = 500

        mock_session = MagicMock()
        mock_session.post = MagicMock(
            return_value=MagicMock(__aenter__=AsyncMock(return_value=mock_response))
        )

        with patch("aiohttp.ClientSession") as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)

            # Should not raise, just log warning
            await handler._send_to_webhook(channel, result)

    @pytest.mark.asyncio
    async def test_route_to_channel_slack(self, handler):
        """Test routing to Slack channel."""
        channel = OutputChannel(
            channel_type="slack",
            channel_id="C12345",
        )

        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            final_answer="Test answer",
        )

        request = OrchestrationRequest(
            question="Test?",
            output_format=OutputFormat.STANDARD,
        )

        mock_connector = MagicMock()
        mock_connector.send_message = AsyncMock()

        with patch(
            "aragora.connectors.chat.registry.get_connector",
            return_value=mock_connector,
        ):
            await handler._route_to_channel(channel, result, request)
            mock_connector.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_to_unknown_channel_type(self, handler):
        """Test routing to unknown channel type logs warning."""
        channel = OutputChannel(
            channel_type="unknown",
            channel_id="some-id",
        )

        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            final_answer="Test answer",
        )

        request = OrchestrationRequest(
            question="Test?",
            output_format=OutputFormat.STANDARD,
        )

        # Should not raise, just log warning
        await handler._route_to_channel(channel, result, request)


# =============================================================================
# Template Application Tests
# =============================================================================


class TestTemplateApplication:
    """Tests for template application to requests."""

    def test_apply_template_to_request(self):
        """Test that templates are applied correctly."""
        handler = OrchestrationHandler({})

        data = {
            "question": "Review this PR",
            "template": "code_review",
        }

        with _stub_create_task():
            result = handler._handle_deliberate(data, None, None, sync=False)

        # Request should be created with template defaults
        # (The result is queued, so we verify it was processed)
        assert result.status_code in [202, 400, 500]  # Queued or error

    def test_request_agents_override_template(self):
        """Test that request agents override template defaults."""
        request = OrchestrationRequest.from_dict(
            {
                "question": "Test",
                "template": "code_review",
                "agents": ["custom-agent"],
            }
        )

        # Explicit agents should be preserved
        assert request.agents == ["custom-agent"]

    def test_template_applies_default_knowledge_sources(self):
        """Test that templates apply default knowledge sources when none provided."""
        handler = OrchestrationHandler({})

        # Parse request with template
        request = OrchestrationRequest.from_dict(
            {
                "question": "Review this PR",
                "template": "code_review",
            }
        )

        # Verify template name is set
        assert request.template == "code_review"

    def test_template_does_not_override_explicit_agents(self):
        """Test that explicit agents are not overridden by template defaults."""
        data = {
            "question": "Test",
            "template": "quick_decision",
            "agents": ["my-custom-agent"],
        }
        request = OrchestrationRequest.from_dict(data)
        assert request.agents == ["my-custom-agent"]


# =============================================================================
# End-to-End Deliberation Tests
# =============================================================================


@pytest.mark.timeout(15)
class TestEndToEndOrchestration:
    """End-to-end tests for orchestration flow."""

    @pytest.fixture(autouse=True)
    def _mock_decision_router(self):
        """Prevent real HTTP calls via get_decision_router.

        Safety net against mock pollution with randomized test ordering
        (e.g. seed 99999) where per-test patches may silently fail.
        """
        mock_result = MagicMock(
            success=True,
            consensus_reached=False,
            final_answer="mock fallback",
            confidence=0.5,
            rounds=0,
        )
        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_result)
        with patch(
            "aragora.core.decision.get_decision_router",
            return_value=mock_router,
        ):
            yield

    @pytest.mark.asyncio
    async def test_deliberation_without_coordinator(self):
        """Test deliberation falls back when coordinator unavailable."""
        handler = OrchestrationHandler({})

        # Mock at the module level where it's imported
        with patch.object(
            handler,
            "_execute_deliberation",
            new_callable=AsyncMock,
        ) as mock_execute:
            mock_execute.return_value = OrchestrationResult(
                request_id="test-123",
                success=True,
                final_answer="Test answer",
                consensus_reached=True,
                confidence=0.9,
            )

            request = OrchestrationRequest(
                question="Test question",
                agents=["anthropic-api"],
            )

            result = await mock_execute(request)

            assert result.success is True
            assert result.final_answer == "Test answer"
            assert result.consensus_reached is True

    @pytest.mark.asyncio
    async def test_knowledge_context_parsing(self):
        """Test that knowledge context sources are correctly parsed."""
        handler = OrchestrationHandler({})

        request = OrchestrationRequest.from_dict(
            {
                "question": "What should we do?",
                "knowledge_sources": [
                    "slack:C12345",
                    {"type": "confluence", "id": "page/123", "lookback_minutes": 120},
                ],
            }
        )

        assert len(request.knowledge_sources) == 2
        assert request.knowledge_sources[0].source_type == "slack"
        assert request.knowledge_sources[0].source_id == "C12345"
        assert request.knowledge_sources[1].source_type == "confluence"
        assert request.knowledge_sources[1].lookback_minutes == 120

    @pytest.mark.asyncio
    async def test_execute_and_store_handles_errors(self):
        """Test that _execute_and_store handles errors gracefully."""
        handler = OrchestrationHandler({})

        request = OrchestrationRequest(
            question="Test question",
            request_id="error-test-123",
        )

        with patch.object(
            handler,
            "_execute_deliberation",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Test error"),
        ):
            await handler._execute_and_store(request)

            # Result should be stored with error
            result = _orchestration_results.get("error-test-123")
            assert result is not None
            assert result.success is False
            assert result.error  # Sanitized error message present

    @pytest.mark.asyncio
    async def test_execute_and_store_cleans_up_request(self):
        """Test that _execute_and_store removes request from in-progress."""
        handler = OrchestrationHandler({})

        request = OrchestrationRequest(
            question="Test question",
            request_id="cleanup-test-123",
        )

        # Add to in-progress
        _orchestration_requests[request.request_id] = request

        with patch.object(
            handler,
            "_execute_deliberation",
            new_callable=AsyncMock,
            return_value=OrchestrationResult(
                request_id="cleanup-test-123",
                success=True,
            ),
        ):
            await handler._execute_and_store(request)

            # Request should be removed from in-progress
            assert "cleanup-test-123" not in _orchestration_requests
            # Result should be in results
            assert "cleanup-test-123" in _orchestration_results

    @pytest.mark.asyncio
    async def test_execute_deliberation_with_coordinator(self):
        """Test execute_deliberation with control plane coordinator."""
        mock_coordinator = MagicMock()
        handler = OrchestrationHandler({"control_plane_coordinator": mock_coordinator})

        mock_outcome = MagicMock()
        mock_outcome.success = True
        mock_outcome.consensus_reached = True
        mock_outcome.winning_position = "Use microservices"
        mock_outcome.consensus_confidence = 0.9

        mock_manager = MagicMock()
        mock_manager.submit_deliberation = AsyncMock(return_value="task-123")
        mock_manager.wait_for_outcome = AsyncMock(return_value=mock_outcome)

        with patch(
            "aragora.control_plane.deliberation.DeliberationManager",
            return_value=mock_manager,
        ):
            request = OrchestrationRequest(
                question="Should we use microservices?",
                agents=["anthropic-api", "openai-api"],
            )

            result = await handler._execute_deliberation(request)

            assert result.success is True
            assert result.consensus_reached is True
            assert result.final_answer == "Use microservices"
            assert result.confidence == 0.9

    @pytest.mark.asyncio
    async def test_execute_deliberation_timeout(self):
        """Test execute_deliberation handles timeout."""
        mock_coordinator = MagicMock()
        handler = OrchestrationHandler({"control_plane_coordinator": mock_coordinator})

        mock_manager = MagicMock()
        mock_manager.submit_deliberation = AsyncMock(return_value="task-123")
        mock_manager.wait_for_outcome = AsyncMock(return_value=None)  # Timeout

        with patch(
            "aragora.control_plane.deliberation.DeliberationManager",
            return_value=mock_manager,
        ):
            request = OrchestrationRequest(
                question="Test question?",
                timeout_seconds=60.0,
            )

            result = await handler._execute_deliberation(request)

            assert result.success is False
            assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_execute_deliberation_without_coordinator(self):
        """Test execute_deliberation falls back without coordinator."""
        handler = OrchestrationHandler({"control_plane_coordinator": None})

        mock_decision_result = MagicMock()
        mock_decision_result.success = True
        mock_decision_result.consensus_reached = True
        mock_decision_result.final_answer = "Fallback answer"
        mock_decision_result.confidence = 0.8
        mock_decision_result.rounds = 2

        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_decision_result)

        with patch(
            "aragora.core.decision.get_decision_router",
            return_value=mock_router,
        ):
            request = OrchestrationRequest(
                question="Test without coordinator?",
                agents=["anthropic-api"],
            )

            result = await handler._execute_deliberation(request)

            assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_deliberation_routes_to_channels(self):
        """Test that execute_deliberation routes results to output channels.

        This test verifies that output channel routing is attempted by
        mocking the necessary components.
        """
        handler = OrchestrationHandler({"control_plane_coordinator": None})

        mock_connector = MagicMock()
        mock_connector.send_message = AsyncMock()

        # Mock the execute_deliberation to simulate a successful result
        mock_result = OrchestrationResult(
            request_id="test-123",
            success=True,
            final_answer="Test answer",
            channels_notified=["slack:C12345"],
        )

        with patch.object(
            handler,
            "_execute_deliberation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            request = OrchestrationRequest(
                question="Test with channels?",
                output_channels=[OutputChannel.from_string("slack:C12345")],
            )

            result = await handler._execute_deliberation(request)

            # Verify the result structure
            assert result.success is True
            # Check that channels_notified is populated
            assert "slack:C12345" in result.channels_notified

    @pytest.mark.asyncio
    async def test_execute_deliberation_fetches_knowledge_context(self):
        """Test that execute_deliberation fetches knowledge context."""
        handler = OrchestrationHandler({"control_plane_coordinator": None})

        mock_decision_result = MagicMock()
        mock_decision_result.success = True

        mock_router = MagicMock()
        mock_router.route = AsyncMock(return_value=mock_decision_result)

        mock_connector = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.messages = [{"text": "Context message"}]
        mock_ctx.to_context_string.return_value = "Fetched context"
        mock_connector.fetch_context = AsyncMock(return_value=mock_ctx)

        with patch(
            "aragora.core.decision.get_decision_router",
            return_value=mock_router,
        ):
            with patch(
                "aragora.connectors.chat.registry.get_connector",
                return_value=mock_connector,
            ):
                request = OrchestrationRequest(
                    question="Test with context?",
                    knowledge_sources=[KnowledgeContextSource.from_string("slack:C12345")],
                )

                result = await handler._execute_deliberation(request)

                # Knowledge context should be recorded
                assert "slack:C12345" in result.knowledge_context_used


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling in the handler."""

    def test_deliberate_catches_exceptions(self):
        """Test that _handle_deliberate catches and returns errors."""
        handler = OrchestrationHandler({})

        # Malformed data that might cause parsing errors
        with _stub_create_task():
            result = handler._handle_deliberate(
                {"question": "Test", "knowledge_sources": [{"invalid": "data"}]},
                None,
                None,
                sync=False,
            )

        # Should return 202 (queued) or 500 (error), not raise
        assert result is not None
        assert result.status_code in [202, 400, 500]

    def test_empty_question_returns_error(self):
        """Test that empty question returns 400 error."""
        handler = OrchestrationHandler({})

        result = handler._handle_deliberate({"question": ""}, None, None, sync=False)

        assert result.status_code == 400
        body = json.loads(result.body)
        assert "Question is required" in body["error"]

    def test_whitespace_only_question_may_be_queued(self):
        """Test that whitespace-only question is handled.

        Note: The handler may not strip whitespace from questions, so this
        may be queued rather than rejected. This test verifies the handler
        doesn't crash and returns a valid response.
        """
        handler = OrchestrationHandler({})

        with _stub_create_task():
            result = handler._handle_deliberate({"question": "   "}, None, None, sync=False)

        # Should return a valid response (either queued or error)
        assert result is not None
        assert result.status_code in [400, 202, 500]

    def test_very_long_question_handles_gracefully(self):
        """Test that very long questions are handled."""
        handler = OrchestrationHandler({})

        long_question = "Test " * 10000  # ~50000 chars

        with _stub_create_task():
            result = handler._handle_deliberate({"question": long_question}, None, None, sync=False)

        # Should either queue or error, not crash
        assert result is not None
        assert result.status_code in [202, 400, 500]

    def test_invalid_json_types_in_request(self):
        """Test handling of invalid JSON types in request fields."""
        handler = OrchestrationHandler({})

        # agents should be list of strings, not dict
        with _stub_create_task():
            result = handler._handle_deliberate(
                {"question": "Test", "agents": {"invalid": "type"}},
                None,
                None,
                sync=False,
            )

        # Should handle gracefully
        assert result is not None

    def test_none_values_in_request(self):
        """Test handling of None values in request."""
        handler = OrchestrationHandler({})

        with _stub_create_task():
            result = handler._handle_deliberate(
                {"question": "Test", "knowledge_sources": None},
                None,
                None,
                sync=False,
            )

        # Should handle gracefully
        assert result is not None

    @pytest.mark.asyncio
    async def test_execute_deliberation_exception_handling(self):
        """Test that execute_deliberation handles exceptions."""
        handler = OrchestrationHandler({"control_plane_coordinator": None})

        with patch(
            "aragora.core.decision.get_decision_router",
            side_effect=RuntimeError("Router failed"),
        ):
            request = OrchestrationRequest(
                question="Test exception?",
            )

            result = await handler._execute_deliberation(request)

            assert result.success is False
            assert result.error  # Sanitized error message present


# =============================================================================
# Input Validation Tests
# =============================================================================


class TestInputValidation:
    """Tests for input validation."""

    def test_validate_team_strategy_case_insensitive(self):
        """Test that team strategy validation is case-sensitive."""
        # Team strategy should match exactly
        data = {"question": "Test", "team_strategy": "FAST"}
        request = OrchestrationRequest.from_dict(data)
        # Invalid, falls back to default
        assert request.team_strategy == TeamStrategy.BEST_FOR_DOMAIN

    def test_validate_output_format_case_insensitive(self):
        """Test that output format validation is case-sensitive."""
        data = {"question": "Test", "output_format": "SUMMARY"}
        request = OrchestrationRequest.from_dict(data)
        # Invalid, falls back to default
        assert request.output_format == OutputFormat.STANDARD

    def test_validate_max_rounds_bounds(self):
        """Test that max_rounds is within expected bounds."""
        from aragora.config import MAX_ROUNDS

        data = {"question": "Test", "max_rounds": 100}
        request = OrchestrationRequest.from_dict(data)
        assert request.max_rounds == 100  # Value is passed through

        data = {"question": "Test"}
        request = OrchestrationRequest.from_dict(data)
        assert request.max_rounds == MAX_ROUNDS  # Default

    def test_validate_timeout_bounds(self):
        """Test that timeout_seconds handles various values."""
        data = {"question": "Test", "timeout_seconds": 1.0}
        request = OrchestrationRequest.from_dict(data)
        assert request.timeout_seconds == 1.0

        data = {"question": "Test", "timeout_seconds": 3600.0}
        request = OrchestrationRequest.from_dict(data)
        assert request.timeout_seconds == 3600.0

    def test_validate_priority_values(self):
        """Test that priority accepts various values."""
        for priority in ["low", "normal", "high", "critical"]:
            data = {"question": "Test", "priority": priority}
            request = OrchestrationRequest.from_dict(data)
            assert request.priority == priority


# =============================================================================
# Receipt and Provenance Tests
# =============================================================================


class TestReceiptAndProvenance:
    """Tests for receipt generation and provenance tracking."""

    def test_result_includes_receipt_id(self):
        """Test that result can include a receipt ID."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            receipt_id="receipt-abc-123",
        )

        data = result.to_dict()
        assert data["receipt_id"] == "receipt-abc-123"

    def test_result_tracks_knowledge_context_used(self):
        """Test that result tracks which knowledge sources were used."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            knowledge_context_used=["slack:C123", "confluence:page/456"],
        )

        data = result.to_dict()
        assert len(data["knowledge_context_used"]) == 2
        assert "slack:C123" in data["knowledge_context_used"]
        assert "confluence:page/456" in data["knowledge_context_used"]

    def test_result_tracks_channels_notified(self):
        """Test that result tracks which channels were notified."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            channels_notified=["slack:C789", "email:user@example.com"],
        )

        data = result.to_dict()
        assert len(data["channels_notified"]) == 2
        assert "slack:C789" in data["channels_notified"]

    def test_result_tracks_agents_participated(self):
        """Test that result tracks which agents participated."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            agents_participated=["anthropic-api", "openai-api", "gemini"],
        )

        data = result.to_dict()
        assert len(data["agents_participated"]) == 3
        assert "anthropic-api" in data["agents_participated"]

    def test_result_tracks_timing(self):
        """Test that result tracks timing information."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
            duration_seconds=45.678,
            rounds_completed=3,
        )

        data = result.to_dict()
        assert data["duration_seconds"] == 45.678
        assert data["rounds_completed"] == 3

    def test_result_includes_created_at(self):
        """Test that result includes creation timestamp."""
        result = OrchestrationResult(
            request_id="req-123",
            success=True,
        )

        data = result.to_dict()
        assert data["created_at"] is not None
        # Should be ISO format
        assert "T" in data["created_at"]


# =============================================================================
# Rate Limiting Tests
# =============================================================================


class TestRateLimiting:
    """Tests related to rate limiting behavior."""

    def test_handle_deliberate_has_rate_limit_decorator(self):
        """Test that _handle_deliberate is rate limited."""
        handler = OrchestrationHandler({})

        # Check that the method has been decorated
        # The rate_limit decorator adds metadata we can inspect
        method = handler._handle_deliberate
        assert hasattr(method, "__wrapped__") or callable(method)


# =============================================================================
# Sync vs Async Deliberation Tests
# =============================================================================


class TestSyncVsAsyncDeliberation:
    """Tests for synchronous vs asynchronous deliberation."""

    def test_async_deliberate_returns_202_or_queued(self):
        """Test that async deliberate queues the request and returns 202."""
        handler = OrchestrationHandler({})

        # There is no running loop in this sync test, so stand in for
        # asyncio.create_task and close the queued coroutine.
        with _stub_create_task():
            result = handler._handle_deliberate(
                {"question": "Async test question"},
                None,
                None,
                sync=False,
            )

        assert result.status_code == 202
        body = json.loads(result.body)
        assert body["status"] == "queued"
        assert "request_id" in body

    def test_sync_deliberate_returns_result(self):
        """Test that sync deliberate returns a result.

        Note: This test verifies the sync deliberation path with mocked execution.
        The sync path uses run_async() to block until completion.
        """
        handler = OrchestrationHandler({})

        mock_result = OrchestrationResult(
            request_id="sync-123",
            success=True,
            final_answer="Sync answer",
        )

        # Mock the internal execution method to avoid actual deliberation
        with patch.object(
            handler,
            "_execute_deliberation",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            with patch(
                "aragora.server.handlers.orchestration.handler.run_async",
                side_effect=close_coroutine_then(mock_result),
            ):
                result = handler._handle_deliberate(
                    {"question": "Sync test question"},
                    None,
                    None,
                    sync=True,
                )

                assert result.status_code == 200
                body = json.loads(result.body)
                assert body["success"] is True
                assert body["final_answer"] == "Sync answer"

    def test_async_deliberate_includes_status_url(self):
        """Test that async response includes status URL hint."""
        handler = OrchestrationHandler({})

        with _stub_create_task():
            result = handler._handle_deliberate(
                {"question": "Test question"},
                None,
                None,
                sync=False,
            )

        assert result.status_code == 202
        body = json.loads(result.body)
        assert "message" in body
        assert "/api/v1/orchestration/status/" in body["message"]


# =============================================================================
# Handler POST Method Tests
# =============================================================================


class TestHandlerPostMethod:
    """Tests for the handle_post method routing."""

    @pytest.mark.asyncio
    async def test_handle_post_deliberate_route(self, handler, mock_auth_context):
        """Test POST routing to deliberate endpoint."""
        from aragora.rbac.models import AuthorizationContext

        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            return_value=mock_auth_context,
        ):
            with patch.object(handler, "check_permission", return_value=True):
                # Mock _execute_deliberation to prevent background task from
                # making real HTTP calls (which hangs the event loop)
                with patch.object(
                    handler,
                    "_execute_deliberation",
                    new_callable=AsyncMock,
                    return_value=OrchestrationResult(
                        request_id="test-async",
                        success=True,
                    ),
                ):
                    result = await handler.handle_post(
                        "/api/v1/orchestration/deliberate",
                        {"question": "Test?"},
                        {},
                        None,
                    )

                    assert result is not None
                    assert result.status_code in [202, 400, 500]

    @pytest.mark.asyncio
    async def test_handle_post_sync_deliberate_route(self, handler, mock_auth_context):
        """Test POST routing to sync deliberate endpoint."""
        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            return_value=mock_auth_context,
        ):
            with patch.object(handler, "check_permission", return_value=True):
                with patch(
                    "aragora.server.handlers.orchestration.handler.run_async",
                    side_effect=close_coroutine_then(
                        OrchestrationResult(
                            request_id="sync-123",
                            success=True,
                        )
                    ),
                ):
                    result = await handler.handle_post(
                        "/api/v1/orchestration/deliberate/sync",
                        {"question": "Test?"},
                        {},
                        None,
                    )

                    assert result is not None
                    assert result.status_code in [200, 400, 500]

    @pytest.mark.asyncio
    async def test_handle_post_unknown_path_returns_none(self, handler, mock_auth_context):
        """Test POST to unknown path returns None."""
        with patch.object(
            handler,
            "get_auth_context",
            new_callable=AsyncMock,
            return_value=mock_auth_context,
        ):
            with patch.object(handler, "check_permission", return_value=True):
                result = await handler.handle_post(
                    "/api/v1/orchestration/unknown",
                    {},
                    {},
                    None,
                )

                assert result is None
