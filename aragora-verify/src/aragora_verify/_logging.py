"""Opt-in local logging, with no import-time configuration or telemetry.

Call configure_logging() explicitly. JSON lines use ts (UTC ISO timestamp),
level, logger, and msg; exception/stack and extra record fields are optional.
"""

from __future__ import annotations

from collections.abc import Mapping
import copy
from datetime import datetime, timezone
import json
import logging
import os
import re
from typing import Any

_SECRET_KEY = r"(?:api[_-]?key|token|secret|password|authorization)"
_KEY_PATTERN = re.compile(_SECRET_KEY, re.IGNORECASE)
_ASSIGNMENT = re.compile(
    rf"(?P<key>[\w-]*{_SECRET_KEY}[\w-]*)(?P<sep>\s*=\s*)"
    r"""(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|"""
    r"(?:Bearer|Basic)\s+[^\s,;}\]]+|[^\s,;}\]]+)",
    re.IGNORECASE,
)
_REDACTED = "***"
_MAPPING_FIELD = re.compile(
    r"%(?:%|\((?P<key>[^)]+)\)[#0 +\-]*\d*(?:\.\d+)?[hlL]?[diouxXeEfFgGcrsa])"
)
_STANDARD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


def redact(obj: Any) -> Any:
    """Copy nested mappings/sequences, masking sensitive keys and assignments."""
    if isinstance(obj, Mapping):
        return {
            key: _REDACTED if _KEY_PATTERN.search(str(key)) else redact(value)
            for key, value in obj.items()
        }
    if isinstance(obj, list):
        return [redact(value) for value in obj]
    if isinstance(obj, tuple):
        return tuple(redact(value) for value in obj)
    if isinstance(obj, str):
        return _ASSIGNMENT.sub(r"\g<key>\g<sep>" + _REDACTED, obj)
    return obj


def _message(record: logging.LogRecord) -> str:
    safe = copy.copy(record)
    # Leave %-placeholders intact until interpolation has completed.
    safe.msg = record.msg if isinstance(record.msg, str) else redact(record.msg)
    if isinstance(record.msg, str) and isinstance(record.args, Mapping):
        # Replace the whole sensitive field, not a numeric value with a string.
        # Matching %% first preserves escaped placeholders as literal text.
        safe.msg = _MAPPING_FIELD.sub(
            lambda match: (
                _REDACTED
                if match.group("key") and _KEY_PATTERN.search(match.group("key"))
                else match.group(0)
            ),
            record.msg,
        )
    safe.args = redact(record.args)
    return str(redact(safe.getMessage()))


class JsonFormatter(logging.Formatter):
    """One JSON object per line, including redacted structured extras."""

    def format(self, record: logging.LogRecord) -> str:
        data = {key: value for key, value in record.__dict__.items() if key not in _STANDARD_FIELDS}
        data.update(
            ts=datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            level=record.levelname,
            logger=record.name,
            msg=_message(record),
        )
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            data["stack"] = self.formatStack(record.stack_info)
        return json.dumps(redact(data), default=lambda obj: redact(str(obj)), ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable output with the same message/exception redaction."""

    def format(self, record: logging.LogRecord) -> str:
        safe = copy.copy(record)
        safe.msg = _message(record)
        safe.args = ()
        safe.exc_text = None
        return str(redact(super().format(safe)))


def configure_logging() -> None:
    """Explicitly replace root handlers; default to plain text at WARNING.

    ARAGORA_LOG_FORMAT=json selects JSON, otherwise text. ARAGORA_LOG_LEVEL
    accepts stdlib level names (case-insensitive); invalid values use WARNING.
    """
    level_name = os.environ.get("ARAGORA_LOG_LEVEL", "WARNING").upper()
    level = logging.getLevelName(level_name)
    if not isinstance(level, int):
        level = logging.WARNING
    handler = logging.StreamHandler()
    formatter: logging.Formatter = (
        JsonFormatter()
        if os.environ.get("ARAGORA_LOG_FORMAT", "text").lower() == "json"
        else TextFormatter("%(levelname)s %(name)s: %(message)s")
    )
    handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[handler], force=True)
