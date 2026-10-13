"""Reliability-aware budget scheduling for heterogeneous debate agents."""

from __future__ import annotations

__all__ = [
    "ReliabilityScheduler",
]

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from aragora.debate.epistemic_outcomes import EpistemicOutcome


@dataclass
class ReliabilityScheduler:
    """Compute per-agent budget shares from calibration and settled outcomes."""

    calibration_weight: float = 0.7
    settlement_weight: float = 0.3
    min_share: float = 0.05

    def score_from_calibration(self, calibration: dict[str, Any]) -> float:
        """Convert calibration metrics into [0, 1] reliability score."""
        brier = float(calibration.get("brier_score", 0.5))
        ece = float(calibration.get("ece", 0.25))
        predictions = int(calibration.get("prediction_count", 0))

        brier_component = max(0.0, min(1.0, 1.0 - brier))
        ece_component = max(0.0, min(1.0, 1.0 - ece))
        confidence_boost = min(1.0, predictions / 50.0)
        return (0.45 * brier_component) + (0.35 * ece_component) + (0.20 * confidence_boost)

    def build_settlement_deltas(
        self,
        outcomes: Iterable[EpistemicOutcome],
    ) -> dict[str, float]:
        """Aggregate resolved confidence deltas by participant agent."""
        deltas: dict[str, float] = defaultdict(float)
        for outcome in outcomes:
            if outcome.status != "resolved":
                continue
            participants = (
                outcome.metadata.get("participants") if isinstance(outcome.metadata, dict) else []
            )
            if not isinstance(participants, list):
                continue
            for agent in participants:
                if not isinstance(agent, str) or not agent.strip():
                    continue
                deltas[agent] += float(outcome.confidence_delta)
        return dict(deltas)

    def allocate_budget(
        self,
        agents: list[str],
        calibration_map: dict[str, dict[str, Any]],
        settlement_deltas: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Allocate normalized budget shares across agents."""
        if not agents:
            return {}

        settlement_deltas = settlement_deltas or {}
        if settlement_deltas:
            max_abs = max(abs(v) for v in settlement_deltas.values()) or 1.0
        else:
            max_abs = 1.0

        raw_scores: dict[str, float] = {}
        for agent in agents:
            calibration_score = self.score_from_calibration(calibration_map.get(agent, {}))
            settlement_component = settlement_deltas.get(agent, 0.0) / max_abs
            settlement_score = 0.5 + (0.5 * max(-1.0, min(1.0, settlement_component)))
            combined = (
                self.calibration_weight * calibration_score
                + self.settlement_weight * settlement_score
            )
            raw_scores[agent] = max(0.001, combined)

        total = sum(raw_scores.values()) or 1.0
        shares = {agent: raw_scores[agent] / total for agent in agents}

        if self.min_share <= 0:
            return shares

        min_share = min(self.min_share, 1.0 / len(agents))
        deficit = 0.0
        for agent in agents:
            if shares[agent] < min_share:
                deficit += min_share - shares[agent]
                shares[agent] = min_share

        if deficit <= 0:
            return shares

        donors = [agent for agent in agents if shares[agent] > min_share]
        donor_pool = sum(shares[a] - min_share for a in donors)
        if donor_pool <= 0:
            equal = 1.0 / len(agents)
            return dict.fromkeys(agents, equal)

        for agent in donors:
            available = shares[agent] - min_share
            reduction = deficit * (available / donor_pool)
            shares[agent] -= reduction

        normalization = sum(shares.values()) or 1.0
        return {agent: shares[agent] / normalization for agent in agents}
