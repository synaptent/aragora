"""Tests for debate tracing module."""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from aragora.debate.tracing import (
    DebateMetrics,
    Span,
    SpanContext,
    SpanRecorder,
    Tracer,
    clear_metrics,
    generate_span_id,
    generate_trace_id,
    get_debate_context,
    get_debate_id,
    get_metrics,
    get_tracer,
    set_debate_context,
    set_tracer,
    trace_agent_call,
    trace_phase,
    trace_round,
    with_debate_context,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeAgent:
    """Minimal agent stub for decorator tests."""

    def __init__(self, name: str = "test-agent", model: str = "test-model"):
        self.name = name
        self.model = model


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_global_tracer():
    """Reset the global tracer between tests to avoid cross-contamination."""
    import aragora.observability.debate_tracing as _mod

    original = _mod._tracer
    _mod._tracer = None
    yield
    _mod._tracer = original


@pytest.fixture()
def recorder():
    """Fresh SpanRecorder for isolated tests."""
    return SpanRecorder(max_spans=100)


@pytest.fixture()
def tracer(recorder):
    """Tracer wired to a fresh recorder with logging disabled."""
    return Tracer(service_name="test-service", recorder=recorder, log_spans=False)


@pytest.fixture(autouse=True)
def _reset_debate_context():
    """Reset debate context between tests."""
    import aragora.observability.debate_tracing as _mod

    token = _mod._debate_context.set({})
    yield
    _mod._debate_context.reset(token)


@pytest.fixture(autouse=True)
def _reset_metrics():
    """Clear global metrics storage between tests."""
    clear_metrics()
    yield
    clear_metrics()


# ===================================================================
# ID generation
# ===================================================================


class TestIdGeneration:
    """Test trace/span ID generation."""

    def test_generate_trace_id_returns_32_hex(self):
        tid = generate_trace_id()
        assert len(tid) == 32
        int(tid, 16)  # must be valid hex

    def test_generate_span_id_returns_16_hex(self):
        sid = generate_span_id()
        assert len(sid) == 16
        int(sid, 16)

    def test_trace_ids_are_unique(self):
        ids = {generate_trace_id() for _ in range(50)}
        assert len(ids) == 50

    def test_span_ids_are_unique(self):
        ids = {generate_span_id() for _ in range(50)}
        assert len(ids) == 50


# ===================================================================
# SpanContext
# ===================================================================


class TestSpanContext:
    """Test SpanContext dataclass."""

    def test_create_without_parent(self):
        ctx = SpanContext(trace_id="aaa", span_id="bbb")
        assert ctx.trace_id == "aaa"
        assert ctx.span_id == "bbb"
        assert ctx.parent_span_id is None

    def test_create_with_parent(self):
        ctx = SpanContext(trace_id="aaa", span_id="bbb", parent_span_id="ccc")
        assert ctx.parent_span_id == "ccc"


# ===================================================================
# Span
# ===================================================================


class TestSpan:
    """Test Span dataclass."""

    def _make_span(self, **overrides):
        defaults = dict(
            name="test.span",
            trace_id="t1",
            span_id="s1",
            parent_span_id=None,
            start_time=1000.0,
        )
        defaults.update(overrides)
        return Span(**defaults)

    # -- attributes ------------------------------------------------

    def test_set_attribute(self):
        span = self._make_span()
        span.set_attribute("key", "value")
        assert span.attributes["key"] == "value"

    def test_set_attributes_bulk(self):
        span = self._make_span()
        span.set_attributes({"a": 1, "b": 2})
        assert span.attributes["a"] == 1
        assert span.attributes["b"] == 2

    def test_set_attributes_overwrites_existing(self):
        span = self._make_span()
        span.set_attribute("x", "old")
        span.set_attributes({"x": "new"})
        assert span.attributes["x"] == "new"

    # -- events ----------------------------------------------------

    def test_add_event(self):
        span = self._make_span()
        span.add_event("my_event", {"detail": 42})
        assert len(span.events) == 1
        evt = span.events[0]
        assert evt["name"] == "my_event"
        assert evt["attributes"]["detail"] == 42
        assert "timestamp" in evt

    def test_add_event_without_attributes(self):
        span = self._make_span()
        span.add_event("bare_event")
        assert span.events[0]["attributes"] == {}

    def test_add_multiple_events(self):
        span = self._make_span()
        span.add_event("e1")
        span.add_event("e2")
        span.add_event("e3")
        assert len(span.events) == 3
        assert [e["name"] for e in span.events] == ["e1", "e2", "e3"]

    # -- exception recording ---------------------------------------

    def test_record_exception_sets_error_status(self):
        span = self._make_span()
        span.record_exception(ValueError("boom"))
        assert span.status == "ERROR"
        assert "ValueError: boom" in span.error

    def test_record_exception_adds_event(self):
        span = self._make_span()
        span.record_exception(RuntimeError("fail"))
        assert len(span.events) == 1
        evt = span.events[0]
        assert evt["name"] == "exception"
        assert evt["attributes"]["exception.type"] == "RuntimeError"
        assert evt["attributes"]["exception.message"] == "fail"

    # -- span context ----------------------------------------------

    def test_get_span_context(self):
        span = self._make_span(parent_span_id="p1")
        ctx = span.get_span_context()
        assert isinstance(ctx, SpanContext)
        assert ctx.trace_id == "t1"
        assert ctx.span_id == "s1"
        assert ctx.parent_span_id == "p1"

    # -- duration --------------------------------------------------

    def test_duration_ms_returns_none_when_not_ended(self):
        span = self._make_span()
        assert span.duration_ms is None

    def test_duration_ms_calculates_correctly(self):
        span = self._make_span(start_time=1000.0)
        span.end_time = 1000.5
        assert span.duration_ms == pytest.approx(500.0)

    def test_duration_ms_zero_duration(self):
        span = self._make_span(start_time=1000.0)
        span.end_time = 1000.0
        assert span.duration_ms == pytest.approx(0.0)

    # -- serialisation ---------------------------------------------

    def test_to_dict_keys(self):
        span = self._make_span()
        span.end_time = 1001.0
        d = span.to_dict()
        expected_keys = {
            "name",
            "trace_id",
            "span_id",
            "parent_span_id",
            "start_time",
            "end_time",
            "duration_ms",
            "attributes",
            "events",
            "status",
            "error",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values(self):
        span = self._make_span(start_time=1000.0)
        span.end_time = 1002.0
        span.set_attribute("agent", "claude")
        d = span.to_dict()
        assert d["name"] == "test.span"
        assert d["trace_id"] == "t1"
        assert d["duration_ms"] == pytest.approx(2000.0)
        assert d["attributes"]["agent"] == "claude"
        assert d["status"] == "OK"
        assert d["error"] is None

    def test_to_dict_with_end_time_none(self):
        span = self._make_span()
        d = span.to_dict()
        assert d["end_time"] is None
        assert d["duration_ms"] is None

    def test_to_dict_includes_events(self):
        span = self._make_span()
        span.end_time = 1001.0
        span.add_event("my_event")
        d = span.to_dict()
        assert len(d["events"]) == 1

    def test_to_dict_with_error(self):
        span = self._make_span()
        span.end_time = 1001.0
        span.record_exception(TypeError("bad type"))
        d = span.to_dict()
        assert d["status"] == "ERROR"
        assert "TypeError" in d["error"]


# ===================================================================
# SpanRecorder
# ===================================================================


class TestSpanRecorder:
    """Test SpanRecorder class."""

    def _make_span(self, trace_id="t1", name="s"):
        return Span(
            name=name,
            trace_id=trace_id,
            span_id=generate_span_id(),
            parent_span_id=None,
            start_time=time.time(),
        )

    def test_record_span(self, recorder):
        span = self._make_span()
        recorder.record(span)
        assert len(recorder.spans) == 1

    def test_record_multiple_spans(self, recorder):
        for _ in range(5):
            recorder.record(self._make_span())
        assert len(recorder.spans) == 5

    def test_evicts_old_spans_when_over_limit(self):
        rec = SpanRecorder(max_spans=10)
        for i in range(15):
            rec.record(self._make_span(name=f"s{i}"))
        # Eviction triggers when len > max_spans.  At 11 items it trims to 5,
        # then 4 more are added without another eviction => 9 total.
        assert len(rec.spans) <= 10
        assert len(rec.spans) == 9
        # Most recent span should be the last one recorded
        assert rec.spans[-1].name == "s14"

    def test_eviction_keeps_recent_spans(self):
        """Verify that eviction retains the most recent entries."""
        rec = SpanRecorder(max_spans=4)
        for i in range(6):
            rec.record(self._make_span(name=f"s{i}"))
        # At 5 items (>4): keep [-2:] => 2, then add s5 => 3 total
        assert len(rec.spans) <= 4
        # The oldest surviving span should be s3 (kept after first eviction at s4)
        names = [s.name for s in rec.spans]
        assert "s0" not in names
        assert "s5" in names

    def test_get_spans_by_trace(self, recorder):
        recorder.record(self._make_span(trace_id="aaa"))
        recorder.record(self._make_span(trace_id="bbb"))
        recorder.record(self._make_span(trace_id="aaa"))
        result = recorder.get_spans_by_trace("aaa")
        assert len(result) == 2
        assert all(s.trace_id == "aaa" for s in result)

    def test_get_spans_by_trace_empty(self, recorder):
        result = recorder.get_spans_by_trace("nonexistent")
        assert result == []

    def test_get_recent_spans(self, recorder):
        for i in range(10):
            recorder.record(self._make_span(name=f"s{i}"))
        recent = recorder.get_recent_spans(3)
        assert len(recent) == 3
        assert recent[-1].name == "s9"

    def test_get_recent_spans_fewer_than_limit(self, recorder):
        recorder.record(self._make_span())
        recent = recorder.get_recent_spans(100)
        assert len(recent) == 1

    def test_clear(self, recorder):
        for _ in range(5):
            recorder.record(self._make_span())
        recorder.clear()
        assert len(recorder.spans) == 0


# ===================================================================
# Tracer
# ===================================================================


class TestTracer:
    """Test Tracer class."""

    def test_default_service_name(self):
        t = Tracer()
        assert t.service_name == "aragora"

    def test_custom_service_name(self, tracer):
        assert tracer.service_name == "test-service"

    def test_span_creates_and_records(self, tracer, recorder):
        with tracer.span("op1") as span:
            span.set_attribute("x", 1)
        assert len(recorder.spans) == 1
        assert recorder.spans[0].name == "op1"
        assert recorder.spans[0].attributes["x"] == 1

    def test_span_sets_ok_status(self, tracer, recorder):
        with tracer.span("ok_span"):
            pass
        assert recorder.spans[0].status == "OK"

    def test_span_records_end_time(self, tracer, recorder):
        with tracer.span("timed"):
            pass
        assert recorder.spans[0].end_time is not None
        assert recorder.spans[0].duration_ms >= 0

    def test_span_includes_service_name_attribute(self, tracer, recorder):
        with tracer.span("svc"):
            pass
        assert recorder.spans[0].attributes["service.name"] == "test-service"

    def test_span_includes_kwargs_attributes(self, tracer, recorder):
        with tracer.span("attrs", agent="claude", round=3):
            pass
        s = recorder.spans[0]
        assert s.attributes["agent"] == "claude"
        assert s.attributes["round"] == 3

    def test_span_auto_generates_trace_id(self, tracer, recorder):
        with tracer.span("auto_tid"):
            pass
        tid = recorder.spans[0].trace_id
        assert len(tid) == 32

    def test_span_uses_provided_trace_id(self, tracer, recorder):
        with tracer.span("explicit_tid", trace_id="deadbeef" * 4):
            pass
        assert recorder.spans[0].trace_id == "deadbeef" * 4

    def test_nested_spans_share_trace_id(self, tracer, recorder):
        with tracer.span("parent") as parent:
            with tracer.span("child") as child:
                pass
        assert recorder.spans[0].trace_id == recorder.spans[1].trace_id

    def test_nested_span_has_parent_span_id(self, tracer, recorder):
        with tracer.span("parent") as parent:
            with tracer.span("child") as child:
                pass
        # child is recorded first (inner exits first)
        child_recorded = recorder.spans[0]
        parent_recorded = recorder.spans[1]
        assert child_recorded.parent_span_id == parent_recorded.span_id

    def test_span_records_exception(self, tracer, recorder):
        with pytest.raises(ValueError, match="test error"):
            with tracer.span("failing"):
                raise ValueError("test error")
        s = recorder.spans[0]
        assert s.status == "ERROR"
        assert "ValueError: test error" in s.error

    def test_span_exception_still_records_end_time(self, tracer, recorder):
        with pytest.raises(RuntimeError):
            with tracer.span("err"):
                raise RuntimeError("boom")
        assert recorder.spans[0].end_time is not None

    def test_get_current_span_inside_context(self, tracer):
        with tracer.span("active") as span:
            current = tracer.get_current_span()
            assert current is span

    def test_get_current_span_outside_context(self, tracer):
        assert tracer.get_current_span() is None

    def test_get_current_trace_id(self, tracer):
        with tracer.span("op"):
            tid = tracer.get_current_trace_id()
            assert tid is not None and len(tid) == 32

    def test_get_current_trace_id_none_outside(self, tracer):
        assert tracer.get_current_trace_id() is None

    def test_span_with_explicit_parent(self, tracer, recorder):
        with tracer.span("p") as parent:
            pass
        # Create a second span explicitly parented to the first
        with tracer.span("c", parent=parent):
            pass
        child_recorded = recorder.spans[1]
        assert child_recorded.parent_span_id == parent.span_id
        assert child_recorded.trace_id == parent.trace_id

    def test_log_spans_enabled(self, recorder):
        t = Tracer(recorder=recorder, log_spans=True)
        with patch("aragora.observability.debate_tracing.logger") as mock_logger:
            with t.span("logged"):
                pass
            # Should have attempted to log (via structured or plain logger)
            # The exact call depends on whether _structured_logger is available

    def test_log_span_ok_status(self, recorder):
        t = Tracer(recorder=recorder, log_spans=True)
        with patch("aragora.observability.debate_tracing._structured_logger", None):
            with patch("aragora.observability.debate_tracing.logger") as mock_logger:
                with t.span("ok_logged"):
                    pass
                mock_logger.log.assert_called_once()
                # First arg is the level (DEBUG for OK)
                import logging

                call_args = mock_logger.log.call_args
                assert call_args[0][0] == logging.DEBUG

    def test_log_span_error_status(self, recorder):
        t = Tracer(recorder=recorder, log_spans=True)
        with patch("aragora.observability.debate_tracing._structured_logger", None):
            with patch("aragora.observability.debate_tracing.logger") as mock_logger:
                with pytest.raises(ValueError):
                    with t.span("err_logged"):
                        raise ValueError("x")
                mock_logger.log.assert_called_once()
                import logging

                call_args = mock_logger.log.call_args
                assert call_args[0][0] == logging.WARNING

    def test_log_span_with_structured_logger(self, recorder):
        mock_sl = MagicMock()
        t = Tracer(recorder=recorder, log_spans=True)
        with patch("aragora.observability.debate_tracing._structured_logger", mock_sl):
            with t.span("structured_ok"):
                pass
            mock_sl.debug.assert_called_once()

    def test_log_span_error_with_structured_logger(self, recorder):
        mock_sl = MagicMock()
        t = Tracer(recorder=recorder, log_spans=True)
        with patch("aragora.observability.debate_tracing._structured_logger", mock_sl):
            with pytest.raises(RuntimeError):
                with t.span("structured_err"):
                    raise RuntimeError("oops")
            mock_sl.warning.assert_called_once()


# ===================================================================
# Global tracer management
# ===================================================================


class TestGlobalTracer:
    """Test get_tracer / set_tracer."""

    def test_get_tracer_creates_singleton(self):
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2

    def test_get_tracer_uses_service_name(self):
        t = get_tracer("my-service")
        assert t.service_name == "my-service"

    def test_set_tracer_overrides_global(self):
        custom = Tracer(service_name="custom")
        set_tracer(custom)
        assert get_tracer() is custom

    def test_set_tracer_to_none_resets(self):
        set_tracer(None)
        t = get_tracer()
        assert isinstance(t, Tracer)


# ===================================================================
# Debate context
# ===================================================================


class TestDebateContext:
    """Test debate context management functions."""

    def test_set_and_get_debate_context(self):
        set_debate_context("d-123", round=5)
        ctx = get_debate_context()
        assert ctx["debate_id"] == "d-123"
        assert ctx["round"] == 5

    def test_get_debate_id(self):
        set_debate_context("d-456")
        assert get_debate_id() == "d-456"

    def test_get_debate_id_returns_none_without_context(self):
        assert get_debate_id() is None

    def test_set_debate_context_calls_set_context_if_available(self):
        mock_set = MagicMock()
        with patch("aragora.observability.debate_tracing.set_context", mock_set):
            set_debate_context("d-789", extra_key="val")
        mock_set.assert_called_once_with(debate_id="d-789", extra_key="val")

    def test_set_debate_context_skips_set_context_when_none(self):
        with patch("aragora.observability.debate_tracing.set_context", None):
            # Should not raise
            set_debate_context("d-000")
        assert get_debate_id() == "d-000"


# ===================================================================
# with_debate_context decorator
# ===================================================================


class TestWithDebateContextDecorator:
    """Test with_debate_context decorator."""

    def test_sync_function(self):
        @with_debate_context("sync-debate")
        def my_func():
            return get_debate_id()

        result = my_func()
        assert result == "sync-debate"

    def test_async_function(self):
        @with_debate_context("async-debate")
        async def my_async():
            return get_debate_id()

        result = asyncio.run(my_async())
        assert result == "async-debate"

    def test_preserves_return_value_sync(self):
        @with_debate_context("d1")
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_preserves_return_value_async(self):
        @with_debate_context("d2")
        async def mul(a, b):
            return a * b

        result = asyncio.run(mul(4, 5))
        assert result == 20


# ===================================================================
# trace_agent_call decorator
# ===================================================================


class TestTraceAgentCallDecorator:
    """Test trace_agent_call decorator."""

    def test_sync_success(self, recorder):
        t = Tracer(recorder=recorder, log_spans=False)
        set_tracer(t)

        class Service:
            @trace_agent_call("propose")
            def run(self, agent):
                return "result"

        svc = Service()
        result = svc.run(FakeAgent())
        assert result == "result"
        assert len(recorder.spans) == 1
        s = recorder.spans[0]
        assert s.name == "agent.propose"
        assert s.attributes["agent_name"] == "test-agent"
        assert s.attributes["agent_model"] == "test-model"
        assert s.attributes["success"] is True
        assert s.attributes["response_length"] == 6  # len("result")

    def test_async_success(self, recorder):
        t = Tracer(recorder=recorder, log_spans=False)
        set_tracer(t)

        class Service:
            @trace_agent_call("critique")
            async def run(self, agent):
                return "async-result"

        svc = Service()
        result = asyncio.run(svc.run(FakeAgent()))
        assert result == "async-result"
        assert len(recorder.spans) == 1
        s = recorder.spans[0]
        assert s.name == "agent.critique"
        assert s.attributes["success"] is True

    def test_sync_failure(self, recorder):
        t = Tracer(recorder=recorder, log_spans=False)
        set_tracer(t)

        class Service:
            @trace_agent_call("vote")
            def run(self, agent):
                raise RuntimeError("agent failed")

        svc = Service()
        with pytest.raises(RuntimeError, match="agent failed"):
            svc.run(FakeAgent())
        assert len(recorder.spans) == 1
        s = recorder.spans[0]
        assert s.attributes["success"] is False
        # Note: exception is also recorded by the tracer.span context manager
        assert s.status == "ERROR"

    def test_async_failure(self, recorder):
        t = Tracer(recorder=recorder, log_spans=False)
        set_tracer(t)

        class Service:
            @trace_agent_call("revise")
            async def run(self, agent):
                raise ValueError("async agent failed")

        svc = Service()
        with pytest.raises(ValueError, match="async agent failed"):
            asyncio.run(svc.run(FakeAgent()))
        assert len(recorder.spans) == 1
        assert recorder.spans[0].attributes["success"] is False

    def test_none_result_sets_zero_length(self, recorder):
        t = Tracer(recorder=recorder, log_spans=False)
        set_tracer(t)

        class Service:
            @trace_agent_call("propose")
            def run(self, agent):
                return None

        svc = Service()
        svc.run(FakeAgent())
        assert recorder.spans[0].attributes["response_length"] == 0

    def test_agent_without_name_attribute(self, recorder):
        t = Tracer(recorder=recorder, log_spans=False)
        set_tracer(t)

        class Service:
            @trace_agent_call("propose")
            def run(self, agent):
                return "ok"

        svc = Service()
        svc.run("bare-string-agent")  # no .name attribute
        s = recorder.spans[0]
        assert s.attributes["agent_name"] == "bare-string-agent"
        assert s.attributes["agent_model"] == "unknown"


# ===================================================================
# trace_round / trace_phase convenience functions
# ===================================================================


class TestTraceConvenience:
    """Test trace_round and trace_phase convenience functions."""

    def test_trace_round(self, recorder):
        set_tracer(Tracer(recorder=recorder, log_spans=False))
        with trace_round(3) as span:
            span.set_attribute("agents", 5)
        assert len(recorder.spans) == 1
        s = recorder.spans[0]
        assert s.name == "debate.round"
        assert s.attributes["round_number"] == 3

    def test_trace_phase(self, recorder):
        set_tracer(Tracer(recorder=recorder, log_spans=False))
        with trace_phase("proposal", 2) as span:
            pass
        assert len(recorder.spans) == 1
        s = recorder.spans[0]
        assert s.name == "debate.phase.proposal"
        assert s.attributes["phase"] == "proposal"
        assert s.attributes["round_number"] == 2


# ===================================================================
# DebateMetrics
# ===================================================================


class TestDebateMetrics:
    """Test DebateMetrics dataclass."""

    def test_init_defaults(self):
        m = DebateMetrics(debate_id="d1")
        assert m.debate_id == "d1"
        assert m.total_duration_ms == 0
        assert m.rounds_completed == 0
        assert m.agent_calls == 0
        assert m.agent_errors == 0
        assert m.agent_timeouts == 0
        assert m.consensus_reached is False
        assert m.consensus_confidence == 0.0
        assert m.per_agent_latencies == {}

    def test_record_agent_latency(self):
        m = DebateMetrics(debate_id="d1")
        m.record_agent_latency("claude", 100.0)
        m.record_agent_latency("claude", 200.0)
        m.record_agent_latency("gpt", 150.0)
        assert m.agent_calls == 3
        assert m.per_agent_latencies["claude"] == [100.0, 200.0]
        assert m.per_agent_latencies["gpt"] == [150.0]

    def test_get_agent_avg_latency(self):
        m = DebateMetrics(debate_id="d1")
        m.record_agent_latency("claude", 100.0)
        m.record_agent_latency("claude", 300.0)
        assert m.get_agent_avg_latency("claude") == pytest.approx(200.0)

    def test_get_agent_avg_latency_unknown_agent(self):
        m = DebateMetrics(debate_id="d1")
        assert m.get_agent_avg_latency("unknown") == 0

    def test_to_dict(self):
        m = DebateMetrics(debate_id="d1")
        m.total_duration_ms = 5000
        m.rounds_completed = 3
        m.agent_calls = 2
        m.consensus_reached = True
        m.consensus_confidence = 0.95
        m.record_agent_latency("claude", 100.0)
        m.record_agent_latency("claude", 200.0)

        d = m.to_dict()
        assert d["debate_id"] == "d1"
        assert d["total_duration_ms"] == 5000
        assert d["rounds_completed"] == 3
        # agent_calls incremented by record_agent_latency
        assert d["agent_calls"] == 4  # 2 initial + 2 from record
        assert d["consensus_reached"] is True
        assert d["consensus_confidence"] == 0.95
        assert d["per_agent_avg_latencies"]["claude"] == pytest.approx(150.0)

    def test_to_dict_keys(self):
        m = DebateMetrics(debate_id="d1")
        d = m.to_dict()
        expected = {
            "debate_id",
            "total_duration_ms",
            "rounds_completed",
            "agent_calls",
            "agent_errors",
            "agent_timeouts",
            "consensus_reached",
            "consensus_confidence",
            "per_agent_avg_latencies",
        }
        assert set(d.keys()) == expected

    def test_to_dict_empty_latencies(self):
        m = DebateMetrics(debate_id="d1")
        d = m.to_dict()
        assert d["per_agent_avg_latencies"] == {}


# ===================================================================
# Metrics storage (get_metrics / clear_metrics)
# ===================================================================


class TestMetricsStorage:
    """Test thread-safe metrics storage functions."""

    def test_get_metrics_creates_new(self):
        m = get_metrics("debate-1")
        assert isinstance(m, DebateMetrics)
        assert m.debate_id == "debate-1"

    def test_get_metrics_returns_same_instance(self):
        m1 = get_metrics("debate-1")
        m2 = get_metrics("debate-1")
        assert m1 is m2

    def test_get_metrics_different_debates(self):
        m1 = get_metrics("d1")
        m2 = get_metrics("d2")
        assert m1 is not m2
        assert m1.debate_id == "d1"
        assert m2.debate_id == "d2"

    def test_clear_metrics_specific(self):
        get_metrics("d1")
        get_metrics("d2")
        clear_metrics("d1")
        # d1 should be recreated fresh
        m1 = get_metrics("d1")
        assert m1.agent_calls == 0
        # d2 should still exist
        m2 = get_metrics("d2")
        assert m2.debate_id == "d2"

    def test_clear_metrics_all(self):
        get_metrics("d1")
        get_metrics("d2")
        clear_metrics()
        # Both should be fresh
        m1 = get_metrics("d1")
        m2 = get_metrics("d2")
        assert m1.agent_calls == 0
        assert m2.agent_calls == 0

    def test_clear_nonexistent_debate_no_error(self):
        clear_metrics("nonexistent")  # Should not raise

    def test_metrics_mutations_persist(self):
        m = get_metrics("d1")
        m.record_agent_latency("claude", 50.0)
        m.rounds_completed = 5
        # Retrieve again - should see mutations
        m2 = get_metrics("d1")
        assert m2.rounds_completed == 5
        assert m2.agent_calls == 1
