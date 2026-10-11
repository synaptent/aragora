"""
Gauntlet - Adversarial Validation Engine.

Stress-tests high-stakes decisions through multi-agent adversarial debate.

The Gauntlet orchestrates:
- Red Team attacks (logical, security, scalability)
- Capability probing (hallucination, sycophancy, consistency)
- Scenario matrix testing (scale, risk, time horizon)
- Risk aggregation and Decision Receipts

Two orchestration options:
1. GauntletRunner - Simple 3-phase runner with templates (recommended)
2. GauntletOrchestrator - Full 5-phase orchestrator with deep audit

Usage (Runner - recommended):
    from aragora.gauntlet import GauntletRunner, GauntletConfig

    config = GauntletConfig(
        attack_categories=[AttackCategory.SECURITY, AttackCategory.COMPLIANCE],
        agents=["anthropic-api", "openai-api", "gemini"],
    )
    runner = GauntletRunner(config)
    result = await runner.run("spec.md content here")
    receipt = result.to_receipt()

Usage (Orchestrator - full 5-phase):
    from aragora.gauntlet import GauntletOrchestrator, OrchestratorConfig

    config = OrchestratorConfig(input_content="spec.md content")
    orchestrator = GauntletOrchestrator(agents)
    result = await orchestrator.run(config)
"""

# Shared types (canonical source)
# Config and categories
from .config import AttackCategory, GauntletConfig, ProbeCategory
from .heatmap import HeatmapCell, RiskHeatmap

# Output formats
from .receipt import DecisionReceipt

# Result types
from .result import GauntletResult, Vulnerability
from .result import RiskSummary as ResultRiskSummary  # noqa: F401 - Alias for backward compat

# Runner
from .runner import GauntletRunner
from .types import (
    BaseFinding,
    GauntletPhase,
    GauntletSeverity,
    InputType,
    RiskSummary,
    SeverityLevel,
    Verdict,
)


# Re-export orchestrator classes (full 5-phase implementation)
# NOTE: Import is deferred to avoid circular imports at import time
def _get_orchestrator_classes():
    """Lazy import of orchestrator classes."""
    from aragora.gauntlet.orchestrator import (
        AI_ACT_GAUNTLET,
        CODE_REVIEW_GAUNTLET,
        GDPR_GAUNTLET,
        HIPAA_GAUNTLET,
        POLICY_GAUNTLET,
        QUICK_GAUNTLET,
        SECURITY_GAUNTLET,
        SOX_GAUNTLET,
        THOROUGH_GAUNTLET,
        Finding,
        VerifiedClaim,
        get_compliance_gauntlet,
        run_gauntlet,
    )
    from aragora.gauntlet.orchestrator import (
        GauntletConfig as _OrchestratorConfig,
    )
    from aragora.gauntlet.orchestrator import (
        GauntletOrchestrator as _Orchestrator,
    )
    from aragora.gauntlet.orchestrator import (
        GauntletProgress as _Progress,
    )
    from aragora.gauntlet.orchestrator import (
        GauntletResult as _OrchestratorResult,
    )

    return {
        "GauntletOrchestrator": _Orchestrator,
        "OrchestratorConfig": _OrchestratorConfig,
        "GauntletProgress": _Progress,
        "OrchestratorResult": _OrchestratorResult,
        "Finding": Finding,
        "VerifiedClaim": VerifiedClaim,
        "run_gauntlet": run_gauntlet,
        "get_compliance_gauntlet": get_compliance_gauntlet,
        "QUICK_GAUNTLET": QUICK_GAUNTLET,
        "THOROUGH_GAUNTLET": THOROUGH_GAUNTLET,
        "CODE_REVIEW_GAUNTLET": CODE_REVIEW_GAUNTLET,
        "POLICY_GAUNTLET": POLICY_GAUNTLET,
        "GDPR_GAUNTLET": GDPR_GAUNTLET,
        "HIPAA_GAUNTLET": HIPAA_GAUNTLET,
        "AI_ACT_GAUNTLET": AI_ACT_GAUNTLET,
        "SECURITY_GAUNTLET": SECURITY_GAUNTLET,
        "SOX_GAUNTLET": SOX_GAUNTLET,
    }


# Lazy attribute access for orchestrator classes
def __getattr__(name: str):
    """Lazy loading for orchestrator classes."""
    orchestrator_names = {
        "GauntletOrchestrator",
        "OrchestratorConfig",
        "GauntletProgress",
        "OrchestratorResult",
        "Finding",
        "VerifiedClaim",
        "run_gauntlet",
        "get_compliance_gauntlet",
        "QUICK_GAUNTLET",
        "THOROUGH_GAUNTLET",
        "CODE_REVIEW_GAUNTLET",
        "POLICY_GAUNTLET",
        "GDPR_GAUNTLET",
        "HIPAA_GAUNTLET",
        "AI_ACT_GAUNTLET",
        "SECURITY_GAUNTLET",
        "SOX_GAUNTLET",
    }
    if name in orchestrator_names:
        classes = _get_orchestrator_classes()
        return classes[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Shared types (canonical)
    "InputType",
    "Verdict",
    "SeverityLevel",
    "GauntletSeverity",
    "GauntletPhase",
    "BaseFinding",
    "RiskSummary",
    "ResultRiskSummary",
    # Config (Runner)
    "GauntletConfig",
    "AttackCategory",
    "ProbeCategory",
    # Result (Runner)
    "GauntletResult",
    "Vulnerability",
    # Runner
    "GauntletRunner",
    # Receipt
    "DecisionReceipt",
    # Heatmap
    "RiskHeatmap",
    "HeatmapCell",
    # Stable API (v1)
    "api",
    # Orchestrator (full 5-phase) - lazy loaded
    "GauntletOrchestrator",
    "OrchestratorConfig",
    "GauntletProgress",
    "OrchestratorResult",
    "Finding",
    "VerifiedClaim",
    "run_gauntlet",
    "get_compliance_gauntlet",
    "QUICK_GAUNTLET",
    "THOROUGH_GAUNTLET",
    "CODE_REVIEW_GAUNTLET",
    "POLICY_GAUNTLET",
    # Compliance presets - lazy loaded
    "GDPR_GAUNTLET",
    "HIPAA_GAUNTLET",
    "AI_ACT_GAUNTLET",
    "SECURITY_GAUNTLET",
    "SOX_GAUNTLET",
]


# Import stable API module
from aragora.gauntlet import api

# The core decision router routes gauntlet decisions through this registration.
from aragora.gauntlet.decision_route import register_decision_route as _register_decision_route

_register_decision_route()
