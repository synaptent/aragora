"""Multi-unit genealogy report — DIC-24 / #6218.

Aggregates CodeUnitGenealogy records into a GenealogyReport for operator
display or receipt-path ingestion.  Flag: ARAGORA_GENEALOGY_ENABLED (off
by default).  Default OFF; data classes importable without the flag.
Live queue effect: none.  Gate: same as DIC-23..28.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from aragora.epistemic.genealogy import CodeUnitGenealogy, GenealogyStore, get_genealogy

UTC = timezone.utc


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class GenealogyUnitSummary:
    """Compact lineage summary for one proof-carrying code unit.

    ``entry_kinds`` is a sorted tuple of distinct entry_kind values present.
    ``oldest_timestamp`` / ``newest_timestamp`` are None for empty chains.
    """

    code_unit_id: str
    entry_count: int
    entry_kinds: tuple[str, ...]
    oldest_timestamp: str | None
    newest_timestamp: str | None
    chain_checksum: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_unit_id": self.code_unit_id,
            "entry_count": self.entry_count,
            "entry_kinds": list(self.entry_kinds),
            "oldest_timestamp": self.oldest_timestamp,
            "newest_timestamp": self.newest_timestamp,
            "chain_checksum": self.chain_checksum,
        }

    @classmethod
    def from_genealogy(cls, genealogy: CodeUnitGenealogy) -> "GenealogyUnitSummary":
        entries = genealogy.entries
        if not entries:
            return cls(
                code_unit_id=genealogy.code_unit_id,
                entry_count=0,
                entry_kinds=(),
                oldest_timestamp=None,
                newest_timestamp=None,
                chain_checksum=genealogy.chain_checksum,
            )
        kinds: tuple[str, ...] = tuple(sorted({e.entry_kind for e in entries}))
        timestamps = [e.timestamp for e in entries]
        return cls(
            code_unit_id=genealogy.code_unit_id,
            entry_count=len(entries),
            entry_kinds=kinds,
            oldest_timestamp=min(timestamps),
            newest_timestamp=max(timestamps),
            chain_checksum=genealogy.chain_checksum,
        )


@dataclass(frozen=True)
class GenealogyReport:
    """Aggregate lineage report across multiple proof-carrying code units.

    ``summaries`` is sorted by code_unit_id for deterministic output.
    """

    unit_count: int
    total_entries: int
    summaries: tuple[GenealogyUnitSummary, ...]
    generated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_count": self.unit_count,
            "total_entries": self.total_entries,
            "summaries": [s.to_dict() for s in self.summaries],
            "generated_at": self.generated_at,
        }

    def units_by_activity(self) -> list[GenealogyUnitSummary]:
        """Return summaries sorted by entry_count descending."""
        return sorted(self.summaries, key=lambda s: s.entry_count, reverse=True)

    def units_with_kind(self, kind: str) -> list[GenealogyUnitSummary]:
        """Return summaries that contain at least one entry of *kind*."""
        return [s for s in self.summaries if kind in s.entry_kinds]


def build_genealogy_report(
    code_unit_ids: Iterable[str],
    store: GenealogyStore,
    *,
    require_enabled: bool = True,
) -> GenealogyReport:
    """Build a GenealogyReport from *store* for *code_unit_ids*.

    Empty *code_unit_ids* returns an empty report without touching the flag.
    Pass ``require_enabled=False`` in tests; the flag check is in get_genealogy.
    """
    ids = list(code_unit_ids)
    if not ids:
        return GenealogyReport(
            unit_count=0, total_entries=0, summaries=(), generated_at=_utc_now_iso()
        )
    summaries = sorted(
        [
            GenealogyUnitSummary.from_genealogy(
                get_genealogy(uid, store, require_enabled=require_enabled)
            )
            for uid in ids
        ],
        key=lambda s: s.code_unit_id,
    )
    return GenealogyReport(
        unit_count=len(summaries),
        total_entries=sum(s.entry_count for s in summaries),
        summaries=tuple(summaries),
        generated_at=_utc_now_iso(),
    )
