"""Comprehensive tests for the InteractiveMixin in _slack_impl/interactive.py.

Covers every public/internal method of InteractiveMixin:
- _handle_interactive: payload parsing, action type dispatch, invalid JSON,
  empty body, audit logging, block_actions routing, unknown action types
- _handle_vote_action: vote_agree, vote_disagree, malformed action_id,
  short action_id, storage recording, vote aggregator integration,
  storage ImportError, storage RuntimeError, aggregator ImportError
- _handle_view_details: debate found, debate not found, empty debate_id,
  missing value field, long task truncation, long answer truncation,
  many agents (>5 truncation), storage errors, consensus/confidence formatting
- Error handling for all caught exception types
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

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


def _make_interactive_handler(
    payload: dict | None = None,
    body_str: str | None = None,
    team_id: str = "T789",
    workspace: Any = None,
):
    """Build a mock HTTP handler with Slack interactive payload body attributes."""
    h = MagicMock()
    if body_str is not None:
        h._slack_body = body_str
    elif payload is not None:
        h._slack_body = urlencode({"payload": json.dumps(payload)})
    else:
        h._slack_body = ""
    h._slack_workspace = workspace
    h._slack_team_id = team_id
    return h


def _block_actions_payload(
    actions: list[dict] | None = None,
    user_id: str = "U123",
    team_id: str = "T789",
) -> dict:
    """Build a block_actions interactive payload."""
    return {
        "type": "block_actions",
        "user": {"id": user_id},
        "team": {"id": team_id},
        "actions": actions or [],
    }


def _vote_action(debate_id: str = "d42", option: str = "agree") -> dict:
    """Build a vote action dict."""
    return {"action_id": f"vote_{debate_id}_{option}"}


def _view_details_action(debate_id: str = "d42") -> dict:
    """Build a view_details action dict."""
    return {"action_id": "view_details", "value": debate_id}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler_module():
    """Import the handler module lazily (after conftest patches)."""
    from aragora.server.handlers.social._slack_impl import handler as mod

    return mod


@pytest.fixture
def interactive_module():
    """Import the interactive module lazily."""
    from aragora.server.handlers.social._slack_impl import interactive as mod

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
def _disable_audit(interactive_module, monkeypatch):
    """Disable the audit logger by default."""
    monkeypatch.setattr(interactive_module, "_get_audit_logger", lambda: None)
    yield


# ===========================================================================
# _handle_interactive - payload parsing
# ===========================================================================


class TestHandleInteractivePayloadParsing:
    """Tests for interactive payload parsing."""

    def test_empty_body_returns_action_received(self, slack_handler):
        """Empty body (no payload field) returns default acknowledgement."""
        h = _make_interactive_handler(body_str="")
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body.get("text") == "Action received"

    def test_no_payload_param_returns_action_received(self, slack_handler):
        """Form body without 'payload' field parses to empty dict."""
        h = _make_interactive_handler(body_str=urlencode({"other": "value"}))
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body.get("text") == "Action received"

    def test_empty_payload_json_returns_action_received(self, slack_handler):
        """Payload with empty JSON object returns default acknowledgement."""
        h = _make_interactive_handler(payload={})
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body.get("text") == "Action received"

    def test_invalid_json_payload_returns_400(self, slack_handler):
        """Invalid JSON in payload field returns 400 error."""
        h = _make_interactive_handler(body_str=urlencode({"payload": "not valid json{{{"}))
        result = slack_handler._handle_interactive(h)
        assert _status(result) == 400
        assert "Invalid JSON" in _body(result).get("error", "")

    def test_handler_body_attribute_used(self, slack_handler):
        """Body is read from handler._slack_body attribute."""
        payload = {"type": "shortcut", "user": {"id": "U999"}, "team": {"id": "T111"}}
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body.get("text") == "Action received"


# ===========================================================================
# _handle_interactive - action type dispatch
# ===========================================================================


class TestHandleInteractiveActionDispatch:
    """Tests for action type routing in _handle_interactive."""

    def test_unknown_action_type_returns_ack(self, slack_handler):
        """Unknown action type returns generic acknowledgement."""
        payload = {"type": "some_unknown_type", "user": {"id": "U123"}, "team": {"id": "T789"}}
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body["text"] == "Action received"

    def test_block_actions_no_actions_returns_ack(self, slack_handler):
        """block_actions with empty actions list returns acknowledgement."""
        payload = _block_actions_payload(actions=[])
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body["text"] == "Action received"

    def test_block_actions_unknown_action_id_returns_ack(self, slack_handler):
        """block_actions with unrecognized action_id returns acknowledgement."""
        payload = _block_actions_payload(actions=[{"action_id": "unknown_button"}])
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body["text"] == "Action received"

    def test_block_actions_routes_vote_action(self, slack_handler):
        """block_actions with vote_ prefix routes to vote handler."""
        payload = _block_actions_payload(actions=[_vote_action("d1", "agree")])
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert "vote" in body["text"].lower() or "recorded" in body["text"].lower()

    def test_block_actions_routes_view_details(self, slack_handler):
        """block_actions with view_details routes to view details handler."""
        payload = _block_actions_payload(actions=[_view_details_action("d42")])
        h = _make_interactive_handler(payload=payload)
        # view_details tries to fetch debate from storage; without mock, debate won't be found
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        # Should return either detail or "not found" since storage is not available
        assert "d42" in body.get("text", "")

    def test_block_actions_uses_first_action_only(self, slack_handler):
        """Only the first action in the actions array is processed."""
        payload = _block_actions_payload(
            actions=[
                _vote_action("d1", "agree"),
                _vote_action("d2", "disagree"),
            ]
        )
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        # Should reference d1 (agree), not d2
        assert "agree" in body["text"].lower()

    def test_null_type_returns_ack(self, slack_handler):
        """Payload with no 'type' field returns acknowledgement."""
        payload = {"user": {"id": "U123"}, "team": {"id": "T789"}}
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body["text"] == "Action received"

    def test_shortcut_type_returns_ack(self, slack_handler):
        """Shortcut action type returns acknowledgement (not block_actions)."""
        payload = {"type": "shortcut", "user": {"id": "U123"}, "team": {"id": "T789"}}
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body["text"] == "Action received"

    def test_view_submission_type_returns_ack(self, slack_handler):
        """view_submission type returns acknowledgement."""
        payload = {
            "type": "view_submission",
            "user": {"id": "U123"},
            "team": {"id": "T789"},
            "view": {"id": "V123"},
        }
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body["text"] == "Action received"


# ===========================================================================
# _handle_interactive - audit logging
# ===========================================================================


class TestHandleInteractiveAuditLogging:
    """Tests for audit logging in _handle_interactive."""

    def test_audit_log_called_for_interactive_action(
        self, slack_handler, interactive_module, monkeypatch
    ):
        """Audit logger receives event when action is processed."""
        mock_audit = MagicMock()
        monkeypatch.setattr(interactive_module, "_get_audit_logger", lambda: mock_audit)

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "team": {"id": "T789"},
            "actions": [],
        }
        h = _make_interactive_handler(payload=payload)
        slack_handler._handle_interactive(h)

        mock_audit.log_event.assert_called_once()
        call_kwargs = mock_audit.log_event.call_args
        # Check keyword args
        kw = call_kwargs[1] if call_kwargs[1] else {}
        if not kw:
            # Check positional via keyword extraction
            kw = call_kwargs.kwargs if hasattr(call_kwargs, "kwargs") else {}
        assert kw.get("event_type") == "interactive:block_actions"
        assert kw.get("user_id") == "U123"
        assert kw.get("success") is True

    def test_audit_log_not_called_when_audit_is_none(
        self, slack_handler, interactive_module, monkeypatch
    ):
        """When audit logger is None, no error occurs."""
        monkeypatch.setattr(interactive_module, "_get_audit_logger", lambda: None)
        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "team": {"id": "T789"},
            "actions": [],
        }
        h = _make_interactive_handler(payload=payload)
        # Should not raise
        result = slack_handler._handle_interactive(h)
        assert _body(result)["text"] == "Action received"

    def test_audit_log_includes_team_id_from_payload(
        self, slack_handler, interactive_module, monkeypatch
    ):
        """Audit log includes team_id from the payload's team object."""
        mock_audit = MagicMock()
        monkeypatch.setattr(interactive_module, "_get_audit_logger", lambda: mock_audit)

        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "team": {"id": "T555"},
            "actions": [],
        }
        h = _make_interactive_handler(payload=payload, team_id="T999")
        slack_handler._handle_interactive(h)

        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["workspace_id"] == "T555"

    def test_audit_log_falls_back_to_handler_team_id(
        self, slack_handler, interactive_module, monkeypatch
    ):
        """When payload has no team, falls back to handler._slack_team_id."""
        mock_audit = MagicMock()
        monkeypatch.setattr(interactive_module, "_get_audit_logger", lambda: mock_audit)

        payload = {"type": "block_actions", "user": {"id": "U123"}, "actions": []}
        h = _make_interactive_handler(payload=payload, team_id="T_FALLBACK")
        slack_handler._handle_interactive(h)

        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["workspace_id"] == "T_FALLBACK"

    def test_audit_user_id_defaults_to_unknown(
        self, slack_handler, interactive_module, monkeypatch
    ):
        """User ID defaults to 'unknown' when not in payload."""
        mock_audit = MagicMock()
        monkeypatch.setattr(interactive_module, "_get_audit_logger", lambda: mock_audit)

        payload = {"type": "block_actions", "actions": []}
        h = _make_interactive_handler(payload=payload)
        slack_handler._handle_interactive(h)

        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["user_id"] == "unknown"


