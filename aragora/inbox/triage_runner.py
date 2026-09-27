"""
Inbox Triage Runner.

Main entry point for the trust wedge. Fetches unread Gmail messages,
runs adversarial debates on each, builds signed receipts, and routes
decisions to auto-approval or the CLI review queue.

Usage::

    from aragora.inbox.triage_runner import InboxTriageRunner

    runner = InboxTriageRunner()
    decisions = await runner.run_triage(batch_size=10, auto_approve=True)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
import uuid
from contextlib import contextmanager, nullcontext, suppress
from dataclasses import dataclass
from typing import Any

from aragora.config.secrets import get_secret_presence, is_secret_presence_available
from aragora.inbox.auto_approval import AutoApprovalPolicy
from aragora.inbox.trust_wedge import (
    ActionIntent,
    AllowedAction,
    InboxWedgeAction,
    ReceiptState,
    TriageDecision,
    compute_content_hash,
    get_inbox_trust_wedge_service,
)
from aragora.inbox.triage_diagnostics import (
    DiagnosticSeverity,
    TriageRunDiagnostics,
    record_triage_diagnostic,
)
from aragora.agents.semantic_extraction import ExtractionProvider, extract_json_object_llm_first

logger = logging.getLogger(__name__)


def _has_api_key(*names: str) -> bool:
    """Return API-key availability without exposing secret values."""
    return any(is_secret_presence_available(get_secret_presence(name)) for name in names)


_SUPPORTED_TRIAGE_PROFILES = {"baseline", "staged_v1"}
_DEFAULT_TRIAGE_PROFILE = "staged_v1"
_FAST_TIER_CONFIDENCE_THRESHOLD = 0.85
_FAST_TIER_TIMEOUT_SECONDS = 8.0
_ESCALATED_TIER_ROUNDS = 1
_TRIAGE_DEBATE_TIMEOUT_SECONDS = 15
_TRIAGE_ROUND_TIMEOUT_SECONDS = 10
_TRIAGE_DEBATE_ROUNDS_TIMEOUT_SECONDS = 12
_TRIAGE_MAX_AGENTS = 2
_HIGH_RISK_ACTIONS = {InboxWedgeAction.LABEL, InboxWedgeAction.STAR}
_DEGRADED_DIAGNOSTIC_SEVERITIES = {
    DiagnosticSeverity.BLOCKING.value,
    DiagnosticSeverity.DEGRADED.value,
}
_FAST_TIER_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_FAST_TRIAGE_PROVIDERS = (
    ExtractionProvider(
        agent_type="gemini",
        model="gemini-2.0-flash",
        role="analyst",
        name="triage-fast",
        env_vars=("GEMINI_API_KEY", "GOOGLE_API_KEY"),
        disable_web_search=True,
    ),
    ExtractionProvider(
        agent_type="openai-api",
        model="gpt-5.4",
        role="analyst",
        name="triage-fast",
        env_vars=("OPENAI_API_KEY",),
        disable_web_search=True,
    ),
    ExtractionProvider(
        agent_type="anthropic-api",
        model="claude-haiku-4-5-20251001",
        role="analyst",
        name="triage-fast",
        env_vars=("ANTHROPIC_API_KEY",),
        disable_web_search=True,
    ),
    ExtractionProvider(
        agent_type="openrouter",
        model="deepseek/deepseek-v4-pro",
        role="analyst",
        name="triage-fast",
        env_vars=("OPENROUTER_API_KEY",),
    ),
)

_ACTION_PATTERNS = {
    AllowedAction.ARCHIVE: re.compile(r"\barchiv(?:e|ed|ing)\b", re.IGNORECASE),
    AllowedAction.STAR: re.compile(r"\bstarr?(?:ed|ing)?\b", re.IGNORECASE),
    AllowedAction.LABEL: re.compile(r"\blabell?(?:ed|ing)?\b", re.IGNORECASE),
    AllowedAction.IGNORE: re.compile(r"\bignor(?:e|ed|ing)?\b", re.IGNORECASE),
}
_DECISION_LINE_PATTERNS = [
    re.compile(
        r"(?im)^\s*(?:#+\s*)?"
        r"(?:proposal|recommended action|recommendation|action|final action)\s*:\s*"
        r"(?:\*\*|__)?(archive|star|label|ignore)(?:\*\*|__)?\b"
    ),
]


@dataclass(frozen=True)
class _NormalizedDebateOutcome:
    final_action: InboxWedgeAction
    confidence: float
    consensus_reached: bool
    dissent_summary: str
    rationale: str
    debate_id: str
    status: str
    parse_failed: bool


def _result_field(debate_result: Any, field: str, default: Any = None) -> Any:
    if hasattr(debate_result, field):
        return getattr(debate_result, field, default)
    if isinstance(debate_result, dict):
        return debate_result.get(field, default)
    return default


def _result_metadata(debate_result: Any) -> dict[str, Any]:
    metadata = _result_field(debate_result, "metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _result_rationale(debate_result: Any) -> str:
    value = _result_field(debate_result, "final_answer", "")
    return str(value or "")


def _result_confidence(debate_result: Any) -> float:
    candidates = [
        _result_field(debate_result, "confidence", None),
        _result_metadata(debate_result).get("consensus_confidence"),
        _result_metadata(debate_result).get("confidence"),
    ]
    for candidate in candidates:
        try:
            if candidate is None:
                continue
            return max(0.0, min(1.0, float(candidate)))
        except (TypeError, ValueError):
            continue
    return 0.0


def _result_consensus_reached(debate_result: Any, rationale: str) -> bool:
    raw_value = _result_field(debate_result, "consensus_reached", None)
    if raw_value is None:
        return bool(rationale.strip())
    if isinstance(raw_value, str):
        normalized = raw_value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
        return False
    return bool(raw_value)


def _result_debate_id(debate_result: Any) -> str:
    debate_id = _result_field(debate_result, "debate_id", None)
    if debate_id:
        return str(debate_id)
    result_id = _result_field(debate_result, "id", None)
    if result_id:
        return str(result_id)
    return f"triage-{uuid.uuid4().hex[:12]}"


def _result_dissenting_views(debate_result: Any) -> list[str]:
    views = _result_field(debate_result, "dissenting_views", [])
    if not isinstance(views, list):
        return []
    return [str(view).strip() for view in views if str(view).strip()]


def _result_status(debate_result: Any) -> str:
    candidates = [
        _result_field(debate_result, "status", None),
        _result_metadata(debate_result).get("status"),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        text = str(candidate).strip().lower()
        if text:
            return text
    return ""


def _extract_fast_tier_json(raw_text: str) -> dict[str, Any] | None:
    text = str(raw_text or "").strip()
    if not text:
        return None

    match = _FAST_TIER_JSON_BLOCK_RE.search(text)
    if match:
        text = match.group(1).strip()
    else:
        brace_match = re.search(r"(\{.*\})", text, re.DOTALL)
        if brace_match:
            text = brace_match.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _build_fast_tier_prompt(*, sender: str, subject: str, body: str) -> str:
    return (
        "You are an executive inbox assistant for a startup founder/CEO. "
        "Your job is to make a genuinely intelligent triage decision about this email — "
        "not pattern-match on keywords, but actually reason about whether this message "
        "matters to someone running a company.\n\n"
        "Think about:\n"
        "- Is this from a real person who knows the recipient, or a mass sender?\n"
        "- Could ignoring this email cost money, damage a relationship, or miss an opportunity?\n"
        "- Is this a security/account alert that needs attention (password changes, login alerts, "
        "phone number changes, billing issues)?\n"
        "- Is this a time-sensitive request from a colleague, investor, customer, or partner?\n"
        "- Or is this genuinely just noise — newsletters, promotions, automated notifications "
        "that have no actionable content?\n\n"
        "Actions:\n"
        "- **star**: Important and needs the founder's attention. Personal messages from known "
        "contacts, investor updates, customer escalations, security alerts, legal notices, "
        "time-sensitive requests.\n"
        "- **archive**: Safe to clear. Marketing, newsletters, promotions, automated "
        "notifications with no action required, social media digests, mass emails.\n"
        "- **label**: Useful reference but not urgent. Receipts, shipping notifications, "
        "subscription confirmations, informational updates from tools/services.\n"
        "- **ignore**: Spam, phishing, completely irrelevant.\n\n"
        "Confidence should reflect YOUR genuine uncertainty, not a formula:\n"
        "- High (0.85-1.0): You are very sure this action is correct.\n"
        "- Medium (0.5-0.84): Reasonable guess but you could be wrong.\n"
        "- Low (below 0.5): Genuinely uncertain — this might need human review.\n\n"
        'Return ONLY valid JSON: {"action": "...", "confidence": 0.XX, "rationale": "..."}\n'
        "Rationale must be under 80 words.\n\n"
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"Body: {body[:2000]}\n"
    )


def _normalize_fast_tier_payload(parsed: dict[str, Any]) -> dict[str, Any] | None:
    action = str(parsed.get("action", "")).strip().lower()
    if action not in {member.value for member in AllowedAction}:
        return None

    try:
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "action": action,
        "confidence": confidence,
        "rationale": str(parsed.get("rationale", "")).strip(),
    }


def _normalize_triage_profile(profile: str | None) -> str:
    normalized = str(profile or _DEFAULT_TRIAGE_PROFILE).strip().lower()
    if normalized in _SUPPORTED_TRIAGE_PROFILES:
        return normalized
    return _DEFAULT_TRIAGE_PROFILE


def _result_triage_execution_metadata(debate_result: Any) -> dict[str, Any]:
    metadata = _result_metadata(debate_result)
    execution = metadata.get("triage_execution")
    return dict(execution) if isinstance(execution, dict) else {}


def _attach_triage_execution_metadata(
    debate_result: Any,
    *,
    execution_tier: str,
    escalation_reasons: list[str] | None = None,
    profile: str | None = None,
) -> Any:
    execution = _result_triage_execution_metadata(debate_result)
    execution["execution_tier"] = execution_tier
    execution["escalation_reasons"] = list(escalation_reasons or [])
    if profile:
        execution["profile"] = profile

    if isinstance(debate_result, dict):
        metadata = debate_result.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
            debate_result["metadata"] = metadata
        metadata["triage_execution"] = execution
        return debate_result

    metadata = dict(_result_metadata(debate_result))
    metadata["triage_execution"] = execution
    try:
        setattr(debate_result, "metadata", metadata)
    except (AttributeError, TypeError):
        pass
    return debate_result


def _is_blocked_status(status: str) -> bool:
    return status in {
        "blocked",
        "error",
        "failed",
        "insufficient_participation",
        "runtime_error",
        "timeout",
    }


def _parse_action_from_rationale(rationale: str) -> tuple[InboxWedgeAction, bool]:
    normalized = rationale.strip().lower()
    if not normalized:
        return InboxWedgeAction.IGNORE, True

    for pattern in _DECISION_LINE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return InboxWedgeAction.parse(match.group(1)), False

    matched_actions = [
        action for action, pattern in _ACTION_PATTERNS.items() if pattern.search(normalized)
    ]
    if len(matched_actions) == 1:
        return InboxWedgeAction.parse(matched_actions[0]), False
    return InboxWedgeAction.IGNORE, True


def _normalize_debate_outcome(debate_result: Any) -> _NormalizedDebateOutcome:
    rationale = _result_rationale(debate_result)
    confidence = _result_confidence(debate_result)
    consensus_reached = _result_consensus_reached(debate_result, rationale)
    debate_id = _result_debate_id(debate_result)
    dissenting_views = _result_dissenting_views(debate_result)
    status = _result_status(debate_result)
    final_action, parse_failed = _parse_action_from_rationale(rationale)

    reasons: list[str] = []
    if not consensus_reached:
        reasons.append("No consensus reached; manual review required.")
    if status == "insufficient_participation":
        reasons.append(
            "Debate quorum failed; showing a blocked recommendation pending human review."
        )
    elif _is_blocked_status(status):
        reasons.append(f"Debate ended in {status.replace('_', ' ')}; manual review required.")
    if parse_failed:
        if rationale.strip():
            reasons.append(
                "Could not map the debate answer to a single inbox action; showing a blocked recommendation."
            )
        else:
            reasons.append(
                "Debate returned no actionable final answer; showing a blocked recommendation."
            )
    if confidence <= 0.0 and not rationale.strip():
        reasons.append("No confident recommendation was produced.")
    if dissenting_views:
        reasons.append(f"Dissent: {'; '.join(dissenting_views[:3])}")

    return _NormalizedDebateOutcome(
        final_action=final_action,
        confidence=confidence,
        consensus_reached=consensus_reached,
        dissent_summary=" ".join(reasons).strip(),
        rationale=rationale,
        debate_id=debate_id,
        status=status,
        parse_failed=parse_failed,
    )


def _create_triage_agents(*, max_agents: int | None = None) -> list[Any]:
    """Create agents for triage debates.

    Prefers cheap, fast models:
      - Anthropic Haiku as proposer
      - OpenRouter/DeepSeek as critic
    Falls back to OpenAI if keys are missing.
    """
    from aragora.agents.base import create_agent

    agents: list[Any] = []
    providers_used: set[str] = set()

    def _append_agent(
        provider: str,
        *,
        name: str,
        role: str,
        model: str | None = None,
    ) -> None:
        try:
            kwargs: dict[str, Any] = {
                "name": name,
                "role": role,
            }
            if model is not None:
                kwargs["model"] = model
            agents.append(create_agent(provider, **kwargs))
            providers_used.add(provider)
        except (ImportError, RuntimeError, ValueError, OSError):
            logger.debug("Triage agent unavailable: provider=%s role=%s", provider, role)

    if _has_api_key("OPENAI_API_KEY"):
        _append_agent(
            "openai-api",
            name="triage-proposer",
            role="proposer",
            model="gpt-5.4",
        )
    elif _has_api_key("ANTHROPIC_API_KEY"):
        _append_agent(
            "anthropic-api",
            name="triage-proposer",
            role="proposer",
            model="claude-haiku-4-5-20251001",
        )
    elif _has_api_key("OPENROUTER_API_KEY") and "openrouter" not in providers_used:
        _append_agent(
            "openrouter",
            name="triage-proposer",
            role="proposer",
            model="anthropic/claude-haiku-4-5-20251001",
        )

    if _has_api_key("OPENROUTER_API_KEY"):
        _append_agent(
            "openrouter",
            name="triage-critic",
            role="critic",
            model="deepseek/deepseek-v4-pro",
        )
    elif _has_api_key("OPENAI_API_KEY"):
        _append_agent(
            "openai-api",
            name="triage-critic",
            role="critic",
            model="gpt-5.4",
        )
    elif _has_api_key("ANTHROPIC_API_KEY"):
        _append_agent(
            "anthropic-api",
            name="triage-critic",
            role="critic",
            model="claude-haiku-4-5-20251001",
        )

    if _has_api_key("ANTHROPIC_API_KEY") and "anthropic-api" not in providers_used:
        _append_agent(
            "anthropic-api",
            name="triage-reviewer",
            role="synthesizer",
            model="claude-haiku-4-5-20251001",
        )
    elif _has_api_key("OPENAI_API_KEY") and len(agents) < 3:
        _append_agent(
            "openai-api",
            name="triage-reviewer",
            role="synthesizer",
            model="gpt-5.4",
        )
    elif _has_api_key("OPENROUTER_API_KEY") and len(agents) < 3:
        # Use a different model family for heterogeneous consensus
        _append_agent(
            "openrouter",
            name="triage-reviewer",
            role="synthesizer",
            model="google/gemini-2.0-flash-001",
        )

    if max_agents is not None:
        return agents[:max_agents]
    return agents


def _attach_display_metadata(intent: ActionIntent, msg: dict[str, Any], body: str) -> None:
    """Attach email display metadata for CLI summaries and receipt auditability."""
    subject = msg.get("subject", "(no subject)")
    sender = msg.get("from_address", msg.get("sender", "(unknown)"))
    snippet = msg.get("snippet", body[:120])
    # Set dataclass fields (survive replace() for receipt persistence)
    object.__setattr__(intent, "email_subject", str(subject))
    object.__setattr__(intent, "email_from", str(sender))
    object.__setattr__(intent, "email_snippet", str(snippet)[:200])
    # Keep private attrs for backward compat with CLI display code
    intent._subject = subject  # type: ignore[attr-defined]
    intent._sender = sender  # type: ignore[attr-defined]
    intent._snippet = snippet  # type: ignore[attr-defined]


@contextmanager
def _set_env_if_missing(key: str, value: str):
    """Temporarily set an environment variable only when unset."""
    existed = key in os.environ
    if not existed:
        os.environ[key] = value
    try:
        yield
    finally:
        if not existed:
            os.environ.pop(key, None)


class InboxTriageRunner:
    """Orchestrates the full inbox triage flow.

    Parameters
    ----------
    gmail_connector:
        An instance of the Gmail connector (or compatible mock).
        Must support ``list_messages``, ``get_message``, and label
        operations (``archive_message``, ``star_message``, ``add_label``).
    auto_approval_policy:
        Policy governing auto-approval. A default policy is created
        if none is provided.
    """

    def __init__(
        self,
        gmail_connector: Any | None = None,
        auto_approval_policy: AutoApprovalPolicy | None = None,
        wedge_service: Any | None = None,
        diagnostics: TriageRunDiagnostics | None = None,
        profile: str | None = None,
    ) -> None:
        self._gmail = gmail_connector
        self._policy = auto_approval_policy or AutoApprovalPolicy()
        self._wedge_service = wedge_service or get_inbox_trust_wedge_service()
        self._diagnostics = diagnostics
        self._profile = _normalize_triage_profile(profile or os.getenv("ARAGORA_TRIAGE_PROFILE"))
        self._triaged: list[TriageDecision] = []
        self._next_page_token: str | None = None

    @property
    def triaged(self) -> list[TriageDecision]:
        """Decisions produced by the most recent ``run_triage`` call."""
        return list(self._triaged)

    @property
    def next_page_token(self) -> str | None:
        """Pagination token for the next unread-message page, if available."""
        return self._next_page_token

    async def run_triage(
        self,
        batch_size: int = 10,
        auto_approve: bool = False,
        page_token: str | None = None,
    ) -> list[TriageDecision]:
        """Run the full triage pipeline.

        1. Fetch unread Gmail messages (up to *batch_size*).
        2. For each message, run an adversarial debate.
        3. Build an ``ActionIntent`` from the debate result.
        4. Create a ``TriageDecision`` with receipt.
        5. If *auto_approve* and the policy allows, auto-approve.
        6. Otherwise queue for CLI review.

        Returns the list of ``TriageDecision`` objects. Those not
        auto-approved remain in CREATED state for later review.
        """
        messages = await self._fetch_messages(batch_size, page_token=page_token)
        logger.info("Fetched %d messages for triage", len(messages))

        decisions: list[TriageDecision] = []

        for msg in messages:
            try:
                decision = await self._triage_message(
                    msg,
                    auto_approve=auto_approve,
                )
                if auto_approve and decision.receipt_state == ReceiptState.APPROVED.value:
                    await self._execute_action(decision)
                decisions.append(decision)
            except (RuntimeError, OSError, ValueError, TypeError) as exc:
                message_id = msg.get("id", "?")
                logger.error(
                    "Triage failed for message %s: %s",
                    message_id,
                    exc,
                )
                blocked_decision = TriageDecision(
                    final_action=InboxWedgeAction.IGNORE,
                    confidence=0.0,
                    dissent_summary=f"Triage dispatch error: {type(exc).__name__}",
                    blocked_by_policy=True,
                    receipt_state="blocked",
                )
                decisions.append(blocked_decision)

        self._triaged = decisions
        auto_count = sum(1 for d in decisions if d.receipt_state == ReceiptState.APPROVED.value)
        logger.info(
            "Triage complete: %d decisions (%d auto-approved, %d for review)",
            len(decisions),
            auto_count,
            len(decisions) - auto_count,
        )
        return decisions

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_messages(
        self,
        batch_size: int,
        *,
        page_token: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch unread messages from Gmail.

        Returns a list of message dicts with at least ``id``, ``subject``,
        ``sender``, ``snippet``, and ``body`` keys.
        """
        if self._gmail is None:
            logger.warning("No Gmail connector configured; returning empty batch")
            return []

        try:
            message_ids, next_page_token = await self._gmail.list_messages(
                query="in:inbox is:unread",
                max_results=batch_size,
                page_token=page_token,
            )
            self._next_page_token = str(next_page_token) if next_page_token else None
        except (RuntimeError, OSError, ConnectionError) as exc:
            logger.error("Failed to list messages: %s", exc)
            self._next_page_token = None
            return []

        messages: list[dict[str, Any]] = []
        for mid in message_ids[:batch_size]:
            try:
                msg = await self._gmail.get_message(mid)
                if isinstance(msg, dict):
                    messages.append(msg)
                elif hasattr(msg, "to_dict"):
                    messages.append(msg.to_dict())
                else:
                    messages.append({"id": mid, "body": str(msg)})
            except (RuntimeError, OSError, ValueError) as exc:
                logger.warning("Failed to fetch message %s: %s", mid, exc)

        return messages

    async def _triage_message(
        self,
        msg: dict[str, Any],
        *,
        auto_approve: bool = False,
    ) -> TriageDecision:
        """Run debate and build a TriageDecision for a single message."""
        started = time.perf_counter()
        message_id = msg.get("id", str(uuid.uuid4()))
        body = msg.get("body_text", msg.get("body", msg.get("snippet", "")))
        content_hash = compute_content_hash(body)
        scope = self._diagnostics.message_scope(message_id) if self._diagnostics else nullcontext()

        with scope:
            debate_result = await self._run_debate(msg)
            normalized = _normalize_debate_outcome(debate_result)
            execution_metadata = _result_triage_execution_metadata(debate_result)
            execution_tier = str(execution_metadata.get("execution_tier", "baseline"))
            escalation_reasons = [
                str(reason)
                for reason in execution_metadata.get("escalation_reasons", [])
                if str(reason).strip()
            ]
            diagnostics_summary = (
                self._diagnostics.get_message_summary(message_id)
                if self._diagnostics
                else {"total": 0}
            )
            final_tier_summary = (
                self._diagnostics.get_message_summary(message_id, tier=execution_tier)
                if self._diagnostics
                else {
                    DiagnosticSeverity.BLOCKING.value: 0,
                    DiagnosticSeverity.DEGRADED.value: 0,
                    DiagnosticSeverity.DIAGNOSTIC.value: 0,
                    "total": 0,
                }
            )
            degraded_final_diagnostics = any(
                final_tier_summary.get(severity, 0) > 0
                for severity in _DEGRADED_DIAGNOSTIC_SEVERITIES
            )
        provider = (
            getattr(self._gmail, "connector_id", "gmail") if self._gmail is not None else "gmail"
        )
        user_id = getattr(self._gmail, "user_id", "me") if self._gmail is not None else "me"

        intent = ActionIntent(
            provider=provider,
            message_id=message_id,
            action=normalized.final_action,
            content_hash=content_hash,
            synthesized_rationale=normalized.rationale[:500],
            confidence=normalized.confidence,
            provider_route="direct",
            debate_id=normalized.debate_id,
            user_id=user_id,
        )
        _attach_display_metadata(intent, msg, body)

        decision = TriageDecision(
            final_action=normalized.final_action,
            confidence=normalized.confidence,
            dissent_summary=normalized.dissent_summary,
            auto_approval_eligible=False,
            provider_route="direct",
            intent=intent,
            blocked_by_policy=bool(normalized.dissent_summary) or degraded_final_diagnostics,
            execution_tier=execution_tier,
            escalation_reasons=escalation_reasons,
            suppressed_diagnostics_count=int(diagnostics_summary.get("total", 0)),
        )

        should_auto_approve = auto_approve and self._policy.can_auto_approve(decision)
        envelope = self._wedge_service.create_receipt(
            intent,
            decision,
            auto_approve=should_auto_approve,
        )
        decision = envelope.decision
        decision.intent = envelope.intent
        decision.receipt_id = envelope.receipt.receipt_id
        decision.receipt_state = envelope.receipt.state.value
        decision.provider_route = envelope.provider_route
        decision.label_id = envelope.intent.label_id or decision.label_id
        decision.execution_tier = execution_tier
        decision.escalation_reasons = escalation_reasons
        decision.suppressed_diagnostics_count = int(diagnostics_summary.get("total", 0))
        decision.blocked_by_policy = bool(normalized.dissent_summary) or degraded_final_diagnostics
        decision.latency_seconds = time.perf_counter() - started
        _attach_display_metadata(decision.intent, msg, body)

        return decision

    async def _run_debate(self, msg: dict[str, Any]) -> Any:
        message_id = str(msg.get("id", ""))
        if self._profile == "staged_v1":
            fast_task = asyncio.create_task(self._run_fast_tier_once(msg))
            try:
                fast_result = await asyncio.wait_for(
                    fast_task,
                    timeout=_FAST_TIER_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                fast_task.cancel()
                with suppress(asyncio.CancelledError):
                    await fast_task
                record_triage_diagnostic(
                    code="fast_tier_timeout",
                    severity=DiagnosticSeverity.BLOCKING,
                    logger_name=__name__,
                    summary="Fast-tier triage debate exceeded its time budget; returning blocked result.",
                    details=f"timeout_seconds={_FAST_TIER_TIMEOUT_SECONDS}",
                    message_id=message_id or None,
                    tier="fast",
                )
                fast_result = {
                    "final_answer": "",
                    "confidence": 0.0,
                    "debate_id": f"timeout-{uuid.uuid4().hex[:8]}",
                    "status": "timeout",
                }
            fast_result = _attach_triage_execution_metadata(
                fast_result,
                execution_tier="fast",
                escalation_reasons=[],
                profile=self._profile,
            )
            fast_outcome = _normalize_debate_outcome(fast_result)
            fast_summary = (
                self._diagnostics.get_message_summary(message_id, tier="fast")
                if self._diagnostics
                else {
                    DiagnosticSeverity.BLOCKING.value: 0,
                    DiagnosticSeverity.DEGRADED.value: 0,
                    DiagnosticSeverity.DIAGNOSTIC.value: 0,
                    "total": 0,
                }
            )
            truthful_stop_reasons: list[str] = []
            if fast_outcome.status == "timeout":
                truthful_stop_reasons.append("fast_timeout")
            elif _is_blocked_status(fast_outcome.status):
                truthful_stop_reasons.append("blocked_status")
            if not fast_outcome.consensus_reached:
                truthful_stop_reasons.append("no_consensus")
            if fast_outcome.parse_failed:
                truthful_stop_reasons.append("parse_failed")

            if truthful_stop_reasons:
                record_triage_diagnostic(
                    code="fast_tier_truthful_stop",
                    severity=DiagnosticSeverity.BLOCKING,
                    logger_name=__name__,
                    summary="Fast-tier triage result was non-decisive; returning blocked result.",
                    details=", ".join(truthful_stop_reasons),
                    message_id=message_id or None,
                    tier="fast",
                )
                return _attach_triage_execution_metadata(
                    fast_result,
                    execution_tier="fast",
                    escalation_reasons=truthful_stop_reasons,
                    profile=self._profile,
                )

            escalation_reasons: list[str] = []
            if fast_outcome.confidence < _FAST_TIER_CONFIDENCE_THRESHOLD:
                escalation_reasons.append("low_confidence")
            if fast_outcome.final_action in _HIGH_RISK_ACTIONS:
                escalation_reasons.append("high_risk_action")
            if any(
                fast_summary.get(severity, 0) > 0 for severity in _DEGRADED_DIAGNOSTIC_SEVERITIES
            ):
                escalation_reasons.append("diagnostic_degraded")

            if not escalation_reasons:
                return fast_result

            record_triage_diagnostic(
                code="fast_tier_escalation",
                severity=DiagnosticSeverity.DIAGNOSTIC,
                logger_name=__name__,
                summary="Escalating triage decision to full review tier.",
                details=", ".join(escalation_reasons),
                message_id=message_id or None,
                tier="fast",
            )

            escalated_result = await self._run_debate_once(
                msg,
                tier="escalated",
                rounds=_ESCALATED_TIER_ROUNDS,
                max_agents=None,
            )
            return _attach_triage_execution_metadata(
                escalated_result,
                execution_tier="escalated",
                escalation_reasons=escalation_reasons,
                profile=self._profile,
            )

        baseline_result = await self._run_debate_once(
            msg,
            tier="baseline",
            rounds=1,
            max_agents=_TRIAGE_MAX_AGENTS,
        )
        return _attach_triage_execution_metadata(
            baseline_result,
            execution_tier="baseline",
            escalation_reasons=[],
            profile=self._profile,
        )

    async def _run_fast_tier_once(self, msg: dict[str, Any]) -> Any:
        subject = msg.get("subject", "(no subject)")
        sender = msg.get("from_address", msg.get("sender", "(unknown)"))
        body = msg.get("body_text", msg.get("body", msg.get("snippet", "")))
        prompt = _build_fast_tier_prompt(sender=sender, subject=subject, body=body)
        extraction = await extract_json_object_llm_first(
            prompt,
            providers=_FAST_TRIAGE_PROVIDERS,
            normalizer=_normalize_fast_tier_payload,
            timeout=_FAST_TIER_TIMEOUT_SECONDS,
            logger=logger,
            context="fast triage",
        )
        if extraction.value is None:
            if extraction.error == "no_available_providers":
                logger.warning(
                    "No fast triage provider available; returning blocked fast-tier result"
                )
                return {
                    "final_answer": "",
                    "confidence": 0.0,
                    "debate_id": f"fast-no-agent-{uuid.uuid4().hex[:8]}",
                    "status": "insufficient_participation",
                }
            logger.warning(
                "Fast triage semantic extraction failed; source=%s error=%s",
                extraction.source,
                extraction.error,
            )
            return {
                "final_answer": "",
                "confidence": 0.0,
                "debate_id": f"fast-parse-{uuid.uuid4().hex[:8]}",
                "status": "failed",
            }

        parsed = extraction.value
        action = str(parsed["action"]).strip()
        confidence = float(parsed["confidence"])
        rationale = str(parsed["rationale"]).strip()
        final_answer = f"{action}: {rationale}" if rationale else action
        provider = extraction.provider.agent_type if extraction.provider else extraction.source
        return {
            "final_answer": final_answer,
            "confidence": confidence,
            "consensus_reached": True,
            "debate_id": f"fast-{uuid.uuid4().hex[:8]}",
            "status": "completed",
            "metadata": {
                "triage_fast_provider": str(provider),
            },
        }

    async def _run_debate_once(
        self,
        msg: dict[str, Any],
        *,
        tier: str,
        rounds: int,
        max_agents: int | None,
    ) -> Any:
        """Run an adversarial debate on a message.

        Attempts to use the Arena with API agents. When debate infrastructure
        is unavailable or quorum fails, returns a blocked result rather than a
        silent IGNORE recommendation.
        """
        subject = msg.get("subject", "(no subject)")
        sender = msg.get("from_address", msg.get("sender", "(unknown)"))
        body = msg.get("body_text", msg.get("body", msg.get("snippet", "")))
        question = (
            "You are debating the correct triage action for an email in a startup "
            "founder's inbox. Think about whether this message genuinely matters — "
            "could ignoring it cost money, damage a relationship, miss an opportunity, "
            "or compromise security? Or is it just noise?\n\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"Body: {body[:2000]}\n\n"
            "Actions: star (important, needs attention), archive (safe to clear), "
            "label (useful reference, not urgent), ignore (spam/irrelevant).\n\n"
            "Your final answer MUST begin with the action word "
            "(archive, star, label, or ignore) followed by your reasoning."
        )
        tier_scope = self._diagnostics.tier_scope(tier) if self._diagnostics else nullcontext()

        with tier_scope:
            try:
                from aragora.core import Environment
                from aragora.debate.orchestrator import Arena
                from aragora.debate.protocol import DebateProtocol

                env = Environment(task=question)
                protocol = DebateProtocol(
                    rounds=rounds,
                    consensus="majority",
                    enable_research=False,
                    convergence_detection=False,
                    vote_grouping=False,
                    enable_trickster=False,
                    role_rotation=False,
                    role_matching=False,
                    enable_calibration=False,
                    enable_rhetorical_observer=False,
                    enable_evolution=False,
                    verify_claims_during_consensus=False,
                    enable_evidence_weighting=False,
                    enable_breakpoints=False,
                    timeout_seconds=_TRIAGE_DEBATE_TIMEOUT_SECONDS,
                    round_timeout_seconds=_TRIAGE_ROUND_TIMEOUT_SECONDS,
                    debate_rounds_timeout_seconds=_TRIAGE_DEBATE_ROUNDS_TIMEOUT_SECONDS,
                )

                record_triage_diagnostic(
                    code="research_disabled_for_profile",
                    severity=DiagnosticSeverity.DIAGNOSTIC,
                    logger_name=__name__,
                    summary="Research is disabled for inbox triage execution.",
                    details=f"profile={self._profile} tier={tier}",
                    once_key=f"research_disabled:{self._profile}:{tier}",
                    tier=tier,
                )

                effective_max = max_agents if max_agents is not None else _TRIAGE_MAX_AGENTS
                agents = _create_triage_agents(max_agents=effective_max)

                if len(agents) < 2:
                    logger.warning(
                        "%d triage agents available (need 2); returning blocked triage result",
                        len(agents),
                    )
                    return {
                        "final_answer": "",
                        "confidence": 0.0,
                        "debate_id": f"no-agents-{uuid.uuid4().hex[:8]}",
                        "status": "insufficient_participation",
                    }
                with _set_env_if_missing("ARAGORA_DISABLE_TRENDING", "true"):
                    arena = Arena(
                        env,
                        agents=agents,
                        protocol=protocol,
                        enable_introspection=False,
                        enable_belief_guidance=False,
                        enable_knowledge_retrieval=False,
                        use_rlm_limiter=False,
                        disable_post_debate_pipeline=True,
                    )
                    result = await arena.run()
                    debate_scope = (
                        self._diagnostics.debate_scope(_result_debate_id(result))
                        if self._diagnostics
                        else nullcontext()
                    )
                    with debate_scope:
                        return result
            except ImportError:
                logger.debug("Debate engine not available; returning blocked triage result")
                return {
                    "final_answer": "",
                    "confidence": 0.0,
                    "debate_id": f"stub-{uuid.uuid4().hex[:8]}",
                    "status": "insufficient_participation",
                }
            except (RuntimeError, OSError, ValueError, TypeError) as exc:
                logger.warning("Debate failed (%s), returning blocked triage result", exc)
                record_triage_diagnostic(
                    code="debate_runtime_error",
                    severity=DiagnosticSeverity.BLOCKING,
                    logger_name=__name__,
                    summary="Escalated triage debate failed; returning blocked result.",
                    details=str(exc)[:200],
                    message_id=str(msg.get("id", "") or "") or None,
                    tier=tier,
                )
                return {
                    "final_answer": "",
                    "confidence": 0.0,
                    "debate_id": f"err-{uuid.uuid4().hex[:8]}",
                    "status": "runtime_error",
                    "metadata": {
                        "debate_error": str(exc)[:200],
                    },
                }

    async def _execute_action(self, decision: TriageDecision) -> None:
        """Execute an approved triage action via the Gmail connector.

        Does NOT wire into the execution safety gate -- that integration
        is handled separately.
        """
        if not decision.receipt_id:
            logger.warning("No persisted receipt on decision; skipping execution")
            return

        try:
            await self._wedge_service.execute_receipt(decision.receipt_id)
            decision.receipt_state = ReceiptState.EXECUTED.value
            logger.info(
                "Executed triage action via receipt %s: %s",
                decision.receipt_id,
                decision.final_action,
            )
        except (RuntimeError, OSError, ConnectionError, ValueError) as exc:
            logger.error(
                "Failed to execute receipt %s: %s",
                decision.receipt_id,
                exc,
            )


__all__ = ["InboxTriageRunner"]
