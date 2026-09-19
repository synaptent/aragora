"""
Accounting handlers for QuickBooks Online and Gusto payroll integration.

Provides HTTP endpoints for:
- QuickBooks OAuth connection flow
- Transaction sync and customer management
- Financial report generation
- Gusto payroll OAuth + employee/payroll sync

Endpoints:
- GET /api/accounting/status - QuickBooks status + dashboard data
- GET /api/accounting/connect - Start QuickBooks OAuth
- GET /api/accounting/callback - QuickBooks OAuth callback
- POST /api/accounting/disconnect - Disconnect QuickBooks
- GET /api/accounting/customers - List QuickBooks customers
- GET /api/accounting/transactions - List QuickBooks transactions
- POST /api/accounting/report - Generate accounting report
- GET /api/accounting/gusto/status - Gusto connection status
- GET /api/accounting/gusto/connect - Start Gusto OAuth
- GET /api/accounting/gusto/callback - Gusto OAuth callback
- POST /api/accounting/gusto/disconnect - Disconnect Gusto
- GET /api/accounting/gusto/employees - List employees
- GET /api/accounting/gusto/payrolls - List payroll runs
- GET /api/accounting/gusto/payrolls/{payroll_id} - Payroll run details
- POST /api/accounting/gusto/payrolls/{payroll_id}/journal-entry - Generate journal entry
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from aiohttp import web

from aragora.connectors.accounting.gusto import GustoConnector
from aragora.server.handlers.utils import parse_json_body
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.handlers.utils.params import get_pagination_params
from aragora.server.handlers.utils.responses import error_dict
from aragora.server.handlers.openapi_decorator import api_endpoint

logger = logging.getLogger(__name__)

VALID_TRANSACTION_TYPES = frozenset({"all", "invoice", "expense"})
VALID_REPORT_TYPES = frozenset({"profit_loss", "balance_sheet", "ar_aging", "ap_aging"})

# Mock data for demo when QBO not connected
MOCK_COMPANY = {
    "name": "Demo Company",
    "legalName": "Demo Company LLC",
    "country": "US",
    "email": "accounting@demo.com",
}

MOCK_STATS = {
    "receivables": 46270.50,
    "payables": 12340.00,
    "revenue": 125000.00,
    "expenses": 78500.00,
    "netIncome": 46500.00,
    "openInvoices": 8,
    "overdueInvoices": 2,
}

MOCK_CUSTOMERS = [
    {
        "id": "1",
        "displayName": "Acme Corporation",
        "companyName": "Acme Corp",
        "email": "billing@acme.com",
        "balance": 15420.50,
        "active": True,
    },
    {
        "id": "2",
        "displayName": "TechStart Inc",
        "companyName": "TechStart",
        "email": "ap@techstart.io",
        "balance": 8750.00,
        "active": True,
    },
    {
        "id": "3",
        "displayName": "Green Energy Solutions",
        "companyName": "Green Energy",
        "email": "finance@greenenergy.com",
        "balance": 22100.00,
        "active": True,
    },
    {
        "id": "4",
        "displayName": "Metro Retail Group",
        "companyName": "Metro Retail",
        "email": "payments@metroretail.com",
        "balance": 0,
        "active": True,
    },
]

MOCK_TRANSACTIONS = [
    {
        "id": "1001",
        "type": "Invoice",
        "docNumber": "INV-1001",
        "txnDate": "2025-01-17",
        "dueDate": "2025-02-16",
        "totalAmount": 5250.00,
        "balance": 5250.00,
        "customerName": "Acme Corporation",
        "status": "Open",
    },
    {
        "id": "1002",
        "type": "Invoice",
        "docNumber": "INV-1002",
        "txnDate": "2025-01-10",
        "dueDate": "2025-02-09",
        "totalAmount": 3800.00,
        "balance": 0,
        "customerName": "TechStart Inc",
        "status": "Paid",
    },
    {
        "id": "1003",
        "type": "Invoice",
        "docNumber": "INV-1003",
        "txnDate": "2025-01-05",
        "dueDate": "2025-01-20",
        "totalAmount": 8750.00,
        "balance": 8750.00,
        "customerName": "TechStart Inc",
        "status": "Overdue",
    },
    {
        "id": "2001",
        "type": "Expense",
        "docNumber": "EXP-2001",
        "txnDate": "2025-01-19",
        "totalAmount": 1250.00,
        "balance": 0,
        "vendorName": "Office Supplies Co",
        "status": "Paid",
    },
    {
        "id": "2002",
        "type": "Expense",
        "docNumber": "EXP-2002",
        "txnDate": "2025-01-15",
        "totalAmount": 4500.00,
        "balance": 0,
        "vendorName": "Cloud Services Inc",
        "status": "Paid",
    },
]


async def get_qbo_connector(request: web.Request) -> Any | None:
    """Get QBO connector from app state if available."""
    return request.app.get("qbo_connector")


async def get_gusto_connector(request: web.Request) -> GustoConnector:
    """Get or create Gusto connector from app state."""
    connector = request.app.get("gusto_connector")
    if not connector:
        connector = GustoConnector()
        request.app["gusto_connector"] = connector

    credentials = request.app.get("gusto_credentials")
    if credentials:
        connector.set_credentials(credentials)

    return connector


def _parse_iso_date(value: str | None, field_name: str) -> date | None:
    """Parse an ISO date query param."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Invalid {field_name}: {value}") from exc


