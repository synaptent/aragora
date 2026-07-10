"""PR review queue, advisory packets, and human settlement (Phases 2a/2b).

This command keeps machine review advisory-only while making the human
settlement step fast and receipt-backed:

- ``build`` prioritizes open PRs for founder review
- ``packet`` builds the advisory packet for one live PR head
- ``run`` walks a human through approve/request-changes/defer in one loop
- ``act`` performs one explicit human settlement action with freshness checks

Out of scope (intentionally still not implemented):

- ``review-queue digest`` (rolled-up activity report)
- ``merge_arbiter`` enforcement of settlement receipts
- Bot-only merge on green CI
- Any hidden merge path that bypasses explicit human action

See docs/plans/2026-04-19-batched-pr-review-triage.md for the full design.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from aragora.cli.commands import review_queue_rest_fallback as rest_fallback
from aragora.cli.commands.review_queue_parsers import (
    add_observe_outcomes_parser,
    add_record_settlement_parser,
)
from aragora.cli.commands.review_queue_comment_verdicts import (
    has_blocking_finding_or_label as _has_blocking_finding_or_label,
    has_blocking_or_negative_verdict as _has_blocking_or_negative_verdict,
    highest_blocking_severity as _highest_blocking_severity,
)
from aragora.cli.commands.review_queue_tier4_settlement import (
    DEFAULT_TRUSTED_SETTLEMENT_CREATOR as DEFAULT_TRUSTED_SETTLEMENT_CREATOR,
    HUMAN_SETTLEMENT_CONTEXT as HUMAN_SETTLEMENT_CONTEXT,
    SETTLEMENT_CREATOR_ENV_VAR as SETTLEMENT_CREATOR_ENV_VAR,
    TIER_FOUR_AUTHORIZED_MERGE_TOKENS as TIER_FOUR_AUTHORIZED_MERGE_TOKENS,
    TIER_FOUR_SETTLEMENT_MARKER as TIER_FOUR_SETTLEMENT_MARKER,
    _has_tier_four_human_preapproval_comment as _has_tier_four_human_preapproval_comment,
    _human_settlement_status_creator_verified as _human_settlement_status_creator_verified,
    _trusted_settlement_creator as _trusted_settlement_creator,
    _trusted_recorded_settlement_comment_url as _trusted_recorded_settlement_comment_url,
    _trusted_tier_four_human_preapproval_comment_url as _trusted_tier_four_human_preapproval_comment_url,
)
from aragora.cli.commands.review_queue_transport import (
    _GhError,
    _gh_error_kind,
    _gh_json,
    _gh_text,
    _is_github_transport_error,
    _merge_packet_transport_blocked_envelope_with_rest_fallback,
    _queue_conductor_transport_blocked_envelope,
)

if TYPE_CHECKING:
    from aragora.review.invalidation import BaselineMeasurement, ThresholdProposal
    from aragora.review.reviewer_output import ReviewerOutput

UTC = timezone.utc
PostMergeLaneAuditProvider = Callable[[int, bool], dict[str, Any]]
DEFAULT_BASELINE_WINDOW_DAYS = 30
DEFAULT_MIN_BASELINE_SAMPLES = 50
DEFAULT_SAFETY_MARGIN = 0.5
DEFAULT_MINIMUM_MEANINGFUL_RATE = 0.01


class AutoHandleCalibrationStore:
    """Lazy proxy for the calibration store used by review-queue rendering.

    The module-level name is a historical monkeypatch seam in tests. Delegating
    from methods rather than replacing __new__ keeps that seam available without
    importing the calibration stack during merge-packet startup.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        from aragora.triage.auto_handle_calibration import (
            AutoHandleCalibrationStore as _AutoHandleCalibrationStore,
        )

        self._impl = _AutoHandleCalibrationStore(*args, **kwargs)

    def list_active_alerts(self, *args: Any, **kwargs: Any) -> Any:
        return self._impl.list_active_alerts(*args, **kwargs)


# Lane classification thresholds and risk-path catalog.
LARGE_DIFF_THRESHOLD = 500  # additions + deletions, beyond which "needs_human_attention"
MODEL_REVIEW_QUEUE_CAP = 6
MODEL_REVIEW_QUORUM_VERSION = "model_review_quorum.v1"
GITHUB_TRANSPORT_ERROR_KIND = "github_transport"
GITHUB_TRANSPORT_BLOCKED_STATUS = "transport_blocked"
_GITHUB_TRANSPORT_ERROR_MARKERS = (
    "api rate limit already exceeded",
    "check your internet connection",
    "client.timeout exceeded",
    "connection refused",
    "connection reset",
    "connection timed out",
    "context deadline exceeded",
    "could not resolve host",
    "error connecting",
    "failed to start",
    "http 502",
    "http 503",
    "http 504",
    "i/o timeout",
    "net/http",
    "no such host",
    "operation timed out",
    "rate limit exceeded",
    "temporary failure in name resolution",
    "timeout awaiting response headers",
    "tls handshake timeout",
)
CANONICAL_MODEL_FAMILIES: tuple[str, ...] = (
    "claude",
    "openai",
    "gemini",
    "grok",
    "mistral",
    "deepseek",
    "qwen",
    "kimi",
    "yi",
    "glm",
    "minimax",
    "hermes",
)
# Western-frontier families (Tier 1-2 single-signal bar must be one of these).
# Single canonical definition lives in aragora.swarm.quorum_evidence and is
# re-exported here so the merge-gate (this module) and the auto-settle path
# (quorum_evidence) reference the *same* frozenset object and cannot drift —
# replacing the prior test-only parity guard (claude #8507 P2).
from aragora.swarm.quorum_evidence import (  # noqa: E402
    WESTERN_FAMILIES as WESTERN_FAMILIES,
    WESTERN_FRONTIER_FAMILIES as WESTERN_FRONTIER_FAMILIES,
    advisory_dissent_settle_enabled as advisory_dissent_settle_enabled,
    severity_gated_dissent_enabled as severity_gated_dissent_enabled,
    tier_quorum_rule as tier_quorum_rule,
    tiered_merge_gate_enabled as tiered_merge_gate_enabled,
)

DIRECT_MODEL_FAMILY_MARKERS: dict[str, tuple[str, ...]] = {
    "claude": ("claude", "anthropic"),
    "openai": ("openai",),
    "gemini": ("gemini", "google"),
    "grok": ("grok", "xai"),
    "mistral": ("mistral", "codestral"),
    "deepseek": ("deepseek",),
    "qwen": ("qwen",),
    "kimi": ("kimi", "moonshot"),
    "yi": ("yi", "yi-large"),
    "glm": ("glm", "zhipu", "z-ai"),
    "minimax": ("minimax",),
    "hermes": ("hermes", "nous hermes"),
}
ROUTER_SURFACE_REVIEWERS: frozenset[str] = frozenset(("factory", "codex", "tesla", "harvey"))
IDENTITY_COUNT_BLOCKERS: frozenset[str] = frozenset(
    (
        "missing_model_family_disclosure",
        "unknown_model_family",
        "heading_model_family_conflict",
        "unknown_surface_reviewer",
    )
)


@dataclass(frozen=True)
class ModelReviewIdentity:
    surface_reviewer_id: str
    model_family: str
    model_id: str
    identity_source: str
    identity_problems: tuple[str, ...] = ()

    def as_packet_fields(self) -> dict[str, Any]:
        return {
            "surface_reviewer_id": self.surface_reviewer_id,
            "model_family": self.model_family,
            "model_id": self.model_id,
            "identity_source": self.identity_source,
            "identity_problems": list(self.identity_problems),
        }


HIGH_RISK_PATHS: tuple[str, ...] = (
    "CLAUDE.md",
    "aragora/__init__.py",
    ".env",
    "scripts/nomic_loop.py",
)
HIGH_RISK_PREFIXES: tuple[str, ...] = (
    "aragora/security/",
    "aragora/auth/",
    "aragora/blockchain/",
    "aragora/rbac/",
    "scripts/auto_revert",
    ".github/workflows/",
)
TIER_2_PREFIXES: tuple[str, ...] = (
    "aragora/cli/",
    "aragora/swarm/",
    "aragora/observability/",
    "aragora/knowledge/mound/metrics",
    "scripts/",
)
TIER_3_PREFIXES: tuple[str, ...] = (
    "aragora/auth/",
    "aragora/rbac/",
    "aragora/security/",
    "aragora/privacy/",
    "aragora/compliance/",
    "aragora/metrics/",
    "aragora/reputation/",
    "aragora/debate/team_selector.py",
    "aragora/server/fastapi/routes/",
    "aragora/server/handlers/",
    "aragora/migrations/",
    "sdk/",
)
TIER_3_TITLE_KEYWORDS: tuple[str, ...] = (
    "agt-",
    "calibration",
    "reputation",
    "semantic",
    "scoring",
    "persistence",
    "public api",
)
TIER_4_PREFIXES: tuple[str, ...] = (
    ".github/workflows/",
    "deploy/",
    "docker/",
    "k8s/",
    # Merge-authority self-modification: when a PR changes the code that
    # enforces model-quorum settlement gates, that PR's own quorum is
    # evaluated by the version of the gate it is trying to land. A bug or
    # weakening introduced in the diff would let the diff itself through.
    # Elevate to Tier 4 (human preapproval) so the human chain-of-trust is
    # not delegated to the artifact under review.
    "aragora/cli/commands/review_queue.py",
    "aragora/swarm/quorum_evidence.py",
    # ``aragora/cli/parser.py`` is the registration surface for every
    # ``aragora`` subcommand the operator can invoke. Adding or modifying a
    # registration changes which entrypoints exist on the merge-authority
    # CLI — a new subcommand could expose tier-relevant behavior (signal
    # collection, settlement recording, packet generation) that the gate
    # would otherwise not see. Listing the parser here makes the
    # registration surface follow the same human-chain-of-trust rule as
    # ``review_queue.py`` itself.
    "aragora/cli/parser.py",
    # ``aragora/swarm/quorum_evidence.py`` composes and verdict-classifies the
    # model-quorum evidence this gate counts (supportive / dissenting / abstain).
    # A change there directly alters what evidence the gate trusts, so — like
    # review_queue.py itself — it must follow the human-chain-of-trust rule
    # (operator preapproval + head-bound settlement) rather than be auto-settled
    # by the tier-2 path. The drain merge-authority guard already treats it as
    # such; this aligns the settlement classifier with that guard and the policy.
    "aragora/swarm/quorum_evidence.py",
    # Settlement and merge helpers can mark human-settlement status, reconcile
    # branch protection, or merge/admin-merge PRs. A PR changing those helpers
    # is changing the authority surface that future settlement runs trust.
    "scripts/settle_tier4_pr.py",
    "scripts/settle_one_pr.py",
    "scripts/merge_codex_automation_prs.py",
)
PARKED_LABELS: tuple[str, ...] = ("stale", "do-not-merge", "wip", "blocked")
OPERATOR_REVIEW_REQUIRED_LABEL = "operator-review-required"
MERGE_QUORUM_CHECK_NAME = "aragora-merge-quorum"
MERGE_QUORUM_WORKFLOW_NAME = "Aragora Merge Quorum"
MERGE_QUORUM_JOB_ID = "merge-quorum"
CHECK_SURFACE_DIAGNOSTIC_LIMIT = 12
OPTIONAL_RUNNER_CAPACITY_NOISE_MIN_SECONDS = 60 * 60
GH_COMMAND_TIMEOUT_SECONDS = 30
GIT_STATUS_TIMEOUT_SECONDS = 10


def resolve_repo_root(path_hint: Path) -> Path:
    """Resolve git repo root without importing the full worktree package."""
    proc = subprocess.run(
        ["git", "-C", str(path_hint), "rev-parse", "--show-toplevel"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
        timeout=GIT_STATUS_TIMEOUT_SECONDS,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return path_hint.resolve()


def default_pr_review_protocol() -> Any:
    from aragora.swarm.pr_review_protocol import default_pr_review_protocol as _impl

    return _impl()


def run_post_merge_lane_audit(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from scripts.post_merge_lane_audit import run_post_merge_lane_audit as _impl

    return _impl(*args, **kwargs)


def post_merge_lane_audit_failed(*args: Any, **kwargs: Any) -> bool:
    from scripts.post_merge_lane_audit import post_merge_lane_audit_failed as _impl

    return bool(_impl(*args, **kwargs))


def post_merge_lane_audit_failure_reason(*args: Any, **kwargs: Any) -> str:
    from scripts.post_merge_lane_audit import post_merge_lane_audit_failure_reason as _impl

    return str(_impl(*args, **kwargs))


LANE_ORDER: dict[str, int] = {
    "ready_now": 0,
    "needs_attention": 1,
    "repairable": 2,
    "parked": 3,
}

ADVISORY_NOTE = (
    "This packet is advisory only. It does not approve or block merge. Human settlement required."
)
REVIEW_QUEUE_ARTIFACT_DIR = ".aragora/review-queue"
REQUEST_CHANGES_REASON_REQUIRED = (
    "request-changes requires a one-line human reason so the repair loop stays bounded."
)
DEFER_REASON_REQUIRED = (
    "defer requires a one-line human reason so the PR does not disappear silently."
)


@dataclass(slots=True)
class QueueItem:
    """One row in the prioritized review queue."""

    number: int
    title: str
    url: str
    head_sha: str
    author: str
    is_draft: bool
    mergeable: str
    review_decision: str
    labels: list[str]
    additions: int
    deletions: int
    changed_files: int
    checks_summary: str
    lane: str
    lane_reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReviewPacket:
    """Advisory packet for one PR. NEVER counts as a GitHub approval."""

    pr_number: int
    title: str
    url: str
    head_sha: str
    base_sha: str
    author: str
    is_draft: bool
    additions: int
    deletions: int
    changed_files: int
    queue_bucket: str
    touched_subsystems: list[str]
    high_risk_paths_touched: list[str]
    validation: list[str]
    checks_summary: str
    risk_flags: list[str]
    machine_recommendation: str
    machine_recommendation_reason: str
    packet_sha: str
    generated_at: str
    check_surfaces: dict[str, Any] = field(default_factory=dict)
    protocol: dict[str, Any] = field(default_factory=dict)
    model_review_quorum: dict[str, Any] = field(default_factory=dict)
    labels: list[str] = field(default_factory=list)
    merge_state_status: str = ""
    advisory_only: bool = True
    settlement_note: str = ADVISORY_NOTE

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SettlementReceipt:
    """Persisted human settlement receipt for one PR/head/packet tuple.

    The five ``outcome_*`` fields are optional post-settlement signals that
    correspond exactly to the canonical invalidation labels in
    :data:`aragora.review.invalidation.INVALIDATION_SIGNALS`. They default to
    ``None`` (= "signal not yet observed") to preserve backward compatibility
    with receipts written before #6375 phase 4. When ``observe_outcome`` (in
    :mod:`aragora.review.settlement_outcome`) populates these, downstream
    consumers like :mod:`aragora.review.invalidation_event_source` can finally
    classify the human side of the baseline (closing the
    ``schema_gap_human_numerator`` note that #6898 surfaces).

    Semantics:
      - All five ``None`` → receipt is denominator-only (counted in
        ``total_human_settled`` but not in invalidation numerator).
      - Any one ``True`` → receipt is invalidated, all firing signals
        contribute to the numerator.
      - All five ``False`` → receipt is a clean human-settled non-invalidation
        (still denominator, explicitly not numerator).

    ``outcome_observed_at`` is the ISO 8601 UTC timestamp at which the
    observation was recorded (separate from ``reviewed_at`` which is the
    settlement time). ``None`` iff none of the five outcome fields have been
    observed yet.
    """

    session_id: str
    reviewed_at: str
    actor: str
    action: str
    reason: str
    pr_number: int
    pr_url: str
    head_sha: str
    base_sha: str
    packet_sha: str
    queue_bucket: str
    machine_recommendation: str
    github_event: str
    elapsed_seconds: float | None = None
    receipt_path: str = ""
    # Post-settlement outcome signals (#6375 phase 4). None == not yet observed.
    outcome_revert_within_window: bool | None = None
    outcome_post_merge_incident: bool | None = None
    outcome_human_override_redo: bool | None = None
    outcome_rollback: bool | None = None
    outcome_reopened_pr: bool | None = None
    outcome_observed_at: str | None = None
    post_merge_lane_audit: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if payload.get("post_merge_lane_audit") is None:
            payload.pop("post_merge_lane_audit", None)
        return payload


@dataclass(slots=True)
class RecordedSettlementResult:
    """Command-facing wrapper for local-only settlement receipt records."""

    receipt: SettlementReceipt
    receipt_sha256: str
    idempotent: bool
    written: bool
    post_merge_lane_audit: dict[str, Any] | None = None
    post_merge_lane_audit_failed: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = self.receipt.to_dict()
        if self.post_merge_lane_audit is not None:
            payload["post_merge_lane_audit"] = self.post_merge_lane_audit
            payload["post_merge_lane_audit_failed"] = self.post_merge_lane_audit_failed
        payload.update(
            {
                "receipt_sha256": self.receipt_sha256,
                "idempotent": self.idempotent,
                "written": self.written,
            }
        )
        return payload


# --- Parser registration ---------------------------------------------------


def add_review_queue_parser(subparsers: argparse._SubParsersAction) -> None:
    """Register review-queue build/packet/run/act sub-actions."""
    parser = subparsers.add_parser(
        "review-queue",
        help="PR review queue + advisory packets + human settlement",
        description=(
            "Build a prioritized queue of open PRs ready for human review, or\n"
            "generate an advisory packet for one PR, or settle one PR with an\n"
            "explicit human action.\n\n"
            "Machine review remains advisory only. Settlement writes are human\n"
            "GitHub reviews/comments plus local founder-review receipts. See\n"
            "docs/plans/2026-04-19-batched-pr-review-triage.md for the design."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="review_queue_command")

    build_p = sub.add_parser("build", help="Build prioritized review queue from open PRs")
    build_p.add_argument("--limit", type=int, default=100, help="Max PRs to fetch (default: 100)")
    build_p.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    build_p.add_argument(
        "--ready-only",
        action="store_true",
        help="Show only ready_now lane",
    )
    build_p.add_argument(
        "--include-parked",
        action="store_true",
        help="Include parked lane (off by default)",
    )
    build_p.add_argument("--json", action="store_true", help="Output as JSON")

    packet_p = sub.add_parser("packet", help="Generate advisory review packet for one PR")
    packet_p.add_argument("pr", help="PR number")
    packet_p.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    packet_p.add_argument(
        "--execute-reviewers",
        action="store_true",
        help=(
            "Attempt one bounded live heterogeneous reviewer pass before falling back to "
            "the metadata-derived packet."
        ),
    )
    packet_p.add_argument("--json", action="store_true", help="Output as JSON")

    run_p = sub.add_parser("run", help="Interactively settle a prioritized PR queue")
    run_p.add_argument("--limit", type=int, default=30, help="Max PRs to walk (default: 30)")
    run_p.add_argument(
        "--ready-only",
        action="store_true",
        help="Restrict the session to ready_now items",
    )
    run_p.add_argument(
        "--include-parked",
        action="store_true",
        help="Include parked items in the session",
    )
    run_p.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )

    act_p = sub.add_parser("act", help="Settle one PR with a human action")
    act_p.add_argument("pr", help="PR number")
    act_p.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    act_group = act_p.add_mutually_exclusive_group(required=True)
    act_group.add_argument("--approve", action="store_true", help="Post a human APPROVE review")
    act_group.add_argument(
        "--request-changes",
        action="store_true",
        help="Post a human REQUEST_CHANGES review",
    )
    act_group.add_argument("--defer", action="store_true", help="Leave a human defer comment")
    act_p.add_argument(
        "--reason",
        default="",
        help="One-line human reason (required for --request-changes and --defer)",
    )
    act_p.add_argument("--json", action="store_true", help="Output settlement receipt as JSON")

    add_record_settlement_parser(sub)

    merge_packet_p = sub.add_parser(
        "merge-packet",
        help="Print a model-quorum merge authorization packet for a PR batch",
        description=(
            "Build a receipt-shaped batch packet for the Model Review Quorum + "
            "Human Risk Settlement process. This is read-only: it does not "
            "approve, merge, comment, or write local receipts."
        ),
    )
    merge_packet_p.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Max open PRs to inspect when --pr is not supplied (default: 30)",
    )
    merge_packet_p.add_argument(
        "--pr",
        action="append",
        default=[],
        help="Specific PR number/ref to include. Repeatable. Defaults to open queue.",
    )
    merge_packet_p.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    merge_packet_p.add_argument(
        "--review-queue-root",
        default=None,
        help=(
            "Override the review-queue store root used for settlement receipt lookups. "
            "Defaults to <repo>/.aragora/review-queue."
        ),
    )
    merge_packet_p.add_argument(
        "--execute-reviewers",
        action="store_true",
        help="Attempt live heterogeneous reviewer execution for each packet.",
    )
    merge_packet_p.add_argument(
        "--ignore-own-quorum-check",
        action="store_true",
        help=(
            "Diagnostic only: exclude the aragora-merge-quorum check (any state) from "
            "the packet's check gating so out-of-CI callers can observe the real "
            "model-quorum state instead of short-circuiting on a stale self-failure. "
            "The enforcing CI gate never sets this; it does not weaken the gate."
        ),
    )
    merge_packet_p.add_argument("--json", action="store_true", help="Output as JSON")

    conductor_p = sub.add_parser(
        "conductor",
        help="Build an owner-aware queue conductor packet and next prompt",
        description=(
            "Read-only queue conductor that combines open PR metadata, required checks, "
            "branch owner lookup, operator steering, merge-packet status, head-change "
            "detection, and supersession hints into one JSON packet plus one next prompt."
        ),
    )
    conductor_p.add_argument(
        "--limit",
        type=int,
        default=30,
        help="Max open PRs to inspect when --pr is not supplied (default: 30)",
    )
    conductor_p.add_argument(
        "--pr",
        action="append",
        default=[],
        help="Specific PR number/ref to include. Repeatable. Defaults to open queue.",
    )
    conductor_p.add_argument(
        "--repo",
        default=None,
        help="GitHub repo slug override (owner/name). Defaults to current repo context.",
    )
    conductor_p.add_argument(
        "--review-queue-root",
        default=None,
        help="Override the review-queue store root used for settlement receipt lookups.",
    )
    conductor_p.add_argument(
        "--owner-timeout-seconds",
        type=float,
        default=8.0,
        help="Timeout for owner and steering helper lookup. Timeout means preserve/no-mutate.",
    )
    conductor_p.add_argument(
        "--mode",
        choices=("queue", "ready-boundary"),
        default="queue",
        help=(
            "Conductor routing mode. ready-boundary emits mark-ready authorization "
            "classification for draft PRs that are otherwise ready."
        ),
    )
    conductor_p.add_argument("--json", action="store_true", help="Output as JSON")

    evidence_lint_p = sub.add_parser(
        "evidence-lint",
        help="Dry-run whether a proposed evidence comment will count for model quorum",
        description=(
            "Lint a proposed PR comment against the same current-head evidence "
            "parsers used by review-queue merge-packet. This is read-only: it "
            "does not fetch GitHub, post comments, write receipts, or mutate state."
        ),
    )
    evidence_lint_p.add_argument("--pr", required=True, help="PR number the evidence targets")
    evidence_lint_p.add_argument(
        "--head-sha",
        required=True,
        help="Exact PR head SHA the proposed comment must cite.",
    )
    evidence_lint_p.add_argument(
        "--head-committed-at",
        default="",
        help=(
            "Optional current head committedDate. When supplied, comments must either "
            "cite --head-sha or have a createdAt at/after this timestamp."
        ),
    )
    body_group = evidence_lint_p.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--body", help="Proposed evidence comment body to lint")
    body_group.add_argument("--body-file", help="Read proposed evidence comment body from file")
    evidence_lint_p.add_argument(
        "--author",
        default="local",
        help="GitHub author login to simulate for the proposed comment (default: local)",
    )
    evidence_lint_p.add_argument("--json", action="store_true", help="Output as JSON")

    collect_evidence_p = sub.add_parser(
        "collect-evidence",
        help="Run genuine model reviewers, lint their evidence, post only if tier allows",
        description=(
            "Run >=2 genuine heterogeneous model reviewers against a PR's exact head, "
            "compose evidence comments the quorum parsers recognize, and validate each "
            "with evidence-lint before posting. Only Tier 0-2 PRs auto-post (with "
            "--apply); Tier 3-4 always prepare evidence for operator settlement. "
            "Defaults to a dry run that posts nothing."
        ),
    )
    collect_evidence_arg = collect_evidence_p.add_argument
    collect_evidence_arg("--pr", required=True, type=int, help="PR number to collect evidence for")
    collect_evidence_arg("--repo", default="", help="owner/name target repo (default: gh context)")
    collect_evidence_arg(
        "--reviewers",
        nargs="+",
        default=None,
        help="reviewer model families to run (default: claude grok)",
    )
    collect_evidence_arg(
        "--author", default=None, help="GitHub login for evidence-lint (default: gh user)"
    )
    collect_evidence_arg(
        "--apply", action="store_true", help="Post Tier 0-2 evidence; Tier 3-4 prepare only."
    )
    collect_evidence_arg(
        "--reviewer-timeout",
        dest="reviewer_timeout",
        type=float,
        default=None,
        help="Per-reviewer timeout in seconds for this invocation.",
    )
    collect_evidence_arg(
        "--overall-timeout",
        dest="overall_timeout",
        type=float,
        default=None,
        help="Overall reviewer orchestration timeout in seconds for this invocation.",
    )
    collect_evidence_arg("--json", dest="json_output", action="store_true", help="Output as JSON")

    lint_comment_p = sub.add_parser(
        "lint-comment",
        help="Dry-run whether a proposed reviewer comment will count before posting",
        description=(
            "Lint a proposed PR reviewer comment against the same current-head evidence "
            "parsers used by review-queue merge-packet. This is read-only: it does not "
            "fetch GitHub, post comments, write receipts, or mutate state."
        ),
    )
    lint_comment_p.add_argument("--pr", required=True, help="PR number the comment targets")
    lint_comment_p.add_argument(
        "--head",
        "--head-sha",
        dest="head_sha",
        required=True,
        help="Exact PR head SHA the proposed comment must cite.",
    )
    lint_comment_p.add_argument(
        "--head-committed-at",
        default="",
        help=(
            "Optional current head committedDate. When supplied, comments must either "
            "cite --head or have a createdAt at/after this timestamp."
        ),
    )
    lint_body_group = lint_comment_p.add_mutually_exclusive_group(required=True)
    lint_body_group.add_argument("--body", help="Proposed reviewer comment body to lint")
    lint_body_group.add_argument(
        "--body-file", help="Read proposed reviewer comment body from file"
    )
    lint_comment_p.add_argument(
        "--author",
        default="local",
        help="GitHub author login to simulate for the proposed comment (default: local)",
    )
    lint_comment_p.add_argument("--json", action="store_true", help="Output as JSON")

    baseline_p = sub.add_parser(
        "baseline",
        help="Measure empirical invalidation baseline from on-disk stores (#6375)",
        description=(
            "Read the auto-handle calibration store (failure outcomes) and the\n"
            "settlement-receipt tree (denominator for human-settled decisions),\n"
            "compute the empirical invalidation baseline, and propose an auto-\n"
            "handle invalidation threshold.\n\n"
            "Read-only: this command does NOT mutate the calibration store, the\n"
            "receipt tree, or any threshold configuration. It is the operator-\n"
            "facing surface for the empirical-threshold framework that landed\n"
            "in #6602 (phase 1) and #6615 (phase 2 adapter)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    baseline_p.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_BASELINE_WINDOW_DAYS,
        help=(f"Measurement-window width in days (default: {DEFAULT_BASELINE_WINDOW_DAYS})."),
    )
    baseline_p.add_argument(
        "--min-samples",
        type=int,
        default=DEFAULT_MIN_BASELINE_SAMPLES,
        help=(
            "Minimum human-settled sample size before the baseline is "
            f"considered usable for non-placeholder threshold derivation "
            f"(default: {DEFAULT_MIN_BASELINE_SAMPLES})."
        ),
    )
    baseline_p.add_argument(
        "--safety-margin",
        type=float,
        default=DEFAULT_SAFETY_MARGIN,
        help=(
            "Multiplier applied to the baseline when deriving the threshold "
            f"(default: {DEFAULT_SAFETY_MARGIN}). Must be in (0, 1]."
        ),
    )
    baseline_p.add_argument(
        "--minimum-meaningful-rate",
        type=float,
        default=DEFAULT_MINIMUM_MEANINGFUL_RATE,
        help=(
            "Floor below which threshold drift is indistinguishable from "
            f"sample noise (default: {DEFAULT_MINIMUM_MEANINGFUL_RATE})."
        ),
    )
    baseline_p.add_argument(
        "--placeholder-value",
        type=float,
        default=0.05,
        help=(
            "Threshold to use when the baseline is below the sample-size "
            "floor (default: 0.05, matching the THESIS Commitment 3 placeholder)."
        ),
    )
    baseline_p.add_argument(
        "--calibration-db",
        default=None,
        help=(
            "Override the auto-handle calibration store path. Defaults to "
            "the canonical store under aragora's data dir."
        ),
    )
    baseline_p.add_argument(
        "--review-queue-root",
        default=None,
        help=(
            "Override the review-queue store root used for settlement "
            "receipts. Defaults to <repo>/.aragora/review-queue."
        ),
    )
    baseline_p.add_argument(
        "--json",
        action="store_true",
        help="Output the BaselineMeasurement + ThresholdProposal as JSON.",
    )

    add_observe_outcomes_parser(sub)

    health_p = sub.add_parser(
        "health",
        help="Report freshness across review-queue + proof-loop write surfaces",
        description=(
            "Read-only, network-free check of the write-side daemons that close the "
            "proof loop: settlement receipts, briefs, boss-metrics ledger, automation "
            "receipts, boss-loop log, watchdog log, B0 publication, and TW-03 rescue "
            "ledger. Exits 1 if any surface is stale or missing. Designed to surface "
            "silent failures within seconds, not 13 days."
        ),
    )
    health_p.add_argument(
        "--repo-root",
        default=None,
        help="Override repo root used for status doc + overnight lookups.",
    )
    health_p.add_argument(
        "--review-queue-root",
        default=None,
        help="Override the review-queue store root.",
    )
    health_p.add_argument(
        "--overnight-root",
        default=None,
        help="Override the .aragora/overnight directory.",
    )
    health_p.add_argument(
        "--automation-receipts-root",
        default=None,
        help="Override the .aragora/automation-receipts directory.",
    )
    health_p.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output the report as JSON.",
    )

    alert_p = sub.add_parser(
        "health-alert",
        help="Edge-triggered alerter: writes an event when proof-loop health changes state",
        description=(
            "Runs the same checks as 'review-queue health', persists state under "
            ".aragora/proof-loop-alerts/, and writes one JSON event per state "
            "transition. Exits 1 if any surface is currently stale or missing."
        ),
    )
    alert_p.add_argument(
        "--repo-root",
        default=None,
        help="Override repo root used for status doc + overnight + state lookups.",
    )
    alert_p.add_argument(
        "--review-queue-root",
        default=None,
        help="Override the review-queue store root.",
    )
    alert_p.add_argument(
        "--overnight-root",
        default=None,
        help="Override the .aragora/overnight directory.",
    )
    alert_p.add_argument(
        "--automation-receipts-root",
        default=None,
        help="Override the .aragora/automation-receipts directory.",
    )
    alert_p.add_argument(
        "--state-dir",
        default=None,
        help="Override the alert state directory (default: <repo>/.aragora/proof-loop-alerts).",
    )
    alert_p.add_argument(
        "--heartbeat",
        action="store_true",
        help="Emit a heartbeat event even when state is unchanged.",
    )
    alert_p.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output the result as JSON.",
    )

    parser.set_defaults(func=cmd_review_queue)


def cmd_review_queue(args: argparse.Namespace) -> int:
    """Dispatch review-queue subcommands."""
    command = getattr(args, "review_queue_command", None)
    if command == "build":
        return _cmd_build(args)
    if command == "packet":
        return _cmd_packet(args)
    if command == "run":
        return _cmd_run(args)
    if command == "act":
        return _cmd_act(args)
    if command == "record-settlement":
        return _cmd_record_settlement(args)
    if command == "conductor":
        return _cmd_conductor(args)
    if command == "merge-packet":
        return _cmd_merge_packet(args)
    if command in {"evidence-lint", "lint-comment"}:
        return _cmd_evidence_lint(args)
    if command == "collect-evidence":
        return _cmd_collect_evidence(args)
    if command == "baseline":
        return _cmd_baseline(args)
    if command == "observe-outcomes":
        from aragora.cli.commands.observe_outcomes_cmd import cmd_observe_outcomes

        return cmd_observe_outcomes(args)
    if command == "health":
        return _cmd_health(args)
    if command == "health-alert":
        return _cmd_health_alert(args)
    print(
        "Usage: aragora review-queue "
        "{build,packet,run,act,record-settlement,conductor,merge-packet,evidence-lint,"
        "lint-comment,"
        "collect-evidence,"
        "baseline,"
        "observe-outcomes,"
        "health,health-alert} [...]\n"
        "Run 'aragora review-queue run --help' for the human settlement loop.",
        file=sys.stderr,
    )
    return 2


# --- Subcommand entry points -----------------------------------------------


def _cmd_build(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False) or getattr(args, "json_output", False))
    try:
        items = _build_queue(limit=args.limit, repo_override=getattr(args, "repo", None))
    except _GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    items = _filter_lanes(
        items,
        ready_only=bool(getattr(args, "ready_only", False)),
        include_parked=bool(getattr(args, "include_parked", False)),
    )
    if json_output:
        print(json.dumps([item.to_dict() for item in items], indent=2))
    else:
        _render_table(items)
    return 0


