"""Run a demo adversarial debate with zero API keys.

Usage::

    python -m aragora_debate
    python -m aragora_debate --topic "Should we use Kubernetes?"
    python -m aragora_debate --topic "Kafka vs RabbitMQ?" --rounds 2
    python -m aragora_debate --trickster --convergence
"""

from __future__ import annotations

import argparse
import asyncio
from importlib import metadata
import sys

from aragora_debate.styled_mock import StyledMockAgent
from aragora_debate.arena import Arena
from aragora_debate.types import Agent, DebateConfig

# ---------------------------------------------------------------------------
# ANSI helpers (no external deps)
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_COLORS = {
    "blue": "\033[34m",
    "green": "\033[32m",
    "red": "\033[31m",
    "yellow": "\033[33m",
    "cyan": "\033[36m",
    "magenta": "\033[35m",
}

_AGENT_COLORS = ["blue", "red", "yellow", "green", "cyan", "magenta"]


def _c(text: str, color: str, bold: bool = False) -> str:
    prefix = _COLORS.get(color, "")
    if bold:
        prefix = _BOLD + prefix
    return f"{prefix}{text}{_RESET}"


def _header(text: str) -> str:
    return f"\n{_BOLD}{text}{_RESET}\n" + "\u2500" * len(text)


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------


async def _run_demo(  # noqa: C901 - Keep the demo's ordered presentation in one place.
    topic: str,
    rounds: int,
    enable_trickster: bool = False,
    enable_convergence: bool = False,
) -> None:
    agents: list[Agent] = [
        StyledMockAgent("analyst", style="supportive"),
        StyledMockAgent("critic", style="critical"),
        StyledMockAgent("moderator", style="balanced"),
    ]
    color_map = {a.name: _AGENT_COLORS[i] for i, a in enumerate(agents)}

    print(_c("aragora-debate", "cyan", bold=True))
    print(_c("Adversarial multi-model debate engine", "cyan"))
    print()
    print(f"  Topic:   {_BOLD}{topic}{_RESET}")
    print(f"  Agents:  {', '.join(_c(a.name, color_map[a.name]) for a in agents)}")
    print(f"  Rounds:  {rounds}")
    print("  Method:  majority consensus")
    if enable_trickster:
        print(f"  Trickster: {_c('enabled', 'yellow')}")
    if enable_convergence:
        print(f"  Convergence: {_c('enabled', 'yellow')}")

    config = DebateConfig(
        rounds=rounds,
        early_stopping=True,
        enable_trickster=enable_trickster,
        enable_convergence=enable_convergence,
    )

    def on_event(event: object) -> None:
        """Print live event updates."""
        if hasattr(event, "event_type"):
            etype = (
                event.event_type.value
                if hasattr(event.event_type, "value")
                else str(event.event_type)
            )
            if etype in ("trickster_intervention", "convergence_detected"):
                print(f"  {_c(f'[{etype}]', 'magenta')}", end="")
                if hasattr(event, "data") and event.data:
                    detail = event.data.get("type", "") or f"sim={event.data.get('similarity', '')}"
                    print(f" {_DIM}{detail}{_RESET}")
                else:
                    print()

    arena = Arena(
        question=topic,
        agents=agents,
        config=config,
        on_event=on_event if (enable_trickster or enable_convergence) else None,
    )
    result = await arena.run()

    # --- Show round-by-round highlights ---
    shown_rounds: set[int] = set()
    for msg in result.messages:
        if msg.round not in shown_rounds and msg.role == "proposer":
            shown_rounds.add(msg.round)
            print(_header(f"Round {msg.round}"))

        if msg.role == "proposer":
            agent_label = _c(msg.agent, color_map.get(msg.agent, "cyan"), bold=True)
            print(f"\n  {agent_label} proposes:")
            content = msg.content[:300]
            if len(msg.content) > 300:
                content += "..."
            for line in content.split("\n"):
                print(f"    {_DIM}{line}{_RESET}")

        if msg.role == "trickster":
            print(f"\n  {_c('trickster', 'magenta', bold=True)} challenges:")
            for line in msg.content[:200].split("\n"):
                print(f"    {_c(line, 'magenta')}")

    # --- Critiques summary ---
    if result.critiques:
        print(_header("Critiques"))
        for crit in result.critiques[:6]:
            src = _c(crit.agent, color_map.get(crit.agent, "cyan"))
            tgt = _c(crit.target_agent, color_map.get(crit.target_agent, "cyan"))
            print(f"  {src} \u2192 {tgt}  (severity {crit.severity}/10)")
            for issue in crit.issues[:2]:
                print(f"    \u2022 {_DIM}{issue}{_RESET}")

    # --- Votes ---
    if result.votes:
        print(_header("Votes"))
        for vote in result.votes:
            voter = _c(vote.agent, color_map.get(vote.agent, "cyan"))
            chosen = _c(vote.choice, color_map.get(vote.choice, "cyan"), bold=True)
            print(f"  {voter} \u2192 {chosen}  (confidence {vote.confidence:.0%})")

    # --- Analysis ---
    if result.trickster_interventions > 0 or result.convergence_detected:
        print(_header("Analysis"))
        if result.trickster_interventions > 0:
            print(f"  Trickster interventions: {result.trickster_interventions}")
        if result.convergence_detected:
            print(f"  Convergence detected (similarity: {result.final_similarity:.2f})")

    # --- Receipt ---
    print(_header("Decision Receipt"))
    if result.receipt:
        print()
        print(result.receipt.to_markdown())
    else:
        print(f"  Status: {result.status}")
        print(f"  Confidence: {result.confidence:.0%}")

    print()
    status_color = "green" if result.consensus_reached else "yellow"
    print(
        _c(
            f"\u2713 Debate complete in {result.duration_seconds:.2f}s "
            f"({result.rounds_used} round{'s' if result.rounds_used != 1 else ''})",
            status_color,
        )
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    try:
        package_version = metadata.version("aragora-debate")
    except metadata.PackageNotFoundError:
        package_version = "0.0.0+source"
    parser = argparse.ArgumentParser(
        prog="python -m aragora_debate",
        description="Run an adversarial multi-agent debate (no API keys needed)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"aragora-debate {package_version}",
    )
    parser.add_argument(
        "--topic",
        default="Should we use microservices or a monolith?",
        help="The question to debate (default: microservices vs monolith)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=2,
        help="Number of debate rounds (default: 2)",
    )
    parser.add_argument(
        "--trickster",
        action="store_true",
        help="Enable hollow-consensus detection and challenge injection",
    )
    parser.add_argument(
        "--convergence",
        action="store_true",
        help="Enable convergence tracking across rounds",
    )
    args = parser.parse_args()

    if not args.topic or not args.topic.strip():
        print(
            "Error: The --topic argument cannot be empty.",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(
        _run_demo(
            args.topic,
            args.rounds,
            enable_trickster=args.trickster,
            enable_convergence=args.convergence,
        )
    )


if __name__ == "__main__":
    main()
