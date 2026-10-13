"""
Tests for aragora.server.middleware.tracing - Distributed tracing middleware.

Tests cover:
- ID generation (trace IDs, span IDs)
- Context variable getters/setters
- Span dataclass (tags, events, errors, duration, serialization)
- trace_context context manager (propagation, nesting, error handling)
- traced decorator (sync and async functions)
- TracingMiddleware (setup, header extraction, response headers, request spans)
- WebSocket tracing helpers
- Error response tracing
- init_tracing / shutdown_tracing with disabled OTel
"""

from __future__ import annotations

import asyncio
import time
from contextvars import copy_context
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_tracing_context():
    """Reset tracing context vars to prevent cross-test contamination."""
    from aragora.observability.middleware.tracing import (
        _trace_id,
        _span_id,
        _parent_span_id,
        _span_stack,
    )

    tokens = [
        _trace_id.set(None),
        _span_id.set(None),
        _parent_span_id.set(None),
        _span_stack.set([]),
    ]
    yield
    for var, tok in zip([_trace_id, _span_id, _parent_span_id, _span_stack], tokens):
        var.reset(tok)


# ===========================================================================
# ID Generation
# ===========================================================================


class TestIDGeneration:
    """Tests for trace and span ID generation."""

    def test_generate_trace_id_is_32_hex_chars(self):
        """generate_trace_id returns a 32-character hex string."""
        from aragora.observability.middleware.tracing import generate_trace_id

        tid = generate_trace_id()
        assert len(tid) == 32
        int(tid, 16)  # should not raise

    def test_generate_trace_id_unique(self):
        """Each call produces a unique trace ID."""
        from aragora.observability.middleware.tracing import generate_trace_id

        ids = {generate_trace_id() for _ in range(50)}
        assert len(ids) == 50

    def test_generate_span_id_is_16_hex_chars(self):
        """generate_span_id returns a 16-character hex string."""
        from aragora.observability.middleware.tracing import generate_span_id

        sid = generate_span_id()
        assert len(sid) == 16
        int(sid, 16)  # should not raise


# ===========================================================================
# Context Variable Getters / Setters
# ===========================================================================


class TestContextVars:
    """Tests for trace context variable accessors."""

    def test_get_trace_id_default_none(self):
        """get_trace_id returns None when no trace context is set."""
        from aragora.observability.middleware.tracing import get_trace_id

        ctx = copy_context()
        result = ctx.run(get_trace_id)
        assert result is None

    def test_set_and_get_trace_id(self):
        """set_trace_id stores a value retrievable by get_trace_id."""
        from aragora.observability.middleware.tracing import get_trace_id, set_trace_id

        def _run():
            set_trace_id("abc123")
            return get_trace_id()

        ctx = copy_context()
        assert ctx.run(_run) == "abc123"

    def test_set_and_get_span_id(self):
        """set_span_id stores a value retrievable by get_span_id."""
        from aragora.observability.middleware.tracing import get_span_id, set_span_id

        def _run():
            set_span_id("span999")
            return get_span_id()

        ctx = copy_context()
        assert ctx.run(_run) == "span999"

    def test_get_parent_span_id_default_none(self):
        """get_parent_span_id returns None when unset."""
        from aragora.observability.middleware.tracing import get_parent_span_id

        ctx = copy_context()
        assert ctx.run(get_parent_span_id) is None


# ===========================================================================
# Span Dataclass
# ===========================================================================


