"""Accounting, AP, AR, invoice and expense routes through real registry dispatch.

Requests go through ``HandlerRegistryMixin._try_modular_handler`` over a
``RouteIndex`` built from the real registry entries. Callers carry JWTs minted
by the production token code and are checked by the unpatched
``require_permission``; the handlers conftest auth bypass is switched off.
"""

from __future__ import annotations

import base64
import functools
import io
import json
import re
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlencode

import pytest

from aragora.server.handler_registry import HANDLER_REGISTRY, HandlerRegistryMixin
from aragora.server.handler_registry.admin import ADMIN_HANDLER_REGISTRY
from aragora.server.handler_registry.core import RouteIndex, _DeferredImport
from aragora.server.handlers.base import json_response
from aragora.server.handlers.finance import (
    ap_automation,
    ar_automation,
    expenses,
    invoices,
)

pytestmark = pytest.mark.no_auto_auth

A = "/api/v1/accounting"
AP, AR, INV, EXP, INT = (
    "_ap_automation_handler",
    "_ar_automation_handler",
    "_invoice_handler",
    "_expense_handler",
    "_accounting_integration_handler",
)
ATTRS = (AP, AR, INV, EXP, INT)
READ, WRITE, APPROVE, EXPORT, SYSTEM = (
    "finance:read",
    "finance:write",
    "finance:approve",
    "finance:export",
    "admin:system",
)
NOT_CONFIGURED = {"error": "accounting integration not configured", "code": "not_configured"}
JWT_SECRET = "s01-accounting-dispatch-test-secret-0123456789"

INTEGRATION_GATED = [
    f"/api/v1/{p}"
    for p in (
        "accounting/status accounting/connect accounting/customers accounting/transactions "
        "accounting/reports accounting/disconnect accounting/report accounting/gusto/status "
        "accounting/gusto/employees accounting/gusto/payrolls accounting/gusto/connect "
        "accounting/gusto/disconnect gusto/connect gusto/disconnect gusto/employees "
        "gusto/payrolls gusto/status ap/batch-payments ap/cash-flow ap/discount-opportunities "
        "ap/invoices ap/optimize"
    ).split()
]
CALLBACKS = [f"{A}/callback", f"{A}/gusto/callback"]

