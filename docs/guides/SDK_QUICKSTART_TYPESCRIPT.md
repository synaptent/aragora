# TypeScript SDK Quickstart

> **Canonical entry point:** New to Aragora? Start at **[docs/START_HERE.md](../START_HERE.md)** for a decision tree that picks the right package for you.

> **Note:** For the comprehensive TypeScript SDK guide with React hooks, Next.js integration, streaming, and advanced features, see **[TypeScript Quickstart Guide](./typescript-quickstart.md)**.
>
> This page provides a minimal 5-minute quickstart.

Get started with Aragora in under 5 minutes.

## Installation

```bash
npm install @aragora/sdk
# or
yarn add @aragora/sdk
# or
pnpm add @aragora/sdk
```

## Basic Usage

```typescript
import { createClient } from '@aragora/sdk';

const client = createClient({
  baseUrl: 'http://localhost:8080',
  apiKey: 'your-api-key'
});

// Run a debate
const result = await client.runDebate({
  task: 'Should we use TypeScript or JavaScript?',
  agents: ['claude', 'gpt-4'],
  rounds: 3
});

console.log('Conclusion:', result.final_answer ?? result.consensus?.conclusion);
```

## Full Example

```typescript
import { createClient, AragoraClientSync } from '@aragora/sdk';

async function main() {
  // Option 1: Low-level client
  const client = createClient({
    baseUrl: 'http://localhost:8080',
    apiKey: process.env.ARAGORA_API_KEY
  });

  // Create a debate
  const debate = await client.createDebate({
    task: 'Design a caching strategy for our API',
    agents: ['anthropic-api', 'openai-api', 'gemini-api'],
    rounds: 3,
    consensus: 'majority'
  });

  console.log('Debate ID:', debate.debate_id);

  // Get results
  const result = await client.getDebate(debate.debate_id);
  console.log('Status:', result.status);
  console.log('Final answer:', result.final_answer ?? result.consensus?.conclusion);

  // Option 2: Sync-style wrapper (simpler API)
  const syncClient = new AragoraClientSync({
    baseUrl: 'http://localhost:8080',
    apiKey: process.env.ARAGORA_API_KEY
  });

  const debates = await syncClient.listDebates();
  console.log('Total debates:', debates.length);
}

main();
```

## Real-time Streaming

```typescript
import { ConnectionError, createClient } from '@aragora/sdk';

const client = createClient({ baseUrl: 'http://localhost:8080' });

// Stream debate events
const stream = client.streamDebate('debate-123');

try {
  for await (const event of stream) {
    console.log(event.type, event.data);
  }
} catch (error) {
  if (!(error instanceof ConnectionError)) throw error;
  console.warn('Stream interrupted; debate completion is unknown', error.code);
}
```

Accepted events drain before a transport failure is thrown; disconnection is not
`debate_end`. Close errors expose `WS_CLOSE_<number>` and numeric `responseBody.code`.
A transport error waits up to 1,000 ms for close details; repeated errors do not
extend that window. If close never arrives, the sanitized error has no close code
and is non-retryable; parsing errors fail immediately and are also non-retryable.
Handle these explicitly rather than assuming the failure is permanent. A genuine
terminal event accepted before finalization still wins, and buffered events drain.
`isRetryableError(error)` reports eligibility, not automatic retry or guaranteed
replay. This iterator never resumes after closure. If reconnecting is appropriate,
use bounded backoff and account for possible gaps or duplicates; do not restart blindly.

## Key APIs

| Method | Description |
|--------|-------------|
| `client.runDebate()` | Run debate and wait for completion |
| `client.createDebate()` | Create debate (non-blocking) |
| `client.getDebate(id)` | Get debate details |
| `client.listDebates()` | List all debates |
| `client.streamDebate(id)` | Stream real-time events |
| `client.getExplanation(id)` | Get decision explanation |
| `client.health.check()` | Check API health |

## SME Workflows (Small Business)

```typescript
// Quick invoice generation
const invoice = await client.sme.quickInvoice({
  customer: 'Acme Corp',
  items: [{ description: 'Consulting', amount: 1500 }]
});

// Quick inventory check
const status = await client.sme.quickInventoryCheck('SKU-123');

// List available SME workflows
const workflows = await client.sme.listWorkflows();
```

## Environment Variables

```bash
export ARAGORA_API_URL="http://localhost:8080"
export ARAGORA_API_KEY="your-api-key"
```

```typescript
const client = createClient({
  baseUrl: process.env.ARAGORA_API_URL,
  apiKey: process.env.ARAGORA_API_KEY
});
```

## Next Steps

- [TypeScript SDK Quickstart](./typescript-quickstart.md) -- Comprehensive guide with React, Next.js, streaming
- [API Reference](../api/API_REFERENCE.md) -- REST API documentation
- [Examples](../../examples/README.md) -- Runnable examples
- [Start Here](../START_HERE.md) -- Unified entry point for all packages
