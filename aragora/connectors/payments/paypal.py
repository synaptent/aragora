"""
PayPal Payment Connector.

Full integration with PayPal REST API:
- Orders (create, capture, authorize)
- Payments (captures, refunds)
- Subscriptions (billing agreements)
- Payouts (mass payments)
- Webhooks for real-time notifications
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, TYPE_CHECKING

from aragora.resilience import get_circuit_breaker

if TYPE_CHECKING:
    import httpx
    from aragora.resilience import CircuitBreaker

logger = logging.getLogger(__name__)

# =============================================================================
# Enums
# =============================================================================


class PayPalEnvironment(str, Enum):
    """PayPal environment."""

    SANDBOX = "sandbox"
    LIVE = "live"


class OrderStatus(str, Enum):
    """PayPal order status."""

    CREATED = "CREATED"
    SAVED = "SAVED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"
    COMPLETED = "COMPLETED"
    PAYER_ACTION_REQUIRED = "PAYER_ACTION_REQUIRED"


class OrderIntent(str, Enum):
    """PayPal order intent."""

    CAPTURE = "CAPTURE"
    AUTHORIZE = "AUTHORIZE"


class CaptureStatus(str, Enum):
    """PayPal capture status."""

    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    PENDING = "PENDING"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class RefundStatus(str, Enum):
    """PayPal refund status."""

    CANCELLED = "CANCELLED"
    FAILED = "FAILED"
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class SubscriptionStatus(str, Enum):
    """PayPal subscription status."""

    APPROVAL_PENDING = "APPROVAL_PENDING"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PayoutBatchStatus(str, Enum):
    """PayPal payout batch status."""

    DENIED = "DENIED"
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    CANCELED = "CANCELED"


# =============================================================================
# Credentials
# =============================================================================


@dataclass
class PayPalCredentials:
    """PayPal API credentials."""

    client_id: str
    client_secret: str
    environment: PayPalEnvironment = PayPalEnvironment.SANDBOX
    webhook_id: str | None = None  # For webhook verification
    webhook_secret: str | None = None  # HMAC secret for signature verification

    @property
    def base_url(self) -> str:
        """Get base URL for environment."""
        if self.environment == PayPalEnvironment.LIVE:
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"

    @classmethod
    def from_env(cls, prefix: str = "PAYPAL_") -> PayPalCredentials:
        """Load credentials from environment variables."""
        import os

        client_id = os.environ.get(f"{prefix}CLIENT_ID", "")
        client_secret = os.environ.get(f"{prefix}CLIENT_SECRET", "")
        environment = os.environ.get(f"{prefix}ENVIRONMENT", "sandbox").lower()
        webhook_id = os.environ.get(f"{prefix}WEBHOOK_ID")
        webhook_secret = os.environ.get(f"{prefix}WEBHOOK_SECRET")

        if not client_id or not client_secret:
            raise ValueError(f"Missing {prefix}CLIENT_ID or {prefix}CLIENT_SECRET")

        return cls(
            client_id=client_id,
            client_secret=client_secret,
            environment=PayPalEnvironment(environment),
            webhook_id=webhook_id,
            webhook_secret=webhook_secret,
        )


# =============================================================================
# Error Handling
# =============================================================================


class PayPalError(Exception):
    """PayPal API error."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        error_name: str | None = None,
        debug_id: str | None = None,
        details: list[dict[str, Any]] | None = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_name = error_name
        self.debug_id = debug_id
        self.details = details or []


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class Money:
    """PayPal money amount."""

    currency_code: str
    value: str  # String to preserve precision

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Money:
        return cls(
            currency_code=data.get("currency_code", "USD"),
            value=data.get("value", "0.00"),
        )

    def to_api(self) -> dict[str, str]:
        return {"currency_code": self.currency_code, "value": self.value}

    @classmethod
    def usd(cls, amount: float) -> Money:
        return cls(currency_code="USD", value=f"{amount:.2f}")


@dataclass
class PayerName:
    """Payer name."""

    given_name: str | None = None
    surname: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PayerName:
        return cls(
            given_name=data.get("given_name"),
            surname=data.get("surname"),
        )

    @property
    def full_name(self) -> str:
        parts = [p for p in [self.given_name, self.surname] if p]
        return " ".join(parts)


@dataclass
class Payer:
    """PayPal payer information."""

    payer_id: str | None = None
    email_address: str | None = None
    name: PayerName | None = None
    phone: str | None = None
    birth_date: str | None = None
    address: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Payer:
        name_data = data.get("name")
        return cls(
            payer_id=data.get("payer_id"),
            email_address=data.get("email_address"),
            name=PayerName.from_api(name_data) if name_data else None,
            phone=data.get("phone", {}).get("phone_number", {}).get("national_number"),
            birth_date=data.get("birth_date"),
            address=data.get("address"),
        )


