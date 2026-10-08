#!/usr/bin/env python3
"""Pure decision core for unattended Tier 0-2 auto-merge on green quorum.

When a Tier 0-2 PR's merge-packet reaches ``status=satisfied`` the merge-quorum
gate already authorizes an admin squash ("Model quorum satisfied; Tier 0-2
settlement authorized" -- see ``.github/workflows/aragora-merge-quorum.yml``).
Today a human still types ``gh pr merge`` for those. This module decides --
purely, from already-fetched state -- whether to *execute* that
already-authorized merge without a human in the loop.

It deliberately makes NO new risk judgment. It re-checks, defense-in-depth, the
exact conditions the existing ``auto_merge_bucket_a`` admin-squash exception
requires (``scripts/auto_merge_bucket_a.py::_merge_packet_allows_blocked_state``)
plus the live check predicate from ``boss_drain_pass._proxy_authorized``
(merge-quorum green + every required check green + mergeable). Tier 3-4 PRs
(which require human risk settlement) are never eligible here -- they continue
to flow through ``scripts/settle_tier4_pr.py`` unchanged.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# The branch-protection required checks (mirrors boss_drain_pass._REQUIRED).
REQUIRED_CHECKS: frozenset[str] = frozenset(
    {"lint", "typecheck", "sdk-parity", "Generate & Validate", "TypeScript SDK Type Check"}
)

# The merge-quorum status check that encodes heterogeneous model-family consensus.
QUORUM_CHECK = "aragora-merge-quorum"

# Tiers 0-2 settle without human risk acceptance; 3-4 always need a human.
MAX_AUTO_MERGE_TIER = 2

# Merge states from which an authorized admin squash is safe. BLOCKED is allowed
# only because a satisfied merge-packet is what substitutes for the missing
# review approval under branch protection; every other non-CLEAN state (DIRTY,
# BEHIND, UNSTABLE, UNKNOWN) is refused.
_SAFE_MERGE_STATES = frozenset({"CLEAN", "BLOCKED"})

# Any check ending in one of these conclusions blocks the merge -- even a
# *non-required* one. The target population is ~always mergeStateStatus=BLOCKED
# (review approval substituted by the packet), so a failing non-required check
# would not show up as UNSTABLE; without this guard it would pass every other
# check and be --admin-merged. This also closes the REQUIRED_CHECKS drift hazard
# (a newly-required check failing is caught here regardless of the static list).
_FAILING_CHECK_STATES = frozenset(
    {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "STARTUP_FAILURE", "ACTION_REQUIRED"}
)


@dataclass(frozen=True)
class PRMergeContext:
    """Already-fetched state for one open PR. Pure input to the decision."""

    number: int
    head_sha: str
    packet_head_sha: str
    packet_pr_number: int
    tier: int | None
    packet_status: str
    packet_verdict: str
    requires_human_risk_settlement: bool
    unresolved_dissent: bool
    admin_squash_allowed: bool
    is_draft: bool
    mergeable: str
    merge_state_status: str
    check_states: dict[str, str]


@dataclass(frozen=True)
class MergeDecision:
    """Verdict for one PR: whether to merge unattended, and why not if not."""

    number: int
    head_sha: str
    should_merge: bool
    blockers: tuple[str, ...]


def decide_auto_merge(
    ctx: PRMergeContext,
    *,
    max_tier: int = MAX_AUTO_MERGE_TIER,
    required_checks: frozenset[str] = REQUIRED_CHECKS,
) -> MergeDecision:
    """Decide whether ``ctx`` may be merged unattended; collect *every* blocker.

    Returns ``should_merge=True`` only when none of the guards trip. All blockers
    are accumulated (not short-circuited) so an operator sees the full picture.
    """
    blockers: list[str] = []

    if ctx.is_draft:
        blockers.append("draft")

    if ctx.tier is None:
        blockers.append("tier unknown (merge-packet did not classify)")
    elif ctx.tier < 0 or ctx.tier > max_tier:
        blockers.append(
            f"tier {ctx.tier} outside auto-merge range 0-{max_tier} "
            "(Tier 3-4 need human settlement; <0 is invalid)"
        )

    if ctx.requires_human_risk_settlement:
        blockers.append("requires human risk settlement")

    if ctx.packet_status != "satisfied":
        blockers.append(f"merge-packet status not satisfied ({ctx.packet_status or 'unknown'})")

    if ctx.packet_verdict != "admin_squash_allowed":
        blockers.append(
            f"merge-packet verdict not admin_squash_allowed ({ctx.packet_verdict or 'unknown'})"
        )

    if not ctx.admin_squash_allowed:
        blockers.append("admin squash not allowed by merge-packet")

    if ctx.unresolved_dissent:
        blockers.append("unresolved dissent present")

    # The merge-packet is a separate subprocess from the gh view; if the head
    # moved between the two fetches we'd be deciding on mismatched data. Only
    # flag when the packet actually disclosed a head (else tier=None blocks).
    if ctx.packet_head_sha and ctx.packet_head_sha != ctx.head_sha:
        blockers.append(
            f"packet head mismatch (packet={ctx.packet_head_sha[:7]} view={ctx.head_sha[:7]})"
        )

    # Defense-in-depth: confirm the merge-packet entry actually belongs to this
    # PR. Absence or parse failure is not "unknown but okay" here: without a
    # concrete packet PR identity, the already-authorized packet cannot be bound
    # to the viewed PR, so unattended merge must fail closed.
    if ctx.packet_pr_number <= 0:
        blockers.append("packet PR number missing or invalid")
    elif ctx.packet_pr_number != ctx.number:
        blockers.append(f"packet PR mismatch (packet=#{ctx.packet_pr_number} view=#{ctx.number})")

    if ctx.mergeable != "MERGEABLE":
        blockers.append(f"not mergeable (mergeable={ctx.mergeable or 'unknown'})")

    if ctx.merge_state_status not in _SAFE_MERGE_STATES:
        blockers.append(
            f"merge state not safe (mergeStateStatus={ctx.merge_state_status or 'unknown'})"
        )

    quorum_state = ctx.check_states.get(QUORUM_CHECK)
    if quorum_state != "SUCCESS":
        blockers.append(f"merge-quorum not green ({QUORUM_CHECK}={quorum_state or 'absent'})")

    for name in sorted(required_checks):
        state = ctx.check_states.get(name)
        if state != "SUCCESS":
            blockers.append(f"required check not green: {name}={state or 'absent'}")

    failing = sorted(n for n, s in ctx.check_states.items() if s in _FAILING_CHECK_STATES)
    if failing:
        shown = ", ".join(failing[:3])
        blockers.append(
            f"failing checks present (incl. non-required): {shown}{', …' if len(failing) > 3 else ''}"
        )

    return MergeDecision(
        number=ctx.number,
        head_sha=ctx.head_sha,
        should_merge=not blockers,
        blockers=tuple(blockers),
    )


def first_error_line(stderr: str, stdout: str) -> str:
    """First non-empty line of a failed merge's output, or a safe default.

    Guards the whitespace-only case: ``"\\n".strip().splitlines()[0]`` would
    raise ``IndexError`` and crash a whole pass mid-merge. Prefer stderr.
    """
    text = (stderr or stdout or "").strip()
    if not text:
        return "merge failed"
    return text.splitlines()[0]


def _rollup_recency(item: dict[str, Any]) -> tuple[str, str]:
    """Sortable recency for one rollup row; ``("", "")`` when unknown.

    Timestamps are ISO-8601 UTC as returned by ``gh``, so lexical order is
    chronological order. Rows missing both stamps rank lowest and are treated
    as unrankable by the caller.

    ``startedAt`` is deliberately the primary key. A run that is still in
    flight has **no** ``completedAt``, so ordering on completion first would
    rank the current run below a stale row that has already finished — letting
    an old ``SUCCESS`` outrank a re-run that is still deciding, which is the
    very hazard this reduction exists to prevent. Check *runs* always carry a
    start time, and the most recently started one is the current run.

    Commit *statuses* (the ``context``/``state`` shape) carry neither stamp, so
    ``("", "")`` means **unrankable**, not "oldest" — see
    :func:`_rollup_is_rankable`.
    """
    return (str(item.get("startedAt") or ""), str(item.get("completedAt") or ""))


def _rollup_is_rankable(recency: tuple[str, str]) -> bool:
    """Whether a row carries enough information to be ordered against another.

    A row without a start time cannot be proven newer *or* older than anything.
    Treating it as merely "oldest" is what let a timestamped stale ``SUCCESS``
    outrank an untimestamped ``FAILURE``.

    Requires ``startedAt`` specifically, not "either stamp": ordering is
    start-primary, so a ``completedAt``-only row compares as ``("", cAt)`` and
    would rank below *every* start-bearing row regardless of the actual times —
    re-admitting the same stale-outranks-current hazard for that shape.
    """
    return bool(recency[0])


def _state_precedence(state: str) -> int:
    """How decision-relevant a collapsed state is; higher must never be masked.

    ``decide_auto_merge`` blocks on ``_FAILING_CHECK_STATES`` specifically, so
    collapsing a terminal ``FAILURE`` into a transient ``PENDING`` would silently
    disarm that guard even though both are non-success. Terminal failure
    therefore outranks transient non-success, which outranks success.
    """
    if state in _FAILING_CHECK_STATES:
        return 2
    if state != "SUCCESS":
        return 1
    return 0


def _reduce_rollup_states(rollup: Any) -> dict[str, str]:
    """Collapse a status-check rollup to one state per check name.

    Newest row per name wins, but **only between rows that can actually be
    ordered**. When two rows are not comparable — equal stamps, or *either* row
    carrying no stamps at all — **any non-success state wins over ``SUCCESS``**
    — not merely an explicitly failing one. ``PENDING``,
    ``QUEUED``, ``IN_PROGRESS`` and unknown/empty states are all "not yet
    proven green", and a success that cannot be shown to be the current row
    must never be what authorises an unattended merge.

    States are upper-cased so this reduction cannot be bypassed by casing,
    matching the normalisation the cheap prefilter applies.
    """
    # Three disjoint pools, so no row can be displaced out of the reduction by a
    # row it is not comparable to. Folding everything into one slot is what let a
    # veto vanish: an unrankable PENDING landing on a FAILURE incumbent matched
    # no branch and was dropped, after which a later SUCCESS outranked the
    # FAILURE and the name read green while the PENDING was still deciding.
    rankable: dict[str, tuple[tuple[str, str], str]] = {}
    veto: dict[str, str] = {}
    unrankable_success: set[str] = set()

    for item in rollup or []:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("context")
        if not name:
            continue
        name = str(name)
        state = str(item.get("conclusion") or item.get("state") or item.get("status") or "").upper()
        recency = _rollup_recency(item)

        if not _rollup_is_rankable(recency):
            if state == "SUCCESS":
                # Cannot be proven current, so it may not outrank anything; it only
                # decides a name that has no rankable row at all.
                unrankable_success.add(name)
            else:
                # Cannot be proven stale either — an unconditional veto, kept out
                # of the rankable pool so nothing can displace it. Among several,
                # keep the most decision-relevant rather than the first seen, so
                # the surviving representative does not depend on row order.
                if _state_precedence(state) > _state_precedence(veto.get(name, "SUCCESS")):
                    veto[name] = state
            continue

        previous = rankable.get(name)
        if previous is None:
            rankable[name] = (recency, state)
            continue
        previous_recency, previous_state = previous
        if recency > previous_recency:
            rankable[name] = (recency, state)
        elif recency == previous_recency and _state_precedence(state) > _state_precedence(
            previous_state
        ):
            # Same instant: neither row is provably the live one, so keep the more
            # decision-relevant state. Resolving by input order — or letting a
            # transient mask a terminal failure — is exactly the defect this
            # reduction exists to remove.
            rankable[name] = (recency, state)

    resolved = {name: state for name, (_, state) in rankable.items()}
    for name in unrankable_success:
        resolved.setdefault(name, "SUCCESS")
    # A veto blocks a success it cannot be proven staler than, but must not
    # *substitute* for a more decision-relevant state: replacing a rankable
    # terminal FAILURE with a transient PENDING would disarm the failing-checks
    # guard in `decide_auto_merge`, which keys on `_FAILING_CHECK_STATES`.
    for name, veto_state in veto.items():
        if _state_precedence(veto_state) > _state_precedence(resolved.get(name, "SUCCESS")):
            resolved[name] = veto_state
    return resolved


def context_from_gh(view: dict[str, Any], packet_entry: dict[str, Any] | None) -> PRMergeContext:
    """Build a :class:`PRMergeContext` from a ``gh pr view`` payload + packet entry.

    ``statusCheckRollup`` mixes two shapes: check *runs* expose ``name`` +
    ``conclusion``; commit *statuses* expose ``context`` + ``state``. Both are
    normalised into ``check_states`` so the decision core sees one flat map.
    A missing ``packet_entry`` leaves ``tier=None`` (which always blocks).

    Rollups routinely carry **several rows per check name** (a rerun, or a
    superseded draft-phase run, leaves its old row in place). Collapsing them
    by last-write-wins made the resulting state depend on GitHub's arbitrary
    row order, so a stale ``SUCCESS`` ordered after the current ``FAILURE``
    would read as green — including for ``aragora-merge-quorum`` itself, which
    directly authorises the merge. Rows are therefore reduced by **recency**
    (``completedAt`` then ``startedAt``), and when recency cannot be
    established the reduction is **fail-closed**: an unranked failing row wins
    over a success it cannot be proven newer than.
    """
    check_states = _reduce_rollup_states(view.get("statusCheckRollup") or [])

    packet = packet_entry or {}
    tier_raw = packet.get("tier")
    try:
        tier = int(tier_raw) if tier_raw is not None else None
    except (TypeError, ValueError):
        tier = None

    pr_raw = packet.get("pr_number")
    try:
        packet_pr_number = int(pr_raw) if pr_raw is not None else 0
    except (TypeError, ValueError):
        packet_pr_number = 0

    return PRMergeContext(
        number=int(view.get("number") or 0),
        head_sha=str(view.get("headRefOid") or ""),
        packet_head_sha=str(packet.get("head_sha") or ""),
        packet_pr_number=packet_pr_number,
        tier=tier,
        packet_status=str(packet.get("status") or ""),
        packet_verdict=str(packet.get("verdict") or ""),
        # Fail CLOSED on these safety flags: an absent/renamed key -> treat as
        # "settlement required" / "dissent present" so a schema drift blocks the
        # merge rather than silently permitting it.
        requires_human_risk_settlement=packet.get("requires_human_risk_settlement") is not False,
        unresolved_dissent=packet.get("unresolved_dissent") is not False,
        admin_squash_allowed=bool(packet.get("admin_squash_allowed")),
        is_draft=bool(view.get("isDraft")),
        mergeable=str(view.get("mergeable") or ""),
        merge_state_status=str(view.get("mergeStateStatus") or ""),
        check_states=check_states,
    )


def merge_eligible(
    contexts: list[PRMergeContext],
    *,
    max_tier: int = MAX_AUTO_MERGE_TIER,
) -> list[MergeDecision]:
    """Decide a batch of contexts (preserves order)."""
    return [decide_auto_merge(ctx, max_tier=max_tier) for ctx in contexts]


def apply_merges(
    decisions: list[MergeDecision],
    *,
    merge_fn: Callable[[int, str], tuple[bool, str]],
    max_merges: int | None = None,
    dry_run: bool = True,
) -> list[dict[str, Any]]:
    """Bounded apply loop. The merge side-effect is injected for testability.

    - Non-eligible decisions are reported as ``skip`` and never merged.
    - ``dry_run`` (default) calls ``merge_fn`` for nothing; it reports
      ``would-merge`` and still honours ``max_merges`` so the plan is accurate.
    - A failed merge does NOT consume a ``max_merges`` slot.
    """
    results: list[dict[str, Any]] = []
    merged = 0
    for decision in decisions:
        record: dict[str, Any] = {"pr": decision.number, "head": decision.head_sha}
        if not decision.should_merge:
            record["action"] = "skip"
            record["blockers"] = list(decision.blockers)
            results.append(record)
            continue
        if max_merges is not None and merged >= max_merges:
            record["action"] = "deferred (max-merges reached)"
            results.append(record)
            continue
        if dry_run:
            record["action"] = "would-merge"
            results.append(record)
            merged += 1
            continue
        ok, detail = merge_fn(decision.number, decision.head_sha)
        record["action"] = "merged" if ok else "merge-failed"
        record["detail"] = detail
        results.append(record)
        if ok:
            merged += 1
    return results
