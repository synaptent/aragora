from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, cast

from aragora.nomic.dev_coordination import (
    DevCoordinationStore,
    IntegrationDecisionType,
    LeaseStatus,
)
from aragora.swarm.tranche import (
    DEFAULT_TRANCHE_MANIFEST_DIR,
    TrancheArtifactStore,
    TrancheLaneArtifact,
)
from aragora.swarm.tranche_state import (
    LANE_STATUS_ABORTED,
    LANE_STATUS_COMPLETED,
    LANE_STATUS_DISPATCHED,
    LANE_STATUS_NEEDS_HUMAN,
    LANE_STATUS_PENDING,
    LANE_STATUS_PREPARING,
    LANE_STATUS_RETRYING,
    LANE_STATUS_REVIEW_FAILED,
    LANE_STATUS_REVIEW_PASSED,
    LANE_STATUS_REVIEWING,
    LANE_STATUS_RUNNING,
    LANE_STATUS_WAITING_FOR_MERGE,
    LANE_STATUS_WAITING_FOR_PR,
    TRANCHE_STATUS_ABORTED,
    TRANCHE_STATUS_COMPLETED,
    TRANCHE_STATUS_INTEGRATING,
    TRANCHE_STATUS_NEEDS_HUMAN,
    TRANCHE_STATUS_PLANNED,
    TRANCHE_STATUS_PREPARING,
    TRANCHE_STATUS_REVIEWING,
    TRANCHE_STATUS_RUNNING,
    LaneRunState,
    TrancheRunState,
    _utcnow,
)

logger = logging.getLogger(__name__)


class DriverAlreadyClaimedError(RuntimeError):
    """Raised when another session already holds the tranche driver lease."""


def claim_driver(
    state: TrancheRunState,
    *,
    session_id: str,
    takeover_timeout_seconds: float = 300.0,
) -> TrancheRunState:
    refreshed = TrancheRunState.from_dict(state.to_dict())
    session = _optional_text(session_id)
    if not session:
        raise ValueError("session_id is required")
    now = _utcnow()

    active_session = _optional_text(refreshed.driver_session)
    active_heartbeat = refreshed.driver_heartbeat
    if active_session and active_session != session and active_heartbeat is not None:
        age = (now - active_heartbeat).total_seconds()
        if age < float(takeover_timeout_seconds):
            raise DriverAlreadyClaimedError(
                f"driver already claimed by {active_session} ({age:.1f}s old heartbeat)"
            )
        _close_session_history(refreshed, active_session, now=now)

    if active_session == session:
        refreshed.driver_heartbeat = now
        refreshed.updated_at = now
        return refreshed

    refreshed.driver_session = session
    refreshed.driver_heartbeat = now
    refreshed.updated_at = now
    refreshed.session_history.append(
        {
            "session_id": session,
            "attached_at": now.isoformat(),
            "detached_at": None,
            "mode": "driver",
        }
    )
    return refreshed


def release_driver(
    state: TrancheRunState,
    *,
    session_id: str | None = None,
) -> TrancheRunState:
    refreshed = TrancheRunState.from_dict(state.to_dict())
    session = _optional_text(session_id) or _optional_text(refreshed.driver_session)
    now = _utcnow()
    if session and _optional_text(refreshed.driver_session) == session:
        refreshed.driver_session = None
        refreshed.driver_heartbeat = None
        refreshed.updated_at = now
        _close_session_history(refreshed, session, now=now)
    return refreshed


def heartbeat_driver(
    state: TrancheRunState,
    *,
    session_id: str,
) -> TrancheRunState:
    refreshed = TrancheRunState.from_dict(state.to_dict())
    session = _optional_text(session_id)
    if not session:
        raise ValueError("session_id is required")
    if _optional_text(refreshed.driver_session) != session:
        raise DriverAlreadyClaimedError(
            f"driver is held by {_optional_text(refreshed.driver_session) or 'no session'}"
        )
    now = _utcnow()
    refreshed.driver_heartbeat = now
    refreshed.updated_at = now
    return refreshed


