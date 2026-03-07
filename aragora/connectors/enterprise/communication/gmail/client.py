"""
Gmail OAuth2 client and API request handling.

Provides authentication flow, token management, and base API request
infrastructure for the Gmail connector.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from aragora.reasoning.provenance import SourceType

logger = logging.getLogger(__name__)


class EnterpriseConnectorMethods(Protocol):
    """Protocol defining expected methods from EnterpriseConnector base class."""

    def check_circuit_breaker(self) -> bool: ...
    def get_circuit_breaker_status(self) -> dict[str, Any]: ...
    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...


# Gmail API scopes
# Note: gmail.metadata doesn't support search queries ('q' parameter)
# Using gmail.readonly alone is sufficient for read operations including search
GMAIL_SCOPES_READONLY = [
    "https://www.googleapis.com/auth/gmail.readonly",
]

# Full scopes including send (required for bidirectional email)
GMAIL_SCOPES_FULL = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.metadata",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Default to read-only for backward compatibility
GMAIL_SCOPES = GMAIL_SCOPES_READONLY
DEFAULT_REFRESH_TOKEN_PATH = Path.home() / ".aragora" / "gmail_refresh_token"


def _get_client_credentials() -> tuple[str, str]:
    """Get OAuth client ID and secret from environment."""
    client_id = (
        os.environ.get("GMAIL_CLIENT_ID")
        or os.environ.get("GOOGLE_GMAIL_CLIENT_ID")
        or os.environ.get("GOOGLE_CLIENT_ID", "")
    )
    client_secret = (
        os.environ.get("GMAIL_CLIENT_SECRET")
        or os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET")
        or os.environ.get("GOOGLE_CLIENT_SECRET", "")
    )
    return client_id, client_secret


def _load_refresh_token_fallback() -> str | None:
    """Load a Gmail refresh token from env or the local Aragora token file."""
    env_token = os.environ.get("GMAIL_REFRESH_TOKEN")
    if env_token:
        env_token = env_token.strip()
        if env_token:
            return env_token

    try:
        if DEFAULT_REFRESH_TOKEN_PATH.exists():
            token = DEFAULT_REFRESH_TOKEN_PATH.read_text(encoding="utf-8").strip()
            if token:
                return token
    except OSError:
        logger.debug("Failed reading Gmail refresh token fallback", exc_info=True)

    return None


class GmailClientMixin(EnterpriseConnectorMethods):
    """Mixin providing OAuth2 authentication and API request infrastructure."""

    # These attributes are expected to be set by the concrete class
    _access_token: str | None
    _refresh_token: str | None
    _token_expiry: datetime | None
    _token_lock: asyncio.Lock
    user_id: str

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # Ensure parent initializers run (e.g., circuit breaker state)
        super().__init__(*args, **kwargs)
        # Default token state if not set by concrete class
        if not hasattr(self, "_access_token"):
            self._access_token = None
        if not hasattr(self, "_refresh_token"):
            self._refresh_token = _load_refresh_token_fallback()
        elif self._refresh_token is None:
            self._refresh_token = _load_refresh_token_fallback()
        if not hasattr(self, "_token_expiry"):
            self._token_expiry = None
        if not hasattr(self, "_token_lock"):
            self._token_lock = asyncio.Lock()
        # Circuit breaker defaults for mixin-only usage (tests)
        if not hasattr(self, "_circuit_open"):
            self._circuit_open = False
        if not hasattr(self, "_failure_count"):
            self._failure_count = 0
        if not hasattr(self, "_success_count"):
            self._success_count = 0

    def _is_protocol_method(self, method: Any) -> bool:
        """Detect Protocol stub methods so we can fall back safely."""
        qualname = getattr(method, "__qualname__", "")
        return qualname.startswith("EnterpriseConnectorMethods.")

    def check_circuit_breaker(self) -> bool:
        """Return circuit breaker status with safe fallback."""
        try:
            # safe-super: mixin super() resolution depends on final MRO
            method = super().check_circuit_breaker  # type: ignore[misc, safe-super]
            result = method()
            if result is Ellipsis or result is None or self._is_protocol_method(method):
                return not getattr(self, "_circuit_open", False)
            return bool(result)
        except AttributeError:
            return not getattr(self, "_circuit_open", False)

    def get_circuit_breaker_status(self) -> dict[str, Any]:
        """Return circuit breaker status with safe fallback."""
        try:
            # safe-super: mixin super() resolution depends on final MRO
            method = super().get_circuit_breaker_status  # type: ignore[misc, safe-super]
            status = method()
            if status is Ellipsis or status is None or self._is_protocol_method(method):
                return {"cooldown_seconds": 60, "failure_count": getattr(self, "_failure_count", 0)}
            return status
        except AttributeError:
            return {"cooldown_seconds": 60, "failure_count": getattr(self, "_failure_count", 0)}

    def record_success(self) -> None:
        """Record circuit breaker success with safe fallback."""
        try:
            # safe-super: mixin super() resolution depends on final MRO
            method = super().record_success  # type: ignore[misc, safe-super]
            method()
            if self._is_protocol_method(method):
                self._success_count = getattr(self, "_success_count", 0) + 1
        except AttributeError:
            self._success_count = getattr(self, "_success_count", 0) + 1

    def record_failure(self) -> None:
        """Record circuit breaker failure with safe fallback."""
        try:
            # safe-super: mixin super() resolution depends on final MRO
            method = super().record_failure  # type: ignore[misc, safe-super]
            method()
            if self._is_protocol_method(method):
                self._failure_count = getattr(self, "_failure_count", 0) + 1
        except AttributeError:
            self._failure_count = getattr(self, "_failure_count", 0) + 1

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOCUMENT

    @property
    def name(self) -> str:
        return "Gmail"

    @property
    def access_token(self) -> str | None:
        """Expose current access token (if available)."""
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        """Expose current refresh token (if available)."""
        return self._refresh_token

    @property
    def token_expiry(self) -> datetime | None:
        """Expose access token expiry (if available)."""
        return self._token_expiry

    @property
    def is_configured(self) -> bool:
        """Check if connector has required configuration."""
        return bool(
            os.environ.get("GMAIL_CLIENT_ID")
            or os.environ.get("GOOGLE_GMAIL_CLIENT_ID")
            or os.environ.get("GOOGLE_CLIENT_ID")
        )

    def get_oauth_url(self, redirect_uri: str, state: str = "") -> str:
        """
        Generate OAuth2 authorization URL.

        Args:
            redirect_uri: URL to redirect after authorization
            state: Optional state parameter for CSRF protection

        Returns:
            Authorization URL for user to visit
        """
        from urllib.parse import urlencode

        client_id, _ = _get_client_credentials()

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(GMAIL_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }

        if state:
            params["state"] = state

        return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"

    async def authenticate(
        self,
        code: str | None = None,
        redirect_uri: str | None = None,
        refresh_token: str | None = None,
    ) -> bool:
        """
        Authenticate with Gmail API.

        Either exchange authorization code for tokens, or use existing refresh token.

        Args:
            code: Authorization code from OAuth callback
            redirect_uri: Redirect URI used in authorization
            refresh_token: Existing refresh token

        Returns:
            True if authentication successful
        """
        from aragora.server.http_client_pool import get_http_pool

        client_id, client_secret = _get_client_credentials()

        if not client_id or not client_secret:
            logger.error("[Gmail] Missing OAuth credentials")
            return False

        try:
            pool = get_http_pool()
            async with pool.get_session("google") as client:
                if code and redirect_uri:
                    # Exchange code for tokens
                    response = await client.post(
                        "https://oauth2.googleapis.com/token",
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "code": code,
                            "redirect_uri": redirect_uri,
                            "grant_type": "authorization_code",
                        },
                    )
                elif refresh_token:
                    # Use refresh token
                    response = await client.post(
                        "https://oauth2.googleapis.com/token",
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "refresh_token": refresh_token,
                            "grant_type": "refresh_token",
                        },
                    )
                else:
                    logger.error("[Gmail] No code or refresh_token provided")
                    return False

                if response.status_code >= 400:
                    logger.error("[Gmail] Authentication failed: %s", response.text)
                    return False
                response.raise_for_status()
                data = response.json()

            access_token = data.get("access_token")
            if not access_token:
                logger.error("[Gmail] Authentication response missing access_token")
                return False

            self._access_token = access_token
            self._refresh_token = data.get("refresh_token", refresh_token)

            expires_in = data.get("expires_in", 3600)
            self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

            logger.info("[Gmail] Authentication successful")
            return True

        except (OSError, ValueError, KeyError) as e:
            logger.error("[Gmail] Authentication failed: %s", e)
            return False
        except (RuntimeError, TypeError) as e:
            logger.error("[Gmail] Authentication failed: %s", e)
            return False

    async def _refresh_access_token(self) -> str:
        """Refresh the access token using refresh token."""
        from aragora.server.http_client_pool import get_http_pool

        if not self._refresh_token:
            raise ValueError("No refresh token available")

        client_id, client_secret = _get_client_credentials()

        pool = get_http_pool()
        async with pool.get_session("google") as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "refresh_token": self._refresh_token,
                    "grant_type": "refresh_token",
                },
            )
            response.raise_for_status()
            data = response.json()

        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

        return self._access_token

    async def _get_access_token(self) -> str:
        """Get valid access token, refreshing if needed.

        Thread-safe: Uses _token_lock to prevent concurrent refresh attempts.
        """
        async with self._token_lock:
            now = datetime.now(timezone.utc)

            if self._access_token and self._token_expiry and now < self._token_expiry:
                return self._access_token

            if not self._refresh_token:
                self._refresh_token = _load_refresh_token_fallback()

            if self._refresh_token:
                return await self._refresh_access_token()

            raise ValueError("No valid access token and no refresh token available")

    async def _api_request(
        self,
        endpoint: str,
        method: str = "GET",
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make a request to Gmail API with circuit breaker protection."""
        from aragora.server.http_client_pool import get_http_pool

        # Check circuit breaker first
        if not self.check_circuit_breaker():
            cb_status = self.get_circuit_breaker_status() or {}
            raise ConnectionError(
                f"Circuit breaker open for Gmail. Cooldown: {cb_status.get('cooldown_seconds', 60)}s"
            )

        token = await self._get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        url = f"https://gmail.googleapis.com/gmail/v1/users/{self.user_id}{endpoint}"

        request_error: Exception | None = None
        response = None
        pool = get_http_pool()
        async with pool.get_session("google") as client:
            try:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    timeout=60,
                )
            except TimeoutError as e:
                request_error = e
            except (OSError, ConnectionError) as e:
                request_error = e

        if request_error:
            self.record_failure()
            if isinstance(request_error, TimeoutError):
                logger.error("Gmail API timeout: %s", request_error)
            else:
                logger.error("Gmail API error: %s", request_error)
            raise request_error

        if response is None:
            raise RuntimeError("Gmail API request failed without a response")

        if response.status_code >= 400:
            # Log the full error response for debugging
            logger.error("Gmail API error %s: %s", response.status_code, response.text)
            # Record failure for circuit breaker on 5xx errors or rate limits
            if response.status_code >= 500 or response.status_code == 429:
                self.record_failure()
            response.raise_for_status()

        self.record_success()
        return response.json() if response.content else {}

    def _get_client(self) -> Any:
        """Get HTTP client context manager for API requests."""
        from aragora.server.http_client_pool import get_http_pool

        pool = get_http_pool()
        return pool.get_session("google")

    async def get_user_info(self) -> dict[str, Any]:
        """Get authenticated user's Gmail profile."""
        return await self._api_request("/profile")
