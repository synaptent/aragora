"""
Debate Sharing Handler.

Provides endpoints for sharing debates with different visibility levels:
- private: Only accessible by the creator
- team: Accessible by organization members
- public: Accessible via shareable link

Endpoints:
    GET  /api/debates/{id}/share          - Get sharing settings
    POST /api/debates/{id}/share          - Update sharing settings
    GET  /api/shared/{token}              - Access shared debate
    POST /api/debates/{id}/share/revoke   - Revoke all share links
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from aragora.rbac.decorators import require_permission
from aragora.server.validation.schema import SHARE_UPDATE_SCHEMA, validate_against_schema

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    handle_errors,
    json_response,
)
from ..utils.lazy_stores import LazyStore
from ..utils.rate_limit import RateLimiter, get_client_ip, rate_limit

logger = logging.getLogger(__name__)

# Rate limiter for social share APIs (60 requests per minute)
_share_limiter = RateLimiter(requests_per_minute=60)


class DebateVisibility(str, Enum):
    """Visibility level for a debate."""

    PRIVATE = "private"  # Only creator can access
    TEAM = "team"  # Organization members can access
    PUBLIC = "public"  # Anyone with link can access


@dataclass
class ShareSettings:
    """Sharing settings for a debate."""

    debate_id: str
    visibility: DebateVisibility = DebateVisibility.PRIVATE
    share_token: str | None = None
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None  # None = no expiration
    allow_comments: bool = False
    allow_forking: bool = False
    view_count: int = 0
    owner_id: str | None = None
    org_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "debate_id": self.debate_id,
            "visibility": self.visibility.value,
            "share_token": self.share_token,
            "share_url": self._get_share_url() if self.share_token else None,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "is_expired": self.is_expired,
            "allow_comments": self.allow_comments,
            "allow_forking": self.allow_forking,
            "view_count": self.view_count,
        }

    def _get_share_url(self) -> str:
        """Generate the share URL."""
        # This would be configured via settings in production
        return f"/api/v1/shared/{self.share_token}"

    @property
    def is_expired(self) -> bool:
        """Check if the share link has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ShareSettings:
        """Create from dictionary."""
        return cls(
            debate_id=data["debate_id"],
            visibility=DebateVisibility(data.get("visibility", "private")),
            share_token=data.get("share_token"),
            created_at=data.get("created_at", time.time()),
            expires_at=data.get("expires_at"),
            allow_comments=data.get("allow_comments", False),
            allow_forking=data.get("allow_forking", False),
            view_count=data.get("view_count", 0),
            owner_id=data.get("owner_id"),
            org_id=data.get("org_id"),
        )


MAX_SHARE_SETTINGS = 10000  # Prevent unbounded memory growth


