# SOC 2 Compliance Controls

This document describes Aragora's implementation of SOC 2 Type II controls across the Trust Services Criteria.

## Overview

Aragora implements controls for:
- **Security**: Protection of system resources against unauthorized access
- **Availability**: System availability for operation and use
- **Processing Integrity**: System processing is complete, valid, accurate, timely, and authorized
- **Confidentiality**: Protection of confidential information
- **Privacy**: Personal information handling

## Security Controls

### CC1: Control Environment

| Control | Implementation | Evidence |
|---------|----------------|----------|
| CC1.1 - Security policies | `aragora/auth/`, `aragora/rbac/` | Role-based access control with 360+ permissions |
| CC1.2 - Board oversight | `docs/ARCHITECTURE.md` | Documented security architecture |
| CC1.3 - Authority and responsibility | `aragora/rbac/defaults.py` | 6 default roles with defined scopes |

### CC2: Communication and Information

| Control | Implementation | Evidence |
|---------|----------------|----------|
| CC2.1 - Security awareness | `docs/AUTH_GUIDE.md` | Authentication documentation |
| CC2.2 - Internal communication | `aragora/rbac/audit.py` | Audit logging for all authorization decisions |
| CC2.3 - External communication | `docs/API_REFERENCE.md` | Public API documentation |

### CC3: Risk Assessment

| Control | Implementation | Evidence |
|---------|----------------|----------|
| CC3.1 - Risk identification | `aragora/gauntlet/` | Adversarial testing framework |
| CC3.2 - Risk analysis | `aragora/observability/metrics/` | Prometheus metrics for monitoring |
| CC3.3 - Fraud risk | `aragora/agents/airlock.py` | Agent isolation and sandboxing |

### CC4: Monitoring Activities

| Control | Implementation | Evidence |
|---------|----------------|----------|
| CC4.1 - Ongoing monitoring | `deploy/monitoring/` | Prometheus + Grafana dashboards |
| CC4.2 - Deficiency evaluation | `deploy/alerting/` | Alert rules for critical conditions |

### CC5: Control Activities

| Control | Implementation | Evidence |
|---------|----------------|----------|
| CC5.1 - Control selection | `aragora/resilience.py` | Circuit breakers for external services |
| CC5.2 - Technology controls | `aragora/server/rate_limit.py` | Rate limiting at API level |
| CC5.3 - Policies deployment | `aragora/control_plane/policy.py` | Policy governance system |

### CC6: Logical and Physical Access

| Control | Implementation | Evidence |
|---------|----------------|----------|
| CC6.1 - Security software | `aragora/auth/oidc.py` | OIDC/SAML SSO integration |
| CC6.2 - Registration/authorization | `aragora/auth/mfa.py` | TOTP/HOTP multi-factor authentication |
| CC6.3 - Access removal | `aragora/billing/auth/blacklist.py` | Token revocation and blacklisting |
| CC6.4 - Access restriction | `aragora/tenancy/isolation.py` | Multi-tenant data isolation |
| CC6.5 - Logical access security | `aragora/rbac/middleware.py` | HTTP route protection |
| CC6.6 - Transmission encryption | TLS 1.3 required | Let's Encrypt via Traefik |
| CC6.7 - Data encryption | `aragora/auth/crypto.py` | AES-256-GCM at rest encryption |
| CC6.8 - Malicious software | `.github/workflows/security.yml` | Bandit, gitleaks scanning |

### CC7: System Operations

| Control | Implementation | Evidence |
|---------|----------------|----------|
| CC7.1 - Infrastructure protection | `deploy/kubernetes/` | Kubernetes network policies |
| CC7.2 - Change detection | Git version control | All changes tracked |
| CC7.3 - Change management | `.github/workflows/test.yml` | CI/CD pipeline with tests |
| CC7.4 - Incident response | `docs/ALERT_RUNBOOKS.md` | Documented incident procedures |
| CC7.5 - Recovery operations | `aragora/backup/manager.py` | Automated backup system |