@dataclass
class PurchaseUnit:
    """PayPal purchase unit (item group)."""

    reference_id: str | None = None
    description: str | None = None
    custom_id: str | None = None
    invoice_id: str | None = None
    soft_descriptor: str | None = None
    amount: Money | None = None
    items: list[dict[str, Any]] = field(default_factory=list)
    shipping: dict[str, Any] | None = None
    payments: dict[str, Any] | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PurchaseUnit:
        amount_data = data.get("amount")
        return cls(
            reference_id=data.get("reference_id"),
            description=data.get("description"),
            custom_id=data.get("custom_id"),
            invoice_id=data.get("invoice_id"),
            soft_descriptor=data.get("soft_descriptor"),
            amount=Money.from_api(amount_data) if amount_data else None,
            items=data.get("items", []),
            shipping=data.get("shipping"),
            payments=data.get("payments"),
        )

    def to_api(self) -> dict[str, Any]:
        result: dict[str, Any] = {}

        if self.reference_id:
            result["reference_id"] = self.reference_id
        if self.description:
            result["description"] = self.description
        if self.custom_id:
            result["custom_id"] = self.custom_id
        if self.invoice_id:
            result["invoice_id"] = self.invoice_id
        if self.soft_descriptor:
            result["soft_descriptor"] = self.soft_descriptor
        if self.amount:
            result["amount"] = self.amount.to_api()
        if self.items:
            result["items"] = self.items
        if self.shipping:
            result["shipping"] = self.shipping

        return result


@dataclass
class Order:
    """PayPal order."""

    id: str
    status: OrderStatus
    intent: OrderIntent = OrderIntent.CAPTURE
    purchase_units: list[PurchaseUnit] = field(default_factory=list)
    payer: Payer | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None
    links: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Order:
        return cls(
            id=data["id"],
            status=OrderStatus(data.get("status", "CREATED")),
            intent=OrderIntent(data.get("intent", "CAPTURE")),
            purchase_units=[PurchaseUnit.from_api(pu) for pu in data.get("purchase_units", [])],
            payer=Payer.from_api(data["payer"]) if data.get("payer") else None,
            create_time=_parse_datetime(data.get("create_time")),
            update_time=_parse_datetime(data.get("update_time")),
            links=data.get("links", []),
        )

    def get_approve_link(self) -> str | None:
        """Get the approval URL for the payer."""
        for link in self.links:
            if link.get("rel") == "approve":
                return link.get("href")
        return None


@dataclass
class Capture:
    """PayPal capture (completed payment)."""

    id: str
    status: CaptureStatus
    amount: Money | None = None
    final_capture: bool = True
    seller_protection: dict[str, Any] | None = None
    seller_receivable_breakdown: dict[str, Any] | None = None
    invoice_id: str | None = None
    custom_id: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Capture:
        amount_data = data.get("amount")
        return cls(
            id=data["id"],
            status=CaptureStatus(data.get("status", "PENDING")),
            amount=Money.from_api(amount_data) if amount_data else None,
            final_capture=data.get("final_capture", True),
            seller_protection=data.get("seller_protection"),
            seller_receivable_breakdown=data.get("seller_receivable_breakdown"),
            invoice_id=data.get("invoice_id"),
            custom_id=data.get("custom_id"),
            create_time=_parse_datetime(data.get("create_time")),
            update_time=_parse_datetime(data.get("update_time")),
        )


@dataclass
class Refund:
    """PayPal refund."""

    id: str
    status: RefundStatus
    amount: Money | None = None
    invoice_id: str | None = None
    note_to_payer: str | None = None
    seller_payable_breakdown: dict[str, Any] | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Refund:
        amount_data = data.get("amount")
        return cls(
            id=data["id"],
            status=RefundStatus(data.get("status", "PENDING")),
            amount=Money.from_api(amount_data) if amount_data else None,
            invoice_id=data.get("invoice_id"),
            note_to_payer=data.get("note_to_payer"),
            seller_payable_breakdown=data.get("seller_payable_breakdown"),
            create_time=_parse_datetime(data.get("create_time")),
            update_time=_parse_datetime(data.get("update_time")),
        )


