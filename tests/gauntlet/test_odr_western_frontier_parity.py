"""The western-frontier family literal both verifiers inline is the canonical set.

The dependency policy forbids the standalone package from importing ``aragora``, so
the set is written out in each engine instead of shared. Nothing else pins those two
literals to ``WESTERN_FRONTIER_FAMILIES``, which is what this reads back out of the
sources through the ``aragora-verify/src`` path shim.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_ARAGORA_VERIFY_SRC = _ROOT / "aragora-verify" / "src"
if str(_ARAGORA_VERIFY_SRC) not in sys.path:
    sys.path.insert(0, str(_ARAGORA_VERIFY_SRC))

import aragora_verify.verifier as package_verifier  # noqa: E402

from aragora.gauntlet import odr_verify as in_repo_verifier  # noqa: E402
from aragora.swarm.quorum_evidence import WESTERN_FRONTIER_FAMILIES  # noqa: E402


def _inlined_family_sets(module: object) -> list[frozenset[str]]:
    """Every ``<expr> & {"a", "b"}`` string-set literal in the module's source."""
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    return [
        frozenset(element.value for element in node.right.elts)
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.BitAnd)
        and isinstance(node.right, ast.Set)
        and node.right.elts
        and all(
            isinstance(element, ast.Constant) and isinstance(element.value, str)
            for element in node.right.elts
        )
    ]


def test_both_verifier_family_literals_equal_the_canonical_set() -> None:
    package = _inlined_family_sets(package_verifier)
    in_repo = _inlined_family_sets(in_repo_verifier)

    assert len(package) == 1, package
    assert len(in_repo) == 1, in_repo
    assert package[0] == frozenset(WESTERN_FRONTIER_FAMILIES)
    assert in_repo[0] == frozenset(WESTERN_FRONTIER_FAMILIES)
