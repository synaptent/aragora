"""Session coordination facade for swarm operators and worker sessions.

This module exposes a small, operator-friendly surface for cross-session
coordination while delegating storage to the existing coordination primitives:

- assignments -> :mod:`aragora.coordination.directives`
- claims -> :mod:`aragora.coordination.claims`
- findings -> :mod:`aragora.coordination.bus`
- liveness -> :mod:`aragora.coordination.registry`

All commands resolve the canonical repository root so sessions in disposable
side worktrees still share the same coordination state.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from aragora.coordination import (
    ClaimManager,
    CoordinationBus,
    DirectiveBoard,
    SessionRegistry,
)
from aragora.worktree.fleet import resolve_repo_root


def _coord_repo_root(repo_root: Path | None = None) -> Path:
    if repo_root is not None:
        return Path(repo_root).resolve()
    return resolve_repo_root(Path.cwd().resolve())


def set_assignment(
    session_id: str,
    task: str,
    *,
    scope: list[str] | None = None,
    constraints: list[str] | None = None,
    status: str = "active",
    issued_by: str = "",
    repo_root: Path | None = None,
) -> dict[str, object]:
    root = _coord_repo_root(repo_root)
    directive = DirectiveBoard(repo_path=root).assign(
        session_id,
        task,
        scope=scope,
        constraints=constraints,
        assigned_by=issued_by,
        status=status,
    )
    CoordinationBus(repo_path=root, source_session=issued_by).publish(
        "directive_assigned",
        {
            "target": session_id,
            "task": task,
            "scope": list(scope or []),
            "constraints": list(constraints or []),
            "status": status,
        },
    )
    return directive.to_dict()


def get_my_assignment(session_id: str, repo_root: Path | None = None) -> dict[str, object] | None:
    root = _coord_repo_root(repo_root)
    directive = DirectiveBoard(repo_path=root).get(session_id)
    return directive.to_dict() if directive is not None else None


def _reap_abandoned_coordination_state(root: Path) -> list[dict[str, object]]:
    board = DirectiveBoard(repo_path=root)
    registry = SessionRegistry(repo_path=root)
    claims_manager = ClaimManager(repo_path=root)

    reaped_sessions = registry.reap_abandoned()
    for session in reaped_sessions:
        session_id = str(session.get("session_id") or "")
        session["directive_cleared"] = board.clear(session_id) if session_id else False
        session["claims_released"] = claims_manager.release(session_id) if session_id else 0
    return reaped_sessions


def claim_pr(
    pr_number: int,
    session_id: str,
    *,
    intent: str = "",
    ttl_minutes: int = 30,
    repo_root: Path | None = None,
) -> dict[str, object]:
    root = _coord_repo_root(repo_root)
    _reap_abandoned_coordination_state(root)
    result = ClaimManager(repo_path=root).claim(
        [f"pr:{pr_number}"],
        session_id=session_id,
        intent=intent or f"Own PR #{pr_number}",
        ttl_minutes=ttl_minutes,
    )
    CoordinationBus(repo_path=root, source_session=session_id).publish(
        "pr_claimed",
        {
            "pr": pr_number,
            "intent": result.claim.intent,
            "status": result.status.value,
            "contested_by": [item.session_id for item in result.contested_by],
        },
    )
    return {
        "status": result.status.value,
        "claim": result.claim.to_dict(),
        "contested_by": [item.to_dict() for item in result.contested_by],
        "contested_paths": list(result.contested_paths),
    }


def report_finding(
    finding: str,
    session_id: str,
    *,
    kind: str = "finding",
    pr: int | None = None,
    scope: list[str] | None = None,
    repo_root: Path | None = None,
) -> dict[str, object]:
    root = _coord_repo_root(repo_root)
    event = CoordinationBus(repo_path=root, source_session=session_id).publish(
        "finding_reported",
        {
            "message": finding,
            "kind": kind,
            "pr": pr,
            "scope": list(scope or []),
            "session_id": session_id,
        },
    )
    return {
        "event_id": event.event_id,
        "timestamp": event.timestamp,
        "source_session": event.source_session,
        "kind": kind,
        "message": finding,
        "pr": pr,
        "scope": list(scope or []),
    }


def list_findings(
    *,
    limit: int = 10,
    session_id: str | None = None,
    kind: str | None = None,
    pr: int | None = None,
    repo_root: Path | None = None,
) -> list[dict[str, object]]:
    root = _coord_repo_root(repo_root)
    events = CoordinationBus(repo_path=root).poll(
        event_type="finding_reported",
        limit=max(limit * 5, limit),
    )
    findings: list[dict[str, object]] = []
    for event in reversed(events):
        payload = event.payload if isinstance(event.payload, dict) else {}
        event_session = str(payload.get("session_id") or event.source_session or "")
        event_kind = str(payload.get("kind") or "finding")
        event_pr = payload.get("pr")
        if session_id and event_session != session_id:
            continue
        if kind and event_kind != kind:
            continue
        if pr is not None and event_pr != pr:
            continue
        findings.append(
            {
                "event_id": event.event_id,
                "timestamp": event.timestamp,
                "source_session": event_session,
                "kind": event_kind,
                "message": str(payload.get("message") or ""),
                "pr": event_pr,
                "scope": list(cast(Any, payload.get("scope") or [])),
            }
        )
        if len(findings) >= limit:
            break
    return findings


def read_directives(repo_root: Path | None = None, *, findings_limit: int = 10) -> dict[str, Any]:
    root = _coord_repo_root(repo_root)
    reaped_sessions = _reap_abandoned_coordination_state(root)
    board = DirectiveBoard(repo_path=root)
    registry = SessionRegistry(repo_path=root)
    claims_manager = ClaimManager(repo_path=root)

    directives = [item.to_dict() for item in board.list()]
    sessions = [registry.describe(item) for item in registry.discover()]
    claims = [item.to_dict() for item in claims_manager.list_all()]
    findings = list_findings(limit=findings_limit, repo_root=root)
    stale_session_count = sum(1 for item in reaped_sessions if item.get("status") == "stale")
    dead_session_count = sum(1 for item in reaped_sessions if item.get("status") == "dead")
    return {
        "repo_root": str(root),
        "summary": {
            "directive_count": len(directives),
            "session_count": len(sessions),
            "claim_count": len(claims),
            "finding_count": len(findings),
            "reaped_session_count": len(reaped_sessions),
            "stale_session_count": stale_session_count,
            "dead_session_count": dead_session_count,
        },
        "directives": directives,
        "sessions": sessions,
        "claims": claims,
        "findings": findings,
        "reaped_sessions": reaped_sessions,
    }


__all__ = [
    "claim_pr",
    "get_my_assignment",
    "list_findings",
    "read_directives",
    "report_finding",
    "set_assignment",
]
