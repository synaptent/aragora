#!/usr/bin/env python3
"""Advisory checker for chartered architecture removals and exclusions."""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


DRAFT_BINDING_IDS = {
    "CHR-P4A-001",
    "CHR-P4A-002",
    "CHR-P4A-003",
    "CHR-P4A-004",
    "CHR-X-007",
}
ENFORCED_STATES = {"REMOVED", "EXCLUSION", "PENDING", "EXPIRING", "PARKED"}
FROM_IMPORT_RE = re.compile(r"^\s*from\s+([A-Za-z_][\w.]*)\s+import\s+(.+)$")
PLAIN_IMPORT_RE = re.compile(r"^\s*import\s+(.+)$")
HUNK_RE = re.compile(r"@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")
WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass(frozen=True)
class CharterEntry:
    entry_id: str
    state: str
    paths: tuple[str, ...]
    symbols: tuple[str, ...]
    kept_symbols: tuple[str, ...]
    binding: str


@dataclass(frozen=True)
class AddedLine:
    path: str
    line_no: int | None
    line: str
    hunk: int = 0


@dataclass(frozen=True)
class Violation:
    binding: str
    entry_id: str
    state: str
    path: str
    line_no: int | None
    line: str
    reason: str
    authority_ids: list[str]


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    binding_violations: list[Violation]
    proposed_violations: list[Violation]
    violations: list[Violation]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "binding_violations": [asdict(violation) for violation in self.binding_violations],
            "proposed_violations": [asdict(violation) for violation in self.proposed_violations],
            "violations": [asdict(violation) for violation in self.violations],
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _normalize_diff_path(raw: str) -> str | None:
    raw = raw.strip()
    if raw == "/dev/null":
        return None
    if raw.startswith("a/") or raw.startswith("b/"):
        raw = raw[2:]
    if raw.startswith("./"):
        raw = raw[2:]
    return raw or None


def _path_matches(pattern: str, path: str) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False
    if pattern.startswith("./"):
        pattern = pattern[2:]
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return path == pattern or fnmatch.fnmatch(path, pattern)


def _path_to_module(path: str) -> str:
    if path.endswith("/__init__.py"):
        path = path[: -len("/__init__.py")]
    elif path.endswith(".py"):
        path = path[:-3]
    return path.replace("/", ".")


def _path_pattern_to_modules(pattern: str) -> tuple[str, ...]:
    pattern = pattern.strip().rstrip("/")
    if not pattern:
        return ()
    if pattern.endswith(".py") or pattern.endswith("/__init__.py"):
        return (_path_to_module(pattern),)
    return (pattern.replace("/", "."),)


def _symbol_module(symbol: str) -> str | None:
    if ":" not in symbol:
        return None
    return symbol.split(":", 1)[0]


def _symbol_export(symbol: str) -> str:
    export = symbol.split(":", 1)[-1]
    return export.rsplit(".", 1)[-1]


def _symbol_root_export(symbol: str) -> str:
    export = symbol.split(":", 1)[-1]
    return export.split(".", 1)[0]


def _symbol_export_roots(symbols: Iterable[str]) -> set[str]:
    roots: set[str] = set()
    for symbol in symbols:
        root = _symbol_root_export(symbol)
        if root:
            roots.add(root)
    return roots


def _is_top_level_symbol(symbol: str) -> bool:
    return "." not in symbol.split(":", 1)[-1]


def _parse_imported_names(imports: str) -> list[str]:
    cleaned = imports.split("#", 1)[0].strip()
    # The parens are stripped independently so an opener whose closer was not part of
    # the diff (an unchanged ``)`` under --unified=0) still yields its names.
    if cleaned.startswith("("):
        cleaned = cleaned[1:]
    if cleaned.endswith(")"):
        cleaned = cleaned[:-1]
    names: list[str] = []
    for part in cleaned.split(","):
        token = part.strip()
        if not token:
            continue
        names.append(token.split(" as ", 1)[0].strip())
    return names


def _from_import(line: str) -> tuple[str, list[str]] | None:
    match = FROM_IMPORT_RE.match(line)
    if not match:
        return None
    return match.group(1), _parse_imported_names(match.group(2))


def _plain_import_modules(line: str) -> list[str]:
    match = PLAIN_IMPORT_RE.match(line)
    if not match:
        return []
    modules: list[str] = []
    for part in match.group(1).split(","):
        token = part.strip()
        if not token:
            continue
        modules.append(token.split(" as ", 1)[0].strip())
    return modules


