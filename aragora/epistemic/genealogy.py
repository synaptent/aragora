"""Epistemic Genealogy ledger — lineage view for proof-carrying code units (DIC-24 / #6218).

Read-only ancestry view.  Given a *code_unit_id*, returns an ordered chain of
evidence nodes (decision receipts, decay signals, crux receipts, and repair
proposals) that explains why a code path looks the way it does today.

No new persistence model is introduced.  ``GenealogyStore`` is a simple
protocol whose :class:`InMemoryGenealogyStore` is used in tests; production
wiring to receipt/KM stores is deferred to the DIC-23..28 activation gate.

Flag: ``ARAGORA_GENEALOGY_ENABLED`` (default False).  The data classes and
store implementations are always importable; only ``get_genealogy`` checks
the flag when ``require_enabled=True`` (the default for production callers).
Tests and demos should set the flag at the process boundary; this module does
not mutate ``os.environ``.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Protocol, get_args, runtime_checkable

UTC = timezone.utc

EntryKind = Literal["decision_receipt", "decay_signal", "crux_receipt", "repair_proposal"]

_ENTRY_KINDS: frozenset[str] = frozenset(get_args(EntryKind))


def _genealogy_enabled() -> bool:
    raw = str(os.environ.get("ARAGORA_GENEALOGY_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Core data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenealogyEntry:
    """One node in a code unit's lineage chain.

    ``entry_kind`` classifies the artifact source.  ``entry_id`` is the
    artifact's own stable identifier.  ``checksum`` is the SHA-256 supplied
    by the artifact (or computed by the caller from its canonical JSON).
    ``timestamp`` is ISO-8601 UTC.
    """

    entry_kind: EntryKind
    entry_id: str
    checksum: str
    timestamp: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.entry_kind not in _ENTRY_KINDS:
            raise ValueError(f"unknown entry_kind: {self.entry_kind!r}")
        if not self.entry_id:
            raise ValueError("entry_id must be non-empty")
        # Q2: validate and normalize timestamp to canonical UTC form so that
        # lex-sort is safe even when producers use mixed ISO-8601 representations.
        try:
            dt = datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            raise ValueError(f"timestamp must be ISO-8601 UTC: {self.timestamp!r}")
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(f"timestamp must include timezone: {self.timestamp!r}")
        normalized = dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        # Q10: defensive copy so caller mutations don't reach inside frozen entry.
        object.__setattr__(self, "timestamp", normalized)
        object.__setattr__(self, "metadata", deepcopy(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "entry_kind": self.entry_kind,
            "entry_id": self.entry_id,
            "checksum": self.checksum,
            "timestamp": self.timestamp,
        }
        if self.metadata:
            d["metadata"] = deepcopy(self.metadata)  # Q10: copy on serialization
        return d


def _chain_checksum(entries: list[GenealogyEntry]) -> str:
    """SHA-256 over canonical-sorted ancestry JSON.  Order-independent."""
    payload = sorted(
        [e.to_dict() for e in entries],
        key=lambda d: (d["timestamp"], d["entry_id"]),
    )
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class CodeUnitGenealogy:
    """Full lineage view for one proof-carrying code unit.

    ``entries`` are ordered oldest-first by timestamp then entry_id.
    ``chain_checksum`` is SHA-256 of the canonical-sorted entries JSON.
    It proves set membership (same entries regardless of insertion order),
    not historical sequence — two genealogies are equal iff they contain the
    same set of entries.
    """

    code_unit_id: str
    entries: list[GenealogyEntry]
    chain_checksum: str
    generated_at: str

    @classmethod
    def build(cls, code_unit_id: str, entries: list[GenealogyEntry]) -> CodeUnitGenealogy:
        if not code_unit_id:
            raise ValueError("code_unit_id must be non-empty")
        sorted_entries = sorted(entries, key=lambda e: (e.timestamp, e.entry_id))
        return cls(
            code_unit_id=code_unit_id,
            entries=sorted_entries,
            chain_checksum=_chain_checksum(sorted_entries),
            generated_at=datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_unit_id": self.code_unit_id,
            "entries": [e.to_dict() for e in self.entries],
            "chain_checksum": self.chain_checksum,
            "generated_at": self.generated_at,
            "entry_count": len(self.entries),
        }


# ---------------------------------------------------------------------------
# Store protocol and in-memory implementation
# ---------------------------------------------------------------------------


@runtime_checkable
class GenealogyStore(Protocol):
    """Read-only ancestry source for one or more code units."""

    def get_entries(self, code_unit_id: str) -> list[GenealogyEntry]:
        """Return all lineage entries for *code_unit_id* in any order."""
        ...


@dataclass
class InMemoryGenealogyStore:
    """Simple dict-backed store for tests and demos."""

    _entries: dict[str, list[GenealogyEntry]] = field(default_factory=dict)

    def add(self, code_unit_id: str, entry: GenealogyEntry) -> None:
        self._entries.setdefault(code_unit_id, []).append(entry)

    def get_entries(self, code_unit_id: str) -> list[GenealogyEntry]:
        return list(self._entries.get(code_unit_id, []))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_genealogy(
    code_unit_id: str,
    store: GenealogyStore,
    *,
    require_enabled: bool = True,
) -> CodeUnitGenealogy:
    """Return the lineage view for *code_unit_id*.

    When *require_enabled* is True (default), raises ``RuntimeError`` if
    ``ARAGORA_GENEALOGY_ENABLED`` is not set.  Tests can pass
    ``require_enabled=False`` or set the env var with ``monkeypatch``.
    """
    if not code_unit_id:
        raise ValueError("code_unit_id must be non-empty")
    if require_enabled and not _genealogy_enabled():
        raise RuntimeError(
            "ARAGORA_GENEALOGY_ENABLED is not set; "
            "set it to '1' or pass require_enabled=False in tests"
        )
    entries = store.get_entries(code_unit_id)
    return CodeUnitGenealogy.build(code_unit_id, entries)
