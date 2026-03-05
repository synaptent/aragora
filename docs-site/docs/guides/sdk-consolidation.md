---
title: TypeScript SDK Consolidation Roadmap
description: TypeScript SDK Consolidation Roadmap
---

# TypeScript SDK Consolidation Roadmap

> **Status:** Phase 2 Complete (January 2026)
> **Next Milestone:** v3.0.0 consolidation (Q2 2026)

This document outlines the plan to consolidate the two TypeScript packages (`@aragora/sdk` and `@aragora/client`) into a single unified SDK.

## Current State (v2.8.x)

Two packages exist with different focuses:

| Aspect | `@aragora/sdk` | `@aragora/client` |
|--------|---------------|-------------------|
| **Version** | 2.6.3 | 2.6.3 (deprecated) |
| **Location** | `sdk/typescript/` | `aragora-js/` |
| **API Style** | Flat (`client.createDebate()`) | Namespaced (`client.debates.create()`) |
| **Build** | tsup (ESM + CJS) | tsc (CJS only) |
| **Tests** | Minimal | 6 test suites |
| **Best For** | Application developers | Enterprise/Control plane |

### Feature Matrix

> **Note:** After Phase 2 completion, `@aragora/sdk` now has feature parity with `@aragora/client`.

| Feature | `@aragora/sdk` | `@aragora/client` |
|---------|:-------------:|:-----------------:|
| Basic debates | Yes | Yes |
| WebSocket streaming | Yes | Yes |
| Workflows | Yes | No |
| Explainability | Yes | No |
| Marketplace | Yes | No |
| Control Plane | Yes | Yes |
| Graph/Matrix debates | Yes | Yes |
| Formal verification | Yes | Yes |
| Team selection | Yes | Yes |
| Gauntlet API | Yes | Yes |
| Codebase scanning | Yes | No |
| Analytics connectors | Yes | No |

## Target State (v3.0.0)

A single `@aragora/sdk` package combining the best of both:

### Goals

- **Single source of truth** - One package to install and maintain
- **Namespace API** - Organized, discoverable API surface
- **Full feature set** - All capabilities from both packages
- **Modern build** - ESM + CJS dual output, tree-shakeable
- **Comprehensive tests** - Merged and expanded test coverage

### Target API Structure

```typescript
import { AragoraClient } from '@aragora/sdk';

const client = new AragoraClient({
  baseUrl: 'https://api.aragora.ai',
  apiKey: 'your-key'
});

// Debates (from both packages)
await client.debates.create({ task: '...' });
await client.debates.list();
await client.graphDebates.create({ ... });
await client.matrixDebates.create({ ... });

// Agents
await client.agents.list();
await client.agents.get('agent-id');

// Control Plane (from @aragora/client)
await client.controlPlane.registerAgent('agent-id', [...]);
await client.controlPlane.submitTask('debate', { ... });
await client.controlPlane.getAgentStatus('agent-id');

// Verification (from @aragora/client)
await client.verification.verifyClaim({ ... });

// Workflows (from @aragora/sdk)
await client.workflows.list();
await client.workflows.execute('template-id', { ... });

// Explainability (from @aragora/sdk)
await client.explainability.getFactors('debate-id');
await client.explainability.getCounterfactuals('debate-id');

// Gauntlet
await client.gauntlet.run({ ... });
await client.gauntlet.getReceipt('receipt-id');

// WebSocket (unified)
const stream = client.createStream();
await stream.connect();
stream.on('message', (event) => { ... });
```

## Migration Timeline

### v2.2.0 (Q1 2026)

**Goal**: Prepare for consolidation

- Add deprecation warnings to `@aragora/client`
- Add namespace aliases to `@aragora/sdk`
- Port test suites from client to sdk
- Document migration path

**Breaking changes**: None

### v2.3.0 (Q1 2026)

**Goal**: Feature parity in `@aragora/sdk`

- Add Control Plane API to sdk
- Add Graph/Matrix debates to sdk
- Add Formal Verification to sdk
- Add Team Selection to sdk
- Client becomes thin wrapper around sdk

