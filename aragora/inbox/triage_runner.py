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

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

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

logger = logging.getLogger(__name__)

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
        r"(archive|star|label|ignore)\b"
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
    final_action, parse_failed = _parse_action_from_rationale(rationale)

    reasons: list[str] = []
    if not consensus_reached:
        reasons.append("No consensus reached; manual review required.")
    if parse_failed:
        if rationale.strip():
            reasons.append(
                "Could not map the debate answer to a single inbox action; fell back to ignore."
            )
        else:
            reasons.append("Debate returned no final answer; fell back to ignore.")
    if dissenting_views:
        reasons.append(f"Dissent: {'; '.join(dissenting_views[:3])}")

    return _NormalizedDebateOutcome(
        final_action=final_action,
        confidence=confidence,
        consensus_reached=consensus_reached,
        dissent_summary=" ".join(reasons).strip(),
        rationale=rationale,
        debate_id=debate_id,
    )


def _create_triage_agents() -> list[Any]:
    """Create the smallest useful remote debate for inbox triage."""
    import os

    from aragora.agents.base import create_agent

    agents: list[Any] = []

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            agents.append(
                create_agent(
                    "anthropic-api",
                    name="triage-proposer",
                    role="proposer",
                    model="claude-haiku-4-5-20251001",
                )
            )
        except (ImportError, RuntimeError, ValueError, OSError):
            logger.debug("Anthropic triage proposer unavailable", exc_info=True)

    if os.environ.get("OPENROUTER_API_KEY"):
        try:
            agents.append(
                create_agent(
                    "openrouter",
                    name="triage-critic",
                    role="critic",
                    model="deepseek/deepseek-chat",
                )
            )
        except (ImportError, RuntimeError, ValueError, OSError):
            logger.debug("OpenRouter triage critic unavailable", exc_info=True)

    if len(agents) < 2 and os.environ.get("OPENAI_API_KEY"):
        role = "critic" if agents else "proposer"
        try:
            agents.append(create_agent("openai-api", name=f"triage-{role}", role=role))
        except (ImportError, RuntimeError, ValueError, OSError):
            logger.debug("OpenAI triage fallback unavailable", exc_info=True)

    return agents


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
    ) -> None:
        self._gmail = gmail_connector
        self._policy = auto_approval_policy or AutoApprovalPolicy()
        self._wedge_service = wedge_service or get_inbox_trust_wedge_service()
        self._triaged: list[TriageDecision] = []

    @property
    def triaged(self) -> list[TriageDecision]:
        """Decisions produced by the most recent ``run_triage`` call."""
        return list(self._triaged)

    async def run_triage(
        self,
        batch_size: int = 10,
        auto_approve: bool = False,
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
        messages = await self._fetch_messages(batch_size)
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
                logger.warning(
                    "Triage failed for message %s: %s",
                    msg.get("id", "?"),
                    exc,
                )

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

    async def _fetch_messages(self, batch_size: int) -> list[dict[str, Any]]:
        """Fetch unread messages from Gmail.

        Returns a list of message dicts with at least ``id``, ``subject``,
        ``sender``, ``snippet``, and ``body`` keys.
        """
        if self._gmail is None:
            logger.warning("No Gmail connector configured; returning empty batch")
            return []

        try:
            message_ids, _ = await self._gmail.list_messages(
                query="is:unread",
                max_results=batch_size,
            )
        except (RuntimeError, OSError, ConnectionError) as exc:
            logger.error("Failed to list messages: %s", exc)
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
        message_id = msg.get("id", str(uuid.uuid4()))
        body = msg.get("body_text", msg.get("body", msg.get("snippet", "")))
        content_hash = compute_content_hash(body)

        debate_result = await self._run_debate(msg)
        normalized = _normalize_debate_outcome(debate_result)
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
        # Attach email metadata for CLI display (private attrs)
        intent._subject = msg.get("subject", "(no subject)")  # type: ignore[attr-defined]
        intent._sender = msg.get("from_address", msg.get("sender", "(unknown)"))  # type: ignore[attr-defined]
        intent._snippet = msg.get("snippet", body[:120])  # type: ignore[attr-defined]

        decision = TriageDecision(
            final_action=normalized.final_action,
            confidence=normalized.confidence,
            dissent_summary=normalized.dissent_summary,
            auto_approval_eligible=False,
            provider_route="direct",
            intent=intent,
            blocked_by_policy=bool(normalized.dissent_summary),
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

        return decision

    async def _run_debate(self, msg: dict[str, Any]) -> Any:
        """Run an adversarial debate on a message.

        Attempts to use the Arena with API agents. Falls back to a stub
        result if the debate engine or agents are unavailable.
        """
        subject = msg.get("subject", "(no subject)")
        sender = msg.get("from_address", msg.get("sender", "(unknown)"))
        body = msg.get("body_text", msg.get("body", msg.get("snippet", "")))
        question = (
            "Triage this email and recommend exactly ONE action: "
            "archive, star, label, or ignore.\n\n"
            f"From: {sender}\n"
            f"Subject: {subject}\n"
            f"Body: {body[:2000]}\n\n"
            "Your final answer MUST begin with the action word "
            "(archive, star, label, or ignore) followed by your reasoning."
        )

        try:
            from aragora.core import Environment
            from aragora.debate.orchestrator import Arena
            from aragora.debate.protocol import DebateProtocol

            env = Environment(task=question)
            protocol = DebateProtocol(rounds=2, consensus="majority")

            agents = _create_triage_agents()

            if len(agents) < 2:
                logger.warning(
                    "%d triage agents available (need 2); using stub debate", len(agents)
                )
                return {
                    "final_answer": "ignore",
                    "confidence": 0.0,
                    "debate_id": f"no-agents-{uuid.uuid4().hex[:8]}",
                }
            arena = Arena(env, agents=agents, protocol=protocol)
            return await arena.run()
        except ImportError:
            logger.debug("Debate engine not available; using stub result")
            return {
                "final_answer": "ignore",
                "confidence": 0.5,
                "debate_id": f"stub-{uuid.uuid4().hex[:8]}",
            }
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            logger.warning("Debate failed, falling back to ignore: %s", exc)
            return {
                "final_answer": "ignore",
                "confidence": 0.0,
                "debate_id": f"err-{uuid.uuid4().hex[:8]}",
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
