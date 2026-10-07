"""GitHub + ``evidence-lint`` I/O for merge-quorum reconciliation CLIs.

Thin subprocess wrappers shared by ``scripts/reconcile_merge_quorum.py`` (A1)
and ``scripts/settle_status.py`` (A2). Kept separate from the pure decision
logic in :mod:`aragora.swarm.merge_quorum_reconcile` so the decision logic stays
network-free and unit-testable. Counting is always delegated to the canonical
``review-queue evidence-lint`` subcommand so these tools match the gate's parser.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Any
from urllib.parse import quote

from aragora.swarm import github_app_auth
from aragora.swarm.merge_quorum_reconcile import (
    EvidenceComment,
    PacketClassification,
    QuorumRun,
    parse_ci_packet_classification,
)

QUORUM_CHECK_NAME = "aragora-merge-quorum"
QUORUM_WORKFLOW_FILE = "aragora-merge-quorum.yml"
HUMAN_SETTLEMENT_CONTEXT = "aragora/human-settlement"
_SHADOW_MARKERS = ("shadow", "advisory")
_FAILED_CONCLUSIONS = {
    "ACTION_REQUIRED",
    "CANCELLED",
    "ERROR",
    "FAILURE",
    "STALE",
    "STARTUP_FAILURE",
    "TIMED_OUT",
}
_SUCCESS_CONCLUSIONS = {"NEUTRAL", "SKIPPED", "SUCCESS"}
_REST_PAGE_SIZE = 100
_REST_MAX_PAGES = 100
_MERGE_PACKET_TIMEOUT = 120
_EVIDENCE_LINT_TIMEOUT = 90
_GH_TIMEOUT = 60
_GITHUB_ACTIONS_AUTHOR = "github-actions[bot]"
_MIN_EVIDENCE_BODY = 40


def _could_count(author: str, body: str) -> bool:
    """Cheap pre-check mirroring evidence-lint's hard rejections.

    A countable comment must have a non-github-actions author and enough text to
    carry a 7-char head citation plus a reviewer heading. Used only to skip
    obviously-uncountable comments before spawning the lint subprocess; the lint
    CLI remains the source of truth for everything that passes this filter.
    """
    if author == _GITHUB_ACTIONS_AUTHOR:
        return False
    return len(body.strip()) >= _MIN_EVIDENCE_BODY


def _looks_like_shadow(name: str) -> bool:
    """Whether a check name is a non-required shadow/advisory check.

    Shadow checks are named with a trailing marker word (e.g. ``... Shadow``),
    so this matches only the *last* token. A required check that merely contains
    a marker earlier in its name (e.g. ``aragora-shadow-deploy-required``, whose
    last token is ``required``) is therefore not misclassified as a shadow. This
    heuristic is only consulted when GitHub does not report ``isRequired``.
    """
    tokens = [t for t in re.split(r"[^a-z0-9]+", name.lower()) if t]
    return bool(tokens) and tokens[-1] in _SHADOW_MARKERS


def aragora_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("ARAGORA_USE_SECRETS_MANAGER", "false")
    return env


def _read_env() -> dict[str, str]:
    """Environment for *read-only* ``gh`` calls.

    Prefer the GitHub App installation token so reads draw on the App's separate
    API budget instead of starving the operator's shared per-user PAT quota (the
    chronic GraphQL-exhaustion failure mode). Degrades transparently to the
    ambient/operator auth when no App config is present. Read-only by design --
    the App installation 403s on classic branch-protection writes, so write call
    sites deliberately keep ``run()``'s default (PAT) env instead of this helper.
    """
    return github_app_auth.github_cli_env(aragora_env())


def run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: int | None = _GH_TIMEOUT,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    # Default to a bounded timeout so no bare call can hang the reconciler;
    # callers that need longer (model-review CLIs) pass an explicit timeout.
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=timeout,
        input=input_text,
    )


def run_json(
    args: list[str], *, env: dict[str, str] | None = None, timeout: int = _GH_TIMEOUT
) -> Any:
    try:
        proc = run(args, env=env, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"command timed out after {timeout}s: {' '.join(args)}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr}")
    return json.loads(proc.stdout or "null")


def list_open_prs(repo: str, *, limit: int, author: str | None) -> list[int]:
    rows = (
        run_json(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                repo,
                "--state",
                "open",
                "--limit",
                str(limit),
                "--json",
                "number,isDraft,author",
            ],
            env=_read_env(),
        )
        or []
    )
    numbers: list[int] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("isDraft"):
            continue
        if author and str((row.get("author") or {}).get("login", "")) != author:
            continue
        num = row.get("number")
        if isinstance(num, int):
            numbers.append(num)
    return numbers


def _check_state(check: dict[str, Any]) -> tuple[str, str, bool | None]:
    """Normalize a GraphQL status/check row for settlement-stability checks."""
    name = str(check.get("name") or check.get("context") or "").strip()
    conclusion = str(check.get("conclusion") or check.get("state") or "").upper()
    is_required = check.get("isRequired")
    return name, conclusion, is_required if isinstance(is_required, bool) else None


def _check_attempt_timestamp(check: dict[str, Any]) -> datetime | None:
    """Return the best attempt-ordering timestamp, or ``None`` if unprovable."""
    for key in (
        "startedAt",
        "started_at",
        "completedAt",
        "completed_at",
        "updatedAt",
        "updated_at",
    ):
        raw = check.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            parsed = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else None
    return None


def _latest_check_attempts(checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select the uniquely newest row per check name; ambiguity becomes pending."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    selected: list[dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        name = str(check.get("name") or check.get("context") or "").strip()
        if not name:
            selected.append(check)
            continue
        grouped.setdefault(name, []).append(check)
    for name, attempts in grouped.items():
        if len(attempts) == 1:
            selected.append(attempts[0])
            continue
        timestamps = [_check_attempt_timestamp(attempt) for attempt in attempts]
        if any(timestamp is None for timestamp in timestamps):
            newest: list[dict[str, Any]] = []
        else:
            latest = max(timestamp for timestamp in timestamps if timestamp is not None)
            newest = [
                attempt for attempt, timestamp in zip(attempts, timestamps) if timestamp == latest
            ]
        if len(newest) == 1:
            selected.append(newest[0])
            continue
        disclosed = [attempt.get("isRequired") for attempt in attempts]
        is_required = (
            True if True in disclosed else False if all(v is False for v in disclosed) else None
        )
        selected.append({"name": name, "conclusion": "", "isRequired": is_required})
    return selected


def _summarize_checks(
    checks: list[dict[str, Any]],
    *,
    required_names: set[str] | None = None,
) -> tuple[str, bool, bool]:
    """Return quorum conclusion plus non-quorum required failure/pending flags.

    ``required_names=None`` means GitHub could not disclose the required-check
    set. In that case every non-shadow failure or pending row is treated as
    required. This can delay evidence publication, but can never promote an
    unstable head during a degraded API incident.
    """
    real_failure = False
    real_pending = False
    quorum_conclusion = ""
    seen_names: set[str] = set()
    for check in _latest_check_attempts(checks):
        name, conclusion, disclosed_required = _check_state(check)
        if name:
            seen_names.add(name)
        if name == QUORUM_CHECK_NAME:
            quorum_conclusion = conclusion
            continue
        if disclosed_required is not None:
            required = disclosed_required
        elif required_names is not None:
            required = name in required_names
        else:
            required = not _looks_like_shadow(name)
        if not required:
            continue
        if conclusion in _FAILED_CONCLUSIONS:
            real_failure = True
        elif conclusion not in _SUCCESS_CONCLUSIONS:
            real_pending = True
    if required_names is not None:
        missing_required = required_names - seen_names - {QUORUM_CHECK_NAME}
        if missing_required:
            real_pending = True
    return quorum_conclusion, real_failure, real_pending


def _mergeable_from_rest(data: dict[str, Any]) -> str:
    mergeable = data.get("mergeable")
    if mergeable is True:
        return "MERGEABLE"
    if mergeable is False and str(data.get("mergeable_state") or "").lower() == "dirty":
        return "CONFLICTING"
    return "UNKNOWN"


def _merge_state_from_rest(data: dict[str, Any]) -> str:
    state = str(data.get("mergeable_state") or "").strip().lower()
    mapping = {
        "behind": "BEHIND",
        "blocked": "BLOCKED",
        "clean": "CLEAN",
        "dirty": "DIRTY",
        "draft": "DRAFT",
        "has_hooks": "HAS_HOOKS",
        "unstable": "UNSTABLE",
        "unknown": "UNKNOWN",
    }
    if state in mapping:
        return mapping[state]
    if data.get("mergeable") is True:
        return "CLEAN"
    if data.get("mergeable") is False:
        return "CONFLICTING"
    return "UNKNOWN"


def _with_page(endpoint: str, page: int) -> str:
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}page={page}"


def _rest_list(endpoint: str, *, env: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, _REST_MAX_PAGES + 1):
        payload = run_json(["gh", "api", "--method", "GET", _with_page(endpoint, page)], env=env)
        if not isinstance(payload, list):
            raise RuntimeError(f"REST endpoint returned a non-list payload: {endpoint}")
        rows.extend(row for row in payload if isinstance(row, dict))
        if len(payload) < _REST_PAGE_SIZE:
            break
    return rows


def _rest_check_runs(endpoint: str, *, env: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in range(1, _REST_MAX_PAGES + 1):
        payload = run_json(["gh", "api", "--method", "GET", _with_page(endpoint, page)], env=env)
        page_rows = payload.get("check_runs") if isinstance(payload, dict) else None
        if not isinstance(page_rows, list):
            raise RuntimeError(f"REST endpoint returned no check-runs list: {endpoint}")
        rows.extend(row for row in page_rows if isinstance(row, dict))
        if len(page_rows) < _REST_PAGE_SIZE:
            break
    return rows


def _applied_branch_rules(repo: str, base_ref: str, *, env: dict[str, str]) -> list[dict[str, Any]]:
    """Fetch every applied branch rule, rejecting incomplete pagination or schema."""
    endpoint = f"repos/{repo}/rules/branches/{quote(base_ref, safe='')}?per_page={_REST_PAGE_SIZE}"
    rows: list[dict[str, Any]] = []
    for page in range(1, _REST_MAX_PAGES + 1):
        payload = run_json(["gh", "api", "--method", "GET", _with_page(endpoint, page)], env=env)
        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
            raise RuntimeError("applied branch rules returned an invalid payload")
        rows.extend(payload)
        if len(payload) < _REST_PAGE_SIZE:
            return rows
    raise RuntimeError("applied branch rules exceeded the pagination limit")


def _required_context(value: Any, source: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise RuntimeError(f"{source} contained an invalid context")
    return value


def _classic_required_check_names(payload: Any) -> set[str]:
    """Normalize classic branch-protection requirements without coercing bad data."""
    if not isinstance(payload, dict):
        raise RuntimeError("classic required checks returned a non-object payload")
    contexts = payload.get("contexts")
    checks = payload.get("checks")
    if not isinstance(contexts, list) or not isinstance(checks, list):
        raise RuntimeError("classic required checks omitted contexts or checks")
    names: set[str] = set()
    for context in contexts:
        names.add(_required_context(context, "classic required checks"))
    for check in checks:
        if not isinstance(check, dict):
            raise RuntimeError("classic required checks contained a non-object check")
        names.add(_required_context(check.get("context"), "classic required checks"))
    return names


def _ruleset_required_check_names(rules: list[dict[str, Any]]) -> set[str]:
    """Normalize required contexts from a complete applied-rules response."""
    names: set[str] = set()
    for rule in rules:
        rule_type = rule.get("type")
        if not isinstance(rule_type, str) or not rule_type or rule_type != rule_type.strip():
            raise RuntimeError("applied branch rules contained an invalid rule type")
        if rule_type != "required_status_checks":
            continue
        parameters = rule.get("parameters")
        if not isinstance(parameters, dict):
            raise RuntimeError("required_status_checks rule omitted parameters")
        requirements = parameters.get("required_status_checks")
        if not isinstance(requirements, list):
            raise RuntimeError("required_status_checks rule omitted its requirements")
        for requirement in requirements:
            if not isinstance(requirement, dict):
                raise RuntimeError("required_status_checks contained a non-object requirement")
            context = requirement.get("context")
            name = requirement.get("name")
            if context is not None and name is not None and context != name:
                raise RuntimeError("required_status_checks contained conflicting context names")
            names.add(
                _required_context(
                    context if context is not None else name,
                    "required_status_checks",
                )
            )
    return names


def _required_check_names(repo: str, base_ref: str, *, env: dict[str, str]) -> set[str] | None:
    if not base_ref:
        return None
    ambient_env = aragora_env()
    candidates = [env]
    if env.get("GH_TOKEN") != ambient_env.get("GH_TOKEN"):
        candidates.append(ambient_env)
    for candidate_env in candidates:
        try:
            classic_payload = run_json(
                [
                    "gh",
                    "api",
                    "--method",
                    "GET",
                    f"repos/{repo}/branches/{quote(base_ref, safe='')}/protection/required_status_checks",
                ],
                env=candidate_env,
            )
            rules = _applied_branch_rules(repo, base_ref, env=candidate_env)
            names = _classic_required_check_names(classic_payload)
            names.update(_ruleset_required_check_names(rules))
        except RuntimeError:
            continue
        return names
    return None


def _fetch_required_pr_checks(repo: str, pr: int, *, env: dict[str, str]) -> list[dict[str, Any]]:
    """Fetch GitHub's canonical required-check surface for a pull request."""
    args = [
        "gh",
        "pr",
        "checks",
        str(pr),
        "--repo",
        repo,
        "--required",
        "--json",
        "name,state,bucket",
    ]
    try:
        proc = run(args, env=env)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"required-check query timed out for {repo}#{pr}") from exc
    try:
        payload = json.loads(proc.stdout or "")
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"required-check query failed ({proc.returncode}) for {repo}#{pr}: "
            f"{(proc.stderr or '').strip()[:200]}"
        ) from exc
    if not isinstance(payload, list):
        raise RuntimeError(f"required-check query returned a non-list payload for {repo}#{pr}")
    return [
        {
            "name": row.get("name"),
            "conclusion": row.get("state") or row.get("bucket"),
            "isRequired": True,
        }
        for row in payload
        if isinstance(row, dict)
    ]


