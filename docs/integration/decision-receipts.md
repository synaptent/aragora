# Decision Receipts Guide

Decision Receipts provide cryptographic audit trails for Gauntlet decisions, enabling compliance with regulatory requirements and supporting defensible decision-making.

## Overview

Every Gauntlet run automatically generates a Decision Receipt that includes:
- Unique receipt ID and Gauntlet ID linkage
- Verdict and confidence scores
- Risk assessment summary
- Cryptographic integrity checksum
- Optional digital signature

## Security Guarantees and Limits

Decision Receipts are a strong integrity and audit primitive, but they are not a complete safety proof.

Guaranteed when signed and verified:
- The receipt content was not altered after signing.
- The signature matches the configured signing key.
- The captured decision metadata (verdict, confidence, risk summary) is auditable.

Not guaranteed by receipt signing alone:
- The decision is factually correct.
- The decision is policy-appropriate or safe to execute.
- The model ensemble was free from correlated blind spots or collusion.
- The arbitration/execution layer itself was uncompromised.

Use signed receipts as a necessary precondition for automation, not a sufficient one.

## Execution Gate Recommendation

For high-impact or autonomous actions, require all checks before execution:

1. Receipt integrity verification passes (`/verify`).
2. Signature verification passes (`/verify-signature`).
3. Consensus quality checks pass (strong confidence, no unresolved high-severity dissent).
4. Ensemble diversity policy passes (provider/operator diversity, anti-collusion guardrails).
5. Domain policy checks pass (security/compliance/business rules).

## Features

### Automatic Persistence

Receipts are automatically persisted after Gauntlet completion:

```python
# Enabled by default - receipts auto-saved to receipt store
await gauntlet.run(statement="Review this API design")
# Receipt automatically created and stored
```

### Auto-Signing

Enable automatic cryptographic signing:

```bash
# In environment
export ARAGORA_AUTO_SIGN_RECEIPTS=true
export ARAGORA_RECEIPT_SIGNING_KEY=your-hmac-key
```

### 7-Year Retention

Receipts support compliance with regulations requiring 7-year retention:

```bash
# Default: 2555 days (7 years)
export ARAGORA_RECEIPT_RETENTION_DAYS=2555

# Cleanup runs automatically
export ARAGORA_RECEIPT_CLEANUP_INTERVAL=86400  # Daily
```

## API Endpoints

### List Receipts

```bash
GET /api/v2/receipts
```

Query parameters:
- `limit`: Max results (default 20, max 100)
- `offset`: Pagination offset
- `verdict`: Filter by verdict (APPROVED, REJECTED, etc.)
- `risk_level`: Filter by risk (LOW, MEDIUM, HIGH, CRITICAL)
- `date_from`: ISO date or unix timestamp
- `date_to`: ISO date or unix timestamp
- `signed_only`: Only signed receipts (true/false)
- `sort_by`: Sort field (created_at, confidence, risk_score)
- `order`: Sort order (asc, desc)

### Get Receipt

```bash
GET /api/v2/receipts/{receipt_id}
```

### Export Receipt

```bash
GET /api/v2/receipts/{receipt_id}/export?format=pdf
```

Supported formats: `json`, `html`, `md`, `pdf`, `sarif`, `csv`

### Verify Integrity

```bash
POST /api/v2/receipts/{receipt_id}/verify
```

Response:
```json
{
  "receipt_id": "receipt-abc123",
  "integrity_valid": true,
  "stored_checksum": "sha256:...",
  "computed_checksum": "sha256:..."
}
```

### Verify Signature

```bash
POST /api/v2/receipts/{receipt_id}/verify-signature
```

Response:
```json
{
  "receipt_id": "receipt-abc123",
  "signature_valid": true,
  "algorithm": "HMAC-SHA256",
  "key_id": "signing-key-1",
  "signed_at": "2026-01-24T10:30:00Z"
}
```

### Batch Verification

