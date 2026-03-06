"""
MFA (Multi-Factor Authentication) Handlers.

Handles MFA-related endpoints:
- POST /api/auth/mfa/setup - Generate MFA secret and provisioning URI
- POST /api/auth/mfa/enable - Enable MFA after verifying setup code
- POST /api/auth/mfa/disable - Disable MFA
- DELETE /api/auth/mfa - Disable MFA (alias)
- POST /api/auth/mfa/verify - Verify MFA code during login
- POST /api/auth/mfa/backup-codes - Regenerate backup codes
"""

from __future__ import annotations

import hashlib
import json as json_module
import logging
import secrets as py_secrets
from typing import TYPE_CHECKING

from aragora.events.handler_events import emit_handler_event, COMPLETED, UPDATED
from ..base import HandlerResult, error_response, json_response, handle_errors, log_request
from ..openapi_decorator import api_endpoint
from ..utils.rate_limit import auth_rate_limit

if TYPE_CHECKING:
    from .handler import AuthHandler

# Unified audit logging
try:
    from aragora.audit.unified import audit_security

    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False
    audit_security = None

logger = logging.getLogger(__name__)


def _enumerate_users_for_compliance(user_store) -> list:
    """Return all users from the supported auth store interfaces."""
    list_all_fn = getattr(user_store, "list_all_users", None)
    if callable(list_all_fn):
        limit = 1000
        offset = 0
        users = []
        while True:
            batch_result = list_all_fn(limit=limit, offset=offset)
            if isinstance(batch_result, tuple) and len(batch_result) == 2:
                batch, total = batch_result
            else:
                batch, total = batch_result, None
            batch_users = list(batch)
            users.extend(batch_users)
            if not batch_users:
                break
            if total is not None and len(users) >= int(total):
                break
            if total is None and len(batch_users) < limit:
                break
            offset += limit
        return users

    list_fn = getattr(user_store, "list_users", None) or getattr(user_store, "get_all_users", None)
    if list_fn is None:
        raise AttributeError("User store does not support listing users")

    result = list_fn()
    if isinstance(result, tuple) and len(result) == 2:
        result, _ = result
    return list(result)


def extract_user_from_request(handler, user_store):
    """Proxy extract_user_from_request for patching in tests without circular imports."""
    from . import handler as auth_handler_module

    return auth_handler_module.extract_user_from_request(handler, user_store)


@api_endpoint(
    method="POST",
    path="/api/auth/mfa/setup",
    summary="Initialize MFA setup",
    description="Generate MFA secret and provisioning URI for authenticator app setup.",
    tags=["Authentication", "MFA"],
    responses={
        "200": {
            "description": "MFA secret and provisioning URI returned",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "secret": {"type": "string"},
                            "provisioning_uri": {"type": "string"},
                            "message": {"type": "string"},
                        },
                    }
                }
            },
        },
        "400": {"description": "MFA already enabled"},
        "401": {"description": "Unauthorized"},
        "404": {"description": "User not found"},
        "503": {"description": "MFA not available"},
    },
)
@auth_rate_limit(requests_per_minute=5, limiter_name="mfa_setup", endpoint_name="MFA setup")
@handle_errors("MFA setup")
@log_request("MFA setup")
def handle_mfa_setup(handler_instance: AuthHandler, handler) -> HandlerResult:
    """Generate MFA secret and provisioning URI for setup."""
    # RBAC check: authentication.create permission required
    if error := handler_instance._check_permission(handler, "authentication.create"):
        return error

    try:
        import pyotp
    except ImportError:
        return error_response("MFA not available (pyotp not installed)", 503)

    # Get current user (already verified by _check_permission)
    user_store = handler_instance._get_user_store()
    auth_ctx = extract_user_from_request(handler, user_store)

    user = user_store.get_user_by_id(auth_ctx.user_id)
    if not user:
        return error_response("User not found", 404)

    if user.mfa_enabled:
        return error_response("MFA is already enabled", 400)

    # Generate new secret
    secret = pyotp.random_base32()

    # Store secret temporarily (not enabled yet)
    user_store.update_user(user.id, mfa_secret=secret)

    # Generate provisioning URI for authenticator apps
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name="Aragora")

    return json_response(
        {
            "secret": secret,
            "provisioning_uri": provisioning_uri,
            "message": "Scan QR code or enter secret in your authenticator app, then call /api/auth/mfa/enable with verification code",
        }
    )


