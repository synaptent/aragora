"""
Sandbox execution endpoint handlers.

Endpoints:
    POST /api/sandbox/execute              - Execute code in sandbox
    DELETE /api/sandbox/executions/{id}     - Cancel a running execution
    GET /api/sandbox/config                - Get sandbox configuration
    PUT /api/sandbox/config                - Update sandbox configuration
    GET /api/sandbox/pool/status           - Get container pool status
"""

from __future__ import annotations

__all__ = [
    "SandboxHandler",
]

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.rbac.decorators import require_permission
from aragora.utils.optional_imports import try_import

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for sandbox execution (10 requests per minute)
_sandbox_limiter = RateLimiter(requests_per_minute=10)

# Optional sandbox imports
_exec_imports, EXECUTOR_AVAILABLE = try_import(
    "aragora.sandbox.executor", "SandboxExecutor", "SandboxConfig", "ExecutionResult"
)
SandboxExecutor = _exec_imports.get("SandboxExecutor")
SandboxConfig = _exec_imports.get("SandboxConfig")

_pool_imports, POOL_AVAILABLE = try_import("aragora.sandbox.pool", "get_container_pool")
get_container_pool = _pool_imports.get("get_container_pool")

# Module-level executor (lazy init)
_executor: Any = None
_config: Any = None

_ALLOWED_LANGUAGES = {"python", "javascript", "bash"}
_MAX_CODE_LENGTH = 50_000  # 50KB


def _get_executor() -> Any:
    """Get or create the module-level sandbox executor."""
    global _executor, _config  # noqa: PLW0603
    if _executor is None and EXECUTOR_AVAILABLE and SandboxExecutor and SandboxConfig:
        _config = SandboxConfig()
        _executor = SandboxExecutor(_config)
    return _executor


