#!/usr/bin/env python3
"""Per-tool output parsers for ``scripts/ci/check_tool_baseline.py``.

Each parser is a pure function ``parse(stdout: str) -> list[Finding]`` that
turns one tool's captured stdout into findings. Parsers never touch the file
system and never run anything, so they are trivially unit-testable against a
captured real-output fixture under ``tests/ci/fixtures/tool_baseline/``.

Adding a parser is a one-function change: write the function and decorate it
with ``@register("<tool>", ...)``. The runner discovers it through ``PARSERS``
and the ``--tool`` choices, usage text, and ``docs/RATCHETS.md`` table follow.

Finding keys
------------
A finding is keyed as ``<path>::<symbol>::<rule>``:

* ``path`` -- POSIX path relative to the runner's ``--cwd`` (parsers hand back
  whatever the tool printed; the runner normalises it);
* ``symbol`` -- either a symbol name the tool reports (vulture, deptry,
  jscpd, ...) or a 12-hex-digit SHA-256 prefix of the offending source line's
  stripped content. Line numbers are deliberately NOT part of the key, so a
  pure line shift never surfaces as a new finding. A parser that leaves
  ``symbol`` empty and sets ``line`` asks the runner to compute the content
  hash from the file (``ToolSpec.symbol_from_line``);
* ``rule`` -- the tool's rule/error code (``F401``, ``arg-type``, ``TODO``).

Stdlib only: this module runs in CI before project dependencies are installed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

KEY_SEPARATOR = "::"
LINE_HASH_LENGTH = 12


@dataclass(frozen=True)
class Finding:
    """One tool finding.

    ``symbol`` may be empty when ``line`` is set: the runner then fills it with
    the content hash of that source line (see ``ToolSpec.symbol_from_line``).
    ``line`` and ``message`` are informational only and never enter the key.
    """

    path: str
    rule: str
    symbol: str = ""
    line: int | None = None
    message: str = ""

    def key(self) -> str:
        return KEY_SEPARATOR.join((self.path, self.symbol, self.rule))


ParseFn = Callable[[str], list[Finding]]


@dataclass(frozen=True)
class ToolSpec:
    """Registry entry describing how the runner should treat one tool."""

    name: str
    parse: ParseFn
    description: str
    example_command: str
    # Exit codes that mean "ran fine, zero findings" when stdout parses to
    # nothing. Any other exit code with zero parsed findings is a tool crash.
    clean_exit_codes: frozenset[int] = field(default_factory=lambda: frozenset({0}))
    # Codes signalling findings. Codes outside clean | finding are failures,
    # even if stdout contains parseable partial findings.
    finding_exit_codes: frozenset[int] = field(default_factory=frozenset)
    # True when the parser leaves ``symbol`` empty and the runner must hash the
    # offending source line read from ``--cwd``.
    symbol_from_line: bool = False


PARSERS: dict[str, ToolSpec] = {}


def register(
    name: str,
    *,
    description: str,
    example_command: str,
    clean_exit_codes: frozenset[int] | set[int] = frozenset({0}),
    finding_exit_codes: frozenset[int] | set[int] = frozenset(),
    symbol_from_line: bool = False,
) -> Callable[[ParseFn], ParseFn]:
    """Decorator registering ``parse`` under ``--tool <name>``."""

    def decorator(fn: ParseFn) -> ParseFn:
        if name in PARSERS:
            raise ValueError(f"parser already registered: {name}")
        PARSERS[name] = ToolSpec(
            name=name,
            parse=fn,
            description=description,
            example_command=example_command,
            clean_exit_codes=frozenset(clean_exit_codes),
            finding_exit_codes=frozenset(finding_exit_codes),
            symbol_from_line=symbol_from_line,
        )
        return fn

    return decorator


def line_hash(content: str) -> str:
    """Stable short hash of a source line, whitespace-insensitive at the ends."""
    return hashlib.sha256(content.strip().encode("utf-8", "replace")).hexdigest()[:LINE_HASH_LENGTH]


def supported_tools() -> list[str]:
    return sorted(PARSERS)


def _load_json_prefix(stdout: str) -> Any:
    """Decode the first JSON value in ``stdout``; anything after it is ignored.

    Some tools append a human-readable summary after their JSON document on the
    same stream (golangci-lint's stats block), which makes ``json.loads`` fail
    with "Extra data". Returns ``None`` for empty or non-JSON output so the
    runner's exit-code logic decides whether that is a clean run or a crash.
    """
    text = stdout.lstrip()
    if not text:
        return None
    try:
        value, _end = json.JSONDecoder().raw_decode(text)
    except json.JSONDecodeError:
        return None
    return value


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _sub_object(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    return value if isinstance(value, dict) else {}


# --- ruff -------------------------------------------------------------------

# ``ruff check --output-format concise``:
#   pkg/mod.py:1:8: F401 [*] `os` imported but unused
#   pkg/mod.py:3:1: invalid-syntax: unexpected indentation
_RUFF_RE = re.compile(
    r"^(?P<path>[^:\n]+?):(?P<line>\d+):(?P<col>\d+): "
    r"(?P<rule>[A-Za-z][A-Za-z0-9-]*):? (?:\[\*\] )?(?P<msg>.*)$"
)


@register(
    "ruff",
    description="ruff check, concise output; key = line-content hash",
    example_command="ruff check <paths> --select N --output-format concise",
    clean_exit_codes={0},
    finding_exit_codes={1},
    symbol_from_line=True,
)
def parse_ruff(stdout: str) -> list[Finding]:
    findings: list[Finding] = []
    for raw in stdout.splitlines():
        match = _RUFF_RE.match(raw)
        if match is None:
            continue
        findings.append(
            Finding(
                path=match["path"],
                rule=match["rule"],
                line=int(match["line"]),
                message=match["msg"].strip(),
            )
        )
    return findings


# --- mypy -------------------------------------------------------------------

# ``mypy`` default text output (with or without --show-column-numbers):
#   pkg/mod.py:11: error: Incompatible return value type ...  [return-value]
#   pkg/mod.py:11:5: error: ...  [arg-type]
#   pkg/mod.py:11: note: ...            (notes are not findings)
_MYPY_RE = re.compile(
    r"^(?P<path>[^:\n]+?):(?P<line>\d+)(?::(?P<col>\d+))?: "
    r"(?P<severity>error|warning): (?P<msg>.*?)(?:  \[(?P<code>[\w-]+)\])?$"
)


@register(
    "mypy",
    description="mypy text output (errors and warnings; notes ignored); key = line-content hash",
    example_command="mypy --ignore-missing-imports <paths>",
    clean_exit_codes={0},
    finding_exit_codes={1},
    symbol_from_line=True,
)
def parse_mypy(stdout: str) -> list[Finding]:
    findings: list[Finding] = []
    for raw in stdout.splitlines():
        match = _MYPY_RE.match(raw)
        if match is None:
            continue
        findings.append(
            Finding(
                path=match["path"],
                rule=match["code"] or match["severity"],
                line=int(match["line"]),
                message=match["msg"].strip(),
            )
        )
    return findings


# --- todo (grep) ------------------------------------------------------------

# ``grep -rn --include='*.py' -E 'TODO|FIXME' .``:
#   ./pkg/mod.py:10:    # TODO: make this real
# The content is already in the output, so the parser hashes it itself; the
# marker word becomes the rule so a TODO turned FIXME is a new finding.
_GREP_RE = re.compile(r"^(?P<path>[^:\n]+?):(?P<line>\d+):(?P<content>.*)$")
_TODO_MARKER_RE = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b")


@register(
    "todo",
    description="grep -rn output for TODO/FIXME markers; key = matched-line hash, rule = marker",
    example_command="grep -rn --include='*.py' -E 'TODO|FIXME' .",
    # grep exits 1 when nothing matches: that is zero findings, not a crash.
    clean_exit_codes={0, 1},
    finding_exit_codes={0},
)
def parse_todo(stdout: str) -> list[Finding]:
    findings: list[Finding] = []
    for raw in stdout.splitlines():
        match = _GREP_RE.match(raw)
        if match is None:
            continue
        content = match["content"]
        marker = _TODO_MARKER_RE.search(content)
        findings.append(
            Finding(
                path=match["path"],
                rule=marker.group(1) if marker else "TODO",
                symbol=line_hash(content),
                line=int(match["line"]),
                message=content.strip(),
            )
        )
    return findings


# --- vulture ----------------------------------------------------------------

# ``vulture <paths>`` (exit 3 when it reports anything):
#   pkg/mod.py:3: unused import 'yaml' (90% confidence)
#   pkg/mod.py:14: unused method 'unused_method' (60% confidence)
#   pkg/mod.py:20: unreachable code after 'return' (100% confidence)
# Named findings key on the symbol so the confidence and line are free to
# move; the rule is ``unused-<kind>``. Unnamed findings (unreachable code,
# unsatisfiable conditions) leave ``symbol`` empty and the runner hashes the
# message.
_VULTURE_RE = re.compile(r"^(?P<path>[^:\n]+?):(?P<line>\d+): (?P<msg>.*)$")
_VULTURE_NAMED_RE = re.compile(r"^unused (?P<kind>[a-z]+) '(?P<name>[^']+)'")
_VULTURE_RULE_RE = re.compile(r"^(?P<rule>[a-z]+(?: [a-z]+)*?)(?: after| '| \()")


@register(
    "vulture",
    description="vulture dead-code report; key = symbol name, rule = unused-<kind>",
    example_command="vulture <paths> --min-confidence 80",
    clean_exit_codes={0},
    finding_exit_codes={3},
)
def parse_vulture(stdout: str) -> list[Finding]:
    findings: list[Finding] = []
    for raw in stdout.splitlines():
        match = _VULTURE_RE.match(raw)
        if match is None:
            continue
        msg = match["msg"].strip()
        named = _VULTURE_NAMED_RE.match(msg)
        if named is not None:
            rule = f"unused-{named['kind']}"
            symbol = named["name"]
        else:
            rule_match = _VULTURE_RULE_RE.match(msg)
            rule = (rule_match["rule"] if rule_match else "vulture").replace(" ", "-")
            symbol = ""
        findings.append(
            Finding(
                path=match["path"],
                rule=rule,
                symbol=symbol,
                line=int(match["line"]),
                message=msg,
            )
        )
    return findings


# --- deptry (JSON) ------------------------------------------------------------

# ``deptry <root> --json-output /dev/stdout`` (exit 1 with issues); the human
# report goes to stderr. stdout is a list of
#   {"error": {"code": "DEP003", "message": "..."},
#    "module": "yaml", "location": {"file": "pkg/mod.py", "line": 3, "column": 8}}
# ``line``/``column`` are null for dependency-file findings (DEP002).


@register(
    "deptry",
    description="deptry --json-output; key = module name, rule = DEP code",
    example_command="deptry <root> --json-output /dev/stdout",
    clean_exit_codes={0},
    finding_exit_codes={1},
)
def parse_deptry(stdout: str) -> list[Finding]:
    data = _load_json_prefix(stdout)
    if not isinstance(data, list):
        return []
    findings: list[Finding] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        error = _sub_object(item, "error")
        location = _sub_object(item, "location")
        path = location.get("file")
        if not isinstance(path, str) or not path:
            continue
        findings.append(
            Finding(
                path=path,
                rule=str(error.get("code") or "deptry"),
                symbol=str(item.get("module") or ""),
                line=_int_or_none(location.get("line")),
                message=str(error.get("message") or ""),
            )
        )
    return findings


# --- jscpd (JSON) -------------------------------------------------------------

# jscpd's ``json`` reporter writes ``<--output DIR>/jscpd-report.json`` and
# never prints the report to stdout (its console lines are coloured even under
# NO_COLOR), so the wired command must cat the report file:
#   sh -c 'jscpd --reporters json --output DIR --silent . >/dev/null; cat DIR/jscpd-report.json'
# Report shape: {"duplicates": [{"firstFile": {"name", "start", "end", ...},
# "secondFile": {...}, "format", "fragment", "lines", "tokens"}], "statistics": {...}}.
# ``name`` is relative to the scanned path, so scan ``.`` from ``--cwd``.
# A clone keys on its first file plus the hash of the duplicated fragment, so it
# survives line shifts; a third copy of the same fragment raises the count.


@register(
    "jscpd",
    description="jscpd JSON report (jscpd-report.json on stdout); key = fragment hash, rule = clone",
    example_command=(
        "sh -c 'jscpd --reporters json --output DIR --silent . >/dev/null; "
        "cat DIR/jscpd-report.json'"
    ),
    clean_exit_codes={0},
    finding_exit_codes={0},
)
def parse_jscpd(stdout: str) -> list[Finding]:
    data = _load_json_prefix(stdout)
    if not isinstance(data, dict):
        return []
    duplicates = data.get("duplicates")
    if not isinstance(duplicates, list):
        return []
    findings: list[Finding] = []
    for dup in duplicates:
        if not isinstance(dup, dict):
            continue
        first = _sub_object(dup, "firstFile")
        second = _sub_object(dup, "secondFile")
        path = first.get("name")
        if not isinstance(path, str) or not path:
            continue
        fragment = dup.get("fragment")
        if not isinstance(fragment, str) or not fragment:
            fragment = f"{path}|{second.get('name', '')}|{dup.get('tokens', '')}"
        second_name = second.get("name", "?")
        findings.append(
            Finding(
                path=path,
                rule="clone",
                symbol=line_hash(fragment),
                line=_int_or_none(first.get("start")),
                message=(
                    f"{dup.get('lines', '?')} lines / {dup.get('tokens', '?')} tokens "
                    f"duplicated in {second_name}:{second.get('start', '?')}"
                ),
            )
        )
    return findings


# --- eslint (JSON) ------------------------------------------------------------

# ``eslint -f json <paths>`` (exit 1 with findings): a list of
#   {"filePath": "/abs/path/src/a.js",
#    "messages": [{"ruleId": "no-var", "severity": 2, "message": "...", "line": 1, ...}], ...}
# ``filePath`` is absolute; the runner makes it relative to ``--cwd``. A fatal
# parse error has ``ruleId: null`` and is keyed under rule ``fatal``.


@register(
    "eslint",
    description="eslint -f json; key = line-content hash, rule = ruleId",
    example_command="eslint -f json <paths>",
    clean_exit_codes={0},
    finding_exit_codes={1},
    symbol_from_line=True,
)
def parse_eslint(stdout: str) -> list[Finding]:
    data = _load_json_prefix(stdout)
    if not isinstance(data, list):
        return []
    findings: list[Finding] = []
    for result in data:
        if not isinstance(result, dict):
            continue
        path = result.get("filePath")
        messages = result.get("messages")
        if not isinstance(path, str) or not path or not isinstance(messages, list):
            continue
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            rule = msg.get("ruleId")
            findings.append(
                Finding(
                    path=path,
                    rule=str(rule) if rule else "fatal",
                    line=_int_or_none(msg.get("line")),
                    message=str(msg.get("message") or ""),
                )
            )
    return findings


# --- golangci-lint (v2 JSON) ----------------------------------------------------

# ``golangci-lint run --output.json.path stdout --show-stats=false ./...`` (v2
# schema; exit 1 with issues):
#   {"Issues": [{"FromLinter": "errcheck", "Text": "...", "Severity": "",
#                "SourceLines": ["\tf.Close()"],
#                "Pos": {"Filename": "main.go", "Offset": 148, "Line": 11, "Column": 9}, ...}],
#    "Report": {"Linters": [...]}}
# Without ``--show-stats=false`` a text stats block follows the JSON on the same
# stream; only the first JSON object is read. ``Issues`` is null when clean.
# ``SourceLines[0]`` is the offending line, so the content hash is taken from
# the report itself; the runner reads the file only when it is missing.


@register(
    "golangci-lint",
    description="golangci-lint v2 JSON (--output.json.path stdout); key = line-content hash, rule = linter",
    example_command="golangci-lint run --output.json.path stdout --show-stats=false ./...",
    clean_exit_codes={0},
    finding_exit_codes={1},
    symbol_from_line=True,
)
def parse_golangci_lint(stdout: str) -> list[Finding]:
    data = _load_json_prefix(stdout)
    if not isinstance(data, dict):
        return []
    issues = data.get("Issues")
    if not isinstance(issues, list):
        return []
    findings: list[Finding] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        pos = _sub_object(issue, "Pos")
        path = pos.get("Filename")
        if not isinstance(path, str) or not path:
            continue
        source_lines = issue.get("SourceLines")
        first_line = (
            source_lines[0]
            if isinstance(source_lines, list) and source_lines and isinstance(source_lines[0], str)
            else ""
        )
        findings.append(
            Finding(
                path=path,
                rule=str(issue.get("FromLinter") or "golangci-lint"),
                symbol=line_hash(first_line) if first_line.strip() else "",
                line=_int_or_none(pos.get("Line")),
                message=str(issue.get("Text") or ""),
            )
        )
    return findings
