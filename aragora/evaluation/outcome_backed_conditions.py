"""Frozen, no-inference condition roster for the outcome-backed benchmark."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from aragora.evaluation.outcome_backed_corpus import BENCHMARK_ID, canonical_json_sha256


CONDITION_ROSTER_SCHEMA = "outcome-backed-condition-roster/2.0"
CLAUDE_SINGLE = "claude-single"
OPENAI_SINGLE = "openai-single"
GEMINI_SINGLE = "gemini-single"
ARAGORA_TEAM = "aragora-team"


class ConditionRosterError(ValueError):
    """Raised when a condition roster cannot be bound without substitution."""


@dataclass(frozen=True)
class ModelIdentity:
    """An exact model and credentialless transport binding."""

    family: str
    requested_model: str
    expected_resolved_model: str
    transport: str
    protocol: str
    catalog_owner: str
    identity_attestation: str
    allow_fallback: bool = False

    def to_dict(self) -> dict[str, str | bool]:
        return {
            "family": self.family,
            "requested_model": self.requested_model,
            "expected_resolved_model": self.expected_resolved_model,
            "transport": self.transport,
            "protocol": self.protocol,
            "catalog_owner": self.catalog_owner,
            "identity_attestation": self.identity_attestation,
            "allow_fallback": self.allow_fallback,
        }


@dataclass(frozen=True)
class ConditionSpec:
    condition_id: str
    members: tuple[ModelIdentity, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "members": [member.to_dict() for member in self.members],
        }


@dataclass(frozen=True)
class ConditionRosterAttestation:
    """Canonical roster payload and its content-bound digest."""

    benchmark_id: str
    conditions: tuple[ConditionSpec, ...]
    roster_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONDITION_ROSTER_SCHEMA,
            "benchmark_id": self.benchmark_id,
            "conditions": [condition.to_dict() for condition in self.conditions],
            "roster_sha256": self.roster_sha256,
        }


CLAUDE_IDENTITY = ModelIdentity(
    family="claude",
    requested_model="claude-opus-5",
    expected_resolved_model="claude-opus-5",
    transport="vibeproxy-required",
    protocol="openai-chat",
    catalog_owner="anthropic",
    identity_attestation="catalog-owner+exact-response-model",
)
OPENAI_IDENTITY = ModelIdentity(
    family="openai",
    requested_model="gpt-5.6-sol",
    expected_resolved_model="gpt-5.6-sol",
    transport="vibeproxy-required",
    protocol="openai-chat",
    catalog_owner="openai",
    identity_attestation="catalog-owner+exact-response-model",
)
GEMINI_IDENTITY = ModelIdentity(
    family="gemini",
    requested_model="gemini-3.1-pro-low",
    expected_resolved_model="gemini-3.1-pro-low",
    transport="vibeproxy-required",
    protocol="openai-chat",
    catalog_owner="antigravity",
    identity_attestation="catalog-owner+exact-response-model",
)

FROZEN_CONDITION_ROSTER = (
    ConditionSpec(CLAUDE_SINGLE, (CLAUDE_IDENTITY,)),
    ConditionSpec(OPENAI_SINGLE, (OPENAI_IDENTITY,)),
    ConditionSpec(GEMINI_SINGLE, (GEMINI_IDENTITY,)),
    ConditionSpec(ARAGORA_TEAM, (CLAUDE_IDENTITY, OPENAI_IDENTITY, GEMINI_IDENTITY)),
)

_EXPECTED_IDENTITIES = {
    identity.family: identity for identity in (CLAUDE_IDENTITY, OPENAI_IDENTITY, GEMINI_IDENTITY)
}
_EXPECTED_CONDITIONS = {
    CLAUDE_SINGLE: ("claude",),
    OPENAI_SINGLE: ("openai",),
    GEMINI_SINGLE: ("gemini",),
    ARAGORA_TEAM: ("claude", "openai", "gemini"),
}
_EXPECTED_CONDITION_ORDER = tuple(_EXPECTED_CONDITIONS)


def _validate_member(member: ModelIdentity, *, path: str) -> None:
    expected = _EXPECTED_IDENTITIES.get(member.family)
    if expected is None:
        raise ConditionRosterError(f"{path} has unknown model family {member.family!r}")
    if member != expected:
        raise ConditionRosterError(
            f"{path} must use the exact frozen {member.family!r} identity; "
            "model substitutions, owner drift, alternate transports, and fallback are forbidden"
        )


def preflight_condition_roster(
    conditions: Sequence[ConditionSpec] = FROZEN_CONDITION_ROSTER,
) -> ConditionRosterAttestation:
    """Validate and attest the fixed roster without constructing model clients."""

    frozen = tuple(conditions)
    condition_ids = tuple(condition.condition_id for condition in frozen)
    if len(set(condition_ids)) != len(condition_ids):
        raise ConditionRosterError("condition roster contains duplicate condition IDs")
    if condition_ids != _EXPECTED_CONDITION_ORDER:
        missing = sorted(set(_EXPECTED_CONDITION_ORDER) - set(condition_ids))
        unknown = sorted(set(condition_ids) - set(_EXPECTED_CONDITION_ORDER))
        detail: list[str] = []
        if missing:
            detail.append(f"missing={missing}")
        if unknown:
            detail.append(f"unknown={unknown}")
        if not detail:
            detail.append("condition order differs from the frozen order")
        raise ConditionRosterError("invalid condition set: " + "; ".join(detail))

    for condition in frozen:
        expected_families = _EXPECTED_CONDITIONS[condition.condition_id]
        actual_families = tuple(member.family for member in condition.members)
        if len(set(actual_families)) != len(actual_families):
            raise ConditionRosterError(
                f"condition {condition.condition_id!r} contains a duplicate model family"
            )
        if actual_families != expected_families:
            raise ConditionRosterError(
                f"condition {condition.condition_id!r} must use ordered families "
                f"{expected_families!r}, got {actual_families!r}"
            )
        for index, member in enumerate(condition.members):
            _validate_member(member, path=f"{condition.condition_id}.members[{index}]")

    unhashed = {
        "schema_version": CONDITION_ROSTER_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "conditions": [condition.to_dict() for condition in frozen],
    }
    return ConditionRosterAttestation(
        benchmark_id=BENCHMARK_ID,
        conditions=frozen,
        roster_sha256=canonical_json_sha256(unhashed),
    )


__all__ = [
    "ARAGORA_TEAM",
    "CLAUDE_SINGLE",
    "CONDITION_ROSTER_SCHEMA",
    "FROZEN_CONDITION_ROSTER",
    "GEMINI_SINGLE",
    "OPENAI_SINGLE",
    "ConditionRosterAttestation",
    "ConditionRosterError",
    "ConditionSpec",
    "ModelIdentity",
    "preflight_condition_roster",
]
