"""Regression tests for the modular accounting entry points."""

from __future__ import annotations

import io
import json
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from aragora.server.handlers import accounting, ap_automation, ar_automation
from aragora.server.handlers.base import HandlerResult, json_response
from aragora.server.handlers.invoices import InvoiceHandler
from aragora.server.handlers.utils.params import parse_query_params


def request(body: bytes = b"") -> SimpleNamespace:
    return SimpleNamespace(
        headers={"Content-Length": str(len(body))},
        rfile=io.BytesIO(body),
        client_address=("127.0.0.1", 12345),
    )


@pytest.fixture(autouse=True)
def fresh_services(monkeypatch: pytest.MonkeyPatch) -> None:
    from aragora.resilience import CircuitBreaker
    from aragora.services.ap_automation import APAutomation
    from aragora.services.ar_automation import ARAutomation

    monkeypatch.setattr(ap_automation, "_ap_automation", APAutomation())
    monkeypatch.setattr(ar_automation, "_ar_automation", ARAutomation())
    monkeypatch.setattr(ap_automation, "_ap_circuit_breaker", CircuitBreaker())
    monkeypatch.setattr(ar_automation, "_ar_circuit_breaker", CircuitBreaker())


async def check_get(area: str, endpoint: str, status: int, key: str = "") -> None:
    cls = ap_automation.APAutomationHandler if area == "ap" else ar_automation.ARAutomationHandler
    result = await cls({}).handle(f"/api/v1/accounting/{area}/{endpoint}", {}, request())
    assert isinstance(result, HandlerResult)
    assert result.status_code == status
    body = json.loads(result.body)
    if status == 401:
        assert isinstance(body["error"], str) and body["error"]
    else:
        assert "error" not in body
        assert key in body["data"]


@pytest.mark.no_auto_auth
async def test_ap_discounts_anonymous_401() -> None:
    await check_get("ap", "discounts", 401)


async def test_ap_discounts_authenticated_200() -> None:
    await check_get("ap", "discounts", 200, "opportunities")


@pytest.mark.no_auto_auth
async def test_ap_forecast_anonymous_401() -> None:
    await check_get("ap", "forecast", 401)


async def test_ap_forecast_authenticated_200() -> None:
    await check_get("ap", "forecast", 200, "forecast")


@pytest.mark.no_auto_auth
async def test_ap_invoices_anonymous_401() -> None:
    await check_get("ap", "invoices", 401)


async def test_ap_invoices_authenticated_200() -> None:
    await check_get("ap", "invoices", 200, "invoices")


@pytest.mark.no_auto_auth
async def test_ar_aging_anonymous_401() -> None:
    await check_get("ar", "aging", 401)


async def test_ar_aging_authenticated_200() -> None:
    await check_get("ar", "aging", 200, "aging_report")


@pytest.mark.no_auto_auth
async def test_ar_collections_anonymous_401() -> None:
    await check_get("ar", "collections", 401)


async def test_ar_collections_authenticated_200() -> None:
    await check_get("ar", "collections", 200, "suggestions")


@pytest.mark.no_auto_auth
async def test_ar_invoices_anonymous_401() -> None:
    await check_get("ar", "invoices", 401)


async def test_ar_invoices_authenticated_200() -> None:
    await check_get("ar", "invoices", 200, "invoices")


async def invoice_query(area: str, query: dict[str, Any]) -> HandlerResult:
    cls = ap_automation.APAutomationHandler if area == "ap" else ar_automation.ARAutomationHandler
    result = await cls({}).handle(f"/api/v1/accounting/{area}/invoices", query, request())
    assert isinstance(result, HandlerResult)
    return result


@pytest.mark.parametrize(
    "area,query_string",
    [
        pytest.param(area, query, id=f"test_{area}_invoices_{case}_400")
        for area in ("ap", "ar")
        for case, query in [
            ("limit_not_int", "limit=abc"),
            ("limit_zero", "limit=0"),
            ("limit_too_large", "limit=5000"),
            ("offset_negative", "offset=-1"),
            ("offset_not_int", "offset=abc"),
            ("repeated_start_date", "start_date=2026-01-01&start_date=2026-01-02"),
            ("repeated_end_date", "end_date=2026-01-01&end_date=2026-01-02"),
            ("bad_iso_date", "start_date=yesterday"),
            ("bad_iso_end_date", "end_date=yesterday"),
        ]
    ],
)
async def test_invoice_query_validation_400(area: str, query_string: str) -> None:
    query = parse_query_params(query_string)
    if "&" in query_string:
        # The HTTP query parser preserves repeated keys as lists, not scalars.
        assert next(iter(query.values())) == ["2026-01-01", "2026-01-02"]
    result = await invoice_query(area, query)
    assert result.status_code == 400
    body = json.loads(result.body)
    assert isinstance(body["error"], str) and body["error"]


