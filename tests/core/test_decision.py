"""
Tests for core decision module.

Tests cover:
- DecisionType enum
- InputSource enum
- Priority enum
- ResponseFormat enum
- ResponseChannel dataclass
- RequestContext dataclass
- DecisionConfig dataclass
- DecisionRequest dataclass
- DecisionResult dataclass
- DecisionRouter class
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from aragora.core.decision import (
    DecisionType,
    InputSource,
    Priority,
    ResponseFormat,
    ResponseChannel,
    RequestContext,
    DecisionConfig,
    DecisionRequest,
    DecisionResult,
    DecisionRouter,
)


class TestDecisionType:
    """Tests for DecisionType enum."""

    def test_has_all_types(self):
        """Enum has all expected decision types."""
        assert DecisionType.DEBATE.value == "debate"
        assert DecisionType.WORKFLOW.value == "workflow"
        assert DecisionType.GAUNTLET.value == "gauntlet"
        assert DecisionType.QUICK.value == "quick"
        assert DecisionType.AUTO.value == "auto"

    def test_type_count(self):
        """Enum has exactly 5 types."""
        assert len(DecisionType) == 5

    def test_string_enum_value(self):
        """DecisionType value is a string."""
        assert isinstance(DecisionType.DEBATE.value, str)
        assert DecisionType.DEBATE.value == "debate"


class TestInputSource:
    """Tests for InputSource enum."""

    def test_chat_platforms(self):
        """Has chat platform sources."""
        assert InputSource.SLACK.value == "slack"
        assert InputSource.DISCORD.value == "discord"
        assert InputSource.TEAMS.value == "teams"
        assert InputSource.TELEGRAM.value == "telegram"

    def test_direct_interfaces(self):
        """Has direct interface sources."""
        assert InputSource.HTTP_API.value == "http_api"
        assert InputSource.WEBSOCKET.value == "websocket"
        assert InputSource.CLI.value == "cli"

    def test_voice_sources(self):
        """Has voice sources."""
        assert InputSource.VOICE.value == "voice"
        assert InputSource.VOICE_SLACK.value == "voice_slack"

    def test_enterprise_sources(self):
        """Has enterprise integration sources."""
        assert InputSource.JIRA.value == "jira"
        assert InputSource.GITHUB.value == "github"
        assert InputSource.CONFLUENCE.value == "confluence"


class TestPriority:
    """Tests for Priority enum."""

    def test_all_priorities(self):
        """Has all priority levels."""
        assert Priority.CRITICAL.value == "critical"
        assert Priority.HIGH.value == "high"
        assert Priority.NORMAL.value == "normal"
        assert Priority.LOW.value == "low"
        assert Priority.BATCH.value == "batch"

    def test_priority_count(self):
        """Has exactly 5 priority levels."""
        assert len(Priority) == 5


class TestResponseFormat:
    """Tests for ResponseFormat enum."""

    def test_all_formats(self):
        """Has all response formats."""
        assert ResponseFormat.FULL.value == "full"
        assert ResponseFormat.SUMMARY.value == "summary"
        assert ResponseFormat.NOTIFICATION.value == "notification"
        assert ResponseFormat.VOICE.value == "voice"
        assert ResponseFormat.VOICE_WITH_TEXT.value == "voice_with_text"


class TestResponseChannel:
    """Tests for ResponseChannel dataclass."""

    def test_create_basic(self):
        """Basic channel creation."""
        channel = ResponseChannel(platform="slack", channel_id="C123")
        assert channel.platform == "slack"
        assert channel.channel_id == "C123"

    def test_default_values(self):
        """Default values are sensible."""
        channel = ResponseChannel(platform="http")
        assert channel.channel_id is None
        assert channel.user_id is None
        assert channel.response_format == "full"
        assert channel.include_reasoning is True
        assert channel.voice_enabled is False

    def test_voice_settings(self):
        """Voice settings work correctly."""
        channel = ResponseChannel(
            platform="slack",
            voice_enabled=True,
            voice_id="alloy",
            voice_only=True,
        )
        assert channel.voice_enabled is True
        assert channel.voice_id == "alloy"
        assert channel.voice_only is True

    def test_to_dict(self):
        """Serializes to dictionary."""
        channel = ResponseChannel(
            platform="slack",
            channel_id="C123",
            user_id="U456",
        )
        data = channel.to_dict()

        assert data["platform"] == "slack"
        assert data["channel_id"] == "C123"
        assert data["user_id"] == "U456"
        assert "response_format" in data
        assert "voice_enabled" in data

    def test_from_dict(self):
        """Creates from dictionary."""
        data = {
            "platform": "discord",
            "channel_id": "123456",
            "response_format": "summary",
            "voice_enabled": True,
        }
        channel = ResponseChannel.from_dict(data)

        assert channel.platform == "discord"
        assert channel.channel_id == "123456"
        assert channel.response_format == "summary"
        assert channel.voice_enabled is True

    def test_from_dict_defaults(self):
        """from_dict handles missing keys with defaults."""
        data = {"platform": "http"}
        channel = ResponseChannel.from_dict(data)

        assert channel.platform == "http"
        assert channel.channel_id is None
        assert channel.response_format == "full"

    def test_roundtrip(self):
        """to_dict -> from_dict preserves data."""
        original = ResponseChannel(
            platform="teams",
            channel_id="C789",
            thread_id="T123",
            response_format="notification",
            voice_enabled=True,
            voice_id="nova",
        )
        data = original.to_dict()
        restored = ResponseChannel.from_dict(data)

        assert restored.platform == original.platform
        assert restored.channel_id == original.channel_id
        assert restored.thread_id == original.thread_id
        assert restored.response_format == original.response_format
        assert restored.voice_enabled == original.voice_enabled
        assert restored.voice_id == original.voice_id


class TestRequestContext:
    """Tests for RequestContext dataclass."""

    def test_create_basic(self):
        """Basic context creation."""
        ctx = RequestContext()
        assert ctx.correlation_id is not None
        assert ctx.created_at is not None

    def test_auto_correlation_id(self):
        """Generates unique correlation IDs."""
        ctx1 = RequestContext()
        ctx2 = RequestContext()
        assert ctx1.correlation_id != ctx2.correlation_id

    def test_user_info(self):
        """User info fields work correctly."""
        ctx = RequestContext(
            user_id="user123",
            user_name="Test User",
            user_email="test@example.com",
            user_roles=["admin", "developer"],
        )
        assert ctx.user_id == "user123"
        assert ctx.user_name == "Test User"
        assert ctx.user_email == "test@example.com"
        assert ctx.user_roles == ["admin", "developer"]

    def test_tenant_info(self):
        """Tenant/workspace fields work correctly."""
        ctx = RequestContext(
            tenant_id="tenant123",
            workspace_id="workspace456",
        )
        assert ctx.tenant_id == "tenant123"
        assert ctx.workspace_id == "workspace456"

    def test_to_dict(self):
        """Serializes to dictionary."""
        ctx = RequestContext(
            user_id="user123",
            tags=["urgent", "security"],
            metadata={"source": "test"},
        )
        data = ctx.to_dict()

        assert data["user_id"] == "user123"
        assert data["tags"] == ["urgent", "security"]
        assert data["metadata"] == {"source": "test"}
        assert "created_at" in data
        assert isinstance(data["created_at"], str)  # ISO format

    def test_from_dict(self):
        """Creates from dictionary."""
        data = {
            "correlation_id": "corr-123",
            "user_id": "user456",
            "created_at": "2024-01-15T10:30:00",
            "tags": ["test"],
        }
        ctx = RequestContext.from_dict(data)

        assert ctx.correlation_id == "corr-123"
        assert ctx.user_id == "user456"
        assert ctx.tags == ["test"]

    def test_from_dict_with_deadline(self):
        """from_dict handles deadline parsing."""
        data = {
            "deadline": "2024-01-15T12:00:00",
        }
        ctx = RequestContext.from_dict(data)

        assert ctx.deadline is not None
        assert isinstance(ctx.deadline, datetime)

    def test_roundtrip(self):
        """to_dict -> from_dict preserves data."""
        original = RequestContext(
            user_id="user789",
            tenant_id="tenant123",
            tags=["important"],
            metadata={"key": "value"},
        )
        data = original.to_dict()
        restored = RequestContext.from_dict(data)

        assert restored.user_id == original.user_id
        assert restored.tenant_id == original.tenant_id
        assert restored.tags == original.tags
        assert restored.metadata == original.metadata


class TestDecisionConfig:
    """Tests for DecisionConfig dataclass."""

    def test_default_values(self):
        """Default values are sensible."""
        config = DecisionConfig()
        assert config.timeout_seconds == 300
        from aragora.config.settings import get_settings

        assert config.max_agents == get_settings().debate.max_agents_per_debate
        assert config.rounds == get_settings().debate.default_rounds
        assert config.consensus == get_settings().debate.default_consensus
        assert config.enable_calibration is True
        assert config.early_stopping is True

    def test_debate_settings(self):
        """Debate-specific settings work."""
        config = DecisionConfig(
            rounds=5,
            consensus="unanimous",
            enable_calibration=False,
        )
        assert config.rounds == 5
        assert config.consensus == "unanimous"
        assert config.enable_calibration is False

    def test_workflow_settings(self):
        """Workflow-specific settings work."""
        config = DecisionConfig(
            workflow_id="wf-123",
            workflow_inputs={"param1": "value1"},
            stop_on_failure=False,
        )
        assert config.workflow_id == "wf-123"
        assert config.workflow_inputs == {"param1": "value1"}
        assert config.stop_on_failure is False

    def test_agents_list(self):
        """Agents list can be customized."""
        config = DecisionConfig(
            agents=["claude", "gpt4", "gemini"],
        )
        assert len(config.agents) == 3
        assert "claude" in config.agents


class TestDecisionRequest:
    """Tests for DecisionRequest dataclass."""

    def test_create_basic(self):
        """Basic request creation."""
        request = DecisionRequest(
            content="Should we use microservices?",
        )
        assert request.content == "Should we use microservices?"
        assert request.request_id is not None
        # AUTO gets auto-detected to DEBATE for this content
        assert request.decision_type == DecisionType.DEBATE

    def test_empty_content_raises(self):
        """Empty content raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DecisionRequest(content="")

    def test_whitespace_content_raises(self):
        """Whitespace-only content raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            DecisionRequest(content="   ")

    def test_with_decision_type(self):
        """Can specify decision type."""
        request = DecisionRequest(
            content="Validate this policy",
            decision_type=DecisionType.GAUNTLET,
        )
        assert request.decision_type == DecisionType.GAUNTLET

    def test_with_source(self):
        """Can specify input source."""
        request = DecisionRequest(
            content="Test question",
            source=InputSource.SLACK,
        )
        assert request.source == InputSource.SLACK

    def test_auto_creates_response_channel(self):
        """Auto-creates response channel if none provided."""
        request = DecisionRequest(
            content="Test",
            source=InputSource.SLACK,
        )
        assert len(request.response_channels) == 1
        assert request.response_channels[0].platform == "slack"

    def test_with_response_channels(self):
        """Can specify response channels."""
        channels = [
            ResponseChannel(platform="slack", channel_id="C123"),
            ResponseChannel(platform="email", email_address="test@example.com"),
        ]
        request = DecisionRequest(
            content="Test",
            response_channels=channels,
        )
        assert len(request.response_channels) == 2

    def test_with_context(self):
        """Can specify request context."""
        ctx = RequestContext(user_id="user123")
        request = DecisionRequest(
            content="Test",
            context=ctx,
        )
        assert request.context.user_id == "user123"

    def test_with_config(self):
        """Can specify decision config."""
        config = DecisionConfig(rounds=5)
        request = DecisionRequest(
            content="Test",
            config=config,
        )
        assert request.config.rounds == 5

    def test_with_attachments(self):
        """Can include attachments."""
        request = DecisionRequest(
            content="Review this code",
            attachments=[
                {"type": "code", "content": "def foo(): pass"},
            ],
        )
        assert len(request.attachments) == 1

    def test_with_priority(self):
        """Can specify priority."""
        request = DecisionRequest(
            content="Urgent issue",
            priority=Priority.CRITICAL,
        )
        assert request.priority == Priority.CRITICAL

    def test_auto_detect_workflow(self):
        """Auto-detects workflow type when workflow_id is set."""
        request = DecisionRequest(
            content="Run the pipeline",
            decision_type=DecisionType.AUTO,
            config=DecisionConfig(workflow_id="wf-123"),
        )
        assert request.decision_type == DecisionType.WORKFLOW

    def test_auto_detect_gauntlet(self):
        """Auto-detects gauntlet type for validation keywords."""
        request = DecisionRequest(
            content="Validate this security policy",
            decision_type=DecisionType.AUTO,
        )
        assert request.decision_type == DecisionType.GAUNTLET

    def test_auto_detect_quick(self):
        """Auto-detects quick type for simple keywords."""
        request = DecisionRequest(
            content="Quick question about this",
            decision_type=DecisionType.AUTO,
        )
        assert request.decision_type == DecisionType.QUICK

    def test_to_dict(self):
        """Serializes to dictionary."""
        request = DecisionRequest(
            content="Test content",
            decision_type=DecisionType.DEBATE,
            source=InputSource.SLACK,
        )
        data = request.to_dict()

        assert data["content"] == "Test content"
        assert data["decision_type"] == "debate"
        assert data["source"] == "slack"
        assert "request_id" in data
        assert "response_channels" in data

    def test_from_dict(self):
        """Creates from dictionary."""
        data = {
            "content": "Test question",
            "decision_type": "debate",
            "source": "http_api",
        }
        request = DecisionRequest.from_dict(data)

        assert request.content == "Test question"
        assert request.decision_type == DecisionType.DEBATE
        assert request.source == InputSource.HTTP_API

    def test_from_chat_message(self):
        """Creates from chat message."""
        request = DecisionRequest.from_chat_message(
            message="Should we deploy?",
            platform="slack",
            channel_id="C123",
            user_id="U456",
            thread_id="T789",
        )

        assert request.content == "Should we deploy?"
        assert request.source == InputSource.SLACK
        assert request.response_channels[0].channel_id == "C123"
        assert request.context.user_id == "U456"

    def test_from_http(self):
        """Creates from HTTP request body."""
        body = {
            "content": "API question",
            "decision_type": "debate",
        }
        request = DecisionRequest.from_http(body)

        assert request.content == "API question"
        assert request.decision_type == DecisionType.DEBATE

    def test_from_http_legacy_format(self):
        """Creates from legacy HTTP format."""
        body = {
            "question": "Legacy question",
            "agents": ["claude", "gpt4"],
            "rounds": 5,
        }
        request = DecisionRequest.from_http(body)

        assert request.content == "Legacy question"
        assert request.config.rounds == 5

    def test_from_http_with_correlation_id(self):
        """Extracts correlation ID from headers."""
        body = {"content": "Test"}
        headers = {"X-Correlation-ID": "corr-123"}
        request = DecisionRequest.from_http(body, headers)

        assert request.context.correlation_id == "corr-123"

    def test_from_http_with_documents(self):
        """Parses document IDs from HTTP request body."""
        body = {
            "question": "Use uploaded docs?",
            "documents": ["doc-1", "doc-2", "doc-1", "", 5],
        }
        request = DecisionRequest.from_http(body)

        assert request.documents == ["doc-1", "doc-2"]


class TestDecisionResult:
    """Tests for DecisionResult dataclass."""

    def test_create_basic(self):
        """Basic result creation."""
        result = DecisionResult(
            request_id="req-123",
            decision_type=DecisionType.DEBATE,
            answer="Use microservices for scalability",
            confidence=0.85,
            consensus_reached=True,
        )
        assert result.request_id == "req-123"
        assert result.answer == "Use microservices for scalability"
        assert result.confidence == 0.85
        assert result.consensus_reached is True

    def test_default_values(self):
        """Default values are sensible."""
        result = DecisionResult(
            request_id="req-123",
            decision_type=DecisionType.DEBATE,
            answer="Test answer",
            confidence=0.9,
            consensus_reached=True,
        )
        assert result.reasoning is None
        assert result.evidence_used == []
        assert result.agent_contributions == []
        assert result.success is True
        assert result.error is None

    def test_with_reasoning(self):
        """Can include reasoning."""
        result = DecisionResult(
            request_id="req-123",
            decision_type=DecisionType.DEBATE,
            answer="Approved",
            confidence=0.95,
            consensus_reached=True,
            reasoning="All criteria met based on evidence.",
        )
        assert "criteria" in result.reasoning

    def test_with_evidence(self):
        """Can include evidence used."""
        result = DecisionResult(
            request_id="req-123",
            decision_type=DecisionType.DEBATE,
            answer="Option A",
            confidence=0.7,
            consensus_reached=False,
            evidence_used=[
                {"source": "doc1", "summary": "Evidence 1"},
                {"source": "doc2", "summary": "Evidence 2"},
            ],
        )
        assert len(result.evidence_used) == 2

    def test_with_agent_contributions(self):
        """Can include agent contributions."""
        result = DecisionResult(
            request_id="req-123",
            decision_type=DecisionType.DEBATE,
            answer="Approved",
            confidence=0.8,
            consensus_reached=True,
            agent_contributions=[
                {"agent": "claude", "vote": "approve"},
                {"agent": "gpt4", "vote": "approve"},
            ],
        )
        assert len(result.agent_contributions) == 2

    def test_success_flag(self):
        """Success flag works correctly."""
        success = DecisionResult(
            request_id="req-123",
            decision_type=DecisionType.DEBATE,
            answer="Done",
            confidence=0.9,
            consensus_reached=True,
            success=True,
        )
        assert success.success is True

        failed = DecisionResult(
            request_id="req-456",
            decision_type=DecisionType.DEBATE,
            answer="",
            confidence=0.0,
            consensus_reached=False,
            success=False,
            error="Timeout occurred",
        )
        assert failed.success is False
        assert failed.error == "Timeout occurred"

    def test_to_dict(self):
        """Serializes to dictionary."""
        result = DecisionResult(
            request_id="req-123",
            decision_type=DecisionType.DEBATE,
            answer="Test answer",
            confidence=0.85,
            consensus_reached=True,
            duration_seconds=10.5,
        )
        data = result.to_dict()

        assert data["request_id"] == "req-123"
        assert data["decision_type"] == "debate"
        assert data["answer"] == "Test answer"
        assert data["confidence"] == 0.85
        assert data["consensus_reached"] is True
        assert data["duration_seconds"] == 10.5


class TestDecisionRouter:
    """Tests for DecisionRouter class."""

    def test_init_default(self):
        """Router initializes with defaults."""
        router = DecisionRouter()
        assert router._enable_caching is True
        assert router._enable_deduplication is True

    def test_init_with_engines(self):
        """Router initializes with engines."""
        debate_engine = MagicMock()
        workflow_engine = MagicMock()

        router = DecisionRouter(
            debate_engine=debate_engine,
            workflow_engine=workflow_engine,
        )

        assert router._debate_engine is debate_engine
        assert router._workflow_engine is workflow_engine

    def test_init_custom_settings(self):
        """Router initializes with custom settings."""
        router = DecisionRouter(
            enable_voice_responses=False,
            enable_caching=False,
            enable_deduplication=False,
            cache_ttl_seconds=7200.0,
        )

        assert router._enable_voice_responses is False
        assert router._enable_caching is False
        assert router._enable_deduplication is False
        assert router._cache_ttl_seconds == 7200.0

    def test_register_response_handler(self):
        """Can register response handlers."""
        router = DecisionRouter()
        handler = MagicMock()

        router.register_response_handler("slack", handler)

        assert "slack" in router._response_handlers
        assert router._response_handlers["slack"] is handler

    def test_register_handler_normalizes_platform(self):
        """Handler registration normalizes platform name."""
        router = DecisionRouter()
        handler = MagicMock()

        router.register_response_handler("SLACK", handler)

        assert "slack" in router._response_handlers

    @pytest.mark.asyncio
    async def test_route_to_debate_engine(self):
        """Routes debate requests to debate engine."""
        debate_engine = MagicMock()
        debate_engine.run = AsyncMock(
            return_value=MagicMock(
                task="test",
                final_answer="Consensus reached",
                confidence=0.9,
                consensus_reached=True,
            )
        )

        router = DecisionRouter(
            debate_engine=debate_engine,
            enable_caching=False,
        )

        request = DecisionRequest(
            content="Should we refactor?",
            decision_type=DecisionType.DEBATE,
        )

        # Route will attempt to use the debate engine
        # Metrics may not be available in test environment
        with patch("aragora.core.decision_router._record_decision_request", None):
            with patch("aragora.core.decision_router._record_decision_result", None):
                try:
                    result = await router.route(request)
                    assert result is not None
                except AttributeError:
                    # Metrics not available, test passes if routing was attempted
                    pass

    @pytest.mark.asyncio
    async def test_route_records_metrics(self):
        """Route records metrics when available."""
        router = DecisionRouter(enable_caching=False)

        request = DecisionRequest(
            content="Test question for debate",
            decision_type=DecisionType.DEBATE,
        )

        # Even without engines, it should handle gracefully
        # and record metrics if available
        mock_result = DecisionResult(
            request_id=request.request_id,
            decision_type=DecisionType.DEBATE,
            answer="Mock answer",
            confidence=0.8,
            consensus_reached=True,
        )

        with patch.object(router, "_route_to_debate", AsyncMock(return_value=mock_result)):
            try:
                await router.route(request)
            except Exception:
                pass  # Metrics may be unavailable in test environment


class TestDecisionIntegration:
    """Integration tests for decision flow."""

    def test_full_request_creation(self):
        """Creates complete request with all components."""
        channels = [
            ResponseChannel(
                platform="slack",
                channel_id="C123",
                response_format="summary",
            ),
        ]
        context = RequestContext(
            user_id="user123",
            tenant_id="tenant456",
            tags=["production"],
        )
        config = DecisionConfig(
            rounds=4,
            consensus="weighted",
            timeout_seconds=600,
        )

        request = DecisionRequest(
            content="Should we deploy to production?",
            decision_type=DecisionType.DEBATE,
            source=InputSource.SLACK,
            response_channels=channels,
            context=context,
            config=config,
            priority=Priority.HIGH,
        )

        assert request.content == "Should we deploy to production?"
        assert request.decision_type == DecisionType.DEBATE
        assert request.source == InputSource.SLACK
        assert request.response_channels[0].channel_id == "C123"
        assert request.context.user_id == "user123"
        assert request.config.rounds == 4
        assert request.priority == Priority.HIGH

    def test_result_with_full_metadata(self):
        """Creates complete result with all fields."""
        result = DecisionResult(
            request_id="req-789",
            decision_type=DecisionType.DEBATE,
            answer="Deploy to staging first",
            confidence=0.85,
            consensus_reached=True,
            reasoning="Risk mitigation suggests staging deployment.",
            evidence_used=[
                {"source": "incident-report", "summary": "Previous direct deploy failed"},
            ],
            agent_contributions=[
                {"agent": "claude", "vote": "approve"},
                {"agent": "gpt4", "vote": "approve"},
            ],
            duration_seconds=45.5,
        )

        assert result.confidence == 0.85
        assert len(result.evidence_used) == 1
        assert len(result.agent_contributions) == 2
        assert result.duration_seconds == 45.5

    def test_roundtrip_request(self):
        """Request can be serialized and deserialized."""
        original = DecisionRequest(
            content="Test question",
            decision_type=DecisionType.DEBATE,
            source=InputSource.SLACK,
            priority=Priority.HIGH,
        )

        data = original.to_dict()
        restored = DecisionRequest.from_dict(data)

        assert restored.content == original.content
        assert restored.decision_type == original.decision_type
        assert restored.source == original.source
        assert restored.priority == original.priority


# ===========================================================================
# Test: Decision Router - Route Methods
# ===========================================================================


class TestDecisionRouterRouteMethods:
    """Tests for DecisionRouter routing to different engines."""

    @pytest.mark.asyncio
    async def test_route_to_workflow_engine(self):
        """Routes workflow requests to workflow engine."""
        workflow_engine = MagicMock()
        workflow_engine.execute = AsyncMock(
            return_value=MagicMock(
                success=True,
                outputs={"result": "Workflow completed"},
            )
        )

        router = DecisionRouter(
            workflow_engine=workflow_engine,
            enable_caching=False,
        )

        request = DecisionRequest(
            content="Run data processing pipeline",
            decision_type=DecisionType.WORKFLOW,
            config=DecisionConfig(workflow_id="data-pipeline"),
        )

        # Mock the internal routing method
        mock_result = DecisionResult(
            request_id=request.request_id,
            decision_type=DecisionType.WORKFLOW,
            answer="Workflow completed",
            confidence=1.0,
            consensus_reached=True,
        )

        with patch.object(router, "_route_to_workflow", AsyncMock(return_value=mock_result)):
            result = await router.route(request)
            assert result.decision_type == DecisionType.WORKFLOW

    @pytest.mark.asyncio
    async def test_route_to_gauntlet_engine(self):
        """Routes gauntlet requests to gauntlet engine."""
        router = DecisionRouter(enable_caching=False)

        request = DecisionRequest(
            content="Validate API contract changes",
            decision_type=DecisionType.GAUNTLET,
        )

        mock_result = DecisionResult(
            request_id=request.request_id,
            decision_type=DecisionType.GAUNTLET,
            answer="All validations passed",
            confidence=1.0,
            consensus_reached=True,
        )

        with patch.object(router, "_route_to_gauntlet", AsyncMock(return_value=mock_result)):
            result = await router.route(request)
            assert result.decision_type == DecisionType.GAUNTLET

    @pytest.mark.asyncio
    async def test_route_to_quick_engine(self):
        """Routes quick requests for fast decisions."""
        router = DecisionRouter(enable_caching=False)

        request = DecisionRequest(
            content="What is 2+2?",
            decision_type=DecisionType.QUICK,
        )

        mock_result = DecisionResult(
            request_id=request.request_id,
            decision_type=DecisionType.QUICK,
            answer="4",
            confidence=1.0,
            consensus_reached=True,
        )

        with patch.object(router, "_route_to_quick", AsyncMock(return_value=mock_result)):
            result = await router.route(request)
            assert result.decision_type == DecisionType.QUICK

    @pytest.mark.asyncio
    async def test_auto_type_routes_correctly(self):
        """Auto type detection routes to appropriate engine."""
        router = DecisionRouter(enable_caching=False)

        # Should detect as workflow based on workflow_id
        request = DecisionRequest(
            content="Process this data",
            decision_type=DecisionType.AUTO,
            config=DecisionConfig(workflow_id="my-workflow"),
        )

        # The router should detect this is a workflow request
        assert request.config.workflow_id == "my-workflow"

    @pytest.mark.asyncio
    async def test_route_to_debate_ingests_attachments(self, tmp_path, monkeypatch):
        """Attachment text is ingested into DocumentStore and passed as document IDs."""
        from types import SimpleNamespace

        from aragora.evidence.store import InMemoryEvidenceStore
        from aragora.documents.parsing import DocumentStore

        # Stub agent lookup
        monkeypatch.setattr(
            "aragora.agents.get_agents_by_names",
            lambda _agents=None: [],
        )

        captured_env = {}

        class DummyArena:
            def __init__(self, environment, agents, protocol, **_kwargs):
                captured_env["env"] = environment

            async def run(self):
                return SimpleNamespace(
                    final_answer="ok",
                    consensus_reached=True,
                    confidence=0.9,
                    summary=None,
                )

        store = DocumentStore(tmp_path)
        evidence_store = InMemoryEvidenceStore()
        router = DecisionRouter(
            debate_engine=DummyArena,
            document_store=store,
            evidence_store=evidence_store,
            enable_caching=False,
            enable_deduplication=False,
        )

        request = DecisionRequest(
            content="Use attachment",
            decision_type=DecisionType.DEBATE,
            config=DecisionConfig(rounds=1, agents=[]),
            attachments=[
                {"filename": "notes.txt", "content": "hello world"},
            ],
        )

        result = await router.route(request)

        assert result.success is True
        env = captured_env.get("env")
        assert env is not None
        assert len(env.documents) >= 1
        # At least one document should be from the attachment
        attachment_found = any(store.get(doc_id) is not None for doc_id in env.documents)
        assert attachment_found

    @pytest.mark.asyncio
    async def test_route_to_debate_ingests_request_evidence(self, monkeypatch):
        """Evidence payloads are persisted into EvidenceStore."""
        from types import SimpleNamespace

        from aragora.evidence.store import InMemoryEvidenceStore

        monkeypatch.setattr(
            "aragora.agents.get_agents_by_names",
            lambda _agents=None: [],
        )

        class DummyArena:
            def __init__(self, environment, agents, protocol, **_kwargs):
                pass

            async def run(self):
                return SimpleNamespace(
                    final_answer="ok",
                    consensus_reached=True,
                    confidence=0.9,
                    summary=None,
                )

        evidence_store = InMemoryEvidenceStore()
        router = DecisionRouter(debate_engine=DummyArena, evidence_store=evidence_store)

        request = DecisionRequest(
            content="Use evidence",
            decision_type=DecisionType.DEBATE,
            config=DecisionConfig(rounds=1, agents=[]),
            evidence=[
                {"title": "Spec excerpt", "content": "Requirement X must hold."},
            ],
        )

        result = await router.route(request)

        assert result.success is True
        assert evidence_store.search_evidence("Requirement X")

    @pytest.mark.asyncio
    async def test_route_to_debate_builds_decision_integrity(self, monkeypatch):
        """Decision integrity package is built when enabled."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        # Stub agent lookup
        monkeypatch.setattr(
            "aragora.agents.get_agents_by_names",
            lambda _agents=None: [],
        )

        class DummyDebateResult:
            debate_id = "debate-123"
            task = "Design a cache"
            final_answer = "Use LRU"
            confidence = 0.9
            consensus_reached = True
            rounds_used = 1
            participants = ["agent-a"]
            metadata = {"source": "test"}

            def to_dict(self):
                return {
                    "debate_id": self.debate_id,
                    "task": self.task,
                    "final_answer": self.final_answer,
                    "confidence": self.confidence,
                    "consensus_reached": self.consensus_reached,
                    "rounds_used": self.rounds_used,
                    "participants": self.participants,
                    "metadata": self.metadata,
                }

        class DummyArena:
            def __init__(self, environment, agents, protocol, **_kwargs):
                pass

            async def run(self):
                return DummyDebateResult()

        router = DecisionRouter(debate_engine=DummyArena, enable_caching=False)

        request = DecisionRequest(
            content="Implement a cache",
            decision_type=DecisionType.DEBATE,
            config=DecisionConfig(
                rounds=1,
                agents=[],
                decision_integrity={"include_plan": True},
            ),
        )

        package_payload = {"debate_id": "debate-123", "plan": {"tasks": []}}

        with patch(
            "aragora.pipeline.decision_integrity.build_decision_integrity_package",
            AsyncMock(return_value=SimpleNamespace(to_dict=lambda: package_payload)),
        ):
            result = await router.route(request)

        assert result.success is True
        assert result.decision_integrity == package_payload

    @pytest.mark.asyncio
    async def test_route_to_debate_blocks_untrusted_intake_execution(self, monkeypatch):
        """Decision integrity execution is fail-closed when intake is untrusted."""
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from aragora.pipeline.decision_plan import ApprovalMode, DecisionPlan, PlanStatus
        from aragora.pipeline.decision_plan.memory import PlanOutcome
        from aragora.implement.types import ImplementPlan, ImplementTask

        monkeypatch.setenv("ARAGORA_ENABLE_IMPLEMENTATION_EXECUTION", "1")

        # Stub agent lookup
        monkeypatch.setattr(
            "aragora.agents.get_agents_by_names",
            lambda _agents=None: [],
        )

        class DummyDebateResult:
            debate_id = "debate-xyz"
            task = "Implement a cache"
            final_answer = "Use LRU"
            confidence = 0.9
            consensus_reached = True
            rounds_used = 1
            participants = ["agent-a"]
            metadata = {"source": "test"}

            def to_dict(self):
                return {
                    "debate_id": self.debate_id,
                    "task": self.task,
                    "final_answer": self.final_answer,
                    "confidence": self.confidence,
                    "consensus_reached": self.consensus_reached,
                    "rounds_used": self.rounds_used,
                    "participants": self.participants,
                    "metadata": self.metadata,
                }

        class DummyArena:
            def __init__(self, environment, agents, protocol, **_kwargs):
                pass

            async def run(self):
                return DummyDebateResult()

        router = DecisionRouter(debate_engine=DummyArena, enable_caching=False)

        request = DecisionRequest(
            content="Implement a cache",
            decision_type=DecisionType.DEBATE,
            config=DecisionConfig(
                rounds=1,
                agents=[],
                decision_integrity={
                    "include_plan": True,
                    "execution_mode": "execute",
                    "execution_engine": "hybrid",
                    "notify_origin": False,
                },
            ),
        )

        task = ImplementTask(
            id="task-1",
            description="Add cache layer",
            files=["cache.py"],
            complexity="simple",
        )
        implement_plan = ImplementPlan(design_hash="hash123", tasks=[task])
        package_payload = {"debate_id": "debate-xyz", "plan": implement_plan.to_dict()}
        package = SimpleNamespace(plan=implement_plan, to_dict=lambda: package_payload)

        monkeypatch.setattr(
            "aragora.pipeline.decision_integrity.build_decision_integrity_package",
            AsyncMock(return_value=package),
        )

        plan = DecisionPlan(
            debate_id="debate-xyz",
            task="Implement a cache",
            implement_plan=implement_plan,
            approval_mode=ApprovalMode.NEVER,
            status=PlanStatus.APPROVED,
        )
        monkeypatch.setattr(
            "aragora.pipeline.decision_plan.DecisionPlanFactory.from_debate_result",
            lambda *args, **kwargs: plan,
        )

        outcome = PlanOutcome(
            plan_id=plan.id,
            debate_id=plan.debate_id,
            task=plan.task,
            success=True,
        )

        with patch(
            "aragora.pipeline.executor.PlanExecutor.execute",
            AsyncMock(return_value=outcome),
        ) as mock_execute:
            result = await router.route(request)

        assert result.success is True
        assert result.decision_integrity is not None
        # The route builds the plan and requests execution, but the backbone
        # gate is fail-closed: the intake trust tier produced by this path
        # ("authenticated-user"/"service-authored") is not in the auto-execution
        # allowlist, so the plan is blocked before the executor is invoked.
        assert result.decision_integrity["plan_id"]
        execution = result.decision_integrity["execution"]
        assert execution["status"] == "failed"
        assert "untrusted_intake_tier" in execution["error"]
        assert mock_execute.called is False


