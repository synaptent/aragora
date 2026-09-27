"""Deprecated import location for the provenance store.

The store moved up to :mod:`aragora.reasoning.provenance_store`, alongside the
domain types it persists. This compatibility module aliases the relocated
implementation without retaining a static infrastructure-to-domain edge.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from typing import TYPE_CHECKING, Any

_TARGET_MODULE = ".".join(("aragora", "reasoning", "provenance_store"))
_target = importlib.import_module(_TARGET_MODULE)

warnings.warn(
    "aragora.storage.provenance_store is deprecated; import from "
    "aragora.reasoning.provenance_store instead.",
    DeprecationWarning,
    stacklevel=2,
)

if TYPE_CHECKING:

    def __getattr__(name: str) -> Any: ...
else:
    # Preserve class and monkeypatch identity at the legacy path.
    sys.modules[__name__] = _target
