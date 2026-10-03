"""Pure routing/gating decision for the operator-driven PR settlement CLI.

``scripts/settle_pr.py`` orchestrates the end-to-end settlement runbook by
*composing* the existing tools (``collect_quorum_evidence.py`` for evidence,
``auto_merge_quorum_green.py`` for Tier 0-2 merges, ``settle_tier4_pr.py`` for
Tier 3-4 human settlement). This module is its single decision brain: given an
already-fetched quorum/tier state it decides whether settlement can proceed and
by which route, accumulating every blocker. It performs **no I/O**, so the
routing/gating logic stays deterministic and unit-testable.

The actual merge gate is never reimplemented here -- the composed tools remain
authoritative and enforce it. This module only decides *which* of them to invoke
and refuses to proceed when the model quorum is not genuinely satisfied.
"""

from __future__ import annotations

import math
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from aragora.cli.commands.review_queue_comment_verdicts import extract_finding_lines

# Tier 0-2 can settle unattended on a green model quorum (auto-merge path);
# Tier 3-4 require a head-bound human risk settlement by a trusted operator.
AUTO_MERGE_MAX_TIER = 2

ROUTE_AUTO_MERGE = "auto_merge_green"
ROUTE_OPERATOR_TIER4 = "operator_human_settlement"
ROUTE_BLOCKED = "blocked"


@dataclass(frozen=True)
class SettlementPlan:
    """The decided route + readiness for one PR. Pure output of :func:`plan_settlement`."""

    tier: int | None
    route: str
    quorum_satisfied: bool
    requires_operator_login: bool
    ready_to_mutate: bool
    blockers: tuple[str, ...]


def plan_settlement(
    *,
    tier: int | None,
    quorum_satisfied: bool,
    supportive_families: Sequence[str],
    head_sha: str | None = None,
    unresolved_dissent: bool = False,
    operator_login_provided: bool = False,
    collect_refused_to_post: bool = False,
) -> SettlementPlan:
    """Decide the settlement route and whether it is safe to proceed.

    ``ready_to_mutate`` is True only when the model quorum is satisfied, the tier
    is classified, and any route-specific precondition is met (Tier 3-4 needs an
    operator login). Every reason a mutation is refused is collected in
    ``blockers`` so the CLI can surface all of them at once.
    """
    blockers: list[str] = []
    supportive = sorted({str(f) for f in supportive_families})

    if not quorum_satisfied:
        blockers.append(f"model quorum not satisfied (supportive families: {supportive or 'none'})")

    if tier is None:
        route = ROUTE_BLOCKED
        blockers.append("tier unknown (merge-packet did not classify the PR)")
    elif tier < 0:
        # A negative tier is malformed; `tier <= 2` would pick the LESS conservative
        # auto-merge path. Fail safe -- the composed tools also treat <0 as invalid.
        route = ROUTE_BLOCKED
        blockers.append(
            f"invalid tier {tier} (negative -- merge-packet classification is malformed)"
        )
    elif tier <= AUTO_MERGE_MAX_TIER:
        route = ROUTE_AUTO_MERGE
    else:
        route = ROUTE_OPERATOR_TIER4

    # Genuine tier escalation is handled by tier-based routing above (collect's
    # reported tier >2 -> operator). A "prepare" verdict is NOT a reliable tier
    # signal: collect also prepares when the head moved (tier 2->2), a recheck is
    # pending, or a transient gh error hit -- so we never re-route an auto-merge to
    # the operator path on it (that would surface Tier-4 commands bound to a
    # superseded head). Instead: never auto-merge OVER a refusal-to-post. Block and
    # tell the operator to re-run collect on the current head.
    if collect_refused_to_post and route == ROUTE_AUTO_MERGE:
        blockers.append(
            "collect refused to post evidence despite a satisfied quorum "
            "(head moved / recheck pending / tier promotion) -- re-run collect on "
            "the current head rather than auto-merging over a refusal-to-post"
        )

    # Dissent blocks every route, not just auto-merge: Tier 0-2 cannot auto-merge
    # over a dissent, and settle_tier4_pr hard-fails on unresolved_dissent too, so
    # a Tier 3-4 plan that ignored it would surface commands doomed to fail.
    if unresolved_dissent and route != ROUTE_BLOCKED:
        blockers.append(
            "unresolved model dissent (auto-merge and Tier 3-4 settlement both refuse it)"
        )

    requires_operator_login = route == ROUTE_OPERATOR_TIER4
    if requires_operator_login and not operator_login_provided:
        blockers.append(
            f"Tier {tier} requires a human risk settlement: pass --operator-login <gh-login>"
        )

    # The Tier 3-4 settle commands are head-bound (settle_tier4_pr --head <sha>);
    # without a resolved head they would render as runnable-looking but doomed
    # `--head <head>` placeholders. Refuse to call that route ready.
    if route == ROUTE_OPERATOR_TIER4 and not (head_sha and str(head_sha).strip()):
        blockers.append("head_sha unresolved (cannot emit head-bound Tier 3-4 settle commands)")

    ready_to_mutate = not blockers and route != ROUTE_BLOCKED
    return SettlementPlan(
        tier=tier,
        route=route,
        quorum_satisfied=quorum_satisfied,
        requires_operator_login=requires_operator_login,
        ready_to_mutate=ready_to_mutate,
        blockers=tuple(blockers),
    )


