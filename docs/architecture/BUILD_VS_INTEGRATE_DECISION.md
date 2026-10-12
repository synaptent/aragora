# Build vs Integrate Decision: Gastown and OpenClaw Parity

This document captures the strategic decision on whether to build custom
implementations or integrate existing code for Gastown and OpenClaw (formerly Moltbot) parity.

## Executive Summary

| Target | Decision | Rationale |
|--------|----------|-----------|
| Gastown concepts | **Build** (inspired by) | Concepts need Aragora-specific semantics |
| OpenClaw concepts | **Build** (inspired by) | Extension must integrate with enterprise core |
| Agent Fabric | **Build** | Core infrastructure, must be Aragora-native |

## Analysis

### Gastown (Developer Orchestration)

**Option A: Integrate Gastown directly**
- Pros: Faster initial parity, proven design
- Cons: Tightly coupled to Claude Code, different persistence model, unclear licensing

**Option B: Build inspired implementation**
- Pros: Aragora-native semantics, integrates with audit/evidence, customizable
- Cons: More development effort, divergence from Gastown patterns

**Decision: Build (inspired by)**

Rationale:
1. Gastown's persistence model (git worktree hooks) is specific to Claude Code
2. Aragora needs its own workspace semantics that integrate with debates/evidence
3. Convoy/Beads concepts can be adapted to Aragora's audit model
4. Building allows tighter integration with Agent Fabric and policy engine

Implementation approach:
- Study Gastown's Mayor/Rigs/Hooks/Convoys/Beads model
- Adapt concepts to Aragora's enterprise semantics
- Build workspace manager that supports both Gastown-style and Aragora-native workflows
- Use git hooks for persistence but with Aragora-specific schema

### OpenClaw (Consumer/Device Extension)

**Option A: Integrate OpenClaw directly**
- Pros: Full-featured consumer assistant, proven UX
- Cons: Different architecture (local-first vs server-centric), unclear licensing

**Option B: Build inspired implementation**
- Pros: Aragora-native, enterprise integration, customizable security model
- Cons: More development effort, may miss OpenClaw UX nuances

**Decision: Build (inspired by)**

Rationale:
1. OpenClaw (formerly Moltbot) is designed as a standalone consumer assistant
2. Aragora's extension needs to integrate with enterprise core (RBAC, audit, tenancy)
3. Security model must be Aragora-native (policy engine, approvals)
4. Key concepts (gateway, inbox, voice) are well-defined and implementable

Implementation approach:
- Study OpenClaw's gateway/inbox/voice/canvas architecture
- Build Aragora-native implementations with enterprise integration
- Support both consumer and enterprise deployment profiles
- Ensure full audit trail and policy enforcement

### Agent Fabric

**Decision: Build**

Rationale:
- Agent Fabric is core infrastructure that all extensions depend on
- Must integrate tightly with Aragora's existing orchestration
- Requires custom policy, budget, and telemetry integration
- No suitable external project matches Aragora's requirements

Implementation approach:
- Build scheduler, isolation, policy, budget, lifecycle, telemetry modules
- Design for 100+ concurrent agents with fair scheduling
- Integrate with existing Aragora resilience and observability

## Component Mapping

### Gastown Concepts -> Aragora Implementation

| Gastown | Aragora Implementation |
|---------|----------------------|
| Mayor | `aragora/extensions/gastown/coordinator.py` - Coordinator agent |
| Town | `aragora/extensions/gastown/workspace.py` - Workspace manager |
| Rigs | Workspace + Agent pool configuration |
| Crew | User workspace membership |
| Polecats | Ephemeral agents via Agent Fabric |
| Hooks | `aragora/worktree/hook_runner.py` - Git worktree persistence |
| Convoys | `aragora/extensions/gastown/convoy.py` - Work tracking |
| Beads | `aragora/extensions/gastown/ledger.py` - Issue ledger |

### OpenClaw Concepts -> Aragora Implementation

| OpenClaw | Aragora Implementation |
|---------|----------------------|
| Gateway | `aragora/extensions/moltbot/gateway.py` - Local routing service |
| Inbox | `aragora/extensions/moltbot/inbox.py` - Channel aggregator |
| Voice | `aragora/extensions/moltbot/voice.py` - Speech I/O |
| Canvas | `aragora/extensions/moltbot/canvas.py` - A2UI renderer |
| Device nodes | `aragora/extensions/moltbot/devices.py` - Device registry |
| Onboarding | `aragora/extensions/moltbot/onboarding.py` - Setup wizard |
| Pairing | `aragora/extensions/moltbot/pairing.py` - Security pairing |

## Timeline Impact

Building custom implementations adds ~2-4 weeks vs direct integration, but:
- Reduces long-term maintenance burden
- Ensures architectural coherence
- Allows proper enterprise integration
- Avoids licensing/compatibility issues

## Open Questions

1. Should we reach out to Gastown/OpenClaw authors for collaboration?
2. What's the minimum viable subset for each extension?
3. How do we handle divergence from source projects over time?

## Approved By

- [ ] Architecture review
- [ ] Security review
- [ ] Product alignment
