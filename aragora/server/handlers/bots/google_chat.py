"""
Google Chat Bot webhook handler.

Handles Google Chat App webhook events for bidirectional chat.

Endpoints:
- POST /api/bots/google-chat/webhook - Handle Google Chat events
- GET  /api/bots/google-chat/status - Get bot status

Environment Variables:
- GOOGLE_CHAT_CREDENTIALS - Service account JSON or path to file
- GOOGLE_CHAT_PROJECT_ID - Google Cloud project ID
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any, Protocol, cast
from collections.abc import Coroutine

from aragora.audit.unified import audit_data

if TYPE_CHECKING:
    pass


class VoteRecordingStore(Protocol):
    """Protocol for stores that can record votes.

    This is a forward-looking interface - ConsensusStore with record_vote
    is planned but not yet implemented. The code gracefully handles ImportError.
    """

    def record_vote(
        self,
        debate_id: str,
        user_id: str,
        vote: str,
        source: str,
    ) -> None:
        """Record a user vote on a debate outcome."""
        ...


from aragora.config import DEFAULT_AGENTS, DEFAULT_CONSENSUS, DEFAULT_ROUNDS
from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.server.handlers.bots.base import BotHandlerMixin
from aragora.server.handlers.secure import SecureHandler
from aragora.server.handlers.utils.rate_limit import rate_limit

# RBAC imports - optional dependency
try:
    from aragora.rbac.checker import check_permission  # noqa: F401
    from aragora.rbac.models import AuthorizationContext  # noqa: F401

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

logger = logging.getLogger(__name__)

# Environment variables - None defaults make misconfiguration explicit
GOOGLE_CHAT_CREDENTIALS = os.environ.get("GOOGLE_CHAT_CREDENTIALS")
GOOGLE_CHAT_PROJECT_ID = os.environ.get("GOOGLE_CHAT_PROJECT_ID")

# Log at debug level for unconfigured optional integrations
if not GOOGLE_CHAT_CREDENTIALS:
    logger.debug("GOOGLE_CHAT_CREDENTIALS not configured - Google Chat bot disabled")


# ---------------------------------------------------------------------------
# Token verification cache
# ---------------------------------------------------------------------------
# Valid tokens are cached longer (5 min) since they won't change mid-session.
# Invalid tokens are cached briefly (1 min) to avoid hammering verifiers on
# repeated bad requests, but expire quickly so a key rotation can unblock.
_TOKEN_CACHE_VALID_TTL: float = 300.0  # 5 minutes for valid tokens
_TOKEN_CACHE_INVALID_TTL: float = 60.0  # 1 minute for invalid tokens

_token_cache: dict[str, tuple[bool, float]] = {}
_token_cache_lock = threading.Lock()


def _token_cache_key(token: str) -> str:
    """Derive a cache key from a token without storing the raw token.

    Uses SHA-256 so the cache never holds plaintext credentials.
    """
    return hashlib.sha256(token.encode("utf-8", errors="replace")).hexdigest()


def _get_cached_result(token: str) -> bool | None:
    """Return a cached verification result, or None on miss / expiry."""
    key = _token_cache_key(token)
    with _token_cache_lock:
        entry = _token_cache.get(key)
        if entry is None:
            return None
        result, expiry = entry
        if time.monotonic() > expiry:
            # Expired -- evict and treat as miss
            del _token_cache[key]
            return None
        return result


def _set_cached_result(token: str, result: bool) -> None:
    """Store a verification result with an appropriate TTL."""
    ttl = _TOKEN_CACHE_VALID_TTL if result else _TOKEN_CACHE_INVALID_TTL
    key = _token_cache_key(token)
    with _token_cache_lock:
        _token_cache[key] = (result, time.monotonic() + ttl)


def clear_token_cache() -> None:
    """Remove all entries from the token cache."""
    with _token_cache_lock:
        _token_cache.clear()


# ---------------------------------------------------------------------------
# Individual verification layers
# ---------------------------------------------------------------------------
# Each layer returns True (valid), False (invalid), or None (layer unavailable
# / inconclusive -- caller should try the next layer).
# ---------------------------------------------------------------------------


def _verify_token_via_jwt_verifier(token: str) -> bool | None:
    """Layer 1: Verify using the JWTVerifier from aragora.connectors.chat.jwt_verify.

    Returns:
        True if the token is valid, False if definitely invalid,
        None if this layer is unavailable (PyJWT missing, JWKS fetch failed, etc.).
    """
    try:
        from aragora.connectors.chat.jwt_verify import verify_google_chat_webhook

        # verify_google_chat_webhook expects "Bearer <token>"
        result = verify_google_chat_webhook(f"Bearer {token}", GOOGLE_CHAT_PROJECT_ID)
        return result
    except ImportError:
        logger.debug("jwt_verify module not available, skipping JWT verifier layer")
        return None
    except RuntimeError as e:
        logger.debug("JWT verifier runtime error (will try next layer): %s", e)
        return None


def _verify_token_via_google_auth(token: str) -> bool | None:
    """Layer 2: Verify using google-auth (google.oauth2.id_token).

    Returns:
        True if the token is valid, False if definitely invalid,
        None if google-auth is not installed.
    """
    try:
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
    except ImportError:
        logger.debug("google-auth not installed, skipping google-auth layer")
        return None

    # In production, require a project_id for audience validation
    if GOOGLE_CHAT_PROJECT_ID is None:
        if os.environ.get("ARAGORA_ENV", "").lower() in ("production", "prod"):
            logger.warning(
                "SECURITY: Google Chat project ID not set in production -- rejecting token"
            )
            return False
        # Dev mode -- skip audience check entirely
        expected_audience = None
    else:
        expected_audience = GOOGLE_CHAT_PROJECT_ID

    try:
        id_info = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            audience=expected_audience,
        )

        # Verify the token is from Google Chat
        email = id_info.get("email", "")
        if not email.endswith("@system.gserviceaccount.com"):
            logger.warning("Google Chat token from unexpected email: %s", email)
            return False

        return True

    except ValueError as e:
        logger.warning("google-auth token verification failed: %s", e)
        return False
    except (RuntimeError, TypeError, OSError) as e:
        logger.debug("google-auth unexpected error (will try next layer): %s", e)
        return None


def _verify_token_via_tokeninfo(token: str) -> bool | None:
    """Layer 3: Verify via Google's tokeninfo HTTP endpoint (fallback).

    Returns:
        True if the token is valid, False if definitely invalid,
        None if the endpoint is unreachable (network error).
    """
    url = f"https://oauth2.googleapis.com/tokeninfo?access_token={token}"

    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310 -- hardcoded Google OAuth URL
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 -- hardcoded Google OAuth URL
            data = json.loads(resp.read().decode("utf-8"))

        # Check email is a Google Chat service account
        email = data.get("email", "")
        if not email.endswith("@system.gserviceaccount.com"):
            logger.warning("tokeninfo: unexpected email %s", email)
            return False

        # Check audience if project_id is configured
        if GOOGLE_CHAT_PROJECT_ID:
            aud = data.get("aud", "")
            if aud != GOOGLE_CHAT_PROJECT_ID:
                logger.warning(
                    "tokeninfo: audience mismatch (got %s, expected %s)",
                    aud,
                    GOOGLE_CHAT_PROJECT_ID,
                )
                return False

        # Check expiry
        try:
            exp = int(data.get("exp", 0))
            if exp < int(time.time()):
                logger.warning("tokeninfo: token expired")
                return False
        except (ValueError, TypeError):
            logger.warning("tokeninfo: could not parse expiry")
            return False

        return True

    except urllib.error.HTTPError as e:
        logger.warning("tokeninfo HTTP error %s: token likely invalid", e.code)
        return False
    except urllib.error.URLError as e:
        logger.debug("tokeninfo network error (endpoint unreachable): %s", e)
        return None
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("tokeninfo unexpected error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Main verification entry point
# ---------------------------------------------------------------------------


def _verify_google_chat_token(auth_header: str) -> bool:
    """Verify a Google Chat bearer token using a layered verification strategy.

    Verification layers (tried in order, first definitive answer wins):
    1. JWT verifier (PyJWT + JWKS) -- strongest
    2. google-auth (google.oauth2.id_token) -- strong
    3. tokeninfo HTTP endpoint -- weakest but needs no dependencies

    Results are cached to avoid repeated network calls for the same token.

    Args:
        auth_header: The Authorization header value (e.g., "Bearer <token>")

    Returns:
        True if token is valid, False otherwise.  Fails closed: if all
        layers are unavailable the token is rejected.
    """
    if not auth_header or not auth_header.startswith("Bearer "):
        return False

    token = auth_header[7:].strip()

    if not token:
        return False

    # Check cache first
    cached = _get_cached_result(token)
    if cached is not None:
        return cached

    # Try each verification layer in order
    for layer in (
        _verify_token_via_jwt_verifier,
        _verify_token_via_google_auth,
        _verify_token_via_tokeninfo,
    ):
        result = layer(token)
        if result is not None:
            _set_cached_result(token, result)
            return result

    # All layers unavailable -- fail closed
    logger.warning("All Google Chat token verification layers unavailable -- rejecting token")
    return False


# Input validation limits
MAX_TOPIC_LENGTH = 500
MAX_STATEMENT_LENGTH = 1000


def _handle_task_exception(task: asyncio.Task[Any], task_name: str) -> None:
    """Handle exceptions from fire-and-forget async tasks."""
    if task.cancelled():
        logger.debug("Task %s was cancelled", task_name)
    elif task.exception():
        exc = task.exception()
        logger.error("Task %s failed: %s", task_name, exc, exc_info=exc)


def create_tracked_task(coro: Coroutine[Any, Any, Any], name: str) -> asyncio.Task[Any]:
    """Create an async task with exception logging."""
    task = asyncio.create_task(coro, name=name)
    task.add_done_callback(lambda t: _handle_task_exception(t, name))
    return task


# Cache for Google Chat connector
_google_chat_connector: Any | None = None


def get_google_chat_connector() -> Any | None:
    """Get or create the Google Chat connector singleton."""
    global _google_chat_connector
    if _google_chat_connector is None:
        if not GOOGLE_CHAT_CREDENTIALS:
            logger.debug("Google Chat connector disabled (no GOOGLE_CHAT_CREDENTIALS)")
            return None
        try:
            from aragora.connectors.chat.google_chat import GoogleChatConnector

            _google_chat_connector = GoogleChatConnector(
                credentials_json=GOOGLE_CHAT_CREDENTIALS,
                project_id=GOOGLE_CHAT_PROJECT_ID,
            )
            logger.info("Google Chat connector initialized")
        except ImportError as e:
            logger.warning("Google Chat connector module not available: %s", e)
            return None
        except (RuntimeError, ValueError, OSError) as e:
            logger.exception("Error initializing Google Chat connector: %s", e)
            return None
    return _google_chat_connector


class GoogleChatHandler(BotHandlerMixin, SecureHandler):
    """Handler for Google Chat App webhook endpoints.

    Uses BotHandlerMixin for shared auth/status patterns.

    RBAC Protected:
    - bots.read - required for status endpoint

    Note: Webhook endpoints are authenticated via Google's bearer token,
    not RBAC, since they are called by Google servers directly.
    """

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    # ------------------------------------------------------------------
    # RBAC helper
    # ------------------------------------------------------------------

    def _check_bot_permission(
        self, permission: str, *, user_id: str = "", context: dict | None = None
    ) -> None:
        """Check RBAC permission if available.

        Args:
            permission: The permission string to check (e.g. "debates:create").
            user_id: Platform-qualified user id (e.g. "gchat:12345").
            context: Optional dict that may carry an ``auth_context`` key.

        Raises:
            PermissionError: When RBAC is available and the check fails.
        """
        if not RBAC_AVAILABLE:
            if rbac_fail_closed():
                raise PermissionError("Service unavailable: access control module not loaded")
            return
        auth_ctx = (context or {}).get("auth_context")
        if auth_ctx is None and user_id:
            auth_ctx = AuthorizationContext(
                user_id=user_id,
                roles={"bot_user"},
            )
        if auth_ctx:
            check_permission(auth_ctx, permission)

    # BotHandlerMixin configuration
    bot_platform = "google_chat"

    ROUTES = [
        "/api/v1/bots/google-chat/webhook",
        "/api/v1/bots/google-chat/status",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    def _is_bot_enabled(self) -> bool:
        """Check if Google Chat bot is configured."""
        connector = get_google_chat_connector()
        return connector is not None

    def _build_status_response(self, extra_status: dict[str, Any] | None = None) -> HandlerResult:
        """Build Google Chat-specific status response."""
        status = {
            "platform": self.bot_platform,
            "enabled": self._is_bot_enabled(),
            "credentials_configured": bool(GOOGLE_CHAT_CREDENTIALS),
            "project_id_configured": bool(GOOGLE_CHAT_PROJECT_ID),
        }
        if extra_status:
            status.update(extra_status)
        return json_response(status)

    def _extract_attachments(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract attachments from a Google Chat event payload."""
        message = event.get("message")
        if not isinstance(message, dict):
            return []
        attachments = message.get("attachments")
        if not isinstance(attachments, list):
            return []

        normalized: list[dict[str, Any]] = []
        for idx, attachment in enumerate(attachments):
            if not isinstance(attachment, dict):
                continue
            entry = dict(attachment)
            filename = (
                entry.get("name")
                or entry.get("filename")
                or entry.get("contentName")
                or f"attachment_{idx + 1}"
            )
            if filename and "filename" not in entry:
                entry["filename"] = filename
            normalized.append(entry)
        return normalized

    @rate_limit(requests_per_minute=60)
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route Google Chat GET requests with RBAC for status endpoint."""
        if path == "/api/v1/bots/google-chat/status":
            # Use BotHandlerMixin's RBAC-protected status handler
            return await self.handle_status_request(handler)

        return None

    @handle_errors("google chat creation")
    @rate_limit(requests_per_minute=120)
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests (webhook events)."""
        if path == "/api/v1/bots/google-chat/webhook":
            return self._handle_webhook(handler)

        return None

    def _handle_webhook(self, handler: Any) -> HandlerResult:
        """Handle Google Chat webhook events.

        Google Chat sends events to this endpoint for:
        - Messages (regular and slash commands)
        - Card button clicks
        - Bot added/removed from space

        Authentication: Google Chat sends a bearer token in the Authorization header.
        We verify the project ID matches our configuration.
        """
        # Require credentials to be configured
        if not GOOGLE_CHAT_CREDENTIALS:
            logger.warning("GOOGLE_CHAT_CREDENTIALS not configured - rejecting webhook request")
            return json_response(
                {"error": "Google Chat credentials not configured"},
                status=503,
            )

        # Verify bearer token (Google Chat authentication)
        auth_header = handler.headers.get("Authorization", "")
        if not _verify_google_chat_token(auth_header):
            logger.warning("Google Chat webhook authentication failed")
            self._audit_webhook_auth_failure("bearer_token", "invalid")
            return error_response("Invalid authorization", 401)

        try:
            # Read and parse body
            body = self._read_request_body(handler)
            event, err = self._parse_json_body(body, "Google Chat event")
            if err:
                return err
            event = cast(dict[str, Any], event)

            event_type = event.get("type", "")
            logger.debug("Google Chat event: %s", event_type)

            # Route by event type
            if event_type == "MESSAGE":
                return self._handle_message(event)
            elif event_type == "CARD_CLICKED":
                return self._handle_card_click(event)
            elif event_type == "ADDED_TO_SPACE":
                return self._handle_added_to_space(event)
            elif event_type == "REMOVED_FROM_SPACE":
                return self._handle_removed_from_space(event)
            else:
                logger.debug("Unhandled Google Chat event type: %s", event_type)
                return json_response({})

        except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError) as e:
            logger.exception("Google Chat webhook error: %s", e)
            return json_response({"text": "An error occurred processing the webhook"})

    def _handle_message(self, event: dict[str, Any]) -> HandlerResult:
        """Handle incoming Google Chat message."""
        message = event.get("message", {})
        space = event.get("space", {})
        user = event.get("user", {})

        space_name = space.get("name", "")
        space_type = space.get("type", "")
        user_name = user.get("displayName", "Unknown")
        text = message.get("text", "")

        logger.info("Google Chat message from %s: %s...", user_name, text[:50])

        # Check for slash command
        slash_command = message.get("slashCommand")
        if slash_command:
            command_name = slash_command.get("commandName", "").lstrip("/")
            args = message.get("argumentText", "")
            return self._handle_slash_command(command_name, args, space_name, user, event)

        # Check if in DM - treat as implicit debate request
        if space_type == "DM" and text.strip():
            return self._start_debate_from_message(text, space_name, user, event)

        # Check for @mention
        mentions = message.get("annotations", [])
        for mention in mentions:
            if (
                mention.get("type") == "USER_MENTION"
                and mention.get("userMention", {}).get("type") == "BOT"
            ):
                # Bot was mentioned - extract text after mention
                mention_text = text
                if mention_text.strip():
                    return self._start_debate_from_message(mention_text, space_name, user, event)

        # Regular message in group - acknowledge
        return json_response({})

    def _handle_slash_command(
        self,
        command: str,
        args: str,
        space_name: str,
        user: dict[str, Any],
        event: dict[str, Any],
    ) -> HandlerResult:
        """Handle Google Chat slash command."""
        command = command.lower()
        user_name = user.get("displayName", "Unknown")

        logger.info("Google Chat command from %s: /%s %s...", user_name, command, args[:50])

        if command in ("debate", "plan", "implement"):
            decision_integrity = None
            if command in ("plan", "implement"):
                decision_integrity = {
                    "include_receipt": True,
                    "include_plan": True,
                    "include_context": command == "implement",
                    "plan_strategy": "single_task",
                    "notify_origin": True,
                }
                if command == "implement":
                    decision_integrity["execution_mode"] = "execute"
                    decision_integrity["execution_engine"] = "hybrid"
            return self._cmd_debate(args, space_name, user, event, decision_integrity)
        elif command == "gauntlet":
            return self._cmd_gauntlet(args, space_name, user, event)
        elif command == "status":
            return self._cmd_status(space_name)
        elif command == "help":
            return self._cmd_help()
        elif command == "agents":
            return self._cmd_agents()
        else:
            return self._card_response(
                title="Unknown Command",
                body=f"Unknown command: /{command}\n\nUse /help for available commands.",
            )

    def _handle_card_click(self, event: dict[str, Any]) -> HandlerResult:
        """Handle Google Chat card button click."""
        action = event.get("action", {})
        function_name = action.get("actionMethodName", "")
        params = {p.get("key"): p.get("value") for p in action.get("parameters", [])}

        user = event.get("user", {})
        user_id = user.get("name", "").split("/")[-1]
        space = event.get("space", {})
        space_name = space.get("name", "")

        logger.info("Google Chat card click: %s from %s", function_name, user_id)

        # Route actions
        if function_name == "vote_agree":
            return self._handle_vote(params.get("debate_id", ""), "agree", user_id, space_name)
        elif function_name == "vote_disagree":
            return self._handle_vote(params.get("debate_id", ""), "disagree", user_id, space_name)
        elif function_name == "view_details":
            return self._handle_view_details(params.get("debate_id", ""))

        return json_response({})

    def _handle_vote(
        self, debate_id: str, vote_option: str, user_id: str, space_name: str
    ) -> HandlerResult:
        """Handle vote button click."""
        if not debate_id:
            return self._card_response(body="Error: No debate ID provided")

        # RBAC: check vote permission
        try:
            self._check_bot_permission("votes:record", user_id=f"gchat:{user_id}")
        except PermissionError as exc:
            logger.warning("RBAC denied votes:record for gchat:%s: %s", user_id, exc)
            return self._card_response(body="Permission denied: you cannot vote.")

        logger.info("Vote from %s on %s: %s", user_id, debate_id, vote_option)

        try:
            # ConsensusStore with record_vote is a planned feature.
            # This import will fail until it's implemented.
            from aragora.memory.consensus import ConsensusStore

            store: VoteRecordingStore = cast(VoteRecordingStore, ConsensusStore())
            store.record_vote(
                debate_id=debate_id,
                user_id=f"gchat:{user_id}",
                vote=vote_option,
                source="google_chat",
            )

            audit_data(
                user_id=f"gchat:{user_id}",
                resource_type="debate_vote",
                resource_id=debate_id,
                action="create",
                vote_option=vote_option,
                platform="google_chat",
            )

            emoji = "✅" if vote_option == "agree" else "❌"
            return self._card_response(
                body=f"{emoji} Your vote for '{vote_option}' has been recorded!"
            )

        except ImportError:
            logger.warning("ConsensusStore not available")
            return self._card_response(body="Vote acknowledged")
        except (RuntimeError, ValueError, KeyError, AttributeError) as e:
            logger.error("Vote recording failed: %s", e)
            return self._card_response(body="Error recording vote")

    def _handle_view_details(self, debate_id: str) -> HandlerResult:
        """Handle view details button click."""
        if not debate_id:
            return self._card_response(body="Error: No debate ID provided")

        try:
            from aragora.server.storage import get_debates_db

            db = get_debates_db()
            debate = db.get(debate_id) if db else None

            if not debate:
                return self._card_response(body=f"Debate {debate_id} not found")

            task = debate.get("task", "Unknown topic")
            final_answer = debate.get("final_answer", "No conclusion")
            consensus = debate.get("consensus_reached", False)
            confidence = debate.get("confidence", 0)
            rounds_used = debate.get("rounds_used", 0)

            return self._card_response(
                title="Debate Details",
                body=f"*Topic:* {task[:200]}\n\n"
                f"*Consensus:* {'Yes' if consensus else 'No'}\n"
                f"*Confidence:* {confidence:.1%}\n"
                f"*Rounds:* {rounds_used}\n\n"
                f"*Conclusion:*\n{final_answer[:500]}...",
            )

        except (ImportError, RuntimeError, KeyError, AttributeError) as e:
            logger.error("View details failed: %s", e)
            return self._card_response(body="Error fetching debate details")

    def _handle_added_to_space(self, event: dict[str, Any]) -> HandlerResult:
        """Handle bot added to space."""
        space = event.get("space", {})
        space.get("displayName", "this space")

        return self._card_response(
            title="Welcome to Aragora!",
            body="I'm a control plane for multi-agent vetted decisionmaking.\n\n"
            "I orchestrate 15+ AI models (Claude, GPT, Gemini, Grok and more) "
            "to debate and deliver defensible decisions.\n\n"
            "*Commands:*\n"
            "/debate <topic> - Start a multi-agent vetted decisionmaking\n"
            "/plan <topic> - Debate + implementation plan\n"
            "/implement <topic> - Debate + plan with context snapshot\n"
            "/gauntlet <statement> - Run adversarial validation\n"
            "/status - Check system status\n"
            "/help - Show available commands\n\n"
            "Or just @mention me with a question!",
        )

    def _handle_removed_from_space(self, event: dict[str, Any]) -> HandlerResult:
        """Handle bot removed from space."""
        space = event.get("space", {})
        logger.info("Bot removed from space: %s", space.get("name"))
        return json_response({})

    # ==========================================================================
    # Slash Command Implementations
    # ==========================================================================

    def _cmd_help(self) -> HandlerResult:
        """Show help message."""
        return self._card_response(
            title="Aragora Commands",
            body="*/debate <topic>* - Start a multi-agent debate\n"
            "*/plan <topic>* - Debate + implementation plan\n"
            "*/implement <topic>* - Debate + plan with context snapshot\n"
            "*/gauntlet <statement>* - Run adversarial stress-test\n"
            "*/status* - Check system status\n"
            "*/agents* - List available agents\n"
            "*/help* - Show this message\n\n"
            "*Examples:*\n"
            "/debate Should AI be regulated?\n"
            "/gauntlet We should migrate to microservices",
        )

    def _cmd_status(self, space_name: str) -> HandlerResult:
        """Show system status."""
        try:
            from aragora.ranking.elo import EloSystem

            store = EloSystem()
            agents = store.get_all_ratings()

            return self._card_response(
                title="Aragora System Status",
                fields=[
                    ("Status", "Online"),
                    ("Agents", str(len(agents))),
                    ("Models", "Claude, GPT, Gemini, Grok, Mistral, DeepSeek"),
                ],
            )

        except ImportError:
            return self._card_response(
                title="Aragora System Status",
                fields=[("Status", "Online"), ("Agents", "Available")],
            )

    def _cmd_agents(self) -> HandlerResult:
        """List available agents."""
        try:
            from aragora.ranking.elo import EloSystem

            store = EloSystem()
            agents = store.get_all_ratings()

            if not agents:
                return self._card_response(body="No agents registered yet.")

            agents = sorted(agents, key=lambda a: getattr(a, "elo", 1500), reverse=True)

            lines = []
            for i, agent in enumerate(agents[:10]):
                name = getattr(agent, "name", "Unknown")
                elo = getattr(agent, "elo", 1500)
                medal = ["🥇", "🥈", "🥉"][i] if i < 3 else f"{i + 1}."
                lines.append(f"{medal} *{name}* - ELO: {elo:.0f}")

            return self._card_response(
                title="Top Agents by ELO",
                body="\n".join(lines),
            )

        except ImportError:
            return self._card_response(body="Agents service temporarily unavailable")

    def _cmd_debate(
        self,
        topic: str,
        space_name: str,
        user: dict[str, Any],
        event: dict[str, Any],
        decision_integrity: dict[str, Any] | bool | None = None,
    ) -> HandlerResult:
        """Start a debate."""
        # RBAC: check debate creation permission
        user_id = user.get("name", "").split("/")[-1]
        try:
            self._check_bot_permission("debates:create", user_id=f"gchat:{user_id}")
        except PermissionError as exc:
            logger.warning("RBAC denied debates:create for gchat:%s: %s", user_id, exc)
            return self._card_response(body="Permission denied: you cannot start debates.")

        if not topic.strip():
            return self._card_response(
                body="Please provide a topic.\n\nExample: /debate Should AI be regulated?"
            )

        topic = topic.strip().strip("\"'")

        if len(topic) < 10:
            return self._card_response(body="Topic is too short. Please provide more detail.")

        if len(topic) > MAX_TOPIC_LENGTH:
            return self._card_response(
                body=f"Topic is too long. Please limit to {MAX_TOPIC_LENGTH} characters."
            )

        user_name = user.get("displayName", "Unknown")
        user_id = user.get("name", "").split("/")[-1]

        attachments = self._extract_attachments(event)

        # Queue debate asynchronously
        create_tracked_task(
            self._run_debate_async(
                topic,
                space_name,
                user_id,
                attachments,
                decision_integrity=decision_integrity,
            ),
            name=f"gchat-debate-{topic[:30]}",
        )

        return self._card_response(
            title="Starting Debate",
            body=f"*Topic:* {topic}\n\n_Processing... I'll post the result when complete._",
            context=f"Requested by {user_name}",
        )

    def _cmd_gauntlet(
        self,
        statement: str,
        space_name: str,
        user: dict[str, Any],
        event: dict[str, Any],
    ) -> HandlerResult:
        """Run gauntlet validation."""
        # RBAC: check gauntlet permission
        user_id = user.get("name", "").split("/")[-1]
        try:
            self._check_bot_permission("gauntlet:run", user_id=f"gchat:{user_id}")
        except PermissionError as exc:
            logger.warning("RBAC denied gauntlet:run for gchat:%s: %s", user_id, exc)
            return self._card_response(body="Permission denied: you cannot run gauntlet.")

        if not statement.strip():
            return self._card_response(
                body="Please provide a statement to stress-test.\n\n"
                "Example: /gauntlet We should migrate to microservices"
            )

        statement = statement.strip().strip("\"'")

        if len(statement) < 10:
            return self._card_response(body="Statement is too short. Please provide more detail.")

        if len(statement) > MAX_STATEMENT_LENGTH:
            return self._card_response(
                body=f"Statement is too long. Please limit to {MAX_STATEMENT_LENGTH} characters."
            )

        user_name = user.get("displayName", "Unknown")
        user_id = user.get("name", "").split("/")[-1]

        # Queue gauntlet asynchronously
        create_tracked_task(
            self._run_gauntlet_async(statement, space_name, user_id),
            name=f"gchat-gauntlet-{statement[:30]}",
        )

        return self._card_response(
            title="Running Gauntlet Stress-Test",
            body=f"*Statement:* {statement[:200]}{'...' if len(statement) > 200 else ''}\n\n"
            "_Running adversarial validation..._",
            context=f"Requested by {user_name}",
        )

    def _start_debate_from_message(
        self,
        text: str,
        space_name: str,
        user: dict[str, Any],
        event: dict[str, Any],
    ) -> HandlerResult:
        """Start a debate from a regular message or @mention."""
        # Clean up the text (remove @mentions)
        import re

        clean_text = re.sub(r"<users/[^>]+>", "", text).strip()

        if not clean_text or len(clean_text) < 10:
            return self._card_response(
                body="I need more context. Try asking a specific question or use /debate <topic>."
            )
        decision_integrity = None
        topic = clean_text
        parts = clean_text.split(maxsplit=1)
        if parts:
            command = parts[0].lower()
            remainder = parts[1] if len(parts) > 1 else ""
            if command in ("plan", "implement") and remainder:
                decision_integrity = {
                    "include_receipt": True,
                    "include_plan": True,
                    "include_context": command == "implement",
                    "plan_strategy": "single_task",
                    "notify_origin": True,
                }
                if command == "implement":
                    decision_integrity["execution_mode"] = "execute"
                    decision_integrity["execution_engine"] = "hybrid"
                topic = remainder
            elif command in ("debate", "ask") and remainder:
                topic = remainder

        return self._cmd_debate(topic, space_name, user, event, decision_integrity)

    # ==========================================================================
    # Async Operations
    # ==========================================================================

    async def _run_debate_async(
        self,
        topic: str,
        space_name: str,
        user_id: str,
        attachments: list[dict[str, Any]] | None = None,
        decision_integrity: dict[str, Any] | bool | None = None,
    ) -> None:
        """Run debate asynchronously via DecisionRouter and post result.

        Uses the unified DecisionRouter for:
        - Deduplication across channels
        - Response caching
        - RBAC enforcement
        - Consistent routing

        Falls back to direct Arena execution if DecisionRouter unavailable.
        """
        connector = get_google_chat_connector()
        if not connector:
            logger.warning("No Google Chat connector available")
            return

        # Try DecisionRouter first (preferred)
        try:
            from aragora.core.decision import (
                DecisionConfig,
                DecisionRequest,
                DecisionType,
                InputSource,
                ResponseChannel,
                RequestContext,
                get_decision_router,
            )
            from aragora.server.debate_origin import register_debate_origin
            import uuid

            debate_id = str(uuid.uuid4())

            # Register origin for result routing
            register_debate_origin(
                debate_id=debate_id,
                platform="google_chat",
                channel_id=space_name,
                user_id=user_id,
                metadata={"topic": topic},
            )

            config = None
            if decision_integrity is not None:
                if isinstance(decision_integrity, bool):
                    decision_integrity = {} if decision_integrity else None
                if isinstance(decision_integrity, dict):
                    config = DecisionConfig(decision_integrity=decision_integrity)

            request_kwargs = {
                "content": topic,
                "decision_type": DecisionType.DEBATE,
                "source": InputSource.GOOGLE_CHAT,
                "response_channels": [
                    ResponseChannel(
                        platform="google_chat",
                        channel_id=space_name,
                        user_id=user_id,
                    )
                ],
                "context": RequestContext(
                    user_id=f"gchat:{user_id}",
                    metadata={"space_name": space_name},
                ),
                "attachments": attachments or [],
            }
            if config is not None:
                request_kwargs["config"] = config

            request = DecisionRequest(**request_kwargs)  # type: ignore[arg-type]

            router = get_decision_router()
            result = await router.route(request)
            if result and result.success:
                logger.info(
                    "DecisionRouter completed debate for Google Chat: %s", result.request_id
                )
                return  # Response handler will post the result
            else:
                logger.warning("DecisionRouter returned unsuccessful result, falling back")

        except ImportError:
            logger.debug("DecisionRouter not available, falling back to direct execution")
        except (RuntimeError, ValueError, KeyError, AttributeError) as e:
            logger.error("DecisionRouter failed: %s, falling back to direct execution", e)

        # Fallback to direct Arena execution
        try:
            from aragora import Arena, DebateProtocol, Environment
            from aragora.agents import get_agents_by_names

            env = Environment(task=f"Debate: {topic}")
            default_agents = [a.strip() for a in DEFAULT_AGENTS.split(",") if a.strip()]
            agents = get_agents_by_names(default_agents)
            protocol = DebateProtocol(
                rounds=DEFAULT_ROUNDS,
                consensus=DEFAULT_CONSENSUS,
                convergence_detection=False,
                early_stopping=False,
            )

            if not agents:
                await connector.send_message(
                    space_name,
                    "Failed to start debate: No agents available",
                )
                return

            arena = Arena.from_env(env, agents, protocol)
            result = await arena.run()

            # Build result card
            consensus_emoji = "✅" if result.consensus_reached else "❌"
            confidence_bar = "█" * int(result.confidence * 5) + "░" * (
                5 - int(result.confidence * 5)
            )

            sections = (
                connector.format_blocks(
                    title=f"{consensus_emoji} Debate Complete",
                    body=f"*Topic:* {topic[:100]}...\n\n"
                    f"*Conclusion:*\n{result.final_answer[:400] if result.final_answer else 'No conclusion'}...",
                    fields=[
                        ("Consensus", "Yes" if result.consensus_reached else "No"),
                        ("Confidence", f"{confidence_bar} {result.confidence:.0%}"),
                        ("Rounds", str(result.rounds_used)),
                        ("Agents", str(len(agents))),
                    ],
                    actions=[
                        connector.connectors.chat.models.MessageButton(
                            text="👍 Agree",
                            action_id="vote_agree",
                            value=result.id,
                        ),
                        connector.connectors.chat.models.MessageButton(
                            text="👎 Disagree",
                            action_id="vote_disagree",
                            value=result.id,
                        ),
                    ],
                )
                if hasattr(connector, "format_blocks")
                else []
            )

            await connector.send_message(
                space_name,
                f"Debate complete: {topic[:50]}...",
                blocks=sections,
            )

        except (RuntimeError, ImportError, ValueError, AttributeError, OSError) as e:
            logger.error("Async debate failed: %s", e, exc_info=True)
            if connector:
                await connector.send_message(
                    space_name,
                    "Sorry, an error occurred while processing your debate request.",
                )

    async def _run_gauntlet_async(
        self,
        statement: str,
        space_name: str,
        user_id: str,
    ) -> None:
        """Run gauntlet asynchronously and post result."""
        from aragora.server.http_client_pool import get_http_pool

        connector = get_google_chat_connector()
        if not connector:
            logger.warning("No Google Chat connector available")
            return

        try:
            pool = get_http_pool()
            async with pool.get_session("google_chat_gauntlet") as client:
                resp = await client.post(
                    "http://localhost:8080/api/v1/gauntlet/run",
                    json={
                        "statement": statement,
                        "intensity": "medium",
                        "metadata": {
                            "source": "google_chat",
                            "space_name": space_name,
                            "user_id": user_id,
                        },
                    },
                    timeout=120,
                )
                data = resp.json()

                if resp.status_code != 200:
                    await connector.send_message(
                        space_name,
                        f"Gauntlet failed: {data.get('error', 'Unknown error')}",
                    )
                    return

                score = data.get("score", 0)
                passed = data.get("passed", False)
                vulnerabilities = data.get("vulnerabilities", [])

                status_emoji = "✅" if passed else "❌"
                score_bar = "█" * int(score * 5) + "░" * (5 - int(score * 5))

                body = f"*Statement:* {statement[:200]}{'...' if len(statement) > 200 else ''}\n\n"
                body += f"*Score:* {score_bar} {score:.0%}\n"
                body += f"*Status:* {'Passed' if passed else 'Failed'}\n"
                body += f"*Issues Found:* {len(vulnerabilities)}\n"

                if vulnerabilities:
                    body += "\n*Issues:*\n"
                    for v in vulnerabilities[:3]:
                        body += f"• {v.get('description', 'Unknown')[:80]}\n"
                    if len(vulnerabilities) > 3:
                        body += f"_...and {len(vulnerabilities) - 3} more_"

                await connector.send_message(
                    space_name,
                    "Gauntlet complete",
                    blocks=(
                        connector.format_blocks(
                            title=f"{status_emoji} Gauntlet Results",
                            body=body,
                        )
                        if hasattr(connector, "format_blocks")
                        else None
                    ),
                )

        except (RuntimeError, ImportError, ValueError, AttributeError, OSError) as e:
            logger.error("Async gauntlet failed: %s", e, exc_info=True)
            if connector:
                await connector.send_message(
                    space_name,
                    "Sorry, an error occurred while running the gauntlet stress-test.",
                )

    # ==========================================================================
    # Response Helpers
    # ==========================================================================

    def _card_response(
        self,
        title: str | None = None,
        body: str | None = None,
        fields: list[tuple[str, str]] | None = None,
        context: str | None = None,
        actions: list[dict] | None = None,
    ) -> HandlerResult:
        """Create a Google Chat Card v2 response."""
        sections: list[dict] = []

        # Header
        if title:
            sections.append({"header": title})

        # Body text
        if body:
            sections.append({"widgets": [{"textParagraph": {"text": body}}]})

        # Fields as decorated text
        if fields:
            widgets = []
            for label, value in fields:
                widgets.append(
                    {
                        "decoratedText": {
                            "topLabel": label,
                            "text": value,
                        }
                    }
                )
            sections.append({"widgets": widgets})

        # Context footer
        if context:
            sections.append({"widgets": [{"textParagraph": {"text": f"<i>{context}</i>"}}]})

        # Action buttons
        if actions:
            sections.append({"widgets": [{"buttonList": {"buttons": actions}}]})

        # Build card response
        response: dict[str, Any] = {}

        if sections:
            response["cardsV2"] = [
                {
                    "cardId": "aragora_response",
                    "card": {"sections": sections},
                }
            ]
        elif body:
            response["text"] = body

        return json_response(response)


# Export handler factory
_google_chat_handler: GoogleChatHandler | None = None


def get_google_chat_handler(server_context: dict[str, Any] | None = None) -> GoogleChatHandler:
    """Get or create the Google Chat handler instance."""
    global _google_chat_handler
    if _google_chat_handler is None:
        if server_context is None:
            server_context = {}
        _google_chat_handler = GoogleChatHandler(server_context)
    return _google_chat_handler


__all__ = [
    "GoogleChatHandler",
    "get_google_chat_handler",
    "get_google_chat_connector",
    # Token verification (public for testing)
    "_verify_google_chat_token",
    "clear_token_cache",
    "_get_cached_result",
    "_set_cached_result",
    "_token_cache",
    "_token_cache_lock",
    "_token_cache_key",
    "_TOKEN_CACHE_VALID_TTL",
    "_TOKEN_CACHE_INVALID_TTL",
    "_verify_token_via_jwt_verifier",
    "_verify_token_via_google_auth",
    "_verify_token_via_tokeninfo",
]
