"""Typed ExecutableClaim manifest model (DIC-13 / #6023).

Mirrors docs/status/claims/executable_claim_manifest.schema.json.

The dataclasses are always importable and safe to construct.  Only the
directory scanner ``load_claims_from_dir`` is flag-gated via
``ARAGORA_EPISTEMIC_CLAIMS_ENABLED`` (default off) so callers that just
need typed claim objects are never blocked by the flag.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


def _claims_enabled() -> bool:
    raw = str(os.environ.get("ARAGORA_EPISTEMIC_CLAIMS_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClaimConfidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class VerificationKind(str, Enum):
    COMMAND = "command"
    WORKFLOW = "workflow"
    MANUAL = "manual"


class FailureSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class FailureAction(str, Enum):
    REPORT_ONLY = "report_only"
    RERUN_WORKFLOW = "rerun_workflow"
    PROPOSE_BOUNDED_ISSUE = "propose_bounded_issue"


class ClaimTruthState(str, Enum):
    LIVE = "live"
    UNSUPPORTED = "unsupported"
    ASPIRATIONAL = "aspirational"


# ---------------------------------------------------------------------------
# Supporting dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ClaimEvidence:
    """One evidence pointer for an ExecutableClaim.

    Requires at least one of: path, workflow, issue, pull_request, url, note.
    """

    path: str | None = None
    workflow: str | None = None
    issue: int | None = None
    pull_request: int | None = None
    url: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not any(
            v is not None
            for v in (self.path, self.workflow, self.issue, self.pull_request, self.url, self.note)
        ):
            raise ValueError(
                "ClaimEvidence requires at least one of: path, workflow, issue, "
                "pull_request, url, note"
            )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClaimEvidence:
        return cls(
            path=d.get("path"),
            workflow=d.get("workflow"),
            issue=d.get("issue"),
            pull_request=d.get("pull_request"),
            url=d.get("url"),
            note=d.get("note"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            k: v
            for k, v in {
                "path": self.path,
                "workflow": self.workflow,
                "issue": self.issue,
                "pull_request": self.pull_request,
                "url": self.url,
                "note": self.note,
            }.items()
            if v is not None
        }


@dataclass
class ClaimVerification:
    kind: VerificationKind
    command: str
    expected_result: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClaimVerification:
        return cls(
            kind=VerificationKind(d["kind"]),
            command=d["command"],
            expected_result=d.get("expected_result"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"kind": self.kind.value, "command": self.command}
        if self.expected_result is not None:
            out["expected_result"] = self.expected_result
        return out


@dataclass
class ClaimFailurePolicy:
    severity: FailureSeverity
    allowed_action: FailureAction
    repair_note: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClaimFailurePolicy:
        return cls(
            severity=FailureSeverity(d["severity"]),
            allowed_action=FailureAction(d["allowed_action"]),
            repair_note=d.get("repair_note"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "severity": self.severity.value,
            "allowed_action": self.allowed_action.value,
        }
        if self.repair_note is not None:
            out["repair_note"] = self.repair_note
        return out


@dataclass
class ClaimReceipt:
    type: str
    path: str | None = None
    workflow: str | None = None
    note: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClaimReceipt:
        return cls(
            type=d["type"],
            path=d.get("path"),
            workflow=d.get("workflow"),
            note=d.get("note"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        for key in ("path", "workflow", "note"):
            val = getattr(self, key)
            if val is not None:
                out[key] = val
        return out


@dataclass
class ClaimTruthStatus:
    """Declared truth posture used by the report-only freshness layer."""

    state: ClaimTruthState
    last_verified_at: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if self.state == ClaimTruthState.LIVE and self.last_verified_at is None:
            raise ValueError("live truth_status requires last_verified_at")
        if self.last_verified_at is not None:
            normalized = self.last_verified_at.removesuffix("Z") + (
                "+00:00" if self.last_verified_at.endswith("Z") else ""
            )
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError as exc:
                raise ValueError("last_verified_at must be an RFC 3339 timestamp") from exc
            if parsed.tzinfo is None:
                raise ValueError("last_verified_at must include a timezone")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClaimTruthStatus:
        return cls(
            state=ClaimTruthState(d["state"]),
            last_verified_at=d.get("last_verified_at"),
            note=d.get("note"),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"state": self.state.value}
        if self.last_verified_at is not None:
            out["last_verified_at"] = self.last_verified_at
        if self.note is not None:
            out["note"] = self.note
        return out


# ---------------------------------------------------------------------------
# Primary model
# ---------------------------------------------------------------------------


@dataclass
class ExecutableClaim:
    """A versioned, evidence-linked, verifiable organizational claim."""

    claim_id: str
    statement: str
    owner: str
    scope: str
    confidence: ClaimConfidence
    evidence: list[ClaimEvidence]
    freshness_sla_hours: int
    verification: ClaimVerification
    failure: ClaimFailurePolicy
    receipts: list[ClaimReceipt]
    truth_status: ClaimTruthStatus | None = None

    def __post_init__(self) -> None:
        if not self.claim_id or not self.claim_id[0].isalnum():
            raise ValueError(f"claim_id must start with alphanumeric: {self.claim_id!r}")
        if not self.statement:
            raise ValueError("statement must be non-empty")
        if not self.evidence:
            raise ValueError("evidence must have at least one entry")
        if self.freshness_sla_hours < 1:
            raise ValueError("freshness_sla_hours must be >= 1")
        if not self.receipts:
            raise ValueError("receipts must have at least one entry")

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ExecutableClaim:
        return cls(
            claim_id=d["claim_id"],
            statement=d["statement"],
            owner=d["owner"],
            scope=d["scope"],
            confidence=ClaimConfidence(d["confidence"]),
            evidence=[ClaimEvidence.from_dict(e) for e in d["evidence"]],
            freshness_sla_hours=int(d["freshness_sla_hours"]),
            verification=ClaimVerification.from_dict(d["verification"]),
            failure=ClaimFailurePolicy.from_dict(d["failure"]),
            receipts=[ClaimReceipt.from_dict(r) for r in d["receipts"]],
            truth_status=(
                ClaimTruthStatus.from_dict(d["truth_status"])
                if d.get("truth_status") is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "claim_id": self.claim_id,
            "statement": self.statement,
            "owner": self.owner,
            "scope": self.scope,
            "confidence": self.confidence.value,
            "evidence": [e.to_dict() for e in self.evidence],
            "freshness_sla_hours": self.freshness_sla_hours,
            "verification": self.verification.to_dict(),
            "failure": self.failure.to_dict(),
            "receipts": [r.to_dict() for r in self.receipts],
        }
        if self.truth_status is not None:
            out["truth_status"] = self.truth_status.to_dict()
        return out


# ---------------------------------------------------------------------------
# Manifest container
# ---------------------------------------------------------------------------


@dataclass
class ClaimManifest:
    """Versioned collection of ExecutableClaims loaded from a YAML file."""

    schema_version: int
    manifest_id: str
    claims: list[ExecutableClaim]
    description: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ClaimManifest:
        if d.get("schema_version") != 1:
            raise ValueError(f"unsupported schema_version: {d.get('schema_version')!r}")
        return cls(
            schema_version=int(d["schema_version"]),
            manifest_id=str(d["manifest_id"]),
            description=str(d.get("description") or ""),
            claims=[ExecutableClaim.from_dict(c) for c in d.get("claims", [])],
        )

    @classmethod
    def from_yaml_file(cls, path: Path) -> ClaimManifest:
        with open(path) as fh:
            return cls.from_dict(yaml.safe_load(fh))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "manifest_id": self.manifest_id,
            "claims": [c.to_dict() for c in self.claims],
        }
        if self.description:
            out["description"] = self.description
        return out


# ---------------------------------------------------------------------------
# Flag-gated directory scanner
# ---------------------------------------------------------------------------


def load_claims_from_dir(claims_dir: Path) -> list[ClaimManifest]:
    """Load all ``*.yaml`` claim manifests from *claims_dir*.

    Returns an empty list when ``ARAGORA_EPISTEMIC_CLAIMS_ENABLED`` is
    not set, so callers can always call this without a separate enable check.
    Silently skips files that fail to parse.
    """
    if not _claims_enabled():
        return []
    manifests: list[ClaimManifest] = []
    for yaml_path in sorted(claims_dir.glob("*.yaml")):
        try:
            manifests.append(ClaimManifest.from_yaml_file(yaml_path))
        except (KeyError, ValueError):
            pass
    return manifests