def _plain_import_aliases(line: str) -> dict[str, str]:
    match = PLAIN_IMPORT_RE.match(line)
    if not match:
        return {}
    aliases: dict[str, str] = {}
    for part in match.group(1).split(","):
        token = part.strip()
        if not token or " as " not in token:
            continue
        module, alias = [piece.strip() for piece in token.split(" as ", 1)]
        if module and alias:
            aliases[alias] = module
    return aliases


def _line_mentions_symbol(line: str, symbol: str) -> bool:
    export = _symbol_export(symbol)
    return bool(re.search(rf"\b{re.escape(export)}\b", line))


def _is_python_path(path: str) -> bool:
    return path.endswith((".py", ".pyi"))


def _line_reexports_or_defines_symbol(line: str, symbol: str) -> bool:
    return _line_reexports_or_defines_export(line, _symbol_export(symbol))


def _line_reexports_or_defines_export(
    line: str,
    export: str,
    *,
    allow_wildcard: bool = True,
) -> bool:
    if line[:1].isspace():
        return False
    from_import = _from_import(line)
    if from_import is not None:
        _module, names = from_import
        return export in names or (allow_wildcard and "*" in names)
    return bool(
        re.match(rf"^(?:async\s+def|def|class)\s+{re.escape(export)}\b", line)
        or re.match(rf"^{re.escape(export)}\s*=", line)
    )


def _line_reexports_or_defines_kept_symbol(line: str, entry: CharterEntry) -> bool:
    return any(
        _line_reexports_or_defines_export(
            line,
            _symbol_root_export(symbol),
            allow_wildcard=False,
        )
        for symbol in entry.kept_symbols
        if _is_top_level_symbol(symbol)
    )


def _module_is_under(module: str, parent: str) -> bool:
    return module == parent or module.startswith(f"{parent}.")


def _line_imports_path(line: str, path_pattern: str) -> bool:
    modules = _path_pattern_to_modules(path_pattern)
    if not modules:
        return False
    from_import = _from_import(line)
    if from_import is not None:
        module, _names = from_import
        return any(_module_is_under(module, parent) for parent in modules)
    return any(
        _module_is_under(imported, parent)
        for imported in _plain_import_modules(line)
        for parent in modules
    )


def _line_uses_symbol_reference(
    line: str,
    symbol: str,
    aliases_by_module: dict[str, set[str]],
) -> bool:
    module_name = _symbol_module(symbol)
    if module_name is None:
        return False
    export = _symbol_export(symbol)
    refs = [module_name, *sorted(aliases_by_module.get(module_name, set()))]
    return any(
        re.search(rf"(?<![\w.]){re.escape(ref)}\.{re.escape(export)}\b", line) for ref in refs
    )


def _line_imports_symbol(
    line: str,
    symbol: str,
    aliases_by_module: dict[str, set[str]] | None = None,
) -> bool:
    aliases_by_module = aliases_by_module or {}
    if _line_uses_symbol_reference(line, symbol, aliases_by_module):
        return True
    module_name = _symbol_module(symbol)
    export = _symbol_export(symbol)
    if module_name is None:
        return _line_mentions_symbol(line, symbol)
    from_import = _from_import(line)
    if from_import is not None:
        imported_module, names = from_import
        return imported_module == module_name and (export in names or "*" in names)
    return any(
        imported == module_name for imported in _plain_import_modules(line)
    ) and _line_mentions_symbol(
        line,
        symbol,
    )


def _line_is_kept_only(added_line: AddedLine, entry: CharterEntry) -> bool:
    if not entry.kept_symbols:
        return False
    line = added_line.line
    kept_exports = _symbol_export_roots(entry.kept_symbols)
    from_import = _from_import(line)
    if from_import is not None:
        imported_module, names = from_import
        matching_kept = [
            symbol for symbol in entry.kept_symbols if _symbol_module(symbol) == imported_module
        ]
        if matching_kept:
            return bool(names) and all(name != "*" and name in kept_exports for name in names)
        return False
    if any(_path_matches(path, added_line.path) for path in entry.paths):
        return _line_reexports_or_defines_kept_symbol(line, entry)
    return False


