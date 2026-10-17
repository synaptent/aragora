"""Hook through which threat intelligence enrichment builds a CVE lookup client.

``aragora.security`` sits below ``aragora.analysis``, whose codebase scanner holds the client for
the NVD, OSV and GitHub advisory databases, and must not import it. The first
:func:`create_cve_client` that finds no factory runs, once per process, the registrations
declared under the ``aragora.security_cve_clients`` entry-point group; aragora's own
``pyproject.toml`` declares the analysis package there. A later registration replaces the
previous factory.

:func:`create_cve_client` raises :class:`CVEClientNotRegisteredError` when no factory is
registered after that.
"""

from __future__ import annotations

from typing import Any, Protocol

from aragora.utils.declared_registrations import DeclaredRegistrations

CVE_CLIENTS_ENTRY_POINT_GROUP = "aragora.security_cve_clients"


class CVEClientFactory(Protocol):
    """Builds a CVE lookup client with its default configuration.

    The client answers ``await client.get_cve(cve_id)``. The factory raises ``ImportError``
    when the client's module cannot be imported.
    """

    def __call__(self) -> Any: ...


class CVEClientNotRegisteredError(RuntimeError):
    """No CVE client factory is registered."""


_factory: CVEClientFactory | None = None
_declared = DeclaredRegistrations(CVE_CLIENTS_ENTRY_POINT_GROUP)


def register_cve_client_factory(factory: CVEClientFactory) -> None:
    """Make ``factory`` build CVE clients, replacing any earlier one."""
    global _factory
    _factory = factory


def create_cve_client() -> Any:
    """Build a CVE lookup client with the registered factory.

    Raises:
        CVEClientNotRegisteredError: no factory is registered, even after the declared
            registrations ran.
    """
    factory = _factory
    if factory is None:
        _declared.load()
        factory = _factory
    if factory is None:
        raise CVEClientNotRegisteredError(
            "no CVE client factory is registered; import aragora.analysis.codebase.cve_registration "
            "and call register_security_cve_client(), or declare a registration under the "
            f"{CVE_CLIENTS_ENTRY_POINT_GROUP!r} entry-point group"
        )
    return factory()


__all__ = [
    "CVE_CLIENTS_ENTRY_POINT_GROUP",
    "CVEClientFactory",
    "CVEClientNotRegisteredError",
    "create_cve_client",
    "register_cve_client_factory",
]
