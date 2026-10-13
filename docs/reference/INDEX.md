# Documentation Index

Canonical documentation lives in `docs/` and is mirrored into `docs-site/`.

This index is scoped to high-signal, actively maintained docs with validated paths.

## Start Here

- Project overview: [../README.md](../README.md)
- First-time setup: [../guides/GETTING_STARTED.md](../guides/GETTING_STARTED.md)
- Install matrix (per-audience, per-distribution): [INSTALL_MATRIX.md](INSTALL_MATRIX.md)
- Developer quickstart: [../quickstart.md](../quickstart.md)
- SDK guide: [../SDK_GUIDE.md](../SDK_GUIDE.md)
- Capability matrix: [../CAPABILITY_MATRIX.md](../CAPABILITY_MATRIX.md)

## CLI and Runtime

- CLI reference (generated): [CLI_REFERENCE.md](CLI_REFERENCE.md)
- Environment variables: [ENVIRONMENT.md](ENVIRONMENT.md)
- Full environment reference: [ENVIRONMENT_COMPLETE.md](ENVIRONMENT_COMPLETE.md)
- Library usage: [LIBRARY_USAGE.md](LIBRARY_USAGE.md)
- Receipt contract: [../RECEIPT_CONTRACT.md](../RECEIPT_CONTRACT.md)

## API and Protocols

- API reference: [../api/API_REFERENCE.md](../api/API_REFERENCE.md)
- Endpoint catalog: [../api/API_ENDPOINTS.md](../api/API_ENDPOINTS.md)
- API examples: [../api/API_EXAMPLES.md](../api/API_EXAMPLES.md)
- Versioning policy: [../api/API_VERSIONING.md](../api/API_VERSIONING.md)
- Webhooks: [../api/WEBHOOKS.md](../api/WEBHOOKS.md)

## Deployment and Operations

- Production deployment: [../deployment/PRODUCTION_DEPLOYMENT.md](../deployment/PRODUCTION_DEPLOYMENT.md)
- Deployment guide: [../DEPLOYMENT.md](../DEPLOYMENT.md)
- Security deployment: [../deployment/SECURITY_DEPLOYMENT.md](../deployment/SECURITY_DEPLOYMENT.md)
- Runbook: [../deployment/RUNBOOK.md](../deployment/RUNBOOK.md)
- Incident response: [../deployment/INCIDENT_RESPONSE.md](../deployment/INCIDENT_RESPONSE.md)

## Architecture and Core Concepts

- Architecture: [../architecture/ARCHITECTURE.md](../architecture/ARCHITECTURE.md)
- Debate internals: [../debate/DEBATE_INTERNALS.md](../debate/DEBATE_INTERNALS.md)
- Execution safety gate: [../debate/EXECUTION_SAFETY_GATE.md](../debate/EXECUTION_SAFETY_GATE.md)
- Agent system: [../debate/AGENTS.md](../debate/AGENTS.md)
- Knowledge Mound: [../knowledge/KNOWLEDGE_MOUND.md](../knowledge/KNOWLEDGE_MOUND.md)
- Workflow engine: [../workflow/WORKFLOW_ENGINE.md](../workflow/WORKFLOW_ENGINE.md)

## Contributing and Governance

- Contributing: [../../CONTRIBUTING.md](../../CONTRIBUTING.md)
- Deprecation policy: [DEPRECATION_POLICY.md](DEPRECATION_POLICY.md)
- Breaking changes: [BREAKING_CHANGES.md](BREAKING_CHANGES.md)
- Status: [../status/STATUS.md](../status/STATUS.md)

## Configuration and Data

- Configuration reference: [CONFIGURATION.md](CONFIGURATION.md)
- Choosing dependencies and install extras: [DEPENDENCIES.md](DEPENDENCIES.md)
- Database architecture: [DATABASE.md](DATABASE.md)
- Database schema: [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md)
- Canonical stores for convoys, beads, gateway and inbox: [CANONICAL_STORES.md](CANONICAL_STORES.md)
- Document ingestion: [DOCUMENTS.md](DOCUMENTS.md)

## Server, Errors and Administration

- HTTP handler index: [HANDLERS.md](HANDLERS.md)
- Message binding router: [BINDINGS.md](BINDINGS.md)
- Control plane: [CONTROL_PLANE.md](CONTROL_PLANE.md)
- Admin console: [ADMIN.md](ADMIN.md)
- Error codes: [ERROR_CODES.md](ERROR_CODES.md)
- Error handling patterns: [ERROR_HANDLING.md](ERROR_HANDLING.md)
- Error tracking with Sentry: [ERROR_TRACKING.md](ERROR_TRACKING.md)

## Billing and Service Terms

- Billing system: [BILLING.md](BILLING.md)
- Billing units and token metering: [BILLING_UNITS.md](BILLING_UNITS.md)
- Accounting automation with QuickBooks Online: [ACCOUNTING.md](ACCOUNTING.md)
- Service level agreement: [SLA.md](SLA.md)

## Development

- Implementation pipeline (`aragora/implement/`): [IMPLEMENT.md](IMPLEMENT.md)
- Type checking with mypy: [TYPE_CHECKING.md](TYPE_CHECKING.md)
- Repository root allowlist: [ROOT_ALLOWLIST.md](ROOT_ALLOWLIST.md)
- Credits and attribution: [CREDITS.md](CREDITS.md)

## Notes

- This index intentionally avoids deprecated/historical paths.
- Use `python scripts/validate_doc_links.py` to audit broader docs link health.
