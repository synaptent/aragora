# Quickstart

Get from zero to a working adversarial debate in under a minute.

---

## 1. Install

```bash
pip install aragora-debate
```

## 2. Zero-Key Demo

No API keys needed — runs with styled mock agents locally:

```bash
python -c "
from aragora_debate.arena import Arena
from aragora_debate.styled_mock import StyledMockAgent
import asyncio

agents = [
    StyledMockAgent('analyst', style='supportive'),
    StyledMockAgent('critic', style='critical'),
    StyledMockAgent('pm', style='balanced'),
]
arena = Arena(question='Should we migrate to microservices?', agents=agents)
result = asyncio.run(arena.run())
print(result.receipt.to_markdown())
"
```

You'll see three agents debate, critique each other, vote, and produce an audit-ready decision receipt.

## 3. Three-Line Debate (Python)

```python
from aragora_debate.arena import Arena
from aragora_debate.styled_mock import StyledMockAgent

agents = [
    StyledMockAgent("analyst", style="supportive"),
    StyledMockAgent("critic", style="critical"),
    StyledMockAgent("pm", style="balanced"),
]
arena = Arena(question="Should we adopt GraphQL?", agents=agents)
result = asyncio.run(arena.run())
print(result.receipt.to_markdown())
```

## 4. Add Real AI Models

Set at least one API key:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."   # Claude
# or
export OPENAI_API_KEY="sk-..."          # GPT
```

Then run a real debate:

```python
import asyncio
from aragora import Arena, Environment, DebateProtocol

env = Environment(task="Design a rate limiter for our API")
protocol = DebateProtocol(rounds=3, consensus="majority")

# Arena auto-discovers available agents from your API keys
arena = Arena(env, protocol=protocol)
result = asyncio.run(arena.run())
print(result.summary)
```

## 5. TypeScript SDK

```bash
npm install @aragora/sdk
```

```typescript
import { AragoraClient } from "@aragora/sdk";

const client = new AragoraClient({ baseUrl: "http://localhost:8080" });
const result = await client.debates.create({
  task: "Should we use microservices or a monolith?",
  agents: ["claude", "openai"],
  rounds: 3,
});
console.log(result.summary);
```

## 6. Self-Host the Full Platform

```bash
docker compose -f deploy/demo/docker-compose.yml up
```

Then visit:
- **Landing page:** http://localhost:3000
- **API docs (Swagger):** http://localhost:8080/api/v2/docs
- **API docs (Redoc):** http://localhost:8080/api/v2/redoc
- **Interactive playground:** http://localhost:3000/playground

## 7. CLI

```bash
pip install aragora
aragora debate "Should we build or buy our auth system?"
aragora serve --api-port 8080 --ws-port 8765
```

## Next Steps

| Guide | What you'll learn |
|-------|-------------------|
| [CLI Reference](CLI_REFERENCE.md) | All CLI commands and flags |
| [SDK Guide](SDK_GUIDE.md) | Python & TypeScript SDK reference |
| [API Reference](api/API_REFERENCE.md) | REST API endpoints |
| [Self-Hosting](guides/SELF_HOSTED_COMPLETE_GUIDE.md) | Production deployment |
| [Start Here](START_HERE.md) | Deeper architectural overview |
