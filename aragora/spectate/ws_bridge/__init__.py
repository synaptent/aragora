"""Spectate WebSocket bridge (compatibility path).

The module lives in :mod:`aragora.events.spectate.ws_bridge`. This path
resolves to that same module object, so patching module state through either
path changes the one shared module.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.events.spectate import ws_bridge as _module

if not TYPE_CHECKING:
    sys.modules[__name__] = _module

if TYPE_CHECKING:
    from aragora.events.spectate.ws_bridge import SpectateEvent as SpectateEvent
    from aragora.events.spectate.ws_bridge import SpectateWebSocketBridge as SpectateWebSocketBridge
    from aragora.events.spectate.ws_bridge import (
        _extract_structured_details as _extract_structured_details,
    )
    from aragora.events.spectate.ws_bridge import bind_spectate_context as bind_spectate_context
    from aragora.events.spectate.ws_bridge import get_spectate_bridge as get_spectate_bridge
    from aragora.events.spectate.ws_bridge import get_spectate_context as get_spectate_context
    from aragora.events.spectate.ws_bridge import reset_spectate_bridge as reset_spectate_bridge