**Breaking changes**: None (client still works)

### v3.0.0 (Q2 2026)

**Goal**: Single unified SDK

- `@aragora/client` deprecated (no longer published)
- `@aragora/sdk` is the only package
- Full namespace API
- ESM-first with CJS fallback
- Complete TypeScript definitions

**Breaking changes**:
- `createClient()` -> `new AragoraClient()`
- Flat methods moved to namespaces
- Some type names may change

## Migration Guide

### From `@aragora/sdk` v2.x to v3.0.0

```typescript
// Before (v2.x)
import { createClient } from '@aragora/sdk';
const client = createClient({ baseUrl: '...' });
await client.createDebate({ ... });
await client.listAgents();

// After (v3.0.0)
import { AragoraClient } from '@aragora/sdk';
const client = new AragoraClient({ baseUrl: '...' });
await client.debates.create({ ... });
await client.agents.list();
```

### From `@aragora/client` v2.x to `@aragora/sdk` v3.0.0

```typescript
// Before (client v2.x)
import { AragoraClient } from '@aragora/client';
const client = new AragoraClient({ baseUrl: '...' });
await client.debates.run({ ... });
await client.controlPlane.submitTask({ ... });

// After (sdk v3.0.0)
import { AragoraClient } from '@aragora/sdk';
const client = new AragoraClient({ baseUrl: '...' });
await client.debates.create({ ... });  // Method renamed for consistency
await client.controlPlane.submitTask({ ... });  // Same API
```

## Implementation Phases

### Phase 1: Analysis (1 week) - COMPLETE

- [x] Document all methods in both packages
- [x] Identify overlapping functionality
- [x] Design unified namespace structure
- [x] Plan test migration

### Phase 2: SDK Enhancement (2-3 weeks) - COMPLETE

- [x] Add namespace structure to sdk (8 namespaces exposed: debates, agents, workflows, sme, billing, budgets, receipts, explainability)
- [x] Port Control Plane API (registerAgent, unregisterAgent, submitTask, etc.)
- [x] Port Graph/Matrix debates (createGraphDebate, createMatrixDebate)
- [x] Port Formal Verification (verifyClaim, verifyDebate, getVerificationStatus)
- [x] Migrate tests from client
- [x] Add Gauntlet API (run, getReceipt, listReceipts)
- [x] Add Codebase scanning (scanCodebase, getVulnerabilities)
- [x] Add Analytics connectors (getAnalyticsPlatforms, connectAnalytics)

**Note:** Additional namespace APIs are defined in `src/namespaces/` (controlPlane, gauntlet, analytics, memory, rbac, knowledge, tournaments, auth, verification, audit, tenants, organizations) but require corresponding flat methods on AragoraClient to be exposed. This is planned for Phase 4.

### Phase 3: Deprecation (1 week) - COMPLETE

- [x] Add deprecation warnings to client (runtime console.warn + package.json deprecated field)
- [x] Update documentation (JSDoc @deprecated tags added)
- [x] Announce migration timeline (documented in SDK_CONSOLIDATION.md)
- [ ] Publish v2.2.0 of both packages (ready for publish)

### Phase 4: Client Wrapper (1 week)

- [ ] Make client a wrapper around sdk
- [ ] Ensure backwards compatibility
- [ ] Test with existing client users
- [ ] Publish v2.3.0

### Phase 5: Final Release (1 week)

- [ ] Remove client source (keep as deprecated npm package)
- [ ] Finalize sdk v3.0.0
- [ ] Update all documentation
- [ ] Announce final migration

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Breaking changes for sdk users | High | Detailed migration guide, deprecation warnings |
| Breaking changes for client users | Medium | Client wrapper maintains compatibility through v2.x |
| Test coverage gaps | Medium | Merge all tests, add integration tests |
| Missing features during transition | Low | Feature flags, gradual rollout |

## Success Metrics

- [ ] Single npm package with all features
- [ ] Zero breaking changes for users following migration guide
- [ ] Test coverage >= 80%
- [ ] Documentation updated on docs.aragora.ai
- [ ] No issues reported within 2 weeks of v3.0.0 release

