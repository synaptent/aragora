"""
Device Connector - Abstract base class for push notification integrations.

All device connectors inherit from DeviceConnector and implement
standardized methods for:
- Sending push notifications
- Device registration and management
- Batch notification delivery
- Health checking

Includes circuit breaker support for fault tolerance.
"""

from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TypeVar
from collections.abc import Awaitable, Callable

from .models import (
    BatchSendResult,
    DeliveryStatus,
    DeviceMessage,
    DeviceRegistration,
    DeviceToken,
    DeviceType,
    SendResult,
    VoiceDeviceRequest,
    VoiceDeviceResponse,
)

T = TypeVar("T")

logger = logging.getLogger(__name__)


@dataclass
class DeviceConnectorConfig:
    """Configuration for device connectors."""

    # Circuit breaker settings
    enable_circuit_breaker: bool = True
    circuit_breaker_threshold: int = 5
    circuit_breaker_cooldown: float = 60.0

    # HTTP settings
    request_timeout: float = 30.0
    max_retries: int = 3
    base_retry_delay: float = 1.0
    max_retry_delay: float = 30.0

    # Batch settings
    max_batch_size: int = 500
    batch_delay_ms: int = 10

    # Rate limiting
    max_requests_per_second: float = 100.0

    # Credentials (platform-specific)
    credentials: dict[str, Any] = field(default_factory=dict)


