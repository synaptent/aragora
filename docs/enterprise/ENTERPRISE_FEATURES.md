# Aragora Enterprise Features

*Comprehensive reference for enterprise-grade capabilities*

This document details the enterprise-specific features available in Aragora, organized by category. For commercial positioning and readiness assessment, see [COMMERCIAL_OVERVIEW.md](../COMMERCIAL_OVERVIEW.md).

---

## Table of Contents

1. [Authentication & Authorization](#1-authentication--authorization)
2. [Multi-Tenancy](#2-multi-tenancy)
3. [Security Features](#3-security-features)
4. [Compliance & Governance](#4-compliance--governance)
5. [Observability](#5-observability)
6. [Enterprise Connectors](#6-enterprise-connectors)
7. [High Availability](#7-high-availability)
8. [Data Management](#8-data-management)

---

## 1. Authentication & Authorization

### OIDC Integration
**Location**: `aragora/auth/oidc.py`

OpenID Connect support for enterprise SSO:
- Discovery document parsing
- Token validation with JWK verification
- Claims mapping to user profiles
- Session management

```python
from aragora.auth.oidc import OIDCProvider

provider = OIDCProvider(
    issuer="https://your-idp.com",
    client_id="aragora-client",
    client_secret=os.getenv("OIDC_CLIENT_SECRET"),
)
user = await provider.authenticate(token)
```

### SAML Support
**Location**: `aragora/auth/saml.py`

SAML 2.0 integration for enterprise identity providers:
- SP-initiated and IdP-initiated flows
- Assertion validation
- Attribute mapping
- Metadata exchange

### Multi-Factor Authentication
**Location**: `aragora/server/middleware/mfa.py`

MFA support via:
- TOTP (Time-based One-Time Password)
- HOTP (HMAC-based One-Time Password)
- Integration with authenticator apps (Google Authenticator, Authy, etc.)

```python
from aragora.server.middleware.mfa import require_mfa

@require_mfa
def sensitive_endpoint(self, handler, user):
    return {"ok": True}
```

### API Key Management
**Location**: `aragora/server/handlers/auth/handler.py`, `aragora/server/middleware/user_auth.py`

- Key generation with configurable entropy
- Scoped permissions per key
- Expiration and rotation
- Usage tracking per key

### Session Management
**Location**: `aragora/server/session_store.py`

- Token versioning for revocation
- Lockout tracking (brute force protection)
- Session cleanup with daemon threads
- Configurable TTL per session type

### Account Protection
**Location**: `aragora/auth/lockout.py`

- Failed attempt tracking
- Progressive lockout delays
- IP-based and user-based tracking
- Automatic unlock after cooldown

### SCIM 2.0 Provisioning
**Location**: `aragora/auth/scim/`

Automated user and group provisioning per RFC 7643/7644:
- **User CRUD**: Create, read, update (PUT/PATCH), delete users
- **Group CRUD**: Create, read, update (PUT/PATCH), delete groups with member management
- **Filtering**: Full SCIM filter support (eq, ne, co, sw, ew, pr, gt, ge, lt, le, and, or)
- **Pagination**: 1-indexed pagination with configurable page sizes (up to 1000)
- **Soft Delete**: Users marked inactive by default (configurable hard delete)
- **Bearer Token Auth**: Dedicated SCIM bearer token separate from API auth
- **Multi-Tenant**: Optional tenant isolation via `SCIM_TENANT_ID`

**Supported Identity Providers**:
- Okta (SCIM 2.0 integration)
- Azure Active Directory (Enterprise app provisioning)
- OneLogin (SCIM provisioning)
- Any SCIM 2.0 compliant IdP

**Configuration**:
```bash
SCIM_BEARER_TOKEN=your-scim-token    # Required: Bearer token for SCIM endpoints
SCIM_TENANT_ID=tenant-id             # Optional: Multi-tenant isolation
SCIM_BASE_URL=https://api.example.com  # Optional: Base URL for resource locations
```

---

## 2. Multi-Tenancy

### Tenant Isolation
**Location**: `aragora/tenancy/isolation.py`

Complete data isolation between tenants:
- SQL query auto-filtering by tenant ID
- Tenant context injection into all operations
- Cross-tenant access prevention

```python
from aragora.tenancy import TenantContext

async with TenantContext(tenant_id="acme-corp"):
    # All operations scoped to this tenant
    debates = await debate_store.list()  # Only ACME debates
```

### Resource Quotas
**Location**: `aragora/tenancy/quotas.py`

Per-tenant resource limits:
- Debate count limits
- API call rate limits
- Storage quotas
- Concurrent execution limits

```python
from aragora.tenancy.quotas import QuotaManager

quotas = QuotaManager(tenant_id="acme-corp")
if not quotas.can_create_debate():
    raise QuotaExceededError("Debate limit reached")
```

### Usage Metering
**Location**: `aragora/billing/metering.py`

- Tenant-aware usage tracking
- BillingEvent collection with periodic flush
- Per-tenant cost calculation
- Usage projections and alerts

### Tenant Configuration
**Location**: `aragora/tenancy/context.py`

- Thread-safe tenant context management
- Async-safe context propagation
- Tenant-specific settings override
- Feature flag support per tenant

---

## 3. Security Features

### Encryption at Rest
**Location**: `aragora/security/encryption.py`

AES-256-GCM authenticated encryption:
- Master key management
- Key derivation via PBKDF2-SHA256 (100k iterations)
- Key rotation with versioning
- Field-level encryption for sensitive data

```python
from aragora.security.encryption import EncryptionService

service = EncryptionService(master_key=os.getenv("MASTER_KEY"))
encrypted = service.encrypt(sensitive_data)
decrypted = service.decrypt(encrypted)
```

### Input Validation
**Location**: `aragora/server/validation/`

Comprehensive validation framework:
- JSON body size limits (1MB default)
- Content-type validation
- Query parameter validation
- Schema-based validation
- Path traversal protection

### Rate Limiting
**Location**: `aragora/server/rate_limit.py`, `aragora/server/handlers/utils/rate_limit.py`

Multi-layer rate limiting:
- IP-based: 1000 req/min per IP
- Token-based: Per API key limits
- Endpoint-based: Custom per-endpoint limits
- Token bucket algorithm with burst support
- Redis backend for distributed systems

```bash
# Configuration
ARAGORA_RATE_LIMIT_DEFAULT=60      # req/min
ARAGORA_RATE_LIMIT_IP=1000         # req/min per IP
ARAGORA_RATE_LIMIT_BURST=10        # burst allowance
ARAGORA_RATE_LIMIT_FAIL_OPEN=false # fail-open mode
```

### Circuit Breaker
**Location**: `aragora/resilience.py`

Fault tolerance pattern:
- Configurable failure thresholds
- Automatic cooldown periods (60s default)
- Thread-safe global registry
- Per-service tracking
- Agent-specific breakers

### Security Barrier
**Location**: `aragora/debate/security_barrier.py`

Telemetry and content protection:
- API key redaction from logs
- Token pattern sanitization
- Error message filtering
- Audit-safe output generation

---

## 4. Compliance & Governance

### Audit Trail
**Location**: `aragora/audit/`

Tamper-evident logging:
- Immutable log entries
- Content-addressable hashing
- Chain integrity verification
- Export for compliance review

```python
from aragora.audit import AuditLogger

logger = AuditLogger()
await logger.log_event(
    event_type="DEBATE_CREATED",
    actor=user_id,
    resource=debate_id,
    details={"topic": topic}
)
```

### SOC 2 Compliance
**Location**: `docs/COMPLIANCE.md`

SOC 2 Type II controls documentation:
- Access control policies
- Change management procedures
- Incident response plans
- Data handling policies

### GDPR Support
**Location**: `aragora/privacy/`, `docs/GDPR.md`

GDPR Article mappings:
- Right to access (DSAR workflow)
- Right to erasure
- Data portability export
- Consent management

### Data Classification
**Location**: `docs/DATA_CLASSIFICATION.md`

Data handling policies:
- Public, Internal, Confidential, Restricted tiers
- Handling procedures per tier
- Encryption requirements
- Retention policies

### EU AI Act Compliance
**Location**: `aragora/compliance/`, `docs/compliance/EU_AI_ACT_GUIDE.md`

> **Enforcement date: August 2, 2026.** EU AI Act obligations for high-risk AI systems
> become legally enforceable on this date. Aragora's compliance CLI provides audit-ready
> artifact bundles to meet these requirements.

- Risk classification and documentation
- Conformity assessment artifact generation (`aragora compliance export`)
- Transparency and explainability logs
- Human oversight controls and audit trails
- Continuous compliance monitoring

```bash
# Generate EU AI Act compliance bundle
aragora compliance export --format eu-ai-act --output ./compliance-bundle
```

### Incident Response
**Location**: `docs/INCIDENT_RESPONSE.md`

Incident management:
- Severity classification
- Escalation procedures
- Communication templates
- Post-incident review

---

## 5. Observability

### Prometheus Metrics
**Location**: `aragora/observability/metrics.py`

14+ custom metrics:
- `aragora_request_count` - Request counter by endpoint
- `aragora_request_latency` - Response time histogram
- `aragora_agent_calls` - Agent invocation counter
- `aragora_agent_latency` - Agent response time
- `aragora_active_debates` - Concurrent debate gauge
- `aragora_consensus_rate` - Consensus achievement rate
- `aragora_memory_operations` - Memory tier operations
- `aragora_websocket_connections` - Active WS connections
- `aragora_cache_hits` / `aragora_cache_misses`
- `aragora_debate_phase_duration` - Per-phase timing

```bash
# Metrics endpoint
curl http://localhost:9090/metrics
```

### Grafana Dashboards
**Location**: `deploy/grafana/`

Pre-built dashboards:
- System overview
- Debate performance
- Agent health
- Memory utilization
- Error rates

### OpenTelemetry Tracing
**Location**: `aragora/observability/tracing.py`

Distributed tracing support:
- Automatic trace ID injection
- Context propagation across services
- Span attributes for debugging
- Configurable sampling rates

### Structured Logging
**Location**: `aragora/observability/logging.py`

JSON-formatted production logs:
- Correlation context tracking (trace_id, span_id, debate_id)
- Log rotation with configurable limits
- Multiple backend support
- SIEM integration

```bash
# Configuration
ARAGORA_LOG_LEVEL=INFO
ARAGORA_LOG_FORMAT=json  # or 'text'
ARAGORA_LOG_FILE=/var/log/aragora/app.log
ARAGORA_LOG_MAX_BYTES=10485760  # 10MB
ARAGORA_LOG_BACKUP_COUNT=5
```

Structured logging redacts sensitive fields (auth tokens, payment data, PII,
session identifiers, and key material) before output.

### SLO Framework
**Location**: `aragora/observability/slo.py`

Service Level Objective tracking:
- Response time targets
- Availability thresholds
- Error rate budgets
- Automatic alerting on breach

---

## 6. Enterprise Connectors

### Chat Platforms

| Platform | Location | Capabilities |
|----------|----------|--------------|
| **Slack** | `aragora/connectors/chat/slack/` | Messages, channels, threads, evidence collection |
| **Discord** | `aragora/connectors/chat/discord.py` | Guilds, channels, DMs, reactions |
| **Teams** | `aragora/connectors/chat/teams.py` | Teams, channels, meetings |
| **Google Chat** | `aragora/connectors/chat/google_chat.py` | Spaces, messages |

### Data Sources

| Source | Location | Capabilities |
|--------|----------|--------------|
| **GitHub** | `aragora/connectors/enterprise/git/github.py` | Repos, PRs, issues, code search |
| **ArXiv** | `aragora/connectors/arxiv.py` | Paper search, metadata, PDFs |
| **Wikipedia** | `aragora/connectors/wikipedia.py` | Article content, references |
| **SEC Filings** | `aragora/connectors/sec.py` | Company filings, financial data |
| **Local Docs** | `aragora/connectors/local_docs.py` | File system documents |

### Enterprise Systems

| System | Location | Capabilities |
|--------|----------|--------------|
| **SharePoint** | `aragora/connectors/enterprise/documents/` | Document libraries, metadata |
| **Confluence** | `aragora/connectors/enterprise/collaboration/` | Pages, spaces, attachments |
| **Notion** | `aragora/connectors/enterprise/collaboration/` | Databases, pages |
| **PostgreSQL** | `aragora/connectors/enterprise/database/postgres.py` | Table sync, LISTEN/NOTIFY |
| **MongoDB** | `aragora/connectors/enterprise/database/mongodb.py` | Document queries |
| **MySQL** | `aragora/connectors/enterprise/database/mysql.py` | Table sync, binlog CDC |
| **SQL Server** | `aragora/connectors/enterprise/database/sqlserver.py` | Table sync, CDC/Change Tracking |
| **Snowflake** | `aragora/connectors/enterprise/database/snowflake.py` | Table sync, time travel |

### Healthcare (HL7/FHIR)
**Location**: `aragora/connectors/enterprise/healthcare/`

Healthcare system integration:
- HL7v2 message parsing
- FHIR resource queries
- Patient data handling (HIPAA-compliant)
- Clinical document support

---

## 7. High Availability

### Connection Pooling
**Location**: `aragora/server/connection_pool.py`

Adaptive connection management:
- Min/max connections with overflow
- Health monitoring (30s intervals)
- Idle timeout (5 min default)
- Graceful degradation on exhaustion

```bash
# Configuration
ARAGORA_POOL_MIN_CONNECTIONS=5
ARAGORA_POOL_MAX_CONNECTIONS=50
ARAGORA_POOL_IDLE_TIMEOUT=300
ARAGORA_POOL_HEALTH_CHECK_INTERVAL=30
```

### Database Backends
**Location**: `aragora/db/backends.py`

Multi-backend support:
- SQLite for development/single-node
- PostgreSQL for production scale
- Parameter placeholder translation
- Connection validation

### Caching
**Location**: `aragora/cache.py`

Unified cache infrastructure:
- TTLCache: In-memory LRU with TTL
- RedisTTLCache: Redis-backed distributed cache
- HybridTTLCache: Intelligent backend selection
- Per-cache statistics tracking

### Redis Cluster
**Location**: `aragora/server/redis_cluster.py`

Redis cluster support:
- Cluster-aware connections
- Automatic failover
- Distributed rate limiting
- Session storage

---

## 8. Data Management

### Database Migration
**Location**: `aragora/persistence/schemas/`

Schema management:
- Version-controlled migrations
- Rollback support
- Dry-run validation
- Multi-database support

### Backup & Recovery
**Location**: `docs/DISASTER_RECOVERY.md`

Disaster recovery procedures:
- RTO/RPO definitions
- Backup procedures
- Restore verification
- Failover runbooks

### Data Export
**Location**: `aragora/server/handlers/training.py`

Export capabilities:
- Training data (SFT, DPO, Gauntlet formats)
- Debate transcripts (JSON, HTML)
- Knowledge graphs (GraphML, D3 JSON)
- Audit logs (CSV, JSON)

### Data Retention
**Location**: `aragora/privacy/retention.py`

Retention policy enforcement:
- Configurable per data type
- Automatic cleanup jobs
- Archive before delete option
- Compliance hold support

---

## Configuration Reference

### Environment Variables

```bash
# Authentication
ARAGORA_API_TOKEN=your-secret-token
ARAGORA_TOKEN_TTL=3600
ARAGORA_OIDC_ISSUER=https://your-idp.com
ARAGORA_OIDC_CLIENT_ID=aragora-client
ARAGORA_OIDC_CLIENT_SECRET=secret

# Security
ARAGORA_ALLOWED_ORIGINS=https://your-domain.com
ARAGORA_ENCRYPTION_KEY=base64-encoded-key
ARAGORA_WS_MAX_MESSAGE_SIZE=65536

# Database
ARAGORA_DATABASE_URL=postgresql://user:pass@host/db
ARAGORA_POOL_SIZE=20
ARAGORA_POOL_MAX_OVERFLOW=10

# Redis
ARAGORA_REDIS_URL=redis://localhost:6379
ARAGORA_REDIS_CLUSTER=false

# Observability
ARAGORA_LOG_LEVEL=INFO
ARAGORA_LOG_FORMAT=json
METRICS_ENABLED=true
METRICS_PORT=9090

# Rate Limiting
ARAGORA_RATE_LIMIT_DEFAULT=60
ARAGORA_RATE_LIMIT_IP=1000
ARAGORA_RATE_LIMIT_FAIL_OPEN=false
```

---

## Getting Started with Enterprise Features

### 1. Enable Multi-Tenancy

```python
# In your application setup
from aragora.tenancy import enable_multi_tenancy

enable_multi_tenancy(
    isolation_level="strict",
    quota_enforcement=True,
    metering=True,
)
```

### 2. Configure SSO

```bash
# Environment variables
export ARAGORA_OIDC_ISSUER=https://your-idp.com
export ARAGORA_OIDC_CLIENT_ID=aragora-client
export ARAGORA_OIDC_CLIENT_SECRET=your-secret
```

### 3. Enable Metrics

```bash
# Start with metrics enabled
export METRICS_ENABLED=true
export METRICS_PORT=9090
aragora serve
```

### 4. Set Up Audit Logging

```python
from aragora.audit import configure_audit

configure_audit(
    storage="postgresql",  # or "immutable_log"
    retention_days=365,
    export_format="json",
)
```

---

## Support

For enterprise support inquiries, see the [ENTERPRISE_SUPPORT.md](ENTERPRISE_SUPPORT.md) document.

---

*Document reflects capabilities discovered through comprehensive codebase exploration (January 2026).*
