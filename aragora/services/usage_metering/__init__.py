"""Compatibility re-export of :mod:`aragora.billing.usage_metering`.

The usage meter moved to the billing layer. Every name below is the identical
object. The meter singleton (``_usage_meter``) lives only in the new module;
patch or reset it there.
"""

from __future__ import annotations

from aragora.billing.usage_metering import (
    DEFAULT_METERING_DB as DEFAULT_METERING_DB,
    MODEL_PRICING,
    TIER_USAGE_CAPS,
    ApiCallRecord,
    DebateUsageRecord,
    HourlyAggregate,
    MeteringPeriod,
    TokenUsageRecord,
    UsageBreakdown,
    UsageLimits,
    UsageMeter,
    UsageSummary,
    UsageType,
    get_usage_meter,
)

__all__ = [
    "UsageMeter",
    "UsageSummary",
    "UsageBreakdown",
    "UsageLimits",
    "TokenUsageRecord",
    "DebateUsageRecord",
    "ApiCallRecord",
    "HourlyAggregate",
    "MeteringPeriod",
    "UsageType",
    "MODEL_PRICING",
    "TIER_USAGE_CAPS",
    "get_usage_meter",
]
