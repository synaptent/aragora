"""Task value-per-cost estimation for autonomous queue prioritization.

Scores issues by expected marginal value relative to expected cost,
using structured heuristics with optional LLM-assisted estimation.
Predictions are logged alongside actual outcomes so the system
calibrates over time.

Scoring formula:
    priority = (value * p_success * proof_weight * unblock_weight) / expected_cost

Where each factor is estimated from issue metadata, historical outcomes,
and optionally a frontier model judgment.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

UTC = timezone.utc


@dataclass
class ValueEstimate:
    """Structured value-per-cost estimate for a single issue."""

    issue_number: int
    title: str

    # Core factors (0.0 - 1.0 unless noted)
    expected_value: float = 0.5  # How much user/product value if completed
    p_success: float = 0.5  # Likelihood of producing a concrete deliverable
    proof_weight: float = 0.5  # Whether it advances current proof gate
    unblock_weight: float = 0.5  # Whether it unblocks other work
    truthfulness: float = 0.8  # Likelihood of ending truthfully if blocked

    # Cost factors
    expected_tokens: int = 50_000  # Estimated token spend
    expected_minutes: float = 10.0  # Wall-clock time
    human_review_minutes: float = 5.0  # Human time to review/merge
    rerun_probability: float = 0.3  # Chance of needing debug/rerun
    merge_difficulty: float = 0.2  # Integration/conflict risk (0=easy, 1=hard)

    # Computed
    priority_score: float = 0.0

    # Metadata
    estimation_method: str = "heuristic"  # heuristic | llm | calibrated
    estimated_at: str = ""
    reasoning: str = ""

    def compute_score(self) -> float:
        """Compute priority score from factors."""
        value_numerator = (
            self.expected_value
            * self.p_success
            * self.proof_weight
            * self.unblock_weight
            * self.truthfulness
        )
        # Normalize cost to 0-1 range using log scale
        token_cost = math.log1p(self.expected_tokens / 10_000) / 5.0
        time_cost = self.expected_minutes / 60.0
        human_cost = self.human_review_minutes / 30.0
        rerun_cost = self.rerun_probability
        merge_cost = self.merge_difficulty

        expected_cost = max(
            0.01,
            0.3 * token_cost
            + 0.2 * time_cost
            + 0.25 * human_cost
            + 0.15 * rerun_cost
            + 0.1 * merge_cost,
        )

        self.priority_score = value_numerator / expected_cost
        return self.priority_score

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OutcomeRecord:
    """Actual outcome for calibration against predictions."""

    issue_number: int
    predicted_score: float
    predicted_p_success: float

    # Actual outcomes
    did_merge: bool = False
    did_produce_receipt: bool = False
    did_unblock_proof: bool = False
    needed_human_rescue: bool = False
    actual_tokens: int = 0
    actual_minutes: float = 0.0
    actual_human_minutes: float = 0.0
    worker_status: str = ""  # completed | needs_human | failed
    recorded_at: str = ""


# ---------------------------------------------------------------------------
# Heuristic estimation from issue metadata
# ---------------------------------------------------------------------------

# Signals that indicate high-value work
_HIGH_VALUE_PATTERNS = [
    (r"fix\b|bug\b|broken\b|crash", 0.15, "bugfix"),
    (r"receipt|proof|audit", 0.15, "proof_work"),
    (r"test.*cover|add.*test", 0.10, "test_coverage"),
    (r"deploy|ci|pipeline", 0.10, "infra"),
]

# Signals that indicate low-value work
_LOW_VALUE_PATTERNS = [
    (r"doc[s]?\b|readme|comment", -0.15, "docs_only"),
    (r"refactor|rename|cleanup|hygiene", -0.10, "hygiene"),
    (r"style|format|lint", -0.15, "style_only"),
]

# Signals that indicate high success probability
_HIGH_SUCCESS_SIGNALS = [
    (r"pytest.*-[xq]|acceptance.*:.*pytest", 0.15, "has_test_command"),
    (r"files?.*:.*\.py|files? to (check|change)", 0.15, "has_file_scope"),
    (r"```", 0.10, "has_code_example"),
]

# Signals that indicate low success probability
_LOW_SUCCESS_SIGNALS = [
    (r"(chrome|browser) extension", -0.20, "browser_extension"),
    (r"frontend|react|next\.?js|tsx", -0.10, "frontend_work"),
    (r"slack.*integration|email.*integration", -0.10, "external_integration"),
    (r"dashboard|ui.*component|visual", -0.10, "ui_work"),
]


def estimate_from_issue(
    issue_number: int,
    title: str,
    body: str,
    *,
    labels: list[str] | None = None,
    historical_outcomes: list[OutcomeRecord] | None = None,
) -> ValueEstimate:
    """Estimate value-per-cost from issue metadata using heuristics.

    This is the fast path — no LLM calls, runs in <1ms.
    """
    text = f"{title} {body}".lower()
    _labels = set(labels or [])

    est = ValueEstimate(
        issue_number=issue_number,
        title=title,
        estimated_at=datetime.now(UTC).isoformat(),
        estimation_method="heuristic",
    )

    # --- Value estimation ---
    value = 0.5
    reasons = []
    for pattern, delta, reason in _HIGH_VALUE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            value += delta
            reasons.append(f"+value:{reason}")
    for pattern, delta, reason in _LOW_VALUE_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            value += delta
            reasons.append(f"-value:{reason}")
    est.expected_value = max(0.05, min(1.0, value))

    # --- Success probability ---
    p_success = 0.5
    for pattern, delta, reason in _HIGH_SUCCESS_SIGNALS:
        if re.search(pattern, text, re.IGNORECASE):
            p_success += delta
            reasons.append(f"+success:{reason}")
    for pattern, delta, reason in _LOW_SUCCESS_SIGNALS:
        if re.search(pattern, text, re.IGNORECASE):
            p_success += delta
            reasons.append(f"-success:{reason}")

    # Issue length correlates with scope clarity
    body_len = len(body or "")
    if body_len > 500:
        p_success += 0.10
        reasons.append("+success:detailed_body")
    elif body_len < 100:
        p_success -= 0.15
        reasons.append("-success:sparse_body")

    est.p_success = max(0.05, min(0.95, p_success))

    # --- Proof weight ---
    proof = 0.5
    if any(lbl in _labels for lbl in ("proof", "receipt", "proving-path")):
        proof = 0.9
        reasons.append("+proof:label")
    elif re.search(r"receipt|proof|audit|verify", text):
        proof = 0.7
        reasons.append("+proof:keyword")
    est.proof_weight = proof

    # --- Unblock weight ---
    unblock = 0.5
    if re.search(r"block|depend|prerequisite|before we can", text):
        unblock = 0.8
        reasons.append("+unblock:keyword")
    est.unblock_weight = unblock

    # --- Cost estimation ---
    # Longer issues tend to require more work
    if body_len > 1000:
        est.expected_tokens = 80_000
        est.expected_minutes = 15.0
    elif body_len > 300:
        est.expected_tokens = 50_000
        est.expected_minutes = 10.0
    else:
        est.expected_tokens = 30_000
        est.expected_minutes = 5.0

    # Frontend/UI work takes longer to verify
    if re.search(r"frontend|react|tsx|css|tailwind", text):
        est.expected_minutes *= 1.5
        est.human_review_minutes *= 2.0
        est.merge_difficulty = 0.4

    # --- Historical calibration ---
    if historical_outcomes:
        _apply_calibration(est, historical_outcomes, reasons)

    est.reasoning = "; ".join(reasons)
    est.compute_score()
    return est


def _apply_calibration(
    est: ValueEstimate,
    outcomes: list[OutcomeRecord],
    reasons: list[str],
) -> None:
    """Adjust estimates based on historical prediction vs outcome data."""
    if len(outcomes) < 5:
        return

    # Calculate historical success rate
    total = len(outcomes)
    successes = sum(1 for o in outcomes if o.did_merge)
    historical_rate = successes / total

    # Blend heuristic with historical rate
    est.p_success = 0.6 * est.p_success + 0.4 * historical_rate
    est.estimation_method = "calibrated"
    reasons.append(f"calibrated:history({successes}/{total}={historical_rate:.0%})")

    # Adjust token estimate from actual data
    actual_tokens = [o.actual_tokens for o in outcomes if o.actual_tokens > 0]
    if actual_tokens:
        median_tokens = sorted(actual_tokens)[len(actual_tokens) // 2]
        est.expected_tokens = int(0.5 * est.expected_tokens + 0.5 * median_tokens)

    # Adjust human cost from rescue rate
    rescue_rate = sum(1 for o in outcomes if o.needed_human_rescue) / total
    est.human_review_minutes *= 1.0 + rescue_rate
    if rescue_rate > 0.5:
        reasons.append(f"warning:high_rescue_rate({rescue_rate:.0%})")


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def rank_issues(
    issues: list[dict[str, Any]],
    *,
    historical_outcomes: list[OutcomeRecord] | None = None,
) -> list[tuple[ValueEstimate, dict[str, Any]]]:
    """Rank issues by estimated value-per-cost, highest first."""
    scored: list[tuple[ValueEstimate, dict[str, Any]]] = []
    for issue in issues:
        est = estimate_from_issue(
            issue_number=issue.get("number", 0),
            title=issue.get("title", ""),
            body=issue.get("body", ""),
            labels=issue.get("labels", []),
            historical_outcomes=historical_outcomes,
        )
        scored.append((est, issue))

    scored.sort(key=lambda x: x[0].priority_score, reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Outcome logging for calibration
# ---------------------------------------------------------------------------

_DEFAULT_OUTCOMES_PATH = Path("~/.aragora/swarm_outcomes.jsonl").expanduser()


def log_outcome(
    outcome: OutcomeRecord,
    *,
    path: Path | None = None,
) -> None:
    """Append an outcome record for future calibration."""
    target = path or _DEFAULT_OUTCOMES_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    outcome.recorded_at = outcome.recorded_at or datetime.now(UTC).isoformat()
    with open(target, "a") as f:
        f.write(json.dumps(asdict(outcome)) + "\n")


def load_outcomes(*, path: Path | None = None) -> list[OutcomeRecord]:
    """Load historical outcome records."""
    target = path or _DEFAULT_OUTCOMES_PATH
    if not target.exists():
        return []
    records: list[OutcomeRecord] = []
    for line in target.read_text().strip().splitlines():
        try:
            data = json.loads(line)
            records.append(
                OutcomeRecord(
                    **{k: v for k, v in data.items() if k in OutcomeRecord.__dataclass_fields__}
                )
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return records


def log_prediction(
    estimate: ValueEstimate,
    *,
    path: Path | None = None,
) -> None:
    """Append a prediction record for future calibration comparison."""
    target = path or Path("~/.aragora/swarm_predictions.jsonl").expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a") as f:
        f.write(json.dumps(estimate.to_dict()) + "\n")


# ---------------------------------------------------------------------------
# LLM-assisted second scoring pass
# ---------------------------------------------------------------------------

_LLM_SCORING_PROMPT = """\
You are evaluating a GitHub issue for autonomous worker dispatch.
Score each factor from 0.0 to 1.0. Be calibrated — most issues are 0.3-0.7.

