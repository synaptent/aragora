"""Epistemic CI and crux-engine helpers (DIC-13..22 + DIC-23..28 tranche).

Exposes:
- DIC-13: typed ExecutableClaim manifest model (:class:`ExecutableClaim`,
  :class:`ClaimManifest`, :func:`load_claims_from_dir`)
- DIC-14: executable claim verification (:class:`ClaimVerifier`)
- DIC-16: signed CruxReceipt for crux-finder debate runs
  (:class:`CruxEntry`, :class:`CruxReceipt`, :func:`build_crux_receipt`)
- DIC-17: follow-up-issue bridge for load-bearing cruxes and
  sharply-losing claims (:class:`FollowupProposal`,
  :func:`propose_followup_for_crux`, :func:`propose_followup_for_cruxset`,
  :func:`propose_followup_for_failed_claim`)
- DIC-18: organizational truth map report (:class:`OrgTruthMapReport`,
  :func:`build_truth_map`, :func:`build_truth_map_from_manifests`)
- DIC-20: epistemic decay monitor (:class:`DecaySignal`,
  :class:`DecayReason`, :func:`evaluate_unit`) plus world-state
  event translation (:class:`WorldStateEvent`, :class:`WorldEventKind`,
  :func:`claims_affected_by_event`, :func:`world_event_to_claim_results`,
  :func:`world_events_enabled`, :func:`enable_world_events`,
  :func:`reset_world_events`).
  Flag gate: ``ARAGORA_WORLD_EVENTS_ENABLED`` (default off).
- DIC-21: fail-closed quarantine policy (:class:`QuarantineDecision`,
  :class:`QuarantinePolicy`, :func:`apply_quarantine_policy`,
  :func:`quarantine_policy_enabled`)
- DIC-22: bounded repair-spec producer (:class:`RepairSpec`,
  :func:`propose_repair`, :func:`repair_pipeline_enabled`)
- DIC-25: adversarial world-state stress-test (:class:`StressPerturbation`,
  :class:`FragilityReport`, :class:`StressTestResult`,
  :func:`run_stress_test`, :func:`stress_test_enabled`)
  Flag gate: ``ARAGORA_STRESS_TEST_ENABLED`` (default off).
- DIC-19: proof-carrying code unit schema, scanner, and constraint graph
  (:class:`ProofCarryingCodeUnit`, :class:`DecayPolicy`,
  :class:`FallbackPolicy`, :func:`load_proof_unit`,
  :func:`load_proof_unit_from_yaml`, :func:`load_proof_units_from_dir`,
  :class:`ProofUnitConstraintGraph`)
  Flag gate: ``ARAGORA_PROOF_UNIT_SCAN_ENABLED`` (default off; dataclasses
  and graph construction are always importable; the scanner that populates
  the unit list is gated).
- DIC-23: dialectical runtime loop orchestrator (:class:`DialecticalEvent`,
  :class:`DialecticalRuntimeError`, :func:`run_dialectical_loop`,
  :func:`dialectical_runtime_enabled`)
  Flag gate: ``ARAGORA_DIALECTICAL_RUNTIME_ENABLED`` (default off).
- DIC-24: epistemic genealogy ledger — lineage view across decision, decay,
  crux, and repair (:class:`CodeUnitGenealogy`, :class:`GenealogyEntry`,
  :class:`GenealogyUnitSummary`, :class:`GenealogyReport`,
  :func:`get_genealogy`, :func:`build_genealogy_report`,
  :class:`InMemoryGenealogyStore`)
  Flag gate: ``ARAGORA_GENEALOGY_ENABLED`` (default off; data classes and
  store are always importable).
- DIC-26: belief coherence monitor (:class:`BeliefEntry`,
  :class:`CoherenceReport`, :func:`scan_coherence`)
- DIC-28: proactive crux gardening (:class:`GardeningConfig`,
  :class:`CruxGardeningResult`, :class:`GardeningReport`,
  :func:`run_gardening_pass`, :func:`crux_gardening_enabled`)
  Flag gate: ``ARAGORA_CRUX_GARDENING_ENABLED`` (default off).

See ``docs/plans/EPISTEMIC_CI_AND_CRUX_ENGINE.md`` for the full
DIC-13..22 + DIC-23..28 sequence and ``docs/status/NEXT_STEPS_CANONICAL.md``
for the queue-governance activation gate.
"""

