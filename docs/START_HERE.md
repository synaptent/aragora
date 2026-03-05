# Start Here

**New to Aragora? This is the only page you need.** Pick the path that matches your goal and follow the 5-line quickstart.

---

## Which package do I need?

```
                          What do you want to do?
                                  |
              +-------------------+-------------------+
              |                   |                   |
     Run debates in          Use the Aragora      Self-host or
     my Python code            REST API           contribute
              |                   |                   |
    pip install aragora-debate  Python or TS SDK    Clone the repo
       (zero dependencies,     (API client for      (3,000+ modules,
        works offline)         a running server)    full platform)
```

| Goal | Package | Install |
|------|---------|---------|
| **Run debates in my code** | `aragora-debate` | `pip install aragora-debate` |
| **Call the Aragora API (Python)** | `aragora-sdk` | `pip install aragora-sdk` |
| **Call the Aragora API (TypeScript)** | `@aragora/sdk` | `npm install @aragora/sdk` |
| **Self-host the platform** | `aragora` | Docker Compose (see below) |
| **Contribute to Aragora** | source | `git clone` + `pip install -e .` |

---

## Path 1: Run debates in my code

Best for: trying adversarial AI debate, CI/CD integration, applications that embed debate logic directly.

**Zero dependencies. No API keys. Works offline.**

```bash
pip install aragora-debate
```

```python
import asyncio
from aragora_debate import Debate, create_agent

async def main():
    debate = Debate(topic="Should we use Kubernetes or stay on VMs?", rounds=2)
    debate.add_agent(create_agent("mock", name="analyst", proposal="Kubernetes enables auto-scaling and self-healing. For a team already using containers, the migration cost is justified by operational savings within 6 months."))
    debate.add_agent(create_agent("mock", name="skeptic", proposal="VMs are simpler and our team lacks Kubernetes expertise. The learning curve and added complexity outweigh the scaling benefits at our current scale of 50 requests/second."))
    debate.add_agent(create_agent("mock", name="pragmatist", proposal="Start with managed Kubernetes (EKS/GKE) to reduce operational burden. Migrate the stateless services first, keep databases on VMs until the team builds confidence."))
    result = await debate.run()
    print(f"Consensus: {result.consensus_reached} ({result.confidence:.0%} confidence)")
    print(f"Receipt: {result.receipt.receipt_id}")

asyncio.run(main())
```

To use real LLM providers instead of mock agents:

```bash
pip install aragora-debate[anthropic]  # or [openai], [all]
export ANTHROPIC_API_KEY=sk-ant-...
```

```python
debate.add_agent(create_agent("anthropic", name="analyst"))
debate.add_agent(create_agent("openai", name="challenger"))
```

**Runnable examples:** [`examples/quickstart/`](../examples/quickstart/)

| Example | What it shows |
|---------|---------------|
| [`01_simple_debate.py`](../examples/quickstart/01_simple_debate.py) | Minimal 3-agent debate with mock agents |
| [`02_with_receipt.py`](../examples/quickstart/02_with_receipt.py) | Decision receipt with HMAC signing |
| [`03_evidence_quality.py`](../examples/quickstart/03_evidence_quality.py) | Evidence quality scoring and hollow consensus detection |

**Next:** [aragora-debate README](../aragora-debate/README.md) for the full API reference, custom agents, and configuration options.

---

## Path 2: Use the Aragora API

Best for: applications that talk to a running Aragora server over HTTP.

**Prerequisite:** A running Aragora server (see Path 3, or use `aragora serve` locally).

### Python

```bash
pip install aragora-sdk
```

```python
import asyncio
from aragora_sdk import AragoraClient

async def main():
    async with AragoraClient(base_url="http://localhost:8080") as client:
        result = await client.debates.run(
            task="Should we use microservices or a monolith?",
            agents=["anthropic-api", "openai-api"],
        )
        print(f"Consensus: {result.consensus.conclusion}")

asyncio.run(main())
```

**Next:** [Python SDK quickstart](guides/python-quickstart.md) | [Full SDK guide](SDK_GUIDE.md)

### TypeScript

```bash
npm install @aragora/sdk
```