Issue #{number}: {title}

{body}

Respond with ONLY a JSON object (no markdown, no explanation):
{{
  "expected_value": <float 0-1, product/user value if completed>,
  "p_success": <float 0-1, chance an AI worker produces a mergeable deliverable>,
  "proof_weight": <float 0-1, does this advance a proving path or audit gate>,
  "unblock_weight": <float 0-1, does this unblock other work>,
  "expected_tokens": <int, estimated token cost>,
  "reasoning": "<one sentence explaining your scoring>"
}}
"""


async def estimate_with_llm(
    issue_number: int,
    title: str,
    body: str,
    *,
    heuristic_estimate: ValueEstimate | None = None,
    model: str = "claude-opus-5",
) -> ValueEstimate:
    """Refine a value estimate using a frontier LLM.

    Only call this for high-uncertainty issues (heuristic score in 0.3-0.7
    range) or when the queue has fewer than 5 issues. This costs ~1k tokens.

    Falls back to heuristic estimate on any failure.
    """
    fallback = heuristic_estimate or estimate_from_issue(
        issue_number=issue_number, title=title, body=body
    )

    try:
        import anthropic

        client = anthropic.AsyncAnthropic()
        prompt = _LLM_SCORING_PROMPT.format(
            number=issue_number,
            title=title,
            body=(body or "")[:2000],
        )
        response = await client.messages.create(
            model=model,
            # Opus 5 thinks by default; max_tokens covers thinking + response.
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        # Opus 5 thinks by default, so content[0] is a thinking block, not text.
        # Scan for the text block instead of indexing blindly.
        text = next(
            (
                getattr(b, "text", "")
                for b in response.content
                if getattr(b, "type", None) == "text"
            ),
            "",
        ).strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        data = json.loads(text)

        est = ValueEstimate(
            issue_number=issue_number,
            title=title,
            expected_value=max(0.05, min(1.0, float(data.get("expected_value", 0.5)))),
            p_success=max(0.05, min(0.95, float(data.get("p_success", 0.5)))),
            proof_weight=max(0.0, min(1.0, float(data.get("proof_weight", 0.5)))),
            unblock_weight=max(0.0, min(1.0, float(data.get("unblock_weight", 0.5)))),
            expected_tokens=int(data.get("expected_tokens", 50_000)),
            estimation_method="llm",
            reasoning=str(data.get("reasoning", "")),
            estimated_at=datetime.now(UTC).isoformat(),
        )

        # Blend LLM estimate with heuristic (60/40 LLM-favored)
        if heuristic_estimate:
            est.expected_value = 0.6 * est.expected_value + 0.4 * heuristic_estimate.expected_value
            est.p_success = 0.6 * est.p_success + 0.4 * heuristic_estimate.p_success
            est.estimation_method = "llm_blended"

        est.compute_score()
        return est

    except (
        ImportError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
        RuntimeError,
    ) as exc:
        logger.debug("LLM value estimation failed, using heuristic: %s", exc)
        return fallback


# ---------------------------------------------------------------------------
# Cross-loop calibration integration
# ---------------------------------------------------------------------------


def apply_cross_loop_calibration(
    estimate: ValueEstimate,
    *,
    calibration_adjustments: dict[str, Any] | None = None,
) -> ValueEstimate:
    """Apply cross-loop calibration adjustments to a value estimate.

    Takes adjustments from ``outcome_signals.apply_calibration_to_estimator()``
    and uses them to refine the estimate.
    """
    if not calibration_adjustments:
        return estimate

    # Global merge rate damper
    damper = calibration_adjustments.get("global_p_success_damper")
    if damper is not None and isinstance(damper, (int, float)):
        # Blend current estimate with observed global rate
        estimate.p_success = 0.7 * estimate.p_success + 0.3 * float(damper)

    # Agent-specific penalties
    for key, penalty in calibration_adjustments.items():
        if key.startswith("agent_penalty_") and isinstance(penalty, (int, float)):
            # If the likely runner agent has a penalty, reduce p_success
            estimate.p_success *= max(0.3, 1.0 - float(penalty) * 0.3)

    # Blocker-specific penalties
    for key, penalty in calibration_adjustments.items():
        if key.startswith("blocker_penalty_") and isinstance(penalty, (int, float)):
            # Reduce expected_value if related blockers are common
            estimate.expected_value *= max(0.5, 1.0 - float(penalty))

    estimate.compute_score()
    return estimate
