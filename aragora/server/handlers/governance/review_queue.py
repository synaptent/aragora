"""Review Queue Handler — PDB UI v0 backend endpoints.

This is the minimum-viable backend for the browser-based PR review surface
described in #6304 / docs/plans/2026-04-19-pr-intelligence-brief-addendum.md §8.

Endpoints (all under ``/api/v1/review-queue/``):

- ``GET  /api/v1/review-queue/prs``                     — list open PRs
- ``GET  /api/v1/review-queue/prs/{number}/brief``      — read brief JSON
- ``POST /api/v1/review-queue/prs/{number}/approve``    — GitHub APPROVE
- ``POST /api/v1/review-queue/prs/{number}/request-changes`` — REQUEST_CHANGES
- ``POST /api/v1/review-queue/prs/{number}/defer``      — LOCAL defer (4h)
- ``GET  /api/v1/review-queue/stats``                   — session stats
- ``GET  /api/v1/review-queue/triage-metrics``          — rolling-window
  triage metrics (#6373 — Commitment 5 of docs/THESIS.md). Requires the
  ``review_queue:read`` permission.

Safety boundaries (v0):

- Approve/request-changes shell out to the ``gh`` CLI on the local machine,
  which runs as the founder's own GitHub identity (same gate the existing
  ``aragora review-queue act`` CLI uses). The server does NOT proxy mutations
  with automation credentials. This preserves the settlement gate — merge
  arbiter still sees a human review record from the founder.
- Defer is LOCAL state only. It writes to
  ``.aragora/review-queue/deferred.json`` and NEVER touches GitHub.
- Briefs are READ-ONLY. This handler does not write brief artifacts.
  Auto-generated briefs will land via #6306.
"""

from __future__ import annotations

__all__ = [
    "ReviewQueueHandler",
    "REVIEW_QUEUE_ROOT",
    "DEFER_HOURS",
    "MAX_PR_NUMBER",
]

import hashlib
import json
import logging
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aragora.pdb import storage as brief_storage
from aragora.pdb import worker as brief_worker
from aragora.server.handlers.governance import review_queue_brief
from aragora.server.versioning.compat import strip_version_prefix
from aragora.triage import compute_window, detect_drift
from aragora.triage.event_source import iter_events_from_store

from ..base import BaseHandler, HandlerResult, error_response, json_response
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

UTC = timezone.utc

# Defer window (hours) — hides a PR from the queue while the founder focuses
# elsewhere. Deliberately short so deferred PRs resurface same-day.
DEFER_HOURS = 4

# Hard upper-bound on PR numbers we accept in paths to avoid DoS via huge ints
# or malformed input. GitHub PR numbers are sequential, 6-7 digits at most.
MAX_PR_NUMBER = 10_000_000

# Rate limiter for the review-queue surface. One human operator per session; a
# generous ceiling is fine (keyboard shortcuts can fire fast).
_review_queue_limiter = RateLimiter(requests_per_minute=120)


def _review_queue_root() -> Path:
    """Return the canonical store root for review-queue artifacts.

    Mirrors the layout used by ``aragora.cli.commands.review_queue`` so the
    UI and CLI share a single on-disk cache.
    """
    override = os.environ.get("ARAGORA_REVIEW_QUEUE_ROOT")
    if override:
        return Path(override)
    # Walk up from cwd looking for a repo root with a ``.aragora`` dir; fall
    # back to ``cwd / .aragora/review-queue`` so tests can point at tmp_path.
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".aragora").exists() or (candidate / ".git").exists():
            return candidate / ".aragora" / "review-queue"
    return cwd / ".aragora" / "review-queue"


# Exported for tests so they can patch a single value.
REVIEW_QUEUE_ROOT = _review_queue_root


def _deferred_path() -> Path:
    return REVIEW_QUEUE_ROOT() / "deferred.json"


def _session_stats_path(when: datetime | None = None) -> Path:
    when = when or datetime.now(UTC)
    return REVIEW_QUEUE_ROOT() / f"session-{when.strftime('%Y%m%d')}.json"


def _subsystem_for(path: str) -> str:
    """Cheap subsystem label — first one or two path segments."""
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "(root)"
    top = parts[0]
    if top in ("aragora", "tests") and len(parts) >= 2:
        return f"{top}/{parts[1]}"
    return top


