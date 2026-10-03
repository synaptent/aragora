"""
Aragora Python SDK Client.

Provides a type-safe interface for interacting with the Aragora API.

Usage:
    from aragora.client import AragoraClient

    # Synchronous usage
    client = AragoraClient(base_url="http://localhost:8080")
    debate = client.debates.create(task="Should we use microservices?")
    result = client.debates.get(debate.debate_id)

    # Async usage
    async with AragoraClient(base_url="http://localhost:8080") as client:
        debate = await client.debates.create_async(task="...")
        result = await client.debates.get_async(debate.debate_id)

    # With retry and rate limiting
    from aragora.client import AragoraClient, RetryConfig
    client = AragoraClient(
        base_url="http://localhost:8080",
        retry_config=RetryConfig(max_retries=3, backoff_factor=0.5),
        rate_limit_rps=10,
    )

    # Batch fetching
    debates = await client.debates.batch_get_async(["id1", "id2", "id3"])

    # Pagination
    async for debate in client.debates.iterate_async(status="completed"):
        print(debate.task)
"""

from __future__ import annotations

import json
import logging
import time as time_module
import urllib.error
import urllib.parse
import urllib.request
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import urljoin

from aragora.config import DEFAULT_ROUNDS

# Import from refactored modules
from .errors import (
    AragoraAPIError,
    AuthenticationError,
    NotFoundError,
    QuotaExceededError,
    RateLimitError,
    ValidationError,
)
from .transport import RateLimiter, RetryConfig
from .resources import (
    AgentsAPI,
    AnalyticsAPI,
    AuditAPI,
    AuthAPI,
    BillingAPI,
    CodebaseAPI,
    ConsensusAPI,
    CostManagementAPI,
    DebatesAPI,
    DecisionsAPI,
    DocumentsAPI,
    ExplainabilityAPI,
    GauntletAPI,
    GmailAPI,
    GraphDebatesAPI,
    KnowledgeAPI,
    LeaderboardAPI,
    MatrixDebatesAPI,
    MemoryAPI,
    NomicAPI,
    NotificationsAPI,
    OnboardingAPI,
    OpenClawAPI,
    OrganizationsAPI,
    PoliciesAPI,
    PulseAPI,
    RBACAPI,
    ReplayAPI,
    SystemAPI,
    TenantsAPI,
    TournamentsAPI,
    VerticalsAPI,
    VerificationAPI,
    WorkflowsAPI,
)
from .models import (
    HealthCheck,
)

if TYPE_CHECKING:
    import aiohttp

logger = logging.getLogger(__name__)

# GauntletAPI, GraphDebatesAPI, MatrixDebatesAPI, ReplayAPI are imported from resources


