#!/usr/bin/env python3
"""Read-only settlement gate preflight for conductor queue selection."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.settle_one_pr as settle_one_pr

RECHECK_RULE = "recheck on next origin/main push; never poll in a loop."
POLICY_METADATA_REASON = "missing PR policy metadata with non-empty files"
QUEUE_POLICY_METADATA_REASON = POLICY_METADATA_REASON
LIVE_METADATA_REASON = "live PR metadata unavailable"
REQUIRED_CHECK_METADATA_REASON = "required check metadata unavailable"
OPEN_QUEUE_METADATA_REASON = "open PR queue metadata unavailable"
ACTIVE_OWNER_METADATA_REASON = (
    "operator-snapshot unavailable; active-owned exclusions cannot be trusted"
)
ACTIVE_OWNER_REASON = "active-owned lane"
MERGE_QUORUM = "aragora-merge-quorum"
REQUIRED_GREEN_CONTEXTS = (
    "lint",
    "typecheck",
    "sdk-parity",
    "Generate & Validate",
    "TypeScript SDK Type Check",
)
EXPECTED_REQUIRED_CONTEXTS = {*REQUIRED_GREEN_CONTEXTS, MERGE_QUORUM}
TRANSPORT_FAILURE_PREFIXES = (
    POLICY_METADATA_REASON,
    LIVE_METADATA_REASON,
    REQUIRED_CHECK_METADATA_REASON,
    OPEN_QUEUE_METADATA_REASON,
    ACTIVE_OWNER_METADATA_REASON,
)

MAIN_RED_HALT = "MAIN_RED_HALT"
DRAFT_SKIP = "DRAFT_SKIP"
HUMAN_GATED = "HUMAN_GATED"
HEAD_BLOCKED = "HEAD_BLOCKED"
GITHUB_UNSTABLE = "GITHUB_UNSTABLE"
READY = "READY"


@dataclass(frozen=True)
class PreflightResult:
    pr_number: int
    verdict: str
    action: str
    recheck_rule: str
    title: str = ""
    head_sha: str = ""
    tier: int | None = None
    mergeable: str = ""
    merge_state: str = ""
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pr_number(*payloads: dict[str, Any]) -> int:
    for payload in payloads:
        value = settle_one_pr._coerce_int(payload.get("pr_number") or payload.get("number"))
        if value is not None:
            return value
    return 0


def _title(entry: dict[str, Any], metadata: dict[str, Any]) -> str:
    return str(metadata.get("title") or entry.get("title") or "")


def _head_sha(entry: dict[str, Any], metadata: dict[str, Any]) -> str:
    return str(metadata.get("headRefOid") or entry.get("head_sha") or "")


def _mergeable(metadata: dict[str, Any], entry: dict[str, Any]) -> str:
    return str(metadata.get("mergeable") or entry.get("mergeable") or "").upper()


def _merge_state(metadata: dict[str, Any], entry: dict[str, Any]) -> str:
    return str(metadata.get("mergeStateStatus") or entry.get("mergeStateStatus") or "").upper()


def _tier(entry: dict[str, Any]) -> int | None:
    return settle_one_pr._coerce_int(entry.get("tier"))


def _human_preapproval_recorded(entry: dict[str, Any]) -> bool:
    if bool(entry.get("human_preapproval_recorded")):
        return True
    settlement = entry.get("settlement_creator_pin")
    if isinstance(settlement, dict):
        return bool(settlement.get("verified") and settlement.get("trusted_creator"))
    return False


def _model_authorized(entry: dict[str, Any]) -> bool:
    return (
        bool(entry.get("admin_squash_allowed"))
        and str(entry.get("status") or "") == "satisfied"
        and str(entry.get("verdict") or "") == "admin_squash_allowed"
    )


def _head_drift_reason(entry: dict[str, Any], metadata: dict[str, Any]) -> str | None:
    packet_head = str(entry.get("head_sha") or "")
    live_head = str(metadata.get("headRefOid") or "")
    if packet_head and live_head and packet_head != live_head:
        return f"head drift: packet {packet_head} live {live_head}"
    return None


def _has_nonempty_policy_file_scope(metadata: dict[str, Any]) -> bool:
    files = metadata.get("files")
    return isinstance(files, list) and bool(files)


def _check_name(check: dict[str, Any]) -> str:
    return str(check.get("name") or check.get("context") or "")


def _check_state(check: dict[str, Any]) -> str:
    return str(check.get("state") or check.get("status") or check.get("conclusion") or "").upper()


def _check_success(check: dict[str, Any]) -> bool:
    return _check_state(check) in {"SUCCESS", "SKIPPED", "NEUTRAL", "PASS"}


def _blocked_ready_reasons(metadata: dict[str, Any]) -> tuple[str, ...]:
    reasons: list[str] = []
    review_decision = str(metadata.get("reviewDecision") or "").upper()
    if review_decision == "CHANGES_REQUESTED":
        reasons.append("reviewDecision=CHANGES_REQUESTED")

    if not _has_nonempty_policy_file_scope(metadata):
        reasons.append(POLICY_METADATA_REASON)

    if metadata.get("required_checks_error"):
        reasons.append(f"{REQUIRED_CHECK_METADATA_REASON}: {metadata['required_checks_error']}")
        return tuple(reasons)

    required_checks = metadata.get("required_checks")
    if not isinstance(required_checks, list):
        reasons.append(REQUIRED_CHECK_METADATA_REASON)
        return tuple(reasons)

    by_name: dict[str, dict[str, Any]] = {}
    for check in required_checks:
        if not isinstance(check, dict):
            continue
        name = _check_name(check)
        if name:
            by_name[name] = check

    unexpected = sorted(name for name in by_name if name not in EXPECTED_REQUIRED_CONTEXTS)
    for name in unexpected:
        reasons.append(f"unexpected required context {name}")

    for context in REQUIRED_GREEN_CONTEXTS:
        check = by_name.get(context)
        if check is None:
            reasons.append(f"required context {context} missing")
        elif not _check_success(check):
            reasons.append(f"required context {context} is {_check_state(check) or 'unknown'}")

    quorum_check = by_name.get(MERGE_QUORUM)
    if quorum_check is None:
        reasons.append(f"required context {MERGE_QUORUM} missing")
    elif _check_success(quorum_check):
        reasons.append(f"{MERGE_QUORUM} is not the remaining BLOCKED gate")

    non_success = [
        name
        for name, check in by_name.items()
        if not _check_success(check) and name != MERGE_QUORUM
    ]
    for name in sorted(non_success):
        reasons.append(f"non-quorum required context {name} is {_check_state(by_name[name])}")
    return tuple(dict.fromkeys(reasons))


def classify_pr(
    *,
    entry: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    main_red: bool = False,
    active_owned_prs: set[int] | None = None,
    active_owner_error: str | None = None,
) -> PreflightResult:
    """Classify one PR using read-only metadata and merge-packet fields."""
    entry = dict(entry or {})
    metadata = dict(metadata or {})
    pr_number = _pr_number(entry, metadata)
    active_owned = set(active_owned_prs or set())
    tier = _tier(entry)
    mergeable = _mergeable(metadata, entry)
    merge_state = _merge_state(metadata, entry)
    title = _title(entry, metadata)
    head_sha = _head_sha(entry, metadata)

    def result(verdict: str, action: str, reasons: tuple[str, ...]) -> PreflightResult:
        return PreflightResult(
            pr_number=pr_number,
            verdict=verdict,
            action=action,
            recheck_rule=RECHECK_RULE,
            title=title,
            head_sha=head_sha,
            tier=tier,
            mergeable=mergeable,
            merge_state=merge_state,
            reasons=reasons,
        )

    if main_red:
        return result(
            MAIN_RED_HALT,
            "halt conductor work and enter main-red incident mode",
            ("origin/main required checks are not green",),
        )

    if bool(metadata.get("isDraft") or entry.get("isDraft")):
        return result(
            DRAFT_SKIP,
            "skip this PR until it is marked ready for review",
            ("PR is draft",),
        )

    head_drift = _head_drift_reason(entry, metadata)
    if head_drift:
        return result(
            HEAD_BLOCKED,
            "park this head until the merge packet is regenerated for the live head",
            (head_drift,),
        )

    if active_owner_error:
        return result(
            HEAD_BLOCKED,
            "park this head until active-owner state can be trusted",
            (active_owner_error,),
        )

    if pr_number in active_owned:
        return result(
            HEAD_BLOCKED,
            "park this head because another active lane owns it",
            (ACTIVE_OWNER_REASON,),
        )

    if bool(entry.get("metadata_unavailable") or entry.get("policy_metadata_unavailable")):
        metadata_reasons = tuple(
            str(reason) for reason in entry.get("reasons") or [POLICY_METADATA_REASON]
        )
        return result(
            HEAD_BLOCKED,
            "park this head until fail-closed preflight metadata can be loaded",
            metadata_reasons,
        )

    if not _has_nonempty_policy_file_scope(metadata):
        return result(
            HEAD_BLOCKED,
            "park this head until PR policy metadata includes changed files",
            (POLICY_METADATA_REASON,),
        )

    policy_reasons = settle_one_pr.policy_exclusion_reasons(
        entry, policy_metadata={pr_number: metadata}
    )
    tier_human = tier is not None and tier > 2
    requires_human_risk = bool(
        entry.get("requires_human_risk_settlement")
    ) and not _human_preapproval_recorded(entry)

    if merge_state in {"DIRTY", "BEHIND"} or mergeable == "CONFLICTING":
        return result(
            HEAD_BLOCKED,
            "park this head until conflicts, behind-base state, or current-head blocker clears",
            (f"mergeable={mergeable or 'unknown'} mergeStateStatus={merge_state or 'unknown'}",),
        )

    requires_human_preapproval = bool(
        entry.get("requires_human_preapproval")
    ) and not _human_preapproval_recorded(entry)
    recorded_human_settlement = _human_preapproval_recorded(entry)
    policy_gate_reasons = [
        reason
        for reason in policy_reasons
        if reason != "dirty/conflicting PR"
        and not (recorded_human_settlement and reason == "requires_human_risk_settlement=true")
    ]
    if tier_human or requires_human_risk or requires_human_preapproval or policy_gate_reasons:
        reasons = []
        if tier_human:
            reasons.append(f"Tier {tier}")
        if requires_human_risk:
            reasons.append("requires_human_risk_settlement=true without recorded preapproval")
        if requires_human_preapproval:
            reasons.append("requires_human_preapproval=true without recorded preapproval")
        for reason in policy_gate_reasons:
            if reason not in reasons:
                reasons.append(reason)
        return result(
            HUMAN_GATED,
            "stop and request exact-head human settlement or operator decision before evidence or merge",
            tuple(reasons),
        )

    entry_blockers = settle_one_pr.entry_blockers(entry) if entry else []
    if recorded_human_settlement:
        entry_blockers = [
            blocker
            for blocker in entry_blockers
            if blocker != "requires_human_risk_settlement=true"
        ]
    if entry_blockers:
        return result(
            HEAD_BLOCKED,
            "park this head until the merge-packet blockers are resolved",
            tuple(entry_blockers),
        )

    model_authorized = _model_authorized(entry)
    if model_authorized and (merge_state not in {"CLEAN", "BLOCKED"} or mergeable != "MERGEABLE"):
        return result(
            GITHUB_UNSTABLE,
            "do not merge; wait for GitHub merge state to become settlement-stable",
            (
                f"model-authorized but mergeable={mergeable or 'unknown'} mergeStateStatus={merge_state or 'unknown'}",
            ),
        )

    if model_authorized and mergeable == "MERGEABLE" and merge_state == "BLOCKED":
        blocked_reasons = _blocked_ready_reasons(metadata)
        if blocked_reasons:
            return result(
                HEAD_BLOCKED,
                "park this head until BLOCKED is proven to be quorum-only",
                blocked_reasons,
            )
        return result(
            READY,
            "run exact-head normal protected squash merge after one final live-state check",
            ("model-authorized and BLOCKED only by aragora-merge-quorum",),
        )

    if mergeable == "MERGEABLE" and merge_state == "CLEAN" and model_authorized:
        return result(
            READY,
            "run exact-head normal protected squash merge after one final live-state check",
            ("model-authorized and settlement-stable",),
        )

    return result(
        HEAD_BLOCKED,
        "park this head until it has a satisfied model packet and stable GitHub merge state",
        (f"status={entry.get('status') or 'unknown'} verdict={entry.get('verdict') or 'unknown'}",),
    )


def _packet_entry(packet: dict[str, Any], pr_number: int) -> dict[str, Any]:
    entries = packet.get("entries")
    if not isinstance(entries, list):
        return {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if _pr_number(entry) == pr_number:
            return entry
    return {}


def _packet_unavailable_entry(
    pr_number: int,
    metadata: dict[str, Any],
    exc: RuntimeError,
) -> dict[str, Any]:
    return {
        "pr_number": pr_number,
        "title": metadata.get("title"),
        "head_sha": metadata.get("headRefOid"),
        "status": "packet_unavailable",
        "verdict": "packet_unavailable",
        "reasons": [str(exc)],
    }


def _metadata_unavailable_entry(
    pr_number: int,
    metadata: dict[str, Any],
    prefix: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "pr_number": pr_number,
        "title": metadata.get("title"),
        "head_sha": metadata.get("headRefOid"),
        "status": "metadata_unavailable",
        "verdict": "metadata_unavailable",
        "metadata_unavailable": True,
        "reasons": [f"{prefix}: {reason}"],
    }


def _command_failure_reason(command: dict[str, Any]) -> str:
    for key in ("stderr", "json_error", "stdout"):
        value = str(command.get(key) or "").strip()
        if value:
            return value
    return "files field missing from PR policy metadata"


def _load_live_metadata(
    cwd: Path, repo: str | None, pr_number: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    live_payload, command = settle_one_pr._run_json(
        settle_one_pr._with_repo(
            [
                "gh",
                "pr",
                "view",
                str(pr_number),
                "--json",
                (
                    "number,title,headRefName,headRefOid,isDraft,mergeable,"
                    "mergeStateStatus,reviewDecision,statusCheckRollup"
                ),
            ],
            repo,
        ),
        cwd=cwd,
        timeout=settle_one_pr.GH_METADATA_TIMEOUT_SECONDS,
    )
    return (live_payload if isinstance(live_payload, dict) else {}), command


def _load_required_checks(
    cwd: Path, repo: str | None, pr_number: int
) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
    payload, command = settle_one_pr._run_json(
        settle_one_pr._with_repo(
            [
                "gh",
                "pr",
                "checks",
                str(pr_number),
                "--required",
                "--json",
                "name,state,bucket,workflow,link",
            ],
            repo,
        ),
        cwd=cwd,
        timeout=settle_one_pr.GH_METADATA_TIMEOUT_SECONDS,
    )
    return (payload if isinstance(payload, list) else None), command


def _load_active_owner_scope(cwd: Path) -> tuple[set[int], str | None]:
    active_owned_prs, command = settle_one_pr.load_active_owned_prs(cwd)
    blocker = settle_one_pr.active_owned_snapshot_blocker(command)
    return active_owned_prs, blocker


def _load_single(
    cwd: Path,
    pr_number: int,
    repo: str | None,
    *,
    seed_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = dict(seed_metadata or {})
    live_metadata, live_command = _load_live_metadata(cwd, repo, pr_number)
    metadata.update(live_metadata)
    live_required_fields = {"headRefOid", "isDraft", "mergeable", "mergeStateStatus"}
    if not live_required_fields.issubset(live_metadata):
        return _metadata_unavailable_entry(
            pr_number,
            metadata,
            LIVE_METADATA_REASON,
            _command_failure_reason(live_command),
        ), metadata

    if bool(metadata.get("isDraft")):
        return {}, metadata

    policy_metadata, policy_command = settle_one_pr.load_pr_policy_metadata(
        cwd, pr_number, repo=repo
    )
    metadata.update(policy_metadata)
    if not _has_nonempty_policy_file_scope(policy_metadata):
        return _metadata_unavailable_entry(
            pr_number,
            metadata,
            POLICY_METADATA_REASON,
            _command_failure_reason(policy_command),
        ), metadata

    required_checks, required_command = _load_required_checks(cwd, repo, pr_number)
    if required_checks is None:
        metadata["required_checks_error"] = _command_failure_reason(required_command)
    else:
        metadata["required_checks"] = required_checks

    try:
        packet = settle_one_pr._load_single_pr_packet(cwd=cwd, pr=pr_number, repo=repo)
        entry = _packet_entry(packet, pr_number)
    except RuntimeError as exc:
        entry = _packet_unavailable_entry(pr_number, metadata, exc)
    return entry, metadata


def _classify_single(
    cwd: Path,
    pr_number: int,
    repo: str | None,
    *,
    main_red: bool = False,
    active_owned_prs: set[int] | None = None,
    active_owner_error: str | None = None,
    seed_metadata: dict[str, Any] | None = None,
) -> PreflightResult:
    if main_red:
        return classify_pr(
            entry={"pr_number": pr_number},
            metadata=seed_metadata or {},
            main_red=True,
        )
    entry, metadata = _load_single(cwd, pr_number, repo, seed_metadata=seed_metadata)
    return classify_pr(
        entry=entry,
        metadata=metadata,
        active_owned_prs=active_owned_prs,
        active_owner_error=active_owner_error,
    )


def _open_queue_unavailable_result(command: dict[str, Any]) -> PreflightResult:
    reason = _command_failure_reason(command)
    entry = _metadata_unavailable_entry(0, {}, OPEN_QUEUE_METADATA_REASON, reason)
    return classify_pr(entry=entry, metadata={})


def _has_transport_failure(result: PreflightResult) -> bool:
    return any(
        reason.startswith(prefix)
        for reason in result.reasons
        for prefix in TRANSPORT_FAILURE_PREFIXES
    )


def _exit_code(results: list[PreflightResult]) -> int:
    return 2 if any(_has_transport_failure(result) for result in results) else 0


def _classify_queue(
    cwd: Path,
    repo: str | None,
    limit: int,
    *,
    active_owned_prs: set[int] | None = None,
    active_owner_error: str | None = None,
) -> list[PreflightResult]:
    metadata_by_pr, _command = settle_one_pr.load_open_pr_metadata(cwd, limit=limit, repo=repo)
    if _command.get("returncode") not in (0, None) or _command.get("json_error"):
        return [_open_queue_unavailable_result(_command)]
    results: list[PreflightResult] = []
    for pr_number, metadata in sorted(metadata_by_pr.items()):
        results.append(
            _classify_single(
                cwd,
                pr_number,
                repo,
                active_owned_prs=active_owned_prs,
                active_owner_error=active_owner_error,
                seed_metadata=metadata,
            )
        )
    return results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--pr", type=int, help="Classify one pull request")
    target.add_argument("--queue", action="store_true", help="Classify open pull requests")
    parser.add_argument("--repo", default=None, help="GitHub repo owner/name")
    parser.add_argument("--limit", type=int, default=50, help="Open-PR limit for --queue")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument(
        "--main-red",
        action="store_true",
        help="Classify all targets as MAIN_RED_HALT after an external main-health check",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cwd = Path.cwd()
    active_owned_prs: set[int] = set()
    active_owner_error: str | None = None
    if not args.main_red:
        active_owned_prs, active_owner_error = _load_active_owner_scope(cwd)

    if args.main_red:
        if args.pr is not None:
            results = [
                classify_pr(
                    entry={"pr_number": args.pr},
                    metadata={},
                    main_red=True,
                )
            ]
        else:
            metadata_by_pr, _command = settle_one_pr.load_open_pr_metadata(
                cwd, limit=args.limit, repo=args.repo
            )
            results = [
                classify_pr(
                    entry={
                        "pr_number": pr_number,
                        "title": metadata.get("title"),
                        "head_sha": metadata.get("headRefOid"),
                    },
                    metadata=metadata,
                    main_red=True,
                )
                for pr_number, metadata in sorted(metadata_by_pr.items())
            ]
            if not results:
                results = [classify_pr(entry={}, metadata={}, main_red=True)]
    elif args.pr is not None:
        results = [
            _classify_single(
                cwd,
                args.pr,
                args.repo,
                active_owned_prs=active_owned_prs,
                active_owner_error=active_owner_error,
            )
        ]
    else:
        results = _classify_queue(
            cwd,
            args.repo,
            args.limit,
            active_owned_prs=active_owned_prs,
            active_owner_error=active_owner_error,
        )

    payload = {"results": [result.to_dict() for result in results]}
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for result in results:
            print(f"#{result.pr_number} {result.verdict}: {result.action} ({result.recheck_rule})")
            for reason in result.reasons:
                print(f"  - {reason}")
    return _exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