from __future__ import annotations

import os

from .runtime_loop import (
    DialecticalEvent,
    DialecticalRuntimeError,
    dialectical_runtime_enabled,
    run_dialectical_loop,
)
from .arbitration import (
    PERSISTENT_CRUX_MIN_CONSECUTIVE,
    PERSISTENT_CRUX_MIN_SCORE,
    DEFAULT_EXPIRY_DAYS,
    ArbitrationSide,
    CruxArbitration,
    CruxArbitrationReversal,
    PersistentCrux,
    build_arbitration,
    build_reversal,
    crux_arbitration_enabled,
)
from .claim_verifier import ClaimResult, ClaimStatus, ClaimVerifier
from .coherence import (
    BeliefEntry,
    CoherenceIssue,
    CoherenceReport,
    IncoherenceKind,
    coherence_monitor_enabled,
    from_belief_node,
    scan_coherence,
)
from .crux_receipt import (
    CruxEntry,
    CruxReceipt,
    build_crux_receipt,
    crux_receipt_enabled,
    enable_crux_receipt,
)
from .gauntlet_crux_bridge import (
    from_gauntlet_receipt,
    ingest_gauntlet_receipt,
    km_crux_ingestion_enabled,
)
from .decay_monitor import (
    DecayReason,
    DecaySignal,
    compute_decay_impact_set,
    evaluate_unit,
)
from .world_event import (
    WorldEventKind,
    WorldStateEvent,
    claims_affected_by_event,
    enable_world_events,
    reset_world_events,
    world_event_to_claim_results,
    world_events_enabled,
)
from .executable_claim import (
    ClaimConfidence,
    ClaimEvidence,
    ClaimFailurePolicy,
    ClaimManifest,
    ClaimReceipt,
    ClaimVerification,
    ExecutableClaim,
    FailureAction,
    FailureSeverity,
    VerificationKind,
    load_claims_from_dir,
)
from .followup import (
    DEFAULT_CRUX_LOAD_BEARING_THRESHOLD,
    DEFAULT_DELTA_LOSS_THRESHOLD,
    FollowupProposal,
    propose_followup_for_crux,
    propose_followup_for_cruxset,
    propose_followup_for_failed_claim,
)
from .quarantine_policy import (
    QuarantineDecision,
    QuarantinePolicy,
    apply_quarantine_policy,
    quarantine_policy_enabled,
)
from .repair import (
    RepairSpec,
    enable_repair_pipeline,
    propose_repair,
    repair_pipeline_enabled,
)
from .stress_test import (
    FragilityReport,
    StressPerturbation,
    StressTestResult,
    run_stress_test,
    stress_test_enabled,
)
from .gardening import (
    CruxGardeningResult,
    GardeningConfig,
    GardeningReport,
    crux_gardening_enabled,
    garden_outstanding_crux,
    garden_resolved_crux,
    run_gardening_pass,
)
from .proof_unit import (
    DecayPolicy,
    FallbackPolicy,
    ProofCarryingCodeUnit,
    ProofUnitConstraintGraph,
    enable_proof_unit_scan,
    load_proof_unit,
    load_proof_unit_from_yaml,
    load_proof_units_from_dir,
    proof_unit_scan_enabled,
    reset_proof_unit_scan,
)
from .question_batteries import (
    BATTERY_NAMES,
    CORE_INTAKE_BATTERIES,
    QuestionBattery,
    build_intake_battery_questions,
    get_question_battery,
    iter_question_batteries,
    should_offer_intake_battery,
)
from .genealogy import (
    CodeUnitGenealogy,
    GenealogyEntry,
    GenealogyStore,
    InMemoryGenealogyStore,
    get_genealogy,
)
from .genealogy_report import (
    GenealogyReport,
    GenealogyUnitSummary,
    build_genealogy_report,
)
from .truth_map import (
    OrgTruthMapReport,
    build_truth_map,
    build_truth_map_from_manifests,
)

