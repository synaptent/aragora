"""Tests for aragora.debate.telemetry_config."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from aragora.debate.telemetry_config import TelemetryConfig, TelemetryLevel


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure singleton state is clean before and after each test."""
    TelemetryConfig._instance = None
    yield
    TelemetryConfig._instance = None


class TestTelemetryLevel:
    """TelemetryLevel enum values."""

    def test_four_members(self):
        assert len(TelemetryLevel) == 4

    def test_silent_exists(self):
        assert TelemetryLevel.SILENT is not None

    def test_diagnostic_exists(self):
        assert TelemetryLevel.DIAGNOSTIC is not None

    def test_controlled_exists(self):
        assert TelemetryLevel.CONTROLLED is not None

    def test_spectacle_exists(self):
        assert TelemetryLevel.SPECTACLE is not None


class TestTelemetryConfigInit:
    """TelemetryConfig.__init__ behavior."""

    def test_explicit_level(self):
        cfg = TelemetryConfig(level=TelemetryLevel.SILENT)
        assert cfg.level == TelemetryLevel.SILENT

    def test_default_without_env_is_controlled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARAGORA_TELEMETRY_LEVEL", None)
            cfg = TelemetryConfig()
            assert cfg.level == TelemetryLevel.CONTROLLED

    @pytest.mark.parametrize(
        "env_val,expected",
        [
            ("silent", TelemetryLevel.SILENT),
            ("SILENT", TelemetryLevel.SILENT),
            ("diagnostic", TelemetryLevel.DIAGNOSTIC),
            ("controlled", TelemetryLevel.CONTROLLED),
            ("spectacle", TelemetryLevel.SPECTACLE),
            ("0", TelemetryLevel.SILENT),
            ("1", TelemetryLevel.DIAGNOSTIC),
            ("2", TelemetryLevel.CONTROLLED),
            ("3", TelemetryLevel.SPECTACLE),
        ],
    )
    def test_load_from_env(self, env_val, expected):
        with patch.dict(os.environ, {"ARAGORA_TELEMETRY_LEVEL": env_val}):
            cfg = TelemetryConfig()
            assert cfg.level == expected

    def test_invalid_env_defaults_to_controlled(self):
        with patch.dict(os.environ, {"ARAGORA_TELEMETRY_LEVEL": "bogus"}):
            cfg = TelemetryConfig()
            assert cfg.level == TelemetryLevel.CONTROLLED

    def test_empty_env_defaults_to_controlled(self):
        with patch.dict(os.environ, {"ARAGORA_TELEMETRY_LEVEL": ""}):
            cfg = TelemetryConfig()
            assert cfg.level == TelemetryLevel.CONTROLLED

    def test_whitespace_env_defaults_to_controlled(self):
        with patch.dict(os.environ, {"ARAGORA_TELEMETRY_LEVEL": "  "}):
            cfg = TelemetryConfig()
            assert cfg.level == TelemetryLevel.CONTROLLED


class TestLevelProperty:
    """Level getter and setter."""

    def test_getter(self):
        cfg = TelemetryConfig(level=TelemetryLevel.SPECTACLE)
        assert cfg.level == TelemetryLevel.SPECTACLE

    def test_setter(self):
        cfg = TelemetryConfig(level=TelemetryLevel.SILENT)
        cfg.level = TelemetryLevel.SPECTACLE
        assert cfg.level == TelemetryLevel.SPECTACLE


class TestConvenienceBooleans:
    """is_silent / is_diagnostic / is_controlled / is_spectacle."""

    @pytest.mark.parametrize(
        "level,method,expected",
        [
            (TelemetryLevel.SILENT, "is_silent", True),
            (TelemetryLevel.SILENT, "is_diagnostic", False),
            (TelemetryLevel.DIAGNOSTIC, "is_diagnostic", True),
            (TelemetryLevel.DIAGNOSTIC, "is_silent", False),
            (TelemetryLevel.CONTROLLED, "is_controlled", True),
            (TelemetryLevel.CONTROLLED, "is_spectacle", False),
            (TelemetryLevel.SPECTACLE, "is_spectacle", True),
            (TelemetryLevel.SPECTACLE, "is_controlled", False),
        ],
    )
    def test_bool_methods(self, level, method, expected):
        cfg = TelemetryConfig(level=level)
        assert getattr(cfg, method)() is expected


class TestShouldBroadcast:
    """should_broadcast returns True for CONTROLLED and SPECTACLE only."""

    @pytest.mark.parametrize(
        "level,expected",
        [
            (TelemetryLevel.SILENT, False),
            (TelemetryLevel.DIAGNOSTIC, False),
            (TelemetryLevel.CONTROLLED, True),
            (TelemetryLevel.SPECTACLE, True),
        ],
    )
    def test_broadcast(self, level, expected):
        cfg = TelemetryConfig(level=level)
        assert cfg.should_broadcast() is expected


