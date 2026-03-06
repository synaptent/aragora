# Golden Path: Your First Aragora Debate

This tutorial takes you from install to decision receipt in under 10 minutes.

## Prerequisites

- **Python 3.10+** or **Node.js 18+**
- An API key: `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`
- A running Aragora server (`aragora serve` or Docker -- see [Self-Hosted Quickstart](../guides/SELF_HOSTED_QUICKSTART.md))

## 1. Install

**Python:**

```bash
pip install aragora-sdk
```

**TypeScript:**

```bash
npm install @aragora/sdk
```

## 2. Create a Client

**Python:**

```python
from aragora_sdk import AragoraClient

client = AragoraClient(
    base_url="http://localhost:8080",
    api_key="your-api-key",
    max_retries=3,
)
```

**TypeScript:**

```typescript
import { createClient } from '@aragora/sdk';

const client = createClient({
  baseUrl: 'http://localhost:8080',
  apiKey: 'your-api-key',
});
```

> **Tip:** In Python, `AragoraClient.from_env()` reads `ARAGORA_API_URL` and `ARAGORA_API_KEY` automatically.

## 3. Run Your First Debate

```python
result = client.debates.create(
    question="Should we adopt microservices?",
    rounds=3,
)
print(result)
```

Response:

```json
{
  "debate_id": "dbt_a1b2c3d4e5f6",
  "status": "completed",
  "question": "Should we adopt microservices?",
  "rounds": 3,
  "agents": ["anthropic-api", "openai-api", "gemini-api"],
  "consensus": {
    "reached": true,
    "conclusion": "Adopt a modular monolith first, extract microservices as scaling demands emerge.",
    "confidence": 0.87,
    "method": "majority"
  },
  "duration_seconds": 14.2
}
```

## 4. Stream a Debate in Real Time

**Python:**

```python
from aragora_sdk import AragoraClient

client = AragoraClient(base_url="http://localhost:8080", api_key="your-api-key")
ws = client.websocket()

for event in ws.stream_debate(debate_id="dbt_a1b2c3d4e5f6"):
    if event.type == "debate_start":
        print(f"Debate started: {event.data['question']}")
    elif event.type == "agent_message":
        print(f"[{event.data['agent']}] {event.data['content'][:80]}...")
    elif event.type == "consensus":
        print(f"Consensus reached: {event.data['conclusion']}")
    elif event.type == "debate_end":
        print(f"Finished in {event.data['duration_seconds']}s")
        break
```

Key WebSocket events: `debate_start`, `round_start`, `agent_message`, `critique`, `vote`, `consensus`, `debate_end`.

## 5. Get the Decision Receipt

Every completed debate produces a cryptographic decision receipt.

```python
receipt = client.receipts.get("dbt_a1b2c3d4e5f6")
print(receipt)
```

```json
{
  "receipt_id": "rct_f7e8d9c0b1a2",
  "debate_id": "dbt_a1b2c3d4e5f6",
  "verdict": "Adopt modular monolith first, extract services as scale demands.",
  "confidence": 0.87,
  "robustness": 0.82,
  "findings": [
    {
      "agent": "anthropic-api",
      "position": "Microservices enable independent scaling per domain.",
      "evidence_quality": 0.91
    },
    {
      "agent": "openai-api",
      "position": "Monolith-first reduces operational complexity.",
      "evidence_quality": 0.88
    }
  ],
  "hash": "sha256:3a7be7b10e4d...",
  "signed_at": "2026-03-05T12:34:56Z"
}
```

| Field | Meaning |
|-------|---------|
| `verdict` | Final consensus answer |
| `confidence` | How strongly agents agreed (0-1) |
| `robustness` | How well the conclusion survived adversarial critique (0-1) |
| `findings` | Per-agent positions with evidence quality scores |
| `hash` | SHA-256 integrity hash for audit trails |

## 6. Submit Feedback

Close the loop by rating the decision quality.

```python
client.feedback.submit(
    debate_id="dbt_a1b2c3d4e5f6",
    rating=5,
    comment="Clear reasoning, actionable conclusion.",
)
```

Feedback improves agent selection and calibration for future debates.

## 7. Handle Errors

```python
from aragora_sdk import AragoraClient, AragoraError, RateLimitError
import time

client = AragoraClient(base_url="http://localhost:8080", api_key="your-api-key")

try:
    result = client.debates.create(question="Should we migrate to GraphQL?", rounds=3)
except RateLimitError as e:
    print(f"Rate limited. Retry after {e.retry_after}s")
    time.sleep(e.retry_after or 5)
except AragoraError as e:
    print(f"Error: {e.message} (trace: {e.trace_id})")
```

For the full error hierarchy and retry patterns, see the [Error Handling Guide](../guides/ERROR_HANDLING.md).

## 8. Next Steps

| Goal | Resource |
|------|----------|
| Full SDK reference | [SDK Guide](../SDK_GUIDE.md) |
| REST API docs | [API Reference](../api/API_REFERENCE.md) |
| Run debates without a server | [aragora-debate package](../START_HERE.md#path-1-run-debates-in-my-code) |
| Advanced consensus modes | `"judge"`, `"supermajority"`, `"weighted"`, `"unanimous"` |
| Gauntlet stress-testing | `aragora gauntlet "your question"` |
| Enterprise features | [Enterprise Guide](../enterprise/ENTERPRISE_FEATURES.md) |
| Error handling patterns | [Error Handling Guide](../guides/ERROR_HANDLING.md) |
