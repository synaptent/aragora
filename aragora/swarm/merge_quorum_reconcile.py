"""Pure decision logic for merge-quorum reconciliation and settlement status.

Background
----------
The enforcing merge gate (``aragora-merge-quorum``) only re-evaluates on
``pull_request`` synchronize-type events, never on ``issue_comment``. The
heterogeneous model-review evidence, however, is posted as PR comments *after*
those events. The result is a recurring stall: the check computes once
(pre-evidence) and concludes FAILURE, and never re-reads the now-complete
evidence, so a PR sits red even though its quorum is satisfied. The safe,
deterministic recovery is to re-run that read-only evaluation once a strictly
newer *countable* evidence comment exists for the current head.

This module is **pure** (no I/O): it takes already-fetched, already-linted
records and returns decisions/summaries. The GitHub I/O lives in the thin CLIs
``scripts/reconcile_merge_quorum.py`` (A1) and ``scripts/settle_status.py``
(A2), mirroring the :mod:`aragora.swarm.unstick` pattern so this logic stays
unit-testable without network access.

Safety invariants (enforced here):

* Never recommend a re-run when the gate already concluded SUCCESS.
* Never recommend a re-run when the latest run belongs to a stale head.
* Never recommend a re-run unless a strictly newer countable comment exists.
* Never recommend a re-run when a *real* required-check failure is present
  (that is a genuine red, not a stale-quorum artifact).
* Respect a per-head cooldown and a per-head max-rerun budget.

Re-running a read-only evaluation can never pass a genuinely failing PR; it only
lets the gate re-read evidence that is already public.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Final

# Read-only *diagnostic* mapping used only to render the "next action" hint; it
# never gates a merge. Tuple = (required_model_signals, requires_dogfood,
# requires_human_settlement). This is the strict-regime (default-OFF) projection of
# the canonical QuorumPolicy (aragora.swarm.quorum_evidence.tier_quorum_rule). It is
# a literal (not a module-load derivation) only because quorum_evidence imports this
# module transitively via merge_quorum_io — a runtime derivation would be a circular
# import. Drift from the policy is prevented by test_tiered_merge_gate_quorum_policy::
# test_reconcile_diagnostic_matches_policy, which asserts equality against
# tier_quorum_rule(tier, tiered_gate=False) (claude/Codex #8507 single-source).
# NOTE: summarize_settlement sources the LIVE signal *count* (and the western-frontier
# constraint) from the flag-aware tier_quorum_rule so the diagnostic mirrors the gate
# under ARAGORA_ENABLE_TIERED_MERGE_GATE; this table supplies only the flag-independent
# dogfood/human-settlement requirements and serves as the strict-regime pin.
TIER_REQUIREMENTS: Final[dict[int, tuple[int, bool, bool]]] = {
    0: (1, False, False),
    1: (2, True, False),
    2: (2, True, False),
    3: (2, True, True),
    4: (2, True, True),
}

_SUCCESS: Final[str] = "SUCCESS"
# Non-terminal states that may arrive via the check-run ``state`` fallback; the
# gate has not concluded, so the right hint is "wait", not "re-run".
_NON_FINAL_STATES: Final[frozenset[str]] = frozenset(
    {"IN_PROGRESS", "QUEUED", "PENDING", "WAITING", "REQUESTED", "EXPECTED"}
)


def parse_iso8601(value: str | None) -> datetime | None:
    """Parse a GitHub ISO-8601 timestamp to an aware UTC datetime, or ``None``.

    Accepts the trailing ``Z`` form GitHub returns. Returns ``None`` for empty
    or unparseable input so callers can fail safe (treat as "unknown").
    """
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class EvidenceComment:
    """A PR comment already evaluated by ``review-queue evidence-lint``.

    Attributes:
        created_at: ISO-8601 creation timestamp of the comment.
        would_count: ``evidence-lint``'s ``would_count`` verdict.
        reviewer_id: The single counted reviewer family (e.g. ``"claude"``),
            or ``""`` when the comment does not count.
        is_dogfood: Whether the comment contributes adversarial-dogfood
            evidence (``evidence-lint`` returned non-empty ``dogfood_evidence``).
        reviewer_signals: Distinct model families carried by GENUINE
            model-review signal items (``evidence-lint``'s ``reviewer_signals``
            list, never ``dogfood_evidence``). ``reviewer_id`` can be
            dogfood-attributed, so it must not feed requirements that the live
            gate derives from review signals only (the western-frontier check).
            ``None`` means provenance is unknown (legacy/hand-built records):
            consumers fall back to ``reviewer_id`` so pre-provenance callers
            keep their behavior; ``()`` affirmatively means "no genuine
            reviewer signal" (e.g. a dogfood-only comment).
    """

    created_at: str
    would_count: bool
    reviewer_id: str = ""
    is_dogfood: bool = False
    reviewer_signals: tuple[str, ...] | None = None


@dataclass(frozen=True)
class QuorumRun:
    """The latest ``aragora-merge-quorum`` workflow run for a PR head."""

    run_id: int
    created_at: str
    conclusion: str
    head_sha: str


@dataclass(frozen=True)
class RerunDecision:
    """Whether A1 should re-run the gate for a PR.

    ``needs_adjudication`` is set when the per-PR round budget is exhausted:
    the correct next step is a net-value adjudication decision (merge-as-is /
    one bounded round / close / restructure), not another rerun. Callers use
    this structured flag instead of sniffing the reason string.
    """

    pr_number: int
    should_rerun: bool
    reason: str
    run_id: int | None = None
    next_prompt: str = ""
    needs_adjudication: bool = False


@dataclass(frozen=True)
class PacketClassification:
    """Semantic merge-packet classification from CI or a local packet."""

    source: str
    pr_number: int
    head_sha: str
    tier: int | None
    status: str
    verdict: str
    requires_human_risk_settlement: bool


@dataclass(frozen=True)
class SettlementStatus:
    """A2's read-only view of where a PR's settlement actually stands."""

    pr_number: int
    head_sha: str
    tier: int | None
    counted_reviewer_ids: list[str] = field(default_factory=list)
    has_dogfood: bool = False
    human_settlement_present: bool = False
    quorum_conclusion: str = ""
    next_action: str = ""

    @property
    def signal_count(self) -> int:
        return len(self.counted_reviewer_ids)


def _newest_countable_created_at(comments: list[EvidenceComment]) -> datetime | None:
    newest: datetime | None = None
    for comment in comments:
        if not comment.would_count:
            continue
        created = parse_iso8601(comment.created_at)
        if created is None:
            continue
        if newest is None or created > newest:
            newest = created
    return newest


def counted_reviewer_ids(comments: list[EvidenceComment]) -> list[str]:
    """Distinct counted reviewer families across countable comments."""
    ids: set[str] = set()
    for comment in comments:
        if comment.would_count and comment.reviewer_id:
            ids.add(comment.reviewer_id)
    return sorted(ids)


def counted_reviewer_signal_families(comments: list[EvidenceComment]) -> set[str]:
    """Distinct counted families backed by GENUINE model-review signals.

    Mirrors the live gate's signal-only derivation (review_queue computes
    ``has_western_frontier_signal`` from ``reviewer_signals`` with an EMPTY
    dogfood list), so a dogfood-only counted identity never satisfies a
    review-signal requirement. Provenance-unaware records
    (``reviewer_signals is None`` — legacy or hand-built) fall back to
    ``reviewer_id`` so existing callers keep their behavior; an explicit empty
    tuple affirmatively means "no genuine reviewer signal".
    """
    families: set[str] = set()
    for comment in comments:
        if not comment.would_count:
            continue
        if comment.reviewer_signals is None:
            if comment.reviewer_id:
                families.add(comment.reviewer_id)
            continue
        families.update(family for family in comment.reviewer_signals if family)
    return families


def plan_rerun(
    *,
    pr_number: int,
    run: QuorumRun | None,
    comments: list[EvidenceComment],
    current_head_sha: str,
    now: datetime,
    last_rerun_at: datetime | None = None,
    reruns_this_head: int = 0,
    cooldown_seconds: int = 600,
    max_reruns_per_head: int = 3,
    has_real_required_failure: bool = False,
    pr_rounds_consumed: int = 0,
    pr_round_budget: int = 0,
) -> RerunDecision:
    """Decide whether to re-run the gate so it re-reads current-head evidence.

    All checks fail safe (a ``False`` decision) when an input is missing or
    ambiguous. See module docstring for the safety invariants.

    ``pr_round_budget`` is the per-PR convergence budget that survives head drift
    (``max_reruns_per_head`` resets every new head, so it never bounds a churning
    PR — see :mod:`aragora.swarm.convergence_ledger`). When ``pr_rounds_consumed``
    reaches it, this stops re-running and signals that the PR needs a *decision*
    (net-value adjudication), not another round. ``pr_round_budget=0`` disables the
    check, so existing callers are unaffected until they opt in.
    """

    def decide(should: bool, reason: str) -> RerunDecision:
        return RerunDecision(
            pr_number=pr_number,
            should_rerun=should,
            reason=reason,
            run_id=run.run_id if run else None,
        )

    if run is None:
        return decide(False, "no aragora-merge-quorum run found for the current head")
    if run.conclusion.upper() == _SUCCESS:
        return decide(False, "quorum check already SUCCESS")
    if run.head_sha and current_head_sha and run.head_sha != current_head_sha:
        return decide(False, "latest run belongs to a stale head; await current-head run")
    if has_real_required_failure:
        return decide(False, "a real required-check failure is present; not a stale-quorum case")

    newest = _newest_countable_created_at(comments)
    if newest is None:
        return decide(False, "no countable evidence present yet")

    run_created = parse_iso8601(run.created_at)
    if run_created is None:
        return decide(False, "quorum run timestamp unparseable")
    if not (run_created < newest):
        return decide(False, "quorum run already postdates the newest countable evidence")

    if pr_round_budget and pr_rounds_consumed >= pr_round_budget:
        return RerunDecision(
            pr_number=pr_number,
            should_rerun=False,
            reason=(
                f"PR round budget exhausted ({pr_rounds_consumed}/{pr_round_budget} repair "
                "rounds across head drift); net-value adjudication required, not another rerun"
            ),
            run_id=run.run_id if run else None,
            needs_adjudication=True,
        )
    if reruns_this_head >= max_reruns_per_head:
        return decide(False, f"max reruns reached for this head ({max_reruns_per_head})")
    if last_rerun_at is not None:
        elapsed = (now - last_rerun_at).total_seconds()
        if elapsed < cooldown_seconds:
            return decide(False, f"within cooldown ({int(elapsed)}s < {cooldown_seconds}s)")

    return decide(
        True,
        "stale quorum check predates newer countable evidence; safe read-only re-run",
    )


_CI_PACKET_RE: Final[re.Pattern[str]] = re.compile(
    r"PR\s+#(?P<pr>\d+)\s+\|\s+Tier\s+(?P<tier>\d+|None|null)\s+\|\s+"
    r"status=(?P<status>[^\s|]+)\s+\|\s+verdict=(?P<verdict>[^\s|]+)"
)


def _requires_human_from_ci_packet(*, tier: int | None, status: str, verdict: str) -> bool:
    text = f"{status} {verdict}".lower()
    return tier in {3, 4} or "human_preapproval" in text or "human_risk" in text


def parse_ci_packet_classification(
    log_text: str, *, pr_number: int, head_sha: str
) -> PacketClassification | None:
    """Parse the CI merge-packet line emitted by ``aragora-merge-quorum``."""
    for match in _CI_PACKET_RE.finditer(log_text):
        parsed_pr = int(match.group("pr"))
        if parsed_pr != pr_number:
            continue
        raw_tier = match.group("tier")
        tier = None if raw_tier.lower() in {"none", "null"} else int(raw_tier)
        status = match.group("status")
        verdict = match.group("verdict")
        return PacketClassification(
            source="ci",
            pr_number=parsed_pr,
            head_sha=head_sha,
            tier=tier,
            status=status,
            verdict=verdict,
            requires_human_risk_settlement=_requires_human_from_ci_packet(
                tier=tier, status=status, verdict=verdict
            ),
        )
    return None


def packet_classification_summary(packet: PacketClassification | None) -> str:
    """Human-readable packet classification for logs and prompts."""
    if packet is None:
        return "unavailable"
    human = "human-risk" if packet.requires_human_risk_settlement else "no-human-risk"
    return (
        f"{packet.source}: head={packet.head_sha or 'unknown'} "
        f"tier={packet.tier} status={packet.status} verdict={packet.verdict} {human}"
    )


def packet_classifications_diverge(
    ci_packet: PacketClassification | None,
    local_packet: PacketClassification | None,
) -> bool:
    """Return true when CI and local packets disagree on semantic risk tier."""
    if ci_packet is None or local_packet is None:
        return False
    if ci_packet.pr_number != local_packet.pr_number:
        return False
    if ci_packet.head_sha and local_packet.head_sha and ci_packet.head_sha != local_packet.head_sha:
        return False
    return (
        ci_packet.tier != local_packet.tier
        or ci_packet.requires_human_risk_settlement != local_packet.requires_human_risk_settlement
    )


def classification_divergence_prompt(
    *,
    pr_number: int,
    head_sha: str,
    ci_packet: PacketClassification,
    local_packet: PacketClassification,
) -> str:
    """Build the bounded follow-up prompt when a rerun would mask policy drift."""
    return "\n".join(
        [
            "Start from live repo truth. Do not trust prior transcript state. "
            "Duplicate-owner detection first. Check Aragora operator-steering mailbox before lane work.",
            "",
            f"Goal: diagnose and repair only the aragora-merge-quorum classification divergence for PR #{pr_number} at exact head {head_sha}. Do not merge, rerun CI/quorum, mark ready, label, cleanup, mutate publisher/outbox state, touch automations, raw transcripts, unrelated PRs, unrelated worktrees, or unrelated dirty files.",
            "",
            "Run root status, fetch origin/main, publisher freshness, active-session conflicts, identify_lane_owner/read_operator_steering for the PR and branch, gh pr view/checks, full check rollup, branch-protection required contexts, latest aragora-merge-quorum log, and a clean current-main/local review-queue merge-packet for the exact PR/head.",
            "",
            "Proceed only if the live blocker remains CI/local policy classification divergence:",
            f"- CI packet: {packet_classification_summary(ci_packet)}",
            f"- Local packet: {packet_classification_summary(local_packet)}",
            "",
            "If clean, use a clean isolated worktree and repair only the smallest policy/classification surface needed so aragora-merge-quorum and merge-packet classify the exact-head PR consistently from workflow context. Preserve the intended policy behavior and do not broaden risk policy.",
            "",
            "Validate focused policy classification tests, the exact PR merge-packet where practical, git diff --check, automation_pr_preflight if applicable, and pre-push hooks if pushing. Push only the repair branch if clean. Do not merge.",
        ]
    )


def guard_rerun_classification_divergence(
    decision: RerunDecision,
    *,
    ci_packet: PacketClassification | None,
    local_packet: PacketClassification | None,
    head_sha: str,
) -> RerunDecision:
    """Suppress a stale-quorum rerun when CI and local packets disagree."""
    if not decision.should_rerun or not packet_classifications_diverge(ci_packet, local_packet):
        return decision
    if ci_packet is None or local_packet is None:
        return decision
    return RerunDecision(
        pr_number=decision.pr_number,
        should_rerun=False,
        reason=(
            "classification_divergence: CI merge-quorum packet differs from "
            f"clean local merge-packet; {packet_classification_summary(ci_packet)}; "
            f"{packet_classification_summary(local_packet)}"
        ),
        run_id=decision.run_id,
        next_prompt=classification_divergence_prompt(
            pr_number=decision.pr_number,
            head_sha=head_sha,
            ci_packet=ci_packet,
            local_packet=local_packet,
        ),
    )


def summarize_settlement(
    *,
    pr_number: int,
    head_sha: str,
    tier: int | None,
    comments: list[EvidenceComment],
    human_settlement_present: bool,
    quorum_conclusion: str,
) -> SettlementStatus:
    """Compute the live settlement state directly from linted comments.

    Immune to the ``merge-packet`` short-circuit (which hides the quorum detail
    whenever the gate check is failing), because it counts evidence from the
    comment lint results rather than from the packet.
    """
    ids = counted_reviewer_ids(comments)
    has_dogfood = any(c.would_count and c.is_dogfood for c in comments)

    # requires_dogfood / requires_human are tier-derived and flag-independent (dogfood for
    # Tier 1+, human settlement for Tier 3+); only the signal *count* and the
    # western-frontier constraint change with the tiered merge gate, so source those two
    # from the strict TIER_REQUIREMENTS projection and the signal bar from the flag-aware
    # rule below.
    _, requires_dogfood, requires_human = TIER_REQUIREMENTS.get(
        tier if tier is not None else -1, (2, True, True)
    )
    # Mirror the LIVE merge gate exactly: read the tiered-gate flag via the same accessor
    # the gate uses (tiered_merge_gate_enabled) rather than hardcoding the strict regime, so
    # when the flag is ON this diagnostic reports the relaxed Tier 1-2 bar (one
    # western-frontier signal) and when OFF the strict bar — it never tells an operator a
    # different requirement than what CI would actually enforce. Deriving from the same
    # tier_quorum_rule means it can only ever match or be stricter than the gate, so it can
    # never falsely green-light. Function-level import avoids a circular import
    # (quorum_evidence imports this module via merge_quorum_io).
    from aragora.swarm.quorum_evidence import (
        WESTERN_FAMILIES,
        WESTERN_FRONTIER_FAMILIES,
        tier_quorum_rule,
        tiered_merge_gate_enabled,
    )

    rule = tier_quorum_rule(tier, tiered_gate=tiered_merge_gate_enabled())
    required_signals = rule.required_signals
    # Jurisdiction-eligible count: drops Chinese-routed families at Tier 3-4. This
    # is what actually drives the gate's quorum decision, not the raw id count.
    counted = rule.counted_families(ids)
    advisory_only = bool(set(ids) - counted)
    # Tiered gate ON: a Tier 1-2 PR settles on ONE western-frontier signal (claude/openai),
    # so a lone non-frontier signal must not be reported as sufficient (mirrors the gate's
    # western_frontier_satisfied check). Like the gate, the frontier requirement is
    # derived from GENUINE model-review signals only (review_queue computes
    # has_western_frontier_signal from reviewer_signals with an EMPTY dogfood list):
    # a dogfood-only counted identity satisfies the dogfood leg below but must not
    # advance the western-frontier advice (VAL-P4A-024).
    counted_signal_families = rule.counted_families(counted_reviewer_signal_families(comments))
    needs_western_frontier = rule.requires_western_frontier and not (
        counted_signal_families & WESTERN_FRONTIER_FAMILIES
    )
    needs_western = rule.requires_at_least_one_western and not (counted & WESTERN_FAMILIES)

    if quorum_conclusion.upper() == _SUCCESS:
        next_action = "none — quorum check is green; PR is ready to merge"
    elif needs_western_frontier:
        next_action = (
            "collect one western-frontier model signal (claude/openai) on the current "
            "head; under the tiered merge gate a Tier 1-2 PR settles on a single "
            "western-frontier signal, which the counted families do not yet include"
        )
    elif len(counted) < required_signals:
        missing = required_signals - len(counted)
        if advisory_only:
            next_action = (
                f"collect {missing} more distinct Western model signal(s) on the current "
                "head; Chinese-routed families are advisory-only at this tier and do not "
                "count toward the quorum"
            )
        else:
            next_action = f"collect {missing} more distinct model signal(s) on the current head"
    elif needs_western:
        next_action = (
            "collect at least one Western model signal on the current head; the counted "
            "families are advisory-only and do not satisfy the Tier 2 Western requirement"
        )
    elif requires_dogfood and not has_dogfood:
        next_action = "post adversarial-dogfood evidence on the current head"
    elif requires_human and not human_settlement_present:
        next_action = (
            "operator: record human settlement for the current head "
            "(scripts/settle_tier4_pr.py --apply)"
        )
    elif not quorum_conclusion or quorum_conclusion.upper() in _NON_FINAL_STATES:
        next_action = "wait for the aragora-merge-quorum check to run on the current head"
    else:
        next_action = (
            "re-run aragora-merge-quorum so it re-reads the current evidence "
            "(scripts/reconcile_merge_quorum.py --apply)"
        )

    return SettlementStatus(
        pr_number=pr_number,
        head_sha=head_sha,
        tier=tier,
        counted_reviewer_ids=ids,
        has_dogfood=has_dogfood,
        human_settlement_present=human_settlement_present,
        quorum_conclusion=quorum_conclusion,
        next_action=next_action,
    )
