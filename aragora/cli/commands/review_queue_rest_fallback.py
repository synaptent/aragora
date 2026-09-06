"""REST fallback helpers for review-queue merge packets."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlparse

from aragora.cli.commands.review_queue_transport import _GhError, _gh_json

GhJson = Callable[[list[str]], Any]
_REST_PAGE_SIZE = 100
_REST_MAX_PAGES = 100


def _paged_endpoint(endpoint: str, page: int) -> str:
    """Append a REST page parameter while preserving existing query args."""
    separator = "&" if "?" in endpoint else "?"
    return f"{endpoint}{separator}page={page}"


def _repo_slug_from_pr_payload(pr: dict[str, Any], repo_override: str | None) -> str:
    """Resolve owner/repo from an explicit override or the PR URL."""
    override = str(repo_override or "").strip()
    if override:
        parsed = urlparse(override)
        if parsed.netloc:
            parts = [part for part in parsed.path.split("/") if part]
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
        if "/" in override and not override.startswith("-"):
            return override.removeprefix("repos/").strip("/")

    url = str(pr.get("url") or "").strip()
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return ""


def _rest_list(
    endpoint: str,
    *,
    required: bool = False,
    gh_json: GhJson = _gh_json,
) -> list[dict[str, Any]]:
    """Fetch a paginated REST list through ``gh api``.

    The fallback is deliberately conservative: if a surface is unavailable, the
    caller gets an empty list and the existing packet logic fails closed on
    missing checks/evidence instead of inventing readiness.
    """
    items: list[dict[str, Any]] = []
    for page in range(1, _REST_MAX_PAGES + 1):
        current_endpoint = endpoint if page == 1 else _paged_endpoint(endpoint, page)
        try:
            payload = gh_json(["api", current_endpoint])
        except _GhError:
            if required:
                raise
            return items
        if not isinstance(payload, list):
            if required:
                raise _GhError(f"REST endpoint {current_endpoint} returned a non-list payload")
            return items
        items.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < _REST_PAGE_SIZE:
            break
    return items


def _rest_pr_state(rest_pr: dict[str, Any]) -> str:
    if rest_pr.get("merged_at"):
        return "MERGED"
    return str(rest_pr.get("state") or "").strip().upper()


def _rest_pr_mergeable(rest_pr: dict[str, Any]) -> str:
    mergeable = rest_pr.get("mergeable")
    if mergeable is True:
        return "MERGEABLE"
    if mergeable is False:
        state = str(rest_pr.get("mergeable_state") or "").strip().lower()
        return "CONFLICTING" if state == "dirty" else "UNKNOWN"
    return "UNKNOWN"


def _rest_pr_merge_state_status(rest_pr: dict[str, Any]) -> str:
    state = str(rest_pr.get("mergeable_state") or "").strip().lower()
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
    mergeable = rest_pr.get("mergeable")
    if mergeable is True:
        return "CLEAN"
    if mergeable is False:
        return "CONFLICTING"
    return "UNKNOWN"


def _normalize_rest_issue_comment(comment: dict[str, Any]) -> dict[str, Any]:
    user_payload = comment.get("user")
    user: dict[str, Any] = user_payload if isinstance(user_payload, dict) else {}
    return {
        "author": {"login": str(user.get("login") or "").strip()},
        "authorAssociation": str(comment.get("author_association") or "").strip().upper(),
        "body": str(comment.get("body") or ""),
        "createdAt": str(comment.get("created_at") or ""),
        "url": str(comment.get("html_url") or ""),
    }


def _normalize_rest_review(review: dict[str, Any]) -> dict[str, Any]:
    user_payload = review.get("user")
    user: dict[str, Any] = user_payload if isinstance(user_payload, dict) else {}
    commit_id = str(review.get("commit_id") or "").strip()
    return {
        "author": {"login": str(user.get("login") or "").strip()},
        "authorAssociation": str(review.get("author_association") or "").strip().upper(),
        "body": str(review.get("body") or ""),
        "state": str(review.get("state") or "").strip().upper(),
        "submittedAt": str(review.get("submitted_at") or ""),
        "url": str(review.get("html_url") or ""),
        "commit": {"oid": commit_id} if commit_id else {},
    }


def _normalize_rest_commit(commit: dict[str, Any]) -> dict[str, Any]:
    raw_commit_payload = commit.get("commit")
    commit_payload: dict[str, Any] = (
        raw_commit_payload if isinstance(raw_commit_payload, dict) else {}
    )
    raw_author = commit_payload.get("author")
    author: dict[str, Any] = raw_author if isinstance(raw_author, dict) else {}
    return {
        "oid": str(commit.get("sha") or "").strip(),
        "committedDate": str(author.get("date") or "").strip(),
    }


def _normalize_rest_status(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "context": str(status.get("context") or "").strip(),
        "state": str(status.get("state") or "").strip().upper(),
        "targetUrl": str(status.get("target_url") or "").strip(),
        "updatedAt": str(status.get("updated_at") or "").strip(),
        "createdAt": str(status.get("created_at") or "").strip(),
    }


def _fetch_direct_commit_statuses(
    repo_slug: str,
    head_sha: str,
    *,
    gh_json: GhJson = _gh_json,
) -> list[dict[str, Any]]:
    """Best-effort direct commit statuses for REST fallback diagnostics."""
    if not repo_slug or not head_sha:
        return []
    try:
        statuses = _rest_list(
            f"repos/{repo_slug}/commits/{head_sha}/statuses?per_page={_REST_PAGE_SIZE}",
            gh_json=gh_json,
        )
        if statuses:
            return [_normalize_rest_status(status) for status in statuses]
    except Exception:
        pass
    try:
        payload = gh_json(["api", f"repos/{repo_slug}/commits/{head_sha}/status"])
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    statuses = payload.get("statuses") or []
    return [_normalize_rest_status(status) for status in statuses if isinstance(status, dict)]


def _hydrate_pr_with_rest_fallback(
    *,
    number: int,
    repo_slug: str,
    source_error: str,
    gh_json: GhJson = _gh_json,
) -> dict[str, Any]:
    """Hydrate PR metadata via REST when GraphQL-backed ``gh pr view`` is blocked."""
    if not repo_slug:
        raise _GhError(
            "could not resolve repo slug for REST fallback after GraphQL PR fetch failed: "
            f"{source_error}"
        )
    rest_pr = gh_json(["api", f"repos/{repo_slug}/pulls/{number}"])
    if not isinstance(rest_pr, dict):
        raise _GhError(f"REST fallback PR #{number} not found after GraphQL failure")

    raw_head = rest_pr.get("head")
    raw_base = rest_pr.get("base")
    raw_user = rest_pr.get("user")
    head: dict[str, Any] = raw_head if isinstance(raw_head, dict) else {}
    base: dict[str, Any] = raw_base if isinstance(raw_base, dict) else {}
    user: dict[str, Any] = raw_user if isinstance(raw_user, dict) else {}
    head_sha = str(head.get("sha") or "").strip()
    files = _rest_list(
        f"repos/{repo_slug}/pulls/{number}/files?per_page=100",
        required=True,
        gh_json=gh_json,
    )
    comments = _rest_list(
        f"repos/{repo_slug}/issues/{number}/comments?per_page=100",
        required=True,
        gh_json=gh_json,
    )
    reviews = _rest_list(f"repos/{repo_slug}/pulls/{number}/reviews?per_page=100", gh_json=gh_json)
    commits = _rest_list(f"repos/{repo_slug}/pulls/{number}/commits?per_page=100", gh_json=gh_json)

    return {
        "number": int(rest_pr.get("number") or number),
        "title": str(rest_pr.get("title") or "").strip(),
        "url": str(rest_pr.get("html_url") or "").strip(),
        "headRefName": str(head.get("ref") or "").strip(),
        "headRefOid": head_sha,
        "baseRefName": str(base.get("ref") or "").strip(),
        "baseRefOid": str(base.get("sha") or "").strip(),
        "state": _rest_pr_state(rest_pr),
        "mergedAt": str(rest_pr.get("merged_at") or "").strip(),
        "mergeCommit": {"oid": str(rest_pr.get("merge_commit_sha") or "").strip()},
        "isDraft": bool(rest_pr.get("draft")),
        "mergeable": _rest_pr_mergeable(rest_pr),
        "mergeStateStatus": _rest_pr_merge_state_status(rest_pr),
        "reviewDecision": "",
        "labels": [
            {"name": str(label.get("name") or "").strip()}
            for label in rest_pr.get("labels") or []
            if isinstance(label, dict) and label.get("name")
        ],
        "author": {"login": str(user.get("login") or "").strip()},
        "additions": int(rest_pr.get("additions") or 0),
        "deletions": int(rest_pr.get("deletions") or 0),
        "changedFiles": int(rest_pr.get("changed_files") or 0),
        "files": [
            {"path": str(item.get("filename") or "").strip()}
            for item in files
            if str(item.get("filename") or "").strip()
        ],
        "body": str(rest_pr.get("body") or ""),
        # Keep the PR rollup unavailable so the existing direct required-check
        # fallback gates on branch-protection contexts instead of treating a
        # best-effort REST check list as the PR-facing rollup.
        "statusCheckRollup": [],
        "comments": [_normalize_rest_issue_comment(comment) for comment in comments],
        "reviews": [_normalize_rest_review(review) for review in reviews],
        "commits": [_normalize_rest_commit(commit) for commit in commits],
        "commitStatuses": _fetch_direct_commit_statuses(repo_slug, head_sha, gh_json=gh_json),
        "_rest_fallback": {
            "enabled": True,
            "repo": repo_slug,
            "source_error": source_error,
            "surfaces": [
                "pull",
                "files",
                "issue_comments",
                "reviews",
                "commits",
                "commit_statuses",
                "check_runs",
            ],
        },
    }


def _fetch_required_status_check_protection(
    repo_slug: str,
    base_ref: str,
    *,
    gh_json: GhJson = _gh_json,
) -> dict[str, Any]:
    """Best-effort branch-protection required status-check settings."""
    if not repo_slug or not base_ref:
        return {"available": False, "contexts": [], "strict": None}
    try:
        payload = gh_json(
            [
                "api",
                f"repos/{repo_slug}/branches/{quote(base_ref, safe='')}"
                "/protection/required_status_checks",
            ]
        )
    except Exception:
        return {"available": False, "contexts": [], "strict": None}
    if not isinstance(payload, dict):
        return {"available": False, "contexts": [], "strict": None}
    required_by_context: dict[str, dict[str, Any]] = {}
    for item in payload.get("contexts") or []:
        context = str(item).strip()
        if context:
            required_by_context.setdefault(context, {"context": context, "app_id": None})
    for item in payload.get("checks") or []:
        if not isinstance(item, dict):
            continue
        context = str(item.get("context") or "").strip()
        if context:
            app_id = item.get("app_id")
            required_by_context[context] = {
                "context": context,
                "app_id": app_id if app_id is not None else None,
            }
    required_checks = list(required_by_context.values())
    return {
        "available": True,
        "contexts": [item["context"] for item in required_checks],
        "checks": required_checks,
        "strict": bool(payload.get("strict")),
    }


def _fetch_direct_commit_check_runs(
    repo_slug: str,
    head_sha: str,
    *,
    gh_json: GhJson = _gh_json,
) -> list[dict[str, Any]]:
    """Best-effort direct commit check-runs for diagnostics only."""
    if not repo_slug or not head_sha:
        return []
    runs: list[dict[str, Any]] = []
    endpoint = f"repos/{repo_slug}/commits/{head_sha}/check-runs?per_page={_REST_PAGE_SIZE}"
    for page in range(1, _REST_MAX_PAGES + 1):
        current_endpoint = endpoint if page == 1 else _paged_endpoint(endpoint, page)
        try:
            payload = gh_json(["api", current_endpoint])
        except Exception:
            return runs
        if not isinstance(payload, dict):
            return runs
        page_runs = [run for run in payload.get("check_runs") or [] if isinstance(run, dict)]
        runs.extend(page_runs)
        total_count = payload.get("total_count")
        if isinstance(total_count, int) and len(runs) >= total_count:
            break
        if len(page_runs) < _REST_PAGE_SIZE:
            break
    return runs


def _direct_check_run_name(run: dict[str, Any]) -> str:
    return str(run.get("name") or run.get("context") or "").strip()


def _direct_check_run_is_success(run: dict[str, Any]) -> bool:
    return str(run.get("conclusion") or "").strip().upper() in {
        "SUCCESS",
        "SKIPPED",
        "NEUTRAL",
    }


def _direct_check_run_is_non_green(run: dict[str, Any]) -> bool:
    status = str(run.get("status") or "").strip().upper()
    conclusion = str(run.get("conclusion") or "").strip().upper()
    if conclusion in {"SUCCESS", "SKIPPED", "NEUTRAL"}:
        return False
    if conclusion:
        return True
    if status in {"", "COMPLETED"}:
        return True
    return status in {"QUEUED", "IN_PROGRESS", "PENDING", "EXPECTED"}


def _latest_direct_check_runs_by_name(
    runs: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    latest: dict[str, tuple[str, int, dict[str, Any]]] = {}
    for index, run in enumerate(runs):
        name = _direct_check_run_name(run)
        if not name:
            continue
        timestamp = str(
            run.get("completed_at")
            or run.get("started_at")
            or run.get("created_at")
            or run.get("completedAt")
            or run.get("startedAt")
            or run.get("createdAt")
            or ""
        )
        previous = latest.get(name)
        if (
            previous is None
            or timestamp > previous[0]
            or (timestamp == previous[0] and index < previous[1])
        ):
            latest[name] = (timestamp, index, run)
    return {name: item[2] for name, item in latest.items()}


def _direct_check_run_app_id(run: dict[str, Any]) -> Any:
    app = run.get("app")
    if isinstance(app, dict):
        return app.get("id")
    return None


def _direct_check_run_matches_required(run: dict[str, Any], required: dict[str, Any]) -> bool:
    if _direct_check_run_name(run) != required.get("context"):
        return False
    required_app_id = required.get("app_id")
    if required_app_id is None:
        return True
    return _direct_check_run_app_id(run) == required_app_id


def _latest_direct_check_run_for_required(
    runs: list[dict[str, Any]],
    required: dict[str, Any],
) -> dict[str, Any] | None:
    latest: tuple[str, int, dict[str, Any]] | None = None
    for index, run in enumerate(runs):
        if not _direct_check_run_matches_required(run, required):
            continue
        timestamp = str(
            run.get("completed_at")
            or run.get("started_at")
            or run.get("created_at")
            or run.get("completedAt")
            or run.get("startedAt")
            or run.get("createdAt")
            or ""
        )
        if (
            latest is None
            or timestamp > latest[0]
            or (timestamp == latest[0] and index < latest[1])
        ):
            latest = (timestamp, index, run)
    return latest[2] if latest else None


def _direct_status_context(status: dict[str, Any]) -> str:
    return str(status.get("context") or status.get("name") or "").strip()


def _direct_status_is_success(status: dict[str, Any]) -> bool:
    return str(status.get("state") or "").strip().upper() == "SUCCESS"


def _direct_status_is_non_green(status: dict[str, Any]) -> bool:
    state = str(status.get("state") or "").strip().upper()
    if state == "SUCCESS":
        return False
    return bool(state)


def _latest_direct_statuses_by_context(
    statuses: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    latest: dict[str, tuple[str, int, dict[str, Any]]] = {}
    for index, status in enumerate(statuses):
        context = _direct_status_context(status)
        if not context:
            continue
        timestamp = str(
            status.get("updatedAt")
            or status.get("updated_at")
            or status.get("createdAt")
            or status.get("created_at")
            or ""
        )
        previous = latest.get(context)
        if (
            previous is None
            or timestamp > previous[0]
            or (timestamp == previous[0] and index < previous[1])
        ):
            latest[context] = (timestamp, index, status)
    return {context: item[2] for context, item in latest.items()}


def _latest_direct_status_for_required(
    statuses: list[dict[str, Any]],
    required: dict[str, Any],
) -> dict[str, Any] | None:
    # GitHub branch-protection ``checks`` entries with an app id refer to
    # check-runs, not legacy commit statuses. Only app-less contexts can be
    # satisfied by the statuses endpoint.
    if required.get("app_id") is not None:
        return None
    context = str(required.get("context") or "").strip()
    if not context:
        return None
    return _latest_direct_statuses_by_context(statuses).get(context)