# (method, path, owner, permission). The fresh_services fixture seeds the ids.
MATRIX: list[tuple[str, str, str, str]] = [
    *[("GET", f"{A}/ap/{p}", AP, "ap:read") for p in ("invoices", "forecast", "discounts")],
    ("GET", f"{A}/ap/invoices/inv-x", AP, "ap:read"),
    ("POST", f"{A}/ap/invoices", AP, WRITE),
    ("POST", f"{A}/ap/invoices/inv-x/payment", AP, WRITE),
    ("POST", f"{A}/ap/optimize", AP, APPROVE),
    ("POST", f"{A}/ap/batch", AP, APPROVE),
    *[("GET", f"{A}/ar/{p}", AR, "ar:read") for p in ("invoices", "aging", "collections")],
    ("GET", f"{A}/ar/invoices/inv-x", AR, "ar:read"),
    ("GET", f"{A}/ar/customers/cust-x/balance", AR, "ar:read"),
    ("POST", f"{A}/ar/invoices", AR, WRITE),
    ("POST", f"{A}/ar/customers", AR, WRITE),
    ("POST", f"{A}/ar/invoices/inv-x/send", AR, WRITE),
    ("POST", f"{A}/ar/invoices/inv-x/payment", AR, WRITE),
    ("POST", f"{A}/ar/invoices/inv-x/reminder", AR, "ar:read"),
    *[
        ("GET", f"{A}/{p}", INV, READ)
        for p in (
            "invoices invoices/pending invoices/overdue invoices/stats invoices/status "
            "payments/scheduled invoices/inv-x invoices/inv-x/anomalies"
        ).split()
    ],
    *[
        ("POST", f"{A}/{p}", INV, WRITE)
        for p in ("invoices/upload", "invoices", "purchase-orders", "invoices/inv-x/match")
    ],
    *[("POST", f"{A}/invoices/inv-x/{p}", INV, APPROVE) for p in ("approve", "reject", "schedule")],
    *[
        ("GET", f"{A}/{p}", EXP, READ)
        for p in ("expenses", "expenses/stats", "expenses/pending", "expenses/exp-x")
    ],
    ("GET", f"{A}/expenses/export", EXP, EXPORT),
    *[
        ("POST", f"{A}/expenses{p}", EXP, WRITE)
        for p in ("/upload", "", "/categorize", "/sync", "/exp-x/approve", "/exp-x/reject")
    ],
    ("PUT", f"{A}/expenses/exp-x", EXP, WRITE),
    ("DELETE", f"{A}/expenses/exp-x", EXP, WRITE),
    *[
        (method, path, INT, SYSTEM if path.endswith("connect") else READ)
        for path in INTEGRATION_GATED
        for method in ("GET", "POST")
    ],
]
CALLBACK_ROUTES = [(method, path) for path in CALLBACKS for method in ("GET", "POST")]
PDF = base64.b64encode(b"%PDF-1.4 test").decode()
BODIES: dict[str, dict[str, Any]] = {
    "POST ap/invoices": {
        "vendor_id": "v",
        "vendor_name": "Vendor",
        "total_amount": 10,
        "priority": "high",
        "early_pay_discount": 0.02,
        "discount_deadline": "2026-06-11",
    },
    "POST ap/invoices/inv-x/payment": {"amount": 5, "payment_date": "2026-06-05"},
    "POST ap/optimize": {"available_cash": 50},
    "POST ap/batch": {"invoice_ids": ["inv-x"], "payment_method": "wire"},
    "POST ar/invoices": {
        "customer_id": "cust-x",
        "customer_name": "Customer",
        "line_items": [{"description": "Work", "amount": 10}],
    },
    "POST ar/customers": {"customer_id": "cust-2", "name": "Customer 2"},
    "POST ar/invoices/inv-x/payment": {"amount": 5},
    "POST invoices/upload": {"document_data": PDF},
    "POST invoices": {"vendor_name": "Vendor", "total_amount": 10, "invoice_date": "2026-06-02"},
    "POST purchase-orders": {"po_number": "PO-1", "vendor_name": "Vendor", "total_amount": 10},
    "POST invoices/inv-x/reject": {"reason": "duplicate"},
    "POST invoices/inv-x/schedule": {"pay_date": "2026-08-01", "payment_method": "wire"},
    "POST expenses/upload": {"receipt_data": PDF},
    "POST expenses": {"vendor_name": "Vendor", "amount": 10, "date": "2026-06-02"},
    "POST expenses/categorize": {"expense_ids": ["exp-x"]},
    "POST expenses/sync": {"expense_ids": ["exp-x"]},
    "POST expenses/exp-x/reject": {"reason": "duplicate"},
    "PUT expenses/exp-x": {"amount": 42},
}


def route_id(value: Any) -> str:
    if isinstance(value, tuple):
        return f"{value[0]}-{route_id(value[1])}"
    return str(value).removeprefix("/api/v1/")


def matrix_ids(rows: list[tuple[Any, ...]]) -> list[str]:
    return [route_id(row[:2]) for row in rows]


