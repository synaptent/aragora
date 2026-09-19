"""CLI command: ``aragora coherence-scan``.

DIC-26 operator surface for the belief coherence monitor (issue #6220).
DIC-17 bridge: ``--emit-followup`` flag forwards error-severity coherence
issues to the follow-up proposal bridge (issue #6027).

Reads a JSON file where each element is a BeliefEntry dict:
    {"belief_id": "...", "subject": "...", "confidence": 0.8,
     "status": "pass", "evidence_paths": ["docs/status/foo.md"]}

Flags:
  ``ARAGORA_COHERENCE_MONITOR_ENABLED`` (default OFF) — gate for scanning.
  ``ARAGORA_EPISTEMIC_FOLLOWUP_ENABLED`` (default OFF) — gate for proposals;
  also required when ``--emit-followup`` is passed.

Live queue effect: none — read-only operator report; proposals are printed
but never filed.
Advances: issues #6220 (DIC-26) and #6027 (DIC-17).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from aragora.epistemic.coherence import (
    BeliefEntry,
    CoherenceReport,
    coherence_monitor_enabled,
    scan_coherence,
)

logger = logging.getLogger(__name__)

_FLAG = "ARAGORA_COHERENCE_MONITOR_ENABLED"
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


def _render_proposals(report: CoherenceReport) -> None:
    """Print DIC-17 follow-up proposals to stdout (text mode only)."""
    if not report.proposals:
        return
    print()
    print(f"  follow-up proposals ({len(report.proposals)}):")
    for p in report.proposals:
        prov = p.provenance
        kind = prov.get("kind", "?")
        ids_list = prov.get("belief_ids", [])
        ids_str = ", ".join(str(i) for i in ids_list)
        print(f"    [{kind}] {p.title[:100]}")
        print(f"      beliefs: {ids_str}")
        print(f"      labels : {', '.join(p.labels)}")
    print()
    print("  (proposals printed, not filed — no live queue effect)")


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

    emit_followup: bool = getattr(args, "emit_followup", False)
    report = scan_coherence(
        entries,
        contradiction_gap=float(getattr(args, "contradiction_gap", _DEFAULT_GAP)),
        min_confidence=float(getattr(args, "min_confidence", _DEFAULT_MIN_CONFIDENCE)),
        enabled=True,
        emit_followup_proposals=emit_followup,
    )

    as_json: bool = getattr(args, "json", False)
    if as_json:
        print(json.dumps(report.to_dict(), indent=2))
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
        _render_proposals(report)
    return 0
