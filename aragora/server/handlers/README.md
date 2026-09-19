# Handlers Architecture

HTTP endpoint handlers for the Aragora unified server.

## Overview

The handlers system provides modular, domain-specific endpoint groups. Each handler manages routes for a specific feature area (debates, agents, analytics, etc.) and inherits common functionality from `BaseHandler`.

**Scale:** 501 handler modules, 461 API endpoints, 30+ handler categories.

## Directory Structure

```
handlers/
├── __init__.py          # Handler exports and registration
├── base.py              # BaseHandler, mixins, response utilities
├── interface.py         # Handler interface contracts (HandlerInterface, etc.)
├── types.py             # Shared type definitions
├── utils/               # Shared utilities
│   ├── decorators.py    # @require_auth, @require_permission, etc.
│   ├── params.py        # Query parameter extraction
│   ├── routing.py       # PathMatcher, RouteDispatcher
│   ├── safe_data.py     # Safe dict access helpers
│   └── rate_limit.py    # Rate limiting utilities
├── admin/               # Admin endpoints (health, billing, cache, security)
├── agents/              # Agent profiles, rankings, calibration
├── auth/                # Authentication and SSO
├── autonomous/          # Autonomous mode triggers, approvals
├── bots/                # Bot platform handlers (Telegram, Discord, etc.)
├── canvas/              # Visual canvas endpoints
├── chat/                # Chat routing and messaging
├── debates/             # Debate CRUD and management
├── decisions/           # Decision explainability
├── features/            # Feature-specific handlers (audio, broadcast, etc.)
├── knowledge/           # Knowledge Mound endpoints
├── memory/              # Memory system endpoints
├── metrics/             # Metrics and observability
├── oauth/               # OAuth flow management
├── social/              # Social platform integrations (Slack, Teams)
├── voice/               # Voice and TTS endpoints
└── webhooks/            # Webhook management
```

## BaseHandler

All handlers inherit from `BaseHandler` in `base.py`:

```python
from aragora.server.handlers.base import BaseHandler, HandlerResult

class MyHandler(BaseHandler):
    def __init__(self, ctx: ServerContext):
        super().__init__(ctx)

    def handle_list(self, handler, query_params) -> HandlerResult:
        # Access shared resources via self.ctx
        storage = self.ctx.get("storage")
        return self.json_response({"items": []})
```

### ServerContext

Handlers receive a `ServerContext` dict with shared resources:

| Resource | Description |
|----------|-------------|
| `storage` | Main debate storage |
| `user_store` | User authentication storage |
| `elo_system` | Agent ELO ratings |
| `continuum_memory` | Cross-debate memory |
| `critique_store` | Critique persistence |
| `ws_manager` | WebSocket connections |
| `event_emitter` | Event pub/sub |

### Response Helpers

```python
# Success response
return self.json_response({"data": result})

# Error response
return self.error_response("Not found", status=404)

# Feature unavailable (503)
return feature_unavailable_response("pulse")
```

## Handler Mixins

Compose handlers with reusable functionality:

```python
class MyHandler(BaseHandler, PaginatedHandlerMixin, CachedHandlerMixin):
    pass
```

| Mixin | Purpose |
|-------|---------|
| `PaginatedHandlerMixin` | Pagination with `paginate_results()` |
| `CachedHandlerMixin` | Response caching with `cache_response()` |
| `AuthenticatedHandlerMixin` | Authentication helpers |

## Route Registration

Handlers are registered in `__init__.py` and connected to the unified server:

```python
# In handlers/__init__.py
from .my_feature import MyFeatureHandler

# In unified_server.py
ctx = {"storage": storage, "elo_system": elo}
my_handler = MyFeatureHandler(ctx)

# Route matching
if my_handler.can_handle(path):
    result = my_handler.handle(path, query_params, request_handler)
```

Handlers may dispatch to `async def handle_*` implementations. The production
handler registry resolves awaitables before writing the response, and
standalone tests should do the same instead of assuming `handle()` is always
purely synchronous.

## Authentication & RBAC

### Authentication Decorator

```python
from aragora.server.handlers.utils.decorators import require_auth

@require_auth
def handle_protected(self, handler, query_params) -> HandlerResult:
    # handler.user is guaranteed to be authenticated
    user_id = handler.user.id
    return self.json_response({"user": user_id})
```

### Permission Decorator

