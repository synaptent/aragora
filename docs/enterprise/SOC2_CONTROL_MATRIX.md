# SOC 2 Type II Control Matrix

**Document Version:** 1.0
**Last Updated:** 2026-01-29
**Applicable Standard:** AICPA Trust Service Criteria (2017)

This document maps Aragora's security controls to SOC 2 Type II Trust Service Criteria (TSC). Use this matrix for audit preparation, compliance assessments, and vendor security questionnaires.

---

## Summary

| TSC Category | Controls Implemented | Status |
|--------------|---------------------|--------|
| **CC** - Common Criteria | 12 | Production |
| **A** - Availability | 8 | Production |
| **PI** - Processing Integrity | 7 | Production |
| **C** - Confidentiality | 13 | Production |
| **P** - Privacy | 20+ | Production |
| **Total** | **60+** | **Production-Ready** |

---

## CC - Common Criteria (Entity-Level Controls)

### CC1: Control Environment

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| CC1.1 | Security Policy Documentation | Comprehensive security architecture and operational procedures documented | `CLAUDE.md`, `docs/STATUS.md`, `docs/ENTERPRISE_FEATURES.md` | Policy documents in repository |
| CC1.2 | Event Log Integrity | HMAC-SHA256 signed audit events with tamper detection | `aragora/rbac/audit.py:100-132` | `sign_event()`, `verify_signature()` |
| CC1.3 | Structured Event Communication | Enum-based security event types for consistent logging | `aragora/rbac/audit.py:134-176` | `AuditEventType` enum |

### CC2: Risk Assessment

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| CC2.1 | Cascading Failure Detection | Circuit breaker metrics for system health monitoring | `aragora/resilience.py:191-204` | `get_metrics()` method |
| CC2.2 | Health Status Monitoring | Liveness probes and health checking infrastructure | `aragora/resilience_patterns/health.py` | `HealthChecker` class |

### CC3: Fraud Prevention

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| CC3.1 | Brute-Force Prevention | Account lockout with exponential backoff after failed attempts | `aragora/auth/lockout.py:59-71` | `LockoutManager` class |
| CC3.2 | Cross-Tenant Access Detection | Audit logging for attempted tenant isolation violations | `aragora/tenancy/isolation.py:573-600` | Violation logging |

### CC5: Resource Acquisition & Management

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| CC5.1 | Backup Retention Policy | Configurable retention (daily/weekly/monthly tiers) | `aragora/backup/manager.py:144-152` | `RetentionPolicy` dataclass |
| CC5.2 | Tenant Provisioning | Controlled resource allocation for new tenants | `aragora/tenancy/provisioning.py` | `TenantProvisioner` class |

### CC6: Logical & Physical Access Controls

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| CC6.1 | API Key Management | Scoped API keys with expiration, IP whitelist, permission limits | `aragora/rbac/models.py:472-516` | `APIKeyScope` dataclass |
| CC6.2 | Session Management | Session creation, expiration, and revocation audit events | `aragora/rbac/audit.py:148-151` | Session event types |
| CC6.3 | Emergency Access (Break-Glass) | Time-limited emergency access with full audit trail | `aragora/rbac/emergency.py`, `aragora/rbac/audit.py:163-166` | `EmergencyAccess` class |

### CC7: System Operations Monitoring

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| CC7.1 | Privileged User Tracking | Impersonation start/end logging with actor tracking | `aragora/rbac/audit.py:159-160` | Impersonation events |
| CC7.2 | Administrative Action Logging | Policy change audit events | `aragora/rbac/audit.py:158-161` | Policy events |

### CC8: Business Continuity & Disaster Recovery

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| CC8.1 | Backup Management | Full, incremental, and differential backup types with verification | `aragora/backup/manager.py:254-407` | `BackupManager.create_backup()` |
| CC8.2 | Disaster Recovery Testing | Dry-run restore capability for DR drills | `aragora/backup/manager.py:531-589` | `restore_backup(dry_run=True)` |
| CC8.3 | Backup Verification Workflow | Weekly automated backup verification in CI | `.github/workflows/backup-verification.yml` | GitHub Actions workflow |

