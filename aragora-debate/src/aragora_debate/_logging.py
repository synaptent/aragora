"""Opt-in local logging, with no import-time configuration or telemetry.

Call configure_logging() explicitly. JSON lines use ts (UTC ISO timestamp),
level, logger, and msg; exception/stack and extra record fields are optional.
Formatters never raise: arguments that cannot be interpolated leave the
redacted template plus a note naming the error, and any other formatting
failure yields one JSON line with the redacted template and format_error.

Redaction is name-based and takes linear time. A value is masked when it
follows a secret name (api key, token, secret, password, authorization) as a
mapping key, an assignment, a header name/value pair, a HAR entry or
Authorization phrasing; where its end is uncertain, the rest of the line is
masked. In structured values a Cookie or Set-Cookie header name counts too.
Credentials logged with no name at all are not recognised.
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
# A bare value ends at whitespace, or at , ; } ] when one is followed by whitespace,
# a quote, another of them, the end or another secret key and its separator: "a,b"
# is one value, and "a, b" and "a,token=b" are not. The key's secret word is found by
# a lookahead before the greedy match, so a long word holding it often stays linear.
_BARE = (
    r"""(?:[^\s,;}\]]|[,;}\]](?![\s,;}\]"']|\Z"""
    rf"""|[^\s,;}}\]]*?(?<![\w.-])(?=[\w.-]*?{_SECRET_KEY})[\w.-]+\\{{0,7}}["']?\s*[=:]))+"""
)
_DQ = r'"(?:\\.|[^"\\])*"'
_SQ = r"'(?:\\.|[^'\\])*'"
# One balanced container level. A quoted string inside it holds no line break and no
# escaped quote, so a quote toggles the scan between in and out of a string the same
# way from every starting bracket; a bracket that never closes is then scanned from at
# most a few starting points, and later values are scanned once.
_QUOTED_IN_BRACKET = r"""(?:"(?:\\[^"'\n]|[^"\\\n])*"|'(?:\\[^"'\n]|[^'\\\n])*')"""
_BRACKET = (
    rf"""\[(?:{_QUOTED_IN_BRACKET}|[^\[\]"'])*\]"""
    rf"""|\{{(?:{_QUOTED_IN_BRACKET}|[^{{}}"'])*\}}"""
    rf"""|\((?:{_QUOTED_IN_BRACKET}|[^()"'])*\)"""
)
# Up to seven backslashes: a key quoted inside a JSON or repr string, up to three deep.
_KEY_QUOTE = r"""(?<!\\)\\{0,7}["']"""
# Whitespace in a name/value pair, also as the \n, \r or \t that a JSON or repr string
# writes for a line break, carriage return or tab, up to three strings deep.
_PAIR_SPACE = r"(?:\s|\\{1,7}[nrt])*"
# key=value, key: value, a quoted key as in JSON or a repr, and a quoted name before a
# comma (a header tuple's first item or a HAR "name" field). A key starts at a word
# boundary and its secret word is found by a lookahead, so a long word takes linear
# time. A quoted key may hold dots, start with a space, hold one more word ('Proxy
# Authorization') and follow a colon whose prefix holds no secret word
# ('header:authorization'), so it never holds an assignment such as 'token:x'. An
# unquoted key may hold dots, or end in a quote that it does not start with, and an
# Authorization name may be followed by one word ("Authorization header: ...").
_ASSIGNMENT = re.compile(
    rf"(?P<key>(?P<kq>{_KEY_QUOTE})(?=[ \w.:-]*?{_SECRET_KEY})"
    rf"(?:(?![\w.-]*?{_SECRET_KEY})[\w.-]+:)? ?[\w.-]+(?: [\w.-]+)?(?P=kq)"
    rf"|(?<![\w.-])(?=[\w.-]*?{_SECRET_KEY})[\w.-]+"
    r"(?:(?<=authorization)[ \t]+(?:header|value|field|credentials?))?"
    rf"(?P<tq>{_KEY_QUOTE})?)"
    rf"(?P<sep>\s*[=:]\s*|(?(kq)(?P<pair>{_PAIR_SPACE},{_PAIR_SPACE})|(?!)))"
    rf"(?:[bBuU]?(?P<dq>{_DQ})|[bBuU]?(?P<sq>{_SQ})|(?P<br>{_BRACKET})"
    rf"|(?:(?:Bearer|Basic)\s+)?{_BARE})?",
    re.IGNORECASE,
)
# An Authorization word followed on its line, within 64 characters and with no = or :
# in between, by an auth scheme and a credential ("Authorization header was Bearer x").
# Inside a repr or JSON string a space around the scheme may be an escape ("was\tBearer").
_ESCAPED_SPACE = r"\\(?:[tnrf]|x0[bc]|xa0|u000[bc]|u00a0)"
_AUTH_PHRASE = re.compile(
    r"(?<![\w-])(?=[\w-]*?authorization)[\w-]+(?![\w-])[^\r\n=:]{0,64}?"
    r"(?:(?<![\w-])|(?<=\\[tnrf])|(?<=\\x0[bc]|\\xa0)|(?<=\\u000[bc]|\\u00a0))"
    r"(?P<scheme>Basic|Bearer|Digest|Negotiate|NTLM|Token|ApiKey|AWS4-HMAC-SHA256|HOBA"
    rf"|Mutual|SCRAM-SHA-1|SCRAM-SHA-256|vapid|DPoP|OAuth)(?:[ \t]|{_ESCAPED_SPACE})+(?=\S)",
    re.IGNORECASE,
)
# The one form whose end is trusted for an Authorization value: a quoted key and a
# quoted value that closes its container, as json.dumps() and repr() of a mapping
# write it ({"Authorization": "...", "n": 1}).
_CLOSES_CONTAINER = re.compile(r"\s*(?:[,;})\]]|\Z)")
# A quoted or bracketed value ends where its token does: at whitespace, a , or ; or the
# end, after any quotes and brackets that close around it ("token='x'", "n": 1 or
# f(token=(x)) ...). "'x'y", "(x)y" and "(x)''y" run on into more text.
_ENDS_TOKEN = re.compile(r"""(?:\\{0,7}["']|[})\]])*(?:[\s,;]|\Z)""")
# A value opening with an escaped quote (a repr inside a JSON string) has no known end.
_ESCAPED_VALUE_QUOTE = re.compile(r"""[bBuU]?\\+["']""")
# A bare value ending in a secret key and its separator ("Basic x_token:", or "token"
# before " = ") swallowed that key, so the key's own value is not known.
_KEY_ENDS_VALUE = re.compile(
    rf"(?<![\w.-])(?=[\w.-]*?{_SECRET_KEY})[\w.-]+(?P<sep>[=:])?\Z", re.IGNORECASE
)
_SEPARATOR_NEXT = re.compile(r"[ \t]*[=:]")
# pprint wraps a long string into adjacent literals on the following lines.
_ADJACENT_LITERAL = re.compile(rf"[ \t]*\r?\n[ \t]*[bBuU]?(?:{_DQ}|{_SQ})")
# A quoted name before a comma is a name/value pair only as a tuple's first item, as the
# first item of a list inside a list or tuple (a list of pairs), or as a HAR "name" or
# "header" field; a list on its own, ['api_key', 'model'], is a list of names. The
# lookbehind leaves room for the line breaks, escaped or not, and the indentation of
# indented JSON.
_PAIR_CONTEXT = re.compile(
    rf"""(?:\({_PAIR_SPACE}[bBuU]?|[\[(,]{_PAIR_SPACE}\[{_PAIR_SPACE}[bBuU]?"""
    rf"""|(?<![\w-])(?:name|header)\\{{0,7}}["']{_PAIR_SPACE}:{_PAIR_SPACE})\Z""",
    re.IGNORECASE,
)
_PAIR_LOOKBEHIND = 64
# A pair goes on below its name's line when that line ends in a comma or an opening
# bracket, or the next line starts with a comma: a HAR entry written one field per
# line (json.dumps(..., indent=0), pprint or comma-first), whose value field may follow
# other fields. Their strings may hold any bracket, but no line break, so the entry's
# extent is read from its lines, never from the brackets inside its strings.
_PAIR_GOES_ON = re.compile(r"[^\n]*?(?:[,\[{][ \t\r]*\n|\n[ \t]*,)")
# A line that ends in an opening bracket, or one that starts with a closing one.
_STRUCTURE_LINE = re.compile(r"[\[{][ \t]*(?=\r?\n)|\r?\n(?P<indent>[ \t]*)[\]}]")
_CLOSER_NEXT = re.compile(r"\r?\n[\]}]")
_COMMA_NEXT = re.compile(r"\r?\n[ \t]*,")
# A HAR value field up to a fixed distance ahead with no brace before it. It only ever
# extends a pair's mask, over a value field that the lines do not place inside the
# entry: {"name": ..., "c": "x"\n"value": ...} or after a list opened inside a line.
_PAIR_VALUE_FIELD = re.compile(r"""[^{}]{0,512}?(?<![\w-])value\\{0,7}["']\s*:\s*""", re.IGNORECASE)
# A container whose scan failed (a string in it holds an escaped quote) and whose opening
# bracket ends its line, as json.dumps(..., indent=0) writes it, reaches the line where
# its closing bracket starts at the key's indentation or less, or else the end of the text.
_OPENS_LINE = re.compile(r"[\[{(][ \t]*\r?\n")
_CLOSING_LINE = re.compile(r"\n([ \t]*)([\]})])")
_CLOSERS = {"[": "]", "{": "}", "(": ")"}
_INDENT = re.compile(r"[ \t]*")
# A line break ends a header value unless the next line starts with a space or tab
# (a folded continuation line, RFC 9112 obs-fold); a lone "\r" does not end it.
_VALUE_LINE_END = re.compile(r"\r?\n(?![ \t])")
# Another key's value can hide an Authorization name from _ASSIGNMENT: by running into
# it, past a quote or an escaped line break in a JSON or repr string, or by ending at
# the quote that opens it ({'url': '?token=', 'Authorization': ...} matches ', ').
_AUTH_NAME = re.compile("authorization", re.IGNORECASE)
_AUTH_NAME_NEXT = re.compile(r"""\\{0,7}["']?[\w-]*authorization""", re.IGNORECASE)
_REDACTED = "***"
_CYCLE = "<cycle>"
# In a structured value, a secret name (or a Cookie or Set-Cookie header name) as the first
# item of a two-item list or tuple, or as the "name" or "header" field of a mapping with a
# "value" field (a HAR header), names the secret in the second item or the value field. In a
# list or tuple a bytes name counts when the value is bytes too, as raw headers hold them.
_PAIR_NAME = re.compile(rf"{_SECRET_KEY}|cookie", re.IGNORECASE)
_RAW_NAME = re.compile(_PAIR_NAME.pattern.encode(), re.IGNORECASE)
_NAME_FIELDS = frozenset({"name", "header"})
_MAPPING_FIELD = re.compile(
    r"%(?:%|\((?P<key>[^)]+)\)[#0 +\-]*\d*(?:\.\d+)?[hlL]?[diouxXeEfFgGcrsa])"
)
# LogRecord itself, not the configured factory: fields a factory adds are caller data.
_STANDARD_FIELDS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)))
_STANDARD_FIELDS |= {"message", "asctime"}
_METADATA = "name levelname pathname filename module funcName threadName processName taskName"
_TRAVERSAL = re.compile(r"\{[^{}]*[.\[][^{}]*" + _SECRET_KEY, re.IGNORECASE)


