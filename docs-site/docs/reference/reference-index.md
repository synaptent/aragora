---
title: Documentation Index
description: Documentation Index
---

# Documentation Index

Canonical documentation lives in `docs/` and is mirrored into `docs-site/`.

This index is scoped to high-signal, actively maintained docs with validated paths.

## Start Here

- Project overview: [../README.md](https://github.com/synaptent/aragora/blob/main/docs/README.md)
- First-time setup: [../guides/GETTING_STARTED.md](../getting-started/overview)
- Install matrix (per-audience, per-distribution): [INSTALL_MATRIX.md](./install-matrix)
- Developer quickstart: [../quickstart.md](../getting-started/quickstart)
- SDK guide: [../SDK_GUIDE.md](../guides/sdk)
- Capability matrix: [../CAPABILITY_MATRIX.md](https://github.com/synaptent/aragora/blob/main/docs/CAPABILITY_MATRIX.md)

## CLI and Runtime

- CLI reference (generated): [CLI_REFERENCE.md](../api/cli)
- Environment variables: [ENVIRONMENT.md](../getting-started/environment)
- Full environment reference: [ENVIRONMENT_COMPLETE.md](./environment-complete)
- Library usage: [LIBRARY_USAGE.md](../guides/library-usage)
- Receipt contract: [../RECEIPT_CONTRACT.md](https://github.com/synaptent/aragora/blob/main/docs/RECEIPT_CONTRACT.md)

## API and Protocols

- API reference: [../api/API_REFERENCE.md](../api/reference)
- Endpoint catalog: [../api/API_ENDPOINTS.md](../api/endpoints)
- API examples: [../api/API_EXAMPLES.md](../api/examples)
- Versioning policy: [../api/API_VERSIONING.md](../api/versioning)
- Webhooks: [../api/WEBHOOKS.md](../api/webhooks)

## Deployment and Operations

- Production deployment: [../deployment/PRODUCTION_DEPLOYMENT.md](../deployment/production-deployment)
- Deployment guide: [../deployment/DEPLOYMENT.md](../deployment/overview)
- Security deployment: [../deployment/SECURITY_DEPLOYMENT.md](../deployment/security)
- Runbook: [../deployment/RUNBOOK.md](../operations/runbook)
- Incident response: [../deployment/INCIDENT_RESPONSE.md](../operations/incident-response)

## Architecture and Core Concepts

- Architecture: [../architecture/ARCHITECTURE.md](../core-concepts/architecture)
- Debate internals: [../debate/DEBATE_INTERNALS.md](../core-concepts/debate-internals)
- Execution safety gate: [../debate/EXECUTION_SAFETY_GATE.md](https://github.com/synaptent/aragora/blob/main/docs/debate/EXECUTION_SAFETY_GATE.md)
- Agent system: [../debate/AGENTS.md](../core-concepts/agents)
- Knowledge Mound: [../knowledge/KNOWLEDGE_MOUND.md](../core-concepts/knowledge-mound)
- Workflow engine: [../workflow/WORKFLOW_ENGINE.md](../core-concepts/workflow-engine)

## Contributing and Governance

- Contributing: [../../CONTRIBUTING.md](../contributing/guide)
- Deprecation policy: [DEPRECATION_POLICY.md](../contributing/deprecation)
- Breaking changes: [BREAKING_CHANGES.md](./breaking-changes)
- Status: [../status/STATUS.md](../contributing/status)

## Notes

- This index intentionally avoids deprecated/historical paths.
- Use `python scripts/validate_doc_links.py` to audit broader docs link health.
