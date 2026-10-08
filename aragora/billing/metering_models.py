"""
Data models, enums, and constants for usage-based billing metering.

This module is self-contained with no imports from usage_metering.py.
All types used by UsageMeter and its consumers live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import uuid4

from aragora.models.pricing_mirror import metering_rows


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MeteringPeriod(Enum):
    """Billing period types for usage queries."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"


class UsageType(Enum):
    """Types of metered usage events."""

    TOKEN = "token"  # noqa: S105 -- enum value
    DEBATE = "debate"
    API_CALL = "api_call"
    STORAGE = "storage"
    CONNECTOR = "connector"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Provider pricing per 1M tokens (as of Jan 2026)
# Aligned with aragora.billing.usage.PROVIDER_PRICING
_LEGACY_MODEL_PRICING: dict[str, dict[str, Decimal]] = {
    "anthropic": {
        "claude-fable-5": Decimal("10.00"),  # catalog / live capture 2026-07-16
        "claude-fable-5-output": Decimal("50.00"),
        "claude-opus-5": Decimal("5.00"),  # live catalog 2026-07-24
        "claude-opus-5-output": Decimal("25.00"),
        "claude-opus-4-8": Decimal("5.00"),
        "claude-opus-4-8-output": Decimal("25.00"),
        "claude-opus-4-7": Decimal("5.00"),
        "claude-opus-4-7-output": Decimal("25.00"),
        "claude-opus-4.8": Decimal("5.00"),
        "claude-opus-4.8-output": Decimal("25.00"),
        "claude-opus-4.7": Decimal("5.00"),
        "claude-opus-4.7-output": Decimal("25.00"),
        "claude-opus-4": Decimal("5.00"),
        "claude-opus-4-output": Decimal("25.00"),
        "claude-sonnet-4": Decimal("3.00"),
        "claude-sonnet-4-output": Decimal("15.00"),
        "claude-haiku-3": Decimal("0.25"),
        "claude-haiku-3-output": Decimal("1.25"),
        "claude-haiku-4-5": Decimal("1.00"),
        "claude-haiku-4-5-output": Decimal("5.00"),
        "claude-haiku-4-5-20251001": Decimal("1.00"),
        "claude-haiku-4-5-20251001-output": Decimal("5.00"),
        "claude-haiku-4.5": Decimal("1.00"),
        "claude-haiku-4.5-output": Decimal("5.00"),
        "claude-haiku-4": Decimal("0.25"),
        "claude-haiku-4-output": Decimal("1.25"),
        "default": Decimal("3.00"),
        "default-output": Decimal("15.00"),
    },
    "openai": {
        "gpt-5.5": Decimal("5.00"),  # repriced by provider ~2026-07-14
        "gpt-5.5-output": Decimal("30.00"),
        "gpt-5.6-sol": Decimal("5.00"),  # catalog / live capture 2026-07-16
        "gpt-5.6-sol-output": Decimal("30.00"),
        "gpt-4o": Decimal("2.50"),
        "gpt-4o-output": Decimal("10.00"),
        "gpt-4o-mini": Decimal("0.15"),
        "gpt-4o-mini-output": Decimal("0.60"),
        "o1": Decimal("15.00"),
        "o1-output": Decimal("60.00"),
        "default": Decimal("2.50"),
        "default-output": Decimal("10.00"),
    },
    "google": {
        "gemini-3.5-flash": Decimal("1.50"),
        "gemini-3.5-flash-output": Decimal("9.00"),
        "gemini-3.1-pro": Decimal("2.00"),
        "gemini-3.1-pro-output": Decimal("12.00"),
        "gemini-3.1-pro-preview": Decimal("2.00"),
        "gemini-3.1-pro-preview-output": Decimal("12.00"),
        "gemini-pro": Decimal("1.25"),
        "gemini-pro-output": Decimal("5.00"),
        "gemini-ultra": Decimal("10.00"),
        "gemini-ultra-output": Decimal("30.00"),
        "default": Decimal("1.25"),
        "default-output": Decimal("5.00"),
    },
    "deepseek": {
        "deepseek-v4-pro": Decimal("1.74"),
        "deepseek-v4-pro-output": Decimal("3.48"),
        # NOTE: "deepseek-v3"/"deepseek-v3-output" were here at 0.14/0.28
        # while aragora/billing/usage.py's shared table priced the same
        # spelling at 0.28/0.42 (DeepSeek's current list price). Because
        # this table is passed to calculate_token_cost as ``extra_prices``,
        # the losing rate won on the tenant-billing path only, so one
        # spelling billed two ways depending on which caller priced it
        # (2026-09-05 merge-gate addendum on #9989). Removed; the shared
        # table's 0.28/0.42 is the rate, and calculate_token_cost now
        # refuses to let extra_prices restate a spelling the shared table
        # already prices at all.
        "default": Decimal("1.74"),
        "default-output": Decimal("3.48"),
    },
    "xai": {
        "grok-4.5": Decimal("2.00"),  # catalog / live capture 2026-07-16
        "grok-4.5-output": Decimal("6.00"),
        "grok-4.3": Decimal("1.25"),
        "grok-4.3-output": Decimal("2.50"),
        "grok-2": Decimal("2.00"),
        "grok-2-output": Decimal("10.00"),
        "default": Decimal("2.00"),
        "default-output": Decimal("10.00"),
    },
    "mistral": {
        # Live catalog 2026-09-04 (frontier-model-refresh): mistral-large is
        # $0.50/$1.50 per MTok, not the pre-refresh $2.00/$6.00 legacy price.
        "mistral-large": Decimal("0.50"),
        "mistral-large-output": Decimal("1.50"),
        "codestral": Decimal("0.20"),
        "codestral-output": Decimal("0.60"),
        "default": Decimal("2.00"),
        "default-output": Decimal("6.00"),
    },
    "openrouter": {
        "anthropic/claude-fable-5": Decimal("10.00"),  # catalog / live capture 2026-07-16
        "anthropic/claude-fable-5-output": Decimal("50.00"),
        "openai/gpt-5.5": Decimal("5.00"),
        "openai/gpt-5.5-output": Decimal("30.00"),
        "openai/gpt-5.6-sol": Decimal("5.00"),
        "openai/gpt-5.6-sol-output": Decimal("30.00"),
        "x-ai/grok-4.5": Decimal("2.00"),
        "x-ai/grok-4.5-output": Decimal("6.00"),
        "x-ai/grok-4.3": Decimal("1.25"),
        "x-ai/grok-4.3-output": Decimal("2.50"),
        "perplexity/sonar-reasoning-pro": Decimal("2.00"),
        "perplexity/sonar-reasoning-pro-output": Decimal("8.00"),
        "cohere/command-a": Decimal("2.50"),
        "cohere/command-a-output": Decimal("10.00"),
        "ai21/jamba-large-1.7": Decimal("2.00"),
        "ai21/jamba-large-1.7-output": Decimal("8.00"),
        "qwen/qwen3.8-max": Decimal("2.00"),
        "qwen/qwen3.8-max-output": Decimal("6.00"),
        "qwen/qwen3.7-max": Decimal("1.475"),
        "qwen/qwen3.7-max-output": Decimal("4.425"),
        "moonshotai/kimi-k3": Decimal("3.00"),
        "moonshotai/kimi-k3-output": Decimal("15.00"),
        "moonshotai/kimi-k2.7-code": Decimal("0.66"),
        "moonshotai/kimi-k2.7-code-output": Decimal("3.40"),
        "google/gemini-3.5-flash": Decimal("1.50"),
        "google/gemini-3.5-flash-output": Decimal("9.00"),
        "anthropic/claude-opus-5": Decimal("5.00"),
        "anthropic/claude-opus-5-output": Decimal("25.00"),
        "anthropic/claude-opus-4-8": Decimal("5.00"),
        "anthropic/claude-opus-4-8-output": Decimal("25.00"),
        "anthropic/claude-opus-4.8": Decimal("5.00"),
        "anthropic/claude-opus-4.8-output": Decimal("25.00"),
        "anthropic/claude-opus-4-7": Decimal("5.00"),
        "anthropic/claude-opus-4-7-output": Decimal("25.00"),
        "anthropic/claude-opus-4.7": Decimal("5.00"),
        "anthropic/claude-opus-4.7-output": Decimal("25.00"),
        "anthropic/claude-haiku-4-5": Decimal("1.00"),
        "anthropic/claude-haiku-4-5-output": Decimal("5.00"),
        "anthropic/claude-haiku-4.5": Decimal("1.00"),
        "anthropic/claude-haiku-4.5-output": Decimal("5.00"),
        "anthropic/claude-haiku-4-5-20251001": Decimal("1.00"),
        "anthropic/claude-haiku-4-5-20251001-output": Decimal("5.00"),
        "default": Decimal("2.00"),
        "default-output": Decimal("8.00"),
    },
}

