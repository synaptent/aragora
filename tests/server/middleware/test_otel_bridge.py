"""
Tests for aragora.server.middleware.otel_bridge - OpenTelemetry Bridge.

Tests cover:
- OTelBridgeConfig dataclass and from_env() factory
- SamplerType enum values
- init_otel_bridge initialization paths (unified, direct, disabled)
- export_span_to_otel span conversion
- inject_trace_context header propagation
- extract_trace_context header extraction
- get_current_trace_id / get_current_span_id helpers
- create_span_context with and without parent
- shutdown_otel_bridge teardown
- is_otel_available state checks
- enrich_span_with_debate_context attribute setting
- enrich_span_with_http_context attribute setting
- Edge cases: missing spans, disabled tracing, import errors
"""

from __future__ import annotations

import importlib
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_module_globals():
    """Reset the module-level globals so each test starts clean."""
    import aragora.server.middleware.otel_bridge as mod

    mod._otel_available = False
    mod._tracer = None
    mod._propagator = None
    mod._config = None


@pytest.fixture(autouse=True)
def _clean_globals():
    """Ensure every test starts with a fresh module state."""
    _reset_module_globals()
    yield
    _reset_module_globals()


def _make_internal_span(
    *,
    operation: str = "test.op",
    trace_id: str = "abc123",
    span_id: str = "span456",
    parent_span_id: str | None = None,
    tags: dict | None = None,
    events: list | None = None,
    status: str = "ok",
    error: str | None = None,
    start_time: float = 1000.0,
):
    """Build a lightweight mock that looks like an internal Span."""
    span = MagicMock()
    span.operation = operation
    span.trace_id = trace_id
    span.span_id = span_id
    span.parent_span_id = parent_span_id
    span.tags = tags or {"http.method": "GET"}
    span.events = events or []
    span.status = status
    span.error = error
    span.start_time = start_time
    return span


# ===========================================================================
# SamplerType enum
# ===========================================================================


class TestSamplerType:
    """Tests for the SamplerType enum."""

    def test_all_sampler_values(self):
        from aragora.server.middleware.otel_bridge import SamplerType

        expected = {
            "always_on",
            "always_off",
            "traceidratio",
            "parentbased_always_on",
            "parentbased_always_off",
            "parentbased_traceidratio",
        }
        assert {s.value for s in SamplerType} == expected

    def test_sampler_is_string_enum(self):
        from aragora.server.middleware.otel_bridge import SamplerType

        assert isinstance(SamplerType.ALWAYS_ON, str)
        assert SamplerType.ALWAYS_ON == "always_on"


# ===========================================================================
# OTelBridgeConfig
# ===========================================================================


