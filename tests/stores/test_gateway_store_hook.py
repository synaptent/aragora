"""The canonical gateway stores reach the gateway store through ``aragora.stores.gateway_store_hook``.

``aragora.stores`` (application layer) must not import ``aragora.gateway`` (interface layer),
whose ``get_gateway_store_from_env`` builds the store behind
:meth:`CanonicalGatewayStores.gateway_store`. The gateway registers that builder through the
``aragora.gateway_stores`` entry point.
"""

from __future__ import annotations

import ast
import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from aragora.stores import gateway_store_hook as hook
from aragora.stores.canonical import CanonicalGatewayStores
from aragora.utils.declared_registrations import DeclaredRegistrations

REPO_ROOT = Path(__file__).resolve().parents[2]
GATEWAY_REGISTRATION = (
    "gateway",
    "aragora.gateway.store_registration:register_canonical_gateway_store",
)
PRE_INVERSION_ARGUMENTS = {
    "backend_env": "ARAGORA_GATEWAY_STORE",
    "fallback_backend_env": "ARAGORA_GATEWAY_SESSION_STORE",
    "path_env": "ARAGORA_GATEWAY_STORE_PATH",
    "fallback_path_env": "ARAGORA_GATEWAY_SESSION_PATH",
    "redis_env": "ARAGORA_GATEWAY_STORE_REDIS_URL",
    "fallback_redis_env": "ARAGORA_GATEWAY_SESSION_REDIS_URL",
    "default_backend": "auto",
    "allow_disabled": True,
    "emit_warning": False,
}


@pytest.fixture
def isolated_hook(monkeypatch, tmp_path):
    """An empty hook whose declared registrations have not run and come only from a test."""
    monkeypatch.setattr(hook, "_factory", None)
    monkeypatch.setattr(
        hook,
        "_declared",
        DeclaredRegistrations(
            hook.GATEWAY_STORES_ENTRY_POINT_GROUP, source_pyproject=tmp_path / "missing.toml"
        ),
    )
    monkeypatch.setattr(importlib.metadata, "entry_points", lambda *, group: [])
    return hook


def test_an_unregistered_gateway_store_raises(isolated_hook):
    with pytest.raises(hook.GatewayStoreFactoryNotRegisteredError, match="aragora.gateway_stores"):
        CanonicalGatewayStores().gateway_store()


def test_registering_again_replaces_the_factory_and_the_store_is_kept(isolated_hook):
    first, second = object(), object()
    hook.register_gateway_store_factory(lambda **_: first)
    hook.register_gateway_store_factory(lambda **_: second)
    stores = CanonicalGatewayStores()
    assert stores.gateway_store() is second
    hook.register_gateway_store_factory(lambda **_: first)
    assert stores.gateway_store() is second


def test_a_lookup_miss_runs_the_declared_registrations_once(isolated_hook, monkeypatch):
    calls = []

    def register():
        calls.append("register")
        hook.register_gateway_store_factory(lambda **_: object())

    entry_point = SimpleNamespace(name="d0", value="tests.declared:d0", load=lambda: register)
    monkeypatch.setattr(
        importlib.metadata,
        "entry_points",
        lambda *, group: [entry_point] if group == hook.GATEWAY_STORES_ENTRY_POINT_GROUP else [],
    )
    first = CanonicalGatewayStores().gateway_store()
    assert CanonicalGatewayStores().gateway_store() is not first
    assert calls == ["register"]


def test_pyproject_declares_the_gateway_registration():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    declared = DeclaredRegistrations(hook.GATEWAY_STORES_ENTRY_POINT_GROUP)._source_declarations()
    assert [(ep.name, ep.value) for ep in declared] == [GATEWAY_REGISTRATION]


def test_the_gateway_registration_passes_the_pre_inversion_arguments(isolated_hook, monkeypatch):
    from aragora.gateway import persistence
    from aragora.gateway.store_registration import register_canonical_gateway_store

    calls = []
    store = object()

    def fake_get_gateway_store_from_env(**kwargs):
        calls.append(kwargs)
        return store

    register_canonical_gateway_store()
    register_canonical_gateway_store()
    monkeypatch.setattr(persistence, "get_gateway_store_from_env", fake_get_gateway_store_from_env)
    assert CanonicalGatewayStores(allow_disabled=True).gateway_store() is store
    assert calls == [PRE_INVERSION_ARGUMENTS]


def test_a_stores_only_process_reaches_the_gateway_store():
    if sys.version_info < (3, 11):
        pytest.importorskip("tomli")
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT), "ARAGORA_GATEWAY_STORE": "memory"}
    script = (
        "import sys\n"
        "from aragora.stores.canonical import CanonicalGatewayStores\n"
        "assert not any(m.startswith('aragora.gateway') for m in sys.modules), 'preloaded'\n"
        "store = CanonicalGatewayStores().gateway_store()\n"
        "print(type(store).__module__, type(store).__name__)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split()[-2:] == ["aragora.gateway.persistence", "InMemoryGatewayStore"]


def _runtime_imports(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    annotation_only: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
            for child in node.body:
                annotation_only.update(range(child.lineno, (child.end_lineno or child.lineno) + 1))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if getattr(node, "lineno", None) in annotation_only:
            continue
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


def test_stores_holds_no_runtime_import_of_the_gateway():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{lineno}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "stores").rglob("*.py"))
        for lineno, name in _runtime_imports(path)
        if name == "aragora.gateway" or name.startswith("aragora.gateway.")
    ]
    assert offenders == []
