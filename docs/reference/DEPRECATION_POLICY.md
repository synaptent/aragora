# Aragora Deprecation Policy

This document outlines Aragora's comprehensive deprecation policy for API endpoints, configuration options, SDK methods, and internal APIs. Following these guidelines ensures backward compatibility and smooth transitions for all users.

## Overview

Aragora follows a structured deprecation process that balances the need for improvement with stability for existing integrations. All deprecations follow a **2 minor version grace period** before removal.

### Deprecation Timeline

| Event | Timeline | Example |
|-------|----------|---------|
| Deprecation announced | Version N | v2.1.0 |
| Grace period begins | Version N | v2.1.x |
| Deprecation warnings active | Version N to N+1 | v2.1.x - v2.2.x |
| Removal | Version N+2 | v2.3.0 |

**Example**: A feature deprecated in v2.1.0 will be removed in v2.3.0, giving users the entire v2.1.x and v2.2.x release cycles to migrate.

### Versioning Reference

For complete API versioning details, see [API_VERSIONING.md](../api/API_VERSIONING.md).

---

## Deprecation Categories

### 1. API Endpoints

REST API endpoints and WebSocket events.

**Grace period**: 2 minor versions (minimum 6 months)

**Notification methods**:
- Response headers (`Deprecation`, `Sunset`, `Link`)
- API documentation updates
- CHANGELOG entries

**Example deprecation headers**:
```http
HTTP/1.1 200 OK
Deprecation: @1735689600
Sunset: 2026-06-01
Link: </api/v2/debates>; rel="successor-version"
X-Deprecation-Level: warning
```

### 2. Configuration Options

Environment variables, config file options, and CLI flags.

**Grace period**: 2 minor versions

**Notification methods**:
- Startup warnings logged to stderr
- Configuration validation warnings
- Documentation updates

**Example startup warning**:
```
WARNING: Configuration option 'ARAGORA_REQUIRE_DISTRIBUTED_STATE' is deprecated.
Use 'ARAGORA_REQUIRE_DISTRIBUTED' instead. This option will be removed in v2.3.0.
```

### 3. SDK Methods

Python SDK classes, functions, and methods.

**Grace period**: 2 minor versions

**Notification methods**:
- `DeprecationWarning` via `warnings.warn()`
- Docstring annotations
- Type hints with deprecation markers
- SDK documentation updates

**Example deprecation warning**:
```python
import warnings

warnings.warn(
    "aragora.modes.gauntlet is deprecated. Use aragora.gauntlet instead. "
    "See docs/GAUNTLET_ARCHITECTURE.md for migration guide.",
    DeprecationWarning,
    stacklevel=2,
)
```

### 4. Internal APIs

Internal modules, classes, and functions not intended for public use.

**Grace period**: 1 minor version (may be shorter for security fixes)

**Notification methods**:
- Code comments
- Internal documentation
- No public announcement required

---

## How to Mark Something as Deprecated

### Python Code

Use the `warnings` module with `DeprecationWarning`:

```python
import warnings

# At module level for deprecated modules
warnings.warn(
    "aragora.crawlers is deprecated. Use aragora.connectors instead.",
    DeprecationWarning,
    stacklevel=2,
)

# At class level for deprecated classes
class LegacyCrawler:
    """
    Legacy crawler implementation.

    .. deprecated:: 2.0
        Use :class:`aragora.connectors.Crawler` instead.
    """

    def __init__(self):
        warnings.warn(
            "LegacyCrawler is deprecated. Use aragora.connectors.Crawler instead.",
            DeprecationWarning,
            stacklevel=2,
        )

# At function level for deprecated functions
def old_function():
    """
    Old function.

    .. deprecated:: 2.1
        Use :func:`new_function` instead. Will be removed in v2.3.0.
    """
    warnings.warn(
        "old_function() is deprecated. Use new_function() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Call the new implementation
    return new_function()
```

### Docstring Annotations

Use Sphinx-style deprecation directives:

```python
def deprecated_method(self, arg):
    """
    Perform an operation (deprecated).

    .. deprecated:: 2.1.0
        Use :meth:`new_method` instead. This method will be removed in v2.3.0.

    Args:
        arg: The argument description.

    Returns:
        The result description.

    Migration:
        Replace ``obj.deprecated_method(x)`` with ``obj.new_method(x, default=True)``.
    """
```

### API Endpoints

Add deprecation headers in the response:

```python
from datetime import datetime

def deprecated_endpoint_handler(request):
    response = create_response(data)

    # RFC 8594 compliant deprecation headers
    response.headers["Deprecation"] = f"@{int(datetime.now().timestamp())}"
    response.headers["Sunset"] = "2026-06-01"
    response.headers["Link"] = '</api/v2/new-endpoint>; rel="successor-version"'
    response.headers["X-Deprecation-Level"] = "warning"  # or "critical" near sunset

    # Log usage for monitoring
    logger.warning(f"Deprecated endpoint accessed: {request.path}")

    return response
```

### Configuration Options

Add validation warnings during config loading:

