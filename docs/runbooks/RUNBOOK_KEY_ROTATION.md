# Key Rotation Runbook

Standard procedures for rotating encryption keys in Aragora deployments.

## Overview

Aragora uses AES-256-GCM encryption for secrets at rest. Keys should be rotated:
- Every 90 days (recommended)
- After any suspected key compromise
- When personnel with key access leave the organization
- Before compliance audits (SOC2, HIPAA, etc.)

## Prerequisites

| Requirement | Verification |
|-------------|--------------|
| Cryptography library installed | `python -c "from cryptography.fernet import Fernet; print('OK')"` |
| Encryption service healthy | `aragora security health` |
| Backup completed | See [Disaster Recovery](./DISASTER_RECOVERY.md) |
| Maintenance window scheduled | Low-traffic period (recommended) |

## Pre-Rotation Checklist

```bash
# 1. Check current encryption status
aragora security status

# 2. Run health check
aragora security health --detailed

# 3. Check key age
curl -s http://localhost:8080/api/health/encryption | jq .

# 4. Verify backup exists
ls -la backups/

# 5. Check disk space (re-encryption needs temp space)
df -h
```

**Expected output from `aragora security status`:**
```
📊 Encryption Status
==================================================
  Cryptography available: ✓
  Active key ID: default
  Key version: 3
  Key age: 45 days
  Created: 2025-12-01T00:00:00

  Total keys: 2
    * default v3
      default v2
```

## Rotation Procedures

### Option 1: CLI (Recommended)

#### Dry Run First

Always preview what will change:

```bash
# Preview rotation
aragora security rotate-key --dry-run

# Preview with specific stores
aragora security rotate-key --dry-run --stores integration,gmail
```

**Expected dry-run output:**
```
🔑 Key Rotation
==================================================
  Mode: DRY RUN (no changes will be made)
  Stores: integration, gmail, sync

✓ Key rotation completed successfully
  Old version: 3
  New version: 4
  Stores processed: 3
  Records re-encrypted: 127
  Duration: 0.00s
```

#### Execute Rotation

```bash
# Interactive rotation (recommended)
aragora security rotate-key

# Non-interactive rotation
aragora security rotate-key --force

# Rotate specific stores only
aragora security rotate-key --stores integration,gmail
```

**Expected prompts:**
```
🔑 Key Rotation
==================================================
  Mode: LIVE ROTATION
  Stores: integration, gmail, sync

  Proceed with key rotation? [y/N] y

✓ Key rotation completed successfully
  Old version: 3
  New version: 4
  Stores processed: 3
  Records re-encrypted: 127
  Duration: 2.34s
```

### Option 2: HTTP API

#### Dry Run

```bash
curl -X POST http://localhost:8080/api/admin/security/rotate-key \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"dry_run": true}'
```

#### Execute

```bash
curl -X POST http://localhost:8080/api/admin/security/rotate-key \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"stores": ["integration", "gmail", "sync"]}'
```

### Option 3: Python API

Register the audit provider first. The server and the `aragora security` CLI
commands do this for you; a standalone script must do it itself, or the
`key_rotation` audit event is dropped and only a warning is logged.

```python
from aragora.ops.security_edge_adapters import register_security_migration_adapters
from aragora.security.migration import rotate_encryption_key

register_security_migration_adapters()

# Dry run
result = rotate_encryption_key(dry_run=True)
print(f"Would re-encrypt {result.records_reencrypted} records")

# Execute
result = rotate_encryption_key(stores=["integration", "gmail", "sync"])
if result.success:
    print(f"Rotated: v{result.old_key_version} -> v{result.new_key_version}")
else:
    print(f"Failed: {result.errors}")
```

## Post-Rotation Verification

```bash
# 1. Verify new key version
aragora security status

# 2. Run health check
aragora security health

# 3. Test encrypt/decrypt round-trip
curl -s http://localhost:8080/api/health/encryption | jq .status

# 4. Verify stores are accessible
curl -s http://localhost:8080/api/integrations | jq 'length'

# 5. Check audit log for rotation event
grep "key_rotation" /var/log/aragora/audit.log | tail -5
```

**Success criteria:**
- [ ] New key version shows in `aragora security status`
- [ ] Health check passes: `aragora security health`
- [ ] Integrations load without errors
- [ ] Audit log shows rotation event

## Rollback Procedures

### If Rotation Fails Mid-Process

The old key remains valid during the overlap period (default: 7 days).

```bash
# Check which records failed
aragora security status

# The system can still decrypt with old key
# Re-run rotation for failed stores only
aragora security rotate-key --stores integration
```

### If New Key Has Issues

Old keys are retained for the overlap period:

```bash
# Check current keys
aragora security status

# Old key is still valid - data can be decrypted
# Contact support if issues persist
```

### Emergency: Restore from Backup

If both keys are compromised:

```bash
# 1. Stop service
sudo systemctl stop aragora

# 2. Restore from backup
# See DISASTER_RECOVERY.md for full procedure

# 3. Restart service
sudo systemctl start aragora
```

## Troubleshooting

### "Cryptography library not installed"

```bash
pip install cryptography
```

### "No active encryption key"

```bash
# Check ARAGORA_ENCRYPTION_KEY environment variable
echo "Key length: ${#ARAGORA_ENCRYPTION_KEY}"

# Should be 32+ characters for AES-256
# Generate new key if needed:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### "Failed to re-encrypt records"

Check specific store errors:

```bash
# Check logs
sudo journalctl -u aragora -n 100 | grep -i "encrypt"

# Try single store
aragora security rotate-key --stores integration --dry-run
```

### High Re-encryption Time

For large datasets:

```bash
# Rotate stores one at a time during low-traffic periods
aragora security rotate-key --stores integration
aragora security rotate-key --stores gmail
aragora security rotate-key --stores sync
```

### Key Age Warning Not Updating

Clear the encryption service cache:

```bash
# Restart service to clear in-memory cache
sudo systemctl restart aragora
```

## Scheduled Rotation

### Recommended Schedule

| Environment | Rotation Frequency | Overlap Period |
|-------------|-------------------|----------------|
| Development | 180 days | 1 day |
| Staging | 90 days | 3 days |
| Production | 90 days | 7 days |

### Automation (Cron)

```bash
# Add to crontab for automatic rotation reminders
# 0 9 1 */3 * /usr/local/bin/aragora security health --detailed >> /var/log/aragora/rotation-check.log
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_ENCRYPTION_KEY` | (required) | Base encryption key |
| `ARAGORA_KEY_ROTATION_OVERLAP_DAYS` | 7 | Days old key remains valid |

## Audit Trail

All key rotations are logged to:
- Application logs: `/var/log/aragora/aragora.log`
- Audit logs: `/var/log/aragora/audit.log`
- Database audit table (if enabled)

**Log format:**
```json
{
  "event_type": "key_rotation",
  "actor_id": "system",
  "old_version": 3,
  "new_version": 4,
  "timestamp": "2025-01-21T10:30:00Z"
}
```

## Related Documentation

- [Secrets Management](../enterprise/SECRETS_MANAGEMENT.md)
- [Disaster Recovery](./DISASTER_RECOVERY.md)
- [Security Patterns](../enterprise/SECURITY_PATTERNS.md)
- [Incident Response](RUNBOOK_INCIDENT.md)
