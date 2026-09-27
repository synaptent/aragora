"""Compatibility shim for the foundation-owned API error hierarchy."""

from __future__ import annotations

import warnings

warnings.warn(
    "aragora.server.errors is deprecated; import API errors from aragora.errors "
    "or aragora.api_errors instead.",
    DeprecationWarning,
    stacklevel=2,
)

from aragora.api_errors import *  # noqa: E402,F403
from aragora.api_errors import __all__  # noqa: E402,F401
