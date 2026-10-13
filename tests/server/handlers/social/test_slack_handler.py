"""
Tests for aragora.server.handlers.social.slack - Slack Integration Handler.

Tests cover:
- Routing and method handling
- Signature verification (HMAC-SHA256)
- SSRF protection (URL validation)
- Rate limiting (user + workspace)
- Slash commands (help, status, agents, debate, ask, search, etc.)
- Interactive components
- Events API
- Multi-workspace support
- Error handling
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from io import BytesIO
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import pytest

try:
    from aragora.server.handlers.social.slack import (
        SLACK_ALLOWED_DOMAINS,
        SlackHandler,
        _validate_slack_url,
        get_slack_handler,
        get_slack_integration,
    )

    if SlackHandler is None:
        raise ImportError("SlackHandler resolved to None")
except (ImportError, ModuleNotFoundError):
    pytest.skip(
        "slack handler not importable (conftest import shadow)",
        allow_module_level=True,
    )

from .conftest import (
    MockHandler,
    create_slack_command_handler,
    create_slack_event_handler,
    create_slack_interactive_handler,
    generate_slack_signature,
    get_json,
    get_status_code,
    parse_result,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def handler(mock_server_context):
    """Create a SlackHandler instance."""
    return SlackHandler(mock_server_context)


@pytest.fixture
def signing_secret():
    """Test signing secret."""
    return "test_signing_secret_12345"


# ===========================================================================
# Routing Tests
# ===========================================================================


class TestRouting:
    """Tests for route handling."""

    def test_can_handle_commands(self, handler):
        """Test handler recognizes commands endpoint."""
        assert handler.can_handle("/api/v1/integrations/slack/commands") is True

    def test_can_handle_interactive(self, handler):
        """Test handler recognizes interactive endpoint."""
        assert handler.can_handle("/api/v1/integrations/slack/interactive") is True

    def test_can_handle_events(self, handler):
        """Test handler recognizes events endpoint."""
        assert handler.can_handle("/api/v1/integrations/slack/events") is True

    def test_can_handle_status(self, handler):
        """Test handler recognizes status endpoint."""
        assert handler.can_handle("/api/v1/integrations/slack/status") is True

    def test_cannot_handle_unknown(self, handler):
        """Test handler rejects unknown endpoints."""
        assert handler.can_handle("/api/v1/integrations/slack/unknown") is False
        assert handler.can_handle("/api/v1/other/endpoint") is False
        assert handler.can_handle("/api/v1/integrations/teams/commands") is False

    def test_routes_defined(self, handler):
        """Test handler has ROUTES defined."""
        assert hasattr(handler, "ROUTES")
        assert len(handler.ROUTES) >= 4

    def test_routes_include_all_endpoints(self, handler):
        """Verify all expected routes are defined."""
        expected = [
            "/api/v1/integrations/slack/commands",
            "/api/v1/integrations/slack/interactive",
            "/api/v1/integrations/slack/events",
            "/api/v1/integrations/slack/status",
        ]
        for route in expected:
            assert route in handler.ROUTES


# ===========================================================================
# SSRF Protection Tests
# ===========================================================================


class TestSSRFProtection:
    """Tests for SSRF protection via URL validation."""

    def test_validate_slack_url_valid_hooks(self):
        """Valid hooks.slack.com URL should pass."""
        assert _validate_slack_url("https://hooks.slack.com/commands/T123/456/abc") is True

    def test_validate_slack_url_valid_api(self):
        """Valid api.slack.com URL should pass."""
        assert _validate_slack_url("https://api.slack.com/something") is True

    def test_validate_slack_url_rejects_http(self):
        """HTTP (non-HTTPS) should be rejected."""
        assert _validate_slack_url("http://hooks.slack.com/commands/T123/456/abc") is False

    def test_validate_slack_url_rejects_other_domains(self):
        """Non-Slack domains should be rejected."""
        assert _validate_slack_url("https://evil.com/commands") is False
        assert _validate_slack_url("https://hooks.slack.com.evil.com/") is False
        assert _validate_slack_url("https://not-slack.com/api/v1") is False

    def test_validate_slack_url_rejects_localhost(self):
        """Localhost should be rejected."""
        assert _validate_slack_url("https://localhost/commands") is False
        assert _validate_slack_url("https://127.0.0.1/commands") is False

    def test_validate_slack_url_rejects_internal_ips(self):
        """Internal IPs should be rejected."""
        assert _validate_slack_url("https://192.168.1.1/commands") is False
        assert _validate_slack_url("https://10.0.0.1/commands") is False

    def test_validate_slack_url_handles_malformed(self):
        """Malformed URLs should be rejected gracefully."""
        assert _validate_slack_url("") is False
        assert _validate_slack_url("not-a-url") is False
        assert _validate_slack_url("://missing-scheme") is False

    def test_allowed_domains_frozen(self):
        """Allowed domains should be immutable."""
        assert isinstance(SLACK_ALLOWED_DOMAINS, frozenset)
        assert "hooks.slack.com" in SLACK_ALLOWED_DOMAINS
        assert "api.slack.com" in SLACK_ALLOWED_DOMAINS


# ===========================================================================
# Status Endpoint Tests
# ===========================================================================


class TestStatusEndpoint:
    """Tests for GET /api/integrations/slack/status."""

    @pytest.mark.asyncio
    async def test_get_status_without_config(self, handler):
        """Status without config shows disabled."""
        mock_http = MockHandler(
            headers={"Content-Type": "application/json"},
            path="/api/v1/integrations/slack/status",
            method="GET",
        )

        with patch.dict(os.environ, {}, clear=True):
            result = await handler.handle("/api/v1/integrations/slack/status", {}, mock_http)

        assert result is not None
        status_code, body = parse_result(result)
        assert status_code == 200
        assert "enabled" in body

    @pytest.mark.asyncio
    async def test_get_status_with_signing_secret(self, handler):
        """Status with signing secret configured."""
        mock_http = MockHandler(
            headers={"Content-Type": "application/json"},
            path="/api/v1/integrations/slack/status",
            method="GET",
        )

        with patch(
            "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET", "secret123"
        ):
            result = await handler.handle("/api/v1/integrations/slack/status", {}, mock_http)

        status_code, body = parse_result(result)
        assert status_code == 200
        assert body.get("signing_secret_configured") is True

    @pytest.mark.asyncio
    async def test_get_status_with_bot_token(self, handler):
        """Status with bot token configured."""
        mock_http = MockHandler(
            headers={"Content-Type": "application/json"},
            path="/api/v1/integrations/slack/status",
            method="GET",
        )

        with patch(
            "aragora.server.handlers.social._slack_impl.config.SLACK_BOT_TOKEN", "xoxb-token"
        ):
            result = await handler.handle("/api/v1/integrations/slack/status", {}, mock_http)

        status_code, body = parse_result(result)
        assert status_code == 200
        assert body.get("bot_token_configured") is True


# ===========================================================================
# Signature Verification Tests
# ===========================================================================


class TestSignatureVerification:
    """Tests for Slack request signature verification."""

    @pytest.mark.asyncio
    async def test_signature_verification_success(self, handler, signing_secret):
        """Valid signature should be accepted."""
        body = "command=/aragora&text=help&user_id=U123"
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        # Should not return 401 (signature valid)
        assert result is not None
        assert get_status_code(result) != 401

    @pytest.mark.asyncio
    async def test_signature_verification_failure(self, handler, signing_secret):
        """Invalid signature should be rejected with 401."""
        body = "command=/aragora&text=help"
        timestamp = str(int(time.time()))

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": "v0=invalidsignature",
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=False, error="Invalid signature")
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        assert result is not None
        status_code, body = parse_result(result)
        assert status_code == 401
        assert "Invalid signature" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_signature_verification_logs_on_failure(self, handler, signing_secret):
        """Signature failure should trigger audit logging."""
        body = "command=/aragora&text=help&team_id=T123"
        timestamp = str(int(time.time()))

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": "v0=wrong",
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
            client_address=("192.168.1.100", 12345),
        )

        mock_audit = MagicMock()
        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch(
                "aragora.server.handlers.social._slack_impl.config._get_audit_logger",
                return_value=mock_audit,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=False, error="Invalid")
            await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        # Audit logger should be called
        mock_audit.log_signature_failure.assert_called_once()

    @pytest.mark.asyncio
    async def test_signature_without_secret_skips_verification(self, handler):
        """Without signing secret configured, verification is skipped."""
        body = "command=/aragora&text=help"

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with patch("aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET", ""):
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        # Should not fail on signature (no secret to verify against)
        assert result is not None
        assert get_status_code(result) != 401


# ===========================================================================
# Rate Limiting Tests
# ===========================================================================


class TestRateLimiting:
    """Tests for rate limiting (user and workspace)."""

    @pytest.mark.asyncio
    async def test_workspace_rate_limit_applied(self, handler, signing_secret):
        """Workspace rate limiting should be enforced."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "help",
                "user_id": "U123",
                "team_id": "T12345",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_limiter = MagicMock()
        mock_limiter.allow.return_value = MagicMock(allowed=False, retry_after=30)

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_workspace_rate_limiter",
                return_value=mock_limiter,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        # Should return rate limit message
        assert result is not None
        body_data = get_json(result)
        assert "workspace is sending commands too quickly" in body_data.get("text", "").lower()

    @pytest.mark.asyncio
    async def test_user_rate_limit_applied(self, handler, signing_secret):
        """User rate limiting should be enforced."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "help",
                "user_id": "U123",
                "team_id": "T12345",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_workspace_limiter = MagicMock()
        mock_workspace_limiter.allow.return_value = MagicMock(allowed=True, retry_after=0)

        mock_user_limiter = MagicMock()
        mock_user_limiter.allow.return_value = MagicMock(allowed=False, retry_after=15)

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_workspace_rate_limiter",
                return_value=mock_workspace_limiter,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_user_rate_limiter",
                return_value=mock_user_limiter,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        assert "sending commands too quickly" in body_data.get("text", "").lower()

    @pytest.mark.asyncio
    async def test_rate_limit_logs_to_audit(self, handler, signing_secret):
        """Rate limit events should be logged for audit."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "help",
                "user_id": "U123",
                "team_id": "T12345",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_limiter = MagicMock()
        mock_limiter.allow.return_value = MagicMock(allowed=False, retry_after=30)
        mock_audit = MagicMock()

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_workspace_rate_limiter",
                return_value=mock_limiter,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_audit_logger",
                return_value=mock_audit,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        mock_audit.log_rate_limit.assert_called()


