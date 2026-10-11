"""Run registration callables declared under a package entry-point group, once.

A lower package that exposes a hook cannot import the upper package that fills it.
The upper package registers from its own init, and a process that never imports it
still reaches the registration through an entry point declared in aragora's
``pyproject.toml``. A source checkout whose installed metadata predates a declaration
also reads it from that ``pyproject.toml`` (on Python 3.10 only when ``tomli`` is
installed).
"""

from __future__ import annotations

import importlib.metadata
import logging
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

SOURCE_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

_REGISTRATION_ERRORS = (
    ImportError,
    SyntaxError,
    AttributeError,
    LookupError,
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
)


class DeclaredRegistrations:
    """The registrations declared under one entry-point group, run at most once per process."""

    def __init__(self, group: str, *, source_pyproject: Path = SOURCE_PYPROJECT) -> None:
        self.group = group
        self._source_pyproject = source_pyproject
        self._loaded = False
        self._lock = threading.RLock()

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self) -> None:
        """Run every declared registration callable; later calls do nothing."""
        with self._lock:
            if self._loaded:
                return
            # Set before loading: a registration that uses the hook must not start another load.
            self._loaded = True
            try:
                installed = list(importlib.metadata.entry_points(group=self.group))
            except _REGISTRATION_ERRORS as exc:
                logger.warning("Reading the %s entry points failed: %s", self.group, exc)
                installed = []
            # Merged by target rather than by name: an unrelated plugin with the same entry-point
            # name must not hide a declaration that only the source checkout carries yet, and no
            # registration runs twice.
            installed_targets = {entry_point.value for entry_point in installed}
            self._run(
                installed
                + [ep for ep in self._source_declarations() if ep.value not in installed_targets]
            )

    def _source_declarations(self) -> list[importlib.metadata.EntryPoint]:
        # An editable install keeps the entry points it was installed with, so a source
        # checkout run against older metadata reads the declarations from its own pyproject.
        if sys.version_info >= (3, 11):
            import tomllib
        else:
            try:
                import tomli as tomllib
            except ImportError:
                return []

        try:
            project = tomllib.loads(self._source_pyproject.read_text(encoding="utf-8")).get(
                "project", {}
            )
        except (OSError, tomllib.TOMLDecodeError):
            return []
        if project.get("name") != "aragora":
            return []
        declared = project.get("entry-points", {}).get(self.group, {})
        return [
            importlib.metadata.EntryPoint(name, value, self.group)
            for name, value in declared.items()
        ]

    def _run(self, entry_points: list[importlib.metadata.EntryPoint]) -> None:
        if not entry_points:
            return
        entry_point, rest = entry_points[0], entry_points[1:]
        try:
            entry_point.load()()
        except _REGISTRATION_ERRORS as exc:
            logger.warning("Registration %s (%s) failed: %s", entry_point.value, self.group, exc)
        finally:
            # The rest run even when an error of another type escapes, so one broken plugin
            # cannot keep aragora's own registration from running; that error still reaches
            # the caller afterwards.
            self._run(rest)


__all__ = ["DeclaredRegistrations", "SOURCE_PYPROJECT"]