def _summarize_checks(checks: Any) -> dict[str, int]:
    """Aggregate a GitHub statusCheckRollup payload into a small counter.

    Returns a dict with ``success``, ``failure``, ``pending``, ``total``.
    Treats skipped/cancelled/neutral checks as not-meaningful for the summary
    (same policy as ``aragora.cli.commands.review_queue``).
    """
    success = failure = pending = 0
    if not isinstance(checks, list):
        return {"success": 0, "failure": 0, "pending": 0, "total": 0}
    for check in checks:
        if not isinstance(check, dict):
            continue
        status = str(check.get("status", "")).upper()
        conclusion = str(check.get("conclusion", "")).upper()
        if conclusion == "SUCCESS":
            success += 1
        elif conclusion in ("FAILURE", "TIMED_OUT", "ACTION_REQUIRED"):
            failure += 1
        elif conclusion in ("CANCELLED", "SKIPPED", "NEUTRAL", "STALE"):
            continue
        elif status in ("IN_PROGRESS", "QUEUED", "PENDING") or not conclusion:
            pending += 1
    return {
        "success": success,
        "failure": failure,
        "pending": pending,
        "total": success + failure + pending,
    }


def _parse_pr_number(text: str) -> int | None:
    """Parse a PR number from a path segment, clamped for safety."""
    raw = (text or "").strip().lstrip("#")
    if not raw.isdigit():
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    if value <= 0 or value > MAX_PR_NUMBER:
        return None
    return value


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _load_deferred() -> dict[str, dict[str, str]]:
    path = _deferred_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("review-queue: could not read deferred state: %s", exc)
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned: dict[str, dict[str, str]] = {}
    for key, value in data.items():
        if isinstance(key, str) and key.isdigit() and isinstance(value, dict):
            cleaned[key] = {"deferred_until": str(value.get("deferred_until", ""))}
    return cleaned


def _save_deferred(state: dict[str, dict[str, str]]) -> None:
    path = _deferred_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def _active_deferrals(state: dict[str, dict[str, str]], now: datetime | None = None) -> set[int]:
    """Return the set of PR numbers whose defer window has not elapsed."""
    now = now or datetime.now(UTC)
    active: set[int] = set()
    for key, value in state.items():
        try:
            pr_number = int(key)
        except ValueError:
            continue
        try:
            deadline = datetime.fromisoformat(value.get("deferred_until", ""))
        except ValueError:
            continue
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        if deadline > now:
            active.add(pr_number)
    return active


def _run_gh(args: list[str], *, input_text: str | None = None) -> tuple[int, str, str]:
    """Run a ``gh`` command. Returns ``(returncode, stdout, stderr)``."""
    try:
        proc = subprocess.run(  # noqa: S603 -- args are code-controlled lists
            ["gh", *args],
            capture_output=True,
            text=True,
            check=False,
            input=input_text,
            timeout=30,
        )
    except FileNotFoundError:
        return 127, "", "gh CLI not found on server host"
    except subprocess.TimeoutExpired:
        return 124, "", "gh CLI timed out"
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _load_brief(pr_number: int) -> dict[str, Any] | None:
    """Read the latest ready brief for ``pr_number`` via the PDB storage layer.

    Delegates to :func:`aragora.pdb.storage.load_latest_ready_brief`.
    Returns ``None`` when no ready brief is on disk.

    Note: the eventual (Mode 3) brief generation API is SHA-aware and
    keys on ``(pr_number, head_sha)``; the legacy response shape used
    here is preserved deliberately to avoid breaking the current UI.
    PR 3 of the Mode 3 rollout adds a SHA-aware ``/brief/state``
    endpoint alongside this one.
    """
    return brief_storage.load_latest_ready_brief(pr_number)


