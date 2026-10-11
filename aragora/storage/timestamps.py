"""Canonical UTC timestamps for stored records.

The SQLite and PostgreSQL approval-request stores keep ``expires_at`` as
ISO-8601 text and compare it with ``datetime.now(timezone.utc).isoformat()``.
The canonical stored form is therefore UTC ISO-8601 text with a ``+00:00``
offset, as produced by ``datetime.isoformat()`` on an aware UTC datetime.

Policy for incoming values:

- ``None`` means "not set" and is stored unchanged.
- Aware datetimes and ISO-8601 strings with an offset or ``Z`` suffix are
  converted to UTC.
- Naive datetimes and ISO-8601 strings without an offset are read as UTC,
  the convention of :mod:`aragora.utils.datetime_helpers`.
- Everything else raises ``ValueError``: other types (including dates, numbers
  and booleans), strings with no time of day, unparseable strings, and
  instants that fall outside the range ``datetime`` can represent in UTC.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from aragora.utils.datetime_helpers import from_iso_timestamp

logger = logging.getLogger(__name__)

__all__ = [
    "canonical_utc_timestamp",
    "parse_utc_timestamp",
    "timestamp_before",
]


def _is_date_only(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def parse_utc_timestamp(value: object, *, field: str) -> datetime:
    """Return ``value`` as an aware UTC datetime.

    Raises:
        ValueError: If ``value`` is not a supported timestamp (see module docs).
            The message names ``field``.
    """
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    elif isinstance(value, str):
        if _is_date_only(value):
            raise ValueError(f"{field} must include a time of day, got {value!r}")
        try:
            moment = from_iso_timestamp(value)
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO-8601 timestamp, got {value!r}") from exc
    else:
        raise ValueError(
            f"{field} must be a datetime or ISO-8601 string, got {type(value).__name__}"
        )
    try:
        return moment.astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError(f"{field} is outside the representable UTC range: {value!r}") from exc


def canonical_utc_timestamp(value: object, *, field: str) -> str | None:
    """Return the canonical stored form of ``value``, or None when it is None.

    Raises:
        ValueError: If ``value`` is not a supported timestamp (see module docs).
    """
    if value is None:
        return None
    return parse_utc_timestamp(value, field=field).isoformat()


def timestamp_before(value: object, moment: datetime, *, field: str) -> bool:
    """Return whether a stored timestamp is strictly earlier than aware ``moment``.

    None is never earlier. Save paths reject unsupported values, so an
    unreadable one can only come from editing a returned record in place; it
    is logged and treated as not earlier so one bad record cannot fail a
    whole list query.
    """
    if value is None:
        return False
    try:
        return parse_utc_timestamp(value, field=field) < moment
    except ValueError:
        logger.warning("Ignoring unreadable %s of type %s", field, type(value).__name__)
        return False
