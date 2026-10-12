"""Registers the gauntlet as the evaluator of trained specialist models.

See :mod:`aragora.training.evaluation_protocols`, whose scoring rules
(:data:`ELO_DEFAULTS`, :func:`win_rate_from_vulnerability`) turn the runner's result
into the specialist's metrics and are re-exported here next to the runner settings.
aragora's ``pyproject.toml`` declares :func:`register_training_adapter` under the
``aragora.training_evaluators`` entry-point group.
"""

from __future__ import annotations

from aragora.gauntlet.config import GauntletConfig
from aragora.gauntlet.runner import GauntletRunner
from aragora.training.evaluation_protocols import (
    ELO_DEFAULTS,
    register_specialist_evaluator,
    win_rate_from_vulnerability,
)

SPECIALIST_EVALUATION_AGENTS = ("claude", "gpt-4")


def build_gauntlet_config(*, vertical: str) -> GauntletConfig:
    """Gauntlet settings for evaluating one specialist trained on ``vertical``."""
    return GauntletConfig(
        domain=vertical,
        agents=list(SPECIALIST_EVALUATION_AGENTS),
        run_scenario_matrix=False,  # Skip scenarios for faster eval
    )


def build_specialist_evaluator(*, vertical: str) -> GauntletRunner:
    """Build the gauntlet runner that evaluates one trained specialist."""
    return GauntletRunner(config=build_gauntlet_config(vertical=vertical))


def register_training_adapter() -> None:
    """Register :func:`build_specialist_evaluator`; safe to call more than once."""
    register_specialist_evaluator(build_specialist_evaluator)


__all__ = [
    "ELO_DEFAULTS",
    "SPECIALIST_EVALUATION_AGENTS",
    "build_gauntlet_config",
    "build_specialist_evaluator",
    "register_training_adapter",
    "win_rate_from_vulnerability",
]
