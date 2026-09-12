"""
Stripe-specific payment processing and webhook handling.

Provides HTTP endpoints for:
- POST /api/payments/charge (Stripe path)
- POST /api/payments/authorize (Stripe path)
- POST /api/payments/capture (Stripe path)
- POST /api/payments/refund (Stripe path)
- POST /api/payments/void (Stripe path)
- GET  /api/payments/transaction/{id} (Stripe path)
- POST /api/payments/webhook/stripe
- POST /api/payments/webhook/authnet
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from typing import Any

from aiohttp import web

from aragora.server.handlers.utils import parse_json_body
from aragora.server.handlers.utils.aiohttp_responses import web_error_response
from aragora.observability.metrics import track_handler
from aragora.rbac.decorators import PermissionDeniedError, require_permission
from aragora.rbac.models import AuthorizationContext

from .handler import (
    PaymentProvider,
    PaymentStatus,
    PaymentResult,
    _payment_write_limiter,
    _payment_read_limiter,
    _webhook_limiter,
    PERM_PAYMENTS_CHARGE,
    PERM_PAYMENTS_AUTHORIZE,
    PERM_PAYMENTS_CAPTURE,
    PERM_PAYMENTS_REFUND,
    PERM_PAYMENTS_VOID,
    PERM_PAYMENTS_READ,
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
# Payment Handlers
# =============================================================================


@require_permission(PERM_PAYMENTS_CHARGE)
@track_handler("payments/charge")
async def handle_charge(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    POST /api/payments/charge

    Process a payment charge.

    Request body:
    {
        "provider": "stripe" | "authorize_net",
        "amount": 100.00,
        "currency": "USD",
        "description": "Order #123",
        "customer_id": "cus_...",  // Optional for Stripe
        "payment_method": {
            "type": "card",
            "card_number": "4111111111111111",  // For Authorize.net
            "exp_month": "12",
            "exp_year": "2025",
            "cvv": "123"
        } | "pm_...",  // Payment method ID for Stripe
        "metadata": {}
    }
    """
    _enforce_permission_if_context(request, PERM_PAYMENTS_CHARGE)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for financial operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        body, err = await parse_json_body(request, context="handle_charge")
        if err:
            return err
        if body is None:
            return web_error_response("Invalid request body", 400)
        provider = _pkg()._get_provider_from_request(request, body)

        amount = Decimal(str(body.get("amount", 0)))
        if amount <= 0:
            return web.json_response(
                {"error": "Amount must be greater than 0"},
                status=400,
            )

        currency = body.get("currency", "USD")
        description = body.get("description")
        customer_id = body.get("customer_id")
        payment_method = body.get("payment_method")
        metadata = body.get("metadata", {})

        if provider == PaymentProvider.STRIPE:
            result = await _charge_stripe(
                request, amount, currency, description, customer_id, payment_method, metadata
            )
        else:
            result = await _charge_authnet(
                request, amount, currency, description, payment_method, metadata
            )

        return web.json_response(
            {
                "success": result.status == PaymentStatus.APPROVED,
                "transaction": result.to_dict(),
            }
        )

    except (ConnectionError, OSError) as e:
        logger.error("Connection error processing charge: %s", e)
        return web_error_response("Payment service temporarily unavailable", 503)
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Data error processing charge: %s", e)
        return web_error_response("Invalid payment data", 400)
    except (RuntimeError, TimeoutError, AttributeError) as e:
        logger.exception("Unexpected error processing charge: %s", e)
        return web_error_response("Internal payment error", 500)