class TestSpan:
    """Tests for the Span dataclass."""

    def _make_span(self, **kwargs):
        from aragora.observability.middleware.tracing import Span

        defaults = {
            "trace_id": "t" * 32,
            "span_id": "s" * 16,
            "operation": "test.op",
        }
        defaults.update(kwargs)
        return Span(**defaults)

    def test_set_tag(self):
        """set_tag stores key-value pairs on the span."""
        span = self._make_span()
        span.set_tag("http.method", "GET")
        assert span.tags["http.method"] == "GET"

    def test_add_event(self):
        """add_event appends an event with timestamp and attributes."""
        span = self._make_span()
        span.add_event("checkpoint", {"step": 1})
        assert len(span.events) == 1
        evt = span.events[0]
        assert evt["name"] == "checkpoint"
        assert evt["attributes"]["step"] == 1
        assert "timestamp" in evt

    def test_set_error_marks_status(self):
        """set_error sets status to 'error' and records exception info."""
        span = self._make_span()
        span.set_error(ValueError("bad value"))
        assert span.status == "error"
        assert "ValueError" in span.error
        assert "bad value" in span.error
        # Should also add an exception event
        assert any(e["name"] == "exception" for e in span.events)

    def test_finish_sets_end_time(self):
        """finish sets the end_time on the span."""
        span = self._make_span()
        assert span.end_time is None
        with patch("aragora.server.middleware.tracing.Span.finish", wraps=span.finish):
            span.finish()
        assert span.end_time is not None
        assert span.end_time >= span.start_time

    def test_duration_ms_before_finish(self):
        """duration_ms returns elapsed time even before finish."""
        span = self._make_span(start_time=time.time() - 0.1)
        dur = span.duration_ms
        assert dur >= 100.0  # at least 100ms

    def test_to_dict_keys(self):
        """to_dict returns all expected keys."""
        span = self._make_span()
        span.finish()
        d = span.to_dict()
        expected_keys = {
            "trace_id",
            "span_id",
            "parent_span_id",
            "operation",
            "start_time",
            "end_time",
            "duration_ms",
            "status",
            "error",
            "tags",
            "events",
        }
        assert expected_keys == set(d.keys())

    def test_to_dict_duration_rounded(self):
        """to_dict duration_ms is rounded to 2 decimal places."""
        span = self._make_span()
        span.finish()
        d = span.to_dict()
        dur_str = str(d["duration_ms"])
        if "." in dur_str:
            assert len(dur_str.split(".")[1]) <= 2


# ===========================================================================
# trace_context Context Manager
# ===========================================================================


class TestTraceContext:
    """Tests for the trace_context context manager."""

    def test_trace_context_creates_span(self):
        """trace_context yields a Span with correct operation name."""
        from aragora.observability.middleware.tracing import trace_context

        def _run():
            with trace_context("my.operation") as span:
                assert span.operation == "my.operation"
                assert span.trace_id
                assert span.span_id

        copy_context().run(_run)

    def test_trace_context_finishes_span(self):
        """Span is finished after exiting the context manager."""
        from aragora.observability.middleware.tracing import trace_context

        captured = {}

        def _run():
            with trace_context("op") as span:
                captured["span"] = span
            assert captured["span"].end_time is not None

        copy_context().run(_run)

    def test_trace_context_propagates_trace_id(self):
        """Nested trace_context inherits the parent trace ID."""
        from aragora.observability.middleware.tracing import trace_context

        def _run():
            with trace_context("parent") as parent_span:
                parent_tid = parent_span.trace_id
                with trace_context("child") as child_span:
                    assert child_span.trace_id == parent_tid
                    assert child_span.parent_span_id == parent_span.span_id

        copy_context().run(_run)

    def test_trace_context_records_error(self):
        """trace_context records exceptions on the span and re-raises."""
        from aragora.observability.middleware.tracing import trace_context

        captured = {}

        def _run():
            with pytest.raises(RuntimeError):
                with trace_context("failing") as span:
                    captured["span"] = span
                    raise RuntimeError("boom")
            assert captured["span"].status == "error"
            assert "RuntimeError" in captured["span"].error

        copy_context().run(_run)

    def test_trace_context_restores_context(self):
        """Context variables are restored after trace_context exits."""
        from aragora.observability.middleware.tracing import (
            get_trace_id,
            set_trace_id,
            trace_context,
        )

        def _run():
            set_trace_id("original")
            with trace_context("inner"):
                pass
            assert get_trace_id() == "original"

        copy_context().run(_run)


# ===========================================================================
# traced Decorator
# ===========================================================================


