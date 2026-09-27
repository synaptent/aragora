# Provider-Neutral Canary Pack

This pack runs one Aragora API canary from an immutable container digest with
external PostgreSQL and Redis supplied through mounted secret custody. It does
not select, create, or mutate a hosting provider, DNS record, tunnel, database,
or secret. Those are separately authorized external actions under #9391.

## Inputs

Copy `canary.env.example` to a private operator path and set only non-secret
values. `ARAGORA_IMAGE` must include an exact `@sha256:` digest. Bindings default
to loopback (`127.0.0.1:18080` and `127.0.0.1:18765`); an authorized reverse
proxy or tunnel may expose a canary hostname later.

Create `ARAGORA_SECRETS_DIR_HOST` as a directory owned by the dedicated runtime
UID/GID (defaults `1000:1000`) with mode `0700`. Each file must have the same
UID/GID, be regular and single-link, and use mode no broader than `0600`.
Required fixed filenames:

- `DATABASE_URL`
- `REDIS_URL`
- `ARAGORA_API_TOKEN`
- `ARAGORA_JWT_SECRET`
- `ARAGORA_ENCRYPTION_KEY`
- `odr-signing-key.pem`
- at least one supported provider key such as `ANTHROPIC_API_KEY` or
  `OPENROUTER_API_KEY`

Never place values in Compose, an env file, command arguments, logs, or this
repository. `ARAGORA_RUNTIME_UID` and `ARAGORA_RUNTIME_GID` must match the
service identity that owns the directory and files; the validator defaults both
to `1000` and rejects root-owned custody that the non-root container cannot read.

## Offline preflight

```bash
set -a
. /private/operator/canary.env
set +a
python3 scripts/validate_provider_neutral_canary.py \
  --image "$ARAGORA_IMAGE" \
  --secrets-dir "$ARAGORA_SECRETS_DIR_HOST" \
  --runtime-uid "$ARAGORA_RUNTIME_UID" \
  --runtime-gid "$ARAGORA_RUNTIME_GID"
docker compose \
  --env-file /private/operator/canary.env \
  -f deploy/provider-neutral/docker-compose.canary.yml \
  config --quiet
```

The validator reads metadata only; it never reads or prints secret values.

## Migration and startup

A verified database backup and successful restore rehearsal are hard gates
before migration. The migration profile hydrates `DATABASE_URL` only inside its
one-shot container and uses PostgreSQL advisory locking:

```bash
docker compose --env-file /private/operator/canary.env \
  -f deploy/provider-neutral/docker-compose.canary.yml \
  --profile migrate run --rm migrate

docker compose --env-file /private/operator/canary.env \
  -f deploy/provider-neutral/docker-compose.canary.yml up -d api
```

No public cutover follows automatically. First verify loopback health,
WebSocket upgrade, persistence, both signing-key endpoints, a signed receipt,
offline signature verification, and the exact running image digest. Repeat the
same proof after one canary restart.

## Rollback

Record the previous immutable image digest, database snapshot/export identity,
secret-directory metadata digest (never file contents), and edge origin before
any authorized change. Application rollback selects the previous digest and
restarts the canary. Database rollback uses the preserved snapshot only when the
migration is declared rollback-safe. Edge rollback is a separate authorized
operation. Rerun the complete verifier after every rollback.

This PR intentionally contains no GitHub Actions workflow. Any workflow that
materializes production secrets or changes deployment behavior is a separate
Tier-4 follow-up requiring exact-head operator preapproval and settlement.
