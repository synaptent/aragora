"""
Inbox Command Center API Handler.

Provides unified API endpoints for the inbox command center including:
- Prioritized email fetching with cross-channel context
- Quick actions (archive, snooze, reply, forward)
- Bulk operations
- Daily digest statistics
- Sender profile lookups

Endpoints:
- GET /api/inbox/command - Fetch prioritized inbox
- POST /api/inbox/actions - Execute quick action
- POST /api/inbox/bulk-actions - Execute bulk action
- GET /api/inbox/sender-profile - Get sender profile
- GET /api/inbox/daily-digest - Get daily digest
- POST /api/inbox/reprioritize - Trigger AI re-prioritization

Action endpoints are in inbox_actions.py (InboxActionsMixin).
Service integration endpoints are in inbox_services.py (InboxServicesMixin).
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from aiohttp import web

from aragora.rbac.checker import get_permission_checker
from aragora.rbac.models import AuthorizationContext
from aragora.server.handlers.utils.auth import get_auth_context, UnauthorizedError
from aragora.server.handlers.utils import parse_json_body
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.services import (
    ServiceRegistry,
    EmailPrioritizer,
    EmailPrioritizationConfig,
    SenderHistoryService,
)
from aragora.caching import HybridTTLCache, RedisTTLCache, register_cache
from aragora.server.validation.query_params import safe_query_int

from .inbox_actions import InboxActionsMixin
from .inbox_services import InboxServicesMixin

# ---------------------------------------------------------------------------
# Security constants: allowlists and input bounds
# ---------------------------------------------------------------------------

# Explicit allowlist of valid quick/bulk actions. Any action not in this set
# is rejected before reaching handler logic, preventing command injection.
ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "archive",
        "snooze",
        "reply",
        "forward",
        "spam",
        "mark_important",
        "mark_vip",
        "block",
        "delete",
    }
)

# Explicit allowlist of valid bulk-action filter types.
ALLOWED_BULK_FILTERS: frozenset[str] = frozenset(
    {
        "low",
        "deferred",
        "spam",
        "read",
        "all",
    }
)

# Explicit allowlist of valid priority filter values for GET /inbox/command.
ALLOWED_PRIORITY_FILTERS: frozenset[str] = frozenset(
    {
        "critical",
        "high",
        "medium",
        "low",
        "defer",
    }
)

# Explicit allowlist of valid force_tier values for reprioritization.
ALLOWED_FORCE_TIERS: frozenset[str] = frozenset(
    {
        "tier_1_rules",
        "tier_2_lightweight",
        "tier_3_debate",
    }
)

# Explicit allowlist of valid snooze duration values.
ALLOWED_SNOOZE_DURATIONS: frozenset[str] = frozenset(
    {
        "1h",
        "3h",
        "1d",
        "3d",
        "1w",
    }
)

# Input length bounds
MAX_EMAIL_ID_LENGTH = 256
MAX_EMAIL_IDS_PER_REQUEST = 200
MAX_EMAIL_ADDRESS_LENGTH = 320  # RFC 5321 maximum
MAX_REPLY_BODY_LENGTH = 100_000  # 100 KB
MAX_FORWARD_TO_LENGTH = 320
MAX_SENDER_PARAM_LENGTH = 320
MAX_PARAMS_KEYS = 20

# Pattern for validating email IDs (alphanumeric, hyphens, underscores, dots)
_EMAIL_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\.]+$")
# RFC 5322 simplified email validation
_EMAIL_ADDRESS_PATTERN = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~\-]+@[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?)*$"
)


def _validate_email_id(email_id: Any) -> str | None:
    """Validate and sanitize an email ID.

    Returns the sanitized ID string, or None if invalid.
    """
    if not isinstance(email_id, str):
        return None
    email_id = email_id.strip()
    if not email_id or len(email_id) > MAX_EMAIL_ID_LENGTH:
        return None
    if not _EMAIL_ID_PATTERN.match(email_id):
        return None
    return email_id


def _validate_email_address(address: Any) -> str | None:
    """Validate and sanitize an email address.

    Returns the sanitized address string, or None if invalid.
    """
    if not isinstance(address, str):
        return None
    address = address.strip()
    if not address or len(address) > MAX_EMAIL_ADDRESS_LENGTH:
        return None
    if not _EMAIL_ADDRESS_PATTERN.match(address):
        return None
    return address


def _sanitize_string_param(value: Any, max_length: int) -> str:
    """Sanitize a generic string parameter.

    Returns the stripped and length-bounded string, or empty string if invalid.
    """
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


def _validate_params(params: Any) -> dict[str, Any] | None:
    """Validate the params dict from request body.

    Returns sanitized params dict, or None if invalid.
    """
    if params is None:
        return {}
    if not isinstance(params, dict):
        return None
    if len(params) > MAX_PARAMS_KEYS:
        return None
    return params


if TYPE_CHECKING:
    from aragora.connectors.enterprise.communication.gmail import GmailConnector

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=dict[str, Any])


class IterableTTLCache(Generic[T]):
    """
    TTL cache wrapper that supports iteration for inbox operations.

    Wraps HybridTTLCache to provide dict-like iteration while maintaining
    Redis persistence for multi-instance deployments.
    """

    def __init__(self, name: str, maxsize: int, ttl_seconds: float) -> None:
        self._cache: RedisTTLCache[T] = HybridTTLCache(
            prefix=name,
            maxsize=maxsize,
            ttl_seconds=ttl_seconds,
        )
        self._keys: set[str] = set()  # Track keys for iteration
        self._lock = threading.Lock()

    def get(self, key: str) -> T | None:
        """Get value from cache."""
        return self._cache.get(key)

    def set(self, key: str, value: T) -> None:
        """Store value in cache."""
        self._cache.set(key, value)
        with self._lock:
            self._keys.add(key)

    def __setitem__(self, key: str, value: T) -> None:
        """Dict-style assignment."""
        self.set(key, value)

    def __getitem__(self, key: str) -> T:
        """Dict-style access."""
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __contains__(self, key: str) -> bool:
        """Check if key exists."""
        return self.get(key) is not None

    def items(self) -> list[tuple[str, T]]:
        """Return list of (key, value) pairs."""
        result: list[tuple[str, T]] = []
        with self._lock:
            for key in list(self._keys):
                value = self.get(key)
                if value is not None:
                    result.append((key, value))
                else:
                    self._keys.discard(key)
        return result

    def values(self) -> list[T]:
        """Return list of values."""
        return [v for _, v in self.items()]

    def invalidate(self, key: str) -> bool:
        """Remove key from cache."""
        with self._lock:
            self._keys.discard(key)
        return self._cache.invalidate(key)

    def __len__(self) -> int:
        """Return number of tracked keys."""
        with self._lock:
            return len(self._keys)

    def clear(self) -> None:
        """Remove all entries from cache."""
        with self._lock:
            for key in list(self._keys):
                self._cache.invalidate(key)
            self._keys.clear()

    @property
    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return self._cache.stats


# Production-ready cache for prioritized emails (Redis when available, fallback to in-memory)
_email_cache: IterableTTLCache = IterableTTLCache(
    name="inbox_email_cache",
    maxsize=10000,
    ttl_seconds=3600,  # 1 hour TTL
)
_priority_results: IterableTTLCache = IterableTTLCache(
    name="inbox_priority_results",
    maxsize=1000,
    ttl_seconds=1800,  # 30 min TTL
)

# Register underlying caches for monitoring
register_cache("inbox_email", _email_cache._cache)
register_cache("inbox_priority", _priority_results._cache)


@dataclass
class InboxCommandHandler(InboxActionsMixin, InboxServicesMixin):
    """Handler for inbox command center API endpoints."""

    ROUTES = [
        "/api/v1/inbox/command",
        "/api/v1/inbox/actions",
        "/api/v1/inbox/bulk-actions",
        "/api/v1/inbox/sender-profile",
        "/api/v1/inbox/daily-digest",
        "/api/v1/inbox/reprioritize",
    ]
    _ROUTE_MAP = {
        "GET /api/v1/inbox/command": "handle_get_inbox",
        "POST /api/v1/inbox/actions": "handle_quick_action",
        "POST /api/v1/inbox/bulk-actions": "handle_bulk_action",
        "GET /api/v1/inbox/sender-profile": "handle_get_sender_profile",
        "GET /api/v1/inbox/daily-digest": "handle_get_daily_digest",
        "POST /api/v1/inbox/reprioritize": "handle_reprioritize",
    }

    gmail_connector: GmailConnector | None = None
    prioritizer: EmailPrioritizer | None = None
    sender_history: SenderHistoryService | None = None
    _initialized: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        """Initialize services from registry if not provided."""
        self._ensure_services()

    def _ensure_services(self) -> None:
        """Lazily initialize services from the registry."""
        if self._initialized:
            return

        registry = ServiceRegistry.get()

        # Try to get GmailConnector from registry
        if self.gmail_connector is None:
            try:
                from aragora.connectors.enterprise.communication.gmail import GmailConnector

                if registry.has(GmailConnector):
                    self.gmail_connector = registry.resolve(GmailConnector)
                    logger.debug("Resolved GmailConnector from registry")
            except ImportError as e:
                logger.debug("GmailConnector module not available: %s", e)
            except (TypeError, RuntimeError) as e:
                # TypeError: registry misconfiguration; RuntimeError: dependency issues
                logger.debug("GmailConnector not available: %s", e)

        # Try to get or create EmailPrioritizer
        if self.prioritizer is None:
            if registry.has(EmailPrioritizer):
                self.prioritizer = registry.resolve(EmailPrioritizer)
                logger.debug("Resolved EmailPrioritizer from registry")
            elif self.gmail_connector is not None:
                # Create a prioritizer with the connector
                self.prioritizer = EmailPrioritizer(
                    gmail_connector=self.gmail_connector,
                    config=EmailPrioritizationConfig(),
                )
                registry.register(EmailPrioritizer, self.prioritizer)
                logger.info("Created and registered EmailPrioritizer")

        # Try to get SenderHistoryService
        if self.sender_history is None:
            if registry.has(SenderHistoryService):
                self.sender_history = registry.resolve(SenderHistoryService)
                logger.debug("Resolved SenderHistoryService from registry")

        self._initialized = True

    async def _check_permission(self, request: web.Request, permission: str) -> None:
        """Check if the request has the required permission.

        SECURITY: Uses JWT-only authentication. X-User-ID headers are NOT trusted
        to prevent user impersonation attacks.

        Raises:
            web.HTTPForbidden: If permission check fails
            web.HTTPUnauthorized: If no valid authentication
        """
        try:
            # SECURITY: Only trust JWT tokens, never trust X-User-ID headers
            context = await get_auth_context(request, require_auth=False)
        except UnauthorizedError as e:
            logger.warning("Inbox auth failed: %s", e)
            raise web.HTTPUnauthorized(
                text="Authentication required",
                content_type="application/json",
            )
        except (ValueError, KeyError, AttributeError) as e:
            # Auth extraction failed due to malformed token or missing fields
            logger.warning("Auth extraction failed: %s", e)
            context = AuthorizationContext(
                user_id="anonymous",
                org_id=None,
                roles=set(),
            )

        if not context.user_id or context.user_id == "anonymous":
            # Require authentication for all inbox operations
            raise web.HTTPUnauthorized(
                text="Authentication required for inbox access",
                content_type="application/json",
            )

        checker = get_permission_checker()
        decision = checker.check_permission(context, permission)

        if not decision.allowed:
            logger.warning(
                "Permission denied: %s for user %s - %s",
                permission,
                context.user_id,
                decision.reason,
            )
            raise web.HTTPForbidden(
                text="Permission denied",
                content_type="application/json",
            )

    @rate_limit(requests_per_minute=60, limiter_name="inbox_read")
    async def handle_get_inbox(self, request: web.Request) -> web.Response:
        """
        GET /api/inbox/command

        Fetch prioritized inbox with stats.

        Query params:
            - limit: Max emails to return (default 50)
            - offset: Pagination offset (default 0)
            - priority: Filter by priority level (critical, high, medium, low, defer)
            - unread_only: Only return unread emails (default false)
        """
        try:
            await self._check_permission(request, "inbox:read")
            self._ensure_services()

            limit = safe_query_int(request.query, "limit", default=50, max_val=1000)
            offset = safe_query_int(request.query, "offset", default=0, max_val=100000)
            priority_filter = request.query.get("priority")
            unread_only = request.query.get("unread_only", "false").lower() == "true"

            # Validate priority filter against allowlist
            if priority_filter is not None:
                priority_filter = priority_filter.strip().lower()
                if priority_filter not in ALLOWED_PRIORITY_FILTERS:
                    return web.json_response(
                        {
                            "success": False,
                            "error": f"Invalid priority filter. Allowed values: {', '.join(sorted(ALLOWED_PRIORITY_FILTERS))}",
                        },
                        status=400,
                    )

            # Get emails from service
            emails = await self._fetch_prioritized_emails(
                limit=limit,
                offset=offset,
                priority_filter=priority_filter,
                unread_only=unread_only,
            )

            # Calculate stats
            stats = await self._calculate_inbox_stats(emails)

            return web.json_response(
                {
                    "success": True,
                    "emails": emails,
                    "total": stats["total"],
                    "stats": stats,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
        except (web.HTTPUnauthorized, web.HTTPForbidden):
            raise
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.exception("Failed to fetch inbox: %s", e)
            return web.json_response(
                {"success": False, "error": "Internal server error"},
                status=500,
            )

    @rate_limit(requests_per_minute=30, limiter_name="inbox_write")
    async def handle_quick_action(self, request: web.Request) -> web.Response:
        """
        POST /api/inbox/actions

        Execute quick action on email(s).

        Body:
            - action: Action to perform (archive, snooze, reply, forward, spam, etc.)
            - emailIds: List of email IDs to act on
            - params: Optional action-specific parameters
        """
        try:
            await self._check_permission(request, "inbox:write")
            self._ensure_services()

            body, err = await parse_json_body(request, context="inbox_quick_action")
            if err:
                return err
            action = body.get("action")
            raw_email_ids = body.get("emailIds")
            raw_params = body.get("params", {})

            if not action or not isinstance(action, str):
                return web.json_response(
                    {"success": False, "error": "action is required"},
                    status=400,
                )

            # Validate action against allowlist
            action = action.strip().lower()
            if action not in ALLOWED_ACTIONS:
                return web.json_response(
                    {
                        "success": False,
                        "error": f"Invalid action '{action}'. Allowed actions: {', '.join(sorted(ALLOWED_ACTIONS))}",
                    },
                    status=400,
                )

            # Validate emailIds is a list with bounded length
            if raw_email_ids is None:
                return web.json_response(
                    {"success": False, "error": "emailIds is required"},
                    status=400,
                )
            if not isinstance(raw_email_ids, list) or not raw_email_ids:
                return web.json_response(
                    {"success": False, "error": "emailIds must be a non-empty list"},
                    status=400,
                )
            if len(raw_email_ids) > MAX_EMAIL_IDS_PER_REQUEST:
                return web.json_response(
                    {
                        "success": False,
                        "error": f"emailIds exceeds maximum of {MAX_EMAIL_IDS_PER_REQUEST}",
                    },
                    status=400,
                )

            # Validate and sanitize each email ID
            email_ids: list[str] = []
            for raw_id in raw_email_ids:
                validated = _validate_email_id(raw_id)
                if validated is None:
                    return web.json_response(
                        {
                            "success": False,
                            "error": f"Invalid email ID: must be alphanumeric (max {MAX_EMAIL_ID_LENGTH} chars)",
                        },
                        status=400,
                    )
                email_ids.append(validated)

            # Validate params
            params = _validate_params(raw_params)
            if params is None:
                return web.json_response(
                    {"success": False, "error": "Invalid params object"},
                    status=400,
                )

            # Sanitize action-specific params
            params = self._sanitize_action_params(action, params)

            # Extract optional receipt_id for enforcement gate
            receipt_id = body.get("receipt_id")
            if receipt_id is not None and not isinstance(receipt_id, str):
                receipt_id = None

            # Execute action
            results = await self._execute_action(
                action,
                email_ids,
                params,
                receipt_id=receipt_id,
                actor_id=body.get("actor_id"),
            )

            return web.json_response(
                {
                    "success": True,
                    "action": action,
                    "processed": len(email_ids),
                    "results": results,
                }
            )
        except (web.HTTPUnauthorized, web.HTTPForbidden):
            raise
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            # Let ReceiptEnforcementError propagate (subclass of RuntimeError)
            try:
                from aragora.pipeline.receipt_enforcement import ReceiptEnforcementError

                if isinstance(e, ReceiptEnforcementError):
                    raise
            except ImportError:
                pass
            logger.exception("Failed to execute action: %s", e)
            return web.json_response(
                {"success": False, "error": "Internal server error"},
                status=500,
            )

    @rate_limit(requests_per_minute=10, limiter_name="inbox_bulk_write")
    async def handle_bulk_action(self, request: web.Request) -> web.Response:
        """
        POST /api/inbox/bulk-actions

        Execute bulk action based on filter.

        Body:
            - action: Action to perform
            - filter: Filter to apply (low, deferred, spam, read, all)
            - params: Optional action-specific parameters
        """
        try:
            await self._check_permission(request, "inbox:write")
            self._ensure_services()

            body, err = await parse_json_body(request, context="inbox_bulk_action")
            if err:
                return err
            action = body.get("action")
            filter_type = body.get("filter")
            raw_params = body.get("params", {})

            if (
                not action
                or not isinstance(action, str)
                or not filter_type
                or not isinstance(filter_type, str)
            ):
                return web.json_response(
                    {"success": False, "error": "action and filter are required"},
                    status=400,
                )

            # Validate action against allowlist
            action = action.strip().lower()
            if action not in ALLOWED_ACTIONS:
                return web.json_response(
                    {
                        "success": False,
                        "error": f"Invalid action '{action}'. Allowed actions: {', '.join(sorted(ALLOWED_ACTIONS))}",
                    },
                    status=400,
                )

            # Validate filter against allowlist
            filter_type = filter_type.strip().lower()
            if filter_type not in ALLOWED_BULK_FILTERS:
                return web.json_response(
                    {
                        "success": False,
                        "error": f"Invalid filter '{filter_type}'. Allowed filters: {', '.join(sorted(ALLOWED_BULK_FILTERS))}",
                    },
                    status=400,
                )

            # Validate params
            params = _validate_params(raw_params)
            if params is None:
                return web.json_response(
                    {"success": False, "error": "Invalid params object"},
                    status=400,
                )

            # Sanitize action-specific params
            params = self._sanitize_action_params(action, params)

            # Extract optional receipt_id for enforcement gate
            receipt_id = body.get("receipt_id")
            if receipt_id is not None and not isinstance(receipt_id, str):
                receipt_id = None

            # Get matching email IDs
            email_ids = await self._get_emails_by_filter(filter_type)

            if not email_ids:
                return web.json_response(
                    {
                        "success": True,
                        "action": action,
                        "processed": 0,
                        "message": "No emails matched the filter",
                    }
                )

            # Execute action
            results = await self._execute_action(
                action,
                email_ids,
                params,
                receipt_id=receipt_id,
                actor_id=body.get("actor_id"),
            )

            return web.json_response(
                {
                    "success": True,
                    "action": action,
                    "filter": filter_type,
                    "processed": len(email_ids),
                    "results": results,
                }
            )
        except (web.HTTPUnauthorized, web.HTTPForbidden):
            raise
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            # Let ReceiptEnforcementError propagate (subclass of RuntimeError)
            try:
                from aragora.pipeline.receipt_enforcement import ReceiptEnforcementError

                if isinstance(e, ReceiptEnforcementError):
                    raise
            except ImportError:
                pass
            logger.exception("Failed to execute bulk action: %s", e)
            return web.json_response(
                {"success": False, "error": "Internal server error"},
                status=500,
            )

    @rate_limit(requests_per_minute=60, limiter_name="inbox_read")
    async def handle_get_sender_profile(self, request: web.Request) -> web.Response:
        """
        GET /api/inbox/sender-profile

        Get profile information for a sender.

        Query params:
            - email: Sender email address
        """
        try:
            await self._check_permission(request, "inbox:read")
            self._ensure_services()

            raw_email = request.query.get("email")
            if not raw_email:
                return web.json_response(
                    {"success": False, "error": "email parameter is required"},
                    status=400,
                )

            email = _validate_email_address(raw_email)
            if email is None:
                return web.json_response(
                    {"success": False, "error": "Invalid email address format"},
                    status=400,
                )

            profile = await self._get_sender_profile(email)
            return web.json_response({"success": True, "profile": profile})
        except (web.HTTPUnauthorized, web.HTTPForbidden):
            raise
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.exception("Failed to get sender profile: %s", e)
            return web.json_response(
                {"success": False, "error": "Internal server error"},
                status=500,
            )

    @rate_limit(requests_per_minute=30, limiter_name="inbox_read")
    async def handle_get_daily_digest(self, request: web.Request) -> web.Response:
        """
        GET /api/inbox/daily-digest

        Get daily digest statistics.
        """
        try:
            await self._check_permission(request, "inbox:read")
            self._ensure_services()

            digest = await self._calculate_daily_digest()
            return web.json_response({"success": True, "digest": digest})
        except (web.HTTPUnauthorized, web.HTTPForbidden):
            raise
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.exception("Failed to get daily digest: %s", e)
            return web.json_response(
                {"success": False, "error": "Internal server error"},
                status=500,
            )

    @rate_limit(requests_per_minute=10, limiter_name="inbox_reprioritize")
    async def handle_reprioritize(self, request: web.Request) -> web.Response:
        """
        POST /api/inbox/reprioritize

        Trigger AI re-prioritization of inbox.

        Body:
            - emailIds: Optional list of specific email IDs to reprioritize
            - force_tier: Optional tier to force (tier_1_rules, tier_2_lightweight, tier_3_debate)
            - auto_debate: Optional bool to trigger debates for critical emails
        """
        try:
            await self._check_permission(request, "inbox:write")
            self._ensure_services()

            body, err = await parse_json_body(request, context="inbox_reprioritize")
            if err:
                return err
            raw_email_ids = body.get("emailIds")
            force_tier = body.get("force_tier")
            auto_debate = bool(body.get("auto_debate", False))

            # Validate and sanitize emailIds if provided
            email_ids: list[str] | None = None
            if raw_email_ids is not None:
                if not isinstance(raw_email_ids, list):
                    return web.json_response(
                        {"success": False, "error": "emailIds must be a list"},
                        status=400,
                    )
                if len(raw_email_ids) > MAX_EMAIL_IDS_PER_REQUEST:
                    return web.json_response(
                        {
                            "success": False,
                            "error": f"emailIds exceeds maximum of {MAX_EMAIL_IDS_PER_REQUEST}",
                        },
                        status=400,
                    )
                email_ids = []
                for raw_id in raw_email_ids:
                    validated = _validate_email_id(raw_id)
                    if validated is None:
                        return web.json_response(
                            {
                                "success": False,
                                "error": f"Invalid email ID: must be alphanumeric (max {MAX_EMAIL_ID_LENGTH} chars)",
                            },
                            status=400,
                        )
                    email_ids.append(validated)

            # Validate force_tier against allowlist
            if force_tier is not None:
                if not isinstance(force_tier, str):
                    return web.json_response(
                        {"success": False, "error": "force_tier must be a string"},
                        status=400,
                    )
                force_tier = force_tier.strip().lower()
                if force_tier not in ALLOWED_FORCE_TIERS:
                    return web.json_response(
                        {
                            "success": False,
                            "error": f"Invalid force_tier. Allowed values: {', '.join(sorted(ALLOWED_FORCE_TIERS))}",
                        },
                        status=400,
                    )

            # Trigger reprioritization
            result = await self._reprioritize_emails(email_ids, force_tier)

            # Optionally trigger debates for critical emails
            debate_results = []
            if auto_debate and result.get("changes"):
                try:
                    from aragora.server.handlers.inbox.auto_debate import (
                        process_reprioritization_debates,
                    )

                    debate_results = await process_reprioritization_debates(
                        changes=result["changes"],
                        email_cache=_email_cache,
                        auto_debate=True,
                    )
                except (ImportError, RuntimeError, OSError) as e:
                    logger.warning("Auto-debate processing failed: %s", e)

            response: dict[str, Any] = {
                "success": True,
                "reprioritized": result["count"],
                "changes": result["changes"],
                "tier_used": result.get("tier_used"),
            }
            if debate_results:
                response["debates_triggered"] = [
                    {
                        "email_id": dr.email_id,
                        "debate_id": dr.debate_id,
                        "triggered": dr.triggered,
                        "reason": dr.reason,
                    }
                    for dr in debate_results
                ]

            return web.json_response(response)
        except (web.HTTPUnauthorized, web.HTTPForbidden):
            raise
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as e:
            logger.exception("Failed to reprioritize: %s", e)
            return web.json_response(
                {"success": False, "error": "Internal server error"},
                status=500,
            )

    # Remaining private methods are provided by:
    # - InboxActionsMixin (action execution, individual actions, email filters)
    # - InboxServicesMixin (email fetching, stats, sender profiles, reprioritization)


def register_routes(app: web.Application) -> None:
    """Register inbox command center routes."""
    handler = InboxCommandHandler()

    # Main inbox endpoints
    app.router.add_get("/api/inbox/command", handler.handle_get_inbox)
    app.router.add_post("/api/inbox/actions", handler.handle_quick_action)
    app.router.add_post("/api/inbox/bulk-actions", handler.handle_bulk_action)
    app.router.add_get("/api/inbox/sender-profile", handler.handle_get_sender_profile)
    app.router.add_get("/api/inbox/daily-digest", handler.handle_get_daily_digest)
    app.router.add_post("/api/inbox/reprioritize", handler.handle_reprioritize)

    # API v1 endpoints
    app.router.add_get("/api/v1/inbox/command", handler.handle_get_inbox)
    app.router.add_post("/api/v1/inbox/actions", handler.handle_quick_action)
    app.router.add_post("/api/v1/inbox/bulk-actions", handler.handle_bulk_action)
    app.router.add_get("/api/v1/inbox/sender-profile", handler.handle_get_sender_profile)
    app.router.add_get("/api/v1/inbox/daily-digest", handler.handle_get_daily_digest)
    app.router.add_post("/api/v1/inbox/reprioritize", handler.handle_reprioritize)

    # Aliases for backward compatibility
    app.router.add_get("/api/email/daily-digest", handler.handle_get_daily_digest)
    app.router.add_get("/api/email/sender-profile", handler.handle_get_sender_profile)

    logger.info("Registered inbox command center routes")
