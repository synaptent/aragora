"""Hook for the gauntlet-backed evaluation of trained specialist models.

``aragora.training`` sits in the domain layer, so it cannot import the gauntlet
(application layer) that stress-tests a freshly trained specialist. The gauntlet
registers a factory for its evaluation runner here, and
:meth:`~aragora.training.specialist_models.SpecialistTrainingPipeline.complete_training`
builds the runner through :func:`create_specialist_evaluator` and scores its result
with :func:`elo_rating_for_verdict` and :func:`win_rate_from_vulnerability`.

The registration is declared under the ``aragora.training_evaluators`` entry-point
group in aragora's ``pyproject.toml``. The first lookup that finds nothing registered
runs those declarations once per process, so a process that only imports
``aragora.training`` still reaches the gauntlet. When nothing is registered after
that, :func:`create_specialist_evaluator` raises
:class:`SpecialistEvaluatorNotRegisteredError`. Registering again replaces the
previous factory instead of adding a second one.
"""

from __future__ import annotations

from typing import Any, Protocol

from aragora.utils.declared_registrations import DeclaredRegistrations

TRAINING_EVALUATORS_ENTRY_POINT_GROUP = "aragora.training_evaluators"

ELO_DEFAULTS: tuple[int, int, int] = (1200, 900, 1050)
"""ELO rating of a specialist whose evaluation verdict is PASS, FAIL, or anything else."""


class SpecialistEvaluator(Protocol):
    """Runs one adversarial evaluation and returns a result carrying ``verdict``,
    ``robustness_score`` and ``vulnerability_rate``."""

    async def run(self, input_content: str, context: str = "") -> Any: ...


class SpecialistEvaluatorFactory(Protocol):
    """Builds the evaluator for a specialist trained on ``vertical``."""

    def __call__(self, *, vertical: str) -> SpecialistEvaluator: ...


class SpecialistEvaluatorNotRegisteredError(LookupError):
    """No factory is registered for the specialist-model evaluator."""


_factory: SpecialistEvaluatorFactory | None = None
_declared_registrations = DeclaredRegistrations(TRAINING_EVALUATORS_ENTRY_POINT_GROUP)


def register_specialist_evaluator(factory: SpecialistEvaluatorFactory) -> None:
    """Register ``factory`` as the builder of the specialist-model evaluator."""
    global _factory
    _factory = factory


def create_specialist_evaluator(*, vertical: str) -> SpecialistEvaluator:
    """Build a new evaluator for ``vertical`` with the registered factory."""
    if _factory is None:
        _declared_registrations.load()
    if _factory is None:
        raise SpecialistEvaluatorNotRegisteredError(
            "No specialist-model evaluator registered; the gauntlet registers one through "
            f"the {TRAINING_EVALUATORS_ENTRY_POINT_GROUP!r} entry point"
        )
    return _factory(vertical=vertical)


def elo_rating_for_verdict(verdict: str) -> int:
    """ELO rating of a specialist from its evaluation verdict (see :data:`ELO_DEFAULTS`)."""
    passed, failed, other = ELO_DEFAULTS
    if verdict == "PASS":
        return passed
    if verdict == "FAIL":
        return failed
    return other


def win_rate_from_vulnerability(vulnerability_rate: float) -> float:
    """Win rate of a specialist: the share of adversarial probes it withstood."""
    return 1.0 - vulnerability_rate


__all__ = [
    "ELO_DEFAULTS",
    "SpecialistEvaluator",
    "SpecialistEvaluatorFactory",
    "SpecialistEvaluatorNotRegisteredError",
    "TRAINING_EVALUATORS_ENTRY_POINT_GROUP",
    "create_specialist_evaluator",
    "elo_rating_for_verdict",
    "register_specialist_evaluator",
    "win_rate_from_vulnerability",
]
