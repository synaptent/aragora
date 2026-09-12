"""Tests for billing handler (aragora/server/handlers/payments/billing.py).

Comprehensive test suite covering all routes and behavior:
- POST /api/payments/customer — Create customer (Stripe + Authorize.net)
- GET  /api/payments/customer/{id} — Get customer (Stripe + Authorize.net)
- PUT  /api/payments/customer/{id} — Update customer (Stripe + Authorize.net)
- DELETE /api/payments/customer/{id} — Delete customer (Stripe + Authorize.net)
- POST /api/payments/subscription — Create subscription (Stripe + Authorize.net)
- GET  /api/payments/subscription/{id} — Get subscription (Stripe + Authorize.net)
- PUT  /api/payments/subscription/{id} — Update subscription (Stripe + Authorize.net)
- DELETE /api/payments/subscription/{id} — Cancel subscription (Stripe + Authorize.net)
- Error handling (ConnectionError, TimeoutError, ValueError, OSError patterns)
- Rate limiting
- Missing parameters / validation
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web

from aragora.server.handlers.payments.billing import (
    handle_cancel_subscription,
    handle_create_customer,
    handle_create_subscription,
    handle_delete_customer,
    handle_get_customer,
    handle_get_subscription,
    handle_update_customer,
    handle_update_subscription,
)
from aragora.server.handlers.payments.handler import PaymentProvider


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
class MockStripeCustomer:
    """Mock Stripe customer object."""

    id: str = "cus_test_123"
    email: str = "test@example.com"
    name: str = "Test User"
    created: int = 1700000000
    metadata: dict[str, Any] = field(default_factory=dict)
    deleted: bool = False


@dataclass
class MockDeletedCustomer:
    """Mock Stripe deleted customer response."""

    id: str = "cus_test_123"
    deleted: bool = True


@dataclass
class MockAuthnetProfile:
    """Mock Authorize.net customer profile."""

    profile_id: str = "profile_123"
    merchant_customer_id: str = "merchant_cust_abc"
    email: str = "test@example.com"
    description: str = "Test User"
    payment_profiles: list[Any] | None = None


@dataclass
class MockStripeSubscription:
    """Mock Stripe subscription object."""

    id: str = "sub_test_123"
    status: str = "active"
    current_period_start: int = 1700000000
    current_period_end: int = 1702592000
    customer: str = "cus_test_123"
    items: Any = None

    def __post_init__(self):
        if self.items is None:
            item = MagicMock()
            item.id = "si_test_123"
            item.price = MagicMock()
            item.price.id = "price_test_123"
            item.quantity = 1
            items_container = MagicMock()
            items_container.data = [item]
            self.items = items_container


@dataclass
class MockAuthnetSubscriptionStatus:
    """Mock Authorize.net subscription status enum."""

    value: str = "active"


@dataclass
class MockAuthnetSubscription:
    """Mock Authorize.net subscription object."""

    subscription_id: str = "sub_authnet_123"
    name: str = "Premium Plan"
    status: MockAuthnetSubscriptionStatus | None = None
    amount: Decimal | None = Decimal("99.99")

    def __post_init__(self):
        if self.status is None:
            self.status = MockAuthnetSubscriptionStatus()


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture
def mock_stripe_connector():
    """Create a mock Stripe connector with customer/subscription methods."""
    connector = AsyncMock()
    connector.create_customer = AsyncMock(return_value=MockStripeCustomer())
    connector.retrieve_customer = AsyncMock(return_value=MockStripeCustomer())
    connector.update_customer = AsyncMock(return_value=MockStripeCustomer())
    connector.delete_customer = AsyncMock(return_value=MockDeletedCustomer())
    connector.create_subscription = AsyncMock(return_value=MockStripeSubscription())
    connector.retrieve_subscription = AsyncMock(return_value=MockStripeSubscription())
    connector.update_subscription = AsyncMock(return_value=MockStripeSubscription())
    connector.cancel_subscription = AsyncMock(
        return_value=MockStripeSubscription(status="canceled")
    )
    return connector


@pytest.fixture
def mock_authnet_connector():
    """Create a mock Authorize.net connector with customer/subscription methods."""
    connector = AsyncMock()
    connector.create_customer_profile = AsyncMock(return_value=MockAuthnetProfile())
    connector.get_customer_profile = AsyncMock(return_value=MockAuthnetProfile())
    connector.update_customer_profile = AsyncMock(return_value=True)
    connector.delete_customer_profile = AsyncMock(return_value=True)
    connector.create_subscription = AsyncMock(return_value=MockAuthnetSubscription())
    connector.get_subscription = AsyncMock(return_value=MockAuthnetSubscription())
    connector.update_subscription = AsyncMock(return_value=True)
    connector.cancel_subscription = AsyncMock(return_value=True)
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
    )

    _payment_write_limiter._requests.clear()
    _payment_read_limiter._requests.clear()
    yield


@pytest.fixture(autouse=True)
def patch_rate_limit():
    """Disable rate limiting for all tests by default."""
    with patch(f"{PKG}._check_rate_limit", return_value=None):
        yield


# ===========================================================================
# Test handle_create_customer
# ===========================================================================


class TestCreateCustomer:
    """Tests for POST /api/payments/customer."""

    @pytest.mark.asyncio
    async def test_create_stripe_customer_success(self, mock_stripe_connector):
        request = create_mock_request(body={"email": "test@example.com", "name": "Test User"})
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_create_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["customer_id"] == "cus_test_123"
        assert data["email"] == "test@example.com"

    @pytest.mark.asyncio
    async def test_create_stripe_customer_with_metadata(self, mock_stripe_connector):
        request = create_mock_request(
            body={
                "email": "meta@example.com",
                "name": "Meta User",
                "metadata": {"tier": "premium"},
            }
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_create_customer(request)
        assert _status(resp) == 200
        mock_stripe_connector.create_customer.assert_called_once_with(
            email="meta@example.com",
            name="Meta User",
            metadata={"tier": "premium"},
        )

    @pytest.mark.asyncio
    async def test_create_authnet_customer_success(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "email": "auth@example.com",
                "name": "Auth User",
                "merchant_customer_id": "merch_123",
            }
        )
        with (
            patch(
                f"{PKG}.get_authnet_connector",
                return_value=mock_authnet_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_create_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["customer_id"] == "profile_123"
        assert data["merchant_customer_id"] == "merchant_cust_abc"

    @pytest.mark.asyncio
    async def test_create_authnet_customer_auto_merchant_id(self, mock_authnet_connector):
        """When merchant_customer_id is not provided, one is auto-generated."""
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "email": "auto@example.com",
                "name": "Auto ID User",
            }
        )
        with (
            patch(
                f"{PKG}.get_authnet_connector",
                return_value=mock_authnet_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_create_customer(request)
        assert _status(resp) == 200
        # Verify create_customer_profile was called with some merchant_customer_id
        call_kwargs = mock_authnet_connector.create_customer_profile.call_args
        assert call_kwargs.kwargs["merchant_customer_id"] is not None
        assert len(call_kwargs.kwargs["merchant_customer_id"]) > 0

    @pytest.mark.asyncio
    async def test_create_stripe_connector_unavailable(self):
        request = create_mock_request(body={"email": "test@example.com", "name": "Test"})
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_create_customer(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_create_authnet_connector_unavailable(self):
        request = create_mock_request(
            body={"provider": "authorize_net", "email": "x@y.com", "name": "X"}
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_create_customer(request)
        assert _status(resp) == 503
        data = _body(resp)
        assert "Authorize.net" in data["error"]

    @pytest.mark.asyncio
    async def test_create_customer_missing_body(self):
        request = create_mock_request()
        resp = await handle_create_customer(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_create_customer_connection_error(self, mock_stripe_connector):
        mock_stripe_connector.create_customer.side_effect = ConnectionError("timeout")
        request = create_mock_request(body={"email": "fail@example.com", "name": "Fail"})
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_create_customer(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_create_customer_value_error(self, mock_stripe_connector):
        mock_stripe_connector.create_customer.side_effect = ValueError("bad data")
        request = create_mock_request(body={"email": "bad@example.com", "name": "Bad"})
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_create_customer(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_create_customer_rate_limited(self):
        """When rate limit is active, returns 429."""
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(body={"email": "x@y.com", "name": "X"})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_create_customer(request)
        assert _status(resp) == 429


# ===========================================================================
# Test handle_get_customer
# ===========================================================================


class TestGetCustomer:
    """Tests for GET /api/payments/customer/{customer_id}."""

    @pytest.mark.asyncio
    async def test_get_stripe_customer_success(self, mock_stripe_connector):
        request = create_mock_request(
            match_info={"customer_id": "cus_test_123"},
            query={"provider": "stripe"},
        )
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_get_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["customer"]["id"] == "cus_test_123"
        assert data["customer"]["email"] == "test@example.com"
        assert data["customer"]["name"] == "Test User"

    @pytest.mark.asyncio
    async def test_get_stripe_customer_default_provider(self, mock_stripe_connector):
        """Default provider is 'stripe' when not specified in query."""
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_get_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["customer"]["id"] == "cus_test_123"

    @pytest.mark.asyncio
    async def test_get_authnet_customer_success(self, mock_authnet_connector):
        request = create_mock_request(
            match_info={"customer_id": "profile_123"},
            query={"provider": "authorize_net"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_get_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["customer"]["id"] == "profile_123"
        assert data["customer"]["email"] == "test@example.com"
        assert data["customer"]["payment_profiles"] == 0

    @pytest.mark.asyncio
    async def test_get_authnet_customer_with_payment_profiles(self, mock_authnet_connector):
        profile = MockAuthnetProfile(payment_profiles=["pp1", "pp2", "pp3"])
        mock_authnet_connector.get_customer_profile.return_value = profile
        request = create_mock_request(
            match_info={"customer_id": "profile_123"},
            query={"provider": "authnet"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_get_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["customer"]["payment_profiles"] == 3

    @pytest.mark.asyncio
    async def test_get_authnet_customer_not_found(self, mock_authnet_connector):
        mock_authnet_connector.get_customer_profile.return_value = None
        request = create_mock_request(
            match_info={"customer_id": "missing_123"},
            query={"provider": "authorize_net"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_get_customer(request)
        assert _status(resp) == 404

    @pytest.mark.asyncio
    async def test_get_customer_missing_id(self):
        request = create_mock_request(match_info={})
        resp = await handle_get_customer(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_get_stripe_connector_unavailable(self):
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        with patch(f"{PKG}.get_stripe_connector", return_value=None):
            resp = await handle_get_customer(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_get_authnet_connector_unavailable(self):
        request = create_mock_request(
            match_info={"customer_id": "profile_123"},
            query={"provider": "authorize_net"},
        )
        with patch(f"{PKG}.get_authnet_connector", return_value=None):
            resp = await handle_get_customer(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_get_customer_connection_error(self, mock_stripe_connector):
        mock_stripe_connector.retrieve_customer.side_effect = ConnectionError("timeout")
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_get_customer(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_get_customer_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_get_customer(request)
        assert _status(resp) == 429

    @pytest.mark.asyncio
    async def test_get_customer_key_error(self, mock_stripe_connector):
        mock_stripe_connector.retrieve_customer.side_effect = KeyError("no_such_field")
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_get_customer(request)
        assert _status(resp) == 500


# ===========================================================================
# Test handle_update_customer
# ===========================================================================


class TestUpdateCustomer:
    """Tests for PUT /api/payments/customer/{customer_id}."""

    @pytest.mark.asyncio
    async def test_update_stripe_customer_success(self, mock_stripe_connector):
        updated = MockStripeCustomer(email="updated@example.com", name="Updated User")
        mock_stripe_connector.update_customer.return_value = updated
        request = create_mock_request(
            body={"email": "updated@example.com", "name": "Updated User"},
            match_info={"customer_id": "cus_test_123"},
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["customer"]["email"] == "updated@example.com"

    @pytest.mark.asyncio
    async def test_update_stripe_customer_email_only(self, mock_stripe_connector):
        updated = MockStripeCustomer(email="newemail@example.com")
        mock_stripe_connector.update_customer.return_value = updated
        request = create_mock_request(
            body={"email": "newemail@example.com"},
            match_info={"customer_id": "cus_test_123"},
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_customer(request)
        assert _status(resp) == 200
        mock_stripe_connector.update_customer.assert_called_once_with(
            customer_id="cus_test_123", email="newemail@example.com"
        )

    @pytest.mark.asyncio
    async def test_update_stripe_customer_with_metadata(self, mock_stripe_connector):
        request = create_mock_request(
            body={"metadata": {"tier": "enterprise"}},
            match_info={"customer_id": "cus_test_123"},
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_customer(request)
        assert _status(resp) == 200
        mock_stripe_connector.update_customer.assert_called_once_with(
            customer_id="cus_test_123", metadata={"tier": "enterprise"}
        )

    @pytest.mark.asyncio
    async def test_update_stripe_customer_no_params(self, mock_stripe_connector):
        """If no email/name/metadata provided, returns 400."""
        request = create_mock_request(
            body={},
            match_info={"customer_id": "cus_test_123"},
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_customer(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_update_authnet_customer_success(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "email": "authnet@example.com",
                "name": "Updated AuthNet",
            },
            match_info={"customer_id": "profile_123"},
        )
        with (
            patch(
                f"{PKG}.get_authnet_connector",
                return_value=mock_authnet_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_update_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_update_customer_missing_id(self):
        request = create_mock_request(
            body={"email": "x@y.com"},
            match_info={},
        )
        resp = await handle_update_customer(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_update_customer_missing_body(self):
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        resp = await handle_update_customer(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_update_stripe_connector_unavailable(self):
        request = create_mock_request(
            body={"email": "x@y.com"},
            match_info={"customer_id": "cus_test_123"},
        )
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_customer(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_update_authnet_connector_unavailable(self):
        request = create_mock_request(
            body={"provider": "authorize_net", "email": "x@y.com"},
            match_info={"customer_id": "profile_123"},
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_update_customer(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_update_customer_timeout_error(self, mock_stripe_connector):
        mock_stripe_connector.update_customer.side_effect = TimeoutError("timed out")
        request = create_mock_request(
            body={"email": "fail@example.com"},
            match_info={"customer_id": "cus_test_123"},
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_customer(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_update_customer_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(
            body={"email": "x@y.com"},
            match_info={"customer_id": "cus_test_123"},
        )
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_update_customer(request)
        assert _status(resp) == 429


# ===========================================================================
# Test handle_delete_customer
# ===========================================================================


class TestDeleteCustomer:
    """Tests for DELETE /api/payments/customer/{customer_id}."""

    @pytest.mark.asyncio
    async def test_delete_stripe_customer_success(self, mock_stripe_connector):
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_delete_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_delete_stripe_customer_not_deleted(self, mock_stripe_connector):
        mock_stripe_connector.delete_customer.return_value = MockDeletedCustomer(deleted=False)
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_delete_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_delete_authnet_customer_success(self, mock_authnet_connector):
        request = create_mock_request(
            match_info={"customer_id": "profile_123"},
            query={"provider": "authorize_net"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_delete_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_delete_authnet_customer_failure(self, mock_authnet_connector):
        mock_authnet_connector.delete_customer_profile.return_value = False
        request = create_mock_request(
            match_info={"customer_id": "profile_123"},
            query={"provider": "authnet"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_delete_customer(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_delete_customer_missing_id(self):
        request = create_mock_request(match_info={})
        resp = await handle_delete_customer(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_delete_stripe_connector_unavailable(self):
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        with patch(f"{PKG}.get_stripe_connector", return_value=None):
            resp = await handle_delete_customer(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_delete_authnet_connector_unavailable(self):
        request = create_mock_request(
            match_info={"customer_id": "profile_123"},
            query={"provider": "authorize_net"},
        )
        with patch(f"{PKG}.get_authnet_connector", return_value=None):
            resp = await handle_delete_customer(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_delete_customer_os_error(self, mock_stripe_connector):
        mock_stripe_connector.delete_customer.side_effect = OSError("network error")
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_delete_customer(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_delete_customer_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(match_info={"customer_id": "cus_test_123"})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_delete_customer(request)
        assert _status(resp) == 429


# ===========================================================================
# Test handle_get_subscription
# ===========================================================================


class TestGetSubscription:
    """Tests for GET /api/payments/subscription/{subscription_id}."""

    @pytest.mark.asyncio
    async def test_get_stripe_subscription_success(self, mock_stripe_connector):
        request = create_mock_request(
            match_info={"subscription_id": "sub_test_123"},
            query={"provider": "stripe"},
        )
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        sub = data["subscription"]
        assert sub["id"] == "sub_test_123"
        assert sub["status"] == "active"
        assert sub["customer"] == "cus_test_123"

    @pytest.mark.asyncio
    async def test_get_stripe_subscription_with_items(self, mock_stripe_connector):
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert len(data["subscription"]["items"]) == 1
        assert data["subscription"]["items"][0]["price_id"] == "price_test_123"
        assert data["subscription"]["items"][0]["quantity"] == 1

    @pytest.mark.asyncio
    async def test_get_stripe_subscription_no_items(self, mock_stripe_connector):
        sub_no_items = MockStripeSubscription()
        sub_no_items.items = None
        mock_stripe_connector.retrieve_subscription.return_value = sub_no_items
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["subscription"]["items"] == []

    @pytest.mark.asyncio
    async def test_get_authnet_subscription_success(self, mock_authnet_connector):
        request = create_mock_request(
            match_info={"subscription_id": "sub_authnet_123"},
            query={"provider": "authorize_net"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        sub = data["subscription"]
        assert sub["id"] == "sub_authnet_123"
        assert sub["name"] == "Premium Plan"
        assert sub["status"] == "active"
        assert sub["amount"] == "99.99"

    @pytest.mark.asyncio
    async def test_get_authnet_subscription_not_found(self, mock_authnet_connector):
        mock_authnet_connector.get_subscription.return_value = None
        request = create_mock_request(
            match_info={"subscription_id": "missing"},
            query={"provider": "authnet"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 404

    @pytest.mark.asyncio
    async def test_get_authnet_subscription_null_status(self, mock_authnet_connector):
        sub = MockAuthnetSubscription()
        sub.status = None
        mock_authnet_connector.get_subscription.return_value = sub
        request = create_mock_request(
            match_info={"subscription_id": "sub_authnet_123"},
            query={"provider": "authorize_net"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["subscription"]["status"] == "unknown"

    @pytest.mark.asyncio
    async def test_get_authnet_subscription_null_amount(self, mock_authnet_connector):
        sub = MockAuthnetSubscription(amount=None)
        mock_authnet_connector.get_subscription.return_value = sub
        request = create_mock_request(
            match_info={"subscription_id": "sub_authnet_123"},
            query={"provider": "authorize_net"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["subscription"]["amount"] is None

    @pytest.mark.asyncio
    async def test_get_subscription_missing_id(self):
        request = create_mock_request(match_info={})
        resp = await handle_get_subscription(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_get_stripe_subscription_connector_unavailable(self):
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(f"{PKG}.get_stripe_connector", return_value=None):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_get_authnet_subscription_connector_unavailable(self):
        request = create_mock_request(
            match_info={"subscription_id": "sub_authnet_123"},
            query={"provider": "authorize_net"},
        )
        with patch(f"{PKG}.get_authnet_connector", return_value=None):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_get_subscription_timeout_error(self, mock_stripe_connector):
        mock_stripe_connector.retrieve_subscription.side_effect = TimeoutError("timed out")
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_get_subscription_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_get_subscription(request)
        assert _status(resp) == 429


# ===========================================================================
# Test handle_create_subscription
# ===========================================================================


class TestCreateSubscription:
    """Tests for POST /api/payments/subscription."""

    @pytest.mark.asyncio
    async def test_create_authnet_subscription_success(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "customer_id": "profile_123",
                "name": "Premium Plan",
                "amount": 99.99,
                "interval": "month",
                "interval_count": 1,
            }
        )
        with (
            patch(
                f"{PKG}.get_authnet_connector",
                return_value=mock_authnet_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["subscription_id"] == "sub_authnet_123"
        assert data["name"] == "Premium Plan"

    @pytest.mark.asyncio
    async def test_create_authnet_subscription_daily_interval(self, mock_authnet_connector):
        """Non-month intervals map to 'days' for Authorize.net."""
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "customer_id": "profile_123",
                "name": "Daily Plan",
                "amount": 1.99,
                "interval": "day",
                "interval_count": 7,
            }
        )
        with (
            patch(
                f"{PKG}.get_authnet_connector",
                return_value=mock_authnet_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 200
        call_kwargs = mock_authnet_connector.create_subscription.call_args
        assert call_kwargs.kwargs["interval_unit"] == "days"
        assert call_kwargs.kwargs["interval_length"] == 7

    @pytest.mark.asyncio
    async def test_create_stripe_subscription_success(self, mock_stripe_connector):
        request = create_mock_request(
            body={
                "customer_id": "cus_test_123",
                "amount": 49.99,
                "price_id": "price_test_456",
            }
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["subscription_id"] == "sub_test_123"
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_create_stripe_subscription_no_price_id(self, mock_stripe_connector):
        """Stripe requires price_id for subscription creation."""
        request = create_mock_request(
            body={
                "customer_id": "cus_test_123",
                "amount": 49.99,
            }
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 400
        data = _body(resp)
        assert "price_id" in data["error"]

    @pytest.mark.asyncio
    async def test_create_subscription_missing_customer_id(self):
        request = create_mock_request(body={"amount": 49.99, "price_id": "price_test_456"})
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_create_subscription_zero_amount(self):
        request = create_mock_request(
            body={
                "customer_id": "cus_test_123",
                "amount": 0,
                "price_id": "price_test_456",
            }
        )
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 400
        data = _body(resp)
        assert "Amount" in data["error"]

    @pytest.mark.asyncio
    async def test_create_subscription_negative_amount(self):
        request = create_mock_request(
            body={
                "customer_id": "cus_test_123",
                "amount": -10,
                "price_id": "price_test_456",
            }
        )
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_create_subscription_invalid_interval_count(self):
        request = create_mock_request(
            body={
                "customer_id": "cus_test_123",
                "amount": 10,
                "interval_count": "abc",
            }
        )
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 400
        data = _body(resp)
        assert "interval_count" in data["error"]

    @pytest.mark.asyncio
    async def test_create_subscription_interval_count_too_high(self):
        request = create_mock_request(
            body={
                "customer_id": "cus_test_123",
                "amount": 10,
                "interval_count": 121,
            }
        )
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 400
        data = _body(resp)
        assert "between 1 and 120" in data["error"]

    @pytest.mark.asyncio
    async def test_create_subscription_interval_count_zero(self):
        request = create_mock_request(
            body={
                "customer_id": "cus_test_123",
                "amount": 10,
                "interval_count": 0,
            }
        )
        with patch(
            f"{PKG}._get_provider_from_request",
            return_value=PaymentProvider.STRIPE,
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_create_subscription_missing_body(self):
        request = create_mock_request()
        resp = await handle_create_subscription(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_create_stripe_connector_unavailable(self):
        request = create_mock_request(
            body={
                "customer_id": "cus_test_123",
                "amount": 49.99,
                "price_id": "price_test_456",
            }
        )
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_create_authnet_connector_unavailable(self):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "customer_id": "profile_123",
                "name": "Plan",
                "amount": 10,
            }
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_create_subscription_connection_error(self, mock_stripe_connector):
        mock_stripe_connector.create_subscription.side_effect = ConnectionError("fail")
        request = create_mock_request(
            body={
                "customer_id": "cus_test_123",
                "amount": 49.99,
                "price_id": "price_test_456",
            }
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_create_subscription_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(
            body={
                "customer_id": "cus_test_123",
                "amount": 49.99,
                "price_id": "price_test_456",
            }
        )
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 429

    @pytest.mark.asyncio
    async def test_create_authnet_subscription_null_status(self, mock_authnet_connector):
        """When authnet subscription status is None, defaults to 'active'."""
        sub = MockAuthnetSubscription()
        sub.status = None
        mock_authnet_connector.create_subscription.return_value = sub
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "customer_id": "profile_123",
                "name": "Plan",
                "amount": 10,
            }
        )
        with (
            patch(
                f"{PKG}.get_authnet_connector",
                return_value=mock_authnet_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_create_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["status"] == "active"


# ===========================================================================
# Test handle_update_subscription
# ===========================================================================


class TestUpdateSubscription:
    """Tests for PUT /api/payments/subscription/{subscription_id}."""

    @pytest.mark.asyncio
    async def test_update_authnet_subscription_success(self, mock_authnet_connector):
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "name": "Updated Plan",
                "amount": 149.99,
            },
            match_info={"subscription_id": "sub_authnet_123"},
        )
        with (
            patch(
                f"{PKG}.get_authnet_connector",
                return_value=mock_authnet_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_update_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_update_authnet_subscription_amount_as_decimal(self, mock_authnet_connector):
        """Amount is converted to Decimal for Authorize.net."""
        request = create_mock_request(
            body={
                "provider": "authorize_net",
                "amount": 49.50,
            },
            match_info={"subscription_id": "sub_authnet_123"},
        )
        with (
            patch(
                f"{PKG}.get_authnet_connector",
                return_value=mock_authnet_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_update_subscription(request)
        assert _status(resp) == 200
        call_kwargs = mock_authnet_connector.update_subscription.call_args
        assert call_kwargs.kwargs["amount"] == Decimal("49.5")

    @pytest.mark.asyncio
    async def test_update_authnet_subscription_null_amount(self, mock_authnet_connector):
        """When amount not provided, passes None."""
        request = create_mock_request(
            body={"provider": "authorize_net", "name": "Updated"},
            match_info={"subscription_id": "sub_authnet_123"},
        )
        with (
            patch(
                f"{PKG}.get_authnet_connector",
                return_value=mock_authnet_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_update_subscription(request)
        assert _status(resp) == 200
        call_kwargs = mock_authnet_connector.update_subscription.call_args
        assert call_kwargs.kwargs["amount"] is None

    @pytest.mark.asyncio
    async def test_update_stripe_subscription_with_metadata(self, mock_stripe_connector):
        request = create_mock_request(
            body={"metadata": {"tier": "enterprise"}},
            match_info={"subscription_id": "sub_test_123"},
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["subscription"]["id"] == "sub_test_123"

    @pytest.mark.asyncio
    async def test_update_stripe_subscription_with_price_change(self, mock_stripe_connector):
        """Price change fetches current subscription to get item ID."""
        request = create_mock_request(
            body={"price_id": "price_new_789"},
            match_info={"subscription_id": "sub_test_123"},
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_subscription(request)
        assert _status(resp) == 200
        # Verify retrieve_subscription was called to get current items
        mock_stripe_connector.retrieve_subscription.assert_called_once_with("sub_test_123")
        # Verify update_subscription was called with items
        call_kwargs = mock_stripe_connector.update_subscription.call_args
        assert "items" in call_kwargs.kwargs

    @pytest.mark.asyncio
    async def test_update_stripe_subscription_no_params(self, mock_stripe_connector):
        """Empty body with no metadata/price_id returns 400."""
        request = create_mock_request(
            body={},
            match_info={"subscription_id": "sub_test_123"},
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_subscription(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_update_subscription_missing_id(self):
        request = create_mock_request(
            body={"metadata": {"k": "v"}},
            match_info={},
        )
        resp = await handle_update_subscription(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_update_subscription_missing_body(self):
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        resp = await handle_update_subscription(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_update_stripe_connector_unavailable(self):
        request = create_mock_request(
            body={"metadata": {"k": "v"}},
            match_info={"subscription_id": "sub_test_123"},
        )
        with (
            patch(f"{PKG}.get_stripe_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_subscription(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_update_authnet_connector_unavailable(self):
        request = create_mock_request(
            body={"provider": "authorize_net", "name": "X"},
            match_info={"subscription_id": "sub_authnet_123"},
        )
        with (
            patch(f"{PKG}.get_authnet_connector", return_value=None),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.AUTHORIZE_NET,
            ),
        ):
            resp = await handle_update_subscription(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_update_subscription_value_error(self, mock_stripe_connector):
        mock_stripe_connector.update_subscription.side_effect = ValueError("invalid")
        request = create_mock_request(
            body={"metadata": {"k": "v"}},
            match_info={"subscription_id": "sub_test_123"},
        )
        with (
            patch(
                f"{PKG}.get_stripe_connector",
                return_value=mock_stripe_connector,
            ),
            patch(
                f"{PKG}._get_provider_from_request",
                return_value=PaymentProvider.STRIPE,
            ),
        ):
            resp = await handle_update_subscription(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_update_subscription_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(
            body={"metadata": {"k": "v"}},
            match_info={"subscription_id": "sub_test_123"},
        )
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_update_subscription(request)
        assert _status(resp) == 429


# ===========================================================================
# Test handle_cancel_subscription
# ===========================================================================


class TestCancelSubscription:
    """Tests for DELETE /api/payments/subscription/{subscription_id}."""

    @pytest.mark.asyncio
    async def test_cancel_stripe_subscription_success(self, mock_stripe_connector):
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_cancel_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True
        assert data["subscription_id"] == "sub_test_123"
        assert data["status"] == "canceled"

    @pytest.mark.asyncio
    async def test_cancel_stripe_subscription_not_canceled(self, mock_stripe_connector):
        """If cancel returns a non-canceled status, success is False."""
        mock_stripe_connector.cancel_subscription.return_value = MockStripeSubscription(
            status="active"
        )
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_cancel_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is False
        assert data["status"] == "active"

    @pytest.mark.asyncio
    async def test_cancel_authnet_subscription_success(self, mock_authnet_connector):
        request = create_mock_request(
            match_info={"subscription_id": "sub_authnet_123"},
            query={"provider": "authorize_net"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_cancel_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_cancel_authnet_subscription_failure(self, mock_authnet_connector):
        mock_authnet_connector.cancel_subscription.return_value = False
        request = create_mock_request(
            match_info={"subscription_id": "sub_authnet_123"},
            query={"provider": "authnet"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_cancel_subscription(request)
        assert _status(resp) == 200
        data = _body(resp)
        assert data["success"] is False

    @pytest.mark.asyncio
    async def test_cancel_subscription_missing_id(self):
        request = create_mock_request(match_info={})
        resp = await handle_cancel_subscription(request)
        assert _status(resp) == 400

    @pytest.mark.asyncio
    async def test_cancel_stripe_connector_unavailable(self):
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(f"{PKG}.get_stripe_connector", return_value=None):
            resp = await handle_cancel_subscription(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_cancel_authnet_connector_unavailable(self):
        request = create_mock_request(
            match_info={"subscription_id": "sub_authnet_123"},
            query={"provider": "authorize_net"},
        )
        with patch(f"{PKG}.get_authnet_connector", return_value=None):
            resp = await handle_cancel_subscription(request)
        assert _status(resp) == 503

    @pytest.mark.asyncio
    async def test_cancel_subscription_connection_error(self, mock_stripe_connector):
        mock_stripe_connector.cancel_subscription.side_effect = ConnectionError("fail")
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_cancel_subscription(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_cancel_subscription_os_error(self, mock_stripe_connector):
        mock_stripe_connector.cancel_subscription.side_effect = OSError("network")
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_cancel_subscription(request)
        assert _status(resp) == 500

    @pytest.mark.asyncio
    async def test_cancel_subscription_rate_limited(self):
        rate_resp = web.json_response({"error": "Rate limit exceeded"}, status=429)
        request = create_mock_request(match_info={"subscription_id": "sub_test_123"})
        with patch(f"{PKG}._check_rate_limit", return_value=rate_resp):
            resp = await handle_cancel_subscription(request)
        assert _status(resp) == 429


# ===========================================================================
# Cross-cutting concerns
# ===========================================================================


class TestProviderRouting:
    """Tests for provider detection via query parameter."""

    @pytest.mark.asyncio
    async def test_authnet_keyword_triggers_authnet_path(self, mock_authnet_connector):
        """'authnet' alias routes to Authorize.net path."""
        request = create_mock_request(
            match_info={"customer_id": "profile_123"},
            query={"provider": "authnet"},
        )
        with patch(
            f"{PKG}.get_authnet_connector",
            return_value=mock_authnet_connector,
        ):
            resp = await handle_get_customer(request)
        assert _status(resp) == 200
        # Verify authnet connector was used
        mock_authnet_connector.get_customer_profile.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_provider_defaults_to_stripe(self, mock_stripe_connector):
        """Unknown provider strings fall through to Stripe."""
        request = create_mock_request(
            match_info={"customer_id": "cus_test_123"},
            query={"provider": "paypal"},
        )
        with patch(
            f"{PKG}.get_stripe_connector",
            return_value=mock_stripe_connector,
        ):
            resp = await handle_get_customer(request)
        assert _status(resp) == 200
        mock_stripe_connector.retrieve_customer.assert_called_once()


class TestCoerceRequest:
    """Tests for the _coerce_request helper."""

    @pytest.mark.asyncio
    async def test_coerce_with_two_args_returns_second(self):
        """When maybe_request is passed, returns it (legacy signature)."""
        from aragora.server.handlers.payments.billing import _coerce_request

        mock1 = MagicMock()
        mock2 = MagicMock()
        result = _coerce_request(mock1, mock2)
        assert result is mock2

    @pytest.mark.asyncio
    async def test_coerce_with_one_arg_returns_first(self):
        """When maybe_request is None, returns first arg."""
        from aragora.server.handlers.payments.billing import _coerce_request

        mock1 = MagicMock()
        result = _coerce_request(mock1, None)
        assert result is mock1

    @pytest.mark.asyncio
    async def test_coerce_default_returns_first(self):
        """Default call with single arg returns first."""
        from aragora.server.handlers.payments.billing import _coerce_request

        mock1 = MagicMock()
        result = _coerce_request(mock1)
        assert result is mock1


class TestParsedBodyContract:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("handler_func", "match_info"),
        [
            (handle_create_customer, None),
            (handle_update_customer, {"customer_id": "cus_test_123"}),
            (handle_update_subscription, {"subscription_id": "sub_test_123"}),
            (handle_create_subscription, None),
        ],
    )
    async def test_missing_body_without_parser_error_fails_closed(
        self,
        handler_func,
        match_info,
    ):
        request = create_mock_request(match_info=match_info)
        with patch(
            "aragora.server.handlers.payments.billing.parse_json_body",
            new_callable=AsyncMock,
            return_value=(None, None),
        ):
            response = await handler_func(request)

        assert _status(response) == 400