class _Matches:
    """The leftmost match at or after a position, for positions that never decrease.

    The text is searched again only once the position passes the last match (its
    group), so one redaction scans the text a bounded number of times however many
    keys it holds.
    """

    def __init__(self, pattern: re.Pattern[str], text: str, group: str | int = 0) -> None:
        self._pattern = pattern
        self._text = text
        self._group = group
        self._match = pattern.search(text)

    def at(self, position: int) -> re.Match[str] | None:
        if self._match is not None and self._match.start(self._group) < position:
            self._match = self._pattern.search(self._text, position)
        return self._match


def _line_end(text: str, start: int) -> int:
    """The end of the line holding start, after any folded continuation lines."""
    match = _VALUE_LINE_END.search(text, start)
    return match.start() if match else len(text)


def _masked_line_end(text: str, assignments: _Matches, value_start: int, end: int) -> int:
    """The end of the line holding end, extended over any secret value that starts
    before it and runs past it (a quoted value holding a line break)."""
    end = _line_end(text, end)
    position = value_start
    while (inner := assignments.at(position)) is not None and inner.start() < end:
        if inner.end() > end:
            end = _line_end(text, inner.end())
        position = inner.end()
    return end


def _value_end(text: str, match: re.Match[str]) -> int:
    """The end of the value, past adjacent literals that continue a quoted one."""
    end = match.end()
    if match.group("dq") or match.group("sq"):
        while adjacent := _ADJACENT_LITERAL.match(text, end):
            end = adjacent.end()
    return end


