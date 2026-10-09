"""
Response builders for HTTP handlers.

Provides standardized JSON response formatting with consistent error handling.

Functions:
    json_response: Create a JSON response with any data
    error_response: Create a structured error response (returns HandlerResult)
    error_dict: Create a standardized error dict (for dict-returning handlers)
    validation_error: Create a validation error response
    not_found_error: Create a not found error response
    permission_denied_error: Create a permission denied error response
    rate_limit_error: Create a rate limit error response

Classes:
    HandlerResult: Dataclass representing an HTTP response
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from aragora.api_errors import ErrorCode

_logger = logging.getLogger(__name__)


@dataclass
class HandlerResult:
    """Result of handling an HTTP request.

    Attributes:
        status_code: HTTP status code (200, 400, 500, etc.)
        content_type: MIME type of the response body
        body: Raw bytes of the response body
        headers: Optional HTTP headers to include
    """

    status_code: int
    content_type: str
    body: bytes
    headers: dict | None = None

    def __post_init__(self) -> None:
        if self.headers is None:
            self.headers = {}

    @property
    def status(self) -> int:
        """Alias for status_code for compatibility with aiohttp-like responses."""
        return self.status_code

    def to_dict(self) -> dict[str, Any]:
        """Return a structured dict with status and decoded JSON body."""
        try:
            body_data = json.loads(self.body.decode("utf-8")) if self.body else {}
        except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
            body_data = {}
        return {
            "status": self.status_code,
            "body": body_data,
            "headers": self.headers or {},
            "content_type": self.content_type,
        }

    def _tuple_body(self) -> Any:
        """Return a tuple-style body value (decoded JSON when applicable)."""
        if self.body is None:
            return b""
        if self.content_type and "json" in self.content_type:
            try:
                raw = (
                    self.body.decode("utf-8")
                    if isinstance(self.body, (bytes, bytearray))
                    else self.body
                )
                # SCIM responses are validated via substring checks in tests; return raw JSON text.
                if self.content_type and "scim" in self.content_type:
                    return raw
                return json.loads(raw) if raw else {}
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
                return self.body
        return self.body

    def __iter__(self) -> Any:
        """Allow tuple-style unpacking (body, status, headers/content_type)."""
        yield self._tuple_body()
        yield self.status_code
        if self.content_type and "scim" in self.content_type:
            yield self.content_type
        else:
            yield self.headers or {}

    def __getitem__(self, key: str | int) -> Any:
        """Dictionary-like and tuple-style access for common response fields."""
        if isinstance(key, int):
            if key == 0:
                return self._tuple_body()
            if key == 1:
                return self.status_code
            if key == 2:
                return self.headers or {}
            raise IndexError(key)
        if key == "status":
            return self.status_code
        if key == "body":
            try:
                return self.body.decode("utf-8") if self.body else ""
            except (UnicodeDecodeError, AttributeError):
                return self.body
        if key == "headers":
            return self.headers or {}
        if key == "content_type":
            return self.content_type
        raise KeyError(key)


def json_response(
    data: Any,
    status: int = 200,
    headers: dict | None = None,
) -> HandlerResult:
    """Create a JSON response.

    Args:
        data: Any JSON-serializable data (uses str() for non-serializable types)
        status: HTTP status code (default: 200)
        headers: Optional additional headers

    Returns:
        HandlerResult with JSON body and application/json content type

    Example:
        return json_response({"items": items, "count": len(items)})
        return json_response({"created": True}, status=201)
    """
    body = json.dumps(data, default=str).encode("utf-8")
    return HandlerResult(
        status_code=status,
        content_type="application/json",
        body=body,
        headers=headers or {},
    )


def error_response(
    message: str,
    status: int = 400,
    headers: dict | None = None,
    *,
    code: str | None = None,
    trace_id: str | None = None,
    suggestion: str | None = None,
    details: dict | None = None,
    structured: bool = False,
) -> HandlerResult:
    """Create an error response.

    Args:
        message: Human-readable error message
        status: HTTP status code (default: 400)
        headers: Optional additional headers
        code: Optional machine-readable error code (e.g., "VALIDATION_ERROR")
        trace_id: Optional request trace ID for debugging
        suggestion: Optional suggestion for resolving the error
        details: Optional additional error details
        structured: If True, always use structured format. If False,
                   only include additional fields if provided.

    Returns:
        HandlerResult with error JSON

    Examples:
        # Simple error (backward compatible)
        error_response("Invalid input", 400)
        # -> {"error": "Invalid input"}

        # Structured error with code and suggestion
        error_response(
            "Field 'name' is required",
            400,
            code="VALIDATION_ERROR",
            suggestion="Include 'name' in request body"
        )
        # -> {"error": {"code": "VALIDATION_ERROR", "message": "...", "suggestion": "..."}}
    """
    # SECURITY: For 5xx errors, sanitize the message to prevent leaking internal
    # details (file paths, SQL queries, stack traces) to clients.  The original
    # message is logged server-side for debugging.
    if status >= 500:
        _include_details = os.environ.get("ARAGORA_ENV", "").lower() != "production"
        if not _include_details:
            if message and message != "Internal server error":
                _logger.error("Sanitized 500 error detail: %s", message)
                message = "Internal server error"

    # Build error payload
    if structured or code or trace_id or suggestion or details:
        # Use structured format
        error_obj: dict[str, Any] = {"message": message}
        if code:
            error_obj["code"] = code
        if trace_id:
            error_obj["trace_id"] = trace_id
        if suggestion:
            error_obj["suggestion"] = suggestion
        if details:
            error_obj["details"] = details
        payload: dict[str, Any] = {"error": error_obj}
    else:
        # Simple format for backward compatibility
        payload = {"error": message}

    return json_response(payload, status=status, headers=headers)


def validation_error(
    message: str,
    field: str | None = None,
    *,
    trace_id: str | None = None,
    headers: dict | None = None,
) -> HandlerResult:
    """Create a validation error response with standardized format.

    Always uses structured format with VALIDATION_ERROR code.

    Args:
        message: Human-readable validation error message
        field: Optional field name that failed validation
        trace_id: Optional request trace ID for debugging
        headers: Optional additional headers

    Returns:
        HandlerResult with 400 status and structured error

    Examples:
        validation_error("Field 'name' is required", field="name")
        # -> {"error": {"code": "VALIDATION_ERROR", "message": "...", "details": {"field": "name"}}}

        validation_error("Invalid email format")
        # -> {"error": {"code": "VALIDATION_ERROR", "message": "Invalid email format"}}
    """
    details = {"field": field} if field else None
    return error_response(
        message,
        status=400,
        code=ErrorCode.VALIDATION_ERROR.value,
        trace_id=trace_id,
        details=details,
        headers=headers,
    )


def not_found_error(
    resource_type: str,
    resource_id: str | None = None,
    *,
    trace_id: str | None = None,
    headers: dict | None = None,
) -> HandlerResult:
    """Create a not found error response with standardized format.

    Always uses structured format with NOT_FOUND code.

    Args:
        resource_type: Type of resource that was not found (e.g., "Debate", "User")
        resource_id: Optional ID of the resource that was not found
        trace_id: Optional request trace ID for debugging
        headers: Optional additional headers

    Returns:
        HandlerResult with 404 status and structured error

    Examples:
        not_found_error("Debate", "abc123")
        # -> {"error": {"code": "NOT_FOUND", "message": "Debate not found", "details": {"resource_type": "Debate", "resource_id": "abc123"}}}

        not_found_error("User")
        # -> {"error": {"code": "NOT_FOUND", "message": "User not found", "details": {"resource_type": "User"}}}
    """
    message = f"{resource_type} not found"
    details: dict[str, Any] = {"resource_type": resource_type}
    if resource_id:
        details["resource_id"] = resource_id
    return error_response(
        message,
        status=404,
        code=ErrorCode.NOT_FOUND.value,
        trace_id=trace_id,
        details=details,
        headers=headers,
    )


def permission_denied_error(
    permission: str | None = None,
    *,
    message: str | None = None,
    trace_id: str | None = None,
    headers: dict | None = None,
) -> HandlerResult:
    """Create a permission denied error response with standardized format.

    Always uses structured format with FORBIDDEN code.

    Args:
        permission: Optional permission that was missing
        message: Optional custom message (defaults to "Permission denied")
        trace_id: Optional request trace ID for debugging
        headers: Optional additional headers

    Returns:
        HandlerResult with 403 status and structured error

    Examples:
        permission_denied_error("backups:read")
        # -> {"error": {"code": "FORBIDDEN", "message": "Permission denied", "details": {"permission": "backups:read"}}}

        permission_denied_error(message="Admin access required")
        # -> {"error": {"code": "FORBIDDEN", "message": "Admin access required"}}
    """
    err_message = message or "Permission denied"
    details = {"permission": permission} if permission else None
    return error_response(
        err_message,
        status=403,
        code=ErrorCode.FORBIDDEN.value,
        trace_id=trace_id,
        details=details,
        headers=headers,
    )


def rate_limit_error(
    retry_after: int | None = None,
    *,
    message: str | None = None,
    trace_id: str | None = None,
    headers: dict | None = None,
) -> HandlerResult:
    """Create a rate limit error response with standardized format.

    Always uses structured format with RATE_LIMITED code.
    Automatically adds Retry-After header when retry_after is provided.

    Args:
        retry_after: Optional seconds until rate limit resets (also added as header)
        message: Optional custom message (defaults to "Rate limit exceeded")
        trace_id: Optional request trace ID for debugging
        headers: Optional additional headers

    Returns:
        HandlerResult with 429 status and structured error

    Examples:
        rate_limit_error(retry_after=60)
        # -> {"error": {"code": "RATE_LIMITED", "message": "Rate limit exceeded", "details": {"retry_after": 60}}}
        # Headers: {"Retry-After": "60"}

        rate_limit_error(message="Too many requests", retry_after=30)
        # -> {"error": {"code": "RATE_LIMITED", "message": "Too many requests", "details": {"retry_after": 30}}}
    """
    err_message = message or "Rate limit exceeded"
    details = {"retry_after": retry_after} if retry_after is not None else None

    # Build headers with Retry-After
    all_headers = headers.copy() if headers else {}
    if retry_after is not None:
        all_headers["Retry-After"] = str(retry_after)

    return error_response(
        err_message,
        status=429,
        code=ErrorCode.RATE_LIMITED.value,
        trace_id=trace_id,
        details=details,
        headers=all_headers,
    )


def success_response(
    data: Any,
    message: str | None = None,
    headers: dict | None = None,
) -> HandlerResult:
    """Create a success response with standard format.

    Convenience wrapper around json_response for consistent success responses.
    Wraps ``data`` in a ``{"success": true, "data": data}`` envelope.

    Args:
        data: Response data payload
        message: Optional success message
        headers: Optional additional headers

    Returns:
        HandlerResult with success JSON body

    Example:
        return success_response({"id": "123"})
        # -> {"success": true, "data": {"id": "123"}}

        return success_response(items, message="Found 5 items")
        # -> {"success": true, "data": items, "message": "Found 5 items"}
    """
    payload: dict[str, Any] = {"success": True, "data": data}
    if message:
        payload["message"] = message
    return json_response(payload, status=200, headers=headers)


def error_dict(
    message: str,
    *,
    code: str | None = None,
    status: int | None = None,
) -> dict[str, Any]:
    """Create a standardized error dict for handlers that return dicts.

    Use this instead of inline ``{"error": "..."}`` dicts to ensure consistent
    error format across all handlers.

    Args:
        message: Human-readable error message
        code: Optional machine-readable error code (e.g., "NOT_FOUND")
        status: Optional HTTP status code hint for the server layer

    Returns:
        Dict with standardized error structure

    Examples:
        return error_dict("Not found", code="NOT_FOUND", status=404)
        # -> {"error": "Not found", "code": "NOT_FOUND", "status": 404}

        return error_dict("Extensions not initialized")
        # -> {"error": "Extensions not initialized"}
    """
    result: dict[str, Any] = {"error": message}
    if code:
        result["code"] = code
    if status is not None:
        result["status"] = status
    return result


def html_response(
    content: str,
    status: int = 200,
    headers: dict | None = None,
    *,
    escape_content: bool = False,
    nonce: str | None = None,
) -> HandlerResult:
    """Create an HTML response.

    Args:
        content: HTML string content
        status: HTTP status code (default: 200)
        headers: Optional additional headers
        escape_content: If True, HTML-escape the content for XSS protection
        nonce: Optional CSP nonce to include in Content-Security-Policy header

    Returns:
        HandlerResult with HTML body and text/html content type
    """
    if escape_content:
        from aragora.server.middleware.xss_protection import escape_html

        content = escape_html(content)

    all_headers = headers.copy() if headers else {}

    # Add CSP header with nonce if provided
    if nonce:
        all_headers["Content-Security-Policy"] = (
            f"default-src 'self'; "
            f"script-src 'self' 'nonce-{nonce}'; "
            f"style-src 'self' 'unsafe-inline'; "
            f"img-src 'self' data: https:; "
            f"font-src 'self'; "
            f"connect-src 'self'"
        )

    return HandlerResult(
        status_code=status,
        content_type="text/html; charset=utf-8",
        body=content.encode("utf-8"),
        headers=all_headers,
    )


def safe_html_response(
    builder_or_content: Any,
    status: int = 200,
    headers: dict | None = None,
    *,
    nonce: str | None = None,
) -> HandlerResult:
    """Create an HTML response from a SafeHTMLBuilder or pre-escaped content.

    This is the recommended way to return HTML responses when the content
    includes user-provided data. Use SafeHTMLBuilder to construct HTML
    with automatic escaping.

    Args:
        builder_or_content: Either a SafeHTMLBuilder instance or a pre-escaped
            HTML string. If a SafeHTMLBuilder, .build() is called automatically.
        status: HTTP status code (default: 200)
        headers: Optional additional headers
        nonce: Optional CSP nonce to include in Content-Security-Policy header

    Returns:
        HandlerResult with HTML body and text/html content type

    Example:
        from aragora.server.middleware.xss_protection import SafeHTMLBuilder

        builder = SafeHTMLBuilder()
        builder.add_raw("<!DOCTYPE html><html><body>")
        builder.add_element("h1", user_provided_title)  # Auto-escaped
        builder.add_element("p", user_provided_content)
        builder.add_raw("</body></html>")
        return safe_html_response(builder)
    """
    from aragora.server.middleware.xss_protection import SafeHTMLBuilder

    if isinstance(builder_or_content, SafeHTMLBuilder):
        content = builder_or_content.build()
    else:
        content = str(builder_or_content)

    return html_response(content, status=status, headers=headers, nonce=nonce)


def redirect_response(
    location: str,
    status: int = 302,
    headers: dict | None = None,
) -> HandlerResult:
    """Create a redirect response.

    Args:
        location: URL to redirect to
        status: HTTP status code (default: 302 Found)
        headers: Optional additional headers

    Returns:
        HandlerResult with Location header for redirect
    """
    all_headers = headers.copy() if headers else {}
    all_headers["Location"] = location
    return HandlerResult(
        status_code=status,
        content_type="text/plain",
        body=b"",
        headers=all_headers,
    )


# =============================================================================
# Pagination Helpers
# =============================================================================


def paginated_response(
    items: list[Any],
    *,
    total: int,
    limit: int,
    offset: int = 0,
    headers: dict | None = None,
) -> HandlerResult:
    """Create a paginated response with standardized format.

    This function provides a consistent pagination format across all handlers.
    The standardized format uses "data" for items and a "pagination" object
    containing metadata.

    Args:
        items: List of items for the current page
        total: Total number of items across all pages
        limit: Maximum items per page
        offset: Number of items skipped (0-indexed)
        headers: Optional additional HTTP headers

    Returns:
        HandlerResult with format:
        {"data": items, "pagination": {"total": N, "limit": L, "offset": O, "has_more": bool}}

    Example:
        # Return first page of 20 items from 55 total
        return paginated_response(
            items=results[:20],
            total=55,
            limit=20,
            offset=0,
        )
        # -> {"data": [...], "pagination": {"total": 55, "limit": 20, "offset": 0, "has_more": true}}
    """
    has_more = offset + len(items) < total

    payload = {
        "data": items,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        },
    }

    return json_response(payload, status=200, headers=headers)


def parse_pagination_params(
    query_params: dict[str, Any],
    *,
    default_limit: int = 20,
    max_limit: int = 100,
) -> tuple[int, int]:
    """Parse and validate limit/offset from query params.

    Extracts pagination parameters with bounds checking to prevent
    abuse and ensure reasonable defaults.

    Args:
        query_params: Dictionary of query parameters from the request
        default_limit: Default limit if not specified (default: 20)
        max_limit: Maximum allowed limit (default: 100)

    Returns:
        Tuple of (limit, offset) with bounds checking:
        - limit: Clamped to [1, max_limit]
        - offset: Clamped to >= 0

    Example:
        limit, offset = parse_pagination_params(
            {"limit": "50", "offset": "10"},
            default_limit=20,
            max_limit=100,
        )
        # -> (50, 10)

        # With negative values
        limit, offset = parse_pagination_params({"limit": "-5", "offset": "-10"})
        # -> (20, 0)  # Uses defaults for invalid values
    """

    def _get_int(params: dict[str, Any], key: str, default: int) -> int:
        """Safely extract integer from params."""
        value = params.get(key, default)
        if isinstance(value, list):
            value = value[0] if value else default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    # Extract limit with bounds checking
    raw_limit = _get_int(query_params, "limit", default_limit)
    if raw_limit < 1:
        limit = default_limit
    elif raw_limit > max_limit:
        limit = max_limit
    else:
        limit = raw_limit

    # Extract offset with bounds checking (must be non-negative)
    raw_offset = _get_int(query_params, "offset", 0)
    offset = max(0, raw_offset)

    return limit, offset


def normalize_pagination_response(response: dict[str, Any]) -> dict[str, Any]:
    """Convert various pagination formats to standard format.

    This function provides backward compatibility by converting legacy
    pagination response formats to the standardized format.

    Supported input formats:
    - {"items": [...], "total": N, ...} -> {"data": [...], "pagination": {...}}
    - {"results": [...], "total_count": N, ...} -> {"data": [...], "pagination": {...}}
    - {"data": [...], "count": N, ...} -> {"data": [...], "pagination": {...}}
    - Already standardized format is returned unchanged

    Args:
        response: Response dict in any supported pagination format

    Returns:
        Dict with standardized format:
        {"data": [...], "pagination": {"total": N, "limit": L, "offset": O, "has_more": bool}}

    Example:
        # Convert legacy format
        legacy = {"items": [1, 2, 3], "total": 10, "limit": 3, "offset": 0}
        standard = normalize_pagination_response(legacy)
        # -> {"data": [1, 2, 3], "pagination": {"total": 10, "limit": 3, "offset": 0, "has_more": true}}
    """
    # Already in standard format
    if "data" in response and "pagination" in response:
        return response

    # Extract items from various keys
    items: list[Any] = []
    if "items" in response:
        items = response["items"]
    elif "results" in response:
        items = response["results"]
    elif "data" in response:
        items = response["data"]

    # Extract total from various keys
    total = 0
    if "total" in response:
        total = response["total"]
    elif "total_count" in response:
        total = response["total_count"]
    elif "count" in response:
        total = response["count"]

    # Extract limit (default to length of items if not specified)
    limit = response.get("limit", len(items) if items else 20)

    # Extract offset
    offset = response.get("offset", 0)

    # Calculate has_more
    has_more = offset + len(items) < total if isinstance(items, list) else False

    return {
        "data": items,
        "pagination": {
            "total": total,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
        },
    }


__all__ = [
    # Core types
    "HandlerResult",
    # Response builders
    "json_response",
    "error_response",
    "success_response",
    "html_response",
    "safe_html_response",
    "redirect_response",
    "error_dict",
    # Standardized error helpers
    "validation_error",
    "not_found_error",
    "permission_denied_error",
    "rate_limit_error",
    # Pagination helpers
    "paginated_response",
    "parse_pagination_params",
    "normalize_pagination_response",
    # Re-exported from errors.py for convenience
    "ErrorCode",
]
