"""OpenAPI declarations for routes wired through free-function registrars.

These routes cannot be discovered from handler ``ROUTES`` attributes or the
``@api_endpoint`` registry. Keep their source-backed declarations here so a
fresh OpenAPI generation does not depend on edits to the generated artifact.
"""

from collections.abc import Iterable
import re
from typing import Any

from aragora.server.openapi.operation_ids import add_operation_ids_to_paths


_MUTATING_METHODS = {"patch", "post", "put"}


def _json_object_schema() -> dict[str, str]:
    return {"type": "object"}


def _operation(
    path: str,
    method: str,
    *,
    source: str,
    tag: str,
    success_status: str = "200",
    public: bool = False,
) -> dict[str, Any]:
    deprecated = not path.startswith("/api/v1/")
    operation: dict[str, Any] = {
        "summary": f"{method.upper()} {path}",
        "description": (
            f"Served route registered by {source}. Auto-generated from wired route "
            "registration; detailed contract pending."
        ),
        "tags": [tag],
        "responses": {
            success_status: {
                "description": "Created" if success_status == "201" else "Success",
                "content": {"application/json": {"schema": _json_object_schema()}},
            }
        },
        "x-method-inferred": False,
        "x-wired-registration": True,
        "x-aragora-stability": "deprecated" if deprecated else "experimental",
    }
    if deprecated:
        operation["deprecated"] = True
        operation["x-preserve-legacy-operation-id"] = True
    parameters = [
        {
            "name": name,
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
            "description": f"Path parameter: {name}",
        }
        for name in re.findall(r"{([^}]+)}", path)
    ]
    if parameters:
        operation["parameters"] = parameters
    if method in _MUTATING_METHODS:
        operation["requestBody"] = {
            "content": {"application/json": {"schema": _json_object_schema()}}
        }
    if not public:
        operation["security"] = [{"bearerAuth": []}]
    return operation


def _routes(
    source: str,
    tag: str,
    entries: Iterable[tuple[str, tuple[str, ...], str, bool]],
) -> dict[str, dict[str, Any]]:
    routes: dict[str, dict[str, Any]] = {}
    for path, methods, success_status, public in entries:
        routes[path] = {
            method: _operation(
                path,
                method,
                source=source,
                tag=tag,
                success_status=success_status,
                public=public,
            )
            for method in methods
        }
    return routes


_ADMIN_CREDIT_ROUTES = (
    ("/api/admin/credits/{org_id}", ("get",), "200", False),
    ("/api/admin/credits/{org_id}/adjust", ("post",), "200", False),
    ("/api/admin/credits/{org_id}/expiring", ("get",), "200", False),
    ("/api/admin/credits/{org_id}/issue", ("post",), "201", False),
    ("/api/admin/credits/{org_id}/transactions", ("get",), "200", False),
    ("/api/v1/admin/credits/{org_id}", ("get",), "200", False),
    ("/api/v1/admin/credits/{org_id}/adjust", ("post",), "200", False),
    ("/api/v1/admin/credits/{org_id}/expiring", ("get",), "200", False),
    ("/api/v1/admin/credits/{org_id}/issue", ("post",), "201", False),
    ("/api/v1/admin/credits/{org_id}/transactions", ("get",), "200", False),
)

_INBOX_ROUTES = (
    ("/api/v1/inbox/actions", ("post",), "200", False),
    ("/api/v1/inbox/bulk-actions", ("post",), "200", False),
    ("/api/v1/inbox/command", ("get",), "200", False),
    ("/api/v1/inbox/daily-digest", ("get",), "200", False),
    ("/api/v1/inbox/reprioritize", ("post",), "200", False),
    ("/api/v1/inbox/sender-profile", ("get",), "200", False),
    ("/api/email/daily-digest", ("get",), "200", False),
    ("/api/email/sender-profile", ("get",), "200", False),
    ("/api/inbox/actions", ("post",), "200", False),
    ("/api/inbox/bulk-actions", ("post",), "200", False),
    ("/api/inbox/command", ("get",), "200", False),
    ("/api/inbox/daily-digest", ("get",), "200", False),
    ("/api/inbox/reprioritize", ("post",), "200", False),
    ("/api/inbox/sender-profile", ("get",), "200", False),
)

_INTEGRATION_ROUTES = (
    ("/api/integrations/status", ("get",), "200", False),
    ("/api/integrations/{type}", ("delete", "get", "patch", "put"), "200", False),
    ("/api/integrations/{type}/test", ("post",), "200", False),
)

