"""
Tests for aragora.server.startup.observability module.

Tests structured logging, error monitoring, OpenTelemetry,
OTLP exporter, and Prometheus metrics initialization.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


_NON_NOMIC_ADAPTERS = (
    pytest.param(
        "pagerduty",
        "aragora.connectors.devops.slo_alert_sink",
        "register_slo_alert_sink",
        "PagerDuty",
        id="pagerduty",
    ),
    pytest.param(
        "channel",
        "aragora.control_plane.slo_alert_sink",
        "register_slo_alert_sink",
        "Channel",
        id="channel",
    ),
    pytest.param(
        "webhook",
        "aragora.integrations.webhooks",
        "register_slo_event_sink",
        "Webhook",
        id="webhook",
    ),
    pytest.param(
        "knowledge_mound",
        "aragora.knowledge.mound.metrics",
        "register_prometheus_health_provider",
        "Knowledge Mound",
        id="knowledge-mound",
    ),
)

_ALL_ADAPTERS = (
    (
        "pagerduty",
        "aragora.connectors.devops.slo_alert_sink",
        "register_slo_alert_sink",
    ),
    (
        "channel",
        "aragora.control_plane.slo_alert_sink",
        "register_slo_alert_sink",
    ),
    (
        "webhook",
        "aragora.integrations.webhooks",
        "register_slo_event_sink",
    ),
    (
        "knowledge_mound",
        "aragora.knowledge.mound.metrics",
        "register_prometheus_health_provider",
    ),
    (
        "nomic",
        "aragora.nomic.metrics",
        "register_prometheus_metrics_provider",
    ),
)


def _mock_observability_adapters() -> dict[str, MagicMock]:
    modules: dict[str, MagicMock] = {}
    for _name, module_path, register_name in _ALL_ADAPTERS:
        adapter = MagicMock()
        getattr(adapter, register_name).return_value = True
        modules[module_path] = adapter
    return modules


class TestRegisterObservabilitySinks:
    """Tests for higher-layer sink composition."""

    def test_adapter_imports_do_not_mutate_observability_registries(self) -> None:
        """Importing an adapter is side-effect free until startup composes it."""
        import importlib

        from aragora.connectors.devops import slo_alert_sink as pagerduty_adapter
        from aragora.control_plane import slo_alert_sink as channel_adapter
        from aragora.integrations import webhooks as webhook_adapter
        from aragora.observability import slo
        from aragora.observability import slo_alert_bridge
        from aragora.observability.metrics import slo as slo_metrics

        slo.register_slo_notification_sink_provider(None)
        slo_alert_bridge.register_pagerduty_alert_sink(None)
        slo_alert_bridge.register_channel_alert_sink(None)
        slo_metrics.register_slo_event_sink_provider(None)

        importlib.reload(pagerduty_adapter)
        importlib.reload(channel_adapter)
        importlib.reload(webhook_adapter)

        assert slo._slo_notification_sink_provider is None
        assert slo_alert_bridge._pagerduty_alert_sink_factory is None
        assert slo_alert_bridge._channel_alert_sink_factory is None
        assert slo_metrics._slo_event_sink_provider is None

    def test_registers_all_external_sink_providers(self) -> None:
        from aragora.observability.metrics import km as km_metrics
        from aragora.observability.metrics import slo as slo_metrics
        from aragora.observability import slo
        from aragora.observability import slo_alert_bridge
        from aragora.observability.server_metrics import export as server_metrics_export
        from aragora.server.startup.observability import register_observability_sinks

        slo.register_slo_notification_sink_provider(None)
        slo_alert_bridge.register_pagerduty_alert_sink(None)
        slo_alert_bridge.register_channel_alert_sink(None)
        slo_metrics.register_slo_event_sink_provider(None)
        km_metrics.register_km_health_provider(None)
        server_metrics_export.register_nomic_metrics_provider(None)
        try:
            assert register_observability_sinks() is True
            assert slo._slo_notification_sink_provider is not None
            assert slo_alert_bridge._pagerduty_alert_sink_factory is not None
            assert slo_alert_bridge._channel_alert_sink_factory is not None
            assert slo_metrics._slo_event_sink_provider is not None
            assert km_metrics._km_health_provider is not None
            assert server_metrics_export._nomic_metrics_provider is not None
        finally:
            slo.register_slo_notification_sink_provider(None)
            slo_alert_bridge.register_pagerduty_alert_sink(None)
            slo_alert_bridge.register_channel_alert_sink(None)
            slo_metrics.register_slo_event_sink_provider(None)
            km_metrics.register_km_health_provider(None)
            server_metrics_export.register_nomic_metrics_provider(None)

    def test_nomic_import_failure_does_not_skip_other_adapters(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Optional Nomic import failure cannot short-circuit other adapters."""
        pagerduty_adapter = MagicMock()
        pagerduty_adapter.register_slo_alert_sink.return_value = True
        channel_adapter = MagicMock()
        channel_adapter.register_slo_alert_sink.return_value = True
        webhook_adapter = MagicMock()
        webhook_adapter.register_slo_event_sink.return_value = True
        km_adapter = MagicMock()
        km_adapter.register_prometheus_health_provider.return_value = True

        with (
            patch.dict(
                "sys.modules",
                {
                    "aragora.connectors.devops.slo_alert_sink": pagerduty_adapter,
                    "aragora.control_plane.slo_alert_sink": channel_adapter,
                    "aragora.integrations.webhooks": webhook_adapter,
                    "aragora.knowledge.mound.metrics": km_adapter,
                    "aragora.nomic.metrics": None,
                },
            ),
            caplog.at_level("DEBUG", logger="aragora.server.startup.observability"),
        ):
            from aragora.server.startup.observability import register_observability_sinks

            result = register_observability_sinks()

        assert result is False
        pagerduty_adapter.register_slo_alert_sink.assert_called_once_with()
        channel_adapter.register_slo_alert_sink.assert_called_once_with()
        webhook_adapter.register_slo_event_sink.assert_called_once_with()
        km_adapter.register_prometheus_health_provider.assert_called_once_with()
        assert "Nomic observability adapter not available" in caplog.text

    @pytest.mark.parametrize(
        ("failed_adapter", "failed_module", "register_name", "log_name"),
        _NON_NOMIC_ADAPTERS,
    )
    def test_non_nomic_import_failure_does_not_skip_sibling_adapters(
        self,
        failed_adapter: str,
        failed_module: str,
        register_name: str,
        log_name: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Every adapter import has its own fail-soft boundary."""
        adapters = _mock_observability_adapters()
        adapters_with_failure: dict[str, MagicMock | None] = dict(adapters)
        adapters_with_failure[failed_module] = None

        with (
            patch.dict("sys.modules", adapters_with_failure),
            caplog.at_level("DEBUG", logger="aragora.server.startup.observability"),
        ):
            from aragora.server.startup.observability import register_observability_sinks

            result = register_observability_sinks()

        assert result is False
        for adapter_name, module_path, sibling_register_name in _ALL_ADAPTERS:
            if adapter_name == failed_adapter:
                continue
            getattr(adapters[module_path], sibling_register_name).assert_called_once_with()
        getattr(adapters[failed_module], register_name).assert_not_called()
        assert f"{log_name} observability adapter not available" in caplog.text

    @pytest.mark.parametrize(
        ("failed_adapter", "failed_module", "register_name", "log_name"),
        _NON_NOMIC_ADAPTERS,
    )
    def test_non_nomic_registration_failure_does_not_skip_sibling_adapters(
        self,
        failed_adapter: str,
        failed_module: str,
        register_name: str,
        log_name: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Every adapter registration has its own fail-soft boundary."""
        adapters = _mock_observability_adapters()
        getattr(adapters[failed_module], register_name).side_effect = RuntimeError("boom")

        with (
            patch.dict("sys.modules", adapters),
            caplog.at_level("WARNING", logger="aragora.server.startup.observability"),
        ):
            from aragora.server.startup.observability import register_observability_sinks

            result = register_observability_sinks()

        assert result is False
        for adapter_name, module_path, sibling_register_name in _ALL_ADAPTERS:
            if adapter_name == failed_adapter:
                continue
            getattr(adapters[module_path], sibling_register_name).assert_called_once_with()
        getattr(adapters[failed_module], register_name).assert_called_once_with()
        assert f"Failed to register {log_name} observability adapter" in caplog.text


# =============================================================================
# init_structured_logging Tests
# =============================================================================


class TestInitStructuredLogging:
    """Tests for init_structured_logging function."""

    def test_json_logging_enabled_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test JSON logging enabled in production environment."""
        monkeypatch.setenv("ARAGORA_ENV", "production")
        monkeypatch.setenv("ARAGORA_LOG_LEVEL", "INFO")
        monkeypatch.delenv("ARAGORA_LOG_FORMAT", raising=False)

        mock_logging = MagicMock()
        mock_logging.configure_structured_logging = MagicMock()

        with patch.dict(
            "sys.modules",
            {"aragora.server.middleware.structured_logging": mock_logging},
        ):
            from aragora.server.startup.observability import init_structured_logging

            result = init_structured_logging()

        assert result is True
        mock_logging.configure_structured_logging.assert_called_once_with(
            level="INFO",
            json_output=True,
            service_name="aragora",
        )

    def test_text_logging_in_development(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test text logging in development environment."""
        monkeypatch.setenv("ARAGORA_ENV", "development")
        monkeypatch.setenv("ARAGORA_LOG_LEVEL", "DEBUG")
        monkeypatch.delenv("ARAGORA_LOG_FORMAT", raising=False)

        mock_logging = MagicMock()
        mock_logging.configure_structured_logging = MagicMock()

        with patch.dict(
            "sys.modules",
            {"aragora.server.middleware.structured_logging": mock_logging},
        ):
            from aragora.server.startup.observability import init_structured_logging

            result = init_structured_logging()

        assert result is False
        mock_logging.configure_structured_logging.assert_called_once_with(
            level="DEBUG",
            json_output=False,
            service_name="aragora",
        )

    def test_json_format_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ARAGORA_LOG_FORMAT=json overrides environment."""
        monkeypatch.setenv("ARAGORA_ENV", "development")
        monkeypatch.setenv("ARAGORA_LOG_FORMAT", "json")
        monkeypatch.setenv("ARAGORA_LOG_LEVEL", "WARNING")

        mock_logging = MagicMock()
        mock_logging.configure_structured_logging = MagicMock()

        with patch.dict(
            "sys.modules",
            {"aragora.server.middleware.structured_logging": mock_logging},
        ):
            from aragora.server.startup.observability import init_structured_logging

            result = init_structured_logging()

        assert result is True
        mock_logging.configure_structured_logging.assert_called_once_with(
            level="WARNING",
            json_output=True,
            service_name="aragora",
        )

    def test_import_error(self) -> None:
        """Test ImportError returns False."""
        with patch.dict("sys.modules", {"aragora.server.middleware.structured_logging": None}):
            import importlib
            import aragora.server.startup.observability as obs_module

            importlib.reload(obs_module)
            result = obs_module.init_structured_logging()

        assert result is False

    def test_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ValueError returns False."""
        monkeypatch.setenv("ARAGORA_ENV", "production")

        mock_logging = MagicMock()
        mock_logging.configure_structured_logging = MagicMock(
            side_effect=ValueError("invalid config")
        )

        with patch.dict(
            "sys.modules",
            {"aragora.server.middleware.structured_logging": mock_logging},
        ):
            from aragora.server.startup.observability import init_structured_logging

            result = init_structured_logging()

        assert result is False


# =============================================================================
# init_error_monitoring Tests
# =============================================================================


class TestInitErrorMonitoring:
    """Tests for init_error_monitoring function."""

    @pytest.mark.asyncio
    async def test_monitoring_enabled(self) -> None:
        """Test error monitoring enabled (Sentry)."""
        mock_monitoring = MagicMock()
        mock_monitoring.init_monitoring = MagicMock(return_value=True)

        with patch.dict("sys.modules", {"aragora.server.error_monitoring": mock_monitoring}):
            from aragora.server.startup.observability import init_error_monitoring

            result = await init_error_monitoring()

        assert result is True
        mock_monitoring.init_monitoring.assert_called_once()

    @pytest.mark.asyncio
    async def test_monitoring_disabled(self) -> None:
        """Test error monitoring returns False when init fails."""
        mock_monitoring = MagicMock()
        mock_monitoring.init_monitoring = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"aragora.server.error_monitoring": mock_monitoring}):
            from aragora.server.startup.observability import init_error_monitoring

            result = await init_error_monitoring()

        assert result is False

    @pytest.mark.asyncio
    async def test_import_error(self) -> None:
        """Test ImportError returns False."""
        with patch.dict("sys.modules", {"aragora.server.error_monitoring": None}):
            import importlib
            import aragora.server.startup.observability as obs_module

            importlib.reload(obs_module)
            result = await obs_module.init_error_monitoring()

        assert result is False


