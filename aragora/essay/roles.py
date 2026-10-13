"""Essay-specific agent roles and round phases for the essay refinement pipeline."""

from __future__ import annotations

from aragora.protocols.debate import RoundPhase

__all__ = [
    "ESSAY_AGENT_ROLES",
    "ESSAY_ROUND_PHASES",
]

# ---------------------------------------------------------------------------
# Round phases: 8 phases (0-indexed) for structured essay critique and revision
# ---------------------------------------------------------------------------

ESSAY_ROUND_PHASES: list[RoundPhase] = [
    RoundPhase(
        number=0,
        name="Idea Extraction",
        description="Extract and catalogue the core ideas, claims, and arguments from the essay",
        focus="Key claims, central thesis, supporting arguments, implicit assumptions",
        cognitive_mode="Analyst",
    ),
    RoundPhase(
        number=1,
        name="Parallel Drafting",
        description="Generate alternative drafts and framings of the core argument",
        focus="Competing narratives, alternative structures, rhetorical approaches",
        cognitive_mode="Writer",
    ),
    RoundPhase(
        number=2,
        name="Structural Critique",
        description="Challenge the essay's organisation, coherence, and logical flow",
        focus="Argument structure, paragraph transitions, logical gaps, coherence",
        cognitive_mode="Skeptic",
    ),
    RoundPhase(
        number=3,
        name="Factual Audit",
        description="Verify claims against evidence and flag unsupported assertions",
        focus="Factual accuracy, citation quality, unsupported claims, data integrity",
        cognitive_mode="Fact-Checker",
    ),
    RoundPhase(
        number=4,
        name="Devil's Advocate",
        description="Argue the strongest opposing position to stress-test the essay's thesis",
        focus="Counter-arguments, edge cases, unintended consequences, opposing evidence",
        cognitive_mode="Devil's Advocate",
    ),
    RoundPhase(
        number=5,
        name="Synthesis",
        description="Integrate critique feedback into a unified, improved argument",
        focus="Emerging consensus, reconciled positions, strengthened thesis, coherent narrative",
        cognitive_mode="Synthesizer",
    ),
    RoundPhase(
        number=6,
        name="Style Polish",
        description="Refine language, tone, and prose for clarity and impact",
        focus="Word choice, sentence rhythm, tone consistency, concision, readability",
        cognitive_mode="Editor",
    ),
    RoundPhase(
        number=7,
        name="Final Judgment",
        description="Render a final verdict on essay quality and approve the polished draft",
        focus="Overall quality, rubric compliance, readiness for publication, final score",
        cognitive_mode="Judge",
    ),
]

# ---------------------------------------------------------------------------
# Agent roles: maps role names to debate role type and description
# ---------------------------------------------------------------------------

ESSAY_AGENT_ROLES: dict[str, dict[str, str]] = {
    "drafter": {
        "role": "proposer",
        "description": (
            "Generates the initial essay draft and alternative formulations of the argument"
        ),
    },
    "critic": {
        "role": "critic",
        "description": ("Challenges the essay's structure, logic, and rhetorical effectiveness"),
    },
    "fact_checker": {
        "role": "critic",
        "description": (
            "Audits factual claims, verifies evidence, and flags unsupported assertions"
        ),
    },
    "devils_advocate": {
        "role": "critic",
        "description": (
            "Argues the strongest opposing position to test the resilience of the thesis"
        ),
    },
    "synthesizer": {
        "role": "synthesizer",
        "description": (
            "Integrates diverse feedback into a coherent, improved version of the essay"
        ),
    },
    "editor": {
        "role": "synthesizer",
        "description": (
            "Polishes prose style, tone, and language for clarity and rhetorical impact"
        ),
    },
    "judge": {
        "role": "critic",
        "description": (
            "Renders the final verdict on essay quality and approves the polished draft"
        ),
    },
}
