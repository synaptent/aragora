# Self-Hosted GA Readiness Checklist

Status: **In Progress**
Last updated: March 5, 2026

This checklist tracks all items required before declaring Aragora self-hosted GA (Generally Available). Items are grouped by category with clear pass/fail criteria.

---

## Security

- [x] **Exception handling hardened** - All bare `except Exception: pass` eliminated (375+ commits)
- [x] **Error message sanitization** - No `str(e)` leaks in user-facing responses
- [x] **JWT validation** - `sub` claim validation + insecure decode audit logging
- [x] **Rate limiting** - Enabled by default on all endpoints, configurable per-route
- [x] **RBAC v2** - 360+ permissions, 7 default roles, fine-grained decorators
- [x] **MFA** - TOTP/HOTP support with enforcement toggle
- [x] **Encryption** - AES-256-GCM for data at rest
- [x] **SSRF protection** - Built-in URL validation
- [x] **Skill scanner** - AST-based malware detection for marketplace skills
- [ ] **External penetration test** - Third-party security assessment
  - Blocker: Vendor outreach in progress; kickoff target March 3, 2026 (may have occurred)
- [x] **Dependency audit** - Trivy scans in CI (CRITICAL/HIGH severity gate)

## Authentication & Authorization

- [x] **OIDC/SAML SSO** - Enterprise single sign-on
- [x] **API key management** - Create, rotate, revoke API tokens
- [x] **SCIM 2.0 provisioning** - Automated user lifecycle from IdP
- [x] **Multi-tenancy** - Tenant isolation with resource quotas
- [x] **Workspace admin UI** - Members, roles, settings, activity feed

## Data & Storage

- [x] **PostgreSQL support** - Production database with connection pooling
- [x] **SQLite fallback** - Offline/development mode
- [x] **Redis HA** - High-availability caching
- [x] **Database migrations** - Automatic on startup, advisory lock protection
- [x] **Backup/restore** - `BackupManager` with incremental support
- [x] **Data retention policies** - Configurable per-workspace
- [x] **Encryption at rest** - AES-256-GCM for sensitive fields

## Observability

- [x] **Prometheus metrics** - `/metrics` endpoint with custom counters
- [x] **Grafana dashboards** - Pre-configured via Docker Compose profile
- [x] **OpenTelemetry tracing** - Distributed tracing with OTLP export
- [x] **Structured logging** - JSON logs with correlation IDs
- [x] **SLO alerting** - Configurable targets with Prometheus alert rules
- [x] **Health endpoints** - `/healthz` (liveness), `/readyz` (readiness), `/health` (detailed)
- [x] **Log aggregation** - Loki + Promtail configuration included

## API & SDK

- [x] **REST API** - 3,000+ operations across 2,900+ paths
- [x] **WebSocket streaming** - 190+ event types
- [x] **Python SDK** - `aragora-sdk` with full API parity
- [x] **TypeScript SDK** - `@aragora/sdk` with 136/136 namespaces
- [x] **OpenAPI spec** - Auto-generated with operation IDs and descriptions
- [x] **Cost estimation endpoint** - Pre-debate cost preview
- [x] **SDK Quickstart** - 5-minute integration guide

## Deployment

- [x] **Docker Compose** - Production-ready with profiles (monitoring, workers)
- [x] **Kubernetes manifests** - HPA, health probes, external secrets
- [x] **TLS documentation** - Traefik and Nginx reverse proxy guides
- [x] **Offline mode** - `aragora serve --offline` for air-gapped environments
- [x] **Upgrade runbook** - Database migrations, rollback procedures
- [x] **Production hardening checklist** - In `docs/DEPLOYMENT.md`

## Testing

- [x] **Test suite** - 208,000+ tests across 4,000+ files
- [x] **Handler tests** - 19,776 tests, 0 failures across randomized seeds
- [x] **CI pipeline** - GitHub Actions with path-based triggers
- [x] **Randomized ordering** - Seeds 12345, 54321, 99999 all pass
- [x] **E2E smoke tests** - Docker-based integration tests in CI
- [x] **Load testing** - Locust suite with 6 user types + k6 scenarios

## Compliance

> **EU AI Act enforcement: August 2, 2026** — compliance CLI artifact export is a key enterprise selling point. Ensure Articles 9, 12-15 artifact generation is complete before this date.

- [x] **SOC 2 controls** - Audit logging, access control, encryption
- [x] **GDPR support** - Data deletion, consent management, retention policies
- [x] **HIPAA readiness** - Anonymization, audit trails, BAA template
- [x] **EU AI Act** - Article 12/13/14 artifact generation
- [x] **Decision receipts** - SHA-256 signed audit trails

## Documentation

- [x] **Deployment guide** - Three paths (local, Docker, K8s)
- [x] **SDK quickstart** - Python + TypeScript integration guide
- [x] **API reference** - REST + WebSocket documentation
- [x] **Vertical guides** - Healthcare, Financial, Legal
- [x] **Self-improvement guide** - Nomic Loop and autonomous orchestration

---

## GA Blockers

| Blocker | Owner | Status | ETA |
|---------|-------|--------|-----|
| External pen test | Security | Vendor outreach in progress | Kickoff target: March 3, 2026 (may have occurred) |

## GA Criteria Summary

| Category | Status | Score |
|----------|--------|-------|
| Security | 10/11 | 91% |
| Auth | 5/5 | 100% |
| Data | 7/7 | 100% |
| Observability | 7/7 | 100% |
| API & SDK | 7/7 | 100% |
| Deployment | 6/6 | 100% |
| Testing | 6/6 | 100% |
| Compliance | 5/5 | 100% |
| Documentation | 5/5 | 100% |
| **Total** | **58/59** | **98%** |

**Only blocker: External penetration test.** Everything else is GA-ready.