@pytest.fixture(autouse=True)
def real_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on any auth bypass; pin the JWT secret and an in-memory blacklist."""
    from aragora.billing import jwt_auth
    from aragora.billing.auth import config, context
    from aragora.server.handlers.utils import decorators
    from aragora.storage import token_blacklist_store

    assert decorators._test_user_context_override is None
    assert decorators.has_permission.__module__ == "aragora.server.handlers.utils.decorators"
    assert jwt_auth.extract_user_from_request is context.extract_user_from_request
    monkeypatch.setenv("ARAGORA_JWT_SECRET", JWT_SECRET)
    monkeypatch.setattr(config, "_jwt_secret_cache", JWT_SECRET)
    monkeypatch.setattr(config, "_jwt_secret_previous_cache", "")
    monkeypatch.setattr(
        token_blacklist_store, "_blacklist_backend", token_blacklist_store.InMemoryBlacklist()
    )


@pytest.fixture(autouse=True)
def fresh_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real in-memory services, each holding one record dated 2026-06-01 under the MATRIX ids."""
    from aragora.resilience import CircuitBreaker
    from aragora.services.ap_automation import APAutomation, PayableInvoice
    from aragora.services.ar_automation import ARAutomation, ARInvoice
    from aragora.services.expense_tracker import ExpenseRecord, ExpenseTracker
    from aragora.services.invoice_processor import InvoiceData, InvoiceProcessor, PaymentSchedule
    from aragora.services.invoice_processor import InvoiceStatus

    ap, ar = APAutomation(), ARAutomation()
    processor = InvoiceProcessor(enable_ocr=False, enable_llm_extraction=False)
    tracker = ExpenseTracker(enable_ocr=False, enable_llm_categorization=False)
    day, amount = datetime(2026, 6, 1), Decimal("100")
    money = {"total_amount": amount, "balance": amount}
    ap._store_invoice(PayableInvoice("inv-x", "v", "Vendor", invoice_date=day, **money))
    ar._customers["cust-x"] = {"id": "cust-x", "name": "Customer", "email": "c@example.com"}
    ar._store_invoice(ARInvoice("inv-x", "cust-x", "Customer", "c@example.com", **money))
    processor._store_invoice(
        InvoiceData("inv-x", "Vendor", invoice_date=day, status=InvoiceStatus.APPROVED)
    )
    processor._payment_schedule["inv-x"] = PaymentSchedule("inv-x", day, amount, "v", "Vendor")
    tracker._store_expense(ExpenseRecord("exp-x", "Vendor", amount, date=day))
    monkeypatch.setattr(ap_automation, "_ap_automation", ap)
    monkeypatch.setattr(ar_automation, "_ar_automation", ar)
    monkeypatch.setattr(ap_automation, "_ap_circuit_breaker", CircuitBreaker())
    monkeypatch.setattr(ar_automation, "_ar_circuit_breaker", CircuitBreaker())
    monkeypatch.setattr(invoices, "_invoice_processor", processor)
    monkeypatch.setattr(expenses, "_expense_tracker", tracker)
    invoices.reset_invoice_circuit_breaker()
    expenses.reset_expense_circuit_breaker()


class _Registry(HandlerRegistryMixin):
    _handlers_initialized = True


def token(role: str) -> str:
    from aragora.billing.jwt_auth import create_access_token

    return create_access_token(f"user-{role}", f"{role}@example.com", "org-s01", role=role)


def dispatch(
    method: str, path: str, role: str | None = None, query: str = "", body: bytes = b"{}"
) -> tuple[int, dict[str, Any]]:
    """Serve one request through the registry; return (status, JSON body)."""
    inst: Any = _Registry()
    inst.command = method
    inst.headers = {"Content-Length": str(len(body))}
    if role:
        inst.headers["Authorization"] = f"Bearer {token(role)}"
    inst.rfile, inst.wfile = io.BytesIO(body), io.BytesIO()
    inst.client_address = ("127.0.0.1", 12345)
    inst._auth_context = None
    for name in (
        "send_response",
        "send_header",
        "end_headers",
        "_add_cors_headers",
        "_add_security_headers",
        "_add_trace_headers",
    ):
        setattr(inst, name, MagicMock())
    registry = [(name, ref) for name, ref in ADMIN_HANDLER_REGISTRY if name in ATTRS]
    for name, ref in registry:
        setattr(inst, name, (ref.resolve() if isinstance(ref, _DeferredImport) else ref)({}))
    index = RouteIndex()
    index.build(inst, registry)
    with (
        patch("aragora.server.handler_registry.HANDLERS_AVAILABLE", True),
        patch("aragora.server.handler_registry.get_route_index", return_value=index),
        patch(
            "aragora.server.middleware.rate_limit.should_apply_default_rate_limit",
            return_value=False,
        ),
    ):
        assert inst._try_modular_handler(path, parse_qs(query)) is True
    status = inst.send_response.call_args[0][0]
    payload = json.loads(inst.wfile.getvalue())
    assert "handler_no_result" not in json.dumps(payload)
    assert status != 500, payload
    return status, payload


