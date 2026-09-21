# Deployment Guide

Three deployment paths, from simplest to production-grade.

## 1. Local Development (no Docker)

```bash
pip install aragora

# Offline mode — SQLite, no external services, no API keys needed
aragora serve --demo

# With API keys — full functionality
export ANTHROPIC_API_KEY=your-key
aragora serve
```

**Minimum requirements:** Python 3.10+, 4GB RAM

**Offline mode** sets SQLite backend, enables demo mode, and skips all external service connections. Good for testing and development.

## Container Images

Pre-built images are published to GitHub Container Registry on every push to `main` and on version tags:

| Image | Pull Command |
|-------|-------------|
| Backend | `docker pull ghcr.io/synaptent/aragora/backend:latest` |
| Frontend | `docker pull ghcr.io/synaptent/aragora/frontend:latest` |
| Operator | `docker pull ghcr.io/synaptent/aragora/operator:latest` |

**Available tags:** `latest` (main branch HEAD), `2.10.0` (version from pyproject.toml), `v2.10.0` (git tag), `<major>.<minor>`, `<sha>`.

## 2. Docker Compose (recommended for production)

```bash
cd deploy
cp docker-compose.yml docker-compose.override.yml  # customize if needed
docker compose up -d
```

**Services started:** Backend (port 8080 + WS 8765), Redis, PostgreSQL (optional profile)

**Docker deployment path:**

- Zero-dependency local run: `docker compose -f docker-compose.simple.yml up` (SQLite, no Postgres or Redis).
- Production hardening (TLS, secrets, resource limits): [PRODUCTION_DEPLOYMENT.md](deployment/PRODUCTION_DEPLOYMENT.md).
- Persistent volumes and bind mounts: [CONTAINER_VOLUMES.md](deployment/CONTAINER_VOLUMES.md).
- Database provisioning: [DATABASE_SETUP.md](guides/DATABASE_SETUP.md).

**Environment variables:**

| Variable | Required | Purpose |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes (one LLM key) | LLM provider |
| `ARAGORA_API_TOKEN` | Yes | API authentication |
| `OPENAI_API_KEY` | No | Additional LLM provider |
| `OPENROUTER_API_KEY` | No | Fallback on quota errors |
| `GMAIL_CLIENT_ID` | No | Gmail integration |
| `GMAIL_CLIENT_SECRET` | No | Gmail integration |
| `STRIPE_SECRET_KEY` | No | Billing (Stripe) |

### Secrets Management

**Production:** Use AWS Secrets Manager (already integrated):

```yaml
# docker-compose.yml
environment:
  - ARAGORA_USE_SECRETS_MANAGER=true
  - ARAGORA_SECRET_NAME=aragora/production
  - AWS_REGION=us-east-1
  - ARAGORA_SECRETS_STRICT=true
volumes:
  - ~/.aws:/home/aragora/.aws:ro  # mount AWS credentials
```

All API keys, OAuth credentials, and tokens are loaded from AWS Secrets Manager at runtime. The `.env` file contains only non-secret configuration (AWS region, database name).

**Development:** Use `.env` file (gitignored):

```bash
cp .env.template .env  # fill in API keys
```

### Health Checks

| Endpoint | Purpose | Auth |
|----------|---------|------|
| `GET /healthz` | Liveness probe (K8s) | None |
| `GET /readyz` | Readiness probe (K8s) | None |
| `GET /health` | Detailed dependency check | API token |

### Build Variants

`deploy/Dockerfile` chooses dependencies via the `VARIANT` build arg, which
drives `scripts/ci_install_project.sh`:

| `VARIANT` | Installs |
|-----------|----------|
| `minimal` | base package only |
| `postgres` | base + PostgreSQL/Redis drivers |
| `full` (default) | base + persistence, Redis, monitoring, observability, PostgreSQL, RLM |

```dockerfile
ARG VARIANT=full   # default; also: minimal, postgres
```

The exact package groups per variant live in `scripts/ci_install_project.sh`.

## 3. Kubernetes

Helm charts and manifests are in `deploy/kubernetes/`.

```bash
# Apply manifests
kubectl apply -f deploy/kubernetes/

# Or use the Helm chart
helm install aragora deploy/kubernetes/helm/
```

**Key K8s features:**
- Liveness/readiness probes at `/healthz` and `/readyz`
- Horizontal pod autoscaler based on CPU/memory
- Secrets mounted from AWS Secrets Manager via External Secrets Operator
- PostgreSQL via CloudNativePG or RDS
- Redis via Elasticache or Bitnami chart

## Platform-Specific: Mac Studio Deployment

For running Aragora as an always-on operations server on macOS (Apple Silicon):

```bash
cd deploy/liftmode
chmod +x setup.sh
./setup.sh
```

This setup script:
1. Validates Docker + AWS CLI prerequisites
2. Creates/verifies AWS Secrets Manager secret with your API keys
3. Starts Docker Compose (backend + Redis + PostgreSQL)
4. Guides through Gmail OAuth setup
5. Installs daily briefing via macOS launchd (7:00 AM)

