"""Organizational Truth Map report (DIC-18 / #6028).

Read-only operator report aggregating ExecutableClaim verification results
(DIC-14), optional CruxFinderResult summaries (DIC-15), and optional
DIC-27 operator arbitration records with age display.
Default OFF — callers must explicitly invoke ``build_truth_map`` or
``build_truth_map_from_manifests``.  No queue mutation, no side effects.
"""

from __future__ import annotations

import datetime
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aragora.epistemic.claim_verifier import ClaimResult, ClaimStatus

if TYPE_CHECKING:
    from aragora.debate.crux_mode import CruxFinderResult
    from aragora.epistemic.arbitration import CruxArbitration
    from aragora.epistemic.genealogy import GenealogyStore

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _genealogy_enabled() -> bool:
    raw = str(os.environ.get("ARAGORA_GENEALOGY_ENABLED") or "").strip().lower()
    return raw in _TRUTHY


def _arbitration_enabled() -> bool:
    """Return True when ARAGORA_CRUX_ARBITRATION_ENABLED is set.

    Same flag as :func:`aragora.epistemic.arbitration.crux_arbitration_enabled`.
    Inlined here to avoid a module-level import of arbitration.py.
    """
    raw = str(os.environ.get("ARAGORA_CRUX_ARBITRATION_ENABLED") or "").strip().lower()
    return raw in _TRUTHY


