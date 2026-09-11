---
title: Environment Variable Reference
description: Environment Variable Reference
---

# Environment Variable Reference

> **Last Updated:** 2026-01-27


Complete reference for all environment variables used by Aragora.

## Quick Start

Copy `.env.example` to `.env` and fill in your values:
```bash
cp .env.example .env
```

## Production Required Variables

These variables **MUST** be set in production (`ARAGORA_ENV=production`). The application will fail loudly if they are missing, preventing silent fallback to localhost defaults.

| Variable | Description | Example |
|----------|-------------|---------|
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client ID | `1234567890-abc.apps.googleusercontent.com` |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth client secret | `your-client-secret` |
| `GOOGLE_OAUTH_REDIRECT_URI` | OAuth callback URL | `https://api.aragora.ai/api/auth/oauth/google/callback` |
| `OAUTH_SUCCESS_URL` | Post-login redirect | `https://aragora.ai/auth/success` |
| `OAUTH_ERROR_URL` | Auth error page | `https://aragora.ai/auth/error` |
| `OAUTH_ALLOWED_REDIRECT_HOSTS` | Comma-separated allowed hosts | `aragora.ai,api.aragora.ai` |
| `NEXT_PUBLIC_API_URL` | Frontend API base URL | `https://api.aragora.ai` |
| `NEXT_PUBLIC_WS_URL` | Frontend WebSocket URL | `wss://api.aragora.ai` |

**Warning Behavior:**
- In development mode, missing URLs will trigger console warnings but fall back to `localhost`
- In production mode (`ARAGORA_ENV=production`), missing OAuth URLs will cause startup failures
- Frontend components will log `[Aragora] NEXT_PUBLIC_API_URL not set` if using localhost fallback

**Example Production Configuration:**
```bash
# OAuth (required in production)
GOOGLE_OAUTH_CLIENT_ID=1234567890-abc.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
GOOGLE_OAUTH_REDIRECT_URI=https://api.aragora.ai/api/auth/oauth/google/callback
OAUTH_SUCCESS_URL=https://aragora.ai/auth/success
OAUTH_ERROR_URL=https://aragora.ai/auth/error
OAUTH_ALLOWED_REDIRECT_HOSTS=aragora.ai,api.aragora.ai,www.aragora.ai

# Frontend URLs (required for deployed frontend)
NEXT_PUBLIC_API_URL=https://api.aragora.ai
NEXT_PUBLIC_WS_URL=wss://api.aragora.ai
```

### OAuth Runtime Controls

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `OAUTH_STATE_TTL_SECONDS` | Optional | OAuth state TTL (seconds) | `600` |
| `OAUTH_MAX_STATES` | Optional | Max in-memory OAuth states | `10000` |

## AI Provider Keys

At least one AI provider key is required.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ANTHROPIC_API_KEY` | One required | Anthropic Claude API key | - |
| `OPENAI_API_KEY` | One required | OpenAI API key | - |
| `GEMINI_API_KEY` | Optional | Google Gemini API key | - |
| `GOOGLE_API_KEY` | Optional | Alias for `GEMINI_API_KEY` | - |
| `XAI_API_KEY` | Optional | Grok/XAI API key | - |
| `GROK_API_KEY` | Optional | Alias for XAI_API_KEY | - |
| `MISTRAL_API_KEY` | Optional | Mistral AI API key (Large, Codestral) | - |
| `OPENROUTER_API_KEY` | Optional | OpenRouter for multi-model access | - |
| `DEEPSEEK_API_KEY` | Optional | DeepSeek CLI key (for `deepseek-cli`) | - |
| `ARAGORA_OPENROUTER_FALLBACK_ENABLED` | Optional | OpenRouter fallback toggle for supported providers; set `false` to opt out | `true` |

**Note:** Never commit your `.env` file. It's gitignored for security.

### OpenRouter Models

OpenRouter provides access to multiple models through a single API:
- DeepSeek (V3, R1 Reasoner)
- Llama (Meta's open models)
- Mistral (also available via direct `MISTRAL_API_KEY`)
- Qwen (Alibaba's code and reasoning models)
- Yi (01.AI's balanced models)

See [OpenRouter docs](https://openrouter.ai/docs) for available models.

### Mistral Direct API

For best performance with Mistral models, use the direct API:
- `mistral-api` agent uses `MISTRAL_API_KEY` directly
- `codestral` agent for code-specialized tasks
- Falls back to OpenRouter if direct API fails

## Web Research (Experimental)

Enable external web research during debates (set the keys below):

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `TAVILY_API_KEY` | Optional | Tavily search API key for web research | - |

## Ollama (Local Models)

Run AI models locally with Ollama.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `OLLAMA_HOST` | Optional | Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | Optional | Default model name | `llama2` |

**Usage:**
```bash
# Install Ollama
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama2

# Set in .env (optional - defaults work for local)
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama2
```

## LM Studio (Local Models)

Run local LLMs through LM Studio's OpenAI-compatible server.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `LM_STUDIO_HOST` | Optional | LM Studio base URL | `http://localhost:1234` |

**Usage:**
```bash
# Start LM Studio server with a model loaded
# Default endpoint: http://localhost:1234/v1
LM_STUDIO_HOST=http://localhost:1234
```

## Supermemory (Cross-Session Memory)