def parse_diff(diff_text: str) -> list[AddedLine]:
    added: list[AddedLine] = []
    current_path: str | None = None
    current_line: int | None = None
    hunk = 0
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("+++ "):
            current_path = _normalize_diff_path(raw_line[4:].split("\t", 1)[0])
            current_line = None
            continue
        if raw_line.startswith("@@"):
            match = HUNK_RE.search(raw_line)
            current_line = int(match.group(1)) if match else None
            hunk += 1
            continue
        if current_path is None:
            continue
        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            added.append(AddedLine(current_path, current_line, raw_line[1:], hunk))
            if current_line is not None:
                current_line += 1
        elif raw_line.startswith("-"):
            continue
        elif current_line is not None:
            current_line += 1
    return added


def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0].rstrip()


def _opens_parenthesized_import(line: str) -> bool:
    match = FROM_IMPORT_RE.match(_strip_comment(line))
    if match is None:
        return False
    imports = match.group(2)
    return "(" in imports and ")" not in imports


def _is_next_source_line(previous: AddedLine, current: AddedLine) -> bool:
    return (
        current.path == previous.path
        and current.hunk == previous.hunk
        and previous.line_no is not None
        and current.line_no == previous.line_no + 1
    )


def reconstruct_multiline_imports(added_lines: list[AddedLine]) -> list[AddedLine]:
    """Join parenthesized ``from … import (`` statements that span several added lines.

    Only consecutive added source lines of one hunk of one Python file are joined, so
    neighbouring files, separate hunks or intervening context lines never form one
    statement. The joined line keeps the opener's path and line number, which is the
    statement's original source location; comments are dropped per physical line so a
    trailing ``# noqa`` on the opener cannot hide the names that follow it.
    """
    logical: list[AddedLine] = []
    index = 0
    while index < len(added_lines):
        opener = added_lines[index]
        if not (_is_python_path(opener.path) and _opens_parenthesized_import(opener.line)):
            logical.append(opener)
            index += 1
            continue
        parts = [_strip_comment(opener.line)]
        end = index
        while end + 1 < len(added_lines) and _is_next_source_line(
            added_lines[end], added_lines[end + 1]
        ):
            end += 1
            piece = _strip_comment(added_lines[end].line).strip()
            if piece:
                parts.append(piece)
            if ")" in piece:
                break
        logical.append(AddedLine(opener.path, opener.line_no, " ".join(parts), opener.hunk))
        index = end + 1
    return logical


def load_charter_entries(
    charter_path: Path,
) -> tuple[list[CharterEntry], dict[str, list[str]], str]:
    data = yaml.safe_load(charter_path.read_text(encoding="utf-8")) or {}
    meta = data.get("meta") or {}
    status = str(meta.get("status") or "DRAFT").upper()
    authority_by_ref: dict[str, list[str]] = {}
    for authority in data.get("authorities") or []:
        authority_id = str(authority.get("id") or "")
        if not authority_id.startswith("ARCH-"):
            continue
        for ref in authority.get("registry_refs") or []:
            authority_by_ref.setdefault(str(ref), []).append(authority_id)

    entries: list[CharterEntry] = []
    for raw_entry in data.get("registry") or []:
        entry_id = str(raw_entry.get("id") or "")
        state = str(raw_entry.get("state") or "").upper()
        if not entry_id.startswith("CHR-") or state not in ENFORCED_STATES:
            continue
        is_binding = (
            status == "RATIFIED"
            or bool(raw_entry.get("binding_in_draft"))
            or entry_id in DRAFT_BINDING_IDS
        )
        entries.append(
            CharterEntry(
                entry_id=entry_id,
                state=state,
                paths=tuple(str(path) for path in raw_entry.get("paths") or []),
                symbols=tuple(str(symbol) for symbol in raw_entry.get("symbols") or []),
                kept_symbols=tuple(str(symbol) for symbol in raw_entry.get("kept_symbols") or []),
                binding="BINDING" if is_binding else "PROPOSED",
            )
        )
    return entries, authority_by_ref, status


