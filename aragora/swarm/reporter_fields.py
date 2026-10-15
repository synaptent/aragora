"""Field extraction and text normalization helpers for the swarm reporter.

They read optional fields from loosely shaped task, lease, receipt and work-order
records, parse timestamps, normalize blocker text, redact CLI transcripts and sensitive
output from boss evidence, and summarize repair journals. ``aragora.swarm.reporter``
re-exports every name here, so importing from either module yields the same objects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

_PLACEHOLDER_BLOCKERS: frozenset[str] = frozenset({"none", "null", "n/a", "na"})
_CLI_TRANSCRIPT_MARKERS: tuple[str, ...] = (
    "openai codex v",
    "workdir:",
    "approval:",
    "sandbox:",
    "session id:",
    "\nuser\n# task:",
    "\nexec\n",
)
_SENSITIVE_OUTPUT_MARKERS: tuple[str, ...] = (
    "api_key=",
    "api key=",
    "authorization:",
    "bearer ",
    "token=",
    "secret=",
    "password=",
)


def _parse_iso_timestamp(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any, *, now: datetime) -> float | None:
    parsed = _parse_iso_timestamp(value)
    if parsed is None:
        return None
    return max(0.0, (now - parsed).total_seconds())


def _seconds_between(start: Any, end: Any) -> float | None:
    start_dt = _parse_iso_timestamp(start)
    end_dt = _parse_iso_timestamp(end)
    if start_dt is None or end_dt is None:
        return None
    return max(0.0, (end_dt - start_dt).total_seconds())


def _text(value: Any) -> str:
    return str(value or "").strip()


def _metadata(item: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    data = item.get("metadata")
    return data if isinstance(data, dict) else {}


def _first_text(*values: Any) -> str:
    for value in values:
        text = _text(value)
        if text:
            return text
    return ""


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(_text(item) for item in value if _text(item)))


def _blocker_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return list(dict.fromkeys(text for item in value if (text := _normalize_blocker_text(item))))


def _normalize_blocker_text(value: Any) -> str:
    text = _text(value)
    lowered = text.lower()
    if not text or lowered in _PLACEHOLDER_BLOCKERS:
        return ""
    if len(text) >= 500 and any(marker in lowered for marker in _CLI_TRANSCRIPT_MARKERS):
        return _cli_transcript_placeholder(text)
    return text


def _first_list(*values: Any) -> list[str]:
    for value in values:
        items = _text_list(value)
        if items:
            return items
    return []


def _first_dict_list(*values: Any) -> list[dict[str, Any]]:
    for value in values:
        if not isinstance(value, (list, tuple, set)):
            continue
        items = [dict(item) for item in value if isinstance(item, dict)]
        if items:
            return items
    return []


def _compact_text(value: Any, *, max_chars: int = 180) -> str:
    text = _single_line_text(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _single_line_text(value: Any) -> str:
    return " ".join(_text(value).split())


def _cli_transcript_placeholder(value: Any) -> str:
    lowered = _text(value).lower()
    if "timeout" in lowered or "timed out" in lowered:
        return "worker_timeout_transcript_captured"
    return "worker_cli_transcript_captured"


def _looks_like_sensitive_cli_output(value: Any) -> bool:
    text = _single_line_text(value)
    if not text:
        return False
    lowered = text.lower()
    transcript_markers = sum(1 for marker in _CLI_TRANSCRIPT_MARKERS if marker in lowered)
    sensitive_markers = sum(1 for marker in _SENSITIVE_OUTPUT_MARKERS if marker in lowered)
    if transcript_markers >= 2:
        return True
    if transcript_markers >= 1 and (sensitive_markers >= 1 or len(text) >= 120):
        return True
    if sensitive_markers >= 2:
        return True
    return False


def _sanitize_boss_evidence_text(value: Any, *, max_chars: int = 180) -> str:
    if _looks_like_sensitive_cli_output(value):
        return _cli_transcript_placeholder(value)
    return _compact_text(value, max_chars=max_chars)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    text = _text(value)
    if text.startswith("-"):
        digits = text[1:]
        return int(text) if digits.isdigit() else None
    return int(text) if text.isdigit() else None


def _repair_journal_entries(*sources: dict[str, Any] | None) -> list[dict[str, Any]]:
    for source in sources:
        if not isinstance(source, dict):
            continue
        raw = source.get("repair_journal")
        if isinstance(raw, list):
            entries = [dict(item) for item in raw if isinstance(item, dict)]
            if entries:
                return entries
        meta = _metadata(source)
        raw = meta.get("repair_journal")
        if isinstance(raw, list):
            entries = [dict(item) for item in raw if isinstance(item, dict)]
            if entries:
                return entries
    return []


def _latest_repair_summary(*sources: dict[str, Any] | None) -> dict[str, Any] | None:
    entries = _repair_journal_entries(*sources)
    if not entries:
        return None

    latest = entries[-1]
    failing = latest.get("failing_verification")
    failing = dict(failing) if isinstance(failing, dict) else {}
    evidence = _first_text(
        _sanitize_boss_evidence_text(failing.get("stderr_tail")),
        _sanitize_boss_evidence_text(failing.get("stdout_tail")),
        _sanitize_boss_evidence_text(latest.get("stderr_tail")),
        _sanitize_boss_evidence_text(latest.get("stdout_tail")),
    )
    summary = {
        "failure_reason": _first_text(latest.get("failure_reason")) or None,
        "worker_outcome": _first_text(latest.get("worker_outcome")) or None,
        "exit_code": _optional_int(latest.get("exit_code")),
        "verification_command": _compact_text(failing.get("command")) or None,
        "verification_exit_code": _optional_int(failing.get("exit_code")),
        "evidence": evidence or None,
    }
    return {key: value for key, value in summary.items() if value not in (None, "")}


def _render_repair_summary(summary: dict[str, Any] | None) -> str:
    if not isinstance(summary, dict):
        return ""
    parts: list[str] = []
    reason = _text(summary.get("failure_reason"))
    if reason:
        parts.append(f"reason={reason}")
    command = _text(summary.get("verification_command"))
    if command:
        parts.append(f"cmd={command}")
    verification_exit = _optional_int(summary.get("verification_exit_code"))
    if verification_exit is not None:
        parts.append(f"verify_exit={verification_exit}")
    exit_code = _optional_int(summary.get("exit_code"))
    if exit_code is not None:
        parts.append(f"worker_exit={exit_code}")
    evidence = _text(summary.get("evidence"))
    if evidence:
        parts.append(f"evidence={evidence}")
    return "; ".join(parts)