class SandboxHandler(BaseHandler):
    """Handler for sandbox code execution endpoints."""

    def __init__(self, ctx: dict | None = None):
        self.ctx = ctx or {}

    ROUTES = [
        "/api/sandbox/execute",
        "/api/sandbox/config",
        "/api/sandbox/pool/status",
    ]

    # Also match /api/sandbox/executions/{id} via prefix
    ROUTE_PREFIXES = [
        "/api/sandbox/executions/",
    ]

    def can_handle(self, path: str) -> bool:
        if path in self.ROUTES:
            return True
        return any(path.startswith(prefix) for prefix in self.ROUTE_PREFIXES)

    @require_permission("sandbox:read")
    def handle(self, path: str, query_params: dict, handler: Any = None) -> HandlerResult | None:
        """Route GET requests."""
        client_ip = get_client_ip(handler)
        if not _sandbox_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/sandbox/config":
            return self._get_config()
        if path == "/api/sandbox/pool/status":
            return self._get_pool_status()
        return None

    @handle_errors("sandbox execution")
    @require_permission("sandbox:execute")
    def handle_post(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route POST requests."""
        client_ip = get_client_ip(handler)
        if not _sandbox_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded. Please try again later.", 429)

        if path == "/api/sandbox/execute":
            return self._execute(handler)
        return None

    @handle_errors("sandbox config update")
    @require_permission("sandbox:admin")
    def handle_put(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route PUT requests."""
        if path == "/api/sandbox/config":
            return self._update_config(handler)
        return None

    @handle_errors("sandbox cancellation")
    @require_permission("sandbox:execute")
    def handle_delete(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route DELETE requests."""
        if path.startswith("/api/sandbox/executions/"):
            execution_id = path.split("/")[-1]
            return self._cancel_execution(execution_id)
        return None

    def _get_config(self) -> HandlerResult:
        """Get current sandbox configuration."""
        if not EXECUTOR_AVAILABLE:
            return error_response("Sandbox module not available", 503)

        executor = _get_executor()
        if executor is None:
            return error_response("Sandbox executor not initialized", 503)

        cfg = executor.config
        return json_response(
            {
                "mode": cfg.mode.value if hasattr(cfg.mode, "value") else str(cfg.mode),
                "docker_image": cfg.docker_image,
                "cleanup_on_complete": cfg.cleanup_on_complete,
                "capture_output": cfg.capture_output,
                "network_enabled": cfg.network_enabled,
                "resource_limits": {
                    "max_memory_mb": getattr(cfg, "max_memory_mb", 256),
                    "max_cpu_percent": getattr(cfg, "max_cpu_percent", 50),
                    "max_execution_seconds": getattr(cfg, "max_execution_seconds", 30),
                    "max_processes": getattr(cfg, "max_processes", 10),
                    "max_file_size_mb": getattr(cfg, "max_file_size_mb", 10),
                },
            }
        )

    @handle_errors("sandbox execution")
    def _execute(self, handler: Any) -> HandlerResult:
        """Execute code in the sandbox."""
        if not EXECUTOR_AVAILABLE:
            return error_response("Sandbox module not available", 503)

        body = self.read_json_body(handler) or {}
        code = body.get("code", "")
        language = body.get("language", "python")

        if not code or not code.strip():
            return error_response("No code provided", 400)

        if len(code) > _MAX_CODE_LENGTH:
            return error_response(f"Code exceeds maximum length ({_MAX_CODE_LENGTH} bytes)", 400)

        if language not in _ALLOWED_LANGUAGES:
            allowed = ", ".join(sorted(_ALLOWED_LANGUAGES))
            return error_response(
                f"Unsupported language: {language}. Allowed: {allowed}",
                400,
            )

        executor = _get_executor()
        if executor is None:
            return error_response("Sandbox executor not initialized", 503)

        result = self._run_async_callable(  # type: ignore[attr-defined]
            executor.execute,
            code=code,
            language=language,
        )

        if result is None:
            return error_response("Execution failed", 500)

        return json_response(result.to_dict())

    def _update_config(self, handler: Any) -> HandlerResult:
        """Update sandbox configuration."""
        global _executor, _config  # noqa: PLW0603

        if not EXECUTOR_AVAILABLE or not SandboxConfig:
            return error_response("Sandbox module not available", 503)

        body = self.read_json_body(handler) or {}

        # Rebuild config with updates
        executor = _get_executor()
        if executor is None:
            return error_response("Sandbox executor not initialized", 503)

        cfg = executor.config
        new_cfg = SandboxConfig(
            mode=body.get("mode", cfg.mode),
            docker_image=body.get("docker_image", cfg.docker_image),
            cleanup_on_complete=body.get("cleanup_on_complete", cfg.cleanup_on_complete),
            capture_output=body.get("capture_output", cfg.capture_output),
            network_enabled=body.get("network_enabled", cfg.network_enabled),
        )

        _config = new_cfg
        _executor = SandboxExecutor(new_cfg)

        return self._get_config()

    def _cancel_execution(self, execution_id: str) -> HandlerResult:
        """Cancel a running sandbox execution."""
        if not EXECUTOR_AVAILABLE:
            return error_response("Sandbox module not available", 503)

        executor = _get_executor()
        if executor is None:
            return error_response("Sandbox executor not initialized", 503)

        # Check if the execution exists and cancel it
        active = getattr(executor, "_active_executions", {})
        proc = active.get(execution_id)
        if proc is None:
            return error_response("Execution not found or already completed", 404)

        try:
            proc.kill()
        except (ProcessLookupError, OSError):
            pass

        return json_response({"execution_id": execution_id, "status": "cancelled"})

    def _get_pool_status(self) -> HandlerResult:
        """Get container pool status."""
        if not POOL_AVAILABLE or not get_container_pool:
            return json_response(
                {
                    "available": 0,
                    "in_use": 0,
                    "total": 0,
                    "healthy": False,
                    "message": "Container pool not available",
                }
            )

        try:
            pool = get_container_pool()
            status = pool.get_status()
            return json_response(
                {
                    "available": status.get("available", 0),
                    "in_use": status.get("in_use", 0),
                    "total": status.get("total", 0),
                    "healthy": status.get("healthy", False),
                }
            )
        except (AttributeError, TypeError, RuntimeError) as e:
            logger.warning("Failed to get pool status: %s", e)
            return json_response(
                {
                    "available": 0,
                    "in_use": 0,
                    "total": 0,
                    "healthy": False,
                }
            )
