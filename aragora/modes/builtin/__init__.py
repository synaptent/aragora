"""
Built-in operational modes.

These modes provide standard operational patterns:
- Architect: High-level design and planning (read-only)
- Coder: Implementation and development
- Reviewer: Code review and quality analysis
- Debugger: Investigation and bug fixing
- Orchestrator: Coordination of other modes
"""

from aragora.modes.builtin.architect import ArchitectMode
from aragora.modes.builtin.coder import CoderMode
from aragora.modes.builtin.debugger import DebuggerMode
from aragora.modes.builtin.epistemic_hygiene import EpistemicHygieneMode
from aragora.modes.builtin.orchestrator import OrchestratorMode
from aragora.modes.builtin.question_personas import (
    AssumptionSurfacerMode,
    DeleterMode,
    FalsifierMode,
    OutsiderMode,
    QuestionPersonaMode,
)
from aragora.modes.builtin.reviewer import ReviewerMode

__all__ = [
    "ArchitectMode",
    "CoderMode",
    "ReviewerMode",
    "DebuggerMode",
    "OrchestratorMode",
    "EpistemicHygieneMode",
    "QuestionPersonaMode",
    "OutsiderMode",
    "FalsifierMode",
    "DeleterMode",
    "AssumptionSurfacerMode",
]


def register_all_builtins() -> None:
    """
    Ensure all built-in modes are registered.

    Called automatically when the module is imported, but can be
    called explicitly to re-register after a clear.
    """
    # Instantiate each mode to trigger registration
    ArchitectMode()
    CoderMode()
    ReviewerMode()
    DebuggerMode()
    OrchestratorMode()
    EpistemicHygieneMode()
    OutsiderMode()
    FalsifierMode()
    DeleterMode()
    AssumptionSurfacerMode()


# Auto-register on import
register_all_builtins()
