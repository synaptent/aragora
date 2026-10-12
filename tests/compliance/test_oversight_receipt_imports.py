"""The oversight modules take receipt primitives from aragora.models.receipts, not the gauntlet."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OVERSIGHT_MODULES = [
    "aragora/compliance/oversight_fetch.py",
    "aragora/compliance/oversight_pack.py",
]


def _imported_modules(tree: ast.AST) -> set[str]:
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in {"import_module", "__import__"}:
                imported.add("<dynamic import>")
    return imported


@pytest.mark.parametrize("path", OVERSIGHT_MODULES)
def test_oversight_module_holds_no_gauntlet_import(path: str) -> None:
    imported = _imported_modules(ast.parse((ROOT / path).read_text(encoding="utf-8")))

    assert "<dynamic import>" not in imported
    assert (
        sorted(
            name
            for name in imported
            if name == "aragora.gauntlet" or name.startswith("aragora.gauntlet.")
        )
        == []
    )


def test_flipped_names_are_the_objects_at_the_old_paths() -> None:
    from aragora.compliance import oversight_fetch, oversight_pack
    from aragora.gauntlet import attestation, odr_export

    assert oversight_pack.jcs_canonicalize is odr_export.jcs_canonicalize
    assert oversight_pack.AUTONOMOUS_DISPOSITION is attestation.AUTONOMOUS_DISPOSITION
    assert oversight_pack.HUMAN_ATTESTED_DISPOSITION is attestation.HUMAN_ATTESTED_DISPOSITION
    assert oversight_fetch.HUMAN_SETTLEMENT_CONTEXT is attestation.HUMAN_SETTLEMENT_CONTEXT
    assert (
        oversight_fetch.attestation_from_settlement_status
        is attestation.attestation_from_settlement_status
    )