def refresh_tranche_state(
    state: TrancheRunState,
    *,
    artifacts: dict[str, TrancheLaneArtifact] | None = None,
    artifact_store: TrancheArtifactStore | None = None,
    store: DevCoordinationStore | Any | None = None,
    repo_root: Path | None = None,
) -> TrancheRunState:
    refreshed = TrancheRunState.from_dict(state.to_dict())
    if str(refreshed.status or "").strip() == TRANCHE_STATUS_ABORTED:
        refreshed.updated_at = _utcnow()
        return refreshed

    resolved_store = store
    if resolved_store is None and repo_root is not None:
        resolved_store = DevCoordinationStore(repo_root=Path(repo_root).resolve())

    artifact_map = _resolve_artifacts(
        refreshed.manifest_id,
        artifacts=artifacts,
        artifact_store=artifact_store,
        repo_root=repo_root,
    )

    for lane_id, lane_state in list(refreshed.lane_states.items()):
        artifact = artifact_map.get(lane_id)
        if artifact is not None:
            _apply_artifact_projection(lane_state, artifact)

        run_dict = _get_supervisor_run(resolved_store, lane_state.run_id)
        if run_dict is not None:
            _apply_run_projection(lane_state, run_dict)

    lease_map = _lease_map(
        resolved_store,
        lease_ids={
            lease_id
            for lane_state in refreshed.lane_states.values()
            if (lease_id := _optional_text(lane_state.lease_id))
        },
    )

    for lane_state in refreshed.lane_states.values():
        lease = lease_map.get(str(lane_state.lease_id or "").strip())
        if lease is not None:
            _apply_lease_projection(lane_state, lease)

        receipt = _get_completion_receipt(resolved_store, lane_state.receipt_id)
        if receipt is not None:
            _apply_receipt_projection(lane_state, receipt)

        decision = _latest_integration_decision(resolved_store, lane_state.receipt_id)
        if decision is not None:
            _apply_integration_projection(lane_state, decision)

        lane_state.last_updated = _utcnow()

    refreshed.status = _aggregate_tranche_status(
        refreshed.lane_states.values(), current=refreshed.status
    )
    refreshed.updated_at = _utcnow()
    return refreshed


async def watch_tick(
    state: TrancheRunState,
    *,
    manifest: Any,
    autonomy_mode: str | None = None,
    artifact_store: TrancheArtifactStore | None = None,
    artifacts: dict[str, TrancheLaneArtifact] | None = None,
    store: DevCoordinationStore | Any | None = None,
    repo_root: Path | None = None,
    run_fn: Any | None = None,
    review_fn: Any | None = None,
    integrate_fn: Any | None = None,
) -> TrancheRunState:
    mode = str(autonomy_mode or state.autonomy_mode or "adaptive").strip().lower() or "adaptive"
    resolved_store = store
    if resolved_store is None and repo_root is not None:
        resolved_store = DevCoordinationStore(repo_root=Path(repo_root).resolve())
    await _collect_and_refresh_supervisor_runs(
        state,
        store=resolved_store,
        repo_root=repo_root,
        artifact_store=artifact_store,
    )
    artifact_map = _resolve_artifacts(
        state.manifest_id,
        artifacts=artifacts,
        artifact_store=artifact_store,
        repo_root=repo_root,
    )
    refreshed = refresh_tranche_state(
        state,
        artifacts=artifact_map,
        artifact_store=artifact_store,
        store=resolved_store,
        repo_root=repo_root,
    )

    if mode in {"adaptive", "fire_and_forget"}:
        if run_fn is not None and _should_attempt_dispatch(refreshed, store=resolved_store):
            dispatch_payload = await run_fn(manifest=manifest)
            _apply_dispatch_payload(refreshed, dispatch_payload)
            artifact_map = _resolve_artifacts(
                state.manifest_id,
                artifacts=artifacts,
                artifact_store=artifact_store,
                repo_root=repo_root,
            )
            refreshed = refresh_tranche_state(
                refreshed,
                artifacts=artifact_map,
                artifact_store=artifact_store,
                store=resolved_store,
                repo_root=repo_root,
            )
        for lane_id, lane_state in refreshed.lane_states.items():
            artifact = artifact_map.get(lane_id)
            if (
                lane_state.status == LANE_STATUS_COMPLETED
                and review_fn is not None
                and not _completed_lane_is_terminal(lane_state, store=resolved_store)
            ):
                lane_state.status = LANE_STATUS_REVIEWING
                review_payload = await review_fn(
                    manifest=manifest,
                    lane_id=lane_id,
                    artifact=artifact,
                )
                _persist_review_payload(
                    state.manifest_id,
                    artifact=artifact,
                    review_payload=review_payload,
                    artifact_store=artifact_store,
                )
                review_status = str(
                    review_payload.get("status", "") if isinstance(review_payload, dict) else ""
                ).strip()
                lane_state.status = _watch_review_status(review_status)
            if (
                lane_state.status
                in {
                    LANE_STATUS_REVIEW_PASSED,
                    LANE_STATUS_WAITING_FOR_PR,
                    LANE_STATUS_WAITING_FOR_MERGE,
                }
                and integrate_fn is not None
            ):
                integrate_payload = await integrate_fn(
                    manifest=manifest,
                    lane_id=lane_id,
                    artifact=artifact,
                    approve=(mode == "fire_and_forget"),
                    run_state=refreshed,
                )
                if isinstance(integrate_payload, dict):
                    _apply_cascade_report_to_state(
                        refreshed,
                        integrate_payload.get("cascade_report"),
                    )
                lane_state.status = _watch_integrate_status(
                    lane_state.status,
                    integrate_payload if isinstance(integrate_payload, dict) else {},
                )

    refreshed.status = _aggregate_tranche_status(
        refreshed.lane_states.values(), current=refreshed.status
    )
    refreshed.updated_at = _utcnow()
    return refreshed


