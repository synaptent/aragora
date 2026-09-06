"""
Data Classification Policy HTTP Handler.

Provides REST API endpoints for querying the active data classification
policy, classifying data, and validating handling operations.

Endpoints:
    GET  /api/v1/data-classification/policy        - Get the active classification policy
    POST /api/v1/data-classification/classify       - Classify data and return metadata
    POST /api/v1/data-classification/validate       - Validate a handling operation
    POST /api/v1/data-classification/enforce        - Enforce cross-context access rules
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.compliance.data_classification import (
    DataClassification,
    DataClassifier,
    PolicyEnforcer,
)
from aragora.rbac.decorators import require_permission
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
)
from aragora.server.handlers.utils.decorators import handle_errors
from aragora.server.handlers.utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)

# Module-level singleton instances (lazy-initialized)
_classifier: DataClassifier | None = None
_enforcer: PolicyEnforcer | None = None


def _get_classifier() -> DataClassifier:
    """Return the module-level DataClassifier singleton."""
    global _classifier
    if _classifier is None:
        _classifier = DataClassifier()
    return _classifier


def _get_enforcer() -> PolicyEnforcer:
    """Return the module-level PolicyEnforcer singleton."""
    global _enforcer
    if _enforcer is None:
        _enforcer = PolicyEnforcer(_get_classifier())
    return _enforcer


class DataClassificationHandler(BaseHandler):
    """HTTP handler for data classification policy endpoints.

    Provides read-only access to the active classification policy and
    operations for classifying data, validating handling, and enforcing
    cross-context access rules.
    """

    ROUTES = [
        "/api/v1/data-classification/policy",
        "/api/v1/data-classification/classify",
        "/api/v1/data-classification/validate",
        "/api/v1/data-classification/enforce",
    ]

    def __init__(self, server_context: dict[str, Any] | None = None):
        """Initialize with server context."""
        super().__init__(server_context or {})

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if path.startswith("/api/v1/data-classification"):
            return True
        return False

    @require_permission("data_classification:read")
    @rate_limit(requests_per_minute=30)
    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Route request to appropriate handler method."""
        method: str = getattr(handler, "command", "GET") if handler else "GET"
        body: dict[str, Any] = (self.read_json_body(handler) or {}) if handler else {}
        query_params = query_params or {}

        # GET /api/v1/data-classification/policy
        if path == "/api/v1/data-classification/policy" and method == "GET":
            return await self._get_policy(query_params)

        # POST /api/v1/data-classification/classify
        if path == "/api/v1/data-classification/classify" and method == "POST":
            return await self._classify_data(body)

        # POST /api/v1/data-classification/validate
        if path == "/api/v1/data-classification/validate" and method == "POST":
            return await self._validate_handling(body)

        # POST /api/v1/data-classification/enforce
        if path == "/api/v1/data-classification/enforce" and method == "POST":
            return await self._enforce_access(body)

        return error_response("Not found", 404)

    # -- GET /api/v1/data-classification/policy ----------------------------

    async def _get_policy(
        self,
        query_params: dict[str, Any],
    ) -> HandlerResult:
        """Return the active classification policy.

        Optional query parameter ``level`` to retrieve the policy for a
        single classification level.
        """
        classifier = _get_classifier()
        level_filter = query_params.get("level")

        if level_filter:
            try:
                level = DataClassification(level_filter)
            except ValueError:
                return error_response(
                    f"Invalid classification level: must be one of "
                    f"{[l.value for l in DataClassification]}",
                    400,
                )
            policy = classifier.get_policy(level)
            return json_response({"data": policy.to_dict()})

        active_policy = classifier.get_active_policy()
        return json_response({"data": active_policy})

    # -- POST /api/v1/data-classification/classify -------------------------

    @handle_errors("data classification")
    async def _classify_data(
        self,
        body: dict[str, Any],
    ) -> HandlerResult:
        """Classify the provided data and return classification metadata.

        Request body:
            data: dict - The data to classify
            context: str (optional) - Additional context for classification
        """
        data = body.get("data")
        if not isinstance(data, dict):
            return error_response("Request body must include 'data' as a dict", 400)

        context = body.get("context", "")
        if not isinstance(context, str):
            context = str(context)

        classifier = _get_classifier()
        metadata = classifier.tag(data, context=context)
        logger.info(
            "Data classified as %s (context=%s)",
            metadata.classification.value,
            context or "none",
        )
        return json_response({"data": metadata.to_dict()})

    # -- POST /api/v1/data-classification/validate -------------------------

    @handle_errors("data classification validation")
    async def _validate_handling(
        self,
        body: dict[str, Any],
    ) -> HandlerResult:
        """Validate whether a handling operation is allowed.

        Request body:
            data: dict - The data being handled
            classification: str - The classification level
            operation: str - The operation to validate (read, write, export, etc.)
            region: str (optional) - Processing region
            has_consent: bool (optional) - Whether user consent is obtained
            is_encrypted: bool (optional) - Whether data is encrypted
        """
        data = body.get("data")
        if not isinstance(data, dict):
            return error_response("Request body must include 'data' as a dict", 400)

        classification_str = body.get("classification")
        if not classification_str:
            return error_response("Request body must include 'classification'", 400)

        try:
            classification = DataClassification(classification_str)
        except ValueError:
            return error_response(
                f"Invalid classification level: must be one of "
                f"{[l.value for l in DataClassification]}",
                400,
            )

        operation = body.get("operation")
        if not operation or not isinstance(operation, str):
            return error_response("Request body must include 'operation' as a string", 400)

        classifier = _get_classifier()
        result = classifier.validate_handling(
            data=data,
            classification=classification,
            operation=operation,
            region=body.get("region"),
            has_consent=body.get("has_consent", False),
            is_encrypted=body.get("is_encrypted", False),
        )

        return json_response({"data": result.to_dict()})

    # -- POST /api/v1/data-classification/enforce --------------------------

    @handle_errors("data classification enforcement")
    async def _enforce_access(
        self,
        body: dict[str, Any],
    ) -> HandlerResult:
        """Enforce cross-context access rules.

        Request body:
            data: dict - The data being accessed
            source_classification: str - Classification of the data source
            target_classification: str - Classification of the target context
            operation: str (optional) - The operation (default: "read")
            region: str (optional) - Processing region
            has_consent: bool (optional) - Whether consent is obtained
            is_encrypted: bool (optional) - Whether data is encrypted
        """
        data = body.get("data")
        if not isinstance(data, dict):
            return error_response("Request body must include 'data' as a dict", 400)

        source_str = body.get("source_classification")
        target_str = body.get("target_classification")
        if not source_str or not target_str:
            return error_response(
                "Request body must include 'source_classification' and 'target_classification'",
                400,
            )

        try:
            source = DataClassification(source_str)
            target = DataClassification(target_str)
        except ValueError:
            return error_response(
                f"Invalid classification level: must be one of "
                f"{[l.value for l in DataClassification]}",
                400,
            )

        enforcer = _get_enforcer()
        result = enforcer.enforce_access(
            data=data,
            source_classification=source,
            target_classification=target,
            operation=body.get("operation", "read"),
            region=body.get("region"),
            has_consent=body.get("has_consent", False),
            is_encrypted=body.get("is_encrypted", False),
        )

        return json_response({"data": result.to_dict()})


def create_data_classification_handler(
    server_context: dict[str, Any] | None = None,
) -> DataClassificationHandler:
    """Factory function for handler registration."""
    return DataClassificationHandler(server_context)


__all__ = [
    "DataClassificationHandler",
    "create_data_classification_handler",
]
