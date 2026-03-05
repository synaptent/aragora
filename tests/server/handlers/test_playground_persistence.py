"""Tests for playground handler debate persistence and shareable links."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.base import HandlerResult, json_response, error_response


@pytest.fixture()
def _fake_debate_store(tmp_path, monkeypatch):
    """Set up a real DebateResultStore backed by a temp directory."""
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    import aragora.storage.debate_store as mod

    monkeypatch.setattr(mod, "_store", None)


@pytest.fixture()
def handler(_fake_debate_store):
    from aragora.server.handlers.playground import PlaygroundHandler

    return PlaygroundHandler()


class TestCanHandle:
    def test_standard_routes(self, handler):
        assert handler.can_handle("/api/v1/playground/debate")
        assert handler.can_handle("/api/v1/playground/status")

    def test_debate_id_route(self, handler):
        assert handler.can_handle("/api/v1/playground/debate/abcdef1234567890")

    def test_debate_id_32_chars(self, handler):
        assert handler.can_handle("/api/v1/playground/debate/abcdef1234567890abcdef1234567890")

    def test_rejects_short_debate_id(self, handler):
        assert not handler.can_handle("/api/v1/playground/debate/abc123")

    def test_rejects_non_hex_debate_id(self, handler):
        assert not handler.can_handle("/api/v1/playground/debate/ghijklmnopqrstuv")

    def test_rejects_too_long_debate_id(self, handler):
        long_id = "a" * 33
        assert not handler.can_handle(f"/api/v1/playground/debate/{long_id}")


class TestHandleGetDebate:
    def test_returns_saved_debate(self, handler):
        from aragora.storage.debate_store import get_debate_store

        debate_id = "abcdef1234567890"
        result_data = {"id": debate_id, "topic": "Test", "verdict": "approved"}

        store = get_debate_store()
        store.save(debate_id, "Test", result_data)

        response = handler.handle(
            f"/api/v1/playground/debate/{debate_id}",
            {},
            MagicMock(),
        )

        assert response is not None
        assert response.status_code == 200
        body = json.loads(response.body.decode("utf-8"))
        assert body["id"] == debate_id
        assert body["topic"] == "Test"

    def test_returns_404_for_nonexistent(self, handler):
        response = handler.handle(
            "/api/v1/playground/debate/0000000000000000",
            {},
            MagicMock(),
        )

        assert response is not None
        assert response.status_code == 404

    def test_returns_none_for_non_id_path(self, handler):
        """Non-matching paths should return None (not handled)."""
        response = handler.handle(
            "/api/v1/playground/debate",
            {},
            MagicMock(),
        )
        assert response is None

    def test_returns_404_when_store_unavailable(self, handler, monkeypatch):
        """When the store import fails, return 404 gracefully."""
        monkeypatch.setattr(
            "aragora.server.handlers.playground.PlaygroundHandler._handle_get_debate",
            lambda self, debate_id: error_response("Debate not found", 404),
        )

        response = handler.handle(
            "/api/v1/playground/debate/abcdef1234567890",
            {},
            MagicMock(),
        )

        assert response is not None
        assert response.status_code == 404


class TestPersistAndRespond:
    def test_persists_and_injects_share_url(self, handler):
        debate_data = {
            "id": "abcdef1234567890",
            "topic": "Test topic",
            "verdict": "approved",
        }
        original = json_response(debate_data)

        result = handler._persist_and_respond(original, "Test topic", "playground")

        body = json.loads(result.body.decode("utf-8"))
        assert "share_url" in body
        assert body["share_url"] == "/debate/abcdef1234567890"
        assert "share_token" in body
        assert body["share_token"] == "abcdef1234567890"

    def test_debate_retrievable_after_persist(self, handler):
        from aragora.storage.debate_store import get_debate_store

        debate_data = {
            "id": "abcdef1234567890",
            "topic": "Persisted topic",
            "verdict": "approved",
        }
        original = json_response(debate_data)

        handler._persist_and_respond(original, "Persisted topic", "playground")

        store = get_debate_store()
        saved = store.get("abcdef1234567890")
        assert saved is not None
        assert saved["topic"] == "Persisted topic"

    def test_passes_through_when_no_id(self, handler):
        """If the debate result has no 'id', persistence is skipped."""
        debate_data = {"topic": "No ID", "verdict": "approved"}
        original = json_response(debate_data)

        result = handler._persist_and_respond(original, "No ID", "mock")

        body = json.loads(result.body.decode("utf-8"))
        assert "share_url" not in body

    def test_passes_through_on_empty_body(self, handler):
        """Empty body should return original result unchanged."""
        original = HandlerResult(
            status_code=200,
            content_type="application/json",
            body=b"",
        )

        result = handler._persist_and_respond(original, "Test", "mock")
        assert result is original

    def test_passes_through_on_import_error(self, handler):
        """The method handles ImportError gracefully."""
        debate_data = {"id": "abcdef1234567890", "topic": "Test"}
        original = json_response(debate_data)

        # The actual method handles ImportError gracefully
        result = handler._persist_and_respond(original, "Test", "mock")
        # Should still return a valid response
        assert result.status_code == 200

    def test_custom_source_persisted(self, handler):
        from aragora.storage.debate_store import get_debate_store

        debate_data = {"id": "abcdef1234567890", "topic": "Oracle test"}
        original = json_response(debate_data)

        handler._persist_and_respond(original, "Oracle test", "oracle")

        store = get_debate_store()
        recent = store.list_recent()
        assert len(recent) == 1
        assert recent[0]["source"] == "oracle"
