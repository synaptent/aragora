"""CLI command: ``aragora decay-monitor``.

DIC-20 operator surface for the epistemic decay monitor (issue #6031).

Loads proof-carrying code unit YAML manifests from ``--units-dir``, then
optionally reads pre-computed ClaimResult rows from ``--claim-results``
JSONL, and emits per-unit DecaySignal assessments.

With ``--transitive-impact`` a manifest may list the ``code_unit_id``s it
depends on under an optional ``depends_on`` key. A failed, stale or
verifier-error claim then also marks every unit that transitively depends on
the claim's owner. An edge naming an unknown unit or the unit itself, a
malformed ``depends_on`` value, or a duplicate ``code_unit_id`` exits 1. The
default report ignores ``depends_on``.

Flag: ``ARAGORA_DECAY_MONITOR_ENABLED`` (default OFF).
Live queue effect: none — read-only report; no queue writes.
Advances: issue #6031 (DIC-20).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FLAG = "ARAGORA_DECAY_MONITOR_ENABLED"
_DEFAULT_UNITS_DIR = ".aragora_proof_units"


def _flag_enabled() -> bool:
    return os.environ.get(_FLAG, "").lower() in {"1", "true", "yes", "on"}


def _load_manifests(units_dir: Path) -> list[dict[str, Any]]:
    import yaml  # type: ignore[import-untyped]  # ImportError propagates to cmd_decay_monitor

    out: list[dict[str, Any]] = []
    for p in sorted(units_dir.glob("*.yaml")):
        try:
            with p.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict):
                out.append(data)
            else:
                logger.warning("manifest %s: not a dict, skipped", p.name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("manifest %s skipped: %s", p.name, exc)
    return out


def _parse_claim_results(path: Path) -> dict[str, Any]:
    from aragora.epistemic.claim_verifier import ClaimResult, ClaimStatus

    raw = path.read_text(encoding="utf-8").strip()
    rows: list[dict[str, Any]] = []
    try:
        parsed = json.loads(raw)
        rows = parsed if isinstance(parsed, list) else [parsed]
    except json.JSONDecodeError:
        for i, line in enumerate(raw.splitlines(), 1):
            if line.strip():
                try:
                    rows.append(json.loads(line.strip()))
                except json.JSONDecodeError as exc:
                    logger.warning("claim-results line %d skipped: %s", i, exc)
    out: dict[str, ClaimResult] = {}
    for row in rows:
        try:
            cid = str(row["claim_id"])
            out[cid] = ClaimResult(
                claim_id=cid,
                status=ClaimStatus(row["status"]),
                message=str(row.get("message", "")),
                severity=str(row.get("severity", "info")),
                allowed_action=str(row.get("allowed_action", "report_only")),
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("claim-results row skipped: %s", exc)
    return out


def _dependency_edges(declared: list[tuple[str, Any]]) -> list[tuple[str, str]]:
    """Turn each unit's ``depends_on`` value into ``(unit, upstream_unit)`` edges."""
    edges: list[tuple[str, str]] = []
    for uid, upstream in declared:
        if upstream is None:
            continue
        if not isinstance(upstream, list) or not all(isinstance(u, str) for u in upstream):
            raise ValueError(f"manifest {uid!r}: depends_on must be a list of code_unit_id strings")
        edges.extend((uid, up) for up in upstream)
    return edges


def cmd_decay_monitor(args: argparse.Namespace) -> int:
    if not _flag_enabled():
        print(f"error: {_FLAG} is not set; set it to '1' to enable decay-monitor", file=sys.stderr)
        return 1

    units_dir = Path(getattr(args, "units_dir", _DEFAULT_UNITS_DIR)).expanduser()
    if not units_dir.is_dir():
        print(f"error: units-dir not found: {units_dir}", file=sys.stderr)
        return 1

    cr_str: str | None = getattr(args, "claim_results", None)
    claim_results: dict[str, Any] = {}
    if cr_str:
        cr_path = Path(cr_str).expanduser()
        if not cr_path.exists():
            print(f"error: claim-results file not found: {cr_path}", file=sys.stderr)
            return 1
        try:
            claim_results = _parse_claim_results(cr_path)
        except ImportError:
            # ``_parse_claim_results`` imports the epistemic package, which pulls
            # in pyyaml at module load. Fail closed with the same clear message
            # rather than a raw ModuleNotFoundError traceback.
            print(
                "error: pyyaml is required but not installed; install it to use decay-monitor",
                file=sys.stderr,
            )
            return 1

    try:
        manifests = _load_manifests(units_dir)
    except ImportError:
        print(
            "error: pyyaml is required but not installed; install it to use decay-monitor",
            file=sys.stderr,
        )
        return 1
    units = []
    signals = []
    declared_deps: list[tuple[str, Any]] = []
    if manifests:
        from aragora.epistemic.proof_unit_model import load_proof_unit
        from aragora.epistemic.decay_monitor import evaluate_unit

        for data in manifests:
            try:
                unit = load_proof_unit(data)
                units.append(unit)
                declared_deps.append((unit.code_unit_id, data.get("depends_on")))
                signals.append(evaluate_unit(unit, claim_results=claim_results or None))
            except Exception as exc:  # noqa: BLE001
                logger.warning("unit %s skipped: %s", data.get("code_unit_id", "?"), exc)

    transitive_impact_set: set[str] = set()
    if getattr(args, "transitive_impact", False) and units:
        from aragora.epistemic.constraint_graph import ProofUnitConstraintGraph
        from aragora.epistemic.decay_monitor import compute_decay_impact_set

        failing_claim_ids: set[str] = {
            r.claim_id
            for s in signals
            for r in s.reasons
            if r.claim_id and r.kind in {"failed_claim", "stale_evidence", "verifier_error"}
        }
        try:
            graph = ProofUnitConstraintGraph(
                units, dependency_edges=_dependency_edges(declared_deps)
            )
        except ValueError as exc:
            # The graph requires unique ids (manifests that omit code_unit_id
            # all load as "") and edges between loaded units, while the default
            # report tolerates duplicates and never reads depends_on.
            print(f"error: --transitive-impact: {exc}", file=sys.stderr)
            return 1
        transitive_impact_set = compute_decay_impact_set(graph, failing_claim_ids, transitive=True)

    ts = datetime.now(timezone.utc).isoformat()
    if getattr(args, "json", False):
        out: dict = {
            "generated_at": ts,
            "total": len(signals),
            "signals": [s.to_dict() for s in signals],
        }
        if transitive_impact_set:
            out["transitive_impact_set"] = sorted(transitive_impact_set)
        print(json.dumps(out, indent=2))
    else:
        print(f"Decay monitor — {ts}\n{len(signals)} unit(s) evaluated\n")
        for s in signals:
            print(
                f"  {s.code_unit_id}: integrity={s.integrity_score:.3f}  action={s.recommended_action}"
            )
            for r in s.reasons:
                print(f"    [{r.kind}] {r.detail}")
        if not signals:
            print("  (no proof-unit manifests found)")
        if transitive_impact_set:
            print(f"\nTransitive impact ({len(transitive_impact_set)} unit(s)):")
            for uid in sorted(transitive_impact_set):
                print(f"  {uid}")
    return 0