def assert_authorized(owner: str, status: int, body: dict) -> None:
    if owner == INT:
        assert (status, body) == (503, NOT_CONFIGURED)
    else:
        assert 200 <= status < 300 and "error" not in body, (status, body)


@pytest.mark.parametrize(("method", "path", "owner", "perm"), MATRIX, ids=matrix_ids(MATRIX))
def test_authorized_caller(
    method: str, path: str, owner: str, perm: str, record_property: Any
) -> None:
    role = "owner" if perm == SYSTEM else "admin"
    data = BODIES.get(f"{method} {path.removeprefix(A + '/')}", {})
    status, body = dispatch(method, path, role, body=json.dumps(data).encode())
    record_property("caller", f"{role}:{status}:{body.get('error') or body.get('code') or ''}")
    assert_authorized(owner, status, body)


@pytest.mark.parametrize(("method", "path", "owner", "perm"), MATRIX, ids=matrix_ids(MATRIX))
def test_insufficient_caller(
    method: str, path: str, owner: str, perm: str, record_property: Any
) -> None:
    role = "admin" if perm == SYSTEM else "viewer"
    status, body = dispatch(method, path, role)
    record_property("caller", f"{role}:{status}:{body.get('error') or ''}")
    assert (status, body) == (403, {"error": "Permission denied"})


@pytest.mark.parametrize(("method", "path", "owner", "perm"), MATRIX, ids=matrix_ids(MATRIX))
def test_anonymous_caller(
    method: str, path: str, owner: str, perm: str, record_property: Any
) -> None:
    status, body = dispatch(method, path)
    record_property("caller", f"anonymous:{status}:{body.get('error') or ''}")
    assert status == 401 and isinstance(body.get("error"), str) and body["error"], body


@pytest.mark.parametrize(("method", "path", "owner", "perm"), MATRIX, ids=matrix_ids(MATRIX))
def test_member_caller(method: str, path: str, owner: str, perm: str, record_property: Any) -> None:
    """Members hold finance:read only."""
    status, body = dispatch(method, path, "member")
    record_property("caller", f"member:{status}:{body.get('error') or body.get('code') or ''}")
    if perm == READ:
        assert_authorized(owner, status, body)
    else:
        assert (status, body) == (403, {"error": "Permission denied"})


@pytest.mark.parametrize("role", ["owner", "admin", "member", "viewer", None])
@pytest.mark.parametrize(("method", "path"), CALLBACK_ROUTES, ids=matrix_ids(CALLBACK_ROUTES))
def test_oauth_callback_not_configured_for_every_caller(
    method: str, path: str, role: str | None
) -> None:
    assert dispatch(method, path, role) == (503, NOT_CONFIGURED)


BODY_ROUTES = [(m, p) for m, p, owner, _ in MATRIX if owner != INT and m in ("POST", "PUT")]


@pytest.mark.parametrize("raw", [b"{", b"[]"], ids=["truncated", "array"])
@pytest.mark.parametrize(("role", "expected"), [(None, 401), ("viewer", 403), ("admin", 400)])
@pytest.mark.parametrize(("method", "path"), BODY_ROUTES, ids=matrix_ids(BODY_ROUTES))
def test_malformed_body_after_permission_check(
    method: str, path: str, role: str | None, expected: int, raw: bytes
) -> None:
    status, body = dispatch(method, path, role, body=raw)
    assert status == expected and isinstance(body.get("error"), str) and body["error"], body


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("ap/invoices", {**BODIES["POST ap/invoices"], "priority": "urgent"}),
        ("ap/batch", {"invoice_ids": ["inv-x"], "payment_method": "cash"}),
    ],
    ids=["priority", "payment_method"],
)
def test_invalid_ap_enum_400(path: str, data: dict[str, Any]) -> None:
    status, body = dispatch("POST", f"{A}/{path}", "admin", body=json.dumps(data).encode())
    assert status == 400 and body["error"]


