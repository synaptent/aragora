"""Receipt operation hooks that only need the agents and debate packages.

``DecisionReceipt.from_debate_result`` in :mod:`aragora.models.receipts.gauntlet`
classifies failed agent responses and infers providers through registered
hooks. The gauntlet receipt facade registers these, and so does any domain
module that builds gauntlet receipts from the foundation module directly, so
that it does not have to import :mod:`aragora.gauntlet` for them.
"""

from __future__ import annotations

from aragora.agents.failure_semantics import all_responses_are_failures
from aragora.models.receipts import operations


def detect_provider(model: str) -> str:
    # Lazy: aragora.debate pulls in the whole debate engine.
    try:
        from aragora.debate.provider_diversity import detect_provider as _detect_provider

        return _detect_provider(model)
    except ImportError:
        return "unknown"


def register_receipt_agent_hooks() -> None:
    """Register provider detection and failure classification (idempotent)."""
    operations.register_provider_detector(detect_provider)
    operations.register_failure_classifier(all_responses_are_failures)


__all__ = ["detect_provider", "register_receipt_agent_hooks"]
