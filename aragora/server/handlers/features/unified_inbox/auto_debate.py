"""Auto-spawn debate for high-priority inbox messages.

Connects the Unified Inbox to the debate engine, allowing
multi-agent deliberation on how to handle critical messages.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from aragora.inbox import InboxWedgeAction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InboxTrustWedgeDebatePlan:
    """Conservative debate options for receipt-gated inbox actions."""

    allowed_actions: tuple[InboxWedgeAction, ...]
    label_id: str | None
    provider_route: str
    expires_in_hours: float
    auto_approve: bool
    auto_execute: bool


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_inbox_trust_wedge_plan(body: dict[str, Any]) -> InboxTrustWedgeDebatePlan | None:
    """Build a trust wedge debate plan from request body."""
    if not body.get("create_receipt"):
        return None

    label_id = str(body.get("label_id", "") or "").strip() or None
    raw_allowed = body.get("allowed_actions")
    if raw_allowed:
        if not isinstance(raw_allowed, list):
            raise ValueError("allowed_actions must be a list when provided")
        allowed_actions: list[InboxWedgeAction] = []
        for raw in raw_allowed:
            action = InboxWedgeAction.parse(str(raw))
            if action not in allowed_actions:
                allowed_actions.append(action)
    else:
        allowed_actions = [
            InboxWedgeAction.ARCHIVE,
            InboxWedgeAction.STAR,
            InboxWedgeAction.IGNORE,
        ]

    if InboxWedgeAction.LABEL in allowed_actions and not label_id:
        raise ValueError("label_id is required when allowed_actions includes 'label'")
    if not allowed_actions:
        raise ValueError("allowed_actions must contain at least one inbox wedge action")

    return InboxTrustWedgeDebatePlan(
        allowed_actions=tuple(allowed_actions),
        label_id=label_id,
        provider_route=str(body.get("provider_route", "direct") or "direct"),
        expires_in_hours=max(_safe_float(body.get("expires_in_hours"), 24.0), 0.1),
        auto_approve=bool(body.get("auto_approve", False)),
        auto_execute=bool(body.get("auto_execute", False)),
    )


def build_inbox_trust_wedge_question(
    message: Any,
    plan: InboxTrustWedgeDebatePlan,
) -> str:
    """Build a wedge-constrained debate question for a single inbox message."""
    sender = getattr(message, "sender_email", "unknown sender") or "unknown sender"
    subject = getattr(message, "subject", "no subject") or "no subject"
    snippet = getattr(message, "snippet", "") or ""
    body_preview = getattr(message, "body_preview", "") or ""
    priority_tier = getattr(message, "priority_tier", "medium") or "medium"

    action_descriptions: list[str] = []
    for action in plan.allowed_actions:
        if action is InboxWedgeAction.LABEL:
            action_descriptions.append(f'label (and only with label_id "{plan.label_id}")')
        else:
            action_descriptions.append(action.value)
    allowed = ", ".join(action_descriptions)

    question = (
        "Analyze this inbox message for a SAFE receipt-gated action. "
        "You may only recommend one of the explicitly allowed inbox wedge actions below, "
        "or return none if the evidence is insufficient.\n\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"Priority tier: {priority_tier}\n"
    )
    if snippet:
        question += f"Snippet: {snippet[:400]}\n"
    if body_preview:
        question += f"Body preview: {body_preview[:600]}\n"
    question += (
        "\nAllowed actions: "
        f"{allowed}. "
        "Disallowed: reply, forward, send, delegate, schedule, or any other action.\n\n"
        "Return ONLY a JSON object with keys: "
        "recommended_action, confidence, rationale, dissent_summary, label_id.\n"
        "Rules:\n"
        "- recommended_action must be one of the allowed actions above, or none.\n"
        "- confidence must be a number between 0 and 1.\n"
        "- rationale must be brief and evidence-based.\n"
        "- dissent_summary should summarize any disagreement or uncertainty.\n"
        "- If recommended_action is label, label_id must exactly match the allowed label.\n"
        "- If no safe action is justified, use recommended_action = none.\n"
    )
    return question


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def parse_inbox_trust_wedge_output(
    final_answer: str,
    *,
    plan: InboxTrustWedgeDebatePlan,
    fallback_confidence: float,
) -> dict[str, Any] | None:
    """Parse a structured debate answer into a safe wedge action."""
    candidate = _extract_json_object(final_answer.strip())
    if not candidate:
        return None

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return None

    raw_action = (
        str(payload.get("recommended_action") or payload.get("action") or "none").strip().lower()
    )
    alias_map = {
        "archive": "archive",
        "star": "star",
        "flag": "star",
        "ignore": "ignore",
        "defer": "ignore",
        "label": "label",
        "none": "none",
        "no_action": "none",
        "no-safe-action": "none",
        "no_safe_action": "none",
    }
    normalized = alias_map.get(raw_action, raw_action)
    if normalized == "none":
        return None

    try:
        action = InboxWedgeAction.parse(normalized)
    except ValueError:
        return None
    if action not in plan.allowed_actions:
        return None

    label_id = None
    if action is InboxWedgeAction.LABEL:
        label_id = str(payload.get("label_id") or "").strip() or plan.label_id
        if not label_id or label_id != plan.label_id:
            return None

    confidence = _safe_float(payload.get("confidence"), fallback_confidence)
    confidence = min(max(confidence, 0.0), 1.0)
    rationale = str(
        payload.get("rationale") or payload.get("reasoning") or "Structured inbox debate output"
    ).strip()
    dissent_summary = str(payload.get("dissent_summary") or payload.get("dissent") or "").strip()

    return {
        "action": action,
        "confidence": confidence,
        "rationale": rationale,
        "dissent_summary": dissent_summary,
        "label_id": label_id,
    }


async def auto_spawn_debate_for_message(
    message: Any,
    factory: Any,
    tenant_id: str,
    *,
    question_override: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Spawn a light debate to triage a high-priority inbox message.

    Creates a 3-round light debate asking agents to recommend how
    to handle the message (respond urgently, respond normally,
    delegate, or schedule later).

    Args:
        message: UnifiedMessage instance with priority_tier, sender_email, subject etc.
        factory: DebateFactory instance for creating arenas.
        tenant_id: Tenant context for the debate.

    Returns:
        Dict with debate_id, final_answer, consensus_reached, confidence.
    """
    from aragora.server.debate_factory import DebateConfig

    # Build triage question from message metadata
    priority_tier = getattr(message, "priority_tier", "medium")
    sender = getattr(message, "sender_email", "unknown sender") or "unknown sender"
    subject = getattr(message, "subject", "no subject") or "no subject"
    snippet = getattr(message, "snippet", "") or ""

    question = question_override
    if not question:
        question = f'Analyze this {priority_tier}-priority message from {sender} re: "{subject}". '
        if snippet:
            question += f'Message preview: "{snippet[:200]}". '
        question += (
            "Recommend one of: "
            "(1) respond urgently, "
            "(2) respond normally, "
            "(3) delegate to team member, "
            "(4) schedule for later."
        )

    debate_id = f"inbox-triage-{uuid4().hex[:12]}"
    config_metadata = {
        "source": "unified_inbox",
        "tenant_id": tenant_id,
        "message_id": getattr(message, "id", ""),
        "priority_tier": priority_tier,
    }
    if metadata:
        config_metadata.update(metadata)

    config = DebateConfig(
        question=question,
        debate_format="light",
        debate_id=debate_id,
        metadata=config_metadata,
    )

    try:
        started = time.monotonic()
        arena = factory.create_arena(config)
        result = await arena.run()
        latency_seconds = time.monotonic() - started

        final_answer = getattr(result, "final_answer", None) or ""
        consensus_reached = getattr(result, "consensus_reached", False)
        confidence = getattr(result, "confidence", 0.0)

        logger.info(
            "Inbox triage debate %s completed: consensus=%s confidence=%.2f",
            debate_id,
            consensus_reached,
            confidence,
        )

        return {
            "debate_id": debate_id,
            "final_answer": final_answer,
            "consensus_reached": consensus_reached,
            "confidence": confidence,
            "latency_seconds": latency_seconds,
        }
    except (ValueError, TypeError, RuntimeError, OSError) as e:
        logger.warning("Inbox triage debate failed for %s: %s", debate_id, e)
        return {
            "debate_id": debate_id,
            "final_answer": "",
            "consensus_reached": False,
            "confidence": 0.0,
            "latency_seconds": 0.0,
            "error": "Debate creation failed",
        }