@dataclass
class BillingPlan:
    """PayPal billing plan (subscription template)."""

    id: str
    name: str
    description: str | None = None
    status: str = "ACTIVE"
    product_id: str | None = None
    billing_cycles: list[dict[str, Any]] = field(default_factory=list)
    payment_preferences: dict[str, Any] | None = None
    taxes: dict[str, Any] | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BillingPlan:
        return cls(
            id=data["id"],
            name=data.get("name", ""),
            description=data.get("description"),
            status=data.get("status", "ACTIVE"),
            product_id=data.get("product_id"),
            billing_cycles=data.get("billing_cycles", []),
            payment_preferences=data.get("payment_preferences"),
            taxes=data.get("taxes"),
            create_time=_parse_datetime(data.get("create_time")),
            update_time=_parse_datetime(data.get("update_time")),
        )


@dataclass
class Subscription:
    """PayPal subscription."""

    id: str
    status: SubscriptionStatus
    plan_id: str
    start_time: datetime | None = None
    quantity: str = "1"
    shipping_amount: Money | None = None
    subscriber: dict[str, Any] | None = None
    billing_info: dict[str, Any] | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None
    links: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Subscription:
        shipping_data = data.get("shipping_amount")
        return cls(
            id=data["id"],
            status=SubscriptionStatus(data.get("status", "APPROVAL_PENDING")),
            plan_id=data.get("plan_id", ""),
            start_time=_parse_datetime(data.get("start_time")),
            quantity=data.get("quantity", "1"),
            shipping_amount=Money.from_api(shipping_data) if shipping_data else None,
            subscriber=data.get("subscriber"),
            billing_info=data.get("billing_info"),
            create_time=_parse_datetime(data.get("create_time")),
            update_time=_parse_datetime(data.get("update_time")),
            links=data.get("links", []),
        )

    def get_approve_link(self) -> str | None:
        """Get the approval URL for the subscriber."""
        for link in self.links:
            if link.get("rel") == "approve":
                return link.get("href")
        return None


@dataclass
class PayoutItem:
    """Single payout recipient."""

    recipient_type: str  # EMAIL, PHONE, PAYPAL_ID
    receiver: str
    amount: Money
    note: str | None = None
    sender_item_id: str | None = None

    def to_api(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "recipient_type": self.recipient_type,
            "receiver": self.receiver,
            "amount": self.amount.to_api(),
        }
        if self.note:
            result["note"] = self.note
        if self.sender_item_id:
            result["sender_item_id"] = self.sender_item_id
        return result


@dataclass
class PayoutBatch:
    """PayPal payout batch."""

    batch_id: str
    batch_status: PayoutBatchStatus
    sender_batch_id: str | None = None
    time_created: datetime | None = None
    time_completed: datetime | None = None
    amount: Money | None = None
    fees: Money | None = None
    items: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PayoutBatch:
        batch_header = data.get("batch_header", {})
        amount_data = batch_header.get("amount")
        fees_data = batch_header.get("fees")

        return cls(
            batch_id=batch_header.get("payout_batch_id", ""),
            batch_status=PayoutBatchStatus(batch_header.get("batch_status", "PENDING")),
            sender_batch_id=batch_header.get("sender_batch_header", {}).get("sender_batch_id"),
            time_created=_parse_datetime(batch_header.get("time_created")),
            time_completed=_parse_datetime(batch_header.get("time_completed")),
            amount=Money.from_api(amount_data) if amount_data else None,
            fees=Money.from_api(fees_data) if fees_data else None,
            items=data.get("items", []),
        )


# =============================================================================
# Helper Functions
# =============================================================================


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime from API response."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# =============================================================================
# PayPal Client
# =============================================================================