def _load_stats(when: datetime | None = None) -> dict[str, Any]:
    path = _session_stats_path(when)
    if not path.exists():
        return {
            "date": (when or datetime.now(UTC)).strftime("%Y-%m-%d"),
            "approved": 0,
            "request_changes": 0,
            "deferred": 0,
            "total_decision_seconds": 0.0,
            "decision_count": 0,
            "streak": 0,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "date": (when or datetime.now(UTC)).strftime("%Y-%m-%d"),
            "approved": 0,
            "request_changes": 0,
            "deferred": 0,
            "total_decision_seconds": 0.0,
            "decision_count": 0,
            "streak": 0,
        }
    if not isinstance(data, dict):
        return {
            "date": (when or datetime.now(UTC)).strftime("%Y-%m-%d"),
            "approved": 0,
            "request_changes": 0,
            "deferred": 0,
            "total_decision_seconds": 0.0,
            "decision_count": 0,
            "streak": 0,
        }
    # Fill in defaults for older session files without all fields.
    data.setdefault("approved", 0)
    data.setdefault("request_changes", 0)
    data.setdefault("deferred", 0)
    data.setdefault("total_decision_seconds", 0.0)
    data.setdefault("decision_count", 0)
    data.setdefault("streak", 0)
    return data


def _save_stats(stats: dict[str, Any], when: datetime | None = None) -> None:
    path = _session_stats_path(when)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")


def _record_action(
    action: str, *, decision_seconds: float | None = None, when: datetime | None = None
) -> dict[str, Any]:
    """Update the daily session stats file after a settlement action."""
    stats = _load_stats(when)
    if action == "approve":
        stats["approved"] = int(stats.get("approved", 0)) + 1
        stats["streak"] = int(stats.get("streak", 0)) + 1
    elif action == "request_changes":
        stats["request_changes"] = int(stats.get("request_changes", 0)) + 1
        stats["streak"] = 0
    elif action == "defer":
        stats["deferred"] = int(stats.get("deferred", 0)) + 1
    if decision_seconds is not None and decision_seconds >= 0:
        stats["total_decision_seconds"] = float(stats.get("total_decision_seconds", 0.0)) + float(
            decision_seconds
        )
        stats["decision_count"] = int(stats.get("decision_count", 0)) + 1
    _save_stats(stats, when)
    return stats


def _shape_pr(pr: dict[str, Any], deferred: set[int]) -> dict[str, Any]:
    """Reduce a ``gh pr list`` entry into the shape the UI consumes."""
    number = int(pr.get("number", 0) or 0)
    title = str(pr.get("title", "")).strip()
    url = str(pr.get("url", "")).strip()
    head_sha = str(pr.get("headRefOid", "")).strip()
    is_draft = bool(pr.get("isDraft", False))
    author_payload = pr.get("author") or {}
    author = (
        str(author_payload.get("login", "")).strip() if isinstance(author_payload, dict) else ""
    )
    labels_payload = pr.get("labels") or []
    labels = [
        str(label.get("name", "")).strip()
        for label in labels_payload
        if isinstance(label, dict) and label.get("name")
    ]
    additions = int(pr.get("additions", 0) or 0)
    deletions = int(pr.get("deletions", 0) or 0)
    changed_files = int(pr.get("changedFiles", 0) or 0)
    created_at = str(pr.get("createdAt", "")).strip()
    updated_at = str(pr.get("updatedAt", "")).strip()

    files_payload = pr.get("files") or []
    touched_subsystems: list[str] = []
    if isinstance(files_payload, list):
        seen: set[str] = set()
        for entry in files_payload:
            if not isinstance(entry, dict):
                continue
            subsystem = _subsystem_for(str(entry.get("path", "")))
            if subsystem and subsystem not in seen:
                seen.add(subsystem)
                touched_subsystems.append(subsystem)

    ci = _summarize_checks(pr.get("statusCheckRollup"))

    age_seconds: int | None = None
    if created_at:
        try:
            created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_seconds = max(0, int((datetime.now(UTC) - created_dt).total_seconds()))
        except ValueError:
            age_seconds = None

    brief = _load_brief(number)
    brief_present = brief is not None
    verdict = str(brief.get("verdict", "")).strip() if isinstance(brief, dict) else ""
    confidence = brief.get("confidence") if isinstance(brief, dict) else None
    if not isinstance(confidence, int):
        confidence = None

    return {
        "number": number,
        "title": title,
        "url": url,
        "head_sha": head_sha,
        "is_draft": is_draft,
        "author": author,
        "labels": labels,
        "additions": additions,
        "deletions": deletions,
        "changed_files": changed_files,
        "created_at": created_at,
        "updated_at": updated_at,
        "age_seconds": age_seconds,
        "touched_subsystems": touched_subsystems,
        "ci": ci,
        "brief_present": brief_present,
        "verdict": verdict or None,
        "confidence": confidence,
        "deferred": number in deferred,
    }


