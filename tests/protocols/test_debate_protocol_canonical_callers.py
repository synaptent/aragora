"""First-party callers import debate protocol types from their canonical home."""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_MODULE = "aragora.debate.protocol"

MIGRATED_CALLERS = (
    "aragora/agents/code_reviewer.py",
    "aragora/canvas/manager.py",
    "aragora/cli/commands/crux.py",
    "aragora/control_plane/arena_bridge.py",
    "aragora/core/decision_router.py",
    "aragora/debate/team_selector.py",
    "aragora/essay/roles.py",
    "aragora/golden.py",
    "aragora/inbox/debate_router.py",
    "aragora/knowledge/mound/revalidation_scheduler.py",
    "aragora/nomic/hierarchical_coordinator.py",
    "aragora/nomic/outcome_tracker.py",
    "aragora/nomic/task_decomposer.py",
    "aragora/nomic/testfixer/validators/arena_validator.py",
    "aragora/pipeline/dag_operations.py",
    "aragora/server/debate_factory.py",
    "aragora/server/handlers/github/pr_review.py",
    "aragora/templates/__init__.py",
    "aragora/workflow/nodes/nomic.py",
)


def _imported_modules(relative_path: str) -> set[str]:
    tree = ast.parse((PROJECT_ROOT / relative_path).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    return imported


@pytest.mark.parametrize("relative_path", MIGRATED_CALLERS)
def test_caller_does_not_import_legacy_protocol_shim(relative_path: str) -> None:
    assert LEGACY_MODULE not in _imported_modules(relative_path)


def test_module_level_callers_do_not_load_legacy_protocol_shim() -> None:
    script = textwrap.dedent(
        """
        import sys
        import warnings

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import aragora.essay.roles
            import aragora.nomic.testfixer.validators.arena_validator

        shim_warnings = [
            str(w.message)
            for w in caught
            if "aragora.debate.protocol is deprecated" in str(w.message)
        ]
        assert "aragora.debate.protocol" not in sys.modules, "legacy shim was imported"
        assert not shim_warnings, shim_warnings
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_module_level_callers_use_canonical_protocol_objects() -> None:
    import aragora.essay.roles as essay_roles
    import aragora.nomic.testfixer.validators.arena_validator as arena_validator
    import aragora.protocols.debate as canonical

    assert essay_roles.RoundPhase is canonical.RoundPhase
    assert arena_validator.DebateProtocol is canonical.DebateProtocol
