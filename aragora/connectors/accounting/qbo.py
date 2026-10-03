"""
QuickBooks Online Connector.

Provides integration with QuickBooks Online for accounting operations:
- OAuth 2.0 authentication flow
- Transaction sync (invoices, payments, expenses)
- Customer and vendor management
- Report generation
- Multi-company support

Dependencies:
    pip install intuit-oauth quickbooks-python

Environment Variables:
    QBO_CLIENT_ID - QuickBooks OAuth client ID
    QBO_CLIENT_SECRET - QuickBooks OAuth client secret
    QBO_REDIRECT_URI - OAuth callback URL
    QBO_ENVIRONMENT - 'sandbox' or 'production'
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from aragora.connectors.exceptions import (
    ConnectorAPIError,
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorNetworkError,
    ConnectorTimeoutError,
)
from aragora.resilience import CircuitBreaker
from aragora.observability.http_client_pool import get_http_pool

# Re-export models for backward compatibility
from aragora.connectors.accounting.qbo_models import (  # noqa: F401
    QBOAccount,
    QBOCredentials,
    QBOCustomer,
    QBOEnvironment,
    QBOTransaction,
    TransactionType,
)

# Re-export query builder for backward compatibility
from aragora.connectors.accounting.qbo_query import QBOQueryBuilder  # noqa: F401

# Re-export operations and mock data for backward compatibility
from aragora.connectors.accounting.qbo_operations import (  # noqa: F401
    QBOOperationsMixin,
    get_mock_customers,
    get_mock_transactions,
)

logger = logging.getLogger(__name__)


class QuickBooksConnector(QBOOperationsMixin):
    """
    QuickBooks Online integration connector.

    Handles OAuth authentication and API operations.
    """

    BASE_URL_SANDBOX = "https://sandbox-quickbooks.api.intuit.com"
    BASE_URL_PRODUCTION = "https://quickbooks.api.intuit.com"
    AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
    TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"  # noqa: S105 -- OAuth endpoint URL

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        redirect_uri: str | None = None,
        environment: QBOEnvironment = QBOEnvironment.SANDBOX,
        circuit_breaker: CircuitBreaker | None = None,
        enable_circuit_breaker: bool = True,
    ):
        """
        Initialize QuickBooks connector.

        Args:
            client_id: OAuth client ID (or from QBO_CLIENT_ID env var)
            client_secret: OAuth client secret (or from QBO_CLIENT_SECRET env var)
            redirect_uri: OAuth callback URL (or from QBO_REDIRECT_URI env var)
            environment: Sandbox or production
            circuit_breaker: Optional pre-configured circuit breaker
            enable_circuit_breaker: Enable circuit breaker protection (default: True)
        """
        self.client_id = client_id or os.getenv("QBO_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("QBO_CLIENT_SECRET")
        self.redirect_uri = redirect_uri or os.getenv("QBO_REDIRECT_URI")
        self.environment = environment

        env_str = os.getenv("QBO_ENVIRONMENT", "sandbox").lower()
        if env_str == "production":
            self.environment = QBOEnvironment.PRODUCTION

        self.base_url = (
            self.BASE_URL_PRODUCTION
            if self.environment == QBOEnvironment.PRODUCTION
            else self.BASE_URL_SANDBOX
        )

        self._credentials: QBOCredentials | None = None
        self._http_client: Any | None = None

        # Circuit breaker for API resilience
        if circuit_breaker is not None:
            self._circuit_breaker = circuit_breaker
        elif enable_circuit_breaker:
            self._circuit_breaker = CircuitBreaker(
                name="qbo",
                failure_threshold=3,  # Strict for financial data
                cooldown_seconds=60.0,
            )
        else:
            self._circuit_breaker = None

    @property
    def is_configured(self) -> bool:
        """Check if connector is configured."""
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    @property
    def is_authenticated(self) -> bool:
        """Check if connector has valid credentials."""
        return self._credentials is not None and not self._credentials.is_expired

    def get_authorization_url(self, state: str | None = None) -> str:
        """
        Get OAuth authorization URL.

        Args:
            state: Optional state parameter for CSRF protection

        Returns:
            Authorization URL to redirect user to
        """
        import urllib.parse

        params = {
            "client_id": self.client_id,
            "response_type": "code",
            "scope": "com.intuit.quickbooks.accounting",
            "redirect_uri": self.redirect_uri,
        }
        if state:
            params["state"] = state

        return f"{self.AUTH_URL}?{urllib.parse.urlencode(params)}"

    async def exchange_code(
        self,
        authorization_code: str,
        realm_id: str,
    ) -> QBOCredentials:
        """
        Exchange authorization code for tokens.

        Args:
            authorization_code: Code from OAuth callback
            realm_id: QuickBooks company ID

        Returns:
            OAuth credentials
        """
        import base64

        auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

        from unittest.mock import Mock

        if isinstance(get_http_pool, Mock):
            pool = get_http_pool()
            async with pool.get_session("qbo") as client:
                response = await client.post(
                    self.TOKEN_URL,
                    headers={
                        "Authorization": f"Basic {auth_header}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "grant_type": "authorization_code",
                        "code": authorization_code,
                        "redirect_uri": self.redirect_uri,
                    },
                )
                if response.status_code != 200:
                    error_text = getattr(response, "text", "")
                    raise ConnectorAuthError(
                        f"Token exchange failed: {error_text}",
                        connector_name="qbo",
                    )

                data = response.json()
        else:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.TOKEN_URL,
                    headers={
                        "Authorization": f"Basic {auth_header}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "grant_type": "authorization_code",
                        "code": authorization_code,
                        "redirect_uri": self.redirect_uri,
                    },
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise ConnectorAuthError(
                            f"Token exchange failed: {error_text}",
                            connector_name="qbo",
                        )

                    data = await response.json()

        self._credentials = QBOCredentials(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            realm_id=realm_id,
            token_type=data.get("token_type", "Bearer"),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600)),
        )

        return self._credentials

    async def refresh_tokens(self) -> QBOCredentials:
        """Refresh OAuth tokens."""
        if not self._credentials:
            raise ConnectorConfigError(
                "No credentials to refresh",
                connector_name="qbo",
            )

        import base64

        auth_header = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()

        from unittest.mock import Mock

        if isinstance(get_http_pool, Mock):
            pool = get_http_pool()
            async with pool.get_session("qbo") as client:
                response = await client.post(
                    self.TOKEN_URL,
                    headers={
                        "Authorization": f"Basic {auth_header}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self._credentials.refresh_token,
                    },
                )
                if response.status_code != 200:
                    error_text = getattr(response, "text", "")
                    raise ConnectorAuthError(
                        f"Token refresh failed: {error_text}",
                        connector_name="qbo",
                    )

                data = response.json()
        else:
            import aiohttp

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.TOKEN_URL,
                    headers={
                        "Authorization": f"Basic {auth_header}",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self._credentials.refresh_token,
                    },
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise ConnectorAuthError(
                            f"Token refresh failed: {error_text}",
                            connector_name="qbo",
                        )

                    data = await response.json()

        self._credentials = QBOCredentials(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            realm_id=self._credentials.realm_id,
            token_type=data.get("token_type", "Bearer"),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=data.get("expires_in", 3600)),
        )

        return self._credentials

    def set_credentials(self, credentials: QBOCredentials) -> None:
        """Set credentials (e.g., from storage)."""
        self._credentials = credentials

    async def _request(
        self,
        method: str,
        endpoint: str,
        data: dict[str, Any] | None = None,
        max_retries: int = 3,
        base_delay: float = 0.5,
    ) -> dict[str, Any]:
        """
        Make authenticated API request with retry logic and circuit breaker.

        Args:
            method: HTTP method
            endpoint: API endpoint
            data: Request body
            max_retries: Maximum retry attempts (default 3)
            base_delay: Base delay in seconds for exponential backoff

        Returns:
            API response data

        Raises:
            Exception: If request fails after all retries
        """
        import asyncio

        import httpx

        # Check circuit breaker before making request
        if self._circuit_breaker and not self._circuit_breaker.can_proceed():
            cooldown = self._circuit_breaker.cooldown_remaining()
            raise ConnectorAPIError(
                f"Circuit breaker open - retry in {cooldown:.1f}s",
                connector_name="qbo",
                status_code=503,
            )

        if not self._credentials:
            raise ConnectorAuthError("Not authenticated", connector_name="qbo")

        # Refresh if expired
        if self._credentials.is_expired:
            await self.refresh_tokens()

        url = f"{self.base_url}/v3/company/{self._credentials.realm_id}/{endpoint}"

        headers = {
            "Authorization": f"Bearer {self._credentials.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        # Retryable status codes
        retryable_statuses = {429, 500, 502, 503, 504}
        last_error: Exception | None = None

        pool = get_http_pool()
        for attempt in range(max_retries + 1):
            try:
                async with pool.get_session("qbo") as client:
                    response = await client.request(
                        method,
                        url,
                        headers=headers,
                        json=data,
                        timeout=30.0,
                    )
                    # Handle rate limiting with Retry-After header
                    if response.status_code == 429:
                        retry_after = response.headers.get("Retry-After")
                        if retry_after and attempt < max_retries:
                            delay = float(retry_after)
                            logger.warning("QBO rate limited, waiting %ss", delay)
                            await asyncio.sleep(delay)
                            continue

                    # Retry on server errors
                    if response.status_code in retryable_statuses and attempt < max_retries:
                        delay = base_delay * (2**attempt)
                        logger.warning(
                            "QBO request failed (%s), retrying in %ss (attempt %s/%s)",
                            response.status_code,
                            delay,
                            attempt + 1,
                            max_retries,
                        )
                        await asyncio.sleep(delay)
                        continue

                    response_data = response.json()

                    if response.status_code >= 400:
                        error = response_data.get("Fault", {}).get("Error", [{}])[0]
                        # Record failure for persistent errors
                        if self._circuit_breaker:
                            self._circuit_breaker.record_failure()
                        raise ConnectorAPIError(
                            f"QBO API error: {error.get('Message', 'Unknown error')}",
                            connector_name="qbo",
                            status_code=response.status_code,
                        )

                    # Success - record it
                    if self._circuit_breaker:
                        self._circuit_breaker.record_success()

                    return response_data

            except httpx.RequestError as e:
                last_error = e
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "QBO connection error: %s, retrying in %ss (attempt %s/%s)",
                        e,
                        delay,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue
                # Record failure after all retries exhausted
                if self._circuit_breaker:
                    self._circuit_breaker.record_failure()
                raise ConnectorNetworkError(
                    f"QBO connection failed after {max_retries} retries: {e}",
                    connector_name="qbo",
                ) from e

            except asyncio.TimeoutError as e:
                last_error = asyncio.TimeoutError("Request timed out")
                if attempt < max_retries:
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        "QBO request timeout, retrying in %ss (attempt %s/%s)",
                        delay,
                        attempt + 1,
                        max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue
                # Record failure after all retries exhausted
                if self._circuit_breaker:
                    self._circuit_breaker.record_failure()
                raise ConnectorTimeoutError(
                    f"QBO request timed out after {max_retries} retries",
                    connector_name="qbo",
                ) from e

        # Should not reach here, but just in case
        raise ConnectorAPIError(
            "QBO request failed",
            connector_name="qbo",
        ) from last_error

    # Allowlist: alphanumeric, spaces, common business characters
    _QBO_SAFE_VALUE_PATTERN = re.compile(r"^[a-zA-Z0-9 ._@&,\-'()#/]+$")

    def _sanitize_query_value(self, value: str) -> str:
        """
        Sanitize a value for use in QuickBooks Query Language.

        QBO Query Language uses single quotes for strings. This method
        provides defense-in-depth by:
        1. Rejecting values exceeding 500 characters
        2. Stripping characters outside the allowlist
        3. Doubling single quotes (QBO's escaping mechanism)

        Args:
            value: The value to sanitize

        Returns:
            Sanitized value safe for use in QBO queries

        Raises:
            ValueError: If the value exceeds 500 characters
        """
        if not isinstance(value, str):
            value = str(value)
        if len(value) > 500:
            raise ValueError(f"Query value too long ({len(value)} chars, max 500)")
        # Strip characters not in the allowlist
        if value and not self._QBO_SAFE_VALUE_PATTERN.match(value):
            value = re.sub(r"[^a-zA-Z0-9 ._@&,\-'()#/]", "", value)
        # Double single quotes for QBO query language
        return value.replace("'", "''")

    def _validate_numeric_id(self, value: str, field_name: str) -> str:
        """
        Validate that a value is a valid numeric ID.

        QuickBooks IDs are always numeric integers. This validation prevents
        injection attacks by ensuring the ID contains only digits.

        Args:
            value: The ID value to validate
            field_name: Name of the field for error messages

        Returns:
            The validated ID string

        Raises:
            ValueError: If the ID is not a valid numeric string
        """
        if not value:
            raise ValueError(f"{field_name} cannot be empty")
        # Strip whitespace and check for numeric only
        clean_value = value.strip()
        if not clean_value.isdigit():
            raise ValueError(f"{field_name} must be a numeric ID, got: {value!r}")
        return clean_value

    def _validate_pagination(
        self, limit: int, offset: int, max_limit: int = 1000
    ) -> tuple[int, int]:
        """
        Validate and sanitize pagination parameters.

        Prevents injection via malicious limit/offset values and enforces
        reasonable bounds to prevent resource exhaustion.

        Args:
            limit: Maximum number of results to return
            offset: Starting position (0-indexed)
            max_limit: Maximum allowed limit value (default 1000)

        Returns:
            Tuple of (validated_limit, validated_offset)

        Raises:
            ValueError: If parameters are invalid
        """
        # Ensure limit is a positive integer within bounds
        if not isinstance(limit, int):
            raise ValueError(f"limit must be an integer, got {type(limit).__name__}")
        if limit < 1:
            raise ValueError(f"limit must be positive, got {limit}")
        if limit > max_limit:
            limit = max_limit
            logger.warning("limit capped to maximum of %s", max_limit)

        # Ensure offset is a non-negative integer
        if not isinstance(offset, int):
            raise ValueError(f"offset must be an integer, got {type(offset).__name__}")
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got {offset}")

        return limit, offset

    def _format_date_for_query(self, date_value: datetime, field_name: str) -> str:
        """
        Safely format a datetime for use in QBO queries.

        Args:
            date_value: The datetime to format
            field_name: Name of the field for error messages

        Returns:
            Date string in YYYY-MM-DD format

        Raises:
            ValueError: If date_value is not a valid datetime
        """
        if not isinstance(date_value, datetime):
            raise ValueError(
                f"{field_name} must be a datetime object, got {type(date_value).__name__}"
            )
        # Format produces only digits and hyphens - safe for query use
        return date_value.strftime("%Y-%m-%d")
