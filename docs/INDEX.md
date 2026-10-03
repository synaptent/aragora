# Aragora Documentation Index

Canonical documentation lives in `docs/` and is mirrored into `docs-site/`.

This index intentionally links to actively maintained docs with validated paths.
For the full goal-oriented landing page, start at **[docs/README.md](README.md)**
— that page is the canonical documentation landing; this index is the flat
reference list.

## Public Utility Path

The core loop, in order: run a debate, get a receipt, verify it independently,
then wire it into CI.

1. [Quickstart](quickstart.md) — a working debate in under a minute
2. [Receipt Lineage Reconciliation](specs/RECEIPT_LINEAGE_RECONCILIATION.md) — what a receipt is: the native record vs. the portable ODR
3. [Independent Verifier Guide](specs/INDEPENDENT_VERIFIER_GUIDE.md) — verify a receipt with `aragora-verify` (exit codes: `0 verified / 1 failed / 2 usage / 3 signatures-present-unchecked`), no Aragora install required
4. [GitHub Action Setup](GITHUB_ACTION_SETUP.md) — add multi-model CI review + receipts to your pull requests

## Getting Started

- [Getting Started](guides/GETTING_STARTED.md)
- [Cold Reviewer Guide](COLD_REVIEWER_GUIDE.md)
- [SDK Guide (Python)](SDK_GUIDE.md)
- [CLI Reference (generated)](reference/CLI_REFERENCE.md)

## Receipts & Verification

- [Open Decision Receipt Spec](specs/OPEN_DECISION_RECEIPT.md)
- [Receipt Lineage Reconciliation](specs/RECEIPT_LINEAGE_RECONCILIATION.md)
- [Independent Verifier Guide](specs/INDEPENDENT_VERIFIER_GUIDE.md)

## API

- [API Reference](api/API_REFERENCE.md)
- [Supported API Surface](api/SUPPORTED_SURFACE.md)
- [API Endpoint Catalog](api/API_ENDPOINTS.md)
- [API Examples](api/API_EXAMPLES.md)
- [API Versioning](api/API_VERSIONING.md)
- [Webhooks](api/WEBHOOKS.md)

## Core Concepts

- [Architecture](architecture/ARCHITECTURE.md)
- [Debate Internals](debate/DEBATE_INTERNALS.md)
- [Agent System](debate/AGENTS.md)
- [Knowledge Mound](knowledge/KNOWLEDGE_MOUND.md)
- [Workflow Engine](workflow/WORKFLOW_ENGINE.md)

## Operations

- [Production Deployment](deployment/PRODUCTION_DEPLOYMENT.md)
- [Deployment Guide](deployment/DEPLOYMENT.md)
- [Security Deployment](deployment/SECURITY_DEPLOYMENT.md)
- [Runbook](deployment/RUNBOOK.md)
- [Incident Response](deployment/INCIDENT_RESPONSE.md)
- [Aragora Conductor Workflow](guides/CONDUCTOR_WORKFLOW.md)
- [Aragora Worker Prompt Pack](guides/WORKER_PROMPT_PACK.md)
- [Dev Swarm Coordination](architecture/DEV_SWARM_COORDINATION.md)

## Architecture and Planning

- [Conductor Control Plane Implementation Spec](plans/2026-03-07-conductor-control-plane.md)

## Security and Compliance

- [Security Overview](enterprise/SECURITY.md)
- [Authentication Guide](enterprise/AUTH_GUIDE.md)
- [SSO Setup](enterprise/SSO_SETUP.md)
- [Compliance](enterprise/COMPLIANCE.md)
- [RBAC Matrix](enterprise/RBAC_MATRIX.md)

## Product Status and Planning

- [Status](status/STATUS.md)
- [Feature Discovery](status/FEATURE_DISCOVERY.md)
- [Feature Gap List](FEATURE_GAP_LIST.md)
- [Next Steps (Canonical)](status/NEXT_STEPS_CANONICAL.md)
- [Active 6-Week Execution Plan](status/EXECUTION_NEXT_6_WEEKS_2026-03-05.md)
- [Documentation Hygiene Register](status/DOCUMENTATION_HYGIENE_AND_GAP_REGISTER.md)
- [Roadmap](../ROADMAP.md)

## Reference

- [Environment Variables](reference/ENVIRONMENT.md)
- [Install Matrix](reference/INSTALL_MATRIX.md)
- [Library Usage](reference/LIBRARY_USAGE.md)

## Contributing

- [Contributing Guide](../CONTRIBUTING.md)
- [Reference Index](reference/INDEX.md)
- [Deprecation Policy](reference/DEPRECATION_POLICY.md)

## Notes

- Deprecated and historical docs are in `docs/deprecated/`.
- For link-health checks, run `python scripts/validate_doc_links.py`.
- `docs/specs/` is mirrored into `docs-site/` (as the `specs/` category) by
  `docs-site/scripts/sync-docs.js`; relative links into it from mirrored docs
  are safe to use.
- `docs/reference/` is mirrored into `docs-site/` (as the `reference/`
  category) the same way; relative links into it from mirrored docs are
  safe to use.
