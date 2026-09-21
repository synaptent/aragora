"""Adapter from on-disk triage receipts to :class:`TriageDecisionEvent`.

This module reads the existing artifacts produced by
``aragora review-queue act`` (see
:mod:`aragora.cli.commands.review_queue`) and the PDB brief storage
layer (:mod:`aragora.pdb.storage`) WITHOUT modifying their schemas,
and emits the pure-function event shape consumed by
:mod:`aragora.triage.metrics`.

Sources
-------

1. **Settlement receipts**
   ``<store_root>/receipts/pr-{n}-{session_id}-{action}.json``
   Emitted per ``aragora review-queue act`` settlement. Fields used:
     - ``pr_number``, ``head_sha``, ``packet_sha``          (identity)
     - ``reviewed_at``                                      (ts)
     - ``action``                                           (human verdict)
     - ``machine_recommendation``, ``queue_bucket``         (ensemble)
     - ``elapsed_seconds``                                  (duration)

2. **PDB brief index** (``<store_root>/briefs/index.jsonl``)
   Append-only event log of brief generation lifecycle events. Used
   to *fill in* triage-side context when the human settled through
   the PDB UI rather than the CLI.

Honest caveats
--------------

The current receipt schemas do NOT carry:

  - a per-decision ``final_outcome`` (merge outcome, close outcome),
  - a ``was_auto_handled`` flag (no auto-handle lane exists yet — #6372),
  - an explicit ``settlement_started_at`` / ``settlement_completed_at``
    pair; ``elapsed_seconds`` is a single duration field.

Event fields that depend on the missing data are emitted as ``None``
rather than synthesized. The downstream metric aggregator
(:func:`aragora.triage.metrics.compute_window`) returns ``None`` for
metrics that require fields the event source cannot populate; the
``notes`` map explains why.

Adding those fields upstream is tracked as a follow-up (see the PR
body for gap #6373).
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from aragora.triage.metrics import TriageDecisionEvent

__all__ = [
    "DEFAULT_STORE_SUBDIR",
    "RECEIPTS_SUBDIR",
    "BRIEFS_INDEX_PATH",
    "resolve_store_root",
    "iter_events_from_store",
    "event_from_settlement_receipt",
]

UTC = timezone.utc
logger = logging.getLogger(__name__)

DEFAULT_STORE_SUBDIR = ".aragora/review-queue"
RECEIPTS_SUBDIR = "receipts"
BRIEFS_INDEX_PATH = ("briefs", "index.jsonl")

# Recommendations that the triage layer treats as "the ensemble wants
# a human to look at this". These buckets map directly to
# ``was_escalated=True``. Anything else (approve_candidate, etc.) is
# ``was_escalated=False`` — the ensemble would have auto-handled if an
# auto-handle lane existed.
_ESCALATION_BUCKETS = frozenset({"needs_attention", "repairable"})
_ESCALATION_RECOMMENDATIONS = frozenset(
    {
        "needs_human_attention",
        "needs_human_review",
        "request_changes",
        "block",
        "reject",
    }
)

# Map from human action + ensemble recommendation to was_human_override.
# An override occurs when the human disagrees materially with the
# ensemble:
#   ensemble == approve-family AND human == request_changes  → override
#   ensemble == reject-family  AND human == approve          → override
# ``defer`` is neither an agreement nor an override — it's a "come back
# later" signal. We record it as non-override.
_APPROVE_RECS = frozenset(
    {
        "approve",
        "approve_candidate",
        "approve_with_followups",
        "approve_now",
        "ready_now",
        "safe_to_merge",
    }
)
_REJECT_RECS = frozenset(
    {"reject", "request_changes", "needs_human_attention", "needs_human_review", "block"}
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_store_root(override: str | Path | None = None) -> Path:
    """Resolve the canonical review-queue store root.

    Mirrors :func:`aragora.server.handlers.governance.review_queue._review_queue_root`
    (and the CLI's ``_review_queue_root``) so the adapter reads from
    the same tree the writers use.

    Resolution order:

    1. Explicit ``override`` argument
    2. ``ARAGORA_REVIEW_QUEUE_ROOT`` environment variable
    3. Walk up from cwd looking for ``.aragora/`` or ``.git/``; return
       ``<found>/.aragora/review-queue``
    4. Fallback: ``cwd/.aragora/review-queue``
    """
    if override is not None:
        return Path(override)
    env = os.environ.get("ARAGORA_REVIEW_QUEUE_ROOT")
    if env:
        return Path(env)
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".aragora").exists() or (candidate / ".git").exists():
            return candidate / ".aragora" / "review-queue"
    return cwd / ".aragora" / "review-queue"


def iter_events_from_store(
    store_root: str | Path | None = None,
) -> Iterator[TriageDecisionEvent]:
    """Yield :class:`TriageDecisionEvent` for every settlement receipt on disk.

    Silently skips receipts that fail to parse — a corrupt receipt
    must not poison the rolling-window query for the remaining
    settlements. Skips are logged at WARNING.

    Args:
        store_root: Path to ``.aragora/review-queue`` (or override via
            env var). See :func:`resolve_store_root`.
    """
    root = resolve_store_root(store_root)
    receipts_dir = root / RECEIPTS_SUBDIR
    if not receipts_dir.exists():
        return
    try:
        candidates = sorted(
            (p for p in receipts_dir.iterdir() if p.is_file() and p.suffix == ".json"),
            key=lambda p: p.name,
        )
    except OSError as exc:
        logger.warning("triage.event_source: could not list %s: %s", receipts_dir, exc)
        return
    for path in candidates:
        payload = _safe_read_json(path)
        if payload is None:
            continue
        event = event_from_settlement_receipt(payload, source_path=path)
        if event is not None:
            yield event


def event_from_settlement_receipt(
    payload: dict[str, Any],
    *,
    source_path: Path | None = None,
) -> TriageDecisionEvent | None:
    """Build a :class:`TriageDecisionEvent` from one settlement-receipt dict.

    Returns ``None`` when the payload is missing the minimum fields
    required to place the event in time (``reviewed_at``) or to
    identify it (``pr_number`` + ``action``). Such receipts cannot
    participate in rolling-window aggregation; skipping them preserves
    the integrity of the remaining metrics.

    Args:
        payload: Parsed JSON of one settlement-receipt file. Schema
            defined by
            :class:`aragora.cli.commands.review_queue.SettlementReceipt`.
        source_path: Optional path for logging diagnostics.
    """
    reviewed_at_raw = payload.get("reviewed_at")
    pr_number = payload.get("pr_number")
    action = payload.get("action")
    if not reviewed_at_raw or pr_number is None or not action:
        logger.debug(
            "triage.event_source: skipping receipt %s — missing reviewed_at/pr_number/action",
            source_path,
        )
        return None
    try:
        reviewed_at = _parse_iso(str(reviewed_at_raw))
    except ValueError:
        logger.warning(
            "triage.event_source: skipping receipt %s — invalid reviewed_at=%r",
            source_path,
            reviewed_at_raw,
        )
        return None

    session_id = str(payload.get("session_id") or "")
    decision_id = f"pr-{pr_number}-{session_id}-{action}"

    machine_recommendation = str(payload.get("machine_recommendation") or "").strip()
    queue_bucket = str(payload.get("queue_bucket") or "").strip()
    human_action = str(action).strip()

    was_escalated = _is_escalation(
        queue_bucket=queue_bucket,
        machine_recommendation=machine_recommendation,
        human_action=human_action,
    )

    # Current receipts carry no auto-handle flag (#6372 follow-up); the
    # adapter emits False until the auto-handle lane is wired.
    was_auto_handled = False

    was_human_override = _is_override(
        machine_recommendation=machine_recommendation,
        human_action=human_action,
    )

    # final_outcome is not recorded in current settlement receipts —
    # emitting None so the metrics layer can honestly suppress the
    # correlation metric. Follow-up: extend receipts with post-merge
    # outcome data.
    final_outcome: str | None = None

    elapsed = payload.get("elapsed_seconds")
    duration: float | None
    if isinstance(elapsed, (int, float)) and float(elapsed) >= 0:
        duration = float(elapsed)
    else:
        duration = None

    return TriageDecisionEvent(
        decision_id=decision_id,
        ts=reviewed_at,
        was_escalated=was_escalated,
        was_auto_handled=was_auto_handled,
        was_human_override=was_human_override,
        ensemble_recommendation=machine_recommendation,
        final_outcome=final_outcome,
        settlement_duration_seconds=duration,
    )


def events_from_iterable(
    payloads: Iterable[dict[str, Any]],
) -> Iterator[TriageDecisionEvent]:
    """Convenience: map an iterable of payload dicts to events.

    Used by tests that want to avoid round-tripping through disk.
    """
    for payload in payloads:
        event = event_from_settlement_receipt(payload)
        if event is not None:
            yield event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_escalation(
    *,
    queue_bucket: str,
    machine_recommendation: str,
    human_action: str,
) -> bool:
    """Decide whether a settled decision counts as an escalation.

    Priority order:

    1. Explicit bucket signal (``needs_attention`` / ``repairable``).
    2. Machine recommendation string ∈ needs-human vocabulary.
    3. Fallback: ``request_changes`` human action (the human judged
       the PR needed another round of machine+human attention).
    """
    bucket = queue_bucket.strip().lower()
    if bucket in _ESCALATION_BUCKETS:
        return True
    rec = machine_recommendation.strip().lower()
    if rec in _ESCALATION_RECOMMENDATIONS:
        return True
    if human_action.strip().lower() == "request_changes":
        return True
    return False


def _is_override(*, machine_recommendation: str, human_action: str) -> bool:
    """Decide whether the human action overrode the ensemble.

    Only approve↔reject contradictions are counted; defer is neither
    agreement nor override.
    """
    rec = machine_recommendation.strip().lower()
    action = human_action.strip().lower()
    if action == "defer":
        return False
    if rec in _APPROVE_RECS and action == "request_changes":
        return True
    if rec in _REJECT_RECS and action == "approve":
        return True
    return False


def _parse_iso(raw: str) -> datetime:
    """Parse an ISO-8601 timestamp, tolerating ``Z`` suffix; normalize to UTC."""
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _safe_read_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("triage.event_source: could not read %s: %s", path, exc)
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("triage.event_source: malformed JSON in %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.warning("triage.event_source: non-dict payload in %s", path)
        return None
    return data
