"""Compatibility re-export of :mod:`aragora.debate.triage_diagnostics`.

Triage diagnostics moved into the debate package, which records into them and
sits below ``aragora.inbox``. Every name below is the identical object, so a
run activated through either path is the active run for both.
"""

from __future__ import annotations

from aragora.debate.triage_diagnostics import (
    DiagnosticSeverity,
    TriageDiagnosticEvent,
    TriageRunDiagnostics,
    get_active_triage_diagnostics,
    record_triage_diagnostic,
    triage_diagnostics_should_mirror_logs,
)

__all__ = [
    "DiagnosticSeverity",
    "TriageDiagnosticEvent",
    "TriageRunDiagnostics",
    "get_active_triage_diagnostics",
    "record_triage_diagnostic",
    "triage_diagnostics_should_mirror_logs",
]
