#!/usr/bin/env python3
"""
Benchmark adaptive stability detection (placeholder until detector lands).

Usage:
    python scripts/benchmarks/bench_adaptive_stopping.py --iterations 200
"""

from __future__ import annotations

import argparse
import random
import statistics
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StabilityBenchmarkResult:
    iterations: int
    stability_scores: list[float] = field(default_factory=list)
    times_ms: list[float] = field(default_factory=list)

    @property
    def mean_ms(self) -> float:
        return statistics.mean(self.times_ms) if self.times_ms else 0.0

    @property
    def mean_stability(self) -> float:
        return statistics.mean(self.stability_scores) if self.stability_scores else 0.0


def _fallback_stability(votes: list[str]) -> float:
    if not votes:
        return 0.0
    counts: dict[str, int] = {}
    for vote in votes:
        counts[vote] = counts.get(vote, 0) + 1
    return max(counts.values()) / len(votes)


def _get_detector() -> Any:
    try:
        from aragora.debate.stability_detector import BetaBinomialStabilityDetector

        return BetaBinomialStabilityDetector()
    except Exception:
        return None


def _require_positive_int(value: int, *, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")


def run_benchmark(iterations: int, votes_per_round: int) -> StabilityBenchmarkResult:
    _require_positive_int(iterations, label="iterations")
    _require_positive_int(votes_per_round, label="votes_per_round")

    rng = random.Random(42)
    result = StabilityBenchmarkResult(iterations=iterations)
    detector = _get_detector()

    for _ in range(iterations):
        votes = [rng.choice(["yes", "no", "abstain"]) for _ in range(votes_per_round)]
        start = time.perf_counter()
        agreement = _fallback_stability(votes)
        if detector and hasattr(detector, "calculate_stability"):
            stability_raw = detector.calculate_stability([agreement])
            stability = (
                float(stability_raw.stability)
                if hasattr(stability_raw, "stability")
                else float(stability_raw)
            )
        else:
            stability = agreement
        elapsed = (time.perf_counter() - start) * 1000
        result.times_ms.append(elapsed)
        result.stability_scores.append(stability)

    return result


def _positive_int(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark adaptive stability detection")
    parser.add_argument("--iterations", type=_positive_int, default=200)
    parser.add_argument("--votes-per-round", type=_positive_int, default=7)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = run_benchmark(args.iterations, args.votes_per_round)
    print("Adaptive Stability Benchmark")
    print(f"Iterations: {result.iterations}")
    print(f"Mean stability score: {result.mean_stability:.4f}")
    print(f"Mean latency: {result.mean_ms:.4f} ms")
    if _get_detector() is None:
        print("Note: BetaBinomialStabilityDetector not implemented yet; using fallback.")


if __name__ == "__main__":
    main()