### CC9: Change Management

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| CC9.1 | Key Rotation | Encryption key version tracking with overlap periods | `aragora/security/encryption.py:556-610` | `rotate_key()` method |
| CC9.2 | Permission Modification Audit | Role creation, deletion, modification events logged | `aragora/rbac/audit.py:142-146` | Role events |

---

## A - Availability

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| A1.1 | Circuit Breaker Pattern | Three-state circuit breaker (CLOSED/OPEN/HALF_OPEN) | `aragora/resilience.py:412-875` | `CircuitBreaker` class |
| A1.2 | Per-Entity Failure Isolation | Individual circuit breakers per agent/service prevent cascading failures | `aragora/resilience.py:545-625` | `MultiEntityCircuitBreaker` |
| A1.3 | Health Check Endpoints | Standardized `/healthz` endpoint for orchestration | `aragora/server/handlers/health.py` | K8s-compatible probes |
| A1.4 | Automatic Recovery | Half-open state with automatic retry after cooldown period | `aragora/resilience.py:676-707` | Recovery logic |
| A1.5 | Backup Integrity Verification | Checksum validation, restore testing, table verification | `aragora/backup/manager.py:408-530` | `verify_backup()` |
| A1.6 | Backup Metadata Tracking | Schema hashing, table checksums, FK tracking | `aragora/backup/manager.py:50-110` | `BackupMetadata` dataclass |
| A1.7 | State Persistence | SQLite persistence for circuit breaker state across restarts | `aragora/resilience.py:925-1118` | Persistent state store |
| A1.8 | Graceful Degradation | Fallback to OpenRouter on primary API quota exhaustion | `aragora/agents/fallback.py` | Automatic failover |

---

## PI - Processing Integrity

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| PI1.1 | Input Validation | Permission validation with wildcard pattern support | `aragora/rbac/models.py:549-565` | `AuthorizationContext.has_permission()` |
| PI1.2 | Referential Integrity Checks | FK constraint verification, orphaned record detection | `aragora/backup/manager.py:914-982` | `_verify_relationships()` |
| PI1.3 | Schema Validation | Column definitions, data types, constraints, index validation | `aragora/backup/manager.py:844-912` | `_verify_schema()` |
| PI1.4 | Data Checksum Verification | SHA-256 checksums per table for corruption detection | `aragora/backup/manager.py:984-1020` | `_calculate_table_checksums()` |
| PI1.5 | Request Tracing | Request IDs for end-to-end tracing | `aragora/rbac/models.py:519-547` | `AuthorizationContext.request_id` |
| PI1.6 | Backup File Integrity | SHA-256 file checksums for backup archives | `aragora/backup/manager.py:1141-1147` | File checksums |
| PI1.7 | Row Count Validation | Stored row counts compared against restored database | `aragora/backup/manager.py:471-509` | Count verification |

---

## C - Confidentiality

### Encryption at Rest

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| C1.1 | AES-256-GCM Encryption | Authenticated encryption for data at rest | `aragora/security/encryption.py:115-223` | `EncryptionManager.encrypt()` |
| C1.2 | Field-Level Encryption | Selective encryption of sensitive fields | `aragora/security/encryption.py:489-554` | `encrypt_fields()` |
| C1.3 | Key Derivation | PBKDF2-SHA256 with 100k iterations | `aragora/security/encryption.py:339-381` | `derive_key()` |
| C1.4 | Key Versioning | Version tracking with auto-rotation support | `aragora/security/encryption.py:294-337` | Key version headers |
| C1.5 | Encryption Enforcement | `ARAGORA_ENCRYPTION_REQUIRED` flag for fail-fast mode | `aragora/security/encryption.py:62-99` | Strict mode |
| C1.6 | Cloud KMS Integration | AWS KMS, Azure Key Vault, GCP KMS, HashiCorp Vault | `aragora/security/kms_provider.py:49-98` | `KMSProvider` class |

