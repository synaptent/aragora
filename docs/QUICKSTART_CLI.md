# Your First Debate in 10 Minutes

Get Aragora running and see your first multi-agent debate in under 10 minutes.

## Prerequisites

- Python 3.11 or later
- At least one API key: `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
  (skip if using the zero-config demo)

## Quick Install

**From PyPI:**

```bash
pip install aragora
```

**From source:**

```bash
git clone https://github.com/your-org/aragora.git
cd aragora
pip install -e .
```

Verify the install:

```bash
aragora --version
```

## Zero-Config Demo (No API Keys Required)

Run an offline debate with mock agents to see how Aragora works before committing any API keys:

```bash
aragora quickstart --demo
```

What you will see:

- A three-round debate between two mock agents on a sample decision topic
- Per-round proposals, critiques, and revisions printed to the terminal
- A consensus summary with a confidence score at the end
- A decision receipt (JSON) saved to `./aragora_receipts/` showing the full audit trail

The demo uses locally generated responses and makes no external API calls. It is safe to run in restricted environments.

## First Real Debate

Set your API key, then run the interactive quickstart:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
aragora quickstart
```

The quickstart wizard will:

1. Detect your available API keys and select agents automatically
2. Prompt you for a decision topic (or use the built-in default)
3. Run a three-round debate with live streaming output
4. Print the winning position, confidence score, and dissenting views
5. Save a cryptographically signed receipt to `./aragora_receipts/`

To use OpenAI instead:

```bash
export OPENAI_API_KEY=sk-...
aragora quickstart
```

To use both providers together (heterogeneous consensus):

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
aragora quickstart
```

## Start the Server

Launch the full HTTP and WebSocket API server:

```bash
aragora serve --api-port 8080
```

The server starts in roughly 15 seconds. Once running:

- Interactive API explorer: http://localhost:8080/api/v2/docs
- Health check: http://localhost:8080/health
- WebSocket stream: `ws://localhost:8080/ws`

Start a debate via the REST API:

```bash
curl -X POST http://localhost:8080/api/v1/debate \
  -H "Content-Type: application/json" \
  -d '{"task": "Should we adopt GraphQL or REST?", "rounds": 3}'
```

## Python SDK Quick Example

```python
import asyncio
from aragora import Arena, Environment, DebateProtocol

async def main():
    env = Environment(task="Should we use microservices or a monolith?")
    protocol = DebateProtocol(rounds=3, consensus="majority")
    arena = Arena(env, agents=["claude", "gpt4"], protocol=protocol)

    result = await arena.run()

    print(result.winner)      # winning position summary
    print(result.confidence)  # float 0.0–1.0
    print(result.receipt)     # audit trail dict

asyncio.run(main())
```

The `result` object also exposes:

| Attribute | Type | Description |
|---|---|---|
| `result.winner` | str | Winning position |
| `result.confidence` | float | Consensus confidence (0–1) |
| `result.rounds` | list | Full per-round transcripts |
| `result.receipt` | dict | Signed audit receipt |
| `result.dissents` | list | Minority positions |

## Next Steps

| Resource | Description |
|---|---|
| `docs/EXTENDED_README.md` | Full technical reference covering all five pillars |
| `docs/SDK_GUIDE.md` | Python and TypeScript SDK usage with advanced examples |
| `docs/api/API_REFERENCE.md` | Complete REST API documentation (3,000+ operations) |