def _parse_bool_param(value: str | None, field_name: str, *, default: bool) -> bool:
    """Parse a boolean query param with strict validation."""
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False

    raise ValueError(f"Invalid {field_name}: {value}")


def _validate_date_range(
    start_value: date | datetime | None,
    end_value: date | datetime | None,
    *,
    start_field: str = "start_date",
    end_field: str = "end_date",
) -> None:
    """Validate that the start of a range is not after the end."""
    if start_value and end_value and start_value > end_value:
        raise ValueError(f"{start_field} must be on or before {end_field}")


@api_endpoint(
    method="GET",
    path="/api/v1/accounting/status",
    summary="Get accounting status",
    description="Check QuickBooks Online connection status and return dashboard data.",
    tags=["Accounting", "QuickBooks"],
    responses={
        "200": {"description": "Accounting status and dashboard data"},
        "401": {"description": "Authentication required"},
        "500": {"description": "Error getting status"},
    },
)
@require_permission("finance:read")
async def handle_accounting_status(request: web.Request) -> web.Response:
    """
    GET /api/accounting/status

    Check QBO connection status and return dashboard data.
    """
    try:
        connector = await get_qbo_connector(request)

        if connector and connector.is_connected():
            # Real QBO data
            company = await connector.get_company_info()
            customers = await connector.list_customers()
            invoices = await connector.list_invoices()
            expenses = await connector.list_expenses()

            # Calculate stats
            receivables = sum(inv.balance for inv in invoices if inv.balance > 0)
            open_invoices = sum(1 for inv in invoices if inv.balance > 0)
            overdue_invoices = sum(
                1
                for inv in invoices
                if inv.balance > 0 and inv.due_date and inv.due_date < datetime.now()
            )

            return web.json_response(
                {
                    "connected": True,
                    "company": {
                        "name": company.name,
                        "legalName": company.legal_name,
                        "country": company.country,
                        "email": company.email,
                    },
                    "stats": {
                        "receivables": receivables,
                        "payables": 0,  # Would need bills API
                        "revenue": 0,
                        "expenses": sum(exp.total_amount for exp in expenses),
                        "netIncome": 0,
                        "openInvoices": open_invoices,
                        "overdueInvoices": overdue_invoices,
                    },
                    "customers": [
                        {
                            "id": c.id,
                            "displayName": c.display_name,
                            "companyName": c.company_name,
                            "email": c.email,
                            "balance": c.balance,
                            "active": c.active,
                        }
                        for c in customers
                    ],
                    "transactions": [
                        {
                            "id": inv.id,
                            "type": inv.type,
                            "docNumber": inv.doc_number,
                            "txnDate": inv.txn_date.isoformat() if inv.txn_date else None,
                            "dueDate": inv.due_date.isoformat() if inv.due_date else None,
                            "totalAmount": inv.total_amount,
                            "balance": inv.balance,
                            "customerName": inv.customer_name,
                            "status": inv.status,
                        }
                        for inv in invoices
                    ],
                }
            )
        else:
            # Return mock data for demo
            return web.json_response(
                {
                    "connected": True,  # Simulated connection
                    "company": MOCK_COMPANY,
                    "stats": MOCK_STATS,
                    "customers": MOCK_CUSTOMERS,
                    "transactions": MOCK_TRANSACTIONS,
                }
            )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error getting accounting status: %s", e)
        return web.json_response(
            {
                "connected": False,
                "error": "Failed to retrieve accounting status",
            },
            status=500,
        )


