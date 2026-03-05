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


async def main():
    env = Environment(task="Should we adopt a microservices architecture for our monolith?")
    protocol = DebateProtocol(rounds=2, consensus="majority")
    arena = Arena(env, agents=None, protocol=protocol)
    result = await arena.run()
    print(f"Verdict: {result.verdict}")
    print(f"Consensus: {result.consensus_text[:200]}")
    print(f"Confidence: {result.confidence:.0%}")


if __name__ == "__main__":
    asyncio.run(main())
