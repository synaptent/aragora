"""Spectator stream (compatibility path).

The module lives in :mod:`aragora.events.spectate.stream`. This path
resolves to that same module object, so patching module state through either
path changes the one shared module.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.events.spectate import stream as _module

if not TYPE_CHECKING:
    sys.modules[__name__] = _module

if TYPE_CHECKING:
    from aragora.events.spectate.stream import VALID_EVENT_TYPES as VALID_EVENT_TYPES
    from aragora.events.spectate.stream import SpectatorStream as SpectatorStream
