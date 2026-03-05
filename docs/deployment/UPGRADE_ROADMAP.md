# Upgrade Roadmap

This document provides version support timelines, recommended upgrade paths, rollback procedures, and a summary of breaking changes across Aragora releases.

For detailed migration instructions, see:
- [MIGRATION_V1_TO_V2.md](../status/MIGRATION_V1_TO_V2.md) - API v1 to v2 migration
- [BREAKING_CHANGES.md](../reference/BREAKING_CHANGES.md) - All breaking changes
- [DEPRECATION_POLICY.md](../reference/DEPRECATION_POLICY.md) - Deprecation timeline and process
- [POSTGRESQL_MIGRATION.md](../status/POSTGRESQL_MIGRATION.md) - SQLite to PostgreSQL migration
- [MIGRATIONS.md](../status/MIGRATIONS.md) - Database migration system

---

## Table of Contents

1. [Version Support Timeline](#version-support-timeline)
2. [Current Version](#current-version)
3. [Upgrade Paths](#upgrade-paths)
4. [Pre-Upgrade Checklist](#pre-upgrade-checklist)
5. [Rollback Procedures](#rollback-procedures)
6. [Breaking Change Summary](#breaking-change-summary)
7. [Dependency Requirements](#dependency-requirements)
8. [Database Migration Guide](#database-migration-guide)
9. [Configuration Changes](#configuration-changes)

---

## Version Support Timeline

| Version | Release | End of Support | Status |
|---------|---------|----------------|--------|
| **v2.8.x** | 2026-02-25 | Active | **Current** |
| v2.7.x | 2026-02-15 | Active | Supported |
| v2.6.x | 2026-02-03 | Active | Supported |
| v2.5.x | 2026-02-01 | Active | Supported |
| v2.0.x–v2.4.x | 2026-01-13–01-25 | Active | Supported |
| v1.0.x | 2026-01-13 | 2026-06-01 | Deprecated |
| v0.8.x | Pre-1.0 | 2026-03-01 | End of life |

**Support policy:**
- **Current:** Receives all updates (features, fixes, security)
- **Supported:** Receives security fixes and critical bug fixes
- **Deprecated:** Receives security fixes only; upgrade recommended
- **End of life:** No updates; upgrade required

---

## Current Version

**Aragora v2.8.0** (released 2026-02-25)

```python
# Check your version
from aragora.__version__ import __version__
print(__version__)  # "2.8.0"
```

**Python support:** 3.10, 3.11, 3.12, 3.13

---

## Upgrade Paths

### v2.x.x -> v2.6.3 (Minor Upgrade)

No breaking changes between v2.x releases. Standard upgrade:

```bash
pip install --upgrade aragora==2.6.3
```

Run database migrations if any are pending:

```bash
python -m aragora.migrations.runner migrate
```

### v1.0.x -> v2.6.3 (Major Upgrade)

This upgrade requires API and SDK migration. Follow these steps in order:

**Step 1: Update dependencies**
```bash
pip install --upgrade aragora==2.6.3
```

**Step 2: Run database migrations**
```bash
python -m aragora.migrations.runner migrate
```

**Step 3: Update API endpoints**

All endpoints move from `/api/v1/` to `/api/v2/` with plural resource names:

| v1 Endpoint | v2 Endpoint |
|-------------|-------------|
| `POST /api/v1/debate` | `POST /api/v2/debates` |
| `GET /api/v1/debate/{id}` | `GET /api/v2/debates/{id}` |
| `GET /api/v1/agents` | `GET /api/v2/agents` |
| `GET /api/v1/health` | `GET /api/v2/system/health` |

**Step 4: Update request/response format**

```python
# v1
response = client.post("/api/v1/debate", {"topic": "Design a cache", "max_rounds": 3})
debates = response["debates"]

# v2
response = client.post("/api/v2/debates", {"task": "Design a cache", "rounds": 3})
debates = response["data"]["debates"]
```

**Step 5: Update SDK usage**

```python
# v1
client = AragoraClient(base_url="https://api.aragora.io")
debates = client.getDebates()

# v2
client = AragoraClient(base_url="https://api.aragora.io", api_version="v2")
debates = client.debates.list()
```

**Step 6: Update module imports**

```python
# Deprecated (removed in v2.3.0)
from aragora.modes.gauntlet import GauntletOrchestrator
from aragora.crawlers import RepositoryCrawler

# Current
from aragora.gauntlet import GauntletOrchestrator
from aragora.connectors.repository_crawler import RepositoryCrawler
```

**Step 7: Update environment variables**

```bash
# Deprecated
ARAGORA_REQUIRE_DISTRIBUTED_STATE=true

# Current
ARAGORA_REQUIRE_DISTRIBUTED=true
```

See [MIGRATION_V1_TO_V2.md](../status/MIGRATION_V1_TO_V2.md) for the complete migration guide.

### v0.8.x -> v2.6.3 (Legacy Upgrade)

Upgrade to v1.0.0 first, then follow the v1 -> v2 path:

```bash
# Step 1: Upgrade to v1.0.0
pip install aragora==1.0.0
python -m aragora.migrations.runner migrate

# Step 2: Verify v1 works
pytest tests/ -v --timeout=60

# Step 3: Upgrade to v2.6.3
pip install aragora==2.6.3
python -m aragora.migrations.runner migrate
```

See `deprecated/migrations/MIGRATION_0.8_to_1.0.md` for v0.8 -> v1.0 details.

### SQLite -> PostgreSQL Migration

For production deployments migrating from SQLite to PostgreSQL:

```bash
# Install PostgreSQL dependencies
pip install aragora[postgres]

# Set connection string
export DATABASE_URL="postgresql://user:pass@host:5432/aragora"
# Or: export ARAGORA_POSTGRES_DSN="postgresql://..."

# Run data migration
python -m aragora.persistence.migrations.postgres.memory_migrator

# Run schema migrations
python -m aragora.migrations.runner migrate
```

See [POSTGRESQL_MIGRATION.md](../status/POSTGRESQL_MIGRATION.md) for details including connection pooling and Supabase setup.

---

## Pre-Upgrade Checklist

Run through this checklist before any upgrade:

### 1. Backup

```bash
# Create a full backup
python -m aragora.backup.manager create --label "pre-upgrade-v2.6.3"

# Verify the backup
python -m aragora.backup.manager verify --latest
```

### 2. Check Compatibility

```bash
# Verify Python version (requires >=3.10)
python --version

# Check current version
python -c "from aragora.__version__ import __version__; print(__version__)"

# Check for deprecated usage in your code
grep -r "from aragora.modes.gauntlet" .
grep -r "from aragora.crawlers" .
grep -r "ARAGORA_REQUIRE_DISTRIBUTED_STATE" .
```

### 3. Review Breaking Changes

Check [BREAKING_CHANGES.md](../reference/BREAKING_CHANGES.md) for any changes between your current version and the target version.

### 4. Test in Staging

```bash
# Run the full test suite
pytest tests/ -v

# Run migration in dry-run mode
python -m aragora.migrations.runner migrate --dry-run
```

### 5. Check API Version Headers

If upgrading from v1, your clients should handle deprecation headers:

```http
Deprecation: @1735689600
Sunset: 2026-06-01
Link: </api/v2/debates>; rel="successor-version"
X-Deprecation-Level: warning
```

---

## Rollback Procedures

### Minor Version Rollback (v2.x -> v2.y)

```bash
# 1. Stop the server
systemctl stop aragora  # or equivalent

# 2. Downgrade the package
pip install aragora==2.4.0  # previous version

# 3. Rollback migrations if needed
python -m aragora.migrations.runner rollback --to <migration_id>

# 4. Restart
systemctl start aragora
```

### Major Version Rollback (v2 -> v1)

Major version rollbacks require restoring from backup:

```bash
# 1. Stop the server
systemctl stop aragora

# 2. Restore from backup
python -m aragora.backup.manager restore --label "pre-upgrade-v2.6.3"

# 3. Downgrade the package
pip install aragora==1.0.0

# 4. Restart
systemctl start aragora
```

### Kubernetes Rollback

```bash
# Rollback deployment
kubectl rollout undo deployment/aragora -n aragora

# Verify rollback
kubectl rollout status deployment/aragora -n aragora

# Run migration rollback job if needed
kubectl apply -f deploy/kubernetes/migration-job.yaml
```

### Database Migration Rollback

The migration system uses advisory locking and checksum verification:

```bash
# List applied migrations
python -m aragora.migrations.runner status

# Rollback last migration
python -m aragora.migrations.runner rollback

# Rollback to specific migration
python -m aragora.migrations.runner rollback --to v20260119000000
```

Migration safety features:
- Advisory locking prevents concurrent migrations
- Checksum verification detects tampered migration files
- Each migration has a corresponding rollback function

---

## Breaking Change Summary

### v2.0.0 Breaking Changes

| Area | Change | Action Required |
|------|--------|-----------------|
| **API responses** | Wrapped with `data` and `meta` objects | Update response parsing |
| **Endpoint naming** | Plural resource names | Update URL paths |
| **Request fields** | `topic` -> `task`, `max_rounds` -> `rounds` | Update request bodies |
| **Authentication** | OAuth 2.0 required for org endpoints | Implement OAuth flow |
| **Error format** | Structured error codes | Update error handling |
| **SDK methods** | `client.getDebates()` -> `client.debates.list()` | Update SDK calls |

### v1.0.0 Breaking Changes (from pre-1.0)

| Area | Change | Action Required |
|------|--------|-----------------|
| **API versioning** | `/api/` deprecated | Use `/api/v2/` prefix |
| **Agent names** | Canonical names required | Use `anthropic-api`, `openai-api` |
| **Rate limiting** | Enabled by default | Configure `ARAGORA_RATE_LIMIT_*` |
| **Redis** | Required for multi-replica | Configure Redis for distributed |

### Upcoming: v2.3.0 Removals

| Item | Type | Replacement |
|------|------|-------------|
| `aragora.modes.gauntlet` | Module | `aragora.gauntlet` |
| `aragora.crawlers` | Module | `aragora.connectors.repository_crawler` |
| `ARAGORA_REQUIRE_DISTRIBUTED_STATE` | Config | `ARAGORA_REQUIRE_DISTRIBUTED` |

### Upcoming: June 1, 2026

| Item | Action |
|------|--------|
| All API v1 endpoints | Removed; returns `410 Gone` |
| `/api/v1/debates` | Use `/api/v2/debates` |
| `/api/v1/agents` | Use `/api/v2/agents` |
| `/api/v1/health` | Use `/api/v2/system/health` |

---

## Dependency Requirements

### Core Dependencies

| Package | Required Version | Notes |
|---------|-----------------|-------|
| Python | >=3.10 | 3.10, 3.11, 3.12, 3.13 supported |
| fastapi | >=0.109.0,<1.0 | HTTP framework |
| uvicorn | >=0.27.0,<1.0 | ASGI server |
| pydantic | >=2.0,<3.0 | Data validation |
| cryptography | >=46.0,<48.0 | AES-256-GCM encryption |

### Optional Dependency Groups

Install specific extras based on your deployment:

```bash
# PostgreSQL support
pip install aragora[postgres]
# Adds: sqlalchemy>=2.0.40, asyncpg>=0.29.0, alembic>=1.13.0

# Full persistence (includes Supabase)
pip install aragora[persistence]

# Observability (metrics, tracing)
pip install aragora[observability]
# Adds: opentelemetry, prometheus-client

# Development/testing
pip install aragora[test]

# All optional dependencies
pip install aragora[all]
```

### Infrastructure Requirements

| Component | Development | Production |
|-----------|-------------|------------|
| Database | SQLite (default) | PostgreSQL 13+ |
| Cache | In-memory | Redis 6+ |
| Python | 3.10+ | 3.11+ recommended |
| Memory | 512MB | 2GB+ |

---

## Database Migration Guide

### Migration System Overview

Aragora uses a lightweight migration system with dual-tier execution (PostgreSQL and SQLite):

```bash
# Check migration status
python -m aragora.migrations.runner status

# Run pending migrations
python -m aragora.migrations.runner migrate

# Dry run (preview without executing)
python -m aragora.migrations.runner migrate --dry-run

# Rollback last migration
python -m aragora.migrations.runner rollback
```

### Auto-Migration on Startup

Enable automatic migrations when the server starts:

```bash
export ARAGORA_AUTO_MIGRATE_ON_STARTUP=true
```

This is convenient for development but not recommended for production. In production, run migrations explicitly before deploying new code.

### Zero-Downtime Migrations

The migration system supports zero-downtime patterns (`aragora/migrations/patterns.py`):

1. **Additive migrations:** Add new columns/tables without modifying existing ones
2. **Backfill migrations:** Populate new columns from existing data
3. **Cleanup migrations:** Remove deprecated columns after grace period

### Key Migrations by Version

| Migration | Version | Description |
|-----------|---------|-------------|
| `v20260113000000_consolidate_databases` | v1.0.0 | Database consolidation |
| `v20260119000000_knowledge_mound_visibility` | v2.0.3 | Knowledge mound visibility flags |
| `v20260120000000_channel_governance_stores` | v2.0.6 | Channel governance tables |
| `v20260120100000_marketplace_webhooks_batch` | v2.0.6 | Marketplace webhook support |

---

## Configuration Changes

### New in v2.x

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_DB_BACKEND` | `sqlite` | Database backend (`sqlite` or `postgres`) |
| `DATABASE_URL` | - | PostgreSQL connection string |
| `ARAGORA_AUTO_MIGRATE_ON_STARTUP` | `false` | Auto-run migrations on startup |
| `ARAGORA_RATE_LIMIT_REQUESTS` | `100` | Rate limit per window |
| `ARAGORA_RATE_LIMIT_WINDOW` | `60` | Rate limit window (seconds) |
| `OAUTH_STATE_TTL_SECONDS` | `600` | OAuth state TTL |
| `ARAGORA_ENABLE_MFA` | `false` | Enable multi-factor auth |

### Deprecated

| Variable | Replacement | Removal Version |
|----------|-------------|-----------------|
| `ARAGORA_REQUIRE_DISTRIBUTED_STATE` | `ARAGORA_REQUIRE_DISTRIBUTED` | v2.3.0 |

### Required (at least one)

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic API key (Claude) |
| `OPENAI_API_KEY` | OpenAI API key (GPT) |

See [ENVIRONMENT.md](../reference/ENVIRONMENT.md) for the full environment variable reference.

---

## Related Documentation

- [BREAKING_CHANGES.md](../reference/BREAKING_CHANGES.md) - Detailed breaking changes per version
- [DEPRECATION_POLICY.md](../reference/DEPRECATION_POLICY.md) - Deprecation process and timeline
- [MIGRATION_V1_TO_V2.md](../status/MIGRATION_V1_TO_V2.md) - Complete API v1 to v2 migration guide
- [POSTGRESQL_MIGRATION.md](../status/POSTGRESQL_MIGRATION.md) - SQLite to PostgreSQL migration
- [MIGRATIONS.md](../status/MIGRATIONS.md) - Database migration system details
- [API_VERSIONING.md](../api/API_VERSIONING.md) - API version selection and deprecation headers
- [ENVIRONMENT.md](../reference/ENVIRONMENT.md) - Environment variable reference

---

*Last updated: 2026-02-01*
