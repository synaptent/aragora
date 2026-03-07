"""Tests for scripts/smoke_self_host_runtime.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


def _load_script_module() -> ModuleType:
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "smoke_self_host_runtime.py"
    spec = importlib.util.spec_from_file_location("smoke_self_host_runtime", script_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError("Unable to load smoke_self_host_runtime.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_openapi_fails_on_generic_json() -> None:
    module = _load_script_module()

    with patch.object(
        module, "_fetch", return_value=(200, {"hello": "world"}, '{"hello":"world"}')
    ):
        assert module.check_openapi("http://localhost:8000", None, 5) is False


def test_check_openapi_passes_on_valid_spec() -> None:
    module = _load_script_module()

    payload = {"openapi": "3.1.0", "paths": {"/healthz": {"get": {}}}}
    with patch.object(module, "_fetch", return_value=(200, payload, '{"openapi":"3.1.0"}')):
        assert module.check_openapi("http://localhost:8000", None, 5) is True


def test_check_readiness_fails_on_http_200_not_ready_status() -> None:
    module = _load_script_module()

    with patch.object(
        module, "_fetch", return_value=(200, {"status": "starting"}, '{"status":"starting"}')
    ):
        assert module.check_readiness("http://localhost:8000", None, 5) is False


def test_check_health_api_requires_status_field() -> None:
    module = _load_script_module()

    with patch.object(
        module, "_fetch", return_value=(200, {"uptime_seconds": 12}, '{"uptime_seconds":12}')
    ):
        assert module.check_health_api("http://localhost:8000", None, 5) is False
