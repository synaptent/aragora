"""Cross-loop outcome signal bus for autonomous orchestration.

All four autonomous loops (Boss, Nomic, Ralph, Pipeline) emit outcome
signals when work completes or fails.  Subscribers consume these signals
to calibrate predictions, generate improvement goals, and route future
work to the loop most likely to succeed.

Architecture:
    OutcomeSignal  — Canonical event emitted by any loop
    OutcomeSignalBus — JSONL-backed pub/sub with in-process subscribers
    OutcomeLearner — Rolling aggregator for loop + agent outcomes
    GoalGenerator  — Consumes failure patterns → produces Nomic goals
    CalibrationHub — Consumes outcomes → adjusts estimator weights
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, TYPE_CHECKING

if TYPE_CHECKING:
    from aragora.swarm.outcome_learner import OutcomeLearner, OutcomeLearnerSnapshot
logger = logging.getLogger(__name__)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# Core signal type
# ---------------------------------------------------------------------------


@dataclass
class OutcomeSignal:
    """Canonical outcome event emitted by any autonomous loop."""

    # Identity
    source_loop: str  # boss | nomic | ralph | pipeline
    signal_type: str  # completed | failed | escalated | repaired | blocked
    entity_id: str  # issue number, cycle ID, campaign ID, etc.
    entity_title: str = ""
    debate_id: str = ""

    # Quality
    quality_delta: float = 0.0  # Net quality change (-1.0 to 1.0)
    proof_advanced: bool = False  # Did this advance a proof gate?
    receipt_produced: bool = False  # Did this produce an audit receipt?

    # Cost
    tokens_used: int = 0
    elapsed_seconds: float = 0.0
    human_minutes: float = 0.0
    cost_usd: float = 0.0

    # Failure detail
    failure_reason: str = ""
    blocker_kind: str = ""  # Ralph BlockerKind value, if applicable

    # Metadata
    agent_type: str = ""  # claude | codex | etc.
    files_changed: list[str] = field(default_factory=list)
    commit_shas: list[str] = field(default_factory=list)
    did_merge: bool = False
    needed_human_rescue: bool = False

    # Provenance
    timestamp: str = ""
    correlation_id: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(UTC).isoformat()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["elapsed_seconds"] = self.elapsed_seconds
        return data

    @property
    def is_success(self) -> bool:
        return self.signal_type in ("completed", "repaired")

    @property
    def is_failure(self) -> bool:
        return self.signal_type in ("failed", "escalated", "blocked")


# ---------------------------------------------------------------------------
# Signal bus — JSONL-backed pub/sub
# ---------------------------------------------------------------------------

SignalHandler = Callable[[OutcomeSignal], None]

_DEFAULT_SIGNAL_LOG = Path("~/.aragora/outcome_signals.jsonl").expanduser()


class OutcomeSignalBus:
    """Thread-safe pub/sub for outcome signals with JSONL persistence."""

    def __init__(self, *, log_path: Path | None = None) -> None:
        self._log_path = log_path or _DEFAULT_SIGNAL_LOG
        self._handlers: dict[str, list[SignalHandler]] = defaultdict(list)
        self._global_handlers: list[SignalHandler] = []
        self._lock = threading.Lock()
        self._signal_count = 0

    def emit(self, signal: OutcomeSignal) -> None:
        """Emit a signal: persist to JSONL, notify all subscribers."""
        # Persist
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_path, "a") as f:
            f.write(json.dumps(signal.to_dict()) + "\n")

        self._signal_count += 1

        # Notify subscribers — isolate handler failures
        with self._lock:
            handlers = list(self._global_handlers)
            handlers.extend(self._handlers.get(signal.source_loop, []))
            handlers.extend(self._handlers.get(signal.signal_type, []))

        for handler in handlers:
            try:
                handler(signal)
            except Exception as exc:  # noqa: BLE001 - subscriber callbacks are external and must not break the bus
                logger.debug("Signal handler failed: %s", exc)

    def subscribe(self, key: str, handler: SignalHandler) -> None:
        """Subscribe to signals by source_loop or signal_type."""
        with self._lock:
            self._handlers[key].append(handler)

    def subscribe_all(self, handler: SignalHandler) -> None:
        """Subscribe to all signals regardless of type."""
        with self._lock:
            self._global_handlers.append(handler)

    def recent(self, *, minutes: int = 60, limit: int = 100) -> list[OutcomeSignal]:
        """Load recent signals from JSONL log."""
        if not self._log_path.exists():
            return []
        cutoff = datetime.now(UTC).timestamp() - (minutes * 60)
        signals: list[OutcomeSignal] = []
        for line in reversed(self._log_path.read_text().strip().splitlines()):
            if len(signals) >= limit:
                break
            try:
                data = json.loads(line)
                ts = data.get("timestamp", "")
                if ts:
                    from datetime import datetime as dt

                    parsed = dt.fromisoformat(ts.replace("Z", "+00:00"))
                    if parsed.timestamp() < cutoff:
                        break
                signals.append(
                    OutcomeSignal(
                        **{k: v for k, v in data.items() if k in OutcomeSignal.__dataclass_fields__}
                    )
                )
            except (
                AttributeError,
                json.JSONDecodeError,
                OSError,
                OverflowError,
                TypeError,
                ValueError,
            ):
                continue
        return list(reversed(signals))

    @property
    def total_emitted(self) -> int:
        return self._signal_count


# Singleton
_bus: OutcomeSignalBus | None = None
_bus_lock = threading.Lock()
_learner: "OutcomeLearner | None" = None
_learner_lock = threading.Lock()


def get_signal_bus(*, log_path: Path | None = None) -> OutcomeSignalBus:
    """Get or create the global outcome signal bus."""
    global _bus
    with _bus_lock:
        if _bus is None:
            _bus = OutcomeSignalBus(log_path=log_path)
        return _bus


def get_outcome_learner(*, window_size: int = 500) -> "OutcomeLearner":
    """Get or create the global outcome learner."""
    from aragora.swarm.outcome_learner import OutcomeLearner

    global _learner
    with _learner_lock:
        if _learner is None:
            _learner = OutcomeLearner(window_size=window_size)
        return _learner


def snapshot_outcome_signals(
    signals: Iterable[OutcomeSignal],
    *,
    window_size: int = 500,
) -> "OutcomeLearnerSnapshot":
    """Compute a deterministic snapshot from a sequence of signals."""
    from aragora.swarm.outcome_learner import OutcomeLearner

    learner = OutcomeLearner(window_size=window_size)
    learner.ingest_many(signals)
    return learner.snapshot()


# ---------------------------------------------------------------------------
# Layer 2: Goal generation from failure patterns
# ---------------------------------------------------------------------------


@dataclass
class GeneratedGoal:
    """A Nomic improvement goal generated from outcome patterns."""

    goal_text: str
    confidence: float
    source_signals: list[str]  # entity_ids that triggered this
    estimated_impact: float = 0.5
    estimated_effort: float = 0.5
    category: str = ""  # test_coverage | reliability | infra | performance

    @property
    def score(self) -> float:
        return self.confidence * self.estimated_impact / max(0.1, self.estimated_effort)


def generate_goals_from_outcomes(
    signals: list[OutcomeSignal],
    *,
    min_failures: int = 3,
    max_goals: int = 5,
) -> list[GeneratedGoal]:
    """Analyze failure patterns and generate improvement goals.

    Looks for repeated failure modes across loops and produces
    actionable goals that Nomic can execute.
    """
    if not signals:
        return []

    goals: list[GeneratedGoal] = []

    # Pattern 1: Repeated needs_human from Boss loop
    boss_failures = [s for s in signals if s.source_loop == "boss" and s.is_failure]
    if len(boss_failures) >= min_failures:
        # Check for common failure reasons
        reason_counts: dict[str, list[str]] = defaultdict(list)
        for s in boss_failures:
            reason = s.failure_reason or "unknown"
            reason_counts[reason].append(s.entity_id)

        for reason, entity_ids in reason_counts.items():
            if len(entity_ids) >= min_failures:
                goals.append(
                    GeneratedGoal(
                        goal_text=(
                            f"Fix recurring boss loop failure: {reason}. "
                            f"Affected {len(entity_ids)} issues. "
                            "Investigate root cause and harden the worker dispatch path."
                        ),
                        confidence=min(0.9, 0.5 + 0.1 * len(entity_ids)),
                        source_signals=entity_ids[:5],
                        estimated_impact=0.8,
                        estimated_effort=0.4,
                        category="reliability",
                    )
                )

    # Pattern 2: Ralph blocker recurrence
    ralph_blockers = [s for s in signals if s.source_loop == "ralph" and s.blocker_kind]
    blocker_counts: dict[str, int] = defaultdict(int)
    for s in ralph_blockers:
        blocker_counts[s.blocker_kind] += 1

    for kind, count in blocker_counts.items():
        if count >= 2:
            goals.append(
                GeneratedGoal(
                    goal_text=(
                        f"Eliminate recurring blocker: {kind} (seen {count} times). "
                        "Root-cause the pattern and add a preventive check."
                    ),
                    confidence=min(0.9, 0.5 + 0.15 * count),
                    source_signals=[kind],
                    estimated_impact=0.7,
                    estimated_effort=0.3,
                    category="reliability",
                )
            )

    # Pattern 3: Low merge rate from any loop
    by_loop: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "merged": 0})
    for s in signals:
        by_loop[s.source_loop]["total"] += 1
        if s.did_merge:
            by_loop[s.source_loop]["merged"] += 1

    for loop, counts in by_loop.items():
        if counts["total"] >= 5:
            rate = counts["merged"] / counts["total"]
            if rate < 0.3:
                goals.append(
                    GeneratedGoal(
                        goal_text=(
                            f"Improve {loop} loop merge rate (currently {rate:.0%}). "
                            f"{counts['merged']}/{counts['total']} attempts merged. "
                            "Audit recent failures and fix the most common cause."
                        ),
                        confidence=0.8,
                        source_signals=[loop],
                        estimated_impact=0.9,
                        estimated_effort=0.5,
                        category="infra",
                    )
                )

    # Pattern 4: High token burn without results
    high_cost_failures = [s for s in signals if s.is_failure and s.tokens_used > 80_000]
    if len(high_cost_failures) >= 3:
        total_wasted = sum(s.tokens_used for s in high_cost_failures)
        goals.append(
            GeneratedGoal(
                goal_text=(
                    f"Reduce wasted tokens on failing tasks ({total_wasted:,} tokens burned "
                    f"across {len(high_cost_failures)} failures). Add early exit conditions "
                    "or better pre-dispatch feasibility checks."
                ),
                confidence=0.7,
                source_signals=[s.entity_id for s in high_cost_failures[:5]],
                estimated_impact=0.6,
                estimated_effort=0.3,
                category="performance",
            )
        )

    # Sort by score, return top N
    goals.sort(key=lambda g: g.score, reverse=True)
    return goals[:max_goals]


# ---------------------------------------------------------------------------
# Layer 3: Calibration hub — cross-loop weight adjustment
# ---------------------------------------------------------------------------


@dataclass
class CalibrationSnapshot:
    """Point-in-time calibration state for the value estimator."""

    timestamp: str
    total_outcomes: int
    merge_rate: float
    avg_tokens_per_task: int
    avg_minutes_per_task: float
    rescue_rate: float  # fraction needing human intervention
    loop_merge_rates: dict[str, float]  # per-loop merge rates
    blocker_frequency: dict[str, int]  # blocker_kind → count
    agent_success_rates: dict[str, float]  # agent_type → success rate
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp_iso"] = self.timestamp
        return data


def compute_calibration(
    signals: list[OutcomeSignal],
) -> CalibrationSnapshot | None:
    """Compute calibration snapshot from outcome signals.

    This is the core of the cross-loop learning system. It produces
    actionable recommendations that tune the value estimator and
    inform model routing decisions.
    """
    if len(signals) < 5:
        return None

    total = len(signals)
    merged = sum(1 for s in signals if s.did_merge)
    rescued = sum(1 for s in signals if s.needed_human_rescue)
    tokens = [s.tokens_used for s in signals if s.tokens_used > 0]
    minutes = [s.elapsed_seconds / 60.0 for s in signals if s.elapsed_seconds > 0]

    # Per-loop rates
    loop_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "merged": 0})
    for s in signals:
        loop_totals[s.source_loop]["total"] += 1
        if s.did_merge:
            loop_totals[s.source_loop]["merged"] += 1

    loop_rates = {
        loop: counts["merged"] / max(1, counts["total"]) for loop, counts in loop_totals.items()
    }

    # Blocker frequency
    blocker_freq: dict[str, int] = defaultdict(int)
    for s in signals:
        if s.blocker_kind:
            blocker_freq[s.blocker_kind] += 1

    # Agent success rates
    agent_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "success": 0})
    for s in signals:
        if s.agent_type:
            agent_totals[s.agent_type]["total"] += 1
            if s.is_success:
                agent_totals[s.agent_type]["success"] += 1

    agent_rates = {
        agent: counts["success"] / max(1, counts["total"]) for agent, counts in agent_totals.items()
    }

    # Generate recommendations
    recommendations: list[str] = []
    merge_rate = merged / total

    if merge_rate < 0.3:
        recommendations.append(
            f"Overall merge rate is {merge_rate:.0%} — consider tightening "
            "issue scope or improving worker prompts."
        )

    for loop, rate in loop_rates.items():
        if rate < 0.2 and loop_totals[loop]["total"] >= 3:
            recommendations.append(
                f"{loop} loop merge rate is {rate:.0%} — investigate failure mode."
            )

    for agent, rate in agent_rates.items():
        if rate < 0.2 and agent_totals[agent]["total"] >= 3:
            recommendations.append(
                f"Agent '{agent}' success rate is {rate:.0%} — consider "
                "routing fewer tasks to this agent or improving its prompts."
            )

    rescue_rate = rescued / total
    if rescue_rate > 0.5:
        recommendations.append(
            f"Human rescue rate is {rescue_rate:.0%} — too many tasks need intervention. "
            "Improve pre-dispatch feasibility checks."
        )

    for kind, count in sorted(blocker_freq.items(), key=lambda x: -x[1]):
        if count >= 3:
            recommendations.append(f"Blocker '{kind}' seen {count} times — add a preventive check.")

    return CalibrationSnapshot(
        timestamp=datetime.now(UTC).isoformat(),
        total_outcomes=total,
        merge_rate=merge_rate,
        avg_tokens_per_task=int(sum(tokens) / len(tokens)) if tokens else 0,
        avg_minutes_per_task=sum(minutes) / len(minutes) if minutes else 0.0,
        rescue_rate=rescue_rate,
        loop_merge_rates=loop_rates,
        blocker_frequency=dict(blocker_freq),
        agent_success_rates=agent_rates,
        recommendations=recommendations,
    )


def goals_from_feedback_records(
    records: list[Any],
    *,
    max_goals: int = 5,
) -> list[GeneratedGoal]:
    """Convert OutcomeFeedbackRecord instances into Nomic Loop goals.

    Translates pipeline outcome feedback (from backbone_contracts) into
    actionable GeneratedGoal objects that the Nomic Loop can execute.
    Does not create GitHub issues — returns goal strings only.
    """
    if not records:
        return []

    goals: list[GeneratedGoal] = []

    for rec in records:
        # Low objective fidelity → improvement goal
        fidelity = getattr(rec, "objective_fidelity", 1.0)
        domain = getattr(rec, "domain", "unknown")
        run_type = getattr(rec, "run_type", "unknown")
        pipeline_id = getattr(rec, "pipeline_id", "")
        recommendation = getattr(rec, "next_action_recommendation", "")
        quality = getattr(rec, "quality_outcome", {}) or {}
        execution = getattr(rec, "execution_outcome", {}) or {}

        if fidelity < 0.5:
            goal_text = (
                f"Improve {domain} pipeline fidelity (currently {fidelity:.0%}) "
                f"for run type '{run_type}'."
            )
            if recommendation:
                goal_text += f" Recommended: {recommendation}"
            goals.append(
                GeneratedGoal(
                    goal_text=goal_text,
                    confidence=min(0.9, 0.5 + (1.0 - fidelity) * 0.5),
                    source_signals=[pipeline_id] if pipeline_id else [],
                    estimated_impact=0.8,
                    estimated_effort=0.4,
                    category="reliability",
                )
            )

        # Quality failures
        if quality.get("error") or quality.get("failed"):
            reason = quality.get("error") or quality.get("reason", "quality check failed")
            goals.append(
                GeneratedGoal(
                    goal_text=(f"Fix quality failure in {domain}/{run_type}: {reason}"),
                    confidence=0.7,
                    source_signals=[pipeline_id] if pipeline_id else [],
                    estimated_impact=0.7,
                    estimated_effort=0.5,
                    category="reliability",
                )
            )

        # Execution failures
        if execution.get("error") or execution.get("failed"):
            reason = execution.get("error") or execution.get("reason", "execution failed")
            goals.append(
                GeneratedGoal(
                    goal_text=(f"Fix execution failure in {domain}/{run_type}: {reason}"),
                    confidence=0.75,
                    source_signals=[pipeline_id] if pipeline_id else [],
                    estimated_impact=0.8,
                    estimated_effort=0.4,
                    category="infra",
                )
            )

    # Deduplicate by goal_text, sort by score, limit
    seen: set[str] = set()
    unique: list[GeneratedGoal] = []
    for g in goals:
        if g.goal_text not in seen:
            seen.add(g.goal_text)
            unique.append(g)
    unique.sort(key=lambda g: g.score, reverse=True)
    return unique[:max_goals]


def apply_calibration_to_estimator(
    snapshot: CalibrationSnapshot,
) -> dict[str, Any]:
    """Apply calibration insights to the value estimator weights.

    Returns a dict of adjustments that were applied.
    """
    adjustments: dict[str, Any] = {}

    # If a specific agent type has low success, the estimator should
    # factor that into p_success when that agent is the likely runner
    for agent, rate in snapshot.agent_success_rates.items():
        if rate < 0.3:
            adjustments[f"agent_penalty_{agent}"] = 1.0 - rate

    # If a blocker kind is very common, downrank issues likely to hit it
    for kind, count in snapshot.blocker_frequency.items():
        if count >= 5:
            adjustments[f"blocker_penalty_{kind}"] = min(0.5, count * 0.05)

    # Overall merge rate adjustment
    if snapshot.merge_rate < 0.3:
        adjustments["global_p_success_damper"] = snapshot.merge_rate

    return adjustments