async def _charge_stripe(
    request: web.Request,
    amount: Decimal,
    currency: str,
    description: str | None,
    customer_id: str | None,
    payment_method: Any,
    metadata: dict[str, Any],
) -> PaymentResult:
    """Process charge via Stripe."""
    connector = await _pkg().get_stripe_connector(request)
    if not connector:
        return PaymentResult(
            transaction_id="",
            provider=PaymentProvider.STRIPE,
            status=PaymentStatus.ERROR,
            amount=amount,
            currency=currency,
            message="Stripe connector not available",
        )

    try:
        # Convert amount to cents for Stripe
        amount_cents = int(amount * 100)

        intent = await _pkg()._resilient_stripe_call(
            "create_payment_intent",
            connector.create_payment_intent,
            amount=amount_cents,
            currency=currency.lower(),
            description=description,
            customer=customer_id,
            payment_method=payment_method if isinstance(payment_method, str) else None,
            metadata=metadata,
        )

        return PaymentResult(
            transaction_id=intent.id,
            provider=PaymentProvider.STRIPE,
            status=(
                PaymentStatus.APPROVED if intent.status == "succeeded" else PaymentStatus.PENDING
            ),
            amount=amount,
            currency=currency,
            message=f"Payment intent {intent.status}",
            metadata=(
                {"client_secret": intent.client_secret} if hasattr(intent, "client_secret") else {}
            ),
        )

    except ConnectionError as e:
        logger.error("Stripe connection error: %s", e)
        return PaymentResult(
            transaction_id="",
            provider=PaymentProvider.STRIPE,
            status=PaymentStatus.ERROR,
            amount=amount,
            currency=currency,
            message="Payment service temporarily unavailable",
        )
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Stripe data error: %s", e)
        return PaymentResult(
            transaction_id="",
            provider=PaymentProvider.STRIPE,
            status=PaymentStatus.ERROR,
            amount=amount,
            currency=currency,
            message="Invalid payment request",
        )
    except (RuntimeError, TimeoutError, AttributeError) as e:
        logger.exception("Unexpected Stripe error: %s", e)
        return PaymentResult(
            transaction_id="",
            provider=PaymentProvider.STRIPE,
            status=PaymentStatus.ERROR,
            amount=amount,
            currency=currency,
            message="Internal payment processing error",
        )


async def _charge_authnet(
    request: web.Request,
    amount: Decimal,
    currency: str,
    description: str | None,
    payment_method: Any,
    metadata: dict[str, Any],
) -> PaymentResult:
    """Process charge via Authorize.net."""
    connector = await _pkg().get_authnet_connector(request)
    if not connector:
        return PaymentResult(
            transaction_id="",
            provider=PaymentProvider.AUTHORIZE_NET,
            status=PaymentStatus.ERROR,
            amount=amount,
            currency=currency,
            message="Authorize.net connector not available",
        )

    try:
        from aragora.connectors.payments.authorize_net import CreditCard, BillingAddress

        # Parse payment method
        if isinstance(payment_method, dict):
            card = CreditCard(
                card_number=payment_method.get("card_number", ""),
                expiration_date=f"{payment_method.get('exp_month', '01')}{payment_method.get('exp_year', '2025')[-2:]}",
                card_code=payment_method.get("cvv"),
            )
            billing = None
            if payment_method.get("billing"):
                billing_data = payment_method["billing"]
                billing = BillingAddress(
                    first_name=billing_data.get("first_name", ""),
                    last_name=billing_data.get("last_name", ""),
                    address=billing_data.get("address"),
                    city=billing_data.get("city"),
                    state=billing_data.get("state"),
                    zip_code=billing_data.get("zip"),
                    country=billing_data.get("country"),
                )
        else:
            return PaymentResult(
                transaction_id="",
                provider=PaymentProvider.AUTHORIZE_NET,
                status=PaymentStatus.ERROR,
                amount=amount,
                currency=currency,
                message="Invalid payment method for Authorize.net",
            )

        async def _do_charge():
            async with connector:
                return await connector.charge(
                    amount=amount,
                    payment_method=card,
                    billing_address=billing,
                    description=description,
                )

        result = await _pkg()._resilient_authnet_call("charge", _do_charge)

        return PaymentResult(
            transaction_id=result.transaction_id,
            provider=PaymentProvider.AUTHORIZE_NET,
            status=PaymentStatus.APPROVED if result.approved else PaymentStatus.DECLINED,
            amount=amount,
            currency=currency,
            message=result.message,
            auth_code=result.auth_code,
            avs_result=result.avs_result,
            cvv_result=result.cvv_result,
        )

    except ConnectionError as e:
        logger.error("Authorize.net connection error: %s", e)
        return PaymentResult(
            transaction_id="",
            provider=PaymentProvider.AUTHORIZE_NET,
            status=PaymentStatus.ERROR,
            amount=amount,
            currency=currency,
            message="Payment service temporarily unavailable",
        )
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Authorize.net data error: %s", e)
        return PaymentResult(
            transaction_id="",
            provider=PaymentProvider.AUTHORIZE_NET,
            status=PaymentStatus.ERROR,
            amount=amount,
            currency=currency,
            message="Invalid payment request",
        )
    except (RuntimeError, TimeoutError, AttributeError) as e:
        logger.exception("Unexpected Authorize.net error: %s", e)
        return PaymentResult(
            transaction_id="",
            provider=PaymentProvider.AUTHORIZE_NET,
            status=PaymentStatus.ERROR,
            amount=amount,
            currency=currency,
            message="Internal payment processing error",
        )


