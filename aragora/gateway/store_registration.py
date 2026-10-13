"""Registers the gateway store builder with :mod:`aragora.stores.gateway_store_hook`.

Reached through the ``aragora.gateway_stores`` entry point in ``pyproject.toml`` on the
canonical gateway stores' first lookup, so ``aragora.stores`` never imports the gateway.
"""

from __future__ import annotations

from typing import Any

from aragora.gateway import persistence
from aragora.stores.gateway_store_hook import register_gateway_store_factory


def build_gateway_store_from_env(**kwargs: Any) -> Any:
    """Build the gateway store with :func:`aragora.gateway.persistence.get_gateway_store_from_env`."""
    # Looked up on each call so a patched module function applies.
    return persistence.get_gateway_store_from_env(**kwargs)


def register_canonical_gateway_store() -> None:
    """Register the gateway store builder; safe to call more than once."""
    register_gateway_store_factory(build_gateway_store_from_env)


__all__ = ["build_gateway_store_from_env", "register_canonical_gateway_store"]