def _age_days(iso_timestamp: str) -> float:
    """Return the age in fractional days from *iso_timestamp* to now (UTC).

    Fails open: an unparseable timestamp returns 0.0 rather than raising,
    so a bad created_at does not abort truth-map generation.
    """
    try:
        dt = datetime.datetime.fromisoformat(iso_timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        delta = datetime.datetime.now(datetime.timezone.utc) - dt
        return max(0.0, delta.total_seconds() / 86400)
    except (ValueError, OverflowError):
        return 0.0


@dataclass
class ClaimRow:
    claim_id: str
    statement: str
    owner: str
    status: str
    evidence_age_hours: float | None
    verifier_kind: str
    verifier_command: str
    follow_up_link: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CruxSummaryRow:
    debate_id: str
    question: str
    convergence_barrier: float
    top_cruxes: list[dict[str, Any]]
    crux_count: int
    open_cruxes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GenealogyRow:
    """Lineage summary for one proof-carrying code unit (DIC-24 drill-down).

    Populated in ``build_truth_map`` when ``ARAGORA_GENEALOGY_ENABLED`` is set
    and the caller supplies ``genealogy_inputs``.  Contains the chain_checksum
    and a brief per-entry summary so truth-map consumers can see how a code
    path evolved without loading full receipt stores.
    """

    code_unit_id: str
    entry_count: int
    chain_checksum: str
    generated_at: str
    entries: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ArbitrationRow:
    """DIC-27 operator arbitration record for the truth map (age display).

    Populated in ``build_truth_map`` when ``ARAGORA_CRUX_ARBITRATION_ENABLED``
    is set and the caller supplies ``arbitration_inputs``.  Provides at-a-glance
    age and status so operators can see stale or reversed arbitrations without
    opening individual receipt files.

    Only included in the truth map when the DIC-27 flag is active; the field
    is always present on :class:`OrgTruthMapReport` but defaults to an empty
    list, so existing callers are unaffected.
    """

    arbitration_id: str
    crux_id: str
    question_family_id: str
    statement: str
    operator: str
    side: str
    created_at: str
    expires_at: str
    age_days: float
    is_expired: bool
    is_reversed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class OrgTruthMapReport:
    """Read-only aggregated truth map for an Aragora deployment."""

    generated_at: str
    claims: list[ClaimRow] = field(default_factory=list)
    crux_summaries: list[CruxSummaryRow] = field(default_factory=list)
    genealogies: list[GenealogyRow] = field(default_factory=list)
    arbitrations: list[ArbitrationRow] = field(default_factory=list)
    arbitration_enabled: bool = False
    total_claims: int = 0
    passing_claims: int = 0
    failing_claims: int = 0
    stale_claims: int = 0
    unsupported_claims: int = 0
    error_claims: int = 0
    open_crux_count: int = 0
    active_arbitration_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        summary = {
            "total_claims": self.total_claims,
            "passing": self.passing_claims,
            "failing": self.failing_claims,
            "stale": self.stale_claims,
            "unsupported": self.unsupported_claims,
            "error": self.error_claims,
            "open_crux_count": self.open_crux_count,
        }
        if self.arbitration_enabled:
            summary["active_arbitrations"] = self.active_arbitration_count

        d: dict[str, Any] = {
            "generated_at": self.generated_at,
            "claims": [c.to_dict() for c in self.claims],
            "crux_summaries": [cs.to_dict() for cs in self.crux_summaries],
            "genealogies": [g.to_dict() for g in self.genealogies],
            "summary": summary,
        }
        if self.arbitrations:
            d["arbitrations"] = [a.to_dict() for a in self.arbitrations]
        return d


def build_truth_map(
    *,
    claim_results: list[ClaimResult],
    claim_metadata: dict[str, dict[str, Any]] | None = None,
    crux_results: list[CruxFinderResult] | None = None,
    top_k_cruxes: int = 3,
    open_crux_score_threshold: float = 0.3,
    genealogy_inputs: "list[tuple[str, GenealogyStore]] | None" = None,
    arbitration_inputs: "list[CruxArbitration] | None" = None,
) -> OrgTruthMapReport:
    """Build an OrgTruthMapReport from pre-computed claim and crux inputs.

    ``genealogy_inputs`` is an optional list of ``(code_unit_id, store)``
    pairs. When ``ARAGORA_GENEALOGY_ENABLED`` is set, each pair is resolved
    via :func:`aragora.epistemic.genealogy.get_genealogy` and added as a
    :class:`GenealogyRow` drill-down.  When the flag is off the parameter
    is silently ignored so callers can wire it unconditionally.

    ``arbitration_inputs`` is an optional list of :class:`CruxArbitration`
    objects (DIC-27).  When ``ARAGORA_CRUX_ARBITRATION_ENABLED`` is set, each
    arbitration is converted to an :class:`ArbitrationRow` with age computed
    from ``created_at``.  When the flag is off the parameter is silently
    ignored so callers can wire it unconditionally.
    """
    meta = claim_metadata or {}
    rows: list[ClaimRow] = []
    for cr in claim_results:
        m = meta.get(cr.claim_id, {})
        verif: dict[str, Any] = m.get("verification", {})
        rows.append(
            ClaimRow(
                claim_id=cr.claim_id,
                statement=m.get("statement", cr.detail.get("statement", "")),
                owner=m.get("owner", cr.detail.get("owner", "")),
                status=cr.status.value if isinstance(cr.status, ClaimStatus) else str(cr.status),
                evidence_age_hours=cr.detail.get("evidence_age_hours"),
                verifier_kind=verif.get("kind", cr.detail.get("verifier_kind", "")),
                verifier_command=verif.get("command", cr.detail.get("verifier_command", "")),
                follow_up_link=cr.detail.get("follow_up_link", ""),
            )
        )

    counts: dict[ClaimStatus, int] = {s: 0 for s in ClaimStatus}
    for row in rows:
        try:
            counts[ClaimStatus(row.status)] += 1
        except ValueError:
            pass

    crux_rows: list[CruxSummaryRow] = []
    open_crux_total = 0
    for cfr in crux_results or []:
        open_count = sum(
            1 for c in cfr.analysis.cruxes if c.crux_score >= open_crux_score_threshold
        )
        open_crux_total += open_count
        crux_rows.append(
            CruxSummaryRow(
                debate_id=cfr.debate_id,
                question=cfr.question,
                convergence_barrier=cfr.convergence_barrier(),
                top_cruxes=[c.to_dict() for c in cfr.top_cruxes()[:top_k_cruxes]],
                crux_count=len(cfr.analysis.cruxes),
                open_cruxes=open_count,
            )
        )

    genealogy_rows: list[GenealogyRow] = []
    if genealogy_inputs and _genealogy_enabled():
        from aragora.epistemic.genealogy import get_genealogy

        for unit_id, store in genealogy_inputs:
            gen = get_genealogy(unit_id, store, require_enabled=False)
            genealogy_rows.append(
                GenealogyRow(
                    code_unit_id=gen.code_unit_id,
                    entry_count=len(gen.entries),
                    chain_checksum=gen.chain_checksum,
                    generated_at=gen.generated_at,
                    entries=[e.to_dict() for e in gen.entries],
                )
            )

    arbitration_enabled = _arbitration_enabled()
    arbitration_rows: list[ArbitrationRow] = []
    if arbitration_inputs and arbitration_enabled:
        for arb in arbitration_inputs:
            arbitration_rows.append(
                ArbitrationRow(
                    arbitration_id=arb.arbitration_id,
                    crux_id=arb.crux.crux_id,
                    question_family_id=arb.crux.question_family_id,
                    statement=arb.crux.statement,
                    operator=arb.operator,
                    side=arb.side,
                    created_at=arb.created_at,
                    expires_at=arb.expires_at,
                    age_days=round(_age_days(arb.created_at), 2),
                    is_expired=arb.is_expired,
                    is_reversed=arb.is_reversed,
                )
            )

    active_arb_count = sum(1 for a in arbitration_rows if not a.is_expired and not a.is_reversed)

    return OrgTruthMapReport(
        generated_at=datetime.datetime.utcnow().isoformat() + "Z",
        claims=rows,
        crux_summaries=crux_rows,
        genealogies=genealogy_rows,
        arbitrations=arbitration_rows,
        arbitration_enabled=arbitration_enabled,
        total_claims=len(rows),
        passing_claims=counts[ClaimStatus.PASS],
        failing_claims=counts[ClaimStatus.FAIL],
        stale_claims=counts[ClaimStatus.STALE],
        unsupported_claims=counts[ClaimStatus.UNSUPPORTED],
        error_claims=counts[ClaimStatus.ERROR],
        open_crux_count=open_crux_total,
        active_arbitration_count=active_arb_count,
    )


def build_truth_map_from_manifests(
    *,
    manifest_paths: list[Path],
    repo_root: Path | None = None,
    crux_results: list[CruxFinderResult] | None = None,
    top_k_cruxes: int = 3,
    open_crux_score_threshold: float = 0.3,
    dry_run: bool = True,
) -> OrgTruthMapReport:
    """Load DIC-13 YAML manifests, verify claims, and build a truth map."""
    import yaml  # project-level dep; local import keeps module testable without it

    from aragora.epistemic.claim_verifier import ClaimVerifier

    verifier = ClaimVerifier(repo_root=repo_root, dry_run=dry_run)
    all_results: list[ClaimResult] = []
    all_metadata: dict[str, dict[str, Any]] = {}
    for path in manifest_paths:
        with open(path) as fh:
            manifest = yaml.safe_load(fh)
        for claim in manifest.get("claims", []):
            all_metadata[claim.get("claim_id", "<unknown>")] = claim
        all_results.extend(verifier.verify_manifest(path))

    return build_truth_map(
        claim_results=all_results,
        claim_metadata=all_metadata,
        crux_results=crux_results,
        top_k_cruxes=top_k_cruxes,
        open_crux_score_threshold=open_crux_score_threshold,
    )
