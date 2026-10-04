"""Import-contract coverage for the deprecated protocol shim modules.

``aragora.types.protocols`` and ``aragora.type_protocols`` are one-release
compatibility shims. Production code must import the canonical
``aragora.protocols`` names so the shims can be deleted without leaving
dangling imports. The allowlists below name the callers that have not
migrated yet; they may only shrink.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = PROJECT_ROOT / "aragora"

TYPES_PROTOCOLS_SHIM = "aragora.types.protocols"
TYPE_PROTOCOLS_SHIM = "aragora.type_protocols"

SHIM_FILES = frozenset({"aragora/types/protocols.py", "aragora/type_protocols.py"})

PENDING_TYPES_PROTOCOLS_IMPORTERS = frozenset({"aragora/server/stream/debate_executor.py"})

P6_OWNED_TYPE_PROTOCOLS_IMPORTERS = frozenset(
    {
        "aragora/debate/phases/consensus_storage.py",
        "aragora/storage/redis_cluster.py",
        "aragora/storage/redis_utils.py",
    }
)

# The shim's ``EventEmitterProtocol`` aliases the legacy contract, not the
# same-named domain protocol exported by ``aragora.protocols``.
MIGRATED_LEGACY_EMITTER_MODULES = (
    "aragora/debate/arena_initializer.py",
    "aragora/debate/orchestrator.py",
    "aragora/knowledge/mound/core.py",
    "aragora/knowledge/mound/facade.py",
    "aragora/memory/continuum/coordinator.py",
    "aragora/memory/continuum/core.py",
    "aragora/memory/continuum/singleton.py",
)

_BARE_EMITTER_NAME = re.compile(r"\bEventEmitterProtocol\b")


def _module_name(rel_path: str) -> str:
    parts = rel_path[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_from_import(node: ast.ImportFrom, rel_path: str) -> str:
    if node.level == 0:
        return node.module or ""
    package = _module_name(rel_path).split(".")
    if not rel_path.endswith("__init__.py"):
        package = package[:-1]
    if node.level > 1:
        package = package[: -(node.level - 1)]
    return ".".join(package + ([node.module] if node.module else []))


def _imported_modules(tree: ast.AST, rel_path: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from_import(node, rel_path)
            modules.add(base)
            modules.update(f"{base}.{alias.name}" for alias in node.names)
    return modules


def _shim_importers(shim: str) -> set[str]:
    importers: set[str] = set()
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        rel_path = path.relative_to(PROJECT_ROOT).as_posix()
        if rel_path in SHIM_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path)
        if shim in _imported_modules(tree, rel_path):
            importers.add(rel_path)
    return importers


def _is_type_checking_guard(node: ast.If) -> bool:
    test = node.test
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def test_types_protocols_shim_importers_are_allowlisted() -> None:
    assert _shim_importers(TYPES_PROTOCOLS_SHIM) <= PENDING_TYPES_PROTOCOLS_IMPORTERS


def test_type_protocols_shim_importers_are_p6_owned() -> None:
    assert _shim_importers(TYPE_PROTOCOLS_SHIM) <= P6_OWNED_TYPE_PROTOCOLS_IMPORTERS


@pytest.mark.parametrize("rel_path", MIGRATED_LEGACY_EMITTER_MODULES)
def test_emitter_annotations_use_canonical_legacy_protocol(rel_path: str) -> None:
    source = (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=rel_path)

    guarded_imports = [
        alias.name
        for guard in ast.walk(tree)
        if isinstance(guard, ast.If) and _is_type_checking_guard(guard)
        for stmt in guard.body
        if isinstance(stmt, ast.ImportFrom)
        and stmt.level == 0
        and stmt.module == "aragora.protocols"
        for alias in stmt.names
        if alias.asname is None
    ]
    assert "LegacyEventEmitterProtocol" in guarded_imports

    bare_references = [
        node.lineno
        for node in ast.walk(tree)
        if (isinstance(node, ast.Name) and node.id == "EventEmitterProtocol")
        or (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _BARE_EMITTER_NAME.search(node.value)
        )
    ]
    assert bare_references == []