## Detailed Migration Examples

### Example 1: Basic Debate Flow

```typescript
// @aragora/client v2.x
import { AragoraClient } from '@aragora/client';

const client = new AragoraClient({
  baseUrl: 'https://api.aragora.ai',
  apiKey: process.env.ARAGORA_API_KEY!,
});

const debate = await client.debates.run({
  task: 'Evaluate the pros and cons of microservices',
  agents: ['claude', 'gpt-4'],
  rounds: 3,
});

// @aragora/sdk v3.0.0
import { AragoraClient } from '@aragora/sdk';

const client = new AragoraClient({
  baseUrl: 'https://api.aragora.ai',
  apiKey: process.env.ARAGORA_API_KEY!,
});

const debate = await client.debates.create({
  task: 'Evaluate the pros and cons of microservices',
  agents: ['claude', 'gpt-4'],
  rounds: 3,
});
```

### Example 2: WebSocket Streaming

```typescript
// Both packages (API unchanged)
const stream = client.createStream();
await stream.connect();

stream.on('round_start', (event) => {
  console.log(`Round ${event.round} started`);
});

stream.on('agent_message', (event) => {
  console.log(`${event.agent}: ${event.content}`);
});

stream.on('consensus', (event) => {
  console.log(`Consensus reached: ${event.outcome}`);
});

await stream.close();
```

### Example 3: Control Plane Operations

```typescript
// @aragora/client v2.x
await client.controlPlane.registerAgent('my-agent', {
  capabilities: ['analysis', 'coding'],
  maxConcurrency: 5,
});

const task = await client.controlPlane.submitTask('debate', {
  task: 'Review architecture',
  priority: 'high',
});

// @aragora/sdk v3.0.0 (same API)
await client.controlPlane.registerAgent('my-agent', {
  capabilities: ['analysis', 'coding'],
  maxConcurrency: 5,
});

const task = await client.controlPlane.submitTask('debate', {
  task: 'Review architecture',
  priority: 'high',
});
```

### Example 4: Gauntlet Security Testing

```typescript
// @aragora/sdk v2.x and v3.0.0
const result = await client.gauntlet.run({
  targetDebate: debate.id,
  attacks: ['hollow_consensus', 'prompt_injection', 'sycophancy'],
  defenseMode: true,
});

const receipt = await client.gauntlet.getReceipt(result.receiptId);
console.log(`Gauntlet score: ${receipt.score}/100`);
```

### Example 5: Codebase Analysis

```typescript
// @aragora/sdk v2.x and v3.0.0
const scan = await client.codebase.scan({
  repositoryUrl: 'https://github.com/org/repo',
  branch: 'main',
  analysisTypes: ['security', 'architecture', 'dependencies'],
});

const vulnerabilities = await client.codebase.getVulnerabilities(scan.id);
for (const vuln of vulnerabilities) {
  console.log(`${vuln.severity}: ${vuln.description} in ${vuln.file}:${vuln.line}`);
}
```

## Compatibility Layer

During the transition period (v2.2.0 - v2.3.0), `@aragora/client` will internally
use `@aragora/sdk` with a compatibility wrapper:

```typescript
// Internal implementation of @aragora/client v2.3.0
import { AragoraClient as SDKClient } from '@aragora/sdk';

export class AragoraClient {
  private sdk: SDKClient;

  constructor(options: ClientOptions) {
    console.warn(
      'DEPRECATION: @aragora/client is deprecated. ' +
      'Please migrate to @aragora/sdk. See https://docs.aragora.ai/migration'
    );
    this.sdk = new SDKClient(options);
  }

  get debates() {
    return {
      run: (opts: DebateOptions) => this.sdk.debates.create(opts),
      list: () => this.sdk.debates.list(),
      get: (id: string) => this.sdk.debates.get(id),
    };
  }

  // ... other namespace mappings
}
```

## Related Documentation

- [sdk/typescript/README.md](../analysis/adr) - SDK documentation
- [aragora-js/README.md](../analysis/adr) - Client documentation
- [CONTRIBUTING.md](../contributing/guide) - Package naming conventions
