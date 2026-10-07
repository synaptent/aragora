#!/usr/bin/env python3
"""Bounded auto-evidence cycle for ready PRs (throughput lever 1, run-20260610).

Open, ready (non-draft) PRs that are missing counted model-review evidence sit
behind the merge-quorum gate until a human coordinator runs reviewers by hand.
This wrapper closes that loop autonomously and *boundedly*: it selects up to
``--max-prs`` such PRs, produces two-family evidence through the proven
``review-queue collect-evidence`` pipeline (which lint-validates every comment
with the gate's own ``evidence-lint`` parser *before* posting), then invokes
``scripts/quorum_rerun_reconciler.py --apply`` so stale quorum checks re-run.

Probe (cheapest reliable, two stages):

1. One ``gh pr list --json number,isDraft,statusCheckRollup`` call prunes
   drafts and PRs whose latest ``aragora-merge-quorum`` check already concluded
   SUCCESS (counted evidence exists at that head). Cheap but potentially stale.
2. Each surviving candidate is confirmed with ``review-queue merge-packet
   --pr N --json`` — the gate's own parser, hence the ground truth the
   reconciler also trusts. Only ``needs_model_review_quorum`` entries at
   Tier 0-2 with <2 counted families, no human-risk settlement requirement and
   no unresolved dissent are selected. Raw comment grepping would be cheaper
   than stage 2 but drifts from the canonical parser, so it is not used.

Safety model (mirrors ``quorum_rerun_reconciler.py``):

- Dry-run by default: prints the plan, runs nothing that spends or posts.
  ``--apply`` gates ALL mutations (reviewer spend, comment posting, reruns).
- Per-invocation caps: ``--max-prs`` (default 3), ``--max-scan`` packet probes
  (default 15), ``--budget-seconds`` wall clock (default 1800).
- Identical-error breaker: 3 consecutive identical collect failures abort the
  cycle (exit 2) — a systemic fault (CLI missing, auth broken) must not burn
  the whole budget. A run of consecutive transport-blocked merge-packet probes
  (GitHub/GraphQL down, auth broken) feeds the same breaker.
- Never-post-on-lint-fail is enforced *inside* collect-evidence; this wrapper
  additionally requires >=2 posted families before counting a PR as done.
- Tier gating is enforced twice: by this wrapper's selection and again by
  collect-evidence itself (Tier 3+/unknown always prepare-only).
- Secrets guard: collect-evidence subprocesses run with
  ``ARAGORA_SECRETS_STRICT=false`` and ``ARAGORA_USE_SECRETS_MANAGER=false``
  forced, because API reviewer construction under strict MFA-gated AWS dies on
  an interactive MFA prompt EOF (Lane V, run-20260609).
- Fail-closed exits: 0 clean (genuinely empty plan, no transport drops), 1 any
  failure, 2 breaker tripped, 3 INDETERMINATE — candidates were dropped because
  a merge-packet probe could not see them (transport_blocked / fetch failure)
  and nothing was posted, so an empty plan does NOT mean the queue is clear.

Legacy opt-in wiring: ``scripts/run_merge_arbiter.sh`` only calls this legacy
direct-apply path when both ``ARAGORA_AUTO_EVIDENCE=1`` and
``ARAGORA_ALLOW_LEGACY_AUTO_EVIDENCE_APPLY=1`` are set. Without the override,
the wrapper logs that no legacy evidence collection/posting will run and still
starts the merge-arbiter. Direct ``auto_evidence_cycle.py --apply`` and imported
``run_cycle(..., apply=True)`` are guarded by the same explicit override and
fail closed before posting. Conductor loops must use exact-head prepared-artifact
replay instead of this direct apply path for countable evidence.

Routing-rationale records (#8233 phase 1): each applied collect run also writes
a standalone JSON artifact (``--routing-records-dir``, default
``.aragora/automation-receipts/routing``) recording which model families were
requested/counted/posted and why that selection was in effect. Honest fields
only: cost is recorded as absent (this pipeline cannot observe it) and the
Pareto optimizer is disclosed as not consulted. Recording never blocks the
cycle; live tier-driven model switching is explicitly out of scope (#8234).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable

DEFAULT_REPO = "synaptent/aragora"
# Western-frontier pair (claude→opus-5, openai→gpt-5.5); see
# aragora.swarm.quorum_evidence.DEFAULT_FAMILIES. Override with --families.
DEFAULT_FAMILIES = ("claude", "openai")
DEFAULT_ROUTING_RECORDS_DIR = os.path.join(".aragora", "automation-receipts", "routing")
ROUTING_RECORD_SCHEMA = "aragora.routing_rationale/v1"
SELECTABLE_STATUS = "needs_model_review_quorum"
AUTO_POSTABLE_TIERS = {0, 1, 2}
REQUIRED_FAMILIES = 2
LEGACY_AUTO_EVIDENCE_APPLY_OVERRIDE_ENV = "ARAGORA_ALLOW_LEGACY_AUTO_EVIDENCE_APPLY"
GH_TIMEOUT_SECONDS = 120
PACKET_TIMEOUT_SECONDS = 300
COLLECT_TIMEOUT_SECONDS = 1200
RECONCILER_TIMEOUT_SECONDS = 600
DEFAULT_DOGFOOD_TIMEOUT = 600
DEFAULT_DOGFOOD_FAMILY = os.environ.get("ARAGORA_DOGFOOD_FAMILY", "claude").strip() or "claude"


def _load_dogfood_module() -> Any:
    """Load the sibling ``dogfood_evidence`` helper (script, not a package)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dogfood_evidence.py")
    spec = importlib.util.spec_from_file_location("aragora_dogfood_evidence", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load dogfood_evidence from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


EXIT_OK = 0
EXIT_FAILURES = 1
EXIT_BREAKER = 2
EXIT_INDETERMINATE = 3

# Sentinel status for a packet probe that could not see the PR (GitHub/GraphQL
# transport hiccup, subprocess failure, timeout, or unparseable output). This is
# INDETERMINATE — not "selectable" and not "genuinely clear" — so the operator
# can tell "no work" from "couldn't see the work".
TRANSPORT_BLOCKED_STATUS = "transport_blocked"


def _sanitized_env() -> dict[str, str]:
    """Child env for collect-evidence: never enter the MFA-gated secrets path.

    Lane V (run-20260609) saw ``scripts/collect_quorum_evidence.py`` API
    reviewers crash under ``ARAGORA_SECRETS_STRICT=true`` with MFA-gated AWS:
    ``create_agent`` triggered an interactive MFA prompt that EOFs in an
    unattended run. Reviewer API keys come from the local environment instead.
    """
    env = dict(os.environ)
    env["ARAGORA_SECRETS_STRICT"] = "false"
    env["ARAGORA_USE_SECRETS_MANAGER"] = "false"
    return env


def latest_quorum_conclusion(pr_row: dict[str, Any]) -> str:
    """Latest ``aragora-merge-quorum`` check conclusion at the PR head, or ``""``."""
    best_key = ""
    conclusion = ""
    for check in pr_row.get("statusCheckRollup") or []:
        if not isinstance(check, dict):
            continue
        workflow = str(check.get("workflowName") or "").lower()
        name = str(check.get("name") or check.get("context") or "").lower()
        if (
            "merge-quorum" not in workflow
            and "merge quorum" not in workflow
            and "merge-quorum" not in name
        ):
            continue
        key = str(check.get("completedAt") or check.get("startedAt") or "")
        if key >= best_key:
            best_key = key
            conclusion = str(check.get("conclusion") or "").upper()
    return conclusion


def stage1_candidates(prs: list[dict[str, Any]]) -> list[int]:
    """Ready (non-draft) PRs whose latest quorum check is not SUCCESS, newest first.

    Newest-first (#8316): the oldest-first ordering meant the low-numbered tail
    of permanently auto-INELIGIBLE PRs (Tier 3/4, human-settlement-required)
    consumed the entire ``--max-scan`` probe budget every run, so fresh ready
    Tier-0-2 PRs at the high end were never probed. Probing the freshest PRs
    first guarantees they are always reached; stage 2 also no longer lets
    ineligible candidates consume the eligible-scan budget.
    """
    out: list[int] = []
    for pr in prs:
        if not isinstance(pr, dict) or pr.get("isDraft"):
            continue
        try:
            number = int(pr["number"])
        except (KeyError, TypeError, ValueError):
            continue
        if latest_quorum_conclusion(pr) == "SUCCESS":
            continue
        out.append(number)
    return sorted(out, reverse=True)


def is_transport_blocked(entry: dict[str, Any]) -> bool:
    """Whether a packet probe came back INDETERMINATE (could not see the PR).

    A transport-blocked probe is neither selectable nor a clean "no work"
    signal: the GitHub/GraphQL hop, the subprocess, or the parser failed, so the
    PR's real selectability is unknown. ``default_fetch_packet`` synthesizes this
    envelope for any fetch failure/exception so the caller never silently treats
    a hiccup as an empty queue. The canonical CLI marks the same condition with
    ``status="transport_blocked"`` / ``transport_blocked: true`` (see
    ``aragora/cli/commands/review_queue_transport.py``).
    """
    if not entry:
        return False
    if entry.get("transport_blocked"):
        return True
    return str(entry.get("status") or "").strip().lower() == TRANSPORT_BLOCKED_STATUS


def rejection_reason(entry: dict[str, Any]) -> str | None:
    """Reason a packet entry is *not* selectable, or ``None`` if it is selectable.

    Returns a stable, low-cardinality reason string so the cycle can surface
    ``rejected_by_reason`` counts and distinguish an empty plan (everything
    rejected) from an exhausted scan window (budget ran out before reaching a
    selectable PR). Callers must treat transport-blocked entries as INDETERMINATE
    *before* asking for a rejection reason; this function assumes a real packet.
    """
    if not entry:
        return "empty_packet"
    if str(entry.get("status") or "").strip().lower() != SELECTABLE_STATUS:
        return "wrong_status"
    try:
        tier = int(entry.get("tier"))
    except (TypeError, ValueError):
        return "unknown_tier"  # fail safe, never auto-postable anyway
    if tier not in AUTO_POSTABLE_TIERS:
        return "wrong_tier"
    if entry.get("requires_human_risk_settlement"):
        return "human_settlement_required"
    if entry.get("unresolved_dissent"):
        return "unresolved_dissent"
    families = entry.get("counted_model_families")
    if families is None:
        families = entry.get("counted_reviewer_ids") or []
    if len(families) >= REQUIRED_FAMILIES:
        return "quorum_satisfied"
    return None


def needs_evidence(entry: dict[str, Any]) -> bool:
    """Whether a merge-packet entry is selectable for bounded auto-evidence."""
    if is_transport_blocked(entry):
        return False
    return rejection_reason(entry) is None


def needs_dogfood(entry: dict[str, Any]) -> bool:
    """Whether a merge-packet entry needs a dogfood-evidence step.

    A Tier-1+ code PR is dogfood-blocked when the packet declares
    ``requires_adversarial_dogfood`` but carries no counted dogfood evidence
    yet. We still only act inside the auto-postable tier band (0-2) and never on
    PRs gated on human risk settlement or with unresolved dissent — the cycle's
    existing safety envelope. (Tier 0 never requires dogfood, so it is filtered
    naturally by the ``requires_adversarial_dogfood`` flag.)
    """
    if not entry:
        return False
    if not entry.get("requires_adversarial_dogfood"):
        return False
    if entry.get("dogfood_evidence"):
        return False
    try:
        tier = int(entry.get("tier"))
    except (TypeError, ValueError):
        return False
    if tier not in AUTO_POSTABLE_TIERS:
        return False
    if entry.get("requires_human_risk_settlement"):
        return False
    if entry.get("unresolved_dissent"):
        return False
    return True


def parse_collect_output(returncode: int, stdout: str, stderr: str) -> dict[str, Any]:
    """Normalize a collect-evidence ``--json`` run into the wrapper's result shape."""
    try:
        payload = json.loads(stdout or "{}")
        if not isinstance(payload, dict):
            raise ValueError("non-object payload")
    except (json.JSONDecodeError, ValueError):
        return {
            "ok": False,
            "counting_families": [],
            "posted_families": [],
            "head_sha": "",
            "tier": None,
            "error": f"unparseable collect-evidence output (exit {returncode}): "
            f"{(stderr or stdout or '').strip()[:200]}",
        }
    counting = list(payload.get("counting_families") or [])
    posted = list(payload.get("posted_families") or [])
    head_sha = str(payload.get("head_sha") or "")
    raw_tier = payload.get("tier")
    tier: int | None
    try:
        tier = int(raw_tier) if raw_tier is not None else None
    except (TypeError, ValueError):
        tier = None
    error = str(payload.get("error") or "")
    post_errors = list(payload.get("post_errors") or [])
    ok = returncode == 0 and len(counting) >= REQUIRED_FAMILIES and not error
    if not ok and not error:
        problems = [
            f"{item.get('family')}: {', '.join(item.get('problems') or [])}"
            for item in payload.get("items") or []
            if isinstance(item, dict) and not item.get("would_count")
        ]
        failures = [
            f"{item.get('family')}: {item.get('error')}"
            for item in payload.get("failures") or []
            if isinstance(item, dict)
        ]
        error = "; ".join(["<2 counting families"] + failures + problems + post_errors)
    return {
        "ok": ok,
        "counting_families": counting,
        "posted_families": posted,
        "head_sha": head_sha,
        "tier": tier,
        "error": error,
    }


# --- Routing-rationale records (#8233 phase 1: instrument + recording only) ----
#
# Phase boundary: this module records WHICH models reviewed a PR and WHY that
# selection was in effect; it never performs live model switching. Live
# tier-driven routing (wiring aragora/routing/cost_quality_optimizer.py into
# the selection itself) is phase 2 (#8234).


def build_routing_record(
    *,
    repo: str,
    pr: int,
    tier: int | None,
    families_requested: tuple[str, ...],
    collect_result: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build one honest routing-rationale record for an applied collect run.

    Honest-fields contract:

    - ``models.*`` lists only families that were actually requested / counted /
      posted by the collect-evidence run (taken from its own JSON output).
    - ``selection_rationale`` states the real selector: a static family
      configuration constrained by the merge-quorum gate's heterogeneity rule.
      The Pareto optimizer is disclosed as NOT consulted — recording a
      ``pareto_optimizer_consulted: true`` here without wiring it would be a
      fabricated rationale.
    - ``cost.recorded`` is ``False`` with ``total_usd: None`` because the
      collect-evidence pipeline (claude CLI + API agents) does not surface
      per-call usage or pricing. Cost is recorded as absent, never estimated.
    """
    when = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tier_value: int | None = tier
    if tier_value is None:
        result_tier = collect_result.get("tier")
        tier_value = result_tier if isinstance(result_tier, int) else None
    return {
        "record_type": "routing_rationale",
        "schema": ROUTING_RECORD_SCHEMA,
        "generated_at": when,
        "repo": repo,
        "pr": pr,
        "head_sha": str(collect_result.get("head_sha") or ""),
        "decision_tier": tier_value,
        "phase_boundary": (
            "instrument-only: routing recorded, never switched live "
            "(#8233 phase 1; live switching is #8234)"
        ),
        "models": {
            "families_requested": list(families_requested),
            "families_counted": list(collect_result.get("counting_families") or []),
            "families_posted": list(collect_result.get("posted_families") or []),
        },
        "selection_rationale": {
            "selector": "static_configuration",
            "inputs": {
                "decision_tier": tier_value,
                "required_model_families": REQUIRED_FAMILIES,
                "heterogeneity_rule": (
                    "merge-quorum gate counts >=2 distinct model families; "
                    "families come from --families / DEFAULT_FAMILIES"
                ),
                "pareto_optimizer_consulted": False,
                "pareto_optimizer_note": (
                    "aragora.routing.cost_quality_optimizer.CostQualityOptimizer "
                    "is not wired into this path yet (#8234)"
                ),
            },
        },
        "cost": {
            "recorded": False,
            "total_usd": None,
            "absent_reason": (
                "collect-evidence reviewers (claude CLI, API agents) do not "
                "surface per-call usage or cost; recorded as absent, never estimated"
            ),
        },
        "outcome": {
            "ok": bool(collect_result.get("ok")),
            "error": str(collect_result.get("error") or ""),
        },
    }


def default_write_routing_record(record: dict[str, Any], records_dir: str) -> str:
    """Write a routing record as a standalone JSON artifact; return its path."""
    os.makedirs(records_dir, exist_ok=True)
    stamp = re.sub(r"[^0-9TZ]", "", str(record.get("generated_at") or ""))
    name = f"routing_pr{record.get('pr')}_{stamp or 'unknown'}.json"
    path = os.path.join(records_dir, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return path


# --- Default (real) I/O callables --------------------------------------------


def _gh_pr_list(repo: str, fields: str, limit: int) -> list[dict[str, Any]] | None:
    try:
        proc = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--json",
                fields,
                "--limit",
                str(limit),
            ],
            capture_output=True,
            text=True,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, list) else None


def default_list_prs(repo: str) -> list[dict[str, Any]]:
    """Open-PR listing with graceful degradation.

    ``statusCheckRollup`` over many PRs 504s GitHub's GraphQL endpoint
    (observed live at ``--limit 50``), so try shrinking pages, then fall back
    to a light listing without rollups — stage 1 then only prunes drafts and
    the canonical stage-2 probe (bounded by ``--max-scan``) carries selection.
    Fails closed with a clean error when even the light listing is down.
    """
    for limit in (100, 50, 30):
        rows = _gh_pr_list(repo, "number,isDraft,statusCheckRollup", limit)
        if rows is not None:
            return rows
    rows = _gh_pr_list(repo, "number,isDraft", 200)
    if rows is not None:
        return rows
    raise RuntimeError(f"gh pr list failed for {repo} (heavy and light listings)")


def _transport_blocked_packet(pr: int, error: str) -> dict[str, Any]:
    """Synthesize an INDETERMINATE packet for a probe that could not see the PR.

    Any fetch failure (subprocess error, non-zero exit, timeout, unparseable
    output, or an explicit transport-blocked CLI envelope) becomes this shape so
    the cycle counts the PR in ``transport_blocked_prs`` rather than silently
    treating the hiccup as a clean empty queue.
    """
    return {
        "pr_number": pr,
        "status": TRANSPORT_BLOCKED_STATUS,
        "transport_blocked": True,
        "error": str(error or "")[:300],
    }


def default_fetch_packet(repo: str, pr: int) -> dict[str, Any]:
    """Canonical per-PR probe: ``review-queue merge-packet --pr N --json``.

    A clean structural "not selectable" packet is returned as-is (possibly
    ``{}``). Any *failure* to see the PR — subprocess error, timeout, non-zero
    exit, unparseable output, or an explicit ``transport_blocked`` envelope — is
    surfaced as an INDETERMINATE transport-blocked packet, never as ``{}``; the
    operator must be able to tell "no work" from "couldn't see the work".
    """
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "aragora.cli.main",
                "review-queue",
                "merge-packet",
                "--pr",
                str(pr),
                "--repo",
                repo,
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=PACKET_TIMEOUT_SECONDS,
            env=_sanitized_env(),
        )
    except subprocess.TimeoutExpired:
        return _transport_blocked_packet(
            pr, f"merge-packet timed out after {PACKET_TIMEOUT_SECONDS}s"
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return _transport_blocked_packet(pr, f"merge-packet subprocess error: {exc}")
    if proc.returncode != 0 or not proc.stdout.strip():
        return _transport_blocked_packet(
            pr,
            (proc.stderr or proc.stdout or f"merge-packet exit {proc.returncode}").strip(),
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return _transport_blocked_packet(pr, "unparseable merge-packet output")
    # An explicit transport-blocked envelope carries no matching entry, so detect
    # it at the envelope level before the per-PR entry scan drops it.
    if isinstance(payload, dict) and (
        payload.get("transport_blocked")
        or str(payload.get("status") or "").strip().lower() == TRANSPORT_BLOCKED_STATUS
    ):
        return _transport_blocked_packet(pr, payload.get("error") or "transport blocked")
    if isinstance(payload, dict):
        entries = payload.get("entries")
        entries = entries if isinstance(entries, list) else [payload]
    elif isinstance(payload, list):
        entries = payload
    else:
        return {}
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("pr_number")) == str(pr):
            return entry
    return {}


def default_run_collect(
    repo: str, families: tuple[str, ...], pr: int, apply: bool
) -> dict[str, Any]:
    cmd = [
        sys.executable,
        "-m",
        "aragora.cli.main",
        "review-queue",
        "collect-evidence",
        "--pr",
        str(pr),
        "--repo",
        repo,
        "--reviewers",
        *families,
        "--json",
    ]
    if apply:
        cmd.append("--apply")
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=COLLECT_TIMEOUT_SECONDS,
            env=_sanitized_env(),
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "counting_families": [],
            "posted_families": [],
            "error": f"collect-evidence timed out after {COLLECT_TIMEOUT_SECONDS}s",
        }
    return parse_collect_output(proc.returncode, proc.stdout, proc.stderr)


def default_run_dogfood(
    repo: str, pr: int, *, model_family: str, timeout: int, apply: bool
) -> dict[str, Any]:
    """Run the bounded dogfood step for one PR via the sibling helper.

    Returns a normalized dict: ``{"status": ..., "reason": ..., "posted": bool}``.
    All git/gh/subprocess work happens inside the helper's injected defaults.
    """
    df = _load_dogfood_module()
    outcome = df.dogfood_pr(
        repo=repo,
        pr=pr,
        model_family=model_family,
        timeout=timeout,
        apply=apply,
        fetch_head=df.default_fetch_pr_head,
        changed_files=df.default_changed_files,
        checkout=df.default_checkout_worktree,
        remove_worktree=df.default_remove_worktree,
        run_validation=df.default_run_validation,
        lint_evidence=df.default_lint_evidence,
        post_comment=df.default_post_comment,
    )
    return {
        "status": outcome.status,
        "reason": outcome.reason,
        "posted": outcome.status == "posted",
        "command": outcome.command,
        "would_count": outcome.would_count,
    }


def default_record_trail(repo: str, pr: int, posted_families: list[str]) -> None:
    """Record a tamper-evident-trail intent for posted quorum evidence.

    TET T1 example call site (docs/specs/TAMPER_EVIDENT_TRAIL.md Component 2,
    step 3): evidence posting is a settlement-advancing repo mutation, so it
    lands on the intent chain as an ``agent-app``/``settle_pr`` intent.
    ``record_intent`` is a no-op unless ``ARAGORA_TRAIL=1`` and never raises;
    the lazy import keeps this wiring non-fatal everywhere.

    Hook contract: ``run_cycle`` deals in ``(pr, posted_families)`` only —
    ``main()`` binds ``repo`` into the injected closure
    (``lambda pr, posted: default_record_trail(args.repo, pr, posted)``), the
    same partial-application pattern every other ``run_cycle`` boundary here
    uses (``run_collect``, ``fetch_packet``). ``repo`` is not dropped.
    """
    try:
        from aragora.trail import record_intent
    except ImportError:
        return
    record_intent(
        actor_class="agent-app",
        intent_type="settle_pr",
        target={"repo": repo, "pr": pr},
        payload={"action": "post_quorum_evidence", "posted_families": list(posted_families)},
    )


def default_run_reconciler(repo: str) -> int:
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quorum_rerun_reconciler.py")
    try:
        proc = subprocess.run(
            [sys.executable, script, "--repo", repo, "--apply"],
            timeout=RECONCILER_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return 1
    return proc.returncode


# --- Singleton lock -------------------------------------------------------------


class CycleLockHeld(RuntimeError):
    """Another auto-evidence cycle currently holds the singleton lock."""


def acquire_cycle_lock(
    lock_path: str,
    *,
    stale_after_seconds: float = 7200.0,
    now: Callable[[], float] = time.time,
) -> Callable[[], None]:
    """Take an exclusive advisory lock for apply mode; return a release callable.

    Two concurrent ``--apply`` invocations (e.g. the merge-arbiter wiring racing
    a manual run) could both pass selection before either posts, double-posting
    evidence. ``O_CREAT | O_EXCL`` makes acquisition atomic; a lock older than
    ``stale_after_seconds`` (default 2h — well past any sane ``--budget-seconds``)
    is treated as a crash leftover and reclaimed. Raises :class:`CycleLockHeld`
    when a live lock exists (caller fails closed without posting anything).
    """
    try:
        age = now() - os.path.getmtime(lock_path)
        if age > stale_after_seconds:
            os.unlink(lock_path)
    except OSError:
        pass  # no lock file (common case) or it vanished between checks
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise CycleLockHeld(f"lock {lock_path} is held by another invocation") from None
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(f"pid={os.getpid()}\n")

    def release() -> None:
        try:
            os.unlink(lock_path)
        except OSError:
            pass

    return release


def default_lock_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".aragora", "auto_evidence_cycle.lock")


def legacy_auto_evidence_apply_allowed(env: Mapping[str, str] = os.environ) -> bool:
    return env.get(LEGACY_AUTO_EVIDENCE_APPLY_OVERRIDE_ENV, "").strip() == "1"


# --- Orchestrator --------------------------------------------------------------


def run_cycle(
    *,
    list_prs: Callable[[], list[dict[str, Any]]],
    fetch_packet: Callable[[int], dict[str, Any]],
    run_collect: Callable[[int, bool], dict[str, Any]],
    run_reconciler: Callable[[], int],
    record_trail: Callable[[int, list[str]], None] | None = None,
    apply: bool,
    max_prs: int,
    max_scan: int,
    budget_seconds: float,
    breaker_threshold: int,
    run_dogfood: Callable[[int, bool], dict[str, Any]] | None = None,
    max_dogfood: int = 3,
    write_routing_record: Callable[[dict[str, Any]], str] | None = None,
    repo: str = DEFAULT_REPO,
    families: tuple[str, ...] = DEFAULT_FAMILIES,
    clock: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = print,
    allow_legacy_apply: bool = False,
) -> dict[str, Any]:
    """Plan and (with ``apply``) execute one bounded auto-evidence cycle.

    Two complementary passes share the candidate scan:

    - **Model-quorum** (existing): PRs at ``needs_model_review_quorum`` with <2
      counted families get two-family evidence minted via collect-evidence.
    - **Dogfood** (#8219, when ``run_dogfood`` is supplied): Tier-1+ code PRs
      whose packet ``requires_adversarial_dogfood`` but carries no dogfood
      evidence get a bounded, fail-closed dogfood run; a passing run posts a
      counting dogfood-evidence comment so the gate's dogfood requirement is
      satisfied. Together the two passes let the cycle settle code PRs
      end-to-end, not just docs.
    """
    started = clock()

    def over_budget() -> bool:
        return clock() - started > budget_seconds

    summary: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "plan": [],
        "dogfood_plan": [],
        "transport_blocked_prs": [],
        "scanned": 0,
        "rejected_by_reason": {},
        "unprobed_candidates": 0,
        "posted_prs": [],
        "failed_prs": [],
        "dogfood_posted_prs": [],
        "dogfood_failed_prs": [],
        "dogfood_skipped_prs": [],
        "routing_records": [],
        "routing_record_errors": [],
        "legacy_apply_refused": False,
        "breaker_tripped": False,
        "budget_exhausted": False,
        "reconciler_exit": None,
        "exit_code": EXIT_OK,
    }

    if apply and not allow_legacy_apply:
        summary["legacy_apply_refused"] = True
        summary["exit_code"] = EXIT_FAILURES
        log(
            json.dumps(
                {
                    "result": "legacy_apply_refused",
                    "reason": (
                        "legacy direct auto-evidence apply requires "
                        f"{LEGACY_AUTO_EVIDENCE_APPLY_OVERRIDE_ENV}=1"
                    ),
                }
            )
        )
        return summary

    candidates = stage1_candidates(list_prs())
    # ``--max-scan`` now bounds ELIGIBLE-or-INDETERMINATE examinations, not raw
    # probes (#8316): cleanly-ineligible candidates (wrong tier / wrong status /
    # human-settlement-required / unresolved-dissent / already-satisfied) no
    # longer consume the scan budget, so a low-numbered tail of permanently
    # ineligible Tier-3/4 PRs can never starve a fresh eligible PR further down
    # the list. ``scanned`` records the total candidates examined.
    examined_budget = 0  # eligible-or-indeterminate examinations against max_scan
    transport_streak = 0  # consecutive transport-blocked probes (breaker input)
    for number in candidates:
        scan_full = len(summary["plan"]) >= max_prs and (
            run_dogfood is None or len(summary["dogfood_plan"]) >= max_dogfood
        )
        if scan_full or examined_budget >= max_scan:
            break
        if over_budget():
            summary["budget_exhausted"] = True
            break
        summary["scanned"] += 1
        entry = fetch_packet(number)

        if is_transport_blocked(entry):
            # INDETERMINATE: could not see the PR. Count it (so an empty plan is
            # distinguishable from a hiccup), consume budget, but do not select.
            summary["transport_blocked_prs"].append(number)
            examined_budget += 1
            transport_streak += 1
            # A run of identical transport failures is a systemic fault (auth
            # broken, GraphQL down) — feed it into the same breaker the apply
            # loop uses so the cycle aborts (exit 2) instead of grinding the
            # whole scan budget against a dead endpoint.
            if transport_streak >= breaker_threshold:
                summary["breaker_tripped"] = True
                log(
                    json.dumps(
                        {
                            "result": "breaker_tripped",
                            "stage": "scan",
                            "transport_blocked_streak": transport_streak,
                        }
                    )
                )
                break
            continue
        transport_streak = 0

        selectable_quorum = needs_evidence(entry)
        selectable_dogfood = run_dogfood is not None and needs_dogfood(entry)
        if selectable_quorum or selectable_dogfood:
            examined_budget += 1
        else:
            # Cleanly ineligible: record the reason, but do NOT consume the
            # eligible-scan budget — keep probing past it to reach fresh PRs.
            reason = rejection_reason(entry) or "ineligible"
            summary["rejected_by_reason"][reason] = summary["rejected_by_reason"].get(reason, 0) + 1

        if selectable_quorum and len(summary["plan"]) < max_prs:
            # NB: keep this local distinct from the ``families`` parameter
            # (requested reviewer families) used by routing records below.
            counted = entry.get("counted_model_families") or entry.get("counted_reviewer_ids") or []
            summary["plan"].append(
                {
                    "pr": number,
                    "tier": entry.get("tier"),
                    "status": entry.get("status"),
                    "counted_families": list(counted),
                }
            )
        if selectable_dogfood and len(summary["dogfood_plan"]) < max_dogfood:
            summary["dogfood_plan"].append(
                {
                    "pr": number,
                    "tier": entry.get("tier"),
                    "status": entry.get("status"),
                    "requires_adversarial_dogfood": True,
                }
            )
    # Candidates the scan never reached (loop broke on cap/budget before the
    # end). ``scanned`` counts every candidate examined, so this is exact.
    summary["unprobed_candidates"] = max(0, len(candidates) - summary["scanned"])

    for item in summary["plan"]:
        log(json.dumps({**item, "mode": summary["mode"]}))
    for item in summary["dogfood_plan"]:
        log(json.dumps({**item, "mode": summary["mode"], "step": "dogfood"}))
    if not summary["plan"] and not summary["dogfood_plan"]:
        log(json.dumps({"plan": "empty", "mode": summary["mode"]}))

    if not apply:
        # Dry-run never posts, so "transport drops + nothing posted" reduces to
        # "transport drops occurred": an empty plan that is INDETERMINATE, not
        # genuinely clear. The scan-phase breaker still wins (exit 2).
        if summary["breaker_tripped"]:
            summary["exit_code"] = EXIT_BREAKER
        elif summary["transport_blocked_prs"]:
            summary["exit_code"] = EXIT_INDETERMINATE
        return summary

    identical_errors = 0
    last_error = None
    collect_plan = [] if summary["breaker_tripped"] else summary["plan"]
    for item in collect_plan:
        if over_budget():
            summary["budget_exhausted"] = True
            break
        result = run_collect(item["pr"], True)
        if write_routing_record is not None:
            # Recording is additive instrumentation: a failed record write is
            # surfaced in the summary but never blocks or fails the cycle.
            record = build_routing_record(
                repo=repo,
                pr=item["pr"],
                tier=item.get("tier") if isinstance(item.get("tier"), int) else None,
                families_requested=families,
                collect_result=result,
            )
            try:
                summary["routing_records"].append(write_routing_record(record))
            except OSError as exc:
                summary["routing_record_errors"].append(f"pr {item['pr']}: {str(exc)[:200]}")
        posted = list(result.get("posted_families") or [])
        ok = bool(result.get("ok")) and len(posted) >= REQUIRED_FAMILIES
        if ok:
            summary["posted_prs"].append(item["pr"])
            if record_trail is not None:
                record_trail(item["pr"], posted)
            identical_errors = 0
            last_error = None
            log(json.dumps({"pr": item["pr"], "posted_families": posted, "result": "posted"}))
            continue
        if result.get("ok"):
            # Collected fine but posted <2 families: not quorum evidence.
            error = f"only {len(posted)} family posted ({', '.join(posted) or 'none'}); not quorum"
        else:
            error = str(result.get("error") or "collect failed")
        summary["failed_prs"].append(item["pr"])
        log(json.dumps({"pr": item["pr"], "result": "failed", "error": error[:300]}))
        identical_errors = identical_errors + 1 if error == last_error else 1
        last_error = error
        if identical_errors >= breaker_threshold:
            summary["breaker_tripped"] = True
            log(
                json.dumps(
                    {
                        "result": "breaker_tripped",
                        "identical_errors": identical_errors,
                        "error": error[:300],
                    }
                )
            )
            break

    # Dogfood pass: bounded, fail-closed. A failing dogfood posts nothing and is
    # recorded as a real not-ready signal (not a cycle failure that should trip
    # the breaker — the breaker is for systemic faults, which the dogfood helper
    # surfaces as "skipped" with a reason, not a passing/failing validation).
    if run_dogfood is not None and not summary["breaker_tripped"]:
        for item in summary["dogfood_plan"]:
            if over_budget():
                summary["budget_exhausted"] = True
                break
            result = run_dogfood(item["pr"], True)
            status = str(result.get("status") or "")
            log(
                json.dumps(
                    {
                        "pr": item["pr"],
                        "step": "dogfood",
                        "result": status,
                        "reason": str(result.get("reason") or "")[:200],
                    }
                )
            )
            if status == "posted":
                summary["dogfood_posted_prs"].append(item["pr"])
            elif status == "failed":
                summary["dogfood_failed_prs"].append(item["pr"])
            else:
                summary["dogfood_skipped_prs"].append(item["pr"])

    if summary["posted_prs"] or summary["dogfood_posted_prs"]:
        summary["reconciler_exit"] = run_reconciler()
        log(json.dumps({"reconciler_exit": summary["reconciler_exit"]}))

    posted_anything = bool(summary["posted_prs"] or summary["dogfood_posted_prs"])
    if summary["breaker_tripped"]:
        summary["exit_code"] = EXIT_BREAKER
    elif summary["failed_prs"] or (summary["reconciler_exit"] not in (None, 0)):
        summary["exit_code"] = EXIT_FAILURES
    elif summary["transport_blocked_prs"] and not posted_anything:
        # Candidates were dropped because we couldn't see them and nothing was
        # posted: INDETERMINATE, not a clean empty queue. Exit 3 so the operator
        # distinguishes "no work" from "couldn't see the work".
        summary["exit_code"] = EXIT_INDETERMINATE
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub repo owner/name")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Run reviewers, post counting evidence, and rerun stale quorum checks "
        "(default: dry-run plan only — nothing is spent or posted)",
    )
    parser.add_argument(
        "--max-prs", type=int, default=3, help="Maximum PRs to produce evidence for (default: 3)"
    )
    parser.add_argument(
        "--max-scan",
        type=int,
        default=15,
        help="Maximum merge-packet probes per invocation (default: 15)",
    )
    parser.add_argument(
        "--budget-seconds",
        type=float,
        default=1800.0,
        help="Wall-clock budget; no new work starts past this (default: 1800)",
    )
    parser.add_argument(
        "--breaker-threshold",
        type=int,
        default=3,
        help="Consecutive identical collect failures that abort the cycle (default: 3)",
    )
    parser.add_argument(
        "--families",
        default=",".join(DEFAULT_FAMILIES),
        help="Comma-separated reviewer model families (default: claude,grok)",
    )
    parser.add_argument(
        "--dogfood",
        action="store_true",
        help="Also run the bounded dogfood-evidence step for Tier-1+ code PRs that "
        "require adversarial dogfood but have none (#8219). Fail-closed: a failing "
        "dogfood posts nothing.",
    )
    parser.add_argument(
        "--max-dogfood",
        type=int,
        default=3,
        help="Maximum PRs to dogfood per invocation (default: 3)",
    )
    parser.add_argument(
        "--dogfood-timeout",
        type=int,
        default=DEFAULT_DOGFOOD_TIMEOUT,
        help="Per-PR dogfood validation wall-clock timeout in seconds (default: 600)",
    )
    parser.add_argument(
        "--dogfood-family",
        default=DEFAULT_DOGFOOD_FAMILY,
        help="Model family disclosed as the dogfooder (default: claude or $ARAGORA_DOGFOOD_FAMILY)",
    )
    parser.add_argument(
        "--routing-records-dir",
        default=DEFAULT_ROUTING_RECORDS_DIR,
        help="Directory for routing-rationale record artifacts written per applied "
        f"collect run (#8233 phase 1; default: {DEFAULT_ROUTING_RECORDS_DIR})",
    )
    parser.add_argument(
        "--no-routing-records",
        action="store_true",
        help="Disable writing routing-rationale records in apply mode",
    )
    args = parser.parse_args(argv)

    families = tuple(f.strip() for f in str(args.families).split(",") if f.strip())
    if len(families) < REQUIRED_FAMILIES:
        print(f"error: need >= {REQUIRED_FAMILIES} reviewer families", file=sys.stderr)
        return EXIT_FAILURES

    if args.apply and not legacy_auto_evidence_apply_allowed():
        print(
            "error: legacy direct auto-evidence apply is disabled by §Conductor; "
            f"set {LEGACY_AUTO_EVIDENCE_APPLY_OVERRIDE_ENV}=1 only for an explicit "
            "operator override, or use prepared-artifact replay",
            file=sys.stderr,
        )
        return EXIT_FAILURES

    release: Callable[[], None] = lambda: None
    if args.apply:
        # Mutations require the singleton lock: two racing --apply invocations
        # could both pass selection and double-post evidence on the same PR.
        lock_dir = os.path.dirname(default_lock_path())
        try:
            os.makedirs(lock_dir, exist_ok=True)
            release = acquire_cycle_lock(default_lock_path())
        except CycleLockHeld as exc:
            print(f"error: {exc}; refusing to run concurrently", file=sys.stderr)
            return EXIT_FAILURES
        except OSError as exc:
            print(f"error: could not take cycle lock: {exc}", file=sys.stderr)
            return EXIT_FAILURES

    run_dogfood: Callable[[int, bool], dict[str, Any]] | None = None
    if args.dogfood:
        run_dogfood = lambda pr, apply: default_run_dogfood(
            args.repo,
            pr,
            model_family=str(args.dogfood_family),
            timeout=max(1, int(args.dogfood_timeout)),
            apply=apply,
        )

    write_record: Callable[[dict[str, Any]], str] | None = None
    if args.apply and not args.no_routing_records:
        write_record = lambda record: default_write_routing_record(record, args.routing_records_dir)

    try:
        summary = run_cycle(
            list_prs=lambda: default_list_prs(args.repo),
            fetch_packet=lambda pr: default_fetch_packet(args.repo, pr),
            run_collect=lambda pr, apply: default_run_collect(args.repo, families, pr, apply),
            run_reconciler=lambda: default_run_reconciler(args.repo),
            record_trail=lambda pr, posted: default_record_trail(args.repo, pr, posted),
            run_dogfood=run_dogfood,
            max_dogfood=max(0, args.max_dogfood),
            write_routing_record=write_record,
            repo=args.repo,
            families=families,
            apply=args.apply,
            max_prs=max(0, args.max_prs),
            max_scan=max(0, args.max_scan),
            budget_seconds=args.budget_seconds,
            breaker_threshold=max(1, args.breaker_threshold),
            allow_legacy_apply=legacy_auto_evidence_apply_allowed(),
        )
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILURES
    finally:
        release()
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "plan"}
            | {"planned_prs": [item["pr"] for item in summary["plan"]]}
        )
    )
    return int(summary["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
