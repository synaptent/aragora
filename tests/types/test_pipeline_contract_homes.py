"""Pipeline contracts the debate engine reads live in ``aragora.types``.

``aragora.debate`` (domain layer) reads the execution mode, the backbone run-ledger contracts and
the decision plan enums without importing ``aragora.pipeline`` (application layer). The old
pipeline module paths resolve to the same module objects, and the pipeline modules that defined
the enums re-export the same classes.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MOVED_MODULES = [
    ("aragora.pipeline.execution_mode", "aragora.types.execution_mode"),
    ("aragora.pipeline.backbone_contracts", "aragora.types.backbone_contracts"),
]
MOVED_ENUMS = [
    ("aragora.pipeline.decision_plan.core", "ApprovalMode"),
    ("aragora.pipeline.decision_plan.core", "PlanStatus"),
    ("aragora.pipeline.decision_plan", "ApprovalMode"),
    ("aragora.pipeline.decision_plan", "PlanStatus"),
    ("aragora.pipeline", "ApprovalMode"),
    ("aragora.pipeline", "PlanStatus"),
    ("aragora.pipeline.risk_register", "RiskLevel"),
]
OLD_PATHS = {
    "aragora.pipeline.execution_mode",
    "aragora.pipeline.backbone_contracts",
    "aragora.pipeline.decision_plan.core",
    "aragora.pipeline.risk_register",
}


@pytest.mark.parametrize(("old", "new"), MOVED_MODULES)
def test_the_old_module_path_is_the_types_module(old, new):
    assert importlib.import_module(old) is importlib.import_module(new)


@pytest.mark.parametrize(
    ("old", "new", "name"),
    [
        (*MOVED_MODULES[0], "resolve_safety_mode"),
        (*MOVED_MODULES[1], "RunLedger"),
    ],
)
def test_a_patch_through_the_old_path_is_seen_through_the_new_one(monkeypatch, old, new, name):
    replacement = object()
    monkeypatch.setattr(f"{old}.{name}", replacement)
    assert getattr(importlib.import_module(new), name) is replacement


def test_the_safety_mode_resolves_the_same_through_both_paths():
    from aragora.pipeline.execution_mode import ExecutionMode as OldMode
    from aragora.pipeline.execution_mode import resolve_safety_mode as old_resolve
    from aragora.types.execution_mode import ExecutionMode, resolve_safety_mode

    signed_in = SimpleNamespace(is_authenticated=True, user_id="u1")
    for resolve in (old_resolve, resolve_safety_mode):
        assert resolve("interactive") is ExecutionMode.INTERACTIVE
        assert resolve(None) is ExecutionMode.AUTONOMOUS
        assert resolve(None, auth_context=signed_in) is OldMode.INTERACTIVE
    assert ExecutionMode.__module__ == "aragora.types.execution_mode"


def test_a_run_ledger_built_at_the_old_path_round_trips_at_the_new_one():
    from aragora.pipeline.backbone_contracts import IntakeBundle as OldIntake
    from aragora.pipeline.backbone_contracts import RunLedger as OldLedger
    from aragora.types.backbone_contracts import RunLedger, propagate_taint

    ledger = OldLedger(
        run_id="run-1",
        entrypoint="post_debate_coordinator.run",
        intake_bundle=OldIntake(source_kind="debate", raw_intent="ship", taint_flags=["t1"]),
    )
    restored = RunLedger.from_dict(ledger.to_dict())
    assert isinstance(restored, OldLedger)
    assert restored.to_dict() == ledger.to_dict()
    assert propagate_taint(["a", " b"], ["b", "c"]) == ["a", "b", "c"]
    assert RunLedger.__module__ == "aragora.types.backbone_contracts"


@pytest.mark.parametrize(("old_path", "name"), MOVED_ENUMS)
def test_the_pipeline_paths_hold_the_same_enum(old_path, name):
    import aragora.types.decision_plans as decision_plans

    assert getattr(importlib.import_module(old_path), name) is getattr(decision_plans, name)


def test_the_enum_members_are_unchanged():
    from aragora.types.decision_plans import ApprovalMode, PlanStatus, RiskLevel

    assert [member.value for member in ApprovalMode] == [
        "always",
        "risk_based",
        "confidence_based",
        "never",
    ]
    assert [member.value for member in PlanStatus] == [
        "created",
        "awaiting_approval",
        "approved",
        "rejected",
        "executing",
        "verifying",
        "completed",
        "failed",
        "rolled_back",
    ]
    assert [member.value for member in RiskLevel] == ["low", "medium", "high", "critical"]


def test_a_decision_plan_defaults_to_the_types_enums():
    from aragora.pipeline.decision_plan.core import DecisionPlan
    from aragora.types.decision_plans import ApprovalMode, PlanStatus, RiskLevel

    plan = DecisionPlan(debate_id="d1", task="t")
    assert plan.status is PlanStatus.CREATED
    assert plan.approval_mode is ApprovalMode.RISK_BASED
    assert plan.max_auto_risk is RiskLevel.LOW


def _imported_modules(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


@pytest.mark.parametrize("module", ["execution_mode", "backbone_contracts", "decision_plans"])
def test_the_types_module_imports_nothing_from_aragora(module):
    path = REPO_ROOT / "aragora" / "types" / f"{module}.py"
    assert [name for _, name in _imported_modules(path) if name.startswith("aragora")] == []


def test_debate_reads_the_moved_contracts_from_the_types_package():
    offenders = [
        f"{path.relative_to(REPO_ROOT)}:{line}: {name}"
        for path in sorted((REPO_ROOT / "aragora" / "debate").rglob("*.py"))
        for line, name in _imported_modules(path)
        if name in OLD_PATHS
    ]
    assert offenders == []