```bash
POST /api/v2/receipts/verify-batch
Content-Type: application/json

{
  "receipt_ids": ["receipt-abc", "receipt-xyz"]
}
```

### Statistics

```bash
GET /api/v2/receipts/stats
```

## Receipt Structure

```json
{
  "receipt_id": "receipt-abc123def456",
  "gauntlet_id": "gauntlet-xyz789",
  "timestamp": "2026-01-24T10:30:00Z",
  "input_summary": "API design review for payment service",
  "input_hash": "sha256:a1b2c3...",
  "verdict": "APPROVED",
  "confidence": 0.87,
  "robustness_score": 0.82,
  "risk_summary": {
    "critical": 0,
    "high": 1,
    "medium": 3,
    "low": 5,
    "total": 9
  },
  "attacks_attempted": 15,
  "attacks_successful": 2,
  "probes_run": 25,
  "vulnerabilities_found": 9
}
```

## Signature Algorithms

Supported signing algorithms:

| Algorithm | Use Case |
|-----------|----------|
| HMAC-SHA256 | Default, fast, symmetric key |
| RSA-SHA256 | PKI integration, asymmetric |
| Ed25519 | Modern, fast, asymmetric |

### Configuration

```bash
# HMAC (default)
export ARAGORA_RECEIPT_SIGNING_KEY=your-secret-key
export ARAGORA_RECEIPT_SIGNING_ALGORITHM=HMAC-SHA256

# RSA
export ARAGORA_RECEIPT_SIGNING_KEY_PATH=/path/to/private.pem
export ARAGORA_RECEIPT_SIGNING_ALGORITHM=RSA-SHA256

# Ed25519
export ARAGORA_RECEIPT_SIGNING_KEY_PATH=/path/to/ed25519.key
export ARAGORA_RECEIPT_SIGNING_ALGORITHM=Ed25519
```

## Database Schema

```sql
CREATE TABLE receipts (
    receipt_id TEXT PRIMARY KEY,
    gauntlet_id TEXT NOT NULL UNIQUE,
    debate_id TEXT,
    created_at REAL NOT NULL,
    expires_at REAL,
    verdict TEXT NOT NULL,
    confidence REAL NOT NULL,
    risk_level TEXT NOT NULL,
    risk_score REAL NOT NULL DEFAULT 0.0,
    checksum TEXT NOT NULL,
    signature TEXT,
    signature_algorithm TEXT,
    signature_key_id TEXT,
    signed_at REAL,
    audit_trail_id TEXT,
    data_json TEXT NOT NULL
);

-- Indexes for efficient queries
CREATE INDEX idx_receipts_verdict ON receipts(verdict);
CREATE INDEX idx_receipts_risk ON receipts(risk_level);
CREATE INDEX idx_receipts_created ON receipts(created_at DESC);
CREATE INDEX idx_receipts_gauntlet ON receipts(gauntlet_id);
CREATE INDEX idx_receipts_expires ON receipts(expires_at);
```

## Integration with Knowledge Mound

Receipts integrate with the Knowledge Mound for organizational learning:

```python
from aragora.knowledge.mound.adapters.receipt_adapter import ReceiptAdapter

adapter = ReceiptAdapter()
# Receipts automatically indexed for search
# Patterns extracted for decision analysis
```

## Compliance Features

### SOC 2

- Immutable audit trail with checksums
- Signature verification for non-repudiation
- 7-year retention support

### GDPR

- Receipt export in multiple formats
- Audit trail for data processing decisions
- Retention policy enforcement

### Financial Regulations

- Cryptographic integrity verification
- Timestamped decision records
- Export to SARIF for security tools

## See Also

- [Gauntlet Architecture](../architecture/GAUNTLET_ARCHITECTURE.md)
- [Compliance Guide](../enterprise/COMPLIANCE.md)
- [Knowledge Mound Guide](./knowledge-system-guide.md)
