"""
Global Exception Handlers for FastAPI.

Provides consistent error responses across all endpoints.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Base API error with status code and message."""

    def __init__(
        self,
        message: str,
        status_code: int = 500,
        code: str = "internal_error",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.details = details or {}


class NotFoundError(APIError):
    """Resource not found error."""

    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, status_code=404, code="not_found")


class UnauthorizedError(APIError):
    """Authentication required error."""

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, status_code=401, code="unauthorized")


class ForbiddenError(APIError):
    """Permission denied error."""

    def __init__(self, message: str = "Permission denied"):
        super().__init__(message, status_code=403, code="forbidden")


class RateLimitError(APIError):
    """Rate limit exceeded error."""

    def __init__(self, message: str = "Rate limit exceeded", retry_after: int = 60):
        super().__init__(message, status_code=429, code="rate_limit_exceeded")
        self.retry_after = retry_after


def setup_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        """Handle custom API errors."""
        content: dict[str, Any] = {
            "error": exc.message,
            "code": exc.code,
        }
        if exc.details:
            content["details"] = exc.details

        headers = {}
        if isinstance(exc, RateLimitError):
            headers["Retry-After"] = str(exc.retry_after)

        return JSONResponse(
            status_code=exc.status_code,
            content=content,
            headers=headers,
        )

    from aragora.knowledge.fact_store import OrgScopeRequiredError

    @app.exception_handler(OrgScopeRequiredError)
    async def fact_scope_error_handler(
        request: Request, exc: OrgScopeRequiredError
    ) -> JSONResponse:
        """Fact routes that do not carry the caller's organization are closed."""
        return JSONResponse(
            status_code=403,
            content={
                "error": "Knowledge fact access is closed until it is organization-scoped",
                "code": "knowledge_fact_access_closed",
            },
        )

    @app.exception_handler(ValidationError)
    async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
        """Handle Pydantic validation errors."""
        return JSONResponse(
            status_code=422,
            content={
                "error": "Validation error",
                "code": "validation_error",
                "details": exc.errors(),
            },
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        """Handle value errors as bad requests."""
        return JSONResponse(
            status_code=400,
            content={
                "error": str(exc),
                "code": "bad_request",
            },
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected errors."""
        logger.exception("Unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "code": "internal_error",
            },
        )