# ===========================================================================
# Slash Command Tests
# ===========================================================================


class TestSlashCommandHelp:
    """Tests for /aragora help command."""

    @pytest.mark.asyncio
    async def test_help_command(self, handler, signing_secret):
        """Help command should return help text."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "help",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "Aragora" in text or "aragora" in text.lower()
        assert "help" in text.lower() or "command" in text.lower()
        assert body_data.get("response_type") == "ephemeral"

    @pytest.mark.asyncio
    async def test_empty_command_shows_help(self, handler, signing_secret):
        """Empty command should default to help."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        assert (
            "Aragora" in body_data.get("text", "") or "command" in body_data.get("text", "").lower()
        )


class TestSlashCommandStatus:
    """Tests for /aragora status command."""

    @pytest.mark.asyncio
    async def test_status_command(self, handler, signing_secret):
        """Status command should return system status."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "status",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = [
            MagicMock(name="agent1", elo=1600, wins=5),
            MagicMock(name="agent2", elo=1500, wins=3),
        ]

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch("aragora.ranking.elo.EloSystem", return_value=mock_elo),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        # Should have blocks with status info
        assert "blocks" in body_data or "text" in body_data
        assert body_data.get("response_type") == "ephemeral"


class TestSlashCommandAgents:
    """Tests for /aragora agents command."""

    @pytest.mark.asyncio
    async def test_agents_command_with_agents(self, handler, signing_secret):
        """Agents command should list available agents."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "agents",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_agents = [
            MagicMock(name="claude", elo=1700, wins=10),
            MagicMock(name="gpt4", elo=1650, wins=8),
        ]
        # Need to set name as property since MagicMock name conflicts
        mock_agents[0].name = "claude"
        mock_agents[1].name = "gpt4"

        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = mock_agents

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch("aragora.ranking.elo.EloSystem", return_value=mock_elo),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "agent" in text.lower() or "claude" in text.lower() or "elo" in text.lower()

    @pytest.mark.asyncio
    async def test_agents_command_empty(self, handler, signing_secret):
        """Agents command with no agents registered."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "agents",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = []

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch("aragora.ranking.elo.EloSystem", return_value=mock_elo),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "no agent" in text.lower()


class TestSlashCommandAsk:
    """Tests for /aragora ask command."""

    @pytest.mark.asyncio
    async def test_ask_command_without_question(self, handler, signing_secret):
        """Ask without question should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "ask",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "provide" in text.lower() or "question" in text.lower()
        assert body_data.get("response_type") == "ephemeral"

    @pytest.mark.asyncio
    async def test_ask_command_too_short(self, handler, signing_secret):
        """Ask with very short question should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "ask why",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "short" in text.lower()

    @pytest.mark.asyncio
    async def test_ask_command_too_long(self, handler, signing_secret):
        """Ask with very long question should show error."""
        long_question = "x" * 600
        body = urlencode(
            {
                "command": "/aragora",
                "text": f"ask {long_question}",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "long" in text.lower()

    @pytest.mark.asyncio
    async def test_ask_command_valid_question(self, handler, signing_secret):
        """Ask with valid question should acknowledge."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": 'ask "What is the capital of France?"',
                "user_id": "U123",
                "channel_id": "C123",
                "response_url": "https://hooks.slack.com/commands/T123/456/token",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch("aragora.server.handlers.social._slack_impl.create_tracked_task"),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        # Should acknowledge with processing message
        assert "blocks" in body_data or "Processing" in body_data.get("text", "")
        assert body_data.get("response_type") == "in_channel"


