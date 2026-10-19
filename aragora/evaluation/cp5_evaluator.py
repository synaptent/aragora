"""CP-5 "productivity-positive" checkpoint evaluator (AGT-06 / #6067).

Joins the rolling VIAH trend from :mod:`aragora.evaluation.viah` to the CP-5
capability checkpoint in :mod:`aragora.evaluation.capability_checkpoint`.
``docs/plans/AGENT_CIVILIZATION_SUBSTRATE.md`` §5 states the CP-5 pass
condition as:

    VIAH trends positive over rolling 4-week window without operator rescue spike

This module turns that sentence into a deterministic, inspectable verdict:

- ``trend_direction == "positive"`` is required for PASS;
- a *rescue spike* is any scored week whose ``rescues_required`` exceeds
  ``rescue_spike_threshold``; any spike week fails the checkpoint;
- fewer scored weeks than ``min_scored_weeks`` yields PENDING rather than a
  verdict, so a half-empty window can never pass or fail CP-5.

Flag: ``ARAGORA_CAPABILITY_CHECKPOINTS_ENABLED`` (shared with the registry;
default off). The trend input is itself gated by ``ARAGORA_VIAH_TREND_ENABLED``.
Nothing here touches the live queue, dispatch, or the boss loop: the evaluator
is a pure function over an already-computed :class:`ViahTrend`, and the only
side effect, :func:`record_cp5`, appends to an in-memory registry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aragora.evaluation.capability_checkpoint import (
    CheckpointCode,
    CheckpointRecord,
    CheckpointRegistry,
    CheckpointRegistryError,
    CheckpointStatus,
    capability_checkpoints_enabled,
)
from aragora.evaluation.viah import ViahTrend

DEFAULT_RESCUE_SPIKE_THRESHOLD = 3
"""Per-week ``rescues_required`` strictly above this value counts as a spike."""

CP5_EVALUATOR_NAME = "cp5_evaluator"


def _require_enabled() -> None:
    if not capability_checkpoints_enabled():
        raise CheckpointRegistryError(
            "CP-5 evaluation is disabled; set ARAGORA_CAPABILITY_CHECKPOINTS_ENABLED=1 to enable"
        )


def rescue_spike_weeks(
    trend: ViahTrend, *, threshold: int = DEFAULT_RESCUE_SPIKE_THRESHOLD
) -> list[int]:
    """Return ``week_index`` values whose rescues exceed ``threshold``.

    Only scored weeks (``viah is not None``) are considered: a week with no
    agent-hours cannot have required operator rescues of autonomous work.
    """
    if threshold < 0:
        raise ValueError("threshold must be >= 0")
    return [
        p.week_index for p in trend.points if p.viah is not None and p.rescues_required > threshold
    ]


@dataclass(frozen=True)
class Cp5Evaluation:
    """Verdict for CP-5 derived from a :class:`ViahTrend`."""

    status: CheckpointStatus
    trend_direction: str
    weeks_requested: int
    scored_weeks: int
    min_scored_weeks: int
    rescue_spike_threshold: int
    spike_weeks: tuple[int, ...]
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "trend_direction": self.trend_direction,
            "weeks_requested": self.weeks_requested,
            "scored_weeks": self.scored_weeks,
            "min_scored_weeks": self.min_scored_weeks,
            "rescue_spike_threshold": self.rescue_spike_threshold,
            "spike_weeks": list(self.spike_weeks),
            "notes": self.notes,
        }

    def to_record(self, *, evaluator: str = CP5_EVALUATOR_NAME) -> CheckpointRecord:
        """Build a :class:`CheckpointRecord` carrying this evaluation as evidence."""
        return CheckpointRecord.create(
            checkpoint_code=CheckpointCode.CP5,
            status=self.status,
            evaluator=evaluator,
            evidence=self.to_dict(),
            notes=self.notes,
        )


def evaluate_cp5(
    trend: ViahTrend,
    *,
    rescue_spike_threshold: int = DEFAULT_RESCUE_SPIKE_THRESHOLD,
    min_scored_weeks: int | None = None,
) -> Cp5Evaluation:
    """Evaluate CP-5 from a rolling VIAH trend.

    ``min_scored_weeks`` defaults to ``trend.weeks_requested`` so every week in
    the window must carry a score before a verdict is issued. Pass a smaller
    value to tolerate weeks with zero agent-hours.

    Raises :class:`CheckpointRegistryError` when the capability-checkpoint
    flag is off, and ``ValueError`` on nonsensical thresholds.
    """
    _require_enabled()
    if rescue_spike_threshold < 0:
        raise ValueError("rescue_spike_threshold must be >= 0")
    required = trend.weeks_requested if min_scored_weeks is None else min_scored_weeks
    if required < 1 or required > trend.weeks_requested:
        raise ValueError("min_scored_weeks must be in [1, trend.weeks_requested]")

    scored = sum(1 for p in trend.points if p.viah is not None)
    spikes = tuple(rescue_spike_weeks(trend, threshold=rescue_spike_threshold))
    direction = trend.trend_direction

    if direction == "insufficient_data" or scored < required:
        status = CheckpointStatus.PENDING
        notes = f"insufficient data: {scored}/{required} scored weeks (direction={direction})"
    elif direction == "positive" and not spikes:
        status = CheckpointStatus.PASS
        notes = f"VIAH trend positive over {scored} scored weeks with no rescue spike"
    else:
        status = CheckpointStatus.FAIL
        reasons: list[str] = []
        if direction != "positive":
            reasons.append(f"trend direction is {direction!r}, not 'positive'")
        if spikes:
            reasons.append(
                f"rescue spike in week(s) {list(spikes)} (> {rescue_spike_threshold} rescues/week)"
            )
        notes = "; ".join(reasons)

    return Cp5Evaluation(
        status=status,
        trend_direction=direction,
        weeks_requested=trend.weeks_requested,
        scored_weeks=scored,
        min_scored_weeks=required,
        rescue_spike_threshold=rescue_spike_threshold,
        spike_weeks=spikes,
        notes=notes,
    )


def record_cp5(
    registry: CheckpointRegistry,
    trend: ViahTrend,
    *,
    rescue_spike_threshold: int = DEFAULT_RESCUE_SPIKE_THRESHOLD,
    min_scored_weeks: int | None = None,
    evaluator: str = CP5_EVALUATOR_NAME,
) -> CheckpointRecord:
    """Evaluate CP-5 and append the result to ``registry``.

    Honours the checkpoint's declared dependency: when CP-5 ``depends_on`` a
    checkpoint that has not passed, a SKIPPED record is written instead of a
    verdict, so productivity cannot be declared before the booster below it
    (CP-4, reputation flow live) is proven. Recording is flag-gated by the
    registry itself.
    """
    _require_enabled()
    cp5 = registry.checkpoint(CheckpointCode.CP5)
    dep = cp5.depends_on
    if dep is not None and registry.status_of(dep) != CheckpointStatus.PASS:
        dep_status = registry.status_of(dep).value
        record = CheckpointRecord.create(
            checkpoint_code=CheckpointCode.CP5,
            status=CheckpointStatus.SKIPPED,
            evaluator=evaluator,
            evidence={"depends_on": dep.value, "dependency_status": dep_status},
            notes=f"skipped: depends on {dep.value} which is {dep_status}",
        )
        return registry.record(record)

    evaluation = evaluate_cp5(
        trend,
        rescue_spike_threshold=rescue_spike_threshold,
        min_scored_weeks=min_scored_weeks,
    )
    return registry.record(evaluation.to_record(evaluator=evaluator))


__all__ = [
    "CP5_EVALUATOR_NAME",
    "DEFAULT_RESCUE_SPIKE_THRESHOLD",
    "Cp5Evaluation",
    "evaluate_cp5",
    "record_cp5",
    "rescue_spike_weeks",
]
