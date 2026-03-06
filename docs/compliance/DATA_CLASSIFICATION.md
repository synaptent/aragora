# Data Classification — Compliance Reference

**Issue:** Enterprise Assurance #511
**Effective Date:** 2026-03-05
**Owner:** Security / Compliance Team
**Controls:** SOC 2 CC6-01, GDPR Art. 32, EU AI Act Art. 13

---

## Overview

Aragora classifies all data it processes into one of four standard levels.
Each level carries mandatory handling rules enforced at the platform layer by
`aragora/compliance/data_classification.py` and validated at every API boundary
by `aragora/compliance/data_classification.py::PolicyEnforcer`.

Hardcoded secrets and PII patterns are blocked at CI time by
`.github/workflows/security-gate.yml` ("Hardcoded secrets pattern scan" step,
which calls `scripts/pre_release_check.py --gate secrets-only`).

---

## Classification Matrix

| Level | Label | Sensitivity | Encryption | Audit Log | Retention | Consent |
|-------|-------|------------|------------|-----------|-----------|---------|
| 1 | PUBLIC | None | No | No | 365 days | No |
| 2 | INTERNAL | Low | No | Yes | 365 days | No |
| 3 | CONFIDENTIAL | Medium | Yes (AES-256-GCM) | Yes | 180 days | No |
| 4 | RESTRICTED | High | Yes (AES-256-GCM) | Yes | 90 days | Yes |

A fifth level, **PII**, maps onto the same controls as RESTRICTED and is used
when the platform detects personally-identifiable information via regex scanning
(email, phone, SSN, credit-card patterns). PII data is always treated with the
strictest handling requirements.

### Allowed Operations per Level

| Operation | PUBLIC | INTERNAL | CONFIDENTIAL | RESTRICTED |
|-----------|--------|----------|--------------|------------|
| read      | Yes    | Yes      | Yes          | Yes        |
| write     | Yes    | Yes      | Yes          | Yes        |
| export    | Yes    | Yes      | No           | No         |
| share     | Yes    | No       | No           | No         |
| delete    | Yes    | Yes      | Yes          | Yes        |
| archive   | Yes    | Yes      | Yes          | No         |

### Region Restrictions

| Level | Allowed Regions |
|-------|----------------|
| PUBLIC | Unrestricted |
| INTERNAL | Unrestricted |
| CONFIDENTIAL | `us`, `eu`, `uk` |
| RESTRICTED | `us`, `eu` |

---

## Implementation

### Classification Engine

`aragora/compliance/data_classification.py` provides:

- `DataClassification` — enum of all levels (`PUBLIC`, `INTERNAL`,
  `CONFIDENTIAL`, `RESTRICTED`, `PII`).
- `DataClassifier.classify(data, context)` — rule-based classification
  that inspects field names, values, and context keywords, then scans
  string values for PII patterns.
- `DataClassifier.validate_handling(data, classification, operation, ...)` —
  checks an operation against the policy for the given level.
- `DataClassifier.scan_for_pii(text)` — regex scanner returning
  `PIIDetection` objects with type, position, and confidence.
- `PolicyEnforcer.enforce_access(data, source, target, ...)` — prevents
  higher-classified data from flowing into a lower-classified context.
- `PolicyEnforcer.audit_label(data)` — generates a classification label
  for audit log entries.
- `PolicyEnforcer.classify_debate_result(result)` — enriches debate
  results with `_classification` metadata.

### Sensitive Pattern Keywords (auto-classify to RESTRICTED or PII)

Restricted keywords: `secret`, `api_key`, `password`, `token`,
`credential`, `private key`, `encryption_key`.

PII keywords: `email`, `phone`, `ssn`, `social_security`, `date_of_birth`,
`dob`, `passport`, `driver_license`, `credit_card`, `address`, `national_id`.

Confidential keywords: `salary`, `revenue`, `financial`, `proprietary`,
`trade_secret`, `internal_only`, `contract`, `medical`, `health`, `diagnosis`.

