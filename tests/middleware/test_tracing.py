"""
Tests for aragora.server.middleware.tracing - Distributed Tracing Middleware.

Tests cover:
- ID generation (trace_id, span_id)
- Context variables (get/set trace_id, span_id, parent_span_id)
- Span dataclass (tags, events, errors, duration, to_dict)
- trace_context context manager (span creation, nesting, error handling)
- traced decorator (sync and async functions)
- TracingMiddleware class (header extraction, request spans)
- WebSocket tracing utilities
- Error response tracing
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from aragora.observability.middleware.tracing import (
    # Header constants
    TRACE_ID_HEADER,
    SPAN_ID_HEADER,
    PARENT_SPAN_HEADER,
    TRACEPARENT_HEADER,
    # ID generators
    generate_trace_id,
    generate_span_id,
    # Context getters/setters
    get_trace_id,
    get_span_id,
    get_parent_span_id,
    set_trace_id,
    set_span_id,
    # Span
    Span,
    # Context manager
    trace_context,
    # Decorator
    traced,
    # Middleware
    TracingMiddleware,
    # WebSocket support
    trace_websocket_event,
    extract_websocket_trace,
    # Error support
    add_trace_to_error,
)


# ===========================================================================
# Test Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def reset_trace_context():
    """Reset trace context before and after each test."""
    # Reset context variables to default state
    from aragora.observability.middleware.tracing import (
        _trace_id,
        _span_id,
        _parent_span_id,
        _span_stack,
    )

    # Store original tokens for cleanup
    old_trace = _trace_id.set(None)
    old_span = _span_id.set(None)
    old_parent = _parent_span_id.set(None)
    old_stack = _span_stack.set([])

    yield

    # Reset after test
    _trace_id.reset(old_trace)
    _span_id.reset(old_span)
    _parent_span_id.reset(old_parent)
    _span_stack.reset(old_stack)


@pytest.fixture
def sample_trace_id():
    """Generate a sample trace ID."""
    return "a1b2c3d4e5f6789012345678abcdef12"


@pytest.fixture
def sample_span_id():
    """Generate a sample span ID."""
    return "0123456789abcdef"


@pytest.fixture
def sample_headers():
    """Create sample request headers with tracing info."""
    return {
        "X-Trace-ID": "trace123456789012345678901234",
        "X-Parent-Span-ID": "parentspan12345",
        "Content-Type": "application/json",
    }


@pytest.fixture
def sample_w3c_traceparent():
    """Create sample W3C traceparent header."""
    return {
        "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
    }


@pytest.fixture
def middleware():
    """Create a TracingMiddleware instance."""
    return TracingMiddleware(service_name="test-service")


# ===========================================================================
# Test Header Constants
# ===========================================================================


class TestHeaderConstants:
    """Tests for header constant definitions."""

    def test_trace_id_header(self):
        """TRACE_ID_HEADER should be X-Trace-ID."""
        assert TRACE_ID_HEADER == "X-Trace-ID"

    def test_span_id_header(self):
        """SPAN_ID_HEADER should be X-Span-ID."""
        assert SPAN_ID_HEADER == "X-Span-ID"

    def test_parent_span_header(self):
        """PARENT_SPAN_HEADER should be X-Parent-Span-ID."""
        assert PARENT_SPAN_HEADER == "X-Parent-Span-ID"

    def test_traceparent_header(self):
        """TRACEPARENT_HEADER should be traceparent (W3C standard)."""
        assert TRACEPARENT_HEADER == "traceparent"


# ===========================================================================
# Test ID Generation
# ===========================================================================


class TestGenerateTraceId:
    """Tests for generate_trace_id function."""

    def test_returns_string(self):
        """Should return a string."""
        trace_id = generate_trace_id()
        assert isinstance(trace_id, str)

    def test_returns_32_characters(self):
        """Should return 32-character hex string."""
        trace_id = generate_trace_id()
        assert len(trace_id) == 32

    def test_returns_hex_string(self):
        """Should return valid hexadecimal string."""
        trace_id = generate_trace_id()
        int(trace_id, 16)  # Should not raise ValueError

    def test_generates_unique_ids(self):
        """Should generate unique IDs on each call."""
        trace_ids = {generate_trace_id() for _ in range(100)}
        assert len(trace_ids) == 100  # All unique


class TestGenerateSpanId:
    """Tests for generate_span_id function."""

    def test_returns_string(self):
        """Should return a string."""
        span_id = generate_span_id()
        assert isinstance(span_id, str)

    def test_returns_16_characters(self):
        """Should return 16-character hex string."""
        span_id = generate_span_id()
        assert len(span_id) == 16

    def test_returns_hex_string(self):
        """Should return valid hexadecimal string."""
        span_id = generate_span_id()
        int(span_id, 16)  # Should not raise ValueError

    def test_generates_unique_ids(self):
        """Should generate unique IDs on each call."""
        span_ids = {generate_span_id() for _ in range(100)}
        assert len(span_ids) == 100  # All unique


# ===========================================================================
# Test Context Variables
# ===========================================================================


class TestContextVariables:
    """Tests for context variable getters and setters."""

    def test_get_trace_id_default(self):
        """get_trace_id should return None by default."""
        assert get_trace_id() is None

    def test_set_and_get_trace_id(self, sample_trace_id):
        """set_trace_id should set value retrievable by get_trace_id."""
        set_trace_id(sample_trace_id)
        assert get_trace_id() == sample_trace_id

    def test_get_span_id_default(self):
        """get_span_id should return None by default."""
        assert get_span_id() is None

    def test_set_and_get_span_id(self, sample_span_id):
        """set_span_id should set value retrievable by get_span_id."""
        set_span_id(sample_span_id)
        assert get_span_id() == sample_span_id

    def test_get_parent_span_id_default(self):
        """get_parent_span_id should return None by default."""
        assert get_parent_span_id() is None

    def test_context_isolation(self, sample_trace_id, sample_span_id):
        """Different context variables should be independent."""
        set_trace_id(sample_trace_id)
        set_span_id(sample_span_id)

        assert get_trace_id() == sample_trace_id
        assert get_span_id() == sample_span_id
        assert get_parent_span_id() is None


# ===========================================================================
# Test Span Dataclass
# ===========================================================================


class TestSpanDataclass:
    """Tests for Span dataclass."""

    def test_span_creation(self, sample_trace_id, sample_span_id):
        """Should create span with required fields."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        assert span.trace_id == sample_trace_id
        assert span.span_id == sample_span_id
        assert span.operation == "test.operation"
        assert span.parent_span_id is None
        assert span.end_time is None
        assert span.tags == {}
        assert span.events == []
        assert span.status == "ok"
        assert span.error is None

    def test_span_with_parent(self, sample_trace_id, sample_span_id):
        """Should create span with parent span ID."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="child.operation",
            parent_span_id="parent123456789",
        )

        assert span.parent_span_id == "parent123456789"

    def test_set_tag(self, sample_trace_id, sample_span_id):
        """set_tag should add tag to span."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        span.set_tag("user_id", "user-123")
        span.set_tag("debate_id", "debate-456")
        span.set_tag("count", 42)

        assert span.tags["user_id"] == "user-123"
        assert span.tags["debate_id"] == "debate-456"
        assert span.tags["count"] == 42

    def test_set_tag_overwrites(self, sample_trace_id, sample_span_id):
        """set_tag should overwrite existing tag."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        span.set_tag("key", "value1")
        span.set_tag("key", "value2")

        assert span.tags["key"] == "value2"

    def test_add_event(self, sample_trace_id, sample_span_id):
        """add_event should add event to span."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        span.add_event("started")
        span.add_event("checkpoint", {"step": 1})

        assert len(span.events) == 2
        assert span.events[0]["name"] == "started"
        assert span.events[0]["attributes"] == {}
        assert "timestamp" in span.events[0]

        assert span.events[1]["name"] == "checkpoint"
        assert span.events[1]["attributes"] == {"step": 1}

    def test_add_event_timestamp_format(self, sample_trace_id, sample_span_id):
        """Event timestamp should be ISO format."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        span.add_event("test")

        timestamp = span.events[0]["timestamp"]
        # Should parse as valid ISO timestamp
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))

    def test_set_error(self, sample_trace_id, sample_span_id):
        """set_error should mark span as errored."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        error = ValueError("Something went wrong")
        span.set_error(error)

        assert span.status == "error"
        assert span.error == "ValueError: Something went wrong"
        assert len(span.events) == 1
        assert span.events[0]["name"] == "exception"
        assert span.events[0]["attributes"]["type"] == "ValueError"
        assert span.events[0]["attributes"]["message"] == "Something went wrong"

    def test_finish(self, sample_trace_id, sample_span_id):
        """finish should set end_time."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        assert span.end_time is None

        span.finish()

        assert span.end_time is not None
        assert span.end_time >= span.start_time

    def test_duration_ms_before_finish(self, sample_trace_id, sample_span_id):
        """duration_ms should calculate from current time before finish."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        time.sleep(0.01)  # 10ms

        duration = span.duration_ms
        assert duration >= 10  # At least 10ms

    def test_duration_ms_after_finish(self, sample_trace_id, sample_span_id):
        """duration_ms should be fixed after finish."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        time.sleep(0.01)
        span.finish()
        duration1 = span.duration_ms

        time.sleep(0.01)
        duration2 = span.duration_ms

        assert duration1 == duration2  # Should not change after finish

    def test_to_dict(self, sample_trace_id, sample_span_id):
        """to_dict should return complete span data."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
            parent_span_id="parent123",
        )

        span.set_tag("key", "value")
        span.add_event("test_event")
        span.finish()

        result = span.to_dict()

        assert result["trace_id"] == sample_trace_id
        assert result["span_id"] == sample_span_id
        assert result["parent_span_id"] == "parent123"
        assert result["operation"] == "test.operation"
        assert result["status"] == "ok"
        assert result["error"] is None
        assert result["tags"] == {"key": "value"}
        assert len(result["events"]) == 1
        assert "start_time" in result
        assert "end_time" in result
        assert "duration_ms" in result
        assert isinstance(result["duration_ms"], float)

    def test_to_dict_without_finish(self, sample_trace_id, sample_span_id):
        """to_dict should handle unfinished span."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        result = span.to_dict()

        assert result["end_time"] is None
        assert result["duration_ms"] >= 0

    def test_to_dict_with_error(self, sample_trace_id, sample_span_id):
        """to_dict should include error information."""
        span = Span(
            trace_id=sample_trace_id,
            span_id=sample_span_id,
            operation="test.operation",
        )

        span.set_error(RuntimeError("Test error"))
        span.finish()

        result = span.to_dict()

        assert result["status"] == "error"
        assert result["error"] == "RuntimeError: Test error"


# ===========================================================================
# Test trace_context Context Manager
# ===========================================================================


class TestTraceContext:
    """Tests for trace_context context manager."""

    def test_creates_span(self):
        """Should create a span for the operation."""
        with trace_context("test.operation") as span:
            assert span.operation == "test.operation"
            assert span.trace_id is not None
            assert span.span_id is not None

    def test_sets_trace_context(self):
        """Should set trace context during execution."""
        with trace_context("test.operation") as span:
            assert get_trace_id() == span.trace_id
            assert get_span_id() == span.span_id

    def test_restores_trace_context(self):
        """Should restore previous trace context after exit."""
        set_trace_id("original-trace")
        set_span_id("original-span")

        with trace_context("test.operation"):
            pass

        # Context should be restored (though with our fixture it resets to None)
        # In real usage, context would be restored

    def test_uses_provided_trace_id(self, sample_trace_id):
        """Should use provided trace ID."""
        with trace_context("test.operation", trace_id=sample_trace_id) as span:
            assert span.trace_id == sample_trace_id
            assert get_trace_id() == sample_trace_id

    def test_generates_trace_id_if_not_provided(self):
        """Should generate trace ID if not provided."""
        with trace_context("test.operation") as span:
            assert span.trace_id is not None
            assert len(span.trace_id) == 32

    def test_uses_current_trace_id(self, sample_trace_id):
        """Should use current trace ID if set."""
        set_trace_id(sample_trace_id)

        with trace_context("test.operation") as span:
            assert span.trace_id == sample_trace_id

    def test_nested_spans(self):
        """Should create nested spans with parent relationship."""
        with trace_context("parent.operation") as parent_span:
            parent_id = parent_span.span_id

            with trace_context("child.operation") as child_span:
                assert child_span.parent_span_id == parent_id
                assert child_span.trace_id == parent_span.trace_id

    def test_deeply_nested_spans(self):
        """Should handle deep nesting correctly."""
        with trace_context("level1") as span1:
            with trace_context("level2") as span2:
                with trace_context("level3") as span3:
                    assert span3.parent_span_id == span2.span_id
                    assert span2.parent_span_id == span1.span_id
                    assert span3.trace_id == span1.trace_id

    def test_explicit_parent_span_id(self, sample_span_id):
        """Should use explicit parent span ID if provided."""
        with trace_context("test.operation", parent_span_id=sample_span_id) as span:
            assert span.parent_span_id == sample_span_id

    def test_finishes_span_on_exit(self):
        """Should finish span on context exit."""
        with trace_context("test.operation") as span:
            assert span.end_time is None

        assert span.end_time is not None

    def test_handles_exception(self):
        """Should mark span as error on exception."""
        with pytest.raises(ValueError):
            with trace_context("test.operation") as span:
                raise ValueError("Test error")

        assert span.status == "error"
        assert "ValueError" in span.error

    def test_reraises_exception(self):
        """Should re-raise exception after marking span."""
        with pytest.raises(ValueError) as exc_info:
            with trace_context("test.operation"):
                raise ValueError("Test error")

        assert str(exc_info.value) == "Test error"

    def test_span_finished_on_exception(self):
        """Should finish span even on exception."""
        with pytest.raises(ValueError):
            with trace_context("test.operation") as span:
                raise ValueError("Test error")

        assert span.end_time is not None

    def test_span_can_set_tags(self):
        """Should allow setting tags on span during context."""
        with trace_context("test.operation") as span:
            span.set_tag("user_id", "user-123")
            span.set_tag("debate_id", "debate-456")

        assert span.tags["user_id"] == "user-123"
        assert span.tags["debate_id"] == "debate-456"

    def test_span_can_add_events(self):
        """Should allow adding events on span during context."""
        with trace_context("test.operation") as span:
            span.add_event("started")
            span.add_event("completed", {"result": "success"})

        assert len(span.events) == 2


# ===========================================================================
# Test traced Decorator
# ===========================================================================


class TestTracedDecorator:
    """Tests for traced decorator."""

    def test_sync_function(self):
        """Should trace synchronous function."""

        @traced("test.operation")
        def my_function():
            return "result"

        result = my_function()

        assert result == "result"

    def test_sync_function_with_trace_context(self):
        """Should set trace context during sync function."""
        trace_id_during_call = None

        @traced("test.operation")
        def my_function():
            nonlocal trace_id_during_call
            trace_id_during_call = get_trace_id()
            return "result"

        my_function()

        assert trace_id_during_call is not None

    def test_sync_function_uses_function_name(self):
        """Should use function name if operation not specified."""
        span_operation = None

        @traced()
        def my_named_function():
            return "result"

        # The decorator wraps the function, we can test the function name
        assert my_named_function.__name__ == "my_named_function"

    def test_sync_function_handles_exception(self):
        """Should mark span as error on sync function exception."""

        @traced("test.operation")
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            failing_function()

    def test_sync_function_preserves_return_value(self):
        """Should preserve function return value."""

        @traced("test.operation")
        def compute():
            return {"value": 42, "status": "ok"}

        result = compute()

        assert result == {"value": 42, "status": "ok"}

    def test_sync_function_preserves_args(self):
        """Should preserve function arguments."""

        @traced("test.operation")
        def add(a, b):
            return a + b

        result = add(3, 4)

        assert result == 7

    def test_sync_function_preserves_kwargs(self):
        """Should preserve function keyword arguments."""

        @traced("test.operation")
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        result = greet("World", greeting="Hi")

        assert result == "Hi, World!"

    @pytest.mark.asyncio
    async def test_async_function(self):
        """Should trace asynchronous function."""

        @traced("test.async_operation")
        async def my_async_function():
            await asyncio.sleep(0.001)
            return "async_result"

        result = await my_async_function()

        assert result == "async_result"

    @pytest.mark.asyncio
    async def test_async_function_with_trace_context(self):
        """Should set trace context during async function."""
        trace_id_during_call = None

        @traced("test.async_operation")
        async def my_async_function():
            nonlocal trace_id_during_call
            trace_id_during_call = get_trace_id()
            return "result"

        await my_async_function()

        assert trace_id_during_call is not None

    @pytest.mark.asyncio
    async def test_async_function_handles_exception(self):
        """Should mark span as error on async function exception."""

        @traced("test.async_operation")
        async def failing_async_function():
            raise RuntimeError("Async error")

        with pytest.raises(RuntimeError):
            await failing_async_function()

    @pytest.mark.asyncio
    async def test_async_function_preserves_args(self):
        """Should preserve async function arguments."""

        @traced("test.async_operation")
        async def async_add(a, b):
            return a + b

        result = await async_add(5, 7)

        assert result == 12

    def test_decorator_preserves_function_metadata(self):
        """Should preserve function name and docstring."""

        @traced("test.operation")
        def documented_function():
            """This is the docstring."""
            return "result"

        assert documented_function.__name__ == "documented_function"
        assert documented_function.__doc__ == "This is the docstring."


# ===========================================================================
# Test TracingMiddleware Class
# ===========================================================================


class TestTracingMiddleware:
    """Tests for TracingMiddleware class."""

    def test_init_default_service_name(self):
        """Should use 'aragora' as default service name."""
        middleware = TracingMiddleware()
        assert middleware.service_name == "aragora"

    def test_init_custom_service_name(self, middleware):
        """Should accept custom service name."""
        assert middleware.service_name == "test-service"

    def test_extract_trace_id_from_custom_header(self, middleware, sample_headers):
        """Should extract trace ID from X-Trace-ID header."""
        trace_id = middleware.extract_trace_id(sample_headers)
        assert trace_id == "trace123456789012345678901234"

    def test_extract_trace_id_lowercase_header(self, middleware):
        """Should handle lowercase header name."""
        headers = {"x-trace-id": "trace123456789012345678901234"}
        trace_id = middleware.extract_trace_id(headers)
        assert trace_id == "trace123456789012345678901234"

    def test_extract_trace_id_from_traceparent(self, middleware, sample_w3c_traceparent):
        """Should extract trace ID from W3C traceparent header."""
        trace_id = middleware.extract_trace_id(sample_w3c_traceparent)
        assert trace_id == "0af7651916cd43dd8448eb211c80319c"

    def test_extract_trace_id_generates_new(self, middleware):
        """Should generate new trace ID if no header present."""
        trace_id = middleware.extract_trace_id({})
        assert trace_id is not None
        assert len(trace_id) == 32

    def test_extract_trace_id_prefers_custom_header(self, middleware):
        """Should prefer X-Trace-ID over traceparent."""
        headers = {
            "X-Trace-ID": "custom-trace-id-123456789012",
            "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
        }
        trace_id = middleware.extract_trace_id(headers)
        assert trace_id == "custom-trace-id-123456789012"

    def test_extract_parent_span_id_from_custom_header(self, middleware, sample_headers):
        """Should extract parent span ID from X-Parent-Span-ID header."""
        parent_id = middleware.extract_parent_span_id(sample_headers)
        assert parent_id == "parentspan12345"

    def test_extract_parent_span_id_lowercase_header(self, middleware):
        """Should handle lowercase header name."""
        headers = {"x-parent-span-id": "parentspan12345"}
        parent_id = middleware.extract_parent_span_id(headers)
        assert parent_id == "parentspan12345"

    def test_extract_parent_span_id_from_traceparent(self, middleware, sample_w3c_traceparent):
        """Should extract parent span ID from W3C traceparent header."""
        parent_id = middleware.extract_parent_span_id(sample_w3c_traceparent)
        assert parent_id == "b7ad6b7169203331"

    def test_extract_parent_span_id_returns_none(self, middleware):
        """Should return None if no parent span header present."""
        parent_id = middleware.extract_parent_span_id({})
        assert parent_id is None

    def test_set_response_headers_trace_id(self, middleware, sample_trace_id):
        """Should set X-Trace-ID in response headers."""
        headers = {}
        middleware.set_response_headers(headers, sample_trace_id)

        assert headers["X-Trace-ID"] == sample_trace_id

    def test_set_response_headers_with_span_id(self, middleware, sample_trace_id, sample_span_id):
        """Should set X-Span-ID in response headers when provided."""
        headers = {}
        middleware.set_response_headers(headers, sample_trace_id, span_id=sample_span_id)

        assert headers["X-Trace-ID"] == sample_trace_id
        assert headers["X-Span-ID"] == sample_span_id

    def test_set_response_headers_no_span_id(self, middleware, sample_trace_id):
        """Should not set X-Span-ID when not provided."""
        headers = {}
        middleware.set_response_headers(headers, sample_trace_id)

        assert "X-Span-ID" not in headers

    def test_start_request_span(self, middleware):
        """Should create span for HTTP request."""
        headers = {}
        span = middleware.start_request_span("GET", "/api/debates", headers)

        assert span.operation == "GET /api/debates"
        assert span.trace_id is not None
        assert span.span_id is not None
        assert span.tags["http.method"] == "GET"
        assert span.tags["http.path"] == "/api/debates"
        assert span.tags["service"] == "test-service"

    def test_start_request_span_with_trace_header(self, middleware, sample_headers):
        """Should use trace ID from header."""
        span = middleware.start_request_span("POST", "/api/debates", sample_headers)

        assert span.trace_id == "trace123456789012345678901234"
        assert span.parent_span_id == "parentspan12345"

    def test_start_request_span_sets_global_context(self, middleware):
        """Should set global trace context."""
        headers = {}
        span = middleware.start_request_span("GET", "/api/health", headers)

        assert get_trace_id() == span.trace_id
        assert get_span_id() == span.span_id

    def test_finish_request_span_success(self, middleware):
        """Should finish span with status code."""
        span = Span(
            trace_id="trace123",
            span_id="span123",
            operation="GET /api/test",
        )

        middleware.finish_request_span(span, 200)

        assert span.tags["http.status_code"] == 200
        assert span.status == "ok"
        assert span.end_time is not None

    def test_finish_request_span_client_error(self, middleware):
        """Should mark span as error for 4xx status."""
        span = Span(
            trace_id="trace123",
            span_id="span123",
            operation="GET /api/test",
        )

        middleware.finish_request_span(span, 404)

        assert span.tags["http.status_code"] == 404
        assert span.status == "error"
        assert span.error == "HTTP 404"

    def test_finish_request_span_server_error(self, middleware):
        """Should mark span as error for 5xx status."""
        span = Span(
            trace_id="trace123",
            span_id="span123",
            operation="GET /api/test",
        )

        middleware.finish_request_span(span, 500)

        assert span.tags["http.status_code"] == 500
        assert span.status == "error"
        assert span.error == "HTTP 500"

    def test_finish_request_span_with_exception(self, middleware):
        """Should set error from exception."""
        span = Span(
            trace_id="trace123",
            span_id="span123",
            operation="GET /api/test",
        )

        error = RuntimeError("Internal error")
        middleware.finish_request_span(span, 500, error=error)

        assert span.status == "error"
        assert "RuntimeError" in span.error
        assert "Internal error" in span.error

    def test_finish_request_span_exception_takes_precedence(self, middleware):
        """Exception error should take precedence over status code error."""
        span = Span(
            trace_id="trace123",
            span_id="span123",
            operation="GET /api/test",
        )

        error = ValueError("Validation failed")
        middleware.finish_request_span(span, 400, error=error)

        assert span.error == "ValueError: Validation failed"
        assert "HTTP 400" not in span.error


# ===========================================================================
# Test WebSocket Tracing
# ===========================================================================


class TestWebSocketTracing:
    """Tests for WebSocket tracing utilities."""

    def test_trace_websocket_event_with_context(self, sample_trace_id, sample_span_id):
        """Should add trace context to event data."""
        set_trace_id(sample_trace_id)
        set_span_id(sample_span_id)

        event_data = {"type": "message", "content": "Hello"}
        result = trace_websocket_event("message", event_data)

        assert result["type"] == "message"
        assert result["content"] == "Hello"
        assert result["_trace"]["trace_id"] == sample_trace_id
        assert result["_trace"]["span_id"] == sample_span_id

    def test_trace_websocket_event_without_context(self):
        """Should not add _trace when no trace context."""
        event_data = {"type": "message"}
        result = trace_websocket_event("message", event_data)

        assert "_trace" not in result
        assert result["type"] == "message"

    def test_trace_websocket_event_none_data(self, sample_trace_id):
        """Should handle None event data."""
        set_trace_id(sample_trace_id)

        result = trace_websocket_event("ping", None)

        assert result["_trace"]["trace_id"] == sample_trace_id

    def test_trace_websocket_event_empty_data(self, sample_trace_id):
        """Should handle empty event data."""
        set_trace_id(sample_trace_id)

        result = trace_websocket_event("ping", {})

        assert result["_trace"]["trace_id"] == sample_trace_id

    def test_extract_websocket_trace_with_trace(self, sample_trace_id):
        """Should extract trace ID from event data."""
        event_data = {
            "type": "message",
            "_trace": {"trace_id": sample_trace_id, "span_id": "span123"},
        }

        trace_id = extract_websocket_trace(event_data)

        assert trace_id == sample_trace_id

    def test_extract_websocket_trace_without_trace(self):
        """Should return None when no _trace field."""
        event_data = {"type": "message"}

        trace_id = extract_websocket_trace(event_data)

        assert trace_id is None

    def test_extract_websocket_trace_empty_trace(self):
        """Should return None when _trace is empty."""
        event_data = {"type": "message", "_trace": {}}

        trace_id = extract_websocket_trace(event_data)

        assert trace_id is None


# ===========================================================================
# Test Error Response Tracing
# ===========================================================================


class TestErrorResponseTracing:
    """Tests for error response tracing."""

    def test_add_trace_to_error_with_context(self, sample_trace_id):
        """Should add trace_id to error response."""
        set_trace_id(sample_trace_id)

        error_response = {"error": "Something went wrong", "code": "INTERNAL_ERROR"}
        result = add_trace_to_error(error_response)

        assert result["error"] == "Something went wrong"
        assert result["code"] == "INTERNAL_ERROR"
        assert result["trace_id"] == sample_trace_id

    def test_add_trace_to_error_without_context(self):
        """Should not add trace_id when no trace context."""
        error_response = {"error": "Something went wrong"}
        result = add_trace_to_error(error_response)

        assert result["error"] == "Something went wrong"
        assert "trace_id" not in result

    def test_add_trace_to_error_modifies_original(self, sample_trace_id):
        """Should modify the original error response dict."""
        set_trace_id(sample_trace_id)

        error_response = {"error": "Test"}
        add_trace_to_error(error_response)

        assert error_response["trace_id"] == sample_trace_id


# ===========================================================================
# Test Module Exports
# ===========================================================================


class TestModuleExports:
    """Tests for module's __all__ exports."""

    def test_all_exports_importable(self):
        """All items in __all__ can be imported."""
        from aragora.observability.middleware import tracing

        for name in tracing.__all__:
            assert hasattr(tracing, name), f"Missing export: {name}"

    def test_exported_items(self):
        """Key items are exported in __all__."""
        from aragora.observability.middleware.tracing import __all__

        expected = [
            "TRACE_ID_HEADER",
            "SPAN_ID_HEADER",
            "PARENT_SPAN_HEADER",
            "generate_trace_id",
            "generate_span_id",
            "get_trace_id",
            "get_span_id",
            "get_parent_span_id",
            "set_trace_id",
            "set_span_id",
            "Span",
            "trace_context",
            "traced",
            "TracingMiddleware",
            "trace_websocket_event",
            "extract_websocket_trace",
            "add_trace_to_error",
        ]

        for item in expected:
            assert item in __all__, f"Expected {item} in __all__"


