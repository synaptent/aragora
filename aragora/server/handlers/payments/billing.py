"""
Billing, invoicing, and subscription management handlers.

Provides HTTP endpoints for:
- Customer profile management (CRUD)
- Subscription management (create, read, update, cancel)
"""

from __future__ import annotations

import sys
from decimal import Decimal
from typing import Any
from uuid import uuid4

from aiohttp import web

from aragora.server.errors import safe_error_message
from aragora.server.handlers.utils import parse_json_body
from aragora.server.handlers.utils.aiohttp_responses import web_error_response
from aragora.observability.metrics import track_handler
from aragora.rbac.decorators import PermissionDeniedError, require_permission
from aragora.rbac.models import AuthorizationContext

from .handler import (
    PaymentProvider,
    _payment_write_limiter,
    _payment_read_limiter,
    PERM_CUSTOMER_CREATE,
    PERM_CUSTOMER_READ,
    PERM_CUSTOMER_UPDATE,
    PERM_CUSTOMER_DELETE,
    PERM_SUBSCRIPTION_CREATE,
    PERM_SUBSCRIPTION_READ,
    PERM_SUBSCRIPTION_UPDATE,
    PERM_SUBSCRIPTION_CANCEL,
    logger,
)


def _pkg():
    """Get the parent package module for runtime attribute lookup.

    This enables mock.patch at 'aragora.server.handlers.payments.X' to work
    correctly by resolving patchable names from the package namespace at call time,
    rather than using module-level imports that create local bindings.
    """
    return sys.modules[__package__]


def _coerce_request(
    request_or_context: Any, maybe_request: web.Request | None = None
) -> web.Request:
    """Support legacy (auth_context, request) handler signatures."""
    return maybe_request if maybe_request is not None else request_or_context


def _enforce_permission_if_context(
    context: Any, permission_key: str, resource_id: str | None = None
) -> None:
    """Fallback permission check when a raw AuthorizationContext is provided."""
    if isinstance(context, AuthorizationContext):
        # Resolve checker at runtime so tests can patch aragora.rbac.decorators.get_permission_checker.
        from aragora.rbac import decorators as rbac_decorators

        checker = rbac_decorators.get_permission_checker()
        decision = checker.check_permission(context, permission_key, resource_id)
        if not decision.allowed:
            logger.warning("Permission denied: %s", permission_key)
            raise PermissionDeniedError("Permission denied", decision)


# =============================================================================
# Customer Profile Handlers
# =============================================================================