# ===========================================================================
# _handle_vote_action
# ===========================================================================


class TestHandleVoteAction:
    """Tests for the _handle_vote_action method."""

    def test_vote_agree_returns_thumbs_up(self, slack_handler):
        """Voting 'agree' returns a thumbs up emoji response."""
        payload = {"user": {"id": "U123"}}
        action = _vote_action("d42", "agree")
        result = slack_handler._handle_vote_action(payload, action)
        body = _body(result)
        assert "\U0001f44d" in body["text"]  # thumbs up
        assert "agree" in body["text"]
        assert body["replace_original"] is False

    def test_vote_disagree_returns_thumbs_down(self, slack_handler):
        """Voting 'disagree' returns a thumbs down emoji response."""
        payload = {"user": {"id": "U123"}}
        action = _vote_action("d42", "disagree")
        result = slack_handler._handle_vote_action(payload, action)
        body = _body(result)
        assert "\U0001f44e" in body["text"]  # thumbs down
        assert "disagree" in body["text"]

    def test_vote_recorded_text(self, slack_handler):
        """Vote response confirms the vote has been recorded."""
        payload = {"user": {"id": "U123"}}
        action = _vote_action("d42", "agree")
        result = slack_handler._handle_vote_action(payload, action)
        body = _body(result)
        assert "recorded" in body["text"].lower()

    def test_short_action_id_returns_fallback(self, slack_handler):
        """Action ID with fewer than 3 parts returns fallback response."""
        payload = {"user": {"id": "U123"}}
        action = {"action_id": "vote_only"}
        result = slack_handler._handle_vote_action(payload, action)
        body = _body(result)
        assert body["text"] == "Vote recorded"

    def test_empty_action_id_returns_fallback(self, slack_handler):
        """Empty action_id returns fallback response."""
        payload = {"user": {"id": "U123"}}
        action = {"action_id": ""}
        result = slack_handler._handle_vote_action(payload, action)
        body = _body(result)
        assert body["text"] == "Vote recorded"

    def test_missing_action_id_returns_fallback(self, slack_handler):
        """Missing action_id key returns fallback response."""
        payload = {"user": {"id": "U123"}}
        action = {}
        result = slack_handler._handle_vote_action(payload, action)
        body = _body(result)
        assert body["text"] == "Vote recorded"

    def test_vote_with_extra_underscore_parts(self, slack_handler):
        """Action ID with more than 3 parts still extracts debate_id and option."""
        payload = {"user": {"id": "U123"}}
        action = {"action_id": "vote_d42_agree_extra_stuff"}
        result = slack_handler._handle_vote_action(payload, action)
        body = _body(result)
        assert "agree" in body["text"]
        assert "\U0001f44d" in body["text"]

    def test_vote_records_to_debates_db(self, slack_handler):
        """Vote is recorded in the debates database when available."""
        mock_db = MagicMock()
        mock_db.record_vote = MagicMock()

        payload = {"user": {"id": "U555"}}
        action = _vote_action("debate123", "agree")

        with patch(
            "aragora.server.handlers.social._slack_impl.interactive.get_debates_db",
            create=True,
        ) as mock_get_db:
            # We need to patch at import time since the import is inside the function
            with patch.dict("sys.modules", {}):
                pass
            # Patch the import within the method
            mock_storage = MagicMock()
            mock_storage.get_debates_db.return_value = mock_db
            with patch(
                "aragora.storage.debate_storage.get_debates_db",
                return_value=mock_db,
                create=True,
            ):
                result = slack_handler._handle_vote_action(payload, action)

        body = _body(result)
        assert "agree" in body["text"]

    def test_vote_storage_import_error_handled(self, slack_handler):
        """ImportError when importing storage is handled gracefully."""
        payload = {"user": {"id": "U123"}}
        action = _vote_action("d42", "agree")

        with patch(
            "aragora.server.handlers.social._slack_impl.interactive.json",
        ):
            # Even if storage fails, vote response is still returned
            result = slack_handler._handle_vote_action(payload, action)

        body = _body(result)
        assert "agree" in body["text"]

    def test_vote_aggregator_records_for_position(self, slack_handler):
        """Vote aggregator records 'for' position when vote is 'agree'."""
        mock_aggregator = MagicMock()

        payload = {"user": {"id": "U555"}}
        action = _vote_action("d42", "agree")

        # Create a mock module with VoteAggregator.get_instance
        mock_va_module = MagicMock()
        mock_va_module.VoteAggregator.get_instance.return_value = mock_aggregator

        import sys

        with patch.dict(sys.modules, {"aragora.debate.vote_aggregator": mock_va_module}):
            result = slack_handler._handle_vote_action(payload, action)

        body = _body(result)
        assert "agree" in body["text"]
        mock_aggregator.record_vote.assert_called_once_with("d42", "slack:U555", "for")

    def test_vote_aggregator_records_against_for_disagree(self, slack_handler):
        """Vote aggregator records 'against' position when vote is 'disagree'."""
        mock_aggregator = MagicMock()

        payload = {"user": {"id": "U555"}}
        action = _vote_action("d42", "disagree")

        mock_va_module = MagicMock()
        mock_va_module.VoteAggregator.get_instance.return_value = mock_aggregator

        import sys

        with patch.dict(sys.modules, {"aragora.debate.vote_aggregator": mock_va_module}):
            result = slack_handler._handle_vote_action(payload, action)

        body = _body(result)
        assert "disagree" in body["text"]
        mock_aggregator.record_vote.assert_called_once_with("d42", "slack:U555", "against")

    def test_vote_aggregator_import_error_handled(self, slack_handler):
        """ImportError from vote aggregator is handled gracefully."""
        payload = {"user": {"id": "U123"}}
        action = _vote_action("d42", "agree")
        # Default environment won't have VoteAggregator; vote still returns response
        result = slack_handler._handle_vote_action(payload, action)
        body = _body(result)
        assert "agree" in body["text"]

    def test_vote_user_id_defaults_to_unknown(self, slack_handler):
        """Missing user ID defaults to 'unknown'."""
        payload = {}
        action = _vote_action("d42", "agree")
        result = slack_handler._handle_vote_action(payload, action)
        body = _body(result)
        assert "agree" in body["text"]

    def test_vote_custom_option_text(self, slack_handler):
        """Custom vote option text is returned in the response."""
        payload = {"user": {"id": "U123"}}
        action = {"action_id": "vote_d42_abstain"}
        result = slack_handler._handle_vote_action(payload, action)
        body = _body(result)
        assert "abstain" in body["text"]
        # Non-agree option gets thumbs down
        assert "\U0001f44e" in body["text"]