@api_endpoint(
    method="POST",
    path="/api/auth/mfa/enable",
    summary="Enable MFA",
    description="Enable MFA after verifying setup code from authenticator app.",
    tags=["Authentication", "MFA"],
    responses={
        "200": {
            "description": "MFA enabled, backup codes returned",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string"},
                            "backup_codes": {"type": "array", "items": {"type": "string"}},
                            "warning": {"type": "string"},
                            "sessions_invalidated": {"type": "boolean"},
                        },
                    }
                }
            },
        },
        "400": {"description": "Invalid verification code or MFA not set up"},
        "401": {"description": "Unauthorized"},
        "404": {"description": "User not found"},
        "503": {"description": "MFA not available"},
    },
)
@auth_rate_limit(requests_per_minute=5, limiter_name="mfa_enable", endpoint_name="MFA enable")
@handle_errors("MFA enable")
@log_request("MFA enable")
def handle_mfa_enable(handler_instance: AuthHandler, handler) -> HandlerResult:
    """Enable MFA after verifying setup code."""
    # RBAC check: authentication.update permission required
    if error := handler_instance._check_permission(handler, "authentication.update"):
        return error

    try:
        import pyotp
    except ImportError:
        return error_response("MFA not available", 503)

    body = handler_instance.read_json_body(handler)
    if body is None:
        return error_response("Invalid JSON body", 400)

    code = body.get("code", "").strip()
    if not code:
        return error_response("Verification code is required", 400)

    # Get current user (already verified by _check_permission)
    user_store = handler_instance._get_user_store()
    auth_ctx = extract_user_from_request(handler, user_store)

    user = user_store.get_user_by_id(auth_ctx.user_id)
    if not user:
        return error_response("User not found", 404)

    if user.mfa_enabled:
        return error_response("MFA is already enabled", 400)

    if not user.mfa_secret:
        return error_response("MFA not set up. Call /api/auth/mfa/setup first", 400)

    # Verify the code
    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(code, valid_window=1):
        return error_response("Invalid verification code", 400)

    # Generate backup codes
    backup_codes = [py_secrets.token_hex(4) for _ in range(10)]
    backup_hashes = [hashlib.sha256(c.encode()).hexdigest() for c in backup_codes]

    user_store.update_user(
        user.id,
        mfa_enabled=True,
        mfa_backup_codes=json_module.dumps(backup_hashes),
    )

    # Invalidate all existing sessions by incrementing token version
    user_store.increment_token_version(user.id)

    logger.info("MFA enabled for user_id=%s", user.id)

    # Audit log: MFA enabled
    if AUDIT_AVAILABLE and audit_security:
        audit_security(
            event_type="encryption",
            actor_id=user.id,
            reason="mfa_enabled",
        )

    emit_handler_event("auth", COMPLETED, {"action": "mfa_enabled"}, user_id=user.id)
    return json_response(
        {
            "message": "MFA enabled successfully",
            "backup_codes": backup_codes,
            "warning": "Save these backup codes securely. They cannot be shown again.",
            "sessions_invalidated": True,
        }
    )


