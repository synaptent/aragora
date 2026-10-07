"""Registry of the code scanners the codebase understanding agent builds.

``aragora.agents`` sits in the domain layer, so it cannot import the audit package
(application layer) that implements the security scanner and the bug detector. The
audit package registers a factory for each scanner kind here from its own init, and
:class:`~aragora.agents.codebase_agent.CodebaseUnderstandingAgent` builds its scanners
through :func:`create_code_scanner`.

A process that only imports ``aragora.agents`` never loads the audit package. The
first lookup that finds nothing registered therefore runs, once per process, the
registrations declared under the ``aragora.code_scanners`` entry-point group;
aragora's own ``pyproject.toml`` declares the audit registration there.

:func:`create_code_scanner` raises :class:`CodeScannerNotRegisteredError` when nothing
is registered for a kind after that. Registration is keyed, so registering again
replaces the previous factory instead of adding a second one.
"""

from __future__ import annotations

import importlib.metadata
import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CODE_SCANNERS_ENTRY_POINT_GROUP = "aragora.code_scanners"

SECURITY_SCANNER = "security_scanner"
BUG_DETECTOR = "bug_detector"

CodeScannerFactory = Callable[[], Any]


class CodeScannerNotRegisteredError(LookupError):
    """No factory is registered for the requested code scanner kind."""


_factories: dict[str, CodeScannerFactory] = {}

_declared_registrations_loaded = False
_declared_registrations_lock = threading.RLock()
_SOURCE_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"

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


def _source_checkout_registrations() -> list[importlib.metadata.EntryPoint]:
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
        project = tomllib.loads(_SOURCE_PYPROJECT.read_text(encoding="utf-8")).get("project", {})
    except (OSError, tomllib.TOMLDecodeError):
        return []
    if project.get("name") != "aragora":
        return []
    declared = project.get("entry-points", {}).get(CODE_SCANNERS_ENTRY_POINT_GROUP, {})
    return [
        importlib.metadata.EntryPoint(name, value, CODE_SCANNERS_ENTRY_POINT_GROUP)
        for name, value in declared.items()
    ]


def _load_declared_registrations() -> None:
    """Run every registration declared under the ``aragora.code_scanners`` group, once."""
    global _declared_registrations_loaded
    with _declared_registrations_lock:
        if _declared_registrations_loaded:
            return
        # Set before loading: a registration that builds a scanner must not start another load.
        _declared_registrations_loaded = True
        declared = (
            list(importlib.metadata.entry_points(group=CODE_SCANNERS_ENTRY_POINT_GROUP))
            or _source_checkout_registrations()
        )
        _run_registrations(declared)


def _run_registrations(entry_points: list[importlib.metadata.EntryPoint]) -> None:
    if not entry_points:
        return
    entry_point, rest = entry_points[0], entry_points[1:]
    try:
        entry_point.load()()
    except _REGISTRATION_ERRORS as exc:
        logger.warning("Code scanner registration %s failed: %s", entry_point.value, exc)
    finally:
        # The rest run even when an error of another type escapes, so one broken plugin
        # cannot keep aragora's own registration from running; that error still reaches
        # the caller afterwards.
        _run_registrations(rest)


def register_code_scanner(kind: str, factory: CodeScannerFactory) -> None:
    """Register ``factory`` as the builder of the scanner named ``kind``."""
    _factories[kind] = factory


def create_code_scanner(kind: str) -> Any:
    """Build a new scanner of ``kind`` with its registered factory."""
    if kind not in _factories:
        _load_declared_registrations()
    try:
        factory = _factories[kind]
    except KeyError:
        raise CodeScannerNotRegisteredError(
            f"No code scanner registered for {kind!r}; the audit package registers it when it "
            f"is loaded, and no {CODE_SCANNERS_ENTRY_POINT_GROUP!r} entry point registered it"
        ) from None
    return factory()


__all__ = [
    "BUG_DETECTOR",
    "CODE_SCANNERS_ENTRY_POINT_GROUP",
    "CodeScannerFactory",
    "CodeScannerNotRegisteredError",
    "SECURITY_SCANNER",
    "create_code_scanner",
    "register_code_scanner",
]