class PayPalClient:
    """
    PayPal REST API client.

    Provides full access to PayPal payments including:
    - Orders (create, capture, authorize)
    - Captures and refunds
    - Subscriptions (recurring billing)
    - Payouts (mass payments)
    - Webhook verification

    Example:
        async with PayPalClient(credentials) as client:
            # Create an order
            order = await client.create_order(
                amount=Money.usd(99.99),
                description="Premium subscription",
            )

            # Redirect user to order.get_approve_link()
            # After approval, capture the payment
            capture = await client.capture_order(order.id)
    """

    def __init__(
        self,
        credentials: PayPalCredentials,
        circuit_breaker: CircuitBreaker | None = None,
        enable_circuit_breaker: bool = True,
    ):
        self.credentials = credentials
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._token_expires_at: datetime | None = None
        self._circuit_breaker = circuit_breaker
        self._enable_circuit_breaker = enable_circuit_breaker

        # Initialize circuit breaker with payment-appropriate settings
        if self._circuit_breaker is None and self._enable_circuit_breaker:
            self._circuit_breaker = get_circuit_breaker(
                "paypal_client",
                failure_threshold=3,  # Fail fast for payment operations
                cooldown_seconds=120,  # Longer recovery for payment APIs
            )

    async def __aenter__(self) -> PayPalClient:
        import httpx

        self._client = httpx.AsyncClient(
            base_url=self.credentials.base_url,
            timeout=httpx.Timeout(30.0),
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_access_token(self) -> str:
        """Get or refresh OAuth2 access token."""
        # Check if current token is still valid
        if self._access_token and self._token_expires_at:
            if datetime.now(timezone.utc) < self._token_expires_at:
                return self._access_token

        if not self._client:
            raise RuntimeError("Client not initialized")

        # Get new token
        auth = base64.b64encode(
            f"{self.credentials.client_id}:{self.credentials.client_secret}".encode()
        ).decode()

        response = await self._client.post(
            "/v1/oauth2/token",
            data={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        if response.status_code != 200:
            raise PayPalError(
                message="Failed to obtain access token",
                status_code=response.status_code,
            )

        data = response.json()
        self._access_token = data["access_token"]

        # Set expiration with 5-minute buffer
        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        from datetime import timedelta

        self._token_expires_at += timedelta(seconds=expires_in - 300)

        return self._access_token

    async def _ensure_valid_token(self) -> str:
        """Ensure a valid access token is available (test hook)."""
        return await self._get_access_token()

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Make authenticated API request."""
        # Check circuit breaker before making request
        if self._circuit_breaker is not None and not self._circuit_breaker.can_proceed():
            cooldown = self._circuit_breaker.cooldown_remaining()
            raise PayPalError(
                message=f"Circuit breaker open. Retry after {cooldown:.1f}s",
                status_code=503,
                error_name="CIRCUIT_BREAKER_OPEN",
            )

        if not self._client:
            raise RuntimeError("Client not initialized. Use async context manager.")

        access_token = await self._get_access_token()

        request_headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        if headers:
            request_headers.update(headers)

        try:
            response = await self._client.request(
                method,
                endpoint,
                json=json,
                params=params,
                headers=request_headers,
            )
        except (OSError, ConnectionError, TimeoutError, RuntimeError) as e:
            # Record failure for network errors
            if self._circuit_breaker is not None:
                self._circuit_breaker.record_failure()
            raise PayPalError(message=f"HTTP error: {e}", status_code=503) from e

        if response.status_code >= 400:
            error_data = response.json() if response.content else {}
            # Record failure for server errors (5xx) or rate limits
            if response.status_code >= 500 or response.status_code == 429:
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure()
            raise PayPalError(
                message=error_data.get("message", f"HTTP {response.status_code}"),
                status_code=response.status_code,
                error_name=error_data.get("name"),
                debug_id=error_data.get("debug_id"),
                details=error_data.get("details", []),
            )

        # Record success
        if self._circuit_breaker is not None:
            self._circuit_breaker.record_success()

        if response.status_code == 204 or not response.content:
            return {}

        return response.json()

    # -------------------------------------------------------------------------
    # Orders
    # -------------------------------------------------------------------------

    async def create_order(
        self,
        amount: Money | str | float,
        currency: str | None = None,
        intent: OrderIntent = OrderIntent.CAPTURE,
        description: str | None = None,
        reference_id: str | None = None,
        custom_id: str | None = None,
        invoice_id: str | None = None,
        items: list[dict[str, Any]] | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
        idempotency_key: str | None = None,
    ) -> Order:
        """
        Create a new order.

        Args:
            amount: Order amount
            currency: Currency code when amount is not a Money instance
            intent: CAPTURE or AUTHORIZE
            description: Order description
            reference_id: Purchase unit reference ID
            custom_id: Your custom ID
            invoice_id: Your invoice ID
            items: Line items
            return_url: URL to return after approval
            cancel_url: URL for cancelled orders
            idempotency_key: Optional idempotency key for safe retries

        Returns:
            Created Order with approval link
        """
        if isinstance(amount, Money):
            money = amount
        else:
            currency_code = currency or "USD"
            if isinstance(amount, (int, float)):
                value = f"{amount:.2f}"
            else:
                value = str(amount)
            money = Money(currency_code=currency_code, value=value)

        purchase_unit: dict[str, Any] = {
            "amount": money.to_api(),
        }

        if reference_id:
            purchase_unit["reference_id"] = reference_id
        if description:
            purchase_unit["description"] = description
        if custom_id:
            purchase_unit["custom_id"] = custom_id
        if invoice_id:
            purchase_unit["invoice_id"] = invoice_id
        if items:
            purchase_unit["items"] = items

        body: dict[str, Any] = {
            "intent": intent.value,
            "purchase_units": [purchase_unit],
        }

        if return_url and cancel_url:
            body["application_context"] = {
                "return_url": return_url,
                "cancel_url": cancel_url,
            }

        headers = {"PayPal-Request-Id": idempotency_key} if idempotency_key else None
        data = await self._request("POST", "/v2/checkout/orders", json=body, headers=headers)
        return Order.from_api(data)

    async def get_order(self, order_id: str) -> Order:
        """Get order details."""
        data = await self._request("GET", f"/v2/checkout/orders/{order_id}")
        return Order.from_api(data)

    async def capture_order(self, order_id: str) -> Order:
        """
        Capture an approved order.

        Call this after the payer approves the order.
        """
        data = await self._request(
            "POST",
            f"/v2/checkout/orders/{order_id}/capture",
            headers={"Prefer": "return=representation"},
        )
        return Order.from_api(data)

    async def authorize_order(self, order_id: str) -> Order:
        """
        Authorize an approved order.

        Use this for delayed capture scenarios.
        """
        data = await self._request(
            "POST",
            f"/v2/checkout/orders/{order_id}/authorize",
            headers={"Prefer": "return=representation"},
        )
        return Order.from_api(data)

    # -------------------------------------------------------------------------
    # Captures & Refunds
    # -------------------------------------------------------------------------

    async def get_capture(self, capture_id: str) -> Capture:
        """Get capture details."""
        data = await self._request("GET", f"/v2/payments/captures/{capture_id}")
        return Capture.from_api(data)

    async def refund_capture(
        self,
        capture_id: str,
        amount: Money | str | float | None = None,
        currency: str | None = None,
        invoice_id: str | None = None,
        note_to_payer: str | None = None,
    ) -> Refund:
        """
        Refund a captured payment.

        Args:
            capture_id: Capture to refund
            amount: Refund amount (full refund if not specified)
            currency: Currency code when amount is not a Money instance
            invoice_id: Your invoice ID
            note_to_payer: Message to the payer

        Returns:
            Refund details
        """
        body: dict[str, Any] = {}

        if amount is not None:
            if isinstance(amount, Money):
                money = amount
            else:
                currency_code = currency or "USD"
                if isinstance(amount, (int, float)):
                    value = f"{amount:.2f}"
                else:
                    value = str(amount)
                money = Money(currency_code=currency_code, value=value)
            body["amount"] = money.to_api()
        if invoice_id:
            body["invoice_id"] = invoice_id
        if note_to_payer:
            body["note_to_payer"] = note_to_payer

        data = await self._request(
            "POST",
            f"/v2/payments/captures/{capture_id}/refund",
            json=body if body else None,
        )
        return Refund.from_api(data)

    async def get_refund(self, refund_id: str) -> Refund:
        """Get refund details."""
        data = await self._request("GET", f"/v2/payments/refunds/{refund_id}")
        return Refund.from_api(data)

    # -------------------------------------------------------------------------
    # Subscriptions
    # -------------------------------------------------------------------------

    async def create_product(
        self,
        name: str,
        description: str | None = None,
        type: str = "SERVICE",
        category: str = "SOFTWARE",
    ) -> dict[str, Any]:
        """Create a product (required for subscriptions)."""
        body: dict[str, Any] = {
            "name": name,
            "type": type,
            "category": category,
        }
        if description:
            body["description"] = description

        return await self._request("POST", "/v1/catalogs/products", json=body)

    async def create_plan(
        self,
        product_id: str,
        name: str,
        billing_cycles: list[dict[str, Any]],
        payment_preferences: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> BillingPlan:
        """
        Create a billing plan for subscriptions.

        Args:
            product_id: Product ID
            name: Plan name
            billing_cycles: Billing cycle definitions
            payment_preferences: Setup fee, auto-bill, etc.
            description: Plan description

        Example billing_cycles:
            [
                {
                    "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                    "tenure_type": "REGULAR",
                    "sequence": 1,
                    "total_cycles": 0,  # Unlimited
                    "pricing_scheme": {
                        "fixed_price": {"value": "9.99", "currency_code": "USD"}
                    }
                }
            ]
        """
        body: dict[str, Any] = {
            "product_id": product_id,
            "name": name,
            "billing_cycles": billing_cycles,
        }

        if payment_preferences:
            body["payment_preferences"] = payment_preferences
        else:
            body["payment_preferences"] = {
                "auto_bill_outstanding": True,
                "payment_failure_threshold": 3,
            }

        if description:
            body["description"] = description

        data = await self._request("POST", "/v1/billing/plans", json=body)
        return BillingPlan.from_api(data)

    async def get_plan(self, plan_id: str) -> BillingPlan:
        """Get billing plan details."""
        data = await self._request("GET", f"/v1/billing/plans/{plan_id}")
        return BillingPlan.from_api(data)

    async def list_plans(
        self,
        product_id: str | None = None,
        page_size: int = 20,
        page: int = 1,
    ) -> list[BillingPlan]:
        """List billing plans."""
        params: dict[str, Any] = {
            "page_size": page_size,
            "page": page,
        }
        if product_id:
            params["product_id"] = product_id

        data = await self._request("GET", "/v1/billing/plans", params=params)
        plans = data.get("plans", [])
        return [BillingPlan.from_api(p) for p in plans]

    async def create_subscription(
        self,
        plan_id: str,
        subscriber_email: str | None = None,
        subscriber_name: dict[str, str] | None = None,
        start_time: datetime | None = None,
        custom_id: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> Subscription:
        """
        Create a subscription.

        Args:
            plan_id: Billing plan ID
            subscriber_email: Subscriber email
            subscriber_name: {"given_name": "John", "surname": "Doe"}
            start_time: Subscription start time
            custom_id: Your custom ID
            return_url: URL after approval
            cancel_url: URL for cancellation

        Returns:
            Subscription with approval link
        """
        body: dict[str, Any] = {"plan_id": plan_id}

        if subscriber_email or subscriber_name:
            subscriber: dict[str, Any] = {}
            if subscriber_email:
                subscriber["email_address"] = subscriber_email
            if subscriber_name:
                subscriber["name"] = subscriber_name
            body["subscriber"] = subscriber

        if start_time:
            body["start_time"] = start_time.isoformat()

        if custom_id:
            body["custom_id"] = custom_id

        if return_url and cancel_url:
            body["application_context"] = {
                "return_url": return_url,
                "cancel_url": cancel_url,
            }

        data = await self._request("POST", "/v1/billing/subscriptions", json=body)
        return Subscription.from_api(data)

    async def get_subscription(self, subscription_id: str) -> Subscription:
        """Get subscription details."""
        data = await self._request("GET", f"/v1/billing/subscriptions/{subscription_id}")
        return Subscription.from_api(data)

    async def cancel_subscription(
        self,
        subscription_id: str,
        reason: str = "Cancelled by user",
    ) -> None:
        """Cancel a subscription."""
        await self._request(
            "POST",
            f"/v1/billing/subscriptions/{subscription_id}/cancel",
            json={"reason": reason},
        )

    async def suspend_subscription(
        self,
        subscription_id: str,
        reason: str = "Suspended by user",
    ) -> Subscription | None:
        """Suspend a subscription."""
        data = await self._request(
            "POST",
            f"/v1/billing/subscriptions/{subscription_id}/suspend",
            json={"reason": reason},
        )
        return Subscription.from_api(data) if data else None

    async def activate_subscription(
        self,
        subscription_id: str,
        reason: str = "Reactivating subscription",
    ) -> Subscription | None:
        """Reactivate a suspended subscription."""
        data = await self._request(
            "POST",
            f"/v1/billing/subscriptions/{subscription_id}/activate",
            json={"reason": reason},
        )
        return Subscription.from_api(data) if data else None

    # -------------------------------------------------------------------------
    # Payouts
    # -------------------------------------------------------------------------

    async def create_payout(
        self,
        items: list[PayoutItem],
        sender_batch_id: str,
        email_subject: str | None = None,
        email_message: str | None = None,
    ) -> PayoutBatch:
        """
        Create a payout batch.

        Args:
            items: List of payout recipients
            sender_batch_id: Your unique batch ID
            email_subject: Email subject for recipients
            email_message: Email message for recipients

        Returns:
            Payout batch details
        """
        sender_batch_header: dict[str, Any] = {
            "sender_batch_id": sender_batch_id,
        }

        if email_subject:
            sender_batch_header["email_subject"] = email_subject
        if email_message:
            sender_batch_header["email_message"] = email_message

        body = {
            "sender_batch_header": sender_batch_header,
            "items": [item.to_api() for item in items],
        }

        data = await self._request("POST", "/v1/payments/payouts", json=body)
        return PayoutBatch.from_api(data)

    async def get_payout(self, payout_batch_id: str) -> PayoutBatch:
        """Get payout batch details."""
        data = await self._request("GET", f"/v1/payments/payouts/{payout_batch_id}")
        return PayoutBatch.from_api(data)

    async def create_payout_batch(
        self,
        sender_batch_id: str,
        items: list[PayoutItem | dict[str, Any]],
        email_subject: str | None = None,
        email_message: str | None = None,
    ) -> PayoutBatch:
        """Convenience wrapper to create a payout batch from dicts or PayoutItems."""
        payout_items: list[PayoutItem] = []
        for item in items:
            if isinstance(item, PayoutItem):
                payout_items.append(item)
                continue
            amount_data = item.get("amount", {})
            money = (
                Money.from_api(amount_data)
                if isinstance(amount_data, dict)
                else Money(currency_code="USD", value=str(amount_data))
            )
            payout_items.append(
                PayoutItem(
                    recipient_type=item.get("recipient_type", ""),
                    receiver=item.get("receiver", ""),
                    amount=money,
                    note=item.get("note"),
                    sender_item_id=item.get("sender_item_id"),
                )
            )

        return await self.create_payout(
            items=payout_items,
            sender_batch_id=sender_batch_id,
            email_subject=email_subject,
            email_message=email_message,
        )

    async def get_payout_batch(self, payout_batch_id: str) -> PayoutBatch:
        """Convenience wrapper for payout batch lookup."""
        return await self.get_payout(payout_batch_id)

    # -------------------------------------------------------------------------
    # Webhooks
    # -------------------------------------------------------------------------

    def parse_webhook_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Parse and normalize a webhook payload."""
        return payload

    def verify_webhook_signature(
        self,
        payload: bytes | None = None,
        headers: dict[str, str] | None = None,
        *,
        transmission_id: str | None = None,
        timestamp: str | None = None,
        webhook_id: str | None = None,
        event_body: str | None = None,
        cert_url: str | None = None,
        auth_algo: str | None = None,
        actual_signature: str | None = None,
    ) -> bool:
        """
        Verify PayPal webhook signatures.

        Supports payload+headers (handler usage) or explicit transmission fields (tests).
        """
        # Uses hmac.compare_digest and CRC32 mask 0xFFFFFFFF in verification.
        if headers:
            lowered = {key.lower(): value for key, value in headers.items()}
            transmission_id = transmission_id or lowered.get("paypal-transmission-id", "")
            timestamp = timestamp or lowered.get("paypal-transmission-time", "")
            actual_signature = actual_signature or lowered.get("paypal-transmission-sig", "")
            cert_url = cert_url or lowered.get("paypal-cert-url", "")
            auth_algo = auth_algo or lowered.get("paypal-auth-algo", "")

        if payload is not None and event_body is None:
            if isinstance(payload, (bytes, bytearray)):
                event_body = payload.decode("utf-8")
            else:
                event_body = str(payload)

        transmission_id = transmission_id or ""
        timestamp = timestamp or ""
        webhook_id = webhook_id or (self.credentials.webhook_id or "")
        event_body = event_body or ""
        cert_url = cert_url or ""
        auth_algo = auth_algo or ""
        actual_signature = actual_signature or ""

        env = os.environ.get("ARAGORA_ENV", "production").lower()
        is_production = env not in ("development", "dev", "local", "test")

        # Check 1: Webhook ID must be configured in production
        if not self.credentials.webhook_id:
            if is_production:
                logger.error(
                    "SECURITY: PayPal webhook_id not configured in production. "
                    "Rejecting webhook to prevent signature bypass."
                )
                return False
            logger.warning("Webhook ID not configured, skipping verification (dev only)")
            return True

        # Check 2: Webhook ID must match
        if webhook_id != self.credentials.webhook_id:
            logger.warning(
                "SECURITY: PayPal webhook ID mismatch. Expected: %s..., Got: %s...",
                self.credentials.webhook_id[:8],
                webhook_id[:8] if webhook_id else "None",
            )
            return False

        # Check 3: Webhook secret must be configured in production
        if not self.credentials.webhook_secret:
            if is_production:
                logger.error(
                    "SECURITY: PayPal webhook_secret not configured in production. "
                    "Rejecting webhook to prevent signature bypass."
                )
                return False
            logger.warning(
                "Webhook secret not configured, skipping signature verification (dev only)"
            )
            return True

        # Check 4: Validate timestamp freshness (reject webhooks older than 5 minutes)
        try:
            ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            age_seconds = abs((datetime.now(timezone.utc) - ts).total_seconds())
            if age_seconds > 300:
                logger.warning(
                    "SECURITY: PayPal webhook timestamp too old: %.0fs. Possible replay attack.",
                    age_seconds,
                )
                return False
        except (ValueError, TypeError) as e:
            logger.warning("SECURITY: PayPal webhook timestamp invalid: %s", e)
            if is_production:
                return False

        # Check 5: Signature must be provided
        if not actual_signature:
            logger.warning("SECURITY: PayPal webhook signature is missing")
            return False

        # Check 6: Compute expected signature and compare (timing-safe)
        try:
            # Build the signature input string per PayPal spec
            # CRC32 should be unsigned (mask with 0xffffffff)
            crc = zlib.crc32(event_body.encode("utf-8")) & 0xFFFFFFFF
            expected_sig_input = f"{transmission_id}|{timestamp}|{webhook_id}|{crc}"

            # Compute HMAC-SHA256 signature
            expected_signature = base64.b64encode(
                hmac.new(
                    self.credentials.webhook_secret.encode("utf-8"),
                    expected_sig_input.encode("utf-8"),
                    hashlib.sha256,
                ).digest()
            ).decode("utf-8")

            # Timing-safe comparison to prevent timing attacks
            is_valid = hmac.compare_digest(expected_signature, actual_signature)

            if not is_valid:
                logger.warning(
                    "SECURITY: PayPal webhook signature mismatch. Transmission ID: %s",
                    transmission_id,
                )
                logger.debug("Signature verification failed. Input: %s...", expected_sig_input[:50])
            else:
                logger.debug(
                    "PayPal webhook signature verified successfully. Transmission ID: %s",
                    transmission_id,
                )

            return is_valid

        except (ValueError, TypeError, UnicodeDecodeError, OverflowError) as e:
            logger.error(
                "SECURITY: PayPal webhook signature verification failed with error: %s. Transmission ID: %s",
                e,
                transmission_id,
            )
            return False

    def _verify_webhook_internally(
        self,
        payload: bytes,
        transmission_id: str,
        transmission_time: str,
        transmission_sig: str,
        cert_url: str,
        auth_algo: str | None = None,
    ) -> bool:
        """Internal webhook verification used by tests/handlers."""
        event_body = (
            payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload)
        )

        is_valid = self._verify_webhook_signature_hmac(
            transmission_id=transmission_id,
            timestamp=transmission_time,
            webhook_id=self.credentials.webhook_id or "",
            event_body=event_body,
            cert_url=cert_url,
            auth_algo=auth_algo or "",
            actual_signature=transmission_sig,
        )

        if not is_valid:
            raise PayPalError(message="Signature verification failed", status_code=401)

        return True

    def _verify_webhook_signature_hmac(
        self,
        transmission_id: str,
        timestamp: str,
        webhook_id: str,
        event_body: str,
        cert_url: str,
        auth_algo: str,
        actual_signature: str,
    ) -> bool:
        """Compatibility wrapper for direct signature verification."""
        return self.verify_webhook_signature(
            transmission_id=transmission_id,
            timestamp=timestamp,
            webhook_id=webhook_id,
            event_body=event_body,
            cert_url=cert_url,
            auth_algo=auth_algo,
            actual_signature=actual_signature,
        )


# =============================================================================
# Mock Data Generators
# =============================================================================


def get_mock_order() -> Order:
    """Get a mock order for testing."""
    return Order(
        id="5O190127TN364715T",
        status=OrderStatus.CREATED,
        intent=OrderIntent.CAPTURE,
        purchase_units=[
            PurchaseUnit(
                reference_id="default",
                amount=Money.usd(100.00),
                description="Test order",
            )
        ],
        create_time=datetime.now(timezone.utc),
        links=[
            {
                "rel": "approve",
                "href": "https://www.sandbox.paypal.com/checkoutnow?token=5O190127TN364715T",
            },
        ],
    )


def get_mock_subscription() -> Subscription:
    """Get a mock subscription for testing."""
    return Subscription(
        id="I-BW452GLLEP1G",
        status=SubscriptionStatus.ACTIVE,
        plan_id="P-5ML4271244454362WXNWU5NQ",
        start_time=datetime.now(timezone.utc),
        subscriber={"email_address": "subscriber@example.com"},
        create_time=datetime.now(timezone.utc),
    )


def get_mock_capture() -> Capture:
    """Get a mock capture for testing."""
    return Capture(
        id="2GG279541U471931P",
        status=CaptureStatus.COMPLETED,
        amount=Money.usd(100.00),
        create_time=datetime.now(timezone.utc),
    )
