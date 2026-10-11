"""aragora.tenancy (infrastructure layer) must not import aragora.server (interface layer).

import-linter counts every runtime import, at module or function scope; only
imports under ``if TYPE_CHECKING:`` are excluded (docs/architecture/IMPORT_LAYERS.md).
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

TENANCY_DIR = Path(__file__).resolve().parents[2] / "aragora" / "tenancy"


def _runtime_imports(tree: ast.AST) -> Iterator[str]:
    type_checking = {
        id(child)
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test)
        for statement in node.body
        for child in ast.walk(statement)
    }
    for node in ast.walk(tree):
        if id(node) in type_checking:
            continue
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module
            if node.module == "aragora":
                yield from (f"aragora.{alias.name}" for alias in node.names)


def test_tenancy_has_no_runtime_import_of_the_server_package() -> None:
    offenders = [
        f"{path.name}:{name}"
        for path in sorted(TENANCY_DIR.rglob("*.py"))
        for name in _runtime_imports(ast.parse(path.read_text(encoding="utf-8")))
        if name == "aragora.server" or name.startswith("aragora.server.")
    ]
    assert offenders == []
