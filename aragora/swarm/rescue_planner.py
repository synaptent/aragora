"""OpenRouter-backed RescuePlanner with typed next-action output.

Consumes session state, blocker evidence, PR truth, and rescue history
to propose bounded recovery actions. Returns schema-validated JSON that
the active supervisor can execute if policy allows.

The planner is read-only by default — it recommends actions, not executes.
Action execution is a separate policy-gated step.
"""

from __future__ import annotations

__all__ = ["ActionPlan", "RescueAction", "plan_rescue", "try_quarantine_override"]

import json
import logging
import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from aragora.config import get_api_key

logger = logging.getLogger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)


class RescueAction(str, Enum):
    """Bounded set of recovery actions the planner can recommend."""

    WAIT_FOR_CI = "wait_for_ci"
    SEND_FOLLOWUP = "send_followup"
    APPROVE_PROMPT = "approve_prompt"
    RESTART_FROM_STATE = "restart_from_state"
    REWRITE_ISSUE = "rewrite_issue"
    SPLIT_ISSUE = "split_issue"
    ESCALATE = "escalate"


@dataclass
class ActionPlan:
    """Schema-validated recovery recommendation."""

    action: str
    reason: str
    confidence: float = 0.0
    required_policy: str = ""
    proposed_prompt: str = ""
    expected_receipt: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Default model for rescue planning — frontier tier ($5/$25 per MTok)
_DEFAULT_MODEL = "anthropic/claude-opus-5"
_FALLBACK_MODEL = "deepseek/deepseek-v4-pro"

_SYSTEM_PROMPT = """\
You are a rescue planner for an autonomous software execution system.
Given a stuck or failed lane, recommend ONE bounded recovery action.

Return ONLY valid JSON with these exact fields:
{
  "action": "wait_for_ci|send_followup|approve_prompt|restart_from_state|rewrite_issue|split_issue|escalate",
  "reason": "brief explanation",
  "confidence": 0.0 to 1.0,
  "required_policy": "what permission is needed",
  "proposed_prompt": "exact text to send if action is send_followup"
}

Rules:
- Only recommend actions you are confident about (>0.5)
- If unsure, recommend "escalate"
- Keep proposed_prompt under 500 chars
- Do not recommend actions outside the allowed set
"""

_VALID_ACTIONS = frozenset(a.value for a in RescueAction)


def plan_rescue(
    *,
    session_summary: str = "",
    blocker_evidence: str = "",
    pr_state: str = "",
    rescue_history: str = "",
    lane_metadata: str = "",
    model: str | None = None,
    api_key: str | None = None,
) -> ActionPlan:
    """Call OpenRouter to classify a stuck lane and propose recovery.

    Returns an ActionPlan with the recommended next action. Falls back
    to ESCALATE if the LLM response is malformed or confidence is low.
    """
    context_parts = []
    if session_summary:
        context_parts.append(f"## Session Summary\n{session_summary}")
    if blocker_evidence:
        context_parts.append(f"## Blocker Evidence\n{blocker_evidence}")
    if pr_state:
        context_parts.append(f"## PR State\n{pr_state}")
    if rescue_history:
        context_parts.append(f"## Rescue History\n{rescue_history}")
    if lane_metadata:
        context_parts.append(f"## Lane Metadata\n{lane_metadata}")

    if not context_parts:
        return ActionPlan(
            action=RescueAction.ESCALATE.value,
            reason="No context provided for rescue planning.",
            confidence=0.0,
        )

    user_prompt = "\n\n".join(context_parts)
    resolved_key = api_key or get_api_key("OPENROUTER_API_KEY", required=False) or ""
    resolved_model = model or _DEFAULT_MODEL

    if not resolved_key:
        return ActionPlan(
            action=RescueAction.ESCALATE.value,
            reason="No OpenRouter API key available for rescue planning.",
            confidence=0.0,
        )

    try:
        raw = _call_openrouter(
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            model=resolved_model,
            api_key=resolved_key,
        )
        return _parse_action_plan(raw)
    except Exception as exc:
        logger.debug("RescuePlanner call failed: %s", exc)
        return ActionPlan(
            action=RescueAction.ESCALATE.value,
            reason=f"Rescue planning failed: {type(exc).__name__}",
            confidence=0.0,
        )


