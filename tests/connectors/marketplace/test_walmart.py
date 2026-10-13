"""
Comprehensive Tests for Walmart Marketplace Connector.

Tests for the Walmart Seller Center integration including:
- Authentication and API key management
- Product listing operations (create, update, delete)
- Inventory management
- Order retrieval and processing
- Pricing updates
- Feed submission and status tracking
- Error handling and retry logic
"""

import pytest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import httpx

from aragora.connectors.marketplace.walmart import (
    WalmartConnector,
    WalmartCredentials,
    WalmartAddress,
    WalmartOrder,
    WalmartItem,
    WalmartReturn,
    WalmartError,
    OrderLine,
    InventoryItem,
    FeedStatus,
    OrderStatus,
    ItemPublishStatus,
    LifecycleStatus,
    FulfillmentType,
    ReturnStatus,
    get_mock_order,
    get_mock_item,
    _parse_datetime,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def credentials():
    """Create test credentials."""
    return WalmartCredentials(
        client_id="test_client_id",
        client_secret="test_client_secret",
        environment="sandbox",
    )


@pytest.fixture
def production_credentials():
    """Create production credentials."""
    return WalmartCredentials(
        client_id="prod_client_id",
        client_secret="prod_client_secret",
        environment="production",
    )


@pytest.fixture
def connector(credentials):
    """Create a test connector instance."""
    return WalmartConnector(credentials)


@pytest.fixture
def authenticated_connector(credentials):
    """Create an authenticated connector with mocked token."""
    connector = WalmartConnector(credentials)
    connector._access_token = "test_access_token"
    connector._token_expires_at = datetime.now() + timedelta(minutes=10)
    return connector


@pytest.fixture
def mock_order_response():
    """Mock API response for a single order."""
    return {
        "purchaseOrderId": "2024010112345",
        "customerOrderId": "ABC12345",
        "orderDate": "2024-01-15T10:30:00Z",
        "orderStatus": "Acknowledged",
        "shipByDate": "2024-01-18T23:59:59Z",
        "deliverByDate": "2024-01-22T23:59:59Z",
        "shippingInfo": {
            "postalAddress": {
                "name": "John Doe",
                "address1": "123 Main St",
                "address2": "Apt 4B",
                "city": "Bentonville",
                "state": "AR",
                "postalCode": "72712",
                "country": "USA",
                "phone": "555-123-4567",
            }
        },
        "orderLines": {
            "orderLine": [
                {
                    "lineNumber": "1",
                    "item": {
                        "productId": "12345678",
                        "sku": "TEST-SKU-001",
                        "productName": "Test Product",
                    },
                    "orderLineQuantity": {"amount": "2"},
                    "charges": {
                        "charge": [
                            {
                                "chargeType": "PRODUCT",
                                "chargeAmount": {"amount": "29.99"},
                            }
                        ]
                    },
                    "orderLineStatuses": {
                        "orderLineStatus": [
                            {
                                "status": "Acknowledged",
                                "trackingInfo": {
                                    "trackingNumber": "1Z999AA10123456784",
                                    "carrierName": {"carrier": "UPS"},
                                },
                            }
                        ]
                    },
                    "fulfillment": {"fulfillmentOption": "SELLER"},
                }
            ]
        },
    }


@pytest.fixture
def mock_orders_list_response(mock_order_response):
    """Mock API response for orders list."""
    return {
        "list": {
            "elements": {"order": [mock_order_response]},
            "meta": {"nextCursor": "cursor_abc123"},
        }
    }


@pytest.fixture
def mock_item_response():
    """Mock API response for an item."""
    return {
        "itemId": "12345678",
        "wpid": "12345678",
        "sku": "TEST-SKU-001",
        "productName": "Test Product",
        "brand": "Test Brand",
        "price": {"amount": "29.99"},
        "publishedStatus": "PUBLISHED",
        "lifecycleStatus": "ACTIVE",
        "upc": "012345678901",
        "gtin": "00012345678901",
        "productImageUrl": "https://example.com/image.jpg",
        "productType": "Electronics",
        "shelf": ["Electronics", "Accessories"],
    }


@pytest.fixture
def mock_inventory_response():
    """Mock API response for inventory."""
    return {
        "sku": "TEST-SKU-001",
        "quantity": {"amount": 100},
        "fulfillmentLagTime": 1,
        "shipNode": "node_123",
        "lastUpdatedDate": "2024-01-15T10:00:00Z",
    }


@pytest.fixture
def mock_feed_status_response():
    """Mock API response for feed status."""
    return {
        "feedId": "feed_abc123",
        "feedType": "inventory",
        "feedStatus": "PROCESSED",
        "itemsReceived": 100,
        "itemsSucceeded": 98,
        "itemsFailed": 2,
        "feedDate": "2024-01-15T10:00:00Z",
    }


@pytest.fixture
def mock_return_response():
    """Mock API response for a return."""
    return {
        "returnOrderId": "RET12345",
        "customerOrderId": "ABC12345",
        "returnDate": "2024-01-20T14:30:00Z",
        "returnStatus": "INITIATED",
        "returnLines": [{"lineNumber": "1", "quantity": 1, "reason": "Customer return"}],
        "refundAmount": {"amount": "29.99"},
    }


# =============================================================================
# Credentials Tests
# =============================================================================


class TestWalmartCredentials:
    """Tests for WalmartCredentials dataclass."""

    def test_default_environment(self):
        """Should default to production environment."""
        creds = WalmartCredentials(
            client_id="test_id",
            client_secret="test_secret",
        )
        assert creds.environment == "production"

    def test_sandbox_base_url(self, credentials):
        """Should return sandbox URL for sandbox environment."""
        assert credentials.base_url == "https://sandbox.walmartapis.com"

    def test_production_base_url(self, production_credentials):
        """Should return production URL for production environment."""
        assert production_credentials.base_url == "https://marketplace.walmartapis.com"

    def test_credentials_attributes(self, credentials):
        """Should have correct attributes."""
        assert credentials.client_id == "test_client_id"
        assert credentials.client_secret == "test_client_secret"
        assert credentials.environment == "sandbox"


# =============================================================================
# Enum Tests
# =============================================================================


class TestEnums:
    """Tests for Walmart-specific enums."""

    def test_order_status_values(self):
        """Should have correct order status values."""
        assert OrderStatus.CREATED.value == "Created"
        assert OrderStatus.ACKNOWLEDGED.value == "Acknowledged"
        assert OrderStatus.SHIPPED.value == "Shipped"
        assert OrderStatus.DELIVERED.value == "Delivered"
        assert OrderStatus.CANCELLED.value == "Cancelled"
        assert OrderStatus.REFUND.value == "Refund"

    def test_item_publish_status_values(self):
        """Should have correct item publish status values."""
        assert ItemPublishStatus.PUBLISHED.value == "PUBLISHED"
        assert ItemPublishStatus.UNPUBLISHED.value == "UNPUBLISHED"
        assert ItemPublishStatus.STAGE.value == "STAGE"
        assert ItemPublishStatus.IN_PROGRESS.value == "IN_PROGRESS"
        assert ItemPublishStatus.SYSTEM_PROBLEM.value == "SYSTEM_PROBLEM"

    def test_lifecycle_status_values(self):
        """Should have correct lifecycle status values."""
        assert LifecycleStatus.ACTIVE.value == "ACTIVE"
        assert LifecycleStatus.ARCHIVED.value == "ARCHIVED"
        assert LifecycleStatus.RETIRED.value == "RETIRED"

    def test_fulfillment_type_values(self):
        """Should have correct fulfillment type values."""
        assert FulfillmentType.SELLER.value == "SELLER"
        assert FulfillmentType.WFS.value == "WFS"

    def test_return_status_values(self):
        """Should have correct return status values."""
        assert ReturnStatus.INITIATED.value == "INITIATED"
        assert ReturnStatus.IN_TRANSIT.value == "IN_TRANSIT"
        assert ReturnStatus.RECEIVED.value == "RECEIVED"
        assert ReturnStatus.COMPLETED.value == "COMPLETED"
        assert ReturnStatus.CANCELLED.value == "CANCELLED"


# =============================================================================
# Dataclass Tests
# =============================================================================


class TestWalmartAddress:
    """Tests for WalmartAddress dataclass."""

    def test_address_creation(self):
        """Should create address with all fields."""
        addr = WalmartAddress(
            name="John Doe",
            address1="123 Main St",
            address2="Apt 4B",
            city="Bentonville",
            state="AR",
            postal_code="72712",
            country="USA",
            phone="555-123-4567",
        )
        assert addr.name == "John Doe"
        assert addr.address1 == "123 Main St"
        assert addr.address2 == "Apt 4B"
        assert addr.city == "Bentonville"
        assert addr.state == "AR"
        assert addr.postal_code == "72712"
        assert addr.country == "USA"
        assert addr.phone == "555-123-4567"

    def test_address_default_country(self):
        """Should default country to USA."""
        addr = WalmartAddress(
            name="John Doe",
            address1="123 Main St",
            city="Bentonville",
            state="AR",
            postal_code="72712",
        )
        assert addr.country == "USA"

    def test_address_from_api(self):
        """Should parse address from API response."""
        data = {
            "name": "Jane Smith",
            "address1": "456 Oak Ave",
            "address2": "Suite 100",
            "city": "Rogers",
            "state": "AR",
            "postalCode": "72756",
            "country": "USA",
            "phone": "555-987-6543",
        }
        addr = WalmartAddress.from_api(data)
        assert addr.name == "Jane Smith"
        assert addr.address1 == "456 Oak Ave"
        assert addr.postal_code == "72756"
        assert addr.phone == "555-987-6543"

    def test_address_from_api_missing_fields(self):
        """Should handle missing fields in API response."""
        data = {"name": "John Doe", "city": "Bentonville"}
        addr = WalmartAddress.from_api(data)
        assert addr.name == "John Doe"
        assert addr.address1 == ""
        assert addr.city == "Bentonville"
        assert addr.phone is None


class TestOrderLine:
    """Tests for OrderLine dataclass."""

    def test_order_line_creation(self):
        """Should create order line with all fields."""
        line = OrderLine(
            line_number="1",
            item_id="12345678",
            sku="TEST-SKU-001",
            product_name="Test Product",
            quantity=2,
            unit_price=Decimal("29.99"),
            total_price=Decimal("59.98"),
            status="Acknowledged",
            fulfillment_type=FulfillmentType.SELLER,
            tracking_number="1Z999AA10123456784",
            carrier="UPS",
        )
        assert line.line_number == "1"
        assert line.quantity == 2
        assert line.total_price == Decimal("59.98")
        assert line.tracking_number == "1Z999AA10123456784"

    def test_order_line_from_api(self, mock_order_response):
        """Should parse order line from API response."""
        line_data = mock_order_response["orderLines"]["orderLine"][0]
        line = OrderLine.from_api(line_data)
        assert line.line_number == "1"
        assert line.item_id == "12345678"
        assert line.sku == "TEST-SKU-001"
        assert line.product_name == "Test Product"
        assert line.quantity == 2
        assert line.unit_price == Decimal("29.99")
        assert line.fulfillment_type == FulfillmentType.SELLER

    def test_order_line_from_api_empty_charges(self):
        """Should handle empty charges in API response."""
        data = {
            "lineNumber": "1",
            "item": {"productId": "123", "sku": "SKU", "productName": "Product"},
            "orderLineQuantity": {"amount": "1"},
            "charges": {"charge": []},
            "orderLineStatuses": {"orderLineStatus": [{"status": "Created"}]},
            "fulfillment": {"fulfillmentOption": "SELLER"},
        }
        line = OrderLine.from_api(data)
        assert line.unit_price == Decimal("0")


class TestWalmartOrder:
    """Tests for WalmartOrder dataclass."""

    def test_order_creation(self):
        """Should create order with all fields."""
        order = WalmartOrder(
            purchase_order_id="2024010112345",
            customer_order_id="ABC12345",
            order_date=datetime.now(),
            status=OrderStatus.ACKNOWLEDGED,
            shipping_address=WalmartAddress(
                name="John Doe",
                address1="123 Main St",
                city="Bentonville",
                state="AR",
                postal_code="72712",
            ),
            order_lines=[],
            total_amount=Decimal("59.98"),
        )
        assert order.purchase_order_id == "2024010112345"
        assert order.status == OrderStatus.ACKNOWLEDGED
        assert order.total_amount == Decimal("59.98")

    def test_order_from_api(self, mock_order_response):
        """Should parse order from API response."""
        order = WalmartOrder.from_api(mock_order_response)
        assert order.purchase_order_id == "2024010112345"
        assert order.customer_order_id == "ABC12345"
        assert order.status == OrderStatus.ACKNOWLEDGED
        assert len(order.order_lines) == 1
        assert order.total_amount == Decimal("59.98")
        assert order.shipping_address.name == "John Doe"

    def test_order_from_api_calculates_total(self):
        """Should calculate total from order lines."""
        data = {
            "purchaseOrderId": "123",
            "customerOrderId": "ABC",
            "orderDate": "2024-01-15T10:00:00Z",
            "orderStatus": "Created",
            "shippingInfo": {"postalAddress": {"name": "Test", "city": "Test"}},
            "orderLines": {
                "orderLine": [
                    {
                        "lineNumber": "1",
                        "item": {"productId": "1", "sku": "SKU1", "productName": "P1"},
                        "orderLineQuantity": {"amount": "2"},
                        "charges": {
                            "charge": [
                                {"chargeType": "PRODUCT", "chargeAmount": {"amount": "10.00"}}
                            ]
                        },
                        "orderLineStatuses": {"orderLineStatus": [{"status": "Created"}]},
                        "fulfillment": {"fulfillmentOption": "SELLER"},
                    },
                    {
                        "lineNumber": "2",
                        "item": {"productId": "2", "sku": "SKU2", "productName": "P2"},
                        "orderLineQuantity": {"amount": "1"},
                        "charges": {
                            "charge": [
                                {"chargeType": "PRODUCT", "chargeAmount": {"amount": "25.00"}}
                            ]
                        },
                        "orderLineStatuses": {"orderLineStatus": [{"status": "Created"}]},
                        "fulfillment": {"fulfillmentOption": "SELLER"},
                    },
                ]
            },
        }
        order = WalmartOrder.from_api(data)
        # 2 * $10 + 1 * $25 = $45
        assert order.total_amount == Decimal("45.00")


class TestWalmartItem:
    """Tests for WalmartItem dataclass."""

    def test_item_creation(self):
        """Should create item with all fields."""
        item = WalmartItem(
            item_id="12345678",
            sku="TEST-SKU-001",
            product_name="Test Product",
            brand="Test Brand",
            price=Decimal("29.99"),
            publish_status=ItemPublishStatus.PUBLISHED,
            lifecycle_status=LifecycleStatus.ACTIVE,
            upc="012345678901",
            gtin="00012345678901",
            image_url="https://example.com/image.jpg",
            product_type="Electronics",
            shelf=["Electronics", "Accessories"],
        )
        assert item.item_id == "12345678"
        assert item.sku == "TEST-SKU-001"
        assert item.price == Decimal("29.99")
        assert item.publish_status == ItemPublishStatus.PUBLISHED

    def test_item_from_api(self, mock_item_response):
        """Should parse item from API response."""
        item = WalmartItem.from_api(mock_item_response)
        assert item.item_id == "12345678"
        assert item.sku == "TEST-SKU-001"
        assert item.brand == "Test Brand"
        assert item.price == Decimal("29.99")
        assert item.publish_status == ItemPublishStatus.PUBLISHED
        assert item.lifecycle_status == LifecycleStatus.ACTIVE
        assert item.upc == "012345678901"

    def test_item_from_api_uses_wpid_fallback(self):
        """Should use wpid when itemId not present."""
        data = {
            "wpid": "WPID123",
            "sku": "SKU",
            "productName": "Product",
            "brand": "Brand",
            "price": {"amount": "19.99"},
            "publishedStatus": "UNPUBLISHED",
            "lifecycleStatus": "ACTIVE",
        }
        item = WalmartItem.from_api(data)
        assert item.item_id == "WPID123"


class TestInventoryItem:
    """Tests for InventoryItem dataclass."""

    def test_inventory_creation(self):
        """Should create inventory item with all fields."""
        item = InventoryItem(
            sku="TEST-SKU-001",
            quantity=100,
            fulfillment_lag_time=1,
            ship_node="node_123",
            last_updated=datetime.now(),
        )
        assert item.sku == "TEST-SKU-001"
        assert item.quantity == 100
        assert item.fulfillment_lag_time == 1

    def test_inventory_from_api(self, mock_inventory_response):
        """Should parse inventory from API response."""
        item = InventoryItem.from_api(mock_inventory_response)
        assert item.sku == "TEST-SKU-001"
        assert item.quantity == 100
        assert item.fulfillment_lag_time == 1
        assert item.ship_node == "node_123"
        assert item.last_updated is not None


class TestWalmartReturn:
    """Tests for WalmartReturn dataclass."""

    def test_return_creation(self):
        """Should create return with all fields."""
        ret = WalmartReturn(
            return_order_id="RET12345",
            customer_order_id="ABC12345",
            return_date=datetime.now(),
            status=ReturnStatus.INITIATED,
            return_lines=[{"lineNumber": "1", "quantity": 1}],
            refund_amount=Decimal("29.99"),
        )
        assert ret.return_order_id == "RET12345"
        assert ret.status == ReturnStatus.INITIATED
        assert ret.refund_amount == Decimal("29.99")

    def test_return_from_api(self, mock_return_response):
        """Should parse return from API response."""
        ret = WalmartReturn.from_api(mock_return_response)
        assert ret.return_order_id == "RET12345"
        assert ret.customer_order_id == "ABC12345"
        assert ret.status == ReturnStatus.INITIATED
        assert ret.refund_amount == Decimal("29.99")
        assert len(ret.return_lines) == 1


class TestFeedStatus:
    """Tests for FeedStatus dataclass."""

    def test_feed_status_creation(self):
        """Should create feed status with all fields."""
        status = FeedStatus(
            feed_id="feed_abc123",
            feed_type="inventory",
            status="PROCESSED",
            items_received=100,
            items_succeeded=98,
            items_failed=2,
            submitted_at=datetime.now(),
        )
        assert status.feed_id == "feed_abc123"
        assert status.feed_type == "inventory"
        assert status.items_succeeded == 98
        assert status.items_failed == 2

    def test_feed_status_from_api(self, mock_feed_status_response):
        """Should parse feed status from API response."""
        status = FeedStatus.from_api(mock_feed_status_response)
        assert status.feed_id == "feed_abc123"
        assert status.feed_type == "inventory"
        assert status.status == "PROCESSED"
        assert status.items_received == 100
        assert status.items_succeeded == 98
        assert status.items_failed == 2


# =============================================================================
# Authentication Tests
# =============================================================================


class TestAuthentication:
    """Tests for authentication and token management."""

    @pytest.mark.asyncio
    async def test_get_client_creates_client(self, connector):
        """Should create HTTP client on first call."""
        assert connector._client is None
        client = await connector._get_client()
        assert client is not None
        assert isinstance(client, httpx.AsyncClient)
        await connector.close()

    @pytest.mark.asyncio
    async def test_get_client_reuses_client(self, connector):
        """Should reuse existing HTTP client."""
        client1 = await connector._get_client()
        client2 = await connector._get_client()
        assert client1 is client2
        await connector.close()

    @pytest.mark.asyncio
    async def test_ensure_token_fresh_token(self, authenticated_connector):
        """Should return existing token if still valid."""
        token = await authenticated_connector._ensure_token()
        assert token == "test_access_token"

    @pytest.mark.asyncio
    async def test_ensure_token_refreshes_expired(self, connector):
        """Should refresh token when expired."""
        connector._access_token = "old_token"
        connector._token_expires_at = datetime.now() - timedelta(minutes=1)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_access_token",
            "expires_in": 900,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            token = await connector._ensure_token()

            assert token == "new_access_token"
            mock_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_token_initial_auth(self, connector):
        """Should obtain token on initial auth."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "initial_token",
            "expires_in": 900,
        }
        mock_response.raise_for_status = MagicMock()

        with patch.object(connector, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            token = await connector._ensure_token()

            assert token == "initial_token"
            assert connector._access_token == "initial_token"
            assert connector._token_expires_at is not None

    def test_get_headers(self, authenticated_connector):
        """Should return correct request headers."""
        headers = authenticated_connector._get_headers("test_token")
        assert headers["Authorization"] == "Bearer test_token"
        assert headers["Accept"] == "application/json"
        assert headers["Content-Type"] == "application/json"
        assert headers["WM_SVC.NAME"] == "Walmart Marketplace"
        assert "WM_QOS.CORRELATION_ID" in headers


# =============================================================================
# Request Tests
# =============================================================================


class TestRequest:
    """Tests for the _request method."""

    @pytest.mark.asyncio
    async def test_request_success(self, authenticated_connector):
        """Should make successful authenticated request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "test"}

        with patch.object(authenticated_connector, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await authenticated_connector._request("GET", "/v3/orders")

            assert result == {"data": "test"}
            mock_client.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_request_204_no_content(self, authenticated_connector):
        """Should handle 204 No Content response."""
        mock_response = MagicMock()
        mock_response.status_code = 204

        with patch.object(authenticated_connector, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            result = await authenticated_connector._request("POST", "/v3/orders/123/acknowledge")

            assert result == {}

    @pytest.mark.asyncio
    async def test_request_error_with_json(self, authenticated_connector):
        """Should raise WalmartError with API error details."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "errors": [
                {
                    "code": "INVALID_REQUEST",
                    "description": "Invalid order ID",
                }
            ]
        }
        mock_response.text = "Bad Request"

        with patch.object(authenticated_connector, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            with pytest.raises(WalmartError) as exc_info:
                await authenticated_connector._request("GET", "/v3/orders/invalid")

            assert "Invalid order ID" in str(exc_info.value)
            assert exc_info.value.code == "INVALID_REQUEST"

    @pytest.mark.asyncio
    async def test_request_error_without_json(self, authenticated_connector):
        """Should handle error response without JSON body."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.text = "Internal Server Error"

        with patch.object(authenticated_connector, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            with pytest.raises(WalmartError) as exc_info:
                await authenticated_connector._request("GET", "/v3/orders")

            assert "HTTP 500" in str(exc_info.value)


# =============================================================================
# Order Tests
# =============================================================================


class TestOrders:
    """Tests for order operations."""

    @pytest.mark.asyncio
    async def test_get_orders_success(self, authenticated_connector, mock_orders_list_response):
        """Should retrieve orders successfully."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = mock_orders_list_response

            orders, next_cursor = await authenticated_connector.get_orders()

            assert len(orders) == 1
            assert orders[0].purchase_order_id == "2024010112345"
            assert next_cursor == "cursor_abc123"
            mock_request.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_orders_with_filters(
        self, authenticated_connector, mock_orders_list_response
    ):
        """Should apply filters to order query."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = mock_orders_list_response

            start_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
            end_date = datetime(2024, 1, 31, tzinfo=timezone.utc)

            await authenticated_connector.get_orders(
                status=OrderStatus.ACKNOWLEDGED,
                created_start_date=start_date,
                created_end_date=end_date,
                limit=50,
            )

            call_args = mock_request.call_args
            params = call_args[1]["params"]
            assert params["status"] == "Acknowledged"
            assert "createdStartDate" in params
            assert "createdEndDate" in params
            assert params["limit"] == 50

    @pytest.mark.asyncio
    async def test_get_orders_with_cursor(self, authenticated_connector, mock_orders_list_response):
        """Should pass cursor for pagination."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = mock_orders_list_response

            await authenticated_connector.get_orders(cursor="previous_cursor")

            call_args = mock_request.call_args
            params = call_args[1]["params"]
            assert params["nextCursor"] == "previous_cursor"

    @pytest.mark.asyncio
    async def test_get_orders_limit_capped(
        self, authenticated_connector, mock_orders_list_response
    ):
        """Should cap limit to 200."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = mock_orders_list_response

            await authenticated_connector.get_orders(limit=500)

            call_args = mock_request.call_args
            params = call_args[1]["params"]
            assert params["limit"] == 200

    @pytest.mark.asyncio
    async def test_get_order_success(self, authenticated_connector, mock_order_response):
        """Should retrieve single order successfully."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"order": mock_order_response}

            order = await authenticated_connector.get_order("2024010112345")

            assert order.purchase_order_id == "2024010112345"
            mock_request.assert_called_with("GET", "/v3/orders/2024010112345")

    @pytest.mark.asyncio
    async def test_acknowledge_order(self, authenticated_connector):
        """Should acknowledge order successfully."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {}

            result = await authenticated_connector.acknowledge_order("2024010112345")

            assert result is True
            mock_request.assert_called_with("POST", "/v3/orders/2024010112345/acknowledge")

    @pytest.mark.asyncio
    async def test_ship_order_lines(self, authenticated_connector):
        """Should ship order lines with tracking."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {}

            line_shipments = [
                {
                    "line_number": "1",
                    "carrier": "UPS",
                    "tracking_number": "1Z999AA10123456784",
                    "ship_date": datetime(2024, 1, 16, 10, 0, 0),
                    "method_code": "Ground",
                }
            ]

            result = await authenticated_connector.ship_order_lines("2024010112345", line_shipments)

            assert result is True
            call_args = mock_request.call_args
            assert call_args[0] == ("POST", "/v3/orders/2024010112345/shipping")
            json_data = call_args[1]["json_data"]
            assert "orderShipment" in json_data

    @pytest.mark.asyncio
    async def test_cancel_order_lines(self, authenticated_connector):
        """Should cancel order lines."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {}

            result = await authenticated_connector.cancel_order_lines("2024010112345", ["1", "2"])

            assert result is True
            call_args = mock_request.call_args
            assert call_args[0] == ("POST", "/v3/orders/2024010112345/cancel")
            json_data = call_args[1]["json_data"]
            assert "orderCancellation" in json_data
            order_lines = json_data["orderCancellation"]["orderLines"]["orderLine"]
            assert len(order_lines) == 2


# =============================================================================
# Inventory Tests
# =============================================================================


class TestInventory:
    """Tests for inventory operations."""

    @pytest.mark.asyncio
    async def test_get_inventory(self, authenticated_connector, mock_inventory_response):
        """Should retrieve inventory successfully."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"elements": {"inventories": [mock_inventory_response]}}

            items = await authenticated_connector.get_inventory()

            assert len(items) == 1
            assert items[0].sku == "TEST-SKU-001"
            assert items[0].quantity == 100

    @pytest.mark.asyncio
    async def test_get_inventory_by_sku(self, authenticated_connector, mock_inventory_response):
        """Should filter inventory by SKU."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"elements": {"inventories": [mock_inventory_response]}}

            await authenticated_connector.get_inventory(sku="TEST-SKU-001")

            call_args = mock_request.call_args
            params = call_args[1]["params"]
            assert params["sku"] == "TEST-SKU-001"

    @pytest.mark.asyncio
    async def test_get_inventory_pagination(self, authenticated_connector, mock_inventory_response):
        """Should support pagination parameters."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"elements": {"inventories": [mock_inventory_response]}}

            await authenticated_connector.get_inventory(limit=25, offset=50)

            call_args = mock_request.call_args
            params = call_args[1]["params"]
            assert params["limit"] == 25
            assert params["offset"] == 50

    @pytest.mark.asyncio
    async def test_update_inventory(self, authenticated_connector, mock_inventory_response):
        """Should update inventory for SKU."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = mock_inventory_response

            result = await authenticated_connector.update_inventory(
                sku="TEST-SKU-001",
                quantity=150,
                fulfillment_lag_time=2,
            )

            assert result.sku == "TEST-SKU-001"
            call_args = mock_request.call_args
            assert call_args[0] == ("PUT", "/v3/inventory")
            json_data = call_args[1]["json_data"]
            assert json_data["sku"] == "TEST-SKU-001"
            assert json_data["quantity"]["amount"] == 150
            assert json_data["fulfillmentLagTime"] == 2

    @pytest.mark.asyncio
    async def test_bulk_update_inventory(self, authenticated_connector, mock_feed_status_response):
        """Should bulk update inventory via feed."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = mock_feed_status_response

            updates = [
                {"sku": "SKU-001", "quantity": 100, "fulfillment_lag_time": 1},
                {"sku": "SKU-002", "quantity": 50},
            ]

            result = await authenticated_connector.bulk_update_inventory(updates)

            assert result.feed_id == "feed_abc123"
            call_args = mock_request.call_args
            assert call_args[1]["params"]["feedType"] == "inventory"


# =============================================================================
# Items/Catalog Tests
# =============================================================================


class TestItems:
    """Tests for catalog item operations."""

    @pytest.mark.asyncio
    async def test_get_items(self, authenticated_connector, mock_item_response):
        """Should retrieve items successfully."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"ItemResponse": [mock_item_response]}

            items = await authenticated_connector.get_items()

            assert len(items) == 1
            assert items[0].item_id == "12345678"
            assert items[0].sku == "TEST-SKU-001"

    @pytest.mark.asyncio
    async def test_get_items_with_filters(self, authenticated_connector, mock_item_response):
        """Should apply filters to items query."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"ItemResponse": [mock_item_response]}

            await authenticated_connector.get_items(
                sku="TEST-SKU",
                publish_status=ItemPublishStatus.PUBLISHED,
                lifecycle_status=LifecycleStatus.ACTIVE,
                limit=25,
                offset=10,
            )

            call_args = mock_request.call_args
            params = call_args[1]["params"]
            assert params["sku"] == "TEST-SKU"
            assert params["publishedStatus"] == "PUBLISHED"
            assert params["lifecycleStatus"] == "ACTIVE"
            assert params["limit"] == 25
            assert params["offset"] == 10

    @pytest.mark.asyncio
    async def test_get_item(self, authenticated_connector, mock_item_response):
        """Should retrieve single item."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = mock_item_response

            item = await authenticated_connector.get_item("12345678")

            assert item.item_id == "12345678"
            mock_request.assert_called_with("GET", "/v3/items/12345678")

    @pytest.mark.asyncio
    async def test_retire_item(self, authenticated_connector):
        """Should retire/archive item."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {}

            result = await authenticated_connector.retire_item("TEST-SKU-001")

            assert result is True
            mock_request.assert_called_with("DELETE", "/v3/items/TEST-SKU-001")


# =============================================================================
# Pricing Tests
# =============================================================================


class TestPricing:
    """Tests for pricing operations."""

    @pytest.mark.asyncio
    async def test_update_price(self, authenticated_connector):
        """Should update item price."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {}

            result = await authenticated_connector.update_price(
                sku="TEST-SKU-001",
                price=Decimal("34.99"),
            )

            assert result is True
            call_args = mock_request.call_args
            assert call_args[0] == ("PUT", "/v3/prices")
            json_data = call_args[1]["json_data"]
            assert json_data["sku"] == "TEST-SKU-001"
            assert json_data["pricing"][0]["currentPrice"]["amount"] == 34.99

    @pytest.mark.asyncio
    async def test_update_price_with_compare_at(self, authenticated_connector):
        """Should update price with comparison price."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {}

            result = await authenticated_connector.update_price(
                sku="TEST-SKU-001",
                price=Decimal("34.99"),
                compare_at_price=Decimal("44.99"),
            )

            assert result is True
            call_args = mock_request.call_args
            json_data = call_args[1]["json_data"]
            assert json_data["pricing"][0]["comparisonPrice"]["amount"] == 44.99

    @pytest.mark.asyncio
    async def test_bulk_update_prices(self, authenticated_connector, mock_feed_status_response):
        """Should bulk update prices via feed."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = mock_feed_status_response

            price_updates = [
                {"sku": "SKU-001", "price": Decimal("19.99")},
                {
                    "sku": "SKU-002",
                    "price": Decimal("29.99"),
                    "compare_at_price": Decimal("39.99"),
                },
            ]

            result = await authenticated_connector.bulk_update_prices(price_updates)

            assert result.feed_id == "feed_abc123"
            call_args = mock_request.call_args
            assert call_args[1]["params"]["feedType"] == "price"
            json_data = call_args[1]["json_data"]
            assert "PriceHeader" in json_data
            assert len(json_data["Price"]) == 2


# =============================================================================
# Returns Tests
# =============================================================================


class TestReturns:
    """Tests for return operations."""

    @pytest.mark.asyncio
    async def test_get_returns(self, authenticated_connector, mock_return_response):
        """Should retrieve returns successfully."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"returnOrders": [mock_return_response]}

            returns = await authenticated_connector.get_returns()

            assert len(returns) == 1
            assert returns[0].return_order_id == "RET12345"

    @pytest.mark.asyncio
    async def test_get_returns_with_filters(self, authenticated_connector, mock_return_response):
        """Should apply filters to returns query."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"returnOrders": [mock_return_response]}

            start_date = datetime(2024, 1, 1)
            end_date = datetime(2024, 1, 31)

            await authenticated_connector.get_returns(
                return_status=ReturnStatus.INITIATED,
                return_start_date=start_date,
                return_end_date=end_date,
                limit=50,
            )

            call_args = mock_request.call_args
            params = call_args[1]["params"]
            assert params["returnStatus"] == "INITIATED"
            assert params["returnCreationStartDate"] == "2024-01-01"
            assert params["returnCreationEndDate"] == "2024-01-31"
            assert params["limit"] == 50

    @pytest.mark.asyncio
    async def test_issue_refund(self, authenticated_connector):
        """Should issue refund for return."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {}

            refund_lines = [
                {
                    "return_line_number": "1",
                    "quantity": 1,
                    "refund_amount": Decimal("29.99"),
                }
            ]

            result = await authenticated_connector.issue_refund("RET12345", refund_lines)

            assert result is True
            call_args = mock_request.call_args
            assert call_args[0] == ("POST", "/v3/returns/RET12345/refund")
            json_data = call_args[1]["json_data"]
            assert json_data["customerOrderId"] == "RET12345"
            assert len(json_data["refundLines"]) == 1


# =============================================================================
# Feed Tests
# =============================================================================


class TestFeeds:
    """Tests for feed operations."""

    @pytest.mark.asyncio
    async def test_get_feed_status(self, authenticated_connector, mock_feed_status_response):
        """Should retrieve feed status."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = mock_feed_status_response

            status = await authenticated_connector.get_feed_status("feed_abc123")

            assert status.feed_id == "feed_abc123"
            assert status.status == "PROCESSED"
            mock_request.assert_called_with("GET", "/v3/feeds/feed_abc123")

    @pytest.mark.asyncio
    async def test_get_all_feed_statuses(self, authenticated_connector, mock_feed_status_response):
        """Should retrieve all feed statuses."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"results": {"feed": [mock_feed_status_response]}}

            statuses = await authenticated_connector.get_all_feed_statuses()

            assert len(statuses) == 1
            assert statuses[0].feed_id == "feed_abc123"

    @pytest.mark.asyncio
    async def test_get_all_feed_statuses_with_filters(
        self, authenticated_connector, mock_feed_status_response
    ):
        """Should apply filters to feed status query."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"results": {"feed": [mock_feed_status_response]}}

            await authenticated_connector.get_all_feed_statuses(
                feed_type="inventory",
                limit=25,
                offset=10,
            )

            call_args = mock_request.call_args
            params = call_args[1]["params"]
            assert params["feedType"] == "inventory"
            assert params["limit"] == 25
            assert params["offset"] == 10


# =============================================================================
# Reports Tests
# =============================================================================


class TestReports:
    """Tests for report operations."""

    @pytest.mark.asyncio
    async def test_get_available_reports(self, authenticated_connector):
        """Should retrieve available report types."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {
                "reportTypes": [
                    {"type": "item", "name": "Item Report"},
                    {"type": "inventory", "name": "Inventory Report"},
                ]
            }

            reports = await authenticated_connector.get_available_reports()

            assert len(reports) == 2
            assert reports[0]["type"] == "item"

    @pytest.mark.asyncio
    async def test_request_report(self, authenticated_connector):
        """Should request report generation."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {"requestId": "req_123"}

            request_id = await authenticated_connector.request_report("item")

            assert request_id == "req_123"
            call_args = mock_request.call_args
            json_data = call_args[1]["json_data"]
            assert json_data["reportType"] == "item"
            assert json_data["reportVersion"] == "v1"

    @pytest.mark.asyncio
    async def test_get_report_status(self, authenticated_connector):
        """Should retrieve report status."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            mock_request.return_value = {
                "requestId": "req_123",
                "status": "COMPLETED",
                "downloadUrl": "https://example.com/download",
            }

            status = await authenticated_connector.get_report_status("req_123")

            assert status["status"] == "COMPLETED"
            mock_request.assert_called_with("GET", "/v3/reports/reportRequests/req_123")

    @pytest.mark.asyncio
    async def test_download_report(self, authenticated_connector):
        """Should download generated report."""
        mock_response = MagicMock()
        mock_response.content = b"CSV,data,here\n1,2,3"
        mock_response.raise_for_status = MagicMock()

        with patch.object(authenticated_connector, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            content = await authenticated_connector.download_report("req_123")

            assert content == b"CSV,data,here\n1,2,3"


# =============================================================================
# Error Handling Tests
# =============================================================================


class TestErrorHandling:
    """Tests for error handling."""

    def test_walmart_error_creation(self):
        """Should create WalmartError with all fields."""
        error = WalmartError(
            message="Invalid request",
            code="INVALID_REQUEST",
            details={"field": "sku", "reason": "missing"},
        )
        assert str(error) == "Invalid request"
        assert error.code == "INVALID_REQUEST"
        assert error.details == {"field": "sku", "reason": "missing"}

    def test_walmart_error_default_details(self):
        """Should default details to empty dict."""
        error = WalmartError("Error occurred")
        assert error.details == {}
        assert error.code is None

    @pytest.mark.asyncio
    async def test_request_handles_empty_error_array(self, authenticated_connector):
        """Should handle empty errors array in response."""
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"errors": []}
        mock_response.text = "Bad Request"

        with patch.object(authenticated_connector, "_get_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.request = AsyncMock(return_value=mock_response)
            mock_get_client.return_value = mock_client

            with pytest.raises(WalmartError) as exc_info:
                await authenticated_connector._request("GET", "/v3/test")

            # Should use fallback from text
            assert "Bad Request" in str(exc_info.value)


# =============================================================================
# Context Manager Tests
# =============================================================================


class TestContextManager:
    """Tests for async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_entry(self, credentials):
        """Should return connector on entry."""
        async with WalmartConnector(credentials) as connector:
            assert isinstance(connector, WalmartConnector)

    @pytest.mark.asyncio
    async def test_context_manager_closes_client(self, credentials):
        """Should close client on exit."""
        connector = WalmartConnector(credentials)
        mock_client = AsyncMock()
        mock_client.aclose = AsyncMock()
        connector._client = mock_client

        async with connector:
            pass

        # After close(), _client is set to None, so we check the mock we kept
        mock_client.aclose.assert_called_once()
        assert connector._client is None

    @pytest.mark.asyncio
    async def test_close_without_client(self, connector):
        """Should handle close when no client exists."""
        await connector.close()  # Should not raise


# =============================================================================
# Helper Function Tests
# =============================================================================


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_parse_datetime_iso_with_milliseconds(self):
        """Should parse datetime with milliseconds."""
        result = _parse_datetime("2024-01-15T10:30:45.123Z")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30
        assert result.second == 45

    def test_parse_datetime_iso_without_milliseconds(self):
        """Should parse datetime without milliseconds."""
        result = _parse_datetime("2024-01-15T10:30:45Z")
        assert result is not None
        assert result.year == 2024

    def test_parse_datetime_iso_without_timezone(self):
        """Should parse datetime without timezone."""
        result = _parse_datetime("2024-01-15T10:30:45")
        assert result is not None
        assert result.year == 2024

    def test_parse_datetime_date_only(self):
        """Should parse date-only format."""
        result = _parse_datetime("2024-01-15")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_parse_datetime_none(self):
        """Should return None for None input."""
        result = _parse_datetime(None)
        assert result is None

    def test_parse_datetime_invalid(self):
        """Should raise ValueError for invalid format."""
        with pytest.raises(ValueError, match="Unsupported Walmart datetime format"):
            _parse_datetime("not-a-date")

    def test_parse_datetime_empty_string(self):
        """Should raise ValueError for empty string (only None means absent)."""
        with pytest.raises(ValueError, match="Unsupported Walmart datetime format"):
            _parse_datetime("")


# =============================================================================
# Mock Data Tests
# =============================================================================


class TestMockData:
    """Tests for mock data generation."""

    def test_get_mock_order(self):
        """Should return valid mock order."""
        order = get_mock_order()
        assert order.purchase_order_id == "2024010112345"
        assert order.customer_order_id == "ABC12345"
        assert order.status == OrderStatus.ACKNOWLEDGED
        assert len(order.order_lines) == 1
        assert order.order_lines[0].sku == "TEST-SKU-001"
        assert order.total_amount == Decimal("59.98")
        assert order.shipping_address.name == "John Doe"
        assert order.shipping_address.city == "Bentonville"

    def test_get_mock_item(self):
        """Should return valid mock item."""
        item = get_mock_item()
        assert item.item_id == "12345678"
        assert item.sku == "TEST-SKU-001"
        assert item.product_name == "Test Product"
        assert item.brand == "Test Brand"
        assert item.price == Decimal("29.99")
        assert item.publish_status == ItemPublishStatus.PUBLISHED
        assert item.lifecycle_status == LifecycleStatus.ACTIVE
        assert item.upc == "012345678901"


# =============================================================================
# Integration-style Tests
# =============================================================================


class TestIntegrationPatterns:
    """Tests for common integration patterns."""

    @pytest.mark.asyncio
    async def test_order_workflow(self, authenticated_connector, mock_order_response):
        """Should support typical order processing workflow."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            # Get order
            mock_request.return_value = {"order": mock_order_response}
            order = await authenticated_connector.get_order("2024010112345")
            assert order.status == OrderStatus.ACKNOWLEDGED

            # Acknowledge order
            mock_request.return_value = {}
            result = await authenticated_connector.acknowledge_order(order.purchase_order_id)
            assert result is True

            # Ship order lines
            shipments = [
                {
                    "line_number": "1",
                    "carrier": "UPS",
                    "tracking_number": "1Z999AA1",
                }
            ]
            result = await authenticated_connector.ship_order_lines(
                order.purchase_order_id, shipments
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_inventory_sync_workflow(
        self, authenticated_connector, mock_inventory_response, mock_feed_status_response
    ):
        """Should support inventory synchronization workflow."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            # Get current inventory
            mock_request.return_value = {"elements": {"inventories": [mock_inventory_response]}}
            items = await authenticated_connector.get_inventory()
            assert len(items) == 1

            # Bulk update inventory
            mock_request.return_value = mock_feed_status_response
            updates = [{"sku": items[0].sku, "quantity": items[0].quantity + 50}]
            feed = await authenticated_connector.bulk_update_inventory(updates)
            assert feed.feed_id == "feed_abc123"

            # Check feed status
            mock_request.return_value = mock_feed_status_response
            status = await authenticated_connector.get_feed_status(feed.feed_id)
            assert status.status == "PROCESSED"

    @pytest.mark.asyncio
    async def test_price_update_workflow(
        self, authenticated_connector, mock_item_response, mock_feed_status_response
    ):
        """Should support price update workflow."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            # Get item
            mock_request.return_value = mock_item_response
            item = await authenticated_connector.get_item("12345678")
            original_price = item.price

            # Update price
            mock_request.return_value = {}
            new_price = original_price - Decimal("5.00")
            result = await authenticated_connector.update_price(
                sku=item.sku,
                price=new_price,
                compare_at_price=original_price,
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_return_processing_workflow(self, authenticated_connector, mock_return_response):
        """Should support return processing workflow."""
        with patch.object(authenticated_connector, "_request") as mock_request:
            # Get returns
            mock_request.return_value = {"returnOrders": [mock_return_response]}
            returns = await authenticated_connector.get_returns(
                return_status=ReturnStatus.INITIATED
            )
            assert len(returns) == 1

            # Issue refund
            mock_request.return_value = {}
            refund_lines = [
                {
                    "return_line_number": "1",
                    "quantity": 1,
                    "refund_amount": returns[0].refund_amount,
                }
            ]
            result = await authenticated_connector.issue_refund(
                returns[0].return_order_id, refund_lines
            )
            assert result is True
