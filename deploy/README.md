# Aragora Deployment

## Which deployment should I use?

| Goal | Command | Time | Requirements |
|------|---------|------|-------------|
| **Try it out** | `docker compose -f docker-compose.quickstart.yml up` | 2 min | Docker only |
| **Development** | `docker compose -f docker-compose.dev.yml up` | 3 min | Docker + API key |
| **Self-hosted production** | `cd deploy/self-hosted && docker compose up -d` | 5 min | Docker + API key |
| **Kubernetes** | `kubectl apply -k deploy/kubernetes/` | 15 min | K8s cluster |

## Quickstart (no API keys needed)

```bash
docker compose -f docker-compose.quickstart.yml up
# Open http://localhost:3000 (Dashboard) / http://localhost:8080 (API)
```

Uses offline mode with mock agents and SQLite. Add `ANTHROPIC_API_KEY` to `.env` for real AI debates.

## Self-Hosted Production

The recommended production deployment. Includes PostgreSQL, Redis with Sentinel HA, and optional monitoring.

```bash
cd deploy/self-hosted
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY (required), ARAGORA_JWT_SECRET, REDIS_PASSWORD

docker compose up -d

# Optional: add monitoring (Prometheus + Grafana)
docker compose --profile monitoring up -d

# Optional: add queue workers for async debates
docker compose --profile workers up -d
```

Access points:
- Dashboard: http://localhost:3000
- API: http://localhost:8080
- WebSocket: ws://localhost:8765/ws
- Grafana: http://localhost:3001 (with `--profile monitoring`)

## Development

Hot-reload backend with Next.js dev server:

```bash
docker compose -f docker-compose.dev.yml up
```

## Directory Structure

```
deploy/
├── self-hosted/              # Production Docker Compose (recommended)
│   ├── docker-compose.yml    # Postgres + Redis Sentinel + API + Dashboard
│   ├── .env.example          # Configuration template
│   └── prometheus.yml        # Metrics config
├── kubernetes/               # K8s manifests + Kustomize
├── observability/            # Standalone Prometheus/Grafana/Loki stack
├── openclaw/                 # OpenClaw governance gateway variants
├── demo/                     # Pre-seeded demo environment
├── scripts/                  # Entrypoint, backup, healthcheck, smoke test
├── redis/                    # Redis Sentinel configuration
├── Dockerfile.backend        # Backend image
└── Dockerfile.frontend       # Frontend image
```

## Environment Variables

### Required (at least one AI provider)
| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic Claude (recommended primary) |

### Optional Providers
| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI GPT (fallback) |
| `OPENROUTER_API_KEY` | OpenRouter (auto-fallback on 429) |
| `GEMINI_API_KEY` | Google Gemini |

### Production
| Variable | Description |
|----------|-------------|
| `ARAGORA_JWT_SECRET` | JWT signing key (`openssl rand -base64 32`) |
| `REDIS_PASSWORD` | Redis auth password |
| `ARAGORA_ALLOWED_ORIGINS` | CORS origins (default: `*`) |

## Health Checks

- API: `GET /healthz`
- Metrics: `GET /metrics` (port 9090)

## Building Images

```bash
# From repo root
docker build -t aragora/api:latest .
docker build -t aragora/dashboard:latest -f deploy/Dockerfile.frontend .
```
