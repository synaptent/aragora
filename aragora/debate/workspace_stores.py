"""Factory hook for the workspace stores the debate engine records beads in.

The debate engine sits below ``aragora.stores`` and must not import it. Importing
``aragora.stores`` stays cheap, so that package does not load the debate engine just to
register here. Instead, the first :func:`get_workspace_stores` that finds no factory runs,
once per process, the registrations declared under the ``aragora.workspace_stores``
entry-point group; aragora's own ``pyproject.toml`` declares the canonical stores there.
A later registration replaces the previous factory.

:func:`get_workspace_stores` raises :class:`WorkspaceStoresNotRegisteredError` when no
factory is registered after that.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aragora.utils.declared_registrations import DeclaredRegistrations

WORKSPACE_STORES_ENTRY_POINT_GROUP = "aragora.workspace_stores"

WorkspaceStoresFactory = Callable[..., Any]


class WorkspaceStoresNotRegisteredError(RuntimeError):
    """No workspace stores factory is registered."""


_factory: WorkspaceStoresFactory | None = None
_declared = DeclaredRegistrations(WORKSPACE_STORES_ENTRY_POINT_GROUP)


def register_workspace_stores_factory(factory: WorkspaceStoresFactory) -> None:
    """Make ``factory`` the builder of workspace stores, replacing any earlier one."""
    global _factory
    _factory = factory


def get_workspace_stores(
    *,
    bead_dir: str | None = None,
    git_enabled: bool = True,
    auto_commit: bool = False,
) -> Any:
    """Build workspace stores (an object with ``async bead_store()``) with the registered factory.

    Raises:
        WorkspaceStoresNotRegisteredError: no factory is registered, even after the
            declared registrations ran.
    """
    factory = _factory
    if factory is None:
        _declared.load()
        factory = _factory
    if factory is None:
        raise WorkspaceStoresNotRegisteredError(
            "no workspace stores factory is registered; import "
            "aragora.stores.debate_registration and call register_debate_workspace_stores(), "
            f"or declare a registration under the {WORKSPACE_STORES_ENTRY_POINT_GROUP!r} "
            "entry-point group"
        )
    return factory(bead_dir=bead_dir, git_enabled=git_enabled, auto_commit=auto_commit)


__all__ = [
    "WORKSPACE_STORES_ENTRY_POINT_GROUP",
    "WorkspaceStoresFactory",
    "WorkspaceStoresNotRegisteredError",
    "get_workspace_stores",
    "register_workspace_stores_factory",
]
