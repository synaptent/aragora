"""Compatibility alias for agent-backed semantic extraction helpers."""

from __future__ import annotations

import importlib
import sys
import warnings

warnings.warn(
    "aragora.utils.semantic_extraction is deprecated; import from "
    "aragora.agents.semantic_extraction instead.",
    DeprecationWarning,
    stacklevel=2,
)

_module = importlib.import_module("aragora.agents.semantic_extraction")
sys.modules[__name__] = _module
