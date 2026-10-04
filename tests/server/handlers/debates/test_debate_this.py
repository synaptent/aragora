"""
Tests for the POST /api/v1/debate-this convenience endpoint.

Tests cover:
- Minimal body acceptance (only question required)
- Auto-format detection based on question length
- auto_select defaulting to True
- Rate limiting inheritance from create endpoint
- spectate_url inclusion in response
- Error handling for missing/invalid inputs
"""

import json

import pytest
from unittest.mock import MagicMock, patch

from aragora.server.handlers.debates.create import CreateOperationsMixin


class _FakeHandler:
    """Minimal handler protocol stub for testing CreateOperationsMixin."""

    def __init__(self, body: dict | None = None):
        self._body = body
        self.stream_emitter = MagicMock()

    ctx: dict = {}

    def get_storage(self):
        return MagicMock()

    def read_json_body(self, handler, max_size=None):
        return self._body

    def get_current_user(self, handler):
        return None

    def _check_spam_content(self, body):
        return None

    def _create_debate_direct(self, handler, body, scope):
        from aragora.server.handlers.base import json_response

        debate_id = f"adhoc_{body.get('question', 'test')[:8]}"
        return json_response(
            {"success": True, "debate_id": debate_id, "status": "starting"},
            status=200,
        )


class _Mixin(_FakeHandler, CreateOperationsMixin):
    """Combine the mixin with the fake handler for isolated testing."""

    pass


@pytest.fixture
def mixin():
    """Return a mixin instance with a default body."""
    return _Mixin(body={"question": "Should we adopt microservices?"})


@pytest.fixture
def mixin_factory():
    """Factory to create mixin with custom body."""

    def _make(body):
        return _Mixin(body=body)

    return _make


@pytest.fixture(autouse=True)
def _bypass_rate_limits(monkeypatch):
    """Bypass rate limiting decorators for all tests in this module."""
    # Patch the decorator factories to be transparent pass-throughs
    _noop_decorator = lambda **kw: (lambda fn: fn)
    monkeypatch.setattr("aragora.server.handlers.debates.create.rate_limit", _noop_decorator)
    monkeypatch.setattr("aragora.server.handlers.debates.create.user_rate_limit", _noop_decorator)
    monkeypatch.setattr(
        "aragora.server.handlers.debates.create.require_quota",
        lambda *a, **kw: (lambda fn: fn),
    )


