"""``dev_leases`` / ``dev_receipts`` consume ``core`` through the package facade.

``core`` delegates lease and receipt operations to those two modules with
function-local imports, and they in turn need ``core``'s helpers. The package
``__init__`` is the designated consumer surface (PEP 562 fall-through to
``core``), so routing the runtime dependency through it leaves ``core`` as the
only module with a concrete edge into the pair.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

import aragora.nomic.dev_coordination as facade
from aragora.nomic import dev_leases, dev_receipts
from aragora.nomic.dev_coordination import core

_NOMIC_DIR = Path(dev_leases.__file__).resolve().parent
_PACKAGE = "aragora.nomic"


def _runtime_imports(path: Path) -> set[str]:
    """Absolute dotted names imported at runtime (``TYPE_CHECKING`` blocks excluded)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()

    def visit(nodes: list[ast.stmt]) -> None:
        for node in nodes:
            if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
                visit(node.orelse)
                continue
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    parts = _PACKAGE.split(".")
                    base = ".".join(parts[: len(parts) - node.level + 1])
                    module = f"{base}.{node.module}" if node.module else base
                else:
                    module = node.module or ""
                names.add(module)
                names.update(f"{module}.{alias.name}" for alias in node.names)
            for field in ("body", "orelse", "finalbody", "handlers"):
                children = getattr(node, field, None)
                if isinstance(children, list):
                    visit([c for c in children if isinstance(c, ast.stmt)])
                    for handler in [c for c in children if isinstance(c, ast.ExceptHandler)]:
                        visit(handler.body)

    visit(tree.body)
    return names


@pytest.mark.parametrize("module_name", ["dev_leases", "dev_receipts"])
def test_module_has_no_runtime_edge_into_core(module_name: str):
    imports = _runtime_imports(_NOMIC_DIR / f"{module_name}.py")
    assert not any(name.startswith("aragora.nomic.dev_coordination.core") for name in imports), (
        imports
    )
    assert "aragora.nomic.dev_coordination" in imports


@pytest.mark.parametrize("module", [dev_leases, dev_receipts])
def test_facade_resolves_every_consumed_name_to_the_core_object(module):
    source = Path(module.__file__).read_text(encoding="utf-8")
    names = sorted(set(re.findall(r"\b_dev\.([A-Za-z_][A-Za-z0-9_]*)", source)))
    assert names, "expected the module to consume helpers through `_dev`"
    mismatches = [n for n in names if getattr(facade, n) is not getattr(core, n)]
    assert mismatches == []
    assert module._dev is facade


def test_leases_claims_overlap_is_the_core_implementation():
    assert dev_leases._claims_overlap is core._claims_overlap
    assert dev_receipts._path_matches_glob is core._path_matches_glob


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("aragora.nomic.dev_leases", "aragora.nomic.dev_coordination.core"),
        ("aragora.nomic.dev_receipts", "aragora.nomic.dev_coordination.core"),
        ("aragora.nomic.dev_coordination.core", "aragora.nomic.dev_receipts"),
    ],
)
def test_modules_import_in_either_order(first: str, second: str):
    result = subprocess.run(
        [sys.executable, "-c", f"import {first}, {second}; print('ok')"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"
