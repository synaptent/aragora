"""Dispatch adapters — how a mission feature becomes a merged, gated change.

The orchestrator (``orchestrator.py``) is gate-agnostic: it hands a ``Feature`` to
a ``Dispatch`` callable and triages the returned ``Handoff``. This module supplies
the real one: :class:`BossLoopDispatch`, which drives Aragora's merge-quorum gate
with every rule we learned the hard way operating Factory for ~13 days —

  * **idempotent**: an already-merged branch is *success*, not an error (a retry
    after a crash must converge, never double-merge);
  * **foreign-commit guard** (the #8616 lesson): if any non-mission commit landed
    on the branch, do NOT collect evidence — return blocked for re-derive;
  * **head-bound merge, never ``--admin``**;
  * **Tier-3 surfaces escalate to the operator** rather than auto-settling.

The live wiring (``swarm/boss_loop`` worker spawn, ``aragora/worktree`` isolation,
``swarm/quorum_evidence`` + ``cli/commands/review_queue`` gate) plugs in behind the
small :class:`FleetGate` protocol, so this logic is fully testable without touching
live ``main``. ``LiveBossLoopGate`` (the thin real binding) is the only remaining
seam — deliberately a separate, reviewable step.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .handoff import Handoff
from .reconcile import write_operator_receipt
from .state import PARK_KIND_MATERIALIZATION, PARK_KIND_MISSING_BRANCH, Feature

# git rev-parse --verify failure signatures: the ref genuinely does not
# resolve (vs a transient runner failure such as a timeout or lock).
_UNKNOWN_REV_MARKERS = (
    "unknown revision",
    "bad revision",
    "needed a single revision",
    "not a valid ref",
)


def _is_unknown_revision(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _UNKNOWN_REV_MARKERS)


logger = logging.getLogger(__name__)


@dataclass
class GateVerdict:
    """Outcome of collecting heterogeneous-model quorum evidence on a head."""

    satisfied: bool
    tier: int = 0
    dissent: list[str] = field(default_factory=list)


class FleetGate(Protocol):
    """The merge-gate surface a dispatch needs. Live impl wraps review_queue."""

    def branch_for(self, feature: Feature) -> str: ...

    def already_merged(self, branch: str) -> bool: ...

    def head_of(self, branch: str) -> str: ...

    def foreign_commits(
        self, branch: str, base: str, allowed_prefixes: tuple[str, ...]
    ) -> list[str]: ...

    def tier_of(self, feature: Feature) -> int: ...  # cheap classification, before evidence

    def collect_evidence(self, branch: str, head: str) -> GateVerdict: ...

    def merge_head_bound(self, branch: str, head: str) -> bool: ...


class BossLoopDispatch:
    """Turn a feature into a gated, head-bound merge — or a precise handoff.

    Operator-settlement boundary (see the Tier-3 bright line, 2026-06-25): pure
    structural moves auto-settle on a clean quorum; Tier >= ``operator_tier``
    surfaces (server/persistence/security) are escalated, never auto-settled.
    """

    def __init__(
        self,
        gate: FleetGate,
        *,
        base: str = "origin/main",
        allowed_prefixes: tuple[str, ...] = ("structex/", "mission/"),
        operator_tier: int = 3,
        receipt_dir: str | Path | None = None,
    ) -> None:
        self.gate = gate
        self.base = base
        self.allowed_prefixes = allowed_prefixes
        self.operator_tier = operator_tier
        self.receipt_dir = Path(receipt_dir) if receipt_dir is not None else None

    def __call__(self, feature: Feature) -> Handoff:
        if _missing_live_branch(feature):
            # Retryable park, NOT terminal (#8758 design decision): a missing
            # branch means "not ready yet", never "dead" — the reconciler
            # releases the park once a live branch appears (intake bridge /
            # worker materialization / operator). Because this check runs on
            # every dispatch, it is also the fail-closed claim-time
            # re-verification: a parked feature promoted on stale state
            # re-parks here instead of reaching the merge gate branchless.
            return Handoff(
                success=False,
                parked=True,
                parked_kind=PARK_KIND_MISSING_BRANCH,
                blocked_reason=(
                    "auto-drain requires feature metadata.branch before live dispatch; "
                    "parked (retryable) until intake/worker materializes a branch"
                ),
                discovered=[
                    f"feature {feature.id} has no metadata.branch; parked non-terminally for intake"
                ],
            )

        branch = self.gate.branch_for(feature)

        # Idempotency: a crash-retried feature whose PR already merged is done.
        if self.gate.already_merged(branch):
            logger.info("feature %s already merged (idempotent success)", feature.id)
            return Handoff(success=True, discovered=["branch already merged on a prior attempt"])

        try:
            head = self.gate.head_of(branch)
        except RuntimeError as exc:
            # The runner raises RuntimeError for EVERY nonzero exit and for
            # timeouts (#8766 claude P2): only a genuine unknown-revision
            # failure means the recorded ref is dead. Anything else is a
            # transient git failure and parks as MATERIALIZATION — the paced,
            # retry-bounded flavor — so one git outage cannot masquerade as a
            # dead branch and burn the missing-branch budget.
            if not _is_unknown_revision(exc):
                return Handoff(
                    success=False,
                    parked=True,
                    parked_kind=PARK_KIND_MATERIALIZATION,
                    blocked_reason=(
                        f"transient git failure resolving metadata.branch {branch!r}; "
                        f"parked (retryable) for a paced retry: {exc}"
                    ),
                    discovered=[
                        f"feature {feature.id}: transient git failure on head_of; paced retry"
                    ],
                )
            return _park_missing_live_branch(
                feature,
                (
                    f"auto-drain requires live git ref for metadata.branch {branch!r}; "
                    f"parked (retryable) until intake/worker materializes a branch: {exc}"
                ),
            )

        # Foreign-commit guard (#8616): never collect evidence on a contaminated
        # head — park for re-derive instead of merging someone else's work.
        foreign = self.gate.foreign_commits(branch, self.base, self.allowed_prefixes)
        if foreign:
            if _only_missing_path_allowlist(foreign):
                return Handoff(
                    success=False,
                    blocked_reason=(
                        "mission metadata missing paths; add metadata.paths before auto-drain "
                        f"so the foreign-commit guard can verify {branch}"
                    ),
                    discovered=[f"mission path allowlist missing on {branch}"],
                )
            # Terminal: a contaminated branch needs a re-derive, not a re-dispatch.
            return Handoff(
                success=False,
                terminal=True,
                blocked_reason=f"contaminated by foreign commits {foreign}; re-derive clean off {self.base} before evidence",
                discovered=[f"foreign-commit guard tripped on {branch}"],
            )

        # Tier-3+ surfaces are an operator fork — classify first and escalate
        # before spending an (expensive) quorum on something that can't auto-settle.
        # Bind once: tier_of may be a non-deterministic (LLM/heuristic) classifier.
        tier = self.gate.tier_of(feature)
        if tier >= self.operator_tier:
            reason = f"tier-{tier} surface requires operator settlement (head {head})"
            receipt = self._operator_receipt(
                feature,
                blocker=reason,
                evidence=[
                    f"branch {branch}",
                    f"head {head}",
                    f"operator_tier {self.operator_tier}",
                ],
                next_action="Ask the operator for exact-head settlement approval.",
            )
            discovered = [f"operator receipt: {receipt}"] if receipt else []
            return Handoff(
                success=False,
                terminal=True,
                blocked_reason=reason,
                discovered=discovered,
            )

        verdict = self.gate.collect_evidence(branch, head)

        # Defense in depth: if evidence reveals a higher tier than the cheap
        # pre-classification, still escalate — never auto-merge past Tier-3.
        if verdict.tier >= self.operator_tier:
            reason = (
                f"evidence reclassified to tier-{verdict.tier}: "
                f"operator settlement required (head {head})"
            )
            receipt = self._operator_receipt(
                feature,
                blocker=reason,
                evidence=[
                    f"branch {branch}",
                    f"head {head}",
                    *verdict.dissent,
                ],
                next_action="Ask the operator for exact-head settlement approval.",
            )
            discovered = [f"operator receipt: {receipt}"] if receipt else []
            return Handoff(
                success=False,
                terminal=True,
                blocked_reason=reason,
                discovered=discovered,
            )

        if not verdict.satisfied:
            # Transient: dissent may resolve on re-collection at a later head.
            return Handoff(
                success=False,
                blocked_reason=f"quorum not satisfied: {verdict.dissent or 'incomplete'}",
            )

        current_head = self.gate.head_of(branch)
        if current_head != head:
            return Handoff(
                success=False,
                blocked_reason=f"head moved from {head} to {current_head} after evidence",
            )
        foreign = self.gate.foreign_commits(branch, self.base, self.allowed_prefixes)
        if foreign:
            if _only_missing_path_allowlist(foreign):
                return Handoff(
                    success=False,
                    blocked_reason=(
                        "mission metadata missing paths after evidence; add metadata.paths "
                        f"before retrying auto-drain for {branch}"
                    ),
                    discovered=[f"mission path allowlist missing on {branch} before merge"],
                )
            return Handoff(
                success=False,
                terminal=True,
                blocked_reason=f"contaminated after evidence by foreign commits {foreign}; re-derive clean off {self.base}",
                discovered=[f"foreign-commit guard tripped on {branch} before merge"],
            )

        if self.gate.merge_head_bound(branch, head):
            logger.info("feature %s merged head-bound at %s", feature.id, head)
            return Handoff(success=True, session_id=head)

        # Transient: head moved under us; a retry re-evaluates the new head.
        return Handoff(
            success=False, blocked_reason=f"head-bound merge of {head} did not land (head moved?)"
        )

    def _operator_receipt(
        self,
        feature: Feature,
        *,
        blocker: str,
        evidence: list[str],
        next_action: str,
    ) -> str | None:
        if self.receipt_dir is None:
            return None
        try:
            path = write_operator_receipt(
                self.receipt_dir,
                feature_id=feature.id,
                blocker=blocker,
                evidence=evidence,
                next_action=next_action,
                human_required=True,
            )
        except OSError as exc:
            logger.error("failed to write operator receipt for %s: %s", feature.id, exc)
            return None
        return str(path)


def _only_missing_path_allowlist(foreign: list[str]) -> bool:
    return bool(foreign) and all(
        item.endswith("(missing mission path allowlist)") for item in foreign
    )


def _missing_live_branch(feature: Feature) -> bool:
    branch = feature.metadata.get("branch")
    return not (isinstance(branch, str) and branch.strip())


def _park_missing_live_branch(feature: Feature, reason: str) -> Handoff:
    return Handoff(
        success=False,
        parked=True,
        parked_kind=PARK_KIND_MISSING_BRANCH,
        blocked_reason=reason,
        discovered=[f"feature {feature.id} has no live metadata.branch ref; parked non-terminally"],
    )