@require_permission(PERM_PAYMENTS_AUTHORIZE)
@track_handler("payments/authorize")
async def handle_authorize(request: web.Request) -> web.Response:
    """
    POST /api/payments/authorize

    Authorize a payment (capture later).
    """
    # Rate limit check for financial operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        body, err = await parse_json_body(request, context="handle_authorize")
        if err:
            return err
        if body is None:
            return web_error_response("Invalid request body", 400)
        provider = _pkg()._get_provider_from_request(request, body)

        amount = Decimal(str(body.get("amount", 0)))
        if amount <= 0:
            return web_error_response("Amount must be greater than 0", 400)

        currency = body.get("currency", "USD")
        payment_method = body.get("payment_method")

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            from aragora.connectors.payments.authorize_net import CreditCard

            if isinstance(payment_method, dict):
                card = CreditCard(
                    card_number=payment_method.get("card_number", ""),
                    expiration_date=f"{payment_method.get('exp_month', '01')}{payment_method.get('exp_year', '2025')[-2:]}",
                    card_code=payment_method.get("cvv"),
                )

                async with connector:
                    result = await connector.authorize(amount=amount, payment_method=card)

                return web.json_response(
                    {
                        "success": result.approved,
                        "transaction_id": result.transaction_id,
                        "auth_code": result.auth_code,
                        "message": result.message,
                    }
                )
        else:
            # Stripe authorization
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            amount_cents = int(amount * 100)
            intent = await connector.create_payment_intent(
                amount=amount_cents,
                currency=currency.lower(),
                capture_method="manual",  # Authorize only
                payment_method=payment_method if isinstance(payment_method, str) else None,
            )

            return web.json_response(
                {
                    "success": True,
                    "transaction_id": intent.id,
                    "client_secret": intent.client_secret,
                    "status": intent.status,
                }
            )

        return web_error_response("Invalid request", 400)

    except (ConnectionError, OSError) as e:
        logger.error("Connection error authorizing payment: %s", e)
        return web_error_response("Payment service temporarily unavailable", 503)
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Data error authorizing payment: %s", e)
        return web_error_response("Invalid authorization data", 400)
    except (RuntimeError, TimeoutError, AttributeError) as e:
        logger.exception("Unexpected error authorizing payment: %s", e)
        return web_error_response("Internal payment error", 500)


@require_permission(PERM_PAYMENTS_CAPTURE)
@track_handler("payments/capture")
async def handle_capture(request: web.Request) -> web.Response:
    """
    POST /api/payments/capture

    Capture an authorized payment.

    Request body:
    {
        "provider": "stripe" | "authorize_net",
        "transaction_id": "...",
        "amount": 100.00  // Optional, for partial capture
    }
    """
    # Rate limit check for financial operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        body, err = await parse_json_body(request, context="handle_capture")
        if err:
            return err
        if body is None:
            return web_error_response("Invalid request body", 400)
        provider = _pkg()._get_provider_from_request(request, body)
        transaction_id = body.get("transaction_id")
        amount = body.get("amount")

        if not transaction_id:
            return web_error_response("Missing transaction_id", 400)

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            async with connector:
                result = await connector.capture(
                    transaction_id=transaction_id,
                    amount=Decimal(str(amount)) if amount else None,
                )

            return web.json_response(
                {
                    "success": result.approved,
                    "transaction_id": result.transaction_id,
                    "message": result.message,
                }
            )
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            intent = await connector.capture_payment_intent(
                payment_intent_id=transaction_id,
                amount_to_capture=int(Decimal(str(amount)) * 100) if amount else None,
            )

            return web.json_response(
                {
                    "success": intent.status == "succeeded",
                    "transaction_id": intent.id,
                    "status": intent.status,
                }
            )

    except (ConnectionError, OSError) as e:
        logger.error("Connection error capturing payment: %s", e)
        return web_error_response("Payment service temporarily unavailable", 503)
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Data error capturing payment: %s", e)
        return web_error_response("Invalid capture data", 400)
    except (RuntimeError, TimeoutError, AttributeError) as e:
        logger.exception("Unexpected error capturing payment: %s", e)
        return web_error_response("Internal payment error", 500)


