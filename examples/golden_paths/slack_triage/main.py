#!/usr/bin/env python3
"""
Golden Path 2: Slack Inbox Auto-Triage
=======================================

Demonstrates how Aragora's InboxDebateTrigger evaluates incoming messages,
detects critical priority, and spawns a mini-debate to produce a triage
recommendation with a decision receipt.

This simulates the flow without a live Slack connection:
  1. A mock Slack webhook payload arrives
  2. InboxDebateTrigger evaluates priority and rate limits
  3. A quick 2-round debate analyzes the message
  4. The result includes a recommendation and audit trail

No API keys or Slack workspace required.

Usage:
    python examples/golden_paths/slack_triage/main.py

Expected runtime: <5 seconds
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow running as a standalone script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from aragora_debate import Arena, DebateConfig, StyledMockAgent


# ----------------------------------------------------------------
# Mock Slack webhook payloads (simulating incoming messages)
# ----------------------------------------------------------------

SAMPLE_MESSAGES = [
    {
        "id": "msg-001",
        "channel": "#incidents",
        "sender": "monitoring-bot",
        "subject": "CRITICAL: Database connection pool exhausted",
        "body": (
            "Production PostgreSQL connection pool at 100% capacity. "
            "P99 latency spiked to 12s. Active connections: 200/200. "
            "Affected services: user-api, billing-api, search-api. "
            "Auto-scaling has not resolved the issue. Immediate action required."
        ),
        "priority": "critical",
    },
    {
        "id": "msg-002",
        "channel": "#team-updates",
        "sender": "project-manager",
        "subject": "Sprint planning moved to Thursday",
        "body": (
            "Hi team, sprint planning has been moved from Wednesday to Thursday "
            "at 2pm. Please update your calendars. Agenda will be shared tomorrow."
        ),
        "priority": "low",
    },
    {
        "id": "msg-003",
        "channel": "#security",
        "sender": "security-scanner",
        "subject": "URGENT: Exposed API key detected in public repository",
        "body": (
            "An active API key for the payment-gateway service was found in a "
            "public GitHub repository (commit sha: abc123). The key has been "
            "active for 3 hours. Recommend immediate rotation and audit of "
            "recent transactions."
        ),
        "priority": "critical",
    },
]


# ----------------------------------------------------------------
# Triage logic
# ----------------------------------------------------------------


def classify_priority(message: dict) -> str:
    """Simple priority classifier based on keywords and source channel."""
    body = (message.get("subject", "") + " " + message.get("body", "")).lower()
    channel = message.get("channel", "")

    # Critical indicators
    critical_keywords = [
        "critical",
        "urgent",
        "down",
        "outage",
        "exhausted",
        "exposed",
        "breach",
        "security",
        "immediate action",
    ]
    if any(kw in body for kw in critical_keywords) or channel in ("#incidents", "#security"):
        return "critical"

    # High priority indicators
    high_keywords = ["error", "failed", "degraded", "spike", "alert"]
    if any(kw in body for kw in high_keywords):
        return "high"

    return "low"


async def run_triage_debate(message: dict) -> dict:
    """Run a quick multi-agent debate to analyze a critical message."""
    # Create agents with roles suited for triage:
    #   - An incident responder who focuses on immediate actions
    #   - A risk analyst who evaluates severity and blast radius
    #   - A coordinator who synthesizes a recommendation
    agents = [
        StyledMockAgent(
            "incident-responder",
            style="supportive",
            proposal=(
                f"Immediate action required for: {message['subject']}. "
                f"Based on the alert from {message['sender']}, I recommend: "
                "1) Acknowledge the incident and notify the on-call team. "
                "2) Begin mitigation steps within 15 minutes. "
                "3) Open a war room channel for coordination. "
                "Impact assessment: HIGH -- multiple services affected."
            ),
        ),
        StyledMockAgent(
            "risk-analyst",
            style="critical",
            proposal=(
                f"Severity assessment for: {message['subject']}. "
                "Before escalating, we need to verify: "
                "1) Is this a genuine incident or a monitoring false positive? "
                "2) What is the actual customer impact (error rates, SLO breach)? "
                "3) Are there dependent systems that could cascade? "
                "Recommend: Verify impact metrics before full escalation."
            ),
        ),
        StyledMockAgent(
            "triage-coordinator",
            style="balanced",
            proposal=(
                f"Triage recommendation for: {message['subject']}. "
                "Balancing urgency with accuracy: "
                "1) Immediately page the on-call engineer (SLA: 5 min response). "
                "2) Simultaneously verify metrics dashboards for confirmation. "
                "3) If confirmed within 10 minutes, escalate to P1 incident. "
                "4) If metrics normal, downgrade to monitoring alert. "
                "This approach ensures fast response without false escalation."
            ),
        ),
    ]

    config = DebateConfig(
        rounds=2,
        consensus_method="majority",
        early_stopping=True,
    )

    arena = Arena(
        question=(
            f"Triage this incoming alert and recommend action: "
            f"'{message['subject']}' from {message['sender']} in {message['channel']}.\n\n"
            f"Details: {message['body']}"
        ),
        agents=agents,
        config=config,
    )

    result = await arena.run()

    return {
        "message_id": message["id"],
        "subject": message["subject"],
        "detected_priority": classify_priority(message),
        "debate_consensus": result.consensus_reached,
        "confidence": result.confidence,
        "recommendation": result.final_answer[:300],
        "agents_involved": result.participants,
        "rounds_used": result.rounds_used,
        "receipt_id": result.receipt.receipt_id if result.receipt else None,
        "verdict": result.receipt.verdict.value if result.receipt else None,
    }


# ----------------------------------------------------------------
# Main
# ----------------------------------------------------------------


async def main() -> None:
    print("=" * 64)
    print("  Aragora Golden Path: Slack Inbox Auto-Triage")
    print("=" * 64)
    print()

    for message in SAMPLE_MESSAGES:
        priority = classify_priority(message)
        print(f"[{message['channel']}] {message['subject']}")
        print(f"  From: {message['sender']}")
        print(f"  Priority: {priority.upper()}")

        if priority == "critical":
            print("  -> Triggering triage debate...")
            triage = await run_triage_debate(message)

            print(
                f"  -> Consensus: {'Yes' if triage['debate_consensus'] else 'No'} "
                f"({triage['confidence']:.0%} confidence)"
            )
            print(f"  -> Verdict: {triage['verdict']}")
            print(f"  -> Receipt: {triage['receipt_id']}")
            print(f"  -> Agents: {', '.join(triage['agents_involved'])}")
            print(f"  -> Recommendation: {triage['recommendation'][:120]}...")
        else:
            print("  -> Skipped (below critical threshold)")

        print()

    print("-" * 64)
    print("Triage complete. Critical messages were analyzed by a 3-agent")
    print("debate panel. Each triage decision has an audit-ready receipt.")
    print()
    print("In production, this flow is triggered by InboxDebateTrigger when")
    print("a Slack webhook delivers a message classified as critical. The")
    print("trigger includes rate limiting (4/hour) and per-message cooldown")
    print("(10 min) to prevent debate spam.")


if __name__ == "__main__":
    asyncio.run(main())