def _call_openrouter(
    *,
    system: str,
    user: str,
    model: str,
    api_key: str,
) -> str:
    """Make a single OpenRouter chat completion call."""
    import httpx

    response = httpx.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user[:4000]},
            ],
            # Opus 5 thinks by default and max_tokens covers thinking +
            # response, so keep headroom. `temperature` is omitted: it is
            # rejected with a 400 on Opus 4.7+ when set to a non-default value.
            "max_tokens": 4096,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        raise ValueError("No choices in OpenRouter response")
    return str(choices[0].get("message", {}).get("content", "")).strip()


def _parse_action_plan(raw: str) -> ActionPlan:
    """Parse and validate an ActionPlan from LLM output."""
    if not raw.strip():
        return ActionPlan(
            action=RescueAction.ESCALATE.value,
            reason="Empty response from rescue planner.",
            confidence=0.0,
        )

    # Try direct JSON parse first
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(raw)
        if not match:
            return ActionPlan(
                action=RescueAction.ESCALATE.value,
                reason="Could not parse JSON from rescue planner response.",
                confidence=0.0,
            )
        data = json.loads(match.group())

    if not isinstance(data, dict):
        return ActionPlan(
            action=RescueAction.ESCALATE.value,
            reason="Rescue planner returned non-object JSON.",
            confidence=0.0,
        )

    action = str(data.get("action", "")).strip().lower()
    if action not in _VALID_ACTIONS:
        action = RescueAction.ESCALATE.value

    confidence = 0.0
    try:
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0))))
    except (TypeError, ValueError):
        pass

    # Fail closed on low confidence
    if confidence < 0.3 and action != RescueAction.ESCALATE.value:
        return ActionPlan(
            action=RescueAction.ESCALATE.value,
            reason=f"Low confidence ({confidence:.2f}) on {action}; escalating.",
            confidence=confidence,
        )

    return ActionPlan(
        action=action,
        reason=str(data.get("reason", "")).strip()[:500],
        confidence=confidence,
        required_policy=str(data.get("required_policy", "")).strip()[:200],
        proposed_prompt=str(data.get("proposed_prompt", "")).strip()[:500],
        expected_receipt=str(data.get("expected_receipt", "")).strip()[:200],
    )


def try_quarantine_override(
    *,
    issue_number: int,
    issue_title: str,
    sanitization_reason: str,
    checks_failed: list[str],
    issue_body: str,
    sanitizer: Any,
) -> tuple[Any, str] | None:
    """Ask RescuePlanner if a sanitizer quarantine is a false positive.

    Returns (new_sanitization, new_body) if the override succeeded,
    or None if the quarantine should stand.
    """
    try:
        rescue = plan_rescue(
            session_summary=f"Issue #{issue_number}: {issue_title}",
            blocker_evidence=(
                f"Task sanitizer quarantined this issue: {sanitization_reason}. "
                f"Failed checks: {', '.join(checks_failed)}. "
                f"Is this a false positive? Should the issue be accepted for dispatch?"
            ),
            lane_metadata=issue_body[:500],
        )
        if rescue.confidence >= 0.7 and rescue.action in ("rewrite_issue", "send_followup"):
            logger.info(
                "rescue_planner_override issue=#%s action=%s confidence=%.2f reason=%s",
                issue_number,
                rescue.action,
                rescue.confidence,
                rescue.reason[:100],
            )
            from aragora.swarm.rescue_events import record_rescue

            record_rescue(
                "issue_rewrite",
                f"RescuePlanner overrode quarantine: {rescue.reason[:200]}",
                issue_number=issue_number,
                outcome="override_accepted",
            )
            override_body = rescue.proposed_prompt or issue_body
            new_sanitization = sanitizer.sanitize(issue_title, override_body)
            from aragora.swarm.task_sanitizer import SanitizationOutcome

            if new_sanitization.outcome not in {
                SanitizationOutcome.DROPPED,
                SanitizationOutcome.QUARANTINED,
            }:
                return new_sanitization, override_body
    except Exception:
        logger.debug("RescuePlanner quarantine override skipped", exc_info=True)
    return None
