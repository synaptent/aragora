"""
HTTP API Handlers for Self-Service Signup.

Provides REST APIs for self-service organization/user signup:
- User registration
- Email verification
- Organization creation
- Team invitations

Endpoints:
- POST /api/v1/auth/signup - Register new user
- POST /api/v1/auth/verify-email - Verify email address
- POST /api/v1/auth/resend-verification - Resend verification email
- POST /api/v1/auth/setup-organization - Create organization after signup
- POST /api/v1/auth/invite - Invite team member
- POST /api/v1/auth/accept-invite - Accept team invitation
- GET /api/v1/auth/check-invite - Check invitation validity
"""

from __future__ import annotations

import logging
import re
import secrets
import threading

from aragora.events.handler_events import emit_handler_event, CREATED
import time
from datetime import datetime, timezone
from typing import Any

from aragora.api_errors import safe_error_message
from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    success_response,
)
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.rbac.checker import get_permission_checker
from aragora.rbac.models import AuthorizationContext

logger = logging.getLogger(__name__)


def _check_permission(
    user_id: str,
    permission: str,
    org_id: str | None = None,
    roles: set | None = None,
) -> HandlerResult | None:
    """Check RBAC permission. Returns error response if denied, None if allowed."""
    try:
        context = AuthorizationContext(
            user_id=user_id,
            org_id=org_id,
            roles=roles if roles else {"member"},
            permissions=set(),
        )
        checker = get_permission_checker()
        decision = checker.check_permission(context, permission)
        if not decision.allowed:
            logger.warning("RBAC denied %s for user %s: %s", permission, user_id, decision.reason)
            return error_response("Permission denied", status=403)
        return None
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        logger.error("RBAC check failed: %s", e)
        return error_response("Authorization check failed", status=500)


# In-memory storage (replace with DB in production)
_pending_signups: dict[str, dict[str, Any]] = {}
_pending_signups_lock = threading.Lock()

_pending_invites: dict[str, dict[str, Any]] = {}
_pending_invites_lock = threading.Lock()

# Verification token TTL (24 hours)
VERIFICATION_TTL = 86400

# Invite TTL (7 days)
INVITE_TTL = 604800

# Email regex
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")

# Password requirements
MIN_PASSWORD_LENGTH = 8

# Supported self-serve organization plans
SUPPORTED_ORG_PLANS = {"free", "team", "enterprise"}


def _generate_verification_token() -> str:
    """Generate a secure verification token."""
    return secrets.token_urlsafe(32)


def _hash_password(password: str) -> str:
    """Hash password using bcrypt via billing.models.

    Uses secure bcrypt hashing with automatic salt generation.
    Falls back to SHA-256 only when ARAGORA_ALLOW_INSECURE_PASSWORDS=1.
    """
    from aragora.billing.models import hash_password

    hashed, _ = hash_password(password)
    return hashed


