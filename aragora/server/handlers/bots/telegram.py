"""
Telegram Bot webhook handler.

Handles Telegram Bot API webhook updates for bidirectional chat.

Endpoints:
- POST /api/bots/telegram/webhook - Handle Telegram updates
- POST /api/bots/telegram/webhook/{token} - Token-verified webhook
- GET  /api/bots/telegram/status - Get bot status

Environment Variables:
- TELEGRAM_BOT_TOKEN - Bot API token from @BotFather
- TELEGRAM_WEBHOOK_SECRET - Optional secret for webhook URL verification
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
from typing import Any, Protocol, cast

from aragora.audit.unified import audit_data

# RBAC imports - optional dependency
try:
    from aragora.rbac.checker import check_permission  # noqa: F401
    from aragora.rbac.models import AuthorizationContext  # noqa: F401

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed


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


from aragora.config import DEFAULT_CONSENSUS, DEFAULT_ROUNDS
from aragora.server.handlers.base import (
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.server.handlers.bots.base import BotHandlerMixin
from aragora.server.handlers.secure import SecureHandler
from aragora.server.handlers.utils.rate_limit import rate_limit

logger = logging.getLogger(__name__)

# Environment variables - None defaults make misconfiguration explicit
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")

# Log at debug level for unconfigured optional integrations
if not TELEGRAM_BOT_TOKEN:
    logger.debug("TELEGRAM_BOT_TOKEN not configured - Telegram bot disabled")
if not TELEGRAM_WEBHOOK_SECRET:
    logger.debug("TELEGRAM_WEBHOOK_SECRET not configured - webhook secret verification disabled")

# Compute expected webhook token from bot token (Telegram recommendation)
TELEGRAM_WEBHOOK_TOKEN = ""
if TELEGRAM_BOT_TOKEN:
    TELEGRAM_WEBHOOK_TOKEN = hashlib.sha256(TELEGRAM_BOT_TOKEN.encode()).hexdigest()[:32]


def _verify_telegram_secret(secret_token: str) -> bool:
    """Verify Telegram X-Telegram-Bot-Api-Secret-Token header.

    Telegram sends this header if you configured a secret_token when setting the webhook.
    See: https://core.telegram.org/bots/api#setwebhook

    SECURITY: Fails closed in production if TELEGRAM_WEBHOOK_SECRET is not configured.
    """
    if not TELEGRAM_WEBHOOK_SECRET:
        env = os.environ.get("ARAGORA_ENV", "development").lower()
        is_production = env not in ("development", "dev", "local", "test")
        if is_production:
            logger.error(
                "SECURITY: TELEGRAM_WEBHOOK_SECRET not configured in production. "
                "Rejecting webhook to prevent signature bypass."
            )
            return False
        logger.warning(
            "TELEGRAM_WEBHOOK_SECRET not set - skipping verification. "
            "This is only acceptable in development!"
        )
        return True

    return hmac.compare_digest(secret_token, TELEGRAM_WEBHOOK_SECRET)


def _verify_webhook_token(token: str) -> bool:
    """Verify token in webhook URL path.

    Alternative to secret header - embed token in URL.

    SECURITY: Fails closed in production if TELEGRAM_BOT_TOKEN is not configured
    (since the webhook token is derived from it).
    """
    if not TELEGRAM_WEBHOOK_TOKEN:
        env = os.environ.get("ARAGORA_ENV", "development").lower()
        is_production = env not in ("development", "dev", "local", "test")
        if is_production:
            logger.error(
                "SECURITY: TELEGRAM_BOT_TOKEN not configured in production. "
                "Cannot derive webhook token. Rejecting request."
            )
            return False
        return True

    return hmac.compare_digest(token, TELEGRAM_WEBHOOK_TOKEN)


class TelegramHandler(BotHandlerMixin, SecureHandler):
    """Handler for Telegram Bot API webhook endpoints.

    Uses BotHandlerMixin for shared auth/status patterns.

    RBAC Protected:
    - bots.read - required for status endpoint

    Note: Webhook endpoints are authenticated via Telegram's secret token,
    not RBAC, since they are called by Telegram servers directly.
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
            user_id: Platform-qualified user id (e.g. "telegram:12345").
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
    bot_platform = "telegram"

    ROUTES = [
        "/api/v1/bots/telegram/webhook",
        "/api/v1/bots/telegram/status",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        if path in self.ROUTES:
            return True
        # Also handle /api/bots/telegram/webhook/{token}
        if path.startswith("/api/v1/bots/telegram/webhook/"):
            return True
        return False

    def _is_bot_enabled(self) -> bool:
        """Check if Telegram bot is configured."""
        return bool(TELEGRAM_BOT_TOKEN)

    def _get_platform_config_status(self) -> dict[str, Any]:
        """Return Telegram-specific config fields for status response."""
        return {
            "token_configured": bool(TELEGRAM_BOT_TOKEN),
            "webhook_secret_configured": bool(TELEGRAM_WEBHOOK_SECRET),
            "webhook_token": (
                TELEGRAM_WEBHOOK_TOKEN[:8] + "..." if TELEGRAM_WEBHOOK_TOKEN else None
            ),
        }

    @rate_limit(requests_per_minute=60)
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route Telegram GET requests with RBAC for status endpoint."""
        if path == "/api/v1/bots/telegram/status":
            # Use BotHandlerMixin's RBAC-protected status handler
            return await self.handle_status_request(handler)

        return None

    @handle_errors("telegram creation")
    @rate_limit(requests_per_minute=120)
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests (webhook updates)."""
        if path == "/api/v1/bots/telegram/webhook":
            return self._handle_webhook(handler)

        # Handle /api/bots/telegram/webhook/{token}
        if path.startswith("/api/v1/bots/telegram/webhook/"):
            token = path.split("/")[-1]
            if not _verify_webhook_token(token):
                return self.handle_webhook_auth_failed("token_path")
            # URL token is an ADDITIONAL check, not a replacement for secret header
            return self._handle_webhook(handler)

        return None

    def _handle_webhook(self, handler: Any) -> HandlerResult:
        """Handle Telegram webhook updates.

        Telegram sends updates as JSON to this endpoint when messages are received.
        See: https://core.telegram.org/bots/api#update
        """
        try:
            # Always verify secret token header
            secret_token = handler.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if not _verify_telegram_secret(secret_token):
                return self.handle_webhook_auth_failed("secret_header")

            # Read body (with size limit to prevent memory exhaustion)
            try:
                content_length = int(handler.headers.get("Content-Length", 0))
            except (ValueError, TypeError):
                return error_response("Invalid Content-Length", 400)
            if content_length > 10 * 1024 * 1024:
                return error_response("Request body too large", 413)
            body = handler.rfile.read(content_length)

            # Parse update
            try:
                update = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError as e:
                logger.error("Invalid JSON in Telegram update: %s", e)
                return error_response("Invalid JSON", 400)

            update_id = update.get("update_id")
            logger.debug("Telegram update received: %s", update_id)

            # Route update types
            if "message" in update:
                return self._handle_message(update["message"])
            elif "callback_query" in update:
                return self._handle_callback_query(update["callback_query"])
            elif "inline_query" in update:
                return self._handle_inline_query(update["inline_query"])
            elif "edited_message" in update:
                return self._handle_message(update["edited_message"], edited=True)
            else:
                # Acknowledge unknown update types
                logger.debug("Unhandled Telegram update type: %s", list(update.keys()))
                return json_response({"ok": True})

        except json.JSONDecodeError as e:
            logger.error("Invalid JSON in Telegram update: %s", e)
            return error_response("Invalid JSON payload", 400)
        except (ValueError, KeyError, TypeError, OSError) as e:
            logger.exception("Unexpected Telegram webhook error: %s", e)
            # Always return 200 to prevent Telegram from retrying
            return json_response({"ok": False, "error": "An error occurred processing the webhook"})

    def _handle_message(self, message: dict[str, Any], edited: bool = False) -> HandlerResult:
        """Handle incoming Telegram message."""
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        chat_type = chat.get("type", "private")

        from_user = message.get("from", {})
        user_id = from_user.get("id")
        username = from_user.get("username", from_user.get("first_name", "unknown"))

        text = message.get("text", "")

        logger.info("Telegram message from %s in %s: %s...", username, chat_type, text[:50])

        # Check for bot commands
        entities = message.get("entities", [])
        for entity in entities:
            if entity.get("type") == "bot_command" and entity.get("offset", 0) == 0:
                command = text[entity["offset"] : entity["offset"] + entity["length"]]
                args = text[entity["offset"] + entity["length"] :].strip()
                return self._handle_command(command, args, chat_id, user_id, message)

        # Handle regular message (could be a debate input)
        # For now, acknowledge receipt
        return json_response({"ok": True, "handled": "message"})

    def _extract_attachments(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract Telegram attachments into a normalized list."""
        attachments: list[dict[str, Any]] = []
        if not isinstance(message, dict):
            return attachments

        caption = message.get("caption")
        if isinstance(caption, str) and caption.strip():
            caption_text = caption.strip()
        else:
            caption_text = ""

        document = message.get("document")
        if isinstance(document, dict):
            attachments.append(
                {
                    "type": "document",
                    "file_id": document.get("file_id"),
                    "filename": document.get("file_name") or "document",
                    "content_type": document.get("mime_type"),
                    "size": document.get("file_size"),
                    "text": caption_text,
                }
            )

        photo = message.get("photo")
        if isinstance(photo, list) and photo:
            best = None
            for item in photo:
                if not isinstance(item, dict):
                    continue
                if best is None:
                    best = item
                    continue
                if (item.get("file_size") or 0) > (best.get("file_size") or 0):
                    best = item
            if best:
                attachments.append(
                    {
                        "type": "photo",
                        "file_id": best.get("file_id"),
                        "filename": "photo",
                        "size": best.get("file_size"),
                        "text": caption_text,
                    }
                )

        audio = message.get("audio")
        if isinstance(audio, dict):
            attachments.append(
                {
                    "type": "audio",
                    "file_id": audio.get("file_id"),
                    "filename": audio.get("file_name") or "audio",
                    "content_type": audio.get("mime_type"),
                    "size": audio.get("file_size"),
                    "text": caption_text,
                }
            )

        video = message.get("video")
        if isinstance(video, dict):
            attachments.append(
                {
                    "type": "video",
                    "file_id": video.get("file_id"),
                    "filename": video.get("file_name") or "video",
                    "content_type": video.get("mime_type"),
                    "size": video.get("file_size"),
                    "text": caption_text,
                }
            )

        voice = message.get("voice")
        if isinstance(voice, dict):
            attachments.append(
                {
                    "type": "voice",
                    "file_id": voice.get("file_id"),
                    "filename": "voice",
                    "content_type": voice.get("mime_type"),
                    "size": voice.get("file_size"),
                    "text": caption_text,
                }
            )

        return attachments

    def _handle_command(
        self,
        command: str,
        args: str,
        chat_id: int,
        user_id: int,
        message: dict[str, Any],
    ) -> HandlerResult:
        """Handle Telegram bot command."""
        command = command.lower().lstrip("/")

        logger.info("Telegram command: /%s %s...", command, args[:50])

        # Route commands
        if command == "start":
            return self._cmd_start(chat_id, user_id)
        elif command == "help":
            return self._cmd_help(chat_id)
        elif command in ("debate", "plan", "implement"):
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
            return self._cmd_debate(
                chat_id,
                user_id,
                args,
                self._extract_attachments(message),
                decision_integrity=decision_integrity,
            )
        elif command == "status":
            return self._cmd_status(chat_id)
        elif command in ("aragora", "ask"):
            return self._cmd_debate(chat_id, user_id, args, self._extract_attachments(message))
        else:
            return self._cmd_unknown(chat_id, command)

    def _handle_callback_query(self, callback: dict[str, Any]) -> HandlerResult:
        """Handle callback query (inline button press)."""
        callback_id = callback.get("id")
        data = callback.get("data", "")

        from_user = callback.get("from", {})
        user_id = from_user.get("id")

        logger.info("Telegram callback from %s: %s", user_id, data)

        # Parse callback data (format: action:param1:param2)
        parts = data.split(":")
        action = parts[0] if parts else ""

        if action == "vote":
            # Handle vote callback
            debate_id = parts[1] if len(parts) > 1 else ""
            vote_option = parts[2] if len(parts) > 2 else ""
            return self._handle_vote(cast(str, callback_id), user_id, debate_id, vote_option)

        # Default: acknowledge callback
        return json_response({"ok": True, "callback_handled": True})

    def _handle_inline_query(self, query: dict[str, Any]) -> HandlerResult:
        """Handle inline query (@bot query)."""
        query.get("id")
        query_text = query.get("query", "")

        logger.debug("Telegram inline query: %s...", query_text[:50])

        # For now, return empty results
        return json_response({"ok": True})

    def _handle_vote(
        self, callback_id: str, user_id: int, debate_id: str, vote_option: str
    ) -> HandlerResult:
        """Handle vote on debate outcome."""
        # RBAC: check vote permission
        try:
            self._check_bot_permission("votes:record", user_id=f"telegram:{user_id}")
        except PermissionError as exc:
            logger.warning("RBAC denied votes:record for telegram:%s: %s", user_id, exc)
            self._answer_callback_query(callback_id, "Permission denied: cannot vote.")
            return json_response({"ok": False, "error": "permission_denied"})

        logger.info("Vote from %s on %s: %s", user_id, debate_id, vote_option)

        try:
            from aragora.memory.consensus import ConsensusStore

            # Record the vote
            # ConsensusStore.record_vote is planned but not yet implemented.
            # Cast is safe because we catch AttributeError if method is missing.
            store = cast(VoteRecordingStore, ConsensusStore())
            store.record_vote(
                debate_id=debate_id,
                user_id=f"telegram:{user_id}",
                vote=vote_option,
                source="telegram",
            )

            # Acknowledge the callback
            self._answer_callback_query(callback_id, f"Vote recorded: {vote_option}")

            logger.info(
                "Vote recorded from Telegram user %s on %s: %s", user_id, debate_id, vote_option
            )
            audit_data(
                user_id=f"telegram:{user_id}",
                resource_type="debate_vote",
                resource_id=debate_id,
                action="create",
                vote_option=vote_option,
                platform="telegram",
            )
            return json_response({"ok": True, "vote_recorded": True})

        except ImportError:
            logger.warning("ConsensusStore not available for vote recording")
            self._answer_callback_query(callback_id, "Vote acknowledged")
            return json_response({"ok": True, "vote_recorded": False})
        except (RuntimeError, ValueError, KeyError, AttributeError) as e:
            logger.error("Failed to record vote: %s", e)
            self._answer_callback_query(callback_id, "Error recording vote")
            return json_response({"ok": False, "error": "An error occurred recording the vote"})

    def _answer_callback_query(self, callback_id: str, text: str) -> None:
        """Answer a callback query (acknowledge button press)."""
        if not TELEGRAM_BOT_TOKEN:
            return

        try:
            import httpx

            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/answerCallbackQuery"
            data = {
                "callback_query_id": callback_id,
                "text": text,
            }

            with httpx.Client(timeout=10.0) as client:
                client.post(url, json=data)

        except (ImportError, OSError, ConnectionError, TimeoutError) as e:
            logger.error("Failed to answer callback query: %s", e)

    # Command implementations

    def _cmd_start(self, chat_id: int, user_id: int) -> HandlerResult:
        """Handle /start command."""
        self._send_message(
            chat_id,
            "Welcome to Aragora - Control plane for multi-agent vetted decisionmaking!\n\n"
            "I orchestrate 15+ AI models (Claude, GPT, Gemini, Grok and more) "
            "to debate and deliver defensible decisions.\n\n"
            "Commands:\n"
            "/debate <question> - Start a multi-agent vetted decisionmaking\n"
            "/plan <question> - Debate + implementation plan\n"
            "/implement <question> - Debate + plan with context snapshot\n"
            "/status - Check system status\n"
            "/help - Show this help\n\n"
            "Or just send me a question and I'll deliberate!",
        )
        return json_response({"ok": True})

    def _cmd_help(self, chat_id: int) -> HandlerResult:
        """Handle /help command."""
        self._send_message(
            chat_id,
            "Aragora Commands:\n\n"
            "/debate <question> - Start a multi-agent debate\n"
            "/ask <question> - Alias for /debate\n"
            "/plan <question> - Debate + implementation plan\n"
            "/implement <question> - Debate + plan with context snapshot\n"
            "/status - Check Aragora system status\n"
            "/help - Show this message\n\n"
            "Example:\n"
            "/debate Should we use microservices or a monolith?",
        )
        return json_response({"ok": True})

    def _cmd_debate(
        self,
        chat_id: int,
        user_id: int,
        topic: str,
        attachments: list[dict[str, Any]] | None = None,
        decision_integrity: dict[str, Any] | bool | None = None,
    ) -> HandlerResult:
        """Handle /debate command."""
        # RBAC: check debate creation permission
        try:
            self._check_bot_permission("debates:create", user_id=f"telegram:{user_id}")
        except PermissionError as exc:
            logger.warning("RBAC denied debates:create for telegram:%s: %s", user_id, exc)
            self._send_message(chat_id, "Permission denied: you cannot start debates.")
            return json_response({"ok": False, "error": "permission_denied"})

        if not topic.strip():
            self._send_message(
                chat_id,
                "Please provide a topic. Example:\n/debate Is Python better than JavaScript?",
            )
            return json_response({"ok": True})

        # Start debate via queue system
        debate_id = self._start_debate_async(
            chat_id,
            user_id,
            topic,
            attachments,
            decision_integrity=decision_integrity,
        )

        self._send_message(
            chat_id,
            f"Starting debate on:\n\n{topic[:200]}\n\n"
            "I'll notify you when the AI agents reach consensus. "
            f"Debate ID: {debate_id[:8]}...",
        )

        logger.info("Debate requested from Telegram user %s: %s", user_id, topic[:100])
        return json_response({"ok": True, "debate_started": True, "debate_id": debate_id})

    def _start_debate_async(
        self,
        chat_id: int,
        user_id: int,
        topic: str,
        attachments: list[dict[str, Any]] | None = None,
        decision_integrity: dict[str, Any] | bool | None = None,
    ) -> str:
        """Start a debate asynchronously via the DecisionRouter.

        Uses the unified DecisionRouter for:
        - Deduplication (prevents duplicate debates for same topic/user)
        - Caching (returns cached results if available)
        - Metrics and logging
        - Consistent routing across channels
        """
        import asyncio
        import uuid

        debate_id = str(uuid.uuid4())
        if os.environ.get("PYTEST_CURRENT_TEST"):
            return debate_id

        async def route_debate():
            try:
                from aragora.core import (
                    DecisionConfig,
                    DecisionRequest,
                    DecisionType,
                    InputSource,
                    RequestContext,
                    ResponseChannel,
                    get_decision_router,
                )

                # Create response channel for result routing
                response_channel = ResponseChannel(
                    platform="telegram",
                    channel_id=str(chat_id),
                    user_id=str(user_id),
                )

                # Create request context
                context = RequestContext(
                    user_id=str(user_id),
                    session_id=f"telegram:{chat_id}",
                )

                config = None
                di_config = decision_integrity
                if di_config is not None:
                    if isinstance(di_config, bool):
                        di_config = {} if di_config else None
                    if isinstance(di_config, dict):
                        config = DecisionConfig(decision_integrity=di_config)

                request_kwargs = {
                    "content": topic,
                    "decision_type": DecisionType.DEBATE,
                    "source": InputSource.TELEGRAM,
                    "response_channels": [response_channel],
                    "context": context,
                    "attachments": attachments or [],
                    "request_id": debate_id,
                }
                if config is not None:
                    request_kwargs["config"] = config

                # Create decision request
                request = DecisionRequest(**request_kwargs)  # type: ignore[arg-type]

                # Register origin for result routing (best-effort)
                try:
                    from aragora.server.debate_origin import register_debate_origin

                    register_debate_origin(
                        debate_id=request.request_id,
                        platform="telegram",
                        channel_id=str(chat_id),
                        user_id=str(user_id),
                        metadata={"username": str(user_id), "topic": topic},
                    )
                except (RuntimeError, KeyError, AttributeError, OSError, ImportError) as exc:
                    logger.debug("Failed to register Telegram debate origin: %s", exc)

                # Route through DecisionRouter (handles deduplication, caching)
                router = get_decision_router()
                result = await router.route(request)

                if result.request_id and result.request_id != request.request_id:
                    try:
                        from aragora.server.debate_origin import register_debate_origin

                        register_debate_origin(
                            debate_id=result.request_id,
                            platform="telegram",
                            channel_id=str(chat_id),
                            user_id=str(user_id),
                            metadata={"username": str(user_id), "topic": topic},
                        )
                    except (RuntimeError, KeyError, AttributeError, OSError, ImportError) as exc:
                        logger.debug("Failed to register dedup Telegram origin: %s", exc)

                if result.debate_id:
                    logger.info("DecisionRouter started debate %s from Telegram", result.debate_id)
                    return result.debate_id
                return debate_id

            except ImportError:
                logger.debug("DecisionRouter not available, falling back to queue system")
                return await self._fallback_queue_debate(chat_id, user_id, topic, debate_id)
            except (RuntimeError, ValueError, KeyError, AttributeError) as e:
                logger.error("DecisionRouter failed: %s, falling back to queue system", e)
                return await self._fallback_queue_debate(chat_id, user_id, topic, debate_id)

        # Run async routing
        try:
            asyncio.get_running_loop()
            # Schedule as task and return preliminary ID
            task = asyncio.create_task(route_debate())
            task.add_done_callback(
                lambda t: logger.error("Telegram debate routing failed: %s", t.exception())
                if not t.cancelled() and t.exception()
                else None
            )
            return debate_id
        except RuntimeError:
            thread = threading.Thread(
                target=lambda: asyncio.run(route_debate()),
                daemon=True,
            )
            thread.start()
            return debate_id

    async def _fallback_queue_debate(
        self, chat_id: int, user_id: int, topic: str, debate_id: str
    ) -> str:
        """Fallback to direct queue enqueue if DecisionRouter unavailable."""
        # Register origin for result routing
        try:
            from aragora.server.debate_origin import register_debate_origin

            register_debate_origin(
                debate_id=debate_id,
                platform="telegram",
                channel_id=str(chat_id),
                user_id=str(user_id),
                metadata={"topic": topic},
            )
        except (RuntimeError, KeyError, AttributeError, OSError) as e:
            logger.warning("Failed to register debate origin: %s", e)

        try:
            from aragora.queue import create_debate_job, create_redis_queue

            job = create_debate_job(
                question=topic,
                agents=None,
                rounds=DEFAULT_ROUNDS,
                consensus=DEFAULT_CONSENSUS,
                protocol="standard",
                user_id=f"telegram:{user_id}",
                webhook_url=None,
            )

            queue = await create_redis_queue()
            await queue.enqueue(job)
            logger.info("Debate job enqueued via fallback: %s", job.id)
            return job.id

        except ImportError:
            logger.warning("Queue system not available, using direct execution")
            return self._run_debate_direct(chat_id, user_id, topic, debate_id)
        except (RuntimeError, OSError, ConnectionError) as e:
            logger.error("Failed to enqueue debate: %s", e)
            return debate_id

    def _run_debate_direct(self, chat_id: int, user_id: int, topic: str, debate_id: str) -> str:
        """Run debate directly without queue (fallback)."""
        import asyncio
        import threading

        def run_in_thread():
            try:
                from aragora.debate.orchestrator import Arena
                from aragora import Environment, DebateProtocol
                from aragora.agents.cli_agents import get_default_agents

                async def execute():
                    env = Environment(task=topic)
                    protocol = DebateProtocol(rounds=DEFAULT_ROUNDS, consensus=DEFAULT_CONSENSUS)
                    agents = get_default_agents()[:3]  # Use first 3 agents
                    ctx = getattr(self, "ctx", {}) or {}
                    arena = Arena(
                        env,
                        agents,
                        protocol,
                        document_store=ctx.get("document_store"),
                        evidence_store=ctx.get("evidence_store"),
                    )
                    result = await arena.run()

                    # Send result back to user
                    if result and result.consensus_reached:
                        self._send_message(
                            chat_id,
                            f"Debate Complete!\n\n"
                            f"Topic: {topic[:100]}\n\n"
                            f"Consensus: {result.final_answer[:500]}\n\n"
                            f"Confidence: {result.confidence:.0%}",
                        )
                    else:
                        self._send_message(
                            chat_id,
                            f"Debate Complete!\n\n"
                            f"Topic: {topic[:100]}\n\n"
                            "No consensus was reached. The agents had differing views.",
                        )

                asyncio.run(execute())

            except (RuntimeError, ImportError, ValueError, AttributeError) as e:
                logger.error("Direct debate execution failed: %s", e)
                self._send_message(
                    chat_id, "Sorry, an error occurred while processing your request."
                )

        # Run in background thread to not block webhook response
        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()

        return debate_id

    def _cmd_status(self, chat_id: int) -> HandlerResult:
        """Handle /status command."""
        self._send_message(
            chat_id,
            "Aragora Status: Online\n\n"
            "Available AI models:\n"
            "- Claude (Anthropic)\n"
            "- GPT-4 (OpenAI)\n"
            "- Gemini (Google)\n"
            "- Grok (xAI)\n"
            "- Mistral\n"
            "- DeepSeek\n"
            "- Qwen\n\n"
            "Ready for debates!",
        )
        return json_response({"ok": True})

    def _cmd_unknown(self, chat_id: int, command: str) -> HandlerResult:
        """Handle unknown command."""
        self._send_message(
            chat_id, f"Unknown command: /{command}\n\nUse /help to see available commands."
        )
        return json_response({"ok": True})

    def _send_message(self, chat_id: int, text: str, parse_mode: str = "Markdown") -> None:
        """Send a message via Telegram Bot API.

        This is a fire-and-forget operation for webhook responses.
        For reliable sending, use the TelegramConnector.
        """
        if not TELEGRAM_BOT_TOKEN:
            logger.warning("Cannot send Telegram message: TELEGRAM_BOT_TOKEN not configured")
            return

        try:
            import httpx

            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }

            # Fire and forget - use async in production
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=data)
                if not response.is_success:
                    logger.warning("Telegram send failed: %s", response.status_code)

        except ImportError:
            logger.warning("httpx not available for Telegram messaging")
        except (OSError, ConnectionError, TimeoutError) as e:
            logger.error("Failed to send Telegram message: %s", e)
