# Connector Patterns Guide

This guide documents the architecture and patterns for implementing connectors in Aragora.

## Table of Contents

1. [Connector Types](#connector-types)
2. [Base Connector Architecture](#base-connector-architecture)
3. [Integration Connector Pattern](#integration-connector-pattern)
4. [Error Handling](#error-handling)
5. [Credential Management](#credential-management)
6. [Resilience Patterns](#resilience-patterns)
7. [Creating a New Connector](#creating-a-new-connector)

---

## Connector Types

Aragora uses two primary connector patterns:

### 1. Evidence Connectors (BaseConnector)

Evidence connectors fetch data from external sources to ground debates in real-world information. They inherit from `BaseConnector` and integrate with the provenance system.

**Location:** `aragora/connectors/`

**Purpose:**
- Search for relevant evidence
- Fetch specific documents/articles
- Record evidence in provenance chain
- Calculate reliability scores

**Examples:**
- `GitHubConnector` - Issues, PRs, discussions
- `WebConnector` - Live web content
- `ArXivConnector` - Academic papers
- `WikipediaConnector` - Encyclopedia articles
- `SQLConnector` - Database queries

### 2. Integration Connectors

Integration connectors interface with external business systems. They use async context managers and provide typed dataclasses for responses.

**Location:** `aragora/connectors/{domain}/`

**Purpose:**
- CRUD operations on external systems
- OAuth/webhook handling
- Event subscriptions
- Real-time sync

**Examples:**
- `StripeConnector` - Payments and billing
- `HubSpotConnector` - CRM and contacts
- `DocuSignConnector` - Document signing
- `PagerDutyConnector` - Incident management

---

## Base Connector Architecture

### Class Hierarchy

```
BaseConnector (ABC)
├── LocalDocsConnector
├── GitHubConnector
├── WebConnector
├── ArXivConnector
├── HackerNewsConnector
├── WikipediaConnector
├── RedditConnector
├── TwitterConnector
├── SQLConnector
├── NewsAPIConnector
├── SECConnector
└── WhisperConnector
```

### Core Interface

```python
from aragora.connectors.base import BaseConnector, Evidence
from aragora.reasoning.provenance import ProvenanceManager, SourceType

class MyConnector(BaseConnector):
    """Connector for MySource."""

    @property
    def name(self) -> str:
        return "MySource"

    @property
    def source_type(self) -> SourceType:
        return SourceType.WEB_SEARCH  # or appropriate type

    @property
    def is_available(self) -> bool:
        """Check if required dependencies are installed."""
        return True

    @property
    def is_configured(self) -> bool:
        """Check if API keys are configured."""
        return bool(self._api_key)

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> list[Evidence]:
        """Search for evidence matching query."""
        ...

    async def fetch(self, evidence_id: str) -> Evidence | None:
        """Fetch specific evidence by ID."""
        ...
```

### Evidence Dataclass

```python
@dataclass
class Evidence:
    id: str
    source_type: SourceType
    source_id: str  # URL, file path, etc.
    content: str
    title: str = ""

    # Metadata
    created_at: str | None = None
    author: str | None = None
    url: str | None = None

    # Reliability indicators
    confidence: float = 0.5
    freshness: float = 1.0
    authority: float = 0.5
    metadata: dict = field(default_factory=dict)

    @property
    def reliability_score(self) -> float:
        """Combined reliability score."""
        return 0.4 * self.confidence + 0.3 * self.freshness + 0.3 * self.authority
```

### Provenance Integration

```python
connector = GitHubConnector(
    token="...",
    provenance=ProvenanceManager(),
)

# Search and automatically record in provenance chain
results = await connector.search_and_record(
    query="rate limiting implementation",
    claim_id="claim_123",  # Optional link to a claim
    limit=5,
)

for evidence, record in results:
    print(f"Evidence: {evidence.title}")
    print(f"Provenance: {record.id if record else 'Not recorded'}")
```

---

## Integration Connector Pattern

### Async Context Manager

Integration connectors use async context managers for proper resource cleanup:

```python
from dataclasses import dataclass
import httpx

@dataclass
class MyCredentials:
    api_key: str
    base_url: str = "https://api.example.com"

class MyConnector:
    """Connector for MyService API."""

    def __init__(self, credentials: MyCredentials):
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "MyConnector":
        self._client = httpx.AsyncClient(
            base_url=self.credentials.base_url,
            headers={"Authorization": f"Bearer {self.credentials.api_key}"},
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("Connector not initialized. Use async context manager.")
        return self._client
```

### Typed Response Models

Use dataclasses with `from_api` class methods:

```python
@dataclass
class Customer:
    id: str
    email: str | None = None
    name: str | None = None
    created_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Customer":
        return cls(
            id=data["id"],
            email=data.get("email"),
            name=data.get("name"),
            created_at=(
                datetime.fromtimestamp(data["created"])
                if data.get("created") else None
            ),
        )
```

### API Request Pattern

```python
async def _request(
    self,
    method: str,
    endpoint: str,
    data: dict | None = None,
    params: dict | None = None,
) -> dict[str, Any]:
    """Make API request with error handling."""
    url = f"{self.BASE_URL}{endpoint}"

    response = await self.client.request(
        method, url, json=data, params=params
    )

    if response.status_code >= 400:
        error = response.json().get("error", {})
        raise MyServiceError(
            message=error.get("message", "Unknown error"),
            status_code=response.status_code,
        )

    return response.json()
```

---

## Error Handling

### Error Hierarchy

```python
# aragora/connectors/exceptions.py

class ConnectorError(Exception):
    """Base exception for all connector errors."""

class ConnectorAuthError(ConnectorError):
    """Authentication or authorization failure."""

class ConnectorRateLimitError(ConnectorError):
    """Rate limit exceeded (HTTP 429)."""
    retry_after: float | None = None

class ConnectorTimeoutError(ConnectorError):
    """Request timed out."""

class ConnectorNetworkError(ConnectorError):
    """Network connectivity issue."""

class ConnectorAPIError(ConnectorError):
    """API returned an error response."""
    status_code: int | None = None

class ConnectorNotFoundError(ConnectorError):
    """Resource not found (HTTP 404)."""

class ConnectorValidationError(ConnectorError):
    """Invalid request parameters."""

class ConnectorQuotaError(ConnectorError):
    """API quota exceeded."""

class ConnectorParseError(ConnectorError):
    """Failed to parse API response."""

class ConnectorCircuitOpenError(ConnectorError):
    """Circuit breaker is open."""
```

### Using the Error Handler

```python
from aragora.connectors.exceptions import (
    connector_error_handler,
    is_retryable_error,
    get_retry_delay,
)

# Context manager for error handling
async with connector_error_handler("fetch_customer"):
    customer = await connector.get_customer(customer_id)

# Check if error is retryable
if is_retryable_error(error):
    delay = get_retry_delay(error)
    await asyncio.sleep(delay)
```

### Changing a Connector's Search/Fetch Error Contract

Connectors do not share one failure contract for `search`, `fetch` and
`resolve_reference`: some re-raise after logging (for example ServiceNow), while
others log and return `[]` or `None`. Each connector's choice is pinned by its
own contract tests (for example `test_search_handles_api_errors` and
`test_fetch_handles_api_errors` in
`tests/connectors/enterprise/itsm/test_servicenow.py`). A PR that changes
whether a connector raises or swallows a failure MUST update those sibling
contract tests and the method docstrings in the same PR. A contract change that
ships without its tests leaves the old assertions failing on `main`. The
pull-request test shards do not run `tests/connectors/` (only the scheduled and
push-to-main "Optional Deps (Full)" job does), so run the connector's test file
locally before pushing.

---

## Credential Management

### Credential Providers

```python
from aragora.connectors.credentials import (
    CredentialProvider,
    EnvCredentialProvider,
    AWSSecretsManagerProvider,
    ChainedCredentialProvider,
    CachedCredentialProvider,
    get_credential_provider,
)

# Environment variable provider
env_provider = EnvCredentialProvider()
api_key = env_provider.get("STRIPE_API_KEY")

# AWS Secrets Manager provider
aws_provider = AWSSecretsManagerProvider(
    secret_name="prod/stripe",
    region="us-east-1",
)

# Chained provider (tries each in order)
provider = ChainedCredentialProvider([
    EnvCredentialProvider(),
    AWSSecretsManagerProvider("prod/stripe"),
])

# Cached provider (reduces API calls)
cached = CachedCredentialProvider(provider, ttl=300)
```

### Credential Dataclasses

```python
@dataclass
class StripeCredentials:
    secret_key: str
    webhook_secret: str | None = None

@dataclass
class HubSpotCredentials:
    access_token: str
    base_url: str = "https://api.hubapi.com"
```

---

## Resilience Patterns

### Built-in Retry with Backoff

BaseConnector provides automatic retry with exponential backoff:

```python
class MyConnector(BaseConnector):
    def __init__(self, ...):
        super().__init__(
            max_retries=3,
            base_delay=1.0,
            max_delay=30.0,
            enable_circuit_breaker=True,
        )

    async def search(self, query: str, limit: int = 10) -> list[Evidence]:
        async def do_request():
            response = await self._client.get("/search", params={"q": query})
            response.raise_for_status()
            return response.json()

        # Automatic retry with backoff
        data = await self._request_with_retry(do_request, "search")
        return [self._parse_evidence(item) for item in data["results"]]
```

**Retry behavior:**
- Retries on: timeout, network errors, 429 (rate limit), 5xx errors
- Does not retry: 4xx errors (except 429), parse errors, auth errors
- Respects `Retry-After` header when present
- Adds jitter to prevent thundering herd

### Circuit Breaker

```python
from aragora.resilience import get_circuit_breaker

# Get named circuit breaker
breaker = get_circuit_breaker("stripe_api")

# Check before request
if breaker.can_proceed():
    try:
        result = await api_call()
        breaker.record_success()
    except Exception:
        breaker.record_failure()
        raise
else:
    # Circuit is open - fail fast
    cooldown = breaker.cooldown_remaining()
    raise ConnectorCircuitOpenError(f"Circuit open, {cooldown:.1f}s remaining")
```

### Recovery Strategies

```python
from aragora.connectors.recovery import (
    RecoveryStrategy,
    RecoveryConfig,
    with_recovery,
    create_recovery_chain,
)

# Define recovery config
config = RecoveryConfig(
    strategy=RecoveryStrategy.EXPONENTIAL_BACKOFF,
    max_retries=3,
    base_delay=1.0,
)

# Apply recovery to a function
@with_recovery(config)
async def fetch_data():
    return await connector.search("query")

# Chain multiple strategies
recovery_chain = create_recovery_chain([
    RecoveryConfig(strategy=RecoveryStrategy.RETRY_ONCE),
    RecoveryConfig(strategy=RecoveryStrategy.FALLBACK, fallback_value=[]),
])
```

### Cache with TTL

BaseConnector includes LRU cache with TTL:

```python
class MyConnector(BaseConnector):
    def __init__(self, ...):
        super().__init__(
            max_cache_entries=500,
            cache_ttl_seconds=3600.0,  # 1 hour
        )

    async def fetch(self, evidence_id: str) -> Evidence | None:
        # Check cache first
        cached = self._cache_get(evidence_id)
        if cached:
            return cached

        # Fetch from API
        evidence = await self._fetch_from_api(evidence_id)

        # Store in cache
        if evidence:
            self._cache_put(evidence_id, evidence)

        return evidence

    def get_cache_stats(self) -> dict:
        return self._cache_stats()
```

---

## Creating a New Connector

### 1. Choose the Pattern

**Use BaseConnector if:**
- Fetching evidence for debates
- Need provenance tracking
- Source provides search/fetch interface

**Use Integration Pattern if:**
- Bidirectional data sync
- Complex CRUD operations
- OAuth/webhook handling

### 2. Define Credentials

```python
# aragora/connectors/myservice/credentials.py

@dataclass
class MyServiceCredentials:
    api_key: str
    webhook_secret: str | None = None
    base_url: str = "https://api.myservice.com"
```

### 3. Define Response Models

```python
# aragora/connectors/myservice/models.py

@dataclass
class MyResource:
    id: str
    name: str
    created_at: datetime | None = None

    @classmethod
    def from_api(cls, data: dict) -> "MyResource":
        return cls(
            id=data["id"],
            name=data["name"],
            created_at=_parse_datetime(data.get("created_at")),
        )
```

### 4. Implement the Connector

```python
# aragora/connectors/myservice/connector.py

class MyServiceConnector:
    """Connector for MyService API."""

    BASE_URL = "https://api.myservice.com/v1"

    def __init__(self, credentials: MyServiceCredentials):
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "MyServiceConnector":
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {self.credentials.api_key}"},
            timeout=30.0,
        )
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()

    async def list_resources(self, limit: int = 100) -> list[MyResource]:
        """List resources."""
        response = await self._client.get(
            f"{self.BASE_URL}/resources",
            params={"limit": limit},
        )
        response.raise_for_status()
        return [MyResource.from_api(r) for r in response.json()["data"]]
```

### 5. Export from Package

```python
# aragora/connectors/myservice/__init__.py

from .connector import MyServiceConnector
from .credentials import MyServiceCredentials
from .models import MyResource

__all__ = [
    "MyServiceConnector",
    "MyServiceCredentials",
    "MyResource",
]
```

### 6. Add Tests

```python
# tests/connectors/test_myservice.py

import pytest
from aragora.connectors.myservice import MyServiceConnector, MyServiceCredentials

@pytest.fixture
def credentials():
    return MyServiceCredentials(api_key="test_key")

class TestMyServiceConnector:
    async def test_list_resources(self, credentials, httpx_mock):
        httpx_mock.add_response(
            url="https://api.myservice.com/v1/resources",
            json={"data": [{"id": "1", "name": "Test"}]},
        )

        async with MyServiceConnector(credentials) as connector:
            resources = await connector.list_resources()
            assert len(resources) == 1
            assert resources[0].name == "Test"
```

---

## File Locations

| What | Where |
|------|-------|
| Base connector | `aragora/connectors/base.py` |
| Exceptions | `aragora/connectors/exceptions.py` |
| Credentials | `aragora/connectors/credentials/` |
| Recovery | `aragora/connectors/recovery.py` |
| Evidence connectors | `aragora/connectors/*.py` |
| Integration connectors | `aragora/connectors/{domain}/*.py` |
| Tests | `tests/connectors/` |

---

*Last updated: 2026-01-30*
