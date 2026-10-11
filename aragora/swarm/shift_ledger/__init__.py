"""Compatibility re-export of :mod:`aragora.evaluation.shift_ledger`.

The ledger is stdlib-only and is read by evaluation metrics, so it lives in the
evaluation package; every name below is the identical object.
"""

from __future__ import annotations

from aragora.evaluation.shift_ledger import (
    DEFAULT_LEDGER_PATH,
    FAILURE_THRESHOLDS,
    GREEN_SHIFT_REQUIRED_HOURS,
    HEALTHY_STOP_PREFIXES,
    LedgerEntry,
    ShiftLedger,
)

__all__ = [
    "DEFAULT_LEDGER_PATH",
    "FAILURE_THRESHOLDS",
    "GREEN_SHIFT_REQUIRED_HOURS",
    "HEALTHY_STOP_PREFIXES",
    "LedgerEntry",
    "ShiftLedger",
]
