"""Human-oversight attestation blocks for ODR receipts (ODR-6 / #8230).

The machine-readable form of the human gate this repo already operates
manually for Tier-4 settlements: **who** accepted the risk (an oversight
identity, credential-separated from the execution identity), **what they
saw** (head SHA, evidence digest), **when**, and **via what mechanism**
(the ``aragora/human-settlement`` commit status, a preapproval comment).

Design rules:

- **Honesty by construction** — a decision without human oversight is
  recorded with the explicit ``autonomous`` disposition (already the ODR
  export default), never by silently omitting the block.
- **Identity separation is enforced** — an attestation whose oversight
  identity equals the execution identity is refused: self-attestation is
  exactly what the oversight layer exists to prevent (see
  ``docs/specs/TAMPER_EVIDENT_TRAIL.md`` H2, the #8169 precedent gap).

Usage with the ODR export::

    att = build_oversight_attestation(
        attestor_id="scarmani",
        attested_at="2026-07-17T12:00:00+00:00",
        mechanism_type="settlement_status",
        mechanism_context=HUMAN_SETTLEMENT_CONTEXT,
        head_sha="abc123...",
        evidence_digest="sha256:...",
        execution_identity_id="an0mium",
    )
    odr = decision_receipt_to_odr(receipt, attestation=att.to_dict())
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

__all__ = [
    "HUMAN_SETTLEMENT_CONTEXT",
    "AUTONOMOUS_DISPOSITION",
    "HUMAN_ATTESTED_DISPOSITION",
    "OversightAttestation",
    "attestation_from_preapproval_comment",
    "attestation_from_settlement_status",
    "build_oversight_attestation",
]

# Keep in sync with aragora/swarm/merge_quorum_io.py — the gate-trusted
# commit-status context whose creator identity is the oversight signal.
HUMAN_SETTLEMENT_CONTEXT = "aragora/human-settlement"

AUTONOMOUS_DISPOSITION = "autonomous"
HUMAN_ATTESTED_DISPOSITION = "human_attested"

_SHA256_RE = re.compile(r"\b[0-9a-f]{64}\b")

_MECHANISM_TYPES = frozenset({"settlement_status", "preapproval_comment", "manual"})


@dataclass
class OversightAttestation:
    """A human-oversight attestation, serializable as the ODR attestation block.

    ``to_dict()`` output is accepted directly by
    :func:`aragora.gauntlet.odr_export.decision_receipt_to_odr` via its
    ``attestation=`` parameter (which passes the block through and defaults
    the disposition to ``human_attested``).
    """

    attestor_id: str
    attested_at: str
    mechanism_type: str
    attestor_role: str = "oversight"
    execution_identity_id: str | None = None
    head_sha: str | None = None
    evidence_digest: str | None = None
    mechanism_context: str | None = None
    mechanism_ref: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.attestor_id or not str(self.attestor_id).strip():
            raise ValueError("attestor_id is required for a human attestation")
        if not self.attested_at:
            raise ValueError("attested_at is required for a human attestation")
        if self.mechanism_type not in _MECHANISM_TYPES:
            raise ValueError(
                f"mechanism_type must be one of {sorted(_MECHANISM_TYPES)}, "
                f"got {self.mechanism_type!r}"
            )
        # Credential separation: the identity accepting the risk must not be
        # the identity that executed the decision (TET H2). Refusing here is
        # fail-closed — a self-attested block is worse than an honest
        # `autonomous` disposition.
        if (
            self.execution_identity_id
            and str(self.attestor_id).strip().lower()
            == str(self.execution_identity_id).strip().lower()
        ):
            raise ValueError(
                "oversight identity must differ from execution identity "
                f"(both are {self.attestor_id!r}); record the decision as "
                "'autonomous' instead of self-attesting"
            )

    def to_dict(self) -> dict[str, Any]:
        block: dict[str, Any] = {
            "disposition": HUMAN_ATTESTED_DISPOSITION,
            "attestor": {"id": self.attestor_id, "role": self.attestor_role},
            "attested_at": self.attested_at,
            "mechanism": {"type": self.mechanism_type},
        }
        if self.execution_identity_id:
            block["execution_identity"] = {"id": self.execution_identity_id}
        observed: dict[str, Any] = {}
        if self.head_sha:
            observed["head_sha"] = self.head_sha
        if self.evidence_digest:
            observed["evidence_digest"] = self.evidence_digest
        if observed:
            block["observed"] = observed
        if self.mechanism_context:
            block["mechanism"]["context"] = self.mechanism_context
        if self.mechanism_ref:
            block["mechanism"]["ref"] = self.mechanism_ref
        if self.extra:
            block.update(dict(self.extra))
        return block


def build_oversight_attestation(
    *,
    attestor_id: str,
    attested_at: str,
    mechanism_type: str,
    attestor_role: str = "oversight",
    execution_identity_id: str | None = None,
    head_sha: str | None = None,
    evidence_digest: str | None = None,
    mechanism_context: str | None = None,
    mechanism_ref: str | None = None,
) -> OversightAttestation:
    """Build a validated :class:`OversightAttestation` (keyword-only)."""
    return OversightAttestation(
        attestor_id=attestor_id,
        attested_at=attested_at,
        mechanism_type=mechanism_type,
        attestor_role=attestor_role,
        execution_identity_id=execution_identity_id,
        head_sha=head_sha,
        evidence_digest=evidence_digest,
        mechanism_context=mechanism_context,
        mechanism_ref=mechanism_ref,
    )


def attestation_from_settlement_status(
    status: Mapping[str, Any],
    *,
    head_sha: str,
    execution_identity_id: str | None = None,
    expected_context: str = HUMAN_SETTLEMENT_CONTEXT,
) -> OversightAttestation:
    """Build an attestation from a GitHub commit-status API object.

    The ``aragora/human-settlement`` status is the repo's gate-trusted
    oversight signal: its ``creator.login`` is the oversight identity, it is
    head-bound (posted on ``head_sha``), and its description embeds the
    settlement receipt's SHA-256 for the status→receipt evidence link (see
    ``review_queue._post_human_settlement_status``).

    Args:
        status: The statuses API object (``creator``, ``created_at``,
            ``context``, ``description``, ``url``).
        head_sha: The commit SHA the status was posted on (the statuses API
            object does not embed it; the caller queried by SHA).
        execution_identity_id: The identity that executed/authored the
            decision, for the separation check.
    """
    # Only a successful status on the settlement context is oversight: this
    # builder is public API, so it must refuse to convert an arbitrary CI
    # status (or a failed settlement) into countable oversight evidence.
    context = str(status.get("context", "") or "")
    if context != expected_context:
        raise ValueError(
            f"status context {context!r} is not the settlement context {expected_context!r}"
        )
    state = str(status.get("state", "") or "")
    if state != "success":
        raise ValueError(f"settlement status state must be 'success', got {state!r}")
    creator = status.get("creator") or {}
    attestor_id = str(creator.get("login", "") or "")
    description = str(status.get("description", "") or "")
    digest_match = _SHA256_RE.search(description)
    return OversightAttestation(
        attestor_id=attestor_id,
        attested_at=str(status.get("created_at", "") or ""),
        mechanism_type="settlement_status",
        execution_identity_id=execution_identity_id,
        head_sha=head_sha,
        evidence_digest=f"sha256:{digest_match.group(0)}" if digest_match else None,
        mechanism_context=str(status.get("context", "") or HUMAN_SETTLEMENT_CONTEXT),
        mechanism_ref=str(status.get("url", "") or "") or None,
    )


def attestation_from_preapproval_comment(
    comment: Mapping[str, Any],
    *,
    head_sha: str | None = None,
    evidence_digest: str | None = None,
    execution_identity_id: str | None = None,
) -> OversightAttestation:
    """Build an attestation from a preapproval comment (Tier-4 flow).

    Args:
        comment: GitHub comment API object (``user.login``/``author``,
            ``created_at``, ``html_url``).
        head_sha: Head SHA the preapproval bound to, when recorded.
        evidence_digest: Digest of the evidence packet the approver saw.
        execution_identity_id: Executing identity, for the separation check.
    """
    user = comment.get("user") or comment.get("author") or {}
    attestor_id = str(user.get("login", "") or "")
    return OversightAttestation(
        attestor_id=attestor_id,
        attested_at=str(comment.get("created_at", "") or ""),
        mechanism_type="preapproval_comment",
        execution_identity_id=execution_identity_id,
        head_sha=head_sha,
        evidence_digest=evidence_digest,
        mechanism_ref=str(comment.get("html_url", "") or "") or None,
    )
