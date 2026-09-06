"""
Per-Debate Cost Accounting.

Provides granular cost tracking scoped to individual debates with:
- Per-agent cost breakdown
- Per-round cost breakdown
- Model usage statistics
- Provider rate lookup (configurable with defaults)
- Integration with DecisionReceipt for audit trails
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from aragora.billing.usage import calculate_token_cost
from aragora.models.pricing_mirror import debate_cost_rows

logger = logging.getLogger(__name__)


# Default provider rates per 1M tokens (input / output).
# These mirror PROVIDER_PRICING from usage.py but can be overridden per-instance.
_LEGACY_PROVIDER_RATES: dict[str, dict[str, tuple[Decimal, Decimal]]] = {
    "anthropic": {
        "claude-fable-5": (Decimal("10.00"), Decimal("50.00")),
        "claude-opus-5": (Decimal("5.00"), Decimal("25.00")),
        "claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
        "claude-opus-4-7": (Decimal("5.00"), Decimal("25.00")),
        "claude-opus-4.8": (Decimal("5.00"), Decimal("25.00")),
        "claude-opus-4.7": (Decimal("5.00"), Decimal("25.00")),
        "claude-opus-4": (Decimal("5.00"), Decimal("25.00")),
        "claude-sonnet-4.6": (Decimal("3.00"), Decimal("15.00")),
        "claude-sonnet-4": (Decimal("3.00"), Decimal("15.00")),
        "claude-haiku-3": (Decimal("0.25"), Decimal("1.25")),
        "claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
        "claude-haiku-4-5-20251001": (Decimal("1.00"), Decimal("5.00")),
        "claude-haiku-4.5": (Decimal("1.00"), Decimal("5.00")),
    },
    "openai": {
        "gpt-5.6-sol": (Decimal("5.00"), Decimal("30.00")),
        "gpt-5.5": (Decimal("5.00"), Decimal("30.00")),  # repriced ~2026-07-14
        "gpt-4.1": (Decimal("2.00"), Decimal("8.00")),
        "gpt-4.1-mini": (Decimal("0.40"), Decimal("1.60")),
        "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
        "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    },
    "google": {
        "gemini-3.5-flash": (Decimal("1.50"), Decimal("9.00")),
        "gemini-3.1-pro": (Decimal("2.00"), Decimal("12.00")),
        "gemini-3.1-pro-preview": (Decimal("2.00"), Decimal("12.00")),
        "gemini-3-flash": (Decimal("0.50"), Decimal("3.00")),
        "gemini-pro": (Decimal("1.25"), Decimal("5.00")),
    },
    "mistral": {
        # Live catalog 2026-09-04 (frontier-model-refresh): mistral-large is
        # $0.50/$1.50 per MTok, not the pre-refresh $2.00/$6.00 legacy price.
        "mistral-large-3": (Decimal("0.50"), Decimal("1.50")),
        "mistral-large": (Decimal("0.50"), Decimal("1.50")),
        "codestral": (Decimal("0.30"), Decimal("0.90")),
    },
    "xai": {
        "grok-4": (Decimal("3.00"), Decimal("15.00")),
        "grok-3": (Decimal("3.00"), Decimal("15.00")),
        "grok-2": (Decimal("2.00"), Decimal("10.00")),
    },
    "deepseek": {
        "deepseek-v4-pro": (Decimal("1.74"), Decimal("3.48")),
        "deepseek-v3.2": (Decimal("0.28"), Decimal("0.42")),
        "deepseek-v3": (Decimal("0.28"), Decimal("0.42")),
        "deepseek-r1": (Decimal("0.28"), Decimal("0.42")),
    },
    "openrouter": {
        "default": (Decimal("2.00"), Decimal("8.00")),
        "anthropic/claude-fable-5": (Decimal("10.00"), Decimal("50.00")),
        "openai/gpt-5.6-sol": (Decimal("5.00"), Decimal("30.00")),
        "qwen/qwen3.8-max": (Decimal("2.00"), Decimal("6.00")),
        "qwen/qwen3.7-max": (Decimal("1.475"), Decimal("4.425")),
        "moonshotai/kimi-k3": (Decimal("3.00"), Decimal("15.00")),
        "moonshotai/kimi-k2.7-code": (Decimal("0.66"), Decimal("3.40")),
        "perplexity/sonar-reasoning-pro": (Decimal("2.00"), Decimal("8.00")),
        "cohere/command-a": (Decimal("2.50"), Decimal("10.00")),
        "ai21/jamba-large-1.7": (Decimal("2.00"), Decimal("8.00")),
        "openai/gpt-5.5": (Decimal("5.00"), Decimal("30.00")),
        "google/gemini-3.5-flash": (Decimal("1.50"), Decimal("9.00")),
        "anthropic/claude-opus-4-8": (Decimal("5.00"), Decimal("25.00")),
        "anthropic/claude-opus-4.8": (Decimal("5.00"), Decimal("25.00")),
        "anthropic/claude-opus-4-7": (Decimal("5.00"), Decimal("25.00")),
        "anthropic/claude-opus-4.7": (Decimal("5.00"), Decimal("25.00")),
        "anthropic/claude-haiku-4-5": (Decimal("1.00"), Decimal("5.00")),
        "anthropic/claude-haiku-4.5": (Decimal("1.00"), Decimal("5.00")),
        "anthropic/claude-haiku-4-5-20251001": (
            Decimal("1.00"),
            Decimal("5.00"),
        ),
    },
}

# Catalog-generated rows win on a key collision with the legacy hand-written
# dict above (aragora.models.pricing_mirror is the single source of truth
# for catalog-known models); hand rows for models the catalog doesn't know
# about are preserved unchanged.
DEFAULT_PROVIDER_RATES: dict[str, dict[str, tuple[Decimal, Decimal]]] = {
    prov: {**_LEGACY_PROVIDER_RATES.get(prov, {}), **rows}
    for prov, rows in {
        **{p: {} for p in _LEGACY_PROVIDER_RATES},
        **debate_cost_rows(),
    }.items()
}


@dataclass
class AgentCallRecord:
    """Record of a single agent API call within a debate."""

    debate_id: str
    agent_name: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal
    round_number: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    operation: str = ""  # e.g., "proposal", "critique", "revision"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "debate_id": self.debate_id,
            "agent_name": self.agent_name,
            "provider": self.provider,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_usd": str(self.cost_usd),
            "round_number": self.round_number,
            "timestamp": self.timestamp.isoformat(),
            "operation": self.operation,
        }


@dataclass
class AgentCostBreakdown:
    """Cost breakdown for a single agent within a debate."""

    agent_name: str
    total_cost_usd: Decimal = Decimal("0")
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    call_count: int = 0
    models_used: dict[str, int] = field(default_factory=dict)  # model -> call_count

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "agent_name": self.agent_name,
            "total_cost_usd": str(self.total_cost_usd),
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "call_count": self.call_count,
            "models_used": self.models_used,
        }


@dataclass
class RoundCostBreakdown:
    """Cost breakdown for a single round within a debate."""

    round_number: int
    total_cost_usd: Decimal = Decimal("0")
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    call_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "round_number": self.round_number,
            "total_cost_usd": str(self.total_cost_usd),
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "call_count": self.call_count,
        }


@dataclass
class ModelUsage:
    """Usage statistics for a single model within a debate."""

    provider: str
    model: str
    total_cost_usd: Decimal = Decimal("0")
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    call_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "provider": self.provider,
            "model": self.model,
            "total_cost_usd": str(self.total_cost_usd),
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "call_count": self.call_count,
        }


@dataclass
class DebateCostSummary:
    """Complete cost summary for a debate.

    Includes total cost, per-agent breakdown, per-round breakdown,
    and model usage statistics.
    """

    debate_id: str
    total_cost_usd: Decimal = Decimal("0")
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_calls: int = 0
    per_agent: dict[str, AgentCostBreakdown] = field(default_factory=dict)
    per_round: dict[int, RoundCostBreakdown] = field(default_factory=dict)
    model_usage: dict[str, ModelUsage] = field(default_factory=dict)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "debate_id": self.debate_id,
            "total_cost_usd": str(self.total_cost_usd),
            "total_tokens_in": self.total_tokens_in,
            "total_tokens_out": self.total_tokens_out,
            "total_calls": self.total_calls,
            "per_agent": {k: v.to_dict() for k, v in self.per_agent.items()},
            "per_round": {str(k): v.to_dict() for k, v in sorted(self.per_round.items())},
            "model_usage": {k: v.to_dict() for k, v in self.model_usage.items()},
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DebateCostSummary:
        """Create from dictionary."""
        summary = cls(
            debate_id=data.get("debate_id", ""),
            total_cost_usd=Decimal(data.get("total_cost_usd", "0")),
            total_tokens_in=data.get("total_tokens_in", 0),
            total_tokens_out=data.get("total_tokens_out", 0),
            total_calls=data.get("total_calls", 0),
        )

        for name, agent_data in data.get("per_agent", {}).items():
            summary.per_agent[name] = AgentCostBreakdown(
                agent_name=agent_data.get("agent_name", name),
                total_cost_usd=Decimal(agent_data.get("total_cost_usd", "0")),
                total_tokens_in=agent_data.get("total_tokens_in", 0),
                total_tokens_out=agent_data.get("total_tokens_out", 0),
                call_count=agent_data.get("call_count", 0),
                models_used=agent_data.get("models_used", {}),
            )

        for round_str, round_data in data.get("per_round", {}).items():
            round_num = int(round_str)
            summary.per_round[round_num] = RoundCostBreakdown(
                round_number=round_data.get("round_number", round_num),
                total_cost_usd=Decimal(round_data.get("total_cost_usd", "0")),
                total_tokens_in=round_data.get("total_tokens_in", 0),
                total_tokens_out=round_data.get("total_tokens_out", 0),
                call_count=round_data.get("call_count", 0),
            )

        for key, model_data in data.get("model_usage", {}).items():
            summary.model_usage[key] = ModelUsage(
                provider=model_data.get("provider", ""),
                model=model_data.get("model", key),
                total_cost_usd=Decimal(model_data.get("total_cost_usd", "0")),
                total_tokens_in=model_data.get("total_tokens_in", 0),
                total_tokens_out=model_data.get("total_tokens_out", 0),
                call_count=model_data.get("call_count", 0),
            )

        return summary


class DebateCostTracker:
    """Tracks API costs scoped to individual debates.

    Records each agent call with token counts and computes costs
    using configurable provider rates. Provides per-agent, per-round,
    and per-model breakdowns.

    Usage::

        tracker = DebateCostTracker()
        tracker.record_agent_call(
            debate_id="debate-123",
            agent_name="claude",
            provider="anthropic",
            tokens_in=2000,
            tokens_out=800,
            model="claude-sonnet-4",
            round_number=1,
        )
        summary = tracker.get_debate_cost("debate-123")
        print(summary.total_cost_usd)
    """

    def __init__(
        self,
        provider_rates: dict[str, dict[str, tuple[Decimal, Decimal]]] | None = None,
    ) -> None:
        """Initialize the debate cost tracker.

        Args:
            provider_rates: Optional custom provider rates. Keys are provider names,
                values are dicts mapping model names to (input_rate, output_rate)
                tuples in USD per 1M tokens. Falls back to DEFAULT_PROVIDER_RATES.
        """
        self._provider_rates = provider_rates or DEFAULT_PROVIDER_RATES
        # debate_id -> list of call records
        self._calls: dict[str, list[AgentCallRecord]] = defaultdict(list)

    def record_agent_call(
        self,
        debate_id: str,
        agent_name: str,
        provider: str,
        tokens_in: int,
        tokens_out: int,
        model: str = "",
        round_number: int = 0,
        operation: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> AgentCallRecord:
        """Record a single agent API call for a debate.

        Args:
            debate_id: The debate this call belongs to.
            agent_name: Name of the agent that made the call.
            provider: LLM provider (e.g., "anthropic", "openai").
            tokens_in: Number of input tokens.
            tokens_out: Number of output tokens.
            model: Model identifier (e.g., "claude-sonnet-4").
            round_number: Debate round number (0 if not applicable).
            operation: Type of operation (e.g., "proposal", "critique").
            metadata: Optional additional metadata.

        Returns:
            The recorded AgentCallRecord with computed cost.
        """
        cost = calculate_token_cost(provider, model, tokens_in, tokens_out)

        record = AgentCallRecord(
            debate_id=debate_id,
            agent_name=agent_name,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            round_number=round_number,
            operation=operation,
            metadata=metadata or {},
        )

        self._calls[debate_id].append(record)

        logger.debug(
            "debate_cost_recorded debate=%s agent=%s model=%s cost=$%s",
            debate_id,
            agent_name,
            model,
            cost,
        )

        return record

    def get_debate_cost(self, debate_id: str) -> DebateCostSummary:
        """Get the complete cost summary for a debate.

        Args:
            debate_id: The debate to summarize.

        Returns:
            DebateCostSummary with total, per-agent, per-round,
            and model breakdowns.
        """
        records = self._calls.get(debate_id, [])
        summary = DebateCostSummary(debate_id=debate_id)

        if not records:
            return summary

        # Track timestamps for started_at / completed_at
        earliest: datetime | None = None
        latest: datetime | None = None

        for record in records:
            # Totals
            summary.total_cost_usd += record.cost_usd
            summary.total_tokens_in += record.tokens_in
            summary.total_tokens_out += record.tokens_out
            summary.total_calls += 1

            # Timestamps
            if earliest is None or record.timestamp < earliest:
                earliest = record.timestamp
            if latest is None or record.timestamp > latest:
                latest = record.timestamp

            # Per-agent breakdown
            if record.agent_name not in summary.per_agent:
                summary.per_agent[record.agent_name] = AgentCostBreakdown(
                    agent_name=record.agent_name,
                )
            agent = summary.per_agent[record.agent_name]
            agent.total_cost_usd += record.cost_usd
            agent.total_tokens_in += record.tokens_in
            agent.total_tokens_out += record.tokens_out
            agent.call_count += 1
            agent.models_used[record.model] = agent.models_used.get(record.model, 0) + 1

            # Per-round breakdown
            rnd = record.round_number
            if rnd not in summary.per_round:
                summary.per_round[rnd] = RoundCostBreakdown(round_number=rnd)
            round_bd = summary.per_round[rnd]
            round_bd.total_cost_usd += record.cost_usd
            round_bd.total_tokens_in += record.tokens_in
            round_bd.total_tokens_out += record.tokens_out
            round_bd.call_count += 1

            # Model usage
            model_key = f"{record.provider}/{record.model}"
            if model_key not in summary.model_usage:
                summary.model_usage[model_key] = ModelUsage(
                    provider=record.provider,
                    model=record.model,
                )
            mu = summary.model_usage[model_key]
            mu.total_cost_usd += record.cost_usd
            mu.total_tokens_in += record.tokens_in
            mu.total_tokens_out += record.tokens_out
            mu.call_count += 1

        summary.started_at = earliest
        summary.completed_at = latest

        return summary

    def get_all_debate_ids(self) -> list[str]:
        """Return all tracked debate IDs."""
        return list(self._calls.keys())

    def clear_debate(self, debate_id: str) -> None:
        """Remove all cost records for a debate (e.g., after archival).

        Args:
            debate_id: The debate to clear.
        """
        self._calls.pop(debate_id, None)

    def get_call_records(self, debate_id: str) -> list[AgentCallRecord]:
        """Get raw call records for a debate.

        Args:
            debate_id: The debate to query.

        Returns:
            List of AgentCallRecord instances.
        """
        return list(self._calls.get(debate_id, []))


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_debate_cost_tracker: DebateCostTracker | None = None


def get_debate_cost_tracker() -> DebateCostTracker:
    """Get or create the global DebateCostTracker singleton."""
    global _debate_cost_tracker
    if _debate_cost_tracker is None:
        _debate_cost_tracker = DebateCostTracker()
    return _debate_cost_tracker


__all__ = [
    "AgentCallRecord",
    "AgentCostBreakdown",
    "DebateCostSummary",
    "DebateCostTracker",
    "DEFAULT_PROVIDER_RATES",
    "ModelUsage",
    "RoundCostBreakdown",
    "get_debate_cost_tracker",
]
