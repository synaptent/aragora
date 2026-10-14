"""Seed rows ordinary store calls can no longer write: NULL-org facts and cross-org relations."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime

from aragora.knowledge import Fact, FactRelation, FactRelationType, FactStore, ScopedFactStore


def seed_unassigned(store, statement: str, workspace: str = "default") -> Fact:
    """A legacy NULL-organization fact, as pre-scoping releases stored it."""
    fact = ScopedFactStore(store, "seed-only").add_fact(statement, workspace)
    if isinstance(store, FactStore):
        with store.connection() as conn:
            conn.execute("UPDATE facts SET org_id = NULL WHERE id = ?", (fact.id,))
    else:
        store._facts[fact.id].org_id = None
    return replace(fact, org_id=None)


def seed_relation(store, source_id: str, target_id: str) -> None:
    """A contradiction stored without an org check, as pre-scoping releases allowed."""
    rel = FactRelation(
        id=f"rel_{uuid.uuid4().hex[:12]}",
        source_fact_id=source_id,
        target_fact_id=target_id,
        relation_type=FactRelationType.CONTRADICTS,
        created_at=datetime.now(),
    )
    if isinstance(store, FactStore):
        with store.connection() as conn:
            conn.execute(
                "INSERT INTO fact_relations (id, source_fact_id, target_fact_id, "
                "relation_type, created_at) VALUES (?, ?, ?, ?, ?)",
                (rel.id, source_id, target_id, rel.relation_type.value, rel.created_at.isoformat()),
            )
    else:
        store._relations[rel.id] = rel
