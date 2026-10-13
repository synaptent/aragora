"""
Tests for OpenTelemetry distributed tracing module.
"""

import pytest


class TestNoOpTracer:
    """Tests for no-op tracer behavior when OpenTelemetry is not installed or disabled."""

    def test_noop_tracer_returns_noop_span(self):
        """Test that no-op tracer returns no-op spans."""
        from aragora.observability.tracing import _NoOpTracer

        tracer = _NoOpTracer()
        span = tracer.start_as_current_span("test")

        assert span is not None
        # Should not raise
        span.set_attribute("key", "value")
        span.set_attributes({"a": 1, "b": 2})
        span.add_event("event", {"attr": "val"})
        span.record_exception(ValueError("test"))
        span.set_status(None)
        span.end()

    def test_noop_span_context_manager(self):
        """Test that no-op span works as context manager."""
        from aragora.observability.tracing import _NoOpTracer

        tracer = _NoOpTracer()
        with tracer.start_as_current_span("test") as span:
            span.set_attribute("key", "value")
            # Should not raise


class TestTracingInitialization:
    """Tests for tracer initialization."""

    def test_get_tracer_returns_tracer(self):
        """Test that get_tracer returns a tracer (may be no-op)."""
        from aragora.observability.tracing import get_tracer

        tracer = get_tracer()
        assert tracer is not None
        # Should have start_as_current_span method
        assert hasattr(tracer, "start_as_current_span")

    def test_create_span_context_manager(self):
        """Test create_span context manager."""
        from aragora.observability.tracing import create_span

        with create_span("test.span", {"attr": "value"}) as span:
            assert span is not None


class TestHandlerTracing:
    """Tests for handler tracing decorators."""

    def test_trace_handler_decorator(self):
        """Test trace_handler decorator."""
        from aragora.observability.tracing import trace_handler

        @trace_handler("test.handler")
        def handle_request(self, handler):
            return {"status": "ok"}

        class MockSelf:
            pass

        class MockHandler:
            path = "/test"
            command = "GET"
            client_address = ("127.0.0.1", 8080)

        result = handle_request(MockSelf(), MockHandler())
        assert result == {"status": "ok"}

    def test_trace_handler_with_exception(self):
        """Test trace_handler records exceptions."""
        from aragora.observability.tracing import trace_handler

        @trace_handler("test.failing_handler")
        def handle_failing(self, handler):
            raise ValueError("Test error")

        class MockSelf:
            pass

        class MockHandler:
            path = "/test"
            command = "POST"
            client_address = ("127.0.0.1", 8080)

        with pytest.raises(ValueError, match="Test error"):
            handle_failing(MockSelf(), MockHandler())


class TestWebhookTracing:
    """Tests for webhook-specific tracing."""

    def test_trace_webhook_delivery(self):
        """Test trace_webhook_delivery context manager."""
        from aragora.observability.tracing import trace_webhook_delivery

        with trace_webhook_delivery(
            event_type="slo_violation",
            webhook_id="webhook-123",
            webhook_url="https://example.com/webhook",
            correlation_id="corr-456",
        ) as span:
            assert span is not None
            span.set_attribute("webhook.success", True)
            span.set_attribute("webhook.status_code", 200)

    def test_trace_webhook_delivery_without_correlation_id(self):
        """Test trace_webhook_delivery without correlation ID."""
        from aragora.observability.tracing import trace_webhook_delivery

        with trace_webhook_delivery(
            event_type="debate_end",
            webhook_id="webhook-789",
            webhook_url="https://example.com/hook",
        ) as span:
            assert span is not None

    def test_trace_webhook_batch(self):
        """Test trace_webhook_batch context manager."""
        from aragora.observability.tracing import trace_webhook_batch

        with trace_webhook_batch(
            event_type="slo_violation",
            batch_size=10,
            correlation_id="batch-123",
        ) as span:
            assert span is not None
            span.set_attribute("webhook.batch_success", True)

    def test_trace_webhook_batch_without_correlation_id(self):
        """Test trace_webhook_batch without correlation ID."""
        from aragora.observability.tracing import trace_webhook_batch

        with trace_webhook_batch(
            event_type="debate_update",
            batch_size=5,
        ) as span:
            assert span is not None

    def test_redact_url(self):
        """Test URL redaction for tracing."""
        from aragora.observability.tracing import _redact_url

        # Query params should be removed
        url = "https://example.com/webhook?secret=abc123&token=xyz"
        redacted = _redact_url(url)
        assert "secret" not in redacted
        assert "token" not in redacted
        assert "example.com/webhook" in redacted

        # Fragment should be removed
        url = "https://example.com/hook#fragment"
        redacted = _redact_url(url)
        assert "fragment" not in redacted

        # Basic URL should be preserved
        url = "https://example.com/webhook/endpoint"
        redacted = _redact_url(url)
        assert redacted == "https://example.com/webhook/endpoint"


