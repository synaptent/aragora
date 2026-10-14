"""Spectator payload redaction (compatibility path).

The module lives in :mod:`aragora.events.spectate.redaction`. This path
resolves to that same module object, so patching module state through either
path changes the one shared module.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.events.spectate import redaction as _module

if not TYPE_CHECKING:
    sys.modules[__name__] = _module

if TYPE_CHECKING:
    from aragora.events.spectate.redaction import (
        redact_spectator_payload as redact_spectator_payload,
    )
    from aragora.events.spectate.redaction import redact_spectator_text as redact_spectator_text