# Catalog-generated rows win on a key collision with the legacy hand-written
# dict above (aragora.models.pricing_mirror is the single source of truth
# for catalog-known models); hand rows for models the catalog doesn't know
# about (including the per-provider "default"/"default-output" fallback
# rows) are preserved unchanged.
MODEL_PRICING: dict[str, dict[str, Decimal]] = {
    prov: {**_LEGACY_MODEL_PRICING.get(prov, {}), **rows}
    for prov, rows in {
        **{p: {} for p in _LEGACY_MODEL_PRICING},
        **metering_rows(),
    }.items()
}

# The catalog covers several providers (ai21, alibaba, cohere, moonshot,
# perplexity) the legacy dict above never had a bucket for, so those
# buckets come out of the merge above with no "default"/"default-output"
# entry. UsageMeter._calculate_token_cost() already falls back to the
# same $2.00/$8.00 constants for an unrecognized model in a recognized
# bucket -- this just makes that fallback an explicit, queryable row
# instead of a hardcoded literal, so every provider bucket satisfies the
# same invariant the hand-written buckets always have.
for _rows in MODEL_PRICING.values():
    _rows.setdefault("default", Decimal("2.00"))
    _rows.setdefault("default-output", Decimal("8.00"))
del _rows

# Tier-based usage caps (monthly)
TIER_USAGE_CAPS: dict[str, dict[str, int]] = {
    "free": {
        "max_tokens": 100_000,
        "max_debates": 10,
        "max_api_calls": 100,
    },
    "starter": {
        "max_tokens": 1_000_000,
        "max_debates": 50,
        "max_api_calls": 1_000,
    },
    "professional": {
        "max_tokens": 10_000_000,
        "max_debates": 200,
        "max_api_calls": 10_000,
    },
    "enterprise": {
        "max_tokens": 999_999_999,  # Effectively unlimited
        "max_debates": 999_999,
        "max_api_calls": 999_999,
    },
}


