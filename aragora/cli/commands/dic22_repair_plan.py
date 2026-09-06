"""CLI command: ``aragora repair-plan``.

DIC-22 operator surface for the verified replacement pipeline (issue #6033).

Reads a DecaySignal JSON (output of ``aragora decay-monitor --json``) and
emits a bounded RepairSpec.

For ``report_only`` (the default) no flag is required — the spec is always
safe to produce.  Non-``report_only`` kinds (``shadow_candidate``,
``pr_candidate``) require ``ARAGORA_REPAIR_PIPELINE_ENABLED=1``; the command
exits 1 with an actionable error message if the flag is absent.

``live_swap`` is permanently blocked by ``repair.py`` and is not accepted as a
``--repair-kind`` value.

Flag: ARAGORA_REPAIR_PIPELINE_ENABLED (required only for non-report_only kinds)
Live queue effect: none — produces a spec dict for human/operator review only.
Advances: issue #6033 (DIC-22 — verified replacement pipeline).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_FLAG = "ARAGORA_REPAIR_PIPELINE_ENABLED"
_REPORT_ONLY = "report_only"
_ALLOWED_KINDS = ("report_only", "shadow_candidate", "pr_candidate")


def _parse_decay_signal(data: dict):
    """Convert a raw dict (from DecaySignal JSON) into a :class:`DecaySignal`."""
    from aragora.epistemic.decay_monitor import DecayReason, DecaySignal

    if "code_unit_id" not in data:
        raise ValueError("missing required field 'code_unit_id'")

    reasons = [
        DecayReason(
            kind=str(r.get("kind", "unknown")),
            detail=str(r.get("detail", "")),
            claim_id=str(r.get("claim_id", "")),
            crux_id=str(r.get("crux_id", "")),
        )
        for r in data.get("reasons", [])
    ]
    return DecaySignal(
        code_unit_id=str(data["code_unit_id"]),
        integrity_score=float(data["integrity_score"]),
        reasons=reasons,
        recommended_action=str(data.get("recommended_action", _REPORT_ONLY)),
    )


def cmd_repair_plan(args: argparse.Namespace) -> int:
    """Entry point for ``aragora repair-plan``."""
    input_path = Path(args.input).expanduser()
    if not input_path.exists():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 2

    try:
        raw = json.loads(input_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"error: failed to read {input_path}: {exc}", file=sys.stderr)
        return 2

    if not isinstance(raw, dict):
        print("error: input must be a DecaySignal JSON object", file=sys.stderr)
        return 2

    repair_kind: str = args.repair_kind

    try:
        signal = _parse_decay_signal(raw)
    except (KeyError, ValueError, TypeError) as exc:
        print(f"error: malformed DecaySignal: {exc}", file=sys.stderr)
        return 2

    from aragora.epistemic.repair import propose_repair, repair_pipeline_enabled

    if repair_kind != _REPORT_ONLY and not repair_pipeline_enabled():
        print(
            f"error: --repair-kind={repair_kind!r} requires {_FLAG}=1; "
            "set the flag or use --repair-kind report_only",
            file=sys.stderr,
        )
        return 1

    try:
        spec = propose_repair(signal, repair_kind=repair_kind)  # type: ignore[arg-type]
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    as_json: bool = getattr(args, "json", False)
    if as_json:
        print(json.dumps(spec.to_dict(), indent=2))
        return 0

    print(f"Repair plan: {input_path}")
    print(f"  spec_id         : {spec.spec_id}")
    print(f"  code_unit_id    : {spec.code_unit_id}")
    print(f"  repair_kind     : {spec.repair_kind}")
    print(f"  linked_claims   : {', '.join(spec.linked_claims) or '(none)'}")
    print(f"  linked_crux_ids : {', '.join(spec.linked_crux_ids) or '(none)'}")
    print(f"  created_at      : {spec.created_at}")
    if spec.provenance_hash:
        print(f"  provenance_hash : {spec.provenance_hash}")
    return 0