def _cmd_packet(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False) or getattr(args, "json_output", False))
    try:
        packet = _build_packet(
            args.pr,
            repo_override=args.repo,
            execute_reviewers=bool(getattr(args, "execute_reviewers", False)),
        )
    except _GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if json_output:
        print(json.dumps(packet.to_dict(), indent=2))
    else:
        _render_packet(packet)
    return 0


def _cmd_conductor(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False) or getattr(args, "json_output", False))
    try:
        from aragora.cli.commands.review_queue_conductor import (
            build_queue_conductor_packet,
            render_queue_conductor_packet,
        )

        packet = build_queue_conductor_packet(
            pr_refs=list(getattr(args, "pr", []) or []),
            limit=int(getattr(args, "limit", 30)),
            repo_override=getattr(args, "repo", None),
            review_queue_root=getattr(args, "review_queue_root", None),
            owner_timeout_seconds=float(getattr(args, "owner_timeout_seconds", 8.0)),
            mode=getattr(args, "mode", "queue"),
        )
    except _GhError as exc:
        if json_output and _is_github_transport_error(exc):
            packet = _queue_conductor_transport_blocked_envelope(
                error=str(exc),
                pr_refs=list(getattr(args, "pr", []) or []),
                repo_override=getattr(args, "repo", None),
                limit=int(getattr(args, "limit", 30)),
                mode=str(getattr(args, "mode", "queue") or "queue"),
            )
            print(json.dumps(packet, indent=2, sort_keys=True))
            return 1
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if json_output:
        print(json.dumps(packet, indent=2, sort_keys=True))
    else:
        print(render_queue_conductor_packet(packet))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    repo_root = resolve_repo_root(Path.cwd())
    try:
        _require_clean_worktree(repo_root)
        items = _build_queue(limit=args.limit, repo_override=getattr(args, "repo", None))
    except _GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    items = _filter_lanes(
        items,
        ready_only=bool(getattr(args, "ready_only", False)),
        include_parked=bool(getattr(args, "include_parked", False)),
    )
    if not items:
        print("(no PRs in scope)")
        return 0
    session_id = _session_id()
    started_at = datetime.now(UTC).isoformat()
    session_receipt: dict[str, Any] = {
        "session_id": session_id,
        "started_at": started_at,
        "completed_at": None,
        "reviewed_prs": [],
        "queue_size": len(items),
        "ready_only": bool(getattr(args, "ready_only", False)),
        "include_parked": bool(getattr(args, "include_parked", False)),
    }
    session_path = _session_receipt_path(repo_root, session_id)
    _write_json(session_path, session_receipt)
    for index, item in enumerate(items, start=1):
        try:
            packet = _build_packet(str(item.number), repo_override=getattr(args, "repo", None))
        except _GhError as exc:
            print(f"\n! skipped PR #{item.number}: {exc}", file=sys.stderr)
            continue
        _render_session_packet(packet, item=item, index=index, total=len(items))
        decision_started = time.monotonic()
        while True:
            choice = input(
                "[a]pprove [r]equest-changes [d]efer [o]pen-files [p]acket-json [q]uit: "
            )
            normalized = choice.strip().lower()
            if normalized == "o":
                _render_changed_files(packet.pr_number, repo_override=getattr(args, "repo", None))
                continue
            if normalized == "p":
                print(json.dumps(packet.to_dict(), indent=2))
                continue
            if normalized == "q":
                session_receipt["completed_at"] = datetime.now(UTC).isoformat()
                _write_json(session_path, session_receipt)
                print(f"Session saved: {session_path}")
                return 0
            if normalized not in {"a", "r", "d"}:
                print("Choose one of: a, r, d, o, p, q")
                continue
            action = {
                "a": "approve",
                "r": "request_changes",
                "d": "defer",
            }[normalized]
            reason = ""
            if action == "approve":
                reason = input("approve note (optional): ").strip()
            else:
                while not reason:
                    prompt = "reason (required): "
                    reason = input(prompt).strip()
            try:
                receipt = _settle_packet(
                    packet=packet,
                    action=action,
                    reason=reason,
                    repo_root=repo_root,
                    repo_override=getattr(args, "repo", None),
                    session_id=session_id,
                    elapsed_seconds=round(time.monotonic() - decision_started, 3),
                )
            except _GhError as exc:
                print(f"! could not settle PR #{packet.pr_number}: {exc}", file=sys.stderr)
                continue
            session_receipt["reviewed_prs"].append(receipt.to_dict())
            _write_json(session_path, session_receipt)
            print(
                f"{action} recorded for PR #{packet.pr_number} "
                f"(packet {packet.packet_sha}, head {packet.head_sha})"
            )
            break
    session_receipt["completed_at"] = datetime.now(UTC).isoformat()
    _write_json(session_path, session_receipt)
    print(f"Session complete: {session_path}")
    return 0


def _cmd_act(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False) or getattr(args, "json_output", False))
    action = _requested_action(args)
    reason = str(getattr(args, "reason", "") or "").strip()
    if action == "request_changes" and not reason:
        print(f"error: {REQUEST_CHANGES_REASON_REQUIRED}", file=sys.stderr)
        return 2
    if action == "defer" and not reason:
        print(f"error: {DEFER_REASON_REQUIRED}", file=sys.stderr)
        return 2
    repo_root = resolve_repo_root(Path.cwd())
    try:
        _require_clean_worktree(repo_root)
        packet = _build_packet(args.pr, repo_override=getattr(args, "repo", None))
        receipt = _settle_packet(
            packet=packet,
            action=action,
            reason=reason,
            repo_root=repo_root,
            repo_override=getattr(args, "repo", None),
            session_id=_session_id(),
        )
    except _GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if json_output:
        print(json.dumps(receipt.to_dict(), indent=2))
    else:
        _render_settlement_receipt(receipt)
    return 0


def _cmd_record_settlement(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False) or getattr(args, "json_output", False))
    action = str(getattr(args, "action", "") or "").strip()
    reason = str(getattr(args, "reason", "") or "").strip()
    head_sha = str(getattr(args, "head_sha", "") or "").strip()
    if not reason:
        print("error: --reason is required", file=sys.stderr)
        return 2
    if not head_sha:
        print("error: --head-sha is required", file=sys.stderr)
        return 2
    repo_root = resolve_repo_root(Path.cwd())
    try:
        _require_clean_worktree(repo_root)
        result = _record_external_settlement(
            pr_ref=str(getattr(args, "pr")),
            head_sha=head_sha,
            action=action,
            reason=reason,
            repo_root=repo_root,
            repo_override=getattr(args, "repo", None),
            review_queue_root=getattr(args, "review_queue_root", None),
            apply_post_merge_lane_audit=bool(getattr(args, "apply_post_merge_lane_audit", False)),
        )
    except _GhError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    # Atomic settlement signal: the receipt is now durably written. Only here do
    # we publish the gate-trusted 'aragora/human-settlement' commit status, so a
    # green status can never exist without its backing receipt. (Running
    # 'gh api ... statuses' as a separate command decoupled the two and could set
    # the status even when the receipt write crashed/failed.) A failure posting
    # the status leaves a receipt with no status — the safe direction: the
    # operator simply retries, and the merge gate stays closed until it lands.
    github_status: dict[str, Any] | None = None
    status_failed = False
    if getattr(args, "post_github_status", False):
        try:
            repo_slug = _resolve_settlement_repo_slug(getattr(args, "repo", None))
            status_target_url = _trusted_recorded_settlement_comment_url(
                pr_number=result.receipt.pr_number,
                repo_slug=repo_slug,
                repo_override=getattr(args, "repo", None),
                head_sha=head_sha,
                gh_json=_gh_json,
            )
            github_status = _post_human_settlement_status(
                repo_slug=repo_slug,
                head_sha=head_sha,
                context=str(
                    getattr(args, "github_status_context", "") or "aragora/human-settlement"
                ),
                pr_ref=str(getattr(args, "pr")),
                receipt_sha256=result.receipt_sha256,
                target_url=status_target_url,
            )
        except _GhError as exc:
            status_failed = True
            github_status = {"posted": False, "error": str(exc)}
    if json_output:
        payload = result.to_dict()
        if github_status is not None:
            payload["github_status"] = github_status
        print(json.dumps(payload, indent=2))
    else:
        _render_recorded_settlement_result(result)
        if github_status is not None and not status_failed:
            print(
                f"  github-status: {github_status.get('context')}="
                f"{github_status.get('state')} @ {head_sha[:12]}"
            )
    if status_failed:
        print(
            "error: receipt written but GitHub status POST failed "
            f"({github_status.get('error') if github_status else 'unknown'}); "
            "re-run record-settlement --post-github-status to retry.",
            file=sys.stderr,
        )
        return 1
    return 1 if result.post_merge_lane_audit_failed else 0


def _cmd_evidence_lint(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False) or getattr(args, "json_output", False))
    body_file = getattr(args, "body_file", None)
    try:
        if body_file:
            body = Path(str(body_file)).read_text(encoding="utf-8")
        else:
            body = str(getattr(args, "body", "") or "")
    except OSError as exc:
        if json_output:
            print(
                json.dumps(
                    {
                        "mode": "evidence_lint",
                        "would_count": False,
                        "problems": [f"body_file_unreadable: {exc}"],
                    },
                    indent=2,
                )
            )
        else:
            print(f"error: could not read --body-file: {exc}", file=sys.stderr)
        return 1
    result = _lint_evidence_comment(
        pr=str(getattr(args, "pr", "") or ""),
        head_sha=str(getattr(args, "head_sha", "") or ""),
        head_committed_at=str(getattr(args, "head_committed_at", "") or ""),
        body=body,
        author=str(getattr(args, "author", "") or ""),
        source="body_file" if body_file else "inline",
    )
    if json_output:
        print(json.dumps(result, indent=2))
    else:
        _render_evidence_lint(result)
    return 0 if result["would_count"] else 1


def _resolve_repo_slug(explicit: str) -> str:
    """Return owner/name from --repo or the current gh repo context."""
    explicit = (explicit or "").strip()
    if explicit:
        return explicit
    from aragora.swarm import merge_quorum_io

    try:
        proc = merge_quorum_io.run(
            ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"],
            env=merge_quorum_io.aragora_env(),
            timeout=30,
        )
    except Exception:
        return ""
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def _repo_slug_from_git_remote() -> str:
    """Best-effort owner/name from ``origin`` without using GitHub APIs."""
    try:
        proc = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_STATUS_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    url = (proc.stdout or "").strip()
    if not url:
        return ""
    if url.startswith("git@github.com:"):
        slug = url.removeprefix("git@github.com:").removesuffix(".git").strip("/")
        return slug if "/" in slug else ""
    parsed = urlparse(url)
    if parsed.netloc.lower() == "github.com":
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1].removesuffix('.git')}"
    return ""


def _resolve_repo_slug_for_rest_fallback(repo_override: str | None) -> str:
    """Resolve owner/name for REST fallback when GraphQL-backed ``gh`` is degraded."""
    return _resolve_repo_slug(str(repo_override or "")) or _repo_slug_from_git_remote()


def _cmd_collect_evidence(args: argparse.Namespace) -> int:
    from aragora.swarm.quorum_evidence import run_collect_cli

    json_output = bool(getattr(args, "json", False) or getattr(args, "json_output", False))
    repo = _resolve_repo_slug(str(getattr(args, "repo", "") or ""))
    if not repo:
        print("error: could not resolve --repo (no gh repo context)", file=sys.stderr)
        return 2
    try:
        pr = int(str(getattr(args, "pr", "") or ""))
    except (TypeError, ValueError):
        print("error: --pr must be an integer", file=sys.stderr)
        return 2
    return run_collect_cli(
        repo=repo,
        pr=pr,
        families=getattr(args, "reviewers", None),
        author=getattr(args, "author", None),
        apply=bool(getattr(args, "apply", False)),
        json_output=json_output,
        reviewer_timeout_seconds=getattr(args, "reviewer_timeout", None),
        overall_timeout_seconds=getattr(args, "overall_timeout", None),
    )


def _cmd_merge_packet(args: argparse.Namespace) -> int:
    json_output = bool(getattr(args, "json", False) or getattr(args, "json_output", False))
    try:
        packet = _build_merge_authorization_packet(
            pr_refs=list(getattr(args, "pr", []) or []),
            limit=int(getattr(args, "limit", 30) or 30),
            repo_override=getattr(args, "repo", None),
            review_queue_root=getattr(args, "review_queue_root", None),
            execute_reviewers=bool(getattr(args, "execute_reviewers", False)),
            ignore_own_quorum_check=bool(getattr(args, "ignore_own_quorum_check", False)),
        )
    except _GhError as exc:
        if json_output and _is_github_transport_error(exc):
            packet = _merge_packet_transport_blocked_envelope_with_rest_fallback(
                error=str(exc),
                pr_refs=list(getattr(args, "pr", []) or []),
                repo_override=getattr(args, "repo", None),
                limit=int(getattr(args, "limit", 30) or 30),
                gh_json=_gh_json,
            )
            print(json.dumps(packet, indent=2, sort_keys=True))
            return 1
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if json_output:
        print(json.dumps(packet, indent=2))
    else:
        _render_merge_authorization_packet(packet)
    return 0


def _cmd_baseline(args: argparse.Namespace) -> int:
    """Measure the empirical invalidation baseline + propose a threshold.

    Read-only against the calibration store and the settlement-receipt
    tree. Does not mutate either; does not write a receipt; does not
    apply the proposed threshold anywhere. The recalibration receipt
    flow is #6375 step B (codex).
    """
    if args.window_days <= 0:
        print("error: --window-days must be positive", file=sys.stderr)
        return 2
    if args.min_samples <= 0:
        print("error: --min-samples must be positive", file=sys.stderr)
        return 2
    if not 0 < args.safety_margin <= 1:
        print("error: --safety-margin must be in (0, 1]", file=sys.stderr)
        return 2
    if args.minimum_meaningful_rate <= 0:
        print("error: --minimum-meaningful-rate must be positive", file=sys.stderr)
        return 2
    if not 0 < args.placeholder_value < 1:
        print("error: --placeholder-value must be in (0, 1)", file=sys.stderr)
        return 2

    json_output = bool(getattr(args, "json", False))

    from aragora.review.invalidation import derive_threshold
    from aragora.review.invalidation_event_source import measure_baseline_from_stores
    from aragora.triage.auto_handle_calibration import AutoHandleCalibrationStore

    try:
        store = AutoHandleCalibrationStore(db_path=args.calibration_db)
    except (OSError, RuntimeError, sqlite3.Error, ValueError, TypeError) as exc:
        print(f"error: cannot open calibration store: {exc}", file=sys.stderr)
        return 1

    window_end = datetime.now(UTC)
    try:
        measurement = measure_baseline_from_stores(
            calibration_store=store,
            review_queue_root=args.review_queue_root,
            window_end=window_end,
            window_days=args.window_days,
            min_samples=args.min_samples,
        )
    except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
        print(f"error: baseline measurement failed: {exc}", file=sys.stderr)
        return 1

    proposal = derive_threshold(
        measurement,
        safety_margin=args.safety_margin,
        minimum_meaningful_rate=args.minimum_meaningful_rate,
        measured_at=window_end,
        placeholder_value=args.placeholder_value,
    )

    if json_output:
        print(
            json.dumps(
                {
                    "measurement": measurement.to_dict(),
                    "proposal": proposal.to_dict(),
                },
                indent=2,
            )
        )
    else:
        _render_baseline_report(measurement=measurement, proposal=proposal)
    return 0


def _cmd_health(args: argparse.Namespace) -> int:
    """Report freshness across review-queue + proof-loop write surfaces.

    Read-only, network-free. Answers "is the proof loop quietly broken?"
    in one command. Closes the observability gap that hid the May 6
    boss-loop httpx regression for 13 days.
    """
    from aragora.review.health import gather_health, render_text

    repo_root = getattr(args, "repo_root", None)
    review_queue_root = getattr(args, "review_queue_root", None)
    overnight_root = getattr(args, "overnight_root", None)
    automation_root = getattr(args, "automation_receipts_root", None)

    report = gather_health(
        repo_root=Path(repo_root) if repo_root else None,
        review_queue_root=Path(review_queue_root) if review_queue_root else None,
        overnight_root=Path(overnight_root) if overnight_root else None,
        automation_receipts_root=Path(automation_root) if automation_root else None,
    )

    json_output = bool(getattr(args, "json_output", False) or getattr(args, "json", False))
    if json_output:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(render_text(report))

    if report.overall_status in {"empty", "stale", "missing"}:
        return 1
    return 0


