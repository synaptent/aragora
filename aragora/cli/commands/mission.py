"""Native Mission CLI commands."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

from aragora.missions import (
    AdmissionPolicy,
    Feature,
    Handoff,
    MissionOrchestrator,
    MissionState,
    ReconcileMode,
    Status,
    WorkArtifact,
)
from aragora.missions.dispatch import BossLoopDispatch
from aragora.missions.intake import IntakeBridgeDispatch, intake_bridge_enabled
from aragora.missions.live_gate import LiveBossLoopGate
from aragora.missions.runtime import MissionRuntimeConfig

logger = logging.getLogger(__name__)

_ACTIONS = {"seed", "status", "run", "resume", "reconcile"}


def cmd_mission(args: argparse.Namespace) -> int:
    """Execute the ``mission`` command."""
    action, goal_words = _normalize_action(args)
    try:
        if action == "seed":
            return _cmd_seed(args, goal_words)
        if action == "status":
            return _cmd_status(args)
        if action == "run":
            return _cmd_run(args, resume=False)
        if action == "resume":
            return _cmd_run(args, resume=True)
        if action == "reconcile":
            return _cmd_reconcile(args)
    except (OSError, ValueError, RuntimeError) as exc:
        logger.exception("mission command failed")
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Error: unknown mission action {action!r}", file=sys.stderr)
    return 2


def _normalize_action(args: argparse.Namespace) -> tuple[str, list[str]]:
    raw = getattr(args, "mission_action", None)
    goal_words = list(getattr(args, "goal", []) or [])
    if raw in _ACTIONS:
        return raw, goal_words
    if raw:
        return "seed", [raw, *goal_words]
    return "seed", goal_words


def _cmd_seed(args: argparse.Namespace, goal_words: list[str]) -> int:
    goal = " ".join(goal_words).strip()
    if not goal:
        raise ValueError("mission seed requires a goal")
    _assert_native_mission_enabled("seed")
    if args.budget is not None and args.budget < 0:
        raise ValueError("budget_usd must be non-negative")
    decision = _admission_decision(args, goal)
    if not decision.allowed:
        raise RuntimeError(f"mission admission blocked: {decision.reason}")
    mission_id = f"mission-{uuid.uuid4().hex[:12]}"
    state_path = _state_path(args, mission_id=mission_id)
    if state_path.exists():
        raise RuntimeError(f"mission state already exists at {state_path}; refusing to overwrite")
    tracks = _tracks(args)
    paths = _paths(args)
    metadata: dict[str, Any] = {
        "budget_usd": args.budget,
        "max_hours": args.max_hours,
        "relay": args.relay,
        "auto_settle_max_tier": args.auto_settle_max_tier,
        "admission_max_unresolved": args.admission_max_unresolved,
        "tracks": tracks,
        "paths": paths,
        "autonomy": args.autonomy,
        "kind": "intake",
    }
    state = MissionState(
        mission_id=mission_id,
        goal=goal,
        milestones=["mission"],
        features=[
            Feature(
                id="mission-intake",
                description=goal,
                milestone="mission",
                metadata=metadata,
            )
        ],
    )
    state.save(state_path)
    print(f"Seeded mission {mission_id}: {goal}")
    print(f"State: {state_path}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    state = MissionState.load(_state_path(args))
    done, total = state.progress()
    blocked = sum(1 for feature in state.features if feature.status == Status.BLOCKED)
    parked = sum(1 for feature in state.features if feature.status == Status.PARKED)
    terminal = sum(1 for feature in state.features if feature.status == Status.TERMINAL)
    in_progress = sum(1 for feature in state.features if feature.status == Status.IN_PROGRESS)
    awaiting = sum(1 for feature in state.features if feature.status == Status.AWAITING_CLAIM)
    print(f"Mission {state.mission_id}: {state.goal}")
    print(
        f"Progress: {done}/{total} completed, {awaiting} awaiting claim, "
        f"{blocked} blocked, {parked} parked, "
        f"{terminal} terminal, {in_progress} in progress"
    )
    for feature in state.features:
        print(f"  - {feature.id}: {feature.status} ({feature.milestone}) {feature.description}")
    return 0


def _cmd_run(args: argparse.Namespace, *, resume: bool) -> int:
    _assert_native_mission_enabled("run")
    state_path = _state_path(args)
    _assert_not_paused(state_path)
    if args.autonomy != "auto-drain":
        state = MissionState.load(state_path)
        done, total = state.progress()
        print(f"Mission run ({args.autonomy}): no dispatch performed; {done}/{total} completed")
        return 0 if done == total else 1
    if resume:
        print("Resume requested; reclaim is handled under the mission owner lock.")
    dispatch = _dispatch_for(args, state_path=state_path)
    done, total = MissionOrchestrator(state_path).run(dispatch, max_ticks=args.max_ticks)
    print(f"Mission run: {done}/{total} completed")
    return 0 if done == total else 1


def _assert_not_paused(state_path: Path) -> None:
    pause_files = [
        state_path.with_name("PAUSED"),
        Path(".aragora") / "missions" / "PAUSED",
    ]
    for pause_file in pause_files:
        if pause_file.exists():
            reason = pause_file.read_text(encoding="utf-8").strip()
            detail = f": {reason}" if reason else ""
            raise RuntimeError(f"mission is paused by {pause_file}{detail}")


def _cmd_reconcile(args: argparse.Namespace) -> int:
    _assert_native_mission_enabled("reconcile")
    mode = ReconcileMode(args.autonomy)
    artifacts = _load_artifacts(
        args,
        include_github=mode == ReconcileMode.AUTO_DRAIN,
        repo_root=_repo_root_for(args, None),
    )
    report = mode.run(artifacts)
    if args.json:
        print(report.to_json())
    else:
        print(f"Reconcile mode: {report.mode}")
        print(f"Artifacts: {len(report.items)}")
        print(f"Authorized cleanup (not executed): {len(report.authorized_cleanup)}")
        print(f"Authorized auto-drain (not executed): {len(report.authorized_auto_drain)}")
        print(f"Parked: {len(report.parked)}")
        for item in report.parked:
            print(f"  - {item.artifact_id}: {item.category.value} ({item.reason})")
    return 0


def _dispatch_for(args: argparse.Namespace, *, state_path: Path | None = None):
    if args.autonomy == "auto-drain":
        base = "origin/main"
        gate = LiveBossLoopGate(repo_root=_repo_root_for(args, state_path), base=base)
        receipt_dir = state_path.parent / "receipts" if state_path is not None else None
        dispatch = BossLoopDispatch(
            gate,
            base=base,
            operator_tier=_operator_tier_for(args, state_path),
            receipt_dir=receipt_dir,
        )
        if intake_bridge_enabled():
            # Seeded intake features get decomposed into child features born in
            # the claimable AWAITING_CLAIM state (#8758): auto-drain leaves them
            # for the worker/lease machinery (select_for) with no retry burn and
            # no BLOCKED children, and the merge gate is never invoked on a
            # nonexistent ref. Kill-switch:
            # ARAGORA_DISABLE_MISSION_INTAKE_BRIDGE=1 restores park-on-intake.
            return IntakeBridgeDispatch(dispatch)
        return dispatch

    def report_dispatch(feature: Feature) -> Handoff:
        return Handoff(
            success=False,
            terminal=True,
            blocked_reason=(
                f"{args.autonomy} autonomy does not dispatch feature {feature.id}; "
                "use mission reconcile for reporting or auto-drain for gated head-bound merges"
            ),
            discovered=[f"{args.autonomy} mission dispatch parked without live head mutation"],
        )

    return report_dispatch


def _assert_native_mission_enabled(action: str) -> None:
    from aragora.config.feature_flags import FeatureFlagRegistry

    runtime_enabled = MissionRuntimeConfig.from_env().enables_native_mission_flag
    registry_enabled = FeatureFlagRegistry().is_enabled("enable_native_mission")
    if not (runtime_enabled or registry_enabled):
        raise RuntimeError(
            f"Native mission engine is disabled for mission {action} "
            "(set ARAGORA_ENABLE_NATIVE_MISSION=1 to opt in)."
        )


def _admission_decision(args: argparse.Namespace, goal: str):
    artifacts = _load_artifacts(
        args,
        include_github=True,
        repo_root=_repo_root_for(args, None),
    )
    report = ReconcileMode.REPORT.run(artifacts)
    return AdmissionPolicy(max_unresolved=max(0, int(args.admission_max_unresolved))).evaluate(
        goal,
        report,
    )


def _operator_tier_for(args: argparse.Namespace, state_path: Path | None) -> int:
    auto_settle_max_tier = int(args.auto_settle_max_tier)
    if state_path is not None and state_path.exists():
        state = MissionState.load(state_path)
        for feature in state.features:
            raw = feature.metadata.get("auto_settle_max_tier")
            if raw is None:
                continue
            try:
                auto_settle_max_tier = min(auto_settle_max_tier, int(raw))
            except (TypeError, ValueError):
                continue
    return min(int(args.operator_tier), auto_settle_max_tier + 1)


def _repo_root_for(args: argparse.Namespace, state_path: Path | None) -> Path:
    explicit = getattr(args, "repo_root", None)
    if explicit:
        return Path(explicit).expanduser().resolve()

    if state_path is not None:
        state_root = _nearest_git_root(state_path.expanduser().resolve().parent)
        if state_root is not None:
            return state_root

    cwd_root = _nearest_git_root(Path.cwd())
    if cwd_root is not None:
        return cwd_root

    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=Path.cwd(),
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"git rev-parse timed out after {exc.timeout}s") from exc
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    raise RuntimeError("could not resolve repository root for mission auto-drain")


def _nearest_git_root(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _state_path(args: argparse.Namespace, *, mission_id: str | None = None) -> Path:
    if getattr(args, "state", None):
        return Path(args.state)
    if mission_id is None:
        raise ValueError("--state is required for this mission action")
    return Path(".aragora") / "missions" / mission_id / "state.json"


def _tracks(args: argparse.Namespace) -> list[str]:
    raw = getattr(args, "tracks", None)
    if not raw:
        return []
    return [track.strip() for track in raw.split(",") if track.strip()]


def _paths(args: argparse.Namespace) -> list[str]:
    raw = getattr(args, "paths", None)
    if not raw:
        return []
    return [path.strip().lstrip("./") for path in raw.split(",") if path.strip()]


def _load_artifacts(
    args: argparse.Namespace, *, include_github: bool, repo_root: Path
) -> list[WorkArtifact]:
    if getattr(args, "artifact_fixture", None):
        payload = json.loads(Path(args.artifact_fixture).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("--artifact-fixture must contain a JSON list")
        return [WorkArtifact.from_dict(item) for item in payload]
    return _load_live_inventory_artifacts(
        limit=args.limit,
        include_github=include_github,
        repo_root=repo_root,
    )


def _load_live_inventory_artifacts(
    *, limit: int, include_github: bool, repo_root: Path
) -> list[WorkArtifact]:
    cmd = [
        sys.executable,
        "scripts/codex_worktree_value_inventory.py",
        "--repo",
        str(repo_root),
        "--limit",
        str(limit),
        "--size-mode",
        "none",
        "--dry-run",
        "--json",
    ]
    if not include_github:
        cmd.insert(-2, "--skip-gh")
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"codex_worktree_value_inventory.py timed out after {exc.timeout}s"
        ) from exc
    if proc.returncode != 0:
        raise RuntimeError(
            (proc.stderr or proc.stdout or "codex_worktree_value_inventory.py failed").strip()
        )
    payload = json.loads(proc.stdout)
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        return []
    artifacts: list[WorkArtifact] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        artifact = _artifact_from_inventory(candidate)
        if include_github:
            artifact = _artifact_with_merge_packet_fields(
                artifact,
                candidate,
                repo_root=repo_root,
            )
        artifacts.append(artifact)
    return artifacts


def _artifact_from_inventory(candidate: dict[str, Any]) -> WorkArtifact:
    raw_git = candidate.get("git")
    raw_links = candidate.get("links")
    raw_safety = candidate.get("cleanup_safety")
    raw_proof = candidate.get("proof")
    git: dict[str, Any] = raw_git if isinstance(raw_git, dict) else {}
    links: dict[str, Any] = raw_links if isinstance(raw_links, dict) else {}
    safety: dict[str, Any] = raw_safety if isinstance(raw_safety, dict) else {}
    classification = str(candidate.get("classification") or "")
    open_prs = links.get("open_prs") if isinstance(links.get("open_prs"), list) else []
    proof: list[Any] = raw_proof if isinstance(raw_proof, list) else []
    clean = False if git.get("dirty") else True
    already_merged = bool(safety.get("safe_to_delete")) and classification in {
        "patch_equivalent_or_merged",
        "no_git_cache_residue",
        "unregistered_git_residue",
    }
    return WorkArtifact(
        artifact_id=str(candidate.get("candidate_id") or candidate.get("path") or "unknown"),
        kind="worktree",
        clean=clean,
        already_merged=already_merged,
        open_pr=classification == "open_pr_or_outbox" or bool(open_prs),
        owner_active=bool(candidate.get("active_session") or candidate.get("lock_files")),
        unique_commits=classification == "unique_unharvested",
        represented_elsewhere=classification in {"patch_equivalent_or_merged", "receipt_protected"},
        superseded=classification == "superseded",
        evidence=[str(item) for item in proof],
    )


def _artifact_with_merge_packet_fields(
    artifact: WorkArtifact,
    candidate: dict[str, Any],
    *,
    repo_root: Path | None = None,
    repo_slug: str = "synaptent/aragora",
) -> WorkArtifact:
    pr_number = _first_open_pr_number(candidate)
    if pr_number is None:
        return artifact
    packet = _merge_packet_for_pr(pr_number, repo_root=repo_root, repo_slug=repo_slug)
    entry = _first_packet_entry(packet, pr_number)
    if entry is None:
        return artifact
    tier = _int_or_none(entry.get("tier"))
    head_sha = str(entry.get("head_sha") or entry.get("headRefOid") or "").strip() or None
    candidate_head = _candidate_head_sha(candidate)
    if head_sha and not candidate_head:
        evidence = [
            *artifact.evidence,
            f"merge-packet PR {pr_number}: parked because inventory omitted candidate head for packet head {head_sha}",
        ]
        return replace(
            artifact,
            tier=tier,
            head_sha=head_sha,
            checks_green=False,
            quorum_satisfied=False,
            evidence=evidence,
        )
    if candidate_head and head_sha and candidate_head != head_sha:
        evidence = [
            *artifact.evidence,
            f"merge-packet PR {pr_number}: parked because inventory head {candidate_head} != packet head {head_sha}",
        ]
        return replace(
            artifact,
            tier=tier,
            head_sha=candidate_head,
            checks_green=False,
            quorum_satisfied=False,
            evidence=evidence,
        )
    squash_allowed = _packet_allows_auto_drain(entry)
    evidence = [
        *artifact.evidence,
        f"merge-packet PR {pr_number}: {entry.get('status', 'unknown')} / {entry.get('verdict', 'unknown')}",
    ]
    return replace(
        artifact,
        tier=tier,
        head_sha=head_sha,
        checks_green=_packet_checks_green(entry),
        quorum_satisfied=squash_allowed,
        evidence=evidence,
    )


def _candidate_head_sha(candidate: dict[str, Any]) -> str | None:
    for key in (
        "candidate_head_sha",
        "head_sha",
        "headRefOid",
        "source_head_sha",
        "sha",
        "commit",
    ):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    raw_git = candidate.get("git")
    git = raw_git if isinstance(raw_git, dict) else {}
    for key in ("head", "head_sha", "headRefOid", "sha", "commit"):
        value = str(git.get(key) or "").strip()
        if value:
            return value
    return None


def _first_open_pr_number(candidate: dict[str, Any]) -> int | None:
    links = candidate.get("links")
    if not isinstance(links, dict):
        return None
    open_prs = links.get("open_prs")
    if not isinstance(open_prs, list) or not open_prs:
        return None
    first = open_prs[0]
    if not isinstance(first, dict):
        return None
    return _int_or_none(first.get("number"))


def _merge_packet_for_pr(
    pr_number: int,
    *,
    repo_root: Path | None = None,
    repo_slug: str = "synaptent/aragora",
) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "aragora.cli.main",
                "review-queue",
                "merge-packet",
                "--pr",
                str(pr_number),
                "--repo",
                repo_slug,
                "--json",
            ],
            cwd=repo_root or Path.cwd(),
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {}
    if proc.returncode != 0:
        return {}
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_packet_entry(packet: dict[str, Any], pr_number: int) -> dict[str, Any] | None:
    candidates: list[Any] = []
    for key in ("entries", "ready", "not_ready", "items"):
        value = packet.get(key)
        if isinstance(value, list):
            candidates.extend(value)
    if not candidates and packet:
        candidates.append(packet)
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if _int_or_none(item.get("pr_number", item.get("number"))) == pr_number:
            return item
    return None


def _packet_checks_green(entry: dict[str, Any]) -> bool:
    surfaces = entry.get("check_surfaces")
    required = surfaces.get("required_pr_checks") if isinstance(surfaces, dict) else None
    summary = ""
    if isinstance(required, dict):
        summary = str(required.get("summary") or "").lower()
    if not summary:
        summary = str(entry.get("checks_summary") or "").lower()
    return (
        bool(summary)
        and "green" in summary
        and "failing" not in summary
        and "pending" not in summary
    )


def _packet_allows_auto_drain(entry: dict[str, Any]) -> bool:
    if str(entry.get("status") or "").lower() != "satisfied":
        return False
    if str(entry.get("verdict") or "").lower() != "admin_squash_allowed":
        return False
    if entry.get("admin_squash_allowed") is not True:
        return False
    for blocker in (
        "requires_human_risk_settlement",
        "requires_human_preapproval",
        "unresolved_dissent",
    ):
        if entry.get(blocker) is not False:
            return False
    return True


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
