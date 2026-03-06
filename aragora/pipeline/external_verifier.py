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