def _cmd_health_alert(args: argparse.Namespace) -> int:
    """Edge-triggered alerter for proof-loop write surfaces.

    Runs the same checks as ``review-queue health``, persists state under
    ``.aragora/proof-loop-alerts/``, and writes one JSON event whenever the
    set of stale/missing surfaces changes (opens, set-change, recovers).
    Designed for periodic launchd execution: repeated calls while a surface
    is steady-state stale do NOT produce duplicate events.

    Exits 1 if any surface is currently stale or missing (so launchd can
    surface failures via its own log retention).
    """
    from aragora.review.alert import resolve_state_dir, run_alert
    from aragora.review.health import _resolve_repo_root

    repo_root_arg = getattr(args, "repo_root", None)
    review_queue_root = getattr(args, "review_queue_root", None)
    overnight_root = getattr(args, "overnight_root", None)
    automation_root = getattr(args, "automation_receipts_root", None)
    state_dir_arg = getattr(args, "state_dir", None)
    emit_heartbeat = bool(getattr(args, "heartbeat", False))

    repo_root_path = Path(repo_root_arg) if repo_root_arg else None
    effective_repo = _resolve_repo_root(repo_root_path)
    state_dir = Path(state_dir_arg) if state_dir_arg else resolve_state_dir(effective_repo)

    result = run_alert(
        state_dir=state_dir,
        emit_heartbeat=emit_heartbeat,
        repo_root=repo_root_path,
        review_queue_root=Path(review_queue_root) if review_queue_root else None,
        overnight_root=Path(overnight_root) if overnight_root else None,
        automation_receipts_root=Path(automation_root) if automation_root else None,
    )

    json_output = bool(getattr(args, "json_output", False) or getattr(args, "json", False))
    if json_output:
        payload = {
            "overall_status": result.report.overall_status,
            "alerting_surfaces": result.state.alerting_surfaces,
            "event_kind": result.event.kind if result.event is not None else None,
            "event_path": str(result.event_path) if result.event_path is not None else None,
            "state_path": str(result.state_path),
            "last_run_at": (
                result.state.last_run_at.isoformat()
                if result.state.last_run_at is not None
                else None
            ),
            "last_event_at": (
                result.state.last_event_at.isoformat()
                if result.state.last_event_at is not None
                else None
            ),
        }
        print(json.dumps(payload, indent=2))
    else:
        kind = result.event.kind if result.event is not None else "no-change"
        print(f"proof-loop alert: kind={kind} overall={result.report.overall_status}")
        if result.state.alerting_surfaces:
            print(f"  alerting:  {', '.join(result.state.alerting_surfaces)}")
        else:
            print("  alerting:  (none)")
        print(f"  state:     {result.state_path}")
        if result.event_path is not None:
            print(f"  event:     {result.event_path}")

    # Exit gate must be driven by the actual set of alerting surfaces, not by
    # ``report.overall_status``. Surface statuses are ranked
    # ``fresh < aging < stale < empty < missing`` (see ``health.py``), and only
    # ``stale``/``missing`` are alerting (see ``alert.ALERTING_STATUSES``).
    # ``overall_status`` is the *max severity rank* across surfaces, so a mix
    # like ``[empty, stale]`` produces ``overall_status == "empty"`` even
    # though a stale surface is firing. Gating on ``state.alerting_surfaces``
    # captures the actual alert condition directly.
    if result.state.alerting_surfaces:
        return 1
    return 0


# --- Internals: gh shell, classification, packet building ------------------


def _resolve_settlement_repo_slug(repo_override: str | None) -> str:
    """Return ``owner/name``, preferring an explicit override then ``gh`` context."""
    slug = str(repo_override or "").strip()
    if slug:
        return slug
    data = _gh_json(["repo", "view", "--json", "nameWithOwner"])
    if isinstance(data, dict):
        slug = str(data.get("nameWithOwner", "") or "").strip()
    if not slug:
        raise _GhError("could not resolve repo slug; pass --repo owner/name")
    return slug


def _post_human_settlement_status(
    *,
    repo_slug: str,
    head_sha: str,
    context: str,
    pr_ref: str,
    receipt_sha256: str,
    target_url: str,
) -> dict[str, Any]:
    """POST the head-bound human-settlement status, citing receipt and comment.

    Only called after the local receipt is durably written, so the status is
    always backed by a receipt. The receipt sha is embedded in the status
    description for an auditable status->receipt link. ``target_url`` binds the
    status to the trusted exact-head Tier 4 settlement comment that quorum later
    verifies.
    """
    target_url = str(target_url or "").strip()
    if not target_url:
        raise _GhError("human-settlement status requires a trusted settlement comment target_url")
    pr_digits = "".join(ch for ch in str(pr_ref) if ch.isdigit()) or str(pr_ref)
    description = (f"Settlement receipt {receipt_sha256} recorded for PR #{pr_digits}")[:140]
    resp = _gh_json(
        [
            "api",
            "--method",
            "POST",
            f"repos/{repo_slug}/statuses/{head_sha}",
            "-f",
            "state=success",
            "-f",
            f"context={context}",
            "-f",
            f"description={description}",
            "-f",
            f"target_url={target_url}",
        ]
    )
    state = ""
    posted_context = context
    if isinstance(resp, dict):
        state = str(resp.get("state", "") or "")
        posted_context = str(resp.get("context", context) or context)
    return {
        "posted": True,
        "context": posted_context,
        "state": state,
        "head_sha": head_sha,
        "receipt_sha256": receipt_sha256,
        "target_url": target_url,
    }


def _build_queue(*, limit: int, repo_override: str | None = None) -> list[QueueItem]:
    fields = ",".join(
        [
            "number",
            "title",
            "url",
            "headRefName",
            "headRefOid",
            "isDraft",
            "mergeable",
            "reviewDecision",
            "labels",
            "author",
            "additions",
            "deletions",
            "changedFiles",
            "statusCheckRollup",
        ]
    )
    args = [
        "pr",
        "list",
        "--state",
        "open",
        "--limit",
        str(limit),
        "--json",
        fields,
    ]
    if repo_override:
        args.extend(["--repo", repo_override])
    raw = _gh_json(args)
    items: list[QueueItem] = []
    for pr in raw or []:
        if not isinstance(pr, dict):
            continue
        items.append(_classify_pr(pr))
    items.sort(key=lambda it: (LANE_ORDER.get(it.lane, 99), -it.number))
    return items


def _classify_pr(pr: dict[str, Any]) -> QueueItem:
    """Assign one PR to a lane based on draft/checks/diff/labels signals."""
    number = int(pr.get("number", 0) or 0)
    title = str(pr.get("title", "")).strip()
    url = str(pr.get("url", "")).strip()
    head_sha = str(pr.get("headRefOid", "")).strip()
    is_draft = bool(pr.get("isDraft", False))
    mergeable = str(pr.get("mergeable", "")).strip().upper()
    review_decision = str(pr.get("reviewDecision", "")).strip().upper()
    labels = [
        str(lab.get("name", "")).strip()
        for lab in (pr.get("labels") or [])
        if isinstance(lab, dict) and lab.get("name")
    ]
    author = ""
    author_payload = pr.get("author")
    if isinstance(author_payload, dict):
        author = str(author_payload.get("login", "")).strip()
    additions = int(pr.get("additions", 0) or 0)
    deletions = int(pr.get("deletions", 0) or 0)
    changed_files = int(pr.get("changedFiles", 0) or 0)
    checks_unavailable = _check_rollup_unavailable(pr)
    checks_summary, has_failures, has_pending = _summarize_checks(pr.get("statusCheckRollup") or [])
    if checks_unavailable:
        checks_summary = "no checks reported"
        has_pending = True

    parked_label_hits = [lab for lab in labels if lab in PARKED_LABELS]

    if is_draft:
        lane, reason = "parked", "draft PR"
    elif parked_label_hits:
        lane, reason = "parked", f"label={','.join(parked_label_hits)}"
    elif mergeable == "CONFLICTING":
        lane, reason = "parked", "merge conflict"
    elif has_failures:
        lane, reason = "repairable", checks_summary
    elif checks_unavailable:
        lane, reason = "needs_attention", checks_summary
    elif has_pending:
        lane, reason = "needs_attention", f"checks pending ({checks_summary})"
    elif additions + deletions > LARGE_DIFF_THRESHOLD:
        lane, reason = "needs_attention", f"large diff (+{additions}/-{deletions})"
    elif mergeable in ("MERGEABLE", "UNKNOWN", ""):
        lane, reason = "ready_now", checks_summary or "all green"
    else:
        lane, reason = "needs_attention", f"mergeable={mergeable}"

    return QueueItem(
        number=number,
        title=title,
        url=url,
        head_sha=head_sha,
        author=author,
        is_draft=is_draft,
        mergeable=mergeable,
        review_decision=review_decision,
        labels=labels,
        additions=additions,
        deletions=deletions,
        changed_files=changed_files,
        checks_summary=checks_summary,
        lane=lane,
        lane_reason=reason,
    )


def _summarize_checks(checks: list, *, ignore_quorum_check: bool = False) -> tuple[str, bool, bool]:
    """Return ``(summary, has_failures, has_pending)`` for a statusCheckRollup.

    ``ignore_quorum_check`` is a diagnostic-only switch (never set by the
    enforcing CI path) that additionally excludes the ``aragora-merge-quorum``
    check in any state (pending or concluded), so out-of-CI callers can observe
    the real non-self check state instead of short-circuiting on a stale
    self-failure. See B2 in docs/governance/BOSS_LOOP_MERGE_GATE_RESILIENCE.md.
    """
    success = failure = pending = 0
    for check in _latest_status_check_rollup(checks):
        if not isinstance(check, dict):
            continue
        if _is_current_merge_quorum_self_check(check) or (
            ignore_quorum_check and _is_merge_quorum_check(check)
        ):
            continue
        status = str(check.get("status") or check.get("state") or "").upper()
        conclusion = str(check.get("conclusion") or "").upper()
        # Status-context rollups use ``state`` without a separate conclusion.
        # Normalize those terminal states into the same summary buckets.
        if not conclusion and status in {
            "SUCCESS",
            "FAILURE",
            "TIMED_OUT",
            "ACTION_REQUIRED",
            "CANCELLED",
            "SKIPPED",
            "NEUTRAL",
            "STALE",
        }:
            conclusion = status
        elif not conclusion and status in {"ERROR", "FAILED"}:
            conclusion = "FAILURE"
        if conclusion == "SUCCESS":
            success += 1
        elif conclusion == "CANCELLED" and _is_merge_quorum_check(check):
            failure += 1
        elif conclusion in ("FAILURE", "TIMED_OUT", "ACTION_REQUIRED"):
            failure += 1
        elif conclusion in ("CANCELLED", "SKIPPED", "NEUTRAL", "STALE"):
            # Treat skipped/cancelled as not-meaningful for the summary; they
            # are correct gating behavior in this repo (see docs/CI_LANES.md).
            continue
        elif status in ("IN_PROGRESS", "QUEUED", "PENDING", "EXPECTED") or not conclusion:
            pending += 1
    total = success + failure + pending
    if failure > 0:
        return (f"{failure} failing / {total} total", True, pending > 0)
    if pending > 0:
        return (f"{pending} pending / {total} total", False, True)
    if success > 0:
        return (f"{success}/{total} green", False, False)
    return ("no checks", False, False)


def _fetch_required_pr_check_surface(pr_number: int, repo_override: str | None) -> dict[str, Any]:
    """Fetch GitHub's branch-protection-required PR checks with diagnostics."""
    args = [
        "pr",
        "checks",
        str(pr_number),
        "--required",
        "--json",
        "name,state,bucket,workflow,link,startedAt,completedAt",
    ]
    if repo_override:
        args.extend(["--repo", repo_override])
    try:
        payload = _gh_json(args)
    except _GhError as exc:
        return {
            "available": False,
            "checks": [],
            "error": str(exc),
            "error_kind": _gh_error_kind(exc),
            "transport_blocked": _is_github_transport_error(exc),
            "preserve_no_mutate": _is_github_transport_error(exc),
        }
    if not isinstance(payload, list):
        return {
            "available": False,
            "checks": [],
            "error": "gh pr checks --required returned a non-list payload",
        }
    return {
        "available": True,
        "checks": [item for item in payload if isinstance(item, dict)],
        "error": "",
    }


def _fetch_required_pr_checks(pr_number: int, repo_override: str | None) -> list[dict[str, Any]]:
    """Fetch GitHub's branch-protection-required PR checks."""
    surface = _fetch_required_pr_check_surface(pr_number, repo_override)
    return [item for item in surface.get("checks") or [] if isinstance(item, dict)]


def _required_pr_check_bucket(check: dict[str, Any]) -> str:
    bucket = str(check.get("bucket") or "").strip().lower()
    if bucket:
        return bucket
    state = str(check.get("state") or "").strip().upper()
    if state in {"SUCCESS", "SUCCESSFUL", "COMPLETED"}:
        return "pass"
    if state in {"SKIPPED", "NEUTRAL"}:
        return "skipping"
    if state in {"FAILURE", "FAILED", "ERROR", "TIMED_OUT", "ACTION_REQUIRED"}:
        return "fail"
    if state in {"CANCELLED", "CANCELED"}:
        return "cancel"
    if state in {"PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", ""}:
        return "pending"
    return state.lower()


def _summarize_required_pr_checks(
    checks: list[dict[str, Any]], *, ignore_quorum_check: bool = False
) -> tuple[str, bool, bool]:
    """Return ``(summary, has_failures, has_pending)`` for required PR checks."""
    success = failure = pending = 0
    for check in checks:
        if _is_required_pr_check_current_merge_quorum_self_check(check) or (
            ignore_quorum_check and _is_merge_quorum_check(check)
        ):
            continue
        bucket = _required_pr_check_bucket(check)
        if bucket in {"pass", "skipping"}:
            success += 1
        elif bucket in {"fail", "cancel"}:
            failure += 1
        elif bucket == "pending":
            pending += 1
        else:
            pending += 1
    total = success + failure + pending
    if failure > 0:
        return (f"{failure} failing / {total} required", True, pending > 0)
    if pending > 0:
        return (f"{pending} pending / {total} required", False, True)
    if success > 0:
        return (f"{success}/{total} required green", False, False)
    return ("no required checks", False, False)


def _effective_required_pr_check_count(
    checks: list[dict[str, Any]], *, ignore_quorum_check: bool = False
) -> int:
    """Count required PR checks after excluding the current merge-quorum self-check."""
    return sum(
        1
        for check in checks
        if isinstance(check, dict)
        and not _is_required_pr_check_current_merge_quorum_self_check(check)
        and not (ignore_quorum_check and _is_merge_quorum_check(check))
    )


def _effective_required_pr_checks(
    checks: list[dict[str, Any]], *, ignore_quorum_check: bool = False
) -> list[dict[str, Any]]:
    """Return required PR checks after excluding current/self quorum rows."""
    return [
        check
        for check in checks
        if isinstance(check, dict)
        and not _is_required_pr_check_current_merge_quorum_self_check(check)
        and not (ignore_quorum_check and _is_merge_quorum_check(check))
    ]


def _status_check_display_name(check: dict[str, Any]) -> str:
    workflow = str(check.get("workflowName") or check.get("workflow") or "").strip()
    name = str(check.get("name") or check.get("context") or "").strip()
    if workflow and name:
        return f"{workflow} / {name}"
    return name or workflow


def _parse_github_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _queued_duration_seconds(check: dict[str, Any]) -> int:
    for key in ("queued_duration_seconds", "queuedDurationSeconds"):
        value = check.get(key)
        if value is None:
            continue
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            continue

    for key in (
        "queuedAt",
        "queued_at",
        "createdAt",
        "created_at",
        "startedAt",
        "started_at",
        "updatedAt",
        "updated_at",
    ):
        queued_at = _parse_github_datetime(check.get(key))
        if queued_at:
            return max(0, int((datetime.now(UTC) - queued_at).total_seconds()))
    return 0


def _self_hosted_shadow_check(check: dict[str, Any]) -> bool:
    workflow = str(check.get("workflowName") or check.get("workflow") or "").lower()
    name = str(check.get("name") or check.get("context") or "").lower()
    labels = {str(label).lower() for label in check.get("labels") or []}
    if "self-hosted shadow" in workflow:
        return True
    return "shadow" in name and ("self-hosted" in workflow or "self-hosted" in labels)


def _has_runner_metadata(check: dict[str, Any]) -> bool:
    return any(key in check for key in ("runner_id", "runnerId", "runner_name", "runnerName"))


def _runner_unassigned(check: dict[str, Any]) -> bool:
    if not _has_runner_metadata(check):
        return False
    for key in ("runner_id", "runnerId"):
        if key not in check:
            continue
        value = check.get(key)
        if value is not None and str(value).strip() not in {"", "0"}:
            return False
    for key in ("runner_name", "runnerName"):
        if key not in check:
            continue
        if str(check.get(key) or "").strip():
            return False
    return True


def _is_optional_runner_capacity_noise(check: dict[str, Any], bucket: str) -> bool:
    return (
        bucket == "pending"
        and _self_hosted_shadow_check(check)
        and _runner_unassigned(check)
        and _queued_duration_seconds(check) >= OPTIONAL_RUNNER_CAPACITY_NOISE_MIN_SECONDS
    )


def _is_long_queued_self_hosted_shadow_without_runner_metadata(
    check: dict[str, Any],
    bucket: str,
) -> bool:
    return (
        bucket == "pending"
        and _self_hosted_shadow_check(check)
        and not _has_runner_metadata(check)
        and _queued_duration_seconds(check) >= OPTIONAL_RUNNER_CAPACITY_NOISE_MIN_SECONDS
    )


def _rollup_non_green_bucket(check: dict[str, Any]) -> str:
    if _is_current_merge_quorum_self_check(check):
        return ""
    status = str(check.get("status") or check.get("state") or "").upper()
    conclusion = str(check.get("conclusion") or "").upper()
    if not conclusion and status in {
        "SUCCESS",
        "FAILURE",
        "TIMED_OUT",
        "ACTION_REQUIRED",
        "CANCELLED",
        "SKIPPED",
        "NEUTRAL",
        "STALE",
    }:
        conclusion = status
    elif not conclusion and status in {"ERROR", "FAILED"}:
        conclusion = "FAILURE"
    if conclusion in {"SUCCESS", "SKIPPED", "NEUTRAL", "STALE"}:
        return ""
    if conclusion == "CANCELLED" and not _is_merge_quorum_check(check):
        return ""
    if conclusion in {"FAILURE", "TIMED_OUT", "ACTION_REQUIRED", "CANCELLED"}:
        return "failing_or_cancelled"
    if status in {"IN_PROGRESS", "QUEUED", "PENDING", "EXPECTED"} or not conclusion:
        return "pending"
    return "pending"


def _rollup_check_matches_required(
    check: dict[str, Any],
    required_checks: list[dict[str, Any]],
) -> bool:
    identity = _status_check_identity(check)
    name = str(check.get("name") or check.get("context") or "").strip()
    required_identities = {
        _status_check_identity(required)
        for required in required_checks
        if isinstance(required, dict) and _status_check_identity(required)
    }
    required_names = {
        str(required.get("name") or required.get("context") or "").strip()
        for required in required_checks
        if isinstance(required, dict)
    }
    return bool((identity and identity in required_identities) or (name and name in required_names))


