"""Compatibility re-export of :mod:`aragora.observability.debate_tracing`.

The implementation moved to the observability layer so that
``aragora.logging_config`` can read the debate correlation context without
importing ``aragora.debate``. Every name below is the identical object, so
tracer, debate-context and metrics state are shared with the new path.
Module-level state (``_tracer``, ``_debate_context``) lives only in the new
module; patch or reset it there.
"""

from __future__ import annotations

from aragora.observability.debate_tracing import (
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

__all__ = [
    "DebateMetrics",
    "Span",
    "SpanContext",
    "SpanRecorder",
    "Tracer",
    "clear_metrics",
    "generate_span_id",
    "generate_trace_id",
    "get_debate_context",
    "get_debate_id",
    "get_metrics",
    "get_tracer",
    "set_debate_context",
    "set_tracer",
    "trace_agent_call",
    "trace_phase",
    "trace_round",
    "with_debate_context",
]