class TestShouldRedact:
    """should_redact returns True only for CONTROLLED."""

    @pytest.mark.parametrize(
        "level,expected",
        [
            (TelemetryLevel.SILENT, False),
            (TelemetryLevel.DIAGNOSTIC, False),
            (TelemetryLevel.CONTROLLED, True),
            (TelemetryLevel.SPECTACLE, False),
        ],
    )
    def test_redact(self, level, expected):
        cfg = TelemetryConfig(level=level)
        assert cfg.should_redact() is expected


class TestAllowsLevel:
    """allows_level hierarchy: SPECTACLE > CONTROLLED > DIAGNOSTIC > SILENT."""

    def test_spectacle_allows_all(self):
        cfg = TelemetryConfig(level=TelemetryLevel.SPECTACLE)
        for lvl in TelemetryLevel:
            assert cfg.allows_level(lvl) is True

    def test_silent_allows_only_silent(self):
        cfg = TelemetryConfig(level=TelemetryLevel.SILENT)
        assert cfg.allows_level(TelemetryLevel.SILENT) is True
        assert cfg.allows_level(TelemetryLevel.DIAGNOSTIC) is False
        assert cfg.allows_level(TelemetryLevel.CONTROLLED) is False
        assert cfg.allows_level(TelemetryLevel.SPECTACLE) is False

    def test_diagnostic_allows_silent_and_diagnostic(self):
        cfg = TelemetryConfig(level=TelemetryLevel.DIAGNOSTIC)
        assert cfg.allows_level(TelemetryLevel.SILENT) is True
        assert cfg.allows_level(TelemetryLevel.DIAGNOSTIC) is True
        assert cfg.allows_level(TelemetryLevel.CONTROLLED) is False

    def test_controlled_allows_up_to_controlled(self):
        cfg = TelemetryConfig(level=TelemetryLevel.CONTROLLED)
        assert cfg.allows_level(TelemetryLevel.SILENT) is True
        assert cfg.allows_level(TelemetryLevel.DIAGNOSTIC) is True
        assert cfg.allows_level(TelemetryLevel.CONTROLLED) is True
        assert cfg.allows_level(TelemetryLevel.SPECTACLE) is False


class TestGetInstance:
    """Singleton via get_instance."""

    def test_returns_same_instance(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARAGORA_TELEMETRY_LEVEL", None)
            a = TelemetryConfig.get_instance()
            b = TelemetryConfig.get_instance()
            assert a is b

    def test_fallback_when_service_registry_unavailable(self):
        with patch.dict("sys.modules", {"aragora.runtime.service_registry": None}):
            inst = TelemetryConfig.get_instance()
            assert isinstance(inst, TelemetryConfig)

    def test_uses_service_registry_when_available(self):
        mock_registry = MagicMock()
        mock_registry.has.return_value = True
        sentinel = TelemetryConfig(level=TelemetryLevel.SPECTACLE)
        mock_registry.resolve.return_value = sentinel

        mock_mod = MagicMock()
        mock_mod.ServiceRegistry.get.return_value = mock_registry
        with patch.dict("sys.modules", {"aragora.runtime.service_registry": mock_mod}):
            result = TelemetryConfig.get_instance()
            assert result is sentinel

    def test_registers_new_instance_in_service_registry(self):
        mock_registry = MagicMock()
        mock_registry.has.return_value = False

        mock_mod = MagicMock()
        mock_mod.ServiceRegistry.get.return_value = mock_registry
        with patch.dict("sys.modules", {"aragora.runtime.service_registry": mock_mod}):
            result = TelemetryConfig.get_instance()
            mock_registry.register.assert_called_once_with(TelemetryConfig, result)


class TestResetInstance:
    """reset_instance clears singleton."""

    def test_clears_class_singleton(self):
        TelemetryConfig._instance = TelemetryConfig(level=TelemetryLevel.SILENT)
        TelemetryConfig.reset_instance()
        assert TelemetryConfig._instance is None

    def test_clears_service_registry(self):
        mock_registry = MagicMock()
        mock_registry.has.return_value = True

        mock_mod = MagicMock()
        mock_mod.ServiceRegistry.get.return_value = mock_registry
        with patch.dict("sys.modules", {"aragora.runtime.service_registry": mock_mod}):
            TelemetryConfig.reset_instance()
            mock_registry.unregister.assert_called_once_with(TelemetryConfig)

    def test_handles_missing_service_registry(self):
        with patch.dict("sys.modules", {"aragora.runtime.service_registry": None}):
            TelemetryConfig.reset_instance()  # should not raise


class TestRepr:
    """String representation."""

    def test_repr_format(self):
        cfg = TelemetryConfig(level=TelemetryLevel.SPECTACLE)
        assert repr(cfg) == "TelemetryConfig(level=SPECTACLE)"

    def test_repr_silent(self):
        cfg = TelemetryConfig(level=TelemetryLevel.SILENT)
        assert "SILENT" in repr(cfg)
