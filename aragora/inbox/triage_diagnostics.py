"""Triage-scoped diagnostics capture for quiet CLI runs."""

from __future__ import annotations

import contextvars
import json
import logging
import re
import traceback
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from aragora.debate.runtime_blockers import classify_stderr_signals
from aragora.utils.error_sanitizer import sanitize_error

_ACTIVE_RUN: contextvars.ContextVar[TriageRunDiagnostics | None] = contextvars.ContextVar(
    "triage_diagnostics_run",
    default=None,
)
_CURRENT_MESSAGE_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "triage_diagnostics_message_id",
    default=None,
)
_CURRENT_TIER: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "triage_diagnostics_tier",
    default=None,
)
_CURRENT_DEBATE_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "triage_diagnostics_debate_id",
    default=None,
)

_TARGET_LOGGER_PREFIXES = (
    "aragora.debate.cache.embeddings_lru",
    "aragora.debate.novelty",
    "aragora.debate.performance_monitor",
    "aragora.debate.phases.consensus_phase",
    "aragora.debate.phases.debate_rounds",
    "aragora.debate.phases.vote_collector",
    "aragora.inbox.triage_runner",
    "aragora.pulse.ingestor",
    "aragora.server.research_phase",
    "aragora.server.startup.database",
    "aragora.shared.embedding_cache",
    "aragora.storage.connection_factory",
    "aragora.storage.pool_manager",
)


class DiagnosticSeverity(str, Enum):
    BLOCKING = "blocking"
    DEGRADED = "degraded"
    DIAGNOSTIC = "diagnostic"


@dataclass(frozen=True)
class TriageDiagnosticEvent:
    ts: str
    run_id: str
    message_id: str | None
    debate_id: str | None
    tier: str | None
    severity: str
    code: str
    logger: str
    summary: str
    details: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "run_id": self.run_id,
            "message_id": self.message_id,
            "debate_id": self.debate_id,
            "tier": self.tier,
            "severity": self.severity,
            "code": self.code,
            "logger": self.logger,
            "summary": self.summary,
            "details": self.details,
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utcnow().isoformat()


def _slug_timestamp() -> str:
    return _utcnow().strftime("%Y%m%dT%H%M%SZ")


def _coerce_severity(value: str | DiagnosticSeverity | None) -> DiagnosticSeverity:
    if isinstance(value, DiagnosticSeverity):
        return value
    normalized = str(value or DiagnosticSeverity.DIAGNOSTIC.value).strip().lower()
    try:
        return DiagnosticSeverity(normalized)
    except ValueError:
        return DiagnosticSeverity.DIAGNOSTIC


def _extract_debate_id(text: str) -> str | None:
    match = re.search(r"\bdebate_id=([A-Za-z0-9._:-]+)\b", text)
    if match:
        return match.group(1)
    return None


def _classify_py_warning(text: str) -> tuple[str, DiagnosticSeverity]:
    classified = classify_stderr_signals(text)
    blockers = classified.get("runtime_blockers", [])
    warning_signals = classified.get("warning_signals", [])
    if blockers:
        return blockers[0], DiagnosticSeverity.BLOCKING
    if warning_signals:
        if "resource_warning" in warning_signals:
            return "resource_warning", DiagnosticSeverity.DIAGNOSTIC
        return warning_signals[0], DiagnosticSeverity.DIAGNOSTIC
    return "captured_warning", DiagnosticSeverity.DIAGNOSTIC


def _infer_log_event(record: logging.LogRecord) -> tuple[str, DiagnosticSeverity]:
    code = getattr(record, "triage_diag_code", None)
    severity = getattr(record, "triage_diag_severity", None)
    if code:
        return str(code), _coerce_severity(severity)

    message = record.getMessage()
    text = message.lower()

    if record.name == "py.warnings":
        return _classify_py_warning(message)
    if "vote returned none" in text:
        return "vote_none", DiagnosticSeverity.DEGRADED
    if "insufficient_participation" in text:
        return "insufficient_participation", DiagnosticSeverity.BLOCKING
    if "global embedding cache" in text:
        return "global_embedding_cache", DiagnosticSeverity.DIAGNOSTIC
    if "falling back to openrouter" in text:
        return "provider_fallback", DiagnosticSeverity.DEGRADED
    if "slow_round_detected" in text:
        return "slow_round", DiagnosticSeverity.DIAGNOSTIC
    if "slow_debate_complete" in text:
        return "slow_debate", DiagnosticSeverity.DIAGNOSTIC
    if record.levelno >= logging.ERROR:
        return "captured_error", DiagnosticSeverity.DEGRADED
    return "captured_warning", DiagnosticSeverity.DIAGNOSTIC


