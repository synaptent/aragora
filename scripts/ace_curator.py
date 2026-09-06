#!/usr/bin/env python3
"""Distill fleet operational exhaust into an incremental, traceable playbook."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


UTC = timezone.utc
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_CHARS = 2_000
DEFAULT_MAX_SOURCES = 80
SUPPORTED_INPUT_SUFFIXES = frozenset({".json", ".jsonl", ".md", ".markdown"})
RESERVED_PLAYBOOK_MARKERS = ("ACE-CURATOR:LESSON", "ACE-CURATOR:END")
PLAYBOOK_HEADER = """\
# Fleet Operational Playbook

This advisory playbook is maintained incrementally by `scripts/ace_curator.py`.
Lessons are grounded in cited fleet exhaust and cannot override repository gates,
the operating contract, or human settlement requirements.

"""
LESSON_BLOCK_RE = re.compile(
    r"<!-- ACE-CURATOR:LESSON\n(?P<meta>\{.*?\})\n-->\n"
    r"- \*\*(?P<id>FL-[0-9A-F]{12})\*\*: (?P<lesson>.*?)\n"
    r"<!-- ACE-CURATOR:END -->",
    re.DOTALL,
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(
        r"(?i)\bBearer[ \t]+(?:eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\."
        r"[A-Za-z0-9_-]{5,}|[A-Za-z0-9][A-Za-z0-9._~+/-]{19,}={0,2})"
        r"(?![A-Za-z0-9._~+/-])"
    ),
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
    re.compile(
        r"(?ix)(?<![A-Z0-9_-])[\"']?[A-Z0-9_-]*?"
        r"(?:API[-_]?KEY|SECRET[-_]?ACCESS[-_]?KEY|ACCESS[-_]?KEY|"
        r"CLIENT[-_]?SECRET|PRIVATE[-_]?KEY|AUTH[-_]?TOKEN|ACCESS[-_]?TOKEN|"
        r"REFRESH[-_]?TOKEN|ID[-_]?TOKEN|TOKEN|SECRET|PASSWORD)"
        r"[\"']?(?![A-Z0-9_-])"
        r"\s*[:=]\s*(?:\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,}]+)"
    ),
)
RECORD_FIELDS = (
    "lesson",
    "learnings_note",
    "summary",
    "result",
    "outcome",
    "action",
    "blocker_class",
    "blockers",
    "failure_detail",
    "rationale",
    "next_action",
    "last_steering_outcome",
)


@dataclass(frozen=True)
class SourceEntry:
    id: str
    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Lesson:
    id: str
    stable_key: str
    lesson: str
    sources: tuple[str, ...]
    change_reason: str
    updated_at: str


@dataclass(frozen=True)
class CuratorResult:
    lessons: tuple[Lesson, ...]
    added: int
    updated: int
    unchanged: int
    ignored: int


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _single_line(value: Any) -> str:
    return " ".join(str(value).replace("\x00", " ").split())


def redact(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED_SECRET]", redacted)
    return redacted


def _bounded_text(value: Any) -> str:
    text = redact(_single_line(value))
    for marker in RESERVED_PLAYBOOK_MARKERS:
        text = text.replace(marker, "[REDACTED_CURATOR_MARKER]")
    if len(text) > MAX_SOURCE_CHARS:
        return f"{text[: MAX_SOURCE_CHARS - 15]} [truncated]"
    return text


def _source_id(path: Path, line: int, text: str) -> str:
    digest = hashlib.sha256(f"{path}:{line}:{text}".encode()).hexdigest()[:12]
    return f"SRC-{digest.upper()}"


def _display_path(path: Path) -> str:
    parts = path.resolve().parts
    if ".aragora" in parts:
        return "/".join(parts[parts.index(".aragora") :])
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return path.name


def _source_entry(path: Path, line: int, text: str) -> SourceEntry:
    display_path = _display_path(path)
    return SourceEntry(_source_id(Path(display_path), line, text), display_path, line, text)


def _record_text(record: dict[str, Any]) -> str:
    pieces: list[str] = []
    for field in RECORD_FIELDS:
        value = record.get(field)
        if value in (None, "", [], {}):
            continue
        if isinstance(value, (list, dict)):
            rendered = json.dumps(value, sort_keys=True, ensure_ascii=True)
        else:
            rendered = str(value)
        pieces.append(f"{field}: {rendered}")
    return _bounded_text("; ".join(pieces))


def _check_readable_file(path: Path) -> None:
    info = path.stat()
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"input must be a regular non-symlink file: {path}")
    if info.st_size > MAX_FILE_BYTES:
        raise ValueError(f"input exceeds {MAX_FILE_BYTES} bytes: {path}")


def _jsonl_entries(path: Path) -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        text = _record_text(record)
        if text:
            entries.append(_source_entry(path, line_no, text))
    return entries


def _json_entries(path: Path) -> list[SourceEntry]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else [payload]
    entries: list[SourceEntry] = []
    for index, record in enumerate(records, 1):
        if not isinstance(record, dict):
            continue
        text = _record_text(record)
        if text:
            entries.append(_source_entry(path, index, text))
    return entries


def _markdown_entries(path: Path) -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    paragraph: list[str] = []
    start_line = 1

    def flush() -> None:
        nonlocal paragraph
        text = _bounded_text(" ".join(paragraph))
        if text:
            entries.append(_source_entry(path, start_line, text))
        paragraph = []

    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            flush()
            start_line = line_no + 1
            continue
        if not paragraph:
            start_line = line_no
        paragraph.append(stripped)
    flush()
    return entries


def collect_sources(paths: Sequence[Path], *, max_sources: int) -> list[SourceEntry]:
    deduplicated: list[SourceEntry] = []
    seen_text: set[str] = set()
    for path in paths:
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED_INPUT_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_INPUT_SUFFIXES))
            raise ValueError(f"unsupported input suffix for {path}: expected one of {supported}")
        _check_readable_file(path)
        if suffix == ".jsonl":
            entries = _jsonl_entries(path)
        elif suffix == ".json":
            entries = _json_entries(path)
        else:
            entries = _markdown_entries(path)
        for entry in entries:
            if entry.text in seen_text:
                continue
            seen_text.add(entry.text)
            deduplicated.append(entry)
            if len(deduplicated) >= max_sources:
                return deduplicated
    return deduplicated


def discover_default_inputs(root: Path) -> list[Path]:
    candidates = [root / ".aragora" / "conductor_cycles" / "long_run_ledger.jsonl"]
    for directory in (root / ".aragora" / "incident", root / ".aragora" / "incidents"):
        if directory.is_dir():
            candidates.extend(sorted(directory.glob("*.md")))
            candidates.extend(sorted(directory.glob("*.json")))
            candidates.extend(sorted(directory.glob("*.jsonl")))
    return [path for path in candidates if path.is_file() and not path.is_symlink()]


def lesson_id(stable_key: str) -> str:
    normalized = _single_line(stable_key).lower()
    if not normalized:
        raise ValueError("stable_key must not be empty")
    return f"FL-{hashlib.sha256(normalized.encode()).hexdigest()[:12].upper()}"


def load_playbook(path: Path) -> list[Lesson]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    matches = list(LESSON_BLOCK_RE.finditer(text))
    if text.count("ACE-CURATOR:LESSON") != len(matches) or text.count("ACE-CURATOR:END") != len(
        matches
    ):
        raise ValueError(f"malformed ACE curator block in {path}")
    lessons: list[Lesson] = []
    for match in matches:
        metadata = json.loads(match.group("meta"))
        identifier = str(metadata.get("id") or match.group("id"))
        if identifier != match.group("id"):
            raise ValueError(f"lesson id mismatch in {path}: {identifier}")
        sources = metadata.get("sources") or []
        if not isinstance(sources, list):
            raise ValueError(f"lesson sources must be a list: {identifier}")
        lessons.append(
            Lesson(
                id=identifier,
                stable_key=str(metadata.get("stable_key") or ""),
                lesson=_single_line(match.group("lesson")),
                sources=tuple(str(item) for item in sources),
                change_reason=str(metadata.get("change_reason") or ""),
                updated_at=str(metadata.get("updated_at") or ""),
            )
        )
    if len({lesson.id for lesson in lessons}) != len(lessons):
        raise ValueError(f"duplicate lesson id in {path}")
    return lessons


def _render_lesson(lesson: Lesson) -> str:
    metadata = json.dumps(
        {
            "change_reason": lesson.change_reason,
            "id": lesson.id,
            "sources": list(lesson.sources),
            "stable_key": lesson.stable_key,
            "updated_at": lesson.updated_at,
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return (
        f"<!-- ACE-CURATOR:LESSON\n{metadata}\n-->\n"
        f"- **{lesson.id}**: {lesson.lesson}\n"
        "<!-- ACE-CURATOR:END -->"
    )


def render_playbook(lessons: Sequence[Lesson]) -> str:
    if not lessons:
        return PLAYBOOK_HEADER
    return PLAYBOOK_HEADER + "\n\n".join(_render_lesson(lesson) for lesson in lessons) + "\n"


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        payload = json.loads(stripped)
    else:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("model output did not contain a JSON object")
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("model output must be a JSON object")
    return payload


def load_decisions(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    decisions = payload.get("decisions") if isinstance(payload, dict) else payload
    if not isinstance(decisions, list) or not all(isinstance(item, dict) for item in decisions):
        raise ValueError("decisions JSON must be a list or an object containing a decisions list")
    return decisions


def consult_model(
    sources: Sequence[SourceEntry],
    lessons: Sequence[Lesson],
    *,
    timeout: int,
) -> list[dict[str, Any]]:
    helper = Path(__file__).resolve().with_name("consult_claude.py")
    if not helper.exists():
        raise RuntimeError("scripts/consult_claude.py is required for model curation")
    prompt = {
        "task": "Curate fleet operational lessons for Aragora issue #8976.",
        "rules": [
            "Use causal operational lessons, not surface keyword summaries.",
            "Return only JSON with a decisions array.",
            "Actions are add, update, or ignore. Never delete.",
            "Prefer update when an existing lesson is semantically equivalent.",
            "Every add needs stable_key, lesson, reason, and source_ids.",
            "Every update needs target_id, lesson, reason, and source_ids.",
            "Each lesson must be actionable, concise, advisory, and grounded only in supplied sources.",
        ],
        "existing_lessons": [
            {
                "id": lesson.id,
                "stable_key": lesson.stable_key,
                "lesson": lesson.lesson,
                "sources": list(lesson.sources),
            }
            for lesson in lessons
        ],
        "sources": [
            {"id": source.id, "path": source.path, "line": source.line, "text": source.text}
            for source in sources
        ],
        "schema": {
            "decisions": [
                {
                    "action": "add|update|ignore",
                    "stable_key": "required for add",
                    "target_id": "required for update",
                    "lesson": "required for add/update",
                    "reason": "required for add/update",
                    "source_ids": ["required source ids"],
                }
            ]
        },
    }
    with tempfile.TemporaryDirectory(prefix="aragora-ace-curator-") as temp_dir:
        prompt_path = Path(temp_dir) / "prompt.json"
        prompt_path.write_text(json.dumps(prompt, ensure_ascii=True), encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(helper),
                "--json",
                "--prompt-file",
                str(prompt_path),
                "--timeout",
                str(timeout),
                "--overall-timeout",
                str(timeout),
                "--fallback-model",
                "",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout + 15,
        )
    if proc.returncode != 0:
        detail = _bounded_text(proc.stderr or proc.stdout or "no output")
        raise RuntimeError(f"model curator failed: {detail}")
    envelope = json.loads(proc.stdout)
    if not envelope.get("ok") or not envelope.get("text"):
        raise RuntimeError(f"model curator failed: {_bounded_text(envelope.get('error'))}")
    payload = _extract_json_object(str(envelope["text"]))
    decisions = payload.get("decisions")
    if not isinstance(decisions, list) or not all(isinstance(item, dict) for item in decisions):
        raise ValueError("model response must contain a decisions list")
    return decisions


def apply_decisions(
    lessons: Sequence[Lesson],
    sources: Sequence[SourceEntry],
    decisions: Sequence[dict[str, Any]],
    *,
    now: str | None = None,
) -> CuratorResult:
    current = list(lessons)
    by_id = {lesson.id: index for index, lesson in enumerate(current)}
    by_key = {lesson.stable_key: index for index, lesson in enumerate(current)}
    source_citations = {source.id: f"{source.id}@{source.path}:{source.line}" for source in sources}
    allowed_sources = set(source_citations)
    added = updated = unchanged = ignored = 0
    timestamp = now or _utc_now()

    for decision in decisions:
        action = _single_line(decision.get("action", "")).lower()
        if action == "ignore":
            ignored += 1
            continue
        if action not in {"add", "update"}:
            raise ValueError(f"unsupported curator action: {action or '<empty>'}")
        lesson_text = _bounded_text(decision.get("lesson", ""))
        reason = _bounded_text(decision.get("reason", ""))
        source_ids_raw = decision.get("source_ids")
        if not lesson_text or not reason:
            raise ValueError(f"{action} decisions require lesson and reason")
        if not isinstance(source_ids_raw, list) or not source_ids_raw:
            raise ValueError(f"{action} decisions require source_ids")
        cited_ids = tuple(dict.fromkeys(str(item) for item in source_ids_raw))
        unknown_sources = sorted(set(cited_ids) - allowed_sources)
        if unknown_sources:
            raise ValueError(f"decision cites unknown source ids: {', '.join(unknown_sources)}")
        source_ids = tuple(source_citations[identifier] for identifier in cited_ids)

        if action == "add":
            stable_key = _bounded_text(decision.get("stable_key", "")).lower()
            identifier = lesson_id(stable_key)
            index = by_key.get(stable_key, by_id.get(identifier))
            if index is None:
                lesson = Lesson(identifier, stable_key, lesson_text, source_ids, reason, timestamp)
                by_id[identifier] = len(current)
                by_key[stable_key] = len(current)
                current.append(lesson)
                added += 1
                continue
        else:
            target_id = _single_line(decision.get("target_id", ""))
            if target_id not in by_id:
                raise ValueError(f"update target does not exist: {target_id or '<empty>'}")
            index = by_id[target_id]

        existing = current[index]
        merged_sources = tuple(dict.fromkeys((*existing.sources, *source_ids)))
        if existing.lesson == lesson_text and existing.sources == merged_sources:
            unchanged += 1
            continue
        current[index] = replace(
            existing,
            lesson=lesson_text,
            sources=merged_sources,
            change_reason=reason,
            updated_at=timestamp,
        )
        updated += 1

    return CuratorResult(tuple(current), added, updated, unchanged, ignored)


def write_playbook(path: Path, content: str) -> bool:
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    if previous == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, default=Path("docs/artifacts/fleet-playbook.md"))
    parser.add_argument("--decisions-json", type=Path, help="Offline model decisions fixture")
    parser.add_argument("--max-sources", type=int, default=DEFAULT_MAX_SOURCES)
    parser.add_argument("--model-timeout", type=int, default=600)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.max_sources <= 0 or args.model_timeout <= 0:
        print("error: --max-sources and --model-timeout must be positive", file=sys.stderr)
        return 64
    root = Path.cwd()
    input_paths = args.input or discover_default_inputs(root)
    if not input_paths:
        print("error: no curator inputs found; pass --input", file=sys.stderr)
        return 2
    try:
        if args.output.is_symlink():
            raise ValueError(f"output must not be a symlink: {args.output}")
        protected_inputs = [*input_paths]
        if args.decisions_json:
            protected_inputs.append(args.decisions_json)
        if args.output.resolve() in {path.resolve() for path in protected_inputs}:
            raise ValueError("output must not alias a curator input or decisions fixture")
        sources = collect_sources(input_paths, max_sources=args.max_sources)
        if not sources:
            raise ValueError("inputs contained no usable lesson evidence")
        lessons = load_playbook(args.output)
        decisions = (
            load_decisions(args.decisions_json)
            if args.decisions_json
            else consult_model(sources, lessons, timeout=args.model_timeout)
        )
        result = apply_decisions(lessons, sources, decisions)
        rendered = render_playbook(result.lessons)
        changed = False if args.dry_run else write_playbook(args.output, rendered)
    except (
        OSError,
        UnicodeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    payload = {
        "ok": True,
        "output": str(args.output),
        "source_count": len(sources),
        "lesson_count": len(result.lessons),
        "added": result.added,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "ignored": result.ignored,
        "changed": changed,
        "dry_run": args.dry_run,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"ACE curator: {len(sources)} sources, {len(result.lessons)} lessons "
            f"({result.added} added, {result.updated} updated, changed={changed})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
