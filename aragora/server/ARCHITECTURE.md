# Aragora Server Architecture

## Overview

Aragora runs two server modes with different trade-offs. The **legacy mode** uses
Python's `ThreadingHTTPServer` with a mixin-based `UnifiedHandler` and is the
production-grade entry point that exposes the full API surface. The **FastAPI mode**
is an async ASGI alternative currently covering a small subset of routes, intended
as the long-term migration target but not yet a full replacement.

Both modes share the same WebSocket streaming infrastructure, which runs on
dedicated ports alongside whichever HTTP server is active.

---

## Legacy Mode (Production)

**Command:**

```bash
python -m aragora.server --port 8080
# or
aragora serve
```

**Architecture:**

The legacy server is built on `http.server.ThreadingHTTPServer` with a composite
handler class assembled from multiple mixins:

```python
class UnifiedHandler(
    ResponseHelpersMixin,      # JSON responses, CORS, security headers
    HandlerRegistryMixin,      # Modular handler routing and dispatch
    AuthChecksMixin,           # Rate limiting and RBAC permission checks
    RequestUtilsMixin,         # Parameter parsing, content validation
    RequestLoggingMixin,       # Request logging and metrics
    DebateControllerMixin,     # Debate controller lifecycle
    BaseHTTPRequestHandler,    # stdlib HTTP handler
):
```

Each HTTP method (`do_GET`, `do_POST`, `do_PUT`, `do_DELETE`, `do_PATCH`) goes
through a `RequestLifecycleManager` that handles:

1. State reset
2. URL parsing and query extraction
3. Tracing span creation (OpenTelemetry)
4. Timeout enforcement (configurable per-path)
5. Delegation to the internal handler method
6. Error handling and metrics recording

**Handler Registry:**

The full API surface is served via the `HandlerRegistryMixin`, which manages
~300 handler classes across 546 handler modules in `aragora/server/handlers/`.
Handlers are organized into domain-specific registries:

| Registry | Domain |
|----------|--------|
| `ADMIN_HANDLER_REGISTRY` | Health, system, admin, docs, SCIM |
| `DEBATE_HANDLER_REGISTRY` | Debates, consensus, gauntlet, reviews |
| `AGENT_HANDLER_REGISTRY` | Agents, personas, calibration, evolution |
| `ANALYTICS_HANDLER_REGISTRY` | Analytics, metrics, dashboards |
| `MEMORY_HANDLER_REGISTRY` | Memory, knowledge, documents, evidence |
| `SOCIAL_HANDLER_REGISTRY` | Chat, bots, social, email |

Route dispatch uses a `RouteIndex` with O(1) exact-path lookup (dict) and
LRU-cached prefix matching for dynamic routes. Handlers are lazily initialized
on first request and auto-instrumented for observability.

**Request flow (legacy GET):**

```
Client
  |
  v
do_GET()
  |-> RequestLifecycleManager
  |     |-> URL parse + query extraction
  |     |-> TracingMiddleware (span creation)
  |     |-> Timeout enforcement
  |     '-> _do_GET_internal()
  |           |-> Query param validation (whitelist)
  |           |-> RBAC authorization check
  |           |-> Rate limiting (DoS protection)
  |           |-> RouteIndex.get_handler(path)  [O(1) lookup]
  |           |     |-> Extract auth context (JWT)
  |           |     |-> Default rate limit check
  |           |     |-> handler.handle(path, query, request)
  |           |     |-> API version headers
  |           |     |-> CORS + security headers
  |           |     '-> Response
  |           |
  |           |-> (fallback) iterate HANDLER_REGISTRY
  |           '-> Static file serving (non-API paths)
  v
Response
```

**Multi-worker mode:**

```bash
python -m aragora.server --workers 4 --host 0.0.0.0
```

Spawns N worker processes using `multiprocessing.Process`. Each worker binds to
`base_port + i` for both HTTP and WebSocket. A reverse proxy (nginx, haproxy)
is expected in front for load balancing.

---

## FastAPI Mode (Partial)

**Command:**

```bash
uvicorn aragora.server.app:app --port 8081

# Or via environment variable with legacy server:
ARAGORA_USE_FASTAPI=true python -m aragora.server
```

**Architecture:**

The FastAPI application is created by `aragora.server.fastapi.factory.create_app()`,
which assembles the ASGI application with middleware and routes.

**Current routes (14 endpoints across 4 modules):**