async def watch_loop(
    state: TrancheRunState,
    *,
    manifest: Any,
    interval_seconds: float = 10.0,
    max_ticks: int | None = None,
    state_path: str | Path | None = None,
    driver_session_id: str | None = None,
    **kwargs: Any,
) -> TrancheRunState:
    current = TrancheRunState.from_dict(state.to_dict())
    if current.status == TRANCHE_STATUS_ABORTED:
        return current
    ticks = 0
    while True:
        if driver_session_id:
            current = heartbeat_driver(current, session_id=driver_session_id)
        current = await watch_tick(current, manifest=manifest, **kwargs)
        if driver_session_id:
            current = heartbeat_driver(current, session_id=driver_session_id)
        if state_path is not None:
            current.save(state_path)
        if current.status in {
            TRANCHE_STATUS_ABORTED,
            TRANCHE_STATUS_COMPLETED,
            TRANCHE_STATUS_NEEDS_HUMAN,
        }:
            return current
        ticks += 1
        if max_ticks is not None and ticks >= max(1, int(max_ticks)):
            return current
        await asyncio.sleep(max(0.0, float(interval_seconds)))


def run_state_path_for_manifest(manifest_path: str | Path) -> Path:
    return Path(manifest_path).resolve().with_name("run_state.yaml")


def load_tranche_run_state(manifest_path: str | Path) -> TrancheRunState:
    return TrancheRunState.load(run_state_path_for_manifest(manifest_path))


def list_tranche_states(repo_root: Path) -> list[dict[str, Any]]:
    root = (Path(repo_root).resolve() / DEFAULT_TRANCHE_MANIFEST_DIR).resolve()
    if not root.exists():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/run_state.yaml")):
        try:
            state = TrancheRunState.load(path)
        except (OSError, ValueError):
            continue
        results.append(
            {
                "manifest_id": state.manifest_id,
                "status": state.status,
                "autonomy_mode": state.autonomy_mode,
                "driver_session": state.driver_session,
                "driver_heartbeat": (
                    state.driver_heartbeat.isoformat() if state.driver_heartbeat else None
                ),
                "lane_states": {
                    lane_id: lane.to_dict() for lane_id, lane in sorted(state.lane_states.items())
                },
                "path": str(path),
                "updated_at": state.updated_at.isoformat(),
            }
        )
    return results


def _resolve_artifacts(
    manifest_id: str,
    *,
    artifacts: dict[str, TrancheLaneArtifact] | None,
    artifact_store: TrancheArtifactStore | None,
    repo_root: Path | None,
) -> dict[str, TrancheLaneArtifact]:
    if artifacts is not None:
        return {
            str(lane_id): artifact
            for lane_id, artifact in artifacts.items()
            if artifact is not None
        }
    store = artifact_store
    if store is None and repo_root is not None:
        store = TrancheArtifactStore(repo_root=Path(repo_root).resolve())
    if store is None:
        return {}
    return {item.lane_id: item for item in store.list(manifest_id)}


async def _collect_and_refresh_supervisor_runs(
    state: TrancheRunState,
    *,
    store: Any | None,
    repo_root: Path | None,
    artifact_store: TrancheArtifactStore | Any | None = None,
) -> None:
    if store is None or repo_root is None:
        return
    run_ids = {
        run_id
        for lane_state in state.lane_states.values()
        if (run_id := _optional_text(lane_state.run_id))
    }
    if not run_ids:
        return
    from aragora.swarm.supervisor import SwarmSupervisor

    supervisor = SwarmSupervisor(repo_root=Path(repo_root).resolve(), store=store)
    for run_id in sorted(run_ids):
        try:
            await supervisor.collect_finished_results(run_id)
        except KeyError:
            continue
        except Exception as exc:
            logger.warning(
                "watch_tick failed collecting finished results for run %s: %s",
                run_id,
                exc,
            )
        try:
            refreshed = supervisor.refresh_run(run_id)
        except KeyError:
            continue
        except Exception as exc:
            logger.warning("watch_tick failed refreshing run %s: %s", run_id, exc)
            continue
        _sync_artifacts_from_supervisor_run(
            state,
            run_dict=refreshed.to_dict() if hasattr(refreshed, "to_dict") else {},
            artifact_store=artifact_store,
        )