class DeviceConnector(ABC):
    """
    Abstract base class for device/push notification integrations.

    Provides a unified interface for sending notifications to various
    platforms including iOS (APNs), Android (FCM), Web Push (VAPID),
    Alexa, and Google Home.

    Subclasses must implement the abstract methods to handle
    platform-specific APIs and message formats.

    Includes circuit breaker support for fault tolerance in HTTP operations.
    """

    def __init__(self, config: DeviceConnectorConfig | None = None):
        """
        Initialize the connector.

        Args:
            config: Connector configuration
        """
        self.config = config or DeviceConnectorConfig()
        self._initialized = False

        # Circuit breaker state
        self._circuit_breaker: Any | None = None
        self._circuit_breaker_initialized = False

        # Rate limiting state
        self._last_request_time: float = 0
        self._request_count: int = 0

    # ==========================================================================
    # Circuit Breaker Support
    # ==========================================================================

    def _get_circuit_breaker(self) -> Any | None:
        """Get or create circuit breaker (lazy initialization)."""
        if not self.config.enable_circuit_breaker:
            return None

        if not self._circuit_breaker_initialized:
            try:
                from aragora.resilience import get_circuit_breaker

                self._circuit_breaker = get_circuit_breaker(
                    name=f"device_connector_{self.platform_name}",
                    failure_threshold=self.config.circuit_breaker_threshold,
                    cooldown_seconds=self.config.circuit_breaker_cooldown,
                )
                logger.debug("Circuit breaker initialized for %s", self.platform_name)
            except ImportError:
                logger.warning("Circuit breaker module not available")
            self._circuit_breaker_initialized = True

        return self._circuit_breaker

    def _check_circuit_breaker(self) -> tuple[bool, str | None]:
        """
        Check if circuit breaker allows the request.

        Returns:
            Tuple of (can_proceed, error_message)
        """
        cb = self._get_circuit_breaker()
        if cb is None:
            return True, None

        if not cb.can_proceed():
            remaining = cb.cooldown_remaining()
            error = f"Circuit breaker open for {self.platform_name}. Retry in {remaining:.1f}s"
            logger.warning(error)
            return False, error

        return True, None

    def _record_success(self) -> None:
        """Record a successful operation with the circuit breaker."""
        cb = self._get_circuit_breaker()
        if cb:
            cb.record_success()

    def _record_failure(self, error: Exception | None = None) -> None:
        """Record a failed operation with the circuit breaker."""
        cb = self._get_circuit_breaker()
        if cb:
            cb.record_failure()
            status = cb.get_status()
            if status == "open":
                logger.warning(
                    "Circuit breaker OPENED for %s after repeated failures", self.platform_name
                )

    # ==========================================================================
    # Retry and HTTP Support
    # ==========================================================================

    async def _with_retry(
        self,
        operation: str,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        max_retries: int | None = None,
        base_delay: float | None = None,
        max_delay: float | None = None,
        retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
        **kwargs: Any,
    ) -> T:
        """
        Execute an async function with exponential backoff retry and circuit breaker.

        Args:
            operation: Name of the operation (for logging)
            func: Async function to execute
            *args: Arguments to pass to the function
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay between retries in seconds
            max_delay: Maximum delay between retries
            retryable_exceptions: Tuple of exception types to retry on
            **kwargs: Keyword arguments to pass to the function

        Returns:
            Result of the function call

        Raises:
            Last exception if all retries fail
        """
        max_retries = max_retries or self.config.max_retries
        base_delay = base_delay or self.config.base_retry_delay
        max_delay = max_delay or self.config.max_retry_delay

        # Check circuit breaker first
        can_proceed, error_msg = self._check_circuit_breaker()
        if not can_proceed:
            raise ConnectionError(error_msg)

        last_exception = None
        for attempt in range(max_retries):
            try:
                result = await func(*args, **kwargs)
                self._record_success()
                return result
            except retryable_exceptions as e:
                last_exception = e
                self._record_failure(e)

                if attempt < max_retries - 1:
                    # Calculate delay with exponential backoff and jitter
                    delay = min(base_delay * (2**attempt), max_delay)
                    jitter = random.uniform(0, delay * 0.1)  # noqa: S311 -- retry jitter
                    total_delay = delay + jitter

                    logger.warning(
                        "%s %s failed (attempt %s/%s): %s. Retrying in %.1fs",
                        self.platform_name,
                        operation,
                        attempt + 1,
                        max_retries,
                        e,
                        total_delay,
                    )
                    await asyncio.sleep(total_delay)
                else:
                    logger.error(
                        "%s %s failed after %s attempts: %s",
                        self.platform_name,
                        operation,
                        max_retries,
                        e,
                    )

        if last_exception:
            raise last_exception
        raise RuntimeError(f"{operation} failed with no exception captured")

    def _is_retryable_status_code(self, status_code: int) -> bool:
        """
        Check if an HTTP status code indicates a retryable error.

        Args:
            status_code: HTTP status code

        Returns:
            True if the error is transient and should be retried
        """
        # 429 Too Many Requests - rate limited
        # 500 Internal Server Error - server error
        # 502 Bad Gateway - upstream error
        # 503 Service Unavailable - server overloaded
        # 504 Gateway Timeout - upstream timeout
        return status_code in {429, 500, 502, 503, 504}

    async def _http_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        data: Any | None = None,
        operation: str = "http_request",
    ) -> tuple[bool, dict[str, Any] | None, str | None]:
        """
        Make an HTTP request with retry, timeout, and circuit breaker support.

        Args:
            method: HTTP method (GET, POST, PUT, DELETE, PATCH)
            url: Request URL
            headers: Optional request headers
            json: Optional JSON body
            data: Optional form data
            operation: Operation name for logging

        Returns:
            Tuple of (success: bool, response_json: dict | None, error: str | None)
        """
        # Check circuit breaker first
        can_proceed, error_msg = self._check_circuit_breaker()
        if not can_proceed:
            return False, None, error_msg

        # Try to import httpx
        try:
            import httpx
        except ImportError:
            return False, None, "httpx not available"

        last_error: str | None = None
        max_retries = self.config.max_retries
        base_delay = self.config.base_retry_delay

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.config.request_timeout) as client:
                    response = await client.request(
                        method=method,
                        url=url,
                        headers=headers,
                        json=json,
                        data=data,
                    )

                    # Check for retryable status codes
                    if self._is_retryable_status_code(response.status_code):
                        last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                        self._record_failure()

                        if attempt < max_retries - 1:
                            delay = min(base_delay * (2**attempt), 30.0)
                            jitter = random.uniform(0, delay * 0.1)  # noqa: S311 -- retry jitter
                            total_delay = delay + jitter

                            logger.warning(
                                "%s %s got %s (attempt %s/%s). Retrying in %.1fs",
                                self.platform_name,
                                operation,
                                response.status_code,
                                attempt + 1,
                                max_retries,
                                total_delay,
                            )
                            await asyncio.sleep(total_delay)
                            continue
                        else:
                            logger.error(
                                "%s %s failed after %s attempts with status %s",
                                self.platform_name,
                                operation,
                                max_retries,
                                response.status_code,
                            )
                            return False, None, last_error

                    # Non-retryable error
                    if response.status_code >= 400:
                        self._record_failure()
                        error = f"HTTP {response.status_code}: {response.text[:200]}"
                        logger.warning("%s %s failed: %s", self.platform_name, operation, error)
                        return False, None, error

                    # Success
                    self._record_success()
                    try:
                        return True, response.json(), None
                    except (ValueError, KeyError):
                        # Response may not be JSON
                        return True, {"status": "ok", "text": response.text}, None

            except (OSError, TimeoutError, RuntimeError, ValueError) as e:
                last_error = f"Request error: {e}"
                self._record_failure()

                if attempt < max_retries - 1:
                    delay = min(base_delay * (2**attempt), 30.0)
                    logger.warning(
                        "%s %s error (attempt %s/%s): %s. Retrying in %.1fs",
                        self.platform_name,
                        operation,
                        attempt + 1,
                        max_retries,
                        e,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "%s %s failed after %s attempts: %s",
                        self.platform_name,
                        operation,
                        max_retries,
                        e,
                    )

        return False, None, last_error

    # ==========================================================================
    # Abstract Properties
    # ==========================================================================

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the platform identifier (e.g., 'fcm', 'apns', 'web_push')."""
        raise NotImplementedError

    @property
    @abstractmethod
    def platform_display_name(self) -> str:
        """Return human-readable platform name (e.g., 'Firebase Cloud Messaging')."""
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_device_types(self) -> list[DeviceType]:
        """Return list of device types this connector supports."""
        raise NotImplementedError

    # ==========================================================================
    # Notification Operations
    # ==========================================================================

    @abstractmethod
    async def send_notification(
        self,
        device: DeviceToken,
        message: DeviceMessage,
        **kwargs: Any,
    ) -> SendResult:
        """
        Send a push notification to a single device.

        Args:
            device: Target device token
            message: Notification message
            **kwargs: Platform-specific options

        Returns:
            SendResult with delivery status
        """
        raise NotImplementedError

    async def send_batch(
        self,
        devices: list[DeviceToken],
        message: DeviceMessage,
        **kwargs: Any,
    ) -> BatchSendResult:
        """
        Send notifications to multiple devices.

        Default implementation sends sequentially; platforms may override
        for more efficient batch APIs.

        Args:
            devices: List of target devices
            message: Notification message
            **kwargs: Platform-specific options

        Returns:
            BatchSendResult with aggregated results
        """
        results = []
        tokens_to_remove = []

        for device in devices:
            try:
                result = await self.send_notification(device, message, **kwargs)
                results.append(result)

                if result.should_unregister:
                    tokens_to_remove.append(device.device_id)

                # Small delay between sends for rate limiting
                if self.config.batch_delay_ms > 0:
                    await asyncio.sleep(self.config.batch_delay_ms / 1000)

            except (OSError, TimeoutError, RuntimeError, ValueError, ConnectionError) as e:
                logger.warning("Failed to send to device %s: %s", device.device_id, e)
                results.append(
                    SendResult(
                        success=False,
                        device_id=device.device_id,
                        status=DeliveryStatus.FAILED,
                        error="Notification delivery failed",
                    )
                )

        success_count = sum(1 for r in results if r.success)
        failure_count = len(results) - success_count

        return BatchSendResult(
            total_sent=len(results),
            success_count=success_count,
            failure_count=failure_count,
            results=results,
            tokens_to_remove=tokens_to_remove,
        )

    async def send_to_user(
        self,
        user_id: str,
        message: DeviceMessage,
        **kwargs: Any,
    ) -> BatchSendResult:
        """
        Send notification to all devices for a user.

        Requires session store integration to look up user devices.

        Args:
            user_id: User identifier
            message: Notification message
            **kwargs: Platform-specific options

        Returns:
            BatchSendResult with aggregated results
        """
        try:
            from aragora.server.session_store import get_session_store

            store = get_session_store()
            device_sessions = store.find_devices_by_user(user_id)

            # Convert DeviceSession to DeviceToken
            devices = [
                DeviceToken(
                    device_id=ds.device_id,
                    user_id=ds.user_id,
                    device_type=DeviceType(ds.device_type),
                    push_token=ds.push_token,
                    device_name=ds.device_name,
                    app_version=ds.app_version,
                )
                for ds in device_sessions
                if DeviceType(ds.device_type) in self.supported_device_types
            ]

            if not devices:
                return BatchSendResult(
                    total_sent=0,
                    success_count=0,
                    failure_count=0,
                    results=[],
                    tokens_to_remove=[],
                )

            return await self.send_batch(devices, message, **kwargs)

        except ImportError:
            logger.error("Session store not available for user device lookup")
            return BatchSendResult(
                total_sent=0,
                success_count=0,
                failure_count=0,
                results=[],
                tokens_to_remove=[],
            )

    # ==========================================================================
    # Device Registration
    # ==========================================================================

    async def register_device(
        self,
        registration: DeviceRegistration,
        **kwargs: Any,
    ) -> DeviceToken | None:
        """
        Register a device for push notifications.

        Validates the device token and stores the registration.

        Args:
            registration: Device registration request
            **kwargs: Platform-specific options

        Returns:
            DeviceToken if registration successful, None otherwise
        """
        # Validate device type
        if registration.device_type not in self.supported_device_types:
            logger.warning(
                "Device type %s not supported by %s", registration.device_type, self.platform_name
            )
            return None

        # Validate token format (subclasses may override for stricter validation)
        if not self.validate_token(registration.push_token):
            logger.warning("Invalid push token format for %s", self.platform_name)
            return None

        # Generate device ID
        import secrets

        device_id = f"{self.platform_name}_{secrets.token_hex(16)}"
        now = datetime.now(timezone.utc)

        device_token = DeviceToken(
            device_id=device_id,
            user_id=registration.user_id,
            device_type=registration.device_type,
            push_token=registration.push_token,
            device_name=registration.device_name,
            app_version=registration.app_version,
            created_at=now,
            last_active=now,
            metadata={
                "os_version": registration.os_version,
                "device_model": registration.device_model,
                "timezone": registration.timezone,
                "locale": registration.locale,
                "app_bundle_id": registration.app_bundle_id,
            },
        )

        # Store in session store
        try:
            from aragora.server.session_store import DeviceSession, get_session_store

            store = get_session_store()

            # Check for existing device with same token
            existing = store.find_device_by_token(registration.push_token)
            if existing:
                # Update existing device
                existing.touch()
                store.set_device_session(existing)
                logger.debug("Updated existing device registration for token")
                return DeviceToken(
                    device_id=existing.device_id,
                    user_id=existing.user_id,
                    device_type=DeviceType(existing.device_type),
                    push_token=existing.push_token,
                    device_name=existing.device_name,
                    app_version=existing.app_version,
                )

            # Create new device session
            session = DeviceSession(
                device_id=device_id,
                user_id=registration.user_id,
                device_type=registration.device_type.value,
                push_token=registration.push_token,
                device_name=registration.device_name,
                app_version=registration.app_version,
                metadata=device_token.metadata,
            )
            store.set_device_session(session)

            logger.info("Registered new device %s for user %s", device_id, registration.user_id)
            return device_token

        except ImportError:
            logger.warning("Session store not available, device not persisted")
            return device_token

    async def unregister_device(
        self,
        device_id: str,
        **kwargs: Any,
    ) -> bool:
        """
        Unregister a device.

        Args:
            device_id: Device to unregister
            **kwargs: Platform-specific options

        Returns:
            True if unregistered successfully
        """
        try:
            from aragora.server.session_store import get_session_store

            store = get_session_store()
            return store.delete_device_session(device_id)

        except ImportError:
            logger.warning("Session store not available")
            return False

    def validate_token(self, token: str) -> bool:
        """
        Validate push token format.

        Default implementation checks for non-empty token.
        Subclasses should override for platform-specific validation.

        Args:
            token: Push token to validate

        Returns:
            True if token format is valid
        """
        return bool(token and len(token) > 10)

    # ==========================================================================
    # Voice Device Support (Alexa, Google Home)
    # ==========================================================================

    async def handle_voice_request(
        self,
        request: VoiceDeviceRequest,
        **kwargs: Any,
    ) -> VoiceDeviceResponse:
        """
        Handle a voice device request.

        Default implementation returns a generic response.
        Voice device connectors should override this.

        Args:
            request: Voice request from the device
            **kwargs: Platform-specific options

        Returns:
            VoiceDeviceResponse to send back to the device
        """
        logger.warning("%s does not support voice requests", self.platform_name)
        return VoiceDeviceResponse(
            text="I'm sorry, this feature is not available.",
            should_end_session=True,
        )

    async def send_proactive_notification(
        self,
        user_id: str,
        message: str,
        **kwargs: Any,
    ) -> bool:
        """
        Send a proactive notification to a voice device.

        Used for Alexa Notifications, Google Assistant broadcasts, etc.

        Args:
            user_id: User identifier
            message: Message to send
            **kwargs: Platform-specific options

        Returns:
            True if notification sent successfully
        """
        logger.warning("%s does not support proactive notifications", self.platform_name)
        return False

    # ==========================================================================
    # Health and Status
    # ==========================================================================

    async def test_connection(self) -> dict[str, Any]:
        """
        Test the connection to the push notification service.

        Returns:
            Dict with success status and details
        """
        return {
            "platform": self.platform_name,
            "success": self._initialized,
            "supported_device_types": [dt.value for dt in self.supported_device_types],
        }

    async def get_health(self) -> dict[str, Any]:
        """
        Get detailed health status for the device connector.

        Returns comprehensive health information including circuit breaker
        state, configuration status, and connectivity details.

        Returns:
            Dict with health status and metrics
        """
        import time

        health: dict[str, Any] = {
            "platform": self.platform_name,
            "display_name": self.platform_display_name,
            "status": "unknown",
            "initialized": self._initialized,
            "timestamp": time.time(),
            "circuit_breaker": None,
            "supported_device_types": [dt.value for dt in self.supported_device_types],
        }

        # Check configuration
        if not self._initialized:
            health["status"] = "uninitialized"
            return health

        # Get circuit breaker status
        cb = self._get_circuit_breaker()
        if cb:
            cb_status = cb.get_status()
            cb_info: dict[str, Any] = {
                "state": cb_status,
                "enabled": True,
            }
            if cb_status == "open":
                cb_info["cooldown_remaining"] = cb.cooldown_remaining()
            health["circuit_breaker"] = cb_info

            # Determine health based on circuit breaker
            if cb_status == "open":
                health["status"] = "unhealthy"
            elif cb_status == "half_open":
                health["status"] = "degraded"
            else:
                health["status"] = "healthy"
        else:
            health["circuit_breaker"] = {"enabled": False}
            health["status"] = "healthy"

        return health

    @property
    def is_configured(self) -> bool:
        """Check if the connector has minimum required configuration."""
        return self._initialized

    # ==========================================================================
    # Lifecycle
    # ==========================================================================

    async def initialize(self) -> bool:
        """
        Initialize the connector.

        Subclasses should override to perform platform-specific initialization
        like loading credentials, connecting to services, etc.

        Returns:
            True if initialization successful
        """
        self._initialized = True
        logger.info("%s device connector initialized", self.platform_name)
        return True

    async def shutdown(self) -> None:
        """
        Shutdown the connector.

        Subclasses should override to perform cleanup.
        """
        self._initialized = False
        logger.info("%s device connector shutdown", self.platform_name)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(platform={self.platform_name})"
