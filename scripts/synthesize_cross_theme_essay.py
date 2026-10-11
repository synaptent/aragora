#!/usr/bin/env python3
"""
Synthesize Cross-Theme Essay from Quality Prose

Takes prose organized by theme and weaves it into a unified essay,
preserving the original prose while adding transitions and structure.

This script:
1. Reads quality prose organized by theme
2. Identifies the strongest passages for each theme
3. Creates an intellectual narrative arc across themes
4. Generates transitions that connect the ideas
5. Outputs a unified, publishable essay

Usage:
    python scripts/synthesize_cross_theme_essay.py \
        --input output/synthesis/quality_prose.json \
        --output output/synthesis/unified_essay.md \
        --title "AI, Evolution, and the Myth of Final States" \
        --target-words 50000
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict


# =============================================================================
# Theme Configuration
# =============================================================================


class ThemeConfig(TypedDict):
    name: str
    short_name: str
    narrative_position: int
    introduction: str
    keywords: list[str]


THEME_CONFIG: dict[str, ThemeConfig] = {
    "ai_risk_evolution": {
        "name": "AI Risk, Evolution, and Instrumental Convergence",
        "short_name": "AI & Evolution",
        "narrative_position": 1,  # Core argument
        "introduction": """
The debate about artificial intelligence tends toward false binaries: utopia or extinction,
alignment or doom, control or catastrophe. This framing obscures what may be the more
interesting and more likely outcome—a world of persistent instability, uneven adaptation,
and evolutionary dynamics that neither resolve nor destroy civilization.
""",
        "keywords": ["AI", "evolution", "instrumental", "convergence", "alignment", "optimization"],
    },
    "systems_complexity": {
        "name": "Systems Thinking, Complexity, and Equilibrium",
        "short_name": "Systems & Equilibrium",
        "narrative_position": 2,  # Supporting framework
        "introduction": """
To understand why final states are mythical, we need the language of complex systems—
attractors, basins, metastability, phase transitions. These concepts reveal that
stability is always local and temporary, and that the interesting question is not
whether systems change, but how they change and who bears the costs.
""",
        "keywords": ["system", "complexity", "equilibrium", "emergence", "stability"],
    },
    "religion_morality": {
        "name": "Religion, Morality, and Optimization Kernels",
        "short_name": "Religion & Optimization",
        "narrative_position": 3,  # Deepening insight
        "introduction": """
The same pattern—optimization kernels that shed their hosts—appears not just in AI
but in the oldest human institutions. Religion and morality are not primarily about
individual meaning; they are coordination technologies for patterns that use individuals
as substrates. Understanding this reframes both AI risk and human flourishing.
""",
        "keywords": ["religion", "morality", "meme", "coordination", "pattern"],
    },
    "intelligence_consciousness": {
        "name": "Intelligence, Substrate Independence, and Consciousness",
        "short_name": "Intelligence & Substrate",
        "narrative_position": 4,  # Philosophical foundation
        "introduction": """
If intelligence is pattern rather than substance, then the question of AI consciousness
becomes a question about functional organization, not carbon versus silicon. This has
profound implications for how we think about moral status, survival, and the continuity
of identity across transformations.
""",
        "keywords": ["intelligence", "substrate", "consciousness", "pattern", "mind"],
    },
    "rate_durability": {
        "name": "Rate/Durability Tradeoffs and Time Preference",
        "short_name": "Rate vs. Durability",
        "narrative_position": 5,  # Practical wisdom
        "introduction": """
Fast optimization burns through resources and creates fragile systems. Durable systems
require slack, redundancy, and the capacity to course-correct. This tradeoff—rate versus
durability—is perhaps the deepest constraint on any intelligent system, biological or artificial.
""",
        "keywords": ["rate", "durability", "tradeoff", "time", "preference", "slack"],
    },
    "art_aesthetics": {
        "name": "Art, Aesthetics, and Compressibility",
        "short_name": "Art & Complexity",
        "narrative_position": 6,  # Cultural application
        "introduction": """
The complexity and merit of a work of art can be understood through information theory—
but not reduced to it. Great art is not merely incompressible; it resonates with the
structure of human cognition in ways that create meaning beyond the information-theoretic
properties of the work itself.
""",
        "keywords": ["art", "aesthetic", "compressibility", "complexity", "beauty"],
    },
    "politics_legitimacy": {
        "name": "Politics, Legitimacy, and Violence",
        "short_name": "Politics & Legitimacy",
        "narrative_position": 7,  # Societal implications
        "introduction": """
