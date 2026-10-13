"""Transport-neutral :class:`PDBExecutionInput` builder for PR 3.

Given ``(repo, pr_number)``, this module shells out to ``gh`` to
materialize everything the Protocol B executor needs:

- the current head SHA
- the PR title, body, labels, changed-file list
- a bounded diff excerpt
- a heuristic :class:`PRReviewProtocolPacket` built from the PR metadata

The output is a :class:`aragora.pdb.protocol.PDBExecutionInput` plus the
current head SHA (so the HTTP caller can key storage lookups on it).

Design constraints
------------------

- **No HTTP concerns.** This is a plain I/O module. The HTTP handler
  translates :class:`InputLoaderError` into the appropriate status
  code, not the loader.
- **No asyncio.** The worker wraps calls into this module through
  ``run_in_executor`` — keeping the loader synchronous means the tests
  can call it directly without an event loop.
- **Fails fast on missing input.** A missing PR (``gh`` returns
  non-zero) or a missing ``gh`` binary raises
  :class:`InputLoaderError` with ``reason=<enum>`` so callers can
  distinguish infrastructure faults from user-input faults.
- **No cached SHA reads.** The head SHA is always refreshed from the
  PR metadata; stale detection in storage depends on truthful SHAs.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from aragora.pdb.protocol import PDBExecutionInput
from aragora.review.policy import ReviewPolicy
from aragora.swarm.pr_review_protocol import (
    PRReviewBinding,
    PRReviewProtocolPacket,
    default_pr_review_protocol,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_DIFF_EXCERPT_CHARS",
    "GH_TIMEOUT_SECONDS",
    "InputLoaderError",
    "InputLoaderErrorReason",
    "LoadedExecutionInput",
    "load_execution_input",
]


DEFAULT_DIFF_EXCERPT_CHARS = 80_000
"""Soft cap on how many characters of the diff feed into the executor.