class TestOTelBridgeConfig:
    """Tests for OTelBridgeConfig dataclass and from_env()."""

    def test_defaults(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig, SamplerType

        cfg = OTelBridgeConfig()
        assert cfg.enabled is False
        assert cfg.endpoint == ""
        assert cfg.service_name == "aragora"
        assert cfg.service_version == "1.0.0"
        assert cfg.environment == "development"
        assert cfg.sampler_type == SamplerType.PARENT_BASED_ALWAYS_ON
        assert cfg.sampler_arg == 1.0
        assert cfg.propagator_format == "tracecontext,baggage"
        assert cfg.headers is None
        assert cfg.insecure is False

    def test_from_env_disabled_by_default(self):
        """With no env vars set, OTEL should be disabled."""
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        with patch.dict("os.environ", {}, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.enabled is False

    def test_from_env_otel_endpoint_enables(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        env = {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4317"}
        with patch.dict("os.environ", env, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.enabled is True
        assert cfg.endpoint == "http://collector:4317"

    def test_from_env_aragora_exporter_without_endpoint_disables(self):
        """ARAGORA_OTLP_EXPORTER set but no endpoint should warn and disable."""
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        env = {"ARAGORA_OTLP_EXPORTER": "otlp"}
        with patch.dict("os.environ", env, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.enabled is False

    def test_from_env_aragora_endpoint_enables(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        env = {
            "ARAGORA_OTLP_EXPORTER": "otlp",
            "ARAGORA_OTLP_ENDPOINT": "http://local:4317",
        }
        with patch.dict("os.environ", env, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.enabled is True
        assert cfg.endpoint == "http://local:4317"

    def test_from_env_otel_endpoint_takes_precedence(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        env = {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel:4317",
            "ARAGORA_OTLP_ENDPOINT": "http://aragora:4317",
        }
        with patch.dict("os.environ", env, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.endpoint == "http://otel:4317"

    def test_from_env_service_name_precedence(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        env = {
            "OTEL_SERVICE_NAME": "otel-svc",
            "ARAGORA_SERVICE_NAME": "aragora-svc",
        }
        with patch.dict("os.environ", env, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.service_name == "otel-svc"

    def test_from_env_invalid_sampler_falls_back(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig, SamplerType

        env = {"OTEL_TRACES_SAMPLER": "invalid_sampler"}
        with patch.dict("os.environ", env, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.sampler_type == SamplerType.PARENT_BASED_ALWAYS_ON

    def test_from_env_invalid_sampler_arg_falls_back(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        env = {"OTEL_TRACES_SAMPLER_ARG": "not_a_number"}
        with patch.dict("os.environ", env, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.sampler_arg == 1.0

    def test_from_env_sampler_arg_out_of_range_falls_back(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        env = {"OTEL_TRACES_SAMPLER_ARG": "2.5"}
        with patch.dict("os.environ", env, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.sampler_arg == 1.0

    def test_from_env_headers_json(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        env = {"ARAGORA_OTLP_HEADERS": '{"Authorization": "Bearer tok"}'}
        with patch.dict("os.environ", env, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.headers == {"Authorization": "Bearer tok"}

    def test_from_env_invalid_headers_json(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        env = {"ARAGORA_OTLP_HEADERS": "not-json"}
        with patch.dict("os.environ", env, clear=True):
            cfg = OTelBridgeConfig.from_env()
        assert cfg.headers is None

    def test_from_env_insecure_true(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig

        for val in ("true", "1", "yes"):
            with patch.dict("os.environ", {"ARAGORA_OTLP_INSECURE": val}, clear=True):
                cfg = OTelBridgeConfig.from_env()
            assert cfg.insecure is True, f"Expected insecure=True for '{val}'"


# ===========================================================================
# get_bridge_config
# ===========================================================================


class TestGetBridgeConfig:
    def test_loads_from_env_on_first_call(self):
        from aragora.server.middleware.otel_bridge import get_bridge_config

        with patch.dict("os.environ", {}, clear=True):
            cfg = get_bridge_config()
        assert cfg.enabled is False

    def test_caches_config(self):
        from aragora.server.middleware.otel_bridge import get_bridge_config

        with patch.dict("os.environ", {}, clear=True):
            c1 = get_bridge_config()
            c2 = get_bridge_config()
        assert c1 is c2


# ===========================================================================
# init_otel_bridge
# ===========================================================================


class TestInitOtelBridge:
    def test_disabled_config_returns_false(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig, init_otel_bridge

        cfg = OTelBridgeConfig(enabled=False)
        assert init_otel_bridge(cfg) is False

    def test_enabled_but_no_endpoint_returns_false(self):
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig, init_otel_bridge

        cfg = OTelBridgeConfig(enabled=True, endpoint="")
        assert init_otel_bridge(cfg) is False

    def test_unified_otel_path_success(self):
        """When aragora.observability.otel is available and initialises, use it."""
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig, init_otel_bridge
        import aragora.server.middleware.otel_bridge as mod

        mock_tracer = MagicMock()
        mock_otel_mod = MagicMock()
        mock_otel_mod.is_initialized.side_effect = [False, True]
        mock_otel_mod.get_tracer.return_value = mock_tracer

        cfg = OTelBridgeConfig(enabled=True, endpoint="http://col:4317")

        with patch.dict("sys.modules", {"aragora.observability.otel": mock_otel_mod}):
            with patch(
                "aragora.server.middleware.otel_bridge.importlib",
                create=True,
            ):
                # Patch the import inside init_otel_bridge
                import builtins

                original_import = builtins.__import__

                def custom_import(name, *args, **kwargs):
                    if name == "aragora.observability.otel":
                        return mock_otel_mod
                    return original_import(name, *args, **kwargs)

                with patch("builtins.__import__", side_effect=custom_import):
                    result = init_otel_bridge(cfg)

        assert result is True
        assert mod._otel_available is True

    def test_fallback_when_otel_import_fails(self):
        """When opentelemetry is not installed, returns False gracefully."""
        from aragora.server.middleware.otel_bridge import OTelBridgeConfig, init_otel_bridge

        cfg = OTelBridgeConfig(enabled=True, endpoint="http://col:4317")

        import builtins

        original_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if "opentelemetry" in name or "aragora.observability.otel" in name:
                raise ImportError(f"No module {name}")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            result = init_otel_bridge(cfg)

        assert result is False


# ===========================================================================
# export_span_to_otel
# ===========================================================================


class TestExportSpanToOtel:
    def test_noop_when_otel_not_available(self):
        """Should silently return when OTEL is not initialised."""
        from aragora.server.middleware.otel_bridge import export_span_to_otel

        # Should not raise
        export_span_to_otel(_make_internal_span())

    def test_exports_span_attributes(self):
        """When OTEL is available, span attributes are forwarded."""
        import aragora.server.middleware.otel_bridge as mod

        mock_otel_span = MagicMock()
        mock_otel_span.__enter__ = MagicMock(return_value=mock_otel_span)
        mock_otel_span.__exit__ = MagicMock(return_value=False)

        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_otel_span

        mod._otel_available = True
        mod._tracer = mock_tracer

        internal_span = _make_internal_span(
            tags={"http.method": "POST"},
            events=[{"name": "started", "attributes": {"key": "val"}}],
            parent_span_id="parent1",
        )

        # Need to mock the opentelemetry imports inside export_span_to_otel
        mock_status_cls = MagicMock()
        mock_status_code = MagicMock()
        mock_status_code.OK = "OK"
        mock_status_code.ERROR = "ERROR"

        with patch.dict(
            "sys.modules",
            {
                "opentelemetry": MagicMock(),
                "opentelemetry.trace": MagicMock(
                    Status=mock_status_cls, StatusCode=mock_status_code
                ),
            },
        ):
            mod.export_span_to_otel(internal_span)

        mock_tracer.start_as_current_span.assert_called_once()

    def test_handles_export_exception_gracefully(self):
        """Exception during export should be swallowed."""
        import aragora.server.middleware.otel_bridge as mod

        mod._otel_available = True
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.side_effect = RuntimeError("boom")
        mod._tracer = mock_tracer

        with patch.dict(
            "sys.modules",
            {"opentelemetry.trace": MagicMock()},
        ):
            # Should not raise
            mod.export_span_to_otel(_make_internal_span())


# ===========================================================================
# inject_trace_context
# ===========================================================================


class TestInjectTraceContext:
    def test_fallback_injects_x_trace_id(self):
        """Without OTEL, falls back to internal tracing headers."""
        from aragora.server.middleware.otel_bridge import inject_trace_context

        mock_tracing = MagicMock()
        mock_tracing.get_trace_id.return_value = "a" * 32
        mock_tracing.get_span_id.return_value = "b" * 16

        import builtins

        original_import = builtins.__import__

        def custom_import(name, *args, **kwargs):
            if name == "aragora.observability.middleware.trace_state":
                return mock_tracing
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=custom_import):
            headers = inject_trace_context({})

        assert headers["X-Trace-ID"] == "a" * 32
        assert "traceparent" in headers

    def test_fallback_no_trace_id_returns_empty(self):
        """When internal tracing has no trace, headers are unchanged."""
        from aragora.server.middleware.otel_bridge import inject_trace_context

        mock_tracing = MagicMock()
        mock_tracing.get_trace_id.return_value = None

        import builtins

        original_import = builtins.__import__

        def custom_import(name, *args, **kwargs):
            if name == "aragora.observability.middleware.trace_state":
                return mock_tracing
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=custom_import):
            headers = inject_trace_context({})

        assert "X-Trace-ID" not in headers

    def test_otel_propagator_inject(self):
        """When OTEL is available, uses propagator.inject()."""
        import aragora.server.middleware.otel_bridge as mod

        mod._otel_available = True
        mock_propagator = MagicMock()
        mod._propagator = mock_propagator

        mock_context_mod = MagicMock()
        with patch.dict(
            "sys.modules", {"opentelemetry": MagicMock(), "opentelemetry.context": mock_context_mod}
        ):
            import builtins

            original_import = builtins.__import__

            def custom_import(name, *args, **kwargs):
                if name == "opentelemetry":
                    m = MagicMock()
                    m.context = mock_context_mod
                    return m
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=custom_import):
                result = mod.inject_trace_context({"existing": "header"})

        mock_propagator.inject.assert_called_once()
        assert result["existing"] == "header"


# ===========================================================================
# extract_trace_context
# ===========================================================================


class TestExtractTraceContext:
    def test_returns_none_when_not_available(self):
        from aragora.server.middleware.otel_bridge import extract_trace_context

        result = extract_trace_context({"traceparent": "00-abc-def-01"})
        assert result is None

    def test_uses_propagator_when_available(self):
        import aragora.server.middleware.otel_bridge as mod

        mod._otel_available = True
        mock_propagator = MagicMock()
        mock_propagator.extract.return_value = {"context": "extracted"}
        mod._propagator = mock_propagator

        result = mod.extract_trace_context({"traceparent": "00-abc-def-01"})
        assert result == {"context": "extracted"}
        mock_propagator.extract.assert_called_once_with({"traceparent": "00-abc-def-01"})

    def test_extract_exception_returns_none(self):
        import aragora.server.middleware.otel_bridge as mod

        mod._otel_available = True
        mock_propagator = MagicMock()
        mock_propagator.extract.side_effect = RuntimeError("bad")
        mod._propagator = mock_propagator

        result = mod.extract_trace_context({})
        assert result is None


# ===========================================================================
# get_current_trace_id / get_current_span_id
# ===========================================================================


class TestGetCurrentIds:
    def test_trace_id_falls_back_to_internal(self):
        from aragora.server.middleware.otel_bridge import get_current_trace_id

        mock_tracing = MagicMock()
        mock_tracing.get_trace_id.return_value = "internal-trace-id"

        import builtins

        original_import = builtins.__import__

        def custom_import(name, *args, **kwargs):
            if name == "aragora.observability.middleware.trace_state":
                return mock_tracing
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=custom_import):
            result = get_current_trace_id()

        assert result == "internal-trace-id"

    def test_span_id_falls_back_to_internal(self):
        from aragora.server.middleware.otel_bridge import get_current_span_id

        mock_tracing = MagicMock()
        mock_tracing.get_span_id.return_value = "internal-span-id"

        import builtins

        original_import = builtins.__import__

        def custom_import(name, *args, **kwargs):
            if name == "aragora.observability.middleware.trace_state":
                return mock_tracing
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=custom_import):
            result = get_current_span_id()

        assert result == "internal-span-id"

    def test_trace_id_returns_none_when_no_tracing(self):
        """When internal tracing is also not importable, returns None."""
        from aragora.server.middleware.otel_bridge import get_current_trace_id

        import builtins

        original_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if name == "aragora.observability.middleware.trace_state":
                raise ImportError("not available")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            result = get_current_trace_id()

        assert result is None

    def test_span_id_returns_none_when_no_tracing(self):
        from aragora.server.middleware.otel_bridge import get_current_span_id

        import builtins

        original_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if name == "aragora.observability.middleware.trace_state":
                raise ImportError("not available")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            result = get_current_span_id()

        assert result is None


# ===========================================================================
# create_span_context
# ===========================================================================


class TestCreateSpanContext:
    def test_fallback_to_internal_trace_context(self):
        from aragora.server.middleware.otel_bridge import create_span_context

        mock_ctx = MagicMock()
        mock_tracing = MagicMock()
        mock_tracing.trace_context.return_value = mock_ctx

        import builtins

        original_import = builtins.__import__

        def custom_import(name, *args, **kwargs):
            if name == "aragora.observability.middleware.trace_state":
                return mock_tracing
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=custom_import):
            result = create_span_context("my.operation")

        assert result is mock_ctx

    def test_fallback_to_nullcontext_when_no_tracing(self):
        from aragora.server.middleware.otel_bridge import create_span_context

        import builtins

        original_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if name == "aragora.observability.middleware.trace_state":
                raise ImportError("nope")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            ctx = create_span_context("op")

        # nullcontext is usable as a context manager without error
        with ctx:
            pass

    def test_uses_otel_tracer_when_available(self):
        import aragora.server.middleware.otel_bridge as mod

        mock_span_cm = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_as_current_span.return_value = mock_span_cm
        mod._otel_available = True
        mod._tracer = mock_tracer

        mock_otel_context = MagicMock()

        import builtins

        original_import = builtins.__import__

        def custom_import(name, *args, **kwargs):
            if name == "opentelemetry":
                m = MagicMock()
                m.context = mock_otel_context
                return m
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=custom_import):
            result = mod.create_span_context("my.op")

        assert result is mock_span_cm
        mock_tracer.start_as_current_span.assert_called_once_with("my.op")


# ===========================================================================
# shutdown_otel_bridge
# ===========================================================================


class TestShutdownOtelBridge:
    def test_noop_when_not_available(self):
        from aragora.server.middleware.otel_bridge import shutdown_otel_bridge

        # Should not raise
        shutdown_otel_bridge()

    def test_calls_provider_shutdown(self):
        import aragora.server.middleware.otel_bridge as mod

        mod._otel_available = True
        mod._tracer = MagicMock()

        mock_provider = MagicMock()
        mock_trace_mod = MagicMock()
        mock_trace_mod.get_tracer_provider.return_value = mock_provider

        import builtins

        original_import = builtins.__import__

        def custom_import(name, *args, **kwargs):
            if name == "opentelemetry":
                m = MagicMock()
                m.trace = mock_trace_mod
                return m
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=custom_import):
            mod.shutdown_otel_bridge()

        assert mod._otel_available is False
        assert mod._tracer is None

    def test_resets_globals_even_on_error(self):
        import aragora.server.middleware.otel_bridge as mod

        mod._otel_available = True
        mod._tracer = MagicMock()

        import builtins

        original_import = builtins.__import__

        def fail_import(name, *args, **kwargs):
            if "opentelemetry" in name:
                raise RuntimeError("shutdown error")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=fail_import):
            mod.shutdown_otel_bridge()

        assert mod._otel_available is False
        assert mod._tracer is None


# ===========================================================================
# is_otel_available
# ===========================================================================


class TestIsOtelAvailable:
    def test_false_by_default(self):
        from aragora.server.middleware.otel_bridge import is_otel_available

        assert is_otel_available() is False

    def test_true_when_set(self):
        import aragora.server.middleware.otel_bridge as mod

        mod._otel_available = True
        assert mod.is_otel_available() is True


# ===========================================================================
# enrich_span_with_debate_context
# ===========================================================================


class TestEnrichSpanWithDebateContext:
    def test_none_span_is_noop(self):
        from aragora.server.middleware.otel_bridge import enrich_span_with_debate_context

        # Should not raise
        enrich_span_with_debate_context(None, debate_id="d1")

    def test_sets_attributes_via_set_attribute(self):
        from aragora.server.middleware.otel_bridge import enrich_span_with_debate_context

        span = MagicMock(spec=["set_attribute"])
        enrich_span_with_debate_context(
            span,
            debate_id="debate-1",
            round_number=3,
            agent_name="claude",
            phase="critique",
        )

        calls = {c.args[0]: c.args[1] for c in span.set_attribute.call_args_list}
        assert calls["debate.id"] == "debate-1"
        assert calls["debate.round_number"] == 3
        assert calls["agent.name"] == "claude"
        assert calls["debate.phase"] == "critique"

    def test_falls_back_to_set_tag(self):
        from aragora.server.middleware.otel_bridge import enrich_span_with_debate_context

        span = MagicMock(spec=["set_tag"])
        enrich_span_with_debate_context(span, debate_id="d1")
        span.set_tag.assert_called_with("debate.id", "d1")

    def test_skips_none_values(self):
        from aragora.server.middleware.otel_bridge import enrich_span_with_debate_context

        span = MagicMock(spec=["set_attribute"])
        enrich_span_with_debate_context(span)
        span.set_attribute.assert_not_called()


# ===========================================================================
# enrich_span_with_http_context
# ===========================================================================


class TestEnrichSpanWithHttpContext:
    def test_none_span_is_noop(self):
        from aragora.server.middleware.otel_bridge import enrich_span_with_http_context

        enrich_span_with_http_context(None, method="GET")

    def test_sets_http_attributes(self):
        from aragora.server.middleware.otel_bridge import enrich_span_with_http_context

        span = MagicMock(spec=["set_attribute"])
        enrich_span_with_http_context(
            span,
            method="POST",
            path="/api/debate",
            status_code=200,
            client_ip="127.0.0.1",
            user_agent="TestBot/1.0",
        )

        calls = {c.args[0]: c.args[1] for c in span.set_attribute.call_args_list}
        assert calls["http.method"] == "POST"
        assert calls["http.target"] == "/api/debate"
        assert calls["http.status_code"] == 200
        assert calls["net.peer.ip"] == "127.0.0.1"
        assert calls["http.user_agent"] == "TestBot/1.0"

    def test_truncates_long_user_agent(self):
        from aragora.server.middleware.otel_bridge import enrich_span_with_http_context

        span = MagicMock(spec=["set_attribute"])
        long_ua = "X" * 500
        enrich_span_with_http_context(span, user_agent=long_ua)

        call_val = span.set_attribute.call_args.args[1]
        assert len(call_val) == 200

    def test_skips_none_values(self):
        from aragora.server.middleware.otel_bridge import enrich_span_with_http_context

        span = MagicMock(spec=["set_attribute"])
        enrich_span_with_http_context(span)
        span.set_attribute.assert_not_called()

    def test_handles_set_attribute_error(self):
        from aragora.server.middleware.otel_bridge import enrich_span_with_http_context

        span = MagicMock(spec=["set_attribute"])
        span.set_attribute.side_effect = TypeError("bad type")
        # Should not raise
        enrich_span_with_http_context(span, method="GET", path="/test")