class TestDebateTracing:
    """Tests for debate-specific tracing."""

    def test_trace_debate_phase(self):
        """Test trace_debate_phase context manager."""
        from aragora.observability.tracing import trace_debate_phase

        with trace_debate_phase("propose", "debate-123", round_num=1) as span:
            assert span is not None

    def test_trace_consensus_check(self):
        """Test trace_consensus_check context manager."""
        from aragora.observability.tracing import trace_consensus_check

        with trace_consensus_check("debate-456", round_num=2) as span:
            assert span is not None


class TestDecisionTracing:
    """Tests for decision routing tracing."""

    def test_trace_decision_routing(self):
        """Test trace_decision_routing context manager."""
        from aragora.observability.tracing import trace_decision_routing

        with trace_decision_routing(
            request_id="req-123",
            decision_type="debate",
            source="http_api",
            priority="high",
        ) as span:
            assert span is not None

    def test_trace_decision_engine(self):
        """Test trace_decision_engine context manager."""
        from aragora.observability.tracing import trace_decision_engine

        with trace_decision_engine("debate", "req-456") as span:
            assert span is not None

    def test_trace_response_delivery(self):
        """Test trace_response_delivery context manager."""
        from aragora.observability.tracing import trace_response_delivery

        with trace_response_delivery(
            platform="slack",
            channel_id="C123456",
            voice_enabled=False,
        ) as span:
            assert span is not None


class TestSpanAttributes:
    """Tests for span attribute helpers."""

    def test_add_span_attributes(self):
        """Test add_span_attributes helper."""
        from aragora.observability.tracing import add_span_attributes, _NoOpSpan

        span = _NoOpSpan()
        # Should not raise
        add_span_attributes(span, {"key": "value", "count": 42, "none_val": None})

    def test_add_span_attributes_with_none_span(self):
        """Test add_span_attributes with None span."""
        from aragora.observability.tracing import add_span_attributes

        # Should not raise
        add_span_attributes(None, {"key": "value"})

    def test_record_exception(self):
        """Test record_exception helper."""
        from aragora.observability.tracing import record_exception, _NoOpSpan

        span = _NoOpSpan()
        # Should not raise
        record_exception(span, ValueError("test"))

    def test_record_exception_with_none_span(self):
        """Test record_exception with None span."""
        from aragora.observability.tracing import record_exception

        # Should not raise
        record_exception(None, ValueError("test"))


class TestBuildTraceHeaders:
    """Tests for build_trace_headers utility function."""

    def test_build_trace_headers_with_context(self):
        """Test build_trace_headers returns headers when trace context is set."""
        from aragora.observability.tracing import build_trace_headers
        from aragora.observability.middleware.tracing import set_trace_id, set_span_id

        # Set trace context
        set_trace_id("a" * 32)
        set_span_id("b" * 16)

        try:
            headers = build_trace_headers()

            # Check custom headers
            assert "X-Trace-ID" in headers
            assert headers["X-Trace-ID"] == "a" * 32
            assert "X-Span-ID" in headers
            assert headers["X-Span-ID"] == "b" * 16

            # Check W3C traceparent header
            assert "traceparent" in headers
            traceparent = headers["traceparent"]
            parts = traceparent.split("-")
            assert len(parts) == 4
            assert parts[0] == "00"  # Version
            assert len(parts[1]) == 32  # Trace ID
            assert len(parts[2]) == 16  # Parent ID
            assert parts[3] == "01"  # Sampled flag
        finally:
            set_trace_id(None)
            set_span_id(None)

    def test_build_trace_headers_without_context(self):
        """Test build_trace_headers returns empty dict when no context."""
        from aragora.observability.tracing import build_trace_headers
        from aragora.observability.middleware.tracing import set_trace_id, set_span_id

        # Ensure no trace context
        set_trace_id(None)
        set_span_id(None)

        headers = build_trace_headers()

        # Should be empty when no trace context
        assert headers == {}

    def test_build_trace_headers_with_short_ids(self):
        """Test build_trace_headers pads short IDs correctly."""
        from aragora.observability.tracing import build_trace_headers
        from aragora.observability.middleware.tracing import set_trace_id, set_span_id

        # Set short IDs
        set_trace_id("short")
        set_span_id("tiny")

        try:
            headers = build_trace_headers()

            # Headers should still be present
            assert "traceparent" in headers

            # Traceparent should have correct lengths
            traceparent = headers["traceparent"]
            parts = traceparent.split("-")
            assert len(parts[1]) == 32  # Trace ID padded to 32
            assert len(parts[2]) == 16  # Parent ID padded to 16
        finally:
            set_trace_id(None)
            set_span_id(None)


