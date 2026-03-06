"""HTTP handler for inbox trust wedge receipts."""

from __future__ import annotations

import logging
from typing import Any

from aragora.server.handlers.base import BaseHandler, HandlerResult, error_response, json_response
from aragora.server.validation.query_params import safe_query_int

from .email_actions import (
    _content_hash_from_payload,
    _receipt_response_payload,
    _safe_float,
    _single_label_from_payload,
    get_inbox_trust_wedge_service_instance,
)

logger = logging.getLogger(__name__)


class InboxTrustWedgeHandler(BaseHandler):
    """Expose receipt-gated inbox wedge actions over HTTP."""

    ROUTES = ["/api/v1/inbox/wedge/receipts"]
    ROUTE_PREFIXES = ["/api/v1/inbox/wedge/receipts/"]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        return path == self.ROUTES[0] or path.startswith(self.ROUTE_PREFIXES[0])

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        method = getattr(handler, "command", "GET").upper()
        if method == "GET":
            user, perm_err = self.require_permission_or_error(handler, "approval:read")
            if perm_err:
                return perm_err
            return self._handle_get(path, query_params, user)

        if method == "POST":
            user, perm_err = self.require_permission_or_error(handler, "email:update")
            if perm_err:
                return perm_err
            body = self.read_json_body(handler)
            if body is None:
                return error_response("Invalid JSON body", 400)
            return self._handle_post(path, body, user)

        return error_response("Method not allowed", 405)

    def _handle_get(
        self,
        path: str,
        query_params: dict[str, Any],
        user: Any,
    ) -> HandlerResult:
        from aragora.inbox import ReceiptState

        service = get_inbox_trust_wedge_service_instance()
        if path == self.ROUTES[0]:
            limit = safe_query_int(query_params, "limit", default=50, min_val=1, max_val=500)
            state = None
            state_raw = query_params.get("state")
            if state_raw:
                try:
                    state = ReceiptState(str(state_raw).lower())
                except ValueError:
                    return error_response("Invalid receipt state", 400)

            receipts = [
                envelope.to_dict()
                for envelope in service.store.list_receipts(state=state, limit=limit)
            ]
            return json_response(
                {
                    "receipts": receipts,
                    "count": len(receipts),
                    "requested_by": getattr(user, "user_id", None),
                }
            )

        receipt_id = self._extract_receipt_id(path)
        if not receipt_id:
            return error_response("Not found", 404)
        envelope = service.store.get_receipt(receipt_id)
        if envelope is None:
            return error_response("Receipt not found", 404)
        return json_response(envelope.to_dict())

    def _handle_post(
        self,
        path: str,
        body: dict[str, Any],
        user: Any,
    ) -> HandlerResult:
        from aragora.inbox import ActionIntent, TriageDecision

        service = get_inbox_trust_wedge_service_instance()
        if path == self.ROUTES[0]:
            message_id = str(body.get("message_id", "")).strip()
            provider = str(body.get("provider", "gmail")).strip().lower()
            action = str(body.get("action", "")).strip().lower()
            if not message_id:
                return error_response("message_id is required", 400)
            if not action:
                return error_response("action is required", 400)

            label_id = _single_label_from_payload(body)
            try:
                intent = ActionIntent.create(
                    provider=provider,
                    user_id=str(body.get("user_id") or getattr(user, "user_id", None) or "default"),
                    message_id=message_id,
                    action=action,
                    content_hash=_content_hash_from_payload(body, message_id),
                    synthesized_rationale=str(
                        body.get("synthesized_rationale")
                        or body.get("rationale")
                        or body.get("reason")
                        or ""
                    ),
                    confidence=_safe_float(
                        body.get("confidence", body.get("debate_confidence")), 0.0
                    ),
                    provider_route=str(body.get("provider_route", "direct")),
                    debate_id=str(body["debate_id"]) if body.get("debate_id") else None,
                    label_id=label_id,
                )
                decision = TriageDecision.create(
                    final_action=action,
                    confidence=_safe_float(
                        body.get("confidence", body.get("debate_confidence")), 0.0
                    ),
                    dissent_summary=str(body.get("dissent_summary", "")),
                    label_id=label_id,
                    blocked_by_policy=bool(body.get("blocked_by_policy", False)),
                    cost_usd=(
                        _safe_float(body.get("cost_usd"))
                        if body.get("cost_usd") is not None
                        else None
                    ),
                    latency_seconds=(
                        _safe_float(body.get("latency_seconds"))
                        if body.get("latency_seconds") is not None
                        else None
                    ),
                )
                envelope = service.create_receipt(
                    intent,
                    decision,
                    expires_in_hours=_safe_float(body.get("expires_in_hours"), 24.0),
                    auto_approve=bool(body.get("auto_approve", False)),
                )
                execution_result = None
                executed = False
                if (
                    bool(body.get("auto_execute", False))
                    and envelope.receipt.state.value == "approved"
                ):
                    result = self._run_async(service.execute_receipt(envelope.receipt.receipt_id))
                    envelope = service.store.get_receipt(envelope.receipt.receipt_id) or envelope
                    execution_result = result.to_dict()
                    executed = True
                return json_response(
                    _receipt_response_payload(
                        envelope,
                        action_name=action,
                        message_id=message_id,
                        executed=executed,
                        execution_result=execution_result,
                    )
                )
            except ValueError as exc:
                return error_response(str(exc), 400)
            except (
                AttributeError,
                RuntimeError,
                OSError,
                ConnectionError,
                TypeError,
                KeyError,
            ) as exc:
                logger.exception("Failed to create inbox trust wedge receipt: %s", exc)
                return error_response("Receipt creation failed", 500)

        receipt_id = self._extract_receipt_id(path)
        if not receipt_id:
            return error_response("Not found", 404)

        if path.endswith("/review"):
            choice = str(body.get("choice", "")).strip().lower()
            if not choice:
                return error_response("choice is required", 400)
            try:
                envelope = service.review_receipt(
                    receipt_id,
                    choice=choice,
                    edited_action=body.get("action"),
                    edited_rationale=body.get("synthesized_rationale") or body.get("rationale"),
                    label_id=body.get("label_id") or _single_label_from_payload(body),
                )
                execution_result = None
                executed = False
                if choice == "approve" and bool(body.get("execute", False)):
                    result = self._run_async(service.execute_receipt(receipt_id))
                    envelope = service.store.get_receipt(receipt_id) or envelope
                    execution_result = result.to_dict()
                    executed = True
                return json_response(
                    _receipt_response_payload(
                        envelope,
                        action_name=envelope.intent.action.value,
                        message_id=envelope.intent.message_id,
                        executed=executed,
                        execution_result=execution_result,
                    )
                )
            except ValueError as exc:
                return error_response(str(exc), 400)
            except (
                AttributeError,
                RuntimeError,
                OSError,
                ConnectionError,
                TypeError,
                KeyError,
            ) as exc:
                logger.exception("Failed to review inbox trust wedge receipt: %s", exc)
                return error_response("Receipt review failed", 500)

        if path.endswith("/execute"):
            try:
                result = self._run_async(service.execute_receipt(receipt_id))
                envelope = service.store.get_receipt(receipt_id)
                if envelope is None:
                    return error_response("Receipt not found after execution", 500)
                return json_response(
                    _receipt_response_payload(
                        envelope,
                        action_name=envelope.intent.action.value,
                        message_id=envelope.intent.message_id,
                        executed=True,
                        execution_result=result.to_dict(),
                    )
                )
            except ValueError as exc:
                return error_response(str(exc), 400)
            except (
                AttributeError,
                RuntimeError,
                OSError,
                ConnectionError,
                TypeError,
                KeyError,
            ) as exc:
                logger.exception("Failed to execute inbox trust wedge receipt: %s", exc)
                return error_response("Receipt execution failed", 500)

        return error_response("Not found", 404)

    def _extract_receipt_id(self, path: str) -> str | None:
        prefix = self.ROUTE_PREFIXES[0]
        if not path.startswith(prefix):
            return None
        remainder = path[len(prefix) :]
        if not remainder:
            return None
        return remainder.split("/", 1)[0] or None

    def _run_async(self, coro: Any) -> Any:
        from aragora.server.handler_registry.core import _run_handler_coroutine

        return _run_handler_coroutine(coro)


__all__ = ["InboxTrustWedgeHandler"]