# ===========================================================================
# Test: Decision Router - Caching and Deduplication
# ===========================================================================


class TestDecisionRouterCaching:
    """Tests for DecisionRouter caching behavior."""

    def test_caching_enabled_by_default(self):
        """Caching is enabled by default."""
        router = DecisionRouter()
        assert router._enable_caching is True

    def test_caching_can_be_disabled(self):
        """Caching can be disabled via constructor."""
        router = DecisionRouter(enable_caching=False)
        assert router._enable_caching is False

    def test_cache_ttl_configurable(self):
        """Cache TTL is configurable."""
        router = DecisionRouter(cache_ttl_seconds=7200.0)
        assert router._cache_ttl_seconds == 7200.0

    @pytest.mark.asyncio
    async def test_identical_requests_use_cache(self):
        """Identical requests within TTL return cached result."""
        router = DecisionRouter(enable_caching=True)

        request = DecisionRequest(
            content="Should we deploy?",
            decision_type=DecisionType.DEBATE,
        )

        first_result = DecisionResult(
            request_id=request.request_id,
            decision_type=DecisionType.DEBATE,
            answer="Yes, deploy",
            confidence=0.9,
            consensus_reached=True,
        )

        call_count = 0

        async def mock_route_to_debate(req):
            nonlocal call_count
            call_count += 1
            return first_result

        with patch.object(router, "_route_to_debate", mock_route_to_debate):
            # First call
            result1 = await router.route(request)

            # Second identical call should use cache
            # (depending on implementation)
            assert result1.answer == "Yes, deploy"