```typescript
import { createClient } from '@aragora/sdk';

const client = createClient({
  baseUrl: 'http://localhost:8080',
  apiKey: process.env.ARAGORA_API_KEY,
});

const result = await client.runDebate({
  task: 'Should we use microservices or a monolith?',
  agents: ['anthropic-api', 'openai-api'],
  rounds: 3,
});

console.log('Answer:', result.final_answer);
```

**Next:** [TypeScript SDK quickstart](guides/typescript-quickstart.md)

---

## Path 3: Self-host the platform

Best for: running the full Aragora platform with REST API, WebSocket streaming, and dashboard.

### Quick start with Docker (5 minutes)

```bash
git clone https://github.com/an0mium/aragora.git
cd aragora
cp .env.example .env
# Edit .env: add at least ANTHROPIC_API_KEY or OPENAI_API_KEY

docker compose -f docker-compose.simple.yml up -d
```

Verify it works:

```bash
curl http://localhost:8080/api/health
# {"status": "healthy"}
```

Run a debate:

```bash
curl -X POST http://localhost:8080/api/debates \
  -H "Content-Type: application/json" \
  -d '{"task": "Should we adopt GraphQL?", "rounds": 3}'
```

### Demo mode (no API keys)

```bash
docker compose -f deploy/demo/docker-compose.yml up --build
# API at localhost:8080, Dashboard at localhost:3000
```

**Next:** [Self-hosted quickstart](guides/SELF_HOSTED_QUICKSTART.md) | [Docker quickstart](guides/QUICKSTART_DOCKER.md)

---

## Path 4: Contribute to Aragora

```bash
git clone https://github.com/an0mium/aragora.git
cd aragora
pip install -e ".[dev]"
pytest tests/ -x -q --timeout=10  # Run a quick subset
```

**Next:** [Developer quickstart](guides/DEVELOPER_QUICKSTART.md) | [CLAUDE.md](../CLAUDE.md) (architecture overview)

---

## Comparison of packages

| | `aragora-debate` | `aragora-sdk` | `@aragora/sdk` | `aragora` (full) |
|---|---|---|---|---|
| **What** | Debate engine library | Python API client | TypeScript API client | Full platform |
| **Install** | `pip install aragora-debate` | `pip install aragora-sdk` | `npm install @aragora/sdk` | `pip install -e .` or Docker |
| **Dependencies** | Zero (stdlib only) | httpx, pydantic | None (ws optional) | 50+ packages |
| **Needs a server** | No | Yes | Yes | Is the server |
| **Mock agents** | Yes | N/A | N/A | Yes |
| **Real LLM agents** | Optional extras | Via server | Via server | Built-in |
| **Decision receipts** | Yes | Via server | Via server | Yes |
| **PyPI / npm** | [pypi.org/project/aragora-debate](https://pypi.org/project/aragora-debate/) | [pypi.org/project/aragora-sdk](https://pypi.org/project/aragora-sdk/) | [npmjs.com/package/@aragora/sdk](https://www.npmjs.com/package/@aragora/sdk) | Source only |
| **Best for** | Embedding debate logic | Integrating with Aragora API | Frontend/Node.js apps | Self-hosting |

---

## Troubleshooting

**"No API keys configured"** -- If using `aragora-debate` with mock agents, no keys are needed. For real providers, set `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.

**"Module not found: aragora_debate"** -- Make sure you installed `aragora-debate` (with the hyphen), not `aragora`.

**"Connection refused"** -- The SDK packages (`aragora-sdk`, `@aragora/sdk`) require a running Aragora server. Start one with `aragora serve` or Docker.

**"Need at least 2 agents"** -- Debates require 2+ agents. Add more agents with `debate.add_agent()` or set more API keys.

---

## Further reading

| Document | Description |
|----------|-------------|
| [API Reference](api/API_REFERENCE.md) | REST API documentation |
| [SDK Guide](SDK_GUIDE.md) | Comprehensive Python and TypeScript SDK guide |
| [Feature Discovery](FEATURE_DISCOVERY.md) | Full catalog of 215+ features |
| [Enterprise Features](enterprise/ENTERPRISE_FEATURES.md) | SSO, RBAC, multi-tenancy, compliance |
| [Status](STATUS.md) | Feature implementation status |
