"""
Tests for NotificationTemplatesHandler.

Coverage:
- GET /api/v1/notifications/templates         (list all)
- GET /api/v1/notifications/templates/{id}    (get one)
- PUT /api/v1/notifications/templates/{id}    (update subject/body)
- POST /api/v1/notifications/templates/{id}/reset    (reset overrides)
- POST /api/v1/notifications/templates/{id}/preview  (render with values)
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def handler(mock_server_context):
    from aragora.server.handlers.notifications.templates import NotificationTemplatesHandler

    return NotificationTemplatesHandler(mock_server_context)


@pytest.fixture(autouse=True)
def _clear_overrides(tmp_path, monkeypatch):
    """Reset the persistent override store before each test."""
    from aragora.server.handlers.notifications import templates as tpl_mod
    from aragora.storage.notification_template_store import (
        get_notification_template_store,
        reset_notification_template_store,
    )

    reset_notification_template_store()
    monkeypatch.setattr(
        tpl_mod,
        "_get_template_store",
        lambda: get_notification_template_store(data_dir=str(tmp_path)),
    )
    yield
    reset_notification_template_store()


def _make_http(method: str = "GET", body: dict | None = None) -> MagicMock:
    mock = MagicMock()
    mock.command = method
    mock.client_address = ("127.0.0.1", 12345)
    body_bytes = json.dumps(body or {}).encode()
    mock.rfile = MagicMock()
    mock.rfile.read = MagicMock(return_value=body_bytes)
    mock.headers = {"Content-Length": str(len(body_bytes))}
    return mock


def _body(result) -> dict[str, Any]:
    raw = result.body
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw) if raw else {}


# ---------------------------------------------------------------------------
# Route matching
# ---------------------------------------------------------------------------


class TestCanHandle:
    def test_list_route(self, handler):
        assert handler.can_handle("/api/v1/notifications/templates") is True

    def test_single_route(self, handler):
        assert handler.can_handle("/api/v1/notifications/templates/debate_completed") is True

    def test_reset_route(self, handler):
        assert handler.can_handle("/api/v1/notifications/templates/debate_completed/reset") is True

    def test_preview_route(self, handler):
        assert handler.can_handle("/api/v1/notifications/templates/weekly_digest/preview") is True

    def test_rejects_unrelated_route(self, handler):
        assert handler.can_handle("/api/v1/notifications/preferences") is False

    def test_rejects_root(self, handler):
        assert handler.can_handle("/api/v1/debates") is False


# ---------------------------------------------------------------------------
# GET list
# ---------------------------------------------------------------------------


class TestListTemplates:
    def test_returns_200(self, handler):
        http = _make_http("GET")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle("/api/v1/notifications/templates", {}, http)
        assert result.status_code == 200

    def test_returns_all_five_defaults(self, handler):
        http = _make_http("GET")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle("/api/v1/notifications/templates", {}, http)
        body = _body(result)
        assert body["count"] == 5
        ids = [t["id"] for t in body["templates"]]
        assert "debate_completed" in ids
        assert "weekly_digest" in ids

    def test_not_customized_by_default(self, handler):
        http = _make_http("GET")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle("/api/v1/notifications/templates", {}, http)
        body = _body(result)
        assert all(not t["customized"] for t in body["templates"])

    def test_rate_limit_returns_429(self, handler):
        http = _make_http("GET")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = False
            result = handler.handle("/api/v1/notifications/templates", {}, http)
        assert result.status_code == 429


# ---------------------------------------------------------------------------
# GET single template
# ---------------------------------------------------------------------------


class TestGetSingleTemplate:
    def test_returns_200_for_known_id(self, handler):
        http = _make_http("GET")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle("/api/v1/notifications/templates/budget_alert", {}, http)
        assert result.status_code == 200
        body = _body(result)
        assert body["template"]["id"] == "budget_alert"

    def test_returns_404_for_unknown_id(self, handler):
        http = _make_http("GET")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle("/api/v1/notifications/templates/nonexistent", {}, http)
        assert result.status_code == 404

    def test_template_has_required_fields(self, handler):
        http = _make_http("GET")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle("/api/v1/notifications/templates/finding_critical", {}, http)
        tpl = _body(result)["template"]
        for field in (
            "id",
            "name",
            "description",
            "channel",
            "subject",
            "body",
            "variables",
            "sample_values",
        ):
            assert field in tpl, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# PUT update
# ---------------------------------------------------------------------------


class TestUpdateTemplate:
    def test_update_subject_returns_200(self, handler):
        http = _make_http("PUT", body={"subject": "Custom subject"})
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_put(
                "/api/v1/notifications/templates/debate_completed", {}, http
            )
        assert result.status_code == 200
        body = _body(result)
        assert body["updated"] is True
        assert body["template"]["subject"] == "Custom subject"

    def test_update_body_only(self, handler):
        http = _make_http("PUT", body={"body": "Custom body text"})
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_put("/api/v1/notifications/templates/weekly_digest", {}, http)
        assert result.status_code == 200
        assert _body(result)["template"]["body"] == "Custom body text"

    def test_marks_customized_true_after_update(self, handler):
        http = _make_http("PUT", body={"subject": "x"})
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            handler.handle_put("/api/v1/notifications/templates/audit_completed", {}, http)

        # Now GET and confirm customized=True
        http_get = _make_http("GET")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle("/api/v1/notifications/templates/audit_completed", {}, http_get)
        assert _body(result)["template"]["customized"] is True

    def test_update_unknown_template_returns_404(self, handler):
        http = _make_http("PUT", body={"subject": "x"})
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_put("/api/v1/notifications/templates/nonexistent", {}, http)
        assert result.status_code == 404

    def test_update_empty_body_returns_400(self, handler):
        http = _make_http("PUT", body={})
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_put(
                "/api/v1/notifications/templates/debate_completed", {}, http
            )
        assert result.status_code == 400

    def test_update_non_string_subject_returns_400(self, handler):
        http = _make_http("PUT", body={"subject": 42})
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_put(
                "/api/v1/notifications/templates/debate_completed", {}, http
            )
        assert result.status_code == 400


# ---------------------------------------------------------------------------
# POST reset
# ---------------------------------------------------------------------------


class TestResetTemplate:
    def _apply_override(self, handler):
        http = _make_http("PUT", body={"subject": "Override"})
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            handler.handle_put("/api/v1/notifications/templates/debate_completed", {}, http)

    def test_reset_restores_default(self, handler):
        from aragora.server.handlers.notifications.templates import _DEFAULT_TEMPLATES_BY_ID

        self._apply_override(handler)

        http = _make_http("POST")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_post(
                "/api/v1/notifications/templates/debate_completed/reset", {}, http
            )
        assert result.status_code == 200
        body = _body(result)
        assert body["reset"] is True
        expected_subject = _DEFAULT_TEMPLATES_BY_ID["debate_completed"]["subject"]
        assert body["template"]["subject"] == expected_subject

    def test_reset_marks_customized_false(self, handler):
        self._apply_override(handler)

        http = _make_http("POST")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_post(
                "/api/v1/notifications/templates/debate_completed/reset", {}, http
            )
        assert _body(result)["template"]["customized"] is False

    def test_reset_unknown_template_returns_404(self, handler):
        http = _make_http("POST")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_post(
                "/api/v1/notifications/templates/nonexistent/reset", {}, http
            )
        assert result.status_code == 404


# ---------------------------------------------------------------------------
# POST preview
# ---------------------------------------------------------------------------


class TestPreviewTemplate:
    def test_preview_renders_sample_values(self, handler):
        http = _make_http("POST", body={})
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_post(
                "/api/v1/notifications/templates/debate_completed/preview", {}, http
            )
        assert result.status_code == 200
        body = _body(result)
        # Placeholders should be gone
        assert "{{" not in body["rendered_subject"]
        assert "{{" not in body["rendered_body"]

    def test_preview_with_custom_values(self, handler):
        http = _make_http(
            "POST",
            body={"values": {"topic": "Custom Topic", "user_name": "Bob"}},
        )
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_post(
                "/api/v1/notifications/templates/debate_completed/preview", {}, http
            )
        body = _body(result)
        assert "Custom Topic" in body["rendered_subject"]
        assert "Bob" in body["rendered_body"]

    def test_preview_unknown_template_returns_404(self, handler):
        http = _make_http("POST")
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_post(
                "/api/v1/notifications/templates/nonexistent/preview", {}, http
            )
        assert result.status_code == 404

    def test_preview_uses_custom_overridden_body(self, handler):
        """Preview renders the user's custom body, not the default."""
        # Apply override
        put_http = _make_http("PUT", body={"body": "Hi {{user_name}}, test override."})
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            handler.handle_put("/api/v1/notifications/templates/audit_completed", {}, put_http)

        # Preview should use override
        post_http = _make_http("POST", body={"values": {"user_name": "Carol"}})
        with patch(
            "aragora.server.handlers.notifications.templates._templates_limiter"
        ) as mock_lim:
            mock_lim.is_allowed.return_value = True
            result = handler.handle_post(
                "/api/v1/notifications/templates/audit_completed/preview", {}, post_http
            )
        body = _body(result)
        assert "test override" in body["rendered_body"]
        assert "Carol" in body["rendered_body"]


# ---------------------------------------------------------------------------
# render_template unit tests
# ---------------------------------------------------------------------------


class TestRenderTemplate:
    def test_replaces_known_variable(self):
        from aragora.server.handlers.notifications.templates import _render_template

        result = _render_template("Hello {{name}}!", {"name": "World"})
        assert result == "Hello World!"

    def test_leaves_unknown_variable_intact(self):
        from aragora.server.handlers.notifications.templates import _render_template

        result = _render_template("Value: {{unknown}}", {})
        assert result == "Value: {{unknown}}"

    def test_replaces_multiple_variables(self):
        from aragora.server.handlers.notifications.templates import _render_template

        result = _render_template("{{a}} and {{b}}", {"a": "X", "b": "Y"})
        assert result == "X and Y"
