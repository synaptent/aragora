"""Registers the codebase scanner's CVE client as the security package's CVE client factory.

Reached through the ``aragora.security_cve_clients`` entry point in ``pyproject.toml`` on the
first CVE client that threat intelligence enrichment builds, so ``aragora.security`` never
imports ``aragora.analysis``.
"""

from __future__ import annotations

from typing import Any

from aragora.security.cve_clients import register_cve_client_factory


def build_cve_client() -> Any:
    """A ``CVEClient`` with its default configuration.

    The module is imported on each call, as the security package's own import was, so a
    patched ``CVEClient`` applies and a module that cannot be imported raises ``ImportError``.
    """
    from aragora.analysis.codebase.cve_client import CVEClient

    return CVEClient()


def register_security_cve_client() -> None:
    """Register the CVE client factory; safe to call more than once."""
    register_cve_client_factory(build_cve_client)


__all__ = ["build_cve_client", "register_security_cve_client"]