def _entry_matches_line(
    entry: CharterEntry,
    added_line: AddedLine,
    aliases_by_module: dict[str, set[str]],
) -> str | None:
    if _line_is_kept_only(added_line, entry):
        return None
    if entry.symbols:
        if not _is_python_path(added_line.path):
            return None
        for symbol in entry.symbols:
            if _line_imports_symbol(added_line.line, symbol, aliases_by_module) or (
                any(_path_matches(path, added_line.path) for path in entry.paths)
                and _line_reexports_or_defines_symbol(added_line.line, symbol)
            ):
                return f"re-adds chartered symbol {symbol}"
        return None
    if any(_path_matches(path, added_line.path) for path in entry.paths):
        return f"adds code under chartered {entry.state.lower()} path"
    for path in entry.paths:
        if _line_imports_path(added_line.line, path):
            return f"imports chartered {entry.state.lower()} path {path}"
    return None


def check_diff(diff_text: str, *, charter_path: Path | str) -> CheckResult:
    entries, authority_by_ref, _status = load_charter_entries(Path(charter_path))
    added_lines = reconstruct_multiline_imports(parse_diff(diff_text))
    aliases_by_path: dict[str, dict[str, set[str]]] = {}
    for added_line in added_lines:
        for alias, module in _plain_import_aliases(added_line.line).items():
            aliases_by_path.setdefault(added_line.path, {}).setdefault(module, set()).add(alias)
    violations: list[Violation] = []
    seen: set[tuple[str, str, int | None, str]] = set()
    for added_line in added_lines:
        for entry in entries:
            reason = _entry_matches_line(
                entry,
                added_line,
                aliases_by_path.get(added_line.path, {}),
            )
            if reason is None:
                continue
            if entry.symbols:
                key = (
                    entry.entry_id,
                    added_line.path,
                    added_line.line_no,
                    added_line.line.strip(),
                )
            else:
                key = (entry.entry_id, added_line.path, None, "")
            if key in seen:
                continue
            seen.add(key)
            violations.append(
                Violation(
                    binding=entry.binding,
                    entry_id=entry.entry_id,
                    state=entry.state,
                    path=added_line.path,
                    line_no=added_line.line_no,
                    line=added_line.line,
                    reason=reason,
                    authority_ids=authority_by_ref.get(entry.entry_id, []),
                )
            )
    binding = [violation for violation in violations if violation.binding == "BINDING"]
    proposed = [violation for violation in violations if violation.binding == "PROPOSED"]
    return CheckResult(
        ok=not violations,
        binding_violations=binding,
        proposed_violations=proposed,
        violations=violations,
    )


def _git_diff(ref_range: str) -> str:
    proc = subprocess.run(
        ["git", "diff", "--no-ext-diff", "--unified=0", ref_range, "--"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise SystemExit(f"git diff failed for {ref_range}: {proc.stderr.strip()}")
    return proc.stdout


def _read_diff(args: argparse.Namespace) -> str:
    if args.diff_file:
        if args.diff_file == "-":
            return sys.stdin.read()
        return Path(args.diff_file).read_text(encoding="utf-8")
    ref_range = args.ref_range or f"{args.base}...{args.head}"
    return _git_diff(ref_range)


def _render_text(result: CheckResult) -> str:
    if result.ok:
        return "Charter compliance: PASS\nNo chartered re-adds or enforceable placement violations found."
    lines = ["Charter compliance: FAIL"]
    for title, violations in (
        ("Binding violations", result.binding_violations),
        ("Proposed violations", result.proposed_violations),
    ):
        if not violations:
            continue
        lines.append("")
        lines.append(f"{title}:")
        for violation in violations:
            location = violation.path
            if violation.line_no is not None:
                location = f"{location}:{violation.line_no}"
            authorities = ""
            if violation.authority_ids:
                authorities = f" authorities={','.join(violation.authority_ids)}"
            lines.append(
                f"- {violation.binding} {violation.entry_id} [{violation.state}]"
                f"{authorities} {location}: {violation.reason}"
            )
            lines.append(f"  added: {violation.line.strip()}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--charters",
        type=Path,
        default=_repo_root() / "docs" / "architecture" / "charters.yaml",
        help="Path to docs/architecture/charters.yaml.",
    )
    parser.add_argument("--diff-file", help="Unified diff file to inspect; use '-' for stdin.")
    parser.add_argument(
        "--range", dest="ref_range", help="Git diff range, for example base...head."
    )
    parser.add_argument("--base", default="origin/main", help="Base ref when --range is omitted.")
    parser.add_argument("--head", default="HEAD", help="Head ref when --range is omitted.")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    diff_text = _read_diff(args)
    result = check_diff(diff_text, charter_path=args.charters)
    if args.format == "json":
        print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    else:
        print(_render_text(result))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