# =============================================================================
# init_opentelemetry Tests
# =============================================================================


class TestInitOpenTelemetry:
    """Tests for init_opentelemetry function."""

    @pytest.mark.asyncio
    async def test_unified_setup_success(self) -> None:
        """Test unified OTel setup succeeds."""
        mock_otel = MagicMock()
        mock_otel.setup_otel = MagicMock(return_value=True)
        mock_otel.is_initialized = MagicMock(return_value=False)

        with patch.dict("sys.modules", {"aragora.observability.otel": mock_otel}):
            from aragora.server.startup.observability import init_opentelemetry

            result = await init_opentelemetry()

        assert result is True
        mock_otel.setup_otel.assert_called_once()

    @pytest.mark.asyncio
    async def test_already_initialized(self) -> None:
        """Test returns True when already initialized."""
        mock_otel = MagicMock()
        mock_otel.setup_otel = MagicMock(return_value=False)
        mock_otel.is_initialized = MagicMock(return_value=True)

        with patch.dict("sys.modules", {"aragora.observability.otel": mock_otel}):
            from aragora.server.startup.observability import init_opentelemetry

            result = await init_opentelemetry()

        assert result is True

    @pytest.mark.asyncio
    async def test_fallback_to_legacy_enabled(self) -> None:
        """Test fallback to legacy tracing when unified not available."""
        mock_config = MagicMock()
        mock_config.is_tracing_enabled = MagicMock(return_value=True)

        mock_tracing = MagicMock()
        mock_tracing.get_tracer = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "aragora.observability.otel": None,  # Force ImportError
                "aragora.observability.config": mock_config,
                "aragora.observability.tracing": mock_tracing,
            },
        ):
            import importlib
            import aragora.server.startup.observability as obs_module

            importlib.reload(obs_module)
            result = await obs_module.init_opentelemetry()

        assert result is True
        mock_tracing.get_tracer.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_legacy_disabled(self) -> None:
        """Test legacy tracing disabled returns False."""
        mock_config = MagicMock()
        mock_config.is_tracing_enabled = MagicMock(return_value=False)

        with patch.dict(
            "sys.modules",
            {
                "aragora.observability.otel": None,
                "aragora.observability.config": mock_config,
                "aragora.observability.tracing": MagicMock(),
            },
        ):
            import importlib
            import aragora.server.startup.observability as obs_module

            importlib.reload(obs_module)
            result = await obs_module.init_opentelemetry()

        assert result is False

    @pytest.mark.asyncio
    async def test_all_imports_fail(self) -> None:
        """Test returns False when all imports fail."""
        with patch.dict(
            "sys.modules",
            {
                "aragora.observability.otel": None,
                "aragora.observability.config": None,
                "aragora.observability.tracing": None,
            },
        ):
            import importlib
            import aragora.server.startup.observability as obs_module

            importlib.reload(obs_module)
            result = await obs_module.init_opentelemetry()

        assert result is False