def _swallows_key(text: str, value_start: int, end: int) -> bool:
    """Whether the value ends in a secret key that a separator follows."""
    key = _KEY_ENDS_VALUE.search(text, value_start, end)
    return key is not None and (
        key.group("sep") is not None or _SEPARATOR_NEXT.match(text, end) is not None
    )


def _unsure(text: str, match: re.Match[str], end: int) -> bool:
    """Whether the value's end is uncertain, so the rest of its line is masked."""
    value_start = match.end("sep")
    quoted = match.group("dq") or match.group("sq") or ""
    if (
        "\\" in (match.group("kq") or "") + (match.group("tq") or "")
        or match.group("pair") is not None
        or quoted[-2:-1] == "\\"
        or (match.group("br") is None and text.startswith(("[", "{", "("), value_start))
        or ((quoted or match.group("br")) and not _ENDS_TOKEN.match(text, end))
        or _ESCAPED_VALUE_QUOTE.match(text, value_start) is not None
        or _swallows_key(text, value_start, end)
        or _AUTH_NAME.search(text, value_start, end) is not None
        or _AUTH_NAME_NEXT.match(text, end) is not None
    ):
        return True
    if _AUTH_NAME.search(match.group("key")) is None:
        return False
    trusted = quoted and match.group("kq") and end == match.end()
    return not (trusted and _CLOSES_CONTAINER.match(text, end))


