"""Tests for legacy 'task' field normalization in debate creation.

Requests using the legacy 'task' field must go through the same validation path
as requests using the modern 'question' field, and dual-field requests must not
silently diverge.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from aragora.server.handlers.debates.create import CreateOperationsMixin


class _FakeHandler:
    """Minimal handler protocol stub for testing CreateOperationsMixin."""

    def __init__(self, body: dict | None = None):
        self._body = body
        self.stream_emitter = MagicMock()
        self._check_rate_limit = MagicMock(return_value=True)

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
def mixin_factory():
    """Factory to create mixin with custom body."""

    def _make(body):
        return _Mixin(body=body)

    return _make


@pytest.fixture(autouse=True)
def _bypass_decorators(monkeypatch):
    """Bypass rate limiting, quota, and other decorators for all tests."""
    _noop_decorator = lambda **kw: (lambda fn: fn)
    monkeypatch.setattr("aragora.server.handlers.debates.create.rate_limit", _noop_decorator)
    monkeypatch.setattr("aragora.server.handlers.debates.create.user_rate_limit", _noop_decorator)
    monkeypatch.setattr(
        "aragora.server.handlers.debates.create.require_quota",
        lambda *a, **kw: (lambda fn: fn),
    )


class TestLegacyTaskFieldNormalization:
    """Tests that legacy 'task' field goes through the same validation as 'question'."""

    def test_valid_task_field_is_accepted(self, mixin_factory):
        """A valid 'task' field should be normalized to 'question' and succeed."""
        mixin = mixin_factory({"task": "Should we adopt microservices for our backend?"})
        result = mixin._create_debate(mixin)
        assert result.status_code == 200

    def test_task_field_normalized_to_question(self, mixin_factory):
        """The 'task' field should be moved to 'question' in the body."""
        captured_body = {}

        def capture_direct(handler, body, scope):
            captured_body.update(body)
            from aragora.server.handlers.base import json_response

            return json_response(
                {"success": True, "debate_id": "test", "status": "starting"},
                status=200,
            )

        mixin = mixin_factory({"task": "Should we adopt microservices for our backend?"})
        mixin._create_debate_direct = capture_direct
        result = mixin._create_debate(mixin)
        assert result.status_code == 200
        assert "question" in captured_body
        assert captured_body["question"] == "Should we adopt microservices for our backend?"

    def test_excessively_long_task_is_rejected(self, mixin_factory):
        """A 'task' field exceeding max_length should be rejected (400 from schema or 422 from Pydantic)."""
        long_task = "A" * 2500  # Exceeds the 2000 char limit
        mixin = mixin_factory({"task": long_task})
        result = mixin._create_debate(mixin)
        # Schema validation catches this first at 400; either way it's rejected
        assert result.status_code in (400, 422)

    def test_too_short_task_is_rejected(self, mixin_factory):
        """A 'task' field below min_length should be rejected with 422."""
        mixin = mixin_factory({"task": "Short"})  # Less than 10 chars
        result = mixin._create_debate(mixin)
        assert result.status_code == 422

    def test_matching_task_and_question_are_accepted(self, mixin_factory):
        """Dual-field requests may pass only when both values match."""
        text = "Should we adopt microservices for our backend?"
        mixin = mixin_factory({"task": text, "question": text})
        result = mixin._create_debate(mixin)
        assert result.status_code == 200

    def test_mismatched_task_and_question_are_rejected(self, mixin_factory):
        """Conflicting legacy/modern values must fail instead of silently winning."""
        mixin = mixin_factory(
            {
                "task": "This is the legacy task field value",
                "question": "This is the modern question field value",
            }
        )
        result = mixin._create_debate(mixin)
        assert result.status_code == 422

    def test_task_field_removed_after_normalization(self, mixin_factory):
        """After normalization, only 'question' should remain (task popped)."""
        captured_body = {}

        def capture_direct(handler, body, scope):
            captured_body.update(body)
            from aragora.server.handlers.base import json_response

            return json_response(
                {"success": True, "debate_id": "test", "status": "starting"},
                status=200,
            )

        mixin = mixin_factory({"task": "Should we adopt microservices for our backend?"})
        mixin._create_debate_direct = capture_direct
        mixin._create_debate(mixin)
        # 'task' should have been popped
        assert "task" not in captured_body

    def test_task_only_request_gets_pydantic_validation(self, mixin_factory):
        """Requests with only 'task' must go through Pydantic validation (not bypass it)."""
        # Whitespace-only task should be caught by Pydantic's question_not_empty validator
        mixin = mixin_factory({"task": "          "})  # 10+ spaces but blank after strip
        result = mixin._create_debate(mixin)
        assert result.status_code == 422

    def test_task_with_extra_fields_validated(self, mixin_factory):
        """Extra fields like rounds should still be validated when using 'task'."""
        mixin = mixin_factory(
            {
                "task": "Should we adopt microservices for our backend?",
                "rounds": 100,  # Exceeds max in schema (20) and Pydantic (10)
            }
        )
        result = mixin._create_debate(mixin)
        # Schema validation catches this first at 400; either way it's rejected
        assert result.status_code in (400, 422)

    def test_question_field_still_works(self, mixin_factory):
        """Standard 'question' field requests should continue to work."""
        mixin = mixin_factory({"question": "Should we adopt microservices for our backend?"})
        result = mixin._create_debate(mixin)
        assert result.status_code == 200
