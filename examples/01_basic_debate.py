"""
Basic Debate Example
====================
Run a structured multi-agent debate on any question.

Usage:
    export ANTHROPIC_API_KEY=your-key
    python examples/01_basic_debate.py
"""

import asyncio

from aragora import Arena, Environment, DebateProtocol
from aragora.agents.base import create_agent


async def main():
    # Build a small panel of agents (each tries its API key; skips if unavailable)
    agent_specs = [
        ("anthropic-api", "proposer"),
        ("openai-api", "critic"),
        ("grok", "synthesizer"),
    ]
    agents = []
    for model_type, role in agent_specs:
        try:
            agents.append(
                create_agent(model_type=model_type, name=f"{model_type}-{role}", role=role)
            )  # type: ignore[arg-type]
        except Exception:
            pass

    if len(agents) < 2:
        raise RuntimeError("Need at least 2 agents. Set ANTHROPIC_API_KEY and/or OPENAI_API_KEY.")

    env = Environment(task="Should we adopt a microservices architecture for our monolith?")
    protocol = DebateProtocol(rounds=2, consensus="majority")
    arena = Arena(env, agents=agents, protocol=protocol)
    result = await arena.run()
    print(f"Answer: {result.final_answer[:300]}")
    print(f"Confidence: {result.confidence:.0%}")


if __name__ == "__main__":
    asyncio.run(main())
