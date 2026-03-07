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
import uuid
from typing import Any

from aragora.inbox.auto_approval import AutoApprovalPolicy
from aragora.inbox.trust_wedge import (
    ActionIntent,
    AllowedAction,
    InboxWedgeAction,
    ReceiptState,
    TriageDecision,
    compute_content_hash,
)

logger = logging.getLogger(__name__)


def _extract_action(debate_result: Any) -> str:
    """Extract an AllowedAction value from a debate result.

    Falls back to IGNORE if the debate output cannot be mapped.
    """
    answer = ""
    if hasattr(debate_result, "final_answer"):
        answer = str(getattr(debate_result, "final_answer", ""))
    elif isinstance(debate_result, dict):
        answer = str(debate_result.get("final_answer", ""))

    answer_lower = answer.lower()
    for action in AllowedAction:
        if action.value in answer_lower:
            return action.value

    return AllowedAction.IGNORE.value


def _extract_confidence(debate_result: Any) -> float:
    """Extract confidence from a debate result."""
    if hasattr(debate_result, "confidence"):
        try:
            return float(getattr(debate_result, "confidence", 0.0))
        except (TypeError, ValueError):
            return 0.0
    if isinstance(debate_result, dict):
        try:
            return float(debate_result.get("confidence", 0.0))
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _extract_dissent(debate_result: Any) -> str:
    """Extract dissent information from a debate result."""
    if hasattr(debate_result, "dissenting_views"):
        views = getattr(debate_result, "dissenting_views", [])
        if views:
            return "; ".join(str(v) for v in views[:3])
    if isinstance(debate_result, dict):
        views = debate_result.get("dissenting_views", [])
        if views:
            return "; ".join(str(v) for v in views[:3])
    return ""


def _create_triage_agents() -> list:
    """Create agents for triage debates.

    Prefers cheap, fast models:
      - Anthropic Haiku as proposer
      - OpenRouter/DeepSeek as critic
    Falls back to OpenAI if keys are missing.
    """
    import os

    from aragora.agents.base import create_agent

    agents: list = []
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
            pass

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
            pass

    # Fallback: try OpenAI if still short
    if len(agents) < 2 and os.environ.get("OPENAI_API_KEY"):
        role = "critic" if agents else "proposer"
        try:
            agents.append(create_agent("openai-api", name=f"triage-{role}", role=role))
        except (ImportError, RuntimeError, ValueError, OSError):
            pass

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
    ) -> None:
        self._gmail = gmail_connector
        self._policy = auto_approval_policy or AutoApprovalPolicy()
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
                decision = await self._triage_message(msg)
                if auto_approve and self._policy.auto_approve(decision):
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

    async def _triage_message(self, msg: dict[str, Any]) -> TriageDecision:
        """Run debate and build a TriageDecision for a single message."""
        message_id = msg.get("id", str(uuid.uuid4()))
        body = msg.get("body", msg.get("snippet", ""))
        content_hash = compute_content_hash(body)

        debate_result = await self._run_debate(msg)

        action = _extract_action(debate_result)
        confidence = _extract_confidence(debate_result)
        dissent = _extract_dissent(debate_result)
        debate_id = getattr(debate_result, "debate_id", None)
        if debate_id is None and isinstance(debate_result, dict):
            debate_id = debate_result.get("debate_id")
        debate_id = debate_id or f"triage-{uuid.uuid4().hex[:12]}"

        rationale = ""
        if hasattr(debate_result, "final_answer"):
            rationale = str(getattr(debate_result, "final_answer", ""))
        elif isinstance(debate_result, dict):
            rationale = str(debate_result.get("final_answer", ""))

        parsed_action = InboxWedgeAction.parse(action)

        intent = ActionIntent(
            provider="arena-consensus",
            message_id=message_id,
            action=parsed_action,
            content_hash=content_hash,
            synthesized_rationale=rationale[:500],
            confidence=confidence,
            provider_route="direct",
            debate_id=debate_id,
        )
        # Attach email metadata for CLI display (private attrs)
        intent._subject = msg.get("subject", "(no subject)")  # type: ignore[attr-defined]
        intent._sender = msg.get("sender", msg.get("from", "(unknown)"))  # type: ignore[attr-defined]
        intent._snippet = msg.get("snippet", body[:120])  # type: ignore[attr-defined]

        decision = TriageDecision(
            final_action=parsed_action,
            confidence=confidence,
            dissent_summary=dissent,
            auto_approval_eligible=False,
            provider_route="direct",
            intent=intent,
        )

        return decision

    async def _run_debate(self, msg: dict[str, Any]) -> Any:
        """Run an adversarial debate on a message.

        Attempts to use the Arena with API agents. Falls back to a stub
        result if the debate engine or agents are unavailable.
        """
        subject = msg.get("subject", "")
        body = msg.get("body", msg.get("snippet", ""))
        question = (
            f"Triage this email and recommend an action "
            f"(archive, star, label, or ignore).\n\n"
            f"Subject: {subject}\n"
            f"Body: {body[:2000]}"
        )

        try:
            from aragora.core import Environment
            from aragora.debate.orchestrator import Arena
            from aragora.debate.protocol import DebateProtocol

            agents = _create_triage_agents()

            if len(agents) < 2:
                logger.warning("Fewer than 2 agents available; using stub debate")
                return {
                    "final_answer": "ignore",
                    "confidence": 0.3,
                    "debate_id": f"no-agents-{uuid.uuid4().hex[:8]}",
                }

            env = Environment(task=question)
            protocol = DebateProtocol(rounds=2, consensus="majority")
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
        if self._gmail is None:
            logger.warning("No Gmail connector; skipping execution")
            return

        intent = decision.intent
        if intent is None:
            logger.warning("No intent on decision %s", decision.receipt_id)
            return

        action = decision.final_action
        message_id = intent.message_id

        try:
            if action == AllowedAction.ARCHIVE.value:
                await self._gmail.archive_message(message_id)
            elif action == AllowedAction.STAR.value:
                await self._gmail.star_message(message_id)
            elif action == AllowedAction.LABEL.value:
                # Label requires a label_id; skip if not provided
                logger.info("LABEL action requires manual label selection; skipping")
            elif action == AllowedAction.IGNORE.value:
                logger.info("IGNORE action; no Gmail operation needed")
            else:
                logger.warning("Unknown action %s; skipping execution", action)
                return

            decision.receipt_state = ReceiptState.EXECUTED.value
            logger.info(
                "Executed triage action: %s on message %s",
                action,
                message_id,
            )
        except (RuntimeError, OSError, ConnectionError) as exc:
            logger.error(
                "Failed to execute action %s on %s: %s",
                action,
                message_id,
                exc,
            )


__all__ = ["InboxTriageRunner"]