class TestDebateThisEndpoint:
    """Tests for _debate_this convenience endpoint."""

    def test_minimal_body_accepted(self, mixin):
        """Endpoint accepts minimal body with only question."""
        result = mixin._debate_this(mixin)
        assert result is not None
        assert result.status_code == 200

    def test_returns_debate_id(self, mixin):
        """Response includes debate_id."""
        result = mixin._debate_this(mixin)
        data = json.loads(result.body)
        assert "debate_id" in data

    def test_returns_spectate_url(self, mixin):
        """Response includes spectate_url derived from debate_id."""
        result = mixin._debate_this(mixin)
        data = json.loads(result.body)
        assert "spectate_url" in data
        assert data["spectate_url"].startswith("/spectate/")

    def test_spectate_url_matches_debate_id(self, mixin):
        """spectate_url path contains the debate_id."""
        result = mixin._debate_this(mixin)
        data = json.loads(result.body)
        assert data["spectate_url"] == f"/spectate/{data['debate_id']}"

    def test_missing_question_returns_400(self, mixin_factory):
        """Missing question field returns 400."""
        mixin = mixin_factory({"context": "some context"})
        result = mixin._debate_this(mixin)
        assert result.status_code == 400

    def test_empty_question_returns_400(self, mixin_factory):
        """Empty question string returns 400."""
        mixin = mixin_factory({"question": ""})
        result = mixin._debate_this(mixin)
        assert result.status_code == 400

    def test_whitespace_question_returns_400(self, mixin_factory):
        """Whitespace-only question returns 400."""
        mixin = mixin_factory({"question": "   "})
        result = mixin._debate_this(mixin)
        assert result.status_code == 400

    def test_null_body_returns_400(self, mixin_factory):
        """Null/missing JSON body returns 400."""
        mixin = mixin_factory(None)
        result = mixin._debate_this(mixin)
        assert result.status_code == 400

    def test_auto_format_short_question(self, mixin_factory):
        """Short questions (<= 200 chars) get quick format (4 rounds)."""
        called_body = {}

        def capture_direct(handler, body, scope):
            called_body.update(body)
            from aragora.server.handlers.base import json_response

            return json_response(
                {"success": True, "debate_id": "adhoc_test", "status": "starting"},
                status=200,
            )

        mixin = mixin_factory({"question": "Should we use React?"})
        mixin._create_debate_direct = capture_direct
        mixin._debate_this(mixin)
        assert called_body.get("rounds") == 4

    def test_auto_format_long_question(self, mixin_factory):
        """Long questions (> 200 chars) get thorough format (9 rounds)."""
        called_body = {}

        def capture_direct(handler, body, scope):
            called_body.update(body)
            from aragora.server.handlers.base import json_response

            return json_response(
                {"success": True, "debate_id": "adhoc_test", "status": "starting"},
                status=200,
            )

        long_question = "A" * 201
        mixin = mixin_factory({"question": long_question})
        mixin._create_debate_direct = capture_direct
        mixin._debate_this(mixin)
        assert called_body.get("rounds") == 9

    def test_auto_select_always_true(self, mixin_factory):
        """auto_select is always set to True."""
        called_body = {}

        def capture_direct(handler, body, scope):
            called_body.update(body)
            from aragora.server.handlers.base import json_response

            return json_response(
                {"success": True, "debate_id": "adhoc_test", "status": "starting"},
                status=200,
            )

        mixin = mixin_factory({"question": "Test question"})
        mixin._create_debate_direct = capture_direct
        mixin._debate_this(mixin)
        assert called_body.get("auto_select") is True

    def test_context_passed_through(self, mixin_factory):
        """Optional context is forwarded to debate creation."""
        called_body = {}

        def capture_direct(handler, body, scope):
            called_body.update(body)
            from aragora.server.handlers.base import json_response

            return json_response(
                {"success": True, "debate_id": "adhoc_test", "status": "starting"},
                status=200,
            )

        mixin = mixin_factory({"question": "Test?", "context": "Background info"})
        mixin._create_debate_direct = capture_direct
        mixin._debate_this(mixin)
        assert called_body.get("context") == "Background info"

    def test_source_in_metadata(self, mixin_factory):
        """Source is captured in metadata."""
        called_body = {}

        def capture_direct(handler, body, scope):
            called_body.update(body)
            from aragora.server.handlers.base import json_response

            return json_response(
                {"success": True, "debate_id": "adhoc_test", "status": "starting"},
                status=200,
            )

        mixin = mixin_factory({"question": "Test?", "source": "pulse"})
        mixin._create_debate_direct = capture_direct
        mixin._debate_this(mixin)
        assert called_body.get("metadata", {}).get("source") == "pulse"

    def test_default_source_is_debate_this(self, mixin_factory):
        """Default source is 'debate_this' when not specified."""
        called_body = {}

        def capture_direct(handler, body, scope):
            called_body.update(body)
            from aragora.server.handlers.base import json_response

            return json_response(
                {"success": True, "debate_id": "adhoc_test", "status": "starting"},
                status=200,
            )

        mixin = mixin_factory({"question": "Test?"})
        mixin._create_debate_direct = capture_direct
        mixin._debate_this(mixin)
        assert called_body.get("metadata", {}).get("source") == "debate_this"

    def test_rounds_override_respected(self, mixin_factory):
        """Explicit rounds in body overrides auto-detection."""
        called_body = {}

        def capture_direct(handler, body, scope):
            called_body.update(body)
            from aragora.server.handlers.base import json_response

            return json_response(
                {"success": True, "debate_id": "adhoc_test", "status": "starting"},
                status=200,
            )

        mixin = mixin_factory({"question": "Short q?", "rounds": 7})
        mixin._create_debate_direct = capture_direct
        mixin._debate_this(mixin)
        assert called_body.get("rounds") == 7
