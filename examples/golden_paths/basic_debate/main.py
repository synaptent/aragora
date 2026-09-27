#!/usr/bin/env python3
"""
Golden Path 1: Basic Multi-Agent Debate
========================================

Three agents with different debate styles (supportive, critical, balanced)
debate a technical question. The debate runs through proposal, critique, and
voting phases, then produces a decision receipt with consensus information.

No API keys required -- uses StyledMockAgent for fully offline execution.

Usage:
    python examples/golden_paths/basic_debate/main.py

Expected runtime: <5 seconds
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running as a standalone script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from aragora_debate import Arena, DebateConfig, StyledMockAgent


async def main() -> None:
    # ----------------------------------------------------------------
    # Step 1: Define agents with distinct debate styles
    # ----------------------------------------------------------------
    # StyledMockAgent provides realistic canned responses based on style.
    # "supportive" endorses proposals, "critical" challenges them,
    # "balanced" weighs tradeoffs.  No API keys needed.
    agents = [
        StyledMockAgent("architect", style="supportive"),
        StyledMockAgent("security-reviewer", style="critical"),
        StyledMockAgent("tech-lead", style="balanced"),
    ]

    # ----------------------------------------------------------------
    # Step 2: Configure the debate
    # ----------------------------------------------------------------
    config = DebateConfig(
        rounds=2,  # Two rounds: propose -> critique -> vote each
        consensus_method="majority",
        early_stopping=True,  # Stop if consensus is reached in round 1
    )

    # ----------------------------------------------------------------
    # Step 3: Create the Arena and run
    # ----------------------------------------------------------------
    arena = Arena(
        question=(
            "Should we migrate our monolithic API to microservices? "
            "Consider team size (12 engineers), current scale (5K req/s), "
            "and a 6-month delivery window."
        ),
        agents=agents,
        config=config,
    )

    print("=" * 64)
    print("  Aragora Golden Path: Basic Multi-Agent Debate")
    print("=" * 64)
    print()
    print(f"Question: {arena.question}")
    print(f"Agents:   {', '.join(a.name for a in agents)}")
    print(f"Rounds:   {config.rounds}")
    print()

    result = await arena.run()

    # ----------------------------------------------------------------
    # Step 4: Inspect the result
    # ----------------------------------------------------------------
    print("--- Debate Result ---")
    print(f"Status:    {result.status}")
    print(f"Rounds:    {result.rounds_used}")
    print(f"Consensus: {'Reached' if result.consensus_reached else 'Not reached'}")
    print(f"Confidence: {result.confidence:.0%}")
    print(f"Duration:  {result.duration_seconds:.2f}s")
    print()

    # Show each agent's proposal (truncated for readability)
    print("--- Proposals ---")
    for agent_name, proposal_text in result.proposals.items():
        short = proposal_text[:120].rstrip() + ("..." if len(proposal_text) > 120 else "")
        print(f"  [{agent_name}] {short}")
    print()

    # Show critiques
    if result.critiques:
        print(f"--- Critiques ({len(result.critiques)}) ---")
        for critique in result.critiques[:4]:
            issues_str = "; ".join(critique.issues[:2])
            print(f"  [{critique.agent} -> {critique.target_agent}] {issues_str}")
        print()

    # Show votes
    if result.votes:
        print("--- Votes ---")
        for vote in result.votes:
            print(
                f"  [{vote.agent}] voted for {vote.choice} "
                f"(confidence: {vote.confidence:.0%}) -- {vote.reasoning[:80]}"
            )
        print()

    # Show dissenting views
    if result.dissenting_views:
        print("--- Dissenting Views ---")
        for view in result.dissenting_views:
            print(f"  {view}")
        print()

    # ----------------------------------------------------------------
    # Step 5: Print the decision receipt
    # ----------------------------------------------------------------
    if result.receipt:
        print("--- Decision Receipt ---")
        print(result.receipt.to_markdown())
    else:
        print("(No receipt generated)")

    print()
    print("Done. The full DebateResult object contains all messages, critiques,")
    print("votes, and the cryptographic decision receipt for audit purposes.")


if __name__ == "__main__":
    asyncio.run(main())