### CC8: Change Management

| Control | Implementation | Evidence |
|---------|----------------|----------|
| CC8.1 - Change authorization | GitHub PRs required | Branch protection rules |
| CC8.2 - Configuration management | `deploy/kubernetes/configmap.yaml` | Versioned configurations |
| CC8.3 - Emergency changes | Documented in ADR | Architecture Decision Records |

### CC9: Risk Mitigation

| Control | Implementation | Evidence |
|---------|----------------|----------|
| CC9.1 - Vendor management | `aragora/agents/fallback.py` | Multi-provider fallback |
| CC9.2 - Business continuity | `aragora/backup/` | Disaster recovery procedures |

## Availability Controls

### A1: Availability

| Control | Implementation | Evidence |
|---------|----------------|----------|
| A1.1 - Capacity management | `deploy/kubernetes/hpa.yaml` | Horizontal pod autoscaling |
| A1.2 - Environmental protection | Cloud infrastructure | AWS/GCP/Azure deployment |
| A1.3 - Recovery operations | `aragora/backup/manager.py` | Incremental backups |

## Processing Integrity Controls

### PI1: Processing Integrity

| Control | Implementation | Evidence |
|---------|----------------|----------|
| PI1.1 - Input validation | `aragora/server/handlers/` | Request validation |
| PI1.2 - Processing monitoring | `aragora/gauntlet/receipts.py` | Cryptographic audit trails |
| PI1.3 - Output integrity | SHA-256 hashing | Receipt chain verification |

## Confidentiality Controls

### C1: Confidentiality

| Control | Implementation | Evidence |
|---------|----------------|----------|
| C1.1 - Confidential info identification | Data classification | Sensitive fields marked |
| C1.2 - Disposal procedures | Database migrations | Secure deletion procedures |

## Privacy Controls

### P1-P8: Privacy

| Control | Implementation | Evidence |
|---------|----------------|----------|
| P1 - Notice | Privacy policy | User-facing documentation |
| P2 - Choice/Consent | Opt-in features | Configurable data sharing |
| P3 - Collection | Minimal data | Only required fields |
| P4 - Use/Retention | Data lifecycle | Configurable retention |
| P5 - Access | User data export | API endpoints for data access |
| P6 - Disclosure | Audit logging | Third-party sharing logs |
| P7 - Quality | Data validation | Input sanitization |
| P8 - Monitoring | Metrics collection | Privacy-respecting analytics |

## Evidence Collection

### Automated Evidence

```bash
# Generate compliance report
python scripts/compliance_report.py --output reports/soc2_evidence.json

# Run security scan
bandit -r aragora/ -f json -o reports/bandit_report.json

# Check for secrets
gitleaks detect --report-format json --report-path reports/secrets_scan.json
```

### Manual Evidence

1. **Access Reviews**: Quarterly review of user access levels
2. **Penetration Testing**: Annual third-party security assessment
3. **Vendor Assessments**: Annual review of AI provider security practices
4. **Training Records**: Security awareness training completion

## Control Gaps and Remediation

| Gap | Priority | Remediation | Target Date |
|-----|----------|-------------|-------------|
| Distributed rate limiting | High | Implement Redis-backed limits | Q1 2026 |
| Data retention automation | Medium | Add scheduled cleanup jobs | Q2 2026 |
| Formal DR testing | Medium | Quarterly restore verification | Q1 2026 |

## Audit Preparation Checklist

- [ ] Collect system access logs (90 days)
- [ ] Compile change management records
- [ ] Document incident response history
- [ ] Prepare vendor security assessments
- [ ] Export user access review records
- [ ] Generate infrastructure diagrams
- [ ] Compile penetration test results
- [ ] Prepare training completion records

## Contact

For SOC 2 audit inquiries, contact: security@aragora.ai
