"""
Partner API HTTP handlers.

Endpoints:
- POST /api/partners/register                - Register as a partner
- GET  /api/partners/me                      - Get current partner profile
- POST /api/partners/keys                    - Create API key
- GET  /api/partners/keys                    - List API keys
- POST /api/partners/keys/{key_id}/rotate    - Rotate API key
- DELETE /api/partners/keys/{key_id}         - Revoke API key
- GET  /api/partners/usage                   - Get usage statistics
- POST /api/partners/webhooks                - Configure webhook
- GET  /api/partners/limits                  - Get rate limits
"""

from __future__ import annotations

import json
import logging
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.validation.query_params import safe_query_int

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    require_user_auth,
    safe_error_message,
)
from ..utils.rate_limit import rate_limit
from ..utils.url_security import validate_webhook_url

logger = logging.getLogger(__name__)


class PartnerHandler(BaseHandler):
    """Handler for partner API endpoints."""

    ROUTES = [
        "/api/v1/partners/register",
        "/api/v1/partners/me",
        "/api/v1/partners/keys",
        "/api/v1/partners/usage",
        "/api/v1/partners/webhooks",
        "/api/v1/partners/limits",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES or path.startswith("/api/v1/partners/keys/")

    @require_permission("partner:read")
    @rate_limit(requests_per_minute=30)
    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route requests to appropriate methods."""
        method = handler.command

        if path == "/api/v1/partners/register" and method == "POST":
            return self._register_partner(handler)
        elif path == "/api/v1/partners/me" and method == "GET":
            return self._get_partner_profile(handler)
        elif path == "/api/v1/partners/keys":
            if method == "POST":
                return self._create_api_key(handler)
            elif method == "GET":
                return self._list_api_keys(handler)
        elif path.startswith("/api/v1/partners/keys/"):
            parts = path.split("/")
            if len(parts) == 7 and parts[-1] == "rotate" and method == "POST":
                key_id = parts[-2]
                return self._rotate_api_key(key_id, handler)
            elif method == "DELETE":
                key_id = parts[-1]
                return self._revoke_api_key(key_id, handler)
        elif path == "/api/v1/partners/usage" and method == "GET":
            return self._get_usage(query_params, handler)
        elif path == "/api/v1/partners/webhooks" and method == "POST":
            return self._configure_webhook(handler)
        elif path == "/api/v1/partners/limits" and method == "GET":
            return self._get_limits(handler)

        return None

    @handle_errors("register partner")
    def _register_partner(self, handler) -> HandlerResult:
        """
        Register a new partner.

        Request body:
        {
            "name": "Partner Name",
            "email": "partner@example.com",
            "company": "Company Inc" (optional)
        }

        Response:
        {
            "partner_id": "...",
            "name": "...",
            "email": "...",
            "tier": "starter",
            "status": "pending",
            "referral_code": "ABC123XY"
        }
        """
        try:
            content_type = (handler.headers.get("Content-Type") or "").lower()
            if not content_type.startswith("application/json"):
                return error_response("Content-Type must be application/json", 415)
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = json.loads(handler.rfile.read(content_length).decode())
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        name = body.get("name")
        email = body.get("email")
        company = body.get("company")

        if not name or not email:
            return error_response("name and email are required", 400)

        try:
            from aragora.billing.partner import get_partner_api

            api = get_partner_api()

            # Check if email already registered
            existing = api._store.get_partner_by_email(email)
            if existing:
                return error_response("Email already registered", 409)

            partner = api.register_partner(name=name, email=email, company=company)

            return json_response(
                {
                    "partner_id": partner.partner_id,
                    "name": partner.name,
                    "email": partner.email,
                    "company": partner.company,
                    "tier": partner.tier.value,
                    "status": partner.status.value,
                    "referral_code": partner.referral_code,
                    "message": "Registration pending approval. You will receive an email when activated.",
                },
                status=201,
            )

        except (ImportError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as e:
            logger.exception("Error registering partner: %s", e)
            return error_response(safe_error_message(e, "registration"), 500)

    @require_user_auth
    @handle_errors("get partner profile")
    def _get_partner_profile(self, handler, user=None) -> HandlerResult:
        """Get current partner profile."""
        partner_id = handler.headers.get("X-Partner-ID")
        if not partner_id:
            return error_response("Partner ID required", 400)

        try:
            from aragora.billing.partner import get_partner_api

            api = get_partner_api()
            stats = api.get_partner_stats(partner_id)

            return json_response(stats)

        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Resource not found", 404)
        except (ImportError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as e:
            logger.exception("Error getting partner profile: %s", e)
            return error_response(safe_error_message(e, "profile"), 500)

    @require_user_auth
    @handle_errors("create API key")
    def _create_api_key(self, handler, user=None) -> HandlerResult:
        """
        Create a new API key.

        Request body:
        {
            "name": "My API Key",
            "scopes": ["debates:read", "debates:write"] (optional),
            "expires_in_days": 365 (optional)
        }

        Response:
        {
            "key_id": "...",
            "key": "ara_...",  // Only returned once!
            "key_prefix": "ara_...",
            "name": "...",
            "scopes": [...],
            "expires_at": "..."
        }
        """
        partner_id = handler.headers.get("X-Partner-ID")
        if not partner_id:
            return error_response("Partner ID required", 400)

        try:
            content_type = (handler.headers.get("Content-Type") or "").lower()
            if not content_type.startswith("application/json"):
                return error_response("Content-Type must be application/json", 415)
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = json.loads(handler.rfile.read(content_length).decode())
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        name = body.get("name", "API Key")
        scopes = body.get("scopes")
        expires_in_days = body.get("expires_in_days")

        try:
            from aragora.billing.partner import get_partner_api

            api = get_partner_api()
            api_key, raw_key = api.create_api_key(
                partner_id=partner_id,
                name=name,
                scopes=scopes,
                expires_in_days=expires_in_days,
            )

            return json_response(
                {
                    "key_id": api_key.key_id,
                    "key": raw_key,  # Only returned once!
                    "key_prefix": api_key.key_prefix,
                    "name": api_key.name,
                    "scopes": api_key.scopes,
                    "created_at": api_key.created_at.isoformat(),
                    "expires_at": (api_key.expires_at.isoformat() if api_key.expires_at else None),
                    "warning": "Save this key securely - it will not be shown again!",
                },
                status=201,
            )

        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except (ImportError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as e:
            logger.exception("Error creating API key: %s", e)
            return error_response(safe_error_message(e, "key creation"), 500)

    @require_user_auth
    @handle_errors("rotate API key")
    def _rotate_api_key(self, key_id: str, handler, user=None) -> HandlerResult:
        """
        Rotate an API key - revokes old key and creates a new one.

        Preserves name, scopes, and expiration policy from the original key.

        Response:
        {
            "key_id": "...",
            "key": "ara_...",  // Only returned once!
            "key_prefix": "ara_...",
            "name": "...",
            "scopes": [...],
            "rotated_from": "old_key_id",
            "expires_at": "..."
        }
        """
        partner_id = handler.headers.get("X-Partner-ID")
        if not partner_id:
            return error_response("Partner ID required", 400)

        try:
            from aragora.billing.partner import get_partner_api

            api = get_partner_api()
            new_key, raw_key = api.rotate_api_key(
                partner_id=partner_id,
                key_id=key_id,
            )

            return json_response(
                {
                    "key_id": new_key.key_id,
                    "key": raw_key,  # Only returned once!
                    "key_prefix": new_key.key_prefix,
                    "name": new_key.name,
                    "scopes": new_key.scopes,
                    "created_at": new_key.created_at.isoformat(),
                    "expires_at": (new_key.expires_at.isoformat() if new_key.expires_at else None),
                    "rotated_from": key_id,
                    "warning": "Save this key securely - it will not be shown again!",
                },
                status=201,
            )

        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request", 400)
        except (ImportError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as e:
            logger.exception("Error rotating API key: %s", e)
            return error_response(safe_error_message(e, "key rotation"), 500)

    @require_user_auth
    @handle_errors("list API keys")
    def _list_api_keys(self, handler, user=None) -> HandlerResult:
        """List all API keys for the partner."""
        partner_id = handler.headers.get("X-Partner-ID")
        if not partner_id:
            return error_response("Partner ID required", 400)

        try:
            from aragora.billing.partner import get_partner_api

            api = get_partner_api()
            keys = api._store.list_partner_keys(partner_id)

            return json_response(
                {
                    "keys": [k.to_dict() for k in keys],
                    "total": len(keys),
                    "active": len([k for k in keys if k.is_active]),
                }
            )

        except (ImportError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as e:
            logger.exception("Error listing API keys: %s", e)
            return error_response(safe_error_message(e, "key listing"), 500)

    @require_user_auth
    @handle_errors("revoke API key")
    def _revoke_api_key(self, key_id: str, handler, user=None) -> HandlerResult:
        """Revoke an API key."""
        partner_id = handler.headers.get("X-Partner-ID")
        if not partner_id:
            return error_response("Partner ID required", 400)

        try:
            from aragora.billing.partner import get_partner_api

            api = get_partner_api()
            success = api._store.revoke_api_key(key_id)

            if not success:
                return error_response("Key not found", 404)

            return json_response({"message": "Key revoked successfully", "key_id": key_id})

        except (ImportError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as e:
            logger.exception("Error revoking API key: %s", e)
            return error_response(safe_error_message(e, "key revocation"), 500)

    @require_user_auth
    @handle_errors("get usage")
    def _get_usage(
        self, query_params: dict[str, Any], handler: Any, user: Any = None
    ) -> HandlerResult:
        """
        Get usage statistics.

        Query params:
        - days: Number of days to look back (default: 30)
        """
        partner_id = handler.headers.get("X-Partner-ID")
        if not partner_id:
            return error_response("Partner ID required", 400)

        days = safe_query_int(query_params, "days", default=30, min_val=1, max_val=365)

        try:
            from aragora.billing.partner import get_partner_api

            api = get_partner_api()
            stats = api.get_partner_stats(partner_id, days=days)

            return json_response(stats)

        except ValueError as e:
            logger.warning("Handler error: %s", e)
            return error_response("Resource not found", 404)
        except (ImportError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as e:
            logger.exception("Error getting usage: %s", e)
            return error_response(safe_error_message(e, "usage"), 500)

    @require_user_auth
    @handle_errors("configure webhook")
    def _configure_webhook(self, handler, user=None) -> HandlerResult:
        """
        Configure webhook endpoint.

        Request body:
        {
            "url": "https://example.com/webhook"
        }

        Response:
        {
            "webhook_url": "...",
            "webhook_secret": "whsec_..."  // Only returned once!
        }
        """
        partner_id = handler.headers.get("X-Partner-ID")
        if not partner_id:
            return error_response("Partner ID required", 400)

        try:
            content_type = (handler.headers.get("Content-Type") or "").lower()
            if not content_type.startswith("application/json"):
                return error_response("Content-Type must be application/json", 415)
            content_length = int(handler.headers.get("Content-Length", 0))
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = json.loads(handler.rfile.read(content_length).decode())
        except (ValueError, json.JSONDecodeError) as e:
            logger.warning("Handler error: %s", e)
            return error_response("Invalid request body", 400)

        url = body.get("url")
        if not url:
            return error_response("url is required", 400)

        # Validate URL - require HTTPS and check for SSRF
        if not url.startswith("https://"):
            return error_response("Webhook URL must use HTTPS", 400)

        is_valid, url_error = validate_webhook_url(url, allow_localhost=False)
        if not is_valid:
            return error_response(f"Invalid webhook URL: {url_error}", 400)

        try:
            from aragora.billing.partner import get_partner_api

            api = get_partner_api()
            partner = api._store.get_partner(partner_id)

            if not partner:
                return error_response("Partner not found", 404)

            partner.webhook_url = url
            secret = api.generate_webhook_secret(partner_id)

            return json_response(
                {
                    "webhook_url": url,
                    "webhook_secret": secret,
                    "warning": "Save this secret securely - it will not be shown again!",
                }
            )

        except (ImportError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as e:
            logger.exception("Error configuring webhook: %s", e)
            return error_response(safe_error_message(e, "webhook"), 500)

    @require_user_auth
    @handle_errors("get limits")
    def _get_limits(self, handler, user=None) -> HandlerResult:
        """Get rate limits for the partner tier."""
        partner_id = handler.headers.get("X-Partner-ID")
        if not partner_id:
            return error_response("Partner ID required", 400)

        try:
            from aragora.billing.partner import (
                PARTNER_TIER_LIMITS,
                get_partner_api,
            )

            api = get_partner_api()
            partner = api._store.get_partner(partner_id)

            if not partner:
                return error_response("Partner not found", 404)

            limits = PARTNER_TIER_LIMITS[partner.tier]
            allowed, current = api.check_rate_limit(partner)

            return json_response(
                {
                    "tier": partner.tier.value,
                    "limits": {
                        "requests_per_minute": limits.requests_per_minute,
                        "requests_per_day": limits.requests_per_day,
                        "debates_per_month": limits.debates_per_month,
                        "max_agents_per_debate": limits.max_agents_per_debate,
                        "max_rounds": limits.max_rounds,
                        "webhook_endpoints": limits.webhook_endpoints,
                        "revenue_share_percent": limits.revenue_share_percent,
                    },
                    "current": current,
                    "allowed": allowed,
                }
            )

        except (ImportError, OSError, RuntimeError, TypeError, KeyError, AttributeError) as e:
            logger.exception("Error getting limits: %s", e)
            return error_response(safe_error_message(e, "limits"), 500)