@api_endpoint(
    method="POST",
    path="/api/auth/mfa/disable",
    summary="Disable MFA",
    description="Disable MFA for the user. Requires MFA code or password verification.",
    tags=["Authentication", "MFA"],
    responses={
        "200": {
            "description": "MFA disabled successfully",
            "content": {
                "application/json": {
                    "schema": {"type": "object", "properties": {"message": {"type": "string"}}}
                }
            },
        },
        "400": {"description": "Invalid code/password or MFA not enabled"},
        "401": {"description": "Unauthorized"},
        "404": {"description": "User not found"},
        "503": {"description": "MFA not available"},
    },
)
@auth_rate_limit(requests_per_minute=5, limiter_name="mfa_disable", endpoint_name="MFA disable")
@handle_errors("MFA disable")
@log_request("MFA disable")
def handle_mfa_disable(handler_instance: AuthHandler, handler) -> HandlerResult:
    """Disable MFA for the user."""
    # RBAC check: authentication.update permission required
    if error := handler_instance._check_permission(handler, "authentication.update"):
        return error

    try:
        import pyotp
    except ImportError:
        return error_response("MFA not available", 503)

    body = handler_instance.read_json_body(handler)
    if body is None:
        return error_response("Invalid JSON body", 400)

    # Require password or MFA code to disable
    code = body.get("code", "").strip()
    password = body.get("password", "").strip()

    if not code and not password:
        return error_response("MFA code or password required to disable MFA", 400)

    # Get current user (already verified by _check_permission)
    user_store = handler_instance._get_user_store()
    auth_ctx = extract_user_from_request(handler, user_store)

    user = user_store.get_user_by_id(auth_ctx.user_id)
    if not user:
        return error_response("User not found", 404)

    if not user.mfa_enabled:
        return error_response("MFA is not enabled", 400)

    # Verify with code or password
    if code:
        totp = pyotp.TOTP(user.mfa_secret)
        if not totp.verify(code, valid_window=1):
            return error_response("Invalid MFA code", 400)
    elif password:
        if not user.verify_password(password):
            return error_response("Invalid password", 400)

    # Disable MFA
    user_store.update_user(
        user.id,
        mfa_enabled=False,
        mfa_secret=None,
        mfa_backup_codes=None,
    )

    logger.info("MFA disabled for user_id=%s", user.id)

    # Audit log: MFA disabled
    if AUDIT_AVAILABLE and audit_security:
        audit_security(
            event_type="encryption",
            actor_id=user.id,
            reason="mfa_disabled",
        )

    emit_handler_event("auth", UPDATED, {"action": "mfa_disabled"}, user_id=user.id)
    return json_response({"message": "MFA disabled successfully"})


@api_endpoint(
    method="POST",
    path="/api/auth/mfa/verify",
    summary="Verify MFA code during login",
    description="Complete login by verifying MFA code. Accepts TOTP code or backup code.",
    tags=["Authentication", "MFA"],
    responses={
        "200": {
            "description": "MFA verified, tokens returned",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string"},
                            "user": {"type": "object", "additionalProperties": True},
                            "tokens": {
                                "type": "object",
                                "properties": {
                                    "access_token": {"type": "string"},
                                    "refresh_token": {"type": "string"},
                                    "token_type": {"type": "string"},
                                    "expires_in": {"type": "integer"},
                                },
                            },
                            "backup_codes_remaining": {"type": "integer"},
                            "warning": {"type": "string"},
                        },
                        "additionalProperties": True,
                    }
                }
            },
        },
        "400": {"description": "Invalid MFA code"},
        "401": {"description": "Invalid or expired pending token"},
        "404": {"description": "User not found"},
        "503": {"description": "MFA not available"},
    },
)
@auth_rate_limit(
    requests_per_minute=10, limiter_name="mfa_verify", endpoint_name="MFA verification"
)
@handle_errors("MFA verify")
@log_request("MFA verify")
def handle_mfa_verify(handler_instance: AuthHandler, handler) -> HandlerResult:
    """Verify MFA code during login."""
    from aragora.billing.jwt_auth import create_token_pair, validate_mfa_pending_token

    try:
        import pyotp
    except ImportError:
        return error_response("MFA not available", 503)

    body = handler_instance.read_json_body(handler)
    if body is None:
        return error_response("Invalid JSON body", 400)

    code = body.get("code", "").strip()
    pending_token = body.get("pending_token", "").strip()

    if not code:
        return error_response("MFA code is required", 400)

    if not pending_token:
        return error_response("Pending token is required", 400)

    # Validate the pending token to identify the user
    pending_payload = validate_mfa_pending_token(pending_token)
    if not pending_payload:
        return error_response("Invalid or expired pending token", 401)

    user_store = handler_instance._get_user_store()
    if not user_store:
        return error_response("Authentication service unavailable", 503)

    user = user_store.get_user_by_id(pending_payload.sub)
    if not user:
        return error_response("User not found", 404)

    if not user.mfa_enabled or not user.mfa_secret:
        return error_response("MFA not enabled for this user", 400)

    # Try TOTP code first
    totp = pyotp.TOTP(user.mfa_secret)
    if totp.verify(code, valid_window=1):
        # Blacklist pending token to prevent replay
        from aragora.billing.jwt_auth import get_token_blacklist

        blacklist = get_token_blacklist()
        blacklist.revoke_token(pending_token)

        # Valid TOTP code - create full tokens
        tokens = create_token_pair(
            user_id=user.id,
            email=user.email,
            org_id=user.org_id,
            role=user.role,
        )
        token_dict = tokens.to_dict()
        logger.info("MFA verified for user_id=%s", user.id)
        return json_response(
            {
                "message": "MFA verification successful",
                "user": user.to_dict(),
                "tokens": token_dict,
            }
        )

    # Try backup code
    if user.mfa_backup_codes:
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        backup_hashes = json_module.loads(user.mfa_backup_codes)

        if code_hash in backup_hashes:
            # Valid backup code - remove it
            backup_hashes.remove(code_hash)
            user_store.update_user(
                user.id,
                mfa_backup_codes=json_module.dumps(backup_hashes),
            )

            # Blacklist pending token to prevent replay
            from aragora.billing.jwt_auth import get_token_blacklist

            blacklist = get_token_blacklist()
            blacklist.revoke_token(pending_token)

            tokens = create_token_pair(
                user_id=user.id,
                email=user.email,
                org_id=user.org_id,
                role=user.role,
            )
            token_dict = tokens.to_dict()
            remaining = len(backup_hashes)

            logger.info("Backup code used for user_id=%s, %s remaining", user.id, remaining)

            return json_response(
                {
                    "message": "MFA verification successful (backup code used)",
                    "user": user.to_dict(),
                    "tokens": token_dict,
                    "backup_codes_remaining": remaining,
                    "warning": (
                        f"Backup code used. {remaining} remaining." if remaining < 5 else None
                    ),
                }
            )

    return error_response("Invalid MFA code", 400)


