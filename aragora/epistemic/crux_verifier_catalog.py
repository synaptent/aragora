"""CruxVerifierCatalog — candidate-verifier enrichment for CruxSets (DIC-15 / #6025).

Fills the ``Crux.candidate_verifier`` field that ``build_cruxset_from_analysis``
always leaves empty.  Matching: ``pattern`` is a crux_id prefix OR a
case-insensitive statement substring; first matching entry wins.

:func:`enrich_cruxset` requires ``ARAGORA_CRUXSET_EMISSION_ENABLED=1`` and is
idempotent — cruxes that already have a ``candidate_verifier`` are left unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Sequence

from aragora.reasoning.cruxset import Crux, CruxSet

_EMISSION_ENV_VAR = "ARAGORA_CRUXSET_EMISSION_ENABLED"
_TRUTHY = {"1", "true", "yes", "on"}


def _cruxset_emission_enabled() -> bool:
    return str(os.environ.get(_EMISSION_ENV_VAR) or "").strip().lower() in _TRUTHY


def _require_enabled() -> None:
    if not _cruxset_emission_enabled():
        raise RuntimeError(
            f"enrich_cruxset requires {_EMISSION_ENV_VAR}=1; "
            "set the flag before enriching CruxSets."
        )


@dataclass(frozen=True)
class VerifierEntry:
    """One (pattern, verifier) mapping in the catalog.

    Matching semantics:
    - If ``pattern`` is a prefix of ``crux.crux_id`` → match.
    - Else if ``pattern`` (case-insensitive) is a substring of
      ``crux.statement`` → match.

    The first matching entry wins.
    """

    pattern: str
    verifier: str

    def __post_init__(self) -> None:
        if not self.pattern.strip():
            raise ValueError("VerifierEntry.pattern must be non-empty")
        if not self.verifier.strip():
            raise ValueError("VerifierEntry.verifier must be non-empty")

    def matches(self, crux: Crux) -> bool:
        if crux.crux_id.startswith(self.pattern):
            return True
        return self.pattern.lower() in crux.statement.lower()


@dataclass
class CruxVerifierCatalog:
    """Ordered list of :class:`VerifierEntry` objects; first match wins."""

    entries: list[VerifierEntry] = field(default_factory=list)

    @classmethod
    def from_dict(cls, mapping: dict[str, str]) -> "CruxVerifierCatalog":
        """Build a catalog from a ``{pattern: verifier}`` dict.

        Entries are inserted in iteration order (Python 3.7+ dict order is
        insertion order), so the caller controls priority.
        """
        return cls(entries=[VerifierEntry(pattern=p, verifier=v) for p, v in mapping.items()])

    @classmethod
    def from_entries(cls, entries: Sequence[VerifierEntry]) -> "CruxVerifierCatalog":
        return cls(entries=list(entries))

    def lookup(self, crux: Crux) -> str:
        """Return the first matching verifier string, or ``""`` if none match."""
        for entry in self.entries:
            if entry.matches(crux):
                return entry.verifier
        return ""

    def __len__(self) -> int:
        return len(self.entries)


def enrich_cruxset(cruxset: CruxSet, catalog: CruxVerifierCatalog) -> CruxSet:
    """Return a new CruxSet with ``candidate_verifier`` populated from *catalog*.

    Requires ``ARAGORA_CRUXSET_EMISSION_ENABLED=1``.  Cruxes that already have
    a non-empty ``candidate_verifier`` are left unchanged.  If nothing changes,
    the original object is returned (no rebuild overhead).  ``cruxset_id`` is
    stable across enrichment; ``checksum`` reflects the new payload.
    """
    _require_enabled()

    updated: list[Crux] = []
    changed = False
    for crux in cruxset.cruxes:
        if (crux.candidate_verifier or "").strip():
            updated.append(crux)
            continue
        verifier = catalog.lookup(crux)
        if verifier:
            updated.append(replace(crux, candidate_verifier=verifier))
            changed = True
        else:
            updated.append(crux)

    if not changed:
        return cruxset

    return CruxSet.build(
        question=cruxset.question,
        cruxes=updated,
        decision=cruxset.decision,
        evidence_gaps=cruxset.evidence_gaps,
        counterfactual_notes=cruxset.counterfactual_notes,
        verifier_candidates=cruxset.verifier_candidates,
        receipt_id=cruxset.receipt_id,
        provenance=dict(cruxset.provenance),
        created_at=cruxset.created_at,
        # Enrichment only sets candidate_verifier. Without this, CruxSet.build
        # restamps a deserialized set with the current CRUXSET_SCHEMA_VERSION,
        # silently changing metadata this function does not own.
        schema_version=cruxset.schema_version,
    )


__all__ = [
    "CruxVerifierCatalog",
    "VerifierEntry",
    "enrich_cruxset",
]