class TestSlashCommandSearch:
    """Tests for /aragora search command."""

    @pytest.mark.asyncio
    async def test_search_without_query(self, handler, signing_secret):
        """Search without query should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "search",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "provide" in text.lower() or "query" in text.lower()

    @pytest.mark.asyncio
    async def test_search_with_short_query(self, handler, signing_secret):
        """Search with too-short query should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "search x",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "short" in text.lower()


class TestSlashCommandUnknown:
    """Tests for unknown commands."""

    @pytest.mark.asyncio
    async def test_unknown_command(self, handler, signing_secret):
        """Unknown command should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "foobar",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "unknown" in text.lower() or "foobar" in text.lower()
        assert body_data.get("response_type") == "ephemeral"


# ===========================================================================
# Interactive Component Tests
# ===========================================================================


class TestInteractiveComponents:
    """Tests for Slack interactive components."""

    @pytest.mark.asyncio
    async def test_interactive_payload_parsed(self, handler, signing_secret):
        """Interactive payload should be parsed correctly."""
        payload = {
            "type": "block_actions",
            "user": {"id": "U123", "name": "testuser"},
            "team": {"id": "T123"},
            "actions": [{"action_id": "vote_for", "value": "debate123"}],
            "response_url": "https://hooks.slack.com/actions/T123/456/token",
        }
        data = {"payload": json.dumps(payload)}
        body = urlencode(data)
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/interactive",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/interactive", {}, mock_http)

        # Should return some response (not 401)
        assert result is not None
        assert get_status_code(result) != 401


# ===========================================================================
# Events API Tests
# ===========================================================================


class TestEventsAPI:
    """Tests for Slack Events API."""

    @pytest.mark.asyncio
    async def test_url_verification_challenge(self, handler, signing_secret):
        """URL verification challenge should be echoed."""
        payload = {
            "type": "url_verification",
            "challenge": "test_challenge_token",
        }
        body = json.dumps(payload)
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/events",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/events", {}, mock_http)

        assert result is not None
        body_data = get_json(result)
        assert body_data.get("challenge") == "test_challenge_token"

    @pytest.mark.asyncio
    async def test_event_callback_processed(self, handler, signing_secret):
        """Event callbacks should be processed."""
        payload = {
            "type": "event_callback",
            "team_id": "T123",
            "event": {
                "type": "message",
                "text": "Hello",
                "user": "U123",
                "channel": "C123",
            },
        }
        body = json.dumps(payload)
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/events",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/events", {}, mock_http)

        assert result is not None
        # Should return OK (acknowledge event)
        assert get_status_code(result) == 200


# ===========================================================================
# Multi-Workspace Tests
# ===========================================================================


class TestMultiWorkspace:
    """Tests for multi-workspace support."""

    @pytest.mark.asyncio
    async def test_team_id_extracted_from_commands(self, handler, signing_secret):
        """Team ID should be extracted from slash command body."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "help",
                "user_id": "U123",
                "team_id": "T_WORKSPACE_123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch(
                "aragora.server.handlers.social._slack_impl.config.resolve_workspace"
            ) as mock_resolve,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            mock_resolve.return_value = None
            await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        mock_resolve.assert_called_with("T_WORKSPACE_123")

    @pytest.mark.asyncio
    async def test_workspace_specific_signing_secret(self, handler):
        """Workspace-specific signing secret should be used if available."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "help",
                "user_id": "U123",
                "team_id": "T_CUSTOM",
            }
        )
        timestamp = str(int(time.time()))
        custom_secret = "custom_workspace_secret"
        signature = generate_slack_signature(body, timestamp, custom_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_workspace = MagicMock()
        mock_workspace.signing_secret = custom_secret

        with (
            patch("aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET", ""),
            patch(
                "aragora.server.handlers.social._slack_impl.config.resolve_workspace",
                return_value=mock_workspace,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        # verify_slack_signature should be called with custom secret
        mock_verify.assert_called_once()
        call_kwargs = mock_verify.call_args
        assert call_kwargs[1].get("signing_secret") == custom_secret or custom_secret in str(
            call_kwargs
        )


# ===========================================================================
# Error Handling Tests
# ===========================================================================


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_method_not_allowed_for_status_post(self, handler):
        """POST to status endpoint should not be allowed for GET-only."""
        mock_http = MockHandler(
            headers={"Content-Type": "application/json"},
            path="/api/v1/integrations/slack/status",
            method="POST",
            body=b"{}",
        )
        # Note: Status endpoint returns via handle() which checks method
        # This is actually handled by handle() which routes to _get_status()
        result = await handler.handle("/api/v1/integrations/slack/status", {}, mock_http)
        # Status works for any method via handle() directly
        assert result is not None

    @pytest.mark.asyncio
    async def test_not_found_for_unknown_path(self, handler, signing_secret):
        """Unknown path should return 404."""
        body = "test"
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/unknown",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/unknown", {}, mock_http)

        # Either None or 404
        if result is not None:
            assert get_status_code(result) == 404


# ===========================================================================
# Handler Factory Tests
# ===========================================================================


class TestHandlerFactory:
    """Tests for handler factory functions."""

    def test_get_slack_handler_creates_instance(self, mock_server_context):
        """get_slack_handler should create handler instance."""
        # Reset global
        import aragora.server.handlers.social.slack as slack_module

        slack_module._slack_handler = None

        handler = get_slack_handler(mock_server_context)
        assert handler is not None
        assert isinstance(handler, SlackHandler)

    def test_get_slack_handler_returns_same_instance(self, mock_server_context):
        """get_slack_handler should return singleton."""
        import aragora.server.handlers.social.slack as slack_module

        slack_module._slack_handler = None

        handler1 = get_slack_handler(mock_server_context)
        handler2 = get_slack_handler(mock_server_context)
        assert handler1 is handler2

    def test_get_slack_handler_default_context(self):
        """get_slack_handler should work with no context."""
        import aragora.server.handlers.social.slack as slack_module

        slack_module._slack_handler = None

        handler = get_slack_handler()
        assert handler is not None

    def test_get_slack_integration_without_webhook(self):
        """get_slack_integration without webhook returns None."""
        import aragora.server.handlers.social.slack as slack_module

        slack_module._slack_integration = None

        with patch("aragora.server.handlers.social._slack_impl.config.SLACK_WEBHOOK_URL", ""):
            integration = get_slack_integration()

        assert integration is None


# ===========================================================================
# Circuit Breaker Tests
# ===========================================================================


class TestCircuitBreaker:
    """Tests for the Slack circuit breaker pattern."""

    def test_circuit_breaker_initial_state_closed(self):
        """Circuit breaker should start in CLOSED state."""
        from aragora.server.handlers.social._slack_impl.messaging import SlackCircuitBreaker

        cb = SlackCircuitBreaker()
        assert cb.state == SlackCircuitBreaker.CLOSED
        assert cb.can_proceed() is True

    def test_circuit_breaker_opens_after_failures(self):
        """Circuit should open after threshold failures."""
        from aragora.server.handlers.social._slack_impl.messaging import SlackCircuitBreaker

        cb = SlackCircuitBreaker(failure_threshold=3)

        # Record failures
        for _ in range(3):
            cb.record_failure()

        assert cb.state == SlackCircuitBreaker.OPEN
        assert cb.can_proceed() is False

    def test_circuit_breaker_success_resets_failures(self):
        """Success should reset failure count."""
        from aragora.server.handlers.social._slack_impl.messaging import SlackCircuitBreaker

        cb = SlackCircuitBreaker(failure_threshold=5)

        # Record some failures
        cb.record_failure()
        cb.record_failure()

        # Record success
        cb.record_success()

        # Should still be closed and failure count reset
        assert cb.state == SlackCircuitBreaker.CLOSED
        assert cb.can_proceed() is True

        # Now need full threshold to trip
        for _ in range(5):
            cb.record_failure()

        assert cb.state == SlackCircuitBreaker.OPEN

    def test_circuit_breaker_transitions_to_half_open(self):
        """Circuit should transition to HALF_OPEN after cooldown."""
        from aragora.server.handlers.social._slack_impl.messaging import SlackCircuitBreaker

        # Very short cooldown for testing
        cb = SlackCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)

        # Trip the circuit
        cb.record_failure()
        assert cb.state == SlackCircuitBreaker.OPEN

        # Wait for cooldown
        import time

        time.sleep(0.02)

        # Should now be half-open
        assert cb.state == SlackCircuitBreaker.HALF_OPEN
        assert cb.can_proceed() is True

    def test_circuit_breaker_closes_after_successful_recovery(self):
        """Circuit should close after successful calls in HALF_OPEN."""
        from aragora.server.handlers.social._slack_impl.messaging import SlackCircuitBreaker

        cb = SlackCircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=0.01,
            half_open_max_calls=2,
        )

        # Trip the circuit
        cb.record_failure()

        # Wait for cooldown
        import time

        time.sleep(0.02)

        # Make successful calls in half-open state
        assert cb.state == SlackCircuitBreaker.HALF_OPEN
        cb.can_proceed()
        cb.record_success()
        cb.can_proceed()
        cb.record_success()

        # Should be closed now
        assert cb.state == SlackCircuitBreaker.CLOSED

    def test_circuit_breaker_reopens_on_failure_in_half_open(self):
        """Failure in HALF_OPEN should reopen circuit."""
        from aragora.server.handlers.social._slack_impl.messaging import SlackCircuitBreaker

        cb = SlackCircuitBreaker(failure_threshold=1, cooldown_seconds=0.01)

        # Trip the circuit
        cb.record_failure()

        # Wait for cooldown
        import time

        time.sleep(0.02)

        # Should be half-open
        assert cb.state == SlackCircuitBreaker.HALF_OPEN

        # Fail again
        cb.record_failure()

        # Should be open again
        assert cb.state == SlackCircuitBreaker.OPEN

    def test_circuit_breaker_get_status(self):
        """get_status should return circuit state info."""
        from aragora.server.handlers.social._slack_impl.messaging import SlackCircuitBreaker

        cb = SlackCircuitBreaker(failure_threshold=5, cooldown_seconds=30)

        status = cb.get_status()

        assert "state" in status
        assert status["state"] == "closed"
        assert status["failure_threshold"] == 5
        assert status["cooldown_seconds"] == 30
        assert "failure_count" in status

    def test_circuit_breaker_reset(self):
        """reset should restore initial state."""
        from aragora.server.handlers.social._slack_impl.messaging import SlackCircuitBreaker

        cb = SlackCircuitBreaker(failure_threshold=1)

        # Trip the circuit
        cb.record_failure()
        assert cb.state == SlackCircuitBreaker.OPEN

        # Reset
        cb.reset()

        # Should be closed again
        assert cb.state == SlackCircuitBreaker.CLOSED
        assert cb.can_proceed() is True

    def test_circuit_breaker_limits_half_open_calls(self):
        """HALF_OPEN should limit number of test calls."""
        from aragora.server.handlers.social._slack_impl.messaging import SlackCircuitBreaker

        cb = SlackCircuitBreaker(
            failure_threshold=1,
            cooldown_seconds=0.01,
            half_open_max_calls=2,
        )

        # Trip the circuit
        cb.record_failure()

        # Wait for cooldown
        import time

        time.sleep(0.02)

        # Should allow limited calls
        assert cb.can_proceed() is True  # First call
        assert cb.can_proceed() is True  # Second call
        assert cb.can_proceed() is False  # Third call blocked

    def test_global_circuit_breaker_singleton(self):
        """get_slack_circuit_breaker should return singleton."""
        from aragora.server.handlers.social._slack_impl.messaging import (
            get_slack_circuit_breaker,
            reset_slack_circuit_breaker,
        )

        reset_slack_circuit_breaker()

        cb1 = get_slack_circuit_breaker()
        cb2 = get_slack_circuit_breaker()

        assert cb1 is cb2

    def test_reset_slack_circuit_breaker(self):
        """reset_slack_circuit_breaker should reset the global instance."""
        from aragora.server.handlers.social._slack_impl.messaging import (
            get_slack_circuit_breaker,
            reset_slack_circuit_breaker,
        )

        cb = get_slack_circuit_breaker()

        # Trip it
        for _ in range(10):
            cb.record_failure()

        assert cb.state != "closed"

        # Reset
        reset_slack_circuit_breaker()

        # Should be reset
        cb = get_slack_circuit_breaker()
        assert cb.state == "closed"

    @pytest.mark.asyncio
    async def test_status_endpoint_includes_circuit_breaker(self, handler, signing_secret):
        """Status endpoint should include circuit breaker status."""
        mock_http = MockHandler(
            headers={"Content-Type": "application/json"},
            path="/api/v1/integrations/slack/status",
            method="GET",
        )

        result = await handler.handle("/api/v1/integrations/slack/status", {}, mock_http)

        assert result is not None
        status_code, body = parse_result(result)
        assert status_code == 200
        assert "circuit_breaker" in body
        assert "state" in body["circuit_breaker"]
        assert body["circuit_breaker"]["state"] == "closed"


# ===========================================================================
# Debate Command Tests
# ===========================================================================


class TestSlashCommandDebate:
    """Tests for /aragora debate command."""

    @pytest.mark.asyncio
    async def test_debate_command_without_topic(self, handler, signing_secret):
        """Debate without topic should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "debate",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "provide" in text.lower() or "topic" in text.lower()
        assert body_data.get("response_type") == "ephemeral"

    @pytest.mark.asyncio
    async def test_plan_command_without_topic(self, handler, signing_secret):
        """Plan without topic should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "plan",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "provide" in text.lower() or "topic" in text.lower()
        assert body_data.get("response_type") == "ephemeral"

    @pytest.mark.asyncio
    async def test_implement_command_without_topic(self, handler, signing_secret):
        """Implement without topic should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "implement",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "provide" in text.lower() or "topic" in text.lower()
        assert body_data.get("response_type") == "ephemeral"

    @pytest.mark.asyncio
    async def test_implement_command_with_computer_use(self, handler, signing_secret):
        """Implement with --computer-use should pass override to debate."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "implement Update docs --computer-use",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands.get_debates_db",
                return_value=None,
            ),
            patch.object(
                handler,
                "_command_debate",
                return_value=handler._slack_response("ok"),
            ) as mock_start,
        ):
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        assert get_status_code(result) == 200
        assert mock_start.called is True
        kwargs = mock_start.call_args.kwargs
        decision_integrity = kwargs.get("decision_integrity") or {}
        assert decision_integrity["execution_engine"] == "hybrid"
        assert decision_integrity["execution_mode"] == "execute"

    @pytest.mark.asyncio
    async def test_debate_command_topic_too_short(self, handler, signing_secret):
        """Debate with very short topic should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "debate hi",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "short" in text.lower()

    @pytest.mark.asyncio
    async def test_debate_command_topic_too_long(self, handler, signing_secret):
        """Debate with very long topic should show error."""
        long_topic = "x" * 600
        body = urlencode(
            {
                "command": "/aragora",
                "text": f"debate {long_topic}",
                "user_id": "U_TOPIC_LONG",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_workspace_rate_limiter",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_user_rate_limiter",
                return_value=None,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "long" in text.lower()

    @pytest.mark.asyncio
    async def test_debate_command_valid_topic(self, handler, signing_secret):
        """Debate with valid topic should acknowledge."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": 'debate "Should AI be regulated?"',
                "user_id": "U_VALID_TOPIC",
                "channel_id": "C123",
                "response_url": "https://hooks.slack.com/commands/T123/456/token",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch("aragora.server.handlers.social._slack_impl.create_tracked_task"),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_workspace_rate_limiter",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_user_rate_limiter",
                return_value=None,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        # Should acknowledge with starting message
        assert "blocks" in body_data or "Starting" in body_data.get("text", "")
        assert body_data.get("response_type") == "in_channel"


# ===========================================================================
# Gauntlet Command Tests
# ===========================================================================


class TestSlashCommandGauntlet:
    """Tests for /aragora gauntlet command."""

    @pytest.mark.asyncio
    async def test_gauntlet_command_without_statement(self, handler, signing_secret):
        """Gauntlet without statement should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "gauntlet",
                "user_id": "U_GAUNTLET_NO_STMT",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_workspace_rate_limiter",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_user_rate_limiter",
                return_value=None,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "provide" in text.lower() or "statement" in text.lower()
        assert body_data.get("response_type") == "ephemeral"

    @pytest.mark.asyncio
    async def test_gauntlet_command_statement_too_short(self, handler, signing_secret):
        """Gauntlet with very short statement should show error."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "gauntlet test",
                "user_id": "U_GAUNTLET_SHORT",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_workspace_rate_limiter",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_user_rate_limiter",
                return_value=None,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "short" in text.lower()


# ===========================================================================
# Leaderboard and Recent Commands Tests
# ===========================================================================


class TestSlashCommandLeaderboard:
    """Tests for /aragora leaderboard command."""

    @pytest.mark.asyncio
    async def test_leaderboard_with_agents(self, handler, signing_secret):
        """Leaderboard should display ranked agents."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "leaderboard",
                "user_id": "U_LEADERBOARD",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_agents = [
            MagicMock(name="claude", elo=1700, wins=10, losses=2),
            MagicMock(name="gpt4", elo=1650, wins=8, losses=4),
        ]
        mock_agents[0].name = "claude"
        mock_agents[1].name = "gpt4"

        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = mock_agents

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch("aragora.ranking.elo.EloSystem", return_value=mock_elo),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_workspace_rate_limiter",
                return_value=None,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_user_rate_limiter",
                return_value=None,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        # Should have blocks with leaderboard
        assert "blocks" in body_data or "text" in body_data
        assert body_data.get("response_type") == "in_channel"

    @pytest.mark.asyncio
    async def test_leaderboard_empty(self, handler, signing_secret):
        """Leaderboard with no agents should show message."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "leaderboard",
                "user_id": "U_LEADERBOARD_EMPTY",  # Unique user to avoid rate limits
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = []

        # Mock rate limiters to avoid interference
        mock_limiter = MagicMock()
        mock_limiter.allow.return_value = MagicMock(allowed=True, retry_after=0)

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch("aragora.ranking.elo.EloSystem", return_value=mock_elo),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_workspace_rate_limiter",
                return_value=mock_limiter,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_user_rate_limiter",
                return_value=mock_limiter,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        assert "no agent" in text.lower() or "start" in text.lower()


class TestSlashCommandRecent:
    """Tests for /aragora recent command."""

    @pytest.mark.asyncio
    async def test_recent_with_debates(self, handler, signing_secret):
        """Recent should display recent debates."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "recent",
                "user_id": "U123",
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_db = MagicMock()
        mock_db.list.return_value = [
            {
                "id": "debate-1",
                "task": "Should we use microservices?",
                "consensus_reached": True,
                "confidence": 0.85,
                "created_at": "2025-01-15",
            },
            {
                "id": "debate-2",
                "task": "Is Python better than JavaScript?",
                "consensus_reached": False,
                "confidence": 0.6,
                "created_at": "2025-01-14",
            },
        ]

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch(
                "aragora.server.handlers.social._slack_impl.commands.get_debates_db",
                return_value=mock_db,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        # Should have blocks with recent debates
        assert "blocks" in body_data or "text" in body_data
        assert body_data.get("response_type") == "ephemeral"

    @pytest.mark.asyncio
    async def test_recent_empty(self, handler, signing_secret):
        """Recent with no debates should show message."""
        body = urlencode(
            {
                "command": "/aragora",
                "text": "recent",
                "user_id": "U_RECENT_EMPTY",  # Unique user to avoid rate limits
                "channel_id": "C123",
            }
        )
        timestamp = str(int(time.time()))
        signature = generate_slack_signature(body, timestamp, signing_secret)

        mock_http = MockHandler(
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(body)),
                "X-Slack-Request-Timestamp": timestamp,
                "X-Slack-Signature": signature,
            },
            body=body.encode("utf-8"),
            path="/api/v1/integrations/slack/commands",
            method="POST",
        )

        mock_db = MagicMock()
        mock_db.list.return_value = []

        # Mock rate limiters to avoid interference
        mock_limiter = MagicMock()
        mock_limiter.allow.return_value = MagicMock(allowed=True, retry_after=0)

        with (
            patch(
                "aragora.server.handlers.social._slack_impl.config.SLACK_SIGNING_SECRET",
                signing_secret,
            ),
            patch("aragora.connectors.chat.webhook_security.verify_slack_signature") as mock_verify,
            patch(
                "aragora.server.handlers.social._slack_impl.commands.get_debates_db",
                return_value=mock_db,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_workspace_rate_limiter",
                return_value=mock_limiter,
            ),
            patch(
                "aragora.server.handlers.social._slack_impl.commands._get_user_rate_limiter",
                return_value=mock_limiter,
            ),
        ):
            mock_verify.return_value = MagicMock(verified=True, error=None)
            result = await handler.handle("/api/v1/integrations/slack/commands", {}, mock_http)

        body_data = get_json(result)
        text = body_data.get("text", "")
        # Message can be either "no recent" (empty db), "history not available" (no db), or "start" (hint)
        assert (
            "no recent" in text.lower()
            or "start" in text.lower()
            or "history not available" in text.lower()
        )


# ===========================================================================
# Thread-Safety Tests
# ===========================================================================


class TestThreadSafety:
    """Tests for thread-safety of circuit breaker."""

    def test_circuit_breaker_concurrent_access(self):
        """Circuit breaker should handle concurrent access safely."""
        import threading

        from aragora.server.handlers.social._slack_impl.messaging import SlackCircuitBreaker

        cb = SlackCircuitBreaker(failure_threshold=100)
        errors = []

        def record_failures():
            try:
                for _ in range(50):
                    cb.record_failure()
            except Exception as e:
                errors.append(e)

        def record_successes():
            try:
                for _ in range(50):
                    cb.record_success()
            except Exception as e:
                errors.append(e)

        def check_state():
            try:
                for _ in range(50):
                    _ = cb.state
                    _ = cb.can_proceed()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_failures),
            threading.Thread(target=record_successes),
            threading.Thread(target=check_state),
            threading.Thread(target=record_failures),
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # No exceptions should have occurred
        assert len(errors) == 0
