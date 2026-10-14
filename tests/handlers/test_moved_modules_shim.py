"""Old flat handler paths listed in MOVED_MODULES keep working through the shim.

Every key of ``aragora.server.handlers._lazy_imports.MOVED_MODULES`` is probed
the way ``scripts/ci/check_moved_handler_shim.py`` probes one by hand: import
``aragora.server.handlers.<key>`` (falling back to the package ``__getattr__``
form), expect a DeprecationWarning naming the key, and expect the canonical
module object back. The canonical modules themselves must import without
emitting a shim warning, and no key may be shadowed by a real module.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.machinery
import json
import os
import subprocess
import sys
import warnings
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import aragora
import aragora.server.handlers as handlers_pkg
from aragora.server.handlers._lazy_imports import MOVED_MODULES

PACKAGE = "aragora.server.handlers"
REPO_ROOT = Path(__file__).resolve().parents[2]
_MISSING = object()

# The parametrized cases are generated from MOVED_MODULES itself, so deleting an
# entry would silently delete its case as well. Lower this floor only when a
# shim is retired on purpose.
MIN_MOVED_MODULES = 170

# Runs in a fresh interpreter. Each canonical module is imported in its own
# "window"; a module pulled in as a dependency of an earlier window is charged
# to that window, so every target's first import is checked exactly once.
_FRESH_IMPORT_PROBE = """
import importlib
import json
import sys
import warnings

report_path, package = sys.argv[1], sys.argv[2]
prefix = package + "."


def import_window(name):
    before = set(sys.modules)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        importlib.import_module(name)
    shim = [
        str(w.message)
        for w in caught
        if issubclass(w.category, DeprecationWarning) and str(w.message).startswith(prefix)
    ]
    return set(sys.modules) - before, shim


first_window = {}
window_warnings = {}
loaded, window_warnings[package] = import_window(package)
first_window.update(dict.fromkeys(loaded, package))
moved = importlib.import_module(package + "._lazy_imports").MOVED_MODULES
targets = sorted(set(moved.values()))
for target in targets:
    if target in sys.modules:
        continue
    loaded, window_warnings[target] = import_window(target)
    for name in loaded:
        first_window.setdefault(name, target)

import aragora

with open(report_path, "w", encoding="utf-8") as fh:
    json.dump(
        {
            "aragora_file": aragora.__file__,
            "first_window": {t: first_window.get(t) for t in targets},
            "window_warnings": window_warnings,
        },
        fh,
    )
"""


@contextlib.contextmanager
def _without_cached_old_path(key: str) -> Iterator[None]:
    """Make the next import of the old path go through the finder again.

    The import system caches the old name in ``sys.modules`` and also binds it
    as an attribute of the package, which would bypass ``__getattr__`` in the
    fallback form. Both are dropped for the probe and restored afterwards so
    other tests see the state they had before.
    """
    old_name = f"{PACKAGE}.{key}"
    package_dict = vars(handlers_pkg)
    saved_module = sys.modules.pop(old_name, _MISSING)
    saved_attr = package_dict.pop(key, _MISSING)
    try:
        yield
    finally:
        if saved_module is _MISSING:
            sys.modules.pop(old_name, None)
        else:
            sys.modules[old_name] = saved_module  # type: ignore[assignment]
        if saved_attr is _MISSING:
            package_dict.pop(key, None)
        else:
            package_dict[key] = saved_attr


def _import_old_path(key: str) -> tuple[Any, list[warnings.WarningMessage]]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            obj = importlib.import_module(f"{PACKAGE}.{key}")
        except ModuleNotFoundError:
            obj = getattr(importlib.import_module(PACKAGE), key)
    return obj, list(caught)


@pytest.fixture(scope="module")
def fresh_import_report(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Import every canonical target once in a fresh interpreter.

    In the test process most targets are already cached by earlier imports, so
    importing them again here would pass without running any module body.
    """
    workdir = tmp_path_factory.mktemp("moved_modules_shim")
    report_path = workdir / "report.json"
    env = dict(os.environ)
    env["ARAGORA_DATA_DIR"] = str(workdir / "data")
    completed = subprocess.run(
        [sys.executable, "-c", _FRESH_IMPORT_PROBE, str(report_path), PACKAGE],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]
    report: dict[str, Any] = json.loads(report_path.read_text(encoding="utf-8"))
    assert Path(report["aragora_file"]).resolve() == Path(aragora.__file__).resolve(), (
        f"fresh interpreter imported {report['aragora_file']}, "
        f"but this test process uses {aragora.__file__}"
    )
    return report


@pytest.mark.parametrize("key", sorted(MOVED_MODULES))
def test_old_path_warns_and_resolves_to_canonical_module(key: str) -> None:
    target = MOVED_MODULES[key]
    with _without_cached_old_path(key):
        obj, caught = _import_old_path(key)

    deprecations = [
        w for w in caught if issubclass(w.category, DeprecationWarning) and key in str(w.message)
    ]
    assert deprecations, (
        f"importing {PACKAGE}.{key} emitted no DeprecationWarning naming {key!r}; "
        f"got {[str(w.message)[:120] for w in caught][:10]}"
    )
    assert any(target in str(w.message) for w in deprecations), (
        f"the DeprecationWarning for {key!r} does not point callers at {target}: "
        f"{[str(w.message) for w in deprecations]}"
    )
    assert obj is importlib.import_module(target)


@pytest.mark.parametrize("key", sorted(MOVED_MODULES))
def test_canonical_module_imports_without_shim_warning(
    key: str, fresh_import_report: dict[str, Any]
) -> None:
    target = MOVED_MODULES[key]
    window = fresh_import_report["first_window"][target]
    assert window is not None, f"{target} was already imported before the probe started"
    shim_warnings = fresh_import_report["window_warnings"][window]
    assert shim_warnings == [], (
        f"importing {window} in a fresh interpreter (which first loaded {target}) "
        f"went through old handler paths: {shim_warnings}"
    )


def test_no_moved_module_key_shadows_a_real_module() -> None:
    """The finder runs after the path finder, so a real module would win silently."""
    search_path = list(handlers_pkg.__path__)
    shadowed = sorted(
        key
        for key in MOVED_MODULES
        if importlib.machinery.PathFinder.find_spec(f"{PACKAGE}.{key}", search_path) is not None
    )
    assert shadowed == [], f"real modules or packages shadow these MOVED_MODULES keys: {shadowed}"


def test_moved_modules_table_is_not_shrunk() -> None:
    assert len(MOVED_MODULES) >= MIN_MOVED_MODULES, (
        f"MOVED_MODULES has {len(MOVED_MODULES)} entries, below the floor of "
        f"{MIN_MOVED_MODULES}; lower MIN_MOVED_MODULES only when retiring a shim on purpose"
    )