def _fetch_pr_context_rest(repo: str, pr: int, *, env: dict[str, str]) -> dict[str, Any]:
    data = run_json(["gh", "api", "--method", "GET", f"repos/{repo}/pulls/{pr}"], env=env)
    if not isinstance(data, dict):
        raise RuntimeError(f"REST pull request payload was not an object for {repo}#{pr}")
    raw_head = data.get("head")
    raw_base = data.get("base")
    head: dict[str, Any] = raw_head if isinstance(raw_head, dict) else {}
    base: dict[str, Any] = raw_base if isinstance(raw_base, dict) else {}
    head_sha = str(head.get("sha") or "").strip()
    if not head_sha:
        raise RuntimeError(f"REST pull request payload omitted head SHA for {repo}#{pr}")
    commit = run_json(["gh", "api", "--method", "GET", f"repos/{repo}/commits/{head_sha}"], env=env)
    commit_payload = commit.get("commit") if isinstance(commit, dict) else {}
    committer = commit_payload.get("committer") if isinstance(commit_payload, dict) else {}
    head_committed_at = str((committer.get("date") if isinstance(committer, dict) else "") or "")
    check_runs = _rest_check_runs(
        f"repos/{repo}/commits/{head_sha}/check-runs?per_page={_REST_PAGE_SIZE}", env=env
    )
    statuses = _rest_list(
        f"repos/{repo}/commits/{head_sha}/statuses?per_page={_REST_PAGE_SIZE}", env=env
    )
    checks: list[dict[str, Any]] = []
    for check in check_runs:
        if not isinstance(check, dict):
            continue
        name = str(check.get("name") or "").strip()
        if name:
            checks.append(
                {
                    "name": name,
                    "conclusion": check.get("conclusion") or check.get("status"),
                    "started_at": check.get("started_at"),
                    "completed_at": check.get("completed_at"),
                    "updated_at": check.get("updated_at"),
                },
            )
    for status in statuses:
        context = str(status.get("context") or "").strip()
        if context:
            checks.append(
                {
                    "context": context,
                    "state": status.get("state"),
                    "updated_at": status.get("updated_at"),
                }
            )
    required_names = _required_check_names(repo, str(base.get("ref") or ""), env=env)
    quorum_conclusion, real_failure, real_pending = _summarize_checks(
        checks, required_names=required_names
    )
    pr_state = "MERGED" if data.get("merged_at") else str(data.get("state") or "").upper()
    return {
        "head_sha": head_sha,
        "head_committed_at": head_committed_at,
        "quorum_conclusion": quorum_conclusion,
        "has_real_required_failure": real_failure,
        "has_real_required_pending": real_pending,
        "is_draft": bool(data.get("draft")),
        "pr_state": pr_state,
        "mergeable": _mergeable_from_rest(data),
        "merge_state_status": _merge_state_from_rest(data),
        "context_source": "rest",
        "required_checks_disclosed": required_names is not None,
    }


