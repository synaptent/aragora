# MFA Bypass Process

This document defines the exception and bypass process for the admin MFA
enforcement requirement (SOC 2 Control CC5-01, GitHub issue #510).

## When Bypass Is Allowed

MFA bypass is permitted **only** for:

- **Service accounts** — Automated integrations that authenticate via API key
  and have no interactive login session.
- **API-only integrations** — Machine-to-machine tokens used by CI/CD pipelines,
  monitoring agents, or third-party connectors.

MFA bypass is **never** permitted for:

- Human users with interactive login access.
- Shared accounts or generic admin accounts.
- Temporary convenience (e.g., "I lost my authenticator app").

## Requesting a Bypass

An authorized administrator (role: `owner` or `superadmin`) must approve
the bypass programmatically:

```python
user.approve_mfa_bypass(
    reason="CI/CD service account - no interactive login",
    approved_by="admin-user-id",
    expires_days=30,
)
```

Parameters:

| Parameter      | Type  | Description                                    |
|----------------|-------|------------------------------------------------|
| `reason`       | str   | Justification for the bypass (audit-logged)    |
| `approved_by`  | str   | User ID of the approving administrator         |
| `expires_days` | int   | Days until the bypass expires (max 90, no permanent bypasses) |

## Duration Limits

- **Default**: 30 days
- **Maximum**: 90 days
- **Permanent bypasses**: Not allowed. All bypasses must have an expiration date.
- **Renewal**: A new approval is required before the current bypass expires.
  There is no auto-renewal.

## Audit Trail

All bypass approvals and revocations are logged to the security audit trail:

- `mfa_bypass_approved` — Records who approved, the reason, and expiration.
- `mfa_bypass_revoked` — Records who revoked the bypass and the reason.
- `mfa_bypass_expired` — Automatically logged when a bypass reaches its
  expiration date.

Audit entries include:

| Field           | Description                          |
|-----------------|--------------------------------------|
| `user_id`       | The service account / user affected  |
| `actor_id`      | The administrator who took action    |
| `reason`        | Justification text                   |
| `expires_at`    | When the bypass expires              |
| `action`        | `approved`, `revoked`, or `expired`  |
| `timestamp`     | ISO-8601 timestamp of the action     |

## Revoking a Bypass

Any administrator with `owner` or `superadmin` role can revoke a bypass
at any time:

```python
user.revoke_mfa_bypass(
    revoked_by="admin-user-id",
    reason="Integration decommissioned",
)
```

Revocation takes effect immediately. The affected account will be subject
to standard MFA enforcement on its next authentication attempt.

## Compliance Monitoring

The `MFADriftMonitor` scans all admin accounts periodically (default: hourly)
and reports:

- Accounts with expired bypasses that have not re-enabled MFA.
- Service accounts whose bypass is approaching expiration (7-day warning).
- Overall compliance rate against the configured threshold (default: 100%).

Non-compliant accounts trigger critical-severity notifications via Slack and
email to the security team.
