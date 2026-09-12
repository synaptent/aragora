"""A2A agent registration bridge — AGT-02 / #6063 sub-deliverable 4.

Agents register themselves with a stable ``agent_id``, a set of
:class:`AgentCapability` strings, an optional Ed25519 ``public_key``, and an
optional ``endpoint_url``.  The resulting :class:`AgentRegistrationRecord` can
be held in the lightweight in-process :class:`RegistrationStore` (useful in
tests and single-process deployments) or handed off to the identity-contract
layer (``aragora/blockchain/contracts/identity.py``) once that wiring lands in
a follow-up slice.

Gate: ``ARAGORA_A2A_REGISTRATION_ENABLED`` (default **off**).  The dataclasses
and the store are always importable and safe to construct; only
:func:`register_agent` and :func:`lookup_agent` check the flag, so callers
that just need typed objects are never blocked.

Out of scope:
- Persistence beyond process lifetime (follow-up: identity-contract bridge).
- HTTP routes for registration (follow-up: server endpoint slice).
- Reputation read/write (AGT-05 track).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Sequence

from aragora.protocols.a2a.types import AgentCapability

__all__ = [
    "registration_enabled",
    "RegistrationError",
    "AgentRegistrationRecord",
    "RegistrationStore",
    "register_agent",
    "lookup_agent",
]

_TRUTHY = {"1", "true", "yes", "on"}

_default_store: RegistrationStore | None = None


def registration_enabled() -> bool:
    raw = os.environ.get("ARAGORA_A2A_REGISTRATION_ENABLED", "").strip().lower()
    return raw in _TRUTHY


def _require_enabled() -> None:
    if not registration_enabled():
        raise RegistrationError(
            "Set ARAGORA_A2A_REGISTRATION_ENABLED=1 to enable A2A registration."
        )


class RegistrationError(RuntimeError):
    """Raised when registration is called while the feature gate is off,
    or when a conflict or lookup failure occurs."""


@dataclass(frozen=True)
class AgentRegistrationRecord:
    """Immutable snapshot of a registered agent's identity and capabilities.

    ``public_key`` is an opaque string (base64-encoded Ed25519 or similar);
    the cryptographic verification bridge lands in a follow-up PR once the
    identity-contract wiring is ready.
    """

    agent_id: str
    capabilities: frozenset[str]
    public_key: str | None
    endpoint_url: str | None
    registered_at: datetime

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "capabilities": sorted(self.capabilities),
            "public_key": self.public_key,
            "endpoint_url": self.endpoint_url,
            "registered_at": self.registered_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "AgentRegistrationRecord":
        """Rebuild a record from :meth:`to_dict` output.

        Persisted records are untrusted input: every field is validated and a
        malformed record raises :class:`RegistrationError` instead of yielding
        a half-formed identity.
        """
        if not isinstance(data, dict):
            raise RegistrationError("record must be a mapping")

        raw_id = data.get("agent_id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise RegistrationError("agent_id must be a non-empty string")

        raw_caps = data.get("capabilities", [])
        if not isinstance(raw_caps, list):
            raise RegistrationError("capabilities must be a list")
        if not raw_caps or not all(isinstance(c, str) and c.strip() for c in raw_caps):
            raise RegistrationError("capabilities must be a non-empty list of non-empty strings")

        raw_ts = data.get("registered_at")
        if not isinstance(raw_ts, str) or not raw_ts.strip():
            raise RegistrationError("registered_at must be an ISO-8601 string")
        try:
            ts = datetime.fromisoformat(raw_ts)
        except ValueError as exc:
            raise RegistrationError(f"registered_at is not ISO-8601: {raw_ts!r}") from exc
        if ts.tzinfo is None or ts.utcoffset() is None:
            raise RegistrationError("registered_at must be timezone-aware")

        def _optional_str(key: str) -> str | None:
            value = data.get(key)
            if value is None:
                return None
            if not isinstance(value, str) or not value.strip():
                raise RegistrationError(f"{key} must be a non-empty string or null")
            return value

        return cls(
            agent_id=raw_id.strip(),
            capabilities=frozenset(c.strip() for c in raw_caps),
            public_key=_optional_str("public_key"),
            endpoint_url=_optional_str("endpoint_url"),
            registered_at=ts,
        )


@dataclass
class RegistrationStore:
    """Thread-unsafe in-process registry for agent registrations.

    Suitable for unit tests and single-process evaluation.  Multi-process or
    persistent deployments should route through the identity-contract bridge
    (out of scope for this slice).
    """

    _records: dict[str, AgentRegistrationRecord] = field(
        default_factory=dict, init=False, repr=False
    )

    def put(self, record: AgentRegistrationRecord, *, overwrite: bool = False) -> None:
        if record.agent_id in self._records and not overwrite:
            raise RegistrationError(
                f"Agent '{record.agent_id}' is already registered. Pass overwrite=True to replace."
            )
        self._records[record.agent_id] = record

    def get(self, agent_id: str) -> AgentRegistrationRecord | None:
        return self._records.get(agent_id)

    def all(self) -> list[AgentRegistrationRecord]:
        return list(self._records.values())

    def remove(self, agent_id: str) -> bool:
        return self._records.pop(agent_id, None) is not None

    def __len__(self) -> int:
        return len(self._records)


def _get_default_store() -> RegistrationStore:
    global _default_store
    if _default_store is None:
        _default_store = RegistrationStore()
    return _default_store


def register_agent(
    agent_id: str,
    capabilities: Sequence[str | AgentCapability],
    *,
    public_key: str | None = None,
    endpoint_url: str | None = None,
    store: RegistrationStore | None = None,
    overwrite: bool = False,
    registered_at: datetime | None = None,
) -> AgentRegistrationRecord:
    """Register an agent, returning the persisted :class:`AgentRegistrationRecord`.

    Raises :class:`RegistrationError` if the gate is off or if ``agent_id`` is
    already present in the store and ``overwrite`` is False.
    """
    _require_enabled()
    if not agent_id or not agent_id.strip():
        raise RegistrationError("agent_id must be a non-empty string.")
    if not capabilities:
        raise RegistrationError("At least one capability is required.")

    cap_strings: frozenset[str] = frozenset(
        c.value if isinstance(c, AgentCapability) else str(c) for c in capabilities
    )
    record = AgentRegistrationRecord(
        agent_id=agent_id.strip(),
        capabilities=cap_strings,
        public_key=public_key,
        endpoint_url=endpoint_url,
        registered_at=registered_at or datetime.now(tz=UTC),
    )
    target = store if store is not None else _get_default_store()
    target.put(record, overwrite=overwrite)
    return record


def lookup_agent(
    agent_id: str,
    *,
    store: RegistrationStore | None = None,
) -> AgentRegistrationRecord | None:
    """Return the :class:`AgentRegistrationRecord` for *agent_id*, or None.

    Raises :class:`RegistrationError` if the gate is off.
    """
    _require_enabled()
    target = store if store is not None else _get_default_store()
    return target.get(agent_id)
