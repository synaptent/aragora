# Python SDK Quickstart

> **Note:** For the comprehensive Python SDK guide with advanced features and streaming, see **[Python Quickstart Guide](guides/python-quickstart.md)**.
>
> This page provides a minimal 5-minute quickstart using the `aragora-sdk` package.

Get started with Aragora in under 5 minutes.

## Installation

```bash
pip install aragora-sdk
```

> **Version note:** PyPI releases are cut deliberately and may trail the
> repository (decoupled cadence, recorded in #9234 — see
> [SDK_GUIDE.md](SDK_GUIDE.md#release-cadence-recorded-operator-policy-2026-07-16)).
> Install from source if you need repo-tip behavior.

## Basic Usage

The published 2.8.0 wheel includes synchronous and asynchronous clients. This
quickstart uses the asynchronous client in offline demo mode, so it runs without
an API key or server. Omit `demo=True` and provide `base_url` to call a running
Aragora deployment.

```python
import asyncio
from aragora_sdk import AragoraAsyncClient

async def main():
    async with AragoraAsyncClient(demo=True) as client:
        debate = await client.debates.create(
            task="Should we use microservices or monolith?",
            agents=["demo"],
        )
        print(f"Debate: {debate['debate_id']}")
        print(f"Conclusion: {debate['consensus']['conclusion']}")

asyncio.run(main())
```

## Full Example

```python
import asyncio
from aragora_sdk import AragoraAsyncClient

async def main():
    async with AragoraAsyncClient(demo=True) as client:
        # 1. Create a debate
        created = await client.debates.create(
            task="Design a rate limiter for our API",
            agents=["demo"],
            max_rounds=3,
        )
        debate_id = created["debate_id"]
        print(f"Created debate: {debate_id}")

        # 2. List recent debates
        recent = await client.debates.list(limit=5)
        print(f"Recent debates: {len(recent.get('debates', []))}")

        # 3. Inspect available agents
        available = await client.agents.list()
        print(f"Available agents: {len(available.get('agents', []))}")

asyncio.run(main())
```

## Key APIs

| API | Description |
|-----|-------------|
| `await client.debates.create()` | Create a debate |
| `await client.debates.list()` | List recent debates |
| `await client.agents.list()` | List available agents |

These calls are checked against the committed
[`aragora-sdk` 2.8.0 released-surface manifest](reference/sdk_released_surface_2.8.0.json).
The repository-tip SDK can expose additional methods before the next PyPI
release; install `./sdk/python` when following repository-tip API references.