def _apply_artifact_projection(lane_state: LaneRunState, artifact: TrancheLaneArtifact) -> None:
    lane_state.status = str(artifact.status or lane_state.status).strip() or lane_state.status
    lane_state.run_id = _prefer_text(lane_state.run_id, artifact.run_id)
    lane_state.worktree_path = _prefer_text(lane_state.worktree_path, artifact.worktree_path)
    metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
    lane_state.receipt_id = _prefer_text(lane_state.receipt_id, metadata.get("receipt_id"))
    lane_state.lease_id = _prefer_text(lane_state.lease_id, metadata.get("lease_id"))
    lane_state.pr_url = _prefer_text(lane_state.pr_url, _artifact_pr_url(artifact))
    blocked_reason = _artifact_blocked_reason(artifact)
    blocking_question = _artifact_blocking_question(artifact)
    if blocked_reason or blocking_question or lane_state.status != LANE_STATUS_NEEDS_HUMAN:
        lane_state.set_blocker(reason=blocked_reason, question=blocking_question)


def _apply_run_projection(lane_state: LaneRunState, run_dict: dict[str, Any]) -> None:
    run_status = str(run_dict.get("status", "")).strip().lower()
    has_deliverable = False
    has_scope_violation = False
    for work_order in run_dict.get("work_orders", []):
        if not isinstance(work_order, dict):
            continue
        has_deliverable = has_deliverable or _work_order_has_deliverable(work_order)
        has_scope_violation = has_scope_violation or _work_order_has_scope_violation(work_order)
        lane_state.worktree_path = _prefer_text(
            lane_state.worktree_path, work_order.get("worktree_path")
        )
        lane_state.receipt_id = _prefer_text(lane_state.receipt_id, work_order.get("receipt_id"))
        lane_state.lease_id = _prefer_text(lane_state.lease_id, work_order.get("lease_id"))
        lane_state.pr_url = _prefer_text(
            lane_state.pr_url,
            work_order.get("pr_url") or work_order.get("adopted_pr"),
        )
        lane_state.set_blocker(
            reason=_prefer_text(
                lane_state.blocked_reason,
                work_order.get("failure_reason")
                or ("scope_violation" if _work_order_has_scope_violation(work_order) else None),
            ),
            question=_prefer_text(
                lane_state.blocking_question,
                work_order.get("blocking_question"),
            ),
        )
        if lane_state.run_id:
            break

    if has_scope_violation:
        lane_state.status = LANE_STATUS_NEEDS_HUMAN
        lane_state.set_blocker(
            reason=lane_state.blocked_reason or "scope_violation",
            question=lane_state.blocking_question
            or "Which files should stay in scope, or should this lane be split before rerunning?",
        )
        return

    mapped = {
        "planned": LANE_STATUS_PENDING,
        "active": LANE_STATUS_RUNNING,
        "completed": lane_state.status,
        "needs_human": (LANE_STATUS_COMPLETED if has_deliverable else LANE_STATUS_NEEDS_HUMAN),
    }.get(run_status)
    if mapped and lane_state.status in {
        LANE_STATUS_PENDING,
        LANE_STATUS_DISPATCHED,
        LANE_STATUS_RUNNING,
    }:
        lane_state.status = mapped


def _apply_lease_projection(lane_state: LaneRunState, lease: Any) -> None:
    lane_state.worktree_path = _prefer_text(
        lane_state.worktree_path, getattr(lease, "worktree_path", None)
    )
    lease_status = str(getattr(lease, "status", "")).strip()
    if lease_status == LeaseStatus.ACTIVE.value and lane_state.status in {
        LANE_STATUS_PENDING,
        LANE_STATUS_DISPATCHED,
    }:
        lane_state.status = LANE_STATUS_RUNNING
    elif lease_status == LeaseStatus.EXPIRED.value:
        lane_state.status = LANE_STATUS_NEEDS_HUMAN
        lane_state.set_blocker(
            reason=lane_state.blocked_reason or "lease_expired",
            question=lane_state.blocking_question
            or "Should this lane reclaim a fresh lease before it is rerun?",
        )
    elif lease_status == LeaseStatus.COMPLETED.value and lane_state.status in {
        LANE_STATUS_PENDING,
        LANE_STATUS_DISPATCHED,
        LANE_STATUS_RUNNING,
    }:
        lane_state.status = LANE_STATUS_COMPLETED


def _apply_receipt_projection(lane_state: LaneRunState, receipt: Any) -> None:
    lane_state.receipt_id = _prefer_text(
        lane_state.receipt_id, getattr(receipt, "receipt_id", None)
    )
    lane_state.lease_id = _prefer_text(lane_state.lease_id, getattr(receipt, "lease_id", None))
    lane_state.worktree_path = _prefer_text(
        lane_state.worktree_path,
        getattr(receipt, "worktree_path", None),
    )
    lane_state.pr_url = _prefer_text(lane_state.pr_url, getattr(receipt, "pr_url", None))
    if lane_state.status == LANE_STATUS_REVIEW_PASSED:
        lane_state.status = (
            LANE_STATUS_WAITING_FOR_MERGE if lane_state.pr_url else LANE_STATUS_WAITING_FOR_PR
        )


