"""
WhatsApp Business webhook handler.

Handles WhatsApp Cloud API webhooks for bidirectional chat.

Endpoints:
- GET  /api/bots/whatsapp/webhook - Webhook verification
- POST /api/bots/whatsapp/webhook - Handle incoming messages
- GET  /api/bots/whatsapp/status - Get integration status

Environment Variables:
- WHATSAPP_VERIFY_TOKEN - Token for webhook verification
- WHATSAPP_ACCESS_TOKEN - Cloud API access token
- WHATSAPP_PHONE_NUMBER_ID - Business phone number ID
"""

from __future__ import annotations

import asyncio
import hmac
import hashlib
import json
import logging
import os
from typing import Any

from aragora.config import DEFAULT_CONSENSUS, DEFAULT_ROUNDS
from aragora.exceptions import REDIS_CONNECTION_ERRORS
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
    from aragora.rbac.checker import check_permission
    from aragora.rbac.models import AuthorizationContext

    RBAC_AVAILABLE = True
except ImportError:
    RBAC_AVAILABLE = False

from aragora.server.handlers.utils.rbac_guard import rbac_fail_closed

logger = logging.getLogger(__name__)

# Environment variables - None defaults make misconfiguration explicit
WHATSAPP_VERIFY_TOKEN = os.environ.get("WHATSAPP_VERIFY_TOKEN")
WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET")

# Log at debug level for unconfigured optional integrations
if not WHATSAPP_VERIFY_TOKEN:
    logger.debug("WHATSAPP_VERIFY_TOKEN not configured - webhook verification disabled")
if not WHATSAPP_APP_SECRET:
    logger.debug("WHATSAPP_APP_SECRET not configured - signature verification disabled")

# WhatsApp Cloud API
WHATSAPP_API_URL = "https://graph.facebook.com/v18.0"


