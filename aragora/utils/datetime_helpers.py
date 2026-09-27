"""Unified datetime handling with timezone awareness.

This module provides consistent datetime utilities to eliminate timezone-related
bugs and ensure proper serialization across the codebase.

Usage:
    from aragora.utils.datetime_helpers import utc_now, to_iso_timestamp, from_iso_timestamp

    # Get current UTC time (always timezone-aware)
    now = utc_now()

    # For dataclass fields with default factories
    @dataclass
    class MyModel:
        created_at: datetime = field(default_factory=utc_now)

    # Serialize to ISO8601
    timestamp_str = to_iso_timestamp(my_datetime)

    # Parse ISO8601 back to datetime
    parsed = from_iso_timestamp(timestamp_str)
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime.

    This should be used instead of:
    - datetime.now() (naive, local timezone)
    - datetime.utcnow() (naive, deprecated in Python 3.12)
    - datetime.now(timezone.utc) (correct but verbose)

    Returns:
        A timezone-aware datetime in UTC.

    Example:
        >>> now = utc_now()
        >>> now.tzinfo is not None
        True
    """
    return datetime.now(timezone.utc)


def utc_now_iso_naive() -> str:
    """Current UTC time as a naive ISO-8601 string (no ``+00:00`` suffix).

    For SQLite TEXT timestamp columns that are aged with UTC
    ``julianday('now')`` comparisons (decay ranking, TTL pruning, cooldown
    checks): SQLite treats naive strings as UTC, so Python-side stamps must
    be UTC too. Kept naive to match the format of legacy local-time rows and
    SQLite's own ``CURRENT_TIMESTAMP`` defaults, and so
    ``datetime.fromisoformat`` consumers keep receiving naive datetimes.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def to_iso_timestamp(dt: datetime) -> str:
    """Convert a datetime to ISO8601 string format.

    Handles both timezone-aware and naive datetimes consistently.
    Naive datetimes are assumed to be UTC.

    Args:
        dt: The datetime to serialize.

    Returns:
        An ISO8601 formatted string with timezone information.

    Example:
        >>> dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        >>> to_iso_timestamp(dt)
        '2024-01-15T12:30:00+00:00'
    """
    if dt.tzinfo is None:
        # Assume naive datetime is UTC
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def from_iso_timestamp(s: str) -> datetime:
    """Parse an ISO8601 timestamp string to a timezone-aware datetime.

    Handles various ISO8601 formats including:
    - Full format with timezone: 2024-01-15T12:30:00+00:00
    - Z suffix for UTC: 2024-01-15T12:30:00Z
    - No timezone (assumes UTC): 2024-01-15T12:30:00

    Args:
        s: The ISO8601 timestamp string to parse.

    Returns:
        A timezone-aware datetime in UTC.

    Raises:
        ValueError: If the string cannot be parsed as ISO8601.

    Example:
        >>> dt = from_iso_timestamp("2024-01-15T12:30:00Z")
        >>> dt.tzinfo is not None
        True
    """
    # Handle Z suffix (common in JavaScript/JSON)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    dt = datetime.fromisoformat(s)

    # Ensure timezone-aware
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt


def ensure_timezone_aware(dt: datetime | None) -> datetime | None:
    """Ensure a datetime is timezone-aware, defaulting to UTC if naive.

    Useful for handling external data that may or may not include timezone info.

    Args:
        dt: The datetime to check, or None.

    Returns:
        A timezone-aware datetime, or None if input was None.

    Example:
        >>> naive = datetime(2024, 1, 15, 12, 30, 0)
        >>> aware = ensure_timezone_aware(naive)
        >>> aware.tzinfo is not None
        True
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def format_timestamp(
    dt: datetime,
    fmt: str = "%Y-%m-%d %H:%M:%S",
    include_tz: bool = True,
) -> str:
    """Format a datetime using strftime with optional timezone suffix.

    Provides consistent formatting across the codebase.

    Args:
        dt: The datetime to format.
        fmt: The strftime format string.
        include_tz: Whether to append timezone info.

    Returns:
        A formatted string representation.

    Example:
        >>> dt = datetime(2024, 1, 15, 12, 30, 0, tzinfo=timezone.utc)
        >>> format_timestamp(dt, "%Y-%m-%d")
        '2024-01-15 UTC'
    """
    result = dt.strftime(fmt)
    if include_tz and dt.tzinfo is not None:
        tz_name = dt.tzinfo.tzname(dt) or "UTC"
        result = f"{result} {tz_name}"
    return result


def parse_timestamp(
    value: str | datetime | None,
    default: datetime | None = None,
) -> datetime | None:
    """Parse a timestamp from various input formats.

    Handles strings, existing datetimes, and None values consistently.

    Args:
        value: The value to parse (string, datetime, or None).
        default: Default value if parsing fails or value is None.

    Returns:
        A timezone-aware datetime, or the default value.

    Example:
        >>> parse_timestamp("2024-01-15T12:30:00Z")
        datetime.datetime(2024, 1, 15, 12, 30, tzinfo=datetime.timezone.utc)
        >>> parse_timestamp(None, default=utc_now())  # Returns current time
    """
    if value is None:
        return default

    if isinstance(value, datetime):
        return ensure_timezone_aware(value)

    if isinstance(value, str):
        try:
            return from_iso_timestamp(value)
        except ValueError:
            return default

    return default


def timestamp_ms() -> int:
    """Return the current UTC time as milliseconds since epoch.

    Useful for unique IDs and cache keys.

    Returns:
        Milliseconds since Unix epoch.

    Example:
        >>> ts = timestamp_ms()
        >>> ts > 1700000000000
        True
    """
    return int(utc_now().timestamp() * 1000)


def timestamp_s() -> int:
    """Return the current UTC time as seconds since epoch.

    Returns:
        Seconds since Unix epoch.

    Example:
        >>> ts = timestamp_s()
        >>> ts > 1700000000
        True
    """
    return int(utc_now().timestamp())


__all__ = [
    "utc_now",
    "utc_now_iso_naive",
    "to_iso_timestamp",
    "from_iso_timestamp",
    "ensure_timezone_aware",
    "format_timestamp",
    "parse_timestamp",
    "timestamp_ms",
    "timestamp_s",
]