def _indentation(text: str, position: int) -> int:
    """The width of the spaces and tabs that start the line holding position."""
    line_start = text.rfind("\n", 0, position) + 1
    indent = _INDENT.match(text, line_start, position)
    return indent.end() - line_start if indent else 0


def _container_end(text: str, match: re.Match[str]) -> int:
    """How far a value whose container scan failed reaches when its opening bracket
    ends its line: to the line where its closer starts at the key's indentation or
    less, or to the end of the text. The search runs once from the value; what it
    passes over is masked."""
    value_start = match.end("sep")
    if match.group("br") is not None or not _OPENS_LINE.match(text, value_start):
        return value_start
    closer = _CLOSERS[text[value_start]]
    indent = _indentation(text, match.start())
    for line in _CLOSING_LINE.finditer(text, value_start):
        if line.group(2) == closer and len(line.group(1)) <= indent:
            return line.end()
    return len(text)


def _structure_stop(text: str, position: int, indent: int) -> int:
    """Where the first line from position that starts with } or ] at indent or less
    begins, past the closers of containers opened at the end of a line on the way;
    the end of the text if there is none."""
    depth = 0
    for line in _STRUCTURE_LINE.finditer(text, position):
        if line.group("indent") is None:
            depth += 1
        elif depth:
            depth -= 1
        elif len(line.group("indent")) <= indent:
            return line.start()
    return len(text)


