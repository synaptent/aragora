"""
Gateway Credentials Handler - HTTP endpoints for credential management.

Stability: STABLE
Graduated from EXPERIMENTAL on 2026-02-02.

Provides API endpoints for securely storing, listing, rotating, and deleting
gateway credentials. CRITICAL: credential values/secrets are NEVER returned
in any response - only metadata is exposed.

Routes:
    POST   /api/v1/gateway/credentials              - Store a new credential
    GET    /api/v1/gateway/credentials               - List credentials (metadata only)
    GET    /api/v1/gateway/credentials/{id}          - Get credential metadata
    DELETE /api/v1/gateway/credentials/{id}          - Delete a credential
    POST   /api/v1/gateway/credentials/{id}/rotate   - Rotate a credential
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from aragora.resilience import CircuitBreaker
from aragora.rbac.decorators import require_permission

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    log_request,
)
from aragora.server.handlers.utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)


# =============================================================================
# Circuit Breaker Configuration
# =============================================================================

# Circuit breaker for gateway credentials operations
# Opens after 5 consecutive failures, recovers after 30 seconds
_gateway_credentials_circuit_breaker = CircuitBreaker(
    name="gateway_credentials_handler",
    failure_threshold=5,
    cooldown_seconds=30.0,
    half_open_success_threshold=2,
    half_open_max_calls=3,
)
_gateway_credentials_circuit_breaker_lock = threading.Lock()


def get_gateway_credentials_circuit_breaker() -> CircuitBreaker:
    """Get the global circuit breaker for gateway credentials operations."""
    return _gateway_credentials_circuit_breaker


def get_gateway_credentials_circuit_breaker_status() -> dict[str, Any]:
    """Get current status of the gateway credentials circuit breaker."""
    return _gateway_credentials_circuit_breaker.to_dict()


def reset_gateway_credentials_circuit_breaker() -> None:
    """Reset the global circuit breaker (for testing)."""
    with _gateway_credentials_circuit_breaker_lock:
        _gateway_credentials_circuit_breaker._single_failures = 0
        _gateway_credentials_circuit_breaker._single_open_at = 0.0
        _gateway_credentials_circuit_breaker._single_successes = 0
        _gateway_credentials_circuit_breaker._single_half_open_calls = 0


# Validation constants
SERVICE_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]{0,127}$")
VALID_CREDENTIAL_TYPES = {"api_key", "oauth_token", "bearer_token", "basic_auth", "custom"}


class GatewayCredentialsHandler(BaseHandler):
    """
    HTTP request handler for gateway credential management endpoints.

    Provides REST API for storing, listing, rotating, and deleting
    gateway credentials. Credential values are NEVER included in responses.

    Uses CredentialProxy from server context when available, otherwise
    falls back to in-memory storage (metadata only after registration).
    """

    ROUTES = [
        "/api/v1/gateway/credentials",
        "/api/v1/gateway/credentials/*",
    ]

    def __init__(self, server_context: Any) -> None:
        super().__init__(server_context)
        # In-memory fallback storage for credential metadata
        self._credentials: dict[str, dict[str, Any]] = {}

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return path.startswith("/api/v1/gateway/credentials")

    def _get_credential_store(self) -> Any | None:
        """Get CredentialProxy from server context if available."""
        return self.ctx.get("credential_proxy")

    def _get_credentials(self) -> dict[str, dict[str, Any]]:
        """Get the in-memory credentials metadata store."""
        return self._credentials

    def _extract_credential_id(self, path: str) -> str | None:
        """Extract credential ID from path like /api/v1/gateway/credentials/{id}."""
        parts = path.rstrip("/").split("/")
        # Expected: ["", "api", "v1", "gateway", "credentials", "{id}"]
        if len(parts) >= 6 and parts[4] == "credentials":
            cred_id = parts[5]
            if cred_id and cred_id != "credentials":
                return cred_id
        return None

    def _is_rotate_path(self, path: str) -> bool:
        """Check if path is a rotate request: /api/v1/gateway/credentials/{id}/rotate."""
        parts = path.rstrip("/").split("/")
        # Expected: ["", "api", "v1", "gateway", "credentials", "{id}", "rotate"]
        return len(parts) >= 7 and parts[4] == "credentials" and parts[6] == "rotate"

    def _validate_service_name(self, service_name: str) -> str | None:
        """Validate service_name. Returns error message or None if valid."""
        if not service_name:
            return "service_name is required"
        if not SERVICE_NAME_PATTERN.match(service_name):
            return (
                "Invalid service_name. Must be alphanumeric with hyphens, "
                "start with alphanumeric, and be at most 128 characters."
            )
        return None

    def _validate_credential_type(self, credential_type: str) -> str | None:
        """Validate credential_type. Returns error message or None if valid."""
        if not credential_type:
            return "credential_type is required"
        if credential_type not in VALID_CREDENTIAL_TYPES:
            return (
                f"Invalid credential_type: {credential_type}. "
                f"Must be one of: {', '.join(sorted(VALID_CREDENTIAL_TYPES))}"
            )
        return None

    def _make_credential_metadata(
        self,
        credential_id: str,
        service_name: str,
        credential_type: str,
        tenant_id: str | None = None,
        scopes: list[str] | None = None,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: str = "active",
    ) -> dict[str, Any]:
        """Create a credential metadata dict (never includes the value)."""
        now = datetime.now(timezone.utc).isoformat()
        result: dict[str, Any] = {
            "credential_id": credential_id,
            "service_name": service_name,
            "credential_type": credential_type,
            "status": status,
            "created_at": now,
        }
        if tenant_id is not None:
            result["tenant_id"] = tenant_id
        if scopes is not None:
            result["scopes"] = scopes
        if expires_at is not None:
            result["expires_at"] = expires_at
        if metadata is not None:
            result["metadata"] = metadata
        return result

    # =========================================================================
    # Route Handlers
    # =========================================================================

    @require_permission("gateway:credential.read")
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests."""
        if not self.can_handle(path):
            return None

        # GET /api/v1/gateway/credentials/{id}
        credential_id = self._extract_credential_id(path)
        if credential_id:
            return self._handle_get_credential(credential_id, handler)

        # GET /api/v1/gateway/credentials
        if path.rstrip("/") == "/api/v1/gateway/credentials":
            return self._handle_list_credentials(query_params, handler)

        return None

    @handle_errors("gateway credentials creation")
    @require_permission("gateway:credential.create")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if not self.can_handle(path):
            return None

        # POST /api/v1/gateway/credentials/{id}/rotate
        if self._is_rotate_path(path):
            credential_id = self._extract_credential_id(path)
            if credential_id:
                return self._handle_rotate_credential(credential_id, handler)

        # POST /api/v1/gateway/credentials
        if path.rstrip("/") == "/api/v1/gateway/credentials":
            return self._handle_store_credential(handler)

        return None

    @handle_errors("gateway credentials deletion")
    @require_permission("gateway:credential.delete")
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle DELETE requests."""
        if not self.can_handle(path):
            return None

        # DELETE /api/v1/gateway/credentials/{id}
        credential_id = self._extract_credential_id(path)
        if credential_id:
            return self._handle_delete_credential(credential_id, handler)

        return None

    # =========================================================================
    # Credential Operations
    # =========================================================================

    @rate_limit(requests_per_minute=5, limiter_name="gateway_credentials_store")
    @handle_errors("store gateway credential")
    @log_request("store gateway credential")
    def _handle_store_credential(self, handler: Any) -> HandlerResult:
        """Handle POST /api/v1/gateway/credentials."""
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        # Validate required fields
        service_name = body.get("service_name")
        if not service_name:
            return error_response("service_name is required", 400)

        credential_type = body.get("credential_type")
        if not credential_type:
            return error_response("credential_type is required", 400)

        value = body.get("value")
        if not value or not isinstance(value, str) or not value.strip():
            return error_response("value is required and must be a non-empty string", 400)

        # Validate service_name format
        name_error = self._validate_service_name(service_name)
        if name_error:
            return error_response(name_error, 400)

        # Validate credential_type
        type_error = self._validate_credential_type(credential_type)
        if type_error:
            return error_response(type_error, 400)

        # Generate credential ID
        credential_id = f"cred_{uuid.uuid4().hex[:12]}"

        # Extract optional fields
        tenant_id = body.get("tenant_id")
        scopes = body.get("scopes")
        expires_at = body.get("expires_at")
        meta = body.get("metadata")

        # Store via credential proxy if available
        proxy = self._get_credential_store()
        if proxy is not None:
            try:
                proxy.store(
                    credential_id=credential_id,
                    service_name=service_name,
                    credential_type=credential_type,
                    value=value,
                    tenant_id=tenant_id,
                    scopes=scopes,
                    expires_at=expires_at,
                    metadata=meta,
                )
            except (RuntimeError, OSError, AttributeError, TypeError) as e:
                logger.error("Failed to store credential via proxy: %s", e)
                return error_response("Failed to store credential", 500)

        # Store metadata in-memory (NEVER store the value)
        cred_metadata = self._make_credential_metadata(
            credential_id=credential_id,
            service_name=service_name,
            credential_type=credential_type,
            tenant_id=tenant_id,
            scopes=scopes,
            expires_at=expires_at,
            metadata=meta,
        )
        self._credentials[credential_id] = cred_metadata

        logger.info(
            "Stored credential: id=%s service=%s type=%s",
            credential_id,
            service_name,
            credential_type,
        )

        # Build response (NEVER include value)
        response_data: dict[str, Any] = {
            "credential_id": credential_id,
            "service_name": service_name,
            "credential_type": credential_type,
            "created_at": cred_metadata["created_at"],
            "message": "Credential stored successfully",
        }
        if tenant_id is not None:
            response_data["tenant_id"] = tenant_id
        if scopes is not None:
            response_data["scopes"] = scopes
        if expires_at is not None:
            response_data["expires_at"] = expires_at

        return json_response(response_data, status=201)

    @rate_limit(requests_per_minute=30, limiter_name="gateway_credentials_list")
    @handle_errors("list gateway credentials")
    def _handle_list_credentials(self, query_params: dict[str, Any], handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/credentials."""
        credentials = self._get_credentials()

        cred_list = []
        for cred_id, meta in credentials.items():
            # NEVER include credential values - metadata only
            entry: dict[str, Any] = {
                "credential_id": meta.get("credential_id", cred_id),
                "service_name": meta.get("service_name", ""),
                "credential_type": meta.get("credential_type", ""),
                "status": meta.get("status", "active"),
                "created_at": meta.get("created_at", ""),
            }
            if "tenant_id" in meta:
                entry["tenant_id"] = meta["tenant_id"]
            if "expires_at" in meta:
                entry["expires_at"] = meta["expires_at"]
            cred_list.append(entry)

        return json_response(
            {
                "credentials": cred_list,
                "total": len(cred_list),
            }
        )

    @rate_limit(requests_per_minute=60, limiter_name="gateway_credentials_get")
    @handle_errors("get gateway credential")
    def _handle_get_credential(self, credential_id: str, handler: Any) -> HandlerResult:
        """Handle GET /api/v1/gateway/credentials/{id}."""
        credentials = self._get_credentials()

        if credential_id not in credentials:
            return error_response(f"Credential not found: {credential_id}", 404)

        meta = credentials[credential_id]

        # NEVER include credential values - metadata only
        response_data: dict[str, Any] = {
            "credential_id": meta.get("credential_id", credential_id),
            "service_name": meta.get("service_name", ""),
            "credential_type": meta.get("credential_type", ""),
            "status": meta.get("status", "active"),
            "created_at": meta.get("created_at", ""),
        }
        if "tenant_id" in meta:
            response_data["tenant_id"] = meta["tenant_id"]
        if "scopes" in meta:
            response_data["scopes"] = meta["scopes"]
        if "expires_at" in meta:
            response_data["expires_at"] = meta["expires_at"]
        if "metadata" in meta:
            response_data["metadata"] = meta["metadata"]

        return json_response(response_data)

    @rate_limit(requests_per_minute=10, limiter_name="gateway_credentials_delete")
    @handle_errors("delete gateway credential")
    @log_request("delete gateway credential")
    def _handle_delete_credential(self, credential_id: str, handler: Any) -> HandlerResult:
        """Handle DELETE /api/v1/gateway/credentials/{id}."""
        credentials = self._get_credentials()

        if credential_id not in credentials:
            return error_response(f"Credential not found: {credential_id}", 404)

        # Remove from proxy if available
        proxy = self._get_credential_store()
        if proxy is not None:
            try:
                proxy.delete(credential_id)
            except (RuntimeError, OSError, AttributeError) as e:
                logger.error("Failed to delete credential via proxy: %s", e)

        del credentials[credential_id]

        logger.info("Deleted credential: id=%s", credential_id)

        return json_response(
            {
                "credential_id": credential_id,
                "message": "Credential deleted successfully",
            }
        )

    @rate_limit(requests_per_minute=5, limiter_name="gateway_credentials_rotate")
    @handle_errors("rotate gateway credential")
    @log_request("rotate gateway credential")
    def _handle_rotate_credential(self, credential_id: str, handler: Any) -> HandlerResult:
        """Handle POST /api/v1/gateway/credentials/{id}/rotate."""
        credentials = self._get_credentials()

        if credential_id not in credentials:
            return error_response(f"Credential not found: {credential_id}", 404)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        new_value = body.get("value")
        if not new_value or not isinstance(new_value, str) or not new_value.strip():
            return error_response(
                "value is required for rotation and must be a non-empty string", 400
            )

        old_meta = credentials[credential_id]

        # Generate new credential ID
        new_credential_id = f"cred_{uuid.uuid4().hex[:12]}"

        # Mark old credential as rotated
        old_meta["status"] = "rotated"

        # Store via proxy if available
        proxy = self._get_credential_store()
        if proxy is not None:
            try:
                proxy.store(
                    credential_id=new_credential_id,
                    service_name=old_meta.get("service_name", ""),
                    credential_type=old_meta.get("credential_type", ""),
                    value=new_value,
                    tenant_id=old_meta.get("tenant_id"),
                    scopes=old_meta.get("scopes"),
                    expires_at=old_meta.get("expires_at"),
                    metadata=old_meta.get("metadata"),
                )
            except (RuntimeError, OSError, AttributeError, TypeError) as e:
                logger.error("Failed to store rotated credential via proxy: %s", e)
                # Revert old credential status
                old_meta["status"] = "active"
                return error_response("Failed to rotate credential", 500)

        # Create new credential metadata (NEVER store the value)
        new_meta = self._make_credential_metadata(
            credential_id=new_credential_id,
            service_name=old_meta.get("service_name", ""),
            credential_type=old_meta.get("credential_type", ""),
            tenant_id=old_meta.get("tenant_id"),
            scopes=old_meta.get("scopes"),
            expires_at=old_meta.get("expires_at"),
            metadata=old_meta.get("metadata"),
        )
        credentials[new_credential_id] = new_meta

        logger.info(
            "Rotated credential: old_id=%s new_id=%s service=%s",
            credential_id,
            new_credential_id,
            old_meta.get("service_name", ""),
        )

        # Response (NEVER include value)
        response_data: dict[str, Any] = {
            "credential_id": new_credential_id,
            "previous_credential_id": credential_id,
            "service_name": new_meta.get("service_name", ""),
            "credential_type": new_meta.get("credential_type", ""),
            "status": "active",
            "created_at": new_meta["created_at"],
            "message": "Credential rotated successfully",
        }

        return json_response(response_data, status=201)


__all__ = [
    "GatewayCredentialsHandler",
    "get_gateway_credentials_circuit_breaker",
    "get_gateway_credentials_circuit_breaker_status",
    "reset_gateway_credentials_circuit_breaker",
]