@require_permission("admin:system")
async def handle_accounting_connect(request: web.Request) -> web.Response:
    """
    GET /api/accounting/connect

    Initiate OAuth flow to connect QuickBooks Online.
    """
    try:
        connector = await get_qbo_connector(request)

        if connector:
            auth_url = connector.get_authorization_url()
            # Redirect to QBO OAuth page
            raise web.HTTPFound(location=auth_url)
        else:
            return web.json_response(
                {
                    "error": "QBO connector not configured",
                    "message": "Set QBO_CLIENT_ID and QBO_CLIENT_SECRET environment variables",
                },
                status=503,
            )

    except web.HTTPFound:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error initiating QBO connection: %s", e)
        return web.json_response(
            {
                "error": "Failed to initiate QuickBooks connection",
            },
            status=500,
        )


async def handle_accounting_callback(request: web.Request) -> web.Response:
    """
    GET /api/accounting/callback

    Handle OAuth callback from QuickBooks.
    """
    try:
        code = request.query.get("code")
        realm_id = request.query.get("realmId")
        _state = request.query.get("state")  # noqa: F841 (for CSRF validation)
        error = request.query.get("error")

        if error:
            return web.json_response(
                {
                    "error": error,
                    "description": request.query.get("error_description", ""),
                },
                status=400,
            )

        if not code or not realm_id:
            return web.json_response(
                {
                    "error": "Missing authorization code or realm ID",
                },
                status=400,
            )

        connector = await get_qbo_connector(request)

        if connector:
            # Exchange code for tokens
            credentials = await connector.exchange_code(code, realm_id)

            # Store credentials (in production, save to database)
            request.app["qbo_credentials"] = credentials

            # Redirect to accounting dashboard
            raise web.HTTPFound(location="/accounting?connected=true")
        else:
            return web.json_response(
                {
                    "error": "QBO connector not available",
                },
                status=503,
            )

    except web.HTTPFound:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error handling OAuth callback: %s", e)
        return web.json_response(
            {
                "error": "Failed to complete OAuth callback",
            },
            status=500,
        )


