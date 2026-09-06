"""
SCIM 2.0 Handler - HTTP endpoints for SCIM user/group provisioning.

Bridges the SCIM 2.0 server implementation (aragora.auth.scim) to the
unified server's BaseHandler routing system.

Provides RFC 7644 compliant endpoints:
    GET    /scim/v2/Users           - List users with filtering and pagination
    POST   /scim/v2/Users           - Create user
    GET    /scim/v2/Users/{id}      - Get user by ID
    PUT    /scim/v2/Users/{id}      - Replace user
    PATCH  /scim/v2/Users/{id}      - Partial update user
    DELETE /scim/v2/Users/{id}      - Delete user
    GET    /scim/v2/Groups          - List groups
    POST   /scim/v2/Groups          - Create group
    GET    /scim/v2/Groups/{id}     - Get group by ID
    PUT    /scim/v2/Groups/{id}     - Replace group
    PATCH  /scim/v2/Groups/{id}     - Partial update group
    DELETE /scim/v2/Groups/{id}     - Delete group
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
)
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.http_utils import run_async
from aragora.server.validation.query_params import safe_query_int

# SCIM handlers return HandlerResult for compatibility with BaseHandler
# Internal methods use tuple format which gets converted to HandlerResult

# SCIM imports
SCIMConfig: Any
SCIMServer: Any
try:
    from aragora.auth.scim.server import SCIMConfig as _SCIMConfig
    from aragora.auth.scim.server import SCIMServer as _SCIMServer

    SCIM_AVAILABLE = True
except ImportError:
    SCIM_AVAILABLE = False
    SCIMConfig = None
    SCIMServer = None
else:
    SCIMConfig = _SCIMConfig
    SCIMServer = _SCIMServer

logger = logging.getLogger(__name__)

# SCIM content type per RFC 7644
SCIM_CONTENT_TYPE = "application/scim+json"


class SCIMHandler(BaseHandler):
    """
    HTTP request handler for SCIM 2.0 provisioning endpoints.

    Routes requests to the SCIMServer implementation which handles
    user and group CRUD operations per RFC 7643/7644.
    """

    ROUTES = [
        "/scim/v2/Users",
        "/scim/v2/Users/*",
        "/scim/v2/Groups",
        "/scim/v2/Groups/*",
    ]

    def __init__(self, server_context):
        super().__init__(server_context)
        self._scim_server: SCIMServer | None = None

    def _get_scim_server(self) -> SCIMServer | None:
        """Get or create the SCIM server instance."""
        if not SCIM_AVAILABLE:
            return None
        if self._scim_server is None:
            config = SCIMConfig(
                bearer_token=os.environ.get("SCIM_BEARER_TOKEN", ""),
                tenant_id=os.environ.get("SCIM_TENANT_ID"),
                base_url=os.environ.get("SCIM_BASE_URL", ""),
            )
            self._scim_server = SCIMServer(config)
        return self._scim_server

    def _verify_bearer_token(self, handler: Any) -> HandlerResult | None:
        """Verify the SCIM bearer token from the Authorization header.

        Returns None if auth succeeds, or an error HandlerResult if it fails.
        """
        scim = self._get_scim_server()
        if not scim or not scim.config.bearer_token:
            return None  # No auth configured

        auth_header = ""
        if hasattr(handler, "headers"):
            auth_header = handler.headers.get("Authorization", "")

        if not auth_header:
            return self._scim_error("Authorization header required", 401)

        if not auth_header.startswith("Bearer "):
            return self._scim_error("Bearer token required", 401)

        token = auth_header[7:]
        if token != scim.config.bearer_token:
            return self._scim_error("Invalid bearer token", 401)

        return None

    def _scim_error(self, detail: str, status: int) -> HandlerResult:
        """Create a SCIM-formatted error response."""
        error_body = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:Error"],
            "detail": detail,
            "status": str(status),
        }
        return HandlerResult(
            status_code=status,
            content_type=SCIM_CONTENT_TYPE,
            body=json.dumps(error_body).encode("utf-8"),
        )

    def _scim_response(self, body: dict | None, status: int) -> HandlerResult:
        """Create a SCIM-formatted response."""
        if body is None and status == 204:
            return HandlerResult(
                status_code=204,
                content_type=SCIM_CONTENT_TYPE,
                body=b"",
            )
        return HandlerResult(
            status_code=status,
            content_type=SCIM_CONTENT_TYPE,
            body=json.dumps(body or {}).encode("utf-8"),
        )

    def _extract_resource_id(self, path: str, resource_type: str) -> str | None:
        """Extract resource ID from path like /scim/v2/Users/{id}."""
        prefix = f"/scim/v2/{resource_type}/"
        if path.startswith(prefix):
            resource_id = path[len(prefix) :]
            # Strip trailing slash and query params
            resource_id = resource_id.rstrip("/").split("?")[0]
            if resource_id:
                return resource_id
        return None

    def _read_json_body(self, handler: Any) -> dict[str, Any] | None:
        """Read and parse JSON body from the request handler."""
        try:
            body = self.ctx.get("body")
            if body and isinstance(body, dict):
                return body
        except (AttributeError, TypeError):
            pass

        # Fallback: try to read from handler
        try:
            if hasattr(handler, "rfile"):
                content_length = int(handler.headers.get("Content-Length", 0))
                if content_length > 0:
                    raw = handler.rfile.read(content_length)
                    return json.loads(raw)
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("SCIM: Failed to parse request body: %s", e)
        return None

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the given path."""
        return path.startswith("/scim/v2/")

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Handle GET requests."""
        if not self.can_handle(path):
            return None

        if not SCIM_AVAILABLE:
            return error_response("SCIM module not available", 503)

        # Verify bearer token
        auth_error = self._verify_bearer_token(handler)
        if auth_error:
            return auth_error

        scim = self._get_scim_server()
        if not scim:
            return error_response("SCIM server initialization failed", 503)

        # GET /scim/v2/Users
        if path.rstrip("/") == "/scim/v2/Users":
            start_index = safe_query_int(
                query_params, "startIndex", default=1, min_val=1, max_val=1000000
            )
            count = safe_query_int(query_params, "count", default=100, min_val=1, max_val=1000)
            filter_expr = query_params.get("filter")
            result = run_async(scim.list_users(start_index, count, filter_expr))
            return self._scim_response(result, 200)

        # GET /scim/v2/Users/{id}
        user_id = self._extract_resource_id(path, "Users")
        if user_id:
            result, status = run_async(scim.get_user(user_id))
            return self._scim_response(result, status)

        # GET /scim/v2/Groups
        if path.rstrip("/") == "/scim/v2/Groups":
            start_index = safe_query_int(
                query_params, "startIndex", default=1, min_val=1, max_val=1000000
            )
            count = safe_query_int(query_params, "count", default=100, min_val=1, max_val=1000)
            filter_expr = query_params.get("filter")
            result = run_async(scim.list_groups(start_index, count, filter_expr))
            return self._scim_response(result, 200)

        # GET /scim/v2/Groups/{id}
        group_id = self._extract_resource_id(path, "Groups")
        if group_id:
            result, status = run_async(scim.get_group(group_id))
            return self._scim_response(result, status)

        return None

    @handle_errors("SCIM provisioning")
    @require_permission("debates:write")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests."""
        if not self.can_handle(path):
            return None

        if not SCIM_AVAILABLE:
            return error_response("SCIM module not available", 503)

        auth_error = self._verify_bearer_token(handler)
        if auth_error:
            return auth_error

        scim = self._get_scim_server()
        if not scim:
            return error_response("SCIM server initialization failed", 503)

        body = self._read_json_body(handler)
        if body is None:
            return self._scim_error("Invalid JSON in request body", 400)

        # POST /scim/v2/Users
        if path.rstrip("/") == "/scim/v2/Users":
            result, status = run_async(scim.create_user(body))
            return self._scim_response(result, status)

        # POST /scim/v2/Groups
        if path.rstrip("/") == "/scim/v2/Groups":
            result, status = run_async(scim.create_group(body))
            return self._scim_response(result, status)

        return None

    @handle_errors("SCIM update")
    @require_permission("debates:write")
    def handle_put(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle PUT requests."""
        if not self.can_handle(path):
            return None

        if not SCIM_AVAILABLE:
            return error_response("SCIM module not available", 503)

        auth_error = self._verify_bearer_token(handler)
        if auth_error:
            return auth_error

        scim = self._get_scim_server()
        if not scim:
            return error_response("SCIM server initialization failed", 503)

        body = self._read_json_body(handler)
        if body is None:
            return self._scim_error("Invalid JSON in request body", 400)

        # PUT /scim/v2/Users/{id}
        user_id = self._extract_resource_id(path, "Users")
        if user_id:
            result, status = run_async(scim.replace_user(user_id, body))
            return self._scim_response(result, status)

        # PUT /scim/v2/Groups/{id}
        group_id = self._extract_resource_id(path, "Groups")
        if group_id:
            result, status = run_async(scim.replace_group(group_id, body))
            return self._scim_response(result, status)

        return None

    @handle_errors("SCIM patch")
    @require_permission("debates:read")
    def handle_patch(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle PATCH requests."""
        if not self.can_handle(path):
            return None

        if not SCIM_AVAILABLE:
            return error_response("SCIM module not available", 503)

        auth_error = self._verify_bearer_token(handler)
        if auth_error:
            return auth_error

        scim = self._get_scim_server()
        if not scim:
            return error_response("SCIM server initialization failed", 503)

        body = self._read_json_body(handler)
        if body is None:
            return self._scim_error("Invalid JSON in request body", 400)

        # PATCH /scim/v2/Users/{id}
        user_id = self._extract_resource_id(path, "Users")
        if user_id:
            result, status = run_async(scim.patch_user(user_id, body))
            return self._scim_response(result, status)

        # PATCH /scim/v2/Groups/{id}
        group_id = self._extract_resource_id(path, "Groups")
        if group_id:
            result, status = run_async(scim.patch_group(group_id, body))
            return self._scim_response(result, status)

        return None

    @require_permission("debates:delete")
    @handle_errors
    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle DELETE requests."""
        if not self.can_handle(path):
            return None

        if not SCIM_AVAILABLE:
            return error_response("SCIM module not available", 503)

        auth_error = self._verify_bearer_token(handler)
        if auth_error:
            return auth_error

        scim = self._get_scim_server()
        if not scim:
            return error_response("SCIM server initialization failed", 503)

        # DELETE /scim/v2/Users/{id}
        user_id = self._extract_resource_id(path, "Users")
        if user_id:
            result, status = run_async(scim.delete_user(user_id))
            return self._scim_response(result, status)

        # DELETE /scim/v2/Groups/{id}
        group_id = self._extract_resource_id(path, "Groups")
        if group_id:
            result, status = run_async(scim.delete_group(group_id))
            return self._scim_response(result, status)

        return None
