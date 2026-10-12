"""``aragora swarm coord|assign|claim-pr|report|findings`` subcommands.

``aragora.cli.commands.swarm`` dispatches these five actions here and re-exports
``_run_coordination_action``. The session-coordinator functions and
``resolve_repo_root`` are imported when the command runs, so tests patch them on
``aragora.swarm.session_coordinator`` and ``aragora.worktree.fleet``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from aragora.cli.commands.swarm_inputs import (
    _coordination_assigned_by,
    _coordination_session_id,
    _optional_text,
)
from aragora.cli.commands.swarm_render import _render_coordination_view

JsonDict = dict[str, Any]


def _run_coordination_action(
    args: argparse.Namespace,
    *,
    action: str,
    goal: str | None,
    as_json: bool,
) -> None:
    """Handle ``aragora swarm coord|assign|claim-pr|report|findings``."""

    from aragora.swarm.session_coordinator import (
        claim_pr as coord_claim_pr,
        list_findings as coord_list_findings,
        read_directives as coord_read,
        report_finding as coord_report_finding,
        set_assignment as coord_set_assignment,
    )
    from aragora.worktree.fleet import resolve_repo_root

    payload: JsonDict
    response: JsonDict

    repo_root = resolve_repo_root(Path.cwd())
    findings_limit = max(1, int(getattr(args, "findings_limit", 10)))
    session_id = _coordination_session_id(args)

    if action == "coord":
        payload = coord_read(repo_root, findings_limit=findings_limit)
        if as_json:
            print(json.dumps(payload, indent=2))
        else:
            _render_coordination_view(payload)
        return

    if action == "assign":
        target_session = _optional_text(goal)
        task_text = _optional_text(getattr(args, "swarm_campaign_target", None))
        if not target_session or not task_text:
            print('Error: usage: aragora swarm assign <session-id> "task description"')
            return
        payload = coord_set_assignment(
            target_session,
            task_text,
            scope=[str(item) for item in (getattr(args, "scope", None) or []) if str(item).strip()],
            constraints=[
                str(item) for item in (getattr(args, "constraint", None) or []) if str(item).strip()
            ],
            status=str(getattr(args, "directive_status", "active") or "active"),
            issued_by=_coordination_assigned_by(args),
            repo_root=repo_root,
        )
        response = {"mode": "coordination-assign", "directive": payload}
        if as_json:
            print(json.dumps(response, indent=2))
        else:
            print(f"assigned {payload.get('target', '')}: {payload.get('task', '')}")
        return

    if action == "claim-pr":
        pr_text = _optional_text(goal)
        if not pr_text:
            print("Error: usage: aragora swarm claim-pr <pr-number>")
            return
        try:
            pr_number = int(pr_text)
        except ValueError:
            print(f"Error: invalid PR number: {pr_text}")
            return
        payload = dict(
            coord_claim_pr(
                pr_number,
                session_id,
                intent=_optional_text(getattr(args, "claim_intent", None)) or "",
                ttl_minutes=max(1, int(getattr(args, "ttl_minutes", 30) or 30)),
                repo_root=repo_root,
            )
        )
        response = {"mode": "coordination-claim-pr", "pr": pr_number, **payload}
        if as_json:
            print(json.dumps(response, indent=2))
        else:
            status_text = str(payload.get("status", "unknown"))
            if status_text == "granted":
                print(f"claimed PR#{pr_number} for {session_id}")
            else:
                owners = [
                    str(item.get("session_id", ""))
                    for item in payload.get("contested_by", [])
                    if isinstance(item, dict)
                ]
                print(
                    f"PR#{pr_number} claim contested for {session_id}"
                    + (f" (also claimed by {', '.join(owners)})" if owners else "")
                )
        return

    if action == "report":
        message = _optional_text(goal)
        if not message:
            print('Error: usage: aragora swarm report "finding text"')
            return
        payload = coord_report_finding(
            message,
            session_id,
            kind=_optional_text(getattr(args, "kind", None)) or "finding",
            pr=getattr(args, "pr", None),
            scope=[str(item) for item in (getattr(args, "scope", None) or []) if str(item).strip()],
            repo_root=repo_root,
        )
        response = {"mode": "coordination-report", "finding": payload}
        if as_json:
            print(json.dumps(response, indent=2))
        else:
            print(f"reported {payload.get('kind', 'finding')} from {session_id}")
        return

    findings = coord_list_findings(
        limit=findings_limit,
        session_id=_optional_text(getattr(args, "session_id", None)),
        kind=_optional_text(getattr(args, "kind", None)),
        pr=getattr(args, "pr", None),
        repo_root=repo_root,
    )
    if as_json:
        print(json.dumps({"mode": "coordination-findings", "findings": findings}, indent=2))
    elif not findings:
        print("No findings reported yet.")
    else:
        for finding in findings:
            pr_value = finding.get("pr")
            pr_text = f" pr=#{pr_value}" if pr_value not in (None, "", 0) else ""
            print(
                "[{session}] {kind}{pr} {message}".format(
                    session=finding.get("source_session", "-") or "-",
                    kind=finding.get("kind", "finding"),
                    pr=pr_text,
                    message=finding.get("message", ""),
                )
            )
    return