def _verify_whatsapp_signature(signature: str, body: bytes) -> bool:
    """Verify WhatsApp webhook signature.

    WhatsApp uses HMAC-SHA256 with the app secret.
    See: https://developers.facebook.com/docs/graph-api/webhooks/getting-started#verification-requests

    Security: Fails closed when app secret is not configured (rejects all requests).
    """
    if not WHATSAPP_APP_SECRET:
        logger.error(
            "WHATSAPP_APP_SECRET not configured - rejecting webhook request. "
            "Set WHATSAPP_APP_SECRET environment variable to enable webhook processing."
        )
        return False  # Fail closed - reject unverifiable requests

    if not signature.startswith("sha256="):
        return False

    expected_sig = signature[7:]  # Remove "sha256=" prefix

    computed_sig = hmac.new(WHATSAPP_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()

    return hmac.compare_digest(expected_sig, computed_sig)


class WhatsAppHandler(BotHandlerMixin, SecureHandler):
    """Handler for WhatsApp Cloud API webhook endpoints.

    Uses BotHandlerMixin for shared auth/status patterns.

    RBAC Protected:
    - bots.read - required for status endpoint

    Note: Webhook endpoints are authenticated via WhatsApp's signature,
    not RBAC, since they are called by Meta servers directly.
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
            user_id: Platform-qualified user id (e.g. "whatsapp:15551234567").
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
    bot_platform = "whatsapp"

    ROUTES = [
        "/api/v1/bots/whatsapp/webhook",
        "/api/v1/bots/whatsapp/status",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        return path in self.ROUTES

    def _is_bot_enabled(self) -> bool:
        """Check if WhatsApp bot is configured."""
        return bool(WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID)

    def _get_platform_config_status(self) -> dict[str, Any]:
        """Return WhatsApp-specific config fields for status response."""
        return {
            "access_token_configured": bool(WHATSAPP_ACCESS_TOKEN),
            "phone_number_configured": bool(WHATSAPP_PHONE_NUMBER_ID),
            "verify_token_configured": bool(WHATSAPP_VERIFY_TOKEN),
            "app_secret_configured": bool(WHATSAPP_APP_SECRET),
        }

    @rate_limit(requests_per_minute=60)
    async def handle(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route WhatsApp GET requests with RBAC for status endpoint."""
        if path == "/api/v1/bots/whatsapp/status":
            # Use BotHandlerMixin's RBAC-protected status handler
            return await self.handle_status_request(handler)

        if path == "/api/v1/bots/whatsapp/webhook":
            # Webhook verification challenge - no RBAC (called by Meta)
            return self._handle_verification(query_params)

        return None

    @handle_errors("whats app creation")
    @rate_limit(requests_per_minute=1000, limiter_name="whatsapp_webhook")
    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Handle POST requests (webhook messages).

        Rate limited to 1000 requests per minute per IP to allow for legitimate
        platform traffic while protecting against abuse. WhatsApp webhooks are
        authenticated via signature verification, so the higher limit is safe.
        """
        if path == "/api/v1/bots/whatsapp/webhook":
            return self._handle_webhook(handler)

        return None

    def _handle_verification(self, query_params: dict[str, Any]) -> HandlerResult:
        """Handle WhatsApp webhook verification challenge.

        WhatsApp sends a GET request with:
        - hub.mode=subscribe
        - hub.verify_token=<your token>
        - hub.challenge=<challenge string>

        We must respond with the challenge if the token matches.
        """
        mode = query_params.get("hub.mode", [""])[0]
        token = query_params.get("hub.verify_token", [""])[0]
        challenge = query_params.get("hub.challenge", [""])[0]

        if mode == "subscribe":
            if not WHATSAPP_VERIFY_TOKEN:
                logger.warning("WHATSAPP_VERIFY_TOKEN not configured")
                return error_response("Verify token not configured", 403)

            if hmac.compare_digest(token, WHATSAPP_VERIFY_TOKEN):
                logger.info("WhatsApp webhook verification successful")
                # Return challenge as plain text
                return HandlerResult(
                    status_code=200,
                    content_type="text/plain",
                    body=challenge.encode(),
                )
            else:
                logger.warning("WhatsApp verification token mismatch")
                return error_response("Invalid verify token", 403)

        return error_response("Invalid verification request", 400)

    def _handle_webhook(self, handler: Any) -> HandlerResult:
        """Handle WhatsApp webhook messages.

        WhatsApp sends POST requests with message updates.
        See: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples
        """
        try:
            # Verify signature if app secret is configured
            signature = handler.headers.get("X-Hub-Signature-256", "")
            body = self._read_request_body(handler)

            if not _verify_whatsapp_signature(signature, body):
                logger.warning("WhatsApp signature verification failed")
                self._audit_webhook_auth_failure("signature")
                return error_response("Invalid signature", 401)

            # Parse webhook payload
            payload, err = self._parse_json_body(body, "WhatsApp webhook")
            if err:
                return err
            if payload is None:
                return error_response("WhatsApp webhook body must be a JSON object", 400)

            entries = payload.get("entry")
            if not isinstance(entries, list):
                return error_response("WhatsApp webhook body must include an 'entry' list", 400)

            # Process webhook entries
            for entry in entries:
                if not isinstance(entry, dict):
                    return error_response("WhatsApp webhook entries must be JSON objects", 400)
                for change in entry.get("changes", []):
                    if change.get("field") == "messages":
                        self._process_messages(change.get("value", {}))

            # Always return 200 to acknowledge
            return json_response({"status": "ok"})

        except (json.JSONDecodeError, KeyError, TypeError, ValueError, RuntimeError, OSError) as e:
            logger.exception("Unexpected WhatsApp webhook error: %s", e)
            # Return 200 to prevent retries
            return json_response(
                {"status": "error", "message": "An error occurred processing the webhook"}
            )

    def _process_messages(self, value: dict[str, Any]) -> None:
        """Process incoming WhatsApp messages."""
        metadata = value.get("metadata", {})
        metadata.get("phone_number_id")

        contacts = value.get("contacts", [])
        messages = value.get("messages", [])

        for message in messages:
            msg_type = message.get("type")
            from_number = message.get("from")
            msg_id = message.get("id")
            message.get("timestamp")

            # Find contact info
            contact_name = "Unknown"
            for contact in contacts:
                if contact.get("wa_id") == from_number:
                    contact_name = contact.get("profile", {}).get("name", from_number)
                    break

            logger.info(
                "WhatsApp message from %s (%s): type=%s", contact_name, from_number, msg_type
            )

            if msg_type == "text":
                text = message.get("text", {}).get("body", "")
                attachments = self._extract_attachments(message)
                attachments = self._hydrate_whatsapp_attachments(attachments)
                self._handle_text_message(
                    from_number,
                    contact_name,
                    text,
                    msg_id,
                    attachments=attachments,
                )
            elif msg_type in ("document", "image", "video", "audio"):
                attachments = self._extract_attachments(message)
                attachments = self._hydrate_whatsapp_attachments(attachments)
                caption = ""
                media_payload = message.get(msg_type, {})
                if isinstance(media_payload, dict):
                    caption = media_payload.get("caption", "")
                if caption:
                    self._start_debate(from_number, contact_name, caption, attachments)
                else:
                    self._send_message(
                        from_number,
                        "Received your file. Please reply with a question to analyze it.",
                    )
            elif msg_type == "interactive":
                self._handle_interactive(from_number, message.get("interactive", {}))
            elif msg_type == "button":
                self._handle_button_reply(from_number, message.get("button", {}))
            else:
                logger.debug("Unhandled WhatsApp message type: %s", msg_type)

    def _handle_text_message(
        self,
        from_number: str,
        contact_name: str,
        text: str,
        msg_id: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> None:
        """Handle incoming text message."""
        text_lower = text.lower().strip()

        # Check for commands
        if text_lower.startswith("/"):
            parts = text[1:].split(maxsplit=1)
            command = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""

            if command == "help":
                self._send_help(from_number)
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
                self._start_debate(
                    from_number,
                    contact_name,
                    args,
                    attachments,
                    decision_integrity=decision_integrity,
                )
            elif command == "status":
                self._send_status(from_number)
            else:
                self._send_message(
                    from_number,
                    f"Unknown command: /{command}\n\nUse /help to see available commands.",
                )
        elif text_lower in ("hi", "hello", "hey", "start"):
            self._send_welcome(from_number)
        else:
            # Treat as debate topic
            self._start_debate(from_number, contact_name, text, attachments)

    def _handle_interactive(self, from_number: str, interactive: dict[str, Any]) -> None:
        """Handle interactive message response (list reply, button reply)."""
        int_type = interactive.get("type")

        if int_type == "list_reply":
            reply = interactive.get("list_reply", {})
            reply_id = reply.get("id", "")
            logger.info("WhatsApp list reply from %s: %s", from_number, reply_id)

        elif int_type == "button_reply":
            reply = interactive.get("button_reply", {})
            button_id = reply.get("id", "")
            logger.info("WhatsApp button reply from %s: %s", from_number, button_id)

    def _handle_button_reply(self, from_number: str, button: dict[str, Any]) -> None:
        """Handle quick reply button response."""
        payload = button.get("payload", "")
        text = button.get("text", "")
        logger.info("WhatsApp button reply from %s: %s (%s)", from_number, payload, text)

    def _extract_attachments(self, message: dict[str, Any]) -> list[dict[str, Any]]:
        """Extract WhatsApp attachment metadata from message payload."""
        attachments: list[dict[str, Any]] = []
        if not isinstance(message, dict):
            return attachments

        caption = ""
        if isinstance(message.get("text"), dict):
            caption = message.get("text", {}).get("body", "")

        document = message.get("document")
        if isinstance(document, dict):
            attachments.append(
                {
                    "type": "document",
                    "file_id": document.get("id"),
                    "filename": document.get("filename") or "document",
                    "content_type": document.get("mime_type"),
                    "caption": document.get("caption"),
                    "text": caption or document.get("caption") or "",
                }
            )

        image = message.get("image")
        if isinstance(image, dict):
            attachments.append(
                {
                    "type": "image",
                    "file_id": image.get("id"),
                    "content_type": image.get("mime_type"),
                    "caption": image.get("caption"),
                    "text": caption or image.get("caption") or "",
                }
            )

        video = message.get("video")
        if isinstance(video, dict):
            attachments.append(
                {
                    "type": "video",
                    "file_id": video.get("id"),
                    "content_type": video.get("mime_type"),
                    "caption": video.get("caption"),
                    "text": caption or video.get("caption") or "",
                }
            )

        audio = message.get("audio")
        if isinstance(audio, dict):
            attachments.append(
                {
                    "type": "audio",
                    "file_id": audio.get("id"),
                    "content_type": audio.get("mime_type"),
                    "text": caption,
                }
            )

        return attachments

    def _hydrate_whatsapp_attachments(
        self,
        attachments: list[dict[str, Any]],
        max_bytes: int = 2_000_000,
    ) -> list[dict[str, Any]]:
        """Best-effort download of WhatsApp media into attachment payloads."""
        if not attachments:
            return attachments

        try:
            from aragora.connectors.chat.registry import get_connector
        except ImportError as e:
            logger.debug("WhatsApp connector unavailable for downloads: %s", e)
            return attachments

        connector = get_connector("whatsapp")
        if (
            connector is None
            or not getattr(connector, "bot_token", "")
            or not getattr(connector, "phone_number_id", "")
        ):
            return attachments

        try:
            asyncio.get_running_loop()
            # If we already have a running loop, skip to avoid blocking.
            return attachments
        except RuntimeError:
            pass

        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            file_id = attachment.get("file_id")
            if not file_id or attachment.get("data") or attachment.get("content"):
                continue
            try:
                file_obj = asyncio.run(connector.download_file(str(file_id)))
                content = getattr(file_obj, "content", None)
                if content and len(content) <= max_bytes:
                    attachment["data"] = content
                    if not attachment.get("filename") and getattr(file_obj, "filename", None):
                        attachment["filename"] = file_obj.filename
                    if not attachment.get("content_type") and getattr(
                        file_obj, "content_type", None
                    ):
                        attachment["content_type"] = file_obj.content_type
                    if not attachment.get("size") and getattr(file_obj, "size", None):
                        attachment["size"] = file_obj.size
            except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
                logger.debug("Failed to download WhatsApp media %s: %s", file_id, e)

        return attachments

    # Message sending

    def _send_message(self, to_number: str, text: str) -> None:
        """Send a text message via WhatsApp Cloud API."""
        if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
            logger.warning("Cannot send WhatsApp message: credentials not configured")
            return

        try:
            import httpx

            url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
            headers = {
                "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
                "Content-Type": "application/json",
            }
            data = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to_number,
                "type": "text",
                "text": {"preview_url": False, "body": text},
            }

            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, headers=headers, json=data)
                if not response.is_success:
                    logger.warning(
                        "WhatsApp send failed: %s - %s", response.status_code, response.text
                    )

        except ImportError:
            logger.warning("httpx not available for WhatsApp messaging")
        except REDIS_CONNECTION_ERRORS as e:
            logger.error("Failed to send WhatsApp message: %s", e)

    def _send_welcome(self, to_number: str) -> None:
        """Send welcome message."""
        self._send_message(
            to_number,
            "Welcome to Aragora - Control plane for multi-agent vetted decisionmaking!\n\n"
            "I orchestrate 15+ AI models (Claude, GPT, Gemini, Grok and more) "
            "to debate and deliver defensible decisions.\n\n"
            "Just send me a question and I'll start a multi-agent vetted decisionmaking!\n\n"
            "Commands:\n"
            "/debate <question> - Start a debate\n"
            "/plan <question> - Debate + implementation plan\n"
            "/implement <question> - Debate + plan with context snapshot\n"
            "/status - Check system status\n"
            "/help - Show help",
        )

    def _send_help(self, to_number: str) -> None:
        """Send help message."""
        self._send_message(
            to_number,
            "Aragora Commands:\n\n"
            "/debate <question> - Start a multi-agent debate\n"
            "/plan <question> - Debate + implementation plan\n"
            "/implement <question> - Debate + plan with context snapshot\n"
            "/status - Check Aragora system status\n"
            "/help - Show this message\n\n"
            "Or just send me any question to start a debate!\n\n"
            "Example:\n"
            "Should we use microservices or a monolith for our new project?",
        )

    def _send_status(self, to_number: str) -> None:
        """Send status message."""
        self._send_message(
            to_number,
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

    def _start_debate(
        self,
        to_number: str,
        contact_name: str,
        topic: str,
        attachments: list[dict[str, Any]] | None = None,
        decision_integrity: dict[str, Any] | bool | None = None,
    ) -> None:
        """Start a debate on the given topic."""
        # RBAC: check debate creation permission
        try:
            self._check_bot_permission("debates:create", user_id=f"whatsapp:{to_number}")
        except PermissionError as exc:
            logger.warning("RBAC denied debates:create for whatsapp:%s: %s", to_number, exc)
            self._send_message(to_number, "Permission denied: you cannot start debates.")
            return

        if not topic.strip():
            self._send_message(
                to_number,
                "Please provide a topic for the debate.\n\n"
                "Example: Should startups focus on growth or profitability first?",
            )
            return

        # Start debate via queue system
        debate_id = self._start_debate_async(
            to_number,
            contact_name,
            topic,
            attachments,
            decision_integrity=decision_integrity,
        )

        self._send_message(
            to_number,
            f"Starting debate on:\n\n{topic[:200]}\n\n"
            "I'll notify you when the AI agents reach consensus. "
            f"Debate ID: {debate_id[:8]}...",
        )

        logger.info(
            "Debate requested from WhatsApp %s (%s): %s", contact_name, to_number, topic[:100]
        )

    def _start_debate_async(
        self,
        to_number: str,
        contact_name: str,
        topic: str,
        attachments: list[dict[str, Any]] | None = None,
        decision_integrity: dict[str, Any] | bool | None = None,
    ) -> str:
        """Start a debate asynchronously via the DecisionRouter.

        Uses the unified DecisionRouter for:
        - Deduplication across channels
        - Response caching
        - RBAC enforcement
        - Consistent routing

        Falls back to queue system if DecisionRouter unavailable.
        """
        import uuid
        import asyncio

        debate_id = str(uuid.uuid4())

        # Register origin for result routing
        try:
            from aragora.server.debate_origin import register_debate_origin

            register_debate_origin(
                debate_id=debate_id,
                platform="whatsapp",
                channel_id=to_number,
                user_id=to_number,
                metadata={"topic": topic, "contact_name": contact_name},
            )
        except (RuntimeError, KeyError, AttributeError, OSError) as e:
            logger.warning("Failed to register debate origin: %s", e)

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

            async def route_via_decision_router():
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
                    "source": InputSource.WHATSAPP,
                    "response_channels": [
                        ResponseChannel(
                            platform="whatsapp",
                            channel_id=to_number,
                            user_id=to_number,
                        )
                    ],
                    "context": RequestContext(
                        user_id=f"whatsapp:{to_number}",
                        metadata={"contact_name": contact_name},
                    ),
                    "attachments": attachments or [],
                }
                if config is not None:
                    request_kwargs["config"] = config

                request = DecisionRequest(**request_kwargs)  # type: ignore[arg-type]

                # Route through DecisionRouter (handles deduplication, caching)
                router = get_decision_router()
                result = await router.route(request)
                if result and result.debate_id:
                    logger.info("DecisionRouter started debate %s from WhatsApp", result.debate_id)
                return result

            # Run async in background
            try:
                asyncio.get_running_loop()
                task = asyncio.create_task(route_via_decision_router())
                task.add_done_callback(
                    lambda t: logger.error("WhatsApp debate routing failed: %s", t.exception())
                    if not t.cancelled() and t.exception()
                    else None
                )
                return debate_id
            except RuntimeError:
                asyncio.run(route_via_decision_router())
                return debate_id

        except ImportError:
            logger.debug("DecisionRouter not available, falling back to queue system")
        except (RuntimeError, ValueError, KeyError, AttributeError) as e:
            logger.error("DecisionRouter failed: %s, falling back to queue system", e)

        # Fallback to queue system
        return self._start_debate_via_queue(to_number, contact_name, topic, debate_id)

    def _start_debate_via_queue(
        self, to_number: str, contact_name: str, topic: str, debate_id: str
    ) -> str:
        """Fallback to direct queue enqueue if DecisionRouter unavailable."""
        import asyncio

        try:
            from aragora.queue import create_debate_job

            job = create_debate_job(
                question=topic,
                agents=None,  # Use default agents
                rounds=DEFAULT_ROUNDS,
                consensus=DEFAULT_CONSENSUS,
                protocol="standard",
                user_id=f"whatsapp:{to_number}",
                webhook_url=None,  # Results routed via debate_origin system
            )

            # Fire and forget - enqueue the job
            async def enqueue_job():
                try:
                    from aragora.queue import create_redis_queue

                    queue = await create_redis_queue()
                    await queue.enqueue(job)
                    logger.info("WhatsApp debate job enqueued: %s", job.id)
                except (RuntimeError, OSError, ConnectionError) as e:
                    logger.error("Failed to enqueue debate job: %s", e)
                    self._send_message(
                        to_number, "Sorry, I couldn't start the debate. Please try again later."
                    )

            # Run async enqueue in background
            try:
                asyncio.get_running_loop()
                task = asyncio.create_task(enqueue_job())
                task.add_done_callback(
                    lambda t: logger.error("WhatsApp job enqueue failed: %s", t.exception())
                    if not t.cancelled() and t.exception()
                    else None
                )
            except RuntimeError:
                # No event loop, create one
                asyncio.run(enqueue_job())

            return job.id

        except ImportError:
            logger.warning("Queue system not available, using direct execution")
            # Fallback: run debate directly (blocking)
            return self._run_debate_direct(to_number, contact_name, topic, debate_id)
        except (RuntimeError, OSError, ConnectionError) as e:
            logger.error("Failed to start debate: %s", e)
            return debate_id

    def _run_debate_direct(
        self, to_number: str, contact_name: str, topic: str, debate_id: str
    ) -> str:
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
                            to_number,
                            f"Debate Complete!\n\n"
                            f"Topic: {topic[:100]}\n\n"
                            f"Consensus: {result.final_answer[:500]}\n\n"
                            f"Confidence: {result.confidence:.0%}",
                        )
                    else:
                        self._send_message(
                            to_number,
                            f"Debate Complete!\n\n"
                            f"Topic: {topic[:100]}\n\n"
                            "No consensus was reached. The agents had differing views.",
                        )

                asyncio.run(execute())

            except (RuntimeError, ImportError, ValueError, AttributeError) as e:
                logger.error("Direct debate execution failed: %s", e)
                self._send_message(
                    to_number, "Sorry, an error occurred while processing your request."
                )

        # Run in background thread to not block webhook response
        thread = threading.Thread(target=run_in_thread, daemon=True)
        thread.start()

        return debate_id