@pytest.mark.parametrize("area", ["ap", "ar"], ids=["ap", "ar"])
async def test_invoice_query_well_formed_filters_200(area: str) -> None:
    result = await invoice_query(area, parse_query_params("limit=5&offset=0&start_date=2026-01-01"))
    assert result.status_code == 200
    body = json.loads(result.body)
    assert "error" not in body
    assert body["data"] == {"invoices": [], "total": 0, "limit": 5, "offset": 0}


@pytest.mark.parametrize("status,expected", [("unpaid", ["2"]), ("partial", ["3"]), ("paid", [])])
async def test_ap_invoice_filters_use_real_service(status: str, expected: list[str]) -> None:
    from aragora.services.ap_automation import PayableInvoice, PaymentPriority

    ap = ap_automation.get_ap_automation()
    ap._invoices = {
        str(day): PayableInvoice(
            id=str(day),
            vendor_id="vendor",
            vendor_name="Vendor",
            invoice_date=datetime(2026, 9, day),
            total_amount=Decimal("100"),
            balance=Decimal("50"),
            amount_paid=Decimal("50") if day == 3 else Decimal("0"),
            priority=PaymentPriority.HIGH if day != 4 else PaymentPriority.NORMAL,
        )
        for day in range(1, 6)
    }
    with patch.object(ap, "list_invoices", wraps=ap.list_invoices) as listing:
        result = await ap_automation.APAutomationHandler({}).handle(
            "/api/v1/accounting/ap/invoices",
            {
                "vendor_id": "vendor",
                "priority": "high",
                "status": status,
                "start_date": "2026-09-02",
                "end_date": "2026-09-04",
                "limit": "1",
            },
            request(),
        )
    assert result.status_code == 200
    listing.assert_awaited_once_with(vendor_id="vendor", priority=PaymentPriority.HIGH)
    assert listing.call_args.kwargs["priority"] is PaymentPriority.HIGH
    body = json.loads(result.body)["data"]
    assert [inv["id"] for inv in body["invoices"]] == expected
    assert body["total"] == len(expected)


async def test_ar_invoice_filters_use_real_service() -> None:
    from aragora.services.ar_automation import ARInvoice, InvoiceStatus

    ar = ar_automation.get_ar_automation()
    ar._invoices = {
        str(day): ARInvoice(
            id=str(day),
            customer_id="customer",
            customer_name="Customer",
            invoice_date=datetime(2026, 9, day),
            status=InvoiceStatus.SENT if day != 3 else InvoiceStatus.DRAFT,
        )
        for day in range(1, 6)
    }
    with patch.object(ar, "list_invoices", wraps=ar.list_invoices) as listing:
        result = await ar_automation.ARAutomationHandler({}).handle(
            "/api/v1/accounting/ar/invoices",
            {
                "customer_id": "customer",
                "status": "sent",
                "start_date": "2026-09-02",
                "end_date": "2026-09-04",
                "limit": "1",
                "offset": "1",
            },
            request(),
        )
    assert result.status_code == 200
    listing.assert_awaited_once_with(customer_id="customer", status=InvoiceStatus.SENT)
    assert listing.call_args.kwargs["status"] is InvoiceStatus.SENT
    body = json.loads(result.body)["data"]
    assert [inv["id"] for inv in body["invoices"]] == ["2"]
    assert body["total"] == 2


@pytest.mark.parametrize(
    "area,query",
    [("ap", {"priority": "invalid"}), ("ap", {"status": "invalid"}), ("ar", {"status": "invalid"})],
)
async def test_invalid_invoice_filter_returns_400(area: str, query: dict[str, str]) -> None:
    cls = ap_automation.APAutomationHandler if area == "ap" else ar_automation.ARAutomationHandler
    result = await cls({}).handle(f"/api/v1/accounting/{area}/invoices", query, request())
    assert result.status_code == 400