def _fetch_pr_context_graphql(repo: str, pr: int, *, env: dict[str, str]) -> dict[str, Any]:
    data = run_json(
        [
            "gh",
            "pr",
            "view",
            str(pr),
            "--repo",
            repo,
            "--json",
            "headRefOid,commits,statusCheckRollup,isDraft,state,mergeable,mergeStateStatus",
        ],
        env=env,
    )
    if not isinstance(data, dict):
        raise RuntimeError(f"GraphQL pull request payload was not an object for {repo}#{pr}")
    head_sha = str(data.get("headRefOid") or "").strip()
    commits = data.get("commits") or []
    head_committed_at = ""
    for entry in commits:
        if isinstance(entry, dict) and str(entry.get("oid") or "") == head_sha:
            head_committed_at = str(entry.get("committedDate") or "")
            break
    if not head_committed_at and head_sha:
        # The head may be beyond the returned commit slice; fetch its date
        # directly rather than guessing from the last listed commit.
        try:
            commit = run_json(["gh", "api", f"repos/{repo}/commits/{head_sha}"], env=env) or {}
        except RuntimeError:
            commit = {}
        committer = (commit.get("commit") or {}).get("committer") or {}
        head_committed_at = str(committer.get("date") or "")

    required_checks = _fetch_required_pr_checks(repo, pr, env=env)
    _, real_failure, real_pending = _summarize_checks(required_checks)
    quorum_conclusion, _, _ = _summarize_checks(data.get("statusCheckRollup") or [])
    if not quorum_conclusion:
        quorum_conclusion, _, _ = _summarize_checks(required_checks)
    return {
        "head_sha": head_sha,
        "head_committed_at": head_committed_at,
        "quorum_conclusion": quorum_conclusion,
        "has_real_required_failure": real_failure,
        "has_real_required_pending": real_pending,
        "is_draft": bool(data.get("isDraft")),
        "pr_state": str(data.get("state") or "").upper(),
        "mergeable": str(data.get("mergeable") or "").upper(),
        "merge_state_status": str(data.get("mergeStateStatus") or "").upper(),
        "context_source": "graphql",
        "required_checks_disclosed": True,
    }