### Encryption in Transit

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| C2.1 | OIDC Token Validation | JWT validation via JWKS with RS256/ES256 | `aragora/auth/oidc.py:257-423` | `validate_id_token()` |
| C2.2 | PKCE Support | Proof Key for Code Exchange for authorization flow | `aragora/auth/oidc.py:354-423` | Code challenge/verifier |
| C2.3 | Fail-Closed Validation | Token validation requires issuer and JWKS | `aragora/auth/oidc.py:565-595` | Strict validation |

### Multi-Tenancy Isolation

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| C3.1 | Tenant Context Filtering | Automatic tenant_id injection in queries | `aragora/tenancy/isolation.py:157-182` | `get_tenant_filter()` |
| C3.2 | SQL Injection Prevention | Parameterized queries with tenant binding | `aragora/tenancy/isolation.py:242-298` | Safe query building |
| C3.3 | Namespace Isolation | Resource key prefixing with tenant ID | `aragora/tenancy/isolation.py:370-413` | `get_namespaced_key()` |
| C3.4 | Per-Tenant Encryption Keys | KMS integration for tenant-specific keys | `aragora/tenancy/isolation.py:415-454` | `get_tenant_key()` |

---

## P - Privacy

### Authentication

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| P1.1 | OIDC/SAML SSO | Enterprise SSO with Okta, Azure AD, Google, Keycloak presets | `aragora/auth/oidc.py:140-160`, `aragora/auth/saml.py` | Provider factory methods |
| P1.2 | Multi-Factor Authentication | TOTP/HOTP support | `aragora/server/middleware/mfa.py` | MFA middleware |
| P1.3 | API Key Scoping | Granular permissions with resource restrictions | `aragora/rbac/models.py:472-516` | `APIKeyScope` |
| P1.4 | Token Rotation | Automatic refresh with expiration tracking | `aragora/auth/token_rotation.py` | Rotation logic |
| P1.5 | Session Revocation | Active session tracking and revocation | `aragora/server/middleware/token_revocation.py` | Revocation store |

### Role-Based Access Control

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| P2.1 | Fine-Grained Permissions | 360+ permissions across resource types | `aragora/rbac/models.py:312-356` | `Permission` dataclass |
| P2.2 | Role Hierarchy | Parent role inheritance with priority conflict resolution | `aragora/rbac/models.py:358-405` | `Role.parent` field |
| P2.3 | Time-Bound Assignments | Role assignment expiration with validity checks | `aragora/rbac/models.py:430-468` | `RoleAssignment.valid_until` |
| P2.4 | Conditional Permissions | Attribute-based access control via metadata | `aragora/rbac/conditions.py` | ABAC support |
| P2.5 | Decorator Enforcement | `@require_permission` for route protection | `aragora/rbac/decorators.py` | Decorator pattern |
| P2.6 | Middleware Enforcement | HTTP-level authorization before handlers | `aragora/rbac/middleware.py` | RBAC middleware |

### Audit & Compliance

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| P3.1 | Authorization Audit | Permission granted/denied decision logging | `aragora/rbac/audit.py:315-628` | `AuditLogger` class |
| P3.2 | Event Signing | HMAC-SHA256 signatures for integrity | `aragora/rbac/audit.py:100-132` | `sign_event()` |
| P3.3 | Tamper Detection | Signature verification with alert on mismatch | `aragora/rbac/audit.py:239-267` | `verify_signature()` |
| P3.4 | Role Change Audit | Assignment/revocation with actor tracking | `aragora/rbac/audit.py:381-428` | Role events |
| P3.5 | API Key Audit | Creation/revocation logging | `aragora/rbac/audit.py:430-475` | API key events |
| P3.6 | Break-Glass Audit | Emergency access with full context | `aragora/rbac/audit.py:920-950` | Emergency events |
| P3.7 | Persistent Audit Storage | Batch flushing to PostgreSQL/SQLite | `aragora/rbac/audit.py:679-1054` | `PersistentAuditHandler` |
| P3.8 | Audit Log Database Table | Indexed audit_log table in PostgreSQL | `migrations/sql/001_initial_schema.sql` | SQL schema |