8K × 10 reviewers is a reasonable context budget. Truncation happens
at a line boundary so the ``diff --git`` header of the last included
hunk is not cut mid-line.
"""

GH_TIMEOUT_SECONDS = 30
"""Per-``gh`` invocation timeout. Matches the existing review-queue handler."""


_PR_VIEW_FIELDS = [
    "number",
    "title",
    "body",
    "url",
    "headRefOid",
    "baseRefOid",
    "isDraft",
    "mergeable",
    "reviewDecision",
    "labels",
    "author",
    "additions",
    "deletions",
    "changedFiles",
    "statusCheckRollup",
    "files",
]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class InputLoaderErrorReason(str, Enum):
    """Why the loader failed. Stable across versions; HTTP maps to codes."""

    GH_MISSING = "gh_missing"
    GH_AUTHENTICATION = "gh_authentication"
    PR_NOT_FOUND = "pr_not_found"
    GH_ERROR = "gh_error"
    MALFORMED_RESPONSE = "malformed_response"
    EMPTY_HEAD_SHA = "empty_head_sha"
    TIMEOUT = "timeout"


class InputLoaderError(RuntimeError):
    """Raised when :func:`load_execution_input` cannot build its payload."""

    def __init__(self, reason: InputLoaderErrorReason, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LoadedExecutionInput:
    """Return value from :func:`load_execution_input`.

    ``head_sha`` is the PR's current head SHA and MUST be used as the
    storage key by the caller (worker + state endpoints). It can differ
    from ``input.binding.head_sha`` only if the loader is called with a
    stale cache — in practice they are identical, but the dataclass
    makes the invariant explicit.
    """

    input: PDBExecutionInput
    head_sha: str
    base_sha: str
    panel_models: tuple[str, ...]
    repo: str


# ---------------------------------------------------------------------------
# gh shell helpers
# ---------------------------------------------------------------------------


def _run_gh(args: Sequence[str], *, capture: bool = True) -> tuple[int, str, str]:
    """Run a ``gh`` command, returning ``(rc, stdout, stderr)``.

    Raises :class:`InputLoaderError` for infrastructure faults
    (missing binary, timeout). Returning a non-zero rc without raising
    lets the caller inspect stderr and classify the error.
    """

    try:
        proc = subprocess.run(  # args are code-controlled lists
            ["gh", *args],
            capture_output=capture,
            text=True,
            check=False,
            timeout=GH_TIMEOUT_SECONDS,
        )
    except FileNotFoundError as exc:
        raise InputLoaderError(
            InputLoaderErrorReason.GH_MISSING,
            "gh CLI not found on PATH",
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise InputLoaderError(
            InputLoaderErrorReason.TIMEOUT,
            f"gh {' '.join(args)} exceeded {GH_TIMEOUT_SECONDS}s",
        ) from exc
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _classify_gh_error(stderr: str, *, pr_number: int) -> InputLoaderErrorReason:
    lower = stderr.lower()
    if "not found" in lower or "no pull request found" in lower or "could not find" in lower:
        return InputLoaderErrorReason.PR_NOT_FOUND
    if "authentication" in lower or "not logged" in lower or "auth token" in lower:
        return InputLoaderErrorReason.GH_AUTHENTICATION
    return InputLoaderErrorReason.GH_ERROR


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def _subsystem_for(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if not parts:
        return "(root)"
    top = parts[0]
    if top in ("aragora", "tests") and len(parts) >= 2:
        return f"{top}/{parts[1]}"
    return top


def _labels(payload: Any) -> tuple[str, ...]:
    result: list[str] = []
    if isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict):
                name = str(entry.get("name", "")).strip()
                if name:
                    result.append(name)
    return tuple(result)


def _changed_files(payload: Any) -> tuple[str, ...]:
    result: list[str] = []
    if isinstance(payload, list):
        for entry in payload:
            if isinstance(entry, dict):
                path = str(entry.get("path", "")).strip()
                if path:
                    result.append(path)
    return tuple(result)


def _repo_from_url(url: str) -> str:
    """Parse ``github.com/<owner>/<repo>`` → ``<owner>/<repo>``.

    Falls back to empty string when the URL is malformed; the caller's
    validation of required inputs catches that case.
    """
    url = (url or "").strip()
    if not url:
        return ""
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if url.startswith(prefix):
            rest = url[len(prefix) :]
            parts = rest.split("/")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
    return ""


def _summarize_checks(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, list):
        return {"success": 0, "failure": 0, "pending": 0, "total": 0}
    success = failure = pending = 0
    for entry in payload:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "")).upper()
        conclusion = str(entry.get("conclusion", "")).upper()
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


def _truncate_diff(text: str, limit: int = DEFAULT_DIFF_EXCERPT_CHARS) -> str:
    if len(text) <= limit:
        return text
    # Truncate at the last full line before the byte cap so ``diff --git``
    # headers remain intact.
    head = text[:limit]
    last_nl = head.rfind("\n")
    if last_nl >= 0:
        head = head[:last_nl]
    return head + "\n[diff truncated]\n"


def _heuristic_packet_from_pr(
    *,
    binding: PRReviewBinding,
    pr: Mapping[str, Any],
    labels: Sequence[str],
    changed_files_count: int,
    additions: int,
    deletions: int,
    high_risk_paths: Sequence[str],
) -> PRReviewProtocolPacket:
    """Build the metadata-heuristic packet using the landed protocol builder.

    We delegate to :func:`default_pr_review_protocol().build_packet` to
    keep the packet field layout in lock-step with the rest of the
    review surface. The executor will overwrite this with its
    ``panel_executed`` packet — we just need a shape-valid placeholder.
    """
    checks_summary_dict = _summarize_checks(pr.get("statusCheckRollup"))
    has_failures = checks_summary_dict["failure"] > 0
    has_pending = checks_summary_dict["pending"] > 0
    checks_summary = (
        f"{checks_summary_dict['success']}/{checks_summary_dict['total']} checks passing"
        if checks_summary_dict["total"]
        else "no checks reported"
    )
    review_decision = str(pr.get("reviewDecision", "")).strip().upper()
    mergeable = str(pr.get("mergeable", "")).strip().upper()
    title = str(pr.get("title", "")).strip()

    machine_recommendation = "approve_candidate" if not has_failures else "needs_human_attention"
    machine_recommendation_reason = "metadata-heuristic placeholder; panel execution will refine."

    return default_pr_review_protocol().build_packet(
        repo=binding.repo,
        pr_number=binding.pr_number,
        title=title,
        base_sha=binding.base_sha,
        head_sha=binding.head_sha,
        mergeable=mergeable,
        review_decision=review_decision,
        checks_summary=checks_summary,
        has_failures=has_failures,
        has_pending=has_pending,
        additions=additions,
        deletions=deletions,
        changed_files=changed_files_count,
        labels=list(labels),
        high_risk_paths=list(high_risk_paths),
        validation_commands=[],
        machine_recommendation=machine_recommendation,
        machine_recommendation_reason=machine_recommendation_reason,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load_execution_input(
    *,
    pr_number: int,
    repo: str | None = None,
    policy: ReviewPolicy | None = None,
    panel_id: str = "protocol_b_default",
    diff_excerpt_char_limit: int = DEFAULT_DIFF_EXCERPT_CHARS,
) -> LoadedExecutionInput:
    """Build a :class:`PDBExecutionInput` for ``pr_number``.

    Parameters
    ----------
    pr_number:
        GitHub PR number; must be positive.
    repo:
        Optional repo override (``owner/name``). When provided it is
        passed to ``gh`` via ``--repo``. When omitted ``gh`` uses its
        own repo inference.
    policy:
        The :class:`ReviewPolicy` to attach to the execution input.
        Defaults to a vanilla :class:`ReviewPolicy`.
    panel_id:
        Panel id to run; defaults to ``protocol_b_default`` which is
        the value shipped in ``aragora/config/pdb_panel.yaml``.
    diff_excerpt_char_limit:
        Overrides :data:`DEFAULT_DIFF_EXCERPT_CHARS`. Zero or negative
        disables the diff fetch entirely.

    Raises
    ------
    InputLoaderError:
        With a machine-readable :class:`InputLoaderErrorReason` on any
        upstream fault.
    """
    if not isinstance(pr_number, int) or pr_number <= 0:
        raise ValueError("pr_number must be a positive integer")

    view_args = ["pr", "view", str(pr_number), "--json", ",".join(_PR_VIEW_FIELDS)]
    if repo:
        view_args.extend(["--repo", repo])
    rc, stdout, stderr = _run_gh(view_args)
    if rc != 0:
        reason = _classify_gh_error(stderr, pr_number=pr_number)
        raise InputLoaderError(reason, stderr.strip() or f"gh rc={rc}")
    try:
        pr = json.loads(stdout) if stdout.strip() else None
    except json.JSONDecodeError as exc:
        raise InputLoaderError(
            InputLoaderErrorReason.MALFORMED_RESPONSE,
            f"gh pr view stdout is not valid JSON: {exc}",
        ) from exc
    if not isinstance(pr, dict):
        raise InputLoaderError(
            InputLoaderErrorReason.MALFORMED_RESPONSE,
            f"gh pr view did not return an object (got {type(pr).__name__})",
        )

    head_sha = str(pr.get("headRefOid", "")).strip()
    base_sha = str(pr.get("baseRefOid", "")).strip()
    if not head_sha:
        raise InputLoaderError(
            InputLoaderErrorReason.EMPTY_HEAD_SHA,
            "gh pr view response lacks headRefOid",
        )

    url = str(pr.get("url", "")).strip()
    resolved_repo = repo or _repo_from_url(url)
    if not resolved_repo:
        raise InputLoaderError(
            InputLoaderErrorReason.MALFORMED_RESPONSE,
            "could not infer repo from gh response",
        )
    # Fail fast before spending a diff call on an invalid record.
    labels = _labels(pr.get("labels"))
    changed_files = _changed_files(pr.get("files"))
    title = str(pr.get("title", "")).strip()
    body_text = str(pr.get("body", "")).strip()
    additions = int(pr.get("additions", 0) or 0)
    deletions = int(pr.get("deletions", 0) or 0)
    changed_files_count = int(pr.get("changedFiles", 0) or len(changed_files))

    # Diff excerpt -----------------------------------------------------
    diff_excerpt = ""
    if diff_excerpt_char_limit > 0:
        diff_args = ["pr", "diff", str(pr_number)]
        if repo:
            diff_args.extend(["--repo", repo])
        rc_d, stdout_d, stderr_d = _run_gh(diff_args)
        if rc_d != 0:
            # A diff fetch failure is not fatal — the executor can still
            # reason from metadata and the heuristic packet. Log loudly.
            logger.warning(
                "pdb.input_loader: gh pr diff %s failed (rc=%s): %s",
                pr_number,
                rc_d,
                stderr_d.strip(),
            )
        else:
            diff_excerpt = _truncate_diff(stdout_d, diff_excerpt_char_limit)

    binding = PRReviewBinding(
        repo=resolved_repo,
        pr_number=pr_number,
        base_sha=base_sha,
        head_sha=head_sha,
    )

    validation_summary: dict[str, Any] = {
        "checks_summary": _summarize_checks(pr.get("statusCheckRollup")),
        "mergeable": str(pr.get("mergeable", "")).strip().upper(),
        "review_decision": str(pr.get("reviewDecision", "")).strip().upper(),
        "additions": additions,
        "deletions": deletions,
        "changed_files": changed_files_count,
        "labels": list(labels),
        "is_draft": bool(pr.get("isDraft", False)),
    }

    packet = _heuristic_packet_from_pr(
        binding=binding,
        pr=pr,
        labels=labels,
        changed_files_count=changed_files_count,
        additions=additions,
        deletions=deletions,
        high_risk_paths=[],  # resolver does not need it; executor overrides
    )

    # Panel models list for the storage queued record — surfaces in
    # ``state`` polls. Derived from candidate ids on the default
    # protocol so we don't double-couple to the YAML.
    panel_models = tuple(res.slot_id for res in packet.provider_slots)

    exec_input = PDBExecutionInput(
        binding=binding,
        packet=packet,
        packet_sha="",  # successor signing layer owns sha; empty is OK for executor
        pr_title=title,
        pr_body=body_text,
        labels=labels,
        changed_files=changed_files,
        diff_excerpt=diff_excerpt,
        validation_summary=validation_summary,
        panel_id=panel_id,
        policy=policy or ReviewPolicy(),
    )
    return LoadedExecutionInput(
        input=exec_input,
        head_sha=head_sha,
        base_sha=base_sha,
        panel_models=panel_models,
        repo=resolved_repo,
    )