def _apply_integration_projection(lane_state: LaneRunState, decision: Any) -> None:
    value = str(getattr(decision, "decision", "")).strip()
    if value in {IntegrationDecisionType.MERGE.value, IntegrationDecisionType.CHERRY_PICK.value}:
        if lane_state.status == LANE_STATUS_COMPLETED:
            return
        lane_state.status = (
            LANE_STATUS_WAITING_FOR_MERGE if lane_state.pr_url else LANE_STATUS_WAITING_FOR_PR
        )
    elif value in {
        IntegrationDecisionType.REQUEST_CHANGES.value,
        IntegrationDecisionType.DISCARD.value,
        IntegrationDecisionType.SALVAGE.value,
    }:
        lane_state.status = LANE_STATUS_NEEDS_HUMAN
        lane_state.set_blocker(
            reason=lane_state.blocked_reason or f"integration_{value}",
            question=lane_state.blocking_question
            or "What integration change is required before this lane can proceed?",
        )
    elif (
        value == IntegrationDecisionType.PENDING_REVIEW.value
        and lane_state.status == LANE_STATUS_REVIEW_PASSED
    ):
        lane_state.status = (
            LANE_STATUS_WAITING_FOR_MERGE if lane_state.pr_url else LANE_STATUS_WAITING_FOR_PR
        )


def _aggregate_tranche_status(
    lane_states: Any,
    *,
    current: str,
) -> str:
    statuses = {str(item.status).strip() for item in lane_states if getattr(item, "status", None)}
    if not statuses:
        return current or TRANCHE_STATUS_PLANNED
    if statuses <= {LANE_STATUS_COMPLETED}:
        return TRANCHE_STATUS_COMPLETED
    if statuses & {LANE_STATUS_NEEDS_HUMAN, LANE_STATUS_REVIEW_FAILED, LANE_STATUS_ABORTED}:
        return TRANCHE_STATUS_NEEDS_HUMAN
    if statuses & {LANE_STATUS_WAITING_FOR_PR, LANE_STATUS_WAITING_FOR_MERGE}:
        return TRANCHE_STATUS_INTEGRATING
    if statuses & {
        LANE_STATUS_REVIEWING,
        LANE_STATUS_REVIEW_PASSED,
        LANE_STATUS_RETRYING,
    }:
        return TRANCHE_STATUS_REVIEWING
    if statuses & {LANE_STATUS_PREPARING}:
        return TRANCHE_STATUS_PREPARING
    if statuses & {LANE_STATUS_DISPATCHED, LANE_STATUS_RUNNING, LANE_STATUS_COMPLETED}:
        return TRANCHE_STATUS_RUNNING
    return current or TRANCHE_STATUS_PLANNED


def _artifact_pr_url(artifact: TrancheLaneArtifact) -> str | None:
    metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
    deliverable = metadata.get("deliverable", {})
    if isinstance(deliverable, dict):
        pr_url = _optional_text(deliverable.get("pr_url"))
        if pr_url:
            return pr_url
    pr_url = _optional_text(metadata.get("pr_url"))
    if pr_url:
        return pr_url
    for url in getattr(artifact, "urls", []):
        text = _optional_text(url)
        if text and "/pull/" in text:
            return text
    return None


def _artifact_blocked_reason(artifact: TrancheLaneArtifact) -> str | None:
    reason = _optional_text(getattr(artifact, "blocked_reason", None))
    if reason:
        return reason
    metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
    blocker = metadata.get("blocker", {})
    if isinstance(blocker, dict):
        return _optional_text(blocker.get("reason"))
    return None


def _artifact_blocking_question(artifact: TrancheLaneArtifact) -> str | None:
    question = _optional_text(getattr(artifact, "blocking_question", None))
    if question:
        return question
    metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
    blocker = metadata.get("blocker", {})
    if isinstance(blocker, dict):
        return _optional_text(blocker.get("question"))
    return None


def _lease_map(store: Any | None, *, lease_ids: set[str] | None = None) -> dict[str, Any]:
    normalized_ids = {item for item in (lease_ids or set()) if str(item).strip()}
    if store is None or not hasattr(store, "list_leases") or not normalized_ids:
        return {}
    return {
        str(item.lease_id): item
        for item in store.list_leases(limit=None)
        if getattr(item, "lease_id", None) and str(item.lease_id) in normalized_ids
    }


