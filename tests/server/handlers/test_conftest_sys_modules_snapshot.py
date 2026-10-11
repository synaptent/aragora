"""Tests for the ``sys.modules`` scan in the handlers ``run_async`` repair fixture."""

from __future__ import annotations

import gc
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from tests.server.handlers import conftest as handlers_conftest


class _ResizingModules(dict):
    """Module table whose ``copy`` fails like a concurrent resize for the first calls."""

    def __init__(self, entries: dict[str, Any], failures: int) -> None:
        super().__init__(entries)
        self.failures = failures
        self.copies = 0

    def copy(self) -> dict[str, Any]:
        self.copies += 1
        if self.copies <= self.failures:
            raise RuntimeError("dictionary changed size during iteration")
        return dict(self)


def _install_module(monkeypatch: pytest.MonkeyPatch, name: str, **attrs: Any) -> types.ModuleType:
    module = types.ModuleType(name)
    for attr, value in attrs.items():
        setattr(module, attr, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def test_restore_survives_imports_during_garbage_collection(monkeypatch):
    real = handlers_conftest._real_run_async
    assert real is not None
    polluted = _install_module(
        monkeypatch, "aragora.server._snapshot_race_probe", run_async=MagicMock()
    )
    imported: list[str] = []

    def import_during_collection(phase: str, info: dict[str, int]) -> None:
        if phase == "start" and len(imported) < 200:
            name = f"_snapshot_race_gc_import_{len(imported)}"
            sys.modules[name] = types.ModuleType(name)
            imported.append(name)

    threshold = gc.get_threshold()
    gc.callbacks.append(import_during_collection)
    gc.set_threshold(1)
    try:
        handlers_conftest._restore_polluted_run_async()
    finally:
        gc.set_threshold(*threshold)
        gc.callbacks.remove(import_during_collection)
        for name in imported:
            sys.modules.pop(name, None)

    assert imported, "no garbage collection ran during the restore pass"
    assert polluted.run_async is real


def test_restore_keeps_prefix_and_attribute_filters(monkeypatch):
    real = handlers_conftest._real_run_async
    assert real is not None
    leaked = MagicMock()
    server_mod = _install_module(
        monkeypatch, "aragora.server._snapshot_probe", run_async=leaked, _run_async=leaked
    )
    utils_mod = _install_module(monkeypatch, "aragora.utils._snapshot_probe", run_async=leaked)
    cleared_mod = _install_module(
        monkeypatch, "aragora.server._snapshot_probe_none", run_async=None
    )
    bare_mod = _install_module(monkeypatch, "aragora.server._snapshot_probe_bare")
    other_mod = _install_module(monkeypatch, "_snapshot_probe_elsewhere", run_async=leaked)
    monkeypatch.setitem(sys.modules, "aragora.server._snapshot_probe_blocked", None)

    handlers_conftest._restore_polluted_run_async()

    assert server_mod.run_async is real
    assert server_mod._run_async is real
    assert utils_mod.run_async is real
    assert cleared_mod.run_async is None
    assert not hasattr(bare_mod, "run_async")
    assert other_mod.run_async is leaked


def test_snapshot_retries_a_transient_resize():
    attempts = handlers_conftest._SYS_MODULES_SNAPSHOT_ATTEMPTS
    modules = _ResizingModules({"a": None, "b": None}, failures=attempts - 1)

    assert handlers_conftest._snapshot_sys_modules(modules) == [("a", None), ("b", None)]
    assert modules.copies == attempts


def test_snapshot_reraises_a_persistent_resize():
    attempts = handlers_conftest._SYS_MODULES_SNAPSHOT_ATTEMPTS
    modules = _ResizingModules({"a": None}, failures=attempts + 5)

    with pytest.raises(RuntimeError, match="changed size during iteration"):
        handlers_conftest._snapshot_sys_modules(modules)
    assert modules.copies == attempts