# =============================================================================
# init_otlp_exporter Tests
# =============================================================================


class TestInitOtlpExporter:
    """Tests for init_otlp_exporter function."""

    @pytest.mark.asyncio
    async def test_bridge_enabled(self) -> None:
        """Test OTEL bridge initialization success."""
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.endpoint = "http://localhost:4317"
        mock_config.service_name = "aragora"
        mock_config.sampler_type = MagicMock(value="parentbased_traceidratio")

        mock_bridge = MagicMock()
        mock_bridge.get_bridge_config = MagicMock(return_value=mock_config)
        mock_bridge.init_otel_bridge = MagicMock(return_value=True)

        with patch.dict("sys.modules", {"aragora.server.middleware.otel_bridge": mock_bridge}):
            from aragora.server.startup.observability import init_otlp_exporter

            result = await init_otlp_exporter()

        assert result is True
        mock_bridge.init_otel_bridge.assert_called_once_with(mock_config)

    @pytest.mark.asyncio
    async def test_bridge_disabled(self) -> None:
        """Test OTEL bridge disabled falls back to legacy."""
        mock_config = MagicMock()
        mock_config.enabled = False

        mock_bridge = MagicMock()
        mock_bridge.get_bridge_config = MagicMock(return_value=mock_config)

        mock_obs_config = MagicMock()
        mock_obs_config.is_otlp_enabled = MagicMock(return_value=False)

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.middleware.otel_bridge": mock_bridge,
                "aragora.observability.config": mock_obs_config,
            },
        ):
            from aragora.server.startup.observability import init_otlp_exporter

            result = await init_otlp_exporter()

        assert result is False

    @pytest.mark.asyncio
    async def test_legacy_exporter_success(self) -> None:
        """Test legacy OTLP exporter initialization."""
        mock_bridge = MagicMock()
        mock_bridge.get_bridge_config = MagicMock(side_effect=ImportError("no bridge"))

        mock_obs_config = MagicMock()
        mock_obs_config.is_otlp_enabled = MagicMock(return_value=True)

        mock_otlp_config = MagicMock()
        mock_otlp_config.exporter_type = MagicMock(value="otlp_grpc")
        mock_otlp_config.get_effective_endpoint = MagicMock(return_value="http://localhost:4317")

        mock_provider = MagicMock()

        mock_export = MagicMock()
        mock_export.get_otlp_config = MagicMock(return_value=mock_otlp_config)
        mock_export.configure_otlp_exporter = MagicMock(return_value=mock_provider)

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.middleware.otel_bridge": mock_bridge,
                "aragora.observability.config": mock_obs_config,
                "aragora.observability.otlp_export": mock_export,
            },
        ):
            from aragora.server.startup.observability import init_otlp_exporter

            result = await init_otlp_exporter()

        assert result is True
        mock_export.configure_otlp_exporter.assert_called_once_with(mock_otlp_config)

    @pytest.mark.asyncio
    async def test_legacy_exporter_fails(self) -> None:
        """Test legacy OTLP exporter returns None provider."""
        mock_obs_config = MagicMock()
        mock_obs_config.is_otlp_enabled = MagicMock(return_value=True)

        mock_export = MagicMock()
        mock_export.get_otlp_config = MagicMock(return_value=MagicMock())
        mock_export.configure_otlp_exporter = MagicMock(return_value=None)

        with patch.dict(
            "sys.modules",
            {
                "aragora.server.middleware.otel_bridge": None,
                "aragora.observability.config": mock_obs_config,
                "aragora.observability.otlp_export": mock_export,
            },
        ):
            import importlib
            import aragora.server.startup.observability as obs_module

            importlib.reload(obs_module)
            result = await obs_module.init_otlp_exporter()

        assert result is False

    @pytest.mark.asyncio
    async def test_all_imports_fail(self) -> None:
        """Test returns False when all imports fail."""
        with patch.dict(
            "sys.modules",
            {
                "aragora.server.middleware.otel_bridge": None,
                "aragora.observability.config": None,
                "aragora.observability.otlp_export": None,
            },
        ):
            import importlib
            import aragora.server.startup.observability as obs_module

            importlib.reload(obs_module)
            result = await obs_module.init_otlp_exporter()

        assert result is False