```python
from aragora.server.handlers.utils.decorators import require_permission

@require_permission("debates:write")
def handle_create_debate(self, handler, query_params) -> HandlerResult:
    # User has debates:write permission
    pass
```

### Manual Authentication

```python
from aragora.billing.jwt_auth import extract_user_from_request

def handle_request(self, handler, query_params) -> HandlerResult:
    user_store = self.ctx.get("user_store")
    auth_ctx = extract_user_from_request(handler, user_store)

    if not auth_ctx.is_authenticated:
        return self.error_response("Not authenticated", status=401)

    # Proceed with authenticated user
    user_id = auth_ctx.user_id
```

### Permission Matrix

Common permissions (see `PERMISSION_MATRIX` in `utils/decorators.py`):

- `debates:read`, `debates:write`, `debates:delete`
- `agents:read`, `agents:write`
- `analytics:read`, `analytics:export`
- `admin:read`, `admin:write`
- `backups:read`, `backups:write`, `backups:delete`

## Request Handling

### Query Parameters

```python
from aragora.server.handlers.base import (
    get_int_param,
    get_bool_param,
    get_string_param,
)

def handle_list(self, handler, query_params) -> HandlerResult:
    limit = get_int_param(query_params, "limit", default=50)
    active = get_bool_param(query_params, "active", default=True)
    search = get_string_param(query_params, "q", default="")
```

### JSON Body

```python
def handle_create(self, handler, query_params) -> HandlerResult:
    body = self.read_json_body(handler)
    if body is None:
        return self.error_response("Invalid JSON")

    title = body.get("title", "")
```

### Path Parameters

```python
# For routes like /api/debates/{debate_id}
def handle_get(self, handler, query_params, debate_id: str) -> HandlerResult:
    # debate_id extracted from path
    pass
```

## Error Handling

### Auto Error Response

```python
from aragora.server.handlers.utils.decorators import auto_error_response

@auto_error_response
def handle_risky(self, handler, query_params) -> HandlerResult:
    # Exceptions automatically converted to error responses
    result = dangerous_operation()
    return self.json_response(result)
```

### Manual Error Handling

```python
def handle_request(self, handler, query_params) -> HandlerResult:
    try:
        result = some_operation()
        return self.json_response(result)
    except ValueError as e:
        logger.warning("Validation error: %s", e)
        return self.error_response("Invalid request parameters", status=400)
    except PermissionError:
        return self.error_response("Forbidden", status=403)
    except Exception:
        logger.exception("Unexpected error")
        return self.error_response("Internal error", status=500)
```

## Creating a New Handler

1. Create a new file in the appropriate directory:

```python
# handlers/features/my_feature.py
from aragora.server.handlers.base import BaseHandler, HandlerResult

class MyFeatureHandler(BaseHandler):
    """Handler for my feature endpoints."""

    def can_handle(self, path: str) -> bool:
        return path.startswith("/api/my-feature")

    def handle(self, path: str, query_params: dict, handler) -> HandlerResult:
        self.set_request_context(handler, query_params)

        if path == "/api/my-feature/list":
            return self._handle_list()
        elif path.startswith("/api/my-feature/"):
            item_id = path.split("/")[-1]
            return self._handle_get(item_id)

        return self.error_response("Not found", status=404)

    def _handle_list(self) -> HandlerResult:
        # Implementation
        return self.json_response({"items": []})

    def _handle_get(self, item_id: str) -> HandlerResult:
        # Implementation
        return self.json_response({"id": item_id})
```

2. Register in `__init__.py`:

```python
from .features.my_feature import MyFeatureHandler
```

3. Add to unified server route registration.

4. Write tests in `tests/server/handlers/test_my_feature.py`.

## Caching

Use TTL caching for expensive operations:

```python
from aragora.server.handlers.base import ttl_cache

@ttl_cache(ttl_seconds=60)
def get_expensive_data(self, key: str) -> dict:
    # Cached for 60 seconds
    return compute_expensive_result(key)
```

Invalidate caches on mutations:

```python
from aragora.server.handlers.base import invalidate_cache

def handle_update(self, handler, query_params) -> HandlerResult:
    # Update data
    result = update_item(item_id)

    # Invalidate related caches
    invalidate_cache("get_expensive_data", item_id)

    return self.json_response(result)
```

## Rate Limiting

Apply rate limits via middleware or decorator:

```python
from aragora.server.handlers.utils.rate_limit import rate_limit

@rate_limit(requests_per_minute=60)
def handle_api_call(self, handler, query_params) -> HandlerResult:
    pass
```