class ShareStore:
    """In-memory store for sharing settings (thread-safe).

    In production, this would be backed by a database.
    """

    def __init__(self) -> None:
        self._settings: dict[str, ShareSettings] = {}
        self._tokens: dict[str, str] = {}  # token -> debate_id
        self._lock = threading.Lock()

    def get(self, debate_id: str) -> ShareSettings | None:
        """Get sharing settings for a debate (thread-safe)."""
        with self._lock:
            return self._settings.get(debate_id)

    def get_by_token(self, token: str) -> ShareSettings | None:
        """Get sharing settings by share token (thread-safe)."""
        with self._lock:
            debate_id = self._tokens.get(token)
            if debate_id:
                return self._settings.get(debate_id)
            return None

    def save(self, settings: ShareSettings) -> None:
        """Save sharing settings (thread-safe with size limit)."""
        with self._lock:
            # Enforce max size with LRU eviction (by created_at)
            if (
                settings.debate_id not in self._settings
                and len(self._settings) >= MAX_SHARE_SETTINGS
            ):
                # Remove oldest 10% by created_at
                sorted_items = sorted(self._settings.items(), key=lambda x: x[1].created_at)
                remove_count = max(1, len(sorted_items) // 10)
                for debate_id_to_remove, s in sorted_items[:remove_count]:
                    del self._settings[debate_id_to_remove]
                    if s.share_token:
                        self._tokens.pop(s.share_token, None)
                logger.debug("ShareStore evicted %s oldest entries", remove_count)

            self._settings[settings.debate_id] = settings
            if settings.share_token:
                self._tokens[settings.share_token] = settings.debate_id

    def delete(self, debate_id: str) -> bool:
        """Delete sharing settings (thread-safe)."""
        with self._lock:
            settings = self._settings.pop(debate_id, None)
            if settings and settings.share_token:
                self._tokens.pop(settings.share_token, None)
            return settings is not None

    def revoke_token(self, debate_id: str) -> bool:
        """Revoke the share token for a debate (thread-safe)."""
        with self._lock:
            settings = self._settings.get(debate_id)
            if settings and settings.share_token:
                self._tokens.pop(settings.share_token, None)
                settings.share_token = None
                return True
            return False

    def increment_view_count(self, debate_id: str) -> None:
        """Increment the view count for a shared debate (thread-safe)."""
        with self._lock:
            settings = self._settings.get(debate_id)
            if settings:
                settings.view_count += 1


# === Social Share Support (consumer sharing) ===


@dataclass
class SocialShare:
    """Represents a social share entry."""

    id: str
    org_id: str
    resource_type: str
    resource_id: str
    shared_by: str
    shared_with: list[str] = field(default_factory=list)
    channel_id: str = ""
    platform: str = ""
    message: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "id": self.id,
            "org_id": self.org_id,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "shared_by": self.shared_by,
            "shared_with": self.shared_with,
            "channel_id": self.channel_id,
            "platform": self.platform,
            "message": self.message,
            "created_at": self.created_at,
        }


class SocialShareStore:
    """In-memory store for social shares (thread-safe)."""

    def __init__(self) -> None:
        self._shares: dict[str, SocialShare] = {}
        self._lock = threading.Lock()

    def get_by_org(self, org_id: str) -> list[SocialShare]:
        """List shares by org."""
        with self._lock:
            return [share for share in self._shares.values() if share.org_id == org_id]

    def get_by_id(self, share_id: str) -> SocialShare | None:
        """Get a share by ID."""
        with self._lock:
            return self._shares.get(share_id)

    def create(self, share: SocialShare) -> SocialShare:
        """Create a share entry."""
        with self._lock:
            self._shares[share.id] = share
            return share

    def delete(self, share_id: str) -> bool:
        """Delete a share by ID."""
        with self._lock:
            return self._shares.pop(share_id, None) is not None


# Global store instances (thread-safe lazy init)
_social_share_store_lazy = LazyStore(
    factory=SocialShareStore,
    store_name="social_share_store",
    logger_context="Sharing",
)


def get_social_share_store() -> SocialShareStore:
    """Get the global social share store instance (thread-safe)."""
    return _social_share_store_lazy.get()


def _create_share_store() -> Any:
    """Create a ShareLinkStore with SQLite fallback to in-memory."""
    try:
        from aragora.persistence.db_config import get_default_data_dir
        from aragora.storage.share_store import ShareLinkStore

        db_path = get_default_data_dir() / "share_links.db"
        store = ShareLinkStore(db_path)
        logger.info("Using SQLite ShareLinkStore: %s", db_path)
        return store
    except (ImportError, OSError, RuntimeError, ValueError) as e:
        logger.warning("Failed to init ShareLinkStore, using in-memory: %s", e)
        return ShareStore()


_share_store_lazy = LazyStore(
    factory=_create_share_store,
    store_name="share_store",
    logger_context="Sharing",
)


def get_share_store() -> Any:
    """Get the global share store instance (thread-safe)."""
    return _share_store_lazy.get()


