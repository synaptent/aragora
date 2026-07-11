"""Reusable epistemic question batteries for intake and deliberation.

These batteries are intentionally small and compositional: they provide named
question patterns that existing intake, prompt-engine, and mode surfaces can
reuse without creating a new orchestration framework.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionBattery:
    """One reusable epistemic question pattern."""

    name: str
    persona_role: str
    question: str
    why_it_matters: str
    dimension: str
    options: tuple[str, ...] = ()
    persona_prompt: str = ""


BATTERIES: dict[str, QuestionBattery] = {
    "outsider": QuestionBattery(
        name="outsider",
        persona_role="Outsider",
        question=(
            "What do you need from me to judge this the way an outside customer, "
            "auditor, or competitor would?"
        ),
        why_it_matters=(
            "Outside standards expose missing context, hidden incentives, and proof gaps "
            "that an internal team can normalize away."
        ),
        dimension="epistemic:outsider",
        options=(
            "Name the external audience and their decision standard",
            "State the artifact they would inspect",
            "Proceed only with internal criteria",
        ),
        persona_prompt=(
            "Adopt an outsider stance. Ask what an external customer, auditor, "
            "operator, competitor, or future maintainer would need to trust the decision."
        ),
    ),
    "falsifier": QuestionBattery(
        name="falsifier",
        persona_role="Falsifier",
        question="What would make this wrong, and where should we look for that observation?",
        why_it_matters=(
            "A decision that names its falsifier can be checked later instead of becoming "
            "an unfalsifiable preference."
        ),
        dimension="epistemic:falsifier",
        options=(
            "Define the falsifying observation and source",
            "Define a check-by date",
            "No practical falsifier exists",
        ),
        persona_prompt=(
            "Adopt a falsifier stance. Convert confident claims into observable failure "
            "conditions, including who or what system can check them."
        ),
    ),
    "assumption_surfacer": QuestionBattery(
        name="assumption_surfacer",
        persona_role="Assumption-Surfacer",
        question="What did we assume that would change the decision if false?",
        why_it_matters=(
            "Load-bearing assumptions are often cheaper to inspect than the whole plan."
        ),
        dimension="epistemic:assumption_surfacer",
        options=(
            "List the accepted assumptions",
            "Pick the highest-risk assumption to validate",
            "No material assumptions identified",
        ),
        persona_prompt=(
            "Adopt an assumption-surfacer stance. Separate observations from assumptions "
            "and identify which assumptions are load-bearing."
        ),
    ),
    "deleter": QuestionBattery(
        name="deleter",
        persona_role="Deleter",
        question="Should this be done, or should we stop, remove, or narrow something instead?",
        why_it_matters=(
            "Deletion pressure prevents solution accretion and keeps the work tied to a "
            "real decision advantage."
        ),
        dimension="epistemic:deleter",
        options=(
            "Do it as requested",
            "Narrow it",
            "Remove or stop something instead",
        ),
        persona_prompt=(
            "Adopt a deleter stance. Prefer removing, narrowing, or stopping work when "
            "that produces a clearer or safer outcome than adding more machinery."
        ),
    ),
    "stranger_test": QuestionBattery(
        name="stranger_test",
        persona_role="Stranger-Test",
        question="Could a capable stranger verify this decision without private context?",
        why_it_matters=(
            "A stranger-testable decision leaves an evidence trail that survives handoff."
        ),
        dimension="epistemic:stranger_test",
        options=(
            "Add public proof",
            "Add local/repo-visible proof",
            "Accept private-context risk",
        ),
        persona_prompt=(
            "Adopt a stranger-test stance. Ask whether an uninvolved but capable reviewer "
            "can reproduce the decision from the visible artifacts."
        ),
    ),
    "moat_audit": QuestionBattery(
        name="moat_audit",
        persona_role="Moat-Audit",
        question="What does this prove that a competitor could not fake with a demo?",
        why_it_matters=(
            "A moat audit distinguishes durable capability from presentation-only progress."
        ),
        dimension="epistemic:moat_audit",
        options=(
            "Evidence of durable capability exists",
            "Only demo-level proof exists",
            "Moat is not relevant here",
        ),
        persona_prompt=(
            "Adopt a moat-audit stance. Distinguish durable, hard-to-fake capability "
            "from surface-level demos or copied phrasing."
        ),
    ),
}

BATTERY_NAMES: tuple[str, ...] = tuple(BATTERIES)
CORE_INTAKE_BATTERIES: tuple[str, ...] = (
    "outsider",
    "falsifier",
    "assumption_surfacer",
    "deleter",
)

_VAGUE_MARKERS = (
    "better",
    "improve",
    "strategy",
    "product",
    "enterprise",
    "customers",
    "launch",
    "decide",
    "should",
    "valuable",
    "growth",
)

_SPECIFIC_MARKERS = (
    "::",
    " line ",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".md",
    "timeout=",
    "test_",
)


def get_question_battery(name: str) -> QuestionBattery:
    """Return a named question battery, raising ``KeyError`` for unknown names."""
    return BATTERIES[name]


def iter_question_batteries(
    names: tuple[str, ...] | list[str] | None = None,
) -> list[QuestionBattery]:
    """Return batteries in stable registry order."""
    selected = names or BATTERY_NAMES
    return [get_question_battery(name) for name in selected]


def should_offer_intake_battery(prompt: str) -> bool:
    """Decide whether broad epistemic intake questions are likely useful."""
    text = " ".join(prompt.lower().split())
    if not text:
        return False
    if any(marker in text for marker in _SPECIFIC_MARKERS):
        return False
    return any(marker in text for marker in _VAGUE_MARKERS) or len(text.split()) <= 6


def build_intake_battery_questions(
    prompt: str,
    *,
    max_questions: int = 4,
    names: tuple[str, ...] | list[str] | None = None,
) -> list[QuestionBattery]:
    """Return high-impact intake batteries for vague or underspecified prompts."""
    if not should_offer_intake_battery(prompt):
        return []
    selected = names or CORE_INTAKE_BATTERIES
    return iter_question_batteries(tuple(selected))[:max_questions]
