"""Deprecated compatibility shim for :mod:`aragora.server.a2a_runtime`."""

from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "aragora.protocols.a2a.server is deprecated. Use aragora.server.a2a_runtime instead.",
    DeprecationWarning,
    stacklevel=2,
)

_canonical = importlib.import_module("aragora.server.a2a_runtime")
sys.modules[__name__] = _canonical
