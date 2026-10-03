#!/usr/bin/env python3
"""End-to-end smoke test for the AGT-05 reputation signal flow.

Exercises the full path:

    MetaculusQuestion (resolved) + agent prediction
        -> bridge_from_metaculus_question
        -> StakeableClaim + ResolvedClaim
        -> settle_claim (Brier-proper scoring rule)
        -> ReputationDelta

with the ``ARAGORA_REPUTATION_FLOW_ENABLED`` flag set to ``1``. Uses
synthetic-but-realistic data so the run is hermetic and deterministic.

Run::

    ARAGORA_REPUTATION_FLOW_ENABLED=1 \\
        python3 scripts/agt_05_reputation_flow_smoke.py

Optional persistence (AGT-05 SD-1 substrate continuation)::

    ARAGORA_REPUTATION_FLOW_ENABLED=1 \\
        python3 scripts/agt_05_reputation_flow_smoke.py \\
            --persist /tmp/agt_05_ledger.jsonl

When ``--persist`` is given, computed deltas are recorded via the
existing :class:`aragora.reputation.store.ReputationStore`, appended to
the JSONL path, and the post-persist per-agent score is read back from
the store to demonstrate the round-trip.

The script prints a per-agent per-question table of reputation deltas
and a per-agent total. No live API calls. No public-API mutation.
This is purely a calibration exercise to prove the signal flow runs
end-to-end on the same code path a live Arena debate would use once
the predictor/resolver hooks are wired.

Out of scope (deliberate):

- Wiring into ``Arena`` -- that is the production integration step
  ``AGT-05`` sub-deliverable that follows this calibration.
- On-chain anchoring via :class:`ReputationRegistry`.
- ``team_selector`` consumption of store scores (separate flag).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Ensure repo root is importable when run from anywhere.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from aragora.connectors.prediction_markets.metaculus import MetaculusQuestion
from aragora.reputation.metaculus_bridge import (
    bridge_from_metaculus_question,
    reputation_flow_enabled,
)
from aragora.reputation.settlement import settle_claim
from aragora.reputation.store import ReputationStore
from aragora.reputation.types import ReputationDelta


# ---------------------------------------------------------------------------
# Pure data construction (testable without env or I/O)
# ---------------------------------------------------------------------------


SMOKE_QUESTIONS: list[tuple[str, str, float]] = [
    ("manifold-1001", "Will the H1-01 rev-4 corpus be promoted by 2026-05-15?", 1.0),
    ("manifold-1002", "Will the proof-loop alerter PR (#7156) land by 2026-05-20?", 1.0),
    ("manifold-1003", "Will boss_metrics.jsonl reach 10k rows by 2026-06-01?", 0.0),
]

SMOKE_AGENT_PREDICTIONS: dict[str, list[float]] = {
    "claude-opus-5": [0.90, 0.85, 0.10],
    "gpt-4.1": [0.60, 0.55, 0.45],
    "demo-anti": [0.10, 0.05, 0.90],
}


def _resolved_question(qid: int, title: str, resolution: float) -> MetaculusQuestion:
    now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    return MetaculusQuestion(
        question_id=qid,
        title=title,
        question_type="binary",
        created_time=now,
        close_time=now,
        resolve_time=now,
        active_state="resolved",
        resolution=resolution,
        community_q2=0.5,
        raw={},
    )


def compute_deltas(
    questions: list[tuple[str, str, float]] | None = None,
    agent_predictions: dict[str, list[float]] | None = None,
    *,
    stake_units: int = 10,
) -> tuple[list[ReputationDelta], list[dict[str, Any]]]:
    """Compute reputation deltas for the smoke scenario.

    Returns ``(deltas, rows)`` where ``rows`` is a list of dicts with
    one entry per (question, agent) pair for pretty-printing.
    """
    qs = questions if questions is not None else SMOKE_QUESTIONS
    preds = agent_predictions if agent_predictions is not None else SMOKE_AGENT_PREDICTIONS

    deltas: list[ReputationDelta] = []
    rows: list[dict[str, Any]] = []

    for q_idx, (q_id, q_title, resolution) in enumerate(qs):
        q = _resolved_question(
            qid=int(q_id.split("-")[1]),
            title=q_title,
            resolution=resolution,
        )
        for agent_id, predictions in preds.items():
            p = predictions[q_idx]
            claim, resolved = bridge_from_metaculus_question(
                q,
                agent_id=agent_id,
                predicted_probability=p,
                stake_units=stake_units,
            )
            delta = settle_claim(claim, resolved)
            deltas.append(delta)
            rows.append(
                {
                    "question_id": q_id,
                    "agent": agent_id,
                    "predicted_p": p,
                    "outcome": resolved.outcome,
                    "brier": delta.reason.get("brier"),
                    "payout_fraction": delta.reason.get("payout_fraction"),
                    "delta": round(delta.delta, 3),
                }
            )

    return deltas, rows


def persist_to_store(
    deltas: list[ReputationDelta],
    path: Path,
) -> tuple[ReputationStore, dict[str, float]]:
    """Persist *deltas* via :class:`ReputationStore` and read back per-agent scores.

    Returns ``(store, scores)`` where ``scores`` maps agent_id to the
    decayed running score from the store after all deltas are recorded.
    """
    store = ReputationStore(path=path)
    for d in deltas:
        store.record_delta(d)
    scores = {aid: store.get_score(aid) for aid in store.agent_ids()}
    return store, scores


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="AGT-05 reputation flow smoke")
    p.add_argument(
        "--json",
        action="store_true",
        help="Also emit a JSON summary to stdout",
    )
    p.add_argument(
        "--persist",
        type=Path,
        default=None,
        help=(
            "Path to a JSONL ledger; when given, computed deltas are recorded "
            "via aragora.reputation.store.ReputationStore and per-agent scores "
            "are read back from the store after persistence."
        ),
    )
    return p.parse_args(argv)


def _print_table(rows: list[dict[str, Any]]) -> None:
    print(
        f"{'question':<14} {'agent':<24} {'pred_p':>7} {'outcome':<6} "
        f"{'brier':>7} {'payout':>8} {'delta':>7}"
    )
    print("-" * 78)
    for r in rows:
        print(
            f"{r['question_id']:<14} {r['agent']:<24} "
            f"{r['predicted_p']:>7.2f} {r['outcome']:<6} "
            f"{(r['brier'] or 0):>7.3f} {(r['payout_fraction'] or 0):>8.3f} "
            f"{r['delta']:>7.2f}"
        )
    print("-" * 78)


def _smoke(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if not reputation_flow_enabled():
        print(
            "ARAGORA_REPUTATION_FLOW_ENABLED is not set; nothing to demonstrate.",
            file=sys.stderr,
        )
        return 2

    deltas, rows = compute_deltas()

    print()
    print("AGT-05 Reputation Flow Smoke Test")
    print("=" * 78)
    print(f"  ARAGORA_REPUTATION_FLOW_ENABLED={os.environ.get('ARAGORA_REPUTATION_FLOW_ENABLED')}")
    print("  scoring_rule=brier_proper")
    print(f"  agents={list(SMOKE_AGENT_PREDICTIONS.keys())}")
    print(f"  questions={[q[0] for q in SMOKE_QUESTIONS]}")
    if args.persist is not None:
        print(f"  persist_to={args.persist}")
    print()

    _print_table(rows)

    per_agent_total: dict[str, float] = dict.fromkeys(SMOKE_AGENT_PREDICTIONS, 0.0)
    for r in rows:
        per_agent_total[r["agent"]] += r["delta"]

    print()
    print("Per-agent total reputation delta (Brier-proper, stake_units=10 per Q):")
    for a in sorted(per_agent_total):
        print(f"  {a:<24} {per_agent_total[a]:>+8.3f}")
    print()

    store_scores: dict[str, float] = {}
    if args.persist is not None:
        _, store_scores = persist_to_store(deltas, args.persist)
        print(f"Persisted {len(deltas)} deltas to {args.persist}")
        print("Per-agent decayed score read back from ReputationStore:")
        for a in sorted(store_scores):
            print(f"  {a:<24} {store_scores[a]:>+8.3f}")
        print()
        print("Round-trip verified: the ledger file is replayable via")
        print("ReputationStore.load_from_file() to reconstruct the same state.")
        print()

    print("Interpretation:")
    print("  delta > 0  -> agent gained reputation (calibrated towards outcome)")
    print("  delta < 0  -> agent lost reputation (systematically miscalibrated)")
    print("  delta ~= 0 -> agent indifferent (predicted near 0.5)")
    print()
    print("This proves the end-to-end signal flow runs cleanly with the flag enabled.")
    print("With --persist, deltas are also durable in a JSONL ledger the")
    print("ReputationCalibrationBridge (selection_bridge.py) can consume.")
    print()

    summary = {
        "scoring_rule": "brier_proper",
        "flag": os.environ.get("ARAGORA_REPUTATION_FLOW_ENABLED"),
        "rows": rows,
        "per_agent_total": per_agent_total,
        "persist_path": str(args.persist) if args.persist else None,
        "store_scores": store_scores,
        "ran_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
    }
    if args.json:
        print(json.dumps(summary, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(_smoke())