The fundamental tension in political philosophy—between procedural and substantive
legitimacy—becomes acute in an age of AI-accelerated change. Democratic processes can
produce unjust outcomes, while just outcomes might require undemocratic processes.
There is no clean resolution, only ongoing negotiation.
""",
        "keywords": ["politics", "legitimacy", "violence", "democracy", "power"],
    },
}


# =============================================================================
# Prose Processing
# =============================================================================


@dataclass
class ThemedPassage:
    """A passage with theme and quality information."""

    text: str
    role: str
    conversation_title: str
    quality_score: float
    primary_theme: str
    word_count: int


def detect_theme(text: str) -> tuple[str, float]:
    """Detect the primary theme of a passage."""
    text_lower = text.lower()
    word_count = len(text.split())

    best_theme = "ai_risk_evolution"  # default
    best_score = 0.0

    for theme_id, config in THEME_CONFIG.items():
        matches = sum(1 for kw in config["keywords"] if kw.lower() in text_lower)
        score = matches / (word_count / 100) if word_count > 0 else 0
        if score > best_score:
            best_score = score
            best_theme = theme_id

    return best_theme, best_score


def load_quality_prose(path: Path) -> list[ThemedPassage]:
    """Load and classify quality prose by theme."""
    with open(path) as f:
        data = json.load(f)

    passages = []

    # Filter out code content
    code_keywords = [
        "def ",
        "class ",
        "import ",
        ".py",
        "function",
        "method",
        "error",
        "terminal",
        "git ",
        "npm",
        "armand@",
        "MacBook",
    ]

    for p in data["passages"]:
        text = p["text"]

        # Skip code
        if any(kw in text[:500].lower() for kw in code_keywords):
            continue

        # Skip low quality
        quality = p["quality_scores"]["overall"]
        if quality < 0.7:
            continue

        theme, theme_score = detect_theme(text)
        if theme_score < 0.1:
            continue

        passages.append(
            ThemedPassage(
                text=text,
                role=p["role"],
                conversation_title=p["conversation_title"],
                quality_score=quality,
                primary_theme=theme,
                word_count=len(text.split()),
            )
        )

    return passages


def organize_by_theme(passages: list[ThemedPassage]) -> dict[str, list[ThemedPassage]]:
    """Organize passages by theme, sorted by quality."""
    by_theme: dict[str, list[ThemedPassage]] = {}

    for theme_id in THEME_CONFIG:
        theme_passages = [p for p in passages if p.primary_theme == theme_id]
        theme_passages.sort(key=lambda p: -p.quality_score)
        by_theme[theme_id] = theme_passages

    return by_theme


# =============================================================================
# Essay Generation
# =============================================================================


def clean_passage_text(text: str) -> str:
    """Clean up passage text for essay inclusion."""
    # Remove markdown artifacts
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)  # Remove bold
    text = re.sub(r"---+", "", text)  # Remove horizontal rules

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return text


def generate_transition(from_theme: str, to_theme: str) -> str:
    """Generate a transition between themes."""
    from_name = THEME_CONFIG[from_theme]["short_name"]
    to_name = THEME_CONFIG[to_theme]["short_name"]

    transitions = {
        ("ai_risk_evolution", "systems_complexity"): """
This evolutionary framing naturally leads us to the language of complex systems.
If AI futures are better understood as evolutionary processes than as engineering
problems, we need tools that can handle emergence, feedback, and non-equilibrium dynamics.
""",
        ("systems_complexity", "religion_morality"): """
The systems perspective reveals something unexpected: the patterns we observe in AI
risk are not new. They recur throughout human history in the form of institutions
that outlive their founders—most notably, in religion and morality.
""",
        ("religion_morality", "intelligence_consciousness"): """
If morality and religion are coordination technologies for information patterns
that use humans as substrates, this raises a deeper question: what is the relationship
between intelligence, substrate, and identity?
""",
        ("intelligence_consciousness", "rate_durability"): """
The substrate independence of intelligence implies a kind of flexibility—but flexibility
is not free. There are deep tradeoffs between the speed of optimization and the
durability of the resulting systems.
""",
        ("rate_durability", "art_aesthetics"): """
