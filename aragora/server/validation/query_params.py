"""
Query parameter parsing and validation.

Provides safe parsing of URL query parameters with bounds checking,
type conversion, and proper error handling. Works with both
urllib.parse_qs (list values) and aiohttp MultiDict (single values).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from collections.abc import Set

logger = logging.getLogger(__name__)

# Default max length for string query parameters
DEFAULT_QUERY_STRING_MAX_LENGTH = 256

# Allowed sort columns for common endpoints (whitelist)
ALLOWED_SORT_COLUMNS = frozenset(
    {
        # Common
        "id",
        "name",
        "created_at",
        "updated_at",
        "timestamp",
        # Debates
        "task",
        "status",
        "rounds",
        "duration",
        "consensus_reached",
        # Agents
        "agent",
        "agent_name",
        "elo",
        "reliability",
        "score",
        "wins",
        "losses",
        # Rankings
        "rating",
        "rank",
        "votes",
        "flip_rate",
        "acceptance_rate",
        # Memory
        "importance",
        "recency",
        "freshness",
        "tier",
    }
)

# Allowed sort directions
ALLOWED_SORT_DIRECTIONS = frozenset({"asc", "desc", "ASC", "DESC"})

# Allowed filter operators (for query building)
ALLOWED_FILTER_OPERATORS = frozenset(
    {
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",  # Comparison
        "contains",
        "startswith",
        "endswith",  # String matching
        "in",
        "not_in",  # Set membership
    }
)

# =============================================================================
# Query Parameter Parsing (parse_qs format with list values)
# =============================================================================


def parse_int_param(
    query: dict[str, list],
    key: str,
    default: int,
    min_val: int = 1,
    max_val: int = 100,
) -> int:
    """Safely parse an integer query parameter with bounds checking.

    Args:
        query: Query dict from parse_qs (values are lists)
        key: Parameter name
        default: Default value if missing or invalid
        min_val: Minimum allowed value (default 1)
        max_val: Maximum allowed value (default 100)

    Returns:
        Parsed integer clamped to [min_val, max_val], or default on error

    Example:
        >>> query = parse_qs("limit=50&offset=10")
        >>> limit = parse_int_param(query, "limit", default=20, max_val=100)
        >>> offset = parse_int_param(query, "offset", default=0, min_val=0)
    """
    try:
        values = query.get(key)
        if values and isinstance(values, list) and len(values) > 0:
            val = int(values[0])
        else:
            return default
        return max(min_val, min(val, max_val))
    except (ValueError, IndexError, TypeError):
        return default


def parse_float_param(
    query: dict[str, list],
    key: str,
    default: float,
    min_val: float = 0.0,
    max_val: float = 1.0,
) -> float:
    """Safely parse a float query parameter with bounds checking.

    Args:
        query: Query dict from parse_qs (values are lists)
        key: Parameter name
        default: Default value if missing or invalid
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Parsed float clamped to [min_val, max_val], or default on error
    """
    try:
        values = query.get(key)
        if values and isinstance(values, list) and len(values) > 0:
            val = float(values[0])
        else:
            return default
        return max(min_val, min(val, max_val))
    except (ValueError, IndexError, TypeError):
        return default


def parse_bool_param(
    query: dict[str, list],
    key: str,
    default: bool = False,
) -> bool:
    """Safely parse a boolean query parameter.

    Recognizes: "true", "1", "yes" as True; "false", "0", "no" as False.

    Args:
        query: Query dict from parse_qs (values are lists)
        key: Parameter name
        default: Default value if missing or invalid

    Returns:
        Parsed boolean or default
    """
    try:
        values = query.get(key, [])
        if not values:
            return default
        val = values[0].lower() if isinstance(values, list) else str(values).lower()
        if val in ("true", "1", "yes"):
            return True
        if val in ("false", "0", "no"):
            return False
        return default
    except (AttributeError, IndexError, TypeError):
        return default


def parse_string_param(
    query: dict[str, list],
    key: str,
    default: str = "",
    max_length: int = 500,
    allowed_values: set | None = None,
) -> str:
    """Safely parse a string query parameter with validation.

    Args:
        query: Query dict from parse_qs (values are lists)
        key: Parameter name
        default: Default value if missing or invalid
        max_length: Maximum string length (truncates if exceeded)
        allowed_values: Optional set of allowed values (returns default if not in set)

    Returns:
        Parsed and validated string, or default
    """
    try:
        values = query.get(key, [default])
        if isinstance(values, list) and len(values) > 0:
            val = str(values[0])[:max_length]
        else:
            val = str(values)[:max_length]

        if allowed_values is not None and val not in allowed_values:
            return default
        return val
    except (IndexError, TypeError):
        return default


# =============================================================================
# Simple Query Value Parsing (for aiohttp-style query dicts)
# =============================================================================


def safe_query_int(
    query: Any,
    key: str,
    default: int,
    min_val: int = 1,
    max_val: int = 100,
) -> int:
    """Safely parse an integer from a query dict with bounds checking.

    Works with both urllib.parse_qs (list values) and aiohttp MultiDict
    (single string values).

    Args:
        query: Query dict (aiohttp MultiDict or parse_qs result)
        key: Parameter name
        default: Default value if missing or invalid
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Parsed integer clamped to bounds, or default on error
    """
    try:
        raw = query.get(key, default)
        # Handle parse_qs list format
        if isinstance(raw, list):
            raw = raw[0] if raw else default
        val = int(raw)
        return max(min_val, min(val, max_val))
    except (ValueError, IndexError, TypeError):
        return default


def safe_query_float(
    query: Any,
    key: str,
    default: float,
    min_val: float = 0.0,
    max_val: float = 1.0,
) -> float:
    """Safely parse a float from a query dict with bounds checking.

    Works with both urllib.parse_qs (list values) and aiohttp MultiDict
    (single string values).

    Args:
        query: Query dict (aiohttp MultiDict or parse_qs result)
        key: Parameter name
        default: Default value if missing or invalid
        min_val: Minimum allowed value
        max_val: Maximum allowed value

    Returns:
        Parsed float clamped to bounds, or default on error
    """
    try:
        raw = query.get(key, default)
        # Handle parse_qs list format
        if isinstance(raw, list):
            raw = raw[0] if raw else default
        val = float(raw)
        return max(min_val, min(val, max_val))
    except (ValueError, IndexError, TypeError):
        return default


def parse_iso_datetime(raw: Any) -> datetime:
    """Parse an ISO 8601 value; an offset-bearing value becomes naive local time.

    The accounting services store naive local ``datetime.now()`` timestamps, and
    comparing naive with aware datetimes raises ``TypeError``. A value outside the
    range of local time, or without a POSIX timestamp there (the AP and AR lists
    compare timestamps), raises ``ValueError``.
    """
    value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    try:
        local = value.astimezone().replace(tzinfo=None) if value.tzinfo else value
        local.timestamp()
    except (OverflowError, OSError) as exc:
        raise ValueError(f"{raw!r} is outside the supported date range") from exc
    return local


def parse_date_range_params(
    query: Any,
) -> tuple[datetime | None, datetime | None, str | None]:
    """Parse the optional ``start_date`` and ``end_date`` ISO 8601 query parameters.

    Accepts scalar values and single-element ``parse_qs`` lists. Returns
    ``(start, end, None)``, or ``(None, None, message)`` where the message names
    the first parameter that is repeated or not an ISO 8601 date/datetime.
    """
    parsed: dict[str, datetime | None] = {}
    for key in ("start_date", "end_date"):
        raw = query.get(key)
        if isinstance(raw, list):
            if len(raw) > 1:
                return None, None, f"{key} must not be repeated"
            raw = raw[0] if raw else None
        parsed[key] = None
        if raw:
            try:
                parsed[key] = parse_iso_datetime(raw)
            except ValueError:
                return None, None, f"{key} must be an ISO format date"
    return parsed["start_date"], parsed["end_date"], None


# =============================================================================
# Sort Parameter Validation
# =============================================================================


def validate_sort_param(
    query: Any,
    key: str = "sort",
    default: str = "created_at",
    allowed_columns: Set[str] | None = None,
) -> str:
    """Validate and parse a sort column parameter.

    Ensures the sort column is in the whitelist to prevent SQL injection.

    Args:
        query: Query dict
        key: Parameter name (default: "sort")
        default: Default column if missing or invalid
        allowed_columns: Set of allowed columns (defaults to ALLOWED_SORT_COLUMNS)

    Returns:
        Validated sort column or default

    Example:
        >>> sort_col = validate_sort_param(query, allowed_columns={"name", "created_at"})
        >>> cursor.execute(f"SELECT * FROM table ORDER BY {sort_col}")
    """
    if allowed_columns is None:
        allowed_columns = ALLOWED_SORT_COLUMNS

    try:
        raw = query.get(key, default)
        if isinstance(raw, list):
            raw = raw[0] if raw else default

        # Normalize to lowercase for comparison
        val = str(raw).strip().lower()

        # Check whitelist
        if val in allowed_columns:
            return val
        # Also check for case-insensitive match against actual allowed columns
        for col in allowed_columns:
            if col.lower() == val:
                return col

        logger.warning("Invalid sort column '%s' not in whitelist, using default", raw)
        return default
    except (IndexError, TypeError, AttributeError):
        return default


def validate_sort_direction(
    query: Any,
    key: str = "order",
    default: str = "desc",
) -> str:
    """Validate and parse a sort direction parameter.

    Args:
        query: Query dict
        key: Parameter name (default: "order")
        default: Default direction if missing or invalid

    Returns:
        "asc" or "desc"
    """
    try:
        raw = query.get(key, default)
        if isinstance(raw, list):
            raw = raw[0] if raw else default

        val = str(raw).strip().lower()
        if val in ("asc", "ascending", "1"):
            return "asc"
        if val in ("desc", "descending", "-1", "0"):
            return "desc"

        return default
    except (IndexError, TypeError, AttributeError):
        return default


def validate_sort_params(
    query: Any,
    sort_key: str = "sort",
    order_key: str = "order",
    default_column: str = "created_at",
    default_order: str = "desc",
    allowed_columns: set | None = None,
) -> tuple[str, str]:
    """Validate both sort column and direction.

    Convenience function that validates both sort parameters together.

    Args:
        query: Query dict
        sort_key: Key for sort column parameter
        order_key: Key for sort direction parameter
        default_column: Default sort column
        default_order: Default sort direction
        allowed_columns: Whitelist of allowed columns

    Returns:
        Tuple of (column, direction) both validated

    Example:
        >>> col, order = validate_sort_params(query)
        >>> cursor.execute(f"SELECT * FROM table ORDER BY {col} {order.upper()}")
    """
    column = validate_sort_param(query, sort_key, default_column, allowed_columns)
    direction = validate_sort_direction(query, order_key, default_order)
    return column, direction


# =============================================================================
# Safe String Parameter with Length Validation
# =============================================================================


def safe_query_string(
    query: Any,
    key: str,
    default: str = "",
    max_length: int = DEFAULT_QUERY_STRING_MAX_LENGTH,
    strip: bool = True,
    allowed_pattern: re.Pattern | None = None,
) -> str:
    """Safely parse a string query parameter with length and pattern validation.

    Args:
        query: Query dict
        key: Parameter name
        default: Default value if missing
        max_length: Maximum allowed length (truncates if exceeded)
        strip: Whether to strip whitespace
        allowed_pattern: Optional regex pattern the value must match

    Returns:
        Validated string or default

    Example:
        >>> search = safe_query_string(query, "q", max_length=100)
    """
    try:
        raw = query.get(key, default)
        if raw is None:
            return default
        if isinstance(raw, list):
            raw = raw[0] if raw else default

        val = str(raw)
        if strip:
            val = val.strip()

        # Truncate to max length
        if len(val) > max_length:
            logger.debug(
                "Query param '%s' truncated from %s to %s chars", key, len(val), max_length
            )
            val = val[:max_length]

        # Validate against pattern if provided
        if allowed_pattern is not None and val and not allowed_pattern.match(val):
            logger.warning("Query param '%s' doesn't match allowed pattern", key)
            return default

        return val
    except (IndexError, TypeError, AttributeError):
        return default


def validate_filter_operator(operator: str) -> tuple[bool, str | None]:
    """Validate a filter operator.

    Args:
        operator: The operator to validate (e.g., "eq", "gt", "contains")

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        >>> is_valid, err = validate_filter_operator(user_input)
        >>> if not is_valid:
        ...     return error_response(400, err)
    """
    if operator.lower() not in ALLOWED_FILTER_OPERATORS:
        allowed_str = ", ".join(sorted(ALLOWED_FILTER_OPERATORS))
        return False, f"Invalid filter operator '{operator}'. Allowed: {allowed_str}"
    return True, None


def validate_search_query(
    query_text: str,
    max_length: int = 200,
    block_sql_keywords: bool = True,
) -> tuple[bool, str, str | None]:
    """Validate and sanitize a search query string.

    Checks for SQL injection patterns and length limits.

    Args:
        query_text: The search query to validate
        max_length: Maximum allowed length
        block_sql_keywords: Whether to block SQL keywords

    Returns:
        Tuple of (is_valid, sanitized_query, error_message)

    Example:
        >>> is_valid, safe_query, err = validate_search_query(user_input)
        >>> if not is_valid:
        ...     return error_response(400, err)
        >>> cursor.execute("SELECT * FROM table WHERE name LIKE ?", (f"%{safe_query}%",))
    """
    if not query_text:
        return True, "", None

    # Truncate
    if len(query_text) > max_length:
        query_text = query_text[:max_length]

    # Strip dangerous characters for LIKE queries
    sanitized = query_text.strip()

    # Block SQL injection keywords (case-insensitive)
    if block_sql_keywords:
        sql_keywords = [
            "select",
            "insert",
            "update",
            "delete",
            "drop",
            "union",
            "exec",
            "execute",
            "xp_",
            "sp_",
            "--",
            ";--",
            "/*",
            "*/",
        ]
        lower_query = sanitized.lower()
        for keyword in sql_keywords:
            if keyword in lower_query:
                return False, "", f"Search query contains blocked keyword: {keyword}"

    # Escape LIKE special characters for safety
    sanitized = sanitized.replace("%", r"\%").replace("_", r"\_")

    return True, sanitized, None