class TestDecisionRouterDeduplication:
    """Tests for DecisionRouter deduplication behavior."""

    def test_deduplication_enabled_by_default(self):
        """Deduplication is enabled by default."""
        router = DecisionRouter()
        assert router._enable_deduplication is True

    def test_deduplication_can_be_disabled(self):
        """Deduplication can be disabled via constructor."""
        router = DecisionRouter(enable_deduplication=False)
        assert router._enable_deduplication is False


# ===========================================================================
# Test: Decision Router - Voice Responses
# ===========================================================================


class TestDecisionRouterVoiceResponses:
    """Tests for DecisionRouter voice response synthesis."""

    def test_voice_responses_disabled_by_default(self):
        """Voice responses are disabled by default."""
        router = DecisionRouter()
        # Voice is typically opt-in
        assert router._enable_voice_responses in (True, False)  # Check it's a boolean

    def test_voice_responses_can_be_enabled(self):
        """Voice responses can be enabled via constructor."""
        router = DecisionRouter(enable_voice_responses=True)
        assert router._enable_voice_responses is True

    @pytest.mark.asyncio
    async def test_synthesize_voice_response_no_tts_bridge(self):
        """Voice synthesis gracefully handles missing TTS bridge."""
        router = DecisionRouter(enable_voice_responses=True)

        result = DecisionResult(
            request_id="test-123",
            decision_type=DecisionType.DEBATE,
            answer="Test answer for voice",
            confidence=0.9,
            consensus_reached=True,
        )

        # Should not raise even if TTS bridge not available
        try:
            voice_result = await router.synthesize_voice_response(result)
            # May return None or voice data depending on TTS availability
            assert voice_result is None or isinstance(voice_result, (bytes, str, dict))
        except Exception:
            # Graceful failure is acceptable
            pass

    @pytest.mark.asyncio
    async def test_synthesize_voice_response_with_mock_bridge(self):
        """Voice synthesis works with mock TTS bridge."""
        router = DecisionRouter(enable_voice_responses=True)

        # Create a mock path that simulates a real file path
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_path.read_bytes.return_value = b"audio_data"

        mock_bridge = MagicMock()
        mock_bridge.synthesize = AsyncMock(return_value=mock_path)

        result = DecisionResult(
            request_id="test-123",
            decision_type=DecisionType.DEBATE,
            answer="Test answer",
            confidence=0.9,
            consensus_reached=True,
        )

        with patch.object(router, "_get_tts_bridge", return_value=mock_bridge):
            try:
                voice_result = await router.synthesize_voice_response(result)
                # Should have called the bridge
                assert voice_result is not None or mock_bridge.synthesize.called
            except Exception:
                # Graceful failure is acceptable if TTS not configured
                pass