def fetch_pr_context(repo: str, pr: int) -> dict[str, Any]:
    """Fetch exact-head settlement context, preferring GraphQL then REST.

    REST is a resilience path for GitHub GraphQL incidents, not a relaxation:
    if branch protection cannot disclose required contexts, every non-shadow
    failure or pending check is conservatively treated as required.
    """
    env = _read_env()
    try:
        return _fetch_pr_context_graphql(repo, pr, env=env)
    except RuntimeError as graphql_error:
        rest_errors: list[str] = []
        rest_envs = [env]
        ambient_env = aragora_env()
        if env.get("GH_TOKEN") != ambient_env.get("GH_TOKEN"):
            rest_envs.append(ambient_env)
        context: dict[str, Any] | None = None
        for rest_env in rest_envs:
            try:
                context = _fetch_pr_context_rest(repo, pr, env=rest_env)
                break
            except RuntimeError as rest_error:
                rest_errors.append(str(rest_error))
        if context is None:
            joined_rest_errors = "; ".join(rest_errors)
            raise RuntimeError(
                f"could not fetch PR context via GraphQL ({graphql_error}) "
                f"or REST ({joined_rest_errors})"
            ) from graphql_error
        context["graphql_error"] = str(graphql_error)[:500]
        return context


def fetch_latest_quorum_run(repo: str, head_sha: str) -> QuorumRun | None:
    if not head_sha:
        return None
    data = run_json(
        [
            "gh",
            "api",
            f"repos/{repo}/actions/workflows/{QUORUM_WORKFLOW_FILE}/runs?head_sha={head_sha}&per_page=1",
        ],
        env=_read_env(),
    )
    runs = (data or {}).get("workflow_runs") or []
    if not runs:
        return None
    run_obj = runs[0]
    raw_id = run_obj.get("id")
    if raw_id is None:
        return None
    try:
        run_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    return QuorumRun(
        run_id=run_id,
        created_at=str(run_obj.get("created_at") or ""),
        conclusion=str(run_obj.get("conclusion") or "").upper(),
        head_sha=str(run_obj.get("head_sha") or ""),
    )