def _get_supervisor_run(store: Any | None, run_id: str | None) -> dict[str, Any] | None:
    if store is None or not run_id or not hasattr(store, "get_supervisor_run"):
        return None
    record = store.get_supervisor_run(run_id)
    return record if isinstance(record, dict) else None


def refresh_supervisor_run_dict(supervisor: Any, run_id: str | None) -> dict[str, Any] | None:
    run = _optional_text(run_id)
    if supervisor is None or not run or not hasattr(supervisor, "refresh_run"):
        return None
    try:
        refreshed = supervisor.refresh_run(run)
    except (KeyError, OSError, RuntimeError, ValueError):
        logger.debug(
            "Supervisor refresh failed for run %s; falling back to stored record",
            run,
            exc_info=True,
        )
        record = _get_supervisor_run(getattr(supervisor, "store", None), run)
        return dict(record) if isinstance(record, dict) else None
    if not hasattr(refreshed, "to_dict"):
        raise TypeError(f"Supervisor refresh for {run} returned {type(refreshed).__name__}")
    payload = refreshed.to_dict()
    if not isinstance(payload, dict):
        raise TypeError(f"Supervisor refresh for {run} returned non-dict payload")
    return dict(payload)


def _get_completion_receipt(store: Any | None, receipt_id: str | None) -> Any | None:
    if store is None or not receipt_id or not hasattr(store, "get_completion_receipt"):
        return None
    return store.get_completion_receipt(receipt_id)


def _latest_integration_decision(store: Any | None, receipt_id: str | None) -> Any | None:
    if store is None or not receipt_id or not hasattr(store, "list_integration_decisions"):
        return None
    decisions = store.list_integration_decisions(receipt_id=receipt_id, limit=1)
    return decisions[0] if decisions else None


def _prefer_text(current: Any, candidate: Any) -> str | None:
    current_text = _optional_text(current)
    if current_text:
        return current_text
    return _optional_text(candidate)


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _work_order_has_deliverable(work_order: dict[str, Any]) -> bool:
    if _optional_text(work_order.get("pr_url")) or _optional_text(work_order.get("adopted_pr")):
        return True
    branch = _optional_text(work_order.get("branch"))
    commit_shas = [
        str(item).strip() for item in work_order.get("commit_shas", []) if str(item).strip()
    ]
    return bool(branch and commit_shas)


def _work_order_has_scope_violation(work_order: dict[str, Any]) -> bool:
    if str(work_order.get("status", "")).strip().lower() == "scope_violation":
        return True
    return isinstance(work_order.get("scope_violation"), dict)


def _sync_artifacts_from_supervisor_run(
    state: TrancheRunState,
    *,
    run_dict: dict[str, Any],
    artifact_store: TrancheArtifactStore | Any | None,
) -> None:
    if artifact_store is None or not isinstance(run_dict, dict):
        return
    work_orders = [item for item in run_dict.get("work_orders", []) if isinstance(item, dict)]
    if not work_orders:
        return
    for work_order in work_orders:
        lane_id = _work_order_lane_id(state, work_order)
        if not lane_id:
            continue
        artifact = _load_artifact_for_lane(artifact_store, state.manifest_id, lane_id)
        if artifact is None:
            continue
        metadata = artifact.metadata if isinstance(artifact.metadata, dict) else {}
        deliverable = metadata.get("deliverable", {})
        if not isinstance(deliverable, dict):
            deliverable = {}
        branch = _optional_text(work_order.get("branch"))
        pr_url = _optional_text(work_order.get("pr_url")) or _optional_text(
            work_order.get("adopted_pr")
        )
        commit_shas = [
            str(item).strip() for item in work_order.get("commit_shas", []) if str(item).strip()
        ]
        if branch:
            metadata["branch"] = branch
            deliverable["branch"] = branch
        if pr_url:
            metadata["pr_url"] = pr_url
            deliverable["pr_url"] = pr_url
            if pr_url not in artifact.urls:
                artifact.urls = [*artifact.urls, pr_url]
        if commit_shas:
            deliverable["commit_shas"] = list(commit_shas)
        receipt_id = _optional_text(work_order.get("receipt_id"))
        if receipt_id:
            metadata["receipt_id"] = receipt_id
        lease_id = _optional_text(work_order.get("lease_id"))
        if lease_id:
            metadata["lease_id"] = lease_id
        if deliverable:
            metadata["deliverable"] = deliverable
        scope_violation = work_order.get("scope_violation")
        if isinstance(scope_violation, dict):
            metadata["scope_violation"] = dict(scope_violation)
        blockers = [
            str(item).strip() for item in work_order.get("blockers", []) if str(item).strip()
        ]
        if blockers:
            metadata["blockers"] = blockers
        artifact.metadata = metadata
        artifact.run_id = _prefer_text(artifact.run_id, run_dict.get("run_id"))
        artifact.worktree_path = _prefer_text(
            artifact.worktree_path, work_order.get("worktree_path")
        )
        if _work_order_has_deliverable(work_order):
            artifact.status = "completed"
            artifact.residual_risk = (
                "Lane delivered a concrete branch/commit and is ready for review."
            )
            artifact.next_actions = ["Run tranche review/integrate for this lane."]
            artifact.clear_blocker()
        elif _work_order_has_scope_violation(work_order):
            artifact.status = "needs_human"
            artifact.residual_risk = "Worker edited files outside the permitted scope."
            artifact.next_actions = ["Inspect scope violation details before any manual recovery."]
            artifact.set_blocker(
                reason="scope_violation",
                question=_optional_text(work_order.get("blocking_question"))
                or "Which files should stay in scope before rerunning this lane?",
            )
        elif str(work_order.get("status", "")).strip().lower() == "needs_human":
            artifact.status = "needs_human"
            artifact.residual_risk = "Worker reached needs_human state."
            artifact.next_actions = ["Worker reached needs_human state."]
            artifact.set_blocker(
                reason=_optional_text(work_order.get("failure_reason")) or "needs_human",
                question=_optional_text(work_order.get("blocking_question"))
                or "What human input is required before rerunning this lane?",
            )
        artifact.timestamp = _utcnow().isoformat()
        artifact_store.save(state.manifest_id, artifact)