```python
def load_config():
    config = {}

    # Check for deprecated options
    if os.environ.get("ARAGORA_REQUIRE_DISTRIBUTED_STATE"):
        warnings.warn(
            "ARAGORA_REQUIRE_DISTRIBUTED_STATE is deprecated. "
            "Use ARAGORA_REQUIRE_DISTRIBUTED instead. "
            "This option will be removed in v2.3.0.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Map old option to new one for backward compatibility
        if not os.environ.get("ARAGORA_REQUIRE_DISTRIBUTED"):
            config["require_distributed"] = os.environ["ARAGORA_REQUIRE_DISTRIBUTED_STATE"]

    return config
```

### Documentation

Update relevant documentation files:

1. **CHANGELOG.md**: Add deprecation notice
2. **API documentation**: Mark endpoint as deprecated
3. **SDK documentation**: Add deprecation warnings
4. **Migration guide**: Create or update migration instructions

---

## Migration Guide Requirements

Every deprecation MUST include a migration guide with:

### Required Elements

1. **Clear reason for deprecation**
   - Why is this being deprecated?
   - What benefits does the new approach provide?

2. **Before/After code examples**
   ```python
   # Before (deprecated)
   from aragora.modes.gauntlet import GauntletOrchestrator

   # After (recommended)
   from aragora.gauntlet import GauntletOrchestrator
   ```

3. **Step-by-step migration instructions**
   - List of changes needed
   - Order of operations
   - Potential pitfalls

4. **Timeline and deadlines**
   - When was it deprecated
   - When will it be removed
   - Key milestones

5. **Breaking changes highlighted**
   - API signature changes
   - Behavior differences
   - Return type changes

### Example Migration Guide

```markdown
## Migrating from aragora.crawlers to aragora.connectors

### Why?

The `aragora.crawlers` module is being replaced by `aragora.connectors` which provides:
- Better AST-based symbol extraction
- Concurrent processing
- Provenance tracking
- Reliability scoring

### Timeline

- **Deprecated**: v2.0.0 (January 2026)
- **Removal**: v2.2.0 (planned June 2026)

### Migration Steps

1. Update imports:
   ```python
   # Old
   from aragora.crawlers import RepositoryCrawler

   # New
   from aragora.connectors.repository_crawler import RepositoryCrawler
   ```

2. Update configuration (if using config files):
   ```yaml
   # Old
   crawler:
     type: repository

   # New
   connector:
     type: repository
   ```

3. Update method calls:
   - `crawler.crawl()` -> `connector.crawl()` (no change)
   - `crawler.index()` -> `connector.index(include_provenance=True)`

### Breaking Changes

- `RepositoryCrawler.get_stats()` now returns `ConnectorStats` instead of `CrawlStats`
- `crawl()` now returns results with provenance metadata by default
```

---

## Testing Requirements Before Removal

Before removing deprecated code:

### 1. Usage Monitoring

Track deprecated feature usage for at least one release cycle:

```python
# Prometheus metrics
from prometheus_client import Counter

deprecated_usage = Counter(
    'aragora_deprecated_feature_usage_total',
    'Usage count of deprecated features',
    ['feature', 'version']
)

# Log when deprecated feature is used
deprecated_usage.labels(feature='crawlers_module', version='2.1.0').inc()
```

### 2. Test Coverage

Ensure tests exist for:
- Deprecation warnings are emitted
- Backward compatibility works during grace period
- Migration path functions correctly
- New replacement feature has equivalent coverage

```python
import warnings
import pytest

def test_deprecation_warning_emitted():
    """Test that importing deprecated module emits warning."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        from aragora.crawlers import RepositoryCrawler

        assert len(w) >= 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "deprecated" in str(w[0].message).lower()

def test_backward_compatibility():
    """Test that deprecated API still works."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from aragora.crawlers import RepositoryCrawler

        crawler = RepositoryCrawler(path="/tmp/test")
        # Verify it still functions
        assert crawler is not None
```

### 3. Documentation Review

Before removal, verify:
- [ ] Migration guide is complete and accurate
- [ ] All references in docs are updated
- [ ] CHANGELOG documents the removal
- [ ] No broken links to removed features

### 4. Communication

Before final removal:
- [ ] Announce in release notes
- [ ] Update API documentation
- [ ] Notify users via deprecation warnings (minimum 2 releases)
- [ ] Check usage metrics to ensure low adoption

---

## Notification Channels

### Primary Channels

| Channel | When | Content |
|---------|------|---------|
| **CHANGELOG.md** | Every release | Deprecation notices, removals |
| **Deprecation warnings** | Runtime | Warning message with migration path |
| **Documentation** | Ongoing | Updated guides, API reference |
| **Response headers** | Per request | Sunset date, successor link |

### CHANGELOG Format