| Module | Prefix | Endpoints |
|--------|--------|-----------|
| `health` | `/` | `/healthz`, `/livez`, `/readyz`, `/api/v2/health`, `/api/v2/metrics/summary` |
| `debates` | `/api/v2` | `GET /debates`, `GET /debates/{id}`, `GET /debates/{id}/messages`, `GET /debates/{id}/convergence` |
| `decisions` | `/api/v2` | `POST /decisions`, `GET /decisions`, `GET /decisions/{id}`, `DELETE /decisions/{id}`, `GET /decisions/{id}/events` (SSE) |
| `testfixer` | `/api/v2` | 4 endpoints (development tooling) |

**Middleware stack** (outermost to innermost):

1. `SecurityHeadersMiddleware` -- security response headers
2. `CORSMiddleware` -- CORS with explicit origins (no wildcard with credentials)
3. `TracingMiddleware` -- request tracing / correlation IDs
4. `RequestValidationMiddleware` -- body size, JSON depth, array limits

**Lifespan management** initializes server context on startup (DebateStorage,
EloSystem, RBAC checker, ContinuumMemory, CrossDebateMemory, Knowledge Mound,
DecisionService) and cleans up on shutdown.

**When to use FastAPI mode:**

- It is NOT a full replacement for legacy mode. The vast majority of the API
  surface (~2000+ operations) is only available through the legacy handler registry.
- Good for: testing async debate orchestration via `/api/v2/decisions`, specific
  integrations needing OpenAPI v2 docs at `/api/v2/docs`.
- Future migration target: new endpoints should be added here when possible.

When `ARAGORA_USE_FASTAPI=true` is set, the `UnifiedServer.start()` method launches
FastAPI via uvicorn instead of `ThreadingHTTPServer`, but the WebSocket servers
still start as separate processes.

---

## WebSocket Servers

The server starts multiple WebSocket servers on dedicated ports for real-time
streaming. All are based on `websockets` / `aiohttp` and run concurrently via
`asyncio.gather()`.

| Server | Default Port | Purpose |
|--------|-------------|---------|
| `DebateStreamServer` | 8765 | Real-time debate event streaming (190+ event types) |
| `ControlPlaneStreamServer` | 8766 | Agent registry, task scheduling, health events |
| `NomicLoopStreamServer` | 8767 | Self-improvement loop phase events |
| `CanvasStreamServer` | 8768 | Collaborative canvas updates (optional) |
| `GatewayStreamServer` | (via gateway) | Gateway protocol streaming |

Additional stream emitters (not separate servers, but publish to WebSocket connections):

- `AutonomousStreamEmitter` -- autonomous operations events
- `GauntletStreamEmitter` -- gauntlet stress-test events
- `TeamInboxEmitter` -- team inbox notifications
- `InboxSyncEmitter` -- cross-device inbox synchronization
- `VoiceStreamHandler` -- voice session management

Event types are defined in `aragora.server.stream.events.StreamEventType` and
include: `debate_start`, `round_start`, `agent_message`, `critique`, `vote`,
`consensus`, `debate_end`, and many more.

---

## Offline Mode

```bash
python -m aragora.server --offline
```

Sets three environment variables before starting any workers:

| Variable | Value | Effect |
|----------|-------|--------|
| `ARAGORA_OFFLINE` | `true` | Disables external service calls |
| `ARAGORA_DEMO_MODE` | `true` | Uses demo/fixture data for unavailable services |
| `ARAGORA_DB_BACKEND` | `sqlite` | Forces SQLite instead of PostgreSQL |

Useful for local development, demos, and environments without network access.

---

## Environment Variables

### Server Binding

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_BIND_HOST` | `127.0.0.1` | Bind address for HTTP and WS servers |
| `ARAGORA_PORT` | -- | HTTP API port (also settable via `--http-port`) |

### Server Behavior

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_USE_FASTAPI` | `false` | Use FastAPI/uvicorn instead of ThreadingHTTPServer |
| `ARAGORA_FASTAPI_PORT` | (same as http_port) | Port for FastAPI when running alongside legacy |
| `ARAGORA_STRICT_STARTUP` | `false` | Fail fast on dependency errors instead of degrading gracefully |
| `ARAGORA_API_TIMEOUT` | `60` | Default request timeout in seconds |
| `ARAGORA_VALIDATION_BLOCKING` | `true` | Whether request validation rejects (true) or warns (false) |