_PAYMENT_ROUTES = (
    ("/api/payments/authorize", ("post",), "200", False),
    ("/api/payments/capture", ("post",), "200", False),
    ("/api/payments/charge", ("post",), "200", False),
    ("/api/payments/customer", ("post",), "200", False),
    ("/api/payments/customer/{customer_id}", ("delete", "get", "put"), "200", False),
    ("/api/payments/refund", ("post",), "200", False),
    ("/api/payments/subscription", ("post",), "200", False),
    (
        "/api/payments/subscription/{subscription_id}",
        ("delete", "get", "put"),
        "200",
        False,
    ),
    ("/api/payments/transaction/{transaction_id}", ("get",), "200", False),
    ("/api/payments/void", ("post",), "200", False),
    ("/api/payments/webhook/authnet", ("post",), "200", False),
    ("/api/payments/webhook/stripe", ("post",), "200", False),
    ("/api/v1/payments/authorize", ("post",), "200", False),
    ("/api/v1/payments/capture", ("post",), "200", False),
    ("/api/v1/payments/charge", ("post",), "200", False),
    ("/api/v1/payments/customer", ("post",), "200", False),
    ("/api/v1/payments/customer/{customer_id}", ("delete", "get", "put"), "200", False),
    ("/api/v1/payments/refund", ("post",), "200", False),
    ("/api/v1/payments/subscription", ("post",), "200", False),
    (
        "/api/v1/payments/subscription/{subscription_id}",
        ("delete", "get", "put"),
        "200",
        False,
    ),
    ("/api/v1/payments/transaction/{transaction_id}", ("get",), "200", False),
    ("/api/v1/payments/void", ("post",), "200", False),
    ("/api/v1/payments/webhook/authnet", ("post",), "200", False),
    ("/api/v1/payments/webhook/stripe", ("post",), "200", False),
)


WIRED_REGISTRATION_NO_V1_ALIASES = frozenset(
    {"/api/email/daily-digest", "/api/email/sender-profile"}
)


WIRED_REGISTRATION_ENDPOINTS = {
    **_routes("aragora/server/handlers/admin/credits.py", "Admin", _ADMIN_CREDIT_ROUTES),
    **_routes(
        "aragora/server/handlers/inbox_command.py",
        "Inbox",
        _INBOX_ROUTES,
    ),
    **_routes(
        "aragora/server/handlers/features/integrations.py",
        "Integrations",
        _INTEGRATION_ROUTES,
    ),
    **_routes("aragora/server/handlers/payments/plans.py", "Payments", _PAYMENT_ROUTES),
    **_routes(
        "aragora/server/handlers/costs/routes.py",
        "Costs",
        (
            ("/api/costs/recommendations/{recommendation_id}", ("get",), "200", False),
            ("/api/costs/recommendations/{recommendation_id}/apply", ("post",), "200", False),
            (
                "/api/costs/recommendations/{recommendation_id}/dismiss",
                ("post",),
                "200",
                False,
            ),
            ("/api/v1/costs/recommendations/{recommendation_id}", ("get",), "200", False),
            (
                "/api/v1/costs/recommendations/{recommendation_id}/apply",
                ("post",),
                "200",
                False,
            ),
            (
                "/api/v1/costs/recommendations/{recommendation_id}/dismiss",
                ("post",),
                "200",
                False,
            ),
        ),
    ),
}

# The integration PUT route returns 201 when it creates a configuration and
# 200 when it updates one. Preserve both runtime outcomes in the source-backed
# legacy route contract.
WIRED_REGISTRATION_ENDPOINTS["/api/integrations/{type}"]["put"]["responses"]["201"] = {
    "description": "Created",
    "content": {"application/json": {"schema": _json_object_schema()}},
}

_PRESERVED_OPERATION_IDS = {
    ("/api/v1/inbox/actions", "post"): "createInboxActions",
    ("/api/v1/inbox/bulk-actions", "post"): "createInboxBulkActions",
    ("/api/v1/inbox/command", "get"): "listInboxCommand",
    ("/api/v1/inbox/daily-digest", "get"): "listInboxDailyDigest",
    ("/api/v1/inbox/reprioritize", "post"): "createInboxReprioritize",
    ("/api/v1/inbox/sender-profile", "get"): "listInboxSenderProfile",
    (
        "/api/v1/costs/recommendations/{recommendation_id}",
        "get",
    ): "handle_get_recommendation",
    (
        "/api/v1/costs/recommendations/{recommendation_id}/apply",
        "post",
    ): "handle_apply_recommendation",
    (
        "/api/v1/costs/recommendations/{recommendation_id}/dismiss",
        "post",
    ): "handle_dismiss_recommendation",
}
for (_path, _method), _operation_id in _PRESERVED_OPERATION_IDS.items():
    WIRED_REGISTRATION_ENDPOINTS[_path][_method]["operationId"] = _operation_id

add_operation_ids_to_paths(
    dict(
        sorted(
            WIRED_REGISTRATION_ENDPOINTS.items(),
            key=lambda item: not item[0].startswith("/api/v1/"),
        )
    )
)
