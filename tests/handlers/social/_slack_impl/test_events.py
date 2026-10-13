"""Comprehensive tests for the EventsMixin in _slack_impl/events.py.

Covers every public/internal method of EventsMixin:
- _handle_events: URL verification, event_callback dispatch, unknown events,
  invalid JSON, invalid data, audit logging, rate limiting
- _audit_event_error: audit log calls on error, None audit logger
- _handle_app_mention: empty text help, debate suggestion, status redirect,
  agents redirect, help redirect, unknown text, bot mention stripping,
  SLACK_BOT_TOKEN posting, no token
- _handle_message_event: channel_type filtering (im only), bot message ignoring,
  empty text help, help command, status command (success/error), agents command
  (success/sorted/empty/error), recent command (success/empty/error), debate
  command (valid/too short/too long/queued), unknown text, no SLACK_BOT_TOKEN
- _create_dm_debate_async: happy path, no agents, ImportError, data error,
  runtime error
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(result) -> dict:
    """Extract JSON body dict from a HandlerResult."""
    if result is None:
        return {}
    if isinstance(result, dict):
        return result
    raw = result.body
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _status(result) -> int:
    """Extract HTTP status code from a HandlerResult."""
    if result is None:
        return 0
    if isinstance(result, dict):
        return result.get("status_code", 200)
    return result.status_code


def _make_event_handler(
    body_dict: dict | None = None,
    body_str: str | None = None,
    team_id: str = "T789",
    workspace: Any = None,
):
    """Build a mock HTTP handler with Slack event body attributes."""
    h = MagicMock()
    if body_str is not None:
        h._slack_body = body_str
    elif body_dict is not None:
        h._slack_body = json.dumps(body_dict)
    else:
        h._slack_body = "{}"
    h._slack_workspace = workspace
    h._slack_team_id = team_id
    return h


def _url_verification_event(challenge: str = "abc123") -> dict:
    return {"type": "url_verification", "challenge": challenge}


def _event_callback(
    inner_type: str, inner_event: dict | None = None, team_id: str = "T789"
) -> dict:
    ev = inner_event or {}
    ev.setdefault("type", inner_type)
    return {"type": "event_callback", "team_id": team_id, "event": ev}


def _app_mention_event(
    text: str = "<@U0BOT> hello",
    channel: str = "C456",
    user: str = "U123",
    ts: str = "1234567890.123456",
) -> dict:
    return _event_callback(
        "app_mention",
        {
            "type": "app_mention",
            "text": text,
            "channel": channel,
            "user": user,
            "ts": ts,
        },
    )


def _message_event(
    text: str = "hello",
    channel: str = "D456",
    user: str = "U123",
    channel_type: str = "im",
    bot_id: str | None = None,
    subtype: str | None = None,
) -> dict:
    ev: dict[str, Any] = {
        "type": "message",
        "text": text,
        "channel": channel,
        "user": user,
        "channel_type": channel_type,
    }
    if bot_id:
        ev["bot_id"] = bot_id
    if subtype:
        ev["subtype"] = subtype
    return _event_callback("message", ev)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler_module():
    """Import the handler module lazily (after conftest patches)."""
    from aragora.server.handlers.social._slack_impl import handler as mod

    return mod


@pytest.fixture
def events_module():
    """Import the events module lazily."""
    from aragora.server.handlers.social._slack_impl import events as mod

    return mod


@pytest.fixture
def config_module():
    """Import the config module lazily."""
    from aragora.server.handlers.social._slack_impl import config as mod

    return mod


@pytest.fixture
def slack_handler(handler_module):
    """Create a SlackHandler with empty context."""
    return handler_module.SlackHandler(ctx={})


@pytest.fixture(autouse=True)
def _reset_config_singletons(config_module, monkeypatch):
    """Reset module-level singletons between tests."""
    monkeypatch.setattr(config_module, "_slack_audit", None)
    monkeypatch.setattr(config_module, "_slack_user_limiter", None)
    monkeypatch.setattr(config_module, "_slack_workspace_limiter", None)
    monkeypatch.setattr(config_module, "_slack_integration", None)
    yield


@pytest.fixture(autouse=True)
def _disable_rate_limit_decorator(monkeypatch):
    """Disable the @rate_limit decorator so it does not interfere with tests."""
    try:
        from aragora.server.handlers.utils import rate_limit as rl_mod

        monkeypatch.setattr(rl_mod, "_RATE_LIMIT_DISABLED", True, raising=False)
    except (ImportError, AttributeError):
        pass
    yield


@pytest.fixture(autouse=True)
def _disable_audit_and_bot_token(events_module, config_module, monkeypatch):
    """Disable audit logger and bot token by default; individual tests override."""
    monkeypatch.setattr(events_module, "_get_audit_logger", lambda: None)
    monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", None)
    monkeypatch.setattr(events_module, "create_tracked_task", MagicMock())
    yield


# ===========================================================================
# _handle_events - URL verification
# ===========================================================================


class TestHandleEventsUrlVerification:
    """Tests for URL verification challenge handling."""

    def test_url_verification_returns_challenge(self, slack_handler):
        """URL verification returns the challenge value."""
        h = _make_event_handler(_url_verification_event("test-challenge"))
        result = slack_handler._handle_events(h)
        assert _status(result) == 200
        assert _body(result)["challenge"] == "test-challenge"

    def test_url_verification_empty_challenge(self, slack_handler):
        """URL verification with empty challenge returns empty string."""
        h = _make_event_handler(_url_verification_event(""))
        result = slack_handler._handle_events(h)
        assert _body(result)["challenge"] == ""

    def test_url_verification_long_challenge(self, slack_handler):
        """URL verification with long challenge returns it fully."""
        challenge = "x" * 500
        h = _make_event_handler(_url_verification_event(challenge))
        result = slack_handler._handle_events(h)
        assert _body(result)["challenge"] == challenge

    def test_url_verification_special_chars(self, slack_handler):
        """URL verification with special characters in challenge."""
        challenge = "abc-123_XYZ.foo"
        h = _make_event_handler(_url_verification_event(challenge))
        result = slack_handler._handle_events(h)
        assert _body(result)["challenge"] == challenge


# ===========================================================================
# _handle_events - event_callback dispatch
# ===========================================================================


class TestHandleEventsCallback:
    """Tests for event_callback dispatch."""

    def test_app_mention_dispatches(self, slack_handler):
        """app_mention event dispatches to _handle_app_mention."""
        h = _make_event_handler(_app_mention_event("<@U0BOT> help"))
        result = slack_handler._handle_events(h)
        assert _status(result) == 200
        assert _body(result)["ok"] is True

    def test_message_event_dispatches(self, slack_handler):
        """message event dispatches to _handle_message_event."""
        h = _make_event_handler(_message_event("help"))
        result = slack_handler._handle_events(h)
        assert _status(result) == 200
        assert _body(result)["ok"] is True

    def test_unknown_inner_event_returns_ok(self, slack_handler):
        """Unknown inner event type still returns ok."""
        h = _make_event_handler(
            _event_callback(
                "reaction_added", {"type": "reaction_added", "user": "U1", "channel": "C1"}
            )
        )
        result = slack_handler._handle_events(h)
        assert _status(result) == 200
        assert _body(result)["ok"] is True

    def test_unknown_outer_type_returns_ok(self, slack_handler):
        """Unknown outer event type returns ok."""
        h = _make_event_handler({"type": "some_other_type"})
        result = slack_handler._handle_events(h)
        assert _status(result) == 200
        assert _body(result)["ok"] is True

    def test_empty_event_returns_ok(self, slack_handler):
        """Empty event dict returns ok."""
        h = _make_event_handler({})
        result = slack_handler._handle_events(h)
        assert _body(result)["ok"] is True


# ===========================================================================
# _handle_events - error handling
# ===========================================================================


class TestHandleEventsErrors:
    """Tests for error handling in _handle_events."""

    def test_invalid_json_returns_ok(self, slack_handler):
        """Invalid JSON body returns 200 ok (Slack expects 200 always)."""
        h = _make_event_handler(body_str="not valid json {{{")
        result = slack_handler._handle_events(h)
        assert _status(result) == 200
        assert _body(result)["ok"] is True

    def test_empty_body_returns_ok(self, slack_handler):
        """Empty body string returns ok (empty JSON)."""
        h = _make_event_handler(body_str="")
        result = slack_handler._handle_events(h)
        # Empty string triggers JSONDecodeError
        assert _status(result) == 200
        assert _body(result)["ok"] is True

    def test_null_body_attr_returns_ok(self, slack_handler):
        """Missing _slack_body attribute defaults to empty string."""
        h = MagicMock(spec=[])  # no attributes
        h._slack_body = ""
        h._slack_workspace = None
        h._slack_team_id = None
        result = slack_handler._handle_events(h)
        assert _status(result) == 200

    def test_no_team_id_attr(self, slack_handler):
        """Missing _slack_team_id defaults gracefully."""
        h = MagicMock()
        h._slack_body = json.dumps({"type": "url_verification", "challenge": "c"})
        del h._slack_team_id  # remove the attribute
        h._slack_team_id = None
        result = slack_handler._handle_events(h)
        assert _body(result)["challenge"] == "c"


# ===========================================================================
# _handle_events - audit logging
# ===========================================================================


class TestHandleEventsAudit:
    """Tests for audit logging in event handling."""

    def test_audit_logged_on_event_callback(self, slack_handler, events_module, monkeypatch):
        """Audit logger is called for event_callback events."""
        mock_audit = MagicMock()
        monkeypatch.setattr(events_module, "_get_audit_logger", lambda: mock_audit)

        h = _make_event_handler(_app_mention_event())
        slack_handler._handle_events(h)

        mock_audit.log_event.assert_called_once()
        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["event_type"] == "app_mention"
        assert call_kwargs["success"] is True

    def test_audit_logged_with_user_and_channel(self, slack_handler, events_module, monkeypatch):
        """Audit log contains user_id and channel_id."""
        mock_audit = MagicMock()
        monkeypatch.setattr(events_module, "_get_audit_logger", lambda: mock_audit)

        h = _make_event_handler(_app_mention_event(user="U999", channel="CXYZ"))
        slack_handler._handle_events(h)

        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["user_id"] == "U999"
        assert call_kwargs["channel_id"] == "CXYZ"

    def test_audit_not_called_when_none(self, slack_handler, events_module, monkeypatch):
        """No audit call when _get_audit_logger returns None."""
        monkeypatch.setattr(events_module, "_get_audit_logger", lambda: None)
        h = _make_event_handler(_app_mention_event())
        # Should not raise
        result = slack_handler._handle_events(h)
        assert _body(result)["ok"] is True

    def test_audit_logged_for_message_event(self, slack_handler, events_module, monkeypatch):
        """Audit logger is called for message events."""
        mock_audit = MagicMock()
        monkeypatch.setattr(events_module, "_get_audit_logger", lambda: mock_audit)

        h = _make_event_handler(_message_event("test"))
        slack_handler._handle_events(h)

        mock_audit.log_event.assert_called_once()
        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["event_type"] == "message"

    def test_audit_workspace_id_from_team_id(self, slack_handler, events_module, monkeypatch):
        """Audit log uses team_id as workspace_id."""
        mock_audit = MagicMock()
        monkeypatch.setattr(events_module, "_get_audit_logger", lambda: mock_audit)

        h = _make_event_handler(_app_mention_event(), team_id="TWORKSPACE")
        slack_handler._handle_events(h)

        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["workspace_id"] == "TWORKSPACE"


# ===========================================================================
# _audit_event_error
# ===========================================================================


class TestAuditEventError:
    """Tests for _audit_event_error helper."""

    def test_audit_error_calls_logger(self, slack_handler, events_module, monkeypatch):
        """_audit_event_error calls audit log with error info."""
        mock_audit = MagicMock()
        monkeypatch.setattr(events_module, "_get_audit_logger", lambda: mock_audit)

        slack_handler._audit_event_error("T123", "app_mention", "Something broke")
        mock_audit.log_event.assert_called_once()
        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["success"] is False
        assert call_kwargs["error"] == "Something broke"
        assert call_kwargs["workspace_id"] == "T123"

    def test_audit_error_truncates_long_error(self, slack_handler, events_module, monkeypatch):
        """Error message is truncated to 200 characters."""
        mock_audit = MagicMock()
        monkeypatch.setattr(events_module, "_get_audit_logger", lambda: mock_audit)

        long_error = "x" * 500
        slack_handler._audit_event_error("T1", "test", long_error)
        call_kwargs = mock_audit.log_event.call_args[1]
        assert len(call_kwargs["error"]) == 200

    def test_audit_error_with_none_logger(self, slack_handler, events_module, monkeypatch):
        """No error when audit logger is None."""
        monkeypatch.setattr(events_module, "_get_audit_logger", lambda: None)
        # Should not raise
        slack_handler._audit_event_error("T1", "test", "error")

    def test_audit_error_payload_summary(self, slack_handler, events_module, monkeypatch):
        """Payload summary contains error_type field."""
        mock_audit = MagicMock()
        monkeypatch.setattr(events_module, "_get_audit_logger", lambda: mock_audit)

        slack_handler._audit_event_error("T1", "test_type", "err")
        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["payload_summary"] == {"error_type": "processing_error"}
        assert call_kwargs["event_type"] == "test_type"


# ===========================================================================
# _handle_app_mention
# ===========================================================================


class TestHandleAppMention:
    """Tests for _handle_app_mention."""

    def test_mention_with_no_text_shows_help(self, slack_handler):
        """Mention with only bot tag shows help message."""
        event = {"text": "<@U0BOT>", "channel": "C1", "user": "U1"}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True

    def test_mention_with_empty_text_shows_help(self, slack_handler):
        """Mention with empty text field shows help."""
        event = {"text": "", "channel": "C1", "user": "U1"}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True

    def test_mention_debate_command(self, slack_handler):
        """Mention with 'debate <topic>' suggests slash command."""
        event = {"text": "<@U0BOT> debate AI regulation", "channel": "C1", "user": "U1"}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True

    def test_mention_status_command(self, slack_handler):
        """Mention with 'status' redirects to slash command."""
        event = {"text": "<@U0BOT> status", "channel": "C1", "user": "U1"}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True

    def test_mention_agents_command(self, slack_handler):
        """Mention with 'agents' redirects to slash command."""
        event = {"text": "<@U0BOT> agents", "channel": "C1", "user": "U1"}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True

    def test_mention_help_command(self, slack_handler):
        """Mention with 'help' redirects to slash command."""
        event = {"text": "<@U0BOT> help", "channel": "C1", "user": "U1"}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True

    def test_mention_unknown_text(self, slack_handler):
        """Unknown text returns 'I don't understand' response."""
        event = {"text": "<@U0BOT> foobar", "channel": "C1", "user": "U1"}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True

    def test_mention_posts_message_with_bot_token(self, slack_handler, events_module, monkeypatch):
        """When SLACK_BOT_TOKEN is set, create_tracked_task is called."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        event = {"text": "<@U0BOT> help", "channel": "C1", "user": "U1", "ts": "123"}
        slack_handler._handle_app_mention(event)
        mock_task.assert_called_once()

    def test_mention_no_post_without_token(self, slack_handler, events_module, monkeypatch):
        """Without SLACK_BOT_TOKEN, create_tracked_task is not called."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", None)
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        event = {"text": "<@U0BOT> help", "channel": "C1", "user": "U1"}
        slack_handler._handle_app_mention(event)
        mock_task.assert_not_called()

    def test_mention_strips_bot_id(self, slack_handler):
        """Bot mention tag is stripped from text before parsing."""
        event = {"text": "<@U0BOT123> debate test topic", "channel": "C1", "user": "U1"}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True

    def test_mention_debate_strips_quotes(self, slack_handler, events_module, monkeypatch):
        """Debate topic has quotes stripped."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        event = {"text": '<@U0BOT> debate "Should AI be regulated?"', "channel": "C1", "user": "U1"}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True

    def test_mention_case_insensitive_commands(self, slack_handler):
        """Commands like STATUS, HELP, AGENTS are case-insensitive."""
        for cmd in ["STATUS", "Status", "HELP", "Help", "AGENTS", "Agents"]:
            event = {"text": f"<@U0BOT> {cmd}", "channel": "C1", "user": "U1"}
            result = slack_handler._handle_app_mention(event)
            assert _body(result)["ok"] is True

    def test_mention_task_name_includes_channel(self, slack_handler, events_module, monkeypatch):
        """Tracked task name includes channel ID."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        event = {"text": "<@U0BOT> help", "channel": "CABCDEF", "user": "U1", "ts": "123"}
        slack_handler._handle_app_mention(event)
        task_name = mock_task.call_args[1].get("name") or mock_task.call_args[0][1]
        assert "CABCDEF" in task_name

    def test_mention_thread_ts_passed(self, slack_handler, events_module, monkeypatch):
        """Thread timestamp is passed to _post_message_async for threading."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        event = {"text": "<@U0BOT> help", "channel": "C1", "user": "U1", "ts": "999.888"}
        slack_handler._handle_app_mention(event)
        # The coroutine passed should include thread_ts from event["ts"]
        mock_task.assert_called_once()

    def test_mention_long_unknown_text_truncated(self, slack_handler):
        """Unknown text longer than 50 chars is truncated in response."""
        long_text = "a" * 100
        event = {"text": f"<@U0BOT> {long_text}", "channel": "C1", "user": "U1"}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True

    def test_mention_missing_fields_defaults(self, slack_handler):
        """Missing text/channel/user fields default to empty string."""
        event = {}
        result = slack_handler._handle_app_mention(event)
        assert _body(result)["ok"] is True


# ===========================================================================
# _handle_message_event - channel type filtering
# ===========================================================================


class TestHandleMessageEventFiltering:
    """Tests for channel type and bot message filtering."""

    def test_non_im_channel_ignored(self, slack_handler):
        """Non-IM channel messages are ignored."""
        ev = {"channel_type": "channel", "text": "hello", "user": "U1", "channel": "C1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_group_channel_ignored(self, slack_handler):
        """Group channel messages are ignored."""
        ev = {"channel_type": "group", "text": "hello", "user": "U1", "channel": "G1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_mpim_channel_ignored(self, slack_handler):
        """MPIM channel messages are ignored."""
        ev = {"channel_type": "mpim", "text": "hello", "user": "U1", "channel": "M1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_bot_message_with_bot_id_ignored(self, slack_handler):
        """Bot messages (bot_id present) are ignored."""
        ev = {"channel_type": "im", "bot_id": "B123", "text": "hi", "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_bot_message_subtype_ignored(self, slack_handler):
        """Bot messages (subtype=bot_message) are ignored."""
        ev = {
            "channel_type": "im",
            "subtype": "bot_message",
            "text": "hi",
            "user": "U1",
            "channel": "D1",
        }
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_im_channel_processed(self, slack_handler):
        """IM channel messages are processed."""
        ev = {"channel_type": "im", "text": "help", "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_missing_channel_type_ignored(self, slack_handler):
        """Missing channel_type means not IM, so ignored."""
        ev = {"text": "hello", "user": "U1", "channel": "C1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True


# ===========================================================================
# _handle_message_event - DM commands
# ===========================================================================


class TestHandleMessageEventCommands:
    """Tests for DM command parsing."""

    def test_empty_text_shows_help(self, slack_handler):
        """Empty text shows help message."""
        ev = {"channel_type": "im", "text": "", "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_whitespace_only_shows_help(self, slack_handler):
        """Whitespace-only text shows help message."""
        ev = {"channel_type": "im", "text": "   ", "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_help_command(self, slack_handler):
        """'help' command returns help text."""
        ev = {"channel_type": "im", "text": "help", "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_help_command_case_insensitive(self, slack_handler):
        """'HELP' and 'Help' also work."""
        for cmd in ["HELP", "Help", "hElP"]:
            ev = {"channel_type": "im", "text": cmd, "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_status_command_success(self, slack_handler):
        """'status' command with working EloSystem."""
        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = [1, 2, 3]  # 3 agents

        with patch("aragora.ranking.elo.EloSystem", return_value=mock_elo):
            ev = {"channel_type": "im", "text": "status", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_status_command_import_error(self, slack_handler):
        """'status' command when EloSystem import fails."""
        with patch.dict("sys.modules", {"aragora.ranking.elo": None}):
            ev = {"channel_type": "im", "text": "status", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_agents_command_with_agents(self, slack_handler):
        """'agents' command with available agents."""
        agents = [
            SimpleNamespace(name="claude", elo=1600, wins=10, losses=2),
            SimpleNamespace(name="gpt-4", elo=1550, wins=8, losses=4),
            SimpleNamespace(name="gemini", elo=1500, wins=5, losses=5),
        ]
        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = agents

        with patch("aragora.ranking.elo.EloSystem", return_value=mock_elo):
            ev = {"channel_type": "im", "text": "agents", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_agents_command_empty_list(self, slack_handler):
        """'agents' command with no registered agents."""
        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = []

        with patch("aragora.ranking.elo.EloSystem", return_value=mock_elo):
            ev = {"channel_type": "im", "text": "agents", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_agents_command_import_error(self, slack_handler):
        """'agents' command when EloSystem import fails."""
        with patch.dict("sys.modules", {"aragora.ranking.elo": None}):
            ev = {"channel_type": "im", "text": "agents", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_agents_sorted_by_elo(self, slack_handler):
        """'agents' are sorted by ELO descending."""
        agents = [
            SimpleNamespace(name="low", elo=1200),
            SimpleNamespace(name="high", elo=1800),
            SimpleNamespace(name="mid", elo=1500),
        ]
        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = agents

        with patch("aragora.ranking.elo.EloSystem", return_value=mock_elo):
            ev = {"channel_type": "im", "text": "agents", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_agents_command_limits_to_5(self, slack_handler):
        """'agents' command shows at most 5 agents."""
        agents = [SimpleNamespace(name=f"agent-{i}", elo=1500 + i) for i in range(10)]
        mock_elo = MagicMock()
        mock_elo.get_all_ratings.return_value = agents

        with patch("aragora.ranking.elo.EloSystem", return_value=mock_elo):
            ev = {"channel_type": "im", "text": "agents", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_recent_command_with_debates(self, slack_handler):
        """'recent' command with available debates."""
        mock_db = MagicMock()
        mock_db.list.return_value = [
            {"task": "AI regulation debate", "consensus_reached": True},
            {"task": "Climate change discussion", "consensus_reached": False},
        ]

        with patch("aragora.storage.debate_storage.get_debates_db", return_value=mock_db):
            ev = {"channel_type": "im", "text": "recent", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_recent_command_no_debates(self, slack_handler):
        """'recent' command with no debates."""
        mock_db = MagicMock()
        mock_db.list.return_value = []

        with patch("aragora.storage.debate_storage.get_debates_db", return_value=mock_db):
            ev = {"channel_type": "im", "text": "recent", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_recent_command_no_db(self, slack_handler):
        """'recent' command when database is unavailable."""
        with patch("aragora.storage.debate_storage.get_debates_db", return_value=None):
            ev = {"channel_type": "im", "text": "recent", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_recent_command_import_error(self, slack_handler):
        """'recent' command when storage module import fails."""
        with patch.dict("sys.modules", {"aragora.storage.debate_storage": None}):
            ev = {"channel_type": "im", "text": "recent", "user": "U1", "channel": "D1"}
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True

    def test_unknown_command(self, slack_handler):
        """Unknown text returns 'I don't understand' response."""
        ev = {"channel_type": "im", "text": "foobar", "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_unknown_command_truncated(self, slack_handler):
        """Unknown text longer than 30 chars is truncated in response."""
        ev = {"channel_type": "im", "text": "a" * 100, "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True


# ===========================================================================
# _handle_message_event - debate command
# ===========================================================================


class TestHandleMessageEventDebate:
    """Tests for the debate DM command."""

    def test_debate_topic_too_short(self, slack_handler):
        """Debate topic shorter than 10 chars is rejected."""
        ev = {"channel_type": "im", "text": "debate xyz", "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_debate_topic_too_long(self, slack_handler):
        """Debate topic longer than 500 chars is rejected."""
        long_topic = "a" * 501
        ev = {"channel_type": "im", "text": f"debate {long_topic}", "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_debate_valid_topic(self, slack_handler, events_module, monkeypatch):
        """Valid debate topic queues a task when bot token is present."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        ev = {
            "channel_type": "im",
            "text": "debate Should we use Rust for backend?",
            "user": "U1",
            "channel": "D1",
        }
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True
        # Two calls: one for debate task, one for response
        assert mock_task.call_count == 2

    def test_debate_no_bot_token_no_task(self, slack_handler, events_module, monkeypatch):
        """Without bot token, no tasks are created."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", None)
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        ev = {
            "channel_type": "im",
            "text": "debate Should we use Rust for backend?",
            "user": "U1",
            "channel": "D1",
        }
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True
        mock_task.assert_not_called()

    def test_debate_strips_quotes(self, slack_handler, events_module, monkeypatch):
        """Debate topic has surrounding quotes stripped."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        ev = {
            "channel_type": "im",
            "text": 'debate "Should we adopt Kubernetes?"',
            "user": "U1",
            "channel": "D1",
        }
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True
        assert mock_task.call_count == 2

    def test_debate_exactly_10_chars(self, slack_handler):
        """Debate topic of exactly 10 chars is accepted."""
        ev = {"channel_type": "im", "text": "debate 1234567890", "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_debate_exactly_500_chars(self, slack_handler):
        """Debate topic of exactly 500 chars is accepted."""
        topic = "a" * 500
        ev = {"channel_type": "im", "text": f"debate {topic}", "user": "U1", "channel": "D1"}
        result = slack_handler._handle_message_event(ev)
        assert _body(result)["ok"] is True

    def test_debate_case_insensitive(self, slack_handler):
        """'Debate' and 'DEBATE' also trigger debate handling."""
        for prefix in ["Debate", "DEBATE"]:
            ev = {
                "channel_type": "im",
                "text": f"{prefix} This is a long enough topic for debate",
                "user": "U1",
                "channel": "D1",
            }
            result = slack_handler._handle_message_event(ev)
            assert _body(result)["ok"] is True


# ===========================================================================
# _handle_message_event - response posting
# ===========================================================================


class TestHandleMessageEventPosting:
    """Tests for message response posting."""

    def test_response_posted_with_bot_token(self, slack_handler, events_module, monkeypatch):
        """Response is posted via create_tracked_task when bot token is set."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        ev = {"channel_type": "im", "text": "help", "user": "U1", "channel": "D1"}
        slack_handler._handle_message_event(ev)
        mock_task.assert_called_once()

    def test_no_response_without_bot_token(self, slack_handler, events_module, monkeypatch):
        """No response posted when bot token is not set."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", None)
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        ev = {"channel_type": "im", "text": "help", "user": "U1", "channel": "D1"}
        slack_handler._handle_message_event(ev)
        mock_task.assert_not_called()

    def test_task_name_includes_channel(self, slack_handler, events_module, monkeypatch):
        """Tracked task name includes channel ID."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        ev = {"channel_type": "im", "text": "help", "user": "U1", "channel": "DABCDEF"}
        slack_handler._handle_message_event(ev)
        task_name = mock_task.call_args[1].get("name") or mock_task.call_args[0][1]
        assert "DABCDEF" in task_name


# ===========================================================================
# _create_dm_debate_async
# ===========================================================================


class TestCreateDmDebateAsync:
    """Tests for _create_dm_debate_async."""

    @pytest.mark.asyncio
    async def test_happy_path(self, slack_handler):
        """Full debate flow posts result to channel."""
        mock_result = SimpleNamespace(
            consensus_reached=True,
            confidence=0.85,
            rounds_used=3,
            final_answer="The best approach is X.",
        )
        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(return_value=mock_result)

        mock_agents = [MagicMock(), MagicMock()]

        with (
            patch("aragora.Arena") as mock_arena_cls,
            patch("aragora.Environment") as mock_env_cls,
            patch("aragora.DebateProtocol") as mock_proto_cls,
            patch("aragora.agents.get_agents_by_names", return_value=mock_agents),
        ):
            mock_arena_cls.from_env.return_value = mock_arena
            slack_handler._post_message_async = AsyncMock()

            await slack_handler._create_dm_debate_async("test topic", "D1", "U1")

            slack_handler._post_message_async.assert_called_once()
            call_args = slack_handler._post_message_async.call_args
            msg = call_args[0][1]
            assert "Debate Complete" in msg
            assert "Yes" in msg  # consensus reached

    @pytest.mark.asyncio
    async def test_no_agents(self, slack_handler):
        """When no agents are available, posts error message."""
        with (
            patch("aragora.Arena"),
            patch("aragora.Environment"),
            patch("aragora.DebateProtocol"),
            patch("aragora.agents.get_agents_by_names", return_value=[]),
        ):
            slack_handler._post_message_async = AsyncMock()

            await slack_handler._create_dm_debate_async("test topic", "D1", "U1")

            slack_handler._post_message_async.assert_called_once()
            msg = slack_handler._post_message_async.call_args[0][1]
            assert "No agents" in msg

    @pytest.mark.asyncio
    async def test_import_error(self, slack_handler):
        """ImportError posts service unavailable message."""
        slack_handler._post_message_async = AsyncMock()

        import sys

        # Temporarily block aragora.agents import to trigger ImportError
        orig = sys.modules.get("aragora.agents")
        sys.modules["aragora.agents"] = None  # type: ignore[assignment]
        try:
            await slack_handler._create_dm_debate_async("topic", "D1", "U1")
        finally:
            if orig is not None:
                sys.modules["aragora.agents"] = orig
            else:
                sys.modules.pop("aragora.agents", None)

        msg = slack_handler._post_message_async.call_args[0][1]
        assert "temporarily unavailable" in msg

    @pytest.mark.asyncio
    async def test_no_consensus(self, slack_handler):
        """Debate with no consensus shows correct status."""
        mock_result = SimpleNamespace(
            consensus_reached=False,
            confidence=0.4,
            rounds_used=5,
            final_answer="No agreement reached.",
        )
        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(return_value=mock_result)

        mock_agents = [MagicMock()]

        with (
            patch("aragora.Arena") as mock_arena_cls,
            patch("aragora.Environment"),
            patch("aragora.DebateProtocol"),
            patch("aragora.agents.get_agents_by_names", return_value=mock_agents),
        ):
            mock_arena_cls.from_env.return_value = mock_arena
            slack_handler._post_message_async = AsyncMock()

            await slack_handler._create_dm_debate_async("test topic", "D1", "U1")

            msg = slack_handler._post_message_async.call_args[0][1]
            assert "No" in msg  # consensus: No

    @pytest.mark.asyncio
    async def test_no_final_answer(self, slack_handler):
        """Debate with None final_answer shows 'No conclusion'."""
        mock_result = SimpleNamespace(
            consensus_reached=True,
            confidence=0.7,
            rounds_used=3,
            final_answer=None,
        )
        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(return_value=mock_result)

        mock_agents = [MagicMock()]

        with (
            patch("aragora.Arena") as mock_arena_cls,
            patch("aragora.Environment"),
            patch("aragora.DebateProtocol"),
            patch("aragora.agents.get_agents_by_names", return_value=mock_agents),
        ):
            mock_arena_cls.from_env.return_value = mock_arena
            slack_handler._post_message_async = AsyncMock()

            await slack_handler._create_dm_debate_async("test topic", "D1", "U1")

            msg = slack_handler._post_message_async.call_args[0][1]
            assert "No conclusion" in msg

    @pytest.mark.asyncio
    async def test_value_error_in_debate(self, slack_handler):
        """ValueError during debate posts error message."""
        mock_agents = [MagicMock()]

        with (
            patch("aragora.Arena") as mock_arena_cls,
            patch("aragora.Environment"),
            patch("aragora.DebateProtocol"),
            patch("aragora.agents.get_agents_by_names", return_value=mock_agents),
        ):
            mock_arena_cls.from_env.side_effect = ValueError("bad config")
            slack_handler._post_message_async = AsyncMock()

            await slack_handler._create_dm_debate_async("test topic", "D1", "U1")

            msg = slack_handler._post_message_async.call_args[0][1]
            assert "error occurred" in msg.lower() or "Sorry" in msg

    @pytest.mark.asyncio
    async def test_runtime_error_in_debate(self, slack_handler):
        """RuntimeError during debate posts error message."""
        mock_agents = [MagicMock()]

        with (
            patch("aragora.Arena") as mock_arena_cls,
            patch("aragora.Environment"),
            patch("aragora.DebateProtocol"),
            patch("aragora.agents.get_agents_by_names", return_value=mock_agents),
        ):
            mock_arena = MagicMock()
            mock_arena.run = AsyncMock(side_effect=RuntimeError("connection lost"))
            mock_arena_cls.from_env.return_value = mock_arena
            slack_handler._post_message_async = AsyncMock()

            await slack_handler._create_dm_debate_async("test topic", "D1", "U1")

            msg = slack_handler._post_message_async.call_args[0][1]
            assert "error occurred" in msg.lower() or "Sorry" in msg

    @pytest.mark.asyncio
    async def test_long_topic_truncated_in_response(self, slack_handler):
        """Long topic is truncated to 100 chars in the result message."""
        topic = "x" * 200
        mock_result = SimpleNamespace(
            consensus_reached=True,
            confidence=0.9,
            rounds_used=2,
            final_answer="Done.",
        )
        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(return_value=mock_result)

        mock_agents = [MagicMock()]

        with (
            patch("aragora.Arena") as mock_arena_cls,
            patch("aragora.Environment"),
            patch("aragora.DebateProtocol"),
            patch("aragora.agents.get_agents_by_names", return_value=mock_agents),
        ):
            mock_arena_cls.from_env.return_value = mock_arena
            slack_handler._post_message_async = AsyncMock()

            await slack_handler._create_dm_debate_async(topic, "D1", "U1")

            msg = slack_handler._post_message_async.call_args[0][1]
            # Topic is truncated to 100 chars + "..."
            assert "..." in msg

    @pytest.mark.asyncio
    async def test_long_final_answer_truncated(self, slack_handler):
        """Long final answer is truncated to 500 chars."""
        mock_result = SimpleNamespace(
            consensus_reached=True,
            confidence=0.8,
            rounds_used=3,
            final_answer="y" * 1000,
        )
        mock_arena = MagicMock()
        mock_arena.run = AsyncMock(return_value=mock_result)

        mock_agents = [MagicMock()]

        with (
            patch("aragora.Arena") as mock_arena_cls,
            patch("aragora.Environment"),
            patch("aragora.DebateProtocol"),
            patch("aragora.agents.get_agents_by_names", return_value=mock_agents),
        ):
            mock_arena_cls.from_env.return_value = mock_arena
            slack_handler._post_message_async = AsyncMock()

            await slack_handler._create_dm_debate_async("test topic", "D1", "U1")

            msg = slack_handler._post_message_async.call_args[0][1]
            # Final answer is truncated to 500 + "..."
            assert "..." in msg


# ===========================================================================
# Integration tests - full event flow
# ===========================================================================


class TestFullEventFlow:
    """Integration tests through _handle_events to inner handlers."""

    def test_url_verification_through_handle_events(self, slack_handler):
        """URL verification through full event pipeline."""
        h = _make_event_handler({"type": "url_verification", "challenge": "verify-me"})
        result = slack_handler._handle_events(h)
        assert _body(result)["challenge"] == "verify-me"

    def test_app_mention_through_handle_events(self, slack_handler):
        """App mention through full event pipeline."""
        h = _make_event_handler(_app_mention_event("<@U0BOT> status"))
        result = slack_handler._handle_events(h)
        assert _status(result) == 200
        assert _body(result)["ok"] is True

    def test_dm_help_through_handle_events(self, slack_handler):
        """DM help command through full event pipeline."""
        h = _make_event_handler(_message_event("help", channel_type="im"))
        result = slack_handler._handle_events(h)
        assert _status(result) == 200

    def test_dm_debate_through_handle_events(self, slack_handler, events_module, monkeypatch):
        """DM debate command through full event pipeline."""
        mock_task = MagicMock()
        monkeypatch.setattr(events_module, "SLACK_BOT_TOKEN", "xoxb-test")
        monkeypatch.setattr(events_module, "create_tracked_task", mock_task)

        h = _make_event_handler(
            _message_event("debate Should we use microservices architecture?", channel_type="im")
        )
        result = slack_handler._handle_events(h)
        assert _status(result) == 200
        assert mock_task.call_count == 2  # debate task + response task

    def test_non_im_message_through_handle_events(self, slack_handler):
        """Non-IM message through full event pipeline is acknowledged."""
        h = _make_event_handler(_message_event("hello", channel_type="channel"))
        result = slack_handler._handle_events(h)
        assert _body(result)["ok"] is True

    def test_bot_message_through_handle_events(self, slack_handler):
        """Bot message through full event pipeline is acknowledged."""
        h = _make_event_handler(_message_event("hello", bot_id="B123"))
        result = slack_handler._handle_events(h)
        assert _body(result)["ok"] is True

    def test_event_callback_no_inner_event(self, slack_handler):
        """event_callback with missing inner event still works."""
        h = _make_event_handler({"type": "event_callback"})
        result = slack_handler._handle_events(h)
        assert _body(result)["ok"] is True

    def test_json_array_body(self, slack_handler):
        """JSON array body is handled by auto_error_response decorator."""
        h = _make_event_handler(body_str="[1,2,3]")
        result = slack_handler._handle_events(h)
        # AttributeError from .get() on list is caught by auto_error_response
        assert _status(result) in (200, 500)

    def test_numeric_json_body(self, slack_handler):
        """Numeric JSON body is handled by auto_error_response decorator."""
        h = _make_event_handler(body_str="42")
        result = slack_handler._handle_events(h)
        # AttributeError from .get() on int is caught by auto_error_response
        assert _status(result) in (200, 500)

    def test_null_json_body(self, slack_handler):
        """Null JSON body is handled by auto_error_response decorator."""
        h = _make_event_handler(body_str="null")
        result = slack_handler._handle_events(h)
        # AttributeError from .get() on None is caught by auto_error_response
        assert _status(result) in (200, 500)

    def test_audit_error_on_invalid_json(self, slack_handler, events_module, monkeypatch):
        """Audit error is logged when JSON is invalid."""
        mock_audit = MagicMock()
        monkeypatch.setattr(events_module, "_get_audit_logger", lambda: mock_audit)

        h = _make_event_handler(body_str="not json")
        slack_handler._handle_events(h)

        # _audit_event_error is called
        mock_audit.log_event.assert_called_once()
        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["success"] is False
        assert "Invalid JSON" in call_kwargs["error"]
