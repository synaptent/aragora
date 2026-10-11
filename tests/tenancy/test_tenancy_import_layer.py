"""aragora.tenancy (infrastructure) must not import aragora.server (interface).

Function-scope imports count too; only ``if TYPE_CHECKING:`` blocks are exempt
(docs/architecture/IMPORT_LAYERS.md).
"""

from __future__ import annotations

import ast
from pathlib import Path

TENANCY_DIR = Path(__file__).resolve().parents[2] / "aragora" / "tenancy"


def _imported_modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
    return []


def _server_imports(tree: ast.AST) -> list[str]:
    exempt = {
        id(child)
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test)
        for child in ast.walk(node)
    }
    return [
        name
        for node in ast.walk(tree)
        if id(node) not in exempt
        for name in _imported_modules(node)
        if name.split(".")[:2] == ["aragora", "server"]
    ]


def test_tenancy_has_no_runtime_import_of_the_server_package() -> None:
    offenders = {
        path.name: found
        for path in sorted(TENANCY_DIR.rglob("*.py"))
        if (found := _server_imports(ast.parse(path.read_text(encoding="utf-8"))))
    }
    assert offenders == {}
