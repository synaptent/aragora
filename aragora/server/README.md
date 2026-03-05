# Server Module

Unified HTTP and WebSocket server for Aragora's API and real-time streaming.

## Overview

The server module provides a modular handler architecture with 122+ endpoint handlers, 32+ middleware components, and WebSocket streaming for real-time debate events. It supports bidirectional chat routing, enterprise authentication, and multi-tenant isolation.

## Quick Start

### Full API + WebSocket Surface (Recommended)

```bash
aragora serve --api-port 8080 --ws-port 8765
```

### FastAPI Subset (Partial API Surface)

```bash
uvicorn aragora.server.app:app --host 0.0.0.0 --port 8081
```

`aragora serve` runs the full handler-registry API plus WebSocket stream server. `aragora.server.app:app` is a partial FastAPI surface used for incremental migration and targeted integrations.

### API Example

```python
import httpx

async with httpx.AsyncClient() as client:
    # Start a debate
    response = await client.post(
        "http://localhost:8080/api/v1/debates",
        json={"task": "Design a rate limiter", "rounds": 5},
        headers={"Authorization": f"Bearer {token}"}
    )
    debate = response.json()

    # Check debate status
    status = await client.get(f"/api/v1/debates/{debate['id']}/status")
```

## Key Files

| File | Purpose |
|------|---------|
| `unified_server.py` | Main server entry point |
| `startup/` | Server initialization sequence |
| `debate_origin/` | Bidirectional chat result routing |
| `handlers/` | 122+ modular endpoint handlers |
| `middleware/` | 32+ composable middleware |
| `stream/` | WebSocket event streaming |
| `handler_registry/` | Centralized route management |

## Architecture

### Unified Server

The `UnifiedHandler` class combines multiple mixins:

- `ResponseHelpersMixin` - JSON responses, CORS, security headers
- `HandlerRegistryMixin` - Modular handler routing
- `AuthChecksMixin` - Rate limiting, RBAC permission checks
- `RequestUtilsMixin` - Parameter parsing, content validation
- `RequestLoggingMixin` - Request/response logging
- `DebateControllerMixin` - Debate lifecycle management

### Startup Sequence

Orchestrated initialization with graceful degradation:

1. Configuration validation
2. Backend connectivity (Redis, PostgreSQL)
3. Database schema validation
4. Observability (OpenTelemetry, Prometheus)
5. Background task schedulers
6. Control plane and knowledge systems
7. Security (RBAC cache, key rotation)
8. Workers (gauntlet, notification)

```python
from aragora.server.startup import run_startup_sequence

# Graceful degradation mode
await run_startup_sequence(graceful_degradation=True)

# Strict mode (Kubernetes)
await run_startup_sequence(graceful_degradation=False)
```

## Handler Organization

### Handler Registry

Centralized routing with O(1) exact path lookup:

```python
# handlers/custom.py
from aragora.server.handlers.base import BaseHandler, json_response

class CustomHandler(BaseHandler):
    ROUTES = ["/api/custom", "/api/custom/{id}"]

    def handle_GET(self, path, params, handler):
        return json_response({"data": result})

    def handle_POST(self, path, params, handler):
        return json_response({"status": "created"}, status=201)
```

### Handler Categories

| Category | Purpose |
|----------|---------|
| `debates.py` | Debate CRUD, history, export |
| `agents.py` | Agent profiles, ELO rankings |
| `memory/` | Learning systems, memory tiers |
| `knowledge.py` | Knowledge Mound adapters |
| `analytics/` | Metrics, dashboards, reporting |
| `autonomous/` | Approvals, alerts, triggers |
| `social/`, `bots/` | Chat platform handlers |
| `admin/` | Health, dashboards, configuration |
| `auth.py`, `oauth/` | Authentication, OAuth flows |
| `billing/` | Usage tracking, invoicing |

## Middleware Pipeline

32+ composable middleware organized by layer:

