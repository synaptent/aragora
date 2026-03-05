"""
Authentication and authorization checks for the unified server.

This module provides the AuthChecksMixin class with methods for:
- Rate limiting (basic API token, tier-based)
- RBAC permission checking
- MFA enforcement for admin roles (SOC 2 CC5-01, GitHub #275)
- Upload rate limiting
- Live streaming budget gating (auth + usage budget for live debate/TTS)

These methods are extracted from UnifiedHandler to improve modularity
and allow easier testing of authentication logic.
"""

import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from urllib.parse import urlparse

if TYPE_CHECKING:
    from aragora.server.middleware.rate_limit import RateLimitResult
    from aragora.storage import UserStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Live Streaming Budget Gate
# ---------------------------------------------------------------------------
# Paths that require authentication + usage budget (not hard-blocked).
# These endpoints consume real API credits so we gate on auth + remaining
# monthly debate quota rather than blocking outright.

BUDGET_GATED_PATHS: frozenset[str] = frozenset(
    [
        "/api/v1/playground/debate/live",
        "/api/v1/playground/debate/live/cost-estimate",
        "/api/v1/playground/tts",
    ]
)

# Default monthly limits per tier for live streaming requests.
# These mirror the debates_per_month from billing models but are kept here as
# a fallback so the gate works even when the billing module is unavailable.
_DEFAULT_LIVE_LIMITS: dict[str, int] = {
    "free": 10,
    "starter": 50,
    "professional": 200,
    "enterprise": 999999,
}


