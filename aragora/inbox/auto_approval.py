"""
Auto-Approval Policy for inbox triage decisions.

Encapsulates the rules that determine whether a triage decision can be
automatically approved without human review.

Rules:
- Only ARCHIVE, STAR, IGNORE are auto-approvable (not LABEL -- requires
  manual label selection).
- Confidence >= 0.85.
- No dissent block flag (non-empty ``dissent_summary`` blocks auto-approval).
- Receipt must be in CREATED state.
"""

from __future__ import annotations

import logging
from typing import Any

from aragora.inbox.trust_wedge import (
    AllowedAction,
    ReceiptState,
    TriageDecision,
)

logger = logging.getLogger(__name__)

# Actions that may be auto-approved (LABEL excluded -- needs manual choice)
_AUTO_APPROVABLE_ACTIONS: frozenset[str] = frozenset(
    {
        AllowedAction.ARCHIVE.value,
        AllowedAction.STAR.value,
        AllowedAction.IGNORE.value,
    }
)

_DEFAULT_CONFIDENCE_THRESHOLD = 0.85


class AutoApprovalPolicy:
    """Policy engine deciding whether a triage decision can skip human review.

    Parameters
    ----------
    confidence_threshold:
        Minimum confidence required for auto-approval. Defaults to 0.85.
    """

    def __init__(
        self,
        *,
        confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
    ) -> None:
        self._confidence_threshold = confidence_threshold

    @property
    def confidence_threshold(self) -> float:
        return self._confidence_threshold

    def can_auto_approve(self, decision: TriageDecision) -> bool:
        """Check whether *decision* is eligible for auto-approval.

        Returns ``True`` only when ALL of the following hold:

        1. ``final_action`` is in the auto-approvable set.
        2. ``confidence >= confidence_threshold``.
        3. ``dissent_summary`` is empty (no dissent block).
        4. ``receipt_state`` is CREATED.
        """
        if decision.final_action not in _AUTO_APPROVABLE_ACTIONS:
            logger.debug(
                "Auto-approval blocked: action %s not auto-approvable",
                decision.final_action,
            )
            return False

        if decision.confidence < self._confidence_threshold:
            logger.debug(
                "Auto-approval blocked: confidence %.2f < threshold %.2f",
                decision.confidence,
                self._confidence_threshold,
            )
            return False

        if decision.dissent_summary:
            logger.debug(
                "Auto-approval blocked: dissent present (%s)",
                decision.dissent_summary[:80],
            )
            return False

        if decision.receipt_state != ReceiptState.CREATED.value:
            logger.debug(
                "Auto-approval blocked: receipt state %s (expected CREATED)",
                decision.receipt_state,
            )
            return False

        return True

    def auto_approve(self, decision: TriageDecision) -> bool:
        """Attempt to auto-approve *decision*.

        If the policy allows, transitions the receipt state to APPROVED
        and returns ``True``. Otherwise leaves the decision unchanged
        and returns ``False``.
        """
        if not self.can_auto_approve(decision):
            return False

        decision.receipt_state = ReceiptState.APPROVED.value
        decision.auto_approval_eligible = True
        logger.info(
            "Auto-approved triage decision: receipt=%s action=%s confidence=%.2f",
            decision.receipt_id,
            decision.final_action,
            decision.confidence,
        )
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence_threshold": self._confidence_threshold,
            "auto_approvable_actions": sorted(_AUTO_APPROVABLE_ACTIONS),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AutoApprovalPolicy:
        return cls(
            confidence_threshold=float(
                data.get("confidence_threshold", _DEFAULT_CONFIDENCE_THRESHOLD)
            ),
        )


__all__ = ["AutoApprovalPolicy"]
