"""
Canonical contract types for the Inbox Trust Wedge.

These types bind the Gmail triage flow together:
- AllowedAction: The set of actions the wedge can take on an email
- ActionIntent: A model's proposed action on a specific email
- TriageDecision: The final decision after debate, ready for review
- ReceiptState: Lifecycle states for triage receipts

All dataclasses support ``to_dict()``/``from_dict()`` for serialization.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AllowedAction(str, Enum):
    """Actions the trust wedge is permitted to take on an email.

    These map to Gmail operations exposed by
    ``aragora.connectors.enterprise.communication.gmail.labels``.
    """

    ARCHIVE = "archive"
    STAR = "star"
    LABEL = "label"
    IGNORE = "ignore"


class ReceiptState(str, Enum):
    """Lifecycle states for a triage receipt.

    State machine:
        CREATED -> APPROVED -> EXECUTED
        CREATED -> EXPIRED
        CREATED -> (edit) -> CREATED   (re-sign on edit)
    """

    CREATED = "created"
    APPROVED = "approved"
    EXPIRED = "expired"
    EXECUTED = "executed"


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hex digest of email content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@dataclass
class ActionIntent:
    """A single model's proposed action on an email message.

    Produced by the debate synthesizer after the proposer/critic rounds.
    """

    provider: str  # which model proposed this
    message_id: str  # Gmail message ID
    action: str  # AllowedAction value
    content_hash: str  # SHA-256 of email content
    synthesized_rationale: str  # why this action
    confidence: float  # synthesizer confidence [0.0, 1.0]
    provider_route: str  # "direct" or "openrouter"
    debate_id: str  # which debate produced this
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "message_id": self.message_id,
            "action": self.action,
            "content_hash": self.content_hash,
            "synthesized_rationale": self.synthesized_rationale,
            "confidence": self.confidence,
            "provider_route": self.provider_route,
            "debate_id": self.debate_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActionIntent:
        return cls(
            provider=data["provider"],
            message_id=data["message_id"],
            action=data["action"],
            content_hash=data["content_hash"],
            synthesized_rationale=data["synthesized_rationale"],
            confidence=float(data["confidence"]),
            provider_route=data["provider_route"],
            debate_id=data["debate_id"],
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class TriageDecision:
    """The final triage decision for an email, ready for user review.

    Wraps an ``ActionIntent`` with consensus metadata and approval status.
    """

    final_action: str  # AllowedAction value
    confidence: float
    dissent_summary: str  # empty if unanimous; describes disagreements
    receipt_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    auto_approval_eligible: bool = False
    provider_route: str = "direct"
    intent: ActionIntent | None = None
    receipt_state: str = ReceiptState.CREATED.value

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_action": self.final_action,
            "confidence": self.confidence,
            "dissent_summary": self.dissent_summary,
            "receipt_id": self.receipt_id,
            "auto_approval_eligible": self.auto_approval_eligible,
            "provider_route": self.provider_route,
            "intent": self.intent.to_dict() if self.intent else None,
            "receipt_state": self.receipt_state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriageDecision:
        intent = None
        if data.get("intent"):
            intent = ActionIntent.from_dict(data["intent"])
        return cls(
            final_action=data["final_action"],
            confidence=float(data["confidence"]),
            dissent_summary=data.get("dissent_summary", ""),
            receipt_id=data.get("receipt_id", str(uuid.uuid4())),
            auto_approval_eligible=data.get("auto_approval_eligible", False),
            provider_route=data.get("provider_route", "direct"),
            intent=intent,
            receipt_state=data.get("receipt_state", ReceiptState.CREATED.value),
        )


__all__ = [
    "AllowedAction",
    "ActionIntent",
    "TriageDecision",
    "ReceiptState",
    "compute_content_hash",
]
