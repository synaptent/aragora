# Zero-Config Guarantee

Aragora is designed to work immediately after `pip install` with no API keys,
no databases, and no external services. This document specifies exactly what
works out of the box and what requires additional configuration.

## Quick Start (30 seconds)

```bash
pip install -e .
aragora serve --demo
# API ready at http://localhost:8080/api/v1/health
```

No `.env` file, no API keys, no Docker, no Redis, no Postgres.

## What Works at Each Configuration Level

### Level 0: Zero Config (`--demo`)

Everything below works with `aragora serve --demo` and zero
environment variables:

| Capability | Details |
|------------|---------|
| REST API | Full HTTP API on port 8080 |
| WebSocket streaming | Real-time events on port 8765 |
| Dashboard | Frontend at port 3000 (via Docker) or API-only |
| Demo debates | 8 mock agents with realistic responses |
| Agent leaderboard | Pre-seeded ELO ratings |
| Knowledge Mound | Demo knowledge entries |
| Decision receipts | SHA-256 audit trails |
| Memory system | In-memory stores |
| Health checks | `/api/v1/health` endpoint |
| CLI commands | `aragora ask "..." --demo --rounds 1` |

**Storage:** SQLite in `~/.aragora/` (auto-created).

**What `--demo` sets automatically:**

| Variable | Value | Effect |
|----------|-------|--------|
| `ARAGORA_OFFLINE` | `true` | Skips external service checks |
| `ARAGORA_DEMO_MODE` | `true` | Returns mock data for unavailable services |
| `ARAGORA_DB_BACKEND` | `sqlite` | Uses SQLite instead of Postgres |
| `ARAGORA_ENV` | `development` | Relaxes production validation |

### Level 1: Single API Key

Add one LLM provider key to run real agent debates:

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # or
export OPENAI_API_KEY=sk-...
aragora serve
```

This unlocks:

| Capability | Details |
|------------|---------|
| Real agent debates | Actual LLM-powered deliberation |
| Consensus detection | Semantic similarity across real responses |
| Calibration tracking | Agent accuracy measurement |
| Cross-debate learning | Pattern extraction from real outcomes |

All storage remains SQLite. No other services needed.

### Level 2: Recommended Setup

For production-quality local development:

```bash
# .env file
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
OPENROUTER_API_KEY=sk-or-...    # Auto-fallback on 429 errors
```

Additional capabilities:

| Capability | Details |
|------------|---------|
| Multi-model debates | Heterogeneous agent consensus |
| Automatic fallback | OpenRouter absorbs quota errors |
| Model diversity | DeepSeek, Llama, Qwen via OpenRouter |

### Level 3: Full Production

For deployed environments, add external services:

| Service | Variable | Unlocks |
|---------|----------|---------|
| PostgreSQL | `DATABASE_URL` | Persistent storage, concurrent access |
| Redis | `REDIS_URL` | Distributed state, caching, pub/sub |
| Supabase | `SUPABASE_URL` + `SUPABASE_KEY` | Cloud persistence, auth |
| S3 | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` | Backup storage |

## Startup Time SLOs

| Metric | Target | Measured |
|--------|--------|----------|
| CLI parser build | < 1.0s | ~0.7s |
| Module import (3000+ modules) | < 6.0s | ~4.9s (M-series Mac) |
| Server ready | < 5.0s | ~3s (offline mode) |
| Health check (p99) | < 50ms | ~5ms |

## API Latency SLOs

| Operation | p50 | p95 | p99 | Timeout |
|-----------|-----|-----|-----|---------|
| Health check | 5ms | 20ms | 50ms | 1s |
| Authentication | 50ms | 150ms | 300ms | 2s |
| Simple API call | 100ms | 300ms | 500ms | 5s |
| Debate start | 500ms | 1.5s | 3s | 10s |
| Single round | 2s | 5s | 10s | 30s |
| Full debate | 30s | 60s | 120s | 300s |

## Graceful Degradation

Every optional dependency degrades gracefully:

| Missing | Behavior |
|---------|----------|
| Redis | Falls back to in-memory stores |
| PostgreSQL | Falls back to SQLite |
| `sentence-transformers` | Disables semantic search, uses keyword matching |
| `scikit-learn` | Disables ML-based calibration, uses heuristic |
| `z3-solver` | Disables formal verification, uses runtime checks |
| LLM API keys | Demo mode with mock agents |
| `boto3` | Disables S3 backup, uses local filesystem |
| `prometheus-client` | Disables metrics export, logs internally |

## Verification

Run the offline golden path test to verify zero-config works:

```bash
# Script
bash scripts/run_offline_golden_path.sh

# Or directly
ARAGORA_OFFLINE=1 aragora ask "Zero-config smoke test" --demo --rounds 1

# Pytest
pytest tests/cli/test_offline_golden_path.py -v
```

## Docker (Zero-Config)

```bash
docker compose -f deploy/demo/docker-compose.yml up --build
```

Opens dashboard at http://localhost:3000 with full demo data.
No API keys, no external services, no volume configuration required.

## Examples (Zero-Config)

```bash
# Simple debate with mock agents
python examples/01_simple_debate.py --demo

# Python SDK example
python examples/python-debate/main.py --demo
```

Both produce realistic multi-agent debate output without any API keys.
