"""External-verifier insertion point for high-impact pipeline actions (CLB-012).

Provides a thin, pluggable hook that lets operators register an independent
verifier (CI gate, security scan, human approval queue) for high-impact
automated actions before final promotion.

The verifier result is carried into the ReceiptEnvelope via policy_gate_result
so the audit trail always reflects whether independent verification occurred.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class HighImpactPolicy:
    """Thresholds that classify an action as high-impact.

    An action is high-impact when ANY threshold is exceeded OR when the scope
    is explicitly production-grade.
    """

    files_changed_threshold: int = 20
    production_scopes: frozenset[str] = field(
        default_factory=lambda: frozenset({"production", "prod", "live"})
    )


_DEFAULT_POLICY = HighImpactPolicy()


def requires_external_verification(
    action: dict[str, Any],
    *,
    policy: HighImpactPolicy | None = None,
) -> bool:
    """Return True when *action* meets the high-impact bar defined by *policy*.

    Args:
        action: Dict describing the action (type, scope, files_changed, …).
        policy: Override the default thresholds. Defaults to ``HighImpactPolicy()``.

    Returns:
        ``True`` when the action requires independent external verification.
    """
    p = policy or _DEFAULT_POLICY
    scope = str(action.get("scope", "")).lower()
    files_changed = int(action.get("files_changed", 0) or 0)

    if scope in p.production_scopes:
        return True
    if files_changed >= p.files_changed_threshold:
        return True
    return False


@dataclass
class ExternalVerificationResult:
    """Result of an external-verifier check.

    Attributes:
        verifier_id: Identity of the verifier that produced this result.
        verdict: One of ``"approved"``, ``"rejected"``, ``"pending"``,
            ``"not_required"``.
        rationale: Free-text explanation from the verifier.
    """

    verifier_id: str
    verdict: str = "pending"
    rationale: str = ""

    @property
    def approved(self) -> bool:
        return self.verdict == "approved" or self.verdict == "not_required"

    def to_policy_dict(self) -> dict[str, Any]:
        """Return a dict suitable for use as ``policy_gate_result`` in a ReceiptEnvelope."""
        return {
            "external_verifier": self.verifier_id,
            "verdict": self.verdict,
            "allowed": self.approved,
            "rationale": self.rationale,
        }


VerifierHook = Callable[[dict[str, Any]], ExternalVerificationResult]


class ExternalVerifier:
    """Pluggable verifier that checks high-impact actions.

    Usage::

        def my_hook(action: dict) -> ExternalVerificationResult:
            # call CI gate, security scanner, etc.
            return ExternalVerificationResult(verifier_id="ci", verdict="approved")

        verifier = ExternalVerifier(hook=my_hook)
        result = verifier.check({"type": "deploy", "scope": "production", "files_changed": 5})
        envelope = generate_receipt_envelope(receipt, policy_gate_result=result.to_policy_dict())
    """

    def __init__(
        self,
        hook: VerifierHook | None = None,
        *,
        policy: HighImpactPolicy | None = None,
        verifier_id: str = "pipeline-external-verifier",
    ) -> None:
        self._hook = hook
        self._policy = policy
        self._verifier_id = verifier_id

    def check(self, action: dict[str, Any]) -> ExternalVerificationResult:
        """Evaluate *action* and return a verification result.

        Returns:
            - ``verdict="not_required"`` when the action is not high-impact.
            - ``verdict="pending"`` when the action IS high-impact but no hook
              is registered (operator must wire up a hook for full enforcement).
            - Hook return value when a hook is registered.
        """
        if not requires_external_verification(action, policy=self._policy):
            return ExternalVerificationResult(
                verifier_id=self._verifier_id,
                verdict="not_required",
                rationale="Action does not meet high-impact threshold.",
            )

        if self._hook is None:
            return ExternalVerificationResult(
                verifier_id=self._verifier_id,
                verdict="pending",
                rationale="High-impact action requires external verification — no hook registered.",
            )

        return self._hook(action)


# Impact levels ordered from lowest to highest.
_IMPACT_LEVELS = ("low", "medium", "high", "critical")

_DEFAULT_THRESHOLD = "high"


@dataclass
class VerificationRecord:
    """Immutable record of an external verification decision."""

    verifier_id: str
    approved: bool
    notes: str
    recorded_at: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


class ExternalVerifierGate:
    """Gate that blocks execution until an external reviewer approves.

    Parameters
    ----------
    impact_threshold:
        Minimum impact level that triggers external review.
        One of ``"low"``, ``"medium"``, ``"high"``, ``"critical"``.
    taint_triggers:
        If the plan's taint_flags contain any of these strings, external
        review is required regardless of impact level.
    """

    def __init__(
        self,
        *,
        impact_threshold: str = _DEFAULT_THRESHOLD,
        taint_triggers: list[str] | None = None,
    ) -> None:
        threshold = impact_threshold.strip().lower()
        if threshold not in _IMPACT_LEVELS:
            raise ValueError(
                f"impact_threshold must be one of {_IMPACT_LEVELS!r}, got {impact_threshold!r}"
            )
        self._threshold_index = _IMPACT_LEVELS.index(threshold)
        self._taint_triggers: set[str] = set(
            taint_triggers if taint_triggers is not None else ["external_unverified"]
        )
        self._verifications: list[VerificationRecord] = []

    def requires_external_review(
        self,
        plan_impact: str,
        taint_flags: list[str] | None = None,
    ) -> bool:
        """Return True when execution should be blocked pending review."""
        impact = plan_impact.strip().lower()
        if impact in _IMPACT_LEVELS:
            if _IMPACT_LEVELS.index(impact) >= self._threshold_index:
                return True
        if taint_flags:
            if self._taint_triggers & set(taint_flags):
                return True
        return False

    def record_verification(
        self,
        verifier_id: str,
        approved: bool,
        notes: str = "",
    ) -> dict[str, Any]:
        """Record an external verification decision and return its dict form."""
        from datetime import datetime, timezone

        record = VerificationRecord(
            verifier_id=verifier_id.strip(),
            approved=approved,
            notes=notes.strip(),
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )
        self._verifications.append(record)
        return {
            "verifier_id": record.verifier_id,
            "approved": record.approved,
            "notes": record.notes,
            "recorded_at": record.recorded_at,
        }

    @property
    def verifications(self) -> list[VerificationRecord]:
        """All recorded verification decisions (read-only snapshot)."""
        return list(self._verifications)
