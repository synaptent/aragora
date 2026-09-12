#!/usr/bin/env bash
# Bring up the production origin. Safe to re-run.
set -euo pipefail
cd "$(dirname "$0")"

fail() { echo "ERROR: $*" >&2; exit 1; }

[[ -f secrets.env ]] || fail "secrets.env missing. Copy secrets.env.template, fill it in, chmod 600."
[[ "$(stat -c '%a' secrets.env 2>/dev/null || stat -f '%Lp' secrets.env)" == "600" ]] \
  || fail "secrets.env must be chmod 600 (currently world- or group-readable)."

# Refuse to start with an unset critical value rather than booting a server that
# silently has no auth token — the failure mode this whole migration exists to remove.
for k in ARAGORA_ENCRYPTION_KEY ARAGORA_JWT_SECRET POSTGRES_PASSWORD ARAGORA_API_TOKEN DATABASE_URL; do
  v="$(grep -E "^${k}=" secrets.env | cut -d= -f2- || true)"
  [[ -n "${v// /}" ]] || fail "$k is empty in secrets.env"
done

command -v docker >/dev/null || fail "docker not installed on this host"
docker compose version >/dev/null 2>&1 || fail "docker compose v2 plugin not installed"

mkdir -p backups
echo "==> building and starting (migrations run first, as a gate)"
docker compose up -d --build

echo "==> waiting for the app to report healthy"
for i in $(seq 1 40); do
  s="$(docker compose ps --format json app 2>/dev/null | grep -o '"Health":"[a-z]*"' | cut -d'"' -f4 || true)"
  [[ "$s" == "healthy" ]] && { echo "    healthy"; break; }
  [[ $i -eq 40 ]] && { docker compose logs --tail=40 app; fail "app did not become healthy"; }
  sleep 5
done

echo "==> local origin check"
curl -fsS --max-time 10 http://127.0.0.1:8080/readyz && echo
echo "Origin is up. Next: start cloudflared so api.aragora.ai reaches it."