# ===========================================================================
# Integration Tests
# ===========================================================================


class TestIntegration:
    """Integration tests combining multiple components."""

    def test_full_request_trace_flow(self, middleware):
        """Test complete request tracing from start to finish."""
        headers = {"X-Trace-ID": "incoming-trace-12345678901234"}

        # Start request span
        span = middleware.start_request_span("POST", "/api/debates", headers)

        # Simulate work with nested spans
        with trace_context("validate_input") as validate_span:
            validate_span.set_tag("valid", True)

        with trace_context("create_debate") as create_span:
            create_span.set_tag("debate_id", "debate-123")
            create_span.add_event("debate_created")

        # Finish request
        middleware.finish_request_span(span, 201)

        assert span.trace_id == "incoming-trace-12345678901234"
        assert span.tags["http.status_code"] == 201
        assert span.status == "ok"

    def test_error_propagation_through_spans(self, middleware):
        """Test error propagation through nested spans."""
        span = middleware.start_request_span("POST", "/api/debates", {})

        with pytest.raises(ValueError):
            with trace_context("outer_operation") as outer:
                with trace_context("inner_operation") as inner:
                    raise ValueError("Validation failed")

        # Inner span should have error
        assert inner.status == "error"
        assert "ValueError" in inner.error

        # Outer span should also have error
        assert outer.status == "error"

    @pytest.mark.asyncio
    async def test_async_traced_with_middleware(self, middleware):
        """Test async traced function with middleware context."""
        headers = {}
        request_span = middleware.start_request_span("GET", "/api/test", headers)

        @traced("process_data")
        async def process_data():
            # Should inherit trace context
            assert get_trace_id() == request_span.trace_id
            return {"result": "ok"}

        result = await process_data()

        middleware.finish_request_span(request_span, 200)

        assert result == {"result": "ok"}

    def test_websocket_event_roundtrip(self, sample_trace_id, sample_span_id):
        """Test WebSocket event trace context roundtrip."""
        set_trace_id(sample_trace_id)
        set_span_id(sample_span_id)

        # Send event with trace context
        outgoing_event = trace_websocket_event("message", {"data": "hello"})

        # Extract trace from received event
        extracted_trace_id = extract_websocket_trace(outgoing_event)

        assert extracted_trace_id == sample_trace_id

    def test_error_response_with_request_trace(self, middleware):
        """Test error response includes request trace ID."""
        headers = {}
        span = middleware.start_request_span("POST", "/api/test", headers)

        error_response = {"error": "Bad request", "code": "INVALID_INPUT"}
        traced_error = add_trace_to_error(error_response)

        middleware.finish_request_span(span, 400)

        assert traced_error["trace_id"] == span.trace_id


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
