"""Integration tests for the landing page debate funnel.

Covers the full flow:
  POST /api/v1/playground/debate  →  debate result  →  share_token/share_url present
  GET  /api/v1/debates/public/{id} →  public viewer returns debate

Uses handler-direct invocation (no live server) to keep tests deterministic
and fast without real API keys.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.e2e


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_http_handler(body: dict, client_ip: str = "10.0.0.1") -> MagicMock:
    """Build a minimal mock of http.server.BaseHTTPRequestHandler."""
    raw = json.dumps(body).encode()
    h = MagicMock()
    h.client_address = (client_ip, 12345)
    h.headers = MagicMock()
    h.headers.get = lambda k, d="": {
        "Content-Length": str(len(raw)),
        "Content-Type": "application/json",
    }.get(k, d)
    h.rfile = MagicMock()
    h.rfile.read = MagicMock(return_value=raw)
    return h


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def _shared_debate_store(tmp_path, monkeypatch):
    """Shared temp debate store for both playground and public viewer."""
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path))
    import aragora.storage.debate_store as mod

    monkeypatch.setattr(mod, "_store", None)
    return mod


@pytest.fixture()
def playground_handler(_shared_debate_store, monkeypatch):
    """PlaygroundHandler backed by a temp debate store."""
    from aragora.server.handlers.playground import PlaygroundHandler, _reset_rate_limits

    _reset_rate_limits()
    yield PlaygroundHandler()
    _reset_rate_limits()


@pytest.fixture()
def public_viewer_handler(_shared_debate_store):
    """PublicDebateViewerHandler sharing the same temp debate store."""
    from aragora.server.handlers.debates.public_viewer import (
        PublicDebateViewerHandler,
        _reset_public_viewer_rate_limits,
    )

    _reset_public_viewer_rate_limits()
    yield PublicDebateViewerHandler()
    _reset_public_viewer_rate_limits()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_landing_debate_produces_shareable_result(playground_handler):
    """Full landing funnel: question → debate → share_token in response."""
    h = _make_http_handler(
        {
            "question": "Should we standardize on Python 3.11 for all services?",
            "source": "landing",
        }
    )

    result = playground_handler.handle_post("/api/v1/playground/debate", {}, h)

    assert result is not None
    assert result.status_code == 200
    body = json.loads(result.body.decode("utf-8"))

    # Core debate identity
    assert "id" in body or "debate_id" in body, f"No debate ID in response: {list(body.keys())}"
    assert "status" in body

    # Share capability — share_token is required (share_url is also expected alongside it)
    assert "share_token" in body, f"Missing share_token in response: {list(body.keys())}"
    assert body["share_token"], "share_token must be non-empty"


def test_landing_debate_consensus_fields(playground_handler):
    """Verify consensus and receipt fields are present in landing debate response."""
    h = _make_http_handler(
        {
            "question": "Should we use GraphQL or REST for our API?",
            "source": "landing",
        }
    )

    result = playground_handler.handle_post("/api/v1/playground/debate", {}, h)

    assert result is not None
    assert result.status_code == 200
    body = json.loads(result.body.decode("utf-8"))

    assert "confidence" in body, f"Missing 'confidence'. Keys: {list(body.keys())}"
    assert "verdict" in body, f"Missing 'verdict'. Keys: {list(body.keys())}"
    assert "final_answer" in body or "consensus_text" in body or "proposals" in body, (
        f"Missing debate content fields. Keys: {list(body.keys())}"
    )


def test_share_token_matches_debate_id(playground_handler):
    """share_token must be the debate ID so the public viewer can look it up."""
    h = _make_http_handler({"topic": "AI regulation in healthcare", "source": "landing"})

    result = playground_handler.handle_post("/api/v1/playground/debate", {}, h)

    assert result is not None
    assert result.status_code == 200
    body = json.loads(result.body.decode("utf-8"))

    debate_id = body.get("id") or body.get("debate_id")
    share_token = body.get("share_token")
    share_url = body.get("share_url", "")

    if share_token is not None:
        assert share_token == debate_id, (
            f"share_token={share_token!r} must equal debate id={debate_id!r}"
        )
    if share_url:
        assert debate_id and debate_id in share_url, (
            f"share_url={share_url!r} must contain debate_id={debate_id!r}"
        )


def test_shared_debate_retrievable_via_public_viewer(playground_handler, public_viewer_handler):
    """End-to-end: debate created → public viewer can retrieve it by ID."""
    # 1. Create a debate
    h = _make_http_handler({"topic": "Should we adopt microservices?", "source": "landing"})
    result = playground_handler.handle_post("/api/v1/playground/debate", {}, h)

    assert result is not None
    assert result.status_code == 200
    body = json.loads(result.body.decode("utf-8"))

    debate_id = body.get("id") or body.get("debate_id")
    assert debate_id, "Debate response must include an id"

    # 2. Retrieve via public viewer
    viewer_result = public_viewer_handler.handle(
        f"/api/v1/debates/public/{debate_id}",
        {},
        MagicMock(client_address=("10.0.0.1", 12345)),
    )

    assert viewer_result is not None
    assert viewer_result.status_code == 200, (
        f"Public viewer returned {viewer_result.status_code} for debate {debate_id}"
    )
    viewer_body = json.loads(viewer_result.body.decode("utf-8"))
    assert viewer_body.get("id") == debate_id or viewer_body.get("topic"), (
        "Public viewer response must include the debate content"
    )


def test_mock_debate_source_landing_sets_share_fields(playground_handler):
    """With source=landing, the inline mock path must also set share fields."""
    h = _make_http_handler({"topic": "Climate change mitigation strategies", "source": "landing"})

    result = playground_handler.handle_post("/api/v1/playground/debate", {}, h)

    assert result is not None
    assert result.status_code == 200
    body = json.loads(result.body.decode("utf-8"))

    # Even for mock debates, share_token must be present
    assert "share_token" in body, (
        f"Mock landing debate missing share_token. Keys: {list(body.keys())}"
    )
