"""Tests for read_json_body handling missing Content-Length and chunked encoding.

Covers Cloudflare HTTP/2 -> HTTP/1.1 proxy scenarios where Content-Length
may be absent or zero even though the request body contains data.
"""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest


@pytest.fixture()
def handler_base():
    """Create a minimal BaseHandler instance for testing."""
    from aragora.server.handlers.base import BaseHandler

    return BaseHandler(server_context={})


def _make_handler(body: bytes, headers: dict[str, str]) -> SimpleNamespace:
    """Build a fake HTTP handler with rfile and headers."""
    return SimpleNamespace(
        rfile=io.BytesIO(body),
        headers=headers,
    )


class TestReadJsonBodyChunked:
    """Test read_json_body with various Content-Length / Transfer-Encoding scenarios."""

    def test_normal_content_length(self, handler_base):
        """Normal case: Content-Length present and correct -> parses JSON."""
        payload = {"username": "alice", "password": "secret"}
        body = json.dumps(payload).encode()
        handler = _make_handler(body, {"Content-Length": str(len(body))})

        result = handler_base.read_json_body(handler)

        assert result == payload

    def test_missing_content_length(self, handler_base):
        """Missing Content-Length: body exists but CL absent -> should still parse."""
        payload = {"email": "bob@example.com"}
        body = json.dumps(payload).encode()
        # No Content-Length header at all
        handler = _make_handler(body, {})

        result = handler_base.read_json_body(handler)

        assert result == payload

    def test_content_length_zero_but_body_exists(self, handler_base):
        """Cloudflare scenario: CL=0 but body has data -> should still parse."""
        payload = {"action": "register", "name": "Charlie"}
        body = json.dumps(payload).encode()
        handler = _make_handler(body, {"Content-Length": "0"})

        result = handler_base.read_json_body(handler)

        assert result == payload

    def test_transfer_encoding_chunked(self, handler_base):
        """Transfer-Encoding: chunked -> should read and parse body."""
        payload = {"stream": True, "data": [1, 2, 3]}
        body = json.dumps(payload).encode()
        handler = _make_handler(
            body,
            {"Transfer-Encoding": "chunked", "Content-Length": "0"},
        )

        result = handler_base.read_json_body(handler)

        assert result == payload

    def test_empty_body_with_cl_zero(self, handler_base):
        """Empty body with CL=0 -> returns empty dict."""
        handler = _make_handler(b"", {"Content-Length": "0"})

        result = handler_base.read_json_body(handler)

        assert result == {}

    def test_empty_body_no_headers(self, handler_base):
        """Truly empty body with no Content-Length -> returns empty dict."""
        handler = _make_handler(b"", {})

        result = handler_base.read_json_body(handler)

        assert result == {}

    def test_invalid_json(self, handler_base):
        """Invalid JSON body -> returns None."""
        body = b"not valid json {{"
        handler = _make_handler(body, {"Content-Length": str(len(body))})

        result = handler_base.read_json_body(handler)

        assert result is None

    def test_body_exceeds_max_size(self, handler_base):
        """Body larger than max_size -> returns None."""
        payload = {"big": "x" * 200}
        body = json.dumps(payload).encode()
        handler = _make_handler(body, {"Content-Length": str(len(body))})

        result = handler_base.read_json_body(handler, max_size=50)

        assert result is None

    def test_chunked_body_exceeds_max_size(self, handler_base):
        """Chunked body that exceeds max_size after read -> returns None."""
        payload = {"big": "x" * 200}
        body = json.dumps(payload).encode()
        handler = _make_handler(
            body,
            {"Transfer-Encoding": "chunked"},
        )

        result = handler_base.read_json_body(handler, max_size=50)

        # Should return None because the read body exceeds max_size
        assert result is None
