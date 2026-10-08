"""
Shared constants and utilities for analytics metrics handlers.

Extracted from _analytics_metrics_impl.py for reuse across submodules.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any


# Valid time granularities
VALID_GRANULARITIES = {"daily", "weekly", "monthly"}

# Valid time ranges for trend queries
VALID_TIME_RANGES = {"7d", "14d", "30d", "90d", "180d", "365d", "all"}


def _parse_time_range(time_range: str) -> datetime | None:
    """Parse time range string into a start datetime.

    Args:
        time_range: Time range string like '7d', '30d', '365d', or 'all'

    Returns:
        datetime for start of range, or None for 'all'
    """
    if time_range == "all":
        return None

    match = re.match(r"^(\d+)d$", time_range)
    if not match:
        return datetime.now(timezone.utc) - timedelta(days=30)  # Default

    days = int(match.group(1))
    return datetime.now(timezone.utc) - timedelta(days=days)


def _group_by_time(
    items: list[dict[str, Any]],
    timestamp_key: str,
    granularity: str,
) -> dict[str, list[dict[str, Any]]]:
    """Group items by time bucket based on granularity.

    Args:
        items: List of items with timestamp field
        timestamp_key: Key name for timestamp in items
        granularity: 'daily', 'weekly', or 'monthly'

    Returns:
        Dict mapping bucket key to list of items
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for item in items:
        ts = item.get(timestamp_key)
        if not ts:
            continue

        # Parse timestamp if string
        if isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
        elif isinstance(ts, datetime):
            dt = ts
        else:
            continue

        # Generate bucket key based on granularity
        if granularity == "daily":
            key = dt.strftime("%Y-%m-%d")
        elif granularity == "weekly":
            # ISO week number
            key = dt.strftime("%Y-W%W")
        else:  # monthly
            key = dt.strftime("%Y-%m")

        groups[key].append(item)

    return dict(groups)
