"""
CLI Review Loop for inbox triage decisions.

Presents triage decisions to the user in a simple terminal interface
and allows approve/reject/edit/skip actions. Uses ``input()`` for
interaction -- no curses dependency.

Usage::

    from aragora.inbox.cli_review import CLIReviewLoop
    from aragora.inbox.trust_wedge import TriageDecision

    loop = CLIReviewLoop()
    results = loop.review_batch(decisions)
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable

from aragora.inbox.trust_wedge import (
    AllowedAction,
    InboxWedgeAction,
    ReceiptState,
    TriageDecision,
)

logger = logging.getLogger(__name__)


def _action_value(action: Any) -> str:
    if isinstance(action, Enum):
        return str(action.value)
    return str(action)


class CLIReviewLoop:
    """Interactive CLI loop for reviewing inbox triage decisions.

    Parameters
    ----------
    input_fn:
        Callable used to read user input. Defaults to the built-in
        ``input``. Override in tests to supply scripted responses.
    print_fn:
        Callable used for output. Defaults to built-in ``print``.
    on_approve:
        Optional callback ``(decision) -> None`` fired after a decision
        is approved.
    on_reject:
        Optional callback ``(decision) -> None`` fired after a decision
        is rejected.
    """

    def __init__(
        self,
        *,
        input_fn: Callable[..., str] | None = None,
        print_fn: Callable[..., Any] | None = None,
        review_fn: Callable[..., Any] | None = None,
        on_approve: Callable[[TriageDecision], None] | None = None,
        on_reject: Callable[[TriageDecision], None] | None = None,
    ) -> None:
        self._input = input_fn or input
        self._print = print_fn or print
        self._review_fn = review_fn
        self._on_approve = on_approve
        self._on_reject = on_reject

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review_batch(self, decisions: list[TriageDecision]) -> list[dict[str, Any]]:
        """Process a list of triage decisions sequentially.

        Returns a list of result dicts, one per decision, with keys:
        ``receipt_id``, ``action_taken`` (approve/reject/edit/skip),
        ``final_action``.
        """
        results: list[dict[str, Any]] = []
        total = len(decisions)

        self._print(f"\n--- Inbox Triage Review ({total} items) ---\n")

        for idx, decision in enumerate(decisions, start=1):
            self._print(f"[{idx}/{total}]")
            result = self._review_single(decision)
            results.append(result)
            self._print("")  # blank line between items

        approved = sum(1 for r in results if r["action_taken"] == "approve")
        rejected = sum(1 for r in results if r["action_taken"] == "reject")
        skipped = sum(1 for r in results if r["action_taken"] == "skip")
        edited = sum(1 for r in results if r["action_taken"] == "edit")

        self._print(
            f"--- Review complete: {approved} approved, {rejected} rejected, "
            f"{edited} edited, {skipped} skipped ---"
        )

        return results

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _review_single(self, decision: TriageDecision) -> dict[str, Any]:
        """Present one decision and collect the user's choice."""
        self._display_decision(decision)

        while True:
            choice = (
                self._input("  [a]pprove / [r]eject / [e]dit action / [s]kip > ").strip().lower()
            )

            if choice in ("a", "approve"):
                return self._handle_approve(decision)
            if choice in ("r", "reject"):
                return self._handle_reject(decision)
            if choice in ("e", "edit"):
                return self._handle_edit(decision)
            if choice in ("s", "skip"):
                return self._handle_skip(decision)

            self._print("  Invalid choice. Please enter a, r, e, or s.")

    def _display_decision(self, decision: TriageDecision) -> None:
        """Print a human-readable summary of a triage decision."""
        intent = decision.intent
        subject = "(unknown)"
        sender = "(unknown)"
        snippet = ""

        if intent:
            # Intent metadata may carry email details if attached
            subject = getattr(intent, "_subject", subject)
            sender = getattr(intent, "_sender", sender)
            snippet = getattr(intent, "_snippet", snippet)

        self._print(f"  Subject : {subject}")
        self._print(f"  Sender  : {sender}")
        if snippet:
            self._print(f"  Snippet : {snippet[:120]}")
        self._print(f"  Action  : {_action_value(decision.final_action)}")
        self._print(f"  Conf.   : {decision.confidence:.0%}")
        if decision.dissent_summary:
            self._print(f"  Dissent : {decision.dissent_summary}")
        self._print(f"  Receipt : {decision.receipt_id}")

    def _handle_approve(self, decision: TriageDecision) -> dict[str, Any]:
        self._apply_review(decision, choice="approve")
        self._print("  -> APPROVED")
        logger.info(
            "Triage approved: receipt=%s action=%s", decision.receipt_id, decision.final_action
        )
        if self._on_approve:
            self._on_approve(decision)
        return {
            "receipt_id": decision.receipt_id,
            "action_taken": "approve",
            "final_action": decision.final_action,
        }

    def _handle_reject(self, decision: TriageDecision) -> dict[str, Any]:
        self._apply_review(decision, choice="reject")
        self._print("  -> REJECTED")
        logger.info("Triage rejected: receipt=%s", decision.receipt_id)
        if self._on_reject:
            self._on_reject(decision)
        return {
            "receipt_id": decision.receipt_id,
            "action_taken": "reject",
            "final_action": decision.final_action,
        }

    def _handle_edit(self, decision: TriageDecision) -> dict[str, Any]:
        valid_actions = [a.value for a in AllowedAction]
        self._print(f"  Available actions: {', '.join(valid_actions)}")
        while True:
            new_action = self._input("  New action > ").strip().lower()
            if new_action in valid_actions:
                break
            self._print(f"  Invalid. Choose from: {', '.join(valid_actions)}")

        old_action = decision.final_action
        parsed_action = InboxWedgeAction.parse(new_action)
        self._apply_review(decision, choice="edit", edited_action=parsed_action.value)
        self._print(f"  -> EDITED: {old_action} -> {new_action}")
        logger.info(
            "Triage edited: receipt=%s %s->%s",
            decision.receipt_id,
            old_action,
            new_action,
        )
        return {
            "receipt_id": decision.receipt_id,
            "action_taken": "edit",
            "final_action": new_action,
        }

    def _handle_skip(self, decision: TriageDecision) -> dict[str, Any]:
        self._apply_review(decision, choice="skip")
        self._print("  -> SKIPPED")
        logger.info("Triage skipped: receipt=%s", decision.receipt_id)
        return {
            "receipt_id": decision.receipt_id,
            "action_taken": "skip",
            "final_action": decision.final_action,
        }

    def _apply_review(
        self,
        decision: TriageDecision,
        *,
        choice: str,
        edited_action: str | None = None,
        edited_rationale: str | None = None,
        label_id: str | None = None,
    ) -> None:
        if self._review_fn is None or not decision.receipt_id:
            if choice == "approve":
                decision.receipt_state = ReceiptState.APPROVED.value
            elif choice == "reject":
                decision.receipt_state = ReceiptState.EXPIRED.value
            elif choice == "edit":
                if edited_action is not None:
                    parsed_action = InboxWedgeAction.parse(edited_action)
                    decision.final_action = parsed_action
                    if decision.intent:
                        decision.intent.action = parsed_action
                decision.receipt_state = ReceiptState.CREATED.value
            return

        envelope = self._review_fn(
            decision.receipt_id,
            choice=choice,
            edited_action=edited_action,
            edited_rationale=edited_rationale,
            label_id=label_id,
        )
        receipt = envelope.receipt
        updated = envelope.decision

        decision.final_action = updated.final_action
        decision.confidence = updated.confidence
        decision.dissent_summary = updated.dissent_summary
        decision.receipt_id = receipt.receipt_id
        decision.auto_approval_eligible = updated.auto_approval_eligible
        decision.receipt_state = receipt.state.value
        decision.intent = envelope.intent
        decision.provider_route = updated.provider_route
        decision.label_id = updated.label_id
        decision.blocked_by_policy = updated.blocked_by_policy


__all__ = ["CLIReviewLoop"]