def _entry_stop(text: str, position: int, indent: int) -> int:
    """The line break before the first line that starts with an unindented } or ],
    once a line where a } or ] starts at indent or less has been passed with the
    indented lines after it; the end of the text if there is none."""
    while (stop := _structure_stop(text, position, indent)) < len(text):
        position = _line_end(text, stop)
        if _CLOSER_NEXT.match(text, position):
            return position
    return len(text)


def _reach(text: str, match: re.Match[str]) -> int:
    """How far an uncertain value reaches past its match: over a container's lines, or
    over the lines of a HAR entry that goes on below its name's line."""
    if match.group("pair") is None:
        return _container_end(text, match)
    name_end = match.end("key")
    if "\n" in match.group("pair") or _PAIR_GOES_ON.match(text, name_end):
        return _entry_stop(text, name_end, _indentation(text, match.start()))
    return match.end()


def _pair_end(text: str, match: re.Match[str], assignments: _Matches, end: int) -> int:
    """Where the mask of a name/value pair ends, from where its reach ends: on over a
    value field found ahead, and on to a line that starts with an unindented } or ]
    while a second pass would read the pair as going on below its name's line. That
    pass keeps the name, its separator and the text from the returned position, so it
    stops there too. The positions only move forward."""
    below = "\n" in match.group("pair")
    indent = _indentation(text, match.start())
    while end < len(text):
        if (below or _COMMA_NEXT.match(text, end)) and not _CLOSER_NEXT.match(text, end):
            end = _masked_line_end(text, assignments, end, _entry_stop(text, end, indent))
        elif (field := _PAIR_VALUE_FIELD.match(text, end)) is not None:
            end = _masked_line_end(text, assignments, end, field.end())
        else:
            break
    return end


def _masked_value(match: re.Match[str]) -> str:
    value = match.group(0)[match.end("sep") - match.start() :]
    quoted = match.group("dq") or match.group("sq")
    if quoted:
        # Keep a b or u prefix and the quotes: b'***'.
        return value[: len(value) - len(quoted) + 1] + _REDACTED + quoted[0]
    if match.group("br"):
        # Keep the brackets, so a masked value followed by "})" reads the same again.
        return value[0] + _REDACTED + value[-1]
    return _REDACTED if value else ""


def _redact_assignment(text: str, match: re.Match[str], assignments: _Matches) -> tuple[str, int]:
    """The masked text for one assignment and the position after what it replaces."""
    if match.group("pair") is not None and not _PAIR_CONTEXT.search(
        text, max(0, match.start() - _PAIR_LOOKBEHIND), match.start()
    ):
        return match.group("key"), match.end("key")
    head = match.group("key") + match.group("sep")
    value_start = match.end("sep")
    end = _value_end(text, match)
    if not _unsure(text, match, end):
        return head + _masked_value(match), end
    end = _masked_line_end(text, assignments, value_start, max(end, _reach(text, match)))
    if match.group("pair") is not None:
        end = _pair_end(text, match, assignments, end)
    return head + (_REDACTED if end > value_start else ""), end


def _redact_text(text: str) -> str:
    assignments = _Matches(_ASSIGNMENT, text)
    phrases = _Matches(_AUTH_PHRASE, text, "scheme")
    parts: list[str] = []
    done = 0
    while True:
        match = assignments.at(done)
        phrase = phrases.at(done)
        # A phrase also wins when its scheme is inside a quoted key ('Bearer token1').
        if phrase is not None and (match is None or phrase.start("scheme") < match.end("key")):
            start = phrase.start("scheme")
            parts += (text[done:start], _REDACTED)
            done = _masked_line_end(text, assignments, start, phrase.end())
        elif match is not None:
            masked, end = _redact_assignment(text, match, assignments)
            parts += (text[done : match.start()], masked)
            done = end
        else:
            break
    parts.append(text[done:])
    return "".join(parts)