```markdown
## [2.1.0] - 2026-01-15

### Deprecated

- `aragora.crawlers` module - Use `aragora.connectors` instead. Will be removed in v2.3.0.
  See `docs/guides/V1_TO_V2_MIGRATION.md` for migration guidance.

- `ARAGORA_REQUIRE_DISTRIBUTED_STATE` environment variable - Use `ARAGORA_REQUIRE_DISTRIBUTED`.
  Will be removed in v2.3.0.

- `GET /api/debates/list` endpoint - Use `GET /api/debates`. Will be removed in v2.3.0.
```

### GitHub Release Notes

Include deprecation section in GitHub releases:

```markdown
## Deprecations

:warning: The following items are deprecated and will be removed in v2.3.0:

- **aragora.crawlers module**: Use `aragora.connectors` instead
- **ARAGORA_REQUIRE_DISTRIBUTED_STATE**: Use `ARAGORA_REQUIRE_DISTRIBUTED`
- **GET /api/debates/list**: Use `GET /api/debates`

See [Deprecation Policy](docs/DEPRECATION_POLICY.md) for migration guides.
```

---

## Currently Deprecated Items

### API Versions

| Version | Status | Sunset Date |
|---------|--------|-------------|
| v1 | Deprecated | 2026-06-01 |
| v2 | Current | - |

> **Historical removals (completed):** The following were deprecated in v1.5–v2.0 and removed by v2.3–v2.8:
>
> - API endpoints: `GET /api/debates/list`, `POST /api/debate/new`, `GET /api/elo/rankings`, `GET /api/agent/elo`, `POST /api/stream/start` — all removed; use v2 equivalents
> - Python modules: `aragora.modes.gauntlet` (→ `aragora.gauntlet`), `aragora.crawlers` (→ `aragora.connectors`) — both removed
> - Config option: `ARAGORA_REQUIRE_DISTRIBUTED_STATE` (→ `ARAGORA_REQUIRE_DISTRIBUTED`) — removed

No items are currently in an active deprecation window. The v1 API sunset date is June 1, 2026.

---

## Examples of Proper Deprecation

### Example 1: Module Deprecation

*(Historical example — `aragora/modes/gauntlet.py` was removed in v2.3.0 after deprecation was complete. The pattern below shows how the deprecation warning was implemented.)*

```python
"""
Gauntlet Mode - Adversarial Validation Engine.

DEPRECATED: This module is deprecated. Use aragora.gauntlet instead.

The canonical Gauntlet implementation is now in the aragora.gauntlet package,
which provides a more feature-complete API with:
- GauntletRunner for simple 3-phase execution
- GauntletOrchestrator for full 5-phase execution
- Templates for common use cases
- Receipt generation for compliance
- Persona-based regulatory testing

Migration:
    # Old (deprecated)
    from aragora.modes.gauntlet import GauntletOrchestrator

    # New (recommended)
    from aragora.gauntlet import GauntletOrchestrator
"""

import warnings

warnings.warn(
    "aragora.modes.gauntlet is deprecated. Use aragora.gauntlet instead. "
    "See docs/GAUNTLET_ARCHITECTURE.md for migration guide.",
    DeprecationWarning,
    stacklevel=2,
)

# Rest of module continues to function for backward compatibility
```

### Example 2: Package Deprecation

*(Historical example — `aragora/crawlers/` was removed in v2.3.0 after deprecation was complete. Use `aragora.connectors` instead.)*

```python
"""
Crawlers for Enterprise Multi-Agent Control Plane.

.. deprecated:: 2.0
    The crawlers module is deprecated. Use the connectors module instead:

    - For repository crawling: use ``aragora.connectors.repository_crawler``
    - For local docs: use ``aragora.connectors.local_docs``
    - For web content: use ``aragora.connectors.web``

Legacy usage (deprecated):
    from aragora.crawlers import RepositoryCrawler

New usage (recommended):
    from aragora.connectors.repository_crawler import RepositoryCrawler
"""

import warnings

warnings.warn(
    "The aragora.crawlers module is deprecated. "
    "Use aragora.connectors.repository_crawler for repository crawling instead. "
    "See module docstring for migration guide.",
    DeprecationWarning,
    stacklevel=2,
)
```

### Example 3: API Endpoint Deprecation

Response headers for `GET /api/debates/list`:

```http
HTTP/1.1 200 OK
Content-Type: application/json
Deprecation: @1704067200
Sunset: 2026-06-01
Link: </api/debates>; rel="successor-version"
X-API-Version: v1
X-API-Deprecated: true
X-Deprecation-Level: warning
```

---

## Exceptions to Policy

The following situations may warrant shorter deprecation periods:

1. **Security vulnerabilities**: Critical security issues may require immediate removal
2. **Legal/compliance requirements**: Regulatory changes may force faster deprecation
3. **Data integrity issues**: Features that could cause data loss may be removed faster

In exceptional cases:
- Minimum 1 release cycle notice
- Direct communication to affected users (if identifiable)
- Prominently documented in release notes

---

## Contact

For deprecation questions or migration assistance:
- **GitHub Issues**: https://github.com/an0mium/aragora/issues (tag: `deprecation`)
- **Documentation**: https://docs.aragora.ai/deprecation

---

*Last updated: 2026-03-05*
