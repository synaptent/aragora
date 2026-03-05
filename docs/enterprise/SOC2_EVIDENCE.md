# SOC 2 Compliance Evidence

This document describes how Aragora addresses SOC 2 Trust Service Criteria and where to find evidence for each control.

## Trust Service Criteria Overview

| Category | Criteria | Status |
|----------|----------|--------|
| Security | CC1-CC9 | Implemented |
| Availability | A1 | Implemented |
| Confidentiality | C1 | Implemented |
| Processing Integrity | PI1 | Implemented |

## Security (Common Criteria)

### CC1: Control Environment

**CC1.1 - Organization and Management**

| Control | Evidence Location |
|---------|-------------------|
| Security policies | `docs/SECURITY_TESTING.md` |
| Code of conduct | `CONTRIBUTING.md` |
| Organizational structure | GitHub team permissions |

### CC2: Communication and Information

**CC2.1 - Internal Communication**

| Control | Evidence Location |
|---------|-------------------|
| Security documentation | `docs/SECURITY_TESTING.md` |
| Change management | GitHub Pull Request history |
| Incident response | `docs/INCIDENT_RESPONSE.md` |

### CC3: Risk Assessment

**CC3.1 - Risk Identification**

| Control | Evidence Location |
|---------|-------------------|
| Automated vulnerability scanning | `.github/workflows/security.yml` |
| Dependency auditing | Safety, pip-audit, npm audit logs |
| SBOM generation | `.github/workflows/sbom.yml` |

### CC4: Monitoring Activities

**CC4.1 - Ongoing Monitoring**

| Control | Evidence Location |
|---------|-------------------|
| CI/CD security scans | GitHub Actions logs |
| Production monitoring | `.github/workflows/production-monitor.yml` |
| Audit logging | `aragora/audit/unified.py` |

### CC5: Control Activities

**CC5.1 - Control Selection and Development**

| Control | Evidence Location |
|---------|-------------------|
| Authentication | `aragora/auth/` |
| Authorization (RBAC) | `aragora/rbac/` |
| Encryption | `aragora/security/encryption.py` |

**CC5.2 - Logical Access Controls**

| Control | Implementation | Evidence |
|---------|----------------|----------|
| Role-based access | RBAC v2 with 360+ permissions | `aragora/rbac/defaults.py` |
| MFA support | TOTP/HOTP with backup codes | `aragora/auth/mfa.py` |
| Session management | JWT with configurable timeout | `aragora/auth/session.py` |
| API key management | Scoped API keys with rotation | `aragora/auth/api_keys.py` |

**CC5.3 - Physical Security**

| Control | Evidence |
|---------|----------|
| Cloud infrastructure | AWS/GCP SOC 2 reports |
| No on-premises systems | N/A |

### CC6: Logical and Physical Access

**CC6.1 - User Identity Management**

```python
# Example: User authentication flow
from aragora.auth import authenticate_user, verify_mfa

user = await authenticate_user(email, password)
if user.mfa_enabled:
    await verify_mfa(user, totp_code)
token = create_session_token(user)
```

**CC6.6 - Restriction of Logical Access**

| Control | Implementation |
|---------|----------------|
| Permission checks | `@require_permission` decorator |
| Tenant isolation | `TenantContext` middleware |
| Rate limiting | Per-endpoint rate limits |

### CC7: System Operations

**CC7.1 - Vulnerability Management**

| Tool | Frequency | Evidence |
|------|-----------|----------|
| CodeQL | On PR and weekly | GitHub Security tab |
| Bandit | On PR | CI/CD logs |
| Gitleaks | On PR | CI/CD logs |
| Dependency audit | On PR and weekly | Security workflow logs |

**CC7.2 - Incident Detection**

| Mechanism | Implementation |
|-----------|----------------|
| Error monitoring | Prometheus metrics + alerts |
| Anomaly detection | Rate limit violations logged |
| Audit trail | All API actions logged |

### CC8: Change Management

**CC8.1 - Change Authorization**

| Control | Evidence |
|---------|----------|
| Code review required | Branch protection rules |
| CI checks must pass | Required status checks |
| Security scan required | Security workflow in CI |

### CC9: Risk Mitigation

**CC9.1 - Identified Risks**

| Risk | Mitigation |
|------|------------|
| Unauthorized access | RBAC + MFA + audit logging |
| Data breach | Encryption at rest and in transit |
| Service disruption | Multi-region deployment support |
| Supply chain attack | SBOM + dependency scanning |

## Availability (A1)

### A1.1 - System Availability Commitment

| SLA Target | Mechanism |
|------------|-----------|
| 99.9% uptime | Health checks + auto-recovery |
| Multi-region support | `deploy-multi-region.yml` |
| Backup/restore | `aragora/backup/manager.py` |

### A1.2 - Disaster Recovery

| Component | RTO | RPO | Evidence |
|-----------|-----|-----|----------|
| Database | 1 hour | 15 minutes | Backup manager |
| Application | 15 minutes | N/A | Container orchestration |
| Configuration | Immediate | N/A | Git + secrets manager |

## Confidentiality (C1)

### C1.1 - Confidential Information

| Data Type | Protection |
|-----------|------------|
| User credentials | Hashed (Argon2) |
| API keys | Encrypted at rest |
| Debate content | Tenant-isolated |
| Audit logs | Immutable storage |

### C1.2 - Confidential Information Disposal

| Process | Implementation |
|---------|----------------|
| Data retention | Configurable per-tenant |
| Secure deletion | Cryptographic erasure |
| Backup expiration | Retention policies |

## Processing Integrity (PI1)

### PI1.1 - Processing Completeness and Accuracy

| Control | Implementation |
|---------|----------------|
| Input validation | Pydantic models |
| Transaction integrity | Database transactions |
| Checksum verification | Migration checksums |

## Evidence Collection

### Automated Evidence

The following evidence is automatically collected:

1. **CI/CD Logs**: GitHub Actions workflow runs
2. **Security Scans**: CodeQL, Bandit, dependency audits
3. **Audit Logs**: API access and admin actions
4. **Metrics**: Prometheus metrics and Grafana dashboards

### Manual Evidence Collection

For audits, collect the following:

```bash
# Export audit logs
python -m aragora.audit.export --start-date 2024-01-01 --end-date 2024-12-31

# Generate access review report
python -m aragora.rbac.reports --type access-review

# Export security scan history
gh run list --workflow=security.yml --limit=100 --json conclusion,createdAt
```

### Evidence Retention

| Evidence Type | Retention Period |
|---------------|------------------|
| Audit logs | 7 years |
| Security scans | 1 year |
| Access reviews | 7 years |
| Incident reports | 7 years |

## Audit Support

For SOC 2 audits, the following documentation is available:

1. **System Description**: Architecture diagrams in `docs/architecture/`
2. **Control Matrices**: This document
3. **Policy Documents**: `docs/SECURITY_TESTING.md`
4. **Technical Evidence**: GitHub, monitoring dashboards, audit logs

Contact: compliance@aragora.ai
