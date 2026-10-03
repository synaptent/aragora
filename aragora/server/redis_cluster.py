"""Deprecated import location for the Redis cluster client.

The cluster client moved down to :mod:`aragora.storage.redis_cluster` so
infrastructure code can use it without importing ``aragora.server``.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from typing import TYPE_CHECKING, Any

_target = importlib.import_module("aragora.storage.redis_cluster")

warnings.warn(
    "aragora.server.redis_cluster is deprecated; import from "
    "aragora.storage.redis_cluster instead.",
    DeprecationWarning,
    stacklevel=2,
)

if TYPE_CHECKING:

    def __getattr__(name: str) -> Any: ...
else:
    # Preserve singleton state and monkeypatch identity at the legacy path.
    sys.modules[__name__] = _target
