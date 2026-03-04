---
title: Getting Started
description: Choose your path to get started with Aragora — from zero-dependency debates to full platform deployment
sidebar_position: 1
---

# Getting Started

Pick the path that matches your goal. Each one gets you to a working debate in under 5 minutes.

## Choose Your Path

| Goal | Package | Install | Time |
|------|---------|---------|------|
| **Embed debates in my code** | `aragora-debate` | `pip install aragora-debate` | 2 min |
| **Call the Aragora REST API** | `aragora-sdk` / `@aragora/sdk` | `pip install aragora-sdk` | 5 min |
| **AI code review on PRs** | GitHub Action | Copy workflow YAML | 5 min |
| **Self-host the platform** | Docker or source | `docker compose up` | 5 min |

## Fastest: Run a Debate in 3 Lines

No server. No API keys. Zero dependencies.

```bash
pip install aragora-debate
```

```python
import asyncio
from aragora_debate import Debate, create_agent

async def main():
    debate = Debate(topic="Should we use Kubernetes or VMs?", rounds=2)
    debate.add_agent(create_agent("mock", name="analyst",
        proposal="K8s enables auto-scaling and self-healing."))
    debate.add_agent(create_agent("mock", name="skeptic",
        proposal="VMs are simpler; our team lacks K8s expertise."))
    result = await debate.run()
    print(f"Consensus: {result.consensus_reached} ({result.confidence:.0%})")

asyncio.run(main())
```

To use real LLM providers:

```bash
pip install aragora-debate[anthropic]  # or [openai], [all]
export ANTHROPIC_API_KEY=sk-ant-...
```

## Guides in This Section

- **[Introduction](/docs/getting-started/introduction)** — What Aragora is and why multi-agent debate works
- **[Installation](/docs/getting-started/installation)** — All installation methods (Docker, pip, source)
- **[Environment Setup](/docs/getting-started/environment)** — API keys and configuration
- **[Your First Debate](/docs/getting-started/first-debate)** — Step-by-step tutorial with REST API
- **[Quickstart: AI Code Review](/docs/getting-started/quickstart)** — GitHub Action setup in 5 minutes
- **[Configuration](/docs/getting-started/configuration)** — Customize agents, rounds, and consensus

## Next Steps

After your first debate:

- [SDK Guide](/docs/guides/sdk) — Full Python and TypeScript SDK reference
- [Core Concepts: Debates](/docs/core-concepts/debates) — How multi-agent debate works under the hood
- [Examples](https://github.com/synaptent/aragora/tree/main/examples) — 30+ runnable examples for every use case
