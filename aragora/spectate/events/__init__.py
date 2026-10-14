"""Spectator event constants (compatibility path).

The module lives in :mod:`aragora.events.spectate.events`. This path
resolves to that same module object, so patching module state through either
path changes the one shared module.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.events.spectate import events as _module

if not TYPE_CHECKING:
    sys.modules[__name__] = _module

if TYPE_CHECKING:
    from aragora.events.spectate.events import EVENT_ASCII as EVENT_ASCII
    from aragora.events.spectate.events import EVENT_STYLES as EVENT_STYLES
    from aragora.events.spectate.events import SpectatorEvents as SpectatorEvents
