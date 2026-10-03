#!/usr/bin/env python3
"""
Knowledge-Grounded Debate with Freshness Weighting
====================================================

Runs a debate that retrieves relevant knowledge from the Knowledge Mound,
using composite scoring (importance + freshness + recency) to surface the
most current and relevant context for agents.

Usage:
    python examples/enterprise/knowledge_debate.py --demo
    python examples/enterprise/knowledge_debate.py          # Requires API keys
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def run_demo():
    """Simulate a knowledge-grounded debate."""
    print("=== Knowledge-Grounded Debate (Demo) ===\n")

    task = "Should we migrate our payment service from REST to gRPC?"
    print(f"Task: {task}\n")

    # Simulate KM retrieval with freshness scores
    print("--- Knowledge Retrieval (freshness-weighted) ---")
    knowledge = [
        {
            "title": "gRPC Migration Post-Mortem (Auth Service)",
            "importance": 0.9,
            "freshness": 0.95,
            "recency": 0.88,
            "composite": 0.9 * 0.5 + 0.95 * 0.3 + 0.88 * 0.2,
        },
        {
            "title": "REST API Performance Benchmarks Q4",
            "importance": 0.85,
            "freshness": 0.7,
            "recency": 0.6,
            "composite": 0.85 * 0.5 + 0.7 * 0.3 + 0.6 * 0.2,
        },
        {
            "title": "Team gRPC Readiness Survey",
            "importance": 0.7,
            "freshness": 0.9,
            "recency": 0.95,
            "composite": 0.7 * 0.5 + 0.9 * 0.3 + 0.95 * 0.2,
        },
    ]

    for item in sorted(knowledge, key=lambda x: x["composite"], reverse=True):
        print(f"  [{item['composite']:.2f}] {item['title']}")
        print(
            f"         importance={item['importance']:.1f}  "
            f"freshness={item['freshness']:.1f}  recency={item['recency']:.1f}"
        )

    print("\n--- Debate (2 rounds, knowledge-enriched) ---")
    time.sleep(0.3)
    print("\n[claude-proposer]:")
    print(
        "  Based on the auth service migration post-mortem, gRPC reduced latency 40%"
        " but required 3-month client SDK migration. For payments, the latency win"
        " matters but client disruption is higher risk."
    )
    time.sleep(0.2)
    print("\n[gpt4-critic]:")
    print(
        "  The Q4 benchmarks show REST is adequate at current load. gRPC benefits"
        " only manifest above 5K req/s. Team readiness survey shows 60% unfamiliar"
        " with protobuf -- training cost is non-trivial."
    )
    time.sleep(0.2)
    print("\n[gemini-synthesizer]:")
    print(
        "  RECOMMENDATION: Adopt gRPC for internal service-to-service calls only."
        " Keep REST for external-facing payment APIs. Phase migration over 2 sprints"
        " starting with lowest-traffic endpoints. This matches the auth service"
        " post-mortem lesson of incremental rollout."
    )

    print("\n--- Result ---")
    print("Consensus: Yes (78% confidence)")
    print("Knowledge items used: 3 (freshness-weighted)")
    return True


async def run_live():
    """Run with real agents and Knowledge Mound."""
    from aragora import Arena, DebateProtocol, Environment
    from aragora.agents.base import create_agent
    from aragora.knowledge.mound.api import KnowledgeMound

    km = KnowledgeMound()
    agents = []
    for agent_type, role in [("anthropic-api", "proposer"), ("openai-api", "critic")]:
        try:
            agents.append(
                create_agent(model_type=agent_type, name=f"{agent_type}-{role}", role=role)
            )
        except Exception:
            pass

    if len(agents) < 2:
        print("Need at least 2 agents. Set API keys or use --demo.")
        return None

    env = Environment(task="Should we migrate our payment service from REST to gRPC?")
    protocol = DebateProtocol(rounds=2, consensus="majority")
    arena = Arena(
        env,
        agents,
        protocol,
        knowledge_mound=km,
        enable_knowledge_retrieval=True,
    )
    result = await arena.run()
    print(f"Consensus: {'Yes' if result.consensus_reached else 'No'}")
    print(f"Answer: {result.final_answer[:500]}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Knowledge-Grounded Debate")
    parser.add_argument("--demo", action="store_true", help="Demo mode (no API keys)")
    args = parser.parse_args()

    if args.demo:
        sys.exit(0 if run_demo() else 1)
    else:
        sys.exit(0 if asyncio.run(run_live()) else 1)