def _work_order_lane_id(state: TrancheRunState, work_order: dict[str, Any]) -> str | None:
    work_order_id = _optional_text(work_order.get("work_order_id"))
    if work_order_id and work_order_id in state.lane_states:
        return work_order_id
    if len(state.lane_states) == 1:
        return next(iter(state.lane_states))
    return None


def _load_artifact_for_lane(
    artifact_store: TrancheArtifactStore | Any,
    manifest_id: str,
    lane_id: str,
) -> TrancheLaneArtifact | None:
    if hasattr(artifact_store, "load"):
        artifact = artifact_store.load(manifest_id, lane_id)
        if artifact is not None:
            return artifact
    if hasattr(artifact_store, "list"):
        for artifact in artifact_store.list(manifest_id):
            if getattr(artifact, "lane_id", None) == lane_id:
                return artifact
    return None


def _watch_review_status(status: str) -> str:
    lowered = str(status or "").strip().lower()
    if lowered == "passed":
        return LANE_STATUS_REVIEW_PASSED
    if lowered == "changes_requested":
        return LANE_STATUS_REVIEW_FAILED
    return LANE_STATUS_NEEDS_HUMAN


def _persist_review_payload(
    manifest_id: str,
    *,
    artifact: TrancheLaneArtifact | Any | None,
    review_payload: Any,
    artifact_store: TrancheArtifactStore | Any | None,
) -> None:
    if artifact is None or not isinstance(review_payload, dict):
        return
    metadata = getattr(artifact, "metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    artifact.metadata = {**metadata, "review": dict(review_payload)}
    artifact.status = _review_artifact_status(review_payload.get("status"))
    artifact.timestamp = _utcnow().isoformat()
    if artifact_store is not None and hasattr(artifact_store, "save"):
        artifact_store.save(manifest_id, artifact)


def _review_artifact_status(status: Any) -> str:
    lowered = str(status or "").strip().lower()
    if lowered == "passed":
        return "review_passed"
    if lowered == "changes_requested":
        return "changes_requested"
    return "review_blocked"


def _watch_integrate_status(current_status: str, payload: dict[str, Any]) -> str:
    recommendation = str(payload.get("recommendation", "") or "").strip().lower()
    executed = bool(payload.get("executed", False))
    if recommendation == "merge" and executed:
        return LANE_STATUS_COMPLETED
    if recommendation == "merge":
        return LANE_STATUS_WAITING_FOR_MERGE
    if recommendation == "awaiting_checks":
        return (
            LANE_STATUS_WAITING_FOR_MERGE
            if _optional_text(payload.get("pr_url"))
            else current_status
        )
    if recommendation == "awaiting_confirmation":
        return LANE_STATUS_NEEDS_HUMAN
    if recommendation in {"request_changes", "blocked", "needs_human"}:
        return LANE_STATUS_NEEDS_HUMAN
    return current_status


def _should_attempt_dispatch(
    state: TrancheRunState,
    *,
    store: Any | None,
) -> bool:
    lane_states = list(state.lane_states.values())
    if not any(str(item.status).strip() == LANE_STATUS_PENDING for item in lane_states):
        return False
    return not any(_lane_blocks_dispatch(item, store=store) for item in lane_states)


def _lane_blocks_dispatch(
    lane_state: LaneRunState,
    *,
    store: Any | None,
) -> bool:
    status = str(lane_state.status or "").strip()
    if status == LANE_STATUS_PENDING:
        return False
    if status == LANE_STATUS_COMPLETED:
        return not _completed_lane_is_terminal(lane_state, store=store)
    return status not in {
        LANE_STATUS_ABORTED,
        LANE_STATUS_NEEDS_HUMAN,
        LANE_STATUS_REVIEW_FAILED,
    }


def _completed_lane_is_terminal(
    lane_state: LaneRunState,
    *,
    store: Any | None,
) -> bool:
    if str(lane_state.status or "").strip() != LANE_STATUS_COMPLETED:
        return False
    decision = _latest_integration_decision(store, lane_state.receipt_id)
    value = str(getattr(decision, "decision", "") or "").strip()
    return value in {
        IntegrationDecisionType.MERGE.value,
        IntegrationDecisionType.CHERRY_PICK.value,
    }


def _apply_dispatch_payload(state: TrancheRunState, payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    results = payload.get("results")
    if not isinstance(results, list):
        return
    now = _utcnow()
    for item in results:
        if not isinstance(item, dict):
            continue
        lane_id = _optional_text(item.get("lane_id"))
        if not lane_id:
            continue
        lane_state = state.lane_states.get(lane_id)
        if lane_state is None:
            lane_state = LaneRunState(lane_id=lane_id, status=LANE_STATUS_PENDING)
            state.lane_states[lane_id] = lane_state
        lane_state.status = _watch_dispatch_status(item)
        lane_state.run_id = _prefer_text(lane_state.run_id, item.get("run_id"))
        lane_state.worktree_path = _prefer_text(
            lane_state.worktree_path,
            item.get("worktree_path"),
        )
        raw_metadata = item.get("metadata")
        metadata = cast(dict[str, Any], raw_metadata) if isinstance(raw_metadata, dict) else {}
        lane_state.receipt_id = _prefer_text(lane_state.receipt_id, metadata.get("receipt_id"))
        lane_state.lease_id = _prefer_text(lane_state.lease_id, metadata.get("lease_id"))
        lane_state.pr_url = _prefer_text(lane_state.pr_url, metadata.get("pr_url"))
        lane_state.set_blocker(
            reason=_prefer_text(
                lane_state.blocked_reason,
                item.get("blocked_reason"),
            ),
            question=_prefer_text(
                lane_state.blocking_question,
                item.get("blocking_question"),
            ),
        )
        lane_state.last_updated = now


def _watch_dispatch_status(payload: dict[str, Any]) -> str:
    lowered = str(payload.get("status", "") or "").strip().lower()
    if lowered == "running":
        return LANE_STATUS_RUNNING
    if lowered == "completed":
        return LANE_STATUS_COMPLETED
    if lowered in {"needs_human", "failed"}:
        return LANE_STATUS_NEEDS_HUMAN
    return LANE_STATUS_DISPATCHED


def _apply_cascade_report_to_state(
    state: TrancheRunState,
    report: dict[str, Any] | None,
) -> None:
    if not isinstance(report, dict):
        return
    now = _utcnow()
    merged_lane_id = _optional_text(report.get("merged_lane_id"))
    if merged_lane_id and merged_lane_id in state.lane_states:
        state.lane_states[merged_lane_id].status = LANE_STATUS_COMPLETED
        state.lane_states[merged_lane_id].last_updated = now

    needs_human = False
    for item in report.get("downstream", []):
        if not isinstance(item, dict):
            continue
        lane_id = _optional_text(item.get("lane_id"))
        action = str(item.get("action", "") or "").strip()
        if not lane_id or action not in {"needs_restack", "missing_pr"}:
            continue
        lane_state = state.lane_states.get(lane_id)
        if lane_state is None:
            lane_state = LaneRunState(lane_id=lane_id, status=LANE_STATUS_NEEDS_HUMAN)
            state.lane_states[lane_id] = lane_state
        lane_state.status = LANE_STATUS_NEEDS_HUMAN
        lane_state.set_blocker(
            reason=action,
            question=(
                "Which upstream branch or PR should this lane restack onto before rerunning?"
                if action == "needs_restack"
                else "Which upstream lane still needs a published PR before this lane can continue?"
            ),
        )
        lane_state.last_updated = now
        needs_human = True

    if needs_human:
        state.status = TRANCHE_STATUS_NEEDS_HUMAN
    state.updated_at = now


def _close_session_history(state: TrancheRunState, session_id: str, *, now: Any) -> None:
    for item in reversed(state.session_history):
        if str(item.get("session_id", "")).strip() != session_id:
            continue
        if item.get("detached_at"):
            continue
        item["detached_at"] = now.isoformat()
        return