### Security

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_ALLOWED_ORIGINS` | localhost defaults | Comma-separated CORS origins (no wildcard with credentials) |
| `ARAGORA_SSL_ENABLED` | `false` | Enable HTTPS |
| `ARAGORA_SSL_CERT` | -- | Path to SSL certificate |
| `ARAGORA_SSL_KEY` | -- | Path to SSL private key |

### Logging

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_ENV` | `development` | Environment name (`production` enables JSON logging) |
| `ARAGORA_LOG_FORMAT` | (auto) | Force `json` or `text` log format |
| `ARAGORA_LOG_LEVEL` | `INFO` | Log level |

### Offline/Minimal

| Variable | Default | Description |
|----------|---------|-------------|
| `ARAGORA_OFFLINE` | `false` | Disable external service calls |
| `ARAGORA_DEMO_MODE` | `false` | Use demo data for unavailable services |
| `ARAGORA_DB_BACKEND` | (auto) | Force `sqlite` or `postgres` backend |

---

## Architecture Diagram

```
                              Aragora Server
    ================================================================

    Client (HTTP)                          Client (WebSocket)
        |                                       |
        v                                       v
    +------------------+           +---------------------------+
    | ThreadingHTTP    |           | DebateStreamServer  :8765 |
    | Server    :8080  |           | ControlPlaneStream  :8766 |
    | (or FastAPI/     |           | NomicLoopStream     :8767 |
    |  uvicorn)        |           | CanvasStream        :8768 |
    +------------------+           +---------------------------+
        |                                       |
        v                                       v
    +------------------+           +---------------------------+
    | Request          |           | SyncEventEmitter          |
    | Lifecycle        |           | WebSocketBroadcaster      |
    | Manager          |           | ClientManager             |
    +------------------+           +---------------------------+
        |
        v
    +------------------------------------------------------+
    |              Middleware Pipeline                       |
    |                                                       |
    |  1. Tracing       (OpenTelemetry span)                |
    |  2. Timeout       (per-path enforcement)              |
    |  3. Query valid.  (whitelist check)                   |
    |  4. RBAC          (role/permission check)             |
    |  5. Rate limit    (DoS protection)                    |
    +------------------------------------------------------+
        |
        v
    +------------------------------------------------------+
    |              RouteIndex (O(1) dispatch)                |
    |                                                       |
    |  exact_routes:  { "/api/debates" -> DebatesHandler }  |
    |  prefix_routes: [ "/api/agent/" -> AgentsHandler ]    |
    |  LRU cache:     500-entry dynamic route cache         |
    +------------------------------------------------------+
        |
        v
    +------------------------------------------------------+
    |              Handler Registry (~700 handlers)          |
    |                                                       |
    |  ADMIN  | DEBATE | AGENT | ANALYTICS | MEMORY | SOCIAL|
    |  -------+--------+-------+-----------+--------+-------|
    |  health | debates| agents| analytics | memory | chat  |
    |  system | gauntlt| calib | metrics   | knowldg| bots  |
    |  admin  | review | evoltn| dashboard | docs   | email |
    |  docs   | consns | persnl| pulse     | evidnc | social|
    +------------------------------------------------------+
        |
        v
    +------------------------------------------------------+
    |              Response Pipeline                        |
    |                                                       |
    |  1. Status code + Content-Type                        |
    |  2. API version headers (X-API-Version, Sunset, etc.) |
    |  3. Handler-specific headers                          |
    |  4. CORS headers                                      |
    |  5. Security headers                                  |
    |  6. Trace headers (X-Trace-ID)                        |
    +------------------------------------------------------+
        |
        v
    Response to Client
```

---

## Key Files

| File | Purpose |
|------|---------|
| `aragora/server/__main__.py` | CLI entry point, argument parsing, worker spawning |
| `aragora/server/unified_server.py` | `UnifiedHandler` class (1240 lines), `UnifiedServer`, `run_unified_server()` |
| `aragora/server/handler_registry/__init__.py` | `HandlerRegistryMixin`, combined registry, route dispatch |
| `aragora/server/handler_registry/core.py` | `RouteIndex`, handler validation, safe import |
| `aragora/server/request_lifecycle.py` | `RequestLifecycleManager` -- tracing, timeout, error handling |
| `aragora/server/app.py` | FastAPI entry point (`create_app()`) |
| `aragora/server/fastapi/factory.py` | FastAPI factory with middleware and lifespan |
| `aragora/server/fastapi/routes/` | FastAPI route modules (health, debates, decisions) |
| `aragora/server/stream/__init__.py` | WebSocket server exports and lazy imports |
| `aragora/server/middleware/` | 35 middleware modules (auth, RBAC, rate limit, tracing, etc.) |
| `aragora/server/handlers/` | 546 handler modules organized by domain |
