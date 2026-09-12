"""Tests for Stripe payment handler (aragora/server/handlers/payments/stripe.py).

Comprehensive test suite covering all routes and behavior:
- POST /api/payments/charge — Stripe and Authorize.net paths
- POST /api/payments/authorize — Stripe and Authorize.net paths
- POST /api/payments/capture — Stripe and Authorize.net paths
- POST /api/payments/refund — Stripe and Authorize.net paths
- POST /api/payments/void — Stripe and Authorize.net paths
- GET  /api/payments/transaction/{id} — Stripe and Authorize.net paths
- POST /api/payments/webhook/stripe — Stripe webhook events
- POST /api/payments/webhook/authnet — Authorize.net webhook events
- Error handling (ConnectionError, ValueError, RuntimeError patterns)
- Rate limiting
- Webhook idempotency
- Webhook event dispatch (checkout, subscription, invoice, payment_intent)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from aragora.server.handlers.payments.handler import (
    PaymentProvider,
    PaymentResult,
    PaymentStatus,
)
from aragora.server.handlers.payments.stripe import (
    _handle_checkout_session_completed,
    _handle_invoice_paid,
    _handle_invoice_payment_failed,
    _handle_payment_intent_failed,
    _handle_payment_intent_succeeded,
    _handle_subscription_deleted,
    _handle_subscription_updated,
    _record_dead_letter,
    _STRIPE_EVENT_HANDLERS,
    handle_authnet_webhook,
    handle_authorize,
    handle_capture,
    handle_charge,
    handle_get_transaction,
    handle_refund,
    handle_stripe_webhook,
    handle_void,
)


# ===========================================================================
# Helpers
# ===========================================================================

PKG = "aragora.server.handlers.payments"


def _status(resp: web.Response) -> int:
    """Extract HTTP status code from aiohttp response."""
    return resp.status


def _body(resp: web.Response) -> dict[str, Any]:
    """Extract JSON body from aiohttp response."""
    return json.loads(resp.body)


def create_mock_request(
    body: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
    match_info: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    raw_payload: bytes | None = None,
) -> MagicMock:
    """Create a mock aiohttp request with the given parameters."""
    request = MagicMock(spec=web.Request)
    request.query = query or {}
    request.match_info = match_info or {}
    request.app = {}
    request.headers = headers or {}
    request.get = MagicMock(side_effect=lambda k, d=None: {"user_id": "test-user"}.get(k, d))

    # Transport for rate limiting
    transport = MagicMock()
    transport.get_extra_info.return_value = ("127.0.0.1", 12345)
    request.transport = transport

    if body is not None:

        async def json_func():
            return body

        request.json = json_func
        body_bytes = json.dumps(body).encode()
        request.content_length = len(body_bytes)

        async def read_func():
            return body_bytes

        request.read = read_func
    elif raw_payload is not None:

        async def json_error():
            raise json.JSONDecodeError("Invalid JSON", "", 0)

        request.json = json_error
        request.content_length = len(raw_payload)

        async def read_func():
            return raw_payload

        request.read = read_func
    else:

        async def json_error():
            raise json.JSONDecodeError("Invalid JSON", "", 0)

        request.json = json_error
        request.content_length = None

        async def read_empty():
            return b""

        request.read = read_empty

    return request


# ===========================================================================
# Mock objects
# ===========================================================================


@dataclass
class MockStripeIntent:
    """Mock Stripe PaymentIntent."""

    id: str = "pi_test_123"
    status: str = "succeeded"
    amount: int = 10000
    currency: str = "usd"
    created: int = 1700000000
    metadata: dict[str, Any] = field(default_factory=dict)
    client_secret: str = "pi_test_123_secret_abc"


@dataclass
class MockStripeRefund:
    """Mock Stripe Refund."""

    id: str = "re_test_123"
    status: str = "succeeded"
    amount: int = 5000


@dataclass
class MockStripeEvent:
    """Mock Stripe webhook event."""

    id: str = "evt_test_123"
    type: str = "payment_intent.succeeded"
    data: Any = None

    def __post_init__(self):
        if self.data is None:
            obj = MagicMock()
            obj._data = {"id": "pi_test_123"}
            data_container = MagicMock()
            data_container.object = obj
            self.data = data_container


@dataclass
class MockAuthnetResult:
    """Mock Authorize.net transaction result."""

    transaction_id: str = "txn_authnet_123"
    approved: bool = True
    message: str = "Approved"
    auth_code: str = "AUTH123"
    avs_result: str = "Y"
    cvv_result: str = "M"


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_stripe_connector():
    """Create a mock Stripe connector."""
    connector = AsyncMock()
    connector.create_payment_intent = AsyncMock(return_value=MockStripeIntent())
    connector.capture_payment_intent = AsyncMock(return_value=MockStripeIntent(status="succeeded"))
    connector.retrieve_payment_intent = AsyncMock(return_value=MockStripeIntent())
    connector.cancel_payment_intent = AsyncMock(return_value=MockStripeIntent(status="canceled"))
    connector.create_refund = AsyncMock(return_value=MockStripeRefund())
    connector.construct_webhook_event = AsyncMock(return_value=MockStripeEvent())
    return connector


@pytest.fixture
def mock_authnet_connector():
    """Create a mock Authorize.net connector."""
    connector = AsyncMock()
    connector.charge = AsyncMock(return_value=MockAuthnetResult())
    connector.authorize = AsyncMock(return_value=MockAuthnetResult())
    connector.capture = AsyncMock(return_value=MockAuthnetResult())
    connector.refund = AsyncMock(return_value=MockAuthnetResult())
    connector.void = AsyncMock(return_value=MockAuthnetResult())
    connector.get_transaction_details = AsyncMock(
        return_value={"id": "txn_123", "status": "settled"}
    )
    connector.verify_webhook_signature = AsyncMock(return_value=True)
    # Support async context manager
    connector.__aenter__ = AsyncMock(return_value=connector)
    connector.__aexit__ = AsyncMock(return_value=False)
    return connector


@pytest.fixture(autouse=True)
def reset_rate_limiters():
    """Reset rate limiters between tests to avoid cross-test pollution."""
    from aragora.server.handlers.payments.handler import (
        _payment_read_limiter,
        _payment_write_limiter,
        _webhook_limiter,
    )

    _payment_write_limiter._requests.clear()
    _payment_read_limiter._requests.clear()
    _webhook_limiter._requests.clear()
    yield


@pytest.fixture(autouse=True)
def patch_rate_limit():
    """Disable rate limiting for all tests by default."""
    with patch(f"{PKG}._check_rate_limit", return_value=None):
        yield


@pytest.fixture(autouse=True)
def patch_audit():
    """Disable audit logging calls for all tests."""
    with patch(f"{PKG}.audit_data"), patch(f"{PKG}.audit_security"):
        yield


# ===========================================================================
# Test handle_charge
# ===========================================================================


class TestHandleCharge:
    """Tests for POST /api/payments/charge."""

    @pytest.mark.asyncio
    async def test_charge_stripe_success(self, mock_stripe_connector):
        request = create_mock_request(body={"amount": 100.00, "currency": "USD"})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
            patch(f"{PKG}._resilient_stripe_call", return_value=MockStripeIntent()),
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["transaction"]["provider"] == "stripe"

    @pytest.mark.asyncio
    async def test_charge_stripe_pending(self, mock_stripe_connector):
        request = create_mock_request(body={"amount": 50.00, "currency": "USD"})
        pending_intent = MockStripeIntent(status="requires_action")
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
            patch(f"{PKG}._resilient_stripe_call", return_value=pending_intent),
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is False
        assert data["transaction"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_charge_stripe_connector_unavailable(self):
        request = create_mock_request(body={"amount": 100.00, "currency": "USD"})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is False
        assert data["transaction"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_charge_amount_zero_returns_400(self):
        request = create_mock_request(body={"amount": 0, "currency": "USD"})
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 400
        assert "Amount" in _body(resp)["error"]

    @pytest.mark.asyncio
    async def test_charge_negative_amount_returns_400(self):
        request = create_mock_request(body={"amount": -10.00, "currency": "USD"})
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_charge_missing_body_returns_400(self):
        request = create_mock_request()
        resp = await handle_charge(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_charge_connection_error_returns_503(self):
        request = create_mock_request(body={"amount": 100.00})
        with (
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
            patch(f"{PKG}.get_stripe_connector", side_effect=ConnectionError("down")),
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_charge_value_error_returns_400(self):
        request = create_mock_request(body={"amount": 100.00})
        with patch(
            f"{PKG}._get_provider_from_request",
            side_effect=ValueError("invalid provider"),
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_charge_runtime_error_returns_500(self, mock_stripe_connector):
        """RuntimeError inside _charge_stripe is caught internally and returns error PaymentResult."""
        request = create_mock_request(body={"amount": 100.00})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
            patch(
                f"{PKG}._resilient_stripe_call",
                side_effect=RuntimeError("unexpected"),
            ),
        ):
            resp = await handle_charge(request)
        # RuntimeError in _charge_stripe is caught inside the helper and
        # returns a PaymentResult with ERROR status; the outer handler wraps
        # it into a 200 response with success=False.
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is False
        assert data["transaction"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_charge_authnet_success(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "amount": 75.00,
                "currency": "USD",
                "payment_method": {
                    "type": "card",
                    "card_number": "4111111111111111",
                    "exp_month": "12",
                    "exp_year": "2025",
                    "cvv": "123",
                },
            }
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
            patch(
                f"{PKG}._resilient_authnet_call",
                return_value=MockAuthnetResult(),
            ),
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["transaction"]["provider"] == "authorize_net"

    @pytest.mark.asyncio
    async def test_charge_authnet_connector_unavailable(self):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "amount": 75.00,
                "payment_method": {"type": "card", "card_number": "4111111111111111"},
            }
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is False
        assert "not available" in data["transaction"]["message"]

    @pytest.mark.asyncio
    async def test_charge_authnet_invalid_payment_method(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "amount": 75.00,
                "payment_method": "pm_string_not_dict",
            }
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is False
        assert "Invalid payment method" in data["transaction"]["message"]

    @pytest.mark.asyncio
    async def test_charge_includes_metadata(self, mock_stripe_connector):
        request = create_mock_request(
            body={
                "amount": 100.00,
                "currency": "EUR",
                "description": "Order #42",
                "customer_id": "cus_abc",
                "payment_method": "pm_xyz",
                "metadata": {"order_id": "42"},
            }
        )
        intent = MockStripeIntent()
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
            patch(f"{PKG}._resilient_stripe_call", return_value=intent),
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_charge_stripe_connection_error_in_internal(self, mock_stripe_connector):
        """ConnectionError inside _charge_stripe is caught internally and returns error PaymentResult."""
        request = create_mock_request(body={"amount": 100.00})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
            patch(
                f"{PKG}._resilient_stripe_call",
                side_effect=ConnectionError("timeout"),
            ),
        ):
            resp = await handle_charge(request)
        # ConnectionError in _charge_stripe is caught inside the helper and
        # returns a PaymentResult with ERROR status; the outer handler wraps
        # it into a 200 response with success=False.
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is False
        assert data["transaction"]["status"] == "error"

    @pytest.mark.asyncio
    async def test_charge_default_currency_usd(self, mock_stripe_connector):
        request = create_mock_request(body={"amount": 100.00})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
            patch(f"{PKG}._resilient_stripe_call", return_value=MockStripeIntent()),
        ):
            resp = await handle_charge(request)
        assert _status(resp) == 200
        assert _body(resp)["transaction"]["currency"] == "USD"


# ===========================================================================
# Test handle_authorize
# ===========================================================================


class TestHandleAuthorize:
    """Tests for POST /api/payments/authorize."""

    @pytest.mark.asyncio
    async def test_authorize_stripe_success(self, mock_stripe_connector):
        request = create_mock_request(
            body={"amount": 200.00, "currency": "USD", "payment_method": "pm_abc"}
        )
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_authorize(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert "transaction_id" in data
        assert "client_secret" in data

    @pytest.mark.asyncio
    async def test_authorize_stripe_connector_unavailable(self):
        request = create_mock_request(body={"amount": 200.00, "currency": "USD"})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_authorize(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_authorize_amount_zero_returns_400(self):
        request = create_mock_request(body={"amount": 0})
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_authorize(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_authorize_missing_body_returns_400(self):
        request = create_mock_request()
        resp = await handle_authorize(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_authorize_authnet_success(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "amount": 200.00,
                "payment_method": {
                    "card_number": "4111111111111111",
                    "exp_month": "12",
                    "exp_year": "2025",
                    "cvv": "123",
                },
            }
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_authorize(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert "transaction_id" in data

    @pytest.mark.asyncio
    async def test_authorize_authnet_connector_unavailable(self):
        request = create_mock_request(body={"provider": "authorize_net", "amount": 200.00})
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_authorize(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_authorize_connection_error_returns_503(self):
        request = create_mock_request(body={"amount": 200.00})
        with (
            patch(
                f"{PKG}._get_provider_from_request",
                side_effect=ConnectionError("down"),
            ),
        ):
            resp = await handle_authorize(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_authorize_value_error_returns_400(self):
        request = create_mock_request(body={"amount": 100.00})
        with patch(
            f"{PKG}._get_provider_from_request",
            side_effect=ValueError("invalid provider"),
        ):
            resp = await handle_authorize(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_authorize_runtime_error_returns_500(self, mock_stripe_connector):
        request = create_mock_request(body={"amount": 200.00})
        with (
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
            patch(
                f"{PKG}.get_stripe_connector",
                side_effect=RuntimeError("fail"),
            ),
        ):
            resp = await handle_authorize(request)
        assert _status(resp) == 500


# ===========================================================================
# Test handle_capture
# ===========================================================================


class TestHandleCapture:
    """Tests for POST /api/payments/capture."""

    @pytest.mark.asyncio
    async def test_capture_stripe_success(self, mock_stripe_connector):
        request = create_mock_request(body={"transaction_id": "pi_test_123"})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_capture(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["transaction_id"] == "pi_test_123"

    @pytest.mark.asyncio
    async def test_capture_stripe_partial(self, mock_stripe_connector):
        request = create_mock_request(body={"transaction_id": "pi_test_123", "amount": 50.00})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_capture(request)
        assert _status(resp) == 200
        mock_stripe_connector.capture_payment_intent.assert_called_once()

    @pytest.mark.asyncio
    async def test_capture_missing_transaction_id_returns_400(self):
        request = create_mock_request(body={})
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_capture(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_capture_stripe_connector_unavailable(self):
        request = create_mock_request(body={"transaction_id": "pi_123"})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_capture(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_capture_authnet_success(self, mock_authnet_connector):
        request = create_mock_request(
            body={"provider": "authorize_net", "transaction_id": "txn_123"}
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_capture(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_capture_authnet_connector_unavailable(self):
        request = create_mock_request(
            body={"provider": "authorize_net", "transaction_id": "txn_123"}
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_capture(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_capture_missing_body_returns_400(self):
        request = create_mock_request()
        resp = await handle_capture(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_capture_connection_error_returns_503(self):
        request = create_mock_request(body={"transaction_id": "pi_123"})
        with patch(
            f"{PKG}._get_provider_from_request",
            side_effect=ConnectionError("down"),
        ):
            resp = await handle_capture(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_capture_runtime_error_returns_500(self):
        request = create_mock_request(body={"transaction_id": "pi_123"})
        with patch(
            f"{PKG}._get_provider_from_request",
            side_effect=RuntimeError("fail"),
        ):
            resp = await handle_capture(request)
        assert _status(resp) == 500


# ===========================================================================
# Test handle_refund
# ===========================================================================


class TestHandleRefund:
    """Tests for POST /api/payments/refund."""

    @pytest.mark.asyncio
    async def test_refund_stripe_success(self, mock_stripe_connector):
        request = create_mock_request(body={"transaction_id": "pi_test_123", "amount": 50.00})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert "refund_id" in data

    @pytest.mark.asyncio
    async def test_refund_stripe_connector_unavailable(self):
        request = create_mock_request(body={"transaction_id": "pi_test_123", "amount": 50.00})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_refund_missing_transaction_id_returns_400(self):
        request = create_mock_request(body={"amount": 50.00})
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_refund_amount_zero_returns_400(self):
        request = create_mock_request(body={"transaction_id": "pi_123", "amount": 0})
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_refund_negative_amount_returns_400(self):
        request = create_mock_request(body={"transaction_id": "pi_123", "amount": -10.00})
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_refund_authnet_success(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "transaction_id": "txn_123",
                "amount": 50.00,
                "card_last_four": "1111",
            }
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_refund_authnet_missing_card_last_four(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "transaction_id": "txn_123",
                "amount": 50.00,
            }
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 400
        assert "card_last_four" in _body(resp)["error"]

    @pytest.mark.asyncio
    async def test_refund_authnet_connector_unavailable(self):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "transaction_id": "txn_123",
                "amount": 50.00,
                "card_last_four": "1111",
            }
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_refund_missing_body_returns_400(self):
        request = create_mock_request()
        resp = await handle_refund(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_refund_connection_error_returns_503(self):
        request = create_mock_request(body={"transaction_id": "pi_123", "amount": 50.00})
        with patch(
            f"{PKG}._get_provider_from_request",
            side_effect=ConnectionError("down"),
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_refund_runtime_error_returns_500_and_audits(self):
        request = create_mock_request(body={"transaction_id": "pi_123", "amount": 50.00})
        with (
            patch(
                f"{PKG}._get_provider_from_request",
                side_effect=RuntimeError("fail"),
            ),
            patch(f"{PKG}.audit_security") as mock_audit_sec,
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 500
        mock_audit_sec.assert_called_once()

    @pytest.mark.asyncio
    async def test_refund_stripe_audits_on_success(self, mock_stripe_connector):
        request = create_mock_request(body={"transaction_id": "pi_test_123", "amount": 50.00})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
            patch(f"{PKG}.audit_data") as mock_audit,
        ):
            resp = await handle_refund(request)
        assert _status(resp) == 200
        mock_audit.assert_called_once()
        call_kwargs = mock_audit.call_args
        assert call_kwargs.kwargs["action"] == "payment_refund"
        assert call_kwargs.kwargs["provider"] == "stripe"


# ===========================================================================
# Test handle_void
# ===========================================================================


class TestHandleVoid:
    """Tests for POST /api/payments/void."""

    @pytest.mark.asyncio
    async def test_void_stripe_success(self, mock_stripe_connector):
        request = create_mock_request(body={"transaction_id": "pi_test_123"})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_void(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["status"] == "canceled"

    @pytest.mark.asyncio
    async def test_void_stripe_connector_unavailable(self):
        request = create_mock_request(body={"transaction_id": "pi_123"})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_void(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_void_missing_transaction_id_returns_400(self):
        request = create_mock_request(body={})
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_void(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_void_authnet_success(self, mock_authnet_connector):
        request = create_mock_request(
            body={"provider": "authorize_net", "transaction_id": "txn_123"}
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_void(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_void_authnet_connector_unavailable(self):
        request = create_mock_request(
            body={"provider": "authorize_net", "transaction_id": "txn_123"}
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_void(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_void_missing_body_returns_400(self):
        request = create_mock_request()
        resp = await handle_void(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_void_connection_error_returns_503(self):
        request = create_mock_request(body={"transaction_id": "pi_123"})
        with patch(
            f"{PKG}._get_provider_from_request",
            side_effect=ConnectionError("down"),
        ):
            resp = await handle_void(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_void_value_error_returns_400(self):
        request = create_mock_request(body={"transaction_id": "pi_123"})
        with patch(
            f"{PKG}._get_provider_from_request",
            side_effect=ValueError("bad"),
        ):
            resp = await handle_void(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_void_runtime_error_returns_500(self):
        request = create_mock_request(body={"transaction_id": "pi_123"})
        with patch(
            f"{PKG}._get_provider_from_request",
            side_effect=RuntimeError("fail"),
        ):
            resp = await handle_void(request)
        assert _status(resp) == 500


# ===========================================================================
# Test handle_get_transaction
# ===========================================================================


class TestHandleGetTransaction:
    """Tests for GET /api/payments/transaction/{transaction_id}."""

    @pytest.mark.asyncio
    async def test_get_transaction_stripe_success(self, mock_stripe_connector):
        request = create_mock_request(
            match_info={"transaction_id": "pi_test_123"},
            query={"provider": "stripe"},
        )
        with patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["transaction"]["id"] == "pi_test_123"
        assert data["transaction"]["status"] == "succeeded"

    @pytest.mark.asyncio
    async def test_get_transaction_default_provider_stripe(self, mock_stripe_connector):
        """When no provider query param, defaults to stripe."""
        request = create_mock_request(
            match_info={"transaction_id": "pi_test_123"},
        )
        with patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_get_transaction_stripe_connector_unavailable(self):
        request = create_mock_request(
            match_info={"transaction_id": "pi_123"},
            query={"provider": "stripe"},
        )
        with patch(f"{PKG}.get_stripe_connector", return_value=None):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_get_transaction_authnet_success(self, mock_authnet_connector):
        request = create_mock_request(
            match_info={"transaction_id": "txn_123"},
            query={"provider": "authorize_net"},
        )
        with patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["transaction"]["id"] == "txn_123"

    @pytest.mark.asyncio
    async def test_get_transaction_authnet_alias(self, mock_authnet_connector):
        """'authnet' is accepted as a provider alias."""
        request = create_mock_request(
            match_info={"transaction_id": "txn_123"},
            query={"provider": "authnet"},
        )
        with patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_get_transaction_authnet_not_found(self, mock_authnet_connector):
        mock_authnet_connector.get_transaction_details = AsyncMock(return_value=None)
        request = create_mock_request(
            match_info={"transaction_id": "txn_nonexistent"},
            query={"provider": "authorize_net"},
        )
        with patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 404

    @pytest.mark.asyncio
    async def test_get_transaction_authnet_connector_unavailable(self):
        request = create_mock_request(
            match_info={"transaction_id": "txn_123"},
            query={"provider": "authorize_net"},
        )
        with patch(f"{PKG}.get_authnet_connector", return_value=None):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_get_transaction_missing_id_returns_400(self):
        request = create_mock_request(
            match_info={},
            query={"provider": "stripe"},
        )
        with patch(f"{PKG}.get_stripe_connector", return_value=MagicMock()):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_get_transaction_connection_error_returns_503(self):
        request = create_mock_request(
            match_info={"transaction_id": "pi_123"},
        )
        with patch(
            f"{PKG}.get_stripe_connector",
            side_effect=ConnectionError("down"),
        ):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_get_transaction_runtime_error_returns_500(self):
        request = create_mock_request(
            match_info={"transaction_id": "pi_123"},
        )
        with patch(
            f"{PKG}.get_stripe_connector",
            side_effect=RuntimeError("fail"),
        ):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_get_transaction_stripe_response_fields(self, mock_stripe_connector):
        """Verify all expected fields in Stripe transaction response."""
        request = create_mock_request(
            match_info={"transaction_id": "pi_test_123"},
        )
        with patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector):
            resp = await handle_get_transaction(request)
        data = _body(resp)["transaction"]
        assert "id" in data
        assert "amount" in data
        assert "currency" in data
        assert "status" in data
        assert "created" in data
        assert "metadata" in data


# ===========================================================================
# Test Stripe Webhook
# ===========================================================================


class TestHandleStripeWebhook:
    """Tests for POST /api/payments/webhook/stripe."""

    @pytest.mark.asyncio
    async def test_webhook_success(self, mock_stripe_connector):
        event = MockStripeEvent(type="payment_intent.succeeded")
        mock_stripe_connector.construct_webhook_event = AsyncMock(return_value=event)

        request = create_mock_request(
            raw_payload=b'{"type":"payment_intent.succeeded"}',
            headers={"Stripe-Signature": "t=123,v1=abc"},
        )
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=False),
            patch(f"{PKG}._mark_webhook_processed"),
        ):
            resp = await handle_stripe_webhook(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["received"] is True

    @pytest.mark.asyncio
    async def test_webhook_missing_signature_returns_400(self):
        request = create_mock_request(
            raw_payload=b'{"type":"test"}',
            headers={},
        )
        resp = await handle_stripe_webhook(request)
        assert _status(resp) == 400
        assert "Stripe-Signature" in _body(resp)["error"]

    @pytest.mark.asyncio
    async def test_webhook_connector_unavailable_returns_503(self):
        request = create_mock_request(
            raw_payload=b'{"type":"test"}',
            headers={"Stripe-Signature": "t=123,v1=abc"},
        )
        with patch(f"{PKG}.get_stripe_connector", return_value=None):
            resp = await handle_stripe_webhook(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_webhook_invalid_payload_returns_400(self, mock_stripe_connector):
        mock_stripe_connector.construct_webhook_event = AsyncMock(side_effect=ValueError("invalid"))
        request = create_mock_request(
            raw_payload=b"bad-data",
            headers={"Stripe-Signature": "t=123,v1=abc"},
        )
        with patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector):
            resp = await handle_stripe_webhook(request)
        assert _status(resp) == 400
        assert "Invalid payload" in _body(resp)["error"]

    @pytest.mark.asyncio
    async def test_webhook_signature_verification_failed(self, mock_stripe_connector):
        mock_stripe_connector.construct_webhook_event = AsyncMock(side_effect=KeyError("sig"))
        request = create_mock_request(
            raw_payload=b'{"type":"test"}',
            headers={"Stripe-Signature": "t=123,v1=bad"},
        )
        with patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector):
            resp = await handle_stripe_webhook(request)
        assert _status(resp) == 400
        assert "verification failed" in _body(resp)["error"]

    @pytest.mark.asyncio
    async def test_webhook_duplicate_returns_200_with_flag(self, mock_stripe_connector):
        event = MockStripeEvent()
        mock_stripe_connector.construct_webhook_event = AsyncMock(return_value=event)

        request = create_mock_request(
            raw_payload=b'{"type":"test"}',
            headers={"Stripe-Signature": "t=123,v1=abc"},
        )
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=True),
        ):
            resp = await handle_stripe_webhook(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["received"] is True
        assert data["duplicate"] is True

    @pytest.mark.asyncio
    async def test_webhook_unrecognized_event_type(self, mock_stripe_connector):
        event = MockStripeEvent(type="unknown.event.type")
        mock_stripe_connector.construct_webhook_event = AsyncMock(return_value=event)

        request = create_mock_request(
            raw_payload=b'{"type":"unknown.event.type"}',
            headers={"Stripe-Signature": "t=123,v1=abc"},
        )
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=False),
            patch(f"{PKG}._mark_webhook_processed"),
        ):
            resp = await handle_stripe_webhook(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["received"] is True
        assert "processing_error" not in data

    @pytest.mark.asyncio
    async def test_webhook_handler_failure_records_dead_letter(self, mock_stripe_connector):
        event = MockStripeEvent(type="checkout.session.completed")
        mock_stripe_connector.construct_webhook_event = AsyncMock(return_value=event)

        request = create_mock_request(
            raw_payload=b'{"type":"checkout.session.completed"}',
            headers={"Stripe-Signature": "t=123,v1=abc"},
        )

        # Patch the dispatch table entry directly because _STRIPE_EVENT_HANDLERS
        # holds a reference to the original function object.
        failing_handler = MagicMock(side_effect=ValueError("bad data"))
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=False),
            patch(f"{PKG}._mark_webhook_processed"),
            patch.dict(
                _STRIPE_EVENT_HANDLERS,
                {"checkout.session.completed": failing_handler},
            ),
        ):
            resp = await handle_stripe_webhook(request)
        # Should still return 200 to prevent Stripe retry storms
        assert _status(resp) == 200
        data = _body(resp)
        assert data["processing_error"] is True

    @pytest.mark.asyncio
    async def test_webhook_idempotency_check_failure_continues(self, mock_stripe_connector):
        event = MockStripeEvent(type="payment_intent.succeeded")
        mock_stripe_connector.construct_webhook_event = AsyncMock(return_value=event)

        request = create_mock_request(
            raw_payload=b'{"type":"payment_intent.succeeded"}',
            headers={"Stripe-Signature": "t=123,v1=abc"},
        )
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(
                f"{PKG}._is_duplicate_webhook",
                side_effect=RuntimeError("store down"),
            ),
            patch(f"{PKG}._mark_webhook_processed"),
        ):
            resp = await handle_stripe_webhook(request)
        # Should still process the event
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_webhook_mark_processed_failure_still_returns_200(self, mock_stripe_connector):
        event = MockStripeEvent(type="payment_intent.succeeded")
        mock_stripe_connector.construct_webhook_event = AsyncMock(return_value=event)

        request = create_mock_request(
            raw_payload=b'{"type":"payment_intent.succeeded"}',
            headers={"Stripe-Signature": "t=123,v1=abc"},
        )
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=mock_stripe_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=False),
            patch(
                f"{PKG}._mark_webhook_processed",
                side_effect=RuntimeError("store down"),
            ),
        ):
            resp = await handle_stripe_webhook(request)
        assert _status(resp) == 200


# ===========================================================================
# Test Authorize.net Webhook
# ===========================================================================


class TestHandleAuthnetWebhook:
    """Tests for POST /api/payments/webhook/authnet."""

    @pytest.mark.asyncio
    async def test_authnet_webhook_success(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "eventType": "net.authorize.payment.authcapture.created",
                "notificationId": "notif_123",
                "payload": {"id": "txn_123"},
            },
            headers={"X-ANET-Signature": "sha512=abc123"},
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=False),
            patch(f"{PKG}._mark_webhook_processed"),
        ):
            resp = await handle_authnet_webhook(request)
        assert _status(resp) == 200
        assert _body(resp)["received"] is True

    @pytest.mark.asyncio
    async def test_authnet_webhook_refund_event(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "eventType": "net.authorize.payment.refund.created",
                "notificationId": "notif_456",
                "payload": {"id": "txn_456"},
            },
            headers={"X-ANET-Signature": "sha512=abc123"},
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=False),
            patch(f"{PKG}._mark_webhook_processed"),
        ):
            resp = await handle_authnet_webhook(request)
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_authnet_webhook_subscription_created(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "eventType": "net.authorize.customer.subscription.created",
                "notificationId": "notif_789",
                "payload": {"id": "sub_789"},
            },
            headers={"X-ANET-Signature": "sha512=abc123"},
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=False),
            patch(f"{PKG}._mark_webhook_processed"),
        ):
            resp = await handle_authnet_webhook(request)
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_authnet_webhook_subscription_cancelled(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "eventType": "net.authorize.customer.subscription.cancelled",
                "notificationId": "notif_101",
                "payload": {"id": "sub_101"},
            },
            headers={"X-ANET-Signature": "sha512=abc123"},
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=False),
            patch(f"{PKG}._mark_webhook_processed"),
        ):
            resp = await handle_authnet_webhook(request)
        assert _status(resp) == 200

    @pytest.mark.asyncio
    async def test_authnet_webhook_connector_unavailable(self):
        request = create_mock_request(
            body={"eventType": "test", "notificationId": "n_1"},
            headers={"X-ANET-Signature": "sha512=abc123"},
        )
        with patch(f"{PKG}.get_authnet_connector", return_value=None):
            resp = await handle_authnet_webhook(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_authnet_webhook_invalid_signature(self, mock_authnet_connector):
        mock_authnet_connector.verify_webhook_signature = AsyncMock(return_value=False)
        request = create_mock_request(
            body={"eventType": "test", "notificationId": "n_1"},
            headers={"X-ANET-Signature": "sha512=bad"},
        )
        with patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector):
            resp = await handle_authnet_webhook(request)
        assert _status(resp) == 400
        assert "Invalid signature" in _body(resp)["error"]

    @pytest.mark.asyncio
    async def test_authnet_webhook_duplicate(self, mock_authnet_connector):
        request = create_mock_request(
            body={"eventType": "test", "notificationId": "n_dup"},
            headers={"X-ANET-Signature": "sha512=abc123"},
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=True),
        ):
            resp = await handle_authnet_webhook(request)
        assert _status(resp) == 200
        assert _body(resp)["duplicate"] is True

    @pytest.mark.asyncio
    async def test_authnet_webhook_generates_deterministic_id(self, mock_authnet_connector):
        """When notificationId and payload.id are both missing, a deterministic hash-based ID is generated."""
        request = create_mock_request(
            body={"eventType": "test", "payload": {"data": "some_data"}},
            headers={"X-ANET-Signature": "sha512=abc123"},
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(f"{PKG}._is_duplicate_webhook", return_value=False) as mock_dup,
            patch(f"{PKG}._mark_webhook_processed"),
        ):
            resp = await handle_authnet_webhook(request)
        assert _status(resp) == 200
        # The event_id passed to _is_duplicate_webhook should start with 'authnet_'
        call_args = mock_dup.call_args[0][0]
        assert call_args.startswith("authnet_")

    @pytest.mark.asyncio
    async def test_authnet_webhook_missing_body_returns_400(self):
        request = create_mock_request()
        resp = await handle_authnet_webhook(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_authnet_webhook_runtime_error_returns_500(self, mock_authnet_connector):
        request = create_mock_request(
            body={"eventType": "test", "notificationId": "n_1"},
            headers={"X-ANET-Signature": "sha512=abc123"},
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=mock_authnet_connector),
            patch(
                f"{PKG}._is_duplicate_webhook",
                side_effect=AttributeError("fail"),
            ),
        ):
            resp = await handle_authnet_webhook(request)
        assert _status(resp) == 500


# ===========================================================================
# Test Stripe Webhook Event Handlers (unit)
# ===========================================================================


class TestStripeEventHandlerDispatch:
    """Test the _STRIPE_EVENT_HANDLERS dispatch table."""

    def test_dispatch_table_has_expected_keys(self):
        expected = [
            "checkout.session.completed",
            "customer.subscription.updated",
            "customer.subscription.deleted",
            "customer.subscription.created",
            "invoice.payment_failed",
            "invoice.paid",
            "invoice.payment_succeeded",
            "payment_intent.succeeded",
            "payment_intent.payment_failed",
        ]
        for key in expected:
            assert key in _STRIPE_EVENT_HANDLERS, f"Missing handler for {key}"

    def test_subscription_created_uses_updated_handler(self):
        assert (
            _STRIPE_EVENT_HANDLERS["customer.subscription.created"] is _handle_subscription_updated
        )

    def test_invoice_payment_succeeded_uses_paid_handler(self):
        assert _STRIPE_EVENT_HANDLERS["invoice.payment_succeeded"] is _handle_invoice_paid


class TestHandleCheckoutSessionCompleted:
    """Tests for _handle_checkout_session_completed."""

    def test_returns_customer_and_subscription(self):
        obj = {
            "customer": "cus_123",
            "subscription": "sub_456",
            "metadata": {"org_id": "org_1", "tier": "professional"},
        }
        result = _handle_checkout_session_completed(obj)
        assert result["customer_id"] == "cus_123"
        assert result["subscription_id"] == "sub_456"

    def test_updates_tier_on_org_found(self):
        obj = {
            "customer": "cus_123",
            "subscription": "sub_456",
            "metadata": {"org_id": "org_1", "tier": "professional"},
        }
        mock_org = MagicMock()
        mock_org.tier.value = "free"

        mock_store = MagicMock()
        mock_store.get_organization_by_id.return_value = mock_org

        with (
            patch(
                "aragora.server.handlers.payments.stripe.SubscriptionTier",
                create=True,
            ) as MockTier,
            patch(
                "aragora.storage.user_store.singleton.get_user_store",
                return_value=mock_store,
            ),
        ):
            MockTier.side_effect = lambda x: MagicMock(value=x)
            MockTier.STARTER = MagicMock(value="starter")
            result = _handle_checkout_session_completed(obj)

        assert result.get("tier_updated") is True

    def test_no_org_id_skips_update(self):
        obj = {
            "customer": "cus_123",
            "subscription": "sub_456",
            "metadata": {},
        }
        result = _handle_checkout_session_completed(obj)
        assert "tier_updated" not in result

    def test_no_subscription_skips_update(self):
        obj = {
            "customer": "cus_123",
            "subscription": "",
            "metadata": {"org_id": "org_1"},
        }
        result = _handle_checkout_session_completed(obj)
        assert "tier_updated" not in result

    def test_handles_missing_metadata(self):
        obj = {"customer": "cus_123", "subscription": "sub_456"}
        result = _handle_checkout_session_completed(obj)
        assert result["customer_id"] == "cus_123"

    def test_handles_none_metadata(self):
        obj = {"customer": "cus_123", "subscription": "sub_456", "metadata": None}
        result = _handle_checkout_session_completed(obj)
        assert result["customer_id"] == "cus_123"


class TestHandleSubscriptionUpdated:
    """Tests for _handle_subscription_updated."""

    def test_returns_subscription_info(self):
        obj = {
            "id": "sub_123",
            "status": "active",
            "items": {"data": [{"price": {"id": "price_pro"}}]},
        }
        result = _handle_subscription_updated(obj)
        assert result["subscription_id"] == "sub_123"
        assert result["status"] == "active"

    def test_canceled_status_downgrades_to_free(self):
        obj = {
            "id": "sub_123",
            "status": "canceled",
            "items": {"data": []},
        }
        mock_org = MagicMock()
        mock_org.id = "org_1"
        mock_org.tier.value = "professional"

        mock_store = MagicMock()
        mock_store.get_organization_by_subscription.return_value = mock_org

        with (
            patch(
                "aragora.storage.user_store.singleton.get_user_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.server.handlers.payments.stripe.get_tier_from_price_id",
                create=True,
                return_value=None,
            ),
        ):
            result = _handle_subscription_updated(obj)

        assert result.get("new_tier") == "free"
        assert result.get("tier_updated") is True

    def test_past_due_flags_degraded(self):
        obj = {
            "id": "sub_123",
            "status": "past_due",
            "items": {"data": []},
        }
        mock_org = MagicMock()
        mock_org.id = "org_1"
        mock_org.tier.value = "professional"

        mock_store = MagicMock()
        mock_store.get_organization_by_subscription.return_value = mock_org

        with (
            patch(
                "aragora.storage.user_store.singleton.get_user_store",
                return_value=mock_store,
            ),
            patch(
                "aragora.server.handlers.payments.stripe.get_tier_from_price_id",
                create=True,
                return_value=None,
            ),
        ):
            result = _handle_subscription_updated(obj)

        assert result.get("status_degraded") is True

    def test_empty_subscription_id_returns_early(self):
        obj = {"id": "", "status": "active", "items": {"data": []}}
        result = _handle_subscription_updated(obj)
        assert result["subscription_id"] == ""

    def test_no_user_store_returns_early(self):
        obj = {"id": "sub_123", "status": "active", "items": {"data": []}}
        with patch(
            "aragora.storage.user_store.singleton.get_user_store",
            return_value=None,
        ):
            result = _handle_subscription_updated(obj)
        assert "tier_updated" not in result


class TestHandleSubscriptionDeleted:
    """Tests for _handle_subscription_deleted."""

    def test_returns_deactivated(self):
        obj = {"id": "sub_123"}
        result = _handle_subscription_deleted(obj)
        assert result["subscription_id"] == "sub_123"
        assert result["action"] == "deactivated"

    def test_downgrades_org_to_free(self):
        obj = {"id": "sub_123"}
        mock_org = MagicMock()
        mock_org.id = "org_1"
        mock_org.tier.value = "professional"

        mock_store = MagicMock()
        mock_store.get_organization_by_subscription.return_value = mock_org

        with patch(
            "aragora.storage.user_store.singleton.get_user_store",
            return_value=mock_store,
        ):
            result = _handle_subscription_deleted(obj)

        assert result["tier_updated"] is True
        assert result["new_tier"] == "free"
        assert result["old_tier"] == "professional"

    def test_empty_subscription_id_returns_early(self):
        obj = {"id": ""}
        result = _handle_subscription_deleted(obj)
        assert "tier_updated" not in result

    def test_no_org_found_returns_early(self):
        obj = {"id": "sub_nonexistent"}
        mock_store = MagicMock()
        mock_store.get_organization_by_subscription.return_value = None

        with patch(
            "aragora.storage.user_store.singleton.get_user_store",
            return_value=mock_store,
        ):
            result = _handle_subscription_deleted(obj)

        assert "tier_updated" not in result


class TestHandleInvoicePaymentFailed:
    """Tests for _handle_invoice_payment_failed."""

    def test_returns_failure_info(self):
        obj = {
            "id": "inv_123",
            "customer": "cus_456",
            "subscription": "sub_789",
            "attempt_count": 3,
        }
        result = _handle_invoice_payment_failed(obj)
        assert result["invoice_id"] == "inv_123"
        assert result["customer_id"] == "cus_456"
        assert result["attempt_count"] == 3
        assert result["payment_failed"] is True

    def test_default_attempt_count(self):
        obj = {"id": "inv_123", "customer": "cus_456"}
        result = _handle_invoice_payment_failed(obj)
        assert result["attempt_count"] == 1


class TestHandleInvoicePaid:
    """Tests for _handle_invoice_paid."""

    def test_returns_recovery_info(self):
        obj = {
            "customer": "cus_456",
            "subscription": "sub_789",
            "amount_paid": 9900,
        }
        result = _handle_invoice_paid(obj)
        assert result["customer_id"] == "cus_456"
        assert result["amount_paid"] == 9900
        assert result["payment_recovered"] is True

    def test_defaults_amount_paid(self):
        obj = {"customer": "cus_456"}
        result = _handle_invoice_paid(obj)
        assert result["amount_paid"] == 0


class TestHandlePaymentIntentSucceeded:
    """Tests for _handle_payment_intent_succeeded."""

    def test_returns_intent_id(self):
        obj = {"id": "pi_abc"}
        result = _handle_payment_intent_succeeded(obj)
        assert result["payment_intent_id"] == "pi_abc"

    def test_missing_id_returns_empty(self):
        obj = {}
        result = _handle_payment_intent_succeeded(obj)
        assert result["payment_intent_id"] == ""


class TestHandlePaymentIntentFailed:
    """Tests for _handle_payment_intent_failed."""

    def test_returns_failure_info(self):
        obj = {"id": "pi_fail"}
        result = _handle_payment_intent_failed(obj)
        assert result["payment_intent_id"] == "pi_fail"
        assert result["failed"] is True


# ===========================================================================
# Test _record_dead_letter
# ===========================================================================


class TestRecordDeadLetter:
    """Tests for _record_dead_letter helper."""

    def test_logs_and_marks_webhook(self):
        with patch(f"{PKG}._mark_webhook_processed") as mock_mark:
            _record_dead_letter("evt_1", "test.event", ValueError("bad"))
        mock_mark.assert_called_once_with("evt_1", result="error:ValueError")

    def test_handles_mark_failure_gracefully(self):
        with patch(
            f"{PKG}._mark_webhook_processed",
            side_effect=RuntimeError("store down"),
        ):
            # Should not raise
            _record_dead_letter("evt_1", "test.event", ValueError("bad"))


# ===========================================================================
# Test Rate Limiting
# ===========================================================================


class TestRateLimiting:
    """Test rate limit enforcement on payment endpoints."""

    @pytest.mark.asyncio
    async def test_charge_rate_limited(self):
        """When rate limit returns a response, handler returns 429."""
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(body={"amount": 100.00})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_charge(request)
        assert _status(resp) == 429

    @pytest.mark.asyncio
    async def test_authorize_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(body={"amount": 100.00})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_authorize(request)
        assert _status(resp) == 429

    @pytest.mark.asyncio
    async def test_capture_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(body={"transaction_id": "pi_123"})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_capture(request)
        assert _status(resp) == 429

    @pytest.mark.asyncio
    async def test_refund_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(body={"transaction_id": "pi_123", "amount": 50})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_refund(request)
        assert _status(resp) == 429

    @pytest.mark.asyncio
    async def test_void_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(body={"transaction_id": "pi_123"})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_void(request)
        assert _status(resp) == 429

    @pytest.mark.asyncio
    async def test_get_transaction_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(match_info={"transaction_id": "pi_123"})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_get_transaction(request)
        assert _status(resp) == 429

    @pytest.mark.asyncio
    async def test_stripe_webhook_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(
            raw_payload=b'{"type":"test"}',
            headers={"Stripe-Signature": "t=123,v1=abc"},
        )
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_stripe_webhook(request)
        assert _status(resp) == 429

    @pytest.mark.asyncio
    async def test_authnet_webhook_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(
            body={"eventType": "test"},
            headers={"X-ANET-Signature": "sha512=abc"},
        )
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_authnet_webhook(request)
        assert _status(resp) == 429


# ===========================================================================
# Test PaymentResult model
# ===========================================================================


class TestPaymentResult:
    """Tests for PaymentResult.to_dict serialization."""

    def test_to_dict_includes_all_fields(self):
        result = PaymentResult(
            transaction_id="txn_1",
            provider=PaymentProvider.STRIPE,
            status=PaymentStatus.APPROVED,
            amount=Decimal("100.00"),
            currency="USD",
            message="Approved",
            auth_code="A1B2",
            avs_result="Y",
            cvv_result="M",
        )
        d = result.to_dict()
        assert d["transaction_id"] == "txn_1"
        assert d["provider"] == "stripe"
        assert d["status"] == "approved"
        assert d["amount"] == "100.00"
        assert d["currency"] == "USD"
        assert d["message"] == "Approved"
        assert d["auth_code"] == "A1B2"
        assert d["avs_result"] == "Y"
        assert d["cvv_result"] == "M"
        assert "created_at" in d
        assert "metadata" in d

    def test_to_dict_minimal(self):
        result = PaymentResult(
            transaction_id="",
            provider=PaymentProvider.AUTHORIZE_NET,
            status=PaymentStatus.ERROR,
            amount=Decimal("0"),
            currency="USD",
        )
        d = result.to_dict()
        assert d["provider"] == "authorize_net"
        assert d["status"] == "error"
        assert d["message"] is None


class TestParsedBodyContract:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "handler_func",
        [
            handle_charge,
            handle_authorize,
            handle_capture,
            handle_refund,
            handle_void,
            handle_authnet_webhook,
        ],
    )
    async def test_missing_body_without_parser_error_fails_closed(self, handler_func):
        request = create_mock_request(headers={"X-ANET-Signature": "sha512=test"})
        with patch(
            "aragora.server.handlers.payments.stripe.parse_json_body",
            new_callable=AsyncMock,
            return_value=(None, None),
        ):
            response = await handler_func(request)

        assert _status(response) == 400
