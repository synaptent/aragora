# Aragora Enterprise Features Reference

Comprehensive reference for Aragora's enterprise capabilities. All features described here are implemented and tested. Features that are framework-level (requiring organizational process beyond the software) are noted as such.

---

## Table of Contents

1. [Authentication](#authentication)
2. [Authorization (RBAC v2)](#authorization-rbac-v2)
3. [Multi-Tenancy](#multi-tenancy)
4. [Security](#security)
5. [Compliance](#compliance)
6. [Observability](#observability)
7. [Deployment](#deployment)
8. [Disaster Recovery](#disaster-recovery)
9. [Decision Audit](#decision-audit)
10. [Control Plane](#control-plane)

---

## Authentication

### OIDC / SAML SSO

Full single sign-on support for enterprise identity providers.

**OIDC (OpenID Connect)**

| Feature | Details |
|---|---|
| Supported providers | Azure AD, Okta, Google Workspace, Auth0, Keycloak, any OIDC-compliant provider |
| Authorization flow | Authorization Code with PKCE (Proof Key for Code Exchange) |
| Token validation | JWKS-based JWT verification with issuer validation |
| Discovery | Automatic `.well-known/openid-configuration` endpoint discovery |
| Session management | Configurable session TTL, secure token storage |
| Dev mode fallback | Triple-layered production guard with explicit opt-in, never enabled silently |

```python
from aragora.auth.oidc import OIDCProvider, OIDCConfig

config = OIDCConfig(
    client_id="your-client-id",
    client_secret="your-client-secret",
    issuer_url="https://login.microsoftonline.com/tenant-id/v2.0",
    callback_url="https://aragora.example.com/auth/callback",
)

provider = OIDCProvider(config)
auth_url = await provider.get_authorization_url(state="...")
user = await provider.authenticate(code="...")
```

**SAML 2.0**

| Feature | Details |
|---|---|
| Bindings | HTTP-POST, HTTP-Redirect |
| Assertions | Signed and optionally encrypted |
| Attribute mapping | Configurable mapping from SAML attributes to Aragora user fields |
| Unsafe fallback | Dual opt-in required (configuration flag + environment variable), audit logged |

Implementation: `aragora/auth/oidc.py`, `aragora/auth/saml.py`, `aragora/auth/sso.py`

### Multi-Factor Authentication (MFA)

| Feature | Details |
|---|---|
| TOTP | Time-based One-Time Password (RFC 6238), compatible with Google Authenticator, Authy, 1Password |
| HOTP | HMAC-based One-Time Password (RFC 4226) for hardware token support |
| Enforcement | Per-user, per-role, or organization-wide MFA requirements |
| Recovery | Backup codes generated at enrollment |
| Bypass audit | MFA bypass attempts are logged to the security audit trail |

### SCIM 2.0 Provisioning

Automatic user lifecycle management from identity providers.

| Feature | Details |
|---|---|
| User provisioning | Automatic creation on IdP assignment |
| User deprovisioning | Automatic deactivation on IdP removal |
| Group sync | IdP groups map to Aragora roles |
| Attribute sync | Display name, email, department, and custom attributes |
| Compliance | SCIM 2.0 specification (RFC 7644) |

### API Key Management

| Feature | Details |
|---|---|
| Key generation | Cryptographically secure API key generation |
| Key rotation | Scheduled rotation with configurable overlap periods |
| Scoping | Keys can be scoped to specific resources, operations, or IP ranges |
| Rate limiting | Per-key rate limits with distributed enforcement |
| Revocation | Immediate revocation with audit trail |

---

## Authorization (RBAC v2)

Fine-grained role-based access control with hierarchical permissions.

### Permission Model

Permissions are defined as `(ResourceType, Action, Scope)` tuples:

- **15 resource types**: Debate, Agent, Workflow, Document, Memory, Culture, KnowledgeNode, AuditSession, AuditFinding, TrainingJob, SpecialistModel, Workspace, Organization, Billing, APIKey
- **8 actions**: Create, Read, Update, Delete, Execute, Export, Share, Admin
- **4 scope levels**: Global, Organization, Workspace, Resource

**420+ named permissions** across all resource domains, including debates, agents, users, organizations, API keys, memory, workflows, analytics, knowledge, provenance, connectors, devices, repositories, webhooks, gauntlet, marketplace, explainability, findings, decisions, policies, compliance, control plane, finance, receipts, scheduling, billing, sessions, approvals, templates, roles, backups, disaster recovery, data governance (classification, retention, lineage, PII), computer use, and more.

### Default Roles

| Role | Scope | Description |
|---|---|---|
| **Superadmin** | Global | Full system access across all resources and scopes |
| **Org Admin** | Organization | Full access within an organization |
| **Workspace Admin** | Workspace | Full access within a workspace |
| **Workspace Editor** | Workspace | Create, read, update, delete on debates, documents, workflows, and memory |
| **Workspace Viewer** | Workspace | Read-only access to all workspace resources |
| **Auditor** | Workspace | Create, read, and execute audit sessions; read audit findings and documents |
| **ML Engineer** | Organization | Full CRUD on training jobs and specialist models |

Custom roles can be created with any combination of permissions. Roles support hierarchy -- a workspace admin inherits all workspace editor permissions.

### Enforcement

```python
from aragora.rbac.decorators import require_permission
from aragora.rbac.models import AuthorizationContext

@require_permission("backups:read")
async def get_backups(ctx: AuthorizationContext) -> list:
    return await manager.list_backups()
```

- **Decorators**: `@require_permission` and `@require_role` for route-level enforcement
- **Middleware**: HTTP middleware validates route permissions against `SYSTEM_PERMISSIONS` registry at startup; logs warnings for undefined permissions
- **Caching**: `PermissionChecker` with LRU caching for fast repeated checks
- **Audit logging**: All authorization decisions (grant and deny) are recorded

Implementation: `aragora/rbac/models.py`, `aragora/rbac/types.py`, `aragora/rbac/checker.py`, `aragora/rbac/decorators.py`, `aragora/rbac/middleware.py`, `aragora/rbac/audit.py`, `aragora/rbac/defaults/`

---

## Multi-Tenancy

### Tenant Isolation

| Feature | Details |
|---|---|
| Data isolation | Tenant-scoped queries enforced at the data access layer |
| Request context | `IsolationContext` threaded through all request handling with actor ID, org ID, workspace ID |
| Cross-tenant protection | Queries automatically scoped; cross-tenant data access requires explicit superadmin override |
| Namespace isolation | Separate storage namespaces per tenant for debates, memory, knowledge, and receipts |

### Resource Quotas

| Quota Type | Configuration |
|---|---|
| Debates per month | Per-tenant configurable limit |
| Agents per debate | Per-tenant maximum |
| Storage capacity | Per-tenant storage allocation |
| API request rate | Per-tenant rate limits with distributed enforcement |
| Concurrent debates | Per-tenant concurrent execution limit |

### Usage Metering

| Feature | Details |
|---|---|
| Real-time tracking | Per-tenant usage counters for debates, API calls, storage, and LLM tokens |
| Cost attribution | LLM costs tracked per debate, per agent, per tenant |
| Budget alerts | Configurable thresholds with notification delivery (Slack, Teams, email, webhook) |
| Usage dashboards | Per-tenant usage visualization with cost breakdown and trend analysis |
| Export | Usage data exportable for billing integration |

Implementation: `aragora/tenancy/isolation.py`, `aragora/billing/cost_tracker.py`, `aragora/billing/budget_manager.py`, `aragora/billing/metering.py`, `aragora/billing/forecaster.py`

---

## Security

### Encryption

**At Rest**

| Feature | Details |
|---|---|
| Algorithm | AES-256-GCM authenticated encryption |
| Key derivation | Password/secret-based key derivation with configurable parameters |
| Key versioning | Multiple key versions with automatic selection of current active key |
| Envelope encryption | For large data objects; data key encrypted with master key |
| Field-level encryption | Selective encryption of sensitive fields within records (HIPAA use case) |

```python
from aragora.security.encryption import get_encryption_service

service = get_encryption_service()

# Encrypt with associated data for integrity binding
encrypted = service.encrypt("sensitive data", associated_data="user_123")

# Field-level encryption for records with mixed sensitivity
encrypted_record = service.encrypt_fields(
    {"name": "John", "ssn": "123-45-6789"},
    sensitive_fields=["ssn"]
)
```

**In Transit**

- TLS 1.2+ enforced on all API endpoints
- Certificate management via cert-manager (Kubernetes deployment)
- WebSocket connections secured with the same TLS configuration

### Key Rotation

| Feature | Details |
|---|---|
| Scheduled rotation | Configurable rotation intervals with automatic key generation |
| Overlap period | Old keys remain valid for decryption during rotation transition |
| Version tracking | All encrypted data tagged with key version for deterministic decryption |
| Rotation audit | Key rotation events logged to security audit trail |

Implementation: `aragora/security/encryption.py`, `aragora/security/key_rotation.py`

### SSRF Protection

| Feature | Details |
|---|---|
| URL validation | `validate_webhook_url()` blocks requests to internal networks, localhost, and metadata endpoints |
| Coverage | Enforced at all external integration points (webhooks, connectors, OAuth callbacks) |
| Allow/deny lists | Configurable domain allow and deny lists |

Implementation: `aragora/security/ssrf_protection.py`

### Anomaly Detection

| Feature | Details |
|---|---|
| Pattern detection | Statistical anomaly detection on API access patterns |
| Rate analysis | Unusual request rate detection per user/tenant/IP |
| Behavioral baselines | Adaptive baselines that learn normal usage patterns |
| Alerting | Integration with observability alerting pipeline |

Implementation: `aragora/security/anomaly_detection.py`

### Rate Limiting

| Feature | Details |
|---|---|
| Algorithm | Sliding window with Redis-backed distributed enforcement |
| Fallback | Graceful degradation to in-memory rate limiting when Redis is unavailable |
| Granularity | Per-user, per-API-key, per-tenant, per-IP |
| Circuit breaker | Integrated circuit breaker pattern (threshold=5, cooldown=60s) |
| Security hardening | `builtins.isinstance` monkeypatch check to prevent rate limit bypass |

### Additional Security Features

- **Path traversal protection**: `safe_path()` utility prevents directory traversal in all file operations
- **SQL injection prevention**: SQL identifier validation with regex-based allowlisting
- **Input validation**: Schema validation on all API inputs
- **Security audit logging**: Comprehensive logging of authentication events, authorization decisions, and security-relevant actions
- **SecurityBarrier**: Telemetry redaction to prevent sensitive data leakage in observability pipelines

---

## Compliance

### SOC 2 Controls

Aragora implements technical controls aligned with SOC 2 Trust Service Criteria:

| Control | Implementation |
|---|---|
| CC6.1 - Logical access security | RBAC v2 with 420+ permissions, OIDC/SAML SSO, MFA |
| CC6.5 - Secure data disposal | GDPR deletion scheduler with cascade management and erasure verification |
| CC6.6 - Secure external transmissions | TLS 1.2+ enforced, webhook URL validation, SSRF protection |
| CC7.1 - Detection of unauthorized activity | Anomaly detection, security audit logging, rate limiting |
| CC8.1 - Change management | Nomic Loop safety rails, protected file checksums, automatic backups |
| P4.1 - Data retention and disposal | Configurable retention policies, scheduled deletion with grace periods |

### GDPR

| Capability | Article | Implementation |
|---|---|---|
| Right to erasure | Article 17 | `GDPRDeletionScheduler` with grace period, cascade deletion, and erasure verification |
| Data portability | Article 20 | Data export APIs for all user data |
| Consent management | Article 7 | Consent tracking and withdrawal support |
| Storage limitation | Article 5(1)(e) | Retention policies with automatic enforcement |
| Anonymization | -- | Safe Harbor de-identification standard implementation |

Implementation: `aragora/privacy/deletion.py`, `aragora/privacy/consent.py`, `aragora/privacy/retention.py`, `aragora/privacy/anonymization.py`

### HIPAA

| Feature | Details |
|---|---|
| Field-level encryption | AES-256-GCM encryption of PHI fields within records |
| Access controls | RBAC enforcement on all PHI-containing resources |
| Audit trails | Complete access logging for PHI interactions |
| Data retention | Configurable retention periods meeting HIPAA minimums |
| BAA compatibility | Architecture supports Business Associate Agreement requirements |

**Note:** HIPAA compliance requires organizational safeguards (policies, training, BAA execution) beyond technical controls. Aragora provides the technical infrastructure.

### EU AI Act

Aragora generates compliance artifacts for high-risk AI system requirements:

| Requirement | Article | What Aragora Generates |
|---|---|---|
| Risk management | Article 9 | Adversarial debate surfaces risks; Gauntlet mode stress-tests specifications |
| Event logging | Article 12 | Decision receipts with timestamps, agent identities, and full debate traces |
| Transparency | Article 13 | Provider identity, known risks, output interpretation guides, reasoning traces |
| Human oversight | Article 14 | Confidence scores, dissent trails, split opinion flagging for human review |
| Accuracy & robustness | Article 15 | Multi-model consensus, ELO rankings, Brier calibration scores |

`ComplianceArtifactGenerator` produces Article 12, 13, and 14 artifact bundles with SHA-256 integrity hashing. Artifacts are generated as a byproduct of normal debate operation.

**EU AI Act high-risk enforcement begins August 2, 2026.**

---

## Observability

### Prometheus Metrics

| Metric Category | Examples |
|---|---|
| Debate metrics | Duration, agent count, consensus rate, rounds to convergence |
| API metrics | Request rate, latency (p50/p95/p99), error rate, status code distribution |
| Agent metrics | Response time per provider, failure rate, circuit breaker state |
| Memory metrics | Tier utilization, promotion/demotion rates, cache hit ratio |
| Business metrics | Cost per debate, receipt generation rate, active tenants |

Metrics endpoint compatible with Prometheus scraping. Pre-built Grafana dashboards available.

### Grafana Dashboards

Pre-configured dashboards for:

- Debate performance and convergence tracking
- API health and latency monitoring
- Agent reliability across providers
- Cost tracking and budget utilization
- SLO compliance and error budgets

### OpenTelemetry Tracing

| Feature | Details |
|---|---|
| OTLP export | Full OpenTelemetry Protocol support (6 backend configurations) |
| Trace correlation | Request ID and correlation ID propagated through all service calls |
| Span instrumentation | Automatic spans for debates, agent calls, database operations, and external integrations |
| Context propagation | `contextvars`-based propagation (zero `threading.local` usage across 63+ migrated files) |
| Sampling | Configurable sampling rates for cost control |

Implementation: `aragora/observability/tracing.py`, `aragora/observability/otel.py`, `aragora/observability/otlp_export.py`, `aragora/observability/trace_correlation.py`

### Structured Logging

| Feature | Details |
|---|---|
| Format | JSON structured logging with consistent field naming |
| Trace context | Automatic request ID and correlation ID injection |
| Log levels | Standard Python logging levels with per-module configuration |
| Backends | Console, file, and external log aggregation (6 backend options) |
| SIEM integration | Security event format compatible with SIEM ingestion |

### SLO Monitoring

| Feature | Details |
|---|---|
| SLO definitions | Configurable service level objectives with error budget tracking |
| Alerting | SLO breach alerts via Prometheus alerting rules |
| History | SLO compliance history for reporting |
| Dashboard | SLO status visualization in Grafana |

Implementation: `aragora/observability/slo.py`, `aragora/observability/slo_alert_bridge.py`, `aragora/observability/slo_history.py`, `aragora/observability/alerting.py`

---

## Deployment

### Docker

**Development / Evaluation**

```bash
docker compose -f deploy/docker-compose.yml up
```

**Production**

```bash
docker compose -f deploy/docker-compose.production.yml up -d
```

Includes separate service definitions for the application server, PostgreSQL, Redis, and background workers.

### Kubernetes + Helm

Full Helm chart with production-grade configurations:

| Resource | Description |
|---|---|
| `deployment.yaml` | Application deployment with readiness/liveness probes |
| `service.yaml` | ClusterIP service for internal routing |
| `ingress.yaml` | Ingress with TLS termination |
| `hpa.yaml` | Horizontal Pod Autoscaler with custom metrics support |
| `pdb.yaml` | Pod Disruption Budget for availability during rolling updates |
| `network-policy.yaml` | Network policies restricting pod-to-pod communication |
| `resourcequota.yaml` | Namespace resource quotas |
| `limitrange.yaml` | Per-pod resource limits |
| `configmap.yaml` | Application configuration |
| `secrets.yaml` | Sensitive configuration (integrates with External Secrets Operator) |

**Multi-Region Values**

Per-region value files for multi-region deployment:

- `values-us-east-2.yaml` (US)
- `values-eu-west-1.yaml` (EU, GDPR data residency)
- `values-ap-south-1.yaml` (APAC)

**Supporting Infrastructure**

- Redis cluster with StatefulSet
- PostgreSQL via CloudNativePG (`cnpg-cluster.yaml`)
- External Secrets Operator integration for secrets management
- Cert-manager for TLS certificate lifecycle
- Monitoring alerts (`monitoring/alerts.yaml`)
- Secrets rotation CronJob
- Backup CronJob with verification CronJob

### Terraform

Infrastructure-as-code for AWS:

| Configuration | Description |
|---|---|
| `single-region/` | Single-region EC2 deployment with security groups and IAM |
| `ec2-multiregion/` | Multi-region EC2 deployment with cross-region networking, IAM, and security groups |

Both configurations include security group definitions, IAM roles, variable files, and example `terraform.tfvars`.

### Offline Mode

```bash
aragora serve --offline
```

Sets `ARAGORA_OFFLINE` and `DEMO_MODE` environment variables, configures SQLite backend. No external network dependencies. Suitable for air-gapped and classified environments.

---

## Disaster Recovery

### Backup

| Feature | Details |
|---|---|
| Incremental backups | Only changed data backed up after initial full backup |
| Storage backends | Local filesystem, S3, Google Cloud Storage |
| Compression | gzip compression for backup artifacts |
| Integrity verification | SHA-256 checksums on all backup artifacts |
| Backup verification | Automated verification CronJob (Kubernetes) validates backup integrity |
| SQL injection prevention | SQL identifier validation in backup/restore operations |

```python
from aragora.backup.manager import BackupManager

manager = BackupManager(config)
backup = await manager.create_backup(backup_type="incremental")
verified = await manager.verify_backup(backup.id)
```

### Retention Policies

| Feature | Details |
|---|---|
| Configurable retention | Per-backup-type retention periods |
| Automatic cleanup | Expired backups automatically removed |
| Policy enforcement | Retention policies enforced on schedule |

### Disaster Recovery Drills

| Feature | Details |
|---|---|
| DR drill framework | Automated DR drills to verify recovery procedures |
| Dry-run restore | Validate restore capability without affecting production data |
| RTO/RPO tracking | Recovery time and recovery point objective measurement |

Implementation: `aragora/backup/manager.py`

Kubernetes deployment includes `backup-cronjob.yaml` for scheduled backups and `backup-verification-cronjob.yaml` for automated backup validation.

---

## Decision Audit

### Cryptographic Decision Receipts

Every debate produces a tamper-evident Decision Receipt:

| Component | Details |
|---|---|
| Debate transcript | Full record of every proposal, critique, revision, and vote |
| Agent positions | Each model's initial position, intermediate revisions, and final stance |
| Consensus proof | Voting breakdown, consensus type (majority/unanimous/judge), confidence level |
| Dissent trail | Explicit record of disagreements, minority positions, and unresolved critiques |
| Calibration scores | ELO ratings and Brier scores of participating agents at time of debate |
| Hash chain | SHA-256 content-addressable hashing for tamper evidence |
| Cryptographic signing | HMAC-SHA256, RSA-SHA256, or Ed25519 signing backends |
| Timestamps | UTC timestamps for all events with microsecond precision |

### Export Formats

| Format | Use Case |
|---|---|
| Markdown | Human-readable reports, documentation |
| HTML | Web-viewable reports with styling |
| PDF | Formal documents for compliance teams and boards |
| SARIF | Static Analysis Results Interchange Format for developer tool integration |
| CSV | Data analysis and spreadsheet import |

### Gauntlet Defense

Adversarial stress-testing with attack/defend cycles:

| Attack Type | What It Tests |
|---|---|
| Red Team | Security holes, injection points, authentication bypasses |
| Devil's Advocate | Logic flaws, hidden assumptions, edge cases |
| Scaling Critic | Performance bottlenecks, single points of failure, thundering herd |
| Compliance | GDPR, HIPAA, SOC 2, EU AI Act violations |

The `proposer_agent` parameter enables attack/defend cycles where a designated agent defends the specification while adversarial agents probe for weaknesses.

### Full Debate Trace

Every debate action is recorded with:

- Agent identity and provider
- Timestamp (UTC, microsecond)
- Action type (propose, critique, revise, vote, synthesize)
- Content (full text of each contribution)
- Severity scores (for critiques)
- Vote weights (calibrated by ELO and Brier scores)
- Correlation IDs for end-to-end tracing

Traces integrate with OpenTelemetry for distributed tracing across the full request lifecycle.

---

## Control Plane

### Agent Registry

| Feature | Details |
|---|---|
| Agent discovery | Centralized registry of available agents with capabilities and status |
| Heartbeat monitoring | Periodic heartbeat checks with configurable timeout |
| Health status | Per-agent health status (healthy, degraded, unhealthy, unknown) |
| Capability tags | Agents tagged with domains, strengths, and supported operations |
| Auto-registration | Agents register on startup, deregister on graceful shutdown |

### Task Scheduler

| Feature | Details |
|---|---|
| Priority-based scheduling | Task queue with configurable priority levels |
| Task distribution | Load-balanced distribution across available agents |
| Task lifecycle | Submit, claim, execute, complete/fail lifecycle with timeout handling |
| Retry policies | Configurable retry with exponential backoff |
| Dead letter queue | Failed tasks routed to DLQ for investigation |

### Health Monitoring

| Feature | Details |
|---|---|
| Liveness probes | HTTP-based liveness checks for Kubernetes integration |
| Readiness probes | Service dependency checks (database, Redis, external APIs) |
| Dependency health | Aggregate health status across all dependencies |
| Health history | Historical health data for trend analysis |

### Policy Governance

| Feature | Details |
|---|---|
| Policy definitions | Declarative policy rules governing agent behavior and debate protocols |
| Conflict detection | `PolicyConflictDetector` identifies contradictory policies before they cause issues |
| Policy cache | `RedisPolicyCache` for distributed fast policy evaluation |
| Policy sync | `PolicySyncScheduler` for continuous background synchronization |
| Policy versioning | Version tracking with rollback capability |

### Notifications

| Feature | Details |
|---|---|
| Omnichannel delivery | Debate results and alerts delivered to Slack, Teams, email, and webhooks |
| Notification routing | Configurable routing rules based on debate type, severity, and team |
| Receipt delivery | Decision receipts auto-delivered to configured channels |
| Rate limiting | Notification rate limiting to prevent alert fatigue |

Implementation: `aragora/control_plane/policy.py`, `aragora/control_plane/scheduler.py`, `aragora/control_plane/registry.py`, `aragora/control_plane/health.py`, `aragora/control_plane/coordinator.py`, `aragora/control_plane/notifications.py`

1,500+ tests covering the control plane subsystem.

---

## Summary

| Capability | Key Numbers |
|---|---|
| Authentication | OIDC + SAML SSO, MFA (TOTP/HOTP), SCIM 2.0, API key management |
| Authorization | 420+ permissions, 7 default roles, 4 scope levels, 15 resource types |
| Multi-tenancy | Full isolation, resource quotas, usage metering, cost attribution |
| Encryption | AES-256-GCM, field-level encryption, key rotation with versioning |
| Compliance | SOC 2 controls, GDPR (Art. 17/20), HIPAA framework, EU AI Act artifacts |
| Observability | Prometheus, Grafana, OpenTelemetry (6 backends), structured logging, SLO monitoring |
| Deployment | Docker, Kubernetes + Helm, Terraform (single/multi-region), offline mode |
| Disaster recovery | Incremental backups (local/S3/GCS), retention policies, DR drills |
| Decision audit | Cryptographic receipts (SHA-256 + HMAC/RSA/Ed25519), Gauntlet defense, full trace |
| Control plane | Agent registry, task scheduler, health monitoring, policy governance, 1,500+ tests |

---

*See [COMMERCIAL_OVERVIEW.md](COMMERCIAL_OVERVIEW.md) for pricing and deployment tiers. See [WHY_ARAGORA.md](WHY_ARAGORA.md) for competitive positioning. See [status/STATUS.md](status/STATUS.md) for detailed feature implementation status.*