class TestTracedDecorator:
    """Tests for the @traced decorator."""

    def test_traced_sync_function(self):
        """@traced wraps a sync function and creates a span."""
        from aragora.observability.middleware.tracing import traced

        @traced("sync.op")
        def my_func(x):
            return x * 2

        def _run():
            result = my_func(5)
            assert result == 10

        copy_context().run(_run)

    def test_traced_async_function(self):
        """@traced wraps an async function and creates a span."""
        from aragora.observability.middleware.tracing import traced

        @traced("async.op")
        async def my_async_func(x):
            return x + 1

        async def _run():
            result = await my_async_func(7)
            assert result == 8

        asyncio.run(_run())

    def test_traced_defaults_to_function_name(self):
        """@traced() uses function name when no operation is given."""
        from aragora.observability.middleware.tracing import traced

        @traced()
        def special_function():
            return 42

        assert special_function.__name__ == "special_function"


# ===========================================================================
# TracingMiddleware
# ===========================================================================


class TestTracingMiddleware:
    """Tests for the TracingMiddleware class."""

    def _make_middleware(self, service_name="test-svc"):
        from aragora.observability.middleware.tracing import TracingMiddleware

        return TracingMiddleware(service_name=service_name)

    def test_default_service_name(self):
        """Default service name is 'aragora'."""
        from aragora.observability.middleware.tracing import TracingMiddleware

        mw = TracingMiddleware()
        assert mw.service_name == "aragora"

    def test_extract_trace_id_from_custom_header(self):
        """extract_trace_id reads X-Trace-ID header."""
        mw = self._make_middleware()
        headers = {"X-Trace-ID": "abc123def456"}
        assert mw.extract_trace_id(headers) == "abc123def456"

    def test_extract_trace_id_from_traceparent(self):
        """extract_trace_id parses W3C traceparent header."""
        mw = self._make_middleware()
        tid = "a" * 32
        headers = {"traceparent": f"00-{tid}-{'b' * 16}-01"}
        assert mw.extract_trace_id(headers) == tid

    def test_extract_trace_id_generates_new(self):
        """extract_trace_id generates a new ID when no header present."""
        mw = self._make_middleware()
        tid = mw.extract_trace_id({})
        assert len(tid) == 32

    def test_extract_parent_span_id_from_header(self):
        """extract_parent_span_id reads X-Parent-Span-ID header."""
        mw = self._make_middleware()
        headers = {"X-Parent-Span-ID": "parentspan123456"}
        assert mw.extract_parent_span_id(headers) == "parentspan123456"

    def test_extract_parent_span_id_from_traceparent(self):
        """extract_parent_span_id parses W3C traceparent for parent span."""
        mw = self._make_middleware()
        parent = "c" * 16
        headers = {"traceparent": f"00-{'a' * 32}-{parent}-01"}
        assert mw.extract_parent_span_id(headers) == parent

    def test_extract_parent_span_id_none_when_missing(self):
        """extract_parent_span_id returns None when no header present."""
        mw = self._make_middleware()
        assert mw.extract_parent_span_id({}) is None

    def test_set_response_headers(self):
        """set_response_headers adds trace and span headers."""
        mw = self._make_middleware()
        headers = {}
        mw.set_response_headers(headers, "trace123", "span456")
        assert headers["X-Trace-ID"] == "trace123"
        assert headers["X-Span-ID"] == "span456"

    def test_set_response_headers_no_span(self):
        """set_response_headers omits span header when not provided."""
        mw = self._make_middleware()
        headers = {}
        mw.set_response_headers(headers, "trace123")
        assert "X-Trace-ID" in headers
        assert "X-Span-ID" not in headers

    def test_start_request_span_tags(self):
        """start_request_span creates a span with HTTP method, path, and service tags."""
        mw = self._make_middleware(service_name="my-svc")

        def _run():
            span = mw.start_request_span("POST", "/api/debates", {})
            assert span.operation == "POST /api/debates"
            assert span.tags["http.method"] == "POST"
            assert span.tags["http.path"] == "/api/debates"
            assert span.tags["service"] == "my-svc"

        copy_context().run(_run)

    def test_finish_request_span_success(self):
        """finish_request_span sets status code tag on success."""
        mw = self._make_middleware()

        def _run():
            span = mw.start_request_span("GET", "/health", {})
            mw.finish_request_span(span, 200)
            assert span.tags["http.status_code"] == 200
            assert span.status == "ok"
            assert span.end_time is not None

        copy_context().run(_run)

    def test_finish_request_span_client_error(self):
        """finish_request_span marks 4xx as error status."""
        mw = self._make_middleware()

        def _run():
            span = mw.start_request_span("GET", "/missing", {})
            mw.finish_request_span(span, 404)
            assert span.status == "error"
            assert span.error == "HTTP 404"

        copy_context().run(_run)

    def test_finish_request_span_with_exception(self):
        """finish_request_span records exception details."""
        mw = self._make_middleware()

        def _run():
            span = mw.start_request_span("POST", "/fail", {})
            mw.finish_request_span(span, 500, error=RuntimeError("internal"))
            assert span.status == "error"
            assert "RuntimeError" in span.error

        copy_context().run(_run)


