"""Unified Inbox API Handler.

Provides a unified interface for multi-account email management:
- Gmail and Outlook integration through a single API
- Cross-account message retrieval with priority scoring
- Multi-agent triage for complex messages
- Inbox health metrics and analytics

OAuth Flow:
1. GET  /api/v1/inbox/oauth/gmail     - Get Gmail OAuth authorization URL
2. GET  /api/v1/inbox/oauth/outlook   - Get Outlook OAuth authorization URL
3. User is redirected to provider authorization page
4. Provider redirects back with auth_code
5. POST /api/v1/inbox/connect         - Exchange auth_code for tokens

Endpoints:
- GET  /api/v1/inbox/oauth/gmail      - Get Gmail OAuth URL (redirect_uri required)
- GET  /api/v1/inbox/oauth/outlook    - Get Outlook OAuth URL (redirect_uri required)
- POST /api/v1/inbox/connect          - Connect Gmail or Outlook account
- GET  /api/v1/inbox/accounts         - List connected accounts
- DELETE /api/v1/inbox/accounts/{id}  - Disconnect an account
- GET  /api/v1/inbox/messages         - Get prioritized messages across accounts
- GET  /api/v1/inbox/messages/{id}    - Get single message details
- POST /api/v1/inbox/triage           - Multi-agent triage for messages
- POST /api/v1/inbox/bulk-action      - Bulk actions (archive, read, etc.)
- GET  /api/v1/inbox/stats            - Inbox health metrics
- GET  /api/v1/inbox/trends           - Priority trends over time
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    success_response,
)
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.handlers.utils import parse_json_body
from aragora.stores import get_canonical_gateway_stores

from .accounts import (
    connect_gmail,
    connect_outlook,
    disconnect_account,
    handle_gmail_oauth_url,
    handle_outlook_oauth_url,
)
from .actions import VALID_ACTIONS, execute_bulk_action
from .messages import fetch_all_messages
from .models import (
    AccountStatus,
    ConnectedAccount,
    EmailProvider,
    UnifiedMessage,
    account_to_record,
    message_to_record,
    record_to_account,
    record_to_message,
    record_to_triage,
    triage_to_record,
)
from .stats import compute_stats, compute_trends
from .triage import run_triage

logger = logging.getLogger(__name__)


class UnifiedInboxHandler(BaseHandler):
    """Handler for unified inbox API endpoints."""

    ROUTES = [
        "/api/v1/inbox/oauth/gmail",
        "/api/v1/inbox/oauth/outlook",
        "/api/v1/inbox/connect",
        "/api/v1/inbox/accounts",
        "/api/v1/inbox/accounts/{account_id}",
        "/api/v1/inbox/messages",
        "/api/v1/inbox/messages/{message_id}",
        "/api/v1/inbox/triage",
        "/api/v1/inbox/bulk-action",
        "/api/v1/inbox/stats",
        "/api/v1/inbox/trends",
        "/api/v1/inbox/messages/{message_id}/debate",
        "/api/v1/inbox/actions",
        "/api/v1/inbox/bulk-actions",
        "/api/v1/inbox/command",
        "/api/v1/inbox/daily-digest",
        "/api/v1/inbox/mentions",
        "/api/v1/inbox/reprioritize",
        "/api/v1/inbox/sender-profile",
        # Non-versioned inbox routes
        "/inbox/accounts",
        "/inbox/bulk-action",
        "/inbox/connect",
        "/inbox/messages",
        "/inbox/messages/send",
        "/inbox/oauth/gmail",
        "/inbox/oauth/outlook",
        "/inbox/stats",
        "/inbox/trends",
        "/inbox/triage",
    ]

    def __init__(self, server_context: dict[str, Any] | None = None):
        """Initialize handler with optional server context."""
        super().__init__(server_context or dict())
        self._store = get_canonical_gateway_stores().inbox_store()

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        return path.startswith("/api/v1/inbox") and not path.startswith("/api/v1/inbox/wedge/")

    @require_permission("inbox:read")
    async def handle_request(self, request: Any, path: str, method: str) -> HandlerResult:
        """Route requests to appropriate handler methods."""
        try:
            # Extract tenant context
            tenant_id = self._get_tenant_id(request)

            # Route based on path and method
            # OAuth URL generation endpoints
            if path == "/api/v1/inbox/oauth/gmail" and method == "GET":
                return await self._handle_gmail_oauth_url(request, tenant_id)

            elif path == "/api/v1/inbox/oauth/outlook" and method == "GET":
                return await self._handle_outlook_oauth_url(request, tenant_id)

            elif path == "/api/v1/inbox/connect" and method == "POST":
                return await self._handle_connect(request, tenant_id)

            elif path == "/api/v1/inbox/accounts" and method == "GET":
                return await self._handle_list_accounts(request, tenant_id)

            elif path.startswith("/api/v1/inbox/accounts/") and method == "DELETE":
                account_id = path.split("/")[-1]
                return await self._handle_disconnect(request, tenant_id, account_id)

            elif path == "/api/v1/inbox/messages" and method == "GET":
                return await self._handle_list_messages(request, tenant_id)

            elif (
                path.startswith("/api/v1/inbox/messages/")
                and path.endswith("/debate")
                and method == "POST"
            ):
                message_id = path.split("/")[-2]
                return await self._handle_auto_debate(request, tenant_id, message_id)

            elif path.startswith("/api/v1/inbox/messages/") and method == "GET":
                message_id = path.split("/")[-1]
                return await self._handle_get_message(request, tenant_id, message_id)

            elif path == "/api/v1/inbox/triage" and method == "POST":
                return await self._handle_triage(request, tenant_id)

            elif path == "/api/v1/inbox/bulk-action" and method == "POST":
                return await self._handle_bulk_action(request, tenant_id)

            elif path == "/api/v1/inbox/stats" and method == "GET":
                return await self._handle_stats(request, tenant_id)

            elif path == "/api/v1/inbox/trends" and method == "GET":
                return await self._handle_trends(request, tenant_id)

            return error_response("Not found", 404)

        except (ValueError, KeyError, TypeError, RuntimeError, OSError) as e:
            logger.exception("Error in unified inbox handler: %s", e)
            return error_response("Internal server error", 500)

    def _get_tenant_id(self, request: Any) -> str:
        """Extract tenant ID from request context."""
        # In production, extract from JWT or session
        return getattr(request, "tenant_id", "default")

    # =========================================================================
    # OAuth URL Generation
    # =========================================================================

    async def _handle_gmail_oauth_url(self, request: Any, tenant_id: str) -> HandlerResult:
        """Generate Gmail OAuth authorization URL."""
        try:
            params = self._get_query_params(request)
            result = await handle_gmail_oauth_url(params, tenant_id)
            if result["success"]:
                return success_response(result["data"])
            return error_response(result["error"], result.get("status_code", 400))
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("Error generating Gmail OAuth URL: %s", e)
            return error_response("OAuth URL generation failed", 500)

    async def _handle_outlook_oauth_url(self, request: Any, tenant_id: str) -> HandlerResult:
        """Generate Outlook OAuth authorization URL."""
        try:
            params = self._get_query_params(request)
            result = await handle_outlook_oauth_url(params, tenant_id)
            if result["success"]:
                return success_response(result["data"])
            return error_response(result["error"], result.get("status_code", 400))
        except (ConnectionError, TimeoutError, OSError, ValueError) as e:
            logger.exception("Error generating Outlook OAuth URL: %s", e)
            return error_response("OAuth URL generation failed", 500)

    # =========================================================================
    # Connect Account
    # =========================================================================

    async def _handle_connect(self, request: Any, tenant_id: str) -> HandlerResult:
        """Handle account connection request."""
        try:
            body = await self._get_json_body(request)

            provider_str = body.get("provider", "").lower()
            if provider_str not in ["gmail", "outlook"]:
                return error_response("Invalid provider. Must be 'gmail' or 'outlook'", 400)

            provider = EmailProvider(provider_str)
            auth_code = body.get("auth_code")
            redirect_uri = body.get("redirect_uri", "")

            if not auth_code:
                return error_response("Missing auth_code", 400)

            # Create account record
            account_id = str(uuid4())
            account = ConnectedAccount(
                id=account_id,
                provider=provider,
                email_address="",  # Will be filled after OAuth
                display_name="",
                status=AccountStatus.PENDING,
                connected_at=datetime.now(timezone.utc),
            )

            # Exchange auth code for tokens based on provider
            if provider == EmailProvider.GMAIL:
                result = await connect_gmail(
                    account,
                    auth_code,
                    redirect_uri,
                    tenant_id,
                    self._schedule_message_persist,
                )
            else:
                result = await connect_outlook(
                    account,
                    auth_code,
                    redirect_uri,
                    tenant_id,
                    self._schedule_message_persist,
                )

            if result.get("success"):
                await self._store.save_account(tenant_id, account_to_record(account))
                logger.info(
                    "Connected %s account for tenant %s: %s",
                    provider.value,
                    tenant_id,
                    account.email_address,
                )
                return success_response(
                    {
                        "account": account.to_dict(),
                        "message": f"Successfully connected {provider.value} account",
                    }
                )
            else:
                return error_response(result.get("error", "Failed to connect account"), 400)

        except (ConnectionError, TimeoutError, OSError, ValueError, KeyError) as e:
            logger.exception("Error connecting account: %s", e)
            return error_response("Account connection failed", 500)

    # =========================================================================
    # List/Disconnect Accounts
    # =========================================================================

    async def _handle_list_accounts(self, request: Any, tenant_id: str) -> HandlerResult:
        """List all connected accounts."""
        records = await self._store.list_accounts(tenant_id)
        accounts = [record_to_account(record) for record in records]
        return success_response(
            {
                "accounts": [acc.to_dict() for acc in accounts],
                "total": len(accounts),
            }
        )

    async def _handle_disconnect(
        self, request: Any, tenant_id: str, account_id: str
    ) -> HandlerResult:
        """Disconnect an account."""
        record = await self._store.get_account(tenant_id, account_id)
        if not record:
            return error_response("Account not found", 404)

        account = record_to_account(record)

        # Stop and remove sync service if running
        await disconnect_account(tenant_id, account_id)

        await self._store.delete_account(tenant_id, account_id)

        logger.info(
            "Disconnected %s account for tenant %s: %s",
            account.provider.value,
            tenant_id,
            account.email_address,
        )

        return success_response(
            {
                "message": f"Successfully disconnected {account.provider.value} account",
                "account_id": account_id,
            }
        )

    # =========================================================================
    # Messages
    # =========================================================================

    async def _handle_list_messages(self, request: Any, tenant_id: str) -> HandlerResult:
        """Get prioritized messages across all accounts."""
        try:
            params = self._get_query_params(request)
            try:
                limit = int(params.get("limit", 50))
            except (ValueError, TypeError):
                limit = 50
            try:
                offset = int(params.get("offset", 0))
            except (ValueError, TypeError):
                offset = 0
            priority_filter = params.get("priority")
            account_filter = params.get("account_id")
            unread_only = params.get("unread_only", "false").lower() == "true"
            search_query = params.get("search")

            records, total = await self._store.list_messages(
                tenant_id=tenant_id,
                limit=limit,
                offset=offset,
                priority_tier=priority_filter,
                account_id=account_filter,
                unread_only=unread_only,
                search=search_query,
            )
            messages = [record_to_message(record) for record in records]

            return success_response(
                {
                    "messages": [m.to_dict() for m in messages],
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + limit < total,
                }
            )

        except (KeyError, ValueError, TypeError) as e:
            logger.exception("Error listing messages: %s", e)
            return error_response("Failed to list messages", 500)

    async def _handle_get_message(
        self, request: Any, tenant_id: str, message_id: str
    ) -> HandlerResult:
        """Get single message details."""
        record = await self._store.get_message(tenant_id, message_id)
        if not record:
            return error_response("Message not found", 404)

        message = record_to_message(record)
        triage_record = await self._store.get_triage_result(tenant_id, message_id)
        triage = record_to_triage(triage_record) if triage_record else None

        return success_response(
            {
                "message": message.to_dict(),
                "triage": triage.to_dict() if triage else None,
            }
        )

    # =========================================================================
    # Triage
    # =========================================================================

    async def _handle_triage(self, request: Any, tenant_id: str) -> HandlerResult:
        """Run multi-agent triage on messages."""
        try:
            body = await self._get_json_body(request)
            message_ids = body.get("message_ids", [])
            context = body.get("context", {})

            if not message_ids:
                return error_response("No message IDs provided", 400)

            messages_to_triage: list[UnifiedMessage] = []
            for message_id in message_ids:
                record = await self._store.get_message(tenant_id, message_id)
                if record:
                    messages_to_triage.append(record_to_message(record))

            if not messages_to_triage:
                return error_response("No matching messages found", 404)

            # Run triage
            results = await run_triage(
                messages_to_triage,
                context,
                tenant_id,
                self._store,
                triage_to_record,
            )

            return success_response(
                {
                    "results": [r.to_dict() for r in results],
                    "total_triaged": len(results),
                }
            )

        except (KeyError, ValueError, TypeError, ConnectionError) as e:
            logger.exception("Error during triage: %s", e)
            return error_response("Triage operation failed", 500)

    # =========================================================================
    # Bulk Actions
    # =========================================================================

    async def _handle_bulk_action(self, request: Any, tenant_id: str) -> HandlerResult:
        """Execute bulk action on messages."""
        try:
            body = await self._get_json_body(request)
            message_ids = body.get("message_ids", [])
            action = body.get("action", "")

            if not message_ids:
                return error_response("No message IDs provided", 400)

            if action not in VALID_ACTIONS:
                return error_response(
                    f"Invalid action. Must be one of: {', '.join(VALID_ACTIONS)}", 400
                )

            result = await execute_bulk_action(tenant_id, message_ids, action, self._store)
            return success_response(result)

        except (KeyError, ValueError, TypeError) as e:
            logger.exception("Error executing bulk action: %s", e)
            return error_response("Bulk action failed", 500)

    # =========================================================================
    # Stats & Trends
    # =========================================================================

    async def _handle_stats(self, request: Any, tenant_id: str) -> HandlerResult:
        """Get inbox health statistics."""
        account_records = await self._store.list_accounts(tenant_id)
        messages = await fetch_all_messages(tenant_id, self._store)
        stats = compute_stats(account_records, messages)
        return success_response({"stats": stats.to_dict()})

    async def _handle_trends(self, request: Any, tenant_id: str) -> HandlerResult:
        """Get priority trends over time."""
        params = self._get_query_params(request)
        try:
            days = int(params.get("days", 7))
        except (ValueError, TypeError):
            days = 7
        trends = compute_trends(days)
        return success_response({"trends": trends})

    # =========================================================================
    # Auto-Debate
    # =========================================================================

    async def _handle_auto_debate(
        self, request: Any, tenant_id: str, message_id: str
    ) -> HandlerResult:
        """Spawn a multi-agent debate to triage a message."""
        try:
            body = await self._get_json_body(request)
            record = await self._store.get_message(tenant_id, message_id)
            if not record:
                return error_response("Message not found", 404)

            message = record_to_message(record)

            from aragora.server.debate_factory import DebateFactory
            from aragora.inbox import (
                ActionIntent,
                ReceiptState,
                TriageDecision,
                get_inbox_trust_wedge_service,
            )
            from .auto_debate import (
                auto_spawn_debate_for_message,
                build_inbox_trust_wedge_plan,
                build_inbox_trust_wedge_question,
                parse_inbox_trust_wedge_output,
            )

            try:
                wedge_plan = build_inbox_trust_wedge_plan(body)
            except ValueError as exc:
                return error_response(str(exc), 400)

            provider_message_id = message.external_id or message.id
            response_payload: dict[str, Any] = {
                "source_message_id": message.id,
                "provider_message_id": provider_message_id,
            }

            question_override = None
            metadata = None
            if wedge_plan is not None:
                if message.provider is not EmailProvider.GMAIL:
                    return error_response(
                        "Inbox trust wedge currently supports Gmail unified inbox messages only",
                        400,
                    )
                if not message.account_id:
                    return error_response("Message missing connected account ID", 400)
                if not provider_message_id:
                    return error_response("Message missing provider message ID", 400)

                metadata = {
                    "mode": "inbox_trust_wedge",
                    "provider_message_id": provider_message_id,
                    "allowed_actions": [action.value for action in wedge_plan.allowed_actions],
                }
                if wedge_plan.label_id:
                    metadata["label_id"] = wedge_plan.label_id
                question_override = build_inbox_trust_wedge_question(message, wedge_plan)

            factory = DebateFactory()
            result = await auto_spawn_debate_for_message(
                message,
                factory,
                tenant_id,
                question_override=question_override,
                metadata=metadata,
            )
            response_payload["data"] = result

            if wedge_plan is None:
                return success_response(response_payload)

            parsed = parse_inbox_trust_wedge_output(
                str(result.get("final_answer") or ""),
                plan=wedge_plan,
                fallback_confidence=float(result.get("confidence") or 0.0),
            )
            if parsed is None:
                response_payload.update(
                    {
                        "receipt_created": False,
                        "receipt_error": ("Debate did not produce a safe inbox trust wedge action"),
                        "receipt": None,
                        "intent": None,
                        "decision": None,
                        "executed": False,
                    }
                )
                return success_response(response_payload)

            intent = ActionIntent.create(
                provider=message.provider.value,
                user_id=message.account_id,
                message_id=provider_message_id,
                action=parsed["action"],
                content_hash=ActionIntent.compute_content_hash(
                    provider_message_id,
                    message.subject,
                    message.snippet,
                    message.body_preview,
                    message.sender_email,
                ),
                synthesized_rationale=parsed["rationale"],
                confidence=parsed["confidence"],
                provider_route=wedge_plan.provider_route,
                debate_id=str(result.get("debate_id") or "") or None,
                label_id=parsed.get("label_id"),
            )
            decision = TriageDecision.create(
                final_action=parsed["action"],
                confidence=parsed["confidence"],
                dissent_summary=parsed["dissent_summary"],
                label_id=parsed.get("label_id"),
                cost_usd=(
                    float(result["cost_usd"]) if result.get("cost_usd") is not None else None
                ),
                latency_seconds=(
                    float(result["latency_seconds"])
                    if result.get("latency_seconds") is not None
                    else None
                ),
            )
            wedge_service = get_inbox_trust_wedge_service()
            envelope = wedge_service.create_receipt(
                intent,
                decision,
                expires_in_hours=wedge_plan.expires_in_hours,
                auto_approve=wedge_plan.auto_approve,
            )
            response_payload.update(
                {
                    "receipt_created": True,
                    "receipt": envelope.receipt.to_dict(),
                    "intent": envelope.intent.to_dict(),
                    "decision": envelope.decision.to_dict(),
                    "provider_route": envelope.provider_route,
                    "debate_id": envelope.debate_id,
                    "executed": False,
                }
            )

            if wedge_plan.auto_execute and envelope.receipt.state is ReceiptState.APPROVED:
                try:
                    execution_result = await wedge_service.execute_receipt(
                        envelope.receipt.receipt_id
                    )
                    updated = wedge_service.store.get_receipt(envelope.receipt.receipt_id)
                    if updated is not None:
                        envelope = updated
                    response_payload.update(
                        {
                            "receipt": envelope.receipt.to_dict(),
                            "intent": envelope.intent.to_dict(),
                            "decision": envelope.decision.to_dict(),
                            "provider_route": envelope.provider_route,
                            "debate_id": envelope.debate_id,
                            "executed": True,
                            "execution_result": execution_result.to_dict(),
                        }
                    )
                except ValueError as exc:
                    response_payload["execution_error"] = str(exc)
                except (
                    AttributeError,
                    RuntimeError,
                    OSError,
                    ConnectionError,
                    TypeError,
                    KeyError,
                ):
                    logger.exception("Error auto-executing inbox trust wedge receipt")
                    response_payload["execution_error"] = "Receipt execution failed"

            return success_response(response_payload)

        except (ValueError, TypeError, RuntimeError, OSError, KeyError) as e:
            logger.exception("Error spawning auto-debate: %s", e)
            return error_response("Auto-debate failed", 500)

    # =========================================================================
    # Persistence Helpers
    # =========================================================================

    def _schedule_message_persist(self, tenant_id: str, message: UnifiedMessage) -> None:
        """Schedule async persistence of a synced message."""

        async def _persist() -> None:
            try:
                await self._store.save_message(tenant_id, message_to_record(message))
                await self._store.update_account_fields(
                    tenant_id,
                    message.account_id,
                    {"last_sync": datetime.now(timezone.utc)},
                )
            except (OSError, ValueError, KeyError) as e:
                logger.warning("[UnifiedInbox] Failed to persist message: %s", e)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_persist())
            return
        loop.create_task(_persist())

    # =========================================================================
    # Utility Methods
    # =========================================================================

    async def _get_json_body(self, request: Any) -> dict[str, Any]:
        """Extract JSON body from request."""
        body, _err = await parse_json_body(request, context="unified_inbox")
        return body if body is not None else {}

    def _get_query_params(self, request: Any) -> dict[str, str]:
        """Extract query parameters from request."""
        if hasattr(request, "query"):
            return dict(request.query)
        if hasattr(request, "args"):
            return dict(request.args)
        return {}


# =============================================================================
# Handler Registration
# =============================================================================

_handler_instance: UnifiedInboxHandler | None = None


def get_unified_inbox_handler() -> UnifiedInboxHandler:
    """Get or create handler instance."""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = UnifiedInboxHandler()
    return _handler_instance


@require_permission("debates:read")
async def handle_unified_inbox(request: Any, path: str, method: str) -> HandlerResult:
    """Entry point for unified inbox requests."""
    handler = get_unified_inbox_handler()
    return await handler.handle_request(request, path, method)