# ---------------------------------------------------------------------------
# Record dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TokenUsageRecord:
    """Record of token usage for a single API call."""

    id: str = field(default_factory=lambda: str(uuid4()))
    org_id: str = ""
    user_id: str | None = None
    model: str = ""
    provider: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    input_cost: Decimal = Decimal("0")
    output_cost: Decimal = Decimal("0")
    total_cost: Decimal = Decimal("0")
    debate_id: str | None = None
    endpoint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "model": self.model,
            "provider": self.provider,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "input_cost": str(self.input_cost),
            "output_cost": str(self.output_cost),
            "total_cost": str(self.total_cost),
            "debate_id": self.debate_id,
            "endpoint": self.endpoint,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class DebateUsageRecord:
    """Record of debate usage."""

    id: str = field(default_factory=lambda: str(uuid4()))
    org_id: str = ""
    user_id: str | None = None
    debate_id: str = ""
    agent_count: int = 0
    rounds: int = 0
    total_tokens: int = 0
    total_cost: Decimal = Decimal("0")
    duration_seconds: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "debate_id": self.debate_id,
            "agent_count": self.agent_count,
            "rounds": self.rounds,
            "total_tokens": self.total_tokens,
            "total_cost": str(self.total_cost),
            "duration_seconds": self.duration_seconds,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class ApiCallRecord:
    """Record of API call usage."""

    id: str = field(default_factory=lambda: str(uuid4()))
    org_id: str = ""
    user_id: str | None = None
    endpoint: str = ""
    method: str = "GET"
    status_code: int = 200
    response_time_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "org_id": self.org_id,
            "user_id": self.user_id,
            "endpoint": self.endpoint,
            "method": self.method,
            "status_code": self.status_code,
            "response_time_ms": self.response_time_ms,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class HourlyAggregate:
    """Hourly aggregation of usage for efficient storage."""

    org_id: str = ""
    hour: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    usage_type: UsageType = UsageType.TOKEN

    # Token metrics
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    token_cost: Decimal = Decimal("0")

    # Counts
    debate_count: int = 0
    api_call_count: int = 0

    # By model/provider breakdown
    tokens_by_model: dict[str, int] = field(default_factory=dict)
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "org_id": self.org_id,
            "hour": self.hour.isoformat(),
            "usage_type": self.usage_type.value,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "token_cost": str(self.token_cost),
            "debate_count": self.debate_count,
            "api_call_count": self.api_call_count,
            "tokens_by_model": self.tokens_by_model,
            "cost_by_model": {k: str(v) for k, v in self.cost_by_model.items()},
        }


# ---------------------------------------------------------------------------
# Summary / limits dataclasses
# ---------------------------------------------------------------------------


