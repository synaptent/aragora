"""Deprecated import location for the debate storage adapter."""

from __future__ import annotations

import importlib
import sys
import warnings
from typing import TYPE_CHECKING, Any

_TARGET_MODULE = ".".join(("aragora", "export", "storage_adapter"))
_target = importlib.import_module(_TARGET_MODULE)

warnings.warn(
    "aragora.storage.adapters is deprecated; import from aragora.export.storage_adapter instead.",
    DeprecationWarning,
    stacklevel=2,
)

if TYPE_CHECKING:

    def __getattr__(name: str) -> Any: ...
else:
    sys.modules[__name__] = _target