## Testing

Handler tests use pytest with fixtures:

```python
# tests/server/handlers/test_my_feature.py
import pytest
from aragora.server.handlers.features.my_feature import MyFeatureHandler

@pytest.fixture
def handler():
    ctx = {"storage": mock_storage}
    return MyFeatureHandler(ctx)

def test_list_returns_items(handler):
    result = handler.handle("/api/my-feature/list", {}, mock_request)
    assert result[1] == 200
    data = json.loads(result[0])
    assert "items" in data
```

### Typed handler characterization suites

The admin, analytics, compliance, identity/auth, OAuth and security handler
modules whose type annotations were tightened carry characterization suites
(`tests/handlers/test_*_typing_contracts.py` and
`tests/handlers/test_spend_analytics.py`) that pin their runtime behaviour.
Run the four suites focused, from the repository root with the project
environment active (`pip install -e ".[dev,test]"`):

```bash
python -m pytest tests/handlers/test_admin_typing_contracts.py tests/handlers/test_spend_analytics.py tests/handlers/test_compliance_identity_typing_contracts.py tests/handlers/test_security_typing_contracts.py -q -p no:randomly -n 4 --timeout=120
```

`-p no:randomly` keeps parametrized case order deterministic (`pytest-randomly`
is installed by the `test` extra), `-n 4` matches the CI worker count and
`--timeout=120` bounds any single case. The suites make no network calls:
every service they exercise is a real in-process object backed by a temporary
SQLite store or directory under `tmp_path`.

Type-check the whole `aragora/` import graph from an empty mypy cache (a warm
`.mypy_cache` can hide line-attribution drift). The tier requires mypy 2.1.0 on
a CPython 3.11 host and exits `0` only when no finding lies outside
`scripts/baselines/root-mypy-full.json`; set `TYPECHECK_PYTHON` to the
interpreter to use when `python` on `PATH` is not the project environment:

```bash
MYPY_CACHE_DIR="$(mktemp -d)" bash scripts/test_tiers.sh typecheck
```

When writing or extending these suites:

- **Await decorated results before inspecting them.** Entry points wrapped by
  the decorators in `utils/decorators.py` can hand back a coroutine even when
  the wrapped method is synchronous. Call the handler, `asyncio.run()` the
  result when `inspect.iscoroutine()` reports one, and only then read
  `status_code` and the body.
- **Patch the defining module object.** Resolve the module with
  `importlib.import_module("aragora.server.handlers.<name>")` and patch
  attributes on the object it returns (`monkeypatch.setattr(module, ...)` or
  `patch.object(module, ...)`). On trees where the handler lives at
  `aragora/server/handlers/<package>/<name>.py`, the package's moved-module
  finder resolves the legacy name to the same module object as
  `aragora.server.handlers.<package>.<name>`, so a patch applied to that object
  is visible through both import names; a string patch target assembled from
  either name, or a re-export on the `aragora.server.handlers` package, is not.
  The `TYPEALIAS_001` cases assert this identity (same module and symbol
  objects, `__file__` inside the tree under test) for every covered module;
  set `TYPING_SNAPSHOT_ROOT=<tree root>` when the interpreter could import
  `aragora` from somewhere other than the tree being tested.
- **Retained legacy semantics are the contract.** Lazy manager accessors such
  as `_get_manager()` and `_get_backup_manager()` may return `None` when the
  subsystem is unavailable, and callers surface the original `AttributeError`
  text rather than a new error response. `DRHandler.handle` accepts three call
  forms (`(path, query_params, request)`, `("GET", path, None)` and
  `(method=..., path=...)`) and answers `400` with
  `Invalid request: no path or method provided` when given none.
  `ThreatIntelHandler.handle` runs its permission check and returns `None`
  (its routes are served through `register_threat_intel_routes`). The audit
  verify endpoint treats an absent, malformed or non-object body as `{}` and
  verifies the full range. Spend analytics resolves an absent, `None` or
  empty-list `workspace_id` query value to `"default"`. New cases characterize
  the existing observation; a behaviour change is a separate change with its
  own tests and review.

## Key Files

| File | Purpose |
|------|---------|
| `base.py` | BaseHandler, ServerContext, response utilities |
| `interface.py` | Handler interface contracts |
| `utils/decorators.py` | @require_auth, @require_permission, @handle_errors |
| `utils/params.py` | Query parameter extraction |
| `utils/routing.py` | PathMatcher, RouteDispatcher |
