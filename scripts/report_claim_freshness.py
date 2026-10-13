#!/usr/bin/env python3
"""Report time-aware executable-claim truth states without mutating the queue."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from aragora.epistemic.executable_claim import (  # noqa: E402
    ClaimManifest,
    ClaimTruthState,
    ExecutableClaim,
)

_REPORT_STATES = ("live", "stale", "unsupported", "aspirational")


@dataclass(frozen=True)
class FreshnessRow:
    claim_id: str
    statement: str
    owner: str
    status: str
    last_verified_at: str | None
    age_hours: float | None
    freshness_sla_hours: int
    allowed_action: str
    repair_note: str | None
    note: str


def _parse_timestamp(value: str) -> datetime:
    normalized = value.removesuffix("Z") + ("+00:00" if value.endswith("Z") else "")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def classify_claim(claim: ExecutableClaim, *, as_of: datetime) -> FreshnessRow:
    """Classify one claim using declared truth state and its existing SLA."""
    truth = claim.truth_status
    status = ClaimTruthState.UNSUPPORTED.value
    last_verified_at: str | None = None
    age_hours: float | None = None
    note = "No truth_status metadata; migration-safe default is unsupported."

    if truth is not None:
        status = truth.state.value
        last_verified_at = truth.last_verified_at
        note = truth.note or ""
        if truth.state == ClaimTruthState.LIVE:
            assert last_verified_at is not None  # Enforced by ClaimTruthStatus.
            verified_at = _parse_timestamp(last_verified_at)
            normalized_as_of = as_of.astimezone(timezone.utc)
            delta_hours = (normalized_as_of - verified_at).total_seconds() / 3600
            if delta_hours < 0:
                status = ClaimTruthState.UNSUPPORTED.value
                note = "last_verified_at is in the future; claim fails closed as unsupported."
            else:
                age_hours = round(delta_hours, 2)
                if delta_hours > claim.freshness_sla_hours:
                    status = "stale"

    return FreshnessRow(
        claim_id=claim.claim_id,
        statement=claim.statement,
        owner=claim.owner,
        status=status,
        last_verified_at=last_verified_at,
        age_hours=age_hours,
        freshness_sla_hours=claim.freshness_sla_hours,
        allowed_action=claim.failure.allowed_action.value,
        repair_note=claim.failure.repair_note,
        note=note,
    )


def build_report(manifests: Sequence[ClaimManifest], *, as_of: datetime) -> dict[str, object]:
    rows = [
        classify_claim(claim, as_of=as_of) for manifest in manifests for claim in manifest.claims
    ]
    counts = Counter(row.status for row in rows)
    return {
        "schema_version": 1,
        "as_of": as_of.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "manifests": [manifest.manifest_id for manifest in manifests],
        "claims": [asdict(row) for row in rows],
        "summary": {state: counts[state] for state in _REPORT_STATES},
        "queue_mutation": False,
    }


def render_markdown(report: dict[str, object]) -> str:
    def cell(value: object) -> str:
        return str(value if value is not None else "-").replace("|", "\\|").replace("\n", " ")

    claims = report["claims"]
    assert isinstance(claims, list)
    lines = [
        "# Executable Claim Freshness",
        "",
        f"As of: `{report['as_of']}`",
        "",
        "| Claim | Owner | Status | Last verified | Age (h) | SLA (h) | Allowed action |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for raw in claims:
        assert isinstance(raw, dict)
        lines.append(
            "| "
            + " | ".join(
                cell(raw[key])
                for key in (
                    "claim_id",
                    "owner",
                    "status",
                    "last_verified_at",
                    "age_hours",
                    "freshness_sla_hours",
                    "allowed_action",
                )
            )
            + " |"
        )
    lines.extend(["", "This report is read-only and cannot create queue work.", ""])
    return "\n".join(lines)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--claims-dir",
        type=Path,
        default=_REPO_ROOT / "docs" / "status" / "claims",
    )
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        metavar="NAME.yaml",
        help="Report one manifest; repeat to select multiple. Defaults to all *.yaml files.",
    )
    parser.add_argument("--as-of", help="RFC 3339 report time; defaults to now.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        as_of = _parse_timestamp(args.as_of) if args.as_of else datetime.now(timezone.utc)
        names = args.manifest or [path.name for path in sorted(args.claims_dir.glob("*.yaml"))]
        if not names:
            raise ValueError(f"no claim manifests found in {args.claims_dir}")
        manifests = [ClaimManifest.from_yaml_file(args.claims_dir / name) for name in names]
        report = build_report(manifests, as_of=as_of)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    text = json.dumps(report, indent=2) + "\n" if args.format == "json" else render_markdown(report)
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
