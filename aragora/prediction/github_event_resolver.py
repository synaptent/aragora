"""Concrete GitHub-event resolution adapter for AGT-04 synthetic prediction markets.

Converts synthetic GitHub event payloads into claim resolutions.  The
adapter operates on *pre-fetched* event data; it never makes live API
calls, so tests run offline.

Feature flag: ``ARAGORA_PREDICTION_MARKETS_ENABLED`` (env var, default OFF).

Advances: issue #6065 (AGT-04), sub-deliverable 2 — GitHub event resolution.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from aragora.prediction.stakeable_claim import (
    QuestionType,
    ResolutionStatus,
    StakeableClaim,
)

_ENV_FLAG = "ARAGORA_PREDICTION_MARKETS_ENABLED"

logger = logging.getLogger(__name__)


def _flag_enabled() -> bool:
    return os.environ.get(_ENV_FLAG, "").lower() in {"1", "true", "yes", "on"}


def _require_enabled() -> None:
    if not _flag_enabled():
        raise RuntimeError(f"Prediction markets are disabled. Set {_ENV_FLAG}=1 to enable.")


@dataclass(frozen=True)
class GitHubEventPayload:
    """Minimal representation of a GitHub webhook event payload.

    Contains only the fields needed to resolve a StakeableClaim.  The
    full webhook payload is not stored; callers extract the relevant
    fields before constructing this object.

    Attributes:
        event_type: One of ``"pull_request"``, ``"issues"``, ``"check_run"``,
            ``"workflow_run"``.
        action: Event action string (e.g. ``"closed"``, ``"completed"``).
        target_ref: ``owner/repo#number`` or ``owner/repo@branch`` — must
            match the claim's ``target_ref`` (after normalization: whitespace
            stripped, owner/repo case-folded) for resolution to proceed.
        occurred_at: ISO-8601 UTC timestamp for when the event occurred.
        merged: For ``pull_request`` events: whether the PR was merged.
        conclusion: For ``check_run``/``workflow_run`` events: the final
            conclusion. ``"success"``, ``"neutral"`` and ``"skipped"`` resolve
            YES; ``"failure"``, ``"cancelled"``, ``"timed_out"`` and
            ``"startup_failure"`` resolve NO; any other value, including a
            missing one, leaves the claim unresolved.
        raw: Arbitrary additional fields preserved for traceability.  ``CI_PASS``
            events resolve only when ``raw["aggregate"] is True``, which means
            the caller has already reduced all required checks for ``target_ref``
            to one verdict; individual check_run/workflow_run payloads must wait.
            Issue-close payloads may carry ``state_reason`` at the top level or
            under the nested ``issue`` object.
    """

    event_type: str
    action: str
    target_ref: str
    occurred_at: str = ""
    merged: bool = False
    conclusion: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolutionResult:
    """Outcome of resolving a StakeableClaim against a GitHubEventPayload."""

    claim_id: str
    resolved: bool
    resolution_value: bool
    evidence: str


class GitHubEventResolver:
    """Resolves StakeableClaim instances from pre-fetched GitHub event payloads.

    Concrete implementation of the interface sketched in
    :class:`~aragora.prediction.stakeable_claim.GithubResolutionAdapterStub`.
    All resolution logic is deterministic and does not call the GitHub API.

    Usage::

        from aragora.prediction import GitHubEventResolver, GitHubEventPayload

        resolver = GitHubEventResolver()
        result = resolver.resolve_from_event(claim, payload)
        if result.resolved:
            store.resolve(claim.claim_id, result.resolution_value, result.evidence)
    """

    _EVENT_TYPES: dict[QuestionType, frozenset[str]] = {
        QuestionType.PR_MERGE: frozenset({"pull_request"}),
        QuestionType.ISSUE_CLOSE: frozenset({"issues"}),
        QuestionType.CI_PASS: frozenset({"check_run", "workflow_run"}),
    }

    # Settlement is irreversible, so only definitive conclusions settle a CI
    # claim. neutral/skipped pass, as for required status checks and in
    # aragora.markets.resolver. Unlike that pull-based resolver, NO is not
    # taken from action_required (a run awaiting approval can still run) or
    # stale; those and unknown or missing values leave the claim OPEN for a
    # later definitive event or the sweeper. startup_failure resolves NO here
    # (that resolver reads it as inconclusive): these claims settle only from
    # run_attempt=1, so a first run that never started can no longer pass and
    # would otherwise sit OPEN until the sweeper voids it.
    _CI_PASS_CONCLUSIONS: frozenset[str] = frozenset({"success", "neutral", "skipped"})
    _CI_FAIL_CONCLUSIONS: frozenset[str] = frozenset(
        {"failure", "cancelled", "timed_out", "startup_failure"}
    )

    @staticmethod
    def _normalize_target_ref(ref: str) -> str:
        """Canonicalize a target_ref for comparison.

        GitHub owner/repo names are case-insensitive, but issue/PR
        numbers and git refs (branch names) are matched verbatim.
        Produces the canonical ``owner/repo#N`` / ``owner/repo@ref``
        form: outer whitespace stripped, the owner/repo part case-folded,
        and the part after the first ``#``/``@`` separator preserved
        as-is (whitespace-stripped only).  A ref with no separator is
        treated as a bare owner/repo and case-folded whole.
        """
        ref = ref.strip()
        sep_idx = min((i for i in (ref.find("#"), ref.find("@")) if i != -1), default=-1)
        if sep_idx == -1:
            return ref.casefold()
        prefix = ref[:sep_idx].strip().casefold()
        suffix = ref[sep_idx + 1 :].strip()
        return f"{prefix}{ref[sep_idx]}{suffix}"

    def can_resolve(self, claim: StakeableClaim, event: GitHubEventPayload | None = None) -> bool:
        """Return True if *event* could update *claim*'s resolution state.

        ``target_ref`` on both the claim and the event is normalized via
        :meth:`_normalize_target_ref` before comparison, so a formatting
        or owner/repo-casing mismatch never silently expires a claim.
        """
        if claim.question_type not in self._EVENT_TYPES:
            return False
        if event is None:
            return True
        return event.event_type in self._EVENT_TYPES[
            claim.question_type
        ] and self._normalize_target_ref(event.target_ref) == self._normalize_target_ref(
            claim.target_ref
        )

    def resolve(self, claim: StakeableClaim) -> tuple[bool, str]:  # pragma: no cover
        """Fail closed for callers using the legacy adapter surface.

        This adapter requires caller-supplied event evidence. Use
        :meth:`resolve_from_event` for settlement.
        """
        raise NotImplementedError(
            "GitHubEventResolver.resolve requires a GitHubEventPayload; "
            "call resolve_from_event(claim, event) with pre-fetched event data."
        )

    def resolve_from_event(
        self, claim: StakeableClaim, event: GitHubEventPayload
    ) -> ResolutionResult:
        """Attempt to resolve *claim* from *event*.

        Returns a :class:`ResolutionResult`.  When the event is not
        applicable, ``resolved=False`` is returned instead of raising.

        Expiry is gated on *event time* (adjudicated design, PR #8519): an
        event that occurred at or before the claim's expiry qualifies even
        when it is processed after that expiry has passed on the wall clock
        (webhook lag, redelivery, replay).  Processing-time finality is
        enforced by the store sweeper's grace window, not here.  ``CI_PASS``
        claims also need an event that completed at or after the claim's
        ``created_at``; PR-merge and issue-close claims have no lower bound.

        Evidence arriving for a claim that is already settled
        (EXPIRED/RESOLVED_*) is emitted as an auditable side-output — a
        structured warning log — and never resurrects the claim.
        """
        _require_enabled()

        if claim.resolution_status != ResolutionStatus.OPEN:
            # Late-event side-output (adjudicated design, PR #8519):
            # auditable log, never raises, never resurrects a settled claim.
            logger.warning(
                "prediction.late_event: evidence arrived for settled claim "
                "claim_id=%s status=%s occurred_at=%s expiry=%s; "
                "side-output only, claim is not resurrected",
                claim.claim_id,
                claim.resolution_status.value,
                event.occurred_at or "<missing>",
                claim.expiry,
            )
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=f"Claim already {claim.resolution_status.value}; skipping.",
            )

        if not self.can_resolve(claim, event):
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=(
                    f"Event {event.event_type!r}/{event.action!r} does not match "
                    f"claim type {claim.question_type.value!r} or target {claim.target_ref!r}."
                ),
            )

        expiry_result = self._check_expiry(claim, event)
        if expiry_result is not None:
            return expiry_result

        if claim.question_type == QuestionType.PR_MERGE:
            return self._resolve_pr_merge(claim, event)
        if claim.question_type == QuestionType.ISSUE_CLOSE:
            return self._resolve_issue_close(claim, event)
        if claim.question_type == QuestionType.CI_PASS:
            return self._resolve_ci_pass(claim, event)

        return ResolutionResult(
            claim_id=claim.claim_id,
            resolved=False,
            resolution_value=False,
            evidence=f"Unsupported question type: {claim.question_type.value!r}.",
        )

    # ------------------------------------------------------------------
    # Per-type resolvers
    # ------------------------------------------------------------------

    def _check_expiry(
        self, claim: StakeableClaim, event: GitHubEventPayload
    ) -> ResolutionResult | None:
        """Event-time expiry gate (adjudicated design, PR #8519).

        Truth is determined by event time; finality by processing time.
        This gate never consults wall-clock ``now()``: an event with
        ``occurred_at <= expiry`` qualifies (returns None so per-type
        resolution proceeds) even when processed after the expiry has
        passed, because GitHub webhooks can lag or be redelivered.  An
        event with ``occurred_at > expiry`` is non-qualifying.  A missing
        or unparseable event timestamp fails closed (unresolved, with
        evidence).  Processing-time finality is bounded by the store
        sweeper's grace window (``expire_stale``), not here.

        ``CI_PASS`` claims also have a lower bound: an event that completed
        before ``claim.created_at`` is non-qualifying, because a branch-scoped
        CI claim binds no run identity and an earlier run would otherwise
        settle it.  A missing or unparseable ``created_at`` on a ``CI_PASS``
        claim fails closed.  PR-merge and issue-close claims keep pure
        occurrence semantics: a merge or close before the claim existed
        still qualifies.
        """
        expiry_dt = self._parse_datetime(claim.expiry)
        if expiry_dt is None:
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=f"Claim expiry {claim.expiry!r} is invalid; cannot resolve safely.",
            )
        event_dt = self._parse_event_time(event)
        if event_dt is None:
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence="Event timestamp is missing or invalid; cannot compare against claim expiry.",
            )
        if event_dt > expiry_dt:
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=(
                    f"Event at {event_dt.isoformat()} occurred after claim expiry "
                    f"{expiry_dt.isoformat()}; leaving unresolved for expiry handling."
                ),
            )
        if claim.question_type == QuestionType.CI_PASS:
            created_dt = self._parse_datetime(claim.created_at)
            if created_dt is None:
                return ResolutionResult(
                    claim_id=claim.claim_id,
                    resolved=False,
                    resolution_value=False,
                    evidence=(
                        f"Claim created_at {claim.created_at!r} is missing or invalid; "
                        "cannot verify the CI event completed after the claim was created."
                    ),
                )
            if event_dt < created_dt:
                return ResolutionResult(
                    claim_id=claim.claim_id,
                    resolved=False,
                    resolution_value=False,
                    evidence=(
                        f"CI event at {event_dt.isoformat()} completed before claim creation "
                        f"{created_dt.isoformat()}; a run that finished before the claim "
                        "existed cannot settle it."
                    ),
                )
        return None

    # Per-event-type allowlist of terminal timestamps (#8777): generic
    # created_at/updated_at can predate the terminal action (open time,
    # last touch), letting an after-expiry event be backdated into the
    # claim window. Only the timestamp of the terminal action itself may
    # stand in for an explicit occurred_at.
    _TERMINAL_TIME_KEYS: dict[str, tuple[str, ...]] = {
        "pull_request": ("merged_at", "closed_at"),
        "issues": ("closed_at",),
        "check_run": ("completed_at",),
        "workflow_run": ("completed_at",),
    }

    @staticmethod
    def _parse_event_time(event: GitHubEventPayload) -> datetime | None:
        raw_time: object = ""
        # Terminal-action timestamps are authoritative when present. This
        # prevents a generic, backdated occurred_at value from bypassing the
        # event-time expiry gate.
        for key in GitHubEventResolver._TERMINAL_TIME_KEYS.get(event.event_type, ()):
            candidate = event.raw.get(key)
            if candidate:
                raw_time = candidate
                break
        if not raw_time:
            raw_time = event.occurred_at or event.raw.get("occurred_at")
        if not isinstance(raw_time, str) or not raw_time:
            return None
        return GitHubEventResolver._parse_datetime(raw_time)

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    def _resolve_pr_merge(
        self, claim: StakeableClaim, event: GitHubEventPayload
    ) -> ResolutionResult:
        if event.action != "closed":
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=f"pull_request action {event.action!r} is not terminal; waiting.",
            )
        if not event.merged:
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=(
                    f"PR {claim.target_ref} closed without merge; not a terminal resolution for this claim. "
                    "Claim will expire unless the PR is reopened before expiry."
                ),
            )
        evidence = f"PR {claim.target_ref} merged (action={event.action!r}, merged=True)."
        return ResolutionResult(
            claim_id=claim.claim_id,
            resolved=True,
            resolution_value=True,
            evidence=evidence,
        )

    def _resolve_issue_close(
        self, claim: StakeableClaim, event: GitHubEventPayload
    ) -> ResolutionResult:
        if event.action != "closed":
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=f"issues action {event.action!r} is not terminal; waiting.",
            )
        state_reason = self._issue_state_reason(event)
        if state_reason == "not_planned":
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=(
                    f"Issue {claim.target_ref} closed with state_reason='not_planned'; "
                    "not counting as a positive resolution."
                ),
            )
        evidence = f"Issue {claim.target_ref} closed (action={event.action!r})."
        return ResolutionResult(
            claim_id=claim.claim_id,
            resolved=True,
            resolution_value=True,
            evidence=evidence,
        )

    def _resolve_ci_pass(
        self, claim: StakeableClaim, event: GitHubEventPayload
    ) -> ResolutionResult:
        if event.action != "completed":
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=(
                    f"check_run/workflow_run action {event.action!r} is not terminal; waiting."
                ),
            )
        if event.raw.get("aggregate") is not True:
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=(
                    f"{event.event_type} event for {claim.target_ref} is not marked with "
                    "aggregate=True for a required-check-set verdict; waiting for a "
                    "pre-aggregated CI event."
                ),
            )
        raw_attempt = event.raw.get("run_attempt")
        if raw_attempt is None:
            # Fail closed (#8777): an aggregate payload without attempt
            # metadata may describe a rerun; never assume first-run.
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=(
                    f"{event.event_type} event for {claim.target_ref} lacks run_attempt "
                    "metadata; cannot verify first run — failing closed."
                ),
            )
        # Strict int, matching the strict aggregate check: True, 1.9 and " 1 "
        # must not pass as a first run.
        if type(raw_attempt) is not int or raw_attempt != 1:
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=(
                    f"{event.event_type} event for {claim.target_ref} is run_attempt="
                    f"{raw_attempt!r}; first-run claims only resolve from run_attempt=1."
                ),
            )
        conclusion = event.conclusion if isinstance(event.conclusion, str) else None
        if conclusion in self._CI_PASS_CONCLUSIONS:
            value = True
        elif conclusion in self._CI_FAIL_CONCLUSIONS:
            value = False
        else:
            return ResolutionResult(
                claim_id=claim.claim_id,
                resolved=False,
                resolution_value=False,
                evidence=(
                    f"Aggregate CI {event.event_type} for {claim.target_ref} completed with "
                    f"conclusion={event.conclusion!r}, which is not a definitive pass/fail "
                    "verdict; waiting."
                ),
            )
        evidence = (
            f"Aggregate CI {event.event_type} for {claim.target_ref} completed with "
            f"conclusion={event.conclusion!r}; {'pass' if value else 'fail'}."
        )
        return ResolutionResult(
            claim_id=claim.claim_id,
            resolved=True,
            resolution_value=value,
            evidence=evidence,
        )

    @staticmethod
    def _issue_state_reason(event: GitHubEventPayload) -> str:
        state_reason = event.raw.get("state_reason")
        if state_reason is None and isinstance(event.raw.get("issue"), dict):
            state_reason = event.raw["issue"].get("state_reason")
        return str(state_reason or "").lower()