def test_expense_put_is_stored() -> None:
    update = json.dumps({"amount": 42, "vendor_name": "Renamed"}).encode()
    assert dispatch("PUT", f"{A}/expenses/exp-x", "admin", body=update)[0] == 200
    status, body = dispatch("GET", f"{A}/expenses/exp-x", "admin")
    assert (body["expense"]["amount"], body["expense"]["vendorName"]) == (42, "Renamed")


def declared_routes(cls: Any) -> set[tuple[str, str]]:
    """(method, path pattern) pairs a handler class declares."""
    pairs: set[tuple[str, str]] = set()
    for table in (getattr(cls, "_ROUTE_MAP", {}), getattr(cls, "DYNAMIC_ROUTES", {}), cls.ROUTES):
        for entry in table:
            if " " in entry:
                method, path = entry.split(" ", 1)
                pairs.add((method, path))
            elif isinstance(table, dict):
                pairs.update((method, entry) for method in table[entry])
            elif not hasattr(cls, "_ROUTE_MAP"):
                pairs.update({("GET", entry), ("POST", entry)})
    return pairs


def test_matrix_covers_every_declared_route() -> None:
    placeholders = {"inv-x": "{invoice_id}", "cust-x": "{customer_id}", "exp-x": "{expense_id}"}
    rows = [*MATRIX, *[(m, p, INT, "") for m, p in CALLBACK_ROUTES]]
    registry = dict(ADMIN_HANDLER_REGISTRY)
    for attr in ATTRS:
        ref = registry[attr]
        cls = ref.resolve() if isinstance(ref, _DeferredImport) else ref
        expected = {
            (m, re.sub(r"(inv|cust|exp)-x", lambda x: placeholders[x[0]], p))
            for m, p, owner, _ in rows
            if owner == attr
        }
        assert declared_routes(cls) == expected, attr


@functools.lru_cache(maxsize=1)
def full_registry() -> tuple[RouteIndex, dict[str, Any]]:
    """Every registry handler, constructed the way ``_init_handlers`` does."""
    handlers: dict[str, Any] = {}
    for name, ref in HANDLER_REGISTRY:
        cls = ref.resolve() if isinstance(ref, _DeferredImport) else ref
        assert cls is not None, name
        try:
            handlers[name] = cls({})
        except TypeError:
            handlers[name] = cls()
    index = RouteIndex()
    index.build(SimpleNamespace(**handlers), HANDLER_REGISTRY)
    return index, handlers


@pytest.mark.parametrize(
    ("method", "path", "owner"),
    [*[row[:3] for row in MATRIX], *[(m, p, INT) for m, p in CALLBACK_ROUTES]],
    ids=matrix_ids([*MATRIX, *CALLBACK_ROUTES]),
)
def test_matrix_owner_full_registry(method: str, path: str, owner: str) -> None:
    """Index first, then the can_handle fallback in HANDLER_REGISTRY order."""
    from aragora.server.versioning import strip_version_prefix

    index, handlers = full_registry()
    candidates = [path, strip_version_prefix(path)]
    match = next(filter(None, (index.get_handler(c) for c in candidates)), None)
    if match is None:
        match = next(
            (name, h)
            for name, h in handlers.items()
            if hasattr(h, "can_handle") and any(h.can_handle(c) for c in candidates)
        )
    assert match[0] == owner


@pytest.mark.parametrize(
    ("path", "key"),
    [
        ("ap/discounts", "opportunities"),
        ("ap/forecast", "forecast"),
        ("ap/invoices", "invoices"),
        ("ar/aging", "aging_report"),
        ("ar/collections", "suggestions"),
        ("ar/invoices", "invoices"),
    ],
    ids=lambda value: value if "/" in value else None,
)
def test_ap_ar_read_admin_200(path: str, key: str) -> None:
    status, body = dispatch("GET", f"{A}/{path}", "admin")
    assert status == 200 and "error" not in body
    assert key in body["data"]


DATE_SITES = [
    f"{A}/{p}"
    for p in (
        "ap/invoices ar/invoices expenses expenses/stats expenses/export invoices "
        "payments/scheduled"
    ).split()
]


