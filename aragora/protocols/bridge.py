"""Deprecated compatibility shim for :mod:`aragora.server.protocol_bridge`."""

from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "aragora.protocols.bridge is deprecated. Use aragora.server.protocol_bridge instead.",
    DeprecationWarning,
    stacklevel=2,
)

_canonical = importlib.import_module("aragora.server.protocol_bridge")
sys.modules[__name__] = _canonical