These tradeoffs appear not just in engineering and biology but in culture itself.
The rate/durability tension shapes how we think about artistic value, complexity,
and what endures across generations.
""",
        ("art_aesthetics", "politics_legitimacy"): """
Art is not separate from politics—both involve questions of legitimacy, value, and
whose preferences should prevail. As AI transforms both domains, we need to think
carefully about the relationship between procedural and substantive legitimacy.
""",
    }

    key = (from_theme, to_theme)
    if key in transitions:
        return transitions[key].strip()

    # Generic transition
    return f"""
This brings us to a related but distinct question: the connection between
{from_name.lower()} and {to_name.lower()}. The themes are not separate;
they illuminate each other in unexpected ways.
""".strip()


def generate_unified_essay(
    by_theme: dict[str, list[ThemedPassage]],
    title: str,
    target_words: int = 50000,
    max_passages_per_theme: int = 8,
) -> str:
    """Generate a unified essay from themed passages."""

    lines = []

    # Title and metadata
    lines.append(f"# {title}")
    lines.append("")
    lines.append("*Synthesized from conversations across multiple AI systems*")
    lines.append(f"*Generated: {datetime.now().strftime('%B %d, %Y')}*")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Abstract
    lines.append("## Abstract")
    lines.append("")
    lines.append(
        """
This essay argues that debates about artificial intelligence are trapped in a false
binary between utopia and extinction. Drawing on evolutionary theory, complex systems,
philosophy of mind, and cultural analysis, it develops an alternative framework:
**metastable equilibrium without final states**. Intelligence—whether biological,
artificial, or institutional—does not resolve into permanent stability. It adapts,
transforms, and persists through ongoing tension. The future shaped by AI will not
be smooth or terminal; it will be uneven, turbulent, and relentlessly non-equilibrial.

The argument proceeds through seven interconnected themes: the evolutionary dynamics
of AI risk, the language of complex systems, the deep structure of religion and
morality, the substrate independence of intelligence, the tradeoff between rate and
durability, the information theory of art, and the politics of legitimacy in an
age of transformation.
""".strip()
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Table of contents
    lines.append("## Contents")
    lines.append("")
    sorted_themes = sorted(THEME_CONFIG.keys(), key=lambda t: THEME_CONFIG[t]["narrative_position"])
    for theme_id in sorted_themes:
        if by_theme.get(theme_id):
            name = THEME_CONFIG[theme_id]["name"]
            lines.append(f"- [{name}](#{theme_id})")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Introduction
    lines.append("## Introduction: Against the Fantasy of Final States")
    lines.append("")
    lines.append(
        """
Public discourse about artificial intelligence oscillates between two poles.
On one side is techno-optimism: the belief that sufficiently advanced, well-aligned
AI systems will solve humanity's hardest problems and usher in an era of abundance.
On the other is existential pessimism: the fear that misaligned superintelligence
will inevitably escape control and destroy civilization.

Both camps make the same structural error. They project a **final state** onto a
system that has never produced one.

Reality has no record of stable end-points. There has been no end of history, no
permanent equilibrium, no lasting stasis—only metastable regimes punctuated by
disruption, followed by renewed complexity. Artificial intelligence will not change
this fact. It will intensify it.

This essay develops that thesis across seven interconnected themes, drawing on
extended conversations with multiple AI systems. The goal is not to predict the
future but to equip the reader with concepts that make the actual dynamics legible—
concepts like instrumental convergence, optimization kernels, substrate independence,
rate/durability tradeoffs, and metastable equilibrium.