def _redact_item(key: Any, value: Any, active: frozenset[int]) -> tuple[Any, Any]:
    if isinstance(key, (str, int, float)) or key is None:
        return key, _REDACTED if _KEY_PATTERN.search(str(key)) else _redact(value, active)
    # json.dumps rejects other key types, and a composite key such as
    # ("api", "key") can split a secret name, so stringify it and fail closed.
    return _redact(str(key), active), _REDACTED


def _names_secret(name: Any, value: Any) -> bool:
    if isinstance(name, str):
        return _PAIR_NAME.search(name) is not None
    raw = isinstance(name, (bytes, bytearray)) and isinstance(value, (bytes, bytearray))
    return raw and _RAW_NAME.search(name) is not None


def _pair_masked(values: list[Any], masked: list[Any]) -> list[Any]:
    """The redacted items, with the second masked when the first of two names a secret."""
    if len(values) == 2 and _names_secret(*values):
        masked[1] = _REDACTED
    return masked


def _redact_items(obj: list[Any] | tuple[Any, ...], active: frozenset[int]) -> list[Any]:
    # One pass over obj: list(obj) would also call a subclass's __len__.
    values = [value for value in obj]
    return _pair_masked(values, [_redact(value, active) for value in values])


def _field(key: Any) -> str | None:
    # str.lower, so that a str subclass's own lower() is never called.
    return str.lower(key) if isinstance(key, str) else None


def _redact_mapping(obj: Mapping[Any, Any], active: frozenset[int]) -> dict[Any, Any]:
    items = list(obj.items())
    entry = any(_field(key) in _NAME_FIELDS and _names_secret(name, None) for key, name in items)
    return dict(
        (key, _REDACTED) if entry and _field(key) == "value" else _redact_item(key, value, active)
        for key, value in items
    )


def _redact_fields(obj: tuple[Any, ...], active: frozenset[int]) -> tuple[Any, ...]:
    # A constructor may change what it is given, so none runs. A class with its own __new__ must
    # declare _fields, and a probe of sentinels must read and print each name at its own slot.
    # Iteration or indexing that a class replaces can reorder the slots, so it is never called:
    # slots are read through tuple, and such a class is masked whole.
    values = list(tuple.__iter__(obj))
    with contextlib.suppress(Exception):
        cls, marks = type(obj), [object() for _ in values]
        below = cls.__mro__[: cls.__mro__.index(tuple)]
        owner = vars(next(c for c in cls.__mro__ if "_fields" in vars(c) or "__new__" in vars(c)))
        names, probe = list(owner["_fields"]), tuple.__new__(cls, marks)
        shown = ", ".join(f"{n}={m!r}" for n, m in zip(names, marks, strict=True))
        reorders = any("__iter__" in vars(c) or "__getitem__" in vars(c) for c in below)
        if not reorders and repr(probe) == f"{cls.__name__}({shown})":
            if all(getattr(probe, n) is m for n, m in zip(names, marks)):
                fields = [_redact_item(*p, active)[1] for p in zip(names, values)]
                return tuple.__new__(cls, _pair_masked(values, fields))
    return (_REDACTED,) * len(values)


def _redact(obj: Any, active: frozenset[int]) -> Any:
    if isinstance(obj, (Mapping, list, tuple)):
        if id(obj) in active:
            return _CYCLE
        active = active | {id(obj)}
    if isinstance(obj, Mapping):
        return _redact_mapping(obj, active)
    if isinstance(obj, list):
        return _redact_items(obj, active)
    if isinstance(obj, tuple):
        named = hasattr(type(obj), "_fields")
        return _redact_fields(obj, active) if named else tuple(_redact_items(obj, active))
    if isinstance(obj, (set, frozenset)):
        items = (_redact(value, active) for value in obj)
        return frozenset(items) if isinstance(obj, frozenset) else set(items)
    if isinstance(obj, str):
        return _redact_text(obj)
    if isinstance(obj, (bytes, bytearray)):
        try:
            masked = _redact_text(obj.decode()).encode()
        except UnicodeDecodeError:  # undecodable text cannot be searched for a secret name
            masked = _REDACTED.encode()
        return bytearray(masked) if isinstance(obj, bytearray) else masked
    return obj


