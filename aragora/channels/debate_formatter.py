"""
Base debate result formatter interface.

Defines the contract for channel-specific debate result formatters,
mirroring the ReceiptFormatter pattern but for raw debate results
(dicts) rather than DecisionReceipt objects.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class DebateResultFormatter(ABC):
    """Base class for channel-specific debate result formatters."""

    @abstractmethod
    def format(
        self,
        result: dict[str, Any],
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Format a debate result for this channel.

        Args:
            result: The debate result dict (keys: consensus_reached, final_answer,
                    confidence, participants, task, rounds, duration_seconds, etc.)
            options: Optional formatting options (e.g., compact mode)

        Returns:
            Channel-specific formatted payload
        """
        ...

    @abstractmethod
    def format_summary(
        self,
        result: dict[str, Any],
        max_length: int = 500,
    ) -> str:
        """
        Format a short text summary of the debate result.

        Args:
            result: The debate result dict
            max_length: Maximum length of the summary

        Returns:
            Short text summary
        """
        ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_DEBATE_FORMATTERS: dict[str, type[DebateResultFormatter]] = {}


def register_debate_formatter(platform: str):
    """Decorator that registers a DebateResultFormatter subclass for *platform*.

    Usage::

        @register_debate_formatter("slack")
        class SlackDebateFormatter(DebateResultFormatter):
            ...
    """

    def _decorator(cls: type[DebateResultFormatter]) -> type[DebateResultFormatter]:
        _DEBATE_FORMATTERS[platform] = cls
        return cls

    return _decorator


def get_debate_formatter(platform: str) -> DebateResultFormatter | None:
    """Return a formatter instance for *platform*, or ``None`` if unregistered."""
    cls = _DEBATE_FORMATTERS.get(platform)
    if cls is not None:
        return cls()
    return None


def format_result_for_channel(
    platform: str,
    result: dict[str, Any],
    options: dict[str, Any] | None = None,
) -> dict[str, Any] | str:
    """Format a debate result for *platform*.

    Falls back to a plain-text summary when no formatter is registered.
    """
    formatter = get_debate_formatter(platform)
    if formatter is not None:
        return formatter.format(result, options)

    # Plain-text fallback
    consensus = result.get("consensus_reached", False)
    answer = result.get("final_answer", "No conclusion reached.")
    confidence = result.get("confidence", 0)
    if isinstance(confidence, (int, float)):
        confidence_str = f"{confidence:.0%}"
    else:
        confidence_str = str(confidence)

    status = "Consensus reached" if consensus else "No consensus"
    text = f"Debate Complete - {status} ({confidence_str} confidence)\n\n{answer}"
    return text
