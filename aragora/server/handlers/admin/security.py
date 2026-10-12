"""
Security endpoint handlers.

Endpoints:
- GET /api/admin/security/status - Get encryption and key status
- POST /api/admin/security/rotate-key - Rotate encryption key
- GET /api/admin/security/health - Check encryption health

All endpoints require admin or owner role.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

from ..base import (
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from ..secure import SecureHandler
from ..utils.rate_limit import RateLimiter, get_client_ip
from .admin import admin_secure_endpoint

from aragora.events.handler_events import emit_handler_event, COMPLETED
from aragora.rbac.decorators import require_permission
from aragora.server.middleware.mfa import enforce_admin_mfa_policy

try:
    from aragora.rbac.checker import check_permission  # noqa: F401
    from aragora.rbac.models import AuthorizationContext  # noqa: F401

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

logger = logging.getLogger(__name__)

# Permission required for security admin access
ADMIN_SECURITY_PERMISSION = "admin:security"

# Rate limiter for security admin endpoints (10 requests per minute)
_security_limiter = RateLimiter(requests_per_minute=10)


class SecurityHandler(SecureHandler):
    """Handler for security-related admin endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    def _get_user_store(self) -> Any:
        """Return the user store for admin auth/MFA enforcement."""
        return self.ctx.get("user_store")

    ROUTES = [
        # Versioned routes
        "/api/v1/admin/security/status",
        "/api/v1/admin/security/rotate-key",
        "/api/v1/admin/security/health",
        "/api/v1/admin/security/keys",
        # Non-versioned routes (backwards compatibility)
        "/api/admin/security/status",
        "/api/admin/security/rotate-key",
        "/api/admin/security/health",
        "/api/admin/security/keys",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return path in self.ROUTES

    @require_permission("admin:security:read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route security endpoint requests."""
        # Rate limit check for security admin endpoints
        client_ip = get_client_ip(handler)
        if not _security_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for security endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # RBAC inline check via rbac.checker if available
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                return error_response("Service unavailable: access control module not loaded", 503)
        elif hasattr(handler, "auth_context"):
            decision = check_permission(handler.auth_context, ADMIN_SECURITY_PERMISSION)
            if not decision.allowed:
                logger.warning("RBAC denied admin security access: %s", decision.reason)
                return error_response(
                    "Permission denied",
                    403,
                    code="PERMISSION_DENIED",
                )

        handlers = {
            "/api/v1/admin/security/status": self._get_status,
            "/api/v1/admin/security/health": self._get_health,
            "/api/v1/admin/security/keys": self._list_keys,
            # Non-versioned routes (backwards compatibility)
            "/api/admin/security/status": self._get_status,
            "/api/admin/security/health": self._get_health,
            "/api/admin/security/keys": self._list_keys,
        }

        # GET endpoints
        endpoint_handler = handlers.get(path)
        if endpoint_handler:
            return endpoint_handler(handler)
        return None

    @handle_errors("security creation")
    @require_permission("admin:security:write")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests for security endpoints."""
        content_length = 0
        if hasattr(handler, "headers"):
            try:
                content_length = int(handler.headers.get("Content-Length", 0) or 0)
            except (TypeError, ValueError):
                content_length = 0

        body = self.read_json_body(handler)
        if body is None:
            if content_length == 0 and query_params:
                body = dict(query_params)
            else:
                return error_response("Invalid JSON body", 400)
        elif content_length == 0 and not body and query_params:
            body = dict(query_params)
        elif not isinstance(body, dict):
            return error_response("JSON body must deserialize to an object", 400)

        # Enforce MFA for admin users (SOC 2 CC5-01)
        if hasattr(handler, "auth_context"):
            user_store = self.ctx.get("user_store") if hasattr(self, "ctx") else None
            if user_store:
                user = user_store.get_user_by_id(handler.auth_context.user_id)
                if user:
                    mfa_result = enforce_admin_mfa_policy(user, user_store)
                    if mfa_result and mfa_result.get("enforced"):
                        return error_response(
                            "Administrative access requires MFA. Please enable MFA at /api/auth/mfa/setup",
                            403,
                        )

        # RBAC inline check via rbac.checker if available
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                return error_response("Service unavailable: access control module not loaded", 503)
        elif hasattr(handler, "auth_context"):
            decision = check_permission(handler.auth_context, ADMIN_SECURITY_PERMISSION)
            if not decision.allowed:
                logger.warning("RBAC denied admin security POST access: %s", decision.reason)
                return error_response(
                    "Permission denied",
                    403,
                    code="PERMISSION_DENIED",
                )

        if path in ("/api/v1/admin/security/keys", "/api/admin/security/keys"):
            return self._create_key(handler, body)
        if path in ("/api/v1/admin/security/rotate-key", "/api/admin/security/rotate-key"):
            return self._rotate_key(handler, body)
        return None

    @admin_secure_endpoint(
        permission="admin.security.status",
        audit=True,
        audit_action="security_status_viewed",
    )
    async def _get_status(self, request: Any, _auth_context: Any) -> HandlerResult:
        """
        Get encryption and key status.

        Returns:
            200: Encryption status information
            500: Error getting status
        """
        try:
            from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

            if not CRYPTO_AVAILABLE:
                return json_response(
                    {
                        "crypto_available": False,
                        "error": "Cryptography library not installed",
                    }
                )

            service = get_encryption_service()
            active_key = service.get_active_key()

            result: dict[str, Any] = {
                "crypto_available": True,
                "active_key_id": service.get_active_key_id(),
            }

            if active_key:
                age_days = (datetime.now(timezone.utc) - active_key.created_at).days
                result.update(
                    {
                        "key_version": active_key.version,
                        "key_age_days": age_days,
                        "key_created_at": active_key.created_at.isoformat(),
                        "rotation_recommended": age_days > 60,
                        "rotation_required": age_days > 90,
                    }
                )
            else:
                result["warning"] = "No active encryption key found"

            # Count all keys
            all_keys = service.list_keys()
            result["total_keys"] = len(all_keys)

            return json_response(result)

        except ImportError as e:
            logger.error("Security status import error: %s", e)
            return error_response("Internal server error", 500)
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Security status error: %s", e)
            return error_response("Internal server error", 500)

    @admin_secure_endpoint(
        permission="admin.security.keys",
        audit=True,
        audit_action="key_created",
    )
    async def _create_key(
        self, request: Any, _auth_context: Any, data: dict[str, Any]
    ) -> HandlerResult:
        """
        Create a new encryption key.

        Request body:
            name (str): Human-friendly key name (required)
            algorithm (str): Encryption algorithm (default: AES-256-GCM)
            expires_in_days (int): Optional expiration window in days
            metadata (dict): Optional metadata echoed in the response

        Returns:
            201: Created key details
            400: Invalid request
            500: Key creation failed
        """
        try:
            from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

            if not CRYPTO_AVAILABLE:
                return error_response("Cryptography library not available", 400)

            name = str(data.get("name", "")).strip()
            if not name:
                return error_response("name is required", 400)

            service = get_encryption_service()
            supported_algorithm = getattr(
                getattr(service, "config", None), "algorithm", "aes-256-gcm"
            )
            if hasattr(supported_algorithm, "value"):
                supported_algorithm = supported_algorithm.value

            algorithm = str(data.get("algorithm") or supported_algorithm).strip().lower()
            if algorithm != str(supported_algorithm).lower():
                return error_response(
                    f"Unsupported algorithm '{algorithm}'. Only {supported_algorithm} is supported.",
                    400,
                )

            expires_in_days = data.get("expires_in_days")
            if expires_in_days is not None:
                if isinstance(expires_in_days, bool):
                    return error_response("expires_in_days must be an integer", 400)
                if isinstance(expires_in_days, str):
                    try:
                        expires_in_days = int(expires_in_days)
                    except ValueError:
                        return error_response("expires_in_days must be an integer", 400)
                if not isinstance(expires_in_days, int):
                    return error_response("expires_in_days must be an integer", 400)
                if expires_in_days <= 0:
                    return error_response("expires_in_days must be greater than 0", 400)

            metadata = data.get("metadata")
            if metadata is None:
                metadata = {}
            elif not isinstance(metadata, dict):
                return error_response("metadata must be an object", 400)

            key_id = re.sub(r"[^A-Za-z0-9_.:-]+", "_", name).strip("_") or None
            key = service.generate_key(key_id=key_id, ttl_days=expires_in_days)
            key_info = key.to_dict() if hasattr(key, "to_dict") else {}

            emit_handler_event(
                "admin", COMPLETED, {"action": "key_created", "key_id": key_info.get("key_id")}
            )
            return json_response(
                {
                    "id": key_info.get("key_id"),
                    "key_id": key_info.get("key_id"),
                    "name": name,
                    "status": "active" if key_info.get("is_active", True) else "inactive",
                    "algorithm": key_info.get("algorithm", algorithm),
                    "version": key_info.get("version"),
                    "created_at": key_info.get("created_at"),
                    "expires_at": key_info.get("expires_at"),
                    "metadata": metadata,
                },
                status=201,
            )

        except ImportError as e:
            logger.error("Create key import error: %s", e)
            return error_response("Internal server error", 500)
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Create key error: %s", e)
            return error_response("Internal server error", 500)

    @admin_secure_endpoint(
        permission="admin.security.rotate",
        audit=True,
        audit_action="key_rotation",
    )
    async def _rotate_key(
        self, request: Any, _auth_context: Any, data: dict[str, Any]
    ) -> HandlerResult:
        """
        Rotate encryption key.

        Request body:
            dry_run (bool): If true, only preview what would be done
            stores (list[str]): Stores to re-encrypt (default: all)
            force (bool): Force rotation even if key is recent

        Returns:
            200: Rotation result
            400: Invalid request
            500: Rotation failed
        """
        try:
            from aragora.security.migration import (
                get_migration_audit_provider,
                rotate_encryption_key,
            )
            from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

            if not CRYPTO_AVAILABLE:
                return error_response("Cryptography library not available", 400)

            dry_run = data.get("dry_run", False)
            stores = data.get("stores")
            force = data.get("force", False)

            # Check if rotation is needed (unless forced)
            if not force and not dry_run:
                service = get_encryption_service()
                active_key = service.get_active_key()
                if active_key:
                    age_days = (datetime.now(timezone.utc) - active_key.created_at).days
                    if age_days < 30:
                        return error_response(
                            f"Key is only {age_days} days old. Use 'force: true' to rotate anyway.",
                            400,
                        )

            # Server startup normally registers the provider, but an embedded
            # handler can run without it; keep any provider the embedder injected.
            if get_migration_audit_provider() is None:
                from aragora.ops.security_edge_adapters import (
                    register_security_migration_adapters,
                )

                register_security_migration_adapters()

            result = rotate_encryption_key(
                stores=stores,
                dry_run=dry_run,
            )

            emit_handler_event("admin", COMPLETED, {"action": "key_rotation", "dry_run": dry_run})
            return json_response(
                {
                    "success": result.success,
                    "dry_run": dry_run,
                    "old_key_version": result.old_key_version,
                    "new_key_version": result.new_key_version,
                    "stores_processed": result.stores_processed,
                    "records_reencrypted": result.records_reencrypted,
                    "failed_records": result.failed_records,
                    "duration_seconds": result.duration_seconds,
                    "errors": result.errors[:10] if result.errors else [],
                }
            )

        except ImportError as e:
            logger.error("Key rotation import error: %s", e)
            return error_response("Internal server error", 500)
        except (RuntimeError, ValueError, TypeError, OSError) as e:
            logger.error("Key rotation error: %s", e)
            return error_response("Internal server error", 500)

    @admin_secure_endpoint(
        permission="admin.security.health",
        audit=False,
    )
    async def _get_health(self, request: Any, _auth_context: Any) -> HandlerResult:
        """
        Check encryption health.

        Returns:
            200: Health check results
            500: Health check failed
        """
        try:
            from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

            issues: list[str] = []
            warnings: list[str] = []
            checks: dict[str, Any] = {}

            # Check 1: Crypto library
            checks["crypto_available"] = CRYPTO_AVAILABLE
            if not CRYPTO_AVAILABLE:
                issues.append("Cryptography library not installed")
                return json_response(
                    {
                        "status": "unhealthy",
                        "checks": checks,
                        "issues": issues,
                        "warnings": warnings,
                    }
                )

            # Check 2: Encryption service
            try:
                service = get_encryption_service()
                checks["service_initialized"] = True
            except (RuntimeError, ValueError, OSError, TypeError) as e:
                checks["service_initialized"] = False
                issues.append(f"Encryption service error: {e}")
                return json_response(
                    {
                        "status": "unhealthy",
                        "checks": checks,
                        "issues": issues,
                        "warnings": warnings,
                    }
                )

            # Check 3: Active key
            active_key = service.get_active_key()
            checks["active_key"] = active_key is not None
            if active_key:
                age_days = (datetime.now(timezone.utc) - active_key.created_at).days
                checks["key_age_days"] = age_days
                checks["key_version"] = active_key.version

                if age_days > 90:
                    warnings.append(f"Key is {age_days} days old (>90 days)")
                elif age_days > 60:
                    warnings.append(f"Key is {age_days} days old, rotation recommended")
            else:
                issues.append("No active encryption key")

            # Check 4: Encrypt/decrypt round-trip
            try:
                test_data = b"health_check_test_data"
                encrypted = service.encrypt(test_data)
                decrypted = service.decrypt(encrypted)
                checks["round_trip"] = decrypted == test_data
                if decrypted != test_data:
                    issues.append("Encrypt/decrypt round-trip failed")
            except (RuntimeError, ValueError, OSError, TypeError) as e:
                checks["round_trip"] = False
                issues.append(f"Encrypt/decrypt error: {e}")

            # Check 5: Key rotation scheduler status
            try:
                from aragora.security.key_rotation import get_key_rotation_scheduler

                scheduler = get_key_rotation_scheduler()
                if scheduler is not None:
                    stats = scheduler.get_stats()
                    checks["key_rotation_scheduler"] = {
                        "status": stats.status.value,
                        "total_rotations": stats.total_rotations,
                        "successful_rotations": stats.successful_rotations,
                        "failed_rotations": stats.failed_rotations,
                        "last_rotation_at": stats.last_rotation_at.isoformat()
                        if stats.last_rotation_at
                        else None,
                        "next_check_at": stats.next_check_at.isoformat()
                        if stats.next_check_at
                        else None,
                        "keys_tracked": stats.keys_tracked,
                        "keys_expiring_soon": stats.keys_expiring_soon,
                    }
                    if stats.failed_rotations > 0 and stats.last_rotation_status == "failed":
                        warnings.append("Last key rotation failed")
                else:
                    checks["key_rotation_scheduler"] = {"status": "not_configured"}
            except ImportError:
                checks["key_rotation_scheduler"] = {"status": "not_available"}

            # Determine overall status
            if issues:
                status = "unhealthy"
            elif warnings:
                status = "degraded"
            else:
                status = "healthy"

            return json_response(
                {
                    "status": status,
                    "checks": checks,
                    "issues": issues,
                    "warnings": warnings,
                }
            )

        except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.error("Security health check error: %s", e)
            return error_response("Internal server error", 500)

    @admin_secure_endpoint(
        permission="admin.security.keys",
        audit=True,
        audit_action="keys_listed",
    )
    async def _list_keys(self, request: Any, _auth_context: Any) -> HandlerResult:
        """
        List all encryption keys.

        Returns:
            200: List of keys (without sensitive data)
            500: Error listing keys
        """
        try:
            from aragora.security.encryption import get_encryption_service, CRYPTO_AVAILABLE

            if not CRYPTO_AVAILABLE:
                return error_response("Cryptography library not available", 400)

            service = get_encryption_service()
            active_key_id = service.get_active_key_id()
            all_keys = service.list_keys()

            keys_info = []
            for key in all_keys:
                # list_keys() returns list[dict[str, Any]] from EncryptionKey.to_dict()
                # Parse the ISO format created_at string back to datetime for age calculation
                created_at_str = key["created_at"]
                created_at = datetime.fromisoformat(created_at_str)
                age_days = (datetime.now(timezone.utc) - created_at).days
                keys_info.append(
                    {
                        "key_id": key["key_id"],
                        "version": key["version"],
                        "is_active": key["key_id"] == active_key_id,
                        "created_at": created_at_str,
                        "age_days": age_days,
                    }
                )

            return json_response(
                {
                    "keys": keys_info,
                    "active_key_id": active_key_id,
                    "total_keys": len(keys_info),
                }
            )

        except ImportError as e:
            logger.error("List keys import error: %s", e)
            return error_response("Internal server error", 500)
        except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError) as e:
            logger.error("List keys error: %s", e)
            return error_response("Internal server error", 500)
