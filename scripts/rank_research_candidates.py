#!/usr/bin/env python3
"""Rank research-intake candidates via a MetaPlanner debate.

Reads ``### N. <title>`` candidates from a dated triage brief (the
``## Candidates`` section of ``docs/research/*-triage.md``), feeds them to
``MetaPlanner.prioritize_work`` as first-class ``candidate_goals`` (rendered
uncapped into the debate topic), and writes the ranked goals plus the debate
DecisionReceipt under ``.aragora/research_intake/``.

Dogfooding contract: research intake goes through the same adversarial
vetting the product sells. The receipt path printed at the end is meant to be
linked from every issue filed for an adopted candidate.

Usage:
    python scripts/rank_research_candidates.py docs/research/2026-08-26-x-bookmarks-triage.md \
        --objective "Rank these externally sourced candidates by expected impact" \
        [--quick] [--max-goals 10] [--output-dir .aragora/research_intake]

``--quick`` skips the debate (heuristic ranking, no LLM calls, no receipt) —
useful as a smoke test of the parsing and plumbing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_CANDIDATE_HEADING = re.compile(r"^### \d+\.\s+(?P<title>.+?)\s*$")
_SECTION_END = re.compile(r"^## ")


def extract_candidates(brief_path: Path) -> list[str]:
    """Extract '### N. <title>' candidates from the '## Candidates' section.

    Each candidate is returned as ``<title>: <first body paragraph>`` so the
    debate sees the claim, not just the label. Parsing stops at the next
    top-level section (e.g. '## Candidates that do not survive').
    """
    lines = brief_path.read_text(encoding="utf-8").splitlines()
    candidates: list[str] = []
    in_section = False
    title: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal title, body
        if title:
            paragraph = " ".join(part.strip() for part in body if part.strip())
            candidates.append(f"{title}: {paragraph}" if paragraph else title)
        title, body = None, []

    for line in lines:
        if line.strip() == "## Candidates":
            in_section = True
            continue
        if not in_section:
            continue
        if _SECTION_END.match(line):
            break
        match = _CANDIDATE_HEADING.match(line)
        if match:
            flush()
            title = match.group("title")
        elif title is not None and not line.startswith("**Verdict"):
            body.append(line)
    flush()
    return candidates


async def rank(
    candidates: list[str],
    objective: str,
    max_goals: int,
    quick: bool,
    agents: list[str] | None = None,
) -> tuple[list[dict], object | None]:
    from aragora.nomic.meta_planner import (
        MetaPlanner,
        MetaPlannerConfig,
        PlanningContext,
    )

    config = MetaPlannerConfig(max_goals=max_goals, quick_mode=quick)
    if agents:
        config.agents = agents
    planner = MetaPlanner(config=config)
    goals = await planner.prioritize_work(
        objective=objective,
        context=PlanningContext(candidate_goals=candidates),
    )
    return [goal.to_dict() for goal in goals], planner.last_receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("brief", type=Path, help="Path to the triage brief markdown")
    parser.add_argument(
        "--objective",
        default=(
            "Rank these externally sourced research candidates by expected "
            "impact on the decision-integrity roadmap; reject any that do not "
            "survive scrutiny"
        ),
    )
    parser.add_argument("--max-goals", type=int, default=10)
    parser.add_argument("--quick", action="store_true", help="Heuristic only, no debate")
    parser.add_argument(
        "--agents",
        default=None,
        help="Comma-separated agent types for the debate (default: MetaPlanner defaults)",
    )
    parser.add_argument("--output-dir", type=Path, default=Path(".aragora/research_intake"))
    args = parser.parse_args()

    if not args.brief.is_file():
        print(f"error: brief not found: {args.brief}", file=sys.stderr)
        return 2
    candidates = extract_candidates(args.brief)
    if not candidates:
        print(f"error: no '### N. <title>' candidates found in {args.brief}", file=sys.stderr)
        return 2
    print(f"extracted {len(candidates)} candidates from {args.brief}")

    agents = [a.strip() for a in args.agents.split(",")] if args.agents else None
    goals, receipt = asyncio.run(
        rank(candidates, args.objective, args.max_goals, args.quick, agents)
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt_path: Path | None = None
    if receipt is not None:
        receipt_path = args.output_dir / f"ranking-receipt-{stamp}.json"
        receipt_path.write_text(json.dumps(receipt.to_dict(), indent=2), encoding="utf-8")

    result_path = args.output_dir / f"ranking-{stamp}.json"
    result_path.write_text(
        json.dumps(
            {
                "brief": str(args.brief),
                "objective": args.objective,
                "mode": "quick" if args.quick else "debate",
                "candidates": candidates,
                "ranked_goals": goals,
                "receipt_path": str(receipt_path) if receipt_path else None,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"ranked {len(goals)} goals -> {result_path}")
    if receipt_path:
        print(f"receipt -> {receipt_path}")
    elif not args.quick:
        print("warning: no receipt produced (debate may have fallen back to heuristics)")
    for goal in goals:
        print(f"  {goal['priority']}. [{goal['estimated_impact']}] {goal['description'][:100]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