@pytest.mark.parametrize(
    ("param", "query"),
    [
        ("start_date", "start_date=2026-01-01&start_date=2026-02-01"),
        ("end_date", "end_date=2026-01-01&end_date=2026-02-01"),
        ("start_date", "start_date=yesterday"),
        ("end_date", "end_date=not-a-date"),
    ],
    ids=["repeated_start_date", "repeated_end_date", "bad_start_date", "bad_end_date"],
)
@pytest.mark.parametrize("path", DATE_SITES, ids=route_id)
def test_malformed_date_filter_400(path: str, param: str, query: str) -> None:
    status, body = dispatch("GET", path, "admin", query)
    assert status == 400, body
    assert param in body["error"]


@pytest.mark.parametrize("path", DATE_SITES, ids=route_id)
def test_well_formed_date_filters_200(path: str) -> None:
    status, body = dispatch("GET", path, "admin", "start_date=2026-01-01&end_date=2026-12-31")
    assert status == 200 and "error" not in body, body


TZ_SITES = {
    "invoices": lambda body: body["data"]["total"],
    "payments/scheduled": lambda body: body["data"]["count"],
    "expenses": lambda body: body["total"],
    "expenses/stats": lambda body: body["stats"]["totalExpenses"],
    "expenses/export": lambda body: body["data"].count("Vendor"),
}


@pytest.mark.parametrize(
    ("query", "count"),
    [
        ({"start_date": "2026-05-01T00:00:00Z"}, 1),
        ({"start_date": "2026-07-01T00:00:00+02:00"}, 0),
        ({"end_date": "2026-07-01T00:00:00Z"}, 1),
        ({"end_date": "2026-05-01T00:00:00+02:00"}, 0),
    ],
    ids=["start_z", "start_offset", "end_z", "end_offset"],
)
@pytest.mark.parametrize("site", TZ_SITES)
def test_timezone_date_filters(site: str, query: dict[str, str], count: int) -> None:
    """The seeded records are dated 2026-06-01, a month from each bound."""
    status, body = dispatch("GET", f"{A}/{site}", "admin", urlencode(query))
    assert status == 200 and TZ_SITES[site](body) == count, body


def test_offset_dated_bodies_keep_lists_working() -> None:
    dated = {"invoice_date": "2026-06-02T00:00:00Z", "due_date": "2026-07-02T00:00:00+02:00"}
    for path, data in [
        ("ap/invoices", {**BODIES["POST ap/invoices"], **dated}),
        ("invoices", {**BODIES["POST invoices"], **dated}),
        ("invoices/inv-x/schedule", {"pay_date": "2026-06-03T00:00:00+02:00"}),
        ("expenses", {**BODIES["POST expenses"], "date": "2026-06-02T00:00:00+02:00"}),
    ]:
        status, body = dispatch("POST", f"{A}/{path}", "admin", body=json.dumps(data).encode())
        assert status == 200, (path, body)
    for path in ["ap/invoices", *TZ_SITES]:
        for query in ("", "start_date=2026-05-01&end_date=2026-07-01"):
            status, body = dispatch("GET", f"{A}/{path}", "admin", query)
            assert status == 200 and "error" not in body, (path, query, body)


@pytest.mark.parametrize(
    "query",
    ["limit=abc", "limit=0", "limit=5000", "offset=-1", "offset=abc", "limit=5&limit=10"],
)
@pytest.mark.parametrize("area", ["ap", "ar"])
def test_ap_ar_invoice_pagination_400(area: str, query: str) -> None:
    status, body = dispatch("GET", f"{A}/{area}/invoices", "admin", query)
    assert status == 400 and isinstance(body["error"], str) and body["error"]


@pytest.mark.parametrize("area", ["ap", "ar", "invoices"])
def test_well_formed_invoice_list_200(area: str) -> None:
    path = f"{A}/invoices" if area == "invoices" else f"{A}/{area}/invoices"
    status, body = dispatch("GET", path, "admin", "limit=5&offset=0&start_date=2026-01-01")
    assert status == 200 and "error" not in body
    assert (body["data"]["limit"], body["data"]["offset"]) == (5, 0)


