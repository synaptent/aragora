"""Per-agent compute and cost metering for the A2A consumer surface (AGT-02).

This module is the AGT-02 billing sub-deliverable.  It gives external software
agents a canonical, machine-parseable record of the compute units, debate cost,
and verifier cost billed to them for a single A2A session.  The record is
content-addressed (SHA-256 of the canonical JSON) so downstream audit pipelines
can detect tampering.

See ``docs/plans/AGENT_CONSUMER_SURFACE.md`` §S3 (billing primitives) and
``docs/plans/AGENT_CIVILIZATION_SUBSTRATE.md`` (AGT-02).

Activation: ``ARAGORA_AGENT_METERING_ENABLED`` (default off).  All
computation is side-effect-free.  No costs are written to the billing stack
automatically; server endpoints that emit metering records will land in a
follow-up PR behind the same AGT-* "no live behavior change" rule from
``docs/status/NEXT_STEPS_CANONICAL.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

METERING_SCHEMA_VERSION = "1.0"

_METERING_FLAG = "ARAGORA_AGENT_METERING_ENABLED"
_metering_enabled_override: bool | None = None


# ---------------------------------------------------------------------------
# Flag gate
# ---------------------------------------------------------------------------


def agent_metering_enabled() -> bool:
    """Return ``True`` when agent metering records may be created and emitted.

    Checks the module-level override first, then the
    ``ARAGORA_AGENT_METERING_ENABLED`` environment variable.  Default is
    *False*; dataclass construction is always safe regardless.
    """
    if _metering_enabled_override is not None:
        return _metering_enabled_override
    raw = str(os.environ.get(_METERING_FLAG) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def enable_agent_metering() -> None:
    """Enable agent metering for the current process.

    Sets a module-level override rather than mutating ``os.environ``.
    Call :func:`reset_agent_metering` to restore env-var-driven behaviour
    (useful in test teardown).
    """
    global _metering_enabled_override
    _metering_enabled_override = True


def reset_agent_metering() -> None:
    """Clear the module-level override, reverting to env-var-driven behaviour."""
    global _metering_enabled_override
    _metering_enabled_override = None


# ---------------------------------------------------------------------------
# Record type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentMeteringRecord:
    """Immutable metering record for a single A2A agent session.

    All monetary fields are in USD; ``compute_units`` is an abstract
    platform unit (e.g., 1 unit ≈ 1 000 tokens processed).  Both default
    to zero so callers can build records incrementally.

    ``content_hash`` is set automatically by :func:`create_metering_record`
    as the SHA-256 hex digest of the canonical JSON serialisation.
    """

    agent_id: str
    session_id: str
    compute_units: float = 0.0
    debate_cost_usd: float = 0.0
    verifier_cost_usd: float = 0.0
    timestamp: str = field(
        default_factory=lambda: datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    )
    schema_version: str = METERING_SCHEMA_VERSION
    content_hash: str = ""

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def total_cost_usd(self) -> float:
        """Sum of debate and verifier costs in USD."""
        return self.debate_cost_usd + self.verifier_cost_usd

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "compute_units": self.compute_units,
            "debate_cost_usd": self.debate_cost_usd,
            "verifier_cost_usd": self.verifier_cost_usd,
            "total_cost_usd": self.total_cost_usd,
            "timestamp": self.timestamp,
            "content_hash": self.content_hash,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, indent=indent)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _canonical_payload(
    agent_id: str,
    session_id: str,
    compute_units: float,
    debate_cost_usd: float,
    verifier_cost_usd: float,
    timestamp: str,
    schema_version: str,
) -> str:
    """Return the deterministic JSON string used for content-addressing."""
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "compute_units": compute_units,
        "debate_cost_usd": debate_cost_usd,
        "schema_version": schema_version,
        "session_id": session_id,
        "timestamp": timestamp,
        "verifier_cost_usd": verifier_cost_usd,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def create_metering_record(
    *,
    agent_id: str,
    session_id: str,
    compute_units: float = 0.0,
    debate_cost_usd: float = 0.0,
    verifier_cost_usd: float = 0.0,
    timestamp: str | None = None,
) -> AgentMeteringRecord:
    """Create a content-addressed :class:`AgentMeteringRecord`.

    Raises :exc:`RuntimeError` when ``ARAGORA_AGENT_METERING_ENABLED`` is not
    set so metering records cannot be created accidentally in production paths
    that haven't opted in.

    Raises :exc:`ValueError` for invalid field values (negative costs, empty
    identifiers).
    """
    if not agent_metering_enabled():
        raise RuntimeError(
            "ARAGORA_AGENT_METERING_ENABLED is not set; "
            "metering records must not be created outside opted-in contexts."
        )

    if not agent_id or not agent_id.strip():
        raise ValueError("agent_id must be a non-empty string")
    if not session_id or not session_id.strip():
        raise ValueError("session_id must be a non-empty string")
    if compute_units < 0:
        raise ValueError(f"compute_units must be >= 0, got {compute_units}")
    if debate_cost_usd < 0:
        raise ValueError(f"debate_cost_usd must be >= 0, got {debate_cost_usd}")
    if verifier_cost_usd < 0:
        raise ValueError(f"verifier_cost_usd must be >= 0, got {verifier_cost_usd}")

    ts = timestamp or datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    canonical = _canonical_payload(
        agent_id=agent_id,
        session_id=session_id,
        compute_units=compute_units,
        debate_cost_usd=debate_cost_usd,
        verifier_cost_usd=verifier_cost_usd,
        timestamp=ts,
        schema_version=METERING_SCHEMA_VERSION,
    )
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return AgentMeteringRecord(
        agent_id=agent_id,
        session_id=session_id,
        compute_units=compute_units,
        debate_cost_usd=debate_cost_usd,
        verifier_cost_usd=verifier_cost_usd,
        timestamp=ts,
        schema_version=METERING_SCHEMA_VERSION,
        content_hash=content_hash,
    )
