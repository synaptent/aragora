"""The Handoff/Dispatch contract leaf shared by the orchestrator and the swarm.

``swarm`` needs the worker contract types and ``orchestrator`` needs the swarm's
ledger reconcile; hosting the contract in a leaf lets the swarm stop importing
the orchestrator while the orchestrator keeps re-exporting the public names.
"""

from __future__ import annotations

import ast
from pathlib import Path

from aragora.missions import handoff, orchestrator, swarm

_MISSIONS_DIR = Path(orchestrator.__file__).resolve().parent
_PACKAGE = "aragora.missions"


def _imported_modules(path: Path) -> set[str]:
    """Absolute dotted names imported by ``path``, with relative imports resolved."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
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
    return names


def test_orchestrator_reexports_the_leaf_contract():
    assert orchestrator.Handoff is handoff.Handoff
    assert orchestrator.Dispatch is handoff.Dispatch


def test_package_surface_still_exposes_handoff():
    from aragora.missions import Handoff

    assert Handoff is handoff.Handoff
    assert swarm.Handoff is handoff.Handoff


def test_swarm_does_not_import_the_orchestrator():
    imports = _imported_modules(_MISSIONS_DIR / "swarm.py")
    assert not any(name.startswith("aragora.missions.orchestrator") for name in imports), imports
    assert "aragora.missions.handoff.Handoff" in imports


def test_leaf_depends_only_on_state():
    imports = _imported_modules(_MISSIONS_DIR / "handoff.py")
    internal = {name for name in imports if name.startswith("aragora.missions")}
    assert internal <= {"aragora.missions.state", "aragora.missions.state.Feature"}, internal


def test_handoff_defaults_are_unchanged():
    h = handoff.Handoff()
    assert (h.success, h.terminal, h.awaiting_claim, h.parked, h.parked_kind) == (
        False,
        False,
        False,
        False,
        None,
    )
    assert h.blocked_reason is None
    assert h.follow_ups == []
    assert h.accept_follow_ups is False
    assert h.discovered == []
    assert h.session_id is None