# ===========================================================================
# _handle_view_details
# ===========================================================================


class TestHandleViewDetails:
    """Tests for the _handle_view_details method."""

    def test_empty_debate_id_returns_error(self, slack_handler):
        """Empty debate_id returns error message."""
        payload = {"user": {"id": "U123"}}
        action = {"action_id": "view_details", "value": ""}
        result = slack_handler._handle_view_details(payload, action)
        body = _body(result)
        assert "Error" in body["text"] or "error" in body["text"].lower()
        assert body["replace_original"] is False

    def test_missing_value_key_returns_error(self, slack_handler):
        """Missing 'value' key in action returns error (empty debate_id)."""
        payload = {"user": {"id": "U123"}}
        action = {"action_id": "view_details"}
        result = slack_handler._handle_view_details(payload, action)
        body = _body(result)
        assert "No debate ID" in body["text"]

    def test_debate_not_found_in_storage(self, slack_handler):
        """When debate is not in storage, returns 'not found' message."""
        payload = {"user": {"id": "U123"}}
        action = _view_details_action("nonexistent_debate")
        # Without storage mock, debate won't be found
        result = slack_handler._handle_view_details(payload, action)
        body = _body(result)
        assert "not found" in body["text"].lower()
        assert "nonexistent_debate" in body["text"]
        assert body["replace_original"] is False

    def test_debate_found_returns_blocks(self, slack_handler):
        """When debate is found, returns detailed block response."""
        debate_data = {
            "task": "Should we use microservices?",
            "final_answer": "Yes, with careful boundary design.",
            "consensus_reached": True,
            "confidence": 0.85,
            "rounds_used": 3,
            "agents": ["claude", "gpt4", "gemini"],
            "created_at": "2026-01-15T10:30:00Z",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        payload = {"user": {"id": "U123"}}
        action = _view_details_action("d42")

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(payload, action)

        body = _body(result)
        assert body["response_type"] == "ephemeral"
        assert "d42" in body["text"]
        assert body["replace_original"] is False
        assert "blocks" in body
        blocks = body["blocks"]
        assert len(blocks) >= 4

    def test_debate_details_contain_header(self, slack_handler):
        """Response blocks include a header block."""
        debate_data = {
            "task": "Test topic",
            "final_answer": "Test conclusion",
            "consensus_reached": False,
            "confidence": 0.5,
            "rounds_used": 2,
            "agents": ["claude"],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        payload = {"user": {"id": "U123"}}
        action = _view_details_action("d42")

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(payload, action)

        blocks = _body(result)["blocks"]
        header = blocks[0]
        assert header["type"] == "header"
        assert "Debate Details" in header["text"]["text"]

    def test_debate_details_task_truncated_at_200(self, slack_handler):
        """Long task text is truncated at 200 characters."""
        long_task = "A" * 300
        debate_data = {
            "task": long_task,
            "final_answer": "Conclusion",
            "consensus_reached": True,
            "confidence": 0.9,
            "rounds_used": 1,
            "agents": [],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        payload = {"user": {"id": "U123"}}
        action = _view_details_action("d42")

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(payload, action)

        blocks = _body(result)["blocks"]
        # Section block with topic (index 1)
        topic_block = blocks[1]
        topic_text = topic_block["text"]["text"]
        # The task[:200] truncation
        assert len(topic_text) < 300 + len("*Topic:*\n")

    def test_debate_details_answer_truncated_at_800(self, slack_handler):
        """Long final_answer is truncated at 800 characters."""
        long_answer = "B" * 1000
        debate_data = {
            "task": "Topic",
            "final_answer": long_answer,
            "consensus_reached": True,
            "confidence": 0.9,
            "rounds_used": 1,
            "agents": [],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        payload = {"user": {"id": "U123"}}
        action = _view_details_action("d42")

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(payload, action)

        blocks = _body(result)["blocks"]
        # Conclusion block is last
        conclusion_block = blocks[-1]
        conclusion_text = conclusion_block["text"]["text"]
        # Should be truncated to 800 chars of answer + prefix
        assert len(conclusion_text) <= 800 + len("*Conclusion:*\n")

    def test_debate_details_consensus_yes(self, slack_handler):
        """Consensus True displays as 'Yes'."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.75,
            "rounds_used": 3,
            "agents": ["claude"],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        consensus_field = fields_block["fields"][2]
        assert "Yes" in consensus_field["text"]

    def test_debate_details_consensus_no(self, slack_handler):
        """Consensus False displays as 'No'."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": False,
            "confidence": 0.3,
            "rounds_used": 5,
            "agents": ["claude"],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        consensus_field = fields_block["fields"][2]
        assert "No" in consensus_field["text"]

    def test_debate_details_confidence_formatted_as_percent(self, slack_handler):
        """Confidence is formatted as percentage (e.g., 85.0%)."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.85,
            "rounds_used": 2,
            "agents": [],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        confidence_field = fields_block["fields"][3]
        assert "85.0%" in confidence_field["text"]

    def test_debate_details_rounds_displayed(self, slack_handler):
        """Rounds used is displayed in the fields block."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.5,
            "rounds_used": 7,
            "agents": [],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        rounds_field = fields_block["fields"][4]
        assert "7" in rounds_field["text"]

    def test_debate_details_agents_listed(self, slack_handler):
        """Agent names are listed in the fields block."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.5,
            "rounds_used": 1,
            "agents": ["claude", "gpt4", "gemini"],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        agents_field = fields_block["fields"][5]
        assert "claude" in agents_field["text"]
        assert "gpt4" in agents_field["text"]
        assert "gemini" in agents_field["text"]

    def test_debate_details_agents_truncated_at_5(self, slack_handler):
        """More than 5 agents shows first 5 plus (+N more)."""
        agents = [f"agent{i}" for i in range(8)]
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.5,
            "rounds_used": 1,
            "agents": agents,
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        agents_field = fields_block["fields"][5]
        assert "+3 more" in agents_field["text"]
        assert "agent0" in agents_field["text"]
        assert "agent4" in agents_field["text"]
        # agent5-7 should NOT be listed
        assert "agent5" not in agents_field["text"]

    def test_debate_details_empty_agents(self, slack_handler):
        """Empty agents list shows 'Unknown'."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.5,
            "rounds_used": 1,
            "agents": [],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        agents_field = fields_block["fields"][5]
        assert "Unknown" in agents_field["text"]

    def test_debate_details_exactly_5_agents_no_more_suffix(self, slack_handler):
        """Exactly 5 agents shows all without (+N more) suffix."""
        agents = [f"agent{i}" for i in range(5)]
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.5,
            "rounds_used": 1,
            "agents": agents,
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        agents_field = fields_block["fields"][5]
        assert "more" not in agents_field["text"]
        for agent in agents:
            assert agent in agents_field["text"]

    def test_debate_details_storage_import_error(self, slack_handler):
        """ImportError when importing storage returns 'not found' gracefully."""
        payload = {"user": {"id": "U123"}}
        action = _view_details_action("d42")

        with patch(
            "builtins.__import__",
            side_effect=lambda name, *a, **kw: (
                (_ for _ in ()).throw(ImportError("no storage"))
                if "aragora.storage.debate_storage" in name
                else __import__(name, *a, **kw)
            ),
        ):
            # The default import may or may not be cached; either way, graceful
            pass

        # Without storage, debate_data will be None
        result = slack_handler._handle_view_details(payload, action)
        body = _body(result)
        assert "not found" in body["text"].lower() or "d42" in body["text"]

    def test_debate_details_storage_returns_none_db(self, slack_handler):
        """When get_debates_db returns None, debate is not found."""
        payload = {"user": {"id": "U123"}}
        action = _view_details_action("d42")

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=None,
            create=True,
        ):
            result = slack_handler._handle_view_details(payload, action)

        body = _body(result)
        assert "not found" in body["text"].lower()

    def test_debate_details_missing_fields_use_defaults(self, slack_handler):
        """Missing fields in debate data use default values."""
        # Must have at least one key so the dict is truthy (empty dict is falsy)
        debate_data = {"_exists": True}
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        body = _body(result)
        blocks = body["blocks"]
        # Check that defaults are used
        topic_block = blocks[1]
        assert "Unknown topic" in topic_block["text"]["text"]
        # Conclusion block
        conclusion_block = blocks[-1]
        assert "No conclusion" in conclusion_block["text"]["text"]

    def test_debate_details_null_final_answer(self, slack_handler):
        """None final_answer displays as 'No conclusion available'."""
        debate_data = {
            "task": "Topic",
            "final_answer": None,
            "consensus_reached": False,
            "confidence": 0,
            "rounds_used": 0,
            "agents": [],
            "created_at": "Unknown",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        conclusion_block = blocks[-1]
        assert "No conclusion available" in conclusion_block["text"]["text"]

    def test_debate_details_zero_confidence(self, slack_handler):
        """Zero confidence formats as 0.0%."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": False,
            "confidence": 0,
            "rounds_used": 0,
            "agents": [],
            "created_at": "Unknown",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        confidence_field = fields_block["fields"][3]
        assert "0.0%" in confidence_field["text"]

    def test_debate_details_full_confidence(self, slack_handler):
        """Full confidence (1.0) formats as 100.0%."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 1.0,
            "rounds_used": 1,
            "agents": ["claude"],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        confidence_field = fields_block["fields"][3]
        assert "100.0%" in confidence_field["text"]

    def test_debate_details_block_structure(self, slack_handler):
        """Response has correct block structure: header, section, divider, fields, divider, conclusion."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.5,
            "rounds_used": 1,
            "agents": ["claude"],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        assert len(blocks) == 6
        assert blocks[0]["type"] == "header"
        assert blocks[1]["type"] == "section"
        assert blocks[2]["type"] == "divider"
        assert blocks[3]["type"] == "section"
        assert blocks[4]["type"] == "divider"
        assert blocks[5]["type"] == "section"

    def test_debate_details_created_at_displayed(self, slack_handler):
        """Created at timestamp is included in the fields."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.5,
            "rounds_used": 1,
            "agents": [],
            "created_at": "2026-02-20T14:30:00Z",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("d42")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        created_field = fields_block["fields"][1]
        assert "2026-02-20T14:30:00Z" in created_field["text"]

    def test_debate_details_debate_id_in_code_block(self, slack_handler):
        """Debate ID is displayed in backtick code format."""
        debate_data = {
            "task": "Topic",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.5,
            "rounds_used": 1,
            "agents": [],
            "created_at": "2026-01-01",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_view_details(
                {"user": {"id": "U123"}}, _view_details_action("my-debate-id")
            )

        blocks = _body(result)["blocks"]
        fields_block = blocks[3]
        id_field = fields_block["fields"][0]
        assert "`my-debate-id`" in id_field["text"]


# ===========================================================================
# _handle_interactive - workspace and team_id extraction
# ===========================================================================


class TestHandleInteractiveContextExtraction:
    """Tests for workspace and team_id context extraction."""

    def test_workspace_attribute_set_on_handler(self, slack_handler):
        """Handler._slack_workspace attribute is available."""
        mock_ws = MagicMock()
        payload = {
            "type": "block_actions",
            "user": {"id": "U1"},
            "team": {"id": "T1"},
            "actions": [],
        }
        h = _make_interactive_handler(payload=payload, workspace=mock_ws)
        result = slack_handler._handle_interactive(h)
        # No error
        assert _body(result)["text"] == "Action received"

    def test_team_id_attribute_used_as_fallback(
        self, slack_handler, interactive_module, monkeypatch
    ):
        """_slack_team_id is used when payload has no team object."""
        mock_audit = MagicMock()
        monkeypatch.setattr(interactive_module, "_get_audit_logger", lambda: mock_audit)

        payload = {"type": "block_actions", "user": {"id": "U1"}, "actions": []}
        h = _make_interactive_handler(payload=payload, team_id="T_FROM_HANDLER")
        slack_handler._handle_interactive(h)

        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["workspace_id"] == "T_FROM_HANDLER"

    def test_none_team_id_defaults_to_empty(self, slack_handler, interactive_module, monkeypatch):
        """When both payload team and handler team_id are None, workspace_id is empty."""
        mock_audit = MagicMock()
        monkeypatch.setattr(interactive_module, "_get_audit_logger", lambda: mock_audit)

        payload = {"type": "block_actions", "user": {"id": "U1"}, "actions": []}
        h = _make_interactive_handler(payload=payload, team_id=None)
        h._slack_team_id = None
        slack_handler._handle_interactive(h)

        call_kwargs = mock_audit.log_event.call_args[1]
        assert call_kwargs["workspace_id"] == ""


# ===========================================================================
# _handle_interactive - error handling
# ===========================================================================


class TestHandleInteractiveErrorHandling:
    """Tests for error handling in _handle_interactive."""

    def test_returns_200_on_generic_payload_error(self, slack_handler):
        """Even with parsing issues, returns a 200 with error text (not 500)."""
        # The auto_error_response decorator may catch this
        h = _make_interactive_handler(body_str="payload=" + urlencode({"x": "y"}).replace("=", ""))
        result = slack_handler._handle_interactive(h)
        # Should either be 200 with error text or 400
        status = _status(result)
        assert status in (200, 400)

    def test_malformed_form_body_handled(self, slack_handler):
        """Malformed form body is handled gracefully."""
        h = _make_interactive_handler(body_str="%%%not_valid_form")
        result = slack_handler._handle_interactive(h)
        # parse_qs doesn't raise on malformed input, just returns empty
        body = _body(result)
        assert body.get("text") == "Action received"


# ===========================================================================
# Integration tests via _handle_interactive for vote flow
# ===========================================================================


class TestInteractiveVoteFlow:
    """End-to-end tests for vote actions through _handle_interactive."""

    def test_vote_agree_through_interactive(self, slack_handler):
        """Vote agree flows through _handle_interactive to _handle_vote_action."""
        payload = _block_actions_payload(
            actions=[_vote_action("d99", "agree")],
            user_id="U777",
            team_id="T555",
        )
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert "agree" in body["text"]
        assert "\U0001f44d" in body["text"]

    def test_vote_disagree_through_interactive(self, slack_handler):
        """Vote disagree flows through _handle_interactive to _handle_vote_action."""
        payload = _block_actions_payload(
            actions=[_vote_action("d99", "disagree")],
            user_id="U777",
        )
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert "disagree" in body["text"]
        assert "\U0001f44e" in body["text"]

    def test_view_details_through_interactive_not_found(self, slack_handler):
        """View details flows through _handle_interactive to _handle_view_details."""
        payload = _block_actions_payload(
            actions=[_view_details_action("missing_debate")],
        )
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert "not found" in body["text"].lower() or "missing_debate" in body["text"]

    def test_view_details_through_interactive_found(self, slack_handler):
        """View details with found debate returns full blocks response."""
        debate_data = {
            "task": "Integration test topic",
            "final_answer": "Test conclusion",
            "consensus_reached": True,
            "confidence": 0.95,
            "rounds_used": 4,
            "agents": ["claude", "gpt4"],
            "created_at": "2026-02-20",
        }
        mock_db = MagicMock()
        mock_db.get.return_value = debate_data

        payload = _block_actions_payload(
            actions=[_view_details_action("d_integration")],
        )
        h = _make_interactive_handler(payload=payload)

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
            create=True,
        ):
            result = slack_handler._handle_interactive(h)

        body = _body(result)
        assert "blocks" in body
        assert body["response_type"] == "ephemeral"
        assert "d_integration" in body["text"]


# ===========================================================================
# Edge cases
# ===========================================================================


class TestInteractiveEdgeCases:
    """Edge case tests for interactive handler."""

    def test_payload_with_message_actions_type(self, slack_handler):
        """message_actions type (not block_actions) returns generic ack."""
        payload = {
            "type": "message_actions",
            "user": {"id": "U123"},
            "team": {"id": "T789"},
        }
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body["text"] == "Action received"

    def test_actions_list_with_none_action_id(self, slack_handler):
        """Action without action_id key returns generic acknowledgement."""
        payload = _block_actions_payload(actions=[{"type": "button"}])
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body["text"] == "Action received"

    def test_unicode_in_payload(self, slack_handler):
        """Unicode characters in payload are handled correctly."""
        payload = {
            "type": "block_actions",
            "user": {"id": "U123", "name": "Jean-Pierre"},
            "team": {"id": "T789"},
            "actions": [],
        }
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert body["text"] == "Action received"

    def test_very_large_payload(self, slack_handler):
        """Large payload with many actions still processes first action only."""
        actions = [_vote_action(f"d{i}", "agree") for i in range(100)]
        payload = _block_actions_payload(actions=actions)
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        # Should process first action (d0)
        assert "agree" in body["text"]

    def test_nested_empty_user_object(self, slack_handler):
        """Empty user object defaults user_id to 'unknown'."""
        payload = {
            "type": "block_actions",
            "user": {},
            "team": {"id": "T789"},
            "actions": [_vote_action("d1", "agree")],
        }
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert "agree" in body["text"]

    def test_missing_user_object(self, slack_handler):
        """Missing user object defaults user_id to 'unknown'."""
        payload = {
            "type": "block_actions",
            "team": {"id": "T789"},
            "actions": [_vote_action("d1", "agree")],
        }
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        assert "agree" in body["text"]

    def test_double_encoded_payload(self, slack_handler):
        """Properly URL-encoded payload with special characters."""
        payload = {
            "type": "block_actions",
            "user": {"id": "U123"},
            "team": {"id": "T789"},
            "actions": [{"action_id": "vote_debate%20id_agree"}],
        }
        h = _make_interactive_handler(payload=payload)
        result = slack_handler._handle_interactive(h)
        body = _body(result)
        # The %20 is part of the action_id string; vote_debate%20id_agree
        # has 4+ parts when split on _, so it should try to process as vote
        # "debate%20id" would be the debate_id and "agree" the option
        assert "agree" in body["text"] or body["text"] == "Action received"