def check_not_configured(result: HandlerResult) -> None:
    assert result.status_code == 503
    assert json.loads(result.body) == {
        "error": "accounting integration not configured",
        "code": "not_configured",
    }


def test_accounting_connect_not_configured_503() -> None:
    check_not_configured(
        accounting.AccountingIntegrationHandler({}).handle(
            "/api/v1/accounting/connect", {}, request()
        )
    )


@pytest.mark.parametrize(
    "path",
    [
        f"/api/v1/{prefix}/{endpoint}"
        for prefix, endpoints in [
            ("accounting", "status callback customers transactions reports disconnect report"),
            ("accounting/gusto", "status employees payrolls connect callback disconnect"),
            ("gusto", "connect disconnect employees payrolls status"),
            ("ap", "batch-payments cash-flow discount-opportunities invoices optimize"),
        ]
        for endpoint in endpoints.split()
    ],
    ids=lambda path: "test_"
    + path.removeprefix("/api/v1/").replace("/", "_")
    + "_not_configured_503",
)
@pytest.mark.parametrize("method", ["handle", "handle_post"])
def test_integration_not_configured_503(path: str, method: str) -> None:
    integration = accounting.AccountingIntegrationHandler({})
    assert integration.can_handle(path)
    check_not_configured(getattr(integration, method)(path, {}, request()))


async def test_invoices_handle_delegates_to_handle_get() -> None:
    invoice = InvoiceHandler({})
    query = {"limit": "2"}
    expected = json_response({"invoices": []})
    with patch.object(invoice, "handle_get", AsyncMock(return_value=expected)) as get:
        result = await invoice.handle("/api/v1/accounting/invoices", query, request())
    assert result is expected
    get.assert_awaited_once_with("/api/v1/accounting/invoices", query)


@pytest.mark.no_auto_auth
async def test_invoices_anonymous_401() -> None:
    result = await InvoiceHandler({}).handle("/api/v1/accounting/invoices", {}, request())
    assert result.status_code == 401


@pytest.mark.parametrize("module", [ap_automation, ar_automation])
@pytest.mark.parametrize("body", [b"{", b"[]", b"null"])
async def test_post_rejects_invalid_json(module: Any, body: bytes) -> None:
    cls = module.APAutomationHandler if module is ap_automation else module.ARAutomationHandler
    area = "ap" if module is ap_automation else "ar"
    result = await cls({}).handle_post(f"/api/v1/accounting/{area}/invoices", {}, request(body))
    assert isinstance(result, HandlerResult)
    assert result.status_code == 400


@pytest.mark.parametrize("module", [ap_automation, ar_automation])
async def test_declared_routes_forward_body_query_and_dynamic_ids(module: Any) -> None:
    cls = module.APAutomationHandler if module is ap_automation else module.ARAutomationHandler
    instance = cls({})
    for route, function in {**cls._ROUTE_MAP, **cls.DYNAMIC_ROUTES}.items():
        method, pattern = route.split(" ", 1)
        path = pattern.replace("{invoice_id}", "inv-123").replace("{customer_id}", "cust-123")
        params = {
            name: value
            for name, value in [("invoice_id", "inv-123"), ("customer_id", "cust-123")]
            if "{" + name + "}" in pattern
        }
        assert instance.can_handle(path)
        http = request(b'{"amount": 10}')
        data = {"limit": "3"} if method == "GET" else {"amount": 10}
        expected = json_response({"routed": route})
        with patch.object(module, function.__name__, AsyncMock(return_value=expected)) as target:
            entry = instance.handle if method == "GET" else instance.handle_post
            result = await entry(path, {"limit": "3"}, http)
        assert result is expected, route
        target.assert_awaited_once_with(data, **params, handler=http)


@pytest.mark.parametrize(
    "cls", [ap_automation.APAutomationHandler, ar_automation.ARAutomationHandler]
)
@pytest.mark.parametrize("path", ["/unrelated", "/api/v1/accounting/ap/invoices/id/unknown"])
async def test_unknown_routes_return_404(cls: Any, path: str) -> None:
    instance = cls({})
    assert not instance.can_handle(path)
    assert (await instance.handle(path, {}, request())).status_code == 404
    assert (await instance.handle_post(path, {}, request())).status_code == 404
