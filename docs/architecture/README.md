# Architecture

System design documents, structural contracts and architecture decision
records. Every page in this directory is listed below once. Start with the
overview pages, then follow the subsystem or decision you need. The full
documentation map is in [docs/README.md](../README.md).

Status notes in the tables come from each page's own header. Proposals,
plans and audits describe the codebase on the date they name; check the code
before relying on them.

## Overview

| Page | What it covers |
|------|----------------|
| [ARCHITECTURE](./ARCHITECTURE.md) | Architecture of the current system |
| [INTENDED_ARCHITECTURE](./INTENDED_ARCHITECTURE.md) | Intended architecture charter: layer model, per-concern authority modules and chartered removals (draft, pending ratification; machine encoding in [charters.yaml](./charters.yaml)) |
| [system-overview](./system-overview.md) | Top-level component diagram of the platform |
| [SYSTEM_DIAGRAM](./SYSTEM_DIAGRAM.md) | Visual architecture diagrams, from clients to storage |
| [IMPORT_LAYERS](./IMPORT_LAYERS.md) | The five import layers and which layer may import which |
| [shims](./shims.md) | Compatibility shims kept at the old import path of moved symbols |

## Subsystem Designs

| Page | What it covers |
|------|----------------|
| [debate-flow](./debate-flow.md) | Round structure of a debate run by the Arena |
| [memory-tiers](./memory-tiers.md) | The four `ContinuumMemory` tiers and how data moves between them |
| [nomic-loop](./nomic-loop.md) | The Nomic Loop self-improvement cycle and its safety guardrails |
| [GAUNTLET_ARCHITECTURE](./GAUNTLET_ARCHITECTURE.md) | Gauntlet package structure and migration from `aragora.modes.gauntlet` |
| [GATEWAY_ARCHITECTURE](./GATEWAY_ARCHITECTURE.md) | Gateway between the debate engine and external agent frameworks |
| [CROSS_FUNCTIONAL_FEATURES](./CROSS_FUNCTIONAL_FEATURES.md) | Enabling the features that connect subsystems (knowledge bridges, coordinated memory writes and more) |
| [HANDLER_PATTERNS](./HANDLER_PATTERNS.md) | Patterns and practices for HTTP handlers |
| [MODEL_CATALOG](./MODEL_CATALOG.md) | Canonical model catalog for model identity and pricing |
| [TRUST_PORTABILITY](./TRUST_PORTABILITY.md) | ERC-8004 agent reputation that transfers between organizations |
| [ANALYSIS](./ANALYSIS.md) | Natural language questions over uploaded documents |
| [CODEBASE_ANALYSIS](./CODEBASE_ANALYSIS.md) | Dependency vulnerability scanning and code quality metrics |
| [CODING_ASSISTANCE](./CODING_ASSISTANCE.md) | Automated test generation for changed code |
| [DEV_SWARM_COORDINATION](./DEV_SWARM_COORDINATION.md) | Protocol for concurrent multi-agent development on one repository |
| [CLOSED_LOOP_BACKBONE](./CLOSED_LOOP_BACKBONE.md) | Target backbone for product and self-improvement flows (status: target architecture, March 2026) |
| [PACKAGING_AND_DISTRIBUTION](./PACKAGING_AND_DISTRIBUTION.md) | Packaging and distribution design record (P3 milestone) |

## Layering and Structural Records

| Page | What it covers |
|------|----------------|
| [ARCHITECTURE_THREE_LAYER](./ARCHITECTURE_THREE_LAYER.md) | Aragora core with optional extension layers |
| [EXTENSION_CONTRACTS](./EXTENSION_CONTRACTS.md) | Cross-layer contracts used by the extension layers |
| [P4A_LAYERING_DISPOSITION](./P4A_LAYERING_DISPOSITION.md) | Disposition of every foundation and infrastructure import-contract edge |
| [P4A_EVENTS_QUEUE_INVERSION](./P4A_EVENTS_QUEUE_INVERSION.md) | Event bus and job-queue registry inversion (status: implemented) |
| [P4B_HANDLERS_DECOMPOSITION](./P4B_HANDLERS_DECOMPOSITION.md) | Decomposition of the flat `aragora/server/handlers` root (design) |
| [QUEUE_ADOPTION_DISPOSITION](./QUEUE_ADOPTION_DISPOSITION.md) | Decision to adopt `aragora/queue` as the canonical durable job API |
| [MODULE_QUARANTINE_PROPOSAL](./MODULE_QUARANTINE_PROPOSAL.md) | Module quarantine boundary (status: proposal only, no moves) |
| [CHARTER_COMPLIANCE_CHECKER](./CHARTER_COMPLIANCE_CHECKER.md) | Advisory checker that reports changes against `charters.yaml` |

## Decisions, Proposals and Audits

Dated records. Each one describes the codebase when it was written.

| Page | What it covers |
|------|----------------|
| [BUILD_VS_INTEGRATE](./BUILD_VS_INTEGRATE.md) | Decision to build extension features in Aragora rather than depend on external repositories (January 2026) |
| [BUILD_VS_INTEGRATE_DECISION](./BUILD_VS_INTEGRATE_DECISION.md) | Analysis behind the build-versus-integrate decision |
| [canonical-apis](./canonical-apis.md) | Canonical APIs for convoys, beads, workspaces, gateway, inbox and routing (status: proposed) |
| [primitive-consolidation](./primitive-consolidation.md) | Decision memo on consolidating those primitives (status: proposed) |
| [nomic-context-builder-plan](./nomic-context-builder-plan.md) | Nomic context builder plan (status: proposed) |
| [nomic-true-test-plan](./nomic-true-test-plan.md) | Nomic "true test" execution plan (status: proposed) |
| [nomic-true-test-spec](./nomic-true-test-spec.md) | Nomic "true test" wiring spec (status: proposed) |
| [metrics-refactoring-plan](./metrics-refactoring-plan.md) | Plan to split the metrics modules (January 2026) |
| [defaults-drift-audit](./defaults-drift-audit.md) | Audit of debate default values (January 2026) |
| [n+1-query-audit](./n+1-query-audit.md) | N+1 query audit of connectors, export handlers and adapters (January 2026) |
| [ARCHITECTURE_REVIEW_RESPONSE](./ARCHITECTURE_REVIEW_RESPONSE.md) | Validated findings and corrections from an architecture review (February 2026) |
| [SOC2_GAP_ANALYSIS](./SOC2_GAP_ANALYSIS.md) | SOC 2 Type II gap analysis (January 2026) |
| [TEST_PLAN_CRITICAL_MODULES](./TEST_PLAN_CRITICAL_MODULES.md) | Test plan for critical untested modules (status: draft, January 2026) |