@pytest.mark.parametrize(
    ("param", "query"),
    [
        ("limit", "limit=abc"),
        ("offset", "offset=abc"),
        ("limit", "limit=5&limit=10"),
        ("offset", "offset=0&offset=1"),
    ],
)
def test_invoice_list_malformed_pagination_400(param: str, query: str) -> None:
    status, body = dispatch("GET", f"{A}/invoices", "admin", query)
    assert status == 400 and param in body["error"]


@pytest.mark.parametrize(
    ("query", "limit", "offset"),
    [
        ("limit=0", 1, 0),
        ("limit=5000", 1000, 0),
        ("offset=-1", 100, 0),
        ("offset=0", 100, 0),
        ("offset=7", 100, 7),
    ],
)
def test_invoice_list_pagination_clamps(query: str, limit: int, offset: int) -> None:
    status, body = dispatch("GET", f"{A}/invoices", "admin", query)
    assert status == 200
    assert (body["data"]["limit"], body["data"]["offset"]) == (limit, offset)


@pytest.mark.parametrize(
    ("area", "query"),
    [("ap", "priority=invalid"), ("ap", "status=invalid"), ("ar", "status=invalid")],
)
def test_invalid_invoice_filter_returns_400(area: str, query: str) -> None:
    status, _ = dispatch("GET", f"{A}/{area}/invoices", "admin", query)
    assert status == 400


@pytest.mark.parametrize("status,expected", [("unpaid", ["2"]), ("partial", ["3"]), ("paid", [])])
def test_ap_invoice_filters_use_real_service(status: str, expected: list[str]) -> None:
    from aragora.services.ap_automation import PayableInvoice, PaymentPriority

    ap_automation.get_ap_automation()._invoices = {
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
    query = (
        f"vendor_id=vendor&priority=high&status={status}"
        "&start_date=2026-09-02&end_date=2026-09-04&limit=1"
    )
    code, body = dispatch("GET", f"{A}/ap/invoices", "admin", query)
    assert code == 200
    assert [inv["id"] for inv in body["data"]["invoices"]] == expected
    assert body["data"]["total"] == len(expected)


def test_ar_invoice_filters_use_real_service() -> None:
    from aragora.services.ar_automation import ARInvoice, InvoiceStatus

    ar_automation.get_ar_automation()._invoices = {
        str(day): ARInvoice(
            id=str(day),
            customer_id="customer",
            customer_name="Customer",
            invoice_date=datetime(2026, 9, day),
            status=InvoiceStatus.SENT if day != 3 else InvoiceStatus.DRAFT,
        )
        for day in range(1, 6)
    }
    query = (
        "customer_id=customer&status=sent&start_date=2026-09-02&end_date=2026-09-04"
        "&limit=1&offset=1"
    )
    code, body = dispatch("GET", f"{A}/ar/invoices", "admin", query)
    assert code == 200
    assert [inv["id"] for inv in body["data"]["invoices"]] == ["2"]
    assert body["data"]["total"] == 2


def request(body: bytes = b"") -> SimpleNamespace:
    return SimpleNamespace(
        headers={"Content-Length": str(len(body))},
        rfile=io.BytesIO(body),
        client_address=("127.0.0.1", 12345),
    )


async def test_invoices_handle_forwards_request_handler() -> None:
    invoice = invoices.InvoiceHandler({})
    query = {"limit": "2"}
    http = request()
    expected = json_response({"invoices": []})
    with patch.object(invoice, "handle_get", AsyncMock(return_value=expected)) as get:
        result = await invoice.handle(f"{A}/invoices", query, http)
    assert result is expected
    get.assert_awaited_once_with(f"{A}/invoices", query, handler=http)


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
@pytest.mark.parametrize("path", ["/unrelated", f"{A}/ap/invoices/id/unknown"])
async def test_unknown_routes_return_404(cls: Any, path: str) -> None:
    instance = cls({})
    assert not instance.can_handle(path)
    assert (await instance.handle(path, {}, request())).status_code == 404
    assert (await instance.handle_post(path, {}, request())).status_code == 404