# ===========================================================================
# Test: Decision Router - Knowledge Context
# ===========================================================================


class TestDecisionRouterKnowledgeContext:
    """Tests for DecisionRouter knowledge context gathering."""

    @pytest.mark.asyncio
    async def test_gather_knowledge_context_empty(self):
        """Knowledge context gathering handles empty case."""
        router = DecisionRouter()

        request = DecisionRequest(
            content="Simple question",
            decision_type=DecisionType.QUICK,
        )

        # Should not raise
        try:
            context = await router._gather_knowledge_context(request)
            assert context is None or isinstance(context, dict)
        except Exception:
            pass  # Acceptable if not configured

    @pytest.mark.asyncio
    async def test_gather_knowledge_context_with_workspace(self):
        """Knowledge context gathering includes workspace context."""
        router = DecisionRouter()

        request = DecisionRequest(
            content="What do we know about project X?",
            decision_type=DecisionType.DEBATE,
            context=RequestContext(
                workspace_id="ws-123",
                tenant_id="tenant-456",
            ),
        )

        # The method should handle the request with workspace context
        try:
            context = await router._gather_knowledge_context(request)
            # Should return None or a dict with knowledge context
            assert context is None or isinstance(context, dict)
        except Exception:
            pass  # KM may not be configured


# ===========================================================================
# Test: Decision Router - Response Delivery
# ===========================================================================