# ===========================================================================
# WebSocket Tracing
# ===========================================================================


class TestWebSocketTracing:
    """Tests for WebSocket tracing helpers."""

    def test_trace_websocket_event_adds_trace_context(self):
        """trace_websocket_event adds _trace when trace context exists."""
        from aragora.observability.middleware.tracing import set_trace_id, trace_websocket_event

        def _run():
            set_trace_id("ws-trace-id")
            data = trace_websocket_event("message", {"text": "hi"})
            assert data["_trace"]["trace_id"] == "ws-trace-id"
            assert data["text"] == "hi"

        copy_context().run(_run)

    def test_trace_websocket_event_no_context(self):
        """trace_websocket_event skips _trace when no trace context."""
        from aragora.observability.middleware.tracing import trace_websocket_event

        def _run():
            data = trace_websocket_event("ping", {"seq": 1})
            assert "_trace" not in data
            assert data["seq"] == 1

        copy_context().run(_run)

    def test_extract_websocket_trace(self):
        """extract_websocket_trace retrieves trace_id from event data."""
        from aragora.observability.middleware.tracing import extract_websocket_trace

        data = {"_trace": {"trace_id": "extracted-id"}}
        assert extract_websocket_trace(data) == "extracted-id"

    def test_extract_websocket_trace_missing(self):
        """extract_websocket_trace returns None when no trace data."""
        from aragora.observability.middleware.tracing import extract_websocket_trace

        assert extract_websocket_trace({}) is None


# ===========================================================================
# Error Response Tracing
# ===========================================================================


class TestErrorTracing:
    """Tests for error response tracing."""

    def test_add_trace_to_error_with_context(self):
        """add_trace_to_error adds trace_id to error response."""
        from aragora.observability.middleware.tracing import add_trace_to_error, set_trace_id

        def _run():
            set_trace_id("err-trace-123")
            resp = add_trace_to_error({"error": "not found"})
            assert resp["trace_id"] == "err-trace-123"
            assert resp["error"] == "not found"

        copy_context().run(_run)

    def test_add_trace_to_error_without_context(self):
        """add_trace_to_error leaves response unchanged when no trace."""
        from aragora.observability.middleware.tracing import add_trace_to_error

        def _run():
            resp = add_trace_to_error({"error": "oops"})
            assert "trace_id" not in resp

        copy_context().run(_run)


# ===========================================================================
# init_tracing / shutdown_tracing (disabled path)
# ===========================================================================


class TestInitShutdown:
    """Tests for init_tracing and shutdown_tracing when OTel is unavailable."""

    def test_init_tracing_returns_false_without_otel(self):
        """init_tracing returns False when otel_bridge is not importable."""
        from aragora.observability.middleware.tracing import init_tracing

        with patch(
            "aragora.server.middleware.tracing.init_tracing",
            wraps=init_tracing,
        ):
            # The actual import of otel_bridge may or may not succeed;
            # force ImportError to test the fallback path.
            with patch.dict(
                "sys.modules",
                {"aragora.server.middleware.otel_bridge": None},
            ):
                result = init_tracing()
                assert result is False

    def test_shutdown_tracing_no_error_without_otel(self):
        """shutdown_tracing does not raise when otel_bridge is unavailable."""
        from aragora.observability.middleware.tracing import shutdown_tracing

        with patch.dict(
            "sys.modules",
            {"aragora.server.middleware.otel_bridge": None},
        ):
            shutdown_tracing()  # should not raise
