"""Focused import-contract coverage for the debate memory manager."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_memory_manager_uses_canonical_legacy_event_emitter_protocol() -> None:
    """The memory manager should annotate emitters with the canonical legacy contract."""
    from aragora.debate.memory_manager import MemoryManager
    from aragora.protocols import LegacyEventEmitterProtocol

    annotation = MemoryManager.__init__.__annotations__["event_emitter"]

    assert annotation == LegacyEventEmitterProtocol | None


def test_memory_manager_import_does_not_warn_for_types_protocols_shim() -> None:
    """Importing the memory manager should not traverse the deprecated protocol shim."""
    project_root = Path(__file__).resolve().parents[2]
    script = """
import importlib
import warnings

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    importlib.import_module("aragora.debate.memory_manager")

shim_warnings = [
    str(item.message)
    for item in caught
    if "aragora.types.protocols is deprecated" in str(item.message)
]
assert shim_warnings == [], shim_warnings
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
