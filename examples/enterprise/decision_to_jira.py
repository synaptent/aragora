#!/usr/bin/env python3
"""
Debate -> DecisionPlan -> Jira/Linear Issue Creation
=====================================================

Shows the full pipeline: agents debate a question, produce a DecisionPlan
with implementation tasks, and the DecisionBridge automatically creates
Jira or Linear issues from those tasks.

Usage:
    python examples/enterprise/decision_to_jira.py --demo
    python examples/enterprise/decision_to_jira.py          # Requires API keys + Jira
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
    """Simulate the debate -> decision plan -> issue creation pipeline."""
    print("=== Decision Plan -> Jira Pipeline (Demo) ===\n")

    task = "Design a customer notification preference center"
    print(f"Task: {task}\n")

    # Phase 1: Debate
    print("--- Phase 1: Multi-Agent Debate ---")
    time.sleep(0.3)
    print("[claude-proposer]: Build a React preference center with per-channel toggles")
    print("                   (email, SMS, push, in-app) and frequency controls.")
    time.sleep(0.2)
    print("[gpt4-critic]:     Add GDPR consent tracking and audit log. Consider")
    print("                   granular topic-level preferences, not just channel-level.")
    time.sleep(0.2)
    print("[synthesis]:       Hybrid: channel + topic matrix with consent audit trail.\n")

    # Phase 2: DecisionPlan generation
    print("--- Phase 2: DecisionPlan Generated ---")
    tasks = [
        ("Create preference_center DB schema", "Backend", "High"),
        ("Build preference API endpoints", "Backend", "High"),
        ("Implement React preference matrix UI", "Frontend", "Medium"),
        ("Add GDPR consent audit logging", "Compliance", "High"),
        ("Write E2E tests for preference flows", "QA", "Medium"),
    ]
    print(f"Plan: {len(tasks)} implementation tasks\n")
    for title, area, priority in tasks:
        print(f"  [{priority:6s}] [{area:10s}] {title}")

    # Phase 3: DecisionBridge -> Jira
    print("\n--- Phase 3: DecisionBridge -> Jira ---")
    time.sleep(0.3)
    for i, (title, area, _) in enumerate(tasks, 1):
        jira_key = f"PREF-{100 + i}"
        print(f"  Created {jira_key}: [Aragora] {title}")
        time.sleep(0.1)

    print(f"\nCreated {len(tasks)} Jira issues in project PREF")
    print("Bridge result: jira_issues=5, linear_issues=0, n8n_triggered=false")
    return True


async def run_live():
    """Run with real agents and DecisionBridge."""
    from aragora import Arena, DebateProtocol, Environment
    from aragora.agents.base import create_agent
    from aragora.integrations.decision_bridge import DecisionBridge

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

    env = Environment(task="Design a customer notification preference center")
    protocol = DebateProtocol(rounds=2, consensus="majority")

    arena = Arena(
        env,
        agents,
        protocol,
        enable_post_debate_workflow=True,
    )
    result = await arena.run()

    print(f"Consensus: {'Yes' if result.consensus_reached else 'No'}")
    print(f"Answer: {result.final_answer[:300]}")

    # Route decision plan to Jira
    if hasattr(result, "decision_plan") and result.decision_plan:
        bridge = DecisionBridge(default_targets=["jira"])
        bridge_result = await bridge.handle_decision_plan(result.decision_plan)
        print(f"\nBridge result: {bridge_result.to_dict()}")
    else:
        print("\nNo decision plan generated (enable post-debate workflow for this)")

    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Decision Plan -> Jira Pipeline")
    parser.add_argument("--demo", action="store_true", help="Demo mode (no API keys)")
    args = parser.parse_args()

    if args.demo:
        sys.exit(0 if run_demo() else 1)
    else:
        sys.exit(0 if asyncio.run(run_live()) else 1)
