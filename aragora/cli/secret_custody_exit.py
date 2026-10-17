"""Exit handling for unusable secret custody, shared by the ``aragora`` CLI and
``python -m aragora.server``.

Graceful degradation does not cover unusable custody: it stays fatal, but the
process exits with one value-free stderr line instead of a traceback.
"""

from __future__ import annotations

import sys
from collections.abc import Callable


def secret_custody_failure_line(exc: BaseException) -> str | None:
    """The one-line custody report for ``exc``, or ``None`` when it is unrelated."""
    # A SecretSourceError can only exist once its module is loaded; checking first
    # keeps unrelated failures from importing the secrets stack while unwinding.
    if "aragora.config.secrets" not in sys.modules:
        return None
    from aragora.config.secrets import format_secret_custody_failure

    return format_secret_custody_failure(exc)


def run_reporting_unusable_secret_custody(entry: Callable[[], int | None]) -> int:
    """Run an entry point and return its exit code (``None`` counts as 0).

    Unusable secret custody, raised directly or explicitly chained under another
    error, prints one line and returns 1. Every other exception propagates.
    """
    try:
        return entry() or 0
    except Exception as exc:
        line = secret_custody_failure_line(exc)
        if line is None:
            raise
        print(line, file=sys.stderr)
        return 1