@api_endpoint(
    method="POST",
    path="/api/auth/mfa/backup-codes",
    summary="Regenerate MFA backup codes",
    description="Generate new backup codes. Requires current MFA code for verification.",
    tags=["Authentication", "MFA"],
    responses={
        "200": {
            "description": "New backup codes generated",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "backup_codes": {"type": "array", "items": {"type": "string"}},
                            "warning": {"type": "string"},
                        },
                    }
                }
            },
        },
        "400": {"description": "Invalid MFA code or MFA not enabled"},
        "401": {"description": "Unauthorized"},
        "404": {"description": "User not found"},
        "503": {"description": "MFA not available"},
    },
)
@auth_rate_limit(requests_per_minute=5, limiter_name="mfa_backup", endpoint_name="MFA backup codes")
@handle_errors("MFA backup codes")
@log_request("MFA backup codes")
def handle_mfa_backup_codes(handler_instance: AuthHandler, handler) -> HandlerResult:
    """Regenerate MFA backup codes."""
    # RBAC check: authentication.read permission required
    if error := handler_instance._check_permission(handler, "authentication.read"):
        return error

    try:
        import pyotp
    except ImportError:
        return error_response("MFA not available", 503)

    body = handler_instance.read_json_body(handler)
    if body is None:
        return error_response("Invalid JSON body", 400)

    # Require current MFA code to regenerate backup codes
    code = body.get("code", "").strip()
    if not code:
        return error_response("Current MFA code is required", 400)

    # Get current user (already verified by _check_permission)
    user_store = handler_instance._get_user_store()
    auth_ctx = extract_user_from_request(handler, user_store)

    user = user_store.get_user_by_id(auth_ctx.user_id)
    if not user:
        return error_response("User not found", 404)

    if not user.mfa_enabled or not user.mfa_secret:
        return error_response("MFA not enabled", 400)

    # Verify current code
    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(code, valid_window=1):
        return error_response("Invalid MFA code", 400)

    # Generate new backup codes
    backup_codes = [py_secrets.token_hex(4) for _ in range(10)]
    backup_hashes = [hashlib.sha256(c.encode()).hexdigest() for c in backup_codes]

    user_store.update_user(
        user.id,
        mfa_backup_codes=json_module.dumps(backup_hashes),
    )

    logger.info("Backup codes regenerated for user_id=%s", user.id)

    return json_response(
        {
            "backup_codes": backup_codes,
            "warning": "Save these backup codes securely. They cannot be shown again.",
        }
    )