---

## CI Enforcement

### Hardcoded Secrets Scan (Blocking)

`.github/workflows/security-gate.yml` runs on every PR to `main`:

```
- name: "BLOCKING: Hardcoded secrets pattern scan"
  run: python scripts/pre_release_check.py --gate secrets-only
```

`scripts/pre_release_check.py` scans all non-test Python source files for:

| Pattern | Description |
|---------|-------------|
| `AKIA[0-9A-Z]{16}` | AWS access key ID |
| `aws_secret_access_key = "..."` | AWS secret key |
| PEM key header (`BEGIN ... KEY`) | Embedded private key |
| `api_key = "..."` (20+ chars) | Generic API key assignment |
| `token = "..."` (20+ chars) | Generic token assignment |
| `password = "..."` (8+ chars) | Hardcoded password |

The scan **fails the CI gate** (non-zero exit code) if any pattern is found
outside test files, fixtures, or documentation strings. Results are uploaded
as a Bandit report artifact for 30 days.

### Static Security Analysis

`bandit -r aragora/ -lll` (HIGH severity, configured in `pyproject.toml`)
runs in the same workflow and blocks PRs on any high-severity finding.

---

## Data Handling Rules

### RESTRICTED and PII

- All secrets (API keys, credentials, tokens) MUST be sourced from environment
  variables or the AWS Secrets Manager (`aragora/config/secrets.py`). Never
  committed to source control.
- Encryption: AES-256-GCM at rest, TLS 1.3 in transit.
- MFA required for admin access to restricted data stores.
- Quarterly access reviews via `aragora/rbac/` audit log.
- Retention: 90 days maximum unless a longer period is legally required.
- Disposal: cryptographic erasure; log erasure event in audit trail.

### CONFIDENTIAL

- Encryption at rest required.
- Accessible only on a need-to-know basis with RBAC enforcement.
- Region restriction: `us`, `eu`, `uk`.
- Retention: 180 days maximum.

### INTERNAL

- Accessible to authenticated users only.
- Audit logging recommended.
- No region restriction.

### PUBLIC

- No special handling requirements.
- Data at this level may be freely shared or published.

---

## Debate Content Classification

Debate results and arguments are automatically classified by
`PolicyEnforcer.classify_debate_result()` when the debate contains sensitive
keywords or PII. The `_classification` key is added to every result dict so
downstream handlers can enforce appropriate controls.

---

## Compliance Controls Mapping

| Framework | Control | Requirement | Implementation |
|-----------|---------|-------------|----------------|
| SOC 2 | CC6-01 | Data classification | `DataClassifier`, `PolicyEnforcer` |
| SOC 2 | CC6-06 | Restrict sensitive outputs | `PolicyEnforcer.enforce_access()` |
| GDPR | Art. 25 | Privacy by design | PII auto-detection, encryption defaults |
| GDPR | Art. 32 | Technical measures | AES-256-GCM, TLS 1.3, access logging |
| EU AI Act | Art. 13 | Transparency | Classification metadata on AI outputs |
| ISO 27001 | A.8.2 | Information classification | Four-level scheme |

---

## Related Files

| File | Purpose |
|------|---------|
| `aragora/compliance/data_classification.py` | Classification engine and policy enforcer |
| `aragora/privacy/classifier.py` | Privacy-layer PII classifier |
| `aragora/privacy/anonymization.py` | PII anonymization for GDPR |
| `aragora/security/encryption.py` | AES-256-GCM encryption primitives |
| `aragora/rbac/types.py` | `data_classification.read/classify/update` permissions |
| `scripts/pre_release_check.py` | CI secrets/PII pattern scanner |
| `.github/workflows/security-gate.yml` | CI workflow running the scan |
| `docs/enterprise/DATA_CLASSIFICATION.md` | Enterprise policy reference (full lifecycle) |
| `tests/compliance/test_data_classification.py` | Classification engine test suite |

---

## Document History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-03-05 | Initial compliance reference (issue #511) |