class SharingHandler(BaseHandler):
    """Handler for debate sharing endpoints."""

    ROUTES = [
        "/api/v1/debates/*/share",
        "/api/v1/debates/*/share/revoke",
        "/api/v1/shared/*",
    ]

    # Require auth for all endpoints except shared view
    AUTH_REQUIRED_ENDPOINTS = [
        "/share",
        "/share/revoke",
    ]

    def __init__(self, server_context: dict[str, Any] | None = None):
        super().__init__(server_context if server_context is not None else dict())
        self._store = get_share_store()
        self._social_store = get_social_share_store()

    def can_handle(self, path: str) -> bool:
        """Check if this handler can handle the request path."""
        if path.startswith("/api/v1/social/shares"):
            return True
        if path.startswith("/api/v1/shared/"):
            return True
        if "/share" in path and "/api/v1/debates/" in path:
            return True
        return False

    @require_permission("sharing:read")
    def handle(
        self,
        path: str,
        query_params: dict,
        handler: Any,
        method: str = "GET",
        user: Any = None,
    ) -> HandlerResult | None:
        """Handle requests for sharing endpoints."""
        if hasattr(handler, "command"):
            method = handler.command

        # Social shares endpoints
        if path.startswith("/api/v1/social/shares"):
            client_ip = get_client_ip(handler)
            if not _share_limiter.is_allowed(client_ip):
                logger.warning("Rate limit exceeded for social shares: %s", client_ip)
                return error_response("Rate limit exceeded. Please try again later.", 429)

            if path == "/api/v1/social/shares":
                if method == "GET":
                    return self._list_social_shares(handler, query_params, user=user)
                if method == "POST":
                    return self._create_social_share(handler, query_params, user=user)
                return error_response("Method not allowed", 405)

            share_id = path.split("/api/v1/social/shares/")[1].rstrip("/")
            if method == "GET":
                return self._get_social_share(share_id, handler, user=user)
            if method == "DELETE":
                return self._delete_social_share(share_id, handler, user=user)
            return error_response("Method not allowed", 405)

        # Shared debate access (public endpoint)
        if path.startswith("/api/v1/shared/"):
            token = path.split("/api/v1/shared/")[1].rstrip("/")
            return self._get_shared_debate(token, query_params)

        # Delegate to existing debate share handlers
        if method == "GET" and path.endswith("/share"):
            debate_id, err = self._extract_debate_id(path)
            if err:
                return error_response(err, 400)
            return self._get_share_settings(debate_id, handler)

        if method == "POST":
            return self.handle_post(path, query_params, handler)

        return None

    @handle_errors("sharing creation")
    @require_permission("sharing:create")
    def handle_post(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Handle POST requests."""
        # Revoke share link
        if path.endswith("/share/revoke"):
            debate_id, err = self._extract_debate_id(path)
            if err:
                return error_response(err, 400)
            return self._revoke_share(debate_id, handler)

        # Update sharing settings
        if path.endswith("/share"):
            debate_id, err = self._extract_debate_id(path)
            if err:
                return error_response(err, 400)
            return self._update_share_settings(debate_id, handler)

        return None

    def _extract_debate_id(self, path: str) -> tuple[str | None, str | None]:
        """Extract debate ID from path."""
        try:
            # Path format: /api/debates/{id}/share or /api/debates/{id}/share/revoke
            parts = path.split("/")
            # Find 'debates' and get the next part
            for i, part in enumerate(parts):
                if part == "debates" and i + 1 < len(parts):
                    debate_id = parts[i + 1]
                    if debate_id and debate_id not in ("share", "revoke", ""):
                        return debate_id, None
            return None, "Could not extract debate ID from path"
        except (IndexError, ValueError):
            return None, "Failed to extract debate ID"

    def _resolve_social_user(self, handler: Any, user: Any) -> Any:
        """Resolve user context for social share operations."""
        if user is None:
            user = self.get_current_user(handler)
        user_store = self.ctx.get("user_store")
        if user_store and hasattr(user, "user_id"):
            try:
                db_user = user_store.get_user_by_id(user.user_id)
                if db_user:
                    return db_user
            except (KeyError, ValueError, AttributeError, RuntimeError, OSError) as e:
                logger.debug("User store lookup failed: %s", e)
        return user

    def _list_social_shares(
        self,
        handler: Any,
        query_params: dict,
        user: Any = None,
    ) -> HandlerResult:
        """List social shares."""
        db_user = self._resolve_social_user(handler, user)
        org_id = getattr(db_user, "org_id", None)
        shares = self._social_store.get_by_org(org_id) if org_id else []

        resource_type = query_params.get("resource_type")
        if resource_type:
            shares = [share for share in shares if share.resource_type == resource_type]

        return json_response({"shares": [s.to_dict() for s in shares], "total": len(shares)})

    def _get_social_share(
        self,
        share_id: str,
        handler: Any,
        user: Any = None,
    ) -> HandlerResult:
        """Get a social share by ID."""
        share = self._social_store.get_by_id(share_id)
        if not share:
            return error_response("Share not found", 404)
        return json_response({"share": share.to_dict()})

    def _create_social_share(
        self,
        handler: Any,
        query_params: dict,
        user: Any = None,
    ) -> HandlerResult:
        """Create a social share."""
        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        resource_type = body.get("resource_type")
        resource_id = body.get("resource_id")
        if not resource_type or not resource_id:
            return error_response("resource_type and resource_id are required", 400)

        db_user = self._resolve_social_user(handler, user)
        org_id = getattr(db_user, "org_id", "") or ""
        shared_by = getattr(db_user, "id", None) or getattr(db_user, "user_id", "")

        share = SocialShare(
            id=secrets.token_urlsafe(8),
            org_id=org_id,
            resource_type=resource_type,
            resource_id=resource_id,
            shared_by=shared_by,
            shared_with=body.get("shared_with") or [],
            channel_id=body.get("channel_id", ""),
            platform=body.get("platform", ""),
            message=body.get("message", ""),
        )

        created = self._social_store.create(share)
        return json_response({"share": created.to_dict()}, status=201)

    @require_permission("social:delete")
    def _delete_social_share(
        self,
        share_id: str,
        handler: Any,
        user: Any = None,
    ) -> HandlerResult:
        """Delete a social share."""
        deleted = self._social_store.delete(share_id)
        if not deleted:
            return error_response("Share not found", 404)
        return json_response({"deleted": True, "share_id": share_id})

    @handle_errors("get share settings")
    def _get_share_settings(self, debate_id: str, handler: Any) -> HandlerResult:
        """Get sharing settings for a debate.

        Returns:
            Current sharing settings including visibility, share URL, etc.
        """
        # Check authorization
        user = self.get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        # Get or create settings
        settings = self._store.get(debate_id)
        if not settings:
            settings = ShareSettings(
                debate_id=debate_id,
                owner_id=user.id,
                org_id=user.org_id,
            )
            self._store.save(settings)

        # Verify ownership
        if settings.owner_id and settings.owner_id != user.id:
            # Allow org members to view team-visible debates
            if settings.visibility != DebateVisibility.TEAM or settings.org_id != user.org_id:
                return error_response("Not authorized to view sharing settings", 403)

        return json_response(settings.to_dict())

    @rate_limit(requests_per_minute=30, limiter_name="share_update")
    @handle_errors("update share settings")
    def _update_share_settings(self, debate_id: str, handler: Any) -> HandlerResult:
        """Update sharing settings for a debate.

        POST body:
            {
                "visibility": "private" | "team" | "public",
                "expires_in_hours": int,  # Optional: hours until link expires
                "allow_comments": bool,   # Optional
                "allow_forking": bool     # Optional
            }

        Returns:
            Updated sharing settings including new share URL if public.
        """
        user = self.get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        body = self.read_json_body(handler)
        if body is None:
            return error_response("Invalid or missing JSON body", 400)

        # Schema validation for input sanitization
        validation_result = validate_against_schema(body, SHARE_UPDATE_SCHEMA)
        if not validation_result.is_valid:
            return error_response(validation_result.error, 400)

        # Get or create settings
        settings = self._store.get(debate_id)
        if not settings:
            settings = ShareSettings(
                debate_id=debate_id,
                owner_id=user.id,
                org_id=user.org_id,
            )

        # Verify ownership
        if settings.owner_id and settings.owner_id != user.id:
            return error_response("Not authorized to modify sharing settings", 403)

        # Update visibility
        visibility_str = body.get("visibility")
        if visibility_str:
            try:
                new_visibility = DebateVisibility(visibility_str)
                old_visibility = settings.visibility
                settings.visibility = new_visibility

                # Generate share token if making public
                if new_visibility == DebateVisibility.PUBLIC and not settings.share_token:
                    settings.share_token = self._generate_share_token(debate_id)

                # Revoke token if making private
                if new_visibility == DebateVisibility.PRIVATE and settings.share_token:
                    self._store.revoke_token(debate_id)
                    settings.share_token = None

                logger.info(
                    "Debate %s visibility changed: %s -> %s",
                    debate_id,
                    old_visibility.value,
                    new_visibility.value,
                )
            except ValueError:
                return error_response(
                    f"Invalid visibility. Must be: {', '.join(v.value for v in DebateVisibility)}",
                    400,
                )

        # Update expiration
        expires_in_hours = body.get("expires_in_hours")
        if expires_in_hours is not None:
            if expires_in_hours <= 0:
                settings.expires_at = None  # No expiration
            else:
                settings.expires_at = time.time() + (expires_in_hours * 3600)

        # Update other settings
        if "allow_comments" in body:
            settings.allow_comments = bool(body["allow_comments"])
        if "allow_forking" in body:
            settings.allow_forking = bool(body["allow_forking"])

        # Save
        self._store.save(settings)

        return json_response(
            {
                "success": True,
                "settings": settings.to_dict(),
            }
        )

    @rate_limit(requests_per_minute=60, limiter_name="shared_debate_access")
    @handle_errors("get shared debate")
    def _get_shared_debate(self, token: str, query_params: dict) -> HandlerResult:
        """Access a shared debate via token.

        This is a public endpoint - no authentication required.
        Returns debate data if the share link is valid.
        """
        settings = self._store.get_by_token(token)

        if not settings:
            # Log failed lookups to detect potential enumeration attacks
            # Use debug level to avoid log spam from legitimate 404s
            logger.debug("Share token not found: %s...", token[:8])
            return error_response("Share link not found", 404)

        if settings.is_expired:
            return error_response("Share link has expired", 410)

        if settings.visibility != DebateVisibility.PUBLIC:
            return error_response("Debate is no longer shared", 403)

        # Increment view count
        self._store.increment_view_count(settings.debate_id)

        # Get debate data
        debate_data = self._get_debate_data(settings.debate_id)
        if not debate_data:
            return error_response("Debate not found", 404)

        return json_response(
            {
                "debate": debate_data,
                "sharing": {
                    "allow_comments": settings.allow_comments,
                    "allow_forking": settings.allow_forking,
                    "view_count": settings.view_count,
                },
            }
        )

    @handle_errors("revoke share")
    def _revoke_share(self, debate_id: str, handler: Any) -> HandlerResult:
        """Revoke all share links for a debate.

        POST body: {} (empty)

        Returns:
            {
                "success": true,
                "message": "Share links revoked"
            }
        """
        user = self.get_current_user(handler)
        if not user:
            return error_response("Authentication required", 401)

        settings = self._store.get(debate_id)
        if not settings:
            return error_response("No sharing settings found", 404)

        # Verify ownership
        if settings.owner_id and settings.owner_id != user.id:
            return error_response("Not authorized to revoke sharing", 403)

        # Revoke token and set to private
        self._store.revoke_token(debate_id)
        settings.visibility = DebateVisibility.PRIVATE
        self._store.save(settings)

        logger.info("Share links revoked for debate %s", debate_id)

        return json_response(
            {
                "success": True,
                "message": "Share links revoked",
            }
        )

    def _generate_share_token(self, debate_id: str) -> str:
        """Generate a secure share token."""
        # Use secrets for cryptographically secure token
        return secrets.token_urlsafe(16)

    def _get_debate_data(self, debate_id: str) -> dict[str, Any] | None:
        """Get debate data for sharing.

        Fetches the debate artifact from the DebateStorage database.
        """
        try:
            from aragora.server.storage import get_debates_db

            db = get_debates_db()
            if db:
                return db.get(debate_id)
        except (ImportError, OSError, RuntimeError, KeyError, ValueError) as e:
            logger.warning("Could not fetch debate %s: %s", debate_id, e)

        return None


__all__ = [
    "SharingHandler",
    "ShareSettings",
    "DebateVisibility",
    "ShareStore",
    "get_share_store",
]
