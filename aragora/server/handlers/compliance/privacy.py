"""
Privacy Handler - GDPR/CCPA Compliant Data Export and Account Deletion.

Endpoints:
- GET /api/privacy/export - Export all user data (GDPR Article 15, CCPA Right to Know)
- GET /api/privacy/data-inventory - Get summary of data categories collected
- DELETE /api/privacy/account - Delete user account (GDPR Article 17, CCPA Right to Delete)
- POST /api/privacy/preferences - Update privacy preferences (CCPA Do Not Sell)

SOC 2 Control: P5-01 - User access to personal data
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.billing.jwt_auth import extract_user_from_request
from aragora.rbac.decorators import require_permission

from ..base import (
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
    log_request,
)
from ..utils.rate_limit import rate_limit
from ..secure import SecureHandler

logger = logging.getLogger(__name__)


class PrivacyHandler(SecureHandler):
    """Handler for GDPR/CCPA privacy endpoints.

    Extends SecureHandler for JWT-based authentication, RBAC permission
    enforcement, and security audit logging.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    # Resource type for audit logging
    RESOURCE_TYPE = "privacy"

    ROUTES = [
        "/api/v1/privacy/export",
        "/api/v1/privacy/data-inventory",
        "/api/v1/privacy/account",
        "/api/v1/privacy/preferences",
        "/api/v1/users",
        "/api/v2/users/me/export",
        "/api/v2/users/me/data-inventory",
        "/api/v2/users/me",
    ]

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    @require_permission("privacy:read")
    def handle(
        self, path: str, query_params: dict, handler: Any, method: str = "GET"
    ) -> HandlerResult | None:
        """Route privacy requests to appropriate methods."""
        if hasattr(handler, "command"):
            method = handler.command

        # Data export
        if path in ("/api/v1/privacy/export", "/api/v2/users/me/export") and method == "GET":
            return self._handle_export(handler, query_params)

        # Data inventory
        if (
            path in ("/api/v1/privacy/data-inventory", "/api/v2/users/me/data-inventory")
            and method == "GET"
        ):
            return self._handle_data_inventory(handler)

        # Account deletion
        if path in ("/api/v1/privacy/account", "/api/v2/users/me") and method == "DELETE":
            return self._handle_delete_account(handler)

        # Privacy preferences
        if path == "/api/v1/privacy/preferences" and method in ("GET", "POST"):
            if method == "GET":
                return self._handle_get_preferences(handler)
            return self._handle_update_preferences(handler)

        return error_response("Method not allowed", 405)

    def _get_user_store(self) -> Any:
        """Get user store from context."""
        return self.ctx.get("user_store")

    @rate_limit(requests_per_minute=5, limiter_name="privacy_export")
    @handle_errors("data export")
    @log_request("data export")
    def _handle_export(self, handler, query_params: dict) -> HandlerResult:
        """
        Export all user data in GDPR-compliant format.

        GDPR Article 15: Right of access
        CCPA: Right to know

        Query params:
            format: json (default), csv
        """
        user_store = self._get_user_store()
        auth_ctx = extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return error_response("Not authenticated", 401)

        if not user_store:
            return error_response("Service unavailable", 503)

        # Get full user data
        user = user_store.get_user_by_id(auth_ctx.user_id)
        if not user:
            return error_response("User not found", 404)

        export_format = query_params.get("format", "json")

        # Collect all user data
        export_data = self._collect_user_data(user_store, user)

        # Add export metadata
        export_data["_export_metadata"] = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "format": export_format,
            "data_controller": "Aragora",
            "contact": "privacy@aragora.ai",
            "legal_basis": "GDPR Article 15 / CCPA Right to Know",
        }

        if export_format == "csv":
            return self._format_csv_export(export_data)

        logger.info("Data export completed for user: %s", user.email)

        return json_response(export_data)

    def _collect_user_data(self, user_store: Any, user: Any) -> dict[str, Any]:
        """Collect all data associated with a user."""
        data: dict[str, Any] = {}

        # Profile information
        data["profile"] = {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "is_active": user.is_active,
            "email_verified": user.email_verified,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "updated_at": user.updated_at.isoformat() if user.updated_at else None,
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
            "mfa_enabled": user.mfa_enabled,
        }

        # API key metadata (not the key itself)
        if user.api_key_prefix:
            data["api_key"] = {
                "prefix": user.api_key_prefix,
                "created_at": (
                    user.api_key_created_at.isoformat() if user.api_key_created_at else None
                ),
                "expires_at": (
                    user.api_key_expires_at.isoformat() if user.api_key_expires_at else None
                ),
            }

        # Organization membership
        if user.org_id:
            org = user_store.get_organization_by_id(user.org_id)
            if org:
                data["organization"] = {
                    "id": org.id,
                    "name": org.name,
                    "slug": org.slug,
                    "tier": org.tier.value if hasattr(org.tier, "value") else str(org.tier),
                    "role": user.role,
                    "joined_at": user.created_at.isoformat() if user.created_at else None,
                }

        # OAuth provider links
        oauth_providers = user_store.get_user_oauth_providers(user.id)
        if oauth_providers:
            data["oauth_providers"] = [
                {
                    "provider": p["provider"],
                    "linked_at": p.get("linked_at"),
                }
                for p in oauth_providers
            ]

        # User preferences
        preferences = user_store.get_user_preferences(user.id)
        if preferences:
            data["preferences"] = preferences

        # Audit log (user's own actions, last 90 days)
        audit_entries = user_store.get_audit_log(
            user_id=user.id,
            since=datetime.now(timezone.utc) - timedelta(days=90),
            limit=1000,
        )
        if audit_entries:
            data["audit_log"] = [
                {
                    "timestamp": e["timestamp"],
                    "action": e["action"],
                    "resource_type": e["resource_type"],
                    "resource_id": e.get("resource_id"),
                }
                for e in audit_entries
            ]

        # Usage summary (if part of an org)
        if user.org_id:
            usage = user_store.get_usage_summary(user.org_id)
            if usage:
                data["usage_summary"] = usage

        # Consent records (from preferences)
        if preferences and "consent" in preferences:
            data["consent_records"] = preferences["consent"]

        return data

    def _format_csv_export(self, export_data: dict) -> HandlerResult:
        """Format export data as CSV."""
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)

        # Profile section
        writer.writerow(["Section", "Field", "Value"])
        writer.writerow([])
        writer.writerow(["Profile"])

        profile = export_data.get("profile", {})
        for key, value in profile.items():
            writer.writerow(["", key, str(value) if value is not None else ""])

        # Organization section
        if "organization" in export_data:
            writer.writerow([])
            writer.writerow(["Organization"])
            for key, value in export_data["organization"].items():
                writer.writerow(["", key, str(value) if value is not None else ""])

        # OAuth providers
        if "oauth_providers" in export_data:
            writer.writerow([])
            writer.writerow(["OAuth Providers"])
            for provider in export_data["oauth_providers"]:
                writer.writerow(["", provider["provider"], provider.get("linked_at", "")])

        csv_content = output.getvalue()

        return HandlerResult(
            status_code=200,
            content_type="text/csv; charset=utf-8",
            body=csv_content.encode("utf-8"),
            headers={
                "Content-Disposition": f"attachment; filename=aragora_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv",
            },
        )

    @handle_errors("data inventory")
    def _handle_data_inventory(self, handler) -> HandlerResult:
        """
        Get inventory of data categories collected about the user.

        CCPA: Disclosure of data categories
        """
        user_store = self._get_user_store()
        auth_ctx = extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return error_response("Not authenticated", 401)

        # Return standardized data inventory
        inventory = {
            "categories": [
                {
                    "name": "Identifiers",
                    "examples": ["Email address", "User ID", "Username"],
                    "purpose": "Account management and authentication",
                    "retention": "Until account deletion",
                },
                {
                    "name": "Internet Activity",
                    "examples": ["Debate participation", "Voting history", "API usage"],
                    "purpose": "Service provision and analytics",
                    "retention": "90 days (anonymized thereafter)",
                },
                {
                    "name": "Geolocation",
                    "examples": ["IP-derived country"],
                    "purpose": "Compliance and fraud prevention",
                    "retention": "90 days",
                },
                {
                    "name": "Professional Information",
                    "examples": ["Organization membership", "Role"],
                    "purpose": "Team collaboration",
                    "retention": "Until account deletion",
                },
                {
                    "name": "Inferences",
                    "examples": ["Agent preferences", "Usage patterns"],
                    "purpose": "Personalization",
                    "retention": "Until account deletion",
                },
            ],
            "third_party_sharing": {
                "llm_providers": {
                    "recipients": ["Anthropic", "OpenAI", "Mistral"],
                    "data_shared": "Debate prompts (anonymized)",
                    "purpose": "AI processing",
                },
                "analytics": {
                    "recipients": ["Internal analytics only"],
                    "data_shared": "Aggregated usage metrics",
                    "purpose": "Service improvement",
                },
            },
            "data_sold": False,
            "opt_out_available": True,
        }

        return json_response(inventory)

    @rate_limit(requests_per_minute=1, limiter_name="privacy_delete")
    @handle_errors("account deletion")
    @log_request("account deletion")
    def _handle_delete_account(self, handler) -> HandlerResult:
        """
        Delete user account and associated data.

        GDPR Article 17: Right to erasure
        CCPA: Right to delete

        Requires password confirmation for security.
        """
        user_store = self._get_user_store()
        auth_ctx = extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return error_response("Not authenticated", 401)

        if not user_store:
            return error_response("Service unavailable", 503)

        # Parse request body for confirmation
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        password = body.get("password", "")
        confirm = body.get("confirm", False)
        reason = body.get("reason", "")

        if not confirm:
            return error_response(
                "Account deletion must be confirmed with 'confirm': true",
                400,
            )

        # Get user
        user = user_store.get_user_by_id(auth_ctx.user_id)
        if not user:
            return error_response("User not found", 404)

        # Verify password
        if not user.verify_password(password):
            return error_response("Invalid password", 401)

        # Check if user is organization owner
        if user.org_id:
            org = user_store.get_organization_by_id(user.org_id)
            if org and org.owner_id == user.id:
                members = user_store.get_org_members(user.org_id)
                if len(members) > 1:
                    return error_response(
                        "Cannot delete account while owning an organization with other members. "
                        "Transfer ownership first via /api/organizations/{id}/transfer-ownership",
                        400,
                    )

        # Log the deletion request first
        user_store.log_audit_event(
            action="account_deletion_requested",
            resource_type="user",
            resource_id=user.id,
            user_id=user.id,
            metadata={
                "reason": reason,
                "email_hash": self._hash_for_audit(user.email),
            },
        )

        # Perform deletion
        deletion_result = self._perform_account_deletion(user_store, user, reason)

        if not deletion_result["success"]:
            return error_response(deletion_result["error"], 500)

        logger.info("Account deleted: %s", self._hash_for_audit(user.email))

        return json_response(
            {
                "message": "Account deleted successfully",
                "deletion_id": deletion_result["deletion_id"],
                "data_deleted": deletion_result["data_deleted"],
                "retention_note": "Audit logs retained for 7 years per compliance requirements",
            }
        )

    def _perform_account_deletion(self, user_store: Any, user: Any, reason: str) -> dict[str, Any]:
        """Perform the actual account deletion with data anonymization."""
        import uuid

        deletion_id = str(uuid.uuid4())
        data_deleted = []

        try:
            # 1. Unlink OAuth providers
            oauth_providers = user_store.get_user_oauth_providers(user.id)
            for provider in oauth_providers:
                user_store.unlink_oauth_provider(user.id, provider["provider"])
            if oauth_providers:
                data_deleted.append(f"oauth_links:{len(oauth_providers)}")

            # 2. Clear API key
            if user.api_key_hash:
                user_store.update_user(
                    user.id,
                    api_key_hash=None,
                    api_key_prefix=None,
                    api_key_created_at=None,
                    api_key_expires_at=None,
                )
                data_deleted.append("api_key")

            # 3. Clear MFA data
            if user.mfa_enabled:
                user_store.update_user(
                    user.id,
                    mfa_enabled=False,
                    mfa_secret=None,
                    mfa_backup_codes=None,
                )
                data_deleted.append("mfa_data")

            # 4. Clear preferences
            user_store.set_user_preferences(user.id, {})
            data_deleted.append("preferences")

            # 5. Remove from organization (if not owner of org with members)
            if user.org_id:
                user_store.remove_user_from_org(user.id)
                data_deleted.append("org_membership")

            # 6. Anonymize the user record (soft delete for audit compliance)
            anonymized_email = f"deleted_{deletion_id[:8]}@deleted.aragora.ai"
            user_store.update_user(
                user.id,
                email=anonymized_email,
                name="[Deleted User]",
                password_hash="DELETED",  # noqa: S106 - GDPR deletion tombstone, not a secret
                password_salt="DELETED",  # noqa: S106 - GDPR deletion tombstone, not a secret
                is_active=False,
            )
            data_deleted.append("profile")

            # 7. Log completion
            user_store.log_audit_event(
                action="account_deletion_completed",
                resource_type="user",
                resource_id=user.id,
                metadata={
                    "deletion_id": deletion_id,
                    "reason": reason,
                    "data_deleted": data_deleted,
                },
            )

            return {
                "success": True,
                "deletion_id": deletion_id,
                "data_deleted": data_deleted,
            }

        except (KeyError, ValueError, OSError, TypeError, RuntimeError) as e:
            logger.error("Account deletion failed: %s", e)
            return {
                "success": False,
                "error": "Account deletion failed",
                "deletion_id": deletion_id,
                "data_deleted": data_deleted,
            }

    def _hash_for_audit(self, value: str) -> str:
        """Hash a value for audit logging (privacy-preserving)."""
        import hashlib

        return hashlib.sha256(value.encode()).hexdigest()[:16]

    @handle_errors("get privacy preferences")
    def _handle_get_preferences(self, handler) -> HandlerResult:
        """Get user's privacy preferences."""
        user_store = self._get_user_store()
        auth_ctx = extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return error_response("Not authenticated", 401)

        if not user_store:
            return error_response("Service unavailable", 503)

        preferences = user_store.get_user_preferences(auth_ctx.user_id) or {}
        privacy_prefs = preferences.get("privacy", {})

        return json_response(
            {
                "do_not_sell": privacy_prefs.get("do_not_sell", False),
                "marketing_opt_out": privacy_prefs.get("marketing_opt_out", False),
                "analytics_opt_out": privacy_prefs.get("analytics_opt_out", False),
                "third_party_sharing": privacy_prefs.get("third_party_sharing", True),
            }
        )

    @rate_limit(requests_per_minute=5, limiter_name="privacy_preferences")
    @handle_errors("update privacy preferences")
    @log_request("update privacy preferences")
    def _handle_update_preferences(self, handler) -> HandlerResult:
        """
        Update user's privacy preferences.

        CCPA: Do Not Sell My Personal Information
        """
        user_store = self._get_user_store()
        auth_ctx = extract_user_from_request(handler, user_store)
        if not auth_ctx.is_authenticated:
            return error_response("Not authenticated", 401)

        if not user_store:
            return error_response("Service unavailable", 503)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid JSON body", 400)

        # Get current preferences
        current = user_store.get_user_preferences(auth_ctx.user_id) or {}
        privacy_prefs = current.get("privacy", {})

        # Update allowed fields
        allowed_fields = [
            "do_not_sell",
            "marketing_opt_out",
            "analytics_opt_out",
            "third_party_sharing",
        ]
        for field in allowed_fields:
            if field in body:
                privacy_prefs[field] = bool(body[field])

        # Save
        current["privacy"] = privacy_prefs
        user_store.set_user_preferences(auth_ctx.user_id, current)

        # Log the preference change
        user_store.log_audit_event(
            action="privacy_preferences_updated",
            resource_type="user",
            resource_id=auth_ctx.user_id,
            user_id=auth_ctx.user_id,
            new_value=privacy_prefs,
        )

        logger.info("Privacy preferences updated for user: %s", auth_ctx.user_id)

        return json_response(
            {
                "message": "Privacy preferences updated",
                "preferences": privacy_prefs,
            }
        )


__all__ = ["PrivacyHandler"]
