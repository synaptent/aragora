"""Deprecated import location for receipt signing primitives.

Receipt signing moved down to :mod:`aragora.storage.receipt_signing`. This
module aliases the relocated module for compatibility.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from typing import TYPE_CHECKING, Any

_target = importlib.import_module("aragora.storage.receipt_signing")

warnings.warn(
    "aragora.gauntlet.signing is deprecated; import from aragora.storage.receipt_signing instead.",
    DeprecationWarning,
    stacklevel=2,
)

if TYPE_CHECKING:

    def __getattr__(name: str) -> Any: ...
else:
    # Preserve the default signer and monkeypatch identity at the legacy path.
    sys.modules[__name__] = _target