class ReviewQueueHandler(BaseHandler):
    """HTTP handler for PDB UI v0 review-queue endpoints."""

    # Base paths are intentionally omitted: the root /api/review-queue is
    # not itself a real endpoint (handle() returns 404 for empty subpath),
    # so declaring it would pollute OpenAPI with a placeholder. The wildcard
    # captures all real routes (/prs, /prs/{n}/brief, etc.).
    ROUTES = [
        "/api/review-queue/*",
        "/api/v1/review-queue/*",
        # Exact literals for spec-documented operations (wildcards above are
        # invisible to the OpenAPI route validator's orphan check).
        "/api/review-queue/triage-metrics",
        "/api/v1/review-queue/triage-metrics",
    ]

    ROUTE_PREFIXES = [
        "/api/review-queue",
        "/api/review-queue/",
        "/api/v1/review-queue",
        "/api/v1/review-queue/",
    ]

    def __init__(self, ctx: dict[str, Any] | None = None) -> None:
        self.ctx = ctx or {}

    def can_handle(self, path: str, method: str = "GET") -> bool:
        normalized = strip_version_prefix(path)
        return normalized == "/api/review-queue" or normalized.startswith("/api/review-queue/")

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def handle(self, path: str, query_params: dict[str, Any], handler: Any) -> HandlerResult | None:
        """Route GET requests under ``/api/v1/review-queue``."""
        method = (getattr(handler, "command", None) or "GET").upper()
        if method == "DELETE":
            return self.handle_delete(path, query_params, handler)
        if method != "GET":
            return self.handle_post(path, query_params, handler)

        client_ip = get_client_ip(handler) if handler else "unknown"
        if not _review_queue_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        normalized = strip_version_prefix(path).rstrip("/")
        subpath = (
            normalized[len("/api/review-queue") :]
            if normalized.startswith("/api/review-queue")
            else ""
        )

        if subpath in ("", "/"):
            return error_response("Not found", 404)
        if subpath == "/prs":
            return self._list_prs()
        if subpath == "/stats":
            return self._get_stats()
        if subpath == "/triage-metrics":
            return self._get_triage_metrics(query_params, handler)
        if subpath.startswith("/prs/"):
            tail = subpath[len("/prs/") :]
            segments = [seg for seg in tail.split("/") if seg]
            if len(segments) == 2 and segments[1] == "brief":
                pr_number = _parse_pr_number(segments[0])
                if pr_number is None:
                    return error_response("Invalid PR number", 400)
                return self._get_brief(pr_number)
            if len(segments) == 3 and segments[1] == "brief" and segments[2] == "state":
                pr_number = _parse_pr_number(segments[0])
                if pr_number is None:
                    return error_response("Invalid PR number", 400)
                return review_queue_brief.handle_state(pr_number)
        return error_response("Not found", 404)

    def handle_post(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route POST requests (approve / request-changes / defer / brief-generate)."""
        client_ip = get_client_ip(handler) if handler else "unknown"
        if not _review_queue_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        # All mutating endpoints require an authenticated session. This does
        # NOT carry GitHub identity; the actual GitHub review is made by the
        # local ``gh`` CLI, which runs as the founder's own account.
        user, err = self.require_auth_or_error(handler)
        if err is not None:
            return err

        normalized = strip_version_prefix(path).rstrip("/")
        subpath = (
            normalized[len("/api/review-queue") :]
            if normalized.startswith("/api/review-queue")
            else ""
        )
        if not subpath.startswith("/prs/"):
            return error_response("Not found", 404)
        tail = subpath[len("/prs/") :]
        segments = [seg for seg in tail.split("/") if seg]

        # /prs/{n}/brief/generate → Mode 3 on-demand generation
        if len(segments) == 3 and segments[1] == "brief" and segments[2] == "generate":
            pr_number = _parse_pr_number(segments[0])
            if pr_number is None:
                return error_response("Invalid PR number", 400)
            body = self.read_json_body(handler) or {}
            return review_queue_brief.handle_generate(
                pr_number,
                body,
                user,
                worker=brief_worker.get_worker(),
            )

        if len(segments) != 2:
            return error_response("Not found", 404)
        pr_number = _parse_pr_number(segments[0])
        if pr_number is None:
            return error_response("Invalid PR number", 400)
        action = segments[1]

        body = self.read_json_body(handler) or {}

        if action == "approve":
            return self._post_approve(pr_number, body, user)
        if action == "request-changes":
            return self._post_request_changes(pr_number, body, user)
        if action == "defer":
            return self._post_defer(pr_number, body, user)
        return error_response("Not found", 404)

    def handle_delete(
        self, path: str, query_params: dict[str, Any], handler: Any
    ) -> HandlerResult | None:
        """Route DELETE /api/v1/review-queue/prs/{n}/brief/generate."""
        client_ip = get_client_ip(handler) if handler else "unknown"
        if not _review_queue_limiter.is_allowed(client_ip):
            return error_response("Rate limit exceeded", 429)

        user, err = self.require_auth_or_error(handler)
        if err is not None:
            return err

        normalized = strip_version_prefix(path).rstrip("/")
        subpath = (
            normalized[len("/api/review-queue") :]
            if normalized.startswith("/api/review-queue")
            else ""
        )
        if not subpath.startswith("/prs/"):
            return error_response("Not found", 404)
        tail = subpath[len("/prs/") :]
        segments = [seg for seg in tail.split("/") if seg]
        if len(segments) == 3 and segments[1] == "brief" and segments[2] == "generate":
            pr_number = _parse_pr_number(segments[0])
            if pr_number is None:
                return error_response("Invalid PR number", 400)
            return review_queue_brief.handle_cancel(
                pr_number,
                user,
                worker=brief_worker.get_worker(),
            )
        return error_response("Not found", 404)

    # ------------------------------------------------------------------
    # GET endpoints
    # ------------------------------------------------------------------

    def _list_prs(self) -> HandlerResult:
        """List open PRs, enriched with brief + CI + defer state.

        Reads from ``gh`` CLI. If ``gh`` is not installed / not authenticated,
        returns an empty list rather than 500 so the UI can still render.
        """
        fields = ",".join(
            [
                "number",
                "title",
                "url",
                "headRefOid",
                "isDraft",
                "author",
                "labels",
                "additions",
                "deletions",
                "changedFiles",
                "createdAt",
                "updatedAt",
                "statusCheckRollup",
                "files",
            ]
        )
        rc, stdout, stderr = _run_gh(
            ["pr", "list", "--state", "open", "--limit", "100", "--json", fields]
        )
        if rc != 0:
            logger.info("review-queue: gh pr list unavailable (rc=%s): %s", rc, stderr.strip())
            return json_response(
                {
                    "prs": [],
                    "total": 0,
                    "degraded": True,
                    "reason": stderr.strip() or "gh CLI unavailable — log in with `gh auth login`.",
                }
            )
        try:
            raw = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError as exc:
            return error_response(f"Malformed gh response: {exc}", 502)

        deferred_state = _load_deferred()
        active_deferrals = _active_deferrals(deferred_state)

        prs: list[dict[str, Any]] = []
        for pr in raw or []:
            if not isinstance(pr, dict):
                continue
            prs.append(_shape_pr(pr, active_deferrals))

        # Default sort: non-deferred first, then newest first (descending number).
        prs.sort(key=lambda p: (p["deferred"], -int(p["number"])))

        visible = [p for p in prs if not p["deferred"]]
        return json_response(
            {
                "prs": prs,
                "total": len(prs),
                "visible": len(visible),
                "deferred_count": len(active_deferrals),
                "degraded": False,
            }
        )

    def _get_brief(self, pr_number: int) -> HandlerResult:
        brief = _load_brief(pr_number)
        if brief is None:
            return error_response("Brief not found", 404)
        return json_response({"brief": brief})

    def _get_stats(self) -> HandlerResult:
        stats = _load_stats()
        decision_count = int(stats.get("decision_count", 0) or 0)
        total_seconds = float(stats.get("total_decision_seconds", 0.0) or 0.0)
        median_seconds = (total_seconds / decision_count) if decision_count > 0 else None
        return json_response(
            {
                "stats": {
                    "date": stats.get("date"),
                    "approved": int(stats.get("approved", 0) or 0),
                    "request_changes": int(stats.get("request_changes", 0) or 0),
                    "deferred": int(stats.get("deferred", 0) or 0),
                    "streak": int(stats.get("streak", 0) or 0),
                    "decision_count": decision_count,
                    "median_decision_seconds": median_seconds,
                }
            }
        )

    def _get_triage_metrics(
        self,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Return rolling-window triage metrics (#6373, Commitment 5).

        Computes 7-day and 30-day windows over the existing settlement
        receipts on disk and returns the four Commitment-5 metrics plus
        advisory drift between them. Auth is required via
        ``review_queue:read`` so dashboards can be scoped per role.
        Honors the ``If-None-Match`` header for ETag round-trip.

        Metrics that cannot be computed from the current receipt schema
        (``human_override_outcome_correlation`` is the notable one —
        settlement receipts do not record merge outcomes) are returned
        as ``null`` with an explanatory entry in the ``notes`` block
        rather than synthesized. This follows the honest-partial-
        coverage principle: a ``null`` with a documented gap is
        strictly better than a false-precision value.
        """
        user, err = self.require_permission_or_error(handler, "review_queue:read")
        if err is not None:
            return err
        _ = user  # permission check is the only thing we need here

        now = datetime.now(UTC)
        try:
            events = list(iter_events_from_store())
        except OSError as exc:
            logger.warning("review-queue: could not read settlement receipts: %s", exc)
            events = []

        seven = compute_window(events, window_end=now, window_days=7)
        thirty = compute_window(events, window_end=now, window_days=30)

        # Drift is advisory: 7d vs 30d is the simplest within-one-request
        # comparison available without persisting prior snapshots. A
        # future enhancement can persist the previous window and compare
        # window-to-window across time.
        drift = detect_drift(seven, thirty)

        windows_payload = {
            "7d": seven.to_dict(),
            "30d": thirty.to_dict(),
        }
        payload: dict[str, Any] = {
            "windows": windows_payload,
            "drift": drift,
            "generated_at": now.isoformat(),
            "commitment": "docs/THESIS.md Commitment 5",
        }

        # ETag is computed from the *content-addressable* portion of
        # the response: the metrics themselves (counts + rates) plus
        # the drift verdict, with per-request timestamps stripped.
        # Two requests that observe the same settlement-receipt tree
        # within the same logical window get the same ETag, enabling
        # 304 responses on re-poll.
        etag_basis = {
            "7d": _etag_window_basis(seven.to_dict()),
            "30d": _etag_window_basis(thirty.to_dict()),
            "drift": drift,
        }
        etag_bytes = json.dumps(etag_basis, default=str, sort_keys=True).encode("utf-8")
        etag = '"' + hashlib.sha256(etag_bytes).hexdigest()[:32] + '"'
        body_bytes = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")

        if_none_match = None
        if handler is not None:
            hdrs = getattr(handler, "headers", None)
            if hdrs is not None:
                if_none_match = hdrs.get("If-None-Match") if hasattr(hdrs, "get") else None
        if if_none_match and if_none_match.strip() == etag:
            return HandlerResult(
                status_code=304,
                content_type="application/json",
                body=b"",
                headers={"ETag": etag, "Cache-Control": "no-cache"},
            )

        return HandlerResult(
            status_code=200,
            content_type="application/json",
            body=body_bytes,
            headers={"ETag": etag, "Cache-Control": "no-cache"},
        )

    # ------------------------------------------------------------------
    # POST endpoints
    # ------------------------------------------------------------------

    def _post_approve(self, pr_number: int, body: dict[str, Any], user: Any) -> HandlerResult:
        note = str(body.get("note", "") or "").strip()
        decision_seconds = _coerce_float(body.get("decision_seconds"))

        args = ["pr", "review", str(pr_number), "--approve"]
        if note:
            args.extend(["--body", note])
        rc, stdout, stderr = _run_gh(args)
        if rc != 0:
            return _gh_error_response(rc, stderr)

        stats = _record_action("approve", decision_seconds=decision_seconds)
        logger.info(
            "review-queue approve: user=%s pr=%s", getattr(user, "user_id", None), pr_number
        )
        return json_response(
            {
                "status": "ok",
                "action": "approve",
                "pr_number": pr_number,
                "settled_at": _now_iso(),
                "output": stdout.strip(),
                "stats": stats,
            }
        )

    def _post_request_changes(
        self, pr_number: int, body: dict[str, Any], user: Any
    ) -> HandlerResult:
        reason = str(body.get("reason", "") or "").strip()
        if not reason:
            return error_response(
                "reason is required for request-changes so the repair loop stays bounded",
                400,
            )
        decision_seconds = _coerce_float(body.get("decision_seconds"))

        rc, stdout, stderr = _run_gh(
            ["pr", "review", str(pr_number), "--request-changes", "--body", reason]
        )
        if rc != 0:
            return _gh_error_response(rc, stderr)

        stats = _record_action("request_changes", decision_seconds=decision_seconds)
        logger.info(
            "review-queue request-changes: user=%s pr=%s",
            getattr(user, "user_id", None),
            pr_number,
        )
        return json_response(
            {
                "status": "ok",
                "action": "request_changes",
                "pr_number": pr_number,
                "settled_at": _now_iso(),
                "output": stdout.strip(),
                "stats": stats,
            }
        )

    def _post_defer(self, pr_number: int, body: dict[str, Any], user: Any) -> HandlerResult:
        """Defer is LOCAL state. Nothing touches GitHub."""
        reason = str(body.get("reason", "") or "").strip()
        hours = body.get("hours")
        try:
            hours_int = int(hours) if hours is not None else DEFER_HOURS
        except (TypeError, ValueError):
            hours_int = DEFER_HOURS
        if hours_int <= 0 or hours_int > 72:
            hours_int = DEFER_HOURS

        state = _load_deferred()
        deadline = datetime.now(UTC) + timedelta(hours=hours_int)
        state[str(pr_number)] = {
            "deferred_until": deadline.isoformat(),
            "reason": reason,
            "by": str(getattr(user, "user_id", "") or ""),
        }
        _save_deferred(state)
        stats = _record_action("defer")
        logger.info(
            "review-queue defer: user=%s pr=%s hours=%s",
            getattr(user, "user_id", None),
            pr_number,
            hours_int,
        )
        return json_response(
            {
                "status": "ok",
                "action": "defer",
                "pr_number": pr_number,
                "deferred_until": deadline.isoformat(),
                "hours": hours_int,
                "stats": stats,
            }
        )


def _etag_window_basis(window: dict[str, Any]) -> dict[str, Any]:
    """Return a stable slice of a window dict for ETag hashing.

    Strips per-request timestamps (``window_start``, ``window_end``)
    so two requests that see the same settlement data within the same
    logical window width produce the same ETag. Keeps everything that
    actually reflects the state of the receipts on disk.
    """
    return {
        "window_label": window.get("window_label"),
        "window_days": window.get("window_days"),
        "total_decisions": window.get("total_decisions"),
        "escalation_rate": window.get("escalation_rate"),
        "auto_handle_override_rate": window.get("auto_handle_override_rate"),
        "human_override_outcome_correlation": window.get("human_override_outcome_correlation"),
        "settlement_duration_median_s": window.get("settlement_duration_median_s"),
        "settlement_duration_p95_s": window.get("settlement_duration_p95_s"),
        "counts": window.get("counts"),
    }


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gh_error_response(rc: int, stderr: str) -> HandlerResult:
    message = stderr.strip() or "gh CLI error"
    status = 502
    if rc == 127:
        status = 503
        message = (
            "gh CLI not found on server. Install and authenticate `gh` to settle PRs "
            "from the web UI."
        )
    elif "authentication" in message.lower() or "not logged" in message.lower():
        status = 403
        message = "gh CLI not authenticated. Run `gh auth login` to attach your GitHub identity."
    return error_response(message, status)
