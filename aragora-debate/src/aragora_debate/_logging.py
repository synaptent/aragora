"""Opt-in local logging, with no import-time configuration or telemetry.

Call configure_logging() explicitly. JSON lines use ts (UTC ISO timestamp),
level, logger, and msg; exception/stack and extra record fields are optional.
Formatters never raise: arguments that cannot be interpolated leave the
redacted template plus a note naming the error, and any other formatting
failure yields one JSON line with the redacted template and format_error.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import contextlib
import copy
from datetime import datetime, timezone
import json
import logging
import os
import re
import sys
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    _StreamHandler = logging.StreamHandler[TextIO]
else:
    _StreamHandler = logging.StreamHandler

_SECRET_KEY = r"(?:api[_-]?key|token|secret|password|authorization)"
_KEY_PATTERN = re.compile(_SECRET_KEY, re.IGNORECASE)
_BARE = r"[^\s,;}\]]+"
_DQ = r'"(?:\\.|[^"\\])*"'
# key=value, key: value, and quoted keys as in JSON ("key": ...) or reprs ('key': ...).
# An unquoted Authorization value matches empty here; _redact_text() masks it to the
# end of the line without parsing the scheme, any auth-param or any quote.
_ASSIGNMENT = re.compile(
    r"""(?P<key>(?P<kq>["']?)[\w-]*"""
    r"(?:api[_-]?key|token|secret|password|(?P<auth>authorization))"
    r"""[\w-]*(?P=kq))(?P<sep>\s*[=:]\s*)"""
    rf"""(?:(?P<dq>{_DQ})|(?P<sq>'(?:\\.|[^'\\])*')|"""
    rf"(?(auth)|(?:(?:Bearer|Basic)\s+)?{_BARE}))",
    re.IGNORECASE,
)
# A line break ends a header value unless the next line starts with a space or tab
# (a folded continuation line, RFC 9112 obs-fold); a lone "\r" does not end it.
_VALUE_LINE_END = re.compile(r"\r?\n(?![ \t])")
# Another key's value can hide an Authorization name from _ASSIGNMENT: by running into
# it, past a quote or an escaped line break in a JSON or repr string, or by ending at
# the quote that opens it ({'url': '?token=', 'Authorization': ...} matches ', ').
_AUTH_NAME = re.compile("authorization", re.IGNORECASE)
_AUTH_NAME_NEXT = re.compile(r"[\w-]*authorization", re.IGNORECASE)
_REDACTED = "***"
_CYCLE = "<cycle>"
_MAPPING_FIELD = re.compile(
    r"%(?:%|\((?P<key>[^)]+)\)[#0 +\-]*\d*(?:\.\d+)?[hlL]?[diouxXeEfFgGcrsa])"
)
_STANDARD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "message",
    "asctime",
}


def _mask_assignment(match: re.Match[str]) -> str:
    quote = '"' if match.group("dq") else "'" if match.group("sq") else ""
    return f"{match.group('key')}{match.group('sep')}{quote}{_REDACTED}{quote}"


def _line_end(text: str, start: int) -> int:
    """The end of the line holding start, after any folded continuation lines."""
    match = _VALUE_LINE_END.search(text, start)
    return match.start() if match else len(text)


def _redact_text(text: str) -> str:
    parts: list[str] = []
    done = 0
    while match := _ASSIGNMENT.search(text, done):
        parts.append(text[done : match.start()])
        value_start = match.end("sep")
        hides_auth = (
            _AUTH_NAME.search(text, value_start, match.end()) is not None
            or _AUTH_NAME_NEXT.match(text, match.end()) is not None
        )
        quoted = match.group("dq") or match.group("sq")
        # Only a quoted key ("Authorization": "...") makes a quoted value the whole
        # value. Otherwise no quote is trusted to end an Authorization value, even the
        # closing quote of a JSON or repr string: the rest of the line is masked.
        if not hides_auth and (match.group("auth") is None or (quoted and match.group("kq"))):
            parts.append(_mask_assignment(match))
            done = match.end()
            continue
        parts.append(match.group("key") + match.group("sep"))
        done = _line_end(text, match.end())
        if done > value_start:
            parts.append(_REDACTED)
    parts.append(text[done:])
    return "".join(parts)


def _redact_item(key: Any, value: Any, active: frozenset[int]) -> tuple[Any, Any]:
    if isinstance(key, (str, int, float)) or key is None:
        return key, _REDACTED if _KEY_PATTERN.search(str(key)) else _redact(value, active)
    # json.dumps rejects other key types, and a composite key such as
    # ("api", "key") can split a secret name, so stringify it and fail closed.
    return _redact(str(key), active), _REDACTED


def _redact(obj: Any, active: frozenset[int]) -> Any:
    if isinstance(obj, (Mapping, list, tuple)):
        if id(obj) in active:
            return _CYCLE
        active = active | {id(obj)}
    if isinstance(obj, Mapping):
        return dict(_redact_item(key, value, active) for key, value in obj.items())
    if isinstance(obj, list):
        return [_redact(value, active) for value in obj]
    if isinstance(obj, tuple):
        return tuple(_redact(value, active) for value in obj)
    if isinstance(obj, str):
        return _redact_text(obj)
    return obj


def redact(obj: Any) -> Any:
    """Copy nested mappings/sequences, masking sensitive keys and assignments.

    Mapping keys other than str/int/float/None become strings, with the value
    masked, so the result is always JSON-encodable as far as keys go. A
    container that contains itself is replaced by "<cycle>" where it recurs.
    An Authorization value is masked to the end of its line, folded continuation
    lines included, also inside a JSON or repr string, where the rest of the line
    is masked too; only a quoted key with a quoted value masks just that string.
    Another secret's value that runs into an Authorization name, or whose quoted
    value ends where one starts, is likewise masked to the end of its line.
    """
    return _redact(obj, frozenset())


def _message(record: logging.LogRecord) -> tuple[str, str | None]:
    """Return the redacted message and, if interpolation failed, the error type."""
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
    try:
        return str(redact(safe.getMessage())), None
    except Exception as exc:  # noqa: BLE001 - any argument's str() may raise anything
        # The template stands in for the message so the record's other fields survive.
        error = type(exc).__name__
        return str(redact(f"{safe.msg} [unformattable log arguments: {error}]")), error


def _timestamp(created: float) -> str:
    return datetime.fromtimestamp(created, timezone.utc).isoformat()


def _text(value: object) -> str:
    return value if isinstance(value, str) else f"<{type(value).__name__}>"


def _fallback(record: logging.LogRecord, error: Exception) -> str:
    """One JSON line from the redacted template; never str() or repr() of the args."""
    created = getattr(record, "created", None)
    ts: str | None = None
    if isinstance(created, (int, float)):
        with contextlib.suppress(OverflowError, OSError, ValueError):
            ts = _timestamp(created)
    msg = getattr(record, "msg", None)
    # A non-string message is not converted: its str() may be what failed.
    template = str(redact(msg)) if isinstance(msg, str) else f"<{type(msg).__name__} message>"
    fields = {
        "ts": ts,
        "level": _text(getattr(record, "levelname", None)),
        "logger": _text(getattr(record, "name", None)),
        "msg": template,
        "format_error": type(error).__name__,
    }
    return json.dumps(fields, ensure_ascii=False)


def _format_safely(render: Callable[[logging.LogRecord], str], record: logging.LogRecord) -> str:
    try:
        return render(record)
    except Exception as exc:  # noqa: BLE001 - boundary: format() must never raise
        # Raising here makes logging's error handler print the raw msg and args.
        return _fallback(record, exc)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, including redacted structured extras."""

    def format(self, record: logging.LogRecord) -> str:
        return _format_safely(self._render, record)

    def _render(self, record: logging.LogRecord) -> str:
        message, error = _message(record)
        data = {key: value for key, value in record.__dict__.items() if key not in _STANDARD_FIELDS}
        data.update(
            ts=_timestamp(record.created), level=record.levelname, logger=record.name, msg=message
        )
        if error:
            data["format_error"] = error
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            data["stack"] = self.formatStack(record.stack_info)
        return json.dumps(redact(data), default=lambda obj: redact(str(obj)), ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable output with the same message/exception redaction."""

    def format(self, record: logging.LogRecord) -> str:
        return _format_safely(self._render, record)

    def _render(self, record: logging.LogRecord) -> str:
        safe = copy.copy(record)
        safe.msg = _message(record)[0]
        safe.args = ()
        safe.exc_text = None
        return str(redact(super().format(safe)))


class _ErrorSafeStreamHandler(_StreamHandler):
    """Report a failed write by error type only."""

    def handleError(self, record: logging.LogRecord) -> None:  # noqa: N802 - stdlib override
        # logging.Handler.handleError prints record.msg and record.args unredacted.
        if not logging.raiseExceptions or sys.stderr is None:
            return
        error = sys.exc_info()[0]
        name = error.__name__ if error else "unknown error"
        logger = _text(getattr(record, "name", None))
        with contextlib.suppress(OSError, ValueError):
            sys.stderr.write(f"--- Logging error: {name} writing a record from {logger} ---\n")


def configure_logging() -> None:
    """Explicitly replace root handlers; default to plain text at WARNING.

    ARAGORA_LOG_FORMAT=json selects JSON, otherwise text. ARAGORA_LOG_LEVEL
    accepts stdlib level names (case-insensitive); invalid values use WARNING.
    """
    level_name = os.environ.get("ARAGORA_LOG_LEVEL", "WARNING").upper()
    level = logging.getLevelName(level_name)
    if not isinstance(level, int):
        level = logging.WARNING
    handler = _ErrorSafeStreamHandler()
    formatter: logging.Formatter = (
        JsonFormatter()
        if os.environ.get("ARAGORA_LOG_FORMAT", "text").lower() == "json"
        else TextFormatter("%(levelname)s %(name)s: %(message)s")
    )
    handler.setFormatter(formatter)
    logging.basicConfig(level=level, handlers=[handler], force=True)
