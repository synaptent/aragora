"""Standalone Aragora debate wedge.

This package intentionally exposes only the minimal offline debate surface that is
truthful for the ``aragora-debate`` distribution:

- ``Environment`` and core message/result types
- ``DebateProtocol`` for debate configuration
- ``Arena`` for running a minimal async debate with mock or real agents
"""

from __future__ import annotations

import importlib
from typing import Any

__version__ = "2.8.0"

_EXPORT_MAP = {
    "Agent": ("aragora.core", "Agent"),
    "Critique": ("aragora.core", "Critique"),
    "DebateProtocol": ("aragora.debate", "DebateProtocol"),
    "DebateResult": ("aragora.core", "DebateResult"),
    "Environment": ("aragora.core", "Environment"),
    "Message": ("aragora.core", "Message"),
    "Vote": ("aragora.core", "Vote"),
    "Arena": ("aragora.debate", "Arena"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORT_MAP[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = sorted(_EXPORT_MAP)