| Layer | Middleware |
|-------|------------|
| **Security** | `security.py`, `security_headers.py`, `xss_protection.py` |
| **Authentication** | `auth.py`, `user_auth.py`, `mfa.py`, `impersonation.py` |
| **Authorization** | `rbac.py`, `abac.py` |
| **Rate Limiting** | `rate_limit.py`, `tier_enforcement.py`, `budget_enforcement.py` |
| **Request Processing** | `body_size_limit.py`, `timeout.py`, `validation.py` |
| **Resilience** | `approval_gate.py`, `token_revocation.py` |
| **Caching** | `cache.py` |
| **Observability** | `request_logging.py`, `tracing.py`, `slo_tracking.py` |
| **Multi-Tenancy** | `tenancy.py`, `tenant_isolation.py`, `correlation.py` |

### Middleware Order

```python
# Recommended application order:
1. Security (reject threats first)
2. Authentication/Authorization
3. Rate Limiting (prevent abuse before expensive ops)
4. Request Processing (validation, size limits)
5. Resilience (approvals, revocation checks)
6. Observability (logging, tracing)
7. Caching (serve cached responses)
```

## Debate Origin Routing

Bidirectional chat result routing to originating platforms:

```python
from aragora.server.debate_origin import (
    register_debate_origin,
    route_debate_result,
)

# When debate starts from Slack
register_debate_origin(
    debate_id="abc123",
    platform="slack",
    channel_id="#debates",
    user_id="U12345",
    metadata={"thread_ts": "1234567890.123456"}
)

# When debate completes, result routes back to Slack
await route_debate_result(debate_id, result)
```

**Supported Platforms:**
- Telegram, WhatsApp (chat)
- Slack, Teams, Discord (team chat)
- Email, Google Chat (enterprise)

## WebSocket Streaming

Real-time debate event broadcasting:

```python
from aragora.server.stream import SyncEventEmitter, StreamEventType

emitter: SyncEventEmitter = ...

emitter.emit(
    StreamEventType.DEBATE_START,
    {"debate_id": "abc123", "participants": [...]}
)
```

**Event Types:**
- `debate_start`, `round_start` - Debate phases
- `agent_message`, `critique`, `vote` - Agent participation
- `consensus`, `debate_end` - Completion
- `approval_requested`, `alert_triggered` - Autonomous operations

### Stream Servers

| Server | Purpose |
|--------|---------|
| `debate_stream_server.py` | Debate event streaming |
| `control_plane_stream.py` | System events |
| `nomic_loop_stream.py` | Self-improvement events |
| `voice_stream.py` | TTS streaming |
| `usage_stream.py` | Billing events |

## Configuration

### Environment Variables

```bash
# Server
ARAGORA_PORT=8080
ARAGORA_API_TIMEOUT=60
ARAGORA_ALLOWED_ORIGINS=*

# Startup
ARAGORA_ENV=production
ARAGORA_STRICT_STARTUP=true
ARAGORA_REQUIRE_DATABASE=true
ARAGORA_AUTO_MIGRATE_ON_STARTUP=true

# Security
ENCRYPTION_KEY=<base64-key>
ARAGORA_API_TOKEN=<token>
```

## Security Features

- **RBAC**: 360+ permissions with role hierarchy
- **Multi-Tenancy**: Workspace isolation with membership verification
- **Rate Limiting**: Per-user, per-tier, per-endpoint quotas
- **Audit Logging**: SOC 2 compliance trails
- **Token Management**: Revocation store with Redis backend
- **MFA Enforcement**: TOTP/HOTP for privileged operations
- **Approval Gates**: High-risk operation approval workflow

## Performance

| Metric | Target |
|--------|--------|
| Route Lookup | O(1) exact match |
| Request Processing | <100ms median |
| WebSocket Broadcast | <10ms per 100 subscribers |
| Handler Lazy Load | ~50-100ms first invocation |
| Startup Time | <30s SLO |

## Related Modules

- `aragora.debate` - Debate orchestration
- `aragora.agents` - Agent implementations
- `aragora.server.handlers/` - Endpoint handlers
- `aragora.server.middleware/` - Request middleware
