"""
Enterprise Security Proxy core implementation.

Provides the main EnterpriseProxy class that coordinates all proxy functionality
including connection pooling, circuit breakers, retries, bulkhead isolation,
and request/response hooks.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .config import (
    ExternalFrameworkConfig,
    HealthStatus,
    ProxyConfig,
    RetrySettings,
    RetryStrategy,
)
from .exceptions import (
    CircuitOpenError,
    FrameworkNotConfiguredError,
    ProxyError,
    RequestTimeoutError,
)
from .models import (
    ErrorHook,
    HealthCheckResult,
    PostRequestHook,
    PreRequestHook,
    ProxyRequest,
    ProxyResponse,
)
from .resilience import FrameworkBulkhead, FrameworkCircuitBreaker
from .sanitizer import RequestSanitizer

logger = logging.getLogger(__name__)


class EnterpriseProxy:
    """
    Enterprise security proxy for external framework integration.

    Provides a secure, resilient proxy layer for all external framework
    calls with connection pooling, circuit breakers, retries, bulkhead
    isolation, and comprehensive security hooks.

    Example:
        >>> proxy = EnterpriseProxy(
        ...     config=ProxyConfig(max_connections=100),
        ...     frameworks={
        ...         "openai": ExternalFrameworkConfig(
        ...             base_url="https://api.openai.com",
        ...             timeout=60.0,
        ...         ),
        ...     },
        ... )
        >>> async with proxy:
        ...     response = await proxy.request(
        ...         framework="openai",
        ...         method="POST",
        ...         path="/v1/chat/completions",
        ...         json={"model": "gpt-4"},
        ...     )
    """

    def __init__(
        self,
        config: ProxyConfig | None = None,
        frameworks: dict[str, ExternalFrameworkConfig] | None = None,
    ) -> None:
        """Initialize enterprise proxy.

        Args:
            config: Global proxy configuration.
            frameworks: Per-framework configurations.
        """
        self.config = config or ProxyConfig()
        self._frameworks: dict[str, ExternalFrameworkConfig] = frameworks or {}

        # Circuit breakers per framework
        self._circuit_breakers: dict[str, FrameworkCircuitBreaker] = {}

        # Bulkheads per framework
        self._bulkheads: dict[str, FrameworkBulkhead] = {}

        # Sanitizers per framework
        self._sanitizers: dict[str, RequestSanitizer] = {}

        # Health check results
        self._health_results: dict[str, HealthCheckResult] = {}

        # Hooks
        self._pre_request_hooks: list[PreRequestHook] = []
        self._post_request_hooks: list[PostRequestHook] = []
        self._error_hooks: list[ErrorHook] = []

        # HTTP session (lazy initialized)
        self._session: Any = None  # aiohttp.ClientSession
        self._session_lock = asyncio.Lock()

        # Health check task
        self._health_check_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

        # Initialize framework components
        for name, fw_config in self._frameworks.items():
            self._init_framework(name, fw_config)

        logger.info("EnterpriseProxy initialized with %s frameworks", len(self._frameworks))

    def _init_framework(self, name: str, config: ExternalFrameworkConfig) -> None:
        """Initialize components for a framework.

        Args:
            name: Framework name.
            config: Framework configuration.
        """
        self._circuit_breakers[name] = FrameworkCircuitBreaker(name, config.circuit_breaker)
        self._bulkheads[name] = FrameworkBulkhead(name, config.bulkhead)
        self._sanitizers[name] = RequestSanitizer(config.sanitization)
        self._health_results[name] = HealthCheckResult(
            framework=name,
            status=HealthStatus.UNKNOWN,
        )

    # =========================================================================
    # Lifecycle Management
    # =========================================================================

    async def __aenter__(self) -> EnterpriseProxy:
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.shutdown()

    async def start(self) -> None:
        """Start the proxy and initialize resources."""
        await self._ensure_session()

        # Start health check background task
        if any(fw.health_check_path for fw in self._frameworks.values()):
            self._health_check_task = asyncio.create_task(self._health_check_loop())

        logger.info("EnterpriseProxy started")

    async def shutdown(self) -> None:
        """Shutdown the proxy and cleanup resources."""
        self._shutdown_event.set()

        # Cancel health check task
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass

        # Close HTTP session
        if self._session:
            await self._session.close()
            self._session = None

        logger.info("EnterpriseProxy shutdown complete")

    async def _ensure_session(self) -> Any:
        """Ensure HTTP session is initialized.

        Returns:
            aiohttp.ClientSession instance.
        """
        if self._session is not None:
            return self._session

        async with self._session_lock:
            if self._session is not None:
                return self._session

            try:
                import aiohttp

                # Configure connection pooling
                connector = aiohttp.TCPConnector(
                    limit=self.config.max_connections,
                    limit_per_host=self.config.max_connections_per_host,
                    keepalive_timeout=self.config.keepalive_timeout,
                    enable_cleanup_closed=True,
                )

                timeout = aiohttp.ClientTimeout(
                    total=self.config.default_timeout,
                    connect=self.config.default_connect_timeout,
                )

                self._session = aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout,
                    headers={"User-Agent": self.config.user_agent},
                )

                return self._session

            except ImportError:
                raise RuntimeError(
                    "aiohttp is required for EnterpriseProxy. Install with: pip install aiohttp"
                )

    # =========================================================================
    # Framework Management
    # =========================================================================

    def register_framework(
        self,
        name: str,
        config: ExternalFrameworkConfig,
    ) -> None:
        """Register a new external framework.

        Args:
            name: Unique framework identifier.
            config: Framework configuration.
        """
        if name in self._frameworks:
            logger.warning("Overwriting existing framework config for '%s'", name)

        self._frameworks[name] = config
        self._init_framework(name, config)
        logger.info("Registered framework: %s", name)

    def unregister_framework(self, name: str) -> bool:
        """Unregister an external framework.

        Args:
            name: Framework identifier to remove.

        Returns:
            True if framework was removed, False if not found.
        """
        if name not in self._frameworks:
            return False

        del self._frameworks[name]
        del self._circuit_breakers[name]
        del self._bulkheads[name]
        del self._sanitizers[name]
        del self._health_results[name]

        logger.info("Unregistered framework: %s", name)
        return True

    def get_framework_config(self, name: str) -> ExternalFrameworkConfig | None:
        """Get configuration for a framework.

        Args:
            name: Framework identifier.

        Returns:
            Framework configuration or None if not found.
        """
        return self._frameworks.get(name)

    def list_frameworks(self) -> list[str]:
        """List all registered framework names.

        Returns:
            List of framework names.
        """
        return list(self._frameworks.keys())

    # =========================================================================
    # Hook Management
    # =========================================================================

    def add_pre_request_hook(self, hook: PreRequestHook) -> None:
        """Add a pre-request hook.

        Pre-request hooks are called before each request is sent.
        They can modify the request or return None to abort.

        Args:
            hook: Async function taking ProxyRequest, returning modified
                  request or None to abort.
        """
        self._pre_request_hooks.append(hook)

    def add_post_request_hook(self, hook: PostRequestHook) -> None:
        """Add a post-request hook.

        Post-request hooks are called after each successful response.

        Args:
            hook: Async function taking ProxyRequest and ProxyResponse.
        """
        self._post_request_hooks.append(hook)

    def add_error_hook(self, hook: ErrorHook) -> None:
        """Add an error hook.

        Error hooks are called when a request fails.

        Args:
            hook: Async function taking ProxyRequest and Exception.
        """
        self._error_hooks.append(hook)

    def remove_pre_request_hook(self, hook: PreRequestHook) -> bool:
        """Remove a pre-request hook.

        Args:
            hook: Hook to remove.

        Returns:
            True if hook was removed, False if not found.
        """
        try:
            self._pre_request_hooks.remove(hook)
            return True
        except ValueError:
            return False

    def remove_post_request_hook(self, hook: PostRequestHook) -> bool:
        """Remove a post-request hook.

        Args:
            hook: Hook to remove.

        Returns:
            True if hook was removed, False if not found.
        """
        try:
            self._post_request_hooks.remove(hook)
            return True
        except ValueError:
            return False

    def remove_error_hook(self, hook: ErrorHook) -> bool:
        """Remove an error hook.

        Args:
            hook: Hook to remove.

        Returns:
            True if hook was removed, False if not found.
        """
        try:
            self._error_hooks.remove(hook)
            return True
        except ValueError:
            return False

    # =========================================================================
    # Request Handling
    # =========================================================================

    async def request(
        self,
        framework: str,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        data: bytes | None = None,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
        tenant_id: str | None = None,
        correlation_id: str | None = None,
        auth_context: Any | None = None,
        skip_circuit_breaker: bool = False,
        skip_retry: bool = False,
    ) -> ProxyResponse:
        """Make a proxied request to an external framework.

        Args:
            framework: Target framework name.
            method: HTTP method (GET, POST, etc.).
            path: Request path (appended to base_url).
            headers: Additional request headers.
            json: JSON body (will be serialized).
            data: Raw body data.
            params: URL query parameters.
            timeout: Request timeout override.
            tenant_id: Tenant identifier for context.
            correlation_id: Request correlation ID.
            auth_context: Authentication context for hooks.
            skip_circuit_breaker: Skip circuit breaker check.
            skip_retry: Skip retry logic.

        Returns:
            ProxyResponse with status, headers, and body.

        Raises:
            FrameworkNotConfiguredError: If framework is not registered.
            CircuitOpenError: If circuit breaker is open.
            BulkheadFullError: If no bulkhead slots available.
            RequestTimeoutError: If request times out.
            ProxyError: For other proxy errors.
        """
        # Validate framework
        fw_config = self._frameworks.get(framework)
        if fw_config is None:
            raise FrameworkNotConfiguredError(framework)

        if not fw_config.enabled:
            raise ProxyError(
                f"Framework '{framework}' is disabled",
                code="FRAMEWORK_DISABLED",
                framework=framework,
            )

        # Build full URL
        url = f"{fw_config.base_url}{path}"

        # Merge headers
        all_headers = dict(fw_config.default_headers)
        if headers:
            all_headers.update(headers)

        # Add tenant context header
        if tenant_id:
            all_headers[self.config.tenant_header_name] = tenant_id

        # Add correlation ID header
        if correlation_id:
            all_headers[self.config.correlation_header_name] = correlation_id

        # Serialize JSON body
        body: bytes | None = None
        if json is not None:
            import json as json_module

            body = json_module.dumps(json).encode("utf-8")
            all_headers.setdefault("Content-Type", "application/json")
        elif data is not None:
            body = data

        # Create proxy request
        proxy_request = ProxyRequest(
            framework=framework,
            method=method.upper(),
            url=url,
            headers=all_headers,
            body=body,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            auth_context=auth_context,
        )

        # Validate request
        sanitizer = self._sanitizers[framework]
        sanitizer.validate_request(proxy_request)

        # Run pre-request hooks
        for hook in self._pre_request_hooks:
            try:
                result = await hook(proxy_request)
                if result is None:
                    raise ProxyError(
                        "Request aborted by pre-request hook",
                        code="REQUEST_ABORTED",
                        framework=framework,
                    )
                proxy_request = result
            except ProxyError:
                raise
            except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided pre-request hook
                logger.error("Pre-request hook failed: %s", e)
                raise ProxyError(
                    f"Pre-request hook failed: {e}",
                    code="HOOK_ERROR",
                    framework=framework,
                )

        # Execute with resilience patterns
        try:
            return await self._execute_with_resilience(
                proxy_request,
                fw_config,
                timeout=timeout,
                skip_circuit_breaker=skip_circuit_breaker,
                skip_retry=skip_retry,
            )
        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            # Run error hooks
            for error_hook in self._error_hooks:
                try:
                    await error_hook(proxy_request, e)
                except (RuntimeError, ValueError, TypeError) as hook_error:  # noqa: BLE001 - user-provided error hook
                    logger.error("Error hook failed: %s", hook_error)
            raise

    async def _execute_with_resilience(
        self,
        request: ProxyRequest,
        config: ExternalFrameworkConfig,
        *,
        timeout: float | None = None,
        skip_circuit_breaker: bool = False,
        skip_retry: bool = False,
    ) -> ProxyResponse:
        """Execute request with resilience patterns.

        Args:
            request: Proxy request to execute.
            config: Framework configuration.
            timeout: Request timeout override.
            skip_circuit_breaker: Skip circuit breaker check.
            skip_retry: Skip retry logic.

        Returns:
            ProxyResponse from the framework.
        """
        framework = request.framework
        circuit_breaker = self._circuit_breakers[framework]
        bulkhead = self._bulkheads[framework]

        # Check circuit breaker
        if not skip_circuit_breaker:
            can_proceed = await circuit_breaker.can_proceed()
            if not can_proceed:
                raise CircuitOpenError(
                    framework,
                    circuit_breaker.cooldown_remaining,
                )

        # Acquire bulkhead slot
        async with bulkhead.acquire():
            # Execute with retry
            if skip_retry:
                return await self._execute_request(request, config, timeout=timeout)

            return await self._execute_with_retry(request, config, timeout=timeout)

    async def _execute_with_retry(
        self,
        request: ProxyRequest,
        config: ExternalFrameworkConfig,
        *,
        timeout: float | None = None,
    ) -> ProxyResponse:
        """Execute request with retry logic.

        Args:
            request: Proxy request to execute.
            config: Framework configuration.
            timeout: Request timeout override.

        Returns:
            ProxyResponse from the framework.
        """
        retry_settings = config.retry
        circuit_breaker = self._circuit_breakers[request.framework]
        last_exception: Exception | None = None

        for attempt in range(retry_settings.max_retries + 1):
            try:
                response = await self._execute_request(request, config, timeout=timeout)

                # Check if response status indicates retry
                if response.status_code in retry_settings.retryable_status_codes:
                    if attempt < retry_settings.max_retries:
                        delay = self._calculate_retry_delay(attempt, retry_settings)
                        logger.debug(
                            "Retrying %s request (attempt %s/%s) after %.2fs due to status %s",
                            request.framework,
                            attempt + 1,
                            retry_settings.max_retries,
                            delay,
                            response.status_code,
                        )
                        await asyncio.sleep(delay)
                        continue

                # Record success for non-retryable responses
                if response.is_success:
                    await circuit_breaker.record_success()

                return response

            except (asyncio.TimeoutError, ConnectionError, OSError) as e:
                last_exception = e
                await circuit_breaker.record_failure()

                if attempt < retry_settings.max_retries:
                    delay = self._calculate_retry_delay(attempt, retry_settings)
                    logger.debug(
                        "Retrying %s request (attempt %s/%s) after %.2fs: %s",
                        request.framework,
                        attempt + 1,
                        retry_settings.max_retries,
                        delay,
                        e,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(
                        "Request to %s failed after %s attempts: %s",
                        request.framework,
                        retry_settings.max_retries + 1,
                        e,
                    )
                    raise

        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected retry state")

    def _calculate_retry_delay(self, attempt: int, settings: RetrySettings) -> float:
        """Calculate retry delay for an attempt.

        Args:
            attempt: Attempt number (0-indexed).
            settings: Retry settings.

        Returns:
            Delay in seconds.
        """
        import random

        if settings.strategy == RetryStrategy.EXPONENTIAL:
            delay = settings.base_delay * (2**attempt)
        elif settings.strategy == RetryStrategy.LINEAR:
            delay = settings.base_delay * (attempt + 1)
        else:  # CONSTANT
            delay = settings.base_delay

        # Cap at max delay
        delay = min(delay, settings.max_delay)

        # Apply jitter
        if settings.jitter:
            jitter_factor = 0.25
            factor = 1.0 + (random.random() * 2 - 1) * jitter_factor  # noqa: S311 -- retry jitter
            delay = delay * factor

        return max(0, delay)

    async def _execute_request(
        self,
        request: ProxyRequest,
        config: ExternalFrameworkConfig,
        *,
        timeout: float | None = None,
    ) -> ProxyResponse:
        """Execute a single HTTP request.

        Args:
            request: Proxy request to execute.
            config: Framework configuration.
            timeout: Request timeout override.

        Returns:
            ProxyResponse from the framework.
        """
        import aiohttp

        session = await self._ensure_session()
        request_timeout = timeout or config.timeout

        start_time = time.time()

        try:
            client_timeout = aiohttp.ClientTimeout(
                total=request_timeout,
                connect=config.connect_timeout,
            )

            # Sanitize headers for outgoing request
            sanitizer = self._sanitizers[request.framework]
            sanitized_headers = sanitizer.sanitize_headers(request.headers)

            async with session.request(
                method=request.method,
                url=request.url,
                headers=sanitized_headers,
                data=request.body,
                timeout=client_timeout,
            ) as response:
                body = await response.read()
                elapsed_ms = (time.time() - start_time) * 1000

                proxy_response = ProxyResponse(
                    status_code=response.status,
                    headers=dict(response.headers),
                    body=body,
                    elapsed_ms=elapsed_ms,
                    framework=request.framework,
                    correlation_id=request.correlation_id,
                )

                # Log request if audit enabled
                if self.config.enable_audit_logging:
                    self._log_request(request, proxy_response, sanitizer)

                # Run post-request hooks
                for hook in self._post_request_hooks:
                    try:
                        await hook(request, proxy_response)
                    except (RuntimeError, ValueError, TypeError) as e:  # noqa: BLE001 - user-provided post-request hook
                        logger.error("Post-request hook failed: %s", e)

                return proxy_response

        except asyncio.TimeoutError:
            raise RequestTimeoutError(request.framework, request_timeout)

    def _log_request(
        self,
        request: ProxyRequest,
        response: ProxyResponse,
        sanitizer: RequestSanitizer,
    ) -> None:
        """Log request/response for audit.

        Args:
            request: The proxy request.
            response: The proxy response.
            sanitizer: Sanitizer for redaction.
        """
        sanitized_headers = sanitizer.sanitize_headers(request.headers, for_logging=True)
        sanitized_body = sanitizer.sanitize_body_for_logging(request.body)

        logger.info(
            "Proxy request: %s %s -> %s (%.1fms)",
            request.method,
            request.url,
            response.status_code,
            response.elapsed_ms,
            extra={
                "framework": request.framework,
                "method": request.method,
                "url": request.url,
                "status_code": response.status_code,
                "elapsed_ms": response.elapsed_ms,
                "tenant_id": request.tenant_id,
                "correlation_id": request.correlation_id,
                "request_headers": sanitized_headers,
                "request_body_preview": sanitized_body[:200] if sanitized_body else None,
            },
        )

    # =========================================================================
    # Health Checks
    # =========================================================================

    async def check_health(self, framework: str) -> HealthCheckResult:
        """Perform a health check for a framework.

        Args:
            framework: Framework to check.

        Returns:
            HealthCheckResult with status and latency.
        """
        fw_config = self._frameworks.get(framework)
        if fw_config is None:
            return HealthCheckResult(
                framework=framework,
                status=HealthStatus.UNKNOWN,
                error="Framework not configured",
            )

        if not fw_config.health_check_path:
            return HealthCheckResult(
                framework=framework,
                status=HealthStatus.UNKNOWN,
                error="No health check path configured",
            )

        start_time = time.time()

        try:
            response = await self.request(
                framework=framework,
                method="GET",
                path=fw_config.health_check_path,
                timeout=10.0,
                skip_circuit_breaker=True,
                skip_retry=True,
            )

            latency_ms = (time.time() - start_time) * 1000

            if response.is_success:
                status = HealthStatus.HEALTHY
                error = None
            else:
                status = HealthStatus.DEGRADED
                error = f"Non-2xx status: {response.status_code}"

            result = HealthCheckResult(
                framework=framework,
                status=status,
                latency_ms=latency_ms,
                error=error,
                consecutive_failures=0,
            )

        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            prev_result = self._health_results.get(framework)
            consecutive_failures = prev_result.consecutive_failures + 1 if prev_result else 1

            result = HealthCheckResult(
                framework=framework,
                status=HealthStatus.UNHEALTHY,
                error=str(e),
                consecutive_failures=consecutive_failures,
            )

        self._health_results[framework] = result
        return result

    async def check_all_health(self) -> dict[str, HealthCheckResult]:
        """Perform health checks for all frameworks.

        Returns:
            Dictionary of framework name to health check result.
        """
        results = {}
        for framework in self._frameworks:
            results[framework] = await self.check_health(framework)
        return results

    async def _health_check_loop(self) -> None:
        """Background task for periodic health checks."""
        while not self._shutdown_event.is_set():
            for name, config in self._frameworks.items():
                if config.health_check_path:
                    try:
                        await self.check_health(name)
                    except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
                        logger.error("Health check failed for %s: %s", name, e)

                    await asyncio.sleep(config.health_check_interval)

            # Sleep before next round
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=10.0,
                )
            except asyncio.TimeoutError as e:
                logger.debug("health check loop encountered an error: %s", e)

    # =========================================================================
    # Monitoring and Statistics
    # =========================================================================

    def get_circuit_breaker_status(
        self,
        framework: str | None = None,
    ) -> dict[str, Any]:
        """Get circuit breaker status.

        Args:
            framework: Specific framework, or None for all.

        Returns:
            Circuit breaker status dictionary.
        """
        if framework:
            cb = self._circuit_breakers.get(framework)
            return cb.to_dict() if cb else {}

        return {name: cb.to_dict() for name, cb in self._circuit_breakers.items()}

    def get_bulkhead_status(
        self,
        framework: str | None = None,
    ) -> dict[str, Any]:
        """Get bulkhead status.

        Args:
            framework: Specific framework, or None for all.

        Returns:
            Bulkhead status dictionary.
        """
        if framework:
            bh = self._bulkheads.get(framework)
            return bh.to_dict() if bh else {}

        return {name: bh.to_dict() for name, bh in self._bulkheads.items()}

    def get_health_status(
        self,
        framework: str | None = None,
    ) -> dict[str, Any]:
        """Get health check status.

        Args:
            framework: Specific framework, or None for all.

        Returns:
            Health status dictionary.
        """
        if framework:
            result = self._health_results.get(framework)
            return result.to_dict() if result else {}

        return {name: result.to_dict() for name, result in self._health_results.items()}

    def get_stats(self) -> dict[str, Any]:
        """Get comprehensive proxy statistics.

        Returns:
            Dictionary of proxy statistics.
        """
        return {
            "config": {
                "max_connections": self.config.max_connections,
                "max_connections_per_host": self.config.max_connections_per_host,
                "default_timeout": self.config.default_timeout,
                "audit_logging_enabled": self.config.enable_audit_logging,
                "metrics_enabled": self.config.enable_metrics,
            },
            "frameworks": {
                name: {
                    "enabled": fw.enabled,
                    "base_url": fw.base_url,
                    "timeout": fw.timeout,
                }
                for name, fw in self._frameworks.items()
            },
            "circuit_breakers": self.get_circuit_breaker_status(),
            "bulkheads": self.get_bulkhead_status(),
            "health": self.get_health_status(),
            "hooks": {
                "pre_request": len(self._pre_request_hooks),
                "post_request": len(self._post_request_hooks),
                "error": len(self._error_hooks),
            },
        }

    async def reset_circuit_breaker(self, framework: str) -> bool:
        """Reset circuit breaker for a framework.

        Args:
            framework: Framework to reset.

        Returns:
            True if reset successful, False if framework not found.
        """
        cb = self._circuit_breakers.get(framework)
        if cb is None:
            return False
        await cb.reset()
        return True


__all__ = [
    "EnterpriseProxy",
]
