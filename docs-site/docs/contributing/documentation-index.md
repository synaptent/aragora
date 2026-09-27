---
title: Aragora Documentation Index
description: Aragora Documentation Index
---

# Aragora Documentation Index

Canonical documentation lives in `docs/` and is mirrored into `docs-site/`.

This index intentionally links to actively maintained docs with validated paths.
For the full goal-oriented landing page, start at **[docs/README.md](https://github.com/synaptent/aragora/blob/main/docs/README.md)**
— that page is the canonical documentation landing; this index is the flat
reference list.

## Public Utility Path

The core loop, in order: run a debate, get a receipt, verify it independently,
then wire it into CI.

1. [Quickstart](../getting-started/quickstart) — a working debate in under a minute
2. [Receipt Lineage Reconciliation](../specs/receipt-lineage-reconciliation) — what a receipt is: the native record vs. the portable ODR
3. [Independent Verifier Guide](../specs/independent-verifier-guide) — verify a receipt with `aragora-verify` (exit codes: `0 verified / 1 failed / 2 usage / 3 signatures-present-unchecked`), no Aragora install required
4. [GitHub Action Setup](../guides/github-action-setup) — add multi-model CI review + receipts to your pull requests

## Getting Started

- [Getting Started](../getting-started/overview)
- [Cold Reviewer Guide](./cold-reviewer-guide)
- [SDK Guide (Python)](../guides/sdk)
- [CLI Reference (generated)](../api/cli)

## Receipts & Verification

- [Open Decision Receipt Spec](../specs/open-decision-receipt)
- [Receipt Lineage Reconciliation](../specs/receipt-lineage-reconciliation)
- [Independent Verifier Guide](../specs/independent-verifier-guide)

## API

- [API Reference](../api/reference)
- [Supported API Surface](../api/supported-surface)
- [API Endpoint Catalog](../api/endpoints)
- [API Examples](../api/examples)
- [API Versioning](../api/versioning)
- [Webhooks](../api/webhooks)

## Core Concepts

- [Architecture](../core-concepts/architecture)
- [Debate Internals](../core-concepts/debate-internals)
- [Agent System](../core-concepts/agents)
- [Knowledge Mound](../core-concepts/knowledge-mound)
- [Workflow Engine](../core-concepts/workflow-engine)

## Operations

- [Production Deployment](../deployment/production-deployment)
- [Deployment Guide](../deployment/overview)
- [Security Deployment](../deployment/security)
- [Runbook](../operations/runbook)
- [Incident Response](../operations/incident-response)
- [Aragora Conductor Workflow](../guides/conductor-workflow)
- [Aragora Worker Prompt Pack](../guides/worker-prompt-pack)
- [Dev Swarm Coordination](./dev-swarm-coordination)

## Architecture and Planning

- [Conductor Control Plane Implementation Spec](./conductor-control-plane-implementation-spec)

## Security and Compliance

- [Security Overview](../security/overview)
- [Authentication Guide](../security/authentication)
- [SSO Setup](../enterprise/sso)
- [Compliance](../enterprise/compliance)
- [RBAC Matrix](../deployment/RBAC_MATRIX)

## Product Status and Planning

- [Status](./status)
- [Feature Discovery](./feature-discovery)
- [Feature Gap List](./feature-gap-list)
- [Next Steps (Canonical)](./next-steps-canonical)
- [Active 6-Week Execution Plan](./execution-next-6-weeks-2026-03-05)
- [Documentation Hygiene Register](./documentation-hygiene-and-gap-register)
- [Roadmap](./roadmap)

## Reference

- [Environment Variables](../getting-started/environment)
- [Install Matrix](../reference/install-matrix)
- [Library Usage](../guides/library-usage)

## Contributing

- [Contributing Guide](./guide)
- [Reference Index](../reference/reference-index)
- [Deprecation Policy](./deprecation)

## Notes

- Deprecated and historical docs are in `docs/deprecated/`.
- For link-health checks, run `python scripts/validate_doc_links.py`.
- `docs/specs/` is mirrored into `docs-site/` (as the `specs/` category) by
  `docs-site/scripts/sync-docs.js`; relative links into it from mirrored docs
  are safe to use.
- `docs/reference/` is mirrored into `docs-site/` (as the `reference/`
  category) the same way; relative links into it from mirrored docs are
  safe to use.