class _CaptureHandler(logging.Handler):
    def __init__(self, run: TriageRunDiagnostics):
        super().__init__(level=logging.WARNING)
        self._run = run

    def emit(self, record: logging.LogRecord) -> None:
        if not self._run.should_capture_record(record):
            return
        code, severity = _infer_log_event(record)
        message = sanitize_error(record.getMessage())
        details = ""
        if record.exc_info:
            details = sanitize_error(
                "".join(traceback.format_exception(*record.exc_info)),
                max_length=2000,
            )
        self._run.record_event(
            code=code,
            severity=severity,
            logger_name=record.name,
            summary=message,
            details=details,
            debate_id=_extract_debate_id(message),
        )


class _SuppressionFilter(logging.Filter):
    def __init__(self, run: TriageRunDiagnostics):
        super().__init__()
        self._run = run

    def filter(self, record: logging.LogRecord) -> bool:
        if self._run.verbose:
            return True
        return not self._run.should_capture_record(record)


class TriageRunDiagnostics:
    """Collects structured diagnostics for a single triage CLI run."""

    def __init__(
        self,
        *,
        profile: str,
        batch_size: int,
        auto_approve: bool,
        dry_run: bool,
        verbose: bool,
        diagnostics_dir: str | Path | None = None,
    ) -> None:
        self.profile = profile
        self.batch_size = batch_size
        self.auto_approve = auto_approve
        self.dry_run = dry_run
        self.verbose = verbose
        self.run_id = f"triage-{_slug_timestamp()}-{uuid4().hex[:6]}"
        base_dir = (
            Path(diagnostics_dir)
            if diagnostics_dir is not None
            else Path.home() / ".aragora" / "triage-runs"
        )
        self.artifact_dir = base_dir / self.run_id
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.artifact_dir / "events.jsonl"
        self.meta_path = self.artifact_dir / "meta.json"
        self.started_at = _iso_now()
        self.finished_at: str | None = None
        self._events: list[TriageDiagnosticEvent] = []
        self._once_keys: set[str] = set()
        self._suppressed_count = 0
        self._capture_handler: _CaptureHandler | None = None
        self._filters: list[tuple[logging.Handler, logging.Filter]] = []

    @property
    def suppressed_count(self) -> int:
        return self._suppressed_count

    @contextmanager
    def activate(self):
        token = _ACTIVE_RUN.set(self)
        try:
            yield self
        finally:
            _ACTIVE_RUN.reset(token)

    @contextmanager
    def capture_logging(self):
        root = logging.getLogger()
        capture_handler = _CaptureHandler(self)
        self._capture_handler = capture_handler
        root.addHandler(capture_handler)
        previous_warning_filters = list(warnings.filters)

        if not self.verbose:
            for handler in list(root.handlers):
                if handler is capture_handler:
                    continue
                suppression_filter = _SuppressionFilter(self)
                handler.addFilter(suppression_filter)
                self._filters.append((handler, suppression_filter))

        logging.captureWarnings(True)
        warnings.simplefilter("always", ResourceWarning)
        try:
            yield self
        finally:
            logging.captureWarnings(False)
            warnings.filters[:] = previous_warning_filters
            for handler, filter_obj in self._filters:
                handler.removeFilter(filter_obj)
            self._filters.clear()
            root.removeHandler(capture_handler)
            capture_handler.close()
            self._capture_handler = None

    def should_capture_record(self, record: logging.LogRecord) -> bool:
        code = getattr(record, "triage_diag_code", None)
        if code:
            return True
        if record.name == "py.warnings":
            return True
        return any(record.name.startswith(prefix) for prefix in _TARGET_LOGGER_PREFIXES)

    @contextmanager
    def message_scope(self, message_id: str):
        token = _CURRENT_MESSAGE_ID.set(message_id)
        try:
            yield self
        finally:
            _CURRENT_MESSAGE_ID.reset(token)

    @contextmanager
    def tier_scope(self, tier: str):
        token = _CURRENT_TIER.set(tier)
        try:
            yield self
        finally:
            _CURRENT_TIER.reset(token)

    @contextmanager
    def debate_scope(self, debate_id: str):
        token = _CURRENT_DEBATE_ID.set(debate_id)
        try:
            yield self
        finally:
            _CURRENT_DEBATE_ID.reset(token)

    def record_event(
        self,
        *,
        code: str,
        severity: str | DiagnosticSeverity,
        logger_name: str,
        summary: str,
        details: str = "",
        message_id: str | None = None,
        debate_id: str | None = None,
        tier: str | None = None,
        once_key: str | None = None,
    ) -> None:
        if once_key and once_key in self._once_keys:
            return
        if once_key:
            self._once_keys.add(once_key)

        event = TriageDiagnosticEvent(
            ts=_iso_now(),
            run_id=self.run_id,
            message_id=message_id or _CURRENT_MESSAGE_ID.get(),
            debate_id=debate_id or _CURRENT_DEBATE_ID.get(),
            tier=tier or _CURRENT_TIER.get(),
            severity=_coerce_severity(severity).value,
            code=str(code),
            logger=logger_name,
            summary=sanitize_error(summary),
            details=sanitize_error(details, max_length=2000) if details else "",
        )
        self._events.append(event)
        if not self.verbose:
            self._suppressed_count += 1
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")

    def get_message_summary(self, message_id: str, *, tier: str | None = None) -> dict[str, int]:
        summary = {
            DiagnosticSeverity.BLOCKING.value: 0,
            DiagnosticSeverity.DEGRADED.value: 0,
            DiagnosticSeverity.DIAGNOSTIC.value: 0,
            "total": 0,
        }
        for event in self._events:
            if event.message_id != message_id:
                continue
            if tier is not None and event.tier != tier:
                continue
            summary[event.severity] += 1
            summary["total"] += 1
        return summary

    def has_degraded_or_blocking(self) -> bool:
        return any(
            event.severity in {DiagnosticSeverity.BLOCKING.value, DiagnosticSeverity.DEGRADED.value}
            for event in self._events
        )

    def finalize(self, decisions: list[Any]) -> dict[str, Any]:
        self.finished_at = _iso_now()
        severity_counts = {
            DiagnosticSeverity.BLOCKING.value: 0,
            DiagnosticSeverity.DEGRADED.value: 0,
            DiagnosticSeverity.DIAGNOSTIC.value: 0,
        }
        for event in self._events:
            severity_counts[event.severity] += 1
        message_suppressed_count = sum(1 for event in self._events if event.message_id)
        global_suppressed_count = sum(1 for event in self._events if not event.message_id)

        meta = {
            "run_id": self.run_id,
            "profile": self.profile,
            "batch_size": self.batch_size,
            "auto_approve": self.auto_approve,
            "dry_run": self.dry_run,
            "verbose": self.verbose,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "processed_count": len(decisions),
            "fast_tier_count": sum(
                1 for decision in decisions if getattr(decision, "execution_tier", "") == "fast"
            ),
            "escalated_count": sum(
                1
                for decision in decisions
                if getattr(decision, "execution_tier", "") == "escalated"
            ),
            "blocked_count": sum(
                1 for decision in decisions if getattr(decision, "blocked_by_policy", False)
            ),
            "suppressed_diagnostics_count": self._suppressed_count,
            "message_suppressed_diagnostics_count": message_suppressed_count,
            "global_suppressed_diagnostics_count": global_suppressed_count,
            "severity_counts": severity_counts,
            "artifact_dir": str(self.artifact_dir),
            "events_path": str(self.events_path),
        }
        with self.meta_path.open("w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2, sort_keys=True)
        return meta


def get_active_triage_diagnostics() -> TriageRunDiagnostics | None:
    return _ACTIVE_RUN.get()


def triage_diagnostics_should_mirror_logs() -> bool:
    active = get_active_triage_diagnostics()
    return bool(active and active.verbose)


def record_triage_diagnostic(
    *,
    code: str,
    severity: str | DiagnosticSeverity,
    logger_name: str,
    summary: str,
    details: str = "",
    message_id: str | None = None,
    debate_id: str | None = None,
    tier: str | None = None,
    once_key: str | None = None,
) -> bool:
    active = get_active_triage_diagnostics()
    if active is None:
        return False
    active.record_event(
        code=code,
        severity=severity,
        logger_name=logger_name,
        summary=summary,
        details=details,
        message_id=message_id,
        debate_id=debate_id,
        tier=tier,
        once_key=once_key,
    )
    return True


__all__ = [
    "DiagnosticSeverity",
    "TriageDiagnosticEvent",
    "TriageRunDiagnostics",
    "get_active_triage_diagnostics",
    "record_triage_diagnostic",
    "triage_diagnostics_should_mirror_logs",
]