Optional integration with [Supermemory](https://github.com/supermemoryai/supermemory) for cross-session learning and context injection. Supermemory provides external persistent memory that enables debates to learn from past sessions across projects.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SUPERMEMORY_API_KEY` | Required for feature | Supermemory API key (sm_... format) | - |
| `SUPERMEMORY_BASE_URL` | Optional | Base URL override | SDK default |
| `SUPERMEMORY_TIMEOUT` | Optional | Request timeout (seconds) | `30` |
| `SUPERMEMORY_SYNC_THRESHOLD` | Optional | Min importance to sync externally (0.0-1.0) | `0.7` |
| `SUPERMEMORY_PRIVACY_FILTER` | Optional | Enable privacy filtering before sync | `true` |
| `SUPERMEMORY_CONTAINER_TAG` | Optional | Default container tag for memories | `aragora` |

**Features:**
- **Context Injection**: Load relevant context from past sessions at debate start
- **Outcome Persistence**: Sync debate conclusions to external memory
- **Semantic Search**: Query historical memories across projects
- **Privacy Filter**: Automatically redacts API keys, tokens, passwords before sync

**Usage:**
```bash
# Enable Supermemory integration
SUPERMEMORY_API_KEY=sm_xxxxxxxxxxxxx

# Optional: adjust sync threshold (default: 0.7)
# Only debates with >= 0.7 confidence are synced externally
SUPERMEMORY_SYNC_THRESHOLD=0.8

# Optional: disable privacy filter (not recommended)
SUPERMEMORY_PRIVACY_FILTER=true

# Optional: custom container for memories
SUPERMEMORY_CONTAINER_TAG=aragora_production
```

**ArenaConfig Options:**
```python
from aragora.debate.arena_config import ArenaConfig

config = (
    ArenaConfig.builder()
    .with_supermemory(
        enable_supermemory=True,
        supermemory_enable_km_adapter=True,  # Force-enable KM adapter in coordinator
        supermemory_inject_on_start=True,
        supermemory_sync_on_conclusion=True,
    )
    .build()
)
```

**Note:** Supermemory is opt-in and disabled by default. Set `enable_supermemory=True` in ArenaConfig to activate. Use `supermemory_enable_km_adapter=True` to force-enable the Supermemory KM adapter in the bidirectional coordinator (requires `SUPERMEMORY_API_KEY`).

## Memory Capture (Tool Usage)

Optional tool-level memory capture for gateway tool/capability usage events.
Disabled by default; enable only if you want tool usage logged into the FAST
memory tier for retrieval and auditing.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_MEMORY_CAPTURE_ENABLED` | Optional | Enable tool usage capture | `false` |
| `ARAGORA_MEMORY_CAPTURE_TOOLS` | Optional | Allowlist of tool names (comma-separated) | - |
| `ARAGORA_MEMORY_SKIP_TOOLS` | Optional | Denylist of tool names (comma-separated) | - |
| `ARAGORA_MEMORY_CAPTURE_CASE_SENSITIVE` | Optional | Treat tool names as case-sensitive | `false` |
| `ARAGORA_MEMORY_CAPTURE_MAX_PER_MINUTE` | Optional | Max captured events per minute | `120` |
| `ARAGORA_MEMORY_CAPTURE_TIER` | Optional | Memory tier for tool entries | `fast` |
| `ARAGORA_MEMORY_CAPTURE_IMPORTANCE` | Optional | Importance score for captured entries | `0.4` |
| `ARAGORA_MEMORY_CAPTURE_MAX_DETAIL_CHARS` | Optional | Max detail chars to store | `800` |

## Claude-Mem (Optional Local Memory Source)

Optional integration with a local [claude-mem](https://github.com/thedotmack/claude-mem)
worker API for read-only memory search. This is an external dependency and
not bundled with Aragora.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_CLAUDE_MEM_BASE_URL` | Optional | claude-mem worker base URL | `http://localhost:37777` |
| `ARAGORA_CLAUDE_MEM_TIMEOUT` | Optional | Request timeout (seconds) | `10` |
| `ARAGORA_CLAUDE_MEM_PROJECT` | Optional | Default project filter | - |

## Persistence (Supabase)

Optional but recommended for production.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SUPABASE_URL` | Optional | Supabase project URL | - |
| `SUPABASE_KEY` | Optional | Supabase service key | - |

Enables:
- Historical debate storage
- Cross-session learning
- Live dashboard at aragora.ai

## Pluggable Storage Backends

Configure storage backends for channel integrations, tokens, workflows, and federation.
Most stores support `sqlite` and `postgres`, with optional `redis` for multi-instance
workloads and `memory` for development.

### Integration Store

Persists channel/integration configurations (Slack, Teams, Discord, Gmail).

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_INTEGRATION_STORE_BACKEND` | Optional | Backend: `memory`, `sqlite`, `postgres`, `redis` | `sqlite` |

### Gmail Token Store

Persists Gmail OAuth tokens and sync job state.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_GMAIL_STORE_BACKEND` | Optional | Backend: `memory`, `sqlite`, `postgres`, `redis` | `sqlite` |

### Unified Inbox Store

Persists unified inbox accounts, messages, and triage results.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_INBOX_STORE_BACKEND` | Optional | Backend: `memory`, `sqlite`, `postgres` | `sqlite` |

### Finding Workflow Store

Persists audit finding workflow state, assignments, and history.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_WORKFLOW_STORE_BACKEND` | Optional | Backend: `memory`, `sqlite`, `postgres`, `redis` | `sqlite` |

### Federation Registry Store

Persists federated region configurations for multi-region knowledge sync.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_FEDERATION_STORE_BACKEND` | Optional | Backend: `memory`, `sqlite`, `postgres`, `redis` | `sqlite` |

### Explainability Batch Store

Persists batch explainability job state.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_EXPLAINABILITY_STORE_BACKEND` | Optional | Backend: `redis`, `postgres`, `sqlite`, `memory` | Auto (prefers Redis) |
| `ARAGORA_EXPLAINABILITY_BATCH_TTL_SECONDS` | Optional | Batch job retention (seconds) | `3600` |
| `ARAGORA_EXPLAINABILITY_DB` | Optional | SQLite path override | - |

**Production default:** Redis with TTL. Use PostgreSQL only when long-term retention
or audit requirements apply.

**Backend Selection:**
- `memory` - Fast but not persistent; use for testing only
- `sqlite` - Default; persists to `ARAGORA_DATA_DIR/<store>.db`
- `postgres` - Production-grade persistence (recommended for multi-instance)
- `redis` - Multi-instance deployments with TTL-based job retention

**Example:**
```bash
# Use Redis for multi-instance deployment
ARAGORA_INTEGRATION_STORE_BACKEND=redis
ARAGORA_GMAIL_STORE_BACKEND=redis
ARAGORA_WORKFLOW_STORE_BACKEND=redis
ARAGORA_FEDERATION_STORE_BACKEND=redis
ARAGORA_EXPLAINABILITY_STORE_BACKEND=redis
ARAGORA_REDIS_URL=redis://localhost:6379/0
```

## Database Connection (PostgreSQL/SQLite)

Use `DATABASE_URL` for managed Postgres, or set backend-specific settings for local control.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `DATABASE_URL` | Optional | Postgres connection string (primary) | - |
| `ARAGORA_DATABASE_URL` | Optional | Legacy alias for `DATABASE_URL` | - |
| `ARAGORA_DB_BACKEND` | Optional | Backend: `sqlite`, `postgres`, `postgresql` | Auto-detect* |
| `ARAGORA_DB_MODE` | Optional | Database layout: `legacy` or `consolidated` | `legacy` |
| `ARAGORA_DB_TIMEOUT` | Optional | Connection timeout (seconds) | `30` |
| `ARAGORA_DB_POOL_SIZE` | Optional | Connection pool size | `10` |
| `ARAGORA_DB_POOL_MAX_OVERFLOW` | Optional | Extra pool connections | `5` |
| `ARAGORA_DB_POOL_OVERFLOW` | Optional | Legacy alias for overflow (settings) | - |
| `ARAGORA_DB_POOL_TIMEOUT` | Optional | Pool wait timeout (seconds) | `30` |
| `ARAGORA_SQLITE_PATH` | Optional | SQLite path for the DB backend | `aragora.db` |
| `ARAGORA_SQLITE_POOL_SIZE` | Optional | SQLite pool size (storage backend) | `10` |
| `ARAGORA_PG_HOST` | Optional | Postgres host | `localhost` |
| `ARAGORA_PG_PORT` | Optional | Postgres port | `5432` |
| `ARAGORA_PG_DATABASE` | Optional | Postgres database name | `aragora` |
| `ARAGORA_PG_USER` | Optional | Postgres user | `aragora` |
| `ARAGORA_PG_PASSWORD` | Optional | Postgres password | - |
| `ARAGORA_PG_SSL_MODE` | Optional | Postgres SSL mode | `require` |
| `ARAGORA_POSTGRESQL_POOL_SIZE` | Optional | Postgres pool size (storage backend) | `5` |
| `ARAGORA_POSTGRESQL_POOL_MAX_OVERFLOW` | Optional | Postgres overflow (storage backend) | `10` |
| `ARAGORA_POLICY_STORE_BACKEND` | Optional | Policy store backend: `sqlite`, `postgres`, `postgresql` | Uses `ARAGORA_DB_BACKEND` |
| `ARAGORA_AUDIT_STORE_BACKEND` | Optional | Audit log backend: `sqlite`, `postgres`, `postgresql` | Uses `ARAGORA_DB_BACKEND` |

## Control Plane Policy Sync

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_CONTROL_PLANE_POLICY_SOURCE` | Optional | Policy source: `compliance`, `inprocess` | Auto (compliance in production) |
| `ARAGORA_REQUIRE_DISTRIBUTED` | Optional | Fail closed when stores fall back to local (prod default) | `auto` |
| `ARAGORA_STORAGE_MODE` | Optional | Force storage mode: `postgres`, `redis`, `sqlite`, `file` | `auto` |

## Control Plane Watchdog

Three-tier monitoring system for agent health and SLA compliance. See [WATCHDOG](../operations/watchdog) for architecture details.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `CP_ENABLE_WATCHDOG` | Optional | Enable the three-tier watchdog system | `true` |
| `CP_WATCHDOG_CHECK_INTERVAL` | Optional | Tier check interval (seconds) | `5` |
| `CP_WATCHDOG_HEARTBEAT_TIMEOUT` | Optional | Agent heartbeat timeout (seconds) | `30` |
| `CP_WATCHDOG_AUTO_ESCALATE` | Optional | Auto-escalate issues to higher tiers | `true` |
| `CP_WATCHDOG_ESCALATION_THRESHOLD` | Optional | Issues before escalating | `3` |
| `CP_WATCHDOG_MEMORY_WARNING_MB` | Optional | Memory usage warning threshold (MB) | `1024` |
| `CP_WATCHDOG_MEMORY_CRITICAL_MB` | Optional | Memory usage critical threshold (MB) | `2048` |
| `CP_WATCHDOG_LATENCY_WARNING_MS` | Optional | Latency warning threshold (ms) | `5000` |
| `CP_WATCHDOG_LATENCY_CRITICAL_MS` | Optional | Latency critical threshold (ms) | `15000` |
| `CP_WATCHDOG_ERROR_RATE_WARNING` | Optional | Error rate warning threshold (0.0-1.0) | `0.1` |
| `CP_WATCHDOG_ERROR_RATE_CRITICAL` | Optional | Error rate critical threshold (0.0-1.0) | `0.3` |
| `CP_WATCHDOG_SLA_AVAILABILITY_PCT` | Optional | SLA availability target (percent) | `99.0` |
| `CP_WATCHDOG_SLA_RESPONSE_TIME_MS` | Optional | SLA response time target (ms) | `10000` |

**Example Configuration:**
```bash
# Production: strict monitoring
CP_ENABLE_WATCHDOG=true
CP_WATCHDOG_CHECK_INTERVAL=2
CP_WATCHDOG_HEARTBEAT_TIMEOUT=10
CP_WATCHDOG_AUTO_ESCALATE=true
CP_WATCHDOG_SLA_AVAILABILITY_PCT=99.9

# Development: relaxed monitoring
CP_ENABLE_WATCHDOG=true
CP_WATCHDOG_CHECK_INTERVAL=30
CP_WATCHDOG_HEARTBEAT_TIMEOUT=120
CP_WATCHDOG_AUTO_ESCALATE=false
```

## Skills System

Skills provide specialized capabilities to agents during debates. See [SKILLS](../guides/skills) for usage.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SKILLS_ENABLED` | Optional | Enable the skills system | `true` |
| `ARAGORA_SKILLS_RATE_LIMIT` | Optional | Skills API rate limit (req/min) | `30` |
| `ARAGORA_SKILLS_TIMEOUT` | Optional | Default skill invocation timeout (seconds) | `30` |
| `ARAGORA_SKILLS_MAX_TIMEOUT` | Optional | Maximum allowed skill timeout (seconds) | `60` |
| `ARAGORA_MARKETPLACE_DB` | Optional | SQLite path for the skills marketplace | `:memory:` |
| `GOOGLE_SEARCH_API_KEY` | Optional | Google Custom Search API key | - |
| `GOOGLE_SEARCH_CX` | Optional | Google Custom Search engine ID | - |

**Notes:**
- `TAVILY_API_KEY` (documented in Web Research section) is used by web search skills
- `GOOGLE_SEARCH_API_KEY` + `GOOGLE_SEARCH_CX` enable Google search skills
- Skills can define their own API key requirements

**\*Auto-detect Behavior:**
- If `DATABASE_URL` or `ARAGORA_POSTGRES_DSN` is set → uses PostgreSQL
- Otherwise → uses SQLite for local development
- Set `ARAGORA_DB_BACKEND` explicitly to override auto-detection
- Store-specific backends (policy/audit) inherit `ARAGORA_DB_BACKEND` unless overridden
- `ARAGORA_REQUIRE_DISTRIBUTED=true` enforces distributed stores in production
- `ARAGORA_REQUIRE_DISTRIBUTED_STATE` is a legacy alias honored when
  `ARAGORA_REQUIRE_DISTRIBUTED` is unset

**Production Setup:**
```bash
# Set PostgreSQL connection string (auto-enables PostgreSQL backend)
DATABASE_URL=postgresql://user:password@host:5432/aragora

# Or use Supabase PostgreSQL
DATABASE_URL=postgresql://postgres:[password]@[project].supabase.co:5432/postgres

# Initialize database tables (choose one method)

# Method 1: Direct store initialization (development)
python scripts/init_postgres_db.py

# Method 2: Alembic migrations (production recommended)
python scripts/init_postgres_db.py --alembic
# Or run Alembic directly:
alembic upgrade head

# Verify tables exist
python scripts/init_postgres_db.py --verify
```

**Migration Management with Alembic:**
```bash
# Check current migration status
alembic current

# Upgrade to latest schema
alembic upgrade head

# Downgrade one revision
alembic downgrade -1

# Generate new migration (after schema changes)
alembic revision --autogenerate -m "description"
```

Note: `ARAGORA_DB_MODE` defaults to `legacy` in the legacy config, while
`aragora.persistence.db_config` defaults to `consolidated` if unset. Set it
explicitly to avoid ambiguity. The storage backend also honors the
`ARAGORA_SQLITE_POOL_SIZE` / `ARAGORA_POSTGRESQL_*` pool settings; set them
explicitly if you need consistent pooling across subsystems.

## Server Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_API_URL` | Optional | API base URL for CLI/SDK clients | `http://localhost:8080` |
| `ARAGORA_ENV` | Recommended | `development` or `production` | `development` |
| `ARAGORA_ENVIRONMENT` | Optional | Alias used by billing/auth | `development` |
| `ARAGORA_API_TOKEN` | Optional | Enable token auth | Disabled |
| `ARAGORA_TOKEN_TTL` | Optional | Token lifetime (seconds) | `3600` |
| `ARAGORA_WS_MAX_MESSAGE_SIZE` | Optional | Max WebSocket message size | `65536` |
| `ARAGORA_WS_HEARTBEAT` | Optional | WebSocket heartbeat interval (seconds) | `30` |
| `ARAGORA_DEFAULT_HOST` | Optional | Fallback host for link generation | `localhost:8080` |
| `ARAGORA_NOTIFICATION_WORKER` | Optional | Enable notification worker (`0` to disable) | `1` |
| `ARAGORA_NOTIFICATION_CONCURRENCY` | Optional | Max concurrent notification deliveries | `20` |

## Debate Defaults

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DEFAULT_ROUNDS` | Optional | Default debate rounds | `9` |
| `ARAGORA_MAX_ROUNDS` | Optional | Max debate rounds | `12` |
| `ARAGORA_DEFAULT_CONSENSUS` | Optional | Consensus mode | `judge` |
| `ARAGORA_DEBATE_TIMEOUT` | Optional | Debate timeout (seconds) | `600` |
| `ARAGORA_AGENT_TIMEOUT` | Optional | Per-agent timeout (seconds) | `240` |

## Agent Defaults

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DEFAULT_AGENTS` | Optional | Default agent list when none specified | `grok,anthropic-api,openai-api,deepseek,mistral,gemini,qwen,kimi` |
| `ARAGORA_STREAMING_AGENTS` | Optional | Agents allowed for streaming responses | `grok,anthropic-api,openai-api,mistral` |

## Streaming Controls

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_STREAM_BUFFER_SIZE` | Optional | Max SSE buffer size (bytes) | `10485760` |
| `ARAGORA_STREAM_CHUNK_TIMEOUT` | Optional | Timeout between stream chunks (seconds) | `180` |

## WebSocket & Audience Limits

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_TRUSTED_PROXIES` | Optional | Comma-separated proxy IPs for client IP resolution | `127.0.0.1,::1,localhost` |
| `ARAGORA_WS_CONN_RATE` | Optional | WS connections per IP per minute | `30` |
| `ARAGORA_WS_MAX_PER_IP` | Optional | Max concurrent WS connections per IP | `10` |
| `ARAGORA_WS_MSG_RATE` | Optional | WS messages per second per connection | `10` |
| `ARAGORA_WS_MSG_BURST` | Optional | WS message burst size | `20` |
| `ARAGORA_AUDIENCE_INBOX_MAX_SIZE` | Optional | Audience inbox queue size | `1000` |
| `ARAGORA_MAX_EVENT_QUEUE_SIZE` | Optional | Event queue size (server) | `10000` |

## Automation Trust (Auto-Merge & Triage)

The merge arbiter and PR triage / auto-merge tooling gate decisions on an
allowlist of trusted author / reviewer logins. The committed defaults contain
only generic automation identities (bot accounts) and **no personal GitHub
login**, so a public fork never auto-trusts an operator's handle. Operators opt
their own logins in via environment variables (comma-separated, whitespace
trimmed):

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_TRUSTED_AUTHORS` | Optional | Logins trusted for auto-merge / triage and treated as automation authors. Unioned with the generic defaults. | _(empty)_ |
| `ARAGORA_BUCKET_A_TRUSTED_AUTHORS` | Optional | Extra logins trusted specifically by `scripts/auto_merge_bucket_a.py` (unioned with `ARAGORA_TRUSTED_AUTHORS`). | _(empty)_ |

Consumed by `aragora/swarm/merge_arbiter.py`, `aragora/triage/evidence.py`,
`scripts/triage_open_prs.py`, and `scripts/auto_merge_bucket_a.py` through the
shared resolver `aragora.config.trusted_authors.resolve_trusted_authors`.

**Migration note:** earlier releases hardcoded `an0mium` as a default trusted
login. To preserve that behavior set `ARAGORA_TRUSTED_AUTHORS=an0mium` in your
`.env` (and in any CI / launchd environment where this tooling runs).

## Reserved / Not Yet Wired

These variables exist in the settings schema but are not currently wired into runtime behavior.

| Variable | Description | Default | Status |
|----------|-------------|---------|--------|
| `ARAGORA_MAX_CONTEXT_CHARS` | Max context length for truncation (chars) | `100000` | Planned |
| `ARAGORA_MAX_MESSAGE_CHARS` | Max message length for truncation (chars) | `50000` | Planned |
| `ARAGORA_LOCAL_FALLBACK_ENABLED` | Enable local LLM fallback in provider chains | `false` | Planned |
| `ARAGORA_LOCAL_FALLBACK_PRIORITY` | Prefer local LLMs over OpenRouter | `false` | Planned |

**Note:** `aragora serve` runs HTTP on port 8080 and WebSocket on port 8765 by default. The WebSocket server accepts `/` or `/ws`. For single-port deployments, embed `AiohttpUnifiedServer` (advanced).

## Legacy/Deployment Host & Port

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_HOST` | Optional | Legacy bind host used by deployment templates | `0.0.0.0` |
| `ARAGORA_PORT` | Optional | Legacy HTTP port used by deployment templates | `8080` |

These are not read by the CLI server directly; prefer `aragora serve --api-port/--ws-port` in local dev.

### Environment Mode

Set `ARAGORA_ENVIRONMENT=production` for production deployments. This enables:
- Strict JWT secret validation (required, minimum 32 characters)
- Disabled unsafe JWT fallbacks
- Blocked format-only API key validation
- Stricter security defaults

## Data Directory

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DATA_DIR` | Recommended | Directory for all runtime data (databases, etc.) | `.nomic` |

All databases are stored under this directory:
- `agent_elo.db` - ELO rankings
- `continuum.db` - Memory storage
- `consensus_memory.db` - Consensus records
- `token_blacklist.db` - Revoked JWT tokens
- And others...

Related directories:
- `ARAGORA_NOMIC_DIR` - Legacy alias used by some migration tooling (defaults to `.nomic`)
- `ARAGORA_STORAGE_DIR` - Non-DB runtime artifacts (plugins, reviews, modes) default to `.aragora`

**Production recommended:** `/var/lib/aragora` or `~/.aragora` for `ARAGORA_DATA_DIR`

Use `aragora.config.resolve_db_path()` to keep legacy SQLite files under
`ARAGORA_DATA_DIR`. For consolidated mapping, use
`aragora.persistence.db_config.get_db_path()`.

### Cleanup (repo root artifacts)

If you ran Aragora in the repo root, stray `.db` files may land there. Move them under `ARAGORA_DATA_DIR` with:

```bash
python scripts/cleanup_runtime_artifacts.py --apply
```

For a DB-only migration with tracked-file safeguards, preview first:

```bash
python scripts/migrate_runtime_dbs.py --dry-run
```

## Receipt Retention

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_RECEIPT_RETENTION_DAYS` | Optional | How long to keep decision receipts | `2555` (~7 years) |
| `ARAGORA_RECEIPT_CLEANUP_INTERVAL_HOURS` | Optional | How often to run receipt cleanup | `24` |

Decision receipts are cryptographic audit trails for debates. They're automatically cleaned up by a background scheduler.

**Compliance note:** The default 7-year retention aligns with financial audit requirements. Adjust based on your regulatory requirements.

## CORS Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ALLOWED_ORIGINS` | Optional | Comma-separated allowed origins | See below |

Default origins:
```
http://localhost:3000,http://localhost:8080,
http://127.0.0.1:3000,http://127.0.0.1:8080,
https://aragora.ai,https://www.aragora.ai,
https://api.aragora.ai
```

Example:
```bash
ARAGORA_ALLOWED_ORIGINS=https://myapp.com,https://staging.myapp.com
```

## Webhook Integration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_WEBHOOKS` | Optional | JSON array of webhook configs | - |
| `ARAGORA_WEBHOOKS_CONFIG` | Optional | Path to JSON config file | - |
| `ARAGORA_WEBHOOK_QUEUE_SIZE` | Optional | Max queued events | `1000` |
| `ARAGORA_WEBHOOK_ALLOW_LOCALHOST` | Optional | Allow localhost webhook targets (dev only) | `false` |
| `ARAGORA_WEBHOOK_WORKERS` | Optional | Max concurrent deliveries | `10` |
| `ARAGORA_WEBHOOK_MAX_RETRIES` | Optional | Delivery retry attempts | `3` |
| `ARAGORA_WEBHOOK_RETRY_DELAY` | Optional | Initial retry delay (seconds) | `1.0` |
| `ARAGORA_WEBHOOK_MAX_RETRY_DELAY` | Optional | Max retry delay (seconds) | `60.0` |
| `ARAGORA_WEBHOOK_TIMEOUT` | Optional | Request timeout (seconds) | `30.0` |

`ARAGORA_WEBHOOKS` and `ARAGORA_WEBHOOKS_CONFIG` accept a JSON array of configs with:
`name`, `url`, optional `secret`, optional `event_types`, and optional `loop_ids`.

## Slack Integration (Server)

Configure Slack slash commands and outbound notifications.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SLACK_SIGNING_SECRET` | Optional | Verify Slack request signatures | - |
| `SLACK_BOT_TOKEN` | Optional | Bot token for Slack API calls | - |
| `SLACK_WEBHOOK_URL` | Optional | Outbound Slack webhook URL | - |

## Rate Limiting

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_RATE_LIMIT` | Optional | Requests per minute per token | `60` |
| `ARAGORA_IP_RATE_LIMIT` | Optional | Requests per minute per IP | `120` |
| `ARAGORA_BURST_MULTIPLIER` | Optional | Burst multiplier for short spikes | `2.0` |
| `ARAGORA_REDIS_URL` | Optional | Redis URL for distributed rate limits | `redis://localhost:6379/0` |
| `REDIS_URL` | Optional | Legacy Redis URL used by queues/oauth/token revocation | `redis://localhost:6379` |
| `ARAGORA_REDIS_KEY_PREFIX` | Optional | Redis key prefix | `aragora:ratelimit:` |
| `ARAGORA_REDIS_TTL` | Optional | Redis TTL for limiter keys (seconds) | `120` |
| `ARAGORA_REDIS_MAX_CONNECTIONS` | Optional | Redis connection pool max size | `50` |
| `ARAGORA_REDIS_SOCKET_TIMEOUT` | Optional | Redis socket timeout (seconds) | `5.0` |
| `ARAGORA_RATE_LIMIT_FAIL_OPEN` | Optional | Allow requests if Redis is down (`true`/`false`) | `false` |
| `ARAGORA_REDIS_FAILURE_THRESHOLD` | Optional | Failures before Redis limiter disables (count) | `3` |

## Redis High-Availability (HA) Configuration

Aragora supports three Redis deployment modes for different availability and scaling requirements:

- **Standalone**: Single Redis instance (development/testing)
- **Sentinel**: Redis Sentinel for automatic failover (production HA)
- **Cluster**: Redis Cluster for horizontal scaling (enterprise)

### Core Redis HA Settings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REDIS_MODE` | Optional | Redis mode: `standalone`, `sentinel`, `cluster` | Auto-detect |
| `ARAGORA_REDIS_URL` | Optional | Redis URL for standalone mode | `redis://localhost:6379/0` |
| `REDIS_URL` | Optional | Legacy Redis URL (fallback) | `redis://localhost:6379` |
| `ARAGORA_REDIS_HOST` | Optional | Redis host for standalone mode | `localhost` |
| `ARAGORA_REDIS_PORT` | Optional | Redis port for standalone mode | `6379` |
| `ARAGORA_REDIS_PASSWORD` | Optional | Redis authentication password | - |
| `ARAGORA_REDIS_DB` | Optional | Redis database number | `0` |

### Redis Sentinel Configuration

Redis Sentinel provides automatic failover for high availability.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REDIS_SENTINEL_HOSTS` | For Sentinel | Comma-separated sentinel hosts (e.g., `sentinel1:26379,sentinel2:26379,sentinel3:26379`) | - |
| `ARAGORA_REDIS_SENTINEL_MASTER` | Optional | Sentinel master name | `mymaster` |
| `ARAGORA_REDIS_SENTINEL_PASSWORD` | Optional | Sentinel authentication password | - |

**Example Sentinel Configuration:**
```bash
# 3-node Redis Sentinel setup
ARAGORA_REDIS_MODE=sentinel
ARAGORA_REDIS_SENTINEL_HOSTS=sentinel1:26379,sentinel2:26379,sentinel3:26379
ARAGORA_REDIS_SENTINEL_MASTER=mymaster
ARAGORA_REDIS_PASSWORD=your-redis-password
ARAGORA_REDIS_SENTINEL_PASSWORD=your-sentinel-password
```

### Redis Cluster Configuration

Redis Cluster provides horizontal scaling with automatic sharding.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REDIS_CLUSTER_NODES` | For Cluster | Comma-separated cluster nodes (e.g., `redis1:6379,redis2:6379,redis3:6379`) | - |
| `ARAGORA_REDIS_CLUSTER_READ_FROM_REPLICAS` | Optional | Enable read from replicas | `true` |
| `ARAGORA_REDIS_CLUSTER_SKIP_FULL_COVERAGE` | Optional | Skip slot coverage check | `false` |

**Example Cluster Configuration:**
```bash
# 3-node Redis Cluster
ARAGORA_REDIS_MODE=cluster
ARAGORA_REDIS_CLUSTER_NODES=redis-node1:6379,redis-node2:6379,redis-node3:6379
ARAGORA_REDIS_CLUSTER_READ_FROM_REPLICAS=true
ARAGORA_REDIS_PASSWORD=your-cluster-password
```

### Common Connection Settings

These settings apply to all Redis modes.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REDIS_SOCKET_TIMEOUT` | Optional | Socket timeout (seconds) | `5.0` |
| `ARAGORA_REDIS_SOCKET_CONNECT_TIMEOUT` | Optional | Connection timeout (seconds) | `5.0` |
| `ARAGORA_REDIS_MAX_CONNECTIONS` | Optional | Max connections in pool | `50` |
| `ARAGORA_REDIS_RETRY_ON_TIMEOUT` | Optional | Retry on timeout | `true` |
| `ARAGORA_REDIS_HEALTH_CHECK_INTERVAL` | Optional | Health check interval (seconds) | `30` |
| `ARAGORA_REDIS_DECODE_RESPONSES` | Optional | Decode responses to strings | `true` |

### Redis SSL/TLS Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REDIS_SSL` | Optional | Enable SSL/TLS | `false` |
| `ARAGORA_REDIS_SSL_CERT_REQS` | Optional | SSL certificate requirements | - |
| `ARAGORA_REDIS_SSL_CA_CERTS` | Optional | Path to CA certificates | - |

### Auto-Detection Behavior

When `ARAGORA_REDIS_MODE` is not set:
- If `ARAGORA_REDIS_SENTINEL_HOSTS` is set -> Sentinel mode
- If `ARAGORA_REDIS_CLUSTER_NODES` is set -> Cluster mode
- Otherwise -> Standalone mode

### Features

- **Auto-detection**: Automatically detects deployment mode from configuration
- **Connection pooling**: Manages connections with health monitoring
- **Graceful failover**: Automatic reconnection on node failures (Sentinel/Cluster)
- **Read scaling**: Distributes reads across replicas when enabled (Cluster)
- **Hash tag support**: Use `\{tag\}` in keys for slot affinity (e.g., `{user:123}:session`)
- **SSL/TLS**: Secure connections for production deployments

### Production Recommendations

**For Sentinel (recommended for most production deployments):**
```bash
# Minimum 3 sentinel nodes for quorum
ARAGORA_REDIS_SENTINEL_HOSTS=sentinel1:26379,sentinel2:26379,sentinel3:26379
ARAGORA_REDIS_SENTINEL_MASTER=mymaster
ARAGORA_REDIS_PASSWORD=your-strong-password
ARAGORA_REDIS_SSL=true
```

**For Cluster (recommended for high-throughput/large datasets):**
```bash
# Minimum 3 master nodes with replicas
ARAGORA_REDIS_CLUSTER_NODES=redis1:6379,redis2:6379,redis3:6379
ARAGORA_REDIS_CLUSTER_READ_FROM_REPLICAS=true
ARAGORA_REDIS_PASSWORD=your-strong-password
ARAGORA_REDIS_SSL=true
```

## Request Timeout Middleware

Controls HTTP request timeouts to prevent hanging requests and cascading failures.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_REQUEST_TIMEOUT` | Optional | Default request timeout (seconds) | `30` |
| `ARAGORA_SLOW_REQUEST_TIMEOUT` | Optional | Timeout for slow endpoints like debates, broadcasts (seconds) | `60` |
| `ARAGORA_MAX_REQUEST_TIMEOUT` | Optional | Maximum allowed timeout (seconds) | `300` |
| `ARAGORA_TIMEOUT_WORKERS` | Optional | Thread pool size for sync timeout operations | `4` |

**Slow Endpoint Patterns** (automatically use `ARAGORA_SLOW_REQUEST_TIMEOUT`):
- `/api/debates/` - Debate orchestration
- `/api/broadcast/` - Audio/video generation
- `/api/evidence/` - Evidence collection
- `/api/gauntlet/` - Comprehensive testing

**Per-endpoint Overrides:**
```python
from aragora.server.middleware.timeout import configure_timeout

configure_timeout(
    endpoint_overrides={
        "/api/debates/run": 120.0,  # 2 minutes for debate runs
        "/api/broadcast/generate": 180.0,  # 3 minutes for video generation
    }
)
```

## Billing & Authentication

JWT authentication and Stripe integration for paid tiers.

### JWT Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_JWT_SECRET` | **Required (prod)** | Secret key for JWT signing (min 32 chars) | - |
| `ARAGORA_JWT_SECRET_PREVIOUS` | Optional | Previous secret for rotation | - |
| `ARAGORA_JWT_SECRET_ROTATED_AT` | Optional | Unix timestamp of rotation | - |
| `ARAGORA_JWT_ROTATION_GRACE_HOURS` | Optional | Grace period for previous secret | `24` |
| `ARAGORA_JWT_EXPIRY_HOURS` | Optional | Access token expiry (max 168h/7d) | `24` |
| `ARAGORA_REFRESH_TOKEN_EXPIRY_DAYS` | Optional | Refresh token expiry (max 90d) | `30` |
| `ARAGORA_ALLOW_FORMAT_ONLY_API_KEYS` | Optional | Allow API key format-only validation (dev only) | `0` |

**Security Notes:**
- In **production** (`ARAGORA_ENVIRONMENT=production`), `ARAGORA_JWT_SECRET` is **required** and must be at least 32 characters.
- Generate a secure secret: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- In other environments, set `ARAGORA_JWT_SECRET` if you use auth endpoints (missing secrets raise config errors).
- `ARAGORA_JWT_SECRET_PREVIOUS` is only honored if `ARAGORA_JWT_SECRET_ROTATED_AT` is set.
- Set `ARAGORA_JWT_ROTATION_GRACE_HOURS` to control the previous-secret window.
- `ARAGORA_ALLOW_FORMAT_ONLY_API_KEYS` is blocked in production regardless of setting.

### Token Blacklist Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_BLACKLIST_BACKEND` | Optional | Backend type: `memory`, `sqlite`, `redis` | `sqlite` |
| `ARAGORA_REDIS_URL` | For redis | Redis connection URL | `redis://localhost:6379/0` |

- **memory**: Fast but not persistent; use for development only
- **sqlite**: Default; persists to `ARAGORA_DATA_DIR/token_blacklist.db`
- **redis**: Use for multi-instance deployments (requires `redis` package)

### Stripe Integration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `STRIPE_SECRET_KEY` | For billing | Stripe API secret key | - |
| `STRIPE_WEBHOOK_SECRET` | For billing | Webhook signing secret | - |
| `STRIPE_PRICE_STARTER` | For billing | Price ID for Starter tier | - |
| `STRIPE_PRICE_PROFESSIONAL` | For billing | Price ID for Professional tier | - |
| `STRIPE_PRICE_ENTERPRISE` | For billing | Price ID for Enterprise tier | - |

See [BILLING.md](../enterprise/billing) for subscription tiers and usage tracking.

### Billing Notifications

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SMTP_HOST` | Optional | SMTP server host | - |
| `ARAGORA_SMTP_PORT` | Optional | SMTP server port | `587` |
| `ARAGORA_SMTP_USER` | Optional | SMTP username | - |
| `ARAGORA_SMTP_PASSWORD` | Optional | SMTP password | - |
| `ARAGORA_SMTP_FROM` | Optional | From email address | `billing@aragora.ai` |
| `ARAGORA_NOTIFICATION_WEBHOOK` | Optional | Webhook URL for billing notifications | - |
| `ARAGORA_PAYMENT_GRACE_DAYS` | Optional | Days before downgrade after payment failure | `10` |
| `ARAGORA_ALLOW_INSECURE_PASSWORDS` | Optional | Allow weak passwords (dev only) | `0` |

## SSO/Enterprise Authentication

Single Sign-On configuration for enterprise authentication. Supports OIDC and SAML 2.0.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SSO_ENABLED` | No | Enable SSO authentication | `false` |
| `ARAGORA_SSO_PROVIDER_TYPE` | If SSO enabled | Provider type: `oidc`, `saml`, `azure_ad`, `okta`, `google` | `oidc` |
| `ARAGORA_SSO_CALLBACK_URL` | If SSO enabled | Callback URL for auth response (must be HTTPS in production) | - |
| `ARAGORA_SSO_ENTITY_ID` | If SSO enabled | Service provider entity ID | - |

### OIDC Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SSO_CLIENT_ID` | OIDC | OAuth client ID | - |
| `ARAGORA_SSO_CLIENT_SECRET` | OIDC | OAuth client secret | - |
| `ARAGORA_SSO_ISSUER_URL` | OIDC | OIDC issuer URL (e.g., `https://login.microsoftonline.com/tenant/v2.0`) | - |
| `ARAGORA_SSO_AUTH_ENDPOINT` | Optional | Override authorization endpoint | Auto-discovered |
| `ARAGORA_SSO_TOKEN_ENDPOINT` | Optional | Override token endpoint | Auto-discovered |
| `ARAGORA_SSO_USERINFO_ENDPOINT` | Optional | Override userinfo endpoint | Auto-discovered |
| `ARAGORA_SSO_JWKS_URI` | Optional | Override JWKS URI | Auto-discovered |
| `ARAGORA_SSO_SCOPES` | Optional | OAuth scopes | `openid,email,profile` |

### SAML Configuration

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SSO_IDP_ENTITY_ID` | SAML | IdP entity ID | - |
| `ARAGORA_SSO_IDP_SSO_URL` | SAML | IdP SSO URL | - |
| `ARAGORA_SSO_IDP_SLO_URL` | Optional | IdP logout URL | - |
| `ARAGORA_SSO_IDP_CERTIFICATE` | SAML | IdP X.509 certificate (PEM format) | - |
| `ARAGORA_SSO_SP_CERTIFICATE` | Optional | SP X.509 certificate for signed requests (PEM) | - |
| `ARAGORA_SSO_SP_PRIVATE_KEY` | Optional | SP private key for signed requests (PEM) | - |

### SSO Options

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SSO_ALLOWED_DOMAINS` | Optional | Comma-separated allowed email domains | - (all allowed) |
| `ARAGORA_SSO_ALLOWED_REDIRECT_HOSTS` | Optional | Allowed redirect hosts for SSO callbacks | - |
| `ARAGORA_SSO_AUTO_PROVISION` | Optional | Auto-create users on first login | `true` |
| `ARAGORA_SSO_SESSION_DURATION` | Optional | Session duration in seconds (300-604800) | `28800` (8h) |

**Security Notes:**
- In **production** (`ARAGORA_ENV=production`), callback URLs must use HTTPS
- SAML in production requires `python3-saml` package for signature validation
- Certificates must be in PEM format (starting with `-----BEGIN`)

**Example OIDC Configuration (Azure AD):**
```bash
ARAGORA_SSO_ENABLED=true
ARAGORA_SSO_PROVIDER_TYPE=azure_ad
ARAGORA_SSO_CLIENT_ID=your-app-client-id
ARAGORA_SSO_CLIENT_SECRET=your-client-secret
ARAGORA_SSO_ISSUER_URL=https://login.microsoftonline.com/your-tenant-id/v2.0
ARAGORA_SSO_CALLBACK_URL=https://your-app.example.com/auth/sso/callback
ARAGORA_SSO_ENTITY_ID=https://your-app.example.com
ARAGORA_SSO_ALLOWED_DOMAINS=yourcompany.com
```

See [SSO_SETUP.md](../enterprise/sso) for detailed provider-specific setup instructions.

### SCIM 2.0 Provisioning

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SCIM_BEARER_TOKEN` | Yes (for SCIM) | Bearer token for SCIM endpoint authentication | _(empty - no auth)_ |
| `SCIM_TENANT_ID` | Optional | Tenant ID for multi-tenant SCIM deployments | _(none)_ |
| `SCIM_BASE_URL` | Optional | Base URL for SCIM resource location headers | _(empty)_ |

Example SCIM Configuration:
```bash
SCIM_BEARER_TOKEN=scim-secret-token-from-idp
SCIM_TENANT_ID=acme-corp
SCIM_BASE_URL=https://api.aragora.ai
```

SCIM endpoints are available at `/scim/v2/Users` and `/scim/v2/Groups`.
See [API_REFERENCE.md](../api/reference) for full endpoint documentation.

## Embedding Providers

For semantic search and memory retrieval.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `OPENAI_EMBEDDING_MODEL` | Optional | OpenAI embedding model | `text-embedding-3-small` |

Currently uses OpenAI or Gemini embeddings based on available API keys.

## Broadcast / TTS

Configure audio generation backends for broadcasts.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_TTS_ORDER` | Optional | Comma-separated backend priority | `elevenlabs,xtts,edge-tts,pyttsx3` |
| `ARAGORA_TTS_BACKEND` | Optional | Force a specific backend | - |
| `ARAGORA_ELEVENLABS_API_KEY` | Optional | ElevenLabs API key | - |
| `ARAGORA_ELEVENLABS_MODEL_ID` | Optional | ElevenLabs model ID | `eleven_multilingual_v2` |
| `ARAGORA_ELEVENLABS_VOICE_ID` | Optional | Default ElevenLabs voice ID | - |
| `ARAGORA_ELEVENLABS_VOICE_MAP` | Optional | JSON map of speaker→voice ID | - |
| `ARAGORA_XTTS_MODEL_PATH` | Optional | Coqui XTTS model name/path | `tts_models/multilingual/multi-dataset/xtts_v2` |
| `ARAGORA_XTTS_DEVICE` | Optional | XTTS device (`auto`, `cuda`, `cpu`) | `auto` |
| `ARAGORA_XTTS_LANGUAGE` | Optional | XTTS language code | `en` |
| `ARAGORA_XTTS_SPEAKER_WAV` | Optional | Default XTTS speaker WAV path | - |
| `ARAGORA_XTTS_SPEAKER_WAV_MAP` | Optional | JSON map of speaker→WAV path | - |

Notes:
- `ELEVENLABS_API_KEY` is also accepted as an alias for `ARAGORA_ELEVENLABS_API_KEY`.
- Use `ARAGORA_TTS_ORDER` to prioritize ElevenLabs or XTTS ahead of edge-tts.

## Social Media APIs (Pulse Module)

For trending topics and real-time context in debates. These power the Pulse ingestors.

| Variable | Required | Description | Source |
|----------|----------|-------------|--------|
| `TWITTER_BEARER_TOKEN` | Optional | Twitter/X API v2 Bearer token for trending topics | [Twitter Developer Portal](https://developer.twitter.com/en/portal/dashboard) |
| `ARAGORA_ALLOWED_OAUTH_HOSTS` | Optional | Comma-separated allowed hosts for social OAuth redirects | `localhost:8080,127.0.0.1:8080` (dev) |

**No credentials needed:**
- **Reddit** - Uses public JSON API (`reddit.com/.json`)
- **Hacker News** - Uses public Firebase API (`hacker-news.firebaseio.com`)

These services are automatically enabled when the pulse module loads.

### Getting Twitter API Access

1. Create a developer account at [developer.twitter.com](https://developer.twitter.com)
2. Create a new project and app
3. Generate a Bearer Token (read-only access is sufficient)
4. Add to your `.env`:
   ```bash
   TWITTER_BEARER_TOKEN=AAAAAAAAAAAAAAAAAAAAAx...
   ```

### Pulse Module Usage

The pulse module fetches trending topics that can inform debate context:

```python
from aragora.pulse import PulseManager

pulse = PulseManager()
trends = await pulse.get_trending()  # Returns combined trends from all sources
```

## Formal Verification

> **Note:** These variables are defined but not yet actively used in the codebase.

| Variable | Required | Description | Default | Status |
|----------|----------|-------------|---------|--------|
| `Z3_TIMEOUT` | Optional | Z3 solver timeout (seconds) | `30` | Planned |
| `LEAN_PATH` | Optional | Path to Lean 4 installation | Auto-detect | Planned |

## OpenTelemetry OTLP Export

Configure distributed tracing export to external backends like Jaeger, Zipkin, or Datadog.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_OTLP_EXPORTER` | Optional | Exporter type: `none`, `jaeger`, `zipkin`, `otlp_grpc`, `otlp_http`, `datadog` | `none` |
| `ARAGORA_OTLP_ENDPOINT` | Optional | Collector/agent endpoint URL | Type-specific defaults |
| `ARAGORA_SERVICE_NAME` | Optional | Service name for traces | `aragora` |
| `ARAGORA_SERVICE_VERSION` | Optional | Service version string | `1.0.0` |
| `ARAGORA_ENVIRONMENT` | Optional | Deployment environment | `development` |
| `ARAGORA_TRACE_SAMPLE_RATE` | Optional | Sampling rate 0.0-1.0 (1.0 = 100%) | `1.0` |
| `ARAGORA_OTLP_HEADERS` | Optional | JSON-encoded headers for authenticated endpoints | - |
| `ARAGORA_OTLP_BATCH_SIZE` | Optional | Batch processor queue size | `512` |
| `ARAGORA_OTLP_EXPORT_TIMEOUT_MS` | Optional | Export timeout in milliseconds | `30000` |
| `ARAGORA_OTLP_INSECURE` | Optional | Allow insecure (non-TLS) connections | `false` |
| `DATADOG_API_KEY` | Optional | Datadog API key (for datadog exporter) | - |

**Default Endpoints by Exporter Type:**
- `jaeger`: `localhost` (uses Jaeger agent UDP port 6831)
- `zipkin`: `http://localhost:9411/api/v2/spans`
- `otlp_grpc`: `http://localhost:4317`
- `otlp_http`: `http://localhost:4318/v1/traces`
- `datadog`: `http://localhost:4317` (Datadog Agent OTLP receiver)

**Example Configurations:**

```bash
# Jaeger (local development)
ARAGORA_OTLP_EXPORTER=jaeger
ARAGORA_OTLP_ENDPOINT=localhost

# Zipkin
ARAGORA_OTLP_EXPORTER=zipkin
ARAGORA_OTLP_ENDPOINT=http://zipkin.example.com:9411/api/v2/spans

# OTLP gRPC (standard OpenTelemetry collector)
ARAGORA_OTLP_EXPORTER=otlp_grpc
ARAGORA_OTLP_ENDPOINT=http://otel-collector.example.com:4317

# OTLP HTTP
ARAGORA_OTLP_EXPORTER=otlp_http
ARAGORA_OTLP_ENDPOINT=http://otel-collector.example.com:4318/v1/traces

# Datadog (via Datadog Agent)
ARAGORA_OTLP_EXPORTER=datadog
ARAGORA_OTLP_ENDPOINT=http://localhost:4317
DATADOG_API_KEY=your-datadog-api-key

# Production with authentication
ARAGORA_OTLP_EXPORTER=otlp_grpc
ARAGORA_OTLP_ENDPOINT=https://otel.example.com:443
ARAGORA_OTLP_HEADERS='{"Authorization": "Bearer your-token"}'
ARAGORA_TRACE_SAMPLE_RATE=0.1  # 10% sampling for high traffic
```

**Required Packages:**
- Jaeger: `pip install opentelemetry-exporter-jaeger`
- Zipkin: `pip install opentelemetry-exporter-zipkin`
- OTLP gRPC: `pip install opentelemetry-exporter-otlp-proto-grpc`
- OTLP HTTP: `pip install opentelemetry-exporter-otlp-proto-http`

## Telemetry Configuration

Controls observation levels for debug and production modes.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_TELEMETRY_LEVEL` | Optional | Telemetry level (SILENT/DIAGNOSTIC/CONTROLLED/SPECTACLE) | `CONTROLLED` |

Levels:
- `SILENT` (0): No telemetry broadcast
- `DIAGNOSTIC` (1): Internal diagnostics only
- `CONTROLLED` (2): Redacted telemetry (default, secrets filtered)
- `SPECTACLE` (3): Full transparency (development only)

## Belief Network Settings

For belief propagation analysis during debates.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_BELIEF_MAX_ITERATIONS` | Optional | Max iterations for belief convergence | `100` |
| `ARAGORA_BELIEF_CONVERGENCE_THRESHOLD` | Optional | Convergence epsilon | `0.001` |

## Queue Settings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_USER_EVENT_QUEUE_SIZE` | Optional | User event queue buffer size | `100` |

## Broadcast (Audio/Podcast)

Configuration for debate-to-podcast conversion.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_AUDIO_DIR` | Optional | Audio storage directory | `.nomic/audio/` |
| `ARAGORA_TTS_TIMEOUT` | Optional | TTS generation timeout (seconds) | `60` |
| `ARAGORA_TTS_RETRIES` | Optional | TTS retry attempts | `3` |

See [BROADCAST.md](../guides/broadcast) for the complete audio pipeline documentation.

## Transcription (Speech-to-Text)

Configuration for audio/video transcription using Whisper backends.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_WHISPER_BACKEND` | Optional | Transcription backend: `openai`, `faster-whisper`, `whisper-cpp`, `auto` | `auto` |
| `ARAGORA_WHISPER_MODEL` | Optional | Whisper model size: `tiny`, `base`, `small`, `medium`, `large` | `base` |
| `ARAGORA_TRANSCRIPTION_TIMEOUT` | Optional | Transcription timeout (seconds) | `300` |
| `ARAGORA_MAX_AUDIO_DURATION` | Optional | Max audio duration for transcription (seconds) | `3600` |
| `ARAGORA_MAX_AUDIO_SIZE_MB` | Optional | Max audio file size (MB) | `25` |

**Backend Selection:**
- `openai` - Uses OpenAI Whisper API (requires `OPENAI_API_KEY`)
- `faster-whisper` - Local CTranslate2-based transcription (requires `pip install faster-whisper`)
- `whisper-cpp` - Local whisper.cpp binary (requires `whisper` in PATH)
- `auto` - Tries OpenAI first, falls back to local backends

**Usage:**
```bash
# Use OpenAI Whisper API (fastest, requires API key)
ARAGORA_WHISPER_BACKEND=openai

# Use local faster-whisper (GPU-accelerated)
ARAGORA_WHISPER_BACKEND=faster-whisper
ARAGORA_WHISPER_MODEL=medium

# Use whisper.cpp (CPU-optimized)
ARAGORA_WHISPER_BACKEND=whisper-cpp
```

## Accounting & Payroll Integrations

Configuration for accounting and payroll connectors (enable only if used).

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `QBO_CLIENT_ID` | Optional | QuickBooks OAuth client ID | - |
| `QBO_CLIENT_SECRET` | Optional | QuickBooks OAuth client secret | - |
| `QBO_REDIRECT_URI` | Optional | QuickBooks OAuth callback URL | - |
| `QBO_ENVIRONMENT` | Optional | QuickBooks environment (`sandbox`, `production`) | `sandbox` |
| `PLAID_CLIENT_ID` | Optional | Plaid client ID | - |
| `PLAID_SECRET` | Optional | Plaid secret key | - |
| `PLAID_ENVIRONMENT` | Optional | Plaid environment (`sandbox`, `development`, `production`) | `sandbox` |
| `GUSTO_CLIENT_ID` | Optional | Gusto OAuth client ID | - |
| `GUSTO_CLIENT_SECRET` | Optional | Gusto OAuth client secret | - |
| `GUSTO_REDIRECT_URI` | Optional | Gusto OAuth callback URL | - |

## Bot Integrations

Configuration for chat platform bots (Discord, Teams, Zoom, Slack).

### Discord Bot

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `DISCORD_BOT_TOKEN` | Required | Discord bot authentication token | - |
| `DISCORD_APPLICATION_ID` | Required | Discord application ID for slash commands | - |
| `DISCORD_PUBLIC_KEY` | Required | Public key for interaction verification | - |

**Setup:**
1. Create application at [Discord Developer Portal](https://discord.com/developers/applications)
2. Enable "Bot" and copy the token
3. Enable "Slash Commands" and note the Application ID
4. Copy the Public Key from "General Information"
5. Set Interactions Endpoint URL to `https://your-api.com/api/bots/discord/interactions`

### Microsoft Teams Bot

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `TEAMS_APP_ID` | Required | Azure Bot registration App ID | - |
| `TEAMS_APP_PASSWORD` | Required | Azure Bot registration password | - |

**Setup:**
1. Register a bot at [Azure Bot Service](https://portal.azure.com/#create/Microsoft.BotServiceConnectivityGalleryPackage)
2. Enable Teams channel in "Channels" settings
3. Create an app manifest for Teams deployment
4. Set Messaging Endpoint to `https://your-api.com/api/bots/teams/messages`

### Zoom Bot

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ZOOM_CLIENT_ID` | Required | Zoom app OAuth client ID | - |
| `ZOOM_CLIENT_SECRET` | Required | Zoom app OAuth client secret | - |
| `ZOOM_BOT_JID` | Required | Bot's JID for chat messages | - |
| `ZOOM_SECRET_TOKEN` | Required | Webhook signature verification token | - |
| `ZOOM_VERIFICATION_TOKEN` | Optional | Legacy verification token | - |

**Setup:**
1. Create an app at [Zoom Marketplace](https://marketplace.zoom.us/develop/create)
2. Choose "Chatbot" app type
3. Configure OAuth scopes for chat messaging
4. Set Event Subscription URL to `https://your-api.com/api/bots/zoom/events`

### Slack (Enhanced)

Slack integration uses the existing `SLACK_*` variables with additional bidirectional features.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `SLACK_CLIENT_ID` | Required | OAuth app client ID | - |
| `SLACK_CLIENT_SECRET` | Required | OAuth app client secret | - |
| `SLACK_SIGNING_SECRET` | Required | Request signing secret (webhook verification) | - |
| `SLACK_REDIRECT_URI` | **Required in Production** | OAuth callback URL (enforced when `ARAGORA_ENV=production`) | Auto-construct in dev |
| `SLACK_BOT_TOKEN` | Optional | Bot token for direct API calls (xoxb-...) | - |
| `SLACK_APP_TOKEN` | Optional | App-level token for Socket Mode (xapp-...) | - |
| `SLACK_SCOPES` | Optional | OAuth scopes (comma-separated) | See default scopes |
| `ARAGORA_API_BASE_URL` | **Required in Production** | Base URL for internal API calls | `http://localhost:8080` |
| `ARAGORA_ENCRYPTION_KEY` | **Required in Production** | Encryption key for token storage | - |
| `ARAGORA_ENV` | Optional | Environment mode (`production` enforces requirements) | `development` |

**Production Requirements:**
- `SLACK_REDIRECT_URI` must be set when `ARAGORA_ENV=production` (prevents open redirect attacks)
- `ARAGORA_API_BASE_URL` should point to your production API endpoint
- `ARAGORA_ENCRYPTION_KEY` required for secure token storage (PBKDF2-HMAC with 480k iterations)

**Additional Commands:**
- `/aragora debate "topic"` - Start a multi-agent debate
- `/aragora gauntlet` - Run stress-test validation (with file attachment)
- `/aragora status` - Check system health
- `/aragora help` - List available commands

See [BOT_INTEGRATIONS.md](../guides/bot-integrations) for detailed setup guides.

## Debug & Logging

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_DEBUG` | Optional | Enable debug logging | `false` |
| `ARAGORA_LOG_LEVEL` | Optional | Log level (DEBUG/INFO/WARN/ERROR) | `INFO` |
| `ARAGORA_LOG_FILE` | Optional | Log file path | - (stdout only) |
| `ARAGORA_LOG_FORMAT` | Optional | Log format (`json`, `text`) | `text` |
| `ARAGORA_LOG_TIMESTAMP` | Optional | Include timestamps in logs | `true` |
| `ARAGORA_LOG_MAX_BYTES` | Optional | Max log file size before rotation | `10485760` (10MB) |
| `ARAGORA_LOG_BACKUP_COUNT` | Optional | Number of rotated log files to keep | `5` |
| `ARAGORA_DEV_MODE` | Optional | Enable development mode features | `false` |

## Security & Encryption

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ENCRYPTION_KEY` | Optional | Encryption key for sensitive data at rest | - |
| `ARAGORA_ENCRYPTION_REQUIRED` | Optional | Fail if encryption unavailable | `false` (auto `true` in production) |
| `ARAGORA_AUDIT_SIGNING_KEY` | Optional | Key for signing audit log entries | - |
| `ARAGORA_METRICS_TOKEN` | Optional | Auth token for metrics endpoint | - |
| `ARAGORA_SECRET_NAME` | Optional | AWS Secrets Manager secret name | - |
| `ARAGORA_USE_SECRETS_MANAGER` | Optional | Enable AWS Secrets Manager loading | `false` locally, auto in prod/staging/AWS runtimes |
| `ARAGORA_SECRETS_STRICT` | Optional | Block critical-secret env fallback | `false` locally, auto in prod/staging |
| `ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS` | Optional | Allow unverified webhooks (dev only) | `false` |

**Security Notes:**
- `ARAGORA_ENCRYPTION_REQUIRED` is automatically enabled when `ARAGORA_ENV=production`
- `ARAGORA_ALLOW_UNVERIFIED_WEBHOOKS` should **never** be set in production - webhooks will fail-closed if verification is unavailable
- Webhook verification requires: Slack (signing secret), Discord (PyNaCl + public key), Teams/Google Chat (PyJWT)
- Secrets Manager is auto-enabled in production/staging or AWS-managed runtimes.
  For local development, set `ARAGORA_USE_SECRETS_MANAGER=true` to opt in.
  `ARAGORA_SECRET_NAME` still falls back to `aragora/production` when Secrets Manager is enabled.
- Use `python3 -m aragora.cli.main secrets health --json` to verify source status without printing secret values.

### ODR Receipt Signing

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ODR_SIGNING_KEY_FILE` | Optional | Path to a PKCS#8 Ed25519 private-key PEM; empty means unset; unusable files fail closed. POSIX group/other-writable files are rejected; readable files warn. | - |
| `ARAGORA_ODR_SIGNING_KEY_SECRET` | Optional | AWS Secrets Manager SecretId holding the signing PEM; used when no key file is configured. An explicit loader secret-name argument overrides the file. | `aragora/odr-signing-key` |
| `ARAGORA_ODR_SIGNING_KEY_STRICT_MODE` | Optional | Reject POSIX group/other-readable key files instead of warning when true (`true`, `1`, `yes`, `on`, case-insensitive). | `false` |

## Knowledge System

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_KNOWLEDGE_AUTO_PROCESS` | Optional | Auto-process new knowledge entries | `true` |
| `ARAGORA_QUERY_CACHE_ENABLED` | Optional | Enable request-scoped knowledge query cache | `true` |
| `ARAGORA_QUERY_CACHE_MAX_SIZE` | Optional | Max entries per request-scoped cache | `1000` |

## Evolution & Prompt Settings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_ALLOW_AUTO_EVOLVE` | Optional | Allow automatic prompt evolution | `false` |
| `ARAGORA_ALLOW_PROMPT_EVOLVE` | Optional | Allow prompt modification during debates | `false` |
| `ARAGORA_HYBRID_IMPLEMENT` | Optional | Enable hybrid implementation mode | `false` |
| `ARAGORA_SKIP_GATES` | Optional | Skip safety gates (dev only) | `false` |

## Cache Settings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_CACHE_MAX_ENTRIES` | Optional | Max entries in LRU caches | `1000` |
| `ARAGORA_CACHE_EVICT_PERCENT` | Optional | Percentage to evict when cache full | `10` |

## Observability & Performance

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_N1_DETECTION` | Optional | N+1 query detection mode: `off`, `warn`, `error` | `off` |
| `ARAGORA_N1_THRESHOLD` | Optional | N+1 query threshold per table | `5` |

## CLI & Process Settings

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_MAX_CLI_SUBPROCESSES` | Optional | Max concurrent CLI agent subprocesses | `4` |
| `ARAGORA_BIND_HOST` | Optional | Host to bind server to | `0.0.0.0` |
| `ARAGORA_ORG_ID` | Optional | Default organization ID | - |
| `ARAGORA_SCOPE_CHECK` | Optional | Enable scope validation | `true` |

## Testing & CI

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_BASELINE_PARALLEL` | Optional | Parallel workers for baseline runner | `auto` |
| `ARAGORA_BASELINE_TIMEOUT` | Optional | Timeout seconds for baseline runner | `60` |
| `ARAGORA_TEST_REAL_AUTH` | Optional | Enable real auth checks in tests | - |

## Legacy Database Aliases

These variables are legacy aliases maintained for backwards compatibility:

| Variable | Alias For | Description |
|----------|-----------|-------------|
| `ARAGORA_SQL_CONNECTION` | `DATABASE_URL` | Legacy SQL connection string |
| `ARAGORA_POSTGRES_DSN` | `DATABASE_URL` | Legacy Postgres DSN |
| `ARAGORA_REQUIRE_DISTRIBUTED_STATE` | `ARAGORA_REQUIRE_DISTRIBUTED` | Deprecated distributed-state flag |

## Validation Rules

### API Keys
- Must be non-empty strings
- Validated on first API call
- Keys are not logged (security)

### Ports
- Must be integers 1-65535
- HTTP API: 8080 (default)
- WebSocket: 8765 (default, `/` or `/ws`)
- Single-port option: use `AiohttpUnifiedServer` (advanced)

### URLs
- Must be valid HTTPS URLs (for production)
- HTTP allowed for localhost development

## Example .env File

```bash
# Required: At least one AI provider
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx

# Optional: Additional providers
GEMINI_API_KEY=AIzaSy...
XAI_API_KEY=xai-xxx
MISTRAL_API_KEY=xxx
OPENROUTER_API_KEY=sk-or-xxx
DEEPSEEK_API_KEY=sk-xxx

# Optional: Local models
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=llama2

# Optional: Persistence
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...

# Optional: Client defaults / auth
ARAGORA_API_URL=http://localhost:8080
ARAGORA_API_TOKEN=my-secret-token

# Optional: JWT Authentication
ARAGORA_JWT_SECRET=your-secure-secret-key
ARAGORA_JWT_EXPIRY_HOURS=24

# Optional: Stripe Billing
STRIPE_SECRET_KEY=sk_test_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_PRICE_STARTER=price_xxx
STRIPE_PRICE_PROFESSIONAL=price_xxx
STRIPE_PRICE_ENTERPRISE=price_xxx

# Optional: Redis (rate limiting, queues, oauth state)
ARAGORA_REDIS_URL=redis://localhost:6379/0
REDIS_URL=redis://localhost:6379

# Optional: Webhooks
ARAGORA_WEBHOOKS_CONFIG=/etc/aragora/webhooks.json

# Optional: Social Media (Pulse module)
TWITTER_BEARER_TOKEN=AAAA...  # For trending topics
```

## Troubleshooting

### "No API key found"
- Set at least one of: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
- Verify `.env` file is in project root

### "CORS blocked"
- Add your domain to `ARAGORA_ALLOWED_ORIGINS`
- Check for typos in origin URLs

### "WebSocket connection failed"
- Verify `--ws-port` (server) matches `NEXT_PUBLIC_WS_URL` (frontend) or your client URL
- Check firewall/proxy settings

### "Rate limit exceeded"
- Increase `ARAGORA_RATE_LIMIT` / `ARAGORA_IP_RATE_LIMIT`
- Or wait for rate limit window to reset

---

## SSL/TLS Configuration

Enable HTTPS for production deployments.

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `ARAGORA_SSL_ENABLED` | Optional | Enable SSL/TLS | `false` |
| `ARAGORA_SSL_CERT` | If SSL enabled | Path to SSL certificate file | - |
| `ARAGORA_SSL_KEY` | If SSL enabled | Path to SSL private key file | - |

Example:
```bash
ARAGORA_SSL_ENABLED=true
ARAGORA_SSL_CERT=/etc/ssl/certs/aragora.pem
ARAGORA_SSL_KEY=/etc/ssl/private/aragora-key.pem
```

### Self-signed certificate for development
```bash
# Generate a self-signed certificate
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

# Use with Aragora
ARAGORA_SSL_ENABLED=true
ARAGORA_SSL_CERT=cert.pem
ARAGORA_SSL_KEY=key.pem
```

---

## Deployment Tuning Guides

### High-Load Deployments

For production systems handling many concurrent debates:

```bash
# Rate limiting - increase for high-traffic APIs
ARAGORA_RATE_LIMIT=200          # 200 req/min per token
ARAGORA_IP_RATE_LIMIT=500       # 500 req/min per IP

# Debate limits
ARAGORA_MAX_AGENTS_PER_DEBATE=8 # Limit agents per debate
ARAGORA_MAX_CONCURRENT_DEBATES=50  # Allow more parallel debates

# WebSocket settings
ARAGORA_WS_MAX_MESSAGE_SIZE=131072  # 128KB for large messages
ARAGORA_WS_HEARTBEAT=15            # More frequent heartbeats

# Database timeouts
ARAGORA_DB_TIMEOUT=60.0            # Longer timeout for complex queries

# Cache TTLs - shorter for freshness
ARAGORA_CACHE_LEADERBOARD=60       # 1 minute leaderboard cache
ARAGORA_CACHE_AGENT_PROFILE=120    # 2 minute profile cache
```

### Development Mode

For local development with faster iteration:

```bash
# Debug output
ARAGORA_DEBUG=true
ARAGORA_LOG_LEVEL=DEBUG

# Disable SSL for localhost
ARAGORA_SSL_ENABLED=false

# Lower timeouts for faster feedback
ARAGORA_DEBATE_TIMEOUT=120         # 2 minute debate timeout
ARAGORA_DB_TIMEOUT=10.0            # Quick database timeout

# Generous rate limits
ARAGORA_RATE_LIMIT=1000
ARAGORA_IP_RATE_LIMIT=1000

# Full telemetry for debugging
ARAGORA_TELEMETRY_LEVEL=SPECTACLE
```

### Testing Configuration

For running test suites:

```bash
# Use in-memory or test databases
ARAGORA_DB_ELO=:memory:
ARAGORA_DB_MEMORY=:memory:

# Short timeouts for fast tests
ARAGORA_DB_TIMEOUT=5.0
ARAGORA_DEBATE_TIMEOUT=30

# Disable external services
# (Don't set API keys to skip external API tests)

# Disable SSL
ARAGORA_SSL_ENABLED=false

# Silent telemetry
ARAGORA_TELEMETRY_LEVEL=SILENT
```

---

## Configuration Validation

Aragora validates configuration at startup. Check configuration with:

```python
from aragora.config import validate_configuration

# Non-strict: logs warnings, returns validation result
result = validate_configuration(strict=False)
print(result["valid"])       # True if no errors
print(result["warnings"])    # List of warnings
print(result["config_summary"])  # Current config values

# Strict: raises ConfigurationError on errors
from aragora.config import validate_configuration, ConfigurationError
try:
    validate_configuration(strict=True)
except ConfigurationError as e:
    print(f"Config error: {e}")
```

### Validation Checks

- **Rate limits**: Must be positive integers
- **Timeouts**: Must be positive numbers
- **SSL paths**: Must exist if SSL enabled
- **API keys**: Warning if none configured (error in strict mode)