def tier4_settle_commands(
    *,
    repo: str,
    pr: int,
    head: str,
    operator_login: str,
    no_app_token: bool = False,
    repo_root: str | None = None,
) -> list[str]:
    """The exact, head-bound ``settle_tier4_pr.py`` commands a trusted operator runs
    to record the human risk settlement and merge. The CLI surfaces these rather
    than executing them: the Tier-4 human settlement must be a deliberate operator
    act, never an automated one.

    Every interpolated value is ``shlex.quote``d: these strings are surfaced for
    copy-paste into a shell, so an unquoted ``repo``/``head``/``operator_login``
    bearing shell metacharacters would be a command-injection vector. ``pr`` is
    coerced to ``int`` for the same reason. ``repo_root``, when given, prepends a
    ``cd <root> &&`` guard so the cwd-relative ``scripts/...`` path resolves even
    when the operator pastes from outside the repo root."""
    cmd = (
        f"python3 scripts/settle_tier4_pr.py --pr {int(pr)} --head {shlex.quote(str(head))} "
        f"--trusted-operator-login {shlex.quote(str(operator_login))} --repo {shlex.quote(str(repo))}"
    )
    cd_prefix = f"cd {shlex.quote(str(repo_root))} && " if repo_root else ""
    env_prefix = "ARAGORA_DISABLE_GITHUB_APP_TOKEN=1 " if no_app_token else ""
    return [
        f"{cd_prefix}{cmd} --check",
        f"{cd_prefix}{cmd} --settle-only",
        f"{cd_prefix}{env_prefix}{cmd} --merge-apply",
    ]


def _coerce_tier(value: Any) -> int | None:
    """Coerce a merge-packet ``tier`` to a non-negative ``int`` (else ``None``).

    ``plan_settlement`` does ``tier <= AUTO_MERGE_MAX_TIER``; a non-int tier from a
    malformed payload would raise ``TypeError`` there. Coercing here keeps the
    planner total: a bool, a non-finite/non-integral/negative float, an
    unparseable string, or a negative int all become ``None`` -> fail-safe
    ``ROUTE_BLOCKED``. ``json.loads`` accepts ``NaN``/``Infinity`` by default, so
    finiteness is checked BEFORE ``int(value)`` (which would otherwise raise
    ``ValueError``/``OverflowError`` on them)."""
    if isinstance(value, bool):
        return None
    coerced: int | None
    if isinstance(value, int):
        coerced = value
    elif isinstance(value, float):
        coerced = int(value) if (math.isfinite(value) and value == int(value)) else None
    elif isinstance(value, str):
        try:
            coerced = int(value.strip())
        except ValueError:
            coerced = None
    else:
        coerced = None
    if coerced is not None and coerced < 0:
        return None
    return coerced


def summarize_collect(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten a ``collect_quorum_evidence --json`` payload into the fields the
    planner and diagnostics need. Tolerates the error envelope (``{"error": ...}``)
    by reporting an unsatisfied quorum with no tier."""
    if payload.get("error"):
        return {
            "error": str(payload["error"]),
            "tier": None,
            "head_sha": payload.get("head_sha"),
            "quorum_satisfied": False,
            "action": payload.get("action"),
            "action_reason": payload.get("action_reason"),
            "supportive_families": [],
            "dissenting_families": [],
            "items": [],
            "failures": list(payload.get("failures") or []),
        }
    items = []
    for it in payload.get("items") or []:
        if not isinstance(it, dict):
            # A malformed (non-dict) item must not crash the flatten the way the
            # top-level error envelope is already guarded against -- skip it.
            continue
        body = str(it.get("body") or "")
        items.append(
            {
                "family": it.get("family"),
                "verdict": it.get("verdict"),
                "would_count": bool(it.get("would_count")),
                "counted_reviewer_ids": list(it.get("counted_reviewer_ids") or []),
                # ``problems`` are countability codes ("blocking_or_negative_verdict",
                # "no_counted_model_family", ...). They say a reviewer dissented but
                # never WHY, so a dissent used to cost a second full reviewer run to
                # diagnose. ``findings`` carries the reviewer's actual [Pn] lines.
                "problems": list(it.get("problems") or []),
                "findings": extract_finding_lines(body),
                "body": body,
            }
        )
    return {
        "error": None,
        "tier": _coerce_tier(payload.get("tier")),
        "head_sha": payload.get("head_sha"),
        "quorum_satisfied": bool(payload.get("has_supportive_quorum")),
        # collect's OWN authority signal: "post" means it classified the PR as
        # auto-postable (Tier 0-2); "prepare" means it refused to post (Tier >=3
        # or a recheck tier-promotion). The CLI uses this as a cross-check so a
        # stale top-level ``tier`` cannot misroute an auto-merge (see settle_pr).
        "action": payload.get("action"),
        "action_reason": payload.get("action_reason"),
        "supportive_families": list(payload.get("supportive_families") or []),
        "dissenting_families": list(payload.get("dissenting_families") or []),
        "items": items,
        "failures": list(payload.get("failures") or []),
    }
