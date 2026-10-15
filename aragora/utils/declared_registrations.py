"""Run registration callables declared under a package entry-point group, once.

A lower package that exposes a hook cannot import the upper package that fills it.
The upper package registers from its own init, and a process that never imports it
still reaches the registration through an entry point declared in aragora's
``pyproject.toml``. A source checkout whose installed metadata predates a declaration
also reads it from that ``pyproject.toml``. On Python 3.10 without ``tomli``, the
single-line string entries of the ``[project]`` table and of the group's entry-point
table are read without a TOML library.

A declared registration runs on the first lookup that misses, which can be after the
application registered its own entries in other registries. The upper package it imports
for the first time then runs its own import-time registrations, so a registry that a
package init fills checks :func:`declared_registrations_running` and only fills what is
missing.
"""

from __future__ import annotations

import importlib.metadata
import logging
import re
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

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

_MULTILINE_STRING = re.compile(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'')
_TABLE_HEADER = re.compile(r"\[\[?([^\[\]]+)\]\]?\s*(?:#.*)?")
_KEY_PART = re.compile(r"\"([^\"\\]*)\"|'([^']*)'|([A-Za-z0-9_-]+)")
_STRING_ENTRY = re.compile(
    r"(\"[^\"\\]*\"|'[^']*'|[A-Za-z0-9_-]+)\s*=\s*(?:\"([^\"\\]*)\"|'([^']*)')\s*(?:#.*)?"
)


# Thread-local, so a registration another thread makes meanwhile still replaces. A depth,
# not a flag: a declared registration can trigger another group's first lookup.
_running = threading.local()


def declared_registrations_running() -> bool:
    """Whether this thread is running the declared registrations of any group."""
    return getattr(_running, "depth", 0) > 0


def _toml_module() -> ModuleType | None:
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib
    try:
        import tomli
    except ImportError:
        return None
    return tomli


def _key(text: str) -> tuple[str, ...]:
    return tuple(double or single or bare for double, single, bare in _KEY_PART.findall(text))


def _scan_string_tables(
    text: str, tables: set[tuple[str, ...]]
) -> dict[tuple[str, ...], dict[str, str]]:
    """The single-line ``key = "string"`` entries of the named tables, read without a TOML library.

    Multi-line strings are blanked first, so a ``readme`` body cannot open a table or add an entry.
    """
    found: dict[tuple[str, ...], dict[str, str]] = {}
    current: tuple[str, ...] = ()
    for line in _MULTILINE_STRING.sub('""', text).splitlines():
        header = _TABLE_HEADER.fullmatch(line.strip())
        entry = _STRING_ENTRY.fullmatch(line.strip())
        if header is not None:
            current = _key(header[1])
        elif entry is not None and current in tables:
            value = entry[2] if entry[2] is not None else entry[3]
            found.setdefault(current, {})[_key(entry[1])[0]] = value
    return found


def _read_project(text: str, group: str) -> tuple[Any, dict[str, Any]] | None:
    """The project name and the group's declared entry points, or None if unreadable."""
    toml = _toml_module()
    if toml is None:
        entry_points = ("project", "entry-points", group)
        tables = _scan_string_tables(text, {("project",), entry_points})
        return tables.get(("project",), {}).get("name"), tables.get(entry_points, {})
    try:
        project = toml.loads(text).get("project", {})
    except toml.TOMLDecodeError:
        return None
    return project.get("name"), project.get("entry-points", {}).get(group, {})


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
            declared = installed + [
                ep for ep in self._source_declarations() if ep.value not in installed_targets
            ]
            _running.depth = getattr(_running, "depth", 0) + 1
            try:
                self._run(declared)
            finally:
                _running.depth -= 1

    def _source_declarations(self) -> list[importlib.metadata.EntryPoint]:
        # An editable install keeps the entry points it was installed with, so a source
        # checkout run against older metadata reads the declarations from its own pyproject.
        try:
            text = self._source_pyproject.read_text(encoding="utf-8")
        except OSError:
            return []
        project = _read_project(text, self.group)
        if project is None:
            return []
        name, declared = project
        if name != "aragora":
            return []
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


__all__ = ["DeclaredRegistrations", "SOURCE_PYPROJECT", "declared_registrations_running"]