@api_endpoint(
    method="GET",
    path="/api/v1/admin/mfa/compliance",
    summary="Get admin MFA compliance report",
    description="Returns a compliance report showing how many admin users have MFA enabled.",
    tags=["Admin", "MFA", "Compliance"],
    responses={
        "200": {
            "description": "MFA compliance report",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "total_admins": {"type": "integer"},
                            "mfa_enabled_count": {"type": "integer"},
                            "mfa_disabled_count": {"type": "integer"},
                            "in_grace_period": {"type": "integer"},
                            "compliance_pct": {"type": "number"},
                            "non_compliant_users": {
                                "type": "array",
                                "items": {"type": "object"},
                            },
                        },
                    }
                }
            },
        },
        "401": {"description": "Unauthorized"},
        "403": {"description": "Permission denied"},
    },
)
@handle_errors("MFA compliance report")
@log_request("MFA compliance report")
def handle_mfa_compliance(handler_instance: "AuthHandler", handler) -> HandlerResult:
    """Return an admin MFA compliance report.

    Scans all users from the user store, filters for admin roles, and
    reports how many have MFA enabled, disabled, or are still within
    the grace period.
    """
    from aragora.auth.mfa_enforcement import DEFAULT_MFA_REQUIRED_ROLES

    # RBAC check: admin:read permission required
    if error := handler_instance._check_permission(handler, "admin:read"):
        return error

    user_store = handler_instance._get_user_store()
    if not user_store:
        return error_response("User service unavailable", 503)

    try:
        all_users = _enumerate_users_for_compliance(user_store)
    except AttributeError:
        return error_response("User store does not support listing users", 501)
    except (RuntimeError, ValueError, TypeError, AttributeError):
        return error_response("Failed to list users", 500)

    # Filter for admin roles
    admin_users = []
    for user in all_users:
        role = str(getattr(user, "role", "")).lower()
        roles = getattr(user, "roles", None)
        is_admin = role in DEFAULT_MFA_REQUIRED_ROLES
        if not is_admin and roles:
            for r in roles:
                if str(r).lower() in DEFAULT_MFA_REQUIRED_ROLES:
                    is_admin = True
                    break
        if is_admin:
            admin_users.append(user)

    # Compute compliance
    mfa_enabled_count = 0
    in_grace_period = 0
    non_compliant_users: list[dict] = []

    for user in admin_users:
        user_id = str(getattr(user, "id", getattr(user, "user_id", "unknown")))
        role = str(getattr(user, "role", "admin"))
        mfa_enabled = bool(getattr(user, "mfa_enabled", False))

        if mfa_enabled:
            mfa_enabled_count += 1
            continue

        has_grace = bool(getattr(user, "mfa_grace_period_started_at", None))
        if has_grace:
            in_grace_period += 1

        non_compliant_users.append(
            {
                "user_id": user_id,
                "role": role,
                "in_grace_period": has_grace,
            }
        )

    total_admins = len(admin_users)
    mfa_disabled_count = total_admins - mfa_enabled_count
    compliance_pct = (mfa_enabled_count / total_admins * 100.0) if total_admins > 0 else 100.0

    return json_response(
        {
            "total_admins": total_admins,
            "mfa_enabled_count": mfa_enabled_count,
            "mfa_disabled_count": mfa_disabled_count,
            "in_grace_period": in_grace_period,
            "compliance_pct": round(compliance_pct, 2),
            "non_compliant_users": non_compliant_users,
        }
    )


__all__ = [
    "handle_mfa_setup",
    "handle_mfa_enable",
    "handle_mfa_disable",
    "handle_mfa_verify",
    "handle_mfa_backup_codes",
    "handle_mfa_compliance",
]