def _validate_password(password: str) -> list[str]:
    """Validate password strength."""
    errors = []

    if len(password) < MIN_PASSWORD_LENGTH:
        errors.append(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")

    if not re.search(r"[a-z]", password):
        errors.append("Password must contain a lowercase letter")

    if not re.search(r"[A-Z]", password):
        errors.append("Password must contain an uppercase letter")

    if not re.search(r"\d", password):
        errors.append("Password must contain a number")

    return errors


def _cleanup_expired_tokens():
    """Remove expired verification tokens and invites."""
    now = time.time()

    with _pending_signups_lock:
        expired = [
            token
            for token, data in _pending_signups.items()
            if now - data.get("created_at", 0) > VERIFICATION_TTL
        ]
        for token in expired:
            del _pending_signups[token]

    with _pending_invites_lock:
        expired = [
            token
            for token, data in _pending_invites.items()
            if now - data.get("created_at", 0) > INVITE_TTL
        ]
        for token in expired:
            del _pending_invites[token]


# =============================================================================
# User Registration
# =============================================================================


@rate_limit(rpm=5, limiter_name="auth_signup")
async def handle_signup(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Register a new user.

    POST /api/v1/auth/signup
    Body: {
        email: str,
        password: str,
        name: str,
        company_name: str (optional),
        invite_token: str (optional) - If joining via invitation
    }
    """
    try:
        email_value = data.get("email", "")
        password = data.get("password", "")
        name_value = data.get("name", "")
        company_name_value = data.get("company_name", "")
        invite_token = data.get("invite_token")

        if not isinstance(email_value, str):
            return error_response("Email must be a string", status=400)
        if not isinstance(password, str):
            return error_response("Password must be a string", status=400)
        if not isinstance(name_value, str):
            return error_response("Name must be a string", status=400)
        if "company_name" in data and not isinstance(company_name_value, str):
            return error_response("Company name must be a string", status=400)
        if invite_token is not None and not isinstance(invite_token, str):
            return error_response("Invite token must be a string", status=400)

        email = email_value.lower().strip()
        name = name_value.strip()
        company_name = company_name_value.strip()

        # Validate email
        if not email or not EMAIL_REGEX.match(email):
            return error_response("Invalid email address", status=400)

        # Validate password
        password_errors = _validate_password(password)
        if password_errors:
            return error_response(
                "Password requirements not met",
                status=400,
            )

        # Validate name
        if not name or len(name) < 2:
            return error_response("Name must be at least 2 characters", status=400)

        # Check if email already registered (would check DB in production)
        # For now, check pending signups
        with _pending_signups_lock:
            for signup_data in _pending_signups.values():
                if signup_data.get("email") == email:
                    return error_response(
                        "Email already pending verification",
                        status=409,
                    )

        # Check for invitation
        invite_data = None
        if invite_token:
            with _pending_invites_lock:
                invite_data = _pending_invites.get(invite_token)
                if invite_data:
                    if invite_data.get("email") != email:
                        return error_response(
                            "Email does not match invitation",
                            status=400,
                        )
                    if time.time() - invite_data.get("created_at", 0) > INVITE_TTL:
                        return error_response(
                            "Invitation has expired",
                            status=400,
                        )

        # Generate verification token
        verification_token = _generate_verification_token()

        # Store pending signup
        signup_record = {
            "email": email,
            "password_hash": _hash_password(password),
            "name": name,
            "company_name": company_name,
            "invite_token": invite_token,
            "invite_data": invite_data,
            "created_at": time.time(),
            "verified": False,
        }

        with _pending_signups_lock:
            _pending_signups[verification_token] = signup_record

        # Cleanup old tokens periodically
        if len(_pending_signups) % 10 == 0:
            _cleanup_expired_tokens()

        # In production: send verification email
        logger.info("Signup initiated for %s", email)

        # Audit logging (security-sensitive action)
        try:
            from aragora.audit.unified import audit_action

            audit_action(
                user_id="anonymous",
                action="signup_initiated",
                resource_type="user",
                email=email,
            )
        except ImportError:
            pass  # Audit not available

        emit_handler_event("auth", CREATED, {"action": "signup", "email": email})
        return success_response(
            {
                "message": "Verification email sent",
                "email": email,
                "verification_token": verification_token,  # Remove in production
                "expires_in": VERIFICATION_TTL,
            }
        )

    except (ValueError, KeyError, TypeError, ImportError, OSError) as e:
        logger.exception("Signup failed")
        return error_response(f"Signup failed: {safe_error_message(e, 'signup')}", status=500)


@rate_limit(rpm=10, limiter_name="auth_verify")
async def handle_verify_email(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Verify email address.

    POST /api/v1/auth/verify-email
    Body: {
        token: str
    }
    """
    try:
        token = data.get("token", "")

        if not token:
            return error_response("Verification token is required", status=400)

        with _pending_signups_lock:
            signup_data = _pending_signups.get(token)

            if not signup_data:
                return error_response("Invalid or expired token", status=400)

            if time.time() - signup_data.get("created_at", 0) > VERIFICATION_TTL:
                del _pending_signups[token]
                return error_response("Verification token has expired", status=400)

            # Mark as verified
            signup_data["verified"] = True
            signup_data["verified_at"] = time.time()

        # In production: create user in database
        email = signup_data["email"]
        name = signup_data["name"]

        # Generate user ID
        user_id = f"user_{secrets.token_hex(8)}"

        # Create JWT token
        from aragora.billing.jwt_auth import create_access_token

        access_token = create_access_token(user_id=user_id, email=email)

        # Remove from pending signups
        with _pending_signups_lock:
            del _pending_signups[token]

        # If this was an invite, remove the invite
        if signup_data.get("invite_token"):
            with _pending_invites_lock:
                _pending_invites.pop(signup_data["invite_token"], None)

        invite_data = signup_data.get("invite_data") or {}
        return success_response(
            {
                "message": "Email verified successfully",
                "user_id": user_id,
                "email": email,
                "name": name,
                "access_token": access_token,
                "token_type": "bearer",
                "needs_org_setup": not invite_data,
                "organization_id": invite_data.get("organization_id"),
            }
        )

    except (ValueError, KeyError, TypeError, ImportError, RuntimeError, OSError) as e:
        logger.exception("Email verification failed")
        return error_response(
            f"Email verification failed: {safe_error_message(e, 'email verification')}",
            status=500,
        )


@rate_limit(rpm=2, limiter_name="auth_resend")
async def handle_resend_verification(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Resend verification email.

    POST /api/v1/auth/resend-verification
    Body: {
        email: str
    }
    """
    try:
        email = data.get("email", "").lower().strip()

        if not email:
            return error_response("Email is required", status=400)

        # Find pending signup by email
        found_token = None
        with _pending_signups_lock:
            for token, signup_data in _pending_signups.items():
                if signup_data.get("email") == email and not signup_data.get("verified"):
                    found_token = token
                    break

        if not found_token:
            # Don't reveal if email exists
            return success_response(
                {
                    "message": "If email is pending verification, a new email will be sent",
                }
            )

        # In production: resend verification email
        logger.info("Resending verification for %s", email)

        return success_response(
            {
                "message": "Verification email resent",
                "email": email,
            }
        )

    except (ValueError, KeyError, TypeError) as e:
        logger.exception("Resend verification failed")
        return error_response(safe_error_message(e, "resend verification"), status=500)


# =============================================================================
# Organization Setup
# =============================================================================


async def handle_setup_organization(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Create organization after signup.

    POST /api/v1/auth/setup-organization
    Body: {
        name: str,
        slug: str (optional),
        plan: str (optional - free, team, enterprise),
        billing_email: str (optional)
    }
    """
    # RBAC check: requires org:create permission
    if error := _check_permission(user_id, "org:create"):
        return error

    try:
        name_value = data.get("name", "")
        slug_value = data.get("slug", "")
        plan_value = data.get("plan", "free")
        billing_email_value = data.get("billing_email", "")

        if not isinstance(name_value, str):
            return error_response("Organization name must be a string", status=400)
        if "slug" in data and not isinstance(slug_value, str):
            return error_response("Slug must be a string", status=400)
        if not isinstance(plan_value, str):
            return error_response("Plan must be a string", status=400)
        if "billing_email" in data and not isinstance(billing_email_value, str):
            return error_response("Billing email must be a string", status=400)

        name = name_value.strip()
        slug = slug_value.lower().strip()
        plan = plan_value.strip().lower()
        billing_email = billing_email_value.lower().strip()

        if not name or len(name) < 2:
            return error_response("Organization name is required", status=400)

        if plan not in SUPPORTED_ORG_PLANS:
            return error_response(
                "Plan must be one of: free, team, enterprise",
                status=400,
            )

        # Generate slug if not provided
        if not slug:
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

        # Validate slug
        if not re.match(r"^[a-z0-9][a-z0-9-]{2,30}[a-z0-9]$", slug):
            return error_response(
                "Slug must be 4-32 characters, alphanumeric with hyphens",
                status=400,
            )

        # Generate organization ID
        org_id = f"org_{secrets.token_hex(8)}"

        # In production: create organization in database
        organization = {
            "id": org_id,
            "name": name,
            "slug": slug,
            "plan": plan,
            "billing_email": billing_email or None,
            "owner_id": user_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "member_count": 1,
        }

        logger.info("Organization created: %s", org_id)

        # Audit logging (admin action)
        try:
            from aragora.audit.unified import audit_admin

            audit_admin(
                admin_id=user_id,
                action="organization_created",
                target_type="organization",
                target_id=org_id,
                org_name=name,
            )
        except ImportError:
            pass  # Audit not available

        return success_response(
            {
                "organization": organization,
                "message": "Organization created successfully",
            }
        )

    except (ValueError, KeyError, TypeError) as e:
        logger.exception("Organization setup failed")
        return error_response(
            f"Organization setup failed: {safe_error_message(e, 'org setup')}",
            status=500,
        )


# =============================================================================
# Team Invitations
# =============================================================================


@rate_limit(rpm=10, limiter_name="auth_invite")
async def handle_invite(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Invite team member to organization.

    POST /api/v1/auth/invite
    Body: {
        email: str,
        organization_id: str,
        role: str (optional - admin, member, viewer)
    }
    """
    # RBAC: Require permission to invite team members
    rbac_err = _check_permission(user_id, "team.invite", data.get("organization_id"))
    if rbac_err:
        return rbac_err

    try:
        email = data.get("email", "").lower().strip()
        organization_id = data.get("organization_id", "")
        role = data.get("role", "member")

        if not email or not EMAIL_REGEX.match(email):
            return error_response("Invalid email address", status=400)

        if not organization_id:
            return error_response("Organization ID is required", status=400)

        valid_roles = {"admin", "member", "viewer"}
        if role not in valid_roles:
            return error_response(
                f"Invalid role. Must be one of: {', '.join(valid_roles)}",
                status=400,
            )

        # Check for existing pending invite
        with _pending_invites_lock:
            for token, invite in _pending_invites.items():
                if (
                    invite.get("email") == email
                    and invite.get("organization_id") == organization_id
                ):
                    return error_response(
                        "Invitation already pending for this email",
                        status=409,
                    )

        # Generate invite token
        invite_token = _generate_verification_token()

        # Store invitation
        invite_record = {
            "email": email,
            "organization_id": organization_id,
            "role": role,
            "invited_by": user_id,
            "created_at": time.time(),
        }

        with _pending_invites_lock:
            _pending_invites[invite_token] = invite_record

        # In production: send invitation email
        invite_url = f"/invite/{invite_token}"
        logger.info("Invitation sent for org %s", organization_id)

        # Audit logging
        try:
            from aragora.audit.unified import audit_action

            audit_action(
                user_id=user_id,
                action="team_invitation_sent",
                resource_type="invitation",
                organization_id=organization_id,
                invitee_email=email,
                role=role,
            )
        except ImportError:
            pass  # Audit not available

        return success_response(
            {
                "message": "Invitation sent",
                "email": email,
                "invite_token": invite_token,  # Remove in production
                "invite_url": invite_url,
                "expires_in": INVITE_TTL,
            }
        )

    except (ValueError, KeyError, TypeError) as e:
        logger.exception("Invite failed")
        return error_response(
            f"Invite failed: {safe_error_message(e, 'invite')}",
            status=500,
        )


async def handle_check_invite(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Check invitation validity.

    GET /api/v1/auth/check-invite
    Query params:
        token: str
    """
    try:
        token = data.get("token", "")

        if not token:
            return error_response("Token is required", status=400)

        with _pending_invites_lock:
            invite = _pending_invites.get(token)

        if not invite:
            return error_response("Invalid invitation", status=404)

        if time.time() - invite.get("created_at", 0) > INVITE_TTL:
            return error_response("Invitation has expired", status=400)

        return success_response(
            {
                "valid": True,
                "email": invite.get("email"),
                "organization_id": invite.get("organization_id"),
                "role": invite.get("role"),
                "expires_at": invite.get("created_at", 0) + INVITE_TTL,
            }
        )

    except (ValueError, KeyError, TypeError) as e:
        logger.exception("Check invite failed")
        return error_response(safe_error_message(e, "invite check"), status=500)


async def handle_accept_invite(
    data: dict[str, Any],
    user_id: str = "default",
) -> HandlerResult:
    """
    Accept team invitation (for existing users).

    POST /api/v1/auth/accept-invite
    Body: {
        token: str
    }
    """
    # RBAC check: requires team:join permission
    if error := _check_permission(user_id, "team:join"):
        return error

    try:
        token = data.get("token", "")

        if not token:
            return error_response("Token is required", status=400)

        with _pending_invites_lock:
            invite = _pending_invites.get(token)

            if not invite:
                return error_response("Invalid invitation", status=404)

            if time.time() - invite.get("created_at", 0) > INVITE_TTL:
                del _pending_invites[token]
                return error_response("Invitation has expired", status=400)

            # Remove invitation
            del _pending_invites[token]

        # In production: add user to organization
        organization_id = invite.get("organization_id")
        role = invite.get("role")

        logger.info("User joined organization %s", organization_id)

        # Audit logging
        try:
            from aragora.audit.unified import audit_action

            audit_action(
                user_id=user_id,
                action="team_invitation_accepted",
                resource_type="membership",
                organization_id=organization_id,
                role=role,
            )
        except ImportError:
            pass  # Audit not available

        return success_response(
            {
                "message": "Successfully joined organization",
                "organization_id": organization_id,
                "role": role,
            }
        )

    except (ValueError, KeyError, TypeError) as e:
        logger.exception("Accept invite failed")
        return error_response(safe_error_message(e, "accept invite"), status=500)


# =============================================================================
# Onboarding Completion
# =============================================================================

# In-memory onboarding state (replace with DB in production)
_onboarding_status: dict[str, dict[str, Any]] = {}
_onboarding_lock = threading.Lock()


async def handle_onboarding_complete(
    data: dict[str, Any],
    user_id: str = "default",
    organization_id: str = "default",
) -> HandlerResult:
    """
    Mark onboarding as complete for an organization.

    POST /api/v1/onboarding/complete
    Body: {
        first_debate_id: str (optional) - ID of the first debate created
        template_used: str (optional) - Template ID used for first debate
    }
    """
    # RBAC check: requires org:admin permission
    if error := _check_permission(user_id, "org:admin", org_id=organization_id):
        return error

    try:
        first_debate_id = data.get("first_debate_id")
        template_used = data.get("template_used")

        with _onboarding_lock:
            _onboarding_status[organization_id] = {
                "completed": True,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "completed_by": user_id,
                "first_debate_id": first_debate_id,
                "template_used": template_used,
            }

        logger.info("Onboarding completed for org %s by %s", organization_id, user_id)

        return success_response(
            {
                "completed": True,
                "organization_id": organization_id,
                "completed_at": _onboarding_status[organization_id]["completed_at"],
            }
        )

    except (ValueError, KeyError, TypeError) as e:
        logger.exception("Onboarding completion failed")
        return error_response(safe_error_message(e, "onboarding completion"), status=500)


async def handle_onboarding_status(
    organization_id: str = "default",
    user_id: str = "default",
) -> HandlerResult:
    """
    Get onboarding status for an organization.

    GET /api/v1/onboarding/status
    """
    # RBAC check: requires org:read permission
    if error := _check_permission(user_id, "org:read", org_id=organization_id):
        return error

    try:
        with _onboarding_lock:
            status = _onboarding_status.get(organization_id, {})

        if not status:
            return success_response(
                {
                    "completed": False,
                    "organization_id": organization_id,
                    "steps": {
                        "signup": True,  # Must be true to reach this endpoint
                        "organization_created": True,  # Must be true to have org_id
                        "first_debate": False,
                        "first_receipt": False,
                    },
                }
            )

        return success_response(
            {
                "completed": status.get("completed", False),
                "organization_id": organization_id,
                "completed_at": status.get("completed_at"),
                "first_debate_id": status.get("first_debate_id"),
                "template_used": status.get("template_used"),
                "steps": {
                    "signup": True,
                    "organization_created": True,
                    "first_debate": bool(status.get("first_debate_id")),
                    "first_receipt": bool(
                        status.get("first_debate_id")
                    ),  # Receipt is auto-generated
                },
            }
        )

    except (ValueError, KeyError, TypeError) as e:
        logger.exception("Onboarding status check failed")
        return error_response(safe_error_message(e, "status check"), status=500)


# =============================================================================
# Handler Registration
# =============================================================================


def get_signup_handlers() -> dict[str, Any]:
    """Get all signup handlers for registration."""
    return {
        "signup": handle_signup,
        "verify_email": handle_verify_email,
        "resend_verification": handle_resend_verification,
        "setup_organization": handle_setup_organization,
        "invite": handle_invite,
        "check_invite": handle_check_invite,
        "accept_invite": handle_accept_invite,
        "onboarding_complete": handle_onboarding_complete,
        "onboarding_status": handle_onboarding_status,
    }


__all__ = [
    "handle_signup",
    "handle_verify_email",
    "handle_resend_verification",
    "handle_setup_organization",
    "handle_invite",
    "handle_check_invite",
    "handle_accept_invite",
    "handle_onboarding_complete",
    "handle_onboarding_status",
    "get_signup_handlers",
]
