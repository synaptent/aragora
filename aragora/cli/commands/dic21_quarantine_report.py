"""CLI command: ``aragora quarantine-report`` (DIC-21 / #6032).

Reads a DecaySignal JSON (file or stdin) and emits a QuarantineDecision.
Pure evaluation — no queue mutation, no live routing change.
Flag gate: ``ARAGORA_QUARANTINE_POLICY_ENABLED=1`` (default OFF).
Advances: issue #6032 (DIC-21 — fail-closed quarantine policy CLI surface).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_FLAG = "ARAGORA_QUARANTINE_POLICY_ENABLED"


def _enabled() -> bool:
    return os.environ.get(_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class _Reason:
    kind: str


@dataclass
class _Signal:
    """Duck-typed DecaySignal that avoids the pyyaml transitive import."""

    code_unit_id: str
    integrity_score: float
    recommended_action: str
    reasons: list[_Reason]


def _build_signal(data: dict) -> _Signal:
    code_unit_id = str(data["code_unit_id"])
    integrity_score = float(data["integrity_score"])
    if not 0.0 <= integrity_score <= 1.0:
        raise ValueError(f"integrity_score out of range [0,1]: {integrity_score}")
    return _Signal(
        code_unit_id=code_unit_id,
        integrity_score=integrity_score,
        recommended_action=str(data.get("recommended_action", "report_only")),
        reasons=[_Reason(kind=str(r["kind"])) for r in data.get("reasons", [])],
    )


def cmd_quarantine_report(args: argparse.Namespace) -> int:
    if not _enabled():
        print(
            f"error: {_FLAG} is not set; set it to '1' to enable quarantine-report", file=sys.stderr
        )
        return 1

    input_arg: str = getattr(args, "input", "-") or "-"
    if input_arg == "-":
        text = sys.stdin.read()
    else:
        p = Path(input_arg).expanduser()
        if not p.exists():
            print(f"error: signal file not found: {p}", file=sys.stderr)
            return 2
        text = p.read_text(encoding="utf-8")

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in signal input: {exc}", file=sys.stderr)
        return 2

    if not isinstance(data, dict):
        print("error: signal JSON must be an object", file=sys.stderr)
        return 2

    try:
        signal = _build_signal(data)
    except (KeyError, TypeError, ValueError) as exc:
        print(f"error: invalid decay signal: {exc}", file=sys.stderr)
        return 2

    from aragora.epistemic.quarantine_policy import apply_quarantine_policy

    _sig: Any = signal  # duck-typed local; avoids pyyaml transitive import
    decision = apply_quarantine_policy(
        _sig,
        code_unit_class=getattr(args, "code_unit_class", "default") or "default",
        request_live_swap=bool(getattr(args, "request_live_swap", False)),
    )

    if getattr(args, "json", False):
        print(json.dumps(decision.to_dict(), indent=2))
    else:
        lines = [
            f"code_unit_id:      {decision.code_unit_id}",
            f"policy_action:     {decision.policy_action}",
            f"fail_closed:       {decision.fail_closed}",
            f"live_swap_blocked: {decision.live_swap_blocked}",
            f"integrity_score:   {decision.integrity_score:.4f}",
            f"rationale:         {decision.rationale}",
        ]
        if decision.provenance_hash:
            lines.append(f"provenance_hash:   {decision.provenance_hash}")
        print("\n".join(lines))

    return 0
