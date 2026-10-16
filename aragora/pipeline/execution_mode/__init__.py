"""Execution mode (compatibility path).

The module lives in :mod:`aragora.types.execution_mode`. This path resolves to that same
module object, so the enum and any patch applied through either path stay in step.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from aragora.types import execution_mode as _module

if not TYPE_CHECKING:
    sys.modules[__name__] = _module

if TYPE_CHECKING:
    from aragora.types.execution_mode import ExecutionMode as ExecutionMode
    from aragora.types.execution_mode import (
        SupportsInteractiveAuthContext as SupportsInteractiveAuthContext,
    )
    from aragora.types.execution_mode import (
        _has_interactive_auth_context as _has_interactive_auth_context,
    )
    from aragora.types.execution_mode import resolve_safety_mode as resolve_safety_mode
