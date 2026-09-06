"""CLI command: ``aragora coherence-scan``.

DIC-26 operator surface for the belief coherence monitor (issue #6220).

Reads a JSON file where each element is a BeliefEntry dict:
    {"belief_id": "...", "subject": "...", "confidence": 0.8,
     "status": "pass", "evidence_paths": ["docs/status/foo.md"]}

Flag: ``ARAGORA_COHERENCE_MONITOR_ENABLED`` (default OFF).
Live queue effect: none — read-only operator report.
Advances: issue #6220 (DIC-26), issue #6027 (DIC-17 followup bridge).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from aragora.epistemic.coherence import (
    BeliefEntry,
    coherence_monitor_enabled,
    scan_coherence,
)
from aragora.epistemic.followup import FollowupProposal

logger = logging.getLogger(__name__)

_FLAG = "ARAGORA_COHERENCE_MONITOR_ENABLED"
_FOLLOWUP_FLAG = "ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED"
_DEFAULT_GAP: float = 0.5
_DEFAULT_MIN_CONFIDENCE: float = 0.3


def _load_entries(path: Path) -> list[BeliefEntry]:
    """Parse *path* as JSON into a list of :class:`BeliefEntry`.

    Accepts a JSON array or a single JSON object. Malformed entries are
    logged at WARNING and skipped so one bad row does not abort the scan.
    """
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = [raw]
    entries: list[BeliefEntry] = []
    for idx, obj in enumerate(raw, 1):
        try:
            entries.append(
                BeliefEntry(
                    belief_id=str(obj["belief_id"]),
                    subject=str(obj["subject"]),
                    confidence=float(obj["confidence"]),
                    status=str(obj.get("status", "unknown")),
                    evidence_paths=tuple(str(p) for p in obj.get("evidence_paths") or []),
                )
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("belief entry %d skipped: %s", idx, exc)
    return entries


def _render_proposals(proposals: list[FollowupProposal], *, followup_enabled: bool) -> None:
    """Print DIC-17 follow-up proposals in text mode."""
    print()
    if proposals:
        print(f"  DIC-17 follow-up proposals: {len(proposals)}")
        for p in proposals:
            print(f"    [{p.source_key}] {p.title}")
            print(f"      {p.rationale}")
            print(f"      labels: {', '.join(p.labels)}")
    else:
        print("  DIC-17 follow-up proposals: none")
        if not followup_enabled:
            print(f"    (set {_FOLLOWUP_FLAG}=1 to enable proposal generation)")


def cmd_coherence_scan(args: argparse.Namespace) -> int:
    """Handle the ``aragora coherence-scan`` subcommand."""
    if not coherence_monitor_enabled():
        print(
            f"error: {_FLAG} is not set; set it to '1' to enable coherence-scan",
            file=sys.stderr,
        )
        return 1

    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        entries = _load_entries(input_path)
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: failed to load {input_path}: {exc}", file=sys.stderr)
        return 1

    emit_followup: bool = bool(getattr(args, "emit_followup", False))

    report = scan_coherence(
        entries,
        contradiction_gap=float(getattr(args, "contradiction_gap", _DEFAULT_GAP)),
        min_confidence=float(getattr(args, "min_confidence", _DEFAULT_MIN_CONFIDENCE)),
        enabled=True,
        emit_followup_proposals=emit_followup,
    )

    as_json: bool = getattr(args, "json", False)
    if as_json:
        d = report.to_dict()
        if emit_followup and report.proposals:
            d["proposals"] = [
                {
                    "source_key": p.source_key,
                    "source_kind": p.source_kind,
                    "title": p.title,
                    "rationale": p.rationale,
                    "labels": list(p.labels),
                }
                for p in report.proposals
            ]
        print(json.dumps(d, indent=2))
        return 0

    print(f"Coherence scan: {input_path}")
    print(f"  scanned            : {report.scanned}")
    print(f"  coherent           : {report.coherent}")
    print(f"  contradictions     : {report.contradiction_count}")
    print(f"  evidence conflicts : {report.evidence_conflict_count}")
    print(f"  confidence rot     : {report.confidence_rot_count}")
    if report.issues:
        print()
        for issue in report.issues:
            ids = ", ".join(issue.belief_ids)
            print(f"  [{issue.severity}] {issue.kind.value}: {ids}")
            print(f"    {issue.detail}")

    if emit_followup:
        followup_enabled = str(os.environ.get(_FOLLOWUP_FLAG) or "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        _render_proposals(report.proposals, followup_enabled=followup_enabled)

    return 0


__all__ = ["cmd_coherence_scan"]