def redact(obj: Any) -> Any:
    """Copy nested mappings/sequences/sets, masking sensitive keys and assignments.

    Mapping keys other than str/int/float/None become strings, with the value
    masked, so the result is always JSON-encodable as far as keys go. A
    container that contains itself is replaced by "<cycle>" where it recurs.
    Sets, frozensets, bytes and bytearrays keep their type; bytes are masked as
    UTF-8 text, and bytes that are not UTF-8 are masked whole.
    A two-item list or tuple whose first item names a secret (a str secret name,
    Cookie and Set-Cookie included, or such a bytes name with a bytes value), and
    a mapping whose "name" or "header" field, in any case, holds such a str name,
    have their second item or "value" field masked at any depth;
    ["api_key", "model"] is masked the same way.
    An Authorization value (under any key containing "authorization", or after
    Authorization phrasing and a scheme) is masked to the end of its line, folded
    continuation lines included, also inside a JSON or repr string; only a quoted
    key with a quoted value that closes its container masks just that string.
    The rest of the line is masked too after an escaped key quote, a name/value
    pair in text (a tuple, a list inside a list or tuple, or a HAR "name" or
    "header" field), an unbalanced bracket, or a value that runs
    into an Authorization name, and a secret value that crosses that line end
    is masked to the end of its own line. A HAR entry written one field per line
    is masked from its name, its other fields included, up to an unindented line
    that starts with } or ] once the entry has closed at the name's indentation,
    or to the end of the text; a HAR value field found shortly after the masked
    text is masked with it. An unbalanced bracket that ends its line masks the
    lines up to its closing bracket at the key's indentation.
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
    # Two arguments are not a name/value pair, so each one is redacted on its own.
    args = record.args
    safe.args = tuple(map(redact, args)) if type(args) is tuple else redact(args)
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
    """One JSON object per line, including redacted structured extras.

    Its own fields (ts, level, logger, msg, format_error, exception, stack) come from the record;
    an extra with one of those names moves to extra_<name>, prefixed again while that is taken.
    """

    def format(self, record: logging.LogRecord) -> str:
        return _format_safely(self._render, record)

    def _render(self, record: logging.LogRecord) -> str:
        message, error = _message(record)
        data = {key: value for key, value in record.__dict__.items() if key not in _STANDARD_FIELDS}
        for key in ("ts", "level", "logger", "msg", "format_error", "exception", "stack"):
            if key in data:
                moved = f"extra_{key}"
                while moved in data:
                    moved = f"extra_{moved}"
                data[moved] = data.pop(key)
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
    """Human-readable output, redacted field by field, then as a line except for logger metadata.

    Extras and format defaults named like a secret print as ***; brace fields reaching into a
    secret-named attribute or item fail like other formatting errors. Logger, level, path, module,
    function, thread, process and task names never count as a secret's name or mask the message.
    """

    def format(self, record: logging.LogRecord) -> str:
        return _format_safely(self._render, record)

    def _render(self, record: logging.LogRecord) -> str:
        if isinstance(self._style, logging.StrFormatStyle) and _TRAVERSAL.search(self._style._fmt):
            raise ValueError("a brace field reaches into a secret")
        defaults = getattr(self._style, "_defaults", None) or {}
        safe = copy.copy(record)
        extras = {key: value for key, value in vars(record).items() if key not in _STANDARD_FIELDS}
        safe.__dict__.update(redact(dict.fromkeys(filter(_KEY_PATTERN.search, defaults)) | extras))
        safe.msg, safe.args, safe.exc_text = _message(record)[0], (), None
        # One private-use character per metadata character: never a secret's name, width-safe.
        table: dict[int, str] = {}
        for key in _METADATA.split():
            if isinstance(value := getattr(record, key, None), str):
                hidden = range(0xF0000 + len(table), 0xF0000 + len(table) + len(value))
                table.update(zip(hidden, value))
                setattr(safe, key, "".join(map(chr, hidden)))
        return _redact_text(super().format(safe)).translate(table)


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