@require_permission("admin:system")
async def handle_accounting_disconnect(request: web.Request) -> web.Response:
    """
    POST /api/accounting/disconnect

    Disconnect QuickBooks Online integration.
    """
    try:
        connector = await get_qbo_connector(request)

        if connector:
            await connector.revoke_token()

        # Clear stored credentials
        if "qbo_credentials" in request.app:
            del request.app["qbo_credentials"]

        return web.json_response(
            {
                "success": True,
                "message": "QuickBooks disconnected",
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error disconnecting QBO: %s", e)
        return web.json_response(
            {
                "error": "Failed to disconnect QuickBooks",
            },
            status=500,
        )


@api_endpoint(
    method="GET",
    path="/api/v1/accounting/customers",
    summary="List customers",
    description="List all customers from QuickBooks Online.",
    tags=["Accounting", "QuickBooks"],
    parameters=[
        {"name": "active", "in": "query", "schema": {"type": "boolean", "default": True}},
        {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}},
        {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
    ],
    responses={
        "200": {"description": "List of customers"},
        "401": {"description": "Authentication required"},
        "500": {"description": "Error listing customers"},
    },
)
@require_permission("finance:read")
async def handle_accounting_customers(request: web.Request) -> web.Response:
    """
    GET /api/accounting/customers

    List all customers from QuickBooks.
    """
    try:
        try:
            active_only = _parse_bool_param(request.query.get("active"), "active", default=True)
            limit, offset = get_pagination_params(dict(request.query))
        except ValueError:
            return web.json_response({"error": "Invalid query parameter"}, status=400)

        connector = await get_qbo_connector(request)

        if connector and connector.is_connected():
            customers = await connector.list_customers(
                active_only=active_only,
                limit=limit,
                offset=offset,
            )

            return web.json_response(
                {
                    "customers": [
                        {
                            "id": c.id,
                            "displayName": c.display_name,
                            "companyName": c.company_name,
                            "email": c.email,
                            "balance": c.balance,
                            "active": c.active,
                        }
                        for c in customers
                    ],
                    "total": len(customers),
                }
            )
        else:
            return web.json_response(
                {
                    "customers": MOCK_CUSTOMERS,
                    "total": len(MOCK_CUSTOMERS),
                }
            )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error listing customers: %s", e)
        return web.json_response(
            {
                "error": "Failed to list customers",
            },
            status=500,
        )


@api_endpoint(
    method="GET",
    path="/api/v1/accounting/transactions",
    summary="List transactions",
    description="List transactions (invoices, expenses, payments) from QuickBooks.",
    tags=["Accounting", "QuickBooks"],
    parameters=[
        {
            "name": "type",
            "in": "query",
            "schema": {"type": "string", "enum": ["all", "invoice", "expense"]},
        },
        {"name": "start_date", "in": "query", "schema": {"type": "string", "format": "date"}},
        {"name": "end_date", "in": "query", "schema": {"type": "string", "format": "date"}},
    ],
    responses={
        "200": {"description": "List of transactions"},
        "401": {"description": "Authentication required"},
        "500": {"description": "Error listing transactions"},
    },
)
@require_permission("finance:read")
async def handle_accounting_transactions(request: web.Request) -> web.Response:
    """
    GET /api/accounting/transactions

    List transactions (invoices, expenses, payments).
    """
    try:
        txn_type = request.query.get("type", "all").strip().lower()
        if txn_type not in VALID_TRANSACTION_TYPES:
            return web.json_response(
                {
                    "error": f"Invalid type. Expected one of: {', '.join(sorted(VALID_TRANSACTION_TYPES))}",
                },
                status=400,
            )

        start_date_str = request.query.get("start_date")
        end_date_str = request.query.get("end_date")
        try:
            start_date = (
                datetime.fromisoformat(start_date_str)
                if start_date_str
                else datetime.now() - timedelta(days=30)
            )
            end_date = datetime.fromisoformat(end_date_str) if end_date_str else datetime.now()
            _validate_date_range(start_date, end_date)
        except ValueError:
            return web.json_response(
                {"error": "Invalid date range or format. Use ISO 8601."}, status=400
            )

        connector = await get_qbo_connector(request)

        if connector and connector.is_connected():
            transactions = []

            if txn_type in ("all", "invoice"):
                invoices = await connector.list_invoices(start_date=start_date, end_date=end_date)
                transactions.extend(
                    [
                        {
                            "id": inv.id,
                            "type": "Invoice",
                            "docNumber": inv.doc_number,
                            "txnDate": inv.txn_date.isoformat() if inv.txn_date else None,
                            "dueDate": inv.due_date.isoformat() if inv.due_date else None,
                            "totalAmount": inv.total_amount,
                            "balance": inv.balance,
                            "customerName": inv.customer_name,
                            "status": inv.status,
                        }
                        for inv in invoices
                    ]
                )

            if txn_type in ("all", "expense"):
                expenses = await connector.list_expenses(start_date=start_date, end_date=end_date)
                transactions.extend(
                    [
                        {
                            "id": exp.id,
                            "type": "Expense",
                            "docNumber": exp.doc_number,
                            "txnDate": exp.txn_date.isoformat() if exp.txn_date else None,
                            "totalAmount": exp.total_amount,
                            "balance": exp.balance,
                            "vendorName": exp.vendor_name,
                            "status": exp.status,
                        }
                        for exp in expenses
                    ]
                )

            return web.json_response(
                {
                    "transactions": transactions,
                    "total": len(transactions),
                }
            )
        else:
            return web.json_response(
                {
                    "transactions": MOCK_TRANSACTIONS,
                    "total": len(MOCK_TRANSACTIONS),
                }
            )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error listing transactions: %s", e)
        return web.json_response(
            {
                "error": "Failed to list transactions",
            },
            status=500,
        )


@require_permission("finance:read")
async def handle_accounting_report(request: web.Request) -> web.Response:
    """
    POST /api/accounting/report

    Generate a financial report.
    """
    try:
        data, err = await parse_json_body(request, context="accounting_report")
        if err:
            return err
        if not isinstance(data, dict):
            return web.json_response({"error": "Request body must be a JSON object"}, status=400)

        report_type = data.get("type", "profit_loss")
        if not isinstance(report_type, str):
            return web.json_response({"error": "type must be a string"}, status=400)
        report_type = report_type.strip().lower()
        if report_type not in VALID_REPORT_TYPES:
            return web.json_response(
                {
                    "error": f"Unknown report type: {report_type}",
                },
                status=400,
            )

        start_date_str = data.get("start_date")
        end_date_str = data.get("end_date")

        if start_date_str is None or end_date_str is None:
            return web.json_response(
                {
                    "error": "start_date and end_date are required",
                },
                status=400,
            )
        if not isinstance(start_date_str, str) or not isinstance(end_date_str, str):
            return web.json_response(
                {"error": "Invalid date range or format. Use ISO 8601."}, status=400
            )
        if not start_date_str.strip() or not end_date_str.strip():
            return web.json_response(
                {
                    "error": "start_date and end_date are required",
                },
                status=400,
            )

        try:
            start_date = datetime.fromisoformat(start_date_str)
            end_date = datetime.fromisoformat(end_date_str)
            _validate_date_range(start_date, end_date)
        except ValueError:
            return web.json_response(
                {"error": "Invalid date range or format. Use ISO 8601."}, status=400
            )

        connector = await get_qbo_connector(request)

        if connector and connector.is_connected():
            if report_type == "profit_loss":
                report = await connector.get_profit_loss_report(start_date, end_date)
            elif report_type == "balance_sheet":
                report = await connector.get_balance_sheet_report(end_date)
            elif report_type == "ar_aging":
                report = await connector.get_ar_aging_report()
            elif report_type == "ap_aging":
                report = await connector.get_ap_aging_report()

            return web.json_response(
                {
                    "report": report,
                    "generated_at": datetime.now().isoformat(),
                }
            )
        else:
            # Return mock report data
            return web.json_response(
                {
                    "report": _generate_mock_report(report_type, start_date, end_date),
                    "generated_at": datetime.now().isoformat(),
                    "mock": True,
                }
            )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error generating report: %s", e)
        return web.json_response(
            {
                "error": "Failed to generate report",
            },
            status=500,
        )


def _generate_mock_report(
    report_type: str, start_date: datetime, end_date: datetime
) -> dict[str, Any]:
    """Generate mock report data for demo."""
    if report_type == "profit_loss":
        return {
            "title": "Profit and Loss",
            "period": f"{start_date.strftime('%b %d, %Y')} - {end_date.strftime('%b %d, %Y')}",
            "sections": [
                {
                    "name": "Income",
                    "items": [
                        {"name": "Services", "amount": 85000.00},
                        {"name": "Product Sales", "amount": 40000.00},
                    ],
                    "total": 125000.00,
                },
                {
                    "name": "Cost of Goods Sold",
                    "items": [
                        {"name": "Materials", "amount": 15000.00},
                        {"name": "Labor", "amount": 25000.00},
                    ],
                    "total": 40000.00,
                },
                {
                    "name": "Gross Profit",
                    "total": 85000.00,
                },
                {
                    "name": "Expenses",
                    "items": [
                        {"name": "Rent", "amount": 8000.00},
                        {"name": "Utilities", "amount": 2500.00},
                        {"name": "Software", "amount": 4500.00},
                        {"name": "Marketing", "amount": 12000.00},
                        {"name": "Payroll", "amount": 35000.00},
                    ],
                    "total": 62000.00,
                },
            ],
            "netIncome": 23000.00,
        }
    elif report_type == "balance_sheet":
        return {
            "title": "Balance Sheet",
            "as_of": end_date.strftime("%b %d, %Y"),
            "sections": [
                {
                    "name": "Assets",
                    "items": [
                        {"name": "Checking Account", "amount": 45000.00},
                        {"name": "Accounts Receivable", "amount": 46270.50},
                        {"name": "Inventory", "amount": 15000.00},
                        {"name": "Equipment", "amount": 25000.00},
                    ],
                    "total": 131270.50,
                },
                {
                    "name": "Liabilities",
                    "items": [
                        {"name": "Accounts Payable", "amount": 12340.00},
                        {"name": "Credit Card", "amount": 3500.00},
                        {"name": "Loan Payable", "amount": 20000.00},
                    ],
                    "total": 35840.00,
                },
                {
                    "name": "Equity",
                    "items": [
                        {"name": "Owner's Equity", "amount": 72430.50},
                        {"name": "Retained Earnings", "amount": 23000.00},
                    ],
                    "total": 95430.50,
                },
            ],
        }
    elif report_type in ("ar_aging", "ap_aging"):
        prefix = "Accounts Receivable" if report_type == "ar_aging" else "Accounts Payable"
        return {
            "title": f"{prefix} Aging",
            "as_of": datetime.now().strftime("%b %d, %Y"),
            "buckets": [
                {"name": "Current", "amount": 15420.50},
                {"name": "1-30 Days", "amount": 12500.00},
                {"name": "31-60 Days", "amount": 8750.00},
                {"name": "61-90 Days", "amount": 5600.00},
                {"name": "Over 90 Days", "amount": 4000.00},
            ],
            "total": 46270.50,
        }
    else:
        return error_dict(f"Unknown report type: {report_type}", code="VALIDATION_ERROR")


@api_endpoint(
    method="GET",
    path="/api/v1/accounting/gusto/status",
    summary="Get Gusto status",
    description="Check Gusto payroll connection status.",
    tags=["Accounting", "Gusto"],
    responses={
        "200": {"description": "Gusto connection status"},
        "401": {"description": "Authentication required"},
        "500": {"description": "Error getting status"},
    },
)
@require_permission("hr:read")
async def handle_gusto_status(request: web.Request) -> web.Response:
    """
    GET /api/accounting/gusto/status

    Check Gusto connection status.
    """
    try:
        connector = await get_gusto_connector(request)
        credentials = request.app.get("gusto_credentials")
        connected = bool(credentials) and connector.is_authenticated

        return web.json_response(
            {
                "configured": connector.is_configured,
                "connected": connected,
                "company": (
                    {
                        "id": credentials.company_id,
                        "name": credentials.company_name,
                    }
                    if credentials
                    else None
                ),
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error getting Gusto status: %s", e)
        return web.json_response(
            {
                "error": "Failed to retrieve Gusto status",
            },
            status=500,
        )


@require_permission("admin:system")
async def handle_gusto_connect(request: web.Request) -> web.Response:
    """
    GET /api/accounting/gusto/connect

    Initiate OAuth flow to connect Gusto.
    """
    try:
        connector = await get_gusto_connector(request)

        if not connector.is_configured:
            return web.json_response(
                {
                    "error": "Gusto connector not configured",
                    "message": "Set GUSTO_CLIENT_ID, GUSTO_CLIENT_SECRET, GUSTO_REDIRECT_URI",
                },
                status=503,
            )

        auth_url = connector.get_authorization_url()
        raise web.HTTPFound(location=auth_url)

    except web.HTTPFound:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error initiating Gusto connection: %s", e)
        return web.json_response(
            {
                "error": "Failed to initiate Gusto connection",
            },
            status=500,
        )


async def handle_gusto_callback(request: web.Request) -> web.Response:
    """
    GET /api/accounting/gusto/callback

    Handle OAuth callback from Gusto.
    """
    try:
        code = request.query.get("code")
        error = request.query.get("error")

        if error:
            return web.json_response(
                {
                    "error": error,
                    "description": request.query.get("error_description", ""),
                },
                status=400,
            )

        if not code:
            return web.json_response(
                {
                    "error": "Missing authorization code",
                },
                status=400,
            )

        connector = await get_gusto_connector(request)

        if not connector.is_configured:
            return web.json_response(
                {
                    "error": "Gusto connector not available",
                },
                status=503,
            )

        credentials = await connector.exchange_code(code)
        request.app["gusto_credentials"] = credentials
        request.app["gusto_connector"] = connector

        raise web.HTTPFound(location="/accounting?connected=true&provider=gusto")

    except web.HTTPFound:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error handling Gusto OAuth callback: %s", e)
        return web.json_response(
            {
                "error": "Failed to complete Gusto OAuth callback",
            },
            status=500,
        )


@require_permission("admin:system")
async def handle_gusto_disconnect(request: web.Request) -> web.Response:
    """
    POST /api/accounting/gusto/disconnect

    Disconnect Gusto integration.
    """
    try:
        if "gusto_credentials" in request.app:
            del request.app["gusto_credentials"]

        return web.json_response(
            {
                "success": True,
                "message": "Gusto disconnected",
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error disconnecting Gusto: %s", e)
        return web.json_response(
            {
                "error": "Failed to disconnect Gusto",
            },
            status=500,
        )


@api_endpoint(
    method="GET",
    path="/api/v1/accounting/gusto/employees",
    summary="List employees",
    description="List employees from Gusto payroll.",
    tags=["Accounting", "Gusto"],
    parameters=[{"name": "active", "in": "query", "schema": {"type": "boolean", "default": True}}],
    responses={
        "200": {"description": "List of employees"},
        "401": {"description": "Authentication required"},
        "503": {"description": "Gusto not connected"},
    },
)
@require_permission("hr:read")
async def handle_gusto_employees(request: web.Request) -> web.Response:
    """
    GET /api/accounting/gusto/employees

    List employees from Gusto.
    """
    try:
        try:
            active_only = _parse_bool_param(request.query.get("active"), "active", default=True)
        except ValueError:
            return web.json_response({"error": "Invalid query parameter"}, status=400)

        connector = await get_gusto_connector(request)
        if not connector.is_authenticated:
            return web.json_response(
                {
                    "error": "Gusto not connected",
                },
                status=503,
            )

        employees = await connector.list_employees(active_only=active_only)

        return web.json_response(
            {
                "employees": [employee.to_dict() for employee in employees],
                "total": len(employees),
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error listing Gusto employees: %s", e)
        return web.json_response(
            {
                "error": "Failed to list employees",
            },
            status=500,
        )


@api_endpoint(
    method="GET",
    path="/api/v1/accounting/gusto/payrolls",
    summary="List payrolls",
    description="List payroll runs from Gusto.",
    tags=["Accounting", "Gusto"],
    parameters=[
        {"name": "start_date", "in": "query", "schema": {"type": "string", "format": "date"}},
        {"name": "end_date", "in": "query", "schema": {"type": "string", "format": "date"}},
        {"name": "processed", "in": "query", "schema": {"type": "boolean", "default": True}},
    ],
    responses={
        "200": {"description": "List of payroll runs"},
        "400": {"description": "Invalid date format"},
        "401": {"description": "Authentication required"},
        "503": {"description": "Gusto not connected"},
    },
)
@require_permission("hr:read")
async def handle_gusto_payrolls(request: web.Request) -> web.Response:
    """
    GET /api/accounting/gusto/payrolls

    List payroll runs from Gusto.
    """
    try:
        start_date = _parse_iso_date(request.query.get("start_date"), "start_date")
        end_date = _parse_iso_date(request.query.get("end_date"), "end_date")
        _validate_date_range(start_date, end_date)
        processed_only = _parse_bool_param(
            request.query.get("processed"), "processed", default=True
        )

        connector = await get_gusto_connector(request)
        if not connector.is_authenticated:
            return web.json_response(
                {
                    "error": "Gusto not connected",
                },
                status=503,
            )

        payrolls = await connector.list_payrolls(
            start_date=start_date,
            end_date=end_date,
            processed_only=processed_only,
        )

        return web.json_response(
            {
                "payrolls": [payroll.to_dict() for payroll in payrolls],
                "total": len(payrolls),
            }
        )

    except ValueError as e:
        logger.warning("Invalid payroll query parameter: %s", e)
        return web.json_response(
            {
                "error": "Invalid query parameter",
            },
            status=400,
        )
    except (
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error listing Gusto payrolls: %s", e)
        return web.json_response(
            {
                "error": "Failed to list payrolls",
            },
            status=500,
        )


@require_permission("hr:read")
async def handle_gusto_payroll_detail(request: web.Request) -> web.Response:
    """
    GET /api/accounting/gusto/payrolls/{payroll_id}

    Get payroll run details.
    """
    try:
        connector = await get_gusto_connector(request)
        if not connector.is_authenticated:
            return web.json_response(
                {
                    "error": "Gusto not connected",
                },
                status=503,
            )

        payroll_id = request.match_info.get("payroll_id")
        if not payroll_id:
            return web.json_response(
                {
                    "error": "Missing payroll_id",
                },
                status=400,
            )

        payroll = await connector.get_payroll(payroll_id)
        if not payroll:
            return web.json_response(
                {
                    "error": "Payroll not found",
                },
                status=404,
            )

        payroll_data = payroll.to_dict()
        payroll_data["payroll_items"] = [item.to_dict() for item in payroll.payroll_items]

        return web.json_response(
            {
                "payroll": payroll_data,
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error fetching Gusto payroll: %s", e)
        return web.json_response(
            {
                "error": "Failed to fetch payroll details",
            },
            status=500,
        )


@require_permission("finance:write")
async def handle_gusto_journal_entry(request: web.Request) -> web.Response:
    """
    POST /api/accounting/gusto/payrolls/{payroll_id}/journal-entry

    Generate a journal entry for a payroll run.
    """
    try:
        connector = await get_gusto_connector(request)
        if not connector.is_authenticated:
            return web.json_response(
                {
                    "error": "Gusto not connected",
                },
                status=503,
            )

        payroll_id = request.match_info.get("payroll_id")
        if not payroll_id:
            return web.json_response(
                {
                    "error": "Missing payroll_id",
                },
                status=400,
            )

        body, err = await parse_json_body(request, context="gusto_journal_entry", allow_empty=True)
        if err:
            return err
        if body is None:
            body = {}
        elif not isinstance(body, dict):
            return web.json_response({"error": "Request body must be a JSON object"}, status=400)

        account_mappings = {}
        raw_mappings = body.get("account_mappings", {})
        if not isinstance(raw_mappings, dict):
            return web.json_response(
                {"error": "account_mappings must be a JSON object"},
                status=400,
            )
        for key, value in raw_mappings.items():
            if not isinstance(key, str) or not key.strip():
                return web.json_response(
                    {
                        "error": "account_mappings entries must contain string account references",
                    },
                    status=400,
                )
            if isinstance(value, dict):
                account_id = value.get("account_id") or value.get("id")
                account_name = value.get("account_name") or value.get("name")
                if (
                    not isinstance(account_id, str)
                    or not account_id.strip()
                    or not isinstance(account_name, str)
                    or not account_name.strip()
                ):
                    return web.json_response(
                        {
                            "error": "account_mappings entries must contain string account references",
                        },
                        status=400,
                    )
                account_mappings[key] = (account_id, account_name)
            elif isinstance(value, (list, tuple)):
                if len(value) != 2:
                    return web.json_response(
                        {
                            "error": "account_mappings entries must contain string account references",
                        },
                        status=400,
                    )
                account_id, account_name = value
                if (
                    not isinstance(account_id, str)
                    or not account_id.strip()
                    or not isinstance(account_name, str)
                    or not account_name.strip()
                ):
                    return web.json_response(
                        {
                            "error": "account_mappings entries must contain string account references",
                        },
                        status=400,
                    )
                account_mappings[key] = (account_id, account_name)
            else:
                return web.json_response(
                    {
                        "error": "account_mappings entries must contain string account references",
                    },
                    status=400,
                )

        payroll = await connector.get_payroll(payroll_id)
        if not payroll:
            return web.json_response(
                {
                    "error": "Payroll not found",
                },
                status=404,
            )

        journal = connector.generate_journal_entry(
            payroll, account_mappings if account_mappings else None
        )

        payroll_data = payroll.to_dict()
        payroll_data["payroll_items"] = [item.to_dict() for item in payroll.payroll_items]

        return web.json_response(
            {
                "payroll": payroll_data,
                "journal_entry": journal.to_dict(),
            }
        )

    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RuntimeError,
        OSError,
        ConnectionError,
    ) as e:
        logger.warning("Error generating Gusto journal entry: %s", e)
        return web.json_response(
            {
                "error": "Failed to generate journal entry",
            },
            status=500,
        )


def register_accounting_routes(app: web.Application) -> None:
    """Register accounting routes with the application."""
    # v1 canonical routes
    app.router.add_get("/api/v1/accounting/status", handle_accounting_status)
    app.router.add_get("/api/v1/accounting/connect", handle_accounting_connect)
    app.router.add_get("/api/v1/accounting/callback", handle_accounting_callback)
    app.router.add_post("/api/v1/accounting/disconnect", handle_accounting_disconnect)
    app.router.add_get("/api/v1/accounting/customers", handle_accounting_customers)
    app.router.add_get("/api/v1/accounting/transactions", handle_accounting_transactions)
    app.router.add_post("/api/v1/accounting/report", handle_accounting_report)
    app.router.add_get("/api/v1/accounting/gusto/status", handle_gusto_status)
    app.router.add_get("/api/v1/accounting/gusto/connect", handle_gusto_connect)
    app.router.add_get("/api/v1/accounting/gusto/callback", handle_gusto_callback)
    app.router.add_post("/api/v1/accounting/gusto/disconnect", handle_gusto_disconnect)
    app.router.add_get("/api/v1/accounting/gusto/employees", handle_gusto_employees)
    app.router.add_get("/api/v1/accounting/gusto/payrolls", handle_gusto_payrolls)
    app.router.add_get(
        "/api/v1/accounting/gusto/payrolls/{payroll_id}",
        handle_gusto_payroll_detail,
    )

    # legacy routes
    app.router.add_get("/api/accounting/status", handle_accounting_status)
    app.router.add_get("/api/accounting/connect", handle_accounting_connect)
    app.router.add_get("/api/accounting/callback", handle_accounting_callback)
    app.router.add_post("/api/accounting/disconnect", handle_accounting_disconnect)
    app.router.add_get("/api/accounting/customers", handle_accounting_customers)
    app.router.add_get("/api/accounting/transactions", handle_accounting_transactions)
    app.router.add_post("/api/accounting/report", handle_accounting_report)
    app.router.add_get("/api/accounting/gusto/status", handle_gusto_status)
    app.router.add_get("/api/accounting/gusto/connect", handle_gusto_connect)
    app.router.add_get("/api/accounting/gusto/callback", handle_gusto_callback)
    app.router.add_post("/api/accounting/gusto/disconnect", handle_gusto_disconnect)
    app.router.add_get("/api/accounting/gusto/employees", handle_gusto_employees)
    app.router.add_get("/api/accounting/gusto/payrolls", handle_gusto_payrolls)
    app.router.add_get(
        "/api/accounting/gusto/payrolls/{payroll_id}",
        handle_gusto_payroll_detail,
    )
    app.router.add_post(
        "/api/accounting/gusto/payrolls/{payroll_id}/journal-entry",
        handle_gusto_journal_entry,
    )
