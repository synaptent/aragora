"""Regression tests for application-tier protocol implementations."""

from __future__ import annotations

import importlib
import subprocess
import sys
import textwrap
import warnings
from pathlib import Path


def _fresh_import(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_a2a_server_canonical_home_and_legacy_shim() -> None:
    canonical = importlib.import_module("aragora.server.a2a_runtime")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        legacy = _fresh_import("aragora.protocols.a2a.server")

    assert legacy is canonical
    assert any(
        item.category is DeprecationWarning and "aragora.protocols.a2a.server" in str(item.message)
        for item in caught
    )


def test_protocol_bridge_canonical_home_and_legacy_shim() -> None:
    canonical = importlib.import_module("aragora.server.protocol_bridge")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        legacy = _fresh_import("aragora.protocols.bridge")

    assert legacy is canonical
    sentinel = object()
    setattr(legacy, "_bridge", sentinel)
    assert getattr(canonical, "_bridge") is sentinel
    setattr(canonical, "_bridge", None)
    assert any(
        item.category is DeprecationWarning and "aragora.protocols.bridge" in str(item.message)
        for item in caught
    )


def test_pure_bridge_definitions_remain_in_protocols() -> None:
    definitions = importlib.import_module("aragora.protocols.bridge_types")
    runtime = importlib.import_module("aragora.server.protocol_bridge")

    assert runtime.Protocol is definitions.Protocol
    assert runtime.ExternalResource is definitions.ExternalResource
    assert runtime.BridgeConfig is definitions.BridgeConfig


def test_protocol_package_exports_remain_compatible() -> None:
    protocols = importlib.import_module("aragora.protocols")
    a2a = importlib.import_module("aragora.protocols.a2a")
    server = importlib.import_module("aragora.server.a2a_runtime")
    bridge = importlib.import_module("aragora.server.protocol_bridge")

    assert protocols.A2AServer is server.A2AServer
    assert a2a.A2AServer is server.A2AServer
    assert protocols.ProtocolBridge is bridge.ProtocolBridge


def test_protocol_package_does_not_eagerly_load_server_implementations() -> None:
    project_root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        import sys
        import aragora.protocols

        assert "aragora.server.a2a_runtime" not in sys.modules
        assert "aragora.server.protocol_bridge" not in sys.modules
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
