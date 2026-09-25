"""Accounting route ownership and the registry's no-result safety net."""

from __future__ import annotations

import inspect
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handler_registry import HANDLER_REGISTRY, HandlerRegistryMixin
from aragora.server.handler_registry.admin import ADMIN_HANDLER_REGISTRY
from aragora.server.handler_registry.core import RouteIndex, _DeferredImport
from aragora.server.handlers.base import BaseHandler, HandlerResult

ROOT = Path(__file__).resolve().parents[3]
ATTRS = [
    "_ap_automation_handler",
    "_ar_automation_handler",
    "_invoice_handler",
    "_expense_handler",
    "_accounting_integration_handler",
]


def accounting_index() -> tuple[RouteIndex, dict[str, Any]]:
    registry = [(name, cls) for name, cls in ADMIN_HANDLER_REGISTRY if name in ATTRS]
    assert [name for name, _ in registry] == ATTRS
    instances = {}
    for name, ref in registry:
        cls = ref.resolve() if isinstance(ref, _DeferredImport) else ref
        assert callable(cls), name
        instances[name] = cls({})
    index = RouteIndex()
    index.build(SimpleNamespace(**instances), registry)
    return index, instances


def accounting_get_paths() -> list[str]:
    spec = json.loads((ROOT / "docs/api/openapi.json").read_text())
    paths = sorted(
        path
        for path, operations in spec["paths"].items()
        if path.startswith("/api/v1/accounting") and "{" not in path and "get" in operations
    )
    assert len(paths) >= 27
    return paths


@pytest.mark.no_auto_auth
async def test_every_accounting_get_dispatches_non_none() -> None:
    index, _ = accounting_index()
    http = SimpleNamespace(headers={}, client_address=("127.0.0.1", 12345))
    for path in accounting_get_paths():
        match = index.get_handler(path)
        assert match is not None, path
        result = match[1].handle(path, {}, http)
        if inspect.isawaitable(result):
            result = await result
        assert isinstance(result, HandlerResult), (path, result)
        assert result.status_code in (200, 401, 503), path


def test_route_owners() -> None:
    index, instances = accounting_index()
    claims: dict[str, str] = {}
    for name, instance in instances.items():
        for path in instance.ROUTES:
            assert path not in claims, (path, claims.get(path), name)
            claims[path] = name
    for path in set(claims) | set(accounting_get_paths()):
        if path.startswith("/api/v1/accounting/ap/"):
            owner = "_ap_automation_handler"
        elif path.startswith("/api/v1/accounting/ar/"):
            owner = "_ar_automation_handler"
        elif path.startswith("/api/v1/accounting/expenses"):
            owner = "_expense_handler"
        elif path.startswith("/api/v1/accounting/invoices") or path in (
            "/api/v1/accounting/payments/scheduled",
            "/api/v1/accounting/purchase-orders",
        ):
            owner = "_invoice_handler"
        else:
            owner = "_accounting_integration_handler"
        match = index.get_handler(path)
        assert match is not None and match[0] == owner, (path, match)
    assert len(instances["_ap_automation_handler"].ROUTES) == 5


def test_collection_routes_remain_visible_to_contract_discovery() -> None:
    from scripts.validate_openapi_routes import get_handler_routes

    registry = [(name, ref) for name, ref in ADMIN_HANDLER_REGISTRY if name in ATTRS]
    with patch("aragora.server.handler_registry.HANDLER_REGISTRY", registry):
        routes = get_handler_routes()
    assert "/api/v1/accounting/invoices" in routes
    assert "/api/v1/accounting/expenses" in routes


def test_route_owners_full_registry() -> None:
    """Index all class-level routes without constructors needing live services."""
    handlers = {}
    for name, ref in HANDLER_REGISTRY:
        cls = ref.resolve() if isinstance(ref, _DeferredImport) else ref
        assert inspect.isclass(cls), name  # Failed imports must not silently lose claims.
        assert name not in handlers, name
        handlers[name] = cls
    assert len(handlers) == len(HANDLER_REGISTRY)
    index = RouteIndex()
    index.build(SimpleNamespace(**handlers), HANDLER_REGISTRY)

    owners = {
        "/api/v1/accounting/invoices": "_invoice_handler",
        "/api/v1/accounting/expenses": "_expense_handler",
        "/api/v1/accounting/ap/invoices": "_ap_automation_handler",
        "/api/v1/accounting/ar/invoices": "_ar_automation_handler",
        "/api/v1/accounting/status": "_accounting_integration_handler",
    }
    for path, owner in owners.items():
        assert path in index._exact_routes
        match = index.get_handler(path)
        assert match is not None and match[0] == owner, (path, match)
    for path, (owner, _) in index._exact_routes.items():
        if path.startswith("/api/v1/accounting"):
            assert owner in ATTRS, (path, owner)


def test_none_result_yields_500_handler_no_result() -> None:
    class NoResultHandler(BaseHandler):
        ROUTES = ["/api/v1/accounting/no-result-test"]

        def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> None:
            return None

    class TestRegistry(HandlerRegistryMixin):
        _handlers_initialized = True

    instance: Any = TestRegistry()
    instance.command = "GET"
    instance.headers = {}
    instance.wfile = io.BytesIO()
    instance._auth_context = None
    instance.client_address = ("127.0.0.1", 12345)
    for name in (
        "send_response",
        "send_header",
        "end_headers",
        "_add_cors_headers",
        "_add_security_headers",
        "_add_trace_headers",
    ):
        setattr(instance, name, MagicMock())
    instance._no_result_handler = NoResultHandler({})
    index = RouteIndex()
    index.build(instance, [("_no_result_handler", NoResultHandler)])
    with (
        patch("aragora.server.handler_registry.HANDLERS_AVAILABLE", True),
        patch("aragora.server.handler_registry.get_route_index", return_value=index),
        patch(
            "aragora.server.middleware.rate_limit.should_apply_default_rate_limit",
            return_value=False,
        ),
    ):
        assert instance._try_modular_handler(NoResultHandler.ROUTES[0], {})
    instance.send_response.assert_called_once_with(500)
    assert json.loads(instance.wfile.getvalue())["code"] == "handler_no_result"
