"""
Aragora Mode System.

Provides two complementary mode systems:

1. **Operational Modes** (Kilocode-inspired)
   - Architect, Coder, Reviewer, Debugger, Orchestrator
   - Granular tool access control via ToolGroups
   - Custom mode creation via YAML

2. **Debate Modes**
   - Adversarial red-teaming
   - Specialized debate protocols

Heavy submodules (deep_audit, redteam, prober) are lazily imported to avoid
pulling in scipy/numpy on every CLI invocation (~13s savings).
"""

# Lightweight imports — these are fast and commonly needed
from aragora.modes import custom  # Expose submodule for patching
from aragora.modes.base import Mode, ModeRegistry
from aragora.modes.builtin import (
    ArchitectMode,
    AssumptionSurfacerMode,
    CoderMode,
    DebuggerMode,
    DeleterMode,
    EpistemicHygieneMode,
    FalsifierMode,
    OrchestratorMode,
    OutsiderMode,
    QuestionPersonaMode,
    ReviewerMode,
    register_all_builtins,
)
from aragora.modes.custom import CustomMode, CustomModeLoader
from aragora.modes.handoff import HandoffContext, ModeHandoff
from aragora.modes.tool_groups import ToolGroup, can_use_tool, get_required_group

# --- Lazy imports for heavy submodules ---
# deep_audit, redteam, and prober import aragora.debate.orchestrator which
# transitively loads scipy/numpy (~13s). Defer until actually accessed.

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    # Deep Audit Mode
    "CODE_ARCHITECTURE_AUDIT": ("aragora.modes.deep_audit", "CODE_ARCHITECTURE_AUDIT"),
    "CONTRACT_AUDIT": ("aragora.modes.deep_audit", "CONTRACT_AUDIT"),
    "STRATEGY_AUDIT": ("aragora.modes.deep_audit", "STRATEGY_AUDIT"),
    "AuditFinding": ("aragora.modes.deep_audit", "AuditFinding"),
    "DeepAuditConfig": ("aragora.modes.deep_audit", "DeepAuditConfig"),
    "DeepAuditOrchestrator": ("aragora.modes.deep_audit", "DeepAuditOrchestrator"),
    "DeepAuditVerdict": ("aragora.modes.deep_audit", "DeepAuditVerdict"),
    "run_deep_audit": ("aragora.modes.deep_audit", "run_deep_audit"),
    # Capability Probing
    "CapabilityProber": ("aragora.modes.prober", "CapabilityProber"),
    "ContradictionTrap": ("aragora.modes.prober", "ContradictionTrap"),
    "HallucinationBait": ("aragora.modes.prober", "HallucinationBait"),
    "PersistenceChallenge": ("aragora.modes.prober", "PersistenceChallenge"),
    "ProbeBeforePromote": ("aragora.modes.prober", "ProbeBeforePromote"),
    "ProbeResult": ("aragora.modes.prober", "ProbeResult"),
    "ProbeStrategy": ("aragora.modes.prober", "ProbeStrategy"),
    "ProbeType": ("aragora.modes.prober", "ProbeType"),
    "SycophancyTest": ("aragora.modes.prober", "SycophancyTest"),
    "VulnerabilityReport": ("aragora.modes.prober", "VulnerabilityReport"),
    "VulnerabilitySeverity": ("aragora.modes.prober", "VulnerabilitySeverity"),
    "generate_probe_report_markdown": ("aragora.modes.prober", "generate_probe_report_markdown"),
    # Red Team Mode
    "Attack": ("aragora.modes.redteam", "Attack"),
    "AttackType": ("aragora.modes.redteam", "AttackType"),
    "Defense": ("aragora.modes.redteam", "Defense"),
    "RedTeamMode": ("aragora.modes.redteam", "RedTeamMode"),
    "RedTeamProtocol": ("aragora.modes.redteam", "RedTeamProtocol"),
    "RedTeamResult": ("aragora.modes.redteam", "RedTeamResult"),
    "RedTeamRound": ("aragora.modes.redteam", "RedTeamRound"),
    "redteam_code_review": ("aragora.modes.redteam", "redteam_code_review"),
    "redteam_policy": ("aragora.modes.redteam", "redteam_policy"),
}


def __getattr__(name: str):
    if name in _LAZY_IMPORTS:
        module_path, attr_name = _LAZY_IMPORTS[name]
        import importlib

        mod = importlib.import_module(module_path)
        val = getattr(mod, attr_name)
        # Cache on the module so __getattr__ isn't called again
        globals()[name] = val
        return val
    raise AttributeError(f"module 'aragora.modes' has no attribute {name!r}")


def load_builtins() -> None:
    """Ensure all built-in modes are registered in the ModeRegistry.

    This is safe to call multiple times (idempotent). Import of the
    builtin subpackage triggers registration via ``register_all_builtins()``.
    Call this explicitly before looking up modes by name to guarantee
    all built-in operational and epistemic-question modes are available.
    """
    register_all_builtins()


__all__ = [
    # Operational Mode System
    "load_builtins",
    "custom",
    "ToolGroup",
    "can_use_tool",
    "get_required_group",
    "Mode",
    "ModeRegistry",
    "HandoffContext",
    "ModeHandoff",
    "CustomMode",
    "CustomModeLoader",
    # Built-in Modes
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
    "register_all_builtins",
    # Debate Modes (lazy)
    "RedTeamMode",
    "RedTeamProtocol",
    "RedTeamResult",
    "RedTeamRound",
    "Attack",
    "Defense",
    "AttackType",
    "redteam_code_review",
    "redteam_policy",
    # Capability Probing (lazy)
    "CapabilityProber",
    "VulnerabilityReport",
    "ProbeResult",
    "ProbeType",
    "ProbeStrategy",
    "ContradictionTrap",
    "HallucinationBait",
    "SycophancyTest",
    "PersistenceChallenge",
    "VulnerabilitySeverity",
    "ProbeBeforePromote",
    "generate_probe_report_markdown",
    # Deep Audit Mode (lazy)
    "DeepAuditOrchestrator",
    "DeepAuditConfig",
    "DeepAuditVerdict",
    "AuditFinding",
    "run_deep_audit",
    "STRATEGY_AUDIT",
    "CONTRACT_AUDIT",
    "CODE_ARCHITECTURE_AUDIT",
]