class TestTracedDecorator:
    """Tests for the @traced decorator."""

    def test_traced_sync_function(self):
        """Test @traced works on synchronous functions."""
        from aragora.observability.tracing import traced

        @traced("test.sync_function")
        def sync_func(x: int, y: int) -> int:
            return x + y

        result = sync_func(2, 3)
        assert result == 5

    def test_traced_async_function(self):
        """Test @traced works on async functions."""
        import asyncio

        from aragora.observability.tracing import traced

        @traced("test.async_function")
        async def async_func(x: int, y: int) -> int:
            return x + y

        result = asyncio.run(async_func(2, 3))
        assert result == 5

    def test_traced_with_default_name(self):
        """Test @traced uses function name when no name provided."""
        from aragora.observability.tracing import traced

        @traced()
        def my_function() -> str:
            return "hello"

        result = my_function()
        assert result == "hello"

    def test_traced_with_attributes(self):
        """Test @traced with static attributes."""
        from aragora.observability.tracing import traced

        @traced("test.with_attrs", attributes={"service": "billing", "version": "1.0"})
        def func_with_attrs() -> bool:
            return True

        result = func_with_attrs()
        assert result is True

    def test_traced_with_record_args(self):
        """Test @traced records function arguments."""
        from aragora.observability.tracing import traced

        @traced("test.record_args", record_args=True)
        def func_with_args(name: str, count: int) -> str:
            return f"{name}:{count}"

        result = func_with_args("test", 42)
        assert result == "test:42"

    def test_traced_with_record_result(self):
        """Test @traced records function result."""
        from aragora.observability.tracing import traced

        @traced("test.record_result", record_result=True)
        def func_with_result() -> dict:
            return {"status": "ok", "count": 10}

        result = func_with_result()
        assert result == {"status": "ok", "count": 10}

    def test_traced_preserves_exception(self):
        """Test @traced preserves and records exceptions."""
        from aragora.observability.tracing import traced

        @traced("test.exception")
        def func_that_raises() -> None:
            raise ValueError("test error")

        with pytest.raises(ValueError, match="test error"):
            func_that_raises()

    def test_traced_async_exception(self):
        """Test @traced preserves async exceptions."""
        import asyncio

        from aragora.observability.tracing import traced

        @traced("test.async_exception")
        async def async_func_that_raises() -> None:
            raise RuntimeError("async error")

        with pytest.raises(RuntimeError, match="async error"):
            asyncio.run(async_func_that_raises())


