#!/usr/bin/env python3
"""Check, record, or merge-apply an exact-head Tier 4 PR settlement.

Tier 4 automation may prepare a packet, but merge/protection mutation requires
a repo-visible operator settlement comment naming the exact head and action.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from aragora.cli.commands import review_queue_rest_fallback as rest_fallback
from aragora.cli.commands.review_queue_transport import _GhError

try:
    from aragora.swarm.github_app_auth import (
        gh_subprocess_run,
        github_cli_env,
    )
except Exception:  # pragma: no cover - script must still run in partial checkouts
    gh_subprocess_run = None  # type: ignore[assignment]

    def github_cli_env(
        base_env: Mapping[str, str] | None = None,
        *,
        prefer_app: bool = True,
    ) -> dict[str, str]:
        del prefer_app
        return dict(os.environ if base_env is None else base_env)


DEFAULT_REPO = "synaptent/aragora"
AUTHORIZED_MARKER = "Tier-4 Human Settlement Authorization"
AUTHORIZED_MERGE_TOKENS = ("admin_squash_merge", "admin squash")
AUTHORIZED_PROTECTION_TOKENS = ("branch_protection_reconcile", "branch protection reconcile")
TRUSTED_OPERATOR_AUTHOR_ASSOCIATIONS = {"OWNER"}
TRUSTED_OPERATOR_MEMBER_ASSOCIATIONS = {"MEMBER"}
# GitHub reports some repo admins as COLLABORATOR rather than MEMBER. Keep
# that association fail-closed: require both an explicit allowlist entry and a
# live repo-admin permission check before accepting it for Tier 4 settlement.
TRUSTED_OPERATOR_ALLOWLIST_ADMIN_ASSOCIATIONS = {"COLLABORATOR"}
TRUSTED_OPERATOR_LOGINS_ENV = "ARAGORA_TIER4_TRUSTED_OPERATORS"
PermissionChecker = Callable[[str], bool]
HUMAN_SETTLEMENT_CONTEXT = "aragora/human-settlement"
HUMAN_SETTLEMENT_STATUS_BLOCKER = f"missing or unsuccessful {HUMAN_SETTLEMENT_CONTEXT} status"
HUMAN_SETTLEMENT_STATUS_PIN_BLOCKER = f"untrusted or unbound {HUMAN_SETTLEMENT_CONTEXT} status"
MERGE_QUORUM_CONTEXT = "aragora-merge-quorum"
OPERATOR_COMMENT_BLOCKER = "missing repo-visible Tier 4 operator settlement comment"
REQUIRED_CHECKS_BLOCKER = "required checks are missing"
REQUIRED_CHECK_VISIBILITY_SKEW_BLOCKER = "required_check_visibility_skew"
REQUIRED_CHECK_REST_VISIBILITY_CONTEXT = "required check REST visibility"
BRANCH_PROTECTION_PREFLIGHT_BLOCKER = "branch protection preflight failed"
MERGE_QUORUM_SETTLEMENT_PROOF_BLOCKER = (
    "aragora-merge-quorum failure is not proven to be missing human settlement"
)
SETTLE_ONLY_TRUSTED_OPERATOR_BLOCKER = "trusted operator allowlist is required for --settle-only"
SETTLE_ONLY_INVOKER_BLOCKER = "could not determine gh login for --settle-only"
SETTLE_ONLY_ADMIN_PERMISSION_BLOCKER = "admin/OWNER permission required for --settle-only"
TIER4_EVIDENCE_BLOCKER = "missing Tier 4 model/dogfood settlement evidence"
COMMAND_FAILURE_DETAIL_LIMIT = 1000
SUCCESS_STATES = {"SUCCESS", "PASS", "PASSED", "SKIPPED", "NEUTRAL"}
BLOCKING_MERGE_STATES = {"DIRTY", "CONFLICTING"}
MIN_TIER4_COUNTED_REVIEWER_IDS = 2
STATUS_TIMESTAMP_FIELDS = (
    "updatedAt",
    "updated_at",
    "createdAt",
    "created_at",
    "completedAt",
    "completed_at",
    "startedAt",
    "started_at",
)
ALLOWED_TIER4_NOT_READY = {
    "human_risk_settlement",
    "tier4_human_risk_settlement",
    "operator_settlement_required",
}
ALLOWED_TIER4_ENTRY_STATUSES = {
    "human_preapproval_required",
}


class Tier4ApplyError(RuntimeError):
    """Structured failure for Tier 4 merge/apply phases."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        mutation_occurred: bool,
        completed_commands: int,
        recovery_action: str,
        rollback_errors: Sequence[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.mutation_occurred = mutation_occurred
        self.completed_commands = completed_commands
        self.recovery_action = recovery_action
        self.rollback_errors = list(rollback_errors or [])

    def to_payload(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "mutation_occurred": self.mutation_occurred,
            "completed_commands": self.completed_commands,
            "rollback_errors": self.rollback_errors,
            "recovery_action": self.recovery_action,
        }


def _text_items(pr_view: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("comments", "reviews"):
        value = pr_view.get(key)
        if not isinstance(value, list):
            continue
        for entry in value:
            if isinstance(entry, dict):
                body = entry.get("body")
                if isinstance(body, str):
                    items.append(
                        {
                            "kind": "review" if key == "reviews" else "comment",
                            "body": body,
                            "authorAssociation": entry.get("authorAssociation"),
                            "author": entry.get("author"),
                            "url": entry.get("url"),
                            "createdAt": entry.get("createdAt") or entry.get("submittedAt"),
                        }
                    )
    return items


def _parse_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f"{text[:-1]}+00:00" if text.endswith("Z") else text


def _head_committed_at(pr_view: dict[str, Any]) -> str:
    direct = str(pr_view.get("headCommittedDate") or "").strip()
    if direct:
        return direct
    commits = pr_view.get("commits")
    if isinstance(commits, list) and commits:
        latest = commits[-1]
        if isinstance(latest, dict):
            return str(latest.get("committedDate") or "").strip()
    return ""


def _authorization_is_fresh(item: dict[str, Any], *, head_committed_at: str) -> bool:
    if not head_committed_at:
        return False
    created_at = str(item.get("createdAt") or "").strip()
    if not created_at:
        return False
    return _parse_timestamp(created_at) >= _parse_timestamp(head_committed_at)


def _trusted_operator_logins(extra_logins: Sequence[str] | None = None) -> frozenset[str]:
    configured = {
        login.strip().lower()
        for login in os.environ.get(TRUSTED_OPERATOR_LOGINS_ENV, "").split(",")
        if login.strip()
    }
    explicit = {login.strip().lower() for login in extra_logins or () if login.strip()}
    return frozenset(configured | explicit)


def _current_gh_login(*, cwd: Path) -> str:
    # Identity is semantic for Tier-4 settlement. Do not let App-token fallback
    # turn an operator identity check into a bot identity check.
    payload = _run_json(["gh", "api", "user"], cwd=cwd, prefer_app=False)
    login = str(payload.get("login") or "").strip().lower()
    if not login:
        raise RuntimeError("gh api user did not return a login")
    return login


def _author_login(item: dict[str, Any]) -> str:
    author = item.get("author")
    if isinstance(author, dict):
        return str(author.get("login") or "").strip().lower()
    if isinstance(author, str):
        return author.strip().lower()
    return ""


def _collaborator_permission_is_admin(payload: dict[str, Any]) -> bool:
    return (
        str(payload.get("permission") or "").lower() == "admin"
        or str(payload.get("role_name") or "").lower() == "admin"
    )


def _login_has_admin_permission(login: str, repo: str, cwd: Path | None) -> bool:
    if not login:
        return False
    endpoint = f"repos/{repo}/collaborators/{quote(login, safe='')}/permission"
    try:
        payload = _run_json(["gh", "api", endpoint], cwd=cwd)
    except RuntimeError:
        return False
    return _collaborator_permission_is_admin(payload)


def _is_trusted_operator_author(
    item: dict[str, Any],
    *,
    trusted_operator_logins: frozenset[str],
    permission_checker: PermissionChecker,
    evaluate_member_permissions: bool = True,
) -> bool:
    return not _operator_author_rejection_reason(
        item,
        trusted_operator_logins=trusted_operator_logins,
        permission_checker=permission_checker,
        evaluate_member_permissions=evaluate_member_permissions,
    )


def _trusted_member_requires_permission_check(
    item: dict[str, Any],
    *,
    trusted_operator_logins: frozenset[str],
) -> bool:
    association = str(item.get("authorAssociation") or "").upper()
    if association not in (
        TRUSTED_OPERATOR_MEMBER_ASSOCIATIONS | TRUSTED_OPERATOR_ALLOWLIST_ADMIN_ASSOCIATIONS
    ):
        return False
    login = _author_login(item)
    if not login:
        return False
    if association in TRUSTED_OPERATOR_ALLOWLIST_ADMIN_ASSOCIATIONS:
        return login in trusted_operator_logins
    return not trusted_operator_logins or login in trusted_operator_logins


def _operator_author_rejection_reason(
    item: dict[str, Any],
    *,
    trusted_operator_logins: frozenset[str],
    permission_checker: PermissionChecker,
    evaluate_member_permissions: bool = True,
) -> str:
    association = str(item.get("authorAssociation") or "").upper()
    if association in TRUSTED_OPERATOR_AUTHOR_ASSOCIATIONS:
        return ""
    if association not in (
        TRUSTED_OPERATOR_MEMBER_ASSOCIATIONS | TRUSTED_OPERATOR_ALLOWLIST_ADMIN_ASSOCIATIONS
    ):
        return f"authorAssociation {association or '<missing>'} is not trusted"
    login = _author_login(item)
    if not login:
        return f"{association} login <missing> is not available"
    if association in TRUSTED_OPERATOR_ALLOWLIST_ADMIN_ASSOCIATIONS and not trusted_operator_logins:
        return f"{association} login {login} requires explicit trusted operator allowlist"
    if trusted_operator_logins and login not in trusted_operator_logins:
        return f"{association} login {login} is not in trusted operator allowlist"
    if not evaluate_member_permissions:
        return ""
    if not permission_checker(login):
        return f"trusted {association.lower()} {login or '<missing>'} lacks admin permission"
    return ""


def _settlement_comment_template(*, pr: int, head: str) -> str:
    return (
        "Tier-4 Human Settlement Authorization\n\n"
        f"PR: #{pr}\n"
        f"Exact head: {head}\n"
        "Authorized action: admin_squash_merge and branch_protection_reconcile, "
        f"only if #{pr} is non-draft and live exact-head checks/merge-packet "
        "remain otherwise green.\n\n"
        "Human-risk settlement: I accept the Tier 4 risk for this PR."
    )


def _authorization_diagnostic(
    item: dict[str, Any],
    *,
    head: str,
    head_committed_at: str,
    require_branch_protection_token: bool,
    trusted_operator_logins: frozenset[str],
    permission_checker: PermissionChecker,
    evaluate_member_permissions: bool = True,
) -> dict[str, Any]:
    body = str(item.get("body") or "")
    association = str(item.get("authorAssociation") or "").upper()
    marker_present = AUTHORIZED_MARKER in body
    author_rejection = _operator_author_rejection_reason(
        item,
        trusted_operator_logins=trusted_operator_logins,
        permission_checker=permission_checker,
        evaluate_member_permissions=evaluate_member_permissions,
    )
    admin_permission_required = _trusted_member_requires_permission_check(
        item,
        trusted_operator_logins=trusted_operator_logins,
    )
    admin_permission_evaluated = admin_permission_required and evaluate_member_permissions
    trusted_author_association = not author_rejection
    fresh_after_head_commit = _authorization_is_fresh(item, head_committed_at=head_committed_at)
    exact_head_present = head in body
    authorized_actions = _comment_authorized_actions(body)
    merge_action_present = "merge" in authorized_actions
    branch_protection_action_present = "branch_protection" in authorized_actions

    rejection_reasons: list[str] = []
    if not marker_present:
        rejection_reasons.append("authorization marker is missing")
    if author_rejection:
        rejection_reasons.append(author_rejection)
    if admin_permission_required and not evaluate_member_permissions:
        rejection_reasons.append(
            "trusted operator admin permission was not evaluated because earlier gate blockers are present"
        )
    if not fresh_after_head_commit:
        rejection_reasons.append("authorization is older than head commit")
    if not exact_head_present:
        rejection_reasons.append("exact head is missing")
    if not merge_action_present:
        rejection_reasons.append("admin_squash_merge action is missing")
    if require_branch_protection_token and not branch_protection_action_present:
        rejection_reasons.append("branch_protection_reconcile action is missing")

    return {
        "kind": item.get("kind") or "text",
        "author": _author_login(item),
        "authorAssociation": association,
        "createdAt": item.get("createdAt"),
        "url": item.get("url"),
        "marker_present": marker_present,
        "trusted_author_association": trusted_author_association,
        "admin_permission_required": admin_permission_required,
        "admin_permission_evaluated": admin_permission_evaluated,
        "fresh_after_head_commit": fresh_after_head_commit,
        "exact_head_present": exact_head_present,
        "merge_action_present": merge_action_present,
        "branch_protection_action_present": branch_protection_action_present,
        "authorized_actions": sorted(authorized_actions),
        "accepted": not rejection_reasons,
        "rejection_reasons": rejection_reasons,
    }


def authorization_diagnostics(
    pr_view: dict[str, Any],
    *,
    pr: int,
    head: str,
    require_branch_protection_token: bool = False,
    repo: str = DEFAULT_REPO,
    cwd: Path | None = None,
    trusted_operator_logins: Sequence[str] | None = None,
    permission_checker: PermissionChecker | None = None,
    evaluate_member_permissions: bool = True,
) -> dict[str, Any]:
    head_committed_at = _head_committed_at(pr_view)
    allowed_logins = _trusted_operator_logins(trusted_operator_logins)
    checker = permission_checker or (lambda login: _login_has_admin_permission(login, repo, cwd))
    return {
        "required_author_associations": sorted(TRUSTED_OPERATOR_AUTHOR_ASSOCIATIONS),
        "admin_permission_evaluation": "enabled"
        if evaluate_member_permissions
        else "skipped_early_gate_blockers",
        "head_committed_at": head_committed_at,
        "settlement_comment_template": _settlement_comment_template(pr=pr, head=head),
        "authorization_diagnostics": [
            _authorization_diagnostic(
                item,
                head=head,
                head_committed_at=head_committed_at,
                require_branch_protection_token=require_branch_protection_token,
                trusted_operator_logins=allowed_logins,
                permission_checker=checker,
                evaluate_member_permissions=evaluate_member_permissions,
            )
            for item in _text_items(pr_view)
        ],
    }


def _state_is_success(value: Any) -> bool:
    return str(value or "").upper() in SUCCESS_STATES


def _required_checks_are_green(required_checks: list[dict[str, Any]] | None) -> bool:
    if not required_checks:
        return False
    for check in required_checks:
        state = check.get("state") or check.get("conclusion")
        if not _state_is_success(state):
            return False
    return True


def _human_settlement_status_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    settlement_statuses: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        context = str(item.get("context") or item.get("name") or "")
        if context == HUMAN_SETTLEMENT_CONTEXT:
            settlement_statuses.append(item)
    return settlement_statuses


def _status_timestamp(item: dict[str, Any]) -> datetime | None:
    for key in STATUS_TIMESTAMP_FIELDS:
        text = _parse_timestamp(item.get(key))
        if not text:
            continue
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _status_state(item: dict[str, Any]) -> str:
    return str(item.get("state") or item.get("conclusion") or "").strip().upper()


def _status_equivalence_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
    context = str(item.get("context") or item.get("name") or "").strip()
    return (
        context,
        _status_target_url(item),
        _status_creator_login(item),
        _status_state(item),
    )


def _dedupe_status_observations(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for item in items:
        key = _status_equivalence_key(item)
        previous = deduped.get(key)
        if previous is None:
            deduped[key] = item
            continue
        previous_timestamp = _status_timestamp(previous)
        item_timestamp = _status_timestamp(item)
        if previous_timestamp is None and item_timestamp is not None:
            deduped[key] = item
        elif (
            previous_timestamp is not None
            and item_timestamp is not None
            and item_timestamp > previous_timestamp
        ):
            deduped[key] = item
    return list(deduped.values())


def _successful_human_settlement_status(pr_view: dict[str, Any]) -> dict[str, Any] | None:
    settlement_statuses = _human_settlement_status_items(pr_view.get("commitStatuses"))
    if not settlement_statuses:
        settlement_statuses = _dedupe_status_observations(
            _human_settlement_status_items(pr_view.get("statusCheckRollup"))
        )
    if not settlement_statuses:
        return None
    if len(settlement_statuses) == 1:
        item = settlement_statuses[0]
        return item if _state_is_success(_status_state(item)) else None
    timestamped: list[tuple[datetime, int, dict[str, Any]]] = []
    for index, item in enumerate(settlement_statuses):
        timestamp = _status_timestamp(item)
        if timestamp is None:
            return None
        timestamped.append((timestamp, index, item))
    timestamped.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    newest = timestamped[0]
    if len(timestamped) > 1 and timestamped[1][0] == newest[0]:
        return None
    return newest[2] if _state_is_success(_status_state(newest[2])) else None


def _human_settlement_status_is_success(pr_view: dict[str, Any]) -> bool:
    return _successful_human_settlement_status(pr_view) is not None


def _status_creator_login(item: dict[str, Any]) -> str:
    for key in ("creator", "author", "user"):
        author = item.get(key)
        if isinstance(author, dict):
            login = str(author.get("login") or "").strip().lower()
            if login:
                return login
        elif isinstance(author, str) and author.strip():
            return author.strip().lower()
    return ""


def _status_target_url(item: dict[str, Any]) -> str:
    for key in ("targetUrl", "target_url"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _accepted_authorization_diagnostics(
    diagnostic_report: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(diagnostic_report, dict):
        return []
    diagnostics = diagnostic_report.get("authorization_diagnostics")
    if not isinstance(diagnostics, list):
        return []
    return [
        diagnostic
        for diagnostic in diagnostics
        if isinstance(diagnostic, dict) and bool(diagnostic.get("accepted"))
    ]


def _human_settlement_status_is_bound_to_accepted_comment(
    pr_view: dict[str, Any],
    accepted_diagnostics: Sequence[dict[str, Any]],
) -> bool:
    status = _successful_human_settlement_status(pr_view)
    if status is None:
        return False
    status_creator = _status_creator_login(status)
    status_target_url = _status_target_url(status)
    if not status_creator or not status_target_url:
        return False
    for diagnostic in accepted_diagnostics:
        comment_url = str(diagnostic.get("url") or "").strip()
        comment_author = str(diagnostic.get("author") or "").strip().lower()
        if comment_url and comment_author and status_target_url == comment_url:
            if status_creator == comment_author:
                return True
    return False


def _packet_has_counted_tier4_evidence(merge_packet: dict[str, Any], *, pr: int) -> bool:
    entry = _entry_for_pr(merge_packet, pr=pr)
    if not entry:
        return False
    if bool(entry.get("unresolved_dissent")):
        return False
    counted = entry.get("counted_reviewer_ids")
    counted_ids = (
        {str(item).strip() for item in counted if isinstance(item, str) and str(item).strip()}
        if isinstance(counted, list)
        else set()
    )
    if len(counted_ids) < MIN_TIER4_COUNTED_REVIEWER_IDS:
        return False
    dogfood = entry.get("dogfood_evidence")
    if not isinstance(dogfood, list) or not dogfood:
        return False
    return True


def _comment_authorizes_requested_action(
    body: str, *, require_branch_protection_token: bool
) -> bool:
    actions = _comment_authorized_actions(body)
    if "merge" not in actions:
        return False
    if require_branch_protection_token and "branch_protection" not in actions:
        return False
    return True


def _comment_authorized_actions(body: str) -> set[str]:
    lowered = body.lower()
    actions: set[str] = set()
    if any(token in lowered for token in AUTHORIZED_MERGE_TOKENS):
        actions.add("merge")
    if any(token in lowered for token in AUTHORIZED_PROTECTION_TOKENS):
        actions.add("branch_protection")
    return actions


def _operator_authorized_actions(
    pr_view: dict[str, Any],
    *,
    pr: int,
    head: str,
    merge_packet: dict[str, Any],
    required_checks: list[dict[str, Any]] | None = None,
    require_branch_protection_token: bool = False,
    repo: str = DEFAULT_REPO,
    cwd: Path | None = None,
    trusted_operator_logins: Sequence[str] | None = None,
    permission_checker: PermissionChecker | None = None,
    diagnostic_report: dict[str, Any] | None = None,
) -> set[str]:
    if not _required_checks_are_green(required_checks):
        return set()
    if not _human_settlement_status_is_success(pr_view):
        return set()
    if not _packet_has_counted_tier4_evidence(merge_packet, pr=pr):
        return set()

    report = diagnostic_report
    if report is None:
        report = authorization_diagnostics(
            pr_view,
            pr=pr,
            head=head,
            require_branch_protection_token=require_branch_protection_token,
            repo=repo,
            cwd=cwd,
            trusted_operator_logins=trusted_operator_logins,
            permission_checker=permission_checker,
        )
    accepted_diagnostics = _accepted_authorization_diagnostics(report)
    if not accepted_diagnostics:
        return set()
    if not _human_settlement_status_is_bound_to_accepted_comment(
        pr_view,
        accepted_diagnostics,
    ):
        return set()
    for diagnostic in accepted_diagnostics:
        if not isinstance(diagnostic, dict) or not diagnostic.get("accepted"):
            continue
        actions = diagnostic.get("authorized_actions")
        if not isinstance(actions, list):
            return set()
        return {str(action) for action in actions if str(action)}
    return set()


def has_operator_authorization(
    pr_view: dict[str, Any],
    *,
    pr: int,
    head: str,
    merge_packet: dict[str, Any],
    required_checks: list[dict[str, Any]] | None = None,
    require_branch_protection_token: bool = False,
    repo: str = DEFAULT_REPO,
    cwd: Path | None = None,
    trusted_operator_logins: Sequence[str] | None = None,
    permission_checker: PermissionChecker | None = None,
    diagnostic_report: dict[str, Any] | None = None,
) -> bool:
    return bool(
        _operator_authorized_actions(
            pr_view,
            pr=pr,
            head=head,
            merge_packet=merge_packet,
            required_checks=required_checks,
            require_branch_protection_token=require_branch_protection_token,
            repo=repo,
            cwd=cwd,
            trusted_operator_logins=trusted_operator_logins,
            permission_checker=permission_checker,
            diagnostic_report=diagnostic_report,
        )
    )


def _entry_for_pr(merge_packet: dict[str, Any], *, pr: int) -> dict[str, Any] | None:
    entries = merge_packet.get("entries")
    if not isinstance(entries, list):
        return None
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get("pr_number") or "") == str(pr):
            return entry
    return None


def _packet_marks_tier4_human_settlement(merge_packet: dict[str, Any], *, pr: int) -> bool:
    entry = _entry_for_pr(merge_packet, pr=pr)
    if not entry:
        return False
    status = str(entry.get("status") or "")
    if status not in ALLOWED_TIER4_ENTRY_STATUSES:
        return False
    if bool(entry.get("requires_human_risk_settlement")):
        return True
    required = merge_packet.get("human_risk_settlement_required")
    return isinstance(required, list) and str(pr) in {str(item) for item in required}


def _numeric_not_ready_allowed(
    merge_packet: dict[str, Any], *, pr: int, pr_view: dict[str, Any]
) -> bool:
    if _packet_marks_tier4_human_settlement(merge_packet, pr=pr):
        return True
    entry = _entry_for_pr(merge_packet, pr=pr)
    if not entry:
        return False
    return bool(
        pr_view.get("isDraft")
        and entry.get("status") == "repair_or_wait"
        and entry.get("verdict") == "not_ready_for_settlement"
        and entry.get("requires_human_risk_settlement")
        and entry.get("requires_human_preapproval")
    )


def _packet_marks_tier4_settlement_surface(merge_packet: dict[str, Any], *, pr: int) -> bool:
    entry = _entry_for_pr(merge_packet, pr=pr)
    if not entry:
        return False
    if bool(entry.get("requires_human_risk_settlement")):
        return True
    required = merge_packet.get("human_risk_settlement_required")
    if isinstance(required, list) and str(pr) in {str(item) for item in required}:
        return True
    tier = entry.get("tier")
    if not isinstance(tier, str | int | float):
        return False
    try:
        return int(tier) >= 4
    except (TypeError, ValueError):
        return False


def _mergeability_blockers(*, pr: int, pr_view: dict[str, Any]) -> list[str]:
    merge_state = str(pr_view.get("mergeStateStatus") or "")
    if merge_state in BLOCKING_MERGE_STATES:
        return [f"PR #{pr} is {merge_state}"]
    rest_fallback_meta = pr_view.get("_rest_fallback")
    if (
        merge_state == "UNKNOWN"
        and isinstance(rest_fallback_meta, dict)
        and bool(rest_fallback_meta.get("enabled"))
    ):
        return [f"PR #{pr} mergeability is UNKNOWN"]
    return []


def _required_check_name(check: dict[str, Any]) -> str:
    return str(check.get("name") or check.get("workflow") or "required check")


def _required_check_state(check: dict[str, Any]) -> str:
    return str(check.get("state") or check.get("conclusion") or "UNKNOWN").upper()


def _merge_packet_entry_diagnostics(merge_packet: dict[str, Any], *, pr: int) -> dict[str, Any]:
    """Surface the human-readable merge-packet entry fields for ``--check``.

    These mirror what an operator would otherwise have to read out of
    ``review-queue merge-packet --json`` by hand to learn *why* a PR is not yet
    settle-eligible (tier, status/verdict, failing-check summary, counted model
    families, and the explicit ``reasons`` list). All fields are best-effort: a
    packet without a matching entry yields empty/``None`` values rather than
    raising.
    """
    entry = _entry_for_pr(merge_packet, pr=pr) or {}
    reasons = entry.get("reasons")
    counted = entry.get("counted_model_families")
    return {
        "tier": entry.get("tier"),
        "tier_name": entry.get("tier_name"),
        "status": entry.get("status"),
        "verdict": entry.get("verdict"),
        "machine_recommendation": entry.get("machine_recommendation"),
        "checks_summary": entry.get("checks_summary"),
        "counted_model_families": list(counted) if isinstance(counted, list) else [],
        "reasons": [str(item) for item in reasons] if isinstance(reasons, list) else [],
        "requires_human_risk_settlement": bool(entry.get("requires_human_risk_settlement")),
        "requires_human_preapproval": bool(entry.get("requires_human_preapproval")),
    }


def _required_check_context(check: dict[str, Any]) -> str:
    return str(check.get("name") or check.get("context") or "").strip()


def _required_check_is_merge_quorum(check: dict[str, Any]) -> bool:
    return _required_check_context(check) == MERGE_QUORUM_CONTEXT


def _required_quorum_only_failure(required_checks: list[dict[str, Any]] | None) -> bool:
    if not required_checks:
        return False
    saw_quorum_failure = False
    for check in required_checks:
        if not isinstance(check, dict):
            continue
        state = _required_check_state(check)
        if _state_is_success(state):
            continue
        if _required_check_is_merge_quorum(check):
            saw_quorum_failure = True
            continue
        return False
    return saw_quorum_failure


def _packet_proves_quorum_missing_settlement(merge_packet: dict[str, Any], *, pr: int) -> bool:
    entry = _entry_for_pr(merge_packet, pr=pr)
    if not entry:
        return False
    if bool(entry.get("unresolved_dissent")):
        return False
    return _packet_marks_tier4_human_settlement(merge_packet, pr=pr)


def _check_link(check: dict[str, Any]) -> str:
    for key in ("link", "detailsUrl", "details_url", "target_url", "targetUrl", "url"):
        value = str(check.get(key) or "").strip()
        if value:
            return value
    return ""


def _github_actions_job_id_from_url(url: str) -> str:
    if "/job/" not in url:
        return ""
    tail = url.split("/job/", 1)[1]
    candidate = tail.split("?", 1)[0].split("#", 1)[0].split("/", 1)[0]
    return candidate if candidate.isdigit() else ""


def _quorum_failure_log_proves_missing_settlement(
    required_checks: list[dict[str, Any]] | None,
    *,
    repo: str,
    cwd: Path,
    head: str,
) -> bool:
    if not _required_quorum_only_failure(required_checks):
        return False
    quorum_check = next(
        (
            check
            for check in required_checks or []
            if isinstance(check, dict)
            and _required_check_is_merge_quorum(check)
            and not _state_is_success(_required_check_state(check))
        ),
        None,
    )
    if quorum_check is None:
        return False
    job_id = _github_actions_job_id_from_url(_check_link(quorum_check))
    if not job_id:
        return False
    try:
        log = _run_text_command(
            ["gh", "run", "view", "--repo", repo, "--job", job_id, "--log-failed"],
            cwd=cwd,
        )
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return False
    lowered = log.lower()
    head_prefix = str(head or "").strip().lower()[:12]
    if len(head_prefix) < 12:
        return False
    return (
        "no human settlement signal is recorded" in lowered
        and HUMAN_SETTLEMENT_CONTEXT.lower() in lowered
        and head_prefix in lowered
    )


def _rollup_check_context(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("context") or "").strip()


def _rollup_check_state(item: dict[str, Any]) -> str:
    return str(item.get("conclusion") or item.get("state") or "UNKNOWN").upper()


def _required_check_visibility_skew_report(
    *,
    pr: int,
    head: str,
    pr_view: dict[str, Any],
    required_checks: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not _required_checks_are_green(required_checks):
        return None
    rollup = pr_view.get("statusCheckRollup")
    if not isinstance(rollup, list):
        return None

    green_required: dict[str, dict[str, Any]] = {}
    for check in required_checks or []:
        if not isinstance(check, dict):
            continue
        context = _required_check_context(check)
        if context and _state_is_success(_required_check_state(check)):
            green_required[context] = check
    if not green_required:
        return None

    stale_failed: list[dict[str, Any]] = []
    for item in rollup:
        if not isinstance(item, dict):
            continue
        context = _rollup_check_context(item)
        if context not in green_required:
            continue
        state = _rollup_check_state(item)
        if _state_is_success(state):
            continue
        stale_failed.append(
            {
                "context": context,
                "rollup_state": state,
                "rollup_status": str(item.get("status") or ""),
                "details_url": item.get("detailsUrl") or item.get("targetUrl") or "",
                "completed_at": item.get("completedAt"),
                "required_state": _required_check_state(green_required[context]),
                "required_link": green_required[context].get("link") or "",
            }
        )

    if not stale_failed:
        return None
    return {
        "blocker": REQUIRED_CHECK_VISIBILITY_SKEW_BLOCKER,
        "pr": pr,
        "head": head,
        "merge_state": pr_view.get("mergeStateStatus"),
        "stale_failed_required_contexts": stale_failed,
        "message": (
            "GraphQL statusCheckRollup still contains a non-green required context "
            "that conflicts with gh pr checks --required reporting that context green; "
            "refusing Tier 4 merge/apply before mergePullRequest can reject on stale state."
        ),
        "next_prompt": _visibility_skew_next_prompt(pr=pr, head=head),
    }


_RUN_ID_RE = re.compile(r"/actions/runs/(\d+)")


def _superseded_run_ids(skew_report: Mapping[str, Any]) -> list[str]:
    """Extract the workflow run IDs of the superseded stale-FAILURE contexts.

    Every context in ``stale_failed_required_contexts`` is, by construction of
    :func:`_required_check_visibility_skew_report`, a required check that GitHub's
    ``--required`` surface reports GREEN (a newer successful run exists) yet the
    GraphQL rollup still lists as failed. Re-running that superseded failed run so
    it re-concludes green is therefore always safe — we never re-run a context
    whose latest run is genuinely failing. Run IDs are parsed from each context's
    ``details_url``; contexts without a parseable run URL are skipped.
    """
    run_ids: list[str] = []
    for context in skew_report.get("stale_failed_required_contexts") or []:
        if not isinstance(context, Mapping):
            continue
        url = str(context.get("details_url") or "")
        match = _RUN_ID_RE.search(url)
        if match:
            run_id = match.group(1)
            if run_id not in run_ids:
                run_ids.append(run_id)
    return run_ids


def _rerun_workflow_run(run_id: str, *, cwd: Path, repo: str) -> bool:
    """``gh run rerun <run_id>`` (a read-safe CI re-trigger). Returns success."""
    try:
        _run_text_command(["gh", "run", "rerun", run_id, "--repo", repo], cwd=cwd)
        return True
    except (subprocess.CalledProcessError, RuntimeError, OSError):
        return False


def _auto_resolve_visibility_skew(
    *,
    pr: int,
    head: str,
    repo: str,
    cwd: Path,
    skew_report: Mapping[str, Any],
    max_reruns: int,
    timeout_seconds: float,
    poll_seconds: float,
    load_inputs: Callable[[], tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]],
    rerun_run: Callable[[str], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = lambda _msg: None,
) -> dict[str, Any]:
    """Bounded rerun-and-wait to clear a superseded required-check visibility skew.

    Re-runs the superseded stale-FAILURE run(s), then polls the live rollup until
    the skew clears or the budget is spent. The timeout is split into ``max_reruns``
    windows; a fresh re-trigger opens each window. Purely mechanical: only re-runs
    already-superseded runs (see :func:`_superseded_run_ids`), never edits files,
    never touches branch protection. Dependencies are injected so this is unit-
    testable without the network or real sleeps.

    Returns ``{cleared: bool, reruns: [...], triggers: int, reason: str}``.
    """
    rerun = rerun_run or (lambda rid: _rerun_workflow_run(rid, cwd=cwd, repo=repo))
    reruns: list[dict[str, Any]] = []
    current_skew: Mapping[str, Any] | None = skew_report
    max_reruns = max(1, int(max_reruns))
    window = timeout_seconds / max_reruns

    for trigger in range(max_reruns):
        if current_skew is None:
            break
        run_ids = _superseded_run_ids(current_skew)
        if not run_ids:
            return {
                "cleared": False,
                "reruns": reruns,
                "triggers": trigger,
                "reason": "no parseable superseded run id in skew report; cannot auto-resolve",
            }
        for run_id in run_ids:
            ok = rerun(run_id)
            reruns.append({"run_id": run_id, "ok": ok})
            log(f"re-ran superseded merge-quorum run {run_id} (ok={ok})")

        window_deadline = monotonic() + window
        while monotonic() < window_deadline:
            sleep(poll_seconds)
            pr_view, _packet, required_checks = load_inputs()
            current_skew = _required_check_visibility_skew_report(
                pr=pr, head=head, pr_view=pr_view, required_checks=required_checks
            )
            if current_skew is None:
                log("required-check visibility skew cleared")
                return {
                    "cleared": True,
                    "reruns": reruns,
                    "triggers": trigger + 1,
                    "reason": "skew cleared after rerun-and-wait",
                }

    return {
        "cleared": False,
        "reruns": reruns,
        "triggers": max_reruns,
        "reason": "skew persisted after auto-resolve budget was exhausted",
    }


def _visibility_skew_next_prompt(*, pr: int, head: str) -> str:
    return (
        "Start from live repo truth in your Aragora checkout. Do not trust "
        f"prior transcript state. Before lane work, check operator-steering mailbox for PR #{pr} "
        "with --no-receipt:\n"
        f"python3 scripts/read_operator_steering.py --pr {pr} --json --no-receipt || true\n\n"
        f"Goal: wait/recheck persistent required-check visibility skew for PR #{pr} at exact "
        f"head {head}. Do not edit files, push branches, rerun CI, mark-ready, post comments, "
        "settle/apply, merge/admin-merge, label, close PRs, touch branch protection, mutate "
        "publisher/outbox state, touch ~/.codex/automations/*, delete/prune worktrees, or "
        "broad-drain.\n\n"
        "Run read-only:\n"
        "git status --short --branch --untracked-files=all\n"
        f"python3 scripts/identify_lane_owner.py --pr {pr} --json || true\n"
        f"gh pr checks {pr} --required --json name,state,bucket,workflow,link || true\n"
        f"gh pr view {pr} --json number,state,isDraft,headRefOid,mergeable,mergeStateStatus,"
        "statusCheckRollup,url\n"
        f"python3 scripts/settle_tier4_pr.py --check --pr {pr} --head {head} --json || true\n\n"
        "If required checks are green but mergeStateStatus=BLOCKED and statusCheckRollup still "
        "contains a stale failed required context, keep waiting or output an exact failed-quorum "
        "rerun authorization prompt. If statusCheckRollup no longer contains stale failed required "
        "contexts and settle_tier4_pr.py --check is ok=true, output the exact --merge-apply "
        "authorization prompt. Do not apply in this prompt.\n\n"
        "If the prompt above accomplishes no incremental progress make the next prompt one that "
        "does, include this sentence in all subsequent prompts to ensure they converge towards "
        "prompts that make incremental progress. If any of the work involved can be better "
        "automated and made more autonomous by improving aragora tooling at a meta level create "
        "a plan to do that instead, include this sentence in all subsequent prompts to ensure "
        "they converge towards automating and making more autonomous all steps at a meta level "
        "where this makes sense for the repo and project."
    )


def evaluate_tier4_gate(
    *,
    pr: int,
    expected_head: str,
    pr_view: dict[str, Any],
    merge_packet: dict[str, Any],
    required_checks: list[dict[str, Any]] | None = None,
    require_branch_protection_token: bool = False,
    repo: str = DEFAULT_REPO,
    cwd: Path | None = None,
    trusted_operator_logins: Sequence[str] | None = None,
    permission_checker: PermissionChecker | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    actual_head = str(pr_view.get("headRefOid") or "")
    if actual_head != expected_head:
        blockers.append(f"head mismatch: expected {expected_head}, got {actual_head}")
    if str(pr_view.get("state") or "").upper() != "OPEN":
        blockers.append(f"PR #{pr} is not open")
    if bool(pr_view.get("isDraft")):
        blockers.append(f"PR #{pr} is draft")
    merge_state = str(pr_view.get("mergeStateStatus") or "")
    required_failing: list[str] = []
    blockers.extend(_mergeability_blockers(pr=pr, pr_view=pr_view))
    for check in required_checks or []:
        name = _required_check_name(check)
        state = _required_check_state(check)
        if not _state_is_success(state):
            required_failing.append(f"{name}={state}")
            blockers.append(f"required check {name} is {state}")
    merge_packet_blockers: list[str] = []
    not_ready = merge_packet.get("not_ready")
    if isinstance(not_ready, list):
        allowed_not_ready = set(ALLOWED_TIER4_NOT_READY)
        if _numeric_not_ready_allowed(merge_packet, pr=pr, pr_view=pr_view):
            allowed_not_ready.add(str(pr))
        merge_packet_blockers = sorted({str(item) for item in not_ready} - allowed_not_ready)
        if merge_packet_blockers:
            blockers.append(
                f"merge-packet has unexpected blockers: {', '.join(merge_packet_blockers)}"
            )

    required_checks_green = _required_checks_are_green(required_checks)
    authorization_precondition_blockers: list[str] = []
    if actual_head == expected_head:
        if not required_checks:
            authorization_precondition_blockers.append(REQUIRED_CHECKS_BLOCKER)
        elif not required_checks_green:
            pass
        elif not _human_settlement_status_is_success(pr_view):
            authorization_precondition_blockers.append(HUMAN_SETTLEMENT_STATUS_BLOCKER)
        elif not _packet_has_counted_tier4_evidence(merge_packet, pr=pr):
            authorization_precondition_blockers.append(TIER4_EVIDENCE_BLOCKER)
    blockers.extend(authorization_precondition_blockers)

    diagnostic_report = authorization_diagnostics(
        pr_view,
        pr=pr,
        head=expected_head,
        require_branch_protection_token=require_branch_protection_token,
        repo=repo,
        cwd=cwd,
        trusted_operator_logins=trusted_operator_logins,
        permission_checker=permission_checker,
        evaluate_member_permissions=not blockers,
    )
    authorized_actions: set[str] = set()
    status_pin_blocker = False
    if (
        actual_head == expected_head
        and required_checks_green
        and not authorization_precondition_blockers
        and not blockers
    ):
        accepted_diagnostics = _accepted_authorization_diagnostics(diagnostic_report)
        if accepted_diagnostics and not _human_settlement_status_is_bound_to_accepted_comment(
            pr_view,
            accepted_diagnostics,
        ):
            status_pin_blocker = True
            blockers.append(HUMAN_SETTLEMENT_STATUS_PIN_BLOCKER)
        if not status_pin_blocker:
            authorized_actions = _operator_authorized_actions(
                pr_view,
                pr=pr,
                head=expected_head,
                merge_packet=merge_packet,
                required_checks=required_checks,
                require_branch_protection_token=require_branch_protection_token,
                repo=repo,
                cwd=cwd,
                trusted_operator_logins=trusted_operator_logins,
                permission_checker=permission_checker,
                diagnostic_report=diagnostic_report,
            )
        if not authorized_actions and not status_pin_blocker:
            blockers.append(OPERATOR_COMMENT_BLOCKER)

    packet_diagnostics = _merge_packet_entry_diagnostics(merge_packet, pr=pr)
    return {
        "ok": not blockers,
        "pr": pr,
        "expected_head": expected_head,
        "actual_head": actual_head,
        "head_match": actual_head == expected_head,
        "merge_state": merge_state,
        "blockers": blockers,
        "required_failing": required_failing,
        "merge_packet_blockers": merge_packet_blockers,
        "merge_packet": packet_diagnostics,
        "reasons": packet_diagnostics["reasons"],
        "settle_eligible": not blockers,
        "authorized_actions": sorted(authorized_actions),
        **diagnostic_report,
    }


def evaluate_tier4_settlement_preconditions(
    *,
    pr: int,
    expected_head: str,
    pr_view: dict[str, Any],
    merge_packet: dict[str, Any],
    required_checks: list[dict[str, Any]] | None = None,
    quorum_missing_settlement_proof: bool = False,
    trusted_operator_logins: Sequence[str] | None = None,
    invoker_login: str | None = None,
    invoker_has_admin_permission: bool | None = None,
    require_trusted_invoker: bool = False,
    require_invoker_admin_permission: bool = False,
) -> dict[str, Any]:
    blockers: list[str] = []
    actual_head = str(pr_view.get("headRefOid") or "")
    if actual_head != expected_head:
        blockers.append(f"head mismatch: expected {expected_head}, got {actual_head}")
    if str(pr_view.get("state") or "").upper() != "OPEN":
        blockers.append(f"PR #{pr} is not open")
    if bool(pr_view.get("isDraft")):
        blockers.append(f"PR #{pr} is draft")
    merge_state = str(pr_view.get("mergeStateStatus") or "")
    blockers.extend(_mergeability_blockers(pr=pr, pr_view=pr_view))

    if not required_checks:
        blockers.append(REQUIRED_CHECKS_BLOCKER)
    else:
        packet_missing_settlement_proof = _packet_proves_quorum_missing_settlement(
            merge_packet, pr=pr
        )
        has_quorum_missing_settlement_proof = (
            packet_missing_settlement_proof or quorum_missing_settlement_proof
        )
        quorum_only_failure = _required_quorum_only_failure(required_checks)
        for check in required_checks:
            name = _required_check_name(check)
            state = _required_check_state(check)
            if _state_is_success(state):
                continue
            if (
                _required_check_is_merge_quorum(check)
                and quorum_only_failure
                and has_quorum_missing_settlement_proof
            ):
                continue
            blockers.append(f"required check {name} is {state}")
        if quorum_only_failure and not has_quorum_missing_settlement_proof:
            blockers.append(MERGE_QUORUM_SETTLEMENT_PROOF_BLOCKER)

    not_ready = merge_packet.get("not_ready")
    if isinstance(not_ready, list):
        allowed_not_ready = set(ALLOWED_TIER4_NOT_READY)
        allowed_not_ready.add(str(pr))
        unexpected = sorted({str(item) for item in not_ready} - allowed_not_ready)
        if unexpected:
            blockers.append(f"merge-packet has unexpected blockers: {', '.join(unexpected)}")

    if not _packet_marks_tier4_settlement_surface(merge_packet, pr=pr):
        blockers.append("merge-packet does not mark Tier 4 human-risk settlement")
    if not _packet_has_counted_tier4_evidence(merge_packet, pr=pr):
        blockers.append(TIER4_EVIDENCE_BLOCKER)

    allowed_logins = _trusted_operator_logins(trusted_operator_logins)
    normalized_invoker = str(invoker_login or "").strip().lower()
    if require_trusted_invoker:
        if not allowed_logins:
            blockers.append(SETTLE_ONLY_TRUSTED_OPERATOR_BLOCKER)
        elif not normalized_invoker:
            blockers.append(SETTLE_ONLY_INVOKER_BLOCKER)
        elif normalized_invoker not in allowed_logins:
            blockers.append(f"gh login {normalized_invoker} is not in trusted operator allowlist")
    if require_invoker_admin_permission:
        if not normalized_invoker and SETTLE_ONLY_INVOKER_BLOCKER not in blockers:
            blockers.append(SETTLE_ONLY_INVOKER_BLOCKER)
        elif allowed_logins and normalized_invoker not in allowed_logins:
            pass
        elif invoker_has_admin_permission is not True:
            blockers.append(
                f"gh login {normalized_invoker} lacks {SETTLE_ONLY_ADMIN_PERMISSION_BLOCKER}"
            )

    return {
        "ok": not blockers,
        "pr": pr,
        "expected_head": expected_head,
        "actual_head": actual_head,
        "merge_state": merge_state,
        "trusted_operator_logins": sorted(allowed_logins),
        "invoker_login": normalized_invoker,
        "invoker_has_admin_permission": invoker_has_admin_permission,
        "blockers": blockers,
    }


def _subprocess_env(*, prefer_app: bool, write_op: bool) -> dict[str, str]:
    if write_op:
        return github_cli_env(os.environ, prefer_app=False)
    return github_cli_env(os.environ, prefer_app=prefer_app)


def _run_process(
    command: list[str],
    *,
    cwd: Path | None = None,
    timeout: float = 120,
    prefer_app: bool = True,
    write_op: bool = False,
    input_text: str | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        if command and command[0] == "gh" and input_text is None and gh_subprocess_run is not None:
            result = gh_subprocess_run(
                command[1:],
                cwd=cwd,
                timeout=timeout,
                prefer_app=prefer_app,
                write_op=write_op,
                env=os.environ,
            )
            if check and result.returncode != 0:
                raise subprocess.CalledProcessError(
                    result.returncode,
                    command,
                    output=result.stdout,
                    stderr=result.stderr,
                )
            return result
        return subprocess.run(
            command,
            cwd=cwd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_subprocess_env(prefer_app=prefer_app, write_op=write_op),
            check=check,
        )
    except subprocess.TimeoutExpired as exc:
        timeout_value = int(exc.timeout if exc.timeout is not None else timeout)
        raise RuntimeError(f"{shlex.join(command)} timed out after {timeout_value}s") from exc
    except OSError as exc:
        raise RuntimeError(f"{shlex.join(command)} failed to start: {exc}") from exc


def _run_json(
    command: list[str],
    *,
    cwd: Path | None = None,
    prefer_app: bool = True,
    write_op: bool = False,
) -> dict[str, Any]:
    result = _run_process(command, cwd=cwd, prefer_app=prefer_app, write_op=write_op)
    if result.returncode != 0:
        raise RuntimeError(f"{shlex.join(command)} failed: {_command_failure_detail(result)}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{shlex.join(command)} did not emit JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{shlex.join(command)} emitted non-object JSON")
    return payload


def _run_json_any(
    command: list[str],
    *,
    cwd: Path | None = None,
    prefer_app: bool = True,
    write_op: bool = False,
) -> Any:
    result = _run_process(command, cwd=cwd, prefer_app=prefer_app, write_op=write_op)
    if result.returncode != 0:
        raise RuntimeError(f"{shlex.join(command)} failed: {_command_failure_detail(result)}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{shlex.join(command)} did not emit JSON") from exc


def _bounded_detail(value: str) -> str:
    text = value.strip()
    if len(text) <= COMMAND_FAILURE_DETAIL_LIMIT:
        return text
    return f"{text[:COMMAND_FAILURE_DETAIL_LIMIT]}..."


def _json_stdout_error(stdout: str) -> str:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in ("error", "message"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    blockers = payload.get("blockers")
    if isinstance(blockers, list):
        normalized = [str(item).strip() for item in blockers if str(item).strip()]
        if normalized:
            return "; ".join(normalized)
    return ""


def _command_failure_detail(result: subprocess.CompletedProcess[str]) -> str:
    stderr = result.stderr.strip()
    if stderr:
        return _bounded_detail(stderr)
    stdout_error = _json_stdout_error(result.stdout)
    if stdout_error:
        return _bounded_detail(stdout_error)
    stdout = result.stdout.strip()
    if stdout:
        return _bounded_detail(stdout)
    return f"exit code {result.returncode}"


def _looks_like_graphql_rate_limit_error(error: object) -> bool:
    text = str(error or "").lower()
    # Current gh CLI surfaces exhausted PR GraphQL calls as
    # "GraphQL: API rate limit ..."; REST rate limits should not switch to
    # REST fallback because those fallback calls would share the same blocker.
    return "rate limit" in text and (
        "graphql" in text or "gh pr view" in text or "gh pr checks" in text
    )


def _gh_json_for_rest_fallback(command: list[str], *, cwd: Path) -> Any:
    try:
        return _run_json_any(["gh", *command], cwd=cwd)
    except RuntimeError as exc:
        raise _GhError(str(exc)) from exc


def _load_pr_view(pr: int, *, cwd: Path, repo: str) -> dict[str, Any]:
    try:
        pr_view = _run_json(
            [
                "gh",
                "pr",
                "view",
                str(pr),
                "--repo",
                repo,
                "--json",
                (
                    "headRefOid,state,isDraft,mergeStateStatus,baseRefName,comments,reviews,commits,"
                    "statusCheckRollup,url"
                ),
            ],
            cwd=cwd,
        )
    except RuntimeError as exc:
        if not _looks_like_graphql_rate_limit_error(exc):
            raise
        try:
            pr_view = rest_fallback._hydrate_pr_with_rest_fallback(
                number=pr,
                repo_slug=repo,
                source_error=str(exc),
                gh_json=lambda command: _gh_json_for_rest_fallback(command, cwd=cwd),
            )
        except _GhError as rest_exc:
            raise RuntimeError(str(rest_exc)) from rest_exc
    pr_view["headCommittedDate"] = _head_committed_at(pr_view)
    return pr_view


def _check_run_state(run: dict[str, Any]) -> str:
    if rest_fallback._direct_check_run_is_success(run):
        return "SUCCESS"
    status = str(run.get("status") or "").strip().upper()
    conclusion = str(run.get("conclusion") or "").strip().upper()
    if status in {"QUEUED", "IN_PROGRESS", "PENDING", "REQUESTED", "WAITING"}:
        return "PENDING"
    if conclusion in {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STALE"}:
        return "FAILURE"
    return "UNKNOWN"


def _commit_status_state(status: dict[str, Any]) -> str:
    state = str(status.get("state") or "").strip().upper()
    if state == "SUCCESS":
        return "SUCCESS"
    if state in {"PENDING", "EXPECTED"}:
        return "PENDING"
    if state in {"FAILURE", "ERROR"}:
        return "FAILURE"
    return "UNKNOWN"


def _rest_page_endpoint(endpoint: str, page: int) -> str:
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}page={page}"


def _fetch_direct_commit_check_runs_for_gate(
    repo: str, head: str, *, gh_json: Callable[[list[str]], Any]
) -> tuple[list[dict[str, Any]], str]:
    endpoint = f"repos/{repo}/commits/{head}/check-runs?per_page=100"
    runs: list[dict[str, Any]] = []
    try:
        for page in range(1, 101):
            current_endpoint = endpoint if page == 1 else _rest_page_endpoint(endpoint, page)
            payload = gh_json(["api", current_endpoint])
            if not isinstance(payload, dict):
                return [], f"{current_endpoint} returned a non-object payload"
            page_runs = [run for run in payload.get("check_runs") or [] if isinstance(run, dict)]
            runs.extend(page_runs)
            total_count = payload.get("total_count")
            if isinstance(total_count, int) and len(runs) >= total_count:
                break
            if len(page_runs) < 100:
                break
    except Exception as exc:
        return [], str(exc)
    return runs, ""


def _rest_status_creator_login(status: dict[str, Any]) -> str:
    creator = status.get("creator")
    if isinstance(creator, dict):
        login = str(creator.get("login") or "").strip()
        if login:
            return login
    for key in ("creator_login", "creatorLogin"):
        login = str(status.get(key) or "").strip()
        if login:
            return login
    user = status.get("user")
    if isinstance(user, dict):
        return str(user.get("login") or "").strip()
    return ""


def _normalize_rest_status_for_gate(status: dict[str, Any]) -> dict[str, Any]:
    creator_login = _rest_status_creator_login(status)
    return {
        "context": str(status.get("context") or "").strip(),
        "state": str(status.get("state") or "").strip().upper(),
        "targetUrl": str(status.get("target_url") or "").strip(),
        "creator": {"login": creator_login} if creator_login else {},
        "updatedAt": str(status.get("updated_at") or "").strip(),
        "createdAt": str(status.get("created_at") or "").strip(),
    }


def _fetch_direct_commit_statuses_for_gate(
    repo: str, head: str, *, gh_json: Callable[[list[str]], Any]
) -> tuple[list[dict[str, Any]], str]:
    endpoint = f"repos/{repo}/commits/{head}/statuses?per_page=100"
    statuses: list[dict[str, Any]] = []
    try:
        for page in range(1, 101):
            current_endpoint = endpoint if page == 1 else _rest_page_endpoint(endpoint, page)
            payload = gh_json(["api", current_endpoint])
            if not isinstance(payload, list):
                return [], f"{current_endpoint} returned a non-list payload"
            statuses.extend(
                _normalize_rest_status_for_gate(status)
                for status in payload
                if isinstance(status, dict)
            )
            if len(payload) < 100:
                break
    except Exception as exc:
        return [], str(exc)
    return statuses, ""


def _attach_direct_commit_statuses_for_gate(
    pr_view: dict[str, Any], *, cwd: Path, repo: str
) -> None:
    head = str(pr_view.get("headRefOid") or "").strip()
    if not head:
        return
    statuses, _status_error = _fetch_direct_commit_statuses_for_gate(
        repo,
        head,
        gh_json=lambda command: _gh_json_for_rest_fallback(command, cwd=cwd),
    )
    if statuses:
        pr_view["commitStatuses"] = statuses


def _strict_branch_freshness_state(
    *, repo: str, base_ref: str, head: str, gh_json: Callable[[list[str]], Any]
) -> str:
    try:
        payload = gh_json(
            [
                "api",
                f"repos/{repo}/compare/{quote(base_ref, safe='')}...{quote(head, safe='')}",
            ]
        )
    except Exception:
        return "UNKNOWN"
    if not isinstance(payload, dict):
        return "UNKNOWN"
    status = str(payload.get("status") or "").strip().lower()
    if status in {"ahead", "identical"}:
        return "SUCCESS"
    if status in {"behind", "diverged"}:
        return "FAILURE"
    return "UNKNOWN"


def _required_checks_from_rest(
    pr_view: dict[str, Any], *, cwd: Path, repo: str
) -> list[dict[str, str]]:
    head = str(pr_view.get("headRefOid") or "").strip()
    base_ref = str(pr_view.get("baseRefName") or "main").strip()
    if not head or not base_ref:
        return []
    gh_json = lambda command: _gh_json_for_rest_fallback(command, cwd=cwd)
    protection = rest_fallback._fetch_required_status_check_protection(
        repo,
        base_ref,
        gh_json=gh_json,
    )
    required_specs = [spec for spec in protection.get("checks") or [] if isinstance(spec, dict)]
    if not protection.get("available") or not required_specs:
        return []
    direct_runs, check_run_error = _fetch_direct_commit_check_runs_for_gate(
        repo, head, gh_json=gh_json
    )
    direct_statuses, status_error = _fetch_direct_commit_statuses_for_gate(
        repo, head, gh_json=gh_json
    )

    checks: list[dict[str, str]] = []
    if check_run_error or status_error:
        checks.append({"name": REQUIRED_CHECK_REST_VISIBILITY_CONTEXT, "state": "UNKNOWN"})
    for spec in required_specs:
        context = str(spec.get("context") or "").strip()
        if not context:
            continue
        run = rest_fallback._latest_direct_check_run_for_required(direct_runs, spec)
        status = (
            None
            if run is not None
            else rest_fallback._latest_direct_status_for_required(
                direct_statuses,
                spec,
            )
        )
        if run is not None:
            state = _check_run_state(run)
        elif status is not None:
            state = _commit_status_state(status)
        else:
            state = "PENDING"
        checks.append({"name": context, "state": state})

    if protection.get("strict"):
        checks.append(
            {
                "name": "strict branch-protection freshness",
                "state": _strict_branch_freshness_state(
                    repo=repo,
                    base_ref=base_ref,
                    head=head,
                    gh_json=gh_json,
                ),
            }
        )
    return checks


def _merge_missing_required_checks(
    required_checks: list[dict[str, Any]],
    fallback_checks: list[dict[str, Any]],
    missing_specs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_contexts = {
        _required_check_context(check)
        for check in required_checks
        if isinstance(check, dict) and _required_check_context(check)
    }
    missing_contexts = {
        str(spec.get("context") or "").strip()
        for spec in missing_specs
        if str(spec.get("context") or "").strip()
    }
    merged = list(required_checks)
    for check in fallback_checks:
        context = _required_check_context(check)
        if not context or context in existing_contexts:
            continue
        if (
            context in missing_contexts
            or context == REQUIRED_CHECK_REST_VISIBILITY_CONTEXT
            or context == "strict branch-protection freshness"
        ):
            merged.append(check)
            existing_contexts.add(context)
    return merged


def _required_checks_with_direct_fallback(
    required_checks: list[dict[str, Any]],
    pr_view: dict[str, Any],
    *,
    cwd: Path,
    repo: str,
) -> list[dict[str, Any]]:
    head = str(pr_view.get("headRefOid") or "").strip()
    base_ref = str(pr_view.get("baseRefName") or "main").strip()
    if not head or not base_ref:
        return required_checks
    gh_json = lambda command: _gh_json_for_rest_fallback(command, cwd=cwd)
    protection = rest_fallback._fetch_required_status_check_protection(
        repo,
        base_ref,
        gh_json=gh_json,
    )
    required_specs = [spec for spec in protection.get("checks") or [] if isinstance(spec, dict)]
    if not protection.get("available") or not required_specs:
        return required_checks

    existing_contexts = {
        _required_check_context(check)
        for check in required_checks
        if isinstance(check, dict) and _required_check_context(check)
    }
    missing_specs = [
        spec
        for spec in required_specs
        if str(spec.get("context") or "").strip()
        and str(spec.get("context") or "").strip() not in existing_contexts
    ]
    if not missing_specs:
        return required_checks
    if protection.get("strict"):
        rest_checks = _required_checks_from_rest(pr_view, cwd=cwd, repo=repo)
        if not rest_checks:
            return [
                *required_checks,
                {"name": REQUIRED_CHECK_REST_VISIBILITY_CONTEXT, "state": "UNKNOWN"},
            ]
        return _merge_missing_required_checks(
            required_checks,
            rest_checks,
            missing_specs,
        ) or [
            *required_checks,
            {"name": REQUIRED_CHECK_REST_VISIBILITY_CONTEXT, "state": "UNKNOWN"},
        ]

    direct_runs, check_run_error = _fetch_direct_commit_check_runs_for_gate(
        repo,
        head,
        gh_json=gh_json,
    )
    direct_statuses, status_error = _fetch_direct_commit_statuses_for_gate(
        repo,
        head,
        gh_json=gh_json,
    )
    if check_run_error or status_error:
        return [
            *required_checks,
            {"name": REQUIRED_CHECK_REST_VISIBILITY_CONTEXT, "state": "UNKNOWN"},
        ]

    filled = list(required_checks)
    for spec in missing_specs:
        context = str(spec.get("context") or "").strip()
        run = rest_fallback._latest_direct_check_run_for_required(direct_runs, spec)
        status = (
            None
            if run is not None
            else rest_fallback._latest_direct_status_for_required(direct_statuses, spec)
        )
        if run is not None:
            filled.append(
                {
                    "name": context,
                    "state": _check_run_state(run),
                    "workflow": "direct required check-run fallback",
                    "source": "direct_commit_check_run",
                }
            )
        elif status is not None:
            filled.append(
                {
                    "name": context,
                    "state": _commit_status_state(status),
                    "workflow": "direct required commit-status fallback",
                    "source": "direct_commit_status",
                }
            )
        else:
            filled.append({"name": context, "state": "PENDING"})
    return filled


def _load_required_checks(
    pr: int, *, cwd: Path, repo: str, pr_view: dict[str, Any]
) -> list[dict[str, Any]]:
    try:
        checks_raw = _run_json_any(
            [
                "gh",
                "pr",
                "checks",
                str(pr),
                "--repo",
                repo,
                "--required",
                "--json",
                "name,state,bucket,workflow,link",
            ],
            cwd=cwd,
        )
    except RuntimeError as exc:
        if not _looks_like_graphql_rate_limit_error(exc):
            raise
        return _required_checks_from_rest(pr_view, cwd=cwd, repo=repo)
    required_checks = (
        [check for check in checks_raw if isinstance(check, dict)]
        if isinstance(checks_raw, list)
        else []
    )
    return _required_checks_with_direct_fallback(
        required_checks,
        pr_view,
        cwd=cwd,
        repo=repo,
    )


def _load_live_inputs(
    pr: int, *, cwd: Path, repo: str = DEFAULT_REPO
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    pr_view = _load_pr_view(pr, cwd=cwd, repo=repo)
    _attach_direct_commit_statuses_for_gate(pr_view, cwd=cwd, repo=repo)
    merge_packet = _run_json(
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
        cwd=cwd,
    )
    required_checks = _load_required_checks(pr, cwd=cwd, repo=repo, pr_view=pr_view)
    return pr_view, merge_packet, required_checks


def _required_status_check_patch(*, repo: str, cwd: Path) -> tuple[list[str], str] | None:
    endpoint = f"repos/{repo}/branches/main/protection/required_status_checks"
    current = _run_json(["gh", "api", endpoint], cwd=cwd, write_op=True)
    contexts = current.get("contexts")
    if not isinstance(contexts, list):
        checks = current.get("checks")
        contexts = (
            [
                str(check.get("context"))
                for check in checks
                if isinstance(check, dict) and check.get("context")
            ]
            if isinstance(checks, list)
            else []
        )
    context_set = {str(context) for context in contexts if str(context)}
    if MERGE_QUORUM_CONTEXT in context_set:
        return None
    context_set.add(MERGE_QUORUM_CONTEXT)
    payload = {"strict": bool(current.get("strict", True)), "contexts": sorted(context_set)}
    return ["gh", "api", "--method", "PATCH", endpoint, "--input", "-"], json.dumps(payload)


def _run_command(command: list[str], *, cwd: Path, input_text: str | None = None) -> None:
    result = _run_process(
        command,
        cwd=cwd,
        input_text=input_text,
        timeout=180,
        prefer_app=True,
        write_op=True,
        check=True,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            command,
            output=result.stdout,
            stderr=result.stderr,
        )


def _run_text_command(command: list[str], *, cwd: Path, input_text: str | None = None) -> str:
    result = _run_process(
        command,
        cwd=cwd,
        input_text=input_text,
        timeout=180,
        prefer_app=True,
        write_op=True,
        check=True,
    )
    return result.stdout.strip()


def _is_not_found_error(exc: BaseException) -> bool:
    text = str(exc)
    return "HTTP 404" in text or "Not Found" in text


def _top_level_rule_absent(top_level: dict[str, Any], key: str) -> bool:
    return top_level.get(key) is None


def _preflight_branch_protection_reconcile(*, repo: str, cwd: Path) -> None:
    try:
        login = _current_gh_login(cwd=cwd)
        has_admin_permission = _login_has_admin_permission(login, repo, cwd)
    except RuntimeError as exc:
        raise Tier4ApplyError(
            f"Tier 4 branch-protection preflight failed before merge mutation: "
            f"could not probe gh admin permission: {exc}",
            phase="preflight",
            mutation_occurred=False,
            completed_commands=0,
            recovery_action=(
                "verify gh auth is available and the eventual merge applier has "
                "branch-protection admin access, then rerun --merge-apply"
            ),
        ) from exc
    if not has_admin_permission:
        raise Tier4ApplyError(
            f"Tier 4 branch-protection preflight failed: gh login {login} lacks admin permission",
            phase="preflight",
            mutation_occurred=False,
            completed_commands=0,
            recovery_action="switch gh auth to an admin/OWNER identity and rerun --merge-apply",
        )

    base = f"repos/{repo}/branches/main/protection"
    try:
        top_level = _run_json(["gh", "api", base], cwd=cwd, write_op=True)
    except RuntimeError as exc:
        raise Tier4ApplyError(
            f"Tier 4 branch-protection preflight failed before merge mutation: {base}: {exc}",
            phase="preflight",
            mutation_occurred=False,
            completed_commands=0,
            recovery_action=(
                "verify the active gh identity has branch-protection admin access, "
                "then rerun --merge-apply"
            ),
        ) from exc

    for key, endpoint in (
        ("required_pull_request_reviews", f"{base}/required_pull_request_reviews"),
        ("required_status_checks", f"{base}/required_status_checks"),
        ("enforce_admins", f"{base}/enforce_admins"),
    ):
        try:
            _run_json(["gh", "api", endpoint], cwd=cwd, write_op=True)
        except RuntimeError as exc:
            if _is_not_found_error(exc) and _top_level_rule_absent(top_level, key):
                continue
            raise Tier4ApplyError(
                "Tier 4 branch-protection preflight failed before merge mutation: "
                f"{endpoint}: {exc}",
                phase="preflight",
                mutation_occurred=False,
                completed_commands=0,
                recovery_action=(
                    "verify the active gh identity has branch-protection admin access, "
                    "then rerun --merge-apply"
                ),
            ) from exc


def _branch_protection_preflight_is_observational_permission_probe(
    exc: Tier4ApplyError,
) -> bool:
    """Return whether ``--check`` only proved the current observer lacks admin."""

    return (
        exc.phase == "preflight"
        and exc.mutation_occurred is False
        and exc.completed_commands == 0
        and "lacks admin permission" in str(exc)
    )


def _branch_protection_preflight_report(
    *,
    repo: str,
    cwd: Path,
    authorized_actions: Collection[str],
) -> dict[str, Any]:
    """Run the merge-apply branch-protection capability probe without mutating."""

    if "branch_protection" not in authorized_actions:
        return {
            "required": False,
            "ok": True,
            "skipped_reason": "branch_protection_reconcile was not authorized",
        }
    try:
        _preflight_branch_protection_reconcile(repo=repo, cwd=cwd)
    except Tier4ApplyError as exc:
        payload = exc.to_payload()
        if _branch_protection_preflight_is_observational_permission_probe(exc):
            return {
                **payload,
                "required": True,
                "ok": True,
                "advisory": True,
                "error": str(exc),
                "non_blocking_reason": (
                    "current gh login lacks admin permission; --check is observational "
                    "and the eventual --merge-apply operator may use a different trusted login"
                ),
            }
        return {
            **payload,
            "required": True,
            "ok": False,
            "error": str(exc),
        }
    return {
        "required": True,
        "ok": True,
        "phase": "preflight",
        "mutation_occurred": False,
        "completed_commands": 0,
    }


def _branch_protection_snapshot(*, repo: str, cwd: Path) -> dict[str, Any]:
    base = f"repos/{repo}/branches/main/protection"
    snapshot: dict[str, Any] = {}
    try:
        top_level = _run_json(["gh", "api", base], cwd=cwd, write_op=True)
    except RuntimeError as exc:
        snapshot["branch_protection"] = {"snapshot_error": str(exc)}
        return snapshot
    snapshot["branch_protection"] = top_level
    for key, endpoint in {
        "required_pull_request_reviews": f"{base}/required_pull_request_reviews",
        "required_status_checks": f"{base}/required_status_checks",
        "enforce_admins": f"{base}/enforce_admins",
    }.items():
        try:
            snapshot[key] = _run_json(["gh", "api", endpoint], cwd=cwd, write_op=True)
        except RuntimeError as exc:
            if _is_not_found_error(exc) and _top_level_rule_absent(top_level, key):
                snapshot[key] = None
                continue
            snapshot[key] = {"snapshot_error": str(exc)}
    return snapshot


def _branch_protection_snapshot_errors(snapshot: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    top_level = snapshot.get("branch_protection")
    if not isinstance(top_level, dict):
        errors.append("branch_protection: missing snapshot")
        top_level = {}
    else:
        snapshot_error = top_level.get("snapshot_error")
        if snapshot_error:
            errors.append(f"branch_protection: {snapshot_error}")
    for key in ("required_pull_request_reviews", "required_status_checks", "enforce_admins"):
        value = snapshot.get(key)
        if value is None and _top_level_rule_absent(top_level, key):
            continue
        if not isinstance(value, dict):
            errors.append(f"{key}: missing snapshot")
            continue
        snapshot_error = value.get("snapshot_error")
        if snapshot_error:
            errors.append(f"{key}: {snapshot_error}")
    return errors


def _snapshot_subresource_available(snapshot: dict[str, Any], key: str) -> bool:
    value = snapshot.get(key)
    return isinstance(value, dict) and "snapshot_error" not in value


def _restore_branch_protection(*, repo: str, cwd: Path, snapshot: dict[str, Any]) -> list[str]:
    base = f"repos/{repo}/branches/main/protection"
    errors: list[str] = []
    reviews = snapshot.get("required_pull_request_reviews")
    if isinstance(reviews, dict) and "snapshot_error" not in reviews:
        command = [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"{base}/required_pull_request_reviews",
            "--input",
            "-",
        ]
        try:
            _run_command(command, cwd=cwd, input_text=json.dumps(reviews))
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"restore required_pull_request_reviews failed: {exc}")
    checks = snapshot.get("required_status_checks")
    if isinstance(checks, dict) and "snapshot_error" not in checks:
        command = [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"{base}/required_status_checks",
            "--input",
            "-",
        ]
        try:
            _run_command(command, cwd=cwd, input_text=json.dumps(checks))
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"restore required_status_checks failed: {exc}")
    enforce = snapshot.get("enforce_admins")
    if isinstance(enforce, dict) and "snapshot_error" not in enforce:
        enabled = bool(enforce.get("enabled", False))
        command = [
            "gh",
            "api",
            "--method",
            "POST" if enabled else "DELETE",
            f"{base}/enforce_admins",
        ]
        try:
            _run_command(command, cwd=cwd)
        except (OSError, subprocess.SubprocessError) as exc:
            errors.append(f"restore enforce_admins failed: {exc}")
    return errors


def _apply_settlement_signal(*, pr: int, head: str, repo: str, cwd: Path) -> list[list[str]]:
    comment_command = [
        "gh",
        "pr",
        "comment",
        str(pr),
        "--body",
        _settlement_comment_template(pr=pr, head=head),
    ]
    status_command = [
        "gh",
        "api",
        "--method",
        "POST",
        f"repos/{repo}/statuses/{head}",
        "-f",
        "state=success",
        "-f",
        f"context={HUMAN_SETTLEMENT_CONTEXT}",
        "-f",
        f"description=Tier 4 exact-head human-risk settlement recorded for PR #{pr}",
    ]
    try:
        comment_url = _run_text_command(comment_command, cwd=cwd).strip()
        if not comment_url:
            raise RuntimeError(
                "Tier 4 settlement comment URL unavailable; refusing to post "
                "unbound aragora/human-settlement status"
            )
        status_command.extend(["-f", f"target_url={comment_url}"])
        _run_command(status_command, cwd=cwd)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"Tier 4 settlement signal failed: {exc}") from exc
    return [comment_command, status_command]


def _apply_merge(
    *,
    pr: int,
    head: str,
    repo: str,
    cwd: Path,
    reconcile_branch_protection: bool = False,
) -> list[list[str]]:
    commands: list[list[str]] = []
    if reconcile_branch_protection:
        _preflight_branch_protection_reconcile(repo=repo, cwd=cwd)
    snapshot = (
        _branch_protection_snapshot(repo=repo, cwd=cwd) if reconcile_branch_protection else {}
    )
    snapshot_errors = (
        _branch_protection_snapshot_errors(snapshot) if reconcile_branch_protection else []
    )
    if snapshot_errors:
        raise Tier4ApplyError(
            "Tier 4 branch-protection snapshot failed before merge mutation: "
            + "; ".join(snapshot_errors),
            phase="branch_protection_snapshot",
            mutation_occurred=False,
            completed_commands=0,
            recovery_action=(
                "verify branch-protection read access and retry --merge-apply before "
                "any merge mutation"
            ),
        )
    merge_command = [
        "gh",
        "pr",
        "merge",
        str(pr),
        "--squash",
        "--admin",
        "--match-head-commit",
        head,
    ]
    merge_invoked = False
    try:
        merge_invoked = True
        _run_command(merge_command, cwd=cwd)
        commands.append(merge_command)

        if not reconcile_branch_protection:
            return commands

        if _snapshot_subresource_available(snapshot, "required_pull_request_reviews"):
            reviews_command = [
                "gh",
                "api",
                "--method",
                "PATCH",
                f"repos/{repo}/branches/main/protection/required_pull_request_reviews",
                "--input",
                "-",
            ]
            _run_command(
                reviews_command,
                cwd=cwd,
                input_text=json.dumps(
                    {
                        "required_approving_review_count": 0,
                        "require_code_owner_reviews": False,
                    }
                ),
            )
            commands.append(reviews_command)

        if _snapshot_subresource_available(snapshot, "required_status_checks"):
            checks_patch = _required_status_check_patch(repo=repo, cwd=cwd)
            if checks_patch is not None:
                checks_command, checks_payload = checks_patch
                _run_command(checks_command, cwd=cwd, input_text=checks_payload)
                commands.append(checks_command)

        if _snapshot_subresource_available(snapshot, "enforce_admins"):
            enforce_command = [
                "gh",
                "api",
                "--method",
                "POST",
                f"repos/{repo}/branches/main/protection/enforce_admins",
            ]
            _run_command(enforce_command, cwd=cwd)
            commands.append(enforce_command)
    except Tier4ApplyError:
        raise
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        rollback_errors = _restore_branch_protection(repo=repo, cwd=cwd, snapshot=snapshot)
        phase = "merge" if not commands else "branch_protection_restore"
        mutation_occurred = bool(commands) or merge_invoked
        recovery_action = (
            "rerun live verification before any retry; if mutation_occurred=true, "
            "inspect PR state and branch protection before rerunning --merge-apply"
        )
        raise Tier4ApplyError(
            "Tier 4 apply failed after partial execution: "
            f"completed_commands={len(commands)} merge_invoked={merge_invoked} "
            f"rollback_errors={rollback_errors}: {exc}",
            phase=phase,
            mutation_occurred=mutation_occurred,
            completed_commands=len(commands),
            rollback_errors=rollback_errors,
            recovery_action=recovery_action,
        ) from exc
    return commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument(
        "--settle-only",
        action="store_true",
        help="Post the exact-head Tier 4 settlement comment/status only; never merge.",
    )
    mode.add_argument(
        "--merge-apply",
        action="store_true",
        help="Apply the already-settled Tier 4 merge/protection action.",
    )
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument(
        "--trusted-operator-login",
        action="append",
        default=[],
        help=(
            "Restrict repo-visible MEMBER authorization comments to this admin "
            "login. Repeatable; also reads comma-separated "
            f"{TRUSTED_OPERATOR_LOGINS_ENV}. If omitted, any live admin MEMBER "
            f"may authorize when {HUMAN_SETTLEMENT_CONTEXT} is success. "
            "--settle-only additionally requires the invoking gh login to be "
            "present in this allowlist and have admin/OWNER authority."
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--skew-auto-resolve",
        action="store_true",
        help=(
            "On --merge-apply, if a required_check_visibility_skew is detected "
            "(a superseded stale-FAILURE required run lingering beside a newer "
            "SUCCESS at the same head), automatically re-run the superseded run(s) "
            "and wait, bounded, for the rollup to clear before applying. Only "
            "re-runs already-superseded runs; never touches branch protection. "
            "Default OFF (falls back to today's block + operator prompt)."
        ),
    )
    parser.add_argument(
        "--skew-max-reruns",
        type=int,
        default=1,
        help="Max superseded-run re-trigger rounds for --skew-auto-resolve (default: 1).",
    )
    parser.add_argument(
        "--skew-timeout-seconds",
        type=float,
        default=300.0,
        help="Total wall-clock budget for --skew-auto-resolve (default: 300).",
    )
    parser.add_argument(
        "--skew-poll-seconds",
        type=float,
        default=20.0,
        help="Poll interval while waiting for the skew to clear (default: 20).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        pr_view, merge_packet, required_checks = _load_live_inputs(
            args.pr, cwd=args.cwd, repo=args.repo
        )
        applied_commands: list[list[str]] = []
        if args.settle_only:
            quorum_missing_settlement_proof = False
            if _required_quorum_only_failure(
                required_checks
            ) and not _packet_proves_quorum_missing_settlement(merge_packet, pr=args.pr):
                quorum_missing_settlement_proof = _quorum_failure_log_proves_missing_settlement(
                    required_checks,
                    repo=args.repo,
                    cwd=args.cwd,
                    head=args.head,
                )
            gate = evaluate_tier4_settlement_preconditions(
                pr=args.pr,
                expected_head=args.head,
                pr_view=pr_view,
                merge_packet=merge_packet,
                required_checks=required_checks,
                quorum_missing_settlement_proof=quorum_missing_settlement_proof,
                trusted_operator_logins=args.trusted_operator_login,
            )
            if not gate["ok"]:
                raise RuntimeError(
                    "Tier 4 settlement preconditions are not satisfied; refusing --settle-only"
                )
            allowed_logins = _trusted_operator_logins(args.trusted_operator_login)
            invoker_login = _current_gh_login(cwd=args.cwd) if allowed_logins else ""
            invoker_has_admin_permission = (
                _login_has_admin_permission(invoker_login, args.repo, args.cwd)
                if invoker_login and invoker_login in allowed_logins
                else None
            )
            gate = evaluate_tier4_settlement_preconditions(
                pr=args.pr,
                expected_head=args.head,
                pr_view=pr_view,
                merge_packet=merge_packet,
                required_checks=required_checks,
                quorum_missing_settlement_proof=quorum_missing_settlement_proof,
                trusted_operator_logins=args.trusted_operator_login,
                invoker_login=invoker_login,
                invoker_has_admin_permission=invoker_has_admin_permission,
                require_trusted_invoker=True,
                require_invoker_admin_permission=True,
            )
            if not gate["ok"]:
                blocker_text = "; ".join(str(blocker) for blocker in gate["blockers"])
                raise RuntimeError(
                    "Tier 4 settlement invoker is not trusted; "
                    f"refusing --settle-only: {blocker_text}"
                )
            applied_commands = _apply_settlement_signal(
                pr=args.pr,
                head=args.head,
                repo=args.repo,
                cwd=args.cwd,
            )
        else:
            gate = evaluate_tier4_gate(
                pr=args.pr,
                expected_head=args.head,
                pr_view=pr_view,
                merge_packet=merge_packet,
                required_checks=required_checks,
                require_branch_protection_token=False,
                repo=args.repo,
                cwd=args.cwd,
                trusted_operator_logins=args.trusted_operator_login,
            )
            if args.check and gate["ok"]:
                branch_protection_preflight = _branch_protection_preflight_report(
                    repo=args.repo,
                    cwd=args.cwd,
                    authorized_actions=set(gate.get("authorized_actions") or []),
                )
                gate["branch_protection_preflight"] = branch_protection_preflight
                preflight_required = bool(branch_protection_preflight.get("required"))
                preflight_ok = bool(branch_protection_preflight.get("ok"))
                if preflight_required and not preflight_ok:
                    error = str(branch_protection_preflight.get("error") or "").strip()
                    blocker = BRANCH_PROTECTION_PREFLIGHT_BLOCKER
                    if error:
                        blocker = f"{blocker}: {error}"
                    gate["blockers"].append(blocker)
                    gate["settle_eligible"] = False
                    gate["ok"] = False
        if args.merge_apply:
            if not gate["ok"]:
                raise RuntimeError("Tier 4 gate is not satisfied; refusing --merge-apply")
            visibility_skew = _required_check_visibility_skew_report(
                pr=args.pr,
                head=args.head,
                pr_view=pr_view,
                required_checks=required_checks,
            )
            skew_auto_resolution: dict[str, Any] | None = None
            if visibility_skew is not None and args.skew_auto_resolve:
                skew_auto_resolution = _auto_resolve_visibility_skew(
                    pr=args.pr,
                    head=args.head,
                    repo=args.repo,
                    cwd=args.cwd,
                    skew_report=visibility_skew,
                    max_reruns=args.skew_max_reruns,
                    timeout_seconds=args.skew_timeout_seconds,
                    poll_seconds=args.skew_poll_seconds,
                    load_inputs=lambda: _load_live_inputs(args.pr, cwd=args.cwd, repo=args.repo),
                    log=lambda msg: None if args.json else print(msg),
                )
                if skew_auto_resolution.get("cleared"):
                    # Skew is gone (the superseded run re-concluded green). Re-read
                    # live inputs so the merge acts on current truth.
                    pr_view, merge_packet, required_checks = _load_live_inputs(
                        args.pr, cwd=args.cwd, repo=args.repo
                    )
                    # Re-evaluate the FULL gate on the fresh inputs — the reload
                    # could have changed gate-relevant state (head moved, a required
                    # check regressed, settlement invalidated); never merge on the
                    # stale pre-resolve gate (#8750 openai [P1]).
                    gate = evaluate_tier4_gate(
                        pr=args.pr,
                        expected_head=args.head,
                        pr_view=pr_view,
                        merge_packet=merge_packet,
                        required_checks=required_checks,
                        require_branch_protection_token=False,
                        repo=args.repo,
                        cwd=args.cwd,
                        trusted_operator_logins=args.trusted_operator_login,
                    )
                    if not gate["ok"]:
                        raise RuntimeError(
                            "Tier 4 gate is not satisfied after skew auto-resolve "
                            "reload; refusing --merge-apply"
                        )
                    visibility_skew = _required_check_visibility_skew_report(
                        pr=args.pr,
                        head=args.head,
                        pr_view=pr_view,
                        required_checks=required_checks,
                    )
            if visibility_skew is not None:
                out = {
                    "ok": False,
                    "blocker": REQUIRED_CHECK_VISIBILITY_SKEW_BLOCKER,
                    "gate": gate,
                    "applied_commands": [],
                    "required_check_visibility_skew": visibility_skew,
                    "next_prompt": visibility_skew["next_prompt"],
                }
                if skew_auto_resolution is not None:
                    out["skew_auto_resolution"] = skew_auto_resolution
                if args.json:
                    print(json.dumps(out, indent=2, sort_keys=True))
                else:
                    print("blocked")
                    print(f"- {REQUIRED_CHECK_VISIBILITY_SKEW_BLOCKER}")
                    if skew_auto_resolution is not None:
                        print(
                            f"- skew-auto-resolve: {skew_auto_resolution.get('reason')} "
                            f"(reruns={len(skew_auto_resolution.get('reruns') or [])})"
                        )
                    print(visibility_skew["next_prompt"])
                return 2
            applied_commands = _apply_merge(
                pr=args.pr,
                head=args.head,
                repo=args.repo,
                cwd=args.cwd,
                reconcile_branch_protection="branch_protection"
                in set(gate.get("authorized_actions") or []),
            )
        out = {"gate": gate, "applied_commands": applied_commands}
    except Tier4ApplyError as exc:
        if args.json:
            print(
                json.dumps(
                    {"ok": False, "error": str(exc), **exc.to_payload()},
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print("ok" if gate["ok"] else "blocked")
        for blocker in gate["blockers"]:
            print(f"- {blocker}")
        diag = gate.get("merge_packet") or {}
        if not gate["ok"] and (diag.get("tier_name") or diag.get("status") or diag.get("reasons")):
            print(
                f"  merge-packet: tier={diag.get('tier')} ({diag.get('tier_name')}) "
                f"status={diag.get('status')} verdict={diag.get('verdict')}"
            )
            if diag.get("checks_summary"):
                print(f"  checks: {diag['checks_summary']}")
            counted = diag.get("counted_model_families") or []
            print(f"  counted_model_families: {len(counted)} {counted}")
            if diag.get("requires_human_risk_settlement"):
                print("  requires_human_risk_settlement: true")
            for reason in diag.get("reasons") or []:
                print(f"  reason: {reason}")
    return 0 if gate["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