__all__ = [
    "DialecticalEvent",
    "DialecticalRuntimeError",
    "dialectical_runtime_enabled",
    "run_dialectical_loop",
    "ArbitrationSide",
    "BeliefEntry",
    "ClaimConfidence",
    "ClaimEvidence",
    "ClaimFailurePolicy",
    "ClaimManifest",
    "ClaimReceipt",
    "ClaimResult",
    "CruxGardeningResult",
    "ClaimStatus",
    "ClaimVerification",
    "ClaimVerifier",
    "ExecutableClaim",
    "FailureAction",
    "FailureSeverity",
    "VerificationKind",
    "BATTERY_NAMES",
    "CORE_INTAKE_BATTERIES",
    "QuestionBattery",
    "build_intake_battery_questions",
    "get_question_battery",
    "iter_question_batteries",
    "should_offer_intake_battery",
    "load_claims_from_dir",
    "CruxArbitration",
    "CruxArbitrationReversal",
    "DEFAULT_EXPIRY_DAYS",
    "PERSISTENT_CRUX_MIN_CONSECUTIVE",
    "PERSISTENT_CRUX_MIN_SCORE",
    "PersistentCrux",
    "build_arbitration",
    "build_reversal",
    "crux_arbitration_enabled",
    "CoherenceIssue",
    "CoherenceReport",
    "CruxEntry",
    "CruxReceipt",
    "DEFAULT_CRUX_LOAD_BEARING_THRESHOLD",
    "GardeningConfig",
    "GardeningReport",
    "DEFAULT_DELTA_LOSS_THRESHOLD",
    "DecayReason",
    "DecaySignal",
    "FollowupProposal",
    "FragilityReport",
    "OrgTruthMapReport",
    "QuarantineDecision",
    "QuarantinePolicy",
    "RepairSpec",
    "DecayPolicy",
    "FallbackPolicy",
    "ProofCarryingCodeUnit",
    "ProofUnitConstraintGraph",
    "StressPerturbation",
    "StressTestResult",
    "IncoherenceKind",
    "enable_proof_unit_scan",
    "load_proof_unit",
    "load_proof_unit_from_yaml",
    "load_proof_units_from_dir",
    "proof_unit_scan_enabled",
    "reset_proof_unit_scan",
    "apply_quarantine_policy",
    "build_crux_receipt",
    "crux_gardening_enabled",
    "garden_outstanding_crux",
    "garden_resolved_crux",
    "run_gardening_pass",
    "build_truth_map",
    "build_truth_map_from_manifests",
    "CodeUnitGenealogy",
    "GenealogyEntry",
    "GenealogyReport",
    "GenealogyStore",
    "GenealogyUnitSummary",
    "InMemoryGenealogyStore",
    "build_genealogy_report",
    "get_genealogy",
    "coherence_monitor_enabled",
    "crux_receipt_enabled",
    "enable_crux_receipt",
    "from_gauntlet_receipt",
    "ingest_gauntlet_receipt",
    "km_crux_ingestion_enabled",
    "enable_epistemic_followup",
    "enable_repair_pipeline",
    "epistemic_followup_enabled",
    "compute_decay_impact_set",
    "evaluate_unit",
    "WorldEventKind",
    "WorldStateEvent",
    "claims_affected_by_event",
    "enable_world_events",
    "reset_world_events",
    "world_event_to_claim_results",
    "world_events_enabled",
    "from_belief_node",
    "propose_followup_for_crux",
    "propose_followup_for_cruxset",
    "propose_followup_for_failed_claim",
    "propose_repair",
    "quarantine_policy_enabled",
    "repair_pipeline_enabled",
    "run_stress_test",
    "scan_coherence",
    "stress_test_enabled",
]


def epistemic_followup_enabled() -> bool:
    """Return True if callers should act on DIC-17 follow-up proposals.

    Reads ``ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED`` from the process
    environment. Default is False; construction of proposals is
    always safe, but filing them on GitHub must be gated.
    """
    raw = str(os.environ.get("ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def enable_epistemic_followup() -> None:
    """Enable the DIC-17 follow-up bridge for the current process."""
    os.environ["ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED"] = "1"