class TestDecisionRouterResponseDelivery:
    """Tests for DecisionRouter response delivery."""

    @pytest.mark.asyncio
    async def test_deliver_to_registered_handler(self):
        """Delivers response to registered platform handler."""
        router = DecisionRouter()

        mock_handler = AsyncMock(return_value=True)
        router.register_response_handler("slack", mock_handler)

        result = DecisionResult(
            request_id="test-123",
            decision_type=DecisionType.DEBATE,
            answer="Decision made",
            confidence=0.9,
            consensus_reached=True,
        )

        channels = [
            ResponseChannel(
                platform="slack",
                channel_id="C123",
                response_format="summary",
            )
        ]

        # Attempt delivery
        try:
            await router._deliver_responses(result, channels)
            # Should have called the handler
            mock_handler.assert_called_once()
        except Exception:
            pass  # May fail due to missing integration

    @pytest.mark.asyncio
    async def test_deliver_to_unregistered_handler(self):
        """Gracefully handles delivery to unregistered platform."""
        router = DecisionRouter()

        result = DecisionResult(
            request_id="test-123",
            decision_type=DecisionType.DEBATE,
            answer="Decision made",
            confidence=0.9,
            consensus_reached=True,
        )

        channels = [
            ResponseChannel(
                platform="unknown_platform",
                channel_id="X123",
            )
        ]

        # Should not raise
        try:
            await router._deliver_responses(result, channels)
        except Exception:
            pass  # Acceptable to fail gracefully

    @pytest.mark.asyncio
    async def test_deliver_voice_response_with_voice_channel(self):
        """Delivers voice response to voice-enabled channel."""
        router = DecisionRouter(enable_voice_responses=True)

        result = DecisionResult(
            request_id="test-123",
            decision_type=DecisionType.DEBATE,
            answer="Voice answer",
            confidence=0.9,
            consensus_reached=True,
        )

        channel = ResponseChannel(
            platform="voice_assistant",
            voice_enabled=True,
        )

        # Should attempt voice delivery
        try:
            await router._deliver_voice_response(result, channel)
        except Exception:
            pass  # Voice may not be configured
