"""Pin the ``HardenedOrchestrator.aragora_path`` declaration as annotation-only.

The class-level annotation exists for the CI changed-file mypy gate, which runs with
``--follow-imports=skip`` and so cannot see ``AutonomousOrchestrator.__init__``. It
must not become a class default: the path always comes from the constructor.
"""

from __future__ import annotations

from pathlib import Path

from aragora.nomic.hardened_orchestrator import HardenedOrchestrator


def test_aragora_path_is_declared_without_a_class_default() -> None:
    assert HardenedOrchestrator.__annotations__["aragora_path"] == "Path"
    assert "aragora_path" not in vars(HardenedOrchestrator)


def test_aragora_path_still_comes_from_the_constructor(tmp_path: Path) -> None:
    assert HardenedOrchestrator(aragora_path=tmp_path).aragora_path == tmp_path