def fetch_human_settlement_present(repo: str, head_sha: str) -> bool:
    if not head_sha:
        return False
    try:
        statuses = (
            run_json(["gh", "api", f"repos/{repo}/commits/{head_sha}/statuses"], env=_read_env())
            or []
        )
    except RuntimeError:
        return False
    for status in statuses:
        if not isinstance(status, dict):
            continue
        if str(status.get("context") or "") == HUMAN_SETTLEMENT_CONTEXT:
            return str(status.get("state") or "").lower() == "success"
    return False


def fetch_pr_tier(repo: str, pr: int) -> int | None:
    """Best-effort tier from ``review-queue merge-packet``; ``None`` if unknown."""
    packet = fetch_merge_packet_classification(repo, pr)
    return packet.tier if packet is not None else None


def fetch_merge_packet_classification(repo: str, pr: int) -> PacketClassification | None:
    """Best-effort current local merge-packet classification for one PR."""
    try:
        proc = run(
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
            env=_read_env(),
            timeout=_MERGE_PACKET_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    # merge-packet --json returns a top-level object with the per-PR rows under
    # "entries"; tier lives on each entry, not the envelope. Accept a bare list
    # or single entry too for forward-compatibility.
    if isinstance(payload, list):
        entries = payload
    elif isinstance(payload, dict):
        nested = payload.get("entries")
        entries = nested if isinstance(nested, list) else [payload]
    else:
        entries = []

    def _coerce(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _packet(entry: dict[str, Any]) -> PacketClassification | None:
        tier = _coerce(entry.get("tier"))
        pr_value = _coerce(entry.get("pr_number"))
        if pr_value is None:
            pr_value = pr
        if pr_value != pr or entry.get("tier") is None:
            return None
        return PacketClassification(
            source="local",
            pr_number=pr_value,
            head_sha=str(entry.get("head_sha") or ""),
            tier=tier,
            status=str(entry.get("status") or ""),
            verdict=str(entry.get("verdict") or ""),
            requires_human_risk_settlement=bool(entry.get("requires_human_risk_settlement")),
        )

    # Prefer the row whose pr_number matches the requested PR. The normal
    # single-PR --json shape always discloses pr_number, so a multi-PR envelope
    # can never resolve the wrong PR's tier (which would mis-gate posting).
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        packet = _packet(entry)
        if packet is not None and _coerce(entry.get("pr_number")) == pr:
            return packet
    # Fall back to the first disclosed tier only when NO row carries a pr_number
    # (forward-compat shapes such as a bare list or single entry).
    if not any(isinstance(e, dict) and e.get("pr_number") is not None for e in entries):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            packet = _packet(entry)
            if packet is not None:
                return packet
    return None


def fetch_quorum_run_packet_classification(
    repo: str, *, run_id: int, pr: int, head_sha: str
) -> PacketClassification | None:
    """Best-effort CI packet classification parsed from a merge-quorum run log."""
    try:
        proc = run(
            ["gh", "run", "view", str(run_id), "--repo", repo, "--log"],
            timeout=_GH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return parse_ci_packet_classification(proc.stdout, pr_number=pr, head_sha=head_sha)


# Hard identity problems that stop one reviewer-signal item from counting.
# Mirrors ``review_queue.IDENTITY_COUNT_BLOCKERS`` — the swarm layer cannot
# import the CLI module (upward layer edge, and a circular import via
# quorum_evidence), so the five blocker strings are duplicated here and pinned
# against the CLI set by
# tests/swarm/test_merge_quorum_reconcile.py::TestSignalFamiliesFromLint.
_SIGNAL_IDENTITY_BLOCKERS: frozenset[str] = frozenset(
    (
        "missing_model_family_disclosure",
        "unknown_model_family",
        "heading_model_family_conflict",
        "unknown_surface_reviewer",
        "proxy_transport_grounding_undisclosed",
    )
)


def _signal_families_from_lint(lint: dict[str, Any]) -> tuple[str, ...]:
    """Counted families backed by GENUINE model-review signal items.

    Derives ``EvidenceComment.reviewer_signals`` provenance from the lint's
    ``reviewer_signals`` list ONLY — never ``dogfood_evidence`` — mirroring the
    live gate's signal-only western-frontier derivation (review_queue computes
    ``has_western_frontier_signal`` from reviewer signals with an EMPTY dogfood
    list). Families are intersected with ``counted_reviewer_ids`` so the result
    is always a subset of the counted families (advisory-only exclusions carry
    over), and items with hard identity blockers never contribute, keeping this
    at-most-as-permissive as the gate.
    """
    counted = {
        str(rid).strip().lower()
        for rid in (lint.get("counted_reviewer_ids") or [])
        if str(rid).strip()
    }
    families: set[str] = set()
    for item in lint.get("reviewer_signals") or []:
        if not isinstance(item, dict):
            continue
        problems = {str(problem) for problem in (item.get("identity_problems") or [])}
        if problems & _SIGNAL_IDENTITY_BLOCKERS:
            continue
        family = str(item.get("model_family") or "").strip().lower()
        if family and family in counted:
            families.add(family)
    return tuple(sorted(families))


def fetch_evidence_comments(
    repo: str, pr: int, head_sha: str, head_committed_at: str
) -> list[EvidenceComment]:
    comments = run_json(["gh", "api", f"repos/{repo}/issues/{pr}/comments", "--paginate"]) or []
    env = aragora_env()
    results: list[EvidenceComment] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        body = str(comment.get("body") or "")
        author = str((comment.get("user") or {}).get("login") or "")
        if not _could_count(author, body):
            # Cheap pre-filter: avoid spawning evidence-lint for comments that
            # cannot possibly count (evidence-lint rejects github-actions
            # authors and anything too short for a head citation + heading).
            continue
        lint = lint_comment(pr, head_sha, head_committed_at, author, body, env)
        counted = lint.get("counted_reviewer_ids") or []
        results.append(
            EvidenceComment(
                created_at=str(comment.get("created_at") or ""),
                would_count=bool(lint.get("would_count")),
                reviewer_id=str(counted[0]) if counted else "",
                is_dogfood=bool(lint.get("dogfood_evidence")),
                reviewer_signals=_signal_families_from_lint(lint),
            )
        )
    return results


def _evidence_lint_args(
    pr: int, head_sha: str, head_committed_at: str, author: str, body_file: str
) -> list[str]:
    """Build the ``review-queue evidence-lint`` argv.

    Note: ``evidence-lint`` infers the repo from the current context and does
    *not* accept ``--repo``; passing it makes argparse reject the call. With
    ``--head-committed-at`` supplied the lint is fully offline.
    """
    args = [
        sys.executable,
        "-m",
        "aragora.cli.main",
        "review-queue",
        "evidence-lint",
        "--pr",
        str(pr),
        "--head-sha",
        head_sha,
        "--author",
        author,
        "--body-file",
        body_file,
        "--json",
    ]
    if head_committed_at:
        args.extend(["--head-committed-at", head_committed_at])
    return args


def _lint_infra_failure(reason: str) -> dict[str, Any]:
    """Explicit fail-closed lint result for an evidence-lint INFRA failure.

    A broken lint subprocess must stay non-counting (fail-closed), but it must
    be distinguishable from a substantive rejection: an empty ``{}`` renders as
    ``DOES NOT count ()`` and silently zeroes evidence that may have counted
    (observed live 2026-07-09: claude items recorded ``would_count=False,
    problems=[]`` while the same body relinted offline with three real
    problems). The ``evidence_lint_infra_failure:`` prefix tells operators and
    reconcile tooling to re-lint rather than treat the family as rejected.
    """
    return {
        "would_count": False,
        "counted_reviewer_ids": [],
        "problems": [f"evidence_lint_infra_failure: {reason}"],
    }


# Retry the evidence-lint subprocess ONLY on infra failure (timeout / nonzero
# exit / empty stdout / undecodable JSON), mirroring the reviewer-side
# ``_run_reviewer_with_infra_retry`` semantics: a lint that returned a parsed
# result — counting or not — is never retried, so a substantive rejection can
# never be "retried away".
_EVIDENCE_LINT_INFRA_RETRIES = 1


def _enforce_reason_invariant(lint: dict[str, Any]) -> dict[str, Any]:
    """Enforce ``would_count == False => problems is non-empty``.

    Every non-counting lint result must carry a diagnosable reason; a parsed
    result that rejects with an empty problems list would still render as the
    unanswerable ``DOES NOT count ()``. Counting/eligibility are unchanged —
    this only guarantees the reason channel is never silently empty."""
    if isinstance(lint, dict) and not lint.get("would_count") and not lint.get("problems"):
        lint = dict(lint)
        lint["problems"] = ["evidence_lint_rejection_without_reason"]
    return lint


def lint_comment(
    pr: int,
    head_sha: str,
    head_committed_at: str,
    author: str,
    body: str,
    env: dict[str, str],
) -> dict[str, Any]:
    body_file = ""
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            # Capture the path before writing so a write failure still cleans up.
            body_file = fh.name
            fh.write(body)
        args = _evidence_lint_args(pr, head_sha, head_committed_at, author, body_file)
        failure: dict[str, Any] = _lint_infra_failure("lint subprocess never ran")
        for _ in range(1 + _EVIDENCE_LINT_INFRA_RETRIES):
            try:
                proc = run(args, env=env, timeout=_EVIDENCE_LINT_TIMEOUT)
            except subprocess.TimeoutExpired:
                failure = _lint_infra_failure(
                    f"evidence-lint timed out after {_EVIDENCE_LINT_TIMEOUT}s"
                )
                continue
            # The evidence-lint CLI exits 1 BY DESIGN on every substantive
            # rejection while still printing the parsed JSON result
            # (review_queue.py: ``return 0 if result["would_count"] else 1``).
            # The exit code is therefore a verdict signal, not a health
            # signal: parse stdout first, and treat only empty/undecodable/
            # non-dict output as infra failure. Gating on returncode here was
            # the original root cause of every rejection collapsing to ``{}``.
            stdout = (proc.stdout or "").strip()
            if not stdout:
                stderr = (proc.stderr or "").strip()[:120]
                failure = _lint_infra_failure(
                    f"evidence-lint exit {proc.returncode} with empty stdout"
                    + (f": {stderr}" if stderr else "")
                )
                continue
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError:
                failure = _lint_infra_failure("evidence-lint emitted undecodable JSON")
                continue
            if not isinstance(parsed, dict):
                failure = _lint_infra_failure(
                    f"evidence-lint emitted non-dict JSON ({type(parsed).__name__})"
                )
                continue
            return _enforce_reason_invariant(parsed)
        return failure
    finally:
        if body_file:
            try:
                os.unlink(body_file)
            except OSError:
                pass
