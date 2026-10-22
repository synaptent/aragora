# AWS Retirement Migration Learnings

## Repo conventions

- Extend `aragora.config.secrets.SecretManager`; do not introduce a second application secrets
  subsystem.
- Supabase persistence already belongs behind the standard PostgreSQL `DATABASE_URL` contract.
  Provider-specific persistence code is unnecessary.
- The self-hosted container path and existing health, WebSocket, and receipt-verification helpers
  are the implementation foundation for the canary.

## Validation and tooling

- `tests/config/test_secrets.py` imports `boto3`, and Ed25519/RSA receipt tests require
  `cryptography`; CI side-loads these even though the locked `dev` and `test` extras do not.
- Repository-wide Ruff is ambient-red on a trusted launcher under `.github/workflows`; use targeted
  touched-file Ruff and record the broad baseline rather than modifying the protected file.
- Docker Compose configuration validation does not require a running daemon, but live container
  validation does.

## Product and domain invariants

- Strict production secret mode must accept only an approved custody source and must reject raw
  environment fallback for critical secrets.
- Explicit signing-key configuration fails closed; it never falls through to another backend or
  silently produces an unsigned receipt.
- External readiness means health, WebSocket, persistence, and independent signed-receipt proof,
  not merely HTTP 200.

## Known traps

- Two stale July 17 contingency worktrees contain uncommitted signing work. They are not live or
  owned, but they are user data and must remain untouched.
- Local Hetzner and Cloudflare authentication are unavailable at staging. Do not mistake
  implementation readiness for live deployment readiness.

## Retired learnings

- The old #9391 next action was AWS login plus EC2/SSM diagnosis. Retired by the operator's
  2026-08-19 decision to treat AWS as retired infrastructure.