@dataclass
class UsageSummary:
    """Summary of usage for a billing period."""

    org_id: str
    period_start: datetime
    period_end: datetime
    period_type: MeteringPeriod = MeteringPeriod.MONTH

    # Token metrics
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    token_cost: Decimal = Decimal("0")

    # Counts
    debate_count: int = 0
    api_call_count: int = 0

    # Breakdowns
    tokens_by_model: dict[str, int] = field(default_factory=dict)
    cost_by_model: dict[str, Decimal] = field(default_factory=dict)
    tokens_by_provider: dict[str, int] = field(default_factory=dict)
    cost_by_provider: dict[str, Decimal] = field(default_factory=dict)
    cost_by_day: dict[str, Decimal] = field(default_factory=dict)

    # Limits
    token_limit: int = 0
    debate_limit: int = 0
    api_call_limit: int = 0

    # Usage percentages
    token_usage_percent: float = 0.0
    debate_usage_percent: float = 0.0
    api_call_usage_percent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "org_id": self.org_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "period_type": self.period_type.value,
            "tokens": {
                "input": self.input_tokens,
                "output": self.output_tokens,
                "total": self.total_tokens,
                "cost": str(self.token_cost),
            },
            "counts": {
                "debates": self.debate_count,
                "api_calls": self.api_call_count,
            },
            "by_model": {
                "tokens": self.tokens_by_model,
                "cost": {k: str(v) for k, v in self.cost_by_model.items()},
            },
            "by_provider": {
                "tokens": self.tokens_by_provider,
                "cost": {k: str(v) for k, v in self.cost_by_provider.items()},
            },
            "by_day": {k: str(v) for k, v in self.cost_by_day.items()},
            "limits": {
                "tokens": self.token_limit,
                "debates": self.debate_limit,
                "api_calls": self.api_call_limit,
            },
            "usage_percent": {
                "tokens": self.token_usage_percent,
                "debates": self.debate_usage_percent,
                "api_calls": self.api_call_usage_percent,
            },
        }


@dataclass
class UsageLimits:
    """Current usage limits and utilization."""

    org_id: str
    tier: str = "free"

    # Limits
    max_tokens: int = 0
    max_debates: int = 0
    max_api_calls: int = 0

    # Current usage
    tokens_used: int = 0
    debates_used: int = 0
    api_calls_used: int = 0

    # Percentages
    tokens_percent: float = 0.0
    debates_percent: float = 0.0
    api_calls_percent: float = 0.0

    # Flags
    tokens_exceeded: bool = False
    debates_exceeded: bool = False
    api_calls_exceeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "org_id": self.org_id,
            "tier": self.tier,
            "limits": {
                "tokens": self.max_tokens,
                "debates": self.max_debates,
                "api_calls": self.max_api_calls,
            },
            "used": {
                "tokens": self.tokens_used,
                "debates": self.debates_used,
                "api_calls": self.api_calls_used,
            },
            "percent": {
                "tokens": self.tokens_percent,
                "debates": self.debates_percent,
                "api_calls": self.api_calls_percent,
            },
            "exceeded": {
                "tokens": self.tokens_exceeded,
                "debates": self.debates_exceeded,
                "api_calls": self.api_calls_exceeded,
            },
        }


@dataclass
class UsageBreakdown:
    """Detailed usage breakdown for billing."""

    org_id: str
    period_start: datetime
    period_end: datetime

    # Totals
    total_cost: Decimal = Decimal("0")
    total_tokens: int = 0
    total_debates: int = 0
    total_api_calls: int = 0

    # By model
    by_model: list[dict[str, Any]] = field(default_factory=list)

    # By provider
    by_provider: list[dict[str, Any]] = field(default_factory=list)

    # By day
    by_day: list[dict[str, Any]] = field(default_factory=list)

    # By user (for multi-user organizations)
    by_user: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "org_id": self.org_id,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "totals": {
                "cost": str(self.total_cost),
                "tokens": self.total_tokens,
                "debates": self.total_debates,
                "api_calls": self.total_api_calls,
            },
            "by_model": self.by_model,
            "by_provider": self.by_provider,
            "by_day": self.by_day,
            "by_user": self.by_user,
        }


__all__ = [
    "MeteringPeriod",
    "UsageType",
    "MODEL_PRICING",
    "TIER_USAGE_CAPS",
    "TokenUsageRecord",
    "DebateUsageRecord",
    "ApiCallRecord",
    "HourlyAggregate",
    "UsageSummary",
    "UsageLimits",
    "UsageBreakdown",
]
