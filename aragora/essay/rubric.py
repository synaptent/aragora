"""EssayScore dataclass, rubric loading, and LLM response parsing."""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from aragora.essay.prompts import build_evaluation_prompt

logger = logging.getLogger(__name__)

# ── Default dimension weights (must sum to 1.0) ──────────────────────────────

_DEFAULT_WEIGHTS: dict[str, float] = {
    "thesis_clarity": 0.20,
    "argument_coherence": 0.20,
    "evidence_grounding": 0.15,
    "rhetorical_force": 0.15,
    "concision": 0.10,
    "factual_accuracy": 0.10,
    "originality": 0.10,
}

_DIMENSION_FIELDS = list(_DEFAULT_WEIGHTS.keys())

_RUBRICS_DIR = Path(__file__).parent / "rubrics"

# ── JSON extraction regex ─────────────────────────────────────────────────────

_JSON_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


# ── Dataclass ─────────────────────────────────────────────────────────────────


@dataclass
class EssayScore:
    """Score across 7 essay quality dimensions with a weighted composite."""

    # Dimensions (0-1)
    thesis_clarity: float = 0.0
    argument_coherence: float = 0.0
    evidence_grounding: float = 0.0
    rhetorical_force: float = 0.0
    concision: float = 0.0
    factual_accuracy: float = 0.0
    originality: float = 0.0

    # Weighted composite
    overall: float = 0.0

    # Evaluator attribution
    evaluator_model: str = ""

    # Qualitative feedback
    severity_notes: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    weakest_paragraph: str = ""
    strongest_paragraph: str = ""
    factual_claims_to_verify: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if any(getattr(self, dim) > 0 for dim in _DIMENSION_FIELDS):
            self.compute_overall(_DEFAULT_WEIGHTS)

    def compute_overall(self, weights: dict[str, float]) -> None:
        """(Re)calculate weighted composite from *weights*."""
        self.overall = sum(getattr(self, dim) * weights.get(dim, 0.0) for dim in _DIMENSION_FIELDS)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary of all fields."""
        return {f.name: getattr(self, f.name) for f in fields(self)}


# ── Parsing ───────────────────────────────────────────────────────────────────


def _normalize_score(value: Any) -> float:
    """Coerce a model-provided score field into a safe float."""
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return score if math.isfinite(score) else 0.0


def _normalize_string_list(value: Any) -> list[str]:
    """Coerce model output into a list of strings without splitting scalars."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list | tuple):
        return [str(item) for item in value if item is not None]
    return []


def parse_score_response(text: str) -> EssayScore:
    """Extract the first JSON object from *text* and map it to an EssayScore.

    Returns an empty ``EssayScore`` when parsing fails.
    """
    match = _JSON_RE.search(text)
    if not match:
        return EssayScore()

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return EssayScore()
    if not isinstance(data, dict):
        return EssayScore()

    kwargs: dict[str, Any] = {}
    for dim in _DIMENSION_FIELDS:
        kwargs[dim] = _normalize_score(data.get(dim, 0.0))

    kwargs["severity_notes"] = _normalize_string_list(data.get("severity_notes", []))
    kwargs["suggestions"] = _normalize_string_list(data.get("suggestions", []))
    kwargs["weakest_paragraph"] = str(data.get("weakest_paragraph", ""))
    kwargs["strongest_paragraph"] = str(data.get("strongest_paragraph", ""))
    kwargs["factual_claims_to_verify"] = _normalize_string_list(
        data.get("factual_claims_to_verify", [])
    )
    kwargs["evaluator_model"] = str(data.get("evaluator_model", ""))

    return EssayScore(**kwargs)


# ── Rubric loading ────────────────────────────────────────────────────────────


def load_rubric(path: str | None = None) -> dict[str, Any]:
    """Load a YAML rubric.

    When *path* is ``None``, the built-in ``default.yaml`` is used.
    Returns a dict with ``"name"``, ``"weights"``, and ``"quality_threshold"``.
    """
    if path is None:
        path = str(_RUBRICS_DIR / "default.yaml")

    with open(path) as fh:
        rubric: dict[str, Any] = yaml.safe_load(fh)

    return rubric


# ── Evaluation ────────────────────────────────────────────────────────────────


async def evaluate_essay(
    essay_text: str,
    judge_agent: Any,
    *,
    rubric: dict[str, Any] | None = None,
    context: str | None = None,
    model_name: str = "",
) -> EssayScore:
    """Evaluate *essay_text* using *judge_agent* and return an ``EssayScore``.

    Parameters
    ----------
    essay_text:
        The essay to evaluate.
    judge_agent:
        Any object with an async ``.generate(prompt)`` method.
    rubric:
        Optional rubric dict (from ``load_rubric``). Defaults to the built-in
        default rubric.
    context:
        Optional additional context to include in the prompt.
    model_name:
        Optional model identifier to record on the returned score for
        evaluator attribution.
    """
    if rubric is None:
        rubric = load_rubric()

    prompt = build_evaluation_prompt(essay_text, rubric, context, model_name=model_name)

    try:
        response = await judge_agent.generate(prompt)
    except Exception:
        logger.exception("Judge agent failed during essay evaluation")
        return EssayScore()

    score = parse_score_response(response)
    score.compute_overall(rubric.get("weights", _DEFAULT_WEIGHTS))
    score.evaluator_model = model_name
    return score