class AragoraClient:
    """
    Aragora API client.

    Provides synchronous and asynchronous access to the Aragora API.

    Available API interfaces:
        - debates: Standard debates (create, get, list, run)
        - graph_debates: Graph-structured debates with branching
        - matrix_debates: Parallel scenario debates
        - documents: Document management, batch processing, and auditing
        - audit: Enterprise audit features (presets, workflow, quick audit)
        - verification: Formal claim verification
        - memory: Memory tier analytics
        - nomic: Nomic loop monitoring and control
        - agents: Agent discovery and profiles
        - leaderboard: ELO rankings
        - gauntlet: Adversarial validation
        - replays: Debate replay viewing and export
        - consensus: Consensus memory, settled topics, and dissent tracking
        - pulse: Trending topics and debate suggestions
        - system: System health, stats, and circuit breaker management
        - tournaments: Agent tournament creation and management
        - billing: Subscription and usage management
        - rbac: Role-based access control
        - auth: Authentication and MFA management
        - knowledge: Knowledge Mound search and management
        - workflows: Workflow creation and execution
        - organizations: Multi-tenant organization management
        - tenants: Tenant isolation and settings
        - codebase: Codebase analysis integration
        - policies: Compliance policy management
        - explainability: Decision explanations and counterfactuals
        - cost_management: Usage tracking and budget management
        - notifications: Notification preferences and history
        - decisions: Unified decision-making API
        - onboarding: User onboarding flows
        - gmail: Gmail connector integration
        - verticals: Vertical specialist configuration and tooling

    Usage:
        # Synchronous
        client = AragoraClient(base_url="http://localhost:8080")
        debate = client.debates.run(task="Should we use microservices?")

        # Graph debate with branching
        result = client.graph_debates.create(task="Design a distributed system")

        # Matrix debate with scenarios
        result = client.matrix_debates.create(
            task="Should we adopt microservices?",
            scenarios=[
                {"name": "small team", "parameters": {"team_size": 5}},
                {"name": "large team", "parameters": {"team_size": 50}},
            ]
        )

        # Verify a claim
        result = client.verification.verify(claim="All primes > 2 are odd")

        # Memory analytics
        analytics = client.memory.analytics(days=30)

        # Asynchronous
        async with AragoraClient(base_url="http://localhost:8080") as client:
            debate = await client.debates.run_async(task="...")
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: str | None = None,
        timeout: int = 60,
        retry_config: RetryConfig | None = None,
        rate_limit_rps: float = 0,
    ):
        """
        Initialize the Aragora client.

        Args:
            base_url: Base URL of the Aragora API server.
            api_key: Optional API key for authentication.
            timeout: Request timeout in seconds.
            retry_config: Optional retry configuration for resilient requests.
            rate_limit_rps: Client-side rate limit in requests per second (0 = disabled).
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retry_config = retry_config
        self._rate_limiter = RateLimiter(rate_limit_rps) if rate_limit_rps > 0 else None

        # Lazy-loaded HTTP clients
        self._session: aiohttp.ClientSession | None = None
        self._sync_client: Any = None

        # API interfaces
        self.debates = DebatesAPI(self)
        self.agents = AgentsAPI(self)
        self.leaderboard = LeaderboardAPI(self)
        self.gauntlet = GauntletAPI(self)

        # Extended API interfaces
        self.graph_debates = GraphDebatesAPI(self)
        self.matrix_debates = MatrixDebatesAPI(self)
        self.verification = VerificationAPI(self)
        self.memory = MemoryAPI(self)
        self.nomic = NomicAPI(self)
        self.replays = ReplayAPI(self)

        # Document management and auditing
        self.documents = DocumentsAPI(self)

        # Enterprise audit features (presets, workflow, quick audit)
        self.audit = AuditAPI(self)

        # Consensus memory and dissent tracking
        self.consensus = ConsensusAPI(self)

        # Trending topics and debate suggestions
        self.pulse = PulseAPI(self)

        # System health and status
        self.system = SystemAPI(self)

        # Agent tournaments
        self.tournaments = TournamentsAPI(self)

        # Analytics (disagreements, role rotation, early stops, consensus quality)
        self.analytics = AnalyticsAPI(self)

        # Billing and subscription management
        self.billing = BillingAPI(self)

        # Role-Based Access Control
        self.rbac = RBACAPI(self)

        # Authentication and MFA
        self.auth = AuthAPI(self)

        # Knowledge Mound
        self.knowledge = KnowledgeAPI(self)

        # Workflows
        self.workflows = WorkflowsAPI(self)

        # Organizations (multi-tenant management)
        self.organizations = OrganizationsAPI(self)

        # Tenants (tenant isolation and settings)
        self.tenants = TenantsAPI(self)

        # Codebase analysis
        self.codebase = CodebaseAPI(self)

        # Compliance policies
        self.policies = PoliciesAPI(self)

        # Decision explainability
        self.explainability = ExplainabilityAPI(self)

        # Cost management
        self.cost_management = CostManagementAPI(self)

        # Notifications
        self.notifications = NotificationsAPI(self)

        # Unified decisions API
        self.decisions = DecisionsAPI(self)

        # User onboarding
        self.onboarding = OnboardingAPI(self)

        # Gmail connector
        self.gmail = GmailAPI(self)

        # Verticals
        self.verticals = VerticalsAPI(self)

        # OpenClaw Enterprise Gateway
        self.openclaw = OpenClawAPI(self)

    def _get_headers(self) -> dict[str, str]:
        """Get common request headers."""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _get(self, path: str, params: dict | None = None) -> dict:
        """Make a synchronous GET request with retry and rate limiting."""
        url = urljoin(self.base_url, path)
        if params:
            query = urllib.parse.urlencode(params)
            delimiter = "&" if "?" in url else "?"
            url = f"{url}{delimiter}{query}"
        last_error: Exception | None = None
        max_attempts = (self.retry_config.max_retries + 1) if self.retry_config else 1

        for attempt in range(max_attempts):
            # Apply rate limiting
            if self._rate_limiter:
                self._rate_limiter.wait()

            try:
                req = urllib.request.Request(  # noqa: S310 -- SDK client, base_url from config
                    url,
                    method="GET",
                    headers=self._get_headers(),
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 -- SDK client, base_url from config
                    body = resp.read() or b"{}"
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                last_error = e
                status_code = getattr(e, "code", 0)
                if self.retry_config and status_code in self.retry_config.retry_statuses:
                    if attempt < max_attempts - 1:
                        delay = self.retry_config.get_delay(attempt)
                        logger.debug(
                            f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (HTTP {status_code})"
                        )
                        time_module.sleep(delay)
                        continue
                self._handle_http_error(e)
            except urllib.error.URLError as e:
                last_error = e
                if self.retry_config and attempt < max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (connection error)"
                    )
                    time_module.sleep(delay)
                    continue
                logger.debug("GET connection error: %s", e)
                raise AragoraAPIError("Connection error", "CONNECTION_ERROR", 0) from e

        # Should not reach here, but handle gracefully
        if last_error:
            logger.debug("GET retries exhausted: %s", last_error)
            raise AragoraAPIError(
                "Request failed after retries", "RETRY_EXHAUSTED", 0
            ) from last_error
        raise AragoraAPIError("Request failed after retries", "RETRY_EXHAUSTED", 0)

    def _post(
        self,
        path: str,
        data: dict | None = None,
        headers: dict | None = None,
        json: dict | None = None,
    ) -> dict:
        """Make a synchronous POST request with retry and rate limiting."""
        import json as json_module

        if json is not None:
            if data is not None:
                raise ValueError("Provide either data or json, not both")
            data = json
        if data is None:
            data = {}
        url = urljoin(self.base_url, path)
        request_headers = self._get_headers()
        if headers:
            request_headers.update(headers)

        last_error: Exception | None = None
        max_attempts = (self.retry_config.max_retries + 1) if self.retry_config else 1

        for attempt in range(max_attempts):
            # Apply rate limiting
            if self._rate_limiter:
                self._rate_limiter.wait()

            try:
                payload = json_module.dumps(data).encode("utf-8")
                req = urllib.request.Request(  # noqa: S310 -- SDK client, base_url from config
                    url,
                    data=payload,
                    method="POST",
                    headers=request_headers,
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 -- SDK client, base_url from config
                    body = resp.read() or b"{}"
                    return json_module.loads(body)
            except urllib.error.HTTPError as e:
                last_error = e
                status_code = getattr(e, "code", 0)
                if self.retry_config and status_code in self.retry_config.retry_statuses:
                    if attempt < max_attempts - 1:
                        delay = self.retry_config.get_delay(attempt)
                        logger.debug(
                            f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (HTTP {status_code})"
                        )
                        time_module.sleep(delay)
                        continue
                self._handle_http_error(e)
            except urllib.error.URLError as e:
                last_error = e
                if self.retry_config and attempt < max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (connection error)"
                    )
                    time_module.sleep(delay)
                    continue
                logger.debug("POST connection error: %s", e)
                raise AragoraAPIError("Connection error", "CONNECTION_ERROR", 0) from e

        # Should not reach here, but handle gracefully
        if last_error:
            logger.debug("POST retries exhausted: %s", last_error)
            raise AragoraAPIError(
                "Request failed after retries", "RETRY_EXHAUSTED", 0
            ) from last_error
        raise AragoraAPIError("Request failed after retries", "RETRY_EXHAUSTED", 0)

    def _delete(self, path: str, params: dict | None = None) -> dict:
        """Make a synchronous DELETE request with retry and rate limiting."""
        url = urljoin(self.base_url, path)
        if params:
            query = urllib.parse.urlencode(params)
            delimiter = "&" if "?" in url else "?"
            url = f"{url}{delimiter}{query}"
        last_error: Exception | None = None
        max_attempts = (self.retry_config.max_retries + 1) if self.retry_config else 1

        for attempt in range(max_attempts):
            # Apply rate limiting
            if self._rate_limiter:
                self._rate_limiter.wait()

            try:
                req = urllib.request.Request(  # noqa: S310 -- SDK client, base_url from config
                    url,
                    method="DELETE",
                    headers=self._get_headers(),
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 -- SDK client, base_url from config
                    body = resp.read() or b"{}"
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                last_error = e
                status_code = getattr(e, "code", 0)
                if self.retry_config and status_code in self.retry_config.retry_statuses:
                    if attempt < max_attempts - 1:
                        delay = self.retry_config.get_delay(attempt)
                        logger.debug(
                            f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (HTTP {status_code})"
                        )
                        time_module.sleep(delay)
                        continue
                self._handle_http_error(e)
            except urllib.error.URLError as e:
                last_error = e
                if self.retry_config and attempt < max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (connection error)"
                    )
                    time_module.sleep(delay)
                    continue
                logger.debug("DELETE connection error: %s", e)
                raise AragoraAPIError("Connection error", "CONNECTION_ERROR", 0) from e

        # Should not reach here, but handle gracefully
        if last_error:
            logger.debug("DELETE retries exhausted: %s", last_error)
            raise AragoraAPIError(
                "Request failed after retries", "RETRY_EXHAUSTED", 0
            ) from last_error
        raise AragoraAPIError("Request failed after retries", "RETRY_EXHAUSTED", 0)

    async def _delete_async(self, path: str, params: dict | None = None) -> dict:
        """Make an asynchronous DELETE request with retry and rate limiting."""
        import asyncio

        import aiohttp

        if self._session is None:
            self._session = aiohttp.ClientSession()

        url = urljoin(self.base_url, path)
        last_error: Exception | None = None
        max_attempts = (self.retry_config.max_retries + 1) if self.retry_config else 1

        for attempt in range(max_attempts):
            # Apply rate limiting
            if self._rate_limiter:
                await self._rate_limiter.wait_async()

            try:
                async with self._session.delete(
                    url,
                    headers=self._get_headers(),
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.json()
                        # Check if we should retry
                        if self.retry_config and resp.status in self.retry_config.retry_statuses:
                            if attempt < max_attempts - 1:
                                delay = self.retry_config.get_delay(attempt)
                                logger.debug(
                                    f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (HTTP {resp.status})"
                                )
                                await asyncio.sleep(delay)
                                continue
                        raise AragoraAPIError(
                            body.get("error", "Unknown error"),
                            body.get("code", "HTTP_ERROR"),
                            resp.status,
                        )
                    return await resp.json()
            except aiohttp.ClientError as e:
                last_error = e
                if self.retry_config and attempt < max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (connection error)"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.debug("DELETE async connection error: %s", e)
                raise AragoraAPIError("Connection error", "CONNECTION_ERROR", 0) from e

        # Should not reach here
        if last_error:
            logger.debug("DELETE async retries exhausted: %s", last_error)
        raise AragoraAPIError("Request failed after retries", "RETRY_EXHAUSTED", 0)

    def _put(self, path: str, data: dict, headers: dict | None = None) -> dict:
        """Make a synchronous PUT request with retry and rate limiting."""
        url = urljoin(self.base_url, path)
        request_headers = self._get_headers()
        if headers:
            request_headers.update(headers)

        last_error: Exception | None = None
        max_attempts = (self.retry_config.max_retries + 1) if self.retry_config else 1

        for attempt in range(max_attempts):
            # Apply rate limiting
            if self._rate_limiter:
                self._rate_limiter.wait()

            try:
                payload = json.dumps(data).encode("utf-8")
                req = urllib.request.Request(  # noqa: S310 -- SDK client, base_url from config
                    url,
                    data=payload,
                    method="PUT",
                    headers=request_headers,
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 -- SDK client, base_url from config
                    body = resp.read() or b"{}"
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                last_error = e
                status_code = getattr(e, "code", 0)
                if self.retry_config and status_code in self.retry_config.retry_statuses:
                    if attempt < max_attempts - 1:
                        delay = self.retry_config.get_delay(attempt)
                        logger.debug(
                            f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (HTTP {status_code})"
                        )
                        time_module.sleep(delay)
                        continue
                self._handle_http_error(e)
            except urllib.error.URLError as e:
                last_error = e
                if self.retry_config and attempt < max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (connection error)"
                    )
                    time_module.sleep(delay)
                    continue
                logger.debug("PUT connection error: %s", e)
                raise AragoraAPIError("Connection error", "CONNECTION_ERROR", 0) from e

        # Should not reach here, but handle gracefully
        if last_error:
            logger.debug("PUT retries exhausted: %s", last_error)
            raise AragoraAPIError(
                "Request failed after retries", "RETRY_EXHAUSTED", 0
            ) from last_error
        raise AragoraAPIError("Request failed after retries", "RETRY_EXHAUSTED", 0)

    async def _put_async(self, path: str, data: dict, headers: dict | None = None) -> dict:
        """Make an asynchronous PUT request with retry and rate limiting."""
        import asyncio

        import aiohttp

        if self._session is None:
            self._session = aiohttp.ClientSession()

        url = urljoin(self.base_url, path)
        request_headers = self._get_headers()
        if headers:
            request_headers.update(headers)

        last_error: Exception | None = None
        max_attempts = (self.retry_config.max_retries + 1) if self.retry_config else 1

        for attempt in range(max_attempts):
            # Apply rate limiting
            if self._rate_limiter:
                await self._rate_limiter.wait_async()

            try:
                async with self._session.put(
                    url,
                    headers=request_headers,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.json()
                        # Check if we should retry
                        if self.retry_config and resp.status in self.retry_config.retry_statuses:
                            if attempt < max_attempts - 1:
                                delay = self.retry_config.get_delay(attempt)
                                logger.debug(
                                    f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (HTTP {resp.status})"
                                )
                                await asyncio.sleep(delay)
                                continue
                        raise AragoraAPIError(
                            body.get("error", "Unknown error"),
                            body.get("code", "HTTP_ERROR"),
                            resp.status,
                        )
                    return await resp.json()
            except aiohttp.ClientError as e:
                last_error = e
                if self.retry_config and attempt < max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (connection error)"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.debug("PUT async connection error: %s", e)
                raise AragoraAPIError("Connection error", "CONNECTION_ERROR", 0) from e

        # Should not reach here
        if last_error:
            logger.debug("PUT async retries exhausted: %s", last_error)
        raise AragoraAPIError("Request failed after retries", "RETRY_EXHAUSTED", 0)

    def _patch(self, path: str, data: dict, headers: dict | None = None) -> dict:
        """Make a synchronous PATCH request with retry and rate limiting."""
        url = urljoin(self.base_url, path)
        request_headers = self._get_headers()
        if headers:
            request_headers.update(headers)

        last_error: Exception | None = None
        max_attempts = (self.retry_config.max_retries + 1) if self.retry_config else 1

        for attempt in range(max_attempts):
            # Apply rate limiting
            if self._rate_limiter:
                self._rate_limiter.wait()

            try:
                payload = json.dumps(data).encode("utf-8")
                req = urllib.request.Request(  # noqa: S310 -- SDK client, base_url from config
                    url,
                    data=payload,
                    method="PATCH",
                    headers=request_headers,
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 -- SDK client, base_url from config
                    body = resp.read() or b"{}"
                    return json.loads(body)
            except urllib.error.HTTPError as e:
                last_error = e
                status_code = getattr(e, "code", 0)
                if self.retry_config and status_code in self.retry_config.retry_statuses:
                    if attempt < max_attempts - 1:
                        delay = self.retry_config.get_delay(attempt)
                        logger.debug(
                            f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (HTTP {status_code})"
                        )
                        time_module.sleep(delay)
                        continue
                self._handle_http_error(e)
            except urllib.error.URLError as e:
                last_error = e
                if self.retry_config and attempt < max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (connection error)"
                    )
                    time_module.sleep(delay)
                    continue
                logger.debug("PATCH connection error: %s", e)
                raise AragoraAPIError("Connection error", "CONNECTION_ERROR", 0) from e

        # Should not reach here, but handle gracefully
        if last_error:
            logger.debug("PATCH retries exhausted: %s", last_error)
            raise AragoraAPIError(
                "Request failed after retries", "RETRY_EXHAUSTED", 0
            ) from last_error
        raise AragoraAPIError("Request failed after retries", "RETRY_EXHAUSTED", 0)

    async def _patch_async(self, path: str, data: dict, headers: dict | None = None) -> dict:
        """Make an asynchronous PATCH request with retry and rate limiting."""
        import asyncio

        import aiohttp

        if self._session is None:
            self._session = aiohttp.ClientSession()

        url = urljoin(self.base_url, path)
        request_headers = self._get_headers()
        if headers:
            request_headers.update(headers)

        last_error: Exception | None = None
        max_attempts = (self.retry_config.max_retries + 1) if self.retry_config else 1

        for attempt in range(max_attempts):
            # Apply rate limiting
            if self._rate_limiter:
                await self._rate_limiter.wait_async()

            try:
                async with self._session.patch(
                    url,
                    headers=request_headers,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.json()
                        # Check if we should retry
                        if self.retry_config and resp.status in self.retry_config.retry_statuses:
                            if attempt < max_attempts - 1:
                                delay = self.retry_config.get_delay(attempt)
                                logger.debug(
                                    f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (HTTP {resp.status})"
                                )
                                await asyncio.sleep(delay)
                                continue
                        raise AragoraAPIError(
                            body.get("error", "Unknown error"),
                            body.get("code", "HTTP_ERROR"),
                            resp.status,
                        )
                    return await resp.json()
            except aiohttp.ClientError as e:
                last_error = e
                if self.retry_config and attempt < max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (connection error)"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.debug("PATCH async connection error: %s", e)
                raise AragoraAPIError("Connection error", "CONNECTION_ERROR", 0) from e

        # Should not reach here
        if last_error:
            logger.debug("PATCH async retries exhausted: %s", last_error)
        raise AragoraAPIError("Request failed after retries", "RETRY_EXHAUSTED", 0)

    def _handle_http_error(self, e: Any) -> NoReturn:
        """Handle HTTP errors with specific error classes."""
        try:
            body = json.loads(e.read().decode())
            error_msg = body.get("error", "Request failed")
            error_code = body.get("code", "HTTP_ERROR")
        except (ValueError, KeyError, UnicodeDecodeError, AttributeError) as parse_err:
            # Failed to parse error response body - use generic message
            logger.debug("Could not parse HTTP error body: %s (original: %s)", parse_err, e)
            error_msg = "Request failed"
            error_code = "HTTP_ERROR"

        # Map HTTP status codes to specific error classes
        status_code = getattr(e, "code", 500)
        if status_code == 401:
            raise AuthenticationError(error_msg)
        elif status_code == 402:
            raise QuotaExceededError(error_msg)
        elif status_code == 404:
            raise NotFoundError(error_msg)
        elif status_code == 429:
            raise RateLimitError(error_msg)
        elif status_code == 400:
            raise ValidationError(error_msg)
        else:
            raise AragoraAPIError(error_msg, error_code, status_code)

    def _handle_httpx_error(self, resp: Any) -> NoReturn:
        """Handle httpx response errors with specific error classes."""
        try:
            body = resp.json()
            error_msg = body.get("error", resp.text)
            error_code = body.get("code", "HTTP_ERROR")
        except (ValueError, KeyError, AttributeError) as parse_err:
            # Failed to parse error response body - use raw error
            logger.debug("Could not parse HTTP error body: %s", parse_err)
            error_msg = resp.text
            error_code = "HTTP_ERROR"

        # Map HTTP status codes to specific error classes
        status_code = resp.status_code
        if status_code == 401:
            raise AuthenticationError(error_msg)
        elif status_code == 402:
            raise QuotaExceededError(error_msg)
        elif status_code == 404:
            raise NotFoundError(error_msg)
        elif status_code == 429:
            raise RateLimitError(error_msg)
        elif status_code == 400:
            raise ValidationError(error_msg)
        else:
            raise AragoraAPIError(error_msg, error_code, status_code)

    async def _get_async(self, path: str, params: dict | None = None) -> dict:
        """Make an asynchronous GET request with retry and rate limiting."""
        import asyncio

        import aiohttp

        if self._session is None:
            self._session = aiohttp.ClientSession()

        url = urljoin(self.base_url, path)
        last_error: Exception | None = None
        max_attempts = (self.retry_config.max_retries + 1) if self.retry_config else 1

        for attempt in range(max_attempts):
            # Apply rate limiting
            if self._rate_limiter:
                await self._rate_limiter.wait_async()

            try:
                async with self._session.get(
                    url,
                    headers=self._get_headers(),
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.json()
                        # Check if we should retry
                        if self.retry_config and resp.status in self.retry_config.retry_statuses:
                            if attempt < max_attempts - 1:
                                delay = self.retry_config.get_delay(attempt)
                                logger.debug(
                                    f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (HTTP {resp.status})"
                                )
                                await asyncio.sleep(delay)
                                continue
                        raise AragoraAPIError(
                            body.get("error", "Unknown error"),
                            body.get("code", "HTTP_ERROR"),
                            resp.status,
                        )
                    return await resp.json()
            except aiohttp.ClientError as e:
                last_error = e
                if self.retry_config and attempt < max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (connection error)"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.debug("GET async connection error: %s", e)
                raise AragoraAPIError("Connection error", "CONNECTION_ERROR", 0) from e

        # Should not reach here
        logger.debug("GET async retries exhausted: %s", last_error)
        raise AragoraAPIError("Request failed after retries", "RETRY_EXHAUSTED", 0) from last_error

    async def _post_async(
        self,
        path: str,
        data: dict | None = None,
        headers: dict | None = None,
        json: dict | None = None,
    ) -> dict:
        """Make an asynchronous POST request with retry and rate limiting."""
        import asyncio

        import aiohttp

        if json is not None:
            if data is not None:
                raise ValueError("Provide either data or json, not both")
            data = json
        if data is None:
            data = {}

        if self._session is None:
            self._session = aiohttp.ClientSession()

        url = urljoin(self.base_url, path)
        request_headers = self._get_headers()
        if headers:
            request_headers.update(headers)

        last_error: Exception | None = None
        max_attempts = (self.retry_config.max_retries + 1) if self.retry_config else 1

        for attempt in range(max_attempts):
            # Apply rate limiting
            if self._rate_limiter:
                await self._rate_limiter.wait_async()

            try:
                async with self._session.post(
                    url,
                    headers=request_headers,
                    json=data,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.json()
                        # Check if we should retry
                        if self.retry_config and resp.status in self.retry_config.retry_statuses:
                            if attempt < max_attempts - 1:
                                delay = self.retry_config.get_delay(attempt)
                                logger.debug(
                                    f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (HTTP {resp.status})"
                                )
                                await asyncio.sleep(delay)
                                continue
                        raise AragoraAPIError(
                            body.get("error", "Unknown error"),
                            body.get("code", "HTTP_ERROR"),
                            resp.status,
                        )
                    return await resp.json()
            except aiohttp.ClientError as e:
                last_error = e
                if self.retry_config and attempt < max_attempts - 1:
                    delay = self.retry_config.get_delay(attempt)
                    logger.debug(
                        f"Retry {attempt + 1}/{max_attempts} after {delay:.2f}s (connection error)"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.debug("POST async connection error: %s", e)
                raise AragoraAPIError("Connection error", "CONNECTION_ERROR", 0) from e

        # Should not reach here
        logger.debug("POST async retries exhausted: %s", last_error)
        raise AragoraAPIError("Request failed after retries", "RETRY_EXHAUSTED", 0) from last_error

    def health(self) -> HealthCheck:
        """Check API health."""
        response = self._get("/api/health")
        return HealthCheck(**response)

    async def health_async(self) -> HealthCheck:
        """Async version of health()."""
        response = await self._get_async("/api/health")
        return HealthCheck(**response)

    async def stream_debate(self, debate_id: str, options: Any | None = None):
        """
        Stream events for a specific debate.

        This is a convenience method that creates a WebSocket connection
        and yields events for the specified debate.

        Args:
            debate_id: The ID of the debate to stream
            options: Optional WebSocketOptions for connection configuration

        Yields:
            DebateEvent objects for each event from the debate

        Example:
            async for event in client.stream_debate("debate-123"):
                print(f"{event.type}: {event.data}")
                if event.type == DebateEventType.DEBATE_END:
                    break
        """
        from aragora.client.websocket import stream_debate

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        async for event in stream_debate(
            base_url=ws_url,
            debate_id=debate_id,
            options=options,
        ):
            yield event

    async def stream_all_debates(self, options: Any | None = None):
        """
        Stream events for all debates (no filter).

        This is a convenience method for monitoring all debate activity
        on the server.

        Args:
            options: Optional WebSocketOptions for connection configuration

        Yields:
            DebateEvent objects for events from all debates

        Example:
            async for event in client.stream_all_debates():
                print(f"[{event.debate_id}] {event.type}: {event.data}")
        """
        from aragora.client.websocket import stream_debate

        ws_url = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        async for event in stream_debate(
            base_url=ws_url,
            debate_id="",  # Empty string means no filter
            options=options,
        ):
            yield event

    async def create_debate_and_stream(
        self,
        task: str,
        agents: list,
        rounds: int = DEFAULT_ROUNDS,
        stream_options: Any | None = None,
        **kwargs: Any,
    ):
        """
        Create a debate and immediately start streaming its events.

        This is a convenience method that combines debate creation with
        event streaming for a streamlined workflow.

        Args:
            task: The debate topic/question
            agents: List of agent IDs to participate
            rounds: Number of debate rounds (default: 3)
            stream_options: Optional WebSocketOptions for connection configuration
            **kwargs: Additional arguments passed to debates.create_async()

        Returns:
            Tuple of (debate_response, event_stream)

        Example:
            debate, stream = await client.create_debate_and_stream(
                task="Should we use microservices?",
                agents=["claude", "gpt-4"],
            )
            print(f"Created debate: {debate['debate_id']}")
            async for event in stream:
                print(f"{event.type}: {event.data}")
        """
        # Create the debate first
        debate = await self.debates.create_async(
            task=task,
            agents=agents,
            rounds=rounds,
            **kwargs,
        )

        # Extract debate_id from response (may be DebateCreateResponse or dict)
        debate_id: str | None
        if hasattr(debate, "debate_id"):
            debate_id = debate.debate_id
        else:
            debate_id = debate.get("debate_id") if isinstance(debate, dict) else None
        if not debate_id:
            raise ValueError("No debate_id in create_debate response")

        # Return debate and stream
        stream = self.stream_debate(debate_id, stream_options)
        return debate, stream

    def __enter__(self) -> AragoraClient:
        """Sync context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Sync context manager exit."""
        self.close()

    async def __aenter__(self) -> AragoraClient:
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close_async()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        """Generic synchronous request helper for SDK namespaces."""
        verb = method.upper()
        if verb == "GET":
            return self._get(path, params=params)
        if verb == "POST":
            return self._post(path, json or {}, headers=headers)
        if verb == "PUT":
            return self._put(path, json or {}, headers=headers)
        if verb == "PATCH":
            return self._patch(path, json or {}, headers=headers)
        if verb == "DELETE":
            return self._delete(path, params=params)
        raise ValueError(f"Unsupported HTTP method: {method}")

    async def close_async(self) -> None:
        """Close async HTTP session."""
        if self._session:
            await self._session.close()
            self._session = None

    def close(self) -> None:
        """Close any open resources."""
        # Sync client cleanup if needed
        self._sync_client = None


class AragoraAsyncClient(AragoraClient):
    """Compatibility alias for async-first client usage."""

    async def request(  # type: ignore[override]  # intentionally async; parent is sync
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        headers: dict | None = None,
    ) -> dict:
        """Generic async request helper for SDK namespaces."""
        verb = method.upper()
        if verb == "GET":
            return await self._get_async(path, params=params)
        if verb == "POST":
            return await self._post_async(path, json or {}, headers=headers)
        if verb == "PUT":
            return await self._put_async(path, json or {}, headers=headers)
        if verb == "PATCH":
            return await self._patch_async(path, json or {}, headers=headers)
        if verb == "DELETE":
            return await self._delete_async(path, params=params)
        raise ValueError(f"Unsupported HTTP method: {method}")
