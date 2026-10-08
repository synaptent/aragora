"""
WooCommerce API client.

Provides the core WooCommerceConnector class with HTTP request handling,
authentication, circuit breaker integration, and CRUD operations for
orders, products, customers, coupons, shipping, tax, and reports.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from collections.abc import AsyncIterator

from aragora.connectors.base import Evidence
from aragora.connectors.enterprise.base import EnterpriseConnector, SyncItem, SyncState, SyncResult
from aragora.connectors.exceptions import (
    ConnectorAPIError,
    ConnectorCircuitOpenError,
    ConnectorTimeoutError,
)
from aragora.reasoning.provenance import SourceType
from aragora.resilience.circuit_breaker import CircuitBreaker

from aragora.connectors.ecommerce.woocommerce.models import (
    DEFAULT_REQUEST_TIMEOUT,
    WooAddress,
    WooCommerceCredentials,
    WooCustomer,
    WooLineItem,
    WooOrder,
    WooOrderStatus,
    WooProduct,
    WooProductStatus,
    WooProductType,
    WooProductVariation,
    WooStockStatus,
    validate_id,
)

logger = logging.getLogger(__name__)

_MAX_PAGES = 1000  # Safety cap for pagination loops


class WooCommerceConnector(EnterpriseConnector):
    """
    Connector for WooCommerce (WordPress) stores.

    Supports:
    - Order sync and management
    - Product and variation management
    - Customer data sync
    - Inventory tracking
    - Webhook handling

    Example:
        ```python
        credentials = WooCommerceCredentials.from_env()
        connector = WooCommerceConnector(credentials)

        # Sync orders
        async for order in connector.sync_orders(since=last_sync):
            process_order(order)

        # Update stock
        await connector.update_product_stock(product_id=123, quantity=50)
        ```
    """

    def __init__(
        self,
        credentials: WooCommerceCredentials,
        circuit_breaker: CircuitBreaker | None = None,
    ):
        """Initialize WooCommerce connector.

        Args:
            credentials: WooCommerce API credentials
            circuit_breaker: Optional circuit breaker for API quota protection.
                            If not provided, a default one is created.
        """
        super().__init__(connector_id="woocommerce", tenant_id="default")
        self._woo_credentials = credentials
        self._client: Any = None
        self._circuit_breaker = circuit_breaker or CircuitBreaker(
            name="woocommerce",
            failure_threshold=5,
            cooldown_seconds=60.0,
        )

    @property
    def name(self) -> str:
        """Human-readable name for this connector."""
        return "WooCommerce"

    @property
    def source_type(self) -> SourceType:
        """The source type for this connector."""
        return SourceType.EXTERNAL_API

    @property
    def base_url(self) -> str:
        """Get API base URL."""
        return f"{self._woo_credentials.store_url}/wp-json/{self._woo_credentials.api_version}"

    async def connect(self) -> bool:
        """Establish connection to WooCommerce API."""
        try:
            import aiohttp
            from aiohttp import BasicAuth

            auth = BasicAuth(
                self._woo_credentials.consumer_key,
                self._woo_credentials.consumer_secret,
            )
            self._client = aiohttp.ClientSession(auth=auth)

            # Test connection
            async with self._client.get(f"{self.base_url}/system_status") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    logger.info(
                        "Connected to WooCommerce store: %s",
                        data.get("environment", {}).get("site_url", "unknown"),
                    )
                    return True
                else:
                    logger.error("Failed to connect: HTTP %s", resp.status)
                    return False

        except ImportError:
            logger.error("aiohttp package not installed. Run: pip install aiohttp")
            return False
        except OSError as e:
            logger.error("Failed to connect to WooCommerce: %s", e)
            return False

    async def disconnect(self) -> None:
        """Close WooCommerce connection."""
        if self._client:
            await self._client.close()
            self._client = None

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Get the circuit breaker instance."""
        breaker = self._circuit_breaker
        if breaker is None:
            raise RuntimeError("WooCommerce circuit breaker is not initialized")
        return breaker

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Make an API request with timeout and circuit breaker protection.

        Args:
            method: HTTP method
            endpoint: API endpoint
            params: Query parameters
            json_data: JSON body data
            timeout: Request timeout in seconds (defaults to credentials.timeout or 30s)

        Returns:
            Response data

        Raises:
            ConnectorTimeoutError: If the request times out
            ConnectorCircuitOpenError: If the circuit breaker is open
            ConnectorAPIError: If the API returns an error
        """
        breaker = self.circuit_breaker

        # Check circuit breaker
        if not breaker.can_proceed():
            cooldown = breaker.cooldown_remaining()
            raise ConnectorCircuitOpenError(
                "WooCommerce API circuit breaker is open due to repeated failures",
                connector_name="woocommerce",
                cooldown_remaining=cooldown,
            )

        if not self._client:
            await self.connect()

        url = f"{self.base_url}/{endpoint}"
        request_timeout = timeout or self._woo_credentials.timeout or DEFAULT_REQUEST_TIMEOUT

        try:
            async with asyncio.timeout(request_timeout):
                async with self._client.request(method, url, params=params, json=json_data) as resp:
                    if resp.status >= 400:
                        error_text = await resp.text()
                        # Record failure for circuit breaker on server errors or rate limits
                        if resp.status >= 500 or resp.status == 429:
                            breaker.record_failure()
                        raise ConnectorAPIError(
                            f"WooCommerce API error: {error_text}",
                            connector_name="woocommerce",
                            status_code=resp.status,
                        )
                    # Record success
                    breaker.record_success()
                    return await resp.json()
        except asyncio.TimeoutError:
            breaker.record_failure()
            raise ConnectorTimeoutError(
                f"WooCommerce API request timed out after {request_timeout}s",
                connector_name="woocommerce",
                timeout_seconds=request_timeout,
            )

    # =========================================================================
    # Orders
    # =========================================================================

    async def sync_orders(
        self,
        since: datetime | None = None,
        status: WooOrderStatus | None = None,
        per_page: int = 100,
    ) -> AsyncIterator[WooOrder]:
        """Sync orders from WooCommerce.

        Args:
            since: Only fetch orders modified after this time
            status: Filter by order status
            per_page: Page size

        Yields:
            WooOrder objects
        """
        params: dict[str, Any] = {"per_page": per_page, "page": 1}
        if since:
            params["modified_after"] = since.isoformat()
        if status:
            params["status"] = status.value

        for _page in range(_MAX_PAGES):
            data = await self._request("GET", "orders", params=params)

            if not data:
                break

            for order_data in data:
                yield self._parse_order(order_data)

            if len(data) < per_page:
                break

            params["page"] += 1

    def _parse_order(self, data: dict[str, Any]) -> WooOrder:
        """Parse order from API response."""
        line_items = [
            WooLineItem(
                id=item["id"],
                product_id=item["product_id"],
                variation_id=item.get("variation_id", 0),
                name=item["name"],
                quantity=item["quantity"],
                subtotal=Decimal(str(item["subtotal"])),
                total=Decimal(str(item["total"])),
                sku=item.get("sku"),
                price=Decimal(str(item.get("price", "0"))),
                tax_class=item.get("tax_class"),
            )
            for item in data.get("line_items", [])
        ]

        return WooOrder(
            id=data["id"],
            number=data["number"],
            order_key=data["order_key"],
            status=WooOrderStatus(data["status"]),
            currency=data["currency"],
            date_created=datetime.fromisoformat(data["date_created_gmt"] + "+00:00"),
            date_modified=datetime.fromisoformat(data["date_modified_gmt"] + "+00:00"),
            total=Decimal(str(data["total"])),
            subtotal=Decimal(str(data.get("subtotal", "0"))),
            total_tax=Decimal(str(data["total_tax"])),
            shipping_total=Decimal(str(data["shipping_total"])),
            discount_total=Decimal(str(data["discount_total"])),
            payment_method=data["payment_method"],
            payment_method_title=data["payment_method_title"],
            customer_id=data["customer_id"],
            billing=self._parse_address(data.get("billing", {})),
            shipping=self._parse_address(data.get("shipping", {})),
            line_items=line_items,
            customer_note=data.get("customer_note"),
            date_paid=(
                datetime.fromisoformat(data["date_paid_gmt"] + "+00:00")
                if data.get("date_paid_gmt")
                else None
            ),
            date_completed=(
                datetime.fromisoformat(data["date_completed_gmt"] + "+00:00")
                if data.get("date_completed_gmt")
                else None
            ),
            transaction_id=data.get("transaction_id"),
        )

    def _parse_address(self, data: dict[str, Any]) -> WooAddress:
        """Parse address from API response."""
        return WooAddress(
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            company=data.get("company"),
            address_1=data.get("address_1"),
            address_2=data.get("address_2"),
            city=data.get("city"),
            state=data.get("state"),
            postcode=data.get("postcode"),
            country=data.get("country"),
            email=data.get("email"),
            phone=data.get("phone"),
        )

    async def get_order(self, order_id: int) -> WooOrder | None:
        """Get a single order by ID.

        Args:
            order_id: Order ID (must be alphanumeric)

        Returns:
            WooOrder or None if not found

        Raises:
            ConnectorValidationError: If order_id contains invalid characters
        """
        validate_id(order_id, "order_id")
        try:
            data = await self._request("GET", f"orders/{order_id}")
            return self._parse_order(data)
        except (
            ConnectorAPIError,
            ConnectorCircuitOpenError,
            ConnectorTimeoutError,
            OSError,
            ValueError,
            KeyError,
        ) as e:
            logger.error("Failed to get order %s: %s", order_id, e)
            return None

    async def update_order_status(
        self,
        order_id: int,
        status: WooOrderStatus,
    ) -> bool:
        """Update order status.

        Args:
            order_id: Order ID (must be alphanumeric)
            status: New status

        Returns:
            True if successful

        Raises:
            ConnectorValidationError: If order_id contains invalid characters
        """
        validate_id(order_id, "order_id")
        try:
            await self._request(
                "PUT",
                f"orders/{order_id}",
                json_data={"status": status.value},
            )
            return True
        except (ConnectorAPIError, ConnectorCircuitOpenError, ConnectorTimeoutError, OSError) as e:
            logger.error("Failed to update order %s: %s", order_id, e)
            return False

    async def create_order(
        self,
        customer_id: int | None = None,
        billing: WooAddress | None = None,
        shipping: WooAddress | None = None,
        line_items: list[dict[str, Any]] | None = None,
        payment_method: str = "",
        payment_method_title: str = "",
        set_paid: bool = False,
        note: str | None = None,
    ) -> WooOrder | None:
        """Create a new order.

        Args:
            customer_id: Customer ID (0 for guest)
            billing: Billing address
            shipping: Shipping address
            line_items: List of line items [{"product_id": 123, "quantity": 1}]
            payment_method: Payment method ID
            payment_method_title: Payment method title
            set_paid: Mark order as paid
            note: Customer note

        Returns:
            Created WooOrder or None on failure
        """
        try:
            order_data: dict[str, Any] = {
                "payment_method": payment_method,
                "payment_method_title": payment_method_title,
                "set_paid": set_paid,
            }

            if customer_id is not None:
                order_data["customer_id"] = customer_id
            if billing:
                order_data["billing"] = {
                    "first_name": billing.first_name or "",
                    "last_name": billing.last_name or "",
                    "company": billing.company or "",
                    "address_1": billing.address_1 or "",
                    "address_2": billing.address_2 or "",
                    "city": billing.city or "",
                    "state": billing.state or "",
                    "postcode": billing.postcode or "",
                    "country": billing.country or "",
                    "email": billing.email or "",
                    "phone": billing.phone or "",
                }
            if shipping:
                order_data["shipping"] = {
                    "first_name": shipping.first_name or "",
                    "last_name": shipping.last_name or "",
                    "company": shipping.company or "",
                    "address_1": shipping.address_1 or "",
                    "address_2": shipping.address_2 or "",
                    "city": shipping.city or "",
                    "state": shipping.state or "",
                    "postcode": shipping.postcode or "",
                    "country": shipping.country or "",
                }
            if line_items:
                order_data["line_items"] = line_items
            if note:
                order_data["customer_note"] = note

            data = await self._request("POST", "orders", json_data=order_data)
            return self._parse_order(data)
        except (ConnectorAPIError, OSError, ValueError, KeyError) as e:
            logger.error("Failed to create order: %s", e)
            return None

    async def get_order_stats(
        self,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
    ) -> dict[str, Any]:
        """Get order statistics.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            Dictionary with order statistics
        """
        total_orders = 0
        total_revenue = Decimal("0.00")
        completed_orders = 0
        cancelled_orders = 0
        refunded_orders = 0
        status_counts: dict[str, int] = {}

        async for order in self.sync_orders(since=start_date):
            if end_date and order.date_created > end_date:
                continue

            total_orders += 1
            total_revenue += order.total

            status = order.status.value
            status_counts[status] = status_counts.get(status, 0) + 1

            if order.status == WooOrderStatus.COMPLETED:
                completed_orders += 1
            elif order.status == WooOrderStatus.CANCELLED:
                cancelled_orders += 1
            elif order.status == WooOrderStatus.REFUNDED:
                refunded_orders += 1

        return {
            "total_orders": total_orders,
            "total_revenue": str(total_revenue),
            "completed_orders": completed_orders,
            "cancelled_orders": cancelled_orders,
            "refunded_orders": refunded_orders,
            "completion_rate": completed_orders / total_orders if total_orders > 0 else 0,
            "average_order_value": (
                str(total_revenue / total_orders) if total_orders > 0 else "0.00"
            ),
            "status_breakdown": status_counts,
        }

    # =========================================================================
    # Products
    # =========================================================================

    async def sync_products(
        self,
        since: datetime | None = None,
        status: WooProductStatus | None = None,
        per_page: int = 100,
    ) -> AsyncIterator[WooProduct]:
        """Sync products from WooCommerce.

        Args:
            since: Only fetch products modified after this time
            status: Filter by product status
            per_page: Page size

        Yields:
            WooProduct objects
        """
        params: dict[str, Any] = {"per_page": per_page, "page": 1}
        if since:
            params["modified_after"] = since.isoformat()
        if status:
            params["status"] = status.value

        for _page in range(_MAX_PAGES):
            data = await self._request("GET", "products", params=params)

            if not data:
                break

            for product_data in data:
                yield self._parse_product(product_data)

            if len(data) < per_page:
                break

            params["page"] += 1

    def _parse_product(self, data: dict[str, Any]) -> WooProduct:
        """Parse product from API response."""
        return WooProduct(
            id=data["id"],
            name=data["name"],
            slug=data["slug"],
            type=WooProductType(data.get("type", "simple")),
            status=WooProductStatus(data.get("status", "publish")),
            sku=data.get("sku"),
            price=Decimal(str(data.get("price", "0") or "0")),
            regular_price=Decimal(str(data.get("regular_price", "0") or "0")),
            sale_price=Decimal(str(data["sale_price"])) if data.get("sale_price") else None,
            date_created=datetime.fromisoformat(data["date_created_gmt"] + "+00:00"),
            date_modified=datetime.fromisoformat(data["date_modified_gmt"] + "+00:00"),
            description=data.get("description"),
            short_description=data.get("short_description"),
            stock_quantity=data.get("stock_quantity"),
            stock_status=WooStockStatus(data.get("stock_status", "instock")),
            manage_stock=data.get("manage_stock", False),
            categories=data.get("categories", []),
            tags=data.get("tags", []),
            images=[img["src"] for img in data.get("images", [])],
            attributes=data.get("attributes", []),
        )

    async def get_product(self, product_id: int) -> WooProduct | None:
        """Get a single product by ID.

        Args:
            product_id: Product ID (must be alphanumeric)

        Returns:
            WooProduct or None if not found

        Raises:
            ConnectorValidationError: If product_id contains invalid characters
        """
        validate_id(product_id, "product_id")
        try:
            data = await self._request("GET", f"products/{product_id}")
            return self._parse_product(data)
        except (
            ConnectorAPIError,
            ConnectorCircuitOpenError,
            ConnectorTimeoutError,
            OSError,
            ValueError,
            KeyError,
        ) as e:
            logger.error("Failed to get product %s: %s", product_id, e)
            return None

    async def update_product_stock(
        self,
        product_id: int,
        quantity: int,
        stock_status: WooStockStatus | None = None,
    ) -> bool:
        """Update product stock.

        Args:
            product_id: Product ID (must be alphanumeric)
            quantity: New stock quantity
            stock_status: Optional stock status

        Returns:
            True if successful

        Raises:
            ConnectorValidationError: If product_id contains invalid characters
        """
        validate_id(product_id, "product_id")
        try:
            update_data: dict[str, Any] = {
                "stock_quantity": quantity,
                "manage_stock": True,
            }
            if stock_status:
                update_data["stock_status"] = stock_status.value

            await self._request(
                "PUT",
                f"products/{product_id}",
                json_data=update_data,
            )
            return True
        except (ConnectorAPIError, ConnectorCircuitOpenError, ConnectorTimeoutError, OSError) as e:
            logger.error("Failed to update product stock %s: %s", product_id, e)
            return False

    async def get_low_stock_products(
        self,
        threshold: int = 5,
    ) -> list[WooProduct]:
        """Get products with low stock.

        Args:
            threshold: Stock level threshold

        Returns:
            List of low stock products
        """
        low_stock = []
        async for product in self.sync_products():
            if product.manage_stock and product.stock_quantity is not None:
                if product.stock_quantity <= threshold:
                    low_stock.append(product)
        return low_stock

    async def sync_product_variations(
        self,
        product_id: int,
        per_page: int = 100,
    ) -> AsyncIterator[WooProductVariation]:
        """Sync variations for a variable product.

        Args:
            product_id: Parent product ID
            per_page: Page size

        Yields:
            WooProductVariation objects
        """
        params: dict[str, Any] = {"per_page": per_page, "page": 1}

        for _page in range(_MAX_PAGES):
            data = await self._request("GET", f"products/{product_id}/variations", params=params)

            if not data:
                break

            for variation_data in data:
                yield self._parse_variation(variation_data)

            if len(data) < per_page:
                break

            params["page"] += 1

    def _parse_variation(self, data: dict[str, Any]) -> WooProductVariation:
        """Parse variation from API response."""
        return WooProductVariation(
            id=data["id"],
            sku=data.get("sku"),
            price=Decimal(str(data.get("price", "0") or "0")),
            regular_price=Decimal(str(data.get("regular_price", "0") or "0")),
            sale_price=Decimal(str(data["sale_price"])) if data.get("sale_price") else None,
            stock_quantity=data.get("stock_quantity"),
            stock_status=WooStockStatus(data.get("stock_status", "instock")),
            manage_stock=data.get("manage_stock", False),
            attributes=data.get("attributes", []),
            image=data.get("image", {}).get("src") if data.get("image") else None,
        )

    async def update_variation_stock(
        self,
        product_id: int,
        variation_id: int,
        quantity: int,
        stock_status: WooStockStatus | None = None,
    ) -> bool:
        """Update variation stock.

        Args:
            product_id: Parent product ID (must be alphanumeric)
            variation_id: Variation ID (must be alphanumeric)
            quantity: New stock quantity
            stock_status: Optional stock status

        Returns:
            True if successful

        Raises:
            ConnectorValidationError: If IDs contain invalid characters
        """
        validate_id(product_id, "product_id")
        validate_id(variation_id, "variation_id")
        try:
            update_data: dict[str, Any] = {
                "stock_quantity": quantity,
                "manage_stock": True,
            }
            if stock_status:
                update_data["stock_status"] = stock_status.value

            await self._request(
                "PUT",
                f"products/{product_id}/variations/{variation_id}",
                json_data=update_data,
            )
            return True
        except (ConnectorAPIError, ConnectorCircuitOpenError, ConnectorTimeoutError, OSError) as e:
            logger.error("Failed to update variation stock %s: %s", variation_id, e)
            return False

    # =========================================================================
    # Customers
    # =========================================================================

    async def sync_customers(
        self,
        since: datetime | None = None,
        per_page: int = 100,
    ) -> AsyncIterator[WooCustomer]:
        """Sync customers from WooCommerce.

        Args:
            since: Only fetch customers modified after this time
            per_page: Page size

        Yields:
            WooCustomer objects
        """
        params: dict[str, Any] = {"per_page": per_page, "page": 1}
        if since:
            params["modified_after"] = since.isoformat()

        for _page in range(_MAX_PAGES):
            data = await self._request("GET", "customers", params=params)

            if not data:
                break

            for customer_data in data:
                yield self._parse_customer(customer_data)

            if len(data) < per_page:
                break

            params["page"] += 1
        else:
            logger.warning("Pagination safety cap reached for customers")

    def _parse_customer(self, data: dict[str, Any]) -> WooCustomer:
        """Parse customer from API response."""
        return WooCustomer(
            id=data["id"],
            email=data["email"],
            first_name=data["first_name"],
            last_name=data["last_name"],
            username=data["username"],
            date_created=datetime.fromisoformat(data["date_created_gmt"] + "+00:00"),
            date_modified=datetime.fromisoformat(data["date_modified_gmt"] + "+00:00"),
            billing=self._parse_address(data.get("billing", {})),
            shipping=self._parse_address(data.get("shipping", {})),
            is_paying_customer=data.get("is_paying_customer", False),
            orders_count=data.get("orders_count", 0),
            total_spent=Decimal(str(data.get("total_spent", "0"))),
            avatar_url=data.get("avatar_url"),
        )

    # =========================================================================
    # Refunds
    # =========================================================================

    async def create_refund(
        self,
        order_id: int,
        amount: Decimal | None = None,
        reason: str = "",
        line_items: list[dict[str, Any]] | None = None,
        restock_items: bool = True,
    ) -> dict[str, Any] | None:
        """Create a refund for an order.

        Args:
            order_id: Order ID to refund (must be alphanumeric)
            amount: Refund amount (if None, refunds full order)
            reason: Reason for refund
            line_items: Specific line items to refund [{"id": 123, "quantity": 1}]
            restock_items: Whether to restock items

        Returns:
            Refund data or None on failure

        Raises:
            ConnectorValidationError: If order_id contains invalid characters
        """
        validate_id(order_id, "order_id")
        try:
            refund_data: dict[str, Any] = {
                "reason": reason,
                "restock_items": restock_items,
            }

            if amount is not None:
                refund_data["amount"] = str(amount)
            if line_items:
                refund_data["line_items"] = line_items

            data = await self._request(
                "POST",
                f"orders/{order_id}/refunds",
                json_data=refund_data,
            )
            return data
        except (ConnectorAPIError, ConnectorCircuitOpenError, ConnectorTimeoutError, OSError) as e:
            logger.error("Failed to create refund for order %s: %s", order_id, e)
            return None

    async def get_refunds(self, order_id: int) -> list[dict[str, Any]]:
        """Get refunds for an order.

        Args:
            order_id: Order ID (must be alphanumeric)

        Returns:
            List of refund data

        Raises:
            ConnectorValidationError: If order_id contains invalid characters
        """
        validate_id(order_id, "order_id")
        try:
            data = await self._request("GET", f"orders/{order_id}/refunds")
            return data if isinstance(data, list) else []
        except (ConnectorAPIError, ConnectorCircuitOpenError, ConnectorTimeoutError, OSError) as e:
            logger.error("Failed to get refunds for order %s: %s", order_id, e)
            return []

    # =========================================================================
    # Coupons
    # =========================================================================

    async def get_coupons(
        self,
        per_page: int = 100,
    ) -> AsyncIterator[dict[str, Any]]:
        """Sync coupons from WooCommerce.

        Args:
            per_page: Page size

        Yields:
            Coupon data dictionaries
        """
        params: dict[str, Any] = {"per_page": per_page, "page": 1}

        for _page in range(_MAX_PAGES):
            data = await self._request("GET", "coupons", params=params)

            if not data:
                break

            for coupon in data:
                yield coupon

            if len(data) < per_page:
                break

            params["page"] += 1
        else:
            logger.warning("Pagination safety cap reached for coupons")

    async def create_coupon(
        self,
        code: str,
        discount_type: str = "percent",
        amount: str = "0",
        description: str = "",
        date_expires: datetime | None = None,
        individual_use: bool = False,
        usage_limit: int | None = None,
        product_ids: list[int] | None = None,
        excluded_product_ids: list[int] | None = None,
        minimum_amount: str | None = None,
        maximum_amount: str | None = None,
        free_shipping: bool = False,
    ) -> dict[str, Any] | None:
        """Create a new coupon.

        Args:
            code: Coupon code
            discount_type: Type (percent, fixed_cart, fixed_product)
            amount: Discount amount
            description: Coupon description
            date_expires: Expiration date
            individual_use: Cannot be combined with other coupons
            usage_limit: Total usage limit
            product_ids: Products coupon applies to
            excluded_product_ids: Products coupon doesn't apply to
            minimum_amount: Minimum order amount
            maximum_amount: Maximum order amount
            free_shipping: Whether coupon grants free shipping

        Returns:
            Created coupon data or None on failure
        """
        try:
            coupon_data: dict[str, Any] = {
                "code": code,
                "discount_type": discount_type,
                "amount": amount,
                "description": description,
                "individual_use": individual_use,
                "free_shipping": free_shipping,
            }

            if date_expires:
                coupon_data["date_expires"] = date_expires.isoformat()
            if usage_limit is not None:
                coupon_data["usage_limit"] = usage_limit
            if product_ids:
                coupon_data["product_ids"] = product_ids
            if excluded_product_ids:
                coupon_data["excluded_product_ids"] = excluded_product_ids
            if minimum_amount:
                coupon_data["minimum_amount"] = minimum_amount
            if maximum_amount:
                coupon_data["maximum_amount"] = maximum_amount

            data = await self._request("POST", "coupons", json_data=coupon_data)
            return data
        except (ConnectorAPIError, OSError) as e:
            logger.error("Failed to create coupon %s: %s", code, e)
            return None

    async def delete_coupon(self, coupon_id: int, force: bool = True) -> bool:
        """Delete a coupon.

        Args:
            coupon_id: Coupon ID (must be alphanumeric)
            force: Permanently delete (vs trash)

        Returns:
            True if successful

        Raises:
            ConnectorValidationError: If coupon_id contains invalid characters
        """
        validate_id(coupon_id, "coupon_id")
        try:
            await self._request(
                "DELETE",
                f"coupons/{coupon_id}",
                params={"force": force},
            )
            return True
        except (ConnectorAPIError, ConnectorCircuitOpenError, ConnectorTimeoutError, OSError) as e:
            logger.error("Failed to delete coupon %s: %s", coupon_id, e)
            return False

    # =========================================================================
    # Shipping
    # =========================================================================

    async def get_shipping_zones(self) -> list[dict[str, Any]]:
        """Get all shipping zones.

        Returns:
            List of shipping zone data
        """
        try:
            data = await self._request("GET", "shipping/zones")
            return data if isinstance(data, list) else []
        except (ConnectorAPIError, OSError) as e:
            logger.error("Failed to get shipping zones: %s", e)
            return []

    async def get_shipping_methods(self, zone_id: int) -> list[dict[str, Any]]:
        """Get shipping methods for a zone.

        Args:
            zone_id: Shipping zone ID (must be alphanumeric)

        Returns:
            List of shipping method data

        Raises:
            ConnectorValidationError: If zone_id contains invalid characters
        """
        validate_id(zone_id, "zone_id")
        try:
            data = await self._request("GET", f"shipping/zones/{zone_id}/methods")
            return data if isinstance(data, list) else []
        except (ConnectorAPIError, ConnectorCircuitOpenError, ConnectorTimeoutError, OSError) as e:
            logger.error("Failed to get shipping methods for zone %s: %s", zone_id, e)
            return []

    # =========================================================================
    # Tax
    # =========================================================================

    async def get_tax_classes(self) -> list[dict[str, Any]]:
        """Get all tax classes.

        Returns:
            List of tax class data
        """
        try:
            data = await self._request("GET", "taxes/classes")
            return data if isinstance(data, list) else []
        except (ConnectorAPIError, OSError) as e:
            logger.error("Failed to get tax classes: %s", e)
            return []

    async def get_tax_rates(self, per_page: int = 100) -> AsyncIterator[dict[str, Any]]:
        """Get tax rates.

        Args:
            per_page: Page size

        Yields:
            Tax rate data dictionaries
        """
        params: dict[str, Any] = {"per_page": per_page, "page": 1}

        for _page in range(_MAX_PAGES):
            data = await self._request("GET", "taxes", params=params)

            if not data:
                break

            for rate in data:
                yield rate

            if len(data) < per_page:
                break

            params["page"] += 1
        else:
            logger.warning("Pagination safety cap reached for tax rates")

    # =========================================================================
    # Reports
    # =========================================================================

    async def get_sales_report(
        self,
        period: str = "month",
        date_min: str | None = None,
        date_max: str | None = None,
    ) -> dict[str, Any]:
        """Get sales report.

        Args:
            period: Report period (week, month, last_month, year)
            date_min: Start date (YYYY-MM-DD)
            date_max: End date (YYYY-MM-DD)

        Returns:
            Sales report data
        """
        params: dict[str, Any] = {"period": period}
        if date_min:
            params["date_min"] = date_min
        if date_max:
            params["date_max"] = date_max

        try:
            data = await self._request("GET", "reports/sales", params=params)
            return data[0] if isinstance(data, list) and data else {}
        except (ConnectorAPIError, OSError) as e:
            logger.error("Failed to get sales report: %s", e)
            return {}

    async def get_top_sellers_report(
        self,
        period: str = "month",
    ) -> list[dict[str, Any]]:
        """Get top selling products report.

        Args:
            period: Report period (week, month, last_month, year)

        Returns:
            List of top selling product data
        """
        try:
            data = await self._request(
                "GET",
                "reports/top_sellers",
                params={"period": period},
            )
            return data if isinstance(data, list) else []
        except (ConnectorAPIError, OSError) as e:
            logger.error("Failed to get top sellers report: %s", e)
            return []

    # =========================================================================
    # BaseConnector abstract methods
    # =========================================================================

    async def search(
        self,
        query: str,
        limit: int = 10,
        **kwargs,
    ) -> list[Evidence]:
        """Search WooCommerce for relevant data.

        Searches across orders, products, and customers.

        Args:
            query: Search query string
            limit: Maximum results to return
            **kwargs: Additional search options (entity_type: str)

        Returns:
            List of Evidence objects
        """
        results: list[Evidence] = []
        entity_type = kwargs.get("entity_type", "all")

        try:
            # Search products
            if entity_type in ("all", "product"):
                params = {"search": query, "per_page": min(limit, 100)}
                products = await self._request("GET", "products", params=params)
                for p in products[:limit]:
                    results.append(
                        Evidence(
                            id=f"woo-product-{p['id']}",
                            source_type=self.source_type,
                            source_id=str(p["id"]),
                            content=f"{p['name']}: {p.get('short_description', '')}",
                            title=p["name"],
                            url=p.get("permalink"),
                            metadata={"type": "product", "sku": p.get("sku")},
                        )
                    )

            # Search customers
            if entity_type in ("all", "customer"):
                params = {"search": query, "per_page": min(limit, 100)}
                customers = await self._request("GET", "customers", params=params)
                for c in customers[:limit]:
                    results.append(
                        Evidence(
                            id=f"woo-customer-{c['id']}",
                            source_type=self.source_type,
                            source_id=str(c["id"]),
                            content=f"{c.get('first_name', '')} {c.get('last_name', '')} - {c.get('email', '')}",
                            title=f"Customer: {c.get('email', 'unknown')}",
                            metadata={"type": "customer"},
                        )
                    )

        except (ConnectorAPIError, OSError, KeyError) as e:
            logger.error("Search failed: %s", e)

        return results[:limit]

    async def fetch(self, evidence_id: str) -> Evidence | None:
        """Fetch a specific piece of evidence by ID.

        Args:
            evidence_id: Evidence ID (format: woo-{type}-{id})

        Returns:
            Evidence object or None if not found
        """
        try:
            parts = evidence_id.split("-")
            if len(parts) < 3 or parts[0] != "woo":
                return None

            entity_type = parts[1]
            entity_id = parts[2]

            if entity_type == "order":
                order = await self.get_order(int(entity_id))
                if order:
                    return Evidence(
                        id=evidence_id,
                        source_type=self.source_type,
                        source_id=str(order.id),
                        content=f"Order #{order.number} - {order.status.value} - ${order.total}",
                        title=f"Order #{order.number}",
                        metadata={"type": "order", "data": order.to_dict()},
                    )

            elif entity_type == "product":
                product = await self.get_product(int(entity_id))
                if product:
                    return Evidence(
                        id=evidence_id,
                        source_type=self.source_type,
                        source_id=str(product.id),
                        content=f"{product.name}: {product.description or ''}",
                        title=product.name,
                        metadata={"type": "product", "data": product.to_dict()},
                    )

            elif entity_type == "customer":
                data = await self._request("GET", f"customers/{entity_id}")
                customer = self._parse_customer(data)
                return Evidence(
                    id=evidence_id,
                    source_type=self.source_type,
                    source_id=str(customer.id),
                    content=f"{customer.first_name} {customer.last_name} - {customer.email}",
                    title=f"Customer: {customer.email}",
                    metadata={"type": "customer", "data": customer.to_dict()},
                )

        except (ConnectorAPIError, OSError, ValueError, KeyError) as e:
            logger.error("Failed to fetch %s: %s", evidence_id, e)

        return None

    # =========================================================================
    # EnterpriseConnector implementation
    # =========================================================================

    async def incremental_sync(
        self,
        state: SyncState | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Perform incremental sync of WooCommerce data.

        Args:
            state: Previous sync state

        Yields:
            Data items as dictionaries
        """
        since = state.last_sync_at if state else None

        # Sync orders
        async for order in self.sync_orders(since=since):
            yield {"type": "order", "data": order.to_dict()}

        # Sync products
        async for product in self.sync_products(since=since):
            yield {"type": "product", "data": product.to_dict()}

        # Sync customers
        async for customer in self.sync_customers(since=since):
            yield {"type": "customer", "data": customer.to_dict()}

    async def full_sync(self) -> SyncResult:
        """Perform full sync of WooCommerce data."""
        start_time = datetime.now(timezone.utc)
        items_synced = 0
        errors: list[str] = []

        try:
            async for _ in self.incremental_sync():
                items_synced += 1
        except (ConnectorAPIError, OSError, ValueError, KeyError) as e:
            errors.append(str(e))

        duration = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

        return SyncResult(
            connector_id=self.name,
            success=len(errors) == 0,
            items_synced=items_synced,
            items_updated=0,
            items_skipped=0,
            items_failed=len(errors),
            duration_ms=duration,
            errors=errors,
        )

    # =========================================================================
    # Webhooks (delegated to webhooks module)
    # =========================================================================

    async def get_webhooks(self) -> list[dict[str, Any]]:
        """Get all registered webhooks.

        Returns:
            List of webhook data
        """
        from aragora.connectors.ecommerce.woocommerce.webhooks import get_webhooks

        return await get_webhooks(self)

    async def create_webhook(
        self,
        name: str,
        topic: str,
        delivery_url: str,
        secret: str = "",
        status: str = "active",
    ) -> dict[str, Any] | None:
        """Register a new webhook.

        Args:
            name: Webhook name
            topic: Event topic (e.g., order.created, product.updated)
            delivery_url: URL to receive webhook payloads
            secret: Secret for payload signing
            status: Webhook status (active, paused, disabled)

        Returns:
            Created webhook data or None on failure
        """
        from aragora.connectors.ecommerce.woocommerce.webhooks import create_webhook

        return await create_webhook(self, name, topic, delivery_url, secret, status)

    async def delete_webhook(self, webhook_id: int, force: bool = True) -> bool:
        """Delete a webhook.

        Args:
            webhook_id: Webhook ID (must be alphanumeric)
            force: Permanently delete

        Returns:
            True if successful

        Raises:
            ConnectorValidationError: If webhook_id contains invalid characters
        """
        from aragora.connectors.ecommerce.woocommerce.webhooks import delete_webhook

        return await delete_webhook(self, webhook_id, force)

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
        secret: str | None = None,
    ) -> bool:
        """Verify webhook payload signature.

        WooCommerce uses base64-encoded HMAC-SHA256 signatures.
        Override parent to handle WooCommerce's signature format.

        Args:
            payload: Raw webhook payload bytes
            signature: X-WC-Webhook-Signature header value
            secret: Webhook secret (optional, uses get_webhook_secret() if not provided)

        Returns:
            True if signature is valid
        """
        from aragora.connectors.ecommerce.woocommerce.webhooks import verify_webhook_signature

        return verify_webhook_signature(payload, signature, secret, self.get_webhook_secret)

    # =========================================================================
    # Knowledge Mound sync (delegated to sync module)
    # =========================================================================

    async def sync_items(
        self,
        state: SyncState,
        batch_size: int = 100,
    ) -> AsyncIterator[SyncItem]:
        """Sync items from WooCommerce for Knowledge Mound.

        Args:
            state: Sync state with cursor/timestamp
            batch_size: Number of items per batch

        Yields:
            SyncItem objects for orders, products, customers
        """
        from aragora.connectors.ecommerce.woocommerce.sync import sync_items_from_connector

        async for item in sync_items_from_connector(self, state, batch_size):
            yield item


__all__ = [
    "WooCommerceConnector",
]
