"""
Login and Registration Handlers.

Handles user authentication endpoints:
- POST /api/auth/register - Create a new user account
- POST /api/auth/login - Authenticate and get tokens
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast

from aragora.auth.lockout import get_lockout_tracker  # noqa: F401

from aragora.events.handler_events import emit_handler_event, CREATED, COMPLETED, FAILED
from ..base import HandlerResult, error_response, json_response, handle_errors, log_request
from ..openapi_decorator import api_endpoint
from ..utils.rate_limit import auth_rate_limit, get_client_ip, get_exact_client_ip
from .validation import validate_email, validate_password

if TYPE_CHECKING:
    from .handler import AuthHandler

# Unified audit logging
try:
    from aragora.audit.unified import audit_admin, audit_login, audit_security

    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False
    audit_admin = audit_login = audit_security = cast(Any, None)

logger = logging.getLogger(__name__)


@api_endpoint(
    method="POST",
    path="/api/auth/register",
    summary="Register a new user account",
    description="Create a new user account with email, password, and optional organization.",
    tags=["Authentication"],
    auth_required=False,
    responses={
        "201": {
            "description": "User created successfully",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "user": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "email": {"type": "string"},
                                    "org_id": {"type": "string"},
                                    "role": {"type": "string"},
                                    "name": {"type": "string"},
                                },
                                "additionalProperties": True,
                            },
                            "tokens": {
                                "type": "object",
                                "properties": {
                                    "access_token": {"type": "string"},
                                    "refresh_token": {"type": "string"},
                                    "token_type": {"type": "string"},
                                    "expires_in": {"type": "integer"},
                                },
                            },
                        },
                    }
                }
            },
        },
        "400": {"description": "Invalid request body or validation error"},
        "409": {"description": "Email already registered"},
        "503": {"description": "User service unavailable"},
    },
)
@auth_rate_limit(
    requests_per_minute=5, limiter_name="auth_register", endpoint_name="user registration"
)
@handle_errors("user registration")
@log_request("user registration")
def handle_register(handler_instance: AuthHandler, handler) -> HandlerResult:
    """Handle user registration."""
    from aragora.billing.jwt_auth import create_token_pair
    from aragora.billing.models import hash_password

    # Parse request body
    body = handler_instance.read_json_body(handler)
    if body is None:
        return error_response("Invalid JSON body", 400)

    # Extract and validate fields
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    name = body.get("name", "").strip()
    org_name = body.get("organization", "").strip()

    # Validate email
    valid, err = validate_email(email)
    if not valid:
        return error_response(err, 400)

    # Validate password
    valid, err = validate_password(password)
    if not valid:
        return error_response(err, 400)

    # Get user store
    user_store = handler_instance._get_user_store()
    if not user_store:
        return error_response("User service unavailable", 503)

    # Check if email already exists
    existing = user_store.get_user_by_email(email)
    if existing:
        return error_response("Email already registered", 409)

    # Hash password
    password_hash, password_salt = hash_password(password)

    # Create user first (without org)
    try:
        user = user_store.create_user(
            email=email,
            password_hash=password_hash,
            password_salt=password_salt,
            name=name or email.split("@")[0],
        )
    except ValueError as e:
        logger.warning("User creation failed: %s: %s", type(e).__name__, e)
        return error_response("User creation failed", 409)

    # Create organization if name provided
    if org_name:
        user_store.create_organization(
            name=org_name,
            owner_id=user.id,
        )
        # Refresh user to get updated org_id
        user = user_store.get_user_by_id(user.id)

    # Create tokens
    tokens = create_token_pair(
        user_id=user.id,
        email=user.email,
        org_id=user.org_id,
        role=user.role,
    )

    logger.info("User registered: id=%s", user.id)

    # Audit log: user registration
    if AUDIT_AVAILABLE and audit_admin:
        audit_admin(
            admin_id=user.id,
            action="user_registered",
            target_type="user",
            target_id=user.id,
        )

    emit_handler_event("auth", CREATED, {"action": "register"}, user_id=user.id)

    # Include organization data so frontend doesn't need a second request
    org_data = None
    org_membership = []
    if user.org_id:
        org = user_store.get_organization_by_id(user.org_id)
        if org:
            org_data = org.to_dict()
            joined_at = getattr(user, "created_at", None)
            org_membership = [
                {
                    "user_id": user.id,
                    "org_id": org.id,
                    "organization": org_data,
                    "role": user.role or "member",
                    "is_default": True,
                    "joined_at": joined_at.isoformat() if joined_at else None,
                }
            ]

    return json_response(
        {
            "user": user.to_dict(),
            "tokens": tokens.to_dict(),
            "organization": org_data,
            "organizations": org_membership,
        },
        status=201,
    )


@api_endpoint(
    method="POST",
    path="/api/auth/login",
    summary="Authenticate user and obtain tokens",
    description="Authenticate with email and password. Returns JWT tokens or MFA challenge if enabled.",
    tags=["Authentication"],
    auth_required=False,
    responses={
        "200": {
            "description": "Login successful, tokens returned",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
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
                            "mfa_required": {"type": "boolean"},
                            "pending_token": {"type": "string"},
                            "message": {"type": "string"},
                        },
                        "additionalProperties": True,
                    }
                }
            },
        },
        "400": {"description": "Invalid request body"},
        "401": {"description": "Invalid credentials or account disabled"},
        "429": {"description": "Account locked due to too many failed attempts"},
        "503": {"description": "Authentication service unavailable"},
    },
)
@auth_rate_limit(requests_per_minute=5, limiter_name="auth_login", endpoint_name="user login")
@handle_errors("user login")
@log_request("user login")
def handle_login(handler_instance: AuthHandler, handler) -> HandlerResult:
    """Handle user login."""
    from aragora.billing.jwt_auth import create_mfa_pending_token, create_token_pair

    # Parse request body
    body = handler_instance.read_json_body(handler)
    if body is None:
        return error_response("Invalid JSON body", 400)

    email = body.get("email", "")
    password = body.get("password", "")

    if not isinstance(email, str) or not isinstance(password, str):
        return error_response("Email and password must be strings", 400)

    email = email.strip().lower()

    if not email or not password:
        return error_response("Email and password required", 400)

    # Lockout is keyed like the rate limiters (IPv6 by /64); audit records get the exact address.
    client_ip = get_client_ip(handler)
    audit_ip = get_exact_client_ip(handler)

    # Get user store
    user_store = handler_instance._get_user_store()
    if not user_store:
        return error_response("Authentication service unavailable", 503)

    # Check lockout tracker (tracks by email AND IP)
    use_handler_tracker = False
    if hasattr(handler_instance, "_get_lockout_tracker"):
        module_name = getattr(handler_instance.__class__, "__module__", "")
        if module_name.startswith("aragora.server.handlers.auth"):
            use_handler_tracker = True
    lockout_tracker = (
        handler_instance._get_lockout_tracker() if use_handler_tracker else get_lockout_tracker()
    )
    if lockout_tracker.is_locked(email=email, ip=client_ip):
        remaining_seconds = lockout_tracker.get_remaining_time(email=email, ip=client_ip)
        remaining_minutes = max(1, remaining_seconds // 60)
        logger.warning("Login attempt on locked account/IP: ip=%s", audit_ip)
        return error_response(
            f"Too many failed attempts. Try again in {remaining_minutes} minute(s).", 429
        )

    # Also check database-based account lockout (legacy support)
    if hasattr(user_store, "is_account_locked"):
        is_locked, lockout_until, failed_attempts = user_store.is_account_locked(email)
        if is_locked and lockout_until:
            remaining_minutes = max(
                1, int((lockout_until - datetime.now(timezone.utc)).total_seconds() / 60)
            )
            logger.warning("Login attempt on locked account (db)")
            return error_response(
                f"Account temporarily locked. Try again in {remaining_minutes} minute(s).", 429
            )

    # Find user
    user = user_store.get_user_by_email(email)
    if not user:
        # Record failed attempt to lockout tracker (prevents enumeration attacks)
        lockout_tracker.record_failure(email=email, ip=client_ip)
        # Use same error to prevent email enumeration
        return error_response("Invalid email or password", 401)

    # Check if account is active
    # 401: account disabled means the user cannot authenticate
    if not user.is_active:
        return error_response("Account is disabled", 401)

    # Verify password
    if not user.verify_password(password):
        # Record failed login attempt to both trackers
        attempts, lockout_seconds = lockout_tracker.record_failure(email=email, ip=client_ip)

        # Also record in database for persistence across restarts
        if hasattr(user_store, "record_failed_login"):
            db_attempts, lockout_until = user_store.record_failed_login(email)

        if lockout_seconds:
            remaining_minutes = max(1, lockout_seconds // 60)
            # Audit log: account lockout
            if AUDIT_AVAILABLE and audit_security:
                audit_security(
                    event_type="anomaly",
                    actor_id=email,
                    ip_address=audit_ip,
                    reason="account_locked_due_to_failed_attempts",
                )
            return error_response(
                f"Too many failed attempts. Account locked for {remaining_minutes} minute(s).",
                429,
            )
        # Audit log: failed login
        if AUDIT_AVAILABLE and audit_login:
            audit_login(email, success=False, ip_address=audit_ip, method="password")
        emit_handler_event("auth", FAILED, {"action": "login", "email": email})
        return error_response("Invalid email or password", 401)

    # Successful login - reset failed attempts in both trackers
    lockout_tracker.reset(email=email, ip=client_ip)
    if hasattr(user_store, "reset_failed_login_attempts"):
        user_store.reset_failed_login_attempts(email)

    # Update last login
    user_store.update_user(user.id, last_login_at=datetime.now(timezone.utc))

    # Check if MFA is enabled - require second factor before issuing tokens
    if user.mfa_enabled and user.mfa_secret:
        pending_token = create_mfa_pending_token(user.id, user.email)
        logger.info("User login pending MFA: user_id=%s", user.id)
        return json_response(
            {
                "mfa_required": True,
                "pending_token": pending_token,
                "message": "MFA verification required",
            }
        )

    # No MFA - create full tokens
    tokens = create_token_pair(
        user_id=user.id,
        email=user.email,
        org_id=user.org_id,
        role=user.role,
    )

    logger.info("User logged in: user_id=%s", user.id)

    # Audit log: successful login
    if AUDIT_AVAILABLE and audit_login:
        audit_login(user.id, success=True, ip_address=audit_ip, method="password")

    emit_handler_event("auth", COMPLETED, {"action": "login"}, user_id=user.id)

    # Include organization data so frontend doesn't need a second request
    org_data = None
    org_membership = []
    if user.org_id:
        org = user_store.get_organization_by_id(user.org_id)
        if org:
            org_data = org.to_dict()
            joined_at = getattr(user, "created_at", None)
            org_membership = [
                {
                    "user_id": user.id,
                    "org_id": org.id,
                    "organization": org_data,
                    "role": user.role or "member",
                    "is_default": True,
                    "joined_at": joined_at.isoformat() if joined_at else None,
                }
            ]

    return json_response(
        {
            "user": user.to_dict(),
            "tokens": tokens.to_dict(),
            "organization": org_data,
            "organizations": org_membership,
        }
    )


__all__ = ["handle_register", "handle_login"]