The structure follows a narrative arc: from the specific dynamics of AI risk, through
the general language of complex systems, to the deep patterns visible in religion
and consciousness, and finally to the practical implications for culture and politics.
""".strip()
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Each theme section
    total_words = 0
    words_per_theme = target_words // len(sorted_themes)

    prev_theme = None
    for theme_id in sorted_themes:
        passages = by_theme.get(theme_id, [])
        if not passages:
            continue

        config = THEME_CONFIG[theme_id]

        # Transition from previous theme
        if prev_theme:
            transition = generate_transition(prev_theme, theme_id)
            lines.append(f"*{transition}*")
            lines.append("")
            lines.append("---")
            lines.append("")

        # Section header
        lines.append(f"## {config['name']}")
        lines.append(f'<a name="{theme_id}"></a>')
        lines.append("")

        # Theme introduction
        lines.append(config["introduction"].strip())
        lines.append("")

        # Include best passages
        theme_word_count = 0
        for i, p in enumerate(passages[:max_passages_per_theme]):
            if theme_word_count > words_per_theme:
                break

            # Add passage with attribution
            if i > 0:
                lines.append("")
                lines.append("* * *")
                lines.append("")

            cleaned_text = clean_passage_text(p.text)
            lines.append(cleaned_text)

            # Attribution
            source = "conversation" if p.role == "user" else "AI synthesis"
            lines.append("")
            lines.append(f'*— From "{p.conversation_title}" ({source})*')

            theme_word_count += p.word_count
            total_words += p.word_count

        lines.append("")
        lines.append("---")
        lines.append("")

        prev_theme = theme_id

    # Conclusion
    lines.append("## Conclusion: Living Without Final States")
    lines.append("")
    lines.append(
        """
The choice is not between a clean AI utopia and total annihilation. Intelligence
does not abolish evolution; it accelerates it. Alignment does not end risk; it
shifts its form. Power does not eliminate adversaries; it constrains them.

The most realistic future is one of **uneven survival**: fortified zones of stability
surrounded by turbulence, persistent low-level threats punctuated by crises, and an
ongoing arms race between adaptation and disruption. This future will produce
extraordinary prosperity for some and profound suffering for others.

It is not a comforting vision. But it is a serious one—and far more plausible than
stories that promise either perfect safety or inevitable doom.

Civilization will not be saved by intelligence alone. It will be tested by it.

The question is not whether we can prevent all negative outcomes—we cannot. The
question is whether we can maintain enough coherence, enough slack, enough capacity
for course-correction to keep the system adapting. That is the real work of wisdom
in an age of artificial intelligence: not the pursuit of final states, but the
cultivation of resilient, adaptive, non-equilibrial flourishing.
""".strip()
    )
    lines.append("")
    lines.append("---")
    lines.append("")

    # Metadata
    lines.append("## About This Essay")
    lines.append("")
    lines.append(f"- **Total words:** ~{total_words:,}")
    lines.append(f"- **Themes covered:** {len([t for t in sorted_themes if by_theme.get(t)])}")
    lines.append(f"- **Source passages:** {sum(len(v) for v in by_theme.values())}")
    lines.append(f"- **Generated:** {datetime.now().isoformat()}")
    lines.append("")
    lines.append(
        "This essay was synthesized from extended conversations with Claude, GPT-4, and other AI systems, preserving the original prose while organizing it into a coherent intellectual arc."
    )

    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Synthesize cross-theme essay from quality prose",
    )
    parser.add_argument("--input", "-i", type=Path, required=True, help="Quality prose JSON file")
    parser.add_argument("--output", "-o", type=Path, required=True, help="Output markdown file")
    parser.add_argument(
        "--title",
        "-t",
        type=str,
        default="AI, Evolution, and the Myth of Final States",
        help="Essay title",
    )
    parser.add_argument("--target-words", type=int, default=50000, help="Target word count")
    parser.add_argument("--max-per-theme", type=int, default=8, help="Max passages per theme")

    args = parser.parse_args()

    print(f"Loading: {args.input}")
    passages = load_quality_prose(args.input)
    print(f"Loaded {len(passages)} quality passages")

    by_theme = organize_by_theme(passages)

    print("\nPassages by theme:")
    for theme_id, theme_passages in sorted(
        by_theme.items(), key=lambda x: THEME_CONFIG[x[0]]["narrative_position"]
    ):
        name = THEME_CONFIG[theme_id]["short_name"]
        words = sum(p.word_count for p in theme_passages)
        print(f"  {name}: {len(theme_passages)} passages, {words:,} words")

    print(f"\nGenerating essay: {args.title}")
    essay = generate_unified_essay(
        by_theme,
        title=args.title,
        target_words=args.target_words,
        max_passages_per_theme=args.max_per_theme,
    )

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(essay)

    word_count = len(essay.split())
    print(f"\nEssay written to: {args.output}")
    print(f"Total words: {word_count:,}")


if __name__ == "__main__":
    main()