@require_permission(PERM_PAYMENTS_REFUND)
@track_handler("payments/refund")
async def handle_refund(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    POST /api/payments/refund

    Refund a payment.

    Request body:
    {
        "provider": "stripe" | "authorize_net",
        "transaction_id": "...",
        "amount": 100.00,
        "card_last_four": "1111"  // Required for Authorize.net
    }
    """
    _enforce_permission_if_context(request, PERM_PAYMENTS_REFUND)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for financial operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    body = None
    try:
        body, err = await parse_json_body(request, context="handle_refund")
        if err:
            return err
        if body is None:
            return web_error_response("Invalid request body", 400)
        provider = _pkg()._get_provider_from_request(request, body)
        transaction_id = body.get("transaction_id")
        amount = Decimal(str(body.get("amount", 0)))

        if not transaction_id:
            return web_error_response("Missing transaction_id", 400)
        if amount <= 0:
            return web_error_response("Amount must be greater than 0", 400)

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            card_last_four = body.get("card_last_four")
            if not card_last_four:
                return web.json_response(
                    {"error": "card_last_four required for Authorize.net refunds"}, status=400
                )

            async with connector:
                result = await connector.refund(
                    transaction_id=transaction_id,
                    amount=amount,
                    card_last_four=card_last_four,
                )

            # Audit the refund
            _pkg().audit_data(
                user_id=request.get("user_id", "unknown"),
                action="payment_refund",
                resource_type="payment",
                resource_id=result.transaction_id,
                provider="authorize_net",
                amount=str(amount),
                success=result.approved,
            )

            return web.json_response(
                {
                    "success": result.approved,
                    "transaction_id": result.transaction_id,
                    "message": result.message,
                }
            )
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            refund = await connector.create_refund(
                payment_intent=transaction_id,
                amount=int(amount * 100),
            )

            # Audit the refund
            _pkg().audit_data(
                user_id=request.get("user_id", "unknown"),
                action="payment_refund",
                resource_type="payment",
                resource_id=refund.id,
                original_transaction_id=transaction_id,
                provider="stripe",
                amount=str(amount),
                status=refund.status,
                success=refund.status == "succeeded",
            )

            return web.json_response(
                {
                    "success": refund.status == "succeeded",
                    "refund_id": refund.id,
                    "status": refund.status,
                }
            )

    except (ConnectionError, OSError) as e:
        logger.error("Connection error processing refund: %s", e)
        return web_error_response("Payment service temporarily unavailable", 503)
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Data error processing refund: %s", e)
        return web_error_response("Invalid refund data", 400)
    except (RuntimeError, TimeoutError, AttributeError) as e:
        logger.exception("Unexpected error processing refund: %s", e)
        _pkg().audit_security(
            event_type="refund_error",
            actor_id=request.get("user_id", "unknown"),
            resource_type="payment",
            resource_id=body.get("transaction_id", "unknown") if body else "unknown",
            reason=type(e).__name__,
        )
        return web_error_response("Internal payment error", 500)


@require_permission(PERM_PAYMENTS_VOID)
@track_handler("payments/void")
async def handle_void(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    POST /api/payments/void

    Void a transaction.

    Request body:
    {
        "provider": "stripe" | "authorize_net",
        "transaction_id": "..."
    }
    """
    _enforce_permission_if_context(request, PERM_PAYMENTS_VOID)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for financial operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_write_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        body, err = await parse_json_body(request, context="handle_void")
        if err:
            return err
        if body is None:
            return web_error_response("Invalid request body", 400)
        provider = _pkg()._get_provider_from_request(request, body)
        transaction_id = body.get("transaction_id")

        if not transaction_id:
            return web_error_response("Missing transaction_id", 400)

        if provider == PaymentProvider.AUTHORIZE_NET:
            connector = await _pkg().get_authnet_connector(request)
            if not connector:
                return web.json_response(
                    {"error": "Authorize.net connector not available"}, status=503
                )

            async with connector:
                result = await connector.void(transaction_id=transaction_id)

            return web.json_response(
                {
                    "success": result.approved,
                    "transaction_id": result.transaction_id,
                    "message": result.message,
                }
            )
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            intent = await connector.cancel_payment_intent(transaction_id)

            return web.json_response(
                {
                    "success": intent.status == "canceled",
                    "transaction_id": intent.id,
                    "status": intent.status,
                }
            )

    except (ConnectionError, OSError) as e:
        logger.error("Connection error voiding transaction: %s", e)
        return web_error_response("Payment service temporarily unavailable", 503)
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Data error voiding transaction: %s", e)
        return web_error_response("Invalid void request", 400)
    except (RuntimeError, TimeoutError, AttributeError) as e:
        logger.exception("Unexpected error voiding transaction: %s", e)
        return web_error_response("Internal payment error", 500)


@require_permission(PERM_PAYMENTS_READ)
async def handle_get_transaction(
    request: web.Request | Any, maybe_request: web.Request | None = None
) -> web.Response:
    """
    GET /api/payments/transaction/{transaction_id}

    Get transaction details.
    """
    _enforce_permission_if_context(request, PERM_PAYMENTS_READ)
    request = _coerce_request(request, maybe_request)

    # Rate limit check for read operations
    rate_limit_response = _pkg()._check_rate_limit(request, _payment_read_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        transaction_id = request.match_info.get("transaction_id")
        provider_str = request.query.get("provider", "stripe")

        if not transaction_id:
            return web_error_response("Missing transaction_id", 400)

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
                details = await connector.get_transaction_details(transaction_id)

            if not details:
                return web_error_response("Transaction not found", 404)

            return web.json_response({"transaction": details})
        else:
            connector = await _pkg().get_stripe_connector(request)
            if not connector:
                return web_error_response("Stripe connector not available", 503)

            intent = await connector.retrieve_payment_intent(transaction_id)

            return web.json_response(
                {
                    "transaction": {
                        "id": intent.id,
                        "amount": intent.amount,
                        "currency": intent.currency,
                        "status": intent.status,
                        "created": intent.created,
                        "metadata": intent.metadata,
                    }
                }
            )

    except (ConnectionError, OSError) as e:
        logger.error("Connection error getting transaction: %s", e)
        return web_error_response("Payment service temporarily unavailable", 503)
    except (ValueError, KeyError, TypeError) as e:
        logger.error("Data error getting transaction: %s", e)
        return web_error_response("Invalid transaction request", 400)
    except (RuntimeError, TimeoutError, AttributeError) as e:
        logger.exception("Unexpected error getting transaction: %s", e)
        return web_error_response("Internal payment error", 500)


# =============================================================================
# Webhook Handlers
# =============================================================================


# =============================================================================
# Stripe Webhook Event Handlers
#
# Each handler is isolated so a failure in one event type does not affect
# others.  Handlers receive the event's data object (dict-like) and return
# a small result dict merged into the response.
# =============================================================================


def _handle_checkout_session_completed(obj: Any) -> dict[str, Any]:
    """Activate subscription after successful checkout.

    Stripe sends this when a Checkout Session payment succeeds.  Extracts the
    tier from session metadata (set during checkout creation) and updates the
    organization's tier in the database.
    """
    from aragora.billing.models import SubscriptionTier

    customer_id = obj.get("customer", "")
    subscription_id = obj.get("subscription", "")
    metadata = obj.get("metadata", {}) or {}
    org_id = metadata.get("org_id", "")
    tier_str = metadata.get("tier", "")

    logger.info(
        "Checkout completed: customer=%s, subscription=%s, org=%s, tier=%s",
        customer_id,
        subscription_id,
        org_id,
        tier_str,
    )

    result: dict[str, Any] = {
        "customer_id": customer_id,
        "subscription_id": subscription_id,
    }

    # Update org tier in the database
    if org_id and subscription_id:
        try:
            from aragora.storage.user_store.singleton import get_user_store

            user_store = get_user_store()
            if user_store:
                org = user_store.get_organization_by_id(org_id)
                if org:
                    old_tier = org.tier.value
                    try:
                        new_tier = (
                            SubscriptionTier(tier_str) if tier_str else SubscriptionTier.STARTER
                        )
                    except ValueError:
                        new_tier = SubscriptionTier.STARTER

                    user_store.update_organization(
                        org_id,
                        stripe_customer_id=customer_id,
                        stripe_subscription_id=subscription_id,
                        tier=new_tier,
                    )
                    logger.info(
                        "Org %s tier updated: %s -> %s after checkout",
                        org_id,
                        old_tier,
                        new_tier.value,
                    )
                    result["tier_updated"] = True
                    result["old_tier"] = old_tier
                    result["new_tier"] = new_tier.value

                    # Audit the tier change
                    try:
                        from aragora.audit.unified import audit_data

                        audit_data(
                            user_id=metadata.get("user_id", "stripe_webhook"),
                            resource_type="subscription",
                            resource_id=subscription_id,
                            action="subscription.created",
                            old_tier=old_tier,
                            new_tier=new_tier.value,
                            org_id=org_id,
                        )
                    except (ImportError, OSError, ValueError) as audit_err:
                        logger.warning("Failed to audit checkout tier change: %s", audit_err)
        except (ImportError, OSError, ValueError, AttributeError) as e:
            logger.error("Failed to update org tier on checkout: %s", e)

    return result


def _handle_subscription_updated(obj: Any) -> dict[str, Any]:
    """Handle plan/tier changes and status transitions on an existing subscription.

    Syncs tier from price changes and handles status transitions:
    - active: restore tier from price if org was on FREE
    - past_due/unpaid/incomplete: log degraded status for monitoring
    - canceled: downgrade org to FREE tier
    """
    from aragora.billing.models import SubscriptionTier

    subscription_id = obj.get("id", "")
    status = obj.get("status", "")
    cancel_at_period_end = obj.get("cancel_at_period_end", False)
    items = obj.get("items", {})
    items_data = items.get("data", []) if isinstance(items, dict) else []
    price_id = items_data[0].get("price", {}).get("id", "") if items_data else ""
    logger.info(
        "Subscription updated: id=%s, status=%s, price=%s, cancel_at_period_end=%s",
        subscription_id,
        status,
        price_id,
        cancel_at_period_end,
    )

    result: dict[str, Any] = {
        "subscription_id": subscription_id,
        "status": status,
        "price_id": price_id,
    }

    if not subscription_id:
        return result

    try:
        from aragora.billing.stripe_client import get_tier_from_price_id
        from aragora.storage.user_store.singleton import get_user_store

        user_store = get_user_store()
        if not user_store:
            return result

        org = user_store.get_organization_by_subscription(subscription_id)
        if not org:
            return result

        old_tier = org.tier.value
        updates: dict[str, Any] = {}
        new_tier = None

        # Sync tier from price change
        if price_id:
            tier = get_tier_from_price_id(price_id)
            if tier:
                updates["tier"] = tier
                new_tier = tier.value

        # Handle subscription status transitions
        if status in ("past_due", "unpaid", "incomplete"):
            logger.warning(
                "Subscription %s entered %s status for org %s",
                subscription_id,
                status,
                org.id,
            )
            result["status_degraded"] = True
        elif status == "canceled":
            updates["tier"] = SubscriptionTier.FREE
            updates["stripe_subscription_id"] = None
            new_tier = "free"
            logger.info(
                "Subscription %s canceled for org %s, downgrading to FREE",
                subscription_id,
                org.id,
            )
        elif status == "active" and old_tier == "free" and not new_tier:
            # Re-activation: restore tier from price if available
            if price_id:
                restored = get_tier_from_price_id(price_id)
                if restored:
                    updates["tier"] = restored
                    new_tier = restored.value
                    logger.info(
                        "Subscription %s re-activated for org %s, restoring tier to %s",
                        subscription_id,
                        org.id,
                        new_tier,
                    )

        if updates:
            user_store.update_organization(org.id, **updates)
            result["tier_updated"] = True
            result["old_tier"] = old_tier
            result["new_tier"] = new_tier

            logger.info(
                "Updated org %s from subscription update: old_tier=%s, new_tier=%s",
                org.id,
                old_tier,
                new_tier,
            )

            # Audit tier change
            if new_tier and new_tier != old_tier:
                try:
                    from aragora.audit.unified import audit_data

                    audit_data(
                        user_id="stripe_webhook",
                        resource_type="subscription",
                        resource_id=subscription_id,
                        action="subscription.tier_changed",
                        old_tier=old_tier,
                        new_tier=new_tier,
                        status=status,
                        org_id=org.id,
                    )
                except (ImportError, OSError, ValueError) as audit_err:
                    logger.warning("Failed to audit subscription tier change: %s", audit_err)

    except (ImportError, OSError, ValueError, AttributeError) as e:
        logger.error("Failed to update org tier on subscription update: %s", e)

    return result


def _handle_subscription_deleted(obj: Any) -> dict[str, Any]:
    """Deactivate subscription and downgrade org to FREE tier."""
    from aragora.billing.models import SubscriptionTier

    subscription_id = obj.get("id", "")
    logger.info("Subscription deleted: id=%s", subscription_id)

    result: dict[str, Any] = {
        "subscription_id": subscription_id,
        "action": "deactivated",
    }

    if not subscription_id:
        return result

    try:
        from aragora.storage.user_store.singleton import get_user_store

        user_store = get_user_store()
        if not user_store:
            return result

        org = user_store.get_organization_by_subscription(subscription_id)
        if not org:
            return result

        old_tier = org.tier.value
        user_store.update_organization(
            org.id,
            tier=SubscriptionTier.FREE,
            stripe_subscription_id=None,
        )
        logger.info(
            "Downgraded org %s from %s to FREE after subscription deletion",
            org.id,
            old_tier,
        )
        result["tier_updated"] = True
        result["old_tier"] = old_tier
        result["new_tier"] = "free"

        # Audit the downgrade
        try:
            from aragora.audit.unified import audit_data

            audit_data(
                user_id="stripe_webhook",
                resource_type="subscription",
                resource_id=subscription_id,
                action="subscription.deleted",
                old_tier=old_tier,
                new_tier="free",
                org_id=org.id,
            )
        except (ImportError, OSError, ValueError) as audit_err:
            logger.warning("Failed to audit subscription deletion: %s", audit_err)

    except (ImportError, OSError, ValueError, AttributeError) as e:
        logger.error("Failed to downgrade org on subscription deletion: %s", e)

    return result


def _handle_invoice_payment_failed(obj: Any) -> dict[str, Any]:
    """Flag account for payment failure.  Send notification via logging.

    Stripe retries failed invoices automatically.  We record the attempt
    count so the payment_recovery system can escalate notifications and
    eventually auto-downgrade after the grace period.
    """
    customer_id = obj.get("customer", "")
    subscription_id = obj.get("subscription", "")
    attempt_count = obj.get("attempt_count", 1)
    invoice_id = obj.get("id", "")
    logger.warning(
        "Invoice payment failed: invoice=%s, customer=%s, subscription=%s, attempt=%s",
        invoice_id,
        customer_id,
        subscription_id,
        attempt_count,
    )
    return {
        "invoice_id": invoice_id,
        "customer_id": customer_id,
        "attempt_count": attempt_count,
        "payment_failed": True,
    }


def _handle_invoice_paid(obj: Any) -> dict[str, Any]:
    """Clear payment failure flags on successful invoice payment."""
    customer_id = obj.get("customer", "")
    subscription_id = obj.get("subscription", "")
    amount_paid = obj.get("amount_paid", 0)
    logger.info(
        "Invoice paid: customer=%s, subscription=%s, amount=%s",
        customer_id,
        subscription_id,
        amount_paid,
    )
    return {
        "customer_id": customer_id,
        "amount_paid": amount_paid,
        "payment_recovered": True,
    }


def _handle_payment_intent_succeeded(obj: Any) -> dict[str, Any]:
    """Log successful one-time payment intent."""
    logger.info("Payment intent succeeded: %s", obj.get("id", ""))
    return {"payment_intent_id": obj.get("id", "")}


def _handle_payment_intent_failed(obj: Any) -> dict[str, Any]:
    """Log failed payment intent."""
    logger.warning("Payment intent failed: %s", obj.get("id", ""))
    return {"payment_intent_id": obj.get("id", ""), "failed": True}


# Dispatch table mapping Stripe event types to handler functions.
_STRIPE_EVENT_HANDLERS: dict[str, Any] = {
    "checkout.session.completed": _handle_checkout_session_completed,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "customer.subscription.created": _handle_subscription_updated,  # same shape
    "invoice.payment_failed": _handle_invoice_payment_failed,
    "invoice.paid": _handle_invoice_paid,
    "invoice.payment_succeeded": _handle_invoice_paid,
    "payment_intent.succeeded": _handle_payment_intent_succeeded,
    "payment_intent.payment_failed": _handle_payment_intent_failed,
}


def _record_dead_letter(event_id: str, event_type: str, error: Exception) -> None:
    """Record a failed webhook event for manual review.

    Logs the failure at ERROR level so it surfaces in monitoring, and
    attempts to persist it in the webhook store with an ``error`` result
    so operators can query for failed events.
    """
    logger.error(
        "Dead-letter webhook event: id=%s, type=%s, error=%s: %s",
        event_id,
        event_type,
        type(error).__name__,
        error,
    )
    try:
        _pkg()._mark_webhook_processed(event_id, result=f"error:{type(error).__name__}")
    except (RuntimeError, OSError, ValueError, AttributeError) as store_err:
        logger.error("Failed to persist dead-letter record: %s", store_err)


@track_handler("payments/webhook/stripe")
@require_permission("billing:read")
async def handle_stripe_webhook(request: web.Request) -> web.Response:
    """
    POST /api/payments/webhook/stripe

    Handle Stripe webhook events with production-grade safety:
    - Signature verification (400 on invalid)
    - Idempotency via persistent event store
    - Isolated per-event-type handlers
    - Always returns 200 after signature passes (prevents Stripe retry loops)
    - Dead-letter recording for handler failures
    """
    # Rate limit check for webhooks (higher limit, server-to-server)
    rate_limit_response = _pkg()._check_rate_limit(request, _webhook_limiter)
    if rate_limit_response:
        return rate_limit_response

    # --- Signature verification (the ONLY place we return 400) ---
    try:
        payload = await request.read()
    except (ConnectionError, OSError, RuntimeError) as e:
        logger.error("Failed to read webhook payload: %s", e)
        return web_error_response("Failed to read request body", 400)

    sig_header = request.headers.get("Stripe-Signature")
    if not sig_header:
        return web_error_response("Missing Stripe-Signature header", 400)

    connector = await _pkg().get_stripe_connector(request)
    if not connector:
        # Cannot verify signature without connector -- must reject
        return web_error_response("Stripe connector not available", 503)

    try:
        event = await connector.construct_webhook_event(payload, sig_header)
    except ValueError:
        return web_error_response("Invalid payload", 400)
    except (KeyError, TypeError, AttributeError):
        return web_error_response("Webhook signature verification failed", 400)

    # --- From here on, always return 200 to prevent Stripe retry storms ---

    event_id = event.id or ""
    event_type = event.type or ""

    # Idempotency check
    if event_id:
        try:
            if _pkg()._is_duplicate_webhook(event_id):
                logger.info("Skipping duplicate Stripe webhook: %s", event_id)
                return web.json_response({"received": True, "duplicate": True})
        except (RuntimeError, OSError, ValueError) as e:
            # Idempotency store unavailable -- log but continue processing
            # (processing twice is better than dropping the event)
            logger.warning("Idempotency check failed, proceeding: %s", e)
    else:
        logger.warning("Webhook event missing ID, cannot check idempotency")

    logger.info("Processing Stripe webhook: %s (id=%s)", event_type, event_id)

    # Dispatch to isolated handler
    handler_fn = _STRIPE_EVENT_HANDLERS.get(event_type)
    result_data: dict[str, Any] = {"received": True}

    if handler_fn is not None:
        try:
            raw = getattr(event.data.object, "_data", None)
            obj = raw if isinstance(raw, dict) else {}
            handler_result = handler_fn(obj)
            if isinstance(handler_result, dict):
                result_data.update(handler_result)
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            # Handler failed -- record in dead letter queue, still return 200
            _record_dead_letter(event_id, event_type, e)
            result_data["processing_error"] = True
    else:
        # Unrecognized event type -- acknowledge without processing
        logger.debug("Unhandled Stripe event type: %s", event_type)

    # Mark as processed (success or handler error -- both are "handled")
    if event_id:
        try:
            if not result_data.get("processing_error"):
                _pkg()._mark_webhook_processed(event_id)
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("Failed to mark webhook as processed: %s", e)

    return web.json_response(result_data)


@track_handler("payments/webhook/authnet")
@require_permission("billing:read")
async def handle_authnet_webhook(request: web.Request) -> web.Response:
    """
    POST /api/payments/webhook/authnet

    Handle Authorize.net webhook events.
    """
    # Rate limit check for webhooks (higher limit, server-to-server)
    rate_limit_response = _pkg()._check_rate_limit(request, _webhook_limiter)
    if rate_limit_response:
        return rate_limit_response

    try:
        payload, err = await parse_json_body(request, context="handle_authnet_webhook")
        if err:
            return err
        if payload is None:
            return web_error_response("Invalid request body", 400)
        signature = request.headers.get("X-ANET-Signature")

        connector = await _pkg().get_authnet_connector(request)
        if not connector:
            return web_error_response("Authorize.net connector not available", 503)

        # Verify webhook signature
        async with connector:
            if not await connector.verify_webhook_signature(payload, signature or ""):
                return web_error_response("Invalid signature", 400)

        # Get event ID for idempotency check
        event_id = payload.get("notificationId") or payload.get("payload", {}).get("id")
        if not event_id:
            # Generate deterministic ID from payload if not provided
            import hashlib

            payload_str = json.dumps(payload, sort_keys=True)
            event_id = f"authnet_{hashlib.sha256(payload_str.encode()).hexdigest()[:16]}"

        if _pkg()._is_duplicate_webhook(event_id):
            logger.info("Skipping duplicate Authorize.net webhook: %s", event_id)
            return web.json_response({"received": True, "duplicate": True})

        # Handle the event
        event_type = payload.get("eventType", "")
        logger.info("Received Authorize.net webhook: %s (id=%s)", event_type, event_id)

        # Process different event types
        if event_type == "net.authorize.payment.authcapture.created":
            logger.info("Payment captured: %s", payload.get("payload", {}).get("id"))
        elif event_type == "net.authorize.payment.refund.created":
            logger.info("Refund processed: %s", payload.get("payload", {}).get("id"))
        elif event_type == "net.authorize.customer.subscription.created":
            logger.info("Subscription created: %s", payload.get("payload", {}).get("id"))
        elif event_type == "net.authorize.customer.subscription.cancelled":
            logger.info("Subscription canceled: %s", payload.get("payload", {}).get("id"))

        # Mark as processed after successful handling
        _pkg()._mark_webhook_processed(event_id)

        return web.json_response({"received": True})

    except (ValueError, KeyError, TypeError) as e:
        logger.error("Data error in Authorize.net webhook: %s", e)
        return web_error_response("Invalid webhook data", 400)
    except (RuntimeError, TimeoutError, AttributeError, OSError) as e:
        logger.exception("Unexpected error handling Authorize.net webhook: %s", e)
        return web_error_response("Webhook processing error", 500)