**Hardware:** Tested on Mac Studio M3 Ultra (96GB). Runs comfortably on any Apple Silicon Mac with 16GB+.

## Port Reference

| Port | Service | Protocol |
|------|---------|----------|
| 8080 | REST API | HTTP |
| 8765 | WebSocket | WS |
| 5432 | PostgreSQL | TCP |
| 6379 | Redis | TCP |
| 9090 | Prometheus metrics | HTTP |

## Monitoring

Enable the monitoring profile for Prometheus + Grafana:

```bash
docker compose --profile monitoring up -d
```

This adds:
- Prometheus (port 9090) — scrapes `/metrics` endpoint
- Grafana (port 3001) — pre-configured dashboards
- Jaeger (port 16686) — distributed tracing via OpenTelemetry
- Loki + Promtail — log aggregation

## TLS / HTTPS

### With Traefik (recommended)

Traefik reverse proxy with automatic Let's Encrypt certificates:

```bash
cd deploy/traefik
docker compose up -d
```

Configure in `deploy/traefik/dynamic.yml`:

```yaml
http:
  routers:
    aragora:
      rule: "Host(`aragora.yourdomain.com`)"
      entryPoints: ["websecure"]
      service: aragora
      tls:
        certResolver: letsencrypt

  services:
    aragora:
      loadBalancer:
        servers:
          - url: "http://aragora-backend:8080"
```

### Manual TLS (Nginx/Caddy)

If using an external reverse proxy, terminate TLS there and proxy to port 8080:

```nginx
server {
    listen 443 ssl;
    server_name aragora.yourdomain.com;

    ssl_certificate /etc/ssl/certs/aragora.crt;
    ssl_certificate_key /etc/ssl/private/aragora.key;

    location / {
        proxy_pass http://localhost:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }

    location /ws {
        proxy_pass http://localhost:8765;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Set `ARAGORA_ALLOWED_ORIGINS=https://aragora.yourdomain.com` for CORS.

## Backup & Restore

### Automated Backups

Aragora includes `BackupManager` with incremental backup support:

```python
from aragora.backup.manager import BackupManager

manager = BackupManager(backup_dir="/backups")
manager.create_backup()          # Full backup
manager.create_incremental()     # Incremental (since last full)
```

### Database Backup (PostgreSQL)

```bash
# Backup
docker exec aragora-postgres pg_dump -U aragora aragora > backup_$(date +%Y%m%d).sql

# Restore
docker exec -i aragora-postgres psql -U aragora aragora < backup_20260216.sql
```

### Scheduled Backups

Add to crontab or use the Docker Compose backup service:

```bash
# Daily backup at 2 AM
0 2 * * * docker exec aragora-postgres pg_dump -U aragora aragora | gzip > /backups/aragora_$(date +\%Y\%m\%d).sql.gz

# Retention: keep 30 days
0 3 * * * find /backups -name "*.sql.gz" -mtime +30 -delete
```

### Disaster Recovery

1. Stop services: `docker compose down`
2. Restore PostgreSQL: `psql < backup.sql`
3. Redis rebuilds from PostgreSQL on startup (no separate backup needed)
4. Start services: `docker compose up -d`
5. Verify: `curl http://localhost:8080/healthz`

## Upgrading

### Docker Compose

```bash
# Pull latest images from ghcr.io
docker compose pull

# Rolling restart (zero-downtime if using replicas)
docker compose up -d --no-deps aragora-backend

# Verify
curl http://localhost:8080/healthz
```

### Database Migrations

Migrations run automatically on startup. To run manually:

```bash
docker exec aragora-backend python -m aragora.db.migrate upgrade
```

Rollback:

```bash
docker exec aragora-backend python -m aragora.db.migrate downgrade --version <target>
```

### Version Pinning

Pin to a specific version in `docker-compose.yml`:

```yaml
services:
  aragora-backend:
    image: ghcr.io/synaptent/aragora/backend:2.10.0  # Pin to known-good version
```

Or via environment variable:

```bash
ARAGORA_BACKEND_IMAGE=ghcr.io/synaptent/aragora/backend:2.10.0 docker compose up -d
```

### Pre-upgrade Checklist

1. Backup database (see above)
2. Check changelog for breaking changes
3. Test upgrade in staging/offline mode first
4. Verify health endpoints after upgrade
5. Check `/api/v1/status` for feature status

## Production Hardening Checklist

- [ ] TLS configured (Traefik, Nginx, or Caddy)
- [ ] `ARAGORA_API_TOKEN` set (not default)
- [ ] `ARAGORA_ALLOWED_ORIGINS` restricted to your domain
- [ ] Database passwords changed from defaults
- [ ] Automated backups configured
- [ ] Monitoring enabled (`--profile monitoring`)
- [ ] Rate limiting configured (default: enabled)
- [ ] MFA enabled for admin accounts
- [ ] Secrets in AWS Secrets Manager (not `.env` in production)
- [ ] Health check endpoints integrated with load balancer
- [ ] Log aggregation configured (Loki/ELK)
- [ ] Resource limits set in Docker/K8s