# =============================================================================
# init_prometheus_metrics Tests
# =============================================================================


class TestInitPrometheusMetrics:
    """Tests for init_prometheus_metrics function."""

    @pytest.mark.asyncio
    async def test_metrics_enabled(self) -> None:
        """Test Prometheus metrics server started."""
        mock_config = MagicMock()
        mock_config.is_metrics_enabled = MagicMock(return_value=True)

        mock_metrics = MagicMock()
        mock_metrics.start_metrics_server = MagicMock()

        with patch.dict(
            "sys.modules",
            {
                "aragora.observability.config": mock_config,
                "aragora.observability.metrics": mock_metrics,
            },
        ):
            from aragora.server.startup.observability import init_prometheus_metrics

            result = await init_prometheus_metrics()

        assert result is True
        mock_metrics.start_metrics_server.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrics_disabled(self) -> None:
        """Test Prometheus metrics disabled."""
        mock_config = MagicMock()
        mock_config.is_metrics_enabled = MagicMock(return_value=False)

        with patch.dict(
            "sys.modules",
            {
                "aragora.observability.config": mock_config,
                "aragora.observability.metrics": MagicMock(),
            },
        ):
            from aragora.server.startup.observability import init_prometheus_metrics

            result = await init_prometheus_metrics()

        assert result is False

    @pytest.mark.asyncio
    async def test_import_error(self) -> None:
        """Test ImportError returns False."""
        with patch.dict(
            "sys.modules",
            {
                "aragora.observability.config": None,
                "aragora.observability.metrics": None,
            },
        ):
            import importlib
            import aragora.server.startup.observability as obs_module

            importlib.reload(obs_module)
            result = await obs_module.init_prometheus_metrics()

        assert result is False

    @pytest.mark.asyncio
    async def test_runtime_error(self) -> None:
        """Test RuntimeError returns False."""
        mock_config = MagicMock()
        mock_config.is_metrics_enabled = MagicMock(return_value=True)

        mock_metrics = MagicMock()
        mock_metrics.start_metrics_server = MagicMock(side_effect=RuntimeError("port in use"))

        with patch.dict(
            "sys.modules",
            {
                "aragora.observability.config": mock_config,
                "aragora.observability.metrics": mock_metrics,
            },
        ):
            from aragora.server.startup.observability import init_prometheus_metrics

            result = await init_prometheus_metrics()

        assert result is False
