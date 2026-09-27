"""
Credential management for OpenClaw Gateway.

Stability: STABLE

Contains:
- CredentialRotationRateLimiter - rate limiting for credential rotation
- Credential management handler methods (mixin class)
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import datetime
from threading import Lock
from typing import TYPE_CHECKING, Any

from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
    safe_error_message,
)
from aragora.server.handlers.openclaw._base import OpenClawMixinBase, _has_permission
from aragora.server.handlers.openclaw.models import CredentialType
from aragora.server.handlers.openclaw.store import _get_store
from aragora.server.handlers.openclaw.validation import (
    MAX_CREDENTIAL_METADATA_SIZE,
    validate_credential_name,
    validate_credential_secret,
    validate_metadata,
)
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.handlers.utils.rate_limit import (
    auth_rate_limit,
    rate_limit,
)
from aragora.server.validation.query_params import safe_query_int

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limiting for Credential Rotation
# =============================================================================

# Rate limiting constants
CREDENTIAL_ROTATION_WINDOW_SECONDS = 3600  # 1 hour window
MAX_CREDENTIAL_ROTATIONS_PER_HOUR = 10


class CredentialRotationRateLimiter:
    """Rate limiter specifically for credential rotation operations.

    Implements a sliding window rate limit to prevent abuse of credential
    rotation functionality. This is separate from the general rate limit
    to provide fine-grained control over this sensitive operation.
    """

    def __init__(
        self,
        max_rotations: int = MAX_CREDENTIAL_ROTATIONS_PER_HOUR,
        window_seconds: int = CREDENTIAL_ROTATION_WINDOW_SECONDS,
    ):
        self._max_rotations = max_rotations
        self._window_seconds = window_seconds
        self._rotation_history: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def is_allowed(self, user_id: str) -> bool:
        """Check if a rotation is allowed for the given user.

        Args:
            user_id: The user ID attempting the rotation

        Returns:
            True if rotation is allowed, False if rate limited
        """
        now = time.time()
        cutoff = now - self._window_seconds

        with self._lock:
            # Clean old entries
            self._rotation_history[user_id] = [
                ts for ts in self._rotation_history[user_id] if ts > cutoff
            ]

            # Check limit
            if len(self._rotation_history[user_id]) >= self._max_rotations:
                return False

            # Record this rotation
            self._rotation_history[user_id].append(now)
            return True

    def get_remaining(self, user_id: str) -> int:
        """Get remaining rotations allowed for the user."""
        now = time.time()
        cutoff = now - self._window_seconds

        with self._lock:
            recent = [ts for ts in self._rotation_history[user_id] if ts > cutoff]
            return max(0, self._max_rotations - len(recent))

    def get_retry_after(self, user_id: str) -> int:
        """Get seconds until the next rotation is allowed."""
        now = time.time()
        cutoff = now - self._window_seconds

        with self._lock:
            recent = sorted([ts for ts in self._rotation_history[user_id] if ts > cutoff])
            if len(recent) < self._max_rotations:
                return 0
            # Return time until oldest rotation expires
            oldest = recent[0]
            return max(0, int((oldest + self._window_seconds) - now))


# Global credential rotation rate limiter
_credential_rotation_limiter: CredentialRotationRateLimiter | None = None


def _get_credential_rotation_limiter() -> CredentialRotationRateLimiter:
    """Get or create the credential rotation rate limiter."""
    # Allow test overrides via the compatibility shim module.
    try:
        import sys

        gateway_module = sys.modules.get("aragora.server.handlers.openclaw.openclaw_gateway")
        override = (
            getattr(gateway_module, "_get_credential_rotation_limiter", None)
            if gateway_module
            else None
        )
        if override is not None and override is not _get_credential_rotation_limiter:
            return override()
    except (ImportError, AttributeError, TypeError) as e:
        logger.debug("Failed to resolve credential rotation limiter override: %s", e)

    global _credential_rotation_limiter
    if _credential_rotation_limiter is None:
        _credential_rotation_limiter = CredentialRotationRateLimiter()
    return _credential_rotation_limiter


# =============================================================================
# Credential Handler Mixin
# =============================================================================


class CredentialHandlerMixin(OpenClawMixinBase):
    """Mixin class providing credential management handler methods.

    This mixin is intended to be used with OpenClawGatewayHandler.
    It requires the following methods from the parent class:
    - _get_user_id(handler) -> str
    - _get_tenant_id(handler) -> str | None
    - get_current_user(handler) -> User | None
    """

    @require_permission("gateway:credentials.read")
    @rate_limit(requests_per_minute=60, limiter_name="openclaw_gateway_list_creds")
    def _handle_list_credentials(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """List credentials (metadata only, no secret values)."""
        try:
            store = _get_store()
            user_id = self._get_user_id(handler)
            tenant_id = self._get_tenant_id(handler)
            # Parse query parameters
            type_str = query_params.get("type")
            cred_type = CredentialType(type_str) if type_str else None
            limit = safe_query_int(query_params, "limit", default=50, max_val=500)
            offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=100000)

            # List credentials (scoped to user/tenant)
            credentials, total = store.list_credentials(
                user_id=user_id,
                tenant_id=tenant_id,
                credential_type=cred_type,
                limit=limit,
                offset=offset,
            )

            return json_response(
                {
                    "credentials": [c.to_dict() for c in credentials],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            )
        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid parameter", 400)
        except (KeyError, ValueError, OSError, RuntimeError) as e:
            logger.error("Error listing credentials: %s", e)
            return error_response(safe_error_message(e, "gateway"), 500)

    @require_permission("gateway:credentials.create")
    @auth_rate_limit(
        requests_per_minute=10,
        limiter_name="openclaw_gateway_store_credential",
        endpoint_name="OpenClaw store credential",
    )
    def _handle_store_credential(self, body: dict[str, Any], handler: Any) -> HandlerResult:
        """Store a new credential."""
        try:
            store = _get_store()
            user_id = self._get_user_id(handler)
            tenant_id = self._get_tenant_id(handler)
            # Validate credential name
            name = body.get("name")
            validation_name = name.replace(" ", "_") if isinstance(name, str) else name
            is_valid, error = validate_credential_name(validation_name)
            if not is_valid or not isinstance(name, str):
                return error_response(error or "Invalid credential name", 400)

            # Validate credential type
            credential_type_str = body.get("type")
            if not credential_type_str:
                return error_response("type is required", 400)

            try:
                credential_type = CredentialType(credential_type_str)
            except ValueError:
                valid_types = [t.value for t in CredentialType]
                return error_response(f"Invalid credential type. Valid types: {valid_types}", 400)

            # Validate secret value
            secret_value = body.get("secret")
            is_valid, error = validate_credential_secret(secret_value, credential_type_str)
            if not is_valid or not isinstance(secret_value, str):
                return error_response(error or "Invalid credential secret", 400)

            # Optional expiration
            expires_at = None
            if body.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(body["expires_at"])
                except ValueError:
                    return error_response("Invalid expires_at format (use ISO 8601)", 400)

            # Validate metadata
            metadata = body.get("metadata", {})
            is_valid, error = validate_metadata(metadata, MAX_CREDENTIAL_METADATA_SIZE)
            if not is_valid:
                return error_response(error or "Invalid credential metadata", 400)

            credential = store.store_credential(
                name=name.strip(),
                credential_type=credential_type,
                secret_value=secret_value,
                user_id=user_id,
                tenant_id=tenant_id,
                expires_at=expires_at,
                metadata=metadata,
            )

            # Audit (without revealing the secret)
            store.add_audit_entry(
                action="credential.create",
                actor_id=user_id,
                resource_type="credential",
                resource_id=credential.id,
                result="success",
                details={"name": name, "type": credential_type_str},
            )

            logger.info("Stored credential %s (%s) for user %s", credential.id, name, user_id)
            return json_response(credential.to_dict(), status=201)

        except (KeyError, ValueError, OSError, RuntimeError) as e:
            logger.error("Error storing credential: %s", e)
            return error_response(safe_error_message(e, "gateway"), 500)

    @require_permission("gateway:credentials.rotate")
    @auth_rate_limit(
        requests_per_minute=10,
        limiter_name="openclaw_gateway_rotate_credential",
        endpoint_name="OpenClaw rotate credential",
    )
    def _handle_rotate_credential(
        self, credential_id: str, body: dict[str, Any], handler: Any
    ) -> HandlerResult:
        """Rotate a credential's secret value."""
        try:
            store = _get_store()
            user_id = self._get_user_id(handler)
            # Check credential rotation rate limit (per-user, in addition to general rate limit)
            rotation_limiter = _get_credential_rotation_limiter()
            if not rotation_limiter.is_allowed(user_id):
                remaining = rotation_limiter.get_remaining(user_id)
                retry_after = rotation_limiter.get_retry_after(user_id)

                # Audit rate limit hit
                store.add_audit_entry(
                    action="credential.rotate.rate_limited",
                    actor_id=user_id,
                    resource_type="credential",
                    resource_id=credential_id,
                    result="rate_limited",
                    details={
                        "remaining": remaining,
                        "retry_after_seconds": retry_after,
                    },
                )

                logger.warning(
                    "Credential rotation rate limit exceeded for user %s (credential: %s)",
                    user_id,
                    credential_id,
                )

                headers = {"Retry-After": str(retry_after)} if retry_after > 0 else {}
                return error_response(
                    f"Too many credential rotations. Limit: {MAX_CREDENTIAL_ROTATIONS_PER_HOUR}/hour. "
                    f"Please try again in {retry_after} seconds.",
                    status=429,
                    headers=headers,
                )

            credential = store.get_credential(credential_id)
            if not credential:
                return error_response(f"Credential not found: {credential_id}", 404)

            # Verify ownership
            if credential.user_id != user_id:
                user = self.get_current_user(handler)
                is_admin = user and _has_permission(
                    user.role if hasattr(user, "role") else None, "gateway:admin"
                )
                if not is_admin:
                    return error_response("Access denied", 403)

            # Validate new secret
            new_secret = body.get("secret")
            is_valid, error = validate_credential_secret(
                new_secret, credential.credential_type.value
            )
            if not is_valid or not isinstance(new_secret, str):
                return error_response(error or "Invalid credential secret", 400)

            # Rotate
            credential = store.rotate_credential(credential_id, new_secret)
            if credential is None:
                return error_response(f"Credential not found: {credential_id}", 404)

            # Audit
            store.add_audit_entry(
                action="credential.rotate",
                actor_id=user_id,
                resource_type="credential",
                resource_id=credential_id,
                result="success",
            )

            logger.info("Rotated credential %s", credential_id)
            return json_response(
                {
                    "rotated": True,
                    "credential_id": credential_id,
                    "rotated_at": credential.last_rotated_at.isoformat()
                    if credential.last_rotated_at
                    else None,
                }
            )

        except (KeyError, ValueError, OSError, RuntimeError) as e:
            logger.error("Error rotating credential %s: %s", credential_id, e)
            return error_response(safe_error_message(e, "gateway"), 500)

    @require_permission("gateway:credentials.delete")
    @rate_limit(requests_per_minute=20, limiter_name="openclaw_gateway_delete_cred")
    def _handle_delete_credential(self, credential_id: str, handler: Any) -> HandlerResult:
        """Delete a credential."""
        try:
            store = _get_store()
            user_id = self._get_user_id(handler)
            credential = store.get_credential(credential_id)
            if not credential:
                return error_response(f"Credential not found: {credential_id}", 404)

            # Verify ownership
            if credential.user_id != user_id:
                user = self.get_current_user(handler)
                is_admin = user and _has_permission(
                    user.role if hasattr(user, "role") else None, "gateway:admin"
                )
                if not is_admin:
                    return error_response("Access denied", 403)

            # Delete
            store.delete_credential(credential_id)

            # Audit
            store.add_audit_entry(
                action="credential.delete",
                actor_id=user_id,
                resource_type="credential",
                resource_id=credential_id,
                result="success",
            )

            logger.info("Deleted credential %s", credential_id)
            return json_response({"deleted": True, "credential_id": credential_id})

        except (KeyError, ValueError, OSError, RuntimeError) as e:
            logger.error("Error deleting credential %s: %s", credential_id, e)
            return error_response(safe_error_message(e, "gateway"), 500)


__all__ = [
    # Rate limiting
    "CREDENTIAL_ROTATION_WINDOW_SECONDS",
    "MAX_CREDENTIAL_ROTATIONS_PER_HOUR",
    "CredentialRotationRateLimiter",
    "_get_credential_rotation_limiter",
    # Mixin
    "CredentialHandlerMixin",
]