@require_permission(PERM_CUSTOMER_CREATE)
@track_handler("payments/customer/create")
async def handle_create_customer(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    POST /api/payments/customer

    Create a customer profile.

    Request body:
    {
        "provider": "stripe" | "authorize_net",
        "email": "customer@example.com",
        "name": "John Doe",
        "merchant_customer_id": "cust_123",  // For Authorize.net
        "payment_method": {...}  // Optional
    }
    """
    _enforce_permission_if_context(request, PERM_CUSTOMER_CREATE)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for write operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        body, err = await parse_json_body(request, context="handle_create_customer")
        if err:
            return err
        if body is None:
            return web_error_response("Invalid request body", 400)
        provider = _pkg()._get_provider_from_request(request, body)

        email = body.get("email")
        name = body.get("name")

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            merchant_customer_id = body.get("merchant_customer_id", str(uuid4())[:12])

            async with connector:
                profile = await connector.create_customer_profile(
                    merchant_customer_id=merchant_customer_id,
                    email=email,
                    description=name,
                )

            return web.json_response(
                {
                    "success": True,
                    "customer_id": profile.profile_id,
                    "merchant_customer_id": profile.merchant_customer_id,
                }
            )
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            customer = await connector.create_customer(
                email=email,
                name=name,
                metadata=body.get("metadata", {}),
            )

            return web.json_response(
                {
                    "success": True,
                    "customer_id": customer.id,
                    "email": customer.email,
                }
            )

    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        logger.exception("Error creating customer: %s", e)
        return web_error_response(safe_error_message(e, "create customer"), 500)


@require_permission(PERM_CUSTOMER_READ)
@track_handler("payments/customer/read")
async def handle_get_customer(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    GET /api/payments/customer/{customer_id}

    Get customer profile.
    """
    _enforce_permission_if_context(request, PERM_CUSTOMER_READ)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for read operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_read_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        customer_id = request.match_info.get("customer_id")
        provider_str = request.query.get("provider", "stripe")

        if not customer_id:
            return web_error_response("Missing customer_id", 400)

        provider = (
            PaymentProvider.AUTHORIZE_NET
            if provider_str in ("authorize_net", "authnet")
            else PaymentProvider.STRIPE
        )

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            async with connector:
                profile = await connector.get_customer_profile(customer_id)

            if not profile:
                return web_error_response("Customer not found", 404)

            return web.json_response(
                {
                    "customer": {
                        "id": profile.profile_id,
                        "merchant_customer_id": profile.merchant_customer_id,
                        "email": profile.email,
                        "description": profile.description,
                        "payment_profiles": len(profile.payment_profiles or []),
                    }
                }
            )
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            customer = await connector.retrieve_customer(customer_id)

            return web.json_response(
                {
                    "customer": {
                        "id": customer.id,
                        "email": customer.email,
                        "name": customer.name,
                        "created": customer.created,
                        "metadata": customer.metadata,
                    }
                }
            )

    except (ConnectionError, TimeoutError, ValueError, KeyError, OSError) as e:
        logger.exception("Error getting customer: %s", e)
        return web_error_response(safe_error_message(e, "get customer"), 500)


@require_permission(PERM_CUSTOMER_DELETE)
@track_handler("payments/customer/delete")
async def handle_delete_customer(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    DELETE /api/payments/customer/{customer_id}

    Delete customer profile.
    """
    _enforce_permission_if_context(request, PERM_CUSTOMER_DELETE)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for write operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        customer_id = request.match_info.get("customer_id")
        provider_str = request.query.get("provider", "stripe")

        if not customer_id:
            return web_error_response("Missing customer_id", 400)

        provider = (
            PaymentProvider.AUTHORIZE_NET
            if provider_str in ("authorize_net", "authnet")
            else PaymentProvider.STRIPE
        )

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            async with connector:
                success = await connector.delete_customer_profile(customer_id)

            return web.json_response({"success": success})
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            result = await connector.delete_customer(customer_id)

            return web.json_response({"success": result.deleted})

    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        logger.exception("Error deleting customer: %s", e)
        return web_error_response(safe_error_message(e, "delete customer"), 500)


@require_permission(PERM_CUSTOMER_UPDATE)
@track_handler("payments/customer/update")
async def handle_update_customer(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    PUT /api/payments/customer/{customer_id}

    Update customer profile.

    Request body:
    {
        "provider": "stripe" | "authorize_net",
        "email": "new-email@example.com",  // Optional
        "name": "New Name",  // Optional
        "metadata": {}  // Optional, Stripe only
    }
    """
    _enforce_permission_if_context(request, PERM_CUSTOMER_UPDATE)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for write operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        customer_id = request.match_info.get("customer_id")
        if not customer_id:
            return web_error_response("Missing customer_id", 400)

        body, err = await parse_json_body(request, context="handle_update_customer")
        if err:
            return err
        if body is None:
            return web_error_response("Invalid request body", 400)
        provider = _pkg()._get_provider_from_request(request, body)

        email = body.get("email")
        name = body.get("name")
        metadata = body.get("metadata")

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            async with connector:
                success = await connector.update_customer_profile(
                    customer_profile_id=customer_id,
                    email=email,
                    description=name,
                )

            return web.json_response({"success": success})
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            update_params: dict[str, Any] = {}
            if email:
                update_params["email"] = email
            if name:
                update_params["name"] = name
            if metadata:
                update_params["metadata"] = metadata

            if not update_params:
                return web_error_response("No update parameters provided", 400)

            customer = await connector.update_customer(
                customer_id=customer_id,
                **update_params,
            )

            return web.json_response(
                {
                    "success": True,
                    "customer": {
                        "id": customer.id,
                        "email": customer.email,
                        "name": customer.name,
                    },
                }
            )

    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        logger.exception("Error updating customer: %s", e)
        return web_error_response(safe_error_message(e, "update customer"), 500)


# =============================================================================
# Subscription Handlers
# =============================================================================


@require_permission(PERM_SUBSCRIPTION_READ)
@track_handler("payments/subscription/read")
async def handle_get_subscription(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    GET /api/payments/subscription/{subscription_id}

    Get subscription details.
    """
    _enforce_permission_if_context(request, PERM_SUBSCRIPTION_READ)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for read operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_read_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        subscription_id = request.match_info.get("subscription_id")
        provider_str = request.query.get("provider", "stripe")

        if not subscription_id:
            return web_error_response("Missing subscription_id", 400)

        provider = (
            PaymentProvider.AUTHORIZE_NET
            if provider_str in ("authorize_net", "authnet")
            else PaymentProvider.STRIPE
        )

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            async with connector:
                subscription = await connector.get_subscription(subscription_id)

            if not subscription:
                return web_error_response("Subscription not found", 404)

            return web.json_response(
                {
                    "subscription": {
                        "id": subscription.subscription_id,
                        "name": subscription.name,
                        "status": subscription.status.value if subscription.status else "unknown",
                        "amount": str(subscription.amount) if subscription.amount else None,
                    }
                }
            )
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            subscription = await connector.retrieve_subscription(subscription_id)

            return web.json_response(
                {
                    "subscription": {
                        "id": subscription.id,
                        "status": subscription.status,
                        "current_period_start": subscription.current_period_start,
                        "current_period_end": subscription.current_period_end,
                        "customer": subscription.customer,
                        "items": [
                            {"price_id": item.price.id, "quantity": item.quantity}
                            for item in subscription.items.data
                        ]
                        if hasattr(subscription, "items") and subscription.items
                        else [],
                    }
                }
            )

    except (ConnectionError, TimeoutError, ValueError, KeyError, OSError) as e:
        logger.exception("Error getting subscription: %s", e)
        return web_error_response(safe_error_message(e, "get subscription"), 500)


@require_permission(PERM_SUBSCRIPTION_UPDATE)
@track_handler("payments/subscription/update")
async def handle_update_subscription(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    PUT /api/payments/subscription/{subscription_id}

    Update subscription.

    Request body:
    {
        "provider": "stripe" | "authorize_net",
        "name": "Updated Plan Name",  // Optional
        "amount": 149.99,  // Optional
        "price_id": "price_...",  // Stripe only, for plan changes
        "metadata": {}  // Stripe only
    }
    """
    _enforce_permission_if_context(request, PERM_SUBSCRIPTION_UPDATE)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for write operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        subscription_id = request.match_info.get("subscription_id")
        if not subscription_id:
            return web_error_response("Missing subscription_id", 400)

        body, err = await parse_json_body(request, context="handle_update_subscription")
        if err:
            return err
        if body is None:
            return web_error_response("Invalid request body", 400)
        provider = _pkg()._get_provider_from_request(request, body)

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            name = body.get("name")
            amount = body.get("amount")

            async with connector:
                success = await connector.update_subscription(
                    subscription_id=subscription_id,
                    name=name,
                    amount=Decimal(str(amount)) if amount else None,
                )

            return web.json_response({"success": success})
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            update_params: dict[str, Any] = {}
            if body.get("metadata"):
                update_params["metadata"] = body["metadata"]

            # Handle price/plan changes
            price_id = body.get("price_id")
            if price_id:
                # Get current subscription to find item ID
                current_sub = await connector.retrieve_subscription(subscription_id)
                if hasattr(current_sub, "items") and current_sub.items.data:
                    item_id = current_sub.items.data[0].id
                    update_params["items"] = [{"id": item_id, "price": price_id}]

            if not update_params:
                return web_error_response("No update parameters provided", 400)

            subscription = await connector.update_subscription(
                subscription_id=subscription_id,
                **update_params,
            )

            return web.json_response(
                {
                    "success": True,
                    "subscription": {
                        "id": subscription.id,
                        "status": subscription.status,
                    },
                }
            )

    except (ConnectionError, TimeoutError, ValueError, KeyError, OSError) as e:
        logger.exception("Error updating subscription: %s", e)
        return web_error_response(safe_error_message(e, "update subscription"), 500)


@require_permission(PERM_SUBSCRIPTION_CREATE)
@track_handler("payments/subscription/create")
async def handle_create_subscription(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    POST /api/payments/subscription

    Create a subscription.

    Request body:
    {
        "provider": "stripe" | "authorize_net",
        "customer_id": "cus_...",
        "name": "Premium Plan",
        "amount": 99.99,
        "interval": "month",
        "interval_count": 1,
        "start_date": "2025-02-01"  // Optional
    }
    """
    _enforce_permission_if_context(request, PERM_SUBSCRIPTION_CREATE)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for write operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        body, err = await parse_json_body(request, context="handle_create_subscription")
        if err:
            return err
        if body is None:
            return web_error_response("Invalid request body", 400)
        provider = _pkg()._get_provider_from_request(request, body)

        customer_id = body.get("customer_id")
        name = body.get("name", "Subscription")
        amount = Decimal(str(body.get("amount", 0)))
        interval = body.get("interval", "month")
        try:
            interval_count = int(body.get("interval_count", 1))
        except (ValueError, TypeError):
            return web_error_response("Invalid interval_count", 400)
        if interval_count < 1 or interval_count > 120:
            return web_error_response("interval_count must be between 1 and 120", 400)

        if not customer_id:
            return web_error_response("Missing customer_id", 400)
        if amount <= 0:
            return web_error_response("Amount must be greater than 0", 400)

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            # Map interval to Authorize.net interval unit (string: "days" or "months")
            interval_unit = "months" if interval == "month" else "days"

            async with connector:
                subscription = await connector.create_subscription(
                    name=name,
                    amount=amount,
                    interval_length=interval_count,
                    interval_unit=interval_unit,
                    customer_profile_id=customer_id,
                )

            return web.json_response(
                {
                    "success": True,
                    "subscription_id": subscription.subscription_id,
                    "name": subscription.name,
                    "status": subscription.status.value if subscription.status else "active",
                }
            )
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            # Create or get price
            price_id = body.get("price_id")
            if not price_id:
                # Create a price on the fly (simplified)
                return web.json_response(
                    {"error": "price_id required for Stripe subscriptions"}, status=400
                )

            subscription = await connector.create_subscription(
                customer=customer_id,
                items=[{"price": price_id}],
            )

            return web.json_response(
                {
                    "success": True,
                    "subscription_id": subscription.id,
                    "status": subscription.status,
                    "current_period_end": subscription.current_period_end,
                }
            )

    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        logger.exception("Error creating subscription: %s", e)
        return web_error_response(safe_error_message(e, "create subscription"), 500)


@require_permission(PERM_SUBSCRIPTION_CANCEL)
@track_handler("payments/subscription/cancel")
async def handle_cancel_subscription(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    DELETE /api/payments/subscription/{subscription_id}

    Cancel a subscription.
    """
    _enforce_permission_if_context(request, PERM_SUBSCRIPTION_CANCEL)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for write operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        subscription_id = request.match_info.get("subscription_id")
        provider_str = request.query.get("provider", "stripe")

        if not subscription_id:
            return web_error_response("Missing subscription_id", 400)

        provider = (
            PaymentProvider.AUTHORIZE_NET
            if provider_str in ("authorize_net", "authnet")
            else PaymentProvider.STRIPE
        )

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            async with connector:
                success = await connector.cancel_subscription(subscription_id)

            return web.json_response({"success": success})
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            subscription = await connector.cancel_subscription(subscription_id)

            return web.json_response(
                {
                    "success": subscription.status == "canceled",
                    "subscription_id": subscription.id,
                    "status": subscription.status,
                }
            )

    except (ConnectionError, TimeoutError, ValueError, OSError) as e:
        logger.exception("Error canceling subscription: %s", e)
        return web_error_response(safe_error_message(e, "cancel subscription"), 500)