class TestAutoInstrumentation:
    """Tests for AutoInstrumentation class."""

    def test_get_instrumented_libraries_initially_empty(self):
        """Test instrumented libraries set starts empty after reset."""
        from aragora.observability.tracing import AutoInstrumentation

        AutoInstrumentation.reset()
        instrumented = AutoInstrumentation.get_instrumented_libraries()
        assert instrumented == set()

    def test_reset_clears_instrumented(self):
        """Test reset clears the instrumented set."""
        from aragora.observability.tracing import AutoInstrumentation

        # Manually add to instrumented (simulating successful instrumentation)
        AutoInstrumentation._instrumented.add("test_lib")
        assert "test_lib" in AutoInstrumentation.get_instrumented_libraries()

        AutoInstrumentation.reset()
        assert "test_lib" not in AutoInstrumentation.get_instrumented_libraries()

    def test_instrument_httpx_returns_bool(self):
        """Test instrument_httpx returns boolean."""
        from aragora.observability.tracing import AutoInstrumentation

        AutoInstrumentation.reset()
        result = AutoInstrumentation.instrument_httpx()
        # May be True or False depending on whether opentelemetry-instrumentation-httpx is installed
        assert isinstance(result, bool)

    def test_instrument_all_returns_list(self):
        """Test instrument_all returns list of instrumented libraries."""
        from aragora.observability.tracing import AutoInstrumentation

        AutoInstrumentation.reset()
        result = AutoInstrumentation.instrument_all()
        assert isinstance(result, list)


class TestWorkerTracing:
    """Tests for worker job tracing helpers."""

    def test_trace_worker_job(self):
        """Test trace_worker_job context manager."""
        from aragora.observability.tracing import trace_worker_job

        with trace_worker_job(
            job_type="routing",
            job_id="job-123",
            worker_id="worker-1",
        ) as span:
            assert span is not None

    def test_trace_worker_job_with_payload(self):
        """Test trace_worker_job with payload keys."""
        from aragora.observability.tracing import trace_worker_job

        payload = {"debate_id": "d-123", "include_voice": True, "secret": "hidden"}

        with trace_worker_job(
            job_type="routing",
            job_id="job-456",
            payload_keys=["debate_id", "include_voice"],
            payload=payload,
        ) as span:
            assert span is not None

    def test_trace_worker_batch(self):
        """Test trace_worker_batch context manager."""
        from aragora.observability.tracing import trace_worker_batch

        with trace_worker_batch(
            job_type="gauntlet",
            batch_size=10,
            worker_id="worker-2",
        ) as span:
            assert span is not None


class TestExternalServiceTracing:
    """Tests for external service tracing helpers."""

    def test_trace_external_call(self):
        """Test trace_external_call context manager."""
        from aragora.observability.tracing import trace_external_call

        with trace_external_call(
            service="openai",
            operation="chat.completions",
            endpoint="https://api.openai.com/v1/chat/completions",
        ) as span:
            assert span is not None

    def test_trace_external_call_without_endpoint(self):
        """Test trace_external_call without endpoint."""
        from aragora.observability.tracing import trace_external_call

        with trace_external_call(
            service="anthropic",
            operation="messages",
        ) as span:
            assert span is not None

    def test_trace_llm_call(self):
        """Test trace_llm_call context manager."""
        from aragora.observability.tracing import trace_llm_call

        with trace_llm_call(
            provider="anthropic",
            model="claude-3-opus",
            operation="generate",
            prompt_tokens=100,
        ) as span:
            assert span is not None

    def test_trace_llm_call_minimal(self):
        """Test trace_llm_call with minimal args."""
        from aragora.observability.tracing import trace_llm_call

        with trace_llm_call(
            provider="openai",
            model="gpt-4",
        ) as span:
            assert span is not None


class TestTracingImports:
    """Tests for new tracing module imports from observability package."""

    def test_traced_importable(self):
        """Test traced decorator is importable from observability."""
        from aragora.observability import traced

        assert callable(traced)

    def test_auto_instrumentation_importable(self):
        """Test AutoInstrumentation is importable from observability."""
        from aragora.observability import AutoInstrumentation

        assert hasattr(AutoInstrumentation, "instrument_all")

    def test_instrument_all_importable(self):
        """Test instrument_all is importable from observability."""
        from aragora.observability import instrument_all

        assert callable(instrument_all)

    def test_trace_worker_job_importable(self):
        """Test trace_worker_job is importable from observability."""
        from aragora.observability import trace_worker_job

        assert callable(trace_worker_job)

    def test_trace_llm_call_importable(self):
        """Test trace_llm_call is importable from observability."""
        from aragora.observability import trace_llm_call

        assert callable(trace_llm_call)

    def test_trace_external_call_importable(self):
        """Test trace_external_call is importable from observability."""
        from aragora.observability import trace_external_call

        assert callable(trace_external_call)
