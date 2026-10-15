"""Pin the split of ledger and Knowledge Mound writes out of ``PostDebateCoordinator``.

The RunLedger (backbone) mirroring helpers and the receipt/outcome Knowledge Mound
payload and writeback helpers live on ``PostDebatePersistenceMixin`` in
``aragora.debate.post_debate_persistence``. ``PostDebateCoordinator`` inherits them,
so ``coordinator._record_backbone_plan(...)`` and ``patch.object(PostDebateCoordinator,
...)`` keep working. The pipeline steps and ``_seed_backbone_run`` (keyed by path in
``tests/pipeline/backbone_entrypoints_inventory.py``) stay on the coordinator.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aragora.debate import post_debate_coordinator as coordinator_module
from aragora.debate import post_debate_persistence as persistence_module
from aragora.debate.post_debate_coordinator import PostDebateCoordinator
from aragora.debate.post_debate_persistence import PostDebatePersistenceMixin

MOVED_METHODS = [
    "_backbone_required",
    "_backbone_failure",
    "_ensure_backbone_write",
    "_get_backbone_runtime",
    "_plan_object",
    "_plan_id",
    "_current_run_id",
    "_record_backbone_plan",
    "_record_backbone_receipt",
    "_record_backbone_execution",
    "_debate_consensus_reached",
    "_debate_final_answer",
    "_task_slug",
    "_build_receipt_km_payload",
    "_build_outcome_km_payload",
    "_persist_receipt_summary_to_km",
    "_persist_outcome_summary_to_km",
]


def test_coordinator_inherits_persistence_mixin() -> None:
    assert issubclass(PostDebateCoordinator, PostDebatePersistenceMixin)
    assert coordinator_module.PostDebatePersistenceMixin is PostDebatePersistenceMixin


@pytest.mark.parametrize("name", MOVED_METHODS)
def test_moved_method_is_defined_once_on_the_mixin(name: str) -> None:
    assert name in PostDebatePersistenceMixin.__dict__
    assert name not in PostDebateCoordinator.__dict__
    assert getattr(PostDebateCoordinator, name) is getattr(PostDebatePersistenceMixin, name)


def test_pipeline_steps_stay_on_the_coordinator() -> None:
    for name in (
        "run",
        "_step_persist_receipt",
        "_step_persist_signed_receipt",
        "_seed_backbone_run",
    ):
        assert name in PostDebateCoordinator.__dict__
        assert name not in PostDebatePersistenceMixin.__dict__


def test_coordinator_module_is_under_the_size_limit() -> None:
    path = Path(coordinator_module.__file__)
    assert len(path.read_bytes().splitlines()) < 2000


def test_moved_methods_log_under_the_coordinator_logger_name() -> None:
    assert persistence_module.logger.name == "aragora.debate.post_debate_coordinator"


def test_seed_backbone_run_reuses_existing_run_id() -> None:
    coordinator = PostDebateCoordinator()
    coordinator._backbone_runtime = SimpleNamespace()
    debate_result = SimpleNamespace(metadata={"backbone_run_id": "run-existing"})

    run_id = coordinator._seed_backbone_run("debate-1", debate_result, "task")

    assert run_id == "run-existing"
    assert debate_result.metadata["backbone_entrypoint"] == "post_debate_coordinator.run"


def test_backbone_failure_logs_instead_of_raising_when_not_required(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator = PostDebateCoordinator()
    with caplog.at_level(logging.WARNING, logger="aragora.debate.post_debate_coordinator"):
        coordinator._backbone_failure("ledger unavailable")
    assert "ledger unavailable" in caplog.text


def test_outcome_payload_uses_consensus_and_task_slug() -> None:
    coordinator = PostDebateCoordinator()
    debate_result: Any = SimpleNamespace(
        consensus_reached=True,
        final_answer="Use a token bucket",
        dissenting_views=[],
        debate_cruxes=[],
    )

    payload = coordinator._build_outcome_km_payload(
        debate_id="d-1",
        debate_result=debate_result,
        task="Design a rate limiter",
        confidence=0.8,
    )

    assert payload["outcome_id"] == "outcome-d-1-design-a-rate-limiter"
    assert payload["outcome_type"] == "success"
    assert payload["impact_score"] == 0.8