def _rollup_non_green_diagnostics(
    checks: list,
    *,
    required_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    non_green: list[str] = []
    non_required_non_green: list[str] = []
    optional_runner_capacity_noise: list[str] = []
    long_queued_shadow_without_runner_metadata: list[str] = []
    pending = failing_or_cancelled = 0
    for check in _latest_status_check_rollup(checks):
        if not isinstance(check, dict):
            continue
        bucket = _rollup_non_green_bucket(check)
        if not bucket:
            continue
        name = _status_check_display_name(check)
        if not name:
            continue
        non_green.append(name)
        if bucket == "pending":
            pending += 1
        else:
            failing_or_cancelled += 1
        is_non_required = required_checks is not None and not _rollup_check_matches_required(
            check, required_checks
        )
        if is_non_required:
            non_required_non_green.append(name)
            if _is_optional_runner_capacity_noise(check, bucket):
                optional_runner_capacity_noise.append(name)
            if _is_long_queued_self_hosted_shadow_without_runner_metadata(check, bucket):
                long_queued_shadow_without_runner_metadata.append(name)
    diagnostics: dict[str, Any] = {
        "non_green_count": len(non_green),
        "non_green_sample": non_green[:CHECK_SURFACE_DIAGNOSTIC_LIMIT],
        "pending_count": pending,
        "failing_or_cancelled_count": failing_or_cancelled,
    }
    if required_checks is not None:
        diagnostics["non_required_non_green_count"] = len(non_required_non_green)
        diagnostics["non_required_non_green_sample"] = non_required_non_green[
            :CHECK_SURFACE_DIAGNOSTIC_LIMIT
        ]
        diagnostics["optional_runner_capacity_noise_count"] = len(optional_runner_capacity_noise)
        diagnostics["optional_runner_capacity_noise_sample"] = optional_runner_capacity_noise[
            :CHECK_SURFACE_DIAGNOSTIC_LIMIT
        ]
        diagnostics["long_queued_self_hosted_shadow_without_runner_metadata_count"] = len(
            long_queued_shadow_without_runner_metadata
        )
        diagnostics["long_queued_self_hosted_shadow_without_runner_metadata_sample"] = (
            long_queued_shadow_without_runner_metadata[:CHECK_SURFACE_DIAGNOSTIC_LIMIT]
        )
    return diagnostics


def _check_rollup_unavailable(pr: dict[str, Any]) -> bool:
    """Return true when an open PR has no GitHub PR-facing check rollup."""
    pr_state = str(pr.get("state") or "").strip().upper()
    if pr_state and pr_state != "OPEN":
        return False
    if pr.get("mergedAt"):
        return False
    rollup = pr.get("statusCheckRollup")
    return rollup is None or rollup == []


def _build_check_surface_diagnostics(
    pr: dict[str, Any],
    *,
    repo_override: str | None,
    checks_summary: str,
    checks_unavailable: bool,
) -> dict[str, Any]:
    """Explain PR-facing check rollup separately from direct commit check-runs.

    Direct commit check-runs are a fail-closed fallback only when branch
    protection required contexts are known and all are successful at the exact
    PR head.
    """
    rollup = pr.get("statusCheckRollup")
    rollup_count = len(rollup) if isinstance(rollup, list) else None
    rollup_diagnostics = (
        _rollup_non_green_diagnostics(rollup)
        if isinstance(rollup, list) and not checks_unavailable
        else {}
    )
    diagnostics: dict[str, Any] = {
        "pr_rollup": {
            "available": not checks_unavailable,
            "count": rollup_count,
            "summary": checks_summary,
            **rollup_diagnostics,
        }
    }
    if not checks_unavailable:
        return diagnostics

    head_sha = str(pr.get("headRefOid") or "").strip()
    repo_slug = rest_fallback._repo_slug_from_pr_payload(pr, repo_override)
    base_ref = str(pr.get("baseRefName") or "").strip()
    required_status_checks = rest_fallback._fetch_required_status_check_protection(
        repo_slug,
        base_ref,
        gh_json=_gh_json,
    )
    required_contexts = required_status_checks["contexts"]
    required_check_specs = required_status_checks.get("checks") or []
    strict_required = bool(required_status_checks["strict"])
    direct_runs = rest_fallback._fetch_direct_commit_check_runs(
        repo_slug, head_sha, gh_json=_gh_json
    )
    direct_statuses = pr.get("commitStatuses") if isinstance(pr.get("commitStatuses"), list) else []
    if not direct_statuses:
        direct_statuses = rest_fallback._fetch_direct_commit_statuses(
            repo_slug,
            head_sha,
            gh_json=_gh_json,
        )
    latest_direct_runs = rest_fallback._latest_direct_check_runs_by_name(direct_runs)
    non_green = [
        name
        for name, run in latest_direct_runs.items()
        if rest_fallback._direct_check_run_is_non_green(run)
    ]
    latest_direct_statuses = rest_fallback._latest_direct_statuses_by_context(direct_statuses)
    non_green_statuses = [
        context
        for context, status in latest_direct_statuses.items()
        if rest_fallback._direct_status_is_non_green(status)
    ]
    missing_required_contexts: list[str] = []
    successful_required_contexts: list[str] = []
    non_success_required_contexts: list[str] = []
    for required in required_check_specs:
        context = str(required.get("context") or "").strip()
        if not context:
            continue
        run = rest_fallback._latest_direct_check_run_for_required(direct_runs, required)
        status = (
            None
            if run is not None
            else rest_fallback._latest_direct_status_for_required(direct_statuses, required)
        )
        if run is None:
            if status is None:
                missing_required_contexts.append(context)
            elif rest_fallback._direct_status_is_success(status):
                successful_required_contexts.append(context)
            else:
                non_success_required_contexts.append(context)
        elif rest_fallback._direct_check_run_is_success(run):
            successful_required_contexts.append(context)
        else:
            non_success_required_contexts.append(context)
    required_contexts_satisfied = (
        bool(required_contexts)
        and not strict_required
        and not (missing_required_contexts or non_success_required_contexts)
    )
    direct_summary = {
        "available": bool(direct_runs or direct_statuses),
        "statuses_available": bool(direct_statuses),
        "total": len(direct_runs),
        "statuses_total": len(direct_statuses),
        "branch_protection_required_status_checks_available": bool(
            required_status_checks["available"]
        ),
        "branch_protection_strict": strict_required,
        "required_contexts": required_contexts,
        "required_checks": required_check_specs,
        "successful_required_contexts": successful_required_contexts,
        "missing_required_contexts": missing_required_contexts,
        "non_success_required_contexts": non_success_required_contexts,
        "required_contexts_satisfied": required_contexts_satisfied,
        "non_green_sample": [*non_green, *non_green_statuses][:CHECK_SURFACE_DIAGNOSTIC_LIMIT],
        "non_green_count": len(non_green) + len(non_green_statuses),
    }
    diagnostics["direct_commit_check_runs"] = direct_summary
    if required_contexts_satisfied:
        diagnostics["diagnosis"] = (
            "GitHub PR statusCheckRollup is empty, but exact-head direct commit "
            "check-runs show every branch-protection required context successful; "
            "merge-packet uses the direct required check-run fallback."
        )
        diagnostics["remediation_prompt"] = (
            "No check-rollup nudge is required for settlement; continue gating on "
            "exact-head branch-protection required check-runs."
        )
    elif direct_runs or direct_statuses:
        if strict_required:
            diagnostics["diagnosis"] = (
                "GitHub PR statusCheckRollup is empty while exact-head direct commit "
                "check-runs/statuses exist, but branch protection requires strict base freshness; "
                "merge-packet fails closed because direct commit checks alone do "
                "not prove the PR is up to date with base."
            )
            diagnostics["remediation_prompt"] = (
                "Refresh the PR-facing check rollup after the branch is current with "
                "base, or keep the PR blocked. Do not settle from direct commit "
                "checks alone when branch protection is strict."
            )
        else:
            diagnostics["diagnosis"] = (
                "GitHub PR statusCheckRollup is empty while direct commit check-runs "
                "or statuses exist at the head; merge-packet fails closed because direct checks "
                "do not satisfy all branch-protection required contexts."
            )
            diagnostics["remediation_prompt"] = (
                "Authorize only a PR-state/check-only nudge to refresh GitHub's PR "
                "check rollup, or keep the PR blocked and open a bounded CI/tooling "
                "repair lane. Do not merge from direct commit check-runs alone."
            )
    else:
        diagnostics["diagnosis"] = (
            "GitHub PR statusCheckRollup is empty and no direct commit check-runs were found."
        )
        diagnostics["remediation_prompt"] = (
            "Wait for checks or authorize a minimal check-only action; do not "
            "settle or merge while the PR-facing rollup is unavailable."
        )
    return diagnostics


def _direct_required_check_fallback_satisfied(check_surfaces: dict[str, Any]) -> bool:
    direct = check_surfaces.get("direct_commit_check_runs")
    if not isinstance(direct, dict):
        return False
    return bool(direct.get("required_contexts_satisfied"))


def _latest_status_check_rollup(checks: list) -> list[dict[str, Any]]:
    """Collapse superseded check-rollup entries to their latest identity.

    GitHub's PR ``statusCheckRollup`` can retain older Actions check runs for
    the same workflow/job at the current head.  Merge-packet should gate on the
    latest visible state for a check identity, matching ``gh pr checks``.
    """
    latest: dict[str, tuple[str, int, dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            continue
        key = _status_check_identity(check)
        if not key:
            passthrough.append(check)
            continue
        timestamp = str(
            check.get("completedAt")
            or check.get("startedAt")
            or check.get("createdAt")
            or check.get("updatedAt")
            or ""
        )
        previous = latest.get(key)
        if previous is None or (timestamp, index) >= (previous[0], previous[1]):
            latest[key] = (timestamp, index, check)
    ordered = sorted(latest.values(), key=lambda item: item[1])
    return passthrough + [item[2] for item in ordered]


def _status_check_identity(check: dict[str, Any]) -> str:
    workflow = str(check.get("workflowName") or check.get("workflow") or "").strip()
    name = str(check.get("name") or check.get("context") or "").strip()
    if not name:
        return ""
    if workflow:
        return f"check-run:{workflow}:{name}"
    return f"status-context:{name}"


def _is_merge_quorum_check(check: dict[str, Any]) -> bool:
    workflow = str(check.get("workflowName") or check.get("workflow") or "").strip()
    name = str(check.get("name") or check.get("context") or "").strip()
    return workflow == MERGE_QUORUM_WORKFLOW_NAME and name == MERGE_QUORUM_CHECK_NAME


def _is_current_merge_quorum_self_check(check: dict[str, Any]) -> bool:
    """Ignore only this merge-quorum workflow run while building its packet."""
    if not _is_merge_quorum_check(check):
        return False

    status = str(check.get("status") or check.get("state") or "").upper()
    conclusion = str(check.get("conclusion") or "").upper()
    if conclusion or status not in {"IN_PROGRESS", "QUEUED", "PENDING", "EXPECTED"}:
        return False

    if os.environ.get("GITHUB_WORKFLOW") != MERGE_QUORUM_WORKFLOW_NAME:
        return False
    if os.environ.get("GITHUB_JOB") != MERGE_QUORUM_JOB_ID:
        return False

    run_id = str(os.environ.get("GITHUB_RUN_ID") or "").strip()
    repo = str(os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if not run_id or not repo:
        return False

    server_url = str(os.environ.get("GITHUB_SERVER_URL") or "https://github.com")
    details_url = str(check.get("detailsUrl") or check.get("link") or "").strip()
    parsed_server = urlparse(server_url)
    parsed_details = urlparse(details_url)
    expected_path_prefix = f"/{repo}/actions/runs/{run_id}/"
    return (
        parsed_details.scheme in {"http", "https"}
        and bool(parsed_server.netloc)
        and parsed_details.netloc == parsed_server.netloc
        and parsed_details.path.startswith(expected_path_prefix)
    )


def _is_required_pr_check_current_merge_quorum_self_check(check: dict[str, Any]) -> bool:
    """Return true for the merge-quorum job's own required PR check row.

    ``gh pr checks --required`` can report the previous merge-quorum attempt
    while the new merge-quorum job is computing its packet. For that required
    PR-check fallback only, the workflow must ignore its own row regardless of
    whether GitHub labels the stale row pending, failed, or cancelled. Other
    call sites keep the stricter URL/status match so stale completed
    merge-quorum failures still block local settlement.
    """
    if not _is_merge_quorum_check(check):
        return False
    return (
        os.environ.get("GITHUB_WORKFLOW") == MERGE_QUORUM_WORKFLOW_NAME
        and os.environ.get("GITHUB_JOB") == MERGE_QUORUM_JOB_ID
    )


def _filter_lanes(
    items: list[QueueItem],
    *,
    ready_only: bool,
    include_parked: bool,
) -> list[QueueItem]:
    if ready_only:
        return [it for it in items if it.lane == "ready_now"]
    if not include_parked:
        return [it for it in items if it.lane != "parked"]
    return items


def _build_packet(
    pr_ref: str,
    *,
    repo_override: str | None,
    review_queue_root: str | Path | None = None,
    execute_reviewers: bool = False,
    ignore_own_quorum_check: bool = False,
) -> ReviewPacket:
    number = _parse_pr_number(pr_ref)
    light_fields = [
        "number",
        "title",
        "url",
        "headRefOid",
        "baseRefOid",
        "state",
        "mergedAt",
        "baseRefName",
        "isDraft",
        "mergeable",
        "mergeStateStatus",
        "reviewDecision",
        "labels",
        "author",
        "additions",
        "deletions",
        "changedFiles",
        "files",
        "body",
    ]
    heavy_fields = ["statusCheckRollup", "comments", "reviews", "commits"]
    args = ["pr", "view", str(number), "--json", ",".join(light_fields)]
    if repo_override:
        args.extend(["--repo", repo_override])
    try:
        pr = _gh_json(args)
    except _GhError as exc:
        if not _is_github_transport_error(exc):
            raise
        pr = rest_fallback._hydrate_pr_with_rest_fallback(
            number=number,
            repo_slug=_resolve_repo_slug_for_rest_fallback(repo_override),
            source_error=str(exc),
            gh_json=_gh_json,
        )
    if pr is None or not isinstance(pr, dict):
        raise _GhError(f"PR #{number} not found")
    settlement_state_block = _settlement_state_block_reason(pr)
    if not settlement_state_block and not pr.get("_rest_fallback"):
        args = ["pr", "view", str(number), "--json", ",".join([*light_fields, *heavy_fields])]
        if repo_override:
            args.extend(["--repo", repo_override])
        try:
            pr = _gh_json(args)
        except _GhError as exc:
            if not _is_github_transport_error(exc):
                raise
            pr = rest_fallback._hydrate_pr_with_rest_fallback(
                number=number,
                repo_slug=_resolve_repo_slug_for_rest_fallback(repo_override),
                source_error=str(exc),
                gh_json=_gh_json,
            )
        if pr is None or not isinstance(pr, dict):
            raise _GhError(f"PR #{number} not found")
        settlement_state_block = _settlement_state_block_reason(pr)

    files: list[str] = []
    for item in pr.get("files") or []:
        if isinstance(item, dict):
            path = str(item.get("path", "")).strip()
            if path:
                files.append(path)
    labels = [
        str(lab.get("name", "")).strip()
        for lab in (pr.get("labels") or [])
        if isinstance(lab, dict) and lab.get("name")
    ]
    parked_label_hits = [lab for lab in labels if lab in PARKED_LABELS]
    touched = sorted({_subsystem_for(p) for p in files})
    high_risk = [p for p in files if _is_high_risk_path(p)]
    check_surfaces: dict[str, Any]
    if settlement_state_block:
        checks_unavailable = False
        checks_summary = f"failing PR state ({settlement_state_block})"
        has_failures = False
        has_pending = False
        check_surfaces = {
            "pr_state": {
                "available": True,
                "state": str(pr.get("state") or "").strip().upper(),
                "merged_at": str(pr.get("mergedAt") or "").strip(),
                "summary": settlement_state_block,
                "gate_selected": True,
            }
        }
    else:
        checks_unavailable = _check_rollup_unavailable(pr)
        checks_summary, has_failures, has_pending = _summarize_checks(
            pr.get("statusCheckRollup") or [], ignore_quorum_check=ignore_own_quorum_check
        )
        if checks_unavailable:
            checks_summary = "no checks reported"
            has_pending = True
        check_surfaces = _build_check_surface_diagnostics(
            pr,
            repo_override=repo_override,
            checks_summary=checks_summary,
            checks_unavailable=checks_unavailable,
        )
    rest_fallback_meta = pr.get("_rest_fallback")
    if isinstance(rest_fallback_meta, dict):
        check_surfaces["metadata_transport_fallback"] = rest_fallback_meta
    required_pr_check_gate_satisfied = False
    if not settlement_state_block and not checks_unavailable and (has_failures or has_pending):
        required_surface = _fetch_required_pr_check_surface(number, repo_override)
        required_pr_checks = [
            item for item in required_surface.get("checks") or [] if isinstance(item, dict)
        ]
        required_available = bool(required_surface.get("available"))
        if required_available:
            required_summary, required_has_failures, required_has_pending = (
                _summarize_required_pr_checks(
                    required_pr_checks, ignore_quorum_check=ignore_own_quorum_check
                )
            )
        else:
            required_summary = "required PR checks unavailable"
            required_has_failures = False
            required_has_pending = True
        effective_required_count = _effective_required_pr_check_count(
            required_pr_checks, ignore_quorum_check=ignore_own_quorum_check
        )
        ignored_self_check_count = sum(
            1
            for check in required_pr_checks
            if isinstance(check, dict)
            and _is_required_pr_check_current_merge_quorum_self_check(check)
        )
        ignored_by_flag_count = (
            sum(
                1
                for check in required_pr_checks
                if isinstance(check, dict)
                and _is_merge_quorum_check(check)
                and not _is_required_pr_check_current_merge_quorum_self_check(check)
            )
            if ignore_own_quorum_check
            else 0
        )
        effective_required_checks = _effective_required_pr_checks(
            required_pr_checks, ignore_quorum_check=ignore_own_quorum_check
        )
        required_failing_or_cancelled_checks = [
            check
            for check in effective_required_checks
            if _required_pr_check_bucket(check) in {"fail", "cancel"}
        ]
        required_pending_checks = [
            check
            for check in effective_required_checks
            if _required_pr_check_bucket(check) == "pending"
        ]
        required_quorum_only_failure = (
            required_available
            and effective_required_count > 0
            and bool(required_failing_or_cancelled_checks)
            and not required_pending_checks
            and all(_is_merge_quorum_check(check) for check in required_failing_or_cancelled_checks)
        )
        # Self-check-independent reachability predicate for advisory-dissent
        # settlement (#8739). Unlike ``required_quorum_only_failure`` above, this
        # does NOT require the merge-quorum row to be *visible* as a failing
        # required check. Inside the enforcing Aragora Merge Quorum job the quorum
        # row is the current self-check and is excluded from
        # ``effective_required_checks``, so ``required_failing_or_cancelled_checks``
        # is empty and ``required_quorum_only_failure`` is False even though the
        # quorum signal is exactly what is missing. Externally the same row appears
        # as a distinct failing entry. Both collapse to "no NON-quorum required
        # check is failing/cancelled/pending" — the true condition advisory_settle
        # needs. Computed separately so the in-job path is reachable WITHOUT
        # disturbing the self-check semantics ``quorum_only_failure`` (and its guard
        # tests) rely on. ``all(...)`` over an empty failing set is True (in-job);
        # over a quorum-only failing set is True (external); over any non-quorum
        # failure it is False (correctly keeps a real failing check blocking).
        advisory_settle_surface_clear = (
            required_available
            and effective_required_count > 0
            and not required_pending_checks
            and all(_is_merge_quorum_check(check) for check in required_failing_or_cancelled_checks)
        )
        # _rollup_non_green_diagnostics reports the raw GitHub rollup counts/sample
        # and is intentionally not filtered by ignore_own_quorum_check. The flag's
        # effect on the rollup is limited to the summary text computed above; the
        # gating decision lives in the required_pr_checks surface.
        rollup_required_diagnostics = _rollup_non_green_diagnostics(
            pr.get("statusCheckRollup") or [],
            required_checks=required_pr_checks if required_available else None,
        )
        check_surfaces["pr_rollup"].update(rollup_required_diagnostics)

        gate_blocked_reason = ""
        if not required_available:
            gate_blocked_reason = (
                "GitHub required PR checks surface is unavailable; merge-packet "
                "cannot distinguish required checks from non-required PR rollup checks."
            )
        elif effective_required_count == 0:
            flag_note = (
                " (and the broader aragora-merge-quorum row, --ignore-own-quorum-check set)"
                if ignore_own_quorum_check
                else ""
            )
            gate_blocked_reason = (
                "GitHub reported no effective branch-protection required checks "
                f"after ignoring the current merge-quorum self-check{flag_note}."
            )
        elif required_has_failures:
            gate_blocked_reason = (
                f"branch-protection required checks are failing ({required_summary})."
            )
        elif required_has_pending:
            gate_blocked_reason = (
                f"branch-protection required checks are pending ({required_summary})."
            )
        check_surfaces["required_pr_checks"] = {
            "available": required_available,
            "total": len(required_pr_checks),
            "effective_total": effective_required_count,
            "ignored_current_merge_quorum_self_check_count": ignored_self_check_count,
            "ignored_by_ignore_own_quorum_flag_count": ignored_by_flag_count,
            "summary": required_summary,
            "gate_selected": False,
            "gate_blocked_reason": gate_blocked_reason,
            "failing_or_cancelled": [
                str(check.get("name") or "").strip()
                for check in required_failing_or_cancelled_checks
            ][:CHECK_SURFACE_DIAGNOSTIC_LIMIT],
            "pending": [str(check.get("name") or "").strip() for check in required_pending_checks][
                :CHECK_SURFACE_DIAGNOSTIC_LIMIT
            ],
            "quorum_only_failure": required_quorum_only_failure,
            "advisory_settle_surface_clear": advisory_settle_surface_clear,
        }
        if required_surface.get("error"):
            check_surfaces["required_pr_checks"]["error"] = str(required_surface.get("error"))
        if (
            required_available
            and effective_required_count > 0
            and not required_has_pending
            and has_pending
        ):
            # Required-check gating can separate branch-protection waits from
            # optional full-rollup capacity noise even when a required check
            # still fails and keeps the packet blocked.
            has_pending = False
        if effective_required_count > 0 and not required_has_failures and not required_has_pending:
            required_pr_check_gate_satisfied = True
            check_surfaces["required_pr_checks"]["gate_selected"] = True
            check_surfaces["required_pr_checks"]["gate_blocked_reason"] = ""
            checks_summary = f"{required_summary} (required PR checks)"
            has_pending = False
            has_failures = False
            checks_unavailable = False
            check_surfaces["effective_gate"] = {
                "source": "required_pr_checks",
                "summary": checks_summary,
            }
            check_surfaces["diagnosis"] = (
                "The PR check rollup includes non-required non-green checks, "
                "but GitHub reports every branch-protection required check green; "
                "merge-packet uses the required PR checks gate."
            )
            check_surfaces["remediation_prompt"] = (
                "Continue gating on branch-protection required checks; keep "
                "non-required shadow/advisory check failures visible but non-blocking."
            )
        elif required_quorum_only_failure:
            check_surfaces["required_pr_checks"]["gate_selected"] = True
            check_surfaces["required_pr_checks"]["gate_blocked_reason"] = ""
            checks_summary = f"{required_summary} (required PR checks; only merge-quorum failing)"
            has_pending = False
            checks_unavailable = False
            check_surfaces["effective_gate"] = {
                "source": "required_pr_checks",
                "summary": checks_summary,
            }
            check_surfaces["diagnosis"] = (
                "The PR check rollup includes non-required non-green checks, "
                "and GitHub reports every non-quorum branch-protection required "
                "check green; merge-packet leaves aragora-merge-quorum to the "
                "model quorum evidence gate."
            )
            check_surfaces["remediation_prompt"] = (
                "Collect missing model quorum evidence or rerun aragora-merge-quorum "
                "after evidence is counted; keep non-required rollup failures advisory."
            )
        elif gate_blocked_reason:
            check_surfaces["diagnosis"] = (
                "The PR check rollup is non-green and merge-packet did not select "
                f"the required PR checks gate: {gate_blocked_reason}"
            )
            check_surfaces["remediation_prompt"] = (
                "Keep the PR blocked or authorize a bounded check-surface repair; "
                "do not settle or merge until required checks can be separated from "
                "non-required PR rollup checks."
            )
    direct_check_fallback_satisfied = (
        not settlement_state_block
        and checks_unavailable
        and _direct_required_check_fallback_satisfied(check_surfaces)
    )
    if direct_check_fallback_satisfied:
        direct_summary = check_surfaces["direct_commit_check_runs"]
        successful_required = direct_summary.get("successful_required_contexts") or []
        required_contexts = direct_summary.get("required_contexts") or []
        checks_summary = (
            f"{len(successful_required)}/{len(required_contexts)} required green "
            "(direct check-runs fallback)"
        )
        has_pending = False
        has_failures = False
        checks_unavailable = False
        check_surfaces["effective_gate"] = {
            "source": "direct_commit_check_runs",
            "summary": checks_summary,
        }
    additions = int(pr.get("additions", 0) or 0)
    deletions = int(pr.get("deletions", 0) or 0)
    is_draft = bool(pr.get("isDraft", False))
    pr_state = str(pr.get("state") or "").strip().upper()
    head_sha = str(pr.get("headRefOid", "")).strip()
    settlement_recorded = pr_state == "MERGED" and _has_recorded_admin_squash_settlement(
        pr_number=number,
        head_sha=head_sha,
        review_queue_root=review_queue_root,
    )
    human_risk_settlement_recorded = (
        pr_state == "OPEN"
        and not settlement_state_block
        and _has_recorded_human_risk_settlement(
            pr_number=number,
            head_sha=head_sha,
            review_queue_root=review_queue_root,
        )
    )
    mergeable = str(pr.get("mergeable", "")).strip().upper()
    queue_item = _classify_pr(pr)
    validation = _extract_validation_commands(str(pr.get("body", "") or ""))

    risk_flags: list[str] = []
    if settlement_recorded:
        risk_flags.append("exact-head admin_squash_merge settlement receipt recorded")
    elif human_risk_settlement_recorded:
        risk_flags.append("exact-head human risk settlement receipt recorded")
    elif settlement_state_block:
        risk_flags.append(settlement_state_block)
    if is_draft:
        risk_flags.append("draft PR")
    if parked_label_hits:
        risk_flags.append(f"parked label ({','.join(parked_label_hits)})")
    if high_risk:
        sample = ", ".join(high_risk[:5])
        more = "" if len(high_risk) <= 5 else f" (+{len(high_risk) - 5} more)"
        risk_flags.append(f"touches high-risk paths: {sample}{more}")
    if additions + deletions > LARGE_DIFF_THRESHOLD:
        risk_flags.append(f"large diff (+{additions}/-{deletions})")
    if mergeable == "CONFLICTING":
        risk_flags.append("merge conflict")
    if checks_unavailable:
        risk_flags.append("check rollup unavailable")
    if has_failures:
        risk_flags.append(f"checks failing ({checks_summary})")
    required_pr_check_surface = check_surfaces.get("required_pr_checks") or {}
    if required_pr_check_gate_satisfied and required_pr_check_surface:
        risk_flags.append(
            "non-required PR checks are non-green; "
            "effective gate uses branch-protection required checks"
        )
    direct_summary = check_surfaces.get("direct_commit_check_runs") or {}
    if direct_check_fallback_satisfied and direct_summary.get("non_green_count", 0):
        risk_flags.append(
            "non-required direct check-runs are non-green; "
            "fallback gates only branch-protection required contexts"
        )

    if settlement_recorded:
        recommendation = "settled_noop"
        recommendation_reason = "PR is already merged with an exact-head settlement receipt"
    elif settlement_state_block:
        recommendation = "needs_human_attention"
        recommendation_reason = settlement_state_block
    elif has_failures or mergeable == "CONFLICTING":
        recommendation = "repair_first"
        recommendation_reason = "checks failing or merge conflict — fix before review"
    elif checks_unavailable:
        recommendation = "needs_human_attention"
        recommendation_reason = "check rollup unavailable — wait for GitHub to report checks"
    elif is_draft:
        recommendation = "needs_human_attention"
        recommendation_reason = "draft PR — keep parked until it is ready for review"
    elif parked_label_hits:
        recommendation = "needs_human_attention"
        recommendation_reason = (
            f"parked label present ({','.join(parked_label_hits)}) — keep parked until cleared"
        )
    elif high_risk or additions + deletions > LARGE_DIFF_THRESHOLD:
        recommendation = "needs_human_attention"
        recommendation_reason = "high-risk paths touched or large diff — human should read it"
    elif has_pending:
        recommendation = "needs_human_attention"
        recommendation_reason = "checks still pending — wait for completion"
    else:
        recommendation = "approve_candidate"
        if required_pr_check_gate_satisfied:
            recommendation_reason = (
                "branch-protection required checks green; non-required PR checks are non-green"
            )
        elif direct_check_fallback_satisfied and direct_summary.get("non_green_count", 0):
            recommendation_reason = (
                "branch-protection required contexts green via direct check-run fallback; "
                "non-required direct check-runs are non-green"
            )
        else:
            recommendation_reason = "all green, bounded diff, no high-risk paths"

    author = ""
    author_payload = pr.get("author")
    if isinstance(author_payload, dict):
        author = str(author_payload.get("login", "")).strip()

    repo = _repo_from_url(str(pr.get("url", "")).strip())
    protocol_runner = default_pr_review_protocol()
    reviewer_outputs: list[ReviewerOutput] = []
    execution_failures: list[Any] = []
    if execute_reviewers:
        diff_args = ["pr", "diff", str(number)]
        if repo_override:
            diff_args.extend(["--repo", repo_override])
        reviewer_outputs, execution_failures = protocol_runner.execute_live_reviewers(
            repo=repo,
            pr_number=number,
            title=str(pr.get("title", "")).strip(),
            base_sha=str(pr.get("baseRefOid", "")).strip(),
            head_sha=str(pr.get("headRefOid", "")).strip(),
            checks_summary=checks_summary,
            changed_files=files,
            diff_text=_gh_text(diff_args),
            machine_recommendation=recommendation,
            machine_recommendation_reason=recommendation_reason,
        )
    protocol = protocol_runner.build_packet(
        repo=repo,
        pr_number=number,
        title=str(pr.get("title", "")).strip(),
        base_sha=str(pr.get("baseRefOid", "")).strip(),
        head_sha=str(pr.get("headRefOid", "")).strip(),
        mergeable=mergeable,
        review_decision=str(pr.get("reviewDecision", "")).strip().upper(),
        checks_summary=checks_summary,
        has_failures=has_failures,
        has_pending=has_pending,
        additions=additions,
        deletions=deletions,
        changed_files=int(pr.get("changedFiles", 0) or 0),
        labels=labels,
        high_risk_paths=high_risk,
        validation_commands=validation,
        machine_recommendation=recommendation,
        machine_recommendation_reason=recommendation_reason,
        reviewer_outputs=reviewer_outputs,
        execution_failures=execution_failures,
    )
    protocol_dict = protocol.to_dict()

    packet = ReviewPacket(
        pr_number=number,
        title=str(pr.get("title", "")).strip(),
        url=str(pr.get("url", "")).strip(),
        head_sha=str(pr.get("headRefOid", "")).strip(),
        base_sha=str(pr.get("baseRefOid", "")).strip(),
        author=author,
        is_draft=is_draft,
        additions=additions,
        deletions=deletions,
        changed_files=int(pr.get("changedFiles", 0) or 0),
        queue_bucket=queue_item.lane,
        touched_subsystems=touched,
        high_risk_paths_touched=high_risk,
        validation=validation,
        checks_summary=checks_summary,
        risk_flags=risk_flags,
        machine_recommendation=recommendation,
        machine_recommendation_reason=recommendation_reason,
        packet_sha="",
        generated_at=datetime.now(UTC).isoformat(),
        check_surfaces=check_surfaces,
        protocol=protocol_dict,
        model_review_quorum=_build_model_review_quorum(
            pr=pr,
            files=files,
            protocol=protocol_dict,
            machine_recommendation=recommendation,
            has_pending=has_pending,
            has_failures=has_failures,
            checks_unavailable=checks_unavailable,
            settlement_recorded=settlement_recorded,
            human_risk_settlement_recorded=human_risk_settlement_recorded,
            check_surfaces=check_surfaces,
            repo_slug=rest_fallback._repo_slug_from_pr_payload(pr, repo_override),
        ),
        labels=labels,
        merge_state_status=str(pr.get("mergeStateStatus") or "").strip().upper(),
    )
    packet.packet_sha = _packet_sha(packet)
    return packet


def _admin_squash_live_gate_blockers(packet: ReviewPacket) -> list[str]:
    blockers: list[str] = []
    labels = {str(label).strip().lower() for label in packet.labels if str(label).strip()}
    if OPERATOR_REVIEW_REQUIRED_LABEL in labels:
        blockers.append("operator-review-required label present")

    merge_state_status = str(packet.merge_state_status or "").strip().upper()
    if not merge_state_status:
        blockers.append("mergeStateStatus unavailable; admin squash requires CLEAN or BLOCKED")
    elif merge_state_status not in {"CLEAN", "BLOCKED"}:
        blockers.append(
            f"mergeStateStatus={merge_state_status}; admin squash requires CLEAN or BLOCKED"
        )
    return blockers


def _build_merge_authorization_packet(
    *,
    pr_refs: list[str],
    limit: int,
    repo_override: str | None,
    review_queue_root: str | Path | None = None,
    execute_reviewers: bool = False,
    ignore_own_quorum_check: bool = False,
) -> dict[str, Any]:
    scoped_pr_refs = False
    if pr_refs:
        refs = list(dict.fromkeys(str(ref).strip() for ref in pr_refs if str(ref).strip()))
        queue_size = len(refs)
        scoped_pr_refs = True
    else:
        queue = _build_queue(limit=limit, repo_override=repo_override)
        refs = [str(item.number) for item in queue]
        queue_size = len(queue)

    prebuilt_entries: dict[str, dict[str, Any]] = {}
    refs_to_hydrate = refs
    if scoped_pr_refs:
        refs_to_hydrate = []
        for ref in refs:
            merged_entry = _explicit_merged_pr_merge_packet_entry(ref, repo_override)
            if merged_entry is not None:
                prebuilt_entries[str(merged_entry["pr_number"])] = merged_entry
            else:
                refs_to_hydrate.append(ref)

    packet_kwargs: dict[str, Any] = {
        "repo_override": repo_override,
        "execute_reviewers": execute_reviewers,
        "ignore_own_quorum_check": ignore_own_quorum_check,
    }
    if review_queue_root is not None:
        packet_kwargs["review_queue_root"] = review_queue_root
    packets = [_build_packet(ref, **packet_kwargs) for ref in refs_to_hydrate]
    hydrated_entries_by_pr: dict[str, dict[str, Any]] = {}
    queue_pressure_active = queue_size > MODEL_REVIEW_QUEUE_CAP
    for packet in packets:
        quorum = dict(packet.model_review_quorum)
        admin_squash_gate_blockers = _admin_squash_live_gate_blockers(packet)
        model_quorum_admin_squash_allowed = bool(quorum["admin_squash_allowed"])
        quorum["queue_pressure"] = {
            "current_open_prs": queue_size,
            "cap": MODEL_REVIEW_QUEUE_CAP,
            "active": queue_pressure_active,
            "scope": "explicit_pr_refs" if scoped_pr_refs else "open_pr_queue",
            "allowed_work_when_active": [
                "review",
                "dogfood",
                "existing_blocker_fix",
                "local_spec_only",
                "merge_authorization_packet",
            ],
        }
        entry_status = quorum["status"]
        entry_verdict = quorum["verdict"]
        if model_quorum_admin_squash_allowed and admin_squash_gate_blockers:
            # The live gate flipped admin_squash_allowed to false; the quorum
            # status/verdict ("satisfied"/"admin_squash_allowed") would be
            # misleading in human-readable output (#8965 openai [P3]).
            entry_status = "blocked_by_live_gate"
            entry_verdict = "admin_squash_blocked_by_live_gate"
        entry = {
            "pr_number": packet.pr_number,
            "title": packet.title,
            "url": packet.url,
            "head_sha": packet.head_sha,
            "checks_summary": packet.checks_summary,
            "machine_recommendation": packet.machine_recommendation,
            "tier": quorum["tier"],
            "tier_name": quorum["tier_name"],
            "status": entry_status,
            "verdict": entry_verdict,
            "admin_squash_allowed": (
                model_quorum_admin_squash_allowed and not admin_squash_gate_blockers
            ),
            "model_quorum_admin_squash_allowed": model_quorum_admin_squash_allowed,
            "admin_squash_gate_blockers": admin_squash_gate_blockers,
            "merge_state_status": packet.merge_state_status,
            "operator_review_required": OPERATOR_REVIEW_REQUIRED_LABEL
            in {str(label).strip().lower() for label in packet.labels if str(label).strip()},
            "requires_human_risk_settlement": quorum["requires_human_risk_settlement"],
            "requires_human_preapproval": quorum.get("requires_human_preapproval", False),
            "human_preapproval_recorded": quorum.get("human_preapproval_recorded", False),
            "settlement_creator_pin": quorum.get("settlement_creator_pin", {}),
            "unresolved_dissent": quorum["unresolved_dissent"],
            "reviewer_signals": quorum["reviewer_signals"],
            "dogfood_evidence": quorum["dogfood_evidence"],
            "counted_reviewer_ids": quorum["counted_reviewer_ids"],
            "counted_model_families": quorum.get(
                "counted_model_families", quorum["counted_reviewer_ids"]
            ),
            "reasons": quorum["reasons"],
        }
        if packet.check_surfaces:
            entry["check_surfaces"] = packet.check_surfaces
        hydrated_entries_by_pr[str(packet.pr_number)] = entry

    entries = []
    for ref in refs:
        pr_key = str(_parse_pr_number(ref))
        if pr_key in prebuilt_entries:
            entries.append(prebuilt_entries[pr_key])
        elif pr_key in hydrated_entries_by_pr:
            entries.append(hydrated_entries_by_pr[pr_key])

    return {
        "version": "merge_authorization_packet.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "queue_pressure": {
            "current_open_prs": queue_size,
            "cap": MODEL_REVIEW_QUEUE_CAP,
            "active": queue_pressure_active,
            "scope": "explicit_pr_refs" if scoped_pr_refs else "open_pr_queue",
        },
        "authorization_sentence": (
            "I accept the model quorum evidence for Tier 0-2 PRs in this packet "
            "and authorize admin squash in the listed order. For Tier 3+ PRs, "
            "I separately accept the semantic-risk packet before merge."
        ),
        "entries": entries,
        "admin_squash_order": [
            entry["pr_number"]
            for entry in entries
            if bool(entry["admin_squash_allowed"]) and not bool(entry["unresolved_dissent"])
        ],
        "human_risk_settlement_required": [
            entry["pr_number"] for entry in entries if bool(entry["requires_human_risk_settlement"])
        ],
        "not_ready": [
            entry["pr_number"]
            for entry in entries
            if entry["status"]
            not in {"satisfied", "human_risk_settlement_required", "settled", "already_merged"}
        ],
    }


def _explicit_merged_pr_merge_packet_entry(
    pr_ref: str,
    repo_override: str | None,
) -> dict[str, Any] | None:
    """Return a lightweight no-op entry for explicit merged PR probes.

    Post-merge audit prompts sometimes re-run ``review-queue merge-packet
    --pr`` after the PR has already merged. At that point merge readiness is
    obsolete, so avoid hydrating comments/reviews/commits and return a stable
    no-op entry instead of re-entering model-quorum settlement logic.
    """

    number = _parse_pr_number(pr_ref)
    fields = ",".join(
        [
            "number",
            "title",
            "url",
            "headRefOid",
            "state",
            "mergedAt",
            "mergeCommit",
        ]
    )
    args = ["pr", "view", str(number), "--json", fields]
    if repo_override:
        args.extend(["--repo", repo_override])
    try:
        pr = _gh_json(args)
    except _GhError as exc:
        if not _is_github_transport_error(exc):
            raise
        pr = rest_fallback._hydrate_pr_with_rest_fallback(
            number=number,
            repo_slug=_resolve_repo_slug_for_rest_fallback(repo_override),
            source_error=str(exc),
            gh_json=_gh_json,
        )
    if pr is None or not isinstance(pr, dict):
        raise _GhError(f"PR #{number} not found")
    state = str(pr.get("state") or "").strip().upper()
    merged_at = str(pr.get("mergedAt") or "").strip()
    if state != "MERGED" and not (merged_at and state != "OPEN"):
        return None

    return {
        "pr_number": int(pr.get("number") or number),
        "title": str(pr.get("title") or "").strip(),
        "url": str(pr.get("url") or "").strip(),
        "head_sha": str(pr.get("headRefOid") or "").strip(),
        "checks_summary": "failing PR state (already merged; checks obsolete for merge-packet)",
        "machine_recommendation": "settled_noop",
        "tier": 0,
        "tier_name": "already_merged",
        "status": "already_merged",
        "verdict": "already_merged_noop",
        "admin_squash_allowed": False,
        "requires_human_risk_settlement": False,
        "unresolved_dissent": False,
        "reviewer_signals": [],
        "dogfood_evidence": [],
        "counted_reviewer_ids": [],
        "counted_model_families": [],
        "reasons": [
            "PR is already merged; merge-packet readiness is obsolete",
        ],
    }


def _is_recognized_model_review(body: str) -> bool:
    """Whether a comment body is a recognized model review (identity resolver, not
    a fixed heading-token list, so recognizers cannot drift — #8729 openai [P2])."""
    return _resolve_model_review_identity(body).surface_reviewer_id != "unknown_model_reviewer"


def _advisory_settle_review_signals(
    comments: list[Any],
    *,
    head_sha: str = "",
    head_committed_at: str = "",
) -> tuple[bool, bool, bool]:
    """Single-pass classification of grounded reviews for advisory_settle.

    Returns ``(has_valid_wf_review, has_valid_advisory_dissent, has_blocking_finding)``.

    Source-validation is applied UNIFORMLY so every *positive* input to the gate
    passes the SAME filters the strict quorum path uses — closing the class of
    bypasses #8729's review round surfaced one input at a time (spoofed identity,
    bot author, uncountable advisory CR):

    * positive signals (a western-frontier review present; genuine advisory
      dissent) require a grounded, NON-bot author with a countable, non-conflicted
      identity (``IDENTITY_COUNT_BLOCKERS``);
    * the blocking-finding scan is deliberately PERMISSIVE / fail-closed: a
      ``[P0]``/``[P1]`` in ANY recognized grounded review (bot or not) blocks
      advisory_settle, so a blocking finding can never be laundered by an
      untrusted source.
    """
    has_wf = False
    has_advisory_dissent = False
    has_blocking = False
    for comment in comments or []:
        if not isinstance(comment, dict):
            continue
        if not _is_comment_grounded_on_head(comment, head_sha, head_committed_at):
            continue
        body = str(comment.get("body", "") or "")
        if not _is_recognized_model_review(body):
            continue
        # Permissive, fail-closed blocking scan (any recognized grounded review).
        if _has_blocking_finding_or_label(body):
            has_blocking = True
        # Positive signals require a validated source (non-bot + countable identity).
        author_payload = comment.get("author")
        author = (
            str(author_payload.get("login", "") or "") if isinstance(author_payload, dict) else ""
        )
        if _is_github_actions_author(author):
            continue
        identity = _resolve_model_review_identity(body)
        if any(problem in IDENTITY_COUNT_BLOCKERS for problem in identity.identity_problems):
            continue
        if str(identity.model_family or "").strip().lower() in WESTERN_FRONTIER_FAMILIES:
            has_wf = True
        # Genuine advisory dissent: a CHANGES-REQUESTED verdict from a validated
        # source with no blocking [P0]/[P1] finding.
        if _has_blocking_or_negative_verdict(body) and not _has_blocking_finding_or_label(body):
            has_advisory_dissent = True
    return has_wf, has_advisory_dissent, has_blocking


def _build_model_review_quorum(
    *,
    pr: dict[str, Any],
    files: list[str],
    protocol: dict[str, Any],
    machine_recommendation: str,
    has_pending: bool,
    has_failures: bool,
    checks_unavailable: bool = False,
    settlement_recorded: bool = False,
    human_risk_settlement_recorded: bool = False,
    check_surfaces: dict[str, Any] | None = None,
    repo_slug: str = "",
) -> dict[str, Any]:
    tier, tier_name, tier_reason = _classify_model_review_tier(files, pr=pr)
    requirement = _tier_requirement(tier)
    head_sha = str(pr.get("headRefOid", "") or "").strip()
    head_committed_at = _head_committed_at_from_pr(pr)
    reviewer_signals = _reviewer_signals_from_protocol(protocol)
    reviewer_signals.extend(
        _model_review_signals_from_comments(
            pr.get("comments") or [],
            head_sha=head_sha,
            head_committed_at=head_committed_at,
        )
    )
    dogfood_evidence = _dogfood_evidence_from_comments(
        pr.get("comments") or [],
        head_sha=head_sha,
        head_committed_at=head_committed_at,
    )
    advisory_views: list[dict[str, Any]] = []
    comment_dissenting_views = _dissenting_views_from_comments(
        pr.get("comments") or [],
        head_sha=head_sha,
        head_committed_at=head_committed_at,
        advisory_views=advisory_views,
    )
    # Bound advisory_views symmetrically with the dissent list (which returns [:5]),
    # so a PR with many recognized comments cannot flood the merge packet's
    # advisory_views field or its `reasons` notes (claude #8574 P3).
    del advisory_views[5:]
    dissenting_views = [
        view for view in (protocol.get("dissenting_views") or []) if isinstance(view, dict)
    ]
    dissenting_views.extend(comment_dissenting_views)
    blocking_workflow_reasons = _blocking_workflow_state_reasons(pr)
    blocking_workflow_state = bool(blocking_workflow_reasons)
    unresolved_dissent = bool(dissenting_views)
    counted_reviewer_ids = _counted_model_reviewer_ids(reviewer_signals, dogfood_evidence)
    review_object_warnings = _review_object_quorum_warnings(
        pr.get("reviews") or [],
        counted_reviewer_ids=counted_reviewer_ids,
        head_sha=head_sha,
        head_committed_at=head_committed_at,
    )
    # Jurisdiction-counted signals (docs/REVIEW_AUTHORITY_PRINCIPLES.md::Tier-
    # eligibility). At Tier 3-4 only Western families count toward the quorum;
    # Chinese-routed families remain advisory — they still post and stay in
    # counted_reviewer_ids for the audit trail, but do not satisfy the count. So
    # signal_count is the jurisdiction-eligible count that drives the gate decision
    # and the reasons (not the raw recognized-family count).
    #
    # The Western-only filter and the at-least-one-Western check are NOT
    # re-implemented here; they come from the canonical policy object so the live
    # gate and the auto-settle path share one jurisdiction implementation and
    # cannot drift (claude/grok #8507 P2/P3). Build the rule once with the same
    # regime _tier_requirement reads.
    rule = tier_quorum_rule(tier, tiered_gate=tiered_merge_gate_enabled())
    counted_family_set = {str(rid).strip().lower() for rid in counted_reviewer_ids}
    jurisdiction_counted = rule.counted_families(counted_reviewer_ids)
    signal_count = len(jurisdiction_counted)
    # The western-frontier check is derived from the model-review signals ONLY (empty
    # dogfood list). _counted_model_reviewer_ids only ever ADDS dogfood-attributable
    # ids, so the signal-only set is a guaranteed subset of counted_reviewer_ids —
    # any western-frontier signal that satisfies the WF requirement is therefore also
    # counted toward signal_count (claude #8507 P2). Pinned by
    # test_western_frontier_signal_set_is_subset_of_counted.
    counted_reviewer_signal_ids = _counted_model_reviewer_ids(reviewer_signals, [])
    has_required_dogfood = not requirement["requires_adversarial_dogfood"] or any(
        _known_model_reviewer_id(item) for item in dogfood_evidence
    )
    # The WF requirement must be met by a model-review signal, not by dogfood-only
    # metadata. Dogfood remains separately required for Tier 1+.
    has_western_frontier_signal = bool(
        {str(rid).strip().lower() for rid in counted_reviewer_signal_ids}
        & WESTERN_FRONTIER_FAMILIES
    )
    western_frontier_satisfied = (
        not requirement.get("requires_western_frontier_signal") or has_western_frontier_signal
    )
    # Tier 2: at least one counted family must be Western (rule-derived flag).
    at_least_one_western_satisfied = not rule.requires_at_least_one_western or bool(
        jurisdiction_counted & WESTERN_FAMILIES
    )
    quorum_satisfied = (
        signal_count >= requirement["required_model_signals"]
        and has_required_dogfood
        and western_frontier_satisfied
        and at_least_one_western_satisfied
    )
    required_pr_check_surface = (
        check_surfaces.get("required_pr_checks") if isinstance(check_surfaces, dict) else {}
    )
    quorum_only_required_failure = bool(
        isinstance(required_pr_check_surface, dict)
        and required_pr_check_surface.get("quorum_only_failure")
    )
    # #8739: self-check-independent reachability for advisory_settle. In the
    # enforcing merge-quorum job the quorum row is the excluded self-check, so
    # ``quorum_only_failure`` is False; ``advisory_settle_surface_clear`` is True
    # whenever no NON-quorum required check is failing/pending. Since
    # ``quorum_only_failure`` implies a clear surface, the OR below is
    # backward-compatible with external settle-tooling callers that only populate
    # the older key.
    advisory_settle_surface_clear = bool(
        isinstance(required_pr_check_surface, dict)
        and required_pr_check_surface.get("advisory_settle_surface_clear")
    )
    advisory_settle_reachable = advisory_settle_surface_clear or quorum_only_required_failure
    stale_quorum_check_after_satisfied_evidence = (
        quorum_only_required_failure and quorum_satisfied and not settlement_recorded
    )
    # --- Advisory-dissent settlement (opt-in, default OFF) ------------------
    # A PR that fails the strict model quorum may still settle via the distinct
    # ``advisory_settle`` verdict when (and ONLY when) every condition holds:
    #   1. the flag is ON (default OFF -> path dormant, behavior byte-identical);
    #   2. tier is 0/1/2 (Tier 3-4 keep human settlement, unaffected);
    #   3. the only failing required check is the model-quorum check itself
    #      (``quorum_only_required_failure``) -> all OTHER required checks are green;
    #   4. at least one western-frontier review (claude/openai) exists at the head;
    #   5. ZERO `[P0]`/`[P1]` blocking findings across ALL collected reviews, AND no
    #      unresolved protocol/comment dissent. Condition (5) reuses the SAME
    #      ``has_blocking_finding_or_label`` helper the dissent half consults, scanned
    #      over every grounded review body, so it holds regardless of whether the
    #      separate severity-gated-dissent flag is on. Any blocking finding or
    #      unresolved dissent disqualifies advisory_settle.
    # This is a strict fallback: it is only consulted when the strict quorum was NOT
    # satisfied, and it never relaxes the blocking-finding bar.
    advisory_findings = list(advisory_views)
    # Single validated pass over grounded reviews — all positive inputs share the
    # strict path's source filters (non-bot + countable identity); the blocking
    # scan is fail-closed (#8729: closes the spoofed-identity / bot-author /
    # uncountable-advisory-CR bypass class in one place).
    (
        _wf_review_present,
        _genuine_advisory_dissent,
        _any_blocking_finding,
    ) = _advisory_settle_review_signals(
        pr.get("comments") or [],
        head_sha=head_sha,
        head_committed_at=head_committed_at,
    )
    advisory_settle_eligible = (
        advisory_dissent_settle_enabled()
        and tier is not None
        and 0 <= tier <= 2
        and advisory_settle_reachable
        and not quorum_satisfied
        and not settlement_recorded
        # NOTE (#8729 claude [P2]): advisory_settle deliberately does NOT require
        # ``has_required_dogfood`` — dogfood is skipped for negative-verdict comments,
        # so a dogfood gate would re-create the self-defeating contradiction the
        # WF-any-verdict fix removed. The adversarial evidence IS the validated WF
        # review plus the hard zero-[P0]/[P1] bar.
        # No other blocker may be in play: only the model-quorum check is failing.
        and not has_pending
        and not checks_unavailable
        and not blocking_workflow_state
        # A validated western-frontier review must EXIST at head in ANY verdict, and
        # there must be GENUINE (validated-source) advisory dissent being waived —
        # not a lone approval (a one-review bypass) — and NO blocking finding in any
        # recognized review, and no unresolved dissent.
        and _wf_review_present
        and _genuine_advisory_dissent
        and not unresolved_dissent
        and not _any_blocking_finding
    )
    # The incomplete-quorum check only acts as an ACTIVE blocker when advisory_settle
    # is NOT rescuing this PR; otherwise the merge-quorum check is treated as resolved
    # by the advisory path (and the verdict chain reports advisory_settle instead).
    missing_quorum_is_active_check_blocker = (
        quorum_only_required_failure
        and not quorum_satisfied
        and not settlement_recorded
        and not advisory_settle_eligible
    )
    requires_human_preapproval = bool(requirement["requires_human_preapproval"])
    local_human_risk_settlement_recorded = human_risk_settlement_recorded
    resolved_repo_slug = repo_slug or rest_fallback._repo_slug_from_pr_payload(pr, None)
    preapproval_comment_url = (
        _trusted_tier_four_human_preapproval_comment_url(
            pr,
            head_sha=head_sha,
            head_committed_at=head_committed_at,
            repo_slug=resolved_repo_slug,
            gh_json=_gh_json,
        )
        if requires_human_preapproval
        else ""
    )
    # Cross-process Tier 4 settlement is repo-visible by design: it counts only
    # when an exact-head trusted operator comment is bound to a matching
    # aragora/human-settlement status created by that same trusted operator.
    repo_visible_human_preapproval_recorded = (
        requires_human_preapproval
        and _has_successful_status_context(pr, HUMAN_SETTLEMENT_CONTEXT)
        and bool(preapproval_comment_url)
    )
    human_preapproval_recorded = False
    settlement_creator_pin = dict(
        trusted_creator=_trusted_settlement_creator(), checked=False, verified=False, reason=""
    )
    if repo_visible_human_preapproval_recorded:
        creator_verified, creator_reason = _human_settlement_status_creator_verified(
            repo_slug=resolved_repo_slug,
            head_sha=head_sha,
            target_url=preapproval_comment_url,
            gh_json=_gh_json,
        )
        settlement_creator_pin["checked"] = True
        settlement_creator_pin["verified"] = creator_verified
        settlement_creator_pin["reason"] = creator_reason
        if creator_verified:
            human_preapproval_recorded = True
    reasons = [tier_reason]
    if settlement_creator_pin["checked"] and not settlement_creator_pin["verified"]:
        reasons.append(str(settlement_creator_pin["reason"]))
    if settlement_recorded:
        reasons.append("exact-head admin_squash_merge settlement receipt recorded")
    elif human_preapproval_recorded:
        if local_human_risk_settlement_recorded:
            reasons.append("exact-head human risk settlement receipt recorded")
        else:
            reasons.append("repo-visible exact-head human risk settlement recorded")
        reasons.append("exact-head Tier 4 human preapproval verified")
        reasons.append(str(settlement_creator_pin["reason"]))
    elif human_risk_settlement_recorded:
        reasons.append("exact-head human risk settlement receipt recorded")
    if (
        has_failures
        and not settlement_recorded
        and not missing_quorum_is_active_check_blocker
        and not advisory_settle_eligible
    ):
        reasons.append("checks are failing; repair before settlement")
    elif missing_quorum_is_active_check_blocker:
        reasons.append(
            "required aragora-merge-quorum is failing because model quorum is incomplete"
        )
    if checks_unavailable and not settlement_recorded:
        reasons.append("checks are unavailable; wait for GitHub check rollup before settlement")
        if isinstance(check_surfaces, dict) and (
            check_surfaces.get("direct_commit_check_runs") or {}
        ).get("total", 0):
            reasons.append(
                "direct commit check-runs are visible, but PR statusCheckRollup is empty; "
                "refresh the PR-facing check rollup before settlement"
            )
    elif has_pending and not settlement_recorded:
        reasons.append("checks are pending; wait before settlement")
    if not settlement_recorded:
        reasons.extend(blocking_workflow_reasons)
    if unresolved_dissent and not settlement_recorded:
        reasons.append("unresolved model dissent is present")
    for advisory in advisory_views:
        family = str(advisory.get("agent", "") or "unknown")
        severity = advisory.get("highest_severity")
        # ``highest_severity`` is None both for a [P2]/[P3]-only CR and for a
        # finding-free CR, so don't assert "[P2]/[P3] only" — report the accurate
        # invariant (no blocking [P0]/[P1] finding) in the audit packet.
        sev_note = severity if severity else "no blocking [P0]/[P1] finding"
        reasons.append(
            f"advisory finding from {family}: {sev_note} — not blocking (severity-gated dissent)"
        )
    if advisory_settle_eligible:
        reasons.append(
            "advisory-dissent settle: only the model-quorum check is failing, a "
            "western-frontier review is present at head, and no [P0]/[P1] blocking "
            "findings remain; settling on advisory findings only"
        )
        if advisory_findings:
            reasons.append(f"{len(advisory_findings)} advisory finding(s) surfaced for follow-up")
    if not quorum_satisfied and not settlement_recorded and not advisory_settle_eligible:
        if signal_count < requirement["required_model_signals"]:
            reasons.append(
                "model quorum incomplete: "
                f"{signal_count}/{requirement['required_model_signals']} signal(s)"
            )
        if not has_required_dogfood:
            reasons.append("focused adversarial dogfood evidence is required")
        if not western_frontier_satisfied:
            reasons.append(
                "a western-frontier model signal (claude/openai) is required to settle this tier"
            )
        if rule.western_only_counted and (counted_family_set - jurisdiction_counted):
            reasons.append(
                "Tier 3-4 requires a Western-only counted quorum; Chinese-routed "
                "families are advisory-only and do not count toward the quorum"
            )
        if not at_least_one_western_satisfied:
            reasons.append("at least one counted model signal must be from a Western family")
        reasons.extend(review_object_warnings)
    admin_squash_allowed = False
    requires_human_risk_settlement = bool(requirement["requires_human_risk_settlement"])
    if settlement_recorded:
        status = "settled"
        verdict = "already_merged_settlement_recorded"
        requires_human_risk_settlement = False
    elif (
        (
            has_failures
            and not missing_quorum_is_active_check_blocker
            and not advisory_settle_eligible
        )
        or has_pending
        or checks_unavailable
        or (
            machine_recommendation == "repair_first"
            and not missing_quorum_is_active_check_blocker
            and not advisory_settle_eligible
        )
        or stale_quorum_check_after_satisfied_evidence
        or blocking_workflow_state
    ):
        status = "repair_or_wait"
        verdict = "not_ready_for_settlement"
    elif advisory_settle_eligible:
        # Opt-in advisory-dissent settlement: a distinct, auditable verdict (NOT
        # ``admin_squash_allowed``) so the audit trail records that this settled on
        # advisory findings only. Tier 0-2 only; no human risk settlement required.
        status = "satisfied"
        verdict = "advisory_settle"
        requires_human_risk_settlement = False
        admin_squash_allowed = True
    elif not quorum_satisfied:
        status = "needs_model_review_quorum"
        verdict = "collect_model_quorum_before_merge"
    elif unresolved_dissent:
        status = "unresolved_dissent"
        verdict = "human_risk_settlement_required"
        requires_human_risk_settlement = True
    elif human_preapproval_recorded:
        status = "satisfied"
        verdict = "admin_squash_allowed"
        requires_human_risk_settlement = False
        requires_human_preapproval = False
        admin_squash_allowed = True
    elif requires_human_preapproval:
        status = "human_preapproval_required"
        verdict = "tier_4_human_preapproval_required"
        requires_human_risk_settlement = True
    elif requires_human_risk_settlement and human_risk_settlement_recorded:
        status = "satisfied"
        verdict = "admin_squash_allowed"
        requires_human_risk_settlement = False
        admin_squash_allowed = True
    elif requires_human_risk_settlement:
        status = "human_risk_settlement_required"
        verdict = "model_quorum_satisfied_human_risk_settlement_required"
    else:
        status = "satisfied"
        verdict = "admin_squash_allowed"
        admin_squash_allowed = True
    return {
        "version": MODEL_REVIEW_QUORUM_VERSION,
        "head_sha": str(pr.get("headRefOid", "")).strip(),
        "tier": tier,
        "tier_name": tier_name,
        "tier_reason": tier_reason,
        "required_model_signals": requirement["required_model_signals"],
        "requires_western_frontier_signal": bool(
            requirement.get("requires_western_frontier_signal")
        ),
        "has_western_frontier_signal": has_western_frontier_signal,
        "requires_adversarial_dogfood": requirement["requires_adversarial_dogfood"],
        "requires_human_risk_settlement": requires_human_risk_settlement,
        "human_risk_settlement_recorded": local_human_risk_settlement_recorded,
        "requires_human_preapproval": requires_human_preapproval,
        "human_preapproval_recorded": human_preapproval_recorded,
        "settlement_creator_pin": settlement_creator_pin,
        "admin_squash_allowed": admin_squash_allowed,
        "status": status,
        "verdict": verdict,
        "reviewer_signals": reviewer_signals,
        "dogfood_evidence": dogfood_evidence,
        "counted_reviewer_ids": counted_reviewer_ids,
        "counted_model_families": counted_reviewer_ids,
        "dissenting_views": dissenting_views,
        "advisory_views": advisory_views,
        # Advisory findings surfaced for follow-up issue-filing by a caller when the
        # PR settles via the advisory_settle path. Populated only when that path is
        # eligible (otherwise empty); issue-filing itself is a caller concern, not
        # this gate's. Mirrors ``advisory_views`` content for the eligible case.
        "advisory_findings": advisory_findings if advisory_settle_eligible else [],
        "advisory_settle": advisory_settle_eligible,
        "unresolved_dissent": unresolved_dissent,
        "reasons": reasons,
    }


def _classify_model_review_tier(
    files: list[str],
    *,
    pr: dict[str, Any] | None = None,
) -> tuple[int, str, str]:
    normalized = [path.strip() for path in files if path.strip()]
    title = str((pr or {}).get("title", "") or "").lower()
    if not normalized:
        return (1, "tier_1_additive_internal", "no changed files reported; defaulting to Tier 1")
    if any(_matches_prefix(path, TIER_4_PREFIXES) for path in normalized):
        return (4, "tier_4_preapproval_required", "workflow/deploy/destructive surface touched")
    if any(_matches_prefix(path, TIER_3_PREFIXES) for path in normalized) or any(
        keyword in title for keyword in TIER_3_TITLE_KEYWORDS
    ):
        return (
            3,
            "tier_3_semantic_risk",
            "semantic, persistence, security, API, or SDK surface touched",
        )
    if all(_is_docs_tests_or_status_path(path) for path in normalized):
        return (0, "tier_0_docs_tests_status", "docs/tests/status-only change")
    if any(_matches_prefix(path, TIER_2_PREFIXES) for path in normalized) or any(
        word in title for word in ("retry", "cache", "cli", "automation", "observability")
    ):
        return (
            2,
            "tier_2_live_automation",
            "live automation, CLI, observability, retry, or cache surface touched",
        )
    return (1, "tier_1_additive_internal", "bounded internal code surface")


def _tier_requirement(tier: int) -> dict[str, Any]:
    # Single source of truth for the model-quorum bar: the shared tier_quorum_rule
    # (also used by the auto-settle path's CollectOutcome.has_supportive_quorum) so the
    # merge gate and the collector share one tier→requirement mapping and one WF
    # allowlist; they cannot drift on WHAT each tier requires.
    #
    # The two paths intentionally differ on regime SELECTION, and the asymmetry is by
    # design (claude #8507 P1; full rationale in docs/specs/TIERED_MERGE_GATE_QUORUM_POLICY.md):
    #   * This live merge gate is evaluated fresh on every CI run against the PR's
    #     current evidence, so there is no prepare→apply staleness window to reconcile.
    #     It reads the live flag directly. The flag is default OFF, and enabling it is
    #     itself the operator's deliberate, Tier-4-gated audit point — the global flag
    #     *is* the revocation control (flip OFF to revoke everywhere).
    #   * The auto-settle apply path stores a prepared artifact with a real time gap
    #     between prepare and apply, so it additionally reconciles via min(prepared,
    #     live) to stop a flag flip from retroactively relaxing a stale artifact.
    # Both are strict-by-default; only the apply path needs the extra reconciliation
    # because only it has stored, deferrable state.
    rule = tier_quorum_rule(tier, tiered_gate=tiered_merge_gate_enabled())
    return {
        "required_model_signals": rule.required_signals,
        "requires_western_frontier_signal": rule.requires_western_frontier,
        "western_only_counted": rule.western_only_counted,
        "requires_at_least_one_western": rule.requires_at_least_one_western,
        "requires_adversarial_dogfood": tier > 0,
        "requires_human_risk_settlement": tier >= 3,
        "requires_human_preapproval": tier >= 4,
    }


def _has_blocking_workflow_state(pr: dict[str, Any]) -> bool:
    return bool(_blocking_workflow_state_reasons(pr))


def _blocking_workflow_state_reasons(pr: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    settlement_state_block = _settlement_state_block_reason(pr)
    if settlement_state_block:
        reasons.append(settlement_state_block)
    if bool(pr.get("isDraft", False)):
        reasons.append("draft PR")
    mergeable = str(pr.get("mergeable", "")).strip().upper()
    if mergeable == "CONFLICTING":
        reasons.append("merge conflict")
    labels = [
        str(label.get("name", "")).strip()
        for label in (pr.get("labels") or [])
        if isinstance(label, dict) and label.get("name")
    ]
    parked_label_hits = [label for label in labels if label in PARKED_LABELS]
    if parked_label_hits:
        reasons.append(f"parked label ({','.join(parked_label_hits)})")
    return reasons


def _settlement_state_block_reason(pr: dict[str, Any]) -> str:
    state = str(pr.get("state") or "").strip().upper()
    merged_at = str(pr.get("mergedAt") or "").strip()
    if merged_at:
        if state == "OPEN":
            return (
                "PR state is OPEN but mergedAt is set; settlement applies only to open unmerged PRs"
            )
        return f"PR is {state or 'MERGED'}; settlement applies only to open PRs"
    if state and state != "OPEN":
        return f"PR is {state}; settlement applies only to open PRs"
    return ""


def _has_recorded_admin_squash_settlement(
    *,
    pr_number: int,
    head_sha: str,
    review_queue_root: str | Path | None,
) -> bool:
    if not head_sha:
        return False
    repo_root = resolve_repo_root(Path.cwd())
    root = _resolve_review_queue_root_override(repo_root, review_queue_root)
    receipts_dir = root / "receipts"
    if not receipts_dir.is_dir():
        return False
    for path in receipts_dir.glob(f"pr-{pr_number}-*.json"):
        try:
            payload = _read_receipt_payload(path)
        except _GhError:
            continue
        if int(payload.get("pr_number") or 0) != pr_number:
            continue
        if str(payload.get("head_sha") or "").strip() != head_sha:
            continue
        if str(payload.get("action") or "").strip() != "admin_squash_merge":
            continue
        if str(payload.get("github_event") or "").strip() != "ADMIN_SQUASH_MERGE":
            continue
        return True
    return False


def _has_recorded_human_risk_settlement(
    *,
    pr_number: int,
    head_sha: str,
    review_queue_root: str | Path | None,
) -> bool:
    if not head_sha:
        return False
    repo_root = resolve_repo_root(Path.cwd())
    root = _resolve_review_queue_root_override(repo_root, review_queue_root)
    receipts_dir = root / "receipts"
    if not receipts_dir.is_dir():
        return False
    # Local settlement receipts are a trusted operator-controlled store, matching
    # admin-squash settlement receipt handling. This path is read-only and exact
    # head bound; it must not infer approval from GitHub comments alone.
    allowed_events = {"APPROVE", "RECORDED_EXTERNAL_APPROVE"}
    for path in receipts_dir.glob(f"pr-{pr_number}-*.json"):
        try:
            payload = _read_receipt_payload(path)
        except _GhError:
            continue
        if int(payload.get("pr_number") or 0) != pr_number:
            continue
        if str(payload.get("head_sha") or "").strip() != head_sha:
            continue
        if str(payload.get("action") or "").strip() != "approve":
            continue
        if str(payload.get("github_event") or "").strip() not in allowed_events:
            continue
        return True
    return False


def _has_successful_status_context(pr: dict[str, Any], context: str) -> bool:
    expected = str(context or "").strip()
    if not expected:
        return False
    for check in _latest_status_check_rollup(pr.get("statusCheckRollup") or []):
        if not isinstance(check, dict):
            continue
        name = str(check.get("context") or check.get("name") or "").strip()
        if name != expected:
            continue
        state = str(check.get("state") or check.get("status") or "").upper()
        conclusion = str(check.get("conclusion") or "").upper()
        return conclusion == "SUCCESS" or state == "SUCCESS"
    for status in rest_fallback._latest_direct_statuses_by_context(
        pr.get("commitStatuses") or []
    ).values():
        if rest_fallback._direct_status_context(status) != expected:
            continue
        return rest_fallback._direct_status_is_success(status)
    return False


def _reviewer_signals_from_protocol(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    validation = protocol.get("validation_summary") or {}
    reviewer_execution = validation.get("reviewer_execution") or {}
    reviewer_ids = reviewer_execution.get("reviewer_ids") or []
    providers = reviewer_execution.get("providers") or []
    signals = []
    for index, reviewer_id in enumerate(reviewer_ids):
        provider = providers[index] if index < len(providers) else ""
        model_family = _normalize_model_reviewer_id(str(provider)) or _normalize_model_reviewer_id(
            str(reviewer_id)
        )
        identity_problems: list[str] = []
        if not model_family:
            identity_problems.append("unknown_model_family")
        signals.append(
            {
                "reviewer_id": str(reviewer_id),
                "provider": str(provider),
                "source": protocol.get("status", ""),
                "surface_reviewer_id": _infer_surface_reviewer_from_candidate(
                    str(provider) or str(reviewer_id)
                ),
                "model_family": model_family,
                "model_id": "",
                "identity_source": "protocol_provider",
                "identity_problems": identity_problems,
            }
        )
    return signals


def _counted_model_reviewer_ids(
    reviewer_signals: list[dict[str, Any]],
    dogfood_evidence: list[dict[str, Any]],
) -> list[str]:
    reviewer_ids: set[str] = set()
    for item in [*reviewer_signals, *dogfood_evidence]:
        reviewer_id = _known_model_reviewer_id(item)
        if reviewer_id:
            reviewer_ids.add(reviewer_id)
    return sorted(reviewer_ids)


def _lint_evidence_comment(
    *,
    pr: str,
    head_sha: str,
    head_committed_at: str,
    body: str,
    author: str,
    source: str,
) -> dict[str, Any]:
    """Dry-run whether one proposed comment would satisfy quorum parsers."""
    grounded, grounding_method = _proposed_evidence_head_grounding(body, head_sha)
    pr_grounded, pr_grounding_method = _proposed_evidence_pr_grounding(body, pr)
    negative_verdict = _has_blocking_or_negative_verdict(body)
    comment = {
        "author": {"login": author},
        "body": body,
        "createdAt": "",
    }
    if grounded and pr_grounded and not negative_verdict:
        dogfood_evidence = _dogfood_evidence_from_comments([comment])
        reviewer_signals = _model_review_signals_from_comments([comment])
    else:
        dogfood_evidence = []
        reviewer_signals = []
    counted_reviewer_ids = _counted_model_reviewer_ids(reviewer_signals, dogfood_evidence)
    identity = _resolve_model_review_identity(body)
    inferred_reviewer = identity.surface_reviewer_id
    lower = body.lower()

    problems: list[str] = []
    if not body.strip():
        problems.append("empty_body")
    if not grounded:
        problems.append("missing_current_head_grounding")
    if not pr_grounded:
        problems.append("wrong_pr_reference")
    if _is_github_actions_author(author):
        problems.append("github_actions_author_not_counted")
    if negative_verdict:
        problems.append("blocking_or_negative_verdict")
    if inferred_reviewer == "unknown_model_reviewer":
        problems.append("missing_known_model_reviewer_heading")
    for problem in identity.identity_problems:
        if problem in IDENTITY_COUNT_BLOCKERS:
            problems.append(problem)
    if not any(
        token in lower
        for token in (
            "dogfood",
            "adversarial",
            "cross-author",
            "recheck",
            "codex review",
            "claude review",
            "grok independent",
            "gemini independent",
            "independent semantic review",
            "independent model review",
            "model-family semantic signal",
        )
    ):
        problems.append("missing_dogfood_or_review_trigger")
    if not counted_reviewer_ids:
        problems.append("no_counted_model_family")
        problems.append("no_counted_model_reviewer")

    return {
        "mode": "evidence_lint",
        "pr_number": str(pr),
        "head_sha": head_sha,
        "head_committed_at": head_committed_at,
        "source": source,
        "author": author,
        "comment_summary": _first_nonempty_line(body)[:240],
        "inferred_reviewer": inferred_reviewer,
        "surface_reviewer_id": identity.surface_reviewer_id,
        "model_family": identity.model_family,
        "model_id": identity.model_id,
        "identity_source": identity.identity_source,
        "identity_problems": list(identity.identity_problems),
        "current_head_grounded": grounded,
        "current_head_grounding_method": grounding_method,
        "current_pr_grounded": pr_grounded,
        "current_pr_grounding_method": pr_grounding_method,
        "dogfood_evidence": dogfood_evidence,
        "reviewer_signals": reviewer_signals,
        "counted_reviewer_ids": counted_reviewer_ids,
        "counted_model_families": counted_reviewer_ids,
        "would_count": bool(counted_reviewer_ids),
        "problems": problems,
    }


def _proposed_evidence_pr_grounding(body: str, pr: str) -> tuple[bool, str]:
    """Fail closed when a proposed evidence comment names the wrong PR.

    Evidence comments are commonly drafted from recursive prompts that include
    both a PR number and an exact head SHA. Lint mode should not approve a
    body that is exact-head grounded but visibly copied from a different PR.
    Comments without an explicit PR citation remain acceptable because the
    caller already supplies the target ``--pr`` and the head SHA is the primary
    current-head proof.
    """
    normalized_pr = str(pr or "").strip().lstrip("#")
    if not normalized_pr:
        return False, "missing_pr_argument"
    cited = {
        match.group(1)
        for match in re.finditer(
            r"\b(?:PR(?:\s+Number)?|pull\s+request)\s*[:#-]?\s*#?(\d+)\b",
            str(body or ""),
            flags=re.IGNORECASE,
        )
    }
    cited.update(
        match.group(1)
        for match in re.finditer(
            r"\bgithub\.com/[^\s)<>]+/pull/(\d+)\b",
            str(body or ""),
            flags=re.IGNORECASE,
        )
    )
    if not cited:
        return True, "no_pr_citation"
    if normalized_pr in cited:
        return True, "pr_citation"
    return False, "wrong_pr_citation"


def _proposed_evidence_head_grounding(body: str, head_sha: str) -> tuple[bool, str]:
    """Require proposed comments to cite the target head SHA prefix.

    Unlike persisted GitHub comments, evidence-lint inputs have no trustworthy
    ``createdAt``.  Lint mode therefore does not use timestamp recency as a
    substitute for current-head grounding.
    """
    normalized_head = str(head_sha or "").strip().lower()
    if len(normalized_head) < 7:
        return False, "missing_head_sha_argument"
    if normalized_head[:7] in str(body or "").lower():
        return True, "head_sha_citation"
    return False, "missing_head_sha_citation"


def _head_committed_at_from_pr(pr: dict[str, Any]) -> str:
    """Return the ``committedDate`` of the PR head commit, or ``""``.

    Used to anchor comment-based quorum signals to the current head
    SHA per the "grounded in the current head SHA" requirement of
    ``docs/REVIEW_AUTHORITY_PRINCIPLES.md``.  Missing identity fails
    closed for comment recency checks.
    """
    head_sha = str(pr.get("headRefOid", "") or "").strip()
    commits = pr.get("commits") or []
    if not isinstance(commits, list):
        return ""
    for entry in commits:
        if not isinstance(entry, dict):
            continue
        committed_at = str(entry.get("committedDate", "") or "").strip()
        if not committed_at:
            continue
        oid = str(entry.get("oid") or entry.get("sha") or "").strip()
        if head_sha and oid == head_sha:
            return committed_at
    return ""


def _known_model_reviewer_id(item: dict[str, Any]) -> str:
    problems = [str(problem) for problem in (item.get("identity_problems") or [])]
    if any(problem in IDENTITY_COUNT_BLOCKERS for problem in problems):
        return ""
    model_family = _normalize_model_family(str(item.get("model_family", "") or ""))
    if model_family:
        return model_family
    provider = str(item.get("provider", "") or "")
    reviewer_id = str(item.get("reviewer_id", "") or "")
    return _normalize_model_reviewer_id(provider) or _normalize_model_reviewer_id(reviewer_id)


def _is_github_actions_author(author: str) -> bool:
    return str(author or "").strip().lower() in {"github-actions", "github-actions[bot]"}


def _normalize_model_reviewer_id(value: str) -> str:
    lower = str(value).lower()
    if not lower or "unknown_model_reviewer" in lower:
        return ""
    known_markers = (
        ("claude", ("claude", "anthropic")),
        ("openai", ("openai", "gpt")),
        ("grok", ("grok", "xai")),
        ("gemini", ("gemini", "google")),
        ("mistral", ("mistral", "codestral")),
        ("deepseek", ("deepseek",)),
        ("qwen", ("qwen",)),
        ("kimi", ("kimi", "moonshot")),
        ("yi", ("yi",)),
        ("glm", ("glm", "zhipu", "z-ai")),
        ("minimax", ("minimax",)),
        ("hermes", ("hermes", "nous hermes")),
    )
    for normalized, markers in known_markers:
        if any(marker in lower for marker in markers):
            return normalized
    return ""


def _normalize_model_family(value: str) -> str:
    lower = str(value or "").strip().lower()
    if not lower:
        return ""
    aliases = {
        "anthropic": "claude",
        "google": "gemini",
        "xai": "grok",
        "codestral": "mistral",
        "moonshot": "kimi",
        "zhipu": "glm",
        "z-ai": "glm",
        "nous-hermes": "hermes",
        "nous hermes": "hermes",
        # OpenAI-family CLI/product names so a disclosed "Model family: codex"
        # still counts at the gate (mirrors canonical_family in quorum_evidence).
        "codex": "openai",
        "gpt": "openai",
        "gpt-5": "openai",
        "gpt5": "openai",
        "chatgpt": "openai",
    }

    def _lookup(token: str) -> str:
        if token in CANONICAL_MODEL_FAMILIES:
            return token
        return aliases.get(token, "")

    # Fast path: the disclosed value is already a bare canonical family or a
    # known (possibly multi-word) alias such as "nous hermes".
    resolved = _lookup(lower)
    if resolved:
        return resolved

    # Agents commonly disclose the family with a trailing parenthetical detail,
    # e.g. ``openai (gpt-5.5, codex exec --sandbox read-only)`` or
    # ``claude (opus-4.8)``. The parenthetical is descriptive metadata, not part
    # of the canonical family token, so a literal lookup of the whole string used
    # to fail and de-count an otherwise-valid reviewer.
    #
    # We ONLY relax the lookup for a *well-formed, trailing, closed*
    # parenthetical suffix: ``<token> (<detail>)`` with nothing but optional
    # whitespace after the closing ``)``. The match captures the text before the
    # ``(`` as ``head`` and the canonical token is the head's *single*
    # whitespace-delimited word (which covers ``openai (gpt-5.5)``). This keeps
    # the gate fail-closed for everything the PR intends to remain blocked:
    #   - no parenthetical at all (``openai claude``) -> no match -> "".
    #   - text *after* the closing paren (``openai (gpt-5.5) claude``) -> the
    #     ``$`` anchor rejects it -> "".
    #   - unclosed parenthetical (``openai (``, ``openai (not closed``) -> no
    #     ``)`` -> no match -> "".
    #   - multi-word head (``openai gpt (x)``) -> head has >1 word -> "".
    # A genuinely-unknown leading token (``mystery (x)``) still resolves to "".
    match = re.fullmatch(r"\s*([^()]*?)\s*\([^()]*\)\s*", lower)
    if not match:
        return ""
    head = match.group(1).strip()
    head_words = head.split()
    if len(head_words) != 1:
        # Multi-word alias such as "nous hermes (8x7b)" is still a legitimate
        # disclosure: try the full head before rejecting a >1-word head.
        resolved = _lookup(head)
        if resolved:
            return resolved
        return ""
    return _lookup(head_words[0])


def _first_heading_candidate(text: str) -> tuple[str, int | None]:
    for index, line in enumerate(str(text).splitlines()):
        stripped = line.strip()
        if stripped.startswith("#"):
            candidate = stripped.lstrip("#").strip()
            if candidate:
                return candidate, index
    return str(text)[:200], None


def _infer_surface_reviewer_from_candidate(candidate: str) -> str:
    lower = str(candidate or "").lower()
    for name in ("claude", "codex", "tesla", "harvey", "factory", "grok", "gemini"):
        if name in lower:
            return name
    for family, markers in DIRECT_MODEL_FAMILY_MARKERS.items():
        if any(marker in lower for marker in markers):
            return family
    return "unknown_model_reviewer"


def _structured_identity_metadata(text: str, heading_index: int | None) -> dict[str, str]:
    if heading_index is None:
        return {}
    lines = str(text).splitlines()
    metadata: dict[str, str] = {}
    in_fence = False
    fence_marker = ""
    for line in lines[heading_index + 1 : heading_index + 26]:
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        if stripped.startswith("#"):
            break
        label, sep, value = stripped.partition(":")
        if not sep:
            continue
        normalized_label = label.strip().strip("*").lower()
        normalized_value = value.strip().strip("*").strip()
        if normalized_label in {
            "reviewer harness",
            "model family",
            "model id",
            "receipt artifact",
        }:
            metadata[normalized_label] = normalized_value
    return metadata


def _resolve_model_review_identity(text: str) -> ModelReviewIdentity:
    candidate, heading_index = _first_heading_candidate(text)
    surface = _infer_surface_reviewer_from_candidate(candidate)
    metadata = _structured_identity_metadata(text, heading_index)
    explicit_family_raw = metadata.get("model family", "")
    explicit_family = _normalize_model_family(explicit_family_raw)
    model_id = metadata.get("model id", "")
    receipt_artifact = metadata.get("receipt artifact", "")
    problems: list[str] = []

    if surface == "unknown_model_reviewer":
        problems.append("unknown_surface_reviewer")

    if explicit_family_raw and not explicit_family:
        problems.append("unknown_model_family")

    model_family = explicit_family
    identity_source = "model_family_metadata" if explicit_family_raw else "none"

    if surface in ROUTER_SURFACE_REVIEWERS:
        if not explicit_family_raw:
            problems.append("missing_model_family_disclosure")
    elif surface != "unknown_model_reviewer":
        direct_family = _normalize_model_family(surface)
        if explicit_family and direct_family and explicit_family != direct_family:
            problems.append("heading_model_family_conflict")
        if not explicit_family_raw and direct_family:
            model_family = direct_family
            identity_source = "direct_heading"
        elif explicit_family and direct_family == explicit_family:
            identity_source = "model_family_metadata"

    if not receipt_artifact:
        problems.append("missing_receipt_artifact")

    return ModelReviewIdentity(
        surface_reviewer_id=surface,
        model_family=model_family,
        model_id=model_id,
        identity_source=identity_source,
        identity_problems=tuple(dict.fromkeys(problems)),
    )


def _model_family_from_body(body: str) -> str:
    """Resolve a known model family from a ``Model family:`` line anywhere.

    The structured-metadata reader (:func:`_structured_identity_metadata`) only
    inspects the lines immediately following the first heading. Dogfood comments
    in the wild disclose the model family in a ``Model family: <name>`` bullet
    that may appear lower in the body — or under a plain
    ``## Focused adversarial dogfood`` heading that names no model. Scan the full
    body for such a line and normalize it to a canonical family. Returns ``""``
    when no recognizable family is disclosed (fail-closed: no phantom inflation).

    Fenced code blocks (```` ``` ````/``~~~``) and inline-code spans (`` `...` ``)
    are skipped so a merely *quoted* ``Model family:`` example — e.g. someone
    pasting the disclosure template into a code fence — cannot inflate quorum.
    """
    in_fence = False
    fence_marker = ""
    for raw_line in str(body).splitlines():
        stripped = raw_line.strip()
        # Track fenced code blocks and skip everything inside them.
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif marker == fence_marker:
                in_fence = False
                fence_marker = ""
            continue
        if in_fence:
            continue
        # Drop inline-code spans so a back-ticked example label is not parsed
        # as a real disclosure line.
        stripped = re.sub(r"`[^`]*`", "", stripped).strip()
        if stripped.startswith("-"):
            stripped = stripped[1:].strip()
        label, sep, value = stripped.partition(":")
        if not sep:
            continue
        normalized_label = label.strip().strip("*").strip().lower()
        if normalized_label != "model family":
            continue
        candidate = value.strip().strip("*").strip().strip("`")
        family = _normalize_model_family(candidate)
        if family:
            return family
    return ""


def _resolve_dogfood_identity(body: str) -> ModelReviewIdentity:
    """Resolve dogfood-comment identity, allowing a body-named model family.

    Starts from the shared :func:`_resolve_model_review_identity` (heading +
    post-heading structured metadata). When that yields a countable model
    reviewer, it is returned unchanged.

    The body-family fallback is applied **only** when the original resolution
    failed for the benign reason "no model was inferable from the heading or its
    structured metadata" — i.e. the heading named no surface and the only
    count-blocker is ``unknown_surface_reviewer``. If the original identity
    carries a *real* problem — an unknown/unnormalizable disclosed family
    (``unknown_model_family``), a router surface that disclosed no family
    (``missing_model_family_disclosure``), or a heading/metadata family
    *conflict* (``heading_model_family_conflict``) — we stay fail-closed and do
    NOT count, exactly as the original resolver intended. Falling back in those
    cases would let a body-scanned family silently override a deliberate block.
    """
    identity = _resolve_model_review_identity(body)
    if _known_model_reviewer_id(identity.as_packet_fields()):
        return identity

    # Only the benign "heading named no model" failure is eligible for the
    # body-family fallback. Any other count-blocker is a real signal that the
    # original resolver intentionally refused to count.
    blockers = {
        problem for problem in identity.identity_problems if problem in IDENTITY_COUNT_BLOCKERS
    }
    if blockers - {"unknown_surface_reviewer"}:
        return identity

    family = _model_family_from_body(body)
    if not family:
        return identity

    metadata = _structured_identity_metadata(body, _first_heading_candidate(body)[1])
    model_id = metadata.get("model id", "")
    return ModelReviewIdentity(
        surface_reviewer_id=family,
        model_family=family,
        model_id=model_id,
        identity_source="dogfood_body_model_family",
    )


def _dogfood_evidence_from_comments(
    comments: list[Any],
    *,
    head_sha: str = "",
    head_committed_at: str = "",
) -> list[dict[str, Any]]:
    """Extract focused-adversarial dogfood signals from PR comments.

    Mirrors the source-side filtering of
    :func:`_model_review_signals_from_comments` for symmetry. Router
    comments whose first heading names a known surface but whose metadata
    is missing or conflicted remain visible in the evidence list with
    ``identity_problems``; counting remains fail-closed.

    Identity is resolved via :func:`_resolve_dogfood_identity`, which accepts a
    model family disclosed anywhere in the body (e.g. a ``Model family: claude``
    line under a plain ``## Focused adversarial dogfood`` heading), not only one
    named in the first heading. The head-grounding and github-actions exclusions
    below are preserved unchanged.
    """
    evidence: list[dict[str, Any]] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        if not _is_comment_grounded_on_head(comment, head_sha, head_committed_at):
            continue
        body = str(comment.get("body", "") or "")
        if _has_blocking_or_negative_verdict(body):
            continue
        lower = body.lower()
        if not any(
            token in lower for token in ("dogfood", "adversarial", "cross-author", "recheck")
        ):
            continue
        identity = _resolve_dogfood_identity(body)
        if identity.surface_reviewer_id == "unknown_model_reviewer":
            continue
        author_payload = comment.get("author")
        author = ""
        if isinstance(author_payload, dict):
            author = str(author_payload.get("login", "") or "")
        if _is_github_actions_author(author):
            continue
        evidence.append(
            {
                "reviewer_id": identity.model_family or identity.surface_reviewer_id,
                "github_author": author,
                "source": "pr_comment",
                "summary": _first_nonempty_line(body)[:240],
                **identity.as_packet_fields(),
            }
        )
    return evidence[:5]


def _dissenting_views_from_comments(
    comments: list[Any],
    *,
    head_sha: str = "",
    head_committed_at: str = "",
    advisory_views: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Extract exact-head model-review comments that visibly request changes.

    When ``ARAGORA_ENABLE_SEVERITY_GATED_DISSENT`` is OFF (default) a comment that
    ``_has_blocking_or_negative_verdict`` — a real ``[P0]``/``[P1]`` finding, a
    populated Blocker label, OR a bare negative ``Verdict:`` line — promotes a
    blocking dissent, byte-identical to historical behavior.

    When the flag is ON, only a comment backed by a real ``[P0]``/``[P1]`` finding
    or a populated Blocker label (``_has_blocking_finding_or_label``) promotes a
    blocking dissent. A ``[P2]``/``[P3]``-only or finding-free CHANGES-REQUESTED is
    downgraded to *advisory*: non-blocking, and — because it is excluded from the
    returned blocking-dissent list and never marked supportive — non-counting. The
    downgraded comment is still recorded (in ``advisory_views`` when provided) so the
    review quality stays visible on the PR / in the audit packet.
    """
    markers = (
        "dogfood",
        "adversarial",
        "cross-author",
        "recheck",
        "codex review",
        "claude review",
        "grok independent",
        "gemini independent",
        "independent semantic review",
        "independent model review",
        "model-family semantic signal",
    )
    severity_gated = severity_gated_dissent_enabled()
    dissent: list[dict[str, Any]] = []
    for comment in comments:
        if not isinstance(comment, dict) or not _is_comment_grounded_on_head(
            comment, head_sha, head_committed_at
        ):
            continue
        body = str(comment.get("body", "") or "")
        lower = body.lower()
        if not any(token in lower for token in markers):
            continue
        # Flag OFF: a bare negative Verdict line still blocks (historical behavior).
        # Flag ON: only a real [P0]/[P1] finding or a populated Blocker label blocks;
        # a [P2]/[P3]-only or finding-free CHANGES-REQUESTED becomes advisory.
        blocks = (
            _has_blocking_finding_or_label(body)
            if severity_gated
            else _has_blocking_or_negative_verdict(body)
        )
        if not blocks:
            if severity_gated and advisory_views is not None:
                advisory = _build_advisory_view(comment, body)
                if advisory is not None:
                    advisory_views.append(advisory)
            continue
        identity = _resolve_model_review_identity(body)
        if identity.surface_reviewer_id == "unknown_model_reviewer":
            identity = _resolve_dogfood_identity(body)
        if identity.surface_reviewer_id == "unknown_model_reviewer":
            continue
        author_payload = comment.get("author")
        github_author = ""
        if isinstance(author_payload, dict):
            github_author = str(author_payload.get("login", "") or "")
        dissent.append(
            {
                "agent": identity.model_family or identity.surface_reviewer_id,
                "position": "changes_requested",
                "reason": _first_nonempty_line(body)[:240],
                "source": "pr_comment",
                "github_author": github_author,
                **identity.as_packet_fields(),
            }
        )
    return dissent[:5]


def _build_advisory_view(comment: dict[str, Any], body: str) -> dict[str, Any] | None:
    """Build the advisory (non-blocking, non-counting) record for a CHANGES-REQUESTED
    comment that, under the severity gate, carries only ``[P2]``/``[P3]`` (or no)
    findings. Returns ``None`` if the reviewer identity is unrecognized.
    """
    # The comment WOULD have blocked under the strict (flag-OFF) regime: it is a
    # genuine negative verdict, just not backed by a real [P0]/[P1] finding or a
    # populated Blocker label. Recording it preserves the reviewer's signal.
    if not _has_blocking_or_negative_verdict(body):
        return None
    identity = _resolve_model_review_identity(body)
    if identity.surface_reviewer_id == "unknown_model_reviewer":
        identity = _resolve_dogfood_identity(body)
    if identity.surface_reviewer_id == "unknown_model_reviewer":
        return None
    author_payload = comment.get("author")
    github_author = ""
    if isinstance(author_payload, dict):
        github_author = str(author_payload.get("login", "") or "")
    severity = _highest_blocking_severity(body)
    return {
        "agent": identity.model_family or identity.surface_reviewer_id,
        "position": "advisory_changes_requested",
        "blocking": False,
        "highest_severity": severity,  # None for finding-free, never P0/P1 here
        "reason": _first_nonempty_line(body)[:240],
        "source": "pr_comment",
        "github_author": github_author,
        **identity.as_packet_fields(),
    }


def _model_review_signals_from_comments(
    comments: list[Any],
    *,
    head_sha: str = "",
    head_committed_at: str = "",
) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    for comment in comments:
        if not isinstance(comment, dict):
            continue
        if not _is_comment_grounded_on_head(comment, head_sha, head_committed_at):
            continue
        body = str(comment.get("body", "") or "")
        if _has_blocking_or_negative_verdict(body):
            continue
        lower = body.lower()
        if not any(
            token in lower
            for token in (
                "codex review",
                "claude review",
                "grok independent",
                "gemini independent",
                "independent semantic review",
                "independent model review",
                "model-family semantic signal",
            )
        ):
            continue
        identity = _resolve_model_review_identity(body)
        if identity.surface_reviewer_id == "unknown_model_reviewer":
            continue
        author_payload = comment.get("author")
        github_author = ""
        if isinstance(author_payload, dict):
            github_author = str(author_payload.get("login", "") or "")
        if _is_github_actions_author(github_author):
            continue
        signals.append(
            {
                "reviewer_id": identity.model_family or identity.surface_reviewer_id,
                "provider": identity.model_family,
                "source": "pr_comment",
                "summary": _first_nonempty_line(body)[:240],
                "github_author": github_author,
                **identity.as_packet_fields(),
            }
        )
    return signals[:5]


def _review_object_quorum_warnings(
    reviews: list[Any],
    *,
    counted_reviewer_ids: list[str],
    head_sha: str = "",
    head_committed_at: str = "",
) -> list[str]:
    """Warn when ``review-pr`` evidence is present in non-countable form.

    Merge quorum intentionally counts model evidence from PR comments because
    comments are easier to audit, quote, and mirror across queue tooling. A
    GitHub review object alone should therefore not satisfy quorum, but it
    should produce an operator-visible warning instead of silently looking like
    missing evidence.
    """
    counted = set(counted_reviewer_ids)
    warnings: list[str] = []
    warned: set[str] = set()
    for review in reviews:
        if not isinstance(review, dict):
            continue
        if not _is_review_grounded_on_head(review, head_sha, head_committed_at):
            continue
        body = str(review.get("body", "") or "")
        identity = _resolve_review_object_model_identity(body)
        reviewer_id = _known_model_reviewer_id(identity.as_packet_fields())
        if reviewer_id:
            if reviewer_id in counted or reviewer_id in warned:
                continue
            warnings.append(
                "GitHub review object from "
                f"{reviewer_id} is advisory-only for merge-packet model quorum; "
                "mirror the review-pr output into a current-head PR comment before settlement"
            )
            warned.add(reviewer_id)
            continue
        surface = identity.surface_reviewer_id
        if surface == "unknown_model_reviewer" or surface in warned:
            continue
        if any(problem in IDENTITY_COUNT_BLOCKERS for problem in identity.identity_problems):
            warnings.append(
                "GitHub review object from "
                f"{surface} lacks lineage-bound model family metadata; mirror the "
                "review-pr output into a current-head PR comment with Model family "
                "metadata before settlement"
            )
            warned.add(surface)
    return warnings


def _resolve_review_object_model_identity(body: str) -> ModelReviewIdentity:
    identity = _resolve_model_review_identity(body)
    if _known_model_reviewer_id(identity.as_packet_fields()):
        return identity

    metadata = _review_pr_metadata_from_body(body)
    reviewer = metadata.get("reviewer", "")
    if not reviewer:
        return identity

    surface = _infer_surface_reviewer_from_candidate(reviewer)
    explicit_family_raw = metadata.get("model family", "")
    explicit_family = _normalize_model_family(explicit_family_raw)
    model_id = metadata.get("model id", "")
    problems: list[str] = []

    if surface == "unknown_model_reviewer":
        problems.append("unknown_surface_reviewer")
    if explicit_family_raw and not explicit_family:
        problems.append("unknown_model_family")

    model_family = explicit_family
    identity_source = "review_pr_model_family_metadata" if explicit_family_raw else "none"
    if surface in ROUTER_SURFACE_REVIEWERS:
        if not explicit_family_raw:
            problems.append("missing_model_family_disclosure")
    elif surface != "unknown_model_reviewer":
        direct_family = _normalize_model_family(surface)
        if explicit_family and direct_family and explicit_family != direct_family:
            problems.append("heading_model_family_conflict")
        if not explicit_family_raw and direct_family:
            model_family = direct_family
            identity_source = "review_pr_direct_reviewer"
        elif explicit_family and direct_family == explicit_family:
            identity_source = "review_pr_model_family_metadata"

    return ModelReviewIdentity(
        surface_reviewer_id=surface,
        model_family=model_family,
        model_id=model_id,
        identity_source=identity_source,
        identity_problems=tuple(dict.fromkeys(problems)),
    )


def _review_pr_metadata_from_body(body: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in str(body).splitlines():
        stripped = line.strip()
        if stripped.startswith("-"):
            stripped = stripped[1:].strip()
        label, sep, value = stripped.partition(":")
        if not sep:
            continue
        normalized_label = label.strip().strip("*").lower()
        if normalized_label not in {"reviewer", "model family", "model id"}:
            continue
        metadata[normalized_label] = value.strip().strip("*").strip().strip("`")
    return metadata


def _is_review_grounded_on_head(
    review: dict[str, Any],
    head_sha: str,
    head_committed_at: str,
) -> bool:
    if not head_sha:
        return True
    commit = review.get("commit")
    body = str(review.get("body", "") or "")
    head_short = head_sha[:7]
    if isinstance(commit, dict):
        commit_oid = str(commit.get("oid", "") or "").strip()
        if commit_oid:
            if commit_oid == head_sha:
                return True
            return bool(head_short and head_short in body)
    if head_short and head_short in body:
        return True
    if not head_committed_at:
        return False
    submitted = str(review.get("submittedAt", "") or "")
    if not submitted:
        return False
    return submitted >= head_committed_at


def _infer_model_reviewer_from_text(text: str) -> str:
    """Infer the reviewing model from a comment body.

    Restricts the substring match to a *structured* marker — the first
    markdown heading line, falling back to the first 200 characters of
    the body when no heading is present.  This avoids false positives
    where a model name appears as a substring deep in the body, for
    example ``codex/some-branch`` in a quoted git command or
    ``claude-mem`` in a file path.  Reviewers conventionally announce
    their identity in the comment's first heading.
    """
    candidate, _ = _first_heading_candidate(text)
    return _infer_surface_reviewer_from_candidate(candidate)


def _is_comment_grounded_on_head(
    comment: dict[str, Any],
    head_sha: str,
    head_committed_at: str,
) -> bool:
    """Return True when *comment* plausibly reviewed the current head.

    Implements the "grounded in the current head SHA" requirement of
    ``docs/REVIEW_AUTHORITY_PRINCIPLES.md``.  A comment is accepted when
    any of:

    * the caller did not supply head metadata (no-op for legacy paths);
    * the comment was posted at or after the head commit's timestamp;
    * the comment body explicitly cites the head SHA prefix (>= 7 chars).

    A comment whose ``createdAt`` predates the head commit and which
    does not cite the head SHA is treated as stale (it reviewed a
    superseded version of the diff) and excluded from quorum counting.
    """
    if not head_sha or not head_committed_at:
        return True
    body = str(comment.get("body", "") or "")
    head_short = head_sha[:7]
    if head_short and head_short in body:
        return True
    created = str(comment.get("createdAt", "") or "")
    if not created:
        # No timestamp on the comment — fall back to SHA-prefix evidence.
        # We have already established head_sha is set; absence of a
        # citation in body means the reviewer cannot be proven to have
        # seen this head, so the comment is treated as stale.
        return False
    return created >= head_committed_at


def _first_nonempty_line(text: str) -> str:
    for line in str(text).splitlines():
        stripped = line.strip("# ").strip()
        if stripped:
            return stripped
    return ""


def _matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in prefixes)


def _is_docs_tests_or_status_path(path: str) -> bool:
    return path.startswith(("docs/", "tests/")) or path in {
        "AGENTS.md",
        "CLAUDE.md",
        "README.md",
        "CHANGELOG.md",
        "GA_CHECKLIST.md",
    }


def _subsystem_for(path: str) -> str:
    """Map a file path to a coarse subsystem label for risk grouping."""
    parts = path.split("/")
    if not parts:
        return "(root)"
    top = parts[0]
    if top in ("aragora", "tests") and len(parts) >= 2:
        return f"{top}/{parts[1]}"
    if top in ("docs", "scripts", "sdk", "benchmarks", ".github"):
        return top
    return top


def _is_high_risk_path(path: str) -> bool:
    if path in HIGH_RISK_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in HIGH_RISK_PREFIXES)


def _parse_pr_number(pr_ref: str) -> int:
    text = str(pr_ref).strip()
    if "/" in text:
        text = text.rstrip("/").split("/")[-1]
    if text.startswith("#"):
        text = text[1:]
    try:
        return int(text)
    except ValueError as exc:
        raise _GhError(f"invalid PR ref: {pr_ref!r}") from exc


def _repo_from_url(url: str) -> str:
    text = str(url).strip().rstrip("/")
    parts = text.split("/")
    if len(parts) >= 5 and parts[2] == "github.com":
        return f"{parts[3]}/{parts[4]}"
    return ""


def _extract_validation_commands(body: str) -> list[str]:
    """Parse bullet lines from a conventional PR `## Validation` section."""
    lines: list[str] = []
    in_validation = False
    for raw_line in body.splitlines():
        line = raw_line.strip()
        lower = line.lower()
        if lower.startswith("## "):
            in_validation = lower == "## validation"
            continue
        if not in_validation:
            continue
        if line.startswith("### "):
            break
        if line.startswith("- ") or line.startswith("* "):
            lines.append(line[2:].strip())
    return lines


def _requested_action(args: argparse.Namespace) -> str:
    if bool(getattr(args, "approve", False)):
        return "approve"
    if bool(getattr(args, "request_changes", False)):
        return "request_changes"
    if bool(getattr(args, "defer", False)):
        return "defer"
    raise _GhError("no settlement action selected")


def _packet_sha(packet: ReviewPacket) -> str:
    payload = packet.to_dict()
    payload.pop("packet_sha", None)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _session_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def _review_queue_root(repo_root: Path) -> Path:
    return repo_root / REVIEW_QUEUE_ARTIFACT_DIR


def _session_receipt_path(repo_root: Path, session_id: str) -> Path:
    return _review_queue_root(repo_root) / "sessions" / f"{session_id}.json"


def _settlement_receipt_path(
    repo_root: Path,
    *,
    session_id: str,
    pr_number: int,
    action: str,
) -> Path:
    filename = f"pr-{pr_number}-{session_id}-{action}.json"
    return _review_queue_root(repo_root) / "receipts" / filename


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _require_clean_worktree(repo_root: Path) -> None:
    cmd = ["git", "status", "--porcelain"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=GIT_STATUS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise _GhError(
            f"git status timed out after {int(exc.timeout or GIT_STATUS_TIMEOUT_SECONDS)}s "
            f"in {repo_root}"
        ) from exc
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "no stderr"
        raise _GhError(f"git status failed in {repo_root}: {stderr}")
    if proc.stdout.strip():
        raise _GhError(
            "review-queue settlement requires a clean worktree so receipts match the reviewed truth"
        )


def _current_head_sha(pr_number: int, *, repo_override: str | None) -> str:
    args = ["pr", "view", str(pr_number), "--json", "headRefOid"]
    if repo_override:
        args.extend(["--repo", repo_override])
    payload = _gh_json(args)
    if not isinstance(payload, dict):
        raise _GhError(f"PR #{pr_number} not found while verifying packet freshness")
    return str(payload.get("headRefOid", "")).strip()


def _github_actor() -> str:
    try:
        payload = _gh_json(["api", "user"])
    except _GhError:
        return "unknown"
    if not isinstance(payload, dict):
        return "unknown"
    return str(payload.get("login", "unknown") or "unknown").strip()


def _github_settlement_event(action: str) -> str:
    if action == "approve":
        return "APPROVE"
    if action == "request_changes":
        return "REQUEST_CHANGES"
    return "COMMENT"


def _recorded_settlement_event(action: str) -> str:
    if action == "admin_squash_merge":
        return "ADMIN_SQUASH_MERGE"
    if action == "approve":
        return "RECORDED_EXTERNAL_APPROVE"
    if action == "request_changes":
        return "RECORDED_EXTERNAL_REQUEST_CHANGES"
    if action == "comment":
        return "RECORDED_EXTERNAL_COMMENT"
    raise _GhError(f"unsupported recorded settlement action: {action!r}")


def _settlement_body(packet: ReviewPacket, *, action: str, reason: str) -> str:
    lines = [
        "Human settlement via `aragora review-queue`.",
        "",
        f"- Action: `{action}`",
        f"- Packet SHA: `{packet.packet_sha}`",
        f"- Head SHA: `{packet.head_sha}`",
        f"- Base SHA: `{packet.base_sha}`",
        f"- Queue bucket: `{packet.queue_bucket}`",
        f"- Machine recommendation: `{packet.machine_recommendation}`",
    ]
    if reason:
        lines.append(f"- Reason: {reason}")
    lines.extend(
        [
            "",
            ADVISORY_NOTE,
        ]
    )
    return "\n".join(lines)


def _settle_packet(
    *,
    packet: ReviewPacket,
    action: str,
    reason: str,
    repo_root: Path,
    repo_override: str | None,
    session_id: str,
    elapsed_seconds: float | None = None,
) -> SettlementReceipt:
    current_head_sha = _current_head_sha(packet.pr_number, repo_override=repo_override)
    if current_head_sha != packet.head_sha:
        raise _GhError(
            f"PR #{packet.pr_number} head changed from {packet.head_sha} to {current_head_sha}; "
            "refresh the packet before settlement"
        )

    body = _settlement_body(packet, action=action, reason=reason)
    if action == "approve":
        gh_args = ["pr", "review", str(packet.pr_number), "--approve", "--body", body]
    elif action == "request_changes":
        gh_args = ["pr", "review", str(packet.pr_number), "--request-changes", "--body", body]
    else:
        gh_args = ["pr", "comment", str(packet.pr_number), "--body", body]
    if repo_override:
        gh_args.extend(["--repo", repo_override])
    _gh_text(gh_args)

    reviewed_at = datetime.now(UTC).isoformat()
    receipt = SettlementReceipt(
        session_id=session_id,
        reviewed_at=reviewed_at,
        actor=_github_actor(),
        action=action,
        reason=reason,
        pr_number=packet.pr_number,
        pr_url=packet.url,
        head_sha=packet.head_sha,
        base_sha=packet.base_sha,
        packet_sha=packet.packet_sha,
        queue_bucket=packet.queue_bucket,
        machine_recommendation=packet.machine_recommendation,
        github_event=_github_settlement_event(action),
        elapsed_seconds=elapsed_seconds,
    )
    receipt_path = _settlement_receipt_path(
        repo_root,
        session_id=session_id,
        pr_number=packet.pr_number,
        action=action,
    )
    receipt.receipt_path = str(receipt_path)
    _write_json(receipt_path, receipt.to_dict())
    return receipt


def _recorded_settlement_session_id(*, pr_number: int, head_sha: str, action: str) -> str:
    action_part = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in action)
    return f"recorded-{pr_number}-{head_sha[:12]}-{action_part}"


def _settlement_receipt_path_for_root(
    review_queue_root: Path,
    *,
    session_id: str,
    pr_number: int,
    action: str,
) -> Path:
    filename = f"pr-{pr_number}-{session_id}-{action}.json"
    return review_queue_root / "receipts" / filename


def _receipt_file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _recorded_packet_sha(
    *,
    pr_number: int,
    pr_url: str,
    head_sha: str,
    base_sha: str,
    action: str,
    reason: str,
    github_state: str,
    merged_at: str,
) -> str:
    payload = {
        "kind": "review_queue_recorded_external_settlement.v1",
        "pr_number": pr_number,
        "pr_url": pr_url,
        "head_sha": head_sha,
        "base_sha": base_sha,
        "action": action,
        "reason": reason,
        "github_state": github_state,
        "merged_at": merged_at,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _read_receipt_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _GhError(f"existing settlement receipt is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise _GhError(f"existing settlement receipt is not a JSON object: {path}")
    return payload


def _settlement_receipt_from_payload(payload: dict[str, Any]) -> SettlementReceipt:
    field_names = {f.name for f in SettlementReceipt.__dataclass_fields__.values()}
    return SettlementReceipt(**{k: v for k, v in payload.items() if k in field_names})


def _recorded_settlement_core(payload: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "session_id",
        "action",
        "reason",
        "pr_number",
        "pr_url",
        "head_sha",
        "base_sha",
        "packet_sha",
        "queue_bucket",
        "machine_recommendation",
        "github_event",
    }
    return {key: payload.get(key) for key in sorted(keys)}


def _resolve_review_queue_root_override(repo_root: Path, raw_root: str | Path | None) -> Path:
    if raw_root is None or str(raw_root).strip() == "":
        return _review_queue_root(repo_root)
    path = Path(raw_root).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return path


def _pr_view_for_recorded_settlement(
    pr_number: int,
    *,
    repo_override: str | None,
) -> dict[str, Any]:
    fields = "number,url,headRefOid,baseRefOid,state,mergedAt"
    args = ["pr", "view", str(pr_number), "--json", fields]
    if repo_override:
        args.extend(["--repo", repo_override])
    payload = _gh_json(args)
    if not isinstance(payload, dict):
        raise _GhError(f"PR #{pr_number} not found while recording settlement")
    return payload


def _record_external_settlement(
    *,
    pr_ref: str,
    head_sha: str,
    action: str,
    reason: str,
    repo_root: Path,
    repo_override: str | None,
    review_queue_root: str | Path | None,
    apply_post_merge_lane_audit: bool = False,
    post_merge_lane_audit_provider: PostMergeLaneAuditProvider | None = None,
) -> RecordedSettlementResult:
    pr_number = _parse_pr_number(pr_ref)
    expected_head_sha = str(head_sha or "").strip()
    if not expected_head_sha:
        raise _GhError("--head-sha is required")
    reason = str(reason or "").strip()
    if not reason:
        raise _GhError("--reason is required")
    github_event = _recorded_settlement_event(action)

    pr_payload = _pr_view_for_recorded_settlement(pr_number, repo_override=repo_override)
    current_head_sha = str(pr_payload.get("headRefOid", "") or "").strip()
    if current_head_sha != expected_head_sha:
        raise _GhError(
            f"PR #{pr_number} head changed from {expected_head_sha} to {current_head_sha}; "
            "record only the exact externally settled head"
        )
    github_state = str(pr_payload.get("state", "") or "").strip().upper()
    merged_at = str(pr_payload.get("mergedAt", "") or "").strip()
    if action == "admin_squash_merge" and github_state != "MERGED":
        raise _GhError(
            "admin_squash_merge records require the PR to be MERGED on GitHub; "
            f"current state is {github_state or 'unknown'}"
        )
    post_merge_lane_audit: dict[str, Any] | None = None
    if action == "admin_squash_merge":
        audit_provider = post_merge_lane_audit_provider
        if audit_provider is None:

            def audit_provider(pr: int, audit_apply: bool = False) -> dict[str, Any]:
                return run_post_merge_lane_audit(
                    pr,
                    repo_root=repo_root,
                    apply=audit_apply,
                )

        try:
            post_merge_lane_audit = audit_provider(pr_number, apply_post_merge_lane_audit)
        except Exception as exc:
            post_merge_lane_audit = {
                "audit_ok": False,
                "audit_applied": False,
                "audit_apply_requested": apply_post_merge_lane_audit,
                "audit_error": str(exc),
            }
    audit_failed = post_merge_lane_audit_failed(
        post_merge_lane_audit,
        apply_requested=apply_post_merge_lane_audit,
    )

    pr_url = str(pr_payload.get("url", "") or "").strip()
    base_sha = str(pr_payload.get("baseRefOid", "") or "").strip()
    packet_sha = _recorded_packet_sha(
        pr_number=pr_number,
        pr_url=pr_url,
        head_sha=expected_head_sha,
        base_sha=base_sha,
        action=action,
        reason=reason,
        github_state=github_state,
        merged_at=merged_at,
    )
    session_id = _recorded_settlement_session_id(
        pr_number=pr_number,
        head_sha=expected_head_sha,
        action=action,
    )
    reviewed_at = (
        merged_at.replace("Z", "+00:00")
        if action == "admin_squash_merge" and merged_at
        else datetime.now(UTC).isoformat()
    )
    receipt = SettlementReceipt(
        session_id=session_id,
        reviewed_at=reviewed_at,
        actor=_github_actor(),
        action=action,
        reason=reason,
        pr_number=pr_number,
        pr_url=pr_url,
        head_sha=expected_head_sha,
        base_sha=base_sha,
        packet_sha=packet_sha,
        queue_bucket="external_settlement",
        machine_recommendation="operator_recorded_external_settlement",
        github_event=github_event,
        post_merge_lane_audit=post_merge_lane_audit,
    )
    root = _resolve_review_queue_root_override(repo_root, review_queue_root)
    receipt_path = _settlement_receipt_path_for_root(
        root,
        session_id=session_id,
        pr_number=pr_number,
        action=action,
    )
    receipt.receipt_path = str(receipt_path)
    new_payload = receipt.to_dict()
    if receipt_path.exists():
        existing_payload = _read_receipt_payload(receipt_path)
        if _recorded_settlement_core(existing_payload) != _recorded_settlement_core(new_payload):
            raise _GhError(
                "conflicting settlement receipt already exists for "
                f"PR #{pr_number} head {expected_head_sha} action {action}: {receipt_path}"
            )
        existing_receipt = _settlement_receipt_from_payload(existing_payload)
        return RecordedSettlementResult(
            receipt=existing_receipt,
            receipt_sha256=_receipt_file_sha256(receipt_path),
            idempotent=True,
            written=False,
            post_merge_lane_audit=post_merge_lane_audit,
            post_merge_lane_audit_failed=audit_failed,
        )

    _write_json(receipt_path, new_payload)
    return RecordedSettlementResult(
        receipt=receipt,
        receipt_sha256=_receipt_file_sha256(receipt_path),
        idempotent=False,
        written=True,
        post_merge_lane_audit=post_merge_lane_audit,
        post_merge_lane_audit_failed=audit_failed,
    )


def _render_changed_files(pr_number: int, *, repo_override: str | None) -> None:
    args = ["pr", "view", str(pr_number), "--json", "files"]
    if repo_override:
        args.extend(["--repo", repo_override])
    payload = _gh_json(args)
    files = []
    if isinstance(payload, dict):
        for item in payload.get("files") or []:
            if isinstance(item, dict) and item.get("path"):
                files.append(str(item["path"]).strip())
    print("changed files:")
    for path in files:
        print(f"  - {path}")
    if not files:
        print("  (no changed files reported)")


# --- Rendering -------------------------------------------------------------


def _render_table(items: list[QueueItem]) -> None:
    if not items:
        print("(no PRs in scope)")
        return
    counts: dict[str, int] = {}
    for item in items:
        counts[item.lane] = counts.get(item.lane, 0) + 1
    lane_summary = ", ".join(f"{lane}={counts.get(lane, 0)}" for lane in LANE_ORDER)
    print(f"Review queue ({len(items)} PRs): {lane_summary}")
    _render_active_auto_handle_alerts()
    print()
    current_lane = ""
    for item in items:
        if item.lane != current_lane:
            current_lane = item.lane
            print(f"== {item.lane} ==")
        title_clip = item.title[:70]
        print(
            f"  #{item.number:>5}  {item.checks_summary:>20}  "
            f"+{item.additions:>5}/-{item.deletions:<5}  {title_clip}"
        )
        print(f"        {item.url}  [{item.lane_reason}]")
    print()
    print(
        "Note: machine review remains advisory only. Settlement writes are explicit "
        "human `gh pr review` / `gh pr comment` actions with local receipts."
    )


def _render_packet(packet: ReviewPacket) -> None:
    print(f"# Advisory review packet — PR #{packet.pr_number}")
    print(f"# {packet.title}")
    print(f"# {packet.url}")
    print()
    print(f"head SHA:        {packet.head_sha}")
    print(f"base SHA:        {packet.base_sha}")
    print(f"packet SHA:      {packet.packet_sha}")
    print(f"author:          {packet.author}")
    print(f"draft:           {packet.is_draft}")
    print(f"queue bucket:    {packet.queue_bucket}")
    print(
        f"diff:            +{packet.additions}/-{packet.deletions} "
        f"across {packet.changed_files} files"
    )
    print(f"checks:          {packet.checks_summary}")
    if packet.check_surfaces:
        rollup = packet.check_surfaces.get("pr_rollup") or {}
        direct = packet.check_surfaces.get("direct_commit_check_runs") or {}
        required = packet.check_surfaces.get("required_pr_checks") or {}
        print(
            "check surfaces:  "
            f"pr_rollup_available={str(bool(rollup.get('available'))).lower()} "
            f"pr_rollup_count={rollup.get('count')}"
        )
        if required:
            gate_selected = str(bool(required.get("gate_selected"))).lower()
            print(
                "                 "
                f"required_pr_checks={required.get('total', 0)} "
                f"summary={required.get('summary')} "
                f"gate_selected={gate_selected}"
            )
            gate_blocked_reason = str(required.get("gate_blocked_reason") or "").strip()
            if gate_blocked_reason:
                print(f"                 required_gate_blocker: {gate_blocked_reason}")
        non_required_rollup_sample = rollup.get("non_required_non_green_sample") or []
        if non_required_rollup_sample:
            print(
                "                 "
                "non_required_non_green_rollup="
                + ", ".join(str(item) for item in non_required_rollup_sample[:3])
            )
        optional_noise_sample = rollup.get("optional_runner_capacity_noise_sample") or []
        if optional_noise_sample:
            print(
                "                 "
                "optional_runner_capacity_noise="
                + ", ".join(str(item) for item in optional_noise_sample[:3])
            )
        long_queued_shadow_sample = (
            rollup.get("long_queued_self_hosted_shadow_without_runner_metadata_sample") or []
        )
        if long_queued_shadow_sample:
            print(
                "                 "
                "long_queued_self_hosted_shadow_without_runner_metadata="
                + ", ".join(str(item) for item in long_queued_shadow_sample[:3])
            )
        if direct:
            print(
                "                 "
                f"direct_commit_check_runs={direct.get('total', 0)} "
                f"successful_required={len(direct.get('successful_required_contexts') or [])}"
            )
        diagnosis = str(packet.check_surfaces.get("diagnosis") or "").strip()
        if diagnosis:
            print(f"                 diagnosis: {diagnosis}")
        remediation = str(packet.check_surfaces.get("remediation_prompt") or "").strip()
        if remediation:
            print(f"                 remediation: {remediation}")
    print()
    if packet.touched_subsystems:
        print("touched subsystems:")
        for sub in packet.touched_subsystems:
            print(f"  - {sub}")
        print()
    if packet.high_risk_paths_touched:
        print("HIGH-RISK PATHS TOUCHED:")
        for path in packet.high_risk_paths_touched:
            print(f"  - {path}")
        print()
    if packet.validation:
        print("validation:")
        for line in packet.validation:
            print(f"  - {line}")
        print()
    if packet.risk_flags:
        print("risk flags:")
        for flag in packet.risk_flags:
            print(f"  - {flag}")
        print()
    print(f"machine recommendation: {packet.machine_recommendation}")
    print(f"  reason: {packet.machine_recommendation_reason}")
    if packet.protocol:
        protocol = packet.protocol
        binding = protocol.get("binding") or {}
        cost_estimate = protocol.get("cost_estimate") or {}
        print()
        print("protocol:")
        print(
            f"  {protocol.get('protocol_version', 'unknown')} [{protocol.get('status', 'unknown')}]"
        )
        print(
            f"  binding: {binding.get('repo', '')} "
            f"PR #{binding.get('pr_number', packet.pr_number)} "
            f"{binding.get('base_sha', packet.base_sha)}..{binding.get('head_sha', packet.head_sha)}"
        )
        print(
            f"  confidence: {protocol.get('confidence', 0):.2f} "
            f"({protocol.get('confidence_basis', 'unknown')})"
        )
        print(f"  dissent: {protocol.get('dissent_summary', '')}")
        availability_summary = protocol.get("availability_summary") or {}
        if availability_summary:
            print(
                "  availability: "
                f"{availability_summary.get('resolved_slots', 0)}/"
                f"{availability_summary.get('total_slots', 0)} slots resolved"
            )
            unresolved_slots = availability_summary.get("unresolved_slots") or []
            if unresolved_slots:
                unresolved = ", ".join(str(slot) for slot in unresolved_slots)
                print(f"    unresolved: {unresolved}")
            opt_in_slots = availability_summary.get("opt_in_slots") or []
            if opt_in_slots:
                opt_in = ", ".join(str(slot) for slot in opt_in_slots)
                print(f"    opt-in: {opt_in}")
        print(
            f"  cost estimate: ${cost_estimate.get('low', 0):.2f}"
            f"-${cost_estimate.get('high', 0):.2f}"
        )
        top_findings = protocol.get("top_findings") or []
        if top_findings:
            print("  top findings:")
            for finding in top_findings[:3]:
                if not isinstance(finding, dict):
                    continue
                severity = str(finding.get("severity", "")).strip()
                summary = str(finding.get("summary", "")).strip()
                print(f"    - [{severity}] {summary}")
        provider_slots = protocol.get("provider_slots") or []
        if provider_slots:
            print("  provider slots:")
            for slot in provider_slots:
                if not isinstance(slot, dict):
                    continue
                selected = slot.get("selected_provider") or "unresolved"
                print(
                    f"    - {slot.get('slot_id')}: {selected} "
                    f"({slot.get('family')}/{slot.get('lens')})"
                )
    if packet.model_review_quorum:
        quorum = packet.model_review_quorum
        print()
        print("model review quorum:")
        print(f"  tier: Tier {quorum.get('tier')} ({quorum.get('tier_name', 'unknown')})")
        print(f"  status: {quorum.get('status', 'unknown')}")
        print(f"  verdict: {quorum.get('verdict', 'unknown')}")
        print(f"  admin squash allowed: {quorum.get('admin_squash_allowed', False)}")
        print(
            "  human risk settlement required: "
            f"{quorum.get('requires_human_risk_settlement', False)}"
        )
        print(
            "  signals: "
            f"{len(quorum.get('counted_reviewer_ids') or [])}/"
            f"{quorum.get('required_model_signals', 0)}"
        )
        if quorum.get("counted_reviewer_ids"):
            print(f"  counted reviewers: {', '.join(quorum.get('counted_reviewer_ids') or [])}")
        if quorum.get("unresolved_dissent"):
            print("  unresolved dissent: true")
        for reason in quorum.get("reasons") or []:
            print(f"    - {reason}")
    print()
    print(f"generated at: {packet.generated_at}")
    _render_active_auto_handle_alerts()
    print()
    print(f"-- {packet.settlement_note}")


def _render_session_packet(
    packet: ReviewPacket,
    *,
    item: QueueItem,
    index: int,
    total: int,
) -> None:
    print()
    print(f"[{index}/{total}] lane={item.lane}  reason={item.lane_reason}")
    _render_packet(packet)


def _render_settlement_receipt(receipt: SettlementReceipt) -> None:
    print(f"Recorded {receipt.action} for PR #{receipt.pr_number}")
    print(f"  actor:        {receipt.actor}")
    print(f"  reviewed at:  {receipt.reviewed_at}")
    print(f"  head SHA:     {receipt.head_sha}")
    print(f"  packet SHA:   {receipt.packet_sha}")
    print(f"  queue bucket: {receipt.queue_bucket}")
    print(f"  event:        {receipt.github_event}")
    if receipt.reason:
        print(f"  reason:       {receipt.reason}")
    if receipt.elapsed_seconds is not None:
        print(f"  elapsed:      {receipt.elapsed_seconds:.3f}s")
    print(f"  receipt:      {receipt.receipt_path}")


def _render_recorded_settlement_result(result: RecordedSettlementResult) -> None:
    _render_settlement_receipt(result.receipt)
    if result.post_merge_lane_audit is not None:
        audit = result.post_merge_lane_audit
        print("  post-merge lane audit:")
        print(f"    finding count: {audit.get('finding_count', 'unknown')}")
        print(f"    resolved count: {audit.get('resolved_count', 'unknown')}")
        if audit.get("blocked_reason"):
            print(f"    blocked:       {audit['blocked_reason']}")
        if result.post_merge_lane_audit_failed:
            print(f"    failed:        {post_merge_lane_audit_failure_reason(audit)}")
        if audit.get("operator_apply_command"):
            print(f"    apply command: {audit['operator_apply_command']}")
    print(f"  receipt sha:  {result.receipt_sha256}")
    print(f"  idempotent:   {str(result.idempotent).lower()}")
    print(f"  written:      {str(result.written).lower()}")


def _render_merge_authorization_packet(packet: dict[str, Any]) -> None:
    queue = packet.get("queue_pressure") or {}
    print("# Merge authorization packet")
    print(f"generated at: {packet.get('generated_at', '')}")
    print(
        "queue pressure: "
        f"{queue.get('current_open_prs', 0)} open / cap {queue.get('cap', MODEL_REVIEW_QUEUE_CAP)} "
        f"(active={queue.get('active', False)})"
    )
    if queue.get("active"):
        print(
            "new implementation PRs: frozen; only review/dogfood/fix-existing/spec-only work allowed"
        )
    print()
    print("authorization sentence:")
    print(packet.get("authorization_sentence", ""))
    print()

    admin_order = packet.get("admin_squash_order") or []
    human_required = packet.get("human_risk_settlement_required") or []
    not_ready = packet.get("not_ready") or []
    print(f"admin squash order: {', '.join(f'#{n}' for n in admin_order) or '(none)'}")
    print(
        f"human risk settlement required: {', '.join(f'#{n}' for n in human_required) or '(none)'}"
    )
    print(f"not ready: {', '.join(f'#{n}' for n in not_ready) or '(none)'}")
    print()

    for entry in packet.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        print(
            f"#{entry.get('pr_number')} | Tier {entry.get('tier')} | "
            f"{entry.get('status')} | {entry.get('verdict')}"
        )
        print(f"  {entry.get('title', '')}")
        print(f"  head: {entry.get('head_sha', '')}")
        print(f"  checks: {entry.get('checks_summary', '')}")
        surfaces = entry.get("check_surfaces") or {}
        if isinstance(surfaces, dict) and surfaces:
            rollup = surfaces.get("pr_rollup") or {}
            direct = surfaces.get("direct_commit_check_runs") or {}
            print(
                "  check surfaces: "
                f"pr_rollup_available={str(bool(rollup.get('available'))).lower()} "
                f"pr_rollup_count={rollup.get('count')}"
            )
            if direct:
                print(
                    "  direct checks: "
                    f"total={direct.get('total', 0)}, "
                    f"successful_required={len(direct.get('successful_required_contexts') or [])}, "
                    f"non_green={direct.get('non_green_count', 0)}"
                )
            remediation = str(surfaces.get("remediation_prompt") or "").strip()
            if remediation:
                print(f"  remediation: {remediation}")
        print(
            "  evidence: "
            f"{len(entry.get('reviewer_signals') or [])} reviewer signal(s), "
            f"{len(entry.get('dogfood_evidence') or [])} dogfood note(s), "
            f"{len(entry.get('counted_reviewer_ids') or [])} counted reviewer(s)"
        )
        gate_blockers = entry.get("admin_squash_gate_blockers") or []
        if gate_blockers:
            print("  admin squash live-gate blockers:")
            for blocker in gate_blockers:
                print(f"    - {blocker}")
        for reason in entry.get("reasons") or []:
            print(f"  - {reason}")
        print()


def _render_evidence_lint(result: dict[str, Any]) -> None:
    print("# Evidence lint")
    print(f"PR: #{result.get('pr_number', '')}")
    print(f"head: {result.get('head_sha', '')}")
    print(f"would count: {str(result.get('would_count', False)).lower()}")
    counted = result.get("counted_reviewer_ids") or []
    print(f"counted reviewers: {', '.join(counted) or '(none)'}")
    problems = result.get("problems") or []
    if problems:
        print("problems:")
        for problem in problems:
            print(f"  - {problem}")


def _render_baseline_report(
    *,
    measurement: BaselineMeasurement,
    proposal: ThresholdProposal,
) -> None:
    """Print a human-readable empirical-threshold baseline report."""
    print("# Empirical invalidation baseline (gap #6375)")
    print()
    print(f"window:       {measurement.window_start.isoformat()}")
    print(f"           -> {measurement.window_end.isoformat()}")
    print(f"              ({measurement.window_days}d)")
    print()
    print("samples:")
    print(
        f"  human-settled:   {measurement.invalidated_human_settled} invalidated "
        f"/ {measurement.total_human_settled} total"
    )
    print(
        f"  auto-handled:    {measurement.invalidated_auto_handled} invalidated "
        f"/ {measurement.total_auto_handled} total"
    )
    print(
        f"  min required:    {measurement.min_samples_required}  "
        f"(acceptable: {measurement.sample_size_acceptable})"
    )
    print()
    print("rates (with Wilson 95% CI):")
    print(
        "  human baseline:  "
        f"{_fmt_rate(measurement.baseline_human_rate)}  "
        f"[{_fmt_rate(measurement.baseline_human_rate_ci_low)}, "
        f"{_fmt_rate(measurement.baseline_human_rate_ci_high)}]"
    )
    print(
        "  auto-handle:     "
        f"{_fmt_rate(measurement.auto_handle_rate)}  "
        f"[{_fmt_rate(measurement.auto_handle_rate_ci_low)}, "
        f"{_fmt_rate(measurement.auto_handle_rate_ci_high)}]"
    )
    print()
    if measurement.per_class_human:
        print("per-class human breakdown (invalidated/total):")
        for cls, (inv, tot) in sorted(measurement.per_class_human.items()):
            print(f"  - {cls}: {inv}/{tot}")
        print()
    if measurement.per_class_auto:
        print("per-class auto-handle breakdown (invalidated/total):")
        for cls, (inv, tot) in sorted(measurement.per_class_auto.items()):
            print(f"  - {cls}: {inv}/{tot}")
        print()
    if measurement.notes:
        print("notes (data-availability caveats):")
        for key, note in sorted(measurement.notes.items()):
            print(f"  - {key}: {note}")
        print()
    print("proposed threshold:")
    print(f"  value:         {_fmt_rate(proposal.threshold)}")
    print(f"  baseline:      {_fmt_rate(proposal.baseline)}")
    print(f"  safety margin: {proposal.safety_margin:.2f}")
    print(f"  min meaningful rate: {proposal.minimum_meaningful_rate:.4f}")
    print(f"  placeholder:   {proposal.is_placeholder}")
    print(f"  rationale:     {proposal.rationale}")
    print(f"  measured at:   {proposal.measured_at.isoformat()}")
    print()
    print(
        "Note: this command is read-only and advisory. Applying the proposed "
        "threshold or persisting a recalibration receipt is the recalibration "
        "scheduler's job (#6375 step B), not this CLI."
    )


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4f} ({value:.2%})"


def _render_active_auto_handle_alerts() -> None:
    try:
        alerts = AutoHandleCalibrationStore().list_active_alerts(limit=3)
    except (OSError, RuntimeError, sqlite3.Error, ValueError, TypeError) as exc:
        print(f"warning: auto-handle calibration unavailable: {exc}", file=sys.stderr)
        return
    if not alerts:
        return
    print()
    print("ACTIVE AUTO-HANDLE DRIFT ALERTS:")
    for alert in alerts:
        current_rate = (
            f"{alert.current_success_rate:.1%}"
            if alert.current_success_rate is not None
            else "unknown"
        )
        print(
            f"  - {alert.auto_handle_path}: {alert.decision_class} "
            f"(success={current_rate}, action={alert.remediation_action})"
        )