### Rate Limiting & DDoS Protection

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| P4.1 | IP-Based Rate Limiting | Per-IP request limits with token buckets | `aragora/server/middleware/rate_limit/limiter.py:51-100` | IP tracking |
| P4.2 | Token-Based Rate Limiting | Per-API-key quota enforcement | `aragora/server/middleware/rate_limit/limiter.py` | Token tracking |
| P4.3 | Endpoint-Specific Limits | Custom rate limits per endpoint | `aragora/server/middleware/rate_limit/limiter.py:96-100` | Configurable limits |
| P4.4 | Burst Size Control | Token bucket with configurable burst | `aragora/server/middleware/rate_limit/bucket.py` | `TokenBucket` class |
| P4.5 | Memory Management | LRU eviction of stale entries (max 10k) | `aragora/server/middleware/rate_limit/limiter.py` | Entry cleanup |

### Brute-Force Protection

| Control ID | Control | Implementation | File Path | Evidence |
|------------|---------|----------------|-----------|----------|
| P5.1 | Account Lockout | Exponential backoff after failed attempts | `aragora/auth/lockout.py:59-71` | Lockout logic |
| P5.2 | Dual-Factor Tracking | Tracking by email AND IP address | `aragora/auth/lockout.py` | Dual tracking |
| P5.3 | Lockout Persistence | Redis backend with in-memory fallback | `aragora/auth/lockout.py` | Persistent store |
| P5.4 | Adaptive Delays | Increasing lockout duration after repeated failures | `aragora/auth/lockout.py:59-71` | Progressive delays |

---

## Audit Artifacts

### Required Evidence for SOC 2 Audit

| Artifact | Location | Frequency |
|----------|----------|-----------|
| Audit Logs | PostgreSQL `audit_log` table | Continuous |
| Backup Reports | `aragora/backup/` output | Daily |
| DR Test Results | GitHub Actions artifacts | Weekly |
| Access Reviews | RBAC assignment reports | Quarterly |
| Penetration Test | Third-party report | Annual |
| Security Training | HR records | Annual |

### Monitoring & Alerting

| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| Failed Auth Rate | `aragora/auth/lockout.py` | >10/min per IP |
| Circuit Breaker Opens | `aragora/resilience.py` | Any OPEN state |
| Cross-Tenant Access | `aragora/tenancy/isolation.py` | Any violation |
| Backup Failures | `BackupManager` | Any failure |
| Key Rotation Age | `EncryptionManager` | >90 days |

---

## Compliance Gaps & Remediation

| Gap | Priority | Remediation | Target Date |
|-----|----------|-------------|-------------|
| 50 handlers missing RBAC decorators | HIGH | Add `@require_permission` to identified handlers | Q1 2026 |
| Audit log export in compliance formats | MEDIUM | Add PDF/CSV export to `aragora/audit/export.py` | Q1 2026 |
| SIEM integration adapters | LOW | Create Splunk/Datadog/ELK adapters | Q2 2026 |

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-01-29 | Engineering | Initial release |

---

## References

- [AICPA Trust Service Criteria](https://www.aicpa.org/interestareas/frc/assuranceadvisoryservices/trustservices)
- [Aragora Enterprise Features](../ENTERPRISE_FEATURES.md)
- [Aragora Security Architecture](../../CLAUDE.md)
- [Environment Configuration](../reference/ENVIRONMENT.md)