class LiveStreamingBudgetGate:
    """Track and enforce monthly live-streaming usage per workspace/org.

    Uses a lightweight SQLite counter (separate from the full billing DB)
    so the gate works even when heavier billing infrastructure is unavailable.
    When the billing models *are* importable, the gate reads tier limits from
    ``TIER_LIMITS``; otherwise it falls back to ``_DEFAULT_LIVE_LIMITS``.
    """

    _instance: "LiveStreamingBudgetGate | None" = None
    _lock = threading.Lock()

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            try:
                from aragora.config import resolve_db_path

                db_path = resolve_db_path("live_streaming_budget.db")
            except ImportError:
                db_path = str(Path.home() / ".aragora" / "live_streaming_budget.db")
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # -- singleton accessor ---------------------------------------------------

    @classmethod
    def get_instance(cls) -> "LiveStreamingBudgetGate":
        """Return (or create) the module-level singleton."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (for tests)."""
        with cls._lock:
            cls._instance = None

    # -- database -------------------------------------------------------------

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS live_usage (
                    org_id      TEXT    NOT NULL,
                    period      TEXT    NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (org_id, period)
                )
            """)
            conn.commit()

    def _current_period(self) -> str:
        """Return the current billing period as ``YYYY-MM``."""
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def get_usage(self, org_id: str) -> int:
        """Return usage count for the current month."""
        period = self._current_period()
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            row = conn.execute(
                "SELECT usage_count FROM live_usage WHERE org_id = ? AND period = ?",
                (org_id, period),
            ).fetchone()
            return row[0] if row else 0

    def increment(self, org_id: str) -> int:
        """Atomically increment and return the new count."""
        period = self._current_period()
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            conn.execute(
                """
                INSERT INTO live_usage (org_id, period, usage_count)
                VALUES (?, ?, 1)
                ON CONFLICT(org_id, period)
                DO UPDATE SET usage_count = usage_count + 1
                """,
                (org_id, period),
            )
            conn.commit()
            row = conn.execute(
                "SELECT usage_count FROM live_usage WHERE org_id = ? AND period = ?",
                (org_id, period),
            ).fetchone()
            return row[0] if row else 1

    # -- tier limit resolution ------------------------------------------------

    @staticmethod
    def get_tier_limit(tier: str) -> int:
        """Return the monthly live-streaming limit for a tier.

        Tries the canonical ``TIER_LIMITS`` from the billing models first,
        then falls back to the hardcoded defaults.
        """
        try:
            from aragora.billing.models import TIER_LIMITS, SubscriptionTier

            tier_enum = SubscriptionTier(tier)
            return TIER_LIMITS[tier_enum].debates_per_month
        except (ImportError, ValueError, KeyError):
            return _DEFAULT_LIVE_LIMITS.get(tier, _DEFAULT_LIVE_LIMITS["free"])

    # -- main check -----------------------------------------------------------

    def check_budget(self, org_id: str, tier: str) -> tuple[bool, dict[str, Any] | None]:
        """Check whether the org still has live-streaming budget.

        Returns ``(True, None)`` if allowed, or ``(False, error_dict)``
        with a JSON-ready error payload if the budget is exhausted.
        """
        limit = self.get_tier_limit(tier)
        current = self.get_usage(org_id)

        if current >= limit:
            from aragora.billing.tier_gating import TIER_DISPLAY_NAMES

            next_tier = "starter" if tier == "free" else "professional"
            display = TIER_DISPLAY_NAMES.get(next_tier, next_tier.title())
            return False, {
                "error": (
                    f"Monthly live debate limit ({limit}) reached for your "
                    f"{TIER_DISPLAY_NAMES.get(tier, tier)} plan."
                ),
                "code": "live_budget_exceeded",
                "current_usage": current,
                "limit": limit,
                "upgrade_url": "/pricing",
                "upgrade_prompt": f"Upgrade to {display} for more live debates.",
            }

        return True, None

    def record_usage(self, org_id: str) -> int:
        """Record a live-streaming usage event and return new count."""
        return self.increment(org_id)


def get_settings() -> Any:
    """Lazily resolve settings for patchable MFA checks in tests."""
    from aragora.config.settings import get_settings as _get_settings

    return _get_settings()


class AuthChecksMixin:
    """Mixin providing authentication and authorization checking methods.

    This mixin expects the following class attributes from the parent:
    - headers: HTTP headers dict
    - command: HTTP method (GET, POST, etc.)
    - path: Request path
    - user_store: Optional UserStore for tier-based rate limiting

    And these methods from ResponseHelpersMixin:
    - _send_json(data, status): Send JSON response

    Auth exempt paths are defined as class attributes and can be customized
    by subclasses.
    """

    # Paths exempt from authentication (health checks, probes, OAuth flow, public read-only)
    AUTH_EXEMPT_PATHS: frozenset[str] = frozenset(
        [
            # Health checks (needed for load balancers, monitoring)
            "/healthz",
            "/readyz",
            "/api/health",
            "/api/health/detailed",
            "/api/health/deep",
            "/api/health/stores",
            "/api/v1/health",
            "/api/v1/health/detailed",
            "/api/v1/health/deep",
            "/api/v1/health/stores",
            # OAuth
            "/api/auth/oauth/providers",  # Login page needs to show available providers
            "/api/v1/auth/oauth/providers",  # v1 route
            # API documentation — require auth to prevent attack surface mapping
            # Authenticated users can still access docs via /api/docs
            # "/api/openapi",  # LOCKED: full spec exposes 2,562 paths
            # "/api/openapi.json",
            # "/api/openapi.yaml",
            # "/api/postman.json",
            # "/api/docs",
            # "/api/docs/",
            # "/api/redoc",
            # "/api/redoc/",
            # "/api/v1/openapi",
            # "/api/v1/openapi.json",
            # "/api/v1/docs",
            # "/api/v1/docs/",
            # Read-only public endpoints
            "/api/insights/recent",
            "/api/flips/recent",
            "/api/evidence",
            "/api/evidence/statistics",
            "/api/verification/status",
            "/api/v1/insights/recent",
            "/api/v1/flips/recent",
            "/api/v1/evidence",
            "/api/v1/evidence/statistics",
            "/api/v1/verification/status",
            # Agent/ranking public data
            "/api/leaderboard",
            "/api/leaderboard-view",
            "/api/agents",
            "/api/v1/leaderboard",
            "/api/v1/leaderboard-view",
            "/api/v1/agents",
            # Public dashboard base paths (without trailing slash)
            # These match exact requests like /api/features that don't have a subpath
            # LOCKED: reveals which security features are disabled
            # "/api/features",
            # "/api/v1/features",
            "/api/analytics",
            "/api/v1/analytics",
            "/api/replays",
            "/api/v1/replays",
            "/api/tournaments",
            "/api/v1/tournaments",
            "/api/reviews",
            "/api/v1/reviews",
            "/api/verticals",
            "/api/v1/verticals",
            "/api/evolution",
            "/api/v1/evolution",
            # LOCKED: returns full debate data without auth
            # "/api/debates",
            # "/api/v1/debates",
            "/api/moments",
            "/api/v1/moments",
            "/api/breakpoints",
            "/api/v1/breakpoints",
            "/api/consensus",
            "/api/v1/consensus",
            "/api/consensus/active",
            "/api/v1/consensus/active",
            "/api/pipeline/plans",
            "/api/v1/pipeline/plans",
            "/api/plans",
            "/api/v1/plans",
            # Metrics (public dashboard monitoring)
            "/api/metrics",
            "/api/v1/metrics",
            # LOCKED: leaks server filesystem path /home/ec2-user/aragora/
            # "/api/nomic/state",
            # "/api/v1/nomic/state",
            # Playground - only mock debate is free (no API credits used)
            "/api/v1/playground/debate",
            # Live debate + TTS: NOT exempt — require auth + budget gate
            # (handled by _check_live_streaming_budget in the request pipeline)
            "/api/v1/playground/status",
            # OAuth callbacks from external providers (redirects carry no auth headers)
            "/api/integrations/slack/callback",
            "/api/integrations/teams/callback",
            "/api/integrations/discord/callback",
            "/api/integrations/google/callback",
            "/api/integrations/zoom/callback",
            "/api/v1/bots/slack/oauth/callback",
            "/api/v1/bots/slack/oauth/start",
        ]
    )

    # Path prefixes exempt from authentication (OAuth callbacks, read-only data)
    # Note: These endpoints bypass the legacy API token check (ARAGORA_API_TOKEN).
    # JWT authentication is still enforced via RBAC middleware for protected endpoints.
    AUTH_EXEMPT_PREFIXES: tuple[str, ...] = (
        "/api/auth/",  # All auth endpoints (JWT auth via RBAC, not API token)
        "/api/v1/auth/",  # All v1 auth endpoints (JWT auth via RBAC, not API token)
        "/api/agent/",  # Agent profiles (read-only)
        "/api/v1/agent/",  # Agent profiles v1 routes
        "/api/routing/",  # Domain detection and routing (read-only)
        "/api/v1/routing/",  # Domain routing v1 routes
    )

    # Path prefixes exempt ONLY for GET requests (read-only access)
    # These are public dashboard data endpoints that don't require auth for viewing
    AUTH_EXEMPT_GET_PREFIXES: tuple[str, ...] = (
        "/api/evidence/",  # Evidence read-only access
        "/api/v1/evidence/",  # Evidence read-only access (v1)
        "/api/evolution/",  # Public evolution data
        "/api/v1/evolution/",  # Public evolution data (v1)
        "/api/analytics/",  # Public analytics dashboards (stubbed when unauthenticated)
        "/api/v1/analytics/",  # Public analytics dashboards (v1)
        "/api/replays/",  # Public replay browsing
        "/api/v1/replays/",  # Public replay browsing (v1)
        "/api/learning/",  # Public learning evolution data
        "/api/v1/learning/",  # Public learning evolution data (v1)
        "/api/meta-learning/",  # Public meta-learning stats
        "/api/v1/meta-learning/",  # Public meta-learning stats (v1)
        "/api/tournaments/",  # Public tournament data
        "/api/v1/tournaments/",  # Public tournament data (v1)
        "/api/reviews/",  # Public reviews
        "/api/v1/reviews/",  # Public reviews (v1)
        "/api/consensus/",  # Public consensus read-only data
        "/api/v1/consensus/",  # Public consensus read-only data (v1)
        "/api/moments/",  # Public moments summaries
        "/api/v1/moments/",  # Public moments summaries (v1)
        "/api/flips/",  # Public flip summaries
        "/api/v1/flips/",  # Public flip summaries (v1)
        "/api/belief-network/",  # Public belief network summaries
        "/api/v1/belief-network/",  # Public belief network summaries (v1)
        "/api/verticals/",  # Public verticals list
        "/api/v1/verticals/",  # Public verticals list (v1)
        # LOCKED: reveals security feature status
        # "/api/features/",
        # "/api/v1/features/",
        "/api/gauntlet/personas",  # Public gauntlet personas list
        "/api/v1/gauntlet/personas",  # Public gauntlet personas list (v1)
        "/api/debates/public/",  # Public share links — no auth required
        "/api/v1/debates/public/",  # Public share links — no auth required (v1)
        # LOCKED: full debate listing requires auth
        # "/api/debates/",
        # "/api/v1/debates/",
        # LOCKED: internal metrics require auth
        # "/api/metrics/",
        # "/api/v1/metrics/",
        "/api/breakpoints/",  # Public breakpoints status
        "/api/v1/breakpoints/",  # Public breakpoints status (v1)
        "/api/plans/",  # Public decision plans
        "/api/v1/plans/",  # Public decision plans (v1)
        # LOCKED: leaks server paths
        # "/api/nomic/",
        # "/api/v1/nomic/",
    )

    # Type stubs for attributes expected from parent class
    headers: Any
    command: str
    path: str
    user_store: Optional["UserStore"]
    rbac: Any

    # Per-request rate limit result (set by _check_tier_rate_limit)
    _rate_limit_result: Optional["RateLimitResult"] = None

    # Type stubs for methods expected from parent class
    def _send_json(self, data: dict[str, Any], status: int = 200) -> None:
        """Send JSON response - provided by ResponseHelpersMixin."""
        ...

    def _is_path_exempt(self, path: str) -> bool:
        """Check if path is exempt from authentication.

        Args:
            path: The URL path to check

        Returns:
            True if the path is exempt from auth, False otherwise
        """
        if path in self.AUTH_EXEMPT_PATHS:
            return True
        if any(path.startswith(prefix) for prefix in self.AUTH_EXEMPT_PREFIXES):
            return True
        return False

    def _is_path_exempt_for_get(self, path: str) -> bool:
        """Check if path is exempt from authentication for GET requests only.

        Args:
            path: The URL path to check

        Returns:
            True if the path is exempt for GET, False otherwise
        """
        return any(path.startswith(prefix) for prefix in self.AUTH_EXEMPT_GET_PREFIXES)

    def _check_rate_limit(self) -> bool:
        """Check auth and rate limit. Returns True if allowed, False if blocked.

        Sends appropriate error response if blocked.

        This method checks:
        1. If path is exempt from auth
        2. If auth is enabled
        3. If authentication is valid
        4. If rate limit is exceeded

        Returns:
            True if request is allowed, False if blocked
        """
        # Check exemptions BEFORE imports so exempt paths work even if
        # auth modules have import issues in production
        parsed = urlparse(self.path)
        if self._is_path_exempt(parsed.path):
            return True
        # For GET-only exempt paths, check method
        if self.command == "GET" and self._is_path_exempt_for_get(parsed.path):
            return True

        from aragora.server.auth import auth_config, check_auth

        if not auth_config.enabled:
            return True

        # Convert headers to dict
        headers = {k: v for k, v in self.headers.items()}

        authenticated, remaining = check_auth(headers, parsed.query)

        if not authenticated:
            if remaining == 0:
                # Rate limited
                self._send_json({"error": "Rate limit exceeded. Try again later."}, status=429)
            else:
                # Auth failed
                self._send_json({"error": "Authentication required"}, status=401)
            return False

        # Note: Rate limit headers are now added by individual handlers
        # that need to include them in their responses
        return True

    def _check_tier_rate_limit(self) -> bool:
        """Check tier-aware rate limit based on user's subscription.

        Returns True if allowed, False if blocked.
        Sends 429 error response if rate limited.
        Also stores the result for inclusion in response headers.

        The tier-based rate limiting applies different limits based on
        the user's subscription tier (free, pro, enterprise, etc.).

        Returns:
            True if request is allowed, False if rate limited
        """
        from aragora.server.middleware.rate_limit import check_tier_rate_limit

        result = check_tier_rate_limit(self, self.user_store)

        # Store result for response headers (used by _add_rate_limit_headers)
        self._rate_limit_result = result

        if not result.allowed:
            self._send_json(
                {
                    "error": "Rate limit exceeded for your subscription tier",
                    "code": "tier_rate_limit",
                    "limit": result.limit,
                    "retry_after": int(result.retry_after) + 1,
                    "upgrade_url": "/pricing",
                },
                status=429,
            )
            return False

        return True

    def _check_rbac(self, path: str, method: str) -> bool:
        """Check RBAC permission for the request.

        Returns True if allowed, False if blocked.
        Sends 401/403 error response if denied.

        This method:
        1. Checks if path is exempt from RBAC
        2. Extracts user context from JWT
        3. Builds authorization context with roles and permissions
        4. Checks if user has required permission for the route

        Args:
            path: The URL path being accessed
            method: The HTTP method (GET, POST, etc.)

        Returns:
            True if request is allowed, False if denied
        """
        # Check exemptions BEFORE imports so exempt paths work even if
        # billing/rbac modules have import issues
        if self._is_path_exempt(path):
            return True
        if method.upper() == "GET" and self._is_path_exempt_for_get(path):
            return True

        # When authentication is disabled (no ARAGORA_API_TOKEN), allow all
        # requests through RBAC — there's no user to authorize against.
        from aragora.server.auth import auth_config

        if not auth_config.enabled:
            return True

        from aragora.billing.auth import extract_user_from_request
        from aragora.rbac import AuthorizationContext, get_role_permissions

        logger.debug("RBAC auth check: %s %s", method, path)

        # Build authorization context from JWT
        auth_ctx = None
        try:
            user_ctx = extract_user_from_request(self, self.user_store)
            logger.debug(
                "RBAC user context: authenticated=%s, user_id=%s",
                user_ctx.authenticated,
                user_ctx.user_id,
            )
            if user_ctx.authenticated and user_ctx.user_id:
                roles = {user_ctx.role} if user_ctx.role else {"member"}
                permissions: set[str] = set()
                for role in roles:
                    permissions |= get_role_permissions(role, include_inherited=True)

                auth_ctx = AuthorizationContext(
                    user_id=user_ctx.user_id,
                    org_id=user_ctx.org_id,
                    roles=roles,
                    permissions=permissions,
                    ip_address=user_ctx.client_ip,
                )
                logger.debug("RBAC auth context created for user %s", user_ctx.user_id)
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            logger.debug("RBAC context extraction failed: %s", e)

        # Check permission
        allowed, reason, permission_key = self.rbac.check_request(path, method, auth_ctx)

        if not allowed:
            if auth_ctx is None:
                self._send_json(
                    {"error": "Authentication required", "code": "auth_required"},
                    status=401,
                )
            else:
                self._send_json(
                    {
                        "error": f"Permission denied: {reason}",
                        "code": "permission_denied",
                        "required_permission": permission_key,
                    },
                    status=403,
                )
            return False

        return True

    def _check_admin_mfa(self, path: str) -> bool:
        """Check MFA enforcement for admin users (SOC 2 CC5-01, GitHub #275).

        Returns True if allowed, False if blocked.
        Sends 403 error response if an admin user lacks MFA.

        This method:
        1. Checks if MFA enforcement is enabled via settings
        2. Checks if path is exempt (auth/health/MFA setup endpoints)
        3. Extracts user context from JWT to determine roles
        4. Delegates to MFAEnforcementMiddleware for policy evaluation
        5. Returns 403 with clear remediation instructions if denied

        Non-admin users always pass through. Admins within the grace
        period are allowed with a warning header. The MFA setup endpoint
        is always accessible so admins can bootstrap their MFA.

        Args:
            path: The URL path being accessed

        Returns:
            True if request is allowed, False if denied
        """
        from aragora.auth.mfa_enforcement import (
            MFAEnforcementMiddleware,
            MFAEnforcementPolicy,
            MFAEnforcementResult,
        )

        settings = get_settings()

        # Check if MFA enforcement is enabled
        if not settings.security.admin_mfa_required:
            return True

        # When authentication is disabled, no user to check
        from aragora.server.auth import auth_config

        if not auth_config.enabled:
            return True

        # Build enforcement policy from settings
        grace_period_hours = settings.security.admin_mfa_grace_period_days * 24
        policy = MFAEnforcementPolicy(
            enabled=True,
            grace_period_hours=grace_period_hours,
        )
        middleware = MFAEnforcementMiddleware(
            policy=policy,
            user_store=self.user_store,
        )

        # Extract user context (same pattern as _check_rbac)
        try:
            from aragora.billing.auth import extract_user_from_request

            user_ctx = extract_user_from_request(self, self.user_store)
            if not user_ctx.authenticated or not user_ctx.user_id:
                return True  # Unauthenticated requests handled by RBAC

            # Build a lightweight context for MFA enforcement
            roles = {user_ctx.role} if user_ctx.role else {"member"}

            class _MFAUserContext:
                """Lightweight user context for MFA enforcement."""

                def __init__(self, user_id: str, user_roles: set[str], meta: dict) -> None:
                    self.user_id = user_id
                    self.roles = user_roles
                    self.metadata = meta

            ctx = _MFAUserContext(
                user_id=user_ctx.user_id,
                user_roles=roles,
                meta=getattr(user_ctx, "metadata", {}) or {},
            )
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            logger.debug("MFA enforcement: context extraction failed: %s", e)
            return True  # Cannot enforce without user context

        # Run enforcement check
        decision = middleware.enforce(ctx, path=path)

        if decision.result == MFAEnforcementResult.DENIED:
            self._send_json(
                {
                    "error": decision.reason,
                    "code": "ADMIN_MFA_REQUIRED",
                    "required_action": decision.required_action or "/api/auth/mfa/setup",
                },
                status=403,
            )
            return False

        if decision.result == MFAEnforcementResult.GRACE_PERIOD:
            logger.info(
                "MFA enforcement: admin %s in grace period (%s hours remaining) on %s",
                decision.user_id,
                decision.grace_period_remaining_hours,
                path,
            )

        return True

    def _check_upload_rate_limit(self) -> bool:
        """Check IP-based upload rate limit. Returns True if allowed, False if blocked.

        This is a separate rate limit for file uploads to prevent abuse.
        Uses IP-based limiting regardless of authentication status.

        Returns:
            True if upload is allowed, False if rate limited
        """
        from typing import cast
        from http.server import BaseHTTPRequestHandler

        from aragora.server.upload_rate_limit import get_upload_limiter

        limiter = get_upload_limiter()
        # Cast self to BaseHTTPRequestHandler for type checking - the mixin
        # expects to be mixed with a handler that has client_address and headers
        client_ip = limiter.get_client_ip(cast(BaseHTTPRequestHandler, self))
        allowed, error_info = limiter.check_allowed(client_ip)

        if not allowed and error_info:
            self._send_json(
                {"error": error_info["message"], "retry_after": error_info["retry_after"]},
                status=429,
            )
            return False

        return True

    def _check_live_streaming_budget(self) -> bool:
        """Check auth + usage budget for live streaming endpoints.

        Budget-gated paths (live debate, cost-estimate, TTS) require:
        1. A valid authenticated user (not anonymous)
        2. Remaining monthly debate credits for the user's workspace/org

        Free tier: 10 live debates/month.
        Paid tiers: limits from TIER_LIMITS (starter=50, pro=200, enterprise=unlimited).

        When auth is disabled (dev/demo mode), requests pass through freely.
        When billing modules are unavailable, access is allowed (graceful degradation).

        Returns:
            True if request is allowed, False if blocked (response already sent).
        """
        parsed = urlparse(self.path)
        if parsed.path not in BUDGET_GATED_PATHS:
            return True

        # When auth is disabled, allow live streaming in dev/demo mode
        from aragora.server.auth import auth_config

        if not auth_config.enabled:
            return True

        # Step 1: Require authentication
        from aragora.billing.auth import extract_user_from_request

        try:
            user_ctx = extract_user_from_request(self, self.user_store)
        except (ValueError, KeyError, AttributeError, TypeError) as e:
            logger.debug("Live streaming budget: auth extraction failed: %s", e)
            self._send_json(
                {
                    "error": "Authentication required for live debates",
                    "code": "auth_required",
                    "hint": "Sign in to access live debate streaming.",
                },
                status=401,
            )
            return False

        if not user_ctx.authenticated or not user_ctx.user_id:
            self._send_json(
                {
                    "error": "Authentication required for live debates",
                    "code": "auth_required",
                    "hint": "Sign in to access live debate streaming.",
                },
                status=401,
            )
            return False

        # Step 2: Resolve org tier
        org_id = user_ctx.org_id or user_ctx.user_id  # fall back to user as workspace
        tier = "free"
        try:
            from aragora.billing.tier_gating import _resolve_org_tier

            class _TierCtx:
                """Minimal context for tier resolution."""

                def __init__(self, oid: str | None) -> None:
                    self.org_id = oid
                    self.subscription_tier = None

            resolved = _resolve_org_tier(_TierCtx(user_ctx.org_id))
            if resolved:
                tier = resolved
        except (ImportError, ValueError, KeyError, AttributeError, TypeError):
            pass  # graceful degradation: default to free

        # Step 3: Check budget
        try:
            gate = LiveStreamingBudgetGate.get_instance()
            allowed, error_info = gate.check_budget(org_id, tier)
        except (OSError, sqlite3.Error) as e:
            # Database issues should not block the user
            logger.warning("Live streaming budget gate DB error, allowing request: %s", e)
            return True

        if not allowed and error_info:
            self._send_json(error_info, status=429)
            return False

        # Step 4: Record usage (only for actual live debate requests, not cost estimates)
        if parsed.path == "/api/v1/playground/debate/live":
            try:
                gate.record_usage(org_id)
                logger.info(
                    "Live debate usage recorded: org=%s tier=%s",
                    org_id,
                    tier,
                )
            except (OSError, sqlite3.Error) as e:
                logger.warning("Failed to record live streaming usage: %s", e)

        return True


__all__ = [
    "AuthChecksMixin",
    "LiveStreamingBudgetGate",
    "BUDGET_GATED_PATHS",
]
